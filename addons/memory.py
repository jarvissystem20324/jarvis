"""Persistent memory — facts JARVIS keeps across restarts.

Stored as plain JSON next to the app so you can read, edit, or delete it with a
text editor. Nothing is uploaded anywhere; the file is only ever read to build
the context sent with your next message.
"""

from __future__ import annotations

import json
from datetime import date

from jarvis.addons import Addon, Command

MAX_FACTS = 200
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
