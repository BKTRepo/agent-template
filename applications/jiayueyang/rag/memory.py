# -*- coding: utf-8 -*-
"""对话记忆工具——历史窗口的 token 预算裁剪与计量。

三种问答模式（naive / hybrid / bypass）共用本模块装配历史窗口, 保证
"记忆策略"一致: 取最近若干条消息, 在【token 预算】（主约束）与【条数
上限】（保险丝）双重约束下裁剪, 并保证窗口从 user 轮开始。

本模块为叶子模块, 不依赖 query.py / llm.py, 避免循环导入; token 估算
与 query.py 的 _estimate_tokens 同口径（中英文混合保守估算）。
"""
from typing import Dict, List, Optional, Tuple

from configure import LOGGER

# 与 query.py 保持一致: 每个 token 约 1.5~2.0 个汉字, 取 1.8 保守估算
_CHARS_PER_TOKEN = 1.8

# 每条消息的固定开销（角色标记 / 分隔符）, 计入预算更安全
_PER_MESSAGE_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    """粗略估算文本 token 数（与 query._estimate_tokens 同口径）。"""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def message_tokens(msg: Dict[str, str]) -> int:
    """单条历史消息的 token 估算（内容 + 每条固定开销）。"""
    return estimate_tokens(msg.get("content") or "") + _PER_MESSAGE_OVERHEAD


def history_token_count(msgs: List[Dict[str, str]]) -> int:
    """历史窗口总 token 估算（供 token 预算扣减）。"""
    return sum(message_tokens(m) for m in msgs) if msgs else 0


def trim_history_window(
        msgs: List[Dict[str, str]],
        max_tokens: int,
        max_messages: int,
) -> List[Dict[str, str]]:
    """按 token 预算 + 条数上限裁剪历史窗口, 并保证从 user 轮开始。

    裁剪策略: 先取最近 max_messages 条（条数保险丝）, 再从最新一条向前
    累加 token, 一旦超出 max_tokens 预算即停止（保留最新的若干条）。
    最新一条即使单独超出预算也会保留（至少要带上最近的消息）。

    :param msgs: 已按时间升序的历史消息（role/content）
    :param max_tokens: 历史窗口 token 预算（<=0 返回空）
    :param max_messages: 条数硬上限（<=0 返回空）
    :return: 时间升序的窗口消息列表
    """
    if not msgs or max_tokens <= 0 or max_messages <= 0:
        return []

    # 条数保险丝: 先取最近 max_messages 条
    candidates = msgs[-max_messages:]

    # token 预算: 从最新向前累加, 超预算即停（最新一条必留）
    window: List[Dict[str, str]] = []
    total = 0
    for msg in reversed(candidates):
        cost = message_tokens(msg)
        if window and total + cost > max_tokens:
            break
        window.insert(0, msg)
        total += cost

    # 保证从 user 轮开始（裁掉开头多余的 assistant 轮）
    while window and window[0].get("role") != "user":
        window = window[1:]

    return window


# ---------------------------------------------------------------------------
# 滚动摘要（长期记忆）——窗口/溢出切分 + 摘要折叠
# ---------------------------------------------------------------------------

def compute_window_and_overflow(
        msgs: List[Dict[str, str]],
        summary_up_to_seq: int,
        max_tokens: int,
        max_messages: int,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], int]:
    """按摘要边界把历史切分为"窗口（近期, 注入用）"与"溢出（被挤出, 待摘要）"。

    不变式: 摘要覆盖 seq <= summary_up_to_seq; 窗口候选为 seq > summary_up_to_seq。
    （messages 按 seq 升序, 列表下标即 seq。）对窗口候选做 token 裁剪后, 若
    边界与窗口起点之间还有消息, 它们就是溢出, 应折叠进摘要并把边界前移到
    窗口起点前一1, 保证"摘要 + 窗口"无缝覆盖全部消息, 不丢不重。

    :return: (window, overflow, new_up_to_seq)
    """
    if not msgs:
        return [], [], summary_up_to_seq
    candidates = msgs[summary_up_to_seq + 1:]
    if not candidates:
        return [], [], summary_up_to_seq

    window = trim_history_window(candidates, max_tokens, max_messages)
    if not window:
        # 窗口为空（极端情况）: 候选全部视为溢出
        return [], candidates, len(msgs) - 1

    # 定位窗口起点在 msgs 中的下标（窗口元素与 msgs 同对象引用）
    start_in_candidates = next(
        (i for i, cm in enumerate(candidates) if cm is window[0]), 0,
    )
    window_start_seq = (summary_up_to_seq + 1) + start_in_candidates
    overflow = msgs[summary_up_to_seq + 1: window_start_seq]
    return window, overflow, window_start_seq - 1


# 滚动摘要提示词: 把"已有摘要 + 新增对话"融合为一段简洁连贯的摘要
_SUMMARY_PROMPT = """你是知识库问答系统的对话摘要助手。请把「已有摘要」和「新增对话」融合为一段简洁、连贯的对话摘要，作为后续问答的背景上下文。

要求:
1. 保留关键事实、结论、用户意图，以及重要的实体/术语指涉；
2. 略去寒暄、重复与无关细节；
3. 直接输出摘要本身，不要任何前缀、标题或解释；
4. 控制在 {max_chars} 字以内；
5. 使用与对话相同的语言。

已有摘要:
{existing_summary}

新增对话:
{new_messages}

融合后的摘要:"""


def build_summary_prompt(
        existing_summary: Optional[str],
        messages: List[Dict[str, str]],
        max_chars: int,
) -> str:
    """渲染滚动摘要提示词（新增对话按 'User: … / Assistant: …' 拼接）。"""
    lines: List[str] = []
    for m in messages:
        role = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    new_messages = "\n".join(lines) if lines else "(empty)"
    return _SUMMARY_PROMPT.format(
        max_chars=max_chars,
        existing_summary=(existing_summary or "(暂无摘要)"),
        new_messages=new_messages,
    )


async def llm_fold_summary(
        existing_summary: Optional[str],
        messages: List[Dict[str, str]],
        max_summary_tokens: int,
) -> Optional[str]:
    """把溢出消息折叠进滚动摘要。成功返回新摘要; 失败返回 None（调用方保留原摘要,
    不推进边界, 下次重试）。"""
    if not messages:
        return existing_summary
    max_chars = max(100, int(max_summary_tokens * _CHARS_PER_TOKEN))
    prompt = build_summary_prompt(existing_summary, messages, max_chars)
    try:
        # 延迟导入: 避免模块加载期引入 LLM 客户端
        from applications.jiayueyang.rag.llm import chat_completion
        response = await chat_completion(
            messages=prompt,
            stream=False,
            max_tokens=max(256, int(max_summary_tokens * 1.5)),
            temperature=0.3,
        )
        if isinstance(response, str):
            result = response.strip()
            for prefix in ("融合后的摘要:", "Merged Summary:", "Summary:", "摘要:"):
                if result.lower().startswith(prefix.lower()):
                    result = result[len(prefix):].strip()
            if result:
                return result
    except Exception as exc:
        LOGGER.warning(f"滚动摘要折叠失败: {exc}——保留原摘要")
    return None


# ---------------------------------------------------------------------------
# L4 向量回忆——把历史轮次嵌入 Milvus 独立集合, 问答时按当前问题召回旧轮次。
# 一切操作直接连接 Milvus Server，并容错降级（失败不影响正常问答）。
# 参数写死（不进 .env）。
# ---------------------------------------------------------------------------

MEMORY_RECALL_TOP_K = 3          # 每次召回的旧轮次条数
MEMORY_RECALL_MIN_SCORE = 0.25   # COSINE 相似度下限（低于视为不相关, 不注入）
MEMORY_EMBED_ANSWER_CHARS = 200  # 嵌入文本中回答的截断长度（问题全文 + 回答摘录）


def _l4_enabled() -> bool:
    """单一 Milvus C/S 架构下始终启用 L4。"""
    return True


def build_memory_text(question: str, answer: str) -> str:
    """单轮的嵌入文本: 问题全文 + 回答摘录（兼顾"按问题召回"与"按内容召回"）。"""
    q = (question or "").strip()
    a = (answer or "").strip()[:MEMORY_EMBED_ANSWER_CHARS]
    return f"{q}。{a}" if a else q


async def upsert_turn_memory(
        conversation_id: int,
        seq: int,
        question: str,
        answer: str,
) -> None:
    """嵌入并直接写入 Milvus Server。异常吞掉, 不影响主流程。"""
    if not _l4_enabled():
        return
    text = build_memory_text(question, answer)
    if not text.strip():
        return
    try:
        from applications.jiayueyang.rag.embedding import embed_texts
        from applications.jiayueyang.rag.milvus_store import upsert_chat_memory
        vecs = await embed_texts([text], quick=True)
        if not vecs or not vecs[0]:
            return
        upsert_chat_memory([{
            "id": f"{conversation_id}-turn-{seq}",
            "vector": vecs[0],
            "conversation_id": str(conversation_id),
            "seq": int(seq),
            "question": question or "",
            "answer": answer or "",
        }])
    except Exception as exc:
        LOGGER.warning(f"对话记忆写入失败（不影响）: {exc}")


async def recall_turn_memory(
        conversation_id: int,
        query: str,
        max_seq: int,
) -> str:
    """召回本会话与当前问题相关的旧轮次（seq <= max_seq）, 拼成上下文文本。

    :param max_seq: 召回轮次的 seq 上限（用于排除近期窗口内的轮次, 避免重复注入）。
    :return: 形如 "Q: ...\nA: ..." 的拼接文本; 无可召回或失败时返回空串。
    """
    if not _l4_enabled() or not query or max_seq < 0:
        return ""
    try:
        from applications.jiayueyang.rag.embedding import embed_texts
        from applications.jiayueyang.rag.milvus_store import search_chat_memory
        vecs = await embed_texts([query], quick=True)
        if not vecs or not vecs[0]:
            return ""
        turns = search_chat_memory(
            [vecs[0]], str(conversation_id),
            top_k=MEMORY_RECALL_TOP_K, max_seq=int(max_seq),
        )
        if not turns:
            return ""
        lines: List[str] = []
        for t in turns:
            score = t.get("distance")
            if score is not None and score < MEMORY_RECALL_MIN_SCORE:
                continue
            q = (t.get("question") or "").strip()
            a = (t.get("answer") or "").strip()
            if q or a:
                lines.append(f"Q: {q}\nA: {a}")
        return "\n\n".join(lines)
    except Exception as exc:
        LOGGER.warning(f"对话记忆召回失败（不影响）: {exc}")
        return ""
