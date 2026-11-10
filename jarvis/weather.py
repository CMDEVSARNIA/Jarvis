"""Weather and world time via Open-Meteo (free, no API key)."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .config import settings

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> words
CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

_place_cache: dict[str, dict] = {}


async def find_place(name: str) -> dict | None:
    """Look up a place name. Accepts 'Toronto' or 'Toronto, Canada'."""
    key = name.strip().lower()
    if key in _place_cache:
        return _place_cache[key]
    city, _, region = name.partition(",")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(GEOCODE, params={"name": city.strip(), "count": 10, "language": "en"})
        r.raise_for_status()
        results = r.json().get("results") or []
    if region.strip():  # prefer a match on country / province / state
        want = region.strip().lower()
        results = [p for p in results if want in " ".join(
            str(p.get(k, "")).lower() for k in ("country", "country_code", "admin1"))] or results
    place = results[0] if results else None
    if place:
        _place_cache[key] = place
    return place


def _label(place: dict) -> str:
    return ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)


def _friendly(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return "The weather service is busy right now (too many requests). Try again in a minute."
    if status:
        return f"The weather service returned an error (HTTP {status}). Try again shortly."
    return "Couldn't reach the weather service. Check the internet connection."


async def get_weather(location: str) -> str:
    try:
        return await _get_weather(location)
    except httpx.HTTPError as exc:
        return _friendly(exc)


async def get_time(location: str) -> str:
    try:
        return await _get_time(location)
    except httpx.HTTPError as exc:
        return _friendly(exc)


async def _get_weather(location: str) -> str:
    name = location.strip() or settings.home_location
    if not name:
        return "No location given and no home location set (run the settings tool)."
    place = await find_place(name)
    if not place:
        return f"Couldn't find a place called '{name}'."
    imperial = settings.units == "imperial"
    params = {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 3,
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(FORECAST, params=params)
        r.raise_for_status()
        data = r.json()
    cur, daily = data["current"], data["daily"]
    t = "°F" if imperial else "°C"
    report = {
        "place": _label(place),
        "now": f"{CODES.get(cur['weather_code'], 'unknown')}, {round(cur['temperature_2m'])}{t} "
               f"(feels like {round(cur['apparent_temperature'])}{t}), wind "
               f"{round(cur['wind_speed_10m'])} {'mph' if imperial else 'km/h'}",
        "next_days": [
            f"{day}: {CODES.get(code, 'unknown')}, high {round(hi)}{t}, low {round(lo)}{t}, "
            f"{pop if pop is not None else '?'}% chance of precipitation"
            for day, code, hi, lo, pop in zip(daily["time"], daily["weather_code"],
                                              daily["temperature_2m_max"], daily["temperature_2m_min"],
                                              daily["precipitation_probability_max"])
        ],
    }
    return json.dumps(report)


async def _get_time(location: str) -> str:
    name = location.strip() or settings.home_location
    if not name:
        return datetime.now().strftime("%A %d %B %Y, %H:%M (this computer's clock)")
    place = await find_place(name)
    if not place or not place.get("timezone"):
        return f"Couldn't find a time zone for '{name}'."
    now = datetime.now(ZoneInfo(place["timezone"]))
    return f"{_label(place)}: {now.strftime('%A %d %B %Y, %H:%M')} ({place['timezone']})"
