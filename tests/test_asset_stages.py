import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from tortoise import Tortoise
from tortoise.timezone import now

from configure import PROJECT_CONFIG
from services import AuthControl
from applications.conversation.models.asset_model import Asset
from applications.conversation.services import asset_service as service
from applications.conversation.services.asset_source import SourceSnapshot
from applications.conversation.views.asset_view import asset_router, ArchiveRequest
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, TestStage
from applications.wrq.agent.schemas.skill_class_schema import SkillClassCreate, SkillClassUpdate, SkillClassRemove
from applications.wrq.agent.services.skill_class_service import SkillClassService


class AssetStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await Tortoise.init(db_url='sqlite://:memory:', modules={'models': [
            'applications.wrq.agent.models.agent_model', 'applications.user.models.user_model',
            'applications.conversation.models.asset_model']})
        await Tortoise.generate_schemas()
        for number, (code, name) in enumerate([
            ('planning', '测试规划'), ('design', '测试设计'), ('data', '数据准备'),
            ('execution', '测试执行'), ('measurement', '测试度量'), ('support', '测试支撑'),
            ('management', '测试管理')], 1):
            await TestStage.create(id=number, code=code, name=name, sort_order=number)
        self.user = SimpleNamespace(id=1, username='qa1', alias='QA')
        self.quantity = patch('applications.conversation.services.asset_quantity.content_quantity', return_value='0')
        self.quantity.start()

    async def asyncTearDown(self):
        self.quantity.stop()
        await Tortoise.close_connections()

    async def kind(self, name, stage):
        return await DeveloperSkillClass.create(name=name, test_stage_id=stage, description='说明',
            publication_status='PUBLISHED', published_revision=1,
            published_content={'name': name, 'test_stage_id': stage, 'description': '说明'})

    async def asset(self, kind, name, *, owner=1, public=False, recycled=False):
        return await Asset.create(name=name, skill_classes_id=kind.id, application_identify='app', created_by=owner,
            visibility='platform' if public else 'private', source_artifact_id=name,
            deleted_at=now() if recycled else None)

    async def test_counts_merge_classes_by_stage_and_respect_visibility_and_recycle(self):
        a, b, c, legacy = [await self.kind(name, stage) for name, stage in [('A', 2), ('B', 2), ('C', 3), ('旧类', None)]]
        first = await self.asset(a, 'asset-A')
        second = await self.asset(b, 'asset-B', owner=2, public=True)
        await self.asset(a, 'hidden', owner=2)
        await self.asset(c, 'data')
        await self.asset(a, 'recycled', recycled=True)
        await self.asset(legacy, 'legacy')
        overview = await service.overview(self.user)
        self.assertEqual(len(overview['test_stages']), 7)
        self.assertEqual(overview['total'], 4)
        self.assertEqual(overview['recycle_count'], 1)
        self.assertEqual(overview['unassigned_count'], 1)
        self.assertEqual([row['count'] for row in overview['test_stages']], [0, 2, 1, 0, 0, 0, 0])
        result = await service.list_page(self.user, 1, '', None, 'desc', False, test_stage_id=2)
        self.assertEqual({row['id'] for row in result['items']}, {first.id, second.id})
        self.assertEqual({row['class_name'] for row in result['items']}, {'A', 'B'})
        searched = await service.list_page(self.user, 1, 'asset-B', None, 'desc', False, test_stage_id=2)
        self.assertEqual([row['id'] for row in searched['items']], [second.id])
        self.assertEqual((await service.list_page(self.user, 1, '', c.id, 'desc', False, test_stage_id=2))['total'], 0)

    async def test_stage_filter_pagination_and_deleted_class_keep_existing_assets(self):
        kind = await self.kind('测试类', 4)
        for i in range(12):
            await self.asset(kind, f'asset-{i}')
        await DeveloperSkillClass.filter(id=kind.id).update(state=1)
        first = await service.list_page(self.user, 1, '', None, 'asc', False, test_stage_id=4)
        second = await service.list_page(self.user, 2, '', None, 'asc', False, test_stage_id=4)
        self.assertEqual((first['total'], len(first['items']), len(second['items']), second['pages']), (12, 10, 2, 2))
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
        self.assertEqual((await service.overview(self.user))['test_stages'][3]['count'], 12)

    async def test_draft_name_and_stage_only_take_effect_after_republish(self):
        classes = SkillClassService()
        values = dict(name='旧名称', test_stage_id=2, description='说明', input_description='输入', output_description='输出', template='# 模板')
        draft = await classes.create(SkillClassCreate(**values), self.user)
        row = await classes.publish(SkillClassRemove(class_id=draft['id'], expected_revision=draft['revision']), self.user)
        kind = await DeveloperSkillClass.get(id=row['id'])
        await self.asset(kind, 'history')
        edited = await classes.update(SkillClassUpdate(**{**values, 'name': '新名称', 'test_stage_id': 3},
            class_id=row['id'], expected_revision=row['revision']), self.user)
        self.assertEqual((await service.overview(self.user))['test_stages'][1]['count'], 1)
        old = await service.list_page(self.user, 1, '', None, 'desc', False, test_stage_id=2)
        self.assertEqual(old['items'][0]['class_name'], '旧名称')
        self.assertEqual((await service.list_page(self.user, 1, '', None, 'desc', False, test_stage_id=3))['total'], 0)
        await classes.publish(SkillClassRemove(class_id=row['id'], expected_revision=edited['revision']), self.user)
        overview = await service.overview(self.user)
        self.assertEqual([row['count'] for row in overview['test_stages']][1:3], [0, 1])
        new = await service.list_page(self.user, 1, '', None, 'desc', False, test_stage_id=3)
        self.assertEqual(new['items'][0]['class_name'], '新名称')

    async def test_archive_counts_once_and_recycle_restore_update_stage(self):
        kind = await self.kind('归档类', 3)
        data = ArchiveRequest(artifact_id='artifact-1', base_hash='a' * 64, name='测试产物',
                              skill_classes_id=kind.id, application_identify='app')
        with tempfile.TemporaryDirectory(prefix='asset-stage-') as directory, \
             patch.object(PROJECT_CONFIG, 'OUTPUT_DIR', directory), \
             patch('applications.conversation.services.asset_service.validate_application_async', AsyncMock()), \
             patch('applications.conversation.services.asset_service.source_snapshot', AsyncMock(return_value=SourceSnapshot('test.txt', b'test'))):
            saved = await service.archive(self.user, data)
            self.assertTrue(saved['included'])
            self.assertEqual((await service.archive(self.user, data))['asset_id'], saved['asset_id'])
            self.assertEqual((await service.overview(self.user))['test_stages'][2]['count'], 1)
            await service.change_recycle_state(self.user, [saved['asset_id']], restore=False)
            overview = await service.overview(self.user)
            self.assertEqual((overview['total'], overview['test_stages'][2]['count'], overview['recycle_count']), (0, 0, 1))
            await service.change_recycle_state(self.user, [saved['asset_id']], restore=True)
            self.assertEqual((await service.overview(self.user))['test_stages'][2]['count'], 1)

    async def test_http_stage_query_is_validated_and_overview_has_seven_stages(self):
        kind = await self.kind('阶段类', 5)
        await self.asset(kind, 'asset')
        app = FastAPI()
        app.include_router(asset_router)
        app.dependency_overrides[AuthControl.is_authed] = lambda: self.user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            overview = (await client.get('/api/assets/overview')).json()['data']
            self.assertEqual(len(overview['test_stages']), 7)
            self.assertEqual(overview['test_stages'][4]['count'], 1)
            self.assertEqual((await client.get('/api/assets/list?test_stage_id=5')).json()['data']['total'], 1)
            self.assertEqual((await client.get('/api/assets/list?test_stage_id=2')).json()['data']['total'], 0)
            for value in ['0', '-1', 'abc']:
                self.assertEqual((await client.get('/api/assets/list', params={'test_stage_id': value})).status_code, 422)
