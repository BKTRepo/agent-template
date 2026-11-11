"""悬浮对话台会话和评价接口。"""

import asyncio
import json
import shutil
import socket
from pydantic import ValidationError
from applications.chat.schemas.chat_schema import PageContext
from applications.chat.services.page_context import resolve_page_context, request_snapshots
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from starlette.responses import StreamingResponse
from tortoise import connections
from tortoise.transactions import in_transaction

from applications.chat.models.chat_model import (ChatArtifact, ChatArtifactCount, ChatConversation, ChatFeedback,
                                                ChatMessage, ChatSkillCall, ChatTask)
from applications.chat.schemas.chat_schema import (ConversationCreate, ConversationFavorite, ConversationId,
                                                   ArtifactInput, ConversationRename, ConversationResources, FeedbackInput, SendInput, TaskInput)
from applications.chat.services.chat_service import (clear_conversation, conversation_data,
                                                     require_conversation, validate_resources)
from applications.chat.services.attachments import save_uploads, task_upload_dir, remove_task_uploads
from applications.chat.services.history_files import history_store, schedule_history, sync_history, write_history_events
from applications.chat.services.execution import model_environment, start_task
from applications.chat.services.model_health import health, select_model
from services.model_gateway import configured_model_registry, model_ids
from applications.user.models.user_model import User
from core.responses import SuccessResponse
from services import DependAuth
from applications.conversation.services.artifact_source import artifact_reference

chat_router = APIRouter()


@chat_router.post("/conversation/create", summary="悬浮窗-创建会话")
async def create_conversation(body: ConversationCreate, user: User = DependAuth):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "会话名称不能为空")
    conversation = await ChatConversation.create(user_id=user.id, title=title)
    try:
        conversation.history_path = f'{user.id}/{conversation.id}.jsonl'
        await conversation.save(update_fields=['history_path'])
        await sync_history(user.id, conversation.id, create=True)
    except Exception:
        await conversation.delete()
        raise HTTPException(503, '创建会话文件失败，请检查存储目录') from None
    return SuccessResponse(data=await conversation_data(conversation))


@chat_router.get("/conversation/list", summary="悬浮窗-历史会话")
async def list_conversations(search: str = "", favorite: bool | None = None,
                             offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                             user: User = DependAuth):
    query = ChatConversation.filter(user_id=user.id, state=0)
    if favorite is not None:
        query = query.filter(favorite=favorite)
    if search.strip():
        term = search.strip().casefold()
        matches = []
        for item in await query.order_by('-updated_time', '-id'):
            await sync_history(user.id, item.id)
            contents = await asyncio.to_thread(history_store().message_contents, user.id, item.id, item.generation)
            visible_ids = set(await ChatMessage.filter(conversation_id=item.id, generation=item.generation).values_list('id', flat=True))
            if term in item.title.casefold() or any(term in text.casefold() for msg_id, text in contents.items() if msg_id in visible_ids):
                matches.append(item)
        return SuccessResponse(data=[await conversation_data(row) for row in matches[offset:offset + limit]], total=len(matches))
    total = await query.count()
    rows = await query.order_by("-updated_time", "-id").offset(offset).limit(limit)
    return SuccessResponse(data=[await conversation_data(row) for row in rows], total=total)


@chat_router.get("/conversation/detail", summary="悬浮窗-会话详情")
async def conversation_detail(conversation_id: str, user: User = DependAuth):
    return SuccessResponse(data=await conversation_data(await require_conversation(conversation_id, user.id)))


@chat_router.get("/message/list", summary="悬浮窗-历史消息")
async def list_messages(conversation_id: str, before_id: int | None = Query(None, gt=0),
                        limit: int = Query(30, ge=1, le=100), user: User = DependAuth):
    conversation = await require_conversation(conversation_id, user.id)
    if await sync_history(user.id, conversation.id):
        events = await asyncio.to_thread(history_store().read, user.id, conversation.id)
        rows = [event['data'] for event in events if event.get('type') == 'message']
        if before_id is not None:
            rows = [row for row in rows if row['id'] < before_id]
        visible = rows[-limit:]
        tasks = await ChatTask.filter(conversation_id=conversation.id, generation=conversation.generation,
            status="success", assistant_message_id__in=[row["id"] for row in visible])
        by_task = {task.id: task.assistant_message_id for task in tasks}
        artifacts = {}
        for item in await ChatArtifact.filter(task_id__in=list(by_task)).order_by("id"):
            artifacts.setdefault(by_task[item.task_id], []).append(artifact_reference(item))
        all_tasks = await ChatTask.filter(conversation_id=conversation.id, generation=conversation.generation).order_by('id')
        task_by_message = {}
        for task in all_tasks:
            task_by_message.setdefault(task.user_message_id, task)
            task_by_message[task.assistant_message_id] = task
        feedback = {item.message_id: item for item in await ChatFeedback.filter(user_id=user.id, message_id__in=[row['id'] for row in visible])}
        snapshots = request_snapshots(events, conversation.generation)
        data = []
        for row in visible:
            task = task_by_message.get(row['id'])
            vote = feedback.get(row['id'])
            snapshot = snapshots.get(task.id, {}) if task else {}
            data.append({**row, 'artifacts': artifacts.get(row['id'], []), 'task_id': task.id if task else None,
                'task_status': task.status if task else None, 'feedback': vote.rating if vote else None,
                'feedback_reason': vote.reason if vote else None, 'context': snapshot.get('context'),
                'attachments': snapshot.get('attachments', []) if row['role'] == 'user' else []})
        return SuccessResponse(data=data)
    raise HTTPException(503, '会话文件不存在，无法读取消息')


@chat_router.post("/conversation/rename", summary="悬浮窗-重命名会话")
async def rename_conversation(body: ConversationRename, user: User = DependAuth):
    row = await require_conversation(body.conversation_id, user.id)
    row.title = body.title.strip()
    if not row.title:
        raise HTTPException(400, "会话名称不能为空")
    await row.save(update_fields=["title", "updated_time"])
    schedule_history(user.id, row.id)
    return SuccessResponse(data=await conversation_data(row))


@chat_router.post("/conversation/favorite", summary="悬浮窗-收藏或取消收藏")
async def favorite_conversation(body: ConversationFavorite, user: User = DependAuth):
    row = await require_conversation(body.conversation_id, user.id)
    row.favorite = body.favorite
    await row.save(update_fields=["favorite", "updated_time"])
    schedule_history(user.id, row.id)
    return SuccessResponse(data=await conversation_data(row))


@chat_router.post("/conversation/resources", summary="悬浮窗-选择技能和知识库")
async def save_resources(body: ConversationResources, user: User = DependAuth):
    original = await require_conversation(body.conversation_id, user.id)
    if body.model and body.model not in model_ids():
        raise HTTPException(400, '不支持的模型')
    skills, knowledge = await validate_resources(user, body.skills, body.knowledge_bases)
    async with in_transaction() as conn:
        row = await require_conversation(body.conversation_id, user.id, connection=conn)
        if row.generation != original.generation:
            raise HTTPException(409, "会话已清空，请重新选择资源")
        row.skills, row.knowledge_bases, row.model = skills, knowledge, body.model
        await row.save(using_db=conn, update_fields=["skills", "knowledge_bases", "model", "updated_time"])
    schedule_history(user.id, row.id)
    return SuccessResponse(data=await conversation_data(row))


@chat_router.post("/conversation/read", summary="悬浮窗-标记消息已读")
async def read_conversation(body: ConversationId, user: User = DependAuth):
    row = await require_conversation(body.conversation_id, user.id)
    count = await ChatMessage.filter(conversation_id=row.id, generation=row.generation,
                                     role="assistant", unread=True).update(unread=False)
    schedule_history(user.id, row.id)
    return SuccessResponse(data={"read_count": count})


@chat_router.post("/conversation/clear", summary="悬浮窗-清空当前会话")
async def clear(body: ConversationId, user: User = DependAuth):
    row = await clear_conversation(body.conversation_id, user.id)
    await sync_history(user.id, row.id)
    return SuccessResponse(data=await conversation_data(row))


@chat_router.post("/conversation/delete", summary="悬浮窗-删除历史会话")
async def delete(body: ConversationId, user: User = DependAuth):
    await clear_conversation(body.conversation_id, user.id, delete=True)
    await sync_history(user.id, body.conversation_id)
    return SuccessResponse()


@chat_router.post("/conversation/delete-all", summary="悬浮窗-删除全部历史会话")
async def delete_all(user: User = DependAuth):
    ids = await ChatConversation.filter(user_id=user.id, state=0).values_list("id", flat=True)
    deleted = 0
    for conversation_id in ids:
        try:
            await clear_conversation(conversation_id, user.id, delete=True)
            await sync_history(user.id, conversation_id)
            deleted += 1
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    return SuccessResponse(data={"deleted_count": deleted})


@chat_router.post("/feedback", summary="悬浮窗-评价回复")
async def feedback(body: FeedbackInput, user: User = DependAuth):
    message = await ChatMessage.filter(id=body.message_id, role="assistant", conversation__user_id=user.id,
                                       conversation__state=0).select_related("conversation").first()
    if not message:
        raise HTTPException(404, "消息不存在或无权访问")
    async with in_transaction() as conn:
        conversation = await require_conversation(message.conversation_id, user.id, connection=conn)
        if message.generation != conversation.generation:
            raise HTTPException(404, "消息不存在或无权访问")
        row, _ = await ChatFeedback.update_or_create(message_id=message.id, user_id=user.id, using_db=conn,
            defaults={"rating": body.rating, "reason": body.reason if body.rating == "dislike" else None})
    schedule_history(user.id, message.conversation_id)
    return SuccessResponse(data={"id": row.id, "rating": row.rating, "reason": row.reason})


@chat_router.post('/artifact/count-retry', summary='悬浮窗-重试产物统计')
async def retry_artifact_count(body: ArtifactInput, user: User = DependAuth):
    item = await ChatArtifact.filter(id=body.artifact_id, task__status='success',
        task__conversation__user_id=user.id, task__conversation__state=0).select_related('task__conversation').first()
    if not item:
        raise HTTPException(404, '产物不存在或无权访问')
    async with in_transaction() as conn:
        conversation = await require_conversation(item.task.conversation_id, user.id, connection=conn)
        if item.task.generation != conversation.generation:
            raise HTTPException(404, '产物不存在或无权访问')
        changed = await ChatArtifact.filter(id=item.id, count_status__in=['failed', 'needs_review']).using_db(conn).update(
            count_status='pending', count_error=None, retry_count=0)
    if not changed:
        raise HTTPException(409, '该产物当前无需重试统计')
    return SuccessResponse(data={'artifact_id': item.id, 'count_status': 'pending'})


@chat_router.get('/models', summary='悬浮窗-模型列表')
async def models(user: User = DependAuth):
    return SuccessResponse(data=[{'name': row['id'], 'display_name': row['model_name']}
                                 for row in configured_model_registry()])


@chat_router.get('/models/health', summary='悬浮窗-模型健康检测',
    description='优先返回缓存。首次查询返回 checking；过期时返回上次结果并标记 stale，后台异步刷新。'
                'checked_at 为 UTC 检测时间，refreshing 表示需要稍后重新查询。')
async def model_health(user: User = DependAuth):
    return SuccessResponse(data=await health())


@chat_router.get('/statistics', summary='悬浮窗-技能调用和产物统计')
async def statistics(skill_id: int | None = Query(None, gt=0), user: User = DependAuth):
    calls = ChatSkillCall.all()
    if skill_id is not None:
        calls = calls.filter(skill_id=skill_id)
    totals = await connections.get('default').execute_query_dict(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM chat_artifact_counts WHERE status = 'counted'")
    return SuccessResponse(data={'skill_id': skill_id, 'skill_call_count': await calls.count(),
        'artifact_count': int(totals[0]['total']),
        'artifact_count_failed': await ChatArtifactCount.filter(status='failed').count()})


@chat_router.get('/statistics/count-failures', summary='悬浮窗-产物埋点失败原因')
async def count_failures(limit: int = Query(50, ge=1, le=100), user: User = DependAuth):
    if not user.is_superuser:
        raise HTTPException(403, '无权查看统计失败记录')
    pending = await ChatArtifact.filter(count_status__in=['failed', 'needs_review']).order_by('-id').limit(limit)
    archived = await ChatArtifactCount.filter(status='failed').order_by('-id').limit(limit)
    return SuccessResponse(data={
        'pending': [{'artifact_id': item.id, 'file_name': item.file_name, 'status': item.count_status,
                     'error': item.count_error, 'retry_count': item.retry_count} for item in pending],
        'cleaned': [{'artifact_id': item.artifact_id, 'error': item.error} for item in archived],
    })


@chat_router.post('/send', summary='悬浮窗-发送消息')
async def send(body: SendInput, user: User = DependAuth):
    return await submit_message(body.conversation_id, body.content, body.model, user, context=body.context, source_task_id=body.source_task_id)


@chat_router.post('/send-with-files', summary='悬浮窗-发送消息和临时附件')
async def send_with_files(conversation_id: str = Form(..., min_length=1, max_length=64),
                          content: str = Form('', max_length=40000),
                          model: str | None = Form(None, max_length=128),
                          files: list[UploadFile] = File(...), context: str | None = Form(None), source_task_id: int | None = Form(None, gt=0), user: User = DependAuth):
    original = await require_conversation(conversation_id, user.id)
    try:
        parsed_context = PageContext.model_validate_json(context) if context else None
    except ValidationError:
        raise HTTPException(422, '页面上下文格式不正确') from None
    directory = await save_uploads(files)
    return await submit_message(conversation_id, content, model, user, directory, original.generation,
                                context=parsed_context, source_task_id=source_task_id)


async def submit_message(conversation_id, content, selected_model, user, directory=None, expected_generation=None, *, context=None, source_task_id=None):
    content = content.strip()
    if not content and not directory:
        raise HTTPException(400, '消息和附件不能同时为空')
    adopted = None
    try:
        page_context = await resolve_page_context(context, user)
        source_snapshot = None
        if source_task_id:
            source = await require_task(source_task_id, user)
            source_events = await asyncio.to_thread(history_store().read, user.id, source.conversation_id)
            source_snapshot = request_snapshots(source_events, source.generation).get(source.id)
            if not source_snapshot:
                raise HTTPException(409, '原请求缺少上下文快照，请重新选择资源发送')
            page_context = source_snapshot.get('context')
            if page_context:
                await resolve_page_context(PageContext.model_validate(page_context), user)
        async with in_transaction() as conn:
            conversation = await require_conversation(conversation_id, user.id, connection=conn)
            if expected_generation is not None and conversation.generation != expected_generation:
                raise HTTPException(409, '会话已清空，请重新上传附件')
            if await ChatTask.filter(conversation_id=conversation.id, generation=conversation.generation,
                                     status__in=['pending', 'running', 'cancelling', 'recovering']).using_db(conn).exists():
                raise HTTPException(409, '当前会话有正在运行的任务')
            try:
                model = selected_model or conversation.model or await select_model()
            except RuntimeError as exc:
                raise HTTPException(400, str(exc)) from exc
            if model is None:
                raise HTTPException(503, '当前没有可用的健康模型，请稍后重试或手动选择')
            if model not in model_ids():
                raise HTTPException(400, '不支持的模型')
            try:
                model_environment(model)
            except RuntimeError as exc:
                raise HTTPException(400, str(exc)) from exc
            message = await ChatMessage.create(conversation_id=conversation.id, generation=conversation.generation,
                                               role='user', using_db=conn)
            assistant = await ChatMessage.create(conversation_id=conversation.id, generation=conversation.generation,
                                                 role='assistant', using_db=conn)
            await write_history_events(user.id, conversation.id, [
                {'type': 'message_content', 'generation': conversation.generation, 'message_id': message.id, 'content': content},
                {'type': 'message_content', 'generation': conversation.generation, 'message_id': assistant.id, 'content': ''},
            ])
            task = await ChatTask.create(conversation_id=conversation.id, generation=conversation.generation,
                                         user_message_id=message.id, assistant_message_id=assistant.id,
                                         model=model, worker_host=socket.gethostname() if directory else None, using_db=conn)
            snapshot = source_snapshot or {'context': page_context, 'skills': list(conversation.skills or []),
                                            'knowledge_bases': list(conversation.knowledge_bases or [])}
            snapshot = {**snapshot, 'attachments': [file.name for file in directory.glob('*/*')] if directory else []}
            from applications.wrq.models.overview_event_model import OverviewEvent
            await OverviewEvent.get_or_create(event_key=f'chat:{task.id}', using_db=conn, defaults={'kind': 'chat_request', 'occurred_at': datetime.now(), 'operator_login_name': user.username, 'data': {'task_id': task.id, 'user_id': user.id, 'username': user.alias or user.username}})
            await write_history_events(user.id, conversation.id, [{'type': 'request_snapshot',
                'generation': conversation.generation, 'task_id': task.id, 'data': snapshot}])
            if directory:
                target = task_upload_dir(task.id)
                if target.exists():
                    raise RuntimeError('附件临时目录冲突')
                directory.rename(target)
                adopted = target
            await conversation.save(using_db=conn, update_fields=['updated_time'])
    except BaseException:
        if adopted and adopted.exists():
            shutil.rmtree(adopted, ignore_errors=True)
        raise
    finally:
        if directory and directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
    start_task(task.id)
    schedule_history(user.id, conversation.id)
    return SuccessResponse(data={'task_id': task.id, 'message_id': assistant.id, 'status': task.status})


async def require_task(task_id, user):
    task = await ChatTask.filter(id=task_id, conversation__user_id=user.id,
                                 conversation__state=0).select_related('conversation').first()
    if not task or task.generation != task.conversation.generation:
        raise HTTPException(404, '任务不存在或无权访问')
    return task


async def task_data(task, contents=None):
    message = await ChatMessage.get_or_none(id=task.assistant_message_id)
    conversation = await ChatConversation.get(id=task.conversation_id)
    if contents is None:
        contents = await asyncio.to_thread(history_store().message_contents, conversation.user_id, conversation.id, task.generation)
    duration = None
    if task.started_at and task.finished_at:
        duration = max(0, round((task.finished_at - task.started_at).total_seconds() * 1000))
    return {'task_id': task.id, 'status': task.status, 'message_id': task.assistant_message_id,
            'content': contents.get(message.id, '') if message else '', 'model': task.model,
            'error': task.error, 'duration_ms': duration,
            'artifacts': [artifact_reference(item) for item in
                await ChatArtifact.filter(task_id=task.id).order_by('id')] if task.status == 'success' else []}


@chat_router.get('/task', summary='悬浮窗-任务状态')
async def task_status(task_id: int = Query(gt=0), user: User = DependAuth):
    return SuccessResponse(data=await task_data(await require_task(task_id, user)))


@chat_router.get('/events', summary='悬浮窗-流式对话')
async def events(task_id: int = Query(gt=0), user: User = DependAuth):
    await require_task(task_id, user)
    async def stream():
        previous = None
        while True:
            try:
                task = await require_task(task_id, user)
            except HTTPException:
                yield 'event: closed\ndata: {}\n\n'
                return
            data = await task_data(task)
            payload = json.dumps(data, ensure_ascii=False)
            if payload != previous:
                yield f'data: {payload}\n\n'
                previous = payload
            if task.status in ('success', 'failed', 'cancelled'):
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@chat_router.post('/stop', summary='悬浮窗-停止生成')
async def stop(body: TaskInput, user: User = DependAuth):
    task = await require_task(body.task_id, user)
    cancelled = await ChatTask.filter(id=task.id, status='pending').update(status='cancelled', finished_at=datetime.now())
    if cancelled and task.worker_host == socket.gethostname():
        try:
            await asyncio.to_thread(remove_task_uploads, task.id)
        except OSError:
            pass  # 后台清理会重试
    await ChatTask.filter(id=task.id, status='running').update(status='cancelling')
    return SuccessResponse(data=await task_data(await require_task(task.id, user)))


@chat_router.post('/retry', summary='悬浮窗-重试最新回复')
async def retry(body: TaskInput, user: User = DependAuth):
    old = await require_task(body.task_id, user)
    return await retry_task(old, user)


@chat_router.post('/retry-with-files', summary='悬浮窗-重新上传附件并重试')
async def retry_with_files(task_id: int = Form(..., gt=0), files: list[UploadFile] = File(...), user: User = DependAuth):
    old = await require_task(task_id, user)
    directory = await save_uploads(files)
    return await retry_task(old, user, directory)


async def retry_task(old, user, directory=None):
    adopted = None
    try:
        async with in_transaction() as conn:
            conversation = await require_conversation(old.conversation_id, user.id, connection=conn)
            latest = await ChatTask.filter(conversation_id=conversation.id, generation=conversation.generation).using_db(conn).order_by('-id').first()
            if old.status not in ('success', 'failed', 'cancelled') or (latest and latest.status in ('pending', 'running', 'cancelling', 'recovering')):
                raise HTTPException(409, '请等待当前会话任务结束后再重试')
            original_message = await ChatMessage.filter(id=old.user_message_id).using_db(conn).first()
            contents = await asyncio.to_thread(history_store().message_contents, user.id, conversation.id, conversation.generation)
            if not directory and (not original_message or not contents.get(original_message.id, '').strip()):
                raise HTTPException(400, '原消息没有文本，请重新上传附件重试')
            # Preserve the original request and response for history/traceability.
            assistant = await ChatMessage.create(conversation_id=conversation.id, generation=conversation.generation,
                                                 role='assistant', using_db=conn)
            await write_history_events(user.id, conversation.id, [
                {'type': 'message_content', 'generation': conversation.generation, 'message_id': assistant.id, 'content': ''}])
            task = await ChatTask.create(conversation_id=conversation.id, generation=conversation.generation,
                user_message_id=old.user_message_id, assistant_message_id=assistant.id,
                retry_of_task_id=old.id, model=old.model,
                worker_host=socket.gethostname() if directory else None, using_db=conn)
            events = await asyncio.to_thread(history_store().read, user.id, conversation.id)
            snapshot = request_snapshots(events, conversation.generation).get(old.id,
                {'context': None, 'skills': list(conversation.skills or []), 'knowledge_bases': list(conversation.knowledge_bases or [])})
            snapshot = {**snapshot, 'attachments': [file.name for file in directory.glob('*/*')] if directory else []}
            from applications.wrq.models.overview_event_model import OverviewEvent
            await OverviewEvent.get_or_create(event_key=f'chat:{task.id}', using_db=conn, defaults={'kind': 'chat_request', 'occurred_at': datetime.now(), 'operator_login_name': user.username, 'data': {'task_id': task.id, 'user_id': user.id, 'username': user.alias or user.username}})
            await write_history_events(user.id, conversation.id, [{'type': 'request_snapshot',
                'generation': conversation.generation, 'task_id': task.id, 'data': snapshot}])
            if directory:
                target = task_upload_dir(task.id)
                if target.exists():
                    raise RuntimeError('附件临时目录冲突')
                directory.rename(target)
                adopted = target
    except BaseException:
        if adopted and adopted.exists():
            shutil.rmtree(adopted, ignore_errors=True)
        raise
    finally:
        if directory and directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
    start_task(task.id)
    schedule_history(user.id, conversation.id)
    return SuccessResponse(data={'task_id': task.id, 'message_id': assistant.id, 'status': task.status,
                                 'attachments_supplied': bool(directory)})


@chat_router.get('/tasks', summary='悬浮窗-当前用户的后台任务及最近结果')
async def list_tasks(user: User = DependAuth):
    from tortoise.expressions import F
    rows = await ChatTask.filter(conversation__user_id=user.id, conversation__state=0,
        generation=F('conversation__generation')).order_by('-id').limit(100)
    data, contents_by_conversation = [], {}
    for row in rows:
        key = (row.conversation_id, row.generation)
        if key not in contents_by_conversation:
            try:
                contents_by_conversation[key] = await asyncio.to_thread(history_store().message_contents, user.id, row.conversation_id, row.generation)
            except (OSError, ValueError):
                contents_by_conversation[key] = {}
        item = await task_data(row, contents_by_conversation[key])
        data.append({**item, 'conversation_id': row.conversation_id})
    return SuccessResponse(data=data)
