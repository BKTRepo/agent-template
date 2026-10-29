"""经用户明确授权，只恢复keenrobot_user；默认只读，--apply才执行。

从删除前私有备份恢复原DDL及原记录，不恢复应用表，不执行自动迁移。
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from applications.wrq.migrations.review_20261024 import connect, digest
from applications.wrq.migrations.review_20261026 import snapshot

TARGET = 'keenrobot_user'
BACKUP = Path.home()/'.codex/private/wrq-backups/20261026T032659Z-identity/local_identity_tables.json'


def same_rows(left, right):
    ordered = lambda rows: sorted(rows, key=lambda row: str(row['id']))
    return digest(ordered(left)) == digest(ordered(right))


async def run(apply=False):
    backup = json.loads(BACKUP.read_text('utf8'))[TARGET]
    ddl, rows = backup['ddl'], backup['rows']
    if not re.match(r'^CREATE TABLE `keenrobot_user` \(', ddl) or ';' in ddl:
        raise RuntimeError('备份DDL不是预期的单张用户表，拒绝执行')
    if not rows or any(not re.fullmatch(r'[a-z_]+', column) for row in rows for column in row):
        raise RuntimeError('用户备份缺失或列名异常')
    folder = Path.home()/'.codex/private/wrq-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ-restore-user')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'mode':'plan','table':TARGET,'backup_row_count':len(rows),
              'backup_column_count':len(rows[0]),'restore_applications':False,
              'automatic_migration':False,'private_evidence':str(folder)}
    conn = await connect()
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            report['tls_cipher'] = (await cursor.fetchone())['Value']
            if not report['tls_cipher']:
                raise RuntimeError('拒绝无TLS连接')
            before = await snapshot(cursor)
            (folder/'before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            report['table_already_exists'] = TARGET in before
            if not apply:
                return report
            if TARGET in before:
                await cursor.execute('SELECT * FROM `keenrobot_user` ORDER BY id')
                existing = list(await cursor.fetchall())
                if existing:
                    if not same_rows(existing, rows):
                        raise RuntimeError('用户表已存在且与删除前备份不同；未覆盖任何现有账号')
                    report['mode'] = 'already_restored'
                else:
                    normalize = lambda sql: re.sub(r' AUTO_INCREMENT=\d+', '', sql)
                    if normalize(before[TARGET]['ddl']) != normalize(ddl):
                        raise RuntimeError('现有空用户表结构与备份不同，未修改')
            else:
                await cursor.execute(ddl)
            if report['mode'] != 'already_restored':
                columns = list(rows[0])
                statement = 'INSERT INTO `keenrobot_user` ('+','.join(f'`{column}`' for column in columns)+') VALUES ('+','.join(['%s']*len(columns))+')'
                await conn.begin()
                try:
                    await cursor.executemany(statement, [[row[column] for column in columns] for row in rows])
                    await cursor.execute('SELECT * FROM `keenrobot_user` ORDER BY id')
                    if not same_rows(list(await cursor.fetchall()), rows):
                        raise RuntimeError('恢复数据与原备份逐值不一致，已回滚插入')
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    raise
                report['mode'] = 'restored'
            after = await snapshot(cursor)
            checks = {name:{'ddl_unchanged':before[name]['ddl']==after[name]['ddl'],
                            'rows_unchanged':before[name]['hash']==after[name]['hash']}
                      for name in before if name != TARGET}
            report.update(restored_row_count=after[TARGET]['count'],
                existing_table_checks=checks,remaining_table_count=len(after),
                restored_data_matches_backup=after[TARGET]['hash']==digest(sorted(rows,key=lambda row:json.dumps(row,sort_keys=True,default=str))))
            if set(after) != set(before)|{TARGET} or not all(all(check.values()) for check in checks.values()):
                raise RuntimeError('恢复后检测到其它表外部变化；本脚本只写用户表，请查看私有检查记录')
            return report
    except BaseException as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        conn.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--apply',action='store_true')
    arguments=parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    result=asyncio.run(run(arguments.apply))
    print(json.dumps(result,ensure_ascii=False,indent=2))
