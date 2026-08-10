"""Command-line entry point for JARVIS 2.0."""

from __future__ import annotations

import sys

from jarvis.assistant import Jarvis
from jarvis.config import load_config


def main() -> int:
    # Windows consoles default to cp1252 and choke on the em dashes in output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    load_config()

    try:
        jarvis = Jarvis()
    except Exception as exc:
        print(f"Failed to start: {exc}")
        return 1

    print(jarvis.greet())
    print("Type /help for commands, /quit to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + jarvis.farewell())
            return 0

        if not user_input:
            continue

        response = jarvis.process(user_input)
        print(f"\nJARVIS: {response.text}\n")

        if response.should_quit:
            return 0


if __name__ == "__main__":
    sys.exit(main())
