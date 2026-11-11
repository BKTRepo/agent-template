"""Opt-in artifact metadata and asset snapshots for local integration."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from stat import S_IMODE
from tempfile import NamedTemporaryFile

from filelock import FileLock, Timeout

from applications.conversation.exceptions import ConversationBusinessError
from configure import PROJECT_CONFIG

MAX_FILE_BYTES = 10 * 1024 * 1024
DEMO_FILES = {
    "test_cases": ("credit-card", "信用卡开户测试用例", "credit-card-cases.xlsx", "case"),
    "docx": ("report", "信用卡开户测试报告", "test-report.docx", "report"),
    "xlsx": ("dataset", "信用卡开户测试数据", "test-data.xlsx", "data"),
    "py": ("python", "信用卡开户校验脚本", "check-account.py", "script"),
    "js": ("javascript", "开户参数校验脚本", "check-account.js", "script"),
    "ts": ("typescript", "开户参数类型校验", "check-account.ts", "script"),
    "sh": ("shell", "开户环境检查脚本", "check-env.sh", "script"),
    "sql": ("sql", "开户数据查询脚本", "check-account.sql", "script"),
    "md": ("markdown", "开户测试说明", "test-notes.md", "report"),
    "json": ("json", "开户测试参数", "test-input.json", "data"),
}


@dataclass(frozen=True)
class Artifact:
    id: str
    name: str
    path: Path
    kind: str
    category: str

    @property
    def file_type(self):
        return self.path.suffix[1:].lower()


def mock_artifact(owner_id: int, artifact_id: str | None = None, *, kind: str = "test_cases") -> Artifact:
    configured = PROJECT_CONFIG.ASSISTANT_ARTIFACT_MOCK_DIR
    if artifact_id is not None:
        kind = next((key for key, spec in DEMO_FILES.items() if artifact_id == f"mock-{spec[0]}-{owner_id}"), "")
    if not configured or kind not in DEMO_FILES:
        raise ConversationBusinessError("产出物不存在或无权访问")
    slug, name, filename, category = DEMO_FILES[kind]
    root = Path(configured).resolve()
    path = (root / str(owner_id) / filename).resolve()
    if path.parent != root / str(owner_id) or path.name != filename:
        raise ConversationBusinessError("产出物不存在或无权访问")
    return Artifact(f"mock-{slug}-{owner_id}", name, path, kind, category)


def read_original(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            content = source.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        raise ConversationBusinessError("原文件不存在，请重新打开产出物") from exc
    except OSError as exc:
        raise ConversationBusinessError("暂时无法读取原文件，请重试") from exc
    if len(content) > MAX_FILE_BYTES:
        raise ConversationBusinessError("文件超过当前样例的处理上限")
    return content


def check_revision(content: bytes, base_hash: str) -> None:
    if sha256(content).hexdigest() != base_hash:
        raise ConversationBusinessError("原文件已更新，请重新打开产出物")


@contextmanager
def file_write_lock(path: Path):
    try:
        with FileLock(str(path) + ".lock", timeout=5):
            yield
    except Timeout as exc:
        raise ConversationBusinessError("原文件正在保存，请稍后重试") from exc
    except OSError as exc:
        raise ConversationBusinessError("共享目录写入失败，请重试") from exc


def replace_original(path: Path, content: bytes) -> None:
    # Replace only after writing a complete sibling file on the same filesystem.
    staged = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".artifact-", suffix=".tmp", delete=False) as file:
            staged = Path(file.name)
            file.write(content)
        if path.exists():
            staged.chmod(S_IMODE(path.stat().st_mode))
        staged.replace(path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def asset_path(artifact: Artifact) -> Path:
    path = artifact.path.with_name(f"archived-{artifact.path.name}")
    if path.is_symlink():
        raise ConversationBusinessError("归档路径不可用")
    return path


def asset_record_path(artifact: Artifact) -> Path:
    target = asset_path(artifact)
    path = target.with_suffix(".json") if artifact.kind == "test_cases" else target.with_name(target.name + ".meta.json")
    if path.is_symlink():
        raise ConversationBusinessError("归档路径不可用")
    return path
