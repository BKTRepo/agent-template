"""独立 SQLite 验证悬浮窗权限、清空与产物计数。"""
import os
import tempfile
import unittest
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch

for key, value in {
    'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
    'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
    'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test',
}.items():
    os.environ[key] = value

from fastapi import HTTPException
from openpyxl import Workbook
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from tortoise import Tortoise
from applications.chat.models.chat_model import ChatArtifact, ChatArtifactCount, ChatCleanup, ChatConversation, ChatMessage, ChatTask
from applications.chat.services.chat_service import clear_conversation, require_conversation
from applications.chat.services.artifacts import count_artifact, count_cases
from applications.chat.services.cleanup import process_cleanup
from applications.chat.services.execution import build_request, execute_task
from applications.user.models.user_model import User
from applications.chat.views import chat_router
from services.dependency import AuthControl


class ChatFoundationTest(unittest.IsolatedAsyncioTestCase):
    async def prepare_history(self, conversation, *messages):
        from applications.chat.services.history_files import history_store, write_history_events
        store = history_store()
        store.ensure(conversation.user_id, conversation.id, {'generation': conversation.generation})
        await write_history_events(conversation.user_id, conversation.id, [
            {'type': 'message_content', 'generation': conversation.generation, 'message_id': row.id, 'content': content}
            for row, content in messages])

    async def asyncSetUp(self):
        self.history_dir = tempfile.TemporaryDirectory()
        self.history_config = patch('applications.chat.services.history_files.PROJECT_CONFIG.CHAT_HISTORY_DIR', self.history_dir.name)
        self.history_config.start()
        await Tortoise.init(db_url='sqlite://:memory:', modules={'models': [
            'applications.user.models.user_model', 'applications.chat.models.chat_model',
            'applications.wrq.agent.models.agent_model',
            'applications.knowledge_base.models.knowledge_base_model',
            'applications.knowledge_base.models.rag_document_model']})
        await Tortoise.generate_schemas()

    async def asyncTearDown(self):
        from applications.chat.services.history_files import close_history_workers
        await close_history_workers()
        await Tortoise.close_connections()
        self.history_config.stop()
        self.history_dir.cleanup()

    async def test_clear_and_access(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        other = await User.create(username='bob', password='x', alias='Bob', email='bob@example.com')
        conversation = await ChatConversation.create(user_id=user.id, skills=[1], knowledge_bases=[2], summary='old')
        message = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='hello')
        task = await ChatTask.create(conversation_id=conversation.id, generation=1, user_message_id=message.id, status='running')
        with self.assertRaises(HTTPException):
            await require_conversation(conversation.id, other.id)
        await clear_conversation(conversation.id, user.id)
        await conversation.refresh_from_db()
        await task.refresh_from_db()
        self.assertEqual(conversation.generation, 2)
        self.assertEqual((conversation.skills, conversation.knowledge_bases, conversation.summary_message_id), ([], [], None))
        self.assertEqual(task.status, 'cancelling')
        self.assertFalse(await ChatMessage.filter(conversation_id=conversation.id, generation=2).exists())
        self.assertTrue(await ChatCleanup.filter(conversation_id=conversation.id, generation=1, status='pending').exists())

    async def test_excel_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.xlsx'
            book = Workbook()
            sheet = book.active
            sheet.append(['测试用例'])
            sheet.append(['用例编号', '描述'])
            sheet.append(['A001', '第一条'])
            sheet.append([None, '空行不算'])
            sheet.append(['A002', '第二条'])
            book.save(path)
            self.assertEqual(count_cases(path), 2)

    async def test_api_history_feedback_and_clear(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        app = FastAPI()
        app.include_router(chat_router, prefix='/chat')
        async def auth():
            return user
        app.dependency_overrides[AuthControl.is_authed] = auth
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/chat/conversation/create', json={'title': '登录测试'})
            self.assertEqual(response.status_code, 200, response.text)
            chat_id = response.json()['data']['id']
            message = await ChatMessage.create(conversation_id=chat_id, generation=1,
                                               role='assistant', content='生成结果', unread=True)
            await self.prepare_history(await ChatConversation.get(id=chat_id), (message, '生成结果'))
            response = await client.post('/chat/feedback', json={'message_id': message.id,
                                                                  'rating': 'dislike', 'reason': '内容不对'})
            self.assertEqual(response.status_code, 200, response.text)
            response = await client.get('/chat/conversation/list')
            self.assertEqual(response.json()['data'][0]['unread_count'], 1)
            response = await client.get('/chat/conversation/list', params={'search': '生成结果'})
            self.assertEqual(len(response.json()['data']), 1)
            response = await client.post('/chat/conversation/clear', json={'conversation_id': chat_id})
            self.assertEqual(response.status_code, 200, response.text)
            response = await client.get('/chat/message/list', params={'conversation_id': chat_id})
            self.assertEqual(response.json()['data'], [])
            response = await client.get('/chat/conversation/list', params={'search': '生成结果'})
            self.assertEqual(response.json()['data'], [])
            response = await client.post('/chat/feedback', json={'message_id': message.id, 'rating': 'like'})
            self.assertEqual(response.status_code, 404)

    async def test_jsonl_projection_recovers_and_clears(self):
        from applications.chat.services.history_files import history_store, sync_history, close_history_workers, write_history_events
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        app = FastAPI()
        app.include_router(chat_router, prefix='/chat')
        async def auth():
            return user
        app.dependency_overrides[AuthControl.is_authed] = auth
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            chat_id = (await client.post('/chat/conversation/create', json={'title': '会话'})).json()['data']['id']
            store = history_store()
            self.assertEqual(store.list_ids(user.id), [chat_id])
            with patch('applications.chat.views.chat_view.start_task'), \
                 patch('applications.chat.views.chat_view.model_environment', return_value={'ANTHROPIC_MODEL': 'test'}):
                sent = await client.post('/chat/send', json={'conversation_id': chat_id, 'content': '问题'})
            self.assertEqual(sent.status_code, 200, sent.text)
            task = await ChatTask.get(id=sent.json()['data']['task_id'])
            conversation = await ChatConversation.get(id=chat_id)
            request, _ = await build_request(task, conversation)
            self.assertEqual(request['messages'][-1]['content'], '问题')
            from tortoise import connections
            columns = await connections.get('default').execute_query_dict('PRAGMA table_info(chat_messages)')
            self.assertNotIn('content', [column['name'] for column in columns])
            conversation_columns = await connections.get('default').execute_query_dict('PRAGMA table_info(chat_conversations)')
            self.assertNotIn('summary', [column['name'] for column in conversation_columns])
            self.assertIn('history_path', [column['name'] for column in conversation_columns])
            await write_history_events(user.id, chat_id, [{'type': 'message_content', 'generation': 1, 'message_id': task.assistant_message_id, 'content': '回答'}])
            await ChatMessage.filter(id=task.assistant_message_id).update(unread=True)
            await sync_history(user.id, chat_id)
            events = store.read(user.id, chat_id)
            self.assertEqual([e['data']['content'] for e in events if e['type'] == 'message'], ['问题', '回答'])
            await write_history_events(user.id, chat_id, [{'type': 'message_content', 'generation': 1, 'message_id': task.assistant_message_id, 'content': '恢复后的回答'}])
            await sync_history(user.id, chat_id)
            loaded = (await client.get('/chat/message/list', params={'conversation_id': chat_id})).json()['data']
            self.assertEqual(loaded[-1]['content'], '恢复后的回答')
            await ChatTask.filter(id=task.id).update(status='success')
            cleared = await client.post('/chat/conversation/clear', json={'conversation_id': chat_id})
            self.assertEqual(cleared.status_code, 200, cleared.text)
            await close_history_workers()
            self.assertFalse(any(e['type'] == 'message' for e in store.read(user.id, chat_id)))
            deleted = await client.post('/chat/conversation/delete', json={'conversation_id': chat_id})
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertEqual(store.list_ids(user.id), [])

    async def test_send_stop_retry_and_permissions(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        app = FastAPI()
        app.include_router(chat_router, prefix='/chat')
        async def auth():
            return user
        app.dependency_overrides[AuthControl.is_authed] = auth
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            chat_id = (await client.post('/chat/conversation/create', json={})).json()['data']['id']
            with patch('applications.chat.views.chat_view.start_task') as start, \
                 patch('applications.chat.views.chat_view.model_environment', return_value={'ANTHROPIC_MODEL': 'test'}):
                sent = await client.post('/chat/send', json={'conversation_id': chat_id, 'content': '生成用例'})
                self.assertEqual(sent.status_code, 200, sent.text)
                task_id = sent.json()['data']['task_id']
                start.assert_called_once_with(task_id)
                concurrent = await client.post('/chat/send', json={'conversation_id': chat_id, 'content': '第二条'})
                self.assertEqual(concurrent.status_code, 409)
                stopped = await client.post('/chat/stop', json={'task_id': task_id})
                self.assertEqual(stopped.json()['data']['status'], 'cancelled')
                retried = await client.post('/chat/retry', json={'task_id': task_id})
                self.assertEqual(retried.status_code, 200, retried.text)
                task = await ChatTask.get(id=retried.json()['data']['task_id'])
                self.assertEqual(task.retry_of_task_id, task_id)
                self.assertEqual(task.user_message_id, (await ChatTask.get(id=task_id)).user_message_id)
                self.assertEqual(await ChatMessage.filter(conversation_id=chat_id, role='assistant').count(), 1)

    async def test_configured_model_is_listed_and_accepted(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        app = FastAPI()
        app.include_router(chat_router, prefix='/chat')
        async def auth():
            return user
        app.dependency_overrides[AuthControl.is_authed] = auth
        registry = '[{"id":"custom-model","name":"自定义模型","direct_model":"actual-name"}]'
        values = {'CHAT_MODEL_REGISTRY': registry, 'ANTHROPIC_BASE_URL': 'https://test', 'ANTHROPIC_API_KEY': 'key'}
        with patch.dict(os.environ, {}, clear=True), patch('services.model_gateway.dotenv_values', return_value=values), \
             patch('applications.chat.views.chat_view.start_task'):
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                models = await client.get('/chat/models')
                self.assertEqual(models.json()['data'], [{'name': 'custom-model', 'display_name': 'actual-name'}])
                chat_id = (await client.post('/chat/conversation/create', json={})).json()['data']['id']
                invalid = await client.post('/chat/send', json={'conversation_id': chat_id, 'content': 'hello', 'model': 'unknown'})
                self.assertEqual(invalid.status_code, 400)
                sent = await client.post('/chat/send', json={'conversation_id': chat_id, 'content': 'hello', 'model': 'custom-model'})
                self.assertEqual(sent.status_code, 200, sent.text)
                task = await ChatTask.get(id=sent.json()['data']['task_id'])
                self.assertEqual(task.model, 'custom-model')

    async def test_milvus_fallback_keeps_scope(self):
        pool = types.ModuleType('applications.knowledge_base.processing.milvus_pool')
        pool.get_milvus_client_pool = lambda **kwargs: None
        with patch.dict(sys.modules, {'applications.knowledge_base.processing.milvus_pool': pool}):
            milvus_store = importlib.import_module('applications.knowledge_base.rag.milvus_store')
        captured = {}
        def dense(vectors, top_k=60, *, filter_expr=''):
            captured['filter'] = filter_expr
            return []
        with patch.object(milvus_store, 'AnnSearchRequest', side_effect=lambda **kw: kw, create=True), \
             patch.object(milvus_store, '_run_milvus_read_with_retry', side_effect=RuntimeError('failed')), \
             patch.object(milvus_store, 'query_chunks', side_effect=dense):
            milvus_store.hybrid_query_chunks([[0.1]], '登录', filter_expr='doc_id in ["doc-a"]')
        self.assertEqual(captured['filter'], 'doc_id in ["doc-a"]')

    async def test_cleanup_preserves_statistics(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='旧消息')
        await ChatArtifactCount.create(artifact_id=123, quantity=5)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old = root / 'conversations' / conversation.id / '1'
            old.mkdir(parents=True)
            (old / 'case.xlsx').write_text('test')
            await clear_conversation(conversation.id, user.id)
            record = await ChatCleanup.get(conversation_id=conversation.id, generation=1)
            with patch('applications.chat.services.cleanup.artifact_root', return_value=root):
                await process_cleanup(record.id)
            await record.refresh_from_db()
            self.assertFalse(old.exists(), record.error)
            self.assertFalse(await ChatMessage.filter(conversation_id=conversation.id, generation=1).exists())
            self.assertEqual((await ChatArtifactCount.get(artifact_id=123)).quantity, 5)

    async def test_count_is_idempotent(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        message = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='生成')
        task = await ChatTask.create(conversation_id=conversation.id, generation=1,
                                     user_message_id=message.id, status='success')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.xlsx'
            book = Workbook()
            book.active.append(['用例编号'])
            book.active.append(['001'])
            book.active.append(['002'])
            book.save(path)
            artifact = await ChatArtifact.create(task_id=task.id, file_name='cases.xlsx',
                                                 storage_key='cases.xlsx', artifact_type='test_case')
            with patch('applications.chat.services.artifacts.artifact_root', return_value=Path(directory).resolve()):
                await count_artifact(artifact.id)
                await count_artifact(artifact.id)
            await artifact.refresh_from_db()
            self.assertEqual(artifact.count_status, 'counted')
            self.assertEqual(await ChatArtifactCount.filter(artifact_id=artifact.id).count(), 1)
            self.assertEqual((await ChatArtifactCount.get(artifact_id=artifact.id)).quantity, 2)

    async def test_long_history_is_marked_for_summary(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        earlier = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='assistant', content='旧' * 30000)
        latest = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='新' * 20000)
        await self.prepare_history(conversation, (earlier, '旧' * 30000), (latest, '新' * 20000))
        task = await ChatTask.create(conversation_id=conversation.id, generation=1, user_message_id=latest.id, model='deepseek')
        request, _ = await build_request(task, conversation)
        self.assertEqual([item['id'] for item in request['older_messages']], [earlier.id])
        self.assertEqual(request['messages'][0]['content'], '新' * 20000)

    async def test_container_result_saved_and_skill_counted(self):
        import json
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        question = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='生成')
        assistant = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='assistant', content='')
        await self.prepare_history(conversation, (question, '生成'), (assistant, ''))
        task = await ChatTask.create(conversation_id=conversation.id, generation=1, user_message_id=question.id,
                                     assistant_message_id=assistant.id, model='deepseek')
        request = {'model': 'deepseek', 'skills': [{'id': 7}], 'knowledge': '', 'messages': []}
        events = [{'type': 'skill_call', 'skill_id': 7, 'call_id': 'call-1'},
                  {'type': 'delta', 'text': '已完成'}, {'type': 'result', 'text': '已完成'}]
        class Stream:
            async def readline(self):
                return ('CHAT_EVENT=' + json.dumps(events.pop(0)) + '\n').encode() if events else b''
        class Process:
            def __init__(self, output=False):
                self.stdout = Stream() if output else None
                self.stdin = self
                self.returncode = 0
            def write(self, data):
                pass
            async def drain(self):
                pass
            async def wait(self):
                return 0
        async def launch(*args, **kwargs):
            if args[1] == 'run':
                mount = next(value for value in args if isinstance(value, str) and value.endswith(',dst=/output'))
                output = Path(mount.split('src=', 1)[1].split(',dst=', 1)[0])
                (output / 'script.py').write_text('print(1)')
                return Process(output=True)
            return Process()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch('applications.chat.services.execution.build_request', return_value=(request, [])), \
                 patch('applications.chat.services.execution.model_environment', return_value={'ANTHROPIC_MODEL': 'deepseek'}), \
                 patch('applications.chat.services.execution.artifact_root', return_value=root), \
                 patch('applications.chat.services.execution.PROJECT_CONFIG.OUTPUT_DATAGRAM_DIR', str(root)), \
                 patch('applications.chat.services.execution._remove_container', return_value=True), \
                 patch('applications.chat.services.execution.asyncio.create_subprocess_exec', side_effect=launch):
                await execute_task(task.id)
            await task.refresh_from_db(); await assistant.refresh_from_db()
            from applications.chat.services.history_files import history_store
            self.assertEqual((task.status, history_store().message_contents(user.id, conversation.id, 1)[assistant.id], assistant.unread), ('success', '已完成', True))
            self.assertEqual(await ChatArtifact.filter(task_id=task.id).count(), 1)
            from applications.chat.models.chat_model import ChatSkillCall
            self.assertTrue(await ChatSkillCall.filter(task_id=task.id, skill_id=7).exists())

    async def test_clear_during_execution_blocks_late_answer(self):
        import json
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        question = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='生成')
        assistant = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='assistant', content='')
        await self.prepare_history(conversation, (question, '生成'), (assistant, ''))
        task = await ChatTask.create(conversation_id=conversation.id, generation=1, user_message_id=question.id,
                                     assistant_message_id=assistant.id, model='deepseek')
        request = {'model': 'deepseek', 'skills': [], 'knowledge': '', 'messages': []}
        class Stream:
            sent = False
            async def readline(self):
                if self.sent:
                    return b''
                self.sent = True
                await clear_conversation(conversation.id, user.id)
                return ('CHAT_EVENT=' + json.dumps({'type': 'result', 'text': '旧结果'}) + '\n').encode()
        class Process:
            stdout = Stream()
            returncode = 0
            async def wait(self):
                return 0
        async def launch(*args, **kwargs):
            return Process()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch('applications.chat.services.execution.build_request', return_value=(request, [])), \
                 patch('applications.chat.services.execution.model_environment', return_value={'ANTHROPIC_MODEL': 'deepseek'}), \
                 patch('applications.chat.services.execution.artifact_root', return_value=root), \
                 patch('applications.chat.services.execution.PROJECT_CONFIG.OUTPUT_DATAGRAM_DIR', str(root)), \
                 patch('applications.chat.services.execution._remove_container', return_value=True), \
                 patch('applications.chat.services.execution.asyncio.create_subprocess_exec', side_effect=launch):
                await execute_task(task.id)
            await task.refresh_from_db(); await assistant.refresh_from_db()
            self.assertEqual(task.status, 'cancelled')
            from applications.chat.services.history_files import history_store
            self.assertEqual(history_store().message_contents(user.id, conversation.id, 1).get(assistant.id), '')
            self.assertFalse(assistant.unread)
            self.assertEqual(await ChatArtifact.filter(task_id=task.id).count(), 0)

    async def test_cleanup_retains_count_failure_reason(self):
        user = await User.create(username='alice', password='x', alias='Alice', email='alice@example.com')
        conversation = await ChatConversation.create(user_id=user.id)
        question = await ChatMessage.create(conversation_id=conversation.id, generation=1, role='user', content='生成')
        task = await ChatTask.create(conversation_id=conversation.id, generation=1, user_message_id=question.id, status='success')
        artifact = await ChatArtifact.create(task_id=task.id, file_name='用例.xlsx', storage_key='x',
            artifact_type='test_case', count_status='needs_review', count_error='未找到用例编号列')
        await clear_conversation(conversation.id, user.id)
        record = await ChatCleanup.get(conversation_id=conversation.id, generation=1)
        with tempfile.TemporaryDirectory() as directory, \
             patch('applications.chat.services.cleanup.artifact_root', return_value=Path(directory).resolve()):
            await process_cleanup(record.id)
        metric = await ChatArtifactCount.get(artifact_id=artifact.id)
        self.assertEqual((metric.status, metric.quantity, metric.error), ('failed', None, '未找到用例编号列'))
        self.assertFalse(await ChatArtifact.filter(id=artifact.id).exists())

if __name__ == '__main__':
    unittest.main()
