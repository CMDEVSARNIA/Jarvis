"""What start-huxley.bat runs: update, install what's new, ask for new settings, start.

    python -m jarvis.launcher [--no-update]
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from . import updater

ROOT = updater.ROOT


def _load_env() -> None:
    """Read .env without third-party packages (they may be mid-upgrade)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _install_requirements() -> None:
    req = (ROOT / "requirements.txt").read_bytes()
    digest = hashlib.sha256(req).hexdigest()
    if updater._state().get("requirements") == digest:
        return
    print("Installing updated components...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-r", str(ROOT / "requirements.txt")])
    if r.returncode == 0:
        updater._save_state(requirements=digest)
    else:
        print("Some components failed to install; Huxley will try again next start.")


def _already_running() -> bool:
    import urllib.request

    port = os.environ.get("PORT", "8000")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
            return b"jarvis-hud" in r.read(4000)
    except OSError:
        return False


def main() -> int:
    _load_env()
    console = "--console" in sys.argv or sys.platform != "win32"
    if _already_running():
        # Don't update files under a running Huxley; just bring its window up.
        print("Huxley is already running (look for the green H icon near the clock). Opening it...")
        subprocess.run([sys.executable, "-c",
                        "from jarvis.__main__ import open_hud; from jarvis.config import settings; "
                        "open_hud(f'http://localhost:{settings.port}/?token={settings.hud_token}')"])
        return 0
    if "--no-update" not in sys.argv:
        print("Checking for updates...")
        print(" ", updater.update())
    _install_requirements()

    configure = [sys.executable, "-m", "jarvis.configure"]
    if (ROOT / ".env").exists():
        configure.append("--missing")  # only settings added since your last update
    subprocess.run(configure)

    _apply_start_with_windows()
    args = [a for a in sys.argv[1:] if a not in ("--no-update", "--console")]
    if console:
        return subprocess.call([sys.executable, "-m", "jarvis", *args])
    # Windows: run in the tray, without a console window.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), "-m", "jarvis", "--tray", *args],
                     cwd=ROOT, creationflags=0x00000008 | 0x00000200,  # detached, new group
                     close_fds=True)
    print("Huxley is running in the tray (the green H icon near the clock). You can close this window.")
    return 0


def _apply_start_with_windows() -> None:
    """Keep the Startup shortcut in line with START_WITH_WINDOWS from .env."""
    if sys.platform != "win32":
        return
    from dotenv import dotenv_values

    from . import desktop

    wanted = (dotenv_values(ROOT / ".env").get("START_WITH_WINDOWS") or "no").strip().lower()
    if wanted in ("yes", "y", "true") and not desktop.shortcut_exists("Startup"):
        desktop.set_start_with_windows(True)
    elif wanted in ("no", "n", "false") and desktop.shortcut_exists("Startup"):
        desktop.set_start_with_windows(False)


if __name__ == "__main__":
    sys.exit(main())
