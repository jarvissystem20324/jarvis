"""Image generation for JARVIS.

Two backends. Pollinations needs no account and is the default, so image
generation works out of the box; OpenAI's gpt-image family is used instead when
a key is present and `JARVIS_IMAGE_PROVIDER=openai` is set, trading money for
noticeably better results.

dall-e-3 was retired on 2026-03-04 and no longer serves requests, so it is not
offered.
"""

from __future__ import annotations

import base64
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from . import providers
from .config import get_image_model, get_image_provider, get_output_dir

# Labels shown in the UI -> pixel sizes.
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

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"
POLLINATIONS_TIMEOUT = 180  # Flux can be slow when the free tier is busy


class ImageGenerationError(RuntimeError):
    """Raised when an image could not be produced."""


class ImageGenerator:
    def __init__(self, model: str | None = None):
        self.model = model or get_image_model()

    # --- entry point ------------------------------------------------------

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

        if self._use_openai():
            try:
                data = self._generate_openai(prompt, size, quality)
            except ImageGenerationError:
                # Paid backend unavailable (no credit, bad key). Rather than
                # hand back an error, quietly produce the image for free.
                data = self._generate_pollinations(prompt, size)
        else:
            data = self._generate_pollinations(prompt, size)

        path = get_output_dir() / self._filename(prompt, data)
        path.write_bytes(data)
        return path

    @staticmethod
    def _use_openai() -> bool:
        """Only spend money when explicitly told to.

        'auto' deliberately means free: having an OpenAI key on file is not
        consent to bill it for every image, and a key with an empty balance is
        the common case here.
        """
        return get_image_provider() == "openai"

    # --- free backend -----------------------------------------------------

    def _generate_pollinations(self, prompt: str, size: str) -> bytes:
        width, height = (1024, 1024) if size == "auto" else map(int, size.split("x"))
        query = urllib.parse.urlencode(
            {
                "width": width,
                "height": height,
                "model": "flux",
                "nologo": "true",
                "referrer": providers.REFERRER,
            }
        )
        url = f"{POLLINATIONS_URL}{urllib.parse.quote(prompt, safe='')}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "JARVIS"})

        try:
            with urllib.request.urlopen(request, timeout=POLLINATIONS_TIMEOUT) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ImageGenerationError(
                    "The free image service is rate limiting us — it allows "
                    "roughly one image every 15 seconds. Wait a moment and try "
                    "again."
                ) from None
            raise ImageGenerationError(
                f"Free image service returned HTTP {exc.code}. Try again shortly."
            ) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ImageGenerationError(
                f"Can't reach the image service: {exc}. Check your connection."
            ) from None

        if not self._looks_like_image(data):
            # The service answers errors with HTML/JSON at HTTP 200.
            raise ImageGenerationError(
                "The free image service returned an error instead of an image. "
                "Try a different prompt, or wait a moment."
            )
        return data

    # --- paid backend -----------------------------------------------------

    def _generate_openai(self, prompt: str, size: str, quality: str) -> bytes:
        try:
            response = providers.get_client(providers.OPENAI).images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )
        except AuthenticationError:
            raise ImageGenerationError(
                "OpenAI rejected the key. Set JARVIS_IMAGE_PROVIDER=pollinations "
                "in .env to use the free image service instead."
            ) from None
        except RateLimitError:
            raise ImageGenerationError(
                "Your OpenAI account is rate limited or out of credit. Set "
                "JARVIS_IMAGE_PROVIDER=pollinations in .env to generate images "
                "for free instead."
            ) from None
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
        return self._extract_bytes(response.data[0])

    @staticmethod
    def _extract_bytes(item) -> bytes:
        """gpt-image-* return base64; some gateways return a short-lived URL."""
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

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        return data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF", b"GIF8"))

    @staticmethod
    def _extension(data: bytes) -> str:
        """Pollinations answers with JPEG, OpenAI with PNG — trust the bytes."""
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if data.startswith(b"RIFF"):
            return ".webp"
        if data.startswith(b"GIF8"):
            return ".gif"
        return ".png"

    @classmethod
    def _filename(cls, prompt: str, data: bytes) -> str:
        """Timestamped name with a short slug so files are recognisable."""
        slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40].strip("-")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = cls._extension(data)
        return f"jarvis_{stamp}_{slug}{suffix}" if slug else f"jarvis_{stamp}{suffix}"
