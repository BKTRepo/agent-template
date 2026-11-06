"""Remove global filename uniqueness; conversion jobs remain uniquely identified by job_id.

Plan by default; explicitly run with --apply before deploying the updated model.
Only single-column UNIQUE(filename) indexes are removed. No document data is changed.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from applications.wrq.migrations.review_20261024 import connect

TABLE = 'rag_document'


def global_filename_indexes(rows):
    indexes = {}
    for row in rows:
        indexes.setdefault(row['Key_name'], []).append(row)
    return [name for name, columns in indexes.items()
            if name != 'PRIMARY' and len(columns) == 1
            and columns[0]['Column_name'] == 'filename' and not columns[0]['Non_unique']]


async def run(apply=False):
    connection = await connect()
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            if not (await cursor.fetchone())['Value']:
                raise RuntimeError('Refusing migration without TLS')
            await cursor.execute(f'SHOW INDEX FROM `{TABLE}`')
            before = list(await cursor.fetchall())
            names = global_filename_indexes(before)
            statements = [f'ALTER TABLE `{TABLE}` DROP INDEX `{name.replace("`", "``")}`' for name in names]
            print({'apply': apply, 'table': TABLE, 'sql': statements})
            if not apply or not names:
                return
            await cursor.execute(f'SHOW CREATE TABLE `{TABLE}`')
            ddl = await cursor.fetchone()
            folder = Path(__file__).resolve().parents[4] / '.tmp' / 'rag-filename-migration'
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
            backup.write_text(json.dumps({'ddl': ddl, 'indexes': before, 'sql': statements},
                                         ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            for statement in statements:
                await cursor.execute(statement)
            await cursor.execute(f'SHOW INDEX FROM `{TABLE}`')
            after = list(await cursor.fetchall())
            if global_filename_indexes(after):
                raise RuntimeError('Global filename uniqueness is still present')
            preserved = [row for row in before if row['Key_name'] not in names]
            if preserved != after:
                # SHOW INDEX cardinality can change, so compare index definitions only.
                keys = ('Key_name', 'Column_name', 'Seq_in_index', 'Non_unique', 'Sub_part')
                definition = lambda rows: sorted(tuple(str(row.get(key)) for key in keys) for row in rows)
                if definition(preserved) != definition(after):
                    raise RuntimeError('Unexpected change to another index')
            print({'verified': True, 'removed_indexes': names, 'schema_backup': str(backup)})
    finally:
        connection.close()


if __name__ == '__main__':
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args().apply))
