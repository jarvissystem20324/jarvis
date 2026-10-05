"""The JARVIS orb, drawn on a canvas (10.0).

One drawing for three places: the big orb on the Home page, the floating orb
that sits on the desktop, and anywhere else that wants one. Rotating arc
segments around a pulsing core, coloured by what JARVIS is doing — idle,
listening, thinking or speaking — the way the arc reactor on the films reads.

Only canvas primitives, moved every 50 ms while visible; nothing is drawn
while the orb is hidden, or while the main window is being dragged or
resized (10.0.1: the see-through floating orb redrawing under a drag held
the drag to 20 frames a second). The shapes are made once and then only
moved and recoloured, not deleted and re-made every frame.
"""

from __future__ import annotations

import math
import time
import tkinter

STATE_COLOURS = {"listening": "#4ade80", "thinking": "#fbbf24", "speaking": None, "idle": None}
# Set by the window: true while it's being dragged or resized.
PAUSED = lambda: False  # noqa: E731


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: str, b: str, t: float) -> str:
    x, y = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(p + (q - p) * t):02x}" for p, q in zip(x, y))


class Orb(tkinter.Canvas):
    def __init__(self, parent, size: int, accent: str, background: str, state=None, label: str = ""):
        super().__init__(parent, width=size, height=size, bg=background, highlightthickness=0, bd=0)
        self.size = size
        self.accent = accent
        self.background = background
        self.state_fn = state or (lambda: "idle")
        self.label = label
        self._job = None
        self._start = time.monotonic()
        self._items: dict | None = None
        self._fills: dict[int, str] = {}
        self.bind("<Map>", lambda e: self._run())
        self.bind("<Unmap>", lambda e: self._halt())

    def _run(self) -> None:
        if self._job is None:
            self._tick()

    def _halt(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _tick(self) -> None:
        self._job = None
        try:
            if not self.winfo_ismapped():
                return
            if not _paused():
                self.draw()
            self._job = self.after(50, self._tick)
        except tkinter.TclError:
            self._job = None

    def colour(self) -> str:
        try:
            state = self.state_fn()
        except Exception:
            state = "idle"
        return STATE_COLOURS.get(state) or self.accent, state

    def _build(self) -> dict:
        """The shapes, made once; draw() only moves and recolours them."""
        self.delete("all")
        s, c = self.size, self.size / 2
        items = {"glow": [], "outer": [], "inner": []}
        for i in range(6, 0, -1):
            r = s * (0.30 + i * 0.03)
            items["glow"].append(self.create_oval(c - r, c - r, c + r, c + r, outline="", fill=self.background))
        r = s * 0.44
        for i in range(12):
            items["outer"].append(self.create_arc(c - r, c - r, c + r, c + r, start=0, extent=18, style="arc",
                                                  outline=self.background, width=max(2, s // 40)))
        r2 = s * 0.34
        for i in range(3):
            items["inner"].append(self.create_arc(c - r2, c - r2, c + r2, c + r2, start=0, extent=80, style="arc",
                                                  outline=self.background, width=max(2, s // 28)))
        items["triangle"] = self.create_polygon(0, 0, 0, 0, 0, 0, outline=self.background, fill="",
                                                width=max(1, s // 60))
        items["halo"] = self.create_oval(0, 0, 0, 0, outline="", fill=self.background)
        items["core"] = self.create_oval(0, 0, 0, 0, outline="", fill=self.background)
        items["label"] = self.create_text(c, s * 0.93, text=self.label if self.label and s >= 160 else "",
                                          fill=self.background, font=("Consolas", max(8, s // 22)))
        self._fills = {}
        return items

    def _paint(self, item: int, option: str, colour: str) -> None:
        """Recolour only when the colour really changed (most frames it doesn't)."""
        if self._fills.get((item, option)) != colour:
            self._fills[(item, option)] = colour
            self.itemconfigure(item, **{option: colour})

    def draw(self) -> None:
        if self._items is None:
            self._items = self._build()
        items = self._items
        colour, state = self.colour()
        t = time.monotonic() - self._start
        s = self.size
        c = s / 2
        bg = self.background
        speed = {"thinking": 3.0, "listening": 1.6, "speaking": 2.2}.get(state, 0.8)
        pulse = (math.sin(t * (4 if state != "idle" else 1.6)) + 1) / 2
        # Glow: concentric rings fading into the background. (Rounded, so a slow pulse
        # changes the colour only every few frames.)
        for n, item in enumerate(items["glow"]):
            self._paint(item, "fill", _mix(bg, colour, round(0.05 + n * 0.025 + pulse * 0.02, 3)))
        # Outer ring of rotating segments.
        for i, item in enumerate(items["outer"]):
            self.itemconfigure(item, start=(t * 40 * speed + i * 30) % 360)
            self._paint(item, "outline", _mix(bg, colour, 0.55 + 0.4 * ((i % 3) == 0)))
        # Counter-rotating inner ring.
        for i, item in enumerate(items["inner"]):
            self.itemconfigure(item, start=(-t * 70 * speed + i * 120) % 360)
            self._paint(item, "outline", colour)
        # Triangle of the Mark VI reactor, faint.
        r3 = s * 0.24
        points = []
        for k in range(3):
            angle = math.radians(90 + k * 120 + t * 10)
            points += [c + r3 * math.cos(angle), c - r3 * math.sin(angle)]
        self.coords(items["triangle"], *points)
        self._paint(items["triangle"], "outline", _mix(bg, colour, 0.5))
        # Core.
        core = s * (0.12 + 0.02 * pulse)
        self.coords(items["halo"], c - core * 1.6, c - core * 1.6, c + core * 1.6, c + core * 1.6)
        self._paint(items["halo"], "fill", _mix(bg, colour, 0.35))
        self.coords(items["core"], c - core, c - core, c + core, c + core)
        self._paint(items["core"], "fill", _mix(colour, "#ffffff", 0.55))
        self._paint(items["label"], "fill", _mix(bg, colour, 0.75))


def _paused() -> bool:
    try:
        return bool(PAUSED())
    except Exception:
        return False
