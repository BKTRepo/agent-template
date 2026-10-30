# -*- coding: utf-8 -*-
from applications.model_config.services.model_config_crud import ModelConfigCrud


async def get_model_config_crud() -> ModelConfigCrud:
    """获取模型配置 CRUD 服务实例"""
    return ModelConfigCrud()
