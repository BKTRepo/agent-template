"""独立长期文件；不维护文件版本，不保存沙箱临时输入文档。"""
from pathlib import Path
import hashlib
import mimetypes
import uuid
import anyio
from tortoise.transactions import in_transaction
from tortoise.exceptions import IntegrityError
from applications.wrq.agent.models.agent_model import Source, ResourceCategory
from applications.wrq.auth import user_login_name
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_resource_rules import resource_role
from configure import PROJECT_CONFIG

MAX_BYTES = 50 * 1024 * 1024

class SourceService:
    def __init__(self, root=None):
        self.root = Path(root or (Path(PROJECT_CONFIG.SKILL_BUILD_DIR) / 'sources')).resolve()

    async def upload(self, files, categories, user):
        login = user_login_name(user)
        if not isinstance(categories, list) or not all(isinstance(v, str) for v in categories):
            raise DeveloperError('资源用途分类必须是按文件顺序排列的列表')
        if not files or len(files) != len(categories) or len(files) > 100:
            raise DeveloperError('每个上传文件都需要选择用途分类')
        paths, staged, total = [], [], 0
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            for upload, category in zip(files, categories):
                name = upload.filename or ''
                try:
                    resource_role(name)
                except ValueError as exc:
                    raise DeveloperError(str(exc)) from exc
                path = self.root / (uuid.uuid4().hex + Path(name).suffix.lower())
                paths.append(path)
                size, digest = 0, hashlib.sha256()
                async with await anyio.open_file(path, 'xb') as stream:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_BYTES or total > MAX_BYTES:
                            raise DeveloperError('单文件及资源总大小不能超过50MB')
                        await stream.write(chunk)
                        digest.update(chunk)
                if not size:
                    raise DeveloperError('不能上传空文件')
                staged.append((name, path, size, category, digest.hexdigest()))
            results = []
            async with in_transaction() as db:
                selected = await ResourceCategory.filter(is_enabled=True).using_db(db).select_for_update()
                mapping = {key: r for r in selected for key in (r.name, r.code)}
                for name, path, size, category, digest in staged:
                    kind = mapping.get(category)
                    if kind is None:
                        raise DeveloperError('请选择有效的资源用途分类')
                    source = await Source.filter(category_id=kind.id, sha256=digest, state='ACTIVE').using_db(db).first()
                    if source:
                        path.unlink(missing_ok=True)
                    else:
                        try:
                            source = await Source.create(using_db=db, original_name=name,
                                extension=Path(name).suffix.lower(), mime_type=mimetypes.guess_type(name)[0],
                                storage_key=str(path), byte_size=size, sha256=digest, category_id=kind.id,
                                create_user_login_name=login, state='ACTIVE')
                        except IntegrityError:
                            source = await Source.filter(category_id=kind.id, sha256=digest, state='ACTIVE').using_db(db).first()
                            if not source:
                                raise
                    results.append({'id': f'file:{source.id}', 'fileId': source.id,
                        'name': source.original_name, 'size': source.byte_size, 'lastModified': 0, 'category': kind.name,
                        'savedCategory': kind.name, 'downloadUrl': f'/skills/developer/resources/{source.id}/download'})
            return results
        except BaseException:
            for path in paths:
                path.unlink(missing_ok=True)
            raise

    async def download(self, file_id, user):
        file = await Source.get_or_none(id=file_id, create_user_login_name=user_login_name(user))
        if not file or file.state == 'DELETED':
            raise DeveloperError('文件不存在或无访问权限', 404)
        path = Path(file.storage_key).resolve()
        if not path.is_relative_to(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()) or not path.is_file():
            raise DeveloperError('原文件缺失，请重新上传', 404)
        if file.sha256 and await anyio.to_thread.run_sync(lambda: hashlib.sha256(path.read_bytes()).hexdigest()) != file.sha256:
            raise DeveloperError('原文件校验失败，请联系维护人员', 409)
        return path, file.original_name
