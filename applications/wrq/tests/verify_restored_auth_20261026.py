"""只验证完整项目真实HTTP鉴权；凭证仅保存私有文件和忽略提交的联调配置。"""
import json
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import jwt
from dotenv import set_key

from applications.wrq.auth import verify_token
from configure import PROJECT_CONFIG
from services import verify_password


def run():
    root=Path(__file__).resolve().parents[3]
    backup=Path.home()/'.codex/private/wrq-backups/20261026T032659Z-identity/local_identity_tables.json'
    rows=json.loads(backup.read_text('utf8'))['keenrobot_user']['rows']
    admin=next(row for row in rows if row['username']=='admin')
    # 显式提供现有账号凭证；先核对备份哈希，不重置密码。
    password=os.environ.get('WRQ_VERIFY_ADMIN_PASSWORD', '')
    if not password:
        raise RuntimeError('请通过 WRQ_VERIFY_ADMIN_PASSWORD 环境变量提供现有管理员密码')
    if not verify_password(password,admin['password']):
        raise RuntimeError('管理员密码与备份哈希不匹配；未重置账号')
    checks=[]
    with httpx.Client(base_url='http://127.0.0.1:8519',trust_env=False,timeout=20) as client:
        response=client.post('/base/auth/access_token',json={'username':admin['username'],'password':password})
        result=response.json()
        if response.status_code!=200 or result.get('status')!='success':
            raise RuntimeError('原项目Token接口未成功；未输出请求或响应中的凭证')
        token=result['data']['access_token']
        identity=verify_token(token)
        if identity.id!=admin['id']:
            raise RuntimeError('签发Token的用户编号与恢复账号不一致')
        claims=jwt.decode(token,PROJECT_CONFIG.AUTH_SECRET_KEY,algorithms=[PROJECT_CONFIG.AUTH_JWT_ALGORITHM])
        checks.append({'name':'原项目HTTP登录签发新Token','passed':True,'http_status':response.status_code})
        for path in ('/skills/developer/context','/skills/developer/metadata','/skills/developer/'):
            response=client.get(path,headers={'token':token})
            payload=response.json()
            ok=response.status_code==200 and payload.get('status')=='success'
            checks.append({'name':path,'passed':ok,'http_status':response.status_code})
            if not ok:
                raise RuntimeError('完整项目受保护接口仍不可用：'+path)
        response=client.get('/skills/developer/context')
        denied=response.json().get('status')=='failure'
        checks.append({'name':'无Token仍然拒绝访问','passed':denied,'http_status':response.status_code})
        if not denied:
            raise RuntimeError('无Token访问未被拒绝')
    frontend=root.parent/'agent-template-frontend-master-latest'
    private=Path.home()/'.codex/private/wrq-interface-test-token.txt'
    private.parent.mkdir(parents=True,exist_ok=True)
    private.write_text(token+'\n',encoding='utf8')
    # 不更改同事的REALTIME_DEBUG_TOKEN；仅更新我们开发者中心联调Token。
    set_key(str(frontend/'.env.local'),'SKILL_API_TOKEN',token)
    report={'user_table_restored':True,'token_issued_by':'POST /base/auth/access_token',
        'checks':checks,'token_saved_privately':True,'frontend_skill_token_updated':True,
        'token_expires_at':datetime.fromtimestamp(claims['exp'],ZoneInfo('Asia/Shanghai')).isoformat(),
        'colleague_token_modified':False,'authentication_bypassed':False,
        'note':'登录验证会正常更新该管理员的最后登录时间并新增原项目审计日志；没有修改其它业务表或同事任务表。'}
    path=root.parent/'deliverables/用户表恢复与整项目鉴权验证_20261026.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    run()
