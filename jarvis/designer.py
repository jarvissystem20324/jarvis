"""9.0 — the Design page's commands, for the chat (and the MCP server).

Everything the Design page makes can also be asked for in words:
"/poster bake sale on Saturday", "make a logo for my coffee shop",
"/orgchart" with an indented list. Each one saves an editable design (it
opens on the Design page) and shows a preview in the chat.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import kit, security
from .design import ai as dai
from .design import diagrams, model, render, templates
from .registry import command

G = "Design"
KIND_COMMANDS = {"thumbnail": "thumbnail", "poster": "poster", "logo": "logo", "greeting": "card", "menu": "menu",
                 "invitation": "invitation", "sticker": "sticker", "sale": "sale"}
RESIZE_ALL = ("instagram", "story", "thumbnail", "facebook", "banner", "poster")


def swatches(colours: list[str], path: Path) -> Path:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (120 * len(colours), 150), "#ffffff")
    draw = ImageDraw.Draw(image)
    font = render.face("Segoe UI", 18)
    for i, colour in enumerate(colours):
        draw.rectangle((i * 120, 0, i * 120 + 119, 110), fill=colour)
        font.draw(draw, i * 120 + 14, 138, colour, (40, 40, 40, 255))
    image.save(path)
    return path


class Designer:
    # --- helpers -------------------------------------------------------------------------------

    def _deliver(self, design: dict, note: str = "", show: bool = False):
        from .assistant import JarvisResponse

        path = model.save(design)
        preview = model.exports_dir() / f"{design['id']}.png"
        render.render_page(design, 0, min(1.0, 1600 / max(design["w"], design["h"]))).save(preview)
        self._last_design = path
        self.current_image = preview
        security.audit.record("design", design["title"][:80], f"{design['kind']}, {len(design['pages'])} page(s)")
        pages = len(design["pages"])
        text = (f"🎨 {design['title']} — {model.FORMATS[design['format']][0]}"
                f"{f', {pages} pages' if pages > 1 else ''}\n{path}\n"
                + (f"{note}\n" if note else "")
                + "Edit it on the 🖌 Design page, or tell me: /design edit make the title bigger")
        return JarvisResponse(text=text, image_path=preview, image_paths=[preview], design_path=path, show_design=show)

    def _design_arg(self, name: str) -> tuple[dict, Path] | None:
        path = kit.path_arg(name) if name and name.endswith(model.EXT) else None
        path = path or model.find_design(name) or (getattr(self, "_last_design", None) if not name else None)
        if path is None or not Path(path).exists():
            return None
        return model.load(path), Path(path)

    def _make_kind(self, kind: str, args: str, usage: str):
        text = args.strip()
        if not text:
            return usage
        try:
            design = dai.design_from(self.brain, text, kind)
        except (dai.DesignAIError, model.DesignError) as exc:
            return str(exc)
        return self._deliver(design)

    # --- describe it, JARVIS designs it ----------------------------------------------------------------

    @command("design", "tasarla", "tasarım", group=G, usage="/design <describe it>",
             help="JARVIS designs it: a poster, slides, a logo, a diagram… /design list · open · edit · export")
    def design(self, args: str, routed: bool = False):
        from .assistant import JarvisResponse

        text = args.strip()
        word, _, rest = text.partition(" ")
        word, rest = word.lower(), rest.strip()
        if not text:
            return ("Describe what you want and I'll design it:\n"
                    "  /design a poster for a charity run on 12 October in Moda\n"
                    "  /design a logo for a coffee shop called Ada\n"
                    "  /design an org chart: CEO Ayşe, CTO Mehmet, two developers\n"
                    "Also: /design list · /design open <name> · /design edit <change> · /design export pdf|png|pptx\n"
                    "Or open the 🖌 Design page in the sidebar.")
        if word in {"list", "liste", "all"}:
            items = model.listing()
            if not items:
                return "No designs yet. /design <describe it> makes one."
            return "Your designs:\n" + "\n".join(
                f"  {i['title']}  ·  {model.FORMATS.get(i['format'], ('?',))[0]}  ·  {i['pages']} page(s)  ·  "
                f"{kit.ago(i['modified'])}" for i in items[:30])
        if word in {"open", "aç"}:
            found = self._design_arg(rest)
            if not found:
                return f"No design called '{rest}'. /design list shows them."
            design, path = found
            self._last_design = path
            return JarvisResponse(text=f"Opened {design['title']} on the Design page.", design_path=path,
                                  show_design=True)
        if word in {"templates", "şablonlar"}:
            groups: dict[str, list[str]] = {}
            for item in templates.catalogue():
                groups.setdefault(item["group"], []).append(item["key"].split(":")[1])
            return f"{sum(len(v) for v in groups.values())} templates — pick one on the Design page (Templates):\n" + \
                "\n".join(f"  {g}: {', '.join(v)}" for g, v in groups.items())
        if word in {"themes", "temalar"}:
            return "Slide themes: " + ", ".join(templates.SLIDE_THEMES) + "\n/design theme <name> restyles the last deck."
        if word == "theme" and rest:
            found = self._design_arg("")
            if not found or found[0]["kind"] != "slides":
                return "Make or open a slide deck first."
            if rest.lower() not in templates.SLIDE_THEMES:
                return "Themes: " + ", ".join(templates.SLIDE_THEMES)
            design, path = found
            templates.apply_theme(design, rest.lower())
            model.save(design, path)
            return self._deliver(design, f"Theme: {rest.lower()}")
        if word in {"edit", "change", "düzenle"}:
            found = self._design_arg("")
            if not found:
                return "Make or open a design first, then /design edit <what to change>."
            if not rest:
                return "Usage: /design edit <change>   e.g. /design edit make the background dark blue"
            design, path = found
            m = re.match(r"(?:page|slide|sayfa)\s+(\d+)\s*:?\s*(.+)", rest, re.I)
            index = max(0, min(len(design["pages"]) - 1, int(m.group(1)) - 1)) if m else 0
            change = m.group(2) if m else rest
            try:
                said = dai.chat_edit(self.brain, design, design["pages"][index], change)
            except dai.DesignAIError as exc:
                return str(exc)
            design["id"] = path.stem
            return self._deliver(design, said)
        if word == "export":
            fmt, _, name = rest.partition(" ")
            return self.export_design(fmt.lower() or "pdf", name.strip())
        if word in {"better", "polish", "improve"}:
            found = self._design_arg(rest)
            if not found:
                return "Make or open a design first."
            design, path = found
            notes = [n for i in range(len(design["pages"])) for n in dai.polish(design, i)]
            design["id"] = path.stem
            return self._deliver(design, "Polished: " + ("; ".join(dict.fromkeys(notes)) or "it already looked tidy"))
        if word == "new":
            fmt = rest.lower() or "slides"
            if fmt not in model.FORMATS:
                return "Formats: " + ", ".join(model.FORMATS)
            return self._deliver(templates.blank(fmt), show=True)
        try:
            design = dai.design_from(self.brain, text)
        except (dai.DesignAIError, model.DesignError) as exc:
            return str(exc)
        return self._deliver(design)

    def export_design(self, fmt: str, name: str = ""):
        from .assistant import JarvisResponse

        found = self._design_arg(name)
        if not found:
            return "No design to export. /design list shows them."
        design, _ = found
        base = model.exports_dir() / f"{kit.slug(design['title'])}_{kit.stamp()}"
        if fmt == "pdf":
            out = [render.export_pdf(design, base.with_suffix(".pdf"))]
        elif fmt in {"png", "jpg", "jpeg"}:
            out = render.export_images(design, base, fmt.upper())
        elif fmt in {"pptx", "powerpoint", "ppt"}:
            from .design import pptxio

            out = [pptxio.export_pptx(design, base.with_suffix(".pptx"))]
        else:
            return "Export as pdf, png, jpg or pptx."
        images = [p for p in out if p.suffix in {".png", ".jpg"}][:4]
        return JarvisResponse(text="Exported:\n" + "\n".join(f"  {p}" for p in out),
                              image_path=images[0] if images else None, image_paths=images)

    # --- one command per kind --------------------------------------------------------------------------

    @command("thumbnail", "ytthumbnail", group=G, usage="/thumbnail <video idea>", help="a YouTube thumbnail")
    def thumbnail(self, args: str, routed: bool = False):
        return self._make_kind("thumbnail", args, "Usage: /thumbnail <what the video is about>   e.g. /thumbnail I tried 5 AI apps for a week")

    @command("poster", "flyer", "afiş", group=G, usage="/poster <event or idea>", help="a poster or flyer (A4)")
    def poster(self, args: str, routed: bool = False):
        return self._make_kind("poster", args, "Usage: /poster <what, when, where>   e.g. /poster book club, Friday 7pm, Kadıköy library")

    @command("logo", group=G, usage="/logo <name, what it is>", help="a simple logo: emblem, wordmark or monogram")
    def logo(self, args: str, routed: bool = False):
        return self._make_kind("logo", args, "Usage: /logo <name and what it is>   e.g. /logo Ada Coffee, a cosy café")

    @command("greeting", "greetingcard", "kart", group=G, usage="/greeting <occasion, for whom>",
             help="a birthday, thank-you or congratulations card")
    def greeting(self, args: str, routed: bool = False):
        return self._make_kind("card", args, "Usage: /greeting <occasion and who for>   e.g. /greeting birthday card for my mum, she loves gardening")

    @command("menu", "menü", group=G, usage="/menu <restaurant, dishes>", help="a restaurant or café menu")
    def menu(self, args: str, routed: bool = False):
        return self._make_kind("menu", args, "Usage: /menu <place and dishes>   e.g. /menu a small Turkish breakfast café")

    @command("invitation", "invite", "davetiye", group=G, usage="/invitation <names, date, place>",
             help="a wedding (or party) invitation")
    def invitation(self, args: str, routed: bool = False):
        return self._make_kind("invitation", args, "Usage: /invitation <names, date, place>   e.g. /invitation Elif & Can, 14 June, Bebek Hotel")

    @command("sticker", "badge", group=G, usage="/sticker <text>", help="a sticker or badge")
    def sticker(self, args: str, routed: bool = False):
        return self._make_kind("sticker", args, "Usage: /sticker <what it says>   e.g. /sticker best seller since 2026")

    @command("sale", "saleposter", "indirim", group=G, usage="/sale <offer>", help="a sale or price-tag poster")
    def sale(self, args: str, routed: bool = False):
        return self._make_kind("sale", args, "Usage: /sale <offer>   e.g. /sale 40% off summer collection, 1-15 July")

    # --- diagrams ------------------------------------------------------------------------------------------

    @command("diagram", "diyagram", group=G, usage="/diagram <kind> <description>",
             help="orgchart, familytree, timeline, gantt, comparison, kanban, wireframe or mindmap (editable)")
    def diagram(self, args: str, routed: bool = False):
        kind, _, rest = args.strip().partition(" ")
        kind = {"org": "orgchart", "family": "familytree", "compare": "comparison", "table": "comparison",
                "mockup": "wireframe", "mind": "mindmap", "map": "mindmap"}.get(kind.lower(), kind.lower())
        if kind not in diagrams.KINDS:
            return "Usage: /diagram <" + "|".join(diagrams.KINDS) + "> <description>"
        return self._make_kind(kind, rest, f"Usage: /diagram {kind} <description, or an indented list>")

    @command("orgchart", "organigram", group=G, usage="/orgchart <team or indented list>", help="an org chart")
    def orgchart(self, args: str, routed: bool = False):
        return self._make_kind("orgchart", args, "Usage: /orgchart <describe the team>, or an indented list:\n  CEO Ayşe\n    CTO Mehmet\n      Developer Ali")

    @command("familytree", "soyağacı", group=G, usage="/familytree <family or indented list>",
             help="a family tree (spouses with +)")
    def familytree(self, args: str, routed: bool = False):
        return self._make_kind("familytree", args, "Usage: /familytree <describe the family>, or a list:\n  Hasan + Fatma\n    Ahmet + Leyla\n      Zahid")

    @command("timeline", "zamançizelgesi", group=G, usage="/timeline <topic or 'date: event' lines>",
             help="a timeline")
    def timeline(self, args: str, routed: bool = False):
        return self._make_kind("timeline", args, "Usage: /timeline <topic>   e.g. /timeline history of the Ottoman Empire")

    @command("gantt", group=G, usage="/gantt <project or 'task | start | end' lines>", help="a Gantt chart")
    def gantt(self, args: str, routed: bool = False):
        return self._make_kind("gantt", args, "Usage: /gantt <project>   e.g. /gantt launching a mobile app in 3 months")

    @command("comparison", "comparetable", group=G, usage="/comparison <things to compare>", help="a comparison table")
    def comparison(self, args: str, routed: bool = False):
        return self._make_kind("comparison", args, "Usage: /comparison <what to compare>   e.g. /comparison iPhone 17 vs Pixel 11 vs Galaxy S26")

    @command("kanban", group=G, usage="/kanban <project>", help="a kanban board picture")
    def kanban(self, args: str, routed: bool = False):
        return self._make_kind("kanban", args, "Usage: /kanban <project>   e.g. /kanban my school science fair project")

    @command("wireframe", "mockup", group=G, usage="/wireframe <screen>", help="an app or website wireframe")
    def wireframe(self, args: str, routed: bool = False):
        return self._make_kind("wireframe", args, "Usage: /wireframe <which screen>   e.g. /wireframe login screen of a banking app")

    # --- slides -------------------------------------------------------------------------------------------------

    def _deck_options(self, text: str) -> tuple[str, int, str]:
        count, theme = 8, ""
        m = re.search(r"\b(\d{1,2})\s*(?:slides?|slayt|questions?|soru)\b", text, re.I)
        if m:
            count = max(3, min(int(m.group(1)), 20))
            text = (text[:m.start()] + text[m.end():]).strip()
        for name in templates.SLIDE_THEMES:
            if re.search(rf"\b{name}\b", text, re.I):
                theme = name
                text = re.sub(rf"\s*\b(?:theme\s+)?{name}(?:\s+theme)?\b", "", text, flags=re.I).strip()
        return text, count, theme

    def _deck_reply(self, design: dict):
        from .design import pptxio

        pptx = pptxio.export_pptx(design, model.exports_dir() / f"{kit.slug(design['title'])}_{kit.stamp()}.pptx")
        return self._deliver(design, f"PowerPoint: {pptx}")

    @command("ytslides", "videoslides", group=G, usage="/ytslides <YouTube link> [8 slides] [theme]",
             help="a slide deck made from a YouTube video")
    def ytslides(self, args: str, routed: bool = False):
        text, count, theme = self._deck_options(args.strip())
        if not text:
            return "Usage: /ytslides <YouTube link> [8 slides] [theme]   themes: " + ", ".join(templates.SLIDE_THEMES)
        try:
            design = dai.deck_from_youtube(self.brain, text.split()[0], count, theme or "midnight")
        except dai.DesignAIError as exc:
            return str(exc)
        return self._deck_reply(design)

    @command("quizslides", "quizdeck", group=G, usage="/quizslides <topic> [6 questions] [theme]",
             help="quiz slides for class: a question slide, then its answer")
    def quizslides(self, args: str, routed: bool = False):
        text, count, theme = self._deck_options(args.strip())
        if not text:
            return "Usage: /quizslides <topic> [6 questions]   e.g. /quizslides the water cycle 8 questions"
        try:
            design = dai.quiz_slides(self.brain, text, min(count, 12), theme or "classroom")
        except dai.DesignAIError as exc:
            return str(exc)
        return self._deck_reply(design)

    # --- colours, fonts, words ------------------------------------------------------------------------------------

    @command("palette", "renkpaleti", group=G, usage="/palette <mood or photo>",
             help="a colour palette from a mood or a photo; /palette apply puts it on the last design")
    def palette(self, args: str, routed: bool = False):
        from .assistant import JarvisResponse

        text = args.strip()
        if not text:
            return "Usage: /palette <mood or a photo's path>   e.g. /palette calm ocean   ·   /palette apply"
        if text.lower() == "apply":
            colours = getattr(self, "_last_palette", None)
            found = self._design_arg("")
            if not colours or not found:
                return "Make a palette (/palette <mood>) and a design first."
            design, path = found
            dai.apply_palette(design, colours)
            design["id"] = path.stem
            return self._deliver(design, "New palette applied.")
        photo = kit.path_arg(text)
        try:
            if photo is not None:
                colours, name = dai.palette_from_photo(photo), f"from {photo.name}"
            else:
                colours, name = dai.palette_from_mood(self.brain, text)
        except dai.DesignAIError as exc:
            return str(exc)
        self._last_palette = colours
        image = swatches(colours, model.exports_dir() / f"palette_{kit.stamp()}.png")
        return JarvisResponse(text=f"🎨 Palette ({name}): {'  '.join(colours)}\n"
                                   "primary · secondary · accent · light · dark — /palette apply puts it on your last design.",
                              image_path=image, image_paths=[image])

    @command("fontpair", "fonts", group=G, usage="/fontpair <mood>", help="font pairings that suit a mood")
    def fontpair(self, args: str, routed: bool = False):
        text = args.strip()
        m = re.match(r"apply\s+(\d+)$", text, re.I)
        if m:
            pairs = getattr(self, "_last_pairs", None) or templates.font_pairs("")
            found = self._design_arg("")
            index = int(m.group(1)) - 1
            if not found or not (0 <= index < len(pairs)):
                return "Make a design and ask for pairs (/fontpair <mood>) first."
            design, path = found
            dai.apply_fonts(design, pairs[index][0], pairs[index][1])
            design["id"] = path.stem
            return self._deliver(design, f"Fonts: {pairs[index][0]} + {pairs[index][1]}")
        pairs = dai.font_suggestions(self.brain if text else None, text, 5)
        if not pairs:
            return "No font pairs found on this PC."
        self._last_pairs = pairs
        return "Font pairings" + (f" for “{text}”" if text else "") + " (heading + body):\n" + "\n".join(
            f"  {i}. {h} + {b}  —  {v}" for i, (h, b, v) in enumerate(pairs, 1)) + "\n/fontpair apply <n> uses one on your last design."

    @command("headline", "headlines", "başlık", group=G, usage="/headline <topic>", help="six headline ideas")
    def headline(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /headline <what it's about>   e.g. /headline our new vegan menu"
        try:
            items = dai.headlines(self.brain, args.strip())
        except dai.DesignAIError as exc:
            return str(exc)
        return "Headline ideas:\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(items, 1))

    @command("critique", "designreview", group=G, usage="/critique [design]", help="design feedback on your last design")
    def critique(self, args: str, routed: bool = False):
        found = self._design_arg(args.strip())
        if not found:
            return "No design to look at. /design list shows them."
        design, _ = found
        findings = dai.critique(design, 0)
        try:
            opinion = dai.critique_ai(self.brain, design, 0, findings)
        except Exception:
            opinion = ""
        return f"Design check — {design['title']}:\n" + "\n".join(f"  • {f}" for f in findings) + (
            f"\n\nJARVIS's take:\n{opinion}" if opinion else "")

    @command("resize", "magicresize", group=G, usage="/resize <format|all> [design]",
             help="the same design at another size (instagram, story, thumbnail, poster…)")
    def resize_design(self, args: str, routed: bool = False):
        from .assistant import JarvisResponse

        fmt, _, name = args.strip().partition(" ")
        fmt = fmt.lower()
        if fmt not in model.FORMATS and fmt != "all":
            return "Usage: /resize <format|all> [design]\nFormats: " + ", ".join(model.FORMATS)
        found = self._design_arg(name.strip())
        if not found:
            return "No design to resize. /design list shows them."
        design, _ = found
        targets = [f for f in RESIZE_ALL if f != design["format"]] if fmt == "all" else [fmt]
        made = []
        for target in targets:
            copy = dai.resize(design, target)
            path = model.save(copy)
            preview = model.exports_dir() / f"{copy['id']}.png"
            render.thumbnail(copy, 1200).save(preview)
            made.append((target, path, preview))
        self._last_design = made[-1][1]
        return JarvisResponse(text="Resized:\n" + "\n".join(f"  {model.FORMATS[t][0]}: {p}" for t, p, _ in made),
                              image_path=made[0][2], image_paths=[m[2] for m in made][:4], design_path=made[-1][1])

    @command("brand", "brandkit", "marka", group=G, usage="/brand [colors|fonts|logo|name|apply|clear]",
             help="your brand kit: colours, fonts and logo, applied in one go")
    def brand(self, args: str, routed: bool = False):
        text = args.strip()
        word, _, rest = text.partition(" ")
        word, rest = word.lower(), rest.strip()
        brand = dai.BRAND.load()
        if word in {"colors", "colours", "renkler"}:
            colours = [model.color(c, None) for c in re.split(r"[\s,]+", rest) if c]
            colours = [c for c in colours if c]
            if len(colours) < 3:
                return "Give 3-5 colours: /brand colors #1e3a8a #f59e0b #10b981 #f8fafc #0f172a"
            brand["colors"] = colours[:5]
        elif word == "fonts":
            heading, _, body = rest.partition("+")
            if not heading.strip():
                return "Usage: /brand fonts Georgia + Segoe UI"
            brand["heading"], brand["body"] = heading.strip(), (body.strip() or heading.strip())
        elif word == "logo":
            path = kit.path_arg(rest)
            if path is None:
                return "Usage: /brand logo <path to a PNG or JPG>"
            brand["logo"] = model.import_asset(path)
        elif word == "name":
            brand["name"] = rest[:80]
        elif word == "clear":
            dai.BRAND.save({"name": "", "colors": [], "heading": "", "body": "", "logo": ""})
            return "Brand kit cleared."
        elif word == "apply":
            found = self._design_arg(rest)
            if not found:
                return "Make or open a design first."
            design, path = found
            done = dai.apply_brand(design, brand)
            if not done:
                return "Your brand kit is empty. /brand colors … · /brand fonts … · /brand logo …"
            design["id"] = path.stem
            return self._deliver(design, "Applied: " + ", ".join(done))
        elif text:
            return "Usage: /brand colors <3-5 colours> · fonts <heading> + <body> · logo <file> · name <name> · apply · clear"
        if word:
            dai.BRAND.save(brand)
        return (f"Brand kit{(' — ' + brand['name']) if brand.get('name') else ''}:\n"
                f"  colours: {' '.join(brand.get('colors') or []) or '—'}\n"
                f"  fonts:   {brand.get('heading') or '—'} + {brand.get('body') or '—'}\n"
                f"  logo:    {brand.get('logo') or '—'}\n"
                "/brand apply puts it on your last design (the Design page has a button too).")

    # --- coding: the MCP server -------------------------------------------------------------------------------------

    @command("mcp", group="Coding", usage="/mcp [setup antigravity|cursor|claude]",
             help="use JARVIS's tools from Antigravity, Claude Code or Cursor (MCP server)")
    def mcp(self, args: str, routed: bool = False):
        from . import mcp_server

        word, _, rest = args.strip().partition(" ")
        word = word.lower()
        if word in {"setup", "install", "kur"}:
            target = rest.strip().lower() or "antigravity"
            if target not in mcp_server.CLIENTS:
                return "Usage: /mcp setup antigravity|cursor|claude"
            if target == "claude":
                return "Run this once in a terminal (Claude Code adds JARVIS for every project):\n  " + \
                    mcp_server.claude_command()
            if not security.permissions.ask(security.WRITE_FILE, ", ".join(str(p) for p in mcp_server.config_paths(target)),
                                            context=f"add JARVIS to {target}'s MCP servers"):
                return "Denied. Nothing was changed."
            try:
                written = mcp_server.install(target)
            except OSError as exc:
                return f"Couldn't write the config: {exc}"
            return (f"Added JARVIS to {target}:\n" + "\n".join(f"  {p}" for p in written) +
                    f"\nRestart {target.title()} (or refresh its MCP servers) and ask its agent to use JARVIS — "
                    "e.g. “use jarvis to make slides about this repo”.")
        return mcp_server.describe()
