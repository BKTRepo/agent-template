"""仅用于显式验收：真实路由/认证/云库，只替换同事沙箱结果读取。

python -m applications.wrq.tests.acceptance_server
独立进程绑定127.0.0.1:8521；结果从本地验收夹具读，不写同事表。
生产入口不导入本模块，也没有用于伪造结果的HTTP接口。
"""
import json
from datetime import datetime
from pathlib import Path

from applications.wrq.main import app
from applications.wrq.agent.views import developer_skill_view
from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud

FIXTURE = Path(__file__).resolve().parents[4] / '.tmp/wrq-acceptance-sandbox.json'


class AcceptanceSandbox:
    async def get(self, run_id, skill_id):
        if not run_id.startswith('wrq-acceptance-') or not FIXTURE.exists():
            return None
        row = json.loads(FIXTURE.read_text('utf8')).get(run_id)
        if not row or row['skill_id'] != skill_id:
            return None
        if row.get('expires_at'):
            row['expires_at'] = datetime.fromisoformat(row['expires_at'])
        return row


developer_skill_view.crud = DeveloperSkillCrud(AcceptanceSandbox())

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8521)
