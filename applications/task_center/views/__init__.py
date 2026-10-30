# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .task_view import tasks

task_center_router = APIRouter()
task_center_router.include_router(tasks)
