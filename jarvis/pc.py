"""PC actions: lock, sleep, shut down or restart (with confirmation and a delay you
can cancel), open common folders, find and open your files.

Opening files is limited to your own folders and to non-program file types, so a
file found on the PC can never be run as a program.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from . import events, winutil

HOME = Path.home()
FOLDERS = {
    "downloads": HOME / "Downloads", "documents": HOME / "Documents", "desktop": HOME / "Desktop",
    "pictures": HOME / "Pictures", "music": HOME / "Music", "videos": HOME / "Videos",
}
# Never opened by Huxley: anything that runs code.
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
               ".wsf", ".wsh", ".msi", ".msp", ".scr", ".lnk", ".url", ".reg", ".hta", ".cpl",
               ".jar", ".py", ".pyw", ".appref-ms", ".application", ".gadget", ".inf", ".sys", ".dll"}
_sleep_task: asyncio.Task | None = None


def _windows_only() -> str | None:
    return None if sys.platform == "win32" else "PC actions only work when Huxley runs on Windows."


async def pc_action(action: str, delay_minutes: float, confirmed: bool) -> str:
    """lock | sleep | shutdown | restart | cancel."""
    global _sleep_task
    if msg := _windows_only():
        return msg
    delay = max(0.0, min(24 * 60.0, float(delay_minutes or 0)))
    if action in ("sleep", "shutdown", "restart") and not confirmed:
        return (f"Not done: ask the owner to confirm the {action} first, then call again with "
                "confirmed=true.")
    if action == "lock":
        await asyncio.to_thread(winutil.lock)
        return "Locked."
    if action == "cancel":
        cancelled = []
        if _sleep_task and not _sleep_task.done():
            _sleep_task.cancel()
            cancelled.append("sleep timer")
        r = subprocess.run(["shutdown", "/a"], capture_output=True)
        if r.returncode == 0:
            cancelled.append("shutdown/restart")
        return "Cancelled " + " and ".join(cancelled) + "." if cancelled else "Nothing was scheduled."
    if action in ("shutdown", "restart"):
        seconds = max(60, int(delay * 60))  # always at least a minute to change your mind
        flag = "/s" if action == "shutdown" else "/r"
        subprocess.run(["shutdown", flag, "/t", str(seconds), "/c", f"Huxley: {action} requested"],
                       check=True)
        events.publish({"type": "activity", "label": "PC", "text": f"{action} in {seconds // 60} min"})
        return f"The PC will {action} in {seconds // 60} minute(s). Say 'cancel' to stop it."
    if action == "sleep":
        async def go_to_sleep():
            await asyncio.sleep(delay * 60)
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        _sleep_task = asyncio.create_task(go_to_sleep())
        events.publish({"type": "activity", "label": "PC", "text": f"sleep in {delay:g} min"})
        return "Going to sleep now." if delay == 0 else f"The PC will sleep in {delay:g} minutes."
    return f"Unknown action '{action}'."


async def open_folder(folder: str) -> str:
    if msg := _windows_only():
        return msg
    path = FOLDERS.get(folder.strip().lower())
    if not path or not path.exists():
        return f"Known folders: {', '.join(FOLDERS)}."
    os.startfile(path)  # type: ignore[attr-defined]
    return f"Opened {path.name}."


def _search(query: str, limit: int = 15) -> list[Path]:
    words = [w for w in query.lower().split() if w]
    hits: list[tuple[float, Path]] = []
    for base in FOLDERS.values():
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d != "node_modules"]
            if dirpath.count(os.sep) - str(base).count(os.sep) > 5:
                dirnames[:] = []
            for name in filenames:
                if all(w in name.lower() for w in words):
                    p = Path(dirpath) / name
                    try:
                        hits.append((p.stat().st_mtime, p))
                    except OSError:
                        pass
    hits.sort(reverse=True)  # newest first
    return [p for _, p in hits[:limit]]


async def find_files(query: str) -> str:
    if not query.strip():
        return "Say part of the file name to look for."
    found = await asyncio.to_thread(_search, query)
    if not found:
        return f"No files matching '{query}' in Desktop, Documents, Downloads, Pictures, Music or Videos."
    return "\n".join(f"{n}. {p}" for n, p in enumerate(found, 1))


async def open_file(path: str) -> str:
    if msg := _windows_only():
        return msg
    p = Path(path.strip().strip('"')).expanduser()
    try:
        p = p.resolve(strict=True)
    except OSError:
        return "That file doesn't exist. Use find_files first."
    if not any(base.resolve() in p.parents for base in FOLDERS.values() if base.exists()):
        return "I only open files in your Desktop, Documents, Downloads, Pictures, Music or Videos folders."
    if p.suffix.lower() in BLOCKED_EXT:
        return f"I won't open {p.suffix} files: they can run programs. Open it yourself if you trust it."
    os.startfile(p)  # type: ignore[attr-defined]
    return f"Opened {p.name}."
