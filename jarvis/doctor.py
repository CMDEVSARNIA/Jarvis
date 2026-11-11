"""Connection checkup. Run:  python -m jarvis.doctor   (Windows: .venv\\Scripts\\python -m jarvis.doctor)

Prints a report that is safe to share: it never prints keys or tokens, only whether
they look right. Each step narrows down where a Claude API problem comes from.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys

import anthropic

from .config import (ROOT, claude_headers, settings, valid_telegram_token, valid_twilio_sid,
                     valid_twilio_token)

SAFE_HEADERS = ("content-type", "content-length", "server", "request-id", "cf-ray", "via", "x-cache")


def line(label: str, value: object) -> None:
    print(f"  {label:<28} {value}")


def section(title: str) -> None:
    print(f"\n== {title} ==")


def describe_error(exc: Exception) -> None:
    if isinstance(exc, anthropic.APIStatusError):
        resp = exc.response
        line("result", f"HTTP {exc.status_code}")
        line("url", f"{resp.request.method} {resp.request.url}")
        for h in SAFE_HEADERS:
            if h in resp.headers:
                line(h, resp.headers[h])
        body = (resp.text or "").strip()
        line("body", body[:400] if body else "(empty)")
    elif isinstance(exc, anthropic.APIConnectionError):
        line("result", f"could not connect: {exc.__cause__ or exc}")
    else:
        line("result", f"{type(exc).__name__}: {exc}")


def check_key() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    section("API key (never printed)")
    if not key:
        line("ANTHROPIC_API_KEY", "MISSING - run python -m jarvis.configure")
        return False
    problems = []
    if not key.startswith("sk-ant-"):
        problems.append(f"starts with '{key[:7]}', expected 'sk-ant-'")
    if any(c.isspace() for c in key):
        problems.append("contains spaces or line breaks")
    if not key.isascii():
        problems.append("contains non-standard characters (bad paste?)")
    if key.startswith(('"', "'")) or key.endswith(('"', "'")):
        problems.append("wrapped in quotes")
    line("type prefix", key[:10] + "...")
    line("length", len(key))
    line("ends with", "..." + key[-4:])
    line("looks valid", "yes" if not problems else "NO: " + "; ".join(problems))
    return not problems


def check_telegram() -> None:
    """Which bot does the saved token belong to? (The token itself is never printed.)"""
    import httpx

    section("Telegram")
    token = settings.telegram_token
    if not token:
        line("bot token", "MISSING - run python -m jarvis.configure")
        return
    line("chat id saved", settings.telegram_owner_chat_id or "not set (the bot will tell you yours)")
    if not valid_telegram_token(token):
        line("bot token", f"LOOKS WRONG ({len(token)} characters) - paste it again with the settings tool")
        return
    base = f"https://api.telegram.org/bot{token}/"
    try:
        me = httpx.get(base + "getMe", timeout=15)
        if me.status_code in (401, 404):
            line("bot token", "REJECTED by Telegram - copy it again from @BotFather")
            return
        bot = me.json().get("result", {})
        line("token belongs to", f"@{bot.get('username')}  ({bot.get('first_name')})")
        hook = httpx.get(base + "getWebhookInfo", timeout=15).json().get("result", {})
        line("webhook", "was set - Huxley clears it when it starts" if hook.get("url") else "none (good)")
        line("waiting messages", hook.get("pending_update_count", "?"))
    except Exception as exc:  # never print str(exc): it contains the token
        line("result", f"could not reach Telegram ({type(exc).__name__})")
        return
    print("  -> Message exactly that @username. Search it in Telegram, or open t.me/<username>.")


def check_phone() -> None:
    """Phone-call settings (secrets never printed) and whether Twilio can reach Huxley."""
    import httpx

    section("Phone calls")
    if not any([settings.twilio_sid, settings.twilio_token, settings.ngrok_domain]):
        line("status", "not set up (optional)")
        return
    line("Account SID", "looks valid" if valid_twilio_sid(settings.twilio_sid) else "LOOKS WRONG - re-enter it")
    line("Auth Token", "looks valid" if valid_twilio_token(settings.twilio_token) else "LOOKS WRONG - re-enter it")
    for label, num in (("Twilio number", settings.twilio_from), ("your cell", settings.owner_phone)):
        ok = num.startswith("+") and num[1:].isdigit() and len(num) >= 11
        line(label, num if ok else f"'{num}' - needs + and country code, e.g. +15551234567")
    line("public URL", settings.public_base_url or "MISSING - set your ngrok domain")
    if settings.public_base_url:
        try:
            r = httpx.get(settings.public_base_url + "/", timeout=10,
                          headers={"ngrok-skip-browser-warning": "1"})
            reachable = r.status_code == 200 and "jarvis-hud" in r.text
            line("reachable by Twilio", "yes" if reachable
                 else f"NO (HTTP {r.status_code}) - is Huxley running with the tunnel?")
        except httpx.HTTPError as exc:
            line("reachable by Twilio", f"NO ({type(exc).__name__}) - start Huxley first, then rerun")


def main() -> None:
    print("Huxley connection checkup (safe to share)")
    section("System")
    line("python", sys.version.split()[0])
    line("os", f"{platform.system()} {platform.release()}")
    line("anthropic SDK", anthropic.__version__)
    line("model", settings.model)
    line("effort", settings.effort)
    line(".env found", (ROOT / ".env").exists())

    section("Environment settings that change where requests go")
    for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE",
                "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(var)
        if val is None:
            line(var, "not set")
        elif var in ("ANTHROPIC_BASE_URL",) or "proxy" in var.lower():
            line(var, f"SET -> {val.split('@')[-1]}")  # drop any user:pass@ part
        else:
            line(var, "SET (value hidden)")

    key_ok = check_key()
    line("workspace id", settings.workspace_id or "not set (fine if the key is scoped to a workspace)")

    check_telegram()
    check_phone()

    client = anthropic.Anthropic(default_headers=claude_headers())
    section("Step 1: can we reach the API and see the model?")
    try:
        m = client.models.retrieve(settings.model)
        line("result", f"OK - {m.id}")
    except Exception as exc:
        describe_error(exc)

    section("Step 2: simplest possible message")
    try:
        r = client.messages.create(model=settings.model, max_tokens=64,
                                   messages=[{"role": "user", "content": "Reply with: ok"}])
        line("result", f"OK - stop_reason={r.stop_reason}")
    except Exception as exc:
        describe_error(exc)

    section("Step 3: a message shaped exactly like Huxley sends")
    from .brain import brain  # imported late so steps 1-2 run even if this import fails
    try:
        r = asyncio.run(brain._create([{"role": "user", "content": "[via hud | test] Reply with: ok"}]))
        line("result", f"OK - stop_reason={r.stop_reason}")
    except Exception as exc:
        describe_error(exc)

    section("Step 4: streamed reply (how Huxley talks now)")
    try:
        pieces: list[str] = []
        r = asyncio.run(brain._stream(
            [{"role": "user", "content": "[via hud | test] Say: one, two, three."}],
            lambda ev: pieces.append(ev.get("text", "")) if ev["type"] == "partial" else None))
        line("result", f"OK - {len(pieces)} pieces streamed, stop_reason={r.stop_reason}")
    except Exception as exc:
        describe_error(exc)

    section("How to read this")
    print("  Step 1 fails      -> network, proxy, base URL or key problem (see the sections above)")
    print("  Only step 3 or 4 fails -> a setting in Huxley's own request; send this report to Claude")
    print("  All OK            -> restart Huxley; it should work now")
    print("  'anthropic-workspace-id' in an error -> your key isn't scoped to a workspace. Either")
    print("     create a new key scoped to a workspace (Console > API keys > Create key), or copy the")
    print("     workspace ID (Console > Workspaces, starts with wrkspc_) into python -m jarvis.configure")
    if not key_ok:
        print("  Your key looks malformed: run python -m jarvis.configure and paste it again.")


if __name__ == "__main__":
    main()
