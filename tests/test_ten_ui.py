"""10.0's window: every page opens, every command has a tile, Ctrl+K and the
chips find tools by what you want rather than what they are called."""

from __future__ import annotations

import tkinter

import pytest

from tests.test_gui import _display_available, app  # noqa: F401 — the window fixture

pytestmark = pytest.mark.skipif(not _display_available(), reason="no display")


@pytest.fixture
def inline(monkeypatch):
    """Page workers run on the spot (no mainloop in a test to carry them back)."""
    from ui.pages import base

    class Now:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            self.target(*self.args, **self.kwargs)

    monkeypatch.setattr(base.threading, "Thread", Now)
    monkeypatch.setattr(base, "safe_after", lambda widget, callback: callback())


def test_every_command_is_in_the_catalogue():
    from jarvis import addons, catalog, registry

    found = catalog.tools()
    names = {n for t in found.values() for n in t.names}
    missing = [n for n in registry.COMMANDS if n not in names]
    assert not missing, missing
    legacy = set(addons.RESERVED_COMMANDS) - {"quit", "exit"}
    assert not [n for n in legacy if n not in names and n not in {"theme", "snip"}]
    assert len(found) > 200


def test_search_finds_tools_by_what_they_do():
    from jarvis import catalog

    assert catalog.search("weather")[0].name == "weather"
    assert any(t.name == "qr" for t in catalog.search("qr code"))
    assert catalog.search("zzzz-nothing") == []
    assert [t.name for t in catalog.suggest("/remi")] [:1] == ["remind"]


def test_forms_build_the_command_text():
    from jarvis.registry import Tool, field, split

    tool = Tool(name="kdv", fields=(field("amount", "number"), field("rate", "choice", options=("20", "10"))))
    assert tool.build({"amount": "1000", "rate": "20"}) == "/kdv 1000 20"
    tool = Tool(name="merge", fields=(field("template", "file"), field("data", "file", optional=True)))
    assert tool.build({"template": "C:/a b.docx", "data": ""}) == "/merge C:/a b.docx"
    assert tool.build({"template": "a.docx", "data": "b.xlsx"}) == "/merge a.docx | b.xlsx"
    assert split("a.docx | b c.xlsx", 2) == ["a.docx", "b c.xlsx"]
    assert split("1000 20", 2) == ["1000", "20"]
    assert split("1000", 3) == ["1000", "", ""]


def test_every_finished_page_imports_and_the_unfinished_list_is_true():
    # The self-test runs the same check in the EXE, where a page module left
    # out of the build once made Home and Coding open empty.
    from ui.pages import PAGES, STILL_BUILDING, page_class

    for page in PAGES:
        if not page.target:
            continue
        if page.key in STILL_BUILDING:
            with pytest.raises(ImportError):
                page_class(page.key)
        else:
            assert page_class(page.key).__name__


def test_a_page_that_cannot_open_says_why(app, monkeypatch):
    from ui import pages
    from ui.pages.base import Hub

    def missing(key):
        raise ModuleNotFoundError("No module named 'ui.pages.home'")

    monkeypatch.setattr(pages, "page_class", missing)
    assert "No module named 'ui.pages.home'" in pages.make("home", app.content, app).subtitle
    for unfinished in sorted(pages.STILL_BUILDING)[:1]:
        assert "still being built" in pages.make(unfinished, app.content, app).subtitle

    class Broken(Hub):
        def build_body(self):
            raise ValueError("bad data")

    page = Broken(app.content, app)
    page.grid(row=0, column=0, sticky="nsew")
    page.show()
    app.update()
    shown = [w.cget("text") for w in page.place_slaves() if isinstance(w, tkinter.Label)]
    assert any("ValueError: bad data" in text for text in shown)
    page.destroy()


def test_a_restarted_exe_unpacks_afresh(app, monkeypatch):
    # 9.9.0: the new copy reused the old one's temporary folder, which the
    # old one deleted on exit — every AI provider then failed with Errno 2.
    import subprocess
    import sys

    from jarvis.config import fresh_process_env

    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI12345")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    env = fresh_process_env()
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not [k for k in env if k.startswith("_PYI_")] and "PATH" in {k.upper() for k in env}

    started = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    monkeypatch.setattr(app, "_on_close", lambda: None)
    app.restart()
    (argv, kw), = started
    assert argv == [sys.executable] and kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_tool_cards_appear_at_once_and_their_forms_follow(app):
    import time

    app._show_tab("study")
    page = app.pages["study"]
    assert page._unfilled, "the cards are drawn before their forms"
    for _ in range(400):
        app.update()
        if not page._unfilled:
            break
        time.sleep(0.005)
    assert not page._unfilled


def test_the_sidebar_lists_every_page_in_folding_sections(app):
    from ui.pages import PAGES

    assert set(app.nav_buttons) == {p.key for p in PAGES}
    header, frame = app._nav_sections["Life"]
    app._set_section("Life", False)
    app.update()
    assert not frame.winfo_ismapped()
    app._show_tab("chat")
    app._set_section("Life", True)
    app.update()
    assert frame.winfo_ismapped()


def test_the_tools_page_has_a_tile_for_everything_and_searches(app):
    app._show_tab("tools")
    app.update()
    page = app.pages["tools"]
    assert app.active_tab == "tools" and page.winfo_ismapped()
    page.search.insert(0, "weather")
    page.refresh()
    shown = [name for name, tile in page.tiles.items() if tile.winfo_manager()]
    assert shown and shown[0] == "weather" or "weather" in shown
    page.search.delete(0, "end")
    page.set_group("All")
    assert sum(1 for tile in page.tiles.values() if tile.winfo_manager()) == len(page.found)


def test_ctrl_k_goes_to_pages_and_tools(app):
    app.open_palette()
    app.update()
    palette = app._palette
    palette.entry.insert(0, "tools")
    palette.fill("tools")
    assert any(v == ("page", "tools") for _, v in palette.items)
    palette.choose()
    app.update()
    assert app.active_tab == "tools"


def test_a_tool_form_runs_its_command_and_shows_the_answer(app, monkeypatch, inline):
    from jarvis.assistant import JarvisResponse
    from ui.pages.base import ToolDialog

    ran = []
    monkeypatch.setattr(app.jarvis, "process", lambda text, **kw: ran.append(text) or JarvisResponse(text="ok: done"))
    dialog = ToolDialog(app, app.tool("weather"))
    app.update()
    dialog.form.inputs["args"][1].insert(0, "Istanbul")
    dialog.form.run()
    app.update()
    assert ran == ["/weather Istanbul"]
    assert "ok: done" in dialog.form.result.text_box.get("1.0", "end")
    dialog.destroy()


def test_chips_offer_tools_for_what_is_being_typed(app):
    app.chat_input.insert(0, "what's the weather in ankara")
    app._update_chips()
    app.update()
    assert app.chips_row.winfo_ismapped()
    app._hide_chips()
    assert not app.chips_row.winfo_children()


def test_home_shows_the_orb_today_and_every_page(app):
    app._show_tab("home")
    app.update()
    page = app.pages["home"]
    assert page.winfo_ismapped() and page.hello.cget("text")
    assert page.clock.cget("text").count(":") == 2
    page.ask.insert(0, "/flip")
    page._ask()
    app.update()
    assert app.active_tab == "chat"


def test_corner_notifications_and_the_status_bar(app, monkeypatch):
    from jarvis import alerts

    monkeypatch.setenv("JARVIS_TOASTS", "on")
    alerts.post("Battery low", "12% left", page="pc", kind="warn")
    app.update()
    assert app._toasts and app._toasts[-1].winfo_exists()
    assert any(a.title == "Battery low" for a in alerts.recent())
    app._statusbar_tick()
    assert "CPU" in app._status_labels["cpu"].cget("text")


def test_shortcuts_can_be_changed_and_take_effect(app):
    from ui import prefs
    from ui.tenui import seq_label

    prefs.set("shortcuts", {"palette": "<Control-p>"})
    app._bind_shortcuts()
    assert "<Control-p>" in app._bound_shortcuts and "<Control-k>" not in app._bound_shortcuts
    assert seq_label("<Control-K>") == "Ctrl+Shift+K"
    assert ("Ctrl+P", "Go to any page or tool") in app.shortcut_lines()
    prefs.set("shortcuts", {})
    app._bind_shortcuts()


def test_the_floating_orb_and_chat_styles(app, monkeypatch):
    app.toggle_orb(True)
    app.update()
    assert app._orb_window is not None and app._orb_window.winfo_exists()
    app.toggle_orb(False)
    assert app._orb_window is None
    monkeypatch.setenv("JARVIS_CHAT_STYLE", "bubbles")
    app._configure_tags()
    app._append_message("You", "hello there", is_user=True)
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    assert box.tag_ranges("ubody")
    assert int(str(box.tag_cget("ubody", "lmargin1"))) > 100


def test_settings_search_and_the_look_and_feel_section(app):
    from ui.settings import SettingsWindow
    from ui.app import COLORS

    window = SettingsWindow(app, COLORS)
    app.update()
    assert "JARVIS_ACCENT" in window.entries and "JARVIS_CHAT_STYLE" in window.choices
    window.search.insert(0, "accent")
    window._filter()
    app.update()
    shown = [child for child, _w, _i in window._rows if child.winfo_manager()]
    assert 0 < len(shown) < len(window._rows)
    window.search.delete(0, "end")
    window._filter()
    assert all(child.winfo_manager() for child, _w, _i in window._rows)
    window.destroy()


def test_accent_colour_mixes_a_matching_dim_shade():
    from ui import theme

    palette = theme.with_accent(theme.get("midnight"), "#ff0000")
    assert palette["accent"] == "#ff0000" and palette["accent_dim"] != "#ff0000"
    assert theme.with_accent(theme.get("midnight"), "nonsense") == theme.get("midnight")
    assert "hud" in theme.THEMES and "ironman" in theme.THEMES
