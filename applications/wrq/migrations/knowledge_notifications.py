"""Additive notification migration. Plan by default, --apply after reviewing its SQL."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from applications.wrq.migrations.review_20261024 import connect

TABLE = 'keenrobot_skill_knowledge_notifications'
CREATE = f'''CREATE TABLE IF NOT EXISTS `{TABLE}` (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 recipient_user_id BIGINT NOT NULL,
 skill_id INT NOT NULL,
 knowledge_base_id INT NOT NULL,
 latest_revision INT NOT NULL DEFAULT 0,
 read_revision INT NOT NULL DEFAULT 0,
 change_summary LONGTEXT NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 read_at DATETIME(6) NULL,
 UNIQUE KEY uq_skill_knowledge_recipient (recipient_user_id,skill_id,knowledge_base_id),
 KEY ix_notice_skill (skill_id), KEY ix_notice_knowledge (knowledge_base_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
BASELINE = '''UPDATE keenrobot_skill_resource_bindings b
 JOIN keenrobot_skills s ON s.id=b.skill_id AND s.current_version_id=b.skill_version_id
 JOIN keenrobot_knowledge_bases k ON k.id=b.source_id
 SET b.knowledge_mount_revision=k.revision
 WHERE b.source_type='knowledge_base' AND b.knowledge_mount_revision IS NULL AND s.state=0'''
INITIALIZE = f'''INSERT INTO {TABLE}
 (recipient_user_id,skill_id,knowledge_base_id,latest_revision,read_revision,change_summary,updated_at)
 SELECT DISTINCT u.id,s.id,k.id,k.revision,k.revision,'',UTC_TIMESTAMP(6)
 FROM keenrobot_skill_resource_bindings b
 JOIN keenrobot_skills s ON s.id=b.skill_id AND s.current_version_id=b.skill_version_id
 JOIN keenrobot_knowledge_bases k ON k.id=b.source_id
 JOIN keenrobot_user u ON u.username=s.create_user_login_name
 WHERE b.source_type='knowledge_base' AND s.state=0 AND k.state<>1 AND u.state<>1 AND u.is_active=1
 ON DUPLICATE KEY UPDATE id={TABLE}.id'''


async def run(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            if not (await cursor.fetchone())['Value']:
                raise RuntimeError('TLS is required')
            await cursor.execute('SHOW COLUMNS FROM keenrobot_skill_resource_bindings')
            columns = {row['Field'] for row in await cursor.fetchall()}
            statements = [] if 'knowledge_mount_revision' in columns else [
                'ALTER TABLE keenrobot_skill_resource_bindings ADD COLUMN knowledge_mount_revision INT NULL']
            await cursor.execute('SHOW INDEX FROM keenrobot_skill_resource_bindings')
            indexes = {}
            for row in await cursor.fetchall():
                indexes.setdefault(row['Key_name'], []).append((row['Seq_in_index'], row['Column_name']))
            if not any([column for _, column in sorted(parts)][:2] == ['source_type', 'source_id'] for parts in indexes.values()):
                statements.append('CREATE INDEX ix_binding_knowledge_lookup ON keenrobot_skill_resource_bindings (source_type,source_id)')
            statements += [CREATE, BASELINE, INITIALIZE]
            print(json.dumps({'apply': apply, 'statements': statements}, ensure_ascii=False))
            if not apply:
                return
            folder = Path(__file__).resolve().parents[4] / '.tmp' / 'knowledge-notification-migration'
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
            await cursor.execute('SHOW CREATE TABLE keenrobot_skill_resource_bindings')
            old_ddl = await cursor.fetchone()
            backup.write_text(json.dumps({'binding_ddl': old_ddl, 'sql': statements}, default=str, indent=2), encoding='utf-8')
            for statement in statements:
                await cursor.execute(statement)
            await cursor.execute(f'SELECT COUNT(*) AS total, COALESCE(SUM(latest_revision>read_revision),0) AS unread FROM {TABLE}')
            print(json.dumps({'verified': await cursor.fetchone(), 'backup': str(backup)}, default=str))
    finally:
        connection.close()


if __name__ == '__main__':
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
