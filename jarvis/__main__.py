"""Start Huxley:  python -m jarvis"""

from __future__ import annotations

import atexit
from pathlib import Path
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
    """On a PC, start ngrok so Twilio can reach Huxley. Returns a status line."""
    if not settings.ngrok_domain:
        return "off"
    exe = shutil.which("ngrok") or next(
        (str(p) for p in (ROOT / "ngrok.exe", ROOT / "ngrok") if p.exists()), None)
    if not exe:
        return "ngrok not found - put ngrok.exe in the Huxley folder"
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


def _pythonw() -> str:
    """The console-less Python next to this one (Windows), else this Python."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


def _setup_logging(tray: bool) -> None:
    if tray:
        # No console in tray mode: everything goes to data/jarvis.log (Tray > Open log).
        from logging.handlers import RotatingFileHandler

        (ROOT / "data").mkdir(exist_ok=True)
        handler = RotatingFileHandler(ROOT / "data" / "jarvis.log", maxBytes=1_000_000,
                                      backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(name)s: %(message)s")
        sys.stdout = sys.stderr = handler.stream
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    # httpx logs every request URL, and Telegram puts the bot token in the URL.
    # Keep those out of the logs so they're safe to read or share.
    for noisy in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _fail(tray: bool, *lines: str) -> None:
    if tray:
        from . import desktop
        desktop.message_box("Huxley can't start", "\n".join(lines))
    for line in lines:
        print(line)
    sys.exit(1)


def run_tray(url: str, open_browser: bool) -> None:
    """Windows: run the server in the background with a tray icon instead of a console."""
    import time

    from . import desktop, events, updater

    log = logging.getLogger("jarvis")
    server = uvicorn.Server(uvicorn.Config("jarvis.server:app", host=settings.host,
                                           port=settings.port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started or not thread.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        _fail(True, f"Port {settings.port} is busy: Huxley is probably already running.",
              "Look for the Huxley icon in the tray, near the clock.")
    if open_browser:
        open_hud(url)

    def show() -> None:
        if not desktop.bring_hud_to_front():
            open_hud(url)

    def on_hotkey() -> None:
        if desktop.bring_hud_to_front():
            events.publish_threadsafe({"type": "listen"})
        else:  # wait for the page to load and connect before asking it to listen
            open_hud(url)
            threading.Timer(4.0, events.publish_threadsafe, args=[{"type": "listen"}]).start()

    log.info("Talk hotkey: %s", desktop.start_hotkey(settings.talk_hotkey, on_hotkey))
    threading.Thread(target=desktop.ensure_desktop_shortcut, daemon=True).start()

    def relaunch() -> None:
        """Stop this copy and start again through the launcher (updates + new components)."""
        server.should_exit = True
        thread.join(15)
        subprocess.Popen(["cmd", "/c", "start", "/min", "", str(ROOT / "start-huxley.bat"),
                          "--no-browser"], cwd=ROOT, creationflags=0x00000008)  # DETACHED_PROCESS
        desktop.stop_tray()

    def check_updates() -> None:
        message = updater.update()
        desktop.notify("Huxley", message)
        if message.startswith("Updated"):
            time.sleep(3)
            relaunch()

    def quit_jarvis() -> None:
        server.should_exit = True
        desktop.stop_tray()

    desktop.run_tray(on_open=show, on_restart=relaunch, on_update=check_updates, on_quit=quit_jarvis)
    server.should_exit = True
    thread.join(10)


def main() -> None:
    tray = "--tray" in sys.argv and sys.platform == "win32"
    _setup_logging(tray)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _fail(tray, "ANTHROPIC_API_KEY is not set. Run:  python -m jarvis.configure")
    if not valid_anthropic_key(os.environ["ANTHROPIC_API_KEY"]):
        _fail(tray, "Your saved Claude API key doesn't look right (it may not have pasted).",
              "Run:  python -m jarvis.configure   and paste it again.")

    url = f"http://localhost:{settings.port}/?token={settings.hud_token}"
    print(f"\n  {settings.display_name} online")
    headless = "--no-browser" in sys.argv
    # On a server the output lands in the system log; keep the HUD token out of it.
    print(f"  HUD:       {'local only (token in data/hud_token)' if headless or tray else url}")
    print(f"  Telegram:  {'on' if settings.telegram_enabled else 'off'}")
    print(f"  Phone:     {'on' if settings.phone_enabled else 'off'}")
    if not headless:  # servers run the tunnel as its own service (deploy/setup-ngrok.sh)
        print(f"  Tunnel:    {start_tunnel()}")
    print()
    if tray:
        run_tray(url, open_browser=not headless)
        return
    if not headless:
        threading.Timer(1.5, open_hud, args=[url]).start()

    uvicorn.run("jarvis.server:app", host=settings.host, port=settings.port,
                log_level="warning")


if __name__ == "__main__":
    main()
