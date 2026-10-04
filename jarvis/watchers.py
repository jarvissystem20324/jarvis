"""One background thread for everything that has to keep an eye on something.

Battery level, the Wi-Fi network, new USB drives, a folder filling up, the
weather for tomorrow: each is a check with its own interval. Running them on
one thread, a few seconds apart, costs one sleeping thread instead of twenty.

A check is a plain function; anything it raises is swallowed and counted, so
one broken check (no battery on a desktop, no network) cannot stop the rest.
JARVIS_WATCHERS=off stops the whole thing — the tests set it.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    every: float
    fn: object
    last: float = 0.0
    errors: int = 0
    last_error: str = ""
    runs: int = 0
    paused: bool = False
    extra: dict = field(default_factory=dict)


class Watchers:
    TICK = 2.0

    def __init__(self) -> None:
        self.checks: dict[str, Check] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def add(self, name: str, every: float, fn, first_after: float = 5.0) -> Check:
        """Run fn() every `every` seconds; the first time after `first_after`."""
        check = Check(name, max(1.0, every), fn, last=time.time() - every + first_after)
        with self._lock:
            self.checks[name] = check
        return check

    def remove(self, name: str) -> None:
        with self._lock:
            self.checks.pop(name, None)

    def enabled(self) -> bool:
        return os.environ.get("JARVIS_WATCHERS", "on").strip().lower() not in {"off", "0", "false", "no"}

    def start(self) -> bool:
        if not self.enabled() or (self._thread is not None and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-watchers", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def run_due(self, now: float | None = None) -> list[str]:
        """Run every check that is due. The loop calls this; tests call it directly."""
        now = time.time() if now is None else now
        with self._lock:
            due = [c for c in self.checks.values() if not c.paused and now - c.last >= c.every]
        ran = []
        for check in due:
            check.last = now
            check.runs += 1
            try:
                check.fn()
            except Exception as exc:  # one broken check must not stop the rest
                check.errors += 1
                check.last_error = str(exc)[:200]
            ran.append(check.name)
        return ran

    def _loop(self) -> None:
        while not self._stop.wait(self.TICK):
            self.run_due()


watchers = Watchers()
