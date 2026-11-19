"""Private OS-temporary staging, bounded storage and cross-worker filesystem leases."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from configure import PROJECT_CONFIG
from .developer_skill_crud import DeveloperError

CAPACITY_LOCK = '0' * 32


class ImportTempStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, identifier):
        if len(identifier) != 32 or any(char not in '0123456789abcdef' for char in identifier):
            raise DeveloperError('导入编号无效')
        path = self.root / identifier
        if path.is_symlink() or path.resolve().parent != self.root:
            raise DeveloperError('临时目录记录无效')
        return path

    def ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (self.root / '.locks').is_symlink():
            raise DeveloperError('导入临时锁目录无效，请检查临时目录配置')
        (self.root / '.locks').mkdir(exist_ok=True, mode=0o700)

    @staticmethod
    def owner_alive(pid):
        if pid == os.getpid():
            return True
        if pid <= 0:
            return False
        if os.name == 'nt':
            # os.kill(pid, 0) is not a safe liveness probe on Windows.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87  # Invalid PID; access denied stays protected.
            try:
                status = wintypes.DWORD()
                kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259
            finally:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def reclaim_lock(self, lock):
        try:
            if lock.is_symlink():
                return False
            token = lock.read_text()
            try:
                if ':' not in token:
                    raise ValueError('legacy lease')
                owner = int(token.split(':', 1)[0])
                if not 0 < owner <= 0xffffffff:
                    raise ValueError('invalid owner')
                abandoned = not self.owner_alive(owner)
            except ValueError:
                abandoned = lock.stat().st_mtime < time.time() - PROJECT_CONFIG.SKILL_IMPORT_EXPIRE_HOURS * 3600
            if abandoned and lock.read_text() == token:
                lock.unlink(missing_ok=True)
                return True
        except FileNotFoundError:
            return True
        return False

    @contextmanager
    def try_lock(self, identifier):
        self.path(identifier)
        self.ensure_root()
        lock = self.root / '.locks' / identifier
        token = f'{os.getpid()}:{uuid.uuid4().hex}'
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not self.reclaim_lock(lock):
                yield False
                return
            try:
                descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                yield False
                return
        try:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(token)
            yield True
        finally:
            try:
                if lock.read_text() == token:
                    lock.unlink()
            except FileNotFoundError:
                pass

    @asynccontextmanager
    async def lock(self, identifier):
        self.ensure_root()
        for _ in range(300):
            with self.try_lock(identifier) as acquired:
                if acquired:
                    yield
                    return
            await asyncio.sleep(0.1)
        raise DeveloperError('当前导入正在处理，请稍后重试', 409)

    def read(self, identifier, owner=None):
        manifest = self.path(identifier) / 'stage.json'
        try:
            if manifest.is_symlink() or manifest.stat().st_size > 32 * 1024 * 1024:
                raise DeveloperError('临时导入记录无效，请重新上传')
            value = json.loads(manifest.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise DeveloperError('临时文件已被清理或不存在，请重新上传', 410) from None
        except (ValueError, KeyError, TypeError) as exc:
            raise DeveloperError('临时导入记录无效，请重新上传') from exc
        if owner is not None and value.get('owner_login') != owner:
            raise DeveloperError('导入批次不存在或无权访问', 404)
        if value['expires_at'] <= time.time():
            raise DeveloperError('临时文件已过期，请重新上传', 410)
        return value

    def write(self, identifier, value):
        encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.prune(required=len(encoded) * 2, protected={identifier})
        target = self.path(identifier) / 'stage.json'
        pending = target.with_suffix('.pending')
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)

    @staticmethod
    def tree_size(path):
        total = 0
        for entry in path.rglob('*'):
            try:
                if not entry.is_symlink() and entry.is_file():
                    total += entry.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def prune(self, required=0, protected=frozenset()):
        self.ensure_root()
        current = time.time()
        ttl = PROJECT_CONFIG.SKILL_IMPORT_EXPIRE_HOURS * 3600
        # Only stale leases left by crashed workers are eligible for recovery.
        for lock in (self.root / '.locks').iterdir():
            try:
                if lock.name != CAPACITY_LOCK:
                    self.reclaim_lock(lock)
            except FileNotFoundError:
                pass
        candidates = []
        for entry in self.root.iterdir():
            if entry.name == '.locks' or entry.is_symlink() or not entry.is_dir():
                continue
            try:
                checked = self.path(entry.name)
            except DeveloperError:
                continue
            try:
                modified = checked.stat().st_mtime
            except FileNotFoundError:
                continue
            expiry = modified + ttl
            manifest = checked / 'stage.json'
            if manifest.is_file() and not manifest.is_symlink():
                try:
                    expiry = float(json.loads(manifest.read_text(encoding='utf-8'))['expires_at'])
                except (ValueError, KeyError, TypeError, FileNotFoundError):
                    pass
            candidates.append((expiry, modified, checked, self.tree_size(checked)))
        used = sum(row[3] for row in candidates)
        removed = 0
        for expiry, _, path, size in sorted(candidates, key=lambda row: (row[0] > current, row[1])):
            pressure = used + required > PROJECT_CONFIG.SKILL_IMPORT_TMP_MAX_BYTES or shutil.disk_usage(self.root).free - required < PROJECT_CONFIG.SKILL_IMPORT_TMP_MIN_FREE_BYTES
            if expiry > current and not pressure:
                continue
            if path.name in protected:
                continue
            with self.try_lock(path.name) as acquired:
                if not acquired:
                    continue
                # Resolve again immediately before recursive deletion; never touch /tmp itself.
                checked = self.path(path.name)
                if checked.exists():
                    shutil.rmtree(checked)
                used -= size
                removed += 1
        if used + required > PROJECT_CONFIG.SKILL_IMPORT_TMP_MAX_BYTES or shutil.disk_usage(self.root).free - required < PROJECT_CONFIG.SKILL_IMPORT_TMP_MIN_FREE_BYTES:
            raise DeveloperError('导入临时空间不足，请稍后重试或减少上传文件', 507)
        return removed
