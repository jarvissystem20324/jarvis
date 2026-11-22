"""Minimize to tray (14.4).

When the window is minimized, JARVIS leaves the taskbar and waits as an icon
in the system tray (by the clock), still listening for its hotkeys and
reminders. Click the icon to bring it back; right-click for Open and Quit.
Settings → Minimize to tray → Off keeps the old behaviour.
"""

from __future__ import annotations

import threading

from jarvis.config import get_setting

SETTING = "JARVIS_TRAY"


def enabled() -> bool:
    return get_setting(SETTING, "on").strip().lower() not in {"off", "0", "false", "no"}


class Tray:
    """The tray icon. pystray runs it on its own thread; every action is
    handed back to the Tk thread with after(), never run on pystray's."""

    def __init__(self, app):
        self.app = app
        self.icon = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        try:
            import pystray  # noqa: F401
        except Exception:
            return False
        return True

    def show_icon(self) -> bool:
        with self._lock:
            if self.icon is not None:
                return True
            try:
                import pystray

                from ui import logo

                menu = pystray.Menu(
                    pystray.MenuItem("Open JARVIS", self._open, default=True),
                    pystray.MenuItem("Quit", self._quit),
                )
                self.icon = pystray.Icon("JARVIS", logo.make(64), "JARVIS", menu)
                self.icon.run_detached()
                return True
            except Exception:
                self.icon = None
                return False

    def hide_icon(self) -> None:
        with self._lock:
            icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    def _open(self, *_args) -> None:
        self._later(self.app.restore_from_tray)

    def _quit(self, *_args) -> None:
        self._later(self.app.quit_from_tray)

    def _later(self, callback) -> None:
        try:
            self.app.after(0, callback)
        except Exception:
            pass
