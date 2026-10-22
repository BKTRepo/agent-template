"""开发者中心的持久化流程。页面只读取此处返回的数据。"""
from datetime import datetime

from tortoise.exceptions import IntegrityError
from applications.agent.models.agent_model import (
    DeveloperApplication, DeveloperSkillClass, Skill, SkillDebugRun, SkillVersion,
)
from applications.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm
from applications.agent.skill_names import SkillNameError, skill_name_key
from applications.base.services.scaffold import unique_identify
from applications.user.models.user_model import User
from core.exceptions import NotFoundException

STATUS_TEXT = {"DRAFT": "草稿", "DEBUGGING": "调试中", "ONLINE": "已上线", "OFFLINE": "已下线"}


class DeveloperSkillCrud:
    async def metadata(self) -> dict:
        classes = await DeveloperSkillClass.filter(is_enabled=True).order_by("sort_order", "id").values("id", "name")
        applications = await DeveloperApplication.filter(is_enabled=True).order_by("sort_order", "id").values("id", "name")
        return {"skill_classes": classes, "applications": applications}

    async def _validate_catalog(self, data: DeveloperSkillForm) -> None:
        if not await DeveloperSkillClass.filter(id=data.class_id, is_enabled=True).exists():
            raise ValueError("请选择有效的技能大类")
        if len(data.application_ids) > 1 or (data.application_ids and data.application_ids[0] == "" ):
            raise ValueError("请选择一个有效的所属应用")
        if data.application_ids:
            if not await DeveloperApplication.filter(id=data.application_ids[0], is_enabled=True).exists():
                raise ValueError("请选择应用目录中存在的应用")

    async def list(self, user: User):
        return await Skill.filter(user_id=user.id, state__not=1).order_by("-updated_time")

    async def get(self, skill_id: str, user: User) -> Skill:
        skill = await Skill.get_or_none(id=skill_id, user_id=user.id, state__not=1)
        if not skill:
            raise NotFoundException(message="技能不存在或无权操作")
        return skill

    @staticmethod
    def _config(data: DeveloperSkillForm) -> dict:
        return {"class_id": data.class_id, "application_ids": data.application_ids,
                "instructions": data.instructions, "resource_ids": data.resource_ids,
                "resource_usage": data.resource_usage, "compatibility": data.compatibility,
                "technical_name": data.technical_name, "uploaded_resources": data.uploaded_resources,
                "knowledge_bases": data.knowledge_bases, "skill_markdown": data.skill_markdown}

    async def _write_version(self, skill: Skill, data: DeveloperSkillForm, user: User):
        revision = skill.current_revision or 1
        version = f"1.0.{revision - 1}"
        version_id = unique_identify()
        await SkillVersion.create(
            id=version_id, skill_id=skill.id, version=version, revision=revision,
            skill_class_id=data.class_id, application_id=(data.application_ids or [None])[0],
            description=data.description, instructions=data.instructions,
            resource_usage=data.resource_usage or None, compatibility=data.compatibility or None,
            skill_markdown=data.skill_markdown, created_by=user.id,
        )
        skill.current_version_id = version_id

    async def create(self, user: User, data: DeveloperSkillForm) -> Skill:
        await self._validate_catalog(data)
        try:
            skill = await Skill.create(
                id=unique_identify(), name=data.name.strip(), name_key=skill_name_key(data.name),
                description=data.description, user_id=user.id, is_enabled=False,
                display_status="DRAFT", current_revision=1, config=self._config(data),
            )
        except IntegrityError as exc:
            raise SkillNameError("技能名称已存在，请使用其他名称") from exc
        await self._write_version(skill, data, user)
        await skill.save(update_fields=["current_version_id"])
        return skill

    async def save(self, skill_id: str, user: User, data: DeveloperSkillForm) -> Skill:
        await self._validate_catalog(data)
        skill = await self.get(skill_id, user)
        if await Skill.filter(name_key=skill_name_key(data.name), state__not=1).exclude(id=skill.id).exists():
            raise SkillNameError("技能名称已存在，请使用其他名称")
        skill.name = data.name.strip()
        skill.description = data.description
        skill.config = self._config(data)
        # 已上线内容一经修改，形成新草稿并重新调试。
        skill.display_status = "DRAFT"
        skill.is_enabled = False
        skill.last_debug_run_id = None
        skill.last_debug_passed_at = None
        skill.current_revision = (skill.current_revision or 0) + 1
        await self._write_version(skill, data, user)
        await skill.save()
        return skill

    async def delete_draft(self, skill_id: str, user: User) -> None:
        skill = await self.get(skill_id, user)
        if skill.display_status != "DRAFT":
            raise ValueError("只有草稿可以删除")
        skill.state = 1
        await skill.save(update_fields=["state"])

    async def offline(self, skill_id: str, user: User) -> Skill:
        skill = await self.get(skill_id, user)
        if skill.display_status != "ONLINE":
            raise ValueError("只有已上线技能可以下线")
        skill.display_status, skill.is_enabled, skill.offline_at = "OFFLINE", False, datetime.now()
        await skill.save(update_fields=["display_status", "is_enabled", "offline_at"])
        return skill

    async def publish(self, skill_id: str, user: User) -> Skill:
        skill = await self.get(skill_id, user)
        if not skill.last_debug_passed_at:
            raise ValueError("当前版本尚未取得沙箱调试通过结果，不能上线")
        skill.display_status, skill.is_enabled, skill.published_at = "ONLINE", True, datetime.now()
        await skill.save(update_fields=["display_status", "is_enabled", "published_at"])
        return skill

    async def record_debug_result(self, skill_id: str, user: User, data: DeveloperDebugResult) -> Skill:
        skill = await self.get(skill_id, user)
        if not skill.current_version_id:
            raise ValueError("当前技能尚未保存版本，不能登记调试结果")
        latest_build_id = (skill.config or {}).get("latest_build_id")
        if latest_build_id and data.build_id and latest_build_id != data.build_id:
            raise ValueError("调试结果不属于当前构建，请重新运行调试")
        now = datetime.now()
        status = data.status.upper()
        existing = await SkillDebugRun.get_or_none(run_id=data.run_id)
        if existing and (existing.skill_id != skill.id or existing.created_by != user.id):
            raise ValueError("该调试运行编号已被其他技能使用")
        values = {
            "skill_id": skill.id, "skill_version_id": skill.current_version_id,
            "build_id": data.build_id or latest_build_id, "status": status,
            "conversation_input": data.conversation_input or None,
            "request_document_count": data.request_document_count,
            "result_file_name": data.result_file_name,
            "result_byte_size": data.result_byte_size,
            "error_message": data.error_message,
            "finished_at": now, "created_by": user.id,
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            await existing.save()
        else:
            await SkillDebugRun.create(id=unique_identify(), run_id=data.run_id, **values)
        skill.last_debug_run_id = data.run_id
        skill.last_debug_passed_at = now if status == "PASSED" else None
        skill.display_status = "DEBUGGING"
        await skill.save(update_fields=["last_debug_run_id", "last_debug_passed_at", "display_status"])
        return skill

    @staticmethod
    def output(skill: Skill, user: User) -> dict:
        config = skill.config or {}
        build_id = config.get("latest_build_id")
        debug = None
        if skill.last_debug_run_id:
            debug = {"id": skill.last_debug_run_id, "runId": skill.last_debug_run_id,
                     "buildId": build_id, "status": "passed" if skill.last_debug_passed_at else "failed",
                     "output": "调试结果已由后端保存。", "origin": "backend"}
        return {"id": skill.id, "name": skill.name, "class_id": config.get("class_id", ""),
                "application_ids": config.get("application_ids", []), "description": skill.description or "",
                "instructions": config.get("instructions", ""), "resource_ids": config.get("resource_ids", []),
                "resource_usage": config.get("resource_usage", ""), "compatibility": config.get("compatibility", ""),
                "technical_name": config.get("technical_name", ""),
                "uploaded_resources": config.get("uploaded_resources", []),
                "knowledge_bases": config.get("knowledge_bases", []), "skill_markdown": config.get("skill_markdown"),
                "version": f"1.0.{max((skill.current_revision or 1) - 1, 0)}",
                "status": STATUS_TEXT.get(skill.display_status, "草稿"), "creator_id": str(user.id),
                "creator_name": user.alias, "updated_at": skill.updated_time,
                "backend_skill_id": skill.id, "build_id": build_id,
                "build_origin": "backend" if build_id else None, "debug": debug}
