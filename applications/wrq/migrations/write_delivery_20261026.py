"""由实际迁移/测试记录生成交付说明；不连接数据库，不包含凭证内容。"""
import html
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from applications.wrq.migrations.schema_20261026 import TABLES

ROOT=Path(__file__).resolve().parents[3].parent
DEST=ROOT/'deliverables'
NAME='开发者中心_按13表基线的11项调整方案_20261026'
REPORT='开发者中心_数据库与后端实施结果_20261026'

def esc(v):return html.escape(str(v))
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table>'

def run():
    live=json.loads((DEST/'开发者中心_数据库与后端验收_20261026.json').read_text('utf8'))
    suites=list(ET.parse(ROOT/'.tmp/wrq-unit-review26.xml').getroot().iter('testsuite'))
    unit={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert not unit['failures'] and not unit['errors'] and live['error'] is None and live['cleanup_completed']
    folder=ROOT/'.tmp/wrq-db-backups/20261026T025625Z-review26'
    migration=json.loads((folder/'report.json').read_text('utf8'))
    identity_report=sorted((Path.home()/'.codex/private/wrq-backups').glob('*-identity/report.json'))[-1]
    identity=json.loads(identity_report.read_text('utf8'))
    assert set(identity['drop_tables'])=={'keenrobot_user','keenrobot_applications'}
    data={'date':'2026-10-26','status':'database_backend_applied','code_directory':'agent-template-master-latest/applications/wrq',
        'unit_tests':unit,'live_api_checks':live['passed'],'live_skipped':live['skipped'],
        'sandbox_execution':'仅独立测试进程模拟执行边界；同事的真实结果表只读兼容检查通过',
        'frontend':'本次未改旧generate流程；创建/轮询/找回的前端切换待单独对接',
        'local_identity_tables_deleted':identity['drop_tables'],'input_document_table_deleted':True,
        'peer_task_table':'keenrobot_online_debug_runs保持原表原数据，不合并不删除',
        'authentication':'JWT签名/有效期/用户编号验证，不查询用户表；不做历史用户衔接',
        'applications':'暂未接外部目录；仅全应用适用；已有业务记录的应用编号不丢弃',
        'token_file':str(Path.home()/'.codex/private/wrq-interface-test-token.txt'),
        'backend_url':'http://127.0.0.1:8519','backup':str(folder),'identity_backup':identity['backup'],
        'schema':{n:{'comment':c,'fields':[{'name':f,'type':t,'comment':d} for f,t,d in fields]} for n,(c,fields,_) in TABLES.items()},
        'existing_rows_preserved':migration['target_counts'],'live_test_data_cleaned':live['cleanup_completed'],
        'legacy_extra_tables':'sources与skill_knowledge_bindings旧数据保留备查；新写入使用规范后的文件/挂载表'}
    (DEST/(REPORT+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    sections=['<h1>开发者中心：数据库与后端实施结果</h1>',
        '<p><b>2026-10-26 · 数据库与后端已实施，服务已启动。</b>本说明替代旧方案中关于用户/应用表保留、沙箱结果表合并的说法。</p>',
        '<div class="notice">代码位于 applications/wrq/。自建用户表、应用表及临时调试输入文档表已备份后删除。鉴权验证已有平台JWT，不查本地用户表。同事的任务表保持不变。</div>',
        '<h2>可以直接测试</h2><p>后端文档：<a href="http://127.0.0.1:8519/docs">http://127.0.0.1:8519/docs</a>。在接口的 token 请求头粘贴本机私有文件中的凭证；也支持 Bearer 方式。</p>',
        '<p>Token本机文件：'+esc(data['token_file'])+'。本页面不包含凭证内容。目前先用“全应用适用”，不接平台用户资料或应用目录，不做历史用户衔接。</p>',
        '<h2>验证结果</h2>'+table(['项目','实际结果'],[
            ('隔离测试',str(unit['tests'])+'项通过；失败/错误均为0'),('真实云库接口检查',str(live['passed'])+'项通过，'+str(live['skipped'])+'项跳过'),
            ('真实执行部分','JWT鉴权、HTTP路由、云库事务、并发/外键、上传下载、真实Skill构建与上下线'),
            ('沙箱范围',data['sandbox_execution']),('测试清理','本次UUID标识的测试记录及文件已清理；原有数据哈希核对通过'),
            ('自动迁移','保持关闭；本次使用显式迁移，不在启动时改表')]),
        '<h2>已完成的关键行为</h2><ul><li>版本表10字段元数据，表单10字段正文；同版本内容不双写，44份历史版本保留。</li><li>保存技能/表单/版本/挂载同一事务；旧修订保存返回409，MySQL复合外键约束版本归属和修订一致。</li><li>来源source_type与用途category_id分开；用途四类编号保留。文件14字段及文件版本14字段保留真实元数据与SHA256。</li><li>上线/下线状态、启用标志、时间及历史同事务保存；上线后修改回草稿，旧版本通过结果不能用于新版上线。</li><li>任务关联表13字段，保存版本/构建/输入及同事表没有的既有信息；执行状态、文件位置、执行时间只从同事表读取。</li></ul>',
        '<h2>任务版本登记接口</h2>'+table(['用途','接口','规则'],[
            ('任务创建后立即登记','POST /skills/developer/{skill_id}/debug-runs','run_id + 本次实际build_id；无需status，queued/running即可登记'),
            ('兼容旧入口','POST /skills/developer/{skill_id}/debug-result','仍可调用；浏览器passed不作为成功依据'),
            ('核对找回的任务版本','GET /skills/developer/{skill_id}/debug-runs/{run_id}','返回skill_version_id、version、build_id、is_current_version；旧任务不能认定新版通过')]),
        '<p>重复登记相同任务关联幂等，改绑其它版本返回409。登记失败使用原run_id补登记，不重复创建任务。同事四个创建/轮询/找回/下载接口不改。本次前端旧generate流程尚未切换。</p>',
        '<h2>表与现存数据</h2>'+table(['表','字段数','迁移后保留记录','作用'],[(n,len(d['fields']),migration['target_counts'][n],d['comment']) for n,d in data['schema'].items()]),
        '<p>技能大类表原3字段、6条目录保留。sources、skill_knowledge_bindings两张旧精简方案额外表的数据保留备查；新业务使用规范后的文件和资源关联表，不继续向旧表写入。</p>',
        '<h2>备份与边界</h2><p>结构/业务迁移备份：'+esc(folder)+'。</p><p>已删除自建账号/应用表的全量备份在用户私有目录：'+esc(identity['backup'])+'；账号数据不写入交付页面。</p>',
        '<p>审计表、aerich及同事任务表在迁移与测试前后结构、数据哈希均保持；未修改同事代码。当前只覆盖开发者中心，不宣称其它业务模块或真实模型执行已验收。</p>',
        '<h2>当前自有表字段</h2>']
    for n,d in data['schema'].items():
        sections.append('<h3>'+esc(n)+'</h3>'+table(['字段','类型','含义'],[(r['name'],r['type'],r['comment']) for r in d['fields']]))
    style='body{font:15px/1.75 "Microsoft YaHei",sans-serif;color:#18314f;background:#f4f7fb;margin:0}main{max-width:1200px;margin:24px auto;padding:30px;background:white}h1{font-size:27px}h2{margin-top:32px;font-size:21px;border-bottom:1px solid #dbe4ef}h3{font-size:17px;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;margin:14px 0}th,td{border:1px solid #dbe4ef;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#edf4fc}.notice{padding:16px;border-left:4px solid #2775dc;background:#edf5ff}a{color:#1465c7}li{margin:8px 0}@media(max-width:700px){main{padding:14px}table{font-size:12px}}'
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WRQ数据库与后端实施结果</title><style>'+style+'</style><main>'+''.join(sections)+'</main></html>'
    (DEST/(REPORT+'.html')).write_text(document,encoding='utf8')
    archive=ROOT/'.tmp/plan-revisions/20261026-before-final-delivery'; archive.mkdir(parents=True,exist_ok=True)
    for suffix in ('.html','.json'):
        p=DEST/(NAME+suffix)
        if p.exists() and not (archive/p.name).exists():shutil.copy2(p,archive/p.name)
    plan_path=DEST/(NAME+'.json'); plan=json.loads(plan_path.read_text('utf8'))
    plan.update(revision='v3_按最新职责边界实施',status='database_backend_applied',implementation_report=REPORT+'.html')
    plan['explicit_drop_tables']={n:'已备份并删除本模块自建表' for n in ('keenrobot_user','keenrobot_applications','keenrobot_skill_debug_documents')}
    for r in plan['requirements']:
        if r[0]=='1':r[1:]=['删除自建用户表，验证平台JWT','已删除；签名/有效期/用户编号由applications/wrq/auth.py验证；不查用户表，不做历史用户衔接。']
        if r[0]=='2':r[1:]=['删除自建应用表','已删除；目前暂不接外部目录，仅全应用适用；既有业务记录的应用编号保留。']
        if r[0]=='10':r[1:]=['保留同事结果表，只登记版本关联','按用户最新要求不合并、不要求同事换表。我们的关联表13字段保留输入及非重叠历史信息，任务开始即可登记。']
    peer_mapping={'status':'status','result_storage_key':'result_file_path','result_file_name':'result_file_name',
                  'error_message':'error_message','started_at':'started_at','finished_at':'finished_at'}
    for row in plan['field_manifest']:
        if row['table']=='keenrobot_online_debug_runs':row.update(action='保留同事表，只读',plan='按最新要求不合并、不删除、不修改；状态和结果以此表为准。')
        if row['table']=='keenrobot_skill_debug_runs' and row['field'] in peer_mapping:
            row.update(action='去重复用同事结果',plan='执行信息读取keenrobot_online_debug_runs.'+peer_mapping[row['field']]+'，不在我方重复保存。历史迁移前数据已有备份。')
    plan['actual_schema']=data['schema']; plan['test_results']={'unit':unit,'live_passed':live['passed'],'live_skipped':live['skipped']}
    plan['authentication']=data['authentication']; plan['frontend_status']=data['frontend']
    plan['additions']['keenrobot_skill_debug_runs']=[]
    for r in plan.get('consistency_rules',[]):
        if r[0]=='C08':r[2]='我方只写任务版本关联和输入等元数据；执行状态、结果位置、失败原因及时间只读同事表，不要求其切换读写，不保存两份状态。'
    for r in plan.get('acceptance',[]):
        if r[0]=='T02':r[1:] = ['JWT身份','已验证签名、有效期、用户编号及令牌内状态；无本地用户表仍可访问开发者中心。暂不做跨平台用户资料接入。']
        if r[0]=='T03':r[1:] = ['应用目录边界','自建应用表已删除；暂不接外部目录，仅全应用适用用于当前测试，旧业务应用编号保留。']
        if r[0]=='T09':r[1:] = ['任务关联去重','我方关联表13字段保存版本/构建/输入及非重叠历史信息；不合并、删除或写入同事结果表。']
        if r[0]=='T10':r[1:] = ['接口对接范围','后端开始登记及版本核对已验收；前端旧generate尚未切换，真实模型执行本次不验收。']
        if r[0]=='T12':r[1:] = ['最终删除及注释','自建用户/应用/临时调试文档3张表已删除；同事任务表保留；自有目标表列有COMMENT，自动迁移关闭。']
    plan['new_forms']=[(x['name'],x['comment']) for x in data['schema']['keenrobot_skill_forms']['fields']]
    plan['version_metadata']=[(x['name'],x['comment']) for x in data['schema']['keenrobot_skill_versions']['fields']]
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
    # 用户原来打开的方案地址直接显示现行实施版，避免继续看到旧删表步骤。
    (DEST/(NAME+'.html')).write_text(document,encoding='utf8')
    after=json.loads((folder/'after.json').read_text('utf8'))
    sql='-- 2026-10-26 已实施结构快照；仅备查，不是可重复执行的迁移。\n'
    sql+='\n\n'.join(after[n]['ddl']+';' for n in list(TABLES)+['keenrobot_skill_classes'])
    (DEST/'开发者中心_WRQ已实施结构_20261026.sql').write_text(sql,encoding='utf8')
    print(json.dumps({'report':str(DEST/(REPORT+'.html')),'unit_passed':unit['tests'],'live_passed':live['passed'],'schema_tables':len(TABLES)},ensure_ascii=False))

if __name__=='__main__':run()
