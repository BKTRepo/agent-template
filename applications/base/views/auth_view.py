# -*- coding: utf-8 -*-
from datetime import timedelta, datetime, timezone

from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field
from tortoise.exceptions import IntegrityError

from applications.base.schemas.token_schema import CredentialsSchema, JWTOut, JWTPayload
from applications.user.dependencies import get_user_crud
from applications.user.models.user_model import User
from applications.user.services.user_crud import UserCrud
from configure import PROJECT_CONFIG
from core.exceptions import NotFoundException, NoPermissionException
from core.responses import SuccessResponse, NotFoundResponse
from services import CTX_USER_ID, create_access_token, get_password_hash

auth_public = APIRouter()
auth_secure = APIRouter()


class TechnicalTestLogin(BaseModel):
    loginName: str = Field(min_length=1, max_length=32)


@auth_public.post('/technical-test-login', summary='技术测试平台免登录')
async def technical_test_login(body: TechnicalTestLogin):
    from applications.user.services.technical_test_directory import DirectoryLookupError, find_active_user

    login_name = body.loginName.strip()
    try:
        directory_user = await find_active_user(login_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DirectoryLookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if directory_user is None:
        raise HTTPException(status_code=404, detail='没有此用户')

    user = await User.filter(username=login_name).first()
    if user is None:
        try:
            user, _ = await User.get_or_create(username=login_name, defaults={
                'password': get_password_hash('qaz1QAZ!'),
                'alias': directory_user.name or login_name,
                'email': directory_user.email or '',
                'phone': directory_user.phone,
                'is_active': True,
                'is_superuser': False,
            })
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail='用户资料与已有账号冲突，请联系管理员') from exc
    if not user.is_active or user.state != 0:
        raise HTTPException(status_code=403, detail='账号已禁用，请联系管理员')

    from applications.wrq.agent.services.login_statistics import record_successful_login
    await record_successful_login(user.id)
    expires = datetime.now(timezone.utc) + timedelta(minutes=PROJECT_CONFIG.AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(data=JWTPayload(user_id=user.id, username=user.username, state=user.state,
        is_superuser=user.is_superuser, token_version=user.token_version, exp=expires), token_version=user.token_version)
    return SuccessResponse(data={'access_token': token, 'username': user.username, 'alias': user.alias})


@auth_public.post("/access_token", summary="用户鉴权-验证用户密码和状态并生成令牌")
async def get_login_access_token(
        credentials: CredentialsSchema = Body(..., description="用户信息"),
        user_crud: UserCrud = Depends(get_user_crud),
):
    try:
        user: User = await user_crud.authenticate(credentials)
    except (NotFoundException, NoPermissionException) as e:
        return NotFoundResponse(message=str(e.message))

    from applications.wrq.agent.services.login_statistics import record_successful_login
    user.last_login = await record_successful_login(user.id)
    access_token_expires = timedelta(minutes=PROJECT_CONFIG.AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + access_token_expires

    data = JWTOut(
        access_token=create_access_token(
            data=JWTPayload(
                user_id=user.id,
                username=user.username,
                state=user.state,
                is_superuser=user.is_superuser,
                token_version=user.token_version,
                exp=expire,
            ),
            token_version=user.token_version,
        ),
        username=user.username,
        alias=user.alias,
        email=user.email,
        phone=user.phone,
        motto=user.motto,
        avatar=user.avatar,
        address=user.address,
        gender=user.gender,
        user_type=user.user_type,
        emergency_name=user.emergency_name,
        emergency_phone=user.emergency_phone,
        state=user.state,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        last_login=user.last_login
    )
    return SuccessResponse(data=data.model_dump())


@auth_secure.post("/userinfo", summary="用户鉴权-查看当前用户信息")
async def get_userinfo(
        user_crud: UserCrud = Depends(get_user_crud),
):
    user_id = CTX_USER_ID.get()
    user_obj = await user_crud.get_or_error(id=user_id)
    data = await user_obj.to_dict(exclude_fields=["password"])
    return SuccessResponse(data=data)
