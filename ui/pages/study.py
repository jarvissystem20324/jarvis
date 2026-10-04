"""Study (10.0): a Pomodoro timer that logs your time, today's progress and
streak, exam countdowns, study sounds, practice games, the timetable, and
every study tool as a form."""

from __future__ import annotations

import random
import re
import time
import tkinter
from datetime import date, datetime

import customtkinter as ctk

from jarvis import alerts, noise
from jarvis.ten import school
from ui.pages.base import Card, Hub, button, label


class StudyPage(Hub):
    key = "study"
    title = "Study"
    icon = "🎓"
    subtitle = "Focus with the timer, keep your streak, practise, and let JARVIS make tests, sheets and plans."

    def build_body(self) -> None:
        self._pomodoro()
        self._today()
        self._sounds()
        self._timetable_card()
        self.section("Practice games")
        self._game(TimesTables)
        self._game(MentalMath)
        self._game(SpellingBee)
        self._game(SpeedReader)
        self.section("Plan and track")
        self.tools("assignment", "exam", "grade", "timetable", "studygoal", "studyreport", "focusapps", "studyplan")
        self.section("Maths and science")
        self.tools("plot", "geometry", "base", "balance", "molar", "biodiagram", "solve")
        self.section("Learn from your material")
        self.tools("practicetest", "ytquiz", "lecturenotes", "formulasheet", "comprehension", "vocab", "flashcards",
                   "quiz")
        self.section("Writing")
        self.tools("essaygrade", "essaycheck", "gradelevel", "bookreport")
        self.section("Projects")
        self.tools("sciencefair", "labreport")
        self.section("For teachers")
        self.tools("lessonplan", "teacherworksheet", "rubric", "worksheet")

    def _game(self, cls) -> None:
        card = self.card(cls.TITLE, cls.SUBTITLE, cls.ICON)
        cls(card.inner, self).pack(fill="both", expand=True)

    # --- Pomodoro ------------------------------------------------------------------
    def _pomodoro(self) -> None:
        c = self.colors
        card = self.card("Focus timer", "Pomodoro: focus, then a short break. Finished sessions are logged.", "🍅")
        self.timer_label = label(card.inner, "25:00", size=52, bold=True, text_color=c["accent"])
        self.timer_label.pack(anchor="center")
        self.phase_label = label(card.inner, "Ready", size=13, muted=True)
        self.phase_label.pack(anchor="center")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self.subject = ctk.CTkEntry(row, placeholder_text="Subject (Maths, History…)", fg_color=c["bg"])
        self.subject.pack(side="left", fill="x", expand=True)
        self.lengths = ctk.CTkOptionMenu(row, values=["25 / 5", "50 / 10", "15 / 3", "90 / 15"], width=100,
                                         fg_color=c["bg"], button_color=c["accent_dim"],
                                         command=lambda v: self.reset_timer())
        self.lengths.pack(side="left", padx=6)
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        self.start_btn = button(row, "▶ Start", self.start_timer, accent=True, width=90)
        self.start_btn.pack(side="left")
        button(row, "↺ Reset", self.reset_timer, width=80).pack(side="left", padx=6)
        button(row, "⏭ Skip", self.skip_phase, width=70).pack(side="left")
        self.close_apps = tkinter.BooleanVar(value=False)
        ctk.CTkCheckBox(card.inner, text="Close distracting apps when a focus session starts",
                        variable=self.close_apps, checkbox_width=16, checkbox_height=16).pack(anchor="w", pady=(8, 0))
        self.running = False
        self.phase = "focus"
        self.left = 25 * 60
        self.done_today = 0
        self._tick_job = None

    def _durations(self) -> tuple[int, int]:
        focus, rest = (int(x) for x in self.lengths.get().split("/"))
        return focus, rest

    def reset_timer(self) -> None:
        self.running = False
        self.phase = "focus"
        self.left = self._durations()[0] * 60
        self.start_btn.configure(text="▶ Start")
        self.phase_label.configure(text="Ready")
        self._show_time()

    def start_timer(self) -> None:
        self.running = not self.running
        self.start_btn.configure(text="⏸ Pause" if self.running else "▶ Resume")
        self.phase_label.configure(text="Focus" if self.phase == "focus" else "Break")
        if self.running and self.phase == "focus" and self.close_apps.get() and self.left == self._durations()[0] * 60:
            self.app.run_tool("/focusapps close", lambda r: self.app.status_label.configure(
                text=str(getattr(r, "text", r))[:90]), name="focusapps")
        if self.running and self._tick_job is None:
            self._tick_job = self.after(1000, self._tick)

    def _tick(self) -> None:
        self._tick_job = None
        if not self.running:
            return
        self.left -= 1
        if self.left <= 0:
            self._finish_phase()
        self._show_time()
        self._tick_job = self.after(1000, self._tick)

    def skip_phase(self) -> None:
        self.left = 0
        self._finish_phase()
        self._show_time()

    def _finish_phase(self) -> None:
        focus, rest = self._durations()
        if self.phase == "focus":
            minutes = focus - max(0, self.left) / 60
            if minutes >= 1:
                school.log_study(minutes, self.subject.get())
            self.done_today += 1
            self.phase = "break"
            self.left = rest * 60
            alerts.post("Focus session done 🍅", f"Take a {rest}-minute break.", page="study", kind="ok")
            self.refresh_today()
        else:
            self.phase = "focus"
            self.left = focus * 60
            alerts.post("Break's over", "Ready for the next focus session?", page="study")
        self.phase_label.configure(text="Focus" if self.phase == "focus" else "Break")
        try:
            self.bell()
        except tkinter.TclError:
            pass

    def _show_time(self) -> None:
        minutes, seconds = divmod(max(0, self.left), 60)
        self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}",
                                   text_color=self.colors["accent"] if self.phase == "focus" else self.colors["ok"])

    # --- today ---------------------------------------------------------------------
    def _today(self) -> None:
        card = self.card("Today", "", "📆")
        self.today_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.today_box.pack(fill="both", expand=True)

    def on_show(self) -> None:
        self.refresh_today()
        self.refresh_timetable()

    def refresh_today(self) -> None:
        c = self.colors
        for child in self.today_box.winfo_children():
            child.destroy()
        log = school.STUDY_LOG.load()
        today = school.minutes_by_day(log, 1)[0][1]
        goal = school.STUDY_GOAL.load().get("daily", 60)
        label(self.today_box, f"{today:g} of {goal} minutes", size=18, bold=True).pack(anchor="w")
        bar = ctk.CTkProgressBar(self.today_box, height=12, progress_color=c["ok"] if today >= goal else c["accent"])
        bar.set(min(1.0, today / max(1, goal)))
        bar.pack(fill="x", pady=4)
        label(self.today_box, f"🔥 Streak: {school.streak(log)} day(s)", size=13).pack(anchor="w")
        try:
            nxt = self.app.jarvis.timetable_cmd("next")
            if nxt.startswith("Next"):
                label(self.today_box, "🗓 " + nxt, size=12).pack(anchor="w", pady=(6, 0))
        except Exception:
            pass
        exams = [e for e in school.EXAMS.load() if date.fromisoformat(e["date"]) >= date.today()][:4]
        if exams:
            row = ctk.CTkFrame(self.today_box, fg_color="transparent")
            row.pack(fill="x", pady=6)
            for exam in exams:
                days = (date.fromisoformat(exam["date"]) - date.today()).days
                chip = ctk.CTkFrame(row, fg_color=c["bg"], corner_radius=10)
                chip.pack(side="left", padx=(0, 6))
                label(chip, str(days), size=24, bold=True, text_color=c["error"] if days < 8 else c["accent"]).pack(
                    padx=10)
                label(chip, f"days · {exam['name'][:14]}", size=10, muted=True).pack(padx=8, pady=(0, 6))
        due = sorted((a for a in school.ASSIGNMENTS.load() if not a.get("done")), key=lambda a: a.get("due") or 9e12)
        for a in due[:4]:
            when = f" — {datetime.fromtimestamp(a['due']):%a %d %b}" if a.get("due") else ""
            label(self.today_box, f"📚 {a['title']}{when}", size=12).pack(anchor="w")

    # --- sounds ----------------------------------------------------------------------
    def _sounds(self) -> None:
        card = self.card("Study sounds", "Noise that hides chatter. Made on the fly, nothing downloaded.", "🎧")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        for kind, text in (("white", "White"), ("pink", "Pink"), ("brown", "Brown"), ("rain", "🌧 Rain")):
            button(row, text, lambda k=kind: self.play_noise(k), width=70).pack(side="left", padx=2)
        button(row, "■ Stop", self.stop_noise, width=60).pack(side="left", padx=8)
        self.volume = ctk.CTkSlider(card.inner, from_=0, to=1, command=lambda v: noise.player.set_volume(float(v)))
        self.volume.set(noise.player.volume)
        self.volume.pack(fill="x", pady=8)
        self.noise_note = label(card.inner, "", size=11, muted=True)
        self.noise_note.pack(anchor="w")

    def play_noise(self, kind: str) -> None:
        try:
            noise.player.play(kind, self.volume.get())
            self.noise_note.configure(text=f"Playing {kind} noise.")
        except Exception as exc:
            self.noise_note.configure(text=f"No sound output: {exc}")

    def stop_noise(self) -> None:
        noise.player.stop()
        self.noise_note.configure(text="Stopped.")

    def close(self) -> None:
        noise.player.stop()
        super().close()

    # --- timetable -----------------------------------------------------------------------
    def _timetable_card(self) -> None:
        card = self.card("This week's classes", "Add classes with the Class timetable form below.", "🗓")
        self.tt = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.tt.pack(fill="both", expand=True)

    def refresh_timetable(self) -> None:
        c = self.colors
        for child in self.tt.winfo_children():
            child.destroy()
        rows = school.TIMETABLE.load()
        if not rows:
            label(self.tt, "No classes yet.", muted=True).pack(anchor="w")
            return
        today = datetime.now().weekday()
        for d in range(7):
            classes = [r for r in rows if r["day"] == d]
            if not classes:
                continue
            line = ctk.CTkFrame(self.tt, fg_color=c["accent_dim"] if d == today else "transparent", corner_radius=6)
            line.pack(fill="x", pady=1)
            label(line, school.DAYS[d].capitalize(), size=12, bold=True, width=44).pack(side="left", padx=4)
            label(line, " · ".join(f"{r['start']} {r['subject']}" for r in classes), size=12, wrap=420).pack(
                side="left")


class _Drill(ctk.CTkFrame):
    """A 60-second question-and-answer round with a best score."""

    TITLE = ""
    SUBTITLE = ""
    ICON = ""
    ROUND = 60

    def __init__(self, parent, page):
        c = page.colors
        super().__init__(parent, fg_color="transparent")
        self.page = page
        self.colors = c
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x")
        self.options(top)
        button(top, "▶ Start", self.start, accent=True, width=70).pack(side="right")
        self.question = label(self, "Press Start", size=30, bold=True, text_color=c["accent"])
        self.question.pack(pady=6)
        self.answer = ctk.CTkEntry(self, font=ctk.CTkFont(size=18), justify="center", fg_color=c["bg"])
        self.answer.pack(fill="x")
        self.answer.bind("<Return>", lambda e: self.check())
        self.status = label(self, "", size=12, muted=True)
        self.status.pack(pady=4)
        self.score = 0
        self.left = 0
        self.correct = ""

    def options(self, parent) -> None:
        pass

    def best_key(self) -> str:
        return f"best_{type(self).__name__}"

    def start(self) -> None:
        self.score = 0
        self.left = self.ROUND
        self.next_question()
        self.answer.focus_set()
        self._tick()

    def _tick(self) -> None:
        if self.left <= 0:
            return
        self.left -= 1
        if self.left == 0:
            from jarvis import prefs

            best = prefs.get(self.best_key(), 0)
            if self.score > best:
                prefs.set(self.best_key(), self.score)
            self.question.configure(text=f"⏱ {self.score} right!")
            self.status.configure(text=f"Best: {max(best, self.score)}" + ("  🏆 new best!" if self.score > best else ""))
            return
        self.status.configure(text=f"{self.left}s · score {self.score}")
        self.after(1000, self._tick)

    def check(self) -> None:
        if self.left <= 0:
            return
        given = self.answer.get().strip().replace(",", ".")
        if given and given.lower() == str(self.correct).lower():
            self.score += 1
            self.status.configure(text=f"✔ {self.left}s · score {self.score}", text_color=self.colors["ok"])
        else:
            self.status.configure(text=f"✘ it was {self.correct}", text_color=self.colors["error"])
        self.answer.delete(0, "end")
        self.next_question()

    def next_question(self) -> None:
        raise NotImplementedError


class TimesTables(_Drill):
    TITLE = "Times tables"
    SUBTITLE = "60 seconds — how many can you get?"
    ICON = "✖"

    def options(self, parent) -> None:
        self.table = ctk.CTkOptionMenu(parent, values=["mixed"] + [str(n) for n in range(2, 13)], width=90,
                                       fg_color=self.colors["bg"], button_color=self.colors["accent_dim"])
        self.table.pack(side="left")

    def next_question(self) -> None:
        a = random.randint(2, 12) if self.table.get() == "mixed" else int(self.table.get())
        b = random.randint(1, 12)
        self.correct = str(a * b)
        self.question.configure(text=f"{a} × {b}")


class MentalMath(_Drill):
    TITLE = "Mental maths"
    SUBTITLE = "Quick sums against the clock."
    ICON = "🧠"

    def options(self, parent) -> None:
        self.level = ctk.CTkSegmentedButton(parent, values=["easy", "medium", "hard"])
        self.level.set("easy")
        self.level.pack(side="left")

    def next_question(self) -> None:
        top = {"easy": 20, "medium": 100, "hard": 500}[self.level.get() or "easy"]
        op = random.choice("+−×÷")
        if op == "+":
            a, b = random.randint(1, top), random.randint(1, top)
            self.correct = str(a + b)
        elif op == "−":
            a, b = sorted((random.randint(1, top), random.randint(1, top)), reverse=True)
            self.correct = str(a - b)
        elif op == "×":
            a, b = random.randint(2, max(5, top // 10)), random.randint(2, 12)
            self.correct = str(a * b)
        else:
            b, q = random.randint(2, 12), random.randint(2, max(5, top // 10))
            a = b * q
            self.correct = str(q)
        self.question.configure(text=f"{a} {op} {b}")


class SpellingBee(_Drill):
    TITLE = "Spelling bee"
    SUBTITLE = "Listen, then type the word. 🔊 says it again."
    ICON = "🐝"
    ROUND = 120

    def options(self, parent) -> None:
        self.level = ctk.CTkOptionMenu(parent, values=list(school.SPELLING), width=90, fg_color=self.colors["bg"],
                                       button_color=self.colors["accent_dim"])
        self.level.pack(side="left")
        button(parent, "🔊", self.say, width=40).pack(side="left", padx=6)

    def next_question(self) -> None:
        self.correct = random.choice(school.SPELLING[self.level.get()].split())
        self.question.configure(text="🔊 " + "_ " * len(self.correct))
        self.after(150, self.say)

    def say(self) -> None:
        if not self.correct:
            return
        try:
            language = "tr" if self.level.get() == "tr" else "en"
            self.page.app.jarvis.voice.speak(self.correct, language=language)
        except Exception:
            self.status.configure(text="No voice available — the first letter is " + self.correct[0])


class SpeedReader(ctk.CTkFrame):
    """One word at a time, at a pace you choose."""

    TITLE = "Speed reading"
    SUBTITLE = "Paste a text; words flash one at a time at your pace."
    ICON = "⚡"

    def __init__(self, parent, page):
        c = page.colors
        super().__init__(parent, fg_color="transparent")
        self.colors = c
        self.text = ctk.CTkTextbox(self, height=80, fg_color=c["bg"], wrap="word")
        self.text.insert("1.0", "Reading faster is mostly about fewer pauses. Your eyes stop on almost every word; "
                                "here the words come to you, so practise keeping up, then raise the speed.")
        self.text.pack(fill="x")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=4)
        self.wpm = ctk.CTkSlider(row, from_=150, to=900, number_of_steps=15, command=lambda v: self.wpm_label.configure(
            text=f"{int(v)} wpm"))
        self.wpm.set(300)
        self.wpm.pack(side="left", fill="x", expand=True)
        self.wpm_label = label(row, "300 wpm", size=11, width=70)
        self.wpm_label.pack(side="left")
        button(row, "▶", self.start, accent=True, width=40).pack(side="left", padx=4)
        button(row, "■", self.stop, width=40).pack(side="left")
        self.word = label(self, "", size=34, bold=True, text_color=c["accent"])
        self.word.pack(pady=10)
        self.words: list[str] = []
        self.index = 0
        self.running = False

    def start(self) -> None:
        self.words = self.text.get("1.0", "end").split()
        self.index = 0
        self.running = True
        self._next()

    def stop(self) -> None:
        self.running = False

    def _next(self) -> None:
        if not self.running or self.index >= len(self.words):
            if self.running:
                self.word.configure(text="✔ done")
            self.running = False
            return
        word = self.words[self.index]
        self.word.configure(text=word)
        self.index += 1
        delay = 60000 / max(60, self.wpm.get())
        if word.endswith((".", "!", "?", ";", ":")):
            delay *= 1.8
        elif word.endswith(","):
            delay *= 1.3
        self.after(int(delay), self._next)
