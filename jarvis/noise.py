"""Background sound for studying: white, pink and brown noise, and rain (10.0).

Made, not shipped: thirty seconds of noise are shaped in one FFT and played
on a loop. Noise made that way is periodic by construction, so the loop has
no seam to hear. One stream at a time; play() replaces whatever is playing.
"""

from __future__ import annotations

import threading

import numpy as np

KINDS = ("white", "pink", "brown", "rain")
RATE = 44100
SECONDS = 30


def make(kind: str, seconds: int = SECONDS, seed: int | None = None) -> np.ndarray:
    """A seamless loop of `kind` noise, float32, about -1..1."""
    if kind not in KINDS:
        raise ValueError(f"Kinds: {', '.join(KINDS)}")
    rng = np.random.default_rng(seed)
    n = RATE * seconds
    white = rng.standard_normal(n)
    if kind == "white":
        out = white
    else:
        spectrum = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n, 1 / RATE)
        freqs[0] = freqs[1]
        power = 1.0 if kind == "pink" else 2.0
        spectrum /= freqs ** (power / 2)
        spectrum[freqs < 20] = 0
        out = np.fft.irfft(spectrum, n=n)
    out = out / (out.std() + 1e-12) * 0.18
    if kind == "rain":
        drops = np.zeros(n)
        hits = rng.integers(0, n, size=seconds * 45)
        drops[hits] = rng.uniform(0.15, 0.6, size=hits.size) * rng.choice([-1, 1], size=hits.size)
        kernel = np.exp(-np.arange(90) / 10.0) * np.sin(np.arange(90) * 0.9)
        patter = np.fft.irfft(np.fft.rfft(drops) * np.fft.rfft(kernel, n=n), n=n)
        out = out * 0.9 + patter * 0.5
    return np.clip(out, -1, 1).astype(np.float32)


class NoisePlayer:
    def __init__(self) -> None:
        self.stream = None
        self.kind = ""
        self.volume = 0.3
        self._loop = np.zeros(1, dtype=np.float32)
        self._pos = 0
        self._lock = threading.Lock()

    @property
    def playing(self) -> bool:
        return self.stream is not None

    def take(self, frames: int) -> np.ndarray:
        loop = self._loop
        idx = (self._pos + np.arange(frames)) % len(loop)
        self._pos = (self._pos + frames) % len(loop)
        return loop[idx]

    def play(self, kind: str, volume: float | None = None) -> None:
        import sounddevice as sd

        loop = make(kind)
        self.stop()
        with self._lock:
            self._loop, self._pos, self.kind = loop, 0, kind
            if volume is not None:
                self.volume = max(0.0, min(1.0, volume))

        def callback(outdata, frames, _time, _status):
            with self._lock:
                outdata[:, 0] = self.take(frames) * self.volume

        self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="float32", callback=callback, blocksize=2048)
        self.stream.start()

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self.volume = max(0.0, min(1.0, volume))

    def stop(self) -> None:
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass


player = NoisePlayer()
