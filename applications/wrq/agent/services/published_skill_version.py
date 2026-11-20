"""呈现发布版本，同时保留沙箱实际调试的原始构建。"""
import json
import re


def strip_generated_resource_notes(markdown: str) -> str:
    """Remove the platform-marked attachment section of an older imported build."""
    return re.sub(r'^<!-- platform-resources:start -->[^\r\n]*\r?\n.*?^<!-- platform-resources:end -->[ \t]*(?:\r?\n|$)',
                  '', markdown, flags=re.M | re.S)


def display_skill_version(markdown: str, version: str | None, *, allow_missing_metadata: bool = False,
                          omit_resource_notes: bool = False) -> str:
    """呈现发布版本；导入技能可隐藏历史构建中自动加入的附件区。"""
    if omit_resource_notes:
        markdown = strip_generated_resource_notes(markdown)
    front = re.match(r'\A---\s*\r?\n(?P<header>.*?)^---[ \t]*\r?\n', markdown, re.M | re.S)
    if not front:
        raise ValueError('Skill YAML 头部无效')
    header = front.group('header')
    if allow_missing_metadata:
        # Imported drafts may predate platform metadata. Adapt the presentation
        # without rewriting the stored source file or changing published rules.
        import yaml
        parsed = yaml.safe_load(header)
        if not isinstance(parsed, dict):
            raise ValueError('Skill YAML 头部无效')
        metadata = parsed.get('metadata')
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata['version'] = version or '-'
        parsed['metadata'] = metadata
        header = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        return markdown[:front.start('header')] + header + markdown[front.end('header'):]
    metadata = re.search(r'^metadata:[ \t]*\r?\n(?P<body>(?:[ \t]+[^\r\n]*\r?\n|\r?\n)*)', header, re.M)
    if not metadata:
        raise ValueError('Skill 缺少 metadata')
    body = metadata.group('body')
    replacement = '  version: ' + json.dumps(version or '-', ensure_ascii=False)
    body, count = re.subn(r'^  version:[^\r\n]*', lambda _: replacement, body, count=1, flags=re.M)
    if count != 1:
        raise ValueError('Skill 缺少 metadata.version')
    header = header[:metadata.start('body')] + body + header[metadata.end('body'):]
    return markdown[:front.start('header')] + header + markdown[front.end('header'):]
