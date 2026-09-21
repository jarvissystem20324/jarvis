"""Bring an older .env up to date when JARVIS updates.

Updating the program does nothing for a settings file written by an earlier
version. A 2.5-era .env has one OpenAI key, model settings that are no longer
read, and none of the free providers added since — so the app updates cleanly
and then still cannot answer. This closes that gap.

Three rules, in order of importance:

  1. An existing value is never changed. Keys especially: nothing here can
     overwrite, reorder or delete a key the user put in, and no value is ever
     printed or logged.
  2. Settings that are no longer read are commented out rather than deleted,
     so nothing is silently lost and the user can see what happened.
  3. The previous file is copied aside before anything is written.

Everything else is additive: missing settings are appended with a blank value
and a line explaining where to get one.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

# (name, default, comment) appended when missing. Blank defaults on purpose —
# a key is the user's to provide.
EXPECTED: tuple[tuple[str, str, str], ...] = (
    ("GEMINI_API_KEY", "", "Free. The only provider that can see images (/see, /read).\n# https://aistudio.google.com/apikey"),
    ("GROQ_API_KEY", "", "Free, fastest, also does speech-to-text.\n# https://console.groq.com/keys"),
    ("INCEPTION_API_KEY", "", "Free, 100M tokens, ~1s replies. Powers Mid mode.\n# https://platform.inceptionlabs.ai"),
    ("NVIDIA_API_KEY", "", "Free.\n# https://build.nvidia.com"),
    ("JARVIS_PROVIDER", "auto", "auto | gemini | groq | inception | nvidia | openai"),
    ("JARVIS_IMAGE_PROVIDER", "auto", "'auto' means free — an OpenAI key is not consent to bill it."),
    ("JARVIS_STT_PROVIDER", "auto", "auto | groq | openai | local"),
    ("JARVIS_HOTKEY", "ctrl+alt+j", "Global shortcut to summon the window (Windows)."),
)

# Read by versions up to 2.5 and ignored since. Commented out, not removed.
OBSOLETE: tuple[str, ...] = (
    "JARVIS_MODEL",
    "JARVIS_IMAGE_MODEL",
    "JARVIS_TTS_MODEL",
    "JARVIS_STT_MODEL",
)

_SETTING = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _present(lines: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        match = _SETTING.match(line)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def _repair_update_url(lines: list[str]) -> str | None:
    """Strip junk before the address in JARVIS_UPDATE_URL.

    A real install had 'JARVIS_UPDATE_URL=update https://github.com/...' and
    could never update again, because the value does not start with https.
    """
    for index, line in enumerate(lines):
        match = _SETTING.match(line)
        if not match or match.group(1) != "JARVIS_UPDATE_URL":
            continue
        value = match.group(2).strip()
        if not value or value.lower().startswith("https://"):
            return None
        marker = value.lower().find("https://")
        if marker <= 0:
            return None
        lines[index] = f"JARVIS_UPDATE_URL={value[marker:]}"
        return value[:marker].strip()
    return None


def migrate(env_path: Path, app_version: str = "") -> list[str]:
    """Update `env_path` in place. Returns a description of what changed.

    Safe to call on every start: with nothing to do it touches no files.
    """
    if not env_path.exists():
        return []

    try:
        original = env_path.read_text(encoding="utf-8")
    except OSError:
        return []

    lines = original.splitlines()
    changes: list[str] = []

    junk = _repair_update_url(lines)
    if junk:
        changes.append(f"removed {junk!r} from the start of JARVIS_UPDATE_URL")

    present = _present(lines)

    for index, line in enumerate(lines):
        match = _SETTING.match(line)
        if match and match.group(1) in OBSOLETE:
            lines[index] = f"# no longer used since 2.6: {line.strip()}"
            changes.append(f"commented out {match.group(1)} (no longer read)")

    missing = [(n, d, c) for n, d, c in EXPECTED if n not in present]
    if missing:
        stamp = f" (JARVIS {app_version})" if app_version else ""
        lines.append("")
        lines.append(f"# --- added automatically on update{stamp} ---")
        for name, default, comment in missing:
            for part in comment.split("\n"):
                lines.append(part if part.startswith("#") else f"# {part}")
            lines.append(f"{name}={default}")
            lines.append("")
        changes.append(
            f"added {len(missing)} missing setting(s): "
            + ", ".join(n for n, _, _ in missing)
        )

    if not changes:
        return []

    updated = "\n".join(lines).rstrip() + "\n"
    if updated == original:
        return []

    try:
        backup = env_path.with_name(
            f".env.backup-{datetime.now():%Y%m%d_%H%M%S}"
        )
        shutil.copy2(env_path, backup)
        env_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return [f"could not update .env: {exc}"]

    changes.append(f"previous file kept as {backup.name}")
    return changes
