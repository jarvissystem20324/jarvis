"""Core JARVIS assistant orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import modes, personality, tools
from .addons import AddonManager
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
        self.addons = AddonManager(self)
        self.addons.load_all()

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

            if name == "addons":
                return JarvisResponse(text=self.addons.summary())

            if name == "mode":
                return JarvisResponse(text=self.set_mode(args))

            if name == "code":
                return JarvisResponse(text=self.toggle_code_mode())

            # Addons are dispatched before the offline tools so they can add
            # new commands. They cannot capture a built-in: the loader refuses
            # to register anything in RESERVED_COMMANDS.
            handled = self.addons.handle(name, args)
            if handled is not None:
                if isinstance(handled, JarvisResponse):
                    return handled
                text_out = str(handled)
                self._maybe_speak(text_out)
                return JarvisResponse(text=text_out)

            builtin = tools.try_handle_command(text)
            if builtin is not None:
                if name == "help":
                    builtin = self._with_addon_help(builtin)
                self._maybe_speak(builtin)
                return JarvisResponse(text=builtin)

        reply = self.brain.chat(text, extra_context=self.addons.context_for(text) or None)
        self.addons.notify_reply(text, reply)
        self._maybe_speak(reply)
        return JarvisResponse(text=reply)

    # --- modes ------------------------------------------------------------

    def set_mode(self, args: str) -> str:
        """Show or change the thinking mode."""
        wanted = (args or "").strip().lower()
        if not wanted:
            lines = [f"Mode: {self.brain.mode.label} — {self.brain.mode.blurb}", "", "Available:"]
            for mode in modes.ALL:
                mark = ">" if mode.name == self.brain.mode.name else " "
                lines.append(f"  {mark} {mode.label:<11} {mode.blurb}")
            lines.append("")
            lines.append("Switch with /mode <name>, e.g. /mode high")
            return "\n".join(lines)

        if wanted not in modes.BY_NAME:
            names = ", ".join(m.name for m in modes.ALL)
            return f"No such mode '{wanted}'. Choose one of: {names}"

        mode = self.brain.set_mode(wanted)
        note = ""
        if mode.name == "hyperdrive":
            note = (
                "\n\nHyperdrive reaches for kimi-k3 first and waits up to 200 "
                "seconds. That model often never answers on the free tier, in "
                "which case JARVIS drops back to Max automatically — so the "
                "first reply may take a while."
            )
        return f"Mode set to {mode.label}. {mode.blurb}{note}"

    def toggle_code_mode(self) -> str:
        """Turn the engineering persona on or off."""
        self.brain.code_mode = not self.brain.code_mode
        # system_prompt() reads persona_override, so flipping the flag alone
        # left code mode claiming to be on while the model never saw it.
        self.brain.persona_override = (
            personality.CODE_MODE_PROMPT if self.brain.code_mode else None
        )
        window = getattr(self, "window", None)
        if window is not None:
            try:
                window.after(0, window.refresh_code_mode)
            except Exception:
                pass
        if self.brain.code_mode:
            return (
                "Code mode on. I'll write complete, runnable code, choose an "
                "approach rather than offer a menu, and say what changed. "
                "Use /code again to switch back."
            )
        return "Code mode off. Back to normal conversation."

    def _with_addon_help(self, builtin: str) -> str:
        lines = self.addons.help_lines()
        if not lines:
            return builtin
        return builtin + "\n\nFrom addons:\n" + "\n".join(lines)

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
