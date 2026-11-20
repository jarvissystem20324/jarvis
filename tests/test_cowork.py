"""13.4.2: Cowork jobs, the smart router, the screen's safety rules, the
preview channel, company documents, and the learning commands.

No test reaches a real AI, mailbox, web page or the real mouse: every one of
those is a stand-in.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import cowork, router, screen, security


class FakeBrain:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.min_tokens = 0

    def ask_once(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.answer(prompt, kwargs)


def manager_with(answer):
    m = cowork.Manager()
    brain = FakeBrain(answer)
    m.brain_factory = lambda: brain
    return m, brain


def finish(job, seconds=10.0):
    end = time.time() + seconds
    while job.running and time.time() < end:
        time.sleep(0.02)
    return job


# --- the smart router ----------------------------------------------------------------------

@pytest.mark.parametrize("text, tier", [
    ("hi", "light"),
    ("thanks!", "light"),
    ("merhaba", "light"),
    ("what's the capital of Australia?", "light"),
    ("def add(a, b): return a - b  — why is this wrong?", "heavy"),
    ("Traceback (most recent call last): ValueError", "heavy"),
    ("explain why the sky is blue in detail", "heavy"),
    ("solve 3x^2 + 2 = 14", "heavy"),
    ("bu kodu adım adım açıkla", "heavy"),
    ("x" * 800, "heavy"),
    ("I am going to Ankara next week for three days with two friends, what should we definitely see there?",
     "standard"),
])
def test_router_sorts_messages_into_tiers(text, tier):
    assert router.classify(text) == tier


def test_router_tier_targets():
    from jarvis import modes

    # 14.1.1: Qwen is Low's model only; Mid's short messages stay on Mercury.
    assert router.targets("light") == modes.targets_for(modes.MID)
    assert all("qwen" not in model for _, model in router.targets("light") + router.targets("heavy"))
    assert router.targets("standard") == ()
    assert router.targets("heavy")[0] == ("groq", "openai/gpt-oss-120b")


def test_brain_routes_in_mid_and_records_the_saving(base, monkeypatch):
    from jarvis import modes
    from jarvis.brain import Brain

    monkeypatch.setenv("JARVIS_ROUTER", "on")
    brain = Brain()
    seen = []

    def chain(messages, on_chunk=None, targets=(), **kwargs):
        seen.append(targets)
        return "Hello!", None

    brain._chat_over_chain = chain
    assert brain.chat("hi") == "Hello!"
    assert seen[-1] == modes.targets_for(modes.MID) and brain.last_route == "light"
    brain.chat("Traceback (most recent call last): KeyError 'x' in my python script")
    assert seen[-1][0] == ("groq", "openai/gpt-oss-120b") and brain.last_route == "heavy"
    data = router.stats()
    assert data["light"]["count"] == 1 and data["heavy"]["count"] == 1
    text = router.readout()
    assert "2 message(s) routed" in text and "saved" in text and "$" in text

    # Another mode is a choice the user made: no routing.
    brain.set_mode("high")
    brain.chat("hi")
    assert seen[-1] == () and brain.last_route == ""


def test_router_off_does_not_route(base, monkeypatch):
    from jarvis.brain import Brain

    monkeypatch.setenv("JARVIS_ROUTER", "off")
    brain = Brain()
    seen = []
    brain._chat_over_chain = lambda messages, on_chunk=None, targets=(), **kw: (seen.append(targets), ("ok", None))[1]
    brain.chat("hi")
    assert seen == [()] and brain.last_route == ""


def test_a_named_vision_model_is_tried_even_if_the_chat_model_cannot_see(monkeypatch):
    from jarvis import providers
    from jarvis.brain import Brain

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-" + "x" * 40)
    brain = Brain()
    vision = providers.NVIDIA.vision_model
    attempts = brain._attempts([], vision=True, extra=(("nvidia", vision),))
    assert attempts and attempts[0][0] is providers.NVIDIA and attempts[0][1] == vision


# --- the screen's rules ------------------------------------------------------------------

@pytest.mark.parametrize("x, y, expect", [
    (0.5, 0.25, (500, 200)),          # Nemotron's 0-1 grid
    (500, 250, (500, 200)),           # Gemini's 0-1000 grid
    (1500, 700, (999, 700)),          # pixels, kept on screen
    (0, 0, (0, 0)),
])
def test_positions_on_any_grid_become_pixels(x, y, expect):
    assert screen.to_pixels(x, y, 1000, 800) == expect


@pytest.mark.parametrize("label, commit", [
    ("Submit", True), ("Send message", True), ("Pay now", True), ("Gönder", True), ("Satın al", True),
    ("Sign in", True), ("Email address", False), ("First name", False), ("Telefon", False),
])
def test_commit_buttons_are_recognised(label, commit):
    assert screen.is_commit(label) is commit


class FakeInput:
    def __init__(self, cursor=(500, 500), size=(2000, 1600)):
        self.at, self.size = cursor, size
        self.clicks, self.typed, self.scrolled, self.selected = [], [], [], 0

    def cursor(self):
        return self.at

    def screen_size(self):
        return self.size

    def click(self, x, y):
        self.clicks.append((x, y))

    def select_all(self):
        self.selected += 1

    def type(self, text):
        self.typed.append(text)

    def scroll(self, clicks):
        self.scrolled.append(clicks)


def test_hands_need_permission_refuse_commits_and_stop_in_the_corner(monkeypatch):
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    fake = FakeInput()
    hands = screen.Hands(backend=fake)
    with pytest.raises(screen.ScreenError):
        hands.click(10, 10, "Email")                       # not allowed yet
    hands.allowed = True
    hands.click(100, 50, "Email", space=(1000, 800))       # screenshot pixels → cursor space
    assert fake.clicks == [(200, 100)]
    hands.type_text("ada@example.com", "Email")
    assert fake.typed == ["ada@example.com"] and fake.selected == 1
    with pytest.raises(screen.ScreenError, match="never presses"):
        hands.click(1, 1, "Submit")
    fake.at = (0, 0)
    with pytest.raises(screen.Stopped):
        hands.click(100, 100, "Name")
    assert hands.allowed is False


def test_utf16_units_cover_turkish_and_emoji():
    assert screen._utf16_units("ş") == [0x015F]
    assert len(screen._utf16_units("😀")) == 2


# --- understanding a job ---------------------------------------------------------------------

def test_jobs_are_sorted_by_what_they_ask(tmp_path):
    folder = tmp_path / "Offers"
    folder.mkdir()
    assert cowork.detect_kind(f"compare the PDFs in {folder} and make a table") == "folder"
    assert cowork.find_folder(f"compare the PDFs in {folder} and make a table") == folder
    assert cowork.detect_kind("sort my inbox and draft replies") == "inbox"
    assert cowork.detect_kind("gelen kutumu düzenle") == "inbox"
    assert cowork.detect_kind("fill https://forms.example.com/apply from my CV") == "form"
    assert cowork.detect_kind("research the best student laptops under 30000 TL") == "research"
    assert cowork.detect_kind("write a 5-day study plan for my physics exam") == "general"
    assert cowork.find_url("fill https://ex.com/a?b=1, please") == "https://ex.com/a?b=1"


def test_mailto_opens_a_draft_without_sending():
    url = cowork.mailto({"to": "ali@example.com", "subject": "Re: Hi & bye", "body": "Merhaba\nGörüşürüz"})
    assert url.startswith("mailto:ali@example.com?subject=Re%3A%20Hi%20%26%20bye&body=")
    assert "%0A" in url


# --- running jobs -----------------------------------------------------------------------------

def test_folder_job_builds_a_spreadsheet_and_report_and_undo_removes_them(base, allow, tmp_path):
    from openpyxl import load_workbook

    folder = tmp_path / "Offers"
    folder.mkdir()
    (folder / "acme.txt").write_text("Offer from Acme. Price: 100 TL. Delivery in 3 days.", encoding="utf-8")
    (folder / "beta.md").write_text("Beta Ltd offer. Price 80 TL, delivery 7 days.", encoding="utf-8")

    def answer(prompt, kwargs):
        if "Decide how to compare" in prompt:
            assert kwargs.get("targets") == cowork.PLANNER
            return '{"title": "Supplier offers", "columns": ["Supplier", "Price"]}'
        if "fill in these fields" in prompt:
            return '{"Supplier": "Acme", "Price": "100 TL"}' if "Acme" in prompt else \
                '{"Supplier": "Beta", "Price": "80 TL"}'
        if "one-page report" in prompt:
            return "# Supplier offers\n\n## Summary\nBeta is cheaper; Acme is faster."
        raise AssertionError(prompt[:80])

    m, _brain = manager_with(answer)
    job = m.start(f"compare the offers in {folder} and make a table", wait=True)
    assert job.status == "done", job.error
    assert [s.status for s in job.steps] == ["done"] * 4 and job.progress == 1.0
    assert any(r.capability is security.READ_FILE for r in allow)
    sheet = next(Path(p) for p in job.outputs if p.endswith(".xlsx"))
    rows = list(load_workbook(sheet).active.iter_rows(values_only=True))
    assert rows[0] == ("File", "Supplier", "Price")
    assert ("acme.txt", "Acme", "100 TL") in rows and ("beta.md", "Beta", "80 TL") in rows
    assert any(p.endswith(".docx") for p in job.outputs)
    assert "2 document(s)" in job.result

    # The job history survives a restart.
    again = cowork.Manager()
    again.load()
    assert again.get(job.id).status == "done"

    made = [Path(p) for p in job.outputs]
    assert "Removed" in m.undo(job.id)
    assert not any(p.exists() for p in made)


def test_a_job_asks_first_and_stops_when_refused(base, deny, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    m, brain = manager_with(lambda p, k: "{}")
    job = m.start(f"compare the files in {tmp_path}", kind="folder", wait=True)
    assert job.status == "failed" and "said no" in job.error
    assert brain.calls == []          # nothing was read or sent


def test_stop_works_between_steps(base, allow):
    gate = threading.Event()

    def answer(prompt, kwargs):
        if "Plan this job" in prompt:
            return json.dumps({"title": "Poem", "steps": [{"title": "Draft", "do": "draft"},
                                                          {"title": "Polish", "do": "polish"}]})
        gate.wait(5)
        return "lines"

    m, _ = manager_with(answer)
    job = m.start("write me a poem about rain", kind="general")
    for _ in range(200):
        if job.steps and job.steps[0].status == "running":
            break
        time.sleep(0.01)
    assert "Stopping" in m.stop(job.id)
    gate.set()
    finish(job)
    assert job.status == "stopped" and job.steps[1].status != "done"


def test_inbox_job_sorts_and_drafts_but_never_sends(base, allow, monkeypatch):
    from jarvis import social

    monkeypatch.setattr(social, "MAIL", SimpleNamespace(load=lambda: {"user": "me@example.com", "password": "x",
                                                                       "host": "imap.example.com"}))
    mails = [{"from": "Ali <ali@example.com>", "subject": "Project meeting", "date": "", "unread": True,
              "body": "Can we meet on Friday?"},
             {"from": "Shop <news@shop.example>", "subject": "50% off", "date": "", "unread": True, "body": "Sale"}]
    monkeypatch.setattr(social, "fetch_mail", lambda account, limit=25, hours=72: mails)

    def answer(prompt, kwargs):
        return json.dumps([{"i": 0, "category": "reply", "priority": 1, "summary": "wants to meet Friday",
                            "reply": "Friday works for me."},
                           {"i": 1, "category": "newsletter", "priority": 3, "summary": "a sale", "reply": ""}])

    m, _ = manager_with(answer)
    job = m.start("sort my inbox and draft replies", wait=True)
    assert job.status == "done", job.error
    assert any(r.capability is security.READ_MAIL for r in allow)
    drafts = job.extra["drafts"]
    assert drafts == [{"to": "ali@example.com", "subject": "Re: Project meeting", "body": "Friday works for me.",
                       "from": "Ali <ali@example.com>"}]
    assert "nothing was sent" in job.result


def test_research_job_cites_its_sources(base, allow, monkeypatch):
    from jarvis import websearch

    monkeypatch.setattr(websearch, "search", lambda q, limit=5: [
        websearch.Result("Laptop guide", "https://a.example/guide", "s"),
        websearch.Result("Prices 2026", "https://b.example/prices", "s")])
    monkeypatch.setattr(websearch, "fetch", lambda url, deep=True: ("Page", "Useful facts about laptops. " * 20))

    def answer(prompt, kwargs):
        if "Research request" in prompt:
            return '{"title": "Student laptops", "queries": ["student laptop 2026", "laptop prices TL"]}'
        assert "[1]" in prompt and "untrusted" in prompt
        return "# Student laptops\n\n## Summary\nA mid-range laptop fits [1][2].\n\n## Bottom line\nBuy one."

    m, _ = manager_with(answer)
    job = m.start("research the best student laptops under 30000 TL", wait=True)
    assert job.status == "done", job.error
    assert "A mid-range laptop fits" in job.result and "2 source(s)" in job.result
    doc = next(p for p in job.outputs if p.endswith(".docx"))
    assert Path(doc).exists()


def test_form_job_fills_text_fields_and_never_submits(base, allow, monkeypatch):
    from PIL import Image

    import webbrowser

    cowork.PROFILE.save({"email": "ada@example.com", "full name": "Ada Yılmaz", "password": "s3cret-pw-77"})
    fake = FakeInput()
    real_hands = screen.Hands
    monkeypatch.setattr(screen, "Hands", lambda stop_event=None: real_hands(stop_event, backend=fake))
    monkeypatch.setattr(screen, "screenshot", lambda: Image.new("RGB", (1000, 800), "white"))
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(cowork.Context, "wait", lambda self, seconds: None)

    def answer(prompt, kwargs):
        assert kwargs.get("image_b64") and kwargs.get("targets")[0][0] == "nvidia"
        assert "s3cret-pw-77" not in prompt          # the password never reaches the model
        return json.dumps({"fields": [
            {"label": "Email", "x": 0.5, "y": 0.25, "kind": "text", "value": "ada@example.com"},
            {"label": "Full name", "x": 0.5, "y": 0.4, "kind": "text", "value": "Ada Yılmaz"},
            {"label": "Country", "x": 0.5, "y": 0.5, "kind": "select", "value": "Türkiye"},
            {"label": "Phone", "x": 0.5, "y": 0.6, "kind": "text", "value": ""},
            {"label": "Submit", "x": 0.5, "y": 0.9, "kind": "text", "value": "x"}],
            "more_below": False})

    m, _ = manager_with(answer)
    job = m.start("fill the application form at https://forms.example.com/apply", wait=True)
    assert job.status == "done", job.error
    assert opened == ["https://forms.example.com/apply"]
    assert any(r.capability is security.CONTROL_SCREEN for r in allow)
    assert fake.clicks == [(1000, 400), (1000, 640)]       # scaled from the 1000×800 screenshot
    assert fake.typed == ["ada@example.com", "Ada Yılmaz"]
    assert "Country: Türkiye" in job.result and "Phone" in job.result
    assert "press Submit yourself" in job.result
    assert job.extra["filled"] == ["Email", "Full name"]


def test_form_job_without_details_says_how_to_add_them(base, allow):
    m, _ = manager_with(lambda p, k: "{}")
    job = m.start("fill the form at https://forms.example.com/x", wait=True)
    assert job.status == "failed" and "/profile" in job.error


def test_profile_never_stores_secrets(base):
    from jarvis.ten.cowork10 import CoworkCommands

    me = SimpleNamespace(brain=None)
    assert "never stores" in CoworkCommands.profile_cmd(me, "password = hunter2")
    assert "email" in CoworkCommands.profile_cmd(me, "email = ada@example.com")
    assert cowork.load_profile() == {"email": "ada@example.com"}
    assert "Forgot" in CoworkCommands.profile_cmd(me, "clear")


# --- the preview channel ------------------------------------------------------------------------

def test_preview_channel_offers_the_newer_of_stable_and_preview(monkeypatch):
    from jarvis import updater

    offers = {updater.DEFAULT_UPDATE_URL: updater.UpdateInfo("13.4.2", "https://x/a.exe", "0" * 64, ""),
              updater.PREVIEW_UPDATE_URL: updater.UpdateInfo("13.5.0", "https://x/b.exe", "1" * 64, "")}
    monkeypatch.setattr(updater, "_check_manifest", lambda url=None: offers[url or updater.DEFAULT_UPDATE_URL])
    monkeypatch.setattr(updater, "get_update_url", lambda: updater.DEFAULT_UPDATE_URL)
    monkeypatch.setenv("JARVIS_UPDATE_CHANNEL", "stable")
    assert updater.check_for_update().version == "13.4.2"
    monkeypatch.setenv("JARVIS_UPDATE_CHANNEL", "preview")
    assert updater.check_for_update().version == "13.5.0"

    def no_preview(url=None):
        if url == updater.PREVIEW_UPDATE_URL:
            raise updater.UpdateError("HTTP 404")
        return offers[url or updater.DEFAULT_UPDATE_URL]

    monkeypatch.setattr(updater, "_check_manifest", no_preview)
    assert updater.check_for_update().version == "13.4.2"


# --- company documents --------------------------------------------------------------------------

def test_the_library_reads_spreadsheets_and_decks(tmp_path):
    from openpyxl import Workbook
    from pptx import Presentation

    from jarvis import library

    book = Workbook()
    book.active.append(["Region", "Revenue"])
    book.active.append(["Ankara", 1200])
    book.save(tmp_path / "sales.xlsx")
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Q3 plan"
    slide.placeholders[1].text = "Open the Izmir office"
    deck.save(tmp_path / "plan.pptx")

    assert "Ankara\t1200" in library.document_text(tmp_path / "sales.xlsx")
    assert "Open the Izmir office" in library.document_text(tmp_path / "plan.pptx")
    data = library.build(tmp_path)
    assert data["files"] == 2
    assert library.search(data, "Izmir office")[0].file == "plan.pptx"


# --- learning ------------------------------------------------------------------------------------

def test_language_partner_speaks_the_language_and_keeps_corrections_off_the_voice():
    from jarvis.ten.learn import Learn

    me = SimpleNamespace(brain=SimpleNamespace(instructions=""), voice_enabled=False)
    reply = Learn.partner_cmd(me, "spanish B2 travel")
    assert "Spanish (B2)" in reply and me.speak_language == "es" and me.voice_enabled
    assert "travel" in me.brain.instructions and "✏" in me.brain.instructions
    assert Learn.spoken_part(me, "¡Hola! ¿Qué tal?\n✏ yo es → yo soy") == "¡Hola! ¿Qué tal?"
    assert "don't have a voice" in Learn.partner_cmd(me, "klingon")
    Learn.partner_cmd(me, "off")
    assert me.speak_language is None and me.brain.instructions == ""
    assert Learn.spoken_part(me, "a ✏ b") == "a ✏ b"


def test_coding_tutor_explains_errors_and_checks_the_exercise():
    from jarvis.ten.learn import Learn

    asked = []
    me = SimpleNamespace(brain=SimpleNamespace(ask_once=lambda p: asked.append(p) or
                                               "It means x is undefined.\n🏋 Exercises\n1. Print 1 to 5."))
    assert "No exercise yet" in Learn.codetutor_cmd(me, "check print(1)")
    reply = Learn.codetutor_cmd(me, "NameError: name 'x' is not defined")
    assert "Explain this error" in asked[-1] and "/codetutor check" in reply
    Learn.codetutor_cmd(me, "check for i in range(1, 6): print(i)")
    assert "Print 1 to 5" in asked[-1]


def test_meeting_stop_writes_notes_and_puts_actions_on_today(base, monkeypatch):
    from jarvis.ten import work

    class Rec:
        running, errors = True, []

        def stop(self):
            self.running = False
            return "Ali will send the budget by Friday. We agreed to launch in May."

    class Me(work.Work):
        def __init__(self):
            self.rec = Rec()
            self.brain = FakeBrain(lambda p, k: json.dumps({
                "title": "Launch", "summary": ["Launch in May"], "decisions": ["Launch in May"],
                "actions": [{"what": "Send the budget", "who": "Ali", "when": ""}], "open_questions": []}))

        def _recorder(self):
            return self.rec

        def record(self, args):
            return "🔴 Recording. /record stop writes the notes · /record status · /record cancel"

    me = Me()
    assert "/meeting stop" in me.meeting("start")
    text = me.meeting("stop")
    assert "Send the budget" in text and "✅ Added 1 action item(s) to your Today" in text
    assert any(t.get("text", t.get("title", "")) == "Send the budget" or "Send the budget" in json.dumps(t)
               for t in work.load_tasks())


def test_the_white_theme_is_readable():
    from jarvis.design import model
    from ui import theme

    white = theme.get("white")
    assert theme.names()["white"] == "White" and white["appearance"] == "light"
    assert white["text"] == white["accent"] == "#000000"      # full black on white
    assert model.contrast(white["text"], white["bg"]) >= 7
    assert model.contrast(white["text"], white["panel"]) >= 7
    assert model.contrast(white["muted"], white["bg"]) >= 4.5
    assert model.contrast(white["accent"], white["bg"]) >= 4.5
    assert model.contrast(white["text"], white["accent_dim"]) >= 4.5     # text on buttons
    # A custom accent keeps the white chip on the Chat / Code switch.
    assert theme.with_accent(white, "#e11d48")["pill"] == "#ffffff"


def test_every_new_command_is_registered():
    from jarvis.registry import TOOLS

    for name in ("cowork", "profile", "router", "askdocs", "codetutor", "partner", "uni", "career",
                 "internshipcv", "meeting"):
        assert name in TOOLS, name
