"""PC (10.0): live CPU, RAM and GPU graphs, temperatures, battery and disk
health, network, a screen colour picker, winget, keep-awake, and the PC tools."""

from __future__ import annotations

import time
import tkinter
from collections import deque

import customtkinter as ctk
import psutil

from jarvis import kit
from jarvis.ten import system
from ui.pages.base import Card, Hub, ResultView, button, label


class Graph(tkinter.Canvas):
    """A rolling line graph of the last 60 readings, 0-100."""

    def __init__(self, parent, colour: str, colors: dict, height: int = 90):
        super().__init__(parent, height=height, bg=colors["bg"], highlightthickness=0)
        self.colour = colour
        self.colors = colors
        self.values: deque = deque([0.0] * 60, maxlen=60)

    def push(self, value: float | None) -> None:
        self.values.append(0.0 if value is None else float(value))
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        w = max(10, self.winfo_width())
        h = max(10, self.winfo_height())
        for y in (0.25, 0.5, 0.75):
            self.create_line(0, h * y, w, h * y, fill=self.colors["panel"])
        step = w / (len(self.values) - 1)
        points = []
        for i, v in enumerate(self.values):
            points += [i * step, h - (min(100.0, v) / 100) * (h - 4) - 2]
        fill = points + [w, h, 0, h]
        from ui.orb import _mix

        self.create_polygon(fill, fill=_mix(self.colors["bg"], self.colour, 0.25), outline="")
        self.create_line(points, fill=self.colour, width=2, smooth=True)


class PCPage(Hub):
    key = "pc"
    title = "PC"
    icon = "🖥"
    subtitle = "How your PC is doing right now, and tools to keep it healthy."

    def build_body(self) -> None:
        c = self.colors
        live = self.card("Live", "Updated every 2 seconds while this page is open.", "📈", span=2)
        grid = ctk.CTkFrame(live.inner, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="g")
        self.graphs = {}
        self.values = {}
        for col, (key, name, colour) in enumerate((("cpu", "CPU", c["accent"]), ("ram", "Memory", c["ok"]),
                                                    ("gpu", "GPU", c["num"]))):
            box = ctk.CTkFrame(grid, fg_color="transparent")
            box.grid(row=0, column=col, sticky="nsew", padx=6)
            head = ctk.CTkFrame(box, fg_color="transparent")
            head.pack(fill="x")
            label(head, name, size=13, bold=True).pack(side="left")
            self.values[key] = label(head, "—", size=13, bold=True, text_color=colour)
            self.values[key].pack(side="right")
            graph = Graph(box, colour, c)
            graph.pack(fill="x", pady=4)
            self.graphs[key] = graph
        self.cores = tkinter.Canvas(live.inner, height=36, bg=c["panel"], highlightthickness=0)
        self.cores.pack(fill="x", pady=(6, 0))
        self.temps = label(live.inner, "Temperatures: reading…", size=12, muted=True)
        self.temps.pack(anchor="w", pady=(6, 0))
        self._gpu = None
        self._temp_job_running = False
        self.every("live", 2000, self.tick)
        self.every("slow", 6000, self.slow_tick)
        # info cards
        self.specs = self._result_card("This PC", "Hardware and Windows.", "💻", "/specs")
        self.battery = self._result_card("Battery", "Health: how much of its original capacity is left.", "🔋",
                                         "/battery")
        self.disks = self._result_card("Disks", "Health, temperature and wear, from Windows.", "💽", "/diskhealth")
        self.network = self._result_card("Network", "Your IPs, router, DNS and public IP.", "🌐", "/ipinfo")
        self.netapps = self._result_card("Apps on the network", "Who has open internet connections right now.",
                                         "📶", "/netapps")
        self._awake_card()
        self._picker_card()
        self._winget_card()
        self.section("Tools")
        self.tools("autosort", "zip", "unzip", "bsod", "cleanup", "startup", "dupes", "speedtest", "pc", "wifi",
                   "screentime", "power")

    def _result_card(self, title: str, subtitle: str, icon: str, command: str) -> ResultView:
        card = self.card(title, subtitle, icon)
        view = ResultView(card.inner, self.app, max_lines=9)
        view.pack(fill="x")
        button(card.inner, "↻ Refresh", lambda: self.app.run_tool(command, view.show, name=command[1:]),
               height=24).pack(anchor="e", pady=(4, 0))
        view._command = command
        return view

    def on_show(self) -> None:
        for view in (self.specs, self.disks, self.network):
            if not view.winfo_children():
                self.app.run_tool(view._command, view.show, name=view._command[1:])

    # --- live ----------------------------------------------------------------------------
    def tick(self) -> None:
        snap = system.snapshot()
        self.graphs["cpu"].push(snap["cpu"])
        self.values["cpu"].configure(text=f"{snap['cpu']:.0f}%")
        self.graphs["ram"].push(snap["ram"])
        self.values["ram"].configure(text=f"{snap['ram']:.0f}%  ({kit.size(snap['ram_used'])})")
        self.graphs["gpu"].push(self._gpu)
        self.values["gpu"].configure(text="—" if self._gpu is None else f"{self._gpu:.0f}%")
        c = self.colors
        self.cores.delete("all")
        cores = snap["cores"]
        w = max(10, self.cores.winfo_width())
        each = w / max(1, len(cores))
        for i, v in enumerate(cores):
            x = i * each
            h = 34 * min(100.0, v) / 100
            self.cores.create_rectangle(x + 1, 36 - h, x + each - 1, 36, fill=c["accent"], outline="")

    def slow_tick(self) -> None:
        if self._temp_job_running:
            return
        self._temp_job_running = True

        def work():
            gpus = system.nvidia()
            load = gpus[0]["load"] if gpus else system.gpu_load_counters()
            return load, gpus, system.cpu_temperature()

        def done(result):
            self._temp_job_running = False
            if isinstance(result, str):
                return
            load, gpus, cpu = result
            self._gpu = load
            parts = [f"CPU {cpu:.0f} °C" if cpu is not None else "CPU temperature not shared by Windows here"]
            parts += [f"{g['name']} {g['temp']:.0f} °C" for g in gpus if g.get("temp") is not None]
            self.temps.configure(text="🌡 " + "  ·  ".join(parts))

        self.run(work, done)

    # --- keep awake ---------------------------------------------------------------------------
    def _awake_card(self) -> None:
        card = self.card("Keep awake", "Stop the PC and screen from sleeping — for a download, a talk, a render.", "☕")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        self.awake_var = tkinter.BooleanVar(value=system.awake.on)
        ctk.CTkSwitch(row, text="Keep awake", variable=self.awake_var, command=self._toggle_awake).pack(side="left")
        self.awake_for = ctk.CTkOptionMenu(row, values=["until I turn it off", "30 min", "1 hour", "2 hours", "4 hours"],
                                           width=160, fg_color=self.colors["bg"],
                                           button_color=self.colors["accent_dim"])
        self.awake_for.pack(side="left", padx=8)
        self.awake_note = label(card.inner, "", size=11, muted=True)
        self.awake_note.pack(anchor="w", pady=4)

    def _toggle_awake(self) -> None:
        if self.awake_var.get():
            seconds = {"30 min": 1800, "1 hour": 3600, "2 hours": 7200, "4 hours": 14400}.get(self.awake_for.get(), 0)
            system.awake.start(seconds)
            self.awake_note.configure(text="☕ Awake" + (f" for {self.awake_for.get()}." if seconds else "."))
        else:
            system.awake.stop()
            self.awake_note.configure(text="Normal sleep settings again.")

    # --- colour picker ---------------------------------------------------------------------------
    def _picker_card(self) -> None:
        card = self.card("Colour picker", "Pick any colour on your screen; the code is copied.", "🎨")
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        button(row, "🎯 Pick from screen", self.pick_colour, accent=True).pack(side="left")
        self.swatch = tkinter.Frame(row, width=40, height=28, bg=self.colors["bg"])
        self.swatch.pack(side="left", padx=10)
        self.colour_text = label(row, "", size=13, bold=True)
        self.colour_text.pack(side="left")

    def pick_colour(self) -> None:
        from PIL import ImageGrab, ImageTk

        top = self.winfo_toplevel()
        top.withdraw()
        self.after(250, lambda: self._picker(ImageGrab, ImageTk, top))

    def _picker(self, ImageGrab, ImageTk, top) -> None:
        shot = ImageGrab.grab()
        overlay = tkinter.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.geometry(f"{shot.width}x{shot.height}+0+0")
        overlay.attributes("-topmost", True)
        photo = ImageTk.PhotoImage(shot)
        canvas = tkinter.Canvas(overlay, width=shot.width, height=shot.height, highlightthickness=0, cursor="tcross")
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        lens = canvas.create_rectangle(0, 0, 0, 0, outline="white", width=2)
        tag = canvas.create_text(0, 0, text="", fill="white", font=("Consolas", 12, "bold"), anchor="nw")
        pixels = shot.convert("RGB").load()

        def colour_at(x, y):
            x = max(0, min(shot.width - 1, x))
            y = max(0, min(shot.height - 1, y))
            return pixels[x, y]

        def move(e):
            r, g, b = colour_at(e.x, e.y)
            hexcode = f"#{r:02X}{g:02X}{b:02X}"
            canvas.coords(lens, e.x + 16, e.y + 16, e.x + 56, e.y + 56)
            canvas.itemconfigure(lens, fill=hexcode)
            canvas.coords(tag, e.x + 62, e.y + 24)
            canvas.itemconfigure(tag, text=f"{hexcode}  rgb({r}, {g}, {b})")

        def done(e=None):
            if e is not None:
                r, g, b = colour_at(e.x, e.y)
                hexcode = f"#{r:02X}{g:02X}{b:02X}"
                self.swatch.configure(bg=hexcode)
                self.colour_text.configure(text=f"{hexcode}   rgb({r}, {g}, {b})")
                self.clipboard_clear()
                self.clipboard_append(hexcode)
            overlay.destroy()
            top.deiconify()

        canvas.bind("<Motion>", move)
        canvas.bind("<Button-1>", done)
        overlay.bind("<Escape>", lambda e: done())
        overlay.focus_force()

    # --- winget ------------------------------------------------------------------------------------
    def _winget_card(self) -> None:
        card = self.card("Install apps", "Search Windows' package manager (winget) and install with one click.", "📥",
                         span=2)
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        self.winget_query = ctk.CTkEntry(row, placeholder_text="App name — vlc, 7zip, discord, python…",
                                         fg_color=self.colors["bg"])
        self.winget_query.pack(side="left", fill="x", expand=True)
        self.winget_query.bind("<Return>", lambda e: self.winget_search())
        button(row, "Search", self.winget_search, accent=True).pack(side="left", padx=6)
        button(row, "Updates available", self.winget_updates).pack(side="left")
        self.winget_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.winget_box.pack(fill="x", pady=6)
        self.winget_note = label(card.inner, "", size=11, muted=True)
        self.winget_note.pack(anchor="w")

    def winget_search(self) -> None:
        query = self.winget_query.get().strip()
        if not query:
            return
        self.winget_note.configure(text="Searching…")

        def work():
            code, out = system.winget("search", query, "--count", "12")
            return system.parse_winget_table(out)

        self.run(work, self._fill_winget, lambda e: self.winget_note.configure(text=str(e)))

    def winget_updates(self) -> None:
        self.winget_note.configure(text="Checking for updates…")

        def work():
            code, out = system.winget("upgrade", timeout=180)
            return system.parse_winget_table(out)

        self.run(work, lambda rows: self._fill_winget(rows, updates=True),
                 lambda e: self.winget_note.configure(text=str(e)))

    def _fill_winget(self, rows, updates: bool = False) -> None:
        for child in self.winget_box.winfo_children():
            child.destroy()
        if isinstance(rows, str):
            self.winget_note.configure(text=rows)
            return
        self.winget_note.configure(text=f"{len(rows)} result(s)." if rows else "Nothing found.")
        for r in rows:
            line = ctk.CTkFrame(self.winget_box, fg_color="transparent")
            line.pack(fill="x", pady=1)
            text = f"{r.get('Name', '')[:40]}   {r.get('Id', '')}   {r.get('Version', '')}" + (
                f" → {r.get('Available', '')}" if updates else "")
            label(line, text, size=12).pack(side="left")
            button(line, "Update" if updates else "Install",
                   lambda i=r.get("Id"): self.app.run_tool(f"/winget install {i}", lambda resp: self.winget_note.configure(
                       text=str(getattr(resp, "text", resp))[:150]), name="winget"), height=24).pack(side="right")
