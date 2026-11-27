"""技能中心只读目录：实现和发布快照均复用开发者中心表。"""
import io
import zipfile
from types import SimpleNamespace
from tortoise.expressions import F, Q, Subquery
from tortoise.functions import Count
from applications.chat.models.chat_model import ChatSkillCall

from applications.wrq.agent.models.agent_model import (
    DeveloperSkillClass, Skill, SkillVersion, SkillForm,
)
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_package_service import SkillPackageService, SkillBuildNotFound
from applications.wrq.agent.services.skill_package_builder import SkillPackageError
from applications.wrq.agent.services.published_skill_version import display_skill_version
from applications.wrq.catalog import application_options
from applications.wrq.markdown_storage import read_markdown
from applications.wrq.agent.services.skill_knowledge_scope import visible_skill_knowledge


class SkillCatalogService:
    @staticmethod
    def visible():
        # 目录面向已认证平台用户；个人写权限仍由开发者中心独立校验。
        return Skill.filter(state=0, display_status__in=['ONLINE', 'OFFLINE']).exclude(published_version_id=None)

    async def published(self, skill_id, *, online=False):
        skill = await self.visible().filter(id=skill_id).first()
        if not skill:
            raise DeveloperError('技能不存在或尚未发布', 404)
        if online and skill.display_status != 'ONLINE':
            raise DeveloperError('技能已下线，不能在线测试', 409)
        version = await SkillVersion.get_or_none(id=skill.published_version_id, skill_id=skill.id)
        form = await SkillForm.get_or_none(skill_version_id=skill.published_version_id)
        if not version or not form:
            raise DeveloperError('发布版本或表单缺失，请联系维护人', 409)
        from .skill_class_service import require_available_class
        await require_available_class(form.skill_class_id, published_snapshot=True)
        return skill, version, form

    @staticmethod
    def summary(skill, version, form, chat_calls=0):
        maintainer = skill.update_user_login_name or skill.create_user_login_name
        return {'id': skill.id, 'name': form.name, 'class_id': form.skill_class_id,
                'application_ids': [form.application_paso] if form.application_paso else [],
                'description': form.description, 'version': version.version,
                'skill_version_id': version.id, 'current_revision': version.revision,
                'status': '已上线' if skill.display_status == 'ONLINE' else '已下线',
                'creator_login_name': skill.create_user_login_name, 'creator_name': skill.create_user_login_name,
                'maintainer_id': maintainer, 'maintainer_name': maintainer,
                'updated_at': skill.updated_time, 'build_id': version.build_id,
                'backend_skill_id': skill.id, 'build_origin': 'backend' if version.build_id else None,
                'call_count': (skill.call_count or 0) + chat_calls, 'download_count': skill.download_count}

    @staticmethod
    async def chat_call_counts(skill_ids):
        if not skill_ids:
            return {}
        rows = await ChatSkillCall.filter(skill_id__in=skill_ids).group_by('skill_id').annotate(
            count=Count('id'),
        ).values('skill_id', 'count')
        return {row['skill_id']: row['count'] for row in rows}

    async def metadata(self):
        from .skill_class_service import class_options, stage_options
        classes = await class_options(available_only=False)
        class_ids = {row['id'] for row in classes}
        skills = await self.visible().filter(display_status='ONLINE').values(
            'id', 'published_version_id', 'update_user_login_name', 'create_user_login_name')
        versions = {row.id: row for row in await SkillVersion.filter(id__in=[row['published_version_id'] for row in skills])}
        forms = {row.skill_version_id: row for row in await SkillForm.filter(skill_version_id__in=list(versions))}
        relations = set()
        for skill in skills:
            version = versions.get(skill['published_version_id'])
            form = forms.get(skill['published_version_id'])
            if version and version.skill_id == skill['id'] and form and form.skill_class_id in class_ids:
                relations.add((form.skill_class_id, skill['update_user_login_name'] or skill['create_user_login_name'] or ''))
        # 零实现大类仍参与阶段/大类联动，但不虚构维护人；关系取发布表单，不取编辑中的分类。
        represented = {class_id for class_id, _ in relations}
        relations.update((class_id, '') for class_id in class_ids - represented)
        return {'skill_classes': classes, 'test_stages': await stage_options(), 'applications': await application_options(),
                'maintainers': [{'id': name, 'name': name} for name in sorted({name for _, name in relations if name})],
                'filter_relations': [{'class_id': class_id, 'maintainer': maintainer} for class_id, maintainer in sorted(relations)]}

    async def class_detail(self, class_id):
        from .skill_class_service import class_option, require_available_class, published_content
        from applications.wrq.agent.models.agent_model import TestStage
        row = await require_available_class(class_id, published_snapshot=True)
        stages = {stage.id: stage for stage in await TestStage.all()}
        data = published_content(row)
        return {**class_option(row, stages, published=True), **{key: data.get(key) or '' for key in ('input_description', 'output_description', 'template')},
                'input_schema': data.get('input_schema'), 'output_schema': data.get('output_schema')}

    async def list(self, *, name='', class_id=None, test_stage_id=None, application='', maintainer='', page=1, page_size=10, online_only=True):
        page_size = max(1, min(page_size, 10))
        # 分类和应用取发布表单，避免当前草稿更换分类后污染目录。
        form_query = SkillForm.all()
        from .skill_class_service import class_options
        classes = await class_options(available_only=False)
        if class_id is not None:
            from .skill_class_service import require_available_class
            await require_available_class(class_id, published_snapshot=True)
        if test_stage_id is not None:
            classes = [row for row in classes if row['test_stage_id'] == test_stage_id]
        form_query = form_query.filter(skill_class_id__in=[row['id'] for row in classes])
        if name.strip():
            kinds = [row['id'] for row in classes if name.strip().casefold() in row['name'].casefold()]
            form_query = form_query.filter(Q(name__icontains=name.strip()) | Q(description__icontains=name.strip()) | Q(skill_class_id__in=kinds))
        if class_id is not None:
            form_query = form_query.filter(skill_class_id=class_id)
        if application:
            form_query = form_query.filter(application_paso__in=['*', application])
        query = self.visible().filter(published_version_id__in=Subquery(form_query.values('skill_version_id')))
        if online_only:
            query = query.filter(display_status='ONLINE')
        if maintainer:
            query = query.filter(Q(update_user_login_name=maintainer) |
                                 ((Q(update_user_login_name__isnull=True) | Q(update_user_login_name='')) & Q(create_user_login_name=maintainer)))
        total = await query.count()
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        skills = await query.order_by('-published_at', 'id').offset((page - 1) * page_size).limit(page_size)
        versions = {row.id: row for row in await SkillVersion.filter(id__in=[s.published_version_id for s in skills])}
        forms = {row.skill_version_id: row for row in await SkillForm.filter(skill_version_id__in=list(versions))}
        calls = await self.chat_call_counts([skill.id for skill in skills])
        items = [self.summary(skill, versions[skill.published_version_id], forms[skill.published_version_id], calls.get(skill.id, 0))
                 for skill in skills if skill.published_version_id in versions and skill.published_version_id in forms
                 and versions[skill.published_version_id].skill_id == skill.id]
        return {'items': items, 'total': total,
                'page': page, 'page_size': page_size, 'pages': pages}

    async def detail(self, skill_id, user):
        skill, version, form = await self.published(skill_id)
        knowledge = await visible_skill_knowledge(version.id, user)
        calls = await self.chat_call_counts([skill.id])
        skill_markdown = ''
        if form.skill_markdown_path:
            try:
                skill_markdown = display_skill_version(read_markdown(form.skill_markdown_path), version.version,
                                                       omit_resource_notes=form.definition_origin == "import")
            except FileNotFoundError:
                # 对话台加载 Skill 仍需要其资源绑定；定义原件缺失不应阻断该只读元数据。
                skill_markdown = ''
        return {**self.summary(skill, version, form, calls.get(skill.id, 0)), 'instructions': form.instructions,
                'technical_name': form.technical_name, 'compatibility': form.compatibility or '',
                'resource_usage': form.resource_usage or '', 'resource_ids': [row['id'] for row in knowledge],
                'knowledge_bases': knowledge, 'uploaded_resources': [],
                'skill_markdown': skill_markdown}

    async def package(self, skill_id, build_id, *, online=False):
        skill, version, _ = await self.published(skill_id, online=online)
        if not version.build_id or version.build_id != build_id:
            raise DeveloperError('发布构建已变更或缺失，请刷新技能目录', 409)
        # 先核实公开发布指针，再在服务内部读取该所有者的固定构建；不放宽私人构建接口。
        owner = SimpleNamespace(login_name=skill.create_user_login_name)
        packages = SkillPackageService()
        try:
            built = await packages.get(skill.id, version.build_id, owner, verify=True)
        except (SkillBuildNotFound, SkillPackageError, FileNotFoundError) as exc:
            raise DeveloperError('发布构建原件缺失，请联系维护人', 409) from exc
        return packages, built, version

    async def download(self, skill_id, build_id):
        packages, built, version = await self.package(skill_id, build_id)
        content = packages._published_archive(built, version.version)[0]
        changed = await self.visible().filter(id=skill_id, published_version_id=version.id).update(download_count=F('download_count') + 1)
        if not changed:
            raise DeveloperError('发布版本已变更，请刷新后重试下载', 409)
        return content

    async def resource(self, skill_id, build_id, path):
        packages, built, version = await self.package(skill_id, build_id, online=True)
        if path not in {row['path'] for row in built['files'] if row['path'] not in ('SKILL.md', 'manifest.json')}:
            raise DeveloperError('资源不属于当前发布构建', 404)
        archive = packages._published_archive(built, version.version)[0]
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            return package.read(f"{built['name']}/{path}")
