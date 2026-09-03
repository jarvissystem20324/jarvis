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


IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


def get_app_dir() -> Path:
    """Where the application itself lives — read-only once installed."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_base_dir() -> Path:
    """Root for everything the app writes: .env, addons, images, addon state.

    On Windows this stays beside the EXE, which keeps existing installs
    working and keeps the app portable on a USB stick.

    On macOS it must NOT be beside the executable. A frozen build lives at
    JARVIS.app/Contents/MacOS/JARVIS, so writing next to it means writing
    inside the bundle — which invalidates the code signature and gets the app
    refused by Gatekeeper, quite apart from /Applications often not being
    user-writable. Apple's answer is Application Support, so use that.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent

    if IS_MACOS:
        home = Path.home() / "Library" / "Application Support" / "JARVIS"
        home.mkdir(parents=True, exist_ok=True)
        return home
    if not IS_WINDOWS:
        home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jarvis"
        home.mkdir(parents=True, exist_ok=True)
        return home
    return Path(sys.executable).parent


def get_bundled_dir() -> Path:
    """Read-only resources shipped inside the build (addons, assets)."""
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def get_output_dir() -> Path:
    """Where generated images are written. Created on demand."""
    path = get_base_dir() / "output" / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _seed_env(env_path: Path) -> None:
    """Put a starter .env in place on first run.

    Windows gets one written by the installer. macOS has no installer — the
    app is dragged to /Applications — so without this the user has nowhere
    obvious to put their key.
    """
    if env_path.exists() or not getattr(sys, "frozen", False):
        return
    template = get_bundled_dir() / ".env.example"
    try:
        if template.is_file():
            env_path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def load_config() -> None:
    """Load .env from the writable data directory. Safe to call repeatedly."""
    global _loaded
    if _loaded:
        return
    env_path = get_base_dir() / ".env"
    _seed_env(env_path)
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
