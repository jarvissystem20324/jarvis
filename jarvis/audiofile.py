"""Audio files as numbers (10.0): read anything Windows can play, write WAV,
MP3 or M4A, and transcribe a whole recording.

Decoding goes through Windows' own media engine (winrt.transcode) into WAV,
which the standard library reads; the editing is numpy. So noise reduction,
silence removal, ringtones and lecture notes from a file need no ffmpeg.
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

from . import winrt

NATIVE = {".wav"}


def load(path: Path) -> tuple[np.ndarray, int]:
    """(mono float32 samples in -1..1, sample rate)."""
    path = Path(path)
    if path.suffix.lower() not in NATIVE:
        temp = Path(tempfile.mkdtemp(prefix="jarvis-audio-")) / "decoded.wav"
        winrt.transcode(path, temp)
        path = temp
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / 8388608.0
    else:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    if rate == target or len(samples) == 0:
        return samples
    count = int(round(len(samples) * target / rate))
    old = np.linspace(0, 1, num=len(samples), endpoint=False)
    new = np.linspace(0, 1, num=count, endpoint=False)
    return np.interp(new, old, samples).astype(np.float32)


def save(samples: np.ndarray, rate: int, path: Path) -> Path:
    """WAV directly; MP3/M4A through Windows' encoder."""
    path = Path(path)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype("<i2").tobytes()
    wav_path = path if path.suffix.lower() == ".wav" else Path(tempfile.mkdtemp(prefix="jarvis-audio-")) / "out.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    if wav_path != path:
        winrt.transcode(wav_path, path)
    return path


def duration(samples: np.ndarray, rate: int) -> float:
    return len(samples) / float(rate or 1)


def transcribe(voice, path: Path, chunk_seconds: int = 480) -> str:
    """The whole recording as text, in pieces the speech-to-text API accepts."""
    samples, rate = load(path)
    samples = resample(samples, rate, 16000)
    if not len(samples):
        return ""
    texts = []
    step = chunk_seconds * 16000
    for start in range(0, len(samples), step):
        piece = samples[start:start + step]
        if np.abs(piece).max(initial=0) < 0.01:
            continue
        pcm = (np.clip(piece, -1, 1) * 32767).astype("<i2").tobytes()
        text = voice._transcribe(pcm)
        if text:
            texts.append(text.strip())
    return "\n".join(texts)
