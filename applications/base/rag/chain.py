# -*- coding: utf-8 -*-
"""RAG检索增强生成链"""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import List, Dict, Any

from applications.base.rag.chroma_store import chroma_store
from applications.base.rag.embeddings import get_single_embedding, is_embedding_configured
from applications.base.rag.llm import OpenAICompatibleLLM, format_messages
from configure import PROJECT_CONFIG, RAG_SYSTEM_PROMPT, GENERAL_SYSTEM_PROMPT, GREETING_RESPONSE


def is_irrelevant_question(question: str) -> bool:
    """检查问题是否与知识库无关"""
    # 无关问题关键词列表
    irrelevant_patterns = [
        r'^你好$', r'^您好$', r'^hi$', r'^hello$',
        r'^你是谁$', r'^你叫什么$', r'^你是什么模型$',
        r'^你能做什么$', r'^介绍一下自己$', r'^介绍.*自己',
        r'^你会什么$', r'^你有.*功能',
    ]

    question_stripped = question.strip()
    for pattern in irrelevant_patterns:
        if re.match(pattern, question_stripped, re.IGNORECASE):
            return True
    return False


def get_irrelevant_response() -> str:
    """生成无关问题的标准回复"""
    return GREETING_RESPONSE


def _format_source_label(result: dict) -> str:
    """格式化检索结果的来源标注"""
    filename = (result.get("filename") or "").strip()
    page_number = result.get("page_number")
    if filename and page_number:
        return f"来源: {filename} 第{page_number}页"
    if filename:
        return f"来源: {filename}"
    if page_number:
        return f"来源: 第{page_number}页"
    return ""


def _filter_embedding_model_consistency(results: List[dict]) -> List[dict]:
    """过滤与当前 Embedding 模型不一致的检索结果"""
    current_model = PROJECT_CONFIG.EMBEDDING_MODEL_NAME
    filtered = []
    for item in results:
        stored_model = (item.get("embedding_model") or "").strip()
        if stored_model and stored_model != current_model:
            print(
                f"[rag] 跳过 embedding 模型不一致的向量: "
                f"{stored_model} != {current_model}"
            )
            continue
        filtered.append(item)
    return filtered


def format_context_from_results(results: List[dict]) -> str:
    """将检索结果格式化为上下文字符串"""
    parts = []
    for i, result in enumerate(results, 1):
        content = result.get("content", "")
        score = result.get("score", 0)
        source = _format_source_label(result)
        header = f"[{i}] (相关度: {score:.3f})"
        if source:
            header += f", {source}"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)


def _retrieve_context(
        question: str,
        knowledge_base_ids: List[str],
        top_k: int = 5,
        score_threshold: float = 0.0,
) -> tuple[List[dict], str]:
    """向量检索，未配置 Embedding 或无知识库时返回空结果"""
    if not knowledge_base_ids:
        return [], ""

    if not is_embedding_configured():
        print("[rag] Embedding API 未配置，跳过知识库检索，使用通用对话模式")
        return [], ""

    query_embedding = get_single_embedding(question)
    search_results = chroma_store.search(
        knowledge_base_ids, query_embedding, top_k=top_k
    )
    search_results = _filter_embedding_model_consistency(search_results)
    if score_threshold > 0:
        search_results = [
            item for item in search_results
            if item.get("score", 0) >= score_threshold
        ]
    context = format_context_from_results(search_results)
    return search_results, context


def _resolve_system_prompt(
        system_prompt: str = None,
        context: str = "",
        has_context: bool = True,
) -> str:
    """解析系统提示词，支持自定义模板或全局默认模板"""
    if not has_context:
        return (system_prompt or "").strip() or GENERAL_SYSTEM_PROMPT

    prompt_template = (system_prompt or "").strip() or RAG_SYSTEM_PROMPT
    if "{context}" in prompt_template:
        return prompt_template.format(context=context)
    return f"{prompt_template}\n\n## 参考资料\n{context}"


def rag_query(
        question: str,
        knowledge_base_ids: List[str],
        chat_history: List[Dict[str, str]] = None,
        model_name: str = "qwen-turbo",
        api_key: str = None,
        base_url: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.95,
        system_prompt: str = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        max_history_rounds: int = 10,
) -> str:
    """
    同步RAG问答

    Args:
        question: 用户问题
        knowledge_base_ids: 知识库ID列表
        chat_history: 历史对话
        model_name: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
        top_p: top-p采样
        system_prompt: 自定义系统提示词
        top_k: 检索返回条数
        score_threshold: 检索相似度阈值
        max_history_rounds: 保留历史对话轮数

    Returns:
        模型回答
    """
    # 1. 向量检索
    search_results, context = _retrieve_context(
        question,
        knowledge_base_ids,
        top_k=top_k,
        score_threshold=score_threshold,
    )
    has_context = bool(search_results) and len(context.strip()) > 0
    resolved_prompt = _resolve_system_prompt(
        system_prompt=system_prompt,
        context=context if has_context else "（无特定参考资料，使用通用知识）",
        has_context=has_context,
    )

    # 2. 构建消息
    messages = format_messages(
        system_prompt=resolved_prompt,
        user_question=question,
        context=context,
        chat_history=chat_history,
        max_history_rounds=max_history_rounds,
        format_context=False,
    )

    # 3. 调用LLM
    llm = OpenAICompatibleLLM(model=model_name, api_key=api_key, base_url=base_url)
    response = llm.chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
    )

    return response


async def rag_stream(
        question: str,
        knowledge_base_ids: List[str],
        chat_history: List[Dict[str, str]] = None,
        model_name: str = "qwen-turbo",
        api_key: str = None,
        base_url: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.95,
        system_prompt: str = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
        max_history_rounds: int = 10,
        enable_thinking: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """
    流式RAG问答

    Args:
        question: 用户问题
        knowledge_base_ids: 知识库ID列表
        chat_history: 历史对话
        model_name: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
        top_p: top-p采样
        system_prompt: 自定义系统提示词
        top_k: 检索返回条数
        score_threshold: 检索相似度阈值
        max_history_rounds: 保留历史对话轮数

    Yields:
        {"type": "content", "content": "..."} 或 usage 字典
    """
    # 0. 检查是否为无关问题
    if is_irrelevant_question(question):
        print(f"[rag_stream] 检测到无关问题: {question}")
        response = get_irrelevant_response()
        # 添加初始延迟，模拟思考时间
        await asyncio.sleep(1.5)
        # 逐字输出以模拟流式效果，添加小延迟
        for char in response:
            yield {"type": "content", "content": char}
            # 标点符号后稍长延迟
            if char in ['，', '。', '！', '？', '：', '\n']:
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.02)
        return

    # 1. 向量检索
    search_results, context = _retrieve_context(
        question,
        knowledge_base_ids,
        top_k=top_k,
        score_threshold=score_threshold,
    )

    # 2. 检查检索结果
    has_context = bool(search_results) and len(context.strip()) > 0
    if has_context:
        print(f"[rag_stream] 检索到 {len(search_results)} 条相关内容")
    else:
        print(f"[rag_stream] 警告：未检索到相关内容，使用通用模式回答")

    resolved_prompt = _resolve_system_prompt(
        system_prompt=system_prompt,
        context=context if has_context else "（无特定参考资料，使用通用知识）",
        has_context=has_context,
    )

    # 3. 构建消息
    messages = format_messages(
        system_prompt=resolved_prompt,
        user_question=question,
        context=context,
        chat_history=chat_history,
        max_history_rounds=max_history_rounds,
        format_context=False,
    )

    # 4. 流式调用LLM
    llm = OpenAICompatibleLLM(model=model_name, api_key=api_key, base_url=base_url)
    async for chunk in llm.stream_chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            enable_thinking=enable_thinking,
    ):
        yield chunk
