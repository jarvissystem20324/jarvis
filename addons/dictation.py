"""Dictation into any app: hold Ctrl+Alt+D, speak, let go — it types.

Works in Word, Discord, a browser, anywhere a cursor blinks. The shortcut is
registered with Windows' RegisterHotKey, exactly like the summon shortcut,
so nothing watches your keyboard: Windows tells JARVIS about this one
combination and nothing else. While it is held, JARVIS checks only whether
that same key is still down.

What you say is transcribed the same way as push-to-talk in the window —
Groq's Whisper if you have a key (the audio is sent to Groq), or
faster-whisper entirely offline if it is installed. The words are then typed
as keystrokes into whichever window has focus; nothing is pasted, so your
clipboard is left alone. Only the length is written to the audit log.

Windows only. Change the shortcut with JARVIS_DICTATE_HOTKEY in .env, or turn
it off with JARVIS_DICTATE_HOTKEY=off.
"""

from __future__ import annotations

import threading
import time

from jarvis.addons import Addon, Command
from jarvis.config import IS_WINDOWS, get_setting

DEFAULT = "ctrl+alt+d"
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 7
MAX_SECONDS = 60


class Dictation(Addon):
    name = "dictation"
    version = "1.0"
    description = "Hold a shortcut anywhere, speak, and the words are typed."

    def __init__(self):
        self._combo = ""
        self._status = "not started"
        self._busy = False

    def commands(self):
        return [Command("dictate", self.show, "Dictation shortcut and status", "/dictate")]

    def show(self, ctx, args: str) -> str:
        if not IS_WINDOWS:
            return "Dictation into other apps is Windows-only for now."
        if not self._combo:
            return "Dictation is off (JARVIS_DICTATE_HOTKEY=off)."
        return (f"Dictation: hold {self._combo.upper()} anywhere, speak, release.\n"
                f"Status: {self._status}\n"
                "Transcribed like push-to-talk, then typed where your cursor is.")

    def on_load(self, ctx) -> None:
        if not IS_WINDOWS:
            self._status = "Windows only"
            return
        combo = get_setting("JARVIS_DICTATE_HOTKEY", DEFAULT).strip().lower()
        if combo in {"", "off", "none", "false"}:
            self._status = "off"
            return
        parsed = parse_combo(combo)
        if parsed is None:
            self._status = f"invalid combination '{combo}'"
            return
        self._combo = combo
        threading.Thread(target=self._listen, args=(ctx, *parsed), daemon=True).start()

    # --- the shortcut -----------------------------------------------------

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
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID and not self._busy:
                    self._busy = True
                    try:
                        self._dictate(ctx, key)
                    finally:
                        self._busy = False
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._status = "stopped"

    def _dictate(self, ctx, key: int) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        voice = getattr(ctx.jarvis, "voice", None)
        if voice is None or not voice.start_push_to_talk():
            self._status = "no microphone"
            _beep(300, 200)
            return
        self._status = "listening"
        _beep(880, 70)
        started = time.monotonic()
        # Held means recording. Only this one key's state is read.
        while user32.GetAsyncKeyState(key) & 0x8000 and time.monotonic() - started < MAX_SECONDS:
            time.sleep(0.03)
        _beep(660, 70)
        self._status = "transcribing"
        try:
            text = voice.stop_push_to_talk()
        except Exception as exc:
            self._status = f"transcription failed: {str(exc)[:80]}"
            _beep(300, 200)
            return
        if not text:
            self._status = "ready (heard nothing)"
            return
        # Ctrl and Alt still down would turn every typed letter into a shortcut.
        deadline = time.monotonic() + 3
        while any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B)) \
                and time.monotonic() < deadline:
            time.sleep(0.02)
        type_text(text.strip() + " ")
        try:
            from jarvis import security

            security.audit.record("dictation", f"{len(text)} characters typed")
        except Exception:
            pass
        self._status = "ready"


def parse_combo(combo: str) -> tuple[int, int] | None:
    """'ctrl+alt+d' -> (modifier flags, virtual key). Same syntax as JARVIS_HOTKEY.

    Addons are loaded from their files, not imported as a package, so this
    cannot borrow the summon addon's parser.
    """
    mods = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
    modifiers, key = 0, ""
    for part in (p.strip().lower() for p in combo.split("+") if p.strip()):
        if part in mods:
            modifiers |= mods[part]
        else:
            key = part
    if not modifiers or not key:
        return None
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    if key == "space":
        return modifiers, 0x20
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x6F + int(key[1:])
    return None


def _beep(frequency: int, ms: int) -> None:
    try:
        import winsound

        winsound.Beep(frequency, ms)
    except Exception:
        pass


def type_text(text: str) -> int:
    """Type `text` into the focused window as Unicode keystrokes."""
    import ctypes
    from ctypes import wintypes

    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP, INPUT_KEYBOARD = 0x0004, 0x0002, 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _UNION(ctypes.Union):
        # The mouse member is the largest; the union must be its size or
        # SendInput rejects every event with a size mismatch.
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    units = text.encode("utf-16-le")
    codes = [int.from_bytes(units[i:i + 2], "little") for i in range(0, len(units), 2)]
    events = []
    for code in codes:
        if code == 0x0A:           # newline -> Enter
            for flags in (0, KEYEVENTF_KEYUP):
                events.append(INPUT(INPUT_KEYBOARD, _UNION(ki=KEYBDINPUT(0x0D, 0, flags, 0, 0))))
            continue
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            events.append(INPUT(INPUT_KEYBOARD, _UNION(ki=KEYBDINPUT(0, code, flags, 0, 0))))
    if not events:
        return 0
    array = (INPUT * len(events))(*events)
    return ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(INPUT))


ADDON = Dictation()
