"""大类保存草稿、本人发布后可用；字典、所有权、修订号及删除保护共用一个事务入口。"""
import hashlib
import unicodedata
from collections import defaultdict

from tortoise.exceptions import IntegrityError
from tortoise.timezone import now
from tortoise.transactions import in_transaction

from applications.user.models.user_model import User
from applications.wrq.auth import user_login_name
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, TestStage, Skill, SkillForm
from .developer_skill_crud import DeveloperError, DeveloperSkillCrud


def normalize_class_name(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()


def class_name_key(value):
    return hashlib.sha256(normalize_class_name(value).encode('utf-8')).hexdigest()


def comparable_class_content(values):
    # textarea 使用 LF；模板保留缩进及空格，普通描述沿用请求模型的首尾去空白规则。
    result = {'test_stage_id': values['test_stage_id']}
    for key in ('name', 'description', 'input_description', 'output_description', 'template'):
        value = (values[key] or '').replace('\r\n', '\n').replace('\r', '\n')
        result[key] = value if key == 'template' else value.strip()
    return result


def available_classes():
    return DeveloperSkillClass.filter(state=0, is_enabled=True, publication_status="PUBLISHED")


async def require_available_class(class_id, db=None):
    query = DeveloperSkillClass.filter(state=0, id=class_id)
    if db is not None:
        query = query.using_db(db).select_for_update()
    row = await query.first()
    if not row:
        raise DeveloperError('技能大类不存在、已删除或已停用，请重新选择', 409, 'class_id')
    if row.publication_status != 'PUBLISHED':
        raise DeveloperError('该技能大类尚未发布', 409, 'class_id')
    if not row.is_enabled:
        raise DeveloperError('技能大类已停用，请重新选择', 409, 'class_id')
    return row


def published_content(row):
    fields = ('name', 'description', 'test_stage_id', 'input_description', 'output_description', 'template', 'input_schema', 'output_schema')
    # 旧预置大类没有快照，保留数据库直接补填历史字段的兼容性。
    return row.published_content if row.published_content is not None else {key: getattr(row, key) for key in fields}


async def stage_options():
    return await TestStage.filter(is_enabled=True).order_by('sort_order', 'id').values('id', 'code', 'name', 'description')


def class_option(row, stages, *, published=False):
    data = published_content(row) if published else {key: getattr(row, key) for key in ('name', 'description', 'test_stage_id')}
    stage = stages.get(data['test_stage_id'])
    return {'id': row.id, 'name': data['name'], 'is_enabled': row.is_enabled,
            'description': data['description'] or '', 'test_stage_id': data['test_stage_id'],
            'test_stage_name': stage.name if stage else None, 'test_stage_code': stage.code if stage else None}


async def class_options(*, available_only=True):
    stages = {row.id: row for row in await TestStage.all()}
    query = available_classes() if available_only else DeveloperSkillClass.filter(state=0, publication_status='PUBLISHED')
    return [class_option(row, stages, published=True) for row in await query.order_by('id')]


async def implementation_counts(class_ids=None, db=None):
    """Count distinct active implementations, including their currently published class."""
    query = Skill.filter(state=0)
    if db is not None:
        query = query.using_db(db)
    skills = await query.values('id', 'skill_classes_id', 'current_version_id', 'published_version_id')
    version_ids = {row[field] for row in skills for field in ('current_version_id', 'published_version_id') if row[field]}
    forms = SkillForm.filter(skill_version_id__in=version_ids)
    if db is not None:
        forms = forms.using_db(db)
    versions = {row['skill_version_id']: row['skill_class_id'] for row in await forms.values('skill_version_id', 'skill_class_id')}
    grouped = defaultdict(set)
    wanted = set(class_ids) if class_ids is not None else None
    for skill in skills:
        for class_id in {skill['skill_classes_id'], versions.get(skill['current_version_id']), versions.get(skill['published_version_id'])}:
            if class_id is not None and (wanted is None or class_id in wanted):
                grouped[class_id].add(skill['id'])
    return {key: len(ids) for key, ids in grouped.items()}


class SkillClassService:
    async def metadata(self):
        return {'test_stages': await stage_options(), 'skill_classes': await class_options()}

    async def _present(self, rows, user):
        counts = await implementation_counts([row.id for row in rows])
        stages = {row.id: row for row in await TestStage.all()}
        logins = {row.create_user_login_name for row in rows if row.create_user_login_name}
        users = await User.filter(username__in=logins)
        names = {row.username: row.alias or row.username for row in users}
        login = user_login_name(user) if user is not None else None
        result = []
        for row in rows:
            mine = bool(login and row.create_user_login_name == login)
            count = counts.get(row.id, 0)
            result.append({**class_option(row, stages), 'class_code': f'class-{row.id}',
                'input_description': row.input_description or '', 'output_description': row.output_description or '',
                'input_schema': row.input_schema, 'output_schema': row.output_schema, 'template': row.template or '',
                'creator_login_name': row.create_user_login_name,
                'maintainer_name': names.get(row.create_user_login_name, row.create_user_login_name or '未填写'),
                'created_time': row.created_time, 'updated_time': row.updated_time, 'revision': row.revision,
                'publication_status': row.publication_status, 'published_revision': row.published_revision, 'published_at': row.published_at,
                'has_unpublished_changes': row.publication_status == 'PUBLISHED' and row.published_revision != row.revision,
                'can_publish': mine and row.is_enabled and row.published_revision != row.revision,
                'can_create_implementation': row.publication_status == 'PUBLISHED' and row.is_enabled,
                'implementation_count': count, 'is_mine': mine, 'can_edit': mine, 'can_delete': mine and count == 0,
                'delete_disabled_reason': f'该大类下还有 {count} 个实现，需先清理后才能删除' if count else None})
        return result

    async def detail(self, class_id, user=None):
        row = await DeveloperSkillClass.get_or_none(id=class_id, state=0)
        if not row:
            raise DeveloperError('技能大类不存在或已删除', 404)
        return (await self._present([row], user))[0]

    async def list(self, user, *, test_stage_id=None, page=1, page_size=10):
        base = DeveloperSkillClass.filter(state=0)
        all_stages = await stage_options()
        # Stage rail counts always describe the whole active catalog.
        rows = await base.values('test_stage_id')
        counts = defaultdict(int)
        for row in rows:
            counts[row['test_stage_id']] += 1
        query = base.filter(test_stage_id=test_stage_id) if test_stage_id is not None else base
        total = await query.count()
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        items = await query.order_by('-updated_time', '-id').offset((page - 1) * page_size).limit(page_size)
        return {'items': await self._present(items, user), 'total': total, 'page': page, 'page_size': page_size,
                'pages': pages, 'summary': {'total': len(rows), 'covered_stages': sum(bool(counts[s['id']]) for s in all_stages),
                    'unassigned': counts[None], 'stages': [{**stage, 'count': counts[stage['id']]} for stage in all_stages]}}

    @staticmethod
    async def _validate(data, db, exclude_id=None):
        if not await TestStage.filter(id=data.test_stage_id, is_enabled=True).using_db(db).select_for_update().first():
            raise DeveloperError('请选择有效的测试阶段', 400, 'test_stage_id')
        rows = DeveloperSkillClass.filter(state=0)
        if exclude_id is not None:
            rows = rows.exclude(id=exclude_id)
        # Also covers legacy fixtures/data whose normalized key is not populated yet.
        if any(normalize_class_name(row.name) == normalize_class_name(data.name) or
               (row.publication_status == 'PUBLISHED' and normalize_class_name(published_content(row)['name']) == normalize_class_name(data.name))
               for row in await rows.using_db(db)):
            raise DeveloperError('已存在同名大类，请换一个名称', 409, 'name')

    @staticmethod
    async def _owned(class_id, user, expected_revision, db):
        row = await DeveloperSkillClass.filter(id=class_id, state=0).using_db(db).select_for_update().first()
        if not row:
            raise DeveloperError('技能大类不存在或已删除', 404)
        if row.create_user_login_name != user_login_name(user):
            raise DeveloperError('仅维护人可修改该大类', 403)
        if row.revision != expected_revision:
            raise DeveloperError('大类已被修改，请刷新后重试', 409)
        return row

    async def create(self, data, user):
        try:
            async with in_transaction() as db:
                await DeveloperSkillCrud.lock_name_catalog(db)
                await self._validate(data, db)
                row = await DeveloperSkillClass.create(using_db=db, **data.model_dump(),
                    active_name_key=class_name_key(data.name), create_user_login_name=user_login_name(user),
                    update_user_login_name=user_login_name(user))
        except IntegrityError as exc:
            raise DeveloperError('已存在同名大类，请换一个名称', 409, 'name') from exc
        return await self.detail(row.id, user)

    async def update(self, data, user):
        try:
            async with in_transaction() as db:
                await DeveloperSkillCrud.lock_name_catalog(db)
                row = await self._owned(data.class_id, user, data.expected_revision, db)
                values = data.model_dump(exclude={'class_id', 'expected_revision'})
                changed = comparable_class_content(values) != comparable_class_content({key: getattr(row, key) for key in values})
                if changed:
                    await self._validate(data, db, row.id)
                    if row.publication_status == 'PUBLISHED' and row.published_content is None:
                        row.published_content = published_content(row)
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.active_name_key = class_name_key(data.name)
                    row.update_user_login_name = user_login_name(user)
                    row.revision += 1
                    await row.save(using_db=db)
        except IntegrityError as exc:
            raise DeveloperError('已存在同名大类，请换一个名称', 409, 'name') from exc
        return {**await self.detail(row.id, user), 'changed': changed}

    async def publish(self, data, user):
        async with in_transaction() as db:
            await DeveloperSkillCrud.lock_name_catalog(db)
            row = await self._owned(data.class_id, user, data.expected_revision, db)
            if row.publication_status == 'PUBLISHED' and row.published_revision == row.revision:
                raise DeveloperError('该大类已发布且没有待发布修改', 409)
            if not row.is_enabled:
                raise DeveloperError('技能大类已停用，不能发布', 409)
            if not (row.output_description or '').strip():
                raise DeveloperError('发布前请补全输出描述', 400, 'output_description')
            from ..schemas.skill_class_schema import SkillClassCreate
            from pydantic import ValidationError
            fields = ('name', 'description', 'test_stage_id', 'input_description', 'output_description', 'template')
            try:
                form = SkillClassCreate.model_validate({key: getattr(row, key) for key in fields})
            except ValidationError as exc:
                raise DeveloperError('发布前请补全大类名称、测试阶段、功能说明、输入描述及Skill模板', 400) from exc
            await self._validate(form, db, row.id)
            row.revision += 1
            row.publication_status = 'PUBLISHED'
            row.published_revision = row.revision
            row.published_content = {**form.model_dump(), 'input_schema': row.input_schema, 'output_schema': row.output_schema}
            row.published_at = now()
            row.update_user_login_name = user_login_name(user)
            await row.save(using_db=db)
        return await self.detail(row.id, user)

    async def remove(self, data, user):
        async with in_transaction() as db:
            # Same lock order as create/save/import; no implementation can enter
            # between this reference check and the logical deletion.
            await DeveloperSkillCrud.lock_name_catalog(db)
            row = await self._owned(data.class_id, user, data.expected_revision, db)
            count = (await implementation_counts([row.id], db)).get(row.id, 0)
            if count:
                raise DeveloperError(f'该大类下还有 {count} 个实现，需先清理后才能删除', 409)
            row.state, row.active_name_key, row.deleted_time = 1, None, now()
            row.revision += 1
            row.update_user_login_name = user_login_name(user)
            await row.save(using_db=db)
        return {'removed': True, 'class_id': row.id, 'name': row.name}
