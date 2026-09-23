"""Conversation persistence and export.

Until now a conversation existed only in memory: closing the window threw away
whatever you had worked out. This keeps the last session on disk and hands it
back on the next start, and can write a transcript out as Markdown.

Only the visible turns are stored — the system prompt, the mode's thinking
instruction and any context addons injected are all rebuilt at send time, so
nothing here needs to hold them. That also means a saved history is readable
and safe to hand to someone else.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import get_data_dir, get_output_dir

HISTORY_FILE = "conversation.json"
# Plenty for continuity, small enough that loading is instant.
MAX_SAVED_MESSAGES = 60


CHATS_DIR = "chats"
CURRENT_FILE = "current.txt"
DEFAULT_CHAT = "main"


def _chats_dir() -> Path:
    path = get_data_dir() / CHATS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(name: str) -> str:
    """A filename that is safe on every platform and still recognisable."""
    cleaned = "".join(
        c if (c.isalnum() or c in " -_") else "-" for c in (name or "").strip()
    )
    cleaned = "-".join(cleaned.split()).strip("-").lower()
    return cleaned[:48] or DEFAULT_CHAT


def current_name() -> str:
    """Which conversation is open. Creates the default on first use."""
    marker = _chats_dir() / CURRENT_FILE
    try:
        name = marker.read_text(encoding="utf-8").strip()
        if name:
            return name
    except OSError:
        pass
    return DEFAULT_CHAT


def set_current(name: str) -> None:
    try:
        (_chats_dir() / CURRENT_FILE).write_text(name.strip(), encoding="utf-8")
    except OSError:
        pass


def _path(name: str | None = None) -> Path:
    """Where a conversation lives.

    The pre-3.3 single file is migrated into the new folder the first time
    this runs, so updating does not appear to lose the conversation you had
    open. The old file is left alone rather than deleted.
    """
    chats = _chats_dir()
    target = chats / f"{_slug(name or current_name())}.json"

    legacy = get_data_dir() / HISTORY_FILE
    if not target.exists() and legacy.is_file() and not any(chats.glob("*.json")):
        try:
            target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    return target


def list_chats() -> list[dict]:
    """Every saved conversation, newest first."""
    _path()  # triggers the one-time migration
    out: list[dict] = []
    for item in _chats_dir().glob("*.json"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        messages = data.get("messages")
        out.append({
            "name": data.get("name") or item.stem,
            "slug": item.stem,
            "saved": str(data.get("saved") or ""),
            "exchanges": len(messages) // 2 if isinstance(messages, list) else 0,
        })
    out.sort(key=lambda c: c["saved"], reverse=True)
    return out


def delete_chat(name: str) -> bool:
    path = _chats_dir() / f"{_slug(name)}.json"
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def save(messages: list[dict], mode: str = "", code_mode: bool = False,
         name: str | None = None) -> None:
    """Write the conversation. Best effort — never interrupts the app."""
    try:
        payload = {
            "name": name or current_name(),
            "saved": datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "code_mode": code_mode,
            "messages": messages[-MAX_SAVED_MESSAGES:],
        }
        _path(name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError):
        pass


def load(name: str | None = None) -> tuple[list[dict], str, bool]:
    """Return (messages, mode, code_mode) from a saved conversation."""
    path = _path(name)
    if not path.exists():
        return [], "", False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "", False
    if not isinstance(data, dict):
        return [], "", False

    messages = data.get("messages")
    if not isinstance(messages, list):
        return [], "", False

    # Only keep well-formed turns; a corrupt file should degrade to "no
    # history" rather than poison the next request.
    clean = [
        m for m in messages
        if isinstance(m, dict)
        and m.get("role") in {"user", "assistant"}
        and isinstance(m.get("content"), str)
    ]
    return clean, str(data.get("mode") or ""), bool(data.get("code_mode"))


def clear(name: str | None = None) -> None:
    try:
        _path(name).unlink(missing_ok=True)
    except OSError:
        pass


def describe_saved(name: str | None = None) -> str:
    """One line about what is on disk, for the startup notice."""
    messages, _mode, _code = load(name)
    if not messages:
        return ""
    exchanges = len(messages) // 2
    where = name or current_name()
    plural = "s" if exchanges != 1 else ""
    return f"{exchanges} earlier exchange{plural} restored from '{where}'"


def export_markdown(messages: list[dict], title: str = "") -> Path:
    """Write the conversation to a Markdown file and return its path."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = get_output_dir().parent / f"jarvis_chat_{stamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {title or 'JARVIS conversation'}",
        "",
        f"*Exported {datetime.now():%d %B %Y at %H:%M}*",
        "",
    ]
    for message in messages:
        who = "You" if message.get("role") == "user" else "JARVIS"
        lines.append(f"### {who}")
        lines.append("")
        lines.append((message.get("content") or "").strip())
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
