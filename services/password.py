# -*- coding: utf-8 -*-
import secrets

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from applications.base.schemas.token_schema import JWTPayload
from configure import PROJECT_CONFIG

password_hasher = PasswordHasher()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return password_hasher.verify(hashed_password, plain_password)
    except (InvalidHashError, VerificationError):
        return False


def get_password_hash(password: str) -> str:
    return password_hasher.hash(password)


def generate_password() -> str:
    return secrets.token_urlsafe(16)


def create_access_token(*, data: JWTPayload, token_version: int = 0):
    payload = data.model_dump().copy()
    payload["token_version"] = token_version
    encoded_jwt = jwt.encode(
        payload,
        PROJECT_CONFIG.AUTH_SECRET_KEY,
        algorithm=PROJECT_CONFIG.AUTH_JWT_ALGORITHM
    )
    return encoded_jwt
