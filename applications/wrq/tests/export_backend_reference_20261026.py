"""只读导出数据库结构和本机OpenAPI；不导出用户、审计或业务行数据。"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

from applications.wrq.migrations.review_20261024 import connect
from configure import PROJECT_CONFIG

OUT = Path(__file__).resolve().parents[4] / 'deliverables'


async def main():
    conn = await connect()
    try:
        async with conn.cursor() as cur:
            await cur.execute('SHOW SESSION STATUS LIKE \'Ssl_cipher\'')
            tls = (await cur.fetchone())['Value']
            await cur.execute('SELECT TABLE_NAME, TABLE_COMMENT, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', [PROJECT_CONFIG.DATABASE_NAME])
            tables = await cur.fetchall()
            for table in tables:
                name = table['TABLE_NAME']
                await cur.execute('SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, EXTRA, COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION', [PROJECT_CONFIG.DATABASE_NAME, name])
                table['columns'] = await cur.fetchall()
                await cur.execute('SHOW CREATE TABLE `' + name.replace('`', '``') + '`')
                table['ddl'] = (await cur.fetchone())['Create Table']
            await cur.execute('SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION', [PROJECT_CONFIG.DATABASE_NAME])
            constraints = await cur.fetchall()
            await cur.execute('SELECT id, code, name, is_enabled FROM keenrobot_resource_categories ORDER BY id')
            categories = await cur.fetchall()
        result = {'captured_at': datetime.now().astimezone().isoformat(), 'database': PROJECT_CONFIG.DATABASE_NAME,
                  'tls_cipher': tls, 'automatic_migration': PROJECT_CONFIG.DATABASE_AUTO_MIGRATION,
                  'certificate_ca_configured': bool(PROJECT_CONFIG.DATABASE_SSL_CA),
                  'tables': tables, 'constraints': constraints, 'resource_categories': categories}
        OUT.mkdir(exist_ok=True)
        (OUT / '开发者中心_最终后端_数据库结构快照_20261026.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    finally:
        conn.close()
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get('http://127.0.0.1:8519/openapi_url', timeout=30)
        response.raise_for_status()
        schema = response.json()
        (OUT / '开发者中心_最终后端_OpenAPI快照_20261026.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'table_count': len(tables), 'columns': {t['TABLE_NAME']: len(t['columns']) for t in tables},
                      'tls': bool(tls), 'automatic_migration': result['automatic_migration'],
                      'openapi_paths': len(schema['paths'])}, ensure_ascii=False))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
