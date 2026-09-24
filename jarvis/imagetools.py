"""Image tools by asking: "make this 800px wide as a JPG".

Works on the image you last dropped, attached, generated or named. The
original is never touched — every result is a new file next to it, named
for what was done. Pillow does the work locally; nothing is uploaded.

Understood, in any combination:
  800px wide / 600 tall / 1920x1080 / half size / 50%
  as jpg | png | webp | pdf        compress (to 200kb)       quality 70
  crop square | crop to 16:9       rotate 90 | rotate left    flip | mirror
  grayscale / black and white       remove metadata (always done on save)
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "pdf": "PDF",
           "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "ico": "ICO"}


class ImageToolError(Exception):
    pass


@dataclass
class Plan:
    width: int | None = None
    height: int | None = None
    scale: float | None = None
    fmt: str | None = None
    quality: int | None = None
    target_kb: int | None = None
    crop: str | None = None          # "square" or "W:H"
    rotate: int = 0
    flip: str | None = None          # "h" | "v"
    gray: bool = False
    steps: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not any((self.width, self.height, self.scale, self.fmt, self.quality,
                        self.target_kb, self.crop, self.rotate, self.flip, self.gray))


def parse(text: str) -> Plan:
    t = text.lower()
    plan = Plan()
    if m := re.search(r"(\d{2,5})\s*[x×]\s*(\d{2,5})", t):
        plan.width, plan.height = int(m.group(1)), int(m.group(2))
    if m := re.search(r"(\d{2,5})\s*(?:px|pixels?)?\s*(?:wide|width|genişlik)", t) or \
            re.search(r"width\s*(?:of|to|=)?\s*(\d{2,5})", t):
        plan.width = int(m.group(1))
    if m := re.search(r"(\d{2,5})\s*(?:px|pixels?)?\s*(?:tall|high|height|yükseklik)", t) or \
            re.search(r"height\s*(?:of|to|=)?\s*(\d{2,5})", t):
        plan.height = int(m.group(1))
    if "half" in t:
        plan.scale = 0.5
    elif "double" in t or "twice" in t:
        plan.scale = 2.0
    elif m := re.search(r"(\d{1,3})\s*%", t):
        plan.scale = int(m.group(1)) / 100
    if m := re.search(r"\b(?:as|to|into|convert(?:\s+it)?\s+to|save as|format)\s+(?:an?\s+)?\.?(jpe?g|png|webp|pdf|bmp|gif|tiff|ico)\b", t) \
            or re.search(r"\b(jpe?g|png|webp|pdf|bmp|gif|tiff|ico)\b", t):
        plan.fmt = m.group(1).replace("jpeg", "jpg")
    if m := re.search(r"quality\s*(\d{1,3})", t):
        plan.quality = max(5, min(100, int(m.group(1))))
    if m := re.search(r"(?:under|below|to|max)\s*(\d{2,5})\s*kb", t):
        plan.target_kb = int(m.group(1))
    elif re.search(r"\bcompress|smaller file|reduce (?:the )?(?:file )?size|küçült", t):
        plan.quality = plan.quality or 70
    if re.search(r"crop[^.]*square|square crop|\bsquare\b", t):
        plan.crop = "square"
    elif m := re.search(r"crop[^.]*?(\d{1,2})\s*:\s*(\d{1,2})", t):
        plan.crop = f"{m.group(1)}:{m.group(2)}"
    if m := re.search(r"rotate\s*(-?\d{2,3})", t):
        plan.rotate = int(m.group(1)) % 360
    elif "rotate left" in t or "counterclockwise" in t or "anticlockwise" in t:
        plan.rotate = 90
    elif "rotate right" in t or "clockwise" in t or "rotate" in t:
        plan.rotate = 270
    if "upside down" in t:
        plan.rotate = 180
    if "flip vertical" in t or "flip it vertical" in t:
        plan.flip = "v"
    elif "flip" in t or "mirror" in t:
        plan.flip = "h"
    if re.search(r"gr[ae]y ?scale|black and white|b&w|siyah beyaz|\bgr[ae]y\b", t):
        plan.gray = True
    return plan


def apply(source: Path, plan: Plan) -> tuple[Path, list[str]]:
    from PIL import Image, ImageOps

    source = Path(source)
    if not source.is_file():
        raise ImageToolError(f"No such image:\n  {source}")
    if plan.empty:
        raise ImageToolError(
            "I couldn't tell what to change. Try: '800px wide', 'as jpg', "
            "'compress to 200kb', 'crop square', 'rotate 90', 'grayscale'."
        )
    done: list[str] = []
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
    original_size = image.size

    if plan.crop:
        w, h = image.size
        if plan.crop == "square":
            ratio = 1.0
        else:
            a, b = (int(x) for x in plan.crop.split(":"))
            ratio = a / b if b else 1.0
        if w / h > ratio:
            new_w = int(h * ratio)
            left = (w - new_w) // 2
            image = image.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / ratio)
            top = (h - new_h) // 2
            image = image.crop((0, top, w, top + new_h))
        done.append(f"cropped to {plan.crop} ({image.width}×{image.height})")
    if plan.rotate:
        image = image.rotate(plan.rotate, expand=True)
        done.append(f"rotated {plan.rotate}°")
    if plan.flip:
        image = ImageOps.mirror(image) if plan.flip == "h" else ImageOps.flip(image)
        done.append("flipped" if plan.flip == "v" else "mirrored")
    if plan.gray:
        image = ImageOps.grayscale(image)
        done.append("grayscale")

    w, h = image.size
    if plan.width and plan.height:
        size = (plan.width, plan.height)
        image = ImageOps.fit(image, size, Image.LANCZOS)
    elif plan.width:
        size = (plan.width, max(1, round(h * plan.width / w)))
        image = image.resize(size, Image.LANCZOS)
    elif plan.height:
        size = (max(1, round(w * plan.height / h)), plan.height)
        image = image.resize(size, Image.LANCZOS)
    elif plan.scale:
        size = (max(1, round(w * plan.scale)), max(1, round(h * plan.scale)))
        image = image.resize(size, Image.LANCZOS)
    if image.size != (w, h):
        done.append(f"resized {original_size[0]}×{original_size[1]} → {image.width}×{image.height}")

    ext = plan.fmt or source.suffix.lower().lstrip(".") or "png"
    ext = "jpg" if ext == "jpeg" else ext
    fmt = FORMATS.get(ext)
    if fmt is None:
        raise ImageToolError(f"I can't write .{ext} files.")
    if fmt in {"JPEG", "PDF"} and image.mode not in {"RGB", "L"}:
        background = Image.new("RGB", image.size, "white")
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    if plan.fmt:
        done.append(f"converted to {ext.upper()}")

    params: dict = {}
    if fmt in {"JPEG", "WEBP"}:
        params["quality"] = plan.quality or 88
        params["optimize"] = True
    elif fmt == "PNG":
        params["optimize"] = True
    if plan.target_kb and fmt in {"JPEG", "WEBP"}:
        # Walk the quality down until it fits; saving again is cheap.
        limit = plan.target_kb * 1024

        def fits(img, q) -> bool:
            buffer = io.BytesIO()
            img.save(buffer, fmt, quality=q, optimize=True)
            return buffer.tell() <= limit

        quality = params["quality"]
        already = source.stat().st_size <= limit and fmt == FORMATS.get(source.suffix.lower().lstrip("."))
        for quality in range(params["quality"], 29, -6):
            if fits(image, quality):
                break
        else:
            already = False
            # Quality alone cannot get there without the picture falling
            # apart, so give up pixels instead, keeping quality usable.
            quality = 60
            for _ in range(12):
                if fits(image, quality):
                    break
                image = image.resize((max(1, int(image.width * 0.85)),
                                      max(1, int(image.height * 0.85))), Image.LANCZOS)
            done.append(f"scaled to {image.width}×{image.height} to fit")
        params["quality"] = quality
        done.append(f"compressed to quality {quality}" if not already
                    else f"already under {plan.target_kb} KB — saved at quality {quality}")
    elif plan.target_kb:
        done.append("(size targets only apply to JPG and WebP — add 'as jpg')")
    elif plan.quality and fmt in {"JPEG", "WEBP"}:
        done.append(f"quality {params['quality']}")
    # Named for what was done, and never over an existing file.
    tag = "-".join(re.sub(r"[^a-z0-9]+", "", d.split(" ")[0]) for d in done
                   if not d.startswith("(")) or "copy"
    out = source.with_name(f"{source.stem}_{tag[:40]}.{ext}")
    counter = 2
    while out.exists():
        out = source.with_name(f"{source.stem}_{tag[:40]}_{counter}.{ext}")
        counter += 1
    # Saving from pixels drops EXIF, which is where GPS locations live.
    image.save(out, fmt, **params)
    before, after = source.stat().st_size, out.stat().st_size
    done.append(f"{before / 1024:,.0f} KB → {after / 1024:,.0f} KB")
    return out, done
