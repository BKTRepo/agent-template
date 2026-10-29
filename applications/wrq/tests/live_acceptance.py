"""显式真实验收；参照deliverables/开发者中心_测试用例_20261025.csv。

生产代理5175和仅替换沙箱边界的验收服务8521均连接真实云数据库。
测试只创建带WRQ验收前缀的我方数据；结束软删除；保护其它表。
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sys
import uuid
import zipfile

import httpx
from applications.wrq.migrations.review_20261024 import connect, snapshot, OWNED, LEGACY
from configure import PROJECT_CONFIG

ROOT = Path(__file__).resolve().parents[4]
REPORT = ROOT / 'deliverables/开发者中心_真实验收结果_20261025.json'
FIXTURE = ROOT / '.tmp/wrq-acceptance-sandbox.json'


async def database_snapshot():
    conn = await connect()
    try:
        async with conn.cursor() as cur:
            result = await snapshot(cur)
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            tls = (await cur.fetchone())['Value']
            return result, tls
    finally:
        conn.close()


def db_snapshot():
    return asyncio.run(database_snapshot())


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class Acceptance:
    def __init__(self):
        env = dict(line.split('=', 1) for line in (ROOT / 'agent-template-frontend-master-latest/.env.local').read_text('utf8').splitlines() if '=' in line and not line.startswith('#'))
        self.client = httpx.Client(base_url='http://127.0.0.1:5175', trust_env=False, timeout=90)
        self.boundary = httpx.Client(base_url='http://127.0.0.1:8521', headers={'token': env['SKILL_API_TOKEN']}, trust_env=False, timeout=90)
        self.rows = []
        self.created = []
        self.forms = {}
        self.results = {}
        self.prefix = 'WRQ验收-' + uuid.uuid4().hex[:8]

    def check(self, case, label, ok, detail=''):
        self.rows.append({'id': case, 'case': label, 'passed': bool(ok), 'detail': detail})
        if not ok:
            raise AssertionError(label + ': ' + str(detail)[:500])

    def call(self, case, label, method, path, expected=200, boundary=False, **kwargs):
        res = (self.boundary if boundary else self.client).request(method, path, **kwargs)
        self.check(case, label, res.status_code == expected, f'HTTP {res.status_code}' + (': ' + res.text[:300] if res.status_code != expected else ''))
        return res

    def create(self, suffix='', **changes):
        form = self.base | {'name': self.prefix + suffix} | changes
        res = self.call('DC09', '真实云库新建草稿' + suffix, 'POST', '/skills/developer/', json=form)
        row = res.json()['data']
        self.created.append(row['id'])
        self.forms[row['id']] = form
        return row

    def save(self, row, boundary=False, **changes):
        form = self.forms[row['id']] | changes
        data = form | {'expected_revision': row['current_revision']}
        saved = self.call('DC11', '真实保存新版本', 'PUT', '/skills/developer/' + row['id'], boundary=boundary, json=data).json()['data']
        self.forms[row['id']] = form
        return saved

    def build(self, row):
        form = {'skill_id': row['id'], 'skill_name': row['name'], 'skill_class_id': row['class_id'],
                'application': '*', 'description': row['description'], 'instructions': row['instructions'],
                'resource_usage': row['resource_usage'], 'expected_version': row['version'],
                'resource_categories': ['reference'] * len(row['uploaded_resources'])}
        res = self.call('DC14', '从真实保存版本生成Skill包', 'POST', '/skills/form/builds', data={'source': json.dumps(form)})
        body = res.json()
        self.check('DC14', '构建业务成功', bool(body.get('data', {}).get('build_id')), str(body)[:350])
        return body['data']

    def sandbox_result(self, skill, build, status='PASSED', expired=False):
        run_id = 'wrq-acceptance-' + uuid.uuid4().hex
        self.results[run_id] = {'run_id': run_id, 'skill_id': skill['id'], 'status': status,
            'expires_at': (datetime.now() - timedelta(hours=1)).isoformat() if expired else None}
        FIXTURE.write_text(json.dumps(self.results), encoding='utf8')
        self.call('DC17' if status != 'PASSED' or expired else 'DC18', '关联边界替身结果，写真实版本关联表', 'POST', f"/skills/developer/{skill['id']}/debug-result", boundary=True,
                  json={'run_id': run_id, 'build_id': build['build_id'], 'status': 'passed'})
        return run_id

    def execute(self):
        before, tls = db_snapshot()
        self.check('DC28', '云数据库TLS已启用且自动迁移关闭', bool(tls) and not PROJECT_CONFIG.aerich_should_run_on_startup, tls)
        completed = False
        try:
            context = self.call('DC02', '前端代理取得真实用户', 'GET', '/skills/developer/context').json()['data']
            meta = self.call('DC02', '读取大类、应用、用途目录', 'GET', '/skills/developer/metadata').json()['data']
            self.check('DC02', '四种用途及全应用目录', len(meta['source_types']) == 4 and any(v['id'] == '*' for v in meta['applications']))
            self.base = {'name': self.prefix, 'class_id': meta['skill_classes'][0]['id'], 'application_ids': ['*'],
                'description': '真实验收临时记录，完成后软删除', 'instructions': '从需求生成登录测试，覆盖正常和错误密码', 'resource_usage': '参考上传需求'}
            for key in ['name', 'class_id', 'description', 'instructions']:
                self.call('DC03', '必填字段缺失：' + key, 'POST', '/skills/developer/', expected=422, json={k: v for k, v in self.base.items() if k != key})
            self.call('DC04', '目录外应用拒绝', 'POST', '/skills/developer/', expected=400, json=self.base | {'application_ids': ['wrq-not-existing']})
            self.call('DC07', '遗漏用途拒绝', 'POST', '/skills/developer/resources', expected=400, data={'categories': '[]'}, files={'files': ('a.md', b'# requirement')})
            self.call('DC07', '不存在用途拒绝', 'POST', '/skills/developer/resources', expected=400, data={'categories': '["不存在"]'}, files={'files': ('a.md', b'# requirement')})
            self.call('DC05', '资源上传拒绝txt（沙箱文档格式不适用此处）', 'POST', '/skills/developer/resources', expected=400, data={'categories': '["参考资料"]'}, files={'files': ('a.txt', b'text')})
            # 有效Office容器与图片，不使用改后缀的伪文件。
            repo = ROOT / 'agent-template-master-latest'
            image_files = {'png': (repo / 'static/swagger-ui/favicon-32x32.png').read_bytes(),
                'jpg': (repo / 'docs/skill-integration-result.jpg').read_bytes(),
                'jpeg': (repo / 'docs/skill-form-no-login.jpg').read_bytes()}
            ns = 'http://schemas.openxmlformats.org/'
            relations = f'<Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" Type="{ns}officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
            word = zip_bytes({'[Content_Types].xml': f'<Types xmlns="{ns}package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
                '_rels/.rels': relations, 'word/document.xml': f'<w:document xmlns:w="{ns}wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>登录错误密码提示</w:t></w:r></w:p></w:body></w:document>'})
            sheet = zip_bytes({'[Content_Types].xml': f'<Types xmlns="{ns}package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
                '_rels/.rels': relations.replace('word/document.xml', 'xl/workbook.xml'),
                'xl/workbook.xml': f'<workbook xmlns="{ns}spreadsheetml/2006/main" xmlns:r="{ns}officeDocument/2006/relationships"><sheets><sheet name="需求" sheetId="1" r:id="rId1"/></sheets></workbook>',
                'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" Type="{ns}officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
                'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{ns}spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>登录需求</t></is></c></row></sheetData></worksheet>'})
            contents = {'py': b'print("test")\n', 'js': b'export const test = true;\n', 'md': '# 登录需求\n错误密码不能登录。'.encode(), 'docx': word, 'xlsx': sheet} | image_files
            upload = self.call('DC05', '八种规定格式实际上传', 'POST', '/skills/developer/resources',
                data={'categories': json.dumps(['参考资料'] * 8)}, files=[('files', (self.prefix + '.' + ext, content)) for ext, content in contents.items()]).json()['data']
            for resource in upload:
                raw = self.call('DC05', '原件下载逐字节核对：' + resource['name'].rsplit('.', 1)[1], 'GET', resource['downloadUrl'])
                self.check('DC05', '下载与上传内容一致', raw.content == contents[resource['name'].rsplit('.', 1)[1]])
            resource = next(v for v in upload if v['name'].endswith('.md'))
            self.call('DC08', '有挂载时使用说明必填', 'POST', '/skills/developer/', expected=400, json=self.base | {'uploaded_resources': [resource], 'resource_usage': ''})
            row = self.create(uploaded_resources=[resource]); first = dict(row)
            self.check('DC09', '初始草稿和版本', row['status'] == '草稿' and row['version'] == '1.0.0')
            self.call('DC10', '重复名称409', 'POST', '/skills/developer/', expected=409, json=self.forms[row['id']])
            self.call('DC10', '名称空格及大小写规范化后409', 'POST', '/skills/developer/', expected=409, json=self.base | {'name': ' ' + self.prefix.lower() + ' '})
            concurrent_form = self.base | {'name': self.prefix + '-并发'}
            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(lambda _: self.client.post('/skills/developer/', json=concurrent_form), range(2)))
            for response in responses:
                if response.status_code == 200:
                    item = response.json()['data']; self.created.append(item['id']); self.forms[item['id']] = concurrent_form
            self.check('DC10', '真实并发同名仅一项成功', sorted(r.status_code for r in responses) == [200, 409], [r.status_code for r in responses])
            row = self.save(row, description='验收修改后的描述')
            self.check('DC11', '保存递增版本', row['version'] == '1.0.1' and isinstance(row['skill_version_id'], int))
            self.call('DC12', '旧revision不能覆盖', 'PUT', '/skills/developer/' + row['id'], expected=409, json=self.forms[row['id']] | {'expected_revision': 1})
            replacement = self.call('DC13', '原件更新并改为模板用途', 'POST', f"/skills/developer/resources/{resource['sourceId']}/versions", data={'categories': '["模板"]'}, files={'files': ('新版需求.md', '# 第二版'.encode())}).json()['data'][0]
            self.check('DC13', '同一source的新版本', replacement['sourceId'] == resource['sourceId'] and replacement['sourceVersionId'] != resource['sourceVersionId'])
            self.check('DC13', '旧版本文件仍可读取', self.client.get(resource['downloadUrl']).content == contents['md'])
            built = self.build(row)
            definition = self.call('DC14', '读取真实Markdown定义', 'GET', f"/skills/{row['id']}/definition").json()['data']
            self.check('DC14', 'Skill包中的文件实际存在', Path(built['skill_directory'], 'SKILL.md').is_file())
            bad = self.call('DC15', '无效Markdown编辑不保存', 'PUT', f"/skills/{row['id']}/definition", json={'expected_version': row['version'], 'markdown': '---\nname: [\n---\n# 无效'})
            self.check('DC15', '无效编辑返回业务失败', bad.json().get('status') != 'success' and not bad.json().get('data', {}).get('build_id'), str(bad.json())[:200])
            edited = self.call('DC15', '有效Markdown编辑重新构建', 'PUT', f"/skills/{row['id']}/definition", json={'expected_version': row['version'], 'markdown': definition['markdown'] + '\n\n验收新增边界测试。'}).json()['data']
            self.check('DC15', 'Markdown修改生成1.0.2', edited['version'] == '1.0.2')
            row = next(v for v in self.client.get('/skills/developer/').json()['data'] if v['id'] == row['id']); built = edited
            self.call('DC16', '无沙箱结果不能上线', 'POST', f"/skills/developer/{row['id']}/publish", expected=409)
            self.call('DC16', '前端伪造passed拒绝', 'POST', f"/skills/developer/{row['id']}/debug-result", expected=409, json={'run_id': 'wrq-forged-' + uuid.uuid4().hex, 'build_id': built['build_id'], 'status': 'passed'})
            self.sandbox_result(row, built, 'FAILED')
            self.call('DC17', '失败结果不能上线', 'POST', f"/skills/developer/{row['id']}/publish", expected=409, boundary=True)
            self.sandbox_result(row, built, expired=True)
            self.call('DC17', '过期结果不能上线', 'POST', f"/skills/developer/{row['id']}/publish", expected=409, boundary=True)
            self.sandbox_result(row, built)
            online = self.call('DC18', '当前版本成功后实际执行上线', 'POST', f"/skills/developer/{row['id']}/publish", boundary=True).json()['data']
            self.check('DC18', '状态持久化为已上线', online['status'] == '已上线')
            self.call('DC22', '已上线不能删除', 'DELETE', f"/skills/developer/{row['id']}", expected=400)
            row = self.save(row, boundary=True, description='已上线修改后返回草稿')
            self.check('DC19', '上线修改生成草稿', row['status'] == '草稿' and row['version'] == '1.0.3')
            self.sandbox_result(row, built)  # 旧构建的晚到结果必须留在旧版本。
            self.call('DC20', '旧构建成功不能让新版上线', 'POST', f"/skills/developer/{row['id']}/publish", expected=409, boundary=True)
            rebuilt = self.build(row)
            self.call('DC22', '调试中不能删除', 'DELETE', f"/skills/developer/{row['id']}", expected=400)
            self.sandbox_result(row, rebuilt)
            self.call('DC21', '新版再次上线', 'POST', f"/skills/developer/{row['id']}/publish", boundary=True)
            offline = self.call('DC21', '实际执行下线', 'POST', f"/skills/developer/{row['id']}/offline", boundary=True).json()['data']
            self.check('DC21', '下线状态', offline['status'] == '已下线')
            self.call('DC21', '重复下线拒绝', 'POST', f"/skills/developer/{row['id']}/offline", expected=400, boundary=True)
            row = self.save(row, boundary=True)
            self.call('DC22', '草稿真实软删除', 'DELETE', f"/skills/developer/{row['id']}")
            again = self.create(uploaded_resources=[resource])
            self.check('DC22', '已删除名称可以重新使用', again['id'] != row['id'])
            # 大小限制通过真实multipart流，不修改服务端阈值。
            limit = 50 * 1024 * 1024
            big = self.call('DC06', '单文件50MiB允许', 'POST', '/skills/developer/resources', data={'categories': '["参考资料"]'}, files={'files': (self.prefix + '-50MB.md', b'a' * limit)}).json()['data'][0]
            self.call('DC06', '单文件50MiB加1字节拒绝', 'POST', '/skills/developer/resources', expected=400, data={'categories': '["参考资料"]'}, files={'files': ('too-large.md', b'a' * (limit + 1))})
            self.call('DC06', '两个26MiB文件总量超限拒绝', 'POST', '/skills/developer/resources', expected=400, data={'categories': '["参考资料","参考资料"]'}, files=[('files', ('a.md', b'a' * (26 * 1024 * 1024))), ('files', ('b.md', b'a' * (26 * 1024 * 1024)))])
            # 从真实云库确认旧版未被覆盖、最新指针以及文件版本关联。
            current, _ = db_snapshot()
            forms = current['keenrobot_skill_forms']['rows']
            old = next(v for v in forms if v['id'] == first['skill_version_id'])
            self.check('DC11', '云库旧版本描述仍保留', old['description'] == self.base['description'])
            source_versions = [v for v in current['keenrobot_source_versions']['rows'] if v['source_id'] == resource['sourceId']]
            self.check('DC13', '云库文件两个版本及用途快照', len(source_versions) == 2 and len({v['source_type_id'] for v in source_versions}) == 2)
            unauth = httpx.get('http://127.0.0.1:8519/skills/developer/', trust_env=False)
            self.check('DC25', '直接无token访问被拒绝', unauth.status_code in (401, 422), unauth.status_code)
            invalid = httpx.get('http://127.0.0.1:8519/skills/developer/', headers={'token': 'invalid'}, trust_env=False)
            self.check('DC25', '无效token拒绝', invalid.status_code == 401, invalid.status_code)
            self.call('DC25', '不存在技能返回404', 'DELETE', '/skills/developer/wrq-not-existing', expected=404)
            self.blocked = [
                {'id': 'DC26', 'reason': '本次仅使用已有admin代理身份，没有第二个门户账号凭证；未写用户表创建第二个账号。跨用户权限仍需真实第二账号验证。'},
                {'id': 'DC27', 'reason': '云库缺少知识库业务表；没有创建或代替同事的知识库数据。正向挂载尚不能真实验收。'}]
            completed = True
        finally:
            if not completed:
                self.rows.append({'id': 'EXECUTION', 'case': '完整用例流程执行结束', 'passed': False, 'detail': '执行中断，已通过的子检查不能代替完整流程通过；请查看命令日志。'})
            cleanup_errors = []
            for skill_id in self.created:
                try:
                    rows = self.client.get('/skills/developer/').json()['data']
                    row = next((v for v in rows if v['id'] == skill_id), None)
                    if row:
                        if row['status'] != '草稿':
                            self.client.put('/skills/developer/' + skill_id, json=self.forms[skill_id] | {'expected_revision': row['current_revision']}).raise_for_status()
                        self.client.delete('/skills/developer/' + skill_id).raise_for_status()
                except Exception as exc:
                    cleanup_errors.append({'skill_id': skill_id, 'error': str(exc)[:200]})
            after, _ = db_snapshot()
            protected = sorted(set(before) - OWNED - LEGACY)
            unchanged = all(before[n]['hash'] == after[n]['hash'] and before[n]['ddl'] == after[n]['ddl'] for n in protected)
            active = [r['id'] for r in after['keenrobot_skills']['rows'] if r['id'] in self.created and r['state'] == 0]
            self.rows.append({'id': 'DC28', 'case': '保护同事表且清理活动测试草稿', 'passed': unchanged and not active and not cleanup_errors,
                'detail': {'protected_tables': protected, 'active_test_ids': active, 'cleanup_errors': cleanup_errors}})
            REPORT.write_text(json.dumps({'created_at': datetime.now().isoformat(), 'execution_completed': completed, 'cases': self.rows, 'blocked': getattr(self, 'blocked', []),
                'test_skill_ids': self.created, 'sandbox_boundary': '仅8521验收进程读取本地结果；未调用沙箱执行、未写同事结果表',
                'database_tls': tls, 'protected_unchanged': unchanged}, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            self.client.close(); self.boundary.close()
            print(json.dumps({'passed_checks': sum(r['passed'] for r in self.rows), 'checks': len(self.rows), 'report': str(REPORT)}, ensure_ascii=False))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    Acceptance().execute()
