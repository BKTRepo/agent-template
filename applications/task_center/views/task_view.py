# -*- coding: utf-8 -*-
import traceback
from typing import Optional

from fastapi import APIRouter, Body, Depends, Form, Query
from tortoise.expressions import Q

from applications.task_center.dependencies import get_task_crud, get_task_record_crud
from applications.task_center.schemas.record_schema import TaskCenterRecordSelect
from applications.task_center.schemas.task_schema import (
    TaskCenterCreate,
    TaskCenterSelect,
    TaskCenterUpdate,
)
from applications.task_center.services.task_crud import TaskCenterCrud
from applications.task_center.services.task_record_crud import TaskCenterRecordCrud
from configure import LOGGER
from core.exceptions import (
    DataAlreadyExistsException,
    DataBaseStorageException,
    NotFoundException,
    ParameterException,
)
from core.responses import (
    DataBaseStorageResponse,
    FailureResponse,
    ParameterResponse,
    SuccessResponse,
)

tasks = APIRouter()

_TASK_DICT_EXCLUDE = {
    "state",
    "created_user", "created_time",
    "updated_user", "updated_time",
    "reserve_1", "reserve_2", "reserve_3",
}


@tasks.get("/presets", summary="任务中心-获取任务模板与调度选项")
async def list_task_presets():
    from applications.task_center.task_presets import SCHEDULER_OPTIONS, TASK_CENTER_PRESETS
    return SuccessResponse(
        message="查询成功",
        data={
            "presets": TASK_CENTER_PRESETS,
            "schedulers": SCHEDULER_OPTIONS,
        },
        total=len(TASK_CENTER_PRESETS),
    )


@tasks.post("/create", summary="任务中心-新增任务")
async def create_task_info(
        task_in: TaskCenterCreate = Body(..., description="任务信息"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        instance = await task_crud.create_task(task_in=task_in)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(message="新增成功", data=data, total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except (DataAlreadyExistsException, DataBaseStorageException) as e:
        return DataBaseStorageResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"新增任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"新增失败: {e}")


@tasks.delete("/delete", summary="任务中心-按id或code删除任务")
async def delete_task_info(
        task_id: Optional[int] = Query(None, description="任务ID"),
        task_code: Optional[str] = Query(None, description="任务标识代码"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        instance = await task_crud.delete_task(task_id=task_id, task_code=task_code)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(message="删除成功", data=data, total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"删除任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@tasks.post("/update", summary="任务中心-按id或code更新任务")
async def update_task_info(
        task_in: TaskCenterUpdate = Body(..., description="任务信息"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        instance = await task_crud.update_task(task_in=task_in)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(data=data, message="更新成功", total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except (DataAlreadyExistsException, DataBaseStorageException) as e:
        return DataBaseStorageResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"更新任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@tasks.get("/get", summary="任务中心-按id或code查询任务")
async def get_task_info(
        task_id: Optional[int] = Query(None, description="任务ID"),
        task_code: Optional[str] = Query(None, description="任务标识代码"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        if task_id:
            instance = await task_crud.get_by_id(task_id=task_id, on_error=True, state__not=1)
        else:
            instance = await task_crud.get_by_code(task_code=task_code, on_error=True, state__not=1)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(message="查询成功", data=data, total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"查询任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@tasks.post("/search", summary="任务中心-按条件查询任务")
async def search_tasks_info(
        task_in: TaskCenterSelect = Body(..., description="查询条件"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        q = Q()
        if task_in.task_id:
            q &= Q(id=task_in.task_id)
        if task_in.task_code:
            q &= Q(task_code=task_in.task_code)
        if task_in.task_name:
            q &= Q(task_name__contains=task_in.task_name)
        if task_in.task_type:
            q &= Q(task_type=task_in.task_type)
        if task_in.task_enabled is not None:
            q &= Q(task_enabled=task_in.task_enabled)
        if task_in.created_user:
            q &= Q(created_user__iexact=task_in.created_user)
        if task_in.updated_user:
            q &= Q(updated_user__iexact=task_in.updated_user)
        q &= Q(state=task_in.state)
        total, instances = await task_crud.select_tasks(
            search=q,
            page=task_in.page,
            page_size=task_in.page_size,
            order=task_in.order,
        )
        data = [
            await obj.to_dict(
                exclude_fields=_TASK_DICT_EXCLUDE,
                replace_fields={"id": "task_id"},
            )
            for obj in instances
        ]
        return SuccessResponse(message="查询成功", data=data, total=total)
    except ParameterException as e:
        return ParameterResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@tasks.post("/run", summary="任务中心-立即执行任务")
async def run_task_info(
        task_id: int = Form(..., description="任务ID"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        task = await task_crud.get_by_id(task_id=task_id, on_error=True, state__not=1)
        from celery_scheduler.tasks.task_dispatch import dispatch_task_center_task

        dispatch_task_center_task(task)
        LOGGER.info(f"已下发执行任务 task_id={task_id}")
        return SuccessResponse(
            message="已下发执行，请稍后在执行记录中查看结果",
            data={"task_id": task_id},
            total=1,
        )
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"执行任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"执行失败: {e}")


@tasks.post("/start", summary="任务中心-启动任务（启用调度）")
async def start_task_info(
        task_id: int = Form(..., description="任务ID"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        instance = await task_crud.set_task_enabled(task_id=task_id, enabled=True)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(message="任务已启动，将按调度执行", data=data, total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"启动任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"启动失败: {e}")


@tasks.post("/stop", summary="任务中心-停止任务（关闭调度）")
async def stop_task_info(
        task_id: int = Form(..., description="任务ID"),
        task_crud: TaskCenterCrud = Depends(get_task_crud),
):
    try:
        instance = await task_crud.set_task_enabled(task_id=task_id, enabled=False)
        data = await instance.to_dict(
            exclude_fields=_TASK_DICT_EXCLUDE,
            replace_fields={"id": "task_id"},
        )
        return SuccessResponse(message="任务已停止，将不再按调度执行", data=data, total=1)
    except (NotFoundException, ParameterException) as e:
        return ParameterResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"停止任务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"停止失败: {e}")


@tasks.post("/record/search", summary="任务中心-执行记录查询")
async def search_task_records(
        record_in: TaskCenterRecordSelect = Body(..., description="查询条件"),
        record_crud: TaskCenterRecordCrud = Depends(get_task_record_crud),
):
    try:
        total, instances = await record_crud.select_records(record_in=record_in)
        data = [
            await obj.to_dict(
                exclude_fields={"created_time", "updated_time"},
                replace_fields={"id": "record_id"},
            )
            for obj in instances
        ]
        return SuccessResponse(message="查询成功", data=data, total=total)
    except ParameterException as e:
        return ParameterResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询任务执行记录失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")
