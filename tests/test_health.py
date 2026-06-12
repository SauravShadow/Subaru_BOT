import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health_reports_all_services(monkeypatch):
    from app.api import router as router_module

    async def fake_probe(url: str) -> bool:
        return "bark" in url  # bark up, browser down

    monkeypatch.setattr(router_module, "_probe_service", fake_probe)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")

    assert res.status_code == 200
    body = res.json()
    assert body["app"] is True
    assert body["bark"] is True
    assert body["browser"] is False
    assert "email" in body
