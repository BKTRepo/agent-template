"""悬浮窗会话 JSONL 正文与数据库索引同步。"""
import json
import os
import re
import tempfile
import asyncio
import weakref
from datetime import date, datetime
from pathlib import Path

from filelock import FileLock
import portalocker

from applications.chat.models.chat_model import ChatConversation, ChatFeedback, ChatMessage
from configure import LOGGER, PROJECT_CONFIG


class HistoryFileStore:
    """追加事件并以操作系统文件锁保护同一会话的读写。"""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, user_id, conversation_id):
        uid = str(user_id)
        if not uid.isdecimal() or not re.fullmatch(r'[0-9a-f]{32}', conversation_id):
            raise ValueError('会话标识无效')
        return self.root / uid / f'{conversation_id}.jsonl'

    def ensure(self, user_id, conversation_id, metadata):
        """幂等创建会话文件；已有文件不会被覆盖。"""
        path = self._path(user_id, conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + '.lock'):
            if path.exists():
                return False
            with path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps({'type': 'created', 'data': metadata}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        return True

    def read(self, user_id, conversation_id):
        path = self._path(user_id, conversation_id)
        if not path.parent.is_dir():
            raise FileNotFoundError('会话不存在')
        with FileLock(str(path) + '.lock'):
            if not path.is_file():
                raise FileNotFoundError('会话不存在')
            with path.open(encoding='utf-8') as stream:
                return [json.loads(line) for line in stream if line.strip()]

    def append_many(self, user_id, conversation_id, events):
        """在同一把文件锁下写入一批消息事件。"""
        path = self._path(user_id, conversation_id)
        if not path.parent.is_dir():
            raise FileNotFoundError('会话不存在')
        lines = []
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get('type'), str):
                raise ValueError('事件格式无效')
            lines.append(json.dumps(event, ensure_ascii=False) + '\n')
        with FileLock(str(path) + '.lock'):
            if not path.is_file():
                raise FileNotFoundError('会话不存在')
            with path.open('a', encoding='utf-8') as stream:
                stream.writelines(lines)
                stream.flush()
                os.fsync(stream.fileno())

    def message_contents(self, user_id, conversation_id, generation):
        """读取当前代次的最后一次正文；消息状态由索引层校验。"""
        contents = {}
        current_generation = None
        for entry in self.read(user_id, conversation_id):
            if entry.get('type') == 'created':
                current_generation = entry.get('data', {}).get('generation')
            if entry.get('type') == 'message' and current_generation == generation:
                row = entry.get('data', {})
                contents[row['id']] = row.get('content', '')
            if entry.get('type') == 'message_content' and entry.get('generation') == generation:
                contents[entry['message_id']] = entry['content']
        return contents

    def replace(self, user_id, conversation_id, events):
        """清空或更新会话时，先落盘到同目录临时文件再原子替换。"""
        path = self._path(user_id, conversation_id)
        if not path.parent.is_dir():
            raise FileNotFoundError('会话不存在')
        with FileLock(str(path) + '.lock'):
            if not path.is_file():
                raise FileNotFoundError('会话不存在')
            fd, name = tempfile.mkstemp(prefix='.history-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    for event in events:
                        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
                            raise ValueError('事件格式无效')
                        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, path)
            finally:
                Path(name).unlink(missing_ok=True)

    def delete(self, user_id, conversation_id):
        path = self._path(user_id, conversation_id)
        if not path.parent.is_dir():
            raise FileNotFoundError('会话不存在')
        with FileLock(str(path) + '.lock'):
            if not path.is_file():
                raise FileNotFoundError('会话不存在')
            path.unlink()

    def list_ids(self, user_id):
        uid = str(user_id)
        if not uid.isdecimal():
            raise ValueError('用户标识无效')
        directory = self.root / uid
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob('*.jsonl')
                      if path.is_file() and re.fullmatch(r'[0-9a-f]{32}', path.stem))


def history_store():
    return HistoryFileStore(PROJECT_CONFIG.CHAT_HISTORY_DIR or Path(__file__).resolve().parents[1] / 'chat_history')


def _json_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


_async_locks = weakref.WeakValueDictionary()


async def sync_history(user_id, conversation_id, *, create=False):
    # 先读数据库，再持有文件锁；否则消息事务持有数据库锁时会与文件投影互相等待。
    conversation = await ChatConversation.get_or_none(id=conversation_id, user_id=user_id)
    rows, feedback = [], []
    if conversation and not conversation.state:
        rows = await ChatMessage.filter(conversation_id=conversation_id,
            generation=conversation.generation).order_by('id').values('id', 'role', 'unread', 'created_time')
        feedback = await ChatFeedback.filter(message_id__in=[row['id'] for row in rows]).values(
            'message_id', 'rating', 'reason', 'created_time', 'updated_time')
    key = (int(user_id), conversation_id)
    lock = _async_locks.setdefault(key, asyncio.Lock())
    async with lock:
        return await _sync_history_locked(user_id, conversation_id, conversation, rows, feedback, create=create)


async def _sync_history_locked(user_id, conversation_id, conversation, rows, feedback, *, create=False):
    """合并数据库消息状态与 JSONL 正文，不能从数据库恢复正文。"""
    store = history_store()
    path = store._path(user_id, conversation_id)
    if not create and not path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # 在多个进程中串行化投影，避免较旧快照覆盖较新快照。
    lock = portalocker.Lock(str(path) + '.projection.lock', mode='a', timeout=30)
    await asyncio.to_thread(lock.acquire)
    try:
        if not conversation or conversation.state:
            if path.is_file():
                await asyncio.to_thread(store.delete, user_id, conversation_id)
            return False
        if not create and not path.is_file():
            return False
        previous = await asyncio.to_thread(store.read, user_id, conversation_id) if path.is_file() else []
        existing_generation = next((e.get('data', {}).get('generation') for e in previous if e.get('type') == 'created'), None)
        if existing_generation is not None and existing_generation > conversation.generation:
            return True
        contents, summary, previous_generation = {}, '', None
        for entry in previous:
            if entry.get('type') == 'created':
                previous_generation = entry.get('data', {}).get('generation')
                if previous_generation == conversation.generation:
                    summary = entry.get('data', {}).get('summary') or ''
            elif entry.get('type') == 'message' and previous_generation == conversation.generation:
                row = entry['data']; contents[row['id']] = row.get('content', '')
            elif entry.get('type') == 'message_content' and entry.get('generation') == conversation.generation:
                contents[entry['message_id']] = entry['content']
            elif entry.get('type') == 'summary' and entry.get('generation') == conversation.generation:
                summary = entry['content']
        if any(row['id'] not in contents for row in rows):
            raise RuntimeError('会话文件缺少消息正文，不能从数据库恢复')
        events = [{'type': 'created', 'data': {'conversation_id': conversation.id,
                   'user_id': conversation.user_id, 'generation': conversation.generation,
                   'title': conversation.title, 'favorite': conversation.favorite,
                   'model': conversation.model, 'skills': conversation.skills,
                   'knowledge_bases': conversation.knowledge_bases,
                   'summary': summary, 'summary_message_id': conversation.summary_message_id}}]
        events.extend({'type': 'message', 'data': {**{key: _json_value(value) for key, value in row.items()},
                      'content': contents.get(row['id'], '')}} for row in rows)
        # 数据库事务可能尚未提交；保留文件已写入但索引尚不可见的正文。
        visible_ids = {row['id'] for row in rows}
        events.extend({'type': 'message_content', 'generation': conversation.generation,
                       'message_id': msg_id, 'content': content}
                      for msg_id, content in contents.items() if msg_id not in visible_ids)
        events.extend({'type': 'feedback', 'data': {key: _json_value(value) for key, value in row.items()}} for row in feedback)
        if create:
            await asyncio.to_thread(store.ensure, user_id, conversation_id, events[0]['data'])
        await asyncio.to_thread(store.replace, user_id, conversation_id, events)
        return True
    finally:
        await asyncio.to_thread(lock.release)


async def write_history_events(user_id, conversation_id, events):
    """与快照同步共用锁，避免并发覆盖新正文。"""
    key = (int(user_id), conversation_id)
    guard = _async_locks.setdefault(key, asyncio.Lock())
    async with guard:
        store = history_store()
        path = store._path(user_id, conversation_id)
        lock = portalocker.Lock(str(path) + '.projection.lock', mode='a', timeout=30)
        await asyncio.to_thread(lock.acquire)
        try:
            await asyncio.to_thread(store.append_many, user_id, conversation_id, events)
        finally:
            await asyncio.to_thread(lock.release)


_projection_dirty = set()
_projection_workers = {}


def schedule_history(user_id, conversation_id):
    """合并连续更新；异常时等待后续更新或后台巡检重试。"""
    key = (int(user_id), conversation_id)
    _projection_dirty.add(key)
    if key in _projection_workers:
        return

    async def worker():
        try:
            while key in _projection_dirty:
                _projection_dirty.discard(key)
                await sync_history(*key)
        except Exception:
            LOGGER.exception('悬浮窗历史文件同步失败: conversation_id={}', conversation_id)
        finally:
            _projection_workers.pop(key, None)
            if key in _projection_dirty:
                schedule_history(*key)

    _projection_workers[key] = asyncio.create_task(worker(), name=f'chat-history-{conversation_id}')


async def resync_histories():
    """同步已有 JSONL 的索引状态；正文丢失时无法由数据库恢复。"""
    store = history_store()
    if not store.root.is_dir():
        return
    for directory in store.root.iterdir():
        if not directory.is_dir() or not directory.name.isdecimal():
            continue
        for conversation_id in store.list_ids(directory.name):
            try:
                await sync_history(int(directory.name), conversation_id)
            except Exception:
                LOGGER.exception('悬浮窗历史文件恢复失败: conversation_id={}', conversation_id)


async def close_history_workers():
    workers = list(_projection_workers.values())
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
    _async_locks.clear()
