"""10.0: Design 2.0's commands — presenting, slides from Excel, a PDF's pages,
a design from a sketch photo, the new kinds (CV, book cover, ticket,
infographic, Instagram carousel, calendar page), spell checking and taking
the white background off a picture. The Design page has a button for each;
the work is in jarvis/design/extras.py and more_templates.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import kit
from ..registry import command, field, split

G = "Design"
EN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]
TR_MONTHS = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım",
             "aralık"]
MONTH_WORDS = {name: i for names in (EN_MONTHS, TR_MONTHS) for i, name in enumerate(names, 1)}
PICTURES = (("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp"),)


def calendar_content(text: str) -> dict | None:
    """'november 2026 family calendar' -> month, year and the rest as its title — no AI needed."""
    words = text.strip()
    month = year = None
    turkish = bool(re.search("[çğışöüÇĞİŞÖÜ]", text))
    for word, number in MONTH_WORDS.items():
        match = re.search(rf"\b{word}\b", words.lower())
        if match:
            month = number
            turkish = turkish or word in TR_MONTHS
            words = (words[:match.start()] + words[match.end():]).strip()
            break
    match = re.search(r"\b(20\d\d)\b", words)
    if match:
        year = int(match.group(1))
        words = (words[:match.start()] + words[match.end():]).strip()
    if month is None and year is None:
        return None
    out: dict = {"title": " ".join(words.split()).strip(" -·,")}
    if month:
        out["month"] = month
    if year:
        out["year"] = year
    if turkish:
        out["lang"] = "tr"
    return out


class Design10:
    @command("slideshow", "present", "sunum", group=G, usage="/slideshow [presenter] [design]",
             help="presents a design full screen with its transitions and animations; presenter view adds notes "
                  "and a timer", title="Slideshow", icon="▶", page="design",
             fields=(field("mode", "choice", "Show", "full screen", ("full screen", "presenter view")),
                     field("design", "text", "Design (blank: the last one)", optional=True)),
             template="{mode} {design}")
    def slideshow_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        words = args.strip()
        presenter = bool(re.match(r"(presenter|sunucu)", words, re.I))
        words = re.sub(r"^(presenter view|presenter|full screen|fullscreen|sunucu)\s*", "", words, flags=re.I)
        found = self._design_arg(words.strip())
        if not found:
            return "No design to present. Make one (/design …, /slides …) or open the 🖌 Design page."
        design, path = found
        pages = len(design["pages"])
        how = "with the presenter view (notes and a timer)" if presenter else "full screen"
        return JarvisResponse(text=f"▶ Presenting {design['title']} {how} — {pages} slide(s). Click or → for the "
                                   "next, ← to go back, Esc to end.",
                              design_path=path, show_design=True,
                              open_page="design:presenter" if presenter else "design:present")

    @command("excelslides", "tableslides", group=G, usage="/excelslides <xlsx or csv> [| rows|table] [theme]",
             help="slides from an Excel or CSV table — a slide per row or the table across slides, plus a chart "
                  "of its numbers", title="Slides from Excel", icon="📊", page="design",
             fields=(field("file", "file", "Excel or CSV file", types=(("Excel or CSV", "*.xlsx *.csv"),)),
                     field("mode", "choice", "Slides", "rows", ("rows", "table")),
                     field("theme", "choice", "Theme", "midnight", ("midnight", "paper", "ocean", "forest", "sunset",
                                                                    "royal", "mono", "candy", "slate", "coffee",
                                                                    "neon", "classroom"))),
             template="{file} | {mode} {theme}")
    def excelslides_cmd(self, args: str, routed: bool = False):
        from ..design import extras, model, templates

        path_text, options = split(args, 2) if "|" in args else (args, "")
        words = options.lower().split()
        mode = "table" if "table" in words or "tablo" in words else "rows"
        theme = next((w for w in words if w in templates.SLIDE_THEMES), "midnight")
        path = kit.path_arg(path_text.strip())
        if path is None or not path.is_file():
            return "Usage: /excelslides C:/sales.xlsx | table ocean   (rows: a slide per row · table: the table itself)"
        try:
            design = extras.slides_from_table(extras.read_table(path), path.stem, mode, theme)
        except Exception as exc:
            return f"📊 {exc}"
        from ..design import pptxio

        pptx = pptxio.export_pptx(design, model.exports_dir() / f"{kit.slug(design['title'])}_{kit.stamp()}.pptx")
        return self._deliver(design, f"PowerPoint: {pptx}")

    @command("pdfdesign", "pdfslides", group=G, usage="/pdfdesign <pdf>",
             help="a PDF's pages as a design, to write, draw and add on top — or present", title="PDF pages",
             icon="📄", page="design", fields=(field("file", "file", "PDF", types=(("PDF", "*.pdf"),)),))
    def pdfdesign_cmd(self, args: str, routed: bool = False):
        from ..design import extras

        path = kit.path_arg(args.strip())
        if path is None or path.suffix.lower() != ".pdf" or not path.is_file():
            return "Usage: /pdfdesign C:/handout.pdf"
        try:
            design = extras.design_from_pdf(path)
        except Exception as exc:
            return f"📄 {exc}"
        return self._deliver(design, "Each page is locked in place, so you can write and draw on top.", show=True)

    @command("sketch", "sketchdesign", "eskiz", group=G, usage="/sketch <photo of a sketch> [| poster|slides|…]",
             help="turns a photo of a hand-drawn layout into a real, editable design", title="Design from a sketch",
             icon="📷", page="design",
             fields=(field("photo", "file", "Photo of your sketch", types=PICTURES),
                     field("format", "choice", "Format", "auto", ("auto", "slides", "poster", "instagram", "story",
                                                                 "thumbnail", "card", "invitation", "banner"))),
             template="{photo} | {format}")
    def sketch_cmd(self, args: str, routed: bool = False):
        from ..design import extras

        path_text, fmt = split(args, 2) if "|" in args else (args, "auto")
        path = kit.path_arg(path_text.strip())
        if path is None or not path.is_file():
            return "Usage: /sketch C:/photos/layout.jpg [| poster]"
        try:
            design = extras.design_from_sketch(self.brain, path, fmt.strip().lower() or "auto")
        except Exception as exc:
            return f"📷 {exc}"
        return self._deliver(design, "From your sketch — everything on it is editable.")

    # --- the new kinds -----------------------------------------------------------------------------------

    @command("cvdesign", "resumedesign", "özgeçmiş", group=G, usage="/cvdesign <about you>",
             help="a designed one-page CV (modern, classic or bold), editable on the Design page",
             title="CV design", icon="🧑\u200d💼", page="design",
             fields=(field("about", "long", "About you: name, job, experience, education, skills"),))
    def cvdesign_cmd(self, args: str, routed: bool = False):
        return self._make_kind("cv", args, "Usage: /cvdesign <about you>   e.g. /cvdesign Ayşe Demir, nurse, 6 years "
                                           "at Acıbadem, Hacettepe 2018, speaks English and German")

    @command("bookcover", "kitapkapağı", group=G, usage="/bookcover <title, author, what it's about>",
             help="a book cover (6×9 in)", title="Book cover", icon="📕", page="design",
             fields=(field("about", "text", "Title, author and what it's about"),))
    def bookcover_cmd(self, args: str, routed: bool = False):
        return self._make_kind("bookcover", args, "Usage: /bookcover <title, author, genre>   e.g. /bookcover "
                                                  "The Silent Bay by Mert Kaya, a mystery in Bodrum")

    @command("ticket", "bilet", group=G, usage="/ticket <event, date, place, price>", help="an event ticket",
             title="Event ticket", icon="🎟", page="design",
             fields=(field("about", "text", "Event, date, place, price"),))
    def ticket_cmd(self, args: str, routed: bool = False):
        return self._make_kind("ticket", args, "Usage: /ticket <event, date, place>   e.g. /ticket school concert, "
                                               "12 June 19:00, Moda Sahnesi, ₺150")

    @command("infographic", "infografik", group=G, usage="/infographic <topic>",
             help="a tall infographic: steps or big numbers", title="Infographic", icon="📈", page="design",
             fields=(field("topic", "text", "Topic"),))
    def infographic_cmd(self, args: str, routed: bool = False):
        return self._make_kind("infographic", args, "Usage: /infographic <topic>   e.g. /infographic 5 ways to "
                                                    "save water at home")

    @command("carousel", "igcarousel", group=G, usage="/carousel <topic>",
             help="an Instagram carousel: a cover, one tip per slide, a closing slide", title="Instagram carousel",
             icon="🎠", page="design", fields=(field("topic", "text", "Topic"),))
    def carousel_cmd(self, args: str, routed: bool = False):
        return self._make_kind("carousel", args, "Usage: /carousel <topic>   e.g. /carousel 5 study tips for exam "
                                                 "week, @ayse.studies")

    @command("calendarpage", "monthpage", "takvimsayfası", group=G, usage="/calendarpage [month] [year] [title]",
             help="a printable calendar page for a month", title="Calendar page", icon="🗓", page="design",
             fields=(field("month", "text", "Month and year (e.g. November 2026)", optional=True),
                     field("style", "choice", "Style", "photo", ("photo", "minimal"))),
             template="{month} {style}")
    def calendarpage_cmd(self, args: str, routed: bool = False):
        from ..design import templates

        text = args.strip()
        variant = "minimal" if re.search(r"\bminimal\b", text, re.I) else "photo"
        text = re.sub(r"\b(minimal|photo)\b", "", text, flags=re.I).strip()
        content = calendar_content(text) if text else {}
        if content is None:
            return self._make_kind("calendar", text, "Usage: /calendarpage november 2026")
        return self._deliver(templates.make("calendar", variant, content))

    # --- words and pictures ------------------------------------------------------------------------------

    @command("spellcheck", "spelling", "yazımdenetimi", group=G, usage="/spellcheck [text] (blank: your last design)",
             help="spelling mistakes in a text or in your last design (Windows' own spell checker, Turkish too)",
             title="Spell check", icon="🔤", page="design",
             fields=(field("text", "long", "Text (blank: the last design)", optional=True),))
    def spellcheck_cmd(self, args: str, routed: bool = False):
        from .. import spelling
        from ..design import extras

        text = args.strip()
        try:
            if text:
                issues = spelling.check(text)
                if not issues:
                    return "🔤 No spelling mistakes found."
                return "🔤 " + "\n".join(f"  {i['word']} → {', '.join(s or '(delete it)' for s in i['suggestions'][:3]) or '?'}"
                                        for i in issues)
            found = self._design_arg("")
            if not found:
                return "Usage: /spellcheck <text> — or make/open a design and run /spellcheck on its own."
            design, _ = found
            issues = extras.spelling_issues(design)
        except spelling.SpellError as exc:
            return f"🔤 {exc}"
        if not issues:
            return f"🔤 {design['title']}: no spelling mistakes found."
        return f"🔤 {design['title']} — {len(issues)} to look at (fix them with ABC✓ on the Design page):\n" + "\n".join(
            f"  page {i['page'] + 1}: {i['word']} → {', '.join(s or '(delete it)' for s in i['suggestions'][:3]) or '?'}"
            for i in issues[:30])

    @command("removebg", "nobg", "arkaplansil", group=G, usage="/removebg <picture> [more]",
             help="takes the white background off a logo or product photo (a transparent PNG next to it)",
             title="Remove white background", icon="✂", page="design",
             fields=(field("picture", "file", "Picture", types=PICTURES),
                     field("strength", "choice", "How much", "normal", ("normal", "more"))),
             template="{picture} | {strength}")
    def removebg_cmd(self, args: str, routed: bool = False):
        from PIL import Image, ImageOps

        from ..assistant import JarvisResponse
        from ..design import extras
        from .media import edited_path

        path_text, strength = split(args, 2) if "|" in args else (args, "")
        path = kit.path_arg(path_text.strip())
        if path is None or not path.is_file():
            return "Usage: /removebg C:/logo.jpg [| more]"
        try:
            with Image.open(path) as image:
                result = extras.remove_white(ImageOps.exif_transpose(image), 60 if "more" in strength.lower() else 28)
        except Exception as exc:
            return f"✂ Couldn't do it: {exc}"
        out = edited_path(Path(path), "nobg", ".png")
        result.save(out)
        self.current_image = out
        return JarvisResponse(text=f"✂ White background removed — {out}", image_path=out, image_paths=[out])
