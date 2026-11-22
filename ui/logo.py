"""The JARVIS mark (14.3), drawn in code so it is sharp at every size.

A deep navy rounded square ("squircle") with a soft inner light, and a bold
"J" whose stroke runs from cyan to violet, with a small spark at the top right
of the hook. Rendered at 4x and scaled down, so the curves are smooth.

The same drawing makes the window icon, the EXE's .ico and the sidebar logo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

CYAN = (0, 212, 255)
VIOLET = (139, 92, 246)
NAVY_TOP = (22, 30, 52)
NAVY_BOTTOM = (8, 11, 22)


def _gradient(size: int, top: tuple, bottom: tuple, diagonal: bool = False) -> Image.Image:
    """A vertical (or diagonal) colour ramp."""
    ramp = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        ramp.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    image = ramp.resize((size, size), Image.BICUBIC)
    if diagonal:
        image = image.rotate(-35, resample=Image.BICUBIC, expand=False, fillcolor=bottom)
    return image


def make(size: int = 256, background: bool = True) -> Image.Image:
    """The logo as an RGBA image, `size` pixels square."""
    s = max(16, size) * 4
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    if background:
        # The squircle: navy, lit a little from the top.
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.25), fill=255)
        out.paste(_gradient(s, NAVY_TOP, NAVY_BOTTOM), (0, 0), mask)
        # A thin light edge, so it reads on dark taskbars too.
        edge = Image.new("L", (s, s), 0)
        inset = int(s * 0.012)
        ImageDraw.Draw(edge).rounded_rectangle([inset, inset, s - 1 - inset, s - 1 - inset],
                                               radius=int(s * 0.24), outline=70, width=max(2, s // 110))
        out.paste(Image.new("RGBA", (s, s), (*CYAN, 255)), (0, 0), edge)

    # The J: a stem and a hook, one thick stroke.
    j = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(j)
    w = int(s * 0.13)                      # stroke width
    stem_x = int(s * 0.60)
    top, hook_bottom = int(s * 0.20), int(s * 0.74)
    left = int(s * 0.27)
    cy = int(s * 0.56)
    # Rounded at the top, square where it meets the hook, so the two join seamlessly.
    draw.rounded_rectangle([stem_x - w // 2, top, stem_x + w // 2, cy], radius=w // 2, fill=255)
    draw.rectangle([stem_x - w // 2, top + w, stem_x + w // 2, cy + 2], fill=255)
    # The hook: the lower half of a ring from the stem round to the left.
    radius = (stem_x - left) // 2
    cx = left + radius
    draw.arc([cx - radius - w // 2, cy - radius - w // 2, cx + radius + w // 2, cy + radius + w // 2],
             start=0, end=180, fill=255, width=w)
    # Round the hook's tip.
    tip_x = cx - radius
    draw.ellipse([tip_x - w // 2, cy - w // 2, tip_x + w // 2, cy + w // 2], fill=255)
    # Spark: a small dot up and to the right of the stem.
    spark = int(s * 0.055)
    sx, sy = int(s * 0.77), int(s * 0.22)
    draw.ellipse([sx - spark, sy - spark, sx + spark, sy + spark], fill=255)
    del hook_bottom

    colour = _gradient(s, CYAN, VIOLET, diagonal=True).convert("RGBA")
    # A soft glow under the J, then the J itself.
    glow = j.filter(ImageFilter.GaussianBlur(s * 0.03)).point(lambda v: int(v * 0.35))
    out.paste(Image.new("RGBA", (s, s), (*CYAN, 255)), (0, 0), glow)
    out.paste(colour, (0, 0), j)
    return out.resize((size, size), Image.LANCZOS)


def ico_path() -> Path:
    """Where the .ico lives, in the source tree or inside the EXE."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "jarvis.ico"


def write_assets(root: Path) -> None:
    """Regenerate assets/jarvis.ico and assets/jarvis.png."""
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    big = make(256)
    big.save(assets / "jarvis.png")
    big.save(assets / "jarvis.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
