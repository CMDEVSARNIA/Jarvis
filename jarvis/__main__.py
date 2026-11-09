"""Start Jarvis:  python -m jarvis"""

from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser

import uvicorn

from .config import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)

    url = f"http://localhost:{settings.port}/?token={settings.hud_token}"
    print("\n  J.A.R.V.I.S. online")
    print(f"  HUD:       {url}")
    print(f"  Telegram:  {'on' if settings.telegram_enabled else 'off'}")
    print(f"  Phone:     {'on' if settings.phone_enabled else 'off'}\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    uvicorn.run("jarvis.server:app", host=settings.host, port=settings.port,
                log_level="warning")


if __name__ == "__main__":
    main()
