"""Shared, lazily-created OpenAI client.

Created on first use rather than at import time so the app can start (and show
a readable error in the UI) when no API key is configured yet.
"""

from __future__ import annotations

import threading

from openai import OpenAI

from .config import get_api_key

_client: OpenAI | None = None
_lock = threading.Lock()


def get_client() -> OpenAI:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = OpenAI(api_key=get_api_key(), timeout=120.0, max_retries=2)
    return _client


def reset_client() -> None:
    """Drop the cached client so a new key is picked up."""
    global _client
    with _lock:
        _client = None


def rate_limit_message(exc: Exception) -> str:
    """OpenAI returns 429 both for real throttling and for an empty balance.

    They need very different responses from the user, so tell them apart.
    """
    text = str(getattr(exc, "message", None) or exc).lower()
    if "insufficient_quota" in text or "credit" in text or "billing" in text:
        return (
            "Your OpenAI account is out of credits. Add funds at "
            "https://platform.openai.com/settings/organization/billing/ "
            "and try again."
        )
    return "Rate limit reached. Please wait a moment and try again."
