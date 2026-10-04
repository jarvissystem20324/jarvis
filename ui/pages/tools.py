"""Every command as a tile, a Ctrl+K palette, and chips under the chat box.

Nobody remembers three hundred commands, so none of these needs remembering:
search by what you want ("compress pdf", "kdv"), click the tile, fill in the
form. The command is still shown on each form, so it can be learnt by use.
"""

from __future__ import annotations

import tkinter

import customtkinter as ctk

from jarvis import catalog
from ui.pages import PAGES
from ui.pages.base import Page, ToolDialog, button, colors, emoji_image, label, one_layout, text_font

TILE_WIDTH = 250


class ToolsPage(Page):
    key = "tools"
    title = "Tools"
    icon = "🧰"

    def build(self) -> None:
        c = self.colors
        self.found = catalog.tools(getattr(self.app.jarvis, "addons", None))
        self.group = "All"
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 6))
        label(top, f"{self.icon}  Tools", size=22, bold=True, text_color=c["accent"]).pack(side="left")
        self.count = label(top, "", size=12, muted=True)
        self.count.pack(side="left", padx=12)
        self.search = ctk.CTkEntry(top, placeholder_text="Search: “compress pdf”, “kdv”, “timer”…", width=380,
                                   height=36, fg_color=c["panel"])
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda e: self._later())
        self.search.bind("<Return>", lambda e: self._open_first())

        self.recent_row = ctk.CTkFrame(self, fg_color="transparent", height=4)
        self.recent_row.pack(fill="x", padx=20, pady=(0, 4))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        side = ctk.CTkScrollableFrame(body, fg_color=c["panel"], width=190)
        side.grid(row=0, column=0, sticky="ns", padx=(8, 8))
        self.group_buttons = {}
        for group in ["All", "Recent"] + catalog.groups(self.found):
            count = len(self.found) if group == "All" else (
                len(catalog.recent(24, self.found)) if group == "Recent" else
                sum(1 for t in self.found.values() if t.group == group))
            icon = {"All": "▦", "Recent": "🕘"}.get(group, catalog.GROUP_ICONS.get(group, "•"))
            b = ctk.CTkButton(side, text=f"{icon}  {group}  ({count})", anchor="w", height=30,
                              fg_color="transparent", hover_color=c["accent_dim"], text_color=c["text"],
                              command=lambda g=group: self.set_group(g))
            b.pack(fill="x", pady=1)
            self.group_buttons[group] = b
        self.grid_frame = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self.grid_frame.grid(row=0, column=1, sticky="nsew")
        self.tiles: dict[str, ctk.CTkButton] = {}
        self._job = None
        self._cols = 0
        self.grid_frame.bind("<Configure>", lambda e: self._later(80))
        self.set_group("All")

    def on_show(self) -> None:
        self._recents()
        try:
            self.search.focus_set()
        except tkinter.TclError:
            pass

    # --- tiles -----------------------------------------------------------------
    def _tile(self, tool) -> "Tile":
        tile = self.tiles.get(tool.name)
        if tile is None:
            tile = self.tiles[tool.name] = Tile(self.grid_frame, tool, self.open, self._menu)
        return tile

    def _later(self, ms: int = 160) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(ms, self.refresh)

    def set_group(self, group: str) -> None:
        self.group = group
        c = self.colors
        for name, b in self.group_buttons.items():
            b.configure(fg_color=c["accent_dim"] if name == group else "transparent")
        self.refresh()

    def visible(self) -> list:
        query = self.search.get().strip()
        if query:
            return catalog.search(query, self.found, limit=200)
        if self.group == "Recent":
            return catalog.recent(24, self.found)
        tools = [t for t in self.found.values() if self.group == "All" or t.group == self.group]
        return sorted(tools, key=lambda t: (catalog.groups(self.found).index(t.group)
                                            if t.group in catalog.groups(self.found) else 99, t.label().lower()))

    def refresh(self) -> None:
        self._job = None
        shown = self.visible()
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        width = max(self.grid_frame.winfo_width(), round(600 * scale))
        cols = max(1, width // round((TILE_WIDTH + 14) * scale))
        if [t.name for t in shown] == getattr(self, "_shown", None) and cols == self._cols:
            return  # a resize that changed nothing (it fires on every scroll-region update)
        self._shown = [t.name for t in shown]
        gap = round(5 * scale)
        with one_layout(self):
            for tile in self.tiles.values():
                tile.grid_forget()
            for i, tool in enumerate(shown):
                self._tile(tool).grid(row=i // cols, column=i % cols, padx=gap, pady=gap, sticky="w")
        self._cols = cols
        self.count.configure(text=f"{len(shown)} of {len(self.found)} commands")

    def _recents(self) -> None:
        for child in self.recent_row.winfo_children():
            child.destroy()
        items = catalog.recent(8, self.found)
        if not items:
            return
        label(self.recent_row, "Recently used:", size=11, muted=True).pack(side="left", padx=(0, 6))
        for tool in items:
            button(self.recent_row, f"{tool.icon} {tool.label()}", lambda t=tool: self.open(t), height=26,
                   font=ctk.CTkFont(size=11)).pack(side="left", padx=2)

    def _open_first(self) -> None:
        shown = self.visible()
        if shown:
            self.open(shown[0])

    def open(self, tool) -> None:
        self.app.open_tool(tool.name)

    def _menu(self, event, tool) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=lambda: self.open(tool))
        menu.add_command(label=f"Put {tool.usage.split()[0]} in the chat box",
                         command=lambda: self.app.prefill_chat(tool.usage.split()[0] + " "))
        menu.add_command(label="Copy the command", command=lambda: self._copy(tool.usage))
        menu.tk_popup(event.x_root, event.y_root)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)


class Tile(tkinter.Frame):
    """One command on the Tools page: icon, name, what it does; click to open.

    Plain Tk rather than a CTkButton: there are three hundred of these, and
    as rounded buttons with an emoji each the page took twelve seconds to open.
    """

    def __init__(self, parent, tool, on_open, on_menu):
        c = colors()
        scale = ctk.ScalingTracker.get_widget_scaling(parent)
        super().__init__(parent, bg=c["panel"], width=round(TILE_WIDTH * scale), height=round(58 * scale),
                         bd=0, highlightthickness=0, cursor="hand2")
        self.pack_propagate(False)
        self.tool = tool
        title, _, _ = text_font(self, 12, bold=True)
        small, _, _ = text_font(self, 11)
        pad = round(10 * scale)
        picture = emoji_image(self, tool.icon, 12)
        name = f"  {tool.label()}" if picture is not None else f"{tool.icon}  {tool.label()}"
        self.parts = [
            tkinter.Label(self, text=name, image=picture or "", compound="left" if picture is not None else "none",
                          font=title, fg=c["text"], bg=c["panel"], anchor="w", bd=0, cursor="hand2"),
            tkinter.Label(self, text=_short(tool.help), font=small, fg=c["muted"], bg=c["panel"],
                          anchor="w", bd=0, cursor="hand2"),
        ]
        self.parts[0].pack(fill="x", padx=pad, pady=(round(9 * scale), 0))
        self.parts[1].pack(fill="x", padx=pad)
        for widget in [self, *self.parts]:
            widget.bind("<Button-1>", lambda e: on_open(tool))
            widget.bind("<Button-3>", lambda e: on_menu(e, tool))
            widget.bind("<Enter>", lambda e: self._paint(c["accent_dim"]))
            widget.bind("<Leave>", lambda e: self._paint(c["panel"]))

    def _paint(self, colour: str) -> None:
        for widget in [self, *self.parts]:
            widget.configure(bg=colour)


def _short(text: str, limit: int = 34) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class Palette(ctk.CTkToplevel):
    """Ctrl+K: type a few letters, Enter. Pages, commands, or a typed command."""

    def __init__(self, app):
        super().__init__(app)
        c = colors()
        self.app = app
        self.found = catalog.tools(getattr(app.jarvis, "addons", None))
        self.configure(fg_color=c["panel"])
        self.title("Go to or run — JARVIS")
        self.resizable(False, False)
        width, height = 640, 430
        try:
            x = app.winfo_rootx() + max(0, (app.winfo_width() - width) // 2)
            y = app.winfo_rooty() + 70
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.transient(app)
        except tkinter.TclError:
            self.geometry(f"{width}x{height}")
        self.entry = ctk.CTkEntry(self, height=40, font=ctk.CTkFont(size=15), fg_color=c["bg"],
                                  placeholder_text="Type a page, a tool, or /command with arguments")
        self.entry.pack(fill="x", padx=12, pady=(12, 6))
        self.listbox = tkinter.Listbox(self, activestyle="none", bd=0, highlightthickness=0, font=("Segoe UI", 11),
                                       bg=c["bg"], fg=c["text"], selectbackground=c["accent_dim"],
                                       selectforeground=c["text"])
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        label(self, "↑ ↓ to choose · Enter to open · Esc to close", size=10, muted=True).pack(pady=(0, 8))
        self.items: list[tuple[str, object]] = []
        self.entry.bind("<KeyRelease>", self._typed)
        for widget in (self.entry, self.listbox):
            widget.bind("<Down>", lambda e: self._move(1))
            widget.bind("<Up>", lambda e: self._move(-1))
            widget.bind("<Return>", lambda e: self.choose())
            widget.bind("<Escape>", lambda e: self.destroy())
        self.listbox.bind("<Double-Button-1>", lambda e: self.choose())
        self.fill("")
        self.after(80, self._focus)

    def _focus(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.entry.focus_set()
        except tkinter.TclError:
            pass

    def _typed(self, event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape"}:
            return
        self.fill(self.entry.get())

    def fill(self, query: str) -> None:
        self.items = []
        q = query.strip()
        low = catalog._norm(q)
        if q.startswith("/") and " " in q:
            self.items.append((f"▶  Run “{q}” in the chat", ("run", q)))
        for page in PAGES:
            hay = catalog._norm(f"{page.label} {page.keywords} {page.key}")
            if not low or all(w in hay for w in low.lstrip("/").split()):
                self.items.append((f"{page.icon}  Go to {page.label}", ("page", page.key)))
        tools = catalog.search(q, self.found, limit=40) if q else catalog.recent(8, self.found)
        for tool in tools:
            self.items.append((f"{tool.icon}  {tool.label()}   —  {tool.usage.split()[0]}   {_short(tool.help, 48)}",
                               ("tool", tool.name)))
        if not q:
            self.items = self.items[:len(PAGES)] + self.items[len(PAGES):]
        self.listbox.delete(0, "end")
        for text, _ in self.items[:60]:
            self.listbox.insert("end", text)
        if self.items:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _move(self, step: int) -> str:
        if not self.items:
            return "break"
        current = self.listbox.curselection()
        index = (current[0] if current else 0) + step
        index = max(0, min(len(self.items[:60]) - 1, index))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)
        return "break"

    def choose(self) -> str:
        current = self.listbox.curselection()
        if not self.items:
            return "break"
        kind, value = self.items[current[0] if current else 0][1]
        self.destroy()
        if kind == "page":
            self.app._show_tab(value)
        elif kind == "tool":
            self.app.open_tool(value)
        elif kind == "run":
            self.app.run_in_chat(value)
        return "break"
