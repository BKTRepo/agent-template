"""Case workbook adapters; edits preserve the source workbook's layout."""

from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from applications.conversation.exceptions import ConversationBusinessError, TestCaseWorkbookFormatError
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field

CASE_SHEET = "测试案例"
STEP_SHEET = "操作步骤"
CASE_HEADER = ("案例编号", "场景分组", "案例名称", "前置条件", "预期结果")
STEP_HEADER = ("案例编号", "步骤编号", "操作内容", "本步骤预期结果")
MAX_ROWS = 5000
MAX_EXPANDED_BYTES = 64 * 1024 * 1024


class CaseStep(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    action: str = Field(max_length=8000)
    expected: str | None = Field(default=None, max_length=8000)


class TestCase(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    group: str = Field(max_length=128)
    name: str = Field(min_length=1, max_length=256)
    preconditions: str = Field(max_length=8000)
    steps: list[CaseStep] = Field(max_length=MAX_ROWS)
    expected: str | None = Field(default=None, max_length=8000)


def _bytes(book) -> bytes:
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def make_demo_workbook() -> bytes:
    book = Workbook()
    cases = book.active
    cases.title = CASE_SHEET
    cases.append(CASE_HEADER)
    steps = book.create_sheet(STEP_SHEET)
    steps.append(STEP_HEADER)
    samples = [
        ("正常流程", "资料完整，开户成功", "开户成功"),
        ("正常流程", "身份验证通过", "进入开户确认"),
        ("异常流程", "必填项缺失", "提示补填必填项"),
        ("异常流程", "证件号重复", "提示该证件已开户"),
        ("边界场景", "证件有效期当天到期", "按有效期边界规则校验"),
        ("边界场景", "姓名达到长度上限", "接受边界长度"),
    ]
    for index, (group, name, expected) in enumerate(samples, 1):
        key = f"CASE-{index:02}"
        cases.append((key, group, name, "进入信用卡开户页面", expected))
        steps.append((key, "1", "填写当前场景的开户资料", "显示已填写的资料"))
        steps.append((key, "2", "提交开户申请", expected))
    book.create_sheet("说明").append(("这是本地联调样例。",))
    return _bytes(book)


def _read_sheet(book, title, header):
    sheet = book[title]
    if sheet.max_row > MAX_ROWS + 1:
        raise ValueError("too many rows")
    rows = sheet.iter_rows(max_col=len(header), values_only=True)
    if next(rows) != header:
        raise ValueError("invalid header")
    return [(number, values) for number, values in enumerate(rows, 2) if any(value is not None for value in values)]


FLAT_HEADERS = {
    "id": {"用例编号", "案例编号", "case_id", "test_case_id"},
    "name": {"案例名称", "用例名称", "测试用例名称", "用例标题", "标题", "title", "name"},
    "preconditions": {"前置条件", "前提条件", "preconditions"},
    "steps": {"步骤", "操作步骤", "测试步骤", "操作内容", "steps"},
    "expected": {"预期结果", "预期", "expected", "expected_result"},
    "group": {"场景分组", "场景类型", "用例类型", "分组", "group"},
}


def _read_flat(book):
    for sheet in book.worksheets:
        if sheet.max_row > MAX_ROWS + 20:
            continue
        for header_row in sheet.iter_rows(max_row=min(sheet.max_row, 20)):
            columns = {}
            for field, aliases in FLAT_HEADERS.items():
                hits = [cell.column for cell in header_row if str(cell.value or "").strip() in aliases]
                if len(hits) == 1:
                    columns[field] = hits[0]
            if not {"id", "name", "preconditions", "steps", "expected"}.issubset(columns):
                continue
            cases, case_rows, step_rows = {}, {}, {}
            for number in range(header_row[0].row + 1, sheet.max_row + 1):
                def value(field):
                    return str(sheet.cell(number, columns[field]).value if sheet.cell(number, columns[field]).value is not None else "") if field in columns else ""
                key = value("id").strip()
                if not key:
                    continue
                if key in cases or sheet.cell(number, columns['id']).data_type == 'f':
                    raise ValueError("invalid case id")
                steps = [CaseStep(id=str(i), action=line) for i, line in
                         enumerate((line for line in value("steps").splitlines() if line.strip()), 1)]
                cases[key] = TestCase(id=key, name=value("name"), group=value("group"),
                    preconditions=value("preconditions"), expected=value("expected"), steps=steps)
                case_rows[key] = number
                step_rows.update({(key, step.id): number for step in steps})
            book._artifact_flat_layout = (sheet.title, columns)
            return book, cases, case_rows, step_rows
    raise ValueError("unsupported case workbook")


def read_workbook(content: bytes):
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ConversationBusinessError("工作簿解压后超过处理上限")
        book = load_workbook(BytesIO(content))
        if (CASE_SHEET not in book.sheetnames or STEP_SHEET not in book.sheetnames or
                tuple(cell.value for cell in book[CASE_SHEET][1][:len(CASE_HEADER)]) != CASE_HEADER):
            return _read_flat(book)
        cases = {}
        case_rows = {}
        for row, (key, group, name, preconditions, expected) in _read_sheet(book, CASE_SHEET, CASE_HEADER):
            case = TestCase(id=key, group=group or "", name=name, preconditions=preconditions or "",
                            expected=expected or "", steps=[])
            if key in cases:
                raise ValueError("duplicate case id")
            cases[key] = case
            case_rows[key] = row
        step_rows = {}
        for row, (case_id, key, action, expected) in _read_sheet(book, STEP_SHEET, STEP_HEADER):
            step = CaseStep(id=key, action=action or "", expected=expected or "")
            if (case_id, key) in step_rows:
                raise ValueError("duplicate step id")
            step_rows[case_id, key] = row
            cases[case_id].steps.append(step)
    except ConversationBusinessError:
        raise
    except Exception as exc:
        raise TestCaseWorkbookFormatError("无法识别测试案例表头，请使用案例编号、案例名称、操作步骤和预期结果列") from exc
    return book, cases, case_rows, step_rows


def workbook_detail(artifact, content: bytes) -> dict:
    book, cases, _, _ = read_workbook(content)
    book.close()
    return {
        "artifact_id": artifact.id, "name": artifact.name, "file_type": "xlsx",
        "is_test_case": True, "base_hash": sha256(content).hexdigest(),
        "cases": [case.model_dump() for case in cases.values()],
    }


def _write_text(sheet, row: int, column: int, value: str) -> None:
    cell = sheet.cell(row, column)
    if (cell.value or "") != value:
        cell.value = value
        cell.data_type = "s"


def update_workbook(content: bytes, updated: list[TestCase]) -> bytes:
    book, cases, case_rows, step_rows = read_workbook(content)
    try:
        kept_cases = {}
        kept_steps = {}
        for case in updated:
            if (case.id not in cases or case.id in kept_cases or
                    case.group != cases[case.id].group or not case.name.strip()):
                raise ConversationBusinessError("案例编号、分组或名称无效")
            kept_cases[case.id] = case
            for step in case.steps:
                key = (case.id, step.id)
                if key not in step_rows or key in kept_steps:
                    raise ConversationBusinessError("步骤编号无效")
                kept_steps[key] = step
        flat = getattr(book, '_artifact_flat_layout', None)
        if flat:
            sheet_name, columns = flat
            sheet = book[sheet_name]
            for key, case in kept_cases.items():
                for field in ('name', 'preconditions', 'expected', 'steps'):
                    if field in columns:
                        text = '\n'.join(step.action for step in case.steps) if field == 'steps' else getattr(case, field) or ''
                        _write_text(sheet, case_rows[key], columns[field], text)
            for row in sorted((row for key, row in case_rows.items() if key not in kept_cases), reverse=True):
                sheet.delete_rows(row)
            return _bytes(book)
        case_sheet = book[CASE_SHEET]
        step_sheet = book[STEP_SHEET]
        for key, case in kept_cases.items():
            row = case_rows[key]
            _write_text(case_sheet, row, 3, case.name)
            _write_text(case_sheet, row, 4, case.preconditions)
            _write_text(case_sheet, row, 5, case.expected or "")
        for key, step in kept_steps.items():
            row = step_rows[key]
            _write_text(step_sheet, row, 3, step.action)
            _write_text(step_sheet, row, 4, step.expected or "")
        for row in sorted((row for key, row in case_rows.items() if key not in kept_cases), reverse=True):
            case_sheet.delete_rows(row)
        for row in sorted((row for key, row in step_rows.items() if key not in kept_steps), reverse=True):
            step_sheet.delete_rows(row)
        return _bytes(book)
    finally:
        book.close()
