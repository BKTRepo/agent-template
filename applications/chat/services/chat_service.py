"""会话权限、资源选择与清空的共享业务规则。"""

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from applications.chat.models.chat_model import ChatCleanup, ChatConversation, ChatMessage, ChatTask
from applications.knowledge_base.services.platform_service import KnowledgeError, KnowledgeService
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_catalog_service import SkillCatalogService


async def require_conversation(conversation_id, user_id, *, connection=None):
    query = ChatConversation.filter(id=conversation_id, user_id=user_id, state=0)
    if connection is not None:
        query = query.using_db(connection).select_for_update()
    conversation = await query.first()
    if not conversation:
        raise HTTPException(404, "会话不存在或无权访问")
    return conversation


async def validate_resources(user, skills, knowledge_bases):
    skills = list(dict.fromkeys(skills))
    knowledge_bases = list(dict.fromkeys(knowledge_bases))
    if any(value <= 0 for value in skills + knowledge_bases):
        raise HTTPException(400, "技能和知识库编号必须为正整数")
    try:
        for skill_id in skills:
            await SkillCatalogService().published(skill_id, online=True)
        for kb_id in knowledge_bases:
            await KnowledgeService().require(kb_id, user)
    except DeveloperError as exc:
        raise HTTPException(getattr(exc, "status_code", 400), str(exc)) from exc
    except KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return skills, knowledge_bases


async def clear_conversation(conversation_id, user_id, *, delete=False):
    async with in_transaction() as conn:
        conversation = await require_conversation(conversation_id, user_id, connection=conn)
        generation = conversation.generation
        await ChatCleanup.get_or_create(conversation_id=conversation.id, generation=generation, using_db=conn)
        await ChatTask.filter(conversation_id=conversation.id, generation=generation,
                              status="pending").using_db(conn).update(status="cancelled")
        # 运行中的容器需退出后才能清理目录；执行器负责把 cancelling 更新为 cancelled。
        await ChatTask.filter(conversation_id=conversation.id, generation=generation,
                              status="running").using_db(conn).update(status="cancelling")
        await ChatMessage.filter(conversation_id=conversation.id, generation=generation,
                                 unread=True).using_db(conn).update(unread=False)
        conversation.generation += 1
        conversation.skills = []
        conversation.knowledge_bases = []
        conversation.model = None
        conversation.summary_message_id = None
        if delete:
            conversation.state = 1
            conversation.favorite = False
        await conversation.save(using_db=conn)
    return conversation


async def conversation_data(conversation):
    unread = await ChatMessage.filter(conversation_id=conversation.id, generation=conversation.generation,
                                      role="assistant", unread=True).count()
    return {"id": conversation.id, "title": conversation.title, "favorite": conversation.favorite,
            "generation": conversation.generation, "skills": conversation.skills,
            "knowledge_bases": conversation.knowledge_bases, "model": conversation.model,
            "unread_count": unread, "created_time": conversation.created_time,
            "updated_time": conversation.updated_time}
