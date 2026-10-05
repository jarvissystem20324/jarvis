"""10.0 templates: CVs, book covers, event tickets, infographics, Instagram
carousels and calendar pages. Same shape as the rest — (content, style) ->
design — and registered in templates.KINDS, so the gallery, "Describe it",
the brand kit and the palettes all work on them.
"""

from __future__ import annotations

import calendar
import datetime as dt

from . import model
from .templates import KINDS, Builder, _c, _style, upper

def _title(content: dict | None, default: str) -> str:
    """The main words: a "title", or whatever the content calls it ("headline", "event", "name")."""
    for key in ("title", "event", "headline", "name"):
        if (content or {}).get(key):
            return str(content[key])
    return default


# --- CVs (A4, 1240 x 1754) ----------------------------------------------------------------------------

SAMPLE_CV = {
    "name": "Elif Yılmaz", "title": "Product Designer",
    "contact": ["elif.yilmaz@mail.com", "+90 532 000 00 00", "İstanbul, Türkiye", "linkedin.com/in/elifyilmaz"],
    "summary": "Designer with six years of turning messy problems into simple, friendly products. "
               "Happiest between research, sketches and shipping.",
    "experience": [
        {"role": "Senior Product Designer", "place": "Getir", "dates": "2023 – now",
         "text": "Led the redesign of checkout; orders up 14%. Built the design system used by 40 people."},
        {"role": "Product Designer", "place": "Trendyol", "dates": "2020 – 2023",
         "text": "Designed the seller app from scratch, from interviews to launch."},
        {"role": "UI Designer", "place": "Freelance", "dates": "2018 – 2020",
         "text": "Websites and brands for 20+ small businesses."}],
    "education": [{"role": "BA Visual Communication Design", "place": "Bilkent University", "dates": "2014 – 2018"}],
    "skills": ["Figma", "User research", "Prototyping", "Design systems", "HTML & CSS"],
    "languages": ["Turkish (native)", "English (fluent)", "German (basic)"],
}


def _list(content: dict | None, key: str) -> list:
    value = (content or {}).get(key)
    if isinstance(value, str):
        value = [v.strip() for v in value.replace(";", "\n").split("\n") if v.strip()]
    return value if isinstance(value, list) and value else SAMPLE_CV[key]


def _jobs(content: dict | None, key: str) -> list[dict]:
    items = [i for i in _list(content, key) if isinstance(i, dict)]
    return items or SAMPLE_CV[key]


def _initials(name: str) -> str:
    words = [w for w in name.split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "CV"


def _section(b: Builder, title: str, x, y, w, colour, line_colour=None) -> float:
    b.text(upper(title), x, y, w, 44, role="section", size=26, color=colour, bold=True, valign="middle",
           autofit=False, font=b.heading)
    b.line(x, y + 52, x + w, y + 52, stroke=line_colour or colour, stroke_w=2)
    return y + 74


def _entries(b: Builder, items: list[dict], x, y, w, bottom, colours: dict, with_text: bool = True) -> float:
    for item in items:
        if y > bottom - 90:
            break
        b.text(str(item.get("role", "")), x, y, w * 0.7, 42, role="entry", size=30, color=colours["head"], bold=True,
               valign="middle")
        b.text(str(item.get("dates", "")), x + w * 0.7, y, w * 0.3, 42, role="dates", size=24, color=colours["muted"],
               align="right", valign="middle")
        b.text(str(item.get("place", "")), x, y + 42, w, 36, role="place", size=25, color=colours["accent"],
               valign="middle")
        y += 84
        if with_text and item.get("text"):
            b.text(str(item["text"]), x, y, w, 70, role="body", size=24, color=colours["body"], line=1.3)
            y += 82
        y += 18
    return y


def cv_modern(content=None, style=None) -> dict:
    s = _style(style, "corporate", "Segoe UI", "Segoe UI")
    name = _c(content, "name", SAMPLE_CV["name"])
    b = Builder("cv", "poster", name, s, bg="#ffffff")
    side = 430
    b.shape("rect", 0, 0, side, 1754, fill=b.primary)
    photo = _c(content, "photo")
    if photo:
        b.picture(photo, 95, 90, 240, 240, circle=True, stroke="#ffffff", stroke_w=6)
    else:
        b.shape("ellipse", 95, 90, 240, 240, role="photo", fill=b.secondary, text=_initials(name), size=90,
                bold=True, color="#ffffff", stroke="#ffffff", stroke_w=6)
    ink, soft = "#ffffff", model.mix("#ffffff", b.primary, 0.25)
    y = _section(b, "Contact", 60, 390, side - 120, ink, soft)
    for line in _list(content, "contact")[:5]:
        b.text(str(line), 60, y, side - 110, 40, role="contact", size=22, color=ink, valign="middle")
        y += 48
    y = _section(b, "Skills", 60, y + 40, side - 120, ink, soft)
    for skill in _list(content, "skills")[:8]:
        b.text(f"•  {skill}", 60, y, side - 110, 40, role="skill", size=23, color=ink, valign="middle")
        y += 46
    y = _section(b, "Languages", 60, y + 40, side - 120, ink, soft)
    for language in _list(content, "languages")[:4]:
        b.text(str(language), 60, y, side - 110, 40, role="language", size=23, color=ink, valign="middle")
        y += 46
    x, w = side + 70, 1240 - side - 140
    b.text(name, x, 90, w, 120, role="name", size=78, color=b.dark, bold=True, valign="bottom", line=1.0)
    b.text(_c(content, "title", SAMPLE_CV["title"]), x, 214, w, 56, role="subtitle", size=36, color=b.primary,
           valign="middle")
    b.text(_c(content, "summary", SAMPLE_CV["summary"]), x, 300, w, 150, role="body", size=25, color="#374151",
           line=1.4)
    colours = {"head": b.dark, "muted": "#6b7280", "accent": b.primary, "body": "#374151"}
    y = _section(b, "Experience", x, 490, w, b.dark, b.primary)
    y = _entries(b, _jobs(content, "experience")[:4], x, y, w, 1420, colours)
    y = _section(b, "Education", x, y + 10, w, b.dark, b.primary)
    _entries(b, _jobs(content, "education")[:2], x, y, w, 1730, colours, with_text=False)
    return b.d


def cv_classic(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Georgia", "Segoe UI")
    name = _c(content, "name", SAMPLE_CV["name"])
    b = Builder("cv", "poster", name, s, bg="#ffffff")
    b.text(name, 100, 80, 1040, 120, role="name", size=84, color=b.dark, align="center", valign="middle")
    b.text(upper(_c(content, "title", SAMPLE_CV["title"])), 100, 200, 1040, 50, role="subtitle", size=30,
           color=b.accent, align="center", valign="middle", font=b.body)
    b.text("  ·  ".join(str(c) for c in _list(content, "contact")[:4]), 100, 262, 1040, 44, role="contact", size=22,
           color="#4b5563", align="center", valign="middle", font=b.body)
    b.line(100, 330, 1140, 330, stroke=b.dark, stroke_w=3)
    b.text(_c(content, "summary", SAMPLE_CV["summary"]), 100, 356, 1040, 130, role="body", size=26,
           color="#374151", align="center", italic=True, line=1.4, font=b.body)
    colours = {"head": b.dark, "muted": "#6b7280", "accent": b.accent, "body": "#374151"}
    y = _section(b, "Experience", 100, 520, 1040, b.dark, "#d1d5db")
    y = _entries(b, _jobs(content, "experience")[:4], 100, y, 1040, 1350, colours)
    y = _section(b, "Education", 100, y + 6, 1040, b.dark, "#d1d5db")
    y = _entries(b, _jobs(content, "education")[:2], 100, y, 1040, 1560, colours, with_text=False)
    half = 500
    top = max(y + 6, 1440)
    _section(b, "Skills", 100, top, half, b.dark, "#d1d5db")
    b.text("  ·  ".join(str(v) for v in _list(content, "skills")[:8]), 100, top + 78, half, 150, role="skill",
           size=24, color="#374151", line=1.4, font=b.body)
    _section(b, "Languages", 640, top, half, b.dark, "#d1d5db")
    b.text("\n".join(str(v) for v in _list(content, "languages")[:4]), 640, top + 78, half, 150, role="language",
           size=24, color="#374151", line=1.4, font=b.body)
    return b.d


def cv_bold(content=None, style=None) -> dict:
    s = _style(style, "tech", "Bahnschrift", "Segoe UI")
    name = _c(content, "name", SAMPLE_CV["name"])
    b = Builder("cv", "poster", name, s, bg="#f8fafc")
    b.shape("rect", 0, 0, 1240, 380, fill=b.dark)
    b.shape("rect", 0, 372, 1240, 12, fill=b.accent)
    photo = _c(content, "photo")
    if photo:
        b.picture(photo, 900, 70, 250, 250, circle=True, stroke=b.accent, stroke_w=8)
    else:
        b.shape("ellipse", 900, 70, 250, 250, role="photo", fill=b.primary, text=_initials(name), size=96, bold=True,
                color="#ffffff", stroke=b.accent, stroke_w=8)
    b.text(upper(name), 90, 90, 780, 140, role="name", size=88, color="#ffffff", bold=True, valign="bottom", line=1.0)
    b.text(_c(content, "title", SAMPLE_CV["title"]), 90, 240, 780, 60, role="subtitle", size=38, color=b.accent,
           valign="middle")
    b.text(_c(content, "summary", SAMPLE_CV["summary"]), 90, 430, 1060, 120, role="body", size=26,
           color="#334155", line=1.4)
    colours = {"head": b.dark, "muted": "#64748b", "accent": b.primary, "body": "#334155"}
    y = _section(b, "Experience", 90, 590, 680, b.primary)
    y = _entries(b, _jobs(content, "experience")[:4], 90, y, 680, 1440, colours)
    y = _section(b, "Education", 90, y + 6, 680, b.primary)
    _entries(b, _jobs(content, "education")[:2], 90, y, 680, 1720, colours, with_text=False)
    b.shape("round", 830, 590, 330, 1080, role="panel", fill="#ffffff", radius=24, shadow=True)
    y = _section(b, "Skills", 865, 620, 260, b.primary)
    for skill in _list(content, "skills")[:8]:
        b.shape("round", 865, y, 260, 48, role="skill", fill=model.mix(b.primary, "#ffffff", 0.85), text=str(skill),
                color=b.dark, size=22, radius=24, font=b.body)
        y += 62
    y = _section(b, "Languages", 865, y + 30, 260, b.primary)
    for language in _list(content, "languages")[:4]:
        b.text(str(language), 865, y, 260, 40, role="language", size=22, color="#334155", valign="middle")
        y += 46
    for line in _list(content, "contact")[:4]:
        if y > 1600:
            break
        b.text(str(line), 865, y + 30, 260, 36, role="contact", size=19, color="#64748b", valign="middle")
        y += 40
    return b.d


# --- book covers (6 x 9 in, 1200 x 1800) --------------------------------------------------------------------

def book_bold(content=None, style=None) -> dict:
    s = _style(style, "dark", "Impact", "Segoe UI")
    b = Builder("bookcover", "book", _title(content, "Book cover"), s, bg="#0b1120")
    b.shape("ellipse", 600, -260, 900, 900, fill=b.primary, opacity=0.85)
    b.shape("ellipse", -300, 1180, 820, 820, fill=b.secondary, opacity=0.7)
    b.shape("rect", 110, 1040, 140, 14, fill=b.accent)
    b.text(upper(_title(content, "The Last Signal")), 100, 520, 1000, 500, role="title", size=170,
           color="#ffffff", valign="bottom", line=0.95)
    b.text(_c(content, "subtitle", "A novel"), 110, 1090, 980, 80, role="subtitle", size=48, color=b.accent,
           font=b.body)
    b.text(upper(_c(content, "author", "Deniz Aksoy")), 110, 1580, 980, 90, role="author", size=58,
           color="#ffffff", bold=True, font=b.body)
    return b.d


def book_classic(content=None, style=None) -> dict:
    s = _style(style, "royal", "Georgia", "Constantia")
    b = Builder("bookcover", "book", _title(content, "Book cover"), s, bg="#1e1b4b")
    gold = "#d4af37"
    b.shape("rect", 60, 60, 1080, 1680, fill=None, stroke=gold, stroke_w=5)
    b.shape("rect", 86, 86, 1028, 1628, fill=None, stroke=gold, stroke_w=2)
    b.icon("✦", 550, 260, 100, color=gold)
    b.text(_title(content, "The Garden of Letters"), 140, 420, 920, 560, role="title", size=130, color="#fdf8e7",
           align="center", valign="middle", line=1.05)
    b.line(450, 1030, 750, 1030, stroke=gold, stroke_w=3)
    b.text(_c(content, "subtitle", "Stories from an old house in Galata"), 160, 1070, 880, 150, role="subtitle",
           size=44, color=gold, align="center", italic=True, line=1.3)
    b.text(upper(_c(content, "author", "Selin Kaya")), 140, 1500, 920, 90, role="author", size=50, color="#fdf8e7",
           align="center", valign="middle")
    return b.d


def book_minimal(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Segoe UI", "Segoe UI")
    b = Builder("bookcover", "book", _title(content, "Book cover"), s, bg="#f5f1ea")
    image = _c(content, "image")
    if image:
        b.picture(image, 0, 640, 1200, 820, role="image")
    else:
        b.shape("rect", 0, 640, 1200, 820, role="image", fill=b.accent)
        b.shape("ellipse", 380, 760, 440, 440, fill="#f5f1ea", opacity=0.9)
    b.text(_title(content, "Quiet Hours"), 110, 140, 980, 300, role="title", size=150, color="#111111",
           bold=True, valign="bottom", line=1.0)
    b.text(_c(content, "subtitle", "Notes on slowing down"), 110, 460, 980, 80, role="subtitle", size=44,
           color="#555555")
    b.text(_c(content, "author", "Can Demir"), 110, 1560, 980, 90, role="author", size=52, color="#111111")
    return b.d


# --- event tickets (1800 x 700) ---------------------------------------------------------------------------

def _ticket_stub(b: Builder, content: dict, x, colour, ink) -> None:
    b.line(x, 60, x, 640, stroke=model.mix(ink, colour, 0.6), stroke_w=4, dash=True, role="deco")
    for y in (20, 680):
        b.shape("ellipse", x - 30, y - 30, 60, 60, fill=b.page["bg"], role="deco")
    rows = [("SEAT", _c(content, "seat", "B 14")), ("PRICE", _c(content, "price", "₺650")),
            ("NO.", _c(content, "code", "000427"))]
    y = 120
    for label, value in rows:
        b.text(label, x + 60, y, 300, 40, role="label", size=24, color=model.mix(ink, colour, 0.35), bold=True)
        b.text(value, x + 60, y + 40, 330, 70, role="detail", size=46, color=ink, bold=True, valign="middle")
        y += 150


def ticket_concert(content=None, style=None) -> dict:
    s = _style(style, "energetic", "Impact", "Segoe UI")
    b = Builder("ticket", "ticket", _title(content, "Ticket"), s, bg="#e5e7eb")
    b.shape("round", 20, 20, 1760, 660, role="ticket", fill="#111827", radius=36)
    b.shape("ellipse", 960, 70, 320, 320, fill=b.primary, opacity=0.85)
    b.shape("ellipse", 1110, 400, 190, 190, fill=b.secondary, opacity=0.8)
    b.text(upper(_title(content, "Gece Konseri")), 90, 110, 1100, 230, role="title", size=130,
           color="#ffffff", valign="bottom", line=0.95)
    b.text(_c(content, "note", "Live · All ages"), 90, 350, 900, 60, role="subtitle", size=40, color=b.accent,
           font=b.body, bold=True)
    details = "   ·   ".join(v for v in (_c(content, "date", "Sat 18 October"), _c(content, "time", "21:00"),
                                          _c(content, "place", "Zorlu PSM, İstanbul")) if v)
    b.text(details, 90, 470, 1150, 70, role="detail", size=38, color="#ffffff", font=b.body, valign="middle")
    _ticket_stub(b, content or {}, 1340, "#111827", "#ffffff")
    return b.d


def ticket_classic(content=None, style=None) -> dict:
    s = _style(style, "wedding", "Georgia", "Constantia")
    b = Builder("ticket", "ticket", _title(content, "Ticket"), s, bg="#ffffff")
    paper = "#fbf3e4"
    b.shape("round", 20, 20, 1760, 660, role="ticket", fill=paper, radius=30, stroke=b.primary, stroke_w=4)
    b.text("ADMIT ONE", -180, 290, 560, 110, role="label", size=56, color=b.primary, bold=True, rot=270,
           align="center", valign="middle")
    b.line(240, 70, 240, 630, stroke=b.primary, stroke_w=2, role="deco")
    b.text(upper(_c(content, "note", "The theatre presents")), 300, 100, 980, 50, role="subtitle", size=30,
           color=b.secondary, font=b.body)
    b.text(_title(content, "A Midsummer Night's Dream"), 300, 160, 1000, 250, role="title", size=96,
           color=b.dark, valign="middle", line=1.05)
    b.text(f"{_c(content, 'date', '24 November')}  ·  {_c(content, 'time', '20:00')}", 300, 440, 1000, 60,
           role="detail", size=40, color=b.dark, font=b.body, bold=True)
    b.text(_c(content, "place", "Kadıköy Halk Eğitim Sahnesi"), 300, 510, 1000, 60, role="detail", size=36,
           color=b.secondary, font=b.body)
    _ticket_stub(b, content or {}, 1340, paper, b.dark)
    return b.d


# --- infographics (1080 x 2400) -------------------------------------------------------------------------------

SAMPLE_INFO = [{"title": "Drink water first", "text": "A glass before coffee wakes you up faster.", "value": "1", "icon": "💧"},
               {"title": "Move for 10 minutes", "text": "A short walk beats a long scroll.", "value": "10", "icon": "🚶"},
               {"title": "Plan three things", "text": "Three wins a day add up to a great week.", "value": "3", "icon": "📝"},
               {"title": "Focus in blocks", "text": "45 minutes on, 10 off — phone in another room.", "value": "45", "icon": "⏱️"},
               {"title": "Stop on time", "text": "Rest is part of the work, not a reward for it.", "value": "8", "icon": "🌙"}]


def _items(content: dict | None) -> list[dict]:
    items = [i for i in (content or {}).get("items") or [] if isinstance(i, dict)]
    return items or SAMPLE_INFO


def info_steps(content=None, style=None) -> dict:
    s = _style(style, "calm", "Bahnschrift", "Segoe UI")
    b = Builder("infographic", "infographic", _title(content, "Infographic"), s, bg="#ffffff")
    b.shape("rect", 0, 0, 1080, 520, fill=b.primary)
    b.text(_title(content, "5 habits for a better morning"), 80, 90, 920, 280, role="title", size=96,
           color="#ffffff", bold=True, valign="bottom", line=1.05)
    b.text(_c(content, "subtitle", "Small steps, big difference"), 80, 390, 920, 70, role="subtitle", size=40,
           color=b.accent, font=b.body)
    items = _items(content)[:6]
    step = (2200 - 620) / max(1, len(items))
    b.line(170, 640, 170, 620 + step * (len(items) - 1) + 60, stroke=b.light, stroke_w=10, role="deco")
    for n, item in enumerate(items):
        y = 620 + n * step
        b.shape("ellipse", 100, y, 140, 140, role="step", fill=b.primary if n % 2 == 0 else b.secondary,
                text=str(n + 1), size=64, bold=True, color="#ffffff")
        b.text(str(item.get("title", "")), 290, y + 4, 700, 70, role="heading", size=46, color=b.dark, bold=True,
               valign="middle")
        b.text(str(item.get("text", "")), 290, y + 80, 700, step - 110, role="body", size=32, color="#4b5563",
               line=1.35)
        if item.get("icon"):
            b.icon(str(item["icon"]), 940, y + 10, 90, set="color")
    b.text(_c(content, "footer", "Share it with someone who needs it ✨"), 80, 2270, 920, 60, role="footer",
           size=30, color="#6b7280", align="center")
    return b.d


def info_stats(content=None, style=None) -> dict:
    s = _style(style, "tech", "Bahnschrift", "Segoe UI")
    b = Builder("infographic", "infographic", _title(content, "Infographic"), s, bg="#0f172a")
    b.text(upper(_c(content, "subtitle", "2026 in numbers")), 80, 110, 920, 60, role="subtitle", size=36,
           color=b.accent, bold=True, font=b.body)
    b.text(_title(content, "Our year at a glance"), 80, 180, 920, 260, role="title", size=100, color="#f8fafc",
           bold=True, valign="top", line=1.05)
    items = _items(content)[:6]
    if not (content or {}).get("items"):
        items = [{"title": "Happy customers", "value": "12,400", "icon": "😊"},
                 {"title": "Orders delivered", "value": "48k", "icon": "📦"},
                 {"title": "Cities", "value": "27", "icon": "📍"}, {"title": "Average rating", "value": "4.8", "icon": "⭐"},
                 {"title": "Trees planted", "value": "3,200", "icon": "🌳"}, {"title": "Team members", "value": "64", "icon": "🤝"}]
    rows = (len(items) + 1) // 2
    card_h = min(560.0, (2200 - 520) / max(1, rows) - 40)
    for n, item in enumerate(items):
        x, y = 80 + (n % 2) * 470, 520 + (n // 2) * (card_h + 40)
        b.shape("round", x, y, 450, card_h, role="card", fill="#1e293b", radius=36)
        if item.get("icon"):
            b.icon(str(item["icon"]), x + 40, y + 40, 90, set="color")
        b.text(str(item.get("value", "")), x + 40, y + card_h * 0.36, 370, card_h * 0.32, role="value", size=110,
               color=b.accent if n % 2 == 0 else b.primary, bold=True, valign="middle", line=1.0)
        b.text(str(item.get("title", "")), x + 40, y + card_h * 0.7, 370, card_h * 0.22, role="label", size=36,
               color="#cbd5e1", font=b.body)
    b.text(_c(content, "footer", "Thank you for being part of it."), 80, 2280, 920, 60, role="footer", size=32,
           color="#94a3b8", align="center")
    return b.d


# --- Instagram carousels (1080 x 1080, several pages) -------------------------------------------------------

SAMPLE_SLIDES = [{"title": "Start before you're ready", "text": "Waiting for the perfect moment is the slowest plan."},
                 {"title": "Batch the boring stuff", "text": "Emails, errands and admin — one block, once a day."},
                 {"title": "Say no more often", "text": "Every yes costs time you could spend on what matters."},
                 {"title": "Write it down", "text": "Your brain is for ideas, not for holding them."}]


def _next_page(b: Builder, bg: str) -> None:
    page = model.new_page(bg)
    b.d["pages"].append(page)
    b.page = page


def _slides(content: dict | None) -> list[dict]:
    items = [i for i in (content or {}).get("slides") or [] if isinstance(i, dict)]
    return items or SAMPLE_SLIDES


def carousel_tips(content=None, style=None) -> dict:
    s = _style(style, "candy", "Bahnschrift", "Segoe UI")
    b = Builder("carousel", "instagram", _title(content, "Carousel"), s, bg=s["palette"][0])
    slides = _slides(content)[:8]
    total = len(slides) + 2
    handle = _c(content, "handle", "@yourname")
    b.shape("ellipse", 640, -200, 640, 640, fill=b.secondary, opacity=0.6)
    b.text(_title(content, "4 habits that changed my week"), 90, 260, 900, 470, role="title", size=110,
           color="#ffffff", bold=True, valign="middle", line=1.0)
    b.text("Swipe  →", 90, 900, 600, 80, role="cta", size=48, color="#ffffff", bold=True, font=b.body)
    b.text(handle, 590, 900, 400, 80, role="handle", size=36, color="#ffffff", align="right", valign="middle")
    for n, slide in enumerate(slides, 2):
        _next_page(b, b.light)
        b.shape("rect", 0, 0, 1080, 24, fill=b.primary)
        b.shape("ellipse", 90, 120, 150, 150, role="number", fill=b.primary, text=str(n - 1), size=72, bold=True,
                color="#ffffff")
        b.text(str(slide.get("title", "")), 90, 330, 900, 300, role="title", size=84, color=b.dark, bold=True,
               valign="bottom", line=1.05)
        b.text(str(slide.get("text", "")), 90, 660, 900, 260, role="body", size=44, color="#4b5563", line=1.35)
        b.text(f"{n}/{total}", 860, 960, 130, 60, role="footer", size=30, color="#9ca3af", align="right")
    _next_page(b, b.primary)
    b.text(_c(content, "cta", "Save this for later"), 90, 300, 900, 260, role="title", size=96, color="#ffffff",
           bold=True, align="center", valign="middle")
    b.shape("round", 290, 640, 500, 110, role="cta", fill="#ffffff", text=f"Follow {handle}", color=b.primary,
            size=44, bold=True, radius=55, font=b.body)
    b.text(f"{total}/{total}", 860, 960, 130, 60, role="footer", size=30, color="#ffffff", align="right")
    return b.d


def carousel_story(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Georgia", "Segoe UI")
    b = Builder("carousel", "instagram", _title(content, "Carousel"), s, bg="#111111")
    slides = _slides(content)[:8]
    handle = _c(content, "handle", "@yourname")
    b.text("“", 80, 60, 200, 260, role="deco", size=300, color=b.accent)
    b.text(_title(content, "What a year of writing every day taught me"), 90, 300, 900, 480, role="title",
           size=96, color="#ffffff", valign="middle", line=1.1)
    b.text(handle, 90, 930, 900, 60, role="handle", size=34, color="#9ca3af")
    for n, slide in enumerate(slides, 1):
        dark = n % 2 == 0
        _next_page(b, "#111111" if dark else "#ffffff")
        ink = "#ffffff" if dark else "#111111"
        b.text(f"{n:02d}", 90, 90, 300, 110, role="number", size=90, color=b.accent, bold=True)
        b.text(str(slide.get("title", "")), 90, 300, 900, 280, role="title", size=78, color=ink, valign="bottom",
               line=1.1)
        b.line(90, 620, 290, 620, stroke=b.accent, stroke_w=6)
        b.text(str(slide.get("text", "")), 90, 660, 900, 300, role="body", size=42, color=model.mix(ink, "#888888", 0.3),
               line=1.4, font=b.body)
    _next_page(b, b.accent)
    b.text(_c(content, "cta", "Follow for more"), 90, 360, 900, 220, role="title", size=96, color="#ffffff",
           align="center", valign="middle")
    b.text(handle, 90, 600, 900, 80, role="handle", size=44, color="#ffffff", align="center", font=b.body)
    return b.d


# --- calendar pages (A4) -----------------------------------------------------------------------------------------

MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"],
          "tr": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
                 "Aralık"]}
WEEKDAYS = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "tr": ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]}


def _calendar_args(content: dict | None) -> tuple[int, int, str]:
    today = dt.date.today()
    nxt = today.replace(day=1) + dt.timedelta(days=32)
    try:
        year = int((content or {}).get("year") or nxt.year)
        month = int((content or {}).get("month") or nxt.month)
    except (TypeError, ValueError):
        year, month = nxt.year, nxt.month
    month = max(1, min(12, month))
    lang = str((content or {}).get("lang") or "")
    if not lang:
        try:
            from .. import i18n

            lang = "tr" if i18n.current() == "tr" else "en"
        except Exception:
            lang = "en"
    return year, month, "tr" if lang.startswith("tr") else "en"


def month_rows(year: int, month: int, lang: str = "en", events: dict | None = None) -> list[list[str]]:
    """The month as a table: weekday names, then a row per week, with a dot on days that have a note."""
    marked = {int(k) for k in (events or {}) if str(k).strip().isdigit()}
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    return [WEEKDAYS[lang]] + [[(f"{d} •" if d in marked else str(d)) if d else "" for d in week] for week in weeks]


def _events(content: dict | None) -> dict:
    events = (content or {}).get("events")
    return events if isinstance(events, dict) else {}


def calendar_photo(content=None, style=None) -> dict:
    s = _style(style, "nature", "Georgia", "Segoe UI")
    year, month, lang = _calendar_args(content)
    b = Builder("calendar", "poster", f"{MONTHS[lang][month - 1]} {year}", s, bg="#ffffff")
    image = _c(content, "image")
    if image:
        b.picture(image, 0, 0, 1240, 760, role="image")
    else:
        b.shape("rect", 0, 0, 1240, 760, role="image", fill=b.primary)
        b.shape("ellipse", 760, 120, 380, 380, fill=b.accent, opacity=0.9)
        b.shape("triangle", -100, 330, 900, 430, fill=b.secondary)
        b.shape("triangle", 420, 380, 1000, 380, fill=model.mix(b.secondary, "#000000", 0.25))
    b.text(MONTHS[lang][month - 1], 80, 800, 760, 150, role="title", size=120, color=b.dark, valign="middle")
    b.text(str(year), 860, 800, 300, 150, role="subtitle", size=80, color=b.primary, align="right", valign="middle")
    rows = month_rows(year, month, lang, _events(content))
    model.add(b.d, b.page, model.table(rows, 80, 990, 1080, 92 * len(rows), header=True, size=34, fill=b.primary,
                                       header_color="#ffffff", stripe="#f7f7f2", color=b.dark, border="#e5e7eb",
                                       align="center", font=b.body, role="calendar"))
    _notes(b, content, 990 + 92 * len(rows) + 30)
    return b.d


def calendar_minimal(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Segoe UI", "Segoe UI")
    year, month, lang = _calendar_args(content)
    b = Builder("calendar", "poster", f"{MONTHS[lang][month - 1]} {year}", s, bg="#ffffff")
    b.text(f"{month:02d}", 80, 80, 500, 300, role="deco", size=280, color=b.accent, bold=True, valign="middle",
           line=1.0)
    b.text(upper(MONTHS[lang][month - 1]), 80, 400, 1080, 120, role="title", size=100, color=b.dark, bold=True,
           valign="middle")
    b.text(str(year), 80, 520, 1080, 70, role="subtitle", size=48, color="#6b7280", valign="middle")
    rows = month_rows(year, month, lang, _events(content))
    model.add(b.d, b.page, model.table(rows, 80, 640, 1080, 110 * len(rows), header=True, size=36, fill="#ffffff",
                                       header_color=b.accent, stripe="#ffffff", color=b.dark, border="#e5e7eb",
                                       align="center", font=b.body, role="calendar"))
    _notes(b, content, 640 + 110 * len(rows) + 30)
    return b.d


def _notes(b: Builder, content: dict | None, top: float) -> None:
    events = _events(content)
    lines = [f"{k} — {v}" for k, v in sorted(events.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 99)]
    title = "Notlar" if _calendar_args(content)[2] == "tr" else "Notes"
    name = _title(content, "")
    b.text(f"{name} · {title}" if name else title, 80, top, 1080, 50, role="section", size=30, color=b.dark,
           bold=True, valign="middle")
    if lines:
        b.text("\n".join(lines[:8]), 80, top + 60, 1080, max(80.0, 1700 - top - 60), role="body", size=28,
               color="#374151", line=1.4)
    else:
        y = top + 100
        while y < 1690:
            b.line(80, y, 1160, y, stroke="#e5e7eb", stroke_w=2)
            y += 70


KINDS.update({
    "cv": {"label": "CV / résumé", "fields": ["name", "title", "contact", "summary", "experience", "education",
                                              "skills", "languages"],
           "variants": {"modern": cv_modern, "classic": cv_classic, "bold": cv_bold}},
    "bookcover": {"label": "Book cover", "fields": ["title", "subtitle", "author"],
                  "variants": {"bold": book_bold, "classic": book_classic, "minimal": book_minimal}},
    "ticket": {"label": "Event ticket", "fields": ["event", "date", "time", "place", "seat", "price", "code", "note"],
               "variants": {"concert": ticket_concert, "classic": ticket_classic}},
    "infographic": {"label": "Infographic", "fields": ["title", "subtitle", "items", "footer"],
                    "variants": {"steps": info_steps, "stats": info_stats}},
    "carousel": {"label": "Instagram carousel", "fields": ["title", "slides", "handle", "cta"],
                 "variants": {"tips": carousel_tips, "story": carousel_story}},
    "calendar": {"label": "Calendar page", "fields": ["year", "month", "title", "events"],
                 "variants": {"photo": calendar_photo, "minimal": calendar_minimal}},
})
