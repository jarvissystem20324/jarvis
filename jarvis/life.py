"""8.0 — Everyday: a to-do list, repeating and medicine reminders, recipes,
meal and workout plans, a sleep calculator, bill splitting, loans, packing
lists, gift ideas, dice and a local calendar that exports .ics.

Anything with a right answer (sleep cycles, a split bill, a loan payment, the
date "next friday" means) is worked out here; the model only writes the
things that are matters of taste.
"""

from __future__ import annotations

import random
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import kit, reminders, security, writer
from .registry import command

G = "Everyday"
TODO = kit.Store("todo.json", [])
CALENDAR = kit.Store("calendar.json", [])
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
            "pazartesi": 0, "salı": 1, "çarşamba": 2, "perşembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6}


def parse_when(text: str, now: datetime | None = None, default_hour: int = 9) -> tuple[datetime | None, str]:
    """Find a moment at the end of `text`: 'friday', 'next monday 14:00', 'tomorrow at 9',
    'on 12/10', 'in 3 days', 'at 5pm'. Returns (moment or None, the text without it)."""
    now = now or datetime.now()
    patterns = [
        r"(?:\s+(?:by|on|due|until|at|için))?\s+(?:next\s+)?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) +
        r")(?:\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\s*$",
        r"(?:\s+(?:by|on|due))?\s+(today|tonight|tomorrow|yarın|bugün)(?:\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\s*$",
        r"(?:\s+(?:by|on|due))?\s+(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)(?:\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\s*$",
        r"\s+in\s+(\d+)\s+(days?|weeks?|hours?|minutes?|mins?)\s*$",
        r"\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*$",
    ]
    for index, pattern in enumerate(patterns):
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        rest = text[:m.start()].strip(" ,")
        clock = None
        if index == 3:
            amount, unit = int(m.group(1)), m.group(2).lower()
            delta = {"d": timedelta(days=amount), "w": timedelta(weeks=amount), "h": timedelta(hours=amount),
                     "m": timedelta(minutes=amount)}[unit[0]]
            return now + delta, rest
        if index == 4:
            clock = m.group(1)
            day = now.date()
        else:
            word = m.group(1).lower()
            clock = m.group(2)
            if word in WEEKDAYS:
                ahead = (WEEKDAYS[word] - now.weekday()) % 7 or 7
                day = now.date() + timedelta(days=ahead)
            elif word in {"today", "bugün", "tonight"}:
                day = now.date()
                clock = clock or ("20:00" if word == "tonight" else None)
            elif word in {"tomorrow", "yarın"}:
                day = now.date() + timedelta(days=1)
            elif "-" in word:
                day = date.fromisoformat(word)
            else:
                parts = [int(p) for p in re.split(r"[./]", word)]
                year = parts[2] if len(parts) > 2 else now.year
                year += 2000 if year < 100 else 0
                day = date(year, parts[1], parts[0])     # day.month, as written in Turkey and Europe
                if len(parts) == 2 and day < now.date():
                    day = date(year + 1, parts[1], parts[0])
        hour, minute = default_hour, 0
        if clock:
            cm = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", clock.strip(), re.I)
            hour, minute = int(cm.group(1)), int(cm.group(2) or 0)
            if (cm.group(3) or "").lower() == "pm" and hour < 12:
                hour += 12
            if (cm.group(3) or "").lower() == "am" and hour == 12:
                hour = 0
        moment = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
        if index == 4 and moment <= now:
            moment += timedelta(days=1)
        return moment, rest
    return None, text.strip()


def parse_repeat(text: str, now: datetime | None = None) -> tuple[str, datetime, str, float] | None:
    """'every monday at 9 to call mum' -> (repeat, first moment, what, until)."""
    now = now or datetime.now()
    body = re.sub(r"^every\s+", "", text.strip(), flags=re.I)
    until = 0.0
    m = re.search(r"\s+for\s+(\d+)\s+(days?|weeks?)\b", body, re.I)
    if m:
        days = int(m.group(1)) * (7 if m.group(2).lower().startswith("w") else 1)
        until = (now + timedelta(days=days)).timestamp()
        body = (body[:m.start()] + body[m.end():]).strip()
    what_m = re.search(r"\s+(?:to|that|about)\s+(.+)$", body, re.I)
    what = what_m.group(1).strip() if what_m else ""
    when = body[:what_m.start()].strip() if what_m else body
    clock_m = re.search(r"(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*$", when, re.I)
    clock = clock_m.group(1) if clock_m else None
    head = when[:clock_m.start()].strip() if clock_m else when.strip()

    def at(day: date) -> datetime:
        hour, minute = 9, 0
        if clock:
            cm = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", clock, re.I)
            hour, minute = int(cm.group(1)) % 24, int(cm.group(2) or 0)
            if (cm.group(3) or "").lower() == "pm" and hour < 12:
                hour += 12
        return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)

    interval = re.fullmatch(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)", head, re.I)
    if interval:
        seconds = int(interval.group(1)) * (3600 if interval.group(2).lower().startswith("h") else 60)
        return f"every:{seconds}", now + timedelta(seconds=seconds), what, until
    head = head.lower()
    if head in {"hour", "hourly"}:
        return "every:3600", now + timedelta(hours=1), what, until
    if head in {"day", "daily", "morning", "evening", "night", "gün", "her gün"} or not head:
        first = at(now.date())
        if not clock:
            first = first.replace(hour={"morning": 8, "evening": 19, "night": 22}.get(head, 9))
        return "daily", first if first > now else first + timedelta(days=1), what, until
    if head in {"weekday", "weekdays", "workday", "workdays"}:
        first = at(now.date())
        while first <= now or first.weekday() >= 5:
            first += timedelta(days=1)
        return "weekdays", first, what, until
    if head in {"month", "monthly"}:
        first = at(now.date())
        return "monthly", first if first > now else first + timedelta(days=30), what, until
    if head in {"week", "weekly"}:
        first = at(now.date())
        return "weekly", first if first > now else first + timedelta(days=7), what, until
    if head in WEEKDAYS:
        first = at(now.date() + timedelta(days=(WEEKDAYS[head] - now.weekday()) % 7))
        return "weekly", first if first > now else first + timedelta(days=7), what, until
    return None


def sleep_times(wake: datetime | None = None, now: datetime | None = None, fall_asleep: int = 15) -> list[datetime]:
    """Bedtimes for a wake-up time, or wake times for going to bed now (90-minute cycles)."""
    now = now or datetime.now()
    if wake is None:
        start = now + timedelta(minutes=fall_asleep)
        return [start + timedelta(minutes=90 * n) for n in (6, 5, 4, 3)]
    return [wake - timedelta(minutes=90 * n + fall_asleep) for n in (6, 5, 4, 3)]


def split_bill(text: str) -> str:
    """'450 3 tip 10%' or 'ali 120, ayşe 80, shared 150'."""
    tip_m = re.search(r"(?:tip|bahşiş|service)\s*(\d+(?:[.,]\d+)?)\s*%?", text, re.I)
    tip = float(tip_m.group(1).replace(",", ".")) if tip_m else 0.0
    body = (text[:tip_m.start()] + text[tip_m.end():]) if tip_m else text
    named = re.findall(r"([^\d,;]+?)\s+(\d+(?:[.,]\d+)?)", body)
    named = [(n.strip().strip(":").strip(), float(v.replace(",", "."))) for n, v in named if n.strip(" :")]
    if len(named) >= 2:
        shared = sum(v for n, v in named if n.lower() in {"shared", "ortak", "together", "everyone"})
        people = [(n, v) for n, v in named if n.lower() not in {"shared", "ortak", "together", "everyone"}]
        share = shared / len(people) if people else 0
        total = 0.0
        lines = []
        for name, value in people:
            owed = (value + share) * (1 + tip / 100)
            total += owed
            lines.append(f"  {name}: {owed:,.2f}")
        return "\n".join(["Each pays" + (f" (with {tip:g}% tip)" if tip else "") + ":"] + lines + [f"  total {total:,.2f}"])
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", body)]
    if len(numbers) < 2 or numbers[1] < 1:
        raise ValueError("Usage: /split <total> <people> [tip 10%]  or  /split ali 120, ayşe 80, shared 150")
    total, people = numbers[0], int(numbers[1])
    with_tip = total * (1 + tip / 100)
    each = with_tip / people
    rounded = -(-each // 1)
    return (f"{with_tip:,.2f} split {people} ways = {each:,.2f} each" + (f" (incl. {tip:g}% tip)" if tip else "") +
            f".\nRounded up: {rounded:,.0f} each ({rounded * people - with_tip:,.2f} extra).")


def loan(amount: float, rate_percent: float, months: int, monthly_rate: bool = False) -> tuple[float, float, float]:
    """(monthly payment, total paid, total interest) for an annuity loan."""
    r = rate_percent / 100 if monthly_rate else rate_percent / 100 / 12
    payment = amount / months if r == 0 else amount * r / (1 - (1 + r) ** -months)
    return payment, payment * months, payment * months - amount


def ics(events: list[dict]) -> str:
    def fmt(epoch: float) -> str:
        return datetime.fromtimestamp(epoch).strftime("%Y%m%dT%H%M%S")

    def esc(text: str) -> str:
        return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//Calendar//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e.get('uid') or uuid.uuid4()}@jarvis", f"DTSTAMP:{fmt(time.time())}",
                  f"DTSTART:{fmt(e['start'])}", f"DTEND:{fmt(e.get('end') or e['start'] + 3600)}",
                  f"SUMMARY:{esc(e['title'])}"]
        if e.get("where"):
            lines.append(f"LOCATION:{esc(e['where'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_ics(text: str) -> list[dict]:
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    events = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.S):
        fields = {}
        for line in block.strip().splitlines():
            key, _, value = line.partition(":")
            fields[key.split(";")[0].upper()] = value.strip()

        def moment(raw: str) -> float | None:
            raw = raw.rstrip("Z")
            for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
                try:
                    return datetime.strptime(raw, fmt).timestamp()
                except ValueError:
                    continue
            return None

        start = moment(fields.get("DTSTART", ""))
        if start is None:
            continue
        events.append({"title": fields.get("SUMMARY", "Event").replace("\\,", ",").replace("\\;", ";"),
                       "start": start, "end": moment(fields.get("DTEND", "")) or start + 3600,
                       "where": fields.get("LOCATION", ""), "uid": fields.get("UID", "").split("@")[0]})
    return events


class Life:
    # --- to-do list -----------------------------------------------------------------------

    @command("mylist", "todolist", "checklist", group=G, usage="/mylist add <thing> [friday 14:00] · /mylist · /done <n>",
             help="a to-do list; a due date also sets a reminder")
    def tasks(self, args: str, routed: bool = False):
        text = args.strip()
        items = TODO.load()
        verb, _, rest = text.partition(" ")
        verb = verb.lower()
        if not text or verb in {"list", "show", "all"}:
            return _describe_tasks(items, show_done=verb == "all")
        if verb in {"done", "finish", "complete", "check"}:
            return self.done(rest)
        if verb in {"delete", "remove", "del"}:
            index = _find_task(items, rest)
            if index is None:
                return f"No item '{rest}'. /mylist shows them."
            removed = items.pop(index)
            TODO.save(items)
            return f"Deleted: {removed['text']}"
        if verb == "add":
            text = rest.strip()
        elif verb == "clear":
            kept = [t for t in items if not t.get("done")]
            TODO.save(kept)
            return f"Cleared {len(items) - len(kept)} finished task(s)."
        due, what = parse_when(text)
        if not what:
            return "What should I add? /mylist add <thing> [when]"
        item = {"text": what, "added": time.time(), "due": due.timestamp() if due else 0, "done": False}
        items.append(item)
        TODO.save(items)
        when = ""
        if due:
            reminders.board.add("task", f"Task due: {what}", due.timestamp())
            when = f", due {due:%a %d %b %H:%M} (I'll remind you)"
        return f"✅ Added: {what}{when}. {sum(1 for t in items if not t.get('done'))} open · /mylist"

    @command("done", group=G)
    def done(self, args: str, routed: bool = False):
        items = TODO.load()
        index = _find_task(items, args)
        if index is None:
            return "Which one? /done <number or words>   (/mylist shows numbers)"
        items[index]["done"] = True
        items[index]["finished"] = time.time()
        TODO.save(items)
        left = sum(1 for t in items if not t.get("done"))
        return f"✔ Done: {items[index]['text']}. {left} left" + (" — all clear! 🎉" if not left else ".")

    # --- reminders that repeat ---------------------------------------------------------------

    @command("every", "repeat", group=G, usage="/every monday at 9 to call mum",
             help="repeating reminders (every day / weekday / monday / 2 hours)")
    def every(self, args: str, routed: bool = False):
        parsed = parse_repeat(args)
        if parsed is None or not parsed[2]:
            return ("Usage: /every <when> to <what>\n  /every day at 8 to take vitamins     /every weekday at 9:30 to stand-up\n"
                    "  /every monday at 18 to call mum      /every 2 hours to drink water\n"
                    "  /every day at 21 to stretch for 30 days")
        repeat, first, what, until = parsed
        item = reminders.board.add("reminder", what, first.timestamp(), repeat=repeat, until=until)
        tail = f" until {datetime.fromtimestamp(until):%d %b}" if until else ""
        return f"🔁 {what} — {reminders.describe_repeat(repeat)}{tail}, next {item.when()}. /reminders lists them, /remind cancel {item.id} stops it."

    @command("meds", "medicine", "ilac", group=G, usage="/meds add <name> at 9:00 [and 21:00] [for 7 days] · /meds",
             help="medicine reminders, every day or every N hours")
    def meds(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        mine = [r for r in reminders.board.items if r.kind == "meds"]
        if not text or verb.lower() in {"list", "show"}:
            if not mine:
                return "No medicine reminders. /meds add vitamin D at 9:00   ·   /meds add antibiotic every 8 hours for 7 days"
            return "💊 Medicine reminders:\n" + "\n".join(r.line() for r in mine) + "\n/meds stop <name> removes one."
        if verb.lower() in {"stop", "remove", "delete", "cancel"}:
            gone = [r for r in mine if rest.strip().lower() in r.text.lower()]
            for r in gone:
                reminders.board.cancel(str(r.id))
            return f"Stopped {len(gone)} reminder(s) for {rest.strip()}." if gone else f"No medicine called '{rest.strip()}'."
        if verb.lower() in {"add", "new"}:
            text = rest
        until = 0.0
        m = re.search(r"\s+for\s+(\d+)\s+(days?|weeks?)\b", text, re.I)
        if m:
            until = time.time() + int(m.group(1)) * 86400 * (7 if m.group(2).startswith("w") else 1)
            text = (text[:m.start()] + text[m.end():]).strip()
        interval = re.search(r"\s+every\s+(\d+)\s*(?:hours?|h|saat)\b", text, re.I)
        if interval:
            name = text[:interval.start()].strip()
            hours = int(interval.group(1))
            item = reminders.board.add("meds", f"Time for {name}", time.time() + hours * 3600, repeat=f"every:{hours * 3600}", until=until)
            return f"💊 {name} every {hours} hours, next {item.when()}" + (f", for {m.group(1)} {m.group(2)}" if m else "") + "."
        times = re.findall(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text, re.I)
        name = re.split(r"\s+(?:at|@|saat)\s+", text, maxsplit=1, flags=re.I)[0].strip()
        if not times or not name:
            return "Usage: /meds add <name> at 9:00 [and 21:00] [for 7 days]   or   /meds add <name> every 8 hours"
        booked = []
        for clock in times[:6]:
            parsed = parse_repeat(f"day at {clock} to Time for {name}")
            item = reminders.board.add("meds", f"Time for {name}", parsed[1].timestamp(), repeat="daily", until=until)
            booked.append(f"{parsed[1]:%H:%M}")
        return f"💊 {name} every day at {', '.join(booked)}" + (f" for {m.group(1)} {m.group(2)}" if m else "") + "."

    # --- food, fitness, sleep ---------------------------------------------------------------------

    @command("fridge", "recipe", "recipes", group=G, usage="/fridge <what you have>",
             help="recipes from what's in your fridge")
    def fridge(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /fridge eggs, tomatoes, cheese, bread, onion"
        return self.brain.ask_once(f"""I have: {args.strip()}. Suggest 3 recipes that use mostly these (assume salt,
pepper, oil and water). For each: a name, time and difficulty, what I'd still need (if anything), and short
numbered steps. Prefer quick, tasty home cooking. Same language as my message.""")

    @command("mealplan", group=G, usage="/mealplan [7 days] [vegetarian, 2000 kcal, budget]",
             help="a weekly meal plan and shopping list (Word)")
    def meal_plan(self, args: str, routed: bool = False):
        return self._document(f"""{writer.PROMPT}
Make a meal plan: {args.strip() or '7 days, balanced, simple home cooking'}.
A table per day (Breakfast | Lunch | Dinner | Snack) with rough calories, then one combined shopping list grouped
by aisle, then prep-ahead tips. Title '# Meal plan'. Same language as the request.""", ("docx",))

    @command("workout", group=G, usage="/workout <goal, days a week, equipment>",
             help="a workout plan (Word), with optional reminders")
    def workout(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /workout <goal, days a week, equipment, level>   e.g. /workout build muscle, 3 days, dumbbells only, beginner"
        return self._document(f"""{writer.PROMPT}
Make a safe, progressive workout plan for: {args.strip()}.
Include a weekly schedule table, each session's exercises (sets × reps, rest), warm-up and cool-down, how to
progress over 6 weeks, and form tips. Remind to consult a doctor if they have health conditions.
Title '# Workout plan'. Same language as the request.""", ("docx",))

    @command("sleepcalc", "bedtime", group=G, usage="/sleepcalc [wake 7:00]",
             help="best times to sleep or wake, in 90-minute cycles")
    def sleep_calc(self, args: str, routed: bool = False):
        text = args.strip().lower()
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if m and not re.search(r"\bnow\b", text):
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3) == "pm" and hour < 12:
                hour += 12
            wake = datetime.now().replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
            if wake <= datetime.now():
                wake += timedelta(days=1)
            times = sleep_times(wake)
            return (f"😴 To wake at {wake:%H:%M} refreshed, go to bed at: " + ", ".join(f"{t:%H:%M}" for t in times) +
                    "\n(9h, 7.5h, 6h or 4.5h of sleep — whole 90-minute cycles, plus 15 minutes to fall asleep.)")
        times = sleep_times()
        return ("😴 If you go to bed now, wake up at: " + ", ".join(f"{t:%H:%M}" for t in times) +
                "\n(6, 5, 4 or 3 full cycles. Set one with: alarm " + f"{times[1]:%H:%M})")

    # --- money ----------------------------------------------------------------------------------------

    @command("split", group=G, usage="/split 450 3 [tip 10%] · /split ali 120, ayşe 80, shared 150",
             help="split a bill, evenly or by what each had")
    def split(self, args: str, routed: bool = False):
        try:
            return "💳 " + split_bill(args)
        except ValueError as exc:
            return str(exc)

    @command("loan", "kredi", group=G, usage="/loan 500000 3.2% monthly 36 months",
             help="loan payments and total interest")
    def loan_calc(self, args: str, routed: bool = False):
        text = args.lower().replace(",", "")
        numbers = re.findall(r"\d+(?:\.\d+)?", text)
        months_m = re.search(r"(\d+)\s*(months?|mo|ay)\b", text)
        years_m = re.search(r"(\d+)\s*(years?|yrs?|yıl)\b", text)
        rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if len(numbers) < 3 or not rate_m or not (months_m or years_m):
            return "Usage: /loan <amount> <rate>% [monthly|yearly] <N months|years>   e.g. /loan 500000 3.2% monthly 36 months"
        amount = float(numbers[0])
        months = int(months_m.group(1)) if months_m else int(years_m.group(1)) * 12
        monthly = bool(re.search(r"\b(monthly|aylık|per month|a month)\b", text))
        payment, total, interest = loan(amount, float(rate_m.group(1)), months, monthly)
        return (f"🏦 {amount:,.0f} over {months} months at {rate_m.group(1)}% {'a month' if monthly else 'a year'}:\n"
                f"  monthly payment  {payment:,.2f}\n  total paid       {total:,.2f}\n  total interest   {interest:,.2f}"
                "\n(Equal monthly payments. Bank fees and taxes such as KKDF/BSMV are not included.)")

    # --- trips and gifts -----------------------------------------------------------------------------

    @command("pack", "packing", group=G, usage="/pack <where, how long, what for>", help="a packing list")
    def pack(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /pack <trip>   e.g. /pack 5 days in Rome in November, city sightseeing"
        forecast = ""
        try:
            from . import weather

            place = re.split(r"\s+(?:for|in|,)\s+", args.strip())
            for chunk in re.findall(r"\b(?:in|to)\s+([A-Z][\w-]+)", args):
                forecast = weather.report(f"this week in {chunk}")
                break
        except Exception:
            forecast = ""
        return self.brain.ask_once(f"Make a packing checklist for: {args.strip()}."
                                   + (f"\nForecast there: {forecast}" if forecast else "") +
                                   "\nGroup it (documents, clothes, toiletries, tech, health, other) as '- [ ] item' lines. "
                                   "Be specific to the trip. Same language as the request.")

    @command("gift", "gifts", group=G, usage="/gift <who, budget, what they like>", help="gift ideas")
    def gift(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /gift <who, occasion, budget, interests>   e.g. /gift my sister's 20th birthday, 1500 TL, loves books and coffee"
        return self.brain.ask_once(f"Suggest 8 thoughtful gift ideas for: {args.strip()}. For each: the idea, a rough "
                                   "price, and one line on why it fits. Mix practical, experiential and personal. "
                                   "Same language as the request.")

    # --- chance -----------------------------------------------------------------------------------------

    @command("roll", "dice", "flip", "pick", "random", group=G, usage="/roll 2d6 · /flip · /pick a, b, c · /random 1-100",
             help="dice, coins and random choices")
    def chance(self, args: str, routed: bool = False):
        text = args.strip()
        low = text.lower()
        rng = random.SystemRandom()
        if low in {"", "coin", "flip"} and getattr(self, "_last_command", "") == "flip" or low in {"coin", "a coin"}:
            return f"🪙 {rng.choice(['Heads', 'Tails'])}"
        m = re.fullmatch(r"(\d*)d(\d+)(?:\s*\+\s*(\d+))?", low)
        if m:
            count, sides, bonus = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)
            if not (1 <= count <= 100 and 2 <= sides <= 1000):
                return "Up to 100 dice of up to 1000 sides."
            rolls = [rng.randint(1, sides) for _ in range(count)]
            return f"🎲 {' + '.join(map(str, rolls))}{f' + {bonus}' if bonus else ''} = {sum(rolls) + bonus}"
        m = re.fullmatch(r"(-?\d+)\s*(?:-|to|\.\.)\s*(-?\d+)", low)
        if m:
            low_n, high_n = sorted((int(m.group(1)), int(m.group(2))))
            return f"🎯 {rng.randint(low_n, high_n)}"
        options = [o.strip() for o in re.split(r",|\bor\b|\bveya\b|;|\n", text) if o.strip()]
        if len(options) >= 2:
            return f"👉 {rng.choice(options)}"
        if not text:
            return f"🎲 {rng.randint(1, 6)}"
        return "Usage: /roll 2d6 · /flip · /pick pizza, sushi, döner · /random 1-100"

    # --- calendar ------------------------------------------------------------------------------------------

    @command("cal", "calendar", "event", group=G, usage="/cal add dentist friday 14:00 · /cal · /cal export",
             help="a local calendar; exports .ics for Google/Outlook")
    def calendar(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        verb = verb.lower()
        events = sorted(CALENDAR.load(), key=lambda e: e["start"])
        if verb in {"add", "new"}:
            length = 3600
            dm = re.search(r"\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(h|hours?|m|min|minutes?)\b\s*$", rest, re.I)
            if dm:
                length = float(dm.group(1)) * (3600 if dm.group(2).lower().startswith("h") else 60)
                rest = rest[:dm.start()]
            where = ""
            wm = re.search(r"\s+@\s*([^@]+?)(?=\s+(?:on|at|tomorrow|today|next|\d)|$)", rest)
            if wm:
                where = wm.group(1).strip()
                rest = rest[:wm.start()] + rest[wm.end():]
            start, title = parse_when(rest)
            if start is None or not title:
                return "Usage: /cal add <what> <when> [1h] [@ place]   e.g. /cal add dentist friday 14:00 @ Kadıköy"
            event = {"title": title, "start": start.timestamp(), "end": start.timestamp() + length, "where": where,
                     "uid": uuid.uuid4().hex}
            events.append(event)
            CALENDAR.save(events)
            if start.timestamp() - 900 > time.time():
                reminders.board.add("event", f"{title} at {start:%H:%M}" + (f" @ {where}" if where else ""), start.timestamp() - 900)
            return f"📅 {title} — {start:%a %d %b %H:%M}" + (f" @ {where}" if where else "") + " (reminder 15 min before)."
        if verb in {"delete", "remove"}:
            upcoming = [e for e in events if e["end"] >= time.time()]
            if not rest.strip().isdigit() or not 1 <= int(rest) <= len(upcoming):
                return "Which one? /cal lists upcoming events with numbers."
            gone = upcoming[int(rest) - 1]
            CALENDAR.save([e for e in events if e is not gone])
            return f"Deleted {gone['title']}."
        if verb == "export":
            path = kit.output_dir() / f"jarvis-calendar_{kit.stamp()}.ics"
            path.write_text(ics(events), encoding="utf-8")
            return f"Exported {len(events)} event(s) to\n  {path}\nImport it in Google Calendar (Settings → Import) or Outlook."
        if verb == "import":
            path = kit.path_arg(rest)
            if path is None:
                return "Usage: /cal import <file.ics>"
            new = parse_ics(path.read_text(encoding="utf-8", errors="replace"))
            uids = {e.get("uid") for e in events}
            added = [e for e in new if not e.get("uid") or e["uid"] not in uids]
            CALENDAR.save(events + added)
            return f"Imported {len(added)} event(s) from {path.name}."
        span = {"today": 1, "tomorrow": 2, "week": 7, "month": 31}.get(verb, 7)
        start = datetime.combine(date.today() + timedelta(days=1 if verb == "tomorrow" else 0), datetime.min.time())
        end = start + timedelta(days=1 if verb in {"today", "tomorrow"} else span)
        upcoming = [e for e in events if e["end"] >= time.time()]
        shown = [(i, e) for i, e in enumerate(upcoming, 1) if start.timestamp() <= e["start"] < end.timestamp() or
                 (verb not in {"today", "tomorrow"} and e["start"] < end.timestamp())]
        if not shown:
            return "Nothing in your calendar" + (f" {verb}." if verb in {"today", "tomorrow"} else " this week.") + \
                "  /cal add <what> <when>"
        lines = ["📅 " + {"today": "Today", "tomorrow": "Tomorrow"}.get(verb, "Coming up") + ":"]
        for i, e in shown:
            moment = datetime.fromtimestamp(e["start"])
            lines.append(f"  {i:>2}. {moment:%a %d %b %H:%M}  {e['title']}" + (f"  @ {e['where']}" if e.get("where") else ""))
        lines.append("/cal today|tomorrow|month · /cal export · /cal delete <n>")
        return "\n".join(lines)


def _find_task(items: list[dict], which: str) -> int | None:
    which = which.strip().lower()
    open_items = [i for i, t in enumerate(items) if not t.get("done")]
    if which.isdigit():
        n = int(which)
        return open_items[n - 1] if 1 <= n <= len(open_items) else None
    matches = [i for i in open_items if which and which in items[i]["text"].lower()]
    return matches[0] if matches else None


def _describe_tasks(items: list[dict], show_done: bool = False) -> str:
    open_items = [t for t in items if not t.get("done")]
    if not open_items and not show_done:
        return "Your list is empty. /mylist add <thing> [when] adds one."
    open_items.sort(key=lambda t: (t.get("due") or 9e12))
    lines = ["To do:"]
    now = time.time()
    for n, t in enumerate(open_items, 1):
        due = ""
        if t.get("due"):
            moment = datetime.fromtimestamp(t["due"])
            due = f"  — {'⚠ overdue ' if t['due'] < now else ''}{moment:%a %d %b %H:%M}"
        lines.append(f"  {n}. ☐ {t['text']}{due}")
    if show_done:
        lines += [f"     ☑ {t['text']}" for t in items if t.get("done")][-15:]
    lines.append("/done <n> · /mylist delete <n> · /mylist clear (removes finished)")
    return "\n".join(lines)
