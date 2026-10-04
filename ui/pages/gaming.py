"""Gaming (10.0): your games in one place, a performance overlay, an aim
trainer, a keyboard and mouse tester, and JARVIS for guides and settings.

The overlay is a small always-on-top window that clicks pass straight
through, so it never steals a click from the game. It can't show a game's
FPS (that needs hooking into the game itself, which anti-cheat rightly
blocks); it shows what JARVIS can measure honestly — CPU, GPU, memory, ping.
"""

from __future__ import annotations

import random
import threading
import time
import tkinter
from pathlib import Path

import customtkinter as ctk

from jarvis import gaming, prefs
from ui.pages.base import Hub, button, label, open_path, plain, safe_after, text_font

TILE_W, TILE_H = 230, 107       # Steam's header art is 460×215


class GamingPage(Hub):
    key = "gaming"
    title = "Gaming"
    icon = "🎮"
    subtitle = "Your games, a performance overlay, an aim trainer, a key and mouse tester — and guides and settings."

    def build_body(self) -> None:
        c = self.colors
        self.overlay: Overlay | None = None
        self._art: list = []
        library = self.card("Your games", "Steam, Epic and GOG. Click to play; right-click for the folder.", "🎮",
                            span=2)
        top = plain(library.inner)
        top.pack(fill="x")
        self.count = label(top, "", size=11, muted=True)
        self.count.pack(side="left")
        button(top, "↻ Refresh", self.load_games, height=26).pack(side="right")
        self.shelf = plain(library.inner)
        self.shelf.pack(fill="x", pady=(8, 0))

        over = self.card("Performance overlay", "On top of your game: CPU, GPU, memory and ping. Works in windowed "
                                                "and borderless games; clicks go through it.", "📊")
        self.overlay_var = tkinter.BooleanVar(value=False)
        ctk.CTkSwitch(over.inner, text="Show the overlay", variable=self.overlay_var,
                      command=self.toggle_overlay).pack(anchor="w")
        row = plain(over.inner)
        row.pack(fill="x", pady=(8, 0))
        label(row, "Corner", size=11, muted=True).pack(side="left")
        self.corner = ctk.CTkOptionMenu(row, values=["top-left", "top-right", "bottom-left", "bottom-right"],
                                        width=130, fg_color=c["bg"], button_color=c["accent_dim"],
                                        command=self.move_overlay)
        self.corner.set(prefs.get("overlay_corner", "top-left"))
        self.corner.pack(side="left", padx=8)

        keys = self.card("Keyboard and mouse", "Click the box, then press keys and buttons. The click test counts "
                                               "clicks per second.", "⌨")
        self.key_test = KeyTester(keys.inner, self)
        self.key_test.pack(fill="x")

        aim = self.card("Aim trainer", "30 seconds: click each target as fast as you can.", "🎯", span=2)
        self.aim = AimTrainer(aim.inner, self)
        self.aim.pack(fill="x")

        self.section("Ask JARVIS")
        self.tools("guide", "gamesettings", "gpudriver", "teams")

    def on_show(self) -> None:
        if not self.shelf.winfo_children():
            self.load_games()

    def on_hide(self) -> None:
        self.aim.stop()

    def open_target(self, part: str) -> None:
        if part in {"overlay", "overlay-on"}:
            self.overlay_var.set(True)
            self.toggle_overlay()
        elif part == "overlay-off":
            self.overlay_var.set(False)
            self.toggle_overlay()
        elif part == "aim":
            self.after(100, lambda: self.body._parent_canvas.yview_moveto(0.45))
        elif part == "keys":
            self.after(100, self.key_test.canvas.focus_set)

    # --- the library -----------------------------------------------------------------------------
    def load_games(self) -> None:
        self.count.configure(text="Looking for games…")
        self.run(gaming.library, self.show_games, lambda exc: self.count.configure(text=str(exc)))

    def show_games(self, games) -> None:
        for child in self.shelf.winfo_children():
            child.destroy()
        self._art = []
        games = games if isinstance(games, list) else []
        sources = sorted({g.source for g in games})
        self.count.configure(text=f"{len(games)} game(s) from {', '.join(sources)}" if games else
                             "No games found. Steam, Epic and GOG games appear here once installed.")
        per_row = max(2, (self.shelf.winfo_width() or 1000) // (TILE_W + 12))
        tiles = []
        for i, game in enumerate(games):
            tile = self._tile(game)
            tile.grid(row=i // per_row, column=i % per_row, padx=6, pady=6, sticky="n")
            tiles.append((game, tile))
        steam = [(g, t) for g, t in tiles if g.image_url]
        if steam:
            self.run(lambda: {g.app_id: _header(g) for g, _ in steam}, lambda art: self._set_art(art, steam))

    def _tile(self, game: gaming.Game) -> tkinter.Frame:
        c = self.colors
        frame = tkinter.Frame(self.shelf, bg=c["bg"], cursor="hand2")
        # Sized in characters until the art arrives, then in pixels (TILE_W×TILE_H).
        picture = tkinter.Label(frame, text="🎮", font=("Segoe UI Emoji", 30), bg=c["bg"], fg=c["muted"],
                                width=7, height=1, bd=0, pady=18)
        picture.pack(fill="x")
        font = text_font(self, 11, bold=True)[0]
        tkinter.Label(frame, text=game.name[:30], font=font, bg=c["bg"], fg=c["text"], anchor="w").pack(fill="x",
                                                                                                       padx=6)
        small = text_font(self, 10)[0]
        size = f" · {game.size / 1e9:.1f} GB" if game.size else ""
        tkinter.Label(frame, text=f"{game.source}{size}", font=small, bg=c["bg"], fg=c["muted"], anchor="w").pack(
            fill="x", padx=6, pady=(0, 6))
        for widget in (frame, *frame.winfo_children()):
            widget.bind("<Button-1>", lambda e, g=game: self.play(g))
            widget.bind("<Button-3>", lambda e, g=game: self._menu(e, g))
        frame.picture = picture
        return frame

    def _set_art(self, art, steam) -> None:
        if not isinstance(art, dict):
            return
        from PIL import Image, ImageTk

        for game, tile in steam:
            path = art.get(game.app_id)
            if not path:
                continue
            try:
                with Image.open(path) as image:
                    image = image.convert("RGB").resize((TILE_W, TILE_H))
                picture = ImageTk.PhotoImage(image, master=self)
                tile.picture.configure(image=picture, text="", width=TILE_W, height=TILE_H, pady=0)
                self._art.append(picture)
            except (OSError, tkinter.TclError):
                continue

    def play(self, game: gaming.Game) -> None:
        try:
            gaming.launch(game)
            self.count.configure(text=f"Starting {game.name}…")
        except OSError as exc:
            self.count.configure(text=f"Couldn't start {game.name}: {exc}")

    def _menu(self, event, game: gaming.Game) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Play", command=lambda: self.play(game))
        if game.folder and Path(game.folder).exists():
            menu.add_command(label="Open the game's folder", command=lambda: open_path(game.folder))
        menu.add_command(label="Best settings for this PC…",
                         command=lambda: self.app.run_in_chat(f"/gamesettings {game.name}"))
        menu.tk_popup(event.x_root, event.y_root)

    # --- the overlay -----------------------------------------------------------------------------
    def toggle_overlay(self) -> None:
        if self.overlay_var.get():
            if self.overlay is None:
                self.overlay = Overlay(self.app, self.corner.get())
        elif self.overlay is not None:
            self.overlay.close()
            self.overlay = None

    def move_overlay(self, corner: str) -> None:
        prefs.set("overlay_corner", corner)
        if self.overlay is not None:
            self.overlay.place_at(corner)

    def close(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        super().close()


def _header(game: gaming.Game) -> str | None:
    """Steam's header art for a game, fetched once and kept in the data folder."""
    from jarvis.config import get_data_dir

    folder = get_data_dir() / "cache" / "steam"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{game.app_id}.jpg"
    if path.exists() and path.stat().st_size > 1000:
        return str(path)
    try:
        from jarvis import net

        with net.urlopen(net.request(game.image_url), timeout=10) as response:
            data = response.read(3_000_000)
        if len(data) > 1000:
            path.write_bytes(data)
            return str(path)
    except Exception:
        pass
    return None


class Overlay(tkinter.Toplevel):
    """A click-through, always-on-top strip of numbers."""

    def __init__(self, app, corner: str) -> None:
        super().__init__(app)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.82)
        except tkinter.TclError:
            pass
        self.configure(bg="#05070c")
        self.text = tkinter.Label(self, text="…", font=("Consolas", 11, "bold"), fg="#7dd3fc", bg="#05070c",
                                  justify="left", padx=10, pady=6)
        self.text.pack()
        self.update_idletasks()
        self.place_at(corner)
        self.after(50, self._click_through)
        self._stop = threading.Event()
        self._gpu_counter = None
        threading.Thread(target=self._sampler, daemon=True, name="jarvis-overlay").start()

    def _click_through(self) -> None:
        """Clicks pass through to the game, and it stays out of Alt+Tab."""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass

    def place_at(self, corner: str) -> None:
        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = 12 if "left" in corner else screen_w - width - 12
        y = 12 if "top" in corner else screen_h - height - 60
        self.geometry(f"+{x}+{y}")

    def _sampler(self) -> None:
        from jarvis.ten import system

        import psutil

        psutil.cpu_percent(interval=0.3)       # CPU use is measured between two calls; this is the first
        last_counter = 0.0
        first = True
        while first or not self._stop.wait(1.5):        # the first reading straight away
            first = False
            try:
                data = gaming.sample()
                if data["gpu"] is None and time.time() - last_counter > 4:
                    self._gpu_counter = system.gpu_load_counters()     # any GPU maker, every few seconds
                    last_counter = time.time()
                if data["gpu"] is None:
                    data["gpu"] = self._gpu_counter
            except Exception:
                continue
            safe_after(self, lambda d=data: self.show(d))

    def show(self, d: dict) -> None:
        def pct(value):
            return f"{value:3.0f}%" if value is not None else "  —"

        lines = [f"CPU {pct(d['cpu'])}   RAM {pct(d['ram'])}",
                 f"GPU {pct(d['gpu'])}" + (f"   {d['gpu_temp']:.0f}°C" if d.get("gpu_temp") else "") +
                 (f"   VRAM {pct(d['vram'])}" if d.get("vram") is not None else ""),
                 f"Ping {d['ping']:.0f} ms" if d.get("ping") else "Ping  —",
                 time.strftime("%H:%M")]
        try:
            self.text.configure(text="\n".join(lines))
        except tkinter.TclError:
            pass

    def close(self) -> None:
        self._stop.set()
        try:
            self.destroy()
        except tkinter.TclError:
            pass


class AimTrainer(tkinter.Frame):
    W, H, SECONDS = 760, 300, 30

    def __init__(self, parent, page: GamingPage) -> None:
        super().__init__(parent, bg=page.colors["panel"])
        self.page = page
        c = page.colors
        top = plain(self)
        top.pack(fill="x")
        self.stats = label(top, "", size=13, bold=True)
        self.stats.pack(side="left")
        button(top, "▶ Start", self.start, accent=True, height=28).pack(side="right")
        self.canvas = tkinter.Canvas(self, width=self.W, height=self.H, bg=c["bg"], highlightthickness=0,
                                     cursor="crosshair")
        self.canvas.pack(anchor="w", pady=8)
        self.canvas.bind("<Button-1>", self.click)
        self.running = False
        self._job = None
        self.reset()
        self.draw_idle()

    def reset(self) -> None:
        self.hits = self.misses = 0
        self.times: list[float] = []
        self.target = None
        self.shown_at = 0.0
        self.ends = 0.0

    def start(self) -> None:
        self.stop()
        self.reset()
        self.running = True
        self.ends = time.time() + self.SECONDS
        self.new_target()
        self.tick()

    def stop(self) -> None:
        self.running = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tkinter.TclError:
                pass
            self._job = None

    def new_target(self) -> None:
        r = random.randint(14, 26)
        self.target = (random.randint(r + 4, self.W - r - 4), random.randint(r + 4, self.H - r - 4), r)
        self.shown_at = time.perf_counter()
        self.draw()

    def click(self, event) -> None:
        if not self.running or self.target is None:
            return
        x, y, r = self.target
        if (event.x - x) ** 2 + (event.y - y) ** 2 <= r * r:
            self.hits += 1
            self.times.append((time.perf_counter() - self.shown_at) * 1000)
            self.new_target()
        else:
            self.misses += 1
        self.show_stats()

    def tick(self) -> None:
        self._job = None
        if not self.running:
            return
        if time.time() >= self.ends:
            self.finish()
            return
        self.show_stats()
        self._job = self.after(200, self.tick)

    def finish(self) -> None:
        self.running = False
        best = prefs.get("best_aim", 0)
        if self.hits > best:
            prefs.set("best_aim", self.hits)
        self.target = None
        self.draw_idle(done=True)
        self.show_stats()

    def show_stats(self) -> None:
        shots = self.hits + self.misses
        accuracy = f"{self.hits / shots * 100:.0f}%" if shots else "—"
        reaction = f"{sum(self.times) / len(self.times):.0f} ms" if self.times else "—"
        left = max(0, int(self.ends - time.time())) if self.running else 0
        best = max(prefs.get("best_aim", 0), self.hits)
        self.stats.configure(text=f"Hits {self.hits}   ·   Accuracy {accuracy}   ·   Reaction {reaction}   ·   "
                                  f"Best {best}" + (f"   ·   {left}s" if self.running else ""))

    def draw(self) -> None:
        c = self.page.colors
        self.canvas.delete("all")
        if self.target is not None:
            x, y, r = self.target
            for ring, colour in ((r, "#ef4444"), (r * 0.66, "#ffffff"), (r * 0.33, "#ef4444")):
                self.canvas.create_oval(x - ring, y - ring, x + ring, y + ring, fill=colour, width=0)
        self.canvas.create_text(self.W - 8, 10, anchor="ne", fill=c["muted"], font=("Segoe UI", 10),
                                text="click the targets")

    def draw_idle(self, done: bool = False) -> None:
        c = self.page.colors
        self.canvas.delete("all")
        text = "Time! Press Start to go again." if done else "Press Start — targets appear one after another."
        self.canvas.create_text(self.W / 2, self.H / 2, text=text, fill=c["muted"], font=("Segoe UI", 14))


KEY_ROWS = (("Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"),
            ("`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "BackSpace"),
            ("Tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]", "\\"),
            ("Caps_Lock", "a", "s", "d", "f", "g", "h", "j", "k", "l", ";", "'", "Return"),
            ("Shift_L", "z", "x", "c", "v", "b", "n", "m", ",", ".", "/", "Shift_R"),
            ("Control_L", "Win_L", "Alt_L", "space", "Alt_R", "Control_R", "Left", "Up", "Down", "Right"))
WIDE = {"BackSpace": 2, "Tab": 1.5, "\\": 1.5, "Caps_Lock": 1.75, "Return": 2.25, "Shift_L": 2.25, "Shift_R": 2.75,
        "space": 5.5, "Control_L": 1.5, "Control_R": 1.5}
SHOWN = {"BackSpace": "⌫", "Return": "Enter", "Caps_Lock": "Caps", "Shift_L": "Shift", "Shift_R": "Shift",
         "Control_L": "Ctrl", "Control_R": "Ctrl", "Alt_L": "Alt", "Alt_R": "AltGr", "Win_L": "Win", "space": "",
         "Left": "←", "Up": "↑", "Down": "↓", "Right": "→"}
SYMBOLS = {"grave": "`", "minus": "-", "equal": "=", "bracketleft": "[", "bracketright": "]", "backslash": "\\",
           "semicolon": ";", "apostrophe": "'", "comma": ",", "period": ".", "slash": "/", "Escape": "Esc",
           "Super_L": "Win_L", "ISO_Level3_Shift": "Alt_R"}


class KeyTester(tkinter.Frame):
    UNIT = 26

    def __init__(self, parent, page: GamingPage) -> None:
        super().__init__(parent, bg=page.colors["panel"])
        self.page = page
        c = page.colors
        self.canvas = tkinter.Canvas(self, width=self.UNIT * 15.5, height=self.UNIT * 6 + 12, bg=c["bg"],
                                     highlightthickness=1, highlightbackground=c["accent_dim"], takefocus=1)
        self.canvas.pack(anchor="w")
        self.canvas.bind("<Button-1>", lambda e: (self.canvas.focus_set(), self.mouse("Left")))
        self.canvas.bind("<Button-2>", lambda e: self.mouse("Middle"))
        self.canvas.bind("<Button-3>", lambda e: self.mouse("Right"))
        self.canvas.bind("<MouseWheel>", lambda e: self.mouse("Wheel " + ("up" if e.delta > 0 else "down")))
        self.canvas.bind("<KeyPress>", self.key_down)
        self.canvas.bind("<KeyRelease>", self.key_up)
        self.keys: dict[str, int] = {}
        self.pressed: set[str] = set()
        self.ever: set[str] = set()
        self.draw()
        row = plain(self)
        row.pack(fill="x", pady=(8, 0))
        self.last = label(row, "Last: —", size=11, muted=True)
        self.last.pack(side="left")
        button(row, "Click test (5 s)", self.click_test, height=26).pack(side="right")
        self.cps = label(self, "", size=12, bold=True)
        self.cps.pack(anchor="w")
        self._clicks: list[float] = []
        self._testing_until = 0.0

    def draw(self) -> None:
        c = self.page.colors
        unit, canvas = self.UNIT, self.canvas
        canvas.delete("all")
        self.keys = {}
        y = 6
        for row in KEY_ROWS:
            x = 6
            for key in row:
                width = WIDE.get(key, 1) * unit
                colour = c["accent"] if key in self.pressed else c["accent_dim"] if key in self.ever else c["panel"]
                rect = canvas.create_rectangle(x, y, x + width - 3, y + unit - 3, fill=colour, outline="")
                canvas.create_text(x + (width - 3) / 2, y + (unit - 3) / 2, text=SHOWN.get(key, key.upper()),
                                   fill=c["text"], font=("Segoe UI", 8))
                self.keys[key] = rect
                x += width
            y += unit

    def _key_name(self, event) -> str:
        name = SYMBOLS.get(event.keysym, event.keysym)
        return name.lower() if len(name) == 1 else name

    def key_down(self, event) -> str:
        name = self._key_name(event)
        self.pressed.add(name)
        self.ever.add(name)
        self.last.configure(text=f"Last: {event.keysym}  (code {event.keycode})")
        self.draw()
        return "break"            # Tab, arrows and Alt shouldn't move focus while testing

    def key_up(self, event) -> str:
        self.pressed.discard(self._key_name(event))
        self.draw()
        return "break"

    def mouse(self, which: str) -> None:
        self.last.configure(text=f"Last: mouse {which}")
        if which == "Left" and time.time() < self._testing_until:
            self._clicks.append(time.time())

    def click_test(self) -> None:
        self._clicks = []
        self._testing_until = time.time() + 5
        self.cps.configure(text="Click inside the box as fast as you can!")
        self.after(5000, self._click_result)

    def _click_result(self) -> None:
        count = len(self._clicks)
        best = prefs.get("best_cps", 0.0)
        cps = count / 5
        if cps > best:
            prefs.set("best_cps", cps)
        self.cps.configure(text=f"{cps:.1f} clicks per second ({count} clicks) · best {max(best, cps):.1f}")
