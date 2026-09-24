"""Weather from Open-Meteo: free, no key, no account.

"weather", "weather tomorrow in Istanbul", "will it rain tomorrow". The city
you name is sent to Open-Meteo to be looked up; nothing else is. Your own
location is never guessed from your IP address — set a home city once with
/weather city <name> and it is remembered in .env.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from . import net
from .config import get_setting

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
UA = {"User-Agent": "JARVIS-desktop (weather)"}

# WMO weather interpretation codes, as Open-Meteo documents them.
CODES = {
    0: ("Clear", "☀"), 1: ("Mostly clear", "🌤"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁"),
    45: ("Fog", "🌫"), 48: ("Freezing fog", "🌫"), 51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"),
    55: ("Heavy drizzle", "🌧"), 56: ("Freezing drizzle", "🌧"), 57: ("Freezing drizzle", "🌧"),
    61: ("Light rain", "🌦"), 63: ("Rain", "🌧"), 65: ("Heavy rain", "🌧"), 66: ("Freezing rain", "🌧"),
    67: ("Freezing rain", "🌧"), 71: ("Light snow", "🌨"), 73: ("Snow", "🌨"), 75: ("Heavy snow", "❄"),
    77: ("Snow grains", "🌨"), 80: ("Showers", "🌦"), 81: ("Showers", "🌧"), 82: ("Violent showers", "⛈"),
    85: ("Snow showers", "🌨"), 86: ("Heavy snow showers", "❄"), 95: ("Thunderstorm", "⛈"),
    96: ("Thunderstorm with hail", "⛈"), 99: ("Thunderstorm with hail", "⛈"),
}


class WeatherError(Exception):
    pass


def _get(url: str, params: dict) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with net.urlopen(urllib.request.Request(full, headers=UA), timeout=15) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise WeatherError(f"Couldn't reach the weather service: {net.describe_ssl_error(exc) or exc}") from None


def geocode(city: str) -> tuple[str, float, float]:
    data = _get(GEOCODE, {"name": city, "count": 1, "language": "en", "format": "json"})
    results = data.get("results") or []
    if not results:
        raise WeatherError(f"I couldn't find a place called '{city}'.")
    place = results[0]
    label = ", ".join(x for x in (place.get("name"), place.get("country")) if x)
    return label, float(place["latitude"]), float(place["longitude"])


def parse(text: str) -> tuple[str, int]:
    """('Istanbul', day offset) from 'tomorrow in istanbul' and friends."""
    t = text.strip().rstrip("?.! ")
    offset = 0
    for word, days in (("day after tomorrow", 2), ("tomorrow", 1), ("yarın", 1), ("today", 0), ("now", 0), ("tonight", 0)):
        if re.search(rf"\b{word}\b", t, re.I):
            offset = days
            t = re.sub(rf"\b{word}\b", " ", t, flags=re.I)
            break
    t = re.sub(r"\b(what'?s|what is|the|weather|forecast|like|will it|rain|be|going to|in|for|at|hava|durumu|how)\b",
               " ", t, flags=re.I)
    return " ".join(t.split()).strip(" ,"), offset


def home_city() -> str:
    return get_setting("JARVIS_CITY", "").strip()


def report(text: str) -> str:
    city, offset = parse(text)
    city = city or home_city()
    if not city:
        return ("Which city? Say 'weather in Istanbul', or set a home city once:\n"
                "  /weather city Istanbul")
    label, lat, lon = geocode(city)
    units = get_setting("JARVIS_UNITS", "metric").lower()
    imperial = units.startswith("imp")
    data = _get(FORECAST, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 4,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    })
    deg = "°F" if imperial else "°C"
    wind = "mph" if imperial else "km/h"
    daily = data.get("daily") or {}
    lines: list[str] = []
    if offset == 0 and data.get("current"):
        now = data["current"]
        name, icon = CODES.get(int(now.get("weather_code", -1)), ("—", ""))
        lines.append(
            f"{icon} {label}: {name}, {now['temperature_2m']:.0f}{deg} "
            f"(feels {now['apparent_temperature']:.0f}{deg}), wind {now['wind_speed_10m']:.0f} {wind}, "
            f"humidity {now['relative_humidity_2m']:.0f}%."
        )
    days = daily.get("time") or []
    for index in range(offset, min(len(days), offset + (3 if offset == 0 else 1))):
        name, icon = CODES.get(int(daily["weather_code"][index]), ("—", ""))
        day = date.fromisoformat(days[index])
        heading = {0: "Today", 1: "Tomorrow"}.get((day - date.today()).days, f"{day:%A}")
        rain = daily.get("precipitation_probability_max", [None] * len(days))[index]
        line = (f"  {heading:<9} {icon} {name}, {daily['temperature_2m_min'][index]:.0f}–"
                f"{daily['temperature_2m_max'][index]:.0f}{deg}")
        if rain is not None:
            line += f", {rain:.0f}% chance of rain"
        lines.append(line)
    if offset > 0 and len(lines) == 1:
        lines[0] = f"{label} — " + lines[0].strip()
    lines.append("(Open-Meteo)")
    return "\n".join(lines)
