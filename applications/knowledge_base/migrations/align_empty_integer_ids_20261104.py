"""将用户确认的空知识库七表改为INT主键；强制SSL、备份、空表检查和外键保留。

默认预览；--apply执行。任何表已有数据即拒绝本空表方案，不能隐式转换字符串编号。
ALTER可能释放表锁，按MySQL文档每步重新加锁并再次检查空表。
https://dev.mysql.com/doc/refman/8.0/en/lock-tables.html
"""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
import sys

from applications.wrq.migrations.add_skill_counters_20261104 import connect_ssl

ROOT = Path(__file__).resolve().parents[3]
TABLES = ('keenrobot_knowledge_bases', 'keenrobot_documents', 'keenrobot_document_chunks',
          'rag_document', 'rag_pipeline_state', 'rag_pipeline_history', 'llm_call_log')
REFERENCES = {'keenrobot_documents': ('knowledge_base_id', 'keenrobot_knowledge_bases', False),
              'keenrobot_document_chunks': ('document_id', 'keenrobot_documents', False),
              'rag_document': ('knowledge_document_id', 'keenrobot_documents', True)}
EXPECTED_FKS = {('keenrobot_documents', 'knowledge_base_id', 'keenrobot_knowledge_bases', 'id'),
                ('keenrobot_document_chunks', 'document_id', 'keenrobot_documents', 'id')}


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_]+', value):
        raise RuntimeError('非预期SQL标识符，拒绝拼接')
    return '`' + value + '`'


def build_plan(columns, foreign_keys):
    alterations = []
    for table in TABLES:
        fields = columns[table]
        changes = []
        pk = fields['id']
        if pk['Key'] != 'PRI':
            raise RuntimeError(f'{table}主键定义与预期不同')
        if pk['Type'].lower() != 'int' or 'auto_increment' not in pk['Extra']:
            changes.append('MODIFY COLUMN `id` INT NOT NULL AUTO_INCREMENT')
        if table in REFERENCES:
            name, _, nullable = REFERENCES[table]
            column = fields[name]
            null_value = 'YES' if nullable else 'NO'
            if column['Type'].lower() != 'int' or column['Null'] != null_value:
                changes.append(f'MODIFY COLUMN {identifier(name)} INT ' + ('NULL' if nullable else 'NOT NULL'))
        if changes:
            alterations.append(f'ALTER TABLE {identifier(table)} ' + ', '.join(changes))
    drops, restores, seen = [], [], set()
    for key in foreign_keys:
        signature = tuple(key[name] for name in ('TABLE_NAME', 'COLUMN_NAME', 'REFERENCED_TABLE_NAME', 'REFERENCED_COLUMN_NAME'))
        if signature == ('keenrobot_knowledge_bases', 'user_id', 'keenrobot_user', 'id'):
            continue  # 用户编号保持BIGINT及原有外键，不在本次变更范围。
        if signature not in EXPECTED_FKS:
            raise RuntimeError('存在额外外键引用，需先明确映射，拒绝隐式修改')
        seen.add(signature)
        table, column, parent, target = signature
        name = key['CONSTRAINT_NAME']
        rules = (key['DELETE_RULE'], key['UPDATE_RULE'])
        if any(rule not in {'CASCADE', 'RESTRICT', 'NO ACTION', 'SET NULL'} for rule in rules):
            raise RuntimeError('非预期外键规则')
        drops.append(f'ALTER TABLE {identifier(table)} DROP FOREIGN KEY {identifier(name)}')
        restores.append(f'ALTER TABLE {identifier(table)} ADD CONSTRAINT {identifier(name)} FOREIGN KEY ({identifier(column)}) '
                        f'REFERENCES {identifier(parent)} ({identifier(target)}) ON DELETE {rules[0]} ON UPDATE {rules[1]}')
    if seen != EXPECTED_FKS:
        raise RuntimeError('原有文档外键缺失，需先核对结构')
    if not alterations:
        return []
    return drops + alterations + restores


async def read_metadata(cursor):
    columns, counts, ddl = {}, {}, {}
    for table in TABLES:
        await cursor.execute(f'SHOW COLUMNS FROM {identifier(table)}')
        columns[table] = {row['Field']: row for row in await cursor.fetchall()}
        await cursor.execute(f'SELECT COUNT(*) AS n FROM {identifier(table)}')
        counts[table] = (await cursor.fetchone())['n']
        await cursor.execute(f'SHOW CREATE TABLE {identifier(table)}')
        ddl[table] = (await cursor.fetchone())['Create Table']
    placeholders = ','.join(['%s'] * len(TABLES))
    await cursor.execute('SELECT k.TABLE_NAME,k.COLUMN_NAME,k.CONSTRAINT_NAME,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,'
        'r.DELETE_RULE,r.UPDATE_RULE FROM information_schema.KEY_COLUMN_USAGE k '
        'JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA=k.TABLE_SCHEMA '
        'AND r.TABLE_NAME=k.TABLE_NAME AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME '
        'WHERE k.TABLE_SCHEMA=DATABASE() AND (k.TABLE_NAME IN (' + placeholders + ') OR k.REFERENCED_TABLE_NAME IN (' + placeholders + '))', TABLES + TABLES)
    return {'columns': columns, 'counts': counts, 'ddl': ddl, 'foreign_keys': list(await cursor.fetchall())}


async def assert_empty(cursor):
    for table in TABLES:
        await cursor.execute(f'SELECT COUNT(*) AS n FROM {identifier(table)}')
        if (await cursor.fetchone())['n']:
            raise RuntimeError(f'{table}已有数据，拒绝空表编号迁移')
    await cursor.execute("SELECT COUNT(*) AS n FROM keenrobot_skill_resource_bindings WHERE source_type IN ('knowledge_base','knowledge_document')")
    if (await cursor.fetchone())['n']:
        raise RuntimeError('已存在知识库技能绑定，需要先映射来源编号')


async def run(apply=False):
    connection = await connect_ssl()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute('SHOW SESSION STATUS LIKE %s', ('Ssl_cipher',))
            cipher = (await cursor.fetchone())['Value']
            if not cipher:
                raise RuntimeError('拒绝无SSL连接')
            before = await read_metadata(cursor)
            sql = build_plan(before['columns'], before['foreign_keys'])
            print(json.dumps({'apply': apply, 'ssl_cipher': cipher, 'row_counts': before['counts'], 'sql': sql}, ensure_ascii=False))
            if not sql:
                return
            await assert_empty(cursor)
            if not apply:
                return
            backup_dir = ROOT / '.tmp' / 'knowledge-id-backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f'{datetime.now():%Y%m%dT%H%M%S%f}.json'
            journal = {'before': before, 'planned': sql, 'executed': []}
            backup.write_text(json.dumps(journal, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            await cursor.execute('SET SESSION lock_wait_timeout=10')
            lock_sql = 'LOCK TABLES ' + ','.join(f'{identifier(table)} WRITE' for table in TABLES) + ',`keenrobot_user` READ,`keenrobot_skill_resource_bindings` READ'
            try:
                for statement in sql:
                    await cursor.execute(lock_sql)
                    await assert_empty(cursor)
                    await cursor.execute(statement)
                    journal['executed'].append(statement)
                    backup.write_text(json.dumps(journal, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            finally:
                await cursor.execute('UNLOCK TABLES')
            after = await read_metadata(cursor)
            if build_plan(after['columns'], after['foreign_keys']):
                raise RuntimeError('迁移后列定义复核失败')
            journal['after'] = after
            backup.write_text(json.dumps(journal, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            print(json.dumps({'verified': True, 'backup': str(backup), 'tables': list(TABLES)}, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
