"""Travel and Map (10.0).

The Map page draws OpenStreetMap tiles on a canvas — drag to move, wheel to
zoom, right-click a spot to save it or look around it — with search,
nearby places and your saved places as pins. Tiles load on a worker and
are kept on disk, so the map only fetches what you look at, once a week.
The Travel page plans trips: budget, itinerary, documents, jet lag.
"""

from __future__ import annotations

import tkinter


import customtkinter as ctk

from jarvis import travel
from ui.pages.base import Hub, Page, background, button, label, plain, text_font

TILE = travel.TILE


class MapView(tkinter.Canvas):
    """A slippy map: OpenStreetMap tiles, pins, dragging and zooming."""

    def __init__(self, parent, colours: dict, on_right_click=None) -> None:
        super().__init__(parent, bg="#d5d8db", highlightthickness=0, cursor="fleur")
        self.colours = colours
        self.zoom = 12
        self.center = (41.015, 28.979)          # Istanbul until told otherwise
        self.pins: list[dict] = []
        self.images: dict[tuple, object] = {}
        self.pending: set[tuple] = set()

        self.on_right_click = on_right_click
        self._drag = None
        self._redraw = None
        self.bind("<Configure>", lambda e: self.schedule())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Double-Button-1>", lambda e: self.zoom_at(e.x, e.y, 1))
        self.bind("<Button-3>", self._right)

    # coordinates
    def _origin(self) -> tuple[float, float]:
        cx, cy = travel.to_pixels(*self.center, self.zoom)
        return cx - self.winfo_width() / 2, cy - self.winfo_height() / 2

    def screen(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = travel.to_pixels(lat, lon, self.zoom)
        ox, oy = self._origin()
        return x - ox, y - oy

    def latlon(self, sx: float, sy: float) -> tuple[float, float]:
        ox, oy = self._origin()
        return travel.to_latlon(ox + sx, oy + sy, self.zoom)

    # interaction
    def _press(self, event) -> None:
        self._drag = (event.x, event.y)

    def _move(self, event) -> None:
        if self._drag is None:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self._drag = (event.x, event.y)
        cx, cy = travel.to_pixels(*self.center, self.zoom)
        self.center = travel.to_latlon(cx - dx, cy - dy, self.zoom)
        self.draw()

    def _wheel(self, event) -> None:
        self.zoom_at(event.x, event.y, 1 if event.delta > 0 else -1)

    def zoom_at(self, sx: float, sy: float, step: int) -> None:
        new = max(3, min(19, self.zoom + step))
        if new == self.zoom:
            return
        lat, lon = self.latlon(sx, sy)
        self.zoom = new
        # Keep the point under the mouse where it was.
        px, py = travel.to_pixels(lat, lon, self.zoom)
        cx = px - sx + self.winfo_width() / 2
        cy = py - sy + self.winfo_height() / 2
        self.center = travel.to_latlon(cx, cy, self.zoom)
        self.draw()

    def _right(self, event) -> None:
        if self.on_right_click is not None:
            self.on_right_click(event, *self.latlon(event.x, event.y))

    def go(self, lat: float, lon: float, zoom: int | None = None) -> None:
        self.center = (lat, lon)
        if zoom is not None:
            self.zoom = zoom
        self.draw()

    # drawing
    def schedule(self) -> None:
        if self._redraw is None:
            self._redraw = self.after(30, self.draw)

    def draw(self) -> None:
        self._redraw = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        self.delete("all")
        ox, oy = self._origin()
        n = 2 ** self.zoom
        for tx in range(int(ox // TILE), int((ox + w) // TILE) + 1):
            for ty in range(int(oy // TILE), int((oy + h) // TILE) + 1):
                if not 0 <= ty < n:
                    continue
                key = (self.zoom, tx % n, ty)
                x, y = tx * TILE - ox, ty * TILE - oy
                image = self.images.get(key)
                if image is not None:
                    self.create_image(x, y, image=image, anchor="nw")
                else:
                    self.create_rectangle(x, y, x + TILE, y + TILE, fill="#e5e3df", outline="#d5d3cf")
                    self._fetch(key)
        for pin in self.pins:
            sx, sy = self.screen(pin["lat"], pin["lon"])
            if -20 < sx < w + 20 and -20 < sy < h + 20:
                colour = pin.get("colour", "#e11d48")
                self.create_oval(sx - 7, sy - 7, sx + 7, sy + 7, fill=colour, outline="white", width=2)
                if pin.get("label"):
                    self.create_text(sx + 11, sy, text=pin["label"], anchor="w", fill="#111827",
                                     font=("Segoe UI", 9, "bold"))
        self.create_rectangle(w - 182, h - 18, w, h, fill="#ffffff", outline="", stipple="gray75")
        self.create_text(w - 4, h - 3, text="© OpenStreetMap contributors", anchor="se", fill="#374151",
                         font=("Segoe UI", 8))

    def _fetch(self, key: tuple) -> None:
        if key in self.pending:
            return
        self.pending.add(key)

        def show(path):
            self.pending.discard(key)
            if not path or isinstance(path, str):
                return
            try:
                from PIL import Image, ImageTk

                with Image.open(path) as picture:
                    self.images[key] = ImageTk.PhotoImage(picture.convert("RGB"), master=self)
                if len(self.images) > 400:              # keep memory in check on long pans
                    for old in list(self.images)[:100]:
                        self.images.pop(old, None)
                self.schedule()
            except Exception:
                pass

        # travel.tile limits itself to four downloads at a time.
        background(self, lambda: travel.tile(*key), show, lambda exc: self.pending.discard(key))


class MapPage(Page):
    key = "map"
    title = "Map"
    icon = "🗺"

    def build(self) -> None:
        c = self.colors
        side = ctk.CTkFrame(self, width=300, fg_color=c["panel"], corner_radius=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        label(side, "🗺  Map", size=20, bold=True, text_color=c["accent"]).pack(anchor="w", padx=14, pady=(14, 6))
        self.search = ctk.CTkEntry(side, placeholder_text="Search a place or address…", fg_color=c["bg"])
        self.search.pack(fill="x", padx=14)
        self.search.bind("<Return>", lambda e: self.find())
        label(side, "Nearby", size=12, bold=True).pack(anchor="w", padx=14, pady=(12, 2))
        grid = plain(side)
        grid.pack(fill="x", padx=12)
        for i, kind in enumerate(("pharmacy", "cafe", "restaurant", "atm", "fuel", "supermarket", "hospital",
                                  "hotel")):
            button(grid, f"{travel.NEARBY[kind][2]} {kind}", lambda k=kind: self.around(k), height=26,
                   font=ctk.CTkFont(size=11)).grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        self.status = label(side, "", size=11, muted=True, wrap=270)
        self.status.pack(anchor="w", padx=14, pady=(8, 0))
        self.results = tkinter.Listbox(side, bd=0, highlightthickness=0, activestyle="none", bg=c["bg"], fg=c["text"],
                                       font=text_font(self, 11)[0], selectbackground=c["accent_dim"])
        self.results.pack(fill="both", expand=True, padx=14, pady=(6, 6))
        self.results.bind("<<ListboxSelect>>", lambda e: self.pick())
        row = plain(side)
        row.pack(fill="x", padx=14, pady=(0, 12))
        button(row, "⭐ Saved places", self.show_saved, height=28).pack(side="left")
        button(row, "⌂ Home", self.go_home, height=28).pack(side="left", padx=6)
        self.map = MapView(self, c, on_right_click=self.menu)
        self.map.pack(side="left", fill="both", expand=True)
        self.rows: list[dict] = []
        self.here = None

    def on_show(self) -> None:
        self.after(60, self.map.draw)
        if self.here is None:
            self.go_home()

    def open_target(self, part: str) -> None:
        self.search.delete(0, "end")
        self.search.insert(0, part)
        self.find()

    def go_home(self) -> None:
        def done(found):
            if isinstance(found, tuple):
                self.here = (found[1], found[2])
                self.map.go(found[1], found[2], 14)
                self.status.configure(text=f"Around {found[0]}. Right-click the map to save a spot.")
            else:
                self.here = self.map.center
                self.status.configure(text="Set your city in Settings, or save a place called Home.")
            self.show_saved()

        self.run(travel.where_am_i, done, lambda exc: done(None))

    def _list(self, rows: list[dict], text: str) -> None:
        self.rows = rows
        self.results.delete(0, "end")
        for row in rows:
            distance = f"{travel.show_distance(row['distance'])}  " if "distance" in row else ""
            self.results.insert("end", f"{distance}{row.get('icon', '📍')} {row['name']}")
        self.status.configure(text=text)
        self.map.pins = [{"lat": r["lat"], "lon": r["lon"], "label": r["name"][:24],
                          "colour": "#f59e0b" if r.get("saved") else "#e11d48"} for r in rows]
        self.map.draw()

    def find(self) -> None:
        query = self.search.get().strip()
        if not query:
            return
        self.status.configure(text="Searching…")

        def done(rows):
            if not isinstance(rows, list) or not rows:
                self.status.configure(text=f"Nothing found for {query}." if isinstance(rows, list) else str(rows))
                return
            self.map.go(rows[0]["lat"], rows[0]["lon"], 15)
            self.here = (rows[0]["lat"], rows[0]["lon"])
            self._list(rows, f"{len(rows)} result(s) for {query}")

        self.run(lambda: travel.search(query), done, lambda exc: self.status.configure(text=str(exc)))

    def around(self, kind: str, at: tuple | None = None) -> None:
        lat, lon = at or self.map.center
        self.status.configure(text=f"Looking for {travel.PLURAL[kind]}…")

        def done(rows):
            if not isinstance(rows, list):
                self.status.configure(text=str(rows))
                return
            self._list(rows, f"{len(rows)} {travel.PLURAL[kind]} within about a kilometre"
                       if rows else f"No {travel.NEARBY[kind][1]} close by.")

        self.run(lambda: travel.nearby(lat, lon, kind), done, lambda exc: self.status.configure(text=str(exc)))

    def pick(self) -> None:
        chosen = self.results.curselection()
        if chosen and chosen[0] < len(self.rows):
            row = self.rows[chosen[0]]
            self.map.go(row["lat"], row["lon"], max(self.map.zoom, 16))
            details = " · ".join(x for x in (row.get("address"), row.get("hours"), row.get("phone"),
                                              row.get("note")) if x)
            self.status.configure(text=f"{row['name']}" + (f"\n{details}" if details else ""))

    def show_saved(self) -> None:
        rows = [dict(r, icon="⭐", saved=True) for r in travel.PLACES.load()]
        if self.here is not None:
            for row in rows:
                row["distance"] = travel.distance_m(self.here[0], self.here[1], row["lat"], row["lon"])
        self._list(rows, f"{len(rows)} saved place(s)" if rows else "No saved places yet — right-click the map.")

    def menu(self, event, lat: float, lon: float) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="⭐ Save this place…", command=lambda: self.save_here(lat, lon))
        nearby = tkinter.Menu(menu, tearoff=0)
        for kind in ("pharmacy", "cafe", "restaurant", "atm", "fuel", "supermarket"):
            nearby.add_command(label=f"{travel.NEARBY[kind][2]} {kind}", command=lambda k=kind: self.around(k, (lat, lon)))
        menu.add_cascade(label="Find nearby", menu=nearby)
        menu.add_command(label=f"Copy {lat:.5f}, {lon:.5f}", command=lambda: (self.clipboard_clear(),
                                                                             self.clipboard_append(f"{lat:.6f}, {lon:.6f}")))
        menu.tk_popup(event.x_root, event.y_root)

    def save_here(self, lat: float, lon: float) -> None:
        name = (ctk.CTkInputDialog(text="Name this place:", title="Save place").get_input() or "").strip()
        if name:
            travel.save_place(name, lat, lon)
            self.show_saved()


class TravelPage(Hub):
    key = "travel"
    title = "Travel"
    icon = "🧭"
    subtitle = "Plan a trip: what it costs, a day-by-day plan in your calendar, the documents, and beating jet lag."

    def build_body(self) -> None:
        docs = self.card("Documents and essentials", "Tick as you pack — saved for this trip.", "🛂", span=2)
        row = plain(docs.inner)
        row.pack(fill="x")
        self.trip = ctk.CTkEntry(row, placeholder_text="Trip name", width=220, fg_color=self.colors["bg"])
        self.trip.insert(0, "My trip")
        self.trip.pack(side="left")
        self.trip.bind("<Return>", lambda e: self.show_docs())
        button(row, "Load", self.show_docs, height=28).pack(side="left", padx=6)
        self.progress = label(row, "", size=12, bold=True)
        self.progress.pack(side="left", padx=8)
        self.docs_box = plain(docs.inner)
        self.docs_box.pack(fill="x", pady=(6, 0))
        self.section("Plan")
        self.tools("tripbudget", "itinerary", "jetlag", "pack")
        self.section("Around you")
        self.tools("nearby", "places", "map", "convert")

    def on_show(self) -> None:
        self.show_docs()

    def show_docs(self) -> None:
        for child in self.docs_box.winfo_children():
            child.destroy()
        trip = self.trip.get().strip() or "My trip"
        done = set(travel.TRAVEL_DOCS.load().get(trip, []))
        n, total = 0, sum(len(v) for v in travel.DOCS.values())
        columns = plain(self.docs_box)
        columns.pack(fill="x")
        for col, (group, things) in enumerate(travel.DOCS.items()):
            box = plain(columns)
            box.grid(row=0, column=col, sticky="nw", padx=(0, 18))
            label(box, group, size=12, bold=True).pack(anchor="w")
            for thing in things:
                var = tkinter.BooleanVar(value=n in done)
                ctk.CTkCheckBox(box, text=thing, variable=var,
                                command=lambda i=n, v=var: self.tick(i, v.get())).pack(anchor="w", pady=1)
                n += 1
        self.progress.configure(text=f"{len(done)}/{total} ready")

    def tick(self, index: int, on: bool) -> None:
        trip = self.trip.get().strip() or "My trip"
        state = travel.TRAVEL_DOCS.load()
        items = set(state.get(trip, []))
        state[trip] = sorted(items | {index} if on else items - {index})
        travel.TRAVEL_DOCS.save(state)
        total = sum(len(v) for v in travel.DOCS.values())
        self.progress.configure(text=f"{len(state[trip])}/{total} ready")
