"""Everyday, Health, Money and Türkiye (10.0).

Each page puts the day-to-day things in front of you — the moon and your
clocks, today's water and habits, this month's budgets, Istanbul's traffic —
with the tools to change them right there. The logic is in jarvis/daily.py,
jarvis/money.py and jarvis/turkey.py; these pages only draw it.
"""

from __future__ import annotations

import math
import threading
import time
import tkinter
from datetime import date, datetime, timedelta

import customtkinter as ctk

from jarvis import daily, money, prefs, spending, turkey
from ui.pages.base import Hub, button, label, open_path, plain


def _bar(parent, share: float, colour: str, width: int = 260) -> tkinter.Canvas:
    """A thin progress bar (plain canvas: dozens of them stay cheap)."""
    from ui.pages.base import colors

    c = colors()
    bar = tkinter.Canvas(parent, width=width, height=8, bg=c["bg"], highlightthickness=0)
    bar.create_rectangle(0, 0, int(width * max(0.0, min(1.0, share))), 8, fill=colour, width=0)
    return bar


# --- Everyday --------------------------------------------------------------------------------------

class EverydayPage(Hub):
    key = "everyday"
    title = "Everyday"
    icon = "☀"
    subtitle = "The moon, your clocks, what to wear, warranties, where things are, decluttering and the kitchen."

    def build_body(self) -> None:
        c = self.colors
        today = self.card("Today", "", "🌙")
        self.moon_label = label(today.inner, "", size=13, wrap=420)
        self.moon_label.pack(anchor="w")
        self.wear_box = plain(today.inner)
        self.wear_box.pack(fill="x", pady=(8, 0))

        clocks = self.card("World clocks", "Add any city; they tick here.", "🕰")
        self.clock_box = plain(clocks.inner)
        self.clock_box.pack(fill="x")
        row = plain(clocks.inner)
        row.pack(fill="x", pady=(6, 0))
        self.city = ctk.CTkEntry(row, placeholder_text="City: Tokyo, Berlin…", fg_color=c["bg"])
        self.city.pack(side="left", fill="x", expand=True)
        self.city.bind("<Return>", lambda e: self.add_city())
        button(row, "＋", self.add_city, width=34, height=28).pack(side="left", padx=4)
        self.clock_labels: list[tuple[tkinter.Label, object]] = []

        stuff = self.card("Where did I put it?", "Tell me where things are; ask later.", "📦")
        row = plain(stuff.inner)
        row.pack(fill="x")
        self.find = ctk.CTkEntry(row, placeholder_text="Find: passport, spare key…", fg_color=c["bg"])
        self.find.pack(side="left", fill="x", expand=True)
        self.find.bind("<KeyRelease>", lambda e: self.show_stash())
        self.stash_box = plain(stuff.inner)
        self.stash_box.pack(fill="x", pady=(6, 0))

        clutter = self.card("Declutter", "One room at a time; ticks are saved.", "🧹")
        self.room = ctk.CTkOptionMenu(clutter.inner, values=list(daily.CHECKLISTS), width=200, fg_color=c["bg"],
                                      button_color=c["accent_dim"], command=lambda v: self.show_room())
        self.room.pack(anchor="w")
        self.room_box = plain(clutter.inner)
        self.room_box.pack(fill="x", pady=(6, 0))

        warranty = self.card("Warranties", "Soonest to run out first. I'll remind you 30 and 7 days before.", "🧾",
                             span=2)
        self.warranty_box = plain(warranty.inner)
        self.warranty_box.pack(fill="x")

        self.section("Tools")
        self.tools("warranty", "putit", "age", "datediff", "kitchen", "scale", "grocery", "fridgephoto")
        self.every("clocks", 1000, self.tick_clocks)

    def on_show(self) -> None:
        m = daily.moon()
        self.moon_label.configure(text=f"{m['emoji']}  {m['name']} — {m['lit'] * 100:.0f}% lit\n"
                                       f"Full moon {m['next_full']:%a %d %b} · new moon {m['next_new']:%a %d %b}")
        self.load_wear()
        self.draw_clocks()
        self.show_stash()
        self.show_room()
        self.show_warranties()

    def load_wear(self) -> None:
        from jarvis import weather

        for child in self.wear_box.winfo_children():
            child.destroy()
        city = weather.home_city()
        if not city:
            label(self.wear_box, "Set your city in Settings to see what to wear.", size=11, muted=True).pack(
                anchor="w")
            return

        def done(day):
            if not isinstance(day, dict):
                label(self.wear_box, str(day), size=11, muted=True, wrap=420).pack(anchor="w")
                return
            label(self.wear_box, f"{day['place']}: {day['low']:.0f}°–{day['high']:.0f}°, rain {day['rain']:.0f}%",
                  size=12, bold=True).pack(anchor="w")
            for line in daily.what_to_wear(day["low"], day["high"], day["rain"], day["wind"], day["uv"]):
                label(self.wear_box, line, size=11, wrap=420).pack(anchor="w")

        self.run(lambda: daily.day_forecast(city), done, lambda exc: done(f"No forecast: {exc}"))

    # clocks
    def draw_clocks(self) -> None:
        from jarvis import clock

        for child in self.clock_box.winfo_children():
            child.destroy()
        self.clock_labels = []
        for city in prefs.get("world_clocks", ["Istanbul", "London", "New York", "Tokyo"]):
            try:
                name, zone = clock.zone_for(city)
            except clock.ClockError:
                continue
            row = plain(self.clock_box)
            row.pack(fill="x")
            label(row, name, size=12, width=140).pack(side="left")
            time_label = label(row, "", size=16, bold=True)
            time_label.pack(side="left")
            button(row, "✕", lambda c=city: self.remove_city(c), width=26, height=22).pack(side="right")
            self.clock_labels.append((time_label, zone))
        self.tick_clocks()

    def tick_clocks(self) -> None:
        for time_label, zone in self.clock_labels:
            now = datetime.now(zone)
            try:
                time_label.configure(text=f"{now:%H:%M:%S}  {now:%a}")
            except tkinter.TclError:
                pass

    def add_city(self) -> None:
        city = self.city.get().strip()
        if city:
            reply = self.app.jarvis.worldclock_cmd(f"add {city}")
            if reply.startswith("🕰"):
                self.city.delete(0, "end")
            self.draw_clocks()

    def remove_city(self, city: str) -> None:
        prefs.set("world_clocks", [c for c in prefs.get("world_clocks", []) if c.lower() != city.lower()] or
                  ["Istanbul"])
        self.draw_clocks()

    # stash, rooms, warranties
    def show_stash(self) -> None:
        for child in self.stash_box.winfo_children():
            child.destroy()
        query = self.find.get().strip()
        rows = daily.stash_find(query) if query else list(reversed(daily.STASH.load()))[:8]
        if not rows:
            label(self.stash_box, "Nothing yet — use “Where I put it” below." if not query else "Not noted.",
                  size=11, muted=True).pack(anchor="w")
        for row in rows[:8]:
            label(self.stash_box, f"{row['thing']} → {row['place']}", size=12).pack(anchor="w")

    def show_room(self) -> None:
        for child in self.room_box.winfo_children():
            child.destroy()
        room = self.room.get()
        done = set(daily.DECLUTTER.load().get(room, []))
        for i, item in enumerate(daily.CHECKLISTS[room]):
            var = tkinter.BooleanVar(value=i in done)
            ctk.CTkCheckBox(self.room_box, text=item, variable=var,
                            command=lambda n=i, v=var: self.tick_room(n, v.get())).pack(anchor="w", pady=1)

    def tick_room(self, index: int, on: bool) -> None:
        state = daily.DECLUTTER.load()
        room = self.room.get()
        items = set(state.get(room, []))
        items = items | {index} if on else items - {index}
        state[room] = sorted(items)
        daily.DECLUTTER.save(state)

    def show_warranties(self) -> None:
        for child in self.warranty_box.winfo_children():
            child.destroy()
        rows = daily.warranties()
        if not rows:
            label(self.warranty_box, "None yet — add one with the Warranty tracker below.", size=11, muted=True).pack(
                anchor="w")
        for row in rows:
            left = row["days_left"]
            colour = self.colors["error"] if left < 30 else self.colors["text"]
            state = "expired" if left < 0 else f"{left} days left"
            label(self.warranty_box, f"{row['item']} — until {date.fromisoformat(row['until']):%d %b %Y} ({state})"
                  + (f" · {row['note']}" if row.get("note") else ""), size=12, text_color=colour).pack(anchor="w")


# --- Health ------------------------------------------------------------------------------------------

TIMERS = {"Tabata 20/10 × 8": (20, 10, 8), "HIIT 40/20 × 10": (40, 20, 10), "HIIT 30/30 × 12": (30, 30, 12),
          "EMOM 60 × 10": (60, 0, 10)}
BREATHING = {"Box 4-4-4-4": ((4, "Breathe in"), (4, "Hold"), (4, "Breathe out"), (4, "Hold")),
             "4-7-8 (to relax)": ((4, "Breathe in"), (7, "Hold"), (8, "Breathe out")),
             "Calm 5-5": ((5, "Breathe in"), (5, "Breathe out"))}


class HealthPage(Hub):
    key = "health"
    title = "Health"
    icon = "💚"
    subtitle = "Water, habits, a workout timer, breathing, weight and BMI — general wellbeing, not medical advice."

    def build_body(self) -> None:
        c = self.colors
        water = self.card("Water today", "", "💧")
        self.water_label = label(water.inner, "", size=20, bold=True, text_color=c["accent"])
        self.water_label.pack(anchor="w")
        self.water_bar = plain(water.inner)
        self.water_bar.pack(fill="x", pady=4)
        row = plain(water.inner)
        row.pack(fill="x", pady=(4, 0))
        for amount, text in ((250, "+ glass"), (500, "+ bottle"), (-250, "−")):
            button(row, text, lambda a=amount: self.drink(a), height=28, accent=amount == 250).pack(side="left",
                                                                                                    padx=(0, 4))
        self.remind = tkinter.BooleanVar(value=daily.HEALTH.load().get("water_reminders", False))
        ctk.CTkSwitch(water.inner, text="Remind me when I fall behind", variable=self.remind,
                      command=lambda: self.app.jarvis.water_cmd("remind " + ("on" if self.remind.get() else "off"))
                      ).pack(anchor="w", pady=(8, 0))

        habits = self.card("Habits", "Tick today; the dots are the last 7 days.", "✅")
        self.habit_box = plain(habits.inner)
        self.habit_box.pack(fill="x")
        row = plain(habits.inner)
        row.pack(fill="x", pady=(6, 0))
        self.new_habit = ctk.CTkEntry(row, placeholder_text="New habit: Read 20 pages", fg_color=c["bg"])
        self.new_habit.pack(side="left", fill="x", expand=True)
        self.new_habit.bind("<Return>", lambda e: self.add_habit())
        button(row, "＋", self.add_habit, width=34, height=28).pack(side="left", padx=4)

        timer = self.card("Workout timer", "Work and rest intervals with a beep at each change.", "⏱")
        self.preset = ctk.CTkOptionMenu(timer.inner, values=list(TIMERS), width=200, fg_color=c["bg"],
                                        button_color=c["accent_dim"], command=lambda v: self.reset_timer())
        self.preset.pack(anchor="w")
        self.phase = label(timer.inner, "", size=14, bold=True)
        self.phase.pack(anchor="w", pady=(8, 0))
        self.count = label(timer.inner, "", size=44, bold=True, text_color=c["accent"])
        self.count.pack(anchor="w")
        row = plain(timer.inner)
        row.pack(fill="x")
        self.timer_button = button(row, "▶ Start", self.toggle_timer, accent=True, height=30)
        self.timer_button.pack(side="left")
        button(row, "Reset", self.reset_timer, height=30).pack(side="left", padx=6)
        self._timer_job = None

        breathe = self.card("Breathing", "Follow the circle.", "🌬")
        self.pattern = ctk.CTkOptionMenu(breathe.inner, values=list(BREATHING), width=200, fg_color=c["bg"],
                                         button_color=c["accent_dim"])
        self.pattern.pack(anchor="w")
        self.circle = tkinter.Canvas(breathe.inner, width=220, height=220, bg=c["panel"], highlightthickness=0)
        self.circle.pack(anchor="w", pady=6)
        row = plain(breathe.inner)
        row.pack(fill="x")
        self.breathe_button = button(row, "▶ Start", self.toggle_breathing, accent=True, height=30)
        self.breathe_button.pack(side="left")
        self.breaths = label(row, "", size=11, muted=True)
        self.breaths.pack(side="left", padx=8)
        self._breath_job = None

        weight = self.card("Weight", "Log it now and then; the trend matters more than any one day.", "📉", span=2)
        row = plain(weight.inner)
        row.pack(fill="x")
        self.kg = ctk.CTkEntry(row, placeholder_text="kg", width=90, fg_color=c["bg"])
        self.kg.pack(side="left")
        self.kg.bind("<Return>", lambda e: self.log_weight())
        button(row, "Log", self.log_weight, height=28).pack(side="left", padx=6)
        self.weight_note = label(row, "", size=12)
        self.weight_note.pack(side="left", padx=8)
        self.weight_chart = tkinter.Label(weight.inner, bg=c["panel"])
        self.weight_chart.pack(anchor="w", pady=(6, 0))

        self.section("Tools")
        self.tools("bmi", "kcal", "uv", "habit")
        self.reset_timer()
        self.draw_circle(0.35, "Ready")

    def on_show(self) -> None:
        self.show_water()
        self.show_habits()
        self.show_weight()

    def on_hide(self) -> None:
        self.stop_breathing()

    def open_target(self, part: str) -> None:
        fractions = {"timer": 0.35, "breathe": 0.35}
        if part in fractions:
            self.after(100, lambda: self.body._parent_canvas.yview_moveto(fractions[part]))

    # water
    def drink(self, ml: int) -> None:
        daily.add_water(ml)
        self.show_water()

    def show_water(self) -> None:
        total, goal = daily.water_today(), daily.HEALTH.load().get("water_goal", 2000)
        self.water_label.configure(text=f"{total} / {goal} ml" + ("  🎉" if total >= goal else ""))
        for child in self.water_bar.winfo_children():
            child.destroy()
        _bar(self.water_bar, total / goal if goal else 0, self.colors["accent"], 300).pack(anchor="w")

    # habits
    def add_habit(self) -> None:
        name = self.new_habit.get().strip()
        if name:
            self.app.jarvis.habit_cmd(f"add {name}")
            self.new_habit.delete(0, "end")
            self.show_habits()

    def show_habits(self) -> None:
        for child in self.habit_box.winfo_children():
            child.destroy()
        data = daily.HABITS.load()
        if not data:
            label(self.habit_box, "No habits yet.", size=11, muted=True).pack(anchor="w")
        today = date.today()
        for name, days in data.items():
            row = plain(self.habit_box)
            row.pack(fill="x", pady=1)
            dots = "".join("●" if (today - timedelta(days=6 - i)).isoformat() in days else "○" for i in range(7))
            label(row, dots, size=12, text_color=self.colors["accent"]).pack(side="left")
            label(row, f"  {name} · {daily.habit_streak(days)}🔥", size=12).pack(side="left")
            done = today.isoformat() in days
            button(row, "✓ Done" if not done else "Done today", lambda n=name: self.tick_habit(n), height=24,
                   accent=not done, state="normal" if not done else "disabled").pack(side="right")

    def tick_habit(self, name: str) -> None:
        daily.habit_done(name)
        self.show_habits()

    # workout timer
    def reset_timer(self) -> None:
        if self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        work, rest, rounds = TIMERS[self.preset.get()]
        self.plan = []
        for r in range(1, rounds + 1):
            self.plan.append(("WORK", work, r))
            if rest:
                self.plan.append(("REST", rest, r))
        self.plan.insert(0, ("GET READY", 5, 0))
        self.step, self.left, self.running = 0, self.plan[0][1], False
        self.timer_button.configure(text="▶ Start")
        self.show_timer()

    def show_timer(self) -> None:
        name, _, rnd = self.plan[self.step]
        rounds = max(r for _, _, r in self.plan)
        colour = {"WORK": self.colors["error"], "REST": self.colors["ok"]}.get(name, self.colors["muted"])
        self.phase.configure(text=f"{name}" + (f" — round {rnd} of {rounds}" if rnd else ""), text_color=colour)
        self.count.configure(text=f"{self.left // 60}:{self.left % 60:02d}")

    def toggle_timer(self) -> None:
        self.running = not self.running
        self.timer_button.configure(text="⏸ Pause" if self.running else "▶ Start")
        if self.running:
            self._timer_job = self.after(1000, self.tick_timer)
        elif self._timer_job is not None:
            self.after_cancel(self._timer_job)
            self._timer_job = None

    def tick_timer(self) -> None:
        self._timer_job = None
        if not self.running:
            return
        self.left -= 1
        if self.left <= 0:
            self.step += 1
            if self.step >= len(self.plan):
                self.beep(3)
                self.phase.configure(text="Done — well done! 💪", text_color=self.colors["ok"])
                self.count.configure(text="0:00")
                self.running = False
                self.timer_button.configure(text="▶ Start")
                self.step = len(self.plan) - 1
                return
            self.left = self.plan[self.step][1]
            self.beep(2 if self.plan[self.step][0] == "WORK" else 1)
        elif self.left <= 3:
            self.beep(1, short=True)
        self.show_timer()
        self._timer_job = self.after(1000, self.tick_timer)

    def beep(self, times: int = 1, short: bool = False) -> None:
        def play():
            try:
                import winsound

                for _ in range(times):
                    winsound.Beep(1200 if not short else 800, 120 if short else 300)
            except Exception:
                pass

        threading.Thread(target=play, daemon=True).start()

    # breathing
    def toggle_breathing(self) -> None:
        if self._breath_job is not None:
            self.stop_breathing()
            return
        self.breath_steps = BREATHING[self.pattern.get()]
        self.breath_index, self.breath_started, self.breath_count = 0, time.time(), 0
        self.breathe_button.configure(text="⏹ Stop")
        self.animate_breath()

    def stop_breathing(self) -> None:
        if self._breath_job is not None:
            self.after_cancel(self._breath_job)
            self._breath_job = None
        self.breathe_button.configure(text="▶ Start")
        self.draw_circle(0.35, "Ready")

    def animate_breath(self) -> None:
        seconds, words = self.breath_steps[self.breath_index]
        elapsed = time.time() - self.breath_started
        if elapsed >= seconds:
            self.breath_index = (self.breath_index + 1) % len(self.breath_steps)
            self.breath_started = time.time()
            if self.breath_index == 0:
                self.breath_count += 1
                self.breaths.configure(text=f"{self.breath_count} breath(s)")
            seconds, words = self.breath_steps[self.breath_index]
            elapsed = 0.0
        share = elapsed / seconds
        eased = (1 - math.cos(math.pi * share)) / 2
        if words == "Breathe in":
            size = 0.35 + 0.6 * eased
        elif words == "Breathe out":
            size = 0.95 - 0.6 * eased
        else:
            size = 0.95 if self.breath_steps[self.breath_index - 1][1] == "Breathe in" else 0.35
        self.draw_circle(size, f"{words}\n{max(1, math.ceil(seconds - elapsed))}")
        self._breath_job = self.after(50, self.animate_breath)

    def draw_circle(self, size: float, words: str) -> None:
        c = self.colors
        canvas = self.circle
        canvas.delete("all")
        r = 100 * size
        canvas.create_oval(110 - 100, 110 - 100, 110 + 100, 110 + 100, outline=c["accent_dim"], width=2)
        canvas.create_oval(110 - r, 110 - r, 110 + r, 110 + r, fill=c["accent_dim"], outline=c["accent"], width=3)
        canvas.create_text(110, 110, text=words, fill=c["text"], font=("Segoe UI", 13, "bold"), justify="center")

    # weight
    def log_weight(self) -> None:
        text = self.kg.get().strip().replace(",", ".")
        try:
            kg = float(text)
        except ValueError:
            self.weight_note.configure(text="Type your weight in kg.")
            return
        daily.log_weight(kg)
        self.kg.delete(0, "end")
        self.show_weight()

    def show_weight(self) -> None:
        rows = daily.WEIGHTS.load()[-60:]
        if not rows:
            self.weight_note.configure(text="No weights logged yet.")
            return
        change = rows[-1]["kg"] - rows[0]["kg"]
        self.weight_note.configure(text=f"{rows[-1]['kg']} kg" + (f" · {change:+.1f} kg over {len(rows)} entries"
                                                                  if len(rows) > 1 else ""))
        if len(rows) < 2:
            return

        def draw():
            from jarvis import charts

            return charts.render("line", [r["day"][5:] for r in rows], {"kg": [r["kg"] for r in rows]},
                                 title="", size=(760, 260))

        def show(image):
            from PIL import ImageTk

            if image is None or isinstance(image, str):
                return
            self._weight_image = ImageTk.PhotoImage(image, master=self)
            self.weight_chart.configure(image=self._weight_image)

        self.run(draw, show)


# --- Money -------------------------------------------------------------------------------------------

class MoneyPage(Hub):
    key = "money"
    title = "Money"
    icon = "💰"
    subtitle = "Where this month's money went, budgets per category, bank imports and who owes who — tracking only."

    def build_body(self) -> None:
        month = self.card("This month", "From your spending log (/spent 45 lunch).", "📊")
        self.month_box = plain(month.inner)
        self.month_box.pack(fill="x")
        row = plain(month.inner)
        row.pack(fill="x", pady=(8, 0))
        button(row, "⬇ Excel with charts", lambda: self.app.run_tool("/spent export", self.say, name="spent"),
               height=28).pack(side="left")
        self.note = label(month.inner, "", size=11, muted=True, wrap=420)
        self.note.pack(anchor="w", pady=(6, 0))

        budgets = self.card("Budgets", "Alerts at 80% and 100%.", "💰")
        self.budget_box = plain(budgets.inner)
        self.budget_box.pack(fill="x")

        owe = self.card("Who owes who", "Shared costs in a group, squared with the fewest payments.", "🤝")
        self.owe_box = plain(owe.inner)
        self.owe_box.pack(fill="x")
        button(owe.inner, "Clear (all settled)", self.clear_owes, height=26).pack(anchor="w", pady=(6, 0))

        challenge = self.card("No-spend challenge", "Spending outside the allowed categories breaks a day.", "🚫")
        self.nospend_box = plain(challenge.inner)
        self.nospend_box.pack(fill="x")

        self.section("Tools")
        self.tools("budget", "importcsv", "owe", "nospend", "split", "loan")

    def on_show(self) -> None:
        self.refresh()

    def say(self, response) -> None:
        self.note.configure(text=getattr(response, "text", str(response)))

    def refresh(self) -> None:
        c = self.colors
        for box in (self.month_box, self.budget_box, self.owe_box, self.nospend_box):
            for child in box.winfo_children():
                child.destroy()
        spent = money.month_by_category()
        total = sum(spent.values())
        home = spending.default_currency()
        if not spent:
            label(self.month_box, "Nothing logged this month.", size=11, muted=True).pack(anchor="w")
        else:
            label(self.month_box, f"Total {spending.money(total, home)}", size=16, bold=True).pack(anchor="w")
            for category, amount in sorted(spent.items(), key=lambda x: -x[1]):
                row = plain(self.month_box)
                row.pack(fill="x", pady=1)
                label(row, category, size=11, width=90).pack(side="left")
                _bar(row, amount / total, c["accent"], 200).pack(side="left", padx=6)
                label(row, spending.money(amount, home), size=11).pack(side="left")
        rows = money.budget_status()
        if not rows:
            label(self.budget_box, "No budgets yet — set one with “Monthly budget by category” below.", size=11,
                  muted=True, wrap=420).pack(anchor="w")
        for r in rows:
            row = plain(self.budget_box)
            row.pack(fill="x", pady=1)
            label(row, r["category"], size=11, width=90).pack(side="left")
            colour = c["error"] if r["share"] >= 1 else "#f59e0b" if r["share"] >= 0.8 else c["ok"]
            _bar(row, r["share"], colour, 180).pack(side="left", padx=6)
            label(row, f"{spending.money(r['spent'], home)} / {spending.money(r['budget'], home)}", size=11).pack(
                side="left")
        net = money.balances()
        if not net:
            label(self.owe_box, "Everyone's square.", size=11, muted=True).pack(anchor="w")
        for payer, payee, amount in money.settle(net):
            label(self.owe_box, f"{payer} → {payee}: {spending.money(amount, home)}", size=12).pack(anchor="w")
        status = money.nospend_status()
        if status is None:
            label(self.nospend_box, "Not running.", size=11, muted=True).pack(anchor="w")
            button(self.nospend_box, "Start 7 days", lambda: self.start_nospend(7), height=26, accent=True).pack(
                anchor="w", pady=(4, 0))
        else:
            label(self.nospend_box, f"Day {status['elapsed']} of {status['days']} · {status['clean']} clean",
                  size=14, bold=True).pack(anchor="w")
            for day, things in sorted(status["slips"].items())[-3:]:
                label(self.nospend_box, f"{day}: {', '.join(things[:2])}", size=11, muted=True).pack(anchor="w")
            button(self.nospend_box, "Stop", self.stop_nospend, height=26).pack(anchor="w", pady=(4, 0))

    def clear_owes(self) -> None:
        money.OWES.save([])
        self.refresh()

    def start_nospend(self, days: int) -> None:
        money.nospend_start(days, ["bills", "groceries"])
        self.refresh()

    def stop_nospend(self) -> None:
        money.NOSPEND.save({})
        self.refresh()


# --- Türkiye -----------------------------------------------------------------------------------------

class TurkeyPage(Hub):
    key = "turkey"
    title = "Türkiye"
    icon = "🧿"
    subtitle = "İstanbul trafiği, KDV, bayramlar, e-Devlet kısayolları ve Türk mutfağı."

    def build_body(self) -> None:
        c = self.colors
        traffic = self.card("İstanbul trafiği", "İBB'nin trafik indeksi (0-100), 5 dakikada bir.", "🚦")
        self.traffic_now = label(traffic.inner, "…", size=28, bold=True, text_color=c["accent"])
        self.traffic_now.pack(anchor="w")
        self.traffic_words = label(traffic.inner, "", size=12, muted=True)
        self.traffic_words.pack(anchor="w")
        self.traffic_chart = tkinter.Canvas(traffic.inner, width=420, height=110, bg=c["bg"], highlightthickness=0)
        self.traffic_chart.pack(anchor="w", pady=(6, 0))
        button(traffic.inner, "Canlı harita", lambda: open_path("https://uym.ibb.gov.tr/"), height=26).pack(
            anchor="w", pady=(6, 0))

        holidays = self.card("Bayramlar ve tatiller", "Bir gün önce hatırlatırım.", "🎊")
        self.holiday_box = plain(holidays.inner)
        self.holiday_box.pack(fill="x")

        links = self.card("e-Devlet kısayolları", "Resmî sayfalar tarayıcıda açılır.", "🏛", span=2)
        grid = plain(links.inner)
        grid.pack(fill="x")
        for i, (name, url, icon) in enumerate(turkey.EDEVLET):
            button(grid, f"{icon}  {name}", lambda u=url: open_path(u), height=30, anchor="w").grid(
                row=i // 3, column=i % 3, padx=3, pady=3, sticky="ew")
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1, uniform="links")
        row = plain(links.inner)
        row.pack(fill="x", pady=(8, 0))
        self.search = ctk.CTkEntry(row, placeholder_text="e-Devlet'te ara: pasaport randevusu…", fg_color=c["bg"])
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<Return>", lambda e: self.search_edevlet())
        button(row, "Ara", self.search_edevlet, height=28).pack(side="left", padx=6)

        kitchen = self.card("Türk mutfağı", "Bir yemeğe tıkla; tarif sohbette gelir.", "🍲", span=2)
        for group, dishes in turkey.DISHES.items():
            label(kitchen.inner, group, size=12, bold=True).pack(anchor="w", pady=(6, 2))
            line = plain(kitchen.inner)
            line.pack(fill="x")
            for dish in dishes:
                button(line, dish, lambda d=dish: self.app.run_in_chat(f"/tarif {d}"), height=26).pack(
                    side="left", padx=(0, 4), pady=2)

        self.section("Araçlar")
        self.tools("kdv", "tarif")
        self.every("traffic", 5 * 60 * 1000, self.load_traffic)

    def on_show(self) -> None:
        self.load_traffic()
        self.load_holidays()

    def search_edevlet(self) -> None:
        words = self.search.get().strip()
        if words:
            open_path(turkey.edevlet_search(words))

    def load_traffic(self) -> None:
        def work():
            return turkey.traffic_now(), turkey.traffic_history()

        def done(result):
            if not isinstance(result, tuple):
                self.traffic_words.configure(text=str(result))
                return
            now, history = result
            self.traffic_now.configure(text=f"%{now['now']}")
            usual = f" · bu saatte genelde %{now['usual']}" if now["usual"] else ""
            words = {"light": "akıcı", "moderate": "orta", "heavy": "yoğun", "very heavy": "çok yoğun"}
            self.traffic_words.configure(text=words[turkey.traffic_words(now["now"])] + usual)
            self.draw_history(history)

        self.run(work, done, lambda exc: self.traffic_words.configure(text=f"İBB yanıt vermedi: {exc}"))

    def draw_history(self, history) -> None:
        canvas, c = self.traffic_chart, self.colors
        canvas.delete("all")
        if len(history) < 2:
            return
        w, h = 420, 110
        values = [v for _, v in history]
        top = max(60, max(values) + 5)
        points = []
        for i, value in enumerate(values):
            points += [i * (w - 10) / (len(values) - 1) + 5, h - 15 - value / top * (h - 25)]
        canvas.create_line(*points, fill=c["accent"], width=2, smooth=True)
        canvas.create_text(5, h - 2, anchor="sw", text=f"{history[0][0]:%H:%M}", fill=c["muted"],
                           font=("Segoe UI", 8))
        canvas.create_text(w - 5, h - 2, anchor="se", text=f"{history[-1][0]:%H:%M}", fill=c["muted"],
                           font=("Segoe UI", 8))

    def load_holidays(self) -> None:
        def done(items):
            for child in self.holiday_box.winfo_children():
                child.destroy()
            if not isinstance(items, list):
                label(self.holiday_box, str(items), size=11, muted=True, wrap=420).pack(anchor="w")
                return
            for item in items:
                soon = ("bugün" if item["in_days"] == 0 else "yarın" if item["in_days"] == 1 else
                        f"{item['in_days']} gün")
                length = f" · {item['days']} gün" if item["days"] > 1 else ""
                label(self.holiday_box, f"{item['first']:%d.%m}  {item['base']}{length}  ({soon})", size=12).pack(
                    anchor="w")

        self.run(turkey.upcoming, done, lambda exc: done(f"Takvime ulaşılamadı: {exc}"))
