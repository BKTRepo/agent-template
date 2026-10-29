"""先定义验收要求，再运行；沙箱状态/结果为测试边界，不写同事任务表。"""
from html import escape
import json
from pathlib import Path

DEFINITIONS = [
    ('B01','真实准备技能及构建','新建草稿并构建','主表、版本、表单及真实ZIP一致'),
    ('B02','任务创建即登记','沙箱返回queued；提交run_id与build_id，不传status','数据库立即保存准确版本和清单摘要'),
    ('B03','重复登记幂等','重复提交相同任务','只有一条关联，首次输入不被覆盖'),
    ('B04','重新连接恢复任务','关闭HTTP连接，再查询登记任务','任务编号、版本、queued状态可找回'),
    ('B05','运行中状态恢复','沙箱变为running，再查询任务和技能列表','状态来自沙箱，关联版本保持不变'),
    ('B06','未完成不得上线','queued/running时申请上线','返回409，未启用，无上线历史'),
    ('B07','失败原因可查询','沙箱变为failed并返回错误原因','恢复接口和技能列表显示失败原因'),
    ('B08','前端伪造通过无效','failed时登记status=passed并申请上线','仍不允许上线，不伪造成功记录'),
    ('B09','失败后重新测试','创建新的queued任务并登记同一版本','新旧任务均保留，不覆盖失败任务'),
    ('B10','成功后真实上线','新任务completed，申请上线','主表状态、启用标记、时间及版本历史一致'),
    ('B11','重复上线幂等','对已上线技能再次上线','不重复写上线历史'),
    ('B12','下线及重新上线','上线后下线，再使用同版有效通过记录上线','状态、启用、时间及历史一致'),
    ('B13','上线后修改回草稿','修改指令并保存','生成新版本，清除当前通过标记，保留旧内容和历史'),
    ('B14','旧结果不能证明新版通过','找回旧成功任务并申请新版上线','is_current_version=false；上线409'),
    ('B15','旧任务不得改绑新版','用旧run_id提交新build_id','409，原关联不变'),
    ('B16','迟到登记准确保存旧版','新版已构建，才登记原来执行的旧build_id','仍关联旧版，不改变当前版本、状态及通过标记'),
    ('B17','新版排队任务不能借用旧结果','新版queued任务登记后申请上线','409，不引用旧版成功结果'),
    ('B18','新版重新通过后上线','新版任务completed后申请上线','只使用新版的任务、版本及构建'),
    ('B19','过期结果不得上线','同版本成功任务已过expires_at','409，不写上线历史'),
    ('B20','错误任务与构建拒绝','提交不存在任务、其他技能任务、未知构建及缺少版本依据','拒绝请求，不新增错误关联'),
    ('B21','输入边界校验','文档数量11、负数、空run_id','422，不写入数据库'),
    ('B22','版本依据冲突拒绝','build_id与skill_version_id指向不同版本','409，不创建错误关联'),
    ('B23','越权操作拒绝','另一个真实签名测试身份查询、登记、上线、修改及删除','404且数据不变，不创建用户表'),
    ('B24','并发登记唯一','同时登记同一个queued任务','至多一条关联；冲突后原编号可重试'),
    ('B25','当前版本删除规则','调试中删除应失败；修改回草稿后删除并重用名称','只软删除草稿，旧版本和任务可追溯'),
    ('F01','前端使用新建任务接口','实际runRealtimeDebug调用仅提供四个新接口的测试沙箱','调用POST /runs，不调用旧/generate'),
    ('F02','前端运行开始登记','实际前端登记函数收到runId及running状态','任务完成前已发送登记请求并保存版本'),
    ('F03','前端终态登记到真实数据库','实际前端函数登记completed对应的passed结果','后端真实校验沙箱状态并写关联'),
    ('F04','前端结果文件下载','实际下载函数请求completed任务的Excel','真实HTTP字节与有效测试Excel一致'),
    ('F05','前端上线调用真实后端','实际前端上线函数调用真实接口','服务器与云库均变为已上线'),
    ('F06','前端下线调用真实后端','实际前端下线函数调用真实接口','服务器与云库均变为已下线'),
    ('F07','前端修改与旧结果失效','重新上线后用实际前端函数修改，再申请上线','新版本草稿；旧成功不能再次上线'),
    ('F08','未完成文档不可下载','实际前端下载函数请求queued任务','显示未完成错误，不保存伪结果'),
    ('F09','前端找回旧任务的版本校验','新版保存后通过latest-run恢复旧版完成任务','查询真实版本关联；isCurrentVersion=false，不为新版补登记'),
    ('F10','关闭查询后恢复原任务','创建排队任务并登记后停止前端查询，再重新找回','只创建一次；后台任务继续，原版本关联不丢失'),
    ('D01','清理与数据保护','清理本轮唯一前缀的数据及临时文件','既有业务行、同事任务表及表结构不变'),
    ('X01','完整项目鉴权可用性','检查整项目公共鉴权所需表及真实服务文档','缺表时明确阻塞，不绕过公共鉴权算通过'),
]


def cases():
    return [{'id':i,'name':n,'steps':s,'expected':e,'status':'PENDING','detail':''}
            for i,n,s,e in DEFINITIONS]


def save_report(path: Path, report: dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    esc=lambda v:escape(str(v))
    rows=''.join('<tr>'+''.join(f'<td>{esc(row.get(k,""))}</td>' for k in
        ('id','name','steps','expected','status','detail'))+'</tr>' for row in report['cases'])
    counts={status:sum(row['status']==status for row in report['cases'])
            for status in ('PASSED','FAILED','BLOCKED','PENDING')}
    notes=''.join(f'<li>{esc(note)}</li>' for note in report.get('notes',[]))
    path.write_text('<!doctype html><meta charset="utf-8"><title>开发者中心调试后续流程验收</title>'
        '<style>body{font:15px/1.6 "Microsoft YaHei",sans-serif;margin:30px;color:#20314a}'
        'table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd5df;padding:9px;vertical-align:top}'
        'th{background:#eaf1fa}td:first-child{white-space:nowrap}pre{white-space:pre-wrap}</style>'
        '<h1>开发者中心：沙箱之后的真实流程测试</h1>'
        f'<p>运行状态：{esc(report.get("phase","编写用例"))}；统计：{esc(counts)}</p>'
        f'<ul>{notes}</ul><p>前端F01、F02失败时，表示当前实现尚未满足新流程，不修改用例让其通过。</p>'
        '<table><thead><tr><th>编号</th><th>测试项</th><th>操作</th><th>期望</th><th>结果</th><th>证据/说明</th></tr></thead>'
        f'<tbody>{rows}</tbody></table><h2>执行信息</h2><pre>{esc(json.dumps(report.get("runtime",{}),ensure_ascii=False,indent=2,default=str))}</pre>',encoding='utf8')
