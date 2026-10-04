"""The window's side of 10.0: corner notifications, the status bar, the
floating orb, chat styles and your avatar, and shortcuts you can change.

A mixin for JarvisApp, like EightUI. Everything here runs on the Tk thread;
alerts posted from worker threads arrive through safe_after.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter
from pathlib import Path

import customtkinter as ctk

from jarvis import alerts
from jarvis.config import get_setting


def _ui():
    from ui import app

    return app


def setting_on(name: str, default: str = "on") -> bool:
    return get_setting(name, default).strip().lower() not in {"off", "0", "false", "no"}


CHAT_STYLES = {"classic": "Classic", "bubbles": "Bubbles", "compact": "Compact", "terminal": "Terminal"}


def seq_label(sequence: str) -> str:
    """'<Control-K>' → 'Ctrl+Shift+K'."""
    body = sequence.strip("<>")
    parts = body.split("-")
    key = parts[-1]
    mods = parts[:-1]
    names = {"Control": "Ctrl", "Alt": "Alt", "Shift": "Shift"}
    out = [names.get(m, m) for m in mods if m != "Key"]
    if len(key) == 1 and key.isalpha() and key.isupper() and "Shift" not in out:
        out.append("Shift")
    special = {"equal": "=", "plus": "+", "minus": "-", "comma": ",", "0": "0", "space": "Space"}
    out.append(special.get(key, key.upper() if len(key) == 1 else key))
    return "+".join(out)


def event_sequence(event) -> str | None:
    """The Tk binding for a key press, or None for a lone modifier."""
    if event.keysym in {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Win_L", "Win_R"}:
        return None
    ctrl = bool(event.state & 0x4)
    shift = bool(event.state & 0x1)
    alt = bool(event.state & 0x20000) or bool(event.state & 0x8 and sys.platform != "win32")
    key = event.keysym
    mods = []
    if ctrl:
        mods.append("Control")
    if alt:
        mods.append("Alt")
    if len(key) == 1 and key.isalpha():
        key = key.upper() if shift else key.lower()
    elif shift:
        mods.append("Shift")
    if not mods and not key.startswith("F"):
        return None
    return "<" + "-".join(mods + [key]) + ">"


class TenUI:
    # --- start-up --------------------------------------------------------------

    def _ten_init(self) -> None:
        self._toasts: list = []
        self._orb_window = None
        self._alert_listener = lambda alert: _ui().safe_after(self, lambda a=alert: self._on_alert(a))
        alerts.listen(self._alert_listener)
        self._build_statusbar()
        try:
            from jarvis import ten

            ten.start(self.jarvis)
        except Exception:
            pass
        if setting_on("JARVIS_ORB", "off"):
            self.after(800, lambda: self.toggle_orb(True))
        try:
            from ui import hotkeys

            hotkeys.start(self)
        except Exception:
            pass
        start = get_setting("JARVIS_START_PAGE", "chat").strip().lower()
        if start and start != "chat":
            self.after(10, lambda: self._show_tab(start))

    def _ten_close(self) -> None:
        alerts.unlisten(self._alert_listener)
        try:
            from jarvis import ten

            ten.stop()
        except Exception:
            pass
        if self._orb_window is not None:
            try:
                self._orb_window.destroy()
            except Exception:
                pass

    # --- commands the window answers ------------------------------------------

    def _ten_ui_command(self, name: str, args: str) -> str | None:
        from ui.pages import BY_KEY, PAGES

        word = args.strip().lower()
        if name == "orb":
            on = None if word not in {"on", "off"} else word == "on"
            self.toggle_orb(on)
            return "The floating orb is " + ("on — click it to ask, drag it anywhere." if self._orb_window else "off.")
        if name in {"page", "go", "goto"} and word:
            match = next((p for p in PAGES if word in {p.key, p.label.lower()} or p.label.lower().startswith(word)),
                         None)
            if match is None:
                return "No page called that. Pages: " + ", ".join(p.label for p in PAGES)
            self._show_tab(match.key)
            return f"Opened {match.label}."
        if name in BY_KEY and not word and name not in {"chat", "image", "code", "design", "memory", "voice"}:
            self._show_tab(name)
            return f"Opened {BY_KEY[name].label}."
        if name == "tools" and not word:
            self._show_tab("tools")
            return "Every command is on the Tools page — search, then click."
        if name in {"notifications", "alerts"}:
            items = alerts.recent(15)
            if not items:
                return "No notifications yet."
            return "Recent notifications:\n" + "\n".join(
                f"  {time.strftime('%H:%M', time.localtime(a.at))}  {a.title}" + (f" — {a.body}" if a.body else "")
                for a in items)
        if name in {"shortcuts", "keys"} and word in {"edit", "change"}:
            self.open_shortcut_editor()
            return "Opened the shortcut editor."
        if name == "restart":
            self.after(300, self.restart)
            return "Restarting…"
        return None

    # --- corner notifications --------------------------------------------------

    def _on_alert(self, alert) -> None:
        try:
            home = getattr(self, "pages", {}).get("home")
            if home is not None and getattr(home, "_built", False):
                home.refresh_alerts()
        except Exception:
            pass
        if setting_on("JARVIS_TOASTS"):
            self.toast(alert.title, alert.body, alert.page, alert.kind)

    def toast(self, title: str, body: str = "", page: str = "", kind: str = "info", seconds: float = 7.0) -> None:
        """A small card in the corner of the screen that fades away."""
        colors = _ui().COLORS
        self._toasts = [t for t in self._toasts if t.winfo_exists()]
        if len(self._toasts) >= 4:
            try:
                self._toasts.pop(0).destroy()
            except Exception:
                pass
        win = tkinter.Toplevel(self)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.0)
        except tkinter.TclError:
            pass
        width, height = 360, 92
        accent = {"warn": "#fbbf24", "ok": colors["ok"], "error": colors["error"]}.get(kind, colors["accent"])
        frame = tkinter.Frame(win, bg=colors["panel"], highlightthickness=1, highlightbackground=accent)
        frame.pack(fill="both", expand=True)
        tkinter.Frame(frame, bg=accent, width=5).pack(side="left", fill="y")
        inner = tkinter.Frame(frame, bg=colors["panel"])
        inner.pack(side="left", fill="both", expand=True, padx=10, pady=8)
        tkinter.Label(inner, text=title[:80], bg=colors["panel"], fg=colors["text"], anchor="w",
                      font=("Segoe UI", 11, "bold")).pack(fill="x")
        if body:
            tkinter.Label(inner, text=body[:200], bg=colors["panel"], fg=colors["muted"], anchor="w", justify="left",
                          wraplength=width - 50, font=("Segoe UI", 9)).pack(fill="x")
        close = tkinter.Label(frame, text="✕", bg=colors["panel"], fg=colors["muted"], cursor="hand2")
        close.pack(side="right", anchor="n", padx=6, pady=4)
        close.bind("<Button-1>", lambda e: win.destroy())

        def clicked(_e=None):
            win.destroy()
            try:
                self.summon()
                if page:
                    self._show_tab(page)
            except Exception:
                pass

        for widget in (frame, inner, *inner.winfo_children()):
            widget.bind("<Button-1>", clicked)
        self._toasts.append(win)
        self._place_toasts(width, height)

        def fade(step=0):
            try:
                if not win.winfo_exists():
                    return
                if step <= 10:
                    win.attributes("-alpha", step / 10 * 0.96)
                    win.after(25, lambda: fade(step + 1))
            except tkinter.TclError:
                pass

        def leave(step=10):
            try:
                if not win.winfo_exists():
                    return
                if step <= 0:
                    win.destroy()
                    self._place_toasts(width, height)
                    return
                win.attributes("-alpha", step / 10 * 0.96)
                win.after(30, lambda: leave(step - 1))
            except tkinter.TclError:
                pass

        fade()
        win.after(int(seconds * 1000), leave)

    def _place_toasts(self, width: int, height: int) -> None:
        self._toasts = [t for t in self._toasts if t.winfo_exists()]
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except tkinter.TclError:
            return
        top = get_setting("JARVIS_TOAST_CORNER", "bottom").strip().lower() == "top"
        for i, win in enumerate(reversed(self._toasts)):
            x = sw - width - 16
            y = 16 + i * (height + 10) if top else sh - 60 - (i + 1) * (height + 10)
            try:
                win.geometry(f"{width}x{height}+{x}+{y}")
            except tkinter.TclError:
                pass

    # --- status bar ------------------------------------------------------------

    def _build_statusbar(self) -> None:
        colors = _ui().COLORS
        bar = ctk.CTkFrame(self.content, height=24, fg_color=colors["panel"], corner_radius=0)
        self.statusbar = bar
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        for key, page in (("page", ""), ("cpu", "pc"), ("ram", "pc"), ("battery", "pc"), ("net", "pc"),
                          ("clock", "home")):
            lab = ctk.CTkLabel(bar, text="", font=ctk.CTkFont(size=11), text_color=colors["muted"], height=22)
            lab.pack(side="left" if key != "clock" else "right", padx=(10, 4))
            if page:
                lab.bind("<Button-1>", lambda e, p=page: self._show_tab(p))
                lab.configure(cursor="hand2")
            self._status_labels[key] = lab
        self._net_last = None
        if setting_on("JARVIS_STATUSBAR"):
            bar.grid(row=1, column=0, sticky="ew")
            self.after(500, self._statusbar_tick)

    def _statusbar_tick(self) -> None:
        if not self.statusbar.winfo_exists():
            return
        try:
            import psutil

            from ui.pages import BY_KEY

            labels = self._status_labels
            info = BY_KEY.get(getattr(self, "active_tab", "chat"))
            labels["page"].configure(text=f"{info.icon} {info.label}" if info else "")
            labels["cpu"].configure(text=f"CPU {psutil.cpu_percent(None):.0f}%")
            labels["ram"].configure(text=f"RAM {psutil.virtual_memory().percent:.0f}%")
            battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
            if battery is not None:
                plug = "⚡" if battery.power_plugged else "🔋"
                labels["battery"].configure(text=f"{plug} {battery.percent:.0f}%")
            io = psutil.net_io_counters()
            now = time.monotonic()
            if self._net_last is not None:
                then, rx, tx = self._net_last
                span = max(0.1, now - then)
                down = (io.bytes_recv - rx) / span
                up = (io.bytes_sent - tx) / span
                labels["net"].configure(text=f"↓ {_rate(down)}  ↑ {_rate(up)}")
            self._net_last = (now, io.bytes_recv, io.bytes_sent)
            labels["clock"].configure(text=time.strftime("%a %d %b  %H:%M"))
        except Exception:
            pass
        self.after(2000, self._statusbar_tick)

    def set_statusbar(self, on: bool) -> None:
        if on:
            self.statusbar.grid(row=1, column=0, sticky="ew")
            self.after(100, self._statusbar_tick)
        else:
            self.statusbar.grid_remove()

    # --- the floating orb ------------------------------------------------------

    def toggle_orb(self, on: bool | None = None) -> None:
        exists = self._orb_window is not None and self._orb_window.winfo_exists()
        on = (not exists) if on is None else on
        if not on:
            if exists:
                self._orb_window.destroy()
            self._orb_window = None
            return
        if exists:
            return
        from ui.orb import Orb

        colors = _ui().COLORS
        key = "#010203"
        win = tkinter.Toplevel(self)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
            if sys.platform == "win32":
                win.attributes("-transparentcolor", key)
        except tkinter.TclError:
            pass
        win.configure(bg=key)
        size = 96
        orb = Orb(win, size, colors["accent"], key, state=self._avatar_state)
        orb.pack()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = getattr(self, "_orb_pos", (sw - size - 30, sh - size - 120))
        win.geometry(f"{size}x{size}+{x}+{y}")
        drag = {}

        def press(e):
            drag.update(x=e.x_root, y=e.y_root, wx=win.winfo_x(), wy=win.winfo_y(), moved=False)

        def move(e):
            dx, dy = e.x_root - drag.get("x", e.x_root), e.y_root - drag.get("y", e.y_root)
            if abs(dx) + abs(dy) > 3:
                drag["moved"] = True
            win.geometry(f"+{drag.get('wx', 0) + dx}+{drag.get('wy', 0) + dy}")

        def release(_e):
            self._orb_pos = (win.winfo_x(), win.winfo_y())
            if not drag.get("moved"):
                self.quick_ask()

        def menu(e):
            m = tkinter.Menu(win, tearoff=0)
            m.add_command(label="Ask JARVIS…", command=self.quick_ask)
            m.add_command(label="Open JARVIS", command=self.summon)
            m.add_command(label="Talk (push to talk: hold F9)", command=self._listen)
            m.add_separator()
            m.add_command(label="Hide the orb", command=lambda: self.toggle_orb(False))
            m.tk_popup(e.x_root, e.y_root)

        orb.bind("<ButtonPress-1>", press)
        orb.bind("<B1-Motion>", move)
        orb.bind("<ButtonRelease-1>", release)
        orb.bind("<Button-3>", menu)
        self._orb_window = win

    # --- chat styles and avatar -------------------------------------------------

    def chat_style(self) -> str:
        style = get_setting("JARVIS_CHAT_STYLE", "classic").strip().lower()
        return style if style in CHAT_STYLES else "classic"

    def _style_tags(self, textbox) -> None:
        colors = _ui().COLORS
        from ui.orb import _mix

        style = self.chat_style()
        size = getattr(self, "_font_size", 14)
        for tag in ("ubody", "jbody"):
            textbox.tag_config(tag, background="", lmargin1=0, lmargin2=0, rmargin=0, spacing1=0, spacing3=0,
                               font="", foreground="")
        textbox.tag_config("user", justify="left", font="")
        textbox.tag_config("jarvis", font="")
        if style == "bubbles":
            textbox.tag_config("user", justify="right", foreground=colors["user"])
            textbox.tag_config("ubody", background=_mix(colors["panel"], colors["user"], 0.16), lmargin1=160,
                               lmargin2=160, rmargin=12, spacing1=2, spacing3=4)
            textbox.tag_config("jbody", background=_mix(colors["panel"], colors["accent"], 0.07), lmargin1=8,
                               lmargin2=8, rmargin=140, spacing3=4)
        elif style == "compact":
            textbox.tag_config("user", font=("Segoe UI", max(9, size - 3), "bold"))
            textbox.tag_config("jarvis", font=("Segoe UI", max(9, size - 3), "bold"))
            textbox.tag_config("ubody", spacing1=0, spacing3=0, font=("Segoe UI", size - 1))
            textbox.tag_config("jbody", spacing1=0, spacing3=0)
        elif style == "terminal":
            textbox.tag_config("user", foreground=colors["muted"], font=("Consolas", size))
            textbox.tag_config("jarvis", foreground=colors["ok"], font=("Consolas", size, "bold"))
            textbox.tag_config("ubody", font=("Consolas", size), foreground=colors["text"])
            textbox.tag_config("jbody", font=("Consolas", size), foreground=colors["ok"])
        textbox.tag_lower("ubody")
        textbox.tag_lower("jbody")

    def _avatar_image(self):
        """Your picture for the chat, 28 px, or None."""
        cached = getattr(self, "_user_avatar", False)
        if cached is not False:
            return cached
        self._user_avatar = None
        path = get_setting("JARVIS_AVATAR", "").strip().strip('"')
        if path and Path(path).is_file():
            try:
                from PIL import Image, ImageDraw, ImageTk

                with Image.open(path) as im:
                    im = im.convert("RGBA")
                    side = min(im.size)
                    im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                                  (im.width + side) // 2, (im.height + side) // 2)).resize((56, 56))
                mask = Image.new("L", (56, 56), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 55, 55), fill=255)
                im.putalpha(mask)
                self._user_avatar = ImageTk.PhotoImage(im.resize((28, 28), Image.LANCZOS))
            except Exception:
                self._user_avatar = None
        return self._user_avatar

    def _user_name(self) -> str:
        return get_setting("JARVIS_USER_NAME", "").strip() or "You"

    # --- shortcuts ---------------------------------------------------------------

    def shortcut_actions(self) -> list[tuple[str, str, str, object]]:
        """(id, default key, what it does, handler) for every rebindable shortcut."""
        return [
            ("palette", "<Control-k>", "Go to any page or tool", lambda e: self.open_palette()),
            ("clear", "<Control-K>", "Clear the conversation", lambda e: self._run_text("/clear")),
            ("find", "<Control-f>", "Find text in the conversation", lambda e: self._prompt_find()),
            ("focus", "<Control-l>", "Jump to the message box", lambda e: self.chat_input.focus_set()),
            ("mode", "<Control-m>", "Next thinking mode", lambda e: self._cycle_mode()),
            ("coding", "<Control-d>", "Open the Coding page", lambda e: self._show_tab("code")),
            ("export", "<Control-e>", "Export the conversation", lambda e: self._run_text("/export")),
            ("copy", "<Control-C>", "Copy JARVIS's last reply", lambda e: self._copy_last("")),
            ("settings", "<Control-comma>", "Open settings", lambda e: self._open_settings()),
            ("stop", "<Escape>", "Stop the request in flight", lambda e: self._stop()),
            ("attach", "<Control-o>", "Attach a file", lambda e: self._choose_file()),
            ("chats", "<Control-b>", "Show or hide the conversation list", lambda e: self._toggle_chat_list()),
            ("bigger", "<Control-equal>", "Bigger text", lambda e: self._zoom(1)),
            ("smaller", "<Control-minus>", "Smaller text", lambda e: self._zoom(-1)),
            ("reset_zoom", "<Control-Key-0>", "Reset text size", lambda e: self._zoom(0, reset=True)),
            ("mini", "<Control-M>", "Mini mode — small, always on top", lambda e: self._toggle_mini()),
            ("lock", "<Control-L>", "Lock JARVIS", lambda e: self._lock_command("")),
            ("home", "<Control-Key-1>", "Home", lambda e: self._show_tab("home")),
            ("chat", "<Control-Key-2>", "Chat", lambda e: self._show_tab("chat")),
            ("tools", "<Control-Key-3>", "Tools page", lambda e: self._show_tab("tools")),
            ("design", "<Control-Key-4>", "Design page", lambda e: self._show_tab("design")),
            ("code", "<Control-Key-5>", "Coding page", lambda e: self._show_tab("code")),
            ("orb", "<Control-J>", "Floating orb on or off", lambda e: self.toggle_orb()),
        ]

    def shortcut_bindings(self) -> list[tuple[str, str, str, object]]:
        """The actions with the user's own keys applied."""
        from ui import prefs

        own = prefs.get("shortcuts", {}) or {}
        return [(aid, own.get(aid, default), text, handler) for aid, default, text, handler in self.shortcut_actions()]

    def open_shortcut_editor(self) -> None:
        ShortcutEditor(self)

    def restart(self) -> None:
        """Start a fresh JARVIS and close this one (for theme and accent changes)."""
        import subprocess

        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable])
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent.parent / "app.py")])
        except OSError:
            return
        self._on_close()


def _rate(bytes_per_second: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bytes_per_second < 1024 or unit == "GB/s":
            return f"{bytes_per_second:.0f} {unit}" if unit == "B/s" else f"{bytes_per_second:.1f} {unit}"
        bytes_per_second /= 1024
    return ""


class ShortcutEditor(ctk.CTkToplevel):
    """Click Change, press the new keys. Saved at once and live at once."""

    def __init__(self, app):
        super().__init__(app)
        from ui import prefs

        colors = _ui().COLORS
        self.app = app
        self.title("Keyboard shortcuts — JARVIS")
        self.geometry("560x640")
        self.configure(fg_color=colors["bg"])
        self.transient(app)
        ctk.CTkLabel(self, text="Keyboard shortcuts", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=colors["accent"]).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(self, text="Change, then press the keys you want. Esc cancels. Global shortcuts (Ctrl+Alt+…) "
                                "are in Settings.", font=ctk.CTkFont(size=11), text_color=colors["muted"],
                     wraplength=520, justify="left").pack(anchor="w", padx=18)
        body = ctk.CTkScrollableFrame(self, fg_color=colors["panel"])
        body.pack(fill="both", expand=True, padx=14, pady=10)
        self.rows = {}
        for aid, seq, text, _handler in app.shortcut_bindings():
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=text, anchor="w", width=290).pack(side="left", padx=6)
            key = ctk.CTkLabel(row, text=seq_label(seq), width=120, text_color=colors["accent"])
            key.pack(side="left")
            ctk.CTkButton(row, text="Change", width=70, height=26, fg_color=colors["bg"],
                          hover_color=colors["accent_dim"], command=lambda a=aid: self.capture(a)).pack(side="left")
            self.rows[aid] = key
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=14, pady=(0, 12))
        self.note = ctk.CTkLabel(foot, text="", text_color=colors["muted"])
        self.note.pack(side="left")
        ctk.CTkButton(foot, text="Reset all", width=90, fg_color="transparent", hover_color=colors["accent_dim"],
                      command=self.reset).pack(side="right")
        self._waiting = None
        self.bind("<KeyPress>", self._key)
        self.prefs = prefs

    def capture(self, aid: str) -> None:
        self._waiting = aid
        self.rows[aid].configure(text="press keys…")
        self.focus_force()

    def _key(self, event) -> str | None:
        if self._waiting is None:
            return None
        aid = self._waiting
        if event.keysym == "Escape":
            self._waiting = None
            self._refresh()
            return "break"
        seq = event_sequence(event)
        if seq is None:
            return "break"
        clash = next((a for a, s, *_ in self.app.shortcut_bindings() if s == seq and a != aid), None)
        if clash:
            self.note.configure(text=f"{seq_label(seq)} is already used — pick another.")
            return "break"
        own = dict(self.prefs.get("shortcuts", {}) or {})
        own[aid] = seq
        self.prefs.set("shortcuts", own)
        self._waiting = None
        self.app._bind_shortcuts()
        self.note.configure(text=f"Saved: {seq_label(seq)}")
        self._refresh()
        return "break"

    def reset(self) -> None:
        self.prefs.set("shortcuts", {})
        self.app._bind_shortcuts()
        self._refresh()
        self.note.configure(text="Back to the defaults.")

    def _refresh(self) -> None:
        for aid, seq, _text, _h in self.app.shortcut_bindings():
            if aid in self.rows:
                self.rows[aid].configure(text=seq_label(seq))
