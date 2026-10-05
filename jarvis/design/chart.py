"""Charts on a design: bar, horizontal bar, line, area, pie and doughnut,
drawn with Pillow so they look the same in the editor, the PNG and the PDF.
(PowerPoint export makes a real, editable PowerPoint chart instead.)

A chart's data is a small table, the way Excel holds it:

    [["",   "2025", "2026"],      <- the series' names
     ["Q1", "12",   "15"],        <- a label, then one number per series
     ["Q2", "18",   "21"]]

Cells are text so the table editor can hold anything; numbers are read
leniently — "1.250,5" and "1,250.5" are both 1250.5, "₺40" is 40.
"""

from __future__ import annotations

import math
import re

from PIL import Image, ImageDraw

from . import model

SERIES = ["#4f8ef7", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"]
LABELS = {"bar": "Bars", "hbar": "Bars across", "line": "Line", "area": "Area", "pie": "Pie", "doughnut": "Doughnut"}
AA = 2


def number(text) -> float | None:
    if isinstance(text, (int, float)):
        return float(text)
    t = re.sub(r"[^\d,.\-]", "", str(text or ""))
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", t) else t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3}){2,}", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse(rows: list[list[str]]) -> tuple[list[str], list[tuple[str, list[float | None]]]]:
    """(labels, [(series name, values)]) — series with no numbers at all are left out."""
    rows = [list(r) for r in rows or [] if any(str(c).strip() for c in r)]
    if not rows:
        return [], []
    header, body = rows[0], rows[1:]
    width = max(len(r) for r in rows)
    labels = [str(r[0]) if r else "" for r in body]
    series = []
    for col in range(1, width):
        values = [number(r[col]) if col < len(r) else None for r in body]
        if any(v is not None for v in values):
            name = str(header[col]).strip() if col < len(header) and str(header[col]).strip() else f"Series {col}"
            series.append((name, values))
    return labels, series


def colours(el: dict, count: int) -> list[str]:
    first = el.get("fill") or SERIES[0]
    rest = [c for c in SERIES if c != first]
    out = [first] + rest
    while len(out) < count:
        out += out
    return out[:max(1, count)]


def nice_step(span: float, ticks: int = 5) -> float:
    raw = max(span, 1e-9) / ticks
    exp = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 2.5, 5, 10):
        if raw <= f * exp:
            return f * exp
    return 10 * exp


def short(value: float) -> str:
    a = abs(value)
    if a >= 1e9:
        return f"{value / 1e9:.1f}B".replace(".0B", "B")
    if a >= 1e6:
        return f"{value / 1e6:.1f}M".replace(".0M", "M")
    if a >= 10_000:
        return f"{value / 1e3:.1f}k".replace(".0k", "k")
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _rgba(colour: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (*model.rgb(colour), alpha)


def render(el: dict, scale: float) -> Image.Image:
    from .render import face

    w, h = max(2, int(round(el["w"] * scale))), max(2, int(round(el["h"] * scale)))
    W, H = w * AA, h * AA
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    s = scale * AA
    fs = max(6.0, el.get("size", 26) * s)
    family = el.get("font") or "Segoe UI"
    font = face(family, fs)
    bold = face(family, fs * 1.3, bold=True)
    ink = el.get("color") or "#1f2430"
    labels, series = parse(el.get("rows") or [])
    kind = el.get("chart", "bar")
    top, bottom, left, right = fs * 0.4, H - fs * 0.4, fs * 0.4, W - fs * 0.4
    if el.get("title"):
        title = el["title"]
        tw = bold.getlength(title)
        bold.draw(draw, (W - tw) / 2, top + bold.getmetrics()[0], title, _rgba(ink))
        top += fs * 1.3 * 1.5
    if not series:
        msg = "Add numbers to the chart's table"
        font.draw(draw, (W - font.getlength(msg)) / 2, (top + bottom) / 2, msg, _rgba(ink, 150))
        return image.reduce(AA)
    pie = kind in {"pie", "doughnut"}
    names = labels if pie else [n for n, _ in series]
    fills = colours(el, len(names))
    if el.get("legend", True) and (pie or len(series) > 1):
        bottom = _legend(draw, font, names, fills, left, right, bottom, fs, ink)
    if pie:
        _pie(draw, font, series[0][1], labels, fills, (left, top, right, bottom), kind == "doughnut",
             el.get("labels", False), fs)
    elif kind == "hbar":
        _hbars(draw, font, labels, series, fills, (left, top, right, bottom), fs, ink, el.get("labels", False))
    else:
        _columns(image, draw, font, labels, series, fills, (left, top, right, bottom), fs, ink, kind,
                 el.get("labels", False))
    return image.reduce(AA)


def _legend(draw, font, names, fills, left, right, bottom, fs, ink) -> float:
    box = fs * 0.75
    widths = [box + fs * 0.4 + font.getlength(n) + fs * 1.2 for n in names]
    rows, row, used = [], [], 0.0
    for i, width in enumerate(widths):
        if row and used + width > right - left:
            rows.append(row)
            row, used = [], 0.0
        row.append(i)
        used += width
    rows.append(row)
    line_h = fs * 1.5
    y = bottom - line_h * len(rows)
    for row in rows:
        total = sum(widths[i] for i in row) - fs * 1.2
        x = left + (right - left - total) / 2
        for i in row:
            draw.rounded_rectangle((x, y + (line_h - box) / 2, x + box, y + (line_h + box) / 2), radius=box * 0.2,
                                   fill=_rgba(fills[i]))
            font.draw(draw, x + box + fs * 0.4, y + line_h / 2 + font.getmetrics()[0] * 0.38, names[i], _rgba(ink))
            x += widths[i]
        y += line_h
    return bottom - line_h * len(rows) - fs * 0.5


def _scale(values: list[float]) -> tuple[float, float, float]:
    lo, hi = min(values + [0.0]), max(values + [0.0])
    if hi == lo:
        hi = lo + 1
    step = nice_step(hi - lo)
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


def _fit(font, text: str, width: float) -> str:
    if font.getlength(text) <= width:
        return text
    while len(text) > 1 and font.getlength(text + "…") > width:
        text = text[:-1]
    return text + "…"


def _columns(image, draw, font, labels, series, fills, box, fs, ink, kind, show_values) -> None:
    left, top, right, bottom = box
    values = [v for _, vals in series for v in vals if v is not None]
    lo, hi, step = _scale(values)
    ticks = [lo + i * step for i in range(int(round((hi - lo) / step)) + 1)]
    label_w = max(font.getlength(short(t)) for t in ticks) + fs * 0.6
    plot = (left + label_w, top + fs * 0.6, right, bottom - fs * 1.6)
    px0, py0, px1, py1 = plot

    def y_of(v: float) -> float:
        return py1 - (v - lo) / (hi - lo) * (py1 - py0)

    ascent = font.getmetrics()[0]
    for t in ticks:
        y = y_of(t)
        draw.line([(px0, y), (px1, y)], fill=_rgba(ink, 60 if t else 140), width=max(1, int(fs * 0.06)))
        text = short(t)
        font.draw(draw, px0 - fs * 0.3 - font.getlength(text), y + ascent * 0.38, text, _rgba(ink, 190))
    n = max(1, len(labels))
    group = (px1 - px0) / n
    for i, label in enumerate(labels):
        text = _fit(font, label, group * 0.95)
        font.draw(draw, px0 + group * (i + 0.5) - font.getlength(text) / 2, py1 + fs * 0.25 + ascent, text,
                  _rgba(ink, 210))
    zero = y_of(max(lo, min(0.0, hi)))
    if kind == "bar":
        width = group * 0.72 / len(series)
        for s, (_, vals) in enumerate(series):
            for i, v in enumerate(vals):
                if v is None:
                    continue
                x = px0 + group * i + group * 0.14 + width * s
                y = y_of(v)
                draw.rounded_rectangle((x + width * 0.06, min(y, zero), x + width * 0.94, max(y, zero)),
                                       radius=min(width * 0.18, abs(zero - y) / 2), fill=_rgba(fills[s]))
                if show_values:
                    text = short(v)
                    font.draw(draw, x + width / 2 - font.getlength(text) / 2, min(y, zero) - fs * 0.3, text,
                              _rgba(ink))
        return
    for s, (_, vals) in enumerate(series):
        points = [(px0 + group * (i + 0.5), y_of(v)) for i, v in enumerate(vals) if v is not None]
        if not points:
            continue
        if kind == "area" and len(points) > 1:
            area = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(area).polygon(points + [(points[-1][0], zero), (points[0][0], zero)],
                                         fill=_rgba(fills[s], 90))
            image.alpha_composite(area)
        width = max(2, int(fs * 0.16))
        if len(points) > 1:
            draw.line(points, fill=_rgba(fills[s]), width=width, joint="curve")
        r = fs * 0.22
        for x, y in points:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=_rgba(fills[s]), outline=(255, 255, 255, 255),
                         width=max(1, int(fs * 0.06)))
        if show_values:
            for (x, y), v in zip(points, [v for v in vals if v is not None]):
                text = short(v)
                font.draw(draw, x - font.getlength(text) / 2, y - fs * 0.45, text, _rgba(ink))


def _hbars(draw, font, labels, series, fills, box, fs, ink, show_values) -> None:
    left, top, right, bottom = box
    values = [v for _, vals in series for v in vals if v is not None]
    lo, hi, step = _scale(values)
    label_w = min((right - left) * 0.35, max((font.getlength(l) for l in labels), default=0) + fs * 0.6)
    plot = (left + label_w, top, right - fs * 1.2, bottom - fs * 1.4)
    px0, py0, px1, py1 = plot
    ascent = font.getmetrics()[0]

    def x_of(v: float) -> float:
        return px0 + (v - lo) / (hi - lo) * (px1 - px0)

    t = lo
    while t <= hi + step / 2:
        x = x_of(t)
        draw.line([(x, py0), (x, py1)], fill=_rgba(ink, 60 if t else 140), width=max(1, int(fs * 0.06)))
        text = short(t)
        font.draw(draw, x - font.getlength(text) / 2, py1 + fs * 0.2 + ascent, text, _rgba(ink, 190))
        t += step
    n = max(1, len(labels))
    group = (py1 - py0) / n
    height = group * 0.72 / len(series)
    zero = x_of(max(lo, min(0.0, hi)))
    for i, label in enumerate(labels):
        text = _fit(font, label, label_w - fs * 0.4)
        font.draw(draw, px0 - fs * 0.3 - font.getlength(text), py0 + group * (i + 0.5) + ascent * 0.38, text,
                  _rgba(ink, 210))
        for s, (_, vals) in enumerate(series):
            v = vals[i] if i < len(vals) else None
            if v is None:
                continue
            y = py0 + group * i + group * 0.14 + height * s
            x = x_of(v)
            draw.rounded_rectangle((min(x, zero), y + height * 0.06, max(x, zero), y + height * 0.94),
                                   radius=min(height * 0.18, abs(x - zero) / 2), fill=_rgba(fills[s]))
            if show_values:
                font.draw(draw, max(x, zero) + fs * 0.25, y + height / 2 + ascent * 0.38, short(v), _rgba(ink))


def _pie(draw, font, values, labels, fills, box, doughnut, show_values, fs) -> None:
    left, top, right, bottom = box
    parts = [(max(0.0, v or 0.0), i) for i, v in enumerate(values)]
    total = sum(v for v, _ in parts) or 1.0
    d = max(4.0, min(right - left, bottom - top))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    circle = (cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2)
    angle = -90.0
    ascent = font.getmetrics()[0]
    for v, i in parts:
        if v <= 0:
            continue
        sweep = v / total * 360
        draw.pieslice(circle, angle, angle + sweep, fill=_rgba(fills[i % len(fills)]), outline=(255, 255, 255, 255),
                      width=max(1, int(fs * 0.08)))
        if show_values and sweep > 12:
            mid = math.radians(angle + sweep / 2)
            r = d / 2 * (0.78 if doughnut else 0.62)
            text = f"{v / total * 100:.0f}%"
            ink = model.readable_on(fills[i % len(fills)])
            font.draw(draw, cx + r * math.cos(mid) - font.getlength(text) / 2, cy + r * math.sin(mid) + ascent * 0.38,
                      text, _rgba(ink))
        angle += sweep
    if doughnut:
        hole = d * 0.28
        draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=(0, 0, 0, 0))
