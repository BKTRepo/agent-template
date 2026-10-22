# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe
@Project : KeenRobot
@Module  : test_case_schema.py
@DateTime: 2026/6/11
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_serializer
from pydantic.alias_generators import to_camel


class TaskInfo(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: int
    folder_path: str
    app_system: str = ""
    requirement_name: str = ""
    status: str
    error_reason: Optional[str] = None
    created_time: datetime
    updated_time: datetime
    created_user: Optional[str] = None
    updated_user: Optional[str] = None

    @field_serializer("created_time", "updated_time")
    def serialize_datetime(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class TaskListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[TaskInfo]
