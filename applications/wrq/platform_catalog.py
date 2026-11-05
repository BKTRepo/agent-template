"""One application provider: mock the real contract now; POST to the portal later."""
import json
import time
from pathlib import Path
import httpx
from configure import PROJECT_CONFIG

_cache_key = None
_cache_rows = []
_expires_at = 0


def normalize_applications(payload):
    if not isinstance(payload, dict) or payload.get('retCd') != '000000' or not isinstance(payload.get('data'), list):
        raise ValueError('应用目录接口返回失败或数据格式不正确')
    rows, seen = [], {}
    for item in payload['data']:
        if not isinstance(item, dict):
            raise ValueError('应用目录中存在无效记录')
        identifier, name = item.get('subApplicationIdentify'), item.get('subApplicationName')
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError('应用目录缺少应用标识或应用名称')
        identifier, name = identifier.strip(), name.strip()
        if identifier == '*' or len(identifier) > 100 or (identifier in seen and seen[identifier] != name):
            raise ValueError('应用目录标识无效或重复冲突')
        if identifier not in seen:
            rows.append(dict(id=identifier, paso=identifier, name=name))
            seen[identifier] = name
    return rows


def _key():
    return (PROJECT_CONFIG.APPLICATION_CATALOG_MODE, PROJECT_CONFIG.APPLICATION_CATALOG_URL)


def _mock():
    return normalize_applications(json.loads((Path(__file__).parent/'data/mock_applications.json').read_text(encoding='utf8')))


async def application_catalog(*, include_all=False):
    global _cache_key, _cache_rows, _expires_at
    key = _key()
    if key[0] == 'mock':
        rows = _mock()
    elif _cache_key == key and time.monotonic() < _expires_at:
        rows = _cache_rows
    else:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.post(key[1], json={})
            response.raise_for_status()
            rows = normalize_applications(response.json())
        _cache_key, _cache_rows = key, rows
        _expires_at = time.monotonic() + PROJECT_CONFIG.APPLICATION_CATALOG_CACHE_SECONDS
    options = [dict(row) for row in rows]
    return ([dict(id='*', paso='*', name='全应用适用')] if include_all else []) + options


def applications():
    """Synchronous compatibility for the legacy form adapter; never does network IO."""
    rows = _mock() if PROJECT_CONFIG.APPLICATION_CATALOG_MODE == 'mock' else (
        _cache_rows if _cache_key == _key() and time.monotonic() < _expires_at else [])
    return [row['id'] for row in rows]


def validate_application(value, *, allow_all=False):
    if value is None or (allow_all and value == "*"):
        return
    if value not in applications():
        raise ValueError("请选择应用目录中存在的应用")


async def validate_application_async(value, *, allow_all=False):
    if not value or (allow_all and value == '*'):
        return
    if value not in {row['id'] for row in await application_catalog()}:
        raise ValueError('请选择应用目录中存在的应用')
