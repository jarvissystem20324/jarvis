"""Everyday life and health (10.0): the moon, ages and date gaps, what to wear,
scaling recipes and converting kitchen units (su bardağı included), warranties,
where you put things, decluttering, water, habits, weight, BMI, calories, UV.

What can be computed is computed — the moon's phase, ages, unit conversions,
scaled quantities, BMI — and the rest comes from open data: Open-Meteo for
weather and UV, Open Food Facts for calories. None of it is medical advice,
and the health tools say so where it matters.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from . import kit

# --- the moon -------------------------------------------------------------------------------------

SYNODIC = 29.530588853                  # days from new moon to new moon
KNOWN_NEW = datetime(2000, 1, 6, 18, 14)  # a new moon (UTC)
PHASES = [(1.84566, "New moon", "🌑"), (5.53699, "Waxing crescent", "🌒"), (9.22831, "First quarter", "🌓"),
          (12.91963, "Waxing gibbous", "🌔"), (16.61096, "Full moon", "🌕"), (20.30228, "Waning gibbous", "🌖"),
          (23.99361, "Last quarter", "🌗"), (27.68493, "Waning crescent", "🌘"), (SYNODIC, "New moon", "🌑")]
TR_PHASES = {"New moon": "Yeni ay", "Waxing crescent": "Hilal (büyüyen)", "First quarter": "İlk dördün",
             "Waxing gibbous": "Şişkin ay (büyüyen)", "Full moon": "Dolunay", "Waning gibbous": "Şişkin ay (küçülen)",
             "Last quarter": "Son dördün", "Waning crescent": "Hilal (küçülen)"}


def moon(when: datetime | None = None) -> dict:
    """The phase at `when`: age in days, how much is lit, its name, and the next new and full moon.
    Accurate to within a day — the moon's orbit isn't a perfect circle, and this treats it as one."""
    when = when or datetime.now(timezone.utc).replace(tzinfo=None)
    age = ((when - KNOWN_NEW).total_seconds() / 86400) % SYNODIC
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2
    name, emoji = next((n, e) for limit, n, e in PHASES if age < limit)
    to_full = (SYNODIC / 2 - age) % SYNODIC
    to_new = (SYNODIC - age) % SYNODIC
    return {"age": age, "lit": lit, "name": name, "emoji": emoji, "tr": TR_PHASES[name],
            "next_full": (when + timedelta(days=to_full)).date(), "next_new": (when + timedelta(days=to_new)).date()}


# --- dates ------------------------------------------------------------------------------------------

MONTHS = {m: i for i, names in enumerate((
    ("jan", "january", "ocak"), ("feb", "february", "şubat", "subat"), ("mar", "march", "mart"),
    ("apr", "april", "nisan"), ("may", "mayıs", "mayis"), ("jun", "june", "haziran"),
    ("jul", "july", "temmuz"), ("aug", "august", "ağustos", "agustos"), ("sep", "sept", "september", "eylül", "eylul"),
    ("oct", "october", "ekim"), ("nov", "november", "kasım", "kasim"), ("dec", "december", "aralık", "aralik")), 1)
    for m in names}


def parse_date(text: str, today: date | None = None) -> date:
    """'1990-05-14', '14.05.1990', '14/05/1990', '14 May 1990', '14 Mayıs 1990', 'today', 'bugün'."""
    today = today or date.today()
    text = text.strip().lower()
    if text in {"today", "bugün", "now", ""}:
        return today
    if text in {"tomorrow", "yarın"}:
        return today + timedelta(days=1)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", text)
    if m:
        year = int(m.group(3))
        year += 2000 if year < 50 else 1900 if year < 100 else 0
        return date(year, int(m.group(2)), int(m.group(1)))       # day first, as in Türkiye and Europe
    m = re.fullmatch(r"(\d{1,2})\s+([a-zçğıöşü]+)\.?\s+(\d{4})", text)
    if m and m.group(2) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    m = re.fullmatch(r"([a-zçğıöşü]+)\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if m and m.group(1) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    raise ValueError(f"I can't read {text!r} as a date — try 14.05.1990 or 1990-05-14.")


def add_months(day: date, months: int) -> date:
    """The same day `months` later, or the month's last day if it's shorter (31 Jan + 1 → 28/29 Feb)."""
    from calendar import monthrange

    year, month = divmod(day.month - 1 + months, 12)
    year += day.year
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def age(born: date, today: date | None = None) -> dict:
    """Years, months and days old, and how far off the next birthday is."""
    today = today or date.today()
    if born > today:
        raise ValueError("That date hasn't happened yet.")
    whole_months = (today.year - born.year) * 12 + today.month - born.month - (today.day < born.day)
    years, months = divmod(whole_months, 12)
    days = (today - add_months(born, whole_months)).days
    upcoming = add_months(born, (years + 1) * 12)
    return {"years": years, "months": months, "days": days, "total_days": (today - born).days,
            "weeks": (today - born).days // 7, "weekday": born.strftime("%A"),
            "next_birthday": upcoming, "days_to_birthday": (upcoming - today).days, "turning": years + 1}


def date_gap(a: date, b: date) -> dict:
    start, end = min(a, b), max(a, b)
    total = (end - start).days
    weekdays = sum(1 for i in range(total) if (start + timedelta(days=i)).weekday() < 5)
    return {"days": total, "weeks": total // 7, "rest": total % 7, "weekdays": weekdays,
            "months": round(total / 30.4375, 1), "forward": b >= a}


# --- what to wear ---------------------------------------------------------------------------------

def what_to_wear(low: float, high: float, rain: float = 0, wind: float = 0, uv: float = 0) -> list[str]:
    """Plain advice from the day's low, high, chance of rain (%), wind (km/h) and UV."""
    out = []
    feel = (low + high) / 2 - (3 if wind >= 30 else 0)
    if feel < 0:
        out.append("🧥 A warm winter coat, hat, scarf and gloves — it's freezing.")
    elif feel < 8:
        out.append("🧥 A warm coat and a sweater underneath.")
    elif feel < 14:
        out.append("🧥 A jacket or a thick sweater.")
    elif feel < 19:
        out.append("👕 Long sleeves, with a light jacket you can take off.")
    elif feel < 25:
        out.append("👕 A T-shirt is fine — maybe a thin layer for the evening.")
    else:
        out.append("🩳 Light, breathable clothes — it's hot.")
    if high - low >= 9:
        out.append(f"🌡 It swings from {low:.0f}° to {high:.0f}°: wear layers.")
    if rain >= 60:
        out.append("☔ Take an umbrella and shoes that cope with puddles.")
    elif rain >= 30:
        out.append("🌂 Maybe rain — a small umbrella in the bag.")
    if wind >= 40:
        out.append("💨 Very windy: skip the umbrella if you can, a hooded jacket is better.")
    if uv >= 6:
        out.append("🕶 Strong sun (UV {:.0f}): sunglasses, a cap and sunscreen.".format(uv))
    return out


def day_forecast(city: str) -> dict:
    """Today's low/high/rain/wind/UV for a city, from Open-Meteo."""
    from . import weather

    label, lat, lon = weather.geocode(city)
    data = weather._get(weather.FORECAST, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,wind_speed_10m_max,"
                 "uv_index_max"})
    daily = data.get("daily", {})

    def pick(name, i=0):
        values = daily.get(name) or []
        return float(values[i]) if len(values) > i and values[i] is not None else 0.0

    return {"place": label, "low": pick("temperature_2m_min"), "high": pick("temperature_2m_max"),
            "rain": pick("precipitation_probability_max"), "wind": pick("wind_speed_10m_max"),
            "uv": pick("uv_index_max"), "uv_tomorrow": pick("uv_index_max", 1)}


# --- recipes ----------------------------------------------------------------------------------------

UNICODE_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8", "⅕": "1/5"}
QUANTITY = re.compile(r"(?<![\w.,/])(\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)(?:\s*-\s*(\d+(?:[.,]\d+)?))?")
NICE = {Fraction(1, 2): "½", Fraction(1, 4): "¼", Fraction(3, 4): "¾", Fraction(1, 3): "⅓", Fraction(2, 3): "⅔",
        Fraction(1, 8): "⅛"}


def _value(text: str) -> Fraction:
    text = text.strip().replace(",", ".")
    if " " in text:
        whole, part = text.split()
        return Fraction(int(whole)) + Fraction(part)
    return Fraction(text).limit_denominator(16)


def show_amount(value: Fraction) -> str:
    """2.5 → '2½', 0.333 → '⅓', 12.5 → '12.5' (fractions only where cooks use them)."""
    value = Fraction(value).limit_denominator(24)
    whole, part = divmod(value, 1)
    nearest = min(NICE, key=lambda f: abs(f - part)) if part else None
    if part == 0:
        return str(int(whole))
    if whole < 10 and nearest is not None and abs(nearest - part) < Fraction(1, 24):
        return (str(int(whole)) if whole else "") + NICE[nearest]
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def scale_recipe(text: str, factor: Fraction) -> str:
    """Every quantity times `factor`; the words stay as they are."""
    for symbol, plain in UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d)\s*{symbol}", rf"\1 {plain}", text).replace(symbol, plain)

    def scaled(m: re.Match) -> str:
        first = show_amount(_value(m.group(1)) * factor)
        if m.group(2):
            return f"{first}-{show_amount(_value(m.group(2)) * factor)}"
        return first

    return "\n".join(QUANTITY.sub(scaled, line) for line in text.splitlines())


# --- kitchen units ---------------------------------------------------------------------------------

VOLUME_ML = {"ml": 1, "milliliter": 1, "millilitre": 1, "l": 1000, "liter": 1000, "litre": 1000, "lt": 1000,
             "cup": 236.6, "cups": 236.6, "tbsp": 15, "tablespoon": 15, "tablespoons": 15, "tsp": 5,
             "teaspoon": 5, "teaspoons": 5, "fl oz": 29.57, "floz": 29.57,
             "su bardağı": 200, "su bardagi": 200, "çay bardağı": 100, "cay bardagi": 100,
             "yemek kaşığı": 15, "yemek kasigi": 15, "tatlı kaşığı": 10, "tatli kasigi": 10,
             "çay kaşığı": 5, "cay kasigi": 5, "kahve fincanı": 70, "kahve fincani": 70}
WEIGHT_G = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "gramı": 1, "kg": 1000, "kilo": 1000, "oz": 28.35,
            "ounce": 28.35, "ounces": 28.35, "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6}
# grams per millilitre, as packed into a cup the usual way
DENSITY = {"flour": 0.53, "un": 0.53, "sugar": 0.85, "şeker": 0.85, "seker": 0.85, "brown sugar": 0.93,
           "powdered sugar": 0.51, "pudra şekeri": 0.51, "butter": 0.96, "tereyağı": 0.96, "tereyag": 0.96,
           "milk": 1.03, "süt": 1.03, "sut": 1.03, "water": 1.0, "su": 1.0, "oil": 0.92, "yağ": 0.92, "yag": 0.92,
           "honey": 1.42, "bal": 1.42, "rice": 0.85, "pirinç": 0.85, "pirinc": 0.85, "salt": 1.2, "tuz": 1.2,
           "cocoa": 0.42, "kakao": 0.42, "oats": 0.38, "yulaf": 0.38, "yogurt": 1.03, "yoğurt": 1.03,
           "semolina": 0.68, "irmik": 0.68, "bulgur": 0.75, "lentils": 0.82, "mercimek": 0.82}


def _unit(text: str) -> tuple[str, str] | None:
    """('volume'|'weight', the unit) for the longest unit name found in text."""
    low = text.lower()
    best = None
    for table, kind in ((VOLUME_ML, "volume"), (WEIGHT_G, "weight")):
        for name in table:
            if re.search(rf"(?<![a-zçğıöşü]){re.escape(name)}(?![a-zçğıöşü])", low):
                if best is None or len(name) > len(best[1]):
                    best = (kind, name)
    return best


def kitchen_convert(text: str) -> str:
    """'2 cups flour to grams', '200 g un kaç su bardağı', '1 su bardağı süt kaç ml'."""
    low = text.lower().replace(",", ".")
    parts = re.split(r"\s+(?:to|in|into|kaç|kac|=)\s+", low, maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Say it like: 2 cups flour to grams · 200 g un kaç su bardağı")
    source, target = parts
    m = re.search(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+)?|[½¼¾⅓⅔])", source)
    if not m:
        raise ValueError("How much? e.g. 2 cups flour to grams")
    raw = UNICODE_FRACTIONS.get(m.group(1), m.group(1)).replace(" ", "")
    amount = float(Fraction(raw)) if "/" in raw else float(raw)
    from_unit, to_unit = _unit(source), _unit(target)
    if not from_unit or not to_unit:
        raise ValueError("I know ml, l, cups, tbsp, tsp, su/çay bardağı, yemek/tatlı/çay kaşığı, g, kg, oz, lb.")
    ingredient = next((name for name in sorted(DENSITY, key=len, reverse=True)
                       if re.search(rf"(?<![a-zçğıöşü]){re.escape(name)}(?![a-zçğıöşü])", source)), "")
    tables = {"volume": VOLUME_ML, "weight": WEIGHT_G}
    base = amount * tables[from_unit[0]][from_unit[1]]          # ml or g
    if from_unit[0] != to_unit[0]:
        if not ingredient:
            raise ValueError("Between cups and grams it depends on what it is — say flour, sugar, butter, milk…")
        base = base * DENSITY[ingredient] if from_unit[0] == "volume" else base / DENSITY[ingredient]
    result = base / tables[to_unit[0]][to_unit[1]]
    shown = f"{result:.0f}" if result >= 20 else f"{result:.1f}".rstrip("0").rstrip(".")
    left = f"{amount:g} {from_unit[1]}" + (f" {ingredient}" if ingredient else "")
    return f"{left} ≈ {shown} {to_unit[1]}"


# --- warranties, things, decluttering -------------------------------------------------------------

WARRANTIES = kit.Store("warranties.json", [])
STASH = kit.Store("stash.json", [])
DECLUTTER = kit.Store("declutter.json", {})

CHECKLISTS = {
    "Kitchen": ["Expired food and spices", "Duplicate utensils and gadgets you don't use",
                "Containers without lids (and lids without containers)", "Chipped mugs and plates",
                "Old takeaway menus and plastic bags", "Appliances unused for a year"],
    "Wardrobe": ["Clothes you haven't worn in a year", "Things that don't fit", "Worn-out shoes",
                 "Single socks and stretched underwear", "Bags and belts you never use", "Donate the good ones"],
    "Bathroom": ["Expired medicines (to the pharmacy, not the bin)", "Old make-up and sunscreen",
                 "Nearly-empty bottles", "Hotel minis", "Worn towels"],
    "Bedroom": ["The chair of clothes", "Under the bed", "Bedside drawer", "Chargers and cables you don't need",
                "Books you won't read again"],
    "Desk and papers": ["Old receipts (keep warranties!)", "Manuals you can find online", "Dried-up pens",
                        "Old bills — scan, then shred", "Business cards"],
    "Digital": ["Downloads folder", "Desktop icons", "Duplicate photos", "Apps you don't use",
                "Newsletters to unsubscribe from", "Old screenshots"],
    "Balcony and storage": ["Broken things you'll never fix", "Boxes from things you own", "Old paint",
                            "Kids' things outgrown", "Seasonal decorations — sort and label"],
}


def warranty_add(item: str, bought: date, months: int, note: str = "") -> dict:
    until = add_months(bought, months)
    entry = {"item": item.strip(), "bought": bought.isoformat(), "months": months, "until": until.isoformat(),
             "note": note.strip()}
    rows = WARRANTIES.load()
    rows.append(entry)
    WARRANTIES.save(rows)
    return entry


def warranties(today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = []
    for row in WARRANTIES.load():
        left = (date.fromisoformat(row["until"]) - today).days
        rows.append(dict(row, days_left=left))
    return sorted(rows, key=lambda r: r["days_left"])


def stash_put(thing: str, place: str) -> None:
    rows = [r for r in STASH.load() if r["thing"].lower() != thing.strip().lower()]
    rows.append({"thing": thing.strip(), "place": place.strip(), "at": datetime.now().isoformat(timespec="minutes")})
    STASH.save(rows)


def stash_find(query: str) -> list[dict]:
    from .games import _fold

    words = _fold(query).split()
    rows = STASH.load()
    hits = [r for r in rows if all(w in _fold(r["thing"]) for w in words)]
    if not hits:
        hits = [r for r in rows if any(w in _fold(r["thing"]) for w in words if len(w) > 2)]
    return sorted(hits, key=lambda r: r["at"], reverse=True)


# --- health -----------------------------------------------------------------------------------------

WATER = kit.Store("water.json", {})
HABITS = kit.Store("habits.json", {})
WEIGHTS = kit.Store("weights.json", [])
HEALTH = kit.Store("health_settings.json", {"water_goal": 2000, "height_cm": 0, "uv_alert": True,
                                            "water_reminders": False})


def water_today(day: date | None = None) -> int:
    return int(WATER.load().get((day or date.today()).isoformat(), 0))


def add_water(ml: int, day: date | None = None) -> int:
    data = WATER.load()
    key = (day or date.today()).isoformat()
    data[key] = max(0, int(data.get(key, 0)) + ml)
    WATER.save(data)
    return data[key]


def water_behind(now: datetime | None = None) -> bool:
    """Behind where you'd be by now if you drank evenly from 9:00 to 21:00."""
    now = now or datetime.now()
    if not (10 <= now.hour < 21):
        return False
    goal = HEALTH.load().get("water_goal", 2000)
    expected = goal * (now.hour - 9 + now.minute / 60) / 12
    return water_today(now.date()) < expected - 250


def habit_done(name: str, day: date | None = None) -> int:
    data = HABITS.load()
    key = next((k for k in data if k.lower() == name.strip().lower()), name.strip())
    days = set(data.get(key, []))
    days.add((day or date.today()).isoformat())
    data[key] = sorted(days)
    HABITS.save(data)
    return habit_streak(data[key], day)


def habit_streak(days: list[str], today: date | None = None) -> int:
    today = today or date.today()
    done = {date.fromisoformat(d) for d in days}
    day = today if today in done else today - timedelta(days=1)
    count = 0
    while day in done:
        count += 1
        day -= timedelta(days=1)
    return count


def bmi(weight_kg: float, height_cm: float) -> dict:
    """WHO adult categories; the healthy range is BMI 18.5-24.9 at this height."""
    if not 20 <= weight_kg <= 400 or not 100 <= height_cm <= 250:
        raise ValueError("Weight in kg (20-400) and height in cm (100-250), please.")
    metres = height_cm / 100
    value = weight_kg / metres ** 2
    category = ("underweight" if value < 18.5 else "a healthy weight" if value < 25 else "overweight"
                if value < 30 else "obese")
    return {"bmi": round(value, 1), "category": category,
            "healthy": (round(18.5 * metres ** 2, 1), round(24.9 * metres ** 2, 1))}


def log_weight(kg: float, day: date | None = None) -> list[dict]:
    rows = [r for r in WEIGHTS.load() if r["day"] != (day or date.today()).isoformat()]
    rows.append({"day": (day or date.today()).isoformat(), "kg": round(kg, 1)})
    rows.sort(key=lambda r: r["day"])
    WEIGHTS.save(rows[-1000:])
    return rows


def food_lookup(query: str, limit: int = 5) -> list[dict]:
    """Calories per 100 g (and protein, carbs, fat) from Open Food Facts' open database."""
    data = kit.get_json("https://world.openfoodfacts.org/cgi/search.pl", {
        "search_terms": query, "search_simple": 1, "json": 1, "page_size": 20,
        "fields": "product_name,brands,nutriments"})
    out = []
    for product in data.get("products", []):
        n = product.get("nutriments") or {}
        kcal = n.get("energy-kcal_100g")
        if kcal is None and n.get("energy_100g") is not None:
            kcal = float(n["energy_100g"]) / 4.184
        if kcal is None or not product.get("product_name"):
            continue
        out.append({"name": product["product_name"].strip(), "brand": (product.get("brands") or "").split(",")[0],
                    "kcal": round(float(kcal)), "protein": n.get("proteins_100g"), "carbs": n.get("carbohydrates_100g"),
                    "fat": n.get("fat_100g")})
        if len(out) >= limit:
            break
    return out


def uv_words(uv: float) -> str:
    return ("low" if uv < 3 else "moderate" if uv < 6 else "high" if uv < 8 else "very high" if uv < 11
            else "extreme")
