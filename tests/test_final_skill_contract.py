"""按当前保存/构建契约核对分类、版本、Markdown、事务与知识库挂载。"""
import io
from pathlib import Path
import zipfile
import pytest
from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillResourceBinding, SourceVersion
from applications.wrq.agent.services.skill_package_service import SkillPackageService
from developer_contract_helpers import (developer_setup, seed_catalog, payload, create_saved, update_saved, build_saved, saved_form, upload)
from test_skill_package_api import token
from test_platform_knowledge import kb_setup, save


@pytest.mark.asyncio
async def test_manual_categories_template_and_asset_keep_original_bytes(developer_setup):
    client, owner, _ = developer_setup
    files = [('files', ('template.md', b'# Template')), ('files', ('diagram.png', b'PNG image unchanged')),
             ('files', ('run.py', b"raise RuntimeError('never execute')"))]
    resources = await upload(client, owner, files, ['template', 'asset', 'script'])
    assert resources.status_code == 200, resources.text
    row = await create_saved(client, owner, application_ids=['核心系统'], resource_usage='按模板生成用例，先看流程图，脚本由运行端使用。', uploaded_resources=resources.json()['data'])
    response = await build_saved(client, owner, row, version='999.999.999')
    assert response.json()['status'] == 'success', response.text
    built = response.json()['data']
    assert built['version'] == '1.0.0'
    assert [v['category'] for v in built['files'][1:]] == ['template', 'asset', 'script']
    assert [v['path'] for v in built['files'][1:]] == ['assets/template.md', 'assets/diagram.png', 'scripts/run.py']
    download = await client.get(f"/skills/{row['id']}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        for entry, (_, (_, content)) in zip(built['files'][1:], files):
            assert archive.read(f"{built['name']}/{entry['path']}") == content


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'resource_categories': []}, {'application': '自由输入的无效应用'}, {'skill_class_id': 'unknown'}])
async def test_missing_classification_and_invalid_catalog_values_roll_back(developer_setup, changes):
    client, owner, _ = developer_setup
    if 'resource_categories' in changes:
        response = await upload(client, owner, [('files', ('rules.md', b'rule'))], [])
        assert await SourceVersion.all().count() == 0
    else:
        data = {'application_ids': [changes['application']]} if 'application' in changes else {'class_id': changes['skill_class_id']}
        response = await client.post('/skills/developer/', headers=token(owner), json=payload(**data))
    assert response.status_code == 400 and response.json()['status'] == 'failure', response.text
    assert await Skill.all().count() == 0 and await SkillVersion.all().count() == 0
    assert await SkillResourceBinding.all().count() == 0
    assert not list(SkillPackageService().builder.root.glob('**/manifest.json'))


@pytest.mark.asyncio
async def test_markdown_edit_version_and_conflict_do_not_duplicate_resources(developer_setup):
    client, owner, other = developer_setup
    resources = (await upload(client, owner, [('files', ('rules.md', b'rule'))], ['reference'])).json()['data']
    row = await create_saved(client, owner, resource_usage='读取规则', uploaded_resources=resources)
    first = (await build_saved(client, owner, row)).json()['data']
    path = f"/skills/{row['id']}/definition"
    current = (await client.get(path, headers=token(owner))).json()['data']
    markdown = current['markdown'].replace('读取需求并生成用例。', '先核对需求，再设计异常场景。')
    edited = await client.put(path, headers=token(owner), json={'markdown': markdown, 'expected_version': '1.0.0'})
    assert edited.json()['status'] == 'success', edited.text
    assert edited.json()['data']['version'] == '1.0.1'
    assert '先核对需求' in edited.json()['data']['source']['instructions']
    current = (await client.get(path, headers=token(owner))).json()['data']
    assert current['markdown'].count('<!-- platform-resources:start -->') == 1
    assert current['markdown'].count('[参考资料 1]') == 1
    assert Path(first['skill_directory'], 'references/rules.md').read_bytes() == b'rule'
    assert await SourceVersion.all().count() == 1
    assert await SkillResourceBinding.filter(skill_version_id=edited.json()['data']['skill_version_id']).count() == 1
    conflict = await client.put(path, headers=token(owner), json={'markdown': markdown, 'expected_version': '1.0.0'})
    assert conflict.status_code == 409 and '刷新' in conflict.json()['message']
    denied = await client.put(path, headers=token(other), json={'markdown': markdown, 'expected_version': '1.0.1'})
    assert denied.json()['status'] == 'failure'
    assert await SkillVersion.filter(skill_id=row['id']).count() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('markdown', ['---\nname: [broken\n---\ntext', '[missing](../out.md)', '---\nname: x\n---\n'])
async def test_bad_markdown_leaves_current_build_and_version_unchanged(developer_setup, markdown):
    client, owner, _ = developer_setup
    row = await create_saved(client, owner)
    first = (await build_saved(client, owner, row)).json()['data']
    result = await client.put(f"/skills/{row['id']}/definition", headers=token(owner), json={'markdown': markdown, 'expected_version': '1.0.0'})
    assert result.json()['status'] == 'failure', result.text
    current = await saved_form(row)
    assert current.id == row['skill_version_id'] and current.build_id == first['build_id'] and current.revision == 1
    assert await SkillVersion.filter(skill_id=row['id']).count() == 1
    assert Path(first['skill_directory'], 'SKILL.md').read_text('utf8') == current.skill_markdown


@pytest.mark.asyncio
async def test_build_storage_is_discarded_when_sql_save_fails(developer_setup, monkeypatch):
    client, owner, _ = developer_setup
    row = await create_saved(client, owner)
    original_save = SkillVersion.save
    async def fail(self, *args, **kwargs):
        if self.build_id:
            raise OSError('simulated SQL write failure')
        return await original_save(self, *args, **kwargs)
    monkeypatch.setattr(SkillVersion, 'save', fail)
    response = await build_saved(client, owner, row)
    assert response.json()['status'] == 'failure', response.text
    current = await saved_form(row)
    assert current.build_id is None and current.skill_markdown == '' and current.revision == 1
    assert (await Skill.get(id=row['id'])).display_status == 'DRAFT'
    assert not list(SkillPackageService().builder.root.glob('**/manifest.json'))


@pytest.mark.asyncio
async def test_real_knowledge_original_files_mount_into_full_skill_zip(kb_setup):
    client, owner, other, _, _ = kb_setup
    await seed_catalog()
    kb = (await save(client, owner)).json()['data']
    row = await create_saved(client, owner, name='实际知识库挂载')
    basic = await build_saved(client, owner, row)
    assert basic.json()['status'] == 'success', basic.text
    result = await client.post(f"/knowledge-bases/{kb['id']}/mounts", headers=token(owner),
        json={'skill_ids': [row['id']], 'resource_usage': '生成用例前先读取转账规则。'})
    assert result.status_code == 200, result.text
    item = result.json()['data']['items'][0]
    assert item['status'] == 'succeeded', result.text
    built = item['build']
    assert built['version'] == '1.0.1' and built['source']['knowledge_base_ids'] == [kb['id']]
    download = await client.get(f"/skills/{row['id']}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        reference = next(v for v in built['files'] if v['role'] == 'reference')
        assert '余额必须充足' in archive.read(f"{built['name']}/{reference['path']}").decode()
    denied = await client.post(f"/knowledge-bases/{kb['id']}/mounts", headers=token(other), json={'skill_ids': [row['id']], 'resource_usage': '尝试修改别人技能'})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_generic_crud_cannot_forge_or_reset_parser_version(developer_setup):
    client, owner, _ = developer_setup
    forged = await client.post('/skills/', headers=token(owner), json={'name': '伪造版本', 'config': {'parser_revision': 999}})
    assert forged.status_code == 422
    row = await create_saved(client, owner)
    built = (await build_saved(client, owner, row)).json()['data']
    reset = await client.put(f"/skills/{row['id']}", headers=token(owner), json={'config': None})
    assert reset.json()['status'] == 'failure'
    name = await client.put(f"/skills/{row['id']}", headers=token(owner), json={'name': '绕过表单修改'})
    assert name.json()['status'] == 'failure'
    current = await saved_form(row)
    assert current.build_id == built['build_id'] and current.revision == 1 and current.skill_name == row['name']
    assert await SkillVersion.filter(skill_id=row['id']).count() == 1


@pytest.mark.asyncio
async def test_form_never_silently_uses_outdated_markdown_instead_of_new_instructions(developer_setup):
    client, owner, _ = developer_setup
    row = await create_saved(client, owner)
    first = (await build_saved(client, owner, row)).json()['data']
    old = (await saved_form(row)).skill_markdown
    response = await update_saved(client, owner, row, instructions='改用验证码和账号锁定的新规则', skill_markdown=old)
    assert response.status_code == 200, response.text
    newer = response.json()['data']
    assert newer['skill_markdown'] == '' and newer['version'] == '1.0.1'
    result = await build_saved(client, owner, newer)
    assert result.json()['status'] == 'success', result.text
    built = result.json()['data']
    assert '改用验证码和账号锁定的新规则' in built['source']['instructions']
    assert '改用验证码和账号锁定的新规则' in Path(built['skill_directory'], 'SKILL.md').read_text('utf8')
    assert Path(first['skill_directory'], 'SKILL.md').read_text('utf8') == old
