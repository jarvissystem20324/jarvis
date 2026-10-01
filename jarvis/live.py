"""8.0 — Live information: prayer times, earthquakes, gold, crypto, stocks,
holidays, news, air quality, sunrise and sunset — and watches that tell you
when a currency crosses a line, a price drops or a page changes.

Every number comes from a public source that needs no key (Diyanet times via
Aladhan, EMSC, gold-api, CoinGecko, Yahoo Finance, Nager.Date, Google News,
Open-Meteo). Watches are checked while JARVIS is open, on the reminder board,
so they cost nothing when it's closed and resume when it starts.
"""

from __future__ import annotations

import difflib
import hashlib
import html
import json
import math
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import i18n, kit, reminders, security, weather
from .registry import command

G = "Live info"
WATCHES = kit.Store("watches.json", [])
OUNCE_GRAMS = 31.1034768
COINS = {"btc": "bitcoin", "bitcoin": "bitcoin", "eth": "ethereum", "ethereum": "ethereum", "sol": "solana",
         "solana": "solana", "bnb": "binancecoin", "xrp": "ripple", "ada": "cardano", "doge": "dogecoin",
         "dogecoin": "dogecoin", "avax": "avalanche-2", "dot": "polkadot", "trx": "tron", "ton": "the-open-network",
         "usdt": "tether", "link": "chainlink", "ltc": "litecoin", "pepe": "pepe", "shib": "shiba-inu"}
PRAYERS_TR = {"Imsak": "İmsak", "Fajr": "Sabah", "Sunrise": "Güneş", "Dhuhr": "Öğle", "Asr": "İkindi",
              "Maghrib": "Akşam", "Isha": "Yatsı"}


def _place(text: str) -> tuple[str, float, float]:
    city = text.strip() or weather.home_city()
    if not city:
        raise kit.KitError("Which city? Add one (e.g. /prayer Istanbul) or set a home city with /weather city <name>.")
    try:
        return weather.geocode(city)
    except weather.WeatherError as exc:
        raise kit.KitError(str(exc)) from None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# --- prices -----------------------------------------------------------------------------

def gold_prices() -> dict:
    ounce = float(kit.get_json("https://api.gold-api.com/price/XAU")["price"])
    silver = float(kit.get_json("https://api.gold-api.com/price/XAG")["price"])
    from . import calc

    rates, _ = calc.rates("USD")
    usd_try = float(rates["TRY"])
    gram = ounce / OUNCE_GRAMS * usd_try
    return {"ounce_usd": ounce, "gram_try": gram, "silver_gram_try": silver / OUNCE_GRAMS * usd_try, "usd_try": usd_try,
            "quarter_try": gram * 1.754 * 0.916}


def crypto_prices(symbols: list[str]) -> dict:
    ids = [COINS.get(s.lower(), s.lower()) for s in symbols]
    data = kit.get_json("https://api.coingecko.com/api/v3/simple/price",
                        {"ids": ",".join(ids), "vs_currencies": "usd,try", "include_24hr_change": "true"})
    return {s: data[i] for s, i in zip(symbols, ids) if i in data}


def stock_quote(symbol: str) -> dict:
    symbol = symbol.strip().upper()
    tries = [symbol] if "." in symbol or "^" in symbol else [symbol, f"{symbol}.IS"]
    for candidate in tries:
        try:
            data = kit.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(candidate)}",
                                {"range": "5d", "interval": "1d"})
        except kit.KitError:
            continue
        result = (data.get("chart", {}).get("result") or [None])[0]
        if result and result.get("meta", {}).get("regularMarketPrice") is not None:
            meta = result["meta"]
            previous = meta.get("chartPreviousClose") or meta.get("previousClose") or meta["regularMarketPrice"]
            return {"symbol": meta.get("symbol", candidate), "name": meta.get("longName") or meta.get("shortName") or candidate,
                    "price": float(meta["regularMarketPrice"]), "previous": float(previous),
                    "currency": meta.get("currency", ""), "exchange": meta.get("fullExchangeName", "")}
    raise kit.KitError(f"No quote for '{symbol}'. Use the ticker (AAPL, THYAO, ASELS.IS, ^GSPC).")


def quote_value(subject: str) -> tuple[float, str]:
    """Current value of what an alert watches: 'usd', 'eur/usd', 'btc', 'gold', 'ons', 'aapl'."""
    s = subject.strip().lower()
    from . import calc

    if s in {"gold", "altın", "altin", "gram"}:
        return gold_prices()["gram_try"], "gram gold (TRY)"
    if s in {"ons", "ounce", "xau"}:
        return gold_prices()["ounce_usd"], "gold ounce (USD)"
    pair = re.fullmatch(r"([a-z]{3})(?:\s*[/-]\s*([a-z]{3}))?", s)
    if pair and calc.currency_code(pair.group(1)) and s not in COINS:
        base = calc.currency_code(pair.group(1))
        target = calc.currency_code(pair.group(2)) if pair.group(2) else ("TRY" if base != "TRY" else "USD")
        rates, _ = calc.rates(base)
        return float(rates[target]), f"{base}/{target}"
    coin = re.fullmatch(r"([a-z0-9-]+)(?:\s*/\s*(usd|try))?", s)
    if coin and coin.group(1) in COINS:
        fiat = coin.group(2) or "usd"
        price = crypto_prices([coin.group(1)])
        return float(price[coin.group(1)][fiat]), f"{coin.group(1).upper()}/{fiat.upper()}"
    quote = stock_quote(subject)
    return quote["price"], f"{quote['symbol']} ({quote['currency']})"


def find_price(page: str) -> float | None:
    """A product page's price: JSON-LD offers, then the usual meta tags."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                for key in ("price", "lowPrice"):
                    if key in item and str(item[key]).strip():
                        try:
                            return _number(str(item[key]))
                        except ValueError:
                            pass
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
    for name in ("product:price:amount", "og:price:amount", "price"):
        m = re.search(rf'<meta[^>]+(?:property|name|itemprop)=["\']{re.escape(name)}["\'][^>]*content=["\']([\d.,]+)', page, re.I)
        if m:
            return _number(m.group(1))
    m = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)', page, re.I)
    return _number(m.group(1)) if m else None


def _price(value: float) -> str:
    """4167720 -> '4,167,720'; 2705.75 -> '2,705.75'; 0.00001234 -> '0.00001234'."""
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:,.2f}"
    return f"{value:.8f}".rstrip("0")


def _number(raw: str) -> float:
    from .spending import _number as parse

    return parse(re.sub(r"[^\d.,]", "", raw))


def page_text(url: str) -> str:
    from . import websearch

    _title, text = websearch.fetch(url)
    return re.sub(r"\s+", " ", text).strip()


# --- watches -----------------------------------------------------------------------------

def _next_id(items: list[dict]) -> int:
    return max((w["id"] for w in items), default=0) + 1


def add_watch(watch: dict) -> dict:
    items = WATCHES.load()
    watch["id"] = _next_id(items)
    watch["created"] = time.time()
    items.append(watch)
    WATCHES.save(items)
    reminders.board.add("watch", str(watch["id"]), time.time() + watch.get("every", 900))
    return watch


def remove_watch(which: str) -> str:
    items = WATCHES.load()
    keep = [w for w in items if str(w["id"]) != which.strip()]
    if len(keep) == len(items):
        return f"No watch {which}. /watches lists them."
    WATCHES.save(keep)
    for r in [r for r in reminders.board.items if r.kind == "watch" and r.text == which.strip()]:
        reminders.board.cancel(str(r.id))
    return f"Stopped watch {which}."


def check_watch(watch_id: int) -> str:
    """Run one watch. Returns a message when it has news, '' otherwise, and re-books it."""
    items = WATCHES.load()
    watch = next((w for w in items if w["id"] == watch_id), None)
    if watch is None:
        return ""
    message, keep = "", True
    try:
        kind = watch["type"]
        if kind == "alert":
            value, label = quote_value(watch["subject"])
            hit = value > watch["value"] if watch["op"] == ">" else value < watch["value"]
            if hit:
                message = f"📈 {label} is {value:,.4g} — {'above' if watch['op'] == '>' else 'below'} your {watch['value']:,g}."
                keep = False
        elif kind == "price":
            price = find_price(kit.get_text(watch["url"], limit=3_000_000))
            if price is not None:
                last = watch.get("last")
                if watch.get("target") and price <= watch["target"]:
                    message = f"🏷 {watch['name']} is now {price:,.2f} — at or below your {watch['target']:,g}.\n{watch['url']}"
                    keep = False
                elif last and price < last:
                    message = f"🏷 Price drop: {watch['name']} {last:,.2f} → {price:,.2f} ({(price - last) / last * 100:.0f}%).\n{watch['url']}"
                watch["last"] = price
        elif kind == "page":
            text = page_text(watch["url"])
            digest = hashlib.sha256(text.encode()).hexdigest()
            if watch.get("hash") and digest != watch["hash"]:
                old = watch.get("text", "")
                added = [l[1:].strip() for l in difflib.ndiff(re.split(r"(?<=[.!?])\s+", old), re.split(r"(?<=[.!?])\s+", text))
                         if l.startswith("+ ") and len(l) > 12][:3]
                message = f"🔔 {watch['url']} changed." + ("".join(f"\n  + {a[:140]}" for a in added) if added else "")
            watch["hash"], watch["text"] = digest, text[:20000]
        elif kind == "quake":
            since = watch.get("since") or (time.time() - 3600)
            found = kit.get_json("https://www.seismicportal.eu/fdsnws/event/1/query", {
                "format": "json", "lat": watch["lat"], "lon": watch["lon"], "maxradius": watch.get("radius_deg", 3),
                "minmag": watch["min"], "start": datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "limit": 5})
            quakes = [_quake(f, watch["lat"], watch["lon"]) for f in found.get("features", [])]
            if quakes:
                message = "🌍 Earthquake:\n" + "\n".join(q["line"] for q in quakes[:3])
                watch["since"] = max(q["epoch"] for q in quakes) + 1
            else:
                watch["since"] = time.time() - 120
    except Exception:
        message = ""
    watch["checked"] = time.time()
    if keep:
        WATCHES.save([watch if w["id"] == watch_id else w for w in items])
        reminders.board.add("watch", str(watch_id), time.time() + watch.get("every", 900))
    else:
        WATCHES.save([w for w in items if w["id"] != watch_id])
    return message


def _quake(feature: dict, lat: float, lon: float) -> dict:
    p = feature.get("properties", {})
    when = datetime.fromisoformat(str(p.get("time", "")).replace("Z", "+00:00"))
    epoch = when.timestamp()
    km = distance_km(lat, lon, float(p.get("lat", 0)), float(p.get("lon", 0)))
    place = str(p.get("flynn_region", "")).title()
    return {"epoch": epoch, "mag": float(p.get("mag") or 0),
            "line": f"  M{float(p.get('mag') or 0):.1f}  {place}  · {km:,.0f} km away · depth {float(p.get('depth') or 0):.0f} km · "
                    f"{datetime.fromtimestamp(epoch):%d %b %H:%M} ({kit.ago(epoch)})"}


def prayer_times(lat: float, lon: float, day: date | None = None) -> dict[str, str]:
    day = day or date.today()
    data = kit.get_json(f"https://api.aladhan.com/v1/timings/{day:%d-%m-%Y}",
                        {"latitude": lat, "longitude": lon, "method": 13})
    timings = data["data"]["timings"]
    return {k: timings[k][:5] for k in ("Imsak", "Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")}


def next_prayer(lat: float, lon: float, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or datetime.now()
    for offset in (0, 1):
        day = now.date() + timedelta(days=offset)
        for name, clock in prayer_times(lat, lon, day).items():
            if name in {"Imsak", "Sunrise"}:
                continue
            hour, minute = map(int, clock.split(":"))
            moment = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
            if moment > now:
                return name, moment
    raise kit.KitError("No prayer time found.")


class Live:
    @command("prayer", "namaz", "ezan", group=G, usage="/prayer [city] · /prayer alerts on|off",
             help="today's prayer times (Diyanet method)")
    def prayer(self, args: str, routed: bool = False):
        text = args.strip()
        low = text.lower()
        if low.startswith(("alerts", "alert", "remind", "hatırlat")):
            on = not low.endswith(("off", "kapat"))
            reminders.board.cancel_kind("prayer")
            if not on:
                return "Prayer alerts off."
            try:
                label, lat, lon = _place("")
                name, moment = next_prayer(lat, lon)
            except kit.KitError as exc:
                return str(exc)
            reminders.board.add("prayer", f"{lat},{lon},{name}", moment.timestamp())
            return f"🕌 Prayer alerts on for {label}. Next: {PRAYERS_TR.get(name, name)} at {moment:%H:%M}."
        try:
            label, lat, lon = _place(text)
            times = prayer_times(lat, lon)
            name, moment = next_prayer(lat, lon)
        except kit.KitError as exc:
            return str(exc)
        turkish = i18n.current() == "tr"
        lines = [f"🕌 {label} — {date.today():%d.%m.%Y}"]
        for key, clock in times.items():
            shown = f"{PRAYERS_TR[key]}" if turkish else f"{key} ({PRAYERS_TR[key]})"
            lines.append(f"  {shown:<22} {clock}")
        left = moment - datetime.now()
        lines.append(f"\nNext: {PRAYERS_TR.get(name, name)} at {moment:%H:%M}, in "
                     f"{reminders.describe_seconds(left.total_seconds())}.  /prayer alerts on")
        return "\n".join(lines)

    @command("quake", "quakes", "deprem", "earthquake", group=G, usage="/quake [city] · /quake alerts on [4.5]",
             help="recent earthquakes near you, and alerts")
    def quakes(self, args: str, routed: bool = False):
        text = args.strip()
        low = text.lower()
        if low.startswith(("alerts", "alert")):
            for w in [w for w in WATCHES.load() if w["type"] == "quake"]:
                remove_watch(str(w["id"]))
            if low.endswith("off"):
                return "Earthquake alerts off."
            m = re.search(r"(\d(?:\.\d)?)", low)
            minimum = float(m.group(1)) if m else 4.0
            try:
                label, lat, lon = _place("")
            except kit.KitError as exc:
                return str(exc)
            add_watch({"type": "quake", "lat": lat, "lon": lon, "min": minimum, "radius_deg": 3.5, "since": time.time(),
                       "every": 180})
            return f"🌍 I'll tell you about any M{minimum:g}+ earthquake within ~400 km of {label} (checked every 3 minutes while I'm open)."
        try:
            label, lat, lon = _place(text)
            found = kit.get_json("https://www.seismicportal.eu/fdsnws/event/1/query", {
                "format": "json", "lat": lat, "lon": lon, "maxradius": 5, "minmag": 2.5, "limit": 10, "orderby": "time"})
        except kit.KitError as exc:
            return str(exc)
        quakes = [_quake(f, lat, lon) for f in found.get("features", [])]
        if not quakes:
            return f"No M2.5+ earthquakes recently within ~550 km of {label}."
        return f"🌍 Latest earthquakes near {label} (EMSC):\n" + "\n".join(q["line"] for q in quakes) + \
            "\n/quake alerts on [4.5] to be told"

    @command("gold", "altin", "altın", group=G, usage="/gold", help="gram gold, quarter, ounce and silver prices")
    def gold(self, args: str, routed: bool = False):
        try:
            p = gold_prices()
        except (kit.KitError, KeyError) as exc:
            return f"Couldn't get gold prices: {exc}"
        return (f"🥇 Gram altın   {p['gram_try']:,.2f} ₺\n   Çeyrek ≈     {p['quarter_try']:,.0f} ₺  (gold value only; shops add workmanship)\n"
                f"   Ons          ${p['ounce_usd']:,.2f}\n🥈 Gram gümüş   {p['silver_gram_try']:,.2f} ₺\n"
                f"(spot price × USD/TRY {p['usd_try']:.2f}; jewellers' buy/sell prices differ)")

    @command("crypto", "coin", group=G, usage="/crypto [btc eth sol]", help="crypto prices in USD and TRY")
    def crypto(self, args: str, routed: bool = False):
        symbols = re.findall(r"[a-zA-Z0-9-]+", args) or ["btc", "eth", "sol"]
        try:
            prices = crypto_prices(symbols[:10])
        except kit.KitError as exc:
            return str(exc)
        if not prices:
            return f"CoinGecko doesn't know {', '.join(symbols)}. Try btc, eth, sol, or the coin's full name."
        lines = ["🪙 Crypto (CoinGecko)"]
        for symbol, p in prices.items():
            change = p.get("usd_24h_change") or 0
            lines.append(f"  {symbol.upper():<6} ${_price(p['usd'])}   {_price(p['try'])} ₺   {'▲' if change >= 0 else '▼'} {abs(change):.1f}% 24h")
        return "\n".join(lines) + "\n(Prices only — not financial advice.)"

    @command("stock", "stocks", "hisse", group=G, usage="/stock <ticker>", help="stock quotes (BIST, NASDAQ, …)")
    def stock(self, args: str, routed: bool = False):
        symbols = re.findall(r"[\w.^-]+", args)
        if not symbols:
            return "Usage: /stock <ticker> [more]   e.g. /stock THYAO ASELS AAPL ^GSPC"
        lines = []
        for symbol in symbols[:6]:
            try:
                q = stock_quote(symbol)
            except kit.KitError as exc:
                lines.append(f"  {exc}")
                continue
            change = (q["price"] - q["previous"]) / q["previous"] * 100 if q["previous"] else 0
            lines.append(f"  {q['symbol']:<10} {q['price']:,.2f} {q['currency']}  {'▲' if change >= 0 else '▼'} {abs(change):.2f}%  {q['name'][:40]}")
        return "📊 Quotes (Yahoo Finance, may be delayed):\n" + "\n".join(lines) + "\n(Prices only — not financial advice.)"

    @command("holidays", "tatil", group=G, usage="/holidays [country] [year]", help="public holidays")
    def holidays(self, args: str, routed: bool = False):
        text = args.strip()
        year = int(m.group(0)) if (m := re.search(r"\b20\d{2}\b", text)) else date.today().year
        country = (re.sub(r"\b20\d{2}\b", "", text).strip() or "TR").upper()[:2]
        try:
            items = kit.get_json(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}")
        except kit.KitError:
            return f"No holiday list for '{country}'. Use a two-letter country code: TR, DE, US, GB…"
        today = date.today()
        lines = [f"🎉 Public holidays {country} {year}:"]
        upcoming_marked = False
        for h in items:
            day = date.fromisoformat(h["date"])
            mark = ""
            if day >= today and not upcoming_marked:
                mark, upcoming_marked = f"   ← next, in {(day - today).days} days", True
            lines.append(f"  {day:%a %d %b}  {h['localName']}" + (f" ({h['name']})" if h['name'] != h['localName'] else "") + mark)
        if country == "TR":
            lines.append("(Ramazan/Kurban Bayramı arife days are half days.)")
        return "\n".join(lines)

    @command("news", "haber", group=G, usage="/news <topic> [summary]", help="latest headlines on any topic")
    def news(self, args: str, routed: bool = False):
        text = args.strip()
        summary = bool(re.search(r"\s+(summary|summarize|summarise|özet)$", text, re.I))
        topic = re.sub(r"\s+(summary|summarize|summarise|özet)$", "", text, flags=re.I).strip()
        if not topic:
            return "Usage: /news <topic> [summary]   e.g. /news yapay zeka   ·   /news Galatasaray summary"
        turkish = i18n.current() == "tr" or bool(re.search(r"[çğıöşüÇĞİÖŞÜ]", topic))
        # "when:7d" keeps it to the last week; Google otherwise ranks months-old
        # stories first.
        params = {"q": f"{topic} when:7d", "hl": "tr" if turkish else "en-US", "gl": "TR" if turkish else "US",
                  "ceid": "TR:tr" if turkish else "US:en"}
        try:
            feed = kit.get_text("https://news.google.com/rss/search?" + urllib.parse.urlencode(params))
        except kit.KitError as exc:
            return str(exc)
        found = []
        for block in re.findall(r"<item>(.*?)</item>", feed, re.S)[:40]:
            title = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r"<title>(.*?)</title>", block, re.S) or [None, ""])[1]))
            when = (re.search(r"<pubDate>(.*?)</pubDate>", block) or [None, ""])[1]
            link = (re.search(r"<link>(.*?)</link>", block) or [None, ""])[1]
            try:
                epoch = parsedate_to_datetime(when).timestamp()
            except (TypeError, ValueError):
                epoch = 0.0
            found.append((epoch, title.strip(), link.strip()))
        found.sort(key=lambda item: -item[0])           # newest first
        items = [(title, kit.ago(epoch) if epoch else "", link) for epoch, title, link in found[:10]]
        if not items:
            return f"No news found for '{topic}'."
        listing = "\n".join(f"  • {t}  ({a})" for t, a, _ in items)
        if summary:
            from . import shield

            wrapped, _ = shield.wrap("\n".join(t for t, _, _ in items), "news headlines")
            brief = self.brain.ask_once(f"{shield.RULE}\n\nIn 3-4 sentences, what is the news about '{topic}' "
                                        f"according to these headlines? Same language as the headlines.\n\n{wrapped}")
            return f"📰 {topic}\n\n{brief}\n\n{listing}"
        return f"📰 {topic} — latest:\n{listing}\n\n/news {topic} summary for a summary · {items[0][2]}"

    @command("air", "aqi", group=G, usage="/air [city]", help="air quality (AQI, PM2.5)")
    def air(self, args: str, routed: bool = False):
        try:
            label, lat, lon = _place(args)
            data = kit.get_json("https://air-quality-api.open-meteo.com/v1/air-quality", {
                "latitude": lat, "longitude": lon, "current": "european_aqi,us_aqi,pm2_5,pm10,ozone,nitrogen_dioxide"})
        except kit.KitError as exc:
            return str(exc)
        c = data.get("current", {})
        aqi = c.get("european_aqi") or 0
        level = next(n for limit, n in ((20, "Good 😊"), (40, "Fair 🙂"), (60, "Moderate 😐"), (80, "Poor 😷"),
                                        (100, "Very poor 😷"), (1e9, "Extremely poor ☠")) if aqi <= limit)
        advice = "" if aqi <= 40 else "\nSensitive people should limit long outdoor exercise." if aqi <= 80 else \
            "\nAvoid outdoor exercise; keep windows closed; a mask helps outside."
        return (f"🌫 Air quality in {label}: {level} (European AQI {aqi:.0f}, US AQI {c.get('us_aqi', 0):.0f})\n"
                f"  PM2.5 {c.get('pm2_5', 0):.1f} µg/m³ · PM10 {c.get('pm10', 0):.1f} · O₃ {c.get('ozone', 0):.0f} · NO₂ {c.get('nitrogen_dioxide', 0):.0f}"
                + advice)

    @command("sun", "sunrise", "sunset", group=G, usage="/sun [city]", help="sunrise, sunset and daylight")
    def sun(self, args: str, routed: bool = False):
        try:
            label, lat, lon = _place(args)
            data = kit.get_json(weather.FORECAST, {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
                                                   "daily": "sunrise,sunset,daylight_duration"})
        except kit.KitError as exc:
            return str(exc)
        d = data["daily"]
        rise, set_ = datetime.fromisoformat(d["sunrise"][0]), datetime.fromisoformat(d["sunset"][0])
        tomorrow = datetime.fromisoformat(d["sunset"][1])
        daylight = d["daylight_duration"][0]
        change = (d["daylight_duration"][1] - daylight) / 60
        return (f"🌅 {label}: sunrise {rise:%H:%M}, sunset {set_:%H:%M} — {reminders.describe_seconds(daylight)} of daylight.\n"
                f"  Golden hour from about {set_ - timedelta(hours=1):%H:%M}. Tomorrow's sunset {tomorrow:%H:%M} "
                f"({'+' if change >= 0 else '−'}{abs(change):.1f} min of daylight).")

    # --- watches ------------------------------------------------------------------------

    @command("alert", group=G, usage="/alert usd > 35 · /alert btc < 80000 · /alert gold > 4000",
             help="tells you when a price crosses a line")
    def alert(self, args: str, routed: bool = False):
        text = args.strip().lower()
        if text.startswith(("delete", "remove", "stop")):
            return remove_watch(text.split()[-1])
        m = re.fullmatch(r"(.+?)\s*(>|<|above|below|over|under|üstü|altı)\s*([\d.,]+)", text)
        if not m:
            return "Usage: /alert <what> > <value>   e.g. /alert usd > 35 · /alert eur/usd < 1.05 · /alert btc > 100000 · /alert thyao > 300"
        op = ">" if m.group(2) in {">", "above", "over", "üstü"} else "<"
        target = float(m.group(3).replace(",", ""))
        try:
            value, label = quote_value(m.group(1))
        except (kit.KitError, KeyError, Exception) as exc:
            return f"I can't price '{m.group(1)}': {exc}"
        if (value > target) if op == ">" else (value < target):
            return f"{label} is already {value:,.4g} — {'above' if op == '>' else 'below'} {target:,g}."
        watch = add_watch({"type": "alert", "subject": m.group(1), "op": op, "value": target, "every": 900})
        return (f"🔔 Alert {watch['id']}: when {label} goes {'above' if op == '>' else 'below'} {target:,g} "
                f"(now {value:,.4g}). Checked every 15 minutes while I'm open. /watches lists them.")

    @command("pricewatch", group=G, usage="/pricewatch <product link> [below 1500]",
             help="tells you when a product's price drops")
    def price_watch(self, args: str, routed: bool = False):
        m = re.match(r"(https?://\S+)(?:\s+(?:below|under|<|altında)\s*([\d.,]+))?", args.strip(), re.I)
        if not m:
            return "Usage: /pricewatch <product link> [below <price>]"
        url = m.group(1)
        if not security.permissions.ask(security.NETWORK, url, context="/pricewatch"):
            return "Denied."
        try:
            page = kit.get_text(url, limit=3_000_000)
        except kit.KitError as exc:
            return str(exc)
        price = find_price(page)
        if price is None:
            return "I couldn't find a price on that page (some shops hide it from anything but a browser)."
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        name = html.unescape(title.group(1)).strip()[:80] if title else url
        target = float(m.group(2).replace(",", "")) if m.group(2) else 0
        watch = add_watch({"type": "price", "url": url, "name": name, "last": price, "target": target, "every": 4 * 3600})
        return (f"🏷 Watching {name}: now {price:,.2f}." + (f" I'll tell you at {target:,g} or less." if target else
                " I'll tell you whenever it drops.") + f" (Checked every 4 hours while I'm open; watch {watch['id']}.)")

    @command("watchpage", group=G, usage="/watchpage <link> [every 1h]", help="tells you when a web page changes")
    def watch_page(self, args: str, routed: bool = False):
        m = re.match(r"(https?://\S+)(?:\s+every\s+(\d+)\s*(m|min|h|hours?))?", args.strip(), re.I)
        if not m:
            return "Usage: /watchpage <link> [every 30m|2h]   e.g. a results page, a job board, a course announcement"
        every = int(m.group(2)) * (60 if m.group(3).lower().startswith("m") else 3600) if m.group(2) else 3600
        url = m.group(1)
        if not security.permissions.ask(security.NETWORK, url, context="/watchpage"):
            return "Denied."
        try:
            text = page_text(url)
        except Exception as exc:
            return f"Couldn't read the page: {exc}"
        watch = add_watch({"type": "page", "url": url, "hash": hashlib.sha256(text.encode()).hexdigest(),
                           "text": text[:20000], "every": max(600, every)})
        return f"👀 Watching {url} every {reminders.describe_seconds(watch['every'])}. I'll tell you when it changes (watch {watch['id']})."

    @command("watches", group=G, usage="/watches · /watches stop <n>", help="your alerts and watches")
    def watches(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower().startswith(("stop", "delete", "remove")):
            return remove_watch(text.split()[-1])
        items = WATCHES.load()
        if not items:
            return "No watches. /alert, /pricewatch, /watchpage and /quake alerts on add them."
        lines = ["Watches (checked while JARVIS is open):"]
        for w in items:
            what = {"alert": lambda: f"{w['subject']} {w['op']} {w['value']:,g}",
                    "price": lambda: f"price of {w['name'][:50]} (last {w.get('last', 0):,.2f})",
                    "page": lambda: f"changes to {w['url'][:60]}",
                    "quake": lambda: f"earthquakes M{w['min']:g}+ nearby"}[w["type"]]()
            checked = f", checked {kit.ago(w['checked'])}" if w.get("checked") else ""
            lines.append(f"  {w['id']}. {what}{checked}")
        lines.append("/watches stop <n>")
        return "\n".join(lines)

    # --- what the reminder board hands back ----------------------------------------------

    def live_fire(self, item) -> str:
        """Work done when a 'watch', 'prayer' or 'word' item comes due. Returns news or ''."""
        if item.kind == "watch":
            try:
                return check_watch(int(item.text))
            except ValueError:
                return ""
        if item.kind == "prayer":
            lat, lon, current = (item.text.split(",") + ["", "", ""])[:3]
            try:
                name, moment = next_prayer(float(lat), float(lon), datetime.fromtimestamp(item.due) + timedelta(minutes=1))
                reminders.board.add("prayer", f"{lat},{lon},{name}", moment.timestamp())
            except Exception:
                reminders.board.add("prayer", item.text, time.time() + 3600)
            if time.time() - item.due > 600:
                return ""          # caught up after a restart; don't announce an old one
            return f"🕌 {PRAYERS_TR.get(current, 'Prayer')} time — {datetime.fromtimestamp(item.due):%H:%M}."
        if item.kind == "word":
            reminders.board.add("word", "", item.due + 86400)
            return self.word_of_the_day("")
        return ""
