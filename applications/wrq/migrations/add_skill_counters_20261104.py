"""只添加已确认的统计列与大类定义列；强制SSL，不创建知识库表或修改既有编号。"""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import ssl
import sys

import asyncmy
from asyncmy.cursors import DictCursor
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
ADDITIONS = {
    'keenrobot_skills': {
        'call_count': "BIGINT NOT NULL DEFAULT 0 COMMENT '技能中心累计接受的在线测试任务数'",
        'download_count': "BIGINT NOT NULL DEFAULT 0 COMMENT '成功生成并返回技能ZIP的累计次数'",
    },
    'keenrobot_skill_classes': {
        'description': "TEXT NULL COMMENT '技能大类描述'",
        'input_schema': "JSON NULL COMMENT '统一输入JSON Schema'",
        'output_schema': "JSON NULL COMMENT '统一输出JSON Schema'",
        'template': "LONGTEXT NULL COMMENT 'Skill模板原文'",
    },
}


async def connect_ssl():
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    context = ssl.create_default_context(cafile=config.get('DATABASE_SSL_CA') or None)
    if not config.get('DATABASE_SSL_CA'):
        # 与现有部署适配器一致：没有私有CA时只加密；仍强制检查实际SSL会话。
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return await asyncmy.connect(host=config['DATABASE_HOST'], port=int(config['DATABASE_PORT']),
        user=config['DATABASE_USERNAME'], password=config['DATABASE_PASSWORD'], db=config['DATABASE_NAME'],
        ssl=context, autocommit=True, cursor_cls=DictCursor, connect_timeout=15, read_timeout=30)


async def run(apply=False):
    connection = await connect_ssl()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute('SHOW SESSION STATUS LIKE %s', ('Ssl_cipher',))
            ssl_state = await cursor.fetchone()
            if not ssl_state or not ssl_state['Value']:
                raise RuntimeError('拒绝未使用SSL的连接')
            before, plans = {}, []
            for table, additions in ADDITIONS.items():
                await cursor.execute(f'SHOW COLUMNS FROM `{table}`')
                columns = {row['Field']: row for row in await cursor.fetchall()}
                for name in ('call_count', 'download_count'):
                    if table == 'keenrobot_skills' and name in columns:
                        column = columns[name]
                        if not column['Type'].lower().startswith('bigint') or column['Null'] != 'NO' or str(column['Default']) != '0':
                            raise RuntimeError(f'{table}.{name}已存在但定义不同，拒绝覆盖')
                missing = {name: definition for name, definition in additions.items() if name not in columns}
                if missing:
                    plans.append((table, 'ALTER TABLE `' + table + '` ' + ', '.join(
                        f'ADD COLUMN `{name}` {definition}' for name, definition in missing.items())))
                await cursor.execute(f'SHOW CREATE TABLE `{table}`')
                before[table] = (await cursor.fetchone())['Create Table']
            print(json.dumps({'apply': apply, 'ssl_cipher': ssl_state['Value'], 'sql': [sql for _, sql in plans]}, ensure_ascii=False))
            if not apply or not plans:
                return
            backup_dir = ROOT / '.tmp' / 'skill-counter-backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f'{datetime.now():%Y%m%dT%H%M%S%f}.json'
            backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
            for table, sql in plans:
                await cursor.execute(sql)
                await cursor.execute(f'SHOW COLUMNS FROM `{table}`')
                actual = {row['Field']: row for row in await cursor.fetchall()}
                assert all(name in actual for name in ADDITIONS[table])
            print(json.dumps({'verified': True, 'backup': str(backup), 'tables': [table for table, _ in plans]}, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
