"""确定性 Skill 生成与目录读取，不执行脚本，不调用大模型或向量服务。"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import quote, unquote, urlsplit
import uuid
import zipfile

from markdown_it import MarkdownIt
import yaml

from applications.agent.schemas.skill_package_schema import (
    SkillPackageSource, SkillValidationReport, ValidationIssue,
)

ROLE_DIRS = {"script": "scripts", "reference": "references", "asset": "assets"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                  *[f"LPT{i}" for i in range(1, 10)]}


class SkillPackageError(Exception):
    def __init__(self, report: SkillValidationReport):
        self.report = report.finish()
        super().__init__("Skill 包校验未通过")


@dataclass(frozen=True)
class ResolvedSkillResource:
    binding_index: int
    path: Path
    filename: str
    document_id: str | None = None
    expected_hash: str | None = None


def safe_relative_path(value: str) -> str:
    """采用 Windows/Linux 都可存储的相对路径；不折叠 .. 或隐藏绝对路径。"""
    parts = value.split("/")
    if not value or len(value) > 255 or "\\" in value:
        raise ValueError("必须是使用 / 分隔的相对文件路径")
    for part in parts:
        if (part in {"", ".", ".."} or part[-1:] in {".", " "}
                or re.search(r'[<>:"|?*\x00-\x1f\x7f]', part)
                or part.split(".")[0].upper() in RESERVED_NAMES):
            raise ValueError("文件路径包含越界、空片段或不支持的文件名")
    return str(PurePosixPath(value))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def markdown_body(raw: str) -> str:
    raw = raw.replace("\r\n", "\n")
    if raw.startswith("---\n"):
        match = re.match(r"\A---\n(.*?)^---[ \t]*\n(.*)\Z", raw, flags=re.M | re.S)
        try:
            if not match or not isinstance(yaml.safe_load(match[1]), dict):
                raise ValueError("YAML 必须是映射且正确结束")
        except (ValueError, yaml.YAMLError) as exc:
            raise SkillPackageBuilder._issue("skill_markdown", "Markdown 的 YAML 头部格式无效") from exc
        raw = match[2]
    # 这一段由服务器依据实际文件重建；重复保存不会不断叠加目录和说明。
    raw = re.sub(r"<!-- platform-resources:start -->.*?<!-- platform-resources:end -->", "", raw, flags=re.S).strip()
    if not raw:
        raise SkillPackageBuilder._issue("skill_markdown", "Skill 定义正文不能为空")
    return raw


def validate_source(source: SkillPackageSource) -> SkillValidationReport:
    report = SkillValidationReport()
    for field in ("name", "display_name", "description", "instructions", "version"):
        if not getattr(source, field):
            report.missing_fields.append(ValidationIssue(field=field, reason="请补充此字段"))
    if source.name and not NAME_RE.fullmatch(source.name):
        report.errors.append(ValidationIssue(field="name", reason="使用小写英文、数字及单个连字符"))
    if source.name and source.name.upper() in RESERVED_NAMES:
        report.errors.append(ValidationIssue(field="name", reason="技术名不能使用系统保留目录名"))
    if source.resource_usage is not None and (source.resources or source.knowledge_base_ids) and not source.resource_usage:
        report.missing_fields.append(ValidationIssue(field="resource_usage", reason="选择知识库或上传资源后，请填写资源使用说明"))
    for index, binding in enumerate(source.resources):
        field = f"resources[{index}]"
        if binding.role is None:
            report.missing_fields.append(ValidationIssue(field=f"{field}.role", reason="资源入口未提供内部文件用途"))
        if binding.upload_index is not None and not binding.usage:
            report.missing_fields.append(ValidationIssue(field=f"{field}.usage", reason="请补充上传资源的使用说明"))
        if bool(binding.document_id) == (binding.upload_index is not None):
            report.errors.append(ValidationIssue(field=field, reason="document_id 和 upload_index 必须提供且只提供一个"))
        if binding.target_path is not None:
            try:
                safe_relative_path(binding.target_path)
            except ValueError as exc:
                report.errors.append(ValidationIssue(field=f"{field}.target_path", reason=str(exc)))
    return report.finish()


class SkillPackageBuilder:
    def __init__(self, root: Path, *, max_file_bytes: int = 50 * 1024 * 1024,
                 max_total_bytes: int = 50 * 1024 * 1024):
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    def check_file_size(self, size: int, field: str):
        if size > self.max_file_bytes:
            raise self._issue(field, f"单个文件不能超过 {self.max_file_bytes / (1024 * 1024):g}MiB")

    def _parent(self, user_id: int, skill_id: str) -> Path:
        if user_id < 1 or not ID_RE.fullmatch(skill_id):
            raise ValueError("无效的用户或技能 ID")
        parent = self.root / str(user_id) / skill_id
        if not parent.resolve().is_relative_to(self.root):
            raise ValueError("构建目录越界")
        return parent

    @staticmethod
    def _issue(field: str, reason: str):
        return SkillPackageError(SkillValidationReport(errors=[ValidationIssue(field=field, reason=reason)]))

    @staticmethod
    def _render_skill(source: SkillPackageSource, entries: list[dict], *, user_id: int, skill_id: str) -> str:
        """标准 YAML 字段与平台元信息分开；正文只采用用户提供的内容。"""
        metadata = {"version": source.version, "skill_id": skill_id, "creator_id": str(user_id),
                    "display_name": source.display_name}
        for field in ("skill_class_id", "application", "model_tier"):
            value = getattr(source, field)
            if value:
                metadata[field] = value
        header = {"name": source.name, "description": source.description}
        if source.compatibility:
            header["compatibility"] = source.compatibility
        header["metadata"] = metadata
        frontmatter = yaml.safe_dump(header, allow_unicode=True, sort_keys=False)
        body = (f"# {source.display_name}\n\n## 功能说明\n\n{source.description}\n\n"
                f"## 执行指令\n\n{source.instructions}\n")
        if source.skill_markdown is not None:
            body = markdown_body(source.skill_markdown) + "\n"
        if entries or source.resource_usage:
            body += "\n<!-- platform-resources:start -->\n"
        if source.resource_usage:
            body += f"\n## 资源使用说明\n\n{source.resource_usage}\n"
        for role, title, label in (("reference", "参考资料", "参考资料"),
                                   ("script", "脚本", "脚本"),
                                   ("asset", "模板与静态资源", "静态资源")):
            group = [entry for entry in entries if entry["role"] == role]
            if not group:
                continue
            body += f"\n## {title}\n\n"
            for index, entry in enumerate(group, start=1):
                body += f"- [{label} {index}]({quote(entry['path'], safe='/')})\n"
                if entry["usage"] and source.resource_usage is None:
                    # 缩进保留多行说明、列表及命令，保持属于当前资源条目。
                    body += "\n" + "\n".join("  " + line for line in entry["usage"].splitlines()) + "\n"
                body += "\n"
        if entries or source.resource_usage:
            body += "<!-- platform-resources:end -->\n"
        return f"---\n{frontmatter}---\n\n{body}"

    def build(self, source: SkillPackageSource, resources: list[ResolvedSkillResource],
              *, user_id: int, skill_id: str) -> dict:
        report = validate_source(source)
        if not report.valid:
            raise SkillPackageError(report)
        if sorted(r.binding_index for r in resources) != list(range(len(source.resources))):
            raise self._issue("resources", "挂载资源未完整解析或出现重复")
        parent = self._parent(user_id, skill_id)
        parent.mkdir(parents=True, exist_ok=True)
        build_id = uuid.uuid4().hex
        final = parent / build_id
        # 临时目录失败时自动清理，成功时原子重命名，不覆盖历史构建。
        with tempfile.TemporaryDirectory(prefix=".building-", dir=parent) as temporary:
            staging = Path(temporary)
            skill_dir = staging / ".claude" / "skills" / source.name
            skill_dir.mkdir(parents=True)
            entries, paths, upload_total = [], set(), 0
            for resource in sorted(resources, key=lambda r: r.binding_index):
                binding = source.resources[resource.binding_index]
                field = f"resources[{resource.binding_index}]"
                try:
                    relative = ROLE_DIRS[binding.role] + "/" + safe_relative_path(binding.target_path or resource.filename)
                except ValueError as exc:
                    raise self._issue(field, str(exc)) from exc
                key = relative.casefold()
                if any(key == p or key.startswith(p + "/") or p.startswith(key + "/") for p in paths):
                    raise self._issue(field, "目标路径与其他文件冲突，请指定不同的 target_path")
                paths.add(key)
                destination = skill_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                try:
                    with resource.path.open("rb") as src, destination.open("xb") as dst:
                        for chunk in iter(lambda: src.read(1024 * 1024), b""):
                            size += len(chunk)
                            if resource.document_id is None:
                                self.check_file_size(size, field)
                                upload_total += len(chunk)
                                if upload_total > self.max_total_bytes:
                                    raise self._issue("files", "直接上传资源合计不能超过 50MiB")
                            digest.update(chunk)
                            dst.write(chunk)
                except OSError as exc:
                    raise self._issue(field, "资源文件不存在、无法读取或无法保存") from exc
                if size == 0:
                    raise self._issue(field, "资源文件为空，请重新选择有效文件")
                sha256 = digest.hexdigest()
                expected = binding.content_hash or resource.expected_hash
                if expected and sha256 != expected:
                    raise self._issue(field, "资源内容已改变，请重新选择或更新固定哈希")
                entries.append({"path": relative, "size": size, "sha256": sha256,
                                "document_id": resource.document_id, "role": binding.role,
                                "category": binding.category, "usage": binding.usage})
            (skill_dir / "SKILL.md").write_text(
                self._render_skill(source, entries, user_id=user_id, skill_id=skill_id), encoding="utf-8")
            self._validate_directory(skill_dir, source.name)
            entries.insert(0, {"path": "SKILL.md", "size": (skill_dir / "SKILL.md").stat().st_size,
                               "sha256": file_hash(skill_dir / "SKILL.md"), "role": "instructions",
                               "document_id": None})
            with zipfile.ZipFile(staging / "package.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for item in entries:
                    archive.write(skill_dir / item["path"], f"{source.name}/{item['path']}")
            manifest = {"build_id": build_id, "skill_id": skill_id, "user_id": user_id,
                        "name": source.name, "version": source.version,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source": source.model_dump(mode="json"), "files": entries,
                        "package_sha256": file_hash(staging / "package.zip"),
                        "status": "succeeded"}
            (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            staging.rename(final)
        return self.read(user_id=user_id, skill_id=skill_id, build_id=build_id)

    def _validate_directory(self, directory: Path, name: str):
        raw = (directory / "SKILL.md").read_text(encoding="utf-8")
        parts = re.match(r"\A---\n(.*?)^---[ \t]*\n(.*)\Z", raw, flags=re.M | re.S)
        if not parts:
            raise self._issue("SKILL.md", "Skill YAML 头部无效")
        header, body = parts[1], parts[2]
        info = yaml.safe_load(header)
        if info.get("name") != name or not info.get("description") or not body.strip():
            raise self._issue("SKILL.md", "Skill 元信息或正文不完整")
        for token in MarkdownIt().parse(body):
            for child in token.children or []:
                if child.type not in {"link_open", "image"}:
                    continue
                reference = child.attrGet("href" if child.type == "link_open" else "src") or ""
                url = urlsplit(reference)
                if url.scheme in {"http", "https", "mailto"}:
                    continue
                if url.scheme or url.netloc:
                    raise self._issue("instructions", "资源链接包含不支持的协议或绝对路径")
                if not url.path:
                    continue
                try:
                    relative = safe_relative_path(unquote(url.path))
                except ValueError as exc:
                    raise self._issue("instructions", "资源引用越界或路径无效") from exc
                target = (directory / relative).resolve()
                if not target.is_relative_to(directory.resolve()) or not target.is_file():
                    raise self._issue("instructions", f"本地资源引用不存在：{relative}")

    def read(self, *, user_id: int, skill_id: str, build_id: str, verify: bool = False) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", build_id):
            raise FileNotFoundError("构建记录不存在")
        directory = self._parent(user_id, skill_id) / build_id
        if not directory.resolve().is_relative_to(self.root):
            raise FileNotFoundError("构建记录不存在")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if (manifest.get("user_id"), manifest.get("skill_id"), manifest.get("build_id")) != (user_id, skill_id, build_id):
            raise FileNotFoundError("构建记录不存在")
        name = manifest.get("name", "")
        if not NAME_RE.fullmatch(name):
            raise self._issue("manifest", "无效的 Skill 技术名")
        skill_dir = directory / ".claude" / "skills" / name
        if not skill_dir.resolve().is_relative_to(directory.resolve()):
            raise self._issue("manifest", "Skill 目录越界")
        if verify:
            expected_paths = {safe_relative_path(item["path"]) for item in manifest["files"]}
            actual_paths = {path.relative_to(skill_dir).as_posix() for path in skill_dir.rglob("*") if path.is_file()}
            if expected_paths != actual_paths:
                raise self._issue("manifest", "构建文件清单与实际目录不一致")
            for item in manifest["files"]:
                path = skill_dir / safe_relative_path(item["path"])
                if (not path.resolve().is_relative_to(skill_dir.resolve()) or not path.is_file()
                        or file_hash(path) != item["sha256"]):
                    raise self._issue("manifest", "构建文件缺失或内容已被修改")
            if file_hash(directory / "package.zip") != manifest["package_sha256"]:
                raise self._issue("manifest", "下载包内容已被修改")
            self._validate_directory(skill_dir, name)
        return {**manifest, "workspace_dir": str(directory), "skill_directory": str(skill_dir)}

    def archive_path(self, *, user_id: int, skill_id: str, build_id: str) -> Path:
        self.read(user_id=user_id, skill_id=skill_id, build_id=build_id, verify=True)
        return self._parent(user_id, skill_id) / build_id / "package.zip"

    def list_builds(self, *, user_id: int, skill_id: str, limit: int = 20, offset: int = 0) -> dict:
        parent = self._parent(user_id, skill_id)
        if not parent.exists():
            return {"items": [], "total": 0}
        directories = [path for path in parent.iterdir()
                       if path.is_dir() and re.fullmatch(r"[0-9a-f]{32}", path.name)]
        directories.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
        items = []
        for directory in directories[offset:offset + limit]:
            record = self.read(user_id=user_id, skill_id=skill_id, build_id=directory.name)
            items.append({key: record[key] for key in ("build_id", "skill_id", "name", "version", "created_at", "status")})
        return {"items": items, "total": len(directories)}
