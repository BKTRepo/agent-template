"""本地演示：真实生成目录包，不连接数据库、模型或知识库，不执行资源脚本。"""
import argparse
import json
from pathlib import Path

from applications.agent.schemas.skill_package_schema import SkillEntryUploadSource, SkillPackageSource
from applications.agent.services.skill_package_builder import (
    ResolvedSkillResource, SkillPackageBuilder, SkillPackageError,
)
from applications.agent.services.skill_upload_adapter import source_from_upload_entries


FIXTURES = Path(__file__).resolve().parent / "skill-package"
SCENARIOS = {
    "basic": [],
    "reference": ["business-rules.md"],
    "script": ["business-rules.md", "check_input.py"],
    "entries": ["business-rules.md", "check_input.py"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="basic")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "output" / "skill-builds")
    args = parser.parse_args()
    raw_source = (FIXTURES / f"source-{args.scenario}.json").read_text(encoding="utf-8")
    resources = [ResolvedSkillResource(index, FIXTURES / filename, filename)
                 for index, filename in enumerate(SCENARIOS[args.scenario])]
    builder = SkillPackageBuilder(args.output_dir)
    # 演示专用身份；真实 API 必须从鉴权上下文取得用户身份。
    user_id, skill_id = 1, "skill-demo"
    try:
        if args.scenario == "entries":
            source = source_from_upload_entries(SkillEntryUploadSource.model_validate_json(raw_source),
                                                 reference_count=1, script_count=1)
        else:
            source = SkillPackageSource.model_validate_json(raw_source)
        built = builder.build(source, resources, user_id=user_id, skill_id=skill_id)
        verified = builder.read(user_id=user_id, skill_id=skill_id, build_id=built["build_id"], verify=True)
    except SkillPackageError as exc:
        print(exc.report.model_dump_json(indent=2))
        return 1
    print(json.dumps({
        "scenario": args.scenario,
        "identity": "演示用户 user_id=1，不代表真实登录",
        "build_id": verified["build_id"],
        "skill_directory": verified["skill_directory"],
        "workspace_dir": verified["workspace_dir"],
        "package_zip": str(Path(verified["workspace_dir"]) / "package.zip"),
        "files": [item["path"] for item in verified["files"]],
        "verified": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
