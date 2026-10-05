"""10.0 productivity: subtasks and repeating tasks on the to-do list, goals,
the end-of-day summary, meeting notes, email drafts in your own tone,
bookmarks, and a notebook with folders and [[linked notes]].

The to-do list is 8.0's (life.TODO); this adds fields to its items rather
than keeping a second list, so /mylist, the Today page and the Home widget
always agree. Everything is stored sealed through kit.Store.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import alerts, kit, reminders, security, shield
from ..registry import command, field, split

G = "Productivity"
GOALS = kit.Store("goals.json", [])
NOTEBOOK = kit.Store("notebook.json", [])
BOOKMARKS = kit.Store("bookmarks.json", [])
TONE = kit.Store("my_tone.json", {})
REPEATS = {"daily": 1, "weekdays": 1, "weekly": 7, "monthly": 30}
LINK = re.compile(r"\[\[([^\]\n]{1,80})\]\]")


# --- the to-do list, extended ------------------------------------------------------

def todo_store():
    from ..life import TODO

    return TODO


def load_tasks() -> list[dict]:
    return todo_store().load()


def save_tasks(items: list[dict]) -> None:
    todo_store().save(items)


def next_due(due: float, repeat: str, now: float | None = None) -> float:
    """When a repeating task comes back after it is ticked off."""
    now = time.time() if now is None else now
    base = datetime.fromtimestamp(due) if due else datetime.combine(date.today(), datetime.min.time()).replace(hour=9)
    step = timedelta(days=REPEATS.get(repeat, 1))
    nxt = base + step
    while nxt.timestamp() <= now:
        nxt += step
    if repeat == "weekdays":
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    if repeat == "monthly":
        month = base.month % 12 + 1
        year = base.year + (base.month == 12)
        day = min(base.day, 28)
        nxt = base.replace(year=year, month=month, day=day)
        while nxt.timestamp() <= now:
            month = nxt.month % 12 + 1
            year = nxt.year + (nxt.month == 12)
            nxt = nxt.replace(year=year, month=month)
    return nxt.timestamp()


def add_task(text: str, due: float = 0.0, repeat: str = "", priority: str = "") -> dict:
    items = load_tasks()
    item = {"text": text.strip(), "added": time.time(), "due": due or 0, "done": False}
    if repeat:
        item["repeat"] = repeat
    if priority:
        item["priority"] = priority
    items.append(item)
    save_tasks(items)
    if due and due > time.time():
        reminders.board.add("task", f"Task due: {item['text']}", due)
    return item


def finish_task(index: int) -> str:
    """Tick a task off; a repeating one comes back with its next date."""
    items = load_tasks()
    if not 0 <= index < len(items):
        return "No such task."
    item = items[index]
    item["done"] = True
    item["finished"] = time.time()
    note = f"✔ Done: {item['text']}"
    if item.get("repeat"):
        again = {k: v for k, v in item.items() if k not in {"done", "finished"}}
        again["done"] = False
        again["added"] = time.time()
        again["due"] = next_due(item.get("due") or 0, item["repeat"])
        again["subtasks"] = [{"text": s["text"], "done": False} for s in item.get("subtasks", [])]
        items.append(again)
        note += f" — back on {datetime.fromtimestamp(again['due']):%a %d %b}"
    save_tasks(items)
    return note


def find_task(items: list[dict], which: str) -> int | None:
    which = which.strip()
    open_items = [i for i, t in enumerate(items) if not t.get("done")]
    if which.isdigit():
        n = int(which)
        return open_items[n - 1] if 1 <= n <= len(open_items) else None
    low = which.lower()
    for i in open_items:
        if low and low in items[i]["text"].lower():
            return i
    return None


def toggle_subtask(index: int, sub: int) -> None:
    items = load_tasks()
    subs = items[index].setdefault("subtasks", [])
    if 0 <= sub < len(subs):
        subs[sub]["done"] = not subs[sub].get("done")
        save_tasks(items)


def progress(item: dict) -> float:
    subs = item.get("subtasks") or []
    if not subs:
        return 1.0 if item.get("done") else 0.0
    return sum(1 for s in subs if s.get("done")) / len(subs)


# --- goals -------------------------------------------------------------------------

def goal_line(i: int, goal: dict) -> str:
    target = goal.get("target") or 0
    done = goal.get("progress", 0)
    pct = min(100, round(100 * done / target)) if target else 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    by = f", by {goal['by']}" if goal.get("by") else ""
    return f"  {i}. {goal['title']}  {bar} {done:g}/{target:g} {goal.get('unit', '')}{by}".rstrip()


# --- the notebook ------------------------------------------------------------------

def notebook() -> list[dict]:
    return NOTEBOOK.load()


def save_note(note: dict) -> dict:
    notes = notebook()
    note = dict(note)
    note.setdefault("id", uuid.uuid4().hex[:12])
    note.setdefault("created", time.time())
    note["updated"] = time.time()
    note["title"] = (note.get("title") or "Untitled").strip()[:120]
    note.setdefault("folder", "Notes")
    note.setdefault("body", "")
    notes = [n for n in notes if n.get("id") != note["id"]] + [note]
    NOTEBOOK.save(notes)
    return note


def delete_note(note_id: str) -> None:
    NOTEBOOK.save([n for n in notebook() if n.get("id") != note_id])


def folders(notes: list[dict] | None = None) -> list[str]:
    notes = notebook() if notes is None else notes
    found = sorted({n.get("folder") or "Notes" for n in notes}, key=str.lower)
    return found or ["Notes"]


def links(body: str) -> list[str]:
    return [m.strip() for m in LINK.findall(body or "")]


def by_title(title: str, notes: list[dict] | None = None) -> dict | None:
    notes = notebook() if notes is None else notes
    low = title.strip().lower()
    return next((n for n in notes if n.get("title", "").lower() == low), None)


def backlinks(title: str, notes: list[dict] | None = None) -> list[dict]:
    notes = notebook() if notes is None else notes
    low = title.strip().lower()
    return [n for n in notes if any(link.lower() == low for link in links(n.get("body", "")))]


def search_notes(query: str, notes: list[dict] | None = None) -> list[dict]:
    notes = notebook() if notes is None else notes
    words = query.lower().split()
    if not words:
        return sorted(notes, key=lambda n: -n.get("updated", 0))
    hits = [n for n in notes if all(w in (n.get("title", "") + " " + n.get("body", "") + " " +
                                          n.get("folder", "")).lower() for w in words)]
    return sorted(hits, key=lambda n: (-(query.lower() in n.get("title", "").lower()), -n.get("updated", 0)))


# --- bookmarks ---------------------------------------------------------------------

def browser_bookmark_files() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    found = []
    for name, folder in (("Chrome", local / "Google" / "Chrome" / "User Data"),
                         ("Edge", local / "Microsoft" / "Edge" / "User Data"),
                         ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data")):
        if folder.is_dir():
            for profile in folder.glob("*/Bookmarks"):
                found.append((f"{name} ({profile.parent.name})", profile))
    return found


def parse_bookmarks(data: dict) -> list[dict]:
    out = []

    def walk(node, path):
        if node.get("type") == "url":
            out.append({"url": node.get("url", ""), "title": node.get("name", ""), "tags": path[-1:] if path else []})
        for child in node.get("children", []) or []:
            walk(child, path + ([node.get("name")] if node.get("type") == "folder" and node.get("name") else []))

    for root in (data.get("roots") or {}).values():
        if isinstance(root, dict):
            walk(root, [])
    return [b for b in out if b["url"].startswith(("http://", "https://"))]


def page_title(url: str) -> str:
    try:
        html = kit.get_text(url, limit=200_000)
    except Exception:
        return ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return ""
    import html as html_mod

    return re.sub(r"\s+", " ", html_mod.unescape(match.group(1))).strip()[:150]


# --- the end of the day -------------------------------------------------------------

def day_facts(day: date | None = None) -> dict:
    from ..life import CALENDAR

    day = day or date.today()
    start = datetime.combine(day, datetime.min.time()).timestamp()
    end = start + 86400
    tasks = load_tasks()
    done = [t["text"] for t in tasks if t.get("done") and start <= (t.get("finished") or 0) < end]
    open_ = [t["text"] for t in tasks if not t.get("done") and (t.get("due") or 0) and t["due"] < end]
    events = [e["title"] for e in CALENDAR.load() if start <= e.get("start", 0) < end]
    spent = 0.0
    try:
        from .. import spending

        for entry in spending.load():
            if start <= entry.get("at", 0) < end:
                spent += float(entry.get("amount", 0))
    except Exception:
        pass
    notes = [n["title"] for n in notebook() if start <= n.get("updated", 0) < end]
    goals = [g["title"] for g in GOALS.load() if any(start <= e.get("at", 0) < end for e in g.get("log", []))]
    return {"date": day.isoformat(), "done": done, "overdue": open_, "events": events, "spent": spent,
            "notes": notes, "goals": goals}


def day_text(facts: dict) -> str:
    lines = [f"🌙 Your day — {datetime.fromisoformat(facts['date']):%A %d %B}"]
    lines.append(f"✔ Done ({len(facts['done'])}): " + (", ".join(facts["done"]) or "nothing ticked off"))
    if facts["overdue"]:
        lines.append(f"⏳ Still open: {', '.join(facts['overdue'])}")
    if facts["events"]:
        lines.append(f"📅 Events: {', '.join(facts['events'])}")
    if facts["goals"]:
        lines.append(f"🎯 Goals moved: {', '.join(facts['goals'])}")
    if facts["notes"]:
        lines.append(f"🗒 Notes: {', '.join(facts['notes'])}")
    if facts["spent"]:
        lines.append(f"💸 Spent: {facts['spent']:.2f}")
    return "\n".join(lines)


def register_watchers(jarvis, watchers) -> None:
    """The end-of-day nudge, at JARVIS_EOD_AT (default off)."""
    from ..config import get_setting

    at = get_setting("JARVIS_EOD_AT", "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", at):
        return
    state = {"day": ""}

    def check():
        now = datetime.now()
        hour, minute = (int(x) for x in at.split(":"))
        if now.hour * 60 + now.minute >= hour * 60 + minute and state["day"] != now.date().isoformat():
            state["day"] = now.date().isoformat()
            facts = day_facts()
            alerts.post("Your day in one line", f"{len(facts['done'])} done, {len(facts['overdue'])} still open",
                        page="today")

    watchers.add("eod", 60, check)


class Work:
    @command("subtask", "subtasks", group=G, usage="/subtask <task n or words> | <step>",
             help="break a to-do into steps", title="Add a subtask", icon="🪜", page="today",
             fields=(field("task", "text", "Task (number or words)"), field("step", "text", "Step")))
    def subtask(self, args: str, routed: bool = False):
        which, step = split(args, 2)
        items = load_tasks()
        index = find_task(items, which)
        if index is None or not step:
            return "Usage: /subtask <task number or words> | <step>   (/mylist shows numbers)"
        items[index].setdefault("subtasks", []).append({"text": step, "done": False})
        save_tasks(items)
        subs = items[index]["subtasks"]
        return f"🪜 {items[index]['text']}: " + " · ".join(("☑ " if s["done"] else "☐ ") + s["text"] for s in subs)

    @command("recur", group=G, usage="/recur <task n or words> daily|weekdays|weekly|monthly|off",
             help="make a to-do come back after you tick it off", title="Repeating task", icon="🔁", page="today",
             fields=(field("task", "text", "Task (number or words)"),
                     field("every", "choice", "Repeats", "daily", ("daily", "weekdays", "weekly", "monthly", "off"))))
    def recur(self, args: str, routed: bool = False):
        text = args.replace("|", " ").strip()
        which, _, every = text.rpartition(" ")
        every = every.lower()
        if every not in set(REPEATS) | {"off"}:
            return "Usage: /recur <task> daily|weekdays|weekly|monthly|off"
        items = load_tasks()
        index = find_task(items, which)
        if index is None:
            return f"No open task '{which}'."
        if every == "off":
            items[index].pop("repeat", None)
        else:
            items[index]["repeat"] = every
        save_tasks(items)
        return f"🔁 {items[index]['text']} — " + ("no longer repeats." if every == "off" else f"repeats {every}.")

    @command("goal", "goals", group=G, usage="/goal add <title> | <target> [unit] [by 2026-12-31] · /goal <n> +1 · /goals",
             help="goals with progress bars", title="Goals", icon="🎯", page="today")
    def goal(self, args: str, routed: bool = False):
        text = args.strip()
        goals = GOALS.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() in {"add", "new"}:
            title, spec = split(rest, 2)
            m = re.match(r"\s*(\d+(?:\.\d+)?)\s*([^\d]*?)\s*(?:by\s+(\d{4}-\d{2}-\d{2}))?\s*$", spec or "")
            if not title or not m:
                return "Usage: /goal add Read 12 books | 12 books by 2026-12-31"
            goals.append({"title": title, "target": float(m.group(1)), "unit": m.group(2).strip(),
                          "by": m.group(3) or "", "progress": 0.0, "log": [], "created": time.time()})
            GOALS.save(goals)
            return f"🎯 New goal: {title} — 0/{float(m.group(1)):g} {m.group(2).strip()}"
        m = re.match(r"(\d+)\s*([+-]?\s*\d+(?:\.\d+)?|done|delete)$", text)
        if m:
            index = int(m.group(1)) - 1
            if not 0 <= index < len(goals):
                return "No such goal. /goals lists them."
            change = m.group(2).replace(" ", "")
            if change == "delete":
                gone = goals.pop(index)
                GOALS.save(goals)
                return f"Deleted the goal {gone['title']}."
            goal = goals[index]
            if change == "done":
                goal["progress"] = goal["target"]
            elif change[0] in "+-":
                goal["progress"] = max(0.0, goal.get("progress", 0) + float(change))
            else:
                goal["progress"] = float(change)
            goal.setdefault("log", []).append({"at": time.time(), "progress": goal["progress"]})
            GOALS.save(goals)
            cheer = " 🎉 Goal reached!" if goal["progress"] >= goal["target"] else ""
            return goal_line(index + 1, goal) + cheer
        if not goals:
            return "No goals yet. /goal add Read 12 books | 12 books by 2026-12-31"
        return "🎯 Goals:\n" + "\n".join(goal_line(i, g) for i, g in enumerate(goals, 1)) + "\n/goal <n> +1 to log progress"

    @command("eod", "endofday", "myday", group=G, usage="/eod [ai]", help="what you did today, in one look",
             title="End-of-day summary", icon="🌙", page="today",
             fields=(field("style", "choice", "Style", "plain", ("plain", "ai")),))
    def end_of_day(self, args: str, routed: bool = False):
        facts = day_facts()
        text = day_text(facts)
        if args.strip().lower() == "ai":
            reflection = self.brain.ask_once(
                "Here is someone's day as data. Write three short lines: what went well, what slipped, and one "
                f"suggestion for tomorrow. Warm, not cheesy.\n\n{json.dumps(facts, ensure_ascii=False)}")
            text += "\n\n" + reflection.strip()
        return text

    @command("meeting", "minutes", group=G, usage="/meeting <notes or transcript, or a file>",
             help="meeting notes: summary, decisions and action items", title="Meeting notes", icon="🧑\u200d🤝\u200d🧑",
             page="today", fields=(field("notes", "long", "Notes or transcript (or a file path)"),))
    def meeting(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower().startswith("add"):
            return self._meeting_actions_to_list()
        path = kit.path_arg(text)
        if path is not None and path.is_file():
            if not security.permissions.ask(security.READ_FILE, str(path), context="/meeting"):
                return "Denied. The file was not read."
            text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) < 30:
            return "Paste the meeting notes or transcript (or give a .txt file): /meeting <notes>"
        wrapped, warning = shield.wrap(text[:30000], "meeting notes")
        data = kit.ask_json(self.brain, (
            f"{shield.RULE}\n\nTurn these meeting notes into JSON: {{\"title\": str, \"summary\": [3-6 bullet strings], "
            "\"decisions\": [str], \"actions\": [{\"what\": str, \"who\": str, \"when\": str}], \"open_questions\": [str]}. "
            f"Use only what is in the notes; who/when empty if not said.\n\n{wrapped}"))
        if not isinstance(data, dict):
            return "I couldn't structure those notes — try again with a little more text."
        self._last_meeting = data
        lines = [f"🧑\u200d🤝\u200d🧑 {data.get('title') or 'Meeting'}", "", "Summary:"]
        lines += [f"  • {s}" for s in data.get("summary", [])]
        if data.get("decisions"):
            lines += ["", "Decisions:"] + [f"  ✔ {d}" for d in data["decisions"]]
        if data.get("actions"):
            lines += ["", "Action items:"]
            for a in data["actions"]:
                who = f" — {a.get('who')}" if a.get("who") else ""
                when = f" (by {a.get('when')})" if a.get("when") else ""
                lines.append(f"  ☐ {a.get('what')}{who}{when}")
        if data.get("open_questions"):
            lines += ["", "Open questions:"] + [f"  ? {q}" for q in data["open_questions"]]
        path = kit.output_dir() / f"meeting_{kit.slug(data.get('title') or 'notes')}_{kit.stamp()}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        lines += ["", f"Saved: {path}", "/meeting add — put the action items on your to-do list"]
        return "\n".join(lines) + (f"\n{warning}" if warning else "")

    def _meeting_actions_to_list(self) -> str:
        data = getattr(self, "_last_meeting", None)
        if not data or not data.get("actions"):
            return "No action items from a meeting yet. /meeting <notes> first."
        from ..life import parse_when

        added = 0
        for action in data["actions"]:
            due, _ = parse_when(action.get("when") or "") if action.get("when") else (None, "")
            add_task(action.get("what", "").strip(), due.timestamp() if due else 0)
            added += 1
        return f"Added {added} action item(s) to your to-do list."

    @command("mytone", group=G, usage="/mytone <paste one of your own emails> · /mytone · /mytone clear",
             help="teach JARVIS how you write, for drafts", title="My writing tone", icon="✒", page="inbox",
             fields=(field("sample", "long", "One of your own emails or messages"),))
    def my_tone(self, args: str, routed: bool = False):
        text = args.strip()
        data = TONE.load()
        samples = data.get("samples", [])
        if text.lower() in {"clear", "reset"}:
            TONE.save({})
            return "Forgot your writing samples."
        if not text:
            return (f"I have {len(samples)} sample(s) of your writing." if samples else
                    "No samples yet. Paste one of your own emails: /mytone <text>") + \
                (f"\nStyle notes: {data['notes']}" if data.get("notes") else "")
        samples = (samples + [text[:3000]])[-5:]
        notes = self.brain.ask_once(
            "Describe this person's writing style in 4 short bullet points (greeting, length, formality, sign-off, "
            "quirks) so another writer could imitate it.\n\n" + "\n\n---\n\n".join(samples))
        TONE.save({"samples": samples, "notes": notes.strip()})
        return f"✒ Got it — {len(samples)} sample(s). Your style:\n{notes.strip()}"

    @command("draft", group=G, usage="/draft <the email you got, or what to write>",
             help="an email draft in your own tone (never sent for you)", title="Email draft in my tone", icon="✉",
             page="inbox", fields=(field("about", "long", "The email you're replying to, or what to write"),
                                   field("goal", "text", "What you want to say", optional=True)))
    def draft(self, args: str, routed: bool = False):
        about, goal = split(args, 2)
        if not about:
            return "Usage: /draft <the email you got, or what to write> | <what you want to say>"
        tone = TONE.load()
        style = tone.get("notes") or "clear, friendly and brief"
        example = (tone.get("samples") or [""])[-1][:1200]
        wrapped, _ = shield.wrap(about[:8000], "the email")
        reply = self.brain.ask_once(
            f"{shield.RULE}\n\nWrite an email for me. My style: {style}\n"
            + (f"An example of how I write:\n{example}\n" if example else "")
            + (f"What I want to say: {goal}\n" if goal else "")
            + f"\nThe email or request:\n{wrapped}\n\nReturn only the email: a subject line starting 'Subject:', a blank "
              "line, then the body.")
        return "✉ Draft (copy it into your mail app — nothing is sent):\n\n" + reply.strip()

    @command("bookmark", "bookmarks", group=G, usage="/bookmark add <url> [tags] · /bookmarks [search] · /bookmark import",
             help="your bookmarks, searchable; imports from Chrome and Edge", title="Bookmarks", icon="🔖",
             page="notes", fields=(field("what", "text", "add <url> [tags] · search words · import", optional=True),))
    def bookmark(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        items = BOOKMARKS.load()
        if verb.lower() == "add":
            url, _, tags = rest.strip().partition(" ")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            if any(b["url"] == url for b in items):
                return "Already saved."
            title = page_title(url) or url
            items.append({"url": url, "title": title, "tags": tags.replace(",", " ").split(), "added": time.time()})
            BOOKMARKS.save(items)
            return f"🔖 Saved: {title}"
        if verb.lower() == "import":
            files = browser_bookmark_files()
            if not files:
                return "No Chrome, Edge or Brave bookmarks found on this PC."
            known = {b["url"] for b in items}
            added = 0
            for _name, path in files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for b in parse_bookmarks(data):
                    if b["url"] not in known:
                        b["added"] = time.time()
                        items.append(b)
                        known.add(b["url"])
                        added += 1
            BOOKMARKS.save(items)
            return f"🔖 Imported {added} bookmark(s) from {', '.join(n for n, _ in files)}."
        if verb.lower() in {"delete", "remove"} and rest.strip().isdigit():
            index = int(rest) - 1
            if 0 <= index < len(items):
                gone = items.pop(index)
                BOOKMARKS.save(items)
                return f"Deleted {gone['title']}."
            return "No such bookmark."
        words = text.lower().split()
        hits = [(i, b) for i, b in enumerate(items, 1)
                if all(w in f"{b['title']} {b['url']} {' '.join(b.get('tags', []))}".lower() for w in words)]
        if not hits:
            return "No bookmarks yet. /bookmark add <url> or /bookmark import" if not items else "Nothing matches."
        return "🔖 Bookmarks:\n" + "\n".join(f"  {i}. {b['title'][:70]} — {b['url']}" for i, b in hits[:40])

    @command("notebook", "nb", group=G, usage="/nb add <folder> | <title> | <text> · /nb <search>",
             help="a notebook with folders and [[linked notes]]", title="Notebook", icon="📓", page="notes",
             fields=(field("folder", "text", "Folder", "Notes"), field("title", "text", "Title"),
                     field("body", "long", "Text — [[Another note]] links to it")),
             template="add {folder} | {title} | {body}")
    def notebook_command(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            folder, title, body = split(rest, 3)
            if not title:
                return "Usage: /nb add <folder> | <title> | <text>"
            note = save_note({"folder": folder or "Notes", "title": title, "body": body})
            return f"📓 Saved “{note['title']}” in {note['folder']}." + (
                f" Links: {', '.join(links(body))}" if links(body) else "")
        hits = search_notes(text)
        if not hits:
            return "No notes yet." if not text else "No notes match."
        return "📓 Notes:\n" + "\n".join(f"  [{n.get('folder')}] {n['title']} — {n.get('body', '')[:60]}"
                                         for n in hits[:30])
