"""Stage Skill uploads, validate roots, and atomically create one draft per candidate."""
import asyncio
from datetime import timedelta
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import unicodedata
import uuid
import zipfile
import struct
import zlib
import yaml
import tempfile
from datetime import datetime
from types import SimpleNamespace

import anyio
from pydantic import ValidationError
from tortoise.exceptions import IntegrityError
from tortoise.timezone import now
from tortoise.transactions import in_transaction

from configure import PROJECT_CONFIG, LOGGER
from common.skill_resource_limits import MAX_SKILL_UPLOAD_FILES
from applications.wrq.auth import user_login_name
from applications.wrq.markdown_storage import discard_markdown, read_markdown
from applications.wrq.agent.models.agent_model import SkillImportBatch, SkillImportItem, Source, ResourceCategory, SkillForm, SkillResourceBinding, Skill
from applications.wrq.agent.skill_names import normalized_skill_name
from applications.wrq.agent.schemas.agent_schema import DeveloperSkillForm
from .developer_skill_crud import DeveloperSkillCrud, DeveloperError
from .skill_definition import parse_definition
from .skill_import_temp import ImportTempStore, CAPACITY_LOCK
from .skill_package_builder import NAME_RE, RESERVED_NAMES, SkillPackageBuilder, SkillPackageError, safe_relative_path, file_hash

MiB = 1024 * 1024
DEFAULT_USAGE = "相关参考资料、模板及脚本见附件，请结合执行指令使用。"


def import_limits():
    return {"max_batch_bytes": PROJECT_CONFIG.SKILL_IMPORT_MAX_BATCH_BYTES,
            "max_file_bytes": 50 * MiB, "max_skill_bytes": 50 * MiB,
            "max_files": 1000, "max_skills": 50, "max_skill_files": MAX_SKILL_UPLOAD_FILES + 1,
            "expires_hours": PROJECT_CONFIG.SKILL_IMPORT_EXPIRE_HOURS}



def zip_entry_path(info):
    """Decode UTF-8/Unicode-path ZIP names and legacy Chinese Windows archives.

    Keep ZipInfo unchanged: archive.open() checks its original decoded name
    against the local header. Only our validated logical path uses this value.
    """
    original = info.orig_filename
    if info.flag_bits & 0x800:
        return original
    raw = original.encode('cp437')
    extra = info.extra
    offset = 0
    while offset + 4 <= len(extra):
        kind, length = struct.unpack_from('<HH', extra, offset)
        value = extra[offset + 4:offset + 4 + length]
        offset += 4 + length
        if kind == 0x7075 and len(value) >= 5 and value[0] == 1:
            checksum = struct.unpack_from('<I', value, 1)[0]
            if checksum == zlib.crc32(raw) & 0xffffffff:
                try:
                    return value[5:].decode('utf-8')
                except UnicodeDecodeError:
                    pass
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    try:
        chinese = raw.decode('gb18030')
    except UnicodeDecodeError:
        return original
    if any('\u3400' <= char <= '\u9fff' or '\U00020000' <= char <= '\U0002fa1f' for char in chinese):
        return chinese
    return original


def path_key(path):
    return unicodedata.normalize("NFKC", path).casefold()


def check_path(path):
    if '\ufffd' in path:
        raise DeveloperError(
            f"文件或目录名称已损坏（包含�）：{path}。"
            "请从原始压缩包按正确编码重新解压，确认中文名称正常后再打包上传；也可直接选择原始ZIP。"
        )
    try:
        safe_relative_path(path)
    except ValueError as exc:
        raise DeveloperError(f"{path}：{exc}") from exc
    return path



def invalid_candidate(path, message):
    return {"id": uuid.uuid4().hex, "root_path": path,
            "default_name": PurePosixPath(path).name[:128] or "未识别文件",
            "payload": {}, "status": "INVALID", "errors": [message]}


def unpack_skill_zip(entry, directory, limits, budget, selected_root=None, prefix='', ensure_space=None):
    """Return logical files while preserving each archive as an isolated namespace."""
    extracted = []
    try:
        with zipfile.ZipFile(directory / entry["storage"]) as archive:
            if len(archive.infolist()) > limits["max_files"] * 2:
                raise DeveloperError("ZIP条目过多")
            for info in archive.infolist():
                logical_path = zip_entry_path(info)
                scoped_path = prefix + logical_path.rstrip('/')
                if selected_root is not None and selected_root != '.' and not (
                    scoped_path == selected_root or scoped_path.startswith(selected_root + '/') or selected_root.startswith(scoped_path + '/')
                ):
                    continue
                check_path(logical_path.rstrip("/"))
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise DeveloperError("ZIP不支持符号链接或特殊文件")
                if info.flag_bits & 1:
                    raise DeveloperError("不支持加密ZIP")
                if info.is_dir():
                    continue
                if info.file_size > limits["max_file_bytes"]:
                    raise DeveloperError("ZIP内单文件超过50MiB")
                target, count, hashed = uuid.uuid4().hex, 0, hashlib.sha256()
                extracted.append(dict(path=logical_path, storage=target, size=0, sha256=""))
                with archive.open(info) as src, (directory / target).open("xb") as dst:
                    for chunk in iter(lambda: src.read(MiB), b""):
                        if ensure_space:
                            ensure_space(len(chunk))
                        budget['bytes'] += len(chunk)
                        count += len(chunk)
                        if budget['bytes'] > limits["max_batch_bytes"] or count > limits["max_file_bytes"]:
                            raise DeveloperError("ZIP解压后的内容超过批次大小限制")
                        hashed.update(chunk)
                        dst.write(chunk)
                budget['files'] += 1
                if budget['files'] > limits['max_files']:
                    raise DeveloperError("解压后的批次文件总数超过1000个")
                extracted[-1].update(size=count, sha256=hashed.hexdigest())
        return extracted
    except BaseException:
        for item in extracted:
            (directory / item['storage']).unlink(missing_ok=True)
        raise


def inspect_skills(entries, directory, limits, ensure_space=None):
    """Entries contain only server-generated storage names and validated relative paths."""
    definitions = [entry for entry in entries if PurePosixPath(entry["path"]).name.casefold() == "skill.md"]
    if len(definitions) > limits["max_skills"]:
        raise DeveloperError("一次最多导入50个技能")
    roots = [str(PurePosixPath(entry["path"]).parent) for entry in definitions]
    unassigned = [entry["path"] for entry in entries if not any(root == "." or entry["path"].startswith(root + "/") for root in roots)]
    if unassigned:
        raise DeveloperError("上传目录包含不属于任何Skill的无关文件，请移除后重新上传：" + "、".join(unassigned[:10]))
    result = []
    for definition, root in zip(definitions, roots):
        item = {"id": uuid.uuid4().hex, "root_path": root, "default_name": PurePosixPath(root).name[:128] or "导入技能",
                "payload": {}, "status": "READY", "errors": []}
        try:
            if any(other != root and (root == "." or other.startswith(root + "/")) for other in roots):
                raise DeveloperError("父子目录同时包含SKILL.md，技能根目录重叠")
            prefix = "" if root == "." else root + "/"
            files = [dict(entry, relative_path=entry["path"][len(prefix):]) for entry in entries if entry["path"].startswith(prefix)]
            if len(files) > limits["max_skill_files"]:
                raise DeveloperError(f'每个技能最多导入 {limits["max_skill_files"] - 1} 个附件')
            if sum(f["size"] for f in files if f["path"] != definition["path"]) > limits["max_skill_bytes"]:
                raise DeveloperError("单技能附件合计不超过50MiB")
            raw = (directory / definition["storage"]).read_bytes().decode("utf-8-sig")
            if len(raw) > 200000:
                raise DeveloperError("SKILL.md不能超过200000字符")
            header, body = parse_definition(raw)
            technical = header.get("name", "")
            if technical and (not isinstance(technical, str) or len(technical) > 64 or not NAME_RE.fullmatch(technical) or technical.upper() in RESERVED_NAMES):
                raise DeveloperError("name需使用小写英文、数字和单个连字符，最长64字符")
            if root == ".":
                item["default_name"] = technical or "导入技能"
            # Validate static Markdown links using a temporary tree with the original paths.
            check_dir = directory / ("check-" + item["id"])
            if ensure_space:
                ensure_space(sum(entry['size'] for entry in files) + MiB)
            check_dir.mkdir()
            try:
                for entry in files:
                    destination = check_dir / ("SKILL.md" if entry["path"] == definition["path"] else entry["relative_path"])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(directory / entry["storage"], destination)
                normalized = "---\n" + yaml.safe_dump({**header, "name": technical or "imported-skill"}, allow_unicode=True) + "---\n\n" + body + "\n"
                (check_dir / "SKILL.md").write_text(normalized, encoding="utf-8")
                SkillPackageBuilder(directory)._validate_directory(check_dir, technical or "imported-skill")
            finally:
                shutil.rmtree(check_dir)
            item["payload"] = {"markdown_storage": definition["storage"], "markdown_hash": definition["sha256"],
                               "description": header["description"], "technical_name": technical, "instructions": body,
                               "compatibility": header.get("compatibility", ""),
                               "source_path": definition.get("source_path", definition["path"]),
                               "source_size": definition.get("source_size", definition["size"]),
                               "attachments": [f for f in files if f["path"] != definition["path"]]}
        except (ValueError, UnicodeDecodeError, SkillPackageError) as exc:
            item["status"] = "INVALID"
            item["errors"] = ([issue.reason for issue in exc.report.errors] if isinstance(exc, SkillPackageError) else [str(exc)])
        result.append(item)
    return result


class SkillImportService:
    def __init__(self, root=None, staging_root=None):
        self.root = Path(root or PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()
        default_tmp = self.root / 'tmp-imports' if root is not None else Path('/tmp' if os.name != 'nt' else tempfile.gettempdir()) / 'keenrobot-skill-import'
        self.temp = ImportTempStore(staging_root or PROJECT_CONFIG.SKILL_IMPORT_TMP_DIR or default_tmp)
        self.staging = self.temp.root
        shared_tmp = {Path('/tmp').resolve(), Path('/var/tmp').resolve(), Path(tempfile.gettempdir()).resolve()}
        if self.staging in shared_tmp or self.staging.parent == self.staging:
            raise DeveloperError('导入暂存必须使用专用子目录，不能使用系统临时根目录')
        if root is None and self.staging.is_relative_to(self.root):
            raise DeveloperError('导入暂存不能放在产物目录下，请配置系统临时子目录')
        self.crud = DeveloperSkillCrud()

    def directory(self, batch_id):
        return self.temp.path(batch_id)

    async def cleanup_expired(self):
        with self.temp.try_lock(CAPACITY_LOCK) as acquired:
            if acquired:
                return await asyncio.to_thread(self.temp.prune)

    async def prepare(self, uploads, manifest, user, *, defer_persistence=False):
        async with self.temp.lock(CAPACITY_LOCK):
            await asyncio.to_thread(self.temp.prune)
            try:
                return await self._prepare(uploads, manifest, user, defer_persistence=defer_persistence)
            except OSError as exc:
                if exc.errno in (28, 122):
                    raise DeveloperError('导入临时空间不足，请稍后重试或减少文件', 507) from exc
                if exc.errno == 2:
                    raise DeveloperError('临时文件已被清理，请重新上传', 410) from exc
                raise

    async def _prepare(self, uploads, manifest, user, *, defer_persistence=False):
        limits = import_limits()
        if sorted(entry.index for entry in manifest.files) != list(range(len(uploads))):
            raise DeveloperError("文件清单与上传文件不一致")
        if manifest.upload_mode in ("file", "zip") and len(uploads) != 1:
            raise DeveloperError("文件入口每次请选择一个SKILL.md或ZIP")
        batch_id = uuid.uuid4().hex
        directory = self.directory(batch_id)
        directory.mkdir(parents=True, mode=0o700)
        ensure_space = lambda size: self.temp.prune(required=size, protected={batch_id})
        entries, seen, total = [], set(), 0
        committed = False

        def register(path, storage, size, digest):
            check_path(path)
            key = path_key(path)
            if any(key == old or key.startswith(old + "/") or old.startswith(key + "/") for old in seen):
                raise DeveloperError(f"文件路径重复或冲突：{path}")
            seen.add(key)
            if len(seen) > limits["max_files"]:
                raise DeveloperError("一次最多上传1000个文件")
            entries.append(dict(path=path, storage=storage, size=size, sha256=digest))

        try:
            for spec in manifest.files:
                path = check_path(spec.path)
                if manifest.upload_mode == "file" and ("/" in path or path.casefold() != "skill.md"):
                    raise DeveloperError("单文件入口只支持SKILL.md")
                if manifest.upload_mode == "zip" and not path.lower().endswith(".zip"):
                    raise DeveloperError("请选择ZIP压缩包")
                storage = uuid.uuid4().hex
                digest, size = hashlib.sha256(), 0
                async with await anyio.open_file(directory / storage, "xb") as stream:
                    while chunk := await uploads[spec.index].read(MiB):
                        size += len(chunk)
                        total += len(chunk)
                        if size > limits["max_file_bytes"]:
                            raise DeveloperError(f"单文件超过上传大小限制：{path}")
                        if total > limits["max_batch_bytes"]:
                            raise DeveloperError("上传内容超过批次大小限制")
                        digest.update(chunk)
                        await asyncio.to_thread(ensure_space, len(chunk))
                        await stream.write(chunk)
                register(path, storage, size, digest.hexdigest())
                entries[-1].update(source_path=path,source_size=size)
            invalid = []
            budget = {'bytes': total, 'files': len(entries)}
            while True:
                roots = [str(PurePosixPath(item['path']).parent) for item in entries
                         if PurePosixPath(item['path']).name.casefold() == 'skill.md']
                containers = [item for item in entries if item['path'].lower().endswith('.zip')
                              and not any(root == '.' or item['path'].startswith(root + '/') for root in roots)]
                if not containers:
                    break
                for container in containers:
                    entries.remove(container)
                    seen.remove(path_key(container['path']))
                    prefix = '' if manifest.upload_mode == 'zip' and container['path'] == manifest.files[0].path else container['path'] + '/'
                    try:
                        extracted = await asyncio.to_thread(unpack_skill_zip, container, directory, limits, budget, manifest.selected_root, prefix, ensure_space)
                    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeDecodeError, EOFError, zlib.error):
                        invalid.append(invalid_candidate(container['path'], 'ZIP损坏、已加密或压缩格式不支持'))
                        continue
                    # Global budget failures and unsafe paths still reject the request.
                    # Namespace every folder-contained ZIP so identical inner names cannot collide.
                    if not any(PurePosixPath(item['path']).name.casefold() == 'skill.md' or item['path'].lower().endswith('.zip') for item in extracted):
                        invalid.append(invalid_candidate(container['path'], '压缩包中未找到SKILL.md，已排除导入'))
                        for item in extracted:
                            (directory / item['storage']).unlink(missing_ok=True)
                        continue
                    for item in extracted:
                        register(prefix + item['path'], item['storage'], item['size'], item['sha256'])
                        entries[-1].update(source_path=container.get('source_path',container['path']),source_size=container.get('source_size',container['size']))
                    (directory / container['storage']).unlink(missing_ok=True)
            if manifest.selected_root is not None:
                root = manifest.selected_root
                if root != '.':
                    check_path(root)
                roots = [str(PurePosixPath(entry['path']).parent) for entry in entries if PurePosixPath(entry['path']).name.casefold() == 'skill.md']
                if root in roots and any(other != root and (root == '.' or other == '.' or root.startswith(other + '/') or other.startswith(root + '/')) for other in roots):
                    raise DeveloperError('父子目录同时包含SKILL.md，技能根目录重叠')
                if root not in roots and not any(root == entry['root_path'] or entry['root_path'].startswith(root + '/') for entry in invalid):
                    raise DeveloperError('所选条目未包含SKILL.md，无法导入为技能')
                entries = [entry for entry in entries if root == '.' or entry['path'].startswith(root + '/') or entry['path'] == root]
                invalid = [entry for entry in invalid if root == '.' or entry['root_path'].startswith(root + '/') or entry['root_path'] == root]
            if invalid:
                details = "；".join(item['root_path'] + '：' + item['errors'][0] for item in invalid[:10])
                raise DeveloperError('上传目录包含无法识别为Skill的文件或压缩包，请移除后重新上传：' + details)
            candidates = await asyncio.to_thread(inspect_skills, entries, directory, limits, ensure_space)
            if not candidates:
                raise DeveloperError('未找到可识别的技能文件，请选择包含SKILL.md的目录或ZIP')
            # When SKILL.md sits directly inside a contained ZIP, use its archive stem as the display name.
            for item in candidates:
                if item['status'] == 'READY' and item['root_path'] == item['payload'].get('source_path') and item['root_path'].lower().endswith('.zip'):
                    item['default_name'] = PurePosixPath(item['root_path']).stem[:128]
            if defer_persistence:
                if manifest.replaces_import_id:
                    await self._link_replacement_candidates(candidates, manifest.replaces_import_id, user)
                accepted_files = set()
                for candidate in candidates:
                    if candidate['status'] == 'READY':
                        accepted_files.add(candidate['payload']['markdown_storage'])
                        accepted_files.update(item['storage'] for item in candidate['payload']['attachments'])
                for path in directory.iterdir():
                    if path.is_file() and len(path.name) == 32 and all(char in '0123456789abcdef' for char in path.name) and path.name not in accepted_files:
                        path.unlink()
                staged = {'id': batch_id, 'owner_login': user_login_name(user), 'upload_mode': manifest.upload_mode,
                          'expires_at': (now() + timedelta(hours=limits['expires_hours'])).timestamp(), 'items': candidates}
                await asyncio.to_thread(self.temp.write, batch_id, staged)
                response = await self.status(batch_id, user)
                if not any(item['status'] == 'READY' for item in candidates):
                    await asyncio.to_thread(shutil.rmtree, self.directory(batch_id))
                committed = True
                return response
            async with in_transaction() as db:
                if manifest.replaces_import_id:
                    base = await SkillImportBatch.filter(id=manifest.replaces_import_id, owner_login=user_login_name(user)).using_db(db).select_for_update().first()
                    if not base:
                        raise DeveloperError('原导入批次不存在或无权访问', 404)
                    previous = list(await SkillImportItem.filter(batch_id=base.id).using_db(db))
                    if len(previous) != len(candidates):
                        raise DeveloperError('重新选择的技能数量与原批次不一致，请保持原技能对应关系')
                    for candidate in candidates:
                        matches = [row for row in previous if row.root_path == candidate['root_path']]
                        if not matches and candidate['payload'].get('technical_name'):
                            matches = [row for row in previous if row.payload.get('technical_name') == candidate['payload']['technical_name']]
                        if not matches:
                            matches = [row for row in previous if row.default_name == candidate['default_name']]
                        if not matches and len(candidates) == 1:
                            matches = previous[:]
                        if len(matches) != 1:
                            raise DeveloperError('重新选择的技能无法与原条目唯一对应，请保持技能目录名称或name字段一致')
                        original = matches[0]
                        previous.remove(original)
                        candidate['selection'] = {**original.selection, 'item_id': candidate['id']}
                        if original.skill_id:
                            skill = await self.crud.get(original.skill_id, user, db)
                            candidate['skill_id'] = skill.id
                            candidate['payload'].update(replace_content=True, edit_revision=skill.current_revision)
                            candidate['selection']['expected_revision'] = candidate['payload']['edit_revision']
                await SkillImportBatch.create(using_db=db, id=batch_id, owner_login=user_login_name(user), upload_mode=manifest.upload_mode,
                                              expires_at=now() + timedelta(hours=limits["expires_hours"]))
                for item in candidates:
                    await SkillImportItem.create(using_db=db, batch_id=batch_id, **item)
            committed = True
            return await self.status(batch_id, user)
        except BaseException:
            if not committed:
                await asyncio.to_thread(shutil.rmtree, directory, True)
            raise

    async def _link_replacement_candidates(self, candidates, base_id, user):
        previous = list(await self._rows(base_id, user))
        if len(previous) != len(candidates):
            raise DeveloperError('重新选择的技能数量与原批次不一致，请保持原技能对应关系')
        for candidate in candidates:
            matches = [row for row in previous if row.root_path == candidate['root_path']]
            if not matches and candidate['payload'].get('technical_name'):
                matches = [row for row in previous if row.payload.get('technical_name') == candidate['payload']['technical_name']]
            if not matches:
                matches = [row for row in previous if row.default_name == candidate['default_name']]
            if not matches and len(candidates) == 1:
                matches = previous[:]
            if len(matches) != 1:
                raise DeveloperError('重新选择的技能无法与原条目唯一对应，请保持技能目录名称或name字段一致')
            original = matches[0]
            previous.remove(original)
            candidate['selection'] = {**original.selection, 'item_id': candidate['id']}
            if original.skill_id:
                skill = await self.crud.get(original.skill_id, user)
                candidate['skill_id'] = skill.id
                revision = skill.current_revision
                candidate['payload'].update(replace_content=True, edit_revision=revision)
                candidate['selection']['expected_revision'] = revision

    async def _materialize(self, batch_id, user):
        batch = await self.batch(batch_id, user)
        if not getattr(batch, 'pending', False):
            return
        staged = self.temp.read(batch_id, user_login_name(user))
        async with in_transaction() as db:
            await self.crud.lock_name_catalog(db)
            if await SkillImportBatch.filter(id=batch_id).using_db(db).exists():
                return
            await SkillImportBatch.create(using_db=db, id=batch_id, owner_login=batch.owner_login,
                upload_mode=batch.upload_mode, expires_at=batch.expires_at)
            for item in staged['items']:
                await SkillImportItem.create(using_db=db, batch_id=batch_id, **item)

    async def discard(self, batch_id, user):
        async with self.temp.lock(batch_id):
            await self.batch(batch_id, user)
            path = self.directory(batch_id)
            if path.exists():
                await asyncio.to_thread(shutil.rmtree, path)

    async def restart(self, batch_id, user):
        async with self.temp.lock(batch_id):
            await self._materialize(batch_id, user)
            return await self._restart(batch_id, user)

    async def _restart(self, batch_id, user):
        """Reopen the same candidates, retaining each imported skill's identity."""
        await self.batch(batch_id, user)
        async with in_transaction() as db:
            batch = await SkillImportBatch.filter(id=batch_id, owner_login=user_login_name(user)).using_db(db).select_for_update().first()
            if not batch:
                raise DeveloperError("暂存文件已过期，请重新选择文件上传")
            rows = await SkillImportItem.filter(batch_id=batch_id).using_db(db).order_by('created_time', 'id')
            for row in rows:
                if row.status == 'INVALID':
                    continue
                if row.skill_id:
                    skill = await self.crud.get(row.skill_id, user, db)
                    if self.crud.status_value(skill.display_status) != 'DRAFT':
                        raise DeveloperError("该技能已进入调试或发布流程，请在开发者中心详情中编辑", 409)
                    form = await SkillForm.get(skill_version_id=skill.current_version_id).using_db(db)
                    row.payload = {**row.payload, 'edit_revision': skill.current_revision,
                                   'replace_content': bool(row.payload.get('replace_content')) and row.status != 'SUCCEEDED'}
                    row.selection = {**row.selection, 'name': form.name, 'class_id': form.skill_class_id,
                                     'application_paso': form.application_paso, 'expected_revision': skill.current_revision}
                else:
                    if batch.expires_at < now():
                        raise DeveloperError('临时文件已过期，请重新上传', 410)
                    files = [(row.payload['markdown_storage'], row.payload['markdown_hash'])]
                    files.extend((entry['storage'], entry['sha256']) for entry in row.payload['attachments'])
                    for storage, digest in files:
                        source = self.directory(batch_id) / storage
                        if not source.is_file() or await asyncio.to_thread(file_hash, source) != digest:
                            raise DeveloperError("暂存文件缺失或已改变，请重新选择文件上传")
                row.status, row.errors = 'READY', []
                await row.save(using_db=db, update_fields=['status', 'errors', 'selection', 'payload'])
        return await self.status(batch_id, user)

    async def update_existing(self, item, selection, user, db, artifacts):
        skill = await self.crud.get(item.skill_id, user, db)
        if self.crud.status_value(skill.display_status) != 'DRAFT':
            raise DeveloperError("该技能已进入调试或发布流程，请在开发者中心详情中编辑", 409)
        self.crud.check_revision(skill, selection.expected_revision)
        form = await SkillForm.get(skill_version_id=skill.current_version_id).using_db(db)
        bindings = await SkillResourceBinding.filter(skill_version_id=skill.current_version_id).using_db(db).order_by('sort_order', 'id')
        resources, knowledge = [], []
        categories = {row.id: row.name for row in await ResourceCategory.all().using_db(db)}
        for binding in bindings:
            if binding.file_id is not None:
                source = await Source.get(id=binding.file_id).using_db(db)
                resources.append({'fileId': source.id, 'category': categories.get(source.category_id),
                                  'relativePath': binding.relative_path, 'usage': binding.usage_text or ''})
            elif binding.source_type == 'knowledge_base':
                knowledge.append(binding.source_id)
        data = DeveloperSkillForm(name=selection.name, class_id=selection.class_id, application_paso=selection.application_paso,
            expected_revision=selection.expected_revision, description=form.description, instructions=form.instructions,
            technical_name=form.technical_name, compatibility=form.compatibility or '', resource_usage=form.resource_usage or '',
            uploaded_resources=resources, resource_ids=knowledge, skill_markdown=read_markdown(form.skill_markdown_path))
        return await self.crud.save_in_transaction(skill.id, user, data, db, artifacts=artifacts)

    async def batch(self, batch_id, user):
        batch = await SkillImportBatch.get_or_none(id=batch_id, owner_login=user_login_name(user))
        if not batch:
            staged = self.temp.read(batch_id, user_login_name(user))
            batch = SimpleNamespace(id=batch_id, owner_login=staged['owner_login'], upload_mode=staged['upload_mode'],
                expires_at=datetime.fromtimestamp(staged['expires_at'], tz=now().tzinfo), pending=True)
        return batch

    async def _rows(self, batch_id, user):
        batch = await self.batch(batch_id, user)
        if getattr(batch, 'pending', False):
            staged = self.temp.read(batch_id, user_login_name(user))
            return [SimpleNamespace(**{'selection': {}, 'skill_id': None, **item}) for item in staged['items']]
        return await SkillImportItem.filter(batch_id=batch.id).order_by('created_time', 'id')

    async def status(self, batch_id, user):
        batch = await self.batch(batch_id, user)
        rows = await self._rows(batch_id, user)
        revisions = {row.id: row.current_revision for row in await Skill.filter(id__in=[item.skill_id for item in rows if item.skill_id])}
        return {"import_id": batch.id, "expires_at": batch.expires_at, "expired": batch.expires_at < now(), "limits": import_limits(),
                "items": [{"item_id": row.id, "root_path": row.root_path, "default_name": row.default_name,
                           "description": row.payload.get("description", ""),
                           "source_path": row.payload.get("source_path", row.root_path), "source_size": row.payload.get("source_size", 0), "valid": row.status != "INVALID", "status": row.status,
                           "attachments": [{"path": f["relative_path"], "size": f["size"]} for f in row.payload.get("attachments", [])],
                           "errors": row.errors, "selection": row.selection, "skill_id": row.skill_id, "revision": revisions.get(row.skill_id)} for row in rows]}

    async def check_names(self, request, user):
        await self.batch(request.import_id, user)
        rows = {row.id: row for row in await self._rows(request.import_id, user)}
        if any(item.item_id not in rows for item in request.items) or len({item.item_id for item in request.items}) != len(request.items):
            raise DeveloperError('候选技能不属于当前批次或重复提交')
        existing = [(skill.id, normalized_skill_name(skill.name)) for skill in await Skill.filter(state=0)]
        keys = [normalized_skill_name(item.name) for item in request.items]
        errors = {}
        for item, key in zip(request.items, keys):
            messages = []
            if keys.count(key) > 1:
                messages.append('本次导入中有重复名称，请修改')
            if any(name == key and skill_id != rows[item.item_id].skill_id for skill_id, name in existing):
                messages.append('该技能名称已存在，请更换')
            if messages:
                errors[item.item_id] = messages
        return {'valid': not errors, 'errors': errors}

    async def confirm(self, request, user):
        async with self.temp.lock(request.import_id):
            await self._materialize(request.import_id, user)
            return await self._confirm(request, user)

    async def _confirm(self, request, user):
        await self.batch(request.import_id, user)
        # Preflight identities before any draft is created.
        ids = await SkillImportItem.filter(batch_id=request.import_id, id__in=[row.item_id for row in request.items]).values_list('id', flat=True)
        if len(ids) != len(request.items):
            raise DeveloperError("候选技能不属于当前批次")
        for selection in request.items:
            await self.import_one(request.import_id, selection, user)
        return await self.status(request.import_id, user)

    async def import_one(self, batch_id, selection, user):
        new_paths, definitions = [], []
        try:
            async with in_transaction() as db:
                # Batch lock also serializes same-batch retries, regardless of HTTP request order.
                batch = await SkillImportBatch.filter(id=batch_id, owner_login=user_login_name(user)).using_db(db).select_for_update().first()
                item = await SkillImportItem.filter(id=selection.item_id, batch_id=batch_id).using_db(db).select_for_update().first()
                if item.status in ("SUCCEEDED", "INVALID"):
                    return
                if batch.expires_at < now() and (not item.skill_id or item.payload.get('replace_content')):
                    raise DeveloperError("导入批次已过期，请重新上传")
                if not selection.name.strip() or not selection.application_paso.strip():
                    raise DeveloperError("请填写名称并选择所属应用")
                await self.crud.lock_name_catalog(db)
                if item.skill_id and not item.payload.get('replace_content'):
                    await self.update_existing(item, selection, user, db, definitions)
                    item.status, item.errors, item.selection = 'SUCCEEDED', [], selection.model_dump()
                    await item.save(using_db=db, update_fields=['status', 'errors', 'selection'])
                    return
                category = await ResourceCategory.filter(code="custom", is_enabled=True).using_db(db).first()
                if not category:
                    raise DeveloperError("缺少已启用的自定义资源分类，请执行导入迁移")
                directory = self.directory(batch.id)
                raw_path = directory / item.payload["markdown_storage"]
                if not raw_path.is_file() or await asyncio.to_thread(file_hash, raw_path) != item.payload["markdown_hash"]:
                    raise DeveloperError("暂存定义文件缺失或已改变，请重新上传")
                raw = raw_path.read_bytes().decode("utf-8-sig")
                resources = []
                source_dir = self.root / "sources"
                source_dir.mkdir(parents=True, exist_ok=True)
                for attachment in item.payload["attachments"]:
                    path = directory / attachment["storage"]
                    if not path.is_file() or await asyncio.to_thread(file_hash, path) != attachment["sha256"]:
                        raise DeveloperError(f"暂存附件缺失或已改变：{attachment['relative_path']}")
                    source = await Source.filter(create_user_login_name=user_login_name(user), category_id=category.id, sha256=attachment["sha256"]).using_db(db).first()
                    if source and source.state != 'ACTIVE':
                        raise DeveloperError("相同附件原记录已失效，请先处理原文件记录")
                    if source is None:
                        target = source_dir / uuid.uuid4().hex
                        new_paths.append(target)
                        await asyncio.to_thread(shutil.copyfile, path, target)
                        source = await Source.create(using_db=db, original_name=PurePosixPath(attachment["relative_path"]).name,
                            extension=PurePosixPath(attachment["relative_path"]).suffix.lower(), byte_size=attachment["size"],
                            sha256=attachment["sha256"], storage_key=str(target), category_id=category.id,
                            create_user_login_name=user_login_name(user))
                    resources.append({"fileId": source.id, "category": category.name, "relativePath": attachment["relative_path"]})
                form = DeveloperSkillForm(name=selection.name, class_id=selection.class_id, application_paso=selection.application_paso,
                    description=item.payload["description"], instructions=item.payload["instructions"],
                    technical_name=item.payload["technical_name"], compatibility=item.payload["compatibility"],
                    resource_usage=DEFAULT_USAGE, uploaded_resources=resources, skill_markdown=raw)
                if item.skill_id:
                    existing = await self.crud.get(item.skill_id, user, db)
                    if self.crud.status_value(existing.display_status) != 'DRAFT':
                        raise DeveloperError("该技能已进入调试或发布流程，请在开发者中心详情中编辑", 409)
                    form.expected_revision = selection.expected_revision
                    skill = await self.crud.save_in_transaction(item.skill_id, user, form, db, artifacts=definitions)
                else:
                    skill = await self.crud.create_in_transaction(user, form, db, artifacts=definitions, definition_origin="import")
                item.status, item.skill_id, item.errors, item.selection = "SUCCEEDED", skill.id, [], selection.model_dump()
                await item.save(using_db=db, update_fields=['status', 'skill_id', 'errors', 'selection'])
        except BaseException as exc:
            for path in new_paths:
                path.unlink(missing_ok=True)
            for relative in definitions:
                discard_markdown(relative)
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, FileNotFoundError):
                message = '临时文件已被清理，请重新上传'
            elif isinstance(exc, (DeveloperError, ValidationError, IntegrityError)):
                message = "名称或文件发生冲突，请刷新信息后重试" if isinstance(exc, IntegrityError) else str(exc)
            else:
                LOGGER.exception("技能导入失败，候选编号 {}", selection.item_id)
                message = "导入失败，请根据候选编号检查后端日志"
            await SkillImportItem.filter(id=selection.item_id, batch_id=batch_id).exclude(status__in=['SUCCEEDED', 'INVALID']).update(
                status="FAILED", errors=[message], selection=selection.model_dump())
