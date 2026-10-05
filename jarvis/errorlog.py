"""Errors nobody would otherwise see (10.0.1).

The EXE is a windowed app: it has no console, so an exception inside a
button's callback, a timer or a worker thread used to vanish — the button
just did nothing. Now each one is written to data/logs/errors.log (kept
small), and the window shows a corner notification once in a while, so a
problem can be noticed, reported and fixed. /errors shows the log.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path

LIMIT = 256 * 1024
_lock = threading.Lock()
_last_alert = [0.0]
_seen: list[str] = []          # the newest summaries, for /errors without reading the file


def log_path() -> Path:
    from .config import get_data_dir

    folder = get_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "errors.log"


def summary(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {text}"[:200] if text else type(exc).__name__


def record(where: str, exc: BaseException | None = None, text: str | None = None) -> str:
    """Write one error to the log. Returns its one-line summary."""
    from . import __version__

    if text is None:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else "(no details)"
    line = summary(exc) if exc else text.strip().splitlines()[-1][:200]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"=== {stamp}  JARVIS {__version__}  {where}\n{text.rstrip()}\n\n"
    with _lock:
        _seen.insert(0, f"{stamp}  {where}: {line}")
        del _seen[50:]
        try:
            path = log_path()
            if path.exists() and path.stat().st_size > LIMIT:
                # Keep the newer half, so the log never grows without end.
                kept = path.read_bytes()[-LIMIT // 2:]
                path.write_bytes(kept[kept.find(b"=== "):] if b"=== " in kept else kept)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(entry)
        except OSError:
            pass
    return line


def recent(limit: int = 10) -> list[str]:
    with _lock:
        return list(_seen[:limit])


def tell(line: str, where: str) -> None:
    """A corner notification, at most one a minute so a broken timer can't flood the screen."""
    now = time.monotonic()
    if now - _last_alert[0] < 60:
        return
    _last_alert[0] = now
    try:
        from . import alerts

        alerts.post("Something went wrong", f"{line}\n({where} — the details are in /errors)", kind="error")
    except Exception:
        pass


def install(root) -> None:
    """Catch what Tk callbacks, threads and the main loop would otherwise drop."""

    def tk_error(exc_type, exc, tb):
        if exc is None:
            exc = exc_type()
        exc.__traceback__ = tb
        line = record("a button or timer", exc)
        tell(line, "a button or timer")
        if sys.stderr is not None:
            traceback.print_exception(exc_type, exc, tb)

    def thread_error(args):
        if args.exc_type is SystemExit:
            return
        where = f"background work ({getattr(args.thread, 'name', 'thread')})"
        line = record(where, args.exc_value)
        tell(line, "background work")
        if sys.stderr is not None:
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    root.report_callback_exception = tk_error
    threading.excepthook = thread_error
