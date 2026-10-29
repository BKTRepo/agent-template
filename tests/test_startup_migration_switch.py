import pytest

from configure.project_config import ProjectConfig


@pytest.mark.parametrize("system", ["Windows", "Linux"])
@pytest.mark.parametrize("debug", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
def test_startup_migration_always_respects_explicit_switch(system, debug, enabled):
    config = ProjectConfig(
        _env_file=None,
        AUTH_SECRET_KEY="migration-switch-test-" + "0" * 64,
        DATABASE_URL="sqlite://:memory:",
        SERVER_SYSTEM=system,
        SERVER_DEBUG=debug,
        DATABASE_AUTO_MIGRATION=enabled,
    )
    assert config.aerich_should_run_on_startup is enabled
