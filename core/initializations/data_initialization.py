# -*- coding: utf-8 -*-
from fastapi import FastAPI

from applications.user.services.init_data import init_database_user


async def init_database_table(app: FastAPI):
    await init_database_user()
