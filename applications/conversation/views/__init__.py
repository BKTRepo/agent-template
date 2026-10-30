# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .chat_view import chat
from .history_view import history

chat_router = APIRouter()
history_router = APIRouter()

chat_router.include_router(chat)
history_router.include_router(history)
