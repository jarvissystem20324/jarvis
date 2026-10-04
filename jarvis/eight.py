"""The 8.0 commands, gathered into one mixin.

Each group lives in its own module (makers, study, life, live, pctools,
guard, devtools, social) and registers its commands with @command; Jarvis
inherits this class, and eight_command finds a command's method by name.

Two things need the window's help, and are answered here for it:
  - secret_request(): commands whose input must never appear in the chat
    (a password to check, a 2FA secret, an app password). The window asks
    for each value in a hidden box and hands them straight to the function.
  - on_fire(): reminder-board items that do work when they come due (a
    price watch, the next prayer time, the end of do-not-disturb).
"""

from __future__ import annotations

import os
import re

from . import registry
from .designer import Designer
from .devtools import DevTools
from .guard import Guard
from .life import Life
from .live import Live
from .makers import Makers
from .pctools import PCTools
from .social import Social
from .study import Study
from .ten import Ten

SECRET_COMMANDS = {"passcheck", "passwordcheck", "pwned", "breach"}
FIRE_KINDS = {"watch", "prayer", "word", "dnd"}


class Eight(Makers, Study, Life, Live, PCTools, Guard, DevTools, Social, Designer, Ten):
    def eight_command(self, name: str, args: str, routed: bool = False):
        method = registry.COMMANDS.get(name)
        if method is None:
            return None
        return getattr(self, method)(args, routed)

    def on_fire(self, item) -> str:
        if item.kind == "dnd":
            try:
                from .pctools import notifications

                notifications(True)
            except Exception:
                pass
            os.environ["JARVIS_QUIET"] = ""
            return "🔔 Do not disturb is over."
        return self.live_fire(item)

    @staticmethod
    def mask(text: str) -> str:
        """What the chat shows for a command that carried a secret inline."""
        name, _, args = text[1:].partition(" ") if text.startswith("/") else ("", "", "")
        if name.lower() in SECRET_COMMANDS and args.strip():
            return f"/{name} " + "•" * 8
        return text

    def secret_request(self, text: str):
        """(prompts, finish) for a command that needs hidden input, else None.

        prompts is a list of (question, hide) and finish(values) -> reply text.
        """
        if not text.startswith("/"):
            return None
        name, _, args = text[1:].partition(" ")
        name, args = name.lower(), args.strip()
        if name in {"passcheck", "passwordcheck"}:
            if args:
                return [], lambda values: self.check_password(args)
            return [("Password to check — never shown, saved or sent:", True)], lambda v: self.check_password(v[0])
        if name in {"pwned", "breach"}:
            if args:
                return [], lambda values: self.check_pwned(args)
            return [("Password to check against known breaches:", True)], lambda v: self.check_pwned(v[0])
        if name in {"2fa", "totp", "otp"} and re.match(r"add\s+\S", args, re.I):
            account = args[4:].strip()
            return [(f"Setup key (or otpauth:// link) for {account}:", True)], lambda v: self.add_totp(account, v[0])
        if name == "encrypt" and args:
            def finish(values):
                if values[0] != values[1]:
                    return "The two passwords didn't match. Nothing was encrypted."
                return self.encrypt_with(args, values[0])
            return [("Password for the locked file (8+ characters):", True), ("The same password again:", True)], finish
        if name == "decrypt" and args:
            return [("Password:", True)], lambda v: self.decrypt_with(args, v[0])
        if name in {"inbox", "mail"} and args.lower() in {"setup", "set up", "connect"}:
            return [("Email address:", False), ("App password (not your normal password):", True)], \
                lambda v: self.setup_inbox(v[0], v[1])
        if name in {"gcal", "googlecalendar"} and args.lower() in {"setup", "connect"}:
            return [("Secret address in iCal format:", True)], lambda v: self.setup_gcal(v[0])
        return None
