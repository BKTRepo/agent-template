"""悬浮窗和开发者中心沙箱共用的模型网关与模型映射。"""
import json
import os
import re
import time
import threading
from pathlib import Path

import httpx
from dotenv import dotenv_values

from configure import PROJECT_CONFIG

MODELS = ('deepseek', 'glm51', 'qwen3.8-27b-nothink', 'qwen3.8-27b-think', 'qwen35-35b-a3b-nothink')
MODEL_ENV = {'deepseek': 'CHAT_MODEL_DEEPSEEK', 'glm51': 'CHAT_MODEL_GLM51',
             'qwen3.8-27b-nothink': 'CHAT_MODEL_QWEN38_NOTHINK',
             'qwen3.8-27b-think': 'CHAT_MODEL_QWEN38_THINK',
             'qwen35-35b-a3b-nothink': 'CHAT_MODEL_QWEN35_NOTHINK'}
CCR_MODEL_ENV = {'deepseek': 'CHAT_CCR_MODEL_DEEPSEEK', 'glm51': 'CHAT_CCR_MODEL_GLM51',
                 'qwen3.8-27b-nothink': 'CHAT_CCR_MODEL_QWEN38_NOTHINK',
                 'qwen3.8-27b-think': 'CHAT_CCR_MODEL_QWEN38_THINK',
                 'qwen35-35b-a3b-nothink': 'CHAT_CCR_MODEL_QWEN35_NOTHINK'}
OPTIONAL_ENV = ('CLAUDE_MAX_TURNS', 'CLAUDE_MAX_BUDGET_USD', 'CLAUDE_CODE_EFFORT_LEVEL',
                'CLAUDE_CODE_AUTO_COMPACT_WINDOW', 'CLAUDE_CODE_MAX_CONTEXT_TOKENS')

_ccr_cache = {}
_ccr_lock = threading.Lock()


def _ccr_models(value):
    base = value('CHAT_CCR_BASE_URL').rstrip('/')
    mode = value('CHAT_CCR_AUTH_MODE').lower() or 'bearer'
    key = value('CHAT_CCR_API_KEY')
    if not base or mode not in ('bearer', 'api_key', 'none') or (mode != 'none' and not key):
        raise RuntimeError('CCR 地址或鉴权配置不完整')
    identity = (base, mode, key)
    with _ccr_lock:
        cached = _ccr_cache.get(identity)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        headers = {'Authorization': f'Bearer {key}'} if mode == 'bearer' else ({'x-api-key': key} if mode == 'api_key' else {})
        url = base + ('/models' if base.endswith('/v1') else '/v1/models')
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
            data = payload.get('data') if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ValueError('模型列表格式错误')
            rows, seen = [], set()
            for item in data:
                model = item.get('id') if isinstance(item, dict) else None
                if isinstance(model, str) and model.strip() == model and 0 < len(model) <= 128 and model not in seen:
                    seen.add(model)
                    rows.append({'id': model, 'name': model, 'ccr_model': model})
            _ccr_cache.clear()
            _ccr_cache[identity] = (time.monotonic() + 30, rows)
            return rows
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError('获取 CCR 模型列表失败，请检查 CCR 服务和鉴权配置') from exc


def _values():
    file_values = dotenv_values(Path(PROJECT_CONFIG.OUTPUT_DIR).resolve().parent / '.env')

    def value(name):
        return (os.environ.get(name) or file_values.get(name) or '').strip()
    return value


def _registry(value):
    """读取可配置模型清单；未配置时兼容原有模型标识与映射。"""
    raw = value('CHAT_MODEL_REGISTRY')
    if not raw:
        return [{'id': model, 'name': model} for model in MODELS]
    try:
        rows = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError('CHAT_MODEL_REGISTRY 必须是有效的 JSON 数组') from exc
    if not isinstance(rows, list) or not rows:
        raise RuntimeError('CHAT_MODEL_REGISTRY 必须包含至少一个模型')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'id', 'name', 'direct_model', 'ccr_model'}:
            raise RuntimeError('模型配置只支持 id、name、direct_model、ccr_model')
        model_id = row.get('id')
        if not isinstance(model_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', model_id):
            raise RuntimeError('模型 id 无效，需为不超过 128 字符的字母、数字及 ._:/-')
        if model_id in seen:
            raise RuntimeError(f'模型 id 重复：{model_id}')
        seen.add(model_id)
        item = {'id': model_id}
        for key in ('name', 'direct_model', 'ccr_model'):
            data = row.get(key)
            if data is not None and (not isinstance(data, str) or len(data) > 256 or not data.strip()):
                raise RuntimeError(f'模型 {model_id} 的 {key} 无效')
            if data is not None:
                item[key] = data.strip()
        item.setdefault('name', model_id)
        result.append(item)
    return result


def model_registry():
    value = _values()
    return _ccr_models(value) if value('CHAT_GATEWAY_MODE').lower() == 'ccr' else _registry(value)


def model_ids():
    return tuple(item['id'] for item in model_registry())


def default_model():
    value = _values()
    rows = model_registry()
    if not rows:
        raise RuntimeError('当前网关没有可用模型')
    model = value('CHAT_DEFAULT_MODEL') or rows[0]['id']
    if model not in {row['id'] for row in rows}:
        raise RuntimeError('CHAT_DEFAULT_MODEL 不是支持的模型标识')
    return model


def model_environment(model):
    value = _values()
    registry = model_registry()
    configured = next((item for item in registry if item['id'] == model), None)
    if (value('CHAT_MODEL_REGISTRY') or value('CHAT_GATEWAY_MODE').lower() == 'ccr') and not configured:
        raise RuntimeError(f'模型 {model} 不在 CHAT_MODEL_REGISTRY 中')
    mode = value('CHAT_GATEWAY_MODE').lower() or 'direct'
    if mode == 'direct':
        result = {name: value(name) for name in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY')}
        if not all(result.values()):
            raise RuntimeError('模型网关尚未配置 ANTHROPIC_BASE_URL 或 ANTHROPIC_API_KEY')
    elif mode == 'ccr':
        base = value('CHAT_CCR_BASE_URL')
        auth_mode = value('CHAT_CCR_AUTH_MODE').lower() or 'bearer'
        key = value('CHAT_CCR_API_KEY')
        if not base:
            raise RuntimeError('CCR 尚未配置 CHAT_CCR_BASE_URL')
        if auth_mode not in ('bearer', 'api_key', 'none'):
            raise RuntimeError('CHAT_CCR_AUTH_MODE 只能是 bearer、api_key 或 none')
        if auth_mode != 'none' and not key:
            raise RuntimeError('CCR 尚未配置 CHAT_CCR_API_KEY')
        result = {'ANTHROPIC_BASE_URL': base}
        if auth_mode == 'api_key':
            result['ANTHROPIC_API_KEY'] = key
        else:
            result['ANTHROPIC_AUTH_TOKEN'] = key if auth_mode == 'bearer' else 'ccr-no-auth'
    else:
        raise RuntimeError('CHAT_GATEWAY_MODE 只能是 direct 或 ccr')
    actual = (configured or {}).get('ccr_model' if mode == 'ccr' else 'direct_model', '')
    if not actual and model in MODEL_ENV:
        # 兼容早期 ccr 模式已使用的 CHAT_MODEL_*；新配置优先使用独立 CCR 映射。
        actual = (value(CCR_MODEL_ENV[model]) if mode == 'ccr' else '') or value(MODEL_ENV[model])
    elif not actual and not value('CHAT_MODEL_REGISTRY') and model not in MODEL_ENV:
        actual = model
    if not actual and model == 'deepseek' and mode == 'direct':
        actual = value('ANTHROPIC_MODEL')
    if not actual:
        raise RuntimeError(f'模型 {model} 尚未配置实际 API 模型名')
    result['ANTHROPIC_MODEL'] = actual
    for name in ('ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL'):
        result[name] = actual
    for name in OPTIONAL_ENV:
        if value(name):
            result[name] = value(name)
    return result


def configured_model_registry():
    """仅返回当前网关中拥有完整连接配置和实际模型名的条目。"""
    result = []
    for row in model_registry():
        try:
            environment = model_environment(row['id'])
        except RuntimeError:
            continue
        result.append({'id': row['id'], 'model_name': environment['ANTHROPIC_MODEL']})
    return result


def sandbox_model_environment(model):
    """沙箱可以配置独立的网关地址，其他模型配置保持一致。"""
    environment = model_environment(model)
    value = _values()
    if value('CHAT_GATEWAY_MODE').lower() == 'ccr' and value('CHAT_CCR_SANDBOX_BASE_URL'):
        environment['ANTHROPIC_BASE_URL'] = value('CHAT_CCR_SANDBOX_BASE_URL')
    return environment


def configured_model_ids():
    return tuple(row['id'] for row in configured_model_registry())
