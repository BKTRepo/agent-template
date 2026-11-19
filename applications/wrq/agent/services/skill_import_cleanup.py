"""Periodic cleanup for Skill import temporary files; never removes permanent assets."""
import asyncio
from configure import LOGGER, PROJECT_CONFIG
from .skill_import_service import SkillImportService


async def cleanup_loop():
    service = SkillImportService()
    while True:
        try:
            await service.cleanup_expired()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception('Skill导入临时文件清理失败')
        await asyncio.sleep(PROJECT_CONFIG.SKILL_IMPORT_CLEANUP_SECONDS)
