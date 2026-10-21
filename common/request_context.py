# -*- coding: utf-8 -*-
"""
轻量分布式追踪：X-Trace-ID + X-Span-ID + X-Parent-Span-ID。
- TraceID：仅来自请求头 X-Trace-ID，未传则由后端留空（日志为 -）
- SpanID：每个入站 HTTP 请求由服务端分配，经 X-Span-ID 回传
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple, Union

from starlette.requests import Request

HEADER_TRACE_ID = "X-Trace-ID"
HEADER_SPAN_ID = "X-Span-ID"
HEADER_PARENT_SPAN_ID = "X-Parent-Span-ID"

_MISSING = "-"

_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")
_SPAN_ID: ContextVar[str] = ContextVar("span_id", default="")
_PARENT_SPAN_ID: ContextVar[str] = ContextVar("parent_span_id", default="")


@dataclass(frozen=True)
class TraceSnapshot:
    trace_id: str
    span_id: str
    parent_span_id: str = ""


def new_span_id() -> str:
    """生成 SpanID（16 位 hex，与 OpenTelemetry span_id 长度一致）。"""
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    return _TRACE_ID.get() or _MISSING


def get_span_id() -> str:
    return _SPAN_ID.get() or _MISSING


def get_parent_span_id() -> str:
    return _PARENT_SPAN_ID.get() or ""


def get_trace_snapshot() -> TraceSnapshot:
    return TraceSnapshot(
        trace_id=get_trace_id(),
        span_id=get_span_id(),
        parent_span_id=get_parent_span_id(),
    )


def bind_trace_context(
        trace_id: str,
        span_id: str,
        parent_span_id: str = "",
) -> Tuple[Token, Token, Token]:
    """绑定 Trace/Span 到当前上下文，返回用于 reset 的 token 元组。"""
    return (
        _TRACE_ID.set(trace_id or ""),
        _SPAN_ID.set(span_id or ""),
        _PARENT_SPAN_ID.set(parent_span_id or ""),
    )


def clear_trace_context(tokens: Tuple[Token, Token, Token]) -> None:
    trace_t, span_t, parent_t = tokens
    _TRACE_ID.reset(trace_t)
    _SPAN_ID.reset(span_t)
    _PARENT_SPAN_ID.reset(parent_t)


def _header_value(request: Request, name: str) -> str:
    return (request.headers.get(name) or "").strip()[:128]


def _incoming_trace_id(request: Request) -> str:
    """仅解析 X-Trace-ID，未传则返回空字符串。"""
    return _header_value(request, HEADER_TRACE_ID)


def _incoming_parent_span_id(request: Request) -> str:
    parent = _header_value(request, HEADER_PARENT_SPAN_ID)
    if not parent:
        parent = _header_value(request, HEADER_SPAN_ID)
    return parent


def enter_server_span(request: Request) -> Tuple[TraceSnapshot, Tuple[Token, Token, Token]]:
    """为当前入站 HTTP 分配 SpanID；TraceID 仅使用客户端传入的 X-Trace-ID。"""
    trace_id = _incoming_trace_id(request)
    parent_span_id = _incoming_parent_span_id(request)
    span_id = new_span_id()
    tokens = bind_trace_context(trace_id, span_id, parent_span_id)
    return TraceSnapshot(trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id), tokens


def apply_response_trace_headers(headers: MutableMapping[str, str], snapshot: TraceSnapshot) -> None:
    if snapshot.trace_id:
        headers[HEADER_TRACE_ID] = snapshot.trace_id
    if snapshot.span_id and snapshot.span_id != _MISSING:
        headers[HEADER_SPAN_ID] = snapshot.span_id
    if snapshot.parent_span_id:
        headers[HEADER_PARENT_SPAN_ID] = snapshot.parent_span_id


def propagate_trace_headers(
        headers: Optional[Union[Mapping[str, Any], MutableMapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    出站 HTTP：有 TraceID 时透传 X-Trace-ID，当前 Span 作为 X-Parent-Span-ID。
    """
    out: Dict[str, Any] = dict(headers or {})
    trace_id = get_trace_id()
    span_id = get_span_id()
    if not trace_id or trace_id == _MISSING:
        return out

    def _has(name: str) -> bool:
        lower = name.lower()
        return any(k.lower() == lower for k in out)

    if not _has(HEADER_TRACE_ID):
        out[HEADER_TRACE_ID] = trace_id
    if span_id and span_id != _MISSING and not _has(HEADER_PARENT_SPAN_ID):
        out[HEADER_PARENT_SPAN_ID] = span_id
    return out
