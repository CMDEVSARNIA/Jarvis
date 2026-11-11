"""Media and volume control through the keyboard's media keys.

Works with Spotify, YouTube in a browser, or anything else that responds to the
play/pause/next keys, with no account linking. Windows only for now.
"""

from __future__ import annotations

import asyncio
import sys
import time

# Windows virtual-key codes
KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "mute": 0xAD,
}
VOLUME_DOWN, VOLUME_UP = 0xAE, 0xAF
KEYUP = 0x0002


def _press(vk: int, times: int = 1) -> None:
    import ctypes

    user32 = ctypes.WinDLL("user32")
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYUP, 0)
        time.sleep(0.01)


def _unsupported() -> str | None:
    if sys.platform != "win32":
        return "Media control only works when Huxley runs on a Windows PC."
    return None


async def media_control(action: str) -> str:
    if msg := _unsupported():
        return msg
    if action not in KEYS:
        return f"Unknown action '{action}'. Use one of: {', '.join(KEYS)}."
    await asyncio.to_thread(_press, KEYS[action])
    return f"Pressed {action.replace('_', '/')}."


async def set_volume(level: int) -> str:
    """Windows has no simple 'set volume to N' call without extra packages, so turn
    it all the way down, then up in 2% steps (each key press moves 2%)."""
    if msg := _unsupported():
        return msg
    level = max(0, min(100, int(level)))

    def adjust() -> None:
        _press(VOLUME_DOWN, 50)
        _press(VOLUME_UP, round(level / 2))

    await asyncio.to_thread(adjust)
    return f"Volume set to about {level}%."
