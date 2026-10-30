# -*- coding: utf-8 -*-
"""解析聊天场景 LLM 连接参数"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from applications.model_config.models.model_config_model import ModelConfig
from applications.model_config.services.secret_utils import decrypt_api_key
from configure import PROJECT_CONFIG


@dataclass
class LLMConnection:
    llm_model_name: str
    llm_api_key: str
    llm_base_url: str


def resolve_llm_connection(model_config: Optional[ModelConfig] = None) -> LLMConnection:
    if model_config and (model_config.llm_model_name or "").strip():
        model = model_config.llm_model_name.strip()
    else:
        model = PROJECT_CONFIG.LLM_MODEL_NAME

    if model_config and (model_config.llm_base_url or "").strip():
        base_url = model_config.llm_base_url.strip()
    else:
        base_url = PROJECT_CONFIG.LLM_BASE_URL

    if model_config and model_config.llm_api_key:
        api_key = decrypt_api_key(model_config.llm_api_key)
    else:
        api_key = PROJECT_CONFIG.LLM_API_KEY

    return LLMConnection(
        llm_model_name=model,
        llm_api_key=api_key,
        llm_base_url=base_url,
    )


def resolve_chat_llm_params(model_config: Optional[ModelConfig] = None) -> Dict[str, Any]:
    """合并 ModelConfig 生成参数与 env 兜底连接信息"""
    conn = resolve_llm_connection(model_config)
    if model_config:
        return {
            "model_name": conn.llm_model_name,
            "api_key": conn.llm_api_key,
            "base_url": conn.llm_base_url,
            "temperature": model_config.temperature,
            "max_tokens": model_config.max_tokens,
            "top_p": model_config.top_p,
            "system_prompt": model_config.system_prompt,
            "top_k": model_config.top_k,
            "score_threshold": model_config.score_threshold,
            "max_history_rounds": model_config.max_history_rounds,
        }
    return {
        "model_name": conn.llm_model_name,
        "api_key": conn.llm_api_key,
        "base_url": conn.llm_base_url,
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 0.95,
        "system_prompt": None,
        "top_k": 5,
        "score_threshold": 0.0,
        "max_history_rounds": 10,
    }
