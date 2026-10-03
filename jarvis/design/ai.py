"""JARVIS's side of the Design page: designing from a description, edits in
plain words, "make it look better", a critique, palettes, fonts, the brand
kit, headlines, speaker notes, decks from YouTube and quiz slides.

What can be decided by rule is decided by rule — contrast is a formula, a
margin is a number — and the model is asked only for words and choices.
Edits the model proposes come back as a short list of operations that are
checked one by one (model.clean_value) before they touch the design, so a
confused reply changes nothing rather than corrupting a page.
"""

from __future__ import annotations

import base64
import io
import json
import re
from collections import Counter
from pathlib import Path

from .. import kit
from . import diagrams, model, render, templates

TEXT_ROLES_TITLE = {"title", "headline", "name", "monogram"}
DIAGRAMS = tuple(diagrams.KINDS)
TEMPLATE_KINDS = tuple(templates.KINDS)
ALL_KINDS = ("slides",) + TEMPLATE_KINDS + DIAGRAMS
FIELDS = {
    "thumbnail": '"headline": "2-5 punchy words", "sub": "short hook", "emoji": "one emoji"',
    "poster": '"headline": "...", "sub": "small line above it", "body": "1-2 sentences", "date": "...", '
              '"time": "...", "place": "...", "cta": "2-4 words"',
    "logo": '"name": "brand name", "tagline": "2-4 words", "icon": "one symbol like ★ ✦ ♥ ⚡ ☀ ✿"',
    "card": '"headline": "Happy Birthday! etc.", "message": "1-2 warm sentences", "from": "who it is from", '
            '"emoji": "one emoji"',
    "menu": '"name": "restaurant", "tagline": "...", "sections": [{"name": "Starters", "items": [{"name": "...", '
            '"desc": "few words", "price": "120"}]}], "footer": "address · phone", "currency": "₺"',
    "invitation": '"names": "A & B", "message": "a line above the names", "date": "...", "time": "...", '
                  '"place": "...", "rsvp": "RSVP line"',
    "sticker": '"text": "1-3 words", "sub": "1-3 words", "icon": "one symbol like ★ ✓ ♥ ⚡"',
    "sale": '"headline": "1-3 words", "discount": "50%", "sub": "...", "dates": "...", "cta": "2-3 words"',
    "slides": '"title": "...", "subtitle": "...", "slides": [{"title": "...", "bullets": ["under 12 words"], '
              '"notes": "2-3 sentences to say"}] — 6-10 slides',
}
THEME_BY_MOOD = {"dark": "neon", "night": "midnight", "tech": "midnight", "ai": "midnight", "nature": "forest",
                 "eco": "forest", "green": "forest", "kids": "classroom", "school": "classroom", "class": "classroom",
                 "fun": "candy", "playful": "candy", "luxury": "royal", "elegant": "royal", "warm": "sunset",
                 "sunset": "sunset", "coffee": "coffee", "cafe": "coffee", "minimal": "mono", "simple": "mono",
                 "business": "slate", "corporate": "slate", "ocean": "ocean", "sea": "ocean", "calm": "ocean",
                 "classic": "paper", "history": "paper", "literature": "paper"}
COLOR_WORDS = {"kırmızı": "red", "mavi": "blue", "yeşil": "green", "sarı": "yellow", "siyah": "black",
               "beyaz": "white", "mor": "purple", "turuncu": "orange", "pembe": "pink", "gri": "gray",
               "lacivert": "navy", "kahverengi": "brown", "altın": "gold", "turkuaz": "turquoise"}


class DesignAIError(Exception):
    pass


def _ask(brain, prompt: str, room: int = 6000):
    try:
        return kit.ask_json(brain, prompt, room=room)
    except kit.KitError as exc:
        raise DesignAIError(str(exc)) from None


def theme_for(mood: str) -> str:
    words = (mood or "").lower()
    for word, theme in THEME_BY_MOOD.items():
        if word in words:
            return theme
    return "midnight"


# --- describe it, JARVIS designs it --------------------------------------------------------------

def plan_prompt(description: str, kind: str | None = None) -> str:
    if kind:
        fields = FIELDS.get(kind) or diagrams.PROMPTS.get(kind, "")
        return (f"Write the content for a {kind} design: {description}\n"
                f'JSON: {{"kind": "{kind}", "mood": "one or two words", "variant": "", "content": {{{fields}}}}}'
                if kind in FIELDS else
                f"Write the content for a {kind} diagram: {description}\n"
                f'JSON: {{"kind": "{kind}", "content": {fields}}}') + (
            "\nAll text in the language of the request. Text goes on a design: keep it short and specific.")
    variants = "; ".join(f"{k}: {'|'.join(v['variants'])}" for k, v in templates.KINDS.items())
    field_lines = "\n".join(f"  {k}: {{{v}}}" for k, v in FIELDS.items())
    diagram_lines = "\n".join(f"  {k}: {v}" for k, v in diagrams.PROMPTS.items())
    return f"""Plan a design for: {description}
Pick the one kind that fits best: {", ".join(ALL_KINDS)}.
JSON: {{"kind": "...", "variant": "...", "mood": "one or two words for the colours", "content": {{...}}}}
Variants — {variants}. Leave variant empty for slides and diagrams.
content fields by kind:
{field_lines}
{diagram_lines}
All text in the language of the request. Text goes on a design: keep it short and specific, no placeholders."""


def build_from_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise DesignAIError("The plan didn't come back in a usable form. Try again.")
    kind = str(plan.get("kind") or "").lower().strip()
    content = plan.get("content") if isinstance(plan.get("content"), dict) else {}
    mood = str(plan.get("mood") or "")
    if kind == "slides" or (not kind and content.get("slides")):
        slides = [s for s in content.get("slides") or [] if isinstance(s, dict) and s.get("title")]
        if not slides:
            raise DesignAIError("No slides came back. Try again.")
        return templates.build_deck({**content, "slides": slides}, theme_for(mood))
    if kind in templates.KINDS:
        palette = templates.palette_for(mood)
        style = {"palette": palette} if palette else None
        return templates.make(kind, str(plan.get("variant") or ""), content, style)
    if kind in diagrams.KINDS:
        return diagrams.build(kind, content)
    raise DesignAIError(f"I can't make a '{kind or '?'}' yet. Try a poster, slides, a logo or a diagram.")


def design_from(brain, description: str, kind: str | None = None) -> dict:
    if kind in diagrams.KINDS:
        typed = diagrams.from_text(kind, description)
        if typed:
            return diagrams.build(kind, typed)
    plan = _ask(brain, plan_prompt(description, kind), room=7000)
    if kind and isinstance(plan, dict) and not plan.get("kind"):
        plan["kind"] = kind
    if kind in diagrams.KINDS and isinstance(plan, dict) and "content" not in plan:
        plan = {"kind": kind, "content": plan}
    return build_from_plan(plan)


# --- edits in plain words ---------------------------------------------------------------------------

def _targets(page: dict, words: str, selected: dict | None) -> list[dict]:
    els = page["elements"]
    if re.search(r"\b(title|headline|başlık)\b", words):
        found = [e for e in els if e.get("role") in TEXT_ROLES_TITLE]
        if not found:
            texts = [e for e in els if e["type"] in {"text", "shape"} and e.get("text")]
            found = sorted(texts, key=lambda e: -e.get("size", 0))[:1]
        return found[:1]
    if re.search(r"\b(subtitle|alt başlık)\b", words):
        return [e for e in els if e.get("role") == "subtitle"][:1]
    if re.search(r"\b(all text|everything|all|tüm yazı|hepsi|tümü)\b", words):
        return [e for e in els if e["type"] in {"text", "shape"} and e.get("text") and not e.get("locked")]
    return [selected] if selected else []


def quick_edit(design: dict, page: dict, instruction: str, selected: dict | None = None) -> str | None:
    """Simple single edits done on the spot, no model: bigger, bold, red, centre, delete…"""
    words = instruction.lower().strip().rstrip(".!")
    bg = re.match(r"^(?:make |set |change )?(?:the )?(?:background|bg|arka ?plan)(?: colou?r)?(?: to| =)?\s+(.+)$", words)
    if bg:
        value = model.color(COLOR_WORDS.get(bg.group(1).strip(), bg.group(1).strip()), None)
        if value:
            page["bg"] = value
            return f"Background set to {value}."
        return None
    if len(words.split()) > 7:
        return None
    targets = _targets(page, words, selected)
    if not targets:
        return None
    done: list[str] = []
    for el in targets:
        if re.search(r"\b(bigger|larger|büyüt|büyük)\b", words) and "size" in el:
            el["size"] = min(2000.0, el["size"] * 1.2)
            done.append("bigger")
        elif re.search(r"\b(smaller|küçült|küçük)\b", words) and "size" in el:
            el["size"] = max(6.0, el["size"] / 1.2)
            done.append("smaller")
        if re.search(r"\b(not bold|unbold)\b", words):
            el["bold"] = False
            done.append("not bold")
        elif re.search(r"\b(bold|kalın)\b", words) and "bold" in el:
            el["bold"] = True
            done.append("bold")
        if re.search(r"\b(italic|eğik)\b", words) and "italic" in el:
            el["italic"] = True
            done.append("italic")
        for word, align in (("center", "center"), ("centre", "center"), ("ortala", "center"), ("left", "left"),
                            ("right", "right"), ("sola", "left"), ("sağa", "right")):
            if re.search(rf"\b{word}\b", words) and "align" in el:
                el["align"] = align
                done.append(f"aligned {align}")
                break
        rotate = re.search(r"\b(?:rotate|döndür)\s*(-?\d{1,3})", words)
        if rotate:
            el["rot"] = float(rotate.group(1)) % 360
            done.append(f"rotated {rotate.group(1)}°")
        for word in re.findall(r"[a-zçğıöşü#0-9]+", words):
            name = COLOR_WORDS.get(word, word)
            if word in {"bold", "bigger", "smaller", "center", "left", "right", "title", "make", "the", "it", "this",
                        "text", "to", "and", "a", "all", "more", "headline", "rotate", "everything", "subtitle"}:
                continue
            value = model.color(name, None)
            if value and (word.startswith("#") or name.isalpha()):
                key = "fill" if el["type"] == "shape" and not el.get("text") or re.search(r"\b(fill|box|shape)\b", words) else (
                    "stroke" if el["type"] == "line" else "color")
                el[key] = value
                done.append(f"{key} {value}")
                break
    if re.search(r"\b(delete|remove|sil|kaldır)\b", words):
        for el in targets:
            if el in page["elements"]:
                page["elements"].remove(el)
        return f"Deleted {len(targets)} element(s)."
    if re.search(r"\b(duplicate|copy|kopyala|çoğalt)\b", words):
        for el in targets:
            model.duplicate(design, page, el)
        return "Duplicated."
    if re.search(r"\b(front|öne)\b", words):
        for el in targets:
            model.arrange(page, el, "front")
        done.append("brought to front")
    elif re.search(r"\b(back|arkaya)\b", words):
        for el in targets:
            model.arrange(page, el, "back")
        done.append("sent to back")
    if not done:
        return None
    return "Done: " + ", ".join(dict.fromkeys(done)) + "."


EDIT_PROMPT = """You are editing one page of a design ({w}x{h} px, origin top-left). Elements, bottom to top:
{elements}
Page background: {bg}. Palette: {palette}. {selected}
Request: {request}

Reply with JSON: {{"ops": [...], "say": "one short sentence about what you changed"}}
ops can be:
  {{"op": "set", "id": "e3", "props": {{"size": 72, "color": "#1e40af", "x": 100, "text": "..."}}}}
  {{"op": "add", "element": {{"type": "text|shape|line|icon", "x": 0, "y": 0, "w": 100, "h": 50, ...}}}}
  {{"op": "delete", "id": "e5"}}
  {{"op": "background", "color": "#ffffff"}}
  {{"op": "order", "id": "e2", "to": "front|back"}}
Properties: text, font, size (px), color, fill, stroke, stroke_w, bold, italic, align (left|center|right),
valign, x, y, w, h, rot, opacity (0-1), shape (rect|round|ellipse|star|...), glyph (for icons), autofit.
Change only what the request asks; keep everything inside the page; colours as #rrggbb."""


def edit_prompt(design: dict, page: dict, request: str, selected: dict | None) -> str:
    return EDIT_PROMPT.format(w=design["w"], h=design["h"],
                              elements=json.dumps(model.summary(page), ensure_ascii=False),
                              bg=page.get("bg"), palette=", ".join(design.get("palette") or []),
                              selected=f"The user has element {selected['id']} selected." if selected else "",
                              request=request)


def apply_ops(design: dict, page: dict, ops) -> int:
    """Apply the model's edit operations, checking each. Returns how many applied."""
    applied = 0
    for op in ops if isinstance(ops, list) else []:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        try:
            if kind == "set":
                el = model.find(page, str(op.get("id")))
                if el is None or not isinstance(op.get("props"), dict):
                    continue
                for key, value in op["props"].items():
                    try:
                        el[key] = model.clean_value(el["type"], key, value, el.get(key))
                    except KeyError:
                        continue
                if el["type"] != "line":
                    el["w"], el["h"] = max(1.0, el["w"]), max(1.0, el["h"])
                applied += 1
            elif kind == "add" and isinstance(op.get("element"), dict):
                el = dict(op["element"])
                el.pop("id", None)
                el = model.clean_element({**model.element(str(el.get("type", "text"))), **el})
                model.add(design, page, el)
                applied += 1
            elif kind == "delete":
                el = model.find(page, str(op.get("id")))
                if el is not None:
                    page["elements"].remove(el)
                    applied += 1
            elif kind == "background":
                value = model.color(op.get("color"), None)
                if value:
                    page["bg"] = value
                    applied += 1
            elif kind == "order":
                el = model.find(page, str(op.get("id")))
                if el is not None:
                    model.arrange(page, el, "front" if op.get("to") != "back" else "back")
                    applied += 1
        except (model.DesignError, KeyError, TypeError, ValueError):
            continue
    return applied


def chat_edit(brain, design: dict, page: dict, request: str, selected: dict | None = None) -> str:
    quick = quick_edit(design, page, request, selected)
    if quick:
        return quick
    reply = _ask(brain, edit_prompt(design, page, request, selected), room=4000)
    if not isinstance(reply, dict):
        raise DesignAIError("The change didn't come back in a usable form. Try again.")
    count = apply_ops(design, page, reply.get("ops"))
    if not count:
        return "I couldn't work out a change from that. Try naming the element: “make the title red”."
    return str(reply.get("say") or f"{count} change(s) made.")[:300]


# --- looking good: polish, critique, resize ------------------------------------------------------------

def _behind(page: dict, el: dict) -> str:
    """The colour under the middle of an element: the topmost filled thing beneath it, else the page."""
    cx, cy = model.center(el)
    index = page["elements"].index(el) if el in page["elements"] else len(page["elements"])
    for other in reversed(page["elements"][:index]):
        if other["type"] in {"shape", "text"} and other.get("fill") and other.get("opacity", 1) > 0.5 \
                and model.contains(other, cx, cy):
            return other["fill"]
        if other["type"] == "table" and model.contains(other, cx, cy):
            return other.get("bg") or "#ffffff"
    return page.get("bg") or "#ffffff"


def _text_colour_ok(page: dict, el: dict, height: float) -> tuple[bool, str, float]:
    bg = el.get("fill") if el["type"] == "shape" and el.get("fill") else _behind(page, el)
    if el["type"] == "text" and el.get("fill"):
        bg = el["fill"]
    ratio = model.contrast(el.get("color") or "#000000", bg)
    large = el.get("size", 0) >= height * 0.045 or (el.get("bold") and el.get("size", 0) >= height * 0.035)
    return ratio >= (3.0 if large else 4.5), bg, ratio


def _texts(page: dict) -> list[dict]:
    return [e for e in page["elements"] if e["type"] in {"text", "shape"} and e.get("text", "").strip()]


def _full_bleed(el: dict, W: float, H: float) -> bool:
    """Decoration meant to run off the edges (bands, big circles), which polish leaves alone."""
    left, top, right, bottom = model.bbox(el)
    if el.get("role") in {"deco", "background"}:
        return True
    if el["type"] == "text":
        return False
    return (right - left) >= W * 0.9 or (bottom - top) >= H * 0.9 \
        or left < -W * 0.02 or top < -H * 0.02 or right > W * 1.02 or bottom > H * 1.02


def polish(design: dict, index: int) -> list[str]:
    """'Make it look better': margins, alignment, type sizes, contrast, overflow, fonts."""
    page = design["pages"][index]
    W, H = design["w"], design["h"]
    margin = min(W, H) * 0.045
    notes: list[str] = []
    movable = [e for e in page["elements"] if not e.get("locked") and e["type"] != "line" and not _full_bleed(e, W, H)]
    # 1. inside the margins
    moved = 0
    for el in movable:
        left, top, right, bottom = model.bbox(el)
        dx = margin - left if left < margin else (W - margin - right if right > W - margin else 0)
        dy = margin - top if top < margin else (H - margin - bottom if bottom > H - margin else 0)
        if dx or dy:
            if right - left > W - 2 * margin:
                el["x"], el["w"], dx = margin, W - 2 * margin, 0
            if bottom - top > H - 2 * margin:
                el["y"], el["h"], dy = margin, H - 2 * margin, 0
            model.move(el, dx, dy)
            moved += 1
    if moved:
        notes.append(f"moved {moved} element(s) inside the margins")
    # 2. near-miss alignment: left edges, and centres close to the page centre
    snapped = 0
    lefts = sorted(movable, key=lambda e: e["x"])
    for i, el in enumerate(lefts):
        for other in lefts[:i]:
            if 0 < abs(el["x"] - other["x"]) <= W * 0.02 and el.get("align", "left") == other.get("align", "left"):
                el["x"] = other["x"]
                snapped += 1
                break
    for el in movable:
        cx = model.center(el)[0]
        if 0 < abs(cx - W / 2) <= W * 0.025 and (el.get("align") == "center" or el["type"] != "text"):
            el["x"] += W / 2 - cx
            snapped += 1
    if snapped:
        notes.append(f"lined up {snapped} edge(s)")
    # 3. type hierarchy and minimum size
    texts = _texts(page)
    if texts:
        titles = [e for e in texts if e.get("role") in TEXT_ROLES_TITLE] or [max(texts, key=lambda e: e.get("size", 0))]
        others = [e for e in texts if e not in titles]
        floor = H * 0.018
        raised = 0
        for el in others:
            if el.get("size", 0) < floor:
                el["size"] = floor
                raised += 1
        if raised:
            notes.append(f"made {raised} small text(s) readable")
        body = max((e.get("size", 0) for e in others), default=0)
        for title in titles:
            if body and title.get("size", 0) < body * 1.5:
                title["size"] = body * 1.6
                title["autofit"] = True
                notes.append("made the title stand out")
    # 4. contrast
    fixed = 0
    for el in texts:
        ok, bg, _ = _text_colour_ok(page, el, H)
        if not ok:
            candidates = [c for c in (design.get("palette") or []) + ["#111827", "#ffffff"]
                          if model.contrast(c, bg) >= 4.5]
            el["color"] = candidates[0] if candidates else model.readable_on(bg)
            fixed += 1
    if fixed:
        notes.append(f"fixed contrast on {fixed} text(s)")
    # 5. overflow
    spilled = 0
    for el in texts:
        if el["type"] == "text" and not el.get("autofit") and not render.fits(el):
            el["autofit"] = True
            spilled += 1
    if spilled:
        notes.append(f"shrank {spilled} overflowing text box(es) to fit")
    # 6. at most two font families
    families = Counter(e.get("font") for e in texts)
    if len(families) > 2:
        heading = Counter(e.get("font") for e in texts if e.get("role") in TEXT_ROLES_TITLE).most_common(1)
        body_font = Counter(e.get("font") for e in texts if e.get("role") not in TEXT_ROLES_TITLE).most_common(1)
        h_font = heading[0][0] if heading else families.most_common(1)[0][0]
        b_font = body_font[0][0] if body_font else h_font
        for el in texts:
            el["font"] = h_font if el.get("role") in TEXT_ROLES_TITLE else b_font
        notes.append(f"cut {len(families)} fonts down to two")
    # 7. text boxes on top of each other
    pushed = 0
    boxes = sorted([e for e in texts if e in movable and e["type"] == "text"], key=lambda e: e["y"])
    for i, el in enumerate(boxes):
        for upper in boxes[:i]:
            ul, ut, ur, ub = model.bbox(upper)
            l, t, r, b = model.bbox(el)
            overlap_x = min(ur, r) - max(ul, l)
            if overlap_x > 0 and t < ub and t >= ut and ub + margin * 0.3 + (b - t) <= H - margin:
                el["y"] = ub + margin * 0.3
                pushed += 1
    if pushed:
        notes.append(f"separated {pushed} overlapping text box(es)")
    return notes


def critique(design: dict, index: int) -> list[str]:
    """What a careful designer would point out, by rule."""
    page = design["pages"][index]
    W, H = design["w"], design["h"]
    issues: list[str] = []
    texts = _texts(page)
    if not page["elements"]:
        return ["The page is empty."]
    for el in texts:
        ok, bg, ratio = _text_colour_ok(page, el, H)
        if not ok:
            issues.append(f"Low contrast ({ratio:.1f}:1) on “{el['text'][:30]}” — hard to read on {bg}.")
        if el.get("size", 0) < H * 0.016:
            issues.append(f"“{el['text'][:30]}” is very small ({el['size']:.0f}px on a {H}px page).")
        if el["type"] == "text" and not el.get("autofit") and not render.fits(el):
            issues.append(f"“{el['text'][:30]}” spills out of its box.")
    families = {e.get("font") for e in texts}
    if len(families) > 2:
        issues.append(f"{len(families)} different fonts — two (one for headings, one for text) look calmer.")
    colours = {e.get("color") for e in texts} | {e.get("fill") for e in page["elements"] if e.get("fill")}
    if len(colours) > 7:
        issues.append(f"{len(colours)} different colours — a palette of 3-5 feels more designed.")
    words = sum(len(e["text"].split()) for e in texts)
    if design.get("kind") == "slides" and words > 70:
        issues.append(f"{words} words on one slide — audiences read or listen, rarely both. Move detail to notes.")
    for el in page["elements"]:
        left, top, right, bottom = model.bbox(el)
        if (right < 0 or bottom < 0 or left > W or top > H) and el.get("role") != "deco":
            issues.append(f"An element ({el['type']} {el['id']}) is off the page.")
    margin = min(W, H) * 0.03
    tight = [e for e in texts if not _full_bleed(e, W, H) and (
        model.bbox(e)[0] < margin or model.bbox(e)[1] < margin or model.bbox(e)[2] > W - margin
        or model.bbox(e)[3] > H - margin)]
    if tight:
        issues.append(f"{len(tight)} text(s) sit right against the edge — give them breathing room.")
    lefts = sorted(e["x"] for e in texts if e.get("align", "left") == "left")
    near = sum(1 for a, b in zip(lefts, lefts[1:]) if 0 < b - a <= W * 0.015)
    if near:
        issues.append(f"{near} text(s) almost line up but not quite — snap their left edges together.")
    if not issues:
        issues.append("Nothing obvious to fix: readable contrast, sizes and margins.")
    return issues


def critique_ai(brain, design: dict, index: int, findings: list[str]) -> str:
    image = render.render_page(design, index, min(1.0, 1024 / max(design["w"], design["h"])))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    prompt = (f"You are a friendly senior graphic designer reviewing this {design.get('kind', 'design')}. "
              f"Automatic checks found: {'; '.join(findings)}\n"
              "Give 3-5 short, specific suggestions (layout, hierarchy, colour, wording), best first, as a list. "
              "Say what is good too, in one line. No preamble.")
    try:
        answer = brain.ask_once(prompt, image_b64=base64.b64encode(buffer.getvalue()).decode("ascii"))
    except Exception:
        answer = ""
    if not answer or answer.startswith(("No AI provider", "Error")) or "vision" in answer.lower()[:80]:
        text = model.page_text(design["pages"][index])[:1500]
        answer = brain.ask_once(f"{prompt}\nYou can't see the image; here is its text:\n{text}")
    return answer.strip()


def resize(design: dict, fmt: str) -> dict:
    """The same design at another size — 'resize to every format'."""
    if fmt not in model.FORMATS:
        raise DesignAIError(f"Unknown format: {fmt}")
    _, W2, H2 = model.FORMATS[fmt]
    W, H = design["w"], design["h"]
    sx, sy = W2 / W, H2 / H
    s = min(sx, sy)
    out = model.copy_design(design, f"{design['title']} — {model.FORMATS[fmt][0]}")
    out["format"], out["w"], out["h"] = fmt, W2, H2
    for page in out["pages"]:
        for el in page["elements"]:
            if el["type"] == "line":
                el["x"], el["y"], el["w"], el["h"] = el["x"] * sx, el["y"] * sy, el["w"] * sx, el["h"] * sy
                el["stroke_w"] = max(1.0, el["stroke_w"] * s)
                continue
            if _full_bleed(el, W, H):
                el["x"], el["y"], el["w"], el["h"] = el["x"] * sx, el["y"] * sy, el["w"] * sx, el["h"] * sy
                if el["type"] in {"icon"} or el.get("shape") in {"ellipse", "star", "burst", "heart"}:
                    side = min(el["w"], el["h"])
                    cx, cy = model.center(el)
                    el["x"], el["y"], el["w"], el["h"] = cx - side / 2, cy - side / 2, side, side
            else:
                cx, cy = model.center(el)
                if el["type"] == "text" or (el["type"] == "shape" and el.get("text")):
                    # Text boxes keep their share of the page width, so words don't pile up into towers.
                    w = min(W2 * 0.92, max(el["w"] * s, el["w"] * sx * 0.9))
                    h = el["h"] * s * (el["w"] * s / w if w > el["w"] * s else 1) + el["h"] * max(0.0, sy - s) * 0.5
                else:
                    w, h = el["w"] * s, el["h"] * s
                el["w"], el["h"] = w, h
                el["x"], el["y"] = cx * sx - w / 2, cy * sy - h / 2
            for key in ("size", "stroke_w", "radius", "pad"):
                if key in el and isinstance(el[key], (int, float)):
                    el[key] = el[key] * s if key != "size" else max(6.0, el[key] * s)
            if el["type"] in {"text", "shape"} and el.get("text"):
                el["autofit"] = True
    for i in range(len(out["pages"])):
        polish(out, i)
    return out


# --- colours and fonts -----------------------------------------------------------------------------------

def palette_from_photo(path: Path) -> list[str]:
    colours = render.dominant_colors(Path(path), 6)
    if not colours:
        raise DesignAIError("That picture doesn't have any colour to take.")
    while len(colours) < 3:
        # A two-colour logo still makes a palette: tints of what is there.
        base = colours[0]
        colours.append(model.mix(base, "#ffffff" if model.luminance(base) < 0.5 else "#000000", 0.3 * len(colours)))
    by_light = sorted(colours, key=model.luminance)
    dark, light = by_light[0], by_light[-1]
    middle = [c for c in colours if c not in {dark, light}]

    def saturation(c):
        r, g, b = model.rgb(c)
        return max(r, g, b) - min(r, g, b)

    middle.sort(key=saturation, reverse=True)
    while len(middle) < 3:
        middle.append(model.mix(dark, light, 0.5))
    if model.luminance(light) < 0.7:
        light = model.mix(light, "#ffffff", 0.8)
    if model.luminance(dark) > 0.08:
        dark = model.mix(dark, "#000000", 0.6)
    return [middle[0], middle[1], middle[2], light, dark]


def palette_from_mood(brain, mood: str) -> tuple[list[str], str]:
    known = templates.palette_for(mood)
    if known:
        return known, "from the built-in palettes"
    reply = _ask(brain, f'A 5-colour palette for this mood: "{mood}". JSON: {{"name": "2 words", "colors": '
                        '["#primary", "#secondary", "#accent", "#very light background", "#very dark text"]}', room=800)
    colours = [model.color(c, None) for c in (reply.get("colors") if isinstance(reply, dict) else []) or []]
    colours = [c for c in colours if c][:5]
    if len(colours) < 5:
        raise DesignAIError("No palette came back. Try another word: calm, luxury, retro…")
    return colours, str(reply.get("name") or mood)


def used_colours(design: dict) -> list[str]:
    counts: Counter = Counter()
    for page in design["pages"]:
        counts[page.get("bg")] += 3
        for el in page["elements"]:
            for key in model.COLOR_KEYS:
                if el.get(key):
                    counts[el[key]] += 1
    return [c for c, _ in counts.most_common(5) if c]


def apply_palette(design: dict, colours: list[str]) -> int:
    """Swap the design's palette for a new one, colour by colour, then repair contrast."""
    new = [model.color(c, "#000000") for c in colours][:5]
    while len(new) < 5:
        new.append(new[-1] if new else "#000000")
    old = list(design.get("palette") or used_colours(design))[:5]
    mapping = {o.lower(): n for o, n in zip(old, new) if o}
    changed = 0
    for page in design["pages"]:
        if page.get("bg", "").lower() in mapping:
            page["bg"] = mapping[page["bg"].lower()]
            changed += 1
        for el in page["elements"]:
            for key in model.COLOR_KEYS:
                value = el.get(key)
                if isinstance(value, str) and value.lower() in mapping:
                    el[key] = mapping[value.lower()]
                    changed += 1
    design["palette"] = new
    for i, page in enumerate(design["pages"]):
        for el in _texts(page):
            ok, bg, _ = _text_colour_ok(page, el, design["h"])
            if not ok:
                choices = [c for c in new + ["#111827", "#ffffff"] if model.contrast(c, bg) >= 4.5]
                el["color"] = choices[0] if choices else model.readable_on(bg)
    return changed


def apply_fonts(design: dict, heading: str, body: str) -> int:
    changed = 0
    for page in design["pages"]:
        for el in page["elements"]:
            if el["type"] in {"text", "shape", "table"} and "font" in el:
                el["font"] = heading if el.get("role") in TEXT_ROLES_TITLE | {"subtitle"} else body
                changed += 1
    design["fonts"] = {"heading": heading, "body": body}
    return changed


def font_suggestions(brain, mood: str, count: int = 4) -> list[tuple[str, str, str]]:
    pairs = templates.font_pairs(mood)
    if not pairs:
        return []
    words = [w for w in mood.lower().split() if len(w) > 2]
    if words and not any(w in pairs[0][2] for w in words) and brain is not None:
        listing = "\n".join(f"{i}: {h} + {b} ({v})" for i, (h, b, v) in enumerate(pairs))
        try:
            reply = _ask(brain, f'Which of these font pairings suit "{mood}"? Best first.\n{listing}\n'
                                'JSON: {"pick": [index, index, index]}', room=400)
            picks = [int(i) for i in reply.get("pick", []) if str(i).isdigit() and int(i) < len(pairs)]
            if picks:
                ordered = [pairs[i] for i in dict.fromkeys(picks)]
                return (ordered + [p for p in pairs if p not in ordered])[:count]
        except (DesignAIError, AttributeError, TypeError, ValueError):
            pass
    return pairs[:count]


# --- the brand kit ----------------------------------------------------------------------------------------

BRAND = kit.Store("brand.json", {"name": "", "colors": [], "heading": "", "body": "", "logo": ""})


def apply_brand(design: dict, brand: dict | None = None) -> list[str]:
    brand = brand or BRAND.load()
    done: list[str] = []
    colours = [c for c in (brand.get("colors") or []) if model.color(c, None)]
    if len(colours) >= 3:
        apply_palette(design, colours)
        done.append("brand colours")
    if brand.get("heading") or brand.get("body"):
        apply_fonts(design, brand.get("heading") or brand.get("body"), brand.get("body") or brand.get("heading"))
        done.append("brand fonts")
    logo = brand.get("logo")
    if logo and model.resolve_src(logo):
        W, H = design["w"], design["h"]
        size = min(W, H) * (0.08 if design.get("kind") == "slides" else 0.12)
        pages = design["pages"] if design.get("kind") == "slides" else design["pages"][:1]
        for page in pages:
            page["elements"] = [e for e in page["elements"] if e.get("role") != "logo"]
            margin = min(W, H) * 0.035
            model.add(design, page, model.picture(logo, W - size - margin, H - size - margin if design.get("kind") ==
                                                  "slides" else margin, size, size, role="logo", fit="contain"))
        done.append("logo")
    return done


# --- words: headlines, notes ---------------------------------------------------------------------------------

def headlines(brain, topic: str, count: int = 6) -> list[str]:
    reply = _ask(brain, f"Write {count} different short headlines for: {topic}\n"
                        "Mix styles: a question, a number, a bold claim, a benefit, playful. Under 8 words each. "
                        'Same language as the request. JSON: {"headlines": ["..."]}', room=800)
    items = reply.get("headlines") if isinstance(reply, dict) else reply
    out = [str(h).strip().strip('"') for h in items or [] if str(h).strip()][:count]
    if not out:
        raise DesignAIError("No headlines came back. Try again.")
    return out


def speaker_notes(brain, design: dict, pages: list[int] | None = None) -> int:
    indexes = pages if pages is not None else list(range(len(design["pages"])))
    listing = [{"slide": i + 1, "text": model.page_text(design["pages"][i])[:600]} for i in indexes]
    reply = _ask(brain, "Write speaker notes for these slides: 2-4 natural sentences each, what to say aloud, "
                        "not a repeat of the bullets. Same language as the slides.\n"
                        f"{json.dumps(listing, ensure_ascii=False)}\n"
                        'JSON: {"notes": [{"slide": 1, "notes": "..."}]}', room=6000)
    written = 0
    for item in (reply.get("notes") if isinstance(reply, dict) else reply) or []:
        try:
            i = int(item["slide"]) - 1
            if i in indexes and str(item.get("notes", "")).strip():
                design["pages"][i]["notes"] = str(item["notes"]).strip()
                written += 1
        except (KeyError, TypeError, ValueError):
            continue
    if not written:
        raise DesignAIError("No notes came back. Try again.")
    return written


def deck_from_youtube(brain, url: str, count: int = 8, theme: str = "midnight") -> dict:
    from .. import shield, youtube
    from ..makers import _deck_prompt

    vid = youtube.video_id(url)
    if not vid:
        raise DesignAIError("That doesn't look like a YouTube link.")
    try:
        _, text = youtube.transcript(vid)
    except Exception as exc:
        raise DesignAIError(str(exc)) from None
    title = youtube.title(vid) or "YouTube video"
    wrapped, _ = shield.wrap(text[:30000], title)
    about = f"based only on this video transcript ({title}):\n{shield.RULE}\n\n{wrapped}\n"
    deck = _ask(brain, _deck_prompt(about, count), room=7000)
    slides = [s for s in (deck.get("slides") if isinstance(deck, dict) else []) or [] if isinstance(s, dict) and s.get("title")]
    if not slides:
        raise DesignAIError("No slides came back. Try again.")
    deck["slides"] = slides
    deck.setdefault("title", title)
    deck.setdefault("subtitle", f"From the video: {title}")
    return templates.build_deck(deck, theme)


def deck_from_topic(brain, topic: str, count: int = 8, theme: str = "midnight", material: str = "") -> dict:
    from ..makers import _deck_prompt

    deck = _ask(brain, _deck_prompt(material or f"about: {topic}", count), room=7000)
    slides = [s for s in (deck.get("slides") if isinstance(deck, dict) else []) or [] if isinstance(s, dict) and s.get("title")]
    if not slides:
        raise DesignAIError("No slides came back. Try again.")
    deck["slides"] = slides
    return templates.build_deck(deck, theme)


def quiz_slides(brain, topic: str, count: int = 6, theme: str = "classroom") -> dict:
    from .. import quiz

    text = brain.ask_once(quiz.QUIZ_PROMPT.format(count=count, about=f"about: {topic}", level=""))
    try:
        questions = quiz.questions_from(text)
    except quiz.QuizError as exc:
        raise DesignAIError(str(exc)) from None
    return templates.quiz_deck(topic, questions[:count], theme)


def ai_image(images, prompt: str, design: dict) -> str:
    """Generate a picture shaped like the design and file it under assets/. Returns its src."""
    W, H = design["w"], design["h"]
    size = "1536x1024" if W > H * 1.2 else ("1024x1536" if H > W * 1.2 else "1024x1024")
    path = images.generate(prompt, size=size)
    return model.import_asset(path)
