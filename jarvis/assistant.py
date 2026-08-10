"""Core JARVIS assistant orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import personality, tools
from .brain import Brain
from .config import voice_enabled_by_default
from .images import DEFAULT_QUALITY, ImageGenerationError, ImageGenerator
from .voice import Voice


@dataclass
class JarvisResponse:
    text: str
    image_path: Path | None = None
    should_quit: bool = False


class Jarvis:
    def __init__(self, voice_enabled: bool | None = None):
        self.brain = Brain()
        self.images = ImageGenerator()
        self.voice = Voice()
        if voice_enabled is None:
            voice_enabled = voice_enabled_by_default()
        self.voice_enabled = bool(voice_enabled) and self.voice.available()

    def greet(self) -> str:
        text = personality.greeting()
        self._maybe_speak(text)
        return text

    def farewell(self) -> str:
        text = personality.FAREWELL
        if self.voice_enabled:
            self.voice.speak(text, block=True)
        return text

    def toggle_voice(self) -> str:
        if not self.voice.available():
            return "Voice module unavailable."

        self.voice_enabled = not self.voice_enabled
        if not self.voice_enabled:
            self.voice.stop()

        parts = []
        if self.voice.tts_available():
            parts.append("speech output")
        if self.voice.mic_available():
            parts.append("microphone input")
        state = "enabled" if self.voice_enabled else "disabled"
        return f"Voice mode {state} ({' and '.join(parts) or 'voice'})."

    def generate_image(
        self, prompt: str, size: str = "1024x1024", quality: str = DEFAULT_QUALITY
    ) -> JarvisResponse:
        try:
            path = self.images.generate(prompt, size=size, quality=quality)
        except ImageGenerationError as exc:
            return JarvisResponse(text=str(exc))

        self._maybe_speak("Image generated, sir.")
        return JarvisResponse(
            text=f"Image generated successfully.\nSaved to: {path}",
            image_path=path,
        )

    def process(self, user_input: str) -> JarvisResponse:
        text = (user_input or "").strip()
        if not text:
            return JarvisResponse(text="I didn't catch that. Could you repeat?")

        if text.startswith("/"):
            name, _, args = text[1:].strip().partition(" ")
            name = name.lower()

            if name in {"quit", "exit"}:
                return JarvisResponse(text=self.farewell(), should_quit=True)

            if name == "clear":
                self.brain.clear_history()
                return JarvisResponse(text="Conversation history cleared.")

            if name == "voice":
                return JarvisResponse(text=self.toggle_voice())

            if name == "image":
                if not args.strip():
                    return JarvisResponse(
                        text="Usage: /image <prompt>\n"
                        "Example: /image a futuristic AI lab at night"
                    )
                return self.generate_image(args)

            builtin = tools.try_handle_command(text)
            if builtin is not None:
                self._maybe_speak(builtin)
                return JarvisResponse(text=builtin)

        reply = self.brain.chat(text)
        self._maybe_speak(reply)
        return JarvisResponse(text=reply)

    def listen_and_respond(self) -> JarvisResponse | None:
        if not self.voice_enabled:
            return JarvisResponse(text="Voice mode is disabled. Use /voice to enable it.")
        if not self.voice.mic_available():
            return JarvisResponse(
                text="Microphone unavailable. You can still hear my responses."
            )

        # Don't record our own voice.
        self.voice.stop()
        try:
            heard = self.voice.listen()
        except RuntimeError as exc:
            return JarvisResponse(text=str(exc))

        if not heard:
            return JarvisResponse(text="I didn't hear anything. Please try again.")
        return self.process(heard)

    def _maybe_speak(self, text: str) -> None:
        if self.voice_enabled and self.voice.tts_available():
            self.voice.speak(text)
