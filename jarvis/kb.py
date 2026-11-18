"""Memory 2.0 (Bounty update): one knowledge base over everything you've told
or shown JARVIS — your conversations, notes, pinned answers, the facts it
remembers, and the folder of documents you indexed with /docs — answered
with sources.

Search is the same offline BM25 the document library uses: nothing is sent
anywhere to find the passages. Only the handful that match a question go to
the AI, and if any of them come from your files you are asked first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import library, security, vault
from .config import get_data_dir


@dataclass
class Source:
    kind: str        # chat · note · pin · fact · file
    label: str       # what the user sees in the sources list
    text: str


def _when(stamp) -> str:
    try:
        return time.strftime("%d %b %Y", time.localtime(float(stamp)))
    except (TypeError, ValueError):
        return str(stamp or "")[:10]


def gather(include_files: bool = True) -> list[Source]:
    out: list[Source] = []
    try:
        from . import history

        for chat in history.list_chats()[:200]:
            messages, _mode, _code = history.load(chat["name"])
            when = str(chat.get("saved") or "")[:10]
            for i in range(0, len(messages) - 1, 2):
                question, answer = messages[i], messages[i + 1]
                if question.get("role") != "user":
                    continue
                text = f"Q: {question.get('content', '')}\nA: {answer.get('content', '')}"
                out.append(Source("chat", f"Chat “{chat['name']}”" + (f", {when}" if when else ""), text[:4000]))
    except Exception:
        pass
    try:
        from . import notes

        for note in notes.load_notes():
            title = note.get("title") or (note.get("text") or "")[:40]
            out.append(Source("note", f"Note “{title}”", f"{note.get('title', '')}\n{note.get('text', '')}"[:4000]))
        for pin in notes.load_pins():
            out.append(Source("pin", f"Pinned answer, {_when(pin.get('at') or pin.get('time'))}",
                              str(pin.get("text") or pin.get("answer") or "")[:4000]))
    except Exception:
        pass
    try:
        facts = vault.read_json(get_data_dir() / "memory.json")
        for fact in facts if isinstance(facts, list) else []:
            text = fact.get("fact") or fact.get("text") if isinstance(fact, dict) else str(fact)
            if text:
                out.append(Source("fact", "Something you told me to remember", str(text)))
    except Exception:
        pass
    if include_files:
        current = _library_root()
        data = library.load(current) if current else None
        for file, page, text in (data or {}).get("passages") or []:
            label = f"{file}" + (f", page {page}" if page else "")
            out.append(Source("file", label, text))
    return out


def _library_root():
    from pathlib import Path

    try:
        return Path((get_data_dir() / "library" / "current.txt").read_text(encoding="utf-8").strip())
    except OSError:
        return None


def search(question: str, limit: int = 8, sources: list[Source] | None = None) -> list[Source]:
    sources = sources if sources is not None else gather()
    data = {"passages": [[str(i), 0, s.text] for i, s in enumerate(sources)]}
    hits = library.search(data, question, limit=limit)
    return [sources[int(p.file)] for p in hits]


def answer(brain, question: str, sources: list[Source] | None = None) -> str:
    found = search(question, sources=sources)
    if not found:
        return ("🧠 I couldn't find anything about that in your chats, notes, pins, memory or indexed documents. "
                "Try other words.")
    files = sorted({s.label for s in found if s.kind == "file"})
    if files and not security.permissions.ask(security.READ_FILE, "passages from:\n" + "\n".join(
            f"  {f}" for f in files), context="/knowledge"):
        found = [s for s in found if s.kind != "file"]
        if not found:
            return "Denied. Nothing was sent."
    from . import shield

    numbered = "\n\n".join(f"[{i}] ({s.label})\n{shield.wrap(s.text, s.label)[0]}" for i, s in enumerate(found, 1))
    reply = brain.ask_once(
        f"{shield.RULE}\nAnswer the question using only these passages from the user's own chats, notes, saved "
        "facts and documents. Cite each claim with its number, like [2]. If they don't contain the answer, say so "
        f"plainly. Same language as the question.\n\nQuestion: {question}\n\n{numbered}")
    legend = "\n".join(f"  [{i}] {s.label}" for i, s in enumerate(found, 1))
    security.audit.record("knowledge", question[:120], f"{len(found)} passages")
    return f"🧠 {reply.strip()}\n\nSources:\n{legend}"


def counts() -> dict:
    sources = gather()
    out: dict[str, int] = {}
    for s in sources:
        out[s.kind] = out.get(s.kind, 0) + 1
    return out
