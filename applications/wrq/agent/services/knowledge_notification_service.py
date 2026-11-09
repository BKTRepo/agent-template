"""Persistent unread notices for the current skill version's knowledge mounts."""
from tortoise.expressions import F, Q
from tortoise.transactions import in_transaction
from tortoise.timezone import now

from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document
from applications.knowledge_base.schemas.platform_schema import next_version
from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import Skill, SkillResourceBinding, SkillKnowledgeNotification as Notice
from applications.wrq.auth import user_login_name


async def recipients(skill, db):
    """Team recipient policy can be replaced here without changing notification APIs."""
    return await User.filter(username=skill.create_user_login_name, state__not=1,
                             is_active=True).using_db(db).all()


async def lock_mount_knowledge(skill_id, knowledge_ids, db):
    # All mount writes lock knowledge rows before locking the skill. The expected
    # skill revision is checked after acquiring its lock, rejecting stale pre-reads.
    ids = set(knowledge_ids)
    if skill_id:
        skill = await Skill.filter(id=skill_id).using_db(db).first()
        if skill:
            ids.update(await SkillResourceBinding.filter(skill_version_id=skill.current_version_id,
                source_type='knowledge_base').using_db(db).values_list('source_id', flat=True))
    if ids:
        await KnowledgeBase.filter(id__in=ids).using_db(db).select_for_update().order_by('id')


async def sync_mounts(skill, previous_version_id, db):
    old = {b.source_id: b for b in await SkillResourceBinding.filter(
        skill_version_id=previous_version_id, source_type='knowledge_base').using_db(db)} if previous_version_id else {}
    bindings = await SkillResourceBinding.filter(skill_id=skill.id,
        skill_version_id=skill.current_version_id, source_type='knowledge_base').using_db(db)
    ids = [b.source_id for b in bindings]
    stale = Notice.filter(skill_id=skill.id).using_db(db)
    if ids:
        stale = stale.exclude(knowledge_base_id__in=ids)
    await stale.delete()
    knowledge = {kb.id: kb for kb in await KnowledgeBase.filter(id__in=ids).using_db(db)}
    users = await recipients(skill, db)
    for binding in bindings:
        kb = knowledge.get(binding.source_id)
        if not kb:
            continue
        previous = old.get(kb.id)
        baseline = previous.knowledge_mount_revision if previous else None
        if baseline is None:
            baseline = kb.revision
        binding.knowledge_mount_revision = baseline
        await binding.save(using_db=db, update_fields=['knowledge_mount_revision'])
        for user in users:
            await Notice.get_or_create(using_db=db, recipient_user_id=user.id, skill_id=skill.id,
                knowledge_base_id=kb.id, defaults={'latest_revision': kb.revision,
                    'read_revision': baseline, 'change_summary': (kb.history or [{}])[-1].get('change_summary', '')})


async def notify_knowledge_update(kb, db):
    # Current reads are essential after waiting for a concurrent mount transaction.
    bindings = await SkillResourceBinding.filter(source_type='knowledge_base', source_id=kb.id).using_db(db).select_for_update()
    if not bindings:
        return
    skills = await Skill.filter(id__in={b.skill_id for b in bindings}, state=0).using_db(db).select_for_update().order_by('id')
    for skill in skills:
        binding = next((b for b in bindings if b.skill_id == skill.id and b.skill_version_id == skill.current_version_id), None)
        if not binding:
            continue
        baseline = binding.knowledge_mount_revision
        if baseline is None:
            # Legacy links have no earlier baseline; migration initializes them.
            baseline = max(0, kb.revision - 1)
        for user in await recipients(skill, db):
            notice, _ = await Notice.get_or_create(using_db=db, recipient_user_id=user.id,
                skill_id=skill.id, knowledge_base_id=kb.id,
                defaults={'latest_revision': baseline, 'read_revision': baseline})
            await Notice.filter(id=notice.id, latest_revision__lt=kb.revision).using_db(db).update(
                latest_revision=kb.revision, change_summary=(kb.history or [{}])[-1].get('change_summary', ''),
                updated_at=now())


async def unread_scope(user, skill_ids=None, db=None):
    query = Skill.filter(create_user_login_name=user_login_name(user), state=0)
    if skill_ids is not None:
        query = query.filter(id__in=skill_ids)
    skills = {s.id: s for s in await query.using_db(db)}
    if not skills:
        return [], {}
    bindings = await SkillResourceBinding.filter(skill_id__in=skills,
        skill_version_id__in=[s.current_version_id for s in skills.values()], source_type='knowledge_base').using_db(db)
    mounted = {(b.skill_id, b.source_id) for b in bindings if b.skill_version_id == skills[b.skill_id].current_version_id}
    knowledge = {k.id: k for k in await KnowledgeBase.filter(
        Q(user_id=user.id) | Q(is_public=True), id__in={kid for _, kid in mounted}, state__not=1).using_db(db)}
    notices = await Notice.filter(recipient_user_id=user.id, skill_id__in=skills,
        latest_revision__gt=F('read_revision')).using_db(db).order_by('-updated_at', 'id')
    return [n for n in notices if (n.skill_id, n.knowledge_base_id) in mounted and n.knowledge_base_id in knowledge], knowledge


async def counts(user, skill_ids=None, db=None):
    notices, _ = await unread_scope(user, skill_ids, db)
    result = {}
    for notice in notices:
        result[notice.skill_id] = result.get(notice.skill_id, 0) + 1
    return result


async def summary(user, db=None):
    result = await counts(user, db=db)
    return {'unread_skill_count': len(result), 'unread_update_count': sum(result.values()),
            'skill_counts': {str(key): value for key, value in result.items()}}


async def require_skill(skill_id, user, db=None):
    from .developer_service_v2 import DeveloperError
    skill = await Skill.filter(id=skill_id, state=0,
        create_user_login_name=user_login_name(user)).using_db(db).first()
    if not skill:
        raise DeveloperError('技能不存在或无提醒访问权限', 404)
    return skill


async def details(skill_id, user, db=None):
    await require_skill(skill_id, user, db)
    notices, knowledge = await unread_scope(user, [skill_id], db)
    # A conversion can finish while the knowledge list is on another page.
    # Reuse the canonical status projection before rendering its live state.
    from applications.knowledge_base.services.conversion_links import sync_knowledge_conversions
    for knowledge_id in {n.knowledge_base_id for n in notices}:
        await sync_knowledge_conversions(knowledge_id)
    # Batch current states; no historical state snapshot in the notification row.
    documents = await Document.filter(knowledge_base_id__in=knowledge).using_db(db).values(
        'knowledge_base_id', 'status', 'is_deleted', 'deletion_retryable')
    states = {}
    for doc in documents:
        state = getattr(doc['status'], 'value', doc['status'])
        if doc['is_deleted'] and not doc['deletion_retryable']:
            state = 'failed'
        elif doc['is_deleted'] and state not in {'deleting', 'delete_failed'}:
            continue
        states.setdefault(doc['knowledge_base_id'], []).append(state)
    def processing(kid):
        values = states.get(kid, [])
        if any(s in {'processing', 'deleting'} for s in values):
            return 'processing'
        return 'failed' if any(s in {'failed', 'delete_failed'} for s in values) else 'completed'
    return {'skill_id': skill_id, 'knowledge_update_count': len(notices), 'items': [{
        'notification_id': n.id, 'knowledge_base_id': n.knowledge_base_id,
        'knowledge_name': knowledge[n.knowledge_base_id].knowledge_name,
        'latest_revision': n.latest_revision, 'read_revision': n.read_revision,
        'from_version': next_version(n.read_revision), 'latest_version': next_version(n.latest_revision),
        'change_summary': n.change_summary, 'processing_status': processing(n.knowledge_base_id),
        'updated_at': n.updated_at.isoformat(),
    } for n in notices]}


async def mark_read(skill_id, items, user):
    from .developer_service_v2 import DeveloperError
    async with in_transaction() as db:
        await require_skill(skill_id, user, db)
        _, visible_knowledge = await unread_scope(user, [skill_id], db)
        # Read records too, so repeated acknowledgements are idempotent.
        records = await Notice.filter(id__in=[i.notification_id for i in items],
            recipient_user_id=user.id, skill_id=skill_id).using_db(db).select_for_update()
        by_id = {n.id: n for n in records}
        mounted = await SkillResourceBinding.filter(skill_id=skill_id,
            skill_version_id=(await require_skill(skill_id, user, db)).current_version_id,
            source_type='knowledge_base').using_db(db).values_list('source_id', flat=True)
        for item in items:
            notice = by_id.get(item.notification_id)
            if not notice or notice.knowledge_base_id not in mounted or notice.knowledge_base_id not in visible_knowledge:
                raise DeveloperError('提醒已失效或无操作权限，请刷新后重试', 404)
            if item.seen_revision > notice.latest_revision:
                raise DeveloperError('已读版本不能超过提醒版本')
        for item in items:
            await Notice.filter(id=item.notification_id, read_revision__lt=item.seen_revision).using_db(db).update(
                read_revision=item.seen_revision, read_at=now())
    return {**await details(skill_id, user), 'summary': await summary(user)}
