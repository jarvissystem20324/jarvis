"""Persistent memory — facts JARVIS keeps across restarts.

Stored as plain JSON next to the app so you can read, edit, or delete it with a
text editor. Nothing is uploaded anywhere; the file is only ever read to build
the context sent with your next message.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from jarvis.addons import Addon, Command

MAX_FACTS = 200
# Shorter than this and it is a heading or a stray word, not a fact.
MIN_FACT_CHARS = 12
# Only this many are sent as context, newest first, to keep prompts small.
CONTEXT_FACTS = 40


class Memory(Addon):
    name = "memory"
    version = "1.0"
    description = "Remembers facts about you between sessions."

    def commands(self):
        return [
            Command("remember", self.remember, "Store a fact", "/remember <fact>"),
            Command("forget", self.forget, "Delete a fact by number, or 'all'", "/forget <n|all>"),
            Command("memories", self.show, "List everything remembered", "/memories"),
            Command("import", self.import_file, "Load facts from a text file", "/import <file.txt>"),
        ]

    # --- storage ----------------------------------------------------------

    def _path(self, ctx):
        return ctx.store("memory.json")

    def _load(self, ctx) -> list[dict]:
        path = self._path(ctx)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt file shouldn't wedge the addon — start fresh but keep
            # the old one around so nothing is silently destroyed.
            try:
                path.rename(path.with_suffix(".json.broken"))
            except OSError:
                pass
            return []
        return data if isinstance(data, list) else []

    def _save(self, ctx, facts: list[dict]) -> None:
        self._path(ctx).write_text(
            json.dumps(facts[-MAX_FACTS:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- commands ---------------------------------------------------------

    def remember(self, ctx, args: str) -> str:
        fact = args.strip()
        if not fact:
            return "Usage: /remember <fact>\nExample: /remember I prefer metric units"

        facts = self._load(ctx)
        if any(f.get("text", "").lower() == fact.lower() for f in facts):
            return "I already have that one, sir."

        facts.append({"text": fact, "added": date.today().isoformat()})
        self._save(ctx, facts)
        return f"Noted. I'm now holding {len(facts)} fact{'s' if len(facts) != 1 else ''}."

    def forget(self, ctx, args: str) -> str:
        arg = args.strip().lower()
        facts = self._load(ctx)

        if arg == "all":
            if not facts:
                return "There was nothing to forget."
            self._save(ctx, [])
            return f"Forgotten all {len(facts)} of them."

        if not arg.isdigit():
            return "Usage: /forget <number>  or  /forget all\nUse /memories to see the numbers."

        index = int(arg)
        if not 1 <= index <= len(facts):
            return f"There's no fact {index}. I have {len(facts)}."

        removed = facts.pop(index - 1)
        self._save(ctx, facts)
        return f"Forgotten: {removed.get('text', '')}"

    def import_file(self, ctx, args: str) -> str:
        """Read a text file and keep each paragraph as a fact.

        Typing a page of notes at /remember one line at a time is the kind of
        chore that means it never gets done. Paragraphs, not lines, because a
        sentence split across two lines is still one fact.
        """
        raw = args.strip().strip('"').strip("'")
        if not raw:
            return (
                "Usage: /import <file.txt>\n"
                "Each blank-line-separated paragraph becomes one fact."
            )

        path = Path(raw).expanduser()
        if not path.exists():
            return f"No such file:\n  {path}"
        if not path.is_file():
            return f"That's a folder, not a file:\n  {path}"
        if path.suffix.lower() not in {".txt", ".md", ".text", ""}:
            return (
                f"I only read plain text ({path.suffix} isn't). Save it as .txt "
                "or .md and try again."
            )
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Couldn't read it: {exc}"

        chunks = [
            " ".join(part.split())
            for part in re.split(r"\n\s*\n", text)
            if part.strip()
        ]
        chunks = [c for c in chunks if len(c) >= MIN_FACT_CHARS]
        if not chunks:
            return (
                f"{path.name} had nothing substantial in it — I look for "
                f"paragraphs of at least {MIN_FACT_CHARS} characters."
            )

        facts = self._load(ctx)
        known = {f.get("text", "").lower() for f in facts}
        added = 0
        skipped = 0
        for chunk in chunks:
            if chunk.lower() in known:
                skipped += 1
                continue
            facts.append({"text": chunk, "added": date.today().isoformat(),
                          "source": path.name})
            known.add(chunk.lower())
            added += 1

        self._save(ctx, facts)
        note = f", {skipped} already known" if skipped else ""
        preview = "\n".join(f"  - {c[:90]}" for c in chunks[:4])
        more = f"\n  ... and {len(chunks) - 4} more" if len(chunks) > 4 else ""
        return (
            f"Read {path.name}: {added} new fact{'s' if added != 1 else ''}"
            f"{note}. I'm now holding {len(facts)}.\n\n{preview}{more}"
        )

    def show(self, ctx, args: str) -> str:
        facts = self._load(ctx)
        if not facts:
            return "I'm not holding anything about you yet. Use /remember <fact>."
        lines = [
            f"  {i}. {f.get('text', '')}  ({f.get('added', '?')})"
            for i, f in enumerate(facts, 1)
        ]
        return f"What I remember ({len(facts)}):\n" + "\n".join(lines)

    # --- conversation hook ------------------------------------------------

    def enrich_prompt(self, ctx, text: str) -> str | None:
        facts = self._load(ctx)
        if not facts:
            return None
        recent = facts[-CONTEXT_FACTS:]
        listed = "\n".join(f"- {f.get('text', '')}" for f in recent)
        return (
            "Things you know about the user (do not mention this list "
            f"unless relevant):\n{listed}"
        )


ADDON = Memory()
