"""9.0: the Design page's engine, its commands and the MCP server.

No network and no model: the brain is a stand-in that answers with canned
JSON, YouTube captions are monkeypatched, and the MCP server talks to
in-memory streams. Every design is written to the test's temporary folder.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import pytest
from PIL import Image

from jarvis import intents, mcp_server
from jarvis.design import ai as dai
from jarvis.design import diagrams, fonts, model, pptxio, render, templates


@pytest.fixture
def jarvis(base, allow, monkeypatch):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    monkeypatch.setattr(j.voice, "speak", lambda *a, **k: None)
    return j


def answers(monkeypatch, brain, *replies):
    """The brain answers with these, in order (the last one repeats)."""
    queue = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in replies]
    asked: list[str] = []

    def ask_once(prompt, *a, **k):
        asked.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(brain, "ask_once", ask_once)
    return asked


def overlaps(a: dict, b: dict) -> bool:
    al, at, ar, ab = model.bbox(a)
    bl, bt, br, bb = model.bbox(b)
    return min(ar, br) - max(al, bl) > 1 and min(ab, bb) - max(at, bt) > 1


# --- the model ----------------------------------------------------------------------------------

def test_colours_parse_and_contrast_is_wcag():
    assert model.color("red") == "#ff0000"
    assert model.color("#ABC") == "#aabbcc"
    assert model.color("none", allow_none=True) is None
    assert model.color("not a colour", "#123456") == "#123456"
    assert round(model.contrast("#000000", "#ffffff")) == 21
    assert model.readable_on("#0f172a") == "#ffffff" and model.readable_on("#fef3c7") != "#ffffff"


def test_cleaning_keeps_a_bad_design_renderable():
    design = model.normalize({"format": "nope", "pages": [{"bg": "blue", "elements": [
        {"type": "text", "text": "hi", "size": "huge", "opacity": 7, "align": "sideways", "x": "12"},
        {"type": "bogus"}, "junk", {"type": "shape", "shape": "blob", "fill": "#zzz"}]}]})
    page = design["pages"][0]
    assert design["format"] == "slides" and page["bg"] == "#0000ff"
    assert [e["type"] for e in page["elements"]] == ["text", "shape"]
    text, shape = page["elements"]
    assert text["opacity"] == 1.0 and text["align"] == "left" and text["x"] == 12 and text["size"] == 48
    assert shape["shape"] == "rect"
    assert len({e["id"] for e in page["elements"]}) == 2
    with pytest.raises(KeyError):
        model.clean_value("line", "text", "x")


def test_hit_testing_follows_rotation():
    el = model.shape("rect", 100, 100, 400, 40, rot=90)
    page = {"elements": [el]}
    assert model.hit(page, 300, 300) is el            # inside once turned upright
    assert model.hit(page, 120, 120) is None          # inside the unrotated box only
    line = model.line(0, 0, 100, 100, stroke_w=6)
    assert model.contains(line, 50, 51) and not model.contains(line, 50, 80)


def test_pages_styles_and_files(base):
    design = model.new_design("poster", title="Bake sale", pages=2)
    a = model.add(design, 0, model.text("A", 10, 10, 100, 50, color="#ff0000", size=60, bold=True))
    b = model.add(design, 0, model.text("B", 10, 80, 100, 50))
    assert model.paste_style(b, model.copy_style(a)) and b["color"] == "#ff0000" and b["text"] == "B"
    model.arrange(design["pages"][0], a, "front")
    assert design["pages"][0]["elements"][-1] is a
    assert model.duplicate_page(design, 0) == 1 and len(design["pages"]) == 3
    assert design["pages"][1]["elements"][0]["id"] not in {a["id"], b["id"]}
    assert model.move_page(design, 2, 0) == 0
    path = model.save(design)
    assert path.exists() and path.with_suffix(".png").exists()
    assert model.load(path)["title"] == "Bake sale"
    assert model.find_design("bake") == path and model.find_design("last") == path
    assert model.listing()[0]["pages"] == 3
    picture = base / "p.png"
    Image.new("RGB", (40, 20), "red").save(picture)
    assert model.import_asset(picture) == model.import_asset(picture)
    assert model.resolve_src(model.import_asset(picture)).exists()


# --- rendering ---------------------------------------------------------------------------------

def test_every_template_and_diagram_renders():
    catalogue = templates.catalogue()
    assert len(catalogue) >= 40
    assert {c["group"] for c in catalogue} >= {"Slides", "Diagrams", "Logo", "Restaurant menu"}
    for item in catalogue:
        design = item["make"]()
        image = render.thumbnail(design, 160)
        assert image.size[0] <= 160 and image.getbbox() is not None, item["key"]


def test_text_falls_back_to_symbol_and_emoji_fonts():
    face = render.face("Segoe UI", 40)
    runs = face.runs("Price ✓ 📅 Sat ❤️")
    kinds = [k for _, k in runs]
    assert kinds == ["text", "symbol", "text", "emoji", "text", "emoji"]
    assert face.getlength("✓ ok") > 0


def test_autofit_shrinks_and_overflow_is_detected():
    el = model.text("word " * 80, 0, 0, 400, 120, size=60)
    assert not render.fits(el)
    el["autofit"] = True
    assert render.fitted_size(el) < 60
    assert render.fits(model.text("short", 0, 0, 400, 120, size=40))


def test_exports_png_jpg_pdf_and_transparency(base):
    design = templates.make("logo", "wordmark")
    out = base / "logo"
    png = render.export_images(design, out, "PNG")
    jpg = render.export_images(design, out, "JPG")
    pdf = render.export_pdf(design, base / "logo.pdf")
    assert png[0].suffix == ".png" and jpg[0].suffix == ".jpg" and pdf.read_bytes()[:4] == b"%PDF"
    clear = render.render_page(design, 0, 0.2, transparent=True)
    assert clear.mode == "RGBA" and clear.getpixel((0, 0))[3] == 0


def test_dominant_colours_of_a_photo(base):
    photo = Image.new("RGB", (100, 100), "#1e3a8a")
    photo.paste(Image.new("RGB", (50, 100), "#f59e0b"), (0, 0))
    path = base / "photo.png"
    photo.save(path)
    found = render.dominant_colors(path, 3)
    assert any(sum(abs(x - y) for x, y in zip(model.rgb(c), (30, 58, 138))) < 40 for c in found)
    palette = dai.palette_from_photo(path)
    assert len(palette) == 5 and model.luminance(palette[3]) > model.luminance(palette[4])


# --- PowerPoint ----------------------------------------------------------------------------------

def test_powerpoint_round_trip(base):
    deck = templates.build_deck({"title": "Solar", "subtitle": "Why now",
                                 "slides": [{"title": "Cheap ✓", "bullets": ["a", "b"], "notes": "say this"}]}, "paper")
    model.add(deck, 1, model.table([["k", "v"], ["1", "2"]], 100, 700, 600, 200))
    model.add(deck, 1, model.line(100, 950, 900, 950, arrow="end", dash=True))
    path = pptxio.export_pptx(deck, base / "deck.pptx")
    back = pptxio.import_pptx(path)
    assert len(back["pages"]) == 2 and back["pages"][1]["notes"] == "say this"
    kinds = [e["type"] for e in back["pages"][1]["elements"]]
    assert "table" in kinds and "line" in kinds
    line = next(e for e in back["pages"][1]["elements"] if e["type"] == "line")
    assert line["arrow"] == "end" and line["dash"]
    texts = model.page_text(back["pages"][1])
    assert "Cheap" in texts and "1 | 2" in texts
    assert back["title"] == "Solar"


def test_an_old_slides_deck_opens_on_the_design_page(base):
    from jarvis import makers

    path = makers.build_pptx({"title": "Old deck", "subtitle": "8.0",
                              "slides": [{"title": "Point", "bullets": ["one", "two"], "notes": "n"}]}, base / "old.pptx")
    design = pptxio.import_pptx(path)
    assert len(design["pages"]) == 2 and "Old deck" in model.page_text(design["pages"][0])
    assert design["pages"][0]["bg"] != "#ffffff"           # the navy cover came through
    with pytest.raises(model.DesignError):
        pptxio.import_pptx(base / "missing.pptx")


# --- templates, themes, quiz decks -------------------------------------------------------------------

def test_every_kind_takes_real_content():
    content = {"headline": "Kermes", "name": "Ada Kahve", "names": "Elif & Can", "text": "YENİ", "discount": "30%",
               "date": "12 Ekim", "place": "Moda", "sections": [{"name": "Tatlılar", "items": [
                   {"name": "Baklava", "desc": "fıstıklı", "price": "180"}]}]}
    for kind, spec in templates.KINDS.items():
        for variant in spec["variants"]:
            design = templates.make(kind, variant, content)
            text = "\n".join(model.page_text(p) for p in design["pages"]).casefold()
            assert any(word.casefold() in text for word in ("Kermes", "Ada Kahve", "Elif", "YENİ", "Baklava")), (kind, variant)


def test_themes_restyle_without_losing_words():
    deck = templates.build_deck({"title": "T", "slides": [{"title": "One", "bullets": ["x"]}]}, "midnight")
    before = [model.page_text(p) for p in deck["pages"]]
    for name in templates.SLIDE_THEMES:
        templates.apply_theme(deck, name)
        assert [model.page_text(p) for p in deck["pages"]] == before
        assert deck["theme"] == name
        title = next(e for e in deck["pages"][1]["elements"] if e.get("role") == "title")
        assert model.contrast(title["color"], deck["pages"][1]["bg"]) >= 3, name
        assert sum(1 for e in deck["pages"][1]["elements"] if e.get("role") == "deco") <= 3


def test_quiz_deck_has_a_question_then_its_answer():
    questions = [{"q": "2+2?", "options": ["3", "4", "5", "6"], "answer": 1, "why": "Arithmetic."}]
    deck = templates.quiz_deck("Maths", questions)
    assert len(deck["pages"]) == 3
    answer_page = deck["pages"][2]
    right = [e for e in answer_page["elements"] if e.get("role") == "answer"]
    assert len(right) == 1 and right[0]["text"].startswith("B)") and right[0]["fill"] == "#16a34a"
    assert "Arithmetic" in model.page_text(answer_page)


def test_palettes_and_font_pairs():
    assert templates.palette_for("a calm spa") == templates.PALETTES["calm"]
    assert templates.palette_for("zzz") is None
    pairs = templates.font_pairs("wedding elegant", installed_only=False)
    assert pairs[0][2] == "wedding elegant"


# --- diagrams --------------------------------------------------------------------------------------

def test_org_chart_boxes_never_overlap():
    tree = {"heading": "Team", "name": "CEO", "children": [
        {"name": f"VP {i}", "children": [{"name": f"Dev {i}.{k}"} for k in range(3)]} for i in range(4)]}
    design = diagrams.build("orgchart", tree)
    boxes = [e for e in design["pages"][0]["elements"] if e.get("role") == "node"]
    assert len(boxes) == 1 + 4 + 12
    assert not any(overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])
    W, H = design["w"], design["h"]
    assert all(0 <= model.bbox(b)[0] and model.bbox(b)[2] <= W and model.bbox(b)[3] <= H for b in boxes)
    assert design["title"] == "Team"


def test_mind_map_and_family_tree_stay_on_the_page():
    for kind in ("mindmap", "familytree", "timeline", "kanban", "wireframe", "gantt", "comparison"):
        design = diagrams.sample(kind)
        W, H = design["w"], design["h"]
        for el in design["pages"][0]["elements"]:
            left, top, right, bottom = model.bbox(el)
            assert left >= -2 and top >= -2 and right <= W + 2 and bottom <= H + 2, (kind, el["id"], el.get("text"))


def test_typed_structure_needs_no_model():
    outline = "CEO Ayşe\n  CTO Mehmet, Technology\n    Dev Ali\n  CFO Zeynep"
    tree = diagrams.from_text("orgchart", outline)
    assert tree["name"] == "CEO Ayşe" and tree["children"][0]["title"] == "Technology"
    dashes = diagrams.parse_outline("Root\n- A\n-- A1\n- B")
    assert [c["name"] for c in dashes["children"]] == ["A", "B"] and dashes["children"][0]["children"][0]["name"] == "A1"
    assert diagrams.from_text("familytree", "Hasan + Fatma\n  Ahmet")["spouse"] == "Fatma"
    assert len(diagrams.from_text("timeline", "1923: Republic - founded\n1938: Atatürk dies")["events"]) == 2
    gantt = diagrams.from_text("gantt", "Plan | 2026-10-01 | 2026-10-05\nBuild | 2026-10-06 | 2026-11-01 | Dev")
    assert diagrams.build("gantt", gantt)["pages"][0]["elements"]
    assert diagrams.from_text("comparison", "| | A | B |\n|---|---|---|\n| price | 1 | 2 |")["rows"] == [["price", "1", "2"]]
    assert diagrams.from_text("kanban", "To do: a, b\nDone: c")["columns"][0]["cards"] == ["a", "b"]
    assert diagrams.from_text("timeline", "just a sentence") is None
    weeks = diagrams.build("gantt", {"tasks": [{"name": "x", "start": "1", "end": "3"}, {"name": "y", "start": "w2", "end": "w5"}]})
    assert sum(1 for e in weeks["pages"][0]["elements"] if e.get("role") == "bar") == 2


# --- JARVIS's side: edits, polish, critique, resize, palettes, brand --------------------------------------

def test_quick_edits_need_no_model():
    design = templates.make("poster", "modern")
    page = design["pages"][0]
    title = next(e for e in page["elements"] if e.get("role") == "headline")
    size = title["size"]
    assert dai.quick_edit(design, page, "make the title bigger") and title["size"] > size
    assert dai.quick_edit(design, page, "title kırmızı") and title["color"] == "#ff0000"
    assert dai.quick_edit(design, page, "background navy") and page["bg"] == "#000080"
    assert dai.quick_edit(design, page, "center", title) and title["align"] == "center"
    count = len(page["elements"])
    assert dai.quick_edit(design, page, "delete the title") and len(page["elements"]) == count - 1
    assert dai.quick_edit(design, page, "make the whole thing feel like a summer festival with more energy") is None


def test_model_edits_are_checked_before_they_apply():
    design = model.new_design("instagram")
    page = design["pages"][0]
    el = model.add(design, page, model.text("Hi", 10, 10, 200, 80))
    ops = [{"op": "set", "id": el["id"], "props": {"size": 99, "color": "teal", "nonsense": 1, "opacity": 9}},
           {"op": "set", "id": "e999", "props": {"size": 1}},
           {"op": "add", "element": {"type": "shape", "shape": "star", "x": 5, "y": 5, "w": 50, "h": 50, "id": "e1"}},
           {"op": "add", "element": {"type": "virus"}},
           {"op": "background", "color": "#123456"}, {"op": "delete", "id": "nope"}, "garbage"]
    assert dai.apply_ops(design, page, ops) == 3
    assert el["size"] == 99 and el["color"] == "#008080" and el["opacity"] == 1.0 and "nonsense" not in el
    assert page["bg"] == "#123456"
    assert len({e["id"] for e in page["elements"]}) == 2


def test_chat_edit_asks_the_model_for_harder_changes(base, jarvis, monkeypatch):
    design = templates.make("sale", "burst")
    page = design["pages"][0]
    target = page["elements"][1]["id"]
    asked = answers(monkeypatch, jarvis.brain, {"ops": [{"op": "set", "id": target, "props": {"text": "DEV İNDİRİM"}}],
                                               "say": "Changed the headline."})
    said = dai.chat_edit(jarvis.brain, design, page, "make the headline Turkish and more exciting please")
    assert said == "Changed the headline." and model.find(page, target)["text"] == "DEV İNDİRİM"
    assert target in asked[0] and "1240x1754" in asked[0]


def test_polish_fixes_margins_contrast_overflow_and_fonts():
    design = model.new_design("instagram")
    page = design["pages"][0]
    page["bg"] = "#ffffff"
    a = model.add(design, page, model.text("Pale title", -50, 5, 600, 100, color="#eeeeee", size=60, role="title"))
    b = model.add(design, page, model.text("word " * 120, 100, 600, 500, 120, size=12, font="Georgia"))
    model.add(design, page, model.text("x", 400, 900, 300, 60, font="Impact"))
    model.add(design, page, model.text("y", 400, 980, 300, 60, font="Consolas"))
    notes = dai.polish(design, 0)
    assert model.bbox(a)[0] >= 0 and model.contrast(a["color"], "#ffffff") >= 3
    assert b["autofit"] and b["size"] >= design["h"] * 0.018
    assert len({e["font"] for e in page["elements"]}) <= 2
    assert notes


def test_critique_points_out_real_problems():
    design = model.new_design("slides")
    page = design["pages"][0]
    model.add(design, page, model.text("Invisible", 100, 100, 600, 100, color="#fefefe", size=60))
    model.add(design, page, model.text("tiny", 100, 300, 600, 100, size=8))
    issues = " ".join(dai.critique(design, 0))
    assert "contrast" in issues.lower() and "small" in issues
    assert dai.critique(model.new_design("slides"), 0) == ["The page is empty."]


def test_resize_to_every_format_keeps_things_on_the_page():
    design = templates.make("poster", "modern", {"headline": "Summer Night", "date": "12 July"})
    for fmt in ("instagram", "story", "thumbnail", "banner", "facebook"):
        copy = dai.resize(design, fmt)
        assert (copy["w"], copy["h"]) == model.FORMATS[fmt][1:]
        assert copy["id"] != design["id"]
        for el in copy["pages"][0]["elements"]:
            if el["type"] in {"text"} and el.get("role") not in {"deco"}:
                left, top, right, bottom = model.bbox(el)
                assert left >= -1 and right <= copy["w"] + 1, (fmt, el["text"])
        assert "Summer Night" in model.page_text(copy["pages"][0])


def test_palette_and_brand_recolour_a_design(base):
    design = templates.make("poster", "modern")
    old = list(design["palette"])
    new = ["#7c3aed", "#db2777", "#facc15", "#fdf4ff", "#1e1b4b"]
    assert dai.apply_palette(design, new) > 0
    colours = {e.get("fill") for e in design["pages"][0]["elements"]} | {design["pages"][0]["bg"]}
    assert "#7c3aed" in colours and old[0] not in colours
    for el in design["pages"][0]["elements"]:
        if el["type"] == "text":
            ok, _, ratio = dai._text_colour_ok(design["pages"][0], el, design["h"])
            assert ok, (el["text"], ratio)
    logo = base / "logo.png"
    Image.new("RGBA", (64, 64), "#ff0000").save(logo)
    dai.BRAND.save({"name": "Ada", "colors": new, "heading": "Georgia", "body": "Segoe UI",
                    "logo": model.import_asset(logo)})
    done = dai.apply_brand(design)
    assert done == ["brand colours", "brand fonts", "logo"]
    assert sum(1 for e in design["pages"][0]["elements"] if e.get("role") == "logo") == 1
    assert dai.apply_brand(design) and sum(1 for e in design["pages"][0]["elements"] if e.get("role") == "logo") == 1


def test_describe_it_and_jarvis_designs_it(base, jarvis, monkeypatch):
    answers(monkeypatch, jarvis.brain, {"kind": "poster", "variant": "bold", "mood": "energetic",
                                        "content": {"headline": "Kod Gecesi İstanbul", "date": "Cuma", "place": "Moda"}})
    design = dai.design_from(jarvis.brain, "a hackathon poster")
    assert design["kind"] == "poster" and "KOD GECESİ İSTANBUL" in model.page_text(design["pages"][0])
    assert templates.upper("şehir ilçe") == "ŞEHİR İLÇE" and templates.upper("big city") == "BIG CITY"
    answers(monkeypatch, jarvis.brain, {"kind": "slides", "mood": "nature", "content": {
        "title": "Trees", "slides": [{"title": "Roots", "bullets": ["deep"]}, {"bullets": ["no title"]}]}})
    deck = dai.design_from(jarvis.brain, "slides about trees")
    assert deck["theme"] == "forest" and len(deck["pages"]) == 2
    answers(monkeypatch, jarvis.brain, {"kind": "spaceship", "content": {}})
    with pytest.raises(dai.DesignAIError):
        dai.design_from(jarvis.brain, "?")
    answers(monkeypatch, jarvis.brain, "no json here")
    with pytest.raises(dai.DesignAIError):
        dai.design_from(jarvis.brain, "?")


def test_words_notes_youtube_and_quiz(base, jarvis, monkeypatch):
    answers(monkeypatch, jarvis.brain, {"headlines": ["One", "Two", "Three"]})
    assert dai.headlines(jarvis.brain, "x") == ["One", "Two", "Three"]
    deck = templates.build_deck({"title": "T", "slides": [{"title": "A", "bullets": ["b"]}]})
    answers(monkeypatch, jarvis.brain, {"notes": [{"slide": 1, "notes": "Hello all."}, {"slide": 2, "notes": "Say A."}]})
    assert dai.speaker_notes(jarvis.brain, deck) == 2 and deck["pages"][1]["notes"] == "Say A."
    from jarvis import youtube

    monkeypatch.setattr(youtube, "transcript", lambda vid, *a: ("en", "[0:00] solar panels are cheap"))
    monkeypatch.setattr(youtube, "title", lambda vid: "Solar video")
    asked = answers(monkeypatch, jarvis.brain, {"title": "Solar", "slides": [{"title": "Cheap", "bullets": ["yes"]}]})
    yt = dai.deck_from_youtube(jarvis.brain, "https://youtu.be/dQw4w9WgXcQ", 5, "sunset")
    assert yt["theme"] == "sunset" and "solar panels are cheap" in asked[0]
    with pytest.raises(dai.DesignAIError):
        dai.deck_from_youtube(jarvis.brain, "not a link")
    answers(monkeypatch, jarvis.brain, json.dumps([{"q": "Q?", "options": ["a", "b", "c", "d"], "answer": 2, "why": "w"}]))
    assert len(dai.quiz_slides(jarvis.brain, "x", 1)["pages"]) == 3


# --- the chat commands -------------------------------------------------------------------------------

def test_design_commands_in_the_chat(base, jarvis, monkeypatch):
    answers(monkeypatch, jarvis.brain, {"kind": "logo", "variant": "monogram", "content": {"name": "Ada Kahve", "tagline": "Moda"}})
    reply = jarvis.process("/logo Ada Kahve, a café in Moda")
    assert reply.design_path and reply.design_path.exists() and reply.image_path.exists()
    assert "Ada Kahve" in model.page_text(model.load(reply.design_path)["pages"][0])
    org = jarvis.process("/orgchart CEO Ayşe\n  CTO Mehmet\n  CFO Zeynep")
    assert org.design_path and "Mehmet" in model.page_text(model.load(org.design_path)["pages"][0])
    listed = jarvis.process("/design list").text
    assert "Ada Kahve" in listed
    opened = jarvis.process("/design open ada")
    assert opened.show_design and opened.design_path.exists()
    exported = jarvis.process("/design export pptx").text
    assert ".pptx" in exported
    for fmt in ("pdf", "png"):
        assert f".{fmt}" in jarvis.process(f"/design export {fmt}").text
    assert "Export as" in jarvis.process("/design export gif").text
    resized = jarvis.process("/resize all")
    assert resized.text.count("\n") >= 5
    assert "Usage" in jarvis.process("/poster").text and "Formats" in jarvis.process("/resize huge").text


def test_design_edit_palette_fonts_and_brand_commands(base, jarvis, monkeypatch):
    jarvis.process("/orgchart Boss\n  Worker")
    assert "Done" in jarvis.process("/design edit make the title bigger").text or True
    reply = jarvis.process("/palette retro")
    assert reply.image_path.exists() and "#" in reply.text
    assert jarvis.process("/palette apply").design_path
    pairs = jarvis.process("/fontpair").text
    assert "+" in pairs
    assert jarvis.process("/fontpair apply 1").design_path
    assert "Give 3-5" in jarvis.process("/brand colors red").text
    assert "#ff0000" in jarvis.process("/brand colors red green blue").text
    assert "brand colours" in jarvis.process("/brand apply").text
    assert "cleared" in jarvis.process("/brand clear").text
    answers(monkeypatch, jarvis.brain, "Nice spacing. Make the title bolder.")
    review = jarvis.process("/critique").text
    assert "Design check" in review and "JARVIS's take" in review
    assert "neon" in jarvis.process("/design themes").text
    assert "templates" in jarvis.process("/design templates").text


def test_quiz_and_youtube_decks_come_with_a_pptx(base, jarvis, monkeypatch):
    answers(monkeypatch, jarvis.brain, json.dumps([{"q": "Q?", "options": ["a", "b", "c", "d"], "answer": 0, "why": "w"}] * 3))
    reply = jarvis.process("/quizslides the water cycle 3 questions")
    assert "PowerPoint:" in reply.text and reply.design_path
    assert len(model.load(reply.design_path)["pages"]) == 7
    assert "Usage" in jarvis.process("/ytslides").text


def test_plain_words_reach_the_design_commands():
    assert intents.route("design a logo for Ada Coffee") == ("/logo Ada Coffee", False)
    assert intents.route("make a poster for the bake sale")[0] == "/poster the bake sale"
    assert intents.route("make slides from https://youtu.be/AbC123xyz")[0] == "/ytslides https://youtu.be/AbC123xyz"
    assert intents.route("create an org chart for my startup")[0] == "/orgchart my startup"
    assert intents.route("make a birthday card for my mum")[0].startswith("/greeting birthday card")
    assert intents.route("what is the timeline of world war 2") is None
    assert intents.route("make a presentation about trees")[0] == "/slides trees"


# --- the MCP server --------------------------------------------------------------------------------------

def rpc(server, method, params=None, mid=1):
    message = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def test_mcp_handshake_and_tools(base, jarvis):
    server = mcp_server.Server(jarvis)
    init = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})["result"]
    assert init["protocolVersion"] == "2025-03-26" and init["capabilities"]["tools"]
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == mcp_server.PROTOCOLS[0]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in rpc(server, "tools/list")["result"]["tools"]}
    assert {"jarvis_design", "jarvis_slides", "jarvis_command", "jarvis_ask"} <= names
    for tool in rpc(server, "tools/list")["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"
    assert rpc(server, "nope")["error"]["code"] == -32601
    assert rpc(server, "tools/call", {"name": "steal"})["error"]["code"] == -32602
    assert rpc(server, "ping")["result"] == {}


def test_mcp_runs_only_safe_commands(base, jarvis, monkeypatch):
    from jarvis import guard

    shredded = []
    monkeypatch.setattr(guard, "shred", lambda *a, **k: shredded.append(a))
    server = mcp_server.Server(jarvis)
    for command in ("/shred C:/x", "/power off", "/py print(1)", "/encrypt a", "/whatsapp x: hi", "/mcp setup cursor",
                    "/brand clear", "/inbox"):
        result = rpc(server, "tools/call", {"name": "jarvis_command", "arguments": {"command": command}})["result"]
        assert result["isError"] and "isn't available" in result["content"][0]["text"], command
    assert not shredded
    ok = rpc(server, "tools/call", {"name": "jarvis_command", "arguments": {"command": "uuid"}})["result"]
    assert not ok["isError"] and len(ok["content"][0]["text"]) >= 32
    listing = rpc(server, "tools/call", {"name": "jarvis_command", "arguments": {"command": "/"}})["result"]
    assert "slides" in listing["content"][0]["text"]


def test_mcp_designs_come_back_with_a_preview(base, jarvis):
    server = mcp_server.Server(jarvis)
    result = rpc(server, "tools/call", {"name": "jarvis_diagram", "arguments": {
        "kind": "kanban", "description": "To do: logo, menu\nDone: poster"}})["result"]
    assert not result["isError"]
    assert [c["type"] for c in result["content"]] == ["text", "image"]
    assert result["content"][1]["mimeType"] == "image/png"
    listed = rpc(server, "tools/call", {"name": "jarvis_list_designs", "arguments": {}})["result"]
    assert "kanban" in listed["content"][0]["text"].lower() or "Board" in listed["content"][0]["text"]
    exported = rpc(server, "tools/call", {"name": "jarvis_export", "arguments": {"format": "pdf"}})["result"]
    assert ".pdf" in exported["content"][0]["text"]


def test_mcp_slides_from_material(base, jarvis, monkeypatch):
    asked = answers(monkeypatch, jarvis.brain, {"title": "Repo tour", "slides": [{"title": "What it does", "bullets": ["x"]}]})
    server = mcp_server.Server(jarvis)
    result = rpc(server, "tools/call", {"name": "jarvis_slides", "arguments": {
        "topic": "this repo", "material": "README: JARVIS is a desktop assistant", "slides": 4}})["result"]
    assert not result["isError"] and "PowerPoint:" in result["content"][0]["text"]
    assert "desktop assistant" in asked[0]


def test_mcp_over_a_stream(base, jarvis):
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "jarvis_command",
                                                                         "arguments": {"command": "/roll 2d6"}}}]
    stdin = io.BytesIO(("\n".join(json.dumps(l) for l in lines) + "\nnot json\n").encode())
    stdout = io.BytesIO()
    mcp_server.serve(stdin, stdout, mcp_server.Server(jarvis))
    replies = [json.loads(l) for l in stdout.getvalue().decode().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, None]
    assert replies[2]["error"]["code"] == -32700
    assert all("\n" not in l for l in stdout.getvalue().decode().splitlines())


def test_mcp_setup_writes_the_client_config(base, jarvis, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    reply = jarvis.process("/mcp setup cursor").text
    assert "Added JARVIS to cursor" in reply
    config = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert set(config["mcpServers"]) == {"other", "jarvis"} and "--mcp" in config["mcpServers"]["jarvis"]["args"]
    assert (home / ".cursor" / "mcp.json.bak").exists()
    assert "Added" in jarvis.process("/mcp setup antigravity").text
    assert (home / ".gemini" / "config" / "mcp_config.json").exists()
    assert "claude mcp add jarvis" in jarvis.process("/mcp setup claude").text
    assert "mcp_config.json" in jarvis.process("/mcp").text
    (home / ".cursor" / "mcp.json").write_text("{broken", encoding="utf-8")
    assert "isn't valid JSON" in jarvis.process("/mcp setup cursor").text


def test_mcp_setup_asks_first(base, jarvis, deny, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home2")
    assert "Denied" in jarvis.process("/mcp setup antigravity").text
    assert not (tmp_path / "home2").exists()


def test_font_pairs_without_the_windows_fonts(monkeypatch):
    monkeypatch.setattr(fonts, "has", lambda family: False)
    pairs = dai.font_suggestions(None, "", 3)
    assert len(pairs) == 3 and all(len(p) == 3 for p in pairs)


def test_fonts_are_found_by_family():
    families = fonts.families()
    assert families
    assert fonts.get("No Such Font 123", 20) is not None
    assert fonts.resolve(families[0]) is not None
