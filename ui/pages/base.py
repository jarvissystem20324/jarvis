"""What every 10.0 page is made of.

A Page is built the first time it is shown, so the thirty-odd pages cost
nothing until someone opens them. A Hub is a Page with a title and a
scrolling body of cards. A ToolForm draws any registered command as fields
and a Run button and shows what came back — which is how one command works
the same from the chat, the Tools page, the Ctrl+K palette and an area page.

Everything slow runs on a worker thread and comes back through after(); a
worker never touches a widget.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
import tkinter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jarvis.registry import Tool

PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\n\"<>|*?]+?\.[A-Za-z0-9]{1,6})(?=[\s),;:'\]]|$)")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def colors() -> dict:
    from ui import app

    return app.COLORS


def safe_after(widget, callback) -> None:
    try:
        widget.after(0, callback)
    except (RuntimeError, tkinter.TclError):
        pass


@contextmanager
def one_layout(widget, settle: bool = True):
    """Build many widgets with one layout pass at the end instead of hundreds.

    customtkinter's scrollbars and option menus call update_idletasks() every
    time they draw, and a scrollbar redraws whenever the page under it grows.
    Each of those calls lays out the whole window, so a page of thirty tool
    cards laid itself out several hundred times and took 13 seconds to open.
    Tk is single-threaded, so muting the call for the length of a build
    affects nothing else.
    """
    from customtkinter.windows.widgets.core_rendering.ctk_canvas import CTkCanvas

    global _layout_depth
    if _layout_depth == 0:
        CTkCanvas.update_idletasks = _no_layout
    _layout_depth += 1
    try:
        yield
        if settle and _layout_depth == 1:
            try:
                widget.update_idletasks()
            except tkinter.TclError:
                pass
    finally:
        _layout_depth -= 1
        if _layout_depth == 0:
            del CTkCanvas.update_idletasks


_layout_depth = 0


def _no_layout(self) -> None:
    pass


def background(widget, work, done=None, error=None) -> threading.Thread:
    """Run work() on a thread; done(result) or error(exception) on the Tk thread."""

    def run():
        try:
            result = work()
        except Exception as exc:  # shown to the user, never raised into Tk
            if error is not None:
                safe_after(widget, lambda e=exc: error(e))
            elif done is not None:
                safe_after(widget, lambda e=exc: done(f"Something went wrong: {e}"))
            return
        if done is not None:
            safe_after(widget, lambda r=result: done(r))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def open_path(path) -> None:
    path = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 — the user's own file, opened on request
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def show_in_folder(path) -> None:
    path = Path(path)
    if sys.platform == "win32" and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_path(path.parent)


def button(parent, text, command, width=0, height=30, accent=False, **kw):
    c = colors()
    return ctk.CTkButton(parent, text=text, command=command, width=width, height=height,
                         fg_color=c["accent_dim"] if accent else c["bg"],
                         hover_color=c["accent"] if accent else c["accent_dim"],
                         text_color=c["text"], **kw)


def label(parent, text, size=12, bold=False, muted=False, wrap=0, icon="", **kw):
    c = colors()
    colour = kw.pop("text_color", None) or (c["muted"] if muted else c["text"])
    if not kw:
        return Text(parent, text, size, bold, colour, wrap, icon)
    if icon:
        text = f"{icon}  {text}"
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                        text_color=colour, justify="left", anchor="w", wraplength=wrap, **kw)


# Plain Tk stand-ins for the two widgets a page has most of. A CTkLabel or a
# "transparent" CTkFrame draws itself on a canvas and redraws on every resize;
# a page of tool cards had ~550 of them and spent seconds redrawing. These
# paint the colour they sit on, so they look the same and cost a tenth.

def surface(widget) -> str:
    """The colour a plain Tk widget must paint to sit invisibly on `widget`."""
    while widget is not None:
        try:
            colour = widget.cget("fg_color")
        except (tkinter.TclError, ValueError):  # a plain Tk widget knows its own
            try:
                return widget.cget("bg")
            except tkinter.TclError:
                break
        if colour and colour != "transparent":
            if isinstance(colour, (tuple, list)):
                colour = colour[1] if ctk.get_appearance_mode() == "Dark" else colour[0]
            return colour
        widget = widget.master
    return colors()["bg"]


class _Scaled:
    """Scales pack/grid padding like a CTk widget, so spacing stays the same on a high-DPI screen."""

    def _scaled(self, kw: dict) -> dict:
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        for key in ("padx", "pady"):
            value = kw.get(key)
            if isinstance(value, (int, float)):
                kw[key] = round(value * scale)
            elif isinstance(value, tuple):
                kw[key] = tuple(round(v * scale) for v in value)
        return kw

    def pack(self, **kw):
        return super().pack(**self._scaled(kw))

    def grid(self, **kw):
        return super().grid(**self._scaled(kw))


class Plain(_Scaled, tkinter.Frame):
    """A layout-only frame: a CTkFrame(fg_color="transparent") without the canvas."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=surface(parent), bd=0, highlightthickness=0, **kw)


def plain(parent, **kw) -> Plain:
    return Plain(parent, **kw)


def text_font(widget, size: int, bold: bool = False):
    """A shared Font as big as a CTkFont of this size, the padding that makes a
    one-line label as tall as a CTkLabel (28 px), and the scaling.

    Shared because Tk resolves a font tuple afresh for every widget.
    """
    scale = ctk.ScalingTracker.get_widget_scaling(widget)
    root = widget._root()
    fonts = root.__dict__.setdefault("_jarvis_fonts", {})  # one set per window; fonts die with it
    key = (size, bold, scale)
    if key not in fonts:
        from tkinter import font as tkfont

        family, pixels, *weight = ctk.CTkFont(size=size, weight="bold" if bold else "normal").create_scaled_tuple(scale)
        font = tkfont.Font(root=root, family=family, size=pixels, weight="bold" if bold else "normal")
        fonts[key] = (font, max(0, round((28 * scale - font.metrics("linespace")) / 2)), scale)
    return fonts[key]


_EMOJI_FONT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "seguiemj.ttf"
_emoji_fonts: dict = {}


def emoji_image(widget, icon: str, size: int):
    """`icon` as a colour picture the height of `size`-pixel text, or None.

    Tk draws an emoji through Windows' font fallback, which costs 13 ms per
    label — the Tools page's 344 tiles took 4.5 s for their icons alone — and
    comes out black and white. Drawn once by Pillow from the Windows emoji
    font, the same icon costs nothing the second time and is in colour.
    None when the icon is not one emoji that font has (newer emoji are missing
    from Windows 10's), or off Windows; the caller then shows it as text.
    """
    glyph = icon.replace("\ufe0f", "")
    if len(glyph) != 1 or ord(glyph) < 0x2190 or not _EMOJI_FONT.exists():
        return None
    scale = ctk.ScalingTracker.get_widget_scaling(widget)
    pixels = max(8, round(size * scale))
    root = widget._root()
    images = root.__dict__.setdefault("_jarvis_emoji", {})  # one set per window
    key = (glyph, pixels)
    if key not in images:
        images[key] = _draw_emoji(root, glyph, pixels)
    return images[key]


def _draw_emoji(root, glyph: str, pixels: int):
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        def shape(font, text: str) -> bytes:
            mask = Image.new("L", (pixels * 2, pixels * 2))
            ImageDraw.Draw(mask).text((0, 0), text, font=font, fill=255)
            return mask.tobytes()

        if pixels not in _emoji_fonts:
            font = ImageFont.truetype(str(_EMOJI_FONT), pixels)
            _emoji_fonts[pixels] = (font, shape(font, "\ue000"))  # what a missing glyph looks like
        font, missing = _emoji_fonts[pixels]
        if shape(font, glyph) == missing:
            return None
        side = round(pixels * 1.25)
        picture = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        draw = ImageDraw.Draw(picture)
        left, top, right, bottom = draw.textbbox((0, 0), glyph, font=font, embedded_color=True)
        draw.text(((side - (right - left)) / 2 - left, (side - (bottom - top)) / 2 - top), glyph, font=font,
                  embedded_color=True)
        return ImageTk.PhotoImage(picture, master=root)
    except Exception:
        return None


class Text(_Scaled, tkinter.Label):
    """Text that looks like label()'s CTkLabel: same font, colour and height.
    An icon goes in front as a colour picture (see emoji_image)."""

    def __init__(self, parent, text, size=12, bold=False, colour="", wrap=0, icon=""):
        font, pad, scale = text_font(parent, size, bold)
        picture = emoji_image(parent, icon, size) if icon else None
        if icon:
            text = f"  {text}" if picture is not None else f"{icon}  {text}"
        super().__init__(parent, text=text, font=font, fg=colour or colors()["text"], bg=surface(parent),
                         justify="left", anchor="w", wraplength=round(wrap * scale) if wrap else 0,
                         bd=0, padx=0, pady=pad, highlightthickness=0,
                         image=picture or "", compound="left" if picture is not None else "none")
        if wrap:
            # Wrap at the container's width too, so text never runs off a narrow card.
            self._widest = round(wrap * scale)
            parent.bind("<Configure>", lambda e: self._fit(e.width), add="+")

    def _fit(self, room: int) -> None:
        try:
            now = int(self.cget("wraplength"))
            # Narrower only when the container is cutting its contents off (if
            # its width came from this text, narrowing would shrink it again
            # and again); wider again, up to wrap, when it has room.
            clipped = room < self.master.winfo_reqwidth()
            want = min(self._widest, room)
            if room > 40 and ((want < now and clipped) or now < want):
                super().configure(wraplength=want)
        except tkinter.TclError:
            pass

    def configure(self, cnf=None, **kw):
        if "text_color" in kw:
            kw["fg"] = kw.pop("text_color")
        return super().configure(cnf, **kw)

    config = configure


class Card(ctk.CTkFrame):
    """A rounded panel with a title; put things in .inner."""

    def __init__(self, parent, title: str = "", subtitle: str = "", icon: str = ""):
        c = colors()
        super().__init__(parent, fg_color=c["panel"], corner_radius=12)
        if title:
            head = plain(self)
            head.pack(fill="x", padx=14, pady=(12, 0))
            label(head, title, size=14, bold=True, icon=icon).pack(anchor="w")
            if subtitle:
                label(head, subtitle, size=11, muted=True, wrap=420).pack(anchor="w")
        self.inner = plain(self)
        self.inner.pack(fill="both", expand=True, padx=14, pady=12)


class Page(ctk.CTkFrame):
    key = ""
    title = ""
    icon = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color=colors()["bg"], corner_radius=0)
        self.app = app
        self.colors = colors()
        self._built = False
        self._jobs: dict[str, str] = {}

    # --- lifecycle --------------------------------------------------------------
    def show(self) -> None:
        with one_layout(self):
            try:
                if not self._built:
                    self._built = True
                    self.build()
                self.on_show()
            except Exception as exc:  # a broken page says so instead of staying blank
                self._broken(exc)

    def _broken(self, exc: Exception) -> None:
        import traceback

        where = traceback.extract_tb(exc.__traceback__)[-1]
        text = (f"This page hit an error: {type(exc).__name__}: {exc}\n"
                f"({Path(where.filename).name}, line {where.lineno}) — its tools are still on the Tools page.")
        note = label(self, text, size=12, wrap=900, text_color=self.colors["error"])
        # place, not pack: the page may already lay itself out with grid.
        note.place(x=20, y=10)
        note.lift()

    def build(self) -> None:
        pass

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def close(self) -> None:
        for job in list(self._jobs.values()):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()

    def every(self, name: str, ms: int, fn) -> None:
        """Call fn every ms while this page is on screen."""

        def tick():
            self._jobs.pop(name, None)
            try:
                if self.winfo_ismapped():
                    fn()
            except Exception:
                pass
            try:
                self._jobs[name] = self.after(ms, tick)
            except (RuntimeError, tkinter.TclError):
                pass

        if name in self._jobs:
            try:
                self.after_cancel(self._jobs[name])
            except Exception:
                pass
        self._jobs[name] = self.after(ms, tick)

    def run(self, work, done=None, error=None):
        return background(self, work, done, error)

    def tool(self, parent, name: str, **kw) -> "ToolForm | None":
        tool = self.app.tool(name)
        if tool is None:
            return None
        form = ToolForm(parent, self.app, tool, **kw)
        return form


class Hub(Page):
    """A page with a header and a scrolling body of cards in columns."""

    columns = 2

    def build(self) -> None:
        c = self.colors
        head = plain(self)
        head.pack(fill="x", padx=20, pady=(16, 6))
        label(head, self.title, size=22, bold=True, icon=self.icon, text_color=c["accent"]).pack(anchor="w")
        if self.subtitle:
            label(head, self.subtitle, size=12, muted=True, wrap=900).pack(anchor="w")
        self.header = head
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        for col in range(self.columns):
            self.body.grid_columnconfigure(col, weight=1, uniform="col")
        self._row = 0
        self._col = 0
        self._unfilled: list = []
        self._fill_job = None
        self.build_body()

    def build_body(self) -> None:
        pass

    def place(self, widget, span: int = 1) -> None:
        """Put a widget in the next free cell; span=columns for a full row."""
        span = min(span, self.columns)
        if self._col + span > self.columns:
            self._row += 1
            self._col = 0
        widget.grid(row=self._row, column=self._col, columnspan=span, sticky="nsew", padx=8, pady=8)
        self._col += span
        if self._col >= self.columns:
            self._row += 1
            self._col = 0

    def section(self, text: str) -> None:
        if self._col:
            self._row += 1
            self._col = 0
        label(self.body, text, size=15, bold=True, text_color=self.colors["accent"]).grid(
            row=self._row, column=0, columnspan=self.columns, sticky="w", padx=10, pady=(14, 0))
        self._row += 1

    def card(self, title: str, subtitle: str = "", icon: str = "", span: int = 1) -> Card:
        card = Card(self.body, title, subtitle, icon)
        self.place(card, span)
        return card

    def tool_card(self, name: str, span: int = 1, **kw) -> Card | None:
        """A command's card. Its form is drawn just after the page appears,
        a few cards at a time, so a page of thirty forms opens at once."""
        tool = self.app.tool(name)
        if tool is None:
            return None
        card = Card(self.body, tool.label(), tool.help, tool.icon)
        self.place(card, span)
        self._unfilled.append((card, tool, kw))
        if self._fill_job is None:
            self._fill_job = self.after(1, lambda: self.after_idle(self._fill_forms))
        return card

    def tools(self, *names: str) -> None:
        for name in names:
            self.tool_card(name)

    def _fill_forms(self) -> None:
        # after_idle, so the page draws (Tk's own idle work) between batches.
        self._fill_job = None
        started = time.perf_counter()
        try:
            with one_layout(self, settle=False):
                while self._unfilled and time.perf_counter() - started < 0.08:
                    card, tool, kw = self._unfilled.pop(0)
                    ToolForm(card.inner, self.app, tool, show_help=False, **kw).pack(fill="both", expand=True)
        except tkinter.TclError:  # the window closed under us
            self._unfilled.clear()
            return
        if self._unfilled:
            self._fill_job = self.after(1, lambda: self.after_idle(self._fill_forms))


class ResultView(Plain):
    """What a command answered: text, pictures, files to open."""

    def __init__(self, parent, app, max_lines: int = 18):
        super().__init__(parent)
        self.app = app
        self.max_lines = max_lines
        self._images: list = []

    def clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._images = []

    def show(self, response) -> None:
        self.clear()
        c = colors()
        text = getattr(response, "text", response)
        text = "" if text is None else str(text)
        if text.strip():
            lines = sum(max(1, len(line) // 70 + 1) for line in text.splitlines()) or 1
            box = ctk.CTkTextbox(self, height=min(self.max_lines, max(2, lines)) * 19 + 12, wrap="word",
                                 fg_color=c["bg"], text_color=c["text"], font=ctk.CTkFont(size=12))
            box.insert("1.0", text)
            box.configure(state="disabled")
            box.pack(fill="x", pady=(6, 2))
            row = plain(self)
            row.pack(fill="x")
            button(row, "⧉ Copy", lambda t=text: self._copy(t), height=24).pack(side="left", padx=(0, 6))
            self.text_box = box
        paths: list[Path] = []
        for p in list(getattr(response, "image_paths", None) or []) + [getattr(response, "image_path", None)]:
            if p and Path(p) not in paths:
                paths.append(Path(p))
        for raw in PATH_RE.findall(text):
            path = Path(raw.strip().rstrip("."))
            if path.exists() and path not in paths:
                paths.append(path)
        if getattr(response, "open_page", ""):
            self.after(10, lambda r=response: self.app.follow_page(r))
        design = getattr(response, "design_path", None)
        if design:
            button(self, "🖌 Open in Design", lambda d=design: self.app.open_design(Path(d)), accent=True).pack(
                anchor="w", pady=4)
        shown = 0
        for path in paths[:6]:
            row = plain(self)
            row.pack(fill="x", pady=2)
            if path.suffix.lower() in IMAGE_EXT and shown < 3:
                try:
                    from PIL import Image

                    with Image.open(path) as im:
                        im.thumbnail((360, 240))
                        image = ctk.CTkImage(im.copy(), size=im.size)
                    self._images.append(image)
                    ctk.CTkButton(row, image=image, text="", fg_color="transparent", hover=False,
                                  command=lambda p=path: open_path(p)).pack(anchor="w")
                    shown += 1
                except Exception:
                    pass
            line = plain(row)
            line.pack(fill="x")
            label(line, path.name, size=11, muted=True).pack(side="left")
            button(line, "Open", lambda p=path: open_path(p), height=24).pack(side="left", padx=6)
            button(line, "Show in folder", lambda p=path: show_in_folder(p), height=24).pack(side="left")

    def _copy(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tkinter.TclError:
            pass


class ToolForm(Plain):
    """A command as fields and a Run button."""

    def __init__(self, parent, app, tool: Tool, show_help: bool = True, prefill: dict | None = None,
                 on_result=None, run_label: str = "Run"):
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.on_result = on_result
        self.run_label = run_label
        self.inputs: dict[str, tuple[str, object]] = {}
        c = colors()
        if show_help and tool.help:
            label(self, tool.help, size=12, muted=True, wrap=460).pack(anchor="w", pady=(0, 6))
        prefill = prefill or {}
        for spec in tool.fields:
            self._field(spec, prefill.get(spec.name))
        choices = tool.extra.get("choices") or []
        if choices and tool.fields:
            row = plain(self)
            row.pack(fill="x", pady=(2, 4))
            for choice in choices:
                button(row, choice, lambda v=choice: self._set_first(v), height=22,
                       font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
        row = plain(self)
        row.pack(fill="x", pady=(4, 0))
        self.run_button = button(row, f"▶  {run_label}", self.run, accent=True, height=32)
        self.run_button.pack(side="left")
        self.error = label(row, "", size=11, text_color=c["error"])
        self.error.pack(side="left", padx=10)
        self.result = ResultView(self, app)
        self.result.pack(fill="x")

    # --- fields -----------------------------------------------------------------
    def _field(self, spec, value) -> None:
        c = colors()
        row = plain(self)
        row.pack(fill="x", pady=2)
        text = spec.label + ("" if not spec.optional else "  (optional)")
        label(row, text, size=11, muted=True).pack(anchor="w")
        value = spec.default if value is None else value
        kind = spec.kind
        if kind == "long":
            widget = ctk.CTkTextbox(row, height=90, fg_color=c["bg"], wrap="word")
            if value:
                widget.insert("1.0", value)
            widget.pack(fill="x")
        elif kind == "choice":
            options = [str(o) for o in spec.options] or [""]
            var = tkinter.StringVar(value=value if value in options else options[0])
            if len(options) <= 4 and sum(len(o) for o in options) < 34:
                widget = ctk.CTkSegmentedButton(row, values=options, variable=var)
            else:
                widget = ctk.CTkOptionMenu(row, values=options, variable=var, fg_color=c["bg"],
                                           button_color=c["accent_dim"])
            widget.pack(anchor="w")
            widget = var
        elif kind == "bool":
            var = tkinter.StringVar(value="on" if str(value).lower() in {"on", "1", "true", "yes"} else "")
            widget = ctk.CTkSwitch(row, text="", variable=var, onvalue="on", offvalue="")
            widget.pack(anchor="w")
            widget = var
        else:
            line = plain(row)
            line.pack(fill="x")
            if kind == "date" and not value:
                value = date.today().isoformat()
            entry = ctk.CTkEntry(line, placeholder_text=spec.hint or "", fg_color=c["bg"])
            if value:
                entry.insert(0, value)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Return>", lambda e: self.run())
            browse = self.tool.extra.get("browse") if self.tool.fields and spec is self.tool.fields[0] else None
            if kind in {"file", "files", "folder"} or browse:
                pick = kind if kind in {"file", "files", "folder"} else browse
                button(line, "Browse…", lambda e=entry, k=pick, s=spec: self._browse(e, k, s), height=28).pack(
                    side="left", padx=(6, 0))
            if kind == "color":
                button(line, "Pick…", lambda e=entry: self._color(e), height=28).pack(side="left", padx=(6, 0))
            widget = entry
        self.inputs[spec.name] = (kind, widget)

    def _browse(self, entry, kind, spec) -> None:
        types = list(spec.types) + [("All files", "*.*")]
        if kind == "folder":
            path = filedialog.askdirectory(parent=self)
        elif kind == "files":
            many = filedialog.askopenfilenames(parent=self, filetypes=types)
            path = ";".join(many)
        else:
            path = filedialog.askopenfilename(parent=self, filetypes=types)
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _color(self, entry) -> None:
        from tkinter import colorchooser

        picked = colorchooser.askcolor(parent=self, initialcolor=entry.get() or "#00d4ff")
        if picked and picked[1]:
            entry.delete(0, "end")
            entry.insert(0, picked[1])

    def _set_first(self, value: str) -> None:
        if not self.tool.fields:
            return
        name = self.tool.fields[0].name
        kind, widget = self.inputs[name]
        if kind == "long":
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
        elif isinstance(widget, tkinter.StringVar):
            widget.set(value)
        else:
            widget.delete(0, "end")
            widget.insert(0, value)
            widget.focus_set()

    def values(self) -> dict[str, str]:
        out = {}
        for name, (kind, widget) in self.inputs.items():
            if kind == "long":
                out[name] = widget.get("1.0", "end").strip()
            else:
                out[name] = widget.get().strip()
        return out

    def focus_first(self) -> None:
        for kind, widget in self.inputs.values():
            if not isinstance(widget, tkinter.StringVar):
                try:
                    widget.focus_set()
                except Exception:
                    pass
                return

    # --- running ----------------------------------------------------------------
    def run(self) -> None:
        values = self.values()
        missing = [f.label for f in self.tool.fields if not f.optional and not values.get(f.name)]
        if missing:
            self.error.configure(text=f"Fill in: {', '.join(missing)}")
            return
        self.error.configure(text="")
        text = self.tool.build(values)
        if self.tool.chat:
            self.app.run_in_chat(text)
            return
        self.run_button.configure(state="disabled", text="…  Working")
        self.app.run_tool(text, self._done, name=self.tool.name)

    def _done(self, response) -> None:
        try:
            self.run_button.configure(state="normal", text=f"▶  {self.run_label}")
        except tkinter.TclError:
            return
        self.result.show(response)
        if self.on_result is not None:
            self.on_result(response)


class ToolDialog(ctk.CTkToplevel):
    """One command in its own small window — from the Tools page or Ctrl+K."""

    def __init__(self, app, tool: Tool, prefill: dict | None = None):
        super().__init__(app)
        c = colors()
        self.configure(fg_color=c["bg"])
        self.title(f"{tool.label()} — JARVIS")
        self.geometry("620x560")
        self.minsize(460, 300)
        try:
            self.transient(app)
        except tkinter.TclError:
            pass
        head = plain(self)
        head.pack(fill="x", padx=18, pady=(14, 4))
        label(head, tool.label(), size=18, bold=True, icon=tool.icon, text_color=c["accent"]).pack(anchor="w")
        label(head, f"{tool.usage}", size=11, muted=True).pack(anchor="w")
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.form = ToolForm(body, app, tool, prefill=prefill)
        self.form.pack(fill="both", expand=True, padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(120, self._focus)
        if not tool.fields and not tool.chat:
            self.after(150, self.form.run)

    def _focus(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.form.focus_first()
        except tkinter.TclError:
            pass
