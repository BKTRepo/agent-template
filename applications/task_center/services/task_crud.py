# -*- coding: utf-8 -*-
import traceback
from typing import Any, Dict, Optional

from tortoise.exceptions import DoesNotExist, FieldError, IntegrityError
from tortoise.expressions import Q

from applications.base.services.scaffold import ScaffoldCrud
from applications.task_center.models.task_center_model import TaskCenterInfo
from applications.task_center.schemas.task_schema import TaskCenterCreate, TaskCenterUpdate
from configure import LOGGER
from core.exceptions import (
    DataAlreadyExistsException,
    DataBaseStorageException,
    NotFoundException,
    ParameterException,
)


class TaskCenterCrud(ScaffoldCrud[TaskCenterInfo, TaskCenterCreate, TaskCenterUpdate]):
    def __init__(self):
        super().__init__(model=TaskCenterInfo)

    @staticmethod
    def _next_task_version(current: Optional[int]) -> int:
        return (current or 0) + 1

    async def get_by_id(self, task_id: int, on_error: bool = False, **kwargs) -> Optional[TaskCenterInfo]:
        if not task_id:
            raise ParameterException(message="查询任务失败, 参数 task_id 不允许为空")
        instance = await self.get_or_none(id=task_id, **kwargs)
        if not instance and on_error:
            raise NotFoundException(message=f"任务(id={task_id})不存在")
        return instance

    async def get_by_code(self, task_code: str, on_error: bool = False, **kwargs) -> Optional[TaskCenterInfo]:
        if not task_code:
            raise ParameterException(message="查询任务失败, 参数 task_code 不允许为空")
        instance = await self.model.filter(task_code=task_code, **kwargs).first()
        if not instance and on_error:
            raise NotFoundException(message=f"任务(code={task_code})不存在")
        return instance

    async def create_task(self, task_in: TaskCenterCreate) -> TaskCenterInfo:
        existing = await self.model.filter(task_name=task_in.task_name, state__not=1).first()
        if existing:
            raise DataAlreadyExistsException(message=f"任务名称已存在: {task_in.task_name}")
        try:
            task_dict: Dict[str, Any] = task_in.model_dump(exclude_none=True, exclude_unset=True)
            if "task_celery_scheduler" in task_dict and task_dict["task_celery_scheduler"] is not None:
                task_dict["task_celery_scheduler"] = task_dict["task_celery_scheduler"].value
            if "task_celery_status" in task_dict and task_dict["task_celery_status"] is not None:
                task_dict["task_celery_status"] = task_dict["task_celery_status"].value
            if task_dict.get("task_enabled"):
                task_dict["task_version"] = 1
            else:
                task_dict.setdefault("task_version", 0)
            return await self.create(task_dict)
        except IntegrityError as e:
            LOGGER.error(f"新增任务失败: {e}\n{traceback.format_exc()}")
            raise DataBaseStorageException(message=f"新增任务失败: {e}") from e

    async def update_task(self, task_in: TaskCenterUpdate) -> TaskCenterInfo:
        task_id = task_in.task_id
        task_code = task_in.task_code
        if task_id:
            instance = await self.get_by_id(task_id=task_id, on_error=True, state__not=1)
        else:
            instance = await self.get_by_code(task_code=task_code, on_error=True, state__not=1)
            task_id = instance.id

        update_dict: Dict[str, Any] = task_in.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude={"task_id", "task_code"},
        )
        if "task_celery_scheduler" in update_dict and update_dict["task_celery_scheduler"] is not None:
            update_dict["task_celery_scheduler"] = update_dict["task_celery_scheduler"].value
        if "task_celery_status" in update_dict and update_dict["task_celery_status"] is not None:
            update_dict["task_celery_status"] = update_dict["task_celery_status"].value
        if update_dict.get("task_enabled") is True and not instance.task_enabled:
            update_dict["task_version"] = self._next_task_version(instance.task_version)

        task_name = update_dict.get("task_name", instance.task_name)
        existing = await self.model.filter(task_name=task_name, state__not=1).exclude(id=task_id).first()
        if existing:
            raise DataAlreadyExistsException(message=f"任务名称已存在: {task_name}")

        try:
            return await self.update(id=task_id, obj_in=update_dict)
        except DoesNotExist as e:
            raise NotFoundException(message=f"任务(id={task_id})不存在") from e
        except IntegrityError as e:
            raise DataBaseStorageException(message=f"更新任务失败: {e}") from e

    async def delete_task(self, task_id: Optional[int] = None, task_code: Optional[str] = None) -> TaskCenterInfo:
        if task_id:
            instance = await self.get_by_id(task_id=task_id, on_error=True, state__not=1)
        else:
            instance = await self.get_by_code(task_code=task_code, on_error=True, state__not=1)
        instance.state = 1
        instance.task_enabled = False
        await instance.save()
        return instance

    async def set_task_enabled(self, task_id: int, enabled: bool = True) -> TaskCenterInfo:
        instance = await self.get_by_id(task_id=task_id, on_error=True, state__not=1)
        update_fields = ["task_enabled"]
        if enabled:
            if not instance.task_enabled:
                instance.task_version = self._next_task_version(instance.task_version)
                update_fields.append("task_version")
            instance.task_enabled = True
        else:
            instance.task_enabled = False
        await instance.save(update_fields=update_fields)
        return instance

    async def select_tasks(self, search: Q, page: int, page_size: int, order: list) -> tuple:
        try:
            return await self.list(page=page, page_size=page_size, search=search, order=order)
        except FieldError as e:
            raise ParameterException(message=f"查询任务失败: {e}") from e
