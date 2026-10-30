"""删除用户明确指定的WRQ自建用户/应用表；默认只读，--apply显式执行。
全量备份存用户私有目录，避免账号数据进入项目；绝不删除同事的任务表。
"""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from applications.wrq.migrations.review_20261024 import connect
from applications.wrq.migrations.review_20261026 import snapshot

TARGETS={'keenrobot_user','keenrobot_applications'}
PROTECTED={'keenrobot_online_debug_runs','keenrobot_audit','aerich'}

async def run(apply=False):
    conn=await connect()
    folder=Path.home()/'.codex/private/wrq-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-identity')
    folder.mkdir(parents=True,exist_ok=False)
    try:
        async with conn.cursor() as cur:
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            tls=(await cur.fetchone())['Value']
            if not tls: raise RuntimeError('拒绝无TLS连接')
            before=await snapshot(cur)
            backups={}
            for name in TARGETS & before.keys():
                await cur.execute(f'SELECT * FROM `{name}`')
                backups[name]={'ddl':before[name]['ddl'],'rows':list(await cur.fetchall())}
            backupfile=folder/'local_identity_tables.json'
            backupfile.write_text(json.dumps(backups,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            await cur.execute('SELECT TABLE_NAME,CONSTRAINT_NAME,REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IN (%s,%s)',sorted(TARGETS))
            references=list(await cur.fetchall())
            if references: raise RuntimeError('仍有数据库外键依赖，未删除表')
            report={'mode':'plan','tls':tls,'backup':str(backupfile),'drop_tables':sorted(backups),
                    'foreign_key_dependents':references,'other_tables_untouched':True}
            if apply:
                for name in sorted(backups):
                    if name not in TARGETS: raise RuntimeError('拒绝非指定表')
                    await cur.execute(f'DROP TABLE `{name}`')
                after=await snapshot(cur)
                checks={n:{'ddl_unchanged':before[n]['ddl']==after[n]['ddl'],
                    'rows_unchanged':before[n]['hash']==after[n]['hash']} for n in before.keys()-TARGETS}
                report.update(mode='applied',preserved_checks=checks,remaining_table_count=len(after))
                if not all(v['ddl_unchanged'] and v['rows_unchanged'] for v in checks.values()):
                    raise RuntimeError('检测到其它表的外部变化，请核对；未更新它们')
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        conn.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--apply',action='store_true'); args=p.parse_args()
    if sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply))
