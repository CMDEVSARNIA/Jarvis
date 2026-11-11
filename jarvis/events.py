"""Tiny pub/sub so every open HUD sees what Huxley is doing on any channel
(HUD, Telegram, phone call)."""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any

_subscribers: set[asyncio.Queue] = set()
LOOP: asyncio.AbstractEventLoop | None = None  # set by the server at startup
# Which HUD window (laptop or phone) started the work in progress. Events get tagged
# with it, so only the screen you asked from speaks the answer out loud.
ORIGIN: contextvars.ContextVar[str] = contextvars.ContextVar("origin", default="")


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
    origin = ORIGIN.get()
    if origin and "origin" not in event:
        event = {**event, "origin": origin}
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # a stalled HUD tab shouldn't block Huxley
