# -*- coding: utf-8 -*-
"""显式创建管理员；不在应用启动时写入默认账号。"""
import argparse
import asyncio
import getpass

if __package__ in (None, ""):
    import _bootstrap  # noqa: F401

from tortoise import Tortoise

from applications.user.models.user_model import User
from configure.project_config import TORTOISE_ORM
from services import get_password_hash


async def init_admin(username: str, password: str, email: str) -> bool:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if await User.exists(username=username):
            print("账号已存在，未修改密码或权限。")
            return False
        await User.create(
            username=username,
            alias=username,
            email=email,
            password=get_password_hash(password),
            is_active=True,
            is_superuser=True,
        )
        print("管理员账号已创建。")
        return True
    finally:
        await Tortoise.close_connections()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("管理员密码（至少 8 位）：")
    if len(password) < 8:
        parser.error("密码长度至少为 8 位")
    if password != getpass.getpass("再次输入密码："):
        parser.error("两次密码不一致")
    asyncio.run(init_admin(args.username, password, args.email))


if __name__ == "__main__":
    main()
