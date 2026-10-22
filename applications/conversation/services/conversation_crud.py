# -*- coding: utf-8 -*-
from typing import AsyncIterator, List, Optional, Dict, Any

from tortoise.query_utils import Prefetch

from applications.agent.services.agent_crud import McpServerCrud, SkillCrud
from applications.base.rag.chain import rag_stream
from applications.base.services.scaffold import ScaffoldCrud
from applications.conversation.models.conversation_model import Conversation, Message
from applications.conversation.schemas.conversation_schema import (
    ChatRequest,
    ConversationBrief,
    ConversationCreate,
    ConversationDetail,
    ConversationStatOut,
    ConversationUpdate,
    KnowledgeBaseBrief,
    MessageCreate,
    MessageUpdate,
    ModelConfigBrief,
    TokenUsage,
    UserBrief,
    normalize_knowledge_base_ids,
    normalize_mcp_ids,
    normalize_skill_ids,
)
from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase
from applications.knowledge_base.services.knowledge_base_crud import KnowledgeBaseCrud
from applications.model_config.models.model_config_model import ModelConfig
from applications.model_config.services.llm_connection import resolve_chat_llm_params
from applications.model_config.services.model_config_crud import ModelConfigCrud
from applications.user.models.user_model import User
from core.exceptions import NotFoundException
from enums.chat_session_enum import ChatMessageRole


class MessageCrud(ScaffoldCrud[Message, MessageCreate, MessageUpdate]):
    def __init__(self):
        super().__init__(model=Message)

    async def list_by_conversation(self, conversation_id: str) -> List[Message]:
        """获取对话下的消息列表（排除已禁用）"""
        return await self.model.filter(
            conversation_id=conversation_id, state__not=1
        ).order_by("created_time")

    async def add_message(
            self,
            conversation_id: str,
            role: ChatMessageRole,
            content: str,
            *,
            prompt_tokens: Optional[int] = None,
            completion_tokens: Optional[int] = None,
            reasoning_tokens: Optional[int] = None,
            process_trace: Optional[List[dict]] = None,
    ) -> Message:
        """添加消息"""
        data = MessageCreate(
            conversation_id=conversation_id,
            role=role,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            process_trace=process_trace,
        )
        return await self.create(data.create_dict())

    async def soft_delete_by_conversations(self, conversation_ids: List[str]) -> None:
        """批量软删除对话下的消息"""
        if conversation_ids:
            await self.model.filter(
                conversation_id__in=conversation_ids, state__not=1
            ).update(state=1)


class ConversationCrud(ScaffoldCrud[Conversation, ConversationCreate, ConversationUpdate]):
    def __init__(self):
        super().__init__(model=Conversation)
        self.message = MessageCrud()

    async def list_by_user(self, user_id: int) -> List[Conversation]:
        """获取用户的对话列表（排除已禁用）"""
        return await self.model.filter(
            user_id=user_id, state__not=1
        ).order_by("-updated_time")

    async def get_by_id(
            self, conversation_id: str, user_id: int
    ) -> Optional[Conversation]:
        """根据 ID 和用户 ID 获取对话（排除已禁用）"""
        return await self.model.get_or_none(
            id=conversation_id, user_id=user_id, state__not=1
        )

    async def get_with_messages(
            self, conversation_id: str, user_id: int
    ) -> Optional[Conversation]:
        """获取对话及其消息列表（排除已禁用）"""
        return (
            await self.model.filter(
                id=conversation_id, user_id=user_id, state__not=1
            )
            .prefetch_related(
                Prefetch(
                    "messages",
                    Message.filter(state__not=1).order_by("created_time"),
                )
            )
            .first()
        )

    async def create_for_user(self, user_id: int) -> Conversation:
        """为用户创建新对话"""
        data = ConversationCreate(user_id=user_id)
        return await self.create(data.create_dict())

    async def clear_by_user(self, user_id: int) -> None:
        """软删除用户的所有对话及消息"""
        conv_ids = await self.model.filter(
            user_id=user_id, state__not=1
        ).values_list("id", flat=True)
        if conv_ids:
            await self.message.soft_delete_by_conversations(conv_ids)
            await self.model.filter(id__in=conv_ids).update(state=1)

    async def update_meta(
            self,
            conversation: Conversation,
            *,
            knowledge_base_ids: Optional[List[str]] = None,
            skill_ids: Optional[List[str]] = None,
            mcp_ids: Optional[List[str]] = None,
            model_config_id: Optional[str] = None,
            title: Optional[str] = None,
    ) -> None:
        """更新对话元数据"""
        if knowledge_base_ids is not None:
            conversation.knowledge_base_ids = knowledge_base_ids
        if skill_ids is not None:
            conversation.skill_ids = skill_ids
        if mcp_ids is not None:
            conversation.mcp_ids = mcp_ids
        if model_config_id is not None:
            conversation.model_config_id = model_config_id
        if title is not None:
            conversation.title = title
        await conversation.save()

    @staticmethod
    def get_knowledge_base_ids(conversation: Conversation) -> List[str]:
        """从对话记录读取知识库 ID 列表"""
        ids = normalize_knowledge_base_ids(conversation.knowledge_base_ids)
        return ids if ids is not None else []

    @staticmethod
    def get_skill_ids(conversation: Conversation) -> List[str]:
        """从对话记录读取技能 ID 列表"""
        ids = normalize_skill_ids(conversation.skill_ids)
        return ids if ids is not None else []

    @staticmethod
    def get_mcp_ids(conversation: Conversation) -> List[str]:
        """从对话记录读取 MCP 服务 ID 列表"""
        ids = normalize_mcp_ids(conversation.mcp_ids)
        return ids if ids is not None else []

    async def list_conversations(self, user: User) -> List[Conversation]:
        """获取当前用户的对话列表"""
        return await self.list_by_user(user.id)

    async def get_conversation(
            self, conversation_id: str, user: User
    ) -> ConversationDetail:
        """获取对话详情"""
        conv = await self.get_with_messages(conversation_id, user.id)
        if not conv:
            raise NotFoundException(message="对话不存在")
        return conv

    async def delete_conversation(self, conversation_id: str, user: User) -> None:
        """软删除对话及其消息"""
        conv = await self.get_by_id(conversation_id, user.id)
        if not conv:
            raise NotFoundException(message="对话不存在")
        await self.message.soft_delete_by_conversations([conv.id])
        conv.state = 1
        await conv.save()

    async def clear_all(self, user: User) -> None:
        """软删除当前用户的所有对话"""
        await self.clear_by_user(user.id)

    async def _validate_kb_access(
            self, knowledge_base_ids: List[str], user: User
    ) -> None:
        """校验知识库访问权限"""
        kb_crud = KnowledgeBaseCrud()
        for kb_id in knowledge_base_ids:
            kb = await kb_crud.get_by_id(kb_id)
            if not kb:
                raise NotFoundException(message=f"知识库 {kb_id} 不存在")
            kb_crud.check_access(kb, user)

    async def _validate_skill_access(
            self, skill_ids: List[str], user: User
    ) -> None:
        """校验技能访问权限"""
        skill_crud = SkillCrud()
        for skill_id in skill_ids:
            skill = await skill_crud.get_by_id(skill_id)
            if not skill or not skill.is_enabled:
                raise NotFoundException(message=f"技能 {skill_id} 不存在")
            skill_crud.check_access(skill, user)

    async def _validate_mcp_access(
            self, mcp_ids: List[str], user: User
    ) -> None:
        """校验 MCP 服务访问权限"""
        mcp_crud = McpServerCrud()
        for mcp_id in mcp_ids:
            mcp = await mcp_crud.get_by_id(mcp_id)
            if not mcp or not mcp.is_enabled:
                raise NotFoundException(message=f"MCP 服务 {mcp_id} 不存在")
            mcp_crud.check_access(mcp, user)

    async def prepare_for_chat(
            self, req: ChatRequest, user: User
    ) -> tuple[Conversation, Optional[ModelConfig], List[dict], List[str]]:
        """准备聊天上下文"""
        if req.conversation_id:
            conv = await self.get_by_id(req.conversation_id, user.id)
            if not conv:
                raise NotFoundException(message="对话不存在")
        else:
            conv = await self.create_for_user(user.id)

        model_config = await ModelConfigCrud().resolve_for_chat(
            user, req.model_config_id
        )

        if req.knowledge_base_ids is not None:
            knowledge_base_ids = req.knowledge_base_ids
        else:
            knowledge_base_ids = self.get_knowledge_base_ids(conv)
        if knowledge_base_ids:
            await self._validate_kb_access(knowledge_base_ids, user)

        if req.skill_ids is not None:
            skill_ids = req.skill_ids
        else:
            skill_ids = self.get_skill_ids(conv)
        if skill_ids:
            await self._validate_skill_access(skill_ids, user)

        if req.mcp_ids is not None:
            mcp_ids = req.mcp_ids
        else:
            mcp_ids = self.get_mcp_ids(conv)
        if mcp_ids:
            await self._validate_mcp_access(mcp_ids, user)

        await self.update_meta(
            conv,
            knowledge_base_ids=knowledge_base_ids,
            skill_ids=skill_ids,
            mcp_ids=mcp_ids,
            model_config_id=model_config.id if model_config else None,
        )

        history_msgs = await self.message.list_by_conversation(conv.id)
        chat_history = [{"role": m.role.value, "content": m.content} for m in history_msgs]

        if not history_msgs:
            title = req.question[:20] + ("..." if len(req.question) > 20 else "")
            await self.update_meta(conv, title=title)

        await self.message.add_message(conv.id, ChatMessageRole.USER, req.question)

        return conv, model_config, chat_history, knowledge_base_ids

    async def stream_response(
            self,
            question: str,
            knowledge_base_ids: List[str],
            chat_history: List[dict],
            model_config: Optional[ModelConfig],
            enable_thinking: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式生成聊天回复"""
        llm_params = resolve_chat_llm_params(model_config)
        effective_thinking = (
                enable_thinking
                and model_config is not None
                and model_config.model_thinking
        )

        async for chunk in rag_stream(
                question=question,
                knowledge_base_ids=knowledge_base_ids,
                chat_history=chat_history,
                enable_thinking=effective_thinking,
                **llm_params,
        ):
            yield chunk

    async def save_assistant_message(
            self,
            conversation_id: str,
            content: str,
            *,
            prompt_tokens: Optional[int] = None,
            completion_tokens: Optional[int] = None,
            reasoning_tokens: Optional[int] = None,
            process_trace: Optional[List[dict]] = None,
    ) -> None:
        """保存助手回复消息"""
        await self.message.add_message(
            conversation_id,
            ChatMessageRole.ASSISTANT,
            content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            process_trace=process_trace,
        )

    async def list_conversation_stats_by_user(
            self,
            user_id: int,
            page: int = 1,
            page_size: int = 10,
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
    ) -> tuple[int, List[ConversationStatOut]]:
        """按用户 ID 分页查询各对话的统计详情（轮次、Token 消耗等）"""
        user = await User.get_or_none(id=user_id)
        if not user:
            raise NotFoundException(message="用户不存在")

        qs = self.model.filter(user_id=user_id, state__not=1)
        if start_time and end_time:
            qs = qs.filter(updated_time__range=[start_time, end_time])
        elif start_time:
            qs = qs.filter(updated_time__gte=start_time)
        elif end_time:
            qs = qs.filter(updated_time__lte=end_time)

        total = await qs.count()
        conversations = (
            await qs.prefetch_related(
                "model_config",
                Prefetch("messages", Message.filter(state__not=1)),
            )
            .order_by("-updated_time")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        all_kb_ids: set[str] = set()
        for conv in conversations:
            all_kb_ids.update(self.get_knowledge_base_ids(conv))

        kb_map: dict[str, KnowledgeBase] = {}
        if all_kb_ids:
            kbs = await KnowledgeBase.filter(id__in=list(all_kb_ids))
            kb_map = {kb.id: kb for kb in kbs}

        user_brief = UserBrief(id=user.id, username=user.username, alias=user.alias)
        results: List[ConversationStatOut] = []

        for conv in conversations:
            assistant_msgs = [
                m for m in conv.messages if m.role == ChatMessageRole.ASSISTANT
            ]
            prompt_sum = sum(m.prompt_tokens or 0 for m in assistant_msgs)
            completion_sum = sum(m.completion_tokens or 0 for m in assistant_msgs)
            reasoning_sum = sum(m.reasoning_tokens or 0 for m in assistant_msgs)

            kb_briefs: List[KnowledgeBaseBrief] = []
            for kb_id in self.get_knowledge_base_ids(conv):
                kb = kb_map.get(kb_id)
                if kb:
                    kb_briefs.append(
                        KnowledgeBaseBrief(
                            id=kb.id,
                            name=kb.knowledge_name,
                            description=kb.description,
                        )
                    )
                else:
                    kb_briefs.append(KnowledgeBaseBrief(id=kb_id))

            model_brief = None
            if conv.model_config:
                model_brief = ModelConfigBrief(
                    id=conv.model_config.id,
                    config_name=conv.model_config.config_name,
                    config_desc=conv.model_config.config_desc,
                )

            results.append(
                ConversationStatOut(
                    conversation=ConversationBrief(id=conv.id, title=conv.title),
                    model_config_info=model_brief,
                    knowledge_bases=kb_briefs,
                    round_count=len(assistant_msgs),
                    token_usage=TokenUsage(
                        prompt_tokens=prompt_sum,
                        completion_tokens=completion_sum,
                        reasoning_tokens=reasoning_sum,
                        total_tokens=prompt_sum + completion_sum + reasoning_sum,
                    ),
                    user=user_brief,
                )
            )

        return total, results
