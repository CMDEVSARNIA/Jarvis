"""Huxley on your phone, through Tailscale (a free private network between your own devices).

`tailscale serve` gives this laptop a private https:// address that only devices
signed in to your Tailscale account can open, and forwards it to Huxley's phone
port (127.0.0.1 only). Nothing is opened to the internet. The phone still needs the
HUD access key, which the pairing QR code carries.

Only the HUD's PAIR PHONE button on this laptop runs these fixed commands; Claude
has no tool that reaches them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys

log = logging.getLogger("jarvis.tailnet")
DOWNLOAD_URL = "https://tailscale.com/download"


def find_cli() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            path = os.path.join(base, "Tailscale", "tailscale.exe") if base else ""
            if path and os.path.exists(path):
                return path
    return None


def _run(args: list[str], timeout: float) -> tuple[int | None, str]:
    """Run the Tailscale CLI. Returns (exit code, output); code None on timeout."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:  # e.g. waiting for you to switch HTTPS on
        out = exc.stdout or b""
        err = exc.stderr or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return None, out + err
    except OSError as exc:
        return 1, str(exc)


LOGIN_LINK = re.compile(r"https://login\.tailscale\.com/\S+")


def _serve_bg(cli: str, target: str, timeout: float = 25) -> tuple[int | None, str]:
    """`tailscale serve --bg`. If HTTPS is off for the account, Tailscale prints a
    link and then waits for you to use it; return as soon as the link shows up."""
    import queue
    import threading
    import time

    try:
        proc = subprocess.Popen([cli, "serve", "--bg", f"http://{target}"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        return 1, str(exc)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()
    out, deadline = "", time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            out += lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and lines.empty():
                return proc.returncode, out
            continue
        if LOGIN_LINK.search(out):
            break
    if proc.poll() is None:
        proc.kill()  # it was waiting for HTTPS to be switched on; pairing again retries
        return None, out
    return proc.returncode, out


def setup(port: int) -> dict:
    """Make sure this laptop's Tailscale address forwards to Huxley's phone port.

    Returns {"state": ...}:
      install      - Tailscale isn't installed on this laptop
      signin       - installed, but not signed in / not connected
      enable_https - your Tailscale account needs HTTPS switched on (one click: "link")
      error        - something else ("detail")
      ready        - working: "url" is the phone address
    """
    if not port:
        return {"state": "error", "detail": "Phone access is off (PHONE_PORT=0 in .env)."}
    cli = find_cli()
    if not cli:
        return {"state": "install", "link": DOWNLOAD_URL}

    code, out = _run([cli, "status", "--json"], timeout=15)
    try:
        status = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        status = {}
    if status.get("BackendState") != "Running":
        return {"state": "signin", "detail": status.get("BackendState") or "not connected"}
    dns = ((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not dns:
        return {"state": "enable_https", "link": "https://login.tailscale.com/admin/dns"}

    target = f"127.0.0.1:{port}"
    _, current = _run([cli, "serve", "status", "--json"], timeout=15)
    if target not in current:
        code, out = _serve_bg(cli, target)
        link = LOGIN_LINK.search(out)
        if link:
            return {"state": "enable_https", "link": link.group(0).rstrip(".,)")}
        if code != 0:
            log.warning("tailscale serve failed: %s", out.strip()[-300:])
            return {"state": "error", "detail": out.strip()[-300:] or "tailscale serve didn't finish"}
    return {"state": "ready", "url": f"https://{dns}/"}


def qr_svg(text: str) -> str:
    """A QR code as an inline SVG. Dark squares on a light background: phone
    cameras read that way round most reliably."""
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    svg = svg[svg.find("<svg"):]
    # Fixed size from the page's CSS, not millimetres.
    return re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
