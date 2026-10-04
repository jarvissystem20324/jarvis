"""How the window is arranged: open sidebar sections, accent colour, chat
style, avatar, shortcuts, home widgets (10.0).

Kept apart from .env, which holds keys and provider choices — these are
cosmetic, change often, and are written from the Tk thread on every click.
"""

from __future__ import annotations

from . import kit

_STORE = kit.Store("ui_prefs.json", {})
_cache: dict | None = None


def all() -> dict:  # noqa: A001 — mirrors dict.items() style use: prefs.all()
    global _cache
    if _cache is None:
        _cache = _STORE.load()
    return _cache


def get(name: str, default=None):
    return all().get(name, default)


def set(name: str, value) -> None:  # noqa: A001
    data = all()
    data[name] = value
    try:
        _STORE.save(data)
    except OSError:
        pass


def reset_cache() -> None:
    global _cache
    _cache = None
