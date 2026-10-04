"""10.0 automations: triggers fire once and at the right time, steps run in
order and are logged, routines answer their phrase, pause stops everything,
and the page builds and saves an automation."""

from __future__ import annotations

import time
from datetime import datetime

import pytest


@pytest.fixture
def jarvis(base):
    from jarvis.assistant import Jarvis

    return Jarvis(voice_enabled=False)


def test_time_triggers_fire_once_a_day_and_not_late():
    from jarvis.ten import automate

    state: dict = {}
    trigger = {"type": "time", "at": "08:30", "days": "every day"}
    assert not automate.time_due(trigger, state, datetime(2026, 10, 5, 8, 0))
    assert automate.time_due(trigger, state, datetime(2026, 10, 5, 8, 31))
    assert not automate.time_due(trigger, state, datetime(2026, 10, 5, 8, 40))
    late: dict = {}
    assert not automate.time_due(trigger, late, datetime(2026, 10, 5, 14, 0))
    assert not automate.time_due({"type": "time", "at": "08:30", "days": "weekdays"}, {},
                                 datetime(2026, 10, 4, 8, 31))          # a Sunday


def test_routines_run_their_steps_and_log(jarvis):
    from jarvis.ten import automate

    out = jarvis.process("/routine good night | /flip ; notify Sleep well").text
    assert "2 step(s)" in out
    reply = jarvis.process("Good night!").text
    assert reply.startswith("⚙ Good night")
    log = automate.AUTO_LOG.load()
    assert log and log[0]["ok"] and "notified" in log[0]["detail"]


def test_pause_stops_routines(jarvis):
    jarvis.process("/routine lights out | notify ok")
    jarvis.process("/automation pause")
    assert jarvis.match_routine("lights out") is None
    jarvis.process("/automation resume")
    assert jarvis.match_routine("lights out") is not None


def test_folder_trigger_waits_for_the_file_to_settle(base, tmp_path):
    from jarvis.ten import automate

    fired = []
    engine = automate.Engine()
    engine.fire = lambda automation, trigger, context=None: fired.append(context)
    automation = automate.new_automation("dl", {"type": "folder", "folder": str(tmp_path), "pattern": "*"}, [])
    state: dict = {}
    engine._folder(automation, automation["trigger"], state)
    (tmp_path / "new.pdf").write_bytes(b"x" * 10)
    engine._folder(automation, automation["trigger"], state)
    assert not fired                                      # first sighting: wait for a stable size
    engine._folder(automation, automation["trigger"], state)
    assert fired and fired[0]["file"] == "new.pdf"


def test_steps_fill_in_the_context(jarvis, monkeypatch):
    from jarvis import alerts
    from jarvis.ten import automate

    posted = []
    monkeypatch.setattr(alerts, "post", lambda title, body="", page="", kind="info": posted.append(body))
    ok, detail = automate.run_steps(jarvis, {"name": "t", "steps": [{"type": "notify", "value": "file {file} at {time}"},
                                                                     {"type": "command", "value": "/flip"}]},
                                    {"file": "a.pdf", "time": "09:00"})
    assert ok and posted == ["file a.pdf at 09:00"] and "/flip" in detail


def test_unapproved_scripts_do_not_run(jarvis, tmp_path):
    from jarvis.ten import automate

    script = tmp_path / "x.py"
    script.write_text("print(1)", encoding="utf-8")
    ok, detail = automate.run_steps(jarvis, {"name": "s", "steps": [{"type": "script", "value": str(script)}]}, {})
    assert not ok and "wasn't approved" in detail


def test_parse_steps():
    from jarvis.ten import automate

    steps = automate.parse_steps("/volume 20 ; say Good night ; media pause ; wait 2")
    assert [s["type"] for s in steps] == ["command", "say", "command", "wait"]
    assert steps[2]["value"] == "/media pause"


def test_macro_tidy_drops_the_stop_click():
    from jarvis import macro

    events = [[0.1, "key", 65, 1], [0.2, "key", 65, 0], [0.3, "move", 5, 5], [0.4, "click", 5, 5, "left", 1],
              [0.5, "click", 5, 5, "left", 0], [0.6, "move", 6, 6]]
    assert macro.tidy(events) == events[:2]
    assert "1 key press" in macro.describe(events[:2])


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_automations_page_builds_and_saves(app):
    from jarvis.ten import automate

    app._show_tab("automations")
    app.update()
    page = app.pages["automations"]
    page._use_template(automate.TEMPLATES[0])
    page.name.delete(0, "end")
    page.name.insert(0, "My rain alert")
    page.save()
    saved = automate.load()
    assert saved and saved[-1]["name"] == "My rain alert" and saved[-1]["trigger"]["type"] == "rain"
    page.fill_list()
    assert page.list_box.winfo_children()
