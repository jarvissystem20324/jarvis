"""Proactive briefings (Bounty update): a few useful nudges a day, never more.

Every 15 minutes JARVIS looks at what it already knows — to-dos that are
overdue or due soon, today's reminders, whether you've focused today — and
picks at most one thing worth saying. The rules keep it from nagging:

  • at most three a day (JARVIS_NUDGES_PER_DAY), at least two hours apart;
  • never at night (22:00-08:00) or while focus mode is running;
  • the same nudge is never repeated on the same day.

Nothing is sent anywhere to decide: it is plain rules over your own data.
JARVIS_NUDGES=off turns it off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import kit
from .config import get_setting

STATE = kit.Store("nudges.json", {})
GAP_SECONDS = 2 * 3600
QUIET = (22, 8)


@dataclass
class Nudge:
    key: str
    title: str
    body: str
    page: str = ""
    weight: int = 1


def enabled() -> bool:
    return get_setting("JARVIS_NUDGES", "on").strip().lower() not in {"off", "0", "false", "no"}


def per_day() -> int:
    return kit.whole(get_setting("JARVIS_NUDGES_PER_DAY", "3"), 3, 1, 6)


def candidates(now: datetime, tasks: list[dict], focused_minutes: float) -> list[Nudge]:
    stamp = now.timestamp()
    out: list[Nudge] = []
    open_tasks = [t for t in tasks if not t.get("done")]
    overdue = [t for t in open_tasks if t.get("due") and t["due"] < stamp]
    soon = [t for t in open_tasks if t.get("due") and stamp <= t["due"] <= stamp + 3 * 3600]
    if overdue:
        first = overdue[0]["text"]
        more = f" and {len(overdue) - 1} more" if len(overdue) > 1 else ""
        out.append(Nudge(f"overdue:{len(overdue)}", "Overdue", f"“{first}”{more} — done, or move it?", "today", 3))
    if soon:
        when = datetime.fromtimestamp(soon[0]["due"])
        out.append(Nudge(f"soon:{soon[0]['text']}", "Due soon", f"“{soon[0]['text']}” is due at {when:%H:%M}.",
                         "today", 2))
    if now.weekday() < 5 and now.hour >= 15 and focused_minutes < 1 and open_tasks:
        out.append(Nudge("focus", "A focus block?", f"{len(open_tasks)} to-do(s) open and no focus yet today. "
                                                   "25 minutes now? /focus start", "today", 1))
    if now.hour >= 20 and open_tasks and not overdue:
        out.append(Nudge("plan", "Tomorrow", "Pick tomorrow's top three on Today before you stop?", "today", 1))
    return sorted(out, key=lambda n: -n.weight)


def pick(now: datetime | None = None, tasks: list[dict] | None = None, focused_minutes: float | None = None,
         focusing: bool = False) -> Nudge | None:
    """The one nudge worth showing now, or None. Records it as shown."""
    now = now or datetime.now()
    if not enabled() or focusing:
        return None
    if now.hour >= QUIET[0] or now.hour < QUIET[1]:
        return None
    state = STATE.load()
    today = now.date().isoformat()
    if state.get("day") != today:
        state = {"day": today, "shown": [], "last": 0}
    if len(state["shown"]) >= per_day() or now.timestamp() - state.get("last", 0) < GAP_SECONDS:
        return None
    if tasks is None:
        from .ten.work import load_tasks

        tasks = load_tasks()
    if focused_minutes is None:
        from . import focus

        focused_minutes = dict(focus.week()).get(today, {}).get("minutes", 0)
    for nudge in candidates(now, tasks, focused_minutes):
        if nudge.key not in state["shown"]:
            state["shown"].append(nudge.key)
            state["last"] = now.timestamp()
            STATE.save(state)
            return nudge
    return None


def register_watchers(jarvis, watchers) -> None:
    from . import alerts, focus

    def check():
        nudge = pick(focusing=focus.focus.running)
        if nudge is not None:
            alerts.post(f"💡 {nudge.title}", nudge.body, page=nudge.page)

    watchers.add("nudges", 900, check, first_after=120)
