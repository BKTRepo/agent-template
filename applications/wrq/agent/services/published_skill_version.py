"""呈现发布版本，同时保留沙箱实际调试的原始构建。"""
import json
import re


def display_skill_version(markdown: str, version: str | None) -> str:
    """只替换 YAML 头部 metadata.version，不触碰正文或其他 version 字段。"""
    front = re.match(r'\A---\s*\r?\n(?P<header>.*?)^---[ \t]*\r?\n', markdown, re.M | re.S)
    if not front:
        raise ValueError('Skill YAML 头部无效')
    header = front.group('header')
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
