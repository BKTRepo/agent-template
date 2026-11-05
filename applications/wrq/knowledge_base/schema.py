"""Explicit query schema plan/apply. Does not generate ingestion schemas."""
import argparse
import asyncio
from tortoise import Tortoise, connections
from configure import PROJECT_CONFIG
from applications.wrq.database import wrq_connections

async def main(apply=False):
    await Tortoise.init(config={'connections': wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps': {'models': {'models': PROJECT_CONFIG.APPLICATIONS_MODELS, 'default_connection': 'default'}}})
    try:
        from .models.query_model import KnowledgeQueryTurn, KnowledgeConversationMemory
        from .models.term_mapping_model import RagTermMappingSource, RagTermMappingLearned
        from .models.feedback_model import RagAnswerFeedback
        db = connections.get('default')
        generator = db.schema_generator(db)
        for model in [KnowledgeQueryTurn, KnowledgeConversationMemory, RagTermMappingSource, RagTermMappingLearned, RagAnswerFeedback]:
            sql = generator._get_table_sql(model, safe=True)['table_creation_string']
            print(sql)
            if apply:
                await db.execute_script(sql)
                await model.all().limit(1).values()
                print('VERIFIED ' + model._meta.db_table)
    finally:
        await Tortoise.close_connections()

if __name__ == '__main__':
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(main(parser.parse_args().apply))
