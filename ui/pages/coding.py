"""Coding (10.0): an IDE in JARVIS — files, tabs, syntax colours, run with
live output, search, git, Python lessons, and the coding agent beside it.

Opening a folder here also opens it for the agent (/project), so /agent,
/fix, /test and /testgen work on what you are looking at. Running a file
asks once per project folder per session, then runs without a shell.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import tkinter
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk

from jarvis.ten import coding
from ui.pages.base import Page, button, label, open_path, safe_after

MONO = ("Consolas", 12)
TEXT_LIMIT = 2_000_000


def token_colours(c: dict) -> dict[str, str]:
    return {"Keyword": c["kw"], "Name.Builtin": c["kw"], "String": c["str"], "Comment": c["com"],
            "Number": c["num"], "Name.Function": c["accent"], "Name.Class": c["user"], "Name.Decorator": c["num"],
            "Operator.Word": c["kw"], "Name.Tag": c["kw"], "Name.Attribute": c["num"], "Literal": c["str"],
            "Generic.Heading": c["accent"], "Generic.Subheading": c["accent"]}


class Editor(ctk.CTkFrame):
    """One file: line numbers, text with colours, indent help."""

    def __init__(self, master, page, path: Path | None, text: str = ""):
        c = page.colors
        super().__init__(master, fg_color=c["code_bg"], corner_radius=0)
        self.page = page
        self.path = path
        self.lexer = None
        self.dirty = False
        self.gutter = tkinter.Canvas(self, width=46, bg=c["code_bg"], highlightthickness=0, bd=0)
        self.gutter.pack(side="left", fill="y")
        self.text = tkinter.Text(self, wrap="none", undo=True, bg=c["code_bg"], fg=c["text"], insertbackground=c["accent"],
                                 selectbackground=c["accent_dim"], relief="flat", font=MONO, tabs=("1c",), padx=6)
        ys = ctk.CTkScrollbar(self, command=self._yview)
        xs = ctk.CTkScrollbar(self, orientation="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=lambda a, b: (ys.set(a, b), self.draw_lines()), xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        for token, colour in token_colours(c).items():
            self.text.tag_configure(token, foreground=colour)
        self.text.tag_configure("found", background=c["accent"], foreground=c["bg"])
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._job = None
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<KeyRelease>", lambda e: self.draw_lines())
        self.text.bind("<Tab>", self._tab)
        self.text.bind("<Shift-Tab>", self._untab)
        self.text.bind("<ISO_Left_Tab>", self._untab)
        self.text.bind("<Return>", self._newline)
        self.text.bind("<Control-slash>", self._comment)
        self.set_lexer()
        self.highlight()
        self.after(50, self.draw_lines)

    def _yview(self, *args):
        self.text.yview(*args)
        self.draw_lines()

    def set_lexer(self) -> None:
        try:
            from pygments.lexers import get_lexer_for_filename, guess_lexer

            name = self.path.name if self.path else "untitled.py"
            try:
                self.lexer = get_lexer_for_filename(name, stripnl=False)
            except Exception:
                self.lexer = guess_lexer(self.text.get("1.0", "1.0+2000c"))
        except Exception:
            self.lexer = None

    def highlight(self) -> None:
        self._job = None
        if self.lexer is None:
            return
        text = self.text.get("1.0", "end-1c")
        if len(text) > 400_000:
            return
        tags = token_colours(self.page.colors)
        for tag in tags:
            self.text.tag_remove(tag, "1.0", "end")
        line, col = 1, 0
        cache: dict = {}
        for token, value in self.lexer.get_tokens(text):
            tag = cache.get(token)
            if tag is None and token not in cache:
                name = str(token).replace("Token.", "")
                tag = next((t for t in tags if name == t or name.startswith(t + ".")), None)
                if tag is None:
                    for prefix, mapped in (("Literal.String", "String"), ("Literal.Number", "Number"),
                                           ("Comment", "Comment"), ("Keyword", "Keyword")):
                        if name.startswith(prefix):
                            tag = mapped
                            break
                cache[token] = tag
            start = f"{line}.{col}"
            breaks = value.count("\n")
            if breaks:
                line += breaks
                col = len(value) - value.rfind("\n") - 1
            else:
                col += len(value)
            if tag:
                self.text.tag_add(tag, start, f"{line}.{col}")

    def _modified(self, _event=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if not self.dirty:
            self.dirty = True
            self.page.refresh_tabs()
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(450, self.highlight)

    def draw_lines(self) -> None:
        c = self.page.colors
        self.gutter.delete("all")
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            number = index.split(".")[0]
            self.gutter.create_text(40, info[1] + 2, anchor="ne", text=number, fill=c["muted"], font=("Consolas", 10))
            index = self.text.index(f"{index}+1line")
            if index == self.text.index("end"):
                break

    def _tab(self, _event=None) -> str:
        try:
            first = self.text.index("sel.first linestart")
            last = self.text.index("sel.last")
            line = int(first.split(".")[0])
            end = int(last.split(".")[0])
            for n in range(line, end + 1):
                self.text.insert(f"{n}.0", "    ")
        except tkinter.TclError:
            self.text.insert("insert", "    ")
        return "break"

    def _untab(self, _event=None) -> str:
        try:
            first, last = self.text.index("sel.first"), self.text.index("sel.last")
        except tkinter.TclError:
            first = last = self.text.index("insert")
        for n in range(int(first.split(".")[0]), int(last.split(".")[0]) + 1):
            start = self.text.get(f"{n}.0", f"{n}.4")
            spaces = len(start) - len(start.lstrip(" "))
            if spaces:
                self.text.delete(f"{n}.0", f"{n}.{spaces}")
        return "break"

    def _newline(self, _event=None) -> str:
        line = self.text.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith((":", "{", "[", "(")):
            indent += "    "
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        return "break"

    def _comment(self, _event=None) -> str:
        marker = "#" if self.path is None or self.path.suffix in {".py", ".sh", ".ps1", ".rb", ".yml", ".yaml", ".toml",
                                                                    ".r"} else "//"
        try:
            first, last = self.text.index("sel.first"), self.text.index("sel.last")
        except tkinter.TclError:
            first = last = self.text.index("insert")
        lines = range(int(first.split(".")[0]), int(last.split(".")[0]) + 1)
        commented = all(self.text.get(f"{n}.0", f"{n}.end").lstrip().startswith(marker) for n in lines
                        if self.text.get(f"{n}.0", f"{n}.end").strip())
        for n in lines:
            content = self.text.get(f"{n}.0", f"{n}.end")
            if not content.strip():
                continue
            if commented:
                at = content.index(marker)
                cut = len(marker) + (1 if content[at + len(marker):at + len(marker) + 1] == " " else 0)
                self.text.delete(f"{n}.{at}", f"{n}.{at + cut}")
            else:
                at = len(content) - len(content.lstrip())
                self.text.insert(f"{n}.{at}", marker + " ")
        self.highlight()
        return "break"

    def content(self) -> str:
        return self.text.get("1.0", "end-1c")

    def save(self, path: Path | None = None) -> bool:
        path = path or self.path
        if path is None:
            chosen = filedialog.asksaveasfilename(parent=self)
            if not chosen:
                return False
            path = Path(chosen)
        path.write_text(self.content(), encoding="utf-8")
        self.path = path
        self.dirty = False
        self.set_lexer()
        self.highlight()
        return True


class CodingPage(Page):
    key = "code"
    title = "Coding"
    icon = "⌨"

    def build(self) -> None:
        c = self.colors
        self.root: Path | None = None
        self.editors: list[Editor] = []
        self.current: Editor | None = None
        self.allowed_roots: set[str] = set()
        self.process: subprocess.Popen | None = None
        self.lesson = None
        # --- toolbar ---
        bar = ctk.CTkFrame(self, fg_color=c["panel"], corner_radius=0, height=44)
        bar.pack(fill="x")
        label(bar, "⌨  Coding", size=16, bold=True, text_color=c["accent"]).pack(side="left", padx=(12, 14))
        for text, command in (("📂 Open folder", self.open_folder), ("＋ New", self.new_file),
                              ("💾 Save", self.save_current), ("▶ Run  F5", self.run_current),
                              ("👁 Preview", self.preview), ("🟦 VS Code", self.vscode)):
            button(bar, text, command, height=30, accent=text.startswith("▶")).pack(side="left", padx=3, pady=6)
        self.check_btn = button(bar, "✔ Check lesson", self.check_lesson, height=30, accent=True)
        self.branch_label = label(bar, "", size=11, muted=True)
        self.branch_label.pack(side="right", padx=10)
        self.root_label = label(bar, "No folder open", size=11, muted=True)
        self.root_label.pack(side="right", padx=6)
        # --- panes ---
        panes = tkinter.PanedWindow(self, orient="horizontal", sashwidth=5, bg=c["bg"], bd=0)
        panes.pack(fill="both", expand=True)
        left = ctk.CTkTabview(panes, width=240, fg_color=c["panel"], segmented_button_selected_color=c["accent_dim"])
        panes.add(left, minsize=180, width=250)
        self._files_tab(left.add("Files"))
        self._find_tab(left.add("Find"))
        self._git_tab(left.add("Git"))
        self._learn_tab(left.add("Learn"))
        center = tkinter.PanedWindow(panes, orient="vertical", sashwidth=5, bg=c["bg"], bd=0)
        panes.add(center, minsize=400, width=760)
        top = ctk.CTkFrame(center, fg_color=c["bg"], corner_radius=0)
        center.add(top, minsize=200, height=480)
        self.tab_bar = ctk.CTkFrame(top, fg_color=c["panel"], corner_radius=0, height=32)
        self.tab_bar.pack(fill="x")
        self.editor_holder = ctk.CTkFrame(top, fg_color=c["code_bg"], corner_radius=0)
        self.editor_holder.pack(fill="both", expand=True)
        self.welcome = label(self.editor_holder, "Open a folder or a file — or start with ＋ New.\n\n"
                                                 "F5 runs · Ctrl+S saves · Ctrl+/ comments · Ctrl+Enter asks the agent",
                             size=14, muted=True)
        self.welcome.place(relx=0.5, rely=0.45, anchor="center")
        bottom = ctk.CTkFrame(center, fg_color=c["panel"], corner_radius=0)
        center.add(bottom, minsize=80, height=190)
        head = ctk.CTkFrame(bottom, fg_color="transparent")
        head.pack(fill="x")
        label(head, "Output", size=12, bold=True).pack(side="left", padx=8)
        button(head, "■ Stop", self.stop_process, height=22, width=60).pack(side="right", padx=4)
        button(head, "Clear", lambda: self.output.delete("1.0", "end"), height=22, width=50).pack(side="right")
        button(head, "🩹 Fix this error", self.fix_error, height=22).pack(side="right", padx=4)
        self.stdin = ctk.CTkEntry(head, placeholder_text="type input for the running program, Enter sends",
                                  height=22, width=300, fg_color=c["bg"])
        self.stdin.pack(side="right", padx=6)
        self.stdin.bind("<Return>", self.send_stdin)
        self.output = tkinter.Text(bottom, bg=c["bg"], fg=c["text"], font=("Consolas", 11), relief="flat", wrap="word",
                                   height=8)
        self.output.tag_configure("err", foreground=c["error"])
        self.output.tag_configure("ok", foreground=c["ok"])
        self.output.tag_configure("dim", foreground=c["muted"])
        self.output.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._agent_pane(panes)
        for seq, fn in (("<Control-s>", self.save_current), ("<F5>", self.run_current),
                        ("<Control-n>", self.new_file), ("<Control-w>", self.close_current),
                        ("<Control-Return>", self.ask_selection), ("<Control-f>", self.find_in_file)):
            self.bind_all_local(seq, fn)
        self.out_queue: queue.Queue = queue.Queue()
        self.every("output", 120, self._drain)

    def bind_all_local(self, sequence: str, fn) -> None:
        """Shortcuts that only act while this page is showing."""

        def handler(event):
            if not self.winfo_ismapped():
                return None
            fn()
            return "break"

        self.winfo_toplevel().bind(sequence, handler, add="+")

    # --- files ------------------------------------------------------------------------
    def _files_tab(self, tab) -> None:
        c = self.colors
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tkinter.TclError:
            pass
        style.configure("Code.Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"],
                        rowheight=22, borderwidth=0)
        style.map("Code.Treeview", background=[("selected", c["accent_dim"])])
        self.tree = ttk.Treeview(tab, style="Code.Treeview", show="tree")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._expand)
        self.tree.bind("<Double-Button-1>", self._tree_open)
        self.tree.bind("<Return>", self._tree_open)
        self.tree.bind("<Button-3>", self._tree_menu)
        self.paths: dict[str, Path] = {}

    def open_folder(self, folder: str | None = None) -> None:
        folder = folder or filedialog.askdirectory(parent=self)
        if not folder:
            return
        self.root = Path(folder)
        self.root_label.configure(text=f"📁 {self.root.name}")
        self.tree.delete(*self.tree.get_children())
        self.paths = {}
        node = self.tree.insert("", "end", text=f"📁 {self.root.name}", open=True)
        self.paths[node] = self.root
        self._fill(node, self.root)
        try:
            self.app.jarvis.addons.handle("project", str(self.root))
        except Exception:
            pass
        self.refresh_git()

    def _fill(self, node, folder: Path) -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for path in entries[:500]:
            if path.name in coding.SKIP or (path.name.startswith(".") and path.name not in {".gitignore", ".env.example"}):
                continue
            if path.is_dir():
                child = self.tree.insert(node, "end", text=f"📁 {path.name}")
                self.paths[child] = path
                self.tree.insert(child, "end", text="…")
            else:
                child = self.tree.insert(node, "end", text=f"   {path.name}")
                self.paths[child] = path

    def _expand(self, _event=None) -> None:
        node = self.tree.focus()
        path = self.paths.get(node)
        children = self.tree.get_children(node)
        if path and path.is_dir() and len(children) == 1 and self.tree.item(children[0], "text") == "…":
            self.tree.delete(children[0])
            self._fill(node, path)

    def _tree_open(self, _event=None) -> None:
        path = self.paths.get(self.tree.focus())
        if path and path.is_file():
            self.open_file(path)

    def _tree_menu(self, event) -> None:
        node = self.tree.identify_row(event.y)
        path = self.paths.get(node)
        if not path:
            return
        menu = tkinter.Menu(self, tearoff=0)
        if path.is_file():
            menu.add_command(label="Open", command=lambda: self.open_file(path))
            menu.add_command(label="Run", command=lambda: (self.open_file(path), self.run_current()))
        menu.add_command(label="New file here…", command=lambda: self.new_file(path if path.is_dir() else path.parent))
        menu.add_command(label="Show in Explorer", command=lambda: open_path(path if path.is_dir() else path.parent))
        menu.add_command(label="Refresh", command=lambda: self.open_folder(str(self.root)) if self.root else None)
        menu.tk_popup(event.x_root, event.y_root)

    def open_file(self, path: Path) -> None:
        for editor in self.editors:
            if editor.path and editor.path.resolve() == path.resolve():
                self.show_editor(editor)
                return
        try:
            if path.stat().st_size > TEXT_LIMIT:
                self.say(f"{path.name} is too big to edit here.", "err")
                return
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                self.say(f"{path.name} isn't a text file.", "err")
                return
            text = raw.decode("utf-8", "replace")
        except OSError as exc:
            self.say(str(exc), "err")
            return
        editor = Editor(self.editor_holder, self, path, text)
        self.editors.append(editor)
        self.show_editor(editor)

    def new_file(self, folder: Path | None = None) -> None:
        name = ctk.CTkInputDialog(text="File name (e.g. main.py):", title="New file").get_input()
        if not name:
            return
        base = folder if isinstance(folder, Path) else (self.root or Path.home())
        path = base / name.strip()
        if path.exists():
            self.open_file(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        if self.root:
            self.open_folder(str(self.root))
        self.open_file(path)

    def show_editor(self, editor: Editor) -> None:
        self.welcome.place_forget()
        for e in self.editors:
            e.pack_forget()
        editor.pack(fill="both", expand=True)
        self.current = editor
        editor.text.focus_set()
        self.refresh_tabs()
        is_lesson = self.lesson is not None and editor.path is None and getattr(editor, "lesson", None) is not None
        if is_lesson:
            self.check_btn.pack(side="left", padx=3)
        else:
            self.check_btn.pack_forget()

    def refresh_tabs(self) -> None:
        c = self.colors
        for child in self.tab_bar.winfo_children():
            child.destroy()
        for editor in self.editors:
            name = editor.path.name if editor.path else getattr(editor, "title", "untitled")
            frame = ctk.CTkFrame(self.tab_bar, fg_color=c["code_bg"] if editor is self.current else c["panel"],
                                 corner_radius=0)
            frame.pack(side="left", padx=(0, 1))
            ctk.CTkButton(frame, text=("● " if editor.dirty else "") + name, height=28, width=0, corner_radius=0,
                          fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                          command=lambda e=editor: self.show_editor(e)).pack(side="left")
            ctk.CTkButton(frame, text="✕", width=22, height=28, corner_radius=0, fg_color="transparent",
                          hover_color=c["error"], text_color=c["muted"],
                          command=lambda e=editor: self.close_editor(e)).pack(side="left")

    def close_editor(self, editor: Editor) -> None:
        if editor.dirty and editor.path:
            from tkinter import messagebox

            answer = messagebox.askyesnocancel("Save?", f"Save changes to {editor.path.name}?", parent=self)
            if answer is None:
                return
            if answer:
                editor.save()
        self.editors.remove(editor)
        editor.destroy()
        self.current = self.editors[-1] if self.editors else None
        if self.current:
            self.show_editor(self.current)
        else:
            self.refresh_tabs()
            self.welcome.place(relx=0.5, rely=0.45, anchor="center")

    def close_current(self) -> None:
        if self.current:
            self.close_editor(self.current)

    def save_current(self) -> None:
        if self.current and self.current.save():
            self.refresh_tabs()
            self.say(f"Saved {self.current.path.name}", "dim")

    # --- output -------------------------------------------------------------------------
    def say(self, text: str, tag: str = "") -> None:
        self.output.insert("end", text.rstrip("\n") + "\n", tag)
        self.output.see("end")

    def _drain(self) -> None:
        moved = False
        while True:
            try:
                text, tag = self.out_queue.get_nowait()
            except queue.Empty:
                break
            self.output.insert("end", text, tag)
            moved = True
        if moved:
            self.output.see("end")

    def run_current(self) -> None:
        editor = self.current
        if editor is None:
            return
        if getattr(editor, "lesson", None) is not None:
            self.check_lesson()
            return
        if editor.path is None and not editor.save():
            return
        if editor.dirty:
            editor.save()
            self.refresh_tabs()
        path = editor.path
        if path.suffix.lower() in {".html", ".htm", ".md"}:
            self.preview()
            return
        try:
            steps, label_text = coding.runner_for(path)
        except coding.CodingError as exc:
            self.say(str(exc), "err")
            return
        folder = str((self.root or path.parent).resolve())
        if folder not in self.allowed_roots:
            from jarvis import security

            if not security.permissions.ask(security.RUN_COMMAND, f"run code in {folder} this session",
                                            context="Coding page"):
                self.say("Not run.", "err")
                return
            self.allowed_roots.add(folder)
        self.stop_process()
        self.say(f"▶ {path.name} ({label_text})", "dim")
        threading.Thread(target=self._run_steps, args=(steps, path.parent), daemon=True).start()

    def _run_steps(self, steps: list[list[str]], cwd: Path) -> None:
        started = time.monotonic()
        code = 0
        for argv in steps:
            try:
                self.process = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, creationflags=coding.NO_WINDOW,
                                                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
            except FileNotFoundError:
                self.out_queue.put((f"{argv[0]} isn't installed (or isn't on PATH).\n", "err"))
                return
            proc = self.process

            def pump(stream, tag):
                for line in iter(stream.readline, b""):
                    self.out_queue.put((line.decode("utf-8", "replace"), tag))

            readers = [threading.Thread(target=pump, args=(proc.stdout, ""), daemon=True),
                       threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
            for r in readers:
                r.start()
            code = proc.wait()
            for r in readers:
                r.join(timeout=1)
            if code != 0:
                break
        self.process = None
        self.out_queue.put((f"— exit {code} in {time.monotonic() - started:.1f} s\n", "ok" if code == 0 else "err"))

    def send_stdin(self, _event=None) -> None:
        text = self.stdin.get()
        self.stdin.delete(0, "end")
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write((text + "\n").encode())
                self.process.stdin.flush()
                self.say(text, "dim")
            except OSError:
                pass

    def stop_process(self) -> None:
        if self.process is not None:
            try:
                self.process.kill()
            except OSError:
                pass
            self.process = None
            self.say("■ stopped", "err")

    def preview(self) -> None:
        if self.current and self.current.path:
            if self.current.dirty:
                self.current.save()
            reply = self.app.jarvis.preview_cmd(str(self.current.path))
            self.say(reply, "dim")

    def vscode(self) -> None:
        target = self.root or (self.current.path if self.current and self.current.path else None)
        self.say(self.app.jarvis.vscode_cmd(str(target) if target else ""), "dim")

    def fix_error(self) -> None:
        error = self.output.get("1.0", "end").strip()[-4000:]
        if not error:
            return
        self.ask_agent(f"/fix {error}")

    # --- find ------------------------------------------------------------------------------
    def _find_tab(self, tab) -> None:
        c = self.colors
        self.find_entry = ctk.CTkEntry(tab, placeholder_text="Find in the project…", fg_color=c["bg"])
        self.find_entry.pack(fill="x", padx=4, pady=4)
        self.find_entry.bind("<Return>", lambda e: self.find_in_project())
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x")
        button(row, "Find", self.find_in_project, height=24).pack(side="left", padx=4)
        button(row, "TODOs", lambda: self.find_in_project(r"\b(TODO|FIXME|HACK|XXX)\b"), height=24).pack(side="left")
        self.results = tkinter.Listbox(tab, bg=c["panel"], fg=c["text"], bd=0, highlightthickness=0,
                                       selectbackground=c["accent_dim"], font=("Consolas", 9))
        self.results.pack(fill="both", expand=True, padx=2, pady=4)
        self.results.bind("<Double-Button-1>", self._open_result)
        self.found: list[tuple[Path, int]] = []

    def find_in_project(self, pattern: str | None = None) -> None:
        if self.root is None:
            return
        needle = pattern or re.escape(self.find_entry.get().strip())
        if not needle:
            return
        regex = re.compile(needle, re.I)
        self.results.delete(0, "end")
        self.found = []
        root = self.root

        def work():
            hits = []
            for folder, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in coding.SKIP and not d.startswith(".")]
                for name in files:
                    path = Path(folder) / name
                    if path.suffix.lower() not in coding.LANGS:
                        continue
                    try:
                        with open(path, encoding="utf-8", errors="replace") as handle:
                            for n, line in enumerate(handle, 1):
                                if regex.search(line):
                                    hits.append((path, n, line.strip()[:90]))
                                    if len(hits) >= 400:
                                        return hits
                    except OSError:
                        continue
            return hits

        def done(hits):
            if isinstance(hits, str):
                return
            for path, n, line in hits:
                self.found.append((path, n))
                self.results.insert("end", f"{path.relative_to(root)}:{n}  {line}")
            if not hits:
                self.results.insert("end", "No matches.")

        self.run(work, done)

    def _open_result(self, _event=None) -> None:
        selection = self.results.curselection()
        if not selection or selection[0] >= len(self.found):
            return
        path, line = self.found[selection[0]]
        self.open_file(path)
        if self.current:
            self.current.text.see(f"{line}.0")
            self.current.text.mark_set("insert", f"{line}.0")
            self.current.text.tag_remove("sel", "1.0", "end")
            self.current.text.tag_add("sel", f"{line}.0", f"{line}.end")

    def find_in_file(self) -> None:
        if self.current is None:
            return
        needle = ctk.CTkInputDialog(text="Find:", title="Find in file").get_input()
        if not needle:
            return
        text = self.current.text
        text.tag_remove("found", "1.0", "end")
        start = "1.0"
        first = None
        while True:
            pos = text.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(needle)}c"
            text.tag_add("found", pos, end)
            first = first or pos
            start = end
        if first:
            text.see(first)

    # --- git ---------------------------------------------------------------------------------
    def _git_tab(self, tab) -> None:
        c = self.colors
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x")
        button(row, "↻", self.refresh_git, width=30, height=24).pack(side="left", padx=2)
        button(row, "New branch", lambda: self._branch("new"), height=24).pack(side="left", padx=2)
        button(row, "Switch", lambda: self._branch("switch"), height=24).pack(side="left", padx=2)
        self.git_text = tkinter.Text(tab, bg=c["panel"], fg=c["text"], font=("Consolas", 9), relief="flat", wrap="none")
        self.git_text.pack(fill="both", expand=True, pady=4)

    def refresh_git(self) -> None:
        if self.root is None:
            return
        jarvis = self.app.jarvis

        def work():
            return jarvis.branch_cmd("list") + "\n\n" + jarvis.gitgraph_cmd("30")

        def done(text):
            self.git_text.delete("1.0", "end")
            self.git_text.insert("1.0", str(text).replace("```", ""))
            m = re.search(r"^\*\s+(\S+)", str(text), re.M)
            self.branch_label.configure(text=f"🌿 {m.group(1)}" if m else "")

        self.run(work, done)

    def _branch(self, action: str) -> None:
        name = ctk.CTkInputDialog(text="Branch name:", title=f"{action.capitalize()} branch").get_input()
        if name:
            self.app.run_tool(f"/branch {action} {name.strip()}", lambda r: (self.say(str(getattr(r, 'text', r))),
                                                                              self.refresh_git()), name="branch")

    # --- lessons ------------------------------------------------------------------------------
    def _learn_tab(self, tab) -> None:
        c = self.colors
        label(tab, "Python, step by step. Pick a lesson, write the code, press ✔ Check.", size=11, muted=True,
              wrap=200).pack(anchor="w", padx=4, pady=4)
        self.lesson_box = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.lesson_box.pack(fill="both", expand=True)
        self.fill_lessons()

    def fill_lessons(self) -> None:
        done = coding.LESSON_PROGRESS.load()
        for child in self.lesson_box.winfo_children():
            child.destroy()
        for lesson in coding.LESSONS:
            button(self.lesson_box, ("✔ " if done.get(lesson["id"]) else "○ ") + lesson["title"],
                   lambda l=lesson: self.open_lesson(l), height=26, anchor="w").pack(fill="x", pady=1)

    def open_lesson(self, lesson: dict) -> None:
        self.lesson = lesson
        header = "\n".join("# " + line for line in (lesson["title"] + "\n\n" + lesson["text"] + "\nTask: " +
                                                    lesson["task"]).splitlines())
        editor = Editor(self.editor_holder, self, None, header + "\n\n" + lesson["start"])
        editor.lesson = lesson
        editor.title = lesson["title"].split(". ", 1)[-1]
        self.editors.append(editor)
        self.show_editor(editor)
        editor.text.mark_set("insert", "end")

    def check_lesson(self) -> None:
        editor = self.current
        lesson = getattr(editor, "lesson", None) if editor else None
        if lesson is None:
            return
        code = editor.content()

        def done(result):
            if isinstance(result, str):
                self.say(result, "err")
                return
            ok, message = result
            self.say(message, "ok" if ok else "err")
            if ok:
                progress = coding.LESSON_PROGRESS.load()
                progress[lesson["id"]] = True
                coding.LESSON_PROGRESS.save(progress)
                self.fill_lessons()

        self.say(f"Checking {lesson['title']}…", "dim")
        self.run(lambda: coding.check_lesson(lesson, code), done)

    # --- agent ----------------------------------------------------------------------------------
    def _agent_pane(self, panes) -> None:
        c = self.colors
        pane = ctk.CTkFrame(panes, fg_color=c["panel"], corner_radius=0)
        panes.add(pane, minsize=220, width=320)
        label(pane, "🤖 Coding agent", size=13, bold=True).pack(anchor="w", padx=8, pady=(8, 2))
        label(pane, "Ask about the code, or use a button. /agent plans bigger jobs.", size=10, muted=True,
              wrap=290).pack(anchor="w", padx=8)
        row = ctk.CTkFrame(pane, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=4)
        row.grid_columnconfigure((0, 1), weight=1)
        for i, (text, prompt) in enumerate((("Explain", "explain"), ("Find bugs", "bugs"), ("Write tests", "tests"),
                                            ("Improve", "improve"))):
            button(row, text, lambda p=prompt: self.quick_agent(p), height=24).grid(row=i // 2, column=i % 2,
                                                                                     sticky="ew", padx=1, pady=1)
        self.agent_log = ctk.CTkTextbox(pane, wrap="word", fg_color=c["bg"], font=ctk.CTkFont(size=12))
        self.agent_log.pack(fill="both", expand=True, padx=6)
        line = ctk.CTkFrame(pane, fg_color="transparent")
        line.pack(fill="x", padx=6, pady=6)
        self.agent_entry = ctk.CTkEntry(line, placeholder_text="Ask… (Ctrl+Enter sends the selection)",
                                        fg_color=c["bg"])
        self.agent_entry.pack(side="left", fill="x", expand=True)
        self.agent_entry.bind("<Return>", lambda e: self.ask_agent(self.agent_entry.get()))
        button(line, "Apply", lambda: self.ask_agent("/apply"), width=56, height=28).pack(side="left", padx=(4, 0))

    def _file_context(self, limit: int = 12000) -> str:
        if not self.current:
            return ""
        name = self.current.path.name if self.current.path else "untitled"
        body = self.current.content()[:limit]
        return f"File {name}:\n```\n{body}\n```"

    def quick_agent(self, kind: str) -> None:
        name = self.current.path.name if self.current and self.current.path else "this code"
        if kind == "tests" and self.current and self.current.path:
            self.ask_agent(f"/testgen {self.current.path}")
            return
        ask = {"explain": f"Explain what {name} does, section by section, briefly.",
               "bugs": f"Review {name} for bugs and risky code. List each with the line and a fix.",
               "improve": f"Suggest the 3 most valuable improvements to {name}, with code."}[kind]
        self.ask_agent(ask, with_file=True)

    def ask_selection(self) -> None:
        if not self.current:
            return
        try:
            selected = self.current.text.get("sel.first", "sel.last")
        except tkinter.TclError:
            selected = ""
        question = self.agent_entry.get().strip() or "Explain this code and point out problems."
        if selected:
            self.ask_agent(f"{question}\n\n```\n{selected[:8000]}\n```")
        else:
            self.ask_agent(question, with_file=True)

    def ask_agent(self, text: str, with_file: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.agent_entry.delete(0, "end")
        self.agent_log.insert("end", f"\nYou: {text[:300]}\n")
        self.agent_log.see("end")
        message = text if text.startswith("/") or not with_file else f"{text}\n\n{self._file_context()}"
        jarvis = self.app.jarvis
        if not jarvis.brain.code_mode:
            jarvis.toggle_code_mode()

        def work():
            return jarvis.process(message)

        def done(response):
            reply = getattr(response, "text", str(response))
            self.agent_log.insert("end", f"JARVIS: {reply}\n")
            self.agent_log.see("end")
            if text.startswith("/apply"):
                for editor in self.editors:
                    if editor.path and editor.path.exists() and not editor.dirty:
                        editor.text.delete("1.0", "end")
                        editor.text.insert("1.0", editor.path.read_text(encoding="utf-8", errors="replace"))
                        editor.dirty = False
                        editor.highlight()
                self.refresh_tabs()

        self.run(work, done)

    def close(self) -> None:
        self.stop_process()
        super().close()
