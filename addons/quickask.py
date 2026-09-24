"""Quick ask: Ctrl+Alt+Space anywhere opens a small JARVIS box on top.

Ask, read the answer, press Escape, and carry on with what you were doing —
the main window never has to come forward. The exchange is also added to
the conversation, so nothing asked this way is lost.

Registered with RegisterHotKey like the other shortcuts: Windows reports
this one combination and nothing else is watched. Change it with
JARVIS_QUICKASK_HOTKEY (e.g. ctrl+shift+space), or turn it off with
JARVIS_QUICKASK_HOTKEY=off. A locked JARVIS shows its PIN screen instead.
"""

from __future__ import annotations

import threading

from jarvis.addons import Addon, Command
from jarvis.config import IS_WINDOWS, get_setting

DEFAULT = "ctrl+alt+space"
HOTKEY_ID = 9
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def parse_combo(combo: str) -> tuple[int, int] | None:
    mods = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
    modifiers, key = 0, ""
    for part in (p.strip().lower() for p in combo.split("+") if p.strip()):
        if part in mods:
            modifiers |= mods[part]
        else:
            key = part
    if not modifiers or not key:
        return None
    if key == "space":
        return modifiers, 0x20
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x6F + int(key[1:])
    return None


class QuickAsk(Addon):
    name = "quickask"
    version = "1.0"
    description = "A small ask box on top of everything, from a global shortcut."

    def __init__(self):
        self._combo = ""
        self._status = "not started"

    def commands(self):
        return [Command("quickask", self.show, "The quick-ask shortcut", "/quickask")]

    def show(self, ctx, args: str) -> str:
        if not self._combo:
            return f"Quick ask is {self._status}."
        return f"Quick ask: {self._combo.upper()} from anywhere. Status: {self._status}."

    def on_load(self, ctx) -> None:
        if not IS_WINDOWS:
            self._status = "Windows only"
            return
        combo = get_setting("JARVIS_QUICKASK_HOTKEY", DEFAULT).strip().lower()
        if combo in {"", "off", "none", "false"}:
            self._status = "off"
            return
        parsed = parse_combo(combo)
        if parsed is None:
            self._status = f"invalid combination '{combo}'"
            return
        self._combo = combo
        threading.Thread(target=self._listen, args=(ctx, *parsed), daemon=True).start()

    def _listen(self, ctx, modifiers: int, key: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, key):
            self._status = "failed — another program already uses that shortcut"
            return
        self._status = "ready"
        message = wintypes.MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):
                    break
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    window = getattr(ctx.jarvis, "window", None)
                    if window is not None:
                        try:
                            window.after(0, window.quick_ask)
                        except Exception:
                            pass
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._status = "stopped"


ADDON = QuickAsk()
