"""真实SQLite、HTTP、固定ZIP；不接生产库及外部沙箱。"""
import io
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, Skill, SkillVersion, SkillForm, SkillDebugRun
from applications.wrq.agent.schemas.skill_package_schema import SkillPackageSource, SkillResourceBinding
from applications.wrq.agent.services.skill_package_builder import ResolvedSkillResource
from applications.wrq.agent.services.skill_package_service import SkillPackageService
from applications.wrq.agent.views import skills_router
from applications.wrq.auth import AuthControl, PlatformIdentity
from applications.wrq.markdown_storage import write_markdown
from configure import PROJECT_CONFIG


@pytest_asyncio.fixture
async def catalog_flow(database, tmp_path, monkeypatch):
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_BUILD_DIR', str(tmp_path / 'builds'))
    kind = await DeveloperSkillClass.create(name='用例生成', description='类的真实说明', input_schema={'type': 'object'}, template='# Configured template')
    await DeveloperSkillClass.create(name='停用类', is_enabled=False)
    app = FastAPI()
    app.include_router(skills_router, prefix='/skills')
    app.dependency_overrides[AuthControl.is_authed] = lambda: PlatformIdentity(2, 'viewer', 'Viewer', login_name='viewer')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client, kind, tmp_path


async def seed(kind, *, status='ONLINE', name='发布实现', application='*', owner='owner', build=False, tmp_path=None):
    skill = await Skill.create(name=name, create_user_login_name=owner, update_user_login_name=owner, skill_classes_id=kind.id, display_status=status)
    version = await SkillVersion.create(skill_id=skill.id, revision=1, version='1.0.0', create_user_login_name=owner)
    form = await SkillForm.create(skill_version_id=version.id, name=name, skill_class_id=kind.id, application_paso=application,
                                  description='发布描述', instructions='发布指令', technical_name='catalog-test')
    skill.current_version_id = version.id
    if status in ('ONLINE', 'OFFLINE'):
        skill.published_version_id = version.id
    await skill.save()
    if build:
        path = tmp_path / 'rules.md'
        path.write_bytes(b'# Immutable published resource')
        source = SkillPackageSource(name='catalog-test', display_name=name, description='发布描述', instructions='发布指令',
            version='1.0.0', resources=[SkillResourceBinding(upload_index=0, role='reference', usage='Read before generation')])
        built = SkillPackageService().builder.build(source, [ResolvedSkillResource(0, path, 'rules.md')], user_id=owner, skill_id=skill.id)
        version.build_id = built['build_id']
        version.package_storage_key = str(Path(built['workspace_dir']) / 'package.zip')
        await version.save()
        form.skill_markdown_path = write_markdown(skill.id, (Path(built['skill_directory']) / 'SKILL.md').read_text('utf-8'))
        await form.save()
    return skill, version, form


@pytest.mark.asyncio
async def test_catalog_uses_published_form_across_users_and_filters(catalog_flow):
    client, kind, _ = catalog_flow
    online, version, form = await seed(kind)
    await seed(kind, status='OFFLINE', name='下线实现', application='APP-B', owner='other')
    await seed(kind, status='DRAFT', name='不可见草稿')
    await seed(kind, status='DEBUG_SUCCESS', name='不可见调试版')
    removed, _, _ = await seed(kind, name='已删除')
    removed.state = 1
    await removed.save()
    # 当前表单变化不能污染公开的发布版，即使当前指针与发布指针不同。
    draft = await SkillVersion.create(skill_id=online.id, revision=2, create_user_login_name='owner')
    await SkillForm.create(skill_version_id=draft.id, name='私有新草稿', skill_class_id=2, description='secret', instructions='secret')
    online.current_version_id = draft.id
    online.name = '私有新草稿'
    await online.save()
    result = (await client.get('/skills/catalog/list-skills', params={'page_size': 1, 'page': 99})).json()['data']
    assert result['total'] == 2 and result['page'] == 2 and result['pages'] == 2
    result = (await client.get('/skills/catalog/list-skills', params={'name': '发布', 'class_id': kind.id, 'application': 'APP-A', 'maintainer': 'owner'})).json()['data']
    assert [row['name'] for row in result['items']] == ['发布实现']
    assert result['items'][0]['call_count'] == 0
    detail = (await client.get('/skills/catalog/get-skill', params={'skill_id': online.id})).json()['data']
    assert detail['name'] == form.name and detail['skill_version_id'] == version.id
    assert detail['creator_name'] == 'owner' and detail['creator_name'] != 'Viewer'
    assert 'secret' not in str(detail)
    assert (await client.get('/skills/catalog/list-skills', params={'name': '私有新草稿'})).json()['data']['total'] == 0


@pytest.mark.asyncio
async def test_class_metadata_and_private_records(catalog_flow):
    client, kind, _ = catalog_flow
    metadata = (await client.get('/skills/catalog/get-metadata')).json()['data']
    assert len(metadata['skill_classes']) == 2
    assert metadata['skill_classes'][1]['is_enabled'] is False
    detail = (await client.get('/skills/catalog/get-class', params={'class_id': kind.id})).json()['data']
    assert detail['description'] == '类的真实说明' and detail['input_schema'] == {'type': 'object'}
    assert detail['output_schema'] is None and detail['template'] == '# Configured template'
    skill, _, _ = await seed(kind, status='DRAFT')
    assert (await client.get('/skills/catalog/get-skill', params={'skill_id': skill.id})).status_code == 404
    assert (await client.get('/skills/catalog/get-class', params={'class_id': -1})).status_code == 422
    assert (await client.get('/skills/catalog/get-class', params={'class_id': 999})).status_code == 404
    assert (await client.get('/skills/catalog/list-skills', params={'page_size': 101})).status_code == 422


@pytest.mark.asyncio
async def test_published_download_resources_and_offline_gate(catalog_flow):
    client, kind, tmp_path = catalog_flow
    skill, version, _ = await seed(kind, build=True, tmp_path=tmp_path)
    params = {'skill_id': skill.id, 'build_id': version.build_id}
    built = (await client.get('/skills/catalog/get-build', params=params)).json()['data']
    assert built['skill_version_id'] == version.id
    assert 'workspace_dir' not in built and 'skill_directory' not in built
    response = await client.get('/skills/catalog/download-skill', params=params)
    assert response.status_code == 200 and 'application/zip' in response.headers['content-type']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read('catalog-test/references/rules.md') == b'# Immutable published resource'
    resource_params = {**params, 'path': 'references/rules.md'}
    assert (await client.get('/skills/catalog/download-resource', params=resource_params)).content == b'# Immutable published resource'
    assert (await client.get('/skills/catalog/download-resource', params={**params, 'path': '../../secret'})).status_code == 404
    assert (await client.get('/skills/catalog/get-build', params={**params, 'build_id': 'other-build'})).status_code == 409
    kind.is_enabled = False
    await kind.save()
    assert (await client.get('/skills/catalog/download-resource', params=resource_params)).status_code == 409
    kind.is_enabled = True
    await kind.save()
    skill.display_status = 'OFFLINE'
    await skill.save()
    assert (await client.get('/skills/catalog/download-resource', params=resource_params)).status_code == 409
    assert (await client.get('/skills/catalog/download-skill', params=params)).status_code == 200
    assert await SkillDebugRun.all().count() == 0
    assert (await Skill.get(id=skill.id)).display_status == 'OFFLINE'


@pytest.mark.asyncio
async def test_catalog_requires_platform_auth(catalog_flow):
    client, _, _ = catalog_flow
    client._transport.app.dependency_overrides.clear()
    assert (await client.get('/skills/catalog/get-metadata')).status_code == 401
