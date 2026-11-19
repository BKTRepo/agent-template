"""Skill import migration. Print pending SQL by default, apply explicitly with --apply."""
import argparse
import asyncio
import sys
from applications.wrq.migrations.review_20261024 import connect

CREATE = [
"""CREATE TABLE IF NOT EXISTS keenrobot_skill_import_batches (
 id VARCHAR(32) PRIMARY KEY, owner_login VARCHAR(10) NOT NULL, upload_mode VARCHAR(16) NOT NULL,
 expires_at DATETIME(6) NOT NULL, created_time DATETIME(6) NOT NULL,
 INDEX ix_import_owner(owner_login), INDEX ix_import_expiry(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS keenrobot_skill_import_items (
 id VARCHAR(32) PRIMARY KEY, batch_id VARCHAR(32) NOT NULL, root_path VARCHAR(255) NOT NULL,
 default_name VARCHAR(128) NOT NULL, payload JSON NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'READY',
 errors JSON NOT NULL, selection JSON NOT NULL, skill_id INT NULL, created_time DATETIME(6) NOT NULL,
 INDEX ix_import_batch(batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


async def migrate(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            statements = list(CREATE)
            additions = {
                'keenrobot_skill_forms': {'definition_origin': "VARCHAR(16) NOT NULL DEFAULT 'platform'"},
                'keenrobot_skill_resource_bindings': {'relative_path': 'VARCHAR(255) NULL', 'resource_key': 'VARCHAR(64) NULL'},
            }
            for table, fields in additions.items():
                await cursor.execute(f'SHOW COLUMNS FROM `{table}`')
                columns = {row['Field'] for row in await cursor.fetchall()}
                statements.extend(f'ALTER TABLE `{table}` ADD COLUMN `{field}` {sql}' for field,sql in fields.items() if field not in columns)
            # Replace old uniqueness only after its replacement has been created.
            for table, new_name, wanted, obsolete in [
                ('keenrobot_skill_resource_bindings', 'uq_binding_resource_key', ['skill_version_id','resource_key'],
                 [['skill_version_id','source_type','source_id'], ['skill_version_id','file_id']]),
                ('keenrobot_skill_uploaded_files', 'uq_source_owner_category_hash', ['create_user_login_name','category_id','sha256'],
                 [['category_id','sha256']]),
            ]:
                await cursor.execute(f'SHOW INDEX FROM `{table}`')
                grouped = {}
                for row in await cursor.fetchall():
                    if row['Non_unique'] == 0:
                        grouped.setdefault(row['Key_name'], []).append((row['Seq_in_index'],row['Column_name']))
                fields_by_index = {key:[field for _,field in sorted(parts)] for key,parts in grouped.items()}
                if table == 'keenrobot_skill_resource_bindings':
                    statements.append("""UPDATE keenrobot_skill_resource_bindings SET resource_key=SHA2(
                      CASE WHEN file_id IS NOT NULL THEN CONCAT('file:',file_id)
                      ELSE CONCAT(source_type,':',source_id) END,256) WHERE resource_key IS NULL""")
                if wanted not in fields_by_index.values():
                    columns = ','.join(f'`{field}`' for field in wanted)
                    statements.append(f'CREATE UNIQUE INDEX `{new_name}` ON `{table}` ({columns})')
                for key, fields in fields_by_index.items():
                    if fields in obsolete:
                        statements.append(f'ALTER TABLE `{table}` DROP INDEX `{key}`')
            statements.append("""INSERT INTO keenrobot_resource_categories (code,name,is_enabled)
                VALUES ('custom','自定义资源',1) ON DUPLICATE KEY UPDATE name=VALUES(name),is_enabled=1""")
            for sql in statements:
                print(sql + ';')
                if apply:
                    await cursor.execute(sql)
            if apply:
                await connection.commit()
    finally:
        connection.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(migrate(parser.parse_args().apply))
