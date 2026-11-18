"""Upcoming rocket launches: who, what, where and when (in your time).

    /launches     the next 8 launches worldwide

From The Space Devs' public Launch Library (no account, no key; it allows
about 15 requests an hour, so results are kept for 30 minutes).
"""

from __future__ import annotations

import time
from datetime import datetime

from jarvis import kit
from jarvis.addons import Addon, Command

API = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"
KEEP_SECONDS = 1800


class Launches(Addon):
    name = "launches"
    version = "1.0"
    description = "The next rocket launches, in your local time."

    def __init__(self):
        self._cache: tuple[float, list] = (0.0, [])

    def commands(self):
        return [Command("launches", self.launches, "Upcoming rocket launches", "/launches")]

    def upcoming(self) -> list:
        at, rows = self._cache
        if time.time() - at < KEEP_SECONDS and rows:
            return rows
        data = kit.get_json(API, {"limit": 8, "mode": "list"}, timeout=20)
        rows = data.get("results", []) if isinstance(data, dict) else []
        self._cache = (time.time(), rows)
        return rows

    def launches(self, ctx, args: str) -> str:
        try:
            rows = self.upcoming()
        except kit.KitError as exc:
            return f"{exc} (the launch library allows about 15 lookups an hour)"
        if not rows:
            return "🚀 No upcoming launches listed right now."
        lines = ["🚀 Next launches (your local time):"]
        for row in rows:
            try:
                when = datetime.fromisoformat(row["net"].replace("Z", "+00:00")).astimezone()
                stamp = when.strftime("%a %d %b %H:%M")
            except (KeyError, ValueError):
                stamp = row.get("net", "?")
            status = (row.get("status") or {}).get("abbrev", "") if isinstance(row.get("status"), dict) else ""
            place = row.get("location") or (row.get("pad") or {}).get("location", {}).get("name", "")
            lines.append(f"  • {stamp}  {row.get('name', '?')}" + (f"  [{status}]" if status else "")
                         + (f"\n      {place}" if place else ""))
        return "\n".join(lines)


ADDON = Launches()
