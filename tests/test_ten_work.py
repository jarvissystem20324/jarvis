"""10.0 productivity: subtasks, repeating tasks, goals, the notebook's links,
bookmarks, the end-of-day summary, and the four pages that show them."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def jarvis(base):
    from jarvis.assistant import Jarvis

    return Jarvis(voice_enabled=False)


def test_a_repeating_task_comes_back_after_it_is_ticked(base):
    from jarvis.ten import work

    due = (datetime.now() + timedelta(hours=2)).timestamp()
    work.add_task("water the plants", due, "daily")
    note = work.finish_task(0)
    items = work.load_tasks()
    assert "back on" in note and len(items) == 2
    assert items[0]["done"] and not items[1]["done"]
    assert items[1]["due"] - due == pytest.approx(86400, abs=5)


def test_weekdays_skip_the_weekend():
    from jarvis.ten import work

    friday = datetime(2026, 10, 2, 9, 0).timestamp()           # a Friday
    nxt = datetime.fromtimestamp(work.next_due(friday, "weekdays", now=friday))
    assert nxt.weekday() == 0                                   # Monday


def test_subtasks_and_recur_commands(jarvis):
    jarvis.process("/mylist add plan the trip")
    out = jarvis.process("/subtask plan the trip | book flights").text
    assert "☐ book flights" in out
    out = jarvis.process("/recur plan the trip weekly").text
    assert "repeats weekly" in out
    from jarvis.ten import work

    item = work.load_tasks()[0]
    assert item["repeat"] == "weekly" and work.progress(item) == 0.0
    work.toggle_subtask(0, 0)
    assert work.progress(work.load_tasks()[0]) == 1.0


def test_goals_track_progress(jarvis):
    assert "New goal" in jarvis.process("/goal add Read 12 books | 12 books by 2026-12-31").text
    out = jarvis.process("/goal 1 +3").text
    assert "3/12" in out
    assert "Goal reached" in jarvis.process("/goal 1 done").text


def test_notes_link_to_each_other(base):
    from jarvis.ten import work

    work.save_note({"title": "Trip", "body": "See [[Packing]] and [[Budget]]", "folder": "Travel"})
    work.save_note({"title": "Packing", "body": "passport"})
    assert work.links("See [[Packing]] and [[Budget]]") == ["Packing", "Budget"]
    assert [n["title"] for n in work.backlinks("packing")] == ["Trip"]
    assert work.folders() == ["Notes", "Travel"]
    assert work.search_notes("passport")[0]["title"] == "Packing"


def test_bookmarks_import_from_a_chrome_file():
    from jarvis.ten import work

    data = {"roots": {"bookmark_bar": {"type": "folder", "name": "Bar", "children": [
        {"type": "url", "name": "Python", "url": "https://python.org"},
        {"type": "folder", "name": "Dev", "children": [{"type": "url", "name": "GH", "url": "https://github.com"}]},
        {"type": "url", "name": "local", "url": "chrome://settings"}]}}}
    found = work.parse_bookmarks(data)
    assert [b["url"] for b in found] == ["https://python.org", "https://github.com"]
    assert found[1]["tags"] == ["Dev"]


def test_the_end_of_day_summary(jarvis):
    from jarvis.ten import work

    work.add_task("send the report")
    work.finish_task(0)
    out = jarvis.process("/eod").text
    assert "send the report" in out and "Done (1)" in out


def test_drafts_use_my_tone(jarvis, monkeypatch):
    asked = []
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **kw: asked.append(prompt) or "- short\n- warm")
    jarvis.process("/mytone Hey! Quick one — can we move it to 3? Cheers, Ahmet")
    out = jarvis.process("/draft Can you send the slides by Friday? | yes, Thursday").text
    assert "nothing is sent" in out
    assert "Cheers, Ahmet" in asked[-1] and "yes, Thursday" in asked[-1]


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_productivity_pages_open_and_work(app):
    from jarvis.ten import work

    app._show_tab("today")
    app.update()
    today = app.pages["today"]
    today.new_task.insert(0, "buy milk tomorrow 10:00")
    today.add_task()
    assert work.load_tasks()[-1]["text"] == "buy milk"
    for key in ("calendar", "notes", "inbox"):
        app._show_tab(key)
        app.update()
        assert app.pages[key].winfo_ismapped()
    cal = app.pages["calendar"]
    cal.ev_title.insert(0, "Dentist")
    cal.ev_time.insert(0, "14:30")
    cal.add_event()
    from jarvis.life import CALENDAR

    assert CALENDAR.load()[-1]["title"] == "Dentist"
    notes = app.pages["notes"]
    app._show_tab("notes")
    notes.new_note()
    notes.title_entry.insert(0, "Ideas")
    notes.text.insert("1.0", "link to [[Plans]]")
    notes.save()
    notes._mark_links()
    assert notes.text.tag_ranges("link")
    assert work.by_title("ideas")["body"] == "link to [[Plans]]"
