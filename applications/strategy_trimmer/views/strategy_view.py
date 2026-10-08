from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse

from core.responses import SuccessResponse, ParameterResponse, NotFoundResponse
from ..schemas import GenerateRequest, GenerateEnvelope
from ..services import get_catalog, download_filename, generate_markdown
from ..services.excel_import_service import import_assets, MAX_FILE_BYTES
from ..services.document_service import save_document, find_latest, document_path, metadata
from ..models import MarkdownDocument

strategy_trimmer_router = APIRouter()
HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}


@strategy_trimmer_router.get('/catalog', summary='读取数据库裁剪规则和系统资产关系')
async def catalog():
    try:
        response = SuccessResponse(data=await get_catalog())
    except ValueError as exc:
        response = ParameterResponse(message=str(exc))
    response.headers.update(HEADERS)
    return response


@strategy_trimmer_router.post('/generate', response_model=GenerateEnvelope, summary='根据选择生成 Markdown')
async def generate(request: GenerateRequest):
    rules = await get_catalog()
    missing = [system.name for system in request.systems if system.name not in rules['systemAssets']]
    if missing:
        return ParameterResponse(message='以下系统尚未配置自动化资产关系，请先导入：' + '、'.join(missing))
    markdown = generate_markdown(request, rules)
    record = await save_document(request, download_filename(request), markdown, rules['version'])
    response = SuccessResponse(data={**metadata(record), 'markdown': markdown})
    response.headers.update(HEADERS)
    return response


@strategy_trimmer_router.get('/automation-assets/template', summary='下载系统自动化资产 Excel 模板')
async def asset_template():
    path = Path(__file__).parent.parent / 'templates' / 'system-automation-assets.xlsx'
    return FileResponse(path, filename='系统自动化资产导入模板.xlsx',
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=HEADERS)


@strategy_trimmer_router.post('/automation-assets/import', summary='导入 Excel 并更新系统自动化资产关系')
async def asset_import(file: UploadFile = File(...)):
    try:
        if not file.filename or not file.filename.lower().endswith('.xlsx'):
            raise ValueError('请上传 .xlsx 格式的模板')
        content = await file.read(MAX_FILE_BYTES + 1)
        result = await import_assets(content)
        return SuccessResponse(message='系统自动化资产关系已更新', data=result)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))
    finally:
        await file.close()


@strategy_trimmer_router.get('/documents/latest', summary='按需求编号或名称查询最新 Markdown 文档')
async def latest_document(reqId: str | None = Query(default=None, max_length=100),
                          name: str | None = Query(default=None, max_length=200)):
    try:
        record = await find_latest(reqId, name)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))
    if record is None:
        return NotFoundResponse(message='没有找到匹配的 Markdown 文档')
    if document_path(record) is None:
        return NotFoundResponse(message='文档记录存在，但文件不可用，请重新生成')
    response = SuccessResponse(data=metadata(record))
    response.headers.update(HEADERS)
    return response


@strategy_trimmer_router.get('/documents/{document_id}/download', summary='下载已保存的 Markdown 文档')
async def download_document(document_id: str):
    record = await MarkdownDocument.get_or_none(document_id=document_id)
    path = document_path(record) if record else None
    if path is None:
        return NotFoundResponse(message='Markdown 文档不存在或文件不可用')
    return FileResponse(path, filename=record.filename, media_type='text/markdown; charset=utf-8', headers=HEADERS)
