"""Design 2.0 on the Design page: selecting several things (Shift+click or a
box), groups, aligning, rulers and guides, smart snapping, the pen, the
emoji picker, charts and their data, text styles, AI rewriting, find and
replace, spell check, taking the white off a picture, slides from Excel, a
PDF's pages, designs from a sketch photo, transitions, animations and the
slideshow.

DesignTools is mixed into DesignPage (ui/designui.py), so `self` here is the
page: it has the design, the canvas and the side panels.
"""

from __future__ import annotations

import math
import tkinter
import unicodedata
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import ImageTk

from jarvis.design import chart as chart_mod
from jarvis.design import extras, fonts, model, render, templates

RULER = 22
# size as a share of the page's height, bold, heading font
TEXT_STYLES = {"title": (0.085, True, True), "heading": (0.055, True, True), "subheading": (0.04, True, False),
               "body": (0.032, False, False), "caption": (0.022, False, False)}
ANIM_LABELS = {"none": "None", "appear": "Appear", "fade": "Fade in", "fly": "Fly in", "zoom": "Zoom",
               "wipe": "Wipe"}
TRANSITION_LABELS = {"none": "None", "fade": "Fade", "push": "Push", "wipe": "Wipe", "split": "Split",
                     "cover": "Cover", "zoom": "Zoom"}
EMOJI_RANGES = ((0x1F600, 0x1F64F), (0x1F910, 0x1F9FF), (0x1F300, 0x1F5FF), (0x1F680, 0x1F6FF),
                (0x1FA70, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF))
_EMOJI: list[tuple[str, str]] | None = None


def all_emoji() -> list[tuple[str, str]]:
    """(emoji, its name) for every single-character emoji this PC's emoji font can draw."""
    global _EMOJI
    if _EMOJI is None:
        font = fonts.emoji(20)[0]
        found = []
        for low, high in EMOJI_RANGES:
            for code in range(low, high + 1):
                ch = chr(code)
                name = unicodedata.name(ch, "")
                if name and render.has_glyph(font, ch):
                    found.append((ch, name.lower()))
        _EMOJI = found
    return _EMOJI


def nice_step(scale: float, pixels: float = 70) -> float:
    raw = pixels / max(scale, 1e-6)
    exp = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 5, 10):
        if f * exp >= raw:
            return f * exp
    return 10 * exp


class DesignTools:
    # =====================================================================================
    # selecting several things
    # =====================================================================================

    @property
    def selected_id(self) -> str | None:
        return self.selection[-1] if self.selection else None

    @selected_id.setter
    def selected_id(self, value: str | None) -> None:
        self.selection = [value] if value else []

    def selected_all(self) -> list[dict]:
        """Everything selected, in stacking order (the main one is self.selected())."""
        chosen = set(self.selection)
        return [e for e in self.page["elements"] if e["id"] in chosen]

    def select_all(self) -> None:
        ids = [e["id"] for e in self.page["elements"] if not e.get("locked")]
        self._set_selection(ids)

    def _set_selection(self, ids: list[str]) -> None:
        if ids != self.selection:
            self._commit_editor()
            self.selection = list(dict.fromkeys(ids))
            self._refresh_style()
            if ids:
                self.show_side("Style")
        self.redraw_overlay()

    def show_side(self, name: str) -> None:
        """Switch the side panel. CTkTabview hides the other tabs 100 ms after a switch, so two
        switches close together could hide both; the current one is put back just after."""
        try:
            if self.side.get() != name:
                self.side.set(name)
                self.after(120, self.side._set_grid_current_tab)
        except Exception:
            pass

    def _with_group(self, element_id: str) -> list[str]:
        el = model.find(self.page, element_id)
        if el is None or not el.get("group"):
            return [element_id]
        return [e["id"] for e in model.group_members(self.page, el["group"]) if e["id"] != element_id] + [element_id]

    def _box_select(self, start, end, add: bool) -> None:
        left, right = sorted((start[0], end[0]))
        top, bottom = sorted((start[1], end[1]))
        ids = []
        for el in self.page["elements"]:
            if el.get("locked"):
                continue
            l, t, r, b = model.bbox(el)
            if l >= left and r <= right and t >= top and b <= bottom:
                ids += [i for i in self._with_group(el["id"]) if i not in ids]
        self._set_selection((self.selection if add else []) + [i for i in ids if not add or i not in self.selection])
        if ids:
            self._say(f"{len(self.selection)} selected — drag to move them together, Ctrl+G groups them.")

    # =====================================================================================
    # groups and aligning
    # =====================================================================================

    def group_selected(self) -> None:
        chosen = self.selected_all()
        if len(chosen) < 2:
            self._say("Select two or more things first (Shift+click, or drag a box around them).")
            return
        self.checkpoint()
        model.make_group(self.design, self.page, chosen)
        self._refresh_style()
        self.redraw()
        self._say("Grouped — they now move together. Ctrl+Shift+G ungroups.")

    def ungroup_selected(self) -> None:
        chosen = [e for e in self.selected_all() if e.get("group")]
        if not chosen:
            return
        self.checkpoint()
        model.ungroup(chosen)
        self._refresh_style()
        self.redraw_overlay()
        self._say("Ungrouped.")

    def align_selected(self, how: str) -> None:
        chosen = [e for e in self.selected_all() if not e.get("locked")]
        if not chosen:
            return
        self.checkpoint()
        if len(chosen) > 1 and len({e.get("group") for e in chosen}) == 1 and chosen[0].get("group") \
                and how not in {"hspace", "vspace"}:
            # One whole group: align it to the page, as one block.
            box = model.union_box(chosen)
            probe = {"x": box[0], "y": box[1], "w": box[2] - box[0], "h": box[3] - box[1], "type": "shape"}
            model.align([probe], how, (self.design["w"], self.design["h"]))
            for el in chosen:
                model.move(el, probe["x"] - box[0], probe["y"] - box[1])
        else:
            model.align(chosen, how, (self.design["w"], self.design["h"]))
        self.redraw()

    def _align_buttons(self, tab) -> None:
        row = self._row(tab)
        for text, how in (("⇤", "left"), ("↔", "center"), ("⇥", "right"), ("⤒", "top"), ("↕", "middle"),
                          ("⤓", "bottom")):
            self._button(row, text, lambda h=how: self.align_selected(h), 38).pack(side="left", padx=1)
        if len(self.selection) > 2:
            row = self._row(tab)
            self._button(row, "Space across", lambda: self.align_selected("hspace"), 116).pack(side="left", padx=2)
            self._button(row, "Space down", lambda: self.align_selected("vspace"), 116).pack(side="left", padx=2)

    def _selection_header(self, tab) -> None:
        chosen = self.selected_all()
        groups = {e.get("group") for e in chosen}
        grouped = len(groups) == 1 and chosen[0].get("group")
        ctk.CTkLabel(tab, text=f"Group of {len(chosen)}" if grouped else f"{len(chosen)} selected",
                     font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(fill="x", pady=(6, 2))
        self._section(tab, "Align" + (" (to the page)" if grouped else ""))
        self._align_buttons(tab)
        row = self._row(tab)
        if any(e.get("group") for e in chosen):
            self._button(row, "Ungroup", self.ungroup_selected, 100).pack(side="left", padx=2)
        if not grouped:
            self._button(row, "Group", self.group_selected, 100, fg_color=self.colors["accent_dim"]).pack(
                side="left", padx=2)
        ctk.CTkLabel(tab, text="Colours and fonts below change every selected thing that has them.",
                     wraplength=250, justify="left", text_color=self.colors["muted"]).pack(fill="x", pady=(6, 0))

    # =====================================================================================
    # rulers and guides
    # =====================================================================================

    def _build_rulers(self, holder) -> None:
        bg, fg = self.colors["panel"], self.colors["muted"]
        self._ruler_fg = fg
        self.ruler_corner = tkinter.Canvas(holder, width=RULER, height=RULER, bg=bg, highlightthickness=0, bd=0)
        self.ruler_top = tkinter.Canvas(holder, height=RULER, bg=bg, highlightthickness=0, bd=0,
                                        cursor="sb_v_double_arrow")
        self.ruler_left = tkinter.Canvas(holder, width=RULER, bg=bg, highlightthickness=0, bd=0,
                                         cursor="sb_h_double_arrow")
        self.ruler_corner.grid(row=0, column=0, sticky="nsew")
        self.ruler_top.grid(row=0, column=1, sticky="ew")
        self.ruler_left.grid(row=1, column=0, sticky="ns")
        for ruler, axis in ((self.ruler_top, "h"), (self.ruler_left, "v")):
            ruler.bind("<ButtonPress-1>", lambda e, a=axis: self._ruler_press(a))
            ruler.bind("<B1-Motion>", lambda e, a=axis: self._ruler_motion(a, e))
            ruler.bind("<ButtonRelease-1>", lambda e: self._ruler_release())
            ruler.bind("<Configure>", lambda e: self._draw_rulers())
        self._rulers_on = True

    def toggle_rulers(self) -> None:
        self._rulers_on = not self._rulers_on
        for widget in (self.ruler_corner, self.ruler_top, self.ruler_left):
            if self._rulers_on:
                widget.grid()
            else:
                widget.grid_remove()
        self.redraw_overlay()
        self._say("Rulers on — drag from a ruler onto the page to add a guide." if self._rulers_on else "Rulers off.")

    def _draw_rulers(self) -> None:
        if not getattr(self, "_rulers_on", False):
            return
        try:
            scale = self._scale
            W, H = self.design["w"], self.design["h"]
            chosen = self.selected_all()
            box = model.union_box(chosen) if chosen else None
            step = nice_step(scale)
            minor = step / 5
            for ruler, horizontal in ((self.ruler_top, True), (self.ruler_left, False)):
                ruler.delete("all")
                length = ruler.winfo_width() if horizontal else ruler.winfo_height()
                start = ((self.canvas.canvasx(0) if horizontal else self.canvas.canvasy(0))
                         - (self._ox if horizontal else self._oy)) / scale
                extent = W if horizontal else H
                a, b = (0 - start) * scale, (extent - start) * scale
                page = (a, 0, b, RULER) if horizontal else (0, a, RULER, b)
                ruler.create_rectangle(*page, fill=self.colors["bg"], outline="")
                if box is not None:
                    lo, hi = (box[0], box[2]) if horizontal else (box[1], box[3])
                    band = ((lo - start) * scale, RULER - 4, (hi - start) * scale, RULER) if horizontal else \
                        (RULER - 4, (lo - start) * scale, RULER, (hi - start) * scale)
                    ruler.create_rectangle(*band, fill=self.colors["accent"], outline="")
                value = math.floor(start / minor) * minor
                end = start + length / scale
                while value <= end:
                    pos = (value - start) * scale
                    major = abs(value / step - round(value / step)) < 1e-6
                    tick = 10 if major else 4
                    if horizontal:
                        ruler.create_line(pos, RULER, pos, RULER - tick, fill=self._ruler_fg)
                        if major:
                            ruler.create_text(pos + 3, 2, text=f"{value:g}", anchor="nw", fill=self._ruler_fg,
                                              font=("Segoe UI", 7))
                    else:
                        ruler.create_line(RULER, pos, RULER - tick, pos, fill=self._ruler_fg)
                        if major:
                            ruler.create_text(2, pos + 3, text=f"{value:g}", anchor="ne", angle=90,
                                              fill=self._ruler_fg, font=("Segoe UI", 7))
                    value += minor
        except (tkinter.TclError, AttributeError, ZeroDivisionError):
            pass

    def _guides_of(self) -> dict:
        guides = self.design.setdefault("guides", {})
        guides.setdefault("v", [])
        guides.setdefault("h", [])
        return guides

    def _ruler_press(self, axis: str) -> None:
        self.checkpoint()
        guides = self._guides_of()
        guides[axis].append(-1.0e6)
        self._guide_drag = (axis, len(guides[axis]) - 1)

    def _ruler_motion(self, axis: str, event) -> None:
        drag = getattr(self, "_guide_drag", None)
        if drag is None:
            return
        x, y = self._to_design(event.x_root - self.canvas.winfo_rootx(), event.y_root - self.canvas.winfo_rooty())
        self._guides_of()[axis][drag[1]] = round(y if axis == "h" else x)
        self.redraw_overlay()

    def _ruler_release(self) -> None:
        drag = getattr(self, "_guide_drag", None)
        self._guide_drag = None
        if drag is not None:
            self._drop_guide(*drag)

    def _drop_guide(self, axis: str, index: int) -> None:
        """A guide dragged off the page is gone."""
        guides = self._guides_of()
        if index < len(guides[axis]):
            limit = self.design["h"] if axis == "h" else self.design["w"]
            if not 0 <= guides[axis][index] <= limit:
                guides[axis].pop(index)
        self.redraw_overlay()

    def _guide_at(self, x: float, y: float) -> tuple[str, int] | None:
        guides = self.design.get("guides") or {}
        reach = 4 / self._scale
        for axis, value in (("v", x), ("h", y)):
            for i, g in enumerate(guides.get(axis) or []):
                if abs(g - value) <= reach:
                    return axis, i
        return None

    def clear_guides(self) -> None:
        if (self.design.get("guides") or {}).get("v") or (self.design.get("guides") or {}).get("h"):
            self.checkpoint()
        self.design["guides"] = {"v": [], "h": []}
        self.redraw_overlay()

    def _draw_guides(self) -> None:
        guides = self.design.get("guides") or {}
        region = getattr(self, "_region", (0, 0, 4000, 4000))
        for x in guides.get("v") or []:
            cx, _ = self._to_canvas(x, 0)
            self.canvas.create_line(cx, 0, cx, region[3], fill="#06b6d4", tags=("overlay", "guide"))
        for y in guides.get("h") or []:
            _, cy = self._to_canvas(0, y)
            self.canvas.create_line(0, cy, region[2], cy, fill="#06b6d4", tags=("overlay", "guide"))

    def _snap_move(self, moving: list[dict]) -> None:
        """Pull what's being dragged so its edges or middle meet the page's edges and middle, a
        guide, or another element's edges and middle — and show the line it meets."""
        if not moving:
            return
        left, top, right, bottom = model.union_box(moving)
        ids = {e["id"] for e in moving}
        W, H = self.design["w"], self.design["h"]
        guides = self.design.get("guides") or {}
        xs, ys = [0.0, W / 2, float(W)] + list(guides.get("v") or []), [0.0, H / 2, float(H)] + list(guides.get("h") or [])
        for el in self.page["elements"]:
            if el["id"] in ids:
                continue
            l, t, r, b = model.bbox(el)
            if r - l >= W * 0.98 and b - t >= H * 0.98:
                continue                                  # a full-page background adds nothing
            xs += [l, (l + r) / 2, r]
            ys += [t, (t + b) / 2, b]
        reach = 7 / self._scale
        shift = [0.0, 0.0]
        for axis, edges, targets in ((0, (left, (left + right) / 2, right), xs), (1, (top, (top + bottom) / 2, bottom), ys)):
            best = min(((abs(t - e), t - e, t) for e in edges for t in targets), default=None)
            if best is not None and best[0] <= reach:
                shift[axis] = best[1]
                if axis == 0:
                    self._guides.append((*self._to_canvas(best[2], 0), *self._to_canvas(best[2], H)))
                else:
                    self._guides.append((*self._to_canvas(0, best[2]), *self._to_canvas(W, best[2])))
        if shift != [0.0, 0.0]:
            for el in moving:
                model.move(el, shift[0], shift[1])

    # =====================================================================================
    # the pen
    # =====================================================================================

    def toggle_pen(self, on: bool | None = None) -> None:
        self._pen_on = (not self._pen_on) if on is None else bool(on)
        try:
            self.pen_btn.configure(text="✏ Stop drawing" if self._pen_on else "✏ Draw",
                                   fg_color=self.colors["accent_dim"] if self._pen_on else "transparent")
        except (AttributeError, tkinter.TclError):
            pass
        self.canvas.configure(cursor="pencil" if self._pen_on else "")
        if self._pen_on:
            self.select(None)
            self.canvas.focus_set()
            self._say("Drawing: drag on the page. Esc (or ✏ again) stops.")
        else:
            self._say("")

    def _pen_colour(self) -> str:
        return getattr(self, "_pen_ink", None) or model.readable_on(self.page.get("bg", "#ffffff"))

    def _set_pen_colour(self, colour: str | None) -> None:
        if colour:
            self._pen_ink = colour
            self.after(10, self._refresh_pen_row)

    def _refresh_pen_row(self) -> None:
        for child in self.pen_row.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.pen_row, text="Pen", width=36, anchor="w").pack(side="left")
        self._color_controls(self.pen_row, self._pen_colour, self._set_pen_colour, allow_none=False)

    def _pen_width(self) -> float:
        return getattr(self, "_pen_size", None) or max(3.0, self.design["h"] * 0.006)

    def _pen_motion(self, drag: dict, x: float, y: float) -> None:
        last = drag["points"][-1]
        if math.hypot((x - last[0]) * self._scale, (y - last[1]) * self._scale) < 2:
            return
        drag["points"].append((x, y))
        width = max(1, int(self._pen_width() * self._scale))
        self.canvas.create_line(*self._to_canvas(*last), *self._to_canvas(x, y), fill=self._pen_colour(),
                                width=width, capstyle="round", joinstyle="round", tags="penpreview")

    def _pen_release(self, drag: dict) -> None:
        self.canvas.delete("penpreview")
        points = drag["points"]
        if len(points) == 1:
            points = points + [(points[0][0] + 0.5, points[0][1] + 0.5)]
        self.checkpoint()
        el = model.path(points, stroke=self._pen_colour(), stroke_w=self._pen_width(), role="drawing")
        model.add(self.design, self.page, el)
        self.redraw()

    def _escape(self) -> None:
        if getattr(self, "_pen_on", False):
            self.toggle_pen(False)
        else:
            self.select(None)

    # =====================================================================================
    # inserting: charts, styled text, emoji
    # =====================================================================================

    def add_chart(self, kind: str = "bar") -> dict:
        W, H = self.design["w"], self.design["h"]
        fill = self._palette()[0]
        el = model.chart(kind, model.SAMPLE_CHART, 0, 0, W * 0.55, H * 0.55, fill=fill,
                         color=model.readable_on(self.page.get("bg", "#ffffff")), font=self._font(False),
                         size=max(12.0, H * 0.024), title="")
        return self._place(el)

    def _chart_menu(self) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        for kind, label in chart_mod.LABELS.items():
            menu.add_command(label=label, command=lambda k=kind: self.add_chart(k))
        self._popup(menu)

    def apply_text_style(self, kind: str) -> None:
        share, bold, heading = TEXT_STYLES[kind]
        chosen = [e for e in self.selected_all() if e["type"] in {"text", "shape"}]
        if not chosen:
            return
        self.checkpoint()
        for el in chosen:
            el["size"] = round(self.design["h"] * share, 1)
            el["bold"] = bold
            el["font"] = self._font(heading)
            if el["type"] == "text" and kind == "title":
                el["role"] = "title"
        self._refresh_style()
        self.redraw()

    def pick_emoji(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Emoji")
        dialog.geometry("520x560")
        dialog.transient(self.winfo_toplevel())
        top = ctk.CTkFrame(dialog, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=8)
        search = ctk.CTkEntry(top, placeholder_text="Search: heart, cat, party, sun…")
        search.pack(side="left", fill="x", expand=True)
        groups = ["Popular"] + list(templates.ICONS) + ["All"]
        group = ctk.CTkOptionMenu(top, values=groups, width=120)
        group.pack(side="left", padx=(6, 0))
        cell, columns = 46, 10
        canvas = tkinter.Canvas(dialog, bg=self.colors["panel"], highlightthickness=0, bd=0)
        bar = ctk.CTkScrollbar(dialog, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y", pady=(0, 10))
        canvas.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        note = ctk.CTkLabel(dialog, text="Click one to put it on the page.", text_color=self.colors["muted"])
        note.pack(pady=(0, 6))
        dialog._photos = []
        shown: list[str] = []

        def items() -> list[str]:
            words = search.get().strip().lower()
            if words:
                return [ch for ch, name in all_emoji() if all(w in name for w in words.split())][:400]
            choice = group.get()
            if choice == "Popular":
                return [g for cat in ("Faces", "People", "Celebrate", "Nature") for g in templates.icon_list(cat)]
            if choice == "All":
                return [ch for ch, _ in all_emoji()][:600]
            return templates.icon_list(choice)

        def fill(_event=None) -> None:
            canvas.delete("all")
            dialog._photos = []
            shown[:] = items()
            for n, glyph in enumerate(shown):
                layer, _ = render.icon_layer(model.icon(glyph, 0, 0, 64, set="color"), 1.0)
                photo = ImageTk.PhotoImage(layer.resize((34, 34)), master=dialog)
                dialog._photos.append(photo)
                canvas.create_image((n % columns) * cell + cell / 2, (n // columns) * cell + cell / 2, image=photo)
            canvas.configure(scrollregion=(0, 0, columns * cell, (len(shown) // columns + 1) * cell))
            note.configure(text=f"{len(shown)} — click one to put it on the page." if shown else "Nothing found.")

        def choose(event) -> None:
            col, row = int(canvas.canvasx(event.x) // cell), int(canvas.canvasy(event.y) // cell)
            n = row * columns + col
            if 0 <= col < columns and 0 <= n < len(shown):
                self.add_icon(shown[n], templates.mono(group.get()) and not search.get().strip())

        canvas.bind("<Button-1>", choose)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        search.bind("<KeyRelease>", fill)
        group.configure(command=lambda _: fill())
        fill()
        dialog.after(120, lambda: (dialog.lift(), search.focus_set()))
        self._emoji_dialog = dialog

    # =====================================================================================
    # words: AI rewrite, find and replace, spell check
    # =====================================================================================

    def rewrite_selected(self, how: str) -> None:
        el = self.selected()
        if el is None or el["type"] not in {"text", "shape"} or not el.get("text", "").strip():
            self._say("Select some text first.")
            return
        text, element_id, brain = el["text"], el["id"], self.app.jarvis.brain

        def done(new, error):
            if error:
                self._say(error)
                return
            target = model.find(self.page, element_id)
            if target is None:
                return
            self.checkpoint()
            target["text"] = new
            self._refresh_style()
            self.redraw()
            self._say("Rewritten. Ctrl+Z puts the old words back.")

        self._work("Rewriting…", lambda: extras.rewrite(brain, text, how), done)

    def _rewrite_menu(self, event=None) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        for how, label in extras.REWRITE_LABELS.items():
            menu.add_command(label=label, command=lambda h=how: self.rewrite_selected(h))
        self._popup(menu, event)

    def open_find(self) -> None:
        dialog = getattr(self, "_find_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            dialog.find_entry.focus_set()
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Find and replace")
        dialog.geometry("420x230")
        dialog.transient(self.winfo_toplevel())
        dialog.find_entry = ctk.CTkEntry(dialog, placeholder_text="Find")
        dialog.find_entry.pack(fill="x", padx=12, pady=(14, 4))
        dialog.replace_entry = ctk.CTkEntry(dialog, placeholder_text="Replace with")
        dialog.replace_entry.pack(fill="x", padx=12, pady=4)
        dialog.case = tkinter.BooleanVar(value=False)
        ctk.CTkCheckBox(dialog, text="Match capitals", variable=dialog.case).pack(anchor="w", padx=12, pady=4)
        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        self._button(row, "Find next", self._find_next, 110).pack(side="left", padx=2)
        self._button(row, "Replace all", self._replace_all, 110, fg_color=self.colors["accent_dim"]).pack(
            side="left", padx=2)
        dialog.result = ctk.CTkLabel(dialog, text="Searches every page, tables and charts too.",
                                     text_color=self.colors["muted"])
        dialog.result.pack(anchor="w", padx=12, pady=4)
        dialog.find_entry.bind("<Return>", lambda e: self._find_next())
        dialog.position = -1
        self._find_dialog = dialog
        dialog.after(120, lambda: (dialog.lift(), dialog.find_entry.focus_set()))

    def find_matches(self, query: str, case: bool = False) -> list[tuple[int, str]]:
        return model.find_text(self.design, query, case)

    def _find_next(self) -> None:
        dialog = self._find_dialog
        matches = self.find_matches(dialog.find_entry.get(), dialog.case.get())
        if not matches:
            dialog.result.configure(text="Not found.")
            return
        dialog.position = (dialog.position + 1) % len(matches)
        page, element_id = matches[dialog.position]
        if page != self.index:
            self.go_to(page)
        self.select(element_id, single=True)
        dialog.result.configure(text=f"{dialog.position + 1} of {len(matches)} · page {page + 1}")

    def replace_all(self, query: str, replacement: str, case: bool = False) -> int:
        if not query:
            return 0
        snap = self._snapshot()
        count = model.replace_text(self.design, query, replacement, case)
        if count:
            self.undo_stack.append(snap)
            self.redo_stack.clear()
            self._changed()
            self._refresh_style()
            self._refresh_pages()
            self._load_notes()
            self.redraw()
        return count

    def _replace_all(self) -> None:
        dialog = self._find_dialog
        count = self.replace_all(dialog.find_entry.get(), dialog.replace_entry.get(), dialog.case.get())
        dialog.result.configure(text=f"Replaced {count}." + (" Ctrl+Z undoes it." if count else ""))

    def spell_check(self) -> None:
        self._commit_editor()
        design, brain = model.clone(self.design), self.app.jarvis.brain

        def job():
            from jarvis import spelling

            try:
                return extras.spelling_issues(design)
            except spelling.SpellError:
                return extras.spelling_issues_ai(brain, design)

        self._work("Checking the spelling…", job, self._show_spelling)

    def _show_spelling(self, issues, error) -> None:
        if error:
            self._say(error)
            return
        if not issues:
            self._say("No spelling mistakes found. ✓")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Spelling — {len(issues)} to look at")
        dialog.geometry("560x480")
        dialog.transient(self.winfo_toplevel())
        listing = ctk.CTkScrollableFrame(dialog, fg_color=self.colors["panel"])
        listing.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        def fix(issue, choice, row) -> None:
            replacement = "" if choice == "(delete it)" else choice
            self.checkpoint()
            if extras.apply_fix(self.design, issue, replacement):
                row.destroy()
                self._refresh_style()
                self.redraw()

        def go(issue) -> None:
            if issue["page"] != self.index:
                self.go_to(issue["page"])
            self.select(issue["id"], single=True)

        for issue in issues:
            row = ctk.CTkFrame(listing, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkButton(row, text=f"p{issue['page'] + 1} · {issue['word']}", width=150, anchor="w",
                          fg_color="transparent", text_color="#f87171", hover_color=self.colors["accent_dim"],
                          command=lambda i=issue: go(i)).pack(side="left")
            options = [s if s else "(delete it)" for s in issue["suggestions"]] or ["—"]
            menu = ctk.CTkOptionMenu(row, values=options, width=180)
            menu.set(options[0])
            menu.pack(side="left", padx=4)
            if options != ["—"]:
                self._button(row, "Fix", lambda i=issue, m=menu, r=row: fix(i, m.get(), r), 56).pack(side="left")
            self._button(row, "Skip", lambda r=row: r.destroy(), 56).pack(side="left", padx=2)

        def fix_all() -> None:
            self.checkpoint()
            done = 0
            for issue in issues:
                if issue["suggestions"]:
                    done += extras.apply_fix(self.design, issue, issue["suggestions"][0])
            dialog.destroy()
            self._refresh_style()
            self.redraw()
            self._say(f"Fixed {done}. Ctrl+Z undoes it.")

        self._button(dialog, "Fix all with the first suggestion", fix_all, 260,
                     fg_color=self.colors["accent_dim"]).pack(pady=8)
        self._spell_dialog = dialog

    # =====================================================================================
    # pictures and charts
    # =====================================================================================

    def remove_background(self, tolerance: int = 28) -> None:
        el = self.selected()
        if el is None or el["type"] != "image" or not el.get("src"):
            self._say("Select a picture first.")
            return
        src, element_id = el["src"], el["id"]

        def done(new_src, error):
            if error:
                self._say(error)
                return
            target = model.find(self.page, element_id)
            if target is not None:
                self.checkpoint()
                target["src"] = new_src
                self.redraw()
                self._say("Background removed. Ctrl+Z puts it back; “More” takes off greyer white.")

        self._work("Taking the white background off…", lambda: extras.remove_white_src(src, tolerance), done)

    def edit_chart_data(self) -> None:
        el = self.selected()
        if el is None or el["type"] != "chart":
            return
        element_id = el["id"]
        rows = [list(r) for r in el["rows"]]
        dialog = ctk.CTkToplevel(self)
        dialog.title("Chart data")
        dialog.geometry("720x480")
        dialog.transient(self.winfo_toplevel())
        bar = ctk.CTkFrame(dialog, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 4))
        grid = ctk.CTkScrollableFrame(dialog, fg_color=self.colors["panel"], orientation="vertical")
        grid.pack(fill="both", expand=True, padx=10, pady=4)
        ctk.CTkLabel(dialog, text="First row: the series' names. First column: the labels. Paste straight "
                                  "from Excel with the button.", text_color=self.colors["muted"]).pack(pady=(0, 8))
        cells: list[list[tkinter.Entry]] = []
        bold = ("Segoe UI", 10, "bold")

        def collect() -> list[list[str]]:
            return [[entry.get() for entry in row] for row in cells]

        def apply(_event=None) -> None:
            target = model.find(self.page, element_id)
            if target is None:
                return
            new = model.clean_value("chart", "rows", collect())
            if new != target["rows"]:
                self._mark_edit(f"{element_id}:rows")
                target["rows"] = new
                self.schedule_render()

        def build(data: list[list[str]]) -> None:
            for child in grid.winfo_children():
                child.destroy()
            cells.clear()
            width = max(len(r) for r in data)
            for r, row in enumerate(data):
                entries = []
                for c in range(width):
                    entry = tkinter.Entry(grid, width=12, font=bold if r == 0 or c == 0 else ("Segoe UI", 10),
                                          relief="solid", bd=1)
                    entry.insert(0, row[c] if c < len(row) else "")
                    entry.grid(row=r, column=c, padx=1, pady=1, sticky="ew")
                    entry.bind("<KeyRelease>", apply)
                    entries.append(entry)
                cells.append(entries)

        def change(rows_by: int = 0, cols_by: int = 0) -> None:
            data = collect()
            width = max(len(r) for r in data)
            if rows_by > 0:
                data.append([""] * width)
            elif rows_by < 0 and len(data) > 2:
                data.pop()
            if cols_by > 0:
                data = [r + ([f"Series {width}"] if i == 0 else [""]) for i, r in enumerate(data)]
            elif cols_by < 0 and width > 2:
                data = [r[:-1] for r in data]
            build(data)
            apply()

        def paste() -> None:
            try:
                text = self.clipboard_get()
            except tkinter.TclError:
                return
            data = [line.split("\t") for line in text.replace("\r", "").split("\n") if line.strip()]
            if data:
                build(data[:40])
                apply()

        def from_file() -> None:
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("Excel or CSV", "*.xlsx *.csv")])
            if not path:
                return
            try:
                data = [r[:8] for r in extras.read_table(Path(path), 40)]
            except Exception as exc:
                self._say(str(exc))
                return
            build(data)
            apply()

        for text, command in (("+ Row", lambda: change(rows_by=1)), ("− Row", lambda: change(rows_by=-1)),
                              ("+ Column", lambda: change(cols_by=1)), ("− Column", lambda: change(cols_by=-1)),
                              ("Paste from Excel", paste), ("From a file…", from_file)):
            self._button(bar, text, command).pack(side="left", padx=2)
        build(rows)
        self._chart_dialog = dialog

    # =====================================================================================
    # bringing things in: Excel, PDF, a sketch
    # =====================================================================================

    def slides_from_excel(self, path: str | None = None, mode: str | None = None) -> None:
        path = path or filedialog.askopenfilename(parent=self, title="An Excel or CSV table", filetypes=[
            ("Excel or CSV", "*.xlsx *.xlsm *.csv"), ("All files", "*.*")])
        if not path:
            return
        if mode is None:
            menu = tkinter.Menu(self, tearoff=0)
            menu.add_command(label="One slide per row", command=lambda: self.slides_from_excel(path, "rows"))
            menu.add_command(label="The table, across slides", command=lambda: self.slides_from_excel(path, "table"))
            self._popup(menu)
            return
        try:
            rows = extras.read_table(Path(path))
            theme = self.theme_menu.get() if self.theme_menu.get() in templates.SLIDE_THEMES else "midnight"
            design = extras.slides_from_table(rows, Path(path).stem, mode, theme)
        except Exception as exc:
            self._say(str(exc))
            return
        self.load(design)
        self.save(quiet=True)
        self._say(f"Made {len(design['pages'])} slides from {Path(path).name}.")

    def import_pdf(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(parent=self, title="A PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return

        def done(design, error):
            if error:
                self._say(error)
                return
            self.load(design)
            self.save(quiet=True)
            self._say(f"{len(design['pages'])} page(s) from {Path(path).name} — locked, so you can draw and "
                      "write on top.")

        self._work("Opening the PDF's pages…", lambda: extras.design_from_pdf(Path(path)), done)

    def sketch_design(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(parent=self, title="A photo of your sketch", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        chosen = self.describe_kind.get()
        fmt = chosen if chosen in model.FORMATS else "auto"
        note = self.describe_box.get("1.0", "end-1c").strip()
        brain = self.app.jarvis.brain

        def done(design, error):
            if error:
                self._say(error)
                self.ai_reply.configure(text=error)
                return
            self.load(design)
            self.save(quiet=True)
            self._say(f"Designed from your sketch: {design['title']}. Everything is editable.")

        self._work("Reading your sketch…", lambda: extras.design_from_sketch(brain, Path(path), fmt, note), done)

    # =====================================================================================
    # slides: transitions and the show
    # =====================================================================================

    @staticmethod
    def _transition_key(label: str) -> str:
        return next((k for k, v in TRANSITION_LABELS.items() if v == label), "none")

    def set_transition(self, kind: str, all_pages: bool = False) -> None:
        kind = kind if kind in model.TRANSITIONS else "none"
        self.checkpoint()
        for page in (self.design["pages"] if all_pages else [self.page]):
            if kind == "none":
                page.pop("transition", None)
            else:
                page["transition"] = kind
        self._say(f"Transition: {TRANSITION_LABELS[kind]}" + (" on every slide." if all_pages else "."))

    def present(self, start: int | None = None, presenter: bool = False, **options):
        from ui.design_show import Slideshow

        self._commit_editor()
        self._show = Slideshow(self, model.clone(self.design), self.index if start is None else start, presenter,
                               **options)
        return self._show

    def open_target(self, part: str) -> None:
        """What a chat reply asks of the page: 'present', 'presenter', 'find', 'spell', 'pen', 'emoji'."""
        actions = {"present": lambda: self.present(0), "presenter": lambda: self.present(0, presenter=True),
                   "find": self.open_find, "spell": self.spell_check, "pen": lambda: self.toggle_pen(True),
                   "emoji": self.pick_emoji}
        action = actions.get(part)
        if action is not None:
            self.after(150, action)

    def _present_menu(self) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="From the start   F5", command=lambda: self.present(0))
        menu.add_command(label="From this slide   Shift+F5", command=lambda: self.present())
        menu.add_command(label="Presenter view (notes and timer)", command=lambda: self.present(0, presenter=True))
        self._popup(menu)
