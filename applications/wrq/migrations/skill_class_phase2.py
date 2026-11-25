"""二期大类迁移；默认只预览，--apply 显式执行。迁移期间暂停技能写入。

历史大类新增业务字段保持 NULL，由产品后续直接在数据库补填。
"""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

from applications.wrq.migrations.review_20261024 import connect

STAGES = [
    ('planning', '测试规划', '需求分析、测试策略与范围界定'),
    ('design', '测试设计', '要点、用例、评审与脚本设计'),
    ('data', '数据准备', '测试数据、环境与依赖准备'),
    ('execution', '测试执行', '自动化执行、缺陷发现与归因'),
    ('measurement', '测试度量', '覆盖率、质量报告与效能分析'),
    ('support', '测试支撑', '平台工具与通用能力支撑'),
    ('management', '测试管理', '计划、进度、人员与质量门禁管理'),
]
ADDITIONS = {
    'test_stage_id': 'INT NULL', 'input_description': 'VARCHAR(200) NULL',
    'output_description': 'VARCHAR(200) NULL', 'create_user_login_name': 'VARCHAR(10) NULL',
    'update_user_login_name': 'VARCHAR(10) NULL', 'revision': 'INT NOT NULL DEFAULT 1',
    'state': 'SMALLINT NOT NULL DEFAULT 0', 'active_name_key': 'CHAR(64) NULL',
    'created_time': 'DATETIME(6) NULL', 'updated_time': 'DATETIME(6) NULL', 'deleted_time': 'DATETIME(6) NULL',
}
CREATE_STAGE = """CREATE TABLE IF NOT EXISTS keenrobot_test_stages (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, code VARCHAR(32) NOT NULL UNIQUE,
 name VARCHAR(20) NOT NULL, description VARCHAR(200) NOT NULL DEFAULT '',
 sort_order INT NOT NULL DEFAULT 0, is_enabled BOOL NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def name_key(name):
    return hashlib.sha256(unicodedata.normalize('NFKC', name).strip().casefold().encode('utf-8')).hexdigest()


async def migrate(*, apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute('SELECT * FROM keenrobot_skill_classes ORDER BY id')
            rows = list(await cursor.fetchall())
            keys = {}
            for row in rows:
                if row.get('state', 0) == 0:
                    key = name_key(row['name'])
                    if key in keys:
                        raise ValueError(f"历史大类名称标准化后重复：{keys[key]} / {row['id']}，请先人工处理")
                    keys[key] = row['id']
            await cursor.execute('SHOW COLUMNS FROM keenrobot_skill_classes')
            columns = {row['Field'] for row in await cursor.fetchall()}
            await cursor.execute('SHOW INDEX FROM keenrobot_skill_classes')
            indexes = list(await cursor.fetchall())
            if apply:
                folder = Path(__file__).resolve().parents[4] / '.tmp' / 'skill-class-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                folder.mkdir(parents=True)
                await cursor.execute('SHOW CREATE TABLE keenrobot_skill_classes')
                ddl = await cursor.fetchone()
                (folder / 'before.json').write_text(json.dumps({'ddl': ddl, 'rows': rows}, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
                print(f'backup: {folder}')

            async def execute(sql, args=None):
                print(sql + (' [参数化]' if args else ''))
                if apply:
                    await cursor.execute(sql, args)

            await execute(CREATE_STAGE)
            for field, sql_type in ADDITIONS.items():
                if field not in columns:
                    await execute(f'ALTER TABLE keenrobot_skill_classes ADD COLUMN `{field}` {sql_type}')
            for order, (code, name, description) in enumerate(STAGES, 1):
                await execute('INSERT INTO keenrobot_test_stages (code,name,description,sort_order) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE code=VALUES(code)', [code, name, description, order])
            for row in rows:
                await execute('UPDATE keenrobot_skill_classes SET active_name_key=%s WHERE id=%s',
                              [name_key(row['name']) if row.get('state', 0) == 0 else None, row['id']])
            # Create replacement uniqueness before removing the old name index.
            groups = {}
            for entry in indexes:
                groups.setdefault(entry['Key_name'], []).append(entry)
            if not any(len(parts) == 1 and parts[0]['Column_name'] == 'active_name_key' and parts[0]['Non_unique'] == 0 for parts in groups.values()):
                await execute('CREATE UNIQUE INDEX uq_skill_class_active_name ON keenrobot_skill_classes (active_name_key)')
            if not any(len(parts) == 1 and parts[0]['Column_name'] == 'test_stage_id' for parts in groups.values()):
                await execute('CREATE INDEX ix_skill_class_stage ON keenrobot_skill_classes (test_stage_id)')
            for key, parts in groups.items():
                if key != 'PRIMARY' and len(parts) == 1 and parts[0]['Column_name'] == 'name' and parts[0]['Non_unique'] == 0:
                    await execute('ALTER TABLE keenrobot_skill_classes DROP INDEX `' + key.replace('`', '``') + '`')
            print('mode:', 'applied' if apply else 'plan only; no changes written')
    finally:
        connection.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply))
