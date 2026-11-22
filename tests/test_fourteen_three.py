"""14.3: the new look (round buttons, Modern chat, mode picker, typing dots,
the logo) and the Code tab's toolbar (files, changes, plan, built-in preview)."""

from __future__ import annotations

import urllib.request

import pytest

from tests.test_gui import _display_available, app  # noqa: F401

needs_display = pytest.mark.skipif(not _display_available(), reason="no display")


# --- the logo ------------------------------------------------------------------------

def test_the_logo_draws_at_every_size_and_the_icon_exists():
    from ui import logo

    for size in (16, 32, 256):
        image = logo.make(size)
        assert image.size == (size, size) and image.mode == "RGBA"
        # Something is drawn in the middle, and the corners stay see-through.
        assert image.getpixel((size // 2, size // 2))[3] > 0 and image.getpixel((0, 0))[3] < 40
    assert logo.ico_path().is_file()


# --- the built-in preview --------------------------------------------------------------

def test_the_preview_serves_the_project_page_on_this_pc_only(tmp_path):
    from ui import preview

    (tmp_path / "index.html").write_text("<h1>hello preview</h1>", encoding="utf-8")
    page = preview.find_page(tmp_path)
    assert page == tmp_path / "index.html"
    url = preview.url_for(tmp_path, page)
    assert url.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(url, timeout=5) as reply:  # noqa: S310 — our own local server
        assert b"hello preview" in reply.read()
        assert reply.headers.get("Cache-Control") == "no-store"
    preview.stop_all()


def test_the_preview_finds_pages_in_usual_places(tmp_path):
    from ui import preview

    assert preview.find_page(tmp_path) is None
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("x", encoding="utf-8")
    assert preview.find_page(tmp_path) == tmp_path / "public" / "index.html"


def test_the_preview_window_is_edge_in_app_mode_with_its_own_profile(tmp_path):
    from pathlib import Path

    from ui import preview

    args = preview.edge_args(Path("msedge.exe"), "http://127.0.0.1:5000/index.html", tmp_path, (10, 20, 640, 480))
    assert "--app=http://127.0.0.1:5000/index.html" in args
    assert f"--user-data-dir={tmp_path}" in args
    assert "--window-position=10,20" in args and "--window-size=640,480" in args


def test_the_agent_records_what_it_changed(base, tmp_path):
    from tests.test_agent_memory import FakeJarvis, ScriptedBrain, _addon
    from jarvis import agent

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    a = agent.Agent(FakeJarvis(_addon(tmp_path), ScriptedBrain(["```a.py\nx = 2\n```"])))
    a.root = tmp_path
    a.plan = agent.Plan(goal="g", steps=[agent.Step("write", "a.py")])
    a._do_write(agent.Step("write", "a.py"), [])
    name, diff = a.changes[-1]
    assert name == "a.py" and "-x = 1" in diff and "+x = 2" in diff


# --- the window ---------------------------------------------------------------------------

@needs_display
def test_buttons_are_round(app):
    import customtkinter as ctk

    assert ctk.ThemeManager.theme["CTkButton"]["corner_radius"] >= 999
    button = ctk.CTkButton(app, text="x", corner_radius=6)
    assert button.cget("corner_radius") >= 10


@needs_display
def test_modern_chat_has_bubbles_and_no_labels(app, monkeypatch):
    monkeypatch.setenv("JARVIS_CHAT_STYLE", "claude")
    app._configure_tags()
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    app._append_message("You", "hello bubble", is_user=True)
    app._append_message("JARVIS", "Hi **there**", is_user=False)
    app.update()
    text = box.get("1.0", "end")
    assert "hello bubble" in text and "Hi there" in text      # still findable and exportable
    assert "JARVIS:\n" not in text and "You:\n" not in text   # no labels
    assert box.window_names()                                 # your words are a bubble widget
    assert box.tag_ranges("ububble") and box.tag_ranges("jbody")


@needs_display
def test_typing_dots_show_until_the_first_words(app, monkeypatch):
    monkeypatch.setenv("JARVIS_CHAT_STYLE", "claude")
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    app._begin_stream()
    assert box.tag_ranges("typing")
    app._append_stream("First words")
    assert not box.tag_ranges("typing")
    app._end_stream("First words and more")
    assert "First words and more" in box.get("1.0", "end")


@needs_display
def test_the_mode_picker_sits_by_the_box(app):
    assert app.mode_pick.winfo_manager()
    assert not app.mode_btn.winfo_manager()                   # gone from the sidebar
    app._pick_mode("high")
    assert app.jarvis.brain.mode.name == "high" and "High" in app.mode_pick.cget("text")
    app._pick_mode("mid")


@needs_display
def test_switching_tabs_does_not_post_code_mode_off(app):
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    app._show_tab("code")
    app._show_tab("chat")
    assert "Code mode off" not in box.get("1.0", "end")


@needs_display
def test_the_code_tab_toolbar_panels(app, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ADVANCED", "off")
    tmp_path = tmp_path / "site"
    tmp_path.mkdir()
    (tmp_path / "index.html").write_text("<h1>hi</h1>\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("const x = 1;  // one\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    app._show_tab("code")
    page = app.pages["code"]
    assert set(page.tool_buttons) == {"plan", "terminal", "changes", "preview", "files", "more"}
    page.folder = str(tmp_path)
    names = [p.name for p in page.project_files()]
    assert names == ["app.js", "index.html"]                 # node_modules is skipped
    page.show_panel("files")
    page.open_file(tmp_path / "app.js")
    viewer = getattr(page.viewer, "_textbox", page.viewer)
    assert "const x = 1;" in viewer.get("1.0", "end") and viewer.tag_ranges("kw")
    page.show_panel("changes")
    assert "No changes yet" in viewer.get("1.0", "end")
    page.show_panel("plan")
    assert "No plan yet" in viewer.get("1.0", "end")
    page.toggle_panel("plan")
    assert page.panel_view == "" and not page.panel.winfo_manager()


# --- 14.4: agent teams, the tray, and the build keeping your keys ----------------------

def test_teams_are_picked_per_mode():
    from jarvis import teams

    mid = teams.team_for("mid")
    assert mid.lead[0] == ("llmsrelay", "claude-opus-4.7")
    assert mid.checkers[0].targets[0] == ("openrouter", "nvidia/nemotron-3.5-super-vl:free")
    assert len(teams.team_for("max").checkers) == 2
    assert teams.team_for("security").checkers[0].name == "Security reviewer"
    assert all("qwen" not in m for t in teams.TEAMS.values() for _p, m in t.lead)   # Qwen is Low chat only
    assert "Claude Opus 4.7" in mid.describe() and "Nemotron" in mid.describe()


@pytest.mark.parametrize("reply, ok, count", [
    ('{"ok": true}', True, 0),
    ('```json\n{"ok": false, "issues": ["app.js is loaded as main.js"]}\n```', False, 1),
    ("Looks fine to me!", True, 0),                 # unclear never blocks
    ('{"ok": false, "issues": []}', True, 0),       # no named problem, no block
])
def test_checker_verdicts(reply, ok, count):
    from jarvis import teams

    assert teams.parse_review(reply) == (ok, teams.parse_review(reply)[1]) and len(teams.parse_review(reply)[1]) == count
    assert teams.parse_review(reply)[0] is ok


def test_a_team_checks_and_the_lead_fixes(base, tmp_path, monkeypatch):
    from jarvis import agent
    from tests.test_agent_memory import FakeJarvis, ScriptedBrain, _addon

    monkeypatch.setenv("JARVIS_AGENT_TEAMS", "on")
    (tmp_path / "index.html").write_text("old\n", encoding="utf-8")
    brain = ScriptedBrain([
        "```index.html\n<script src='main.js'></script>\n```",                       # the lead writes
        '{"ok": false, "issues": ["it loads main.js but the file is app.js"]}',    # the reviewer
        "```index.html\n<script src='app.js'></script>\n```",                        # the lead fixes
    ])
    a = agent.Agent(FakeJarvis(_addon(tmp_path), brain))
    a.root = tmp_path
    a.plan = agent.Plan(goal="page", steps=[agent.Step("write", "index.html")])
    step = a.plan.steps[0]
    a._do_write(step, [])
    assert "app.js" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "fixed 1 issue" in step.detail and "main.js but the file is app.js" in brain.prompts[2]
    assert len(a.written) == 1                                  # one backup: /undo goes back to "old"
    name, diff = a.changes[-1]
    assert "-old" in diff and "+<script src='app.js'>" in diff
    a.undo()
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "old\n"


def test_teams_off_means_no_checkers(base, tmp_path, monkeypatch):
    from jarvis import agent
    from tests.test_agent_memory import FakeJarvis, ScriptedBrain, _addon

    monkeypatch.setenv("JARVIS_AGENT_TEAMS", "off")
    brain = ScriptedBrain(["```a.py\nx = 1\n```"])
    a = agent.Agent(FakeJarvis(_addon(tmp_path), brain))
    a.root = tmp_path
    a.plan = agent.Plan(goal="g", steps=[agent.Step("write", "a.py")])
    a._do_write(a.plan.steps[0], [])
    assert len(brain.prompts) == 1 and not a.reviews


def test_the_teams_command(base, monkeypatch):
    from jarvis.assistant import Jarvis

    jarvis = Jarvis(voice_enabled=False)
    assert "Agent teams: on" in jarvis.process("/agentteam on").text
    assert "Claude Opus 4.7" in jarvis.process("/agentteam").text
    assert "Agent teams: off" in jarvis.process("/agentteam off").text


def test_the_build_merges_env_and_never_drops_a_saved_key(tmp_path):
    import build

    source, target = tmp_path / "project.env", tmp_path / "dist.env"
    source.write_text("GROQ_API_KEY=gsk_project\nOPENROUTER_API_KEY=\nNEW_KEY=abc\n", encoding="utf-8")
    target.write_text("GROQ_API_KEY=\nOPENROUTER_API_KEY=sk-or-saved-in-the-exe\n", encoding="utf-8")
    build.merge_env(source, target)
    text = target.read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-saved-in-the-exe" in text      # kept, not wiped
    assert "GROQ_API_KEY=gsk_project" in text and "NEW_KEY=abc" in text


def test_the_tray_is_on_by_default_and_can_be_turned_off(monkeypatch):
    from ui import tray

    monkeypatch.delenv("JARVIS_TRAY", raising=False)
    assert tray.enabled()
    monkeypatch.setenv("JARVIS_TRAY", "off")
    assert not tray.enabled()
    assert tray.Tray(object()).available()
