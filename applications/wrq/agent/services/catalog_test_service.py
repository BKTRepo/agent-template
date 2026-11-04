"""目录调用适配器：固定发布快照，任务/关联/计数原子落库后复用同事的沙箱执行器。"""
import asyncio
import io
from pathlib import Path
import zipfile

from tortoise.transactions import in_transaction
from tortoise.expressions import F
from tortoise.exceptions import IntegrityError

from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillDebugRun, DeveloperSkillClass
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_catalog_service import SkillCatalogService
from applications.wrq.auth import user_login_name
from applications.zhaoyunlong.models.online_debug_run_model import OnlineDebugRun
from applications.zhaoyunlong.services.online_debug_run_service import OnlineDebugRunService
from applications.zhaoyunlong.services.online_debug_file_parser import extract_uploaded_file, extract_mounted_resource, FileParseError


async def existing_run(data, user, db=None):
    links = SkillDebugRun.filter(run_id=data.request_id)
    if db:
        links = links.using_db(db)
    link = await links.first()
    if not link:
        return None
    if (link.skill_id != data.skill_id or link.build_id != data.build_id or
            link.create_user_login_name != user_login_name(user)):
        raise DeveloperError('调用编号已被使用，请重新提交', 409)
    query = OnlineDebugRun.filter(run_id=data.request_id)
    if db:
        query = query.using_db(db)
    task = await query.first()
    if not task:
        raise DeveloperError('任务关联不完整，请联系维护人', 409)
    return task


async def create_catalog_test(data, documents, user):
    previous = await existing_run(data, user)
    if previous:
        return await OnlineDebugRunService.as_response(previous)
    if len(documents) > 10 or not (data.conversation_input.strip() or documents):
        raise DeveloperError('请提供对话或需求文档，最多10份文档', 422)
    catalog = SkillCatalogService()
    packages, built, version = await catalog.package(data.skill_id, data.build_id, online=True)
    _, _, form = await catalog.published(data.skill_id, online=True)
    try:
        document_entries = [await asyncio.to_thread(extract_uploaded_file, file.filename or '', await file.read()) for file in documents]
        entries = [row for row in built['files'] if row['path'] not in ('SKILL.md', 'manifest.json')]
        if len(entries) > 20:
            raise DeveloperError('在线测试最多20个挂载资源', 422)
        # 不相信浏览器传来的定义和资源；从刚校验完整性的固定发布ZIP读取。
        archive = await asyncio.to_thread(packages._published_archive, built, version.version)
        with zipfile.ZipFile(io.BytesIO(archive[0])) as package:
            markdown = package.read(f"{built['name']}/SKILL.md").decode('utf-8')
            resources, names = [], set()
            for entry in entries:
                name = Path(entry['path']).name
                key = name.casefold()
                if key in names:
                    raise DeveloperError('挂载资源存在同名文件，当前沙箱不支持目录传参', 422)
                names.add(key)
                content = package.read(f"{built['name']}/{entry['path']}")
                resources.append(await asyncio.to_thread(extract_mounted_resource, name, content))
    except FileParseError as exc:
        raise DeveloperError(str(exc), 422) from exc
    payload = {'skill_id': str(data.skill_id), 'skill_definition': markdown,
               'conversation_input': data.conversation_input, 'documents': document_entries, 'mounted_resources': resources}
    if len(markdown) > 100000:
        raise DeveloperError('发布定义超过沙箱长度限制', 422)
    try:
        async with in_transaction() as db:
            skill = await Skill.filter(id=data.skill_id, state=0).using_db(db).select_for_update().first()
            if not skill or skill.display_status != 'ONLINE' or skill.published_version_id != version.id:
                raise DeveloperError('技能已下线或发布版本已变更，请刷新后重试', 409)
            if not await DeveloperSkillClass.filter(id=form.skill_class_id, is_enabled=True).using_db(db).select_for_update().first():
                raise DeveloperError('技能大类已停用', 409)
            current = await SkillVersion.filter(id=version.id, build_id=data.build_id).using_db(db).first()
            if not current:
                raise DeveloperError('发布构建已变更，请刷新后重试', 409)
            previous = await existing_run(data, user, db)
            if previous:
                return await OnlineDebugRunService.as_response(previous)
            task = await OnlineDebugRun.create(using_db=db, skill_id=str(skill.id), run_id=data.request_id,
                                               status='queued', debugger=(user.alias or user.username)[:64])
            await SkillDebugRun.create(using_db=db, run_id=data.request_id, skill_id=skill.id,
                skill_version_id=version.id, build_id=data.build_id, conversation_input=data.conversation_input,
                request_document_count=len(documents), resource_manifest_hash=version.manifest_hash,
                create_user_login_name=user_login_name(user))
            await Skill.filter(id=skill.id).using_db(db).update(call_count=F('call_count') + 1)
    except IntegrityError as exc:
        previous = await existing_run(data, user)
        if previous:
            return await OnlineDebugRunService.as_response(previous)
        raise DeveloperError('调用编号冲突，请重新提交', 409) from exc
    # 必须在提交后创建后台任务，避免新任务继承尚未提交的事务连接上下文。
    work = asyncio.create_task(OnlineDebugRunService._execute(task.id, task.run_id, payload, int(user.id)), name=f'catalog-debug-{task.run_id}')
    OnlineDebugRunService._tasks.add(work)
    work.add_done_callback(OnlineDebugRunService._tasks.discard)
    return await OnlineDebugRunService.as_response(task)
