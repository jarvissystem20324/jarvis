"""Natural voices: Microsoft's neural text-to-speech, free and keyless.

These are the voices behind Edge's Read Aloud, reached through the edge-tts
package. They sound like a person rather than a 2009 screen reader, and there
is one for every language JARVIS is likely to be asked to speak.

The trade, stated where it is made: the text being spoken is sent to
Microsoft to be turned into audio. So Privacy mode switches back to the
built-in Windows voice, which never leaves the PC, and so does being offline
or the service failing — speech degrades, it does not stop.

Playback needs nothing extra: Windows' own MCI plays the MP3 (and can pause
and resume it, which read-aloud needs); macOS uses afplay.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .config import get_setting

DEFAULT_VOICE = "en-GB-RyanNeural"   # calm, British — the obvious JARVIS

# Offered in Settings. Every one was confirmed to exist on 2026-09-24.
VOICES: tuple[tuple[str, str], ...] = (
    ("en-GB-RyanNeural", "Ryan — British, male (default)"),
    ("en-GB-ThomasNeural", "Thomas — British, male"),
    ("en-GB-SoniaNeural", "Sonia — British, female"),
    ("en-US-AndrewNeural", "Andrew — American, male"),
    ("en-US-GuyNeural", "Guy — American, male"),
    ("en-US-JennyNeural", "Jenny — American, female"),
    ("tr-TR-AhmetNeural", "Ahmet — Turkish, male"),
    ("tr-TR-EmelNeural", "Emel — Turkish, female"),
)

# One voice per language, for translation and for Turkish replies.
BY_LANGUAGE: dict[str, str] = {
    "en": "en-GB-RyanNeural", "tr": "tr-TR-AhmetNeural", "de": "de-DE-ConradNeural",
    "fr": "fr-FR-HenriNeural", "es": "es-ES-AlvaroNeural", "it": "it-IT-DiegoNeural",
    "pt": "pt-BR-AntonioNeural", "nl": "nl-NL-MaartenNeural", "ru": "ru-RU-DmitryNeural",
    "ar": "ar-SA-HamedNeural", "ja": "ja-JP-KeitaNeural", "zh": "zh-CN-YunxiNeural",
    "ko": "ko-KR-InJoonNeural", "hi": "hi-IN-MadhurNeural", "az": "az-AZ-BabekNeural",
    "pl": "pl-PL-MarekNeural", "uk": "uk-UA-OstapNeural", "fa": "fa-IR-FaridNeural",
    "el": "el-GR-NestorasNeural", "sv": "sv-SE-MattiasNeural",
}

# Short enough that the first words play within a second, long enough that
# the joins between pieces are not heard as stutters.
CHUNK_CHARS = 700
FIRST_CHUNK_CHARS = 200
_TURKISH = re.compile(r"[şğıŞĞİ]")


def installed() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True


def enabled() -> bool:
    """Natural voice unless the user chose the offline Windows voice."""
    if get_setting("JARVIS_NEURAL_VOICE", "").strip().lower() == "offline":
        return False
    return get_setting("JARVIS_TTS", "neural").strip().lower() in {"neural", "natural", "auto", ""} \
        and installed()


def voice_for(text: str = "", language: str | None = None) -> str:
    if language and language in BY_LANGUAGE:
        chosen = get_setting("JARVIS_NEURAL_VOICE", "")
        if chosen.lower().startswith(language + "-"):
            return chosen
        return BY_LANGUAGE[language]
    chosen = get_setting("JARVIS_NEURAL_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
    # An English voice reading Turkish is unintelligible; switch when the
    # text is plainly Turkish, or the window is.
    if not chosen.startswith("tr-"):
        from . import i18n

        if _TURKISH.search(text or "") or i18n.current() == "tr":
            return BY_LANGUAGE["tr"]
    return chosen


def chunks(text: str, size: int = CHUNK_CHARS, first: int = FIRST_CHUNK_CHARS) -> list[str]:
    """Split at sentence ends, never mid-word.

    The first piece is kept short: synthesis takes roughly a second per 120
    characters, and nothing is heard until the first piece is ready.
    """
    text = " ".join((text or "").split())
    if len(text) <= first:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    out: list[str] = []
    if len(sentences) > 1 and len(sentences[0]) <= first:
        out.append(sentences.pop(0))
    current = ""
    for sentence in sentences:
        while len(sentence) > size:          # one enormous sentence
            cut = sentence.rfind(" ", 0, size)
            if cut <= 0:
                cut = size
            out.append((current + " " + sentence[:cut]).strip())
            current, sentence = "", sentence[cut:].strip()
        if len(current) + len(sentence) + 1 > size:
            out.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}"
    if current.strip():
        out.append(current.strip())
    return [c for c in out if c]


def synthesize(text: str, voice: str, rate: str = "+0%", timeout: float = 20.0) -> bytes:
    """MP3 bytes for `text`. Raises on any failure; the caller falls back."""
    import edge_tts

    async def run() -> bytes:
        audio = bytearray()
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        async for part in communicate.stream():
            if part.get("type") == "audio":
                audio.extend(part["data"])
        return bytes(audio)

    data = asyncio.run(asyncio.wait_for(run(), timeout))
    if not data:
        raise RuntimeError("the voice service returned no audio")
    return data


class Player:
    """Plays one MP3 at a time. Stop, pause and resume work from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alias = ""
        self._proc: subprocess.Popen | None = None
        self.paused = False
        self._counter = 0

    # MCI is Windows' multimedia command interface, present on every version
    # since 95. It plays MP3 with no codec to install and no window.
    @staticmethod
    def _mci(command: str) -> tuple[int, str]:
        import ctypes

        buffer = ctypes.create_unicode_buffer(256)
        code = ctypes.windll.winmm.mciSendStringW(command, buffer, 255, 0)
        return code, buffer.value

    def play(self, mp3: bytes, should_stop) -> bool:
        """Block until finished or stopped. False if nothing could play it."""
        folder = Path(tempfile.gettempdir()) / "jarvis-voice"
        folder.mkdir(exist_ok=True)
        self._counter += 1
        # Unique per clip, not per player: two players in one process (the
        # window's and a test's) once collided on the same name while MCI
        # still held the first file open.
        path = folder / f"say-{os.getpid()}-{os.urandom(4).hex()}.mp3"
        path.write_bytes(mp3)
        try:
            if sys.platform == "win32":
                return self._play_windows(path, should_stop)
            if sys.platform == "darwin":
                return self._play_process(["afplay", str(path)], should_stop)
            for player in (["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
                from shutil import which

                if which(player[0]):
                    return self._play_process([*player, str(path)], should_stop)
            return False
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    def _play_windows(self, path: Path, should_stop) -> bool:
        alias = f"jarvis{self._counter}"
        code, _ = self._mci(f'open "{path}" type mpegvideo alias {alias}')
        if code != 0:
            return False
        with self._lock:
            self._alias = alias
        try:
            if self._mci(f"play {alias}")[0] != 0:
                return False
            while not should_stop():
                code, mode = self._mci(f"status {alias} mode")
                if code != 0 or (mode == "stopped" and not self.paused):
                    break
                time.sleep(0.05)
            return True
        finally:
            with self._lock:
                self._alias = ""
            self._mci(f"close {alias}")

    def _play_process(self, argv: list[str], should_stop) -> bool:
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        with self._lock:
            self._proc = proc
        try:
            while proc.poll() is None:
                if should_stop():
                    proc.terminate()
                    break
                time.sleep(0.05)
            return True
        finally:
            with self._lock:
                self._proc = None

    def stop(self) -> None:
        self.paused = False
        with self._lock:
            alias, proc = self._alias, self._proc
        if alias:
            self._mci(f"stop {alias}")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def pause(self) -> bool:
        with self._lock:
            alias, proc = self._alias, self._proc
        if alias and self._mci(f"pause {alias}")[0] == 0:
            self.paused = True
            return True
        if proc and sys.platform == "darwin":
            import signal

            proc.send_signal(signal.SIGSTOP)
            self.paused = True
            return True
        return False

    def resume(self) -> bool:
        with self._lock:
            alias, proc = self._alias, self._proc
        if alias and self._mci(f"resume {alias}")[0] == 0:
            self.paused = False
            return True
        if proc and sys.platform == "darwin":
            import signal

            proc.send_signal(signal.SIGCONT)
            self.paused = False
            return True
        return False
