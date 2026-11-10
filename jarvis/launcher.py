"""What start-jarvis.bat runs: update, install what's new, ask for new settings, start.

    python -m jarvis.launcher [--no-update]
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

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
        print("Some components failed to install; Jarvis will try again next start.")


def main() -> int:
    _load_env()
    if "--no-update" not in sys.argv:
        print("Checking for updates...")
        print(" ", updater.update())
    _install_requirements()

    configure = [sys.executable, "-m", "jarvis.configure"]
    if (ROOT / ".env").exists():
        configure.append("--missing")  # only settings added since your last update
    subprocess.run(configure)

    args = [a for a in sys.argv[1:] if a != "--no-update"]
    return subprocess.call([sys.executable, "-m", "jarvis", *args])


if __name__ == "__main__":
    sys.exit(main())
