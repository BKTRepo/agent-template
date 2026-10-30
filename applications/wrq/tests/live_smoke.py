"""显式运行真实联调，不生成沙箱任务，不修改同事表。
测试记录最后软删除，历史版本/原件作为被删除记录的快照保留。
"""
import json
from pathlib import Path
import uuid
import httpx

def run():
    root=Path(__file__).resolve().parents[3]
    report=[]; created=[]
    with httpx.Client(base_url='http://127.0.0.1:5175',timeout=40,trust_env=False) as client:
        def request(label,method,path,expected=200,**kwargs):
            response=client.request(method,path,**kwargs)
            report.append({'case':label,'status':response.status_code,'passed':response.status_code==expected})
            if response.status_code!=expected:
                raise AssertionError(label+': '+response.text[:400])
            return response
        try:
            request('服务端代理认证，无前端登录', 'GET','/skills/developer/context')
            meta=request('用途字典四项和全应用目录','GET','/skills/developer/metadata').json()['data']
            assert len(meta['source_types'])==4 and any(r['id']=='*' for r in meta['applications'])
            resource=request('上传真实Markdown原文件','POST','/skills/developer/resources',
                files=[('files',('验收需求.md','# 登录需求\n错误密码不能登录。'.encode(),'text/markdown'))],
                data={'categories':json.dumps(['参考资料'])}).json()['data']
            prefix='WRQ验收-'+uuid.uuid4().hex[:8]
            form={'name':prefix,'class_id':meta['skill_classes'][0]['id'],'application_ids':['*'],
                'description':'验收后自动软删除','instructions':'按需求生成登录功能测试用例',
                'resource_usage':'参考登录需求','uploaded_resources':resource}
            skill=request('新建草稿写云数据库','POST','/skills/developer/',json=form).json()['data'];created.append(skill['id'])
            request('名称重复返回HTTP409','POST','/skills/developer/',expected=409,json=form)
            rows=request('刷新后仍可读取文件挂载','GET','/skills/developer/').json()['data']
            fresh=next(r for r in rows if r['id']==skill['id'])
            assert fresh['uploaded_resources'][0]['sourceVersionId']==resource[0]['sourceVersionId']
            raw=request('从服务端下载挂载原文件','GET',fresh['uploaded_resources'][0]['downloadUrl'])
            assert '错误密码'.encode() in raw.content
            changed=form|{'description':'修改后的验收描述','expected_revision':1}
            skill=request('保存修改递增为1.0.1','PUT',f"/skills/developer/{skill['id']}",json=changed).json()['data']
            assert skill['version']=='1.0.1' and isinstance(skill['skill_version_id'],int)
            request('旧页面保存被拦截','PUT',f"/skills/developer/{skill['id']}",expected=409,json=changed)
            build_form={'skill_id':skill['id'],'skill_name':skill['name'],'skill_class_id':skill['class_id'],
                'application':'*','description':skill['description'],'instructions':skill['instructions'],
                'resource_usage':skill['resource_usage'],'resource_categories':['reference'],'expected_version':'1.0.1'}
            built=request('使用已保存原文件构建Skill，无需重新选择文件','POST','/skills/form/builds',
                data={'source':json.dumps(build_form)},files=[]).json()['data']
            definition=request('在线调试可读取Markdown','GET',f"/skills/{skill['id']}/definition").json()['data']
            assert definition['build']['build_id']==built['build_id']
            request('没有真实沙箱成功结果不能上线','POST',f"/skills/developer/{skill['id']}/publish",expected=409)
            request('浏览器伪造passed不能上线','POST',f"/skills/developer/{skill['id']}/debug-result",expected=409,
                json={'run_id':'wrq-not-a-real-run','build_id':built['build_id'],'status':'passed'})
            fresh=request('回到编辑生成新草稿','PUT',f"/skills/developer/{skill['id']}",json=form|{'expected_revision':2}).json()['data']
            request('删除草稿','DELETE',f"/skills/developer/{skill['id']}")
            for cycle in range(2):
                again=request(f'第{cycle+1}次重新使用已删除名称','POST','/skills/developer/',json=form).json()['data']
                created.append(again['id'])
                request(f'第{cycle+1}次再次删除','DELETE',f"/skills/developer/{again['id']}")
        finally:
            for skill_id in created:
                client.delete(f'/skills/developer/{skill_id}')
            path=root.parent/'deliverables/WRQ_真实接口基础测试_20261024.json'
            path.write_text(json.dumps({'cases':report,'created_test_ids':created,'sandbox_execution':'not_invoked'},ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'passed':sum(r['passed'] for r in report),'total':len(report),'report':str(path)},ensure_ascii=False))

if __name__=='__main__':run()
