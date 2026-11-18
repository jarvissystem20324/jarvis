"""The Cowork panel (13.4.2): jobs beside the chat, each with its plan, live
progress, and a Stop button while it runs.

The engine (jarvis.cowork) calls back from its worker threads; the window
passes every update here through after(), so this file only ever runs on the
Tk thread.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import customtkinter as ctk

from jarvis import cowork

ICONS = {"folder": "📁", "inbox": "📬", "form": "📝", "research": "🔎", "general": "🧰"}
STEP_MARKS = {"done": "✓", "running": "▶", "failed": "✗", "skipped": "–", "waiting": "○"}
WIDTH = 300


class JobCard(ctk.CTkFrame):
    def __init__(self, master, panel: "CoworkPanel", job: cowork.Job):
        c = panel.colors
        super().__init__(master, fg_color=c["panel"], corner_radius=10)
        self.panel, self.job_id = panel, job.id
        self.head = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=WIDTH - 40,
                                 font=ctk.CTkFont(size=12, weight="bold"), text_color=c["text"])
        self.head.pack(fill="x", padx=10, pady=(8, 0))
        self.status = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont(size=11), text_color=c["muted"])
        self.status.pack(fill="x", padx=10)
        self.bar = ctk.CTkProgressBar(self, height=6, progress_color=c["accent"], fg_color=c["bg"])
        self.bar.pack(fill="x", padx=10, pady=(2, 4))
        self.steps = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=WIDTH - 40,
                                  font=ctk.CTkFont(size=11), text_color=c["text"])
        self.steps.pack(fill="x", padx=10)
        self.note = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=WIDTH - 40,
                                 font=ctk.CTkFont(size=11), text_color=c["muted"])
        self.note.pack(fill="x", padx=10, pady=(2, 0))
        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.pack(fill="x", padx=6, pady=(4, 8))
        self._shape = None
        self._extra_rows: list = []
        self.update_from(job)

    def _button(self, text, command, danger=False):
        c = self.panel.colors
        ctk.CTkButton(self.buttons, text=text, command=command, height=24, width=0, font=ctk.CTkFont(size=11),
                      fg_color=c["error"] if danger else c["bg"], hover_color=c["accent_dim"],
                      text_color=c["text"]).pack(side="left", padx=3, pady=2)

    def update_from(self, job: cowork.Job) -> None:
        c = self.panel.colors
        self.head.configure(text=f"{ICONS.get(job.kind, '🧰')}  #{job.id}  {job.title or job.goal}"[:140])
        colour = {"done": c["ok"], "failed": c["error"], "stopped": c["muted"]}.get(job.status, c["accent"])
        label = {"planning": "Planning…", "running": f"Working · {int(job.progress * 100)}%", "done": "Done",
                 "failed": "Couldn't finish", "stopped": "Stopped"}.get(job.status, job.status)
        self.status.configure(text=f"{job.label()} · {label}", text_color=colour)
        self.bar.set(job.progress if job.status != "done" else 1.0)
        self.bar.configure(progress_color=colour)
        lines = []
        for step in job.steps:
            mark = STEP_MARKS.get(step.status, "○")
            detail = f" — {step.detail}" if step.detail and step.status in {"running", "done", "failed"} else ""
            lines.append(f"{mark} {step.title}{detail}"[:120])
        self.steps.configure(text="\n".join(lines) or "Making a plan…")
        note = job.error or ("" if job.running else job.result)
        if len(note) > 260:
            note = note[:260].rsplit(" ", 1)[0] + "…"
        self.note.configure(text=note, text_color=c["error"] if job.error else c["muted"])
        if not note:
            self.note.pack_forget()
        elif not self.note.winfo_ismapped():
            self.note.pack(fill="x", padx=10, pady=(2, 0), before=self.buttons)

        # Rebuild the buttons only when what they offer changes.
        shape = (job.status, tuple(job.outputs), len(job.extra.get("drafts") or []), bool(job.extra.get("undone")))
        if shape == self._shape:
            return
        self._shape = shape
        for child in self.buttons.winfo_children():
            child.destroy()
        for extra in self._extra_rows:
            extra.destroy()
        self._extra_rows = []
        if job.running:
            self._button("■  Stop", lambda: self.panel.stop(job.id), danger=True)
            return
        existing = [Path(p) for p in job.outputs if Path(p).exists()]
        row = self.buttons
        for path in existing[:2]:
            self._button(f"Open {path.suffix.lstrip('.').upper() or 'file'}", lambda p=path: self.panel.open(p))
        if existing:
            self._button("📂", lambda p=existing[0]: self.panel.folder(p))
            self._button("↶ Undo", lambda: self.panel.undo(job.id))
        if job.status in {"failed", "stopped"}:
            self._button("Retry", lambda: self.panel.retry(job))
        drafts = (job.extra.get("drafts") or [])[:6]
        if drafts:
            # Drafts get rows of their own: three a row fits the panel.
            for start in range(0, len(drafts), 3):
                self.buttons = ctk.CTkFrame(row.master, fg_color="transparent")
                self.buttons.pack(fill="x", padx=6, pady=(0, 4))
                for draft in drafts[start:start + 3]:
                    who = (draft.get("from") or draft.get("to") or "").split("<")[0].strip().strip('"')[:14] \
                        or "reply"
                    self._button(f"✉ {who}", lambda d=draft: self.panel.draft(d))
                self._extra_rows.append(self.buttons)
            self.buttons = row


class CoworkPanel(ctk.CTkFrame):
    def __init__(self, master, app, colors: dict):
        super().__init__(master, fg_color=colors["bg"], width=WIDTH, corner_radius=0)
        self.app, self.colors = app, colors
        self.cards: dict[int, JobCard] = {}
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(16, 4))
        ctk.CTkLabel(head, text="🧰  Cowork", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=colors["accent"]).pack(side="left", padx=4)
        ctk.CTkButton(head, text="✕", width=26, height=26, fg_color="transparent", hover_color=colors["accent_dim"],
                      text_color=colors["muted"], command=lambda: app.show_cowork_panel(False)).pack(side="right")
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=WIDTH - 24,
                                    font=ctk.CTkFont(size=11), text_color=colors["muted"])
        self.summary.pack(fill="x", padx=12)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", width=WIDTH - 20)
        self.list.pack(fill="both", expand=True, padx=4, pady=(4, 12))
        self.empty = ctk.CTkLabel(
            self.list, justify="left", anchor="w", wraplength=WIDTH - 40, font=ctk.CTkFont(size=12),
            text_color=colors["muted"],
            text=("Describe a job and press Send — it runs in the background while you keep chatting.\n\n"
                  "• Compare the PDFs in C:\\…\\Offers and make a table\n"
                  "• Sort my inbox and draft replies\n"
                  "• Research student laptops under 30,000 TL\n"
                  "• Fill https://… from my CV C:\\…\\cv.pdf\n\n"
                  "It asks before it reads your files or email, never sends or submits anything, and "
                  "Undo removes what it made."))
        self.empty.pack(fill="x", padx=6, pady=6)
        cowork.manager.load()
        for job in cowork.manager.jobs[-8:]:
            self.update_job(job)
        self._summarise()

    def _summarise(self) -> None:
        running = len(cowork.manager.running())
        self.summary.configure(text=f"{running} job(s) running" if running else "Nothing running")

    def update_job(self, job: cowork.Job) -> None:
        card = self.cards.get(job.id)
        try:
            if card is None:
                self.empty.pack_forget()
                card = self.cards[job.id] = JobCard(self.list, self, job)
                first = self._first_card(card)
                if first is not None:
                    card.pack(fill="x", padx=4, pady=4, before=first)   # newest on top
                else:
                    card.pack(fill="x", padx=4, pady=4)
            else:
                card.update_from(job)
        except Exception:
            pass
        self._summarise()

    def _first_card(self, exclude):
        """Newest on top: the card currently at the top of the list."""
        try:
            packed = [c for c in self.list.pack_slaves() if isinstance(c, JobCard) and c is not exclude]
        except Exception:
            packed = []
        return packed[0] if packed else None

    # --- actions ----------------------------------------------------------------------
    def stop(self, job_id: int) -> None:
        self.app._quick(cowork.manager.stop(job_id))

    def undo(self, job_id: int) -> None:
        def work():
            return cowork.manager.undo(job_id)

        self.app.run_tool_text(work)

    def retry(self, job: cowork.Job) -> None:
        self.app.start_cowork(job.goal)

    def open(self, path: Path) -> None:
        from ui.pages.base import open_path

        open_path(path)

    def folder(self, path: Path) -> None:
        from ui.pages.base import show_in_folder

        show_in_folder(path)

    def draft(self, draft: dict) -> None:
        """Open the reply in the user's own mail app. They read it and press Send."""
        try:
            webbrowser.open(cowork.mailto(draft))
        except Exception:
            pass
