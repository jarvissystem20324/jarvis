"""Brain, modes, history, env migration, the index, git and the addons.

Each test here exists because the thing it checks was broken at some point,
or nearly shipped broken. The comment says which.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from jarvis import envfix, history, index, modes, personality, vcs
from jarvis.brain import Brain, Cancelled, _NeedsMoreRoom


# --- identity and modes ----------------------------------------------------

def test_code_mode_keeps_the_creator():
    """Code mode once answered 'I am Mercury, trained by Inception'."""
    brain = Brain()
    brain.persona_override = personality.CODE_MODE_PROMPT
    assert "Ahmed Zahid Dilmen" in brain.system_prompt()


def test_status_line_is_safe_before_the_first_reply():
    """_last_model was read before it was ever set."""
    brain = Brain()
    assert brain._last_model == ""
    assert "not connected" in brain.active_label()


def test_every_mode_reaches_for_its_own_model():
    """Low, High and Max once all fell to the same model, so switching tiers
    changed only the wording of the instruction."""
    picked = [m.targets[0] for m in modes.ALL]
    assert all(m.targets for m in modes.ALL)
    assert len(picked) == len(set(picked))


def test_low_does_not_use_a_reasoning_model():
    """gpt-oss-20b spent Low's whole 512-token budget reasoning and returned
    nothing at all — every Low answer would have been 'cut short'."""
    assert "gpt-oss" not in modes.LOW.targets[0][1]


def test_hyperdrive_leash_applies_to_the_first_model_only(monkeypatch):
    for mode in modes.ALL:
        for provider, _ in mode.targets:
            monkeypatch.setenv(f"{provider.upper()}_API_KEY", "test")
    brain = Brain()
    brain.set_mode("hyperdrive")
    preferred = [a for a in brain._attempts(brain._chain()) if a[3]]
    assert preferred[0][2] == modes.HYPERDRIVE.first_target_timeout
    assert all(a[2] <= modes.HYPERDRIVE.fallback_timeout for a in preferred[1:])


def test_a_model_that_timed_out_is_skipped_for_the_session(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    brain = Brain()
    brain.set_mode("hyperdrive")
    brain._slow_targets.add(("nvidia", "moonshotai/kimi-k3"))
    models = [a[1] for a in brain._attempts(brain._chain()) if a[3]]
    assert "moonshotai/kimi-k3" not in models


def test_a_mode_can_be_repointed_from_env(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE_HIGH", "groq:openai/gpt-oss-120b")
    assert modes.targets_for(modes.HIGH) == (("groq", "openai/gpt-oss-120b"),)


def test_a_malformed_override_falls_back(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE_HIGH", "no-colon-here")
    assert modes.targets_for(modes.HIGH) == modes.HIGH.targets


def _long_history(n=60):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
            for i in range(n)]


def test_history_is_trimmed_in_aligned_pairs(monkeypatch):
    brain = Brain()
    monkeypatch.setattr(brain, "_chat_over_chain", lambda *a, **k: ("summary", None))
    brain.history = _long_history()
    brain._trim()
    assert len(brain.history) <= 40
    assert brain.history[0]["role"] == "user"


def test_trimmed_turns_are_summarised_not_lost(monkeypatch):
    """Turns past the limit used to vanish, so a long session forgot its
    own beginning."""
    brain = Brain()
    seen = []

    def fake(messages, **kwargs):
        seen.append(messages[0]["content"])
        return "We agreed to use SQLite and name the table 'orders'.", None

    monkeypatch.setattr(brain, "_chat_over_chain", fake)
    brain.history = _long_history()
    brain._trim()
    assert "turn 0" in seen[0]                       # the oldest turns were handed over
    assert "SQLite" in brain.summary
    assert "SQLite" in brain.system_prompt()


def test_summarising_happens_in_batches_not_every_message(monkeypatch):
    brain = Brain()
    calls = []
    monkeypatch.setattr(brain, "_chat_over_chain",
                        lambda *a, **k: (calls.append(1), ("s", None))[1])
    brain.history = _long_history(42)
    brain._trim()
    for i in range(4):          # four more exchanges: still under the limit
        brain.history += [{"role": "user", "content": "q"},
                          {"role": "assistant", "content": "a"}]
        brain._trim()
    assert len(calls) == 1


def test_a_failed_summary_says_so_instead_of_inventing_one(monkeypatch):
    brain = Brain()
    monkeypatch.setattr(brain, "_chat_over_chain", lambda *a, **k: (None, "all down"))
    brain.history = _long_history()
    brain._trim()
    assert "could not be summarised" in brain.summary


def test_clearing_the_conversation_clears_the_summary():
    brain = Brain()
    brain.summary = "old"
    brain.clear_history()
    assert brain.summary == ""


def test_turkish_interface_makes_the_model_answer_in_turkish():
    """4.0 translated the window but never told the model — the edit that
    should have added this instruction silently failed to apply."""
    from jarvis import i18n

    i18n.set_language("tr")
    try:
        assert "Türkçe" in Brain().system_prompt()
    finally:
        i18n.set_language("en")
    assert "Türkçe" not in Brain().system_prompt()


# --- streaming -------------------------------------------------------------

class _Choice:
    def __init__(self, content, finish=None):
        self.delta = type("Delta", (), {"content": content})()
        self.finish_reason = finish


class _Event:
    def __init__(self, content, finish=None):
        self.choices = [_Choice(content, finish)]


def test_a_stream_is_joined_exactly():
    pieces: list = []
    text = Brain._read_stream([_Event("Hel"), _Event("lo"), _Event(None, "stop")],
                              pieces.append)
    assert text == "Hello"
    assert pieces == ["Hel", "lo"]


def test_an_empty_stream_that_ran_out_of_room_asks_for_more():
    """The signal that triggers a retry with a bigger budget."""
    with pytest.raises(_NeedsMoreRoom):
        Brain._read_stream([_Event(None, "length")], lambda _p: None)


def test_stop_escapes_the_stream():
    def refuse(_piece):
        raise Cancelled()

    with pytest.raises(Cancelled):
        Brain._read_stream([_Event("x")], refuse)


def test_stop_never_records_the_unseen_answer(monkeypatch):
    """Pressing Stop once left the discarded reply in history, where it was
    saved and quietly sent as context with the next question."""
    brain = Brain()
    monkeypatch.setattr(brain, "_chat_over_chain", lambda *a, **k: ("answer", None))
    brain.chat("question", should_commit=lambda: False)
    assert brain.history == []
    brain.chat("question", should_commit=lambda: True)
    assert len(brain.history) == 2


# --- conversations ---------------------------------------------------------

def test_conversations_round_trip(base):
    history.save([{"role": "user", "content": "a"},
                  {"role": "assistant", "content": "b"}], mode="max")
    messages, mode, _code = history.load()
    assert len(messages) == 2 and mode == "max"


def test_a_new_conversation_starts_empty_and_the_old_one_survives(base):
    history.save([{"role": "user", "content": "a"},
                  {"role": "assistant", "content": "b"}])
    history.set_current("second")
    assert history.load()[0] == []
    history.set_current("main")
    assert len(history.load()[0]) == 2


def test_a_corrupt_history_degrades_to_empty(base):
    history._path().write_text("{not json", encoding="utf-8")
    assert history.load() == ([], "", False)


def test_junk_turns_are_filtered(base):
    history._path().write_text(json.dumps({"messages": [
        {"role": "user", "content": "keep"},
        {"role": "system", "content": "drop"},
        {"role": "user", "content": 12},
        "not a dict",
    ]}), encoding="utf-8")
    assert history.load()[0] == [{"role": "user", "content": "keep"}]


def test_a_pre_3_3_conversation_is_migrated(base):
    (base / "data" / "conversation.json").write_text(json.dumps({
        "messages": [{"role": "user", "content": "old"},
                     {"role": "assistant", "content": "reply"}],
        "mode": "max",
    }), encoding="utf-8")
    messages, mode, _ = history.load()
    assert len(messages) == 2 and mode == "max"
    assert (base / "data" / "conversation.json").exists()


@pytest.mark.parametrize("name,expected", [
    ('a/b\\c:d*e?"f', "a-b-c-d-e--f"),
    ("   ", "main"),
    ("Project Alpha", "project-alpha"),
])
def test_conversation_names_become_safe_filenames(name, expected):
    assert history._slug(name) == expected


# --- .env migration --------------------------------------------------------

def test_env_migration_never_changes_a_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-keep-me\nJARVIS_MODEL=gpt-4o\n", encoding="utf-8")
    envfix.migrate(env, "5.0")
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-keep-me" in text
    assert "# no longer used since 2.6: JARVIS_MODEL=gpt-4o" in text


def test_env_migration_repairs_a_malformed_update_url(tmp_path):
    """A real install read 'JARVIS_UPDATE_URL=update https://...' and could
    never update again."""
    env = tmp_path / ".env"
    env.write_text("JARVIS_UPDATE_URL=update https://x.test/m.json\n", encoding="utf-8")
    envfix.migrate(env, "5.0")
    assert "JARVIS_UPDATE_URL=https://x.test/m.json" in env.read_text(encoding="utf-8")


def test_env_migration_is_idempotent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
    envfix.migrate(env, "5.0")
    assert envfix.migrate(env, "5.0") == []
    assert len(list(tmp_path.glob(".env.backup-*"))) == 1


def test_env_migration_keeps_equals_signs_inside_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NVIDIA_API_KEY=nvapi-aa==bb\n", encoding="utf-8")
    envfix.migrate(env, "5.0")
    assert "NVIDIA_API_KEY=nvapi-aa==bb" in env.read_text(encoding="utf-8")


# --- codebase index --------------------------------------------------------

def test_the_index_finds_definitions(base, project):
    built = index.build(project)
    names = {s.name for s in built.symbols}
    assert {"add", "multiply", "TestCalc"} <= names


def test_code_outranks_documentation(base, project):
    """'where is the permission prompt shown' once returned eleven markdown
    headings and not a single line of code."""
    (project / "NOTES.md").write_text("# How add works in detail\n", encoding="utf-8")
    built = index.build(project)
    top = index.search(built, "add")[0][0]
    assert not top.file.endswith(".md")


def test_python_comments_are_not_indexed_as_headings(base, project):
    (project / "src" / "calc.py").write_text(
        "# Past this point the log is rotated\ndef add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    built = index.build(project)
    assert not any(s.name.startswith("Past this") for s in built.symbols)


# --- git -------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)

    git("init")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "T")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "-m", "init")
    return root


def _commits(root):
    out = subprocess.run(["git", "-C", str(root), "log", "--oneline"],
                         capture_output=True, text=True).stdout.strip()
    return len(out.splitlines())


def test_git_reads_never_prompt(base, repo, deny):
    assert "init" in vcs.handle(repo, "log")
    assert deny == []


def test_git_refuses_unknown_commands(base, repo, allow):
    assert "not a git command JARVIS runs" in vcs.handle(repo, "rm -rf /")


def test_a_staged_secret_blocks_the_commit(base, repo, allow):
    """This project once staged a .env backup and only caught it by hand."""
    from conftest import FAKE_OPENAI_KEY

    (repo / "config.py").write_text(f"KEY = '{FAKE_OPENAI_KEY}'\n", encoding="utf-8")
    vcs.handle(repo, "add .")
    out = vcs.handle(repo, 'commit -m "add config"')
    assert "Refusing to commit" in out
    assert FAKE_OPENAI_KEY not in out
    assert _commits(repo) == 1


def test_a_denied_commit_commits_nothing(base, repo, deny):
    (repo / "b.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "b.txt"], capture_output=True)
    assert "Denied" in vcs.handle(repo, 'commit -m "b"')
    assert _commits(repo) == 1


# --- addons ----------------------------------------------------------------

@pytest.fixture
def addons(base):
    from jarvis.addons import AddonManager

    manager = AddonManager(None)
    manager.load_all()
    return manager


def test_every_bundled_addon_loads(addons):
    assert not addons.errors
    assert len(addons.loaded) == 8


def test_the_team_is_known(addons):
    assert "Ata Ibrahim" in addons.handle("who", "ata")
    assert "Amade Albayrak" in addons.handle("who", "amade")


def test_database_does_not_mean_ata(addons, base):
    """Word-boundary matching: 'ata' is inside 'data' and 'database'."""
    from jarvis.addons import Context

    people = next(e.addon for e in addons.loaded if e.addon.name == "people")
    ctx = Context(jarvis=None, data_dir=base / "data")
    assert "People mentioned" not in (people.enrich_prompt(ctx, "the database schema") or "")
    assert "Ata Ibrahim" in (people.enrich_prompt(ctx, "ask ata") or "")


def test_an_addon_cannot_take_over_a_security_command():
    from jarvis.addons import RESERVED_COMMANDS

    for command in ("scan", "audit", "privacy", "agent", "git", "run"):
        assert command in RESERVED_COMMANDS


def test_multi_file_proposals_ignore_language_fences():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("cm_core", root / "addons" / "code_mode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    blocks = module.ADDON._blocks(
        "```src/a.py\nA\n```\n```src/b.py\nB\n```\n```python\nIGNORE\n```\n"
    )
    assert [p for p, _ in blocks] == ["src/a.py", "src/b.py"]


# --- updater ---------------------------------------------------------------

def test_the_manifest_is_never_fetched_from_cache():
    """A cached manifest with a stale version silently withholds an update."""
    from jarvis import updater

    assert "?_=" in updater._uncached("https://x.test/update.json")
    assert "&_=" in updater._uncached("https://x.test/update.json?a=1")


# --- opt-in providers ------------------------------------------------------

def test_an_opt_in_provider_is_never_in_the_chain_by_default(monkeypatch):
    """A relay that takes 90s to fail would add 90s to every failover."""
    from jarvis import providers

    monkeypatch.setenv("BLUEMINDS_API_KEY", "test")
    monkeypatch.delenv("JARVIS_EXTRA_PROVIDERS", raising=False)
    assert "blueminds" not in [p.name for p in providers.chat_chain()]
    assert "blueminds" in [p.name for p in providers.keyed_but_idle()]


def test_an_opt_in_provider_joins_the_chain_last_when_promoted(monkeypatch):
    from jarvis import providers

    monkeypatch.setenv("BLUEMINDS_API_KEY", "test")
    monkeypatch.setenv("JARVIS_EXTRA_PROVIDERS", "blueminds")
    chain = [p.name for p in providers.chat_chain()]
    assert chain[-1] == "blueminds"


def test_hyperdrive_never_leaves_nvidia(monkeypatch):
    """Hyperdrive is NVIDIA's heaviest models. Falling through to Gemini or
    Groq would make it a different mode wearing the same name."""
    for env in ("GEMINI", "GROQ", "INCEPTION", "NVIDIA", "OPENAI"):
        monkeypatch.setenv(f"{env}_API_KEY", "test")
    brain = Brain()
    brain.set_mode("hyperdrive")
    assert {a[0].name for a in brain._attempts(brain._chain())} == {"nvidia"}


def test_other_modes_still_fall_back_across_providers(monkeypatch):
    for env in ("GEMINI", "GROQ", "INCEPTION", "NVIDIA", "OPENAI"):
        monkeypatch.setenv(f"{env}_API_KEY", "test")
    brain = Brain()
    brain.set_mode("max")
    assert len({a[0].name for a in brain._attempts(brain._chain())}) > 1


# --- searching every conversation ------------------------------------------

def test_recall_searches_every_conversation(base):
    history.save([{"role": "user", "content": "what port does postgres use"},
                  {"role": "assistant", "content": "5432 by default"}], name="db")
    history.save([{"role": "user", "content": "hello"},
                  {"role": "assistant", "content": "hi"}], name="main")
    hits = history.search_all("5432")
    assert hits and hits[0][0] == "db"


def test_recall_searches_summaries_too(base):
    history.save([{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "y"}],
                 name="old", summary="We chose Flask over Django.")
    assert any(who == "summary" for _c, who, _s in history.search_all("flask"))


def test_the_summary_survives_a_restart(base):
    history.save([{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
                 summary="decided on SQLite")
    assert history.load_summary() == "decided on SQLite"


# --- health ----------------------------------------------------------------

def test_health_lists_each_provider_once(monkeypatch):
    from jarvis import providers

    monkeypatch.setenv("GROQ_API_KEY", "t")
    monkeypatch.setenv("BLUEMINDS_API_KEY", "t")
    monkeypatch.delenv("JARVIS_EXTRA_PROVIDERS", raising=False)
    labels = [label for label, _ in Brain().health()]
    assert len(labels) == len(set(labels))
    assert "Blueminds" not in labels          # opt-in and not promoted


def test_health_reports_a_dead_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "t")
    brain = Brain()
    brain._dead.add("groq")
    assert ("Groq", "dead") in brain.health()


def test_status_callback_never_breaks_a_request():
    brain = Brain()

    def explode(_text):
        raise RuntimeError("UI went away")

    brain.status_callback = explode
    brain._status("anything")          # must not raise


# --- image variations ------------------------------------------------------

def test_vary_without_an_image_explains(base):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    assert "Generate an image first" in j.vary("").text


def test_vary_uses_a_new_seed_each_time(base, monkeypatch):
    from jarvis.assistant import Jarvis

    j = Jarvis(voice_enabled=False)
    seeds = []

    def fake_render(prompt, size, quality, seed=0):
        seeds.append(seed)
        return b"\xff\xd8\xff" + bytes(20)

    monkeypatch.setattr(j.images, "_render", fake_render)
    j._last_image = ("a red cube", "1024x1024", "medium")
    response = j.vary("3")
    assert len(response.image_paths) == 3
    assert len(set(seeds)) == 3


def test_openrouter_is_free_and_comes_before_paid():
    from jarvis import providers

    names = [p.name for p in providers.AUTO_CHAT_PROVIDERS]
    assert names.index("openrouter") < names.index("openai")
    assert providers.BY_NAME["openrouter"].chat_model == "openrouter/free"


def test_the_installer_asks_for_every_free_key():
    """Mid runs on Inception, yet the installer never asked for its key."""
    pytest.importorskip("winreg", reason="the installer is Windows-only")
    import installer

    asked = {env for env, _label, _hint in installer.PROVIDER_FIELDS}
    from jarvis import providers

    for provider in providers.AUTO_CHAT_PROVIDERS:
        assert provider.key_env in asked, provider.name


def test_an_updated_env_learns_about_openrouter(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    envfix.migrate(env, "5.0")
    assert "OPENROUTER_API_KEY=" in env.read_text(encoding="utf-8")
