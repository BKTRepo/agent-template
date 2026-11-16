"""Resolve department names by platform login name, independently of platform authentication."""
import asyncio
import json
import ssl
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from configure import LOGGER, PROJECT_CONFIG


class DirectoryUser(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    login_name: str
    department_id: int | None = None


class DirectoryDepartment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    department_id: int
    department_name: str


def _read_mock(logins):
    data = json.loads(Path(PROJECT_CONFIG.USER_DEPARTMENT_MOCK_FILE).read_text(encoding='utf-8-sig'))
    departments = {}
    for item in data['departments']:
        row = DirectoryDepartment.model_validate(item)
        if row.department_id in departments and departments[row.department_id] != row.department_name:
            raise ValueError('Conflicting mock department identifiers')
        departments[row.department_id] = row.department_name
    result = {}
    for item in data['users']:
        row = DirectoryUser.model_validate(item)
        name = departments.get(row.department_id)
        if row.login_name in logins and name:
            if row.login_name in result and result[row.login_name] != name:
                raise ValueError('Conflicting mock login names')
            result[row.login_name] = name
    return result


async def _read_mysql(logins):
    # Deliberately lazy: mock mode never initializes the external connector.
    import asyncmy
    from asyncmy.cursors import DictCursor
    cfg = PROJECT_CONFIG
    if not all((cfg.USER_DEPARTMENT_DB_HOST, cfg.USER_DEPARTMENT_DB_NAME,
                cfg.USER_DEPARTMENT_DB_USERNAME, cfg.USER_DEPARTMENT_DB_PASSWORD)):
        raise ValueError('Department database configuration is incomplete')
    tls = None
    if cfg.USER_DEPARTMENT_DB_SSL_ENABLED:
        tls = ssl.create_default_context(cafile=cfg.USER_DEPARTMENT_DB_SSL_CA or None)
        if not cfg.USER_DEPARTMENT_DB_SSL_CA:
            tls.check_hostname = False
            tls.verify_mode = ssl.CERT_NONE
    connection = await asyncmy.connect(host=cfg.USER_DEPARTMENT_DB_HOST, port=cfg.USER_DEPARTMENT_DB_PORT,
        user=cfg.USER_DEPARTMENT_DB_USERNAME, password=cfg.USER_DEPARTMENT_DB_PASSWORD,
        db=cfg.USER_DEPARTMENT_DB_NAME, charset='utf8mb4', ssl=tls, autocommit=True,
        connect_timeout=cfg.USER_DEPARTMENT_TIMEOUT_SECONDS, read_timeout=cfg.USER_DEPARTMENT_TIMEOUT_SECONDS,
        cursor_cls=DictCursor)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute('SET SESSION TRANSACTION READ ONLY')
            placeholders = ','.join(['%s'] * len(logins))
            await cursor.execute('SELECT u.login_name, d.department_name FROM `user` u '
                'LEFT JOIN `department` d ON d.department_id = u.department_id '
                f'WHERE u.login_name IN ({placeholders})', logins)
            return {row['login_name']: row['department_name'] for row in await cursor.fetchall()
                    if row['department_name']}
    finally:
        connection.close()


async def departments_for_users(login_names):
    """Batch only the displayed users; no match/unavailable source leaves department empty."""
    logins = sorted({name.strip() for name in login_names if isinstance(name, str) and name.strip()})
    mode = PROJECT_CONFIG.USER_DEPARTMENT_MODE
    if not logins or mode == 'disabled':
        return {}
    try:
        async with asyncio.timeout(PROJECT_CONFIG.USER_DEPARTMENT_TIMEOUT_SECONDS):
            if mode == 'mock':
                return await asyncio.to_thread(_read_mock, set(logins))
            if mode == 'mysql':
                return await _read_mysql(logins)
            raise ValueError('Unsupported department directory mode')
    except Exception as exc:
        # Never log connection strings, credentials, or raw directory records.
        LOGGER.warning('用户部门目录暂不可用: mode={}, type={}', mode, type(exc).__name__)
        return {}
