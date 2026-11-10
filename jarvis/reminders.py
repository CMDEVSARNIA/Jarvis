"""Reminders, timers and lists, stored in data/ so they survive restarts.

Reminders fire without involving Claude (no cost): they're spoken on the HUD and
sent to Telegram. If Jarvis was off when one was due, it's delivered on startup,
marked as late.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from . import events
from .config import DATA_DIR, local_now

log = logging.getLogger("jarvis.reminders")
REMINDERS_FILE = DATA_DIR / "reminders.json"
LISTS_FILE = DATA_DIR / "lists.json"
REPEATS = ("none", "daily", "weekdays", "weekly")


# ------------------------------------------------------------------ storage --

def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _save(path, data) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic, so a crash can't leave a half-written file


def _fmt(when: datetime) -> str:
    today = local_now().date()
    day = ("today" if when.date() == today else
           "tomorrow" if when.date() == today + timedelta(days=1) else when.strftime("%a %d %b"))
    return f"{day} at {when.strftime('%H:%M')}"


# ---------------------------------------------------------------- reminders --

def _next_after(due: datetime, repeat: str, now: datetime) -> datetime | None:
    if repeat == "none":
        return None
    step = timedelta(weeks=1) if repeat == "weekly" else timedelta(days=1)
    nxt = due + step
    while nxt <= now or (repeat == "weekdays" and nxt.weekday() >= 5):
        nxt += timedelta(days=1) if repeat == "weekdays" else step
    return nxt


async def set_reminder(text: str, when: str, repeat: str) -> str:
    try:
        due = datetime.fromisoformat(when.strip()).replace(tzinfo=None, second=0, microsecond=0)
    except ValueError:
        return "Invalid time. Use local time in ISO format, e.g. 2026-11-10T09:00."
    if repeat not in REPEATS:
        repeat = "none"
    if due <= local_now() and repeat == "none":
        return f"That time ({due:%Y-%m-%d %H:%M}) is in the past. Ask the owner to clarify."
    items = _load(REMINDERS_FILE, [])
    item = {"id": uuid.uuid4().hex[:6], "text": text.strip(), "due": due.isoformat(), "repeat": repeat}
    items.append(item)
    _save(REMINDERS_FILE, items)
    events.publish({"type": "activity", "label": "REMINDER", "text": f"{item['text']} - {_fmt(due)}"})
    extra = "" if repeat == "none" else f", repeating {repeat}"
    return f"Reminder {item['id']} set for {_fmt(due)}{extra}: {item['text']}"


async def set_timer(minutes: float, label: str) -> str:
    if not 0 < minutes <= 24 * 60:
        return "Timers can be between a few seconds and 24 hours."
    due = local_now() + timedelta(minutes=minutes)
    items = _load(REMINDERS_FILE, [])
    item = {"id": uuid.uuid4().hex[:6], "text": label.strip() or "Timer done",
            "due": due.replace(microsecond=0).isoformat(), "repeat": "none", "timer": True}
    items.append(item)
    _save(REMINDERS_FILE, items)
    return f"Timer {item['id']} set for {minutes:g} minutes (until {due:%H:%M:%S})."


async def list_reminders() -> str:
    items = sorted(_load(REMINDERS_FILE, []), key=lambda i: i["due"])
    if not items:
        return "No reminders or timers set."
    return "\n".join(
        f"{i['id']}: {_fmt(datetime.fromisoformat(i['due']))} - {i['text']}"
        + ("" if i.get("repeat", "none") == "none" else f" (repeats {i['repeat']})")
        for i in items)


async def cancel_reminder(reminder_id: str) -> str:
    items = _load(REMINDERS_FILE, [])
    keep = [i for i in items if i["id"] != reminder_id.strip()]
    if len(keep) == len(items):
        return f"No reminder with id {reminder_id}. Use list_reminders to see ids."
    _save(REMINDERS_FILE, keep)
    return "Cancelled."


async def _deliver(item: dict[str, Any], late_by: timedelta) -> None:
    from . import telegram_bot  # late import: avoids a cycle at startup

    prefix = "Timer" if item.get("timer") else "Reminder"
    late = ""
    if late_by > timedelta(minutes=2):
        late = f" (was due {_fmt(datetime.fromisoformat(item['due']))}; I was offline)"
    text = f"{prefix}: {item['text']}{late}"
    log.info("Delivering %s %s", prefix.lower(), item["id"])
    events.publish({"type": "reminder", "text": text})
    try:
        await telegram_bot.send_to_owner(text)
    except Exception as exc:  # never let one failed send stop the scheduler
        log.warning("Couldn't send reminder to Telegram: %s", type(exc).__name__)


async def run_scheduler() -> None:
    """Check every 10 seconds for reminders that are due."""
    while True:
        try:
            now = local_now()
            items = _load(REMINDERS_FILE, [])
            due = [i for i in items if datetime.fromisoformat(i["due"]) <= now]
            if due:
                for item in due:
                    await _deliver(item, now - datetime.fromisoformat(item["due"]))
                remaining = [i for i in items if i not in due]
                for item in due:
                    nxt = _next_after(datetime.fromisoformat(item["due"]), item.get("repeat", "none"), now)
                    if nxt:
                        remaining.append({**item, "due": nxt.isoformat()})
                _save(REMINDERS_FILE, remaining)
        except Exception:
            log.exception("Reminder check failed")
        await asyncio.sleep(10)


def upcoming(limit: int = 3, before: datetime | None = None) -> list[str]:
    """Next reminders as short strings, for the briefing and the HUD panel."""
    items = sorted(_load(REMINDERS_FILE, []), key=lambda i: i["due"])
    out = []
    for i in items:
        due = datetime.fromisoformat(i["due"])
        if before and due > before:
            break
        out.append(f"{_fmt(due)} - {i['text']}")
    return out[:limit]


def all_lists() -> dict[str, list[str]]:
    return _load(LISTS_FILE, {})


# -------------------------------------------------------------------- lists --

async def add_to_list(list_name: str, item: str) -> str:
    lists = _load(LISTS_FILE, {})
    name = list_name.strip().lower() or "to-do"
    lists.setdefault(name, []).append(item.strip())
    _save(LISTS_FILE, lists)
    return f"Added to {name} ({len(lists[name])} items)."


async def show_list(list_name: str) -> str:
    lists = _load(LISTS_FILE, {})
    name = list_name.strip().lower()
    if not name:
        return ("Lists: " + ", ".join(f"{k} ({len(v)})" for k, v in lists.items())) if lists else "No lists yet."
    items = lists.get(name, [])
    if not items:
        return f"The {name} list is empty."
    return "\n".join(f"{n}. {text}" for n, text in enumerate(items, 1))


async def remove_from_list(list_name: str, item: str) -> str:
    """Remove by number ('2'), by text, or 'all' to clear the list."""
    lists = _load(LISTS_FILE, {})
    name = list_name.strip().lower()
    items = lists.get(name, [])
    target = item.strip()
    if target.lower() == "all":
        lists[name] = []
        removed = f"all {len(items)} items"
    elif target.isdigit() and 1 <= int(target) <= len(items):
        removed = items.pop(int(target) - 1)
    else:
        match = next((i for i in items if i.lower() == target.lower()), None) or next(
            (i for i in items if target.lower() in i.lower()), None)
        if match is None:
            return f"'{target}' isn't on the {name} list."
        items.remove(match)
        removed = match
    _save(LISTS_FILE, lists)
    return f"Removed {removed} from {name}."
