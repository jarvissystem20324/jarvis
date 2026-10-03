"""PowerPoint in and out.

Export maps each element onto a real PowerPoint object — text boxes stay
editable text, shapes stay shapes, tables stay tables, speaker notes go into
the notes pane — so "Open in PowerPoint" gives a deck you can keep working
on, not a slideshow of pictures. Only what PowerPoint has no equivalent for
(filtered or rounded photos, colour emoji icons, a ribbon) goes in as a
picture of itself.

Import does the reverse as well as python-pptx allows: positions, text with
its size, colour and weight, pictures (with their crop), plain shapes,
lines, tables, the slide background and the notes. Charts and SmartArt come
in as a labelled box rather than silently disappearing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import model, render

SHAPE_MAP = {"rect": "RECTANGLE", "round": "ROUNDED_RECTANGLE", "ellipse": "OVAL", "triangle": "ISOSCELES_TRIANGLE",
             "diamond": "DIAMOND", "pentagon": "REGULAR_PENTAGON", "hexagon": "HEXAGON", "star": "STAR_5_POINT",
             "burst": "STAR_16_POINT", "arrow": "RIGHT_ARROW", "chevron": "CHEVRON", "plus": "CROSS",
             "heart": "HEART", "bubble": "ROUNDED_RECTANGULAR_CALLOUT"}


def _inches(design: dict) -> float:
    return min(56.0, max(1.0, render.INCHES_WIDE.get(design.get("format", ""), design["w"] / 144)))


# --- export ---------------------------------------------------------------------------------

def export_pptx(design: dict, path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation()
    emu = _inches(design) * 914400 / design["w"]
    prs.slide_width, prs.slide_height = Emu(int(design["w"] * emu)), Emu(int(design["h"] * emu))
    blank = prs.slide_layouts[6]
    with tempfile.TemporaryDirectory() as tmp:
        for index, page in enumerate(design["pages"]):
            slide = prs.slides.add_slide(blank)
            fill = slide.background.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(page.get("bg", "#ffffff"))
            for n, el in enumerate(page["elements"]):
                try:
                    _export(slide, el, emu, Path(tmp) / f"p{index}_{n}.png")
                except Exception:
                    continue
            if page.get("notes"):
                slide.notes_slide.notes_text_frame.text = page["notes"]
        prs.save(str(path))
    return path


def _rgb(hex_color: str):
    from pptx.dml.color import RGBColor

    return RGBColor(*model.rgb(hex_color))


def _box(el: dict, emu: float):
    from pptx.util import Emu

    left, top, right, bottom = model.bbox(el)
    return Emu(int(left * emu)), Emu(int(top * emu)), Emu(int(max(1, right - left) * emu)), Emu(int(max(1, bottom - top) * emu))


def _alpha(fill_format, opacity: float) -> None:
    """python-pptx has no transparency setting; it is one attribute in the XML."""
    if opacity >= 0.999:
        return
    from pptx.oxml.ns import qn

    clr = fill_format._xPr.find(qn("a:solidFill"))
    if clr is not None and len(clr):
        alpha = clr[0].makeelement(qn("a:alpha"), {"val": str(int(opacity * 100000))})
        clr[0].append(alpha)


def _font(run, el: dict, size_px: float, emu: float) -> None:
    from pptx.util import Pt

    run.font.name = el.get("font") or "Segoe UI"
    run.font.size = Pt(max(1.0, size_px * emu / 12700))
    run.font.bold = bool(el.get("bold"))
    run.font.italic = bool(el.get("italic"))
    run.font.underline = bool(el.get("underline"))
    run.font.color.rgb = _rgb(el.get("color") or "#000000")


def _fill_text(frame, el: dict, size_px: float, emu: float) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu

    frame.word_wrap = True
    pad = Emu(int(el.get("pad", 0) * emu))
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = pad
    frame.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                             "bottom": MSO_ANCHOR.BOTTOM}[el.get("valign", "top")]
    align = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[el.get("align", "left")]
    for i, line in enumerate(str(el.get("text", "")).split("\n")):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = el.get("line", 1.15)
        run = paragraph.add_run()
        run.text = line
        _font(run, el, size_px, emu)


def _picture(slide, el: dict, emu: float, tmp: Path) -> None:
    flat = model.clone(el)
    flat["rot"] = 0
    flat["opacity"] = el.get("opacity", 1.0)
    scale = min(2.0, max(0.5, 1600 / max(1.0, abs(el["w"]), abs(el["h"]))))
    builder = {"image": render.image_layer, "icon": render.icon_layer, "shape": render.shape_layer}[el["type"]]
    layer, pad = builder(flat, scale)
    if pad:
        layer = layer.crop((pad, pad, layer.width - pad, layer.height - pad))
    if flat["opacity"] < 1:
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * flat["opacity"])))
    layer.save(tmp)
    left, top, width, height = _box(el, emu)
    picture = slide.shapes.add_picture(str(tmp), left, top, width, height)
    picture.rotation = el.get("rot", 0)


def _export(slide, el: dict, emu: float, tmp: Path) -> None:
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu, Pt

    kind = el["type"]
    if kind == "text":
        box = slide.shapes.add_textbox(*_box(el, emu))
        size = render.fitted_size(el) if el.get("autofit") else el["size"]
        _fill_text(box.text_frame, el, size, emu)
        if el.get("fill"):
            box.fill.solid()
            box.fill.fore_color.rgb = _rgb(el["fill"])
            _alpha(box.fill, el.get("opacity", 1.0))
        box.rotation = el.get("rot", 0)
        return
    if kind == "shape":
        name = SHAPE_MAP.get(el["shape"])
        if name is None:
            _picture(slide, el, emu, tmp)
            return
        shape =slide.shapes.add_shape(getattr(MSO_SHAPE, name), *_box(el, emu))
        if el["shape"] == "round":
            try:
                shape.adjustments[0] = min(0.5, el.get("radius", 0) / max(1.0, min(el["w"], el["h"])))
            except (IndexError, ValueError):
                pass
        if el.get("fill"):
            shape.fill.solid()
            shape.fill.fore_color.rgb = _rgb(el["fill"])
            _alpha(shape.fill, el.get("opacity", 1.0))
        else:
            shape.fill.background()
        if el.get("stroke") and el.get("stroke_w", 0) > 0:
            shape.line.color.rgb = _rgb(el["stroke"])
            shape.line.width = Emu(int(el["stroke_w"] * emu))
        else:
            shape.line.fill.background()
        shape.shadow.inherit = False
        if el.get("text", "").strip():
            inner = render._shape_text_box(el)
            probe = dict(el, w=inner[2], h=inner[3], pad=0)
            size = render.fitted_size(probe) if el.get("autofit") else el["size"]
            _fill_text(shape.text_frame, dict(el, valign=el.get("valign", "middle")), size, emu)
        shape.rotation = el.get("rot", 0)
        return
    if kind == "line":
        x0, y0 = el["x"], el["y"]
        x1, y1 = x0 + el["w"], y0 + el["h"]
        conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(int(x0 * emu)), Emu(int(y0 * emu)),
                                          Emu(int(x1 * emu)), Emu(int(y1 * emu)))
        conn.line.color.rgb = _rgb(el.get("stroke") or "#000000")
        conn.line.width = Pt(max(0.25, el.get("stroke_w", 4) * emu / 12700))
        if el.get("dash"):
            from pptx.enum.dml import MSO_LINE

            conn.line.dash_style = MSO_LINE.DASH
        arrow = el.get("arrow", "none")
        if arrow != "none":
            from pptx.oxml.ns import qn

            ln = conn.line._get_or_add_ln()
            for tag, wanted in (("a:headEnd", arrow in {"start", "both"}), ("a:tailEnd", arrow in {"end", "both"})):
                if wanted:
                    ln.append(ln.makeelement(qn(tag), {"type": "triangle", "w": "med", "len": "med"}))
        return
    if kind in {"image", "icon"}:
        _picture(slide, el, emu, tmp)
        return
    if kind == "table":
        rows = el["rows"]
        frame = slide.shapes.add_table(len(rows), max(len(r) for r in rows), *_box(el, emu))
        table = frame.table
        table.first_row = bool(el.get("header"))
        size = _table_size(el)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                cell = table.cell(r, c)
                header = r == 0 and el.get("header")
                cell.fill.solid()
                cell.fill.fore_color.rgb = _rgb(el.get("fill") if header else (
                    el.get("stripe") if r % 2 == 0 and el.get("stripe") else el.get("bg") or "#ffffff"))
                frame_ = cell.text_frame
                frame_.text = ""
                run = frame_.paragraphs[0].add_run()
                run.text = value
                style = dict(el, bold=bool(header), color=el.get("header_color") if header else el.get("color"),
                             italic=False, underline=False)
                _font(run, style, size, emu)


def _table_size(el: dict) -> float:
    rows = el.get("rows") or [[""]]
    n, m = len(rows), max(len(r) for r in rows)
    cw, rh = el["w"] / m, el["h"] / n
    size = el.get("size", 28)
    for _ in range(30):
        font = render.face(el.get("font") or "Segoe UI", size)
        pad = size * 0.35
        if all(len(render._wrap(cell, font, max(1, cw - 2 * pad))) * size * 1.15 <= rh - pad * 0.6 + 0.5
               for row in rows for cell in row) or size <= 6:
            return size
        size *= 0.92
    return size


# --- import ---------------------------------------------------------------------------------

def import_pptx(path: Path) -> dict:
    from pptx import Presentation

    path = Path(path)
    try:
        prs = Presentation(str(path))
    except Exception as exc:
        raise model.DesignError(f"Couldn't open {path.name}: {exc}") from None
    width = 1920
    scale = width / prs.slide_width
    design = model.new_design("slides", "slides", path.stem)
    design["w"], design["h"] = width, int(round(prs.slide_height * scale))
    design["pages"] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, slide in enumerate(prs.slides):
            page = model.new_page(_background(slide))
            page["layout"] = "content"
            for n, shape in enumerate(slide.shapes):
                try:
                    _import_shape(design, page, shape, scale, (0.0, 0.0, 1.0, 1.0), Path(tmp), f"{index}_{n}")
                except Exception:
                    continue
            try:
                if slide.has_notes_slide:
                    page["notes"] = slide.notes_slide.notes_text_frame.text
            except Exception:
                pass
            design["pages"].append(page)
    if not design["pages"]:
        design["pages"].append(model.new_page())
    first = next((e for e in design["pages"][0]["elements"] if e["type"] in {"text", "shape"} and e.get("text")), None)
    if first:
        design["title"] = first["text"].split("\n")[0][:80]
    return design


def _solid(fill) -> str | None:
    try:
        from pptx.enum.dml import MSO_FILL

        if fill.type == MSO_FILL.SOLID and fill.fore_color.type is not None:
            return "#" + str(fill.fore_color.rgb).lower()
    except Exception:
        return None
    return None


def _background(slide) -> str:
    for source in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        try:
            colour = _solid(source.background.fill)
        except Exception:
            colour = None
        if colour:
            return colour
    return "#ffffff"


def _run_style(shape, placeholder_title: bool) -> dict:
    size, bold, italic, colour, family = None, False, False, None, None
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size and size is None:
                size = run.font.size.pt
            if run.font.name and family is None:
                family = run.font.name
            bold = bold or bool(run.font.bold)
            italic = italic or bool(run.font.italic)
            try:
                if colour is None and run.font.color and run.font.color.type is not None:
                    colour = "#" + str(run.font.color.rgb).lower()
            except Exception:
                pass
    align = "left"
    try:
        from pptx.enum.text import PP_ALIGN

        first = shape.text_frame.paragraphs[0].alignment
        align = {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right"}.get(first, "left")
    except Exception:
        pass
    return {"size_pt": size or (40.0 if placeholder_title else 20.0), "bold": bold or placeholder_title,
            "italic": italic, "color": colour, "align": align, "font": family or "Segoe UI"}


def _import_shape(design: dict, page: dict, shape, scale: float, group: tuple, tmp: Path, tag: str) -> None:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    ox, oy, fx, fy = group
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        child = _group_transform(shape, scale, group)
        for n, sub in enumerate(shape.shapes):
            try:
                _import_shape(design, page, sub, scale, child, tmp, f"{tag}_{n}")
            except Exception:
                continue
        return
    if shape.left is None or shape.width is None:
        return
    x, y = ox + shape.left * scale * fx, oy + shape.top * scale * fy
    w, h = max(1.0, shape.width * scale * fx), max(1.0, shape.height * scale * fy)
    rot = float(getattr(shape, "rotation", 0) or 0)
    if shape.shape_type == MSO_SHAPE_TYPE.LINE or shape.__class__.__name__ == "Connector":
        x0, y0 = ox + shape.begin_x * scale * fx, oy + shape.begin_y * scale * fy
        x1, y1 = ox + shape.end_x * scale * fx, oy + shape.end_y * scale * fy
        colour = "#000000"
        try:
            colour = "#" + str(shape.line.color.rgb).lower()
        except Exception:
            pass
        arrow, dash = "none", False
        try:
            from pptx.oxml.ns import qn

            ln = shape.line._get_or_add_ln()
            head = ln.find(qn("a:headEnd")) is not None and ln.find(qn("a:headEnd")).get("type", "none") != "none"
            tail = ln.find(qn("a:tailEnd")) is not None and ln.find(qn("a:tailEnd")).get("type", "none") != "none"
            arrow = "both" if head and tail else ("start" if head else ("end" if tail else "none"))
            dash_el = ln.find(qn("a:prstDash"))
            dash = dash_el is not None and dash_el.get("val", "solid") != "solid"
        except Exception:
            pass
        model.add(design, page, model.line(x0, y0, x1, y1, stroke=colour, arrow=arrow, dash=dash,
                                           stroke_w=max(1.0, (shape.line.width or 12700) * scale)))
        return
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image") and shape.shape_type in {
            MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.PLACEHOLDER}:
        try:
            image = shape.image
        except Exception:
            image = None
        if image is not None:
            file = tmp / f"{tag}.{image.ext}"
            file.write_bytes(image.blob)
            crop = [float(getattr(shape, f"crop_{side}", 0) or 0) for side in ("left", "top", "right", "bottom")]
            model.add(design, page, model.picture(model.import_asset(file), x, y, w, h, rot=rot, crop=crop,
                                                  fit="stretch"))
            return
    if getattr(shape, "has_table", False) and shape.has_table:
        table = shape.table
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        props = {}
        try:
            props["fill"] = _solid(table.cell(0, 0).fill) or "#4f8ef7"
            props["header_color"] = model.readable_on(props["fill"])
            runs = [r for p in table.cell(0, 0).text_frame.paragraphs for r in p.runs] +                    [r for p in table.cell(min(1, len(rows) - 1), 0).text_frame.paragraphs for r in p.runs]
            sizes = [r.font.size.pt for r in runs if r.font.size]
            if sizes:
                props["size"] = sizes[-1] * 12700 * scale
            if len(rows) > 2:
                props["stripe"] = _solid(table.cell(2, 0).fill) or "#f1f5f9"
                props["bg"] = _solid(table.cell(1, 0).fill) or "#ffffff"
        except Exception:
            pass
        props.setdefault("size", max(8.0, h / max(1, len(rows)) * 0.3))
        model.add(design, page, model.table(rows, x, y, w, h, header=bool(table.first_row), **props))
        return
    if getattr(shape, "has_chart", False) and shape.has_chart:
        model.add(design, page, model.shape("rect", x, y, w, h, fill="#f1f5f9", stroke="#94a3b8", stroke_w=2,
                                            text="Chart (kept in the original file)", color="#475569", size=28))
        return
    fill = None
    try:
        fill = _solid(shape.fill)
    except Exception:
        pass
    text = ""
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = "\n".join(p.text for p in shape.text_frame.paragraphs).strip("\n")
    is_title = False
    is_body = False
    try:
        if shape.is_placeholder:
            kind = str(shape.placeholder_format.type)
            is_title = "TITLE" in kind
            is_body = "BODY" in kind or "OBJECT" in kind
    except Exception:
        pass
    if text.strip():
        style = _run_style(shape, is_title)
        size = style["size_pt"] * 12700 * scale
        if is_body:
            text = "\n".join(f"•  {line}" if line.strip() else line for line in text.split("\n"))
        colour = style["color"] or model.readable_on(fill or page["bg"])
        props = dict(size=size, bold=style["bold"], italic=style["italic"], color=colour, align=style["align"],
                     font=style["font"],
                     rot=rot, autofit=True, role="title" if is_title else ("body" if is_body else ""))
        if fill and shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
            model.add(design, page, model.shape(_auto_kind(shape), x, y, w, h, fill=fill, text=text, **props))
        else:
            model.add(design, page, model.text(text, x, y, w, h, fill=fill, valign="middle" if is_title else "top",
                                               **props))
        return
    if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
        stroke = None
        try:
            stroke = "#" + str(shape.line.color.rgb).lower()
        except Exception:
            pass
        if fill or stroke:
            model.add(design, page, model.shape(_auto_kind(shape), x, y, w, h, fill=fill, stroke=stroke,
                                                stroke_w=3 if stroke else 0, rot=rot))


def _auto_kind(shape) -> str:
    try:
        name = shape.auto_shape_type.name if hasattr(shape.auto_shape_type, "name") else str(shape.auto_shape_type)
    except Exception:
        return "rect"
    for kind, mapped in SHAPE_MAP.items():
        if mapped == str(name).split(".")[-1].split(" ")[0]:
            return kind
    return "rect"


def _group_transform(shape, scale: float, parent: tuple) -> tuple:
    """Child coordinates of a group are in their own space; map them to the slide."""
    ox, oy, fx, fy = parent
    try:
        from pptx.oxml.ns import qn

        xfrm = shape._element.grpSpPr.find(qn("a:xfrm"))
        off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
        ch_off, ch_ext = xfrm.find(qn("a:chOff")), xfrm.find(qn("a:chExt"))
        sx = int(ext.get("cx")) / max(1, int(ch_ext.get("cx")))
        sy = int(ext.get("cy")) / max(1, int(ch_ext.get("cy")))
        gx = ox + (int(off.get("x")) - int(ch_off.get("x")) * sx) * scale * fx
        gy = oy + (int(off.get("y")) - int(ch_off.get("y")) * sy) * scale * fy
        return gx, gy, fx * sx, fy * sy
    except Exception:
        return parent
