"""MCP uses scoped run credentials through the production auth middleware."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from applications.wrq.agent.views.knowledge_view import search_router
from core.middlewares.auth_middleware import auth_middleware


@pytest.mark.asyncio
async def test_mcp_delegates_auth_but_neighbouring_platform_routes_stay_protected(database):
    app = FastAPI()
    app.middleware('http')(auth_middleware)
    app.include_router(search_router, prefix='/skills')

    @app.post('/skills/knowledge/search-extra')
    async def neighbour():
        pytest.fail('Platform authentication was bypassed')

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for headers in ({}, {'Authorization': 'Bearer invalid-run-token'}):
            result = await client.post('/skills/knowledge/search', headers=headers, json={'query': 'rule'})
            assert result.status_code == 403
        result = await client.post('/skills/knowledge/search-extra', json={'query': 'rule'})
        assert result.json()['status'] != 'success'
        assert 'Token' in result.json()['message']
