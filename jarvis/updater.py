"""Self-update from GitHub, run by start-huxley.bat before Huxley starts.

Downloads the latest code only when it has changed, and replaces program files
while never touching your settings or data:
  .env, data/, .venv/, config/apps.json (your app list), ngrok.exe, .git/

Uses only the Python standard library, so it keeps working even when an update
adds new packages. Turn it off with AUTO_UPDATE=false in .env. If this folder is
a git checkout, it runs `git pull` instead.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "version.json"
REPO = os.environ.get("UPDATE_REPO", "CMDEVSARNIA/Jarvis")
API = "https://api.github.com/repos/" + REPO

PROTECTED_TOP = {".env", "data", ".venv", ".git", "ngrok.exe", "ngrok"}
KEEP_IF_PRESENT = {"config/apps.json"}          # yours once you've edited it
# Windows reads a running .bat file as it goes, so the launcher is never
# rewritten in place: it's staged and swapped in on the next start.
STAGED = {"start-jarvis.bat": "start-jarvis.new.bat", "start-huxley.bat": "start-huxley.new.bat"}


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    headers = {"Accept": accept, "User-Agent": "jarvis-updater"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()  # only needed for a private repo
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(**values) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({**_state(), **values}, indent=2), encoding="utf-8")


def _safe_target(rel: str) -> Path | None:
    """Map a path from the zip to this folder; None if it must not be written."""
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ("..", "") for p in parts) or PurePosixPath(rel).is_absolute():
        return None
    if parts[0] in PROTECTED_TOP:
        return None
    if rel in KEEP_IF_PRESENT and (ROOT / rel).exists():
        return None
    target = (ROOT / STAGED.get(rel, rel)).resolve()
    if ROOT not in target.parents:
        return None
    return target


def apply_zip(data: bytes) -> list[str]:
    """Write changed files from a GitHub zipball. Returns the paths changed."""
    changed = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            target = _safe_target(rel)
            if target is None:
                continue
            content = zf.read(info)
            real = ROOT / rel
            if real.exists() and real.read_bytes() == content:
                if target != real and target.exists():
                    target.unlink()  # a staged launcher that's no longer needed
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(content)
            tmp.replace(target)
            changed.append(rel)
    return changed


def _git_pull() -> str:
    if not shutil.which("git"):
        return "This folder is a git checkout but git isn't installed; skipping update."
    r = subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only"], capture_output=True, text=True)
    return "Updated with git." if r.returncode == 0 and "Already up to date" not in r.stdout \
        else ("Up to date." if r.returncode == 0 else "git pull failed: " + r.stderr.strip()[:200])


def update() -> str:
    if os.environ.get("AUTO_UPDATE", "true").strip().lower() == "false":
        return "Auto-update is off (AUTO_UPDATE=false)."
    if (ROOT / ".git").exists():
        return _git_pull()
    try:
        branch = os.environ.get("UPDATE_BRANCH") or json.loads(_get(API))["default_branch"]
        sha = json.loads(_get(f"{API}/commits/{branch}"))["sha"]
        if _state().get("sha") == sha:
            return "Huxley is up to date."
        changed = apply_zip(_get(f"{API}/zipball/{sha}", accept="*/*"))
        _save_state(sha=sha)
        if not changed:
            return "Huxley is up to date."
        note = " The launcher itself changed; that applies on the next start." \
            if any(c in STAGED for c in changed) else ""
        return f"Updated Huxley ({len(changed)} files).{note}"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return (f"Couldn't check for updates (GitHub said {exc.code}). If the repository is "
                    "private, add a read-only GITHUB_TOKEN to .env.")
        return f"Couldn't check for updates (GitHub error {exc.code}). Starting anyway."
    except (urllib.error.URLError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        return f"Couldn't check for updates ({type(exc).__name__}). Starting anyway."
