from fastapi.testclient import TestClient


def test_health():
    from main import app
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["slots"] == 5
