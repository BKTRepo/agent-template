# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .platform_view import knowledge

knowledge_router = APIRouter()
knowledge_router.include_router(knowledge)
