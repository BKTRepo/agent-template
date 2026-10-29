"""同事沙箱结果只读适配；不建表、不写结果、不伪造成功。"""
from tortoise import connections

class SandboxResults:
    async def get(self, run_id, skill_id):
        rows = await connections.get('default').execute_query_dict(
            'SELECT run_id,skill_id,status,result_file_path,error_message,expires_at,started_at,finished_at '
            'FROM keenrobot_online_debug_runs WHERE run_id=%s', [run_id])
        if not rows or str(rows[0]['skill_id']) != str(skill_id):
            return None
        row = rows[0]
        status = str(row['status']).upper()
        row['status'] = {'SUCCESS': 'PASSED', 'COMPLETED': 'PASSED', 'SUCCEEDED': 'PASSED',
                         'FAILURE': 'FAILED', 'ERROR': 'FAILED'}.get(status, status)
        return row
