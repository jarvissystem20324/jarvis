"""10.0 global shortcuts: the selection assistant and hold-to-talk.

  Ctrl+Alt+R (JARVIS_SELECT_HOTKEY): select text in any app, press it — a
      small box offers Fix, Shorter, Formal, Translate… or a question about the
      text, and Replace puts the result back where it came from.
  Ctrl+Alt+V (JARVIS_PTT_HOTKEY): hold it and speak to JARVIS from anywhere;
      let go and the question goes to the chat.

Registered with RegisterHotKey like the other global shortcuts (no keyboard
hook), each on its own thread. "off" disables either one.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter

import customtkinter as ctk

from jarvis.config import get_setting

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
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit():
        return modifiers, 0x6F + int(key[1:])
    if key == "space":
        return modifiers, 0x20
    return None


def listen(hotkey_id: int, combo: str, on_press) -> str:
    """Start a thread that calls on_press(vk) (on that thread) for each press."""
    if sys.platform != "win32":
        return "Windows only"
    if combo.strip().lower() in {"", "off", "none", "false"}:
        return "off"
    parsed = parse_combo(combo)
    if parsed is None:
        return f"invalid shortcut {combo!r}"
    status = {"text": "starting"}

    def run():
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        modifiers, key = parsed
        if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, key):
            status["text"] = "taken by another program"
            return
        status["text"] = "ready"
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam == hotkey_id:
                    try:
                        on_press(key)
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    threading.Thread(target=run, daemon=True, name=f"jarvis-hotkey-{hotkey_id}").start()
    return status["text"]


def _key(vk: int, up: bool = False) -> None:
    ctypes.windll.user32.keybd_event(vk, 0, 0x0002 if up else 0, 0)


def release_modifiers() -> None:
    for vk in (0x12, 0x11, 0x10, 0x5B):          # Alt, Ctrl, Shift, Win
        if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
            _key(vk, up=True)


def send_ctrl(letter: str) -> None:
    release_modifiers()
    _key(0x11)
    _key(ord(letter.upper()))
    _key(ord(letter.upper()), up=True)
    _key(0x11, up=True)


def start(app) -> None:
    """Register both shortcuts for this window."""
    from ui.pages.base import safe_after

    def selection(_vk):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        safe_after(app, lambda: SelectionAssistant.open(app, hwnd))

    def talk(vk):
        voice = app.jarvis.voice
        if not voice.start_push_to_talk():
            return
        started = time.monotonic()
        while ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000 and time.monotonic() - started < 60:
            time.sleep(0.03)
        try:
            heard = voice.stop_push_to_talk()
        except Exception:
            heard = None
        if heard:
            safe_after(app, lambda: (app.summon(), app.run_in_chat(heard)))

    app._select_hotkey = listen(41, get_setting("JARVIS_SELECT_HOTKEY", "ctrl+alt+r"), selection)
    app._ptt_hotkey = listen(42, get_setting("JARVIS_PTT_HOTKEY", "ctrl+alt+v"), talk)


class SelectionAssistant(ctk.CTkToplevel):
    """The box Ctrl+Alt+R opens over the app you are working in."""

    current = None

    @classmethod
    def open(cls, app, hwnd: int) -> None:
        if cls.current is not None:
            try:
                cls.current.destroy()
            except tkinter.TclError:
                pass
        try:
            previous = app.clipboard_get()
        except tkinter.TclError:
            previous = ""
        try:
            app.clipboard_clear()
        except tkinter.TclError:
            pass
        send_ctrl("c")

        def read():
            try:
                text = app.clipboard_get()
            except tkinter.TclError:
                text = ""
            if previous and text != previous:
                app.clipboard_clear()
                app.clipboard_append(previous)
            cls.current = cls(app, hwnd, text.strip())

        app.after(220, read)

    def __init__(self, app, hwnd: int, text: str):
        from jarvis.ten.aihelp import REWRITES
        from ui.app import COLORS as c

        super().__init__(app)
        self.app = app
        self.hwnd = hwnd
        self.text = text
        self.result = ""
        self.title("JARVIS — selection")
        self.attributes("-topmost", True)
        self.configure(fg_color=c["panel"])
        x, y = self.winfo_pointerx(), self.winfo_pointery()
        self.geometry(f"520x420+{max(0, x - 260)}+{max(0, y + 20)}")
        self.bind("<Escape>", lambda e: self.destroy())
        if not text:
            ctk.CTkLabel(self, text="Select some text in any app first, then press Ctrl+Alt+R.",
                         text_color=c["muted"]).pack(padx=20, pady=40)
            return
        preview = text if len(text) < 180 else text[:177] + "…"
        ctk.CTkLabel(self, text=f"“{preview}”", wraplength=480, justify="left", text_color=c["muted"],
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(10, 6))
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=10)
        for i, name in enumerate(["fix", "shorter", "longer", "formal", "friendly", "simple", "english", "turkish",
                                  "summary", "reply", "bullets"]):
            ctk.CTkButton(grid, text=name.capitalize(), height=26, width=88, fg_color=c["bg"],
                          hover_color=c["accent_dim"], command=lambda n=name: self.rewrite(REWRITES[n])).grid(
                row=i // 5, column=i % 5, padx=2, pady=2)
        self.question = ctk.CTkEntry(self, placeholder_text="…or ask about it, then Enter", fg_color=c["bg"])
        self.question.pack(fill="x", padx=12, pady=6)
        self.question.bind("<Return>", lambda e: self.ask())
        self.output = ctk.CTkTextbox(self, height=150, wrap="word", fg_color=c["bg"])
        self.output.pack(fill="both", expand=True, padx=12)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)
        self.replace_btn = ctk.CTkButton(row, text="⇩ Replace in the app", fg_color=c["accent_dim"],
                                         hover_color=c["accent"], command=self.replace, state="disabled")
        self.replace_btn.pack(side="left")
        ctk.CTkButton(row, text="⧉ Copy", fg_color="transparent", hover_color=c["accent_dim"],
                      command=self.copy).pack(side="left", padx=6)
        self.after(100, self.question.focus_force)

    def _work(self, fn, can_replace: bool) -> None:
        from ui.pages.base import background

        self.output.delete("1.0", "end")
        self.output.insert("1.0", "Thinking…")

        def done(result):
            self.result = str(result)
            try:
                self.output.delete("1.0", "end")
                self.output.insert("1.0", self.result)
                self.replace_btn.configure(state="normal" if can_replace else "disabled")
            except tkinter.TclError:
                pass

        background(self, fn, done)

    def rewrite(self, instruction: str) -> None:
        self._work(lambda: self.app.jarvis.rewrite_text(self.text, instruction), True)

    def ask(self) -> None:
        question = self.question.get().strip()
        self._work(lambda: self.app.jarvis.ask_about(self.text, question), False)

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.output.get("1.0", "end").strip())

    def replace(self) -> None:
        text = self.output.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        hwnd = self.hwnd
        self.destroy()
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            return
        self.app.after(150, lambda: send_ctrl("v"))
