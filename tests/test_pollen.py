"""12.6.2, "The Pollen Update": Pollinations as the last resort for everything.

Nothing here reaches Pollinations; the key is a fake and the calls are stubbed.
"""

from __future__ import annotations

from jarvis import providers


def _keyed(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk_" + "NotARealKey0123456789")


def test_pollinations_is_the_keyed_openai_compatible_api():
    p = providers.POLLINATIONS
    assert p.key_env == "POLLINATIONS_API_KEY"
    assert p.base_url == "https://gen.pollinations.ai/v1"
    assert p.transport == "sdk"
    assert p.stt_model and p.vision and p.free


def test_last_in_every_chain(monkeypatch):
    _keyed(monkeypatch)
    assert providers.AUTO_CHAT_PROVIDERS[-1] is providers.POLLINATIONS
    assert providers.STT_PROVIDERS[-1] is providers.POLLINATIONS
    chain = providers.chat_chain()
    assert chain[-1] is providers.POLLINATIONS
    stt = providers.stt_chain()
    assert stt and stt[-1] is providers.POLLINATIONS


def test_skipped_without_a_key(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "")
    assert providers.POLLINATIONS not in providers.chat_chain()
    assert providers.POLLINATIONS not in providers.stt_chain()


def test_agent_falls_back_to_it_last(monkeypatch):
    """The coding agent's own model first, the chain after, Pollinations at the end."""
    from jarvis.brain import Brain

    _keyed(monkeypatch)
    brain = Brain.__new__(Brain)
    brain._dead, brain._slow_targets, brain._model_override = set(), set(), None
    from jarvis import modes

    brain.mode = modes.DEFAULT
    attempts = brain._attempts(providers.chat_chain(), extra=modes.agent_targets())
    assert attempts[-1][0] is providers.POLLINATIONS
    assert attempts[-1][1] == "openai"


def test_voice_uses_pollinations_after_openai(monkeypatch):
    from jarvis import voice as voice_mod

    v = voice_mod.Voice.__new__(voice_mod.Voice)
    import threading

    v._stop_flag = threading.Event()
    v._openai_tts_ok = True
    v._pollinations_tts_ok = True
    order = []
    v._speak_neural = lambda text, language=None: order.append("neural") or False
    v._speak_openai = lambda text: order.append("openai") or False
    v._speak_pollinations = lambda text: order.append("pollinations") or True
    v._speak_offline = lambda text: order.append("offline")
    v._speak_worker("hello")
    assert order == ["neural", "openai", "pollinations"]

    order.clear()
    v._speak_pollinations = lambda text: order.append("pollinations") or False
    v._speak_worker("hello")
    assert order == ["neural", "openai", "pollinations", "offline"]


def test_pollinations_voice_sends_no_instructions(monkeypatch):
    """tts-1 takes no `instructions`; sending them could get the request refused."""
    from jarvis import voice as voice_mod

    seen = {}

    class Streaming:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"\x00\x00" * 10

    class Client:
        class audio:
            class speech:
                class with_streaming_response:
                    create = Streaming

    monkeypatch.setattr(providers, "get_client", lambda provider: Client)
    v = voice_mod.Voice.__new__(voice_mod.Voice)
    import threading

    v._stop_flag = threading.Event()
    v._stop_flag.set()  # nothing is played
    v._pollinations_tts_ok = True
    assert v._speak_pollinations("Good evening.") is True
    assert seen["model"] == "tts-1" and seen["response_format"] == "pcm"
    assert "instructions" not in seen
