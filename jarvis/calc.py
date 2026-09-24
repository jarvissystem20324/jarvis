"""Exact answers: arithmetic, percentages, units, currency and dates.

A language model asked "what is 17.5% of 2,340" usually gets it right and
sometimes confidently does not. These are worked out here instead:

    /calc (12.5 * 4) ^ 2 / 3        2,340 * 17.5%        sqrt(2) * pi
    15% of 240                      what is 3 to the power of 8
    convert 5 miles to km           72 f in c            2 GB in MB
    100 usd to try                  1,500 lira in euros  (live ECB rates)
    days until 2026-12-31           how many days until christmas

The arithmetic is parsed with Python's own parser and evaluated by walking
the tree with a short list of allowed operations — never eval(), so nothing
typed here can run code. Currency rates come from the European Central
Bank's daily reference rates via Frankfurter (free, no key), with
open.er-api.com as a fallback; only the currency codes are sent.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
import time
import urllib.request
from datetime import date, datetime

from . import net


class CalcError(Exception):
    pass


# --- arithmetic ---------------------------------------------------------------

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "log": math.log, "log10": math.log10,
          "ln": math.log, "sin": math.sin, "cos": math.cos, "tan": math.tan, "floor": math.floor,
          "ceil": math.ceil, "exp": math.exp, "factorial": math.factorial, "min": min, "max": max}
_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise CalcError("That exponent is too large to be useful.")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        args = [_eval(a) for a in node.args]
        if node.func.id == "factorial" and (args[0] > 500 or args[0] != int(args[0])):
            raise CalcError("factorial needs a whole number up to 500.")
        return _FUNCS[node.func.id](*args)
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    raise CalcError("I can only do arithmetic here: + - * / ^ %, brackets and "
                    "sqrt, log, sin, cos, tan, round, abs, pi, e.")


def _normalise(expression: str) -> str:
    text = expression.strip().rstrip("=?").strip()
    text = text.replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)             # 2,340 -> 2340
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*%\s+of\s+", r"(\1/100)*", text, flags=re.I)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)     # 17.5% -> (17.5/100)
    words = {r"\bplus\b": "+", r"\bminus\b": "-", r"\btimes\b": "*", r"\bmultiplied by\b": "*",
             r"\bdivided by\b": "/", r"\bto the power of\b": "**", r"\bsquared\b": "**2",
             r"\bcubed\b": "**3", r"\bsquare root of\b": "sqrt", r"\bmod\b": "%", r"\bx\b": "*"}
    for pattern, symbol in words.items():
        text = re.sub(pattern, symbol, text, flags=re.I)
    return text


def evaluate(expression: str) -> float:
    text = _normalise(expression)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise CalcError(f"I couldn't read '{expression.strip()}' as a calculation.") from None
    try:
        return _eval(tree)
    except ZeroDivisionError:
        raise CalcError("That divides by zero.") from None
    except (OverflowError, ValueError) as exc:
        raise CalcError(f"That has no sensible answer ({exc}).") from None


def fmt(value: float) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    if abs(value) >= 1e12 or (value != 0 and abs(value) < 1e-6):
        return f"{value:.6g}"
    return f"{value:,.10f}".rstrip("0").rstrip(".")


# --- units --------------------------------------------------------------------

# Everything expressed in one base unit per dimension.
UNITS: dict[str, tuple[str, float]] = {}


def _add(dimension: str, factor: float, *names: str) -> None:
    for name in names:
        UNITS[name] = (dimension, factor)


_add("length", 1, "m", "meter", "meters", "metre", "metres", "metre")
_add("length", 1000, "km", "kilometer", "kilometers", "kilometre", "kilometres")
_add("length", 0.01, "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_add("length", 0.001, "mm", "millimeter", "millimeters")
_add("length", 1609.344, "mi", "mile", "miles")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 0.3048, "ft", "foot", "feet")
_add("length", 0.0254, "in", "inch", "inches")
_add("length", 1852, "nmi", "nautical mile", "nautical miles")
_add("mass", 1, "kg", "kilogram", "kilograms", "kilo", "kilos")
_add("mass", 0.001, "g", "gram", "grams")
_add("mass", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("mass", 0.028349523125, "oz", "ounce", "ounces")
_add("mass", 1000, "t", "tonne", "tonnes", "ton", "tons")
_add("mass", 6.35029318, "st", "stone", "stones")
_add("volume", 1, "l", "liter", "liters", "litre", "litres")
_add("volume", 0.001, "ml", "milliliter", "milliliters", "millilitre", "millilitres")
_add("volume", 3.785411784, "gal", "gallon", "gallons")
_add("volume", 0.946352946, "qt", "quart", "quarts")
_add("volume", 0.2365882365, "cup", "cups")
_add("volume", 0.0295735295625, "fl oz", "fluid ounce", "fluid ounces")
_add("speed", 1, "km/h", "kmh", "kph")
_add("speed", 1.609344, "mph")
_add("speed", 3.6, "m/s")
_add("speed", 1.852, "knot", "knots", "kn")
_add("data", 1, "b", "byte", "bytes")
_add("data", 1000, "kb", "kilobyte", "kilobytes")
_add("data", 1000 ** 2, "mb", "megabyte", "megabytes")
_add("data", 1000 ** 3, "gb", "gigabyte", "gigabytes")
_add("data", 1000 ** 4, "tb", "terabyte", "terabytes")
_add("data", 1024 ** 2, "mib")
_add("data", 1024 ** 3, "gib")
_add("time", 1, "s", "sec", "second", "seconds")
_add("time", 60, "min", "minute", "minutes")
_add("time", 3600, "h", "hr", "hour", "hours")
_add("time", 86400, "day", "days")
_add("time", 604800, "week", "weeks")
_add("area", 1, "m2", "sqm", "square meter", "square meters", "square metre", "square metres")
_add("area", 10000, "ha", "hectare", "hectares")
_add("area", 4046.8564224, "acre", "acres")
_add("area", 0.09290304, "sqft", "square foot", "square feet")
_add("area", 1e6, "km2", "square kilometer", "square kilometers")
TEMPERATURE = {"c": "C", "celsius": "C", "°c": "C", "f": "F", "fahrenheit": "F", "°f": "F",
               "k": "K", "kelvin": "K"}


def convert_units(value: float, source: str, target: str) -> tuple[float, str, str]:
    s, t = source.lower().strip(), target.lower().strip()
    if s in TEMPERATURE and t in TEMPERATURE:
        a, b = TEMPERATURE[s], TEMPERATURE[t]
        celsius = value if a == "C" else (value - 32) * 5 / 9 if a == "F" else value - 273.15
        out = celsius if b == "C" else celsius * 9 / 5 + 32 if b == "F" else celsius + 273.15
        return out, f"°{a}" if a != "K" else "K", f"°{b}" if b != "K" else "K"
    if s not in UNITS or t not in UNITS:
        raise CalcError(f"I don't know the unit '{source if s not in UNITS else target}'.")
    (dim_s, f_s), (dim_t, f_t) = UNITS[s], UNITS[t]
    if dim_s != dim_t:
        raise CalcError(f"{source} is a {dim_s} and {target} is a {dim_t}; they don't convert.")
    return value * f_s / f_t, source, target


# --- currency -----------------------------------------------------------------

CURRENCY_WORDS = {
    "lira": "TRY", "liras": "TRY", "tl": "TRY", "₺": "TRY", "try": "TRY",
    "dollar": "USD", "dollars": "USD", "$": "USD", "usd": "USD", "bucks": "USD",
    "euro": "EUR", "euros": "EUR", "€": "EUR", "eur": "EUR",
    "pound": "GBP", "pounds sterling": "GBP", "£": "GBP", "gbp": "GBP", "sterling": "GBP",
    "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY", "rupee": "INR", "rupees": "INR",
    "franc": "CHF", "francs": "CHF", "chf": "CHF", "ruble": "RUB", "rubles": "RUB",
}
_rates_cache: dict[str, tuple[float, dict, str]] = {}


def currency_code(word: str) -> str | None:
    w = word.lower().strip()
    if w in CURRENCY_WORDS:
        return CURRENCY_WORDS[w]
    if re.fullmatch(r"[a-z]{3}", w) and w not in UNITS and w not in {"the", "and", "for"}:
        return w.upper()
    return None


def _fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-desktop (currency)"})
    with net.urlopen(request, timeout=12) as response:
        return json.loads(response.read())


def rates(base: str) -> tuple[dict, str]:
    """(rates from `base`, as-of date). Cached for an hour."""
    cached = _rates_cache.get(base)
    if cached and time.time() - cached[0] < 3600:
        return cached[1], cached[2]
    try:
        data = _fetch(f"https://api.frankfurter.dev/v1/latest?base={base}")
        found, when = data.get("rates") or {}, str(data.get("date") or "")
        source = "European Central Bank"
    except Exception:
        found, when, source = {}, "", ""
    if not found:
        try:
            data = _fetch(f"https://open.er-api.com/v6/latest/{base}")
            found = data.get("rates") or {}
            when, source = str(data.get("time_last_update_utc") or "")[:16], "open.er-api.com"
        except Exception as exc:
            raise CalcError(f"Couldn't reach a currency service: {net.describe_ssl_error(exc) or exc}") from None
    if not found:
        raise CalcError(f"No exchange rates for {base}.")
    label = f"{source}, {when}".strip(", ")
    _rates_cache[base] = (time.time(), found, label)
    return found, label


def convert_currency(amount: float, source: str, target: str) -> tuple[float, str]:
    table, label = rates(source)
    if target not in table:
        raise CalcError(f"No rate from {source} to {target}.")
    return amount * float(table[target]), label


# --- dates ---------------------------------------------------------------------

HOLIDAYS = {"christmas": (12, 25), "new year": (1, 1), "new year's": (1, 1),
            "halloween": (10, 31), "valentine's day": (2, 14), "valentines": (2, 14),
            "cumhuriyet bayramı": (10, 29), "republic day": (10, 29)}


def days_until(text: str, today: date | None = None) -> str:
    today = today or date.today()
    t = text.lower().strip().rstrip("?")
    target = None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        target = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        m = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", t)
        if m:
            year = int(m.group(3)) if m.group(3) else today.year
            year += 2000 if year < 100 else 0
            target = date(year, int(m.group(2)), int(m.group(1)))
        else:
            for name, (month, day) in HOLIDAYS.items():
                if name in t:
                    target = date(today.year, month, day)
                    if target < today:
                        target = date(today.year + 1, month, day)
                    break
    if target is None:
        raise CalcError("Give me a date like 2026-12-31 or 31.12, or a holiday.")
    delta = (target - today).days
    when = target.strftime("%A %d %B %Y")
    if delta == 0:
        return f"{when} is today."
    if delta < 0:
        return f"{when} was {-delta:,} day{'s' if delta != -1 else ''} ago."
    weeks, days = divmod(delta, 7)
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
    return f"{delta:,} day{'s' if delta != 1 else ''} until {when}" + (
        f" ({plural(weeks, 'week')} and {plural(days, 'day')})." if weeks and days
        else f" ({plural(weeks, 'week')})." if weeks else ".")


# --- one entry point -------------------------------------------------------------

_CONVERT = re.compile(
    r"^(?:convert\s+|how\s+much\s+is\s+|what'?s\s+|what\s+is\s+)?"
    r"(-?[\d.,]+)\s*([^\d\s][\w°/$€£₺ ]*?)\s+(?:to|in|into|as)\s+([\w°/$€£₺ ]+?)\??$",
    re.I,
)


def solve(text: str) -> str:
    """Answer a calculation, conversion or date question. Raises CalcError."""
    t = " ".join(text.strip().split())
    t = re.sub(r"^(?:calculate|compute|what'?s|what\s+is|how\s+much\s+is)\s+", "", t, flags=re.I)
    if re.match(r"^(?:how\s+many\s+)?days?\s+(?:until|till|to|since)\b", t, re.I):
        return days_until(t)
    m = _CONVERT.match(t)
    if m:
        amount = float(m.group(1).replace(",", "")) if re.fullmatch(r"-?\d{1,3}(,\d{3})*(\.\d+)?|-?\d+(\.\d+)?", m.group(1)) \
            else float(m.group(1).replace(".", "").replace(",", "."))
        source, target = m.group(2).strip(), m.group(3).strip()
        s_code, t_code = currency_code(source), currency_code(target)
        if s_code and t_code and source.lower() not in UNITS and target.lower() not in UNITS:
            value, label = convert_currency(amount, s_code, t_code)
            return f"{fmt(round(amount, 2))} {s_code} = {value:,.2f} {t_code}   ({label})"
        value, s_label, t_label = convert_units(amount, source, target)
        return f"{fmt(amount)} {s_label} = {fmt(round(value, 6))} {t_label}"
    value = evaluate(t)
    return f"{t.rstrip('=?').strip()} = {fmt(value)}"


def looks_like_math(text: str) -> bool:
    """For plain-language routing: arithmetic or a conversion, nothing else."""
    t = text.strip().rstrip("?=").strip()
    t = re.sub(r"^(?:calculate|compute|what'?s|what\s+is|how\s+much\s+is)\s+", "", t, flags=re.I)
    m = _CONVERT.match(t)
    if m and len(t) < 60:
        # Both sides must be something convertible: "3pm istanbul in london"
        # is a time-zone question, not 3 of a unit called "pm istanbul".
        def known(word: str) -> bool:
            w = word.lower().strip()
            return w in UNITS or w in TEMPERATURE or (currency_code(w) is not None and " " not in w)
        return known(m.group(2)) and known(m.group(3))
    if re.match(r"^(?:how\s+many\s+)?days?\s+(?:until|till|since)\b", t, re.I):
        return True
    # Digits and operators only (plus a few function names and %).
    stripped = re.sub(r"\b(sqrt|pi|of|plus|minus|times|divided by|squared|cubed|mod|to the power of|x)\b", "", t, flags=re.I)
    return bool(re.fullmatch(r"[\d\s.,+\-*/^()%×÷]+", stripped)) and bool(re.search(r"\d\s*[-+*/^×÷%]", t))
