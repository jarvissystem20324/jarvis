"""The Code tab for beginners (14.1), laid out like Claude Code's.

One box: "Describe a task or ask a question". Under it, the computer it runs
on and the folder it works in — click the folder and File Explorer's folder
picker opens. Then say what you want and the coding agent does it: it plans,
asks before it changes anything, and /undo puts files back.

The full editor (files, tabs, run, git) is still there: Settings → Advanced
mode → On.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import prefs
from ui.pages.base import Page, label

EXAMPLES = ("Make a to-do list website from scratch", "Now add a dark mode to it",
            "Explain what this project does", "Write tests for the main file")


class SimpleCodePage(Page):
    key = "code"
    title = "Code"
    icon = "⌨"

    def build(self) -> None:
        c = self.colors
        self.folder = prefs.get("code_folder", "")
        column = ctk.CTkFrame(self, fg_color="transparent")
        column.pack(fill="both", expand=True, padx=40, pady=(24, 16))
        self.column = column

        self.log = ctk.CTkTextbox(column, wrap="word", fg_color=c["bg"], text_color=c["text"],
                                  font=ctk.CTkFont(size=14))
        self.log.pack(fill="both", expand=True, pady=(0, 12))
        self._welcome()

        # The box, like Claude Code's: "+", the text, and send.
        box = ctk.CTkFrame(column, fg_color=c["panel"], corner_radius=16, border_width=1,
                           border_color=c["accent_dim"])
        box.pack(fill="x")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkButton(row, text="+", width=34, height=34, font=ctk.CTkFont(size=20), fg_color="transparent",
                      hover_color=c["accent_dim"], text_color=c["text"], command=self._attach).pack(side="left")
        self.entry = ctk.CTkTextbox(row, height=56, wrap="word", fg_color=c["panel"], text_color=c["text"],
                                    border_width=0, font=ctk.CTkFont(size=15))
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", self._enter)
        self.send = ctk.CTkButton(row, text="↵", width=38, height=34, font=ctk.CTkFont(size=16),
                                  fg_color=c["accent_dim"], hover_color=c["accent"], text_color=c["text"],
                                  command=self.submit)
        self.send.pack(side="right")
        self._placeholder()

        chips = ctk.CTkFrame(column, fg_color="transparent")
        chips.pack(fill="x", pady=(8, 0))
        label(chips, "💻  This computer", size=12, muted=True).pack(side="left", padx=(6, 18))
        self.folder_btn = ctk.CTkButton(chips, text="", height=28, width=0, font=ctk.CTkFont(size=12),
                                        fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                                        command=self.choose_folder)
        self.folder_btn.pack(side="left")
        # The agent remembers earlier tasks in this folder; this starts over.
        self.new_btn = ctk.CTkButton(chips, text="＋  New chat", height=28, width=0, font=ctk.CTkFont(size=12),
                                     fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                                     command=self.new_chat)
        self.new_btn.pack(side="left", padx=(12, 0))
        label(chips, "Full editor: Settings → Advanced mode", size=11, muted=True).pack(side="right", padx=6)
        self._show_folder()

    # --- the welcome ----------------------------------------------------------------------
    def _welcome(self) -> None:
        self._write("Code with JARVIS\n\n", "title")
        self._write("1. Click the folder under the box and pick your project — an empty folder is fine.\n"
                    "2. Say what you want — build something from scratch, fix, explain or test.\n"
                    "3. JARVIS shows its plan and asks before changing anything. /undo puts files back.\n"
                    "It remembers what you asked before in this folder, so “now make it blue” works. "
                    "“＋ New chat” starts over.\n\n"
                    "Try: " + " · ".join(f"“{e}”" for e in EXAMPLES) + "\n\n", "muted")

    def _write(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.tag_config("title", foreground=self.colors["accent"])
        self.log.tag_config("muted", foreground=self.colors["muted"])
        self.log.tag_config("you", foreground=self.colors["user"])
        self.log.configure(state="disabled")
        self.log.see("end")

    def _placeholder(self) -> None:
        if not self.entry.get("1.0", "end").strip():
            self.entry.insert("1.0", "Describe a task or ask a question")
            self.entry.configure(text_color=self.colors["muted"])
            self.entry.bind("<FocusIn>", self._clear_placeholder)

    def _clear_placeholder(self, _event=None) -> None:
        if self.entry.cget("text_color") == self.colors["muted"]:
            self.entry.delete("1.0", "end")
            self.entry.configure(text_color=self.colors["text"])

    # --- the folder ------------------------------------------------------------------------
    def _show_folder(self) -> None:
        name = Path(self.folder).name if self.folder else ""
        self.folder_btn.configure(text=f"📁  {name}  ▾" if name else "📁  Choose a folder  ▾")

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose your project folder", parent=self,
                                         initialdir=self.folder or str(Path.home()))
        if chosen:
            self.open_folder(chosen)

    def open_folder(self, folder: str) -> None:
        self.folder = str(Path(folder))
        prefs.set("code_folder", self.folder)
        self._show_folder()
        self.run(lambda: self.app.jarvis.process(f"/project {self.folder}").text,
                 lambda text: self._write(f"📁 {text}\n\n", "muted"))

    def on_show(self) -> None:
        # The agent works on the open project; reopen the remembered one once per session.
        if self.folder and not getattr(self, "_opened", False) and Path(self.folder).is_dir():
            self._opened = True
            self.run(lambda: self.app.jarvis.process(f"/project {self.folder}"))
        self.after(50, self.entry.focus_set)

    def new_chat(self) -> None:
        if not self.folder:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._welcome()
        self.run(lambda: self.app.jarvis.process("/agent forget").text,
                 lambda text: self._write(f"{text}\n\n", "muted"))

    # --- asking --------------------------------------------------------------------------------
    def _attach(self) -> None:
        chosen = filedialog.askopenfilename(title="Add a file to the task", parent=self,
                                            initialdir=self.folder or str(Path.home()))
        if chosen:
            self._clear_placeholder()
            self.entry.insert("end", f" {chosen} ")

    def _enter(self, event):
        if not (event.state & 0x1):        # Shift+Enter makes a new line
            self.submit()
            return "break"
        return None

    def submit(self) -> None:
        self._clear_placeholder()
        task = self.entry.get("1.0", "end").strip()
        if not task:
            return
        if not self.folder:
            self._write("Choose a folder first — click “📁 Choose a folder” under the box.\n\n", "muted")
            self.choose_folder()
            if not self.folder:
                return
        self.entry.delete("1.0", "end")
        self._write(f"You: {task}\n", "you")
        self._write("JARVIS is working on it…\n", "muted")
        self.send.configure(state="disabled")
        # A question about the code is answered; anything else is a job for the agent.
        is_question = task.rstrip().endswith("?") or task.lower().startswith(
            ("what", "why", "how", "where", "explain", "ne ", "neden", "nasıl"))
        jarvis = self.app.jarvis

        def work():
            if task.startswith("/"):
                return jarvis.process(task).text
            if is_question:
                return jarvis.code_question(task)
            return jarvis.process(f"/agent {task}").text

        def done(text):
            self.send.configure(state="normal")
            self._write(f"{text}\n\n")

        def failed(exc):
            self.send.configure(state="normal")
            self._write(f"Something went wrong: {exc}\n\n", "muted")

        self.run(work, done, failed)
