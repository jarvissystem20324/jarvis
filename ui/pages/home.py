"""Home: the orb, the time, the weather, today's list, what JARVIS noticed,
your recent tools and every page one click away (10.0).

Each widget can be hidden from ⚙ Customize; the choice is remembered. Data
that needs the network (weather) is fetched on a worker and cached for ten
minutes, so opening Home twice does not ask Open-Meteo twice.
"""

from __future__ import annotations

import time
import tkinter
from datetime import date, datetime

import customtkinter as ctk

from jarvis import alerts, catalog
from ui import prefs
from ui.pages import PAGES
from ui.pages.base import Card, Hub, button, label

WIDGETS = {"orb": "JARVIS and quick ask", "clock": "Clock", "weather": "Weather", "today": "Today",
           "alerts": "Notifications", "tools": "Recent tools", "system": "This PC", "pages": "All pages"}


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour < 5:
        return "Working late"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def today_lines(limit: int = 8) -> list[str]:
    """Reminders, tasks and events for today, soonest first."""
    from jarvis import reminders
    from jarvis.life import CALENDAR, TODO

    start = datetime.combine(date.today(), datetime.min.time()).timestamp()
    end = start + 86400
    rows: list[tuple[float, str]] = []
    for item in reminders.board.items:
        if start <= item.due < end and item.kind not in {"briefing", "prayer", "word", "dnd", "watch"}:
            rows.append((item.due, f"⏰ {datetime.fromtimestamp(item.due):%H:%M}  {item.text}"))
    for event in CALENDAR.load():
        if start <= event.get("start", 0) < end:
            rows.append((event["start"], f"📅 {datetime.fromtimestamp(event['start']):%H:%M}  {event['title']}"))
    for task in TODO.load():
        if task.get("done"):
            continue
        due = task.get("due") or 0
        if not due or due < end:
            rows.append((due or end, ("☐ " + (f"{datetime.fromtimestamp(due):%H:%M}  " if due else "") + task["text"])))
    rows.sort(key=lambda r: r[0])
    return [text for _, text in rows[:limit]]


class HomePage(Hub):
    key = "home"
    title = "Home"
    icon = "🏠"
    columns = 3

    def build_body(self) -> None:
        c = self.colors
        button(self.header, "⚙ Customize", self.customize, height=26).place(relx=1.0, rely=0.0, anchor="ne")
        shown = set(prefs.get("home_widgets", list(WIDGETS)))
        self.widgets = {}
        if "orb" in shown:
            self._orb_card()
        if "clock" in shown:
            card = self.card("Clock", icon="🕒")
            self.clock = label(card.inner, "", size=40, bold=True, text_color=c["accent"])
            self.clock.pack(anchor="w")
            self.clock_date = label(card.inner, "", size=13, muted=True)
            self.clock_date.pack(anchor="w")
            self.every("clock", 1000, self._tick_clock)
            self._tick_clock()
        if "weather" in shown:
            card = self.card("Weather", icon="⛅")
            self.weather = label(card.inner, "Loading…", size=12, wrap=300)
            self.weather.pack(anchor="w")
            button(card.inner, "↻", self._load_weather, height=22, width=30).pack(anchor="e")
            self._load_weather()
        if "today" in shown:
            card = self.card("Today", icon="✅")
            self.today = ctk.CTkFrame(card.inner, fg_color="transparent")
            self.today.pack(fill="x")
            row = ctk.CTkFrame(card.inner, fg_color="transparent")
            row.pack(fill="x", pady=(6, 0))
            button(row, "Open Today", lambda: self.app._show_tab("today"), height=24).pack(side="left")
            self._fill_today()
        if "alerts" in shown:
            card = self.card("Notifications", icon="🔔")
            self.alert_box = ctk.CTkFrame(card.inner, fg_color="transparent")
            self.alert_box.pack(fill="x")
            self.refresh_alerts()
        if "system" in shown:
            card = self.card("This PC", icon="🖥")
            self.bars = {}
            for key in ("CPU", "RAM", "Disk", "Battery"):
                row = ctk.CTkFrame(card.inner, fg_color="transparent")
                row.pack(fill="x", pady=2)
                label(row, key, size=11, muted=True, width=60).pack(side="left")
                bar = ctk.CTkProgressBar(row, height=10, progress_color=c["accent"])
                bar.set(0)
                bar.pack(side="left", fill="x", expand=True, padx=6)
                value = label(row, "", size=11, width=48)
                value.pack(side="left")
                self.bars[key] = (bar, value)
            self.every("system", 3000, self._tick_system)
            self._tick_system()
        if "tools" in shown:
            card = self.card("Recent tools", icon="🧰", span=2)
            self.recent_box = ctk.CTkFrame(card.inner, fg_color="transparent")
            self.recent_box.pack(fill="x")
            self._fill_recent()
        if "pages" in shown:
            self.section("Pages")
            card = Card(self.body)
            self.place(card, span=self.columns)
            grid = card.inner
            for i, page in enumerate(p for p in PAGES if p.key != "home"):
                ctk.CTkButton(grid, text=f"{page.icon}  {page.label}", height=36, width=150, anchor="w",
                              fg_color=c["bg"], hover_color=c["accent_dim"], text_color=c["text"],
                              command=lambda k=page.key: self.app._show_tab(k)).grid(row=i // 5, column=i % 5,
                                                                                      padx=4, pady=4, sticky="w")

    def _orb_card(self) -> None:
        from ui.orb import Orb

        c = self.colors
        card = self.card("", span=self.columns)
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        orb = Orb(row, 150, c["accent"], c["panel"], state=self.app._avatar_state, label="J.A.R.V.I.S.")
        orb.pack(side="left", padx=(0, 18))
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self.hello = label(right, "", size=22, bold=True)
        self.hello.pack(anchor="w", pady=(10, 0))
        label(right, "Ask anything, or type / for a command. Ctrl+K finds any page or tool.", size=12,
              muted=True).pack(anchor="w")
        line = ctk.CTkFrame(right, fg_color="transparent")
        line.pack(fill="x", pady=10)
        self.ask = ctk.CTkEntry(line, height=40, placeholder_text="Ask JARVIS…", fg_color=c["bg"],
                                font=ctk.CTkFont(size=14))
        self.ask.pack(side="left", fill="x", expand=True)
        self.ask.bind("<Return>", lambda e: self._ask())
        button(line, "Ask", self._ask, accent=True, height=40, width=70).pack(side="left", padx=(8, 0))
        button(line, "🎤", self.app._listen, height=40, width=44).pack(side="left", padx=(6, 0))
        button(line, "◉ Orb", self.app.toggle_orb, height=40, width=70).pack(side="left", padx=(6, 0))

    def on_show(self) -> None:
        name = self.app._user_name()
        if hasattr(self, "hello"):
            self.hello.configure(text=f"{greeting()}{'' if name == 'You' else ', ' + name}.")
        if hasattr(self, "today"):
            self._fill_today()
        if hasattr(self, "recent_box"):
            self._fill_recent()
        if hasattr(self, "alert_box"):
            self.refresh_alerts()

    # --- widgets ---------------------------------------------------------------
    def _ask(self) -> None:
        text = self.ask.get().strip()
        if not text:
            return
        self.ask.delete(0, "end")
        self.app.run_in_chat(text)

    def _tick_clock(self) -> None:
        now = datetime.now()
        self.clock.configure(text=now.strftime("%H:%M:%S"))
        self.clock_date.configure(text=now.strftime("%A, %d %B %Y"))

    def _load_weather(self) -> None:
        cache = getattr(HomePage, "_weather_cache", None)
        if cache and time.time() - cache[0] < 600:
            self.weather.configure(text=cache[1])
            return
        from jarvis import weather

        def work():
            if not weather.home_city():
                return "Set your city in Settings → Home city, or say “weather in Istanbul”."
            text = weather.report("")
            return "\n".join(line for line in text.splitlines() if not line.startswith("(Open"))

        def done(text):
            HomePage._weather_cache = (time.time(), str(text))
            try:
                self.weather.configure(text=str(text))
            except tkinter.TclError:
                pass

        self.run(work, done, lambda e: done(f"Weather unavailable: {e}"))

    def _fill_today(self) -> None:
        for child in self.today.winfo_children():
            child.destroy()
        try:
            lines = today_lines()
        except Exception:
            lines = []
        if not lines:
            label(self.today, "Nothing due today. 🎉", size=12, muted=True).pack(anchor="w")
        for line in lines:
            label(self.today, line, size=12, wrap=320).pack(anchor="w", pady=1)

    def refresh_alerts(self) -> None:
        for child in self.alert_box.winfo_children():
            child.destroy()
        items = alerts.recent(6)
        if not items:
            label(self.alert_box, "Nothing yet — battery, weather, scans and automations report here.",
                  size=11, muted=True, wrap=300).pack(anchor="w")
        for alert in items:
            text = f"{time.strftime('%H:%M', time.localtime(alert.at))}  {alert.title}"
            b = ctk.CTkButton(self.alert_box, text=text, anchor="w", height=24, fg_color="transparent",
                              hover_color=self.colors["accent_dim"], text_color=self.colors["text"],
                              command=lambda a=alert: a.page and self.app._show_tab(a.page))
            b.pack(fill="x")

    def _fill_recent(self) -> None:
        for child in self.recent_box.winfo_children():
            child.destroy()
        tools = catalog.recent(10) or [self.app.tool(n) for n in ("weather", "remind", "slides", "qr", "calc")]
        for i, tool in enumerate(t for t in tools if t is not None):
            button(self.recent_box, f"{tool.icon} {tool.label()}", lambda t=tool: self.app.open_tool(t.name),
                   height=30).grid(row=i // 5, column=i % 5, padx=3, pady=3, sticky="w")
        button(self.recent_box, "🧰 All tools", lambda: self.app._show_tab("tools"), height=30, accent=True).grid(
            row=99, column=0, padx=3, pady=(6, 0), sticky="w")

    def _tick_system(self) -> None:
        import psutil

        values = {"CPU": psutil.cpu_percent(None), "RAM": psutil.virtual_memory().percent}
        try:
            import os

            values["Disk"] = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent
        except Exception:
            values["Disk"] = None
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        values["Battery"] = battery.percent if battery else None
        for key, (bar, value) in self.bars.items():
            v = values.get(key)
            if v is None:
                bar.set(0)
                value.configure(text="—")
            else:
                bar.set(max(0.0, min(1.0, v / 100)))
                value.configure(text=f"{v:.0f}%")

    # --- customise ---------------------------------------------------------------
    def customize(self) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        shown = set(prefs.get("home_widgets", list(WIDGETS)))
        for key, name in WIDGETS.items():
            menu.add_checkbutton(label=name, onvalue=True, offvalue=False,
                                 variable=tkinter.BooleanVar(value=key in shown),
                                 command=lambda k=key: self._toggle(k))
        menu.add_separator()
        menu.add_command(label="Start JARVIS on Home", command=self._start_here)
        x, y = self.winfo_pointerx(), self.winfo_pointery()
        menu.tk_popup(x, y)

    def _toggle(self, key: str) -> None:
        shown = list(prefs.get("home_widgets", list(WIDGETS)))
        if key in shown:
            shown.remove(key)
        else:
            shown.append(key)
        prefs.set("home_widgets", [k for k in WIDGETS if k in shown])
        self.rebuild()

    def rebuild(self) -> None:
        self.close()
        for child in self.winfo_children():
            child.destroy()
        self._built = False
        self.show()

    def _start_here(self) -> None:
        from ui.settings import write_env
        import os

        try:
            write_env({"JARVIS_START_PAGE": "home"})
            os.environ["JARVIS_START_PAGE"] = "home"
        except OSError:
            pass
