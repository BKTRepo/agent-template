# -*- coding: utf-8 -*-
from typing import Dict, Any

from applications.user.models.user_model import User
from configure import LOGGER


async def init_database_user():
    """初始化默认用户数据"""
    user_count = await User.filter().count()
    if user_count > 0:
        LOGGER.info("[用户]数据已存在，跳过初始化")
        return

    user_data: Dict[str, Any] = {
        "username": "admin",
        "password": "123456",
        "alias": "系统管理员",
        "email": "admin@test.com",
        "phone": "18888888888",
        "avatar": "",
        "is_active": True,
        "is_superuser": True,
    }
    try:
        user = await User.create(**user_data)
        LOGGER.info(f"创建用户成功: {user.alias} (id: {user.id}, username: {user.username})")
    except Exception as e:
        LOGGER.error(f"创建用户失败: {user_data.get('alias')}, username: {user_data.get('username')}: {e}")
