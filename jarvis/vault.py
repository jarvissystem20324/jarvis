"""Encryption at rest for what JARVIS keeps about you.

Conversations, remembered facts, notes, reminders and the document index are
written encrypted with Windows' Data Protection API (DPAPI). The key is your
Windows login: nothing is typed, nothing is stored next to the files, and a
copy of the data folder — on a USB stick, in a backup, on another account —
is unreadable noise.

What it does not protect against, said plainly: anything running as you, on
your account, while you are logged in. DPAPI hands the plaintext to any
process of the same user, which is also how JARVIS reads it back. And if a
Windows password is *reset* by an administrator rather than changed by you,
Windows discards the key and these files cannot be recovered.

Files keep their names and are recognised by a header, so older plain files
still load and are encrypted the next time they are saved. On a platform
without DPAPI the data is stored as before, and /security says so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import get_setting

MAGIC = b"JARVIS-VAULT-1\n"
# Mixed into DPAPI's key so another program running as you cannot decrypt
# these simply by calling CryptUnprotectData with no entropy.
_ENTROPY = b"jarvis-desktop/data-at-rest/v1"


class VaultError(OSError):
    """The file is encrypted, but not for this Windows account.

    An OSError so every `except OSError` that already guards a file read
    treats an unreadable sealed file like any other unreadable file.
    """


def available() -> bool:
    return sys.platform == "win32"


def enabled() -> bool:
    """On by default wherever it can be. JARVIS_ENCRYPT=off turns it off."""
    return available() and get_setting("JARVIS_ENCRYPT", "on").strip().lower() not in {
        "0", "off", "false", "no",
    }


# --- DPAPI ---------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _UI_FORBIDDEN = 0x01

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _take(blob: _Blob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def protect(data: bytes) -> bytes:
        plain, _keep = _blob(data)
        entropy, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptProtectData(
            ctypes.byref(plain), "JARVIS", ctypes.byref(entropy),
            None, None, _UI_FORBIDDEN, ctypes.byref(out),
        ):
            raise VaultError(f"Windows refused to encrypt (error {ctypes.GetLastError()}).")
        return _take(out)

    def unprotect(data: bytes) -> bytes:
        sealed, _keep = _blob(data)
        entropy, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(sealed), None, ctypes.byref(entropy),
            None, None, _UI_FORBIDDEN, ctypes.byref(out),
        ):
            raise VaultError(
                "This file is encrypted for a different Windows account, or "
                "the account's password was reset by an administrator."
            )
        return _take(out)

else:  # pragma: no cover - exercised on macOS/Linux CI only
    def protect(data: bytes) -> bytes:
        raise VaultError("Encryption at rest needs Windows.")

    def unprotect(data: bytes) -> bytes:
        raise VaultError("This file was encrypted on Windows and can only be read there.")


# --- files ---------------------------------------------------------------

def is_sealed(raw: bytes) -> bool:
    return raw.startswith(MAGIC)


def read_bytes(path: Path) -> bytes:
    """A file's plaintext, whether it was written sealed or not."""
    raw = Path(path).read_bytes()
    if is_sealed(raw):
        return unprotect(raw[len(MAGIC):])
    return raw


def write_bytes(path: Path, data: bytes) -> None:
    """Write, sealed when encryption is on. Replaces the file atomically."""
    path = Path(path)
    payload = MAGIC + protect(data) if enabled() else data
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(payload)
    temp.replace(path)


def read_text(path: Path) -> str:
    return read_bytes(path).decode("utf-8")


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def read_json(path: Path):
    """Parsed JSON from a sealed or plain file. Raises ValueError if unreadable."""
    try:
        return json.loads(read_text(path))
    except VaultError as exc:
        raise ValueError(str(exc)) from None


def write_json(path: Path, data, indent: int | None = 2) -> None:
    write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


def seal_existing(folder: Path, patterns=("*.json",)) -> int:
    """Encrypt plain files already on disk. Returns how many were sealed."""
    if not enabled():
        return 0
    sealed = 0
    for pattern in patterns:
        for path in Path(folder).rglob(pattern):
            try:
                raw = path.read_bytes()
                if not raw or is_sealed(raw):
                    continue
                write_bytes(path, raw)
                sealed += 1
            except (OSError, VaultError):
                continue
    return sealed


def describe() -> str:
    if not available():
        return "off — encryption at rest needs Windows (DPAPI)"
    if not enabled():
        return "off (JARVIS_ENCRYPT=off)"
    return "on — chats, memory, notes and reminders are tied to your Windows login"
