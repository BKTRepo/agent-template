"""Update only selected OOXML package members and retain unrelated parts verbatim."""

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from lxml import etree

MAX_EXPANDED_BYTES = 64 * 1024 * 1024


def check_package(content: bytes):
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if sum(member.file_size for member in members) > MAX_EXPANDED_BYTES:
                raise HTTPException(413, "Office 文件解压后超过在线处理上限")
            if len({member.filename for member in members}) != len(members):
                raise ValueError("duplicate package part")
    except (BadZipFile, ValueError) as exc:
        raise HTTPException(422, "Office 文件损坏或格式不支持") from exc


def xml_root(data: bytes):
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def xml_bytes(root):
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def rewrite_package(content: bytes, replacements: dict[str, bytes], removed=()) -> bytes:
    target = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(target, "w") as output:
        output.comment = source.comment
        for entry in source.infolist():
            if entry.filename not in removed:
                value = replacements.get(entry.filename)
                output.writestr(entry, source.read(entry) if value is None else value)
    return target.getvalue()
