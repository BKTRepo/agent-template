"""Platform adapter to the migrated query engine, with durable stream replay."""
import asyncio
import json
from applications.wrq.knowledge import document_scope
from applications.wrq.knowledge_base.config import PROJECT_CONFIG
from applications.wrq.knowledge_base.models.query_model import KnowledgeQueryTurn, KnowledgeConversationMemory
from applications.wrq.knowledge_base.rag.query import QueryParam, run_query, _partial_answer_with_notice
from applications.wrq.knowledge_base.rag.scope import query_scope
from applications.wrq.knowledge_base.rag.scope import model_connection
from applications.wrq.knowledge_base.rag.memory import compute_window_and_overflow, llm_fold_summary, recall_turn_memory, upsert_turn_memory
from applications.model_config.services.llm_connection import resolve_chat_llm_params
from applications.conversation.models.conversation_model import Conversation

_tasks = set()

async def _publish(turn, event, payload):
    turn.events = [*turn.events, {'event': event, 'data': payload}]
    await turn.save(update_fields=['events', 'answer', 'retrieval', 'status', 'error', 'updated_at'])

async def start_query(req, user, crud):
    conv, model, history, kb_ids = await crud.prepare_for_chat(req, user)
    scope = await document_scope(user.id, kb_ids) if kb_ids else []
    turn = await KnowledgeQueryTurn.create(owner_id=user.id, conversation_id=conv.id, question=req.question)
    task = asyncio.create_task(_execute(turn, req, crud, model, history, scope))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return turn

async def _execute(turn, req, crud, model, history, scope):
    connection_token = model_connection.set(resolve_chat_llm_params(model))
    try:
        await _publish(turn, 'meta', dict(type='meta', conversation_id=turn.conversation_id, run_id=turn.id))
        memory, _ = await KnowledgeConversationMemory.get_or_create(conversation_id=turn.conversation_id)
        window, overflow, boundary = compute_window_and_overflow(history, memory.up_to_seq,
            max_tokens=PROJECT_CONFIG.CHAT_HISTORY_MAX_TOKENS, max_messages=PROJECT_CONFIG.CHAT_HISTORY_MAX_MESSAGES)
        if len(overflow) >= PROJECT_CONFIG.CHAT_SUMMARY_BATCH_MESSAGES:
            folded = await llm_fold_summary(memory.summary, overflow, PROJECT_CONFIG.CHAT_SUMMARY_MAX_TOKENS)
            if folded is not None:
                memory.summary, memory.up_to_seq = folded, boundary
                await memory.save()
        recall = await recall_turn_memory(turn.conversation_id, req.question, boundary)
        llm = resolve_chat_llm_params(model)
        param = QueryParam(mode=req.query_mode if scope else 'bypass', stream=True,
            conversation_history=window, conversation_summary=memory.summary, conversation_recall=recall,
            enable_rerank=req.enable_rerank, model=llm.get('model_name'), temperature=llm.get('temperature'),
            max_total_tokens=req.max_total_tokens or PROJECT_CONFIG.MAX_TOTAL_TOKENS)
        with query_scope(j for d in scope for j in d['jobs']):
            result = await run_query(req.question, param)
        turn.retrieval = result.raw_data or {}
        await _publish(turn, 'retrieval', dict(type='retrieval', **turn.retrieval))
        await _publish(turn, 'references', dict(type='references', references=turn.retrieval.get('data', {}).get('references', [])))
        if result.is_streaming and result.response_iterator:
            async for chunk in result.response_iterator:
                turn.answer += chunk
                await _publish(turn, 'token', dict(type='token', content=chunk))
            truncated = getattr(result.response_iterator, 'finish_reason', None) == 'length'
        else:
            turn.answer = result.content or ''
            truncated = False
            await _publish(turn, 'token', dict(type='token', content=turn.answer))
        if truncated:
            notice = _partial_answer_with_notice('')
            turn.answer += notice
            await _publish(turn, 'token', dict(type='token', content=notice))
        # Respect conversation deletion and never silently recreate it.
        if await Conversation.filter(id=turn.conversation_id, user_id=turn.owner_id).exists():
            await crud.save_assistant_message(turn.conversation_id, turn.answer,
                process_trace=[dict(type='knowledge_retrieval', run_id=turn.id)])
        turn.status = 'truncated' if truncated else 'completed'
        await _publish(turn, 'done', dict(type='done', content=turn.answer, run_id=turn.id, status=turn.status))
        await upsert_turn_memory(turn.conversation_id, len(history)+1, req.question, turn.answer)
    except Exception as exc:
        from configure import LOGGER
        LOGGER.opt(exception=True).error('Knowledge query failed')
        turn.status, turn.error = 'failed', type(exc).__name__
        await _publish(turn, 'error', dict(type='error', message='知识库问答失败，请查看后端记录', run_id=turn.id))
    finally:
        model_connection.reset(connection_token)

async def replay(turn_id, owner_id, after=0):
    """Replay persisted events; disconnecting a subscriber never cancels execution."""
    cursor = after
    while True:
        turn = await KnowledgeQueryTurn.get_or_none(id=turn_id, owner_id=owner_id)
        if turn is None:
            return
        for entry in turn.events[cursor:]:
            cursor += 1
            yield dict(id=str(cursor), event=entry['event'], data=json.dumps(entry['data'], ensure_ascii=False))
        if turn.status != 'running':
            return
        await asyncio.sleep(.25)
