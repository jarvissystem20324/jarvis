"""Mask secrets and personal details before anything reaches a cloud AI.

Everything JARVIS sends — your message, the conversation so far, what an
addon attached — passes through here first. API keys, passwords, email
addresses, phone numbers and card numbers are swapped for placeholders like
[EMAIL-1]; the model works with the placeholder, and the reply has the real
value put back before you see it. So "write an email to ata@example.com"
still produces an email to ata@example.com, but the provider never saw it.

It is pattern matching, so it errs towards masking: a long random-looking
string may be masked although it was not a key. What it will not catch is a
secret written in words ("my password is the name of my first dog"). The
setting is JARVIS_REDACT (on by default); /redact shows what was masked in
the last request, as counts only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import get_setting

# (kind, pattern). Order matters: a key is masked before the generic
# long-token rule can see it, and emails before phone numbers, so digits in
# an address are not taken for a phone.
_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("KEY", re.compile(
        r"\b(?:sk-(?:proj-|ant-|or-v1-)?[A-Za-z0-9_\-]{20,}"
        r"|sk_(?:live_|test_)?[A-Za-z0-9_]{20,}"             # Inception, Stripe
        r"|gsk_[A-Za-z0-9]{20,}"
        r"|nvapi-[A-Za-z0-9_\-]{20,}"
        r"|AIza[A-Za-z0-9_\-]{30,}"
        r"|AQ\.[A-Za-z0-9_\-]{30,}"                           # Google's newer key form
        r"|fc-[0-9a-f]{32}"                                   # Firecrawl
        r"|hf_[A-Za-z0-9]{30,}"                               # Hugging Face
        r"|cfat_[A-Za-z0-9_\-]{20,}"                          # Cloudflare"
        r"|gh[pousr]_[A-Za-z0-9]{30,}"
        r"|github_pat_[A-Za-z0-9_]{30,}"
        r"|AKIA[A-Z0-9]{16}"
        r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
        r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"
    )),
    # api_key = …, token: …, secret=… — whatever the key looks like. A value
    # with a digit and no dots or call after it: `api_key = settings.API_KEY`
    # and `token = request.headers.get(…)` are code, not secrets.
    ("KEY", re.compile(
        r"(?i)(?<![A-Za-z])(?:api[_\- ]?key|apikey|access[_\- ]?token|token|secret|client[_\- ]?secret)"
        r"(?:\s+is|\s*[:=])\s*[\"']?((?=[A-Za-z0-9_\-/+]*\d)[A-Za-z0-9_\-/+]{16,})(?![.(\w])"
    )),
    # password: hunter2 / pwd = "x" / şifre: x / "my password is x"
    ("PASSWORD", re.compile(
        r"(?i)(?<![A-Za-z])(?:password|passwd|pwd|passcode|şifre(?:m)?|parola(?:m)?)"
        r"(?:\s+is|\s*[:=])\s*[\"']?([^\s\"',;]{3,})"
    )),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("CARD", re.compile(r"\b\d(?:[ \-]?\d){12,18}\b")),
    ("PHONE", re.compile(
        r"(?<![\w/])(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3}[\s\-]?\d{2,4}[\s\-]?\d{2,4}(?![\w/])"
    )),
)

_PLACEHOLDER = re.compile(r"\[(KEY|PASSWORD|EMAIL|CARD|PHONE)-(\d+)\]")


def enabled() -> bool:
    return get_setting("JARVIS_REDACT", "on").strip().lower() not in {"0", "off", "false", "no"}


def _own_secrets() -> list[str]:
    """Values of the keys and tokens in JARVIS's settings, longest first."""
    import os

    values = {
        value.strip() for name, value in os.environ.items()
        if re.search(r"(?:_API_KEY|_TOKEN|_SECRET|_PASSWORD)$", name) and len(value.strip()) >= 12
    }
    return sorted(values, key=len, reverse=True)


def _luhn(digits: str) -> bool:
    """Real card numbers pass the Luhn check; most long numbers do not."""
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _looks_like_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if not 9 <= len(digits) <= 15:
        return False
    # Years, times and version numbers are not phone numbers.
    if re.fullmatch(r"(19|20)\d{2}", digits[:4]) and len(digits) <= 8:
        return False
    # A plain run of digits with no separators and no + is more often an ID
    # or an amount than a phone number; require some phone-like shape.
    return text.strip().startswith("+") or bool(re.search(r"[\s\-()]", text.strip()))


@dataclass
class Redactor:
    """Masks one request's text and restores the reply. Keeps the mapping."""

    to_value: dict[str, str] = field(default_factory=dict)
    to_token: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def _token(self, kind: str, value: str) -> str:
        if value in self.to_token:
            return self.to_token[value]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        token = f"[{kind}-{self.counts[kind]}]"
        self.to_token[value] = token
        self.to_value[token] = value
        return token

    def mask(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text
        # The keys JARVIS itself holds, whatever their shape: a Mistral or
        # Cloudflare key matches no pattern, and was sent as it was.
        for value in _own_secrets():
            if value in text:
                text = text.replace(value, self._token("KEY", value))
        for kind, pattern in _PATTERNS:
            def replace(match: re.Match, kind=kind) -> str:
                whole = match.group(0)
                if match.groups() and match.group(1) and kind in {"PASSWORD", "KEY"}:
                    secret = match.group(1)
                    return whole.replace(secret, self._token(kind, secret))
                if kind == "CARD":
                    digits = re.sub(r"\D", "", whole)
                    if not (13 <= len(digits) <= 19 and _luhn(digits)):
                        return whole
                if kind == "PHONE" and not _looks_like_phone(whole):
                    return whole
                return self._token(kind, whole)

            text = pattern.sub(replace, text)
        return text

    def mask_messages(self, messages: list[dict]) -> list[dict]:
        """A masked copy. The originals — your saved history — are untouched."""
        out = []
        for message in messages:
            content = message.get("content")
            copy = dict(message)
            if isinstance(content, str):
                copy["content"] = self.mask(content)
            elif isinstance(content, list):
                copy["content"] = [
                    {**part, "text": self.mask(part["text"])}
                    if isinstance(part, dict) and isinstance(part.get("text"), str) else part
                    for part in content
                ]
            out.append(copy)
        return out

    def restore(self, text: str) -> str:
        if not text or not self.to_value:
            return text
        return _PLACEHOLDER.sub(lambda m: self.to_value.get(m.group(0), m.group(0)), text)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def describe(self) -> str:
        if not self.total:
            return "nothing"
        names = {"KEY": "key", "PASSWORD": "password", "EMAIL": "email address",
                 "CARD": "card number", "PHONE": "phone number"}
        return ", ".join(
            f"{n} {names[k]}{'s' if n != 1 else ''}" for k, n in self.counts.items()
        )


NOTE = (
    "Some values in this conversation were replaced with placeholders such as "
    "[EMAIL-1] or [PHONE-1] for privacy. Use a placeholder exactly as written "
    "wherever the real value belongs; it is filled in before the user sees "
    "your reply. Never ask the user for the hidden value."
)
