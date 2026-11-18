"""13.4.2's window: Chat and Code on one sliding bar at the top, the Cowork
switch beside Send, and the Cowork panel."""

from __future__ import annotations

import pytest

from tests.test_gui import _display_available, app  # noqa: F401 — the window fixture

pytestmark = pytest.mark.skipif(not _display_available(), reason="no display")


def settle(app, rounds: int = 40) -> None:
    import time

    for _ in range(rounds):
        app.update()
        time.sleep(0.01)


def test_the_top_bar_switches_between_chat_and_code(app):
    bar = app.top_tabs
    assert bar.get() == "chat"
    app._show_tab("code")
    settle(app)
    assert bar.get() == "code" and app.active_tab == "code"
    assert abs(bar._pill_x - bar._x_for("code")) < 1          # the pill finished sliding
    app._show_tab("music")
    assert bar.get() is None                                  # neither: no pill
    bar.command("chat")
    settle(app)
    assert app.active_tab == "chat" and bar.get() == "chat"
    # Icon-only, drawn on the canvas: a bubble and </>, no text items.
    assert not [i for i in bar.find_all() if bar.type(i) == "text"]
    assert bar.tips == {"chat": "Chat", "code": "Code"}


def test_the_cowork_switch_turns_send_into_start(app, monkeypatch):
    from jarvis import cowork

    started = []
    monkeypatch.setattr(cowork.manager, "start",
                        lambda goal, kind=None, wait=False: started.append(goal) or cowork.Job(99, goal, "research"))
    app.cowork_switch.set("cowork")
    app._set_cowork("cowork")
    settle(app, 5)
    assert app.send_btn.cget("text") == "Start"
    assert app.cowork_panel.winfo_ismapped()
    app.chat_input.insert(0, "research the best student laptops under 30000 TL")
    app._send_chat()
    assert started == ["research the best student laptops under 30000 TL"]
    assert "Cowork job #99" in app.chat_log.get("1.0", "end")
    # A typed command still runs as a command.
    app.chat_input.insert(0, "/help")
    app._send_chat()
    assert started == ["research the best student laptops under 30000 TL"]
    app._set_cowork("ask")
    assert app.send_btn.cget("text") != "Start"


def test_a_finished_job_reports_in_the_chat_and_the_panel(app):
    from jarvis import cowork

    job = cowork.Job(41, "compare offers", "folder", title="Offers")
    job.status, job.progress, job.finished = "running", 0.5, 0
    job.steps = [cowork.Step("Read files", "running", "3/6")]
    app._cowork_update(job)
    card = app.cowork_panel.cards[41]
    assert "50%" in card.status.cget("text")
    job.status, job.progress, job.finished, job.result = "done", 1.0, 1.0, "Compared 6 document(s)."
    job.steps[0].status = "done"
    app._cowork_update(job)
    assert card.status.cget("text").endswith("Done")
    assert "Job #41 done" in app.chat_log.get("1.0", "end")
    app._cowork_update(job)
    assert app.chat_log.get("1.0", "end").count("Job #41 done") == 1   # said once
