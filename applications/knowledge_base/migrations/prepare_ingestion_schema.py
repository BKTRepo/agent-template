"""Create only the four migrated ingestion tables. Default: print a plan; --apply executes it."""
import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from tortoise import Tortoise, connections
from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG

async def main(apply=False):
    await Tortoise.init(config={
        'connections':wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps':{'models':{'models':PROJECT_CONFIG.APPLICATIONS_MODELS,'default_connection':'default'}},
        'use_tz':False,'timezone':'Asia/Shanghai'})
    try:
        from applications.knowledge_base.models.rag_document_model import RagDocument
        from applications.knowledge_base.models.pipeline_model import RagPipelineState,RagPipelineHistory
        from applications.knowledge_base.models.llm_call_log_model import LLMCallLog
        connection=connections.get('default')
        generator=connection.schema_generator(connection)
        for model in [RagDocument,RagPipelineState,RagPipelineHistory,LLMCallLog]:
            if model._meta.db_table not in {'rag_document','rag_pipeline_state','rag_pipeline_history','llm_call_log'}:
                raise RuntimeError('Unexpected migration table')
            ddl=generator._get_table_sql(model,safe=True)['table_creation_string']
            print(ddl)
            if apply:
                await connection.execute_script(ddl)
        # Existing source-era tables need the ownership/binding columns added explicitly.
        if connection.capabilities.dialect=='mysql':
            _,rows=await connection.execute_query("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rag_document'")
            names={row['COLUMN_NAME'] for row in rows}
            for name,definition in [('owner_id','BIGINT NULL'),('knowledge_document_id','VARCHAR(64) NULL')]:
                if names and name not in names:
                    ddl=f'ALTER TABLE `rag_document` ADD COLUMN `{name}` {definition};'
                    print(ddl)
                    if apply:
                        await connection.execute_script(ddl)
    finally:
        await Tortoise.close_connections()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    asyncio.run(main(parser.parse_args().apply))
