"""Resolve already-bound knowledge IDs to their current metadata, without editing skills."""
from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase
from applications.knowledge_base.schemas.platform_schema import next_version


async def current_knowledge_references(bindings):
    bindings = [row for row in bindings if row.source_type == 'knowledge_base']
    if not bindings:
        return []
    # Skill visibility/ownership is checked by the caller. Only metadata for IDs
    # already in that skill version is exposed; document access still uses the
    # existing knowledge permissions and runtime document_scope checks.
    current = {row['id']: row for row in await KnowledgeBase.filter(
        id__in=[binding.source_id for binding in bindings], state__not=1,
    ).values('id', 'knowledge_name', 'revision')}
    result = []
    for binding in bindings:
        kb = current.get(binding.source_id)
        reference = {'id': binding.source_id,
                     'name': kb['knowledge_name'] if kb else binding.display_name or str(binding.source_id),
                     'source': 'backend'}
        if kb:
            reference['version'] = next_version(kb['revision'])
        result.append(reference)
    return result
