"""复用现有 Skill 和知识库权限；只由数据库 ID 解析服务器文件路径。"""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from contextlib import ExitStack
import shutil

import anyio
from fastapi import UploadFile
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError

from applications.wrq.auth import user_login_name
from applications.wrq.markdown_storage import read_markdown, write_markdown, discard_markdown
from applications.wrq.agent.models.agent_model import Skill
from applications.wrq.agent.schemas.skill_package_schema import (
    MAX_SKILL_UPLOAD_FILES, SkillDeveloperForm, SkillPackageSource, SkillResourceBinding, SkillValidationReport, ValidationIssue,
)
from applications.wrq.agent.services.skill_package_builder import (
    ResolvedSkillResource, SkillPackageBuilder, SkillPackageError, validate_source, markdown_body,
)
from applications.wrq.agent.services.skill_upload_adapter import source_from_developer_form
from applications.wrq.agent.services.skill_resource_rules import resource_role
from applications.wrq.agent.services.agent_crud import SkillCrud
from applications.wrq.agent.skill_names import SkillNameError
from applications.wrq.knowledge_base.models.knowledge_base_model import Document, KnowledgeBase
from configure import PROJECT_CONFIG


class SkillBuildNotFound(Exception):
    pass


class LegacySkillPackageService:
    def __init__(self):
        self.builder = SkillPackageBuilder(
            Path(PROJECT_CONFIG.SKILL_BUILD_DIR),
            max_file_bytes=PROJECT_CONFIG.SKILL_RESOURCE_MAX_BYTES,
            max_total_bytes=PROJECT_CONFIG.SKILL_RESOURCE_TOTAL_MAX_BYTES,
        )

    async def require_skill(self, skill_id, user):
        # 与现有 SkillCrud.check_access 一致，不向其他用户暴露记录是否存在。
        skill = await Skill.filter(id=skill_id, create_user_login_name=user_login_name(user), state=0).first()
        if not skill:
            raise SkillBuildNotFound("技能不存在")
        return skill

    async def _knowledge_base(self, kb_id, user):
        kb = await KnowledgeBase.filter(id=kb_id, state__not=1).first()
        if not kb or (kb.user_id != user.id and not kb.is_public):
            return None
        return kb

    async def resolve(self, source: SkillPackageSource, user):
        """返回有效源、可用文件及报告；原文件内容在复制时再校验固定哈希。"""
        report = validate_source(source)
        source_error_count = len(report.errors)
        bindings = list(source.resources)
        selected = {binding.document_id for binding in bindings if binding.document_id}
        for index, kb_id in enumerate(dict.fromkeys(source.knowledge_base_ids)):
            kb = await self._knowledge_base(kb_id, user)
            if not kb:
                report.errors.append(ValidationIssue(field=f"knowledge_base_ids[{index}]",
                                                     reason="知识库不存在或无访问权限"))
                continue
            documents = await Document.filter(knowledge_base_id=kb.id, is_deleted=False).order_by("id").limit(101)
            if not documents:
                issues = report.errors if source.resource_usage is not None else report.warnings
                issues.append(ValidationIssue(field=f"knowledge_base_ids[{index}]",
                                               reason="知识库没有原文件，未生成资源快照"))
            for document in documents:
                if document.id in selected:
                    continue
                selected.add(document.id)
                # 原 ID 和哈希仍完整写入清单；短文件前缀避免 Windows 路径过长。
                prefix = hashlib.sha256(document.id.encode()).hexdigest()[:12]
                role = "reference"
                if source.resource_usage is not None:
                    try:
                        role = resource_role(document.filename)
                    except ValueError as exc:
                        report.errors.append(ValidationIssue(field=f"knowledge_base_ids[{index}]", reason=str(exc)))
                        continue
                bindings.append(SkillResourceBinding(document_id=document.id, role=role,
                                target_path=f"{prefix}-{document.filename}",
                                usage=source.resource_usage or "",
                                content_hash=document.content_hash))
        if len(bindings) > 100:
            report.errors.append(ValidationIssue(field="resources", reason="展开知识库后资源总数超过 100"))
            return source, [], report.finish()
        effective = source.model_copy(update={"resources": bindings})
        # 展开知识库产生的路径也必须经过同样的校验。
        expanded_report = validate_source(effective)
        report.errors = expanded_report.errors + report.errors[source_error_count:]
        resolved = []
        upload_root = PROJECT_CONFIG.upload_path.resolve()
        for index, binding in enumerate(bindings):
            if not binding.document_id:
                continue
            document = await Document.filter(id=binding.document_id, is_deleted=False).first()
            kb = await self._knowledge_base(document.knowledge_base_id, user) if document else None
            field = f"resources[{index}]"
            if not document or not kb:
                report.errors.append(ValidationIssue(field=field, reason="文件不存在或无访问权限"))
                continue
            path = Path(document.file_path).resolve()
            if not path.is_relative_to(upload_root) or not path.is_file():
                report.errors.append(ValidationIssue(field=field, reason="挂载原文件缺失或位于上传目录之外"))
                continue
            if source.resource_usage is not None and path.stat().st_size == 0:
                report.errors.append(ValidationIssue(field=field, reason="资源文件为空，请重新选择有效文件"))
                continue
            if binding.content_hash and document.content_hash and binding.content_hash != document.content_hash:
                report.errors.append(ValidationIssue(field=field, reason="所选文件哈希与当前版本不一致"))
                continue
            resolved.append(ResolvedSkillResource(index, path, document.filename, document.id, document.content_hash))
        return effective, resolved, report.finish()

    async def validate(self, skill_id, source, user):
        await self.require_skill(skill_id, user)
        _, _, report = await self.resolve(source, user)
        if any(item.upload_index is not None for item in source.resources):
            report.warnings.append(ValidationIssue(field="resources", reason="上传文件的内容和文件名将在构建时校验"))
        return report

    async def _discard(self, built):
        path = Path(built["workspace_dir"]).resolve()
        if path.is_relative_to(self.builder.root) and path.name == built["build_id"]:
            # 清理失败回滚时，目录可能已经被其他清理逻辑删除；回滚不能
            # 覆盖真正触发失败的异常。
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)

    async def build(self, skill_id, source, user, uploads: list[UploadFile] | None = None):
        await self.require_skill(skill_id, user)
        source, resources, report = await self.resolve(source, user)
        uploads = uploads or []
        if len(uploads) > MAX_SKILL_UPLOAD_FILES:
            report.errors.append(ValidationIssue(field="files", reason=f"每次最多上传 {MAX_SKILL_UPLOAD_FILES} 个文件"))
        indexes = {item.upload_index for item in source.resources if item.upload_index is not None}
        if indexes != set(range(len(uploads))):
            report.errors.append(ValidationIssue(field="resources", reason="upload_index 必须完整对应 files 中的每个上传文件"))
        if not report.valid or report.errors:
            raise SkillPackageError(report)
        staging_root = self.builder.root / ".uploads"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
            uploaded_paths = {}
            total = 0
            for index, upload in enumerate(uploads):
                path = Path(temporary) / str(index)
                size = 0
                async with await anyio.open_file(path, "xb") as stream:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        self.builder.check_file_size(size, f"files[{index}]")
                        if total > self.builder.max_total_bytes:
                            raise self.builder._issue("files", "直接上传资源合计不能超过 50MiB")
                        await stream.write(chunk)
                uploaded_paths[index] = path
                if source.resource_usage is not None and size == 0:
                    raise self.builder._issue(f"files[{index}]", "资源文件为空，请重新选择有效文件")
            for index, binding in enumerate(source.resources):
                if binding.upload_index is not None:
                    upload = uploads[binding.upload_index]
                    resources.append(ResolvedSkillResource(index, uploaded_paths[binding.upload_index], upload.filename or "resource"))
            return await asyncio.to_thread(self.builder.build, source, resources, user_id=user_login_name(user), skill_id=skill_id)

    async def get(self, skill_id, build_id, user, *, verify=False):
        await self.require_skill(skill_id, user)
        try:
            return await asyncio.to_thread(self.builder.read, user_id=user_login_name(user), skill_id=skill_id,
                                           build_id=build_id, verify=verify)
        except FileNotFoundError as exc:
            raise SkillBuildNotFound("构建记录不存在") from exc

    async def list_builds(self, skill_id, user, *, limit=20, offset=0):
        await self.require_skill(skill_id, user)
        return await asyncio.to_thread(self.builder.list_builds, user_id=user_login_name(user),
                                       skill_id=skill_id, limit=limit, offset=offset)

    async def download(self, skill_id, build_id, user):
        await self.get(skill_id, build_id, user)
        return await asyncio.to_thread(self.builder.archive_path, user_id=user_login_name(user),
                                       skill_id=skill_id, build_id=build_id)


class SkillPackageService(LegacySkillPackageService):
    async def build_form(self, form, user, uploads):
        from applications.wrq.agent.models.agent_model import SkillVersion, SkillForm, SkillResourceBinding, Source, ResourceCategory
        from applications.wrq.agent.services.version_service import version_and_form
        from applications.wrq.agent.services.developer_skill_crud import DeveloperError
        built = None
        definition_path = ''
        try:
            async with in_transaction() as db:
                skill = await Skill.filter(id=form.skill_id, create_user_login_name=user_login_name(user), state=0).using_db(db).select_for_update().first()
                if not skill:
                    raise SkillBuildNotFound("技能不存在")
                saved, content = await version_and_form(skill.current_version_id, db)
                if not saved or not content or (form.expected_version or None) != (saved.version or None):
                    raise DeveloperError("技能已被修改，请刷新后重试", 409)
                # multipart 表单中的 skill_class_id 可能被 Pydantic 保留为字符串，
                # 而数据库表单保存的是整数。比较前统一成整数，避免新建技能首次构建被误判为版本不一致。
                try:
                    form_skill_class_id = int(form.skill_class_id)
                except (TypeError, ValueError) as exc:
                    raise DeveloperError("技能大类信息无效，请刷新后重试", 409) from exc
                if (form.skill_name, form.description, form.instructions, form_skill_class_id, form.application_paso or None,
                        form.resource_usage or '', form.compatibility or '') != (content.name, content.description, content.instructions,
                        content.skill_class_id, content.application_paso, content.resource_usage or '', content.compatibility or ''):
                    raise DeveloperError("表单与保存版本不一致，请先保存修改", 409)
                if saved.build_id:
                    return await self.get(skill.id, saved.build_id, user, verify=True)
                links = await SkillResourceBinding.filter(skill_version_id=saved.id).exclude(file_id=None).using_db(db).order_by('sort_order','id')
                files = [await Source.filter(id=r.file_id).using_db(db).select_for_update().first() for r in links]
                if any(f is None or f.state == 'DELETED' or f.create_user_login_name != user_login_name(user) for f in files):
                    raise DeveloperError('挂载文件不存在或无访问权限',409)
                categories = {r.id: r.code for r in await ResourceCategory.all().using_db(db)}
                normalized = form.model_copy(update={'resource_categories': [categories[f.category_id] for f in files],
                                                    'skill_markdown': read_markdown(content.skill_markdown_path) or None})
                # 新建草稿尚未登记公开版本时，页面合同约定首次构建使用 1.0.0。
                # 数据库中的 version 仍可为 NULL，但不能把 NULL 传给构建器。
                source = source_from_developer_form(normalized, [f.file_name for f in files], technical_name=content.technical_name,
                    version=saved.version or "1.0.0", validate_catalog=False)
                source, resolved, report = await self.resolve(source, user)
                if not report.valid:
                    raise SkillPackageError(report)
                for index, file in enumerate(files):
                    path = Path(file.storage_key).resolve()
                    if not path.is_relative_to(self.builder.root) or not path.is_file():
                        raise DeveloperError("挂载原文件缺失，请重新上传", 409)
                    if file.sha256:
                        actual = await asyncio.to_thread(lambda p=path: hashlib.sha256(p.read_bytes()).hexdigest())
                        if actual != file.sha256:
                            raise DeveloperError("挂载原文件校验失败", 409)
                    resolved.append(ResolvedSkillResource(index, path, file.file_name, expected_hash=file.sha256))
                built = await asyncio.to_thread(self.builder.build, source, resolved, user_id=user_login_name(user), skill_id=skill.id)
                saved.build_id = built['build_id']
                saved.package_storage_key = str(Path(built['workspace_dir'])/'package.zip')
                manifest = Path(built['workspace_dir'])/'manifest.json'
                saved.manifest_hash = await asyncio.to_thread(lambda: hashlib.sha256(manifest.read_bytes()).hexdigest())
                raw = await asyncio.to_thread((Path(built['skill_directory'])/'SKILL.md').read_bytes)
                definition_path = write_markdown(skill.id, raw.decode('utf8'))
                content.skill_markdown_path = definition_path
                await content.save(using_db=db, update_fields=['skill_markdown_path'])
                saved.update_user_login_name = user_login_name(user)
                await saved.save(using_db=db, update_fields=['build_id', 'package_storage_key', 'manifest_hash', 'update_user_login_name', 'updated_time'])
                if skill.display_status in ('DRAFT','DEBUGGING'):
                    skill.display_status = 'DEBUGGING'
                skill.update_user_login_name = user_login_name(user)
                await skill.save(using_db=db)
            return {**built, 'skill_version_id': saved.id, 'current_revision': saved.revision}
        except BaseException:
            if built:
                await self._discard(built)
            discard_markdown(definition_path)
            raise

    async def get(self, skill_id, build_id, user, *, verify=False):
        from applications.wrq.agent.models.agent_model import SkillVersion
        await self.require_skill(skill_id, user)
        version = await SkillVersion.filter(skill_id=skill_id, build_id=build_id).first()
        if version and version.package_storage_key:
            package = Path(version.package_storage_key).resolve()
            if not package.is_relative_to(self.builder.root) or package.parent.name != build_id or not package.is_file():
                raise SkillBuildNotFound('构建原件不存在或位置无效')
            manifest = package.parent/'manifest.json'
            try:
                info = json.loads(manifest.read_bytes().decode('utf8'))
                owner = info.get('user_login_name', info.get('user_id'))
                built = await asyncio.to_thread(self.builder.read, user_id=owner,
                    skill_id=skill_id, build_id=build_id, verify=verify)
            except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
                raise SkillBuildNotFound('构建记录不存在') from exc
            if Path(built['workspace_dir']).resolve() != package.parent:
                raise SkillBuildNotFound('构建目录与已保存版本不一致')
            return {**built, 'skill_version_id':version.id, 'current_revision':version.revision}
        return await super().get(skill_id, build_id, user, verify=verify)

    async def list_builds(self, skill_id, user, *, limit=20, offset=0):
        from applications.wrq.agent.models.agent_model import SkillVersion
        await self.require_skill(skill_id, user)
        q = SkillVersion.filter(skill_id=skill_id).exclude(build_id=None).order_by('-revision')
        total = await q.count()
        items=[]
        for version in await q.offset(offset).limit(limit):
            try: items.append(await self.get(skill_id, version.build_id, user))
            except SkillBuildNotFound: continue
        return {'items':items,'total':total}

    async def download(self, skill_id, build_id, user):
        built = await self.get(skill_id, build_id, user, verify=True)
        return Path(built['workspace_dir'])/'package.zip'

    async def definition(self, skill_id, user):
        from applications.wrq.agent.services.version_service import version_and_form
        skill = await self.require_skill(skill_id, user)
        version, content = await version_and_form(skill.current_version_id)
        if not version or not content or not version.build_id:
            raise SkillBuildNotFound("请先生成当前版本的Skill定义")
        built = await self.get(skill_id, version.build_id, user, verify=True)
        return {'build': built, 'markdown': read_markdown(content.skill_markdown_path), 'version': version.version}

    async def rebuild_saved(self, skill_id, user, *, markdown=None, expected_version=None, knowledge_base_id=None, resource_usage=None):
        async with in_transaction():
            from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud, DeveloperError
            from applications.wrq.agent.schemas.agent_schema import DeveloperSkillForm
            crud = DeveloperSkillCrud()
            skill = await crud.get(skill_id, user)
            row = await crud.output(skill, user)
            if expected_version != row['version']:
                raise DeveloperError('技能已被修改，请刷新后重试', 409)
            if knowledge_base_id and knowledge_base_id not in row['resource_ids']:
                row['resource_ids'].append(knowledge_base_id)
            if resource_usage is not None:
                row['resource_usage'] = resource_usage
            if markdown is not None:
                row['instructions'] = markdown_body(markdown)
                row['skill_markdown'] = markdown
            data = DeveloperSkillForm(**row, expected_revision=skill.current_revision)
            updated = await crud.save(skill_id, user, data, definition=markdown is not None)
            row = await crud.output(updated, user)
            form = SkillDeveloperForm(skill_id=skill_id, skill_name=row['name'], description=row['description'],
                instructions=row['instructions'], skill_class_id=row['class_id'], application_paso=row['application_paso'],
                compatibility=row['compatibility'], resource_usage=row['resource_usage'], knowledge_base_ids=row['resource_ids'],
                resource_categories=[], expected_version=row['version'], skill_markdown=row['skill_markdown'] or None)
            return await self.build_form(form, user, [])

async def get_skill_package_service():
    return SkillPackageService()
