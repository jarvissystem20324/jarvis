"""Things JARVIS tells you without being asked (10.0).

Battery low, rain tomorrow, a new USB device, a scan that finished, a budget
gone over: whatever notices it calls post(), from any thread. The window
listens and shows a corner notification; the Home page lists the recent ones.
Nothing here touches Tk.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Alert:
    title: str
    body: str = ""
    page: str = ""          # the page that explains it, opened on click
    kind: str = "info"      # info, warn, ok
    at: float = field(default_factory=time.time)


_listeners: list = []
_recent: deque = deque(maxlen=100)
_lock = threading.Lock()


def listen(callback) -> None:
    """callback(alert) is called on the posting thread."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unlisten(callback) -> None:
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


def post(title: str, body: str = "", page: str = "", kind: str = "info") -> Alert:
    alert = Alert(title.strip(), body.strip(), page, kind)
    with _lock:
        _recent.appendleft(alert)
        listeners = list(_listeners)
    for callback in listeners:
        try:
            callback(alert)
        except Exception:
            pass
    return alert


def recent(limit: int = 20) -> list[Alert]:
    with _lock:
        return list(_recent)[:limit]


def clear() -> None:
    with _lock:
        _recent.clear()
