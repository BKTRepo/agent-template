# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe
@Project : KeenRobot
@Module  : claude_generator.py
@DateTime: 2026/6/11
"""
from services.claude_agent_service import build_base_options, run_with_model_pool


class ClaudeTestCaseGenerator:
    async def generate(self, source_path: str, output_dir: str = "") -> str:
        prompt = (
            f"请读取 {source_path} 目录中的所有 md 文档，按照 skill 的要求生成测试案例。"
            f"所有输出产物保存到 {output_dir} 目录。"
        )

        base_options = build_base_options(
            skills=["test-case-generator"],
            output_dir=output_dir,
        )

        return await run_with_model_pool(base_options, prompt)
