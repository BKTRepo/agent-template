"""Read an imported skill's original attachments from a verified build."""
from hashlib import sha256
from pathlib import Path
import zipfile

from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_package_builder import safe_relative_path
from common.skill_resource_limits import MAX_SKILL_UPLOAD_FILES
from applications.zhaoyunlong.services.online_debug_file_parser import MAX_ORIGINAL_RESOURCE_BYTES


def read_imported_debug_resources(built: dict) -> list[dict[str, str | bytes]]:
    entries = [entry for entry in built["files"] if entry["path"] != "SKILL.md"]
    if len(entries) > MAX_SKILL_UPLOAD_FILES:
        raise DeveloperError(f'在线测试最多挂载 {MAX_SKILL_UPLOAD_FILES} 个资源文件', 422)
    if sum(entry["size"] for entry in entries) > MAX_ORIGINAL_RESOURCE_BYTES:
        raise DeveloperError('技能附件合计不能超过 50 MB', 422)
    resources = []
    try:
        with zipfile.ZipFile(Path(built["workspace_dir"]) / "package.zip") as archive:
            for entry in entries:
                relative_path = safe_relative_path(entry["path"])
                info = archive.getinfo(f"{built['name']}/{relative_path}")
                if info.file_size != entry["size"]:
                    raise ValueError("附件大小与构建清单不一致")
                content = archive.read(info)
                if sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError("附件内容与构建清单不一致")
                resources.append({"relative_path": relative_path, "content": content})
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise DeveloperError('技能附件构建读取失败，请重新生成技能', 409) from exc
    return resources
