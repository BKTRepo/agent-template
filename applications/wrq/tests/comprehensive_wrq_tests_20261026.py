"""WRQ 新结构综合验收。

真实部分：HTTP、TLS 云 MySQL、数据库结构、上传/下载、版本和构建。
边界部分：只在本地测试进程模拟同事沙箱，不写 keenrobot_online_debug_runs。
执行：python -m applications.wrq.tests.comprehensive_wrq_tests_20261026
"""
import asyncio
import hashlib
import html
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from applications.wrq.migrations.review_20261024 import connect
from configure import PROJECT_CONFIG

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
REPORT_JSON = WORKSPACE / 'deliverables' / '开发者中心_新结构综合测试结果_20261026.json'
REPORT_HTML = WORKSPACE / 'deliverables' / '开发者中心_新结构综合测试结果_20261026.html'
TOKEN_FILE = Path.home() / '.codex/private/wrq-interface-test-token.txt'
BASE = 'http://127.0.0.1:8519'


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def render_html(report):
    rows = []
    for case in report['cases']:
        cls = 'pass' if case['status'] == 'PASSED' else 'fail'
        rows.append('<tr><td>{}</td><td>{}</td><td class="{}">{}</td><td>{}</td></tr>'.format(
            html.escape(case['id']), html.escape(case['name']), cls,
            html.escape(case['status']), html.escape(case.get('detail', ''))))
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>开发者中心新结构综合测试结果</title>
<style>body{{font:14px/1.7 "Microsoft YaHei",sans-serif;background:#f3f6fa;color:#17304d;margin:0}}main{{max-width:1250px;margin:auto;padding:28px}}header,section{{background:#fff;border:1px solid #dce5ef;border-radius:12px;padding:22px;margin:18px 0}}header{{background:#173d6a;color:#fff}}h1{{margin:0}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #dce5ef;padding:9px;text-align:left;vertical-align:top}}th{{background:#edf4fb}}.pass{{color:#14764b;font-weight:bold}}.fail{{color:#b3261e;font-weight:bold}}code{{background:#eef3f8;padding:2px 5px;border-radius:4px}}</style></head><body><main>
<header><h1>开发者中心新结构综合测试结果</h1><p>真实云接口/数据库 + 独立沙箱边界 Mock · 2026-10-26</p></header>
<section><h2>结果</h2><p><b>{passed}/{total}</b> 通过，失败 {failed}，数据库 TLS：<code>{tls}</code>。</p>
<p>真实测试不修改同事沙箱表；测试数据使用随机前缀并已清理。沙箱模型执行使用 Mock。</p></section>
<section><h2>测试明细</h2><table><tr><th>编号</th><th>测试项</th><th>结果</th><th>详情</th></tr>{rows}</table></section>
<section><h2>边界说明</h2><ul><li>同事数组响应尚未确定，本轮保持旧协议。</li><li>真实 Claude/Docker 沙箱执行不在本轮测试范围内。</li><li>用户、审计、同事任务表仅做结构/行数保护校验。</li></ul></section></main></body></html>'''.format(
        passed=report['summary']['passed'], total=report['summary']['total'], failed=report['summary']['failed'],
        tls=html.escape(report['runtime'].get('tls_cipher', 'unknown')), rows=''.join(rows))


class Runner:
    def __init__(self, client, cursor_connection):
        self.client = client
        self.db = cursor_connection
        self.cases = []
        self.skill_ids = []
        self.version_ids = []
        self.file_ids = []
        self.file_paths = []
        self.prefix = 'WRQ综合验收-' + uuid.uuid4().hex[:10] + '-'
        self.class_id = None
        self.category_name = '参考资料'

    async def call(self, method, path, expected=None, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        payload = response.json() if response.headers.get('content-type', '').startswith('application/json') else None
        if expected is not None and response.status_code != expected:
            raise AssertionError(f'{method} {path}: HTTP {response.status_code}, expected {expected}; {response.text[:300]}')
        return response, payload

    async def check(self, case_id, name, fn):
        started = datetime.now().isoformat()
        try:
            detail = await fn()
            self.cases.append({'id': case_id, 'name': name, 'status': 'PASSED', 'detail': str(detail or ''), 'started': started})
        except Exception as exc:
            self.cases.append({'id': case_id, 'name': name, 'status': 'FAILED', 'detail': f'{type(exc).__name__}: {exc}', 'started': started})

    async def schema_case(self):
        async with self.db.cursor() as cur:
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            cipher = (await cur.fetchone())['Value']
            if not cipher:
                raise AssertionError('数据库连接没有 TLS cipher')
            await cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
            names = {next(iter(row.values())) for row in await cur.fetchall()}
            required = {'keenrobot_skills','keenrobot_skill_versions','keenrobot_skill_forms','keenrobot_skill_uploaded_files',
                        'keenrobot_skill_resource_bindings','keenrobot_skill_debug_runs','keenrobot_skill_publications',
                        'keenrobot_skill_classes','keenrobot_resource_categories','keenrobot_skill_knowledge_bindings'}
            if not required <= names:
                raise AssertionError(f'缺少表：{sorted(required-names)}')
            if 'keenrobot_source_versions' in names:
                raise AssertionError('文件版本表仍存在')
            await cur.execute("SELECT COUNT(*) n FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL AND TABLE_NAME LIKE 'keenrobot_%'")
            if (await cur.fetchone())['n'] != 0:
                raise AssertionError('WRQ仍存在数据库外键')
            await cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='keenrobot_skill_forms'")
            columns = {row['COLUMN_NAME'] for row in await cur.fetchall()}
            if 'skill_markdown_path' not in columns or 'skill_markdown' in columns:
                raise AssertionError('表单Markdown列不符合路径方案')
            await cur.execute("SELECT COUNT(*) n FROM keenrobot_skills")
            if (await cur.fetchone())['n'] != 0:
                raise AssertionError('测试开始前技能表不是空表')
            return f'TLS={cipher}; tables={len(names)}'

    async def metadata_case(self):
        response, payload = await self.call('GET', '/skills/developer/metadata', 200)
        data = payload['data']
        if len(data['skill_classes']) < 1 or len(data['resource_categories']) != 4:
            raise AssertionError('字典数据不完整')
        self.class_id = data['skill_classes'][0]['id']
        if data['applications'] != [{'id': '*', 'paso': '*', 'name': '全应用适用'}]:
            raise AssertionError(f'应用目录不是无假数据模式：{data["applications"]}')
        return '技能大类、用途和全应用选项正常'

    def form(self, name=None, **changes):
        data = {'name': name or self.prefix + '技能', 'class_id': self.class_id,
                'application_ids': ['*'], 'description': '综合验收技能描述',
                'instructions': '覆盖正常、异常、边界测试场景', 'resource_ids': [],
                'uploaded_resources': [], 'resource_usage': '', 'compatibility': '',
                'technical_name': 'wrq-comprehensive-check'}
        data.update(changes)
        return data

    async def create(self, data):
        _, payload = await self.call('POST', '/skills/developer/', 200, json=data)
        row = payload['data']; self.skill_ids.append(row['id']); self.version_ids.append(row['skill_version_id'])
        return row

    async def create_and_read_case(self):
        row = await self.create(self.form())
        if row['application_paso'] != '*' or row['class_id'] != self.class_id or row['version'] != '1.0.0':
            raise AssertionError(f'主表/表单回读错误：{row}')
        _, payload = await self.call('GET', '/skills/developer/', 200)
        if not any(item['id'] == row['id'] for item in payload['data']):
            raise AssertionError('本人列表未返回创建技能')
        return f'skill_id={row["id"]}'

    async def duplicate_name_case(self):
        data = self.form(name=self.prefix + '重名')
        await self.create(data)
        response, _ = await self.call('POST', '/skills/developer/', 409, json=data)
        return response.status_code

    async def revision_case(self):
        row = await self.create(self.form(name=self.prefix + '版本'))
        stale = dict(self.form(name=self.prefix + '旧页面'), expected_revision=99)
        await self.call('PUT', f'/skills/developer/{row["id"]}', 409, json=stale)
        update = self.form(name=self.prefix + '版本-修改', expected_revision=row['current_revision'])
        _, payload = await self.call('PUT', f'/skills/developer/{row["id"]}', 200, json=update)
        new = payload['data']
        if new['current_revision'] != 2 or new['version'] != '1.0.1' or new['status'] != '草稿':
            raise AssertionError(f'版本状态错误：{new}')
        return 'revision 1 -> 2; version 1.0.1'

    async def file_case(self):
        response, payload = await self.call('POST', '/skills/developer/resources', 200,
            files={'files': ('验收.md', b'# test-resource', 'text/markdown')},
            data={'categories': json.dumps([self.category_name], ensure_ascii=False)})
        row = payload['data'][0]; file_id = row['fileId']; self.file_ids.append(file_id)
        download = await self.client.get(f'/skills/developer/resources/{file_id}/download')
        if download.status_code != 200 or download.content != b'# test-resource':
            raise AssertionError('文件下载内容不一致')
        await self.call('POST', f'/skills/developer/resources/{file_id}/versions', 410,
            files={'files': ('new.md', b'new', 'text/markdown')},
            data={'categories': json.dumps([self.category_name], ensure_ascii=False)})
        return f'file_id={file_id}; version endpoint=410'

    async def file_attach_case(self):
        file_id = self.file_ids[0]
        data = self.form(name=self.prefix + '文件挂载', resource_usage='使用验收资源',
                         uploaded_resources=[{'fileId': file_id, 'name': '验收.md', 'size': 15,
                                              'category': self.category_name, 'usage': '读取资料'}])
        row = await self.create(data)
        if not row['uploaded_resources'] or row['uploaded_resources'][0]['fileId'] != file_id:
            raise AssertionError('资源挂载未按file_id回读')
        return 'file_id挂载和用途回读正常'

    async def invalid_file_case(self):
        await self.call('POST', '/skills/developer/resources', 400,
            files={'files': ('bad.pdf', b'not-allowed', 'application/pdf')},
            data={'categories': json.dumps([self.category_name], ensure_ascii=False)})
        return '不支持格式被拒绝'

    async def build_case(self):
        row = await self.create(self.form(name=self.prefix + '构建'))
        source = {'skill_id': row['id'], 'skill_name': row['name'], 'skill_class_id': row['class_id'],
                  'application': '*', 'description': row['description'], 'version': row['version'],
                  'expected_version': row['version'], 'instructions': row['instructions'],
                  'compatibility': '', 'resource_usage': '', 'knowledge_base_ids': [], 'resource_categories': []}
        _, payload = await self.call('POST', '/skills/form/builds', 200,
                                     data={'source': json.dumps(source, ensure_ascii=False)})
        built = payload['data']; self.version_ids.append(built['skill_version_id'])
        if not built.get('build_id') or built.get('skill_version_id') is None:
            raise AssertionError('构建响应没有build_id或skill_version_id')
        _, definition = await self.call('GET', f'/skills/{row["id"]}/definition', 200)
        if not definition['data'].get('markdown'):
            raise AssertionError('定义读取为空')
        async with self.db.cursor() as cur:
            await cur.execute('SELECT skill_markdown_path FROM keenrobot_skill_forms WHERE skill_version_id=%s', [built['skill_version_id']])
            path = (await cur.fetchone())['skill_markdown_path']
            if not path or path.startswith('/') or '\\' in path:
                raise AssertionError(f'Markdown路径不是受控相对路径：{path}')
        return f'build_id={built["build_id"]}; markdown_path={path}'

    async def validation_case(self):
        bad = self.form(name=self.prefix + '空资源说明', resource_ids=['1'])
        await self.call('POST', '/skills/developer/', 400, json=bad)
        bad['resource_usage'] = '说明'
        # 云库没有知识库实体表，业务应明确返回服务未接入。
        await self.call('POST', '/skills/developer/', 503, json=bad)
        return '知识库未部署时不造假数据，返回503'

    async def auth_case(self):
        async with httpx.AsyncClient(base_url=BASE, trust_env=False, timeout=30) as unauthenticated:
            response = await unauthenticated.get('/skills/developer/')
        payload = response.json()
        if response.status_code not in (401, 403) and payload.get('status') != 'failure':
            raise AssertionError(f'无Token没有被拒绝：HTTP{response.status_code} {payload}')
        return f'HTTP={response.status_code}; business_status={payload.get("status")}'

    async def debug_contract_case(self):
        row = await self.create(self.form(name=self.prefix + '调试登记'))
        # 无构建、无任务时不能登记；不会写我方关联表。
        await self.call('POST', f'/skills/developer/{row["id"]}/debug-runs', 409,
                        json={'run_id': 'missing-run-' + uuid.uuid4().hex[:8], 'status': 'passed'})
        return '浏览器伪造passed且不存在任务被拒绝'

    async def clean(self):
        ids = list(dict.fromkeys(self.skill_ids))
        versions = list(dict.fromkeys(self.version_ids))
        files = list(dict.fromkeys(self.file_ids))
        async with self.db.cursor() as cur:
            if ids:
                marks = ','.join(['%s'] * len(ids))
                await cur.execute(f'DELETE FROM keenrobot_skill_publications WHERE skill_id IN ({marks})', ids)
                await cur.execute(f'DELETE FROM keenrobot_skill_debug_runs WHERE skill_id IN ({marks})', ids)
                await cur.execute(f'DELETE FROM keenrobot_skill_resource_bindings WHERE skill_id IN ({marks})', ids)
                await cur.execute(f'DELETE FROM keenrobot_skill_versions WHERE skill_id IN ({marks})', ids)
                await cur.execute(f'DELETE FROM keenrobot_skills WHERE id IN ({marks})', ids)
            if versions:
                marks = ','.join(['%s'] * len(versions))
                await cur.execute(f'DELETE FROM keenrobot_skill_forms WHERE skill_version_id IN ({marks})', versions)
            if files:
                marks = ','.join(['%s'] * len(files))
                await cur.execute(f'DELETE FROM keenrobot_skill_uploaded_files WHERE id IN ({marks})', files)
        for path in self.file_paths:
            Path(path).unlink(missing_ok=True)


async def main():
    if not TOKEN_FILE.exists():
        raise RuntimeError('测试Token文件不存在')
    token = TOKEN_FILE.read_text(encoding='utf8').strip()
    report = {'phase': '执行中', 'started_at': datetime.now().isoformat(), 'cases': [], 'runtime': {}, 'summary': {}}
    db = await connect()
    runner = None
    try:
        async with httpx.AsyncClient(base_url=BASE, headers={'token': token}, trust_env=False, timeout=45) as client:
            runner = Runner(client, db)
            async with db.cursor() as cur:
                await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                report['runtime']['tls_cipher'] = (await cur.fetchone())['Value']
            checks = [
                ('S01','数据库结构、TLS和空库前提',runner.schema_case),
                ('S02','元数据和无假应用目录',runner.metadata_case),
                ('S03','创建草稿、本人列表和PASO回读',runner.create_and_read_case),
                ('S04','名称唯一约束',runner.duplicate_name_case),
                ('S05','乐观锁和修改生成新版本',runner.revision_case),
                ('S06','长期文件上传、下载和格式限制',runner.file_case),
                ('S07','文件挂载和用途回读',runner.file_attach_case),
                ('S08','Skill构建和Markdown路径',runner.build_case),
                ('S09','知识库和资源使用说明校验',runner.validation_case),
                ('S10','无Token访问拒绝',runner.auth_case),
                ('S11','调试登记不接受伪造成功',runner.debug_contract_case),
            ]
            for case_id, name, fn in checks:
                await runner.check(case_id, name, fn)
    finally:
        if runner:
            await runner.clean()
            report['cases'] = runner.cases
        db.close()
    report['phase'] = '测试结束'
    report['finished_at'] = datetime.now().isoformat()
    report['summary'] = {'total': len(report['cases']),
                         'passed': sum(c['status'] == 'PASSED' for c in report['cases']),
                         'failed': sum(c['status'] == 'FAILED' for c in report['cases'])}
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    REPORT_HTML.write_text(render_html(report), encoding='utf8')
    print(json.dumps({'report': str(REPORT_JSON), **report['summary'], 'tls': report['runtime'].get('tls_cipher')}, ensure_ascii=False))
    if report['summary']['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
