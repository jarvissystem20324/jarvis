"""Screen vision — JARVIS looks at your screen and describes what it sees.

Captures with Pillow's ImageGrab (no extra dependency on Windows), downscales
so the upload stays small, and sends it to whichever provider is answering.
Vision needs a model that accepts images: Gemini and OpenAI both do, Groq's
text models do not.

The screenshot is sent to your AI provider. It is not stored anywhere unless
you pass --save.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime

from jarvis.addons import Addon, Command
from jarvis.config import get_output_dir

# Long edge in pixels. Big enough to read most on-screen text, small enough
# that the upload isn't slow.
MAX_EDGE = 1400


class ScreenVision(Addon):
    name = "screen-vision"
    version = "1.0"
    description = "Screenshots your screen and describes it."

    def commands(self):
        return [
            Command("see", self.see, "Describe what's on screen", "/see [question]"),
            Command("read", self.read_screen, "Read the text on screen", "/read"),
        ]

    # --- capture ----------------------------------------------------------

    @staticmethod
    def _grab():
        try:
            from PIL import ImageGrab
        except ImportError:
            raise RuntimeError("Pillow isn't available, so I can't capture the screen.")

        image = ImageGrab.grab()
        if image is None:
            raise RuntimeError("The screen capture came back empty.")

        width, height = image.size
        longest = max(width, height)
        if longest > MAX_EDGE:
            scale = MAX_EDGE / longest
            image = image.resize((int(width * scale), int(height * scale)))
        return image

    @staticmethod
    def _encode(image) -> str:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    # --- commands ---------------------------------------------------------

    def see(self, ctx, args: str) -> str:
        question = args.strip()
        save = "--save" in question
        question = question.replace("--save", "").strip()

        try:
            image = self._grab()
        except Exception as exc:
            return f"Couldn't capture the screen: {exc}"

        saved_note = ""
        if save:
            path = get_output_dir() / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
            image.save(path)
            saved_note = f"\n\n(Saved to {path})"

        prompt = question or (
            "Describe what is on this screen concisely. Mention any visible "
            "error messages or dialogs first."
        )
        answer = ctx.ask(prompt, image_b64=self._encode(image))
        return answer + saved_note

    def read_screen(self, ctx, args: str) -> str:
        try:
            image = self._grab()
        except Exception as exc:
            return f"Couldn't capture the screen: {exc}"

        return ctx.ask(
            "Transcribe all readable text in this image. Output only the text, "
            "preserving line breaks. If there is no text, say so.",
            image_b64=self._encode(image),
        )


ADDON = ScreenVision()
