"""Tests for the /ws/browser-relay WebSocket endpoint."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


def test_browser_relay_endpoint_exists():
    """Verify /ws/browser-relay accepts connections without error."""
    broadcast_calls = []

    async def fake_broadcast(data):
        broadcast_calls.append(data)

    with patch("app.api.websocket.broadcast_event", new=fake_broadcast):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/browser-relay") as ws:
                ws.send_json({
                    "type": "browser_frame",
                    "slot": 1,
                    "frame": "base64data",
                    "url": "https://linkedin.com",
                    "action": "Filling Name",
                })
                # TestClient is synchronous so we just verify no exception was raised


def test_browser_relay_ignores_invalid_json():
    """Relay endpoint should not crash on malformed messages."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/browser-relay") as ws:
            ws.send_text("not-valid-json{{{")
