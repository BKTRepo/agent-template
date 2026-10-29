"""展示名称的比较规则；摘要避免数据库排序规则影响唯一性。"""
import hashlib
import unicodedata


class SkillNameError(ValueError):
    pass


def normalized_skill_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise SkillNameError("技能名称必填且最长 128 个字符")
    normalized = unicodedata.normalize("NFKC", value.strip()).strip().lower()
    if not normalized:
        raise SkillNameError("请填写技能名称")
    return normalized


def skill_name_key(value: str) -> str:
    return hashlib.sha256(normalized_skill_name(value).encode("utf-8")).hexdigest()
