"""Export the existing overview detail facts as a downloadable Excel workbook."""
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from . import overview_facts as facts

EXCEL_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MAX_DATA_ROWS = 1_048_575
PERIOD_METRICS = frozenset({'active_users', 'test_artifacts', 'new_skills', 'new_knowledge_bases'})
USER_COLUMNS = [('department', '部门'), ('username', '用户名'), ('employee_no', '用户工号')]
SKILL_COLUMNS = [('name', 'Skill 名称'), ('skill_class_name', '所属技能大类'), ('application_name', '所属应用')]
STATE_COLUMNS = [('version', '线上版本号'), ('status', '当前状态', 'status')]
METRICS = {
    'connected_users': ('用户接入数量', [*USER_COLUMNS, ('first_access_at', '首次接入时间', 'time'),
        ('last_login_at', '最近登录时间', 'time'), ('login_count', '累计登录次数')]),
    'online_skills': ('在册 Skill 总数', [*SKILL_COLUMNS, ('published_at', '上线时间', 'time'),
        *STATE_COLUMNS, ('call_count', '累计调用次数'), ('last_called_at', '最近调用时间', 'time')]),
    'skill_calls': ('技能被调用次数', [('skill_name', 'Skill 名称'), ('operator_login_name', '操作人工号'),
        ('called_at', '调用时间', 'time')]),
    'knowledge_mounts': ('知识库被挂载次数', [('knowledge_base_name', '知识库名称'), ('knowledge_base_version', '知识库版本'),
        ('target_name', '挂载目标名称'), ('operator_login_name', '操作人工号'), ('mounted_at', '挂载时间', 'time')]),
    'active_users': ('活跃用户数', [*USER_COLUMNS, ('conversation_call_count', '智能对话调用次数'),
        ('first_called_at', '首次调用时间', 'time'), ('last_called_at', '近期调用时间', 'time')]),
    'test_artifacts': ('AI 辅助测试产出物', [('generated_at', '产出时间', 'time'), ('employee_no', '用户工号'),
        ('department', '所属部门'), ('artifact_type', '产出物类型'), ('skill_name', 'Skill 名称'),
        ('artifact_count', '产出物数量'), ('duration_ms', '生成耗时（分钟）', 'minutes'), ('status', '生成状态', 'status')]),
    'new_skills': ('新增技能数', [*SKILL_COLUMNS, ('created_time', '创建时间', 'time'),
        ('creator_login_name', '创建人工号'), *STATE_COLUMNS]),
    'new_knowledge_bases': ('新增知识库数', [('name', '知识库名称'), ('application_name', '所属应用'),
        ('creator_login_name', '创建人工号'), ('created_time', '创建时间', 'time'), ('version', '当前版本号'),
        ('file_count', '文件数量'), ('updated_at', '最近维护时间', 'time')]),
}
STATUS_NAMES = {'ONLINE': '已上线', 'OFFLINE': '已下线', 'DRAFT': '草稿', 'DEBUGGING': '调试中',
                'DEBUG_SUCCESS': '调试成功', 'DEBUG_FAILED': '调试失败', 'success': '成功', 'failed': '失败'}


async def export_rows(metric, start, end):
    if metric not in METRICS:
        raise DeveloperError('不支持的总览指标', 422)
    result = await facts.detail(metric, start, end, 1, MAX_DATA_ROWS)
    if result['total'] > MAX_DATA_ROWS:
        raise DeveloperError('明细超过 Excel 单表行数上限，请缩小日期范围后导出', 422)
    if len(result['items']) != result['total']:
        raise DeveloperError('明细数据发生变化，请重试导出', 409)
    return result['items']


def _value(value, kind):
    if kind == 'minutes' and isinstance(value, (int, float)):
        return value / 60_000
    if kind == 'status':
        value = STATUS_NAMES.get(value, value)
    if kind == 'time' and value:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                pass
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = value.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    return value


def workbook_bytes(metric, rows):
    title, columns = METRICS[metric]
    book = Workbook(write_only=True)
    try:
        sheet = book.create_sheet(title)
        sheet.freeze_panes = 'A2'
        header = []
        for index, (_, label, *_) in enumerate(columns, 1):
            cell = WriteOnlyCell(sheet, label)
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='EAF0FA')
            header.append(cell)
            sheet.column_dimensions[get_column_letter(index)].width = 24 if '时间' in label else 22
        sheet.append(header)
        count = 0
        for row in rows:
            cells = []
            for key, _, *options in columns:
                kind = options[0] if options else None
                value = _value(row.get(key), kind)
                if isinstance(value, str):
                    value = ILLEGAL_CHARACTERS_RE.sub('', value)
                cell = WriteOnlyCell(sheet, value)
                if isinstance(value, str):
                    cell.data_type = 's'  # Names/employee IDs remain text, including leading zeroes and '='.
                elif isinstance(value, datetime):
                    cell.number_format = 'yyyy/mm/dd hh:mm:ss'
                elif kind == 'minutes' and isinstance(value, (int, float)):
                    cell.number_format = '0.00'
                cells.append(cell)
            sheet.append(cells)
            count += 1
        sheet.auto_filter.ref = f'A1:{get_column_letter(len(columns))}{count + 1}'
        with BytesIO() as output:
            book.save(output)
            return output.getvalue()
    finally:
        book.close()
