# -*- coding: utf-8 -*-
"""对话历史 CRUD 层（会话 / 消息 / 检索详情三表的唯一数据访问入口）。

替代 JSON 时代的"portalocker 跨进程锁 + 全量读-改-写":
- 多 Web worker 并发写入由 MySQL 行级更新与事务（会话行 SELECT FOR UPDATE
  分配消息 seq）保证一致, 不再需要文件锁;
- 消息 seq（会话内位置）即对外 message_index, 停止生成 / 重新生成 /
  SSE 重连 / 搜索跳转均依赖其稳定性（消息只追加不删改序）。
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from tortoise.functions import Max
from tortoise.transactions import in_transaction

from applications.jiayueyang.models.conversation_model import (
    MSG_DONE,
    MSG_GENERATING,
    MSG_INTERRUPTED,
    MSG_TRUNCATED,
    RagConversation,
    RagConversationMessage,
    RagConversationRetrieval,
)
from applications.jiayueyang.services.scaffold import ScaffoldCrud
from configure import LOGGER

# 默认标题 / 自动标题截断长度（与原实现一致）
DEFAULT_TITLE = "新对话"
TITLE_MAX_LEN = 12

# "generating" 状态超过该时长视为中断: 生成任务随 Web 进程存活, 进程被杀
# （重启 / gunicorn max_requests 回收）后占位消息会永远停在 generating,
# 读取时发现超期即就地修正为 interrupted, 实现状态自愈
STALE_GENERATING_SECONDS = 15 * 60


class ConversationCrud(ScaffoldCrud[RagConversation, Dict, Dict]):
    """会话三表 CRUD（含消息 seq 分配、状态自愈、检索详情维护）。"""

    def __init__(self):
        super().__init__(model=RagConversation)

    # ==================== 会话 ====================

    async def get_conversation(self, conversation_id: int) -> Optional[RagConversation]:
        """按 ID 获取会话（不存在返回 None）。"""
        return await self.model.filter(id=conversation_id).first()

    async def list_conversations(self) -> List[RagConversation]:
        """全部会话（置顶优先, 其余按最近活跃倒序; Meta.ordering 已声明）。"""
        return await self.model.all()

    async def create_conversation(self, username: str, title: str) -> RagConversation:
        """新建会话（updated_time 显式置为当前时间）。"""
        now = datetime.now()
        return await self.model.create(
            username=username, title=title, pinned=False, updated_time=now,
        )

    async def touch(self, conversation_id: int) -> None:
        """刷新会话最近活跃时间（提问落盘 / 消息终态 / 重命名时调用）。"""
        await self.model.filter(id=conversation_id).update(updated_time=datetime.now())

    async def rename(self, conversation_id: int, title: str) -> Optional[RagConversation]:
        """重命名并刷新活跃时间; 会话不存在返回 None。"""
        conv = await self.get_conversation(conversation_id)
        if conv is None:
            return None
        conv.title = title
        conv.updated_time = datetime.now()
        await conv.save(update_fields=["title", "updated_time"])
        return conv

    async def set_pinned(self, conversation_id: int, pinned: bool) -> Optional[RagConversation]:
        """置顶/取消置顶; 不刷新活跃时间（保持"最近对话"排序语义）。"""
        conv = await self.get_conversation(conversation_id)
        if conv is None:
            return None
        conv.pinned = bool(pinned)
        await conv.save(update_fields=["pinned"])
        return conv

    async def delete_conversation(self, conversation_id: int) -> bool:
        """删除会话（消息与检索详情经外键级联清理）。"""
        deleted = await self.model.filter(id=conversation_id).delete()
        return deleted > 0

    # ==================== 消息 ====================

    async def list_messages(self, conversation_id: int) -> List[RagConversationMessage]:
        """会话内全部消息（按 seq 升序, 即写入顺序）。"""
        return await RagConversationMessage.filter(
            conversation_id=conversation_id,
        ).order_by("seq")

    async def append_qa_round(self, conversation_id: int, query: str) -> Optional[Tuple[int, int]]:
        """提问即落盘: 会话行锁内分配 seq, 追加用户提问 + generating 占位回答。

        首条用户提问自动生成标题（截断规则与原实现一致）。

        :return: (user_seq, assistant_seq); 会话不存在返回 None
        """
        async with in_transaction():
            conv = await self.model.filter(id=conversation_id).select_for_update().first()
            if conv is None:
                LOGGER.warning(f"问答落盘失败: 会话不存在 id={conversation_id}")
                return None
            seq_base = await RagConversationMessage.filter(
                conversation_id=conversation_id,
            ).count()
            now = datetime.now()
            await RagConversationMessage.create(
                conversation_id=conversation_id, seq=seq_base,
                role="user", content=query, status=MSG_DONE, created_time=now,
            )
            if not conv.title or conv.title == DEFAULT_TITLE:
                text = query.strip()
                conv.title = (
                    text[:TITLE_MAX_LEN] + "…" if len(text) > TITLE_MAX_LEN
                    else (text or DEFAULT_TITLE)
                )
            conv.updated_time = now
            await conv.save(update_fields=["title", "updated_time"])
            await RagConversationMessage.create(
                conversation_id=conversation_id, seq=seq_base + 1,
                role="assistant", content="", status=MSG_GENERATING, created_time=now,
            )
        return seq_base, seq_base + 1

    async def update_message(
            self,
            conversation_id: int,
            index: int,
            content: Optional[str] = None,
            status: Optional[str] = None,
            thinking_ms: Optional[int] = None,
    ) -> bool:
        """按 seq 更新消息内容/状态/思考耗时（生成中节流回写与终态落盘共用）。

        终态（done/interrupted/truncated）同时刷新会话活跃时间; 生成中的高频回写
        不打扰"最近对话"排序。

        :return: 消息存在返回 True; 否则 False（会话可能已被删除,
                 调用方应停止后续回写）
        """
        msg = await RagConversationMessage.filter(
            conversation_id=conversation_id, seq=index,
        ).first()
        if msg is None:
            return False
        values: Dict[str, Any] = {}
        if content is not None:
            values["content"] = content
        if status is not None:
            values["status"] = status
        if thinking_ms is not None:
            values["thinking_ms"] = thinking_ms
        if values:
            await RagConversationMessage.filter(id=msg.id).update(**values)
        if status in (MSG_DONE, MSG_INTERRUPTED, MSG_TRUNCATED):
            await self.touch(conversation_id)
        return True

    async def read_message_status(self, conversation_id: int, index: int) -> Optional[str]:
        """读取指定消息当前状态（会话/消息不存在返回 None）。"""
        msg = await RagConversationMessage.filter(
            conversation_id=conversation_id, seq=index,
        ).only("status").first()
        return msg.status if msg is not None else None

    async def stop_generating(self, conversation_id: int, index: int) -> bool:
        """停止生成: 仅当消息仍处于 generating 时置为 interrupted（保留已有内容）。

        正在回写的后台任务在下一次节流落盘时读取到 interrupted 状态后自行收尾。
        """
        updated = await RagConversationMessage.filter(
            conversation_id=conversation_id, seq=index, status=MSG_GENERATING,
        ).update(status=MSG_INTERRUPTED)
        if updated:
            await self.touch(conversation_id)
            LOGGER.info(f"停止生成: conv={conversation_id}, index={index}")
            return True
        return False

    async def reset_for_regenerate(self, conversation_id: int, index: int) -> bool:
        """重新生成: 校验目标为 assistant 消息后清空内容并置回 generating。

        同事务清除上一轮的检索详情; 新一轮生成完成后写入新详情,
        中断/失败时该回答不再展示过期的旧检索详情。
        """
        async with in_transaction():
            msg = await RagConversationMessage.filter(
                conversation_id=conversation_id, seq=index,
            ).select_for_update().first()
            if msg is None or msg.role != "assistant":
                return False
            await RagConversationMessage.filter(id=msg.id).update(
                content="", status=MSG_GENERATING,
            )
            await RagConversationRetrieval.filter(
                conversation_id=conversation_id, message_seq=index,
            ).delete()
        return True

    # ==================== 状态自愈 ====================

    async def recover_stale_generating(self, conversation_id: Optional[int] = None) -> int:
        """将超期的 generating 消息修正为 interrupted（条件更新, 返回修正条数）。

        生成进程随 Web 进程存活, 进程被杀后占位消息永远停在 generating;
        超过容忍时长（15 分钟）即视为确定性中断。conversation_id 为 None
        时全量自愈（会话列表前调用）。
        """
        threshold = datetime.now() - timedelta(seconds=STALE_GENERATING_SECONDS)
        qs = RagConversationMessage.filter(status=MSG_GENERATING, created_time__lt=threshold)
        if conversation_id is not None:
            qs = qs.filter(conversation_id=conversation_id)
        return await qs.update(status=MSG_INTERRUPTED)

    # ==================== 会话列表聚合辅助 ====================

    async def generating_conversation_ids(self) -> Set[int]:
        """存在 generating 消息的会话 id 集合（侧栏"生成中"标记）。"""
        rows = await RagConversationMessage.filter(
            status=MSG_GENERATING,
        ).distinct().values_list("conversation_id", flat=True)
        return set(rows)

    async def last_question_times(self) -> Dict[int, datetime]:
        """每个会话最近一条用户消息的时间（无用户消息的会话不在其中）。"""
        rows = await RagConversationMessage.filter(role="user").group_by(
            "conversation_id",
        ).annotate(last_q=Max("created_time")).values("conversation_id", "last_q")
        return {r["conversation_id"]: r["last_q"] for r in rows if r["last_q"]}

    # ==================== 检索详情 ====================

    async def get_retrieval_map(self, conversation_id: int) -> Dict[int, Dict[str, Any]]:
        """会话内全部检索详情（message_seq → detail）。"""
        rows = await RagConversationRetrieval.filter(conversation_id=conversation_id)
        return {r.message_seq: r.detail for r in rows}

    async def save_retrieval(
            self, conversation_id: int, index: int, detail: Dict[str, Any],
    ) -> None:
        """写入一条 AI 回答的检索详情（重复写入覆盖旧详情, 如重新生成）。"""
        async with in_transaction():
            existing = await RagConversationRetrieval.filter(
                conversation_id=conversation_id, message_seq=index,
            ).first()
            if existing is not None:
                existing.detail = detail
                await existing.save(update_fields=["detail"])
            else:
                await RagConversationRetrieval.create(
                    conversation_id=conversation_id, message_seq=index, detail=detail,
                )

    # ==================== 搜索 ====================

    async def search_messages(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """按关键词搜索消息内容（MySQL LIKE, utf8mb4 ci 排序规则下大小写不敏感）。

        :return: 命中消息列表（含会话标题与 seq, 按时间倒序, 最多 limit 条）
        """
        rows = await RagConversationMessage.filter(
            content__icontains=keyword,
        ).prefetch_related("conversation").order_by("-created_time").limit(limit)
        results: List[Dict[str, Any]] = []
        for m in rows:
            conv = m.conversation
            results.append({
                "conversation_id": m.conversation_id,
                "conversation_title": conv.title if conv else DEFAULT_TITLE,
                "role": m.role,
                "message_index": m.seq,
                "content": m.content or "",
                "created_time": m.created_time,
            })
        return results

    # ==================== 滚动摘要（长期记忆） ====================

    async def get_memory_meta(self, conversation_id: int) -> Tuple[str, int]:
        """读取会话的滚动摘要与摘要边界。

        :return: (memory_summary, summary_up_to_seq); 会话不存在时 ("", -1)
        """
        conv = await self.model.filter(id=conversation_id).only(
            "memory_summary", "summary_up_to_seq",
        ).first()
        if conv is None:
            return "", -1
        return (
            conv.memory_summary or "",
            conv.summary_up_to_seq if conv.summary_up_to_seq is not None else -1,
        )

    async def save_memory_meta(
            self, conversation_id: int, summary: str, up_to_seq: int,
    ) -> None:
        """写回滚动摘要与摘要边界（折叠成功后调用）。"""
        await self.model.filter(id=conversation_id).update(
            memory_summary=summary, summary_up_to_seq=up_to_seq,
        )
