"""一次性 Docker Skill 沙箱执行器。

该模块只负责创建、限制和清理容器，不关心测试用例生成的业务逻辑。
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class SandboxValidationError(ValueError):
    """沙箱挂载路径或运行参数不符合安全约束。"""


@dataclass(frozen=True)
class SandboxConfig:
    """一次容器运行需要的受控参数。"""

    skill_dir: Path
    input_dir: Path
    output_dir: Path
    command: tuple[str, ...]
    image: str
    environment: Mapping[str, str]
    # None 表示不限制容器业务执行时长；仍保留容器资源隔离和最终清理逻辑。
    timeout_seconds: float | None = None
    memory: str = "1g"
    cpus: float = 1.0
    network: str = "bridge"
    max_output_bytes: int = 200_000


@dataclass(frozen=True)
class SandboxResult:
    """容器运行的最小可诊断结果。"""

    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    container_name: str
    cleanup_succeeded: bool
    error: str | None = None


def _validate_directory(directory: Path, *, label: str, require_skill: bool = False) -> Path:
    """解析目录并禁止其内部软链接越过当前挂载边界。"""
    resolved = directory.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise SandboxValidationError(f"{label}不是目录：{resolved}")
    if require_skill and not (resolved / "SKILL.md").is_file():
        raise SandboxValidationError(f"Skill 目录缺少 SKILL.md：{resolved}")
    for item in resolved.rglob("*"):
        if item.is_symlink() and not item.resolve(strict=False).is_relative_to(resolved):
            raise SandboxValidationError(f"{label}中存在指向目录外的软链接：{item}")
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    """判断两个目录是否相同或互为父子目录。"""
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _trim_output(value: str, limit: int) -> str:
    """限制日志尺寸，避免异常进程无限输出占满 API 进程内存。"""
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore") + "\n[日志已截断]"


def _as_text(value: str | bytes | None) -> str:
    """将 subprocess 在超时路径返回的 bytes 统一为文本。"""
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


class DockerSandboxRunner:
    """以最小权限同步运行一次 Docker 容器，并保证清理。"""

    def __init__(self, docker_bin: str = "docker") -> None:
        self.docker_bin = docker_bin

    def _docker(self, *args: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.docker_bin, *args], text=True, capture_output=True, check=False, timeout=timeout
        )

    def ensure_available(self) -> None:
        """在真正运行前确认 Docker CLI 与守护进程均可用。"""
        try:
            result = self._docker("info", "--format", "{{.ServerVersion}}")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Docker CLI 或 Docker 守护进程不可用") from exc
        if result.returncode != 0:
            raise RuntimeError(f"Docker 守护进程不可用：{result.stderr.strip()}")

    def run(self, config: SandboxConfig) -> SandboxResult:
        """同步运行容器；超时后停止容器，任何路径最终都会强制清理。"""
        skill_dir = _validate_directory(config.skill_dir, label="Skill 目录", require_skill=True)
        input_dir = _validate_directory(config.input_dir, label="输入目录")
        output_dir = _validate_directory(config.output_dir, label="输出目录")
        if any(_overlap(left, right) for left, right in (
            (skill_dir, input_dir), (skill_dir, output_dir), (input_dir, output_dir)
        )):
            raise SandboxValidationError("Skill、输入和输出目录必须彼此独立")
        if not config.command:
            raise SandboxValidationError("容器执行命令不能为空")
        if config.timeout_seconds is not None and config.timeout_seconds <= 0:
            raise SandboxValidationError("超时时间必须为正数或 None")
        if not config.environment:
            raise SandboxValidationError("模型配置不能为空")
        if any(not key.isidentifier() or not value for key, value in config.environment.items()):
            raise SandboxValidationError("模型环境变量名称或值不合法")

        self.ensure_available()
        container_name = f"sandbox-{uuid.uuid4().hex[:16]}"
        started = time.monotonic()
        status = "setup_error"
        error: str | None = None
        exit_code: int | None = None
        stdout = stderr = ""
        cleanup_succeeded = True
        process: subprocess.Popen[str] | None = None

        # 密钥只放进 Docker 子进程的环境，命令行中仅出现变量名，避免通过 ps 泄露。
        child_env = {**os.environ, **dict(config.environment)}
        args = [
            self.docker_bin, "run", "--rm", "--name", container_name,
            "--read-only", "--security-opt", "no-new-privileges:true",
            "--cap-drop", "ALL", "--pids-limit", "128",
            "--memory", config.memory, "--cpus", str(config.cpus),
            "--network", config.network, "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={skill_dir},dst=/skill,readonly",
            "--mount", f"type=bind,src={input_dir},dst=/input,readonly",
            "--mount", f"type=bind,src={output_dir},dst=/output",
            "--workdir", "/skill",
            "--env", "HOME=/tmp",
            "--env", "XDG_CACHE_HOME=/tmp/.cache",
            "--env", "XDG_CONFIG_HOME=/tmp/.config",
            "--env", "XDG_DATA_HOME=/tmp/.local/share",
        ]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            args.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        for name in config.environment:
            args.extend(["--env", name])
        args.extend([config.image, *config.command])

        try:
            process = subprocess.Popen(
                args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env
            )
            try:
                if config.timeout_seconds is None:
                    stdout, stderr = process.communicate()
                else:
                    stdout, stderr = process.communicate(timeout=config.timeout_seconds)
                exit_code = process.returncode
                status = "succeeded" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired as exc:
                stdout, stderr = _as_text(exc.stdout), _as_text(exc.stderr)
                try:
                    self._docker("stop", "--time", "0", container_name, timeout=10)
                except Exception:
                    pass
                try:
                    more_stdout, more_stderr = process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    more_stdout, more_stderr = process.communicate()
                stdout += _as_text(more_stdout)
                stderr += _as_text(more_stderr)
                exit_code = process.returncode
                status = "timed_out"
                error = f"执行超过 {config.timeout_seconds:g} 秒"
        except Exception as exc:
            error = str(exc)
        finally:
            # --rm 负责正常场景；rm --force 覆盖 Docker 客户端异常、超时等残留路径。
            try:
                cleaned = self._docker("rm", "--force", container_name, timeout=15)
                if cleaned.returncode not in (0, 1):
                    cleanup_succeeded = False
            except Exception:
                cleanup_succeeded = False

        return SandboxResult(
            status=status,
            exit_code=exit_code,
            stdout=_trim_output(stdout, config.max_output_bytes),
            stderr=_trim_output(stderr, config.max_output_bytes),
            duration_ms=round((time.monotonic() - started) * 1000),
            container_name=container_name,
            cleanup_succeeded=cleanup_succeeded,
            error=error,
        )
