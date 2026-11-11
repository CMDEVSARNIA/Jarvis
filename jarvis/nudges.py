"""Proactive nudges: Jarvis speaks first.

- 10 minutes before a calendar event: a heads-up.
- Once a day, if rain or snow looks likely in the next few hours: a warning.
- At RECAP_TIME: an evening recap (tomorrow's calendar, reminders, open to-dos).

Nudges are spoken on the HUD and sent to Telegram, only between 07:00 and 22:00
(reminders you set yourself still fire any time). NUDGES=false turns them off.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from . import calendar_feed, events, reminders, weather
from .config import DATA_DIR, local_now, settings

log = logging.getLogger("jarvis.nudges")
STATE_FILE = DATA_DIR / "nudges.json"
QUIET_START, QUIET_END = 22, 7


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _quiet(now: datetime) -> bool:
    return now.hour >= QUIET_START or now.hour < QUIET_END


async def deliver(text: str) -> None:
    from . import telegram_bot

    events.publish({"type": "reminder", "text": text})
    if events.listeners() == 0:
        from . import desktop
        desktop.notify("Jarvis", text)
    try:
        await telegram_bot.send_to_owner(text)
    except Exception as exc:
        log.warning("Couldn't send nudge to Telegram: %s", type(exc).__name__)


async def _calendar_heads_up(state: dict) -> None:
    told = set(state.get("told_events", []))
    for ev in await calendar_feed.starting_soon(10):
        if ev["uid"] in told:
            continue
        mins = max(1, round((ev["start"] - local_now()).total_seconds() / 60))
        where = f" at {ev['location']}" if ev["location"] else ""
        await deliver(f"Heads up: {ev['title']}{where} starts in {mins} minutes.")
        told.add(ev["uid"])
    state["told_events"] = sorted(told)[-200:]


async def _rain_warning(state: dict, now: datetime) -> None:
    today = now.date().isoformat()
    if state.get("rain_day") == today or not settings.home_location:
        return
    if state.get("rain_checked_at", "") > (now - timedelta(minutes=30)).isoformat():
        return
    state["rain_checked_at"] = now.isoformat()
    hour, chance, kind = await weather.precipitation_soon(hours=4)
    if hour is not None and chance >= 60:
        await deliver(f"{kind.capitalize()} is likely around {hour:%H:%M} ({chance}% chance). "
                      "Worth taking an umbrella if you head out.")
        state["rain_day"] = today


async def _evening_recap(state: dict, now: datetime) -> None:
    if not settings.recap_time:
        return
    try:
        h, m = (int(x) for x in settings.recap_time.split(":"))
    except ValueError:
        return
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    today = now.date().isoformat()
    if not (at <= now < at + timedelta(hours=1)) or state.get("recap_day") == today:
        return
    state["recap_day"] = today
    _save(state)  # mark first so a slow Claude call can't trigger it twice
    from . import telegram_bot
    from .brain import brain

    tomorrow = (now + timedelta(days=1)).date().isoformat()
    data = {
        "tomorrow_calendar": await calendar_feed.get_calendar(tomorrow, 1) if calendar_feed.configured() else "",
        "upcoming_reminders": reminders.upcoming(limit=6),
        "open_to_dos": (reminders.all_lists().get("to-do") or [])[:8],
    }
    text = await brain.ask("Give me my evening recap: what's coming tomorrow and anything still "
                           f"open. Data (JSON): {json.dumps(data)}", channel="briefing")
    try:
        await telegram_bot.send_to_owner(text)
    except Exception as exc:
        log.warning("Couldn't send recap to Telegram: %s", type(exc).__name__)


async def run() -> None:
    while True:
        await asyncio.sleep(60)
        if not settings.nudges:
            continue
        now = local_now()
        state = _state()
        try:
            if not _quiet(now):
                await _calendar_heads_up(state)
                await _rain_warning(state, now)
            await _evening_recap(state, now)
        except Exception:
            log.exception("Nudge check failed")
        _save(state)
