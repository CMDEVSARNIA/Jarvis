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
    """Apps Jarvis may launch: name -> command/path. Edit config/apps.json."""
    path = ROOT / "config" / "apps.json"
    if not path.exists():
        return {}
    return {k.lower(): v for k, v in json.loads(path.read_text()).items()}


@dataclass(frozen=True)
class Settings:
    model: str = _env("JARVIS_MODEL", "claude-opus-5-5")
    effort: str = _env("JARVIS_EFFORT", "low")
    owner_name: str = _env("OWNER_NAME", "sir")
    # Needed only for a personal/service-account key that isn't scoped to one workspace.
    workspace_id: str = _env("ANTHROPIC_WORKSPACE_ID")

    host: str = _env("HOST", "127.0.0.1")
    port: int = int(_env("PORT", "8000"))
    hud_token: str = field(default_factory=_load_or_create_token)

    telegram_token: str = _env("TELEGRAM_BOT_TOKEN")
    telegram_owner_chat_id: str = _env("TELEGRAM_OWNER_CHAT_ID")

    twilio_sid: str = _env("TWILIO_ACCOUNT_SID")
    twilio_token: str = _env("TWILIO_AUTH_TOKEN")
    twilio_from: str = _env("TWILIO_FROM_NUMBER")
    owner_phone: str = _env("OWNER_PHONE_NUMBER")
    public_base_url: str = _env("PUBLIC_BASE_URL").rstrip("/")
    twilio_voice: str = _env("TWILIO_VOICE", "Polly.Brian")
    # Caller ID can be spoofed, so calls INTO Jarvis are off unless you opt in.
    allow_inbound_calls: bool = _env("ALLOW_INBOUND_CALLS", "false").lower() == "true"

    apps: dict[str, str] = field(default_factory=_load_apps)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token)

    @property
    def phone_enabled(self) -> bool:
        return all(
            [self.twilio_sid, self.twilio_token, self.twilio_from, self.owner_phone, self.public_base_url]
        )


settings = Settings()


def valid_anthropic_key(value: str) -> bool:
    return value.startswith("sk-ant-") and value.isascii() and value.isprintable() \
        and " " not in value and len(value) > 30


def valid_telegram_token(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", value))


def claude_headers() -> dict[str, str] | None:
    """Extra headers for every Claude API request."""
    return {"anthropic-workspace-id": settings.workspace_id} if settings.workspace_id else None
