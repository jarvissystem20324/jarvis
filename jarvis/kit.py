"""Small shared helpers for the 8.0 commands: storage, the web, model JSON.

Store: a sealed (vault) JSON file in the data folder, the same at-rest
encryption notes and spending use. get_json: a GET through net.urlopen
(certifi-pinned TLS). ask_json: ask the model for JSON and get Python back,
tolerating the code fences and chatter models wrap it in.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from . import net, vault
from .config import get_data_dir, get_output_dir

UA = {"User-Agent": net.DEFAULT_USER_AGENT, "Accept": "application/json"}


class KitError(Exception):
    pass


class Store:
    """A JSON value kept sealed in the data folder."""

    def __init__(self, name: str, default):
        self.name = name
        self.default = default

    @property
    def path(self) -> Path:
        return get_data_dir() / self.name

    def load(self):
        path = self.path
        if not path.exists():
            return json.loads(json.dumps(self.default))
        try:
            data = vault.read_json(path)
        except (OSError, ValueError):
            return json.loads(json.dumps(self.default))
        return data if isinstance(data, type(self.default)) else json.loads(json.dumps(self.default))

    def save(self, data) -> None:
        vault.write_json(self.path, data)


def get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 15):
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    try:
        with net.urlopen(urllib.request.Request(full, headers={**UA, **(headers or {})}), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        host = urllib.parse.urlparse(url).netloc
        raise KitError(f"Couldn't reach {host}: {net.describe_ssl_error(exc) or exc}") from None


def get_text(url: str, headers: dict | None = None, timeout: float = 15, limit: int = 2_000_000) -> str:
    try:
        with net.urlopen(urllib.request.Request(url, headers={"User-Agent": net.DEFAULT_USER_AGENT, **(headers or {})}),
                         timeout=timeout) as r:
            return r.read(limit).decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as exc:
        host = urllib.parse.urlparse(url).netloc
        raise KitError(f"Couldn't reach {host}: {net.describe_ssl_error(exc) or exc}") from None


def parse_json(text: str):
    """The first JSON object or list in a model reply — repaired if it was cut off."""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)(?:```|$)", body, re.S)
    if fence:
        body = fence.group(1).strip()
    starts = [i for i in (body.find("{"), body.find("[")) if i >= 0]
    if not starts:
        raise KitError("The answer didn't come back in a usable form. Try again.")
    start = min(starts)
    closer = "}" if body[start] == "{" else "]"
    end = body.rfind(closer)
    try:
        return json.loads(body[start:end + 1])
    except ValueError:
        repaired = _repair(body[start:])
        if repaired is not None:
            return repaired
        raise KitError("The answer didn't come back in a usable form. Try again.") from None


def _repair(body: str):
    """Keep everything up to the last complete value of a cut-off reply and close it.

    '{"slides": [{"a": 1}, {"b": 2}, {"c": "half' -> {"slides": [{"a": 1}, {"b": 2}]}
    """
    stack: list[str] = []
    cuts: list[tuple[int, str]] = []          # (index after a complete value, closers needed)
    in_string = escaped = False
    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            cuts.append((i + 1, "".join(reversed(stack))))
    for index, closers in reversed(cuts[-200:]):
        try:
            return json.loads(body[:index] + closers)
        except ValueError:
            continue
    return None


def ask_json(brain, prompt: str, room: int = 6000, **kwargs):
    with more_room(brain, room):
        return parse_json(brain.ask_once(prompt + "\n\nReturn JSON only.", **kwargs))


class more_room:
    """`with more_room(brain):` — this call's reply may be long (a deck, a CV)."""

    def __init__(self, brain, tokens: int = 6000):
        self.brain, self.tokens = brain, tokens

    def __enter__(self):
        self.before = getattr(self.brain, "min_tokens", 0)
        try:
            self.brain.min_tokens = max(self.before, self.tokens)
        except AttributeError:
            pass
        return self.brain

    def __exit__(self, *exc):
        try:
            self.brain.min_tokens = self.before
        except AttributeError:
            pass
        return False


def output_dir(kind: str = "documents") -> Path:
    folder = get_output_dir().parent / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip()
    return re.sub(r"\s+", "-", cleaned)[:limit] or "file"


def size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def ago(epoch: float) -> str:
    seconds = max(0, time.time() - epoch)
    for unit, length in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= length:
            return f"{int(seconds // length)}{unit} ago"
    return "just now"


def path_arg(text: str) -> Path | None:
    """A file path given as an argument, quoted or not, if it exists."""
    raw = (text or "").strip().strip('"').strip("'")
    if not raw or len(raw) > 400:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def windows() -> bool:
    import sys

    return sys.platform == "win32"
