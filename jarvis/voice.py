"""Voice input/output for JARVIS.

Speech uses OpenAI's audio models when a key is available, with an offline
pyttsx3 fallback. Playback and recording both run off the calling thread so the
Tk event loop never blocks.
"""

from __future__ import annotations

import io
import re
import threading
import wave

from .config import get_stt_model, get_tts_model, get_tts_voice

try:
    import numpy as np
    import sounddevice as sd

    _HAS_AUDIO = True
except Exception:  # pragma: no cover - depends on host audio stack
    _HAS_AUDIO = False

try:
    import pyttsx3

    _HAS_PYTTSX3 = True
except Exception:  # pragma: no cover
    _HAS_PYTTSX3 = False

# OpenAI PCM speech output is 24 kHz, 16-bit, mono.
TTS_SAMPLE_RATE = 24000
MIC_SAMPLE_RATE = 16000

# Recording behaviour
BLOCK_SIZE = 1024
CALIBRATION_SECONDS = 0.4
START_TIMEOUT_SECONDS = 6.0
SILENCE_SECONDS = 1.2
MAX_RECORD_SECONDS = 30.0
MIN_SPEECH_SECONDS = 0.3


class Voice:
    def __init__(self):
        self._speak_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()
        self._mic_ok = self._probe_mic()
        self._tts_ok = _HAS_AUDIO or _HAS_PYTTSX3
        # Set False after a key/quota failure so we stop paying the network
        # round-trip on every utterance and go straight to offline speech.
        self._openai_tts_ok = _HAS_AUDIO

    # --- capability probing ----------------------------------------------

    @staticmethod
    def _probe_mic() -> bool:
        if not _HAS_AUDIO:
            return False
        try:
            for device in sd.query_devices():
                if device.get("max_input_channels", 0) > 0:
                    return True
        except Exception:
            return False
        return False

    def tts_available(self) -> bool:
        return self._tts_ok

    def mic_available(self) -> bool:
        return self._mic_ok

    def available(self) -> bool:
        return self._tts_ok or self._mic_ok

    # --- text to speech ---------------------------------------------------

    def _strip_markdown(self, text: str) -> str:
        """Markdown reads badly aloud — flatten it before speaking."""
        text = re.sub(r"```[\s\S]*?```", " code block omitted ", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return re.sub(r"\n{2,}", ". ", text).strip()

    def speak(self, text: str, block: bool = False) -> None:
        """Speak `text`. Returns immediately unless `block` is set."""
        clean = self._strip_markdown(text or "")
        if not clean or not self._tts_ok:
            return

        self.stop()
        self._stop_flag.clear()
        thread = threading.Thread(target=self._speak_worker, args=(clean,), daemon=True)
        with self._lock:
            self._speak_thread = thread
        thread.start()
        if block:
            thread.join()

    def stop(self) -> None:
        """Interrupt any in-progress speech."""
        self._stop_flag.set()
        if _HAS_AUDIO:
            try:
                sd.stop()
            except Exception:
                pass
        with self._lock:
            thread = self._speak_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _speak_worker(self, text: str) -> None:
        if self._openai_tts_ok and self._speak_openai(text):
            return
        if not self._stop_flag.is_set():
            self._speak_offline(text)

    def _speak_openai(self, text: str) -> bool:
        """Stream PCM from OpenAI straight into the sound device."""
        try:
            from openai import AuthenticationError, RateLimitError

            from .client import get_client

            with get_client().audio.speech.with_streaming_response.create(
                model=get_tts_model(),
                voice=get_tts_voice(),
                input=text[:4000],
                response_format="pcm",
                instructions=(
                    "Speak in a calm, composed, lightly British tone — "
                    "measured and precise, never theatrical."
                ),
            ) as response:
                pcm = response.read()
        except (AuthenticationError, RateLimitError):
            # No key or no credits — this won't fix itself mid-session.
            self._openai_tts_ok = False
            return False
        except Exception:
            return False

        if self._stop_flag.is_set() or not pcm:
            return True  # treated as handled; nothing more to say

        try:
            samples = np.frombuffer(pcm, dtype=np.int16)
            sd.play(samples, samplerate=TTS_SAMPLE_RATE)
            sd.wait()
        except Exception:
            return False
        return True

    def _speak_offline(self, text: str) -> None:
        if not _HAS_PYTTSX3:
            return
        try:
            # A fresh engine per utterance avoids pyttsx3's "run loop already
            # started" error when speaking from a worker thread.
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            for voice in engine.getProperty("voices") or []:
                name = (voice.name or "").lower()
                if "david" in name or "mark" in name or "male" in name:
                    engine.setProperty("voice", voice.id)
                    break
            engine.say(text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
        except Exception:
            pass

    # --- speech to text ---------------------------------------------------

    def listen(self, duration: float | None = None) -> str | None:
        """Record a phrase and transcribe it. Returns None if nothing was heard."""
        if not self._mic_ok:
            return None
        try:
            pcm = self._record(duration)
        except Exception as exc:
            raise RuntimeError(f"Microphone error: {exc}") from None

        if not pcm:
            return None

        try:
            return self._transcribe(self._to_wav(pcm))
        except Exception as exc:
            raise RuntimeError(f"Speech recognition unavailable: {exc}") from None

    def _record(self, duration: float | None = None) -> bytes:
        """Record until the speaker stops, or for a fixed `duration` if given."""
        chunks: list[bytes] = []
        max_seconds = duration or MAX_RECORD_SECONDS

        with sd.InputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=BLOCK_SIZE,
        ) as stream:
            block_seconds = BLOCK_SIZE / MIC_SAMPLE_RATE
            elapsed = 0.0
            silence = 0.0
            speech = 0.0
            started = False
            noise_floor = 0.0
            calibration: list[float] = []

            while elapsed < max_seconds:
                block, _overflowed = stream.read(BLOCK_SIZE)
                chunks.append(bytes(block))
                elapsed += block_seconds

                if duration is not None:
                    continue  # fixed-length capture: skip endpointing

                level = float(np.sqrt(np.mean(np.square(block.astype(np.float32)))))

                if elapsed <= CALIBRATION_SECONDS:
                    calibration.append(level)
                    continue
                if noise_floor == 0.0:
                    noise_floor = max(sum(calibration) / max(len(calibration), 1), 1.0)

                threshold = max(noise_floor * 3.0, 250.0)

                if level > threshold:
                    started = True
                    speech += block_seconds
                    silence = 0.0
                elif started:
                    silence += block_seconds
                    if silence >= SILENCE_SECONDS:
                        break
                elif elapsed >= START_TIMEOUT_SECONDS:
                    return b""  # nobody spoke

            if duration is None and (not started or speech < MIN_SPEECH_SECONDS):
                return b""

        return b"".join(chunks)

    @staticmethod
    def _to_wav(pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(MIC_SAMPLE_RATE)
            wav.writeframes(pcm)
        return buffer.getvalue()

    @staticmethod
    def _transcribe(wav_bytes: bytes) -> str | None:
        from .client import get_client

        buffer = io.BytesIO(wav_bytes)
        buffer.name = "speech.wav"  # the SDK infers the format from the name
        result = get_client().audio.transcriptions.create(
            model=get_stt_model(),
            file=buffer,
        )
        text = (getattr(result, "text", "") or "").strip()
        return text or None
