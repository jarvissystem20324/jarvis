"""Commands without the slash (10.5.2). The model is a stand-in throughout."""

from __future__ import annotations

import json

import pytest

from jarvis import autocmd, registry


@pytest.fixture
def on(monkeypatch):
    import jarvis.assistant  # noqa: F401  (registers every command)

    monkeypatch.setenv(autocmd.SETTING, "on")
    asked = []

    def answer(reply: dict | None):
        def fake(prompt: str) -> str:
            asked.append(prompt)
            return json.dumps(reply) if reply is not None else ""
        monkeypatch.setattr(autocmd, "_ask_model", fake)
        return asked

    return answer


@pytest.mark.parametrize("text", [
    "what is the capital of France", "how do I make pasta?", "tell me a joke", "make it shorter",
    "translate this", "neden gökyüzü mavi", "/kdv 1000",
])
def test_questions_chat_and_the_last_answer_stay_in_the_chat(on, text):
    asked = on({"command": "kdv", "args": "1"})
    assert autocmd.route(text) is None and asked == []


def test_a_message_holding_a_secret_is_never_sent_to_the_router(on):
    from conftest import FAKE_OPENAI_KEY

    asked = on({"command": "b64", "args": "x"})
    assert autocmd.route(f"make a base64 of {FAKE_OPENAI_KEY}") is None and asked == []


def test_a_command_name_that_is_no_ordinary_word_runs_without_the_model(on, monkeypatch):
    asked = on(None)
    monkeypatch.setattr(autocmd, "_is_word", lambda word: False)
    assert autocmd.route("tripbudget rome 5 days") == "/tripbudget rome 5 days"
    assert asked == []


def test_the_model_chooses_from_a_shortlist(on, monkeypatch):
    asked = on({"command": "tripbudget", "args": "Rome | 5 | 1 | 20000 TL"})
    monkeypatch.setattr(autocmd, "_is_word", lambda word: True)
    assert autocmd.route("plan a 5 day trip budget for Rome on 20000 TL") == "/tripbudget Rome | 5 | 1 | 20000 TL"
    assert "tripbudget" in asked[0]


@pytest.mark.parametrize("reply", [
    {"command": None}, {"command": "shred", "args": "C:/taxes"}, {"command": "nosuchthing"}, "not json at all",
])
def test_none_a_dangerous_command_or_nonsense_means_the_chat(on, monkeypatch, reply):
    if isinstance(reply, str):
        monkeypatch.setattr(autocmd, "_ask_model", lambda prompt: reply)
    else:
        on(reply)
    assert autocmd.route("make a budget for my trip to Rome") is None


def test_nothing_that_deletes_sends_or_controls_a_device_can_be_chosen():
    import jarvis.assistant  # noqa: F401

    choosable = {t.name for t in registry.TOOLS.values() if autocmd.allowed(t)}
    assert not choosable & {"shred", "whatsapp", "cleanup", "winget", "plugs", "cast", "print", "firewall"}
    assert not {t.name for t in registry.TOOLS.values() if t.group in {"Automation", "Phone"}} & choosable
    assert {"tripbudget", "poster", "worksheet", "kdv", "bmi"} <= choosable


def test_turkish_puts_the_verb_last(on, monkeypatch):
    asked = on({"command": "studyplan", "args": "fizik sınavı"})
    monkeypatch.setattr(autocmd, "_is_word", lambda word: True)
    assert autocmd.route("fizik sınavı için çalışma planı hazırla") == "/studyplan fizik sınavı"
    assert asked


def test_it_can_be_switched_off(on, monkeypatch):
    asked = on({"command": "poster", "args": "x"})
    monkeypatch.setenv(autocmd.SETTING, "off")
    assert autocmd.route("make a poster for the summer sale") is None and asked == []


def test_the_reply_shows_which_command_ran(base, on, monkeypatch):
    from jarvis.assistant import Jarvis

    on({"command": "kdv", "args": "1000 20"})
    monkeypatch.setattr(autocmd, "_is_word", lambda word: True)
    jarvis = Jarvis(voice_enabled=False)
    monkeypatch.setattr(jarvis.brain, "chat", lambda *a, **k: pytest.fail("went to the chat"))
    reply = jarvis.process("calculate the kdv on 1000 lira at 20 percent").text
    assert reply.startswith("↪ /kdv 1000 20\n\n")
    assert reply.split("\n\n", 1)[1] == jarvis.process("/kdv 1000 20").text      # the command really ran
