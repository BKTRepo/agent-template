from pathlib import Path

from applications.wrq.agent.schemas.skill_package_schema import SkillPackageSource
from applications.wrq.agent.services.skill_package_builder import SkillPackageBuilder
from configure import PROJECT_CONFIG
from services.claude_agent_service import build_base_options


def test_runtime_uses_verified_build_workspace(tmp_path):
    builder = SkillPackageBuilder(tmp_path / "builds")
    built = builder.build(SkillPackageSource(name="case-generator", display_name="测试用例生成", description="生成用例。",
                         instructions="读取需求并生成用例。", version="0.1.0"),
                         [], user_id=1, skill_id="s")
    verified = builder.read(user_id=1, skill_id="s", build_id=built["build_id"], verify=True)
    options = build_base_options(skills=[verified["name"]], output_dir=str(tmp_path / "output"),
                                 workspace_dir=verified["workspace_dir"])
    assert str(options.cwd) == verified["workspace_dir"]
    assert "project" in options.setting_sources
    assert options.skills == [verified["name"]]
    assert (Path(options.cwd) / ".claude/skills/case-generator/SKILL.md").is_file()


def test_existing_agent_calls_keep_default_workspace():
    options = build_base_options(skills=["case-recommender"], output_dir="output")
    assert options.cwd == PROJECT_CONFIG.WORKSPACE_DIR
