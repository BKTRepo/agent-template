"""--live：真实云库/认证/HTTP路由/文件验收；仅沙箱边界注入，绝不写同事表。
运行后清理本次UUID标识的自有测试记录与文件，不保留伪造运行结果。
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
import httpx
import jwt
from fastapi import FastAPI
from tortoise import Tortoise, connections
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError
from configure import PROJECT_CONFIG
from applications.wrq.auth import verify_token
from applications.wrq.agent.models.agent_model import Skill, SkillVersion, SkillForm, Source, SourceVersion, SkillDebugRun
from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud
from applications.wrq.agent.views import skills_router, developer_skill_view
from applications.wrq.database import wrq_connections
from applications.wrq.sandbox import SandboxResults
from applications.wrq.migrations.review_20261024 import connect
from applications.wrq.migrations.review_20261026 import snapshot, PROTECTED
from applications.wrq.migrations.schema_20261026 import TABLES

class SandboxBoundary:
    def __init__(self): self.rows={}
    async def get(self,run_id,skill_id):
        if run_id in self.rows:
            row=self.rows[run_id]
            return row if row['skill_id']==skill_id else None
        return await SandboxResults().get(run_id,skill_id)

async def run():
    checks=[]; skill_ids=[]; file_ids=[]; failure=None; cleanup_done=False
    root=Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()
    report_path=Path(__file__).resolve().parents[3].parent/'deliverables/开发者中心_数据库与后端验收_20261026.json'
    report_path.parent.mkdir(exist_ok=True)
    conn=await connect()
    async with conn.cursor() as cur: before=await snapshot(cur)
    await Tortoise.init(config={'connections':wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps':{'models':{'models':PROJECT_CONFIG.APPLICATIONS_MODELS,'default_connection':'default'}},
        'use_tz':False,'timezone':'Asia/Shanghai'})
    token=Path.home().joinpath('.codex/private/wrq-interface-test-token.txt').read_text('utf8').strip()
    owner=verify_token(token)
    headers={'token':token}
    fake=SandboxBoundary(); original_crud=developer_skill_view.crud
    developer_skill_view.crud=DeveloperSkillCrud(fake)
    app=FastAPI(); app.include_router(skills_router,prefix='/skills')
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok: raise AssertionError(name)
    async def request(client,method,url,*,expected=200,**kwargs):
        response=await client.request(method,url,headers=headers,**kwargs)
        if response.status_code!=expected:
            raise AssertionError(f'{method} {url}: expected {expected}, got {response.status_code}; {response.text[:350]}')
        return response.json().get('data') if response.content else None
    def payload(name,cls,**changes):
        return {'name':name,'class_id':cls,'application_ids':['*'],'description':'本次真实云库验收',
            'instructions':'覆盖正常、异常和边界','resource_usage':'','compatibility':'','uploaded_resources':[],
            'resource_ids':[],**changes}
    def edit(row,**changes):
        return {k:row[k] for k in ('name','class_id','application_ids','description','instructions','resource_usage',
            'compatibility','uploaded_resources','resource_ids','technical_name')}|{'expected_revision':row['current_revision']}|changes
    async def build(client,row):
        form={'skill_id':row['id'],'skill_name':row['name'],'skill_class_id':row['class_id'],
            'application':(row['application_ids'] or [None])[0],'description':row['description'],
            'instructions':row['instructions'],'resource_usage':row['resource_usage'],
            'compatibility':row['compatibility'],'expected_version':row['version'],'knowledge_base_ids':row['resource_ids']}
        return await request(client,'POST','/skills/form/builds',data={'source':json.dumps(form)})
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://wrq-test',timeout=40,trust_env=False) as client:
            identity=await request(client,'GET','/skills/developer/context')
            check('平台token鉴权不查询本地用户表',identity['id']==str(owner.id))
            check('云库已无本地用户表和应用表',not {'keenrobot_user','keenrobot_applications'} & before.keys())
            bad=await client.get('/skills/developer/context',headers={'token':'invalid-token'})
            check('无效token拒绝',bad.status_code==401)
            meta=await request(client,'GET','/skills/developer/metadata')
            check('用途和平台应用目录',len(meta['resource_categories'])==4 and any(r['id']=='*' for r in meta['applications']))
            cls=meta['skill_classes'][0]['id']; name='WRQ验收-'+uuid.uuid4().hex[:12]
            row=await request(client,'POST','/skills/developer/',json=payload(name,cls)); skill_ids.append(row['id'])
            sid=row['id']; old=row['skill_version_id']
            check('真实创建草稿',row['status']=='草稿' and row['version']=='1.0.0')
            await request(client,'POST','/skills/developer/',json=payload(name,cls),expected=409)
            check('名称唯一约束',True)
            await request(client,'POST','/skills/developer/',json=payload(name+'bad',cls,application_ids=['not-registered']),expected=400)
            check('未知应用拒绝',True)
            row=await request(client,'PUT',f'/skills/developer/{sid}',json=edit(row,instructions='新版指令'))
            check('保存生成新版本且保留旧正文',row['current_revision']==2 and (await SkillForm.get(skill_version_id=old)).instructions=='覆盖正常、异常和边界')
            await request(client,'PUT',f'/skills/developer/{sid}',json=edit(row,expected_revision=1),expected=409)
            check('旧页面并发校验',True)
            resources=await request(client,'POST','/skills/developer/resources',data={'categories':json.dumps(['参考资料'])},
                files=[('files',('验收需求.md',b'# login acceptance','text/markdown'))])
            fid=resources[0]['sourceId']; file_ids.append(fid)
            row=await request(client,'PUT',f'/skills/developer/{sid}',json=edit(row,uploaded_resources=resources,resource_usage='参考登录需求'))
            original_file=await SourceVersion.get(id=resources[0]['sourceVersionId'])
            newer=await request(client,'POST',f'/skills/developer/resources/{fid}/versions',
                data={'categories':json.dumps(['模板'])},files=[('files',('验收需求.md',b'# next version','text/markdown'))])
            actual=await request(client,'GET','/skills/developer/')
            current=next(r for r in actual if r['id']==sid)
            check('文件换版不改变历史技能挂载',current['uploaded_resources'][0]['sourceVersionId']==original_file.id)
            check('文件用途快照独立',original_file.category_id!=(await SourceVersion.get(id=newer[0]['sourceVersionId'])).category_id)
            download=await client.get(resources[0]['downloadUrl'],headers=headers)
            check('原件下载与哈希',download.status_code==200 and hashlib.sha256(download.content).hexdigest()==original_file.sha256)
            built=await build(client,row)
            version=await SkillVersion.get(id=row['skill_version_id'])
            check('真实构建包与版本摘要',Path(version.package_storage_key).is_file() and bool(version.manifest_hash) and version.build_id==built['build_id'])
            run_id=uuid.uuid4().hex
            fake.rows[run_id]={'run_id':run_id,'skill_id':sid,'status':'QUEUED'}
            registration={'run_id':run_id,'build_id':built['build_id'],'skill_version_id':version.id,
                'conversation_input':'验证登录','request_document_count':1}
            await request(client,'POST',f'/skills/developer/{sid}/debug-runs',json=registration)
            await request(client,'POST',f'/skills/developer/{sid}/debug-runs',json=registration)
            link=await SkillDebugRun.get(run_id=run_id)
            check('开始即登记且重复请求幂等',link.skill_version_id==version.id and await SkillDebugRun.filter(run_id=run_id).count()==1)
            check('对话与文档数量保留',link.conversation_input=='验证登录' and link.request_document_count==1)
            await request(client,'POST',f'/skills/developer/{sid}/publish',expected=409)
            fake.rows[run_id]['status']='FAILED'
            await request(client,'POST',f'/skills/developer/{sid}/debug-result',json={**registration,'status':'passed'})
            await request(client,'POST',f'/skills/developer/{sid}/publish',expected=409)
            check('queued和失败不能伪造通过',True)
            fake.rows[run_id]['status']='PASSED'
            row=await request(client,'POST',f'/skills/developer/{sid}/publish')
            skill=await Skill.get(id=sid)
            check('上线状态与时间一致',row['status']=='已上线' and skill.is_enabled and skill.published_at is not None)
            published=await connections.get('default').execute_query_dict('SELECT * FROM keenrobot_skill_publications WHERE skill_id=%s',[sid])
            check('上线操作历史真实写入',len(published)==1 and published[0]['skill_version_id']==version.id)
            row=await request(client,'PUT',f'/skills/developer/{sid}',json=edit(row,instructions='上线后修改内容'))
            skill=await Skill.get(id=sid)
            check('上线后修改回草稿并清除当前通过标记',row['status']=='草稿' and not skill.is_enabled and skill.last_debug_passed_at is None and skill.last_debug_run_id is None)
            await request(client,'POST',f'/skills/developer/{sid}/publish',expected=409)
            recovered=await request(client,'GET',f'/skills/developer/{sid}/debug-runs/{run_id}')
            check('找回旧任务不能认定新版通过',not recovered['is_current_version'] and recovered['skill_version_id']==version.id)
            newer_build=await build(client,row)
            await request(client,'POST',f'/skills/developer/{sid}/debug-runs',json={**registration,'build_id':newer_build['build_id'],'skill_version_id':row['skill_version_id']},expected=409)
            check('任务版本关联不可改绑',True)
            try:
                async with in_transaction() as db:
                    await db.execute_query('UPDATE keenrobot_skills SET current_revision=current_revision+10 WHERE id=%s',[sid])
                check('云库外键拒绝当前版本与修订不一致',False)
            except IntegrityError:
                check('云库外键拒绝当前版本与修订不一致',True)
            try:
                async with in_transaction() as db:
                    await db.execute_query('UPDATE keenrobot_skill_resource_bindings SET file_id=4294967294 WHERE skill_id=%s',[sid])
                check('云库外键拒绝错误文件归属',False)
            except IntegrityError:
                check('云库外键拒绝错误文件归属',True)
            responses=await asyncio.gather(*[client.put(f'/skills/developer/{sid}',headers=headers,
                json=edit(row,instructions='并发保存'+str(i))) for i in range(2)])
            check('真实MySQL双请求仅一次成功',sorted(r.status_code for r in responses)==[200,409])
            row=next(r.json()['data'] for r in responses if r.status_code==200)
            await request(client,'DELETE',f'/skills/developer/{sid}')
            reused=await request(client,'POST','/skills/developer/',json=payload(name,cls)); skill_ids.append(reused['id'])
            check('软删除释放名称且保留旧版本',reused['id']!=sid and await SkillVersion.filter(skill_id=sid).count()>1)
            other_token=jwt.encode({'user_id':owner.id+1,'username':'isolated-permission-test','state':0,
                'exp':datetime.now(timezone.utc)+timedelta(minutes=10)},PROJECT_CONFIG.AUTH_SECRET_KEY,algorithm=PROJECT_CONFIG.AUTH_JWT_ALGORITHM)
            response=await client.get(f'/skills/developer/{reused["id"]}/debug-runs/{run_id}',headers={'token':other_token})
            check('独立签名身份越权拒绝，不建用户记录',response.status_code==404)
            async with conn.cursor() as cur:
                await cur.execute('SELECT TABLE_NAME,COLUMN_NAME,COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()')
                cols=list(await cur.fetchall())
                check('全部自有目标列有COMMENT',all(c['COLUMN_COMMENT'] for c in cols if c['TABLE_NAME'] in TABLES))
                for table,(_,fields,_) in TABLES.items():
                    check(table+'字段数',len([c for c in cols if c['TABLE_NAME']==table])==len(fields))
            for name,table in before.items():
                if name=='keenrobot_online_debug_runs' and table['count']:
                    async with conn.cursor() as cur:
                        await cur.execute('SELECT run_id,skill_id FROM keenrobot_online_debug_runs LIMIT 1'); peer=await cur.fetchone()
                    real=await SandboxResults().get(peer['run_id'],peer['skill_id'])
                    check('同事现有结果表只读查询兼容',real is not None)
            print('live API and SQL checks completed',flush=True)
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc)}
    finally:
        developer_skill_view.crud=original_crud
        try:
            files=await SourceVersion.filter(file_id__in=file_ids) if file_ids else []
            async with in_transaction() as db:
                if skill_ids:
                    slots=','.join(['%s']*len(skill_ids))
                    await db.execute_query(f'UPDATE keenrobot_skills SET current_version_id=NULL WHERE id IN ({slots})',skill_ids)
                    for table in ('keenrobot_skill_resource_bindings','keenrobot_skill_debug_runs','keenrobot_skill_publications'):
                        await db.execute_query(f'DELETE FROM {table} WHERE skill_id IN ({slots})',skill_ids)
                    await db.execute_query(f'DELETE FROM keenrobot_skill_forms WHERE skill_version_id IN (SELECT id FROM keenrobot_skill_versions WHERE skill_id IN ({slots}))',skill_ids)
                    await db.execute_query(f'DELETE FROM keenrobot_skill_versions WHERE skill_id IN ({slots})',skill_ids)
                    await db.execute_query(f'DELETE FROM keenrobot_skills WHERE id IN ({slots})',skill_ids)
                if file_ids:
                    slots=','.join(['%s']*len(file_ids))
                    await db.execute_query(f'UPDATE keenrobot_skill_uploaded_files SET current_version_id=NULL WHERE id IN ({slots})',file_ids)
                    await db.execute_query(f'DELETE FROM keenrobot_source_versions WHERE file_id IN ({slots})',file_ids)
                    await db.execute_query(f'DELETE FROM keenrobot_skill_uploaded_files WHERE id IN ({slots})',file_ids)
            for file in files:
                path=Path(file.storage_key).resolve()
                if not path.is_relative_to(root/'sources'): raise RuntimeError('拒绝清理受控目录外文件')
                path.unlink(missing_ok=True)
            for sid in skill_ids:
                path=(root/str(owner.id)/sid).resolve()
                if not path.is_relative_to(root) or path.parent!=root/str(owner.id): raise RuntimeError('拒绝越界清理')
                if path.is_dir(): shutil.rmtree(path)
            cleanup_done=True
            async with conn.cursor() as cur: after=await snapshot(cur)
            for name in PROTECTED:
                if name in before:
                    check('受保护表未改动：'+name,before[name]['ddl']==after[name]['ddl'] and before[name]['hash']==after[name]['hash'])
            check('本次自有测试数据清理后原记录保持',all(before[n]['hash']==after[n]['hash'] for n in TABLES))
        except BaseException as exc:
            failure=failure or {'type':type(exc).__name__,'message':'清理/校验：'+str(exc)}
        await Tortoise.close_connections(); conn.close()
    report={'date':'2026-10-26','scope':'真实云库/认证/HTTP路由/文件；沙箱边界独立模拟，不修改同事表',
        'checks':checks,'passed':sum(r['passed'] is True for r in checks),'skipped':sum(r['passed'] is None for r in checks),
        'cleanup_completed':cleanup_done,'error':failure,'production_backend_url':'http://127.0.0.1:8519'}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
    if failure: raise SystemExit(1)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--live',action='store_true'); args=parser.parse_args()
    if not args.live: parser.error('真实云库验收须显式--live')
    if sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
