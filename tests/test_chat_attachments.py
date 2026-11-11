"""临时附件只供单次任务使用，结束后清理且不增加数据库表。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

for key, value in {'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
                   'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
                   'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test'}.items():
    os.environ[key] = value

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise
from applications.chat.models.chat_model import ChatTask
from applications.chat.services.attachments import stage_attachments, task_upload_dir
from applications.chat.services.execution import execute_task
from applications.chat.views import chat_router
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG
from services.dependency import AuthControl


class TemporaryAttachmentTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = patch.object(PROJECT_CONFIG, 'OUTPUT_DATAGRAM_DIR', self.temp.name)
        self.config.start()
        self.history_config = patch.object(PROJECT_CONFIG, 'CHAT_HISTORY_DIR', str(Path(self.temp.name) / 'history'))
        self.history_config.start()
        await Tortoise.init(db_url='sqlite://:memory:', modules={'models': [
            'applications.user.models.user_model', 'applications.chat.models.chat_model',
            'applications.wrq.agent.models.agent_model', 'applications.knowledge_base.models.knowledge_base_model',
            'applications.knowledge_base.models.rag_document_model']})
        await Tortoise.generate_schemas()
        self.user = await User.create(username='alice', password='x', alias='Alice', email='a@example.com')
        self.other = await User.create(username='bob', password='x', alias='Bob', email='b@example.com')
        self.current_user = self.user
        app = FastAPI()
        app.include_router(chat_router, prefix='/chat')
        async def auth():
            return self.current_user
        app.dependency_overrides[AuthControl.is_authed] = auth
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        from applications.chat.services.history_files import close_history_workers
        await close_history_workers()
        await self.client.aclose()
        await Tortoise.close_connections()
        self.history_config.stop()
        self.config.stop()
        self.temp.cleanup()

    async def test_send_failure_retry_and_stop_remove_files(self):
        chat_id = (await self.client.post('/chat/conversation/create', json={})).json()['data']['id']
        with patch('applications.chat.views.chat_view.start_task'), \
             patch('applications.chat.views.chat_view.model_environment', return_value={'ANTHROPIC_MODEL': 'test'}):
            sent = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id, 'content': '分析'},
                                          files=[('files', ('需求.txt', b'hello', 'text/plain'))])
        self.assertEqual(sent.status_code, 200, sent.text)
        task = await ChatTask.get(id=sent.json()['data']['task_id'])
        self.assertTrue(task_upload_dir(task.id).exists())
        dest = Path(self.temp.name) / 'input'
        entries = await stage_attachments(task, dest)
        self.assertEqual(entries[0]['file_name'], '需求.txt')
        self.assertEqual((dest / 'attachments' / '0' / '需求.txt').read_bytes(), b'hello')
        with patch('applications.chat.services.execution.build_request', new=AsyncMock(side_effect=RuntimeError('失败'))):
            await execute_task(task.id)
        await task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertFalse(task_upload_dir(task.id).exists())
        self.current_user = self.other
        denied = await self.client.post('/chat/retry-with-files', data={'task_id': task.id}, files={'files': ('a.txt', b'x')})
        self.assertEqual(denied.status_code, 404)
        self.current_user = self.user
        with patch('applications.chat.views.chat_view.start_task'):
            retried = await self.client.post('/chat/retry-with-files', data={'task_id': task.id},
                                             files={'files': ('新附件.txt', b'new')})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertTrue(retried.json()['data']['attachments_supplied'])
        retry_id = retried.json()['data']['task_id']
        self.assertTrue(task_upload_dir(retry_id).exists())
        stopped = await self.client.post('/chat/stop', json={'task_id': retry_id})
        self.assertEqual(stopped.status_code, 200)
        self.assertFalse(task_upload_dir(retry_id).exists())
        history = (await self.client.get('/chat/message/list', params={'conversation_id': chat_id})).json()['data']
        self.assertNotIn('attachments', history[0])

    async def test_validation_does_not_leave_files(self):
        chat_id = (await self.client.post('/chat/conversation/create', json={})).json()['data']['id']
        self.current_user = self.other
        denied = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id}, files={'files': ('a.txt', b'x')})
        self.assertEqual(denied.status_code, 404)
        self.current_user = self.user
        with patch('applications.chat.services.attachments.MAX_FILE_SIZE', 2):
            large = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id}, files={'files': ('a.txt', b'123')})
        self.assertEqual(large.status_code, 413)
        invalid = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id}, files={'files': ('bad.exe', b'x')})
        self.assertEqual(invalid.status_code, 400)
        root = Path(self.temp.name) / 'chat_uploads'
        self.assertFalse(root.exists() and list(root.iterdir()))

    async def test_file_only_and_upload_cleanup_after_rejected_task(self):
        chat_id = (await self.client.post('/chat/conversation/create', json={})).json()['data']['id']
        with patch('applications.chat.views.chat_view.start_task'), \
             patch('applications.chat.views.chat_view.model_environment', return_value={'ANTHROPIC_MODEL': 'test'}):
            first = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id}, files={'files': ('a.txt', b'a')})
            second = await self.client.post('/chat/send-with-files', data={'conversation_id': chat_id}, files={'files': ('b.txt', b'b')})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409)
        paths = list((Path(self.temp.name) / 'chat_uploads').iterdir())
        self.assertEqual(len(paths), 1)
