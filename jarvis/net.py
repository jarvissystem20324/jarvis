"""Shared HTTPS access for the parts of JARVIS that don't go through the SDK.

Every plain-urllib call in the app routes through here for one reason: a frozen
build cannot rely on the machine's certificate store. Python's ssl module has
no bundled CA file on Windows (`ssl.get_default_verify_paths()` reports no
cafile), so it falls back to whatever roots the OS happens to hold. On a
machine that has never fetched them — a fresh Windows install, an offline or
locked-down box — verification fails with:

    CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate

which is what update checks and image generation hit in the wild while the
developer's own machine worked fine. httpx (and therefore the OpenAI SDK)
already defaults to certifi, which is why chat kept working when these did not.

Pinning certifi's bundle makes every machine behave like the one it was built
on. Verification is never disabled: the updater downloads an executable, and a
caller who can forge the TLS session can forge the SHA-256 in the manifest
alongside it, so turning verification off would defeat the checksum too.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

# Cloudflare (in front of Pollinations) rejects clients that don't look like a
# browser, so the default "Python-urllib/3.x" earns an error 1010.
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/2.5"


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """A verifying context backed by certifi where possible."""
    try:
        import certifi

        bundle = Path(certifi.where())
        if bundle.is_file():
            return ssl.create_default_context(cafile=str(bundle))
    except Exception:
        # certifi missing or unreadable inside the bundle — fall back to the
        # OS store, which is what shipped before and works on most machines.
        pass
    return ssl.create_default_context()


def using_certifi() -> bool:
    """Whether the pinned bundle was found — surfaced by the self-test."""
    try:
        import certifi

        return Path(certifi.where()).is_file()
    except Exception:
        return False


def request(url: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
    merged = {"User-Agent": DEFAULT_USER_AGENT}
    merged.update(headers or {})
    return urllib.request.Request(url, headers=merged)


def _is_cert_error(exc: BaseException) -> bool:
    text = str(exc)
    return "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerification" in text


def urlopen(target, timeout: float = 60, data: bytes | None = None):
    """urlopen that verifies against certifi, falling back to the OS store.

    Neither trust source alone covers everyone. certifi fixes machines whose
    certificate store lacks the public roots — the reported failure. But it is
    a curated list that deliberately excludes private roots, so a corporate
    proxy or antivirus doing TLS inspection installs its root into Windows and
    not into certifi; pinning certifi alone would break those users instead.

    So: try the bundle, and on a verification failure try the OS store. Both
    attempts verify fully — this widens which certificates are trusted, it
    never accepts an unverified one.
    """
    if isinstance(target, str):
        target = request(target)

    try:
        return urllib.request.urlopen(
            target, timeout=timeout, data=data, context=ssl_context()
        )
    except (urllib.error.URLError, ssl.SSLError) as exc:
        if not _is_cert_error(exc) or not using_certifi():
            raise
        return urllib.request.urlopen(
            target, timeout=timeout, data=data, context=ssl.create_default_context()
        )


def describe_ssl_error(exc: BaseException) -> str | None:
    """A human explanation when a failure is really a certificate problem."""
    if not _is_cert_error(exc):
        return None
    return (
        "The secure connection could not be verified against either the "
        "bundled certificates or this machine's own store.\n\n"
        "This usually means Windows is missing root certificates, or security "
        "software is inspecting encrypted traffic. Installing Windows updates "
        "normally fixes it."
    )
