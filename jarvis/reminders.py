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
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "half an": 0.5,
}


@dataclass
class Reminder:
    id: int
    kind: str          # reminder | timer | alarm
    text: str
    due: float         # epoch seconds
    created: float
    fired: bool = False

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
        icon = {"timer": "⏱", "alarm": "⏰"}.get(self.kind, "🔔")
        return f"  {self.id:>2}. {icon} {self.text or self.kind}  —  {self.when()}"


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
    match = re.match(
        r"^(?:for\s+)?(half an|an|a|\d+(?:[.,]\d+)?|one|two|three|four|five|ten|fifteen|twenty|thirty|forty|fifty)"
        r"\s*(seconds?|secs?|s|minutes?|mins?|m|dk|dakika|hours?|hrs?|h|saat|saniye|days?|d|gün)\b(.*)$",
        text, re.I,
    )
    if not match:
        return None
    amount = _amount(match.group(1))
    unit = _UNITS.get(match.group(2).lower())
    if amount is None or unit is None:
        return None
    if match.group(1).lower() == "half an":
        amount = 0.5
    return amount * unit, match.group(3).strip(" ,.-:")


def parse_clock(text: str, now: datetime | None = None) -> tuple[datetime, str] | None:
    """'7:30', '5pm', 'tomorrow at 9', 'at 17:45 leave' -> (moment, rest)."""
    now = now or datetime.now()
    text = text.strip()
    day_offset = 0
    lowered = text.lower()
    tonight = False
    for word, offset in (("tomorrow", 1), ("yarın", 1), ("today", 0), ("bugün", 0), ("tonight", 0)):
        if lowered.startswith(word):
            day_offset = offset
            text = text[len(word):].strip(" ,")
            if word == "tonight" and not re.search(r"\d", text):
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
        moment += timedelta(days=1)       # "alarm 7:30" at 22:00 means tomorrow
    return moment, match.group(4).strip(" ,.-:")


def parse_reminder(text: str, now: datetime | None = None) -> tuple[float, str] | None:
    """'in 20 minutes to call Ata' / 'at 5pm to leave' -> (epoch, 'call Ata')."""
    now = now or datetime.now()
    body = text.strip()
    body = re.sub(r"^(?:me\s+)", "", body, flags=re.I)

    def tidy(rest: str) -> str:
        return re.sub(r"^(?:to|that|about|of)\s+", "", rest.strip(" ,.-:"), flags=re.I)

    # "to call Ata in 20 minutes" — the time can come last, too.
    tail = re.match(r"^(?:to\s+)?(.+?)\s+(in\s+.+|at\s+.+|tomorrow.*|tonight.*)$", body, re.I)
    candidates = [body]
    if tail:
        candidates.append(f"{tail.group(2)} to {tail.group(1)}")

    for candidate in candidates:
        lowered = candidate.lower()
        if lowered.startswith("in "):
            parsed = parse_duration(candidate[3:])
            if parsed:
                seconds, rest = parsed
                return now.timestamp() + seconds, tidy(rest)
        parsed_clock = parse_clock(candidate, now)
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
                ))
            except (KeyError, TypeError, ValueError):
                continue
        now = time.time()
        # Due while JARVIS was closed: reported once, not fired late in a burst.
        self.missed = [r for r in items if not r.fired and r.due < now - 60]
        self.items = [r for r in items if not r.fired and r not in self.missed]
        if self.missed:
            self.save()

    def save(self) -> None:
        try:
            vault.write_json(self._path(), [r.__dict__ for r in self.items])
        except (OSError, TypeError, ValueError):
            pass

    def add(self, kind: str, text: str, due: float) -> Reminder:
        with self._lock:
            next_id = max((r.id for r in self.items), default=0) + 1
            item = Reminder(next_id, kind, text.strip(), due, time.time())
            self.items.append(item)
            self.items.sort(key=lambda r: r.due)
        self.save()
        return item

    def cancel(self, which: str) -> str:
        which = which.strip().lower()
        with self._lock:
            if which in {"all", "everything"}:
                count = len(self.items)
                self.items = []
            else:
                keep = [r for r in self.items if str(r.id) != which and r.text.lower() != which]
                count = len(self.items) - len(keep)
                self.items = keep
        self.save()
        return f"Cancelled {count}." if count else f"Nothing called '{which}' is pending."

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
