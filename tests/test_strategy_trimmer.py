import ast
import asyncio
import copy
import itertools
import unittest
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, APIRouter
from starlette.staticfiles import StaticFiles

from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

import json
import tempfile
import os
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from applications.strategy_trimmer.models import TrimmerConfig, SystemAutomationAsset, MarkdownDocument
from applications.strategy_trimmer.services import init_trimmer_data
CATALOG = json.loads((Path(__file__).resolve().parents[1]/"applications/strategy_trimmer/catalog.json").read_text(encoding="utf-8"))
from trimmer_main import create_app

ROOT = Path(__file__).resolve().parents[1]


def payload():
    return {'reqId': 'REQ-001', 'name': '核心交易系统信创改造', 'duration': '6-15个工作日',
            'changes': ['database', 'middleware', 'os'],
            'systems': [{'name': '核心交易系统', 'testDept': '是'}],
            'functionDecisions': {}, 'nfDecisions': {}, 'toolChoices': {}, 'extraGates': [],
            'stakeholders': copy.deepcopy(CATALOG['stakeholders']), 'collabConfirmed': True}


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {'TRIMMER_DOCUMENT_DIR': self.directory.name+'/documents'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.database_url = 'sqlite://'+self.directory.name.replace('\\','/')+'/trimmer.sqlite3'
        self.client = TestClient(create_app(self.database_url))
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None,None,None))

    def generate(self, data):
        return self.client.post('/strategy-trimmer/generate', json=data)

    def test_catalog_matches_five_types_and_six_gates(self):
        response = self.client.get('/strategy-trimmer/catalog')
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(len(response.json()['data']['changeTypes']), 5)
        self.assertEqual(len(response.json()['data']['hardGates']), 6)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_output_matches_selected_decisions_and_all_six_chapters(self):
        data = payload()
        data['functionDecisions']['database'] = {'status':'裁剪', 'reason':'开发提供自检证据，测试经理确认'}
        data['nfDecisions']['os'] = {'status':'必测', 'reason':'必须覆盖主备切换'}
        data['toolChoices']['ai'] = {'decision':'不使用'}
        data['extraGates'] = [{'name':'报告完整', 'rule':'完整归档', 'kind':'硬性', 'checked':True}]
        response = self.generate(data)
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        result = response.json()['data']
        md = result['markdown']
        self.assertEqual(result['filename'], 'REQ-001-测试裁剪指引.md')
        self.assertEqual(md.count('\n## '), 6)
        self.assertIn('开发提供自检证据，测试经理确认', md)
        self.assertIn('必须覆盖主备切换', md)
        self.assertIn('报告完整', md)
        self.assertIn('终端 / 浏览器适配：未选择', md)
        self.assertNotIn(CATALOG['functional']['browser']['content'], md)
        self.assertIn('不使用', md)
        self.assertIn('增量代码覆盖率', md)

    def test_every_nonempty_change_combination_has_only_selected_rows(self):
        keys = [x[0] for x in CATALOG['changeTypes']]
        for size in range(1,6):
            for ids in itertools.combinations(keys,size):
                with self.subTest(ids=ids):
                    data = payload(); data['changes'] = list(ids)
                    md = self.generate(data).json()['data']['markdown']
                    for key in keys:
                        self.assertEqual(CATALOG['functional'][key]['content'] in md, key in ids)
                        self.assertEqual(CATALOG['nonfunctional'][key]['strategy'] in md, key in ids)

    def test_invalid_choices_and_confirmation_rejected(self):
        invalid = [
            {'changes':[]}, {'changes':['unknown']}, {'changes':['database','database']},
            {'name':'   '}, {'systems':[]}, {'collabConfirmed':False},
            {'functionDecisions':{'database':{'status':'裁剪','reason':'  '}}},
            {'nfDecisions':{'os':{'status':'裁剪','reason':''}}},
            {'functionDecisions':{'browser':{'status':'必测'}}},
            {'toolChoices':{'automation':{'decision':'未知'}}},
            {'extraGates':[{'name':'门禁','rule':'规则','kind':'硬性','checked':False}]},
            {'stakeholders':[]}, {'unexpected':'not accepted'},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                data = payload(); data.update(fields)
                body = self.generate(data).json()
                self.assertEqual(body['status'], 'failure')
                self.assertTrue(body['message'])

    def test_user_content_escaped_and_filename_sanitized(self):
        data = payload(); data['reqId'] = '../bad:*?'
        data['name'] = '<script>alert(1)</script> | #需求'
        data['functionDecisions'] = {'database':{'status':'裁剪', 'reason':'第一行 | 第二列\n<img src=x onerror=alert(1)>'}}
        result = self.generate(data).json()['data']
        self.assertNotIn('<script>', result['markdown'])
        self.assertNotIn('<img', result['markdown'])
        self.assertIn('\\|', result['markdown'])
        self.assertIn('<br>', result['markdown'])
        for char in '/:*?': self.assertNotIn(char, result['filename'])

    def test_no_selection_carries_over_between_requests(self):
        first = payload(); first['functionDecisions'] = {'database':{'status':'裁剪','reason':'独有备注'}}
        self.generate(first)
        second = self.generate(payload()).json()['data']['markdown']
        self.assertNotIn('独有备注', second)


def excel_fixture(rows, formula=False):
    # Change the provided template's XML for import test cases; retain its native validation/styles.
    template = ROOT / 'applications/strategy_trimmer/templates/system-automation-assets.xlsx'
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    output = BytesIO()
    with ZipFile(template) as source, ZipFile(output, 'w') as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                sheet = ET.fromstring(content)
                dimension=sheet.find(f'{{{ns}}}dimension')
                if dimension is None: dimension=ET.SubElement(sheet,f'{{{ns}}}dimension')
                dimension.set('ref',f'A1:B{len(rows)}')
                data = sheet.find(f'{{{ns}}}sheetData'); data.clear()
                for i, values in enumerate(rows, 1):
                    row = ET.SubElement(data,f'{{{ns}}}row',r=str(i))
                    for j,value in enumerate(values):
                        if value is None: continue
                        cell = ET.SubElement(row,f'{{{ns}}}c',r=f'{chr(65+j)}{i}',t='inlineStr')
                        if formula and i == 2 and j == 1:
                            cell.attrib.pop('t'); ET.SubElement(cell,f'{{{ns}}}f').text='1+1'
                        else:
                            ET.SubElement(ET.SubElement(cell,f'{{{ns}}}is'),f'{{{ns}}}t').text=str(value)
                content=ET.tostring(sheet,encoding='utf-8',xml_declaration=True)
            target.writestr(entry,content)
    return output.getvalue()


class DatabaseTests(GenerateTests):
    def upload(self, rows, **kwargs):
        return self.client.post('/strategy-trimmer/automation-assets/import',files={'file':('assets.xlsx',excel_fixture(rows,**kwargs),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).json()

    def test_config_loaded_from_database_and_seed_never_overwrites(self):
        async def update_config():
            record=await TrimmerConfig.get(key='strategy_catalog')
            record.value['functional']['database']['content']='数据库配置规则即时生效'
            record.version='db-v2'
            await record.save(); await init_trimmer_data()
        self.client.portal.call(update_config)
        catalog=self.client.get('/strategy-trimmer/catalog').json()['data']
        self.assertEqual(catalog['functional']['database']['content'],'数据库配置规则即时生效')
        result=self.generate(payload()).json()['data']
        self.assertIn('数据库配置规则即时生效',result['markdown'])
        self.assertEqual(result['configVersion'],'db-v2')

    def test_excel_upserts_and_generation_uses_database_assets(self):
        result=self.upload([['系统名称','接口/UI自动化'],['核心交易系统','无自动化资产'],['新业务系统','有自动化资产']])
        self.assertEqual(result['data'],{'total':2,'created':1,'updated':1})
        catalog=self.client.get('/strategy-trimmer/catalog').json()['data']
        self.assertEqual(catalog['systemAssets']['核心交易系统'],'无自动化资产')
        self.assertIn('新业务系统',catalog['systems'])
        md=self.generate(payload()).json()['data']['markdown']
        self.assertIn('| 核心交易系统 | 无自动化资产 | 是 |',md)
        data=payload(); data['systems'][0]['automation']='有自动化资产'
        self.assertEqual(self.generate(data).json()['status'],'failure')
        data=payload(); data['systems'][0]['name']='未配置的系统'
        self.assertEqual(self.generate(data).json()['status'],'failure')

    def test_import_invalid_batches_do_not_partially_update(self):
        for row in [['新系统','未知状态'],['核心交易系统','无自动化资产'],['','有自动化资产']]:
            response=self.upload([['系统名称','接口/UI自动化'],['核心交易系统','无自动化资产'],row])
            self.assertEqual(response['status'],'failure')
            self.assertEqual(self.client.get('/strategy-trimmer/catalog').json()['data']['systemAssets']['核心交易系统'],'有自动化资产')
        self.assertEqual(self.upload([['系统名称','接口/UI自动化'],['核心交易系统','有自动化资产']],formula=True)['status'],'failure')
        self.assertEqual(self.upload([['错误列','接口/UI自动化'],['核心交易系统','有自动化资产']])['status'],'failure')
        self.assertEqual(self.upload([['系统名称','接口/UI自动化']])['status'],'failure')
        self.assertEqual(self.upload([['系统名称','接口/UI自动化'],['核心交易系统','有自动化资产','多余字段']])['status'],'failure')
        for content,filename in [(b'broken','assets.xlsx'),(b'not xlsx','assets.xls'),(b'x'*(2*1024*1024+1),'large.xlsx')]:
            self.assertEqual(self.client.post('/strategy-trimmer/automation-assets/import',files={'file':(filename,content)}).json()['status'],'failure')

    def test_latest_by_id_or_name_downloads_exact_persisted_document(self):
        first=self.generate(payload()).json()['data']
        data=payload(); data['functionDecisions']={'database':{'status':'裁剪','reason':'最新版本备注'}}
        second=self.generate(data).json()['data']
        self.assertNotEqual(first['documentId'],second['documentId'])
        for criteria in [{'reqId':data['reqId']},{'name':data['name']},{'reqId':data['reqId'],'name':data['name']}]:
            latest=self.client.get('/strategy-trimmer/documents/latest',params=criteria).json()['data']
            self.assertEqual(latest['documentId'],second['documentId'])
            self.assertEqual(self.client.get(latest['downloadUrl']).text,second['markdown'])
        self.assertEqual(self.client.get(first['downloadUrl']).text,first['markdown'])
        for criteria in [{},{'reqId':'  '},{'reqId':'unknown'},{'reqId':data['reqId'],'name':'其他需求'}]:
            self.assertEqual(self.client.get('/strategy-trimmer/documents/latest',params=criteria).json()['status'],'failure')
        self.assertEqual(self.client.get('/strategy-trimmer/documents/unknown/download').json()['status'],'failure')
        path=Path(self.directory.name)/'documents'/f"{second['documentId']}.md"
        path.unlink()
        self.assertEqual(self.client.get(second['downloadUrl']).json()['status'],'failure')
        self.assertEqual(self.client.get('/strategy-trimmer/documents/latest',params={'reqId':data['reqId']}).json()['status'],'failure')

    def test_restart_keeps_mapping_and_documents(self):
        self.upload([['系统名称','接口/UI自动化'],['核心交易系统','无自动化资产']])
        document=self.generate(payload()).json()['data']
        self.client.__exit__(None,None,None)
        self.client=TestClient(create_app(self.database_url)); self.client.__enter__()
        self.assertEqual(self.client.get('/strategy-trimmer/catalog').json()['data']['systemAssets']['核心交易系统'],'无自动化资产')
        latest=self.client.get('/strategy-trimmer/documents/latest',params={'reqId':'REQ-001'}).json()['data']
        self.assertEqual(latest['documentId'],document['documentId'])
        self.assertEqual(self.client.get(latest['downloadUrl']).text,document['markdown'])

    def test_template_download_can_be_imported(self):
        response=self.client.get('/strategy-trimmer/automation-assets/template')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/strategy-trimmer/automation-assets/import',files={'file':('assets.xlsx',response.content)}).json()['status'],'success')

    def test_failed_index_insert_removes_generated_file(self):
        with patch.object(MarkdownDocument,'create',AsyncMock(side_effect=RuntimeError('模拟索引写入失败'))):
            with self.assertRaises(RuntimeError): self.generate(payload())
        self.assertEqual(list((Path(self.directory.name)/'documents').glob('*')),[])


def load_functions(relative_path, names, namespace):
    tree = ast.parse((ROOT / relative_path).read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.Module(body=functions,type_ignores=[]),relative_path,'exec'),namespace)
    return namespace


class ExistingMiddlewareTests(GenerateTests):
    def test_existing_router_registry_exposes_real_trimmer_endpoints(self):
        # Execute the existing registry, replacing only unrelated applications.
        tree = ast.parse((ROOT / 'core/initializations/app_initialization.py').read_text(encoding='utf-8'))
        registry = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'register_routers')
        unrelated = {}
        for node in ast.walk(registry):
            if isinstance(node,ast.ImportFrom) and node.module.startswith('applications.') and 'strategy_trimmer' not in node.module:
                module = ModuleType(node.module)
                for alias in node.names: setattr(module,alias.name,APIRouter())
                unrelated[node.module] = module
        fake_docs = SimpleNamespace(get_swagger_ui_html=SimpleNamespace(__kwdefaults__={}),get_redoc_html=SimpleNamespace(__kwdefaults__={}))
        config = SimpleNamespace(STATIC_DIR=str(ROOT/'static'),APP_OPENAPI_VERSION='3.0.2',APP_OPENAPI_JS_URL='',APP_OPENAPI_CSS_URL='',APP_OPENAPI_FAVICON_URL='')
        namespace = {'FastAPI':FastAPI,'StaticFiles':StaticFiles,'sys':SimpleNamespace(modules={'fastapi.openapi.docs':fake_docs}),
                     'PROJECT_CONFIG':config,'DependAuth':SimpleNamespace(dependency=lambda:None)}
        exec(compile(ast.Module(body=[registry],type_ignores=[]),'app_initialization.py','exec'),namespace)
        existing_app = FastAPI(lifespan=create_app(self.database_url).router.lifespan_context)
        with patch.dict('sys.modules',unrelated): namespace['register_routers'](existing_app)
        self.assertTrue(any(r.path == '/strategy-trimmer/catalog' for r in existing_app.routes))
        self.assertTrue(any(r.path == '/strategy-trimmer/automation-assets/import' for r in existing_app.routes))

    def test_original_audit_middleware_never_reads_or_persists_selection(self):
        # Run the production middleware function without importing the unrelated DB/LLM stack.
        namespace = load_functions('core/middlewares/app_middleware.py', ['logging_middleware'],
                                   {'Request':Request, 'Audit':SimpleNamespace(create=AsyncMock(side_effect=AssertionError('写入审计'))),
                                    'LOGGER':SimpleNamespace(info=lambda *args: self.fail('写入日志'))})
        async def verify():
            for path in ['/strategy-trimmer/generate','/strategy-trimmer/catalog','/strategy-trimmer/missing']:
                req = SimpleNamespace(url=SimpleNamespace(path=path), body=AsyncMock(side_effect=AssertionError('读取请求体')))
                call_next = AsyncMock(return_value=Response('ok',status_code=400))
                response = await namespace['logging_middleware'](req,call_next)
                call_next.assert_awaited_once_with(req)
                req.body.assert_not_awaited()
                self.assertEqual(response.headers['cache-control'],'no-store')
            namespace['Audit'].create.assert_not_awaited()
        asyncio.run(verify())

    def test_original_auth_keeps_import_protected_and_allows_document_reads(self):
        namespace = load_functions('core/middlewares/auth_middleware.py',
            ['_normalize_path','_rule_matches','_is_whitelisted','auth_middleware'],
            {'Iterable':list, 'Request':Request,
             'PROJECT_CONFIG':SimpleNamespace(APP_DOCS_URL='/docs',APP_REDOC_URL='/redoc',APP_OPENAPI_URL='/openapi_url'),
             'UnauthorizedResponse': lambda **kwargs: Response(status_code=401)})
        async def verify():
            for method,path,allowed in [('GET','/strategy-trimmer/catalog',True),('POST','/strategy-trimmer/generate',True),
                                        ('GET','/strategy-trimmer/documents/latest',True),
                                        ('GET','/strategy-trimmer/documents/abc/download',True),
                                        ('GET','/strategy-trimmer/automation-assets/template',True),
                                        ('POST','/strategy-trimmer/automation-assets/import',False),
                                        ('POST','/strategy-trimmer/catalog',False),('GET','/strategy-trimmer/generate',False),
                                        ('POST','/strategy-trimmer/anything',False),('GET','/user/list',False)]:
                req = SimpleNamespace(method=method,url=SimpleNamespace(path=path),headers={})
                response = await namespace['auth_middleware'](req,AsyncMock(return_value=Response('ok')))
                self.assertEqual(response.status_code,200 if allowed else 401)
        asyncio.run(verify())


if __name__ == '__main__':
    unittest.main()
