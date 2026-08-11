"""Global hotkey — bring JARVIS to the front from anywhere.

Ctrl+Alt+J by default. Uses the Win32 RegisterHotKey API through ctypes, so
there's no extra dependency and no keyboard hook that antivirus software might
object to. Only the chosen combination is ever received; this cannot see any
other keystroke.

Windows only. On anything else the addon loads and does nothing.
"""

from __future__ import annotations

import sys
import threading

from jarvis.addons import Addon, Command
from jarvis.config import get_setting

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT, "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN,
}


class GlobalHotkey(Addon):
    name = "hotkey"
    version = "1.0"
    description = "Summons the window with a global keyboard shortcut."

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._combo = ""
        self._status = "not started"

    def commands(self):
        return [Command("hotkey", self.status, "Show the summon shortcut", "/hotkey")]

    def status(self, ctx, args: str) -> str:
        if not sys.platform.startswith("win"):
            return "Global hotkeys are Windows-only, so this addon is idle."
        return (
            f"Summon shortcut: {self._combo or 'none'}\nStatus: {self._status}\n"
            "Change it with JARVIS_HOTKEY in .env, e.g. JARVIS_HOTKEY=ctrl+alt+space"
        )

    # --- setup ------------------------------------------------------------

    def on_load(self, ctx) -> None:
        if not sys.platform.startswith("win"):
            self._status = "inactive (not Windows)"
            return

        combo = get_setting("JARVIS_HOTKEY", "ctrl+alt+j")
        parsed = self._parse(combo)
        if parsed is None:
            self._status = f"invalid combination '{combo}'"
            return

        self._combo = combo.lower()
        modifiers, key = parsed
        # Daemon thread: the message loop must not keep the app alive on exit.
        self._thread = threading.Thread(
            target=self._listen, args=(ctx, modifiers, key), daemon=True
        )
        self._thread.start()

    @staticmethod
    def _parse(combo: str):
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        if not parts:
            return None

        modifiers = 0
        key_name = ""
        for part in parts:
            if part in MODIFIERS:
                modifiers |= MODIFIERS[part]
            else:
                key_name = part

        if not modifiers or not key_name:
            return None

        if len(key_name) == 1:
            return modifiers, ord(key_name.upper())
        specials = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B}
        if key_name in specials:
            return modifiers, specials[key_name]
        if key_name.startswith("f") and key_name[1:].isdigit():
            number = int(key_name[1:])
            if 1 <= number <= 24:
                return modifiers, 0x6F + number
        return None

    # --- message loop -----------------------------------------------------

    def _listen(self, ctx, modifiers: int, key: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # RegisterHotKey binds to the calling thread, so the message pump has
        # to live in this same thread.
        if not user32.RegisterHotKey(None, 1, modifiers, key):
            self._status = "failed — another program already owns that shortcut"
            return

        self._status = "listening"
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
                if message.message == WM_HOTKEY:
                    self._summon(ctx)
        finally:
            user32.UnregisterHotKey(None, 1)
            self._status = "stopped"

    @staticmethod
    def _summon(ctx) -> None:
        """Ask the UI to show itself. Ignored by the CLI, which has no window."""
        window = getattr(ctx.jarvis, "window", None)
        if window is None:
            return
        try:
            # Must happen on the Tk thread.
            window.after(0, window.summon)
        except Exception:
            pass


ADDON = GlobalHotkey()
