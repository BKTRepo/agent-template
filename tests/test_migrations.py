"""在临时数据库中验证 Aerich 命令及显式启动迁移。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class MigrationTests(unittest.TestCase):
    def test_fresh_database_and_existing_migrations(self):
        root = Path(__file__).resolve().parents[1]
        executable = Path(sys.executable).with_name("aerich.exe" if os.name == "nt" else "aerich")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "template.db"
            migrations = temporary / "migrations"
            config = temporary / "aerich.toml"
            config.write_text(
                '[tool.aerich]\ntortoise_orm = "configure.project_config.TORTOISE_ORM"\n'
                f'location = {json.dumps(migrations.as_posix())}\n'
                f'src_folder = {json.dumps(root.as_posix(), ensure_ascii=False)}\n', encoding="utf-8",
            )
            env = {**os.environ, "AUTH_SECRET_KEY": "migration-test-key-" + "0" * 64,
                   "DATABASE_URL": "sqlite://" + database.as_posix(),
                   "DATABASE_AUTO_MIGRATION": "False", "MIGRATION_DIR": str(migrations),
                   "SERVER_DEBUG": "False", "PYTHONUTF8": "1"}
            def run(command, environment=env):
                result = subprocess.run(command, cwd=root, env=environment,
                                        capture_output=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            run([str(executable), "-c", str(config), "init-db"])
            files_before = sorted(p.name for p in migrations.rglob("*.py"))
            self.assertEqual(len(files_before), 1)
            with closing(sqlite3.connect(database)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(tables - {"sqlite_sequence"}, {"keenrobot_user", "keenrobot_audit", "aerich"})
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM keenrobot_user").fetchone()[0], 0)
            run([str(executable), "-c", str(config), "upgrade"])
            result = run([str(executable), "-c", str(config), "migrate", "--name", "verify_clean"])
            self.assertIn("No changes detected", result.stdout)
            script = '''
from fastapi.testclient import TestClient
from backend_main import app
with TestClient(app) as client:
    assert client.get("/health").json()["status"] == "ok"
'''
            run([sys.executable, "-c", script], {**env, "DATABASE_AUTO_MIGRATION": "True"})
            self.assertEqual(sorted(p.name for p in migrations.rglob("*.py")), files_before)


if __name__ == "__main__":
    unittest.main()
