"""复用现有 Skill 和知识库权限；只由数据库 ID 解析服务器文件路径。"""
import asyncio
import hashlib
from pathlib import Path
import tempfile
from contextlib import ExitStack
import shutil

import anyio
from fastapi import UploadFile
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError

from applications.agent.models.agent_model import Skill
from applications.agent.schemas.skill_package_schema import (
    MAX_SKILL_UPLOAD_FILES, SkillDeveloperForm, SkillPackageSource, SkillResourceBinding, SkillValidationReport, ValidationIssue,
)
from applications.agent.services.skill_package_builder import (
    ResolvedSkillResource, SkillPackageBuilder, SkillPackageError, validate_source, markdown_body,
)
from applications.agent.services.skill_upload_adapter import source_from_developer_form
from applications.agent.services.skill_resource_rules import resource_role
from applications.agent.services.agent_crud import SkillCrud
from applications.agent.skill_names import SkillNameError
from applications.knowledge_base.models.knowledge_base_model import Document, KnowledgeBase
from configure import PROJECT_CONFIG


class SkillBuildNotFound(Exception):
    pass


class SkillPackageService:
    def __init__(self):
        self.builder = SkillPackageBuilder(
            Path(PROJECT_CONFIG.SKILL_BUILD_DIR),
            max_file_bytes=PROJECT_CONFIG.SKILL_RESOURCE_MAX_BYTES,
            max_total_bytes=PROJECT_CONFIG.SKILL_RESOURCE_TOTAL_MAX_BYTES,
        )

    async def require_skill(self, skill_id, user):
        # 与现有 SkillCrud.check_access 一致，不向其他用户暴露记录是否存在。
        skill = await Skill.filter(id=skill_id, user_id=user.id, state__not=1).first()
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

    async def build_form(self, form: SkillDeveloperForm, user, uploads: list[UploadFile]):
        # 技能记录仍复用现有 POST /skills/；校验权限后从服务端历史取得包标识。
        if not form.skill_id:
            raise SkillPackageError(SkillValidationReport(missing_fields=[
                ValidationIssue(field="skill_id", reason="请先创建技能记录")]))
        skill = await self.require_skill(form.skill_id, user)
        built = None
        try:
            async with in_transaction() as connection:
                # 先占用名称再生成，避免生成成功后才发现并发重名；构建失败回滚名称。
                skill = await Skill.filter(id=form.skill_id, user_id=user.id, state__not=1).using_db(connection).select_for_update().first()
                if not skill:
                    raise SkillBuildNotFound("技能不存在")
                history = await self.list_builds(form.skill_id, user, limit=1)
                previous = history["items"][0] if history["items"] else {}
                config = dict(skill.config or {})
                if form.expected_version and form.expected_version != f"1.0.{config.get('parser_revision', 0)}":
                    raise self.builder._issue("expected_version", "技能已被修改，请刷新后重试")
                revision = int(config.get("parser_revision", -1)) + 1
                source = source_from_developer_form(
                    form, [upload.filename or "resource" for upload in uploads],
                    technical_name=previous.get("name"), version=f"1.0.{revision}",
                )
                await SkillCrud().require_available_name(source.display_name, exclude_id=skill.id, using_db=connection)
                skill.name = source.display_name
                skill.description = source.description
                built = await self.build(form.skill_id, source, user, uploads)
                config.update(parser_revision=revision, latest_build_id=built["build_id"],
                              parser_source=source.model_dump(mode="json"))
                skill.config = config
                await skill.save(using_db=connection, update_fields=["name", "description", "config", "updated_time"])
            return built
        except (SkillNameError, IntegrityError) as exc:
            if built:
                await self._discard(built)
            reason = str(exc) if isinstance(exc, SkillNameError) else "技能名称已存在，请使用其他名称"
            raise SkillPackageError(SkillValidationReport(errors=[ValidationIssue(field="skill_name", reason=reason)])) from exc
        except BaseException:
            if built:
                await self._discard(built)
            raise

    async def _discard(self, built):
        path = Path(built["workspace_dir"]).resolve()
        if path.is_relative_to(self.builder.root) and path.name == built["build_id"]:
            await asyncio.to_thread(shutil.rmtree, path)

    async def definition(self, skill_id, user):
        skill = await self.require_skill(skill_id, user)
        build_id = (skill.config or {}).get("latest_build_id")
        if not build_id:
            raise SkillBuildNotFound("请先生成 Skill 包")
        built = await self.get(skill_id, build_id, user, verify=True)
        markdown = await asyncio.to_thread((Path(built["skill_directory"]) / "SKILL.md").read_text, encoding="utf-8")
        return {"build": built, "markdown": markdown, "version": built["version"]}

    async def rebuild_saved(self, skill_id, user, *, markdown=None, expected_version=None,
                            knowledge_base_id=None, resource_usage=None):
        current = await self.definition(skill_id, user)
        built, source = current["build"], current["build"]["source"]
        if expected_version and expected_version != built["version"]:
            raise self.builder._issue("expected_version", "技能已被修改，请刷新后重试")
        entries = [entry for entry in built["files"] if entry["role"] != "instructions"]
        categories, uploads = [], []
        knowledge_ids = list(source.get("knowledge_base_ids", []))
        if knowledge_base_id and knowledge_base_id not in knowledge_ids:
            knowledge_ids.append(knowledge_base_id)
        with ExitStack() as stack:
            for binding, entry in zip(source["resources"], entries):
                if binding.get("upload_index") is None:
                    continue
                path = Path(built["skill_directory"]) / entry["path"]
                categories.append(binding.get("category") or binding["role"])
                uploads.append(UploadFile(filename=path.name, file=stack.enter_context(path.open("rb"))))
            form = SkillDeveloperForm(skill_id=skill_id, skill_name=source["display_name"],
                description=source["description"], instructions=markdown_body(markdown) if markdown is not None else source["instructions"],
                skill_class_id=source.get("skill_class_id") or "", application=source.get("application"),
                compatibility=source.get("compatibility", ""), resource_categories=categories,
                resource_usage=resource_usage if resource_usage is not None else (source.get("resource_usage") or ""),
                knowledge_base_ids=knowledge_ids, expected_version=expected_version or built["version"],
                skill_markdown=markdown if markdown is not None else source.get("skill_markdown"))
            return await self.build_form(form, user, uploads)

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
            return await asyncio.to_thread(self.builder.build, source, resources, user_id=user.id, skill_id=skill_id)

    async def get(self, skill_id, build_id, user, *, verify=False):
        await self.require_skill(skill_id, user)
        try:
            return await asyncio.to_thread(self.builder.read, user_id=user.id, skill_id=skill_id,
                                           build_id=build_id, verify=verify)
        except FileNotFoundError as exc:
            raise SkillBuildNotFound("构建记录不存在") from exc

    async def list_builds(self, skill_id, user, *, limit=20, offset=0):
        await self.require_skill(skill_id, user)
        return await asyncio.to_thread(self.builder.list_builds, user_id=user.id,
                                       skill_id=skill_id, limit=limit, offset=offset)

    async def download(self, skill_id, build_id, user):
        await self.get(skill_id, build_id, user)
        return await asyncio.to_thread(self.builder.archive_path, user_id=user.id,
                                       skill_id=skill_id, build_id=build_id)


async def get_skill_package_service():
    return SkillPackageService()
