"""Quick notes and prompt templates — two small stores of your own text.

Notes are things you want to jot down: "/note buy milk". They are not what
JARVIS remembers about you (that is /remember) and they are never sent as
context; they sit, sealed, until you list or search them.

Templates are prompts you reuse: "/t email-reply <paste>" expands a saved
prompt around whatever you give it and asks it. A few useful ones come
built in and can be overwritten.
"""

from __future__ import annotations

import time
from datetime import datetime

from . import vault
from .config import get_data_dir

NOTES_FILE = "notes.json"
TEMPLATES_FILE = "templates.json"
MAX_NOTES = 1000


# --- notes -----------------------------------------------------------------

def _notes_path():
    return get_data_dir() / NOTES_FILE


def load_notes() -> list[dict]:
    path = _notes_path()
    if not path.exists():
        return []
    try:
        data = vault.read_json(path)
    except (OSError, ValueError):
        return []
    return [n for n in data if isinstance(n, dict) and n.get("text")] if isinstance(data, list) else []


def _save_notes(notes: list[dict]) -> None:
    vault.write_json(_notes_path(), notes[-MAX_NOTES:])


def add_note(text: str) -> str:
    text = text.strip()
    if not text:
        return "Usage: /note <anything>   —   /notes lists them, /notes <word> searches."
    notes = load_notes()
    notes.append({"text": text, "at": time.time()})
    _save_notes(notes)
    return f"Noted ({len(notes)}). /notes to see them."


def list_notes(search: str = "") -> str:
    notes = load_notes()
    needle = search.strip().lower()
    shown = [(i, n) for i, n in enumerate(notes, 1) if not needle or needle in n["text"].lower()]
    if not shown:
        return "No notes yet. /note <text> adds one." if not notes else f"No note mentions '{search}'."
    lines = [f"Notes ({len(shown)}{' matching' if needle else ''}):"]
    for index, note in shown[-50:]:
        when = datetime.fromtimestamp(float(note.get("at") or 0)).strftime("%d %b %H:%M")
        lines.append(f"  {index:>3}. {note['text']}   ({when})")
    lines.append("")
    lines.append("/notes delete <n>  ·  /notes clear")
    return "\n".join(lines)


def delete_note(which: str) -> str:
    notes = load_notes()
    which = which.strip().lower()
    if which in {"all", "clear", "everything"}:
        _save_notes([])
        return f"Deleted all {len(notes)} notes."
    if not which.isdigit() or not 1 <= int(which) <= len(notes):
        return f"There is no note {which}. /notes lists them with numbers."
    removed = notes.pop(int(which) - 1)
    _save_notes(notes)
    return f"Deleted: {removed['text'][:80]}"


# --- templates ---------------------------------------------------------------

BUILT_IN = {
    "email-reply": "Write a short, polite reply to this email. Match its tone and language, "
                   "and answer every question it asks:\n\n{input}",
    "summarize": "Summarise this in five bullet points, then one sentence on what matters most:\n\n{input}",
    "fix-grammar": "Correct the spelling and grammar. Keep my wording and tone; only fix mistakes. "
                   "Return just the corrected text:\n\n{input}",
    "eli5": "Explain this like I'm five, then once more like I'm a university student:\n\n{input}",
    "translate-tr": "Translate into natural Turkish. Return only the translation:\n\n{input}",
    "translate-en": "Translate into natural English. Return only the translation:\n\n{input}",
    "review-code": "Review this code for bugs, edge cases and unclear names. Most important first:\n\n{input}",
}


def _templates_path():
    return get_data_dir() / TEMPLATES_FILE


def load_templates() -> dict[str, str]:
    saved: dict[str, str] = {}
    path = _templates_path()
    if path.exists():
        try:
            data = vault.read_json(path)
            if isinstance(data, dict):
                saved = {str(k): str(v) for k, v in data.items() if v}
        except (OSError, ValueError):
            pass
    return {**BUILT_IN, **saved}


def save_template(name: str, body: str) -> str:
    name = name.strip().lower()
    if not name or not body.strip():
        return "Usage: /t save <name> <prompt, with {input} where your text goes>"
    path = _templates_path()
    saved = {}
    if path.exists():
        try:
            saved = vault.read_json(path) or {}
        except (OSError, ValueError):
            saved = {}
    body = body.strip()
    if "{input}" not in body:
        body += "\n\n{input}"
    saved[name] = body
    vault.write_json(path, saved)
    return f"Saved template '{name}'. Use it with /t {name} <text>."


def delete_template(name: str) -> str:
    path = _templates_path()
    try:
        saved = vault.read_json(path) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    if name in saved:
        del saved[name]
        vault.write_json(path, saved)
        return f"Deleted '{name}'." + (" The built-in version is back." if name in BUILT_IN else "")
    if name in BUILT_IN:
        return f"'{name}' is built in and can be overwritten with /t save, but not deleted."
    return f"There is no template called '{name}'."


def expand(name: str, text: str) -> str | None:
    template = load_templates().get(name.strip().lower())
    if template is None:
        return None
    return template.replace("{input}", text.strip())


def describe_templates() -> str:
    templates = load_templates()
    lines = ["Prompt templates:"]
    for name, body in sorted(templates.items()):
        mark = "" if name in BUILT_IN else "  (yours)"
        first = body.replace("{input}", "…").split("\n")[0][:70]
        lines.append(f"  {name:<14} {first}{mark}")
    lines.append("")
    lines.append("/t <name> <text>  ·  /t save <name> <prompt with {input}>  ·  /t delete <name>")
    return "\n".join(lines)
