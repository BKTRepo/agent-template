import base64
import hashlib
import io
from pathlib import Path
import zipfile

import pytest

from applications.wrq.knowledge_base.models.knowledge_base_model import KnowledgeBase
from configure import PROJECT_CONFIG
from test_skill_package_api import setup, token, document
from test_skill_developer_form import form, submit


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')


@pytest.mark.asyncio
@pytest.mark.parametrize('filename', ['流程.png', 'diagram.PNG', 'flow.jpg', 'flow.JPEG',
                                       'flow.gif', 'diagram.GIF', 'flow.webp', 'diagram.WEBP',
                                       'flow.svg', 'diagram.SVG'])
async def test_image_bytes_assets_links_and_download(setup, filename):
    client, owner, _, skill = setup
    # JPEG 资源使用独立二进制样例；本引擎只保存原文件，不解码图像。
    suffix = Path(filename).suffix.lower()
    content = {'.png': PNG, '.gif': b'GIF89a-resource', '.webp': b'RIFF-resource-WEBP',
               '.svg': b'<svg xmlns="http://www.w3.org/2000/svg"><script>throw Error("must not run")</script></svg>'}.get(
                   suffix, b'\xff\xd8\xff\xe0jpeg-resource\xff\xd9')
    usage = f'生成测试用例前，读取业务流程图 {filename}。'
    result = await submit(client, owner, form(skill, resource_usage=usage), [('files', (filename, content, 'application/octet-stream'))])
    assert result['status'] == 'success', result
    built = result['data']
    path = f'assets/{filename}'
    image = next(entry for entry in built['files'] if entry['path'] == path)
    assert image['role'] == 'asset' and image['sha256'] == hashlib.sha256(content).hexdigest()
    root = Path(built['skill_directory'])
    assert (root / path).read_bytes() == content
    raw = (root / 'SKILL.md').read_text(encoding='utf-8')
    assert usage in raw and filename in raw and 'assets/' in raw
    assert not (root / 'references').exists()
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read(f"{built['name']}/{path}") == content


@pytest.mark.asyncio
@pytest.mark.parametrize('files', [
    [('files', ('bad.exe', b'x'))], [('files', ('../flow.png', PNG))],
    [('files', ('empty.md', b''))], [('files', ('CON.png', PNG))],
    [('files', ('Flow.png', PNG)), ('files', ('Ｆｌｏｗ.png', PNG))],
])
async def test_resource_failure_rolls_back_name_and_leaves_no_build(setup, files):
    client, owner, _, skill = setup
    original, original_description = skill.name, skill.description
    result = await submit(client, owner, form(skill, skill_name='失败时不修改名称', resource_usage='使用附件'), files)
    assert result['status'] == 'failure' and result['data']['errors']
    await skill.refresh_from_db()
    assert skill.name == original and skill.description == original_description
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('.uploads/*'))


@pytest.mark.asyncio
async def test_image_requires_usage_and_knowledge_base_must_have_files(setup):
    client, owner, _, skill = setup
    no_usage = await submit(client, owner, form(skill), [('files', ('flow.png', PNG))])
    assert no_usage['data']['missing_fields'][0]['field'] == 'resource_usage'
    kb = await KnowledgeBase.create(user_id=owner.id, knowledge_name='空库')
    result = await submit(client, owner, form(skill, knowledge_base_ids=[kb.id], resource_usage='读取规则'))
    assert result['status'] == 'failure' and result['data']['errors'][0]['field'] == 'knowledge_base_ids[0]'


@pytest.mark.asyncio
async def test_knowledge_base_image_is_asset_and_missing_original_fails(setup):
    client, owner, _, skill = setup
    kb, doc = await document(owner)
    doc.filename = 'flow.png'
    Path(doc.file_path).write_bytes(PNG)
    doc.content_hash = hashlib.sha256(PNG).hexdigest()
    await doc.save()
    data = form(skill, knowledge_base_ids=[kb.id], resource_usage='先读取业务流程图')
    result = await submit(client, owner, data)
    assert result['status'] == 'success', result
    assert result['data']['files'][1]['path'].startswith('assets/')
    Path(doc.file_path).unlink()
    assert (await submit(client, owner, data))['status'] == 'failure'


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', ['file', 'total'])
async def test_new_form_limits_leave_no_published_package(setup, monkeypatch, limit):
    client, owner, _, skill = setup
    files = [('files', ('one.md', b'12')), ('files', ('two.md', b'34'))]
    if limit == 'file':
        monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_MAX_BYTES', 1)
    else:
        monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_TOTAL_MAX_BYTES', 3)
    result = await submit(client, owner, form(skill, resource_usage='读取资源'), files)
    assert result['status'] == 'failure'
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('.uploads/*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [3, 4, 5])
async def test_upload_file_size_boundary(setup, monkeypatch, size):
    client, owner, _, skill = setup
    # 按比例缩小阈值，验证同一流式判断的上限前、等于上限、上限后。
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_MAX_BYTES', 4)
    content = b'x' * size
    result = await submit(client, owner, form(skill, resource_usage='读取附件'),
                          [('files', ('rules.md', content))])
    if size > 4:
        assert result['status'] == 'failure'
        assert result['data']['errors'][0]['field'] == 'files[0]'
        assert '单个文件不能超过' in result['data']['errors'][0]['reason']
        assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))
    else:
        assert result['status'] == 'success', result
        built = result['data']
        assert built['files'][1]['size'] == size
        download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert archive.read(f"{built['name']}/references/rules.md") == content
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('.uploads/*'))


@pytest.mark.asyncio
async def test_multiple_uploads_can_exceed_single_file_limit_in_total(setup, monkeypatch):
    client, owner, _, skill = setup
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_MAX_BYTES', 4)
    files = [('files', ('one.md', b'1234')), ('files', ('two.md', b'5678'))]
    result = await submit(client, owner, form(skill, resource_usage='依次读取两份规则'), files)
    assert result['status'] == 'success', result
    built = result['data']
    assert sum(entry['size'] for entry in built['files'][1:]) == 8
    assert (await client.get(f"/skills/{skill.id}/builds/{built['build_id']}", headers=token(owner))).json()['status'] == 'success'
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read(f"{built['name']}/references/one.md") == b'1234'
        assert archive.read(f"{built['name']}/references/two.md") == b'5678'


@pytest.mark.asyncio
async def test_mounted_file_and_upload_have_independent_limits(setup, monkeypatch):
    client, owner, _, skill = setup
    kb, doc = await document(owner)
    Path(doc.file_path).write_bytes(b'1234')
    doc.content_hash = hashlib.sha256(b'1234').hexdigest()
    await doc.save()
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_MAX_BYTES', 4)
    result = await submit(client, owner, form(skill, knowledge_base_ids=[kb.id], resource_usage='读取两份规则'),
                          [('files', ('uploaded.md', b'5678'))])
    assert result['status'] == 'success', result
    assert [entry['size'] for entry in result['data']['files'][1:]] == [4, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [4, 5, 6])
async def test_direct_upload_count_boundary_and_download(setup, count):
    client, owner, _, skill = setup
    original_name = skill.name
    files = [('files', (f'{index}.md', f'rule-{index}'.encode())) for index in range(count)]
    result = await submit(client, owner, form(skill, resource_usage='读取上传规则'), files)
    if count > 100:
        assert result['status'] == 'failure'
        assert result['data']['errors'][0] == {'field': 'files', 'reason': '每次最多上传 100 个文件'}
        assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))
        await skill.refresh_from_db()
        assert skill.name == original_name
    else:
        assert result['status'] == 'success', result
        built = result['data']
        assert len(built['files']) == count + 1
        download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            for index in range(count):
                assert archive.read(f"{built['name']}/references/{index}.md") == f'rule-{index}'.encode()
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('.uploads/*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('entry_mode', [False, True])
async def test_legacy_upload_routes_cannot_bypass_total_file_limit(setup, monkeypatch, entry_mode):
    import json
    from test_skill_package_api import FORM

    client, owner, _, skill = setup
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_RESOURCE_TOTAL_MAX_BYTES', 5)
    if entry_mode:
        source = {**FORM, 'reference_uploads': [{'usage': '读取'}] * 3,
                  'script_uploads': [{'usage': '校验'}] * 3}
        files = [('reference_files', (f'{i}.md', b'x')) for i in range(3)] + [
            ('script_files', (f'{i}.py', b'x')) for i in range(3)]
    else:
        source = {**FORM, 'resources': [{'upload_index': i, 'role': 'reference', 'usage': '读取'} for i in range(6)]}
        files = [('files', (f'{i}.md', b'x')) for i in range(6)]
    path = f'/skills/{skill.id}/builds/upload' + ('/entries' if entry_mode else '')
    result = (await client.post(path, headers=token(owner), data={'source': json.dumps(source)}, files=files)).json()
    assert result['status'] == 'failure'
    assert any('合计不能超过' in issue['reason'] for issue in result['data']['errors'])
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('**/manifest.json'))
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob('.uploads/*'))
