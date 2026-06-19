import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def goal_db(tmp_path):
    import app.services.goals as g
    original = g.DB_PATH
    g.DB_PATH = tmp_path / "api_goals.db"
    g.init_db()
    yield g
    g.DB_PATH = original


@pytest.mark.asyncio
async def test_api_goals_returns_active(goal_db):
    goal_db.create_goal("Active one")
    done = goal_db.create_goal("Done one")
    goal_db.update_goal_status(done, "done")

    from app.api import router as router_module
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/goals?status=active")

    assert res.status_code == 200
    titles = {g["title"] for g in res.json()["goals"]}
    assert "Active one" in titles
    assert "Done one" not in titles


@pytest.mark.asyncio
async def test_api_goals_all_when_no_status(goal_db):
    goal_db.create_goal("G1")
    goal_db.create_goal("G2")

    from app.api import router as router_module
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/goals")

    assert res.status_code == 200
    assert len(res.json()["goals"]) == 2
