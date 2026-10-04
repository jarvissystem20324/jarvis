"""Commands added from 8.0 on register themselves here.

Before 8.0 each group of commands had its own dispatch table (everyday.py,
extras.py, toolkit.py). With ninety-odd more that stops scaling, so a method
is now marked with @command and found by name:

    @command("task", "tasks", group="Everyday", usage="/task <thing> [friday]",
             help="a to-do list; due dates become reminders")
    def tasks(self, args, routed=False): ...

Every registered method takes (args, routed). `routed` is True when a plain
sentence was turned into the command and the method may return None to hand
the sentence back to the AI.

10.0: a command can also describe its own form, so the window can offer it as
fields and buttons instead of something to remember and type:

    @command("kdv", group="Türkiye", usage="/kdv <amount> [rate]", help="KDV ekle / çıkar",
             title="KDV hesaplama", icon="🧾", page="turkey",
             fields=(field("amount", "number", "Tutar"), field("rate", "choice", "Oran", "20", ("20", "10", "1"))))

The values are joined with spaces, or with " | " when any of them may hold
spaces (`template` overrides both), so the same command works typed in the
chat, spoken, from the MCP server, and from its form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as _dc_field

COMMANDS: dict[str, str] = {}
HELP: list[tuple[str, str, str]] = []      # (group, usage, what it does)
GROUPS = ("Make and write", "Design", "Documents", "Study", "Everyday", "Live info", "PC and files",
          "Security", "Coding", "Automation", "Media", "Music and games", "Health and money",
          "Travel", "Türkiye", "Phone", "Productivity", "Voice, connections and fun", "Chat and AI")

# Field kinds a form knows how to draw.
KINDS = ("text", "long", "number", "choice", "file", "files", "folder", "date", "time", "color", "bool")


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "text"
    label: str = ""
    default: str = ""
    options: tuple = ()
    optional: bool = False
    hint: str = ""
    # File dialogs: ("Pictures", "*.png *.jpg") pairs.
    types: tuple = ()


def field(name: str, kind: str = "text", label: str = "", default: str = "", options: tuple = (),
          optional: bool = False, hint: str = "", types: tuple = ()) -> Field:
    if kind not in KINDS:
        raise ValueError(f"unknown field kind {kind!r}")
    return Field(name, kind, label or name.replace("_", " ").capitalize(), str(default), tuple(options),
                 optional, hint, tuple(types))


@dataclass
class Tool:
    """One command as the window shows it."""

    name: str
    names: tuple = ()
    group: str = ""
    usage: str = ""
    help: str = ""
    title: str = ""
    icon: str = "•"
    page: str = ""
    fields: tuple = ()
    template: str = ""
    # Runs in the chat rather than a form: it asks follow-up questions
    # (a quiz, twenty questions) or needs a hidden box for a secret.
    chat: bool = False
    keywords: str = ""
    method: str = ""
    extra: dict = _dc_field(default_factory=dict)

    def label(self) -> str:
        return self.title or self.name.capitalize()

    def build(self, values: dict[str, str]) -> str:
        """The command text for these form values."""
        vals = {f.name: str(values.get(f.name, "")).strip() for f in self.fields}
        if self.template:
            text = re.sub(r"[ \t]+", " ", self.template.format(**vals)).strip()
            text = re.sub(r"(\s*\|\s*)+$", "", text)
            return f"/{self.name} {text}".rstrip()
        parts = [vals[f.name] for f in self.fields]
        spaced = len(self.fields) > 1 and any(f.kind in {"text", "long", "file", "files", "folder"}
                                               for f in self.fields)
        if spaced:
            while parts and not parts[-1]:
                parts.pop()
            return f"/{self.name} {' | '.join(parts)}".rstrip()
        return f"/{self.name} {' '.join(p for p in parts if p)}".rstrip()


TOOLS: dict[str, Tool] = {}


def command(*names: str, group: str = "", usage: str = "", help: str = "", title: str = "", icon: str = "",
            page: str = "", fields: tuple = (), template: str = "", chat: bool = False, keywords: str = ""):
    def wrap(fn):
        for name in names:
            if name in COMMANDS and COMMANDS[name] != fn.__name__:
                raise RuntimeError(f"/{name} is registered twice ({COMMANDS[name]} and {fn.__name__})")
            COMMANDS[name] = fn.__name__
        if help:
            HELP.append((group, usage or f"/{names[0]}", help))
        if names[0] not in TOOLS or TOOLS[names[0]].method == fn.__name__:
            TOOLS[names[0]] = Tool(
                name=names[0], names=tuple(names), group=group, usage=usage or f"/{names[0]}", help=help,
                title=title, icon=icon or "•", page=page, fields=tuple(fields), template=template, chat=chat,
                keywords=keywords, method=fn.__name__,
            )
        return fn
    return wrap


def split(args: str, count: int) -> list[str]:
    """Split form-built arguments: " | " first, then whitespace for the rest.

    `count` is how many values the command expects; the last one keeps any
    spaces it has. Always returns exactly `count` strings.
    """
    text = (args or "").strip()
    if count <= 1:
        return [text]
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
        if len(parts) > count:
            parts = parts[:count - 1] + [" | ".join(parts[count - 1:])]
    else:
        parts = text.split(None, count - 1)
    parts = [p.strip() for p in parts]
    return parts + [""] * (count - len(parts))


def help_text() -> str:
    lines: list[str] = []
    for group in GROUPS:
        rows = [(u, h) for g, u, h in HELP if g == group]
        if not rows:
            continue
        lines += ["", group]
        width = min(max(len(u) for u, _ in rows), 38)
        lines += [f"  {u:<{width}}  {h}" for u, h in rows]
    return "\n".join(lines)
