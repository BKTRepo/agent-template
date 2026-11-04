"""离线生成整数编号知识库/RAG建表方案；没有执行DDL的选项。"""
import argparse
import asyncio
from pathlib import Path
from tortoise import Tortoise, connections


async def plan():
    # 仅初始化模型元数据。端口为不可用占位值，从不连接或执行SQL。
    await Tortoise.init(config={
        'connections': {'default': {'engine': 'tortoise.backends.mysql', 'credentials': {
            'host': '127.0.0.1', 'port': 1, 'user': 'plan_only', 'password': 'unused', 'database': 'plan_only'}}},
        'apps': {'models': {'models': ['applications.user.models.user_model',
            'applications.knowledge_base.models.knowledge_base_model',
            'applications.knowledge_base.models.rag_document_model',
            'applications.knowledge_base.models.pipeline_model',
            'applications.knowledge_base.models.llm_call_log_model'], 'default_connection': 'default'}},
        'use_tz': False, 'timezone': 'Asia/Shanghai'})
    try:
        from applications.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document, DocumentChunk
        from applications.knowledge_base.models.rag_document_model import RagDocument
        from applications.knowledge_base.models.pipeline_model import RagPipelineState, RagPipelineHistory
        from applications.knowledge_base.models.llm_call_log_model import LLMCallLog
        db = connections.get('default')
        generator = db.schema_generator(db)
        statements = ['-- REFERENCE SCHEMA: 2026-11-04. Generator does not execute SQL.',
                      '-- Existing empty target tables were aligned using align_empty_integer_ids_20261104, not by executing this CREATE script.',
                      '-- For populated legacy tables, an explicit identifier mapping is required; CREATE IF NOT EXISTS does not convert existing columns.',
                      '-- Knowledge/document/chunk IDs and rag_document.knowledge_document_id are INT.',
                      '-- Existing keenrobot_skill_resource_bindings.source_id is INT; no changes to existing skill identifiers.',
                      '-- Review storage/charset and existing user-table constraints before applying.']
        for model in (KnowledgeBase, Document, DocumentChunk, RagDocument, RagPipelineState, RagPipelineHistory, LLMCallLog):
            statements.append(generator._get_table_sql(model, safe=True)['table_creation_string'])
        return '\n\n'.join(statements) + '\n'
    finally:
        await Tortoise.close_connections()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    sql = asyncio.run(plan())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(sql, encoding='utf-8')
        print(f'Plan written: {args.output}')
    else:
        print(sql)
