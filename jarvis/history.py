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


def _path() -> Path:
    return get_data_dir() / HISTORY_FILE


def save(messages: list[dict], mode: str = "", code_mode: bool = False) -> None:
    """Write the conversation. Best effort — never interrupts the app."""
    try:
        payload = {
            "saved": datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "code_mode": code_mode,
            "messages": messages[-MAX_SAVED_MESSAGES:],
        }
        _path().write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError):
        pass


def load() -> tuple[list[dict], str, bool]:
    """Return (messages, mode, code_mode) from the last session."""
    path = _path()
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


def clear() -> None:
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass


def describe_saved() -> str:
    """One line about what is on disk, for the startup notice."""
    messages, _mode, _code = load()
    if not messages:
        return ""
    exchanges = len(messages) // 2
    return f"{exchanges} earlier exchange{'s' if exchanges != 1 else ''} restored"


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
