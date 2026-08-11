"""Path and environment configuration for dev and frozen EXE builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# --- Model defaults -------------------------------------------------------
# Override any of these in .env without touching the code.
DEFAULT_CHAT_MODEL = "gpt-5.4-mini"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_TTS_VOICE = "onyx"

# 'auto' picks a free backend unless a paid key is configured. See
# jarvis/providers.py for the full chain and its ordering.
DEFAULT_PROVIDER = "auto"
DEFAULT_IMAGE_PROVIDER = "auto"
DEFAULT_STT_PROVIDER = "auto"

_loaded = False


def get_base_dir() -> Path:
    """Directory the app lives in — next to the EXE when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_output_dir() -> Path:
    """Where generated images are written. Created on demand."""
    path = get_base_dir() / "output" / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> None:
    """Load .env from beside the app. Safe to call repeatedly."""
    global _loaded
    if _loaded:
        return
    env_path = get_base_dir() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # fall back to CWD / process env
    _loaded = True


def get_api_key() -> str:
    load_config()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Place a .env file next to the app with your key."
        )
    return key


def get_setting(name: str, default: str) -> str:
    load_config()
    value = os.getenv(name, "").strip()
    return value or default


def get_chat_model() -> str:
    return get_setting("JARVIS_MODEL", DEFAULT_CHAT_MODEL)


def get_provider() -> str:
    return get_setting("JARVIS_PROVIDER", DEFAULT_PROVIDER).lower()


def get_image_provider() -> str:
    return get_setting("JARVIS_IMAGE_PROVIDER", DEFAULT_IMAGE_PROVIDER).lower()


def get_stt_provider() -> str:
    return get_setting("JARVIS_STT_PROVIDER", DEFAULT_STT_PROVIDER).lower()


def get_addons_dir() -> Path:
    """Where addon .py files live. Created on demand."""
    path = get_base_dir() / "addons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    """Writable store for addon state (memory, caches). Created on demand."""
    path = get_base_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_image_model() -> str:
    return get_setting("JARVIS_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)


def get_tts_model() -> str:
    return get_setting("JARVIS_TTS_MODEL", DEFAULT_TTS_MODEL)


def get_stt_model() -> str:
    return get_setting("JARVIS_STT_MODEL", DEFAULT_STT_MODEL)


def get_tts_voice() -> str:
    return get_setting("JARVIS_TTS_VOICE", DEFAULT_TTS_VOICE)


def voice_enabled_by_default() -> bool:
    return get_setting("JARVIS_VOICE", "false").lower() in {"1", "true", "yes", "on"}
