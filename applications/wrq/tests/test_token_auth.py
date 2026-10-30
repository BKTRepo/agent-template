"""无数据库的JWT鉴权；不创建用户，不调用登录或审计写入接口。"""
from datetime import datetime,timedelta,timezone
import unittest
import httpx
import jwt
from fastapi import FastAPI
from configure import PROJECT_CONFIG
from applications.wrq.agent.views.developer_skill_view import developer_skills

class TokenAuthTests(unittest.IsolatedAsyncioTestCase):
    def token(self,**changes):
        claims={'user_id':123,'username':'platform-test','state':0,
                'exp':datetime.now(timezone.utc)+timedelta(minutes=5)}|changes
        return jwt.encode(claims,PROJECT_CONFIG.AUTH_SECRET_KEY,algorithm=PROJECT_CONFIG.AUTH_JWT_ALGORITHM)

    async def request(self,headers):
        app=FastAPI(); app.include_router(developer_skills,prefix='/skills')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',trust_env=False) as c:
            return await c.get('/skills/developer/context',headers=headers)

    async def test_valid_platform_token_without_database(self):
        r=await self.request({'token':self.token()})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['data'],{'id':'123','name':'platform-test'})

    async def test_bearer_token(self):
        r=await self.request({'Authorization':'Bearer '+self.token()})
        self.assertEqual(r.status_code,200)

    async def test_expired_token(self):
        r=await self.request({'token':self.token(exp=datetime.now(timezone.utc)-timedelta(seconds=1))})
        self.assertEqual(r.status_code,401)

    async def test_missing_or_forged_token(self):
        for headers in ({},{'token':'not-a-jwt'}, {'token':jwt.encode({'user_id':123,
            'exp':datetime.now(timezone.utc)+timedelta(minutes=1)},'other-test-signing-key',algorithm='HS256')}):
            self.assertEqual((await self.request(headers)).status_code,401)

    async def test_missing_expiry_or_user_identity(self):
        for claims in ({'user_id':1},{'exp':datetime.now(timezone.utc)+timedelta(minutes=1)}):
            token=jwt.encode(claims,PROJECT_CONFIG.AUTH_SECRET_KEY,algorithm=PROJECT_CONFIG.AUTH_JWT_ALGORITHM)
            self.assertEqual((await self.request({'token':token})).status_code,401)

    async def test_disabled_or_invalid_identity(self):
        for changes in ({'state':1},{'is_active':False},{'user_id':0},{'user_id':True},{'user_id':'../invalid'}):
            self.assertEqual((await self.request({'token':self.token(**changes)})).status_code,401)
