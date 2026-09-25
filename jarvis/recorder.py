"""Lecture and meeting notes: listen for as long as it takes, then write it up.

The microphone is read on a background thread and cut into four-minute
pieces. Each piece is transcribed as soon as it is complete (with the same
speech-to-text JARVIS already uses for push-to-talk), so when you say
"/record stop" only the last few minutes are left to do. Audio is held in
memory and dropped once transcribed; it is never written to disk.
"""

from __future__ import annotations

import queue
import threading
import time

CHUNK_SECONDS = 240
MAX_SECONDS = 3 * 3600

NOTES_PROMPT = """Below is the transcript of a recording (a lecture, meeting or talk),
made by speech recognition, so expect small mistakes. Write clear notes in Markdown:

# <a short title>
## Summary            (3-5 sentences)
## Key points         (bullets, grouped under ### subheadings if it is long)
## Action items       (who does what, by when — only if any were said; otherwise omit)
## Questions / follow-ups   (only if any)

Write in the language of the transcript. Output only the notes.

--- transcript ---
{transcript}
"""


class Recorder:
    """One recording at a time. `transcribe` turns 16 kHz int16 PCM into text."""

    def __init__(self, transcribe, sample_rate: int = 16000, block: int = 1024) -> None:
        self.transcribe = transcribe
        self.rate = sample_rate
        self.block = block
        self.started: float | None = None
        self.pieces: list[str] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.started is not None

    def elapsed(self) -> float:
        return time.time() - self.started if self.started else 0.0

    def start(self, stream_factory=None) -> None:
        if self.running:
            return
        self.pieces, self.errors = [], []
        self._stop.clear()
        self.started = time.time()
        self._reader = threading.Thread(target=self._read, args=(stream_factory,), daemon=True)
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._reader.start()
        self._writer.start()

    def _open(self):
        import sounddevice as sd

        return sd.InputStream(samplerate=self.rate, channels=1, dtype="int16", blocksize=self.block)

    def _read(self, stream_factory) -> None:
        chunk: list[bytes] = []
        per_chunk = CHUNK_SECONDS * self.rate // self.block
        blocks = 0
        try:
            with (stream_factory or self._open)() as stream:
                while not self._stop.is_set() and self.elapsed() < MAX_SECONDS:
                    data, _overflowed = stream.read(self.block)
                    chunk.append(bytes(data))
                    blocks += 1
                    if blocks >= per_chunk:
                        self._queue.put(b"".join(chunk))
                        chunk, blocks = [], 0
        except Exception as exc:
            self.errors.append(f"microphone: {exc}")
        if chunk:
            self._queue.put(b"".join(chunk))
        self._queue.put(None)

    def _write(self) -> None:
        while True:
            pcm = self._queue.get()
            if pcm is None:
                return
            # Under a second of audio is the tail of pressing stop.
            if len(pcm) < self.rate * 2:
                continue
            try:
                text = self.transcribe(pcm)
                if text:
                    self.pieces.append(text.strip())
            except Exception as exc:
                self.errors.append(str(exc).splitlines()[0][:160])

    def stop(self, timeout: float = 300) -> str:
        """Stop, wait for the last pieces, and return the whole transcript."""
        if not self.running:
            return ""
        self._stop.set()
        for thread in (self._reader, self._writer):
            if thread is not None:
                thread.join(timeout=timeout)
        self.started = None
        return "\n\n".join(self.pieces)
