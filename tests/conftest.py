"""Shared fixtures.

Every test runs against a temporary base directory. That is not tidiness: the
modules here read and write .env, conversations, the audit log and the memory
file by absolute path, and a test that forgets to redirect one of those edits
the developer's real install. It has already happened once — a test fixture
wrote two junk facts into the real memory.json.

Redirecting is fiddlier than it looks, because several modules do
`from .config import get_data_dir`, which binds the function at import time.
Patching `config.get_data_dir` alone leaves those modules pointing at the real
folder, so each importer is patched by name below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fake_key(prefix: str, body: str = "AbCdEf0123456789AbCdEf0123456789") -> str:
    """A credential-shaped string that is obviously not a credential.

    Assembled at runtime on purpose. Written out literally, these fixtures
    are flagged by JARVIS's own /scan and can trip GitHub's push protection,
    which pattern-matches keys in pushed code — the tests for the secret
    scanner must not themselves look like leaked secrets.
    """
    return prefix + body


FAKE_OPENAI_KEY = fake_key("sk-" + "proj-")


@pytest.fixture
def base(tmp_path, monkeypatch):
    """A throwaway JARVIS installation. Yields its root."""
    (tmp_path / "data").mkdir()
    (tmp_path / "output" / "images").mkdir(parents=True)

    from jarvis import addons as addons_mod
    from jarvis import config, history, security

    data = tmp_path / "data"
    monkeypatch.setattr(config, "get_base_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_data_dir", lambda: data)
    monkeypatch.setattr(config, "get_output_dir", lambda: tmp_path / "output" / "images")
    # Bound at import time in each of these, so patching config is not enough.
    monkeypatch.setattr(history, "get_data_dir", lambda: data)
    monkeypatch.setattr(history, "get_output_dir", lambda: tmp_path / "output" / "images")
    monkeypatch.setattr(addons_mod, "get_data_dir", lambda: data)
    monkeypatch.setattr(addons_mod, "get_addons_dir", lambda: ROOT / "addons")
    monkeypatch.setattr(security, "get_data_dir", lambda: data)
    from jarvis import library, schedule

    monkeypatch.setattr(schedule, "get_data_dir", lambda: data)
    monkeypatch.setattr(library, "get_data_dir", lambda: data)
    monkeypatch.setattr(schedule.scheduler, "tasks", [])

    # The developer's real .env still loads underneath these, and it may have
    # voice on: a GUI test once greeted the room out loud through the
    # speakers. Nothing in a test run should speak, search the web on its
    # own, or register a system-wide dictation shortcut.
    monkeypatch.setenv("JARVIS_VOICE", "false")
    monkeypatch.setenv("JARVIS_TTS", "offline")
    monkeypatch.setenv("JARVIS_AUTO_WEB", "off")
    monkeypatch.setenv("JARVIS_DICTATE_HOTKEY", "off")
    monkeypatch.setenv("JARVIS_QUICKASK_HOTKEY", "off")
    monkeypatch.setenv("JARVIS_SUGGEST", "off")
    from jarvis import notes, reminders

    monkeypatch.setattr(notes, "get_data_dir", lambda: data)
    monkeypatch.setattr(reminders, "get_data_dir", lambda: data)
    monkeypatch.setattr(reminders.board, "items", [])
    monkeypatch.setattr(reminders.board, "missed", [])

    security.privacy.on = False
    security.permissions.set_asker(None)
    yield tmp_path
    security.permissions.set_asker(None)
    security.privacy.on = False


@pytest.fixture
def allow(monkeypatch):
    """Answer every permission prompt with yes, and record what was asked."""
    from jarvis import security

    asked: list = []
    security.permissions.set_asker(lambda request: (asked.append(request), True)[1])
    return asked


@pytest.fixture
def deny():
    """Answer every permission prompt with no."""
    from jarvis import security

    asked: list = []
    security.permissions.set_asker(lambda request: (asked.append(request), False)[1])
    return asked


@pytest.fixture
def project(tmp_path):
    """A tiny Python project with one real bug and a test that catches it."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_calc.py").write_text(
        "import sys\nimport unittest\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from src.calc import add\n\n\n"
        "class TestCalc(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 2), 4)\n",
        encoding="utf-8",
    )
    return root
