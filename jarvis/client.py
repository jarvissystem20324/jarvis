"""Compatibility shim over the provider registry.

Client construction moved to `jarvis.providers` when JARVIS gained free
backends. This module keeps the old `get_client()` entry point working for code
that specifically wants OpenAI (paid speech, image generation).
"""

from __future__ import annotations

from openai import OpenAI

from . import providers
from .config import get_api_key  # re-exported; callers still import it from here

__all__ = ["get_client", "reset_client", "rate_limit_message", "get_api_key"]


def get_client() -> OpenAI:
    """The OpenAI-proper client. Raises if no OpenAI key is configured."""
    if not providers.has_key(providers.OPENAI):
        raise RuntimeError(
            "OPENAI_API_KEY not set. JARVIS runs on free providers without it — "
            "this path needs a paid OpenAI key specifically."
        )
    return providers.get_client(providers.OPENAI)


def reset_client() -> None:
    """Drop cached clients so a new key is picked up."""
    providers.reset_clients()


def rate_limit_message(exc: Exception) -> str:
    """OpenAI returns 429 both for real throttling and for an empty balance.

    They need very different responses from the user, so tell them apart.
    """
    text = str(getattr(exc, "message", None) or exc).lower()
    if "insufficient_quota" in text or "credit" in text or "billing" in text:
        return (
            "Your OpenAI account is out of credits. JARVIS can run on free "
            "providers instead — see the Providers section of the README."
        )
    return "Rate limit reached. Please wait a moment and try again."
