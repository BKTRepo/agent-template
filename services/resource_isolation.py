"""Single policy hook for knowledge resources; replace this function for team access."""
from tortoise.expressions import Q


def resolve_isolation_rule(user, *, resource_kind="knowledge", action="read"):
    if resource_kind != "knowledge" or action not in {"read", "write"}:
        raise ValueError("Unsupported isolation policy")
    owned = Q(user_id=user.id)
    return owned if action == "write" else owned | Q(is_public=True)
