"""Today, Calendar, Notes and Inbox (10.0).

All four read and write the same stores the chat commands use (life.TODO,
life.CALENDAR, ten.work's notebook, goals and bookmarks), so typing
"/mylist add milk" and ticking a box here change the same list.
"""

from __future__ import annotations

import calendar as cal_mod
import re
import time
import tkinter
import uuid
import webbrowser
from datetime import date, datetime, timedelta

import customtkinter as ctk

from jarvis import reminders
from jarvis.ten import work
from ui.pages.base import Card, Hub, Page, ResultView, button, label


def _when(ts: float) -> str:
    if not ts:
        return ""
    moment = datetime.fromtimestamp(ts)
    days = (moment.date() - date.today()).days
    day = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(days, moment.strftime("%a %d %b"))
    return f"{day} {moment:%H:%M}"


class TodayPage(Hub):
    key = "today"
    title = "Today"
    icon = "✅"
    subtitle = "Your to-do list with steps and repeats, your goals, and the day in one look."

    def build_body(self) -> None:
        c = self.colors
        # --- tasks ---
        card = self.card("To-do", "Tick a box to finish. 🔁 tasks come back by themselves.", "☑", span=1)
        add = ctk.CTkFrame(card.inner, fg_color="transparent")
        add.pack(fill="x")
        self.new_task = ctk.CTkEntry(add, placeholder_text="New task… (e.g. call the dentist friday 10:00)",
                                     fg_color=c["bg"])
        self.new_task.pack(side="left", fill="x", expand=True)
        self.new_task.bind("<Return>", lambda e: self.add_task())
        self.repeat = ctk.CTkOptionMenu(add, values=["once", "daily", "weekdays", "weekly", "monthly"], width=100,
                                        fg_color=c["bg"], button_color=c["accent_dim"])
        self.repeat.pack(side="left", padx=6)
        button(add, "Add", self.add_task, accent=True, width=60).pack(side="left")
        self.show_done = tkinter.BooleanVar(value=False)
        ctk.CTkCheckBox(card.inner, text="Show finished", variable=self.show_done, command=self.refresh_tasks,
                        checkbox_width=16, checkbox_height=16).pack(anchor="w", pady=(6, 2))
        self.task_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.task_box.pack(fill="both", expand=True)
        # --- right column ---
        right = ctk.CTkFrame(self.body, fg_color="transparent")
        self.place(right)
        today = Card(right, "Schedule", "Reminders and events today", "📅")
        today.pack(fill="x", pady=(0, 10))
        self.schedule = ctk.CTkFrame(today.inner, fg_color="transparent")
        self.schedule.pack(fill="x")
        goals = Card(right, "Goals", "Log progress with +1, or type a number.", "🎯")
        goals.pack(fill="x", pady=(0, 10))
        self.goal_box = ctk.CTkFrame(goals.inner, fg_color="transparent")
        self.goal_box.pack(fill="x")
        row = ctk.CTkFrame(goals.inner, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.goal_title = ctk.CTkEntry(row, placeholder_text="New goal (Read 12 books)", fg_color=c["bg"])
        self.goal_title.pack(side="left", fill="x", expand=True)
        self.goal_target = ctk.CTkEntry(row, placeholder_text="12 books", width=90, fg_color=c["bg"])
        self.goal_target.pack(side="left", padx=4)
        self.goal_by = ctk.CTkEntry(row, placeholder_text="by 2026-12-31", width=110, fg_color=c["bg"])
        self.goal_by.pack(side="left", padx=(0, 4))
        button(row, "Add", self.add_goal, width=50).pack(side="left")
        eod = Card(right, "End of the day", "What you did, what slipped, one idea for tomorrow.", "🌙")
        eod.pack(fill="x")
        row = ctk.CTkFrame(eod.inner, fg_color="transparent")
        row.pack(fill="x")
        button(row, "Summarise my day", lambda: self._eod(False), accent=True).pack(side="left")
        button(row, "…with AI thoughts", lambda: self._eod(True)).pack(side="left", padx=6)
        self.eod_view = ResultView(eod.inner, self.app)
        self.eod_view.pack(fill="x")
        self.section("More")
        self.tools("meeting", "goal")

    def on_show(self) -> None:
        self.refresh_tasks()
        self.refresh_goals()
        self.refresh_schedule()

    # --- tasks ---------------------------------------------------------------
    def add_task(self) -> None:
        from jarvis.life import parse_when

        text = self.new_task.get().strip()
        if not text:
            return
        due, what = parse_when(text)
        repeat = self.repeat.get()
        work.add_task(what or text, due.timestamp() if due else 0, "" if repeat == "once" else repeat)
        self.new_task.delete(0, "end")
        self.refresh_tasks()

    def refresh_tasks(self) -> None:
        c = self.colors
        for child in self.task_box.winfo_children():
            child.destroy()
        items = work.load_tasks()
        rows = [(i, t) for i, t in enumerate(items) if self.show_done.get() or not t.get("done")]
        rows.sort(key=lambda r: (r[1].get("done", False), r[1].get("due") or 9e12, r[1].get("added", 0)))
        if not rows:
            label(self.task_box, "Nothing on the list. Add something above.", muted=True).pack(anchor="w", pady=6)
        for index, task in rows[:80]:
            row = ctk.CTkFrame(self.task_box, fg_color=c["bg"], corner_radius=8)
            row.pack(fill="x", pady=2)
            var = tkinter.BooleanVar(value=bool(task.get("done")))
            ctk.CTkCheckBox(row, text="", variable=var, width=24, checkbox_width=18, checkbox_height=18,
                            command=lambda i=index: self.finish(i)).pack(side="left", padx=(8, 0), pady=6)
            text = task["text"] + ("  🔁" if task.get("repeat") else "")
            label(row, text, size=13, text_color=c["muted"] if task.get("done") else c["text"],
                  wrap=360).pack(side="left", padx=4)
            due = task.get("due") or 0
            if due:
                late = due < time.time() and not task.get("done")
                label(row, _when(due), size=11, text_color=c["error"] if late else c["muted"]).pack(side="left", padx=6)
            button(row, "✕", lambda i=index: self.delete(i), width=26, height=24).pack(side="right", padx=4)
            button(row, "＋ step", lambda i=index: self.add_step(i), height=24).pack(side="right")
            subs = task.get("subtasks") or []
            if subs:
                bar = ctk.CTkProgressBar(row, width=60, height=8, progress_color=c["accent"])
                bar.set(work.progress(task))
                bar.pack(side="right", padx=6)
                for j, sub in enumerate(subs):
                    line = ctk.CTkFrame(self.task_box, fg_color="transparent")
                    line.pack(fill="x", padx=(34, 0))
                    v = tkinter.BooleanVar(value=bool(sub.get("done")))
                    ctk.CTkCheckBox(line, text=sub["text"], variable=v, checkbox_width=14, checkbox_height=14,
                                    font=ctk.CTkFont(size=12),
                                    command=lambda i=index, k=j: (work.toggle_subtask(i, k), self.refresh_tasks())
                                    ).pack(anchor="w", pady=1)

    def finish(self, index: int) -> None:
        items = work.load_tasks()
        if items[index].get("done"):
            items[index]["done"] = False
            work.save_tasks(items)
        else:
            self.app.status_label.configure(text=work.finish_task(index))
        self.refresh_tasks()

    def delete(self, index: int) -> None:
        items = work.load_tasks()
        if 0 <= index < len(items):
            items.pop(index)
            work.save_tasks(items)
        self.refresh_tasks()

    def add_step(self, index: int) -> None:
        dialog = ctk.CTkInputDialog(text="A step for this task:", title="Add a step")
        step = (dialog.get_input() or "").strip()
        if step:
            items = work.load_tasks()
            items[index].setdefault("subtasks", []).append({"text": step, "done": False})
            work.save_tasks(items)
            self.refresh_tasks()

    # --- goals ---------------------------------------------------------------
    def refresh_goals(self) -> None:
        c = self.colors
        for child in self.goal_box.winfo_children():
            child.destroy()
        goals = work.GOALS.load()
        if not goals:
            label(self.goal_box, "No goals yet.", muted=True).pack(anchor="w")
        for i, goal in enumerate(goals):
            row = ctk.CTkFrame(self.goal_box, fg_color="transparent")
            row.pack(fill="x", pady=3)
            target = goal.get("target") or 1
            label(row, goal["title"], size=12, width=150).pack(side="left")
            bar = ctk.CTkProgressBar(row, height=10, progress_color=c["ok"] if goal["progress"] >= target
                                     else c["accent"])
            bar.set(min(1.0, goal.get("progress", 0) / target))
            bar.pack(side="left", fill="x", expand=True, padx=6)
            label(row, f"{goal.get('progress', 0):g}/{target:g} {goal.get('unit', '')}", size=11).pack(side="left")
            button(row, "+1", lambda n=i: self._goal(n, "+1"), width=34, height=22).pack(side="left", padx=4)
            button(row, "✕", lambda n=i: self._goal(n, "delete"), width=24, height=22).pack(side="left")

    def _goal(self, index: int, change: str) -> None:
        self.app.jarvis.goal(f"{index + 1} {change}")
        self.refresh_goals()

    def add_goal(self) -> None:
        title = self.goal_title.get().strip()
        target = self.goal_target.get().strip() or "1"
        by = self.goal_by.get().strip()
        if not title:
            return
        spec = target + (f" by {by.replace('by ', '')}" if by else "")
        reply = self.app.jarvis.goal(f"add {title} | {spec}")
        self.app.status_label.configure(text=reply[:80])
        for entry in (self.goal_title, self.goal_target, self.goal_by):
            entry.delete(0, "end")
        self.refresh_goals()

    def refresh_schedule(self) -> None:
        from ui.pages.home import today_lines

        for child in self.schedule.winfo_children():
            child.destroy()
        lines = [line for line in today_lines(12) if not line.startswith("☐")]
        if not lines:
            label(self.schedule, "Nothing scheduled today.", muted=True).pack(anchor="w")
        for line in lines:
            label(self.schedule, line, size=12).pack(anchor="w")

    def _eod(self, ai: bool) -> None:
        self.app.run_tool("/eod ai" if ai else "/eod", self.eod_view.show, name="eod")


class CalendarPage(Page):
    key = "calendar"
    title = "Calendar"
    icon = "📅"

    def build(self) -> None:
        c = self.colors
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 6))
        label(top, "📅  Calendar", size=22, bold=True, text_color=c["accent"]).pack(side="left")
        button(top, "◀", lambda: self.shift(-1), width=34).pack(side="left", padx=(20, 2))
        self.month_label = label(top, "", size=16, bold=True, width=180)
        self.month_label.pack(side="left", padx=6)
        button(top, "▶", lambda: self.shift(1), width=34).pack(side="left", padx=2)
        button(top, "Today", self.go_today, width=60).pack(side="left", padx=8)
        button(top, "Export .ics", lambda: self.app.run_tool("/cal export", self._said, name="cal")).pack(side="right")
        button(top, "Import .ics", self.import_ics).pack(side="right", padx=6)
        button(top, "Google Calendar", lambda: self.app.run_in_chat("/gcal week")).pack(side="right")
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.grid_frame = ctk.CTkFrame(body, fg_color=c["panel"], corner_radius=12)
        self.grid_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        for col in range(7):
            self.grid_frame.grid_columnconfigure(col, weight=1, uniform="day")
        side = Card(body, "", "")
        side.grid(row=0, column=1, sticky="nsew")
        self.day_title = label(side.inner, "", size=16, bold=True)
        self.day_title.pack(anchor="w")
        self.day_list = ctk.CTkScrollableFrame(side.inner, fg_color="transparent", height=220)
        self.day_list.pack(fill="both", expand=True, pady=6)
        label(side.inner, "Add an event", size=12, bold=True).pack(anchor="w", pady=(8, 2))
        self.ev_title = ctk.CTkEntry(side.inner, placeholder_text="What", fg_color=c["bg"])
        self.ev_title.pack(fill="x", pady=2)
        row = ctk.CTkFrame(side.inner, fg_color="transparent")
        row.pack(fill="x")
        self.ev_time = ctk.CTkEntry(row, placeholder_text="14:00", width=70, fg_color=c["bg"])
        self.ev_time.pack(side="left")
        self.ev_len = ctk.CTkOptionMenu(row, values=["30 min", "1 hour", "2 hours", "all day"], width=100,
                                        fg_color=c["bg"], button_color=c["accent_dim"])
        self.ev_len.set("1 hour")
        self.ev_len.pack(side="left", padx=4)
        self.ev_where = ctk.CTkEntry(side.inner, placeholder_text="Where (optional)", fg_color=c["bg"])
        self.ev_where.pack(fill="x", pady=2)
        button(side.inner, "Add to this day", self.add_event, accent=True).pack(anchor="w", pady=4)
        self.note = label(side.inner, "", size=11, muted=True, wrap=240)
        self.note.pack(anchor="w")

    def on_show(self) -> None:
        self.draw()

    def shift(self, months: int) -> None:
        year = self.month.year + (self.month.month - 1 + months) // 12
        month = (self.month.month - 1 + months) % 12 + 1
        self.month = date(year, month, 1)
        self.draw()

    def go_today(self) -> None:
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self.draw()

    def events(self) -> list[dict]:
        from jarvis.life import CALENDAR

        return CALENDAR.load()

    def draw(self) -> None:
        c = self.colors
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.month_label.configure(text=self.month.strftime("%B %Y"))
        for col, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            label(self.grid_frame, name, size=11, muted=True).grid(row=0, column=col, pady=(8, 2))
        events = self.events()
        by_day: dict[date, list[dict]] = {}
        for event in events:
            day = datetime.fromtimestamp(event.get("start", 0)).date()
            by_day.setdefault(day, []).append(event)
        weeks = cal_mod.Calendar(firstweekday=0).monthdatescalendar(self.month.year, self.month.month)
        for r, week in enumerate(weeks, 1):
            self.grid_frame.grid_rowconfigure(r, weight=1, uniform="week")
            for col, day in enumerate(week):
                inside = day.month == self.month.month
                chosen = day == self.selected
                cell = ctk.CTkFrame(self.grid_frame, corner_radius=8,
                                    fg_color=c["accent_dim"] if chosen else (c["bg"] if inside else c["panel"]),
                                    border_width=2 if day == date.today() else 0, border_color=c["accent"])
                cell.grid(row=r, column=col, sticky="nsew", padx=3, pady=3)
                head = label(cell, str(day.day), size=12, bold=day == date.today(),
                             text_color=c["text"] if inside else c["muted"])
                head.pack(anchor="nw", padx=6, pady=(4, 0))
                items = sorted(by_day.get(day, []), key=lambda e: e["start"])
                for event in items[:3]:
                    label(cell, f"{datetime.fromtimestamp(event['start']):%H:%M} {event['title'][:16]}", size=10,
                          text_color=c["accent"]).pack(anchor="w", padx=6)
                if len(items) > 3:
                    label(cell, f"+{len(items) - 3} more", size=10, muted=True).pack(anchor="w", padx=6)
                for widget in (cell, *cell.winfo_children()):
                    widget.bind("<Button-1>", lambda e, d=day: self.select(d))
        self.show_day()

    def select(self, day: date) -> None:
        self.selected = day
        if day.month != self.month.month:
            self.month = day.replace(day=1)
        self.draw()

    def show_day(self) -> None:
        for child in self.day_list.winfo_children():
            child.destroy()
        self.day_title.configure(text=self.selected.strftime("%A %d %B"))
        start = datetime.combine(self.selected, datetime.min.time()).timestamp()
        items = sorted((e for e in self.events() if start <= e.get("start", 0) < start + 86400),
                       key=lambda e: e["start"])
        if not items:
            label(self.day_list, "Nothing on this day.", muted=True).pack(anchor="w")
        for event in items:
            row = ctk.CTkFrame(self.day_list, fg_color="transparent")
            row.pack(fill="x", pady=2)
            text = f"{datetime.fromtimestamp(event['start']):%H:%M}  {event['title']}" + (
                f"\n   @ {event['where']}" if event.get("where") else "")
            label(row, text, size=12, wrap=200).pack(side="left")
            button(row, "✕", lambda e=event: self.delete(e), width=24, height=22).pack(side="right")

    def add_event(self) -> None:
        from jarvis.life import CALENDAR

        title = self.ev_title.get().strip()
        if not title:
            self.note.configure(text="What is it?")
            return
        length = {"30 min": 1800, "1 hour": 3600, "2 hours": 7200, "all day": 86400}[self.ev_len.get()]
        raw = self.ev_time.get().strip() or ("00:00" if length == 86400 else "09:00")
        m = re.match(r"(\d{1,2})(?::(\d{2}))?$", raw)
        if not m or int(m.group(1)) > 23:
            self.note.configure(text="Time like 14:00")
            return
        start = datetime.combine(self.selected, datetime.min.time()).replace(hour=int(m.group(1)),
                                                                             minute=int(m.group(2) or 0))
        event = {"title": title, "start": start.timestamp(), "end": start.timestamp() + length,
                 "where": self.ev_where.get().strip(), "uid": uuid.uuid4().hex}
        CALENDAR.save(CALENDAR.load() + [event])
        if start.timestamp() - 900 > time.time() and length < 86400:
            reminders.board.add("event", f"{title} at {start:%H:%M}", start.timestamp() - 900)
        for entry in (self.ev_title, self.ev_time, self.ev_where):
            entry.delete(0, "end")
        self.note.configure(text=f"Added {title}.")
        self.draw()

    def delete(self, event: dict) -> None:
        from jarvis.life import CALENDAR

        CALENDAR.save([e for e in CALENDAR.load() if not (e.get("uid") == event.get("uid") and
                                                           e.get("start") == event.get("start"))])
        self.draw()

    def import_ics(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self, filetypes=[("Calendar", "*.ics"), ("All files", "*.*")])
        if path:
            self.app.run_tool(f"/cal import {path}", self._said, name="cal")

    def _said(self, response) -> None:
        self.note.configure(text=str(getattr(response, "text", response))[:200])
        self.draw()


class NotesPage(Page):
    key = "notes"
    title = "Notes"
    icon = "🗒"

    def build(self) -> None:
        c = self.colors
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 4))
        label(top, "🗒  Notes", size=22, bold=True, text_color=c["accent"]).pack(side="left")
        tabs = ctk.CTkTabview(self, fg_color=c["panel"], segmented_button_selected_color=c["accent_dim"])
        tabs.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._notebook(tabs.add("Notebook"))
        self._bookmarks(tabs.add("Bookmarks"))
        self.current: dict | None = None

    # --- notebook -------------------------------------------------------------
    def _notebook(self, tab) -> None:
        c = self.colors
        tab.grid_columnconfigure(2, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        self.search = ctk.CTkEntry(tab, placeholder_text="Search notes…", fg_color=c["bg"])
        self.search.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.search.bind("<KeyRelease>", lambda e: self.fill_list())
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=2, sticky="ew", padx=4)
        button(bar, "＋ New note", self.new_note, accent=True).pack(side="left")
        button(bar, "Save", self.save).pack(side="left", padx=6)
        button(bar, "Delete", self.delete).pack(side="left")
        self.saved = label(bar, "", size=11, muted=True)
        self.saved.pack(side="left", padx=10)
        self.folder_box = ctk.CTkScrollableFrame(tab, fg_color=c["bg"], width=130)
        self.folder_box.grid(row=1, column=0, sticky="ns", padx=4, pady=4)
        self.list_box = ctk.CTkScrollableFrame(tab, fg_color=c["bg"], width=220)
        self.list_box.grid(row=1, column=1, sticky="ns", padx=4, pady=4)
        editor = ctk.CTkFrame(tab, fg_color="transparent")
        editor.grid(row=1, column=2, sticky="nsew", padx=4, pady=4)
        head = ctk.CTkFrame(editor, fg_color="transparent")
        head.pack(fill="x")
        self.title_entry = ctk.CTkEntry(head, placeholder_text="Title", font=ctk.CTkFont(size=16, weight="bold"),
                                        fg_color=c["bg"])
        self.title_entry.pack(side="left", fill="x", expand=True)
        self.folder_entry = ctk.CTkEntry(head, placeholder_text="Folder", width=120, fg_color=c["bg"])
        self.folder_entry.pack(side="left", padx=(6, 0))
        self.text = tkinter.Text(editor, wrap="word", bg=c["bg"], fg=c["text"], insertbackground=c["accent"],
                                 relief="flat", font=("Segoe UI", 12), undo=True, padx=10, pady=8)
        self.text.pack(fill="both", expand=True, pady=6)
        self.text.tag_config("link", foreground=c["accent"], underline=True)
        self.text.tag_bind("link", "<Button-1>", self._follow)
        self.text.tag_bind("link", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda e: self.text.configure(cursor="xterm"))
        self.text.bind("<KeyRelease>", lambda e: self._mark_links())
        self.text.bind("<Control-s>", lambda e: (self.save(), "break")[1])
        label(editor, "Tip: write [[Another note]] to link notes — click a link to open it (or create it).",
              size=10, muted=True).pack(anchor="w")
        self.backlinks = label(editor, "", size=11, muted=True, wrap=600)
        self.backlinks.pack(anchor="w")
        self.folder = "All"

    def on_show(self) -> None:
        self.fill_folders()
        self.fill_list()
        self.fill_bookmarks()

    def fill_folders(self) -> None:
        c = self.colors
        for child in self.folder_box.winfo_children():
            child.destroy()
        for name in ["All"] + work.folders() + ["Quick notes"]:
            ctk.CTkButton(self.folder_box, text=name, anchor="w", height=26,
                          fg_color=c["accent_dim"] if name == self.folder else "transparent",
                          hover_color=c["accent_dim"], text_color=c["text"],
                          command=lambda n=name: self._pick_folder(n)).pack(fill="x", pady=1)

    def _pick_folder(self, name: str) -> None:
        self.folder = name
        self.fill_folders()
        self.fill_list()

    def fill_list(self) -> None:
        c = self.colors
        for child in self.list_box.winfo_children():
            child.destroy()
        if self.folder == "Quick notes":
            from jarvis import notes as quick

            for note in reversed(quick.load_notes()[-80:]):
                label(self.list_box, f"• {note.get('text', '')[:60]}", size=11, wrap=200).pack(anchor="w", pady=2)
            return
        hits = work.search_notes(self.search.get())
        if self.folder != "All":
            hits = [n for n in hits if (n.get("folder") or "Notes") == self.folder]
        for note in hits:
            ctk.CTkButton(self.list_box, text=f"{note['title'][:28]}\n{note.get('body', '')[:30]}", anchor="w",
                          height=44, fg_color=c["accent_dim"] if self.current and note["id"] == self.current.get("id")
                          else "transparent", hover_color=c["accent_dim"], text_color=c["text"],
                          command=lambda n=note: self.open(n)).pack(fill="x", pady=1)

    def new_note(self, title: str = "") -> None:
        self.current = None
        self.title_entry.delete(0, "end")
        if title:
            self.title_entry.insert(0, title)
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, self.folder if self.folder not in {"All", "Quick notes"} else "Notes")
        self.text.delete("1.0", "end")
        self.backlinks.configure(text="")
        self.text.focus_set()

    def open(self, note: dict) -> None:
        self.current = note
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, note.get("title", ""))
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, note.get("folder", "Notes"))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", note.get("body", ""))
        self._mark_links()
        back = work.backlinks(note.get("title", ""))
        self.backlinks.configure(text=("Linked from: " + ", ".join(n["title"] for n in back)) if back else "")
        self.fill_list()

    def save(self) -> None:
        title = self.title_entry.get().strip()
        body = self.text.get("1.0", "end").rstrip()
        if not title and not body:
            return
        note = dict(self.current or {})
        note.update(title=title or body.splitlines()[0][:60], body=body,
                    folder=self.folder_entry.get().strip() or "Notes")
        self.current = work.save_note(note)
        self.saved.configure(text=f"Saved {time.strftime('%H:%M:%S')}")
        self.fill_folders()
        self.fill_list()

    def delete(self) -> None:
        if self.current:
            work.delete_note(self.current["id"])
        self.new_note()
        self.fill_folders()
        self.fill_list()

    def _mark_links(self) -> None:
        self.text.tag_remove("link", "1.0", "end")
        body = self.text.get("1.0", "end")
        for match in work.LINK.finditer(body):
            self.text.tag_add("link", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def _follow(self, event) -> str:
        index = self.text.index(f"@{event.x},{event.y}")
        body = self.text.get("1.0", "end")
        offset = len(self.text.get("1.0", index))
        for match in work.LINK.finditer(body):
            if match.start() <= offset <= match.end():
                self.save()
                target = work.by_title(match.group(1))
                if target:
                    self.open(target)
                else:
                    self.new_note(match.group(1).strip())
                break
        return "break"

    # --- bookmarks ------------------------------------------------------------
    def _bookmarks(self, tab) -> None:
        c = self.colors
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=4)
        self.bm_url = ctk.CTkEntry(row, placeholder_text="https://… and tags", fg_color=c["bg"])
        self.bm_url.pack(side="left", fill="x", expand=True)
        self.bm_url.bind("<Return>", lambda e: self.add_bookmark())
        button(row, "Save", self.add_bookmark, accent=True).pack(side="left", padx=6)
        button(row, "Import from Chrome / Edge", self.import_bookmarks).pack(side="left")
        self.bm_search = ctk.CTkEntry(tab, placeholder_text="Search bookmarks…", fg_color=c["bg"])
        self.bm_search.pack(fill="x", padx=4)
        self.bm_search.bind("<KeyRelease>", lambda e: self.fill_bookmarks())
        self.bm_list = ctk.CTkScrollableFrame(tab, fg_color=c["bg"])
        self.bm_list.pack(fill="both", expand=True, padx=4, pady=4)

    def fill_bookmarks(self) -> None:
        for child in self.bm_list.winfo_children():
            child.destroy()
        items = work.BOOKMARKS.load()
        words = self.bm_search.get().lower().split()
        shown = 0
        for i, b in enumerate(items):
            hay = f"{b.get('title', '')} {b.get('url', '')} {' '.join(b.get('tags', []))}".lower()
            if words and not all(w in hay for w in words):
                continue
            row = ctk.CTkFrame(self.bm_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkButton(row, text=f"🔖 {b.get('title', '')[:80]}", anchor="w", fg_color="transparent",
                          hover_color=self.colors["accent_dim"], text_color=self.colors["text"],
                          command=lambda u=b["url"]: webbrowser.open(u)).pack(side="left", fill="x", expand=True)
            tags = " ".join("#" + t for t in b.get("tags", []))
            label(row, tags, size=10, muted=True).pack(side="left", padx=6)
            button(row, "✕", lambda n=i: self._delete_bookmark(n), width=24, height=22).pack(side="right")
            shown += 1
            if shown >= 300:
                break
        if not shown:
            label(self.bm_list, "No bookmarks yet." if not items else "Nothing matches.", muted=True).pack(anchor="w")

    def add_bookmark(self) -> None:
        text = self.bm_url.get().strip()
        if not text:
            return
        self.bm_url.delete(0, "end")
        self.app.run_tool(f"/bookmark add {text}", lambda r: self.fill_bookmarks(), name="bookmark")

    def import_bookmarks(self) -> None:
        self.app.run_tool("/bookmark import", lambda r: (self.fill_bookmarks(), self.app.status_label.configure(
            text=str(getattr(r, "text", r))[:90])), name="bookmark")

    def _delete_bookmark(self, index: int) -> None:
        items = work.BOOKMARKS.load()
        if 0 <= index < len(items):
            items.pop(index)
            work.BOOKMARKS.save(items)
        self.fill_bookmarks()


class InboxPage(Page):
    key = "inbox"
    title = "Inbox"
    icon = "📥"

    def build(self) -> None:
        from jarvis.social import MAIL

        c = self.colors
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 6))
        label(top, "📥  Inbox", size=22, bold=True, text_color=c["accent"]).pack(side="left")
        self.account = label(top, "", size=12, muted=True)
        self.account.pack(side="left", padx=12)
        button(top, "↻ Refresh", self.refresh, accent=True).pack(side="right")
        button(top, "Summarise all", lambda: self.app.run_tool("/inbox", self.detail.show, name="inbox")).pack(
            side="right", padx=6)
        button(top, "Connect an account", lambda: self.app.run_in_chat("/inbox setup")).pack(side="right")
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.list = ctk.CTkScrollableFrame(body, fg_color=c["panel"], width=330)
        self.list.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        right = ctk.CTkScrollableFrame(body, fg_color=c["panel"])
        right.grid(row=0, column=1, sticky="nsew")
        self.subject = label(right, "Pick an email", size=16, bold=True, wrap=600)
        self.subject.pack(anchor="w", padx=12, pady=(10, 0))
        self.sender = label(right, "", size=11, muted=True)
        self.sender.pack(anchor="w", padx=12)
        row = ctk.CTkFrame(right, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        button(row, "Summarise", self.summarise).pack(side="left")
        button(row, "✉ Draft a reply in my tone", self.reply, accent=True).pack(side="left", padx=6)
        self.body_text = ctk.CTkTextbox(right, height=220, wrap="word", fg_color=c["bg"])
        self.body_text.pack(fill="x", padx=12)
        self.detail = ResultView(right, self.app)
        self.detail.pack(fill="x", padx=12, pady=6)
        tone = Card(right, "My writing tone", "Paste one or two of your own emails once; drafts then sound like you.",
                    "✒")
        tone.pack(fill="x", padx=12, pady=10)
        form = self.tool(tone.inner, "mytone", show_help=False)
        if form:
            form.pack(fill="x")
        self.mails: list[dict] = []
        self.current: dict | None = None
        user = MAIL.load().get("user")
        self.account.configure(text=user or "No email account connected yet.")

    def on_show(self) -> None:
        if not self.mails:
            self.refresh()

    def refresh(self) -> None:
        from jarvis.social import MAIL, fetch_mail

        account = MAIL.load()
        if not account.get("user"):
            self.account.configure(text="No email account connected — press Connect an account.")
            return
        self.account.configure(text=f"{account['user']} — checking…")

        def done(result):
            if isinstance(result, str):
                self.account.configure(text=result)
                return
            self.mails = result
            self.account.configure(text=f"{account['user']} — {sum(m['unread'] for m in result)} unread of "
                                        f"{len(result)} recent")
            self.fill()

        self.run(lambda: fetch_mail(account, limit=30, hours=96), done,
                 lambda e: self.account.configure(text=f"Couldn't check mail: {e}"))

    def fill(self) -> None:
        c = self.colors
        for child in self.list.winfo_children():
            child.destroy()
        for mail in self.mails:
            text = f"{'●' if mail['unread'] else '○'} {mail['from'][:34]}\n{mail['subject'][:44]}"
            ctk.CTkButton(self.list, text=text, anchor="w", height=48, fg_color="transparent",
                          hover_color=c["accent_dim"], text_color=c["text"],
                          command=lambda m=mail: self.open(m)).pack(fill="x", pady=1)

    def open(self, mail: dict) -> None:
        self.current = mail
        self.subject.configure(text=mail["subject"] or "(no subject)")
        self.sender.configure(text=mail["from"])
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", mail.get("body", ""))
        self.detail.clear()

    def summarise(self) -> None:
        if not self.current:
            return
        from jarvis import shield

        mail = self.current
        wrapped, _ = shield.wrap(mail.get("body", "")[:8000], "an email")

        def work_():
            return self.app.jarvis.brain.ask_once(
                f"{shield.RULE}\n\nSummarise this email in 2-4 bullet points; say first if it needs a reply or "
                f"action, and by when.\n\nFrom: {mail['from']}\nSubject: {mail['subject']}\n\n{wrapped}")

        self.run(work_, self.detail.show)

    def reply(self) -> None:
        if not self.current:
            return
        mail = self.current
        text = f"From: {mail['from']}\nSubject: {mail['subject']}\n\n{mail.get('body', '')[:6000]}"
        self.app.run_tool(f"/draft {text.replace('|', '/')}", self.detail.show, name="draft")
