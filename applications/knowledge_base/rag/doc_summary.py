# -*- coding: utf-8 -*-
"""文档摘要生成（文档级召回的数据源）。

入库流水线在解析清洗后调用一次: LLM 生成覆盖"主题 / 关键术语与缩写 /
章节范围"的结构化摘要（200~300 字）, embed 后与摘要文本一并落盘为
bundle 目录下的 ``summary.json``::

    {"summary": "...", "vector": [...], "created_at": 1723...}

查询侧的文档摘要索引（doc_recall）读取该文件做文档级召回: 摘要回答的是
"这份文档讲什么", 与"分块内容相似度"互补——文档只有一小段相关时,
分块相似度可能很弱, 但摘要级匹配仍能把文档送入候选池。

摘要文本同时升级文档表 summary 字段（原为 markdown 前 15 字符占位）。
"""
from typing import Any, Dict

from configure import LOGGER, PROJECT_CONFIG

from applications.knowledge_base.rag.embedding import embed_texts
from applications.knowledge_base.rag.llm import chat_completion

# 摘要输入截断: 头部优先（标题/范围/引言信息密度最高）, 尾部补足（附录/总结）。
# 全文送入既浪费 token 又稀释重点——摘要质量不随输入长度线性提升
_HEAD_CHARS_RATIO = 0.8

_SUMMARY_SYSTEM_PROMPT = """你是文档分析助手。请为给定文档写一段 200~300 字的检索用摘要，要求：
1. 首句点明文档主题与类型（规范/手册/协议/报告等）；
2. 覆盖文档的关键术语、专有名词与缩写（原文照录，不要翻译或改写）；
3. 说明文档的章节/内容范围（涉及哪些主题、哪些字段或流程）；
4. 用陈述句，不用"本文"开头，不加评价，不编造文档中没有的内容；
5. 直接输出摘要文本，不要标题、不要解释。"""


def _truncate_for_summary(markdown: str) -> str:
    """按预算截取送 LLM 的正文（头部优先, 尾部补足）。"""
    budget = PROJECT_CONFIG.DOC_SUMMARY_INPUT_MAX_CHARS
    if len(markdown) <= budget:
        return markdown
    head_len = int(budget * _HEAD_CHARS_RATIO)
    tail_len = budget - head_len
    return markdown[:head_len] + "\n…（中段省略）…\n" + markdown[-tail_len:]


async def generate_doc_summary(markdown: str, filename: str = "") -> Dict[str, Any]:
    """生成文档摘要并嵌入。

    :return: ``{"summary": str, "vector": List[float], "filename": str}``
    :raises: LLM / 嵌入调用异常由调用方决定降级策略（流水线中为非致命）
    """
    text = _truncate_for_summary((markdown or "").strip())
    if not text:
        raise ValueError("文档正文为空, 无法生成摘要")

    user_msg = f"文件名: {filename}\n\n文档正文:\n{text}" if filename else text
    summary = await chat_completion(
        messages=user_msg,
        system_prompt=_SUMMARY_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=800,
    )
    summary = (summary or "").strip()
    if not summary:
        raise RuntimeError("LLM 返回空摘要")

    vectors = await embed_texts([summary])
    vector = vectors[0] if vectors else []
    if not vector or not any(vector):
        raise RuntimeError("摘要嵌入失败（零向量）")

    LOGGER.info(f"文档摘要已生成: {filename or '(未知)'}, {len(summary)} 字")
    return {"summary": summary, "vector": vector, "filename": filename}
