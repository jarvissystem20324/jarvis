"""Themes and text size.

Three palettes rather than a colour picker. A picker looks generous and
produces unreadable combinations; three that were each checked for contrast
do not. Every colour the window uses is named here, so a theme is complete by
construction — a missing key is a crash at start-up rather than one widget
staying black on black in the light theme.

The choice lives in .env like everything else, so it survives an update.
"""

from __future__ import annotations

from jarvis.config import get_setting

DEFAULT = "midnight"
MIN_FONT, MAX_FONT, DEFAULT_FONT = 10, 22, 14

THEMES: dict[str, dict[str, str]] = {
    # The original. Dark blue, cyan accent.
    "midnight": {
        "label": "Midnight",
        "appearance": "dark",
        "bg": "#0a0e17",
        "panel": "#111827",
        "accent": "#00d4ff",
        "accent_dim": "#0e7490",
        "text": "#e2e8f0",
        "user": "#60a5fa",
        "muted": "#64748b",
        "error": "#f87171",
        "ok": "#4ade80",
        "code_bg": "#0d1524",
        "kw": "#c084fc",
        "str": "#86efac",
        "com": "#64748b",
        "num": "#fbbf24",
    },
    # Dark, but warmer and lower contrast for long sessions.
    "graphite": {
        "label": "Graphite",
        "appearance": "dark",
        "bg": "#17181c",
        "panel": "#1f2126",
        "accent": "#f59e0b",
        "accent_dim": "#92400e",
        "text": "#e5e5e5",
        "user": "#fbbf24",
        "muted": "#8b8b8b",
        "error": "#ef4444",
        "ok": "#22c55e",
        "code_bg": "#111216",
        "kw": "#f472b6",
        "str": "#a3e635",
        "com": "#71717a",
        "num": "#38bdf8",
    },
    # For a bright room or a projector.
    "daylight": {
        "label": "Daylight",
        "appearance": "light",
        "bg": "#f8fafc",
        "panel": "#e9eef5",
        "accent": "#0369a1",
        "accent_dim": "#7dd3fc",
        "text": "#0f172a",
        "user": "#1d4ed8",
        "muted": "#64748b",
        "error": "#b91c1c",
        "ok": "#15803d",
        "code_bg": "#e2e8f0",
        "kw": "#7e22ce",
        "str": "#15803d",
        "com": "#64748b",
        "num": "#b45309",
    },
}

# Every theme must define exactly these. Checked at import so a half-written
# palette fails here rather than halfway through drawing the window.
REQUIRED = set(THEMES[DEFAULT])
for _name, _palette in THEMES.items():
    _missing = REQUIRED - set(_palette)
    if _missing:
        raise RuntimeError(f"theme '{_name}' is missing: {', '.join(sorted(_missing))}")


def names() -> dict[str, str]:
    return {key: value["label"] for key, value in THEMES.items()}


def get(name: str | None = None) -> dict[str, str]:
    """A palette by name, falling back to the default."""
    return THEMES.get((name or "").strip().lower(), THEMES[DEFAULT])


def from_env() -> tuple[dict[str, str], str, int]:
    """(palette, theme name, font size) as configured in .env."""
    wanted = get_setting("JARVIS_THEME", DEFAULT).strip().lower()
    if wanted not in THEMES:
        wanted = DEFAULT
    try:
        size = int(get_setting("JARVIS_FONT_SIZE", str(DEFAULT_FONT)))
    except ValueError:
        size = DEFAULT_FONT
    return THEMES[wanted], wanted, max(MIN_FONT, min(MAX_FONT, size))
