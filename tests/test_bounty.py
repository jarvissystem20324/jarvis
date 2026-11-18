"""The Bounty update: Memory 2.0, Focus mode 2.0, Build it live, upscaling,
proactive nudges and the new add-ons. Nothing reaches the network or the AI."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from jarvis import buildlive, focus, images, kb, nudges


class FakeBrain:
    def __init__(self, reply):
        self.reply, self.prompts, self.min_tokens = reply, [], 0

    def ask_once(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.reply


def test_knowledge_finds_and_cites_across_chats_notes_and_facts(base):
    sources = [kb.Source("chat", "Chat “club”, 2026-11-01", "Q: budget?\nA: The robotics club budget is 4000 TL."),
               kb.Source("note", "Note “shopping”", "milk eggs bread"),
               kb.Source("fact", "Something you told me to remember", "My exam is on 12 January.")]
    found = kb.search("robotics club budget", sources=sources)
    assert found and found[0].kind == "chat"
    brain = FakeBrain("The budget is 4000 TL [1].")
    reply = kb.answer(brain, "what is the robotics club budget?", sources=sources)
    assert "4000 TL [1]" in reply and "Chat “club”" in reply and "untrusted" in brain.prompts[0]
    assert "couldn't find" in kb.answer(brain, "zebra migration", sources=sources)


def test_focus_blocks_distractions_in_browsers_only():
    block = {"sites": ["youtube"], "apps": ["steam.exe"]}
    assert focus.blocked("Funny cats - YouTube - Google Chrome", "chrome.exe", block) == "youtube"
    assert focus.blocked("youtube notes.docx - Word", "winword.exe", block) == ""
    assert focus.blocked("Steam", "steam.exe", block) == "steam.exe"


def test_focus_session_runs_blocks_breaks_and_stats(base, monkeypatch):
    shown, minimised = [], []
    windows = iter([("Cats - YouTube", "chrome.exe")] + [("Essay.docx", "winword.exe")] * 10)
    engine = focus.Focus(notify=lambda t, b: shown.append(t), front=lambda: next(windows),
                         minimise=lambda: minimised.append(1))
    monkeypatch.setattr(focus.threading, "Thread", lambda **k: SimpleNamespace(start=lambda: None))
    assert "25 min on" in engine.start(25, 5, 2)
    start = engine.session.ends - 25 * 60
    engine.tick(start + 10)
    assert minimised == [1] and engine.session.stopped_now == 1 and shown[-1].startswith("Back to it")
    engine.tick(start + 25 * 60 + 1)
    assert engine.session.phase == "break"
    engine.tick(engine.session.ends + 1)
    assert engine.session.phase == "focus" and engine.session.block == 2
    engine.tick(engine.session.ends + 1)
    assert engine.session.phase == "done"
    today = dict(focus.week())[datetime.now().date().isoformat()]
    assert today["sessions"] == 2 and today["minutes"] == 50 and today["blocked"] == 1
    assert "Focus this week" in focus.stats_text()


def test_build_it_live_writes_one_self_contained_page(base):
    brain = FakeBrain("Here you go:\n```html\n<!doctype html><html><head><script src=\"https://cdn.x/y.js\">"
                      "</script></head><body><h1>Robotics Club</h1><script>let n=0</script></body></html>\n```")
    site = buildlive.build(brain, "a site for our robotics club with a quiz")
    html = (site / "index.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "Robotics Club" in html
    assert "cdn.x" not in html and "let n=0" in html
    with pytest.raises(buildlive.LiveError):
        buildlive.extract_html("Sorry, I can't.")
    assert buildlive.qr("http://192.168.1.5:8777/x/", site).exists()


def test_build_it_live_asks_before_sharing_on_the_wifi(base, deny, tmp_path):
    live = buildlive.Live()
    with pytest.raises(buildlive.LiveError, match="Not shared"):
        live.share(tmp_path)
    assert live.server is None


def test_upscale_makes_a_bigger_copy_and_keeps_the_original(tmp_path):
    from PIL import Image

    source = tmp_path / "pic.png"
    Image.new("RGB", (100, 60), "red").save(source)
    bigger = images.upscale(source, 4)
    with Image.open(bigger) as im:
        assert im.size == (400, 240)
    assert source.exists() and images.upscale(source, 2).name == "pic_x2.png"


def test_nudges_are_few_spaced_and_never_at_night(base, monkeypatch):
    monkeypatch.setenv("JARVIS_NUDGES", "on")
    day = datetime(2026, 11, 18, 10, 0)
    tasks = [{"text": "Send the report", "due": day.timestamp() - 3600, "done": False}]
    first = nudges.pick(day, tasks, 0)
    assert first is not None and first.title == "Overdue"
    assert nudges.pick(day.replace(hour=11), tasks, 0) is None             # two hours apart
    assert nudges.pick(day.replace(hour=23), tasks, 0) is None             # quiet at night
    assert nudges.pick(day.replace(hour=13), tasks, 0, focusing=True) is None
    later = nudges.pick(day.replace(hour=16), tasks, 0)
    assert later is not None and later.key != first.key                    # never the same twice a day
    monkeypatch.setenv("JARVIS_NUDGES", "off")
    assert nudges.pick(day.replace(hour=19), tasks, 0) is None


def test_the_new_addons_load_and_their_commands_work(base, monkeypatch):
    from jarvis import kit
    from jarvis.addons import AddonManager

    manager = AddonManager(None)
    manager.load_all()
    names = {key for entry in manager.loaded for key in entry.commands}
    assert {"hn", "apod", "launches", "standup"} <= names, manager.errors
    stories = {"topstories.json": [1, 2], "item/1.json": {"id": 1, "title": "Rust 2.0", "score": 99, "url": "https://a"},
               "item/2.json": {"id": 2, "title": "New GPU", "score": 50}}
    monkeypatch.setattr(kit, "get_json", lambda url, *a, **k: stories[url.split("/v0/")[1]])
    hn = next(e for e in manager.loaded if "hn" in e.commands)
    text = hn.commands["hn"].handler(manager.ctx, "")
    assert "Rust 2.0" in text and "news.ycombinator.com/item?id=2" in text


def test_every_bounty_command_is_registered():
    from jarvis.registry import TOOLS

    for name in ("knowledge", "focus", "buildlive", "upscale", "nudges"):
        assert name in TOOLS, name
