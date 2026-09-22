"""People JARVIS knows — the team, plus anyone you add.

Two separate stores, on purpose:

  * The built-in roster below ships with JARVIS. It is the team that built it,
    and it is the same on every install.
  * `data/people.json` is yours. Anyone you add with `/who add` goes there,
    never into the shipped file, so an update cannot overwrite your additions
    and your additions cannot leak into a release.

A profile is only sent to the model when that person actually comes up in the
conversation. Sending the whole roster with every message would waste context
and, on a free tier, real rate limit.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jarvis.addons import Addon, Command

# --- the team -------------------------------------------------------------
# Ships with the build, at the creator's request. Keep this factual and keep
# it short: it is public the moment a release goes out.

TEAM: tuple[dict[str, Any], ...] = (
    {
        "name": "Ahmed Zahid Dilmen",
        "aliases": ("ahmed", "zahid", "ahmed zahid", "creator", "my creator"),
        "role": "Creator of JARVIS. Tech legend.",
        "facts": (
            "Built JARVIS, and is the person I answer to.",
            "Competed in Teknofest.",
            "Assembles and repairs PCs.",
            "Knows a great deal about coding and robotics.",
        ),
    },
    {
        "name": "Ata Ibrahim",
        "aliases": ("ata", "ata ibrahim", "ibrahim"),
        "role": "Designer on the Teknofest team. Tech god.",
        "facts": (
            "The best designer on the team.",
            "The team's cable manager.",
            "Teaches tech to the others.",
            "Limited coding knowledge — a designer, not a programmer.",
        ),
    },
    {
        "name": "Amade Albayrak",
        "aliases": ("amade", "albayrak", "amade albayrak"),
        "role": "The team's second tech legend.",
        "facts": (
            "Knows nearly as much as Ahmed Zahid.",
            "Especially strong at robotics.",
            "His father is well known.",
        ),
    },
)

# The team's own ranking, so JARVIS uses the words the way they do.
RANKS = (
    "The team ranks itself, highest first: 'tech legend', then 'tech god'. "
    "Ahmed Zahid and Amade are tech legends; Ata is a tech god."
)

STORE = "people.json"


class People(Addon):
    name = "people"
    version = "1.0"
    description = "Knows the team, and anyone else you introduce."

    def commands(self):
        return [
            Command("who", self.who, "Look someone up", "/who <name>  |  /who add <name>: <facts>"),
            Command("people", self.roster, "Everyone I know", "/people"),
        ]

    # --- storage ----------------------------------------------------------

    def _custom(self, ctx) -> list[dict]:
        path = ctx.store(STORE)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("name")] \
            if isinstance(data, list) else []

    def _save_custom(self, ctx, people: list[dict]) -> None:
        ctx.store(STORE).write_text(
            json.dumps(people, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _all(self, ctx) -> list[dict]:
        """Shipped roster first, then yours. A name you add wins."""
        mine = self._custom(ctx)
        taken = {p["name"].lower() for p in mine}
        return [dict(p) for p in TEAM if p["name"].lower() not in taken] + mine

    # --- lookup -----------------------------------------------------------

    @staticmethod
    def _keys(person: dict) -> set[str]:
        keys = {person["name"].lower()}
        keys.update(a.lower() for a in person.get("aliases", ()))
        # First name alone, which is how anyone actually refers to a teammate.
        keys.add(person["name"].split()[0].lower())
        return keys

    def _find(self, ctx, needle: str) -> dict | None:
        needle = needle.strip().lower()
        if not needle:
            return None
        for person in self._all(ctx):
            if needle in self._keys(person):
                return person
        # Fall back to a partial match, so "dilmen" finds him too.
        for person in self._all(ctx):
            if any(needle in key for key in self._keys(person)):
                return person
        return None

    @staticmethod
    def _describe(person: dict) -> str:
        lines = [person["name"]]
        if person.get("role"):
            lines.append(f"  {person['role']}")
        for fact in person.get("facts", ()):
            lines.append(f"  - {fact}")
        return "\n".join(lines)

    # --- commands ---------------------------------------------------------

    def who(self, ctx, args: str) -> str:
        text = args.strip()
        if not text:
            return (
                "Usage: /who <name>\n"
                "       /who add <name>: <fact>; <fact>\n"
                "       /who forget <name>\n"
                "Use /people to see everyone I know."
            )

        if text.lower().startswith("add "):
            return self._add(ctx, text[4:])
        if text.lower().startswith("forget "):
            return self._forget(ctx, text[7:])

        person = self._find(ctx, text)
        if person is None:
            return (
                f"I don't know anyone called '{text}'.\n"
                f"Introduce them: /who add {text}: what they do; what they're good at"
            )
        return self._describe(person)

    def _add(self, ctx, rest: str) -> str:
        name, _, facts = rest.partition(":")
        name = name.strip()
        if not name:
            return "Usage: /who add <name>: <fact>; <fact>"
        entries = [f.strip() for f in facts.split(";") if f.strip()]
        if not entries:
            return f"Tell me something about {name}: /who add {name}: what they do"

        mine = self._custom(ctx)
        for person in mine:
            if person["name"].lower() == name.lower():
                known = list(person.get("facts", []))
                added = [e for e in entries if e.lower() not in {k.lower() for k in known}]
                person["facts"] = known + added
                self._save_custom(ctx, mine)
                if not added:
                    return f"I already knew all of that about {person['name']}."
                return (
                    f"Updated {person['name']} — {len(added)} new "
                    f"fact{'s' if len(added) != 1 else ''}.\n\n"
                    + self._describe(person)
                )

        person = {"name": name, "role": "", "facts": entries, "aliases": []}
        mine.append(person)
        self._save_custom(ctx, mine)
        return f"Noted, I know {name} now.\n\n" + self._describe(person)

    def _forget(self, ctx, rest: str) -> str:
        name = rest.strip()
        mine = self._custom(ctx)
        kept = [p for p in mine if p["name"].lower() != name.lower()]
        if len(kept) == len(mine):
            if self._find(ctx, name):
                return (
                    f"{name} is part of the built-in team roster, so there is "
                    "nothing of mine to forget."
                )
            return f"I don't know anyone called '{name}'."
        self._save_custom(ctx, kept)
        return f"Forgotten {name}."

    def roster(self, ctx, args: str) -> str:
        people = self._all(ctx)
        shipped = {p["name"] for p in TEAM}
        lines = []
        for person in people:
            mark = "" if person["name"] in shipped else "  (yours)"
            role = person.get("role") or f"{len(person.get('facts', []))} facts"
            lines.append(f"  {person['name']} — {role}{mark}")
        return (
            f"People I know ({len(people)}):\n" + "\n".join(lines)
            + "\n\n/who <name> for the detail."
        )

    # --- conversation hook ------------------------------------------------

    def enrich_prompt(self, ctx, text: str) -> str | None:
        """Only inject the people the message actually mentions."""
        words = set(re.findall(r"[\w']+", text.lower()))
        if not words:
            return None

        hits: list[dict] = []
        for person in self._all(ctx):
            keys = self._keys(person)
            # Multi-word keys need a substring test; single words must match a
            # whole word, so "ata" doesn't fire on "data".
            matched = any(
                (key in text.lower()) if " " in key else (key in words)
                for key in keys
            )
            if matched:
                hits.append(person)

        if not hits:
            return None
        blocks = [self._describe(p) for p in hits[:4]]
        return "People mentioned, for your reference:\n" + "\n\n".join(blocks) + f"\n\n{RANKS}"


ADDON = People()
