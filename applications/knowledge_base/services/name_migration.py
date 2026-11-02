"""在建好定稿字段后显式回填名称键；审计有冲突时完全不写数据。"""
from tortoise import Tortoise
from tortoise.transactions import in_transaction
from applications.knowledge_base.name_rules import name_key


async def migrate_knowledge_names(connection=None, *, apply=False):
    connection = connection or Tortoise.get_connection("default")
    rows = await connection.execute_query_dict("SELECT id, knowledge_name, state FROM keenrobot_knowledge_bases")
    groups, invalid = {}, []
    for row in rows:
        if row["state"] == 1:
            continue
        if not row["knowledge_name"] or not row["knowledge_name"].strip():
            invalid.append(row["id"])
        else:
            groups.setdefault(name_key(row["knowledge_name"]), []).append(row["id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    result = {"ready": not invalid and not duplicates, "invalid_ids": invalid,
              "duplicate_ids": duplicates, "applied": False, "rows": len(rows)}
    if not apply or not result["ready"]:
        return result
    dialect = connection.capabilities.dialect
    if dialect not in {"sqlite", "mysql"}:
        raise ValueError("名称迁移当前只支持 SQLite/MySQL")
    placeholder = "?" if dialect == "sqlite" else "%s"
    async with in_transaction(connection.connection_name) as conn:
        await conn.execute_query("UPDATE keenrobot_knowledge_bases SET name_key = NULL")
        for row in rows:
            if row["state"] != 1:
                await conn.execute_query(f"UPDATE keenrobot_knowledge_bases SET name_key = {placeholder} WHERE id = {placeholder}",
                                         [name_key(row["knowledge_name"]), row["id"]])
    return {**result, "applied": True}
