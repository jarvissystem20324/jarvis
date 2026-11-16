"""Reminders, timers and alarms, from plain words.

    remind me in 20 minutes to call Ata
    remind me at 17:30 to leave
    remind me tomorrow at 9 to send the report
    timer 10 minutes tea          alarm 7:30

One engine for all three: a list of things due at a moment, saved (sealed,
see vault) so a restart does not lose them. They fire only while JARVIS is
open — like scheduled tasks there is no background service — and anything
that came due while it was closed is shown, marked as missed, on the next
start rather than silently dropped.

The time parsing is deliberately plain pattern matching. It understands the
handful of ways people actually say these things; anything else gets a clear
"I couldn't tell when" rather than a guess.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import vault
from .config import get_data_dir

FILE = "reminders.json"
TICK_SECONDS = 1.0

_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "saniye": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "dakika": 60, "dk": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "saat": 3600,
    "d": 86400, "day": 86400, "days": 86400, "gün": 86400,
}
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_NUMBERS: dict[str, float] = {
    "a": 1, "an": 1, "half an": 0.5, "a couple of": 2, "a few": 3,
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50,
    **{word: n for n, word in enumerate(_ONES)}, **_TENS,
    # "forty-five", "twenty five": every tens-and-units pair.
    **{f"{t}{sep}{u}": _TENS[t] + _ONES.index(u) for t in _TENS for u in _ONES[1:10] for sep in ("-", " ")},
}
# Longest first, so "forty-five" wins over "forty" and "half an" over "a".
_NUMBER_WORDS = "|".join(sorted((re.escape(w) for w in _WORD_NUMBERS), key=len, reverse=True))
_UNIT_WORDS = r"seconds?|secs?|s|minutes?|mins?|m|dk|dakika|hours?|hrs?|h|saat|saniye|days?|d|gün"


@dataclass
class Reminder:
    id: int
    kind: str          # reminder | timer | alarm
    text: str
    due: float         # epoch seconds
    created: float
    fired: bool = False
    repeat: str = ""   # "" | daily | weekly | weekdays | monthly | every:<seconds>   (8.0)
    until: float = 0.0  # a repeating item stops after this moment; 0 = never

    def when(self) -> str:
        moment = datetime.fromtimestamp(self.due)
        delta = self.due - time.time()
        if delta < 0:
            return f"was due {moment:%H:%M}"
        if delta < 3600:
            minutes, seconds = divmod(int(delta), 60)
            return f"in {minutes}m {seconds:02d}s" if minutes else f"in {seconds}s"
        day = "today" if moment.date() == datetime.now().date() else f"{moment:%a %d %b}"
        return f"{day} at {moment:%H:%M}"

    def line(self) -> str:
        icon = {"timer": "⏱", "alarm": "⏰", "meds": "💊", "event": "📅", "task": "✅"}.get(self.kind, "🔔")
        again = f"  ({describe_repeat(self.repeat)})" if self.repeat else ""
        return f"  {self.id:>2}. {icon} {self.text or self.kind}  —  {self.when()}{again}"


# Kinds that do their work when they fire (a price check, the next prayer
# time). If one came due while JARVIS was closed it is simply run soon after
# start, instead of being listed as a missed reminder.
RESUME_KINDS = {"watch", "prayer", "word"}


def describe_repeat(repeat: str) -> str:
    if repeat.startswith("every:"):
        seconds = int(float(repeat[6:]))
        return f"every {describe_seconds(seconds)}"
    return {"daily": "every day", "weekly": "every week", "weekdays": "every weekday",
            "monthly": "every month"}.get(repeat, repeat)


def next_due(due: float, repeat: str, now: float | None = None) -> float | None:
    """The next occurrence after `now` of something that repeats."""
    now = time.time() if now is None else now
    if not repeat:
        return None
    moment = datetime.fromtimestamp(due)
    for _ in range(10000):
        if repeat == "daily":
            moment += timedelta(days=1)
        elif repeat == "weekly":
            moment += timedelta(days=7)
        elif repeat == "weekdays":
            moment += timedelta(days=1)
            while moment.weekday() >= 5:
                moment += timedelta(days=1)
        elif repeat == "monthly":
            month = moment.month % 12 + 1
            year = moment.year + (moment.month == 12)
            day = min(moment.day, 28)
            moment = moment.replace(year=year, month=month, day=day)
        elif repeat.startswith("every:"):
            moment += timedelta(seconds=max(60.0, float(repeat[6:])))
        else:
            return None
        if moment.timestamp() > now:
            return moment.timestamp()
    return None


# --- parsing ---------------------------------------------------------------

def _amount(raw: str) -> float | None:
    raw = raw.strip().lower()
    if raw in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[raw])
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_duration(text: str) -> tuple[float, str] | None:
    """'10 minutes tea' -> (600, 'tea'). Also '1h30m', '90s', 'half an hour'."""
    text = text.strip()
    compact = re.match(r"^(\d+h)?\s*(\d+m)?\s*(\d+s)?\b(.*)$", text, re.I)
    if compact and any(compact.group(i) for i in (1, 2, 3)):
        seconds = 0
        for group, unit in ((1, 3600), (2, 60), (3, 1)):
            if compact.group(group):
                seconds += int(compact.group(group)[:-1]) * unit
        return float(seconds), compact.group(4).strip(" ,.-:")
    # Every "<amount> <unit>" in a row adds up: "1 hour 30 minutes" was one
    # hour, with "30 minutes" left over as the label.
    pattern = re.compile(rf"^(?:for\s+|and\s+|,\s*)?({_NUMBER_WORDS}|\d+(?:[.,]\d+)?)\s*({_UNIT_WORDS})\b(.*)$", re.I)
    total, rest, matched = 0.0, text, False
    while True:
        match = pattern.match(rest.strip())
        if not match:
            break
        amount = _amount(match.group(1))
        unit = _UNITS.get(match.group(2).lower())
        if amount is None or unit is None:
            break
        total += amount * unit
        rest, matched = match.group(3), True
    if not matched:
        return None
    return total, rest.strip(" ,.-:")


def parse_clock(text: str, now: datetime | None = None, later_today: bool = False) -> tuple[datetime, str] | None:
    """'7:30', '5pm', 'tomorrow at 9', 'at 17:45 leave' -> (moment, rest).

    `later_today`: a bare hour already past today means this evening ("at 5"
    at 14:00 is 17:00). Reminders ask for that; alarms don't, since "alarm 6"
    set in the afternoon means 06:00 tomorrow.
    """
    now = now or datetime.now()
    text = text.strip()
    day_offset = 0
    lowered = text.lower()
    tonight = said_tonight = False
    for word, offset in (("tomorrow", 1), ("yarın", 1), ("today", 0), ("bugün", 0), ("tonight", 0), ("bu akşam", 0)):
        if lowered.startswith(word):
            day_offset = offset
            text = text[len(word):].strip(" ,")
            said_tonight = word in {"tonight", "bu akşam"}
            if said_tonight and not re.search(r"\d", text):
                tonight = True
                text = "20:00 " + text
            break
    match = re.match(
        r"^(?:at\s+|saat\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b(.*)$", text, re.I
    )
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridian = (match.group(3) or "").lower().replace(".", "")
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if said_tonight and not meridian and 1 <= hour <= 11:
        hour += 12                         # "tonight at 9" is 21:00, not 09:00 tomorrow
    elif said_tonight and not meridian and hour == 12:
        hour, day_offset = 0, day_offset + 1     # "tonight at 12" is midnight, not noon tomorrow
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    # A bare number with no colon and no am/pm must look like a time.
    if not match.group(2) and not meridian and not text.lower().startswith(("at ", "saat ")) and day_offset == 0:
        if not re.match(r"^\d{1,2}\s*$", text.split(" to ")[0].strip()):
            return None
    moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    if tonight and moment <= now:
        # "Tonight" said at 21:00 still means tonight, not tomorrow night.
        moment = now.replace(second=0, microsecond=0) + timedelta(minutes=30)
    elif moment <= now and day_offset == 0:
        later = moment + timedelta(hours=12)
        if later_today and not meridian and not match.group(2) and 1 <= hour <= 11 and later > now \
                and later.date() == now.date():
            moment = later                # "at 5" said at 14:00 means 17:00 today, not 05:00 tomorrow
        else:
            moment += timedelta(days=1)   # "alarm 7:30" at 22:00 means tomorrow
    return moment, match.group(4).strip(" ,.-:")


def parse_reminder(text: str, now: datetime | None = None) -> tuple[float, str] | None:
    """'in 20 minutes to call Ata' / 'at 5pm to leave' -> (epoch, 'call Ata')."""
    now = now or datetime.now()
    body = text.strip()
    body = re.sub(r"^(?:me\s+)", "", body, flags=re.I)

    def tidy(rest: str) -> str:
        return re.sub(r"^(?:to|that|about|of)\s+", "", rest.strip(" ,.-:"), flags=re.I)

    # "to call Ata in 20 minutes" — the time can come last, too. Every split
    # is tried, last first: "to check in with Ali at 5pm" split at its first
    # "in" found no time and set nothing.
    candidates = [body]
    splits = [m.start() for m in re.finditer(r"\s+(?=(?:in|at)\s|tomorrow\b|tonight\b)", body, re.I)]
    for at in reversed(splits):
        what, when = body[:at].strip(), body[at:].strip()
        candidates.append(f"{when} to {re.sub(r'^to\s+', '', what, flags=re.I)}")

    for candidate in candidates:
        lowered = candidate.lower()
        if lowered.startswith("in "):
            parsed = parse_duration(candidate[3:])
            if parsed:
                seconds, rest = parsed
                return now.timestamp() + seconds, tidy(rest)
        parsed_clock = parse_clock(candidate, now, later_today=True)
        if parsed_clock:
            moment, rest = parsed_clock
            return moment.timestamp(), tidy(rest)
    return None


# --- store and runner --------------------------------------------------------

class Board:
    """Everything pending, persisted, and fired on time while JARVIS is open."""

    def __init__(self) -> None:
        self.items: list[Reminder] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_fire = None
        self.missed: list[Reminder] = []
        self.load()

    def _path(self):
        return get_data_dir() / FILE

    def load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            data = vault.read_json(path)
        except (OSError, ValueError):
            return
        items = []
        for raw in data if isinstance(data, list) else []:
            try:
                items.append(Reminder(
                    id=int(raw["id"]), kind=str(raw.get("kind") or "reminder"),
                    text=str(raw.get("text") or ""), due=float(raw["due"]),
                    created=float(raw.get("created") or 0), fired=bool(raw.get("fired")),
                    repeat=str(raw.get("repeat") or ""), until=float(raw.get("until") or 0),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        now = time.time()
        # Due while JARVIS was closed: reported once, not fired late in a burst.
        late = [r for r in items if not r.fired and r.due < now - 60]
        self.items = [r for r in items if not r.fired and r not in late]
        self.missed = []
        for r in late:
            if r.kind == "prayer":
                # Keeps its real time, so live_fire sees it is old: moved to
                # now+30, it announced "İkindi time — 18:15" at start-up.
                self.items.append(r)
                continue
            if r.kind in RESUME_KINDS:
                r.due = now + 30
                self.items.append(r)
                continue
            self.missed.append(r)
            following = next_due(r.due, r.repeat, now)
            if following and (not r.until or following <= r.until):
                self.items.append(Reminder(r.id, r.kind, r.text, following, r.created, repeat=r.repeat, until=r.until))
        self.items.sort(key=lambda r: r.due)
        if late:
            self.save()

    def save(self) -> None:
        try:
            vault.write_json(self._path(), [r.__dict__ for r in self.items])
        except (OSError, TypeError, ValueError):
            pass

    def add(self, kind: str, text: str, due: float, repeat: str = "", until: float = 0.0) -> Reminder:
        with self._lock:
            next_id = max((r.id for r in self.items), default=0) + 1
            item = Reminder(next_id, kind, text.strip(), due, time.time(), repeat=repeat, until=until)
            self.items.append(item)
            self.items.sort(key=lambda r: r.due)
        self.save()
        return item

    def cancel(self, which: str, kinds: set[str] | None = None) -> str:
        """Cancel by number, text or "all" — only among `kinds` when given.

        "/timers stop" used to call this with "all" and no kinds, which also
        cancelled every reminder, alarm, briefing, price watch and prayer
        alert; the watches never came back, as their entry is what re-runs them.
        """
        which = which.strip().lower()
        with self._lock:
            mine = [r for r in self.items if kinds is None or r.kind in kinds]
            if which in {"all", "everything"} and kinds is None:
                # "/reminders cancel all" is about reminders: price watches,
                # prayer alerts and the word of the day have their own off
                # switches, and cancelled here they silently never ran again.
                mine = [r for r in mine if r.kind not in RESUME_KINDS]
            if which in {"all", "everything"}:
                gone = mine
            else:
                gone = [r for r in mine if str(r.id) == which or r.text.lower() == which]
            count = len(gone)
            self.items = [r for r in self.items if r not in gone]
        self.save()
        return f"Cancelled {count}." if count else f"Nothing called '{which}' is pending."

    def cancel_kind(self, kind: str) -> int:
        with self._lock:
            before = len(self.items)
            self.items = [r for r in self.items if r.kind != kind]
            removed = before - len(self.items)
        if removed:
            self.save()
        return removed

    def describe(self, kinds: set[str] | None = None) -> str:
        shown = [r for r in self.items if kinds is None or r.kind in kinds]
        if not shown:
            return "Nothing pending."
        return "\n".join(r.line() for r in shown)

    def start(self, on_fire) -> None:
        self._on_fire = on_fire
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            now = time.time()
            with self._lock:
                due = [r for r in self.items if r.due <= now]
                self.items = [r for r in self.items if r.due > now]
                for r in due:
                    following = next_due(r.due, r.repeat, now)
                    if following and (not r.until or following <= r.until):
                        self.items.append(Reminder(r.id, r.kind, r.text, following, r.created,
                                                   repeat=r.repeat, until=r.until))
                self.items.sort(key=lambda r: r.due)
            if not due:
                continue
            self.save()
            for item in due:
                item.fired = True
                try:
                    if self._on_fire:
                        self._on_fire(item)
                except Exception:
                    continue


board = Board()


def describe_seconds(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours}h" if hours else "", f"{minutes}m" if minutes else "",
             f"{secs}s" if secs and not hours else ""]
    return " ".join(p for p in parts if p) or "0s"


def ring(kind: str) -> None:
    """A sound people will actually notice. Windows only; silent elsewhere."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import winsound
        from pathlib import Path

        alarm = Path(r"C:\Windows\Media\Alarm01.wav")
        if kind == "alarm" and alarm.exists():
            for _ in range(3):
                winsound.PlaySound(str(alarm), winsound.SND_FILENAME)
            return
        for _ in range(3 if kind == "timer" else 1):
            winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS)
            time.sleep(0.35)
    except Exception:
        pass
