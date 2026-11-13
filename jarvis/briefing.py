"""Greeting, daily briefing and the live data behind the HUD's side panels.

- When the HUD first opens after Huxley starts: the day's briefing if it hasn't
  been given yet today (from 4 AM), otherwise a short welcome (no Claude call).
- At BRIEFING_TIME (if set): the briefing, spoken on the PC and sent to Telegram.
  If Huxley wasn't running then, the HUD greeting covers it instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from . import calendar_feed, google_auth, google_tools, memory, reminders, traffic, weather
from .config import DATA_DIR, local_now, settings

log = logging.getLogger("jarvis.briefing")
STATE_FILE = DATA_DIR / "state.json"

_lock = asyncio.Lock()
_greeted = False
dashboard: dict = {"weather": "", "upcoming": [], "todo": [], "today": [], "memory": [], "rain_hours": [],
                   "bridge": ""}


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _mark_briefed(day: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({**_state(), "last_briefing": day}), encoding="utf-8")


def _part_of_day(now: datetime) -> str:
    return "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"


async def _gather() -> dict:
    now = local_now()
    data: dict = {"date": now.strftime("%A %d %B %Y"), "time": now.strftime("%H:%M")}
    try:
        data["weather"] = json.loads(await weather._get_weather(""))
    except Exception as exc:
        data["weather"] = f"unavailable ({type(exc).__name__})"
    data["reminders_today"] = reminders.upcoming(limit=10, before=now.replace(hour=23, minute=59))
    data["calendar_today"] = await calendar_feed.today_summary()
    lists = reminders.all_lists()
    data["to_do"] = lists.get("to-do") or lists.get("todo") or []
    data["other_lists"] = {k: len(v) for k, v in lists.items() if k not in ("to-do", "todo") and v}
    if settings.border_crossing:
        try:
            data["border_crossing"] = await traffic.border_wait("")
        except Exception as exc:
            data["border_crossing"] = f"unavailable ({type(exc).__name__})"
    if settings.commute_to and settings.tomtom_key:
        data["commute"] = await traffic.drive_time("", "")
    if google_auth.connected() and google_auth.has("gmail_read"):
        # Senders and subjects only; the owner can ask for more.
        data["unread_email_last_day"] = await google_tools.check_email("is:unread in:inbox newer_than:1d", 8)
    return data


async def give_briefing(send_telegram: bool) -> str:
    """Compose today's briefing with Claude and deliver it."""
    from . import telegram_bot
    from .brain import brain

    async with _lock:
        today = local_now().date().isoformat()
        if _state().get("last_briefing") == today:
            return ""
        _mark_briefed(today)  # mark first so two triggers can't both run
    data = await _gather()
    prompt = (f"Give me my {_part_of_day(local_now())} briefing. Today's data (JSON): "
              f"{json.dumps(data)}")
    text = await brain.ask(prompt, channel="briefing")
    if send_telegram:
        try:
            await telegram_bot.send_to_owner(text)
        except Exception as exc:
            log.warning("Couldn't send briefing to Telegram: %s", type(exc).__name__)
    return text


async def greet() -> None:
    """Called when the HUD connects for the first time since Huxley started."""
    from . import events

    global _greeted
    if _greeted:
        return
    _greeted = True
    await asyncio.sleep(1.5)  # let the page finish loading voices
    now = local_now()
    if now.hour >= 4 and _state().get("last_briefing") != now.date().isoformat():
        await give_briefing(send_telegram=False)
        return
    events.publish({"type": "reply", "channel": "briefing",
                    "text": f"Welcome back, {settings.owner_name}. All systems are online."})


def _briefing_due(now: datetime) -> bool:
    if not settings.briefing_time:
        return False
    try:
        hour, minute = (int(x) for x in settings.briefing_time.split(":"))
    except ValueError:
        return False
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Only within an hour of the set time; later starts get the HUD greeting instead.
    return at <= now < at + timedelta(hours=1)


async def run() -> None:
    """Background loop: scheduled briefing, and refreshing the HUD panels."""
    last_weather = last_bridge = datetime.min
    while True:
        now = local_now()
        try:
            if _briefing_due(now) and _state().get("last_briefing") != now.date().isoformat():
                await give_briefing(send_telegram=True)
            if now - last_weather > timedelta(minutes=20) and settings.home_location:
                dashboard["weather"] = await weather.current_summary()
                dashboard["rain_hours"] = await weather.hourly_outlook(8)
                last_weather = now
            if now - last_bridge > timedelta(minutes=10) and settings.border_crossing:
                dashboard["bridge"] = await traffic.bridge_summary()
                last_bridge = now
            dashboard["upcoming"] = reminders.upcoming(limit=3)
            lists = reminders.all_lists()
            dashboard["todo"] = (lists.get("to-do") or lists.get("todo") or [])[:5]
            dashboard["today"] = (await calendar_feed.today_summary())[:5]
            dashboard["memory"] = memory.load()
        except Exception:
            log.exception("Briefing loop error")
        await asyncio.sleep(30)
