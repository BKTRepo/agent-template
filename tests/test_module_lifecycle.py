from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from core.initializations import module_initialization


@pytest.mark.asyncio
async def test_application_lifespan_starts_and_stops_modules_in_order(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        module_initialization,
        "register_database",
        AsyncMock(side_effect=lambda app: calls.append("main-db-start")),
    )
    monkeypatch.setattr(
        module_initialization,
        "init_database_table",
        AsyncMock(side_effect=lambda app: calls.append("main-db-init")),
    )
    monkeypatch.setattr(
        module_initialization,
        "start_ticket_review",
        AsyncMock(side_effect=lambda app: calls.append("ticket-start")),
    )
    monkeypatch.setattr(
        module_initialization,
        "start_code_server_ide",
        AsyncMock(side_effect=lambda app: calls.append("ide-start")),
    )
    monkeypatch.setattr(
        module_initialization,
        "stop_code_server_ide",
        AsyncMock(side_effect=lambda app: calls.append("ide-stop")),
    )
    monkeypatch.setattr(
        module_initialization,
        "stop_ticket_review",
        AsyncMock(side_effect=lambda app: calls.append("ticket-stop")),
    )
    monkeypatch.setattr(
        module_initialization.Tortoise,
        "close_connections",
        AsyncMock(side_effect=lambda: calls.append("main-db-stop")),
    )

    app = FastAPI()
    async with module_initialization.application_lifespan(app):
        # 只为实际启用的模块模拟“启动成功”。测试期望值跟随当前
        # .env 开关，关闭的可选模块不应被强制计入生命周期顺序。
        if module_initialization.PROJECT_CONFIG.TICKET_REVIEW_ENABLED:
            app.state.ticket_review_started = True
        if module_initialization.PROJECT_CONFIG.CODE_SERVER_IDE_ENABLED:
            app.state.code_server_ide_started = True
        calls.append("running")

    expected = ["main-db-start", "main-db-init"]
    if module_initialization.PROJECT_CONFIG.TICKET_REVIEW_ENABLED:
        expected.append("ticket-start")
    if module_initialization.PROJECT_CONFIG.CODE_SERVER_IDE_ENABLED:
        expected.append("ide-start")
    expected.append("running")
    if module_initialization.PROJECT_CONFIG.CODE_SERVER_IDE_ENABLED:
        expected.append("ide-stop")
    if module_initialization.PROJECT_CONFIG.TICKET_REVIEW_ENABLED:
        expected.append("ticket-stop")
    expected.append("main-db-stop")
    assert calls == expected


@pytest.mark.asyncio
async def test_partial_startup_still_stops_started_ticket_module(monkeypatch):
    app = FastAPI()

    async def start_ticket(target):
        target.state.ticket_review_started = True

    monkeypatch.setattr(module_initialization, "register_database", AsyncMock())
    monkeypatch.setattr(module_initialization, "init_database_table", AsyncMock())
    monkeypatch.setattr(module_initialization, "start_ticket_review", AsyncMock(side_effect=start_ticket))
    monkeypatch.setattr(
        module_initialization,
        "start_code_server_ide",
        AsyncMock(side_effect=RuntimeError("IDE startup failed")),
    )
    stop_ticket = AsyncMock()
    monkeypatch.setattr(module_initialization, "stop_ticket_review", stop_ticket)
    monkeypatch.setattr(module_initialization, "stop_code_server_ide", AsyncMock())
    monkeypatch.setattr(module_initialization.Tortoise, "close_connections", AsyncMock())

    if module_initialization.PROJECT_CONFIG.CODE_SERVER_IDE_ENABLED:
        with pytest.raises(RuntimeError, match="IDE startup failed"):
            async with module_initialization.application_lifespan(app):
                pass
    else:
        async with module_initialization.application_lifespan(app):
            pass

    if module_initialization.PROJECT_CONFIG.TICKET_REVIEW_ENABLED:
        stop_ticket.assert_awaited_once_with(app)
    else:
        stop_ticket.assert_not_awaited()


def test_health_reports_test_case_generate_as_celery_module():
    app = FastAPI()

    health = module_initialization.application_health(app)

    assert health["modules"]["test_case_generate"] == {
        "registered": True,
        "executor": "celery",
        "outputDirectory": module_initialization.PROJECT_CONFIG.TEST_CASE_OUTPUT_DIR,
    }
