"""Focus mode 2.0 (Bounty update): Pomodoro, blocking, and stats.

Work in focus blocks (25 minutes by default) with short breaks between. While
a focus block runs, JARVIS looks at the window in front every two seconds:
if it is a site or an app on your block list, the window is minimised and you
get a gentle "back to it". Sites are recognised by the browser's tab title
(YouTube, Instagram…) — no administrator rights, nothing installed, and
nothing changes on the PC once focus mode stops.

Every finished block, every minute focused and every distraction stopped is
counted, per day, for the stats.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import kit

DEFAULT_SITES = ["youtube", "instagram", "tiktok", "twitter", "x.com", "reddit", "netflix", "twitch", "facebook",
                 "9gag", "pinterest", "disney+", "prime video", "ekşi sözlük"]
DEFAULT_APPS = ["steam.exe", "epicgameslauncher.exe", "discord.exe", "spotify.exe", "riotclientservices.exe",
                "battle.net.exe", "whatsapp.exe", "telegram.exe"]
LISTS = kit.Store("focus_lists.json", {})
STATS = kit.Store("focus_stats.json", {})
TICK = 2.0
NUDGE_EVERY = 45


def lists() -> dict:
    data = LISTS.load()
    return {"sites": data.get("sites", list(DEFAULT_SITES)), "apps": data.get("apps", list(DEFAULT_APPS))}


def edit_list(kind: str, action: str, value: str) -> str:
    data = lists()
    value = value.strip().lower()
    if kind not in data or not value:
        return "Usage: /focus sites add youtube · /focus apps remove discord.exe"
    if action == "add" and value not in data[kind]:
        data[kind].append(value)
    elif action == "remove":
        data[kind] = [v for v in data[kind] if v != value]
    LISTS.save(data)
    return f"🎯 Blocked {kind}: {', '.join(data[kind]) or 'none'}"


def blocked(title: str, process: str, block: dict) -> str:
    """What on the block list this window is, or ''."""
    low_title, low_process = (title or "").lower(), (process or "").lower()
    if low_process and low_process in [a.lower() for a in block.get("apps", [])]:
        return low_process
    # Only browser windows are judged by their title: a document called "youtube notes.docx" is work.
    browsers = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "arc.exe")
    if low_process in browsers or not low_process:
        for site in block.get("sites", []):
            if site.lower() in low_title:
                return site
    return ""


def _today() -> str:
    return date.today().isoformat()


def record(minutes: float = 0, sessions: int = 0, blocked_count: int = 0, day: str | None = None) -> None:
    data = STATS.load()
    row = data.setdefault(day or _today(), {"minutes": 0, "sessions": 0, "blocked": 0})
    row["minutes"] = round(row.get("minutes", 0) + minutes, 1)
    row["sessions"] = row.get("sessions", 0) + sessions
    row["blocked"] = row.get("blocked", 0) + blocked_count
    STATS.save({d: r for d, r in data.items() if d >= (date.today() - timedelta(days=90)).isoformat()})


def week() -> list[tuple[str, dict]]:
    data = STATS.load()
    days = [(date.today() - timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
    return [(d, data.get(d, {"minutes": 0, "sessions": 0, "blocked": 0})) for d in days]


def stats_text() -> str:
    rows = week()
    total = sum(r["minutes"] for _, r in rows)
    lines = [f"🎯 Focus this week: {total / 60:.1f} h in {sum(r['sessions'] for _, r in rows)} block(s), "
             f"{sum(r['blocked'] for _, r in rows)} distraction(s) stopped."]
    best = max(r["minutes"] for _, r in rows) or 1
    for day, row in rows:
        bar = "█" * round(12 * row["minutes"] / best) if row["minutes"] else ""
        lines.append(f"  {date.fromisoformat(day):%a}  {bar:<12} {row['minutes']:.0f} min")
    return "\n".join(lines)


@dataclass
class Session:
    focus_minutes: int = 25
    break_minutes: int = 5
    blocks: int = 4
    phase: str = "idle"              # idle · focus · break · done
    block: int = 0
    ends: float = 0.0
    started: float = 0.0
    stopped_now: int = 0
    log: list = field(default_factory=list)

    def remaining(self, now: float | None = None) -> float:
        return max(0.0, self.ends - (now or time.time()))


class Focus:
    def __init__(self, notify=None, front=None, minimise=None) -> None:
        self.session = Session()
        self.notify = notify or (lambda title, body: None)
        self.front = front or front_window
        self.minimise = minimise or minimise_window
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_nudge = 0.0
        self.listeners: list = []

    @property
    def running(self) -> bool:
        return self.session.phase in {"focus", "break"}

    def start(self, focus_minutes: int = 25, break_minutes: int = 5, blocks: int = 4) -> str:
        if self.running:
            return self.status()
        self.session = Session(max(1, focus_minutes), max(1, break_minutes), max(1, blocks))
        self._begin("focus", 1)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-focus")
        self._thread.start()
        block = lists()
        return (f"🎯 Focus: {self.session.focus_minutes} min on, {self.session.break_minutes} off, "
                f"{self.session.blocks} block(s). I'll minimise {len(block['sites'])} site(s) and "
                f"{len(block['apps'])} app(s) until the break. /focus stop ends it.")

    def stop(self) -> str:
        if not self.running:
            return "Focus mode isn't on."
        self._credit()
        self.session.phase = "idle"
        self._stop.set()
        self._changed()
        return "🎯 Focus mode off. " + stats_text().splitlines()[0][2:]

    def _begin(self, phase: str, block: int) -> None:
        s = self.session
        s.phase, s.block, s.started = phase, block, time.time()
        s.ends = s.started + 60 * (s.focus_minutes if phase == "focus" else s.break_minutes)
        self._changed()

    def _credit(self) -> None:
        s = self.session
        if s.phase == "focus":
            record(minutes=(time.time() - s.started) / 60)

    def tick(self, now: float | None = None) -> None:
        """One look at the screen and the clock. The loop calls it; tests call it directly."""
        now = now or time.time()
        s = self.session
        if s.phase == "focus":
            title, process = self.front()
            hit = blocked(title, process, lists())
            if hit:
                self.minimise()
                s.stopped_now += 1
                record(blocked_count=1)
                if now - self._last_nudge > NUDGE_EVERY:
                    self._last_nudge = now
                    self.notify("Back to it 🎯", f"{hit} is blocked for {int(s.remaining(now) // 60) + 1} more min.")
        if s.phase in {"focus", "break"} and now >= s.ends:
            if s.phase == "focus":
                record(minutes=s.focus_minutes, sessions=1)
                if s.block >= s.blocks:
                    s.phase = "done"
                    self._stop.set()
                    self.notify("Focus done 🎉", f"{s.blocks} block(s) finished. Great work.")
                    self._changed()
                    return
                self.notify("Break ☕", f"Block {s.block} done. {s.break_minutes} min break.")
                self._begin("break", s.block)
            else:
                self.notify("Back to focus 🎯", f"Block {s.block + 1} of {s.blocks}: {s.focus_minutes} min.")
                self._begin("focus", s.block + 1)

    def _loop(self) -> None:
        while not self._stop.wait(TICK):
            try:
                self.tick()
            except Exception:
                pass

    def _changed(self) -> None:
        for listener in list(self.listeners):
            try:
                listener(self.session)
            except Exception:
                pass

    def status(self) -> str:
        s = self.session
        if not self.running:
            return "Focus mode is off. /focus start [minutes] begins a session."
        left = s.remaining()
        word = "Focus" if s.phase == "focus" else "Break"
        return (f"🎯 {word}, block {s.block}/{s.blocks}: {int(left // 60)}:{int(left % 60):02d} left. "
                f"{s.stopped_now} distraction(s) stopped so far.")


# --- the window in front (Windows) -------------------------------------------------------------

def front_window() -> tuple[str, str]:  # pragma: no cover - the real desktop
    if sys.platform != "win32":
        return "", ""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil

        process = psutil.Process(pid.value).name()
    except Exception:
        process = ""
    if process.lower() in {"python.exe", "pythonw.exe", "jarvis.exe"}:
        return "", ""       # never JARVIS itself
    return buffer.value, process


def minimise_window() -> None:  # pragma: no cover - the real desktop
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.user32.GetForegroundWindow(), 6)   # SW_MINIMIZE


focus = Focus()
