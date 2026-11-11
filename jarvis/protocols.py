"""Protocols: named routines like "work mode" or "movie night".

A protocol is a short list of steps built only from Huxley's existing, narrow
actions, so a protocol can never do more than Huxley could already do one step
at a time. Steps run directly, without a Claude call per step.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .config import DATA_DIR

PROTOCOLS_FILE = DATA_DIR / "protocols.json"

# action -> what "value" means
ACTIONS = {
    "open_website": "a full https:// URL",
    "launch_app": "an app name from config/apps.json",
    "media": "play_pause, next, previous or mute",
    "volume": "a number 0-100",
    "show_list": "a list name, e.g. to-do",
    "weather": "a city, or empty for home",
    "wait": "seconds to pause, up to 30",
    "say": "a sentence Huxley says when the protocol runs",
}


def _load() -> dict[str, list[dict[str, str]]]:
    try:
        return json.loads(PROTOCOLS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PROTOCOLS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _key(name: str) -> str:
    name = name.strip().lower()
    return name.removesuffix(" protocol").strip()


async def save_protocol(name: str, steps: list[dict[str, Any]]) -> str:
    key = _key(name)
    if not key:
        return "A protocol needs a name."
    if not steps:
        return "A protocol needs at least one step."
    if len(steps) > 15:
        return "Keep protocols to 15 steps or fewer."
    clean = []
    for i, step in enumerate(steps, 1):
        action, value = str(step.get("action", "")), str(step.get("value", ""))
        if action not in ACTIONS:
            return f"Step {i}: unknown action '{action}'. Allowed: {', '.join(ACTIONS)}."
        clean.append({"action": action, "value": value})
    data = _load()
    existed = key in data
    data[key] = clean
    _save(data)
    return f"{'Updated' if existed else 'Saved'} the '{key}' protocol with {len(clean)} steps."


async def list_protocols() -> str:
    data = _load()
    if not data:
        return "No protocols yet."
    return "\n".join(
        f"{name}: " + "; ".join(f"{s['action']}({s['value']})" if s["value"] else s["action"] for s in steps)
        for name, steps in data.items())


async def delete_protocol(name: str) -> str:
    data = _load()
    if data.pop(_key(name), None) is None:
        return f"No protocol called '{_key(name)}'."
    _save(data)
    return "Deleted."


async def run_protocol(name: str) -> str:
    from . import events, media, reminders, tools, weather  # late: avoid import cycles

    data = _load()
    key = _key(name)
    steps = data.get(key)
    if steps is None:
        known = ", ".join(data) or "none yet"
        return f"No protocol called '{key}'. Known protocols: {known}."
    events.publish({"type": "activity", "label": "PROTOCOL", "text": key})
    results = []
    for step in steps:
        action, value = step["action"], step["value"]
        try:
            if action == "open_website":
                out = await tools.open_website(value)
            elif action == "launch_app":
                out = await tools.launch_app(value)
            elif action == "media":
                out = await media.media_control(value)
            elif action == "volume":
                out = await media.set_volume(int(float(value or 0)))
            elif action == "show_list":
                out = f"{value or 'to-do'} list:\n" + await reminders.show_list(value or "to-do")
            elif action == "weather":
                out = "weather: " + await weather.get_weather(value)
            elif action == "wait":
                await asyncio.sleep(max(0.0, min(30.0, float(value or 1))))
                out = f"waited {value}s"
            else:  # say
                out = f"say: {value}"
        except Exception as exc:  # one failed step shouldn't stop the rest
            out = f"{action} failed: {type(exc).__name__}: {exc}"
        results.append(out)
    return f"Ran the '{key}' protocol:\n" + "\n".join(f"- {r}" for r in results)
