"""Bind resumable chunk artifacts to the source and splitter settings that made them."""
import hashlib
import json
from pathlib import Path


def chunk_source_fingerprint(markdown, *, filename, config, multimodal, source_paths):
    sources = []
    for path in source_paths:
        file = Path(path) if path else None
        sources.append(hashlib.sha256(file.read_bytes()).hexdigest()
                       if file and file.is_file() else None)
    payload = {"version": 1, "markdown": markdown, "filename": filename,
               "config": config, "multimodal": multimodal, "sources": sources}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def chunk_cache_matches(chunks_file, fingerprint):
    file = Path(chunks_file)
    try:
        meta = json.loads(file.with_name("chunks_meta.json").read_text(encoding="utf-8"))
        return (meta.get("version") == 1
                and meta.get("source_sha256") == fingerprint
                and meta.get("chunks_sha256") == hashlib.sha256(file.read_bytes()).hexdigest())
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def save_chunk_cache_metadata(chunks_file, fingerprint):
    file = Path(chunks_file)
    meta = {"version": 1, "source_sha256": fingerprint,
            "chunks_sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    target = file.with_name("chunks_meta.json")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
