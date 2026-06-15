import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_call_history_returns_list(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_call_history.return_value = [
            {"id": "c1", "direction": "outbound", "number": "+91123", "goal": "Book table",
             "outcome": "success", "summary": "Table booked.", "started_at": "2026-06-14T10:00:00"},
        ]
        resp = client.get("/api/calls/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "c1"


def test_call_history_filters_passed(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_call_history.return_value = []
        # '+' must be percent-encoded in a query string, else it decodes to a space
        client.get("/api/calls/history?direction=outbound&outcome=success&number=%2B91")
        mock_store.get_call_history.assert_called_once_with(
            direction="outbound", outcome="success", number_prefix="+91", limit=50
        )


def test_call_transcript_returns_detail(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_transcript.return_value = {
            "id": "c2", "goal": "Book flight",
            "transcript": [{"speaker": "nexus", "text": "Hello!", "timestamp": "2026-06-14T10:01:00"}],
        }
        resp = client.get("/api/calls/c2/transcript")
    assert resp.status_code == 200
    assert resp.json()["id"] == "c2"
    assert len(resp.json()["transcript"]) == 1


def test_call_transcript_404_for_missing(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.get_transcript.return_value = None
        resp = client.get("/api/calls/nonexistent/transcript")
    assert resp.status_code == 404


def test_call_search_returns_results(client):
    with patch("app.api.router.call_store") as mock_store:
        mock_store.search_calls.return_value = [
            {"id": "c3", "goal": "Book flight to Mumbai", "summary": "Flight enquiry done."}
        ]
        resp = client.get("/api/calls/search?q=Mumbai")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "c3"
