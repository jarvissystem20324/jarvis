"""Global hotkey — bring JARVIS to the front from anywhere.

Windows uses the Win32 RegisterHotKey API through ctypes: no dependency, no
keyboard hook, and the OS hands us only the one combination we registered.
Ctrl+Alt+J by default.

macOS has no equivalent that works without permission. Watching for a shortcut
system-wide means an input monitor, which macOS gates behind Accessibility —
the same permission a keylogger needs, and the same alarming prompt. So on
macOS this stays off unless you deliberately set JARVIS_HOTKEY in your .env.
A fresh install therefore asks for nothing, and you opt in only if you want it.

Nothing here records what you type. Windows delivers only the registered
combination; the macOS listener matches against that combination and discards
everything else.
"""

from __future__ import annotations

import threading

from jarvis.addons import Addon, Command
from jarvis.config import IS_MACOS, IS_WINDOWS, get_setting

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT, "option": MOD_ALT, "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN, "command": MOD_WIN,
}

WINDOWS_DEFAULT = "ctrl+alt+j"


class GlobalHotkey(Addon):
    name = "hotkey"
    version = "2.0"
    description = "Summons the window with a global keyboard shortcut."

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._combo = ""
        self._status = "not started"

    def commands(self):
        return [Command("hotkey", self.status, "Show the summon shortcut", "/hotkey")]

    def status(self, ctx, args: str) -> str:
        if not self._combo:
            if IS_MACOS:
                return (
                    "No summon shortcut is set.\n\n"
                    "On macOS this is off by default, because watching for a "
                    "shortcut system-wide needs Accessibility permission — the "
                    "same one a keylogger asks for. To enable it, add a line "
                    "like this to your .env and restart:\n"
                    "    JARVIS_HOTKEY=cmd+shift+j\n\n"
                    "macOS will then ask you to allow JARVIS under\n"
                    "System Settings > Privacy & Security > Accessibility."
                )
            return "No summon shortcut is configured (set JARVIS_HOTKEY in .env)."
        return (
            f"Summon shortcut: {self._combo}\nStatus: {self._status}\n"
            "Change it with JARVIS_HOTKEY in .env, e.g. JARVIS_HOTKEY=ctrl+alt+space"
        )

    # --- setup ------------------------------------------------------------

    def on_load(self, ctx) -> None:
        # Windows keeps its long-standing default; macOS requires opting in.
        default = WINDOWS_DEFAULT if IS_WINDOWS else ""
        combo = get_setting("JARVIS_HOTKEY", default).strip()
        if not combo:
            self._status = "disabled (no JARVIS_HOTKEY set)"
            return

        self._combo = combo.lower()
        if IS_WINDOWS:
            self._start_windows(ctx)
        elif IS_MACOS:
            self._start_macos(ctx)
        else:
            self._status = "unsupported on this platform"

    # --- Windows ----------------------------------------------------------

    def _start_windows(self, ctx) -> None:
        parsed = self._parse_windows(self._combo)
        if parsed is None:
            self._status = f"invalid combination '{self._combo}'"
            return
        modifiers, key = parsed
        # Daemon thread: the message loop must not keep the app alive on exit.
        self._thread = threading.Thread(
            target=self._listen_windows, args=(ctx, modifiers, key), daemon=True
        )
        self._thread.start()

    @staticmethod
    def _parse_windows(combo: str):
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

    def _listen_windows(self, ctx, modifiers: int, key: int) -> None:
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
            while True:
                # GetMessageW returns 0 for WM_QUIT and -1 on error. Treating
                # -1 as a message would spin this thread at 100% CPU forever.
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):
                    break
                if message.message == WM_HOTKEY:
                    self._summon(ctx)
        finally:
            user32.UnregisterHotKey(None, 1)
            self._status = "stopped"

    # --- macOS ------------------------------------------------------------

    def _start_macos(self, ctx) -> None:
        try:
            from pynput import keyboard  # noqa: F401
        except Exception:
            self._status = "needs pynput — install it with: pip install pynput"
            return

        combo = self._parse_macos(self._combo)
        if combo is None:
            self._status = f"invalid combination '{self._combo}'"
            return

        self._thread = threading.Thread(
            target=self._listen_macos, args=(ctx, combo), daemon=True
        )
        self._thread.start()

    @staticmethod
    def _parse_macos(combo: str) -> str | None:
        """Translate our combo syntax into pynput's GlobalHotKeys format."""
        names = {
            "ctrl": "<ctrl>", "control": "<ctrl>",
            "alt": "<alt>", "option": "<alt>",
            "shift": "<shift>",
            "cmd": "<cmd>", "command": "<cmd>", "win": "<cmd>", "super": "<cmd>",
            "space": "<space>", "enter": "<enter>", "tab": "<tab>",
            "escape": "<esc>",
        }
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        if len(parts) < 2:
            return None

        out = []
        for part in parts:
            if part in names:
                out.append(names[part])
            elif len(part) == 1:
                out.append(part)
            elif part.startswith("f") and part[1:].isdigit():
                out.append(f"<{part}>")
            else:
                return None
        return "+".join(out)

    def _listen_macos(self, ctx, combo: str) -> None:
        from pynput import keyboard

        try:
            with keyboard.GlobalHotKeys({combo: lambda: self._summon(ctx)}) as listener:
                self._status = "listening"
                listener.join()
        except Exception as exc:
            # Almost always a denied Accessibility permission.
            self._status = (
                f"not permitted ({type(exc).__name__}). Allow JARVIS under "
                "System Settings > Privacy & Security > Accessibility, then restart."
            )

    # --- shared -----------------------------------------------------------

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
