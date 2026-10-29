"""隔离SQLite，不连接云库；沙箱通过依赖注入模拟，不提供生产造数入口。"""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi import FastAPI, UploadFile
from tortoise import Tortoise, connections
from applications.wrq.agent.models.agent_model import (
    Skill, SkillVersion, SkillForm, SkillPublication, DeveloperSkillClass, SourceType, SourceVersion, SkillResourceBinding, SkillDebugRun)
from applications.wrq.agent.schemas.agent_schema import DeveloperSkillForm, DeveloperDebugResult
from applications.wrq.agent.schemas.skill_package_schema import SkillDeveloperForm
from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud, DeveloperError
from applications.wrq.agent.services.source_service import SourceService
from applications.wrq.agent.services.skill_package_service import SkillPackageService
from applications.wrq.agent.views import developer_skill_view
from applications.wrq.auth import AuthControl
from configure import PROJECT_CONFIG

class FakeSandbox:
    def __init__(self): self.rows={}
    async def get(self,run_id,skill_id):
        row=self.rows.get(run_id)
        return row if row and row['skill_id']==skill_id else None
    def result(self,run_id,skill_id,status='PASSED'):
        self.rows[run_id]={'run_id':run_id,'skill_id':skill_id,'status':status}

class DeveloperTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await Tortoise.init(db_url='sqlite://:memory:',modules={'models':[
            'applications.user.models.user_model','applications.wrq.agent.models.agent_model',
            'applications.wrq.knowledge_base.models.knowledge_base_model']})
        await Tortoise.generate_schemas()
        await connections.get('default').execute_script("CREATE TABLE keenrobot_applications (id TEXT PRIMARY KEY,name TEXT,is_enabled INT); INSERT INTO keenrobot_applications VALUES ('credit','信用卡系统',1);")
        await connections.get('default').execute_script('CREATE UNIQUE INDEX uq_test_active_name ON keenrobot_skills(lower(trim(name))) WHERE state=0;')
        await DeveloperSkillClass.create(id='SKILL-CASE-001',name='智能用例生成')
        for i,code,name in [(1,'reference','参考资料'),(2,'template','模板'),(3,'asset','静态资源'),(4,'script','脚本')]:
            await SourceType.create(id=i,code=code,name=name)
        self.user=SimpleNamespace(id=1,alias='测试用户',username='tester')
        self.other=SimpleNamespace(id=2,alias='另一用户',username='other')
        self.sandbox=FakeSandbox(); self.crud=DeveloperSkillCrud(self.sandbox)
        self.temp=tempfile.TemporaryDirectory()
        self.config=patch.object(PROJECT_CONFIG,'SKILL_BUILD_DIR',self.temp.name); self.config.start()
        self.sources=SourceService()

    async def asyncTearDown(self):
        await Tortoise.close_connections()
        self.config.stop(); self.temp.cleanup()

    def form(self,**changes):
        return DeveloperSkillForm(**({'name':'登录测试','class_id':'SKILL-CASE-001','application_ids':['*'],
            'description':'生成登录功能测试用例','instructions':'覆盖成功、错误密码、边界场景'}|changes))

    async def built(self):
        skill=await self.crud.create(self.user,self.form())
        row=await self.crud.output(skill,self.user)
        data=SkillDeveloperForm(skill_id=skill.id,skill_name=row['name'],skill_class_id=row['class_id'],
            application='*',description=row['description'],instructions=row['instructions'],resource_usage='',
            expected_version=row['version'],resource_categories=[])
        package=await SkillPackageService().build_form(data,self.user,[])
        return await self.crud.get(skill.id,self.user),package

    async def test_empty_list_and_catalog(self):
        self.assertEqual(await self.crud.list(self.user),[])
        metadata=await self.crud.metadata()
        self.assertEqual(len(metadata['source_types']),4)
        self.assertIn('*',[r['id'] for r in metadata['applications']])

    async def test_required_and_unknown_application(self):
        for changes in [{'name':' '},{'description':' '},{'instructions':' '},{'application_ids':['不存在']}]:
            with self.assertRaises((ValueError,DeveloperError)):
                await self.crud.create(self.user,self.form(**changes))
        self.assertEqual(await Skill.all().count(),0)

    async def test_duplicate_and_reuse_name_after_repeated_soft_delete(self):
        a=await self.crud.create(self.user,self.form())
        with self.assertRaises(DeveloperError): await self.crud.create(self.user,self.form())
        await self.crud.delete_draft(a.id,self.user)
        b=await self.crud.create(self.user,self.form())
        await self.crud.delete_draft(b.id,self.user)
        c=await self.crud.create(self.user,self.form())
        self.assertNotEqual(a.id,c.id)
        self.assertEqual(len(await self.crud.list(self.user)),1)

    async def test_personal_list_and_permissions(self):
        skill=await self.crud.create(self.user,self.form())
        self.assertEqual(await self.crud.list(self.other),[])
        for action in [self.crud.get,self.crud.delete_draft]:
            with self.assertRaises(DeveloperError): await action(skill.id,self.other)

    async def test_new_revision_keeps_snapshot_and_rejects_stale_save(self):
        skill=await self.crud.create(self.user,self.form())
        old=skill.current_version_id
        skill=await self.crud.save(skill.id,self.user,self.form(expected_revision=1,description='新版描述'))
        self.assertEqual(skill.current_revision,2)
        self.assertEqual((await SkillForm.get(skill_version_id=old)).description,'生成登录功能测试用例')
        with self.assertRaises(DeveloperError): await self.crud.save(skill.id,self.user,self.form(expected_revision=1))
        self.assertEqual(await SkillVersion.all().count(),2)

    async def test_transaction_rolls_back_partial_creation(self):
        with patch.object(self.crud,'_write',side_effect=RuntimeError('模拟版本保存失败')):
            with self.assertRaises(RuntimeError): await self.crud.create(self.user,self.form())
        self.assertEqual(await Skill.all().count(),0)

    async def test_source_classification_original_and_version_snapshot(self):
        uploaded=await self.sources.upload([UploadFile(filename='需求.md',file=io.BytesIO(b'# login'))],['参考资料'],self.user)
        skill=await self.crud.create(self.user,self.form(uploaded_resources=uploaded,resource_usage='参考登录规则'))
        original=await SourceVersion.get(id=uploaded[0]['sourceVersionId'])
        newer=await self.sources.upload([UploadFile(filename='需求.md',file=io.BytesIO(b'# new'))],['模板'],self.user,uploaded[0]['sourceId'])
        binding=await SkillResourceBinding.get(skill_version_id=skill.current_version_id)
        self.assertEqual(binding.source_version_id,original.id)
        self.assertNotEqual(original.id,newer[0]['sourceVersionId'])
        self.assertEqual(Path(original.storage_key).read_bytes(),b'# login')
        with self.assertRaises(DeveloperError): await self.sources.download(original.id,self.other)

    async def test_reject_resource_format_empty_and_size(self):
        for name,data in [('需求.pdf',b'pdf'),('空.md',b'')]:
            with self.assertRaises(DeveloperError):
                await self.sources.upload([UploadFile(filename=name,file=io.BytesIO(data))],['参考资料'],self.user)
        with patch('applications.wrq.agent.services.source_service.MAX_BYTES',3):
            with self.assertRaises(DeveloperError):
                await self.sources.upload([UploadFile(filename='大.md',file=io.BytesIO(b'1234'))],['参考资料'],self.user)
            with self.assertRaises(DeveloperError):
                await self.sources.upload([UploadFile(filename='a.md',file=io.BytesIO(b'12')),UploadFile(filename='b.md',file=io.BytesIO(b'34'))],['参考资料','参考资料'],self.user)
        self.assertEqual(await SourceVersion.all().count(),0)

    async def test_resource_usage_and_forged_resource_rejected(self):
        with self.assertRaises(DeveloperError):
            await self.crud.create(self.user,self.form(uploaded_resources=[{'name':'假.md'}]))
        with self.assertRaises(DeveloperError):
            await self.crud.create(self.user,self.form(uploaded_resources=[{'sourceId':999,'sourceVersionId':1}],resource_usage='参考'))

    async def test_real_package_and_markdown_edit(self):
        skill,built=await self.built()
        self.assertTrue((Path(built['skill_directory'])/'SKILL.md').is_file())
        definition=await SkillPackageService().definition(skill.id,self.user)
        changed=definition['markdown'].replace('覆盖成功、错误密码、边界场景','补充验证码测试')
        rebuilt=await SkillPackageService().rebuild_saved(skill.id,self.user,markdown=changed,expected_version='1.0.0')
        self.assertEqual(rebuilt['version'],'1.0.1')
        self.assertEqual(await SkillVersion.all().count(),2)

    async def test_form_edit_after_build_replaces_stale_markdown(self):
        skill,built=await self.built()
        old=(await self.crud.output(skill,self.user))['skill_markdown']
        skill=await self.crud.save(skill.id,self.user,self.form(expected_revision=1,
            instructions='新增验证码规则',skill_markdown=old))
        saved=await SkillForm.get(skill_version_id=skill.current_version_id)
        self.assertEqual(saved.skill_markdown,'')
        form=SkillDeveloperForm(skill_id=skill.id,skill_name=skill.name,skill_class_id='SKILL-CASE-001',
            application='*',description='生成登录功能测试用例',instructions='新增验证码规则',expected_version='1.0.1')
        newer=await SkillPackageService().build_form(form,self.user,[])
        text=(Path(newer['skill_directory'])/'SKILL.md').read_text('utf8')
        self.assertIn('新增验证码规则',text)

    async def test_forged_success_not_accepted(self):
        skill,built=await self.built()
        with self.assertRaises(DeveloperError):
            await self.crud.record_debug_result(skill.id,self.user,DeveloperDebugResult(run_id='fake',build_id=built['build_id'],status='passed'))
        with self.assertRaises(DeveloperError): await self.crud.publish(skill.id,self.user)

    async def test_bad_markdown_rolls_back_entire_new_revision(self):
        from applications.wrq.agent.services.skill_package_builder import SkillPackageError
        skill,built=await self.built()
        before=skill.current_version_id
        for markdown in ['---\nname: [broken\n---\ntext','[missing](../outside.md)','---\nname: x\n---\n']:
            with self.assertRaises((SkillPackageError,DeveloperError)):
                await SkillPackageService().rebuild_saved(skill.id,self.user,markdown=markdown,expected_version='1.0.0')
            current=await self.crud.get(skill.id,self.user)
            self.assertEqual(current.current_version_id,before)
            self.assertEqual(await SkillVersion.all().count(),1)

    async def test_build_sql_failure_removes_uncommitted_package(self):
        skill=await self.crud.create(self.user,self.form())
        form=SkillDeveloperForm(skill_id=skill.id,skill_name=skill.name,skill_class_id='SKILL-CASE-001',
            application='*',description='生成登录功能测试用例',instructions='覆盖成功、错误密码、边界场景',expected_version='1.0.0')
        with patch.object(SkillVersion,'save',side_effect=RuntimeError('模拟提交失败')):
            with self.assertRaises(RuntimeError): await SkillPackageService().build_form(form,self.user,[])
        current=await self.crud.get(skill.id,self.user)
        self.assertEqual(current.display_status,'DRAFT')
        self.assertIsNone((await SkillVersion.get(id=current.current_version_id)).build_id)
        self.assertEqual(list(Path(self.temp.name).rglob('package.zip')),[])

    async def test_package_version_conflict_is_http409(self):
        from applications.wrq.agent.views.skill_package_view import skill_packages
        skill=await self.crud.create(self.user,self.form())
        app=FastAPI(); app.include_router(skill_packages,prefix='/skills')
        app.dependency_overrides[AuthControl.is_authed]=lambda:self.user
        data={'skill_id':skill.id,'skill_name':skill.name,'skill_class_id':'SKILL-CASE-001',
              'description':'生成登录功能测试用例','instructions':'覆盖成功、错误密码、边界场景','expected_version':'0.0.0'}
        import json
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/skills/form/builds',data={'source':json.dumps(data)})
        self.assertEqual(response.status_code,409)

    async def test_lifecycle_with_injected_sandbox_and_old_result_invalid(self):
        skill,built=await self.built()
        self.sandbox.result('test-run',skill.id)
        await self.crud.record_debug_result(skill.id,self.user,DeveloperDebugResult(run_id='test-run',build_id=built['build_id'],status='passed'))
        skill=await self.crud.publish(skill.id,self.user)
        self.assertEqual(skill.display_status,'ONLINE')
        with self.assertRaises(DeveloperError): await self.crud.delete_draft(skill.id,self.user)
        skill=await self.crud.offline(skill.id,self.user)
        self.assertEqual(skill.display_status,'OFFLINE')
        skill=await self.crud.publish(skill.id,self.user)
        skill=await self.crud.save(skill.id,self.user,self.form(expected_revision=1))
        self.assertEqual(skill.display_status,'DRAFT')
        with self.assertRaises(DeveloperError): await self.crud.publish(skill.id,self.user)

    async def test_api_error_status_and_identity(self):
        app=FastAPI(); app.include_router(developer_skill_view.developer_skills,prefix='/skills')
        app.dependency_overrides[AuthControl.is_authed]=lambda:self.user
        with patch.object(developer_skill_view,'crud',self.crud):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                identity=await client.get('/skills/developer/context')
                self.assertEqual(identity.json()['data']['id'],'1')
                body=self.form().model_dump()
                self.assertEqual((await client.post('/skills/developer/',json=body)).status_code,200)
                duplicate=await client.post('/skills/developer/',json=body)
                self.assertEqual(duplicate.status_code,409)
                self.assertEqual(duplicate.json()['status'],'failure')
                invalid=await client.post('/skills/developer/',json={})
                self.assertEqual(invalid.status_code,422)

    async def test_queued_registration_without_status_and_idempotence(self):
        skill,built=await self.built()
        self.sandbox.result('queued-task',skill.id,'QUEUED')
        request=DeveloperDebugResult(run_id='queued-task',build_id=built['build_id'],
            conversation_input='验证登录',request_document_count=1)
        await self.crud.record_debug_result(skill.id,self.user,request)
        await self.crud.record_debug_result(skill.id,self.user,request)
        self.assertEqual(await SkillDebugRun.all().count(),1)
        link=await SkillDebugRun.get(run_id='queued-task')
        self.assertEqual(link.skill_version_id,skill.current_version_id)
        self.assertEqual(link.conversation_input,'验证登录')
        self.assertEqual(link.request_document_count,1)
        self.assertEqual(link.build_id,built['build_id'])
        with self.assertRaises(DeveloperError): await self.crud.publish(skill.id,self.user)
        self.sandbox.result('queued-task',skill.id,'PASSED')
        published=await self.crud.publish(skill.id,self.user)
        self.assertTrue(published.is_enabled)
        self.assertIsNotNone(published.last_debug_passed_at)

    async def test_registration_uses_frozen_old_build_not_current_version(self):
        skill,built=await self.built(); old=skill.current_version_id
        skill=await self.crud.save(skill.id,self.user,self.form(expected_revision=1,instructions='新指令'))
        self.sandbox.result('old-queued',skill.id,'QUEUED')
        await self.crud.record_debug_result(skill.id,self.user,
            DeveloperDebugResult(run_id='old-queued',build_id=built['build_id']))
        self.assertEqual((await SkillDebugRun.get(run_id='old-queued')).skill_version_id,old)
        self.assertTrue((await self.crud.debug_link(skill.id,'old-queued',self.user))['is_current_version'] is False)
        self.sandbox.result('old-queued',skill.id,'PASSED')
        with self.assertRaises(DeveloperError): await self.crud.publish(skill.id,self.user)

    async def test_task_cannot_rebind_to_new_version_and_forged_status_ignored(self):
        skill,built=await self.built()
        self.sandbox.result('immutable-run',skill.id,'RUNNING')
        await self.crud.record_debug_result(skill.id,self.user,
            DeveloperDebugResult(run_id='immutable-run',build_id=built['build_id'],status='passed'))
        with self.assertRaises(DeveloperError): await self.crud.publish(skill.id,self.user)
        skill=await self.crud.save(skill.id,self.user,self.form(expected_revision=1))
        row=await self.crud.output(skill,self.user)
        newer=await SkillPackageService().build_form(SkillDeveloperForm(skill_id=skill.id,skill_name=row['name'],
            skill_class_id=row['class_id'],application='*',description=row['description'],instructions=row['instructions'],
            expected_version=row['version']),self.user,[])
        with self.assertRaises(DeveloperError):
            await self.crud.record_debug_result(skill.id,self.user,
                DeveloperDebugResult(run_id='immutable-run',build_id=newer['build_id']))

    async def test_version_and_unique_form_rollback_together(self):
        with patch.object(SkillForm,'create',side_effect=RuntimeError('表单写入失败')):
            with self.assertRaises(RuntimeError): await self.crud.create(self.user,self.form())
        self.assertEqual(await Skill.all().count(),0)
        self.assertEqual(await SkillVersion.all().count(),0)
        self.assertEqual(await SkillForm.all().count(),0)

    async def test_publication_log_and_status_rollback_together(self):
        skill,built=await self.built(); self.sandbox.result('publish-test',skill.id)
        await self.crud.record_debug_result(skill.id,self.user,
            DeveloperDebugResult(run_id='publish-test',build_id=built['build_id']))
        with patch.object(SkillPublication,'create',side_effect=RuntimeError('历史记录写入失败')):
            with self.assertRaises(RuntimeError): await self.crud.publish(skill.id,self.user)
        current=await self.crud.get(skill.id,self.user)
        self.assertFalse(current.is_enabled)
        self.assertNotEqual(current.display_status,'ONLINE')
        self.assertIsNone(current.published_at)
        await self.crud.publish(skill.id,self.user)
        await self.crud.publish(skill.id,self.user)
        self.assertEqual(await SkillPublication.all().count(),1)
        await self.crud.offline(skill.id,self.user)
        self.assertEqual(await SkillPublication.all().count(),2)

    async def test_current_cache_and_snapshot_after_edit(self):
        skill=await self.crud.create(self.user,self.form())
        old=skill.current_version_id
        skill=await self.crud.save(skill.id,self.user,self.form(name='新名称',description='新描述',expected_revision=1))
        current=await SkillForm.get(skill_version_id=skill.current_version_id)
        version=await SkillVersion.get(id=skill.current_version_id)
        self.assertEqual(skill.name,current.name)
        self.assertEqual(skill.description,current.description)
        self.assertEqual(skill.current_revision,version.revision)
        self.assertNotEqual((await SkillForm.get(skill_version_id=old)).name,current.name)
        self.assertNotIn('instructions',SkillVersion._meta.fields_map)
        self.assertNotIn('created_by',SkillForm._meta.fields_map)

    async def test_same_content_tamper_detected_before_build(self):
        upload=await self.sources.upload([UploadFile(filename='需求.md',file=io.BytesIO(b'original'))],['参考资料'],self.user)
        skill=await self.crud.create(self.user,self.form(uploaded_resources=upload,resource_usage='参考需求'))
        file=await SourceVersion.get(id=upload[0]['sourceVersionId'])
        Path(file.storage_key).write_bytes(b'tampered')
        with self.assertRaises(DeveloperError): await self.sources.download(file.id,self.user)
        row=await self.crud.output(skill,self.user)
        form=SkillDeveloperForm(skill_id=skill.id,skill_name=row['name'],skill_class_id=row['class_id'],
            application='*',description=row['description'],instructions=row['instructions'],
            resource_usage=row['resource_usage'],expected_version=row['version'])
        with self.assertRaises(DeveloperError): await SkillPackageService().build_form(form,self.user,[])

    async def test_queued_registration_http_and_recovery(self):
        skill,built=await self.built(); self.sandbox.result('new-api',skill.id,'QUEUED')
        app=FastAPI(); app.include_router(developer_skill_view.developer_skills,prefix='/skills')
        app.dependency_overrides[AuthControl.is_authed]=lambda:self.user
        with patch.object(developer_skill_view,'crud',self.crud):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post(f'/skills/developer/{skill.id}/debug-runs',
                    json={'run_id':'new-api','build_id':built['build_id']})
                self.assertEqual(response.status_code,200,response.text)
                recovered=await client.get(f'/skills/developer/{skill.id}/debug-runs/new-api')
                self.assertEqual(recovered.status_code,200)
                self.assertEqual(recovered.json()['data']['skill_version_id'],skill.current_version_id)

    async def test_knowledge_origin_and_reference_count_use_canonical_bindings(self):
        from applications.user.models.user_model import User
        from applications.wrq.knowledge_base.models.knowledge_base_model import KnowledgeBase
        await User.create(id=1,username='tester',alias='测试用户',password='unused',email='test@example.com')
        kb=await KnowledgeBase.create(id='kb-real',knowledge_name='规则库',user_id=1,is_public=False)
        skill=await self.crud.create(self.user,self.form(resource_ids=[kb.id],resource_usage='读取规则'))
        binding=await SkillResourceBinding.get(skill_version_id=skill.current_version_id)
        self.assertEqual(binding.source_type,'knowledge_base')
        self.assertEqual(binding.source_id,kb.id)
        self.assertIsNone(binding.file_id)
        self.assertIsNone(binding.source_version_id)
        row=await self.crud.output(skill,self.user)
        self.assertEqual(row['resource_ids'],[kb.id])
        self.assertEqual(row['knowledge_bases'][0]['name'],'规则库')
        from applications.wrq.knowledge_base.services.platform_service import KnowledgeService
        detail=await KnowledgeService().detail(kb.id,self.user)
        self.assertEqual(detail['reference_count'],1)

if __name__=='__main__': unittest.main()
