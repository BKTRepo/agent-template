"""技术测试平台人员目录查询；身份认证需单独验证可信凭证。"""

from dataclasses import dataclass
import os
import re

import httpx


class DirectoryLookupError(RuntimeError):
    """人员目录不可用或返回数据不符合约定。"""


@dataclass(frozen=True)
class DirectoryUser:
    login_name: str
    name: str | None
    email: str | None
    phone: str | None


def _optional_text(value: object, maximum: int) -> str | None:
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise DirectoryLookupError('人员目录返回的用户信息格式不正确')
    value = value.strip()
    if len(value) > maximum:
        raise DirectoryLookupError('人员目录返回的用户信息超过字段长度限制')
    return value or None


async def find_active_user(login_name: str, *, client: httpx.AsyncClient | None = None) -> DirectoryUser | None:
    """按工号查询在职人员；不使用、不返回目录中的密码或盐值。"""
    if not isinstance(login_name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', login_name):
        raise ValueError('工号格式不正确')
    url = os.environ.get('TECHNICAL_TEST_DIRECTORY_URL', 'http://10.240.105.88:9999/userInfo/findByLoginName')
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10, trust_env=False)
    try:
        response = await client.post(url, files={'loginName': (None, login_name), 'state': (None, '1')})
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DirectoryLookupError('查询人员目录失败，请稍后重试') from exc
    finally:
        if own_client:
            await client.aclose()
    if not isinstance(body, dict) or body.get('retCd') != '000000' or 'data' not in body:
        raise DirectoryLookupError('人员目录返回异常')
    data = body['data']
    if data is None:
        return None
    if not isinstance(data, dict) or data.get('loginName') != login_name or str(data.get('state', '')) != '1':
        raise DirectoryLookupError('人员目录返回的工号或状态不匹配')
    return DirectoryUser(login_name=login_name, name=_optional_text(data.get('username'), 64),
                         email=_optional_text(data.get('email'), 64), phone=_optional_text(data.get('telPhone'), 20))
