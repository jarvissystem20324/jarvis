"""14.2: the coding agent builds from an empty folder and remembers the talk.

No model is called: the brain below hands back fixed answers and records the
prompts, which is what's under test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from jarvis import agent

ROOT = Path(__file__).resolve().parent.parent


class ScriptedBrain:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def ask_once(self, prompt, image_b64=None):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "ok"


def _addon(folder):
    spec = importlib.util.spec_from_file_location("cm_memory", ROOT / "addons" / "code_mode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ADDON.root = folder
    return module.ADDON


class FakeJarvis:
    def __init__(self, addon, brain):
        self.brain = brain

        class Entry:
            pass

        entry = Entry()
        entry.addon = addon

        class Addons:
            loaded = [entry]

        self.addons = Addons()


PLAN = ('{"goal": "Build a to-do website", "risk": "none", "steps": ['
        '{"action": "write", "target": "index.html", "why": "page"},'
        '{"action": "write", "target": "app.js", "why": "logic"},'
        '{"action": "write", "target": "README.md", "why": "how to run"}]}')


@pytest.fixture
def empty(base, tmp_path):
    folder = tmp_path / "newsite"
    folder.mkdir()
    return folder


def test_it_builds_a_project_in_an_empty_folder(empty):
    brain = ScriptedBrain([PLAN, "```index.html\n<script src='app.js'></script>\n```",
                           "```app.js\nconsole.log('todo')\n```", "```README.md\nOpen index.html\n```"])
    a = agent.Agent(FakeJarvis(_addon(empty), brain))
    plan = a.make_plan("make a to-do list website from scratch")
    assert "empty folder" in brain.prompts[0] and "Building from nothing is normal" in brain.prompts[0]
    report = a.run()
    assert "Finished all 3 steps" in report
    assert (empty / "index.html").exists() and (empty / "app.js").exists() and (empty / "README.md").exists()
    # Each file is written knowing the others, so they fit together.
    assert "app.js" in brain.prompts[1] and "make a to-do list website from scratch" in brain.prompts[1]
    assert plan.writes == ["index.html", "app.js", "README.md"]


def test_it_remembers_earlier_tasks_even_after_a_restart(empty):
    brain = ScriptedBrain([PLAN, "```index.html\nhi\n```", "```app.js\nx\n```", "```README.md\nr\n```"])
    a = agent.Agent(FakeJarvis(_addon(empty), brain))
    a.make_plan("make a to-do list website")
    a.run()

    # A new Agent, as after closing JARVIS: the memory is on disk.
    later = ScriptedBrain(['{"goal": "make it blue", "steps": [{"action": "read", "target": "index.html"}]}'])
    b = agent.Agent(FakeJarvis(_addon(empty), later))
    b.make_plan("now make it blue")
    prompt = later.prompts[0]
    assert "Earlier in this conversation" in prompt and "make a to-do list website" in prompt
    assert "index.html" in prompt.split("Earlier in this conversation", 1)[1]


def test_questions_see_the_project_and_are_remembered(empty):
    (empty / "game.py").write_text("print('hello')\n", encoding="utf-8")
    brain = ScriptedBrain(["Run it with: python game.py"])
    a = agent.Agent(FakeJarvis(_addon(empty), brain))
    reply = a.answer("how do I run game.py?")
    assert "python game.py" in reply and "print('hello')" in brain.prompts[0]
    assert a.memory()[-1]["task"] == "how do I run game.py?"


def test_forget_starts_over(empty):
    brain = ScriptedBrain(["Answer one"])
    a = agent.Agent(FakeJarvis(_addon(empty), brain))
    a.answer("what is this?")
    assert a.memory()
    assert "Forgot 1" in a.forget()
    assert a.memory() == [] and a.memory_text() == ""


def test_memory_is_kept_per_folder(base, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(), two.mkdir()
    a = agent.Agent(FakeJarvis(_addon(one), ScriptedBrain(["x"])))
    a.answer("question about one")
    b = agent.Agent(FakeJarvis(_addon(two), ScriptedBrain(["y"])))
    b.root = two
    assert b.memory() == []
