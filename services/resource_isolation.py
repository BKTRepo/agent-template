"""Single policy hook for knowledge resources; replace this function for team access."""
from tortoise.expressions import Q


def resolve_isolation_rule(user, *, resource_kind="knowledge", action="read"):
    if resource_kind != "knowledge" or action not in {"read", "write"}:
        raise ValueError("Unsupported isolation policy")
    # 兼容原知识库入口；查询过滤与MCP执行共享同一个隔离策略函数。
    from applications.wrq.knowledge import knowledge_permissions
    policy = knowledge_permissions(user.id, None)
    return policy['write_filter'] if action == 'write' else policy['visible_filter']
