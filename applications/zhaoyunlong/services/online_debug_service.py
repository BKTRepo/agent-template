"""开发者中心在线调试的同步 Docker 沙箱服务。"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from urllib.parse import quote

from configure import PROJECT_CONFIG
from dotenv import dotenv_values

from .docker_sandbox import DockerSandboxRunner, SandboxConfig, SandboxResult


_RESULT_PREFIX = "SKILL_SANDBOX_RESULT="
_RESULT_RETENTION_SECONDS = 24 * 60 * 60
_RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_MAX_RESULT_DOCUMENTS = 20
_MAX_RESULT_FILE_BYTES = 20 * 1024 * 1024
_MAX_RESULT_TOTAL_BYTES = 100 * 1024 * 1024
_RESULT_FILE_SUFFIXES = frozenset({".txt", ".md", ".json", ".csv", ".xlsx", ".docx", ".pdf"})
_RESULT_MEDIA_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
_REQUIRED_MODEL_ENV_NAMES = (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)
_OPTIONAL_MODEL_ENV_NAMES = (
    "CLAUDE_MAX_TURNS", "CLAUDE_MAX_BUDGET_USD", "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
)


class OnlineDebugError(ValueError):
    """应以 HTTP 422 返回给前端的在线调试校验错误。"""


@dataclass(frozen=True)
class OnlineDebugRun:
    """运行接口成功后返回给前端的安全元数据。"""

    run_id: str
    result_dir: Path
    duration_ms: int
    expires_at: str
    documents: tuple["OnlineDebugDocument", ...]

    def as_response(self) -> dict[str, Any]:
        """转换为运行接口约定的 JSON 响应。"""
        return {
            "run_id": self.run_id,
            "status": "completed",
            "documents": [document.as_response(self.run_id, self.expires_at) for document in self.documents],
            "sandbox": {"duration_ms": self.duration_ms},
        }


@dataclass(frozen=True)
class OnlineDebugDocument:
    """下载接口所需的已授权结果文件信息。"""

    file_path: Path
    filename: str
    size_bytes: int
    media_type: str

    def as_response(self, run_id: str, expires_at: str) -> dict[str, Any]:
        """转换为前端下载文件列表中的单个文件信息。"""
        suffix = f"/document?filename={quote(self.filename)}"
        return {
            "filename": self.filename,
            "format": Path(self.filename).suffix.removeprefix(".").lower(),
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "download_url": f"/realtime-test-case-gen/runs/{run_id}{suffix}",
            "expires_at": expires_at,
        }


class OnlineDebugService:
    """执行动态 Skill 定义，并在宿主机保存短期可下载的结果文件。"""

    def __init__(self, runner: DockerSandboxRunner | None = None) -> None:
        self.runner = runner or DockerSandboxRunner()
        # 调试结果与在线调试模块放在一起，目录结构为 sandbox_results/runs/{run_id}。
        self.data_dir = Path(__file__).resolve().parents[1] / "sandbox_results"
        self.runs_dir = self.data_dir / "runs"
        self.image = os.environ.get("ZHAOYUNLONG_SANDBOX_IMAGE", "test-case-sandbox:local")
        self.skill_dir = Path(__file__).resolve().parents[1] / "sandbox" / "online-debug-skill"
        # 默认无限等待模型完成；仅在运维主动配置时才启用沙箱执行超时。
        self.execution_timeout_seconds = self._read_execution_timeout_seconds()
        self.retention_seconds = self._read_retention_seconds()
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, payload: dict[str, Any], owner_id: int, run_id: str | None = None) -> OnlineDebugRun:
        """同步运行容器，并保留 Skill 在本次运行目录中生成的最终文件。"""
        self._validate_payload(payload)
        self.cleanup_expired_runs()
        model_environment = self._model_environment()
        if not (self.skill_dir / "SKILL.md").is_file() or not (self.skill_dir / "run.py").is_file():
            raise OnlineDebugError("在线调试容器入口文件不完整")

        run_id = run_id or uuid.uuid4().hex
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise OnlineDebugError("调试任务编号格式不正确")
        run_dir = self.runs_dir / run_id
        if run_dir.exists():
            raise OnlineDebugError("调试任务编号已存在")
        # Docker 执行器要求 Skill、输入和输出挂载目录彼此独立。容器工作目录
        # 只在本次执行期间存在；通过校验后的最终文件才会搬入 runs/{run_id}。
        work_dir = self.data_dir / ".work" / run_id
        input_dir, output_dir = work_dir / "input", work_dir / "output"
        run_dir.mkdir(mode=0o700)
        input_dir.mkdir(mode=0o700, parents=True)
        output_dir.mkdir(mode=0o700)
        try:
            self._write_input(input_dir, payload)
            result = self.runner.run(SandboxConfig(
                skill_dir=self.skill_dir,
                input_dir=input_dir,
                output_dir=output_dir,
                command=("python", "run.py"),
                image=self.image,
                environment=model_environment,
                timeout_seconds=self.execution_timeout_seconds,
            ))
            _, skill_result = self._extract_skill_result(result.stdout)
            documents = self._validate_sandbox_result(result, skill_result, output_dir)
            documents = self._persist_result_files(documents, run_dir)
            expires_at = time.time() + self.retention_seconds
            self._write_metadata(run_dir, run_id, owner_id, result, documents, expires_at)
            # 上传内容和容器输出工作目录都是临时文件；最终文件已位于 run_id 目录。
            shutil.rmtree(work_dir, ignore_errors=True)
            return OnlineDebugRun(
                run_id=run_id, result_dir=run_dir, duration_ms=result.duration_ms,
                expires_at=self._format_timestamp(expires_at), documents=documents,
            )
        except OnlineDebugError:
            shutil.rmtree(run_dir, ignore_errors=True)
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(run_dir, ignore_errors=True)
            shutil.rmtree(work_dir, ignore_errors=True)
            raise OnlineDebugError(f"在线调试沙箱启动失败：{exc}") from exc

    def get_document(
        self, run_id: str, owner_id: int, is_superuser: bool, filename: str | None = None,
    ) -> OnlineDebugDocument:
        """校验归属和有效期后，返回指定文件；未指定时返回首个结果文件。"""
        documents = self.get_documents(run_id, owner_id, is_superuser)
        if filename is None:
            return documents[0]
        for document in documents:
            if document.filename == filename:
                return document
        raise OnlineDebugError("指定的调试结果文档不存在")

    def get_documents(self, run_id: str, owner_id: int, is_superuser: bool) -> tuple[OnlineDebugDocument, ...]:
        """校验归属和有效期后，返回该次调试生成的全部结果文件。"""
        self.cleanup_expired_runs()
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise OnlineDebugError("调试结果编号格式不正确")
        run_dir = self.runs_dir / run_id
        metadata = self._read_metadata(run_dir)
        if not is_superuser and metadata.get("owner_id") != owner_id:
            raise OnlineDebugError("无权下载该调试结果文档")
        expires_at = metadata.get("expires_at")
        if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
            shutil.rmtree(run_dir, ignore_errors=True)
            raise OnlineDebugError("调试结果文档已过期，请重新运行调试")
        return self._documents_from_metadata(run_dir, metadata)

    @staticmethod
    def _validate_sandbox_result(
        result: SandboxResult, skill_result: dict[str, Any] | None, output_dir: Path,
    ) -> tuple[OnlineDebugDocument, ...]:
        """校验容器状态并读取 Skill 自主生成的一个或多个最终文件。"""
        if result.status == "timed_out":
            raise OnlineDebugError("在线调试沙箱执行超时")
        if result.status != "succeeded":
            raise OnlineDebugError(OnlineDebugService._result_error("沙箱执行失败", result))
        if skill_result is None:
            raise OnlineDebugError("容器未按在线调试协议返回执行结果")
        result_files = tuple(sorted(
            (
                path for path in output_dir.iterdir()
                if path.is_file()
                and path.name != "metadata.json"
                and not path.name.startswith(".")
                and path.suffix.lower() in _RESULT_FILE_SUFFIXES
                and path.stat().st_size > 0
            ),
            key=lambda path: path.name,
        ))
        if not result_files:
            allowed_suffixes = "、".join(sorted(_RESULT_FILE_SUFFIXES))
            raise OnlineDebugError(f"Skill 执行结束但未生成最终文件；支持格式：{allowed_suffixes}")
        if len(result_files) > _MAX_RESULT_DOCUMENTS:
            raise OnlineDebugError(f"模型生成的结果文件超过 {_MAX_RESULT_DOCUMENTS} 个")
        total_size = sum(path.stat().st_size for path in result_files)
        if total_size > _MAX_RESULT_TOTAL_BYTES:
            raise OnlineDebugError("Skill 生成的结果文件总大小超过 100 MB")
        documents: list[OnlineDebugDocument] = []
        for file_path in result_files:
            if file_path.stat().st_size > _MAX_RESULT_FILE_BYTES:
                raise OnlineDebugError(f"Skill 生成的结果文件超过 20 MB：{file_path.name}")
            documents.append(OnlineDebugDocument(
                file_path=file_path,
                filename=file_path.name,
                size_bytes=file_path.stat().st_size,
                media_type=OnlineDebugService._media_type(file_path),
            ))
        return tuple(documents)

    def _write_metadata(
        self, run_dir: Path, run_id: str, owner_id: int, result: SandboxResult,
        documents: tuple[OnlineDebugDocument, ...], expires_at: float,
    ) -> None:
        """只保存下载和权限校验所需的最小运行元数据。"""
        metadata = {
            "run_id": run_id, "owner_id": owner_id, "created_at": self._format_timestamp(time.time()),
            "expires_at": expires_at, "duration_ms": result.duration_ms,
            "documents": [
                {
                    "filename": document.filename,
                    "size_bytes": document.size_bytes,
                    "media_type": document.media_type,
                }
                for document in documents
            ],
        }
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    @staticmethod
    def _persist_result_files(
        documents: tuple[OnlineDebugDocument, ...], run_dir: Path,
    ) -> tuple[OnlineDebugDocument, ...]:
        """将已校验的容器输出搬入最终 run_id 目录，并返回最终路径信息。"""
        persisted: list[OnlineDebugDocument] = []
        for document in documents:
            target = run_dir / document.filename
            # 文件名在校验阶段已限定为普通文件名，且 run_dir 为本次新建目录。
            shutil.move(str(document.file_path), str(target))
            persisted.append(OnlineDebugDocument(
                file_path=target,
                filename=document.filename,
                size_bytes=document.size_bytes,
                media_type=document.media_type,
            ))
        return tuple(persisted)

    def _read_metadata(self, run_dir: Path) -> dict[str, Any]:
        """读取并校验运行目录内的元数据，避免使用任何外部路径。"""
        try:
            value = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OnlineDebugError("调试结果不存在或元数据已损坏") from exc
        if not isinstance(value, dict):
            raise OnlineDebugError("调试结果元数据格式不正确")
        return value

    def cleanup_expired_runs(self) -> set[str]:
        """清理已过期结果目录并返回已删除任务编号，供定时任务同步删除表记录。"""
        now = time.time()
        deleted_run_ids: set[str] = set()
        for run_dir in self.runs_dir.iterdir():
            if not run_dir.is_dir() or not _RUN_ID_PATTERN.fullmatch(run_dir.name):
                continue
            try:
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
                expires_at = metadata.get("expires_at") if isinstance(metadata, dict) else None
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(expires_at, (int, float)) and expires_at <= now:
                shutil.rmtree(run_dir, ignore_errors=True)
                if not run_dir.exists():
                    deleted_run_ids.add(run_dir.name)
        return deleted_run_ids

    def remove_run_directories(self, run_ids: Iterable[str]) -> set[str]:
        """按任务表中已过期的任务编号删除结果目录，避免表和目录的过期时间不一致。"""
        deleted_run_ids: set[str] = set()
        for run_id in set(run_ids):
            if not _RUN_ID_PATTERN.fullmatch(run_id):
                continue
            run_dir = self.runs_dir / run_id
            if not run_dir.is_dir():
                continue
            shutil.rmtree(run_dir, ignore_errors=True)
            if not run_dir.exists():
                deleted_run_ids.add(run_id)
        return deleted_run_ids

    @staticmethod
    def _documents_from_metadata(run_dir: Path, metadata: dict[str, Any]) -> tuple[OnlineDebugDocument, ...]:
        """从元数据还原并校验 Skill 生成的结果文件。"""
        values = metadata.get("documents")
        if not isinstance(values, list):
            raise OnlineDebugError("调试结果元数据格式不正确")
        documents: list[OnlineDebugDocument] = []
        for value in values:
            if not isinstance(value, dict):
                raise OnlineDebugError("调试结果元数据格式不正确")
            filename = value.get("filename")
            if (
                not isinstance(filename, str)
                or not OnlineDebugService._is_plain_filename(filename)
                or Path(filename).suffix.lower() not in _RESULT_FILE_SUFFIXES
            ):
                raise OnlineDebugError("调试结果文件名不合法")
            document = run_dir / filename
            if not document.is_file() or document.stat().st_size == 0:
                raise OnlineDebugError("调试结果文档不存在或已损坏")
            size_bytes = value.get("size_bytes")
            media_type = value.get("media_type")
            documents.append(OnlineDebugDocument(
                file_path=document,
                filename=filename,
                size_bytes=size_bytes if isinstance(size_bytes, int) and size_bytes >= 0 else document.stat().st_size,
                media_type=media_type if isinstance(media_type, str) and media_type else OnlineDebugService._media_type(document),
            ))
        if not documents:
            raise OnlineDebugError("调试结果文档不存在或已损坏")
        return tuple(documents)

    @staticmethod
    def _media_type(file_path: Path) -> str:
        """返回下载响应使用的安全媒体类型，未知格式退回通用二进制下载。"""
        return _RESULT_MEDIA_TYPES.get(
            file_path.suffix.lower(),
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
        )

    @staticmethod
    def _is_plain_filename(value: str) -> bool:
        """同时按 Windows 和 POSIX 路径规则判断值是否为普通文件名。"""
        return bool(value) and (
            PurePosixPath(value).name == value
            and PureWindowsPath(value).name == value
        )

    @staticmethod
    def _read_execution_timeout_seconds() -> float | None:
        """读取可选的执行超时；未设置或设为 0 时无限等待模型完成。"""
        raw_value = os.environ.get("ZHAOYUNLONG_SANDBOX_TIMEOUT_SECONDS", "").strip()
        if not raw_value or raw_value == "0":
            return None
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise OnlineDebugError("ZHAOYUNLONG_SANDBOX_TIMEOUT_SECONDS 必须是数字") from exc
        if value <= 0:
            raise OnlineDebugError("ZHAOYUNLONG_SANDBOX_TIMEOUT_SECONDS 必须大于 0 或设为 0")
        return value

    @staticmethod
    def _read_retention_seconds() -> int:
        """读取结果保留时长；范围限制为 1 小时到 7 天。"""
        raw_value = os.environ.get("ZHAOYUNLONG_DEBUG_RESULT_RETENTION_SECONDS", "").strip()
        if not raw_value:
            return _RESULT_RETENTION_SECONDS
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise OnlineDebugError("ZHAOYUNLONG_DEBUG_RESULT_RETENTION_SECONDS 必须是整数") from exc
        if not 3600 <= value <= 7 * 24 * 60 * 60:
            raise OnlineDebugError("调试结果保留时长必须介于 3600 秒和 604800 秒之间")
        return value

    @staticmethod
    def _result_error(prefix: str, result: SandboxResult) -> str:
        """返回简洁执行诊断，避免把整段容器日志放进 HTTP 响应。"""
        detail = (result.stderr or result.error or result.stdout).strip()
        return f"{prefix}：{detail[:1000]}" if detail else f"{prefix}（退出码：{result.exit_code}）"

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        """校验 API 模型之外仍需保障的总量和必要输入约束。"""
        definition = payload.get("skill_definition")
        conversation = str(payload.get("conversation_input", "")).strip()
        documents, resources = payload.get("documents", []), payload.get("mounted_resources", [])
        if not isinstance(definition, str) or not definition.strip():
            raise OnlineDebugError("skill_definition 必须是非空 Markdown 文本")
        if len(definition) > 100_000:
            raise OnlineDebugError("skill_definition 不能超过 100000 个字符")
        if not isinstance(documents, list) or not isinstance(resources, list):
            raise OnlineDebugError("documents 和 mounted_resources 必须是数组")
        if not conversation and not documents:
            raise OnlineDebugError("至少提供对话输入或一份文档输入文件")

    def _write_input(self, input_dir: Path, payload: dict[str, Any]) -> None:
        """将前端文本安全写为容器可读取、不可修改的输入文件。"""
        # 本次文档输入已在接口层按允许格式解析，保留格式检查作为服务层兜底。
        document_paths = self._write_text_files(
            input_dir / "documents", payload["documents"], "文档", validate_text_suffix=True,
        )
        # 已挂载资源由资源系统负责格式管理；在线调试只安全落盘其已解析文本。
        resource_paths = self._write_text_files(
            input_dir / "resources", payload["mounted_resources"], "挂载资源", validate_text_suffix=False,
        )
        (input_dir / "online-debug-request.json").write_text(json.dumps({
            "skill_definition": payload["skill_definition"],
            "conversation_input": str(payload.get("conversation_input", "")).strip(),
            "document_paths": document_paths, "resource_paths": resource_paths,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_text_files(
        directory: Path,
        items: list[Any],
        label: str,
        *,
        validate_text_suffix: bool,
    ) -> list[str]:
        """写入已解析文本资源，禁止路径穿越和同名覆盖。"""
        paths: list[str] = []
        total_size = 0
        for item in items:
            if not isinstance(item, dict):
                raise OnlineDebugError(f"{label}中的每项必须是对象")
            raw_name, content = str(item.get("filename", "")), str(item.get("content", ""))
            filename = raw_name
            if not OnlineDebugService._is_plain_filename(filename):
                raise OnlineDebugError(f"{label}文件名不合法")
            if validate_text_suffix and Path(filename).suffix.lower() not in {".md", ".txt", ".json"}:
                raise OnlineDebugError(f"{label}必须是已解析的 Markdown、TXT 或 JSON 文本")
            if len(content) > 500_000:
                raise OnlineDebugError(f"{label}文件过大：{filename}")
            total_size += len(content)
            if total_size > 1_000_000:
                raise OnlineDebugError(f"{label}总长度不能超过 1000000 个字符")
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / filename
            if target.exists():
                raise OnlineDebugError(f"{label}文件名重复：{filename}")
            target.write_text(content, encoding="utf-8")
            # 宿主机在 Windows 时 Path 字符串会生成反斜杠；容器内始终按 POSIX 路径读取。
            paths.append(target.relative_to(directory.parent).as_posix())
        return paths

    @staticmethod
    def _model_environment() -> dict[str, str]:
        """读取 .env 或进程环境中的 Anthropic 兼容模型配置，不修改全局环境。"""
        # .env 位于项目根目录，而 OUTPUT_DIR 位于项目根目录下的 output 目录。
        env_file = Path(PROJECT_CONFIG.OUTPUT_DIR).resolve().parent / ".env"
        file_values = dotenv_values(env_file) if env_file.is_file() else {}

        def value(name: str) -> str:
            return (os.environ.get(name) or file_values.get(name) or "").strip()

        missing = [name for name in _REQUIRED_MODEL_ENV_NAMES if not value(name)]
        if missing:
            raise OnlineDebugError(f"模型配置缺少：{', '.join(missing)}；请在 .env 或进程环境中配置")
        names = _REQUIRED_MODEL_ENV_NAMES + tuple(name for name in _OPTIONAL_MODEL_ENV_NAMES if value(name))
        return {name: value(name) for name in names}

    @staticmethod
    def _extract_skill_result(stdout: str) -> tuple[str, dict[str, Any] | None]:
        """提取并移除容器入口约定的单行 JSON 结果。"""
        lines = stdout.splitlines(keepends=True)
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index].strip()
            if not line.startswith(_RESULT_PREFIX):
                continue
            try:
                value = json.loads(line.removeprefix(_RESULT_PREFIX))
            except json.JSONDecodeError:
                return stdout, None
            if isinstance(value, dict):
                return "".join(lines[:index] + lines[index + 1:]), value
        return stdout, None

    @staticmethod
    def _format_timestamp(timestamp: float) -> str:
        """使用 ISO 8601 UTC 时间串返回创建和过期时间。"""
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
