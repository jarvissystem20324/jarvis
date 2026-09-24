"""The window itself. Skipped where there is no display to draw on.

These build the real JarvisApp. They exist because two shipped bugs lived
entirely in the UI layer and no other test could see them: the 3.0 Update
button that raised before downloading anything, and 4.0's markdown renderer
that was written, tested on its own, and never actually called by the chat.
"""

from __future__ import annotations

import pytest


def _display_available() -> bool:
    try:
        import tkinter

        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _display_available(), reason="no display")


@pytest.fixture
def app(base, allow, monkeypatch):
    import time
    import tkinter

    import ui.app as ui_app

    # The window checks for updates 2.5s after it opens, over the network.
    # A slow test outlived that once and the real check's result landed in
    # the middle of the update-dialog test. Tests do not touch the network.
    monkeypatch.setattr(ui_app.updater, "get_update_url", lambda: "")

    # Creating many Tk interpreters in one process occasionally fails on
    # Windows with "couldn't read file .../tcl8.6/auto.tcl" although the file
    # is there — measured at about one run in three. That is Tcl starting up,
    # not anything under test, so the creation alone is retried.
    for attempt in range(3):
        try:
            window = ui_app.JarvisApp()
            break
        except tkinter.TclError:
            if attempt == 2:
                raise
            time.sleep(0.5)
    window.update()
    yield window
    try:
        window.destroy()
    except Exception:
        pass


def _text(window) -> str:
    box = getattr(window.chat_log, "_textbox", window.chat_log)
    return box.get("1.0", "end")


def test_replies_are_rendered_as_markdown(app):
    app._append_message("JARVIS", "# Title\n- item with `code` and **bold**\n\n"
                                  "```python\ndef f():\n    return 1\n```", is_user=False)
    app.update()
    body = _text(app)
    assert "**" not in body and "```" not in body and "•" in body
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    used = {tag for tag in box.tag_names() if box.tag_ranges(tag)}
    assert {"kw", "code_bg", "bold", "inline", "h"} <= used


def test_streamed_replies_are_rendered_too(app):
    """The test above passed while every real reply showed raw ** and ```:
    live answers stream, and the streamed path wrote plain text. That is the
    path almost every answer takes."""
    app._begin_stream()
    app._append_stream("**bo")
    app._append_stream("ld** text")
    app._end_stream("# Title\n**bold** text\n\n```python\nx = 1\n```")
    app.update()
    body = _text(app)
    assert "**" not in body and "```" not in body
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    used = {tag for tag in box.tag_names() if box.tag_ranges(tag)}
    assert {"bold", "h", "code_bg"} <= used


def test_the_conversation_list_switches_and_redraws(app):
    from jarvis import history

    app.jarvis.brain.history = [{"role": "user", "content": "first chat question"},
                                {"role": "assistant", "content": "first answer"}]
    app.jarvis.save_history()
    app.jarvis.chats("new second")
    app._render_conversation()
    assert "first chat question" not in _text(app)
    app._switch_chat("main")
    app.update()
    assert history.current_name() == "main"
    assert "first chat question" in _text(app)
    names = [child.cget("text") for child in app.chat_list.winfo_children()]
    assert "main" in names and "second" in names


def test_a_due_reminder_appears_in_the_chat(app, monkeypatch):
    from jarvis import reminders
    from ui import notify

    shown = []
    monkeypatch.setattr(notify, "toast", lambda title, body: shown.append((title, body)))
    monkeypatch.setattr(notify, "flash", lambda window: None)
    item = reminders.Reminder(1, "reminder", "call Ata", 0, 0)
    app._show_reminder(item)
    assert "call Ata" in _text(app)
    assert shown == [("JARVIS — Reminder", "call Ata")]


def _embedded(app) -> list:
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    return [box.nametowidget(name) for name in box.window_names()]


def test_code_blocks_get_copy_and_save(app):
    app._append_message("JARVIS", "Try:\n```python\nprint('hi')\n```", is_user=False)
    app.update()
    bars = _embedded(app)
    labels = [child.cget("text") for bar in bars for child in bar.winfo_children()]
    assert "Copy" in labels and "Save…" in labels
    copy_button = next(child for bar in bars for child in bar.winfo_children() if child.cget("text") == "Copy")
    copy_button.invoke()
    assert app.clipboard_get() == "print('hi')"


def test_up_brings_back_the_last_question_and_edit_drops_the_answer(app):
    app.jarvis.brain.history = [{"role": "user", "content": "what is 2+2"},
                                {"role": "assistant", "content": "4"}]
    app.chat_input.delete(0, "end")
    app._recall_last()
    assert app.chat_input.get() == "what is 2+2"
    app.chat_input.delete(0, "end")
    assert "back in the box" in app._ui_command("/edit")
    assert app.chat_input.get() == "what is 2+2" and app.jarvis.brain.history == []


def test_suggestions_are_clickable(app):
    sent = []
    app._run_text = sent.append
    app._show_suggestions(["How long does it take?", "What flour?"])
    buttons = [child for bar in _embedded(app) for child in bar.winfo_children()]
    buttons[1].invoke()
    assert sent == ["What flour?"]


def test_zoom_changes_the_body_text_too(app):
    """The Text size setting only ever reached headings, bold and code."""
    start = app._font_size
    app._zoom(1)
    assert app._font_size == start + 2
    assert app.chat_log.cget("font").cget("size") == start + 2
    app._zoom(0, reset=True)
    assert app._font_size == start


def test_mini_mode_toggles(app):
    app._toggle_mini()
    assert app._mini and not app.sidebar_frame.winfo_ismapped()
    app._toggle_mini()
    app.update()
    assert not app._mini


def test_a_password_goes_to_the_clipboard_and_nowhere_else(app):
    text = app._ui_command("/password 24")
    password = app.clipboard_get()
    assert len(password) == 24 and password not in text
    assert password not in _text(app)
    assert all(password not in m["content"] for m in app.jarvis.brain.history)


def test_the_lock_screen_blocks_everything_until_the_pin(app, base):
    from jarvis import applock

    applock.set_pin("2468")
    app._lock_now()
    app.update()
    assert app._locked
    app.chat_input.insert(0, "hello")
    app._send_chat()                       # ignored while locked
    assert "hello" not in _text(app)
    entry = app._lock_entry
    entry.insert(0, "0000")
    app._lock_attempt()
    app.update()
    assert app._locked
    entry.delete(0, "end")
    entry.insert(0, "2468")
    app._lock_attempt()
    app.update()
    assert not app._locked


def test_the_memory_manager_lists_and_forgets(app):
    entry = next(e for e in app.jarvis.addons.loaded if e.addon.name == "memory")
    entry.addon.remember(app.jarvis.addons.ctx, "Ahmed prefers short answers")
    app._open_memory_manager()
    app.update()
    window = [w for w in app.winfo_children() if w.winfo_class() == "CTkToplevel" or "toplevel" in str(w)][-1]
    assert window.title() == "What JARVIS remembers"
    window.destroy()


def test_quick_ask_opens_a_popup(app):
    app.quick_ask()
    app.update()
    assert app._quick_popup.winfo_exists()
    app._quick_popup.destroy()


def test_find_highlights_and_copy_takes_the_code(app):
    app._append_message("JARVIS", "Use this:\n```python\nprint('hi')\n```", is_user=False)
    assert "match" in app._ui_command("/find print")
    app._ui_command("/copy code")
    assert app.clipboard_get().strip() == "print('hi')"


def test_first_run_greets_once(app, base):
    assert "Welcome to JARVIS" in _text(app)
    assert (base / "data" / ".welcomed").exists()
    assert "Welcome to JARVIS" in app._ui_command("/setup")


def test_generated_images_appear_in_the_chat(app, base):
    from PIL import Image

    from jarvis.assistant import JarvisResponse

    paths = []
    for i in range(2):
        path = base / f"img{i}.png"
        Image.new("RGB", (64, 64), (i * 100, 0, 0)).save(path)
        paths.append(path)
    app._begin_stream()
    app._handle_response(JarvisResponse(text="done", image_path=paths[0], image_paths=paths))
    app.update()
    box = getattr(app.chat_log, "_textbox", app.chat_log)
    assert len(box.image_names()) >= 2
    assert app.active_tab == "chat"            # it no longer yanks you away


def test_progress_is_shown_only_while_busy(app):
    app._show_progress("Asking Groq…")
    assert app.status_label.cget("text") != "Asking Groq…"
    app._busy = True
    app._show_progress("Asking Groq…")
    assert app.status_label.cget("text") == "Asking Groq…"
    app._busy = False


def test_provider_line_shows_health(app, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    app.jarvis.brain._dead.add("groq")
    assert "✕ Groq" in app._provider_text()


def test_the_update_button_starts_a_download(app, monkeypatch):
    """3.0 shipped with this button raising AttributeError before downloading."""
    import ui.app as ui_app

    started = []
    monkeypatch.setattr(ui_app.updater, "download_update",
                        lambda info, progress=None: started.append(1) or info)
    monkeypatch.setattr(ui_app.updater, "apply_update", lambda path: None)

    class Info:
        version, notes = "9.9", "x"

    dialog = ui_app.UpdateDialog(app, Info())
    dialog._install()
    import time

    for _ in range(20):
        app.update()
        if started:
            break
        time.sleep(0.05)
    assert started


def test_a_pre_downloaded_update_is_a_restart_not_a_download(app, monkeypatch, base):
    import ui.app as ui_app

    applied = []
    monkeypatch.setattr(ui_app.updater, "download_update",
                        lambda *a, **k: pytest.fail("downloaded twice"))
    monkeypatch.setattr(ui_app.updater, "apply_update", lambda path: applied.append(path))

    staged = base / "JARVIS.update"
    staged.write_bytes(b"x")

    class Info:
        version, notes = "9.9", "x"

    dialog = ui_app.UpdateDialog(app, Info(), downloaded=staged)
    assert dialog.install_btn.cget("text") == "Restart to update"
    dialog._install()
    import time

    for _ in range(20):
        app.update()
        if applied:
            break
        time.sleep(0.05)
    assert applied == [staged]


def test_permission_dialog_defaults_to_deny(app):
    import ui.app as ui_app

    from jarvis import security

    dialog = ui_app.PermissionDialog(app, security.Request(security.RUN_COMMAND, "echo", "/run"))
    assert dialog.allowed is False
    dialog._deny()


def test_a_notification_never_breaks_anything(app):
    from ui import notify

    notify.flash(app)                      # must not raise, whatever the OS
    assert notify._ps_quote("it's") == "'it''s'"
