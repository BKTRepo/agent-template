"""Additive deployment migration; prints a plan unless --apply is explicitly supplied.

No historical login/mount events are fabricated. Existing facts remain intact.
"""
import argparse
import asyncio
from applications.wrq.migrations.review_20261024 import connect

CREATE = '''CREATE TABLE IF NOT EXISTS keenrobot_overview_events (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 event_key VARCHAR(128) NOT NULL UNIQUE,
 kind VARCHAR(32) NOT NULL,
 occurred_at DATETIME(6) NOT NULL,
 operator_login_name VARCHAR(32) NOT NULL,
 data JSON NOT NULL,
 INDEX ix_overview_kind_time (kind,occurred_at), INDEX ix_overview_time (occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
ADDITIONS = {
 'chat_skill_calls': {'operator_login_name': 'VARCHAR(32) NULL', 'skill_name_snapshot': 'VARCHAR(128) NULL'},
 'chat_artifact_counts': {'generated_at': 'DATETIME(6) NULL', 'details': 'JSON NULL'},
 'keenrobot_online_debug_runs': {'owner_id': 'BIGINT NULL'},
}


async def migrate(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            statements = [CREATE]
            for table, fields in ADDITIONS.items():
                await cursor.execute(f'SHOW COLUMNS FROM `{table}`')
                columns = {row['Field'] for row in await cursor.fetchall()}
                statements.extend(f'ALTER TABLE `{table}` ADD COLUMN `{name}` {definition}'
                                  for name, definition in fields.items() if name not in columns)
            for table, index, field in [('chat_artifact_counts', 'ix_artifact_generated_at', 'generated_at'),
                                         ('keenrobot_online_debug_runs', 'ix_debug_owner', 'owner_id')]:
                await cursor.execute(f'SHOW INDEX FROM `{table}`')
                existing = {row['Key_name'] for row in await cursor.fetchall()}
                if index not in existing:
                    statements.append(f'ALTER TABLE `{table}` ADD INDEX `{index}` (`{field}`)')
            for statement in statements:
                print(statement + ';')
                if apply:
                    await cursor.execute(statement)
            if apply:
                await connection.commit()
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(migrate(parser.parse_args().apply))
