"""Tools Jarvis can use. Deliberately narrow: no arbitrary shell access.
Add your own by appending a schema to TOOLS and a handler to HANDLERS."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import webbrowser
from datetime import datetime
from typing import Any, Awaitable, Callable

import psutil

from .config import DATA_DIR, settings

MEMORY_FILE = DATA_DIR / "memory.json"


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


TOOLS: list[dict[str, Any]] = [
    # Server-side tool: runs on Anthropic's side, no handler needed here.
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
    {
        "name": "system_status",
        "description": "Report this PC's CPU, memory, disk and battery status.",
        "input_schema": _schema({}),
        "strict": True,
    },
    {
        "name": "open_website",
        "description": "Open a URL in the default browser on the owner's PC.",
        "input_schema": _schema({"url": {"type": "string", "description": "Full http(s) URL"}}),
        "strict": True,
    },
    {
        "name": "launch_app",
        "description": (
            "Launch an application on the owner's PC. Only names from the allowlist work; "
            "call with name='list' to see them."
        ),
        "input_schema": _schema({"name": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "remember",
        "description": (
            "Save a durable fact about the owner (preferences, people, routines) so it is "
            "available in future conversations. Use sparingly, for things worth keeping."
        ),
        "input_schema": _schema({"fact": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "message_owner",
        "description": "Send the owner a text message on their phone (Telegram).",
        "input_schema": _schema({"text": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "call_owner",
        "description": (
            "Phone the owner's cell and start a voice conversation. Only use when the owner "
            "asks to be called, or something is genuinely urgent. 'reason' is spoken first."
        ),
        "input_schema": _schema({"reason": {"type": "string"}}),
        "strict": True,
    },
]


# ---------------------------------------------------------------- handlers --

async def system_status() -> str:
    def collect() -> dict[str, Any]:
        disk_root = os.path.abspath(os.sep)
        info: dict[str, Any] = {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage(disk_root).percent,
            "uptime_hours": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1),
        }
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if battery:
            info["battery_percent"] = battery.percent
            info["plugged_in"] = battery.power_plugged
        return info

    return json.dumps(await asyncio.to_thread(collect))


async def open_website(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "Refused: only http(s) URLs can be opened."
    await asyncio.to_thread(webbrowser.open, url)
    return f"Opened {url}"


async def launch_app(name: str) -> str:
    apps = settings.apps
    if name.lower() == "list" or name.lower() not in apps:
        known = ", ".join(sorted(apps)) or "(none configured - edit config/apps.json)"
        prefix = "" if name.lower() == "list" else f"'{name}' is not in the allowlist. "
        return f"{prefix}Allowed apps: {known}"
    target = apps[name.lower()]
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", target])
    else:
        subprocess.Popen([target])
    return f"Launched {name}"


def load_memory() -> list[str]:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return []


async def remember(fact: str) -> str:
    facts = load_memory()
    facts.append(fact)
    MEMORY_FILE.write_text(json.dumps(facts, indent=2))
    return "Saved."


async def message_owner(text: str) -> str:
    from . import telegram_bot

    return await telegram_bot.send_to_owner(text)


async def call_owner(reason: str) -> str:
    from . import phone

    return await phone.call_owner(reason)


HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "system_status": system_status,
    "open_website": open_website,
    "launch_app": launch_app,
    "remember": remember,
    "message_owner": message_owner,
    "call_owner": call_owner,
}


async def run_tool(name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Returns (result_text, is_error)."""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool {name}", True
    try:
        return await handler(**args), False
    except Exception as exc:  # report failures to Claude instead of crashing
        return f"{type(exc).__name__}: {exc}", True
