"""Binary catalog downloads must survive the production audit middleware unchanged."""
import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock
from core.middlewares import app_middleware


@pytest.mark.asyncio
@pytest.mark.parametrize('media_type', ['application/zip', 'application/octet-stream', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'])
async def test_binary_response_not_decoded_or_truncated(monkeypatch, media_type):
    payload = b'PK\x03\x04\xff\xfe\x00\x80\xe4\xb8\xad'
    monkeypatch.setattr(app_middleware, '_resolve_audit_user', AsyncMock(return_value=(0, '')))
    monkeypatch.setattr(app_middleware.Audit, 'create', AsyncMock())
    app = FastAPI()
    app.middleware('http')(app_middleware.logging_middleware)

    @app.get('/binary')
    async def binary():
        return Response(payload, media_type=media_type)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/binary', headers={'authorization': 'Bearer scoped-test-credential'})
        assert response.content == payload
        assert int(response.headers['content-length']) == len(payload)
    kwargs = app_middleware.Audit.create.call_args.kwargs
    assert kwargs['request_header']['authorization'] == '[REDACTED]'
