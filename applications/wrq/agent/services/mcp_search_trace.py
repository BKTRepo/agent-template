"""File-backed diagnostics keyed by the existing knowledge tool call ID."""
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from configure import PROJECT_CONFIG


SEARCH_ID_PATTERN = r'^[0-9a-f]{32}$'


def _trace_path(search_id):
    if not re.fullmatch(SEARCH_ID_PATTERN, search_id):
        raise ValueError('Invalid MCP search ID')
    return Path(PROJECT_CONFIG.OUTPUT_DIR) / 'mcp-search-traces' / f'{search_id}.json'


def write_trace(search_id, trace):
    path = _trace_path(search_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(trace, stream, ensure_ascii=False, allow_nan=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_trace(search_id):
    try:
        return json.loads(_trace_path(search_id).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
