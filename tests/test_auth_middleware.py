import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from core.middlewares.auth_middleware import auth_middleware


class AuthMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, failure=None, token='test-token'):
        app = FastAPI()
        app.add_middleware(BaseHTTPMiddleware, dispatch=auth_middleware)

        @app.get('/private')
        async def private():
            return {'status': 'success'}

        with patch('core.middlewares.auth_middleware.AuthControl.is_authed',
                   new=AsyncMock(side_effect=failure)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                return await client.get('/private', headers={'token': token} if token else {})

    async def test_dependency_failure_is_retryable_not_expired(self):
        for failure in (HTTPException(500, 'network:ConnectionError'), ConnectionError('unavailable')):
            response = await self.request(failure)
            self.assertEqual(response.status_code, 503)
            self.assertNotEqual(str(response.json()['code']), '400401')
            self.assertEqual(response.json()['message'], '登录验证服务暂不可用，请稍后重试。')

    async def test_expired_or_missing_token_still_requires_login(self):
        expired = await self.request(HTTPException(401, 'Token 已过期'))
        self.assertEqual(str(expired.json()['code']), '400401')
        missing = await self.request(token=None)
        self.assertEqual(str(missing.json()['code']), '400401')

    async def test_valid_session_passes_and_forbidden_is_not_logout(self):
        self.assertEqual((await self.request()).json()['status'], 'success')
        forbidden = await self.request(HTTPException(403, '没有权限'))
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotEqual(str(forbidden.json()['code']), '400401')
