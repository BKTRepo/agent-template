# -*- coding: utf-8 -*-
import time
from io import BytesIO
from typing import Dict, Any, Optional
from urllib.parse import unquote

import orjson
from fastapi import Request, Response
from starlette.datastructures import FormData

from applications.base.models.audit_model import Audit
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG, GLOBAL_CONFIG, LOGGER, ROUTER_SUMMARY, ROUTER_TAGS
from services import AuthControl, CTX_USER_ID

LOGIN_ACCESS_TOKEN_PATH = "/base/auth/access_token"


def is_upload_request(request: Request) -> bool:
    """判断当前请求是否为文件上传请求（multipart/form-data 或路径含 upload）。

    :param request: FastAPI/Starlette 请求对象。
    :returns: 是上传请求返回 True，否则 False。
    """
    path: str = request.url.path.lower()
    content_type: str = request.headers.get("content-type", "")
    return "multipart/form-data" in content_type.lower() or path.startswith("upload") or path.endswith("upload")


def is_html_response(response: Response) -> bool:
    """判断响应是否为 HTML 或 XML 文本类型。

    :param response: 响应对象。
    :returns: Content-Type 含 text/html 或 application/xml 时返回 True。
    """
    content_type: str = response.headers.get("content-type", "")
    return "text/html" in content_type.lower() or "application/xml" in content_type.lower()


def is_image_response(response: Response) -> bool:
    """判断响应是否为图片类型。

    :param response: 响应对象。
    :returns: Content-Type 含 image 时返回 True。
    """
    content_type: str = response.headers.get("content-type", "")
    return "image" in content_type.lower()


def is_download_response(response: Response) -> bool:
    """判断响应是否为附件下载（Content-Disposition 含 attachment）。

    :param response: 响应对象。
    :returns: 为附件下载时返回 True。
    """
    content_disposition: str = response.headers.get("content-disposition", "")
    return "attachment" in content_disposition.lower()


def is_longtext_response(response: Response) -> bool:
    """判断响应体是否超过 102400 字节（用于决定是否截断审计日志中的响应体）。

    :param response: 响应对象。
    :returns: Content-Length 大于 5000 时返回 True。
    """
    content_length: int = response.headers.get("content-length", 0)
    return int(content_length) > 102400


def is_streaming_response(response: Response) -> bool:
    """判断响应是否为 SSE 等流式传输，此类响应不可缓冲整包 body。"""
    content_type: str = response.headers.get("content-type", "")
    return "text/event-stream" in content_type.lower()


async def _resolve_audit_user(
        request: Request,
        response_payload: Optional[dict],
) -> tuple[int, str]:
    """
    解析审计日志中的用户身份。
    优先使用鉴权链已写入的 CTX_USER_ID（避免登出后 token 吊销导致二次鉴权失败）。
    """
    ctx_user_id = CTX_USER_ID.get() or 0
    if ctx_user_id:
        user = await User.get_or_none(id=ctx_user_id)
        if user:
            return user.id, user.username
        return ctx_user_id, ""

    if request.url.path == LOGIN_ACCESS_TOKEN_PATH and response_payload:
        data = response_payload.get("data")
        if isinstance(data, dict):
            user_id = data.get("id", 0)
            username = data.get("username", "")
            return user_id, username

    token = request.headers.get("token")
    if token:
        try:
            user = await AuthControl.is_authed(token)
            return user.id, user.username
        except Exception as exc:
            LOGGER.warning(f"审计日志从请求 Token 解析用户失败: {exc}")

    return 0, ""


async def logging_middleware(request: Request, call_next):
    """记录请求与响应摘要、耗时，并写入审计表；对上传/下载/大响应体做特殊处理。

    :param request: 当前请求。
    :param call_next: 下一层 ASGI 可调用对象。
    :returns: 下游返回的 Response。
    """
    # 接口服务时间
    start_time = time.time()
    request_time: str = time.strftime(GLOBAL_CONFIG.DATETIME_FORMAT2, time.localtime(start_time))

    # 变量初始化
    request_body, response_body = b'', b''

    # 读取并保存原始请求体，重置请求流以便后续处理
    original_request_body: bytes = await request.body()
    request._body = original_request_body
    request._stream = BytesIO(original_request_body)

    # 判断是否为文件上传请求
    is_upload: bool = is_upload_request(request)
    if is_upload:
        form_data: Dict[str, Any] = {}
        original_form_data: FormData = await request.form()
        # 提取字段和文件信息
        for field_name, field_value in original_form_data.items():
            if hasattr(field_value, 'file'):
                form_data[field_name] = {
                    "filename": field_value.filename,
                    "content_type": field_value.content_type,
                    "size": field_value.size
                }
            else:
                form_data[field_name] = field_value

        # 重置流的位置到开头，确保后续处理能正确读取
        request_body = orjson.dumps(form_data)
        request._stream.seek(0)

    # 记录请求信息
    request_method: str = request.method
    request_router: str = request.url.path
    request_header: dict = dict(request.headers)
    if "referer" in request_header and request_header["referer"]:
        try:
            request_header["referer"] = unquote(request_header["referer"])
        except:
            pass
    request_client: str = request.client.host if request.client else "127.0.0.1"
    request_tags: str = ROUTER_TAGS.get(request_router or "未定义", "未定义")
    request_summary: str = ROUTER_SUMMARY.get(request_router or "未定义", "未定义")
    request_body: bytes = request_body if is_upload else original_request_body.decode("utf-8", errors="ignore")
    request_params: str = unquote(request.query_params.__str__())

    # 请求流传递并获取响应
    response = await call_next(request)

    # 判断是否管控响应
    is_download: bool = is_download_response(response)
    is_html: bool = is_html_response(response)
    is_image: bool = is_image_response(response)
    is_longtext: bool = is_longtext_response(response)
    is_streaming: bool = is_streaming_response(response)

    response_header: dict = dict(response.headers)

    # 路由排除（静态文件&OpenApi文档）
    if not request_router.startswith("/static/") and request_router not in (
            '/',
            '/base/audit/list',
            PROJECT_CONFIG.APP_DOCS_URL,
            PROJECT_CONFIG.APP_REDOC_URL,
            PROJECT_CONFIG.APP_OPENAPI_URL,
    ):
        # 消费响应体
        if is_download:
            response_body: bytes = b"<FILE DOWNLOAD>"
        elif is_html:
            response_body: bytes = b"<HTML CONTENT>"
        elif is_image:
            response_body: bytes = b"<IMAGE CONTENT>"
        elif is_longtext:
            response_body: bytes = b"<LONGTEXT CONTENT>"
        elif is_streaming:
            # SSE 流式响应不能消费 body_iterator，否则客户端会等到整段结束才收到数据
            response_body: bytes = b"<STREAMING RESPONSE>"
        else:
            body_chunks = []
            async for chunk in response.body_iterator:
                body_chunks.append(chunk)

            response_body: str = b"".join(body_chunks).decode("utf-8", errors="ignore")

            # 重置响应体
            response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=response_header,
                media_type=response.media_type
            )

        # 接口服务结束时间
        end_time = time.time()
        response_time: str = time.strftime(GLOBAL_CONFIG.DATETIME_FORMAT2, time.localtime(end_time))
        response_elapsed = f"{end_time - start_time:.4f}s"

        # 记录日志
        audit_log: Dict[str, Any] = {
            "request_time": request_time,
            "request_tags": request_tags,
            "request_summary": request_summary,
            "request_method": request_method,
            "request_router": request_router,
            "request_client": request_client,
            "request_header": request_header,
            "request_params": request_body or request_params,
            "response_time": response_time,
            "response_header": response_header,
            "response_elapsed": response_elapsed
        }
        response_payload: Optional[dict] = None
        if isinstance(response_body, str) and response_body:
            try:
                _response = orjson.loads(response_body)
                if isinstance(_response, dict):
                    response_payload = _response
                    audit_log["response_code"] = _response.get("code", "")
                    audit_log["response_message"] = _response.get("message", "")[:512]
                audit_log["response_params"] = response_body
            except orjson.JSONDecodeError:
                audit_log["response_params"] = response_body

        request_message: str = f"\n> > > > > > > > > > > > > > > > > > > >\n" \
                               f"请求时间：{audit_log.get('request_time')}\n" \
                               f"请求模块：{audit_log.get('request_tags')}\n" \
                               f"请求接口：{audit_log.get('request_summary')}\n" \
                               f"请求方式：{audit_log.get('request_method')}\n" \
                               f"请求路由：{audit_log.get('request_router')}\n" \
                               f"请求来源：{audit_log.get('request_client')}\n" \
                               f"请求头部：{audit_log.get('request_header')}\n" \
                               f"请求参数：{audit_log.get('request_params')}\n" \
                               f"响应头部：{audit_log.get('response_header')}\n" \
                               f"响应代码：{audit_log.get('response_code')}\n" \
                               f"响应消息：{audit_log.get('response_message')}\n" \
                               f"响应参数：{audit_log.get('response_params')}\n" \
                               f"响应时间：{audit_log.get('response_time')}\n" \
                               f"响应耗时：{audit_log.get('response_elapsed')}\n" \
                               f"< < < < < < < < < < < < < < < < < < < < "

        LOGGER.info(request_message)

        user_id, username = await _resolve_audit_user(request, response_payload)
        audit_log["user_id"] = user_id
        audit_log["username"] = username

        # 审计落库
        await Audit.create(**audit_log)

    return response
