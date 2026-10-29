"""本机接口测试凭证配置：复用已验证JWT，或显式签发短期测试JWT；不查询用户表。
python -m applications.wrq.configure_local_token
python -m applications.wrq.configure_local_token --issue-test-token
凭证仅写忽略提交的本地文件，不打印，不提供对外签发接口。
"""
import argparse
from datetime import datetime,timedelta,timezone
from pathlib import Path
import jwt
from dotenv import dotenv_values
from applications.wrq.auth import verify_token
from configure import PROJECT_CONFIG

def configure(issue=False):
    backend=Path(__file__).resolve().parents[2]
    frontend=backend.parent/'agent-template-frontend-master-latest'
    file=frontend/'.env.local'
    values=dotenv_values(file) if file.exists() else {}
    token=values.get('SKILL_API_TOKEN')
    if issue:
        token=jwt.encode({'user_id':1,'username':'interface-test','state':0,
            'exp':datetime.now(timezone.utc)+timedelta(hours=8)},
            PROJECT_CONFIG.AUTH_SECRET_KEY,algorithm=PROJECT_CONFIG.AUTH_JWT_ALGORITHM)
    if not token: raise RuntimeError('未找到已有平台Token；可显式--issue-test-token用于本机测试')
    identity=verify_token(token)
    private=Path.home()/'.codex/private/wrq-interface-test-token.txt'
    private.parent.mkdir(parents=True,exist_ok=True)
    private.write_text(token+'\n',encoding='utf8')
    updates={'SKILL_API_TOKEN':token,'SKILL_BACKEND_TARGET':'http://127.0.0.1:8519',
        'VITE_SKILL_PROXY_AUTH':'true','VITE_SKILL_PROXY_ACCOUNT':'platform-proxy','VITE_SKILL_METADATA_READY':'true'}
    lines=file.read_text('utf8').splitlines() if file.exists() else []
    lines=[line for line in lines if line.split('=',1)[0] not in updates]
    file.write_text('\n'.join(lines+[f'{key}={value}' for key,value in updates.items()])+'\n',encoding='utf8')
    print('已验证并准备接口测试Token；用户编号：'+str(identity.id))
    print('Token文件：'+str(private))
    print('请求头：token: <文件中的内容>；凭证未输出，也未查询用户表。')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--issue-test-token',action='store_true'); args=p.parse_args()
    configure(args.issue_test_token)
