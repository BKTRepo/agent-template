"""Resolve a published skill's bindings using the caller's knowledge access policy."""
from applications.knowledge_base.models.knowledge_base_model import Document, KnowledgeBase
from applications.knowledge_base.schemas.platform_schema import next_version
from applications.wrq.agent.models.agent_model import SkillResourceBinding
from services.resource_isolation import resolve_isolation_rule


async def visible_skill_knowledge(version_id, user):
    bindings = await SkillResourceBinding.filter(
        skill_version_id=version_id, source_type__in=('knowledge_base', 'knowledge_document'),
    ).order_by('sort_order', 'id')
    document_ids = [binding.source_id for binding in bindings if binding.source_type == 'knowledge_document']
    documents = dict(await Document.filter(id__in=document_ids, is_deleted=False).values_list(
        'id', 'knowledge_base_id',
    )) if document_ids else {}
    ids = list(dict.fromkeys(
        binding.source_id if binding.source_type == 'knowledge_base' else documents.get(binding.source_id)
        for binding in bindings
    ))
    ids = [value for value in ids if value]
    if not ids:
        return []
    visible = {row['id']: row for row in await KnowledgeBase.filter(
        resolve_isolation_rule(user), id__in=ids, state__not=1,
    ).values('id', 'knowledge_name', 'revision')}
    return [
        {'id': value, 'name': visible[value]['knowledge_name'],
         'version': next_version(visible[value]['revision']), 'source': 'backend'}
        for value in ids if value in visible
    ]
