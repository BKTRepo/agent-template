"""开发者中心事务入口；正文一版一份，任务只登记版本关联。"""
from datetime import datetime
import hashlib
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError
from applications.wrq.agent.models.agent_model import (
    DeveloperSkillClass, Skill, SkillVersion, SkillForm, Source,
    ResourceCategory, SkillResourceBinding, SkillDebugRun, SkillPublication)
from applications.wrq.agent.skill_names import normalized_skill_name
from applications.wrq.catalog import application_options
from applications.wrq.auth import user_login_name
from applications.wrq.markdown_storage import write_markdown, read_markdown, discard_markdown
from applications.wrq.sandbox import SandboxResults
from applications.wrq.agent.services.version_service import version_and_form
from applications.wrq.agent.services.published_skill_version import display_skill_version

STATUS_TEXT = {
    'DRAFT': '草稿',
    'DEBUGGING': '调试中',
    'DEBUG_SUCCESS': '调试成功',
    'DEBUG_FAILED': '调试失败',
    'ONLINE': '已上线',
    'OFFLINE': '已下线',
}

class DeveloperError(ValueError):
    def __init__(self, message, status_code=400, field=None):
        self.status_code, self.field = status_code, field
        super().__init__(message)

def version_text(revision):
    return f'1.0.{revision - 1}'

def next_public_version(value):
    try:
        major, minor, patch = (int(part) for part in str(value).split('.'))
        return f'{major}.{minor}.{patch + 1}'
    except (TypeError, ValueError):
        return '1.0.0'

class DeveloperSkillCrud:
    def __init__(self, sandbox=None):
        self.sandbox = sandbox or SandboxResults()

    @staticmethod
    def debug_status(result):
        """将同事沙箱状态投影为当前版本的持久化技能状态。"""
        if not result:
            return None
        status = str(result.get('status', '')).upper()
        if status in ('QUEUED', 'RUNNING'):
            return 'DEBUGGING'
        if status in ('PASSED', 'COMPLETED', 'SUCCESS', 'SUCCEEDED'):
            return 'DEBUG_SUCCESS'
        if status in ('FAILED', 'FAILURE', 'ERROR', 'TIMEOUT'):
            return 'DEBUG_FAILED'
        return None

    @staticmethod
    def status_value(value):
        """兼容 Tortoise CharEnumField 返回枚举成员或字符串。"""
        return getattr(value, 'value', str(value))

    async def sync_debug_status(self, skill, version, link, result, db=None):
        """只同步当前版本、当前构建的任务，旧任务绝不能覆盖新版本状态。"""
        if (not result or skill.current_version_id != version.id or link.build_id != version.build_id
                or self.status_value(skill.display_status) in ('ONLINE', 'OFFLINE')):
            return skill
        target = self.debug_status(result)
        if target and self.status_value(skill.display_status) != target:
            skill.display_status = target
            if db:
                await skill.save(using_db=db, update_fields=['display_status', 'updated_time'])
            else:
                await skill.save(update_fields=['display_status', 'updated_time'])
        return skill

    async def metadata(self):
        categories = await ResourceCategory.filter(is_enabled=True).order_by('id').values('id','code','name')
        return {'skill_classes':await DeveloperSkillClass.filter(is_enabled=True).order_by('id').values('id','name'),
                'applications':await application_options(), 'resource_categories':categories,
                'source_types':categories}  # 旧前端响应键兼容；值仍只是用途，不是来源。

    async def get(self, skill_id, user, db=None):
        q = Skill.filter(id=skill_id,create_user_login_name=user_login_name(user),state=0)
        if db:
            q=q.using_db(db).select_for_update()
        skill=await q.first()
        if not skill:
            raise DeveloperError('技能不存在或无权操作',404)
        return skill

    async def name_available(self,name,exclude_id=None,connection=None):
        key=normalized_skill_name(name)
        q=Skill.filter(state=0).exclude(id=exclude_id or '')
        if connection: q=q.using_db(connection)
        return not any(normalized_skill_name(r.name)==key for r in await q)

    async def validate(self,data,user,db=None):
        for key,message in [('name','技能名称不能为空'),('description','请填写描述'),('instructions','请填写执行指令')]:
            if not getattr(data,key).strip(): raise DeveloperError(message,field=key)
        normalized_skill_name(data.name)
        classes = DeveloperSkillClass.filter(id=data.class_id, is_enabled=True)
        if db: classes = classes.using_db(db).select_for_update()
        if not await classes.first():
            raise DeveloperError('请选择有效的技能大类',field='class_id')
        apps={r['id'] for r in await application_options()}
        application_paso = data.effective_application_paso
        if application_paso and application_paso not in apps:
            raise DeveloperError('请选择应用目录中存在的应用',field='application_paso')
        if (data.uploaded_resources or data.resource_ids) and not data.resource_usage.strip():
            raise DeveloperError('已选择挂载知识库或上传资源，请填写资源使用说明',field='resource_usage')
        files=[]
        for row in data.uploaded_resources:
            file_id = row.get('fileId')
            if isinstance(file_id, bool) or not isinstance(file_id, int):
                raise DeveloperError('上传资源缺少有效文件编号，请重新上传', field='uploaded_resources')
            q = Source.filter(id=file_id, create_user_login_name=user_login_name(user))
            if db: q = q.using_db(db).select_for_update()
            file = await q.first()
            if not file or file.state == 'DELETED':
                raise DeveloperError('上传资源不存在或无访问权限', field='uploaded_resources')
            cq = ResourceCategory.filter(id=file.category_id, is_enabled=True)
            if db: cq = cq.using_db(db).select_for_update()
            category = await cq.first()
            if not category or row.get('category') != category.name:
                raise DeveloperError('请选择并保存资源用途分类', field='uploaded_resources')
            files.append(file)
        if len({f.id for f in files}) != len(files):
            raise DeveloperError('不能重复挂载同一文件', field='uploaded_resources')
        if sum(f.byte_size for f in files) > 50*1024*1024 or any(f.byte_size > 50*1024*1024 for f in files):
            raise DeveloperError('单文件及资源总大小不能超过50MB', field='uploaded_resources')
        knowledge=[]
        if data.resource_ids:
            from tortoise import connections
            tables = await connections.get('default').execute_query_dict(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='keenrobot_knowledge_bases'")
            if not tables:
                raise DeveloperError('知识库服务尚未接入，请先使用资源上传', 503, 'resource_ids')
            from applications.wrq.knowledge_base.models.knowledge_base_model import KnowledgeBase
            for kid in dict.fromkeys(data.resource_ids):
                kb=await KnowledgeBase.filter(id=kid,state__not=1).first()
                if not kb or (getattr(kb, 'create_user_login_name', None)!=user_login_name(user) and not kb.is_public):
                    raise DeveloperError('知识库不存在或无挂载权限',field='resource_ids')
                knowledge.append((kid,kb.knowledge_name))
        return files,knowledge

    @staticmethod
    def check_revision(skill,expected):
        if expected!=skill.current_revision:
            raise DeveloperError('技能已被修改或缺少版本信息，请刷新后重试',409)

    async def _write(self,skill,data,user,files,knowledge,db,markdown=None,artifacts=None):
        published = await SkillVersion.filter(id=skill.published_version_id).using_db(db).first() if skill.published_version_id else None
        version=await SkillVersion.create(using_db=db,skill_id=skill.id,version=published.version if published else None,
            revision=skill.current_revision,create_user_login_name=user_login_name(user),
            update_user_login_name=user_login_name(user))
        markdown_path = write_markdown(skill.id, markdown) if markdown else ''
        if markdown_path and artifacts is not None: artifacts.append(markdown_path)
        technical=data.technical_name or 'skill-'+hashlib.sha256(skill.id.encode()).hexdigest()[:24]
        await SkillForm.create(using_db=db,skill_version_id=version.id,name=data.name.strip(),
            skill_class_id=data.class_id,application_paso=data.effective_application_paso,
            description=data.description.strip(),instructions=data.instructions.strip(),
            resource_usage=data.resource_usage or None,compatibility=data.compatibility or None,
            technical_name=technical,skill_markdown_path=markdown_path)
        for index,file in enumerate(files):
            row=data.uploaded_resources[index]
            await SkillResourceBinding.create(using_db=db,skill_id=skill.id,skill_version_id=version.id,
                source_type='upload',source_id=file.id,
                file_id=file.id,display_name=file.original_name,
                usage_text=row.get('usage') or row.get('usage_text'),content_hash=file.sha256,sort_order=index)
        for index,(kid,name) in enumerate(knowledge,len(files)):
            await SkillResourceBinding.create(using_db=db,skill_id=skill.id,skill_version_id=version.id,
                source_type='knowledge_base',source_id=kid,
                display_name=name,sort_order=index)
        skill.name=data.name.strip()
        skill.application_paso=data.effective_application_paso
        skill.skill_classes_id=data.class_id
        skill.update_user_login_name=user_login_name(user)
        skill.current_version_id=version.id
        await skill.save(using_db=db)
        return skill

    async def create(self,user,data):
        artifacts=[]
        try:
            async with in_transaction() as db:
                files,kbs=await self.validate(data,user,db)
                if not await self.name_available(data.name,connection=db):
                    raise DeveloperError('该技能名称已存在，请更换',409,'name')
                skill=await Skill.create(using_db=db,name=data.name.strip(),create_user_login_name=user_login_name(user),
                    update_user_login_name=user_login_name(user),skill_classes_id=data.class_id,application_paso=data.effective_application_paso)
                return await self._write(skill,data,user,files,kbs,db,artifacts=artifacts)
        except BaseException as exc:
            for relative in artifacts: discard_markdown(relative)
            if isinstance(exc, IntegrityError):
                raise DeveloperError('名称或版本发生冲突，请刷新后重试',409) from exc
            raise

    async def save(self,skill_id,user,data,*,definition=False):
        artifacts=[]
        try:
            async with in_transaction() as db:
                skill=await self.get(skill_id,user,db)
                self.check_revision(skill,data.expected_revision)
                files,kbs=await self.validate(data,user,db)
                if not await self.name_available(data.name,skill.id,db):
                    raise DeveloperError('该技能名称已存在，请更换',409,'name')
                skill.current_revision+=1
                skill.display_status='DRAFT'
                skill.last_debug_run_id=None
                return await self._write(skill,data,user,files,kbs,db,markdown=data.skill_markdown if definition else None,artifacts=artifacts)
        except BaseException as exc:
            for relative in artifacts: discard_markdown(relative)
            if isinstance(exc, IntegrityError):
                raise DeveloperError('名称或版本发生冲突，请刷新后重试',409) from exc
            raise

    async def delete_draft(self,skill_id,user):
        async with in_transaction() as db:
            skill=await self.get(skill_id,user,db)
            if skill.display_status!='DRAFT': raise DeveloperError('只有草稿可以删除')
            skill.state=1
            skill.update_user_login_name=user_login_name(user)
            await skill.save(using_db=db,update_fields=['state','update_user_login_name','updated_time'])

    async def offline(self,skill_id,user,data=None):
        async with in_transaction() as db:
            skill=await self.get(skill_id,user,db)
            if skill.display_status!='ONLINE': raise DeveloperError('只有已上线技能可以下线')
            reason_code = getattr(data, 'reason_code', None) or 'ABILITY_DEFECT'
            reason_text = getattr(data, 'reason_text', None)
            if reason_code == 'OTHER' and not (reason_text or '').strip():
                raise DeveloperError('选择其他下线原因时必须填写具体原因', field='reason_text')
            if reason_code != 'OTHER' and reason_text and reason_text.strip():
                raise DeveloperError('该下线原因不允许填写额外说明', field='reason_text')
            skill.display_status='OFFLINE'; skill.offline_at=datetime.now()
            skill.update_user_login_name=user_login_name(user)
            await skill.save(using_db=db)
            published = await SkillVersion.get_or_none(id=skill.published_version_id).using_db(db) if skill.published_version_id else None
            await SkillPublication.create(using_db=db,skill_id=skill.id,skill_version_id=skill.published_version_id or skill.current_version_id,
                version=published.version if published else None, action='OFFLINE',operator_login_name=user_login_name(user),
                reason_code=reason_code, reason_text=(reason_text or '').strip() or None)
            return skill

    @staticmethod
    def expired(result):
        expiry=result.get('expires_at')
        return bool(expiry and expiry<datetime.now(expiry.tzinfo))

    async def publish(self,skill_id,user):
        async with in_transaction() as db:
            skill=await self.get(skill_id,user,db)
            if skill.display_status=='ONLINE': return skill
            if skill.display_status=='OFFLINE':
                raise DeveloperError('下线技能必须先修改并重新调试通过后才能上线',409)
            version,_=await version_and_form(skill.current_version_id,db)
            if not version or not version.build_id:
                raise DeveloperError('当前版本尚未生成有效构建，不能上线',409)
            links=await SkillDebugRun.filter(skill_id=skill.id,skill_version_id=skill.current_version_id,
                create_user_login_name=user_login_name(user)).using_db(db).order_by('-created_time')
            accepted=None
            for link in links:
                if not version or link.build_id!=version.build_id: continue
                result=await self.sandbox.get(link.run_id,skill.id)
                if result and str(result.get('status','')).upper() in ('PASSED','COMPLETED','SUCCESS','SUCCEEDED') and not self.expired(result):
                    accepted=(link,result); break
            if not accepted:
                raise DeveloperError('当前版本尚未取得沙箱调试通过结果，不能上线',409)
            published = await SkillVersion.get_or_none(id=skill.published_version_id).using_db(db) if skill.published_version_id else None
            version.version = next_public_version(published.version if published else None)
            await version.save(using_db=db, update_fields=['version','updated_time'])
            skill.display_status='ONLINE'; skill.published_at=datetime.now(); skill.published_version_id=version.id
            skill.update_user_login_name=user_login_name(user)
            skill.last_debug_run_id=accepted[0].run_id
            await skill.save(using_db=db)
            await SkillPublication.create(using_db=db,skill_id=skill.id,skill_version_id=version.id,
                version=version.version, action='PUBLISH',operator_login_name=user_login_name(user))
            return skill

    async def record_debug_result(self,skill_id,user,data):
        # queued/running即可登记；不相信浏览器传来的成功状态或结果文件。
        result=await self.sandbox.get(data.run_id,skill_id)
        try:
            async with in_transaction() as db:
                skill=await self.get(skill_id,user,db)
                q=SkillVersion.filter(skill_id=skill.id).using_db(db)
                if data.build_id: q=q.filter(build_id=data.build_id)
                if data.skill_version_id: q=q.filter(id=data.skill_version_id)
                version=await q.first() if (data.build_id or data.skill_version_id) else None
                if not version or not version.build_id:
                    raise DeveloperError('调试任务无法对应已保存的构建版本',409)
                old=await SkillDebugRun.filter(run_id=data.run_id).using_db(db).first()
                if old and (old.skill_id!=skill.id or old.skill_version_id!=version.id or old.create_user_login_name!=user_login_name(user)):
                    raise DeveloperError('该任务编号已关联其他技能或版本',409)
                if not old:
                    await SkillDebugRun.create(using_db=db,run_id=data.run_id,skill_id=skill.id,
                        skill_version_id=version.id,build_id=version.build_id,create_user_login_name=user_login_name(user),
                        conversation_input=data.conversation_input,request_document_count=data.request_document_count,
                        resource_manifest_hash=version.manifest_hash)
                if skill.current_version_id==version.id:
                    skill.last_debug_run_id=data.run_id
                    skill.update_user_login_name=user_login_name(user)
                    target = self.debug_status(result) or 'DEBUGGING'
                    if skill.display_status not in ('ONLINE', 'OFFLINE'):
                        skill.display_status = target
                    await skill.save(using_db=db)
                return skill
        except IntegrityError as exc:
            raise DeveloperError('任务登记发生并发冲突，请使用原任务编号重试',409) from exc

    async def debug_link(self,skill_id,run_id,user):
        await self.get(skill_id,user)
        link=await SkillDebugRun.get_or_none(run_id=run_id,skill_id=skill_id,create_user_login_name=user_login_name(user))
        if not link: raise DeveloperError('该任务尚未关联技能版本',404)
        skill=await self.get(skill_id,user)
        version=await SkillVersion.get(id=link.skill_version_id)
        result = await self.sandbox.get(run_id,skill_id)
        await self.sync_debug_status(skill, version, link, result)
        return {'run_id':link.run_id,'skill_id':skill_id,'skill_version_id':version.id,
                'version':version.version,'build_id':link.build_id,
                'is_current_version':skill.current_version_id==version.id,
                'task':result}

    async def list(self,user,*,page=None,page_size=None):
        query=Skill.filter(create_user_login_name=user_login_name(user),state=0).order_by('-updated_time')
        if page is None or page_size is None:
            return await query
        total=await query.count()
        return await query.offset((page-1)*page_size).limit(page_size), total

    async def output(self,skill,user):
        version,form=await version_and_form(skill.current_version_id)
        if not version or not form or version.skill_id!=skill.id:
            raise DeveloperError('技能缺少有效版本或表单，请检查迁移记录',409)
        categories={r.id:r.name for r in await ResourceCategory.all()}
        files=[]; knowledge=[]
        for binding in await SkillResourceBinding.filter(skill_version_id=version.id).order_by('sort_order','id'):
            if binding.file_id is not None:
                file=await Source.get_or_none(id=binding.file_id)
                if not file: raise DeveloperError('挂载文件不存在，请核对资源关系',409)
                category=categories.get(file.category_id,'')
                files.append({'id':f'file:{file.id}','fileId':file.id,
                    'name':file.original_name,'size':file.byte_size,'lastModified':0,'category':category,'savedCategory':category,
                    'downloadUrl':f'/skills/developer/resources/{file.id}/download',
                    'usage':binding.usage_text or ''})
            elif binding.source_type=='knowledge_base':
                knowledge.append({'id':binding.source_id,'name':binding.display_name or binding.source_id,'source':'backend'})
        link=await SkillDebugRun.filter(skill_id=skill.id,skill_version_id=version.id).order_by('-created_time').first()
        debug=None
        if link:
            result=await self.sandbox.get(link.run_id,skill.id)
            if result:
                await self.sync_debug_status(skill, version, link, result)
                debug={'id':link.run_id,'runId':link.run_id,'buildId':link.build_id,'skillVersionId':version.id,
                    'status':('passed' if str(result.get('status','')).upper() in ('PASSED','COMPLETED','SUCCESS','SUCCEEDED') else str(result.get('status','')).lower()),
                    'output':result.get('error_message') or '调试状态来自沙箱服务。','origin':'backend'}
        page_status = STATUS_TEXT.get(self.status_value(skill.display_status), '草稿')
        if page_status not in ('已上线','已下线') and debug:
            page_status = {'passed':'调试成功','failed':'调试失败','queued':'调试中','running':'调试中'}.get(debug['status'], page_status)
        return {'id':skill.id,'name':form.name,'class_id':form.skill_class_id,
            'application_paso':form.application_paso,'application_ids':[form.application_paso] if form.application_paso else [],'description':form.description,
            'instructions':form.instructions,'resource_ids':[k['id'] for k in knowledge],
            'resource_usage':form.resource_usage or '','compatibility':form.compatibility or '',
            'technical_name':form.technical_name,'uploaded_resources':files,'knowledge_bases':knowledge,
            'skill_markdown':display_skill_version(read_markdown(form.skill_markdown_path), version.version) if form.skill_markdown_path else '', 'version':version.version,'current_revision':version.revision,
            'skill_version_id':version.id,'status':page_status,'creator_login_name':skill.create_user_login_name,'updater_login_name':skill.update_user_login_name,
            'creator_name':user.alias or user.username,'updated_at':skill.updated_time,'backend_skill_id':skill.id,
            'build_id':version.build_id,'build_origin':'backend' if version.build_id else None,'debug':debug}
