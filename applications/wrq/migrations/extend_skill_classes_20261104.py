"""技能大类新增展示字段；默认只预览，--apply 才改表，不写实现类表。"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from applications.wrq.migrations.review_20261024 import connect

TABLE = 'keenrobot_skill_classes'
COLUMNS = {
    'description': "TEXT NULL COMMENT '技能大类描述'",
    'input_schema': "JSON NULL COMMENT '统一输入JSON Schema'",
    'output_schema': "JSON NULL COMMENT '统一输出JSON Schema'",
    'template': "LONGTEXT NULL COMMENT 'Skill模板原文'",
}


async def run(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(f'SHOW COLUMNS FROM `{TABLE}`')
            existing = {row['Field'] for row in await cursor.fetchall()}
            clauses = [f'ADD COLUMN `{key}` {value}' for key, value in COLUMNS.items() if key not in existing]
            sql = f'ALTER TABLE `{TABLE}` ' + ', '.join(clauses) if clauses else None
            print({'apply': apply, 'sql': sql})
            if not apply or not sql:
                return
            await cursor.execute(f'SHOW CREATE TABLE `{TABLE}`')
            before = (await cursor.fetchone())['Create Table']
            backup_dir = Path(__file__).resolve().parents[3] / '.tmp' / 'skill-class-backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f'{datetime.now():%Y%m%dT%H%M%S%f}.sql'
            backup.write_text(before, encoding='utf-8')
            await cursor.execute(sql)
            # 历史行保持空描述；不写入原型演示Schema或模板。
            await cursor.execute(f'UPDATE `{TABLE}` SET description=%s WHERE description IS NULL', ('',))
            await connection.commit()
            print({'updated': True, 'backup': str(backup)})
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
