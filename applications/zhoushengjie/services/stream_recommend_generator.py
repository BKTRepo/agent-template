# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : stream_recommend_generator.py
@DateTime: 2026/6/15

用例推荐流式生成服务。
业务层仅关注 prompt 和 skill 配置，通用 StreamEvent 解析由 common.claude_stream_service 提供。
"""
import os
from typing import AsyncIterator

from services.claude_stream_service import build_stream_options, stream_agent_query
from configure import PROJECT_CONFIG


async def stream_recommend_generate(
    project_id: str,
    model: str = "sonnet",
) -> AsyncIterator[dict]:
    """流式调用 Claude Agent SDK 生成推荐测试用例。

    Args:
        project_id: 项目标识。
        model: 使用的模型名，默认 sonnet。

    Yields:
        SSE 事件字典，参见 common.claude_stream_service.stream_agent_query 文档。
    """
    base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "case_recommendation", project_id)

    prompt = (
        f"使用case-recommender这个skill，根据项目下id={project_id}文件夹中的内容，"
        f"生成推荐的测试用例。所有输出产物保存到 {base_dir} 目录。"
    )

    options = build_stream_options(
        skills=["case-recommender"],
        output_dir=base_dir,
        model=model,
    )

    async for event_dict in stream_agent_query(prompt=prompt, options=options, log_tag="Recommend"):
        yield event_dict
