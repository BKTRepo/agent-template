"""知识库名称键审计/回填；默认不修改数据，不执行 DDL 或自动迁移。"""
import argparse
import asyncio
import json
from pathlib import Path
from tortoise import Tortoise
from applications.wrq.knowledge_base.services.name_migration import migrate_knowledge_names


async def run(args):
    if args.sqlite:
        path = Path(args.sqlite).resolve()
        if not path.is_file():
            raise ValueError("指定 SQLite 数据库不存在")
        await Tortoise.init(db_url=f"sqlite://{path.as_posix()}", modules={"models": []})
    else:
        from configure import PROJECT_CONFIG
        await Tortoise.init(config={"connections": PROJECT_CONFIG.DATABASE_CONNECTIONS, "apps": {}})
    try:
        result = await migrate_knowledge_names(apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识库名称预审与回填（应用前备份并停止写入）")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--sqlite")
    target.add_argument("--configured-db", action="store_true")
    parser.add_argument("--apply", action="store_true", help="已升级表结构且预审通过后回填名称键")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
