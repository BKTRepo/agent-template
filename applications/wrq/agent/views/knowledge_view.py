"""知识库查询及后端审计接口；不增加前端功能。"""
import asyncio

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from core.responses import SuccessResponse
from applications.wrq.auth import DependAuth
from applications.wrq.http import WrqRoute
from applications.wrq.knowledge import search
from applications.wrq.models.knowledge_execution_model import KnowledgeToolCall, KnowledgeExecution
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.mcp_search_trace import SEARCH_ID_PATTERN, read_trace

router = APIRouter(route_class=WrqRoute)
search_router = APIRouter(route_class=WrqRoute)
CALL_FIELDS = ('id', 'run_id', 'tool_call_id', 'query', 'status', 'matches', 'error_type',
               'duration_ms', 'delivered_at', 'created_at')

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)

@search_router.post('/knowledge/search', summary='知识库MCP-原始查询混合检索及模型重排，返回原文与来源')
async def search_for_mcp(data: SearchRequest, authorization: str = Header(default='')):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise DeveloperError('请携带知识库运行凭据', 403)
    return await search(token, data.query, data.top_k)

@router.get('/developer/list-knowledge-tool-calls', summary='开发者中心-查询本人调试任务MCP调用证据')
async def logs(run_id: str = Query(..., min_length=1, max_length=128),
               limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), current_user=DependAuth):
    if not await KnowledgeExecution.filter(run_id=run_id, owner_id=current_user.id).exists():
        raise DeveloperError('任务不存在或无访问权限', 404)
    rows = await KnowledgeToolCall.filter(run_id=run_id, owner_id=current_user.id).order_by('-created_at').offset(offset).limit(limit).values(*CALL_FIELDS)
    return SuccessResponse(data=rows)


@router.get('/developer/get-knowledge-tool-call', summary='开发者中心-查询本人MCP检索明细')
async def tool_call_detail(search_id: str = Query(..., pattern=SEARCH_ID_PATTERN), current_user=DependAuth):
    rows = await KnowledgeToolCall.filter(id=search_id, owner_id=current_user.id).values(*CALL_FIELDS)
    if not rows or not await KnowledgeExecution.filter(run_id=rows[0]['run_id'], owner_id=current_user.id).exists():
        raise DeveloperError('检索记录不存在或无访问权限', 404)
    try:
        trace = await asyncio.to_thread(read_trace, search_id)
    except (OSError, ValueError) as exc:
        raise DeveloperError('知识库检索明细暂不可读取', 503) from exc
    result = SuccessResponse(data=dict(rows[0], search_id=search_id, trace=trace))
    result.headers['Cache-Control'] = 'no-store'
    return result
