# -*- coding: utf-8 -*-
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from tortoise.exceptions import FieldError
from tortoise.expressions import Q

from applications.base.services.scaffold import ScaffoldCrud
from applications.task_center.models.task_center_model import TaskCenterRecord
from applications.task_center.schemas.record_schema import (
    TaskCenterRecordCreate,
    TaskCenterRecordSelect,
    TaskCenterRecordUpdate,
)
from configure import LOGGER
from core.exceptions import ParameterException


class TaskCenterRecordCrud(ScaffoldCrud[TaskCenterRecord, TaskCenterRecordCreate, TaskCenterRecordUpdate]):
    def __init__(self):
        super().__init__(model=TaskCenterRecord)

    async def get_by_celery_id(self, celery_id: str) -> Optional[TaskCenterRecord]:
        if not celery_id:
            return None
        return await self.model.filter(celery_id=celery_id).first()

    async def create_record(self, data: Dict[str, Any]) -> TaskCenterRecord:
        return await self.create(data)

    async def update_record_by_celery_id(
            self,
            celery_id: str,
            data: Dict[str, Any],
    ) -> Optional[TaskCenterRecord]:
        record = await self.get_by_celery_id(celery_id=celery_id)
        if not record:
            return None
        allow_none_keys = ("task_summary", "task_error")
        update_dict = {
            k: v for k, v in data.items()
            if hasattr(record, k) and (v is not None or k in allow_none_keys)
        }
        for key, value in update_dict.items():
            setattr(record, key, value)
        await record.save(update_fields=list(update_dict.keys()))
        return record

    async def select_records(self, record_in: TaskCenterRecordSelect) -> tuple:
        try:
            q = Q()
            if record_in.celery_id:
                q &= Q(celery_id=record_in.celery_id)
            if record_in.task_id is not None:
                q &= Q(task_id=record_in.task_id)
            if record_in.task_version is not None:
                q &= Q(task_version=record_in.task_version)
            if record_in.task_name:
                q &= Q(task_name__contains=record_in.task_name)
            if record_in.task_celery_node:
                q &= Q(task_celery_node__contains=record_in.task_celery_node)
            if record_in.task_celery_status:
                q &= Q(task_celery_status=record_in.task_celery_status)
            if record_in.task_celery_scheduler:
                q &= Q(task_celery_scheduler=record_in.task_celery_scheduler)
            if record_in.celery_start_time_begin:
                try:
                    start_begin = datetime.strptime(record_in.celery_start_time_begin.strip()[:19], "%Y-%m-%d %H:%M:%S")
                    q &= Q(celery_start_time__gte=start_begin)
                except ValueError:
                    LOGGER.error(f"日期格式解析失败: celery_start_time_begin={record_in.celery_start_time_begin}")
                    raise ParameterException(message=f"日期格式错误: {record_in.celery_start_time_begin}")
            if record_in.celery_start_time_end:
                try:
                    start_end = datetime.strptime(record_in.celery_start_time_end.strip()[:19], "%Y-%m-%d %H:%M:%S")
                    q &= Q(celery_start_time__lte=start_end)
                except ValueError:
                    LOGGER.error(f"日期格式解析失败: celery_start_time_end={record_in.celery_start_time_end}")
                    raise ParameterException(message=f"日期格式错误: {record_in.celery_start_time_end}")
            if record_in.celery_end_time_begin:
                try:
                    end_begin = datetime.strptime(record_in.celery_end_time_begin.strip()[:19], "%Y-%m-%d %H:%M:%S")
                    q &= Q(celery_end_time__gte=end_begin)
                except ValueError:
                    LOGGER.error(f"日期格式解析失败: celery_end_time_begin={record_in.celery_end_time_begin}")
                    raise ParameterException(message=f"日期格式错误: {record_in.celery_end_time_begin}")
            if record_in.celery_end_time_end:
                try:
                    end_end = datetime.strptime(record_in.celery_end_time_end.strip()[:19], "%Y-%m-%d %H:%M:%S")
                    q &= Q(celery_end_time__lte=end_end)
                except ValueError:
                    LOGGER.error(f"日期格式解析失败: celery_end_time_end={record_in.celery_end_time_end}")
                    raise ParameterException(message=f"日期格式错误: {record_in.celery_end_time_end}")

            return await self.list(
                page=record_in.page,
                page_size=record_in.page_size,
                search=q,
                order=record_in.order or ["-celery_start_time", "-id"],
            )
        except FieldError as e:
            LOGGER.error(f"查询任务执行记录失败: {e}\n{traceback.format_exc()}")
            raise ParameterException(message=f"查询任务执行记录失败: {e}") from e
