from applications.wrq.agent.services.developer_skill_crud import DeveloperError
"""Skill 表单解析与目录包接口，沿用认证依赖及统一响应封装。"""
from applications.wrq.http import WrqRoute
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import ValidationError
from starlette.responses import FileResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from applications.wrq.agent.schemas.skill_package_schema import (
    SkillDeveloperForm, SkillDefinitionEdit, SkillEntryUploadSource, SkillPackageSource, SkillValidationReport, ValidationIssue,
)
from applications.wrq.agent.schemas.api_request_schema import (
    SkillDefinitionSaveRequest, SkillPackageRequest, business_payload,
)
from applications.wrq.agent.services.skill_package_builder import SkillPackageError
from applications.wrq.agent.services.skill_package_service import (
    SkillBuildNotFound, SkillPackageService, get_skill_package_service,
)
from applications.wrq.agent.services.skill_upload_adapter import report_for_upload_entries, source_from_upload_entries
from applications.wrq.auth import PlatformIdentity as User
from applications.wrq.validation_errors import ValidationResponseRoute, validation_issues
from configure import LOGGER
from core.responses import FailureResponse, NotFoundResponse, ParameterResponse, SuccessResponse
from applications.wrq.auth import DependAuth

skill_packages = APIRouter(route_class=WrqRoute)


async def _respond(operation):
    try:
        return SuccessResponse(data=await operation)
    except SkillPackageError as exc:
        return ParameterResponse(message="请补充或修正 Skill 信息", data=exc.report.model_dump())
    except SkillBuildNotFound as exc:
        return NotFoundResponse(message=str(exc))
    except DeveloperError:
        raise
    except (OSError, ValueError):
        LOGGER.exception("Skill 包读写失败")
        return FailureResponse(message="Skill 包存储异常，请联系管理员检查存储目录")


@skill_packages.post("/packages/build-from-form", summary="Skill包-从开发者表单和上传资源构建生成Skill包")
async def build_skill_from_form(request: Request, source: str = Form(...),
                                files: list[UploadFile] = File(default=[]),
                                current_user: User = DependAuth,
                                service: SkillPackageService = Depends(get_skill_package_service)):
    multipart = await request.form()
    all_uploads = [(field, value) for field, value in multipart.multi_items()
                   if isinstance(value, StarletteUploadFile)]
    try:
        unknown = {field for field, _ in all_uploads} - {"files"}
        if unknown:
            return ParameterResponse(message="文件请统一通过 files 上传", data={"errors": [
                {"field": field, "reason": "文件请统一通过 files 上传"} for field in sorted(unknown)]})
        try:
            form = SkillDeveloperForm.model_validate_json(source)
        except ValidationError as exc:
            return ParameterResponse(message="source 必须是符合定稿表单合同的 JSON",
                data={"errors": validation_issues(exc.errors())})
        return await _respond(service.build_form(form, current_user, files))
    finally:
        for _, upload in all_uploads:
            await upload.close()


@skill_packages.get("/packages/get-definition", summary="Skill包-查询当前技能Markdown定义")
async def get_definition(skill_id: int = Query(..., ge=1), current_user: User = DependAuth,
                         service: SkillPackageService = Depends(get_skill_package_service)):
    return await _respond(service.definition(skill_id, current_user))


@skill_packages.post("/packages/save-definition", summary="Skill包-保存Markdown定义并校验版本、重新构建")
async def save_definition(data: SkillDefinitionSaveRequest, current_user: User = DependAuth,
                          service: SkillPackageService = Depends(get_skill_package_service)):
    return await _respond(service.rebuild_saved(data.skill_id, current_user, markdown=data.markdown,
                                               expected_version=data.expected_version))


@skill_packages.post("/packages/validate", summary="Skill包-校验技能表单、资源及知识库挂载")
async def validate_skill_package(source: SkillPackageRequest,
                                current_user: User = DependAuth,
                                service: SkillPackageService = Depends(get_skill_package_service)):
    async def operation():
        return (await service.validate(source.skill_id, business_payload(source, SkillPackageSource), current_user)).model_dump()
    return await _respond(operation())


@skill_packages.post("/packages/build-from-documents", summary="Skill包-从技能表单和已有文档构建生成Skill包")
async def build_skill_package(source: SkillPackageRequest,
                             current_user: User = DependAuth,
                             service: SkillPackageService = Depends(get_skill_package_service)):
    return await _respond(service.build(source.skill_id, business_payload(source, SkillPackageSource), current_user))


@skill_packages.post("/packages/build-from-uploads", summary="Skill包-从技能表单和统一上传文件构建生成Skill包")
async def build_skill_package_with_uploads(skill_id: int = Form(..., ge=1), source: str = Form(...),
                                          files: list[UploadFile] = File(default=[]),
                                          current_user: User = DependAuth,
                                          service: SkillPackageService = Depends(get_skill_package_service)):
    try:
        try:
            parsed = SkillPackageSource.model_validate_json(source)
        except ValidationError as exc:
            return ParameterResponse(message="source 必须是符合字段合同的 JSON",
                                     data={"errors": validation_issues(exc.errors())})
        return await _respond(service.build(skill_id, parsed, current_user, files))
    finally:
        for upload in files:
            await upload.close()


@skill_packages.post("/packages/build-from-entries", summary="Skill包-从参考资料及脚本分入口上传构建生成Skill包")
async def build_skill_package_from_entries(request: Request, skill_id: int = Form(..., ge=1), source: str = Form(...),
                                          reference_files: list[UploadFile] = File(default=[]),
                                          script_files: list[UploadFile] = File(default=[]),
                                          current_user: User = DependAuth,
                                          service: SkillPackageService = Depends(get_skill_package_service)):
    multipart = await request.form()
    all_uploads = [(field, value) for field, value in multipart.multi_items() if isinstance(value, StarletteUploadFile)]
    try:
        try:
            parsed = SkillEntryUploadSource.model_validate_json(source)
        except ValidationError as exc:
            return ParameterResponse(message="source 必须是符合分入口上传合同的 JSON",
                                     data={"errors": validation_issues(exc.errors())})

        async def operation():
            unknown_fields = {field for field, _ in all_uploads} - {"reference_files", "script_files"}
            if unknown_fields:
                raise SkillPackageError(SkillValidationReport(errors=[
                    ValidationIssue(field=field, reason="文件请通过 reference_files 或 script_files 上传")
                    for field in sorted(unknown_fields)]))
            normalized = source_from_upload_entries(parsed, reference_count=len(reference_files),
                                                     script_count=len(script_files))
            try:
                return await service.build(skill_id, normalized, current_user, reference_files + script_files)
            except SkillPackageError as exc:
                raise SkillPackageError(report_for_upload_entries(exc.report, parsed)) from exc

        return await _respond(operation())
    finally:
        for _, upload in all_uploads:
            await upload.close()


@skill_packages.get("/packages/get-build", summary="Skill包-查询构建清单及资源目录")
async def get_skill_package(skill_id: int = Query(..., ge=1), build_id: str = Query(..., min_length=1, max_length=64), current_user: User = DependAuth,
                           service: SkillPackageService = Depends(get_skill_package_service)):
    return await _respond(service.get(skill_id, build_id, current_user, verify=True))


@skill_packages.get("/packages/list-builds", summary="Skill包-分页查询技能构建历史")
async def list_skill_packages(skill_id: int = Query(..., ge=1), limit: int = Query(default=20, ge=1, le=100),
                             offset: int = Query(default=0, ge=0), current_user: User = DependAuth,
                             service: SkillPackageService = Depends(get_skill_package_service)):
    return await _respond(service.list_builds(skill_id, current_user, limit=limit, offset=offset))


@skill_packages.get("/packages/download-build", summary="Skill包-下载完整技能ZIP构建包")
async def download_skill_package(skill_id: int = Query(..., ge=1), build_id: str = Query(..., min_length=1, max_length=64), current_user: User = DependAuth,
                                service: SkillPackageService = Depends(get_skill_package_service)):
    try:
        content = await service.download(skill_id, build_id, current_user)
        return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="skill-{build_id}.zip"'})
    except SkillPackageError as exc:
        return ParameterResponse(message="构建包内容校验失败", data=exc.report.model_dump())
    except SkillBuildNotFound as exc:
        return NotFoundResponse(message=str(exc))
    except DeveloperError:
        raise
    except (OSError, ValueError):
        LOGGER.exception("Skill 包下载失败")
        return FailureResponse(message="Skill 包存储异常，请联系管理员检查存储目录")
