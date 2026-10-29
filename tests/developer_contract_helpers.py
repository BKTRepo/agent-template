"""新版契约夹具：真实HTTP/ORM/文件，隔离SQLite，不接触云库或沙箱。"""
import json
from pathlib import Path
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest_asyncio
from tortoise import connections
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, Skill, SkillVersion, SourceType
from applications.wrq.agent.services.source_service import SourceService
from applications.wrq.agent.views import skills_router, developer_skill_view
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG
from test_skill_package_api import token

FORM_FIELDS = ('name','class_id','application_ids','description','instructions','resource_ids','resource_usage','compatibility','uploaded_resources')
TYPE_NAMES = {'reference':'参考资料','template':'模板','asset':'静态资源','script':'脚本'}

async def seed_catalog():
    await DeveloperSkillClass.get_or_create(id='SKILL-CASE-001', defaults={'name':'智能用例生成'})
    for number,(code,name) in enumerate(TYPE_NAMES.items(),1):
        await SourceType.get_or_create(id=number,defaults={'code':code,'name':name})

@pytest_asyncio.fixture
async def developer_setup(database,tmp_path,monkeypatch):
    monkeypatch.setattr(PROJECT_CONFIG,'SKILL_BUILD_DIR',str(tmp_path/'builds'))
    monkeypatch.setattr(PROJECT_CONFIG,'OUTPUT_UPLOAD_DIR',str(tmp_path/'uploads'))
    Path(PROJECT_CONFIG.OUTPUT_UPLOAD_DIR).mkdir()
    await seed_catalog()
    # SQLite等价覆盖未删除名称的lower(trim)唯一约束；Unicode比较另走实际API。
    await connections.get('default').execute_script('CREATE UNIQUE INDEX uq_contract_active_name ON keenrobot_skills(lower(trim(name))) WHERE state=0;')
    monkeypatch.setattr(developer_skill_view,'sources',SourceService())
    owner=await User.create(username='owner',alias='owner',email='owner@example.com',password='unused')
    other=await User.create(username='other',alias='other',email='other@example.com',password='unused')
    app=FastAPI(); app.include_router(skills_router,prefix='/skills')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        yield client,owner,other

def payload(**changes):
    return {'name':'八字段用例生成','class_id':'SKILL-CASE-001','application_ids':[],
        'description':'按需求生成测试用例，适用于测试设计。','instructions':'读取需求并生成用例。',
        'resource_usage':'','resource_ids':[],'compatibility':'','uploaded_resources':[],**changes}

async def upload(client,user,files,categories):
    return await client.post('/skills/developer/resources',headers=token(user),
        data={'categories':json.dumps([TYPE_NAMES.get(v,v) for v in categories])},files=files)

async def create_saved(client,user,**changes):
    response=await client.post('/skills/developer/',headers=token(user),json=payload(**changes))
    assert response.status_code==200,response.text
    assert response.json()['status']=='success',response.text
    return response.json()['data']

async def update_saved(client,user,row,**changes):
    data={field:row[field] for field in FORM_FIELDS if field in row}
    return await client.put(f"/skills/developer/{row['id']}",headers=token(user),
        json={**data,'expected_revision':row['current_revision'],**changes})

async def build_saved(client,user,row,**changes):
    source={'skill_id':row['id'],'skill_name':row['name'],'skill_class_id':row['class_id'],
        'description':row['description'],'instructions':row['instructions'],
        'application':(row['application_ids'] or [None])[0],'resource_usage':row['resource_usage'],
        'compatibility':row['compatibility'],'knowledge_base_ids':row['resource_ids'],
        'expected_version':row['version'],**changes}
    return await client.post('/skills/form/builds',headers=token(user),data={'source':json.dumps(source)})

async def saved_form(row):
    skill=await Skill.get(id=row['id'])
    return await SkillVersion.get(id=skill.current_version_id)
