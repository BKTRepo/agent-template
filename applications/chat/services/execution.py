"""悬浮窗容器任务：异步启动、流式保存、取消以及代次校验。"""
import asyncio
import io
import json
import os
import shutil
import socket
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace

from tortoise.transactions import in_transaction

from applications.chat.models.chat_model import ChatArtifact, ChatConversation, ChatMessage, ChatSkillCall, ChatTask
from applications.chat.services.artifacts import artifact_root, count_cases
from applications.chat.services.attachments import stage_attachments, task_upload_dir, remove_task_uploads
from applications.chat.services.history_files import history_store, schedule_history, sync_history, write_history_events
from applications.knowledge_base.models.knowledge_base_model import Document
from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import SkillResourceBinding
from applications.wrq.agent.services.skill_catalog_service import SkillCatalogService
from applications.wrq.markdown_storage import read_markdown
from configure import LOGGER, PROJECT_CONFIG
from services.model_gateway import model_environment

_workers = set()
_prefix = 'CHAT_EVENT='
_suffixes = {'.txt', '.md', '.json', '.csv', '.xlsx', '.docx', '.pdf', '.py', '.js', '.sql', '.sh'}


def start_task(task_id):
    worker = asyncio.create_task(execute_task(task_id), name=f'chat-task-{task_id}')
    _workers.add(worker)
    worker.add_done_callback(_workers.discard)


async def build_request(task, conversation):
    user = await User.get(id=conversation.user_id)
    skills, knowledge_ids, packages = [], set(conversation.knowledge_bases or []), []
    for skill_id in conversation.skills or []:
        catalog = SkillCatalogService()
        skill, version, form = await catalog.published(skill_id, online=True)
        instructions = read_markdown(form.skill_markdown_path) if form.skill_markdown_path else form.instructions
        skills.append({'id': skill.id, 'name': form.name, 'description': form.description,
                       'instructions': instructions, 'resource_dir': f'/input/skills/{skill.id}'})
        if version.build_id:
            package_service, built, published_version = await catalog.package(skill.id, version.build_id, online=True)
            archive = package_service._published_archive(built, published_version.version)[0]
            packages.append((skill.id, built, archive))
        bindings = await SkillResourceBinding.filter(skill_version_id=version.id)
        for binding in bindings:
            if binding.source_type == 'knowledge_base' and binding.source_id:
                knowledge_ids.add(binding.source_id)
            elif binding.source_type == 'knowledge_document' and binding.source_id:
                document = await Document.get_or_none(id=binding.source_id, is_deleted=False)
                if document:
                    knowledge_ids.add(document.knowledge_base_id)
    knowledge = ''
    contents = await asyncio.to_thread(history_store().message_contents, conversation.user_id, conversation.id, task.generation)
    question = contents.get(task.user_message_id)
    if question is None:
        raise RuntimeError('用户消息正文不存在，请检查会话文件')
    if knowledge_ids:
        from applications.chat.services.retrieval import retrieve
        chunks = await retrieve(user, sorted(knowledge_ids), question)
        knowledge = '\n\n'.join(str(row.get('content', ''))[:3000] for row in chunks)[:24000]
    if await sync_history(conversation.user_id, conversation.id):
        events = await asyncio.to_thread(history_store().read, conversation.user_id, conversation.id)
        rows = [SimpleNamespace(**entry['data']) for entry in events if entry.get('type') == 'message'
                and entry['data']['id'] <= task.user_message_id
                and (not conversation.summary_message_id or entry['data']['id'] > conversation.summary_message_id)]
        rows.reverse()
    else:
        raise RuntimeError('会话文件不存在，无法加载上下文')
    messages, older, remaining = [], [], 40000
    for row in rows:
        if not row.content and row.role != 'user':
            continue
        content = row.content or '[用户上传了附件]'
        if older or len(content) > remaining:
            if row.id == task.user_message_id:
                raise ValueError('本次输入过长，请缩短后重试')
            older.append({'id': row.id, 'role': row.role, 'content': content})
            continue
        messages.append({'id': row.id, 'role': row.role, 'content': content})
        remaining -= len(content)
    metadata = next((entry['data'] for entry in events if entry.get('type') == 'created'), {})
    return {'model': task.model, 'skills': skills, 'knowledge': knowledge, 'messages': list(reversed(messages)),
            'summary': metadata.get('summary') or '', 'older_messages': list(reversed(older))}, packages


def stage_skill_packages(packages, input_dir):
    total = 0
    for skill_id, built, contents in packages:
        destination = input_dir / 'skills' / str(skill_id)
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            for item in built.get('files', []):
                relative = item.get('path', '')
                if item.get('document_id') is not None or relative in ('SKILL.md', 'manifest.json'):
                    continue
                path = PurePosixPath(relative)
                if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative:
                    raise ValueError('技能资源路径无效')
                info = archive.getinfo(f"{built['name']}/{relative}")
                total += info.file_size
                if total > 50 * 1024 * 1024:
                    raise ValueError('技能资源超过 50MB')
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)


async def _read_events(process, task, assistant_id, skill_ids, user_id):
    result, response, last_flush = None, '', 0.0
    while line := await process.stdout.readline():
        raw = line.decode('utf-8', errors='replace').strip()
        if not raw.startswith(_prefix):
            continue
        try:
            event = json.loads(raw[len(_prefix):])
        except (ValueError, TypeError):
            continue
        if event.get('type') == 'delta':
            text = event.get('text')
            if isinstance(text, str):
                first_delta = not response and bool(text)
                response += text
                if len(response) > 500000:
                    raise RuntimeError('回复超过长度上限')
                if (first_delta or time.monotonic() - last_flush >= 0.25) and \
                   await ChatTask.filter(id=task.id, status='running').exists():
                    async with in_transaction() as conn:
                        current = await ChatConversation.filter(id=task.conversation_id).using_db(conn).select_for_update().first()
                        if not current or current.state or current.generation != task.generation or not await ChatTask.filter(id=task.id, status='running').using_db(conn).exists():
                            continue
                        await write_history_events(user_id, task.conversation_id, [
                            {'type': 'message_content', 'generation': task.generation, 'message_id': assistant_id, 'content': response}])
                        if first_delta:
                            await ChatMessage.filter(id=assistant_id).using_db(conn).update(unread=True)
                    schedule_history(user_id, task.conversation_id)
                    last_flush = time.monotonic()
        elif event.get('type') == 'skill_call' and event.get('skill_id') in skill_ids:
            call_id = event.get('call_id')
            if isinstance(call_id, str) and len(call_id) <= 64:
                record, _ = await ChatSkillCall.get_or_create(call_id=call_id, defaults={'task_id': task.id, 'skill_id': event['skill_id']})
                if record.task_id != task.id or record.skill_id != event['skill_id']:
                    raise RuntimeError('技能调用标识冲突')
                process.stdin.write((json.dumps({'call_id': call_id}) + '\n').encode())
                await process.stdin.drain()
        elif event.get('type') == 'result':
            result = event.get('text') or response
            if not isinstance(result, str) or len(result) > 500000:
                raise RuntimeError('回复超过长度上限')
        elif event.get('type') == 'summary':
            text, until = event.get('text'), event.get('until')
            if isinstance(text, str) and isinstance(until, int) and len(text) <= 12000:
                async with in_transaction() as conn:
                    current = await ChatConversation.filter(id=task.conversation_id).using_db(conn).select_for_update().first()
                    if current and current.state == 0 and current.generation == task.generation and \
                       await ChatTask.filter(id=task.id, status='running').using_db(conn).exists():
                        await write_history_events(user_id, task.conversation_id, [
                            {'type': 'summary', 'generation': task.generation, 'content': text}])
                        current.summary_message_id = until
                        await current.save(using_db=conn, update_fields=['summary_message_id'])
                schedule_history(user_id, task.conversation_id)
    return result


async def _watch_cancel(process, task_id, container_name):
    ticks = 0
    while process.returncode is None:
        await asyncio.sleep(1)
        if not await ChatTask.filter(id=task_id, status='running').exists():
            stopper = await asyncio.create_subprocess_exec('docker', 'stop', '--time', '1', container_name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await stopper.wait()
            return
        ticks += 1
        if ticks % 10 == 0:
            await ChatTask.filter(id=task_id, status='running').update(heartbeat_at=datetime.now())


async def _remove_container(name):
    try:
        cleanup = await asyncio.create_subprocess_exec('docker', 'rm', '--force', name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(cleanup.communicate(), timeout=20)
        return cleanup.returncode == 0 or (cleanup.returncode == 1 and b'No such container' in stderr)
    except Exception:
        return False


async def recover_stale_tasks():
    cutoff = datetime.now() - timedelta(minutes=2)
    rows = await ChatTask.filter(status__in=['running', 'cancelling', 'recovering'],
        worker_host=socket.gethostname(), heartbeat_at__lt=cutoff).limit(50)
    for row in rows:
        if row.status != 'recovering':
            claimed = await ChatTask.filter(id=row.id, status=row.status, heartbeat_at=row.heartbeat_at).update(status='recovering')
            if not claimed:
                continue
        if await _remove_container(f'floating-chat-{row.id}'):
            work_root = (Path(PROJECT_CONFIG.OUTPUT_DATAGRAM_DIR).resolve() / 'chat_work').resolve()
            if work_root.is_dir():
                for path in work_root.glob(f'task-{row.id}-*'):
                    if not path.is_symlink() and path.is_dir() and path.resolve().is_relative_to(work_root):
                        await asyncio.to_thread(shutil.rmtree, path)
            conversation = await ChatConversation.get_or_none(id=row.conversation_id)
            cancelled = row.status == 'cancelling' or not conversation or conversation.state or conversation.generation != row.generation
            await ChatTask.filter(id=row.id, status='recovering').update(
                status='cancelled' if cancelled else 'failed', error=None if cancelled else '任务执行中断，请重试',
                finished_at=datetime.now())


async def execute_task(task_id):
    task = await ChatTask.get_or_none(id=task_id)
    if not task or (task.worker_host and task.worker_host != socket.gethostname()):
        return
    expects_uploads = bool(task.worker_host)
    if not await ChatTask.filter(id=task_id, status='pending').update(
            status='running', started_at=datetime.now(), heartbeat_at=datetime.now(), worker_host=socket.gethostname()):
        return
    process = watcher = None
    name = None
    temporary = None
    final_dir = None
    try:
        conversation = await ChatConversation.get(id=task.conversation_id)
        if conversation.state or conversation.generation != task.generation:
            raise RuntimeError('会话已清空')
        if expects_uploads and not task_upload_dir(task.id).is_dir():
            raise RuntimeError('临时附件已丢失，请重新上传')
        request, packages = await build_request(task, conversation)
        environment = model_environment(task.model)
        request['model'] = environment['ANTHROPIC_MODEL']
        work_root = Path(PROJECT_CONFIG.OUTPUT_DATAGRAM_DIR).resolve() / 'chat_work'
        work_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f'task-{task.id}-', dir=work_root))
        input_dir, output_dir = temporary / 'input', temporary / 'output'
        input_dir.mkdir(); output_dir.mkdir()
        await asyncio.to_thread(stage_skill_packages, packages, input_dir)
        request['attachments'] = await stage_attachments(task, input_dir)
        (input_dir / 'request.json').write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        sandbox = Path(__file__).resolve().parents[1] / 'sandbox'
        name = f'floating-chat-{task.id}'
        command = ['docker', 'run', '-i', '--rm', '--name', name, '--read-only', '--security-opt', 'no-new-privileges:true',
                   '--cap-drop', 'ALL', '--pids-limit', '128', '--memory', '1g', '--cpus', '1',
                   '--network', 'bridge', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                   '--mount', f'type=bind,src={sandbox},dst=/skill,readonly',
                   '--mount', f'type=bind,src={input_dir},dst=/input,readonly',
                   '--mount', f'type=bind,src={output_dir},dst=/output', '--workdir', '/skill',
                   '--env', 'HOME=/tmp', '--env', 'XDG_CACHE_HOME=/tmp/.cache',
                   '--env', 'XDG_CONFIG_HOME=/tmp/.config', '--env', 'XDG_DATA_HOME=/tmp/.local/share']
        if hasattr(os, 'getuid'):
            command += ['--user', f'{os.getuid()}:{os.getgid()}']
        for key in environment:
            command += ['--env', key]
        command += [os.environ.get('ZHAOYUNLONG_SANDBOX_IMAGE', 'test-case-sandbox:local'), 'python', 'run.py']
        if not await ChatTask.filter(id=task.id, status='running').exists():
            raise RuntimeError('任务已取消')
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env={**os.environ, **environment},
            limit=4 * 1024 * 1024)
        watcher = asyncio.create_task(_watch_cancel(process, task.id, name))
        answer = await _read_events(process, task, task.assistant_message_id, {s['id'] for s in request['skills']}, conversation.user_id)
        returncode = await process.wait()
        if returncode or answer is None:
            raise RuntimeError('模型容器未正常完成，请检查网关配置和容器日志')
        manifest_types = {}
        manifest_path = output_dir / '_artifacts.json'
        if manifest_path.is_file() and not manifest_path.is_symlink() and manifest_path.stat().st_size <= 65536:
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                for entry in manifest.get('artifacts', []):
                    if isinstance(entry, dict) and isinstance(entry.get('file_name'), str) and entry.get('type') in ('test_case', 'other'):
                        manifest_types[entry['file_name']] = entry['type']
            except (ValueError, AttributeError, TypeError):
                pass
        files = [p for p in output_dir.iterdir() if p.name != '_artifacts.json' and p.is_file()
                 and not p.is_symlink() and p.suffix.lower() in _suffixes]
        if len(files) > 20 or any(p.stat().st_size > 20 * 1024 * 1024 for p in files):
            raise RuntimeError('生成文件超过数量或大小限制')
        final_dir = artifact_root() / 'conversations' / conversation.id / str(task.generation) / str(task.id)
        final_dir.mkdir(parents=True, exist_ok=False)
        staged = []
        for file in files:
            filename = Path(file.name).name
            safe_name = uuid.uuid4().hex + file.suffix.lower()
            shutil.copyfile(file, final_dir / safe_name)
            key = (final_dir / safe_name).relative_to(artifact_root()).as_posix()
            kind = manifest_types.get(filename, 'other')
            if file.suffix.lower() == '.xlsx':
                try:
                    await asyncio.to_thread(count_cases, file)
                    kind = 'test_case'
                except Exception:
                    # 看似用例表但无法识别列时交由埋点重试与人工处理，不能按单个文件误算。
                    if '用例' in filename or 'testcase' in filename.lower().replace('_', '').replace('-', ''):
                        kind = 'test_case'
            elif kind == 'test_case':
                # 用例按 Excel 有效行统计，其他格式不能猜测条数。
                raise RuntimeError('测试用例产物必须使用 Excel 格式')
            staged.append((filename, key, kind))
        async with in_transaction() as conn:
            current = await ChatConversation.filter(id=conversation.id).using_db(conn).select_for_update().first()
            running = await ChatTask.filter(id=task.id, status='running').using_db(conn).select_for_update().first()
            if not current or current.state or current.generation != task.generation or not running:
                raise RuntimeError('会话已清空或任务已取消')
            existing = await ChatMessage.filter(id=task.assistant_message_id).using_db(conn).select_for_update().first()
            if existing:
                if not existing.unread and answer:
                    existing.unread = True
                await write_history_events(conversation.user_id, conversation.id, [
                    {'type': 'message_content', 'generation': task.generation, 'message_id': existing.id, 'content': answer}])
                await existing.save(using_db=conn, update_fields=['unread'])
            for filename, key, kind in staged:
                await ChatArtifact.create(task_id=task.id, file_name=filename, storage_key=key,
                                          artifact_type=kind, using_db=conn)
            running.status = 'success'; running.finished_at = datetime.now()
            await running.save(using_db=conn, update_fields=['status', 'finished_at'])
            final_dir = None
        schedule_history(conversation.user_id, conversation.id)
    except Exception as exc:
        LOGGER.warning('悬浮窗任务执行失败: task_id={}, type={}', task_id, type(exc).__name__)
        await ChatTask.filter(id=task_id, status='running').update(status='failed', error=str(exc)[:300], finished_at=datetime.now())
    finally:
        try:
            await asyncio.to_thread(remove_task_uploads, task_id)
        except OSError:
            LOGGER.warning('临时附件清理失败，等待后台重试: task_id={}', task_id)
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        cleanup_ok = True
        if process and name:
            cleanup_ok = await _remove_container(name)
        if cleanup_ok:
            await ChatTask.filter(id=task_id, status='cancelling').update(status='cancelled', finished_at=datetime.now())
        else:
            # 无法确认容器已经退出时保留工作目录，并交给同主机的恢复任务重试。
            await ChatTask.filter(id=task_id, status__in=['failed', 'cancelling']).update(
                status='recovering', heartbeat_at=datetime.now() - timedelta(minutes=3),
                worker_host=socket.gethostname(), error='容器清理未完成，等待恢复')
            temporary = None
        if final_dir and final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        if temporary and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
