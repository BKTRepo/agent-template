"""完整项目启动不得隐式迁移、初始化账号；失败时释放数据库连接。"""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from applications.wrq import full_backend


class FullBackendStartupTests(IsolatedAsyncioTestCase):
    async def test_absent_identity_table_does_not_trigger_initialization(self):
        db = SimpleNamespace(execute_query=AsyncMock(side_effect=[(1, []), (1, [{"present": 0}])]))
        app = SimpleNamespace(routes=[])
        with patch.object(full_backend.Tortoise, "init", new_callable=AsyncMock) as init, \
                patch.object(full_backend.Tortoise, "close_connections", new_callable=AsyncMock) as close, \
                patch.object(full_backend.connections, "get", return_value=db), \
                patch.object(full_backend.PROJECT_CONFIG, "DATABASE_AUTO_MIGRATION", False):
            async with full_backend.lifespan(app):
                pass
            init.assert_awaited_once()
            close.assert_awaited_once()
            queries = [call.args[0].upper() for call in db.execute_query.await_args_list]
            self.assertEqual(len(queries), 2)
            self.assertTrue(all(query.startswith("SELECT ") for query in queries))

    async def test_migration_enabled_refuses_startup_before_database_access(self):
        with patch.object(full_backend.Tortoise, "init", new_callable=AsyncMock) as init, \
                patch.object(full_backend.PROJECT_CONFIG, "DATABASE_AUTO_MIGRATION", True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_AUTO_MIGRATION"):
                async with full_backend.lifespan(SimpleNamespace(routes=[])):
                    self.fail("启动迁移开启时不得进入运行状态")
            init.assert_not_awaited()

    async def test_database_failure_closes_connections(self):
        with patch.object(full_backend.Tortoise, "init", new_callable=AsyncMock,
                          side_effect=RuntimeError("connection failed")), \
                patch.object(full_backend.Tortoise, "close_connections", new_callable=AsyncMock) as close, \
                patch.object(full_backend.PROJECT_CONFIG, "DATABASE_AUTO_MIGRATION", False):
            with self.assertRaisesRegex(RuntimeError, "connection failed"):
                async with full_backend.lifespan(SimpleNamespace(routes=[])):
                    self.fail("连接失败时不得进入运行状态")
            close.assert_awaited_once()
