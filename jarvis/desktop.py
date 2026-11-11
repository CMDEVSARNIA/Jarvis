"""Windows desktop polish: tray icon, global talk hotkey, notifications, shortcuts.

Everything here is Windows-only and degrades to a no-op elsewhere, so the server
and the cloud setup are unaffected.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from .config import ROOT

log = logging.getLogger("jarvis.desktop")
ICON_FILE = ROOT / "assets" / "huxley.ico"
TRAY_IMAGE = ROOT / "assets" / "tray-huxley.png"
LAUNCHER = ROOT / "start-huxley.bat"
SHORTCUT_NAME = "Huxley.lnk"
LEGACY_SHORTCUT = "Jarvis.lnk"  # from before the rename; replaced automatically

_tray = None  # the pystray icon while running


# ------------------------------------------------------------------ hotkey --

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "pause": 0x13, "insert": 0x2D,
              "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22}
WM_HOTKEY = 0x0312


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (modifiers, virtual key). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("a hotkey needs at least one modifier, e.g. ctrl+alt+space")
    mods = 0
    for p in parts[:-1]:
        if p not in MODIFIERS:
            raise ValueError(f"unknown modifier '{p}'")
        mods |= MODIFIERS[p]
    key = parts[-1]
    if key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unknown key '{key}'")
    return mods, vk


def start_hotkey(hotkey: str, on_press: Callable[[], None]) -> str:
    """Listen for a system-wide hotkey on a background thread. Returns a status line."""
    if sys.platform != "win32" or not hotkey.strip():
        return "off"
    try:
        mods, vk = parse_hotkey(hotkey)
    except ValueError as exc:
        return f"invalid ({exc})"
    result: dict = {}
    ready = threading.Event()

    def loop() -> None:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            result["error"] = "already used by another program"
            ready.set()
            return
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                try:
                    on_press()
                except Exception:
                    log.exception("Hotkey handler failed")

    threading.Thread(target=loop, name="hotkey", daemon=True).start()
    ready.wait(3)
    return f"{hotkey} ({result['error']})" if "error" in result else hotkey


def bring_hud_to_front() -> bool:
    """Restore and focus the Huxley window. False if it isn't open."""
    if sys.platform != "win32":
        return False
    from . import winutil

    windows = winutil.jarvis_windows()
    user32 = ctypes.WinDLL("user32")
    for hwnd in windows:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(windows)


# ------------------------------------------------------------ notifications --

def notify(title: str, text: str) -> None:
    """A Windows notification from the tray icon (no-op without the tray)."""
    if _tray is None:
        return
    try:
        _tray.notify(text[:250], title[:60])
    except Exception:
        log.warning("Couldn't show a notification")


# --------------------------------------------------------------- shortcuts --

def _shortcut(folder: str, create: bool, name: str = SHORTCUT_NAME) -> bool:
    """Create or remove a shortcut in a special folder ('Desktop' or 'Startup')."""
    if sys.platform != "win32":
        return False
    env = {**os.environ, "J_FOLDER": folder, "J_NAME": name, "J_TARGET": str(LAUNCHER),
           "J_WD": str(ROOT), "J_ICON": str(ICON_FILE), "J_CREATE": "1" if create else "0"}
    # Values travel in environment variables, so paths with spaces need no quoting.
    script = (
        "$p = Join-Path ([Environment]::GetFolderPath($env:J_FOLDER)) $env:J_NAME; "
        "if ($env:J_CREATE -eq '1') { $s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); "
        "$s.TargetPath = $env:J_TARGET; $s.WorkingDirectory = $env:J_WD; $s.IconLocation = $env:J_ICON; "
        "$s.WindowStyle = 7; $s.Description = 'Start Huxley'; $s.Save() } "
        "elseif (Test-Path $p) { Remove-Item $p }")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env=env, capture_output=True, text=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        log.warning("Shortcut update failed: %s", r.stderr.strip()[:200])
    return r.returncode == 0


def shortcut_exists(folder: str, name: str = SHORTCUT_NAME) -> bool:
    if sys.platform != "win32":
        return False
    base = {"Desktop": Path.home() / "Desktop",
            "Startup": Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"}
    path = base.get(folder)
    return bool(path and (path / name).exists())


def set_start_with_windows(enabled: bool) -> bool:
    return _shortcut("Startup", enabled)


def ensure_desktop_shortcut() -> None:
    """Create the Huxley desktop shortcut once, and swap any old Jarvis shortcuts
    (desktop and Start with Windows) for Huxley ones with the new icon."""
    from .updater import _save_state, _state

    if sys.platform != "win32":
        return
    for folder in ("Desktop", "Startup"):
        if shortcut_exists(folder, LEGACY_SHORTCUT):
            _shortcut(folder, False, LEGACY_SHORTCUT)
            _shortcut(folder, True)
    if not _state().get("huxley_shortcut"):
        if shortcut_exists("Desktop") or _shortcut("Desktop", True):
            _save_state(huxley_shortcut=True)


# -------------------------------------------------------------------- tray --

def run_tray(on_open: Callable[[], None], on_restart: Callable[[], None],
             on_update: Callable[[], None], on_quit: Callable[[], None]) -> None:
    """Show the tray icon; blocks until Quit. Right-click for the menu."""
    global _tray
    import pystray
    from PIL import Image

    def toggle_startup(icon, item) -> None:
        enable = not shortcut_exists("Startup")
        if set_start_with_windows(enable):
            # Save the choice too, or the launcher would undo it on the next start.
            from dotenv import set_key
            set_key(str(ROOT / ".env"), "START_WITH_WINDOWS", "yes" if enable else "no", quote_mode="never")

    def open_log(icon, item) -> None:
        log_file = ROOT / "data" / "jarvis.log"
        if log_file.exists():
            os.startfile(log_file)  # type: ignore[attr-defined]

    def run(fn):
        return lambda icon, item: threading.Thread(target=fn, daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("Open Huxley", run(on_open), default=True),
        pystray.MenuItem("Check for updates", run(on_update)),
        pystray.MenuItem("Restart Huxley", run(on_restart)),
        pystray.MenuItem("Start with Windows", toggle_startup,
                         checked=lambda item: shortcut_exists("Startup")),
        pystray.MenuItem("Open log", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Huxley", lambda icon, item: on_quit()),
    )
    from .config import settings
    _tray = pystray.Icon("jarvis", Image.open(TRAY_IMAGE), settings.display_name, menu)
    try:
        _tray.run()
    finally:
        _tray = None


def stop_tray() -> None:
    if _tray is not None:
        _tray.stop()


def message_box(title: str, text: str) -> None:
    """A simple Windows dialog, for errors when there's no console to print to."""
    if sys.platform == "win32":
        ctypes.WinDLL("user32").MessageBoxW(None, text, title, 0x10)  # MB_ICONERROR
