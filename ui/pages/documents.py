"""Documents (10.0): a spreadsheet viewer, PDF pages you can see and drag
into order, a signature pad, template galleries, and every document tool as
a form."""

from __future__ import annotations

import shutil
import tkinter
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk
from PIL import Image, ImageDraw

from jarvis import kit
from jarvis.ten import office
from ui.pages.base import Card, Hub, ResultView, button, label, open_path, show_in_folder


class DocumentsPage(Hub):
    key = "documents"
    title = "Documents"
    icon = "📄"
    subtitle = "PDF, Word and Excel tools. Pick a file, choose what to do — every result opens with one click."

    def build_body(self) -> None:
        self.section("Look at a file")
        self._viewer()
        self._recent()
        self.section("PDF pages — see them, click to pick, then act")
        self._pdf_pages()
        self._signature()
        self.tools("pdfcompress", "pdf2word", "pdfnumber", "pdfwatermark", "pdfform", "pdfrotate", "pdfpages",
                   "pdfmerge", "pdfsplit")
        self.section("Excel")
        self.tools("excel", "exceledit", "formula", "xlchart", "data")
        self.section("Word and writing")
        self._gallery("Document templates", "Pick one, fill in the details, get Word and PDF.", "🗃",
                      [(k, v[0]) for k, v in office.DOC_TEMPLATES.items()], "doctemplate", "kind")
        self._gallery("Email templates", "Ready emails in English and Turkish — fill in the blanks.", "📧",
                      [(k, v[0]) for k, v in office.all_email_templates().items()], "emailtpl", "name")
        self.tools("makedoc", "mailmerge", "handout", "wordcount", "readability", "similarity", "print",
                   "fileconvert", "grammar")

    # --- spreadsheet viewer -------------------------------------------------------
    def _viewer(self) -> None:
        c = self.colors
        card = self.card("Spreadsheet viewer", "Excel or CSV: sort by clicking a heading, filter by typing.", "▦",
                         span=self.columns)
        bar = ctk.CTkFrame(card.inner, fg_color="transparent")
        bar.pack(fill="x")
        button(bar, "Open a spreadsheet…", self.open_sheet, accent=True).pack(side="left")
        self.sheet_menu = ctk.CTkOptionMenu(bar, values=["—"], width=150, command=lambda s: self.load_sheet(s),
                                            fg_color=c["bg"], button_color=c["accent_dim"])
        self.sheet_menu.pack(side="left", padx=6)
        self.filter = ctk.CTkEntry(bar, placeholder_text="Filter rows…", width=200, fg_color=c["bg"])
        self.filter.pack(side="left")
        self.filter.bind("<KeyRelease>", lambda e: self.fill_tree())
        self.sheet_info = label(bar, "", size=11, muted=True)
        self.sheet_info.pack(side="left", padx=10)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tkinter.TclError:
            pass
        style.configure("Jarvis.Treeview", background=c["bg"], fieldbackground=c["bg"], foreground=c["text"],
                        rowheight=24, borderwidth=0)
        style.configure("Jarvis.Treeview.Heading", background=c["panel"], foreground=c["accent"], relief="flat")
        style.map("Jarvis.Treeview", background=[("selected", c["accent_dim"])])
        holder = tkinter.Frame(card.inner, bg=c["bg"])
        holder.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(holder, style="Jarvis.Treeview", show="headings", height=12)
        ys = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.sheet_stats = label(card.inner, "", size=11, muted=True, wrap=1000)
        self.sheet_stats.pack(anchor="w")
        self.sheet_path: Path | None = None
        self.headers: list[str] = []
        self.rows: list[list] = []
        self.sort_col: tuple[int, bool] | None = None

    def open_sheet(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(parent=self, filetypes=list(office.XL_TYPES) + [("All", "*.*")])
        if not path:
            return
        self.sheet_path = Path(path)
        sheets = [self.sheet_path.stem]
        if self.sheet_path.suffix.lower() != ".csv":
            from openpyxl import load_workbook

            try:
                wb = load_workbook(self.sheet_path, read_only=True)
                sheets = list(wb.sheetnames)
                wb.close()
            except Exception as exc:
                self.sheet_info.configure(text=f"Couldn't open: {exc}")
                return
        self.sheet_menu.configure(values=sheets)
        self.sheet_menu.set(sheets[0])
        self.load_sheet(sheets[0])

    def load_sheet(self, name: str) -> None:
        if self.sheet_path is None:
            return
        try:
            self.headers, self.rows, _ = office.read_table(self.sheet_path, name, limit=20000)
        except Exception as exc:
            self.sheet_info.configure(text=f"Couldn't read: {exc}")
            return
        self.sort_col = None
        self.tree.configure(columns=[str(i) for i in range(len(self.headers))])
        for i, h in enumerate(self.headers):
            self.tree.heading(str(i), text=h, command=lambda n=i: self.sort(n))
            self.tree.column(str(i), width=max(80, min(260, 9 * len(h) + 30)), stretch=False)
        self.fill_tree()

    def sort(self, column: int) -> None:
        desc = bool(self.sort_col and self.sort_col[0] == column and not self.sort_col[1])
        self.sort_col = (column, desc)

        def key(row):
            value = row[column] if column < len(row) else None
            return (value is None, value if isinstance(value, (int, float)) else str(value).lower())

        try:
            self.rows.sort(key=key, reverse=desc)
        except TypeError:
            self.rows.sort(key=lambda r: str(r[column]).lower(), reverse=desc)
        self.fill_tree()

    def fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        words = self.filter.get().lower().split()
        shown = 0
        for row in self.rows:
            if words and not all(w in " ".join(str(c) for c in row).lower() for w in words):
                continue
            self.tree.insert("", "end", values=["" if c is None else c for c in row])
            shown += 1
            if shown >= 5000:
                break
        self.sheet_info.configure(text=f"{self.sheet_path.name if self.sheet_path else ''} · {shown} of "
                                       f"{len(self.rows)} rows · {len(self.headers)} columns")
        sums = []
        for i, h in enumerate(self.headers):
            numbers = [r[i] for r in self.rows if i < len(r) and isinstance(r[i], (int, float))]
            if numbers and len(numbers) >= max(1, len(self.rows) // 2):
                sums.append(f"{h}: total {sum(numbers):,.2f}, average {sum(numbers) / len(numbers):,.2f}")
        self.sheet_stats.configure(text="  ·  ".join(sums[:6]))

    # --- recent documents -----------------------------------------------------------
    def _recent(self) -> None:
        card = self.card("Recent documents", "What you opened or made lately.", "🕘", span=self.columns)
        self.recent_box = ctk.CTkFrame(card.inner, fg_color="transparent")
        self.recent_box.pack(fill="x")
        button(card.inner, "↻ Refresh", self.fill_recent, height=24).pack(anchor="e")

    def on_show(self) -> None:
        self.fill_recent()

    def fill_recent(self) -> None:
        for child in self.recent_box.winfo_children():
            child.destroy()

        def work():
            return [(t, office.resolve_link(p)) for t, p in office.recent_documents(16)]

        def done(items):
            if isinstance(items, str):
                return
            for i, (_t, path) in enumerate(items):
                b = ctk.CTkButton(self.recent_box, text=f"📄 {path.name[:34]}", anchor="w", width=230, height=28,
                                  fg_color=self.colors["bg"], hover_color=self.colors["accent_dim"],
                                  text_color=self.colors["text"], command=lambda p=path: open_path(p))
                b.grid(row=i // 4, column=i % 4, padx=3, pady=2, sticky="w")
                b.bind("<Button-3>", lambda e, p=path: show_in_folder(p))
            if not items:
                label(self.recent_box, "Nothing recent yet.", muted=True).grid(row=0, column=0)

        self.run(work, done)

    # --- PDF pages --------------------------------------------------------------------
    def _pdf_pages(self) -> None:
        c = self.colors
        card = self.card("PDF pages", "Open a PDF to see every page. Click pages to select them.", "📑",
                         span=self.columns)
        bar = ctk.CTkFrame(card.inner, fg_color="transparent")
        bar.pack(fill="x")
        button(bar, "Open a PDF…", self.open_pdf, accent=True).pack(side="left")
        for text, command in (("⟲ Rotate", lambda: self.pdf_action("rotate")),
                              ("◀ Move", lambda: self.move(-1)), ("Move ▶", lambda: self.move(1)),
                              ("🗑 Delete", lambda: self.pdf_action("delete")),
                              ("⇪ Extract", lambda: self.pdf_action("extract")),
                              ("💾 Save as new PDF", lambda: self.pdf_action("save"))):
            button(bar, text, command, height=28).pack(side="left", padx=3)
        self.pdf_note = label(bar, "", size=11, muted=True)
        self.pdf_note.pack(side="left", padx=8)
        self.thumbs = ctk.CTkFrame(card.inner, fg_color=c["bg"], corner_radius=8, height=40)
        self.thumbs.pack(fill="x", pady=6)
        self.pdf_result = ResultView(card.inner, self.app)
        self.pdf_result.pack(fill="x")
        self.pdf_path: Path | None = None
        self.order: list[int] = []
        self.rotation: dict[int, int] = {}
        self.picked: set[int] = set()
        self._thumb_images: dict[int, object] = {}
        self._thumb_files: dict[int, Path] = {}

    def open_pdf(self, path: str | None = None) -> None:
        from jarvis import winrt

        path = path or filedialog.askopenfilename(parent=self, filetypes=list(office.PDF_TYPES))
        if not path:
            return
        self.pdf_path = Path(path)
        self.pdf_note.configure(text="Reading pages…")
        folder = kit.output_dir("documents") / ".pages" / kit.stamp()

        def work():
            return winrt.pdf_pages(self.pdf_path, folder, None, 220)

        def done(pages):
            if isinstance(pages, str):
                self.pdf_note.configure(text=pages[:120])
                return
            self._thumb_files = {p["page"]: p["path"] for p in pages}
            self.order = [p["page"] for p in pages]
            self.rotation = {}
            self.picked = set()
            self.draw_thumbs()
            self.pdf_note.configure(text=f"{self.pdf_path.name}: {len(pages)} page(s)")

        self.run(work, done, lambda e: self.pdf_note.configure(text=f"Couldn't read it: {e}"))

    def draw_thumbs(self) -> None:
        c = self.colors
        for child in self.thumbs.winfo_children():
            child.destroy()
        self._thumb_images = {}
        per_row = 8
        for i, page in enumerate(self.order):
            path = self._thumb_files.get(page)
            frame = ctk.CTkFrame(self.thumbs, fg_color=c["accent"] if page in self.picked else c["panel"],
                                 corner_radius=6)
            frame.grid(row=i // per_row, column=i % per_row, padx=4, pady=4)
            try:
                with Image.open(path) as im:
                    im = im.rotate(-self.rotation.get(page, 0), expand=True)
                    im.thumbnail((110, 150))
                    image = ctk.CTkImage(im.copy(), size=im.size)
                self._thumb_images[page] = image
                b = ctk.CTkButton(frame, image=image, text=f"{page}", compound="top", fg_color="transparent",
                                  hover_color=c["accent_dim"], text_color=c["text"], width=120,
                                  command=lambda p=page: self.toggle(p))
            except Exception:
                b = ctk.CTkButton(frame, text=f"Page {page}", width=120, height=150, command=lambda p=page:
                                  self.toggle(p))
            b.pack(padx=3, pady=3)

    def toggle(self, page: int) -> None:
        self.picked ^= {page}
        self.draw_thumbs()

    def move(self, step: int) -> None:
        if not self.picked:
            self.pdf_note.configure(text="Click a page first.")
            return
        order = list(self.order)
        indices = sorted((order.index(p) for p in self.picked), reverse=step > 0)
        for i in indices:
            j = i + step
            if 0 <= j < len(order) and order[j] not in self.picked:
                order[i], order[j] = order[j], order[i]
        self.order = order
        self.draw_thumbs()

    def pdf_action(self, action: str) -> None:
        if self.pdf_path is None:
            self.pdf_note.configure(text="Open a PDF first.")
            return
        if action == "rotate":
            for page in self.picked or set(self.order):
                self.rotation[page] = (self.rotation.get(page, 0) + 90) % 360
            self.draw_thumbs()
            return
        if action == "delete":
            if not self.picked:
                self.pdf_note.configure(text="Click the pages to delete first.")
                return
            self.order = [p for p in self.order if p not in self.picked]
            self.picked = set()
            self.draw_thumbs()
            return
        pages = [p for p in self.order if p in self.picked] if action == "extract" else list(self.order)
        if not pages:
            self.pdf_note.configure(text="Nothing to save.")
            return
        from pypdf import PdfWriter

        reader = office.pdf_reader(self.pdf_path)
        writer = PdfWriter()
        for page in pages:
            p = reader.pages[page - 1]
            if self.rotation.get(page):
                p.rotate(self.rotation[page])
            writer.add_page(p)
        target = office.out_path(self.pdf_path, "extracted" if action == "extract" else "arranged")
        with open(target, "wb") as handle:
            writer.write(handle)
        self.pdf_result.show(f"Saved {len(pages)} page(s):\n{target}")

    # --- signature pad ------------------------------------------------------------------
    def _signature(self) -> None:
        c = self.colors
        card = self.card("Sign a PDF", "Draw your signature once — it is kept for next time. Then click on the page "
                                       "where it should go.", "✍", span=self.columns)
        row = ctk.CTkFrame(card.inner, fg_color="transparent")
        row.pack(fill="x")
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", anchor="n")
        self.pad = tkinter.Canvas(left, width=360, height=140, bg="white", highlightthickness=1,
                                  highlightbackground=c["accent_dim"], cursor="pencil")
        self.pad.pack()
        self.strokes: list[list[tuple[int, int]]] = []
        self.pad.bind("<ButtonPress-1>", lambda e: self.strokes.append([(e.x, e.y)]))
        self.pad.bind("<B1-Motion>", self._draw_stroke)
        line = ctk.CTkFrame(left, fg_color="transparent")
        line.pack(fill="x", pady=4)
        button(line, "Clear", self._clear_pad, height=26).pack(side="left")
        button(line, "Use a picture instead…", self._signature_file, height=26).pack(side="left", padx=6)
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="left", padx=16, anchor="n", fill="x", expand=True)
        button(right, "Choose the PDF…", self._sign_pick, accent=True).pack(anchor="w")
        self.sign_note = label(right, "", size=11, muted=True, wrap=500)
        self.sign_note.pack(anchor="w", pady=4)
        self.sign_preview = tkinter.Canvas(right, width=260, height=340, bg=c["bg"], highlightthickness=0,
                                           cursor="crosshair")
        self.sign_preview.pack(anchor="w")
        self.sign_preview.bind("<Button-1>", self._place_signature)
        self.sign_result = ResultView(right, self.app)
        self.sign_result.pack(fill="x")
        self.sign_pdf: Path | None = None
        self.sign_page = 0
        self._sign_image = None
        saved = self.signature_file()
        if saved.exists():
            self.sign_note.configure(text="Using your saved signature. Draw a new one to replace it.")

    @staticmethod
    def signature_file() -> Path:
        from jarvis.config import get_data_dir

        return get_data_dir() / "signature.png"

    def _draw_stroke(self, event) -> None:
        if not self.strokes:
            return
        x0, y0 = self.strokes[-1][-1]
        self.strokes[-1].append((event.x, event.y))
        self.pad.create_line(x0, y0, event.x, event.y, width=3, fill="#0b1f4d", capstyle="round", smooth=True)

    def _clear_pad(self) -> None:
        self.strokes = []
        self.pad.delete("all")

    def _signature_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("Pictures", "*.png *.jpg *.jpeg")])
        if path:
            shutil.copyfile(path, self.signature_file())
            self.sign_note.configure(text="Signature picture saved.")

    def _save_drawn(self) -> Path | None:
        if not self.strokes:
            return self.signature_file() if self.signature_file().exists() else None
        scale = 3
        image = Image.new("RGBA", (360 * scale, 140 * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for stroke in self.strokes:
            if len(stroke) > 1:
                draw.line([(x * scale, y * scale) for x, y in stroke], fill=(11, 31, 77, 255), width=3 * scale,
                          joint="curve")
        box = image.getbbox()
        if box:
            image = image.crop((max(0, box[0] - 10), max(0, box[1] - 10), box[2] + 10, box[3] + 10))
        image.save(self.signature_file())
        return self.signature_file()

    def _sign_pick(self) -> None:
        from jarvis import winrt

        path = filedialog.askopenfilename(parent=self, filetypes=list(office.PDF_TYPES))
        if not path:
            return
        self.sign_pdf = Path(path)
        count = len(office.pdf_reader(self.sign_pdf).pages)
        self.sign_page = count
        self.sign_note.configure(text=f"Showing the last page ({count}). Click where the signature should go.")
        folder = kit.output_dir("documents") / ".pages" / kit.stamp()

        def done(pages):
            if isinstance(pages, str) or not pages:
                self.sign_note.configure(text="Couldn't show the page — use the Sign a PDF form instead.")
                return
            with Image.open(pages[0]["path"]) as im:
                im.thumbnail((260, 340))
                from PIL import ImageTk

                self._sign_image = ImageTk.PhotoImage(im.copy())
                self._sign_size = im.size
            self.sign_preview.configure(width=self._sign_size[0], height=self._sign_size[1])
            self.sign_preview.delete("all")
            self.sign_preview.create_image(0, 0, image=self._sign_image, anchor="nw")

        self.run(lambda: winrt.pdf_pages(self.sign_pdf, folder, [count], 520), done,
                 lambda e: self.sign_note.configure(text=f"Couldn't show the page: {e}"))

    def _place_signature(self, event) -> None:
        if self.sign_pdf is None or self._sign_image is None:
            return
        signature = self._save_drawn()
        if signature is None:
            self.sign_note.configure(text="Draw your signature first.")
            return
        w, h = self._sign_size
        box = (max(0.0, min(0.9, event.x / w - 0.1)), max(0.0, min(0.95, event.y / h - 0.03)))
        try:
            target = office.pdf_sign(self.sign_pdf, signature, self.sign_page, box=box)
        except Exception as exc:
            self.sign_note.configure(text=str(exc))
            return
        self.sign_result.show(f"Signed:\n{target}")

    # --- galleries --------------------------------------------------------------------
    def _gallery(self, title: str, subtitle: str, icon: str, items: list[tuple[str, str]], tool: str,
                 field_name: str) -> None:
        card = self.card(title, subtitle, icon)
        grid = card.inner
        for i, (key, name) in enumerate(items):
            button(grid, name, lambda k=key: self.app.open_tool(tool, {field_name: k}), height=30, width=170).grid(
                row=i // 3, column=i % 3, padx=3, pady=3, sticky="w")
