"""14.1: image analysis, the beginner Code tab, and Cowork's folder chooser."""

from __future__ import annotations

import pytest
from PIL import Image

from jarvis import vision
from tests.test_gui import _display_available, app  # noqa: F401 — the window fixture


class FakeBrain:
    def __init__(self):
        self.calls = []

    def ask_once(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return "## What it is\nA red square."


def test_image_analysis_measures_locally_then_asks_the_vision_model(base, allow, tmp_path):
    path = tmp_path / "red.png"
    Image.new("RGB", (320, 200), "#ff0000").save(path)
    measured = vision.facts(path)
    assert measured["size"] == "320 × 200" and measured["colours"][0] == "#ff0000"
    brain = FakeBrain()
    text = vision.analyse(brain, path, "what colour is it?")
    prompt, kwargs = brain.calls[0]
    assert kwargs["image_b64"] and "what colour is it?" in prompt and "never name" in prompt
    assert "A red square" in text and "320 × 200" in text


def test_image_analysis_asks_first_and_sends_nothing_when_refused(base, deny, tmp_path):
    path = tmp_path / "p.png"
    Image.new("RGB", (10, 10), "blue").save(path)
    brain = FakeBrain()
    with pytest.raises(vision.VisionError, match="Not sent"):
        vision.analyse(brain, path)
    assert brain.calls == []
    with pytest.raises(vision.VisionError):
        vision.analyse(brain, tmp_path / "missing.png")


def test_analyze_is_registered():
    from jarvis.registry import TOOLS

    assert "analyze" in TOOLS


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_code_tab_is_simple_until_advanced_mode(app, monkeypatch):
    from ui.pages.codesimple import SimpleCodePage

    monkeypatch.setenv("JARVIS_ADVANCED", "off")
    app._show_tab("code")
    page = app.pages["code"]
    assert isinstance(page, SimpleCodePage)
    assert "Choose a folder" in page.folder_btn.cget("text")
    monkeypatch.setenv("JARVIS_ADVANCED", "on")
    app._show_tab("chat")
    app._show_tab("code")
    assert not isinstance(app.pages["code"], SimpleCodePage)


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_cowork_sends_the_chosen_folder_with_the_job(app, monkeypatch, tmp_path):
    from jarvis import cowork

    started = []
    monkeypatch.setattr(cowork.manager, "start",
                        lambda goal, kind=None, wait=False: started.append(goal) or cowork.Job(5, goal, "folder"))
    app._set_cowork("cowork")
    assert app.cowork_bar.winfo_manager()
    app._cowork_folder = str(tmp_path)
    app.start_cowork("compare these files")
    assert started == [f"compare these files (folder: {tmp_path})"]
    assert cowork.find_folder(started[0]) == tmp_path
    app._set_cowork("ask")
    assert not app.cowork_bar.winfo_manager()
