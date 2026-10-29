"""开发者中心在线调试四个接口的完整本地联调示例。"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SKILL_DEFINITION = """# 登录功能测试用例生成

## 目标
根据输入的需求、文档和挂载资源生成可执行的 Excel 功能测试用例。

## 覆盖范围
覆盖正常、异常、边界、权限与安全场景；每条用例应包含前置条件、步骤、预期结果和优先级。
"""

MULTI_RESULT_SKILL_DEFINITION = """# 登录与权限测试用例生成

## 目标
根据本次调试诉求，生成两份彼此独立、可导入 ATPM 的功能测试用例。

## 固定输出要求
必须生成以下两份 Markdown 结果文件，不能合并为同一个文件：

1. `/output/登录功能.md`：覆盖登录成功、错误密码、空值、账号状态和输入边界等场景。
2. `/output/权限功能.md`：覆盖角色权限、无权限访问、越权访问、权限变更和会话失效等场景。

每份文件均使用 ATPM 测试用例表格格式，包含正向、反向和边界用例。
"""


def main() -> int:
    """依次联调四个在线调试接口，并下载本次任务的全部结果文件。"""
    args = _parse_args()
    try:
        token = _get_token(args)
        base_url = args.base_url.rstrip("/")

        # 第一个在线调试接口：创建后台沙箱任务。
        created_run = _create_run(base_url, token, args)
        run_id = _require_string(created_run, "run_id", "创建任务接口")
        print("\n[1/4] 创建调试任务成功")
        _print_json(created_run)

        # 第二个在线调试接口：模拟弹窗重新打开，读取该技能最近一次任务。
        latest_run = _get_latest_run(base_url, token, args.skill_id)
        print("\n[2/4] 查询技能最近一次调试任务成功")
        _print_json(latest_run)
        if latest_run.get("run_id") != run_id:
            print("提示：该技能存在其他更新的调试任务；本示例仍按本次 run_id 继续查询。", file=sys.stderr)

        # 第三个在线调试接口：轮询本次任务，直到成功或失败。
        completed_run = _wait_for_completion(
            base_url=base_url,
            token=token,
            run_id=run_id,
            wait_seconds=args.wait_seconds,
            poll_interval=args.poll_interval,
        )
        if completed_run is None:
            return 1

        # 第四个在线调试接口：使用同一个下载地址按文件名下载全部 Excel 结果文档。
        output_paths = _download_documents(
            base_url=base_url,
            token=token,
            run_id=run_id,
            completed_run=completed_run,
            output_dir=Path(args.output_dir),
        )
        print(f"\n[4/4] 下载调试结果文档成功，共 {len(output_paths)} 个文件")
        for output_path in output_paths:
            print(f"文件位置：{output_path}")
        return 0
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        print(f"接口调用失败：HTTP {exc.code}\n{payload}", file=sys.stderr)
        return 1
    except (FileNotFoundError, URLError, ValueError, json.JSONDecodeError) as exc:
        print(f"接口调用失败：{exc}", file=sys.stderr)
        return 1


def _parse_args() -> argparse.Namespace:
    """读取脚本参数；敏感的登录信息也可从环境变量读取。"""
    parser = argparse.ArgumentParser(description="完整调用在线调试四个接口并下载 Excel 测试用例")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端服务地址")
    parser.add_argument("--token", default=os.getenv("ONLINE_DEBUG_TOKEN", ""), help="已有登录令牌；也可使用 ONLINE_DEBUG_TOKEN")
    parser.add_argument("--username", default=os.getenv("ONLINE_DEBUG_USERNAME", ""), help="登录账号；未传 token 时必填")
    parser.add_argument("--password", default=os.getenv("ONLINE_DEBUG_PASSWORD", ""), help="登录密码；未传 token 时必填")
    parser.add_argument("--skill-id", default="seed-skill-login", help="被调试技能的业务标识")
    parser.add_argument("--skill-definition-file", help="Skill 定义 Markdown 文件路径；不传时使用内置示例")
    parser.add_argument(
        "--multi-result-example",
        action="store_true",
        help="使用内置多结果示例，要求模型生成登录功能和权限功能两份 Excel",
    )
    parser.add_argument("--conversation", default="请为登录功能生成完整功能测试用例。", help="本次调试诉求")
    parser.add_argument("--document", action="append", default=[], help="需求文档路径；可重复指定，最多 10 个")
    parser.add_argument("--resource", action="append", default=[], help="挂载资源路径；可重复指定，最多 20 个")
    parser.add_argument("--output-dir", default="./downloads", help="Excel 调试结果保存目录")
    parser.add_argument("--wait-seconds", type=int, default=0, help="等待任务完成的最长秒数；0 表示无限等待")
    parser.add_argument("--poll-interval", type=float, default=2, help="查询任务状态的间隔秒数")
    args = parser.parse_args()

    if not args.token and (not args.username or not args.password):
        parser.error("请传入 --token，或同时传入 --username 和 --password")
    if len(args.document) > 10 or len(args.resource) > 20:
        parser.error("--document 最多 10 个，--resource 最多 20 个")
    if args.multi_result_example and args.skill_definition_file:
        parser.error("--multi-result-example 不能与 --skill-definition-file 同时使用")
    if args.wait_seconds < 0 or args.poll_interval <= 0:
        parser.error("--wait-seconds 必须大于等于 0，--poll-interval 必须大于 0")
    return args


def _get_token(args: argparse.Namespace) -> str:
    """优先使用已有 Token；否则调用登录接口获取 Token。"""
    if args.token:
        print("使用传入的 Token，跳过登录接口。")
        return args.token

    request = Request(
        url=f"{args.base_url.rstrip('/')}/base/auth/access_token",
        data=json.dumps({"username": args.username, "password": args.password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = _read_json(response)

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"登录接口未返回 data：{payload}")
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError(f"登录接口未返回 access_token：{payload}")
    print("登录接口调用成功，已获取 Token。")
    return token


def _create_run(base_url: str, token: str, args: argparse.Namespace) -> dict[str, Any]:
    """调用 POST /runs，创建本次在线调试任务。"""
    fields = {
        "skill_id": args.skill_id,
        "skill_definition": _read_skill_definition(args.skill_definition_file, args.multi_result_example),
        "conversation_input": args.conversation,
    }
    files = [("documents", Path(path)) for path in args.document]
    files.extend(("mounted_resources", Path(path)) for path in args.resource)
    body, content_type = _encode_multipart(fields, files)
    request = Request(
        url=f"{base_url}/realtime-test-case-gen/runs",
        data=body,
        headers={"Content-Type": content_type, "token": token},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return _read_json(response)


def _get_latest_run(base_url: str, token: str, skill_id: str) -> dict[str, Any]:
    """调用 GET /skills/{skill_id}/latest-run，模拟调试弹窗重新打开。"""
    request = Request(
        url=f"{base_url}/realtime-test-case-gen/skills/{skill_id}/latest-run",
        headers={"token": token},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        return _read_json(response)


def _wait_for_completion(
    *, base_url: str, token: str, run_id: str, wait_seconds: int, poll_interval: float,
) -> dict[str, Any] | None:
    """调用 GET /runs/{run_id}，轮询直至任务进入终态。"""
    deadline = None if wait_seconds == 0 else time.monotonic() + wait_seconds
    while deadline is None or time.monotonic() < deadline:
        request = Request(
            url=f"{base_url}/realtime-test-case-gen/runs/{run_id}",
            headers={"token": token},
            method="GET",
        )
        with urlopen(request, timeout=30) as response:
            run = _read_json(response)

        task_status = run.get("status")
        print(f"\n[3/4] 查询任务状态：{task_status}")
        _print_json(run)
        if task_status == "completed":
            documents = run.get("documents")
            if isinstance(documents, list) and documents:
                return run
            print("任务已完成，但接口响应中没有下载地址。", file=sys.stderr)
            return None
        if task_status == "failed":
            print(f"任务执行失败：{run.get('error_message', '未知错误')}", file=sys.stderr)
            return None
        time.sleep(poll_interval)

    print(f"等待超时。可稍后用 run_id 查询：{run_id}", file=sys.stderr)
    return None


def _download_documents(
    *, base_url: str, token: str, run_id: str, completed_run: dict[str, Any], output_dir: Path,
) -> list[Path]:
    """逐个调用结果下载地址，并将所有 Excel 保存到本地。"""
    documents = completed_run.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("任务完成响应缺少 documents")

    output_paths: list[Path] = []
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("任务完成响应中的 documents 格式不正确")
        download_url = _require_string(document, "download_url", "任务完成响应")
        filename = document.get("filename")
        safe_filename = Path(filename).name if isinstance(filename, str) and filename else "调试结果文档.xlsx"
        request = Request(url=f"{base_url}{download_url}", headers={"token": token}, method="GET")
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            content = response.read()

        # 部分项目异常响应使用 HTTP 200，不能只凭状态码判断下载成功。
        expected_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if content_type != expected_type:
            detail = content.decode("utf-8", errors="replace")
            raise ValueError(f"下载接口未返回 Excel（Content-Type: {content_type}）：{detail}")
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("下载接口返回的内容不是有效的 Excel 文件，未保存下载副本")

        target = output_dir.expanduser().resolve() / f"{run_id}_{safe_filename}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        output_paths.append(target)
    return output_paths


def _read_skill_definition(file_path: str | None, multi_result_example: bool) -> str:
    """读取自定义 Skill 定义，或选择内置的单结果、多结果示例。"""
    if multi_result_example:
        return MULTI_RESULT_SKILL_DEFINITION
    if not file_path:
        return DEFAULT_SKILL_DEFINITION
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"找不到 Skill 定义文件：{path}")
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        raise ValueError(f"Skill 定义文件为空：{path}")
    return content


def _read_json(response: Any) -> dict[str, Any]:
    """解析接口 JSON 响应，并确保最外层为对象。"""
    payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"接口返回的 JSON 不是对象：{payload}")
    return payload


def _require_string(data: dict[str, Any], key: str, source: str) -> str:
    """读取接口响应中的必填字符串字段。"""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source}缺少 {key}：{data}")
    return value


def _print_json(data: dict[str, Any]) -> None:
    """以易读的 UTF-8 格式打印接口响应。"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _encode_multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    """使用标准库组装 multipart 请求，避免示例额外依赖 HTTP 客户端包。"""
    boundary = f"----OnlineDebug{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    for field_name, path in files:
        if not path.is_file():
            raise FileNotFoundError(f"找不到上传文件：{path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode("utf-8"),
            path.read_bytes(),
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    raise SystemExit(main())
