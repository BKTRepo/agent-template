"""已有数据库的显式迁移：先审计，冲突时不改表、不改业务名称。

应用迁移必须在停止技能写入后运行；MySQL DDL 不受事务回滚保护，失败可重跑。
"""
from applications.agent.skill_names import SkillNameError, skill_name_key
from tortoise.transactions import in_transaction


async def migrate_skill_names(connection, *, apply=False):
    dialect = connection.capabilities.dialect
    if dialect not in {"sqlite", "mysql"}:
        raise ValueError("当前迁移仅支持 SQLite 与 MySQL")
    rows = await connection.execute_query_dict("SELECT id, name, state FROM keenrobot_skills")
    groups, invalid, keys = {}, [], {}
    for row in rows:
        if row["state"] == 1:
            keys[row["id"]] = None
            continue
        try:
            key = skill_name_key(row["name"])
        except SkillNameError:
            invalid.append(row["id"])
            continue
        keys[row["id"]] = key
        groups.setdefault(key, []).append(row["id"])
    conflicts = [ids for ids in groups.values() if len(ids) > 1]
    result = {"ready": not invalid and not conflicts, "rows": len(rows), "invalid_ids": invalid,
              "duplicate_ids": conflicts, "applied": False}
    if not apply or not result["ready"]:
        return result
    if dialect == "sqlite":
        columns = await connection.execute_query_dict("PRAGMA table_info(keenrobot_skills)")
        has_column = any(row["name"] == "name_key" for row in columns)
        indexes = await connection.execute_query_dict("PRAGMA index_list(keenrobot_skills)")
        has_unique = False
        for index in indexes:
            # 名称来自 SQLite 系统表；使用双引号转义，不能直接拼接为标识符。
            quoted = index["name"].replace('"', '""')
            fields = await connection.execute_query_dict(f'PRAGMA index_info("{quoted}")')
            has_unique |= bool(index["unique"] and [field["name"] for field in fields] == ["name_key"])
        column_sql = "ALTER TABLE keenrobot_skills ADD COLUMN name_key VARCHAR(64) NULL"
        parameter = "?"
    else:
        columns = await connection.execute_query_dict("SHOW COLUMNS FROM keenrobot_skills")
        has_column = any(row["Field"] == "name_key" for row in columns)
        indexes = await connection.execute_query_dict("SHOW INDEX FROM keenrobot_skills")
        grouped = {}
        for row in indexes:
            grouped.setdefault(row["Key_name"], []).append(row)
        has_unique = any(len(fields) == 1 and fields[0]["Non_unique"] == 0
                         and fields[0]["Column_name"] == "name_key" for fields in grouped.values())
        column_sql = "ALTER TABLE keenrobot_skills ADD COLUMN name_key VARCHAR(64) NULL"
        parameter = "%s"
    if not has_column:
        await connection.execute_script(column_sql)
    # 数据迁移全程事务；已存在键先清空，避免旧键与待回填键互相占用。
    async with in_transaction(connection.connection_name) as transaction:
        await transaction.execute_query("UPDATE keenrobot_skills SET name_key = NULL")
        for skill_id, key in keys.items():
            await transaction.execute_query(
                f"UPDATE keenrobot_skills SET name_key = {parameter} WHERE id = {parameter}", [key, skill_id])
    if not has_unique:
        await connection.execute_script("CREATE UNIQUE INDEX uq_skill_name_key ON keenrobot_skills (name_key)")
    result["applied"] = True
    return result
