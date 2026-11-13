"""Settings loaded from .env (see .env.example)."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"

# .env is the source of truth: it beats any stale ANTHROPIC_API_KEY etc. set in
# the system environment (e.g. a Windows user variable from an earlier attempt).
load_dotenv(ROOT / ".env", override=True)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _load_or_create_token() -> str:
    """A per-install secret the HUD must present. Protects the PC-control
    channel if the server is ever reachable from outside (e.g. via a tunnel)."""
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / "hud_token"
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(24)
    path.write_text(token)
    return token


def _load_apps() -> dict[str, str]:
    """Apps Huxley may launch: name -> command/path. Edit config/apps.json."""
    path = ROOT / "config" / "apps.json"
    if not path.exists():
        return {}
    return {k.lower(): v for k, v in json.loads(path.read_text()).items()}


# The assistant's name is fixed: H.U.X.L.E.Y. ("Highly Useful eXecutive Logic Engine, Yours").
# (The code folder and the GitHub repository keep the old internal name "jarvis".)
ASSISTANT_NAME = "Huxley"
DISPLAY_NAME = "H.U.X.L.E.Y."


@dataclass(frozen=True)
class Settings:
    model: str = _env("JARVIS_MODEL", "claude-opus-5-5")
    effort: str = _env("JARVIS_EFFORT", "low")
    owner_name: str = _env("OWNER_NAME", "sir")
    hud_theme: str = _env("HUD_THEME", "phosphor").lower()    # phosphor | classic
    home_location: str = _env("HOME_LOCATION")          # e.g. "Toronto, Canada"
    units: str = _env("UNITS", "metric").lower()        # metric | imperial
    timezone: str = _env("JARVIS_TIMEZONE")
    briefing_time: str = _env("BRIEFING_TIME", "08:00")  # HH:MM daily; blank = only on startup
    recap_time: str = _env("RECAP_TIME", "21:00")        # evening recap; blank = off
    nudges: bool = _env("NUDGES", "true").lower() != "false"
    talk_hotkey: str = _env("TALK_HOTKEY", "ctrl+alt+space")  # blank = off
    calendar_url: str = _env("CALENDAR_ICS_URL")         # private iCal link (a secret)             # e.g. America/Toronto; blank = this computer's
    # Traffic: border waits need nothing; drive times need a free TomTom key.
    border_crossing: str = _env("BORDER_CROSSING")      # e.g. Blue Water Bridge; blank = off
    commute_to: str = _env("COMMUTE_TO")                # usual destination, e.g. "Port Huron, MI"
    tomtom_key: str = _env("TOMTOM_API_KEY")
    # Needed only for a personal/service-account key that isn't scoped to one workspace.
    workspace_id: str = _env("ANTHROPIC_WORKSPACE_ID")

    host: str = _env("HOST", "127.0.0.1")
    port: int = int(_env("PORT", "8000"))
    hud_token: str = field(default_factory=_load_or_create_token)

    telegram_token: str = _env("TELEGRAM_BOT_TOKEN")
    telegram_owner_chat_id: str = field(default_factory=lambda: clean_chat_id(_env("TELEGRAM_OWNER_CHAT_ID")))

    twilio_sid: str = _env("TWILIO_ACCOUNT_SID")
    twilio_token: str = _env("TWILIO_AUTH_TOKEN")
    twilio_from: str = _env("TWILIO_FROM_NUMBER")
    owner_phone: str = _env("OWNER_PHONE_NUMBER")
    # Your free static ngrok domain; Huxley starts the tunnel itself on a PC.
    ngrok_domain: str = field(default_factory=lambda: _clean_domain(_env("NGROK_DOMAIN")))
    public_base_url: str = field(default_factory=lambda: (
        _env("PUBLIC_BASE_URL").rstrip("/")
        or (f"https://{_clean_domain(_env('NGROK_DOMAIN'))}" if _env("NGROK_DOMAIN") else "")))
    twilio_voice: str = _env("TWILIO_VOICE", "Polly.Brian")
    # Caller ID can be spoofed, so calls INTO Huxley are off unless you opt in.
    allow_inbound_calls: bool = _env("ALLOW_INBOUND_CALLS", "false").lower() == "true"

    apps: dict[str, str] = field(default_factory=_load_apps)

    @property
    def assistant_name(self) -> str:
        return ASSISTANT_NAME

    @property
    def display_name(self) -> str:
        return DISPLAY_NAME

    @property
    def phone_port(self) -> int:
        """Where `tailscale serve` hands phone requests to Huxley (127.0.0.1 only).
        A separate port, so the server can tell your phone apart from a public
        tunnel (ngrok) that forwards to the main port. PHONE_PORT=0 turns it off."""
        value = _env("PHONE_PORT", str(self.port + 1))
        return int(value) if value.isdigit() else 0

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token)

    @property
    def phone_enabled(self) -> bool:
        return all(
            [self.twilio_sid, self.twilio_token, self.twilio_from, self.owner_phone, self.public_base_url]
        )




def _clean_domain(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.rstrip("/")


def valid_twilio_sid(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"AC[0-9a-fA-F]{32}", value))


def valid_twilio_token(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", value))


def clean_chat_id(value: str) -> str:
    """Pull the numeric Telegram chat id out of whatever was pasted, e.g.
    'TELEGRAM_OWNER_CHAT_ID=9229556595.' -> '9229556595'."""
    import re
    joined = re.sub(r"(?<=\d)\s+(?=\d)", "", value or "")  # "922 955 6595" -> digits
    match = re.search(r"-?\d{5,}", joined)
    return match.group(0) if match else ""


def valid_anthropic_key(value: str) -> bool:
    return value.startswith("sk-ant-") and value.isascii() and value.isprintable() \
        and " " not in value and len(value) > 30


def valid_telegram_token(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", value))


def local_now():
    """The owner's local time (naive datetime). Uses JARVIS_TIMEZONE when set, which
    matters on a cloud server whose clock runs in UTC."""
    from datetime import datetime
    if settings.timezone:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    return datetime.now()


def claude_headers() -> dict[str, str] | None:
    """Extra headers for every Claude API request."""
    return {"anthropic-workspace-id": settings.workspace_id} if settings.workspace_id else None


settings = Settings()
