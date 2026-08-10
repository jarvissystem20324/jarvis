"""Image generation for JARVIS.

Uses the gpt-image family. Note that dall-e-3 was retired on 2026-03-04 and no
longer serves requests, so it is not offered as an option here.
"""

from __future__ import annotations

import base64
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from openai import APIError, APIConnectionError, AuthenticationError, RateLimitError

from .client import get_client, rate_limit_message
from .config import get_image_model, get_output_dir

# Labels shown in the UI -> API size values.
SIZES: dict[str, str] = {
    "Square (1024x1024)": "1024x1024",
    "Portrait (1024x1536)": "1024x1536",
    "Landscape (1536x1024)": "1536x1024",
    "Auto (model decides)": "auto",
}

# 'high' runs a four-stage understand/plan/generate/review pass and is far
# slower than the others — medium is the sane default for an interactive app.
QUALITIES = ("auto", "low", "medium", "high")
DEFAULT_QUALITY = "medium"

MAX_PROMPT_CHARS = 4000


class ImageGenerationError(RuntimeError):
    """Raised when an image could not be produced."""


class ImageGenerator:
    def __init__(self, model: str | None = None):
        self.model = model or get_image_model()

    def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = DEFAULT_QUALITY,
    ) -> Path:
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageGenerationError("Please enter an image prompt.")
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS]

        size = SIZES.get(size, size)
        if size not in SIZES.values():
            size = "1024x1024"
        if quality not in QUALITIES:
            quality = DEFAULT_QUALITY

        try:
            response = get_client().images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )
        except AuthenticationError:
            raise ImageGenerationError(
                "Authentication failed. Check OPENAI_API_KEY in your .env file."
            ) from None
        except RateLimitError as exc:
            raise ImageGenerationError(rate_limit_message(exc)) from None
        except APIConnectionError:
            raise ImageGenerationError(
                "Can't reach OpenAI. Check your internet connection."
            ) from None
        except APIError as exc:
            raise ImageGenerationError(
                f"Image generation failed: {getattr(exc, 'message', None) or exc}"
            ) from None

        if not response.data:
            raise ImageGenerationError("No image was returned from OpenAI.")

        data = self._extract_bytes(response.data[0])
        path = get_output_dir() / self._filename(prompt)
        path.write_bytes(data)
        return path

    @staticmethod
    def _extract_bytes(item) -> bytes:
        """gpt-image-* return base64; dall-e-* return a short-lived URL."""
        b64 = getattr(item, "b64_json", None)
        if b64:
            # Some gateways hand back a data: URI rather than bare base64.
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[-1]
            return base64.b64decode(b64)

        url = getattr(item, "url", None)
        if url:
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    return resp.read()
            except OSError as exc:
                raise ImageGenerationError(f"Could not download the image: {exc}") from None

        raise ImageGenerationError("No image data was returned from OpenAI.")

    @staticmethod
    def _filename(prompt: str) -> str:
        """Timestamped name with a short slug so files are recognisable."""
        slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40].strip("-")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"jarvis_{stamp}_{slug}.png" if slug else f"jarvis_{stamp}.png"
