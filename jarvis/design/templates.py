"""Templates: slide themes, posters, cards, logos, menus, invitations,
stickers, sale posters and thumbnails — plus palettes, font pairs and icons.

A template is a function of (content, style) -> design. Content is what the
user or the model supplies (a headline, a date, a menu's dishes); style is a
five-colour palette [primary, secondary, accent, light, dark] and a heading
and body font. Each design remembers the palette and fonts it was built with,
which is what lets "palette from a photo" or the brand kit recolour it later
by swapping colours rather than guessing which shape was which.
"""

from __future__ import annotations

import random

from . import fonts as font_mod
from . import model

# --- palettes, font pairs, icons ------------------------------------------------------------

PALETTES: dict[str, list[str]] = {
    "ocean": ["#0b4f8a", "#1e88e5", "#00bcd4", "#e8f4fd", "#0d1b2a"],
    "sunset": ["#e8590c", "#d6336c", "#fab005", "#fff4e6", "#2b1d16"],
    "forest": ["#2b8a3e", "#5c940d", "#e0a800", "#f1f8e9", "#1b2e1f"],
    "royal": ["#5f3dc4", "#9c36b5", "#f59f00", "#f8f0fc", "#1c1433"],
    "candy": ["#e64980", "#7950f2", "#22b8cf", "#fff0f6", "#2d1b2e"],
    "corporate": ["#1c3d5a", "#3e7cb1", "#f4a259", "#f5f7fa", "#16212c"],
    "luxury": ["#b08d57", "#1f2937", "#d4af37", "#faf7f0", "#111111"],
    "nature": ["#386641", "#6a994e", "#bc4749", "#f2e8cf", "#1f2a1f"],
    "retro": ["#e76f51", "#2a9d8f", "#e9c46a", "#fdf6e3", "#264653"],
    "minimal": ["#111111", "#555555", "#e03131", "#ffffff", "#111111"],
    "pastel": ["#9775fa", "#f783ac", "#63e6be", "#fdf7ff", "#3b3247"],
    "tech": ["#2563eb", "#7c3aed", "#06b6d4", "#f8fafc", "#0f172a"],
    "warm": ["#c2410c", "#b45309", "#eab308", "#fffbeb", "#292524"],
    "cool": ["#0369a1", "#4338ca", "#14b8a6", "#f0f9ff", "#0c1a2b"],
    "dark": ["#38bdf8", "#a78bfa", "#facc15", "#0b1120", "#f8fafc"],
    "romantic": ["#c2255c", "#e599f7", "#ffd8a8", "#fff5f7", "#3a1d2a"],
    "autumn": ["#9c4221", "#c05621", "#d69e2e", "#fffaf0", "#2d2016"],
    "spring": ["#2f9e44", "#f06595", "#fcc419", "#f8fff4", "#203020"],
    "summer": ["#f76707", "#1098ad", "#fcc419", "#fffdf2", "#1d2b2f"],
    "winter": ["#1864ab", "#5c7cfa", "#99e9f2", "#f3f8ff", "#14213d"],
    "kids": ["#f03e3e", "#1c7ed6", "#fcc419", "#fffdf5", "#212529"],
    "sport": ["#d9480f", "#111827", "#facc15", "#f8f9fa", "#111827"],
    "food": ["#c92a2a", "#e67700", "#2b8a3e", "#fff9f0", "#2b1a12"],
    "wedding": ["#a07a4a", "#7d8f69", "#e8c9a0", "#fffdf8", "#3a3026"],
    "birthday": ["#f06595", "#5c7cfa", "#ffd43b", "#fff9fb", "#2c2340"],
    "calm": ["#3d8a85", "#7aa6c2", "#e9c46a", "#f4f9f8", "#1f3b3a"],
    "energetic": ["#ff3d00", "#2962ff", "#ffd600", "#fffaf5", "#1a1a1a"],
}
MOODS = {
    "calm": "calm", "relax": "calm", "peace": "calm", "sakin": "calm", "huzur": "calm",
    "energy": "energetic", "energetic": "energetic", "exciting": "energetic", "enerji": "energetic",
    "luxury": "luxury", "premium": "luxury", "gold": "luxury", "lüks": "luxury", "elegant": "luxury",
    "nature": "nature", "eco": "nature", "green": "forest", "doğa": "nature", "forest": "forest",
    "fun": "candy", "playful": "candy", "eğlence": "candy", "kids": "kids", "child": "kids", "çocuk": "kids",
    "love": "romantic", "romantic": "romantic", "aşk": "romantic", "valentine": "romantic",
    "business": "corporate", "corporate": "corporate", "professional": "corporate", "iş": "corporate",
    "tech": "tech", "ai": "tech", "startup": "tech", "teknoloji": "tech", "retro": "retro", "vintage": "retro",
    "minimal": "minimal", "simple": "minimal", "sade": "minimal", "pastel": "pastel", "soft": "pastel",
    "warm": "warm", "sıcak": "warm", "cool": "cool", "cold": "winter", "soğuk": "winter", "dark": "dark",
    "night": "dark", "gece": "dark", "autumn": "autumn", "fall": "autumn", "sonbahar": "autumn",
    "spring": "spring", "ilkbahar": "spring", "summer": "summer", "yaz": "summer", "beach": "summer",
    "winter": "winter", "kış": "winter", "christmas": "winter", "sport": "sport", "gym": "sport", "spor": "sport",
    "food": "food", "restaurant": "food", "yemek": "food", "cafe": "warm", "coffee": "autumn", "kahve": "autumn",
    "wedding": "wedding", "düğün": "wedding", "birthday": "birthday", "doğum günü": "birthday", "party": "birthday",
    "ocean": "ocean", "sea": "ocean", "deniz": "ocean", "sunset": "sunset", "royal": "royal",
}
FONT_PAIRS: list[tuple[str, str, str]] = [
    ("Georgia", "Segoe UI", "classic editorial"),
    ("Bahnschrift", "Segoe UI", "modern tech"),
    ("Impact", "Arial", "loud and bold"),
    ("Cambria", "Calibri", "professional report"),
    ("Segoe Script", "Georgia", "wedding elegant"),
    ("Gabriola", "Constantia", "romantic invitation"),
    ("Rockwell", "Verdana", "sturdy retro"),
    ("Trebuchet MS", "Georgia", "friendly blog"),
    ("Segoe Print", "Segoe UI", "handwritten fun"),
    ("Ink Free", "Corbel", "casual notes"),
    ("Palatino Linotype", "Segoe UI", "bookish literary"),
    ("Franklin Gothic Medium", "Georgia", "newspaper headline"),
    ("Comic Sans MS", "Segoe UI", "kids classroom"),
    ("Century Gothic", "Candara", "clean geometric"),
    ("Consolas", "Segoe UI", "developer code"),
    ("Stencil", "Arial", "industrial military"),
    ("Showcard Gothic", "Verdana", "circus party poster"),
    ("Elephant", "Calibri", "heavy display"),
    ("Constantia", "Candara", "soft serif calm"),
    ("Corbel", "Corbel", "soft sans minimal"),
    ("Book Antiqua", "Calibri", "luxury classic"),
    ("Segoe UI", "Segoe UI", "neutral clean"),
]
ICONS: dict[str, str] = {
    "Faces": "😀 😂 😍 🤩 😎 🤔 😴 😭 😡 🥳 🤯 😇 🙂 😉 😱 🤓",
    "People": "👍 👎 👏 🙌 🤝 ✌️ 👋 💪 🙏 👀 🧠 ❤️ 👨\u200d🎓 👩\u200d💻 👨\u200d🍳 🧑\u200d🏫",
    "Objects": "💡 📱 💻 ⌚ 📷 🎁 📚 ✏️ 📌 📎 🔑 🔒 🛒 🎧 🎮 🧪",
    "Business": "📈 📉 💰 💳 🏆 🎯 📊 🗂️ 📅 ⏰ ✅ ❌ 📣 🤖 🚀 ⚙️",
    "Nature": "🌸 🌻 🌿 🍀 🌳 🌊 🔥 ⭐ 🌙 ☀️ ⛅ ❄️ 🌈 🍁 🌵 🌺",
    "Food": "🍕 🍔 ☕ 🍰 🍎 🍓 🍩 🍷 🥗 🍜 🍪 🧁 🥐 🍦 🫖 🍉",
    "Celebrate": "🎉 🎈 🎂 🎊 💍 💐 🎄 🎃 🕌 ✨ 🎆 🥂 🎀 🕯️ 🪅 🎵",
    "Travel": "✈️ 🚗 🚀 🏠 🏫 🏥 🗺️ 📍 ⛰️ 🏖️ 🚲 ⚽ 🏀 🎾 🚆 ⛵",
    "Symbols": "★ ☆ ♥ ✓ ✗ ✦ ✧ ◆ ● ■ ▲ ➜ ⚑ ☎ ✉ ♪ ♫ ☀ ☂ ☺ ⚡ ✿ ❖ ∞",
}
SHAPE_LABELS = {"rect": "▭ Rectangle", "round": "▢ Rounded", "ellipse": "◯ Circle", "triangle": "△ Triangle",
                "diamond": "◇ Diamond", "pentagon": "⬠ Pentagon", "hexagon": "⬡ Hexagon", "star": "☆ Star",
                "burst": "✹ Burst", "arrow": "➜ Arrow", "chevron": "❯ Chevron", "plus": "✚ Plus",
                "heart": "♡ Heart", "bubble": "💬 Speech", "ribbon": "🎗 Ribbon"}



TURKISH = set("çğışöüÇĞİŞÖÜ")


def upper(text: str) -> str:
    """Capitals that respect Turkish: 'gecesi' -> 'GECESİ', not 'GECESI'."""
    try:
        from .. import i18n

        turkish = i18n.current() == "tr"
    except Exception:
        turkish = False
    if turkish or TURKISH & set(text):
        return text.replace("i", "İ").replace("ı", "I").upper()
    return text.upper()

def icon_list(category: str) -> list[str]:
    return ICONS.get(category, "").split()


def mono(category: str) -> bool:
    return category == "Symbols"


def palette_for(mood: str) -> list[str] | None:
    text = (mood or "").lower()
    for word, name in MOODS.items():
        if word in text:
            return list(PALETTES[name])
    return list(PALETTES[text]) if text in PALETTES else None


def font_pairs(mood: str = "", installed_only: bool = True) -> list[tuple[str, str, str]]:
    pairs = [p for p in FONT_PAIRS if not installed_only or (font_mod.has(p[0]) and font_mod.has(p[1]))]
    words = [w for w in (mood or "").lower().split() if len(w) > 2]
    if words:
        ranked = sorted(pairs, key=lambda p: -sum(w in p[2] for w in words))
        if sum(w in ranked[0][2] for w in words):
            return ranked
    return pairs


def _font(name: str, fallback: str = "Segoe UI") -> str:
    """A font the template wants, if this PC has it."""
    try:
        return name if font_mod.has(name) else fallback
    except Exception:
        return fallback


# --- building blocks -------------------------------------------------------------------------

class Builder:
    """A one-page design with the template's palette and fonts to hand."""

    def __init__(self, kind: str, fmt: str, title: str, style: dict, bg: str | None = None):
        self.style = style
        self.pal = list(style.get("palette") or PALETTES["ocean"])
        self.heading = _font(style.get("heading", "Segoe UI"))
        self.body = _font(style.get("body", "Segoe UI"))
        self.d = model.new_design(kind, fmt, title)
        self.d["palette"] = self.pal[:5]
        self.d["fonts"] = {"heading": self.heading, "body": self.body}
        self.page = self.d["pages"][0]
        self.page["bg"] = bg or self.pal[3]
        self.W, self.H = self.d["w"], self.d["h"]

    primary = property(lambda self: self.pal[0])
    secondary = property(lambda self: self.pal[1])
    accent = property(lambda self: self.pal[2])
    light = property(lambda self: self.pal[3])
    dark = property(lambda self: self.pal[4])

    def text(self, value, x, y, w, h, role: str = "body", **props) -> dict:
        heading = role in {"title", "headline", "name", "subtitle"}
        props.setdefault("font", self.heading if heading else self.body)
        props.setdefault("color", self.dark)
        props.setdefault("autofit", True)
        return model.add(self.d, self.page, model.text(str(value or ""), x, y, w, h, role=role, **props))

    def shape(self, kind, x, y, w, h, role: str = "deco", **props) -> dict:
        props.setdefault("font", self.heading)
        return model.add(self.d, self.page, model.shape(kind, x, y, w, h, role=role, **props))

    def line(self, x1, y1, x2, y2, role: str = "deco", **props) -> dict:
        return model.add(self.d, self.page, model.line(x1, y1, x2, y2, role=role, **props))

    def icon(self, glyph, x, y, size, role: str = "icon", **props) -> dict:
        if glyph and all(ord(c) < 0x2b00 for c in glyph):
            props.setdefault("set", "mono")
            props.setdefault("color", self.accent)
        return model.add(self.d, self.page, model.icon(glyph or "⭐", x, y, size, role=role, **props))

    def picture(self, src, x, y, w, h, role: str = "image", **props) -> dict:
        return model.add(self.d, self.page, model.picture(src, x, y, w, h, role=role, **props))


def _c(content: dict | None, key: str, default: str = "") -> str:
    value = (content or {}).get(key)
    return default if value in (None, "") else str(value)


def _style(style: dict | None, palette: str, heading: str, body: str) -> dict:
    style = dict(style or {})
    style.setdefault("palette", PALETTES[palette])
    style.setdefault("heading", heading)
    style.setdefault("body", body)
    return style


def _details(b: Builder, content: dict, x, y, w, size, color, align="center", gap=1.5) -> float:
    """📅 date · ⏰ time · 📍 place, one line each. Returns the y after them."""
    rows = [("📅", _c(content, "date")), ("⏰", _c(content, "time")), ("📍", _c(content, "place"))]
    for glyph, value in rows:
        if not value:
            continue
        b.text(f"{glyph}  {value}", x, y, w, size * gap, role="detail", size=size, color=color, align=align)
        y += size * gap
    return y


# --- YouTube thumbnails (1280 x 720) -----------------------------------------------------------

def thumbnail_split(content=None, style=None) -> dict:
    s = _style(style, "energetic", "Impact", "Segoe UI")
    b = Builder("thumbnail", "thumbnail", _c(content, "headline", "Thumbnail"), s, bg=s["palette"][4])
    b.shape("rect", 0, 0, 640, 720, fill=b.dark)
    b.shape("rect", 60, 520, 220, 18, fill=b.accent)
    b.text(upper(_c(content, "headline", "I TRIED THIS FOR 30 DAYS")), 60, 90, 600, 420, role="headline", size=120,
           color="#ffffff", stroke="#000000", stroke_w=6, valign="bottom", line=1.0)
    sub = _c(content, "sub", "The result surprised me")
    b.shape("round", 60, 580, 560, 90, role="badge", fill=b.accent, text=sub, color=b.dark, size=40, bold=True,
            radius=45, font=b.body)
    image = _c(content, "image")
    if image:
        b.picture(image, 680, 60, 560, 600, radius=36, rot=3, stroke="#ffffff", stroke_w=10, shadow=True)
    else:
        b.shape("ellipse", 760, 110, 460, 460, fill=b.primary)
        b.icon(_c(content, "emoji", "😱"), 820, 170, 340, set="color")
    return b.d


def thumbnail_center(content=None, style=None) -> dict:
    s = _style(style, "sunset", "Impact", "Segoe UI")
    b = Builder("thumbnail", "thumbnail", _c(content, "headline", "Thumbnail"), s, bg=s["palette"][0])
    b.shape("burst", 880, -120, 520, 520, fill=b.accent, opacity=0.9)
    b.shape("ellipse", -160, 420, 460, 460, fill=b.secondary, opacity=0.8)
    b.text(upper(_c(content, "headline", "DON'T BUY THIS")), 80, 150, 1120, 330, role="headline", size=150,
           color="#ffffff", stroke="#000000", stroke_w=8, align="center", valign="middle", shadow=True, line=1.0)
    b.text(_c(content, "sub", "until you watch this"), 240, 500, 800, 90, role="subtitle", size=54, color=b.dark,
           align="center", valign="middle", fill="#ffffff", radius=45, bold=True, font=b.body)
    b.icon(_c(content, "emoji", "🔥"), 70, 40, 170, set="color", rot=-12)
    return b.d


def thumbnail_banner(content=None, style=None) -> dict:
    s = _style(style, "tech", "Impact", "Segoe UI")
    b = Builder("thumbnail", "thumbnail", _c(content, "headline", "Thumbnail"), s, bg=s["palette"][4])
    image = _c(content, "image")
    if image:
        b.picture(image, 0, 0, 1280, 720, role="background")
        b.shape("rect", 0, 0, 1280, 720, fill="#000000", opacity=0.35)
    else:
        for i in range(6):
            b.shape("rect", -200 + i * 260, -100, 120, 1000, fill=b.primary if i % 2 else b.secondary, rot=20,
                    opacity=0.55)
    b.shape("rect", -40, 430, 1360, 210, fill=b.accent, rot=-3)
    b.text(upper(_c(content, "headline", "THE ULTIMATE GUIDE")), 60, 445, 1160, 180, role="headline", size=120,
           color=b.dark, align="center", valign="middle", rot=-3, line=1.0)
    b.text(_c(content, "sub", "Everything in 10 minutes"), 60, 80, 900, 90, role="subtitle", size=56,
           color="#ffffff", stroke="#000000", stroke_w=4, bold=True, font=b.body)
    return b.d


# --- posters and flyers (A4, 1240 x 1754) ------------------------------------------------------

def poster_modern(content=None, style=None) -> dict:
    s = _style(style, "ocean", "Bahnschrift", "Segoe UI")
    b = Builder("poster", "poster", _c(content, "headline", "Poster"), s)
    b.shape("rect", 0, 0, 1240, 1000, fill=b.primary)
    b.shape("ellipse", 820, -180, 600, 600, fill=b.secondary, opacity=0.6)
    b.shape("ellipse", -140, 640, 340, 340, fill=b.accent, opacity=0.85)
    b.text(upper(_c(content, "sub", "Community event")), 110, 170, 900, 70, role="subtitle", size=44,
           color=b.accent, bold=True, font=b.body)
    b.text(_c(content, "headline", "Summer Music Night"), 110, 260, 1020, 560, role="headline", size=150,
           color="#ffffff", bold=True, valign="middle", line=1.0)
    b.text(_c(content, "body", "Live bands, street food and good people under the stars. Bring your friends."),
           110, 1060, 1020, 220, role="body", size=46, color=b.dark, line=1.3)
    y = _details(b, content or {}, 110, 1300, 1020, 44, b.dark, align="left")
    b.shape("round", 110, max(y + 30, 1540), 520, 120, role="cta", fill=b.primary,
            text=_c(content, "cta", "Free entry"), size=48, bold=True, color="#ffffff", radius=60, font=b.body)
    return b.d


def poster_bold(content=None, style=None) -> dict:
    s = _style(style, "dark", "Impact", "Segoe UI")
    b = Builder("poster", "poster", _c(content, "headline", "Poster"), s, bg="#0b1120")
    b.shape("rect", -300, 980, 1900, 160, fill=b.accent, rot=-12)
    b.shape("rect", -300, 1170, 1900, 50, fill=b.secondary, rot=-12)
    b.text(upper(_c(content, "headline", "HACK THE WEEKEND")), 90, 110, 1060, 760, role="headline", size=230,
           color=b.primary, line=0.95, valign="top")
    b.text(_c(content, "sub", "48 hours. One idea. Your team."), 90, 880, 1060, 90, role="subtitle", size=54,
           color="#f8fafc", font=b.body, bold=True)
    b.text(_c(content, "body", "Prizes, mentors, pizza at 3 a.m."), 90, 1330, 1060, 100, role="body", size=44,
           color="#cbd5e1")
    _details(b, content or {}, 90, 1440, 1060, 44, "#f8fafc", align="left")
    b.text(_c(content, "cta", "Register now"), 90, 1660, 1060, 70, role="cta", size=52, color=b.accent, bold=True)
    return b.d


def poster_elegant(content=None, style=None) -> dict:
    s = _style(style, "luxury", "Georgia", "Constantia")
    b = Builder("poster", "poster", _c(content, "headline", "Poster"), s, bg="#faf7f0")
    b.shape("rect", 60, 60, 1120, 1634, fill=None, stroke=b.primary, stroke_w=4)
    b.shape("rect", 84, 84, 1072, 1586, fill=None, stroke=b.primary, stroke_w=1.5)
    b.icon("✦", 570, 200, 100, color=b.primary)
    b.text(upper(_c(content, "sub", "You are invited to")), 160, 340, 920, 70, role="subtitle", size=38,
           color=b.secondary, align="center", font=b.body)
    b.text(_c(content, "headline", "An Evening of Jazz"), 140, 430, 960, 380, role="headline", size=130,
           color=b.dark, align="center", valign="middle", line=1.05)
    b.line(470, 860, 770, 860, stroke=b.primary, stroke_w=3)
    b.text(_c(content, "body", "Wine, candlelight and the city's finest quartet."), 180, 920, 880, 200,
           role="body", size=44, color=b.secondary, align="center", italic=True, line=1.35)
    _details(b, content or {}, 180, 1180, 880, 42, b.dark)
    b.text(_c(content, "cta", "RSVP by Friday"), 180, 1500, 880, 70, role="cta", size=40, color=b.primary,
           align="center", bold=True)
    return b.d


# --- logos (1000 x 1000) -------------------------------------------------------------------------

def _initials(name: str) -> str:
    words = [w for w in name.replace("&", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or (name[:1].upper() or "J")


def logo_emblem(content=None, style=None) -> dict:
    s = _style(style, "corporate", "Bahnschrift", "Segoe UI")
    b = Builder("logo", "logo", _c(content, "name", "Logo"), s, bg="#ffffff")
    b.shape("ellipse", 150, 150, 700, 700, fill=b.primary)
    b.shape("ellipse", 190, 190, 620, 620, fill=None, stroke="#ffffff", stroke_w=6)
    b.icon(_c(content, "icon", "★"), 420, 250, 160, color=b.accent, set="mono")
    b.text(upper(_c(content, "name", "Northwind")), 220, 430, 560, 170, role="name", size=110, color="#ffffff",
           bold=True, align="center", valign="middle", line=1.0)
    b.text(upper(_c(content, "tagline", "Coffee Roasters")), 240, 610, 520, 80, role="tagline", size=44,
           color=b.accent, align="center", valign="middle", font=b.body)
    return b.d


def logo_wordmark(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Segoe UI", "Segoe UI")
    b = Builder("logo", "logo", _c(content, "name", "Logo"), s, bg="#ffffff")
    b.text(_c(content, "name", "lumen"), 80, 330, 840, 260, role="name", size=210, color=b.dark, bold=True,
           align="center", valign="middle", line=1.0)
    b.shape("ellipse", 760, 520, 60, 60, fill=b.accent)
    b.text(upper(_c(content, "tagline", "light for your home")), 120, 620, 760, 80, role="tagline", size=40,
           color=b.secondary, align="center", valign="middle", font=b.body)
    return b.d


def logo_monogram(content=None, style=None) -> dict:
    s = _style(style, "royal", "Georgia", "Segoe UI")
    name = _c(content, "name", "Atlas Studio")
    b = Builder("logo", "logo", name, s, bg="#ffffff")
    b.shape("round", 280, 160, 440, 440, fill=b.primary, radius=110, rot=0)
    b.shape("round", 310, 190, 380, 380, fill=None, stroke=b.accent, stroke_w=5, radius=90)
    b.text(_c(content, "initials", _initials(name)), 300, 230, 400, 300, role="monogram", size=210, color="#ffffff",
           bold=True, align="center", valign="middle", line=1.0)
    b.text(name, 100, 660, 800, 120, role="name", size=88, color=b.dark, align="center", valign="middle", bold=True)
    b.text(_c(content, "tagline", "Architecture & Interiors"), 150, 790, 700, 70, role="tagline", size=38,
           color=b.secondary, align="center", font=b.body)
    return b.d


# --- greeting cards (1500 x 1050) ------------------------------------------------------------------

def card_confetti(content=None, style=None) -> dict:
    s = _style(style, "birthday", "Segoe UI", "Segoe UI")
    b = Builder("card", "card", _c(content, "headline", "Card"), s, bg="#fffdf7")
    rnd = random.Random(7)
    for _ in range(46):
        kind = rnd.choice(["ellipse", "triangle", "rect", "star"])
        size = rnd.randint(18, 46)
        x, y = rnd.randint(0, 1480), rnd.randint(0, 1030)
        if 260 < x < 1240 and 260 < y < 820:
            continue
        b.shape(kind, x, y, size, size, fill=rnd.choice(b.pal[:3]), rot=rnd.randint(0, 90))
    b.text(_c(content, "headline", "Happy Birthday!"), 200, 260, 1100, 260, role="headline", size=150,
           color=b.primary, bold=True, align="center", valign="middle", line=1.0)
    b.text(_c(content, "message", "Wishing you a year full of laughter, cake and adventures."), 280, 540,
           940, 180, role="body", size=50, color=b.dark, align="center", line=1.3)
    b.text(f"— {_c(content, 'from', 'with love')}", 280, 740, 940, 80, role="from", size=44, color=b.secondary,
           align="center", italic=True)
    return b.d


def card_elegant(content=None, style=None) -> dict:
    s = _style(style, "luxury", "Georgia", "Constantia")
    b = Builder("card", "card", _c(content, "headline", "Card"), s, bg="#14213d")
    gold = "#d4af37"
    b.shape("rect", 50, 50, 1400, 950, fill=None, stroke=gold, stroke_w=4)
    b.shape("rect", 72, 72, 1356, 906, fill=None, stroke=gold, stroke_w=1.5)
    b.icon("✦", 700, 150, 100, color=gold)
    b.text(_c(content, "headline", "Congratulations"), 160, 270, 1180, 230, role="headline", size=130, color=gold,
           align="center", valign="middle", italic=True)
    b.line(600, 540, 900, 540, stroke=gold, stroke_w=2)
    b.text(_c(content, "message", "On your well-deserved success. The best is yet to come."), 260, 580, 980, 200,
           role="body", size=48, color="#f5efe0", align="center", line=1.35)
    b.text(_c(content, "from", "Your friends"), 260, 820, 980, 80, role="from", size=42, color=gold, align="center")
    return b.d


def card_cute(content=None, style=None) -> dict:
    s = _style(style, "pastel", "Segoe Print", "Segoe UI")
    b = Builder("card", "card", _c(content, "headline", "Card"), s, bg="#fde2ef")
    b.shape("ellipse", -120, -140, 520, 520, fill="#ffffff", opacity=0.6)
    b.shape("ellipse", 1180, 700, 480, 480, fill="#ffffff", opacity=0.6)
    b.shape("round", 230, 300, 1040, 600, fill="#ffffff", radius=60, shadow=True)
    b.icon(_c(content, "emoji", "🎂"), 640, 90, 230, set="color")
    b.text(_c(content, "headline", "Happy Birthday!"), 280, 340, 940, 200, role="headline", size=110, color=b.primary,
           align="center", valign="middle", bold=True)
    b.text(_c(content, "message", "Hope your day is as sweet as you are!"), 300, 560, 900, 180, role="body",
           size=50, color=b.dark, align="center", line=1.3)
    b.text(_c(content, "from", "xoxo"), 300, 760, 900, 80, role="from", size=44, color=b.secondary, align="center")
    return b.d


# --- menus (A4) -----------------------------------------------------------------------------------

SAMPLE_MENU = [
    {"name": "Starters", "items": [{"name": "Lentil soup", "desc": "with lemon and toasted bread", "price": "120"},
                                   {"name": "Hummus", "desc": "chickpeas, tahini, olive oil", "price": "140"},
                                   {"name": "Stuffed vine leaves", "desc": "rice, herbs, pine nuts", "price": "160"}]},
    {"name": "Mains", "items": [{"name": "Adana kebab", "desc": "spicy minced lamb, grilled peppers", "price": "380"},
                                {"name": "Grilled sea bass", "desc": "rocket salad, lemon butter", "price": "450"},
                                {"name": "Vegetable moussaka", "desc": "aubergine, tomato, béchamel", "price": "290"}]},
    {"name": "Desserts", "items": [{"name": "Baklava", "desc": "pistachio, syrup", "price": "180"},
                                   {"name": "Künefe", "desc": "warm cheese pastry", "price": "200"}]},
]


def _menu(b: Builder, content: dict, top: float, bottom: float, x: float, w: float, colors: dict,
          section_style: str) -> None:
    sections = (content or {}).get("sections") or SAMPLE_MENU
    rows = sum(1 + len(s.get("items") or []) for s in sections if isinstance(s, dict)) or 1
    unit = min(110.0, (bottom - top) / (rows + 0.6 * len(sections)))
    size = unit * 0.38
    y = top
    for section in sections:
        if not isinstance(section, dict):
            continue
        name = str(section.get("name", ""))
        if section_style == "pill":
            b.shape("round", x, y + unit * 0.1, min(w, max(220, len(name) * size * 0.75 + 80)), unit * 0.8,
                    role="section", fill=colors["section_bg"], text=name, color=colors["section"], size=size * 1.05,
                    bold=True, radius=unit, font=b.heading)
        else:
            b.text(upper(name) if section_style == "caps" else name, x, y, w, unit, role="section", size=size * 1.3,
                   color=colors["section"], bold=True, align="center" if section_style == "center" else "left",
                   valign="middle", autofit=False)
        y += unit * 1.25
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            price = str(item.get("price", "")).strip()
            if price and price[0].isdigit():
                price = f"{price} {content.get('currency', '₺')}".strip()
            b.text(str(item.get("name", "")), x, y, w * 0.72, unit * 0.5, role="item", size=size, color=colors["item"],
                   bold=True, valign="middle")
            b.text(price, x + w * 0.72, y, w * 0.28, unit * 0.5, role="price", size=size, color=colors["price"],
                   bold=True, align="right", valign="middle")
            if item.get("desc"):
                b.text(str(item["desc"]), x, y + unit * 0.48, w * 0.8, unit * 0.42, role="desc", size=size * 0.78,
                       color=colors["desc"], italic=True, valign="top")
            y += unit
        y += unit * 0.35


def menu_classic(content=None, style=None) -> dict:
    s = _style(style, "wedding", "Georgia", "Constantia")
    b = Builder("menu", "poster", _c(content, "name", "Menu"), s, bg="#fbf6ec")
    b.shape("rect", 50, 50, 1140, 1654, fill=None, stroke=b.primary, stroke_w=3)
    b.text(_c(content, "name", "Lokanta Ada"), 100, 100, 1040, 150, role="headline", size=100, color=b.dark,
           align="center", valign="middle", italic=True)
    b.text(upper(_c(content, "tagline", "Home cooking since 1987")), 100, 250, 1040, 60, role="subtitle", size=32,
           color=b.primary, align="center", font=b.body)
    b.line(420, 330, 820, 330, stroke=b.primary, stroke_w=2)
    _menu(b, content or {}, 370, 1560, 140, 960,
          {"section": b.primary, "item": b.dark, "price": b.primary, "desc": b.secondary, "section_bg": b.primary},
          "center")
    b.text(_c(content, "footer", "Moda Cad. 12, Kadıköy · 0216 000 00 00"), 100, 1600, 1040, 60, role="footer",
           size=30, color=b.secondary, align="center")
    return b.d


def menu_modern(content=None, style=None) -> dict:
    s = _style(style, "food", "Bahnschrift", "Segoe UI")
    b = Builder("menu", "poster", _c(content, "name", "Menu"), s, bg="#ffffff")
    b.shape("rect", 0, 0, 40, 1754, fill=b.primary)
    b.shape("rect", 0, 0, 1240, 330, fill=b.light)
    b.text(_c(content, "name", "GRILL & GREENS"), 110, 80, 1020, 150, role="headline", size=110, color=b.dark,
           bold=True, valign="middle")
    b.text(_c(content, "tagline", "Fresh, local, made to order"), 110, 230, 1020, 60, role="subtitle", size=38,
           color=b.primary, font=b.body)
    _menu(b, content or {}, 380, 1600, 110, 1020,
          {"section": "#ffffff", "item": b.dark, "price": b.primary, "desc": "#6b7280", "section_bg": b.primary}, "pill")
    b.text(_c(content, "footer", "Order online · grillandgreens.com"), 110, 1640, 1020, 60, role="footer", size=30,
           color="#6b7280")
    return b.d


def menu_chalk(content=None, style=None) -> dict:
    s = _style(style, "nature", "Segoe Print", "Segoe UI")
    b = Builder("menu", "poster", _c(content, "name", "Menu"), s, bg="#1f2a24")
    chalk = "#f1f5e9"
    b.shape("rect", 40, 40, 1160, 1674, fill=None, stroke="#8b6b3d", stroke_w=24)
    b.text(_c(content, "name", "Today's Menu"), 100, 110, 1040, 170, role="headline", size=110, color=chalk,
           align="center", valign="middle")
    b.icon("✿", 590, 290, 60, color="#e9c46a")
    _menu(b, content or {}, 380, 1560, 130, 980,
          {"section": "#e9c46a", "item": chalk, "price": "#e9c46a", "desc": "#b7c4b0", "section_bg": "#e9c46a"},
          "caps")
    b.text(_c(content, "footer", "Ask about our daily specials"), 100, 1600, 1040, 60, role="footer", size=32,
           color="#b7c4b0", align="center")
    return b.d


# --- wedding invitations (1050 x 1470) -------------------------------------------------------------

def invite_floral(content=None, style=None) -> dict:
    s = _style(style, "wedding", "Segoe Script", "Constantia")
    b = Builder("invitation", "invitation", _c(content, "names", "Invitation"), s, bg="#fffdf8")
    for glyph, x, y, size, rot in (("🌸", -30, -20, 220, -20), ("🌿", 150, -40, 200, 40), ("🌿", 840, 1290, 220, 200),
                                   ("🌸", 880, 1230, 160, 10), ("🌸", 860, -10, 150, 30), ("🌿", -40, 1280, 200, -60)):
        b.icon(glyph, x, y, size, set="color", rot=rot, role="deco")
    b.text(upper(_c(content, "message", "Together with their families")), 120, 300, 810, 70, role="subtitle",
           size=30, color=b.secondary, align="center", font=b.body)
    b.text(_c(content, "names", "Ayşe & Mehmet"), 80, 390, 890, 300, role="name", size=140, color=b.primary,
           align="center", valign="middle")
    b.text("request the pleasure of your company", 120, 700, 810, 70, role="body", size=34, color=b.dark,
           align="center", italic=True)
    b.line(375, 800, 675, 800, stroke=b.accent, stroke_w=2)
    _details(b, content or {}, 120, 840, 810, 38, b.dark)
    b.text(_c(content, "rsvp", "RSVP by 1 May · 0555 000 00 00"), 120, 1110, 810, 60, role="rsvp", size=30,
           color=b.secondary, align="center")
    return b.d


def invite_gold(content=None, style=None) -> dict:
    s = _style(style, "luxury", "Georgia", "Constantia")
    b = Builder("invitation", "invitation", _c(content, "names", "Invitation"), s, bg="#0f2a24")
    gold = "#d4af37"
    b.shape("rect", 45, 45, 960, 1380, fill=None, stroke=gold, stroke_w=4)
    b.shape("rect", 65, 65, 920, 1340, fill=None, stroke=gold, stroke_w=1.5)
    b.shape("diamond", 485, 120, 80, 80, fill=gold)
    b.text("THE WEDDING OF", 120, 260, 810, 60, role="subtitle", size=34, color=gold, align="center", font=b.body)
    b.text(_c(content, "names", "Elif & Can"), 90, 340, 870, 280, role="name", size=130, color="#f8f1df",
           align="center", valign="middle", italic=True)
    b.line(375, 650, 675, 650, stroke=gold, stroke_w=2)
    _details(b, content or {}, 120, 700, 810, 38, "#f8f1df")
    b.text(_c(content, "message", "Dinner and dancing to follow"), 120, 980, 810, 70, role="body", size=34,
           color=gold, align="center", italic=True)
    b.text(_c(content, "rsvp", "Kindly reply by 1 May"), 120, 1230, 810, 60, role="rsvp", size=30, color="#c9bfa5",
           align="center")
    return b.d


def invite_minimal(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Georgia", "Segoe UI")
    b = Builder("invitation", "invitation", _c(content, "names", "Invitation"), s, bg="#ffffff")
    b.line(100, 220, 950, 220, stroke="#111111", stroke_w=2)
    b.line(100, 1250, 950, 1250, stroke="#111111", stroke_w=2)
    b.text("SAVE THE DATE", 100, 270, 850, 60, role="subtitle", size=34, color="#111111", align="center",
           font=b.body, bold=True)
    names = _c(content, "names", "Zeynep & Ali").replace("&", "\n&\n")
    b.text(names, 100, 360, 850, 520, role="name", size=120, color="#111111", align="center", valign="middle",
           line=1.05)
    _details(b, content or {}, 100, 920, 850, 36, "#333333")
    b.text(_c(content, "rsvp", "Formal invitation to follow"), 100, 1160, 850, 60, role="rsvp", size=28,
           color="#555555", align="center", italic=True)
    return b.d


# --- stickers and badges (1000 x 1000) -------------------------------------------------------------

def sticker_circle(content=None, style=None) -> dict:
    s = _style(style, "retro", "Impact", "Segoe UI")
    b = Builder("sticker", "sticker", _c(content, "text", "Sticker"), s, bg="#ffffff")
    b.shape("ellipse", 80, 80, 840, 840, fill="#ffffff", stroke=b.dark, stroke_w=10, shadow=True)
    b.shape("ellipse", 120, 120, 760, 760, fill=b.primary)
    b.shape("ellipse", 160, 160, 680, 680, fill=None, stroke="#ffffff", stroke_w=6, role="deco")
    b.icon(_c(content, "icon", "★"), 430, 220, 140, color=b.accent)
    b.text(upper(_c(content, "text", "BEST SELLER")), 200, 380, 600, 240, role="headline", size=130,
           color="#ffffff", align="center", valign="middle", line=1.0)
    b.text(upper(_c(content, "sub", "since 2026")), 250, 640, 500, 80, role="subtitle", size=44, color=b.accent,
           align="center", valign="middle", font=b.body, bold=True)
    return b.d


def sticker_burst(content=None, style=None) -> dict:
    s = _style(style, "energetic", "Impact", "Segoe UI")
    b = Builder("sticker", "sticker", _c(content, "text", "Sticker"), s, bg="#ffffff")
    b.shape("burst", 60, 60, 880, 880, fill=b.primary, rot=8, shadow=True)
    b.shape("ellipse", 230, 230, 540, 540, fill=b.accent)
    b.text(upper(_c(content, "text", "NEW!")), 260, 320, 480, 260, role="headline", size=170, color=b.dark,
           align="center", valign="middle", rot=-8, line=1.0)
    b.text(_c(content, "sub", "limited edition"), 280, 580, 440, 90, role="subtitle", size=48, color=b.dark,
           align="center", valign="middle", rot=-8, font=b.body, bold=True)
    return b.d


def sticker_ribbon(content=None, style=None) -> dict:
    s = _style(style, "royal", "Georgia", "Segoe UI")
    b = Builder("sticker", "sticker", _c(content, "text", "Badge"), s, bg="#ffffff")
    b.shape("burst", 170, 90, 660, 660, fill=b.accent)
    b.shape("ellipse", 230, 150, 540, 540, fill=b.primary)
    b.icon(_c(content, "icon", "★"), 420, 250, 160, color=b.accent)
    b.text(upper(_c(content, "sub", "No. 1")), 300, 430, 400, 120, role="subtitle", size=80, color="#ffffff",
           align="center", valign="middle", bold=True)
    b.shape("ribbon", 60, 650, 880, 170, role="ribbon", fill=b.secondary, text=upper(_c(content, "text", "QUALITY")),
            size=80, bold=True, color="#ffffff")
    return b.d


# --- sale posters (A4) -----------------------------------------------------------------------------

def sale_burst(content=None, style=None) -> dict:
    s = _style(style, "energetic", "Impact", "Segoe UI")
    b = Builder("sale", "poster", _c(content, "headline", "Sale"), s, bg=s["palette"][0])
    b.shape("ellipse", -300, 1150, 900, 900, fill=b.secondary, opacity=0.9)
    b.text(upper(_c(content, "headline", "MEGA SALE")), 80, 120, 1080, 420, role="headline", size=230,
           color="#ffffff", align="center", valign="middle", line=0.95, shadow=True)
    b.shape("burst", 320, 560, 600, 600, role="discount", fill=b.accent, rot=-10,
            text=_c(content, "discount", "50%") + "\nOFF", size=150, color=b.dark, bold=True, line=0.95)
    b.text(_c(content, "sub", "on everything in store"), 80, 1200, 1080, 100, role="subtitle", size=60,
           color="#ffffff", align="center", bold=True, font=b.body)
    b.text(_c(content, "dates", "This weekend only · Sat–Sun"), 80, 1320, 1080, 80, role="dates", size=46,
           color="#ffffff", align="center", font=b.body)
    b.shape("round", 370, 1480, 500, 120, role="cta", fill="#ffffff", text=_c(content, "cta", "Shop now"),
            color=b.primary, size=54, bold=True, radius=60, font=b.body)
    return b.d


def sale_stripe(content=None, style=None) -> dict:
    s = _style(style, "minimal", "Impact", "Segoe UI")
    b = Builder("sale", "poster", _c(content, "headline", "Sale"), s, bg="#ffffff")
    for i in range(9):
        b.shape("rect", -400 + i * 230, -200, 90, 2300, fill=b.accent if i % 2 else "#ffe3e3", rot=25, opacity=0.9)
    b.shape("rect", 70, 200, 1100, 1300, fill="#ffffff", shadow=True)
    b.text(upper(_c(content, "headline", "SALE")), 120, 260, 1000, 420, role="headline", size=330, color="#111111",
           align="center", valign="middle", line=0.9)
    b.shape("ellipse", 420, 700, 400, 400, role="discount", fill=b.accent,
            text="-" + _c(content, "discount", "40%"), size=130, color="#ffffff", bold=True)
    b.text(_c(content, "sub", "Summer collection"), 120, 1150, 1000, 100, role="subtitle", size=64, color="#111111",
           align="center", font=b.body, bold=True)
    b.text(_c(content, "dates", "1–15 July"), 120, 1270, 1000, 80, role="dates", size=48, color="#444444",
           align="center", font=b.body)
    b.text(_c(content, "cta", "In store & online"), 120, 1380, 1000, 70, role="cta", size=42, color=b.accent,
           align="center", bold=True, font=b.body)
    return b.d


def sale_tag(content=None, style=None) -> dict:
    s = _style(style, "sunset", "Bahnschrift", "Segoe UI")
    b = Builder("sale", "poster", _c(content, "headline", "Sale"), s, bg="#fff4e6")
    b.text(_c(content, "headline", "Black Friday"), 90, 110, 1060, 300, role="headline", size=170, color=b.dark,
           bold=True, align="center", valign="middle", line=1.0)
    b.shape("round", 250, 470, 740, 820, role="tag", fill=b.primary, radius=60, rot=-8, shadow=True)
    b.shape("ellipse", 560, 540, 110, 110, role="deco", fill="#fff4e6", rot=-8)
    b.text(_c(content, "discount", "70%"), 280, 720, 680, 330, role="discount", size=260, color="#ffffff", bold=True,
           align="center", valign="middle", rot=-8, line=1.0)
    b.text("OFF", 280, 1020, 680, 140, role="discount", size=110, color=b.accent, bold=True, align="center",
           valign="middle", rot=-8)
    b.text(_c(content, "sub", "Biggest deals of the year"), 90, 1380, 1060, 90, role="subtitle", size=56,
           color=b.dark, align="center", font=b.body)
    b.text(_c(content, "dates", "Friday 28 November"), 90, 1490, 1060, 80, role="dates", size=46,
           color=b.secondary, align="center", bold=True, font=b.body)
    return b.d


# --- slide themes and decks -----------------------------------------------------------------------

SLIDE_THEMES: dict[str, dict] = {
    "midnight": dict(label="Midnight", bg="#0f172a", cover_bg="#0f172a", title="#f8fafc", body="#cbd5e1",
                     accent="#38bdf8", accent2="#818cf8", surface="#1e293b", heading="Segoe UI", body_font="Segoe UI",
                     style="bar"),
    "paper": dict(label="Paper", bg="#ffffff", cover_bg="#ffffff", title="#1f2a44", body="#3f4a5c", accent="#ef6351",
                  accent2="#1f2a44", surface="#f4f1ea", heading="Georgia", body_font="Segoe UI", style="underline"),
    "ocean": dict(label="Ocean", bg="#f2f8fd", cover_bg="#0b4f8a", title="#0b3a66", body="#2b4a66", accent="#1e88e5",
                  accent2="#00bcd4", surface="#dbeefb", heading="Bahnschrift", body_font="Segoe UI", style="band"),
    "forest": dict(label="Forest", bg="#f6fbf4", cover_bg="#1b4332", title="#1b4332", body="#2d4a3a",
                   accent="#40916c", accent2="#d4a373", surface="#e3f1e6", heading="Cambria", body_font="Calibri",
                   style="side"),
    "sunset": dict(label="Sunset", bg="#fff8f1", cover_bg="#fff8f1", title="#3d1f12", body="#5c3a2a",
                   accent="#f76707", accent2="#e64980", surface="#ffe8d6", heading="Trebuchet MS", body_font="Segoe UI",
                   style="circle"),
    "royal": dict(label="Royal", bg="#faf7ff", cover_bg="#3b1f73", title="#2e1065", body="#4c3a75", accent="#7c3aed",
                  accent2="#f59f00", surface="#ede5ff", heading="Palatino Linotype", body_font="Segoe UI", style="band"),
    "mono": dict(label="Mono", bg="#ffffff", cover_bg="#ffffff", title="#111111", body="#333333", accent="#111111",
                 accent2="#e03131", surface="#f1f1f1", heading="Segoe UI", body_font="Segoe UI", style="minimal"),
    "candy": dict(label="Candy", bg="#fff5fa", cover_bg="#fff5fa", title="#4a1942", body="#5b3a55", accent="#e64980",
                  accent2="#7950f2", surface="#ffe3f1", heading="Segoe UI", body_font="Segoe UI", style="blobs"),
    "slate": dict(label="Slate", bg="#f8fafc", cover_bg="#0f766e", title="#0f172a", body="#334155", accent="#0f766e",
                  accent2="#f59e0b", surface="#e2e8f0", heading="Segoe UI", body_font="Segoe UI", style="split"),
    "coffee": dict(label="Coffee", bg="#faf6f1", cover_bg="#3e2723", title="#3e2723", body="#5d4037",
                   accent="#a1662f", accent2="#d7b98e", surface="#efe4d6", heading="Georgia", body_font="Constantia",
                   style="underline"),
    "neon": dict(label="Neon", bg="#09090b", cover_bg="#09090b", title="#fafafa", body="#d4d4d8", accent="#a3e635",
                 accent2="#22d3ee", surface="#18181b", heading="Bahnschrift", body_font="Segoe UI", style="bar"),
    "classroom": dict(label="Classroom", bg="#fffbeb", cover_bg="#2563eb", title="#1e3a8a", body="#374151",
                      accent="#2563eb", accent2="#f59e0b", surface="#fef3c7", heading="Comic Sans MS",
                      body_font="Segoe UI", style="blobs"),
}
SLIDE_W, SLIDE_H = 1920, 1080


def theme_palette(theme: dict) -> list[str]:
    return [theme["accent"], theme["accent2"], theme["surface"], theme["bg"], theme["title"]]


def _cover_colors(theme: dict) -> tuple[str, str]:
    bg = theme["cover_bg"]
    if model.contrast(theme["title"], bg) >= 4.5:
        return theme["title"], theme["body"]
    return model.readable_on(bg), model.mix(model.readable_on(bg), bg, 0.25)


def decorate(design: dict, page: dict, theme: dict) -> None:
    """The theme's shapes for one page, tagged role 'deco' so a new theme can replace them."""
    page["elements"] = [e for e in page["elements"] if e.get("role") != "deco"]
    layout = page.get("layout", "content")
    style, a, a2, surface = theme["style"], theme["accent"], theme["accent2"], theme["surface"]
    W, H = design["w"], design["h"]
    deco: list[dict] = []
    if layout == "cover":
        if style in {"bar", "underline", "minimal"}:
            deco.append(model.shape("rect", 140, 640, 200, 14, fill=a))
        if style == "band":
            deco.append(model.shape("rect", 0, H - 60, W, 60, fill=a2))
        if style == "side":
            deco.append(model.shape("rect", 0, 0, 40, H, fill=a))
            deco.append(model.shape("rect", 140, 640, 200, 14, fill=a2))
        if style == "circle":
            deco += [model.shape("ellipse", W - 700, -300, 1000, 1000, fill=a, opacity=0.9),
                     model.shape("ellipse", W - 380, 560, 520, 520, fill=a2, opacity=0.85)]
        if style == "blobs":
            deco += [model.shape("ellipse", W - 560, -220, 760, 760, fill=a, opacity=0.25),
                     model.shape("ellipse", -200, H - 380, 600, 600, fill=a2, opacity=0.25),
                     model.shape("rect", 140, 640, 200, 14, fill=a)]
        if style == "split":
            deco.append(model.shape("rect", W * 0.62, 0, W * 0.38, H, fill=theme["accent2"]))
    else:
        if style == "bar":
            deco.append(model.shape("rect", 0, 0, 18, H, fill=a))
        elif style == "band":
            deco.append(model.shape("rect", 0, 0, W, 26, fill=a))
        elif style == "side":
            deco.append(model.shape("rect", 0, 0, 60, H, fill=a))
        elif style == "circle":
            deco.append(model.shape("ellipse", W - 300, -300, 560, 560, fill=a2, opacity=0.18))
        elif style == "blobs":
            deco += [model.shape("ellipse", W - 260, H - 260, 420, 420, fill=a, opacity=0.18),
                     model.shape("ellipse", W - 420, H - 140, 260, 260, fill=a2, opacity=0.18)]
        elif style == "split":
            deco.append(model.shape("rect", 0, 0, W, 230, fill=surface))
        if style in {"underline", "bar", "band", "side", "blobs"}:
            deco.append(model.shape("rect", _content_x(theme), 228, 140, 10, fill=a))
        elif style == "minimal":
            deco.append(model.shape("rect", _content_x(theme), 236, W - 2 * _content_x(theme), 3, fill=a))
    for i, el in enumerate(deco):
        el["role"] = "deco"
        el["locked"] = True
        model.add(design, page, el, index=i)


def _content_x(theme: dict) -> float:
    return 170 if theme["style"] == "side" else 120


def style_text(page: dict, theme: dict) -> None:
    cover = page.get("layout") == "cover"
    cover_title, cover_sub = _cover_colors(theme)
    heading, body = _font(theme["heading"]), _font(theme["body_font"])
    for el in page["elements"]:
        role = el.get("role")
        if el["type"] not in {"text", "shape"}:
            continue
        if role == "title":
            el["font"], el["color"] = heading, (cover_title if cover else theme["title"])
            if cover and theme["style"] == "circle":
                el["color"] = theme["title"]
        elif role in {"subtitle", "body", "footer", "notes"}:
            el["font"] = body
            el["color"] = cover_sub if cover and role == "subtitle" else theme["body"]
            if role == "footer":
                el["color"] = model.mix(theme["body"], theme["bg"], 0.4)
        elif role == "option" and el["type"] == "shape":
            el["font"], el["fill"], el["color"] = body, theme["surface"], theme["title"]
        elif role == "answer" and el["type"] == "shape":
            el["font"] = body


def apply_theme(design: dict, name: str) -> dict:
    theme = SLIDE_THEMES.get(name) or SLIDE_THEMES["midnight"]
    design["theme"] = name if name in SLIDE_THEMES else "midnight"
    for page in design["pages"]:
        cover = page.get("layout") == "cover"
        page["bg"] = theme["cover_bg"] if cover else theme["bg"]
        decorate(design, page, theme)
        style_text(page, theme)
    design["palette"] = theme_palette(theme)
    design["fonts"] = {"heading": _font(theme["heading"]), "body": _font(theme["body_font"])}
    return design


def cover_page(design: dict, title: str, subtitle: str, theme: dict) -> dict:
    page = model.new_page(theme["cover_bg"])
    page["layout"] = "cover"
    width = 1000 if theme["style"] in {"split", "circle"} else 1640
    model.add(design, page, model.text(title, 140, 220, width, 400, role="title", size=140, bold=True,
                                       autofit=True, valign="bottom", line=1.05))
    model.add(design, page, model.text(subtitle, 140, 690, width, 180, role="subtitle", size=58, autofit=True))
    return page


def content_page(design: dict, title: str, bullets: list[str], theme: dict, notes: str = "",
                 image: str = "", number: int | None = None) -> dict:
    page = model.new_page(theme["bg"])
    page["layout"] = "content"
    page["notes"] = notes
    x = _content_x(theme)
    W = design["w"]
    model.add(design, page, model.text(title, x, 64, W - x - 120, 150, role="title", size=68, bold=True,
                                       autofit=True, valign="bottom", line=1.05))
    text = "\n".join(f"•  {b}" for b in bullets if str(b).strip())
    body_w = (W - x - 120) if not image else 980
    model.add(design, page, model.text(text, x, 290, body_w, 690, role="body", size=44, autofit=True, line=1.45))
    if image:
        model.add(design, page, model.picture(image, x + body_w + 60, 290, W - (x + body_w + 60) - 120, 690,
                                              role="image", radius=24))
    if number is not None:
        model.add(design, page, model.text(str(number), W - 160, design["h"] - 80, 80, 50, role="footer", size=26,
                                           align="right"))
    return page


def build_deck(deck: dict, theme_name: str = "midnight") -> dict:
    """{"title", "subtitle", "slides": [{"title", "bullets", "notes", "image"?}]} -> a slides design."""
    theme = SLIDE_THEMES.get(theme_name) or SLIDE_THEMES["midnight"]
    design = model.new_design("slides", "slides", str(deck.get("title") or "Presentation"))
    design["pages"] = [cover_page(design, str(deck.get("title") or "Presentation"), str(deck.get("subtitle") or ""),
                                  theme)]
    for number, slide in enumerate(deck.get("slides") or [], 2):
        if not isinstance(slide, dict):
            continue
        bullets = [str(b) for b in slide.get("bullets") or []][:8]
        design["pages"].append(content_page(design, str(slide.get("title") or ""), bullets, theme,
                                            str(slide.get("notes") or ""), str(slide.get("image") or ""), number))
    return apply_theme(design, theme_name if theme_name in SLIDE_THEMES else "midnight")


def quiz_deck(topic: str, questions: list[dict], theme_name: str = "classroom") -> dict:
    """A question slide then an answer slide for each multiple-choice question."""
    theme = SLIDE_THEMES.get(theme_name) or SLIDE_THEMES["classroom"]
    design = model.new_design("slides", "slides", f"Quiz: {topic}")
    design["pages"] = [cover_page(design, f"Quiz: {topic}", f"{len(questions)} questions", theme)]
    letters = "ABCD"
    for n, q in enumerate(questions, 1):
        for reveal in (False, True):
            page = model.new_page(theme["bg"])
            page["layout"] = "content"
            page["notes"] = (f"Answer: {letters[q['answer']]}. {q.get('why', '')}" if not reveal else q.get("why", ""))
            model.add(design, page, model.text(f"{n}. {q['q']}", 120, 60, 1680, 230, role="title", size=60, bold=True,
                                               autofit=True, valign="bottom"))
            for i, option in enumerate(q["options"][:4]):
                col, row = i % 2, i // 2
                right = reveal and i == q["answer"]
                el = model.shape("round", 120 + col * 860, 340 + row * 260, 820, 220,
                                 role="answer" if right else "option", text=f"{letters[i]})  {option}", size=42,
                                 align="left", radius=28, fill="#16a34a" if right else theme["surface"],
                                 color="#ffffff" if right else theme["title"])
                if reveal and not right:
                    el["opacity"] = 0.45
                model.add(design, page, el)
            if reveal and q.get("why"):
                model.add(design, page, model.text(f"✓ {q['why']}", 120, 880, 1680, 140, role="body", size=36,
                                                   autofit=True, italic=True))
            design["pages"].append(page)
    return apply_theme(design, theme_name if theme_name in SLIDE_THEMES else "classroom")


# --- the catalogue ----------------------------------------------------------------------------------

KINDS: dict[str, dict] = {
    "thumbnail": {"label": "YouTube thumbnail", "fields": ["headline", "sub", "emoji"],
                  "variants": {"split": thumbnail_split, "center": thumbnail_center, "banner": thumbnail_banner}},
    "poster": {"label": "Poster / flyer", "fields": ["headline", "sub", "body", "date", "time", "place", "cta"],
               "variants": {"modern": poster_modern, "bold": poster_bold, "elegant": poster_elegant}},
    "logo": {"label": "Logo", "fields": ["name", "tagline", "icon"],
             "variants": {"emblem": logo_emblem, "wordmark": logo_wordmark, "monogram": logo_monogram}},
    "card": {"label": "Greeting card", "fields": ["headline", "message", "from", "emoji"],
             "variants": {"confetti": card_confetti, "elegant": card_elegant, "cute": card_cute}},
    "menu": {"label": "Restaurant menu", "fields": ["name", "tagline", "sections", "footer", "currency"],
             "variants": {"classic": menu_classic, "modern": menu_modern, "chalk": menu_chalk}},
    "invitation": {"label": "Wedding invitation", "fields": ["names", "message", "date", "time", "place", "rsvp"],
                   "variants": {"floral": invite_floral, "gold": invite_gold, "minimal": invite_minimal}},
    "sticker": {"label": "Sticker / badge", "fields": ["text", "sub", "icon"],
                "variants": {"circle": sticker_circle, "burst": sticker_burst, "ribbon": sticker_ribbon}},
    "sale": {"label": "Sale poster", "fields": ["headline", "discount", "sub", "dates", "cta"],
             "variants": {"burst": sale_burst, "stripe": sale_stripe, "tag": sale_tag}},
}


def make(kind: str, variant: str = "", content: dict | None = None, style: dict | None = None) -> dict:
    spec = KINDS.get(kind)
    if spec is None:
        raise model.DesignError(f"Unknown design kind: {kind}")
    builder = spec["variants"].get(variant) or next(iter(spec["variants"].values()))
    design = builder(content or {}, style)
    if content and (content.get("title") or content.get("headline") or content.get("name") or content.get("names")):
        design["title"] = str(content.get("title") or content.get("headline") or content.get("name")
                              or content.get("names"))[:80]
    return design


def catalogue() -> list[dict]:
    """Every built-in template: {key, label, group, make()} — 38 designs, 12 slide themes, 8 diagrams."""
    out = []
    for kind, spec in KINDS.items():
        for variant in spec["variants"]:
            out.append({"key": f"{kind}:{variant}", "label": f"{spec['label']} — {variant}", "group": spec["label"],
                        "make": (lambda k=kind, v=variant: make(k, v))})
    sample = {"title": "Our Big Idea", "subtitle": "A short story in five slides",
              "slides": [{"title": "Why it matters", "bullets": ["The problem today", "Who it hurts", "What it costs"]},
                         {"title": "What we'll do", "bullets": ["Step one", "Step two", "Step three"]}]}
    for name, theme in SLIDE_THEMES.items():
        out.append({"key": f"slides:{name}", "label": f"Slides — {theme['label']}", "group": "Slides",
                    "make": (lambda n=name: build_deck(sample, n))})
    from . import diagrams

    for kind, spec in diagrams.KINDS.items():
        out.append({"key": f"diagram:{kind}", "label": spec["label"], "group": "Diagrams",
                    "make": (lambda k=kind: diagrams.sample(k))})
    return out


def blank(fmt: str = "slides") -> dict:
    design = model.new_design("slides" if fmt == "slides" else fmt, fmt, f"Untitled {model.FORMATS[fmt][0]}")
    if fmt == "slides":
        design["pages"][0]["layout"] = "content"
    return design


from . import more_templates  # noqa: E402,F401  (10.0's kinds join KINDS)
