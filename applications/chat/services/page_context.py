"""Permission-checked page context; clients provide identifiers, never trusted business data."""
from fastapi import HTTPException
from applications.chat.schemas.chat_schema import PageContext

LABELS = {'overview': '总览', 'skills': '技能中心', 'developer': '开发者中心', 'knowledge': '知识库与文件管理',
          'assets': '资产管理', 'workflow': '技能编排', 'mcp': 'MCP 接入配置'}


async def resolve_page_context(context: PageContext | None, user):
    from applications.knowledge_base.services.platform_service import KnowledgeError
    from applications.wrq.agent.services.developer_skill_crud import DeveloperError
    try:
        return await _resolve_page_context(context, user)
    except (KnowledgeError, DeveloperError) as exc:
        raise HTTPException(getattr(exc, 'status_code', 403), str(exc)) from exc


async def _resolve_page_context(context: PageContext | None, user):
    if context is None:
        return None
    result = {'module': context.module, 'page': LABELS[context.module]}
    if context.object_id is None:
        return result
    if context.module in ('developer', 'skills') and context.object_type == 'skill':
        from applications.wrq.agent.models.agent_model import Skill, SkillForm
        if context.module == 'developer':
            skill = await Skill.filter(id=context.object_id, state=0, create_user_login_name=user.username).first()
            if not skill:
                raise HTTPException(403, '无权读取当前技能上下文')
            form = await SkillForm.get_or_none(skill_version_id=skill.current_version_id)
            value = {'id': skill.id, 'name': form.name if form else skill.name,
                     'description': form.description if form else '', 'status': str(skill.display_status)}
        else:
            from applications.wrq.agent.services.skill_catalog_service import SkillCatalogService
            skill, version, form = await SkillCatalogService().published(context.object_id)
            value = {'id': skill.id, 'name': form.name, 'description': form.description, 'version': version.version}
    elif context.module == 'knowledge' and context.object_type == 'knowledge_base':
        from applications.knowledge_base.services.platform_service import get_knowledge_service
        detail = await (await get_knowledge_service()).detail(context.object_id, user)
        value = {key: detail[key] for key in ('id', 'knowledge_name', 'description', 'version', 'status', 'document_count')}
    elif context.module == 'assets' and context.object_type == 'asset':
        from applications.conversation.services.asset_service import visible_assets, serialize
        asset = await visible_assets(user).filter(id=context.object_id).first()
        if not asset:
            raise HTTPException(403, '无权读取当前资产上下文')
        value = (await serialize([asset], user))[0]
    else:
        raise HTTPException(400, '页面与操作对象类型不匹配')
    return {**result, 'object_type': context.object_type, 'object_id': context.object_id, 'object': value}


def request_snapshots(events, generation):
    return {event['task_id']: event['data'] for event in events
            if event.get('type') == 'request_snapshot' and event.get('generation') == generation}
