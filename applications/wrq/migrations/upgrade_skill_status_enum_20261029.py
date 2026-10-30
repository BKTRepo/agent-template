"""将技能状态字段扩展为六态 MySQL ENUM。

默认只检查当前列定义；传入 --apply 后才执行 DDL。DDL 自动提交，执行前会在
.tmp/wrq-status-enum-backups 保存当前 SHOW CREATE TABLE 结果，便于审计与回退。
"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sys

from applications.wrq.migrations.review_20261024 import connect


TARGET = "ENUM('DRAFT','DEBUGGING','DEBUG_SUCCESS','DEBUG_FAILED','ONLINE','OFFLINE')"
ROOT = Path(__file__).resolve().parents[4]
BACKUP_ROOT = ROOT / '.tmp' / 'wrq-status-enum-backups'


async def run(apply: bool) -> None:
    conn = await connect()
    try:
        async with conn.cursor() as cur:
            await cur.execute("SHOW CREATE TABLE `keenrobot_skills`")
            ddl = (await cur.fetchone())['Create Table']
            current = 'DEBUG_SUCCESS' in ddl and 'DEBUG_FAILED' in ddl
            print({'current_is_six_state_enum': current, 'apply': apply})
            if not apply or current:
                return
            BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
            backup = BACKUP_ROOT / f"{datetime.now().strftime('%Y%m%dT%H%M%S%f')}-keenrobot_skills.sql"
            backup.write_text(ddl, encoding='utf8')
            await cur.execute(
                "ALTER TABLE `keenrobot_skills` MODIFY `display_status` "
                f"{TARGET} NOT NULL DEFAULT 'DRAFT' "
                "COMMENT '草稿 调试中 调试成功 调试失败 已上线 已下线'"
            )
            print({'updated': True, 'backup': str(backup)})
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply))
