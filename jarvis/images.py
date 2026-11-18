"""Image generation for JARVIS.

Three backends, tried best-free-first.

FLUX.1-dev on NVIDIA is the default when an NVIDIA key is present, because
it is a real step up in quality and costs nothing on a key most people
already have for chat. Pollinations is the backstop: it is the only one
that needs no account at all, which is what makes image generation work on
a completely fresh install. OpenAI's gpt-image family is used only when
`JARVIS_IMAGE_PROVIDER=openai` is set explicitly, because having a key on
file is not consent to bill it.

Gemini's image models are deliberately not offered. They are listed on the
key and answer every request with HTTP 429 and 'limit: 0' on the free
tier, so wiring them up would mean shipping a button that never works.

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

from . import net, providers, safety
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
# With a free key (sk_… or plln_…, enter.pollinations.ai/keys): POLLINATIONS_API_KEY.
POLLINATIONS_KEYED_URL = "https://gen.pollinations.ai/image/"

# FLUX.1 schnell on Cloudflare Workers AI: 3 s, on the Cloudflare chat token.
CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
CLOUDFLARE_TIMEOUT = 60
POLLINATIONS_TIMEOUT = 180  # Flux can be slow when the free tier is busy

# FLUX.1-dev on NVIDIA. Free on the same key that drives Max mode, and a
# clear step up in quality from the anonymous Pollinations endpoint.
FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
FLUX_TIMEOUT = 150


class ImageGenerationError(RuntimeError):
    """Raised when an image could not be produced."""


MAX_UPSCALED_SIDE = 8192


def upscale(path: Path, factor: int = 2) -> Path:
    """Image Studio 2.0: a bigger copy of a picture, made on this PC.

    Lanczos resampling with a light unsharp mask — not an AI upscaler, so it
    adds no detail that wasn't there, but edges stay clean and nothing is
    uploaded. The original is never changed; the result is a new file.
    """
    from PIL import Image, ImageFilter

    factor = max(2, min(4, int(factor)))
    with Image.open(path) as source:
        image = source.convert("RGBA" if source.mode in {"RGBA", "LA", "P"} else "RGB")
    width, height = image.width * factor, image.height * factor
    if max(width, height) > MAX_UPSCALED_SIDE:
        ratio = MAX_UPSCALED_SIDE / max(width, height)
        width, height = int(width * ratio), int(height * ratio)
    bigger = image.resize((width, height), Image.LANCZOS)
    bigger = bigger.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2))
    target = path.with_name(f"{path.stem}_x{factor}.png")
    n = 2
    while target.exists():
        target = path.with_name(f"{path.stem}_x{factor}-{n}.png")
        n += 1
    bigger.save(target)
    return target


class ImageGenerator:
    def __init__(self, model: str | None = None):
        self.model = model or get_image_model()

    # --- entry point ------------------------------------------------------

    def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = DEFAULT_QUALITY,
        seed: int | None = None,
    ) -> Path:
        """Generate one image. A different `seed` gives a different picture
        of the same prompt, which is what /vary relies on — with the seed
        fixed at 0, asking twice returned the identical image."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageGenerationError("Please enter an image prompt.")
        # 10.0.2: every image passes here, whoever wrote the prompt (you, or
        # a model improving it) and whichever backend draws it.
        refused = safety.image_refusal_for(prompt)
        if refused:
            raise ImageGenerationError(refused)
        prompt = safety.modest(prompt)
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS]

        size = SIZES.get(size, size)
        if size not in SIZES.values():
            size = "1024x1024"
        if quality not in QUALITIES:
            quality = DEFAULT_QUALITY

        if seed is None:
            import random

            seed = random.randint(1, 2_000_000_000)
        data = self._render(prompt, size, quality, seed)

        path = self._free_path(get_output_dir() / self._filename(prompt, data))
        path.write_bytes(data)
        return path

    @staticmethod
    def _free_path(path: Path) -> Path:
        """Never overwrite an existing image.

        The name carries a one-second timestamp, so generating the same prompt
        twice inside the same second produced the same filename and the second
        image silently replaced the first.
        """
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        for counter in range(2, 1000):
            candidate = path.with_name(f"{stem}-{counter}{suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{stem}-{datetime.now():%f}{suffix}")

    def _render(self, prompt: str, size: str, quality: str, seed: int = 0) -> bytes:
        """Produce the image, the most reliable free backend first.

        Measured on 2026-11-18 (10.5.3):
        - Cloudflare Workers AI, FLUX.1 schnell: 3 s, 10,000 free units a day
          on the same token as Cloudflare chat. First, when it has a key.
        - NVIDIA FLUX.1-dev: had failed every request since NVIDIA stopped
          accepting a "seed" (422), so every image fell to Pollinations.
        - Pollinations without a key now allows one image every 45 s per IP
          (402) and answers 503 under load: the "free image service
          unavailable" friends kept seeing. With a free key (sk_/plln_) it has its
          own limits; without one it is the last resort, tried twice.

        Gemini's image models are deliberately absent: on free keys they
        answer 429 to every request.
        """
        if self._use_openai():
            try:
                return self._generate_openai(prompt, size, quality)
            except ImageGenerationError:
                # Paid backend unavailable (no credit, bad key). Rather than
                # hand back an error, quietly produce the image for free.
                pass

        wanted = get_image_provider()
        problems: list[str] = []
        attempts = [
            ("Cloudflare", {"auto", "cloudflare"}, self._cloudflare_ready, self._generate_cloudflare),
            ("NVIDIA FLUX", {"auto", "nvidia", "flux"}, self._nvidia_ready, self._generate_flux),
        ]
        for label, names, ready, generate in attempts:
            if wanted in names and ready():
                try:
                    return generate(prompt, size, seed)
                except ImageGenerationError as exc:
                    problems.append(f"{label}: {exc}")
        try:
            return self._generate_pollinations(prompt, size, seed)
        except ImageGenerationError as exc:
            problems.append(f"Pollinations: {exc}")
        raise ImageGenerationError(
            "No free image service could make it right now.\n"
            + "\n".join(f"  • {p}" for p in problems)
            + "\n\nThe reliable free fix: a Cloudflare token (Settings → Cloudflare Workers AI; 10,000 free "
              "units a day, no card), or a free Pollinations key (Settings → Pollinations, from "
              "enter.pollinations.ai/keys)."
        )

    @staticmethod
    def _cloudflare_ready() -> bool:
        cloudflare = providers.BY_NAME.get("cloudflare")
        return cloudflare is not None and providers.has_key(cloudflare)

    @staticmethod
    def _nvidia_ready() -> bool:
        nvidia = providers.BY_NAME.get("nvidia")
        return nvidia is not None and providers.has_key(nvidia)

    def _generate_cloudflare(self, prompt: str, size: str, seed: int = 0) -> bytes:
        """FLUX.1 schnell on Cloudflare Workers AI (1024×1024; it takes no size)."""
        import json
        import os

        account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        request = net.request(f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{CLOUDFLARE_MODEL}", {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('CLOUDFLARE_API_TOKEN', '').strip()}",
        })
        request.data = json.dumps({"prompt": prompt[:2048], "steps": 4, "seed": int(seed) % 2_147_483_647}).encode()
        try:
            with net.urlopen(request, timeout=CLOUDFLARE_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ImageGenerationError("today's free allowance is used up (it resets daily)") from None
            raise ImageGenerationError(f"HTTP {exc.code}") from None
        except Exception as exc:
            raise ImageGenerationError(f"unreachable ({exc})") from None
        encoded = (body.get("result") or {}).get("image")
        if not encoded:
            raise ImageGenerationError("no image in the reply")
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            raise ImageGenerationError("an image that couldn't be decoded") from None

    def _generate_flux(self, prompt: str, size: str, seed: int = 0) -> bytes:
        """FLUX.1-dev through NVIDIA's generative endpoint."""
        import json
        import os

        width, height = (1024, 1024) if size == "auto" else map(int, size.split("x"))
        # It takes only 768–1344 in steps of 64 and rejects anything else
        # outright; and since November 2026 it rejects "seed" too (422 on
        # every request, so every image had fallen through to Pollinations).
        width, height = (min(1344, max(768, w - w % 64)) for w in (width, height))

        payload = json.dumps({
            "prompt": prompt,
            "mode": "base",
            "cfg_scale": 3.5,
            "width": width,
            "height": height,
            "steps": 30,
        }).encode("utf-8")

        request = net.request(FLUX_URL, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('NVIDIA_API_KEY', '').strip()}",
            "Accept": "application/json",
        })
        request.data = payload
        try:
            with net.urlopen(request, timeout=FLUX_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ImageGenerationError(f"FLUX returned HTTP {exc.code}.") from None
        except Exception as exc:
            raise ImageGenerationError(f"FLUX was unreachable: {exc}") from None

        encoded = body.get("image")
        if not encoded:
            artifacts = body.get("artifacts") or []
            encoded = artifacts[0].get("base64") if artifacts else None
        if not encoded:
            raise ImageGenerationError("FLUX returned no image.")
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            raise ImageGenerationError("FLUX returned an image I couldn't decode.")

    @staticmethod
    def _use_openai() -> bool:
        """Only spend money when explicitly told to.

        'auto' deliberately means free: having an OpenAI key on file is not
        consent to bill it for every image, and a key with an empty balance is
        the common case here.
        """
        return get_image_provider() == "openai"

    # --- free backend -----------------------------------------------------

    def _generate_pollinations(self, prompt: str, size: str, seed: int = 0) -> bytes:
        width, height = (1024, 1024) if size == "auto" else map(int, size.split("x"))
        query = urllib.parse.urlencode(
            {
                "width": width,
                "height": height,
                "model": "flux",
                "nologo": "true",
                # Pollinations' own filter, on top of the prompt check.
                "safe": "true",
                "referrer": providers.REFERRER,
                "seed": int(seed),
            }
        )
        import os
        import time

        key = os.getenv("POLLINATIONS_API_KEY", "").strip()
        if key:
            # The keyed service: its own limits, not the shared anonymous ones.
            request = net.request(f"{POLLINATIONS_KEYED_URL}{urllib.parse.quote(prompt, safe='')}?{query}",
                                  {"Authorization": f"Bearer {key}"})
        else:
            request = f"{POLLINATIONS_URL}{urllib.parse.quote(prompt, safe='')}?{query}"

        data = b""
        for attempt in range(2):
            try:
                with net.urlopen(request, timeout=POLLINATIONS_TIMEOUT) as response:
                    data = response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 and attempt == 0:
                    time.sleep(3)          # 503 under load often clears in a moment
                    continue
                if exc.code in (402, 429):
                    raise ImageGenerationError(
                        "the free tier without a key allows one image every 45 seconds"
                        if not key else "this key's limit is reached for now") from None
                if exc.code == 401:
                    raise ImageGenerationError("the Pollinations key was refused") from None
                raise ImageGenerationError(f"HTTP {exc.code}, busy or down") from None
            except (urllib.error.URLError, OSError) as exc:
                explanation = net.describe_ssl_error(exc)
                raise ImageGenerationError(explanation or f"unreachable ({exc})") from None

        if not self._looks_like_image(data):
            # The service answers errors with HTML/JSON at HTTP 200.
            raise ImageGenerationError("it sent an error page instead of an image")
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
                with net.urlopen(url, timeout=60) as resp:
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
