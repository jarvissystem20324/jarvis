"""The fonts this PC has, by family name, and a cached loader for Pillow.

Pillow wants a file, people pick a family ("Georgia", "Segoe UI"), so the
font folders are read once — each file's family and style straight from its
name table — and kept as {family: {style: (path, index)}}. A family that is
missing falls back to Segoe UI, Arial or DejaVu Sans, never to an error: a
design made on another PC still opens and renders.
"""

from __future__ import annotations

import os
import sys
import threading
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FALLBACKS = ("Segoe UI", "Arial", "Helvetica", "DejaVu Sans", "Liberation Sans")
# Families shown first in the picker: on every Windows PC, and they read well.
POPULAR = ("Segoe UI", "Arial", "Calibri", "Cambria", "Georgia", "Times New Roman", "Verdana", "Tahoma",
           "Trebuchet MS", "Impact", "Comic Sans MS", "Bahnschrift", "Candara", "Constantia", "Corbel",
           "Franklin Gothic Medium", "Palatino Linotype", "Book Antiqua", "Century Gothic", "Gabriola",
           "Segoe Print", "Segoe Script", "Ink Free", "Rockwell", "Consolas", "Courier New")
EMOJI_FILES = ("seguiemj.ttf", "NotoColorEmoji.ttf", "Apple Color Emoji.ttc")
SYMBOL_FILES = ("seguisym.ttf", "DejaVuSans.ttf")

_lock = threading.Lock()
_catalog: dict[str, dict[str, tuple[str, int]]] | None = None


def font_dirs() -> list[Path]:
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]


def _style_key(style: str) -> str:
    low = (style or "").lower()
    bold = "bold" in low and "semibold" not in low.replace(" ", "")
    italic = "italic" in low or "oblique" in low
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    if low in {"regular", "normal", "book", "roman", "medium", ""}:
        return "regular"
    return low


def scan() -> dict[str, dict[str, tuple[str, int]]]:
    found: dict[str, dict[str, tuple[str, int]]] = {}
    for folder in font_dirs():
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            for index in range(4 if path.suffix.lower() == ".ttc" else 1):
                try:
                    family, style = ImageFont.truetype(str(path), 12, index=index).getname()
                except Exception:
                    break
                if not family:
                    continue
                styles = found.setdefault(family, {})
                styles.setdefault(_style_key(style), (str(path), index))
    return found


def catalog() -> dict[str, dict[str, tuple[str, int]]]:
    global _catalog
    with _lock:
        if _catalog is None:
            _catalog = scan()
        return _catalog


def warm() -> None:
    """Read the font folders on a worker, so the picker opens instantly."""
    threading.Thread(target=catalog, daemon=True).start()


def families() -> list[str]:
    names = [n for n in catalog() if not n.startswith((".", "@"))]
    popular = [n for n in POPULAR if n in names]
    rest = sorted((n for n in names if n not in popular), key=str.lower)
    return popular + rest


def has(family: str) -> bool:
    return family in catalog()


def resolve(family: str, bold: bool = False, italic: bool = False) -> tuple[str, int] | None:
    cat = catalog()
    for name in (family, *FALLBACKS):
        styles = cat.get(name)
        if not styles:
            continue
        wanted = ("bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular")
        for key in (wanted, "bold" if bold else "regular", "regular", next(iter(styles))):
            if key in styles:
                return styles[key]
    return None


@lru_cache(maxsize=256)
def _load(path: str, index: int, size: int):
    return ImageFont.truetype(path, size, index=index)


def get(family: str, size: float, bold: bool = False, italic: bool = False):
    size = max(4, int(round(size)))
    found = resolve(family or "Segoe UI", bold, italic)
    if found:
        try:
            return _load(found[0], found[1], size)
        except OSError:
            pass
    from .. import drawing

    return drawing.font(size, bold)


def _special(files: tuple[str, ...]):
    for folder in font_dirs():
        for name in files:
            path = folder / name
            if path.exists():
                return str(path)
    return None


@lru_cache(maxsize=64)
def emoji(size: int):
    """(font, True) for a colour emoji font, else (a plain font, False)."""
    path = _special(EMOJI_FILES)
    if path:
        try:
            return ImageFont.truetype(path, max(4, int(size))), True
        except OSError:
            pass
    return symbol(size), False


@lru_cache(maxsize=64)
def symbol(size: int):
    path = _special(SYMBOL_FILES)
    if path:
        try:
            return ImageFont.truetype(path, max(4, int(size)))
        except OSError:
            pass
    return get("Segoe UI", size)
