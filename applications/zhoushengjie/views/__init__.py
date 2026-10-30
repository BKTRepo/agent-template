# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : __init__.py
@DateTime: 2025/6/7
"""
from fastapi import APIRouter

from .case_recommendation_view import case_recommendation_router as _case_recommendation_router
from .stream_recommendation_view import stream_recommendation_router as _stream_recommendation_router

case_recommendation_router = APIRouter()
case_recommendation_router.include_router(_case_recommendation_router)
case_recommendation_router.include_router(_stream_recommendation_router)
