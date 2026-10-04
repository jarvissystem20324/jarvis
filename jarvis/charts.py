"""Charts drawn with Pillow: bar, column, line, area, pie and doughnut (10.0).

One renderer for the Design page's chart element, Excel chart previews and
the money and health pages, so a chart looks the same wherever it appears.
No plotting library: the axes, ticks and labels are a few hundred lines, and
matplotlib would add tens of megabytes to the download for them.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

KINDS = ("bar", "column", "line", "area", "pie", "doughnut")
PALETTE = ["#4f8ef7", "#f7a14f", "#4fd18e", "#e85d75", "#a77cf2", "#f2d24f", "#4fd1d9", "#9aa5b1"]


def _font(size: int, bold: bool = False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), ("arialbd.ttf" if bold else "arial.ttf"),
                 "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick values covering low..high, like a spreadsheet would choose."""
    if high <= low:
        high = low + 1
    span = high - low
    raw = span / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=magnitude * 10)
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 0.001:
        ticks.append(round(value, 10))
        value += step
    if ticks[-1] < high:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def short(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= limit:
            return f"{sign}{value / limit:.1f}".rstrip("0").rstrip(".") + suffix
    if value == int(value):
        return f"{sign}{int(value)}"
    return f"{sign}{value:.2f}".rstrip("0").rstrip(".")


def render(kind: str, labels: list[str], series: dict[str, list[float]], size=(900, 560), title: str = "",
           colors: list[str] | None = None, background: str = "#ffffff", text: str = "#1f2430",
           grid: str = "#e3e7ee", legend: bool = True, scale: int = 2) -> Image.Image:
    """The chart as an RGBA image (drawn at `scale`× and reduced, for smooth edges)."""
    kind = kind if kind in KINDS else "column"
    colors = colors or PALETTE
    w, h = size[0] * scale, size[1] * scale
    transparent = background in {"", "none", "transparent"}
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0) if transparent else _rgb(background) + (255,))
    draw = ImageDraw.Draw(image)
    s = scale
    names = list(series)
    values = [[float(v or 0) for v in series[n]] for n in names]
    n_points = max((len(v) for v in values), default=0)
    labels = (list(labels) + [""] * n_points)[:n_points]
    top = 16 * s
    if title:
        f = _font(26 * s, True)
        draw.text((w / 2, top), title, fill=text, font=f, anchor="ma")
        top += 44 * s
    small = _font(15 * s)
    if kind in {"pie", "doughnut"}:
        data = values[0] if values else []
        total = sum(max(0.0, v) for v in data) or 1.0
        legend_w = 260 * s if legend else 0
        radius = min(w - legend_w - 60 * s, h - top - 30 * s) / 2
        cx, cy = 30 * s + radius, top + (h - top) / 2
        angle = -90.0
        for i, v in enumerate(data):
            sweep = 360 * max(0.0, v) / total
            draw.pieslice((cx - radius, cy - radius, cx + radius, cy + radius), angle, angle + sweep,
                          fill=colors[i % len(colors)], outline=background if not transparent else None,
                          width=3 * s)
            if sweep > 12:
                mid = math.radians(angle + sweep / 2)
                r = radius * (0.78 if kind == "doughnut" else 0.62)
                draw.text((cx + r * math.cos(mid), cy + r * math.sin(mid)), f"{100 * v / total:.0f}%",
                          fill="#ffffff", font=_font(16 * s, True), anchor="mm")
            angle += sweep
        if kind == "doughnut":
            hole = radius * 0.55
            draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole),
                         fill=(0, 0, 0, 0) if transparent else _rgb(background) + (255,))
            draw.text((cx, cy), short(total), fill=text, font=_font(26 * s, True), anchor="mm")
        if legend:
            y = top + 20 * s
            for i, name in enumerate(labels):
                draw.rectangle((w - legend_w, y, w - legend_w + 18 * s, y + 18 * s), fill=colors[i % len(colors)])
                draw.text((w - legend_w + 28 * s, y + 9 * s), f"{name}  ({short(data[i])})"[:30], fill=text,
                          font=small, anchor="lm")
                y += 30 * s
        return image.reduce(scale)

    flat = [v for row in values for v in row] or [0.0]
    low = min(0.0, min(flat))
    high = max(flat) if max(flat) > low else low + 1
    ticks = nice_ticks(low, high)
    low, high = ticks[0], ticks[-1]
    legend_h = (34 * s if legend and len(names) > 1 else 0)
    left, right, bottom = 70 * s, w - 24 * s, h - 46 * s - legend_h
    horizontal = kind == "bar"
    if horizontal:
        left = 150 * s
    plot_w, plot_h = right - left, bottom - top

    def pos(value: float) -> float:
        frac = (value - low) / (high - low)
        return left + frac * plot_w if horizontal else bottom - frac * plot_h

    for tick in ticks:
        p = pos(tick)
        if horizontal:
            draw.line((p, top, p, bottom), fill=grid, width=s)
            draw.text((p, bottom + 8 * s), short(tick), fill=text, font=small, anchor="ma")
        else:
            draw.line((left, p, right, p), fill=grid, width=s)
            draw.text((left - 10 * s, p), short(tick), fill=text, font=small, anchor="rm")
    zero = pos(0.0)
    count = max(1, n_points)
    if kind in {"column", "bar"}:
        band = (plot_h if horizontal else plot_w) / count
        group = band * 0.72
        each = group / max(1, len(names))
        for i in range(n_points):
            for k, row in enumerate(values):
                v = row[i] if i < len(row) else 0.0
                start = (top if horizontal else left) + i * band + (band - group) / 2 + k * each
                fill = colors[k % len(colors)]
                if horizontal:
                    draw.rectangle((min(zero, pos(v)), start, max(zero, pos(v)), start + each - 2 * s), fill=fill)
                else:
                    draw.rectangle((start, min(zero, pos(v)), start + each - 2 * s, max(zero, pos(v))), fill=fill)
            centre = (top if horizontal else left) + i * band + band / 2
            if horizontal:
                draw.text((left - 10 * s, centre), labels[i][:18], fill=text, font=small, anchor="rm")
            else:
                draw.text((centre, bottom + 8 * s), labels[i][:14], fill=text, font=small, anchor="ma")
    else:
        step = plot_w / max(1, count - 1) if count > 1 else 0
        for k, row in enumerate(values):
            pts = [(left + (i * step if count > 1 else plot_w / 2), pos(v)) for i, v in enumerate(row)]
            colour = colors[k % len(colors)]
            if kind == "area" and len(pts) > 1:
                fill = _rgb(colour) + (90,)
                layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
                ImageDraw.Draw(layer).polygon(pts + [(pts[-1][0], zero), (pts[0][0], zero)], fill=fill)
                image.alpha_composite(layer)
                draw = ImageDraw.Draw(image)
            if len(pts) > 1:
                draw.line(pts, fill=colour, width=4 * s, joint="curve")
            for x, y in pts:
                draw.ellipse((x - 5 * s, y - 5 * s, x + 5 * s, y + 5 * s), fill=colour)
        every = max(1, math.ceil(count / 12))
        for i in range(0, n_points, every):
            x = left + (i * step if count > 1 else plot_w / 2)
            draw.text((x, bottom + 8 * s), labels[i][:12], fill=text, font=small, anchor="ma")
    draw.line((left, top, left, bottom), fill=text, width=s)
    draw.line((left, bottom, right, bottom), fill=text, width=s)
    if legend and len(names) > 1:
        x = left
        y = h - legend_h + 6 * s
        for k, name in enumerate(names):
            draw.rectangle((x, y, x + 18 * s, y + 18 * s), fill=colors[k % len(colors)])
            draw.text((x + 26 * s, y + 9 * s), name[:24], fill=text, font=small, anchor="lm")
            x += (40 + 9 * min(24, len(name))) * s
    return image.reduce(scale)


def parse_table(text: str) -> tuple[list[str], dict[str, list[float]]]:
    """'Q1, 10, 12\\nQ2, 14, 9' (optionally a header row) → labels and series."""
    rows = [[c.strip() for c in line.replace("\t", ",").replace(";", ",").split(",")]
            for line in (text or "").strip().splitlines() if line.strip()]
    if not rows:
        return [], {}

    def number(cell: str) -> float | None:
        try:
            return float(cell.replace("%", "").replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    header = None
    if rows and all(number(c) is None for c in rows[0][1:]) and len(rows) > 1:
        header = rows[0]
        rows = rows[1:]
    width = max(len(r) for r in rows)
    names = (header[1:] if header else [f"Series {i}" for i in range(1, width)])
    names = (names + [f"Series {i}" for i in range(len(names) + 1, width)])[:max(1, width - 1)]
    labels = [r[0] for r in rows]
    series = {name: [number(r[i + 1]) or 0.0 if i + 1 < len(r) else 0.0 for r in rows] for i, name in enumerate(names)}
    return labels, series
