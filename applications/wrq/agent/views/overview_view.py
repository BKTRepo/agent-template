from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.overview_service import online_skills, period_skills, skill_details
from applications.wrq.http import WrqRoute
from core.responses import SuccessResponse
from services import DependAuth
from applications.wrq.agent.services import overview_facts as facts


overview_router = APIRouter(route_class=WrqRoute)
DATE_PATTERN = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
Metric = Literal[
    'connected_users', 'online_skills', 'skill_calls', 'knowledge_mounts',
    'active_users', 'test_artifacts', 'new_skills', 'new_knowledge_bases',
]


def parse_period(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        return date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError as exc:
        raise DeveloperError('请输入有效的开始日期和结束日期', 422) from exc


def success(data):
    response = SuccessResponse(data=data)
    response.headers['Cache-Control'] = 'no-store'
    return response


@overview_router.get('/cumulative-summary', summary='总览-查询累计指标')
async def cumulative_summary(current_user=DependAuth):
    return success(await facts.cumulative())


@overview_router.get('/period-summary', summary='总览-按日期查询期间指标、趋势和热门技能')
async def period_summary(start_date: str = Query(..., pattern=DATE_PATTERN),
                         end_date: str = Query(..., pattern=DATE_PATTERN), current_user=DependAuth):
    start, end = parse_period(start_date, end_date)
    return success({**await facts.period(start, end), 'start_date': start_date, 'end_date': end_date})


@overview_router.get('/metric-detail', summary='总览-分页查询指标明细')
async def metric_detail(metric: Metric,
                        start_date: str | None = Query(None, pattern=DATE_PATTERN),
                        end_date: str | None = Query(None, pattern=DATE_PATTERN),
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), current_user=DependAuth):
    is_period_metric = metric in ('active_users', 'test_artifacts', 'new_skills', 'new_knowledge_bases')
    if is_period_metric:
        if start_date is None or end_date is None:
            raise DeveloperError('查询期间指标明细需要开始日期和结束日期', 422)
        start, end = parse_period(start_date, end_date)
    else:
        start, end = None, None
    return success(await facts.detail(metric, start, end, page, page_size))
