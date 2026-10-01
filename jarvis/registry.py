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
"""

from __future__ import annotations

COMMANDS: dict[str, str] = {}
HELP: list[tuple[str, str, str]] = []      # (group, usage, what it does)
GROUPS = ("Make and write", "Study", "Everyday", "Live info", "PC and files", "Security",
          "Coding", "Voice, connections and fun")


def command(*names: str, group: str = "", usage: str = "", help: str = ""):
    def wrap(fn):
        for name in names:
            if name in COMMANDS and COMMANDS[name] != fn.__name__:
                raise RuntimeError(f"/{name} is registered twice ({COMMANDS[name]} and {fn.__name__})")
            COMMANDS[name] = fn.__name__
        if help:
            HELP.append((group, usage or f"/{names[0]}", help))
        return fn
    return wrap


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
