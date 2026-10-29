"""开发者中心前端全流程联调数据。

默认只读规划；--apply 补齐当前代码依赖的 WRQ 增量列并写入六个场景；
--cleanup 只删除本脚本以 E2E-20261028 标记创建的数据和文件。
脚本不重置表，不覆盖已有技能，且每次执行前备份相关行和 DDL。
"""
import argparse
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys

from applications.wrq.migrations.review_20261024 import connect
from configure import PROJECT_CONFIG

MARKER = "E2E-20261028"
OWNER = "admin"
ROOT = Path(__file__).resolve().parents[3]
BACKUP_ROOT = ROOT.parent / ".tmp" / "wrq-e2e-seed-backups"
SOURCE_ROOT = Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve() / "sources" / MARKER.lower()

SKILLS = [
    ("e2e-20261028-draft", f"{MARKER}-01-资源丰富草稿", "DRAFT", 1, None, 1),
    ("e2e-20261028-queued", f"{MARKER}-02-调试中", "DEBUGGING", 1, None, 2),
    ("e2e-20261028-passed", f"{MARKER}-03-调试成功", "DEBUG_SUCCESS", 1, None, 3),
    ("e2e-20261028-failed", f"{MARKER}-04-调试失败", "DEBUG_FAILED", 1, None, 4),
    ("e2e-20261028-online", f"{MARKER}-05-已上线", "ONLINE", 2, "1.0.0", 5),
    ("e2e-20261028-offline", f"{MARKER}-06-已下线", "OFFLINE", 3, "1.0.1", 6),
]

RUNS = {
    "e2e-20261028-queued": ("e2e1028queued", "QUEUED", None),
    "e2e-20261028-passed": ("e2e1028passed", "PASSED", None),
    "e2e-20261028-failed": ("e2e1028failed", "FAILED", "模拟错误：输入文档缺少必填字段"),
    "e2e-20261028-online": ("e2e1028online", "PASSED", None),
    "e2e-20261028-offline": ("e2e1028offline", "PASSED", None),
}

FILES = [
    ("reference.txt", "text/plain", 1, "登录、退出、密码重置业务规则。\n"),
    ("case-template.md", "text/markdown", 2, "# 用例模板\n- 前置条件\n- 步骤\n- 预期结果\n"),
    ("test-data.json", "application/json", 3, '{"valid_user":"demo","invalid_user":"locked"}\n'),
    ("helper.py", "text/x-python", 4, "def normalize(value):\n    return value.strip().lower()\n"),
]


async def table_columns(cur, table):
    await cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
        [table],
    )
    return {row["COLUMN_NAME"] for row in await cur.fetchall()}


async def table_indexes(cur, table):
    await cur.execute(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
        [table],
    )
    return {row["INDEX_NAME"] for row in await cur.fetchall()}


async def backup(cur, folder):
    tables = [
        "keenrobot_skills", "keenrobot_skill_versions", "keenrobot_skill_forms",
        "keenrobot_skill_uploaded_files", "keenrobot_skill_resource_bindings",
        "keenrobot_skill_debug_runs", "keenrobot_skill_publications",
        "keenrobot_online_debug_runs",
    ]
    result = {}
    for table in tables:
        await cur.execute(f"SHOW CREATE TABLE `{table}`")
        ddl = (await cur.fetchone())["Create Table"]
        await cur.execute(f"SELECT * FROM `{table}`")
        result[table] = {"ddl": ddl, "rows": list(await cur.fetchall())}
    (folder / "before.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf8"
    )


async def ensure_schema(cur, journal):
    changes = []

    async def add_column(table, column, definition):
        columns = await table_columns(cur, table)
        if column not in columns:
            sql = f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
            await cur.execute(sql)
            changes.append(sql)

    await add_column("keenrobot_skills", "published_version_id", "INT NULL COMMENT '最近成功上线的技能版本主键'")
    await cur.execute(
        "ALTER TABLE keenrobot_skill_versions MODIFY version VARCHAR(32) NULL COMMENT '显示版本号；首次上线前为空'"
    )
    changes.append("keenrobot_skill_versions.version -> nullable")

    for table in ("keenrobot_skill_uploaded_files", "keenrobot_skill_resource_bindings"):
        await add_column(table, "update_user_login_name", "VARCHAR(10) NULL COMMENT '最近修改人工号'")
        await add_column(table, "updated_time", "DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '最后修改时间'")

    await add_column("keenrobot_skill_publications", "version", "VARCHAR(32) NULL COMMENT '操作时的对外版本号'")
    await add_column("keenrobot_skill_publications", "reason_code", "VARCHAR(32) NULL COMMENT '下线原因枚举'")
    await add_column("keenrobot_skill_publications", "reason_text", "VARCHAR(500) NULL COMMENT '其他原因说明'")
    await add_column("keenrobot_skill_publications", "update_user_login_name", "VARCHAR(10) NULL COMMENT '最近修改人工号'")
    await add_column("keenrobot_skill_publications", "updated_time", "DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '最后修改时间'")

    indexes = await table_indexes(cur, "keenrobot_skill_uploaded_files")
    if "uq_file_category_hash" not in indexes:
        sql = "ALTER TABLE keenrobot_skill_uploaded_files ADD UNIQUE KEY uq_file_category_hash(category_id,sha256)"
        await cur.execute(sql); changes.append(sql)
    indexes = await table_indexes(cur, "keenrobot_skill_resource_bindings")
    if "uq_skill_version_file" not in indexes:
        sql = "ALTER TABLE keenrobot_skill_resource_bindings ADD UNIQUE KEY uq_skill_version_file(skill_version_id,file_id)"
        await cur.execute(sql); changes.append(sql)
    journal.extend({"schema": value} for value in changes)


async def cleanup(cur, journal):
    ids = [row[0] for row in SKILLS]
    run_ids = [row[0] for row in RUNS.values()]
    placeholders = ",".join(["%s"] * len(ids))
    run_placeholders = ",".join(["%s"] * len(run_ids))
    statements = [
        (f"DELETE FROM keenrobot_online_debug_runs WHERE run_id IN ({run_placeholders})", run_ids),
        (f"DELETE FROM keenrobot_skill_publications WHERE skill_id IN ({placeholders})", ids),
        (f"DELETE FROM keenrobot_skill_debug_runs WHERE skill_id IN ({placeholders})", ids),
        (f"DELETE FROM keenrobot_skill_resource_bindings WHERE skill_id IN ({placeholders})", ids),
        (f"DELETE FROM keenrobot_skill_forms WHERE skill_version_id IN (SELECT id FROM keenrobot_skill_versions WHERE skill_id IN ({placeholders}))", ids),
        (f"DELETE FROM keenrobot_skill_versions WHERE skill_id IN ({placeholders})", ids),
        (f"DELETE FROM keenrobot_skills WHERE id IN ({placeholders})", ids),
        ("DELETE FROM keenrobot_skill_uploaded_files WHERE storage_key LIKE %s", [f"%{MARKER.lower()}%"]),
    ]
    for sql, args in statements:
        await cur.execute(sql, args)
        journal.append({"cleanup": sql, "affected": cur.rowcount})
    if SOURCE_ROOT.exists():
        shutil.rmtree(SOURCE_ROOT)


async def seed(cur, journal):
    now = datetime.now()
    version_ids = {}
    run_by_skill = {sid: values[0] for sid, values in RUNS.items()}
    for sid, name, status, revision, public_version, class_id in SKILLS:
        await cur.execute(
            "INSERT INTO keenrobot_skills (id,name,create_user_login_name,update_user_login_name,application_paso,skill_classes_id,display_status,current_revision,last_debug_run_id,published_at,offline_at,state,created_time,updated_time) "
            "VALUES (%s,%s,%s,%s,'*',%s,%s,%s,%s,%s,%s,0,%s,%s)",
            [sid, name, OWNER, OWNER, class_id, status, revision, run_by_skill.get(sid),
             now if status in ("ONLINE", "OFFLINE") else None,
             now if status == "OFFLINE" else None, now, now],
        )
        build_id = hashlib.md5((sid + "-build").encode()).hexdigest() if sid in RUNS else None
        manifest_hash = hashlib.sha256((sid + "-manifest").encode()).hexdigest() if build_id else None
        await cur.execute(
            "INSERT INTO keenrobot_skill_versions (skill_id,version,revision,build_id,package_storage_key,manifest_hash,create_user_login_name,update_user_login_name,created_time,updated_time) "
            "VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s)",
            [sid, public_version, revision, build_id, manifest_hash, OWNER, OWNER, now, now],
        )
        vid = cur.lastrowid
        version_ids[sid] = (vid, build_id, manifest_hash)
        await cur.execute(
            "INSERT INTO keenrobot_skill_forms (skill_version_id,name,skill_class_id,application_paso,description,instructions,resource_usage,compatibility,technical_name,skill_markdown_path) "
            "VALUES (%s,%s,%s,'*',%s,%s,%s,%s,%s,'')",
            [vid, name, class_id,
             f"{MARKER} 联调数据：{name}",
             "你是软件测试助手。根据输入和挂载资源生成结构化测试用例，包含前置条件、步骤和预期结果。",
             "按参考资料理解业务，按模板输出，静态资源用于构造数据，脚本仅作辅助。" if sid.endswith("draft") else None,
             "Python 3.12；输出 UTF-8；单次最多 100 条用例。",
             f"e2e-{sid.removeprefix('e2e-20261028-')}"]
        )
        await cur.execute(
            "UPDATE keenrobot_skills SET current_version_id=%s,published_version_id=%s WHERE id=%s",
            [vid, vid if status in ("ONLINE", "OFFLINE") else None, sid],
        )

    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    draft_id = "e2e-20261028-draft"
    draft_version = version_ids[draft_id][0]
    for order, (name, mime, category, content) in enumerate(FILES):
        path = SOURCE_ROOT / name
        raw = content.encode("utf8")
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        await cur.execute(
            "INSERT INTO keenrobot_skill_uploaded_files (original_name,extension,mime_type,byte_size,sha256,storage_key,create_user_login_name,update_user_login_name,state,category_id,created_time,updated_time) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE',%s,%s,%s)",
            [name, Path(name).suffix.lower(), mime, len(raw), digest, str(path), OWNER, OWNER, category, now, now],
        )
        file_id = cur.lastrowid
        await cur.execute(
            "INSERT INTO keenrobot_skill_resource_bindings (skill_id,skill_version_id,source_type,source_id,file_id,display_name,usage_text,content_hash,sort_order,update_user_login_name,created_time,updated_time) "
            "VALUES (%s,%s,'upload',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [draft_id, draft_version, file_id, file_id, name, f"联调用途：{name}", digest, order, OWNER, now, now],
        )

    for sid, (run_id, status, error) in RUNS.items():
        vid, build_id, manifest_hash = version_ids[sid]
        await cur.execute(
            "INSERT INTO keenrobot_skill_debug_runs (run_id,skill_id,skill_version_id,build_id,conversation_input,request_document_count,resource_manifest_hash,error_code,create_user_login_name,created_time,updated_time) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [run_id, sid, vid, build_id, "请生成登录、异常锁定和密码重置场景测试用例", 1,
             manifest_hash, "E2E_EXPECTED_FAILURE" if status == "FAILED" else None, OWNER, now, now],
        )
        await cur.execute(
            "INSERT INTO keenrobot_online_debug_runs (skill_id,run_id,status,result_file_path,error_message,started_at,finished_at,expires_at,debugger) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [sid, run_id, status,
             f"/e2e/{run_id}" if status == "PASSED" else None,
             error, now if status != "QUEUED" else None,
             now if status in ("PASSED", "FAILED") else None,
             now + timedelta(days=30) if status == "PASSED" else None, OWNER],
        )

    for sid in ("e2e-20261028-online", "e2e-20261028-offline"):
        vid = version_ids[sid][0]
        version = "1.0.0" if sid.endswith("online") else "1.0.1"
        await cur.execute(
            "INSERT INTO keenrobot_skill_publications (skill_id,skill_version_id,action,version,operator_login_name,reason_code,reason_text,reason,update_user_login_name,created_time,updated_time) "
            "VALUES (%s,%s,'PUBLISH',%s,%s,NULL,NULL,NULL,%s,%s,%s)",
            [sid, vid, version, OWNER, OWNER, now, now],
        )
    sid = "e2e-20261028-offline"; vid = version_ids[sid][0]
    await cur.execute(
        "INSERT INTO keenrobot_skill_publications (skill_id,skill_version_id,action,version,operator_login_name,reason_code,reason_text,reason,update_user_login_name,created_time,updated_time) "
        "VALUES (%s,%s,'OFFLINE','1.0.1',%s,'OTHER',%s,%s,%s,%s,%s)",
        [sid, vid, OWNER, "联调测试主动下线", "联调测试主动下线", OWNER, now, now],
    )
    journal.append({"seeded_skills": [row[0] for row in SKILLS], "owner": OWNER})


async def verify(cur):
    await cur.execute(
        "SELECT s.id,s.name,s.display_status,s.current_revision,s.current_version_id,s.published_version_id,v.version,v.build_id "
        "FROM keenrobot_skills s JOIN keenrobot_skill_versions v ON v.id=s.current_version_id "
        "WHERE s.id LIKE 'e2e-20261028-%' ORDER BY s.id"
    )
    skills = list(await cur.fetchall())
    await cur.execute("SELECT COUNT(*) n FROM keenrobot_skill_uploaded_files WHERE storage_key LIKE %s", [f"%{MARKER.lower()}%"])
    files = (await cur.fetchone())["n"]
    await cur.execute("SELECT COUNT(*) n FROM keenrobot_skill_debug_runs WHERE skill_id LIKE 'e2e-20261028-%'")
    debug_runs = (await cur.fetchone())["n"]
    await cur.execute("SELECT COUNT(*) n FROM keenrobot_skill_publications WHERE skill_id LIKE 'e2e-20261028-%'")
    publications = (await cur.fetchone())["n"]
    if len(skills) != 6 or files != 4 or debug_runs != 5 or publications != 3:
        raise RuntimeError("联调数据数量校验失败")
    return {"skills": skills, "files": files, "debug_runs": debug_runs, "publications": publications}


async def run(apply=False, cleanup_only=False):
    folder = BACKUP_ROOT / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    folder.mkdir(parents=True, exist_ok=False)
    conn = await connect()
    journal = []
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT GET_LOCK('wrq_e2e_seed_20261028',0) acquired")
            if (await cur.fetchone())["acquired"] != 1:
                raise RuntimeError("另一个联调数据任务正在执行")
            await backup(cur, folder)
            if not apply and not cleanup_only:
                print(json.dumps({"mode": "plan", "owner": OWNER, "skills": [r[1] for r in SKILLS], "backup": str(folder)}, ensure_ascii=False, indent=2))
                return
            if cleanup_only:
                await cleanup(cur, journal)
                print(json.dumps({"mode": "cleanup", "backup": str(folder)}, ensure_ascii=False, indent=2))
                return
            await ensure_schema(cur, journal)
            await cleanup(cur, journal)
            await seed(cur, journal)
            report = {"mode": "applied", "backup": str(folder), "verification": await verify(cur), "journal": journal}
            (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf8")
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.apply, args.cleanup))
