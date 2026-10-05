"""9.0: the Design page in the window — clicking, dragging, typing, undo.

Mouse work is simulated with real Tk events on the canvas, so these go
through the same handlers a person's clicks do.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from test_gui import _display_available, app, inline_workers  # noqa: F401 — fixtures

from jarvis.design import model, templates

pytestmark = pytest.mark.skipif(not _display_available(), reason="no display")


@pytest.fixture
def page(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app, "_open_path", lambda path: opened.append(path))
    app.geometry("1400x860")
    app._show_tab("design")
    design_page = app.design_page()
    app.update()
    design_page.fit()
    app.update()
    design_page.opened = opened
    return design_page


CLOCK = [100_000]


def tick() -> int:
    """An event timestamp a second after the last one. Tk decides what is a
    double-click from these, and synthetic events otherwise all share one —
    so every second press on the same spot would count as a double-click."""
    CLOCK[0] += 1000
    return CLOCK[0]


def click(page, x, y, *, double=False, shift=False):
    cx, cy = page._to_canvas(x, y)
    sx, sy = int(cx - page.canvas.canvasx(0)), int(cy - page.canvas.canvasy(0))
    state = 0x1 if shift else 0
    page.canvas.event_generate("<ButtonPress-1>", x=sx, y=sy, state=state, time=tick())
    page.canvas.event_generate("<ButtonRelease-1>", x=sx, y=sy, state=state, time=tick())
    if double:
        # Tk won't synthesise a double-click; call what it would have called.
        page._double(SimpleNamespace(x=sx, y=sy))
    page.update()


def drag(page, start, end, steps=4, shift=False):
    (x0, y0), (x1, y1) = start, end
    to_screen = lambda x, y: (int(page._to_canvas(x, y)[0] - page.canvas.canvasx(0)),
                              int(page._to_canvas(x, y)[1] - page.canvas.canvasy(0)))
    state = 0x1 if shift else 0
    sx, sy = to_screen(x0, y0)
    page.canvas.event_generate("<ButtonPress-1>", x=sx, y=sy, state=state, time=tick())
    for i in range(1, steps + 1):
        mx, my = to_screen(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        page.canvas.event_generate("<B1-Motion>", x=mx, y=my, state=state | 0x100, time=tick())
    page.canvas.event_generate("<ButtonRelease-1>", x=mx, y=my, state=state, time=tick())
    page.update()


def test_the_design_page_opens_from_the_sidebar(app, page):
    assert app.active_tab == "design" and page.winfo_ismapped()
    assert page.design["format"] == "slides" and page._page_image is not None
    app._show_tab("chat")
    assert not page.winfo_ismapped()
    reply = app._ui_command("/design")
    assert app.active_tab == "design" and "Design page" in reply


def test_add_select_drag_resize_rotate_and_undo(page):
    # A fixed zoom: on a CI runner's small screen the page is tiny, and 10.0's snapping
    # (a few screen pixels) then reaches far enough to pull this 200 px drag onto the centre line.
    page.set_zoom(0.6 / page._fit_scale())
    el = page.add_shape("rect")
    start = (el["x"], el["y"], el["w"], el["h"])
    cx, cy = model.center(el)
    page.select(None)
    click(page, cx, cy)
    assert page.selected_id == el["id"]
    drag(page, (cx, cy), (cx + 200, cy + 100))
    assert el["x"] == pytest.approx(start[0] + 200, abs=3) and el["y"] == pytest.approx(start[1] + 100, abs=3)
    # the south-east handle makes it bigger and keeps the north-west corner put
    se = (el["x"] + el["w"], el["y"] + el["h"])
    drag(page, se, (se[0] + 100, se[1] + 60))
    assert el["w"] == pytest.approx(start[2] + 100, abs=3) and el["h"] == pytest.approx(start[3] + 60, abs=3)
    assert el["x"] == pytest.approx(start[0] + 200, abs=3)
    # the round handle rotates
    knob_y = el["y"] - 28 / page._scale
    cx, cy = model.center(el)
    drag(page, (cx, knob_y), (cx + 300, cy), shift=True)
    assert el["rot"] == pytest.approx(90, abs=1)
    for _ in range(3):
        page.undo()
    restored = page.selected() or model.find(page.page, el["id"])
    assert (restored["x"], restored["y"], restored["w"], restored["h"]) == pytest.approx(start, abs=1)
    page.redo()
    assert model.find(page.page, el["id"])["x"] == pytest.approx(start[0] + 200, abs=3)


def press(page, sequence: str) -> None:
    """A shortcut, run through the canvas's own binding for it.

    Tk sends generated key events to whichever window holds the OS keyboard
    focus, and on a CI runner that is never this one — so the binding's
    script is evaluated directly, with its %-fields filled in."""
    script = page.canvas.bind(sequence)
    assert script, f"{sequence} isn't bound on the canvas"
    filled = re.sub(r"%[#bfhkstwxyAEKNWTXYD]", lambda m: str(page.canvas) if m.group() == "%W" else "0", script)
    page.canvas.tk.eval("catch {" + filled + "}")
    page.update()


def test_keyboard_shortcuts(page):
    el = page.add_text("body")
    assert page.canvas.focus_lastfor() is page.canvas   # selecting gives the canvas the keyboard
    x0, y0 = el["x"], el["y"]
    press(page, "<Key-Right>")
    press(page, "<Shift-Key-Down>")
    assert el["x"] == x0 + 2 and el["y"] == y0 + 20
    count = len(page.page["elements"])
    press(page, "<Control-Key-d>")
    assert len(page.page["elements"]) == count + 1
    press(page, "<Control-Key-c>")
    press(page, "<Key-Delete>")
    assert len(page.page["elements"]) == count
    page.paste_element()
    assert len(page.page["elements"]) == count + 1
    press(page, "<Control-Key-z>")
    assert len(page.page["elements"]) == count
    press(page, "<Control-Key-y>")
    assert len(page.page["elements"]) == count + 1
    press(page, "<Key-Escape>")
    assert page.selected_id is None
    for sequence in ("<Control-Key-s>", "<Control-Key-l>", "<Key-F2>", "<Key-Prior>", "<Control-Key-0>"):
        assert page.canvas.bind(sequence), sequence


def test_double_click_edits_text_in_place(page):
    el = page.add_text("title")
    cx, cy = model.center(el)
    click(page, cx, cy, double=True)
    box = page._editor[0]
    box.delete("1.0", "end")
    box.insert("1.0", "Merhaba dünya")
    page._commit_editor()
    assert el["text"] == "Merhaba dünya"
    page.undo()
    assert model.find(page.page, el["id"])["text"] == "Your title"


def test_the_text_editor_survives_alt_tab(page, monkeypatch):
    el = page.add_text("body")
    page.edit_text()
    box = page._editor[0]
    box.insert("end", " more")
    monkeypatch.setattr(page, "focus_get", lambda: None)          # the whole window lost focus
    page._focus_left()
    assert page._editor is not None
    monkeypatch.setattr(page, "focus_get", lambda: page.notes_box)  # moved to another part of JARVIS
    page._focus_left()
    assert page._editor is None and el["text"].endswith(" more")


def test_style_panel_changes_the_selection(page):
    el = page.add_shape("star")
    page._set("fill", "#ff0000")
    page._set("opacity", 0.5)
    page._set("shape", "heart")
    assert (el["fill"], el["opacity"], el["shape"]) == ("#ff0000", 0.5, "heart")
    page.copy_style()
    other = page.add_shape("rect")
    page.paste_style()
    assert other["fill"] == "#ff0000" and other["shape"] == "rect"
    page.toggle_lock()
    assert other["locked"]
    page.update()
    page._refresh_style()


def test_eyedropper_picks_from_the_page(page):
    page.page["bg"] = "#336699"
    page.redraw()
    el = page.add_text("body")
    page._start_eyedropper(lambda c: page._set("color", c))
    click(page, 5, 5)
    assert el["color"] == "#336699" and page._eyedropper is None


def test_pages_add_duplicate_move_delete(page):
    page.load(templates.build_deck({"title": "T", "slides": [{"title": "A", "bullets": ["a"]}]}, "ocean"))
    page.add_page()
    assert len(page.design["pages"]) == 3 and page.index == 1
    assert any(e.get("role") == "deco" for e in page.page["elements"])
    page.duplicate_page(2)
    page.move_page(3, -1)
    page.delete_page(page.index)
    assert len(page.design["pages"]) == 3
    page.go_to(0)
    assert page.index == 0
    page.theme_menu.set("neon")
    page.apply_theme()
    assert page.design["theme"] == "neon"


def test_ask_jarvis_to_change_it(page, monkeypatch, inline_workers):
    import ui.designui as designui

    page.load(templates.make("poster", "modern"))
    headline = next(e for e in page.page["elements"] if e.get("role") == "headline")
    page.select(headline["id"])
    page.ask_change("make it bigger")
    assert "bigger" in page.ai_reply.cget("text")
    monkeypatch.setattr(designui.threading, "Thread", inline_workers_thread())
    monkeypatch.setattr(page.app.jarvis.brain, "ask_once", lambda *a, **k: json.dumps(
        {"ops": [{"op": "set", "id": headline["id"], "props": {"text": "Yaz Gecesi"}}], "say": "Renamed it."}))
    page.ask_change("translate the headline into Turkish and keep it short please")
    assert model.find(page.page, headline["id"])["text"] == "Yaz Gecesi"
    assert page.ai_reply.cget("text") == "Renamed it."
    page.undo()
    assert model.find(page.page, headline["id"])["text"] != "Yaz Gecesi"


def inline_workers_thread():
    class Now:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            self.target(*self.args, **self.kwargs)

    return Now


def test_describe_and_design(page, monkeypatch, inline_workers):
    import ui.designui as designui

    monkeypatch.setattr(designui.threading, "Thread", inline_workers_thread())
    monkeypatch.setattr(page.app.jarvis.brain, "ask_once", lambda *a, **k: json.dumps(
        {"kind": "invitation", "variant": "gold", "content": {"names": "Elif & Can", "date": "14 Haziran"}}))
    page.describe_design("a wedding invitation for Elif and Can")
    assert page.design["kind"] == "invitation" and page.path is not None and page.path.exists()
    assert "Elif & Can" in model.page_text(page.page)


def test_polish_palette_fonts_resize_and_templates(page, monkeypatch, inline_workers):
    import ui.designui as designui

    monkeypatch.setattr(designui.threading, "Thread", inline_workers_thread())
    page.load(templates.make("sale", "tag"))
    page.make_better(True)
    page._show_palette(["#7c3aed", "#db2777", "#facc15", "#fdf4ff", "#1e1b4b"], None)
    page.apply_palette()
    assert page.design["palette"][0] == "#7c3aed"
    page.apply_fonts("Georgia", "Segoe UI")
    assert page.design["fonts"]["heading"] == "Georgia"
    page.resize_copy("instagram")
    assert page.design["format"] == "instagram"
    page.save_template()
    assert model.listing(model.templates_dir())
    page.open_templates()
    page.update()
    page.open_gallery()
    page.update()


def test_export_everything(page):
    page.load(templates.make("logo", "emblem"))
    for kind in ("pdf", "png", "png-all", "png-clear", "jpg", "pptx", "open"):
        out = page.export(kind)
        assert out and out[0].exists(), kind
    assert page.opened


def test_a_design_made_in_the_chat_opens_on_the_page(app, page, monkeypatch):
    from jarvis.assistant import JarvisResponse

    app._show_tab("chat")
    design = templates.make("sticker", "burst", {"text": "SICAK"})
    path = model.save(design)
    app._handle_response(JarvisResponse(text="made it", design_path=path, show_design=True))
    assert app.active_tab == "design" and page.design["id"] == design["id"]


def test_dropping_files_on_the_page(app, page, base):
    from PIL import Image

    picture = base / "drop.png"
    Image.new("RGB", (80, 40), "blue").save(picture)
    count = len(page.page["elements"])
    app._attach(picture)
    assert len(page.page["elements"]) == count + 1 and page.selected()["type"] == "image"
    from jarvis.design import pptxio

    deck = pptxio.export_pptx(templates.build_deck({"title": "Dropped", "slides": []}), base / "d.pptx")
    app._attach(deck)
    assert page.design["title"] == "Dropped"
