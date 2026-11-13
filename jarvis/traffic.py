"""Border crossing waits and drive times.

Border waits come from the two governments' free public feeds, no key needed:
  into the US:     U.S. Customs and Border Protection (bwt.cbp.gov)
  into Canada:     Canada Border Services Agency (cbsa-asfc.gc.ca)
Drive times with live traffic use TomTom's free tier (TOMTOM_API_KEY, optional).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from .config import settings

log = logging.getLogger("jarvis.traffic")
CBP_URL = "https://bwt.cbp.gov/api/bwtnew"
CBSA_URL = "https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv"
TOMTOM = "https://api.tomtom.com"
CACHE_SECONDS = 300
_cache: dict[str, tuple[float, object]] = {}

# Everyday names -> words that appear in both feeds' names for that crossing.
ALIASES = {
    "blue water": "bluewater", "bluewater": "bluewater", "sarnia": "bluewater",
    "port huron": "bluewater", "point edward": "bluewater",
    "ambassador": "ambassador", "windsor tunnel": "tunnel", "detroit windsor tunnel": "tunnel",
    "detroit-windsor tunnel": "tunnel", "tunnel": "tunnel",
    "peace bridge": "peacebridge", "rainbow": "rainbow", "lewiston": "lewiston", "queenston": "lewiston",
    "thousand islands": "thousand", "lansdowne": "thousand",
}


def _key(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _wanted(crossing: str) -> str:
    c = crossing.strip().lower() or settings.border_crossing.lower()
    for name, key in ALIASES.items():
        if name in c:
            return key
    return _key(c)


async def _cached(url: str, parse) -> object:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "huxley-assistant"}) as client:
        r = await client.get(url)
        r.raise_for_status()
    data = parse(r)
    _cache[url] = (time.time(), data)
    return data


def _parse_cbsa(r: httpx.Response) -> list[dict]:
    rows = []
    for line in r.content.decode("utf-8-sig", "replace").splitlines():
        cells = [c.strip() for c in line.split(";;")]
        if len(cells) >= 7 and cells[0] and cells[0] != "Customs Office":
            rows.append({"office": cells[0], "location": cells[1], "updated": cells[2],
                         "travellers": cells[5]})
    return rows


def _minutes(text: str) -> str:
    t = (text or "").strip()
    if not t or t in ("--", "N/A"):
        return ""
    return "no delay" if t.lower() in ("no delay", "0") else t.lower()


async def _into_us(want: str) -> str | None:
    ports = await _cached(CBP_URL, lambda r: r.json())
    for p in ports:  # type: ignore[union-attr]
        if want not in _key(f"{p.get('crossing_name', '')} {p.get('port_name', '')}"):
            continue
        name = p.get("crossing_name") or p.get("port_name")
        if p.get("port_status", "").lower() != "open":
            return f"Into the US ({name}): {p.get('port_status', 'status unknown').lower()}."
        pv = p.get("passenger_vehicle_lanes", {})
        std, nexus = pv.get("standard_lanes", {}), pv.get("NEXUS_SENTRI_lanes", {})

        def lane(d: dict) -> str:
            if d.get("operational_status", "").lower() in ("", "n/a", "update pending"):
                return ""
            mins = d.get("delay_minutes", "")
            return "no delay" if mins in ("0", "") else f"{mins} min"
        parts = [f"cars {lane(std)}" if lane(std) else "", f"NEXUS {lane(nexus)}" if lane(nexus) else ""]
        parts = [x for x in parts if x] or ["no current report"]
        when = std.get("update_time", "").lower()
        return f"Into the US ({name}): {', '.join(parts)}" + (f" ({when})." if when else ".")
    return None


async def _into_canada(want: str) -> str | None:
    rows = await _cached(CBSA_URL, _parse_cbsa)
    for row in rows:  # type: ignore[union-attr]
        if want in _key(f"{row['office']} {row['location']}"):
            wait = _minutes(row["travellers"]) or "no current report"
            return f"Into Canada ({row['office']}): cars {wait} (updated {row['updated']})."
    return None


async def border_wait(crossing: str) -> str:
    """Current waits at a Canada-US crossing, both directions."""
    want = _wanted(crossing)
    results = await asyncio.gather(_into_us(want), _into_canada(want), return_exceptions=True)
    lines = []
    for direction, res in zip(("into the US", "into Canada"), results):
        if isinstance(res, Exception):
            lines.append(f"Couldn't get waits {direction} ({type(res).__name__}).")
        elif res:
            lines.append(res)
    if not lines:
        return (f"I couldn't find a border crossing called '{crossing or settings.border_crossing}'. "
                "Try e.g. Blue Water Bridge, Ambassador Bridge or Detroit-Windsor Tunnel.")
    return " ".join(lines)


async def bridge_summary() -> str:
    """One short line for the HUD panel: 'US 5 MIN · CA NO DELAY'."""
    if not settings.border_crossing:
        return ""
    want = _wanted("")
    out = []
    try:
        us = await _into_us(want)
        m = re.search(r"cars ([^,(.]+)", us or "")
        if m:
            out.append("US " + m.group(1).strip())
    except Exception:
        pass
    try:
        ca = await _into_canada(want)
        m = re.search(r"cars ([^(]+?) \(", ca or "")
        if m:
            out.append("CA " + m.group(1).strip())
    except Exception:
        pass
    return " · ".join(out)


# ------------------------------------------------------------- drive time --

async def _geocode(client: httpx.AsyncClient, place: str) -> tuple[float, float, str]:
    from urllib.parse import quote

    r = await client.get(f"{TOMTOM}/search/2/geocode/{quote(place)}.json",
                         params={"key": settings.tomtom_key, "limit": 1})
    r.raise_for_status()
    hits = r.json().get("results") or []
    if not hits:
        raise LookupError(place)
    pos = hits[0]["position"]
    return pos["lat"], pos["lon"], hits[0].get("address", {}).get("freeformAddress", place)


async def drive_time(destination: str, origin: str) -> str:
    """Driving time with live traffic. Empty origin = home; empty destination = the commute."""
    destination = destination.strip() or settings.commute_to
    origin = origin.strip() or settings.home_location
    if not destination:
        return "Where to? (The owner can set a usual commute destination with COMMUTE_TO in setup.)"
    if not settings.tomtom_key:
        return ("Drive times need a free TomTom key (developer.tomtom.com), added with Huxley's "
                "setup. Border waits work without one.")
    if not origin:
        return "I don't know where home is; set HOME_LOCATION in setup or give a starting point."
    try:
        # Never put exception text in the reply or logs: the key is in the URL.
        async with httpx.AsyncClient(timeout=20) as client:
            (a_lat, a_lon, a_name), (b_lat, b_lon, b_name) = await asyncio.gather(
                _geocode(client, origin), _geocode(client, destination))
            r = await client.get(
                f"{TOMTOM}/routing/1/calculateRoute/{a_lat},{a_lon}:{b_lat},{b_lon}/json",
                params={"key": settings.tomtom_key, "traffic": "true", "travelMode": "car"})
            r.raise_for_status()
    except LookupError as exc:
        return f"I couldn't find '{exc.args[0]}' on the map."
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        return ("TomTom refused the key (check TOMTOM_API_KEY)." if code in (401, 403)
                else f"TomTom returned an error ({code}).")
    except httpx.HTTPError as exc:
        return f"Couldn't reach TomTom ({type(exc).__name__})."
    s = r.json()["routes"][0]["summary"]
    mins = round(s["travelTimeInSeconds"] / 60)
    delay = round(s.get("trafficDelayInSeconds", 0) / 60)
    km = s["lengthInMeters"] / 1000
    dist = f"{km:.0f} km" if settings.units != "imperial" else f"{km * 0.621:.0f} miles"
    traffic = f", including {delay} min of traffic delay" if delay >= 2 else ", traffic is light"
    note = " Border wait not included." if _crosses_border(a_name, b_name) else ""
    return f"{a_name} to {b_name}: about {_fmt(mins)} ({dist}){traffic}.{note}"


def _fmt(mins: int) -> str:
    return f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d} min"


def _crosses_border(a: str, b: str) -> bool:
    us = re.compile(r"\b(MI|NY|USA|United States|Michigan|New York)\b")
    return bool(us.search(a)) != bool(us.search(b))
