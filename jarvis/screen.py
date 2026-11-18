"""Eyes and hands for Cowork (13.4.2): see the screen, click and type, safely.

Seeing is a screenshot, shrunk and sent to a vision model (NVIDIA's Nemotron
3.5 VL by the user's choice, Gemini as the backup). Models give positions on
different grids — Nemotron on 0-1, Gemini on 0-1000 — so `to_pixels` turns
either into a pixel on this screen.

Acting is done by `Hands`, and only after the user has allowed it for that
one job. Three rules hold whatever a model asks for:

  1. Nothing that commits: Submit, Send, Pay, Buy, Delete, Sign in and the
     like are never clicked. Cowork fills; the user presses the button.
  2. A way out: push the mouse into the top-left corner of the screen and
     every action after that is refused.
  3. Everything is logged in the audit log.
"""

from __future__ import annotations

import base64
import io
import re
import sys
import time

# Labels Cowork must never click or press, English and Turkish.
COMMIT_WORDS = re.compile(
    r"\b(submit|send|pay|buy|purchase|order|checkout|check out|confirm|place order|delete|remove|sign in|log in|"
    r"login|sign up|register|apply now|publish|post|transfer|donate|subscribe|unsubscribe|accept|agree|"
    r"gönder|öde|ödeme|satın al|sipariş|onayla|sil|kaldır|giriş yap|oturum aç|kaydol|üye ol|başvur|yayınla|"
    r"kabul|abone)\b",
    re.IGNORECASE,
)

# The corner that stops everything: this many pixels from the top-left.
FAILSAFE_PIXELS = 4
MAX_SHOT_WIDTH = 1280


class ScreenError(Exception):
    pass


class Stopped(ScreenError):
    """The user pushed the mouse into the corner, or the job was stopped."""


def is_commit(label: str) -> bool:
    """True for a control whose click would commit something (Submit, Pay…)."""
    return bool(COMMIT_WORDS.search(label or ""))


def to_pixels(x: float, y: float, width: int, height: int, grid: str = "auto") -> tuple[int, int]:
    """A model's position as a pixel on a width×height screen.

    grid: "unit" (0-1), "thousand" (0-1000), "pixels", or "auto", which
    decides from the numbers: both ≤ 1 is the unit grid, both ≤ 1000 the
    thousand grid, anything bigger is already pixels.
    """
    x, y = float(x), float(y)
    if grid == "auto":
        if 0 <= x <= 1 and 0 <= y <= 1:
            grid = "unit"
        elif 0 <= x <= 1000 and 0 <= y <= 1000:
            grid = "thousand"
        else:
            grid = "pixels"
    if grid == "unit":
        px, py = x * width, y * height
    elif grid == "thousand":
        px, py = x / 1000 * width, y / 1000 * height
    else:
        px, py = x, y
    return max(0, min(width - 1, round(px))), max(0, min(height - 1, round(py)))


def screenshot():
    """The primary screen as a PIL image (physical pixels)."""
    try:
        from PIL import ImageGrab
    except ImportError as exc:  # pragma: no cover - Pillow ships with JARVIS
        raise ScreenError(f"Screenshots need Pillow: {exc}") from None
    try:
        return ImageGrab.grab()
    except Exception as exc:
        raise ScreenError(f"Couldn't capture the screen: {exc}") from None


def encode(image, max_width: int = MAX_SHOT_WIDTH) -> str:
    """A PNG, shrunk to max_width, as base64 — what a vision model is sent."""
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * ratio))))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# --- hands ----------------------------------------------------------------------

class Hands:
    """Click, type and scroll — only after `allowed` is set, never on a commit."""

    def __init__(self, stop_event=None, backend=None) -> None:
        self.allowed = False
        self.stop_event = stop_event
        self.backend = backend or (_WindowsInput() if sys.platform == "win32" else None)
        self.done: list[str] = []

    def _check(self, label: str = "") -> None:
        if not self.allowed:
            raise ScreenError("Cowork isn't allowed to use the mouse and keyboard for this job.")
        if self.stop_event is not None and self.stop_event.is_set():
            raise Stopped("Stopped.")
        if self.backend is None:
            raise ScreenError("Clicking and typing work on Windows only.")
        x, y = self.backend.cursor()
        if x <= FAILSAFE_PIXELS and y <= FAILSAFE_PIXELS:
            self.allowed = False
            raise Stopped("Stopped: the mouse is in the top-left corner.")
        if is_commit(label):
            raise ScreenError(f"Cowork never presses “{label}”. That one is yours.")

    def click(self, x: int, y: int, label: str = "", space: tuple[int, int] | None = None) -> None:
        """Click at (x, y). `space` is the screenshot's size when (x, y) came from one: the
        screenshot is in physical pixels, the cursor may not be (display scaling)."""
        self._check(label)
        if space is not None and hasattr(self.backend, "screen_size"):
            width, height = self.backend.screen_size()
            if width and height and space[0] and space[1]:
                x, y = round(x * width / space[0]), round(y * height / space[1])
        self.backend.click(x, y)
        self.done.append(f"click {label or ''} at {x},{y}".strip())
        time.sleep(0.15)

    def type_text(self, text: str, label: str = "", replace: bool = True) -> None:
        self._check(label)
        if replace:
            self.backend.select_all()
        self.backend.type(text)
        self.done.append(f"type into {label or 'field'}")
        time.sleep(0.1)

    def scroll(self, clicks: int = -5) -> None:
        self._check()
        self.backend.scroll(clicks)
        self.done.append("scroll")
        time.sleep(0.6)


class _WindowsInput:  # pragma: no cover - drives the real mouse and keyboard
    """SendInput through ctypes: no extra package, Unicode text (ç, ğ, ş…)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.KEYBDINPUT, self.MOUSEINPUT, self.INPUT = KEYBDINPUT, MOUSEINPUT, INPUT

    def screen_size(self) -> tuple[int, int]:
        """The primary screen in this process's own coordinates."""
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)

    def cursor(self) -> tuple[int, int]:
        point = self.wintypes.POINT()
        self.user32.GetCursorPos(self.ctypes.byref(point))
        return point.x, point.y

    def _send(self, *inputs) -> None:
        array = (self.INPUT * len(inputs))(*inputs)
        self.user32.SendInput(len(inputs), array, self.ctypes.sizeof(self.INPUT))

    def _mouse(self, flags: int, data: int = 0):
        item = self.INPUT(type=0)
        item.u.mi = self.MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, None)
        return item

    def _key(self, vk: int = 0, scan: int = 0, flags: int = 0):
        item = self.INPUT(type=1)
        item.u.ki = self.KEYBDINPUT(vk, scan, flags, 0, None)
        return item

    def click(self, x: int, y: int) -> None:
        self.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        self._send(self._mouse(0x0002), self._mouse(0x0004))   # left down, left up

    def scroll(self, clicks: int) -> None:
        self._send(self._mouse(0x0800, int(clicks) * 120))

    def select_all(self) -> None:
        ctrl, a, up = 0x11, 0x41, 0x0002
        self._send(self._key(ctrl), self._key(a), self._key(a, flags=up), self._key(ctrl, flags=up))
        time.sleep(0.05)

    def type(self, text: str) -> None:
        unicode, up = 0x0004, 0x0002
        for ch in text:
            if ch == "\n":
                continue  # Enter could submit a form; never sent
            for unit in _utf16_units(ch):
                self._send(self._key(scan=unit, flags=unicode), self._key(scan=unit, flags=unicode | up))
            time.sleep(0.008)


def _utf16_units(ch: str) -> list[int]:
    data = ch.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
