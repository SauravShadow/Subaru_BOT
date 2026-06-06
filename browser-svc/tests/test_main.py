from fastapi.testclient import TestClient

from main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["slots"] == 5
