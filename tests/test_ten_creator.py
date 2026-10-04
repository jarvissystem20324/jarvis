"""10.0 creators: threads that fit, real search suggestions, the feed
preview and overlays as files, and what each writing tool asks the AI."""

from __future__ import annotations

import pytest
from PIL import Image

from jarvis import creator, kit


class Brain:
    def __init__(self, reply="ok"):
        self.reply, self.asked = reply, []

    def ask_once(self, prompt, **kw):
        self.asked.append(prompt)
        return self.reply


def test_threads_fit_the_limit_and_are_numbered():
    text = ("This is the first point. " * 12).strip() + "\n\n" + "Second paragraph, short.\n\n" + "x" * 600
    posts = creator.split_thread(text, 280)
    assert all(len(p) <= 280 for p in posts) and len(posts) >= 4
    assert posts[0].endswith(f"1/{len(posts)}") and posts[-1].endswith(f"{len(posts)}/{len(posts)}")
    assert creator.split_thread("1/ Hello there.\n\n2/ And again.", 280) == ["Hello there. 1/2", "And again. 2/2"]
    assert creator.split_thread("One post only.") == ["One post only."]


def test_keyword_ideas_are_real_suggestions_without_repeats(monkeypatch):
    asked = []

    def fake(url, params=None, headers=None, timeout=15):
        asked.append(params["q"])
        return [params["q"], [f"{params['q']} 2026", "kahve demleme", f"{params['q']} 2026"]]

    from jarvis import i18n

    monkeypatch.setattr(kit, "get_json", fake)
    monkeypatch.setattr(i18n, "current", lambda: "tr")
    ideas = creator.keyword_ideas("kahve demleme")
    assert asked[1] == "kahve demleme nasıl"          # JARVIS speaks Turkish → Turkish phrasings
    monkeypatch.setattr(i18n, "current", lambda: "en")
    asked.clear()
    creator.keyword_ideas("coffee")
    assert asked[1] == "how to coffee"
    asked.clear()
    creator.keyword_ideas("çay demleme")              # Turkish letters say it even in English mode
    assert asked[1] == "çay demleme nasıl"
    assert ideas.count("kahve demleme") == 1 and "kahve demleme nasıl 2026" in ideas
    monkeypatch.setattr(kit, "get_json", lambda *a, **k: (_ for _ in ()).throw(kit.KitError("offline")))
    assert creator.youtube_suggestions("x") == []


def test_feed_preview_and_overlays_are_pictures(base, tmp_path):
    thumb = tmp_path / "t.png"
    Image.new("RGB", (1280, 720), "orange").save(thumb)
    out = creator.feed_preview(thumb, "I Tried Every Kebab in Istanbul and Ranked Them All Honestly", "Mustafa",
                               out=tmp_path / "p.png")
    with Image.open(out) as image:
        assert image.size == (1400, 760) and image.getpixel((40 + 360 + 24 + 10, 60)) != (15, 15, 15)
    files = creator.stream_overlays("MyChannel", "#ff4f9a", tmp_path / "ov", socials="@me")
    assert [f.name for f in files] == ["webcam-frame.png", "lower-third.png", "starting-soon.png",
                                       "be-right-back.png", "thanks-for-watching.png"]
    with Image.open(files[1]) as lower:
        assert lower.mode == "RGBA" and lower.getpixel((1800, 100))[3] == 0     # see-through where empty
        assert lower.getpixel((65, 900))[:3] == (255, 79, 154)                   # the accent bar


def test_each_writing_tool_asks_for_the_right_thing(base, monkeypatch):
    from jarvis.ten import creator as commands

    monkeypatch.setattr(creator, "keyword_ideas", lambda topic, lang="": ["kahve demleme yöntemleri"])
    tool = commands.Creator()
    tool.brain = Brain("1. Title — angle")
    assert tool.videoideas_cmd("kahve demleme | TikTok").startswith("💡")
    assert "TikTok" in tool.brain.asked[-1] and "kahve demleme yöntemleri" in tool.brain.asked[-1]
    assert "language of the request" in tool.brain.asked[-1]
    tool.hooks_cmd("living on 100 lira a day")
    assert "10 different opening hooks" in tool.brain.asked[-1]
    tool.hashtags_cmd("street food | TikTok")
    assert "5 hashtags" in tool.brain.asked[-1]
    tool.brain = Brain("Post one is here.\n\nPost two is here.\n\nPost three.")
    reply = tool.thread_cmd("moving to Ankara | X | 3")
    assert "3 posts" in reply and "Post two is here. 2/3" in reply
    seo = tool.seo_cmd("coffee")
    assert "kahve demleme yöntemleri" in seo
    for name in ("videoideas", "script", "hooks", "hashtags", "repurpose", "seo", "thread", "thumbpreview",
                 "overlays"):
        assert "Usage" in getattr(tool, f"{name}_cmd")("")
    assert tool.teleprompter_cmd("").open_page == "creator:teleprompter"


def test_a_script_is_saved_as_word(base, monkeypatch):
    from jarvis import writer
    from jarvis.ten import creator as commands

    saved = []
    monkeypatch.setattr(writer, "save", lambda md, formats: saved.append(formats) or [writer.documents_dir() / "s.docx"])
    tool = commands.Creator()
    tool.brain = Brain("# Why Istanbul has cats\n\n## Hook (0:00)\nLook around.")
    reply = tool.script_cmd("why Istanbul has cats | 6 | story")
    assert reply.startswith("📝 Why Istanbul has cats") and saved == [("docx",)] and "s.docx" in reply
    assert "6-minute story" in tool.brain.asked[0]


def test_repurpose_reads_the_video_itself(base, monkeypatch):
    from jarvis import youtube
    from jarvis.ten import creator as commands

    monkeypatch.setattr(youtube, "transcript", lambda vid: ("en", "[00:00] cats rule the city"))
    monkeypatch.setattr(youtube, "title", lambda vid: "Cats of Istanbul")
    tool = commands.Creator()
    tool.brain = Brain("1. thread …")
    reply = tool.repurpose_cmd("https://youtu.be/dQw4w9WgXcQ")
    assert "Cats of Istanbul" in reply and "cats rule the city" in tool.brain.asked[0]


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_creator_page_and_teleprompter(app):
    app._show_tab("creator")
    app.update()
    page = app.pages["creator"]
    page.start()
    assert "Paste" in page.note.cget("text") and page.window is None
    page.script.insert("1.0", "Hello and welcome back.\n" * 30)
    page.start()
    prompter = page.window
    app.update()
    y0 = prompter.canvas.coords(prompter.text)[1]
    prompter.tick()
    assert prompter.canvas.coords(prompter.text)[1] < y0
    prompter.toggle()
    y1 = prompter.canvas.coords(prompter.text)[1]
    prompter.tick()
    assert prompter.canvas.coords(prompter.text)[1] == y1          # paused
    prompter.faster(2)
    prompter.resize(8)
    assert prompter.speed > 3 and prompter.size == 60
    prompter.close()
