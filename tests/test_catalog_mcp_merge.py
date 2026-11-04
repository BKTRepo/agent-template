"""合并回归：目录发布版MCP授权不漏接、不扩大私人调试权限，不丢原子计数。"""
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from applications.user.models.user_model import User
from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document, DocumentChunk
from applications.wrq.agent.models.agent_model import Skill, SkillDebugRun, SkillResourceBinding
from applications.wrq.agent.schemas.skill_package_schema import SkillPackageSource
from applications.wrq.agent.services.skill_package_service import SkillPackageService
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.auth import PlatformIdentity
from applications.wrq.knowledge import prepare_execution
from applications.wrq.markdown_storage import write_markdown
from applications.wrq.models.knowledge_execution_model import KnowledgeExecution
from applications.zhaoyunlong.models.online_debug_run_model import OnlineDebugRun
from applications.zhaoyunlong.services.online_debug_run_service import OnlineDebugRunService
from test_skill_catalog_flow import catalog_flow, seed


async def bound_skill(kind, *, public):
    owner = await User.create(username='owner', alias='Owner', email='mcp@test.local', password='unused')
    kb = await KnowledgeBase.create(knowledge_name='Scoped rules', user_id=owner.id, is_public=public)
    document = await Document.create(knowledge_base_id=kb.id, filename='rules.md', file_path='unused', file_size=1,
        status='completed', generation=1, indexed_generation=1, content_hash='a' * 64)
    await DocumentChunk.create(document_id=document.id, content='Authorized rule', chunk_index=0,
        chroma_id='chunk-1', source_metadata={'job_id': 'doc-mcp-test'})
    skill, version, form = await seed(kind)
    source = SkillPackageSource(name='mcp-merge-test', display_name=skill.name, description='MCP scoped knowledge',
        instructions='Use knowledge_search before generation', version='1.0.0', knowledge_base_ids=[str(kb.id)])
    packages = SkillPackageService()
    if public:
        normalized, resolved, report = await packages.resolve(source, PlatformIdentity(2, 'viewer', 'Viewer', login_name='viewer'))
        assert report.valid and not resolved  # 知识库不再展开为ZIP附件。
    else:
        normalized, resolved = source, []
    built = packages.builder.build(normalized, resolved, user_id='owner', skill_id=skill.id)
    version.build_id = built['build_id']
    version.package_storage_key = str(Path(built['workspace_dir']) / 'package.zip')
    await version.save()
    raw = (Path(built['skill_directory']) / 'SKILL.md').read_text('utf-8')
    assert 'knowledge_search' in raw and len(built['files']) == 1
    form.skill_markdown_path = write_markdown(skill.id, raw)
    await form.save()
    await SkillResourceBinding.create(skill_id=skill.id, skill_version_id=version.id,
        source_type='knowledge_base', source_id=kb.id, display_name=kb.knowledge_name)
    return skill, version, kb, document


@pytest.mark.asyncio
async def test_catalog_creates_frozen_mcp_scope_without_expanding_private_debug(catalog_flow, monkeypatch):
    client, kind, _ = catalog_flow
    skill, version, kb, document = await bound_skill(kind, public=True)
    executed = []
    async def execute(record_id, run_id, payload, owner_id):
        executed.append(payload)
        await OnlineDebugRun.filter(id=record_id).update(status='failed', error_message='Explicit test failure')
        await KnowledgeExecution.filter(run_id=run_id).update(active=False)
    monkeypatch.setattr(OnlineDebugRunService, '_execute', execute)
    source = {'skill_id': skill.id, 'build_id': version.build_id, 'request_id': 'd' * 32, 'conversation_input': 'Generate'}
    for _ in range(2):
        response = await client.post('/skills/catalog/create-test-run', data={'source': json.dumps(source)})
        assert response.status_code == 200, response.text
        assert '_knowledge_token' not in response.text
        await asyncio.gather(*list(OnlineDebugRunService._tasks))
    context = await KnowledgeExecution.get(run_id=source['request_id'])
    assert len(executed) == 1 and executed[0]['mounted_resources'] == []
    assert context.owner_id == 2 and context.skill_version_id == version.id and not context.active
    assert context.token_hash == hashlib.sha256(executed[0]['_knowledge_token'].encode()).hexdigest()
    assert context.scope[0]['knowledge_base_id'] == str(kb.id) and context.scope[0]['document_id'] == document.id
    assert (await Skill.get(id=skill.id)).call_count == 1
    assert (await Skill.get(id=skill.id)).display_status == 'ONLINE'
    with pytest.raises(DeveloperError, match='权限'):
        await prepare_execution({'skill_id': skill.id}, PlatformIdentity(2, 'viewer', 'Viewer', login_name='viewer'), 'private-debug')


@pytest.mark.asyncio
async def test_catalog_respects_private_knowledge_access(catalog_flow, monkeypatch):
    client, kind, _ = catalog_flow
    skill, version, _, _ = await bound_skill(kind, public=False)
    execute = AsyncMock()
    monkeypatch.setattr(OnlineDebugRunService, '_execute', execute)
    response = await client.post('/skills/catalog/create-test-run', data={'source': json.dumps({
        'skill_id': skill.id, 'build_id': version.build_id, 'request_id': 'e' * 32, 'conversation_input': 'Generate'})})
    assert response.status_code == 403, response.text
    assert await KnowledgeExecution.all().count() == 0
    assert await OnlineDebugRun.all().count() == 0
    assert (await Skill.get(id=skill.id)).call_count == 0
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_context_rolls_back_together_with_counter_and_task(catalog_flow, monkeypatch):
    client, kind, _ = catalog_flow
    skill, version, _, _ = await bound_skill(kind, public=True)
    monkeypatch.setattr(SkillDebugRun, 'create', AsyncMock(side_effect=RuntimeError('Explicit link failure')))
    execute = AsyncMock()
    monkeypatch.setattr(OnlineDebugRunService, '_execute', execute)
    with pytest.raises(RuntimeError, match='link failure'):
        await client.post('/skills/catalog/create-test-run', data={'source': json.dumps({
            'skill_id': skill.id, 'build_id': version.build_id, 'request_id': 'f' * 32, 'conversation_input': 'Generate'})})
    assert await KnowledgeExecution.all().count() == 0 and await OnlineDebugRun.all().count() == 0
    assert (await Skill.get(id=skill.id)).call_count == 0
    execute.assert_not_called()
