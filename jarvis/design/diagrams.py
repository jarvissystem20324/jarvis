"""Diagrams as editable designs: org charts, family trees, timelines, Gantt
charts, comparison tables, kanban boards, wireframes and mind maps.

The model (or the user, as an indented outline) supplies the structure; the
positions are computed here, so boxes never overlap and lines meet the boxes
they join. Every box is an ordinary shape on the page afterwards — drag it,
recolour it, retype it on the Design page like anything else.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from . import model, templates

W, H = 1920, 1080
LEVEL_COLORS = ["#1e3a8a", "#2563eb", "#0891b2", "#0d9488", "#7c3aed", "#db2777"]
GROUP_COLORS = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"]

PROMPTS = {
    "orgchart": '{"heading": "chart title", "name": "Name", "title": "Job title", "children": [ {"name": ..., '
                '"title": ..., "children": [...]} ]} — one root, at most 4 levels and 20 people',
    "familytree": '{"heading": "chart title", "name": "Name (born–died)", "spouse": "Name (born)", "children": '
                  '[ {same form} ]} — one root couple, at most 4 generations and 20 people; spouse may be empty',
    "timeline": '{"title": "...", "events": [{"date": "1923", "title": "2-5 words", "text": "one short sentence"}]} '
                '— 4 to 10 events in date order',
    "gantt": '{"title": "...", "tasks": [{"name": "2-5 words", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", '
             '"group": "phase name"}]} — 4 to 14 tasks; dates realistic and consecutive',
    "comparison": '{"title": "...", "columns": ["Feature", "Option A", "Option B"], "rows": [["Price", "...", "..."]]} '
                  '— 2-4 options, 4-9 rows, cells under 6 words; use ✓ and ✗ for yes/no',
    "kanban": '{"title": "...", "columns": [{"name": "To do", "cards": ["short task", ...]}]} '
              '— 3-5 columns, 1-5 cards each, cards under 7 words',
    "wireframe": '{"title": "screen name", "screen": "phone|desktop", "components": [{"type": "navbar|header|search|'
                 'text|image|button|input|card|list|tabs|avatar|footer", "label": "short label"}]} '
                 '— 5-12 components top to bottom, a realistic screen',
    "mindmap": '{"center": "short topic", "branches": [{"name": "2-4 words", "children": ["2-5 words", ...]}]} '
               '— 4-7 branches, 2-4 children each',
}


class Board:
    """A 16:9 diagram page with the helpers every layout needs."""

    def __init__(self, kind: str, title: str, bg: str = "#ffffff"):
        self.d = model.new_design("diagram", "diagram", title or kind.title())
        self.d["kind"] = "diagram"
        self.d["palette"] = ["#2563eb", "#0891b2", "#f59e0b", bg, "#0f172a"]
        self.d["fonts"] = {"heading": "Segoe UI", "body": "Segoe UI"}
        self.page = self.d["pages"][0]
        self.page["bg"] = bg

    def add(self, el: dict) -> dict:
        return model.add(self.d, self.page, el)

    def title(self, text: str, size: float = 54) -> None:
        if text:
            self.add(model.text(text, 80, 36, W - 160, 90, role="title", size=size, bold=True, color="#0f172a",
                                autofit=True, valign="middle"))

    def box(self, text: str, x, y, w, h, fill: str, color: str = "#ffffff", size: float = 30, **props) -> dict:
        return self.add(model.shape(props.pop("shape", "round"), x, y, w, h, fill=fill, text=text, color=color,
                                    size=size, radius=props.pop("radius", 18), role=props.pop("role", "node"), **props))

    def line(self, x1, y1, x2, y2, **props) -> dict:
        props.setdefault("stroke", "#94a3b8")
        props.setdefault("stroke_w", 4)
        return self.add(model.line(x1, y1, x2, y2, role=props.pop("role", "link"), **props))


# --- trees: org charts, family trees, mind maps -------------------------------------------------

def _tree(node, depth: int = 0) -> dict | None:
    if isinstance(node, str):
        return {"name": node, "children": []}
    if not isinstance(node, dict):
        return None
    children = [c for c in (_tree(c, depth + 1) for c in (node.get("children") or [])[:12]) if c] if depth < 5 else []
    return {"name": str(node.get("name") or node.get("center") or "?"), "title": str(node.get("title") or ""),
            "spouse": str(node.get("spouse") or ""), "children": children}


def _leaves(node: dict) -> int:
    return max(1, sum(_leaves(c) for c in node["children"])) if node["children"] else 1


def _depth(node: dict) -> int:
    return 1 + max((_depth(c) for c in node["children"]), default=0)


def _place(node: dict, left: float, unit: float, level: int, out: list) -> float:
    """Leaf-order layout: each node sits centred over its children. Returns its centre x."""
    if not node["children"]:
        cx = left + unit * _leaves(node) / 2
    else:
        x, centres = left, []
        for child in node["children"]:
            centres.append(_place(child, x, unit, level + 1, out))
            x += unit * _leaves(child)
        cx = (centres[0] + centres[-1]) / 2
    out.append((node, level, cx))
    return cx


def org_chart(data: dict, family: bool = False) -> dict:
    root = _tree(data.get("root", data) if isinstance(data, dict) else data) or {"name": "?", "children": []}
    heading = str(data.get("heading") or "")
    b = Board("familytree" if family else "orgchart", heading or ("Family tree" if family else "Org chart"))
    b.title(heading)
    top = 150 if heading else 70
    leaves, depth = _leaves(root), _depth(root)
    couple = family and any(n.get("spouse") for n, *_ in _walk(root))
    unit = (W - 100) / leaves
    level_h = (H - top - 50) / depth
    box_h = min(130.0, level_h * 0.62)
    single = min(320.0, unit * (0.42 if couple else 0.86))
    placed: list = []
    _place(root, 50, unit, 0, placed)
    centres: dict[int, tuple[float, float, float]] = {}
    for node, level, cx in placed:
        y = top + level * level_h
        width = single
        colour = LEVEL_COLORS[level % len(LEVEL_COLORS)]
        size = max(14.0, min(30.0, box_h * 0.24))
        label = node["name"] + (f"\n{node['title']}" if node.get("title") else "")
        if family and node.get("spouse"):
            gap = 30
            b.box(label, cx - width - gap / 2, y, width, box_h, colour, size=size)
            b.box(node["spouse"], cx + gap / 2, y, width, box_h, model.mix(colour, "#ffffff", 0.25), size=size)
            b.line(cx - gap / 2, y + box_h / 2, cx + gap / 2, y + box_h / 2, stroke=colour, stroke_w=5)
        else:
            b.box(label, cx - width / 2, y, width, box_h, colour, size=size)
        centres[id(node)] = (cx, y, y + box_h)
    for node, level, cx in placed:
        if not node["children"]:
            continue
        _, _, bottom = centres[id(node)]
        kids = [centres[id(c)] for c in node["children"]]
        mid = bottom + (kids[0][1] - bottom) / 2
        b.line(cx, bottom, cx, mid)
        if len(kids) > 1:
            b.line(kids[0][0], mid, kids[-1][0], mid)
        for kx, ky, _ in kids:
            b.line(kx, mid, kx, ky)
    # Lines first, boxes on top: the connectors were added after the boxes, so move them under.
    b.page["elements"].sort(key=lambda e: 0 if e.get("role") == "link" else (2 if e.get("role") == "title" else 1))
    return b.d


def _walk(node: dict, level: int = 0):
    yield node, level
    for child in node["children"]:
        yield from _walk(child, level + 1)


def mind_map(data: dict) -> dict:
    center = str(data.get("center") or data.get("name") or "Topic")
    branches = []
    for item in (data.get("branches") or data.get("children") or [])[:8]:
        if isinstance(item, str):
            branches.append({"name": item, "children": []})
        elif isinstance(item, dict):
            kids = [str(c.get("name") if isinstance(c, dict) else c) for c in (item.get("children") or [])][:5]
            branches.append({"name": str(item.get("name") or "?"), "children": kids})
    b = Board("mindmap", center, bg="#f8fafc")
    cx, cy = W / 2, H / 2
    right, left = branches[: (len(branches) + 1) // 2], branches[(len(branches) + 1) // 2:]
    links, nodes = [], []
    for side, items in ((1, right), (-1, left)):
        rows = sum(max(1, len(i["children"])) for i in items) or 1
        row_h = min(120.0, (H - 120) / rows)
        y = cy - rows * row_h / 2
        for n, item in enumerate(items):
            colour = templates.PALETTES["tech"][n % 3] if side == 1 else GROUP_COLORS[(n + 3) % len(GROUP_COLORS)]
            span = max(1, len(item["children"])) * row_h
            by = y + span / 2
            bx = cx + side * 420
            nodes.append(model.shape("round", bx - 150, by - 45, 300, 90, fill=colour, text=item["name"], size=30,
                                     bold=True, color="#ffffff", radius=45, role="branch"))
            links.append(model.line(cx + side * 190, cy, bx - side * 150, by, stroke=colour, stroke_w=6, role="link"))
            for k, child in enumerate(item["children"]):
                ky = y + k * row_h + row_h / 2
                near = cx + side * 630                 # the edge of the leaf nearest the centre
                nodes.append(model.text(child, near if side == 1 else near - 300, ky - row_h * 0.4, 300, row_h * 0.8,
                                        size=26, color="#0f172a", fill="#ffffff", radius=16, pad=10, autofit=True,
                                        align="left" if side == 1 else "right", valign="middle", role="leaf"))
                links.append(model.line(bx + side * 150, by, near, ky, stroke=colour, stroke_w=3, role="link"))
            y += span
    for el in links:
        b.add(el)
    for el in nodes:
        b.add(el)
    b.add(model.shape("ellipse", cx - 190, cy - 95, 380, 190, fill="#0f172a", text=center, size=40, bold=True,
                      color="#ffffff", role="center"))
    return b.d


# --- timelines and Gantt charts -------------------------------------------------------------------

def timeline(data: dict) -> dict:
    events = [e for e in (data.get("events") or []) if isinstance(e, dict)][:12]
    b = Board("timeline", str(data.get("title") or "Timeline"))
    b.title(str(data.get("title") or ""))
    n = max(1, len(events))
    axis = 600
    b.line(80, axis, W - 80, axis, stroke="#334155", stroke_w=8, arrow="end", role="axis")
    step = (W - 240) / n
    card_w = min(400.0, step * 1.75)
    for i, event in enumerate(events):
        x = 140 + step * i + step / 2
        colour = GROUP_COLORS[i % len(GROUP_COLORS)]
        up = i % 2 == 0
        b.add(model.shape("ellipse", x - 18, axis - 18, 36, 36, fill=colour, stroke="#ffffff", stroke_w=6,
                          role="dot"))
        b.add(model.text(str(event.get("date", "")), x - card_w / 2, axis + (30 if up else -80), card_w, 50,
                         size=30, bold=True, color=colour, align="center", role="date"))
        top = axis - 330 if up else axis + 110
        b.line(x, axis - 20 if up else axis + 20, x, top + 220 if up else top, stroke=colour, stroke_w=3, dash=True)
        label = str(event.get("title", ""))
        detail = str(event.get("text", ""))
        b.add(model.shape("round", x - card_w / 2, top, card_w, 220, fill=colour, text=label + (f"\n{detail}" if detail else ""),
                          size=26, color="#ffffff", radius=20, role="event", align="center"))
    b.page["elements"].sort(key=lambda e: 0 if e.get("role") in {"axis", "link"} else 1)
    return b.d


def _when(value) -> date | float | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(?:w(?:eek)?\s*)?(-?\d+(?:\.\d+)?)$", text, re.I)
    return float(m.group(1)) if m else None


def gantt(data: dict) -> dict:
    raw = [t for t in (data.get("tasks") or []) if isinstance(t, dict)][:16]
    tasks = []
    for t in raw:
        start, end = _when(t.get("start")), _when(t.get("end"))
        if start is None or end is None or type(start) is not type(end):
            continue
        tasks.append((str(t.get("name", "")), start, end, str(t.get("group") or "")))
    b = Board("gantt", str(data.get("title") or "Project plan"))
    b.title(str(data.get("title") or "Project plan"))
    if not tasks:
        b.add(model.text("No tasks with start and end dates.", 80, 300, 1700, 100, size=40, color="#64748b"))
        return b.d
    dated = isinstance(tasks[0][1], date)
    to_num = (lambda d: d.toordinal()) if dated else (lambda d: float(d))
    lo = min(to_num(t[1]) for t in tasks)
    hi = max(to_num(t[2]) for t in tasks)
    span = max(1.0, hi - lo + (1 if dated else 0))
    left, right, top = 460, W - 70, 190
    row_h = min(70.0, (H - top - 60) / len(tasks))
    groups: dict[str, str] = {}
    # Scale: weeks for a few months, months for longer, plain numbers otherwise.
    ticks = 8
    for k in range(ticks + 1):
        value = lo + span * k / ticks
        x = left + (right - left) * k / ticks
        if dated:
            label = date.fromordinal(int(value)).strftime("%d %b")
        else:
            label = f"{value:g}"
        b.line(x, top - 10, x, top + row_h * len(tasks), stroke="#e2e8f0", stroke_w=2, role="grid")
        b.add(model.text(label, x - 70, top - 60, 140, 40, size=22, color="#64748b", align="center", role="scale"))
    for i, (name, start, end, group) in enumerate(tasks):
        y = top + i * row_h
        colour = groups.setdefault(group, GROUP_COLORS[len(groups) % len(GROUP_COLORS)])
        b.add(model.text(name, 70, y, left - 90, row_h, size=min(28.0, row_h * 0.45), color="#0f172a",
                         valign="middle", autofit=True, role="task"))
        x0 = left + (right - left) * (to_num(start) - lo) / span
        x1 = left + (right - left) * (to_num(end) - lo + (1 if dated else 0)) / span
        b.add(model.shape("round", x0, y + row_h * 0.18, max(12.0, x1 - x0), row_h * 0.64, fill=colour,
                          radius=row_h * 0.32, role="bar", text=group if x1 - x0 > 160 and group else "",
                          size=min(22.0, row_h * 0.3), color="#ffffff"))
    b.page["elements"].sort(key=lambda e: 0 if e.get("role") == "grid" else 1)
    return b.d


# --- tables, boards, wireframes --------------------------------------------------------------------

def comparison(data: dict) -> dict:
    columns = [str(c) for c in (data.get("columns") or [])][:6]
    rows = [[str(c) for c in r][:len(columns) or 6] for r in (data.get("rows") or []) if isinstance(r, list)][:14]
    if not columns and rows:
        columns, rows = rows[0], rows[1:]
    b = Board("comparison", str(data.get("title") or "Comparison"))
    b.title(str(data.get("title") or "Comparison"))
    table = [columns or ["", ""]] + (rows or [[""] * len(columns or ["", ""])])
    height = min(860.0, 110 + 90 * (len(table) - 1))
    b.add(model.table(table, 80, 160, W - 160, height, size=34, fill="#1e3a8a", stripe="#eef2ff", role="table"))
    return b.d


def kanban(data: dict) -> dict:
    columns = [c for c in (data.get("columns") or []) if isinstance(c, dict)][:5] or [
        {"name": "To do", "cards": []}, {"name": "Doing", "cards": []}, {"name": "Done", "cards": []}]
    b = Board("kanban", str(data.get("title") or "Board"), bg="#eef2f7")
    b.title(str(data.get("title") or ""))
    top = 150 if data.get("title") else 60
    gap = 40
    col_w = (W - 160 - gap * (len(columns) - 1)) / len(columns)
    for i, col in enumerate(columns):
        x = 80 + i * (col_w + gap)
        colour = GROUP_COLORS[i % len(GROUP_COLORS)]
        cards = [str(c) for c in (col.get("cards") or [])][:7]
        b.add(model.shape("round", x, top, col_w, H - top - 50, fill="#ffffff", radius=24, role="column",
                          opacity=0.7))
        b.add(model.shape("round", x, top, col_w, 90, fill=colour, radius=24,
                          text=f"{col.get('name', '')}  ·  {len(cards)}", size=32, bold=True, role="header"))
        card_h = min(130.0, (H - top - 190) / max(1, len(cards)) - 18)
        for k, card in enumerate(cards):
            y = top + 115 + k * (card_h + 18)
            b.add(model.shape("round", x + 20, y, col_w - 40, card_h, fill="#ffffff", radius=16, shadow=True,
                              text=card, color="#0f172a", size=26, align="left", role="card",
                              stroke=colour, stroke_w=3))
    return b.d


WIRE = {"navbar": 90, "header": 120, "search": 80, "text": 110, "image": 260, "button": 90, "input": 80,
        "card": 200, "list": 240, "tabs": 80, "avatar": 140, "footer": 90}


def wireframe(data: dict) -> dict:
    phone = str(data.get("screen", "phone")).lower() != "desktop"
    comps = [c if isinstance(c, dict) else {"type": "text", "label": str(c)} for c in (data.get("components") or [])][:14]
    b = Board("wireframe", str(data.get("title") or "Wireframe"), bg="#f1f5f9")
    grey, dark, mid = "#e2e8f0", "#334155", "#94a3b8"
    if phone:
        fx, fy, fw, fh = W / 2 - 240, 40, 480, 1000
        b.add(model.shape("round", fx, fy, fw, fh, fill="#ffffff", stroke=dark, stroke_w=10, radius=60, role="frame"))
        b.add(model.shape("round", fx + fw / 2 - 70, fy + 20, 140, 26, fill=dark, radius=13, role="frame"))
        inner = (fx + 30, fy + 70, fw - 60, fh - 110)
        b.add(model.text(str(data.get("title") or ""), 100, 80, fx - 160, 300, size=54, bold=True, color=dark,
                         role="title", autofit=True))
    else:
        fx, fy, fw, fh = 120, 60, W - 240, 960
        b.add(model.shape("round", fx, fy, fw, fh, fill="#ffffff", stroke=dark, stroke_w=6, radius=18, role="frame"))
        b.add(model.shape("rect", fx + 3, fy + 3, fw - 6, 60, fill=grey, role="frame"))
        for k, c in enumerate(("#ef4444", "#f59e0b", "#22c55e")):
            b.add(model.shape("ellipse", fx + 24 + k * 36, fy + 20, 22, 22, fill=c, role="frame"))
        b.add(model.text(str(data.get("title") or ""), fx + 160, fy + 12, 800, 40, size=24, color=dark, role="title"))
        inner = (fx + 40, fy + 90, fw - 80, fh - 120)
    x, y, w, h = inner
    total = sum(WIRE.get(str(c.get("type")), 100) for c in comps) + 18 * len(comps)
    k = min(1.0, h / max(1, total))
    for comp in comps:
        kind = str(comp.get("type") or "text").lower()
        label = str(comp.get("label") or kind.title())
        ch = WIRE.get(kind, 100) * k
        if kind in {"navbar", "footer", "tabs"}:
            b.add(model.shape("rect", x, y, w, ch, fill=grey, text=label, color=dark, size=24 * max(k, 0.7), role=kind))
        elif kind == "header":
            b.add(model.text(label, x, y, w, ch, size=44 * max(k, 0.6), bold=True, color=dark, valign="middle",
                             autofit=True, role=kind))
        elif kind == "image":
            b.add(model.picture("", x, y, w, ch, role=kind))
        elif kind == "button":
            b.add(model.shape("round", x + w * 0.2, y, w * 0.6, ch, fill=dark, text=label, size=26 * max(k, 0.7),
                              color="#ffffff", radius=ch / 2, role=kind))
        elif kind in {"input", "search"}:
            b.add(model.shape("round", x, y, w, ch, fill="#ffffff", stroke=mid, stroke_w=3, radius=14,
                              text=("🔍 " if kind == "search" else "") + label, color=mid, size=24 * max(k, 0.7),
                              align="left", role=kind))
        elif kind == "avatar":
            b.add(model.shape("ellipse", x + w / 2 - ch / 2, y, ch, ch, fill=grey, role=kind))
        elif kind in {"card", "list"}:
            b.add(model.shape("round", x, y, w, ch, fill=grey, radius=16, role=kind))
            rows = 3 if kind == "list" else 2
            for r in range(rows):
                b.add(model.shape("round", x + 20, y + 20 + r * (ch - 40) / rows, w * (0.7 if r else 0.5),
                                  (ch - 40) / rows * 0.55, fill=mid if r == 0 else "#cbd5e1", radius=8,
                                  text=label if r == 0 else "", size=22 * max(k, 0.7), color="#ffffff", align="left",
                                  role=kind))
        else:
            b.add(model.text(label, x, y, w, ch, size=26 * max(k, 0.7), color="#475569", autofit=True, role=kind))
        y += ch + 18 * k
    return b.d


# --- the catalogue ---------------------------------------------------------------------------------

KINDS: dict[str, dict] = {
    "orgchart": {"label": "Org chart", "build": org_chart,
                 "sample": {"heading": "Our team", "name": "Ayşe Kaya", "title": "CEO", "children": [
                     {"name": "Mehmet", "title": "CTO", "children": [{"name": "Ali", "title": "Developer"},
                                                                      {"name": "Deniz", "title": "Designer"}]},
                     {"name": "Zeynep", "title": "CFO", "children": [{"name": "Can", "title": "Accountant"}]},
                     {"name": "Elif", "title": "Marketing", "children": [{"name": "Ece", "title": "Content"},
                                                                         {"name": "Emre", "title": "Ads"}]}]}},
    "familytree": {"label": "Family tree", "build": lambda d: org_chart(d, family=True),
                   "sample": {"heading": "The Yılmaz family", "name": "Hasan (1940–2015)", "spouse": "Fatma (1945)",
                              "children": [{"name": "Ahmet (1968)", "spouse": "Leyla (1970)",
                                            "children": [{"name": "Zahid (2000)"}, {"name": "Selin (2004)"}]},
                                           {"name": "Ayten (1972)", "spouse": "Murat (1969)",
                                            "children": [{"name": "Kerem (1999)"}]}]}},
    "timeline": {"label": "Timeline", "build": timeline,
                 "sample": {"title": "Our journey", "events": [
                     {"date": "2019", "title": "The idea", "text": "Two friends, one laptop"},
                     {"date": "2020", "title": "First users", "text": "100 people in a month"},
                     {"date": "2022", "title": "Funding", "text": "Seed round closed"},
                     {"date": "2024", "title": "Going global", "text": "Offices in 3 countries"},
                     {"date": "2026", "title": "JARVIS 9", "text": "The design page ships"}]}},
    "gantt": {"label": "Gantt chart", "build": gantt,
              "sample": {"title": "App launch plan", "tasks": [
                  {"name": "Research", "start": "2026-10-01", "end": "2026-10-10", "group": "Plan"},
                  {"name": "Wireframes", "start": "2026-10-08", "end": "2026-10-20", "group": "Design"},
                  {"name": "Visual design", "start": "2026-10-18", "end": "2026-11-02", "group": "Design"},
                  {"name": "Build the app", "start": "2026-10-25", "end": "2026-12-05", "group": "Build"},
                  {"name": "Testing", "start": "2026-11-28", "end": "2026-12-15", "group": "Build"},
                  {"name": "Launch", "start": "2026-12-15", "end": "2026-12-20", "group": "Launch"}]}},
    "comparison": {"label": "Comparison table", "build": comparison,
                   "sample": {"title": "Which phone?", "columns": ["", "Phone A", "Phone B", "Phone C"],
                              "rows": [["Price", "₺42,000", "₺35,000", "₺28,000"], ["Battery", "2 days", "1 day", "2 days"],
                                       ["Camera", "✓ Excellent", "✓ Good", "✗ Average"], ["5G", "✓", "✓", "✗"],
                                       ["Weight", "187 g", "201 g", "176 g"]]}},
    "kanban": {"label": "Kanban board", "build": kanban,
               "sample": {"title": "Sprint 12", "columns": [
                   {"name": "To do", "cards": ["Login screen", "Dark mode", "Export to PDF"]},
                   {"name": "Doing", "cards": ["Design page", "MCP server"]},
                   {"name": "Done", "cards": ["Slides themes", "Font picker", "Undo"]}]}},
    "wireframe": {"label": "App wireframe", "build": wireframe,
                  "sample": {"title": "Recipe app — home", "screen": "phone", "components": [
                      {"type": "navbar", "label": "≡   Recipes   ♡"}, {"type": "search", "label": "Search recipes"},
                      {"type": "tabs", "label": "Breakfast · Lunch · Dinner"}, {"type": "image", "label": "Hero"},
                      {"type": "header", "label": "Today's pick"}, {"type": "card", "label": "Lentil soup"},
                      {"type": "button", "label": "Start cooking"}, {"type": "footer", "label": "⌂   ★   ☺"}]}},
    "mindmap": {"label": "Mind map", "build": mind_map,
                "sample": {"center": "Healthy life", "branches": [
                    {"name": "Sleep", "children": ["8 hours", "Same bedtime", "No screens"]},
                    {"name": "Food", "children": ["Vegetables", "Water", "Less sugar"]},
                    {"name": "Exercise", "children": ["Walk daily", "Stretch"]},
                    {"name": "Mind", "children": ["Read", "Meditate", "Friends"]}]}},
}


def build(kind: str, data: dict) -> dict:
    spec = KINDS.get(kind)
    if spec is None:
        raise model.DesignError(f"Unknown diagram: {kind}")
    if not isinstance(data, dict):
        raise model.DesignError("The diagram data didn't come back in a usable form.")
    design = spec["build"](data)
    tree = kind in {"orgchart", "familytree"}
    design["title"] = str(data.get("heading") or (None if tree else data.get("title")) or data.get("center")
                          or spec["label"])[:80]
    return design


def sample(kind: str) -> dict:
    return build(kind, dict(KINDS[kind]["sample"]))


# --- plain-text input, so a diagram doesn't always need the model ------------------------------------

def parse_outline(text: str) -> dict | None:
    """An indented outline (spaces, tabs or '-' bullets) -> {"name", "children"}."""
    rows = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        leading = raw[:len(raw) - len(raw.lstrip())]
        bullets = re.match(r"^([-*•]+)\s*", raw.lstrip())
        indent = len(leading.expandtabs(4)) + (len(bullets.group(1)) * 2 if bullets else 0)
        name = raw.strip().lstrip("-*•").strip()
        rows.append((indent, name))
    if len(rows) < 2 or len({i for i, _ in rows}) < 2:
        return None
    root = {"name": rows[0][1], "children": []}
    stack = [(rows[0][0], root)]
    for indent, name in rows[1:]:
        node = {"name": name, "children": []}
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1]["children"].append(node)
        stack.append((indent, node))
    return root


def from_text(kind: str, text: str) -> dict | None:
    """Structure typed by hand: an outline for trees, 'date: event' lines for a
    timeline, 'task | start | end' for Gantt, 'a | b | c' rows for a table,
    'Column: card, card' lines for kanban. None if it doesn't look like that."""
    lines = [l for l in text.splitlines() if l.strip()]
    if kind in {"orgchart", "familytree"}:
        tree = parse_outline(text)
        if tree is None:
            return None
        if kind == "orgchart":
            def split(node):
                name, _, title = node["name"].partition(",")
                if not title:
                    name, _, title = node["name"].partition(" - ")
                return {"name": name.strip(), "title": title.strip(), "children": [split(c) for c in node["children"]]}
            return split(tree)

        def couple(node):
            name, _, spouse = node["name"].partition("+")
            return {"name": name.strip(), "spouse": spouse.strip(), "children": [couple(c) for c in node["children"]]}
        return couple(tree)
    if kind == "mindmap":
        tree = parse_outline(text)
        if tree is None:
            return None
        return {"center": tree["name"], "branches": [{"name": c["name"], "children": [g["name"] for g in c["children"]]}
                                                     for c in tree["children"]]}
    if kind == "timeline" and len(lines) >= 2 and all(re.match(r"^\s*[^:]{1,20}:\s*\S", l) for l in lines):
        events = []
        for l in lines:
            when, _, what = l.partition(":")
            title, _, rest = what.strip().partition(" - ")
            events.append({"date": when.strip(), "title": title.strip(), "text": rest.strip()})
        return {"events": events}
    if kind == "gantt" and len(lines) >= 1 and all(l.count("|") >= 2 for l in lines):
        tasks = []
        for l in lines:
            parts = [p.strip() for p in l.split("|")]
            tasks.append({"name": parts[0], "start": parts[1], "end": parts[2], "group": parts[3] if len(parts) > 3 else ""})
        return {"tasks": tasks}
    if kind == "comparison" and len(lines) >= 2 and all("|" in l for l in lines):
        rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
        rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
        return {"columns": rows[0], "rows": rows[1:]}
    if kind == "kanban" and len(lines) >= 2 and all(":" in l for l in lines):
        return {"columns": [{"name": l.partition(":")[0].strip(),
                             "cards": [c.strip() for c in re.split(r"[,;]", l.partition(":")[2]) if c.strip()]}
                            for l in lines]}
    return None
