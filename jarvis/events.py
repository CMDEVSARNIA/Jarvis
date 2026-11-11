"""Tiny pub/sub so every open HUD sees what Jarvis is doing on any channel
(HUD, Telegram, phone call)."""

from __future__ import annotations

import asyncio
from typing import Any

_subscribers: set[asyncio.Queue] = set()
LOOP: asyncio.AbstractEventLoop | None = None  # set by the server at startup


def listeners() -> int:
    """How many HUD windows are connected."""
    return len(_subscribers)


def publish_threadsafe(event: dict[str, Any]) -> None:
    """publish() from another thread (the hotkey or tray threads)."""
    if LOOP is not None:
        LOOP.call_soon_threadsafe(publish, event)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # a stalled HUD tab shouldn't block Jarvis
