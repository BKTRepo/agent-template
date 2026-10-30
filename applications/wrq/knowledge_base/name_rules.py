"""与数据库无关的名称归一化，供表单和迁移审计复用。"""
import hashlib
import unicodedata


def name_key(name):
    return hashlib.sha256(unicodedata.normalize("NFKC", name.strip()).casefold().encode()).hexdigest()
