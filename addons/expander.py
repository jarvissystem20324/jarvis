"""Text expander: type a shortcut anywhere, press Ctrl+Alt+E, get the full text.

    /expand add addr = Moda Cd. No:12, Kadıköy, İstanbul
    …then in any app: type "addr" and press Ctrl+Alt+E.

No keyboard hook watches what you type: the shortcut is a registered hotkey
(RegisterHotKey, like the others), and only when you press it does JARVIS
select the word before the cursor, look it up and type the expansion in its
place. The clipboard is put back as it was. Change the combination with
JARVIS_EXPAND_HOTKEY, or turn it off with JARVIS_EXPAND_HOTKEY=off.
"""

from __future__ import annotations

import threading
import time

from jarvis.addons import Addon, Command
from jarvis.config import IS_WINDOWS, get_setting

DEFAULT = "ctrl+alt+e"
HOTKEY_ID = 10
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "left": 0x25, "right": 0x27, "c": 0x43}


def _key(code: int, up: bool = False) -> None:
    import ctypes

    ctypes.windll.user32.keybd_event(code, 0, 0x0002 if up else 0, 0)


def _combo(*codes: int) -> None:
    for code in codes:
        _key(code)
    for code in reversed(codes):
        _key(code, up=True)


def _clipboard_text() -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def _set_clipboard(text: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        if text:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def expand_now(lookup) -> bool:
    """Replace the word before the cursor with its expansion. True if it did."""
    import ctypes

    from addons.dictation import type_text

    user32 = ctypes.windll.user32
    deadline = time.time() + 1.5
    while time.time() < deadline and any(user32.GetAsyncKeyState(k) & 0x8000 for k in (0x11, 0x12, 0x10)):
        time.sleep(0.02)                  # wait for Ctrl+Alt to be let go
    try:
        saved = _clipboard_text()
    except Exception:
        saved = ""
    try:
        _set_clipboard("")
        _combo(VK["ctrl"], VK["shift"], VK["left"])
        time.sleep(0.05)
        _combo(VK["ctrl"], VK["c"])
        time.sleep(0.15)
        word = _clipboard_text().strip().lstrip(";").lower()
        expansion = lookup(word) if word else None
        if expansion:
            type_text(expansion)
            return True
        _combo(VK["right"])               # leave the selection as it was
        return False
    finally:
        time.sleep(0.1)
        try:
            _set_clipboard(saved)
        except Exception:
            pass


class Expander(Addon):
    name = "expander"
    version = "1.0"
    description = "Text shortcuts that expand anywhere on a hotkey."

    def __init__(self):
        self._combo = ""
        self._status = "not started"

    def commands(self):
        return [Command("expandkey", self.show, "The text-expander shortcut", "/expandkey")]

    def show(self, ctx, args: str) -> str:
        return f"Text expander: {self._combo.upper() or '-'} ({self._status}). Shortcuts: /expand"

    def on_load(self, ctx) -> None:
        if not IS_WINDOWS:
            self._status = "Windows only"
            return
        combo = get_setting("JARVIS_EXPAND_HOTKEY", DEFAULT).strip().lower()
        if combo in {"", "off", "none", "false"}:
            self._status = "off"
            return
        from addons.quickask import parse_combo

        parsed = parse_combo(combo)
        if parsed is None:
            self._status = f"invalid combination '{combo}'"
            return
        self._combo = combo
        threading.Thread(target=self._listen, args=parsed, daemon=True).start()

    def _listen(self, modifiers: int, key: int) -> None:
        import ctypes
        from ctypes import wintypes

        from jarvis.pctools import EXPANSIONS

        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, key):
            self._status = "failed — another program already uses that shortcut"
            return
        self._status = "ready"
        message = wintypes.MSG()

        def lookup(word: str):
            return EXPANSIONS.load().get(word)

        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) not in (0, -1):
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    threading.Thread(target=expand_now, args=(lookup,), daemon=True).start()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._status = "stopped"


ADDON = Expander()
