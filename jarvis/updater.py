"""In-place updates for the frozen JARVIS build.

The app checks a JSON manifest at ``JARVIS_UPDATE_URL``:

    {
      "version": "2.1",
      "url":     "https://.../JARVIS.exe",
      "sha256":  "<hex digest of that file>",
      "notes":   "What changed in this release"
    }

Any static host works — GitHub Releases, S3, a plain web server.

Swapping a running EXE: Windows refuses to delete a running executable but
allows renaming it. So the live EXE is renamed aside, the new one moved into
its place, and the fresh copy relaunched. The leftover is deleted on next
start. If anything fails midway the original name is restored.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from . import net
from dataclasses import dataclass
from pathlib import Path

from .config import get_base_dir, get_setting

USER_AGENT = "JARVIS-Updater"
CONNECT_TIMEOUT = 20
OLD_SUFFIX = ".old.exe"
DOWNLOAD_NAME = "JARVIS.new.exe"


class UpdateError(RuntimeError):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""


def current_version() -> str:
    from . import __version__

    return __version__


def get_update_url() -> str:
    return get_setting("JARVIS_UPDATE_URL", "")


def parse_version(text: str) -> tuple[int, ...]:
    """'2.10.1' -> (2, 10, 1). Unparseable pieces sort as 0."""
    parts = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    length = max(len(a), len(b))
    return a + (0,) * (length - len(a)) > b + (0,) * (length - len(b))


def _require_https(url: str, what: str) -> None:
    if not url.lower().startswith("https://"):
        raise UpdateError(f"{what} must use https (refusing {url[:60]}).")


def check_for_update(url: str | None = None) -> UpdateInfo | None:
    """Return an UpdateInfo if the manifest advertises a newer version."""
    manifest_url = (url or get_update_url()).strip()
    if not manifest_url:
        raise UpdateError(
            "No update source configured. Set JARVIS_UPDATE_URL in your .env "
            "to the address of your update manifest."
        )
    _require_https(manifest_url, "Update URL")

    try:
        with net.urlopen(
            net.request(manifest_url, {"User-Agent": USER_AGENT}),
            timeout=CONNECT_TIMEOUT,
        ) as response:
            raw = response.read(256 * 1024)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Update server returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, OSError) as exc:
        explanation = net.describe_ssl_error(exc)
        if explanation:
            raise UpdateError(explanation) from None
        raise UpdateError(f"Could not reach the update server: {exc}") from None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError("The update manifest is not valid JSON.") from None

    version = str(data.get("version", "")).strip()
    download = str(data.get("url", "")).strip()
    digest = str(data.get("sha256", "")).strip().lower()

    if not version or not download:
        raise UpdateError("The update manifest is missing 'version' or 'url'.")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        # Without a digest we cannot tell a real build from a tampered one.
        raise UpdateError("The update manifest has no valid sha256 checksum.")
    _require_https(download, "Download URL")

    if not is_newer(version, current_version()):
        return None
    return UpdateInfo(version, download, digest, str(data.get("notes", "")).strip())


def download_update(info: UpdateInfo, progress=None) -> Path:
    """Download to a staging file and verify its checksum before returning."""
    target = get_base_dir() / DOWNLOAD_NAME
    digest = hashlib.sha256()

    try:
        with net.urlopen(
            net.request(info.url, {"User-Agent": USER_AGENT}),
            timeout=CONNECT_TIMEOUT,
        ) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(target, "wb") as handle:
                while chunk := response.read(256 * 1024):
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except (urllib.error.URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from None

    if digest.hexdigest() != info.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError(
            "Checksum mismatch — the download was corrupted or tampered with. "
            "Update cancelled."
        )
    return target


def apply_update(downloaded: Path, relaunch: bool = True) -> None:
    """Swap the new EXE in and restart. Does not return if relaunch succeeds."""
    if not getattr(sys, "frozen", False):
        raise UpdateError(
            "Updates only apply to the packaged app. Running from source — "
            "use git or rebuild instead."
        )

    live = Path(sys.executable).resolve()
    retired = live.with_name(live.stem + OLD_SUFFIX)

    if not downloaded.exists() or downloaded.stat().st_size == 0:
        raise UpdateError("The downloaded update is missing or empty.")

    retired.unlink(missing_ok=True)
    try:
        live.rename(retired)  # allowed while running; deletion is not
    except OSError as exc:
        raise UpdateError(f"Could not replace the running app: {exc}") from None

    try:
        downloaded.replace(live)
    except OSError as exc:
        retired.rename(live)  # put things back the way they were
        raise UpdateError(f"Could not install the update: {exc}") from None

    if relaunch:
        subprocess.Popen([str(live)], cwd=str(live.parent), close_fds=True)
        os._exit(0)


def cleanup_previous_update() -> None:
    """Delete the retired EXE left behind by the last update. Best effort."""
    try:
        base = get_base_dir()
        for leftover in base.glob(f"*{OLD_SUFFIX}"):
            leftover.unlink(missing_ok=True)
        (base / DOWNLOAD_NAME).unlink(missing_ok=True)
    except OSError:
        pass
