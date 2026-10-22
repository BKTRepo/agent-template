# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from applications.model_config.models.model_config_model import ModelConfig
from applications.model_config.services.secret_utils import (
    decrypt_api_key,
    mask_api_key,
)


class ModelConfigBase(BaseModel):
    config_name: Optional[str] = Field(default=None, max_length=64, description="配置名称")
    config_desc: Optional[str] = Field(default=None, max_length=500, description="配置说明")
    model_provider: Optional[str] = Field(default=None, max_length=32, description="模型所属供应商")
    llm_model_name: Optional[str] = Field(default=None, max_length=64, description="API model 参数")
    model_thinking: Optional[bool] = Field(default=None, description="模型深度思考开关")
    llm_base_url: Optional[str] = Field(default=None, max_length=512, description="LLM API Base URL")
    llm_api_key: Optional[str] = Field(default=None, max_length=512, description="LLM API Key")
    temperature: Optional[float] = Field(default=None, ge=0, le=2, description="温度(控制AI回答随机性)")
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192, description="限制单次回答的最大输出Token数")
    top_p: Optional[float] = Field(default=None, ge=0, le=1, description="Top P(核采样参数)")
    top_k: Optional[int] = Field(default=None, ge=1, le=20, description="Top K(知识库检索条数)")
    max_history_rounds: Optional[int] = Field(default=None, ge=0, le=50, description="保留历史对话轮数")
    score_threshold: Optional[float] = Field(default=None, ge=0, le=1, description="检索相似度阈值(0-1)")
    system_prompt: Optional[str] = Field(default=None, max_length=4000, description="系统提示词，支持{context}占位符")
    is_default: Optional[bool] = Field(default=None, description="是否默认配置")


class ModelConfigCreate(ModelConfigBase):
    config_name: str = Field(..., min_length=1, max_length=64, description="配置名称")
    llm_model_name: str = Field(default="deepseek-chat", max_length=64, description="API model 参数")
    model_provider: str = Field(default="custom", max_length=32, description="模型所属供应商")
    model_thinking: bool = Field(default=False, description="模型深度思考开关")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度(控制AI回答随机性)")
    max_tokens: int = Field(default=4096, ge=1, le=8192, description="限制单次回答的最大输出Token数")
    top_p: float = Field(default=0.95, ge=0, le=1, description="Top P(核采样参数)")
    top_k: int = Field(default=5, ge=1, le=20, description="Top K(知识库检索条数)")
    max_history_rounds: int = Field(default=10, ge=0, le=50, description="保留历史对话轮数")
    score_threshold: float = Field(default=0.0, ge=0, le=1, description="检索相似度阈值(0-1)")
    is_default: bool = Field(default=False, description="是否默认配置")

    def create_dict(self):
        return self.model_dump(exclude_unset=True)


class ModelConfigUpdate(ModelConfigBase):
    config_id: Optional[str] = Field(default=None, description="模型配置ID")


class ModelConfigSelect(ModelConfigBase):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=10, description="每页数量")
    order: Optional[list] = Field(default=["-is_default", "-created_time"], description="排序字段")


class ModelConfigOut(BaseModel):
    id: str = Field(..., description="配置ID")
    user_id: int = Field(..., description="用户ID")
    config_name: str = Field(..., description="配置名称")
    config_desc: Optional[str] = Field(default=None, description="配置说明")
    model_provider: str = Field(..., description="模型所属供应商")
    llm_model_name: str = Field(..., description="API model 参数")
    model_thinking: bool = Field(..., description="模型深度思考开关")
    llm_base_url: Optional[str] = Field(default=None, description="LLM API Base URL")
    llm_api_key_masked: Optional[str] = Field(default=None, description="脱敏后的 API Key")
    has_llm_api_key: bool = Field(default=False, description="是否已配置 API Key")
    temperature: float = Field(..., description="温度(控制AI回答随机性)")
    max_tokens: int = Field(..., description="限制单次回答的最大输出Token数")
    top_p: float = Field(..., description="Top P(核采样参数)")
    top_k: int = Field(..., description="Top K(知识库检索条数)")
    max_history_rounds: int = Field(..., description="保留历史对话轮数")
    score_threshold: float = Field(..., description="检索相似度阈值(0-1)")
    system_prompt: Optional[str] = Field(default=None, description="系统提示词，支持{context}占位符")
    is_default: bool = Field(..., description="是否默认配置")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_model(cls, config: ModelConfig) -> "ModelConfigOut":
        has_key = bool(config.llm_api_key)
        masked = mask_api_key(decrypt_api_key(config.llm_api_key)) if has_key else None
        return cls(
            id=config.id,
            user_id=config.user_id,
            config_name=config.config_name,
            config_desc=config.config_desc,
            model_provider=config.model_provider,
            llm_model_name=config.llm_model_name,
            model_thinking=config.model_thinking,
            llm_base_url=config.llm_base_url,
            llm_api_key_masked=masked,
            has_llm_api_key=has_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            top_k=config.top_k,
            max_history_rounds=config.max_history_rounds,
            score_threshold=config.score_threshold,
            system_prompt=config.system_prompt,
            is_default=config.is_default,
            created_time=config.created_time,
            updated_time=config.updated_time,
        )
