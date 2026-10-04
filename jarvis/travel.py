"""Travel and maps (10.0): finding places, what's nearby, saved places, the
map's tiles, trip budgets, itineraries into the calendar, a documents
checklist, and a jet lag plan.

Everything map-shaped is OpenStreetMap: tiles from tile.openstreetmap.org,
place search from Nominatim, nearby places from Overpass (with Nominatim as
a fallback — Overpass is often busy). Their usage policies ask for an honest
User-Agent, light use and attribution, so tiles are cached on disk, searches
are one at a time, and the map credits OpenStreetMap's contributors.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from . import kit

PLACES = kit.Store("places.json", [])
TRAVEL_DOCS = kit.Store("travel_docs.json", {})
_last_nominatim = [0.0]


class TravelError(Exception):
    pass


def user_agent() -> dict:
    from . import __version__

    return {"User-Agent": f"JARVIS/{__version__} (desktop assistant; github.com/jarvissystem20324/jarvis)"}


def _get(url: str, timeout: float = 20) -> bytes:
    from . import net

    try:
        with net.urlopen(urllib.request.Request(url, headers=user_agent()), timeout=timeout) as response:
            return response.read(5_000_000)
    except Exception as exc:
        raise TravelError(f"Couldn't reach {urllib.parse.urlparse(url).netloc}: {exc}") from None


def _nominatim(params: dict) -> list[dict]:
    # Nominatim's rule: at most one request a second.
    wait = 1.05 - (time.time() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    _last_nominatim[0] = time.time()
    body = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        dict(params, format="jsonv2", addressdetails=0)))
    return json.loads(body)


# --- places ---------------------------------------------------------------------------------------

def search(query: str, limit: int = 6) -> list[dict]:
    """Places matching `query`: {name, label, lat, lon, kind}."""
    rows = _nominatim({"q": query, "limit": limit})
    return [{"name": r.get("name") or r["display_name"].split(",")[0], "label": r["display_name"],
             "lat": float(r["lat"]), "lon": float(r["lon"]), "kind": r.get("type", "")} for r in rows]


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def show_distance(metres: float) -> str:
    return f"{metres:.0f} m" if metres < 1000 else f"{metres / 1000:.1f} km"


NEARBY = {
    "pharmacy": ('["amenity"="pharmacy"]', "pharmacy", "💊"), "cafe": ('["amenity"="cafe"]', "cafe", "☕"),
    "restaurant": ('["amenity"="restaurant"]', "restaurant", "🍽"), "atm": ('["amenity"="atm"]', "atm", "🏧"),
    "fuel": ('["amenity"="fuel"]', "fuel", "⛽"), "hospital": ('["amenity"="hospital"]', "hospital", "🏥"),
    "supermarket": ('["shop"="supermarket"]', "supermarket", "🛒"), "hotel": ('["tourism"="hotel"]', "hotel", "🏨"),
    "museum": ('["tourism"="museum"]', "museum", "🏛"), "toilets": ('["amenity"="toilets"]', "toilets", "🚻"),
    "parking": ('["amenity"="parking"]', "parking", "🅿"), "bank": ('["amenity"="bank"]', "bank", "🏦"),
    "mosque": ('["amenity"="place_of_worship"]["religion"="muslim"]', "mosque", "🕌"),
    "charging": ('["amenity"="charging_station"]', "charging station", "🔌"),
}
PLURAL = {"pharmacy": "pharmacies", "cafe": "cafés", "restaurant": "restaurants", "atm": "ATMs",
          "fuel": "petrol stations", "hospital": "hospitals", "supermarket": "supermarkets", "hotel": "hotels",
          "museum": "museums", "toilets": "toilets", "parking": "car parks", "bank": "banks", "mosque": "mosques",
          "charging": "charging stations"}
NEARBY_WORDS = {"eczane": "pharmacy", "kafe": "cafe", "kahve": "cafe", "restoran": "restaurant", "lokanta": "restaurant",
                "bankamatik": "atm", "benzinlik": "fuel", "akaryakıt": "fuel", "hastane": "hospital",
                "market": "supermarket", "otel": "hotel", "müze": "museum", "tuvalet": "toilets", "wc": "toilets",
                "otopark": "parking", "banka": "bank", "cami": "mosque", "şarj": "charging", "ev charging": "charging"}


def nearby_kind(text: str) -> str | None:
    low = text.lower().strip()
    for word, kind in NEARBY_WORDS.items():
        if word in low:
            return kind
    return next((k for k in NEARBY if k in low or low.rstrip("s") == k), None)


def nearby(lat: float, lon: float, kind: str, radius: int = 1200, limit: int = 15) -> list[dict]:
    """Places of a kind near a point, nearest first. Overpass first; Nominatim if it's busy."""
    tag, word, icon = NEARBY[kind]
    query = f"[out:json][timeout:15];nwr(around:{radius},{lat},{lon}){tag};out center 40;"
    rows: list[dict] = []
    try:
        data = json.loads(_get("https://overpass-api.de/api/interpreter?" + urllib.parse.urlencode({"data": query}),
                               timeout=20))
        for e in data.get("elements", []):
            plat = e.get("lat") or (e.get("center") or {}).get("lat")
            plon = e.get("lon") or (e.get("center") or {}).get("lon")
            if plat is None:
                continue
            tags = e.get("tags", {})
            rows.append({"name": tags.get("name") or tags.get("brand") or word.capitalize(), "lat": plat, "lon": plon,
                         "kind": kind, "icon": icon, "address": " ".join(
                             x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x),
                         "hours": tags.get("opening_hours", ""), "phone": tags.get("phone", "")})
    except (TravelError, ValueError):
        d = radius / 111_000
        box = f"{lon - d * 1.3},{lat + d},{lon + d * 1.3},{lat - d}"
        for r in _nominatim({"q": word, "limit": 30, "viewbox": box, "bounded": 1}):
            rows.append({"name": r.get("name") or word.capitalize(), "lat": float(r["lat"]), "lon": float(r["lon"]),
                         "kind": kind, "icon": icon, "address": r["display_name"].split(",")[1].strip()
                         if "," in r["display_name"] else "", "hours": "", "phone": ""})
    for row in rows:
        row["distance"] = distance_m(lat, lon, row["lat"], row["lon"])
    rows = [r for r in rows if r["distance"] <= radius * 1.4]
    return sorted(rows, key=lambda r: r["distance"])[:limit]


def where_am_i() -> tuple[str, float, float] | None:
    """Home (a saved place called home/ev), else the city in Settings, else None."""
    for place in PLACES.load():
        if place["name"].lower() in {"home", "ev", "evim"}:
            return place["name"], place["lat"], place["lon"]
    from . import weather

    city = weather.home_city()
    if city:
        try:
            return weather.geocode(city)
        except Exception:
            return None
    return None


def save_place(name: str, lat: float, lon: float, note: str = "") -> dict:
    rows = [r for r in PLACES.load() if r["name"].lower() != name.strip().lower()]
    entry = {"name": name.strip(), "lat": round(lat, 6), "lon": round(lon, 6), "note": note.strip(),
             "added": datetime.now().isoformat(timespec="minutes")}
    rows.append(entry)
    PLACES.save(rows)
    return entry


# --- map tiles --------------------------------------------------------------------------------------

TILE = 256
_TILE_SLOTS = threading.BoundedSemaphore(4)


def to_pixels(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """World pixel position of a point at a zoom level (Web Mercator, as every web map uses)."""
    scale = TILE * 2 ** zoom
    x = (lon + 180) / 360 * scale
    lat = max(-85.0511, min(85.0511, lat))
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * scale
    return x, y


def to_latlon(x: float, y: float, zoom: int) -> tuple[float, float]:
    scale = TILE * 2 ** zoom
    lon = x / scale * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    return lat, lon


def tile_path(z: int, x: int, y: int) -> Path:
    from .config import get_data_dir

    return get_data_dir() / "cache" / "tiles" / str(z) / str(x) / f"{y}.png"


def tile(z: int, x: int, y: int) -> Path | None:
    """A map tile from the disk cache, or fetched from OpenStreetMap (kept for a week)."""
    n = 2 ** z
    if not (0 <= y < n):
        return None
    x %= n
    path = tile_path(z, x, y)
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return path
    try:
        with _TILE_SLOTS:          # a few downloads at a time, as OpenStreetMap's tile policy asks
            data = _get(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", timeout=15)
    except TravelError:
        return path if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- trips ------------------------------------------------------------------------------------------

DOCS = {
    "Before you go": ["Passport valid 6+ months after you return", "Visa or e-Visa if needed (check the official "
                      "consulate site)", "Travel insurance", "Flight / bus tickets", "Hotel bookings",
                      "Copies of passport and bookings (phone + paper)", "Bank card works abroad; tell the bank"],
    "On the day": ["Passport and ID", "Tickets / boarding pass", "Phone, charger, power bank", "Plug adapter",
                   "Some local cash", "Medicines in hand luggage (with prescriptions)", "e-SIM or roaming set up"],
    "Driving abroad": ["Driving licence", "International driving permit (if needed)", "Car rental voucher",
                       "Green card / car insurance"],
}


def jetlag_plan(origin_zone, dest_zone, depart: datetime) -> dict:
    """How far the body clock has to move, and a plan for the days around the flight."""
    offset_from = depart.replace(tzinfo=origin_zone).utcoffset()
    offset_to = depart.replace(tzinfo=dest_zone).utcoffset()
    hours = (offset_to - offset_from).total_seconds() / 3600
    east = hours > 0
    shift = abs(hours)
    # Roughly a day per hour going east, and a little faster going west.
    days = math.ceil(shift if east else shift / 1.5)
    before = min(3, math.ceil(shift))
    steps = []
    for i in range(before, 0, -1):            # an hour more each day, up to three
        day = (depart - timedelta(days=i)).date()
        steps.append(f"{day:%a %d %b}: bed and wake about {before - i + 1} h {'earlier' if east else 'later'} "
                     "than usual")
    arrival = []
    if shift >= 2:
        arrival.append("Get daylight in the morning there" if east else "Get daylight in the late afternoon there")
        arrival.append("Avoid bright light in the evening" if east else "Avoid bright light early in the morning")
        arrival.append("Eat meals at local times from the first day; keep naps under 30 minutes")
        arrival.append("Drink water on the flight; go easy on coffee after midday local time")
    return {"hours": hours, "east": east, "days": days if shift >= 2 else 0, "before": steps if shift >= 3 else [],
            "arrival": arrival}
