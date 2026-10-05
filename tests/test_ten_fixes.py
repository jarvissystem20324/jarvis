"""10.0.1: the bugs a sweep of every command and every page turned up, and
what now catches the next ones (the error log, and a command that trips
answering with its usage instead of a Python error)."""

from __future__ import annotations

import sys
import threading

import pytest

from jarvis import errorlog, kit, registry


def test_numbers_in_commands_are_read_leniently():
    assert kit.whole("15", 3) == 15 and kit.whole("15 questions", 3) == 15 and kit.whole(" 2 ", 9) == 2
    assert kit.whole("test", 7) == 7 and kit.whole("", 7) == 7 and kit.whole(None, 7) == 7
    assert kit.whole("90", 15, 3, 50) == 50 and kit.whole("-4", 15, 3, 50) == 3


def test_the_error_log(base):
    try:
        int("nope")
    except ValueError as exc:
        line = errorlog.record("a test", exc)
    assert line.startswith("ValueError: invalid literal")
    text = errorlog.log_path().read_text(encoding="utf-8")
    assert "a test" in text and "Traceback" in text and "JARVIS" in text
    assert errorlog.recent(1)[0].endswith(line)
    big = "x" * 4000
    for _ in range(80):
        errorlog.record("filler", RuntimeError(big))
    assert errorlog.log_path().stat().st_size <= errorlog.LIMIT + 10_000          # it never grows without end
    assert errorlog.log_path().read_text(encoding="utf-8").startswith("=== ")


def test_a_command_that_trips_answers_with_its_usage(base, monkeypatch):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    monkeypatch.setattr(type(j), "debate_cmd", lambda self, args, routed=False: int("oops"), raising=True)
    reply = j.eight_command("debate", "something")
    assert "/debate couldn't do that (ValueError" in reply and "Usage: /debate" in reply and "/errors" in reply
    assert j.eight_command("debate", "something", routed=True) is None           # a sentence goes to the AI
    assert "debate" in errorlog.recent(1)[0]
    assert "Recent errors" in j.errors_cmd("") and "cleared" in j.errors_cmd("clear")


def test_number_fields_that_get_words(base, monkeypatch):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    asked = []
    monkeypatch.setattr(j.brain, "ask_once", lambda prompt, **k: (asked.append(prompt), "{}")[1])
    for text in ("Rome | lots | many | mid", "Rome | 🙂 test"):
        assert "couldn't do that" not in str(j.tripbudget_cmd(text))
    assert "5 days" in asked[0] and "2 people" in asked[0]
    assert "couldn't do that" not in str(j.practicetest_cmd("volcanoes | fifteen | mixed"))
    assert "with 15 mixed" in asked[-1]


def test_json_to_types_names_the_languages_it_knows():
    from jarvis.ten import coding

    with pytest.raises(coding.CodingError, match="python, typescript"):
        coding.json_to_types({"a": 1}, "2")
    assert "interface Root" in coding.json_to_types({"a": 1}, "ts")
    assert "class Root" in coding.json_to_types({"a": 1}, "c#")


def test_a_program_that_wont_start_is_a_message(monkeypatch):
    import subprocess

    from jarvis import pctools
    from jarvis.ten import coding

    def blocked(*a, **k):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(subprocess, "run", blocked)
    with pytest.raises(coding.CodingError, match="wouldn't start"):
        coding.run_program(["python", "-V"])
    assert pctools.wifi_info() == {}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")
def test_recent_documents_resolve_their_shortcuts(tmp_path):
    from jarvis.ten import office

    target = tmp_path / "report.docx"
    target.write_bytes(b"x")
    link = tmp_path / "report.docx.lnk"
    try:
        import win32com.client

        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
        shortcut.TargetPath = str(target)
        shortcut.Save()
    except Exception as exc:
        pytest.skip(f"can't make a shortcut here: {exc}")
    assert office.resolve_link(link) == target
    found = []
    worker = threading.Thread(target=lambda: found.append(office.resolve_link(link)))   # the page resolves on a thread
    worker.start()
    worker.join()
    assert found == [target]


def test_every_form_builds_a_real_command():
    from jarvis.assistant import Jarvis  # noqa: F401  (registers every command)

    for tool in registry.TOOLS.values():
        if not tool.fields:
            continue
        values = {f.name: (f.default or (f.options[0] if f.options else "")) for f in tool.fields}
        text = tool.build(values)
        assert text[1:].split(" ", 1)[0] in registry.COMMANDS, tool.name


# --- the window -----------------------------------------------------------------------------------

from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_animations_rest_while_the_window_moves(app):
    from types import SimpleNamespace

    from ui import orb

    app.update()
    assert app.window_settled()
    app._window_changed(SimpleNamespace(widget=app, x=10, y=10, width=900, height=600))
    app._window_changed(SimpleNamespace(widget=app, x=40, y=10, width=900, height=600))   # dragged
    assert not app.window_settled() and orb.PAUSED()
    app._window_changed(SimpleNamespace(widget=app.content, x=0, y=0, width=1, height=1))  # a child: ignored
    app._settle_at = 0
    assert app.window_settled() and not orb.PAUSED()
    canvas = orb.Orb(app, 120, "#38bdf8", "#0f172a", label="J")
    canvas.draw()
    shapes = set(canvas.find_all())
    canvas._start -= 1.5
    canvas.draw()
    assert set(canvas.find_all()) == shapes and len(shapes) == 25                 # moved, not re-made
    canvas.destroy()


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_a_failing_button_is_logged_not_lost(app, monkeypatch):
    posted = []
    from jarvis import alerts

    monkeypatch.setattr(alerts, "post", lambda *a, **k: posted.append((a, k)))
    monkeypatch.setattr(errorlog, "_last_alert", [0.0])

    def broken():
        raise ZeroDivisionError("a broken button")

    app.after(0, broken)
    app.update()
    assert "ZeroDivisionError: a broken button" in errorlog.log_path().read_text(encoding="utf-8")
    assert posted and posted[0][0][0] == "Something went wrong"
    done = threading.Event()

    def thread_fails():
        try:
            raise KeyError("from a worker")
        finally:
            done.set()

    worker = threading.Thread(target=thread_fails, name="worker-x")
    worker.start()
    worker.join()
    assert "worker-x" in errorlog.log_path().read_text(encoding="utf-8")
