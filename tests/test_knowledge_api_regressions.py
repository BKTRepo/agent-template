"""隔离验证知识库字符串 ID、增量更新及技能挂载。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, Skill, SkillForm, SkillVersion, SkillResourceBinding
from applications.knowledge_base.models.knowledge_base_model import Document
from applications.knowledge_base.services.document_pipeline import DocumentPipeline
from applications.knowledge_base.services.platform_service import KnowledgeService, get_knowledge_service
from applications.knowledge_base.views import knowledge_router
from configure import PROJECT_CONFIG
from enums import DocumentStatus
from services import AuthControl


class FakeIndex:
    def __init__(self):
        self.rows = {}
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        return [[0.2, 0.5, 0.3] for _ in texts]

    async def put(self, kb_id, rows):
        self.rows.update({row['vector_id']: row for row in rows})

    async def remove(self, ids):
        for key in ids:
            self.rows.pop(key, None)


class KnowledgeApiRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kb-regression-')
        self.patches = [patch.object(PROJECT_CONFIG, 'OUTPUT_UPLOAD_DIR', str(Path(self.temp.name) / 'upload')),
                        patch.object(PROJECT_CONFIG, 'SKILL_BUILD_DIR', str(Path(self.temp.name) / 'build')),
                        patch.object(PROJECT_CONFIG, 'KNOWLEDGE_TASK_MODE', 'inline')]
        for item in self.patches:
            item.start()
        await Tortoise.init(db_url='sqlite://:memory:', modules={'models': [
            'applications.user.models.user_model', 'applications.wrq.agent.models.agent_model',
            'applications.knowledge_base.models.knowledge_base_model']})
        await Tortoise.generate_schemas()
        self.user = await User.create(username='kbowner', alias='Owner', email='kbowner@example.com', password='unused')
        self.index = FakeIndex()
        self.service = KnowledgeService(DocumentPipeline(self.index))
        app = FastAPI()
        app.include_router(knowledge_router, prefix='/knowledge-bases')
        app.dependency_overrides[AuthControl.is_authed] = lambda: self.user
        app.dependency_overrides[get_knowledge_service] = lambda: self.service
        self.client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await Tortoise.close_connections()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_create_edit_and_mount_string_id(self):
        form = {'knowledge_name': '规则库', 'description': '业务规则', 'tag': 'custom', 'application': '*', 'is_public': False}
        response = await self.client.post('/knowledge-bases/', data={'source': json.dumps(form)},
                                          files=[('files', ('rules.md', b'# Rules\ncontent'))])
        self.assertEqual(response.status_code, 200, response.text)
        kb = response.json()['data']
        self.assertEqual(kb['version'], 'V1.0.0')
        self.assertEqual(self.index.calls, 1)
        kb_id = kb['id']
        detail = await self.client.get(f'/knowledge-bases/{kb_id}')
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['reference_count'], 0)
        edit = await self.client.put(f'/knowledge-bases/{kb_id}',
                                     data={'source': json.dumps({**form, 'description': '补充说明', 'change_summary': '修改说明'})})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(edit.json()['data']['version'], 'V1.0.1')
        self.assertEqual(self.index.calls, 1)
        await DeveloperSkillClass.create(id=1, name='测试类')
        skill = await Skill.create(id='skill-one', name='测试技能', create_user_login_name=self.user.username,
                                   update_user_login_name=self.user.username, skill_classes_id=1)
        version = await SkillVersion.create(skill_id=skill.id, version='1.0.0', revision=1,
                                            create_user_login_name=self.user.username)
        await SkillForm.create(skill_version_id=version.id, name=skill.name, skill_class_id=1,
                               description='测试说明', instructions='执行测试')
        skill.current_version_id = version.id
        await skill.save(update_fields=['current_version_id'])
        mounted = await self.client.post(f'/knowledge-bases/{kb_id}/mounts',
                                         json={'skill_ids': [skill.id], 'resource_usage': '读取规则'})
        self.assertEqual(mounted.status_code, 200, mounted.text)
        self.assertEqual(mounted.json()['data']['items'][0]['status'], 'succeeded', mounted.text)
        await skill.refresh_from_db()
        self.assertTrue(await SkillResourceBinding.filter(skill_version_id=skill.current_version_id,
                                                         source_type='knowledge_base', source_id=kb_id).exists())
        detail = await self.client.get(f'/knowledge-bases/{kb_id}')
        self.assertEqual(detail.json()['data']['reference_count'], 1)
        self.assertEqual(await Document.filter(knowledge_base_id=kb_id).count(), 1)
        document = await Document.filter(knowledge_base_id=kb_id).first()
        document.status = DocumentStatus.FAILED
        await document.save(update_fields=['status'])
        blocked = await self.client.post(f'/knowledge-bases/{kb_id}/mounts',
                                         json={'skill_ids': [skill.id], 'resource_usage': '读取规则'})
        self.assertEqual(blocked.status_code, 409, blocked.text)

    async def test_add_file_only_reprocesses_new_document(self):
        form = {'knowledge_name': '增量库', 'description': '业务规则', 'tag': 'custom', 'application': '*', 'is_public': True}
        response = await self.client.post('/knowledge-bases/', data={'source': json.dumps(form)},
                                          files=[('files', ('first.txt', b'first document'))])
        self.assertEqual(response.status_code, 200, response.text)
        kb_id = response.json()['data']['id']
        response = await self.client.put(f'/knowledge-bases/{kb_id}',
                                         data={'source': json.dumps({**form, 'change_summary': '新增文件'})},
                                         files=[('files', ('second.txt', b'second document'))])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['data']['version'], 'V1.0.1')
        self.assertEqual(response.json()['data']['document_count'], 2)
        self.assertEqual(self.index.calls, 2)


if __name__ == '__main__':
    unittest.main()
