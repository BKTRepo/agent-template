# -*- coding: utf-8 -*-
"""对话历史服务 — 会话与消息的持久化（MySQL）。

会话 / 消息 / 检索详情分别存于 keenrobot_rag_conversation /
keenrobot_rag_conversation_message / keenrobot_rag_conversation_retrieval
三张表（见 models/conversation_model.py）; 检索详情沿用"独立于对话内容"
的既定要求单独存表。跨进程一致性由 MySQL 行级更新与事务保证
（JSON + portalocker 文件锁方案已退役）。
所有会话当前归属公共用户 "User"（username 字段预留, 后续接入真实用户体系）。

消息状态（status）::

    done        正常完成（缺省值, 兼容旧数据）
    generating  答案正在生成（提问时即写入占位消息, 刷新/切换会话后仍可见）
    interrupted 生成被中断（用户主动停止 / 出错 / 进程异常退出超时自愈）

对外接口契约（chat_view / rag_view / 前端）与原 JSON 时代完全一致:
消息下标 = 会话内位置（seq）, 时间统一格式化为
"yyyy-MM-dd HH:mm:ss" 字符串（空值输出 ""）。
"""
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from applications.jiayueyang.models.conversation_model import MSG_DONE
from applications.jiayueyang.services.conversation_crud import (
    DEFAULT_TITLE,
    ConversationCrud,
)
from configure import LOGGER

# 当前阶段全部会话归属的公共用户（预留后续接入真实用户体系）
DEFAULT_USERNAME = "User"

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


async def _delete_conversation_memory_bg(conversation_id: int) -> None:
    """后台删除会话的 L4 向量记忆（直连 Milvus Server）。"""
    try:
        from applications.jiayueyang.rag.memory import _l4_enabled
        if not _l4_enabled():
            return
        from applications.jiayueyang.rag.milvus_store import delete_chat_memory_by_conv
        await asyncio.to_thread(delete_chat_memory_by_conv, str(conversation_id))
    except Exception as e:
        LOGGER.warning(f"删除会话记忆向量失败（不影响）: {e}")


def _fmt_time(value: Optional[datetime]) -> str:
    """datetime → 'yyyy-MM-dd HH:mm:ss'; 空值为 ''（前端契约不变）。"""
    return value.strftime(_TIME_FMT) if value else ""


def _public_view(
        conv,
        generating: bool,
        last_question_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """会话对外序列化（不含 messages, 字段与前端约定一致）。"""
    return {
        "id": conv.id,
        "title": conv.title or DEFAULT_TITLE,
        "pinned": bool(conv.pinned),
        "username": conv.username or DEFAULT_USERNAME,
        "created_time": _fmt_time(conv.created_time),
        "updated_time": _fmt_time(conv.updated_time),
        # 最近一次提问时间（无则回退会话创建时间）
        "last_question_time": _fmt_time(last_question_time or conv.created_time),
        # 会话内是否存在生成中的消息（前端侧栏据此展示"生成中"标记）
        "generating": generating,
    }


# ==================== 消息读写（模块级异步原语） ====================
# rag_view 的生成任务（含客户端断连后仍继续回写的后台协程）经以下原语
# 读写消息; 均为异步实现, 依赖 Web/任务侧的事件循环（Tortoise 连接所在 loop）。


async def update_message(
        conversation_id: int,
        index: int,
        content: Optional[str] = None,
        status: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """按消息下标更新内容/状态（生成中节流回写与终态落盘共用）。

    :param extra: 终态附加字段（目前仅 thinking_ms 思考耗时入库）;
             检索详情不在此列——体积大且不属于对话内容, 经
             save_retrieval_detail 独立存储。
    :return: 消息存在返回 True; 否则 False（会话可能已被删除,
             调用方应停止后续回写）。
    """
    thinking_ms = (extra or {}).get("thinking_ms")
    return await ConversationCrud().update_message(
        conversation_id, index,
        content=content, status=status, thinking_ms=thinking_ms,
    )


async def read_message_status(conversation_id: int, index: int) -> Optional[str]:
    """读取指定消息当前状态（会话/消息不存在返回 None）。"""
    return await ConversationCrud().read_message_status(conversation_id, index)


async def save_retrieval_detail(
        conversation_id: int,
        index: int,
        retrieval: Dict[str, Any],
) -> None:
    """将一条 AI 回答的检索详情写入独立存储（重复写入覆盖, 如重新生成）。"""
    await ConversationCrud().save_retrieval(conversation_id, index, retrieval)


# 搜索命中片段的最大长度（命中词 + 前后上下文）
_SNIPPET_MAX_LEN = 240
# 片段在命中位置之前保留的上下文长度
_SNIPPET_PREFIX_LEN = 40


def _snippet_around(content: str, pos: int, query_len: int) -> str:
    """截取以命中位置为中心的片段: 保留命中词与前后上下文, 截断处加省略号。"""
    start = max(0, pos - _SNIPPET_PREFIX_LEN)
    end = min(len(content), pos + query_len + (_SNIPPET_MAX_LEN - _SNIPPET_PREFIX_LEN))
    snippet = content[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"


class ConversationService:
    """会话 / 消息管理服务（MySQL 存储, 跨进程安全）。"""

    def __init__(self):
        self.crud = ConversationCrud()

    async def list_conversations(self) -> List[Dict[str, Any]]:
        """返回全部会话, 置顶优先, 其余按最近活跃（updated_time）倒序。"""
        # 先自愈超期 generating 消息, 保证"生成中"标记不失真
        await self.crud.recover_stale_generating()
        convs = await self.crud.list_conversations()
        generating_ids = await self.crud.generating_conversation_ids()
        last_q = await self.crud.last_question_times()
        return [
            _public_view(c, c.id in generating_ids, last_q.get(c.id))
            for c in convs
        ]

    async def create_conversation(self, title: str = DEFAULT_TITLE) -> Dict[str, Any]:
        """新建会话并返回其字典表示。"""
        conv = await self.crud.create_conversation(
            username=DEFAULT_USERNAME,
            title=(title or DEFAULT_TITLE).strip()[:255] or DEFAULT_TITLE,
        )
        LOGGER.info(f"新建会话: id={conv.id}, title={conv.title}")
        return _public_view(conv, generating=False)

    async def get_conversation(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 获取单个会话（对外视图, 不含消息）; 不存在返回 None。"""
        conv = await self.crud.get_conversation(conversation_id)
        if conv is None:
            return None
        generating_ids = await self.crud.generating_conversation_ids()
        last_q = await self.crud.last_question_times()
        return _public_view(conv, conversation_id in generating_ids, last_q.get(conversation_id))

    async def delete_conversation(self, conversation_id: int) -> bool:
        """删除会话（消息与检索详情经外键级联清理; L4 记忆向量后台清理）。返回是否命中记录。"""
        deleted = await self.crud.delete_conversation(conversation_id)
        if deleted:
            LOGGER.info(f"删除会话: id={conversation_id}")
            # 后台清理该会话的 L4 向量记忆（不阻塞删除响应）
            asyncio.create_task(_delete_conversation_memory_bg(conversation_id))
        return deleted

    async def rename_conversation(self, conversation_id: int, title: str) -> Optional[Dict[str, Any]]:
        """重命名会话, 返回更新后的字典; 会话不存在返回 None。"""
        conv = await self.crud.rename(
            conversation_id,
            (title or DEFAULT_TITLE).strip()[:255] or DEFAULT_TITLE,
        )
        if conv is None:
            return None
        generating_ids = await self.crud.generating_conversation_ids()
        last_q = await self.crud.last_question_times()
        return _public_view(conv, conversation_id in generating_ids, last_q.get(conversation_id))

    async def set_pinned(self, conversation_id: int, pinned: bool) -> Optional[Dict[str, Any]]:
        """设置/取消会话置顶, 返回更新后的字典; 会话不存在返回 None。

        不刷新 updated_time, 因此置顶操作不影响"最近活跃"排序。
        """
        conv = await self.crud.set_pinned(conversation_id, pinned)
        if conv is None:
            return None
        LOGGER.info(f"{'置顶' if pinned else '取消置顶'}会话: id={conversation_id}")
        generating_ids = await self.crud.generating_conversation_ids()
        last_q = await self.crud.last_question_times()
        return _public_view(conv, conversation_id in generating_ids, last_q.get(conversation_id))

    async def get_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """返回会话内全部消息, 按写入顺序升序（含 status 字段）。

        读取时顺带自愈本会话超期 generating 消息, 保证刷新后前端不出现
        永久"生成中"的幽灵状态。
        """
        await self.crud.recover_stale_generating(conversation_id)
        msgs = await self.crud.list_messages(conversation_id)
        retrieval_map = await self.crud.get_retrieval_map(conversation_id)
        result: List[Dict[str, Any]] = []
        for m in msgs:
            item: Dict[str, Any] = {
                "role": m.role,
                "content": m.content or "",
                "status": m.status or MSG_DONE,
                "created_time": _fmt_time(m.created_time),
            }
            # 思考耗时与检索详情仅属于 AI 回答, 用户消息不携带这两个字段;
            # 检索详情来自独立表（按消息 seq 索引）
            if m.role == "assistant":
                item["thinking_ms"] = m.thinking_ms
                item["retrieval"] = retrieval_map.get(m.seq)
            result.append(item)
        return result

    async def search_messages(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """按关键词搜索对话内容（用户提问与 AI 回答, MySQL 不区分大小写匹配）。

        返回命中消息列表, 每项含会话 id/标题、消息角色（user=提问 /
        assistant=回答）、消息在会话中的下标（供前端跳转定位）、以命中位置
        为中心的内容片段与消息时间（命中提问即提问时间, 命中回答即回答时间）;
        按消息时间倒序（最近的在前）, 最多 limit 条。
        """
        q = query.strip()
        if not q:
            return []
        rows = await self.crud.search_messages(q, limit)
        results: List[Dict[str, Any]] = []
        for r in rows:
            content = r["content"] or ""
            pos = content.lower().find(q.lower())
            results.append({
                "conversation_id": r["conversation_id"],
                "conversation_title": r["conversation_title"],
                "role": r["role"],
                "message_index": r["message_index"],
                "content": _snippet_around(content, pos, len(q)) if pos != -1 else content[:_SNIPPET_MAX_LEN],
                "created_time": _fmt_time(r["created_time"]),
            })
        return results

    async def start_qa_round(self, conversation_id: int, query: str) -> Optional[Tuple[int, int]]:
        """提问即落盘: 追加用户提问 + generating 占位回答。

        :return: (user_index, assistant_index); 会话不存在时返回 None。
        """
        return await self.crud.append_qa_round(conversation_id, query)

    async def reset_message_for_regenerate(self, conversation_id: int, index: int) -> bool:
        """重新生成前置位: 清空内容置回 generating, 并清除上一轮检索详情。"""
        return await self.crud.reset_for_regenerate(conversation_id, index)

    async def stop_generating_message(self, conversation_id: int, index: int) -> bool:
        """停止生成: 仅当消息仍处于 generating 时置为 interrupted（保留已有内容）。"""
        return await self.crud.stop_generating(conversation_id, index)

    async def get_memory_meta(self, conversation_id: int):
        """读取会话滚动摘要与摘要边界（memory_summary, summary_up_to_seq）。"""
        return await self.crud.get_memory_meta(conversation_id)

    async def save_memory_meta(self, conversation_id: int, summary: str, up_to_seq: int) -> None:
        """写回会话滚动摘要与摘要边界。"""
        await self.crud.save_memory_meta(conversation_id, summary, up_to_seq)
