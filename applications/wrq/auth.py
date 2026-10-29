"""WRQ接口验证既有平台JWT，不查询或维护用户表，不提供登录接口。"""
from dataclasses import dataclass
import jwt
from fastapi import Depends, Header, HTTPException
from configure import PROJECT_CONFIG
from services import CTX_USER_ID

@dataclass(frozen=True)
class PlatformIdentity:
    id: int
    username: str
    alias: str
    is_superuser: bool = False
    login_name: str = ""

def user_login_name(user) -> str:
    """只接收已验证身份，不能从浏览器请求体取得权限归属。"""
    value = getattr(user, 'login_name', '') or getattr(user, 'username', '')
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 10:
        raise HTTPException(401, '可信身份缺少有效工号，或工号超过10字符')
    return value

def verify_token(token: str) -> PlatformIdentity:
    try:
        payload = jwt.decode(token, PROJECT_CONFIG.AUTH_SECRET_KEY,
            algorithms=[PROJECT_CONFIG.AUTH_JWT_ALGORITHM], options={'require':['exp','user_id']})
        uid = payload['user_id']
        if isinstance(uid,bool) or not isinstance(uid,(str,int)) or not str(uid).isdigit() or int(uid)<1:
            raise ValueError('invalid user id')
        if payload.get('state',0)!=0 or payload.get('is_active',True) is False:
            raise HTTPException(401,'平台身份不可用')
        username = payload.get('username') or payload.get('login_name')
        alias = payload.get('alias') or username
        if not isinstance(username,str) or not isinstance(alias,str): raise ValueError('invalid identity')
        identity = PlatformIdentity(int(uid), username, alias, payload.get('is_superuser') is True,
                                    payload.get('login_name') or username)
        user_login_name(identity)
        return identity
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(401,'Token已过期，请获取新的平台Token') from None
    except (jwt.InvalidTokenError,ValueError,TypeError,KeyError):
        raise HTTPException(401,'Token无效或缺少可信用户编号') from None

class AuthControl:
    @staticmethod
    async def is_authed(token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        if not token and authorization:
            scheme,_,value=authorization.partition(' ')
            if scheme.lower()=='bearer': token=value.strip()
        if not token: raise HTTPException(401,'请携带平台Token')
        identity=verify_token(token)
        CTX_USER_ID.set(identity.id)
        return identity

DependAuth=Depends(AuthControl.is_authed)
