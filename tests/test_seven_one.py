"""7.1: quiz and flashcards, YouTube, lecture notes, spending, speed test, power.

No network, no microphone and no model: captions, Cloudflare, the mic and
the AI are stand-ins. Power actions run under JARVIS_POWER_DRYRUN (set for
the whole run in conftest), so they are logged, never carried out.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime

import pytest

from jarvis import addons, intents, power, quiz, recorder, reminders, spending, speedtest, youtube

QUESTIONS = json.dumps([
    {"q": "What do plants make in photosynthesis?", "options": ["Glucose", "Salt", "Iron", "Plastic"],
     "answer": 0, "why": "Light energy turns CO2 and water into glucose."},
    {"q": "Which gas do plants take in?", "options": ["Oxygen", "Carbon dioxide", "Helium", "Neon"],
     "answer": 1, "why": "CO2 is fixed in the Calvin cycle."},
])


@pytest.fixture
def jarvis(base, allow, monkeypatch):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    monkeypatch.setattr(j.voice, "speak", lambda *a, **k: None)
    monkeypatch.setattr(j, "_write_setting", lambda name, value: monkeypatch.setenv(name, value))
    return j


# --- routing -------------------------------------------------------------------------

@pytest.mark.parametrize("said,command", [
    ("quiz me on photosynthesis", "/quiz photosynthesis"),
    ("make 30 flashcards for spanish verbs", "/flashcards 30 spanish verbs"),
    ("summarize this video https://www.youtube.com/watch?v=dQw4w9WgXcQ", "/yt https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("record this lecture", "/record start"),
    ("stop recording", "/record stop"),
    ("I spent 45 on lunch", "/spent 45 on lunch"),
    ("how much did I spend this week", "/spent this week"),
    ("how fast is my internet", "/speedtest"),
    ("shut down the pc in 30 minutes", "/power shutdown in 30 minutes"),
    ("restart my computer", "/power restart"),
    ("put my laptop to sleep", "/power sleep"),
    ("lock my pc", "/power lock"),
    ("cancel shutdown", "/power cancel"),
])
def test_plain_words_route(said, command):
    assert intents.route(said)[0] == command


@pytest.mark.parametrize("said", ["I spent 3 hours debugging", "lock", "shut down the server",
                                  "restart the loop", "record a macro"])
def test_things_that_are_not_these_commands(said):
    routed = intents.route(said)
    assert routed is None or not routed[0].startswith(("/spent", "/power", "/record"))


def test_new_commands_cannot_be_taken_by_addons():
    for name in ("quiz", "flashcards", "yt", "record", "spent", "speedtest", "power"):
        assert name in addons.RESERVED_COMMANDS


# --- quiz and flashcards --------------------------------------------------------------

def test_questions_parse_from_a_fenced_reply():
    got = quiz.questions_from(f"Here you go:\n```json\n{QUESTIONS}\n```")
    assert len(got) == 2 and got[1]["answer"] == 1


def test_broken_questions_are_dropped():
    bad = json.dumps([{"q": "x", "options": ["a", "b"], "answer": 0}, {"q": "y", "options": list("abcd"), "answer": 7}])
    with pytest.raises(quiz.QuizError):
        quiz.questions_from(bad)


@pytest.mark.parametrize("reply,index", [("a", 0), ("B)", 1), ("3", 2), ("answer: d", 3), ("Carbon dioxide", 1), ("carbon", 1)])
def test_answers_are_understood(reply, index):
    q = quiz.Quiz("t", quiz.questions_from(QUESTIONS), index=1)
    assert q.choice(reply) == index


def test_a_quiz_runs_in_the_chat(jarvis, monkeypatch):
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **k: QUESTIONS)
    monkeypatch.setattr(jarvis.brain, "chat", lambda *a, **k: pytest.fail("an answer went to the AI"))
    first = jarvis.process("quiz me on photosynthesis").text
    assert "Q1/2" in first and "A) Glucose" in first
    assert "Answer with A, B, C or D" in jarvis.process("maybe").text
    second = jarvis.process("a").text
    assert "✅ Correct" in second and "Q2/2" in second
    assert "Study, video and money" in jarvis.process("/help").text   # commands still work mid-quiz
    assert jarvis._quiz is not None
    last = jarvis.process("a").text
    assert "❌ It's B) Carbon dioxide" in last and "Score: 1/2" in last
    assert jarvis._quiz is None
    again = jarvis.process("/quiz again").text
    assert "Which gas" in again and "Q1/1" in again


def test_stopping_a_quiz_gives_the_score(jarvis, monkeypatch):
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **k: QUESTIONS)
    jarvis.process("/quiz 5 the water cycle")
    assert "Score: 0/0" in jarvis.process("stop").text
    assert jarvis._quiz is None


def test_quiz_from_a_file_uses_its_text(jarvis, monkeypatch, base):
    notes = base / "notes.txt"
    notes.write_text("Mitochondria are the powerhouse of the cell.", encoding="utf-8")
    sent = {}
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **k: (sent.setdefault("p", prompt), QUESTIONS)[1])
    reply = jarvis.process(f"/quiz {notes}").text
    assert "Quiz on notes.txt" in reply
    assert "powerhouse" in sent["p"] and "<<untrusted" in sent["p"]


def test_flashcards_are_saved_for_anki(jarvis, monkeypatch):
    cards = json.dumps([{"front": "hola", "back": "hello"}, {"front": "gracias", "back": "thank you"}])
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **k: cards)
    reply = jarvis.process("/flashcards spanish basics").text
    path = reply.split("\n\n")[1].splitlines()[0].strip()
    assert path.endswith(".csv")
    assert open(path, encoding="utf-8-sig").read().splitlines() == ["hola,hello", "gracias,thank you"]


# --- YouTube ------------------------------------------------------------------------

@pytest.mark.parametrize("link", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ?t=42",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ", "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
])
def test_video_ids(link):
    assert youtube.video_id(link) == "dQw4w9WgXcQ"


def test_captions_get_timestamps():
    pieces = [{"text": "hello", "start": 0}, {"text": "[Music]", "start": 5}, {"text": "world", "start": 12},
              {"text": "later on", "start": 75}]
    assert youtube.join(pieces) == "[0:00] hello world\n[1:15] later on"


def test_a_video_is_summarised_and_stays_open(jarvis, monkeypatch):
    monkeypatch.setattr(youtube, "transcript", lambda vid: ("en", "[0:00] Today we learn Rust ownership."))
    monkeypatch.setattr(youtube, "title", lambda vid: "Rust in 10 minutes — Some Channel")
    prompts = []
    monkeypatch.setattr(jarvis.brain, "ask_once", lambda prompt, **k: (prompts.append(prompt), "It explains ownership.")[1])
    reply = jarvis.process("summarize this https://youtu.be/dQw4w9WgXcQ").text
    assert "Rust in 10 minutes" in reply and "It explains ownership." in reply
    assert "ownership" in prompts[0] and "<<untrusted" in prompts[0]
    jarvis.process("/yt what is borrowing?")
    assert "what is borrowing?" in prompts[1] and "Rust ownership" in prompts[1]


def test_a_video_without_captions_says_so(jarvis, monkeypatch):
    def fail(vid):
        raise youtube.YouTubeError("Couldn't read the captions: captions are turned off for this video.")

    monkeypatch.setattr(youtube, "transcript", fail)
    assert "captions are turned off" in jarvis.process("/yt https://youtu.be/dQw4w9WgXcQ").text


# --- lecture notes --------------------------------------------------------------------

class FakeStream:
    def __init__(self, blocks):
        self.blocks = blocks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        if self.blocks <= 0:
            time.sleep(0.01)
        self.blocks -= 1
        return b"\x01\x00" * n, False


def test_the_recorder_transcribes_in_pieces(monkeypatch):
    monkeypatch.setattr(recorder, "CHUNK_SECONDS", 1)
    heard = []
    rec = recorder.Recorder(lambda pcm: (heard.append(len(pcm)), f"part {len(heard)}")[1], sample_rate=1000, block=100)
    rec.start(stream_factory=lambda: FakeStream(35))
    deadline = time.time() + 5
    while len(heard) < 3 and time.time() < deadline:
        time.sleep(0.01)
    text = rec.stop(timeout=5)
    assert text.startswith("part 1\n\npart 2\n\npart 3")
    assert heard[0] == 2000          # one second of 16-bit audio per piece
    assert not rec.running


def test_record_stop_writes_the_notes(jarvis, monkeypatch):
    class Rec:
        running, pieces, errors = True, [], []

        def elapsed(self):
            return 1500

        def stop(self, timeout=300):
            self.running = False
            return "Today we covered the causes of the First World War. Essay due Friday."

    jarvis._rec = Rec()
    monkeypatch.setattr(jarvis.brain, "ask_once",
                        lambda prompt, **k: "# WW1 causes\n\n## Summary\nAlliances.\n\n## Action items\n- Essay due Friday")
    reply = jarvis.process("/record stop").text
    assert reply.startswith("# WW1 causes") and "Essay due Friday" in reply and ".docx" in reply
    assert "25m" in reply


# --- spending ------------------------------------------------------------------------

@pytest.mark.parametrize("said,amount,currency,what,category", [
    ("45 lunch", 45, None, "lunch", "food"),
    ("120 tl on groceries", 120, "TRY", "groceries", "groceries"),
    ("$12.50 coffee", 12.5, "USD", "coffee", "food"),
    ("1,250.50 € rent", 1250.5, "EUR", "rent", "bills"),
    ("1.250,50 tl kira", 1250.5, "TRY", "kira", "bills"),
    ("2 coffees 9 dollars", 9, "USD", "2 coffees", "food"),
    ("30 for uber #transport", 30, None, "uber", "transport"),
])
def test_spending_is_parsed(said, amount, currency, what, category):
    entry = spending.parse(said)
    assert (entry["amount"], entry["currency"], entry["what"], entry["category"]) == (amount, currency, what, category)


def test_spending_adds_up_and_undoes(jarvis):
    assert "₺45" in jarvis.process("I spent 45 on lunch").text
    jarvis.process("spent 30 tl on taxi")
    jarvis.process("/spent 10 usd coffee")
    month = jarvis.process("how much did I spend this month").text
    assert "Total: ₺75" in month and "Total: $10" in month and "food" in month
    assert "Removed $10" in jarvis.process("/spent undo").text
    assert len(spending.load()) == 2


def test_the_budget_warns(jarvis):
    jarvis.process("/spent budget 100")
    reply = jarvis.process("/spent 90 groceries").text
    assert "90% of this month's budget" in reply
    assert "Over this month's budget" in jarvis.process("/spent 20 lunch").text


def test_spending_exports_to_excel(jarvis):
    from openpyxl import load_workbook

    jarvis.process("/spent 45 lunch")
    reply = jarvis.process("/spent export").text
    path = reply.splitlines()[-1].strip()
    book = load_workbook(path)
    assert book["Spending"]["B2"].value == 45
    assert book["By month"]["D2"].value == 45


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_spending_is_encrypted_at_rest(jarvis, base):
    jarvis.process("/spent 45 secret lunch")
    raw = (base / "data" / spending.FILE).read_bytes()
    assert b"secret" not in raw


def test_last_month_is_its_own_period():
    start, end, label = spending.period("last month", datetime(2026, 3, 15, 12))
    assert datetime.fromtimestamp(start) == datetime(2026, 2, 1) and datetime.fromtimestamp(end) == datetime(2026, 3, 1)
    assert label == "February 2026"


# --- speed test ----------------------------------------------------------------------

def test_speed_test_reports(jarvis, monkeypatch):
    monkeypatch.setattr(speedtest, "_ping", lambda: (14.2, 2.1))
    monkeypatch.setattr(speedtest, "_download", lambda size: size / 250_000)
    monkeypatch.setattr(speedtest, "_upload", lambda size: size / 500_000)
    monkeypatch.setattr(speedtest, "_where", lambda: "server IST")
    reply = jarvis.process("how fast is my internet").text
    assert "⬇ 100.0 Mbps" in reply and "⬆ 10.0 Mbps" in reply and "ping 14 ms" in reply
    assert "fast" in reply and "server IST" in reply


def test_speed_test_needs_permission(base, deny):
    from jarvis.assistant import Jarvis

    assert "Denied" in Jarvis(voice_enabled=False).process("/speedtest").text


# --- power ---------------------------------------------------------------------------

def test_shutdown_is_scheduled_with_windows(jarvis, allow):
    reply = jarvis.process("shut down the pc in 30 minutes").text
    assert "Shutdown in 30m" in reply
    assert power.dry_log[-1].startswith("shutdown /s /t 1800")
    assert any("shutdown this PC" in r.detail for r in allow)
    assert "Shutdown at" in jarvis.process("/power status").text
    assert "Cancelled the shutdown" in jarvis.process("cancel shutdown").text
    assert power.dry_log[-1] == "shutdown /a"


def test_now_still_gets_a_grace_period(jarvis):
    jarvis.process("restart my computer")
    assert power.dry_log[-1].startswith(f"shutdown /r /t {power.GRACE_SECONDS}")


def test_power_asks_first(base, deny):
    from jarvis.assistant import Jarvis

    assert "Denied" in Jarvis(voice_enabled=False).process("/power shutdown").text
    assert power.dry_log == []


def test_sleep_later_is_on_the_board_and_cancels(jarvis):
    reply = jarvis.process("put my pc to sleep in 20 minutes").text
    assert "sleep" in reply and [r.kind for r in reminders.board.items] == ["sleep"]
    jarvis.process("/power cancel")
    assert reminders.board.items == []


def test_lock(jarvis):
    assert "Locked" in jarvis.process("lock my pc").text
    assert power.dry_log == ["lock"]
