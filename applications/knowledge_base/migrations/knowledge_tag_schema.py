"""Explicit additive tag dictionary migration; reruns preserve administrator edits."""
import argparse
import asyncio
from applications.wrq.migrations.review_20261024 import connect

TABLE = 'keenrobot_knowledge_tags'
SQL = '''CREATE TABLE IF NOT EXISTS keenrobot_knowledge_tags (
id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
code VARCHAR(32) NOT NULL UNIQUE,
name VARCHAR(64) NOT NULL,
is_enabled BOOL NOT NULL DEFAULT 1,
sort_order INT NOT NULL DEFAULT 0,
created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) CHARACTER SET utf8mb4 COMMENT='知识库标签配置';'''

async def run(apply=False):
    connection=await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute('SHOW TABLES LIKE %s',(TABLE,))
            exists=bool(await cursor.fetchone())
            print({'apply':apply,'table_exists':exists,'sql':SQL})
            if not apply:return
            await cursor.execute(SQL)
            await cursor.execute('SHOW COLUMNS FROM keenrobot_knowledge_tags')
            columns={row['Field'] for row in await cursor.fetchall()}
            if not {'id','code','name','is_enabled','sort_order','created_at','updated_at'} <= columns:
                raise RuntimeError('Existing tag dictionary schema is incompatible')
            for code,name,order in [('general','通识类',10),('custom','自定义',20)]:
                await cursor.execute('INSERT INTO keenrobot_knowledge_tags (code,name,is_enabled,sort_order) '
                    'VALUES (%s,%s,1,%s) ON DUPLICATE KEY UPDATE code=code',(code,name,order))
            await connection.commit()
            await cursor.execute('SELECT code,name,is_enabled,sort_order FROM keenrobot_knowledge_tags ORDER BY sort_order,id')
            print({'verified':await cursor.fetchall()})
    finally:connection.close()

if __name__=='__main__':
    import sys
    if sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    asyncio.run(run(parser.parse_args().apply))
