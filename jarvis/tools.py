"""Built-in tools Jarvis can invoke without an LLM."""

from __future__ import annotations

import platform
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime
from typing import Callable

ToolHandler = Callable[[str], str]

# Read-only commands only. Anything not on this list is refused.
ALLOWED_COMMANDS = frozenset({"echo", "whoami", "dir", "date", "ls", "time", "pwd"})

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
    """Run a safe, read-only shell command."""
    parts = args.strip().split()
    base = parts[0].lower() if parts else ""
    if base not in ALLOWED_COMMANDS:
        return (
            f"Command not allowed: {base or '(empty)'}"
            f". Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )
    try:
        result = subprocess.run(
            args,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
        return (result.stdout + result.stderr).strip() or "(no output)"
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
