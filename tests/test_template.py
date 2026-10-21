"""模板启动、空数据库和保留基础接口的集成验证。"""
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["AUTH_SECRET_KEY"] = "template-test-key-" + "0" * 64
os.environ["DATABASE_URL"] = "sqlite://:memory:"
os.environ["DATABASE_AUTO_MIGRATION"] = "False"
os.environ["SERVER_DEBUG"] = "False"

from fastapi.testclient import TestClient
from tortoise import Tortoise, connections

from backend_main import app
from configure import LOGGER, PROJECT_CONFIG
from configure.project_config import ProjectConfig
from enums import Code
from services.password import get_password_hash, verify_password

LOGGER.remove()


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def prepare_database(self):
        self.client.portal.call(Tortoise.generate_schemas)

    def create_user_and_login(self):
        self.prepare_database()
        response = self.client.post("/user/create", json={
            "username": "tester",
            "password": "template-test-password",
            "alias": "Tester",
            "email": "tester@example.com",
        })
        self.assertEqual(response.json()["status"], "success", response.text)
        user_id = response.json()["data"]["id"]
        self.assertNotIn("password", response.json()["data"])
        response = self.client.post("/base/auth/access_token", json={
            "username": "tester", "password": "template-test-password",
        })
        self.assertEqual(response.json()["status"], "success", response.text)
        return user_id, {"token": response.json()["data"]["access_token"]}

    def test_startup_does_not_create_tables_or_seed_data(self):
        async def tables():
            return await connections.get("default").execute_query_dict(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        self.assertEqual(self.client.portal.call(tables), [])
        for path in ("/", "/health", "/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_only_framework_models_and_routes_remain(self):
        self.assertEqual(set(PROJECT_CONFIG.APPLICATIONS_INSTALLED), {"base", "user"})
        self.assertEqual(set(PROJECT_CONFIG.APPLICATIONS_MODELS), {
            "applications.base.models.audit_model", "applications.user.models.user_model", "aerich.models",
        })
        paths = set(app.openapi()["paths"])
        self.assertTrue(all(p in {"/", "/health"} or p.startswith(("/base/", "/user/")) for p in paths))
        self.prepare_database()
        async def counts():
            from applications.user.models.user_model import User
            from applications.base.models.audit_model import Audit
            return await User.all().count(), await Audit.all().count()
        self.assertEqual(self.client.portal.call(counts), (0, 0))

    def test_docs_assets_and_request_trace(self):
        response = self.client.get("/docs")
        self.assertIn('/static/swagger-ui/swagger-ui-bundle.js', response.text)
        for path in ("/static/swagger-ui/swagger-ui-bundle.js", "/static/swagger-ui/swagger-ui.css", "/static/redoc/bundles/redoc.standalone.js"):
            self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.get("/health", headers={"X-Trace-ID": "test-trace"})
        self.assertEqual(response.headers["X-Trace-ID"], "test-trace")
        self.assertEqual(len(response.headers["X-Span-ID"]), 16)

    def test_authentication_user_update_and_logout(self):
        user_id, headers = self.create_user_and_login()
        self.assertEqual(self.client.get("/user/list").json()["code"], Code.CODE401.value)
        self.assertEqual(self.client.post("/base/auth/userinfo", headers=headers).json()["data"]["id"], user_id)
        result = self.client.post("/user/update", headers=headers, json={"user_id": user_id, "alias": "Updated"})
        self.assertEqual(result.json()["status"], "success", result.text)
        self.assertEqual(result.json()["data"]["alias"], "Updated")
        self.assertEqual(self.client.get("/user/list", headers=headers).json()["total"], 1)
        routes = self.client.post("/base/routes/routers", headers=headers)
        self.assertEqual(routes.json()["status"], "success", routes.text)
        self.assertEqual(self.client.post("/user/logout", headers=headers).json()["status"], "success")
        self.assertEqual(self.client.post("/base/auth/userinfo", headers=headers).json()["code"], Code.CODE401.value)

    def test_admin_script_creates_hashed_account_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite://" + (Path(directory) / "admin.db").as_posix()
            script = '''
import asyncio
from tortoise import Tortoise
from configure.project_config import TORTOISE_ORM
from applications.user.models.user_model import User
from services.password import verify_password
from services.scripts.init_admin import init_admin
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()
    await Tortoise.close_connections()
    assert await init_admin("admin", "first-password", "admin@example.com")
    assert not await init_admin("admin", "second-password", "other@example.com")
    await Tortoise.init(config=TORTOISE_ORM)
    user = await User.get(username="admin")
    assert verify_password("first-password", user.password)
    assert user.email == "admin@example.com" and user.is_superuser
    await Tortoise.close_connections()
asyncio.run(check())
'''
            result = subprocess.run([sys.executable, "-c", script],
                                    env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_password_hash_compatibility_and_invalid_values(self):
        hashed = get_password_hash("example-password")
        self.assertTrue(hashed.startswith("$argon2id$"))
        self.assertTrue(verify_password("example-password", hashed))
        self.assertFalse(verify_password("wrong", hashed))
        self.assertFalse(verify_password("example-password", "invalid-hash"))

    def test_mysql_config_does_not_require_external_services(self):
        config = ProjectConfig(_env_file=None, DATABASE_URL="", DATABASE_USERNAME="template_user",
                               DATABASE_PASSWORD="p@ss", DATABASE_HOST="localhost", DATABASE_PORT=3306)
        self.assertEqual(config.DATABASE_CONNECTIONS["default"]["engine"], "tortoise.backends.mysql")
        self.assertEqual(config.DATABASE_CONNECTIONS["default"]["credentials"]["port"], 3306)
        self.assertIn("p%40ss", config.DATABASE_URL)

    def test_all_remaining_modules_import_without_business_dependencies(self):
        for module in ("common", "configure", "enums", "services", "services.file_transfer",
                       "core.decorators", "core.exceptions", "core.responses",
                       "applications.base.models", "applications.user.models"):
            with self.subTest(module=module):
                importlib.import_module(module)


if __name__ == "__main__":
    unittest.main()
