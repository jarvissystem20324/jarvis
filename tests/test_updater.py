"""The updater: the part that decides what code runs on other people's PCs.

Every failure mode here reached a real user at least once — a malformed
update URL that could never update again, a certificate store that did not
exist on a friend's machine, a cached manifest that said "you are up to
date". Nothing below touches the network: the server is a fake that hands
back exactly the bytes each test needs.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from jarvis import updater


# --- versions --------------------------------------------------------------

@pytest.mark.parametrize("candidate,current,newer", [
    ("3.10", "3.9", True),       # string comparison would get this wrong
    ("4.0.1", "4.0", True),
    ("4.0", "4.0.0", False),
    ("4.0", "4.0", False),
    ("3.3", "4.0", False),       # never "update" backwards
    ("v5.0", "4.0.1", True),
    ("5.0", "garbage", True),
])
def test_version_ordering(candidate, current, newer):
    assert updater.is_newer(candidate, current) is newer


# --- the update address ----------------------------------------------------

def test_https_is_accepted():
    updater._require_https("https://github.com/x/y/update.json", "Update URL")


def test_plain_http_is_refused_with_the_fix():
    with pytest.raises(updater.UpdateError, match="https://example.test"):
        updater._require_https("http://example.test/u.json", "Update URL")


def test_junk_before_the_address_is_named():
    """A real .env read 'JARVIS_UPDATE_URL=update https://...'."""
    with pytest.raises(updater.UpdateError, match="'update'"):
        updater._require_https("update https://github.com/x/u.json", "Update URL")


# --- a fake server ---------------------------------------------------------

class _Response(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def server(monkeypatch):
    """Serve whatever each test puts in `server.files`, and record requests."""
    class Server:
        files: dict[str, bytes] = {}
        requested: list[str] = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        Server.requested.append(url)
        for prefix, body in Server.files.items():
            if url.startswith(prefix):
                return _Response(body)
        raise OSError(f"no fake for {url}")

    monkeypatch.setattr(updater.net, "urlopen", fake_urlopen)
    monkeypatch.setattr(updater, "current_version", lambda: "4.0")
    monkeypatch.setattr(updater, "platform_key", lambda: "windows")
    monkeypatch.setattr(updater, "IS_WINDOWS", True)
    Server.files = {}
    Server.requested = []
    return Server


MANIFEST = "https://example.test/update.json"
BINARY = b"pretend this is JARVIS.exe"
DIGEST = hashlib.sha256(BINARY).hexdigest()


def manifest(**overrides) -> bytes:
    data = {
        "version": "5.0",
        "url": "https://example.test/JARVIS.exe",
        "sha256": DIGEST,
        "notes": "JARVIS 5.0",
    }
    data.update(overrides)
    return json.dumps(data).encode()


def test_a_newer_version_is_offered(server):
    server.files[MANIFEST] = manifest()
    info = updater.check_for_update(MANIFEST)
    assert info is not None and info.version == "5.0"


def test_the_same_version_is_not_offered(server):
    server.files[MANIFEST] = manifest(version="4.0")
    assert updater.check_for_update(MANIFEST) is None


def test_the_manifest_request_cannot_be_answered_from_cache(server):
    """A cached manifest with an old version tells everyone they are up to
    date — the 'it says latest version and doesn't update' report."""
    server.files[MANIFEST] = manifest()
    updater.check_for_update(MANIFEST)
    assert "?_=" in server.requested[0]


def test_a_manifest_without_a_checksum_is_refused(server):
    server.files[MANIFEST] = manifest(sha256="")
    with pytest.raises(updater.UpdateError, match="sha256"):
        updater.check_for_update(MANIFEST)


def test_a_plain_http_download_is_refused(server):
    server.files[MANIFEST] = manifest(url="http://example.test/JARVIS.exe")
    with pytest.raises(updater.UpdateError, match="https"):
        updater.check_for_update(MANIFEST)


def test_invalid_json_is_reported_not_crashed(server):
    server.files[MANIFEST] = b"<html>502 Bad Gateway</html>"
    with pytest.raises(updater.UpdateError, match="not valid JSON"):
        updater.check_for_update(MANIFEST)


def test_the_platform_entry_wins_over_the_flat_fields(server):
    server.files[MANIFEST] = manifest(platforms={
        "windows": {"url": "https://example.test/win.exe", "sha256": DIGEST},
    })
    assert updater.check_for_update(MANIFEST).url.endswith("win.exe")


def test_a_mac_is_never_handed_the_windows_build(server, monkeypatch):
    monkeypatch.setattr(updater, "platform_key", lambda: "macos-arm64")
    monkeypatch.setattr(updater, "IS_WINDOWS", False)
    server.files[MANIFEST] = manifest()          # flat fields only: Windows
    with pytest.raises(updater.UpdateError, match="no build for macos-arm64"):
        updater.check_for_update(MANIFEST)


# --- the download ----------------------------------------------------------

def test_a_download_matching_its_checksum_is_kept(server, base, monkeypatch):
    monkeypatch.setattr(updater, "get_base_dir", lambda: base)
    server.files["https://example.test/JARVIS.exe"] = BINARY
    info = updater.UpdateInfo("5.0", "https://example.test/JARVIS.exe", DIGEST)
    path = updater.download_update(info)
    assert path.read_bytes() == BINARY


def test_a_tampered_download_is_deleted_and_refused(server, base, monkeypatch):
    monkeypatch.setattr(updater, "get_base_dir", lambda: base)
    server.files["https://example.test/JARVIS.exe"] = b"something else entirely"
    info = updater.UpdateInfo("5.0", "https://example.test/JARVIS.exe", DIGEST)
    with pytest.raises(updater.UpdateError, match="Checksum mismatch"):
        updater.download_update(info)
    assert not (base / updater.DOWNLOAD_NAME).exists()


def test_progress_is_reported(server, base, monkeypatch):
    monkeypatch.setattr(updater, "get_base_dir", lambda: base)
    server.files["https://example.test/JARVIS.exe"] = BINARY
    seen = []
    updater.download_update(
        updater.UpdateInfo("5.0", "https://example.test/JARVIS.exe", DIGEST),
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen and seen[-1][0] == len(BINARY)


# --- usage stats -----------------------------------------------------------

def test_usage_reads_the_audit_log(base):
    from jarvis import security, usage

    security.audit.record("answered", "Groq / qwen/qwen3.8-27b", "1.2s, Low")
    security.audit.record("answered", "Groq / qwen/qwen3.8-27b", "1.8s, Low")
    security.audit.record("answered", "NVIDIA NIM / nemotron", "4.0s, Max")
    report = usage.report()
    assert "3 answers from 2 provider(s)" in report
    assert "Low" in report and "Max" in report
