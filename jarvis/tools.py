"""Built-in tools Jarvis can invoke without an LLM."""

from __future__ import annotations

import platform
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime
from typing import Callable

from . import security

ToolHandler = Callable[[str], str]

# Read-only commands only. Anything not on this list is refused.
ALLOWED_COMMANDS = frozenset({"echo", "whoami", "dir", "date", "ls", "time", "pwd"})

# Punctuation that lets a shell chain, redirect, substitute or expand. Any of
# these in the argument string means the line could do more than the one
# allow-listed command it appears to be, so the whole thing is refused.
SHELL_METACHARACTERS = frozenset('&|;<>^$`()!%\n\r\t')

# These exist only inside cmd.exe, so they cannot be launched directly.
WINDOWS_SHELL_BUILTINS = frozenset({"dir", "echo", "date", "time"})

COMMAND_TIMEOUT = 10


def _get_time(_: str) -> str:
    return datetime.now().strftime("The current time is %I:%M %p on %A, %B %d, %Y.")


def _get_date(_: str) -> str:
    return datetime.now().strftime("Today is %A, %B %d, %Y.")


def _system_info(_: str) -> str:
    return (
        f"System: {platform.system()} {platform.release()}"
        f"\nMachine: {platform.machine()}"
        f"\nPython: {platform.python_version()}"
    )


def _open_url(args: str) -> str:
    url = args.strip()
    if not url:
        return "Please specify a URL. Example: open https://google.com"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}"


def _search_web(args: str) -> str:
    query = args.strip()
    if not query:
        return "Please specify a search query. Example: search Python tutorials"
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searching the web for: {query}"


def _run_command(args: str) -> str:
    """Run a safe, read-only shell command.

    The allow-list is checked against the first word, so the rest of the line
    must not be able to start a second command. Shell punctuation is therefore
    rejected outright and nothing is passed through a shell: previously the
    whole string went to cmd.exe with shell=True, which made the allow-list
    decorative — `echo x & hostname` passed the check on `echo` and then ran
    `hostname` anyway.
    """
    raw = args.strip()
    if not raw:
        return f"Usage: /run <command>. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"

    present = sorted(set(raw) & SHELL_METACHARACTERS)
    if present:
        shown = " ".join(present).replace("\n", "\\n").replace("\r", "\\r")
        return (
            f"Refused: that contains shell characters ({shown}) which could "
            "chain another command. Run one simple command at a time."
        )

    parts = raw.split()
    base = parts[0].lower()
    if base not in ALLOWED_COMMANDS:
        return (
            f"Command not allowed: {base}"
            f". Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    # The allow-list says this command is safe in principle; the prompt is
    # about this particular run. Both matter: the list stops a command that
    # should never run, the prompt stops one the user did not ask for.
    if not security.permissions.ask(security.RUN_COMMAND, raw, context="/run"):
        return f"Denied. '{raw}' was not run."
    security.audit.record("run", raw)

    # dir/echo/date/time have no executable on disk — they only exist inside
    # cmd.exe — so those need an interpreter. Everything else is launched
    # directly, and no argument reaches a shell in either case.
    if sys.platform.startswith("win") and base in WINDOWS_SHELL_BUILTINS:
        argv = ["cmd", "/d", "/c", *parts]
    else:
        argv = parts

    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            # Stops a console window flashing up over the GUI on Windows.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (result.stdout + result.stderr).strip() or "(no output)"
    except FileNotFoundError:
        return f"'{base}' is not available on this system."
    except subprocess.TimeoutExpired:
        return f"Command timed out after {COMMAND_TIMEOUT} seconds."
    except Exception as exc:
        return f"Error running command: {exc}"


BUILTIN_TOOLS: dict[str, tuple[str, ToolHandler]] = {
    "time": ("Get the current time and date", _get_time),
    "date": ("Get today's date", _get_date),
    "system": ("Show system information", _system_info),
    "open": ("Open a URL in the browser", _open_url),
    "search": ("Search the web via Google", _search_web),
    "run": ("Run a safe shell command", _run_command),
}


def try_handle_command(user_input: str) -> str | None:
    """If input is a built-in command, return the result. Otherwise None."""
    text = user_input.strip()
    if not text.startswith("/"):
        return None

    body = text[1:].strip()
    name, _, args = body.partition(" ")
    name = name.lower()

    if name == "help":
        lines = ["Available commands:"]
        lines += [f"  /{cmd} — {desc}" for cmd, (desc, _h) in BUILTIN_TOOLS.items()]
        lines += [
            "  /image <prompt> — Generate an image",
            "  /help — Show this help",
            "  /clear — Clear conversation history",
            "  /voice — Toggle voice mode",
            "  /quit — Exit JARVIS",
        ]
        return "\n".join(lines)

    if name in BUILTIN_TOOLS:
        return BUILTIN_TOOLS[name][1](args)

    # Handled upstream by the assistant, not here.
    if name in {"image", "clear", "voice", "quit", "exit"}:
        return None

    return f"Unknown command: /{name}. Type /help for available commands."
