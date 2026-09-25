"""Shut down, restart, sleep and lock the PC — always after asking.

Shutdown and restart go through Windows' own `shutdown` timer, so a delayed
one survives JARVIS being closed and Windows shows its usual warning; even
"now" gets a 30-second grace period, so "cancel shutdown" always has a
chance. Sleep in the future is kept on the reminder board, which only fires
while JARVIS is open, and says so.

Nothing here runs under the test suite by accident: JARVIS_POWER_DRYRUN
(set in conftest) turns every action into a log line.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

GRACE_SECONDS = 30
ACTIONS = {"shutdown", "restart", "sleep", "lock", "cancel", "status"}
ALIASES = {
    "shut down": "shutdown", "turn off": "shutdown", "power off": "shutdown", "off": "shutdown",
    "reboot": "restart", "suspend": "sleep", "cancel": "cancel", "abort": "cancel", "kapat": "shutdown",
    "yeniden başlat": "restart", "uyku": "sleep", "kilitle": "lock",
}
dry_log: list[str] = []
_pending: dict = {}   # {"action": "shutdown", "at": epoch}


class PowerError(Exception):
    pass


def _dry() -> bool:
    return os.environ.get("JARVIS_POWER_DRYRUN", "").lower() in {"1", "true", "yes", "on"}


def _run(args: list[str]) -> None:
    if _dry():
        dry_log.append(" ".join(args))
        return
    if sys.platform != "win32":
        raise PowerError("Power controls work on Windows only.")
    result = subprocess.run(args, capture_output=True, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise PowerError((result.stderr or result.stdout or "Windows refused.").strip()[:200])


def schedule(action: str, seconds: float) -> float:
    """Shutdown or restart after `seconds` (at least the grace period)."""
    seconds = max(GRACE_SECONDS, round(seconds))
    flag = "/s" if action == "shutdown" else "/r"
    _run(["shutdown", flag, "/t", str(seconds), "/c", f"JARVIS: {action} requested. Say 'cancel shutdown' to stop it."])
    _pending.update(action=action, at=time.time() + seconds)
    return _pending["at"]


def cancel() -> str:
    if not _pending:
        # Windows may still have one pending from another tool; abort anyway.
        try:
            _run(["shutdown", "/a"])
        except PowerError:
            return "Nothing is scheduled."
        return "Cancelled whatever shutdown Windows had pending."
    action = _pending.get("action", "shutdown")
    _pending.clear()
    if action != "sleep":
        try:
            _run(["shutdown", "/a"])
        except PowerError as exc:
            return f"Windows would not cancel it: {exc}"
    return f"Cancelled the {action}."


def sleep_now() -> None:
    if _dry():
        dry_log.append("sleep")
        return
    if sys.platform != "win32":
        raise PowerError("Power controls work on Windows only.")
    import ctypes

    # SetSuspendState(hibernate=False, force=False, disable_wake=False).
    # (rundll32 powrprof.dll,SetSuspendState hibernates on machines with
    # hibernation on, because rundll32 passes the arguments wrongly.)
    if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
        raise PowerError("Windows would not go to sleep.")


def lock() -> None:
    if _dry():
        dry_log.append("lock")
        return
    if sys.platform != "win32":
        raise PowerError("Power controls work on Windows only.")
    import ctypes

    if not ctypes.windll.user32.LockWorkStation():
        raise PowerError("Windows would not lock.")


def pending() -> dict:
    if _pending and _pending.get("at", 0) < time.time() - 120:
        _pending.clear()
    return dict(_pending)


def parse(text: str) -> tuple[str, str]:
    """'shut down in 30 minutes' -> ('shutdown', 'in 30 minutes')."""
    low = " ".join(text.strip().lower().split())
    for phrase in sorted(ALIASES, key=len, reverse=True):
        if low == phrase or low.startswith(phrase + " "):
            return ALIASES[phrase], low[len(phrase):].strip()
    word, _, rest = low.partition(" ")
    return word, rest.strip()
