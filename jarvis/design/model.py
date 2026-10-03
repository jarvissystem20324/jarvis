"""A design as plain JSON, and everything that edits or stores one.

    {"version": 1, "id": "spring-sale_20261003_101500", "title": "Spring sale",
     "kind": "poster", "format": "poster", "w": 1240, "h": 1754, "theme": "",
     "seq": 7, "pages": [{"bg": "#ffffff", "notes": "", "elements": [...]}]}

Elements are positioned in pixels of the design's own size and drawn in list
order (last on top). Every element has x, y, w, h, rot, opacity, locked and an
optional role ("title", "body", "deco", "logo"...) that themes, palettes and
the brand kit use to recolour a design without knowing how it was made.
A line runs from (x, y) to (x + w, y + h), so w and h may be negative.

Designs live in Documents/JARVIS/designs as .jdesign files with a .png
thumbnail beside each; pictures put on a design are copied into assets/ so a
design still opens after the original file is moved.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from .. import kit

EXT = ".jdesign"
FORMATS: dict[str, tuple[str, int, int]] = {
    "slides": ("Slides 16:9", 1920, 1080),
    "thumbnail": ("YouTube thumbnail", 1280, 720),
    "instagram": ("Instagram post", 1080, 1080),
    "story": ("Story (Instagram, TikTok)", 1080, 1920),
    "poster": ("Poster / flyer (A4)", 1240, 1754),
    "a4_landscape": ("A4 landscape", 1754, 1240),
    "card": ("Greeting card", 1500, 1050),
    "invitation": ("Invitation (5x7)", 1050, 1470),
    "logo": ("Logo", 1000, 1000),
    "sticker": ("Sticker / badge", 1000, 1000),
    "banner": ("X / LinkedIn banner", 1500, 500),
    "facebook": ("Facebook post", 1200, 630),
    "diagram": ("Diagram 16:9", 1920, 1080),
}
TYPES = ("text", "shape", "line", "image", "icon", "table")
SHAPES = ("rect", "round", "ellipse", "triangle", "diamond", "pentagon", "hexagon", "star", "burst",
          "arrow", "chevron", "plus", "heart", "bubble", "ribbon")
FILTERS = ("none", "grayscale", "sepia", "vintage", "blur", "bright", "dark", "contrast", "vivid",
           "cool", "warm", "invert", "sharpen")
COMMON = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0, "rot": 0.0, "opacity": 1.0, "locked": False, "role": ""}
DEFAULTS: dict[str, dict] = {
    "text": {"text": "Text", "font": "Segoe UI", "size": 48.0, "color": "#1f2430", "bold": False, "italic": False,
             "underline": False, "align": "left", "valign": "top", "line": 1.15, "fill": None, "radius": 0.0,
             "pad": 0.0, "autofit": False, "stroke": None, "stroke_w": 0.0, "shadow": False},
    "shape": {"shape": "rect", "fill": "#4f8ef7", "stroke": None, "stroke_w": 0.0, "radius": 24.0, "shadow": False,
              "text": "", "font": "Segoe UI", "size": 36.0, "color": "#ffffff", "bold": False, "italic": False,
              "underline": False, "align": "center", "valign": "middle", "line": 1.1, "autofit": True},
    "line": {"stroke": "#1f2430", "stroke_w": 6.0, "arrow": "none", "dash": False},
    "image": {"src": "", "fit": "cover", "crop": [0.0, 0.0, 0.0, 0.0], "filter": "none", "flip_h": False,
              "flip_v": False, "radius": 0.0, "circle": False, "stroke": None, "stroke_w": 0.0, "shadow": False},
    "icon": {"glyph": "⭐", "set": "color", "color": "#1f2430"},
    "table": {"rows": [["Column 1", "Column 2"], ["", ""]], "header": True, "font": "Segoe UI", "size": 28.0,
              "color": "#1f2430", "fill": "#4f8ef7", "header_color": "#ffffff", "stripe": "#f1f5f9",
              "border": "#cbd5e1", "bg": "#ffffff", "align": "left"},
}
# What "copy style" carries: everything but where it is, what it says and what it is.
NOT_STYLE = {"id", "type", "x", "y", "w", "h", "rot", "text", "src", "glyph", "rows", "crop", "locked", "role",
             "shape", "set"}
COLOR_KEYS = {"color", "fill", "stroke", "header_color", "stripe", "border", "bg"}
NULLABLE = {"fill", "stroke"}
CHOICES = {"align": ("left", "center", "right"), "valign": ("top", "middle", "bottom"),
           "arrow": ("none", "end", "start", "both"), "fit": ("cover", "contain", "stretch"),
           "set": ("color", "mono"), "shape": SHAPES, "filter": FILTERS}


class DesignError(Exception):
    pass


# --- colours -----------------------------------------------------------------------------

def color(value, default: str | None = "#000000", allow_none: bool = False) -> str | None:
    """'#abc', '#aabbcc', 'red', 'rgb(1,2,3)' -> '#rrggbb'; 'none' -> None where allowed."""
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "none", "transparent", "null"}):
        return None if allow_none else default
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in value[:3])
        except (TypeError, ValueError):
            return default
    text = str(value).strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        return "#" + text.lstrip("#").lower()
    if re.fullmatch(r"#?[0-9a-fA-F]{3}", text):
        return "#" + "".join(c * 2 for c in text.lstrip("#")).lower()
    try:
        from PIL import ImageColor

        return "#%02x%02x%02x" % ImageColor.getrgb(text)[:3]
    except (ValueError, TypeError):
        return default


def rgb(hex_color: str) -> tuple[int, int, int]:
    value = color(hex_color, "#000000")
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def luminance(hex_color: str) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(bg: str, dark: str = "#111827", light: str = "#ffffff") -> str:
    return dark if contrast(dark, bg) >= contrast(light, bg) else light


def mix(a: str, b: str, t: float) -> str:
    ra, rb = rgb(a), rgb(b)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(ra, rb))


# --- building ----------------------------------------------------------------------------

def new_design(kind: str = "slides", fmt: str | None = None, title: str = "Untitled design",
               pages: int = 1, bg: str = "#ffffff") -> dict:
    fmt = fmt if fmt in FORMATS else (kind if kind in FORMATS else "slides")
    _, w, h = FORMATS[fmt]
    return {"version": 1, "id": f"{kit.slug(title)}_{kit.stamp()}", "title": title, "kind": kind,
            "format": fmt, "w": w, "h": h, "theme": "", "seq": 0, "created": time.time(), "modified": time.time(),
            "pages": [new_page(bg) for _ in range(max(1, pages))]}


def new_page(bg: str = "#ffffff") -> dict:
    return {"bg": color(bg, "#ffffff"), "notes": "", "elements": []}


def element(type_: str, **props) -> dict:
    if type_ not in DEFAULTS:
        raise DesignError(f"Unknown element type: {type_}")
    out = {"id": "", "type": type_, **json.loads(json.dumps(COMMON)), **json.loads(json.dumps(DEFAULTS[type_]))}
    out.update(props)
    return clean_element(out)


def text(value: str, x, y, w, h, **props) -> dict:
    return element("text", text=value, x=x, y=y, w=w, h=h, **props)


def shape(kind: str, x, y, w, h, **props) -> dict:
    return element("shape", shape=kind, x=x, y=y, w=w, h=h, **props)


def line(x1, y1, x2, y2, **props) -> dict:
    return element("line", x=x1, y=y1, w=x2 - x1, h=y2 - y1, **props)


def picture(src: str, x, y, w, h, **props) -> dict:
    return element("image", src=src, x=x, y=y, w=w, h=h, **props)


def icon(glyph: str, x, y, size, **props) -> dict:
    return element("icon", glyph=glyph, x=x, y=y, w=size, h=size, **props)


def table(rows: list[list[str]], x, y, w, h, **props) -> dict:
    return element("table", rows=rows, x=x, y=y, w=w, h=h, **props)


def add(design: dict, page: dict | int, el: dict, index: int | None = None) -> dict:
    page = design["pages"][page] if isinstance(page, int) else page
    design["seq"] = int(design.get("seq", 0)) + 1
    el["id"] = f"e{design['seq']}"
    if index is None:
        page["elements"].append(el)
    else:
        page["elements"].insert(index, el)
    return el


def find(page: dict, element_id: str) -> dict | None:
    return next((e for e in page.get("elements", []) if e.get("id") == element_id), None)


def by_role(page: dict, role: str) -> list[dict]:
    return [e for e in page.get("elements", []) if e.get("role") == role]


def clone(value):
    return json.loads(json.dumps(value))


# --- cleaning (files from disk, edits from the model) -------------------------------------------

def _number(value, default: float, low: float | None = None, high: float | None = None) -> float:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            raise ValueError
    except (TypeError, ValueError):
        number = default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def clean_value(type_: str, key: str, value, current=None):
    """One property, checked and coerced. Raises KeyError for a key the type doesn't have."""
    defaults = {**COMMON, **DEFAULTS[type_]}
    if key not in defaults:
        raise KeyError(key)
    default = defaults[key] if current is None else current
    if key in COLOR_KEYS:
        return color(value, default if default else "#000000", allow_none=key in NULLABLE)
    if key in CHOICES:
        word = str(value).strip().lower()
        return word if word in CHOICES[key] else default
    base = DEFAULTS[type_].get(key, COMMON.get(key))
    if isinstance(base, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(base, float):
        limits = {"opacity": (0.0, 1.0), "size": (4.0, 2000.0), "line": (0.6, 3.0), "stroke_w": (0.0, 200.0),
                  "radius": (0.0, 5000.0), "pad": (0.0, 500.0), "rot": (-3600.0, 3600.0)}.get(key, (None, None))
        number = _number(value, float(default) if isinstance(default, (int, float)) else base, *limits)
        return number % 360 if key == "rot" else number
    if key == "crop":
        try:
            parts = [max(0.0, min(0.45, float(v))) for v in value][:4]
            return parts if len(parts) == 4 else [0.0] * 4
        except (TypeError, ValueError):
            return [0.0] * 4
    if key == "rows":
        if not isinstance(value, list):
            return default
        rows = [[str(c) for c in row] if isinstance(row, list) else [str(row)] for row in value][:40]
        width = max((len(r) for r in rows), default=1)
        return [r + [""] * (width - len(r)) for r in rows] or [[""]]
    if key in {"text", "glyph", "src", "font", "role", "id"}:
        return "" if value is None else str(value)[:4000 if key == "text" else 400]
    return value


def clean_element(el: dict) -> dict:
    type_ = el.get("type")
    if type_ not in DEFAULTS:
        raise DesignError(f"Unknown element type: {type_}")
    out = {"id": str(el.get("id", "")), "type": type_}
    for key, default in {**COMMON, **DEFAULTS[type_]}.items():
        out[key] = clean_value(type_, key, el[key]) if key in el else clone(default)
    if type_ != "line":
        out["w"], out["h"] = max(1.0, out["w"]), max(1.0, out["h"])
    return out


def normalize(design: dict) -> dict:
    """A design read from disk or written by a model, made safe to render."""
    if not isinstance(design, dict):
        raise DesignError("Not a design file.")
    fmt = design.get("format") if design.get("format") in FORMATS else "slides"
    out = {"version": 1, "id": str(design.get("id") or f"design_{kit.stamp()}"),
           "title": str(design.get("title") or "Untitled design")[:120], "kind": str(design.get("kind") or fmt),
           "format": fmt, "w": int(_number(design.get("w"), FORMATS[fmt][1], 64, 8000)),
           "h": int(_number(design.get("h"), FORMATS[fmt][2], 64, 8000)), "theme": str(design.get("theme") or ""),
           "seq": int(_number(design.get("seq"), 0, 0)), "created": _number(design.get("created"), time.time()),
           "modified": _number(design.get("modified"), time.time()), "pages": []}
    palette = [color(c, None) for c in design.get("palette") or [] if isinstance(c, str)]
    if any(palette):
        out["palette"] = [c for c in palette if c][:6]
    fonts = design.get("fonts")
    if isinstance(fonts, dict):
        out["fonts"] = {k: str(v)[:80] for k, v in fonts.items() if k in {"heading", "body"} and v}
    for page in design.get("pages") or [{}]:
        if not isinstance(page, dict):
            continue
        clean = {"bg": color(page.get("bg"), "#ffffff"), "notes": str(page.get("notes") or ""), "elements": []}
        if page.get("layout"):
            clean["layout"] = str(page["layout"])[:40]
        for el in page.get("elements") or []:
            try:
                clean["elements"].append(clean_element(el))
            except (DesignError, AttributeError, TypeError):
                continue
        out["pages"].append(clean)
    if not out["pages"]:
        out["pages"].append(new_page())
    seen: set[str] = set()
    for page in out["pages"]:
        for el in page["elements"]:
            if not el["id"] or el["id"] in seen:
                out["seq"] += 1
                el["id"] = f"e{out['seq']}"
            seen.add(el["id"])
            m = re.fullmatch(r"e(\d+)", el["id"])
            if m:
                out["seq"] = max(out["seq"], int(m.group(1)))
    return out


# --- geometry ------------------------------------------------------------------------------

def bbox(el: dict) -> tuple[float, float, float, float]:
    """(left, top, right, bottom), whichever way a line points."""
    x0, y0 = el["x"], el["y"]
    x1, y1 = x0 + el["w"], y0 + el["h"]
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def center(el: dict) -> tuple[float, float]:
    left, top, right, bottom = bbox(el)
    return (left + right) / 2, (top + bottom) / 2


def contains(el: dict, x: float, y: float, tolerance: float = 0.0) -> bool:
    if el["type"] == "line":
        x0, y0, x1, y1 = el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"]
        length = (x1 - x0) ** 2 + (y1 - y0) ** 2
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / length))
        px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        return math.hypot(x - px, y - py) <= max(el["stroke_w"], 4) / 2 + tolerance
    cx, cy = center(el)
    if el.get("rot"):
        angle = math.radians(-el["rot"])
        dx, dy = x - cx, y - cy
        x, y = cx + dx * math.cos(angle) - dy * math.sin(angle), cy + dx * math.sin(angle) + dy * math.cos(angle)
    left, top, right, bottom = bbox(el)
    return left - tolerance <= x <= right + tolerance and top - tolerance <= y <= bottom + tolerance


def hit(page: dict, x: float, y: float, tolerance: float = 0.0, include_locked: bool = False) -> dict | None:
    for el in reversed(page.get("elements", [])):
        if (include_locked or not el.get("locked")) and contains(el, x, y, tolerance):
            return el
    return None


def move(el: dict, dx: float, dy: float) -> None:
    el["x"] += dx
    el["y"] += dy


# --- pages and order -------------------------------------------------------------------------

def move_page(design: dict, source: int, target: int) -> int:
    pages = design["pages"]
    if not (0 <= source < len(pages)):
        return source
    target = max(0, min(len(pages) - 1, target))
    pages.insert(target, pages.pop(source))
    return target


def duplicate_page(design: dict, index: int) -> int:
    copy = clone(design["pages"][index])
    for el in copy["elements"]:
        design["seq"] = int(design.get("seq", 0)) + 1
        el["id"] = f"e{design['seq']}"
    design["pages"].insert(index + 1, copy)
    return index + 1


def delete_page(design: dict, index: int) -> int:
    if len(design["pages"]) <= 1:
        design["pages"][0] = new_page(design["pages"][0].get("bg", "#ffffff"))
        return 0
    design["pages"].pop(index)
    return max(0, min(index, len(design["pages"]) - 1))


def duplicate(design: dict, page: dict, el: dict, offset: float = 30) -> dict:
    copy = clone(el)
    copy["x"] += offset
    copy["y"] += offset
    copy["locked"] = False
    return add(design, page, copy, page["elements"].index(el) + 1)


def arrange(page: dict, el: dict, where: str) -> None:
    """front | back | forward | backward"""
    items = page["elements"]
    index = items.index(el)
    items.pop(index)
    target = {"front": len(items), "back": 0, "forward": min(len(items), index + 1),
              "backward": max(0, index - 1)}.get(where, index)
    items.insert(target, el)


def copy_style(el: dict) -> dict:
    return {k: clone(v) for k, v in el.items() if k not in NOT_STYLE}


def paste_style(el: dict, style: dict) -> list[str]:
    changed = []
    for key, value in style.items():
        try:
            el[key] = clean_value(el["type"], key, value, el.get(key))
            changed.append(key)
        except KeyError:
            continue
    return changed


def page_text(page: dict) -> str:
    parts = []
    for el in page.get("elements", []):
        if el["type"] in {"text", "shape"} and el.get("text", "").strip():
            parts.append(el["text"].strip())
        elif el["type"] == "table":
            parts += [" | ".join(row) for row in el["rows"]]
    return "\n".join(parts)


def summary(page: dict) -> list[dict]:
    """A page as the model sees it when asked to change it: short, no file paths."""
    out = []
    for el in page.get("elements", []):
        item = {"id": el["id"], "type": el["type"], "x": round(el["x"]), "y": round(el["y"]),
                "w": round(el["w"]), "h": round(el["h"])}
        for key in ("role", "text", "shape", "font", "size", "color", "fill", "bold", "align", "glyph", "rot",
                    "opacity", "filter"):
            value = el.get(key)
            if key in el and (value not in ("", None, False, 0, 0.0) or key in {"color", "fill"}):
                item[key] = value[:200] if isinstance(value, str) else (round(value, 2) if isinstance(value, float) else value)
        if el["type"] == "table":
            item["rows"] = el["rows"][:8]
        out.append(item)
    return out


# --- files ---------------------------------------------------------------------------------

def designs_dir() -> Path:
    return kit.output_dir("designs")


def templates_dir() -> Path:
    folder = designs_dir() / "templates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def exports_dir() -> Path:
    folder = designs_dir() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def assets_dir() -> Path:
    folder = designs_dir() / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def import_asset(path: str | Path) -> str:
    """Copy a picture into assets/ (named by its content, so twice is once). Returns 'assets/<name>'."""
    source = Path(path)
    data = source.read_bytes()
    name = hashlib.sha1(data).hexdigest()[:16] + (source.suffix.lower() or ".png")
    target = assets_dir() / name
    if not target.exists():
        target.write_bytes(data)
    return f"assets/{name}"


def resolve_src(src: str) -> Path | None:
    if not src:
        return None
    path = Path(src)
    if not path.is_absolute():
        path = designs_dir() / src
    return path if path.exists() else None


def save(design: dict, path: Path | None = None, thumbnail: bool = True) -> Path:
    design["modified"] = time.time()
    path = Path(path) if path else designs_dir() / f"{design['id']}{EXT}"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    if thumbnail:
        try:
            from . import render

            render.thumbnail(design, 360).save(path.with_suffix(".png"))
        except Exception:
            pass
    return path


def load(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DesignError(f"Couldn't open {Path(path).name}: {exc}") from None
    return normalize(data)


def listing(folder: Path | None = None) -> list[dict]:
    folder = folder or designs_dir()
    out = []
    for path in folder.glob(f"*{EXT}"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        thumb = path.with_suffix(".png")
        out.append({"path": path, "title": str(data.get("title") or path.stem), "kind": str(data.get("kind") or ""),
                    "format": str(data.get("format") or ""), "pages": len(data.get("pages") or []),
                    "modified": float(data.get("modified") or path.stat().st_mtime),
                    "thumb": thumb if thumb.exists() else None})
    return sorted(out, key=lambda d: d["modified"], reverse=True)


def find_design(name: str) -> Path | None:
    """A saved design by (part of) its title, or 'last'."""
    items = listing()
    if not items:
        return None
    word = (name or "").strip().lower()
    if word in {"", "last", "latest", "recent"}:
        return items[0]["path"]
    for item in items:
        if word == item["title"].lower() or word == item["path"].stem.lower():
            return item["path"]
    for item in items:
        if word in item["title"].lower():
            return item["path"]
    return None


def delete(path: Path) -> None:
    """To the Recycle Bin where there is one, so a mistaken delete can be undone."""
    for target in (path, path.with_suffix(".png")):
        if not target.exists():
            continue
        try:
            from ..pctools import recycle

            recycle([target])
        except Exception:
            target.unlink(missing_ok=True)


def copy_design(design: dict, title: str | None = None) -> dict:
    copy = clone(design)
    copy["title"] = title or f"{design['title']} (copy)"
    copy["id"] = f"{kit.slug(copy['title'])}_{kit.stamp()}_{int(time.time() * 1000) % 1000:03d}"
    copy["created"] = copy["modified"] = time.time()
    return copy


def page_size(design: dict) -> tuple[int, int]:
    return int(design["w"]), int(design["h"])
