"""技能中心只读目录：实现和发布快照均复用开发者中心表。"""
import io
import zipfile
from types import SimpleNamespace
from tortoise.expressions import F, Q, Subquery

from applications.wrq.agent.models.agent_model import (
    DeveloperSkillClass, Skill, SkillVersion, SkillForm,
    SkillResourceBinding,
)
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_package_service import SkillPackageService, SkillBuildNotFound
from applications.wrq.agent.services.skill_package_builder import SkillPackageError
from applications.wrq.agent.services.published_skill_version import display_skill_version
from applications.wrq.catalog import application_options
from applications.wrq.markdown_storage import read_markdown
from applications.wrq.agent.services.knowledge_reference_service import current_knowledge_references


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
        if online and not await DeveloperSkillClass.filter(id=form.skill_class_id, is_enabled=True).exists():
            raise DeveloperError('技能大类已停用，不能在线测试', 409)
        return skill, version, form

    @staticmethod
    def summary(skill, version, form):
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
                'call_count': skill.call_count, 'download_count': skill.download_count}

    async def metadata(self):
        classes = []
        for row in await DeveloperSkillClass.all().order_by('id'):
            classes.append({'id': row.id, 'name': row.name, 'is_enabled': row.is_enabled,
                            'description': row.description or ''})
        return {'skill_classes': classes, 'applications': await application_options(),
                'maintainers': [{'id': name, 'name': name} for name in sorted({
                    row.update_user_login_name or row.create_user_login_name for row in await self.visible()})]}

    async def class_detail(self, class_id):
        row = await DeveloperSkillClass.get_or_none(id=class_id)
        if not row:
            raise DeveloperError('技能大类不存在', 404)
        return {'id': row.id, 'name': row.name, 'is_enabled': row.is_enabled,
                'description': row.description or '', 'input_schema': row.input_schema,
                'output_schema': row.output_schema, 'template': row.template}

    async def list(self, *, name='', class_id=None, application='', maintainer='', page=1, page_size=10):
        page_size = max(1, min(page_size, 10))
        # 分类和应用取发布表单，避免当前草稿更换分类后污染目录。
        form_query = SkillForm.all()
        if name.strip():
            kinds = await DeveloperSkillClass.filter(name__icontains=name.strip()).values_list('id', flat=True)
            form_query = form_query.filter(Q(name__icontains=name.strip()) | Q(description__icontains=name.strip()) | Q(skill_class_id__in=kinds))
        if class_id is not None:
            form_query = form_query.filter(skill_class_id=class_id)
        if application:
            form_query = form_query.filter(application_paso__in=['*', application])
        query = self.visible().filter(published_version_id__in=Subquery(form_query.values('skill_version_id')))
        if maintainer:
            query = query.filter(Q(update_user_login_name=maintainer) |
                                 ((Q(update_user_login_name__isnull=True) | Q(update_user_login_name='')) & Q(create_user_login_name=maintainer)))
        total = await query.count()
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        skills = await query.order_by('-published_at', 'id').offset((page - 1) * page_size).limit(page_size)
        versions = {row.id: row for row in await SkillVersion.filter(id__in=[s.published_version_id for s in skills])}
        forms = {row.skill_version_id: row for row in await SkillForm.filter(skill_version_id__in=list(versions))}
        items = [self.summary(skill, versions[skill.published_version_id], forms[skill.published_version_id])
                 for skill in skills if skill.published_version_id in versions and skill.published_version_id in forms
                 and versions[skill.published_version_id].skill_id == skill.id]
        return {'items': items, 'total': total,
                'page': page, 'page_size': page_size, 'pages': pages}

    async def detail(self, skill_id):
        skill, version, form = await self.published(skill_id)
        knowledge = await current_knowledge_references(await SkillResourceBinding.filter(
            skill_version_id=version.id, source_type='knowledge_base').order_by('sort_order', 'id'))
        return {**self.summary(skill, version, form), 'instructions': form.instructions,
                'technical_name': form.technical_name, 'compatibility': form.compatibility or '',
                'resource_usage': form.resource_usage or '', 'resource_ids': [row['id'] for row in knowledge],
                'knowledge_bases': knowledge, 'uploaded_resources': [],
                'skill_markdown': display_skill_version(read_markdown(form.skill_markdown_path), version.version) if form.skill_markdown_path else ''}

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
