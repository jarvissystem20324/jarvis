"""Content creators (10.0): the parts that aren't just writing — real YouTube
search suggestions for keyword ideas, splitting a thread so every post fits,
seeing a thumbnail the way viewers will (small, in a feed, among others), and
stream overlays for OBS.

The feed preview is a plain, unbranded layout with a video site's
proportions (16:9 thumbnails, two-line titles, channel and views under them);
it's for judging whether a thumbnail and title read at the size people see
them, not a copy of anyone's site.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from . import kit

# --- keyword ideas ------------------------------------------------------------------------------

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"


def youtube_suggestions(query: str, lang: str = "") -> list[str]:
    """What people actually type into YouTube's search box, starting with `query`."""
    params = {"client": "firefox", "ds": "yt", "q": query, "ie": "utf-8", "oe": "utf-8"}
    if lang:
        params["hl"] = lang
    try:
        data = kit.get_json(SUGGEST_URL, params)
    except kit.KitError:
        return []
    return [s for s in (data[1] if isinstance(data, list) and len(data) > 1 else []) if isinstance(s, str)]


def keyword_ideas(topic: str, lang: str = "") -> list[str]:
    """Suggestions for the topic and the usual ways people phrase it, without repeats."""
    from . import i18n

    seen, out = set(), []
    # Turkish phrasings when JARVIS speaks Turkish or the topic plainly is
    # (letters alone miss "kahve demleme", hence the language setting too).
    turkish = (lang or i18n.current()) == "tr" or bool(re.search(r"[çğıöşü]", topic.lower()))
    variants = ((topic, f"{topic} nasıl", f"en iyi {topic}", f"{topic} için", f"{topic} vs") if turkish else
                (topic, f"how to {topic}", f"best {topic}", f"{topic} for beginners", f"{topic} vs"))
    for query in variants:
        for suggestion in youtube_suggestions(query, "tr" if turkish else lang):
            key = suggestion.lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(suggestion.strip())
    return out


# --- threads ------------------------------------------------------------------------------------------

def split_thread(text: str, limit: int = 280, number: bool = True) -> list[str]:
    """Posts of at most `limit` characters, broken between sentences where it can
    and between words where it must, each numbered "1/6" if asked."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\d+[/.)]\s)", text.strip()) if p.strip()]
    # Leave room for " 12/12".
    room = limit - (7 if number else 0)
    posts: list[str] = []
    for paragraph in paragraphs:
        paragraph = re.sub(r"^\d+\s*[/.)]\s*(\d+\s+)?", "", paragraph).strip()     # numbering the AI added
        current = ""
        for sentence in re.split(r"(?<=[.!?…])\s+", paragraph):
            for piece in (textwrap.wrap(sentence, room) if len(sentence) > room else [sentence]):
                if not current:
                    current = piece
                elif len(current) + 1 + len(piece) <= room:
                    current += " " + piece
                else:
                    posts.append(current)
                    current = piece
        if current:
            posts.append(current)
    if number and len(posts) > 1:
        posts = [f"{post} {i}/{len(posts)}" for i, post in enumerate(posts, 1)]
    return posts


# --- the feed preview ------------------------------------------------------------------------------

def _font(size: int, bold: bool = False):
    from .charts import _font as chart_font

    return chart_font(size, bold)


def _cover(image, size: tuple[int, int]):
    """Fill `size` exactly, cropping the middle, as a video site crops a thumbnail."""
    from PIL import ImageOps

    return ImageOps.fit(image.convert("RGB"), size)


def _title_lines(draw, text: str, font, width: int, lines: int = 2) -> list[str]:
    words, out, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            out.append(line)
            line = word
            if len(out) == lines:
                break
    if len(out) < lines and line:
        out.append(line)
    if len(out) == lines and " ".join(out) != text.strip():
        last = out[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out[:lines]


def feed_preview(thumbnail: Path, title: str, channel: str = "Your channel", dark: bool = True,
                 out: Path | None = None) -> Path:
    """Your thumbnail and title at desktop and phone size, next to grey placeholders."""
    from PIL import Image, ImageDraw

    bg, fg, muted, card = (("#0f0f0f", "#f1f1f1", "#aaaaaa", "#272727") if dark else
                           ("#ffffff", "#0f0f0f", "#606060", "#e5e5e5"))
    width, height = 1400, 760
    canvas = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(canvas)
    with Image.open(thumbnail) as source:
        picture = source.convert("RGB")
    title_font, small_font = _font(18, True), _font(15)
    tile_w, tile_h, gap, left = 360, 202, 24, 40

    def card_at(x: int, y: int, mine: bool, scale: float = 1.0) -> None:
        w, h = int(tile_w * scale), int(tile_h * scale)
        if mine:
            canvas.paste(_cover(picture, (w, h)), (x, y))
            badge = _font(max(9, int(14 * scale)))
            bw = int(draw.textlength("12:34", font=badge)) + 10
            bh = int(20 * scale) + 4
            draw.rounded_rectangle((x + w - bw - 6, y + h - bh - 6, x + w - 6, y + h - 6), 4, fill="#000000")
            draw.text((x + w - bw - 1, y + h - bh - 5), "12:34", font=badge, fill="#ffffff")
        else:
            draw.rounded_rectangle((x, y, x + w, y + h), 10, fill=card)
        draw.ellipse((x, y + h + 12, x + 36 * scale, y + h + 12 + 36 * scale), fill="#3ea6ff" if mine else card)
        text_x = x + int(48 * scale)
        if mine:
            font = _font(int(18 * scale), True)
            for i, line in enumerate(_title_lines(draw, title, font, w - int(48 * scale))):
                draw.text((text_x, y + h + 10 + i * int(24 * scale)), line, font=font, fill=fg)
            info = _font(int(15 * scale))
            draw.text((text_x, y + h + 10 + int(52 * scale)), channel, font=info, fill=muted)
            draw.text((text_x, y + h + 10 + int(72 * scale)), "12K views · 2 days ago", font=info, fill=muted)
        else:
            for i, length in enumerate((0.9, 0.6)):
                top = y + h + 14 + i * 24
                draw.rounded_rectangle((text_x, top, text_x + (w - 48) * length, top + 14), 6, fill=card)

    draw.text((left, 16), "Desktop feed", font=title_font, fill=muted)
    for i in range(3):
        card_at(left + i * (tile_w + gap), 50, mine=i == 1)
    draw.text((left, 390), "Phone (smaller still)", font=title_font, fill=muted)
    for i in range(4):
        card_at(left + i * (int(tile_w * 0.62) + gap), 424, mine=i == 0, scale=0.62)
    draw.text((left, height - 34), "Can you read it at the small size? Is the face or the subject clear?",
              font=small_font, fill=muted)
    target = out or kit.output_dir("images") / f"feed-preview_{kit.stamp()}.png"
    canvas.save(target)
    return target


# --- stream overlays -------------------------------------------------------------------------------

def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.strip().lstrip("#")
    if len(colour) == 3:
        colour = "".join(c * 2 for c in colour)
    try:
        return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0, 212, 255)


def stream_overlays(name: str, colour: str = "#00d4ff", folder: Path | None = None,
                    socials: str = "") -> list[Path]:
    """A set for OBS at 1920×1080: a webcam frame and a lower third (both see-through),
    and Starting soon / Be right back / Thanks for watching screens."""
    from PIL import Image, ImageDraw, ImageFilter

    folder = folder or kit.output_dir("images") / f"overlays_{kit.slug(name)}_{kit.stamp()}"
    folder.mkdir(parents=True, exist_ok=True)
    accent = _rgb(colour)
    dark = (10, 14, 23)
    made = []

    frame = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle((4, 4, 635, 355), 18, outline=accent + (255,), width=8)
    d.rounded_rectangle((20, 312, 20 + 24 + int(d.textlength(name, font=_font(24, True))), 350), 10,
                        fill=dark + (230,))
    d.text((32, 315), name, font=_font(24, True), fill=accent + (255,))
    made.append(folder / "webcam-frame.png")
    frame.save(made[-1])

    lower = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(lower)
    big, small = _font(54, True), _font(30)
    width = int(max(d.textlength(name, font=big), d.textlength(socials or " ", font=small))) + 120
    d.rounded_rectangle((60, 850, 60 + width, 1010), 20, fill=dark + (225,))
    d.rectangle((60, 850, 76, 1010), fill=accent + (255,))
    d.text((110, 868), name, font=big, fill=(255, 255, 255, 255))
    if socials:
        d.text((112, 945), socials, font=small, fill=accent + (255,))
    made.append(folder / "lower-third.png")
    lower.save(made[-1])

    for file, headline in (("starting-soon.png", "Starting soon"), ("be-right-back.png", "Be right back"),
                           ("thanks-for-watching.png", "Thanks for watching")):
        screen = Image.new("RGB", (1920, 1080), dark)
        glow = Image.new("RGB", (1920, 1080), dark)
        ImageDraw.Draw(glow).ellipse((560, 140, 1360, 940), fill=tuple(int(a * 0.55) for a in accent))
        screen = Image.blend(screen, glow.filter(ImageFilter.GaussianBlur(220)), 0.9)
        d = ImageDraw.Draw(screen)
        title = _font(120, True)
        w = d.textlength(headline, font=title)
        d.text(((1920 - w) / 2, 400), headline, font=title, fill=(255, 255, 255))
        sub = _font(44)
        w = d.textlength(name, font=sub)
        d.text(((1920 - w) / 2, 560), name, font=sub, fill=accent)
        if socials:
            w = d.textlength(socials, font=_font(34))
            d.text(((1920 - w) / 2, 640), socials, font=_font(34), fill=(200, 210, 225))
        d.rectangle((760, 720, 1160, 726), fill=accent)
        made.append(folder / file)
        screen.save(made[-1])
    return made
