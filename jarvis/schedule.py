"""Scheduled tasks — things JARVIS does on its own, on a timer.

Deliberately modest, because the honest version of this is better than an
impressive one that lies. Tasks run only while JARVIS is open: there is no
background service, nothing is installed, and closing the window stops
everything. A task that was due while the app was shut is reported as missed
rather than fired late in a burst.

Each task is a command — the same commands you type — run on an interval. It
cannot do anything you could not do yourself in the window, and everything it
does still goes through the permission prompts and the audit log.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import get_data_dir

TASKS_FILE = "tasks.json"
# Anything faster than this is a busy loop wearing a hat.
MIN_INTERVAL_MINUTES = 1
# How often the runner wakes to see whether anything is due.
TICK_SECONDS = 20


@dataclass
class Task:
    name: str
    command: str
    every_minutes: int
    last_run: float = 0.0
    enabled: bool = True
    runs: int = 0

    def due(self, now: float) -> bool:
        if not self.enabled:
            return False
        return now - self.last_run >= self.every_minutes * 60

    def next_due(self) -> str:
        if not self.enabled:
            return "paused"
        if not self.last_run:
            return "on the next tick"
        when = datetime.fromtimestamp(self.last_run) + timedelta(minutes=self.every_minutes)
        delta = (when - datetime.now()).total_seconds()
        if delta <= 0:
            return "now"
        if delta < 3600:
            return f"in {int(delta / 60)} min"
        return when.strftime("%H:%M")

    def line(self) -> str:
        mark = " " if self.enabled else "-"
        return (
            f"  {mark} {self.name:<18} every {self.every_minutes:>4} min   "
            f"next {self.next_due():<12} ran {self.runs}x\n"
            f"      {self.command}"
        )


class Scheduler:
    """Holds the tasks and, while JARVIS is open, runs them."""

    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._runner = None
        self._lock = threading.Lock()
        self.load()

    # --- storage ----------------------------------------------------------

    def _path(self):
        return get_data_dir() / TASKS_FILE

    def load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        self.tasks = [
            Task(
                name=str(t.get("name") or "task"),
                command=str(t.get("command") or ""),
                every_minutes=max(MIN_INTERVAL_MINUTES, int(t.get("every_minutes") or 60)),
                last_run=float(t.get("last_run") or 0),
                enabled=bool(t.get("enabled", True)),
                runs=int(t.get("runs") or 0),
            )
            for t in data
            if isinstance(t, dict) and t.get("command")
        ]

    def save(self) -> None:
        try:
            self._path().write_text(json.dumps([
                {
                    "name": t.name, "command": t.command,
                    "every_minutes": t.every_minutes, "last_run": t.last_run,
                    "enabled": t.enabled, "runs": t.runs,
                }
                for t in self.tasks
            ], indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    # --- managing ---------------------------------------------------------

    def add(self, name: str, minutes: int, command: str) -> str:
        name = name.strip() or f"task-{len(self.tasks) + 1}"
        command = command.strip()
        if not command:
            return "A task needs a command to run."
        if not command.startswith("/"):
            command = "/" + command.lstrip("/")
        minutes = max(MIN_INTERVAL_MINUTES, minutes)
        if any(t.name.lower() == name.lower() for t in self.tasks):
            return f"There is already a task called '{name}'."
        self.tasks.append(Task(name=name, command=command, every_minutes=minutes))
        self.save()
        return (
            f"Added '{name}': {command} every {minutes} minutes.\n"
            "It runs only while JARVIS is open."
        )

    def remove(self, name: str) -> str:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.name.lower() != name.strip().lower()]
        if len(self.tasks) == before:
            return f"There is no task called '{name}'."
        self.save()
        return f"Removed '{name}'."

    def toggle(self, name: str) -> str:
        for task in self.tasks:
            if task.name.lower() == name.strip().lower():
                task.enabled = not task.enabled
                self.save()
                return f"'{task.name}' is now {'on' if task.enabled else 'paused'}."
        return f"There is no task called '{name}'."

    def describe(self) -> str:
        if not self.tasks:
            return (
                "No scheduled tasks.\n\n"
                "  /task add <name> <minutes> <command>\n"
                '  e.g. /task add scan 60 /scan self\n\n'
                "Tasks run only while JARVIS is open — there is no background "
                "service and nothing is installed."
            )
        running = "running" if self._thread and self._thread.is_alive() else "not running"
        return (
            f"Scheduled tasks ({len(self.tasks)}, scheduler {running}):\n"
            + "\n".join(t.line() for t in self.tasks)
            + "\n\n/task remove <name>, /task pause <name>, /task run <name>"
        )

    def find(self, name: str) -> Task | None:
        for task in self.tasks:
            if task.name.lower() == name.strip().lower():
                return task
        return None

    # --- running ----------------------------------------------------------

    def start(self, runner) -> None:
        """Begin ticking. `runner(task)` is called when one is due."""
        self._runner = runner
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            if not self.tasks or self._runner is None:
                continue
            now = time.time()
            with self._lock:
                due = [t for t in self.tasks if t.due(now)]
            for task in due:
                task.last_run = now
                task.runs += 1
                self.save()
                try:
                    self._runner(task)
                except Exception:
                    # A task that throws must not take the scheduler with it.
                    continue


scheduler = Scheduler()
