"""Start Jarvis:  python -m jarvis"""

from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser

import uvicorn

from .config import settings, valid_anthropic_key


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
    print(f"  Phone:     {'on' if settings.phone_enabled else 'off'}\n")
    if not headless:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    uvicorn.run("jarvis.server:app", host=settings.host, port=settings.port,
                log_level="warning")


if __name__ == "__main__":
    main()
