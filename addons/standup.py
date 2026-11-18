"""Stand-up: yesterday, today and blockers, written from your own to-do list.

    /standup          a stand-up note ready to paste into a team chat

Built from what you ticked off since yesterday and what's still open on
Today — nothing is invented. The AI only tidies the wording.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from jarvis.addons import Addon, Command


class Standup(Addon):
    name = "standup"
    version = "1.0"
    description = "A daily stand-up note from your own to-do list."

    def commands(self):
        return [Command("standup", self.standup, "A stand-up note from your to-dos", "/standup")]

    def standup(self, ctx, args: str) -> str:
        from jarvis.ten.work import load_tasks

        tasks = load_tasks()
        since = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0).timestamp()
        done = [t["text"] for t in tasks if t.get("done") and t.get("finished", 0) >= since]
        open_ = [t for t in tasks if not t.get("done")]
        open_.sort(key=lambda t: (not t.get("due"), t.get("due") or 0))
        overdue = [t["text"] for t in open_ if t.get("due") and t["due"] < time.time()]
        today = [t["text"] for t in open_[:5]]
        if not done and not today:
            return "Nothing on your to-do list yet. Add some with /task, then /standup writes the note."
        facts = (f"Done since yesterday: {done or 'nothing recorded'}\n"
                 f"Planned today: {today or 'nothing planned'}\n"
                 f"Overdue (possible blockers): {overdue or 'none'}")
        note = ctx.ask("Write a short stand-up note with three headings: Yesterday, Today, Blockers. Use only these "
                       "facts, one bullet per item, no extra words, same language as the items.\n\n" + facts)
        return f"🗣 Stand-up — {datetime.now():%a %d %b}\n\n{note.strip()}"


ADDON = Standup()
