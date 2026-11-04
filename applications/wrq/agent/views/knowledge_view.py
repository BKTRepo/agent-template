"""知识库查询及后端审计接口；不增加前端功能。"""
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from core.responses import SuccessResponse
from applications.wrq.auth import DependAuth
from applications.wrq.http import WrqRoute
from applications.wrq.knowledge import search
from applications.wrq.models.knowledge_execution_model import KnowledgeToolCall, KnowledgeExecution
from applications.wrq.agent.services.developer_skill_crud import DeveloperError

router = APIRouter(route_class=WrqRoute)
search_router = APIRouter(route_class=WrqRoute)

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)

@search_router.post('/knowledge/search', summary='知识库MCP-执行本次任务授权范围内的检索')
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
    rows = await KnowledgeToolCall.filter(run_id=run_id, owner_id=current_user.id).order_by('-created_at').offset(offset).limit(limit).values('id','run_id','tool_call_id','query','status','matches','error_type','duration_ms','delivered_at','created_at')
    return SuccessResponse(data=rows)
