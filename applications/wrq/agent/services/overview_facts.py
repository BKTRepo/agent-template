"""Overview aggregates and detail rows use the same durable facts and Shanghai date window."""
from collections import defaultdict
import httpx
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from applications.chat.models.chat_model import ChatArtifactCount, ChatSkillCall
from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document
from applications.knowledge_base.schemas.platform_schema import next_version
from applications.user.models.user_model import User
from applications.wrq.models.overview_event_model import OverviewEvent
from applications.wrq.agent.models.agent_model import Skill
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from .overview_service import online_skills, period_skills, skill_details
from applications.wrq.catalog import application_options

NOTES = ['登录、智能对话及挂载事件从本版部署后记录；未记录的历史次数不估算。',
         '用户表没有部门信息，部门字段留空；缺少生成时间或来源的旧产物不混入日期统计。',
         '产出物按最终成功文件统计；Top5 的产出物数按同一任务实际调用的技能关联，用于并列排序。']


def window(start, end):
    period_skills(start, end)  # shared date validation
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def local(value):
    return value.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None) if value.tzinfo else value


def page_rows(rows, page, size):
    pages = max(1, (len(rows) + size - 1) // size)
    page = min(page, pages)
    return dict(items=rows[(page - 1) * size:page * size], total=len(rows), page=page, page_size=size, pages=pages,
                data_notes=NOTES)


async def call_rows(start=None, end=None):
    query = ChatSkillCall.all()
    if start is not None:
        query = query.filter(created_time__gte=start, created_time__lt=end)
    calls = await query.order_by('-created_time', '-id')
    skills = await Skill.in_bulk({item.skill_id for item in calls})
    # Old rows can lack snapshots; show known current identity without inventing an operator.
    return [{'id': item.id, 'skill_id': item.skill_id, 'skill_name': item.skill_name_snapshot or (skills[item.skill_id].name if item.skill_id in skills else '历史技能'),
             'operator_login_name': item.operator_login_name, 'called_at': item.created_time} for item in calls]


async def connected_rows():
    users = await User.filter(last_login__isnull=False).order_by('id')
    events = await OverviewEvent.filter(kind='login').order_by('occurred_at', 'id')
    by_user = defaultdict(list)
    for event in events:
        by_user[event.data.get('user_id')].append(event)
    rows = []
    for user in users:
        logs = by_user[user.id]
        unknown = not logs or any(item.data.get('history_unknown') for item in logs)
        rows.append({'id': user.id, 'department': None, 'username': user.alias or user.username, 'employee_no': user.username,
                     'first_access_at': logs[0].occurred_at if logs and not unknown else None,
                     'last_login_at': user.last_login, 'login_count': len(logs) if not unknown else None,
                     'recorded_login_count': len(logs)})
    return rows


async def mount_rows():
    return [{'id': event.id, **event.data, 'operator_login_name': event.operator_login_name, 'mounted_at': event.occurred_at}
            for event in await OverviewEvent.filter(kind='knowledge_mount').order_by('-occurred_at', '-id')]


async def artifact_rows(start, end):
    records = await ChatArtifactCount.filter(status='counted', generated_at__gte=start, generated_at__lt=end).order_by('-generated_at', '-id')
    return [{'id': item.artifact_id, **item.details, 'generated_at': item.generated_at, 'artifact_count': item.quantity, 'status': 'success'}
            for item in records if item.details and item.details.get('skill_ids') and item.quantity is not None]


async def active_rows(start, end):
    groups = defaultdict(list)
    for event in await OverviewEvent.filter(kind='chat_request', occurred_at__gte=start, occurred_at__lt=end).order_by('occurred_at', 'id'):
        groups[event.operator_login_name].append(event)
    return [{'id': name, 'department': None, 'username': events[-1].data.get('username'), 'employee_no': name,
             'conversation_call_count': len(events), 'first_called_at': events[0].occurred_at,
             'last_called_at': events[-1].occurred_at} for name, events in groups.items()]


async def new_knowledge_rows(start, end):
    try:
        applications = {row['id']: row['name'] for row in await application_options()}
    except (httpx.HTTPError, ValueError, OSError):
        applications = {'*': '全应用适用'}
    knowledge = await KnowledgeBase.filter(created_time__gte=start, created_time__lt=end).order_by('-created_time', '-id')
    owners = await User.in_bulk({item.user_id for item in knowledge})
    return [{'id': item.id, 'name': item.knowledge_name, 'application_name': applications.get(item.application, item.application),
             'creator_login_name': owners[item.user_id].username if item.user_id in owners else None,
             'created_time': item.created_time, 'version': next_version(item.revision),
             'file_count': await Document.filter(knowledge_base_id=item.id, is_deleted=False).count(),
             'updated_at': item.updated_time} for item in knowledge]


async def cumulative():
    return dict(connected_user_count=len(await connected_rows()), online_skill_count=await online_skills().count(),
                skill_call_count=await ChatSkillCall.all().count(),
                knowledge_mount_count=await OverviewEvent.filter(kind='knowledge_mount').count(), data_notes=NOTES)


async def period(start, end):
    start_at, end_at = window(start, end)
    artifacts, calls, active, knowledge = await artifact_rows(start_at, end_at), await call_rows(start_at, end_at), await active_rows(start_at, end_at), await new_knowledge_rows(start_at, end_at)
    days = (end - start).days + 1
    bucket = 1 if days <= 14 else 2 if days <= 30 else 7
    points = []
    for offset in range(0, days, bucket):
        left = start_at + timedelta(days=offset)
        right = min(end_at, left + timedelta(days=bucket))
        points.append({'start_date': left.date().isoformat(), 'end_date': (right - timedelta(days=1)).date().isoformat(),
            'artifact_count': sum(item['artifact_count'] for item in artifacts if left <= local(item['generated_at']) < right),
            'skill_call_count': sum(1 for item in calls if left <= local(item['called_at']) < right)})
    ranking = {}
    for call in calls:
        key = call['skill_id']
        ranking.setdefault(key, {'skill_id': key, 'name': call['skill_name'], 'call_count': 0, 'artifact_count': 0})['call_count'] += 1
    for artifact in artifacts:
        for key in artifact['skill_ids']:
            if key in ranking:
                ranking[key]['artifact_count'] += artifact['artifact_count']
    return dict(active_user_count=len(active), test_artifact_count=sum(item['artifact_count'] for item in artifacts),
                new_skill_count=await period_skills(start, end).count(), new_knowledge_base_count=len(knowledge),
                trend={'bucket_days': bucket, 'points': points},
                top_skills=sorted(ranking.values(), key=lambda row: (-row['call_count'], -row['artifact_count'], row['skill_id']))[:5], data_notes=NOTES)


async def detail(metric, start, end, page, size):
    if metric == 'online_skills':
        return await skill_details(online_skills(), by_creation=False, page=page, page_size=size)
    if metric == 'new_skills':
        return await skill_details(period_skills(start, end), by_creation=True, page=page, page_size=size)
    if metric in ('active_users', 'test_artifacts', 'new_knowledge_bases'):
        left, right = window(start, end)
        rows = await {'active_users': active_rows, 'test_artifacts': artifact_rows, 'new_knowledge_bases': new_knowledge_rows}[metric](left, right)
    else:
        rows = await {'connected_users': connected_rows, 'skill_calls': call_rows, 'knowledge_mounts': mount_rows}[metric]()
    return page_rows(rows, page, size)
