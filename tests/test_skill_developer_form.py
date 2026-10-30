"""新表单完整接口链路，沿用旧接口的隔离数据库和认证测试夹具。"""
import io
import json
from pathlib import Path
import zipfile

from pydantic import ValidationError
import pytest
import yaml

from applications.wrq.agent.schemas.skill_package_schema import SkillDeveloperForm
from applications.wrq.agent.services.skill_upload_adapter import source_from_developer_form
from applications.wrq.agent.services.skill_package_builder import SkillPackageError
from applications.wrq.agent.services.skill_package_service import SkillPackageService
from configure import PROJECT_CONFIG
from test_skill_package_api import setup, token, document, FORM


def form(skill, **changes):
    return {"skill_id": skill.id, "skill_name": "八字段用例生成", "description": "按需求生成测试用例，适用于测试设计。",
            "skill_class_id": "SKILL-CASE-001", "instructions": "读取需求并生成用例。", **changes}


async def submit(client, owner, data, files=None):
    # 模拟新版表单逐项选择分类；负例显式传 [] 可测试未分类。
    if "resource_categories" not in data and files:
        from applications.wrq.agent.services.skill_resource_rules import resource_role
        categories = []
        for _, (filename, *_) in files:
            try:
                categories.append(resource_role(filename))
            except ValueError:
                categories.append("reference")
        data = {**data, "resource_categories": categories}
    return (await client.post("/skills/form/builds", headers=token(owner),
                             data={"source": json.dumps(data)}, files=files or [])).json()


def test_adapter_preserves_description_version_without_client_metadata():
    dto = SkillDeveloperForm(skill_id="s-1", skill_name=" 中文名称 ", description=' 描述: "原文"\n第二段。 ',
                             version=" v0.2.0 ", skill_class_id="SKILL-CASE-001", instructions=" 首个段落。\n第二段。 ")
    built = source_from_developer_form(dto, [])
    assert built.name.startswith("skill-") and len(built.name) <= 64
    assert built.display_name == "中文名称" and built.version == "1.0.0"
    assert built.description == '描述: "原文"\n第二段。'
    assert built.instructions == "首个段落。\n第二段。"
    assert built.description == source_from_developer_form(dto, []).description
    assert built.name == source_from_developer_form(dto, []).name
    assert built.system is None and built.team is None and built.skill_class_id == "SKILL-CASE-001"
    long = dto.model_copy(update={"instructions": "长" * 5000})
    assert source_from_developer_form(long, []).description == built.description
    for field in ("creator_id", "maintainer_id", "technical_name", "role", "target_path"):
        with pytest.raises(ValidationError):
            SkillDeveloperForm(**dto.model_dump(), **{field: "client-value"})


def test_adapter_accepts_all_applications():
    dto = SkillDeveloperForm(skill_id="s-all", skill_name="全应用测试用例生成", description="面向全应用生成测试用例。",
                             version="1.0.0", skill_class_id="SKILL-CASE-001", application="*", instructions="读取需求并生成用例。")
    assert source_from_developer_form(dto, []).application == "*"


@pytest.mark.parametrize("knowledge,files", [(False, ["rule.md"]), (True, [])])
def test_common_usage_is_required_for_either_kind_of_resource(knowledge, files):
    dto = SkillDeveloperForm(skill_id="s-1", skill_name="名称", description="描述", version="0.2.0",
                             instructions="步骤", skill_class_id="SKILL-CASE-001", resource_categories=["reference"] if files else [],
                             knowledge_base_ids=["kb"] if knowledge else [])
    with pytest.raises(SkillPackageError) as error:
        source_from_developer_form(dto, files)
    assert [issue.field for issue in error.value.report.missing_fields] == ["resource_usage"]


from developer_contract_helpers import (
    developer_setup, payload, create_saved, update_saved, build_saved, saved_form, upload)
from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillKnowledgeBinding


@pytest.mark.asyncio
async def test_new_route_plain_form_and_stable_edit(developer_setup):
    client, owner, _ = developer_setup
    description = '场景: "测试设计"\n保留  内部空白与换行。'
    row = await create_saved(client, owner, description=description)
    response = await build_saved(client, owner, row, version='v0.2.0')
    assert response.json()['status'] == 'success', response.text
    built = response.json()['data']
    assert len(built['files']) == 1
    original = Path(built['skill_directory'], 'SKILL.md').read_bytes()
    header = yaml.safe_load(Path(built['skill_directory'], 'SKILL.md').read_text('utf8').split('---', 2)[1])
    assert header['metadata']['creator_id'] == str(owner.id)
    assert header['description'] == description
    assert header['metadata']['version'] == built['version'] == '1.0.0'
    assert built['source']['description'] == description
    assert 'compatibility' not in header and '## 资源使用说明' not in original.decode()
    assert built['source']['instructions'] == row['instructions'] and built['source']['resource_usage'] == ''
    edited = await update_saved(client, owner, row, name='改后的中文名称', description='新版描述', compatibility='Python 3.12')
    assert edited.status_code == 200, edited.text
    newer = edited.json()['data']
    again = (await build_saved(client, owner, newer, version='v0.3.0')).json()['data']
    assert again['name'] == built['name'] and again['build_id'] != built['build_id']
    assert again['version'] == again['source']['version'] == '1.0.1'
    current = await saved_form(newer)
    assert current.skill_name == '改后的中文名称' and current.description == '新版描述'
    assert (await Skill.get(id=row['id'])).display_status == 'DEBUGGING'
    old = (await client.get(f"/skills/{row['id']}/builds/{built['build_id']}", headers=token(owner))).json()['data']
    assert old['source']['description'] == description and old['source']['version'] == '1.0.0'
    # 重复构建同一保存版本应复用已有包，修改保存才生成新版。
    repeated = (await build_saved(client, owner, newer)).json()['data']
    assert repeated['build_id'] == again['build_id']
    history = (await client.get(f"/skills/{row['id']}/builds", headers=token(owner))).json()['data']
    assert history['total'] == 2 and await SkillVersion.filter(skill_id=row['id']).count() == 2
    download = await client.get(f"/skills/{row['id']}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read(f"{built['name']}/SKILL.md") == original


@pytest.mark.asyncio
async def test_unified_mixed_upload_preserves_bytes_and_common_usage_once(developer_setup):
    client, owner, _ = developer_setup
    usage = 'rules.md 核对规则；check.py 校验输入；diagram.png 提供流程图。'
    files = [('files', ('rules.md', b'rules')), ('files', ('check.py', b"raise RuntimeError('must not run')")),
             ('files', ('diagram.png', b'image-bytes-no-execution'))]
    resources = await upload(client, owner, files, ['reference', 'script', 'asset'])
    assert resources.status_code == 200, resources.text
    row = await create_saved(client, owner, resource_usage=usage, compatibility='Python 3.12；预先提供依赖', uploaded_resources=resources.json()['data'])
    response = await build_saved(client, owner, row)
    assert response.json()['status'] == 'success', response.text
    built = response.json()['data']
    assert {entry['path'] for entry in built['files']} == {'SKILL.md', 'references/rules.md', 'scripts/check.py', 'assets/diagram.png'}
    raw = Path(built['skill_directory'], 'SKILL.md').read_text('utf8')
    assert raw.count(usage) == 1 and built['source']['resource_usage'] == usage
    downloaded = await client.get(f"/skills/{row['id']}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.read(f"{built['name']}/scripts/check.py") == files[1][1][1]
        assert archive.read(f"{built['name']}/assets/diagram.png") == files[2][1][1]
    forbidden = await upload(client, owner, [('files', ('dependencies.zip', b'zip-bytes'))], ['asset'])
    assert forbidden.status_code == 400 and forbidden.json()['status'] == 'failure'


@pytest.mark.asyncio
async def test_form_authentication_and_ownership(developer_setup):
    client, owner, other = developer_setup
    row = await create_saved(client, owner)
    assert (await client.post('/skills/form/builds', headers={'token': 'bad'}, data={'source': '{}'})).status_code == 401
    assert (await client.post('/skills/form/builds', data={'source': '{}'})).status_code == 422
    denied = await build_saved(client, other, row)
    assert denied.json()['status'] == 'failure' and denied.json()['message'] == '技能不存在'
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()


@pytest.mark.asyncio
async def test_missing_fields_and_client_identity_rejected(developer_setup):
    client, owner, _ = developer_setup
    missing = await client.post('/skills/developer/', headers=token(owner), json={})
    assert missing.status_code == 422
    assert {v['field'] for v in missing.json()['data']['errors']} == {'name', 'class_id', 'description', 'instructions'}
    row = await create_saved(client, owner)
    no_id = (await client.post('/skills/form/builds', headers=token(owner), data={'source': json.dumps({'skill_name': '名字', 'instructions': '步骤'})})).json()
    assert no_id['status'] == 'failure' and no_id['message'] == '技能不存在'
    identity = await build_saved(client, owner, row, creator_id='other')
    assert identity.json()['status'] == 'failure' and identity.json()['data']['errors'][0]['field'] == 'creator_id'
    resource = (await upload(client, owner, [('files', ('r.md', b'r'))], ['reference'])).json()['data']
    no_usage = await update_saved(client, owner, row, uploaded_resources=resource)
    assert no_usage.status_code == 400 and no_usage.json()['data']['errors'][0]['field'] == 'resource_usage'
    unknown = await client.post('/skills/form/builds', headers=token(owner), data={'source': '{}'}, files=[('reference_files', ('r.md', b'r'))])
    assert unknown.json()['data']['errors'][0]['field'] == 'reference_files'
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))


@pytest.mark.asyncio
async def test_knowledge_usage_permissions_and_snapshot(developer_setup):
    client, owner, other = developer_setup
    kb, _ = await document(owner)
    missing = await client.post('/skills/developer/', headers=token(owner), json=payload(resource_ids=[kb.id]))
    assert missing.status_code == 400 and missing.json()['data']['errors'][0]['field'] == 'resource_usage'
    private, _ = await document(other)
    denied = await client.post('/skills/developer/', headers=token(owner), json=payload(resource_ids=[private.id], resource_usage='读取规则'))
    assert denied.status_code == 400
    row = await create_saved(client, owner, resource_ids=[kb.id, kb.id], resource_usage='读取规则')
    good = await build_saved(client, owner, row)
    assert good.json()['status'] == 'success', good.text
    built = good.json()['data']
    assert len(built['files']) == 2 and built['files'][1]['usage'] == '读取规则'
    assert built['source']['knowledge_base_ids'] == [kb.id]
    assert await SkillKnowledgeBinding.filter(skill_version_id=row['skill_version_id']).count() == 1


@pytest.mark.asyncio
async def test_existing_legacy_build_remains_readable_after_new_form_build(developer_setup):
    client, owner, _ = developer_setup
    row = await create_saved(client, owner)
    old = (await client.post(f"/skills/{row['id']}/builds", headers=token(owner), json=FORM)).json()
    assert old['status'] == 'success'
    new = (await build_saved(client, owner, row)).json()
    assert new['status'] == 'success' and new['data']['version'] == '1.0.0'
    history = (await client.get(f"/skills/{row['id']}/builds/{old['data']['build_id']}", headers=token(owner))).json()['data']
    assert history['name'] == 'case-generator' and history['version'] == '0.1.0'
    edited = (await update_saved(client, owner, row, description='新描述')).json()['data']
    again = (await build_saved(client, owner, edited)).json()['data']
    assert again['name'] == new['data']['name']


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['description', 'skill_class_id'])
@pytest.mark.parametrize('value', [None, '', ' \n\t ', 'omitted'])
async def test_new_required_fields_never_fall_back_to_history(developer_setup, field, value):
    client, owner, _ = developer_setup
    row = await create_saved(client, owner)
    first = (await build_saved(client, owner, row)).json()['data']
    target = 'class_id' if field == 'skill_class_id' else field
    data = payload(name='无效修改', expected_revision=row['current_revision'])
    if value == 'omitted': data.pop(target)
    else: data[target] = value
    response = await client.put(f"/skills/developer/{row['id']}", headers=token(owner), json=data)
    assert response.status_code in (400, 422), response.text
    assert any(v['field'] == target for v in response.json()['data']['errors'])
    saved = await saved_form(row)
    assert saved.skill_name == row['name'] and saved.description == row['description']
    assert saved.build_id == first['build_id'] and saved.revision == 1
    assert await SkillVersion.filter(skill_id=row['id']).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('field,limit', [('description', 1024), ('compatibility', 500)])
async def test_text_limits_are_rejected_without_truncation(developer_setup, field, limit):
    client, owner, _ = developer_setup
    invalid = await client.post('/skills/developer/', headers=token(owner), json=payload(**{field: '长' * (limit + 1)}))
    assert invalid.status_code == 422 and invalid.json()['data']['errors'][0]['field'] == field
    assert await Skill.all().count() == 0
    row = await create_saved(client, owner, **{field: '长' * limit})
    valid = await build_saved(client, owner, row)
    assert valid.json()['status'] == 'success', valid.text
    assert valid.json()['data']['source'][field] == '长' * limit


@pytest.mark.asyncio
@pytest.mark.parametrize('with_files', [False, True])
async def test_empty_knowledge_ids_never_access_knowledge_base(developer_setup, monkeypatch, with_files):
    client, owner, _ = developer_setup
    async def forbidden_knowledge_access(*args, **kwargs):
        raise AssertionError('不挂载知识库时不应查询知识库')
    monkeypatch.setattr(SkillPackageService, '_knowledge_base', forbidden_knowledge_access)
    files = [('files', ('rules.md', b'rules')), ('files', ('flow.png', b'image-bytes')),
             ('files', ('check.py', b"raise RuntimeError('do not run')"))] if with_files else []
    resources = (await upload(client, owner, files, ['reference', 'asset', 'script'])).json()['data'] if files else []
    row = await create_saved(client, owner, uploaded_resources=resources, resource_usage='读取规则和图片，脚本供运行端使用' if files else '')
    result = await build_saved(client, owner, row)
    assert result.json()['status'] == 'success', result.text
    built = result.json()['data']
    expected = {'SKILL.md', 'references/rules.md', 'assets/flow.png', 'scripts/check.py'} if files else {'SKILL.md'}
    assert {v['path'] for v in built['files']} == expected and built['source']['knowledge_base_ids'] == []
    queried = (await client.get(f"/skills/{row['id']}/builds/{built['build_id']}", headers=token(owner))).json()
    assert queried['status'] == 'success' and queried['data']['files'] == built['files']
    response = await client.get(f"/skills/{row['id']}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {f"{built['name']}/{name}" for name in expected}
