"""Permissions, audit log and privacy mode.

Three related things live here because they answer the same question from
different angles: what is JARVIS allowed to do, what did it actually do, and
what should it not write down.

**Permissions.** Anything that reaches outside the conversation — running a
command, writing a file, reading the screen, sending your code to a provider —
goes through `permissions.ask()` first. The user is asked every time. The
asker is pluggable: the desktop app shows a dialog, the CLI prompts on stdin,
and a context with neither (the self-test) allows the action and records that
it did, because there the user is already typing the command themselves.

**Audit log.** Append-only, `data/audit.log`, one line per action. It records
what happened and which provider answered — never what you or JARVIS said.
That is the difference between a log you can hand to someone and one that
quietly accumulates whatever you pasted into the window.

**Privacy mode.** Turns off everything that persists: no conversation saved to
disk, no audit lines, no memory or people facts injected into prompts. What is
already on disk is left alone — this stops new writing, it does not delete.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_data_dir

AUDIT_FILE = "audit.log"
# Past this the log is rotated to audit.log.1 so it cannot grow without bound.
MAX_AUDIT_BYTES = 2_000_000
# A permission prompt nobody answers must not wedge the worker thread forever.
ASK_TIMEOUT = 120.0


# --- capabilities ---------------------------------------------------------
# Each is one sentence the user has to be able to judge in a dialog.

@dataclass(frozen=True)
class Capability:
    name: str
    title: str
    why: str


RUN_COMMAND = Capability(
    "run_command", "Run a command on this PC",
    "The command runs with your account's full permissions.",
)
WRITE_FILE = Capability(
    "write_file", "Write to a file",
    "The current contents are backed up first and /undo restores them.",
)
DELETE_FILE = Capability(
    "delete_file", "Delete a file",
    "This removes the file from disk.",
)
READ_SCREEN = Capability(
    "read_screen", "Capture your screen",
    "The image is sent to an AI provider to be described.",
)
READ_FILE = Capability(
    "read_file", "Read a file into the conversation",
    "Its contents are sent to an AI provider with your next message.",
)
SEND_CODE = Capability(
    "send_code", "Send project code to an AI provider",
    "The files you opened leave this machine.",
)
RUN_TESTS = Capability(
    "run_tests", "Run this project's test suite",
    "Tests are ordinary programs and can do anything your account can.",
)
RUN_AGENT = Capability(
    "run_agent", "Let the agent carry out this plan",
    "It will do every step below without asking again, and stop if it "
    "needs to do anything the plan does not list. Stop always works, and "
    "/undo puts every file back.",
)
NETWORK = Capability(
    "network", "Fetch something over the network",
    "JARVIS will download from the address shown.",
)

ALL_CAPABILITIES = (
    RUN_COMMAND, WRITE_FILE, DELETE_FILE, READ_SCREEN,
    READ_FILE, SEND_CODE, RUN_TESTS, NETWORK, RUN_AGENT,
)
BY_NAME = {c.name: c for c in ALL_CAPABILITIES}


# --- privacy --------------------------------------------------------------

class Privacy:
    """One switch, read by everything that would otherwise persist."""

    def __init__(self) -> None:
        self.on = False

    def enable(self) -> str:
        self.on = True
        return (
            "Privacy mode on.\n"
            "  - This conversation is not saved to disk\n"
            "  - Nothing is written to the audit log\n"
            "  - Stored facts and people are not sent with your messages\n"
            "Already-saved files are untouched. /privacy again to turn it off."
        )

    def disable(self) -> str:
        self.on = False
        return "Privacy mode off. Conversations and the audit log resume."

    def toggle(self) -> str:
        return self.disable() if self.on else self.enable()


privacy = Privacy()


# --- audit ----------------------------------------------------------------

class AuditLog:
    """Append-only record of actions. Never records message content."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enabled = True

    def path(self) -> Path:
        return get_data_dir() / AUDIT_FILE

    def record(self, action: str, detail: str = "", outcome: str = "") -> None:
        """Write one line. Best effort: logging must never break the app."""
        if not self.enabled or privacy.on:
            return
        line = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "action": action,
        }
        if detail:
            line["detail"] = detail[:300]
        if outcome:
            line["outcome"] = outcome[:120]
        try:
            with self._lock:
                path = self.path()
                self._rotate(path)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    @staticmethod
    def _rotate(path: Path) -> None:
        try:
            if path.exists() and path.stat().st_size > MAX_AUDIT_BYTES:
                path.replace(path.with_suffix(".log.1"))
        except OSError:
            pass

    def read(self, limit: int = 40) -> list[dict]:
        """The most recent entries, newest last."""
        path = self.path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict] = []
        for raw in lines[-limit:]:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def clear(self) -> str:
        try:
            self.path().unlink(missing_ok=True)
            return "Audit log cleared."
        except OSError as exc:
            return f"Could not clear the audit log: {exc}"


audit = AuditLog()


# --- permissions ----------------------------------------------------------

@dataclass
class Request:
    """One thing JARVIS wants to do, phrased for a human to judge."""

    capability: Capability
    detail: str          # the command, path or address in question
    context: str = ""    # where the request came from, e.g. "/apply"

    @property
    def title(self) -> str:
        return self.capability.title

    def describe(self) -> str:
        parts = [self.capability.title]
        if self.detail:
            parts.append(self.detail)
        return " — ".join(parts)


class Denied(Exception):
    """Raised when the user says no. Callers turn this into a reply."""


class PermissionBroker:
    def __init__(self) -> None:
        self._asker = None
        self.enabled = True
        # Set False only by the self-test, which loads addons with no UI.
        self.allow_without_asker = True

    def set_asker(self, asker) -> None:
        """Register something that can put the question to the user.

        `asker(request) -> bool`. The desktop app marshals a dialog onto the
        Tk thread; the CLI reads stdin.
        """
        self._asker = asker

    def ask(self, capability: Capability, detail: str = "", context: str = "") -> bool:
        """Put one request to the user. Returns True if allowed."""
        request = Request(capability, detail, context)

        if not self.enabled:
            audit.record("permission", request.describe(), "allowed (checks off)")
            return True

        if self._asker is None:
            allowed = self.allow_without_asker
            audit.record(
                "permission", request.describe(),
                "allowed (no prompt available)" if allowed else "denied (no prompt available)",
            )
            return allowed

        try:
            allowed = bool(self._asker(request))
        except Exception:
            # A broken asker must fail closed, not open.
            audit.record("permission", request.describe(), "denied (asker failed)")
            return False

        audit.record("permission", request.describe(), "allowed" if allowed else "DENIED")
        return allowed

    def require(self, capability: Capability, detail: str = "", context: str = "") -> None:
        """Ask, and raise Denied if the answer is no."""
        if not self.ask(capability, detail, context):
            raise Denied(
                f"Denied: {capability.title.lower()}"
                + (f" ({detail})" if detail else "")
                + ". Nothing was done."
            )


permissions = PermissionBroker()


def console_asker(request: Request) -> bool:
    """stdin prompt, for `python main.py`."""
    print(f"\n[permission] {request.capability.title}")
    if request.detail:
        print(f"             {request.detail}")
    print(f"             {request.capability.why}")
    try:
        answer = input("             Allow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def summary() -> str:
    """What the security features are currently set to."""
    entries = audit.read(limit=1000)
    denied = sum(1 for e in entries if str(e.get("outcome", "")).startswith("DENIED"))
    return (
        "Security settings\n"
        f"  Permission prompts : {'on — asked every time' if permissions.enabled else 'OFF'}\n"
        f"  Audit log          : {'on' if audit.enabled and not privacy.on else 'off'}"
        f"  ({len(entries)} entries, {denied} denied)\n"
        f"  Privacy mode       : {'ON — nothing is being saved' if privacy.on else 'off'}\n"
        f"  Log file           : {audit.path()}\n"
        f"  Encryption at rest : {_vault_state()}\n"
        f"  Redaction          : {_redact_state()}\n"
        "  Injection shield   : on — web pages, documents and files are marked untrusted\n\n"
        "  /audit    recent actions        /privacy  stop saving anything\n"
        "  /scan     find security problems  /sandbox what untrusted code would do"
    )


def _vault_state() -> str:
    from . import vault

    return vault.describe()


def _redact_state() -> str:
    from . import redact

    return ("on — keys, passwords, emails, phone and card numbers are masked before sending"
            if redact.enabled() else "OFF — /redact on")


def env_file_findings() -> list[tuple[str, str, str]]:
    """Check JARVIS's own install. Returns (level, title, detail)."""
    from .config import get_base_dir

    out: list[tuple[str, str, str]] = []
    base = get_base_dir()
    env = base / ".env"

    if not env.exists():
        out.append(("info", "No .env yet", f"Expected at {env}"))
    else:
        # Leftover migration backups hold exactly the same keys as .env.
        backups = sorted(base.glob(".env.backup-*")) + sorted(base.glob(".env.*.bak"))
        if backups:
            out.append((
                "warn",
                f"{len(backups)} .env backup file(s) still on disk",
                "Each holds the same API keys as .env. Delete them once you are "
                "sure the current .env is good: " + ", ".join(b.name for b in backups[:4]),
            ))

        try:
            text = env.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if "JARVIS_UPDATE_URL" in text:
            for line in text.splitlines():
                if line.strip().startswith("JARVIS_UPDATE_URL"):
                    value = line.partition("=")[2].strip()
                    if value and not value.lower().startswith("https://"):
                        out.append((
                            "high", "Update URL is not HTTPS",
                            f"{value[:60]} — updates would not be fetched securely.",
                        ))

    # A repository checkout that is about to commit its own secrets.
    gitignore = base / ".gitignore"
    if (base / ".git").exists():
        ignored = ""
        try:
            ignored = gitignore.read_text(encoding="utf-8")
        except OSError:
            pass
        if ".env" not in ignored:
            out.append((
                "high", ".env is not in .gitignore",
                "A commit from this folder would publish your API keys.",
            ))

    if os.getenv("JARVIS_UPDATE_URL", "").strip().lower().startswith("http://"):
        out.append((
            "high", "Update URL in the environment is plain HTTP",
            "An update fetched over HTTP can be replaced in transit.",
        ))
    return out
