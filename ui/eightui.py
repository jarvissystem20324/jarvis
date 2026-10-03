"""The window's side of 8.0: hidden boxes for secrets, hands-free talk, the
animated avatar, the welcome tour, screenshot-and-annotate, and the reminder
items that do work when they fire.

A mixin for JarvisApp, kept out of app.py (already the longest file). Every
method here runs on the Tk thread unless it says otherwise; work that waits
on the network or the microphone runs on a worker and comes back through
safe_after.
"""

from __future__ import annotations

import math
import os
import re
import sys
import threading
import time
import tkinter
from pathlib import Path

import customtkinter as ctk

from jarvis import eight

STOP_LISTENING = re.compile(r"\b(stop listening|stop hands[- ]free|that'?s all|goodbye jarvis|dinlemeyi bırak|görüşürüz)\b", re.I)
TOUR = [
    ("Welcome to JARVIS 9.0", "Type or talk to me like a person. Most things don't need a command:\n"
     "“pause music”, “remind me every day at 9 to take vitamins”, “gold price”, “flip a coin”."),
    ("New: the Design page", "🖌 Design in the sidebar: slides, posters, thumbnails, logos, cards, menus, invitations\n"
     "and diagrams. Drag things around, or ask: “make the title bigger”. Try ▦ Templates or AI → Describe it."),
    ("Make things", "Slides, CVs, cover letters, dilekçe, invoices, mind maps, flowcharts, memes and websites.\n"
     "Try: “make a presentation about renewable energy”."),
    ("Study", "Quizzes, flashcards with spaced review, a language tutor, exact algebra, dictionary and Wikipedia.\n"
     "Try: /quiz photosynthesis   ·   /solve x^2-5x+6=0   ·   /tutor spanish A2"),
    ("Your day", "A to-do list, repeating and medicine reminders, a calendar, prayer times, earthquakes, gold, crypto,\n"
     "the news and alerts when a price crosses a line. Try: “what's on my list”."),
    ("Your PC and safety", "Duplicates, PDF tools, conversions, startup apps, dark mode, AI wallpapers, screen time;\n"
     "password and link checks, 2FA codes and file encryption. Secrets go in hidden boxes, never the chat."),
    ("Talk to me", "Press 🎧 Hands-free and just talk; say “stop listening” to end. /persona coach changes how I speak.\n"
     "/help lists everything. This tour: /tour."),
]


def _ui():
    from ui import app

    return app


class EightUI:
    # --- start-up ----------------------------------------------------------------

    def _eight_init(self) -> None:
        self._handsfree_on = False
        self._handsfree_status = ""
        from jarvis.config import get_setting

        if sys.platform == "win32" and get_setting("JARVIS_SCREENTIME", "on").lower() not in {"off", "false", "0"}:
            from jarvis.pctools import screen_time

            screen_time.start()
        self.after(120, self._avatar_tick)
        self.after(1200, self._maybe_tour)

    def _eight_close(self) -> None:
        self._handsfree_on = False
        try:
            from jarvis.pctools import screen_time

            screen_time.stop()
        except Exception:
            pass

    # --- the avatar ----------------------------------------------------------------

    def _avatar_build(self, parent) -> None:
        colors = _ui().COLORS
        self._avatar = tkinter.Canvas(parent, width=52, height=52, bg=colors["panel"], highlightthickness=0, bd=0)
        self._avatar.pack(side="left", padx=(0, 10))
        self._avatar_phase = 0.0

    def _avatar_state(self) -> str:
        try:
            if getattr(self, "_recording", False) or getattr(self, "_handsfree_status", "") == "listening":
                return "listening"
            if self.jarvis.voice.speaking():
                return "speaking"
        except Exception:
            pass
        return "thinking" if getattr(self, "_busy", False) else "idle"

    def _avatar_tick(self) -> None:
        canvas = getattr(self, "_avatar", None)
        if canvas is None or not canvas.winfo_exists():
            return
        colors = _ui().COLORS
        state = self._avatar_state()
        self._avatar_phase += 0.12
        p = self._avatar_phase
        canvas.delete("all")
        c, accent = 26, colors["accent"]
        ring = {"listening": "#22c55e", "speaking": accent, "thinking": "#f59e0b"}.get(state, accent)
        glow = 3 + (math.sin(p * (0.6 if state == "idle" else 1.6)) + 1) * (2 if state == "idle" else 3.5)
        canvas.create_oval(c - 18 - glow, c - 18 - glow, c + 18 + glow, c + 18 + glow, outline=ring, width=1)
        canvas.create_oval(c - 18, c - 18, c + 18, c + 18, outline=ring, width=2, fill=colors["bg"])
        if state == "thinking":
            canvas.create_arc(c - 13, c - 13, c + 13, c + 13, start=(p * 120) % 360, extent=110, style="arc", outline=ring, width=3)
        elif state in {"speaking", "listening"}:
            for i in range(5):
                height = 4 + abs(math.sin(p * 2.2 + i * 0.9)) * (11 if state == "speaking" else 7)
                x = c - 10 + i * 5
                canvas.create_line(x, c - height / 2, x, c + height / 2, fill=ring, width=3, capstyle="round")
        else:
            r = 6 + math.sin(p * 0.6) * 1.2
            canvas.create_oval(c - r, c - r, c + r, c + r, fill=accent, outline="")
        self.after(60 if state != "idle" else 110, self._avatar_tick)

    # --- secrets --------------------------------------------------------------------

    def _ask_value(self, prompt: str, hide: bool, on_value) -> None:
        colors = _ui().COLORS
        dialog = ctk.CTkToplevel(self)
        dialog.title("JARVIS")
        dialog.geometry("440x170")
        dialog.transient(self)
        dialog.configure(fg_color=colors["panel"])
        ctk.CTkLabel(dialog, text=prompt, text_color=colors["text"], wraplength=400).pack(pady=(18, 4))
        ctk.CTkLabel(dialog, text="Stays on this PC; never shown in the chat.", font=ctk.CTkFont(size=11),
                     text_color=colors["muted"]).pack()
        entry = ctk.CTkEntry(dialog, show="•" if hide else "", width=360)
        entry.pack(pady=8)
        result = {"sent": False}

        def done(_event=None):
            result["sent"] = True
            value = entry.get()
            dialog.destroy()
            on_value(value)

        def cancel(_event=None):
            dialog.destroy()
            if not result["sent"]:
                on_value(None)

        entry.bind("<Return>", done)
        dialog.bind("<Escape>", cancel)
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.after(150, lambda: (dialog.lift(), dialog.grab_set(), entry.focus_set()))
        self._last_secret_dialog = (dialog, entry, done)

    def _secret_flow(self, prompts, finish) -> None:
        values: list[str] = []
        app = _ui()

        def run():
            self._set_busy(True, "Working…")

            def work():
                try:
                    reply = finish(values)
                except Exception as exc:
                    reply = f"Error: {exc}"
                finally:
                    values.clear()       # don't keep a password around longer than the call

                def show():
                    self._set_busy(False)
                    self._append_message("JARVIS", reply, is_user=False, record=False)

                app.safe_after(self, show)

            threading.Thread(target=work, daemon=True).start()

        def next_prompt(index: int):
            if index >= len(prompts):
                run()
                return
            question, hide = prompts[index]

            def got(value):
                if value is None:
                    self._append_message("JARVIS", "Cancelled.", is_user=False, record=False)
                    return
                values.append(value)
                next_prompt(index + 1)

            self._ask_value(question, hide, got)

        next_prompt(0)

    # --- commands only the window can do --------------------------------------------------

    def _eight_ui_command(self, name: str, args: str) -> str | None:
        if name in {"handsfree", "conversation"}:
            word = args.strip().lower()
            wanted = {"on": True, "off": False}.get(word, not self._handsfree_on)
            return self._set_handsfree(wanted)
        if name in {"snip", "screenshot"}:
            self.after(50, self._snip)
            return "Drag a box around what you want. Escape cancels."
        if name == "tour":
            self.after(50, lambda: self._tour(force=True))
            return "Here's the tour."
        return None

    # --- hands-free ---------------------------------------------------------------------

    def _set_handsfree(self, on: bool) -> str:
        voice = self.jarvis.voice
        if on and not voice.mic_available():
            return "No microphone found."
        if on and not voice.stt_available():
            return "Nothing can turn speech into text yet — add a free GROQ_API_KEY in /keys."
        if on == self._handsfree_on:
            return f"Hands-free is already {'on' if on else 'off'}."
        self._handsfree_on = on
        button = getattr(self, "_handsfree_button", None)
        if button is not None:
            button.configure(text="🎧 Listening…" if on else "🎧 Hands-free")
        if on:
            self._handsfree_voice = self.jarvis.voice_enabled
            self.jarvis.voice_enabled = True
            threading.Thread(target=self._handsfree_loop, daemon=True).start()
            return "🎧 Hands-free on — just talk. I'll answer out loud and listen again. Say “stop listening” to end."
        self.jarvis.voice_enabled = getattr(self, "_handsfree_voice", self.jarvis.voice_enabled)
        self._handsfree_status = ""
        return "Hands-free off."

    def _handsfree_loop(self) -> None:
        app = _ui()
        voice = self.jarvis.voice
        while self._handsfree_on:
            while self._handsfree_on and (self._busy or voice.speaking()):
                time.sleep(0.2)
            if not self._handsfree_on:
                break
            self._handsfree_status = "listening"
            try:
                heard = voice.listen()
            except Exception as exc:
                self._handsfree_status = ""
                app.safe_after(self, lambda e=exc: (self._append_message("JARVIS", f"Hands-free stopped: {e}", is_user=False,
                                                                          record=False), self._set_handsfree(False)))
                return
            self._handsfree_status = ""
            if not self._handsfree_on or not heard or not heard.strip():
                continue
            if STOP_LISTENING.search(heard):
                app.safe_after(self, lambda: self._append_message("JARVIS", self._set_handsfree(False), is_user=False, record=False))
                return
            app.safe_after(self, lambda h=heard.strip(): self._run_text(h))
            time.sleep(0.8)          # let the request start before checking _busy again

    # --- screenshot and annotate ----------------------------------------------------------

    def _snip(self) -> None:
        from PIL import ImageGrab, ImageTk

        self.withdraw()
        self.update()
        time.sleep(0.25)
        shot = ImageGrab.grab(all_screens=True)
        try:
            import ctypes

            left, top = ctypes.windll.user32.GetSystemMetrics(76), ctypes.windll.user32.GetSystemMetrics(77)
        except Exception:
            left, top = 0, 0
        overlay = tkinter.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.geometry(f"{shot.width}x{shot.height}+{left}+{top}")
        photo = ImageTk.PhotoImage(shot.point(lambda v: int(v * 0.6)))
        canvas = tkinter.Canvas(overlay, width=shot.width, height=shot.height, highlightthickness=0, cursor="crosshair")
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        canvas.create_text(shot.width // 2, 40, text="Drag a box to capture  ·  Esc cancels", fill="white",
                           font=("Segoe UI", 16, "bold"))
        state = {"start": None, "rect": None}

        def finish(box=None):
            overlay.destroy()
            self.deiconify()
            self.lift()
            if box:
                self._annotate(shot.crop(box))

        def press(e):
            state["start"] = (e.x, e.y)
            state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#22d3ee", width=2)

        def drag(e):
            if state["rect"] is not None:
                canvas.coords(state["rect"], *state["start"], e.x, e.y)

        def release(e):
            if state["start"] is None:
                return
            x0, y0 = state["start"]
            box = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
            finish(box if box[2] - box[0] > 8 and box[3] - box[1] > 8 else None)

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", release)
        overlay.bind("<Escape>", lambda _e: finish(None))
        overlay.focus_force()

    def _annotate(self, image) -> None:
        from PIL import ImageDraw, ImageTk

        from jarvis import drawing, kit

        colors = _ui().COLORS
        window = ctk.CTkToplevel(self)
        window.title("JARVIS — annotate")
        window.configure(fg_color=colors["bg"])
        scale = min(1.0, 1100 / image.width, 680 / image.height)
        shown = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        photo = ImageTk.PhotoImage(shown)
        tools = {"tool": "pen", "color": "#ef4444"}
        ops: list[dict] = []
        bar = ctk.CTkFrame(window, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=8)
        canvas = tkinter.Canvas(window, width=shown.width, height=shown.height, highlightthickness=0, cursor="pencil")
        canvas.pack(padx=10, pady=(0, 10))
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        current: dict = {}

        def pick(tool):
            tools["tool"] = tool

        for label, tool in (("✏ Pen", "pen"), ("▭ Box", "box"), ("➜ Arrow", "arrow"), ("T Text", "text"), ("▮ Highlight", "mark")):
            ctk.CTkButton(bar, text=label, width=0, height=28, command=lambda t=tool: pick(t)).pack(side="left", padx=3)
        for color in ("#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#111827"):
            ctk.CTkButton(bar, text="", width=24, height=24, fg_color=color, hover_color=color,
                          command=lambda c=color: tools.update(color=c)).pack(side="left", padx=2)

        def press(e):
            x, y = e.x / scale, e.y / scale
            if tools["tool"] == "text":
                def put(value):
                    if value:
                        ops.append({"tool": "text", "xy": (x, y), "text": value, "color": tools["color"]})
                        canvas.create_text(e.x, e.y, text=value, fill=tools["color"], anchor="nw", font=("Segoe UI", 14, "bold"))
                self._ask_value("Text to add:", False, put)
                return
            current.clear()
            current.update(tool=tools["tool"], color=tools["color"], points=[(x, y)], item=None)

        def move(e):
            if not current:
                return
            x, y = e.x / scale, e.y / scale
            if current["tool"] == "pen":
                last = current["points"][-1]
                canvas.create_line(last[0] * scale, last[1] * scale, e.x, e.y, fill=current["color"], width=3, capstyle="round")
                current["points"].append((x, y))
            else:
                if current["item"]:
                    canvas.delete(current["item"])
                x0, y0 = current["points"][0]
                if current["tool"] == "arrow":
                    current["item"] = canvas.create_line(x0 * scale, y0 * scale, e.x, e.y, fill=current["color"], width=4, arrow="last",
                                                         arrowshape=(16, 20, 6))
                else:
                    current["item"] = canvas.create_rectangle(x0 * scale, y0 * scale, e.x, e.y, outline=current["color"], width=3,
                                                              fill=current["color"] if current["tool"] == "mark" else "",
                                                              stipple="gray25" if current["tool"] == "mark" else "")
                current["end"] = (x, y)

        def release(_e):
            if current:
                ops.append(dict(current))
                current.clear()

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", release)

        def render():
            out = image.convert("RGBA")
            layer = ImageDraw.Draw(out, "RGBA")
            for op in ops:
                color = op["color"]
                if op["tool"] == "pen" and len(op["points"]) > 1:
                    layer.line(op["points"], fill=color, width=max(3, int(3 / scale)), joint="curve")
                elif op["tool"] in {"box", "mark"} and op.get("end"):
                    box = [min(op["points"][0][0], op["end"][0]), min(op["points"][0][1], op["end"][1]),
                           max(op["points"][0][0], op["end"][0]), max(op["points"][0][1], op["end"][1])]
                    if op["tool"] == "mark":
                        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
                        layer.rectangle(box, fill=rgb + (90,))
                    else:
                        layer.rectangle(box, outline=color, width=max(3, int(3 / scale)))
                elif op["tool"] == "arrow" and op.get("end"):
                    (x0, y0), (x1, y1) = op["points"][0], op["end"]
                    width = max(4, int(4 / scale))
                    layer.line([(x0, y0), (x1, y1)], fill=color, width=width)
                    angle = math.atan2(y1 - y0, x1 - x0)
                    head = 18 / scale
                    layer.polygon([(x1, y1), (x1 - head * math.cos(angle - 0.4), y1 - head * math.sin(angle - 0.4)),
                                   (x1 - head * math.cos(angle + 0.4), y1 - head * math.sin(angle + 0.4))], fill=color)
                elif op["tool"] == "text":
                    layer.text(op["xy"], op["text"], fill=color, font=drawing.font(max(14, int(19 / scale)), True))
            return out.convert("RGB")

        def save():
            path = kit.output_dir("images") / f"snip_{kit.stamp()}.png"
            render().save(path)
            self.current_image = path
            self.jarvis.current_image = path
            window.destroy()
            self._append_message("JARVIS", f"Saved {path}\nAsk about it (“what's in this picture?”) or /meme it.",
                                 is_user=False, record=False)

        def copy():
            try:
                import io

                import win32clipboard

                buffer = io.BytesIO()
                render().save(buffer, "BMP")
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, buffer.getvalue()[14:])
                finally:
                    win32clipboard.CloseClipboard()
                copy_button.configure(text="✓ Copied")
            except Exception as exc:
                copy_button.configure(text=f"Copy failed: {exc}"[:30])

        def undo():
            if ops:
                ops.pop()
                canvas.delete("all")
                canvas.create_image(0, 0, image=photo, anchor="nw")
                redraw()

        def redraw():
            for op in ops:
                if op["tool"] == "pen":
                    pts = [(x * scale, y * scale) for x, y in op["points"]]
                    if len(pts) > 1:
                        canvas.create_line(*[v for p in pts for v in p], fill=op["color"], width=3, capstyle="round")
                elif op["tool"] == "text":
                    canvas.create_text(op["xy"][0] * scale, op["xy"][1] * scale, text=op["text"], fill=op["color"],
                                       anchor="nw", font=("Segoe UI", 14, "bold"))
                elif op.get("end"):
                    (x0, y0), (x1, y1) = op["points"][0], op["end"]
                    if op["tool"] == "arrow":
                        canvas.create_line(x0 * scale, y0 * scale, x1 * scale, y1 * scale, fill=op["color"], width=4, arrow="last",
                                           arrowshape=(16, 20, 6))
                    else:
                        canvas.create_rectangle(x0 * scale, y0 * scale, x1 * scale, y1 * scale, outline=op["color"], width=3,
                                                fill=op["color"] if op["tool"] == "mark" else "",
                                                stipple="gray25" if op["tool"] == "mark" else "")

        ctk.CTkButton(bar, text="↶ Undo", width=0, height=28, fg_color="transparent", command=undo).pack(side="left", padx=(12, 3))
        ctk.CTkButton(bar, text="💾 Save", width=0, height=28, command=save).pack(side="right", padx=3)
        copy_button = ctk.CTkButton(bar, text="⧉ Copy", width=0, height=28, command=copy)
        copy_button.pack(side="right", padx=3)
        window.bind("<Control-z>", lambda _e: undo())
        window.bind("<Control-s>", lambda _e: save())
        window.after(150, window.lift)

    # --- the welcome tour --------------------------------------------------------------------

    def _maybe_tour(self) -> None:
        from jarvis.config import get_data_dir

        if not (get_data_dir() / ".toured").exists() and os.environ.get("JARVIS_TOUR", "on").lower() != "off":
            self._tour()

    def _tour(self, force: bool = False) -> None:
        from jarvis.config import get_data_dir

        colors = _ui().COLORS
        window = ctk.CTkToplevel(self)
        window.title("JARVIS — welcome")
        window.geometry("620x330")
        window.transient(self)
        window.configure(fg_color=colors["panel"])
        page = {"n": 0}
        title = ctk.CTkLabel(window, text="", font=ctk.CTkFont(size=20, weight="bold"), text_color=colors["accent"])
        title.pack(pady=(28, 10))
        body = ctk.CTkLabel(window, text="", wraplength=560, justify="center", text_color=colors["text"],
                            font=ctk.CTkFont(size=14))
        body.pack(padx=24, pady=6, fill="both", expand=True)
        dots = ctk.CTkLabel(window, text="", text_color=colors["muted"])
        dots.pack()
        row = ctk.CTkFrame(window, fg_color="transparent")
        row.pack(pady=16)

        def close():
            try:
                (get_data_dir() / ".toured").write_text("8.0", encoding="utf-8")
            except OSError:
                pass
            window.destroy()

        def show():
            heading, text = TOUR[page["n"]]
            title.configure(text=heading)
            body.configure(text=text)
            dots.configure(text="  ".join("●" if i == page["n"] else "○" for i in range(len(TOUR))))
            back.configure(state="normal" if page["n"] else "disabled")
            forward.configure(text="Start" if page["n"] == len(TOUR) - 1 else "Next →")

        def step(delta):
            if page["n"] + delta >= len(TOUR):
                close()
                return
            page["n"] = max(0, page["n"] + delta)
            show()

        back = ctk.CTkButton(row, text="← Back", width=90, fg_color="transparent", command=lambda: step(-1))
        back.pack(side="left", padx=6)
        ctk.CTkButton(row, text="Skip", width=70, fg_color="transparent", text_color=colors["muted"], command=close).pack(side="left", padx=6)
        forward = ctk.CTkButton(row, text="Next →", width=110, command=lambda: step(1))
        forward.pack(side="left", padx=6)
        window.bind("<Right>", lambda _e: step(1))
        window.bind("<Left>", lambda _e: step(-1))
        window.bind("<Escape>", lambda _e: close())
        window.protocol("WM_DELETE_WINDOW", close)
        show()
        window.after(200, window.lift)
        self._tour_window = window

    # --- reminder items that do work -------------------------------------------------------------

    def _fire_eight(self, item) -> None:
        app = _ui()

        def work():
            try:
                text = self.jarvis.on_fire(item)
            except Exception:
                text = ""
            if not text:
                return

            def show():
                self._append_message("JARVIS", text, is_user=False, record=False)
                if not os.environ.get("JARVIS_QUIET"):
                    app.notify.toast("JARVIS", text.splitlines()[0][:120])
                    app.notify.flash(self)
                    if self.jarvis.voice_enabled:
                        self.jarvis.voice.speak(text.splitlines()[0])

            app.safe_after(self, show)

        threading.Thread(target=work, daemon=True).start()


FIRE_KINDS = eight.FIRE_KINDS
