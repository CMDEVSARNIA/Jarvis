"""Small Windows helpers using only ctypes: clipboard, the Huxley window, lock/sleep.

Every function raises OSError("not on Windows") elsewhere, so callers can turn
that into a friendly message.
"""

from __future__ import annotations

import ctypes
import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
SW_MINIMIZE, SW_RESTORE = 6, 9


def _title() -> str:
    from .config import settings
    return settings.display_name


def _require_windows() -> None:
    if sys.platform != "win32":
        raise OSError("not on Windows")


def _user32():
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return user32


def _kernel32():
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    return k


def _open_clipboard(user32) -> None:
    for _ in range(10):  # another app may hold it for a moment
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("the clipboard is busy")


def read_clipboard() -> str:
    _require_windows()
    user32, kernel32 = _user32(), _kernel32()
    _open_clipboard(user32)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard(text: str) -> None:
    _require_windows()
    user32, kernel32 = _user32(), _kernel32()
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, size)
    kernel32.GlobalUnlock(handle)
    _open_clipboard(user32)
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise OSError("couldn't set the clipboard")
    finally:
        user32.CloseClipboard()


def jarvis_windows() -> list[int]:
    """Visible top-level windows showing the Huxley HUD."""
    _require_windows()
    from ctypes import wintypes

    user32 = _user32()
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith(_title()):
                found.append(hwnd)
        return True

    user32.EnumWindows(proc(callback), 0)
    return found


def set_windows(hwnds: list[int], minimized: bool) -> None:
    user32 = _user32()
    for hwnd in hwnds:
        user32.ShowWindow(hwnd, SW_MINIMIZE if minimized else SW_RESTORE)


def lock() -> None:
    _require_windows()
    if not ctypes.WinDLL("user32").LockWorkStation():
        raise OSError("couldn't lock")
