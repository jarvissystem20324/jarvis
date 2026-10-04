"""Creator (10.0): a teleprompter, and the tools for planning, writing and
packaging videos and posts — ideas, scripts, hooks, hashtags, threads,
keyword ideas, repurposing a video, the feed preview and stream overlays.
"""

from __future__ import annotations

import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui.pages.base import Hub, button, label, plain


class CreatorPage(Hub):
    key = "creator"
    title = "Creator"
    icon = "📹"
    subtitle = "Plan, write and package your videos and posts — and read your script off a teleprompter."

    def build_body(self) -> None:
        c = self.colors
        prompter = self.card("Teleprompter", "Paste your script, set the speed, press Start. Space pauses, ↑ ↓ "
                                             "change speed, + − change size, Esc closes.", "📜", span=2)
        self.script = ctk.CTkTextbox(prompter.inner, height=150, wrap="word", fg_color=c["bg"])
        self.script.pack(fill="x")
        row = plain(prompter.inner)
        row.pack(fill="x", pady=(8, 0))
        button(row, "▶ Start", self.start, accent=True, height=30).pack(side="left")
        button(row, "Open a file…", self.open_file, height=30).pack(side="left", padx=6)
        label(row, "Speed", size=11, muted=True).pack(side="left", padx=(16, 4))
        self.speed = ctk.CTkSlider(row, from_=1, to=10, number_of_steps=18, width=140)
        self.speed.set(3)
        self.speed.pack(side="left")
        label(row, "Size", size=11, muted=True).pack(side="left", padx=(16, 4))
        self.size = ctk.CTkSlider(row, from_=28, to=96, number_of_steps=34, width=140)
        self.size.set(52)
        self.size.pack(side="left")
        self.note = label(prompter.inner, "", size=11, muted=True)
        self.note.pack(anchor="w", pady=(6, 0))
        self.window: Prompter | None = None

        self.section("Plan and write")
        self.tools("videoideas", "seo", "script", "hooks", "thread", "hashtags", "repurpose")
        self.section("Package")
        self.tools("thumbpreview", "overlays", "thumbnail")

    def open_target(self, part: str) -> None:
        if part == "teleprompter":
            self.after(100, self.script.focus_set)

    def open_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("Scripts", "*.txt *.md *.docx"),
                                                                   ("All files", "*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".docx"):
                import docx

                text = "\n\n".join(p.text for p in docx.Document(path).paragraphs if p.text.strip())
            else:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.note.configure(text=f"Couldn't read it: {exc}")
            return
        self.script.delete("1.0", "end")
        self.script.insert("1.0", text)
        self.note.configure(text=f"Loaded {Path(path).name}.")

    def start(self) -> None:
        text = self.script.get("1.0", "end").strip()
        if not text:
            self.note.configure(text="Paste or open a script first.")
            return
        if self.window is not None:
            self.window.close()
        self.window = Prompter(self.app, text, float(self.speed.get()), int(self.size.get()))


class Prompter(tkinter.Toplevel):
    """Big white text on black, rising at a steady pace past a reading line."""

    FRAME_MS = 33

    def __init__(self, app, text: str, speed: float, size: int) -> None:
        super().__init__(app)
        self.title("Teleprompter — JARVIS")
        self.configure(bg="#000000")
        width, height = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{width}x{height}+0+0")
        try:
            self.attributes("-fullscreen", True)
        except tkinter.TclError:
            pass
        self.speed, self.size, self.paused = speed, size, False
        self.canvas = tkinter.Canvas(self, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.update_idletasks()
        self.w, self.h = self.canvas.winfo_width() or width, self.canvas.winfo_height() or height
        self.reading_line = self.h // 3
        self.canvas.create_line(0, self.reading_line, 40, self.reading_line, fill="#ef4444", width=6)
        self.canvas.create_line(self.w - 40, self.reading_line, self.w, self.reading_line, fill="#ef4444", width=6)
        self.text = self.canvas.create_text(self.w / 2, self.reading_line + 40, text=text, fill="#ffffff",
                                            width=self.w * 0.8, anchor="n", justify="center",
                                            font=("Segoe UI", self.size, "bold"))
        self.hint = self.canvas.create_text(self.w / 2, self.h - 24, fill="#555555", font=("Segoe UI", 12),
                                            text="Space pause · ↑ ↓ speed · + − size · Home restart · Esc close")
        for key, action in (("<space>", self.toggle), ("<Up>", lambda: self.faster(0.5)),
                            ("<Down>", lambda: self.faster(-0.5)), ("<plus>", lambda: self.resize(4)),
                            ("<equal>", lambda: self.resize(4)), ("<minus>", lambda: self.resize(-4)),
                            ("<Home>", self.restart), ("<Escape>", self.close)):
            self.bind(key, lambda e, a=action: a())
        self.focus_force()
        self._job = self.after(1200, self.tick)       # a moment to get ready

    def tick(self) -> None:
        if not self.paused:
            self.canvas.move(self.text, 0, -self.speed)
            bottom = self.canvas.bbox(self.text)[3]
            if bottom < self.reading_line - 40:
                self.paused = True
                self.canvas.itemconfigure(self.hint, text="The end · Home restarts · Esc closes")
        self._job = self.after(self.FRAME_MS, self.tick)

    def toggle(self) -> None:
        self.paused = not self.paused

    def faster(self, step: float) -> None:
        self.speed = max(0.5, min(15.0, self.speed + step))

    def resize(self, step: int) -> None:
        self.size = max(20, min(140, self.size + step))
        self.canvas.itemconfigure(self.text, font=("Segoe UI", self.size, "bold"))

    def restart(self) -> None:
        x, y = self.canvas.coords(self.text)
        self.canvas.move(self.text, 0, self.reading_line + 40 - y)
        self.paused = False
        self.canvas.itemconfigure(self.hint, text="Space pause · ↑ ↓ speed · + − size · Home restart · Esc close")

    def close(self) -> None:
        try:
            self.after_cancel(self._job)
        except (tkinter.TclError, AttributeError):
            pass
        try:
            self.destroy()
        except tkinter.TclError:
            pass
