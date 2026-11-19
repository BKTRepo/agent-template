"""Parse Skill frontmatter and keep imported definitions editable without losing metadata."""
import re
import yaml
from .developer_skill_crud import DeveloperError


def parse_definition(raw):
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n")
    match = re.match(r"\A---[ \t]*\n(.*?)^---[ \t]*(?:\n|$)(.*)\Z", raw, re.M | re.S)
    if not match:
        raise DeveloperError("SKILL.md 缺少完整的 YAML 头部")
    try:
        # Alias graphs can expand without relation to upload size; definitions use plain fields.
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(match[1])):
            raise DeveloperError("Skill YAML 不支持锚点或别名，请展开为普通字段")
        header = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise DeveloperError("SKILL.md 的 YAML 格式无效") from exc
    if not isinstance(header, dict) or not all(isinstance(key, str) for key in header):
        raise DeveloperError("SKILL.md 的 YAML 必须是字段对象")
    description = header.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise DeveloperError("description 必须为非空文本且不超过1024字符")
    body = match[2].strip()
    if not body or len(body) > 100000:
        raise DeveloperError("SKILL.md 正文必须非空且不超过100000字符")
    compatibility = header.get("compatibility", "")
    if not isinstance(compatibility, str) or len(compatibility) > 500:
        raise DeveloperError("compatibility 必须为文本且不超过500字符")
    return header, body


def sync_definition(raw, data, technical_name, *, version=None):
    header, _ = parse_definition(raw)
    header.update(name=technical_name, description=data.description, compatibility=data.compatibility or "")
    metadata = header.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata.update(version=version or "-", display_name=data.name, skill_class_id=data.class_id, application_paso=data.effective_application_paso)
    header["metadata"] = metadata
    # 资源区由构建器重新生成，编辑正文时也剔除旧的自动生成区。
    body = re.sub(r"<!-- platform-resources:start -->.*?<!-- platform-resources:end -->", "", data.instructions, flags=re.S).strip()
    return "---\n" + yaml.safe_dump(header, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n"
