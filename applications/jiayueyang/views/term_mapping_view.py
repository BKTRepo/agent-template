# -*- coding: utf-8 -*-
"""用户权威术语映射模板导入接口。"""

from fastapi import APIRouter, Body, File, Query, UploadFile

from applications.jiayueyang.services.term_mapping_import_service import (
    term_mapping_import_service,
)
from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.mapping_evidence_model import RagTermMappingEvidence
from applications.jiayueyang.services.term_mapping_crud import learned_term_mapping_crud
from applications.jiayueyang.services.learned_mapping_service import learned_mapping_service
from common.file_utils import read_upload_with_cap
from core.exceptions import NotFoundException, ParameterException
from core.responses import FailureResponse, NotFoundResponse, ParameterResponse, SuccessResponse


term_mapping_router = APIRouter()
_MAX_TEMPLATE_BYTES = 10 * 1024 * 1024


@term_mapping_router.post(
    "/term-mappings/source/import",
    summary="导入用户权威术语映射模板",
)
async def import_source_term_mapping(
    file: UploadFile = File(...),
    dry_run: bool = Query(True, description="true 只预检查，false 确认写入用户权威映射表"),
    upload_batch_id: str | None = Query(None, description="确认导入时可复用的批次编号"),
    operator: str | None = Query(None, description="操作人标识"),
):
    """采用预检查和确认导入两阶段，任何校验错误都不会写入半批数据。"""
    try:
        filename = file.filename or "mapping.xlsx"
        file_bytes = await read_upload_with_cap(file, _MAX_TEMPLATE_BYTES)
        if dry_run:
            data = await term_mapping_import_service.preview(file_bytes, filename)
        else:
            data = await term_mapping_import_service.import_file(
                file_bytes,
                filename,
                upload_batch_id=upload_batch_id,
                operator=operator,
            )
        return SuccessResponse(data=data)
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        return FailureResponse(message=f"映射模板导入失败: {exc}")


async def _serialize_rows(rows):
    return [await row.to_dict() for row in rows]


@term_mapping_router.get("/term-mappings/learned", summary="查询程序归纳映射")
async def list_learned_mappings(
    status: str | None = Query(None),
    scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    try:
        total, rows = await learned_term_mapping_crud.list_mappings(
            status=status, scope=scope, page=page, page_size=page_size,
        )
        return SuccessResponse(data=await _serialize_rows(rows), total=total)
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        return FailureResponse(message=f"查询程序映射失败: {exc}")


@term_mapping_router.post("/term-mappings/learned", summary="创建程序归纳映射")
async def create_learned_mapping(
    payload: dict = Body(..., description="程序归纳字段；状态由服务端固定为 active"),
):
    """创建可直接参与查询的程序映射；采纳自动聚合也使用 active 状态。"""
    try:
        values = dict(payload)
        values["status"] = "active"
        values.pop("reviewed_by", None)
        values.pop("reviewed_time", None)
        data = await learned_term_mapping_crud.create_mapping(values)
        return SuccessResponse(data=await data.to_dict())
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        return FailureResponse(message=f"创建程序映射失败: {exc}")


@term_mapping_router.post(
    "/term-mappings/learned/from-feedback/{feedback_uid}",
    summary="从采纳反馈归纳程序映射",
)
async def create_learned_mapping_from_feedback(feedback_uid: str):
    try:
        rows = await learned_mapping_service.from_feedback(feedback_uid)
        return SuccessResponse(data=[await row.to_dict() for row in rows])
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        return FailureResponse(message=f"从采纳反馈归纳映射失败: {exc}")


@term_mapping_router.get("/term-mappings/learned/{learned_mapping_id}", summary="查看程序归纳映射详情")
async def get_learned_mapping(learned_mapping_id: str):
    row = await learned_term_mapping_crud.model.filter(
        learned_mapping_id=learned_mapping_id,
    ).first()
    if row is None:
        return NotFoundResponse(message="程序映射不存在")
    return SuccessResponse(data=await row.to_dict())


@term_mapping_router.patch("/term-mappings/learned/{learned_mapping_id}/review", summary="审核程序归纳映射")
async def review_learned_mapping(
    learned_mapping_id: str,
    payload: dict = Body(..., description="action: activate/reject/disable, reviewer: 审核人"),
):
    try:
        data = await learned_term_mapping_crud.review(
            learned_mapping_id,
            str(payload.get("action") or ""),
            str(payload.get("reviewer") or ""),
        )
        return SuccessResponse(data=await data.to_dict())
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        return FailureResponse(message=f"审核程序映射失败: {exc}")


@term_mapping_router.get("/term-mappings/feedback", summary="查询采纳经验供审核")
async def list_feedback_for_review(
    action: str = Query("accepted"),
    index_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    if action not in {"accepted", "revoked"}:
        return ParameterResponse(message="action 只能是 accepted 或 revoked")
    query = RagAnswerFeedback.filter(action=action)
    if index_status:
        query = query.filter(index_status=index_status)
    total = await query.count()
    rows = await query.order_by("-updated_time", "id").offset((page - 1) * page_size).limit(page_size)
    return SuccessResponse(data=await _serialize_rows(rows), total=total)


@term_mapping_router.get("/term-mappings/evidence", summary="查询程序映射提取证据")
async def list_mapping_evidence(
    status: str | None = Query(None),
    mapping_key: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    """查看第一次采纳保存的证据，不直接改变用户映射表。"""
    query = RagTermMappingEvidence.all()
    if status:
        query = query.filter(status=status)
    if mapping_key:
        query = query.filter(mapping_key=mapping_key)
    total = await query.count()
    rows = await query.order_by("-updated_time", "id").offset((page - 1) * page_size).limit(page_size)
    return SuccessResponse(data=await _serialize_rows(rows), total=total)
