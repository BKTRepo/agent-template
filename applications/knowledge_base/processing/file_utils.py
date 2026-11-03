from core.exceptions import ParameterException

def sanitize_upload_filename(raw: str, max_length: int = 200) -> str:
    """返回安全的纯文件名，拒绝路径穿越、控制字符和非法尾缀。"""
    if not raw:
        raise ParameterException(message="未提供文件名")
    name = raw.replace("\\", "/").strip().rsplit("/", 1)[-1].strip()
    if (
        not name
        or name in (".", "..")
        or name != name.strip(". ")
        or any(ord(ch) < 32 for ch in name)
        or len(name) > max_length
    ):
        raise ParameterException(message="文件名不合法")
    return name

async def read_upload_with_cap(file, max_bytes: int) -> bytes:
    """分块读取上传文件，并对伪造 Content-Length 的请求实施硬上限。"""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(4 * 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ParameterException(
                message=f"文件超过 {max_bytes // (1024 * 1024)}MB 限制"
            )
        chunks.append(chunk)
    return b"".join(chunks)
