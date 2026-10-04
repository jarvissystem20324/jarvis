"""The JARVIS orb, drawn on a canvas (10.0).

One drawing for three places: the big orb on the Home page, the floating orb
that sits on the desktop, and anywhere else that wants one. Rotating arc
segments around a pulsing core, coloured by what JARVIS is doing — idle,
listening, thinking or speaking — the way the arc reactor on the films reads.

Only canvas primitives, redrawn every 50 ms while visible; nothing is drawn
while the orb is hidden.
"""

from __future__ import annotations

import math
import time
import tkinter

STATE_COLOURS = {"listening": "#4ade80", "thinking": "#fbbf24", "speaking": None, "idle": None}


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

    def draw(self) -> None:
        colour, state = self.colour()
        t = time.monotonic() - self._start
        s = self.size
        c = s / 2
        bg = self.background
        speed = {"thinking": 3.0, "listening": 1.6, "speaking": 2.2}.get(state, 0.8)
        pulse = (math.sin(t * (4 if state != "idle" else 1.6)) + 1) / 2
        self.delete("all")
        # Glow: concentric rings fading into the background.
        for i in range(6, 0, -1):
            r = s * (0.30 + i * 0.03)
            self.create_oval(c - r, c - r, c + r, c + r, outline="",
                             fill=_mix(bg, colour, 0.05 + (6 - i) * 0.025 + pulse * 0.02))
        # Outer ring of rotating segments.
        r = s * 0.44
        for i in range(12):
            start = (t * 40 * speed + i * 30) % 360
            self.create_arc(c - r, c - r, c + r, c + r, start=start, extent=18, style="arc",
                            outline=_mix(bg, colour, 0.55 + 0.4 * ((i % 3) == 0)), width=max(2, s // 40))
        # Counter-rotating inner ring.
        r2 = s * 0.34
        for i in range(3):
            start = (-t * 70 * speed + i * 120) % 360
            self.create_arc(c - r2, c - r2, c + r2, c + r2, start=start, extent=80, style="arc",
                            outline=colour, width=max(2, s // 28))
        # Triangle of the Mark VI reactor, faint.
        r3 = s * 0.24
        points = []
        for k in range(3):
            angle = math.radians(90 + k * 120 + t * 10)
            points += [c + r3 * math.cos(angle), c - r3 * math.sin(angle)]
        self.create_polygon(points, outline=_mix(bg, colour, 0.5), fill="", width=max(1, s // 60))
        # Core.
        core = s * (0.12 + 0.02 * pulse)
        self.create_oval(c - core * 1.6, c - core * 1.6, c + core * 1.6, c + core * 1.6, outline="",
                         fill=_mix(bg, colour, 0.35))
        self.create_oval(c - core, c - core, c + core, c + core, outline="", fill=_mix(colour, "#ffffff", 0.55))
        if self.label and s >= 160:
            self.create_text(c, s * 0.93, text=self.label, fill=_mix(bg, colour, 0.75),
                             font=("Consolas", max(8, s // 22)))
