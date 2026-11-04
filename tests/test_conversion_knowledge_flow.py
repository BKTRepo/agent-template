"""Real SQLite/HTTP linkage; external ingestion stages are explicit test doubles."""
import hashlib
import io
import json
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk, KnowledgeBase
from applications.knowledge_base.models.rag_document_model import RagDocument
from applications.knowledge_base.services.rag_pipeline import RagPipelineService
from applications.knowledge_base.services.rag_service import RagDocumentService
from applications.knowledge_base.services.platform_service import KnowledgeService
from applications.knowledge_base.views import knowledge_router
from applications.knowledge_base.views.conversion_view import conversion_router
from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, SkillResourceBinding
from applications.wrq.agent.views import skills_router
from applications.wrq.auth import AuthControl as WrqAuth
from configure import PROJECT_CONFIG
from services import AuthControl


@pytest_asyncio.fixture
async def flow(database, tmp_path, monkeypatch):
    monkeypatch.setattr(PROJECT_CONFIG, 'RAG_INPUT_DIR', str(tmp_path / 'input'))
    monkeypatch.setattr(PROJECT_CONFIG, 'OUTPUT_UPLOAD_DIR', str(tmp_path / 'uploads'))
    monkeypatch.setattr(PROJECT_CONFIG, 'SKILL_BUILD_DIR', str(tmp_path / 'builds'))
    owner = await User.create(username='owner', alias='Owner', email='owner@test.local', password='unused')
    other = await User.create(username='other', alias='Other', email='other@test.local', password='unused')
    actor = {'user': owner}
    app = FastAPI()
    app.include_router(knowledge_router, prefix='/knowledge-bases')
    app.include_router(conversion_router, prefix='/api')
    app.include_router(skills_router, prefix='/skills')
    app.dependency_overrides[AuthControl.is_authed] = lambda: actor['user']
    app.dependency_overrides[WrqAuth.is_authed] = lambda: actor['user']
    counter = []

    async def submit(_self, *, file_bytes, filename, owner_id, **kwargs):
        job_id = f'doc-test-{len(counter)}'
        path = Path(PROJECT_CONFIG.RAG_INPUT_DIR) / job_id / filename
        path.parent.mkdir(parents=True); path.write_bytes(file_bytes)
        await RagDocument.create(job_id=job_id, filename=filename, owner_id=owner_id,
                                 input_path=str(path), file_sha256=hashlib.sha256(file_bytes).hexdigest(), status='embedding')
        counter.append(job_id)
        return {'job_id': job_id, 'status': 'embedding', 'filename': filename}

    monkeypatch.setattr(RagPipelineService, 'submit_conversion', submit)
    monkeypatch.setattr(RagDocumentService, 'get_document_chunks', AsyncMock(return_value=[{'order': 1, 'content': 'business rule'}]))
    monkeypatch.setattr(RagDocumentService, 'get_document_markdown', AsyncMock(return_value='# Business rule'))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client, actor, owner, other, counter, app


async def create_from_job(client, job, name='Business knowledge', public=False):
    return await client.post('/knowledge-bases/create', data={'source': json.dumps({
        'knowledge_name': name, 'is_public': public, 'conversion_job_ids': [job]})})


@pytest.mark.asyncio
async def test_convert_create_poll_complete_and_skill_update_binding(flow):
    client, actor, owner, _, submitted, _ = flow
    job = (await client.post('/api/convert', files={'file': ('rules.md', b'business rule')})).json()['data']['job_id']
    assert await KnowledgeBase.all().count() == 0
    assert await SkillResourceBinding.all().count() == 0
    response = await create_from_job(client, job)
    assert response.status_code == 200, response.text
    kb = response.json()['data']
    assert kb['status'] == 'processing'
    assert kb['documents'][0]['conversion_job_id'] == job
    assert isinstance(kb['id'], int) and isinstance(kb['documents'][0]['id'], int)
    assert await SkillResourceBinding.all().count() == 0  # 创建知识库不自动挂载技能。
    assert len(submitted) == 1
    assert (await client.get('/api/convert/status', params={'job_id': job})).json()['data']['status'] == 'embedding'
    assert await DocumentChunk.all().count() == 0
    await RagDocument.filter(job_id=job).update(status='complete')
    assert (await client.get('/api/convert/status', params={'job_id': job})).json()['data']['status'] == 'complete'
    detail = (await client.get('/knowledge-bases/detail', params={'kb_id': kb['id']})).json()['data']
    assert detail['status'] == 'completed'
    assert detail['documents'][0]['chunk_count'] == 1
    downloaded = await client.get('/knowledge-bases/documents/download', params={'kb_id': kb['id'], 'doc_id': kb['documents'][0]['id']})
    assert downloaded.content == b'business rule'
    # The public update API, not an ad-hoc binding write, saves all related skill data.
    kind = await DeveloperSkillClass.create(name='Case generation')
    form = {'class_id': kind.id, 'name': 'Sample skill', 'description': 'Generate tests', 'instructions': 'Generate cases',
            'application_ids': [], 'resource_ids': [], 'uploaded_resources': [], 'resource_usage': ''}
    created = (await client.post('/skills/developer/create-skill-draft', json=form)).json()['data']
    saved = await client.post('/skills/developer/save-skill', json={**form, 'skill_id': created['id'],
        'expected_revision': created['current_revision'], 'resource_ids': [kb['id']], 'resource_usage': 'Use business rules'})
    assert saved.json()['status'] == 'success', saved.text
    version = saved.json()['data']['skill_version_id']
    assert await SkillResourceBinding.filter(skill_id=created['id'], skill_version_id=version,
        source_type='knowledge_base', source_id=kb['id']).count() == 1


@pytest.mark.asyncio
async def test_private_jobs_cannot_be_claimed_and_lost_response_is_idempotent(flow):
    client, actor, owner, other, _, _ = flow
    job = (await client.post('/api/convert', files={'file': ('private.txt', b'private')})).json()['data']['job_id']
    actor['user'] = other
    assert (await create_from_job(client, job)).status_code == 404
    assert (await client.get('/api/convert/status', params={'job_id': job})).json()['status'] == 'failure'
    actor['user'] = owner
    first = (await create_from_job(client, job)).json()['data']
    repeated = (await create_from_job(client, job)).json()['data']
    assert first['id'] == repeated['id']
    assert await KnowledgeBase.all().count() == 1
    assert await Document.all().count() == 1
    conflict = await create_from_job(client, job, name='Another knowledge base')
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_failure_retries_original_conversion_without_new_version(flow, monkeypatch):
    client, actor, owner, _, _, _ = flow
    job = (await client.post('/api/convert', files={'file': ('retry.md', b'retry')})).json()['data']['job_id']
    kb = (await create_from_job(client, job)).json()['data']
    await RagDocument.filter(job_id=job).update(status='failed', summary='embedding unavailable')
    detail = (await client.get('/knowledge-bases/detail', params={'kb_id': kb['id']})).json()['data']
    assert detail['status'] == 'failed'

    async def retry(_self, job_id):
        assert job_id == job
        await RagDocument.filter(job_id=job_id).update(status='parsing')
        return {'job_id': job_id, 'status': 'parsing'}
    monkeypatch.setattr(RagPipelineService, 'retry_document', retry)
    response = await client.post('/api/convert/retry', json={'job_id': job})
    assert response.json()['status'] == 'success', response.text
    detail = (await client.get('/knowledge-bases/detail', params={'kb_id': kb['id']})).json()['data']
    assert detail['status'] == 'processing' and detail['version'] == 'V1.0.0'
    assert await RagDocument.all().count() == 1


@pytest.mark.asyncio
async def test_all_changed_api_parameters_follow_get_post_convention(flow):
    *_, app = flow
    for route in app.routes:
        if not hasattr(route, 'dependant'):
            continue
        assert route.methods <= {'GET', 'POST'}, route.path
        assert '{' not in route.path, route.path
        if 'POST' in route.methods:
            assert not route.dependant.query_params, route.path


@pytest.mark.asyncio
async def test_same_filename_edit_hands_new_generation_to_existing_pipeline(flow):
    from applications.knowledge_base.schemas.platform_schema import KnowledgeForm
    client, actor, owner, _, _, _ = flow
    job = (await client.post('/api/convert', files={'file': ('replace.md', b'first rule')})).json()['data']['job_id']
    kb = (await create_from_job(client, job)).json()['data']
    await RagDocument.filter(job_id=job).update(status='complete')
    await client.get('/knowledge-bases/detail', params={'kb_id': kb['id']})
    doc_id = kb['documents'][0]['id']
    form = KnowledgeForm(knowledge_name='Business knowledge', expected_version='V1.0.0',
                         retained_document_ids=[doc_id], change_summary='Replace rules', is_public=False)
    updated, jobs = await KnowledgeService().save(owner, form, [UploadFile(filename='replace.md', file=io.BytesIO(b'new rule'))], kb_id=kb['id'])
    assert updated['version'] == 'V1.0.1'
    assert jobs == [doc_id]
    assert (await Document.get(id=doc_id)).generation == 2
    assert (await RagDocument.get(job_id=job)).knowledge_document_id is None
