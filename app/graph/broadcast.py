# app/graph/broadcast.py
"""Thread-scoped broadcast registry — decouples worker nodes from websocket.py."""
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_registry: dict[str, Callable[[dict], Awaitable[None]]] = {}


def register(thread_id: str, fn: Callable[[dict], Awaitable[None]]) -> None:
    _registry[thread_id] = fn


def unregister(thread_id: str) -> None:
    _registry.pop(thread_id, None)


async def send(thread_id: str, data: dict) -> None:
    fn = _registry.get(thread_id)
    if fn:
        try:
            await fn(data)
        except Exception as exc:
            logger.warning("broadcast send error for %s: %s", thread_id, exc)


async def noop_send(data: dict) -> None:
    pass
