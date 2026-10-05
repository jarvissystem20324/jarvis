"""Draw a design page with Pillow — for the editor, the exports and previews.

Every element is drawn on its own transparent layer the size of its box,
then rotated about its centre and composited onto the page. Shapes and lines
are drawn at twice the size and scaled down, which is the cheapest way to get
smooth edges out of ImageDraw. Pictures are processed once per size and
cached, so dragging a photo around the editor doesn't redo its filter on
every mouse move.
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import fonts, model

AA = 2
LANCZOS = Image.Resampling.LANCZOS
_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))
# Dots per inch a design prints at, by format: A4 pages are 150 dpi, slides
# are 13.33 inches wide like PowerPoint's own 16:9.
INCHES_WIDE = {"slides": 13.333, "diagram": 13.333, "poster": 8.27, "a4_landscape": 11.69, "invitation": 5.0,
               "card": 7.0, "book": 6.0, "ticket": 7.5}


# --- the page ------------------------------------------------------------------------------

def render_page(design: dict, index: int = 0, scale: float = 1.0, transparent: bool = False) -> Image.Image:
    page = design["pages"][max(0, min(index, len(design["pages"]) - 1))]
    width, height = max(1, round(design["w"] * scale)), max(1, round(design["h"] * scale))
    bg = (0, 0, 0, 0) if transparent else (*model.rgb(page.get("bg", "#ffffff")), 255)
    canvas = Image.new("RGBA", (width, height), bg)
    for el in page.get("elements", []):
        try:
            draw_element(canvas, el, scale)
        except Exception:
            continue                      # one broken element must not blank the page
    return canvas if transparent else canvas.convert("RGB")


def thumbnail(design: dict, longest: int = 320, index: int = 0) -> Image.Image:
    scale = longest / max(design["w"], design["h"])
    return render_page(design, index, scale)


def composite(canvas: Image.Image, layer: Image.Image, x: float, y: float) -> None:
    """alpha_composite that tolerates a layer hanging off any edge of the page."""
    x, y = int(round(x)), int(round(y))
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(layer.width, canvas.width - x), min(layer.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, layer.width, layer.height):
        layer = layer.crop((left, top, right, bottom))
    canvas.alpha_composite(layer, (x + left, y + top))


_LAYERS: "OrderedDict[str, tuple[Image.Image, float, float]]" = OrderedDict()


def _layer_key(el: dict, scale: float) -> str:
    return f"{scale:.5f}|" + json.dumps({k: v for k, v in el.items()
                                         if k not in {"x", "y", "id", "locked", "role", "group", "anim"}},
                                        sort_keys=True, ensure_ascii=False)


def draw_element(canvas: Image.Image, el: dict, scale: float) -> None:
    """Draw one element. Its finished layer is cached by everything but its
    position, so dragging something around costs one composite per frame."""
    key = _layer_key(el, scale)
    cached = _LAYERS.get(key)
    if cached is not None:
        _LAYERS.move_to_end(key)
        layer, dx, dy = cached
        composite(canvas, layer, el["x"] * scale + dx, el["y"] * scale + dy)
        return
    layer, x, y = _build(el, scale)
    _LAYERS[key] = (layer, x - el["x"] * scale, y - el["y"] * scale)
    while len(_LAYERS) > 160:
        _LAYERS.popitem(last=False)
    composite(canvas, layer, x, y)


def _build(el: dict, scale: float) -> tuple[Image.Image, float, float]:
    if el["type"] == "line":
        layer, (x, y) = line_layer(el, scale)
    else:
        builder = {"text": text_layer, "shape": shape_layer, "image": image_layer, "icon": icon_layer,
                   "table": table_layer, "chart": chart_layer, "path": path_layer}[el["type"]]
        layer, pad = builder(el, scale)
        if el.get("rot"):
            layer = layer.rotate(-el["rot"], expand=True, resample=Image.Resampling.BICUBIC)
        cx, cy = model.center(el)
        if el["type"] == "text" and layer.height - 2 * pad > el["h"] * scale + 1 and el.get("valign") == "top" \
                and not el.get("rot") and not el.get("curve"):
            # Overflowing text grows downwards from its box, it isn't recentred.
            x, y = el["x"] * scale - pad, el["y"] * scale - pad
        else:
            x, y = cx * scale - layer.width / 2, cy * scale - layer.height / 2
    if el.get("opacity", 1.0) < 1.0:
        alpha = layer.getchannel("A").point(lambda a, o=el["opacity"]: int(a * o))
        layer.putalpha(alpha)
    return layer, x, y


def clear_cache() -> None:
    _LAYERS.clear()
    _picture.cache_clear()
    _source.cache_clear()


# --- shapes ----------------------------------------------------------------------------------

def _regular(n: int, box, rotate: float = -90) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = box
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    return [(cx + rx * math.cos(math.radians(rotate + i * 360 / n)), cy + ry * math.sin(math.radians(rotate + i * 360 / n)))
            for i in range(n)]


def _star(points: int, inner: float, box) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = box
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    out = []
    for i in range(points * 2):
        r = 1 if i % 2 == 0 else inner
        a = math.radians(-90 + i * 180 / points)
        out.append((cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
    return out


def shape_points(kind: str, box) -> list[tuple[float, float]] | None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if kind == "triangle":
        return [(x0 + w / 2, y0), (x1, y1), (x0, y1)]
    if kind == "diamond":
        return [(x0 + w / 2, y0), (x1, y0 + h / 2), (x0 + w / 2, y1), (x0, y0 + h / 2)]
    if kind == "pentagon":
        return _regular(5, box)
    if kind == "hexagon":
        return _regular(6, box, 0)
    if kind == "star":
        return _star(5, 0.45, box)
    if kind == "burst":
        return _star(16, 0.8, box)
    if kind == "arrow":
        head = min(w * 0.45, h)
        return [(x0, y0 + h * 0.25), (x1 - head, y0 + h * 0.25), (x1 - head, y0), (x1, y0 + h / 2),
                (x1 - head, y1), (x1 - head, y0 + h * 0.75), (x0, y0 + h * 0.75)]
    if kind == "chevron":
        k = min(h / 2, w * 0.3)
        return [(x0, y0), (x1 - k, y0), (x1, y0 + h / 2), (x1 - k, y1), (x0, y1), (x0 + k, y0 + h / 2)]
    if kind == "plus":
        a, b = w / 3, h / 3
        return [(x0 + a, y0), (x1 - a, y0), (x1 - a, y0 + b), (x1, y0 + b), (x1, y1 - b), (x1 - a, y1 - b),
                (x1 - a, y1), (x0 + a, y1), (x0 + a, y1 - b), (x0, y1 - b), (x0, y0 + b), (x0 + a, y0 + b)]
    if kind == "heart":
        pts = []
        for i in range(72):
            t = math.radians(i * 5)
            px = 16 * math.sin(t) ** 3
            py = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((x0 + w * (px + 16) / 32, y0 + h * (1 - (py + 17) / 30)))
        return pts
    if kind == "ribbon":
        k = min(w * 0.08, h / 2)
        return [(x0, y0), (x1, y0), (x1 - k, y0 + h / 2), (x1, y1), (x0, y1), (x0 + k, y0 + h / 2)]
    return None


def draw_shape(draw: ImageDraw.ImageDraw, kind: str, box, fill, outline, width: int, radius: float) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    fill_rgba = (*model.rgb(fill), 255) if fill else None
    line_rgba = (*model.rgb(outline), 255) if outline and width > 0 else None
    width = int(width) if line_rgba else 0
    if kind in {"rect", "round", "bubble"}:
        r = min(radius, w / 2, h / 2) if kind != "rect" else 0
        body = box if kind != "bubble" else (x0, y0, x1, y0 + h * 0.78)
        if kind == "bubble":
            tail = [(x0 + w * 0.18, body[3] - 2), (x0 + w * 0.36, body[3] - 2), (x0 + w * 0.12, y1)]
            draw.polygon(tail, fill=fill_rgba, outline=line_rgba, width=width)
            r = min(radius, w / 2, (body[3] - y0) / 2)
        if r > 0:
            draw.rounded_rectangle(body, radius=r, fill=fill_rgba, outline=line_rgba, width=width)
        else:
            draw.rectangle(body, fill=fill_rgba, outline=line_rgba, width=width)
        return
    if kind == "ellipse":
        draw.ellipse(box, fill=fill_rgba, outline=line_rgba, width=width)
        return
    points = shape_points(kind, box) or [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    draw.polygon(points, fill=fill_rgba, outline=line_rgba, width=width)


def _with_shadow(layer: Image.Image, strength: float, scale: float) -> Image.Image:
    offset = max(1, int(round(8 * scale)))
    blur = max(1, int(round(10 * scale)))
    # Blurred at a quarter of the size and scaled back up: a soft shadow has
    # no detail to lose, and a full-size blur of a big shape takes 200 ms.
    alpha = layer.getchannel("A").point(lambda a: int(a * strength))
    small = alpha.resize((max(1, layer.width // 4), max(1, layer.height // 4)), Image.Resampling.BILINEAR)
    alpha = small.filter(ImageFilter.GaussianBlur(max(1, blur / 4))).resize(layer.size, Image.Resampling.BILINEAR)
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    composite(out, shadow, offset, offset)
    out.alpha_composite(layer)
    return out


def pattern_image(size: tuple[int, int], kind: str, colour: str, step: float) -> Image.Image:
    """A transparent picture covered in a repeating pattern, `step` pixels apart."""
    w, h = size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    ink = (*model.rgb(colour), 255)
    line = max(1, int(round(step * 0.18)))
    if kind == "stripes":
        x = -h
        while x < w + h:
            draw.line([(x, h), (x + h, 0)], fill=ink, width=max(1, int(step * 0.35)))
            x += step
    elif kind == "dots":
        r = step * 0.17
        for row, y in enumerate(_steps(step / 2, h + step, step)):
            for x in _steps(step / 2 + (step / 2 if row % 2 else 0), w + step, step):
                draw.ellipse((x - r, y - r, x + r, y + r), fill=ink)
    elif kind == "grid":
        for x in _steps(0, w + 1, step):
            draw.line([(x, 0), (x, h)], fill=ink, width=line)
        for y in _steps(0, h + 1, step):
            draw.line([(0, y), (w, y)], fill=ink, width=line)
    elif kind == "checks":
        for row, y in enumerate(_steps(0, h, step)):
            for col, x in enumerate(_steps(0, w, step)):
                if (row + col) % 2 == 0:
                    draw.rectangle((x, y, x + step - 1, y + step - 1), fill=ink)
    elif kind == "lines":
        for y in _steps(step / 2, h + step, step):
            draw.line([(0, y), (w, y)], fill=ink, width=max(1, int(step * 0.22)))
    elif kind == "waves":
        amp = step * 0.22
        for y in _steps(step / 2, h + step, step):
            points = [(x, y + amp * math.sin(x / step * 2 * math.pi)) for x in _steps(0, w + 4, max(2.0, step / 8))]
            draw.line(points, fill=ink, width=max(1, int(step * 0.14)), joint="curve")
    return out


def _steps(start: float, stop: float, step: float):
    value = start
    while value < stop:
        yield value
        value += step


def _pad(el: dict, scale: float) -> int:
    stroke = el.get("stroke_w", 0) * scale if el.get("stroke") else 0
    shadow = 20 * scale if el.get("shadow") else 0
    return int(math.ceil(stroke / 2 + shadow)) + 1


def shape_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    w, h = max(1.0, el["w"] * scale), max(1.0, el["h"] * scale)
    pad = _pad(el, scale)
    size = (int(math.ceil(w + 2 * pad)), int(math.ceil(h + 2 * pad)))
    big = Image.new("RGBA", (size[0] * AA, size[1] * AA), (0, 0, 0, 0))
    stroke = el.get("stroke_w", 0) * scale * AA
    inset = stroke / 2 if el.get("stroke") else 0
    box = (pad * AA + inset, pad * AA + inset, (pad + w) * AA - inset, (pad + h) * AA - inset)
    radius = el.get("radius", 0) * scale * AA
    draw_shape(ImageDraw.Draw(big), el["shape"], box, el.get("fill"), el.get("stroke"), round(stroke), radius)
    if el.get("pattern", "none") != "none":
        # The pattern is masked by the shape's inside, then the outline goes back on top of it.
        inside = Image.new("RGBA", big.size, (0, 0, 0, 0))
        draw_shape(ImageDraw.Draw(inside), el["shape"], box, "#ffffff", None, 0, radius)
        tile = pattern_image(big.size, el["pattern"], el.get("pattern_color") or "#ffffff",
                             max(4.0, el.get("pattern_size", 28) * scale * AA))
        tile.putalpha(ImageChops.multiply(tile.getchannel("A"), inside.getchannel("A")))
        big.alpha_composite(tile)
        if el.get("stroke") and stroke > 0:
            draw_shape(ImageDraw.Draw(big), el["shape"], box, None, el.get("stroke"), round(stroke), radius)
    layer = big.reduce(AA)
    if el.get("shadow"):
        layer = _with_shadow(layer, 0.35, scale)
    if el.get("text", "").strip():
        inner = _shape_text_box(el)
        draw_text(layer, el, scale, (pad + inner[0] * scale, pad + inner[1] * scale, inner[2] * scale, inner[3] * scale))
    return layer, pad


def _shape_text_box(el: dict) -> tuple[float, float, float, float]:
    """(x, y, w, h) inside a shape where its label goes, relative to the shape."""
    w, h = el["w"], el["h"]
    margin = min(w, h) * 0.08
    kind = el["shape"]
    if kind in {"ellipse", "diamond", "star", "burst", "hexagon", "pentagon", "heart"}:
        fx, fy = {"diamond": (0.22, 0.25), "star": (0.3, 0.33), "burst": (0.16, 0.2), "heart": (0.18, 0.18)}.get(
            kind, (0.15, 0.15))
        return w * fx, h * fy, w * (1 - 2 * fx), h * (1 - 2 * fy)
    if kind == "triangle":
        return w * 0.25, h * 0.45, w * 0.5, h * 0.5
    if kind == "bubble":
        return margin, margin, w - 2 * margin, h * 0.78 - 2 * margin
    if kind in {"arrow", "chevron", "ribbon"}:
        return w * 0.1, h * 0.2, w * 0.7, h * 0.6
    return margin, margin, w - 2 * margin, h - 2 * margin


# --- text ------------------------------------------------------------------------------------

JOINERS = {0xFE0F, 0x200D, 0x20E3}


def _char_kind(ch: str) -> str:
    o = ord(ch)
    if o >= 0x1F000:
        return "emoji"
    if 0x2190 <= o <= 0x2BFF or 0x2600 <= o <= 0x27BF:
        return "symbol"
    return "text"


_GLYPHS: dict[tuple, bool] = {}


def has_glyph(font, ch: str) -> bool:
    """Whether a font draws a character itself rather than its 'missing' box."""
    key = (getattr(font, "path", id(font)), ch)
    known = _GLYPHS.get(key)
    if known is None:
        try:
            known = _ink(font, ch) != _ink(font, "\U000F0000")
        except Exception:
            known = True
        _GLYPHS[key] = known
    return known


def _ink(font, ch: str) -> bytes:
    left, top, right, bottom = font.getbbox(ch)
    image = Image.new("L", (max(1, int(right - left)) + 2, max(1, int(bottom - top)) + 2), 0)
    ImageDraw.Draw(image).text((1 - left, 1 - top), ch, font=font, fill=255)
    return image.tobytes()


class Face:
    """A text font plus the symbol and emoji fonts its missing characters fall
    back to: '✓ Excellent' or '📅 Saturday' would otherwise draw boxes, since
    Pillow has no font fallback of its own. A letter the font lacks (₺ in
    Constantia, say) comes from Segoe UI instead."""

    def __init__(self, font, size: float, bold: bool = False, italic: bool = False):
        self.font, self.size = font, size
        self.bold, self.italic = bold, italic
        self._sym = self._emo = self._plain = None

    @property
    def plain(self):
        if self._plain is None:
            self._plain = fonts.get("Segoe UI", self.size, self.bold, self.italic)
        return self._plain

    def _kind(self, ch: str) -> str:
        kind = _char_kind(ch)
        if kind == "text" and ord(ch) > 0x7F and not has_glyph(self.font, ch):
            return "plain"
        return kind

    @property
    def sym(self):
        if self._sym is None:
            self._sym = fonts.symbol(int(round(self.size)))
        return self._sym

    @property
    def emo(self):
        if self._emo is None:
            self._emo = fonts.emoji(int(round(self.size)))
        return self._emo

    def getmetrics(self):
        return self.font.getmetrics()

    def runs(self, text: str) -> list[list]:
        out: list[list] = []
        for ch in text:
            o = ord(ch)
            if out and (o in JOINERS or 0x1F3FB <= o <= 0x1F3FF or out[-1][0].endswith("\u200d")):
                if o == 0xFE0F and out[-1][1] == "symbol":
                    if len(out[-1][0]) > 1:
                        last = out[-1][0][-1]
                        out[-1][0] = out[-1][0][:-1]
                        out.append([last, "emoji"])
                    else:
                        out[-1][1] = "emoji"
                out[-1][0] += ch
                continue
            kind = self._kind(ch)
            if out and out[-1][1] == kind:
                out[-1][0] += ch
            else:
                out.append([ch, kind])
        return out

    @staticmethod
    def _clean(seg: str, kind: str) -> str:
        # Without a shaping engine a variation selector draws as a box of its own.
        return seg.replace("️", "").replace("︎", "") if kind == "emoji" else seg

    def _font_for(self, kind: str):
        if kind == "emoji":
            return self.emo[0]
        if kind == "plain":
            return self.plain
        return self.sym if kind == "symbol" else self.font

    def getlength(self, text: str) -> float:
        if text.isascii():
            return self.font.getlength(text)
        return sum(self._font_for(kind).getlength(self._clean(seg, kind)) for seg, kind in self.runs(text))

    def draw(self, draw, x: float, baseline: float, text: str, fill, stroke_w: int = 0, stroke=None,
             color_emoji: bool = True) -> float:
        for seg, kind in ([[text, "text"]] if text.isascii() else self.runs(text)):
            font = self._font_for(kind)
            seg = self._clean(seg, kind)
            if kind == "emoji" and self.emo[1] and color_emoji:
                draw.text((x, baseline), seg, font=font, anchor="ls", embedded_color=True)
            else:
                draw.text((x, baseline), seg, font=font, anchor="ls", fill=fill,
                          stroke_width=stroke_w if kind != "emoji" else 0, stroke_fill=stroke)
            x += font.getlength(seg)
        return x


def face(family: str, size: float, bold: bool = False, italic: bool = False) -> Face:
    return Face(fonts.get(family, size, bold, italic), size, bold, italic)


def _wrap(text: str, font, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split(" "):
            trial = f"{line} {word}" if line else word
            if font.getlength(trial) <= width or not line:
                if not line and font.getlength(word) > width and len(word) > 1:
                    # A word wider than the box is broken, not left hanging off the edge.
                    piece = ""
                    for ch in word:
                        if font.getlength(piece + ch) > width and piece:
                            lines.append(piece)
                            piece = ch
                        else:
                            piece += ch
                    line = piece
                else:
                    line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def layout(el: dict, scale: float, box_w: float, box_h: float, autofit: bool | None = None):
    """(face, lines, line_height, size) for a text box, shrunk to fit if it autofits."""
    size = max(4.0, el.get("size", 32) * scale)
    autofit = el.get("autofit", False) if autofit is None else autofit
    family, bold, italic = el.get("font") or "Segoe UI", el.get("bold", False), el.get("italic", False)
    spacing = el.get("line", 1.15)
    for _ in range(40):
        font = face(family, size, bold, italic)
        lines = _wrap(el.get("text", ""), font, max(1.0, box_w))
        line_h = size * spacing
        if not autofit or size <= 6 or len(lines) * line_h <= box_h + 0.5:
            return font, lines, line_h, size
        size *= 0.92
    return font, lines, line_h, size


def fits(el: dict) -> bool:
    """Whether a text element's words fit its box at its own size."""
    pad = el.get("pad", 0)
    _, lines, line_h, _ = layout(el, 1.0, el["w"] - 2 * pad, el["h"] - 2 * pad, autofit=False)
    return len(lines) * line_h <= el["h"] - 2 * pad + 1


def fitted_size(el: dict) -> float:
    pad = el.get("pad", 0)
    return layout(el, 1.0, el["w"] - 2 * pad, el["h"] - 2 * pad)[3]


def needed_height(el: dict, scale: float = 1.0) -> float:
    pad = el.get("pad", 0) * scale
    _, lines, line_h, _ = layout(el, scale, el["w"] * scale - 2 * pad, el["h"] * scale - 2 * pad)
    return len(lines) * line_h + 2 * pad


def draw_text(layer: Image.Image, el: dict, scale: float, box: tuple[float, float, float, float]) -> None:
    x, y, w, h = box
    font, lines, line_h, size = layout(el, scale, w, h)
    color = (*model.rgb(el.get("color", "#000000")), 255)
    block = len(lines) * line_h
    valign = el.get("valign", "top")
    top = y + (h - block) / 2 if valign == "middle" else (y + h - block if valign == "bottom" else y)
    stroke_w = int(round(el.get("stroke_w", 0) * scale)) if el.get("stroke") else 0
    stroke = (*model.rgb(el["stroke"]), 255) if stroke_w else None
    draw = ImageDraw.Draw(layer)
    if el.get("shadow"):
        shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        offset = max(1, size * 0.05)
        _text_lines(sd, lines, font, x + offset, top + offset, w, line_h, el.get("align"), (0, 0, 0, 150), stroke_w,
                    (0, 0, 0, 150) if stroke_w else None, False, size, color_emoji=False)
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.04)))
        layer.alpha_composite(shadow)
    _text_lines(draw, lines, font, x, top, w, line_h, el.get("align"), color, stroke_w, stroke,
                el.get("underline", False), size)


def _text_lines(draw, lines, font: Face, x, top, w, line_h, align, fill, stroke_w, stroke, underline, size,
                color_emoji: bool = True) -> None:
    ascent, descent = font.getmetrics()
    for i, line in enumerate(lines):
        width = font.getlength(line)
        lx = x + (w - width) / 2 if align == "center" else (x + w - width if align == "right" else x)
        baseline = top + i * line_h + (line_h - (ascent + descent)) / 2 + ascent
        font.draw(draw, lx, baseline, line, fill, stroke_w, stroke, color_emoji)
        if underline and line.strip():
            base = baseline + max(1, size * 0.08)
            draw.line([(lx, base), (lx + width, base)], fill=fill, width=max(1, int(size * 0.06)))


def _units(text: str) -> list[str]:
    """Characters, with emoji joiners and skin tones kept on the character they belong to."""
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        if out and (o in JOINERS or 0x1F3FB <= o <= 0x1F3FF or out[-1].endswith("\u200d") or o == 0xFE0E):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def curved_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    """Text along an arc: a positive curve arches up like a rainbow, a negative one smiles.
    ±360 wraps the words all the way round a circle."""
    w, h = max(1.0, el["w"] * scale), max(1.0, el["h"] * scale)
    size = max(4.0, el.get("size", 32) * scale)
    font = face(el.get("font") or "Segoe UI", size, el.get("bold", False), el.get("italic", False))
    units = _units(" ".join(str(el.get("text", "")).split("\n")))
    ascent, descent = font.getmetrics()
    stroke_w = int(round(el.get("stroke_w", 0) * scale)) if el.get("stroke") else 0
    stroke = (*model.rgb(el["stroke"]), 255) if stroke_w else None
    colour = (*model.rgb(el.get("color", "#000000")), 255)
    widths = [font.getlength(u) for u in units]
    total = max(1.0, sum(widths))
    curve = el.get("curve", 0.0)
    sign = 1 if curve > 0 else -1
    angle = math.radians(max(1.0, abs(curve)))
    radius = total / angle
    sag = radius * (1 - math.cos(min(angle / 2, math.pi)))
    chord = 2 * radius * math.sin(min(angle / 2, math.pi / 2))
    margin = int(size * 0.5) + stroke_w + (int(size * 0.2) if el.get("shadow") else 0) + 2
    lw = int(math.ceil(max(w, chord + size * 1.5) + 2 * margin))
    lh = int(math.ceil(max(h, sag + size * 1.6) + 2 * margin))
    layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    if el.get("fill"):
        ImageDraw.Draw(layer).rectangle(((lw - w) / 2, (lh - h) / 2, (lw + w) / 2, (lh + h) / 2),
                                        fill=(*model.rgb(el["fill"]), 255))
    words = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    mid_x, mid_y = lw / 2, lh / 2 - sign * sag / 2
    centre_y = mid_y + sign * radius
    pos = -total / 2
    pad = int(size * 0.3) + stroke_w + 2
    for unit, width in zip(units, widths):
        phi = (pos + width / 2) / radius
        pos += width
        if not unit.strip():
            continue
        glyph = Image.new("RGBA", (int(math.ceil(width)) + 2 * pad, ascent + descent + 2 * pad), (0, 0, 0, 0))
        font.draw(ImageDraw.Draw(glyph), pad, pad + ascent, unit, colour, stroke_w, stroke)
        glyph = glyph.rotate(-sign * math.degrees(phi), expand=True, resample=Image.Resampling.BICUBIC)
        px = mid_x + radius * math.sin(phi)
        py = centre_y - sign * radius * math.cos(phi)
        composite(words, glyph, px - glyph.width / 2, py - glyph.height / 2)
    if el.get("shadow"):
        shadow = Image.new("RGBA", words.size, (0, 0, 0, 0))
        shadow.putalpha(words.getchannel("A").point(lambda a: int(a * 0.6)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size * 0.04)))
        composite(layer, shadow, max(1, size * 0.05), max(1, size * 0.05))
    layer.alpha_composite(words)
    return layer, margin


def text_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    if el.get("curve"):
        return curved_layer(el, scale)
    w, h = max(1.0, el["w"] * scale), max(1.0, el["h"] * scale)
    pad = _pad(el, scale) + int(el.get("size", 32) * scale * 0.15)
    inner_pad = el.get("pad", 0) * scale
    needed = needed_height(el, scale) if not el.get("autofit") else h
    full_h = max(h, needed)
    layer = Image.new("RGBA", (int(math.ceil(w + 2 * pad)), int(math.ceil(full_h + 2 * pad))), (0, 0, 0, 0))
    if el.get("fill"):
        draw = ImageDraw.Draw(layer)
        r = min(el.get("radius", 0) * scale, w / 2, full_h / 2)
        box = (pad, pad, pad + w, pad + full_h)
        if r > 0:
            draw.rounded_rectangle(box, radius=r, fill=(*model.rgb(el["fill"]), 255))
        else:
            draw.rectangle(box, fill=(*model.rgb(el["fill"]), 255))
    draw_text(layer, el, scale, (pad + inner_pad, pad + inner_pad, w - 2 * inner_pad, full_h - 2 * inner_pad))
    return layer, pad


# --- pictures --------------------------------------------------------------------------------

@lru_cache(maxsize=24)
def _source(path: str, mtime: float) -> Image.Image:
    image = Image.open(path)
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail((2400, 2400), LANCZOS)
    return image


def apply_filter(image: Image.Image, name: str, strength: float = 1.0) -> Image.Image:
    if name in {"", "none"}:
        return image
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    if name == "grayscale":
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    elif name in {"sepia", "vintage"}:
        rgb = ImageOps.colorize(ImageOps.grayscale(rgb), "#2e1f10", "#f3e2c3")
        if name == "vintage":
            rgb = ImageEnhance.Contrast(rgb).enhance(0.85)
            rgb = Image.blend(rgb, Image.new("RGB", rgb.size, "#f0c987"), 0.12)
    elif name == "blur":
        rgb = rgb.filter(ImageFilter.GaussianBlur(max(1, min(rgb.size) / 120)))
    elif name == "bright":
        rgb = ImageEnhance.Brightness(rgb).enhance(1.3)
    elif name == "dark":
        rgb = ImageEnhance.Brightness(rgb).enhance(0.65)
    elif name == "contrast":
        rgb = ImageEnhance.Contrast(rgb).enhance(1.45)
    elif name == "vivid":
        rgb = ImageEnhance.Color(rgb).enhance(1.7)
    elif name == "cool":
        rgb = Image.blend(rgb, Image.new("RGB", rgb.size, "#3b82f6"), 0.15)
    elif name == "warm":
        rgb = Image.blend(rgb, Image.new("RGB", rgb.size, "#f97316"), 0.15)
    elif name == "invert":
        rgb = ImageOps.invert(rgb)
    elif name == "sharpen":
        rgb = rgb.filter(ImageFilter.UnsharpMask(2, 160, 2))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _placeholder(w: int, h: int) -> Image.Image:
    layer = Image.new("RGBA", (w, h), (226, 232, 240, 255))
    draw = ImageDraw.Draw(layer)
    draw.line([(0, 0), (w, h)], fill=(148, 163, 184, 255), width=max(1, w // 200))
    draw.line([(0, h), (w, 0)], fill=(148, 163, 184, 255), width=max(1, w // 200))
    return layer


@lru_cache(maxsize=64)
def _picture(path: str, mtime: float, w: int, h: int, crop: tuple, fit: str, filter_: str, flip_h: bool,
             flip_v: bool) -> Image.Image:
    image = _source(path, mtime)
    left, top, right, bottom = crop
    if any(crop):
        W, H = image.size
        box = (int(W * left), int(H * top), int(W * (1 - right)), int(H * (1 - bottom)))
        if box[2] > box[0] + 1 and box[3] > box[1] + 1:
            image = image.crop(box)
    if flip_h:
        image = ImageOps.mirror(image)
    if flip_v:
        image = ImageOps.flip(image)
    if fit == "stretch":
        image = image.resize((w, h), LANCZOS)
    elif fit == "contain":
        copy = image.copy()
        copy.thumbnail((w, h), LANCZOS)
        if copy.width < w and copy.height < h:
            ratio = min(w / copy.width, h / copy.height)
            copy = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))), LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(copy, ((w - copy.width) // 2, (h - copy.height) // 2))
        image = canvas
    else:
        image = ImageOps.fit(image, (w, h), LANCZOS)
    return apply_filter(image, filter_)


def image_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    w, h = max(1, int(round(el["w"] * scale))), max(1, int(round(el["h"] * scale)))
    path = model.resolve_src(el.get("src", ""))
    if path is None:
        picture = _placeholder(w, h)
    else:
        try:
            picture = _picture(str(path), path.stat().st_mtime, w, h, tuple(el.get("crop") or (0, 0, 0, 0)),
                               el.get("fit", "cover"), el.get("filter", "none"), el.get("flip_h", False),
                               el.get("flip_v", False)).copy()
        except Exception:
            picture = _placeholder(w, h)
    radius = el.get("radius", 0) * scale
    if el.get("circle") or radius > 0:
        mask = Image.new("L", (w * AA, h * AA), 0)
        md = ImageDraw.Draw(mask)
        if el.get("circle"):
            md.ellipse((0, 0, w * AA - 1, h * AA - 1), fill=255)
        else:
            md.rounded_rectangle((0, 0, w * AA - 1, h * AA - 1), radius=radius * AA, fill=255)
        mask = mask.reduce(AA)
        picture.putalpha(ImageChops.multiply(picture.getchannel("A"), mask))
    pad = _pad(el, scale)
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    layer.alpha_composite(picture, (pad, pad))
    if el.get("stroke") and el.get("stroke_w", 0) > 0:
        big = Image.new("RGBA", (layer.width * AA, layer.height * AA), (0, 0, 0, 0))
        bd = ImageDraw.Draw(big)
        sw = max(1, round(el["stroke_w"] * scale * AA))
        box = (pad * AA + sw / 2, pad * AA + sw / 2, (pad + w) * AA - sw / 2, (pad + h) * AA - sw / 2)
        outline = (*model.rgb(el["stroke"]), 255)
        if el.get("circle"):
            bd.ellipse(box, outline=outline, width=sw)
        elif radius > 0:
            bd.rounded_rectangle(box, radius=radius * AA, outline=outline, width=sw)
        else:
            bd.rectangle(box, outline=outline, width=sw)
        layer.alpha_composite(big.reduce(AA))
    if el.get("shadow"):
        layer = _with_shadow(layer, 0.4, scale)
    return layer, pad


# --- icons and tables --------------------------------------------------------------------------

def icon_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    w, h = max(1, int(round(el["w"] * scale))), max(1, int(round(el["h"] * scale)))
    size = max(4, int(min(w, h) * 0.86))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # Without a shaping engine a variation selector draws as a box of its own.
    glyph = (el.get("glyph") or "⭐").replace("️", "").replace("︎", "") or "⭐"
    if el.get("set") == "color":
        font, colored = fonts.emoji(size)
        if colored:
            draw.text((w / 2, h / 2), glyph, font=font, anchor="mm", embedded_color=True)
            return layer, 0
    else:
        font = fonts.symbol(size)
    draw.text((w / 2, h / 2), glyph, font=font, anchor="mm", fill=(*model.rgb(el.get("color", "#000000")), 255))
    return layer, 0


def table_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    w, h = max(2, int(round(el["w"] * scale))), max(2, int(round(el["h"] * scale)))
    rows = el.get("rows") or [[""]]
    n, m = len(rows), max(len(r) for r in rows)
    cw, rh = w / m, h / n
    layer = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle((0, 0, w, h), fill=(*model.rgb(el.get("bg", "#ffffff")), 255))
    size = max(4.0, el.get("size", 28) * scale)
    pad = size * 0.35
    family = el.get("font") or "Segoe UI"
    # One size for the whole table: the largest at which every cell fits.
    for _ in range(30):
        font = face(family, size)
        fits_all = all(len(_wrap(cell, font, max(1, cw - 2 * pad))) * size * 1.15 <= rh - pad * 0.6 + 0.5
                       for row in rows for cell in row)
        if fits_all or size <= 6:
            break
        size *= 0.92
    bold = face(family, size, bold=True)
    for r, row in enumerate(rows):
        top = r * rh
        if r == 0 and el.get("header"):
            draw.rectangle((0, top, w, top + rh), fill=(*model.rgb(el.get("fill") or "#4f8ef7"), 255))
        elif r % 2 == 0 and el.get("stripe"):
            draw.rectangle((0, top, w, top + rh), fill=(*model.rgb(el["stripe"]), 255))
        for c in range(m):
            cell = row[c] if c < len(row) else ""
            header = r == 0 and el.get("header")
            f = bold if header else font
            colour = el.get("header_color") if header else el.get("color")
            lines = _wrap(cell, f, max(1, cw - 2 * pad))
            line_h = size * 1.15
            ty = top + (rh - len(lines) * line_h) / 2
            for i, line in enumerate(lines):
                lw = f.getlength(line)
                align = "center" if header else el.get("align", "left")
                lx = c * cw + (cw - lw) / 2 if align == "center" else (
                    c * cw + cw - pad - lw if align == "right" else c * cw + pad)
                f.draw(draw, lx, ty + i * line_h + f.getmetrics()[0], line, (*model.rgb(colour or "#000000"), 255))
    border = (*model.rgb(el.get("border") or "#cbd5e1"), 255)
    width = max(1, int(round(2 * scale)))
    for r in range(n + 1):
        draw.line([(0, min(h, r * rh)), (w, min(h, r * rh))], fill=border, width=width)
    for c in range(m + 1):
        draw.line([(min(w, c * cw), 0), (min(w, c * cw), h)], fill=border, width=width)
    return layer, 0


# --- charts and pen strokes ------------------------------------------------------------------

def chart_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    from . import chart

    return chart.render(el, scale), 0


def smooth_points(points: list[tuple[float, float]], closed: bool = False, rounds: int = 2) -> list[tuple[float, float]]:
    """Chaikin's corner cutting: a shaky mouse line comes out as a smooth curve."""
    pts = list(points)
    for _ in range(rounds):
        if len(pts) < 3:
            return pts
        out = [] if closed else [pts[0]]
        pairs = list(zip(pts, pts[1:] + pts[:1])) if closed else list(zip(pts, pts[1:]))
        for (x0, y0), (x1, y1) in pairs:
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def path_points(el: dict, w: float, h: float, ox: float = 0.0, oy: float = 0.0) -> list[tuple[float, float]]:
    points = [(ox + px * w, oy + py * h) for px, py in el.get("points") or []]
    if el.get("smooth", True) and len(points) > 2:
        points = smooth_points(points, el.get("closed", False))
    return points


def path_layer(el: dict, scale: float) -> tuple[Image.Image, int]:
    w, h = max(1.0, el["w"] * scale), max(1.0, el["h"] * scale)
    width = el.get("stroke_w", 0) * scale if el.get("stroke") else 0.0
    pad = int(math.ceil(width / 2)) + 2
    big = Image.new("RGBA", (int(math.ceil(w + 2 * pad)) * AA, int(math.ceil(h + 2 * pad)) * AA), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    points = path_points(el, w * AA, h * AA, pad * AA, pad * AA)
    if len(points) < 2:
        return big.reduce(AA), pad
    if el.get("closed") and el.get("fill") and len(points) > 2:
        draw.polygon(points, fill=(*model.rgb(el["fill"]), 255))
    if width > 0:
        ink = (*model.rgb(el["stroke"]), 255)
        line = max(1, int(round(width * AA)))
        draw.line(points + ([points[0]] if el.get("closed") else []), fill=ink, width=line, joint="curve")
        if not el.get("closed"):
            r = line / 2
            for x, y in (points[0], points[-1]):
                draw.ellipse((x - r, y - r, x + r, y + r), fill=ink)
    return big.reduce(AA), pad


# --- lines -----------------------------------------------------------------------------------

def line_layer(el: dict, scale: float) -> tuple[Image.Image, tuple[float, float]]:
    x0, y0 = el["x"] * scale, el["y"] * scale
    x1, y1 = (el["x"] + el["w"]) * scale, (el["y"] + el["h"]) * scale
    width = max(1.0, el.get("stroke_w", 4) * scale)
    head = max(8 * scale, width * 3.2) if el.get("arrow", "none") != "none" else 0
    margin = head + width + 2
    left, top = min(x0, x1) - margin, min(y0, y1) - margin
    size = (int(math.ceil(abs(x1 - x0) + 2 * margin)), int(math.ceil(abs(y1 - y0) + 2 * margin)))
    big = Image.new("RGBA", (size[0] * AA, size[1] * AA), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    colour = (*model.rgb(el.get("stroke") or "#000000"), 255)
    ax, ay, bx, by = (x0 - left) * AA, (y0 - top) * AA, (x1 - left) * AA, (y1 - top) * AA
    length = math.hypot(bx - ax, by - ay) or 1
    ux, uy = (bx - ax) / length, (by - ay) / length
    arrow = el.get("arrow", "none")
    sa = (ax + ux * head * AA * 0.8, ay + uy * head * AA * 0.8) if arrow in {"start", "both"} else (ax, ay)
    sb = (bx - ux * head * AA * 0.8, by - uy * head * AA * 0.8) if arrow in {"end", "both"} else (bx, by)
    w_big = max(1, int(round(width * AA)))
    if el.get("dash"):
        dash, gap = width * AA * 3, width * AA * 2
        total = math.hypot(sb[0] - sa[0], sb[1] - sa[1])
        pos = 0.0
        while pos < total:
            end = min(total, pos + dash)
            draw.line([(sa[0] + ux * pos, sa[1] + uy * pos), (sa[0] + ux * end, sa[1] + uy * end)], fill=colour,
                      width=w_big)
            pos = end + gap
    else:
        draw.line([sa, sb], fill=colour, width=w_big)
    for tip, direction in (((bx, by), 1), ((ax, ay), -1)):
        if (direction == 1 and arrow in {"end", "both"}) or (direction == -1 and arrow in {"start", "both"}):
            dx, dy = ux * direction, uy * direction
            hl, hw = head * AA, head * AA * 0.55
            base = (tip[0] - dx * hl, tip[1] - dy * hl)
            draw.polygon([tip, (base[0] - dy * hw, base[1] + dx * hw), (base[0] + dy * hw, base[1] - dx * hw)],
                         fill=colour)
    return big.reduce(AA), (left, top)


# --- exports ---------------------------------------------------------------------------------

def dpi(design: dict) -> float:
    inches = INCHES_WIDE.get(design.get("format", ""), design["w"] / 150)
    return max(72.0, design["w"] / inches)


def export_images(design: dict, base: Path, fmt: str = "PNG", pages: list[int] | None = None,
                  scale: float = 1.0) -> list[Path]:
    fmt = "JPEG" if fmt.upper() in {"JPG", "JPEG"} else "PNG"
    suffix = ".jpg" if fmt == "JPEG" else ".png"
    indexes = pages if pages is not None else list(range(len(design["pages"])))
    out = []
    for i in indexes:
        path = base.with_suffix(suffix) if len(indexes) == 1 else base.with_name(f"{base.stem}_{i + 1:02d}{suffix}")
        image = render_page(design, i, scale)
        if fmt == "JPEG":
            image.save(path, "JPEG", quality=92, dpi=(dpi(design),) * 2)
        else:
            image.save(path, "PNG", dpi=(dpi(design),) * 2)
        out.append(path)
    return out


def export_pdf(design: dict, path: Path, scale: float = 1.0) -> Path:
    images = [render_page(design, i, scale) for i in range(len(design["pages"]))]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=dpi(design) * scale)
    return path


def dominant_colors(path: Path, count: int = 5) -> list[str]:
    """The main colours of a photo, most common first — for 'palette from photo'."""
    image = Image.open(path).convert("RGB")
    image.thumbnail((200, 200))
    quant = image.quantize(colors=max(2, count + 3), method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    out: list[str] = []
    for _, index in counts:
        r, g, b = palette[index * 3:index * 3 + 3]
        hex_ = "#%02x%02x%02x" % (r, g, b)
        if all(sum(abs(a - b) for a, b in zip(model.rgb(hex_), model.rgb(o))) > 60 for o in out):
            out.append(hex_)
        if len(out) == count:
            break
    return out
