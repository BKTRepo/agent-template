"""Translate shared application paths for a Docker engine outside the app container."""
import os
from pathlib import Path


def docker_source(path: Path) -> Path:
    host_root = os.environ.get('DOCKER_SHARED_HOST_DIR')
    if not host_root:
        return path
    relative = path.resolve().relative_to(Path('/data'))
    return Path(host_root) / relative
