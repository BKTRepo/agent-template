"""Stable tag codes with editable labels, ordering and enabled state."""
from applications.knowledge_base.models.knowledge_base_model import KnowledgeTag


async def tag_options(include_disabled=False):
    query = KnowledgeTag.all() if include_disabled else KnowledgeTag.filter(is_enabled=True)
    return await query.order_by('sort_order', 'id').values('id', 'code', 'name', 'is_enabled', 'sort_order')


async def validate_tag(code, previous=None):
    if not code or code == previous:
        return
    if not await KnowledgeTag.filter(code=code, is_enabled=True).exists():
        raise ValueError('请选择有效的知识库标签')
