"""计数使用真实SQL事务；Docker执行器仅为显式替身。"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from tortoise.expressions import F

from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillResourceBinding, SkillDebugRun, SkillPublication
from applications.wrq.agent.schemas.agent_schema import DeveloperSkillForm, OfflineSkillRequest
from applications.wrq.agent.services.developer_service_v2 import DeveloperSkillCrud
from applications.zhaoyunlong.models.online_debug_run_model import OnlineDebugRun
from applications.zhaoyunlong.services.online_debug_run_service import OnlineDebugRunService
from applications.wrq.auth import PlatformIdentity
from test_skill_catalog_flow import catalog_flow, seed


@pytest.mark.asyncio
async def test_call_creation_is_atomic_idempotent_and_uses_server_snapshot(catalog_flow, monkeypatch):
    client, kind, tmp_path = catalog_flow
    skill, version, _ = await seed(kind, build=True, tmp_path=tmp_path)
    received = []
    async def execute(record_id, run_id, payload, owner_id):
        received.append(payload)
        await OnlineDebugRun.filter(id=record_id).update(status='failed', error_message='Explicit test failure')
    monkeypatch.setattr(OnlineDebugRunService, '_execute', execute)
    source = {'skill_id': skill.id, 'build_id': version.build_id, 'request_id': 'a' * 32, 'conversation_input': 'Generate tests'}
    before = (skill.updated_time, skill.current_revision, skill.display_status, skill.update_user_login_name)
    response = await client.post('/skills/catalog/create-test-run', data={'source': json.dumps(source), 'skill_definition': 'forged content'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['run_id'] == source['request_id']
    await asyncio.gather(*list(OnlineDebugRunService._tasks))
    again = await client.post('/skills/catalog/create-test-run', data={'source': json.dumps(source)})
    assert again.status_code == 200
    assert len(received) == 1 and 'forged' not in received[0]['skill_definition']
    assert '# Immutable published resource' in received[0]['mounted_resources'][0]['content']
    await skill.refresh_from_db()
    assert skill.call_count == 1 and skill.download_count == 0
    assert before == (skill.updated_time, skill.current_revision, skill.display_status, skill.update_user_login_name)
    assert await SkillDebugRun.filter(run_id=source['request_id']).count() == 1
    for _ in range(3):
        assert (await client.get('/skills/catalog/get-skill', params={'skill_id': skill.id})).json()['data']['call_count'] == 1
    assert (await OnlineDebugRun.get(run_id=source['request_id'])).status == 'failed'
    assert await SkillPublication.all().count() == 0


@pytest.mark.asyncio
async def test_failed_counter_transaction_leaves_no_job_or_link(catalog_flow, monkeypatch):
    client, kind, tmp_path = catalog_flow
    skill, version, _ = await seed(kind, build=True, tmp_path=tmp_path)
    execute = AsyncMock()
    monkeypatch.setattr(OnlineDebugRunService, '_execute', execute)
    monkeypatch.setattr(SkillDebugRun, 'create', AsyncMock(side_effect=RuntimeError('Explicit SQL failure')))
    with pytest.raises(RuntimeError, match='Explicit SQL failure'):
        await client.post('/skills/catalog/create-test-run', data={'source': json.dumps({
            'skill_id': skill.id, 'build_id': version.build_id, 'request_id': 'b' * 32, 'conversation_input': 'Run'})})
    assert await OnlineDebugRun.all().count() == 0
    assert await SkillDebugRun.all().count() == 0
    assert (await Skill.get(id=skill.id)).call_count == 0
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_atomic_increments_survive_stale_save_and_business_lifecycle(catalog_flow):
    _, kind, _ = catalog_flow
    skill, _, _ = await seed(kind)
    stale = await Skill.get(id=skill.id)
    await asyncio.gather(*(Skill.filter(id=skill.id).update(call_count=F('call_count') + 1, download_count=F('download_count') + 1) for _ in range(25)))
    stale.name = 'Changed metadata'
    await stale.save()
    current = await Skill.get(id=skill.id)
    assert current.call_count == current.download_count == 25
    user = PlatformIdentity(1, 'owner', 'Owner', login_name='owner')
    crud = DeveloperSkillCrud(sandbox=type('Sandbox', (), {'get': AsyncMock(return_value={'status': 'PASSED'})})())
    await crud.offline(skill.id, user, OfflineSkillRequest(reason_code='ABILITY_DEFECT'))
    saved = await crud.save(skill.id, user, DeveloperSkillForm(expected_revision=1, name='Changed metadata', class_id=kind.id,
        description='Keep stats', instructions='Generate tests'))
    assert saved.id == skill.id and saved.current_revision == 2
    version = await SkillVersion.get(id=saved.current_version_id)
    version.build_id = 'test-fixed-build'
    await version.save(update_fields=['build_id'])
    await SkillDebugRun.create(skill_id=skill.id, skill_version_id=version.id, run_id='test-owner-run', build_id=version.build_id, create_user_login_name='owner')
    await crud.publish(skill.id, user)
    current = await Skill.get(id=skill.id)
    assert current.display_status == 'ONLINE' and current.current_revision == 2
    assert current.call_count == current.download_count == 25


@pytest.mark.asyncio
async def test_download_count_excludes_resources_previews_and_failures(catalog_flow):
    client, kind, tmp_path = catalog_flow
    skill, version, _ = await seed(kind, build=True, tmp_path=tmp_path)
    params = {'skill_id': skill.id, 'build_id': version.build_id}
    updated = skill.updated_time
    await client.get('/skills/catalog/get-build', params=params)
    await client.get('/skills/catalog/download-resource', params={**params, 'path': 'references/rules.md'})
    assert (await client.get('/skills/catalog/download-skill', params={**params, 'build_id': 'wrong'})).status_code == 409
    assert (await Skill.get(id=skill.id)).download_count == 0
    assert (await client.get('/skills/catalog/download-skill', params=params)).status_code == 200
    assert (await client.get('/skills/catalog/download-skill', params=params)).status_code == 200
    after = await Skill.get(id=skill.id)
    assert after.download_count == 2 and after.updated_time == updated and after.call_count == 0


@pytest.mark.asyncio
async def test_integer_models_match_live_identifier_columns(catalog_flow):
    _, kind, _ = catalog_flow
    skill, version, _ = await seed(kind)
    assert isinstance(skill.id, int) and isinstance(version.skill_id, int)
    link = await SkillResourceBinding.create(skill_id=skill.id, skill_version_id=version.id, source_type='knowledge_base', source_id=12)
    assert isinstance((await SkillResourceBinding.get(id=link.id)).source_id, int)


@pytest.mark.asyncio
async def test_legacy_string_build_survives_integer_skill_model(catalog_flow):
    from pathlib import Path
    from applications.wrq.agent.services.skill_package_service import SkillPackageService
    from applications.wrq.agent.schemas.skill_package_schema import SkillPackageSource
    _, kind, _ = catalog_flow
    skill, version, _ = await seed(kind)
    skill.legacy_id = 'legacy-old-skill'
    await skill.save(update_fields=['legacy_id'])
    packages = SkillPackageService()
    built = packages.builder.build(SkillPackageSource(name='legacy-skill', display_name='Old build',
        description='Legacy description', instructions='Keep this immutable build', version='1.0.0'), [],
        user_id='owner', skill_id=skill.legacy_id)
    version.build_id = built['build_id']
    version.package_storage_key = str(Path(built['workspace_dir']) / 'package.zip')
    await version.save()
    read = await packages.get(skill.id, version.build_id, PlatformIdentity(1, 'owner', 'Owner', login_name='owner'), verify=True)
    assert read['build_id'] == built['build_id'] and read['skill_version_id'] == version.id
