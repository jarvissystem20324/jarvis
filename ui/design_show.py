"""Presenting a design: a full-screen slideshow that plays each slide's
transition and its elements' entrance animations, and a presenter view —
this slide, the next one, the speaker notes and a timer.

With two screens the audience sees the slides on the second one and the
presenter view stays on the first, the way PowerPoint does it. With one
screen, "Presenter view" opens on its own for rehearsing.

Every frame is drawn by jarvis.design.render, so the show looks exactly
like the editor and the exports. Animations are a handful of frames mixed
with Pillow; a click during one finishes it.

Keys: → ↓ Space PgDn Enter (next) · ← ↑ PgUp Backspace (back) · Home/End ·
a number then Enter (go to that slide) · B black screen · W white · Esc.
"""

from __future__ import annotations

import ctypes
import sys
import time
import tkinter

from PIL import Image, ImageDraw, ImageTk

from jarvis.design import model, render

FRAMES = 9
FRAME_MS = 26
BG = "#0f1115"
FG = "#e5e7eb"
MUTED = "#9ca3af"


def monitors() -> list[tuple[int, int, int, int]]:
    """(x, y, width, height) of every screen, the main one first."""
    if sys.platform != "win32":
        return []
    try:
        from ctypes import wintypes

        found: list[tuple[int, int, int, int]] = []
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                  wintypes.LPARAM)

        def callback(_monitor, _dc, rect, _data):
            r = rect.contents
            found.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc(callback), 0)
        return sorted(found, key=lambda m: (m[0], m[1]) != (0, 0))
    except Exception:
        return []


def steps(page: dict) -> list[tuple[str, list[str]]]:
    """The page's clicks: (animation, element ids) in stacking order. A group comes in as one,
    with the first animation any of its members has — as it does in PowerPoint."""
    out, seen = [], set()
    for el in page["elements"]:
        group = el.get("group")
        if group:
            if group in seen:
                continue
            seen.add(group)
            members = model.group_members(page, group)
            anim = next((m["anim"] for m in members if m.get("anim", "none") != "none"), "none")
            if anim != "none":
                out.append((anim, [m["id"] for m in members]))
        elif el.get("anim", "none") != "none":
            out.append((el["anim"], [el["id"]]))
    return out


def transition_frame(kind: str, before: Image.Image, after: Image.Image, t: float) -> Image.Image:
    W, H = after.size
    if kind == "fade":
        return Image.blend(before, after, t)
    if kind == "push":                                  # the new slide pushes up from below
        out = Image.new("RGB", (W, H))
        offset = int(H * t)
        out.paste(before, (0, -offset))
        out.paste(after, (0, H - offset))
        return out
    if kind == "wipe":
        out = before.copy()
        width = int(W * t)
        if width:
            out.paste(after.crop((0, 0, width, H)), (0, 0))
        return out
    if kind == "split":
        out = before.copy()
        half = int(W * t / 2)
        if half:
            out.paste(after.crop((W // 2 - half, 0, W // 2 + half, H)), (W // 2 - half, 0))
        return out
    if kind == "cover":                                 # the new slide slides in over the old one
        out = before.copy()
        out.paste(after, (int(W * (1 - t)), 0))
        return out
    if kind == "zoom":
        s = 0.6 + 0.4 * t
        small = after.resize((max(1, int(W * s)), max(1, int(H * s))), Image.Resampling.BILINEAR)
        out = before.copy()
        out.paste(small, ((W - small.width) // 2, (H - small.height) // 2))
        return Image.blend(before, out, min(1.0, t * 1.4))
    return after


def effect_frame(anim: str, before: Image.Image, layer: Image.Image, box: tuple[int, int, int, int],
                 t: float) -> Image.Image:
    """`before` without the element, `layer` the element alone (transparent elsewhere)."""
    out = before.convert("RGBA")
    W, H = out.size
    left, top, right, bottom = box
    if anim == "fade":
        part = layer.copy()
        part.putalpha(part.getchannel("A").point(lambda a: int(a * t)))
        out.alpha_composite(part)
    elif anim == "wipe":
        width = int((right - left) * t)
        if width > 0:
            part = layer.crop((left, top, left + width, bottom))
            out.alpha_composite(part, (left, top))
    elif anim == "fly":
        offset = int((H - top) * (1 - t))
        if offset < H:
            render.composite(out, layer, 0, offset)
    elif anim == "zoom":
        part = layer.crop(box)
        s = 0.2 + 0.8 * t
        part = part.resize((max(1, int(part.width * s)), max(1, int(part.height * s))), Image.Resampling.BILINEAR)
        part.putalpha(part.getchannel("A").point(lambda a: int(a * min(1.0, t * 1.5))))
        cx, cy = (left + right) / 2, (top + bottom) / 2
        render.composite(out, part, cx - part.width / 2, cy - part.height / 2)
    else:
        out.alpha_composite(layer)
    return out.convert("RGB")


class Slideshow:
    def __init__(self, owner, design: dict, start: int = 0, presenter: bool = False, animate: bool = True,
                 screen: tuple[int, int, int, int] | None = None):
        self.owner = owner
        self.root = owner.winfo_toplevel()
        self.design = design
        self.index = max(0, min(start, len(design["pages"]) - 1))
        self.step = 0
        self.ended = False
        self.blank: str | None = None
        self.animate = animate
        self.closed = False
        self._cache: dict[tuple, Image.Image] = {}
        self._animating = False
        self._skip = False
        self._typed = ""
        self._current: Image.Image | None = None
        self._afters: list = []
        self.started = time.monotonic()
        self.paused_since: float | None = None
        self.paused_total = 0.0
        self.audience = self.presenter = None
        screens = monitors()
        if screen is not None:
            audience_rect, presenter_rect = screen, None
        elif presenter and len(screens) >= 2:
            audience_rect, presenter_rect = screens[1], screens[0]
        elif presenter:
            audience_rect, presenter_rect = None, None
        else:
            audience_rect, presenter_rect = (screens[0] if screens else None), None
        if not presenter or audience_rect is not None:
            self._open_audience(audience_rect, windowed=screen is not None)
        else:
            self.size = (1600, int(1600 * design["h"] / design["w"]))
        if presenter:
            self._open_presenter(presenter_rect)
        self.show()

    # --- windows --------------------------------------------------------------------------------
    def _bind(self, window) -> None:
        for key in ("<Right>", "<Down>", "<space>", "<Next>", "<Key-n>"):
            window.bind(key, lambda e: self.next())
        window.bind("<Return>", lambda e: self._enter())
        for key in ("<Left>", "<Up>", "<Prior>", "<BackSpace>", "<Key-p>"):
            window.bind(key, lambda e: self.prev())
        window.bind("<Home>", lambda e: self.go(0))
        window.bind("<End>", lambda e: self.go(len(self.design["pages"]) - 1))
        window.bind("<Escape>", lambda e: self.close())
        for key, colour in (("b", "black"), ("period", "black"), ("w", "white"), ("comma", "white")):
            window.bind(f"<Key-{key}>", lambda e, c=colour: self.toggle_blank(c))
        for digit in "0123456789":
            window.bind(f"<Key-{digit}>", lambda e, d=digit: self._digit(d))
        window.protocol("WM_DELETE_WINDOW", self.close)

    def _open_audience(self, rect, windowed: bool = False) -> None:
        win = tkinter.Toplevel(self.root)
        win.title(self.design.get("title", "Slideshow"))
        win.configure(bg="black")
        if windowed:
            x, y, w, h = rect
            win.geometry(f"{w}x{h}+{x}+{y}")
        elif rect is not None and rect[:2] != (0, 0):
            x, y, w, h = rect
            win.overrideredirect(True)
            win.geometry(f"{w}x{h}+{x}+{y}")
        else:
            w, h = win.winfo_screenwidth(), win.winfo_screenheight()
            if rect is not None:
                w, h = rect[2], rect[3]
            win.attributes("-fullscreen", True)
            win.attributes("-topmost", True)
        self.size = (int(w), int(h))
        canvas = tkinter.Canvas(win, bg="black", highlightthickness=0, bd=0, cursor="none")
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", lambda e: self.next())
        canvas.bind("<Button-3>", lambda e: self.prev())
        canvas.bind("<MouseWheel>", lambda e: self.next() if e.delta < 0 else self.prev())
        canvas.bind("<Motion>", lambda e: self._wake_cursor())
        self._bind(win)
        self.audience, self.canvas = win, canvas
        win.after(50, lambda: (win.focus_force(), canvas.focus_set()) if not self.closed else None)

    def _wake_cursor(self) -> None:
        self.canvas.configure(cursor="")
        job = getattr(self, "_cursor_job", None)
        if job:
            self.canvas.after_cancel(job)
        self._cursor_job = self.canvas.after(1800, lambda: self.closed or self.canvas.configure(cursor="none"))

    def _open_presenter(self, rect) -> None:
        win = tkinter.Toplevel(self.root)
        win.title(f"Presenter view — {self.design.get('title', '')}")
        win.configure(bg=BG)
        win.geometry("1280x760" if rect is None else f"{rect[2]}x{rect[3]}+{rect[0]}+{rect[1]}")
        if rect is not None:
            try:
                win.state("zoomed")
            except tkinter.TclError:
                pass
        bar = tkinter.Frame(win, bg=BG)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        self.timer_label = tkinter.Label(bar, text="00:00", font=("Segoe UI", 30, "bold"), fg=FG, bg=BG)
        self.timer_label.pack(side="left")

        def button(text, command):
            tkinter.Button(bar, text=text, command=command, font=("Segoe UI", 12), fg=FG, bg="#1f2430",
                           activebackground="#2d3443", activeforeground=FG, relief="flat", padx=12,
                           pady=4).pack(side="left", padx=4)

        button("⏸ / ▶", self.toggle_timer)
        button("↺", self.reset_timer)
        self.clock_label = tkinter.Label(bar, text="", font=("Segoe UI", 16), fg=MUTED, bg=BG)
        self.clock_label.pack(side="left", padx=18)
        for text, command in (("End show", self.close), ("▶", self.next), ("◀", self.prev)):
            tkinter.Button(bar, text=text, command=command, font=("Segoe UI", 12), fg=FG, bg="#1f2430",
                           activebackground="#2d3443", activeforeground=FG, relief="flat", padx=12,
                           pady=4).pack(side="right", padx=4)
        self.counter_label = tkinter.Label(bar, text="", font=("Segoe UI", 16), fg=FG, bg=BG)
        self.counter_label.pack(side="right", padx=18)
        body = tkinter.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(1, weight=1)
        self.now_view = tkinter.Label(body, bg="#000000")
        self.now_view.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16))
        side = tkinter.Frame(body, bg=BG)
        side.grid(row=0, column=1, sticky="new")
        tkinter.Label(side, text="NEXT", font=("Segoe UI", 11, "bold"), fg=MUTED, bg=BG).pack(anchor="w")
        self.next_view = tkinter.Label(side, bg="#000000")
        self.next_view.pack(anchor="w", pady=(4, 10))
        notes = tkinter.Frame(body, bg=BG)
        notes.grid(row=1, column=1, sticky="nsew")
        head = tkinter.Frame(notes, bg=BG)
        head.pack(fill="x")
        tkinter.Label(head, text="NOTES", font=("Segoe UI", 11, "bold"), fg=MUTED, bg=BG).pack(side="left")
        self.notes_size = 18
        for text, step in (("A+", 2), ("A−", -2)):
            tkinter.Button(head, text=text, command=lambda s=step: self._notes_font(s), font=("Segoe UI", 10),
                           fg=FG, bg="#1f2430", relief="flat", padx=8).pack(side="right", padx=2)
        # A small asked-for size: the grid then shares the window out, rather than a wide box
        # of notes squeezing the slide.
        self.notes_view = tkinter.Text(notes, wrap="word", bg="#161a22", fg=FG, bd=0, padx=12, pady=10, width=24,
                                       height=6, font=("Segoe UI", self.notes_size), highlightthickness=0)
        self.notes_view.pack(fill="both", expand=True, pady=(4, 0))
        self._bind(win)
        self.presenter = win
        self._size_job = None
        self._last_width = 0
        win.bind("<Configure>", lambda e: self._resized() if e.widget is win else None)
        self._tick()
        win.after(80, lambda: (win.focus_force() if not self.closed else None))

    def _resized(self) -> None:
        """Fit the previews to a resized presenter window (once it settles)."""
        if self.closed or abs(self.presenter.winfo_width() - self._last_width) < 20:
            return
        if self._size_job is not None:
            self.presenter.after_cancel(self._size_job)
        self._size_job = self.presenter.after(250, self._sync)

    def _notes_font(self, step: int) -> None:
        self.notes_size = max(10, min(48, self.notes_size + step))
        self.notes_view.configure(font=("Segoe UI", self.notes_size))

    # --- frames ---------------------------------------------------------------------------------
    def _page_without(self, index: int, hidden: set[str], only: set[str] | None = None) -> dict:
        page = self.design["pages"][index]
        keep = [e for e in page["elements"] if e["id"] not in hidden and (only is None or e["id"] in only)]
        pages = list(self.design["pages"])
        pages[index] = dict(page, elements=keep)
        return dict(self.design, pages=pages)

    def _scale(self) -> float:
        return min(self.size[0] / self.design["w"], self.size[1] / self.design["h"])

    def _offset(self, image: Image.Image) -> tuple[int, int]:
        return (self.size[0] - image.width) // 2, (self.size[1] - image.height) // 2

    def frame(self, index: int, step: int) -> Image.Image:
        key = ("frame", index, step, self.size)
        if key not in self._cache:
            hidden = {i for _, ids in steps(self.design["pages"][index])[step:] for i in ids}
            slide = render.render_page(self._page_without(index, hidden), index, self._scale())
            out = Image.new("RGB", self.size, "black")
            out.paste(slide, self._offset(slide))
            if len(self._cache) > 16:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = out
        return self._cache[key]

    def layer(self, index: int, ids: list[str]) -> tuple[Image.Image, tuple[int, int, int, int]]:
        alone = render.render_page(self._page_without(index, set(), set(ids)), index, self._scale(), transparent=True)
        out = Image.new("RGBA", self.size, (0, 0, 0, 0))
        out.alpha_composite(alone, self._offset(alone))
        return out, out.getbbox() or (0, 0, 1, 1)

    def end_frame(self) -> Image.Image:
        out = Image.new("RGB", self.size, "black")
        text = "End of the slideshow — click or press Esc to leave."
        face = render.face("Segoe UI", max(14, self.size[1] // 36))
        face.draw(ImageDraw.Draw(out), (self.size[0] - face.getlength(text)) / 2, self.size[1] / 2, text,
                  (156, 163, 175, 255))
        return out

    def _display(self, image: Image.Image) -> None:
        self._current = image
        if self.audience is not None:
            self._photo = ImageTk.PhotoImage(image, master=self.audience)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    def _play(self, make, final: Image.Image) -> None:
        if not self.animate or self.audience is None:
            self._display(final)
            return
        self._animating, self._skip = True, False

        def tick(n: int = 1) -> None:
            if self.closed:
                return
            if self._skip or n >= FRAMES:
                self._animating = False
                self._display(final)
                return
            t = n / FRAMES
            self._display(make(1 - (1 - t) ** 3))
            self._afters.append(self.audience.after(FRAME_MS, tick, n + 1))

        tick()

    # --- moving through the show ---------------------------------------------------------------
    def show(self) -> None:
        self.ended = False
        self._display(self.blank_frame() if self.blank else self.frame(self.index, self.step))
        self._sync()

    def blank_frame(self) -> Image.Image:
        return Image.new("RGB", self.size, self.blank or "black")

    def next(self) -> None:
        if self.closed:
            return
        if self._animating:
            self._skip = True
            return
        if self.blank:
            self.blank = None
            self.show()
            return
        if self.ended:
            self.close()
            return
        clicks = steps(self.design["pages"][self.index])
        if self.step < len(clicks):
            anim, ids = clicks[self.step]
            before = self.frame(self.index, self.step)
            self.step += 1
            after = self.frame(self.index, self.step)
            if anim == "appear":
                self._display(after)
            else:
                layer, box = self.layer(self.index, ids)
                self._play(lambda t: effect_frame(anim, before, layer, box, t), after)
            self._sync()
            return
        if self.index + 1 >= len(self.design["pages"]):
            self.ended = True
            self._display(self.end_frame())
            self._sync()
            return
        before = self._current or self.frame(self.index, self.step)
        self.index += 1
        self.step = 0
        after = self.frame(self.index, 0)
        kind = self.design["pages"][self.index].get("transition", "none")
        if kind in model.TRANSITIONS[1:]:
            self._play(lambda t: transition_frame(kind, before, after, t), after)
        else:
            self._display(after)
        self._sync()

    def prev(self) -> None:
        if self.closed:
            return
        self._skip = True
        self.blank = None
        if self.ended:
            self.show()
            return
        if self.step > 0:
            self.step -= 1
        elif self.index > 0:
            self.index -= 1
            self.step = len(steps(self.design["pages"][self.index]))
        self.show()

    def go(self, index: int) -> None:
        self.index = max(0, min(index, len(self.design["pages"]) - 1))
        self.step = 0
        self.blank = None
        self.show()

    def toggle_blank(self, colour: str) -> None:
        self.blank = None if self.blank == colour else colour
        self.show()

    def _digit(self, digit: str) -> None:
        self._typed = (self._typed + digit)[-3:]

    def _enter(self) -> None:
        if self._typed:
            number, self._typed = int(self._typed), ""
            self.go(number - 1)
        else:
            self.next()

    # --- presenter view -----------------------------------------------------------------------
    def elapsed(self) -> float:
        now = self.paused_since or time.monotonic()
        return now - self.started - self.paused_total

    def toggle_timer(self) -> None:
        if self.paused_since is None:
            self.paused_since = time.monotonic()
        else:
            self.paused_total += time.monotonic() - self.paused_since
            self.paused_since = None

    def reset_timer(self) -> None:
        self.started = time.monotonic()
        self.paused_total = 0.0
        self.paused_since = time.monotonic() if self.paused_since else None

    def _tick(self) -> None:
        if self.closed or self.presenter is None:
            return
        seconds = int(self.elapsed())
        hours, rest = divmod(seconds, 3600)
        self.timer_label.configure(text=(f"{hours}:" if hours else "") + f"{rest // 60:02d}:{rest % 60:02d}",
                                   fg=MUTED if self.paused_since else FG)
        self.clock_label.configure(text=time.strftime("%H:%M"))
        self._afters.append(self.presenter.after(500, self._tick))

    def _preview(self, image: Image.Image, width: int) -> ImageTk.PhotoImage:
        height = max(1, int(width * image.height / image.width))
        return ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.BILINEAR), master=self.presenter)

    def _sync(self) -> None:
        if self.presenter is None or self.closed:
            return
        pages = self.design["pages"]
        total = len(pages)
        self.counter_label.configure(text=f"Slide {self.index + 1} / {total}" + (" · end" if self.ended else ""))
        self._size_job = None
        self._last_width = self.presenter.winfo_width()
        width = max(400, int(self._last_width * 0.56) or 700)
        current = self.end_frame() if self.ended else self.frame(self.index, self.step)
        self._now_photo = self._preview(current, width)
        self.now_view.configure(image=self._now_photo)
        clicks = steps(pages[self.index])
        if self.ended:
            upcoming = None
        elif self.step < len(clicks):
            upcoming = self.frame(self.index, self.step + 1)
        elif self.index + 1 < total:
            upcoming = self.frame(self.index + 1, 0)
        else:
            upcoming = self.end_frame()
        if upcoming is not None:
            self._next_photo = self._preview(upcoming, max(240, int(width * 0.62)))
            self.next_view.configure(image=self._next_photo)
        self.notes_view.configure(state="normal")
        self.notes_view.delete("1.0", "end")
        notes = pages[self.index].get("notes", "").strip()
        self.notes_view.insert("1.0", notes or "No notes for this slide.")
        self.notes_view.configure(state="disabled")

    # --- the end ------------------------------------------------------------------------------
    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for window in (self.audience, self.presenter):
            if window is None:
                continue
            for job in self._afters:
                try:
                    window.after_cancel(job)
                except (tkinter.TclError, ValueError):
                    pass
            try:
                window.destroy()
            except tkinter.TclError:
                pass
        try:
            self.owner._say("Slideshow ended.")
            self.owner.canvas.focus_set()
        except Exception:
            pass
