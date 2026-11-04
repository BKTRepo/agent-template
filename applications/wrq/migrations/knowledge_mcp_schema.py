"""仅创建 MCP 上下文及审计两张表；默认输出计划，--apply 执行。"""
import argparse
import asyncio
from tortoise import Tortoise, connections
from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG

async def main(apply=False):
    await Tortoise.init(config={'connections':wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps':{'models':{'models':PROJECT_CONFIG.APPLICATIONS_MODELS,'default_connection':'default'}},
        'use_tz':False,'timezone':'Asia/Shanghai'})
    try:
        from applications.wrq.models.knowledge_execution_model import KnowledgeExecution, KnowledgeToolCall
        db=connections.get('default')
        generator=db.schema_generator(db)
        for model in (KnowledgeExecution, KnowledgeToolCall):
            sql=generator._get_table_sql(model,safe=True)['table_creation_string']
            print(sql)
            if apply:
                await db.execute_script(sql)
        if db.capabilities.dialect == 'mysql':
            rows = await db.execute_query_dict("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='keenrobot_knowledge_tool_calls'")
            names = {row['COLUMN_NAME'] for row in rows}
            for name, definition in [('duration_ms','INT NOT NULL DEFAULT 0'),('tool_call_id','VARCHAR(128) NULL'),('delivered_at','DATETIME(6) NULL')]:
                if rows and name not in names:
                    sql = f'ALTER TABLE keenrobot_knowledge_tool_calls ADD COLUMN {name} {definition}'
                    print(sql)
                    if apply:
                        await db.execute_script(sql)
    finally:
        await Tortoise.close_connections()

if __name__=='__main__':
    import sys
    if sys.platform=='win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    asyncio.run(main(parser.parse_args().apply))
