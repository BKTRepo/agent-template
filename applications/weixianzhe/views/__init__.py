# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : __init__.py
@DateTime: 2025/6/7
"""
from fastapi import APIRouter

from .test_case_view import test_case_router
from .stream_test_case_view import stream_test_case_router

test_case_gen_router = APIRouter()

test_case_gen_router.include_router(test_case_router)
test_case_gen_router.include_router(stream_test_case_router)
