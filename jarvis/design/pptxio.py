"""PowerPoint in and out.

Export maps each element onto a real PowerPoint object — text boxes stay
editable text, shapes stay shapes, tables stay tables, speaker notes go into
the notes pane — so "Open in PowerPoint" gives a deck you can keep working
on, not a slideshow of pictures. Only what PowerPoint has no equivalent for
(filtered or rounded photos, colour emoji icons, a ribbon) goes in as a
picture of itself.

Charts become real PowerPoint charts (their data opens in Excel from
PowerPoint), pen strokes become freeform shapes, pattern fills stay pattern
fills, groups stay groups, and slide transitions and entrance animations
are written into the slide the way PowerPoint itself writes them.

Import does the reverse as well as python-pptx allows: positions, text with
its size, colour and weight, pictures (with their crop), plain shapes,
lines, tables, charts (with their data), groups, the slide background and
the notes. SmartArt comes in as a labelled box rather than silently
disappearing.
"""

from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

from . import model, render

SHAPE_MAP = {"rect": "RECTANGLE", "round": "ROUNDED_RECTANGLE", "ellipse": "OVAL", "triangle": "ISOSCELES_TRIANGLE",
             "diamond": "DIAMOND", "pentagon": "REGULAR_PENTAGON", "hexagon": "HEXAGON", "star": "STAR_5_POINT",
             "burst": "STAR_16_POINT", "arrow": "RIGHT_ARROW", "chevron": "CHEVRON", "plus": "CROSS",
             "heart": "HEART", "bubble": "ROUNDED_RECTANGULAR_CALLOUT"}
CHART_MAP = {"bar": "COLUMN_CLUSTERED", "hbar": "BAR_CLUSTERED", "line": "LINE_MARKERS", "area": "AREA",
             "pie": "PIE", "doughnut": "DOUGHNUT"}
PATTERN_MAP = {"stripes": "WIDE_UPWARD_DIAGONAL", "dots": "PERCENT_20", "grid": "LARGE_GRID",
               "checks": "LARGE_CHECKER_BOARD", "lines": "LIGHT_HORIZONTAL", "waves": "WAVE"}
# Entrance effects: (PowerPoint preset id, subtype).
ANIM_PRESETS = {"appear": (1, 0), "fade": (10, 0), "fly": (2, 4), "zoom": (53, 16), "wipe": (22, 8)}
TRANSITION_ATTRS = {"fade": {}, "push": {"dir": "u"}, "wipe": {"dir": "r"}, "split": {"orient": "vert", "dir": "out"},
                    "cover": {"dir": "l"}, "zoom": {}}


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
            animated: list[tuple[int, str, bool]] = []
            done_groups: set[str] = set()
            elements = page["elements"]
            for n, el in enumerate(elements):
                group = el.get("group")
                if group:
                    if group in done_groups:
                        continue
                    done_groups.add(group)
                    members = [e for e in elements if e.get("group") == group]
                    holder = slide.shapes.add_group_shape()
                    for m, member in enumerate(members):
                        try:
                            _export(holder.shapes, member, emu, Path(tmp) / f"p{index}_{n}_{m}.png")
                        except Exception:
                            continue
                    if not len(holder.shapes):
                        holder._element.getparent().remove(holder._element)
                        continue
                    anim = next((e["anim"] for e in members if e.get("anim", "none") != "none"), "none")
                    if anim != "none":
                        animated.append((holder.shape_id, anim, False))
                    continue
                try:
                    shape = _export(slide.shapes, el, emu, Path(tmp) / f"p{index}_{n}.png")
                except Exception:
                    continue
                if shape is not None and el.get("anim", "none") != "none":
                    animated.append((shape.shape_id, el["anim"], _has_text(shape)))
            if page.get("notes"):
                slide.notes_slide.notes_text_frame.text = page["notes"]
            add_transition(slide, page.get("transition", "none"))
            add_animations(slide, animated)
        prs.save(str(path))
    return path


def _has_text(shape) -> bool:
    return shape._element.tag.endswith("}sp") and bool(getattr(shape, "has_text_frame", False)) \
        and bool(shape.text_frame.text.strip())


# --- transitions and animations -------------------------------------------------------------

def add_transition(slide, kind: str) -> None:
    """<p:transition> goes after the slide's colour map, before any <p:timing>."""
    if kind not in TRANSITION_ATTRS:
        return
    from pptx.oxml.ns import qn

    sld = slide._element
    transition = sld.makeelement(qn("p:transition"), {"spd": "med"})
    transition.append(transition.makeelement(qn(f"p:{kind}"), TRANSITION_ATTRS[kind]))
    anchor = sld.find(qn("p:clrMapOvr"))
    if anchor is None:
        anchor = sld.find(qn("p:cSld"))
    anchor.addnext(transition)


def _effect(spid: int, anim: str, ids) -> str:
    """One click's entrance effect for one shape, as PowerPoint writes it."""
    preset, subtype = ANIM_PRESETS[anim]
    target = f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    show = (f'<p:set><p:cBhvr><p:cTn id="{next(ids)}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/>'
            f'</p:stCondLst></p:cTn>{target}<p:attrNameLst><p:attrName>style.visibility</p:attrName>'
            f'</p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>')

    def move(attr: str, start: str, end: str) -> str:
        return (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{next(ids)}" dur="500" '
                f'fill="hold"/>{target}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>'
                f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="{start}"/></p:val></p:tav><p:tav tm="100000"><p:val>'
                f'<p:strVal val="{end}"/></p:val></p:tav></p:tavLst></p:anim>')

    def effect(name: str) -> str:
        return (f'<p:animEffect transition="in" filter="{name}"><p:cBhvr><p:cTn id="{next(ids)}" dur="500"/>{target}'
                f'</p:cBhvr></p:animEffect>')

    body = show
    if anim == "fade":
        body += effect("fade")
    elif anim == "wipe":
        body += effect("wipe(left)")
    elif anim == "fly":
        body += move("ppt_x", "#ppt_x", "#ppt_x") + move("ppt_y", "1+#ppt_h/2", "#ppt_y")
    elif anim == "zoom":
        body += move("ppt_w", "0", "#ppt_w") + move("ppt_h", "0", "#ppt_h") + effect("fade")
    outer, middle, inner = next(ids), next(ids), next(ids)
    return (f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
            f'<p:childTnLst><p:par><p:cTn id="{middle}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'<p:childTnLst><p:par><p:cTn id="{inner}" presetID="{preset}" presetClass="entr" '
            f'presetSubtype="{subtype}" fill="hold" grpId="0" nodeType="clickEffect"><p:stCondLst>'
            f'<p:cond delay="0"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst></p:cTn></p:par></p:childTnLst>'
            f'</p:cTn></p:par></p:childTnLst></p:cTn></p:par>')


def timing_xml(animated: list[tuple[int, str, bool]]) -> str:
    """The slide's <p:timing>: each animated shape comes in on its own click, in stacking order."""
    from pptx.oxml.ns import nsdecls

    ids = itertools.count(3)
    clicks = "".join(_effect(spid, anim, ids) for spid, anim, _ in animated if anim in ANIM_PRESETS)
    builds = "".join(f'<p:bldP spid="{spid}" grpId="0" animBg="1"/>' for spid, anim, text in animated
                     if text and anim in ANIM_PRESETS)
    return (f'<p:timing {nsdecls("p")}><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" '
            f'nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" '
            f'nodeType="mainSeq"><p:childTnLst>{clicks}</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" '
            f'delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" '
            f'delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn>'
            f'</p:par></p:tnLst>{f"<p:bldLst>{builds}</p:bldLst>" if builds else ""}</p:timing>')


def add_animations(slide, animated: list[tuple[int, str, bool]]) -> None:
    animated = [a for a in animated if a[1] in ANIM_PRESETS]
    if not animated:
        return
    from pptx.oxml import parse_xml
    from pptx.oxml.ns import qn

    sld = slide._element
    timing = parse_xml(timing_xml(animated))
    anchor = sld.find(qn("p:transition"))
    if anchor is None:
        anchor = sld.find(qn("p:clrMapOvr"))
    if anchor is None:
        anchor = sld.find(qn("p:cSld"))
    anchor.addnext(timing)


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


def _text_effects(run, el: dict, emu: float) -> None:
    """A text outline (<a:ln>, first in the run's properties) and a soft shadow (<a:effectLst>,
    after the colour): python-pptx has no setting for either."""
    from pptx.oxml.ns import qn

    rPr = run._r.get_or_add_rPr()
    if el.get("stroke") and el.get("stroke_w", 0) > 0:
        ln = rPr.makeelement(qn("a:ln"), {"w": str(max(3175, int(el["stroke_w"] * emu)))})
        fill = ln.makeelement(qn("a:solidFill"), {})
        fill.append(fill.makeelement(qn("a:srgbClr"), {"val": model.color(el["stroke"])[1:]}))
        ln.append(fill)
        rPr.insert(0, ln)
    if el.get("shadow"):
        size = el.get("size", 32) * emu
        effects = rPr.makeelement(qn("a:effectLst"), {})
        shadow = effects.makeelement(qn("a:outerShdw"), {"blurRad": str(int(size * 0.08)), "dist": str(int(size * 0.05)),
                                                         "dir": "2700000", "algn": "tl", "rotWithShape": "0"})
        colour = shadow.makeelement(qn("a:srgbClr"), {"val": "000000"})
        colour.append(colour.makeelement(qn("a:alpha"), {"val": "60000"}))
        shadow.append(colour)
        effects.append(shadow)
        fill = rPr.find(qn("a:solidFill"))
        if fill is not None:
            fill.addnext(effects)
        else:
            rPr.insert(1 if rPr.find(qn("a:ln")) is not None else 0, effects)


def _fill_text(frame, el: dict, size_px: float, emu: float, effects: bool = False) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu

    frame.word_wrap = True
    pad = Emu(int(el.get("pad", 0) * emu))
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = pad
    frame.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                             "bottom": MSO_ANCHOR.BOTTOM}[el.get("valign", "top")]
    align = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[el.get("align", "left")]
    lines = str(el.get("text", "")).split("\n")
    if el.get("curve"):
        lines = [" ".join(lines)]
        _warp(frame, el["curve"])
    for i, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.CENTER if el.get("curve") else align
        paragraph.line_spacing = el.get("line", 1.15)
        run = paragraph.add_run()
        run.text = line
        _font(run, el, size_px, emu)
        if effects:
            _text_effects(run, el, emu)


def _warp(frame, curve: float) -> None:
    """Curved text is WordArt's 'arch' warp: up for a rainbow, down for a smile."""
    from pptx.oxml.ns import qn

    body = frame._bodyPr
    warp = body.makeelement(qn("a:prstTxWarp"), {"prst": "textArchUp" if curve > 0 else "textArchDown"})
    warp.append(warp.makeelement(qn("a:avLst"), {}))
    body.insert(0, warp)


def _picture(shapes, el: dict, emu: float, tmp: Path):
    flat = model.clone(el)
    flat["rot"] = 0
    flat["opacity"] = el.get("opacity", 1.0)
    scale = min(2.0, max(0.5, 1600 / max(1.0, abs(el["w"]), abs(el["h"]))))
    builder = {"image": render.image_layer, "icon": render.icon_layer, "shape": render.shape_layer,
               "table": render.table_layer, "chart": render.chart_layer, "path": render.path_layer}[el["type"]]
    layer, pad = builder(flat, scale)
    if pad:
        layer = layer.crop((pad, pad, layer.width - pad, layer.height - pad))
    if flat["opacity"] < 1:
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * flat["opacity"])))
    layer.save(tmp)
    left, top, width, height = _box(el, emu)
    picture = shapes.add_picture(str(tmp), left, top, width, height)
    picture.rotation = el.get("rot", 0)
    return picture


def _chart(shapes, el: dict, emu: float):
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Pt

    from . import chart

    labels, series = chart.parse(el.get("rows") or [])
    if not series:
        raise ValueError("no numbers")
    kind = el.get("chart", "bar")
    pie = kind in {"pie", "doughnut"}
    data = CategoryChartData()
    data.categories = labels or [""]
    for name, values in series[:1] if pie else series:
        data.add_series(name, values)
    frame = shapes.add_chart(getattr(XL_CHART_TYPE, CHART_MAP.get(kind, "COLUMN_CLUSTERED")), *_box(el, emu), data)
    graph = frame.chart
    size = Pt(max(6.0, el.get("size", 26) * emu / 12700))
    graph.font.size = size
    graph.font.name = el.get("font") or "Segoe UI"
    graph.font.color.rgb = _rgb(el.get("color") or "#1f2430")
    graph.has_title = bool(el.get("title"))
    if el.get("title"):
        graph.chart_title.text_frame.text = el["title"]
        run = graph.chart_title.text_frame.paragraphs[0].runs[0]
        run.font.size = Pt(size.pt * 1.3)
        run.font.bold = True
        run.font.color.rgb = _rgb(el.get("color") or "#1f2430")
    graph.has_legend = bool(el.get("legend", True)) and (pie or len(series) > 1)
    if graph.has_legend:
        graph.legend.position = XL_LEGEND_POSITION.BOTTOM
        graph.legend.include_in_layout = False
    fills = chart.colours(el, len(labels) if pie else len(series))
    plot = graph.plots[0]
    if pie:
        for i, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = _rgb(fills[i % len(fills)])
    else:
        for i, line in enumerate(plot.series):
            if kind == "line":
                line.format.line.color.rgb = _rgb(fills[i])
                line.smooth = False
            else:
                line.format.fill.solid()
                line.format.fill.fore_color.rgb = _rgb(fills[i])
    if el.get("labels"):
        plot.has_data_labels = True
        labels_ = plot.data_labels
        labels_.font.size = size
        if pie:
            labels_.show_percentage, labels_.show_value = True, False
        else:
            labels_.show_value = True
    return frame


def _freeform(shapes, el: dict, emu: float):
    from pptx.util import Emu

    left, top, right, bottom = model.bbox(el)
    points = render.path_points(el, right - left, bottom - top, left, top)
    if len(points) < 2:
        raise ValueError("an empty stroke")
    builder = shapes.build_freeform(int(points[0][0] * emu), int(points[0][1] * emu), scale=1.0)
    builder.add_line_segments([(int(x * emu), int(y * emu)) for x, y in points[1:]], close=bool(el.get("closed")))
    shape = builder.convert_to_shape()
    if el.get("closed") and el.get("fill"):
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
    shape.rotation = el.get("rot", 0)
    return shape


def _export(shapes, el: dict, emu: float, tmp: Path):
    """One element onto a slide (or into a group's shapes). Returns the shape it made."""
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu, Pt

    kind = el["type"]
    if kind == "text":
        box = shapes.add_textbox(*_box(el, emu))
        size = render.fitted_size(el) if el.get("autofit") and not el.get("curve") else el["size"]
        _fill_text(box.text_frame, el, size, emu, effects=True)
        if el.get("fill"):
            box.fill.solid()
            box.fill.fore_color.rgb = _rgb(el["fill"])
            _alpha(box.fill, el.get("opacity", 1.0))
        box.rotation = el.get("rot", 0)
        return box
    if kind == "chart":
        try:
            return _chart(shapes, el, emu)
        except Exception:
            return _picture(shapes, el, emu, tmp)
    if kind == "path":
        return _freeform(shapes, el, emu)
    if kind == "shape":
        name = SHAPE_MAP.get(el["shape"])
        if name is None:
            return _picture(shapes, el, emu, tmp)
        shape = shapes.add_shape(getattr(MSO_SHAPE, name), *_box(el, emu))
        if el["shape"] == "round":
            try:
                shape.adjustments[0] = min(0.5, el.get("radius", 0) / max(1.0, min(el["w"], el["h"])))
            except (IndexError, ValueError):
                pass
        if el.get("fill") and el.get("pattern", "none") in PATTERN_MAP:
            from pptx.enum.dml import MSO_PATTERN

            shape.fill.patterned()
            shape.fill.pattern = getattr(MSO_PATTERN, PATTERN_MAP[el["pattern"]])
            shape.fill.fore_color.rgb = _rgb(el.get("pattern_color") or "#ffffff")
            shape.fill.back_color.rgb = _rgb(el["fill"])
        elif el.get("fill"):
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
        return shape
    if kind == "line":
        x0, y0 = el["x"], el["y"]
        x1, y1 = x0 + el["w"], y0 + el["h"]
        conn = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(int(x0 * emu)), Emu(int(y0 * emu)),
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
        return conn
    if kind in {"image", "icon"}:
        return _picture(shapes, el, emu, tmp)
    if kind == "table":
        if not hasattr(shapes, "add_table"):          # a group can't hold a table in PowerPoint
            return _picture(shapes, el, emu, tmp)
        rows = el["rows"]
        frame = shapes.add_table(len(rows), max(len(r) for r in rows), *_box(el, emu))
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
        return frame
    return None


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
            page["transition"] = _transition_of(slide)
            design["pages"].append(page)
    if not design["pages"]:
        design["pages"].append(model.new_page())
    first = next((e for e in design["pages"][0]["elements"] if e["type"] in {"text", "shape"} and e.get("text")), None)
    if first:
        design["title"] = first["text"].split("\n")[0][:80]
    return design


def _transition_of(slide) -> str:
    """The slide's transition, if it's one the editor knows (PowerPoint may wrap it in
    mc:AlternateContent, so look anywhere in the slide)."""
    try:
        from pptx.oxml.ns import qn

        for transition in slide._element.iter(qn("p:transition")):
            for child in transition:
                name = child.tag.rsplit("}", 1)[-1]
                if name in model.TRANSITIONS:
                    return name
    except Exception:
        pass
    return "none"


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
        before = len(page["elements"])
        for n, sub in enumerate(shape.shapes):
            try:
                _import_shape(design, page, sub, scale, child, tmp, f"{tag}_{n}")
            except Exception:
                continue
        members = page["elements"][before:]
        if len(members) > 1 and group == (0.0, 0.0, 1.0, 1.0):     # nested groups join the outermost one
            group_id = model.new_group_id(design)
            for el in members:
                el["group"] = group_id
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
        try:
            model.add(design, page, _import_chart(shape.chart, x, y, w, h, scale))
        except Exception:
            model.add(design, page, model.shape("rect", x, y, w, h, fill="#f1f5f9", stroke="#94a3b8", stroke_w=2,
                                                text="Chart (kept in the original file)", color="#475569", size=28))
        return
    if shape.shape_type == MSO_SHAPE_TYPE.FREEFORM:
        stroke = _line_colour(shape)
        points, closed = _freeform_points(shape)
        if len(points) >= 2:
            fill = _solid(shape.fill)
            width = max(1.0, (shape.line.width or 12700) * scale) if stroke else 0.0
            model.add(design, page, model.element("path", x=x, y=y, w=w, h=h, rot=rot, points=points, closed=closed,
                                                  stroke=stroke, stroke_w=width, fill=fill, smooth=False))
            return
    fill, pattern = None, {}
    try:
        fill = _solid(shape.fill)
        if fill is None:
            pattern = _patterned(shape.fill)
            fill = pattern.pop("fill", None)
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
            model.add(design, page, model.shape(_auto_kind(shape), x, y, w, h, fill=fill, text=text, **pattern,
                                                **props))
        else:
            model.add(design, page, model.text(text, x, y, w, h, fill=fill, valign="middle" if is_title else "top",
                                               **props))
        return
    if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
        stroke = _line_colour(shape)
        if fill or stroke:
            model.add(design, page, model.shape(_auto_kind(shape), x, y, w, h, fill=fill, stroke=stroke,
                                                stroke_w=3 if stroke else 0, rot=rot, **pattern))


def _line_colour(shape) -> str | None:
    try:
        if shape.line.fill.type is None or "BACKGROUND" in str(shape.line.fill.type):
            return None
        return "#" + str(shape.line.color.rgb).lower()
    except Exception:
        return None


def _patterned(fill) -> dict:
    """A pattern fill as the editor's pattern (the nearest one) on its back colour."""
    from pptx.enum.dml import MSO_FILL

    if fill.type != MSO_FILL.PATTERNED:
        return {}
    name = str(fill.pattern).split(".")[-1].split(" ")[0].upper()
    kind = next((k for k, v in PATTERN_MAP.items() if v == name), None)
    if kind is None:
        kind = ("stripes" if "DIAGONAL" in name else "grid" if "GRID" in name or "CROSS" in name else
                "checks" if "CHECKER" in name else "lines" if "HORIZONTAL" in name else "dots")
    return {"fill": "#" + str(fill.back_color.rgb).lower(), "pattern": kind,
            "pattern_color": "#" + str(fill.fore_color.rgb).lower()}


def _freeform_points(shape) -> tuple[list[list[float]], bool]:
    """A freeform's outline as fractions of its box (curves are followed by their end points)."""
    from pptx.oxml.ns import qn

    points, closed = [], False
    for path in shape._element.iter(qn("a:path")):
        pw, ph = float(path.get("w") or 0), float(path.get("h") or 0)
        if pw <= 0 or ph <= 0:
            continue
        for step in path:
            name = step.tag.rsplit("}", 1)[-1]
            if name == "close":
                closed = True
                continue
            pts = step.findall(qn("a:pt"))
            if pts:
                points.append([float(pts[-1].get("x")) / pw, float(pts[-1].get("y")) / ph])
        break
    return points, closed


def _import_chart(graph, x, y, w, h, scale) -> dict:
    """A PowerPoint chart back into an editable chart: its kind, its data and its title."""
    name = str(graph.chart_type).split(".")[-1].split(" ")[0].upper()
    kind = ("doughnut" if "DOUGHNUT" in name else "pie" if "PIE" in name else "hbar" if name.startswith("BAR")
            else "area" if "AREA" in name else "line" if "LINE" in name else "bar")
    plot = graph.plots[0]
    categories = [str(c) for c in plot.categories]
    series = list(plot.series)

    def cell(value) -> str:
        if value is None:
            return ""
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    rows = [[""] + [s.name or f"Series {i + 1}" for i, s in enumerate(series)]]
    for i, label in enumerate(categories):
        rows.append([label] + [cell(s.values[i]) if i < len(s.values) else "" for s in series])
    title = ""
    try:
        if graph.has_title:
            title = graph.chart_title.text_frame.text
    except Exception:
        pass
    props = {"title": title, "legend": bool(graph.has_legend), "size": max(10.0, min(w, h) * 0.045)}
    try:
        colour = series[0].format.fill.fore_color.rgb if kind not in {"line"} else None
        if colour is not None:
            props["fill"] = "#" + str(colour).lower()
    except Exception:
        pass
    return model.chart(kind, rows, x, y, w, h, **props)


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
