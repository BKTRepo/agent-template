# -*- coding: utf-8 -*-
"""ModelConfig 敏感字段加解密"""
import base64
import hashlib

from configure import PROJECT_CONFIG

_ENCRYPT_PREFIX = "enc:"


def _derive_key() -> bytes:
    secret = PROJECT_CONFIG.AUTH_SECRET_KEY or "keenrobot-default-key"
    return hashlib.sha256(secret.encode()).digest()


def encrypt_api_key(plain: str) -> str:
    if not plain:
        return plain
    key = _derive_key()
    data = plain.encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return _ENCRYPT_PREFIX + base64.urlsafe_b64encode(encrypted).decode()


def decrypt_api_key(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith(_ENCRYPT_PREFIX):
        return stored
    key = _derive_key()
    raw = base64.urlsafe_b64decode(stored[len(_ENCRYPT_PREFIX):].encode())
    plain = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return plain.decode()


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "sk-***"
    return f"{key[:3]}***{key[-4:]}"
