"""Media (10.0): your photos and videos as a gallery, a photo editor with a
live preview, blurring faces, and the audio clean-up tools.

The gallery reads Pictures (or any folder) newest first; thumbnails are made
on a worker thread — Pillow for photos, Windows' own thumbnails for videos —
so the page opens at once and fills in. The editor applies the same changes
/photoedit understands to a small preview while you move the sliders, and to
the full picture only when you save, so it never touches the original.
"""

from __future__ import annotations

import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from jarvis.ten import media
from ui.pages.base import Hub, button, label, open_path, plain, show_in_folder

THUMB = 132
PAGE_SIZE = 48
PREVIEW = (560, 380)


class MediaPage(Hub):
    key = "media"
    title = "Media"
    icon = "🎬"
    subtitle = "Your photos and videos, a photo editor, blurring faces, and cleaning up recordings."

    def build_body(self) -> None:
        c = self.colors
        self.folder = media.default_folder()
        self.kind = "all"
        self.files: list[Path] = []
        self.shown = 0
        self._thumbs: list = []          # PhotoImages must stay referenced
        self._loading = 0                # which load is current; older ones are dropped
        gallery = self.card("Gallery", "Newest first. Click a photo to edit it; double-click opens it.", "🖼",
                            span=2)
        bar = plain(gallery.inner)
        bar.pack(fill="x")
        self.folder_label = label(bar, "", size=11, muted=True)
        self.folder_label.pack(side="left")
        button(bar, "Change folder…", self.pick_folder, height=26).pack(side="right")
        self.filter = ctk.CTkSegmentedButton(bar, values=["All", "Photos", "Videos"], command=self.set_kind)
        self.filter.set("All")
        self.filter.pack(side="right", padx=8)
        self.grid_box = plain(gallery.inner)
        self.grid_box.pack(fill="x", pady=(8, 0))
        self.more = button(gallery.inner, "Show more", self.show_more, height=26)
        self.status = label(gallery.inner, "", size=11, muted=True)
        self.status.pack(anchor="w")

        editor = self.card("Photo editor", "Changes show at once; Save keeps the original and writes a copy.",
                           "🎨", span=2)
        body = plain(editor.inner)
        body.pack(fill="x")
        self.canvas = tkinter.Canvas(body, width=PREVIEW[0], height=PREVIEW[1], bg=c["bg"], highlightthickness=0)
        self.canvas.pack(side="left")
        self.canvas_text = self.canvas.create_text(PREVIEW[0] // 2, PREVIEW[1] // 2, fill=c["muted"],
                                                   text="Click a photo in the gallery, or Open a photo…")
        side = plain(body)
        side.pack(side="left", fill="both", expand=True, padx=(14, 0))
        row = plain(side)
        row.pack(fill="x")
        button(row, "Open a photo…", self.pick_photo, accent=True).pack(side="left")
        button(row, "⟲", lambda: self.turn(-90), width=34).pack(side="left", padx=(6, 0))
        button(row, "⟳", lambda: self.turn(90), width=34).pack(side="left", padx=4)
        button(row, "⇋", self.mirror, width=34).pack(side="left")
        button(row, "▢", self.square, width=34).pack(side="left", padx=4)
        self.sliders: dict[str, ctk.CTkSlider] = {}
        for name in ("brightness", "contrast", "saturation", "sharpen"):
            line = plain(side)
            line.pack(fill="x", pady=1)
            label(line, name.capitalize(), size=11, muted=True, width=80).pack(side="left")
            slider = ctk.CTkSlider(line, from_=0, to=2, number_of_steps=40, command=lambda v: self.changed())
            slider.set(1)
            slider.pack(side="left", fill="x", expand=True)
            self.sliders[name] = slider
        filters = plain(side)
        filters.pack(fill="x", pady=(6, 0))
        self.filter_var = tkinter.StringVar(value="none")
        ctk.CTkOptionMenu(filters, values=["none", *media.FILTERS], variable=self.filter_var, width=120,
                          fg_color=c["bg"], button_color=c["accent_dim"], command=lambda v: self.changed()).pack(
            side="left")
        button(filters, "✨ Auto", self.auto, height=28).pack(side="left", padx=6)
        button(filters, "Reset", self.reset, height=28).pack(side="left")
        actions = plain(side)
        actions.pack(fill="x", pady=(10, 0))
        button(actions, "😶 Blur faces", self.blur_faces, height=30).pack(side="left")
        button(actions, "💾 Save copy", self.save, accent=True, height=30).pack(side="left", padx=6)
        self.editor_note = label(side, "", size=11, muted=True, wrap=300)
        self.editor_note.pack(anchor="w", pady=(6, 0))
        self.photo: Path | None = None
        self.base_image = None
        self._preview = None
        self._job = None
        self.reset(draw=False)

        self.section("Clean up a recording")
        self.tools("denoise", "cutsilence", "ringtone")
        self.section("In words")
        self.tools("photoedit", "blurfaces", "imagestyle", "media")

    def on_show(self) -> None:
        if not self.files:
            self.load()

    # --- gallery --------------------------------------------------------------------------------
    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=str(self.folder))
        if folder:
            self.folder = Path(folder)
            self.load()

    def set_kind(self, value: str) -> None:
        self.kind = value.lower()
        self.load()

    def load(self) -> None:
        self._loading += 1
        ticket = self._loading
        self.folder_label.configure(text=str(self.folder))
        self.status.configure(text="Looking…")
        for child in self.grid_box.winfo_children():
            child.destroy()
        self._thumbs = []
        self.shown = 0

        def found(files):
            if ticket != self._loading:
                return
            self.files = files if isinstance(files, list) else []
            if not self.files:
                self.status.configure(text=f"No {'photos or videos' if self.kind == 'all' else self.kind} here.")
                self.more.pack_forget()
                return
            self.show_more()

        self.run(lambda: media.media_files(self.folder, self.kind), found)

    def show_more(self) -> None:
        batch = self.files[self.shown:self.shown + PAGE_SIZE]
        first = self.shown
        self.shown += len(batch)
        ticket = self._loading
        tiles = [self._tile(path, first + i) for i, path in enumerate(batch)]
        self.status.configure(text=f"{self.shown} of {len(self.files)} shown")
        if self.shown < len(self.files):
            self.more.pack(anchor="w", pady=(6, 0), before=self.status)
        else:
            self.more.pack_forget()

        def made(pictures):
            if ticket != self._loading or not isinstance(pictures, dict):
                return
            from PIL import ImageTk

            for path, tile in zip(batch, tiles):
                picture = pictures.get(path)
                if picture is None:
                    continue
                try:
                    image = ImageTk.PhotoImage(picture, master=self)
                    tile.configure(image=image, text="", width=THUMB, height=THUMB)
                    self._thumbs.append(image)
                except tkinter.TclError:
                    return

        self.run(lambda: make_thumbnails(batch), made)

    def _tile(self, path: Path, index: int) -> tkinter.Label:
        c = self.colors
        per_row = max(3, (self.grid_box.winfo_width() or 900) // (THUMB + 8))
        icon = "🎬" if media.kind_of(path) == "video" else "🖼"
        tile = tkinter.Label(self.grid_box, text=f"{icon}\n{path.name[:16]}", bg=c["bg"], fg=c["muted"],
                             width=16, height=7, cursor="hand2", bd=0, wraplength=THUMB)
        tile.grid(row=index // per_row, column=index % per_row, padx=3, pady=3)
        tile.bind("<Button-1>", lambda e, p=path: self.chose(p))
        tile.bind("<Double-Button-1>", lambda e, p=path: open_path(p))
        tile.bind("<Button-3>", lambda e, p=path: self._menu(e, p))
        return tile

    def _menu(self, event, path: Path) -> None:
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=lambda: open_path(path))
        menu.add_command(label="Show in folder", command=lambda: show_in_folder(path))
        if media.kind_of(path) == "photo":
            menu.add_command(label="Edit", command=lambda: self.chose(path))
            menu.add_command(label="Blur faces", command=lambda: (self.chose(path), self.blur_faces()))
        menu.tk_popup(event.x_root, event.y_root)

    def chose(self, path: Path) -> None:
        if media.kind_of(path) == "photo":
            self.open_photo(path)
        else:
            open_path(path)

    # --- editor ---------------------------------------------------------------------------------
    def pick_photo(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=list(media.PICTURE_TYPES) + [("All files", "*.*")])
        if path:
            self.open_photo(Path(path))

    def open_photo(self, path: Path) -> None:
        from PIL import Image, ImageOps

        try:
            with Image.open(path) as image:
                image.draft("RGB", (PREVIEW[0] * 2, PREVIEW[1] * 2))   # JPEGs decode small, fast
                picture = ImageOps.exif_transpose(image)
                picture.thumbnail(PREVIEW, Image.LANCZOS)
                self.base_image = picture.convert("RGBA" if "A" in picture.getbands() else "RGB")
        except OSError:
            self.editor_note.configure(text=f"I can't open {path.name} as a picture.")
            return
        self.photo = path
        self.reset()
        self.editor_note.configure(text=path.name)

    def reset(self, draw: bool = True) -> None:
        self.rotation = 0
        self.mirrored = False
        self.squared = False
        self.auto_on = False
        for slider in self.sliders.values():
            slider.set(1)
        self.filter_var.set("none")
        if draw:
            self.changed()

    def turn(self, degrees: int) -> None:
        self.rotation = (self.rotation + degrees) % 360
        self.changed()

    def mirror(self) -> None:
        self.mirrored = not self.mirrored
        self.changed()

    def square(self) -> None:
        self.squared = not self.squared
        self.changed()

    def auto(self) -> None:
        self.auto_on = not self.auto_on
        self.changed()

    def ops(self) -> list[tuple[str, float | None]]:
        """What the controls say, in the words /photoedit understands."""
        out: list[tuple[str, float | None]] = []
        if self.rotation:
            out.append(("rotate", float(self.rotation)))
        if self.mirrored:
            out.append(("flip", None))
        if self.squared:
            out.append(("square", None))
        if self.auto_on:
            out.append(("auto", None))
        for name, slider in self.sliders.items():
            value = round(float(slider.get()), 2)
            if abs(value - 1) > 0.01:
                out.append((name, value * 2 if name == "sharpen" else value))
        if self.filter_var.get() != "none":
            out.append((self.filter_var.get(), None))
        return out

    def changed(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tkinter.TclError:
                pass
        self._job = self.after(40, self.draw)

    def draw(self) -> None:
        self._job = None
        if self.base_image is None:
            return
        from PIL import ImageTk

        picture = media.apply_ops(self.base_image, self.ops())
        picture.thumbnail(PREVIEW)
        self._preview = ImageTk.PhotoImage(picture, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(PREVIEW[0] // 2, PREVIEW[1] // 2, image=self._preview)

    def save(self) -> None:
        if self.photo is None:
            self.editor_note.configure(text="Open a photo first.")
            return
        ops = self.ops() or [("auto", None)]
        source = self.photo

        def work():
            from PIL import Image

            with Image.open(source) as image:
                image.load()
                return media.save_picture(media.apply_ops(image, ops), media.edited_path(source))

        self.editor_note.configure(text="Saving…")
        self.run(work, lambda path: self.editor_note.configure(text=f"Saved a copy: {Path(str(path)).name}"),
                 lambda exc: self.editor_note.configure(text=f"Couldn't save: {exc}"))

    def blur_faces(self) -> None:
        if self.photo is None:
            self.editor_note.configure(text="Open a photo first.")
            return
        self.editor_note.configure(text="Looking for faces…")

        def done(result):
            target, count = result
            self.editor_note.configure(text=f"Blurred {count} face(s) — saved {Path(target).name}" if count else
                                       "No faces found.")
            if count:
                self.open_photo(Path(target))
                self.editor_note.configure(text=f"Blurred {count} face(s) — saved {Path(target).name}")

        self.run(lambda: media.blur_faces(self.photo), done,
                 lambda exc: self.editor_note.configure(text=f"😶 {exc}"))


def make_thumbnails(paths: list[Path]) -> dict:
    """{path: small Pillow image} — photos by Pillow, videos by Windows."""
    from PIL import Image, ImageOps

    out: dict = {}
    videos = []
    for path in paths:
        if media.kind_of(path) == "video":
            videos.append(path)
            continue
        try:
            with Image.open(path) as image:
                image.draft("RGB", (THUMB * 2, THUMB * 2))
                picture = ImageOps.exif_transpose(image)
                picture.thumbnail((THUMB, THUMB))
                out[path] = picture.convert("RGB")
        except (OSError, ValueError):
            continue
    if videos:
        try:
            import tempfile

            from jarvis import winrt

            folder = Path(tempfile.mkdtemp(prefix="jarvis-thumbs-"))
            for video, thumb in winrt.thumbnails(videos, folder, THUMB * 2).items():
                with Image.open(thumb) as image:
                    picture = image.convert("RGB")
                    picture.thumbnail((THUMB, THUMB))
                    out[video] = picture
        except Exception:
            pass        # videos keep their 🎬 tile
    # winrt resolves paths; match them back to the ones asked for
    resolved = {Path(p).resolve(): p for p in paths}
    return {resolved.get(Path(k).resolve(), k): v for k, v in out.items()}
