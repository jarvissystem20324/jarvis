"""The Code tab for beginners (14.1), laid out like Claude Code's.

One box: "Describe a task or ask a question". Under it, the computer it runs
on and the folder it works in — click the folder and File Explorer's folder
picker opens. Then say what you want and the coding agent does it: it plans,
asks before it changes anything, and /undo puts files back.

The full editor (files, tabs, run, git) is still there: Settings → Advanced
mode → On.

14.3: a toolbar at the top right, like Claude Code's — the plan, a terminal,
the changes the agent made, a built-in browser preview, the project's files
with a code viewer, and a ⋯ menu. The panels open on the right of the chat.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import prefs, render
from ui.pages.base import Page, label

EXAMPLES = ("Make a to-do list website from scratch", "Now add a dark mode to it",
            "Explain what this project does", "Write tests for the main file")

# Never listed in the Files panel: tools' folders, not the project's own files.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".idea", ".vscode",
             "dist", "build", ".next", ".cache"}
LANGUAGES = {".py": "py", ".js": "js", ".mjs": "js", ".jsx": "js", ".ts": "ts", ".tsx": "ts", ".sh": "sh",
             ".ps1": "ps1", ".bat": "sh"}
VIEW_LIMIT = 300_000          # bytes shown in the code viewer


class SimpleCodePage(Page):
    key = "code"
    title = "Code"
    icon = "⌨"

    def build(self) -> None:
        c = self.colors
        self.folder = prefs.get("code_folder", "")
        self.panel_view = ""
        column = ctk.CTkFrame(self, fg_color="transparent")
        column.pack(fill="both", expand=True, padx=28, pady=(10, 16))
        self.column = column

        # The toolbar: icon-only, top right.
        bar = ctk.CTkFrame(column, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        self.tool_buttons = {}
        tools = (("plan", "☰", "Plan", lambda: self.toggle_panel("plan")),
                 ("terminal", ">_", "Terminal", self.open_terminal),
                 ("changes", "±", "Changes", lambda: self.toggle_panel("changes")),
                 ("preview", "🌐", "Preview in the built-in browser", self.preview),
                 ("files", "📁", "Files and code", lambda: self.toggle_panel("files")),
                 ("more", "⋯", "More", self.more_menu))
        # Packed from the right, so in reverse to read left to right.
        for key, glyph, tip, command in reversed(tools):
            button = ctk.CTkButton(bar, text=glyph, width=38, height=32, font=ctk.CTkFont(size=15),
                                   fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                                   command=command)
            button.pack(side="right", padx=2)
            _tip(button, tip, c)
            self.tool_buttons[key] = button

        body = ctk.CTkFrame(column, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(0, 12))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.body = body
        self.log = ctk.CTkTextbox(body, wrap="word", fg_color=c["bg"], text_color=c["text"],
                                  font=ctk.CTkFont(size=14))
        self.log.grid(row=0, column=0, sticky="nsew")
        self._welcome()
        self._build_panel()

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
        # 14.3: agent teams — a lead writes, teammates check; models picked for the mode.
        self.team_btn = ctk.CTkButton(chips, text="", height=28, width=0, font=ctk.CTkFont(size=12),
                                      fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                                      command=self.toggle_team)
        self.team_btn.pack(side="left", padx=(12, 0))
        _tip(self.team_btn, "A lead agent writes, teammates check its work", c)
        self._show_team()
        label(chips, "Full editor: Settings → Advanced mode", size=11, muted=True).pack(side="right", padx=6)
        self._show_folder()

    # --- 14.3: the side panel ---------------------------------------------------------------
    def _build_panel(self) -> None:
        c = self.colors
        panel = ctk.CTkFrame(self.body, fg_color=c["panel"], corner_radius=14, width=460)
        panel.grid_propagate(False)
        panel.pack_propagate(False)
        self.panel = panel
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        self.panel_title = label(head, "", size=13, bold=True, text_color=c["text"])
        self.panel_title.pack(side="left")
        ctk.CTkButton(head, text="✕", width=28, height=28, fg_color="transparent", hover_color=c["accent_dim"],
                      text_color=c["muted"], command=self.close_panel).pack(side="right")
        self.refresh_btn = ctk.CTkButton(head, text="⟳", width=28, height=28, fg_color="transparent",
                                         hover_color=c["accent_dim"], text_color=c["muted"],
                                         command=self.refresh_panel)
        self.refresh_btn.pack(side="right")
        self.file_list = ctk.CTkScrollableFrame(panel, fg_color="transparent", height=170)
        self.file_name = label(panel, "", size=11, muted=True, text_color=c["muted"])
        self.viewer = ctk.CTkTextbox(panel, wrap="none", fg_color=c["bg"], text_color=c["text"],
                                     font=ctk.CTkFont(family="Consolas", size=12))
        self.viewer.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        box = getattr(self.viewer, "_textbox", self.viewer)
        render.configure_tags(box, c, 13)
        box.tag_config("code_bg", background=c["bg"], lmargin1=6, lmargin2=6)
        box.tag_config("add", foreground=c.get("ok", "#22c55e"))
        box.tag_config("del", foreground=c.get("error", "#ef4444"))
        box.tag_config("hunk", foreground=c["accent"])
        box.tag_config("muted", foreground=c["muted"])
        self.viewer.configure(state="disabled")

    def toggle_panel(self, view: str) -> None:
        if self.panel_view == view:
            self.close_panel()
        else:
            self.show_panel(view)

    def show_panel(self, view: str) -> None:
        self.panel_view = view
        self.panel.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        for key, button in self.tool_buttons.items():
            button.configure(fg_color=self.colors["accent_dim"] if key == view else "transparent")
        self.refresh_panel()

    def close_panel(self) -> None:
        self.panel_view = ""
        self.panel.grid_remove()
        for button in self.tool_buttons.values():
            button.configure(fg_color="transparent")

    def refresh_panel(self) -> None:
        view = self.panel_view
        self.file_list.pack_forget()
        self.file_name.pack_forget()
        if view == "files":
            self.panel_title.configure(text="Files")
            self.file_list.pack(fill="x", padx=8, pady=(0, 4), before=self.viewer)
            self.file_name.pack(fill="x", padx=14, before=self.viewer)
            self._list_files()
        elif view == "changes":
            self.panel_title.configure(text="Changes")
            self._show_changes()
        elif view == "plan":
            self.panel_title.configure(text="Plan")
            self._show_plan()

    def _agent(self):
        return getattr(getattr(self.app, "jarvis", None), "_agent", None)

    def _view(self, writer) -> None:
        """Replace the viewer's text: writer(textbox) inserts the new content."""
        box = getattr(self.viewer, "_textbox", self.viewer)
        self.viewer.configure(state="normal")
        box.delete("1.0", "end")
        writer(box)
        self.viewer.configure(state="disabled")
        box.see("1.0")

    def project_files(self, limit: int = 400) -> list[Path]:
        root = Path(self.folder) if self.folder else None
        if root is None or not root.is_dir():
            return []
        found: list[Path] = []
        for here, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(files):
                if name.endswith(".bak") or name.endswith(".pyc"):
                    continue
                found.append(Path(here) / name)
                if len(found) >= limit:
                    return found
        return found

    def _list_files(self) -> None:
        for child in self.file_list.winfo_children():
            child.destroy()
        files = self.project_files()
        if not files:
            label(self.file_list, "Choose a folder to see its files." if not self.folder
                  else "This folder is empty — ask me to build something.", size=12, muted=True).pack(anchor="w")
            self._view(lambda box: None)
            return
        root = Path(self.folder)
        for path in files:
            relative = path.relative_to(root).as_posix()
            ctk.CTkButton(self.file_list, text=relative, anchor="w", height=24, corner_radius=10,
                          font=ctk.CTkFont(size=12), fg_color="transparent", hover_color=self.colors["accent_dim"],
                          text_color=self.colors["text"],
                          command=lambda p=path: self.open_file(p)).pack(fill="x")
        if not getattr(self, "_viewing", None) or not Path(self._viewing).exists():
            page = next((p for p in files if p.name.lower() in {"index.html", "main.py", "app.py", "readme.md"}),
                        files[0])
            self.open_file(page)
        else:
            self.open_file(Path(self._viewing))

    def open_file(self, path: Path) -> None:
        """Show a file in the code viewer, coloured, read-only."""
        self._viewing = str(path)
        try:
            relative = path.relative_to(Path(self.folder)).as_posix()
        except ValueError:
            relative = path.name
        self.file_name.configure(text=relative)
        try:
            raw = path.read_bytes()[:VIEW_LIMIT]
        except OSError as exc:
            self._view(lambda box: box.insert("end", f"Can't open it: {exc}", "muted"))
            return
        if b"\x00" in raw[:4096]:
            self._view(lambda box: box.insert("end", "This is not a text file, so there is nothing to show.",
                                               "muted"))
            return
        text = raw.decode("utf-8", errors="replace")
        language = LANGUAGES.get(path.suffix.lower(), "")

        def write(box):
            for line in text.splitlines():
                render._code_line(box, line + "\n", language)

        self._view(write)

    def _show_changes(self) -> None:
        agent = self._agent()
        changes = list(getattr(agent, "changes", []) or [])

        def write(box):
            if not changes:
                box.insert("end", "No changes yet. When I change files for you, every added and removed "
                                  "line shows up here.\n\n/undo puts the files back.", "muted")
                return
            for name, diff in changes:
                box.insert("end", f"{name}\n", "h")
                for line in (diff or "(no difference)\n").splitlines():
                    tag = ("hunk" if line.startswith("@@") else "muted" if line.startswith(("---", "+++"))
                           else "add" if line.startswith("+") else "del" if line.startswith("-") else "")
                    box.insert("end", line + "\n", tag)
                box.insert("end", "\n")

        self._view(write)

    def _show_plan(self) -> None:
        agent = self._agent()
        plan = getattr(agent, "plan", None)

        def write(box):
            if plan is None:
                box.insert("end", "No plan yet. Ask for a task and the steps show up here, ticked off as "
                                  "they're done.", "muted")
                return
            box.insert("end", f"{plan.goal}\n\n", "h")
            for step in plan.steps:
                mark = {"done": "✓", "failed": "✗", "skipped": "–"}.get(step.status, "○")
                tag = {"done": "add", "failed": "del"}.get(step.status, "")
                target = f" {step.target}" if step.target else ""
                box.insert("end", f"{mark}  {step.action}{target}\n", tag)
                if step.why:
                    box.insert("end", f"     {step.why}\n", "muted")
            if plan.risk:
                box.insert("end", f"\nRisk: {plan.risk}\n", "muted")

        self._view(write)

    # --- 14.3: terminal, preview, more ----------------------------------------------------
    def _need_folder(self) -> bool:
        if self.folder and Path(self.folder).is_dir():
            return True
        self._write("Choose a folder first — click “📁 Choose a folder” under the box.\n\n", "muted")
        return False

    def open_terminal(self) -> None:
        """A real terminal, opened in the project folder."""
        if not self._need_folder():
            return
        try:
            if shutil.which("wt"):
                subprocess.Popen(["wt", "-d", self.folder])
            else:
                subprocess.Popen(["cmd.exe", "/k", "title JARVIS terminal"], cwd=self.folder,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except OSError as exc:
            self._write(f"Couldn't open a terminal: {exc}\n\n", "muted")

    def preview(self) -> None:
        """Open the project's web page in the built-in browser, beside JARVIS."""
        from ui import preview

        if not self._need_folder():
            return
        page = preview.find_page(self.folder)
        if page is None:
            self._write("🌐 There's no web page in this folder yet. Ask me to build a website, then press 🌐 "
                        "again to see it here.\n\n", "muted")
            return
        try:
            url = preview.url_for(self.folder, page)
        except OSError as exc:
            self._write(f"Couldn't start the preview: {exc}\n\n", "muted")
            return
        top = self.winfo_toplevel()
        width, height = top.winfo_width(), top.winfo_height()
        geometry = (top.winfo_rootx() + width // 2, top.winfo_rooty(), max(480, width // 2), max(400, height))
        how = preview.open_window(url, geometry)
        where = "the built-in browser" if how == "edge" else "your browser"
        self._write(f"🌐 Showing {page.name} in {where}. It updates when you press 🌐 again after a change.\n"
                    f"   {url}\n\n", "muted")

    def more_menu(self) -> None:
        c = self.colors
        menu = tkinter.Menu(self, tearoff=0, bg=c["panel"], fg=c["text"], activebackground=c["accent_dim"],
                            activeforeground=c["text"], font=("Segoe UI", 10), bd=0)
        menu.add_command(label="📂  Open the folder in File Explorer", command=self.open_in_explorer)
        menu.add_command(label="↶  Undo my last changes", command=self.undo)
        menu.add_command(label="＋  New chat (forget this folder's talk)", command=self.new_chat)
        menu.add_separator()
        menu.add_command(label="⚙  Full editor: Settings → Advanced mode", command=self._open_settings)
        button = self.tool_buttons["more"]
        try:
            menu.tk_popup(button.winfo_rootx() - 200, button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def open_in_explorer(self) -> None:
        if self._need_folder():
            try:
                os.startfile(self.folder)  # noqa: S606 — the user's own folder, opened on request
            except OSError as exc:
                self._write(f"Couldn't open it: {exc}\n\n", "muted")

    def undo(self) -> None:
        self._write("You: undo\n", "you")
        self.run(lambda: self.app.jarvis.process("/undo").text,
                 lambda text: (self._write(f"{text}\n\n"), self.panel_view and self.refresh_panel()))

    def _open_settings(self) -> None:
        opener = getattr(self.app, "_open_settings", None)
        if opener:
            opener()

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

    def _show_team(self) -> None:
        from jarvis import teams

        on = teams.enabled()
        self.team_btn.configure(text="👥  Agent team: On" if on else "👥  Agent team: Off",
                                fg_color=self.colors["accent_dim"] if on else "transparent")

    def toggle_team(self) -> None:
        from jarvis import teams

        word = "off" if teams.enabled() else "on"
        text = self.app.jarvis.process(f"/agentteam {word}").text
        self._show_team()
        self._write(f"{text}\n\n", "muted")

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
            if self.panel_view:
                self.refresh_panel()      # new files, changes and plan show up straight away

        def failed(exc):
            self.send.configure(state="normal")
            self._write(f"Something went wrong: {exc}\n\n", "muted")

        self.run(work, done, failed)


def _tip(widget, text: str, colors: dict) -> None:
    """A small label under an icon-only button while the mouse rests on it."""
    state = {"tip": None, "job": None}

    def show():
        state["job"] = None
        try:
            tip = tkinter.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tkinter.Label(tip, text=text, bg=colors.get("panel", "#111827"), fg=colors.get("text", "#e5e7eb"),
                          font=("Segoe UI", 9), padx=8, pady=3, bd=0).pack()
            tip.geometry(f"+{widget.winfo_rootx() - 10}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
            state["tip"] = tip
        except tkinter.TclError:
            state["tip"] = None

    def enter(_event=None):
        leave()
        state["job"] = widget.after(450, show)

    def leave(_event=None):
        if state["job"] is not None:
            try:
                widget.after_cancel(state["job"])
            except tkinter.TclError:
                pass
            state["job"] = None
        if state["tip"] is not None:
            try:
                state["tip"].destroy()
            except tkinter.TclError:
                pass
            state["tip"] = None

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")
    widget.bind("<ButtonPress>", leave, add="+")
