"""Screen and clipboard awareness. Only ever used when the owner asks.

look_at_screen hides the Jarvis window for a moment, takes a screenshot of the main
screen, brings Jarvis back, and gives Claude a downscaled JPEG (fewer tokens).
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

from . import events, winutil
from .config import local_now

MAX_SIDE = 1568  # larger images are downscaled by the API anyway


def _grab(hide_jarvis: bool) -> bytes:
    from PIL import Image, ImageGrab

    hidden = []
    if hide_jarvis:
        try:
            hidden = winutil.jarvis_windows()
            winutil.set_windows(hidden, minimized=True)
            import time
            time.sleep(0.45)  # let the minimize animation finish
        except OSError:
            hidden = []
    try:
        image = ImageGrab.grab()
    finally:
        if hidden:
            winutil.set_windows(hidden, minimized=False)
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=70)
    return out.getvalue()


async def look_at_screen() -> list[dict[str, Any]] | str:
    try:
        jpeg = await asyncio.to_thread(_grab, True)
    except ImportError:
        return "Screen capture needs the Pillow package (restart Jarvis to install it)."
    except OSError as exc:
        return f"Couldn't capture the screen ({exc})."
    events.publish({"type": "activity", "label": "SCREEN", "text": "screenshot taken for Claude"})
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(jpeg).decode()}},
        {"type": "text", "text": f"The owner's screen at {local_now():%H:%M} (Jarvis hidden)."},
    ]


async def read_clipboard() -> str:
    try:
        text = await asyncio.to_thread(winutil.read_clipboard)
    except OSError as exc:
        return f"Couldn't read the clipboard ({exc})."
    if not text.strip():
        return "The clipboard has no text in it (it may hold an image or nothing)."
    return text[:20000] + ("\n[...cut off: the copied text was very long]" if len(text) > 20000 else "")


async def write_clipboard(text: str) -> str:
    try:
        await asyncio.to_thread(winutil.write_clipboard, text)
    except OSError as exc:
        return f"Couldn't write to the clipboard ({exc})."
    return "Copied to the clipboard; the owner can paste it with Ctrl+V."
