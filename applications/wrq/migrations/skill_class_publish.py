"""技能大类发布增量迁移；默认只预览，--apply 执行。"""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys

from applications.wrq.migrations.review_20261024 import connect

ADDITIONS = {
    'publication_status': "VARCHAR(16) NOT NULL DEFAULT 'DRAFT'",
    'published_revision': 'INT NULL',
    'published_content': 'JSON NULL',
    'published_at': 'DATETIME(6) NULL',
}


async def migrate(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            tls = await cursor.fetchone()
            if not tls or not tls['Value']:
                raise RuntimeError('拒绝无TLS迁移')
            print('TLS cipher:', tls['Value'])
            await cursor.execute('SHOW COLUMNS FROM keenrobot_skill_classes')
            columns = {row['Field'] for row in await cursor.fetchall()}
            await cursor.execute('SELECT * FROM keenrobot_skill_classes ORDER BY id')
            rows = list(await cursor.fetchall())
            if apply:
                folder = Path(__file__).resolve().parents[4] / '.tmp' / 'skill-class-publish-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                folder.mkdir(parents=True)
                await cursor.execute('SHOW CREATE TABLE keenrobot_skill_classes')
                ddl = await cursor.fetchone()
                (folder / 'before.json').write_text(json.dumps({'ddl': ddl, 'rows': rows}, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
                print(f'backup: {folder}')
            for field, sql_type in ADDITIONS.items():
                if field not in columns:
                    sql = f'ALTER TABLE keenrobot_skill_classes ADD COLUMN `{field}` {sql_type}'
                    print(sql)
                    if apply:
                        await cursor.execute(sql)
            if 'publication_status' not in columns:
                # 保留原已可用的系统预置大类及已有有效实现的引用；未使用的用户创建大类仍为草稿。
                sql = """UPDATE keenrobot_skill_classes c SET publication_status='PUBLISHED', published_revision=revision
 WHERE state=0 AND (create_user_login_name IS NULL OR EXISTS
 (SELECT 1 FROM keenrobot_skills s WHERE s.state=0 AND s.skill_classes_id=c.id))"""
                print(sql)
                if apply:
                    await cursor.execute(sql)
            print('mode:', 'applied' if apply else 'plan only; no changes written')
    finally:
        connection.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(migrate(parser.parse_args().apply))
