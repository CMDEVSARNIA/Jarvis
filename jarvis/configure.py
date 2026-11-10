"""Interactive settings helper, so you never have to hand-edit .env.

    python -m jarvis.configure          (Windows: .venv\\Scripts\\python -m jarvis.configure)

Press Enter to keep the value shown in [brackets]. Secrets are hidden as you type;
Ctrl+V and right-click both paste.
"""

from __future__ import annotations

import os
import shutil
import sys
from getpass import getpass

from dotenv import dotenv_values, set_key

from .config import ROOT, clean_chat_id, valid_anthropic_key, valid_telegram_token

ENV = ROOT / ".env"

MODELS = {
    "1": ("claude-sonnet-5-5", "Sonnet 5.5 - fast, about half the price of Opus (recommended for low cost)"),
    "2": ("claude-opus-5-5", "Opus 5.5 - smartest, costs more"),
    "3": ("claude-haiku-5-5", "Haiku 5.5 - cheapest, no web search"),
}


VALIDATORS = {
    "ANTHROPIC_API_KEY": (valid_anthropic_key, "Claude keys start with sk-ant- and are long"),
    "TELEGRAM_BOT_TOKEN": (valid_telegram_token, "Telegram tokens look like 123456789:AAF..."),
}


def _windows_clipboard() -> str:
    """Read text from the Windows clipboard (no extra packages)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    kernel32 = ctypes.WinDLL("kernel32")
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def read_secret(prompt: str) -> str:
    """Hidden input. On Windows, getpass turns Ctrl+V into a junk character
    instead of pasting, so handle keys ourselves and paste from the clipboard."""
    if os.name != "nt":
        return getpass(prompt).strip()
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            break
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x08":
            if chars:
                chars.pop()
        elif ch == "\x16":  # Ctrl+V
            try:
                chars.extend(_windows_clipboard().strip())
            except Exception:
                print("\n  (Couldn't read the clipboard. Right-click to paste instead.)")
        elif ch in ("\x00", "\xe0"):  # arrow/function keys send two codes
            msvcrt.getwch()
        elif ch.isprintable():
            chars.append(ch)
    value = "".join(chars).strip()
    print(f"  ({len(value)} characters entered)" if value else "")
    return value


def ask(current: dict, key: str, prompt: str, secret: bool = False, default: str = "") -> None:
    old = current.get(key) or default
    check = VALIDATORS.get(key)
    for _attempt in range(3):
        if secret:
            if not old:
                shown = "[not set]"
            elif check and not check[0](old):
                shown = "[saved value looks wrong - paste it again]"
            else:
                shown = f"[{old[:7]}...{old[-4:]}]"
            value = read_secret(f"{prompt} {shown}: ")
        else:
            value = input(f"{prompt} [{old or 'not set'}]: ").strip()
        if value == "-":          # explicit clear
            value = ""
            break
        if not value:
            value = old
            if not (check and old and not check[0](old)):
                break
            print(f"  The saved value doesn't look right. {check[1]}.")
            continue
        if check and not check[0](value):
            print(f"  That doesn't look right ({len(value)} characters). {check[1]}. Try again.")
            continue
        break
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
    print("Workspace ID: only needed if your key is NOT scoped to a workspace.")
    print("  Find it at platform.claude.com > Workspaces (starts with wrkspc_). Leave blank otherwise.")
    ask(cur, "ANTHROPIC_WORKSPACE_ID", "Workspace ID")
    ws = cur.get("ANTHROPIC_WORKSPACE_ID", "")
    if ws and not ws.startswith("wrkspc_"):
        print("  Warning: workspace IDs start with wrkspc_ - check you copied the ID, not the name.")
    ask(cur, "OWNER_NAME", "What should Jarvis call you", default="sir")

    section("Telegram (phone chat)")
    ask(cur, "TELEGRAM_BOT_TOKEN", "Bot token from @BotFather (hidden)", secret=True)
    ask(cur, "TELEGRAM_OWNER_CHAT_ID", "Your chat id (leave blank on first run; the bot tells you)")
    raw = cur.get("TELEGRAM_OWNER_CHAT_ID", "")
    cleaned = clean_chat_id(raw)
    if raw and cleaned != raw:
        print(f"  Saved just the number: {cleaned or '(none found - leave blank and ask the bot again)'}")
        set_key(str(ENV), "TELEGRAM_OWNER_CHAT_ID", cleaned, quote_mode="never")
        cur["TELEGRAM_OWNER_CHAT_ID"] = cleaned

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
