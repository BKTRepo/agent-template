"""Read-only metrics derived from the current Skill lifecycle state."""
from datetime import date, datetime, time, timedelta

import httpx
from tortoise import timezone
from tortoise.functions import Count, Max
from tortoise.transactions import in_transaction

from applications.wrq.agent.models.agent_model import DeveloperSkillClass, Skill, SkillDisplayStatus, SkillForm, SkillVersion
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.catalog import application_options
from configure import LOGGER


def online_skills():
    return Skill.filter(state=0, display_status=SkillDisplayStatus.ONLINE)


def period_skills(start_date: date, end_date: date):
    if start_date > end_date:
        raise DeveloperError('开始日期不能晚于结束日期', 422)
    if end_date > timezone.localtime(timezone.now(), 'Asia/Shanghai').date():
        raise DeveloperError('不能选择未来日期', 422)
    # Both backend entry points store local wall-clock times with use_tz=False.
    start_at = datetime.combine(start_date, time.min)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min)
    return online_skills().filter(created_time__gte=start_at, created_time__lt=end_at)


async def skill_details(query, *, by_creation: bool, page: int, page_size: int):
    order = '-created_time' if by_creation else '-published_at'
    async with in_transaction() as db:
        query = query.using_db(db)
        total = await query.count()
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        skills = await query.order_by(order, '-id').offset((page - 1) * page_size).limit(page_size)

    from applications.chat.models.chat_model import ChatSkillCall
    calls = {row['skill_id']: row for row in await ChatSkillCall.filter(skill_id__in=[skill.id for skill in skills]).group_by('skill_id').annotate(total=Count('id'), recent=Max('created_time')).values('skill_id', 'total', 'recent')}
    items = []
    if skills:
        version_ids = [skill.published_version_id for skill in skills if skill.published_version_id is not None]
        versions = {row.id: row for row in await SkillVersion.filter(id__in=version_ids)}
        forms = {row.skill_version_id: row for row in await SkillForm.filter(skill_version_id__in=version_ids)}
        class_ids = {skill.skill_classes_id for skill in skills} | {form.skill_class_id for form in forms.values()}
        classes = {row.id: row.name for row in await DeveloperSkillClass.filter(id__in=class_ids)}
        try:
            applications = {row['id']: row['name'] for row in await application_options()}
        except (httpx.HTTPError, ValueError, OSError) as exc:
            LOGGER.warning('总览应用目录暂不可用: {}', type(exc).__name__)
            applications = {'*': '全应用适用'}
        for skill in skills:
            version = versions.get(skill.published_version_id)
            if version and version.skill_id != skill.id:
                version = None
            form = forms.get(version.id) if version else None
            class_id = form.skill_class_id if form else skill.skill_classes_id
            application = form.application_paso if form else skill.application_paso
            items.append({
                'skill_id': skill.id,
                'name': form.name if form else skill.name,
                'skill_class_name': classes.get(class_id),
                'application_name': applications.get(application),
                'version': version.version if version else None,
                'status': skill.display_status,
                'published_at': skill.published_at,
                'created_time': skill.created_time,
                'creator_login_name': skill.create_user_login_name,
                # The formal invocation event provider is separate from catalog test counts.
                'call_count': calls.get(skill.id, {}).get('total', 0),
                'last_called_at': calls.get(skill.id, {}).get('recent'),
            })
    return dict(items=items, total=total, page=page, page_size=page_size, pages=pages)
