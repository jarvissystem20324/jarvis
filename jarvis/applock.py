"""App lock: a PIN to open JARVIS, and an automatic lock when idle.

The PIN is never stored. What is kept is a PBKDF2-SHA256 hash with a random
salt and 300,000 iterations, so the file does not reveal the PIN and
guessing it offline is slow. Wrong attempts are rate limited: after five,
each further try waits longer.

This keeps someone at your desk out of your conversations. It is not disk
encryption — that is what the vault (your Windows login) is for — and a
forgotten PIN is reset by deleting data/lock.json, which anyone with access
to your files could also do. Said plainly so it is not mistaken for more.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from .config import get_data_dir, get_setting

FILE = "lock.json"
ITERATIONS = 300_000
MIN_LENGTH = 4


def _path():
    return get_data_dir() / FILE


def _hash(pin: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations).hex()


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled() -> bool:
    return bool(_load().get("hash"))


def set_pin(pin: str) -> str:
    pin = pin.strip()
    if len(pin) < MIN_LENGTH or not pin.isdigit():
        return f"A PIN is {MIN_LENGTH} or more digits."
    salt = os.urandom(16)
    _path().write_text(json.dumps({
        "salt": salt.hex(), "hash": _hash(pin, salt), "iterations": ITERATIONS,
        "failures": 0, "locked_until": 0,
    }), encoding="utf-8")
    return "PIN set. JARVIS asks for it when it opens and after it has been idle."


def remove() -> None:
    _path().unlink(missing_ok=True)


def wait_seconds() -> float:
    return max(0.0, float(_load().get("locked_until") or 0) - time.time())


def check(pin: str) -> bool:
    data = _load()
    if not data.get("hash"):
        return True
    if wait_seconds() > 0:
        return False
    expected = _hash(pin.strip(), bytes.fromhex(data["salt"]), int(data.get("iterations") or ITERATIONS))
    ok = hmac.compare_digest(expected, data["hash"])
    data["failures"] = 0 if ok else int(data.get("failures") or 0) + 1
    if data["failures"] >= 5:
        # 5 wrong: 30s, then 60s, 120s … capped at 15 minutes.
        data["locked_until"] = time.time() + min(900, 30 * 2 ** (data["failures"] - 5))
    _path().write_text(json.dumps(data), encoding="utf-8")
    return ok


def idle_minutes() -> int:
    raw = get_setting("JARVIS_LOCK_IDLE", "10").strip()
    return int(raw) if raw.isdigit() else 10
