"""Voice input/output for JARVIS.

Speech out prefers OpenAI's voices when a paid key is present and falls back to
the offline Windows voices, so it always works. Speech in walks the provider
chain — Groq's Whisper is free — and can use a locally installed faster-whisper
for full offline transcription. Playback and recording both run off the calling
thread so the Tk event loop never blocks.
"""

from __future__ import annotations

import io
import re
import threading
import wave

from . import providers
from .config import get_stt_provider, get_tts_model, get_tts_voice

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
        # Without an OpenAI key there is nothing to try in the first place.
        self._openai_tts_ok = _HAS_AUDIO and providers.has_key(providers.OPENAI)
        self._local_stt = None  # lazily loaded faster-whisper model

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

        return self._transcribe(pcm)

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

    def stt_available(self) -> bool:
        """True when something can turn speech into text."""
        return bool(providers.stt_chain()) or self._local_stt_installed()

    def _transcribe(self, pcm: bytes) -> str | None:
        """Try each transcription backend until one produces text."""
        choice = get_stt_provider()
        problems: list[str] = []

        if choice != "local":
            wav = self._to_wav(pcm)
            chain = providers.stt_chain()
            if choice not in {"auto", ""}:
                chain = [p for p in chain if p.name == choice] or chain
            for provider in chain:
                try:
                    return self._transcribe_remote(provider, wav)
                except Exception as exc:
                    problems.append(f"{provider.label}: {self._brief(exc)}")

        # Local Whisper needs no key and no network, but only if installed.
        if self._local_stt_installed():
            try:
                return self._transcribe_local(pcm)
            except Exception as exc:
                problems.append(f"local Whisper: {self._brief(exc)}")

        raise RuntimeError(self._stt_help(problems))

    @staticmethod
    def _transcribe_remote(provider, wav_bytes: bytes) -> str | None:
        buffer = io.BytesIO(wav_bytes)
        buffer.name = "speech.wav"  # the SDK infers the format from the name
        result = providers.get_client(provider).audio.transcriptions.create(
            model=providers.stt_model_for(provider),
            file=buffer,
        )
        text = (getattr(result, "text", "") or "").strip()
        return text or None

    def _transcribe_local(self, pcm: bytes) -> str | None:
        """Transcribe with faster-whisper, entirely offline.

        Audio is handed over as a float32 array rather than a file so
        faster-whisper never reaches for its PyAV decoding path.
        """
        if self._local_stt is None:
            from faster_whisper import WhisperModel

            from .config import get_setting

            size = get_setting("JARVIS_WHISPER_MODEL", "base")
            # int8 keeps it usable on a CPU-only machine.
            self._local_stt = WhisperModel(size, device="cpu", compute_type="int8")

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._local_stt.transcribe(samples, language=None)
        text = " ".join(segment.text for segment in segments).strip()
        return text or None

    @staticmethod
    def _local_stt_installed() -> bool:
        import importlib.util

        return importlib.util.find_spec("faster_whisper") is not None

    @staticmethod
    def _brief(exc: Exception) -> str:
        text = str(getattr(exc, "message", None) or exc).strip()
        low = text.lower()
        if "api key" in low or "unauthorized" in low or "invalid_api_key" in low:
            return "key rejected"
        if "rate" in low and "limit" in low:
            return "rate limited"
        return text[:90] or exc.__class__.__name__

    @staticmethod
    def _stt_help(problems: list[str]) -> str:
        detail = ("\n" + "\n".join(f"  - {p}" for p in problems)) if problems else ""
        return (
            "No speech-to-text backend is available." + detail + "\n\n"
            "Add a free Groq key to .env for transcription:\n"
            "  GROQ_API_KEY=...  (https://console.groq.com/keys)\n"
            "Or install faster-whisper to transcribe offline:\n"
            "  pip install faster-whisper"
        )
