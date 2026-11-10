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

from .config import ROOT, settings

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
    if not key.startswith("sk-ant-api"):
        problems.append(f"starts with '{key[:10]}', expected 'sk-ant-api'")
    if any(c.isspace() for c in key):
        problems.append("contains spaces or line breaks")
    if not key.isascii():
        problems.append("contains non-standard characters (bad paste?)")
    if key.startswith(('"', "'")) or key.endswith(('"', "'")):
        problems.append("wrapped in quotes")
    line("length", len(key))
    line("ends with", "..." + key[-4:])
    line("looks valid", "yes" if not problems else "NO: " + "; ".join(problems))
    return not problems


def main() -> None:
    print("Jarvis connection checkup (safe to share)")
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

    client = anthropic.Anthropic()
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

    section("Step 3: a message shaped exactly like Jarvis sends")
    from .brain import brain  # imported late so steps 1-2 run even if this import fails
    try:
        r = asyncio.run(brain._create([{"role": "user", "content": "[via hud | test] Reply with: ok"}]))
        line("result", f"OK - stop_reason={r.stop_reason}")
    except Exception as exc:
        describe_error(exc)

    section("How to read this")
    print("  Step 1 fails      -> network, proxy, base URL or key problem (see the sections above)")
    print("  Only step 3 fails -> a setting in Jarvis's own request; send this report to Claude")
    print("  All OK            -> restart Jarvis; it should work now")
    if not key_ok:
        print("  Your key looks malformed: run python -m jarvis.configure and paste it again.")


if __name__ == "__main__":
    main()
