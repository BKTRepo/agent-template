# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : model_config_view.py
@DateTime: 2026/6/9
"""
import traceback

from fastapi import APIRouter, Depends

from applications.model_config.dependencies import get_model_config_crud
from applications.model_config.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
)
from applications.model_config.services.model_config_crud import ModelConfigCrud
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import SuccessResponse, FailureResponse, NotFoundResponse
from services import DependAuth

model_config = APIRouter()


@model_config.get("/", summary="模型配置-查询配置列表")
async def list_model_configs(
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        items = await model_config_crud.list_configs(current_user)
        data = [
            ModelConfigOut.from_model(item).model_dump()
            for item in items
        ]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询模型配置列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@model_config.post("/", summary="模型配置-新增配置")
async def create_model_config(
        config_data: ModelConfigCreate,
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        instance = await model_config_crud.create_config(current_user, config_data)
        data = ModelConfigOut.from_model(instance).model_dump()
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"创建模型配置失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"创建失败: {e}")


@model_config.get("/default", summary="模型配置-查询默认配置")
async def get_default_config(
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        instance = await model_config_crud.get_default(current_user)
        data = ModelConfigOut.from_model(instance).model_dump()
        return SuccessResponse(data=data)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询默认模型配置失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@model_config.get("/{config_id}", summary="模型配置-按id查询配置详情")
async def get_model_config(
        config_id: str,
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        instance = await model_config_crud.get_config(config_id, current_user)
        data = ModelConfigOut.from_model(instance).model_dump()
        return SuccessResponse(data=data)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询模型配置详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@model_config.put("/{config_id}", summary="模型配置-按id更新配置")
async def update_model_config(
        config_id: str,
        config_data: ModelConfigUpdate,
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        instance = await model_config_crud.update_config(
            config_id, current_user, config_data
        )
        data = ModelConfigOut.from_model(instance).model_dump()
        return SuccessResponse(data=data)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新模型配置失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@model_config.delete("/{config_id}", summary="模型配置-按id删除配置")
async def delete_model_config(
        config_id: str,
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        await model_config_crud.delete_config(config_id, current_user)
        return SuccessResponse(message="模型配置已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除模型配置失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@model_config.post("/{config_id}/default", summary="模型配置-设为默认配置")
async def set_default_config(
        config_id: str,
        current_user: User = DependAuth,
        model_config_crud: ModelConfigCrud = Depends(get_model_config_crud),
):
    try:
        await model_config_crud.set_default(config_id, current_user)
        return SuccessResponse(message="已设为默认配置")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"设置默认模型配置失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"设置失败: {e}")
