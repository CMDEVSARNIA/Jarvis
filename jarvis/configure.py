"""Interactive settings helper, so you never have to hand-edit .env.

    python -m jarvis.configure          (Windows: .venv\\Scripts\\python -m jarvis.configure)

Press Enter to keep the value shown in [brackets]. Secrets are typed hidden.
"""

from __future__ import annotations

import os
import shutil
import sys
from getpass import getpass

from dotenv import dotenv_values, set_key

from .config import ROOT

ENV = ROOT / ".env"

MODELS = {
    "1": ("claude-sonnet-5-5", "Sonnet 5.5 - fast, about half the price of Opus (recommended for low cost)"),
    "2": ("claude-opus-5-5", "Opus 5.5 - smartest, costs more"),
    "3": ("claude-haiku-5-5", "Haiku 5.5 - cheapest, no web search"),
}


def ask(current: dict, key: str, prompt: str, secret: bool = False, default: str = "") -> None:
    old = current.get(key) or default
    if secret:
        shown = f"[{old[:7]}...{old[-4:]}]" if len(old) > 12 else "[not set]"
        value = getpass(f"{prompt} {shown}: ").strip()
    else:
        value = input(f"{prompt} [{old or 'not set'}]: ").strip()
    if value == "-":          # explicit clear
        value = ""
    elif not value:
        value = old
    set_key(str(ENV), key, value, quote_mode="never")
    current[key] = value


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def yes(prompt: str) -> bool:
    return input(f"{prompt} (y/N): ").strip().lower().startswith("y")


def main() -> None:
    if not ENV.exists():
        shutil.copy(ROOT / ".env.example", ENV)
    if os.name != "nt":
        os.chmod(ENV, 0o600)  # only you can read your keys
    cur = {k: (v or "") for k, v in dotenv_values(ENV).items()}

    print("Jarvis setup. Press Enter to keep a value, type - to clear it.")

    section("Claude")
    ask(cur, "ANTHROPIC_API_KEY", "Anthropic API key (hidden while typing)", secret=True)
    print("Which model?")
    for n, (_, label) in MODELS.items():
        print(f"  {n}) {label}")
    choice = input(f"Choose 1-3 [{cur.get('JARVIS_MODEL') or 'claude-opus-5-5'}]: ").strip()
    if choice in MODELS:
        set_key(str(ENV), "JARVIS_MODEL", MODELS[choice][0], quote_mode="never")
    ask(cur, "OWNER_NAME", "What should Jarvis call you", default="sir")

    section("Telegram (phone chat)")
    ask(cur, "TELEGRAM_BOT_TOKEN", "Bot token from @BotFather (hidden)", secret=True)
    ask(cur, "TELEGRAM_OWNER_CHAT_ID", "Your chat id (leave blank on first run; the bot tells you)")

    section("Phone calls (Twilio) - optional")
    if yes("Set up phone calls now?"):
        ask(cur, "TWILIO_ACCOUNT_SID", "Twilio Account SID")
        ask(cur, "TWILIO_AUTH_TOKEN", "Twilio Auth Token (hidden)", secret=True)
        ask(cur, "TWILIO_FROM_NUMBER", "Your Twilio number, e.g. +15551234567")
        ask(cur, "OWNER_PHONE_NUMBER", "YOUR cell number, e.g. +15557654321")
        ask(cur, "PUBLIC_BASE_URL", "Public URL, e.g. https://your-name.ngrok-free.app")
        url = cur.get("PUBLIC_BASE_URL", "").rstrip("/")
        set_key(str(ENV), "PUBLIC_BASE_URL", url, quote_mode="never")
        for key in ("TWILIO_FROM_NUMBER", "OWNER_PHONE_NUMBER"):
            if cur.get(key) and not cur[key].startswith("+"):
                print(f"  Warning: {key} should start with + and the country code (US: +1).")

    print(f"\nSaved to {ENV}")
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        print("Apply with:  sudo systemctl restart jarvis")
    else:
        print("Restart Jarvis to apply.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; anything already entered was saved.")
