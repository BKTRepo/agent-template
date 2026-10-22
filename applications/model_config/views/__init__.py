# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .model_config_view import model_config

model_router = APIRouter()
model_router.include_router(model_config)
