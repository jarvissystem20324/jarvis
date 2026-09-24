"""World clock and time-zone conversion.

    /clock Tokyo                    what time is it in Tokyo
    /clock 3pm Istanbul in London   15:00 in Istanbul is 13:00 in London
    /clock                          a few cities at a glance

Common cities are known offline. Anything else is looked up with
Open-Meteo's geocoder (the city name is sent, nothing else), which also
returns the place's time zone. Daylight saving is handled by the IANA
database that ships with JARVIS.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CITIES = {
    "istanbul": "Europe/Istanbul", "ankara": "Europe/Istanbul", "izmir": "Europe/Istanbul",
    "turkey": "Europe/Istanbul", "türkiye": "Europe/Istanbul", "london": "Europe/London",
    "uk": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam", "madrid": "Europe/Madrid", "rome": "Europe/Rome",
    "moscow": "Europe/Moscow", "athens": "Europe/Athens", "kyiv": "Europe/Kyiv", "kiev": "Europe/Kyiv",
    "dubai": "Asia/Dubai", "riyadh": "Asia/Riyadh", "doha": "Asia/Qatar", "tehran": "Asia/Tehran",
    "baku": "Asia/Baku", "karachi": "Asia/Karachi", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "india": "Asia/Kolkata", "bangkok": "Asia/Bangkok", "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai", "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland",
    "new york": "America/New_York", "nyc": "America/New_York", "boston": "America/New_York",
    "washington": "America/New_York", "toronto": "America/Toronto", "chicago": "America/Chicago",
    "denver": "America/Denver", "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "são paulo": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires", "cairo": "Africa/Cairo", "lagos": "Africa/Lagos",
    "johannesburg": "Africa/Johannesburg", "nairobi": "Africa/Nairobi", "utc": "UTC", "gmt": "UTC",
}
AT_A_GLANCE = ("Istanbul", "London", "New York", "Los Angeles", "Tokyo")


class ClockError(Exception):
    pass


def zone_for(place: str) -> tuple[str, ZoneInfo]:
    key = place.lower().strip().strip("?.,")
    if key in CITIES:
        return place.strip().title(), ZoneInfo(CITIES[key])
    try:
        return place, ZoneInfo(place.strip())            # "Europe/Lisbon"
    except (ZoneInfoNotFoundError, ValueError):
        pass
    from . import weather

    try:
        data = weather._get(weather.GEOCODE, {"name": place, "count": 1, "language": "en", "format": "json"})
    except weather.WeatherError as exc:
        raise ClockError(str(exc)) from None
    results = data.get("results") or []
    if not results or not results[0].get("timezone"):
        raise ClockError(f"I don't know where '{place}' is.")
    hit = results[0]
    return ", ".join(x for x in (hit.get("name"), hit.get("country")) if x), ZoneInfo(hit["timezone"])


def _stamp(moment: datetime, reference: datetime | None = None) -> str:
    day = ""
    if reference is not None and moment.date() != reference.date():
        day = " (next day)" if moment.date() > reference.date() else " (previous day)"
    offset = moment.utcoffset() or timedelta(0)
    hours = offset.total_seconds() / 3600
    sign = "+" if hours >= 0 else "-"
    utc = f"UTC{sign}{abs(hours):g}"
    return f"{moment:%H:%M} {moment:%a}{day}  ({utc})"


def parse_time(text: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", text.strip(), re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    meridian = (m.group(3) or "").lower()
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None


def answer(text: str) -> str:
    t = " ".join(text.strip().rstrip("?").split())
    t = re.sub(r"^(?:what\s+time\s+is\s+it|what'?s\s+the\s+time|time)\s*(?:now\s+)?(?:in\s+)?", "", t, flags=re.I)
    if not t:
        here = datetime.now().astimezone()
        rows = [f"  {'Here':<14} {_stamp(here)}"]
        for city in AT_A_GLANCE:
            label, zone = zone_for(city)
            rows.append(f"  {label:<14} {_stamp(datetime.now(zone), here)}")
        return "World clock\n" + "\n".join(rows)

    m = re.fullmatch(r"(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?)\s+(?:in\s+)?(.+?)\s+(?:in|to|for)\s+(.+)", t, re.I)
    if m and parse_time(m.group(1)):
        hour, minute = parse_time(m.group(1))
        src_label, src_zone = zone_for(m.group(2))
        dst_label, dst_zone = zone_for(m.group(3))
        start = datetime.now(src_zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
        there = start.astimezone(dst_zone)
        return f"{start:%H:%M} in {src_label} is {_stamp(there, start)} in {dst_label}."

    label, zone = zone_for(t)
    now = datetime.now(zone)
    here = datetime.now().astimezone()
    difference = ((now.utcoffset() or timedelta(0)) - (here.utcoffset() or timedelta(0))).total_seconds() / 3600
    relation = ("the same time as here" if difference == 0 else
                f"{abs(difference):g} hour{'s' if abs(difference) != 1 else ''} "
                f"{'ahead of' if difference > 0 else 'behind'} you")
    return f"{label}: {now:%H:%M}, {now:%A %d %B} — {relation}."
