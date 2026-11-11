"""Calendar via your calendar's private iCal ("secret address") link, read-only, with
no account linking. Works with Google Calendar, Outlook and Apple iCloud.

Adding an event opens a pre-filled event in your calendar for you to Save, so
Jarvis can never change your calendar without you.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

import httpx

from .config import local_now, settings

log = logging.getLogger("jarvis.calendar")
_cache: dict = {"at": 0.0, "data": b""}
CACHE_SECONDS = 600


def configured() -> bool:
    return bool(settings.calendar_url)


def provider() -> str:
    url = settings.calendar_url.lower()
    if "outlook" in url or "office365" in url or "live.com" in url:
        return "outlook"
    if "icloud" in url:
        return "apple"
    return "google"


async def _fetch() -> bytes:
    if time.time() - _cache["at"] < CACHE_SECONDS and _cache["data"]:
        return _cache["data"]
    url = settings.calendar_url.replace("webcal://", "https://", 1)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
    _cache.update(at=time.time(), data=r.content)
    return r.content


def _to_local(value) -> datetime:
    """iCal times -> naive local datetimes (all-day dates become midnight)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        if settings.timezone:
            from zoneinfo import ZoneInfo
            return value.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None)
        return value.astimezone().replace(tzinfo=None)
    return datetime.combine(value, datetime.min.time())


def _parse(data: bytes, start: datetime, end: datetime) -> list[dict]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev.get("DTSTART").dt
        dtend = ev.get("DTEND").dt if ev.get("DTEND") else dtstart
        all_day = not isinstance(dtstart, datetime)
        out.append({
            "uid": str(ev.get("UID", "")) + "@" + str(dtstart),
            "title": str(ev.get("SUMMARY", "(no title)")),
            "start": _to_local(dtstart),
            "end": _to_local(dtend),
            "all_day": all_day,
            "location": str(ev.get("LOCATION", "") or ""),
        })
    out.sort(key=lambda e: e["start"])
    return out


async def events_between(start: datetime, end: datetime) -> list[dict]:
    data = await _fetch()
    return await asyncio.to_thread(_parse, data, start, end)


def describe(ev: dict) -> str:
    when = "all day" if ev["all_day"] else f"{ev['start']:%H:%M}-{ev['end']:%H:%M}"
    day = ev["start"].strftime("%a %d %b")
    loc = f" at {ev['location']}" if ev["location"] else ""
    return f"{day}, {when}: {ev['title']}{loc}"


async def get_calendar(start_date: str, days: int) -> str:
    if not configured():
        return ("No calendar connected. The owner can add their calendar's secret iCal link "
                "with the settings tool.")
    try:
        first = date.fromisoformat(start_date) if start_date.strip() else local_now().date()
    except ValueError:
        return "start_date must look like 2026-11-12, or be empty for today."
    days = max(1, min(31, int(days or 1)))
    start = datetime.combine(first, datetime.min.time())
    try:
        found = await events_between(start, start + timedelta(days=days))
    except ImportError:
        return "Calendar support needs new components; restart Jarvis to install them."
    except httpx.HTTPStatusError as exc:
        return f"The calendar link was refused (HTTP {exc.response.status_code}). It may have been reset."
    except httpx.HTTPError as exc:
        return f"Couldn't reach the calendar ({type(exc).__name__})."
    except Exception as exc:  # malformed calendar data
        log.exception("Calendar parse failed")
        return f"Couldn't read the calendar ({type(exc).__name__})."
    if not found:
        return f"Nothing on the calendar for {days} day(s) from {first:%a %d %b}."
    return "\n".join(describe(e) for e in found)


async def add_calendar_event(title: str, start: str, end: str, location: str) -> str:
    """Build a pre-filled event for the owner to Save (opens in the browser)."""
    from .tools import open_website

    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end) if end.strip() else s + timedelta(hours=1)
    except ValueError:
        return "Times must be local ISO format, e.g. 2026-11-13T15:00."
    if e <= s:
        e = s + timedelta(hours=1)
    if provider() == "outlook":
        link = "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode({
            "subject": title, "startdt": s.isoformat(), "enddt": e.isoformat(),
            "location": location, "path": "/calendar/action/compose", "rru": "addevent"})
    else:  # Google (also the fallback for Apple: opens Google's form)
        link = ("https://calendar.google.com/calendar/render?action=TEMPLATE"
                f"&text={quote(title)}&dates={s:%Y%m%dT%H%M%S}/{e:%Y%m%dT%H%M%S}"
                f"&location={quote(location)}")
    await open_website(link)
    return (f"Opened a pre-filled '{title}' event ({s:%a %d %b %H:%M}-{e:%H:%M}) in the browser. "
            "Tell the owner to check it and click Save.")


async def today_summary() -> list[str]:
    """Today's remaining events as short lines, for the briefing and the HUD."""
    if not configured():
        return []
    now = local_now()
    try:
        found = await events_between(now.replace(hour=0, minute=0, second=0, microsecond=0),
                                     now.replace(hour=23, minute=59, second=59))
    except Exception:
        return []
    return [("All day: " if e["all_day"] else f"{e['start']:%H:%M} ") + e["title"]
            for e in found if e["all_day"] or e["end"] > now]


async def starting_soon(minutes: int = 10) -> list[dict]:
    if not configured():
        return []
    now = local_now()
    try:
        found = await events_between(now, now + timedelta(minutes=minutes + 1))
    except Exception:
        return []
    return [e for e in found if not e["all_day"] and now <= e["start"] <= now + timedelta(minutes=minutes)]
