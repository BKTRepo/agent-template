from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.overview_service import online_skills, period_skills, skill_details
from applications.wrq.http import WrqRoute
from core.responses import SuccessResponse


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
async def cumulative_summary():
    return success(dict(
        connected_user_count=None,
        online_skill_count=await online_skills().count(),
        skill_call_count=None,
        knowledge_mount_count=None,
    ))


@overview_router.get('/period-summary', summary='总览-按日期查询期间指标、趋势和热门技能')
async def period_summary(start_date: str = Query(..., pattern=DATE_PATTERN),
                         end_date: str = Query(..., pattern=DATE_PATTERN)):
    start, end = parse_period(start_date, end_date)
    count = await period_skills(start, end).count()
    days = (end - start).days + 1
    bucket_days = 1 if days <= 14 else 2 if days <= 30 else 7
    return success(dict(
        start_date=start_date,
        end_date=end_date,
        active_user_count=None,
        test_artifact_count=None,
        new_skill_count=count,
        new_knowledge_base_count=None,
        trend=dict(bucket_days=bucket_days, points=None),
        top_skills=None,
    ))


@overview_router.get('/metric-detail', summary='总览-分页查询指标明细')
async def metric_detail(metric: Metric,
                        start_date: str | None = Query(None, pattern=DATE_PATTERN),
                        end_date: str | None = Query(None, pattern=DATE_PATTERN),
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    is_period_metric = metric in ('active_users', 'test_artifacts', 'new_skills', 'new_knowledge_bases')
    if is_period_metric:
        if start_date is None or end_date is None:
            raise DeveloperError('查询期间指标明细需要开始日期和结束日期', 422)
        query = period_skills(*parse_period(start_date, end_date))
    else:
        query = online_skills()
    if metric not in ('online_skills', 'new_skills'):
        raise DeveloperError('该指标的数据源尚未接入', 503)
    by_creation = metric == 'new_skills'
    data = await skill_details(query, by_creation=by_creation, page=page, page_size=page_size)
    if by_creation:
        data.update(start_date=start_date, end_date=end_date)
    return success(data)
