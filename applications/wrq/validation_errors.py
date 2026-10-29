"""Skill/知识库接口使用一致的、可定位字段的中文校验提示。"""
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from core.responses import ParameterResponse


def validation_issues(errors, *, knowledge=False):
    labels = {"skill_id": "技能 ID", "skill_name": "技能名称", "description": "描述",
        "instructions": "执行指令", "skill_class_id": "所属技能类", "application": "所属应用",
        "knowledge_base_ids": "挂载知识库", "resource_categories": "资源用途分类",
        "resource_usage": "资源使用说明", "compatibility": "运行环境要求",
        "knowledge_name": "知识库名称", "tag": "知识库标签", "change_summary": "变更摘要",
        "content": "文档内容", "markdown": "Skill 定义", "skill_markdown": "Skill 定义",
        "expected_version": "当前版本", "expected_generation": "文档代次", "files": "上传文件",
        "skill_ids": "目标技能", "retained_document_ids": "保留文件"}
    if knowledge:
        labels["description"] = "知识库描述"
    result = []
    for error in errors:
        loc = list(error["loc"])
        transport = loc.pop(0) if loc and loc[0] in {"body", "query", "header", "path"} else None
        field = ".".join(map(str, loc)) or "source"
        label = labels.get(str(loc[0]) if loc else "source", field)
        kind, context = error["type"], error.get("ctx", {})
        if kind == "missing":
            reason = "请先登录平台" if transport == "header" and field == "token" else f"请填写{label}"
        elif kind == "string_too_short":
            minimum = context.get("min_length", 1)
            reason = f"请填写{label}" if minimum == 1 else f"{label}至少需要 {minimum} 个字符"
        elif kind == "string_too_long":
            reason = f"{label}不能超过 {context['max_length']} 个字符"
        elif kind == "extra_forbidden":
            reason = "不支持提交此字段"
        elif kind == "literal_error":
            reason = f"{label}选项无效，请从列表中选择"
        elif kind == "too_long":
            reason = f"{label}不能超过 {context['max_length']} 项"
        elif kind == "too_short":
            reason = f"{label}至少需要 {context['min_length']} 项"
        elif kind == "json_invalid":
            reason = "请求数据不是合法 JSON，请检查提交格式"
        elif kind.endswith("_type") or kind in {"int_parsing", "string_pattern_mismatch"}:
            reason = f"{label}格式不正确，请检查填写内容"
        else:
            reason = error["msg"]
        result.append({"field": field, "reason": reason})
    return result


class ValidationResponseRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        knowledge = ".knowledge_base." in self.endpoint.__module__
        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                response = ParameterResponse(message="请补充或修正填写内容",
                    data={"errors": validation_issues(exc.errors(), knowledge=knowledge)})
                response.status_code = 422
                return response
        return handler
