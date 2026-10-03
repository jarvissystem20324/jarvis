"""The Design page — slides, posters, cards, logos and diagrams, edited by
hand or by asking JARVIS.

Left: the pages. Middle: the canvas — click to select, drag to move, the
square handles resize, the round one rotates, double-click edits text,
right-click for more, Ctrl+wheel zooms, middle-drag pans. Right: Insert,
Style, AI and Page panels. Underneath: speaker notes.

The canvas shows the page as jarvis.design.render draws it, so what you see
is exactly what exports. Edits change the design's JSON and redraw; every
change is undoable. Work that waits on the network (JARVIS designing,
editing, writing notes, making a picture) runs on a worker and comes back
through safe_after, like the rest of the window.
"""

from __future__ import annotations

import json
import math
import threading
import time
import tkinter
from pathlib import Path
from tkinter import colorchooser, filedialog

import customtkinter as ctk
from PIL import Image, ImageTk

from jarvis import kit
from jarvis.design import ai as dai
from jarvis.design import fonts, model, render, templates

HANDLE = 5
MARGIN = 40
HANDLES = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0), "se": (1, 1), "s": (0, 1), "sw": (-1, 1),
           "w": (-1, 0)}
DESCRIBE_KINDS = ["Auto", "slides", "poster", "thumbnail", "logo", "card", "menu", "invitation", "sticker", "sale",
                  "orgchart", "familytree", "timeline", "gantt", "comparison", "kanban", "wireframe", "mindmap"]
SHORTCUTS = [("Delete", "delete the selection"), ("Ctrl+Z / Ctrl+Y", "undo / redo"),
             ("Ctrl+C / V / X", "copy / paste / cut (V also pastes a picture)"), ("Ctrl+D", "duplicate"),
             ("Ctrl+Shift+C / V", "copy / paste style"), ("Arrow keys", "nudge (Shift: further)"),
             ("Ctrl+S", "save"), ("Ctrl+E", "export"), ("Ctrl + / − / 0", "zoom in / out / fit"),
             ("Ctrl+wheel", "zoom at the pointer"), ("Middle-drag", "pan"), ("PgUp / PgDn", "previous / next page"),
             ("T  R  O  L", "add text, box, circle, line"), ("F2 or double-click", "edit text"),
             ("Ctrl+] / Ctrl+[", "bring forward / send backward"), ("Ctrl+L", "lock / unlock"),
             ("Shift while resizing", "keep proportions"), ("Shift while rotating", "15° steps"),
             ("Esc", "deselect")]


def _ui():
    from ui import app

    return app


def _rot(x: float, y: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


class DesignPage(ctk.CTkFrame):
    def __init__(self, master, app):
        colors = _ui().COLORS
        super().__init__(master, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.design: dict = templates.blank("slides")
        self.path: Path | None = None
        self.index = 0
        self.selected_id: str | None = None
        self.zoom = 1.0
        self.undo_stack: list[str] = []
        self.redo_stack: list[str] = []
        self.dirty = False
        self._scale = 0.4
        self._ox = self._oy = MARGIN
        self._photo = None
        self._page_image: Image.Image | None = None
        self._render_job = None
        self._thumb_job = None
        self._autosave_job = None
        self._drag: dict | None = None
        self._guides: list[tuple] = []
        self._style_clip: dict | None = None
        self._element_clip: dict | None = None
        self._eyedropper = None
        self._editor = None
        self._listening = False
        self._edit_mark = ("", 0.0)
        self._thumb_photos: list = []
        self._icon_images: list = []
        self._palette_result: list[str] = []
        self._busy = False
        fonts.warm()
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_toolbar()
        self._build_body()
        self._build_bottom()
        self._load_into_ui()
        self.after(60, self.fit)
        self._autosave_job = self.after(30_000, self._autosave_tick)

    # =====================================================================================
    # layout
    # =====================================================================================

    def _button(self, parent, text, command, width=0, **kw):
        return ctk.CTkButton(parent, text=text, command=command, width=width or max(40, 9 * len(text) + 20),
                             height=kw.pop("height", 30), fg_color=kw.pop("fg_color", "transparent"),
                             hover_color=self.colors["accent_dim"], border_width=kw.pop("border_width", 1),
                             border_color=self.colors["accent_dim"], text_color=self.colors["text"], **kw)

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=self.colors["panel"], corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        self.toolbar = bar
        b = self._button
        b(bar, "＋ New", self._new_menu).pack(side="left", padx=(10, 3), pady=8)
        b(bar, "📂 Designs", self.open_gallery).pack(side="left", padx=3)
        b(bar, "▦ Templates", self.open_templates).pack(side="left", padx=3)
        self.title_entry = ctk.CTkEntry(bar, width=200, height=30)
        self.title_entry.pack(side="left", padx=8)
        self.title_entry.bind("<Return>", lambda e: self._set_title())
        self.title_entry.bind("<FocusOut>", lambda e: self._set_title())
        b(bar, "↶", self.undo, 34).pack(side="left", padx=2)
        b(bar, "↷", self.redo, 34).pack(side="left", padx=2)
        b(bar, "−", lambda: self.set_zoom(self.zoom / 1.25), 30).pack(side="left", padx=(10, 2))
        self.zoom_label = ctk.CTkLabel(bar, text="100%", width=46, text_color=self.colors["muted"])
        self.zoom_label.pack(side="left")
        b(bar, "+", lambda: self.set_zoom(self.zoom * 1.25), 30).pack(side="left", padx=2)
        b(bar, "Fit", self.fit, 40).pack(side="left", padx=2)
        b(bar, "⌨", self.show_shortcuts, 34).pack(side="right", padx=(3, 10))
        self.export_btn = b(bar, "⇩ Export", self._export_menu, fg_color=self.colors["accent_dim"])
        self.export_btn.pack(side="right", padx=3)
        b(bar, "💾 Save", self.save).pack(side="right", padx=3)

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color=self.colors["bg"], corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        # pages
        left = ctk.CTkFrame(body, fg_color=self.colors["panel"], corner_radius=0, width=150)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.pages_frame = ctk.CTkScrollableFrame(left, fg_color=self.colors["panel"], width=128,
                                                  label_text="Pages", label_text_color=self.colors["muted"])
        self.pages_frame.grid(row=0, column=0, sticky="nsew")
        self._button(left, "＋ Page", self.add_page, 120).grid(row=1, column=0, pady=6)
        # canvas
        holder = ctk.CTkFrame(body, fg_color=self.colors["bg"], corner_radius=0)
        holder.grid(row=0, column=1, sticky="nsew")
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        dark = _ui().PALETTE.get("appearance") == "dark"
        self.canvas = tkinter.Canvas(holder, bg="#262b36" if dark else "#d5dbe5", highlightthickness=0, bd=0,
                                     xscrollincrement=1, yscrollincrement=1, takefocus=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys = ctk.CTkScrollbar(holder, orientation="vertical", command=self.canvas.yview)
        ys.grid(row=0, column=1, sticky="ns")
        xs = ctk.CTkScrollbar(holder, orientation="horizontal", command=self.canvas.xview)
        xs.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self._bind_canvas()
        # side panel
        self.side = ctk.CTkTabview(body, width=300, fg_color=self.colors["panel"],
                                   segmented_button_selected_color=self.colors["accent_dim"])
        self.side.grid(row=0, column=2, sticky="ns", padx=(0, 6), pady=(0, 4))
        for name in ("Insert", "Style", "AI", "Page"):
            self.side.add(name)
        self.insert_tab = self._scroller(self.side.tab("Insert"))
        self.style_tab = self._scroller(self.side.tab("Style"))
        self.ai_tab = self._scroller(self.side.tab("AI"))
        self.page_tab = self._scroller(self.side.tab("Page"))
        self._build_insert()
        self._build_ai()
        self._build_page_tab()

    def _scroller(self, parent):
        frame = ctk.CTkScrollableFrame(parent, fg_color="transparent", width=270)
        frame.pack(fill="both", expand=True)
        return frame

    def _build_bottom(self) -> None:
        bottom = ctk.CTkFrame(self, fg_color=self.colors["panel"], corner_radius=0)
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bottom, text="Notes", text_color=self.colors["muted"], width=50).grid(row=0, column=0, padx=(10, 4))
        self.notes_box = ctk.CTkTextbox(bottom, height=54, wrap="word")
        self.notes_box.grid(row=0, column=1, sticky="ew", pady=6)
        self.notes_box.bind("<KeyRelease>", lambda e: self._notes_changed())
        self.status = ctk.CTkLabel(bottom, text="", text_color=self.colors["muted"], width=260, anchor="e",
                                   wraplength=260, justify="right")
        self.status.grid(row=0, column=2, padx=10)

    # --- small widget helpers --------------------------------------------------------------

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text.upper(), font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=self.colors["muted"], anchor="w").pack(fill="x", pady=(12, 3))

    def _row(self, parent) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        return row

    def _say(self, text: str) -> None:
        try:
            self.status.configure(text=text)
        except Exception:
            pass

    # =====================================================================================
    # the Insert panel
    # =====================================================================================

    def _build_insert(self) -> None:
        tab = self.insert_tab
        self._section(tab, "Text")
        row = self._row(tab)
        for label, kind in (("Title", "title"), ("Heading", "heading"), ("Body", "body")):
            self._button(row, label, lambda k=kind: self.add_text(k), 82).pack(side="left", padx=2)
        self._section(tab, "Shapes")
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x")
        for i, (kind, label) in enumerate(templates.SHAPE_LABELS.items()):
            self._button(grid, label, lambda k=kind: self.add_shape(k), 124, height=28).grid(
                row=i // 2, column=i % 2, padx=2, pady=2, sticky="w")
        row = self._row(tab)
        self._button(row, "╱ Line", lambda: self.add_line(False), 82).pack(side="left", padx=2)
        self._button(row, "➝ Arrow", lambda: self.add_line(True), 82).pack(side="left", padx=2)
        self._button(row, "▦ Table", self.add_table, 82).pack(side="left", padx=2)
        self._section(tab, "Pictures")
        self._button(tab, "🖼  Picture from a file…", self.add_image_file, 250).pack(anchor="w", pady=2)
        self.ai_image_entry = ctk.CTkEntry(tab, placeholder_text="Describe a picture for JARVIS to make")
        self.ai_image_entry.pack(fill="x", pady=2)
        self.ai_image_entry.bind("<Return>", lambda e: self.add_ai_image())
        self._button(tab, "✨ Make the picture", self.add_ai_image, 250).pack(anchor="w", pady=2)
        self._section(tab, "Icons")
        self.icon_category = ctk.CTkOptionMenu(tab, values=list(templates.ICONS), command=lambda _: self._show_icons())
        self.icon_category.pack(fill="x", pady=2)
        self.icon_grid = ctk.CTkFrame(tab, fg_color="transparent")
        self.icon_grid.pack(fill="x")
        self._show_icons()

    def _icon_image(self, glyph: str, mono: bool) -> ctk.CTkImage:
        el = model.icon(glyph, 0, 0, 64, set="mono" if mono else "color", color=self.colors["text"])
        layer, _ = render.icon_layer(el, 1.0)
        return ctk.CTkImage(layer, size=(26, 26))

    def _show_icons(self) -> None:
        for child in self.icon_grid.winfo_children():
            child.destroy()
        category = self.icon_category.get()
        mono = templates.mono(category)
        self._icon_images = []
        for i, glyph in enumerate(templates.icon_list(category)):
            image = self._icon_image(glyph, mono)
            self._icon_images.append(image)
            ctk.CTkButton(self.icon_grid, text="", image=image, width=38, height=38, fg_color="transparent",
                          hover_color=self.colors["accent_dim"],
                          command=lambda g=glyph, m=mono: self.add_icon(g, m)).grid(row=i // 6, column=i % 6, padx=1,
                                                                                    pady=1)

    # =====================================================================================
    # the AI panel
    # =====================================================================================

    def _build_ai(self) -> None:
        tab = self.ai_tab
        self._section(tab, "Ask JARVIS to change it")
        self.ask_box = ctk.CTkTextbox(tab, height=56, wrap="word")
        self.ask_box.pack(fill="x", pady=2)
        self.ask_box.bind("<Control-Return>", lambda e: (self.ask_change(), "break")[1])
        row = self._row(tab)
        self._button(row, "Change it", self.ask_change, 120, fg_color=self.colors["accent_dim"]).pack(side="left", padx=2)
        self.mic_btn = self._button(row, "◉ Say it", self.toggle_voice, 120)
        self.mic_btn.pack(side="left", padx=2)
        self.ai_reply = ctk.CTkLabel(tab, text="e.g. “make the title bigger and dark blue”, “add a subtitle”",
                                     wraplength=260, justify="left", anchor="w", text_color=self.colors["muted"])
        self.ai_reply.pack(fill="x", pady=(2, 4))

        self._section(tab, "Describe it — JARVIS designs it")
        self.describe_box = ctk.CTkTextbox(tab, height=70, wrap="word")
        self.describe_box.pack(fill="x", pady=2)
        row = self._row(tab)
        self.describe_kind = ctk.CTkOptionMenu(row, values=DESCRIBE_KINDS, width=120)
        self.describe_kind.pack(side="left", padx=2)
        self._button(row, "✨ Design it", self.describe_design, 120, fg_color=self.colors["accent_dim"]).pack(
            side="left", padx=2)

        self._section(tab, "Polish")
        row = self._row(tab)
        self._button(row, "✨ Look better", lambda: self.make_better(False), 120).pack(side="left", padx=2)
        self._button(row, "All pages", lambda: self.make_better(True), 110).pack(side="left", padx=2)
        self._button(tab, "🧐 Critique this page", self.critique, 250).pack(anchor="w", pady=2)

        self._section(tab, "Headline ideas")
        self.headline_entry = ctk.CTkEntry(tab, placeholder_text="What is it about?")
        self.headline_entry.pack(fill="x", pady=2)
        self.headline_entry.bind("<Return>", lambda e: self.headline_ideas())
        self._button(tab, "💡 Write headlines", self.headline_ideas, 250).pack(anchor="w", pady=2)
        self.headline_box = ctk.CTkFrame(tab, fg_color="transparent")
        self.headline_box.pack(fill="x")

        self._section(tab, "Colour palette")
        self.mood_entry = ctk.CTkEntry(tab, placeholder_text="A mood: calm ocean, luxury, retro…")
        self.mood_entry.pack(fill="x", pady=2)
        self.mood_entry.bind("<Return>", lambda e: self.palette_mood())
        row = self._row(tab)
        self._button(row, "From mood", self.palette_mood, 120).pack(side="left", padx=2)
        self._button(row, "From photo…", self.palette_photo, 120).pack(side="left", padx=2)
        self.palette_box = ctk.CTkFrame(tab, fg_color="transparent")
        self.palette_box.pack(fill="x")

        self._section(tab, "Font pairs")
        self.font_mood = ctk.CTkEntry(tab, placeholder_text="A vibe: elegant, techy, kids…")
        self.font_mood.pack(fill="x", pady=2)
        self.font_mood.bind("<Return>", lambda e: self.font_tips())
        self._button(tab, "🔤 Suggest fonts", self.font_tips, 250).pack(anchor="w", pady=2)
        self.font_box = ctk.CTkFrame(tab, fg_color="transparent")
        self.font_box.pack(fill="x")

        self._section(tab, "Resize to every format")
        row = self._row(tab)
        self.resize_menu = ctk.CTkOptionMenu(row, values=[k for k in model.FORMATS], width=130)
        self.resize_menu.set("instagram")
        self.resize_menu.pack(side="left", padx=2)
        self._button(row, "Make a copy", self.resize_copy, 110).pack(side="left", padx=2)
        self._button(tab, "📐 Every social size", self.resize_all, 250).pack(anchor="w", pady=2)

        self._section(tab, "Brand kit and templates")
        row = self._row(tab)
        self._button(row, "Apply brand", self.apply_brand, 120).pack(side="left", padx=2)
        self._button(row, "Edit brand…", self.edit_brand, 120).pack(side="left", padx=2)
        row = self._row(tab)
        self._button(row, "Templates…", self.open_templates, 120).pack(side="left", padx=2)
        self._button(row, "Save as template", self.save_template, 120).pack(side="left", padx=2)

    # =====================================================================================
    # the Page panel
    # =====================================================================================

    def _build_page_tab(self) -> None:
        tab = self.page_tab
        self.page_info = ctk.CTkLabel(tab, text="", text_color=self.colors["muted"], anchor="w", justify="left")
        self.page_info.pack(fill="x", pady=(4, 2))
        self._section(tab, "Background")
        self.bg_row = self._row(tab)
        self._section(tab, "Pages")
        row = self._row(tab)
        self._button(row, "Duplicate", lambda: self.duplicate_page(self.index), 82).pack(side="left", padx=2)
        self._button(row, "Delete", lambda: self.delete_page(self.index), 70).pack(side="left", padx=2)
        self._button(row, "▲", lambda: self.move_page(self.index, -1), 34).pack(side="left", padx=2)
        self._button(row, "▼", lambda: self.move_page(self.index, 1), 34).pack(side="left", padx=2)
        self._section(tab, "Slide theme")
        row = self._row(tab)
        self.theme_menu = ctk.CTkOptionMenu(row, values=list(templates.SLIDE_THEMES), width=130)
        self.theme_menu.pack(side="left", padx=2)
        self._button(row, "Apply", self.apply_theme, 80).pack(side="left", padx=2)
        self._section(tab, "Speaker notes")
        row = self._row(tab)
        self._button(row, "✍ This slide", lambda: self.write_notes(False), 120).pack(side="left", padx=2)
        self._button(row, "All slides", lambda: self.write_notes(True), 110).pack(side="left", padx=2)
        self._section(tab, "AI picture for this slide")
        self._button(tab, "✨ Picture from the slide's title", self.slide_picture, 250).pack(anchor="w", pady=2)
        self._section(tab, "Deck from a YouTube video")
        self.yt_entry = ctk.CTkEntry(tab, placeholder_text="https://youtube.com/watch?v=…")
        self.yt_entry.pack(fill="x", pady=2)
        row = self._row(tab)
        self.yt_count = ctk.CTkOptionMenu(row, values=["6", "8", "10", "12", "15"], width=70)
        self.yt_count.set("8")
        self.yt_count.pack(side="left", padx=2)
        self._button(row, "🎬 Make the deck", self.deck_from_youtube, 150).pack(side="left", padx=2)
        self._section(tab, "Quiz slides for class")
        self.quiz_entry = ctk.CTkEntry(tab, placeholder_text="Topic: the water cycle")
        self.quiz_entry.pack(fill="x", pady=2)
        row = self._row(tab)
        self.quiz_count = ctk.CTkOptionMenu(row, values=["4", "6", "8", "10"], width=70)
        self.quiz_count.set("6")
        self.quiz_count.pack(side="left", padx=2)
        self._button(row, "❓ Make the quiz", self.quiz_deck, 150).pack(side="left", padx=2)
        self._section(tab, "PowerPoint")
        row = self._row(tab)
        self._button(row, "Open a .pptx…", self.import_pptx, 120).pack(side="left", padx=2)
        self._button(row, "Open in PowerPoint", lambda: self.export("open"), 130).pack(side="left", padx=2)

    def _refresh_page_tab(self) -> None:
        W, H = self.design["w"], self.design["h"]
        self.page_info.configure(text=f"{model.FORMATS.get(self.design['format'], ('Custom',))[0]} · {W}×{H}px\n"
                                      f"Page {self.index + 1} of {len(self.design['pages'])}")
        for child in self.bg_row.winfo_children():
            child.destroy()
        page = self.page
        self._color_controls(self.bg_row, lambda: page.get("bg"), self._set_bg, allow_none=False)
        if self.design.get("theme"):
            self.theme_menu.set(self.design["theme"])

    # =====================================================================================
    # state
    # =====================================================================================

    @property
    def page(self) -> dict:
        return self.design["pages"][self.index]

    def selected(self) -> dict | None:
        return model.find(self.page, self.selected_id) if self.selected_id else None

    def _snapshot(self) -> str:
        return json.dumps({"design": self.design, "index": self.index, "selected": self.selected_id})

    def checkpoint(self) -> None:
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-80]
        self.redo_stack.clear()
        self._changed()

    def _changed(self) -> None:
        self.dirty = True
        self._schedule_thumb()

    def _restore(self, snap: str) -> None:
        data = json.loads(snap)
        self.design = data["design"]
        self.index = min(data["index"], len(self.design["pages"]) - 1)
        self.selected_id = data["selected"]
        self.dirty = True
        self._load_into_ui(keep_view=True)

    def undo(self) -> None:
        if not self.undo_stack:
            self._say("Nothing to undo.")
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        self._say("Undone.")

    def redo(self) -> None:
        if not self.redo_stack:
            self._say("Nothing to redo.")
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        self._say("Redone.")

    def _mark_edit(self, key: str) -> None:
        """One undo step per run of edits to the same property, not one per slider tick."""
        last_key, when = self._edit_mark
        now = time.monotonic()
        if key != last_key or now - when > 1.5:
            self.checkpoint()
        self._edit_mark = (key, now)

    def _load_into_ui(self, keep_view: bool = False) -> None:
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, self.design.get("title", ""))
        self._refresh_pages()
        self._refresh_style()
        self._refresh_page_tab()
        self._load_notes()
        if keep_view:
            self.redraw()
        else:
            self.fit()

    # --- opening, new, saving ---------------------------------------------------------------

    def load(self, design: dict, path: Path | None = None) -> None:
        self._autosave()
        self.design = model.normalize(design)
        self.path = Path(path) if path else None
        self.index = 0
        self.selected_id = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = path is None
        self.zoom = 1.0
        self._load_into_ui()
        self._say(f"Opened {self.design['title']}.")

    def open_path(self, path: Path) -> None:
        try:
            self.load(model.load(path), path)
        except model.DesignError as exc:
            self._say(str(exc))

    def new_design(self, fmt: str) -> None:
        self.load(templates.blank(fmt))

    def _new_menu(self) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        for key, (label, w, h) in model.FORMATS.items():
            menu.add_command(label=f"{label}   {w}×{h}", command=lambda k=key: self.new_design(k))
        self._popup(menu)

    def _popup(self, menu: tkinter.Menu, event=None) -> None:
        x = event.x_root if event is not None else self.winfo_pointerx()
        y = event.y_root if event is not None else self.winfo_pointery()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _set_title(self) -> None:
        title = self.title_entry.get().strip()
        if title and title != self.design.get("title"):
            self.checkpoint()
            self.design["title"] = title[:120]

    def save(self, quiet: bool = False) -> Path:
        self._commit_editor()
        self._set_title()
        self.path = model.save(self.design, self.path)
        self.dirty = False
        if not quiet:
            self._say(f"Saved · {self.path.name}")
        return self.path

    def _autosave(self) -> None:
        if self.dirty and any(p["elements"] for p in self.design["pages"]):
            try:
                self.save(quiet=True)
            except Exception:
                pass

    def _autosave_tick(self) -> None:
        self._autosave()
        try:
            self._autosave_job = self.after(30_000, self._autosave_tick)
        except tkinter.TclError:
            pass

    def close(self) -> None:
        self._autosave()

    # =====================================================================================
    # pages
    # =====================================================================================

    def _refresh_pages(self) -> None:
        for child in self.pages_frame.winfo_children():
            child.destroy()
        self._thumb_photos = []
        self._thumb_labels = []
        for i in range(len(self.design["pages"])):
            cell = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
            cell.pack(pady=3)
            ctk.CTkLabel(cell, text=str(i + 1), width=14, text_color=self.colors["muted"]).pack(side="left")
            label = tkinter.Label(cell, bd=0, highlightthickness=2, cursor="hand2",
                                  highlightbackground=self.colors["accent"] if i == self.index else self.colors["panel"])
            label.pack(side="left")
            self._thumb_labels.append(label)
            self._paint_thumb(i)
            label.bind("<ButtonPress-1>", lambda e, n=i: self._thumb_press(n))
            label.bind("<ButtonRelease-1>", lambda e, n=i: self._thumb_release(e, n))
            label.bind("<Button-3>", lambda e, n=i: self._page_menu(e, n))

    def _paint_thumb(self, i: int) -> None:
        if i >= len(getattr(self, "_thumb_labels", [])):
            return
        scale = 112 / max(self.design["w"], self.design["h"])
        photo = ImageTk.PhotoImage(render.render_page(self.design, i, scale), master=self)
        while len(self._thumb_photos) <= i:
            self._thumb_photos.append(None)
        self._thumb_photos[i] = photo
        try:
            self._thumb_labels[i].configure(image=photo)
        except tkinter.TclError:
            pass

    def _schedule_thumb(self) -> None:
        if self._thumb_job is not None:
            try:
                self.after_cancel(self._thumb_job)
            except Exception:
                pass
        self._thumb_job = self.after(400, lambda: self._paint_thumb(self.index))

    def _thumb_press(self, i: int) -> None:
        self._page_drag = i

    def _thumb_release(self, event, i: int) -> None:
        source = getattr(self, "_page_drag", None)
        self._page_drag = None
        target = None
        widget = self.winfo_containing(event.x_root, event.y_root)
        for n, label in enumerate(self._thumb_labels):
            if widget is label:
                target = n
        if source is not None and target is not None and target != source:
            self.checkpoint()
            self.index = model.move_page(self.design, source, target)
            self.selected_id = None
            self._load_into_ui(keep_view=True)
            self._say(f"Moved page {source + 1} to {target + 1}.")
        else:
            self.go_to(i)

    def _page_menu(self, event, i: int) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Duplicate", command=lambda: self.duplicate_page(i))
        menu.add_command(label="Delete", command=lambda: self.delete_page(i))
        menu.add_command(label="Move up", command=lambda: self.move_page(i, -1))
        menu.add_command(label="Move down", command=lambda: self.move_page(i, 1))
        self._popup(menu, event)

    def go_to(self, i: int) -> None:
        self._commit_editor()
        if not (0 <= i < len(self.design["pages"])):
            return
        self.index = i
        self.selected_id = None
        for n, label in enumerate(getattr(self, "_thumb_labels", [])):
            try:
                label.configure(highlightbackground=self.colors["accent"] if n == i else self.colors["panel"])
            except tkinter.TclError:
                pass
        self._load_notes()
        self._refresh_style()
        self._refresh_page_tab()
        self.redraw()

    def add_page(self) -> None:
        self.checkpoint()
        page = model.new_page(self.page.get("bg", "#ffffff"))
        if self.design.get("kind") == "slides":
            page["layout"] = "content"
            theme = templates.SLIDE_THEMES.get(self.design.get("theme") or "")
            if theme:
                templates.decorate(self.design, page, theme)
                self.design["pages"].insert(self.index + 1, page)
                model.add(self.design, page, model.text("New slide", templates._content_x(theme), 64,
                                                         self.design["w"] - 300, 150, role="title", size=68,
                                                         bold=True, autofit=True, valign="bottom"))
                templates.style_text(page, theme)
                self.index += 1
                self._load_into_ui(keep_view=True)
                return
        self.design["pages"].insert(self.index + 1, page)
        self.index += 1
        self._load_into_ui(keep_view=True)

    def duplicate_page(self, i: int) -> None:
        self.checkpoint()
        self.index = model.duplicate_page(self.design, i)
        self._load_into_ui(keep_view=True)

    def delete_page(self, i: int) -> None:
        self.checkpoint()
        self.index = model.delete_page(self.design, i)
        self.selected_id = None
        self._load_into_ui(keep_view=True)

    def move_page(self, i: int, step: int) -> None:
        target = i + step
        if not (0 <= target < len(self.design["pages"])):
            return
        self.checkpoint()
        self.index = model.move_page(self.design, i, target)
        self._load_into_ui(keep_view=True)

    def _load_notes(self) -> None:
        self.notes_box.delete("1.0", "end")
        self.notes_box.insert("1.0", self.page.get("notes", ""))

    def _notes_changed(self) -> None:
        text = self.notes_box.get("1.0", "end-1c")
        if text != self.page.get("notes", ""):
            self._mark_edit("notes")
            self.page["notes"] = text

    # =====================================================================================
    # the canvas: drawing
    # =====================================================================================

    def fit(self) -> None:
        self.zoom = 1.0
        self.redraw()
        try:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        except tkinter.TclError:
            pass

    def _fit_scale(self) -> float:
        cw = max(200, self.canvas.winfo_width())
        ch = max(200, self.canvas.winfo_height())
        return max(0.05, min((cw - 2 * MARGIN) / self.design["w"], (ch - 2 * MARGIN) / self.design["h"]))

    def set_zoom(self, zoom: float, anchor: tuple[int, int] | None = None) -> None:
        fit = self._fit_scale()
        # Never more than about 8 megapixels on screen; a 4x zoom of an A4 page would be 60.
        limit = math.sqrt(8_000_000 / (self.design["w"] * self.design["h"])) / fit
        zoom = max(0.2, min(zoom, 8.0, limit))
        if anchor is None:
            self.zoom = zoom
            self.redraw()
            return
        dx, dy = self._to_design(*anchor)
        self.zoom = zoom
        self.redraw()
        cx, cy = self._to_canvas(dx, dy)
        region = self._region
        if region[2] > 0 and region[3] > 0:
            self.canvas.xview_moveto(max(0.0, (cx - anchor[0]) / region[2]))
            self.canvas.yview_moveto(max(0.0, (cy - anchor[1]) / region[3]))
        self.redraw_overlay()

    def schedule_render(self) -> None:
        if self._render_job is None:
            self._render_job = self.after(12, self._render_now)

    def _render_now(self) -> None:
        self._render_job = None
        self.redraw()

    def redraw(self) -> None:
        try:
            cw, ch = max(200, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        except tkinter.TclError:
            return
        self._scale = self._fit_scale() * self.zoom
        pw, ph = self.design["w"] * self._scale, self.design["h"] * self._scale
        self._ox = max(MARGIN, (cw - pw) / 2)
        self._oy = max(MARGIN, (ch - ph) / 2)
        image = render.render_page(self.design, self.index, self._scale)
        self._page_image = image
        self._photo = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("page")
        self.canvas.create_rectangle(self._ox + 4, self._oy + 4, self._ox + pw + 4, self._oy + ph + 4,
                                     fill="#000000", outline="", stipple="gray50", tags="page")
        self.canvas.create_image(self._ox, self._oy, image=self._photo, anchor="nw", tags=("page", "pageimage"))
        self.canvas.tag_lower("page")
        self._region = (0, 0, max(cw, pw + 2 * self._ox), max(ch, ph + 2 * self._oy))
        self.canvas.configure(scrollregion=self._region)
        try:
            self.zoom_label.configure(text=f"{round(self.zoom * 100)}%")
        except tkinter.TclError:
            pass
        self.redraw_overlay()

    def _to_design(self, ex: float, ey: float) -> tuple[float, float]:
        return ((self.canvas.canvasx(ex) - self._ox) / self._scale, (self.canvas.canvasy(ey) - self._oy) / self._scale)

    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self._ox + x * self._scale, self._oy + y * self._scale

    def _corner(self, el: dict, lx: float, ly: float) -> tuple[float, float]:
        """A point in the element's own frame (lx, ly from its centre) on the canvas."""
        cx, cy = model.center(el)
        rx, ry = _rot(lx, ly, el.get("rot", 0))
        return self._to_canvas(cx + rx, cy + ry)

    def redraw_overlay(self) -> None:
        self.canvas.delete("overlay")
        accent = self.colors["accent"]
        for guide in self._guides:
            self.canvas.create_line(*guide, fill="#ec4899", dash=(4, 3), tags="overlay")
        el = self.selected()
        if el is None:
            return
        if el["type"] == "line":
            for name, (x, y) in (("p1", (el["x"], el["y"])), ("p2", (el["x"] + el["w"], el["y"] + el["h"]))):
                cx, cy = self._to_canvas(x, y)
                self.canvas.create_oval(cx - HANDLE - 1, cy - HANDLE - 1, cx + HANDLE + 1, cy + HANDLE + 1,
                                        fill="#ffffff", outline=accent, width=2, tags=("overlay", f"handle:{name}"))
            return
        w, h = abs(el["w"]), abs(el["h"])
        corners = [self._corner(el, sx * w / 2, sy * h / 2) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        flat = [v for point in corners for v in point]
        self.canvas.create_polygon(*flat, outline=accent, fill="", dash=(5, 3), width=1.5, tags="overlay")
        if el.get("locked"):
            x, y = corners[1]
            self.canvas.create_text(x + 10, y - 10, text="🔒", fill=accent, tags="overlay")
            return
        for name, (hx, hy) in HANDLES.items():
            x, y = self._corner(el, hx * w / 2, hy * h / 2)
            self.canvas.create_rectangle(x - HANDLE, y - HANDLE, x + HANDLE, y + HANDLE, fill="#ffffff",
                                         outline=accent, width=1.5, tags=("overlay", f"handle:{name}"))
        top = self._corner(el, 0, -h / 2)
        knob = self._corner(el, 0, -h / 2 - 28 / self._scale)
        self.canvas.create_line(*top, *knob, fill=accent, tags="overlay")
        self.canvas.create_oval(knob[0] - 6, knob[1] - 6, knob[0] + 6, knob[1] + 6, fill=accent, outline="#ffffff",
                                width=1.5, tags=("overlay", "handle:rotate"))

    # =====================================================================================
    # the canvas: mouse and keys
    # =====================================================================================

    def _bind_canvas(self) -> None:
        c = self.canvas
        c.bind("<Configure>", lambda e: self.schedule_render())
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<Button-3>", self._context)
        c.bind("<Motion>", self._hover)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<ButtonPress-2>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B2-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        keys = {
            "<Delete>": lambda e: self.delete_selected(), "<BackSpace>": lambda e: self.delete_selected(),
            "<Control-z>": lambda e: self.undo(), "<Control-y>": lambda e: self.redo(),
            "<Control-Z>": lambda e: self.redo(), "<Control-c>": lambda e: self.copy_element(),
            "<Control-v>": lambda e: self.paste_element(), "<Control-x>": lambda e: self.cut_element(),
            "<Control-d>": lambda e: self.duplicate_selected(), "<Control-C>": lambda e: self.copy_style(),
            "<Control-V>": lambda e: self.paste_style(), "<Control-s>": lambda e: self.save(),
            "<Control-e>": lambda e: self._export_menu(), "<Control-equal>": lambda e: self.set_zoom(self.zoom * 1.25),
            "<Control-plus>": lambda e: self.set_zoom(self.zoom * 1.25),
            "<Control-minus>": lambda e: self.set_zoom(self.zoom / 1.25), "<Control-Key-0>": lambda e: self.fit(),
            "<Prior>": lambda e: self.go_to(self.index - 1), "<Next>": lambda e: self.go_to(self.index + 1),
            "<Escape>": lambda e: self.select(None), "<F2>": lambda e: self.edit_text(),
            "<Control-bracketright>": lambda e: self.arrange("forward"),
            "<Control-bracketleft>": lambda e: self.arrange("backward"), "<Control-l>": lambda e: self.toggle_lock(),
            "<Key-t>": lambda e: self.add_text("body"), "<Key-r>": lambda e: self.add_shape("rect"),
            "<Key-o>": lambda e: self.add_shape("ellipse"), "<Key-l>": lambda e: self.add_line(False),
        }
        for sequence, handler in keys.items():
            c.bind(sequence, lambda e, h=handler: (h(e), "break")[1])
        for key, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.items():
            c.bind(f"<{key}>", lambda e, d=(dx, dy): (self.nudge(*d, 2), "break")[1])
            c.bind(f"<Shift-{key}>", lambda e, d=(dx, dy): (self.nudge(*d, 20), "break")[1])

    def _handle_at(self, event) -> str | None:
        items = self.canvas.find_overlapping(event.x - 1 + self.canvas.canvasx(0), event.y - 1 + self.canvas.canvasy(0),
                                             event.x + 1 + self.canvas.canvasx(0), event.y + 1 + self.canvas.canvasy(0))
        for item in reversed(items):
            for tag in self.canvas.gettags(item):
                if tag.startswith("handle:"):
                    return tag[7:]
        return None

    def _press(self, event) -> None:
        self.canvas.focus_set()
        self._commit_editor()
        x, y = self._to_design(event.x, event.y)
        if self._eyedropper is not None:
            self._sample(event)
            return
        handle = self._handle_at(event)
        el = self.selected()
        if handle and el is not None and not el.get("locked"):
            mode = "rotate" if handle == "rotate" else ("point" if handle in {"p1", "p2"} else "resize")
            self._drag = {"mode": mode, "handle": handle, "start": (x, y), "orig": model.clone(el),
                          "snap": self._snapshot(), "moved": False}
            return
        hit = model.hit(self.page, x, y, 6 / self._scale, include_locked=True)
        if hit is not None and hit.get("locked") and hit["id"] != self.selected_id:
            # A locked element is selected (to unlock it) but never dragged.
            unlocked = model.hit(self.page, x, y, 6 / self._scale)
            hit = unlocked or hit
        self.select(hit["id"] if hit else None)
        if hit is not None and not hit.get("locked"):
            self._drag = {"mode": "move", "start": (x, y), "orig": model.clone(hit), "snap": self._snapshot(),
                          "moved": False}
        else:
            self._drag = None

    def _motion(self, event) -> None:
        drag = self._drag
        el = self.selected()
        if drag is None or el is None:
            return
        x, y = self._to_design(event.x, event.y)
        sx, sy = drag["start"]
        if not drag["moved"]:
            if math.hypot((x - sx) * self._scale, (y - sy) * self._scale) < 2:
                return
            self.undo_stack.append(drag["snap"])
            self.redo_stack.clear()
            drag["moved"] = True
        orig = drag["orig"]
        shift = bool(event.state & 0x1)
        self._guides = []
        if drag["mode"] == "move":
            el["x"], el["y"] = orig["x"] + x - sx, orig["y"] + y - sy
            self._snap(el)
        elif drag["mode"] == "point":
            if drag["handle"] == "p1":
                end = (orig["x"] + orig["w"], orig["y"] + orig["h"])
                el["x"], el["y"] = x, y
                el["w"], el["h"] = end[0] - x, end[1] - y
            else:
                el["w"], el["h"] = x - orig["x"], y - orig["y"]
            if shift:      # straight: horizontal, vertical or 45°
                angle = round(math.degrees(math.atan2(el["h"], el["w"])) / 45) * 45
                length = math.hypot(el["w"], el["h"])
                el["w"], el["h"] = length * math.cos(math.radians(angle)), length * math.sin(math.radians(angle))
        elif drag["mode"] == "rotate":
            cx, cy = model.center(orig)
            angle = math.degrees(math.atan2(y - cy, x - cx)) + 90
            if shift:
                angle = round(angle / 15) * 15
            el["rot"] = angle % 360
        else:
            self._resize(el, orig, drag["handle"], x - sx, y - sy, shift)
        self._changed()
        self.schedule_render()

    def _resize(self, el: dict, orig: dict, handle: str, dx: float, dy: float, keep: bool) -> None:
        hx, hy = HANDLES[handle]
        rot = orig.get("rot", 0)
        ldx, ldy = _rot(dx, dy, -rot)
        w0, h0 = orig["w"], orig["h"]
        w = max(8.0, w0 + hx * ldx) if hx else w0
        h = max(8.0, h0 + hy * ldy) if hy else h0
        if (keep or el["type"] == "icon") and hx and hy:
            factor = max(w / w0, h / h0)
            w, h = w0 * factor, h0 * factor
        cx0, cy0 = model.center(orig)
        ax, ay = _rot(-hx * w0 / 2, -hy * h0 / 2, rot)
        anchor = (cx0 + ax, cy0 + ay)
        ox, oy = _rot(hx * w / 2, hy * h / 2, rot)
        cx, cy = anchor[0] + ox, anchor[1] + oy
        el["w"], el["h"] = w, h
        el["x"], el["y"] = cx - w / 2, cy - h / 2

    def _snap(self, el: dict) -> None:
        """Pull the element's centre onto the page's centre lines, and show the guide."""
        W, H = self.design["w"], self.design["h"]
        cx, cy = model.center(el)
        reach = 8 / self._scale
        if abs(cx - W / 2) < reach:
            el["x"] += W / 2 - cx
            self._guides.append((*self._to_canvas(W / 2, 0), *self._to_canvas(W / 2, H)))
        if abs(cy - H / 2) < reach:
            el["y"] += H / 2 - cy
            self._guides.append((*self._to_canvas(0, H / 2), *self._to_canvas(W, H / 2)))

    def _release(self, event) -> None:
        moved = self._drag is not None and self._drag.get("moved")
        self._drag = None
        self._guides = []
        if moved:
            self._refresh_style()
            self.redraw()
        else:
            self.redraw_overlay()

    def _hover(self, event) -> None:
        if self._eyedropper is not None:
            self.canvas.configure(cursor="crosshair")
            return
        handle = self._handle_at(event)
        cursor = {"rotate": "exchange", "p1": "crosshair", "p2": "crosshair", "n": "sb_v_double_arrow",
                  "s": "sb_v_double_arrow", "e": "sb_h_double_arrow", "w": "sb_h_double_arrow"}.get(handle or "", "")
        if handle in {"nw", "ne", "se", "sw"}:
            cursor = "sizing"
        if not cursor:
            x, y = self._to_design(event.x, event.y)
            cursor = "fleur" if model.hit(self.page, x, y, 6 / self._scale) else ""
        self.canvas.configure(cursor=cursor)

    def _wheel(self, event) -> None:
        steps = -1 if event.delta > 0 else 1
        if event.state & 0x4:
            self.set_zoom(self.zoom * (1.15 if steps < 0 else 1 / 1.15), anchor=(event.x, event.y))
        elif event.state & 0x1:
            self.canvas.xview_scroll(steps * 60, "units")
        else:
            self.canvas.yview_scroll(steps * 60, "units")

    def _double(self, event) -> None:
        x, y = self._to_design(event.x, event.y)
        hit = model.hit(self.page, x, y, 6 / self._scale)
        if hit is not None and hit["type"] in {"text", "shape", "table"}:
            self.select(hit["id"])
            self.edit_text()

    def _context(self, event) -> None:
        x, y = self._to_design(event.x, event.y)
        hit = model.hit(self.page, x, y, 6 / self._scale, include_locked=True)
        menu = tkinter.Menu(self, tearoff=0)
        if hit is not None:
            self.select(hit["id"])
            if hit["type"] in {"text", "shape", "table"}:
                menu.add_command(label="Edit text   F2", command=self.edit_text)
            if hit["type"] == "image":
                menu.add_command(label="Replace picture…", command=self.replace_image)
            menu.add_command(label="Duplicate   Ctrl+D", command=self.duplicate_selected)
            menu.add_command(label="Delete   Del", command=self.delete_selected)
            menu.add_separator()
            menu.add_command(label="Bring to front", command=lambda: self.arrange("front"))
            menu.add_command(label="Send to back", command=lambda: self.arrange("back"))
            menu.add_command(label="Copy style   Ctrl+Shift+C", command=self.copy_style)
            menu.add_command(label="Paste style   Ctrl+Shift+V", command=self.paste_style)
            menu.add_command(label="Unlock" if hit.get("locked") else "Lock", command=self.toggle_lock)
        else:
            menu.add_command(label="Paste   Ctrl+V", command=self.paste_element)
            menu.add_command(label="Add text here", command=lambda: self.add_text("body", at=(x, y)))
            menu.add_command(label="Page background…", command=lambda: self._pick_color(self._set_bg, self.page.get("bg")))
        self._popup(menu, event)

    # =====================================================================================
    # selection and element actions
    # =====================================================================================

    def select(self, element_id: str | None) -> None:
        if element_id != self.selected_id:
            self._commit_editor()
            self.selected_id = element_id
            self._refresh_style()
            if element_id is not None:
                try:
                    self.side.set("Style")
                except Exception:
                    pass
        if element_id is not None:
            # The keyboard follows the selection, so Delete, Ctrl+D and the arrows
            # work straight after inserting from the side panel.
            try:
                self.canvas.focus_set()
            except tkinter.TclError:
                pass
        self.redraw_overlay()

    def _place(self, el: dict, at: tuple[float, float] | None = None) -> dict:
        self.checkpoint()
        W, H = self.design["w"], self.design["h"]
        if at is None:
            at = (W / 2, H / 2)
        if el["type"] != "line":
            el["x"], el["y"] = at[0] - el["w"] / 2, at[1] - el["h"] / 2
        model.add(self.design, self.page, el)
        self.select(el["id"])
        self.redraw()
        return el

    def _palette(self) -> list[str]:
        return list(self.design.get("palette") or dai.used_colours(self.design) or ["#2563eb", "#f59e0b", "#10b981",
                                                                                      "#ffffff", "#111827"])

    def _font(self, heading: bool) -> str:
        fonts_ = self.design.get("fonts") or {}
        return fonts_.get("heading" if heading else "body") or "Segoe UI"

    def add_text(self, kind: str, at=None) -> dict:
        H, W = self.design["h"], self.design["w"]
        size = {"title": H * 0.085, "heading": H * 0.055, "body": H * 0.032}[kind]
        words = {"title": "Your title", "heading": "A heading", "body": "Write something here"}[kind]
        ink = model.readable_on(self.page.get("bg", "#ffffff"))
        el = model.text(words, 0, 0, W * (0.7 if kind != "body" else 0.5), size * 1.5, size=size,
                        bold=kind != "body", font=self._font(kind != "body"), color=ink, autofit=True,
                        role="title" if kind == "title" else "")
        return self._place(el, at)

    def add_shape(self, kind: str) -> dict:
        side = min(self.design["w"], self.design["h"]) * 0.25
        w = side * (1.8 if kind in {"rect", "round", "arrow", "chevron", "ribbon", "bubble"} else 1)
        el = model.shape(kind, 0, 0, w, side, fill=self._palette()[0], font=self._font(False),
                         color=model.readable_on(self._palette()[0]), size=side * 0.16)
        return self._place(el)

    def add_line(self, arrow: bool) -> dict:
        W, H = self.design["w"], self.design["h"]
        el = model.line(W * 0.35, H * 0.5, W * 0.65, H * 0.5, stroke=model.readable_on(self.page.get("bg", "#fff")),
                        stroke_w=max(3.0, H * 0.006), arrow="end" if arrow else "none")
        return self._place(el)

    def add_table(self) -> dict:
        W, H = self.design["w"], self.design["h"]
        el = model.table([["Item", "Detail", "Note"], ["", "", ""], ["", "", ""]], 0, 0, W * 0.6, H * 0.3,
                         size=H * 0.028, fill=self._palette()[0], header_color=model.readable_on(self._palette()[0]),
                         font=self._font(False))
        return self._place(el)

    def add_icon(self, glyph: str, mono: bool) -> dict:
        side = min(self.design["w"], self.design["h"]) * 0.15
        el = model.icon(glyph, 0, 0, side, set="mono" if mono else "color", color=self._palette()[0])
        return self._place(el)

    def _image_element(self, src: str) -> dict:
        W, H = self.design["w"], self.design["h"]
        w, h = W * 0.5, H * 0.5
        path = model.resolve_src(src)
        if path is not None:
            try:
                with Image.open(path) as im:
                    ratio = im.width / max(1, im.height)
                h = min(H * 0.7, w / ratio)
                w = h * ratio
            except Exception:
                pass
        return model.picture(src, 0, 0, w, h, fit="cover")

    def add_image_file(self, path: str | None = None) -> dict | None:
        path = path or filedialog.askopenfilename(parent=self, title="Choose a picture", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")])
        if not path:
            return None
        try:
            src = model.import_asset(path)
        except OSError as exc:
            self._say(f"Couldn't read it: {exc}")
            return None
        return self._place(self._image_element(src))

    def replace_image(self) -> None:
        el = self.selected()
        path = filedialog.askopenfilename(parent=self, title="Choose a picture", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")])
        if el is None or not path:
            return
        self.checkpoint()
        el["src"] = model.import_asset(path)
        self.redraw()

    def delete_selected(self) -> None:
        el = self.selected()
        if el is None:
            return
        self.checkpoint()
        self.page["elements"].remove(el)
        self.select(None)
        self.redraw()

    def duplicate_selected(self) -> None:
        el = self.selected()
        if el is None:
            return
        self.checkpoint()
        copy = model.duplicate(self.design, self.page, el, offset=self.design["w"] * 0.02)
        self.select(copy["id"])
        self.redraw()

    def copy_element(self) -> None:
        el = self.selected()
        if el is not None:
            self._element_clip = model.clone(el)
            self._say("Copied.")

    def cut_element(self) -> None:
        self.copy_element()
        self.delete_selected()

    def paste_element(self) -> None:
        try:
            from PIL import ImageGrab

            grabbed = ImageGrab.grabclipboard()
        except Exception:
            grabbed = None
        if isinstance(grabbed, Image.Image):
            path = model.assets_dir() / f"pasted_{kit.stamp()}.png"
            grabbed.save(path)
            self._place(self._image_element(model.import_asset(path)))
            path.unlink(missing_ok=True)
            return
        if self._element_clip is None:
            return
        el = model.clone(self._element_clip)
        el["x"] += self.design["w"] * 0.02
        el["y"] += self.design["h"] * 0.02
        self._element_clip = model.clone(el)
        self.checkpoint()
        model.add(self.design, self.page, el)
        self.select(el["id"])
        self.redraw()

    def copy_style(self) -> None:
        el = self.selected()
        if el is not None:
            self._style_clip = model.copy_style(el)
            self._say("Style copied — select something and Ctrl+Shift+V.")

    def paste_style(self) -> None:
        el = self.selected()
        if el is None or not self._style_clip:
            return
        self.checkpoint()
        changed = model.paste_style(el, self._style_clip)
        self._refresh_style()
        self.redraw()
        self._say(f"Pasted {len(changed)} style setting(s).")

    def arrange(self, where: str) -> None:
        el = self.selected()
        if el is None:
            return
        self.checkpoint()
        model.arrange(self.page, el, where)
        self.redraw()

    def toggle_lock(self) -> None:
        el = self.selected()
        if el is None:
            return
        self.checkpoint()
        el["locked"] = not el.get("locked")
        self._refresh_style()
        self.redraw_overlay()
        self._say("Locked." if el["locked"] else "Unlocked.")

    def nudge(self, dx: int, dy: int, step: float) -> None:
        el = self.selected()
        if el is None or el.get("locked"):
            return
        self._mark_edit("nudge")
        model.move(el, dx * step, dy * step)
        self.redraw()

    # --- inline text editing -----------------------------------------------------------------

    def edit_text(self) -> None:
        el = self.selected()
        if el is None or el["type"] not in {"text", "shape", "table"}:
            return
        self._commit_editor()
        if el["type"] == "table":
            value = "\n".join(" | ".join(row) for row in el["rows"])
        else:
            value = el.get("text", "")
        left, top, right, bottom = model.bbox(el)
        x, y = self._to_canvas(left, top)
        w, h = max(60.0, (right - left) * self._scale), max(30.0, (bottom - top) * self._scale)
        size = max(9, int(el.get("size", 30) * self._scale)) if el["type"] != "table" else 12
        bg = el.get("fill") or self.page.get("bg") or "#ffffff"
        box = tkinter.Text(self.canvas, wrap="word", bd=1, relief="solid", undo=True, padx=4, pady=2,
                           font=(el.get("font") or "Segoe UI", -size, "bold" if el.get("bold") else "normal"),
                           fg=el.get("color") or "#000000", bg=bg, insertbackground=model.readable_on(bg))
        box.insert("1.0", value)
        window = self.canvas.create_window(x, y, window=box, anchor="nw", width=w, height=max(h, size * 2.4),
                                           tags="editor")
        self._editor = (box, window, el["id"])
        box.focus_set()
        box.tag_add("sel", "1.0", "end-1c")
        box.bind("<Escape>", lambda e: (self._commit_editor(cancel=True), "break")[1])
        box.bind("<Control-Return>", lambda e: (self._commit_editor(), "break")[1])
        box.bind("<FocusOut>", lambda e: self.after(10, self._focus_left))

    def _focus_left(self) -> None:
        """The editor lost focus: finish if you moved to something else in the
        window, but keep typing if the whole window lost it (Alt+Tab away)."""
        if not self._editor:
            return
        try:
            now = self.focus_get()
        except (KeyError, tkinter.TclError):
            now = None
        if now is None or now is self._editor[0]:
            return
        self._commit_editor()

    def _commit_editor(self, cancel: bool = False) -> None:
        if not self._editor:
            return
        box, window, element_id = self._editor
        self._editor = None
        try:
            value = box.get("1.0", "end-1c")
            self.canvas.delete(window)
            box.destroy()
        except tkinter.TclError:
            return
        el = model.find(self.page, element_id)
        if cancel or el is None:
            return
        if el["type"] == "table":
            rows = [[c.strip() for c in line.split("|")] for line in value.splitlines() if line.strip()]
            if rows and rows != el["rows"]:
                self.checkpoint()
                el["rows"] = model.clean_value("table", "rows", rows)
        elif value != el.get("text"):
            self.checkpoint()
            el["text"] = value
        self._refresh_style()
        self.redraw()
        try:
            self.canvas.focus_set()
        except tkinter.TclError:
            pass

    # =====================================================================================
    # the Style panel
    # =====================================================================================

    def _refresh_style(self) -> None:
        tab = self.style_tab
        for child in tab.winfo_children():
            child.destroy()
        el = self.selected()
        if el is None:
            ctk.CTkLabel(tab, text="Click something on the page to change how it looks.\n\n"
                                   "Double-click text to type. Drag the round handle to rotate.",
                         wraplength=250, justify="left", text_color=self.colors["muted"]).pack(fill="x", pady=12)
            return
        kind = el["type"]
        title = {"text": "Text", "shape": f"Shape · {el.get('shape')}", "line": "Line", "image": "Picture",
                 "icon": "Icon", "table": "Table"}[kind]
        ctk.CTkLabel(tab, text=title + ("  🔒" if el.get("locked") else ""), font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").pack(fill="x", pady=(6, 2))
        if kind in {"text", "shape"}:
            self._section(tab, "Words")
            box = ctk.CTkTextbox(tab, height=64, wrap="word")
            box.insert("1.0", el.get("text", ""))
            box.pack(fill="x", pady=2)
            box.bind("<KeyRelease>", lambda e: self._set("text", box.get("1.0", "end-1c"), rerender_style=False))
            self._text_controls(tab, el)
        if kind == "table":
            self._section(tab, "Cells (one row per line, columns split by |)")
            box = ctk.CTkTextbox(tab, height=90, wrap="none")
            box.insert("1.0", "\n".join(" | ".join(r) for r in el["rows"]))
            box.pack(fill="x", pady=2)

            def rows_changed(_e=None):
                rows = [[c.strip() for c in line.split("|")] for line in box.get("1.0", "end-1c").splitlines() if line.strip()]
                if rows:
                    self._set("rows", rows, rerender_style=False)

            box.bind("<KeyRelease>", rows_changed)
            self._font_controls(tab, el)
            self._check(tab, "Header row", "header")
            self._color_row(tab, "Header", "fill")
            self._color_row(tab, "Header text", "header_color")
            self._color_row(tab, "Text", "color")
            self._color_row(tab, "Stripes", "stripe")
        if kind == "shape":
            self._section(tab, "Shape")
            self._option(tab, "Kind", "shape", list(model.SHAPES))
            self._color_row(tab, "Fill", "fill", allow_none=True)
            self._color_row(tab, "Outline", "stroke", allow_none=True)
            self._slider(tab, "Outline width", "stroke_w", 0, 40)
            if el.get("shape") in {"round", "bubble"}:
                self._slider(tab, "Corners", "radius", 0, min(el["w"], el["h"]) / 2)
            self._check(tab, "Shadow", "shadow")
        if kind == "line":
            self._section(tab, "Line")
            self._color_row(tab, "Colour", "stroke")
            self._slider(tab, "Width", "stroke_w", 1, 40)
            self._seg(tab, "Arrow", "arrow", ["none", "end", "start", "both"])
            self._check(tab, "Dashed", "dash")
        if kind == "image":
            self._image_controls(tab, el)
        if kind == "icon":
            self._section(tab, "Icon")
            self._seg(tab, "Style", "set", ["color", "mono"])
            if el.get("set") == "mono":
                self._color_row(tab, "Colour", "color")
        self._section(tab, "Position and size")
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x")
        for i, key in enumerate(("x", "y", "w", "h")):
            self._number(grid, key.upper(), key, i)
        if kind != "line":
            self._slider(tab, "Rotation", "rot", 0, 359)
        self._slider(tab, "Opacity", "opacity", 0.05, 1.0)
        self._section(tab, "Arrange")
        row = self._row(tab)
        for label, where in (("Front", "front"), ("Forward", "forward"), ("Back", "back")):
            self._button(row, label, lambda w=where: self.arrange(w), 76).pack(side="left", padx=2)
        row = self._row(tab)
        self._button(row, "Copy style", self.copy_style, 90).pack(side="left", padx=2)
        self._button(row, "Paste style", self.paste_style, 90).pack(side="left", padx=2)
        self._button(row, "🔓" if el.get("locked") else "🔒", self.toggle_lock, 40).pack(side="left", padx=2)
        row = self._row(tab)
        self._button(row, "Duplicate", self.duplicate_selected, 90).pack(side="left", padx=2)
        self._button(row, "Delete", self.delete_selected, 90).pack(side="left", padx=2)

    def _text_controls(self, tab, el: dict) -> None:
        self._font_controls(tab, el)
        row = self._row(tab)
        for label, key in (("B", "bold"), ("I", "italic"), ("U", "underline")):
            on = bool(el.get(key))
            ctk.CTkButton(row, text=label, width=34, height=28, fg_color=self.colors["accent_dim"] if on else "transparent",
                          border_width=1, border_color=self.colors["accent_dim"], text_color=self.colors["text"],
                          font=ctk.CTkFont(weight="bold" if key == "bold" else "normal", slant="italic" if key == "italic" else "roman",
                                           underline=key == "underline"),
                          command=lambda k=key: self._set(k, not bool((self.selected() or {}).get(k)))).pack(side="left", padx=2)
        self._seg(tab, "Align", "align", ["left", "center", "right"])
        self._seg(tab, "Vertical", "valign", ["top", "middle", "bottom"])
        self._color_row(tab, "Text colour", "color")
        if el["type"] == "text":
            self._color_row(tab, "Box fill", "fill", allow_none=True)
            self._check(tab, "Shadow", "shadow")
        self._slider(tab, "Line spacing", "line", 0.8, 2.2)
        self._check(tab, "Shrink to fit the box", "autofit")

    def _font_controls(self, tab, el: dict) -> None:
        self._section(tab, "Font")
        row = self._row(tab)
        self._button(row, el.get("font") or "Segoe UI", self.pick_font, 150,
                     font=ctk.CTkFont(family=el.get("font") or "Segoe UI", size=13)).pack(side="left", padx=2)
        size = ctk.CTkEntry(row, width=56)
        size.insert(0, f"{el.get('size', 30):.0f}")
        size.pack(side="left", padx=2)
        size.bind("<Return>", lambda e: self._set("size", size.get()))
        size.bind("<FocusOut>", lambda e: self._set("size", size.get()))
        self._button(row, "A+", lambda: self._scale_font(1.15), 38).pack(side="left", padx=1)
        self._button(row, "A-", lambda: self._scale_font(1 / 1.15), 38).pack(side="left", padx=1)

    def _image_controls(self, tab, el: dict) -> None:
        self._section(tab, "Picture")
        row = self._row(tab)
        self._button(row, "Replace…", self.replace_image, 90).pack(side="left", padx=2)
        self._button(row, "Flip ↔", lambda: self._set("flip_h", not el.get("flip_h")), 70).pack(side="left", padx=2)
        self._button(row, "Flip ↕", lambda: self._set("flip_v", not el.get("flip_v")), 70).pack(side="left", padx=2)
        self._option(tab, "Filter", "filter", list(model.FILTERS))
        self._seg(tab, "Fit", "fit", ["cover", "contain", "stretch"])
        self._section(tab, "Crop")
        for i, side in enumerate(("left", "top", "right", "bottom")):
            row = self._row(tab)
            ctk.CTkLabel(row, text=side.title(), width=60, anchor="w").pack(side="left")
            slider = ctk.CTkSlider(row, from_=0, to=0.45, width=170)
            slider.set((el.get("crop") or [0, 0, 0, 0])[i])
            slider.pack(side="left")
            slider.configure(command=lambda v, n=i: self._set_crop(n, v))
        self._slider(tab, "Rounded corners", "radius", 0, min(el["w"], el["h"]) / 2)
        self._check(tab, "Circle", "circle")
        self._color_row(tab, "Border", "stroke", allow_none=True)
        self._slider(tab, "Border width", "stroke_w", 0, 40)
        self._check(tab, "Shadow", "shadow")

    def _set_crop(self, n: int, value: float) -> None:
        el = self.selected()
        if el is None:
            return
        crop = list(el.get("crop") or [0, 0, 0, 0])
        crop[n] = float(value)
        self._set("crop", crop, rerender_style=False)

    def _scale_font(self, factor: float) -> None:
        el = self.selected()
        if el is not None and "size" in el:
            self._set("size", el["size"] * factor)

    def _set(self, key: str, value, rerender_style: bool = True) -> None:
        el = self.selected()
        if el is None:
            return
        try:
            clean = model.clean_value(el["type"], key, value, el.get(key))
        except KeyError:
            return
        if clean == el.get(key):
            return
        self._mark_edit(f"{el['id']}:{key}")
        el[key] = clean
        self.schedule_render()
        if rerender_style and key in {"shape", "set", "bold", "italic", "underline", "fill", "stroke", "color",
                                      "header_color", "stripe", "font", "circle", "flip_h", "flip_v", "locked"}:
            self.after(10, self._refresh_style)

    def _number(self, grid, label: str, key: str, column: int) -> None:
        el = self.selected()
        ctk.CTkLabel(grid, text=label, width=14).grid(row=0, column=column * 2, padx=(2, 0))
        entry = ctk.CTkEntry(grid, width=50)
        entry.insert(0, f"{el.get(key, 0):.0f}")
        entry.grid(row=0, column=column * 2 + 1, padx=(1, 3))
        entry.bind("<Return>", lambda e: self._set(key, entry.get(), rerender_style=False))
        entry.bind("<FocusOut>", lambda e: self._set(key, entry.get(), rerender_style=False))

    def _slider(self, tab, label: str, key: str, lo: float, hi: float) -> None:
        el = self.selected()
        row = self._row(tab)
        ctk.CTkLabel(row, text=label, width=96, anchor="w").pack(side="left")
        slider = ctk.CTkSlider(row, from_=lo, to=max(hi, lo + 0.01), width=150)
        slider.set(max(lo, min(hi, float(el.get(key, lo) or lo))))
        slider.pack(side="left")
        slider.configure(command=lambda v: self._set(key, v, rerender_style=False))

    def _check(self, tab, label: str, key: str) -> None:
        el = self.selected()
        var = tkinter.BooleanVar(value=bool(el.get(key)))
        ctk.CTkCheckBox(tab, text=label, variable=var, command=lambda: self._set(key, var.get())).pack(anchor="w", pady=2)

    def _seg(self, tab, label: str, key: str, values: list[str]) -> None:
        el = self.selected()
        row = self._row(tab)
        ctk.CTkLabel(row, text=label, width=70, anchor="w").pack(side="left")
        seg = ctk.CTkSegmentedButton(row, values=values, command=lambda v: self._set(key, v),
                                     selected_color=self.colors["accent_dim"])
        seg.set(el.get(key) or values[0])
        seg.pack(side="left")

    def _option(self, tab, label: str, key: str, values: list[str]) -> None:
        el = self.selected()
        row = self._row(tab)
        ctk.CTkLabel(row, text=label, width=70, anchor="w").pack(side="left")
        menu = ctk.CTkOptionMenu(row, values=values, width=150, command=lambda v: self._set(key, v))
        menu.set(el.get(key) or values[0])
        menu.pack(side="left")

    def _color_row(self, tab, label: str, key: str, allow_none: bool = False) -> None:
        row = self._row(tab)
        ctk.CTkLabel(row, text=label, width=86, anchor="w").pack(side="left")
        self._color_controls(row, lambda: (self.selected() or {}).get(key), lambda v: self._set(key, v),
                             allow_none=allow_none)

    def _color_controls(self, row, get, put, allow_none: bool) -> None:
        """A swatch (opens the colour picker), an eyedropper, 'none', and the design's palette as chips."""
        current = get()
        swatch = ctk.CTkButton(row, text="" if current else "∅", width=30, height=26, fg_color=current or "transparent",
                               border_width=1, border_color=self.colors["muted"], hover=False,
                               command=lambda: self._pick_color(put, get()))
        swatch.pack(side="left", padx=2)
        self._button(row, "💧", lambda: self._start_eyedropper(put), 30, height=26).pack(side="left", padx=1)
        if allow_none:
            self._button(row, "∅", lambda: put(None), 26, height=26).pack(side="left", padx=1)
        for colour in self._palette()[:5]:
            ctk.CTkButton(row, text="", width=16, height=16, fg_color=colour, hover=False, corner_radius=8,
                          border_width=1, border_color=self.colors["muted"],
                          command=lambda c=colour: put(c)).pack(side="left", padx=1)

    def _pick_color(self, put, current: str | None) -> None:
        chosen = colorchooser.askcolor(color=current or "#ffffff", parent=self, title="Choose a colour")
        if chosen and chosen[1]:
            put(chosen[1])
            self._refresh_style()
            self._refresh_page_tab()

    def _start_eyedropper(self, put) -> None:
        self._eyedropper = put
        self.canvas.configure(cursor="crosshair")
        self._say("Click anywhere on the page to pick its colour. Esc cancels.")
        self.canvas.focus_set()
        self.canvas.bind("<Escape>", lambda e: (self._stop_eyedropper(), "break")[1])

    def _stop_eyedropper(self) -> None:
        self._eyedropper = None
        self.canvas.configure(cursor="")
        self.canvas.bind("<Escape>", lambda e: (self.select(None), "break")[1])

    def _sample(self, event) -> None:
        put = self._eyedropper
        self._stop_eyedropper()
        image = self._page_image
        if image is None:
            return
        px = int(self.canvas.canvasx(event.x) - self._ox)
        py = int(self.canvas.canvasy(event.y) - self._oy)
        if 0 <= px < image.width and 0 <= py < image.height:
            colour = "#%02x%02x%02x" % image.getpixel((px, py))[:3]
            put(colour)
            self._say(f"Picked {colour}.")
            self._refresh_style()
            self._refresh_page_tab()

    def _set_bg(self, colour: str | None) -> None:
        colour = model.color(colour, None)
        if colour and colour != self.page.get("bg"):
            self._mark_edit("bg")
            self.page["bg"] = colour
            self.redraw()

    # --- fonts --------------------------------------------------------------------------------

    def pick_font(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Choose a font")
        dialog.geometry("420x520")
        dialog.transient(self.winfo_toplevel())
        search = ctk.CTkEntry(dialog, placeholder_text="Search fonts")
        search.pack(fill="x", padx=10, pady=8)
        text = tkinter.Text(dialog, wrap="none", cursor="hand2", bd=0, padx=10, pady=6,
                            bg=self.colors["panel"], fg=self.colors["text"], highlightthickness=0)
        text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        families = fonts.families()

        def fill(filter_text: str = "") -> None:
            text.configure(state="normal")
            text.delete("1.0", "end")
            for family in families:
                if filter_text and filter_text.lower() not in family.lower():
                    continue
                tag = f"f{abs(hash(family))}"
                text.tag_configure(tag, font=(family, 16), spacing1=4, spacing3=4)
                text.tag_bind(tag, "<Button-1>", lambda e, f=family: choose(f))
                text.insert("end", family + "\n", tag)
            text.configure(state="disabled")

        def choose(family: str) -> None:
            self._set("font", family)
            dialog.destroy()

        search.bind("<KeyRelease>", lambda e: fill(search.get().strip()))
        fill()
        dialog.after(120, lambda: (dialog.lift(), search.focus_set()))

    # =====================================================================================
    # inserting: pictures made by JARVIS
    # =====================================================================================

    def _work(self, label: str, job, done) -> None:
        """Run job() on a worker; done(result, error) back on the Tk thread."""
        if self._busy:
            self._say("Still working on the last one…")
            return
        self._busy = True
        self._say(label)

        def work():
            try:
                result, error = job(), None
            except Exception as exc:
                result, error = None, str(exc) or type(exc).__name__

            def back():
                self._busy = False
                done(result, error)

            _ui().safe_after(self, back)

        threading.Thread(target=work, daemon=True).start()

    def add_ai_image(self, prompt: str | None = None, replace: dict | None = None) -> None:
        prompt = (prompt or self.ai_image_entry.get()).strip()
        if not prompt:
            self._say("Describe the picture first.")
            return
        images = self.app.jarvis.images
        design = self.design

        def done(src, error):
            if error:
                self._say(f"No picture: {error}")
                return
            if replace is not None and model.find(self.page, replace["id"]) is not None:
                self.checkpoint()
                replace["src"] = src
                self.redraw()
            else:
                self._place(self._image_element(src))
            self._say("Picture added.")

        self._work("Making the picture…", lambda: dai.ai_image(images, prompt, design), done)

    def slide_picture(self) -> None:
        title = next((e["text"] for e in self.page["elements"] if e.get("role") == "title" and e.get("text")), "")
        topic = title or self.design.get("title", "")
        page = self.page
        images = self.app.jarvis.images
        design = self.design

        def done(src, error):
            if error:
                self._say(f"No picture: {error}")
                return
            self.checkpoint()
            W, H = design["w"], design["h"]
            existing = next((e for e in page["elements"] if e.get("role") == "image"), None)
            if existing is not None:
                existing["src"] = src
            else:
                body = next((e for e in page["elements"] if e.get("role") == "body"), None)
                x = W * 0.56
                if body is not None and body["x"] + body["w"] > x - 40:
                    body["w"] = max(W * 0.3, x - 60 - body["x"])
                model.add(design, page, model.picture(src, x, H * 0.27, W * 0.38, H * 0.62, role="image", radius=24))
            self.redraw()
            self._say("Picture added to the slide.")

        prompt = f"{topic}. Clean, modern illustration for a presentation slide, no text"
        self._work("Making a picture for this slide…", lambda: dai.ai_image(images, prompt, design), done)

    # =====================================================================================
    # the AI panel's actions
    # =====================================================================================

    def ask_change(self, text: str | None = None) -> None:
        request = (text or self.ask_box.get("1.0", "end-1c")).strip()
        if not request:
            self.ai_reply.configure(text="Type (or say) what to change first.")
            return
        snap = self._snapshot()
        design, page, el = self.design, self.page, self.selected()
        quick = dai.quick_edit(design, page, request, el)
        if quick:
            self.undo_stack.append(snap)
            self.redo_stack.clear()
            self._changed()
            self.ai_reply.configure(text=quick)
            self._refresh_style()
            self.redraw()
            return
        brain = self.app.jarvis.brain
        work_copy = model.clone(design)
        work_page = work_copy["pages"][self.index]
        selected = model.find(work_page, self.selected_id) if self.selected_id else None

        def done(said, error):
            if error:
                self.ai_reply.configure(text=error)
                self._say("")
                return
            self.undo_stack.append(snap)
            self.redo_stack.clear()
            self.design = work_copy
            self._changed()
            self.ai_reply.configure(text=said)
            if self.selected_id and model.find(self.page, self.selected_id) is None:
                self.selected_id = None
            self._load_into_ui(keep_view=True)
            self._say("Changed. Ctrl+Z undoes it.")

        self._work("JARVIS is changing it…", lambda: dai.chat_edit(brain, work_copy, work_page, request, selected), done)

    def toggle_voice(self) -> None:
        voice = self.app.jarvis.voice
        if not self._listening:
            if not voice.mic_available() or not voice.start_push_to_talk():
                self.ai_reply.configure(text="No microphone found.")
                return
            self._listening = True
            self.mic_btn.configure(text="● Stop", fg_color="#b91c1c")
            self.ai_reply.configure(text="Listening… say the change, then press Stop.")
            return
        self._listening = False
        self.mic_btn.configure(text="◉ Say it", fg_color="transparent")

        def done(heard, error):
            if error or not heard:
                self.ai_reply.configure(text=error or "I didn't catch that.")
                return
            self.ask_box.delete("1.0", "end")
            self.ask_box.insert("1.0", heard)
            if heard.lower().startswith(("design ", "make a ", "make an ", "create ", "tasarla")):
                self.describe_box.delete("1.0", "end")
                self.describe_box.insert("1.0", heard)
                self.describe_design()
            else:
                self.ask_change(heard)

        self._work("Hearing you…", voice.stop_push_to_talk, done)

    def describe_design(self, text: str | None = None, kind: str | None = None) -> None:
        description = (text or self.describe_box.get("1.0", "end-1c")).strip()
        if not description:
            self.ai_reply.configure(text="Describe what to make first.")
            return
        chosen = kind or self.describe_kind.get()
        chosen = None if chosen == "Auto" else chosen
        brain = self.app.jarvis.brain

        def done(design, error):
            if error:
                self._say(error)
                self.ai_reply.configure(text=error)
                return
            self.load(design)
            self.save(quiet=True)
            self._say(f"Designed: {design['title']}. Everything on it is editable.")

        self._work("JARVIS is designing it…", lambda: dai.design_from(brain, description, chosen), done)

    def make_better(self, all_pages: bool) -> None:
        self.checkpoint()
        pages = range(len(self.design["pages"])) if all_pages else [self.index]
        notes = [n for i in pages for n in dai.polish(self.design, i)]
        self.redraw()
        self._refresh_pages()
        message = "; ".join(dict.fromkeys(notes)) or "It already looked tidy — nothing to change."
        self.ai_reply.configure(text=message[:400])
        self._say("Polished. Ctrl+Z undoes it." if notes else "Nothing to change.")

    def critique(self) -> None:
        findings = dai.critique(self.design, self.index)
        brain = self.app.jarvis.brain
        design, index = model.clone(self.design), self.index
        self._show_text("Design check", "\n".join(f"• {f}" for f in findings) + "\n\nAsking JARVIS for its take…")

        def done(opinion, error):
            body = "\n".join(f"• {f}" for f in findings)
            body += f"\n\nJARVIS's take:\n{opinion}" if opinion else (f"\n\n({error})" if error else "")
            self._show_text("Design check", body)

        self._work("Looking at it…", lambda: dai.critique_ai(brain, design, index, findings), done)

    def _show_text(self, title: str, body: str) -> None:
        dialog = getattr(self, "_text_dialog", None)
        if dialog is None or not dialog.winfo_exists():
            dialog = ctk.CTkToplevel(self)
            dialog.geometry("520x460")
            dialog.transient(self.winfo_toplevel())
            box = ctk.CTkTextbox(dialog, wrap="word")
            box.pack(fill="both", expand=True, padx=10, pady=10)
            dialog._box = box
            self._text_dialog = dialog
        dialog.title(title)
        dialog._box.configure(state="normal")
        dialog._box.delete("1.0", "end")
        dialog._box.insert("1.0", body)
        dialog._box.configure(state="disabled")
        dialog.after(100, dialog.lift)

    def headline_ideas(self) -> None:
        topic = self.headline_entry.get().strip() or self.design.get("title", "")
        brain = self.app.jarvis.brain

        def done(items, error):
            for child in self.headline_box.winfo_children():
                child.destroy()
            if error:
                self.ai_reply.configure(text=error)
                return
            for item in items:
                ctk.CTkButton(self.headline_box, text=item, anchor="w", height=28, fg_color="transparent",
                              hover_color=self.colors["accent_dim"], text_color=self.colors["text"],
                              command=lambda t=item: self._use_headline(t)).pack(fill="x", pady=1)
            self._say("Click a headline to put it on the page.")

        self._work("Writing headlines…", lambda: dai.headlines(brain, topic), done)

    def _use_headline(self, text: str) -> None:
        el = self.selected()
        if el is None or el["type"] not in {"text", "shape"}:
            el = next((e for e in self.page["elements"] if e.get("role") in dai.TEXT_ROLES_TITLE), None)
        self.checkpoint()
        if el is None:
            self.undo_stack.pop()
            self.add_text("title")
            el = self.selected()
        el["text"] = text
        self._refresh_style()
        self.redraw()

    def palette_mood(self) -> None:
        mood = self.mood_entry.get().strip()
        if not mood:
            self._say("Type a mood first.")
            return
        brain = self.app.jarvis.brain
        self._work("Mixing colours…", lambda: dai.palette_from_mood(brain, mood)[0], self._show_palette)

    def palette_photo(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="A photo to take colours from", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if path:
            self._work("Reading the photo's colours…", lambda: dai.palette_from_photo(Path(path)), self._show_palette)

    def _show_palette(self, colours, error) -> None:
        for child in self.palette_box.winfo_children():
            child.destroy()
        if error:
            self._say(error)
            return
        self._palette_result = colours
        row = self._row(self.palette_box)
        for colour in colours:
            ctk.CTkButton(row, text="", width=40, height=30, fg_color=colour, hover=False, border_width=1,
                          border_color=self.colors["muted"]).pack(side="left", padx=1)
        self._button(self.palette_box, "Apply to the design", self.apply_palette, 250,
                     fg_color=self.colors["accent_dim"]).pack(anchor="w", pady=2)
        self._say("  ".join(colours))

    def apply_palette(self, colours: list[str] | None = None) -> None:
        colours = colours or self._palette_result
        if not colours:
            return
        self.checkpoint()
        dai.apply_palette(self.design, colours)
        self._load_into_ui(keep_view=True)
        self._say("New colours applied. Ctrl+Z undoes it.")

    def font_tips(self) -> None:
        mood = self.font_mood.get().strip()
        brain = self.app.jarvis.brain if mood else None

        def done(pairs, error):
            for child in self.font_box.winfo_children():
                child.destroy()
            if error or not pairs:
                self._say(error or "No font pairs on this PC.")
                return
            for heading, body, vibe in pairs:
                ctk.CTkButton(self.font_box, text=f"{heading} + {body}\n{vibe}", anchor="w", height=44,
                              fg_color="transparent", hover_color=self.colors["accent_dim"],
                              text_color=self.colors["text"], font=ctk.CTkFont(family=heading, size=14),
                              command=lambda h=heading, b=body: self.apply_fonts(h, b)).pack(fill="x", pady=1)

        self._work("Choosing fonts…", lambda: dai.font_suggestions(brain, mood, 5), done)

    def apply_fonts(self, heading: str, body: str) -> None:
        self.checkpoint()
        dai.apply_fonts(self.design, heading, body)
        self._load_into_ui(keep_view=True)
        self._say(f"Fonts: {heading} for headings, {body} for text.")

    def resize_copy(self, fmt: str | None = None) -> None:
        fmt = fmt or self.resize_menu.get()
        try:
            copy = dai.resize(self.design, fmt)
        except dai.DesignAIError as exc:
            self._say(str(exc))
            return
        self.save(quiet=True)
        self.load(copy)
        self.save(quiet=True)
        self._say(f"Made a {model.FORMATS[fmt][0]} copy — the original is in Designs.")

    def resize_all(self) -> None:
        self.save(quiet=True)
        made = []
        for fmt in ("instagram", "story", "thumbnail", "facebook", "banner", "poster"):
            if fmt == self.design["format"]:
                continue
            made.append(model.save(dai.resize(self.design, fmt)))
        self._say(f"Made {len(made)} copies — open them from 📂 Designs.")
        self.ai_reply.configure(text="Copies: " + ", ".join(model.FORMATS[f][0] for f in
                                                            ("instagram", "story", "thumbnail", "facebook", "banner",
                                                             "poster") if f != self.design["format"]))

    def apply_brand(self) -> None:
        self.checkpoint()
        done = dai.apply_brand(self.design)
        if not done:
            self.undo_stack.pop()
            self._say("Your brand kit is empty — Edit brand… first.")
            return
        self._load_into_ui(keep_view=True)
        self._say("Applied " + ", ".join(done) + ".")

    def edit_brand(self) -> None:
        brand = dai.BRAND.load()
        dialog = ctk.CTkToplevel(self)
        dialog.title("Brand kit")
        dialog.geometry("440x420")
        dialog.transient(self.winfo_toplevel())
        ctk.CTkLabel(dialog, text="Your brand, applied to any design in one click.",
                     text_color=self.colors["muted"]).pack(pady=(12, 6))
        name = ctk.CTkEntry(dialog, placeholder_text="Brand name", width=380)
        name.insert(0, brand.get("name", ""))
        name.pack(pady=4)
        colours = list(brand.get("colors") or []) + [""] * 5
        colours = colours[:5]
        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(pady=6)
        swatches: list = []
        for i, label in enumerate(("Primary", "Secondary", "Accent", "Light", "Dark")):
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.pack(side="left", padx=4)
            button = ctk.CTkButton(cell, text="" if colours[i] else "+", width=56, height=40,
                                   fg_color=colours[i] or "transparent", border_width=1,
                                   border_color=self.colors["muted"])
            button.configure(command=lambda n=i, b=button: pick(n, b))
            button.pack()
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=10)).pack()
            swatches.append(button)

        def pick(n, button):
            chosen = colorchooser.askcolor(color=colours[n] or "#ffffff", parent=dialog)
            if chosen and chosen[1]:
                colours[n] = chosen[1]
                button.configure(fg_color=chosen[1], text="")

        heading = ctk.CTkComboBox(dialog, values=fonts.families()[:60], width=380)
        heading.set(brand.get("heading") or "Heading font")
        heading.pack(pady=4)
        body = ctk.CTkComboBox(dialog, values=fonts.families()[:60], width=380)
        body.set(brand.get("body") or "Body font")
        body.pack(pady=4)
        logo = {"src": brand.get("logo", "")}
        logo_label = ctk.CTkLabel(dialog, text=Path(logo["src"]).name if logo["src"] else "No logo")

        def choose_logo():
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp")])
            if path:
                logo["src"] = model.import_asset(path)
                logo_label.configure(text=Path(path).name)

        self._button(dialog, "Choose logo…", choose_logo, 140).pack(pady=(8, 2))
        logo_label.pack()

        def save():
            fonts_ok = set(fonts.families())
            dai.BRAND.save({"name": name.get().strip(), "colors": [c for c in colours if c],
                            "heading": heading.get() if heading.get() in fonts_ok else "",
                            "body": body.get() if body.get() in fonts_ok else "", "logo": logo["src"]})
            dialog.destroy()
            self._say("Brand kit saved. Apply brand puts it on this design.")

        self._button(dialog, "Save brand kit", save, 160, fg_color=self.colors["accent_dim"]).pack(pady=12)

    def save_template(self) -> None:
        copy = model.copy_design(self.design, self.design["title"])
        path = model.save(copy, model.templates_dir() / f"{copy['id']}{model.EXT}")
        self._say(f"Saved as a template: {path.stem}. It's under Templates → Mine.")

    # --- the Page panel's actions ------------------------------------------------------------------

    def apply_theme(self) -> None:
        name = self.theme_menu.get()
        if self.design.get("kind") != "slides":
            self._say("Slide themes are for decks — for other designs try a palette (AI tab).")
            return
        self.checkpoint()
        templates.apply_theme(self.design, name)
        self._load_into_ui(keep_view=True)
        self._say(f"Theme: {templates.SLIDE_THEMES[name]['label']}.")

    def write_notes(self, all_pages: bool) -> None:
        brain = self.app.jarvis.brain
        work = model.clone(self.design)
        pages = None if all_pages else [self.index]

        def done(count, error):
            if error:
                self._say(error)
                return
            self.checkpoint()
            for i, page in enumerate(work["pages"]):
                if i < len(self.design["pages"]):
                    self.design["pages"][i]["notes"] = page.get("notes", "")
            self._load_notes()
            self._say(f"Wrote notes for {count} slide(s).")

        self._work("Writing speaker notes…", lambda: dai.speaker_notes(brain, work, pages), done)

    def deck_from_youtube(self) -> None:
        url = self.yt_entry.get().strip()
        if not url:
            self._say("Paste a YouTube link first.")
            return
        brain, count, theme = self.app.jarvis.brain, int(self.yt_count.get()), self.theme_menu.get()

        def done(design, error):
            if error:
                self._say(error)
                return
            self.load(design)
            self.save(quiet=True)
            self._say(f"Made {len(design['pages'])} slides from the video.")

        self._work("Reading the video and making slides…", lambda: dai.deck_from_youtube(brain, url, count, theme), done)

    def quiz_deck(self) -> None:
        topic = self.quiz_entry.get().strip()
        if not topic:
            self._say("Type a topic first.")
            return
        brain, count = self.app.jarvis.brain, int(self.quiz_count.get())

        def done(design, error):
            if error:
                self._say(error)
                return
            self.load(design)
            self.save(quiet=True)
            self._say(f"Quiz ready: {count} questions, each followed by its answer.")

        self._work("Writing the quiz…", lambda: dai.quiz_slides(brain, topic, count), done)

    def import_pptx(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(parent=self, title="Open a PowerPoint", filetypes=[
            ("PowerPoint", "*.pptx")])
        if not path:
            return
        from jarvis.design import pptxio

        try:
            design = pptxio.import_pptx(Path(path))
        except model.DesignError as exc:
            self._say(str(exc))
            return
        self.load(design)
        self.save(quiet=True)
        self._say(f"Opened {Path(path).name}: {len(design['pages'])} slides, all editable.")

    def drop_file(self, path: Path) -> bool:
        """A file dropped on the window while this page is showing."""
        suffix = path.suffix.lower()
        if suffix == ".pptx":
            self.import_pptx(str(path))
            return True
        if suffix == model.EXT:
            self.open_path(path)
            return True
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            self.add_image_file(str(path))
            return True
        return False

    # =====================================================================================
    # exporting
    # =====================================================================================

    def _export_menu(self) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="PDF (all pages)", command=lambda: self.export("pdf"))
        menu.add_command(label="PNG (this page)", command=lambda: self.export("png"))
        menu.add_command(label="PNG (all pages)", command=lambda: self.export("png-all"))
        menu.add_command(label="PNG with a transparent background", command=lambda: self.export("png-clear"))
        menu.add_command(label="JPG (this page)", command=lambda: self.export("jpg"))
        menu.add_separator()
        menu.add_command(label="PowerPoint (.pptx)", command=lambda: self.export("pptx"))
        menu.add_command(label="Open in PowerPoint", command=lambda: self.export("open"))
        self._popup(menu)

    def export(self, kind: str) -> list[Path]:
        self._commit_editor()
        self.save(quiet=True)
        base = model.exports_dir() / f"{kit.slug(self.design['title'])}_{kit.stamp()}"
        try:
            if kind == "pdf":
                out = [render.export_pdf(self.design, base.with_suffix(".pdf"))]
            elif kind in {"png", "jpg"}:
                out = render.export_images(self.design, base, kind.upper(), [self.index])
            elif kind == "png-all":
                out = render.export_images(self.design, base, "PNG")
            elif kind == "png-clear":
                path = base.with_suffix(".png")
                render.render_page(self.design, self.index, 1.0, transparent=True).save(path)
                out = [path]
            else:
                from jarvis.design import pptxio

                out = [pptxio.export_pptx(self.design, base.with_suffix(".pptx"))]
        except Exception as exc:
            self._say(f"Export failed: {exc}")
            return []
        if kind == "open":
            self.app._open_path(out[0])
            self._say("Opening it in PowerPoint…")
        else:
            self._say(f"Exported {out[0].name}" + (f" (+{len(out) - 1})" if len(out) > 1 else ""))
            self.app._open_path(out[0].parent)
        return out

    # =====================================================================================
    # galleries
    # =====================================================================================

    def _grid_dialog(self, title: str) -> tuple[ctk.CTkToplevel, ctk.CTkScrollableFrame, ctk.CTkFrame]:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("860x600")
        dialog.transient(self.winfo_toplevel())
        top = ctk.CTkFrame(dialog, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))
        grid = ctk.CTkScrollableFrame(dialog, fg_color=self.colors["panel"])
        grid.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        dialog.after(150, dialog.lift)
        return dialog, grid, top

    def open_gallery(self) -> None:
        self._autosave()
        dialog, grid, top = self._grid_dialog("My designs")
        ctk.CTkLabel(top, text="Click to open · right-click for more", text_color=self.colors["muted"]).pack(side="left")
        self._button(top, "Open a .pptx…", lambda: (dialog.destroy(), self.import_pptx()), 120).pack(side="right", padx=4)
        self._button(top, "Folder", lambda: self.app._open_path(model.designs_dir()), 70).pack(side="right", padx=4)
        items = model.listing()
        if not items:
            ctk.CTkLabel(grid, text="No designs yet — make one with ＋ New, a template, or AI → Describe it.").pack(pady=30)
            return
        dialog._images = []
        for n, item in enumerate(items[:120]):
            image = None
            if item["thumb"]:
                try:
                    with Image.open(item["thumb"]) as im:
                        im.thumbnail((180, 130))
                        image = ctk.CTkImage(im.copy(), size=im.size)
                except Exception:
                    image = None
            dialog._images.append(image)
            text = f"{item['title'][:24]}\n{kit.ago(item['modified'])}"
            button = ctk.CTkButton(grid, text=text, image=image, compound="top", width=190, height=170,
                                   fg_color="transparent", hover_color=self.colors["accent_dim"],
                                   text_color=self.colors["text"],
                                   command=lambda p=item["path"]: (dialog.destroy(), self.open_path(p)))
            button.grid(row=n // 4, column=n % 4, padx=6, pady=6)
            button.bind("<Button-3>", lambda e, p=item["path"]: self._gallery_menu(e, p, dialog))

    def _gallery_menu(self, event, path: Path, dialog) -> None:
        menu = tkinter.Menu(self, tearoff=0)

        def duplicate():
            copy = model.copy_design(model.load(path))
            model.save(copy)
            dialog.destroy()
            self.open_gallery()

        def delete():
            model.delete(path)
            dialog.destroy()
            self.open_gallery()

        menu.add_command(label="Open", command=lambda: (dialog.destroy(), self.open_path(path)))
        menu.add_command(label="Duplicate", command=duplicate)
        menu.add_command(label="Delete (to the Recycle Bin)", command=delete)
        self._popup(menu, event)

    def open_templates(self) -> None:
        dialog, grid, top = self._grid_dialog("Templates")
        catalogue = templates.catalogue()
        mine = model.listing(model.templates_dir())
        groups = ["All"] + list(dict.fromkeys(item["group"] for item in catalogue)) + (["Mine"] if mine else [])
        choice = ctk.CTkSegmentedButton(top, values=groups, selected_color=self.colors["accent_dim"])
        choice.pack(side="left")
        dialog._images = []

        def show(group: str) -> None:
            for child in grid.winfo_children():
                child.destroy()
            dialog._images = []
            if group == "Mine":
                entries = [{"label": m["title"], "make": (lambda p=m["path"]: model.copy_design(model.load(p),
                                                                                                model.load(p)["title"])),
                            "thumb": m["thumb"]} for m in mine]
            else:
                entries = [c for c in catalogue if group in {"All", c["group"]}]
            queue = list(enumerate(entries))

            def next_batch():
                for _ in range(4):
                    if not queue or not dialog.winfo_exists():
                        return
                    n, entry = queue.pop(0)
                    try:
                        if entry.get("thumb"):
                            with Image.open(entry["thumb"]) as im:
                                im.thumbnail((180, 130))
                                picture = im.copy()
                        else:
                            picture = render.thumbnail(entry["make"](), 180)
                        image = ctk.CTkImage(picture, size=picture.size)
                    except Exception:
                        image = None
                    dialog._images.append(image)
                    ctk.CTkButton(grid, text=entry["label"][:30], image=image, compound="top", width=190, height=170,
                                  fg_color="transparent", hover_color=self.colors["accent_dim"],
                                  text_color=self.colors["text"],
                                  command=lambda e=entry: (dialog.destroy(), self.load(e["make"]()))).grid(
                        row=n // 4, column=n % 4, padx=6, pady=6)
                dialog.after(1, next_batch)

            next_batch()

        choice.configure(command=show)
        choice.set("All")
        show("All")

    def show_shortcuts(self) -> None:
        self._show_text("Design page shortcuts", "\n".join(f"{k:<24} {v}" for k, v in SHORTCUTS) +
                        "\n\nClick the canvas first so it has the keyboard.")
