"""技能主键及引用统一为有符号 INT(11)；先备份，再事务改号，最后修改列类型。

默认只检查。--apply 执行；执行期间停止技能写入。DDL 中断后可重跑，legacy_id 保留映射。
"""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from tortoise import Tortoise, connections
from tortoise.transactions import in_transaction

from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG

MAX_INT = 2147483647
SKILLS = 'keenrobot_skills'
REFERENCES = (
    'keenrobot_skill_versions', 'keenrobot_skill_resource_bindings',
    'keenrobot_skill_debug_runs', 'keenrobot_skill_publications',
    'keenrobot_online_debug_runs', 'keenrobot_knowledge_executions',
)


def integer_mapping(ids):
    """保留已有正整数编号，其余稳定分配，避免更新过程中主键冲突。"""
    used = {int(value) for value in ids if str(value).isdigit() and 0 < int(value) <= MAX_INT}
    next_id = max(used, default=0) + 1
    mapping = {}
    for value in ids:
        text = str(value)
        if text.isdigit() and str(int(text)) == text and int(text) in used:
            mapping[text] = int(text)
        else:
            if next_id > MAX_INT:
                raise ValueError('技能编号超过有符号 INT 范围')
            mapping[text] = next_id
            next_id += 1
    return mapping


async def migrate(apply=False):
    await Tortoise.init(config={
        'connections': wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps': {'models': {'models': PROJECT_CONFIG.APPLICATIONS_MODELS, 'default_connection': 'default'}},
        'use_tz': False, 'timezone': 'Asia/Shanghai',
    })
    try:
        db = connections.get('default')
        columns = await db.execute_query_dict(
            "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,COLUMN_COMMENT "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()")
        existing = {r['TABLE_NAME'] for r in columns}
        refs = [table for table in REFERENCES if table in existing]
        unexpected = {r['TABLE_NAME'] for r in columns if r['COLUMN_NAME'] == 'skill_id'} - set(REFERENCES)
        if unexpected:
            raise RuntimeError(f'发现未纳入迁移的技能引用表：{sorted(unexpected)}')
        foreign_keys = await db.execute_query_dict(
            "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME='keenrobot_skills'")
        if foreign_keys:
            raise RuntimeError('发现额外外键，需先纳入迁移计划')
        skills = await db.execute_query_dict(f'SELECT * FROM `{SKILLS}` ORDER BY created_time,id')
        mapping = integer_mapping([row['id'] for row in skills])
        tables = {SKILLS: skills}
        for table in refs:
            rows = await db.execute_query_dict(f'SELECT * FROM `{table}`')
            unknown = {str(row['skill_id']) for row in rows} - set(mapping)
            if unknown:
                raise RuntimeError(f'{table} 有 {len(unknown)} 个无对应技能的编号，迁移已停止')
            tables[table] = rows
        def preserve_time(table):
            return ', updated_time=updated_time' if any(
                r['TABLE_NAME'] == table and r['COLUMN_NAME'] == 'updated_time' for r in columns) else ''
        def comment(table, name):
            value = next((r['COLUMN_COMMENT'] for r in columns
                          if r['TABLE_NAME'] == table and r['COLUMN_NAME'] == name), '')
            return " COMMENT '" + value.replace('\\', '\\\\').replace("'", "''") + "'"
        # 对本次开发者中心表中的整数列统一 signed INT；容量字节数字段保持 BIGINT。
        owned = {SKILLS, *refs, 'keenrobot_skill_forms', 'keenrobot_skill_classes',
                 'keenrobot_skill_uploaded_files', 'keenrobot_resource_categories',
                 'keenrobot_knowledge_tool_calls'}
        numeric = [r for r in columns if r['TABLE_NAME'] in owned
                   and (r['COLUMN_TYPE'].lower().startswith(('int', 'bigint')))
                   and r['COLUMN_NAME'] not in {'byte_size', 'result_byte_size'}]
        for col in numeric:
            table, name = col['TABLE_NAME'], col['COLUMN_NAME']
            bounds = await db.execute_query_dict(f'SELECT MIN(`{name}`) lo, MAX(`{name}`) hi FROM `{table}`')
            if bounds[0]['lo'] is not None and (bounds[0]['lo'] < -2147483648 or bounds[0]['hi'] > MAX_INT):
                raise RuntimeError(f'{table}.{name} 超出 INT 范围，未执行迁移')
        print(json.dumps({'skills': len(skills), 'reference_counts': {t: len(tables[t]) for t in refs},
                          'mapping': mapping, 'integer_columns': len(numeric), 'apply': apply}, ensure_ascii=False))
        if not apply:
            return
        backup = Path('.tmp/skill-integer-migration') / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        (backup/'backup.json').write_text(json.dumps({'columns': columns, 'tables': tables, 'mapping': mapping},
                                                   ensure_ascii=False, default=str), encoding='utf8')
        print(f'backup={backup.resolve()}')
        if not any(r['TABLE_NAME'] == SKILLS and r['COLUMN_NAME'] == 'legacy_id' for r in columns):
            await db.execute_script(f'ALTER TABLE `{SKILLS}` ADD COLUMN legacy_id VARCHAR(64) NULL UNIQUE COMMENT \'迁移前技能编号；仅用于核验历史构建\'')
        async with in_transaction() as tx:
            # 锁住技能范围，确认备份与待变更记录一致；所有关系在同一事务内改号。
            current = await tx.execute_query_dict(f'SELECT * FROM `{SKILLS}` ORDER BY created_time,id FOR UPDATE')
            if [str(row['id']) for row in current] != [str(row['id']) for row in skills]:
                raise RuntimeError('备份后技能发生变化，未改号，请重试')
            for old, new in mapping.items():
                if old == str(new):
                    continue
                await tx.execute_query(f'UPDATE `{SKILLS}` SET legacy_id=COALESCE(legacy_id,%s){preserve_time(SKILLS)} WHERE id=%s', [old, old])
                for table in refs:
                    await tx.execute_query(f'UPDATE `{table}` SET skill_id=%s{preserve_time(table)} WHERE skill_id=%s', [str(new), old])
                await tx.execute_query(f'UPDATE `{SKILLS}` SET id=%s{preserve_time(SKILLS)} WHERE id=%s', [str(new), old])
        for table in refs:
            await db.execute_script(f'ALTER TABLE `{table}` MODIFY COLUMN skill_id INT(11) NOT NULL{comment(table, "skill_id")}')
        await db.execute_script(f'ALTER TABLE `{SKILLS}` MODIFY COLUMN id INT(11) NOT NULL AUTO_INCREMENT{comment(SKILLS, "id")}')
        for col in numeric:
            table, name = col['TABLE_NAME'], col['COLUMN_NAME']
            if name == 'skill_id' or table == SKILLS and name == 'id':
                continue
            null = 'NULL' if col['IS_NULLABLE'] == 'YES' else 'NOT NULL'
            default = '' if col['COLUMN_DEFAULT'] is None else f" DEFAULT {int(col['COLUMN_DEFAULT'])}"
            extra = ' AUTO_INCREMENT' if 'auto_increment' in col['EXTRA'] else ''
            await db.execute_script(f'ALTER TABLE `{table}` MODIFY COLUMN `{name}` INT(11) {null}{default}{extra}{comment(table, name)}')
        for table in refs:
            orphan = await db.execute_query_dict(f'SELECT COUNT(*) n FROM `{table}` r LEFT JOIN `{SKILLS}` s ON s.id=r.skill_id WHERE s.id IS NULL')
            if orphan[0]['n']:
                raise RuntimeError(f'{table} 引用校验失败；保留备份供恢复')
            after = await db.execute_query_dict(f'SELECT COUNT(*) n FROM `{table}`')
            if after[0]['n'] != len(tables[table]):
                raise RuntimeError(f'{table} 行数发生变化，请检查并发写入')
        print('verified: all skill references preserved; signed INT; skill AUTO_INCREMENT')
    finally:
        await Tortoise.close_connections()


if __name__ == '__main__':
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(migrate(parser.parse_args().apply))
