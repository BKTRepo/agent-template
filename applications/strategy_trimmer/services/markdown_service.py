"""使用本次数据库配置快照渲染 Markdown。"""
import re

from ..schemas import GenerateRequest



def escape(value: object) -> str:
    # Escape user supplied HTML and Markdown, including table delimiters/newlines.
    value = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    value = re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', value)
    return value.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')


def table(headers, rows) -> str:
    lines = ['| ' + ' | '.join(escape(x) for x in headers) + ' |',
             '| ' + ' | '.join('---' for _ in headers) + ' |']
    lines.extend('| ' + ' | '.join(escape(x) for x in row) + ' |' for row in rows)
    return '\n'.join(lines)


def bullets(items) -> str:
    return '\n'.join('- ' + escape(x) for x in items)


def generate_markdown(request: GenerateRequest, catalog: dict) -> str:
    r = request
    parts = [f'# 《{escape(r.name)}测试裁剪指引》',
             '最终测试指引 · 待测试经理确认',
             f'本指引依据《信创项目测试指引{escape(catalog["version"])}》生成。最终范围、责任和例外结论由测试经理确认。',
             '## 一、需求分析工件',
             table(['需求编号', '需求名称', '测试周期'], [[r.reqId or '未填写', r.name, r.duration]]),
             '### 改造类型 / 信创技术栈勾选',
             '；'.join(escape(f'{title}：{"已选择" if key in r.changes else "未选择"}') for key, title, _ in catalog['changeTypes']),
             '### 涉及系统与自动化资产',
             table(['涉及系统', '接口/UI自动化', '是否测试部测试'],
                   [[s.name, catalog['systemAssets'][s.name], s.testDept] for s in r.systems])]
    for kind, title, decisions, field, entry, exit_ in (
        ('functional', '二、功能测试裁剪工件（参考 9.1）', r.functionDecisions, 'content', 'functionalEntry', 'functionalExit'),
        ('nonfunctional', '三、非功能测试裁剪工件（参考 9.2）', r.nfDecisions, 'strategy', 'nonfunctionalEntry', 'nonfunctionalExit'),
    ):
        rows = []
        for key in r.changes:
            item = catalog[kind][key]
            decision = decisions.get(key)
            status = decision.status if decision else ('必测' if kind == 'functional' else '条件测试')
            rows.append([item['title'], item[field], item['cut'], status,
                         decision.reason if decision and decision.reason else '无补充备注'])
        parts.extend([f'## {title}'])
        if kind == 'nonfunctional':
            parts.extend(['### 非功能测试准入确认', bullets(catalog[entry])])
        parts.append(table(['改造类型' if kind == 'functional' else '信创技术栈',
                            '测试要求' if kind == 'functional' else '测试要求 / 策略',
                            '裁剪明细', '裁剪结论', '备注'], rows))
        if kind == 'functional':
            parts.extend(['### 功能测试准入', bullets(catalog[entry])])
        parts.extend(['### 功能测试准出' if kind == 'functional' else '### 非功能测试准出', bullets(catalog[exit_])])
    parts.extend(['## 四、工具选择与能力描述（参考 9.3）',
                  table(['工具', '能力 / 适合场景', '使用前提', '建议介入时机', '输入', '输出', '是否采用'],
                        [[t['name'], t['scene'], t['pre'], t['when'], t['input'], t['output'],
                          r.toolChoices[t['id']].decision if t['id'] in r.toolChoices else '条件使用'] for t in catalog['tools']]),
                  '### 工具使用边界', bullets(catalog['toolBoundaries']),
                  '## 五、全部质量门禁指标',
                  table(['指标 / 条款', '计算方式或判定方式', '阈值 / 类型', '状态'],
                        [[g['name'], g['formula'], g['threshold'], '默认硬性门禁'] for g in catalog['hardGates']] +
                        [[g.name, g.rule, g.kind, '已确认' if g.checked else '未确认'] for g in r.extraGates]),
                  '6项默认硬性门禁不需要勾选，直接纳入最终指引；额外硬性条款需完成确认。',
                  '## 六、干系人和协作总结', '### 协作原则', bullets(catalog['principles']),
                  '### 干系人确认', table(['角色', '姓名 / 团队', '本需求承担事项'],
                                         [[s.role, s.name, s.duty] for s in r.stakeholders]),
                  '协作确认状态：已确认。'])
    return '\n\n'.join(parts) + '\n'


def download_filename(request: GenerateRequest) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', request.reqId or request.name).strip(' .')[:100]
    return f'{stem or "信创"}-测试裁剪指引.md'
