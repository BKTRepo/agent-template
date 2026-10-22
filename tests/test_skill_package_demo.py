"""用独立进程证明演示不依赖 pytest 注入的后端配置。"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.mark.parametrize("scenario,expected", [
    ("basic", {"SKILL.md"}),
    ("reference", {"SKILL.md", "references/business-rules.md"}),
    ("script", {"SKILL.md", "references/business-rules.md", "scripts/check_input.py"}),
    ("entries", {"SKILL.md", "references/business-rules.md", "scripts/check_input.py"}),
])
def test_demo_runs_without_backend_settings(tmp_path, scenario, expected):
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("AUTH_SECRET_KEY", None)
    environment["PYTHONPATH"] = str(repository)
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "examples.skill_package_demo", "--scenario", scenario,
         "--output-dir", str(tmp_path / "builds")],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    built = json.loads(result.stdout)
    assert built["verified"] is True
    assert set(built["files"]) == expected
    root = Path(built["skill_directory"])
    raw = (root / "SKILL.md").read_text(encoding="utf-8")
    header = yaml.safe_load(raw.split("---\n", 2)[1])
    assert root.name == header["name"]
    assert ("compatibility" in header) == (scenario in {"script", "entries"})
    assert Path(built["package_zip"]).is_file()


def test_existing_model_exports_still_work():
    from applications.agent import McpServer, Skill
    from applications.agent.models.agent_model import McpServer as ModelMcpServer, Skill as ModelSkill

    assert Skill is ModelSkill
    assert McpServer is ModelMcpServer
