"""Image analysis (14.1): drop in a picture, get a real read-out.

Two halves:
  • Measured on this PC, nothing sent: size, format, file size, when and with
    what it was taken (EXIF), its main colours, and any text in it (Windows'
    own OCR, when the PC has it).
  • Read by a vision model: what the picture is, what's in it, any text, and
    what matters — a chart's numbers and trend, a form's fields, an error's
    cause and fix, a photo's details — plus your own question if you asked
    one. Real people are described, never named or identified.

The picture goes to the AI only after you say yes, like a screenshot does.
"""

from __future__ import annotations

from pathlib import Path

from . import security

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

PROMPT = """Analyse this image thoroughly but clearly. Use these headings, skipping any that don't apply:
## What it is            (one or two sentences)
## What's in it          (the main objects, places and people — describe people, never name or identify them)
## Text in it            (transcribe the important text)
## What matters          (for a chart: the numbers and the trend; a document or form: the key fields;
                          an error or code: the cause and the fix; a photo: notable details, quality, mood)
## Suggestions           (one to three useful next steps, only if they help)
{question}
Same language as the question if there is one, otherwise English. Be specific; never guess at what you can't see."""


class VisionError(Exception):
    pass


def facts(path: Path) -> dict:
    """What can be measured without sending anything."""
    from PIL import ExifTags, Image

    out: dict = {"file": path.name, "bytes": path.stat().st_size}
    with Image.open(path) as image:
        out["size"] = f"{image.width} × {image.height}"
        out["format"] = image.format or path.suffix.lstrip(".").upper()
        try:
            exif = image.getexif()
            names = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            if names.get("DateTime"):
                out["taken"] = str(names["DateTime"])
            camera = " ".join(str(names.get(k, "")).strip() for k in ("Make", "Model")).strip()
            if camera:
                out["camera"] = camera
        except Exception:
            pass
        out["colours"] = main_colours(image)
    return out


def main_colours(image, count: int = 5) -> list[str]:
    small = image.convert("RGB").resize((96, 96))
    quantised = small.quantize(colors=count, method=2)
    palette = quantised.getpalette() or []
    usage = sorted(quantised.getcolors() or [], reverse=True)
    out = []
    for _n, index in usage[:count]:
        r, g, b = palette[index * 3:index * 3 + 3]
        out.append(f"#{r:02x}{g:02x}{b:02x}")
    return out


def read_text(path: Path) -> str:
    try:
        from . import ocr

        return ocr.read_image(path).strip() if ocr.available() else ""
    except Exception:
        return ""


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def analyse(brain, path: Path, question: str = "", ask: bool = True) -> str:
    path = Path(path)
    if not path.is_file():
        raise VisionError(f"There's no picture at {path}.")
    if path.suffix.lower() not in IMAGE_TYPES:
        raise VisionError("That isn't a picture (PNG, JPG, WEBP, GIF, BMP or TIFF).")
    measured = facts(path)
    text = read_text(path)
    if ask and not security.permissions.ask(security.READ_SCREEN, f"{path.name} — to analyse it",
                                            context="Image analysis"):
        raise VisionError("Not sent. Here is what I could tell on this PC:\n" + summary(measured, text))
    from . import screen
    from PIL import Image

    with Image.open(path) as image:
        image_b64 = screen.encode(image.convert("RGB"), max_width=1600)
    extra = f"\nThe user's question — answer it first, under ## Answer: {question.strip()}" if question.strip() else ""
    if text:
        extra += f"\nText found on this PC by OCR (may have small errors): {text[:1500]}"
    reply = brain.ask_once(PROMPT.format(question=extra), image_b64=image_b64)
    security.audit.record("image analysis", path.name, question[:80])
    return f"🔍 {path.name}\n\n{reply.strip()}\n\n---\n{summary(measured, '')}"


def summary(measured: dict, text: str = "") -> str:
    lines = [f"{measured.get('format', '')} · {measured.get('size', '')} · {_size(measured.get('bytes', 0))}"]
    if measured.get("taken") or measured.get("camera"):
        lines.append(" · ".join(x for x in (measured.get("taken", ""), measured.get("camera", "")) if x))
    if measured.get("colours"):
        lines.append("Main colours: " + "  ".join(measured["colours"]))
    if text:
        lines.append("Text: " + text[:600])
    return "\n".join(lines)
