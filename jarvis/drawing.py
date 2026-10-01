"""Pictures drawn with Pillow: mind maps, flowcharts and memes.

The model decides the content (as JSON); the layout is done here, so the
result is always legible: text is wrapped to fit its box and nothing is left
to a model's idea of coordinates.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PALETTE = ["#4F8EF7", "#F25F5C", "#43AA8B", "#F9A03F", "#9B5DE5", "#00BBF9", "#F15BB5", "#90BE6D"]
BG = "#FFFFFF"
INK = "#1F2430"


def font(size: int, bold: bool = False, family: str = "arial") -> ImageFont.ImageFont:
    names = {
        "arial": ("arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        "impact": ("impact.ttf", "DejaVuSans-Bold.ttf"),
    }[family]
    folders = [Path(r"C:\Windows\Fonts")] if sys.platform == "win32" else [
        Path("/usr/share/fonts/truetype/dejavu"), Path("/System/Library/Fonts/Supplemental")]
    for folder in folders:
        for name in names:
            if (folder / name).exists():
                return ImageFont.truetype(str(folder / name), size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, f) -> float:
    return draw.textlength(text, font=f)


def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if text_width(draw, trial, f) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def centered_text(draw, center: tuple[float, float], text: str, f, width: float, fill=INK, spacing: int = 4) -> None:
    lines = wrap(draw, text, f, width)
    height = sum(f.size + spacing for _ in lines) - spacing
    y = center[1] - height / 2
    for line in lines:
        draw.text((center[0] - text_width(draw, line, f) / 2, y), line, font=f, fill=fill)
        y += f.size + spacing


def text_box_size(draw, text: str, f, width: float, pad: int = 14, spacing: int = 4) -> tuple[float, float]:
    lines = wrap(draw, text, f, width)
    w = max(text_width(draw, l, f) for l in lines) + pad * 2
    h = len(lines) * (f.size + spacing) - spacing + pad * 2
    return w, h


# --- mind map ------------------------------------------------------------------

def mind_map(tree: dict, out: Path) -> Path:
    """{"center": str, "branches": [{"name": str, "children": [str]}]} -> PNG."""
    branches = [b for b in tree.get("branches", []) if isinstance(b, dict) and b.get("name")][:8]
    W, H = 2200, 1500
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    cx, cy = W / 2, H / 2
    big, mid, small = font(34, True), font(24, True), font(19)
    n = max(len(branches), 1)
    center = str(tree.get("center") or "Topic")
    cw, ch = text_box_size(draw, center, big, 300, pad=26)
    # Everything placed so far, as boxes; a group of children is pushed further
    # out until it overlaps none of them (two bottom branches used to collide).
    placed: list[tuple[float, float, float, float]] = [(cx - cw / 2 - 20, cy - ch / 2 - 10, cx + cw / 2 + 20, cy + ch / 2 + 10)]
    nodes = []
    for i, branch in enumerate(branches):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        bx, by = cx + math.cos(angle) * 430, cy + math.sin(angle) * 330
        bw, bh = text_box_size(draw, branch["name"], mid, 240)
        placed.append((bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2))
        nodes.append((branch, angle, bx, by, bw, bh, PALETTE[i % len(PALETTE)]))

    def clear(box) -> bool:
        return all(box[2] + 10 < p[0] or box[0] - 10 > p[2] or box[3] + 8 < p[1] or box[1] - 8 > p[3] for p in placed)

    leaves: list[tuple] = []
    for branch, angle, bx, by, bw, bh, color in nodes:
        children = [str(c) for c in branch.get("children", []) if str(c).strip()][:5]
        sizes = [text_box_size(draw, c, small, 200) for c in children]
        sideways = abs(math.cos(angle)) >= 0.45
        side = (1 if math.cos(angle) > 0 else -1) if sideways else (1 if math.sin(angle) > 0 else -1)
        for push in range(0, 600, 30):
            spots: list[tuple[float, float, float, float]] = []
            if sideways:      # a column further out
                column = bx + side * (bw / 2 + 70 + push + max((w for w, _ in sizes), default=0) / 2)
                total = sum(h for _, h in sizes) + 14 * (len(sizes) - 1)
                y = by - total / 2
                for w, h in sizes:
                    spots.append((column, y + h / 2, w, h))
                    y += h + 14
            else:             # a row beyond it
                row = by + side * (bh / 2 + 85 + push)
                total = sum(w for w, _ in sizes) + 16 * (len(sizes) - 1)
                x = bx - total / 2
                for w, h in sizes:
                    spots.append((x + w / 2, row, w, h))
                    x += w + 16
            spots = [(min(max(x, w / 2 + 20), W - w / 2 - 20), min(max(y, h / 2 + 20), H - h / 2 - 20), w, h)
                     for x, y, w, h in spots]
            boxes = [(x - w / 2, y - h / 2, x + w / 2, y + h / 2) for x, y, w, h in spots]
            if all(clear(b) for b in boxes):
                break
        placed.extend(boxes)
        leaves.extend((child, bx, by, kx, ky, w, h, color) for child, (kx, ky, w, h) in zip(children, spots))
    # Every line first, every box on top, so no line crosses another branch's box.
    for _, bx, by, kx, ky, _, _, color in leaves:
        draw.line([(bx, by), (kx, ky)], fill=color, width=3)
    for child, _, _, kx, ky, w, h, color in leaves:
        draw.rounded_rectangle([kx - w / 2, ky - h / 2, kx + w / 2, ky + h / 2], 12, fill="#F6F7F9", outline=color, width=2)
        centered_text(draw, (kx, ky), child, small, 200)
    for branch, angle, bx, by, bw, bh, color in nodes:
        draw.line([(cx, cy), (bx, by)], fill=color, width=7)
        draw.rounded_rectangle([bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2], 16, fill=color)
        centered_text(draw, (bx, by), branch["name"], mid, 240, fill="#FFFFFF")
    w, h = cw, ch
    draw.ellipse([cx - w / 2 - 20, cy - h / 2 - 10, cx + w / 2 + 20, cy + h / 2 + 10], fill=INK)
    centered_text(draw, (cx, cy), center, big, 300, fill="#FFFFFF")
    image.save(out)
    return out


# --- flowchart -------------------------------------------------------------------

def _levels(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    ids = [n["id"] for n in nodes]
    incoming = {i: 0 for i in ids}
    for e in edges:
        if e["to"] in incoming:
            incoming[e["to"]] += 1
    start = next((n["id"] for n in nodes if n.get("type") == "start"), None) or \
        next((i for i in ids if incoming[i] == 0), ids[0])
    level = {start: 0}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for e in edges:
            if e["from"] == current and e["to"] in incoming and e["to"] not in level:
                level[e["to"]] = level[current] + 1
                queue.append(e["to"])
    deepest = max(level.values(), default=0)
    for i in ids:
        if i not in level:
            deepest += 1
            level[i] = deepest
    return level


def flowchart(chart: dict, out: Path) -> Path:
    """{"nodes": [{"id", "text", "type": start|end|step|decision|io}], "edges": [{"from", "to", "label"}]}."""
    nodes = [n for n in chart.get("nodes", []) if isinstance(n, dict) and n.get("id")][:30]
    if not nodes:
        raise ValueError("no steps")
    for n in nodes:
        n["id"] = str(n["id"])
    known = {n["id"] for n in nodes}
    edges = [{"from": str(e.get("from")), "to": str(e.get("to")), "label": str(e.get("label") or "")}
             for e in chart.get("edges", []) if isinstance(e, dict) and str(e.get("from")) in known and str(e.get("to")) in known]
    level = _levels(nodes, edges)
    rows: dict[int, list[dict]] = {}
    for n in nodes:
        rows.setdefault(level[n["id"]], []).append(n)
    f, small = font(20), font(16)
    box_w, box_h, gap_y = 300, 90, 70
    width = max(1000, max(len(r) for r in rows.values()) * (box_w + 80) + 120)
    height = len(rows) * (box_h + gap_y) + 120
    image = Image.new("RGB", (int(width), int(height)), BG)
    draw = ImageDraw.Draw(image)
    pos: dict[str, tuple[float, float]] = {}
    for depth, row in sorted(rows.items()):
        y = 70 + depth * (box_h + gap_y) + box_h / 2
        for k, n in enumerate(row):
            x = width * (k + 1) / (len(row) + 1)
            pos[n["id"]] = (x, y)

    def arrow(a, b, label):
        (x1, y1), (x2, y2) = a, b
        if y2 > y1:
            start, end = (x1, y1 + box_h / 2), (x2, y2 - box_h / 2)
            draw.line([start, end], fill="#5A6170", width=3)
        else:   # a loop back up: go round the right-hand side
            side = max(x1, x2) + box_w / 2 + 40
            start, end = (x1 + box_w / 2, y1), (x2 + box_w / 2, y2)
            draw.line([start, (side, y1), (side, y2), end], fill="#5A6170", width=3)
            start = (side, y2)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        tip = [end, (end[0] - 14 * math.cos(angle - 0.4), end[1] - 14 * math.sin(angle - 0.4)),
               (end[0] - 14 * math.cos(angle + 0.4), end[1] - 14 * math.sin(angle + 0.4))]
        draw.polygon(tip, fill="#5A6170")
        if label:
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            lw = text_width(draw, label, small)
            draw.rectangle([mx - lw / 2 - 4, my - 11, mx + lw / 2 + 4, my + 11], fill=BG)
            draw.text((mx - lw / 2, my - 9), label, font=small, fill="#C0392B")

    for e in edges:
        arrow(pos[e["from"]], pos[e["to"]], e["label"])
    for n in nodes:
        x, y = pos[n["id"]]
        kind = str(n.get("type") or "step").lower()
        box = [x - box_w / 2, y - box_h / 2, x + box_w / 2, y + box_h / 2]
        if kind in {"start", "end"}:
            draw.ellipse(box, fill="#43AA8B" if kind == "start" else "#F25F5C")
            fill = "#FFFFFF"
        elif kind == "decision":
            draw.polygon([(x, box[1] - 8), (box[2] + 10, y), (x, box[3] + 8), (box[0] - 10, y)], fill="#FFF4D6", outline="#F9A03F", width=3)
            fill = INK
        elif kind == "io":
            draw.polygon([(box[0] + 25, box[1]), (box[2], box[1]), (box[2] - 25, box[3]), (box[0], box[3])], fill="#E8F1FE", outline="#4F8EF7", width=3)
            fill = INK
        else:
            draw.rounded_rectangle(box, 14, fill="#E8F1FE", outline="#4F8EF7", width=3)
            fill = INK
        centered_text(draw, (x, y), str(n.get("text") or n["id"]), f, box_w - 40 if kind != "decision" else box_w - 90, fill=fill)
    image.save(out)
    return out


# --- meme --------------------------------------------------------------------------

def meme(source: Path, top: str, bottom: str, out: Path) -> Path:
    image = Image.open(source).convert("RGB")
    if image.width < 600:
        image = image.resize((600, int(image.height * 600 / image.width)))
    draw = ImageDraw.Draw(image)
    for text, at_top in ((top, True), (bottom, False)):
        text = (text or "").strip().upper()
        if not text:
            continue
        size = max(28, image.width // 11)
        while size > 18:
            f = font(size, family="impact")
            lines = wrap(draw, text, f, image.width * 0.92)
            if len(lines) <= 3:
                break
            size -= 4
        block = len(lines) * (size + 6)
        y = image.height * 0.03 if at_top else image.height * 0.97 - block
        stroke = max(2, size // 14)
        for line in lines:
            x = (image.width - text_width(draw, line, f)) / 2
            draw.text((x, y), line, font=f, fill="#FFFFFF", stroke_width=stroke, stroke_fill="#000000")
            y += size + 6
    image.save(out)
    return out
