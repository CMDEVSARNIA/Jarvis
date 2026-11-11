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

import httpx
import psutil

from . import events, media, protocols, reminders, viewer, weather
from .config import DATA_DIR, settings

MEMORY_FILE = DATA_DIR / "memory.json"


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _web_tools() -> list[dict[str, Any]]:
    """Server-side web search and page reading (run on Anthropic's side, no handler
    needed). These versions are supported on Opus and Sonnet models; they're left
    off for others (e.g. Haiku) rather than risk every request being rejected."""
    if settings.model.startswith(("claude-opus", "claude-sonnet", "claude-fable")):
        return [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
            # Reads pages whose URLs are already in the conversation (pasted or found by search).
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5,
             "max_content_tokens": 20000},
        ]
    return []


TOOLS: list[dict[str, Any]] = [
    *_web_tools(),
    {
        "name": "get_weather",
        "description": "Current weather and a 3-day forecast. Empty location = the owner's home.",
        "input_schema": _schema({"location": {"type": "string",
                                              "description": "City, optionally with country, e.g. 'Paris, France'. Empty for home."}}),
        "strict": True,
    },
    {
        "name": "get_time",
        "description": "The current local time in a city. Empty location = the owner's home.",
        "input_schema": _schema({"location": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "media_control",
        "description": "Control whatever is playing (Spotify, YouTube, ...) with the media keys.",
        "input_schema": _schema({"action": {"type": "string",
                                            "enum": ["play_pause", "next", "previous", "mute"]}}),
        "strict": True,
    },
    {
        "name": "set_volume",
        "description": "Set the PC's volume, 0-100.",
        "input_schema": _schema({"level": {"type": "integer"}}),
        "strict": True,
    },
    {
        "name": "run_protocol",
        "description": ("Run a saved protocol (routine) by name, e.g. 'work mode'. When the owner "
                        "says '<name> protocol' or '<name> mode', try this first."),
        "input_schema": _schema({"name": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "save_protocol",
        "description": (
            "Create or replace a protocol: a named routine of steps that runs on one command. "
            "Read the steps back to the owner and get their OK before saving. Actions: "
            + "; ".join(f"{a} (value: {d})" for a, d in protocols.ACTIONS.items())),
        "input_schema": _schema({
            "name": {"type": "string"},
            "steps": {"type": "array", "items": _schema({
                "action": {"type": "string", "enum": list(protocols.ACTIONS)},
                "value": {"type": "string"},
            })},
        }),
        "strict": True,
    },
    {
        "name": "list_protocols",
        "description": "List saved protocols and their steps.",
        "input_schema": _schema({}),
        "strict": True,
    },
    {
        "name": "delete_protocol",
        "description": "Delete a saved protocol by name.",
        "input_schema": _schema({"name": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "set_reminder",
        "description": (
            "Remind the owner at a specific time (spoken on the PC and sent to their phone). "
            "Work out the exact local date and time from the date/time in the message tag. "
            "If the owner gave no time, ask instead of guessing."),
        "input_schema": _schema({
            "text": {"type": "string", "description": "What to remind them of, phrased as a reminder"},
            "when": {"type": "string", "description": "Local time, ISO format, e.g. 2026-11-10T09:00"},
            "repeat": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly"]},
        }),
        "strict": True,
    },
    {
        "name": "set_timer",
        "description": "Start a countdown timer. Use for 'in N minutes' requests.",
        "input_schema": _schema({"minutes": {"type": "number"}, "label": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "list_reminders",
        "description": "List upcoming reminders and timers with their ids.",
        "input_schema": _schema({}),
        "strict": True,
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a reminder or timer by id (get ids from list_reminders).",
        "input_schema": _schema({"reminder_id": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "add_to_list",
        "description": "Add an item to a named list, e.g. 'shopping' or 'to-do'.",
        "input_schema": _schema({"list_name": {"type": "string"}, "item": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "show_list",
        "description": "Show a list's items, numbered. Empty list_name shows all list names.",
        "input_schema": _schema({"list_name": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "remove_from_list",
        "description": "Remove an item from a list by its number or text, or 'all' to clear it.",
        "input_schema": _schema({"list_name": {"type": "string"}, "item": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "system_status",
        "description": "Report this PC's CPU, memory, disk and battery status.",
        "input_schema": _schema({}),
        "strict": True,
    },
    {
        "name": "show_on_screen",
        "description": (
            "Show a web page inside the Jarvis screen (live page, video/map embed, or a clean "
            "reader view). Prefer this when the owner wants to see or read a page. Login sites "
            "(email, social media) automatically open in the browser instead."),
        "input_schema": _schema({"url": {"type": "string", "description": "Full http(s) URL"}}),
        "strict": True,
    },
    {
        "name": "show_map",
        "description": "Show a map of a place or address inside the Jarvis screen.",
        "input_schema": _schema({"place": {"type": "string"}}),
        "strict": True,
    },
    {
        "name": "close_screen",
        "description": "Close the page or map currently shown on the Jarvis screen.",
        "input_schema": _schema({}),
        "strict": True,
    },
    {
        "name": "open_website",
        "description": "Open a URL in a separate browser tab on the owner's PC (only when they ask for a tab or the browser).",
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


async def show_on_screen(url: str) -> str:
    try:
        payload = await viewer.prepare(url)
    except viewer.BlockedURL as exc:
        return f"Not shown: {exc}"
    except httpx.HTTPError as exc:
        return f"Couldn't load the page ({type(exc).__name__}). It may be down or slow."
    if payload["mode"] == "external":
        await open_website(payload["url"])
        return f"Opened in the browser instead. {payload.get('note', '')}"
    events.publish({"type": "viewer", **payload})
    if payload["mode"] == "reader":
        excerpt = " ".join(b["text"] for b in payload["blocks"])[:1500]
        return f"Showing a reader view of '{payload['title']}'. Start of the text: {excerpt}"
    kind = "the live page" if payload["mode"] == "frame" else "the embedded player/map"
    return f"Showing {kind} for {payload['url']} on screen."


async def show_map(place: str) -> str:
    events.publish({"type": "viewer", "mode": "embed", "url": f"https://maps.google.com/?q={place}",
                    "embed_url": viewer.map_embed(place), "title": place})
    return f"Showing a map of {place} on screen."


async def close_screen() -> str:
    events.publish({"type": "viewer", "mode": "close"})
    return "Closed."


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


# The API accepts at most 20 "strict" tools (strict = inputs are guaranteed to match
# the schema). Strict only pays off where the input has structure: several fields,
# numbers, enums or arrays. One free-text field or no input gains nothing, and the
# handlers already turn bad input into an error message for Claude.
STRICT_LIMIT = 20


def _needs_strict(tool: dict[str, Any]) -> bool:
    props = tool.get("input_schema", {}).get("properties", {})
    if not props:
        return False
    if len(props) > 1:
        return True
    only = next(iter(props.values()))
    return only.get("type") != "string" or "enum" in only


def _apply_strict_policy(tools: list[dict[str, Any]]) -> None:
    kept = 0
    for tool in tools:
        if "strict" not in tool:
            continue  # server tools
        if _needs_strict(tool) and kept < STRICT_LIMIT:
            kept += 1
        else:
            tool.pop("strict")


_apply_strict_policy(TOOLS)


HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "get_weather": weather.get_weather,
    "show_on_screen": show_on_screen,
    "show_map": show_map,
    "close_screen": close_screen,
    "media_control": media.media_control,
    "set_volume": media.set_volume,
    "run_protocol": protocols.run_protocol,
    "save_protocol": protocols.save_protocol,
    "list_protocols": protocols.list_protocols,
    "delete_protocol": protocols.delete_protocol,
    "get_time": weather.get_time,
    "set_reminder": reminders.set_reminder,
    "set_timer": reminders.set_timer,
    "list_reminders": reminders.list_reminders,
    "cancel_reminder": reminders.cancel_reminder,
    "add_to_list": reminders.add_to_list,
    "show_list": reminders.show_list,
    "remove_from_list": reminders.remove_from_list,
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
