"""Start Jarvis:  python -m jarvis"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
import webbrowser

import uvicorn

from .config import ROOT, settings, valid_anthropic_key


def find_edge() -> str | None:
    """Locate Microsoft Edge on Windows (it's preinstalled on Windows 10/11)."""
    if sys.platform != "win32":
        return None
    candidates = [shutil.which("msedge")]
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as key:
                    candidates.append(winreg.QueryValue(key, None))
            except OSError:
                pass
    except ImportError:
        pass
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    return next((c for c in candidates if c and os.path.exists(c)), None)


def open_hud(url: str) -> None:
    """Open the HUD. Default: Edge as a standalone app window (no tabs or address bar),
    which also gives the best built-in voices. HUD_WINDOW=tab uses the default browser
    instead; fullscreen with HUD_FULLSCREEN=true."""
    style = os.environ.get("HUD_WINDOW", "app").strip().lower()
    edge = find_edge() if style in ("app", "edge") else None
    if edge:
        args = [edge, f"--app={url}" if style == "app" else url]
        args.append("--start-fullscreen" if os.environ.get("HUD_FULLSCREEN", "").lower() == "true"
                    else "--start-maximized")
        try:
            subprocess.Popen(args)
            return
        except OSError:
            pass
    webbrowser.open(url)


def start_tunnel() -> str:
    """On a PC, start ngrok so Twilio can reach Jarvis. Returns a status line."""
    if not settings.ngrok_domain:
        return "off"
    exe = shutil.which("ngrok") or next(
        (str(p) for p in (ROOT / "ngrok.exe", ROOT / "ngrok") if p.exists()), None)
    if not exe:
        return "ngrok not found - put ngrok.exe in the Jarvis folder"
    try:
        help_text = subprocess.run([exe, "http", "--help"], capture_output=True, text=True,
                                   timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "ngrok couldn't start"
    flag = "--url" if "--url" in help_text else "--domain"
    log_path = ROOT / "data" / "ngrok.log"
    log_file = open(log_path, "w")  # noqa: SIM115 - kept open for the process's lifetime
    proc = subprocess.Popen([exe, "http", f"{flag}={settings.ngrok_domain}", str(settings.port),
                             "--log=stdout"], stdout=log_file, stderr=subprocess.STDOUT)
    atexit.register(proc.terminate)
    return f"https://{settings.ngrok_domain}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    # httpx logs every request URL, and Telegram puts the bot token in the URL.
    # Keep those out of the logs so they're safe to read or share.
    for noisy in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run:  python -m jarvis.configure")
        sys.exit(1)
    if not valid_anthropic_key(os.environ["ANTHROPIC_API_KEY"]):
        print("Your saved Claude API key doesn't look right (it may not have pasted).")
        print("Run:  python -m jarvis.configure   and paste it again.")
        sys.exit(1)

    url = f"http://localhost:{settings.port}/?token={settings.hud_token}"
    print("\n  J.A.R.V.I.S. online")
    headless = "--no-browser" in sys.argv
    # On a server the output lands in the system log; keep the HUD token out of it.
    print(f"  HUD:       {'local only (token in data/hud_token)' if headless else url}")
    print(f"  Telegram:  {'on' if settings.telegram_enabled else 'off'}")
    print(f"  Phone:     {'on' if settings.phone_enabled else 'off'}")
    if not headless:  # servers run the tunnel as its own service (deploy/setup-ngrok.sh)
        print(f"  Tunnel:    {start_tunnel()}")
    print()
    if not headless:
        threading.Timer(1.5, open_hud, args=[url]).start()

    uvicorn.run("jarvis.server:app", host=settings.host, port=settings.port,
                log_level="warning")


if __name__ == "__main__":
    main()
