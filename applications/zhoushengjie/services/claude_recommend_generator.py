# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : claude_recommend_generator.py
@DateTime: 2026/6/11
"""
import os

from configure import PROJECT_CONFIG
from services.claude_agent_service import build_base_options, run_with_model_pool


class ClaudeTestCaseRecommendGenerator:
    async def generate(self, project_id: str) -> str:
        base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "case_recommendation", project_id)

        prompt = (
            f"使用case-recommender这个skill，根据项目下id={project_id}文件夹中的内容，"
            f"生成推荐的测试用例。所有输出产物保存到 {base_dir} 目录。"
        )

        base_options = build_base_options(
            skills=["case-recommender"],
            output_dir=base_dir,
        )

        return await run_with_model_pool(base_options, prompt)
