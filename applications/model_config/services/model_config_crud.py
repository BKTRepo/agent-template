# -*- coding: utf-8 -*-
from typing import List, Optional

from applications.base.services.scaffold import ScaffoldCrud
from applications.model_config.models.model_config_model import ModelConfig
from applications.model_config.schemas.model_config_schema import (
    ModelConfigCreate,
    ModelConfigUpdate,
)
from applications.model_config.services.secret_utils import encrypt_api_key
from applications.user.models.user_model import User
from core.exceptions import NotFoundException


class ModelConfigCrud(ScaffoldCrud[ModelConfig, ModelConfigCreate, ModelConfigUpdate]):
    def __init__(self):
        super().__init__(model=ModelConfig)

    @staticmethod
    def _should_skip_api_key_update(value: Optional[str]) -> bool:
        if value is None:
            return True
        stripped = value.strip()
        if not stripped:
            return True
        return "***" in stripped

    @staticmethod
    def _prepare_api_key(value: Optional[str]) -> Optional[str]:
        if not value or not value.strip():
            return None
        return encrypt_api_key(value.strip())

    def _prepare_create_dict(self, data: ModelConfigCreate) -> dict:
        obj_dict = data.create_dict()
        if "llm_api_key" in obj_dict:
            obj_dict["llm_api_key"] = self._prepare_api_key(obj_dict.get("llm_api_key"))
        return obj_dict

    def _prepare_update_dict(self, data: ModelConfigUpdate) -> dict:
        obj_dict = data.model_dump(exclude_unset=True, exclude={"config_id"})
        if "llm_api_key" in obj_dict:
            if self._should_skip_api_key_update(obj_dict.get("llm_api_key")):
                obj_dict.pop("llm_api_key")
            else:
                obj_dict["llm_api_key"] = self._prepare_api_key(obj_dict["llm_api_key"])
        return obj_dict

    async def list_by_user(self, user_id: int) -> List[ModelConfig]:
        """获取用户的模型配置列表"""
        return await self.model.filter(user_id=user_id).order_by(
            "-is_default", "-created_time"
        )

    async def get_by_id_and_user(
        self, config_id: str, user_id: int
    ) -> Optional[ModelConfig]:
        """根据 ID 和用户 ID 获取模型配置"""
        return await self.model.get_or_none(id=config_id, user_id=user_id)

    async def get_default_config(self, user_id: int) -> Optional[ModelConfig]:
        """获取用户的默认模型配置"""
        config = await self.model.get_or_none(user_id=user_id, is_default=True)
        if config:
            return config
        return await self.model.filter(user_id=user_id).order_by("created_time").first()

    async def clear_default(
        self, user_id: int, exclude_id: Optional[str] = None
    ) -> None:
        """清除用户的默认配置标记"""
        qs = self.model.filter(user_id=user_id, is_default=True)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        await qs.update(is_default=False)

    async def get_first_other(
        self, user_id: int, exclude_id: str
    ) -> Optional[ModelConfig]:
        """获取用户除指定配置外的第一条配置"""
        return (
            await self.model.filter(user_id=user_id)
            .exclude(id=exclude_id)
            .order_by("created_time")
            .first()
        )

    async def list_configs(self, current_user: User) -> List[ModelConfig]:
        """获取当前用户自己的模型配置列表"""
        return await self.list_by_user(current_user.id)

    async def create_config(
        self, current_user: User, data: ModelConfigCreate
    ) -> ModelConfig:
        """创建模型配置"""
        if data.is_default:
            await self.clear_default(current_user.id)
        obj_dict = self._prepare_create_dict(data)
        obj_dict["user_id"] = current_user.id
        return await self.create(obj_dict)

    async def get_config(self, config_id: str, current_user: User) -> ModelConfig:
        """获取指定模型配置"""
        config = await self.get_by_id_and_user(config_id, current_user.id)
        if not config:
            raise NotFoundException(message="模型配置不存在")
        return config

    async def update_config(
        self, config_id: str, current_user: User, data: ModelConfigUpdate
    ) -> ModelConfig:
        """更新模型配置"""
        effective_id = data.config_id or config_id
        config = await self.get_config(effective_id, current_user)
        if data.is_default:
            await self.clear_default(current_user.id, exclude_id=effective_id)
        obj_dict = self._prepare_update_dict(data)
        if obj_dict:
            config = config.update_from_dict(obj_dict)
            await config.save()
        return config

    async def delete_config(self, config_id: str, current_user: User) -> None:
        """删除模型配置"""
        config = await self.get_config(config_id, current_user)
        if config.is_default:
            other = await self.get_first_other(current_user.id, config_id)
            if other:
                other.is_default = True
                await other.save()
        await config.delete()

    async def set_default(self, config_id: str, current_user: User) -> None:
        """设置默认模型配置"""
        config = await self.get_config(config_id, current_user)
        await self.clear_default(current_user.id, exclude_id=config_id)
        config.is_default = True
        await config.save()

    async def get_default(self, current_user: User) -> ModelConfig:
        """获取当前用户的默认模型配置"""
        config = await self.get_default_config(current_user.id)
        if config:
            return config
        raise NotFoundException(message="没有找到模型配置")

    async def resolve_for_chat(
        self,
        current_user: User,
        model_config_id: Optional[str] = None,
    ) -> Optional[ModelConfig]:
        """解析聊天场景使用的模型配置：指定 ID 或当前用户默认；无则 None（走 .env 兜底）"""
        if model_config_id:
            config = await self.get_by_id_and_user(model_config_id, current_user.id)
            if config:
                return config

        return await self.get_default_config(current_user.id)
