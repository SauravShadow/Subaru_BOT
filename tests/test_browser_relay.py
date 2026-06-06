"""Tests for the /ws/browser-relay WebSocket endpoint."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


def test_browser_relay_endpoint_exists():
    """Verify /ws/browser-relay accepts connections and broadcasts received events."""
    broadcast_calls = []

    async def fake_broadcast(data):
        broadcast_calls.append(data)

    with patch("app.main.broadcast_event", new=fake_broadcast):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/browser-relay") as ws:
                ws.send_json({
                    "type": "browser_frame",
                    "slot": 1,
                    "frame": "base64data",
                    "url": "https://linkedin.com",
                    "action": "Filling Name",
                })

    assert len(broadcast_calls) == 1
    payload = broadcast_calls[0]
    assert payload["type"] == "browser_frame"
    assert payload["slot"] == 1
    assert payload["frame"] == "base64data"
    assert payload["url"] == "https://linkedin.com"
    assert payload["action"] == "Filling Name"


def test_browser_relay_ignores_invalid_json():
    """Relay endpoint should not crash on malformed messages."""
    broadcast_calls = []

    async def fake_broadcast(data):
        broadcast_calls.append(data)

    with patch("app.main.broadcast_event", new=fake_broadcast):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/browser-relay") as ws:
                # Sending malformed text — endpoint should handle gracefully and disconnect
                ws.send_text("not-valid-json{{{")
                # No exception should escape the context manager

    # Connection received bad input and disconnected; broadcast was never called
    assert len(broadcast_calls) == 0
