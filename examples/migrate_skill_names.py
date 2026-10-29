"""名称迁移命令默认仅审计；不启动应用、不执行自动 Aerich 迁移。"""
import argparse
import asyncio
import json
from pathlib import Path

from tortoise import Tortoise
from applications.wrq.agent.services.skill_name_migration import migrate_skill_names


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
        result = await migrate_skill_names(Tortoise.get_connection("default"), apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="技能名称审计与迁移（应用前停止技能写入并备份数据库）")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--sqlite", help="已有本地 SQLite 文件路径")
    target.add_argument("--configured-db", action="store_true", help="明确选择项目配置中的数据库")
    parser.add_argument("--apply", action="store_true", help="审计无冲突后添加字段、回填并建立约束")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
