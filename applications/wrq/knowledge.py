"""知识库运行范围与权限；本模块不接收模型提供的用户身份或知识库授权。"""
import asyncio
import hashlib
import secrets
import time
from datetime import datetime, timedelta

from configure import LOGGER
from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document, DocumentChunk
from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillResourceBinding
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.models.knowledge_execution_model import KnowledgeExecution, KnowledgeToolCall
from enums import DocumentStatus
from applications.wrq.agent.services.mcp_knowledge_retrieval import retrieve_mcp_chunks
from applications.wrq.agent.services.mcp_search_trace import write_trace


def knowledge_permissions(user_id, kb):
    from tortoise.expressions import Q
    owner = kb is not None and kb.state != 1 and kb.user_id == user_id
    visible = kb is not None and kb.state != 1 and (owner or kb.is_public)
    return dict(can_view=bool(visible), can_edit=bool(owner), can_retry=bool(owner),
        visible_filter=Q(user_id=user_id) | Q(is_public=True), write_filter=Q(user_id=user_id))


async def document_scope(user_id, knowledge_ids):
    result = []
    for kid in knowledge_ids:
        kb = await KnowledgeBase.get_or_none(id=kid)
        if not knowledge_permissions(user_id, kb)['can_view']:
            raise DeveloperError('知识库不存在或无访问权限', 403)
        docs = await Document.filter(knowledge_base_id=kid, is_deleted=False).order_by('id')
        if not docs or any(d.status != DocumentStatus.COMPLETED or d.indexed_generation != d.generation for d in docs):
            raise DeveloperError('知识库尚未处理完成或索引不可用', 409)
        for doc in docs:
            from configure import PROJECT_CONFIG
            if doc.embedding_model and doc.embedding_model != PROJECT_CONFIG.EMBEDDING_MODEL:
                raise DeveloperError('知识库嵌入模型配置已变化，请重新处理', 409)
            chunks = await DocumentChunk.filter(document_id=doc.id).values('chroma_id', 'source_metadata')
            jobs = sorted({c['source_metadata'].get('job_id') for c in chunks if c['source_metadata'].get('job_id')})
            if not chunks or not jobs:
                raise DeveloperError('知识库索引缺失，请重新处理', 409)
            result.append(dict(knowledge_base_id=str(kid), document_id=doc.id,
                generation=doc.generation, hash=doc.content_hash, filename=doc.filename, jobs=jobs,
                chunk_ids=sorted(c['chroma_id'] for c in chunks if c['chroma_id'])))
    return result


async def prepare_execution(payload, user, run_id, *, published=False):
    skill = await Skill.get_or_none(id=payload['skill_id'], state=0)
    if not skill or (not published and skill.create_user_login_name != (getattr(user, 'login_name', None) or user.username)):
        raise DeveloperError('技能不存在或无调试权限', 403)
    if published and skill.display_status != 'ONLINE':
        raise DeveloperError('技能已下线，不能在线测试', 409)
    version = await SkillVersion.get_or_none(id=skill.published_version_id if published else skill.current_version_id, skill_id=skill.id)
    if not version or not version.build_id or payload.get('build_id') != version.build_id:
        raise DeveloperError('调试构建不匹配，请重新生成技能', 409)
    if str(payload.get('skill_version_id')) != str(version.id):
        raise DeveloperError('调试技能版本不匹配', 409)
    from applications.wrq.agent.models.agent_model import SkillForm
    from applications.wrq.markdown_storage import read_markdown
    form = await SkillForm.get_or_none(skill_version_id=version.id)
    if form and form.skill_markdown_path:
        payload['skill_definition'] = read_markdown(form.skill_markdown_path)
        if published:
            from applications.wrq.agent.services.published_skill_version import display_skill_version
            payload['skill_definition'] = display_skill_version(payload['skill_definition'], version.version)
    bindings = await SkillResourceBinding.filter(skill_version_id=version.id, source_type='knowledge_base').order_by('sort_order')
    if not bindings:
        return None
    scope = await document_scope(user.id, [b.source_id for b in bindings])
    token = secrets.token_urlsafe(32)
    await KnowledgeExecution.create(run_id=run_id, owner_id=user.id, skill_id=skill.id,
        skill_version_id=version.id, build_id=version.build_id, scope=scope,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=datetime.now()+timedelta(hours=2))
    return token


async def authorized_execution(token):
    context = await KnowledgeExecution.get_or_none(token_hash=hashlib.sha256(token.encode()).hexdigest(), active=True)
    if not context or context.expires_at <= datetime.now(context.expires_at.tzinfo):
        raise DeveloperError('知识库运行凭据无效或已过期', 403)
    scope = await document_scope(context.owner_id, list(dict.fromkeys(d['knowledge_base_id'] for d in context.scope)))
    if scope != context.scope:
        raise DeveloperError('本次知识库索引已变化，请重新调试', 409)
    return context


async def search(token, query, top_k=5):
    context = await authorized_execution(token)
    if not query.strip() or len(query) > 4000 or not 1 <= top_k <= 10:
        raise DeveloperError('检索问题或数量不合法', 422)
    call = await KnowledgeToolCall.create(run_id=context.run_id, owner_id=context.owner_id, query=query)
    started = time.monotonic()
    trace = dict(schema_version=1, search_id=call.id, run_id=context.run_id, top_k=top_k, final_order=[])
    try:
        chunks, retrieval = await retrieve_mcp_chunks(query, context.scope, top_k, trace=trace)
        await authorized_execution(token)
        docs = {j: d for d in context.scope for j in d['jobs']}
        matches = []
        for chunk in chunks:
            doc = docs.get(chunk['doc_id'])
            if not doc or chunk['id'] not in doc['chunk_ids']:
                raise DeveloperError('检索结果不属于授权索引', 409)
            match = dict(knowledge_base_id=doc['knowledge_base_id'], document_id=doc['document_id'],
                chunk_id=chunk['id'], filename=doc['filename'], text=chunk['content'])
            if 'rerank_score' in chunk:
                match['rerank_score'] = chunk['rerank_score']
            matches.append(match)
        call.status, call.matches = 'success', matches
        call.duration_ms = int((time.monotonic()-started)*1000)
        await call.save()
        trace['final_order'] = [match['chunk_id'] for match in matches]
        return dict(search_id=call.id, trace_id=call.id, status='ok', matches=matches, retrieval=retrieval)
    except Exception as exc:
        call.status, call.error_type = 'failed', type(exc).__name__
        call.duration_ms = int((time.monotonic()-started)*1000)
        await call.save()
        raise DeveloperError('知识库检索失败，请查看后端调用记录', 503) from exc
    finally:
        trace.update(status=call.status, duration_ms=call.duration_ms, error_type=call.error_type)
        try:
            await asyncio.to_thread(write_trace, call.id, trace)
        except Exception as exc:
            LOGGER.warning('MCP检索明细写入失败 search_id={} error_type={}', call.id, type(exc).__name__)


async def verify_evidence(run_id, receipts, required=False):
    context = await KnowledgeExecution.get_or_none(run_id=run_id)
    if not context:
        if required:
            raise DeveloperError('知识库运行上下文缺失', 422)
        return
    valid_receipts = {r['search_id']: r['tool_call_id'] for r in receipts
        if isinstance(r,dict) and isinstance(r.get('search_id'),str) and isinstance(r.get('tool_call_id'),str)}
    rows = await KnowledgeToolCall.filter(run_id=run_id, id__in=list(valid_receipts), status='success')
    if not any(r.matches for r in rows):
        raise DeveloperError('未取得模型自主调用知识库的有效证据', 422)
    for row in rows:
        row.tool_call_id = valid_receipts[row.id]
        row.delivered_at = datetime.now()
        await row.save(update_fields=['tool_call_id','delivered_at'])
