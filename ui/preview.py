"""The Code tab's built-in browser (14.3).

A website the agent built is served from your project folder on this PC only
(127.0.0.1, a free port) and opened in a window of its own: Microsoft Edge in
app mode, which has no address bar, tabs or bookmarks, so it looks like part
of JARVIS rather than a browser. Edge is on every Windows 10 and 11 PC, so
nothing extra is installed; without it, the normal browser opens instead.

The window uses its own profile in JARVIS's data folder, so it never mixes
with your own browser's tabs, history or sign-ins.
"""

from __future__ import annotations

import functools
import http.server
import os
import subprocess
import threading
import webbrowser
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Folders a project's page is usually in, best first.
_PLACES = ("", "public", "dist", "build", "src", "site", "docs", "web")
_servers: dict[str, tuple[http.server.ThreadingHTTPServer, int]] = {}
_lock = threading.Lock()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """Serves files without printing every request, and never from cache,
    so a page the agent just rewrote shows its new version on reload."""

    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def find_page(folder) -> Path | None:
    """The project's web page: index.html in the usual places, else any .html."""
    root = Path(folder)
    for place in _PLACES:
        candidate = root / place / "index.html"
        if candidate.is_file():
            return candidate
    pages = sorted(p for p in root.glob("*.html")) + sorted(p for p in root.glob("*/*.html"))
    return pages[0] if pages else None


def serve(folder) -> int:
    """Serve `folder` on 127.0.0.1 (started once per folder); the port."""
    key = str(Path(folder).resolve()).lower()
    with _lock:
        if key in _servers:
            return _servers[key][1]
        handler = functools.partial(_Quiet, directory=str(Path(folder).resolve()))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _servers[key] = (server, port)
        return port


def url_for(folder, page: Path) -> str:
    port = serve(folder)
    relative = Path(page).resolve().relative_to(Path(folder).resolve()).as_posix()
    return f"http://127.0.0.1:{port}/{relative}"


def stop_all() -> None:
    with _lock:
        for server, _port in _servers.values():
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        _servers.clear()


def edge_path() -> Path | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidate.is_file():
                return candidate
    return None


def edge_args(edge: Path, url: str, profile: Path, geometry: tuple[int, int, int, int] | None = None) -> list[str]:
    args = [str(edge), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-features=Translate"]
    if geometry:
        x, y, w, h = geometry
        args += [f"--window-position={x},{y}", f"--window-size={w},{h}"]
    return args


def open_window(url: str, geometry: tuple[int, int, int, int] | None = None) -> str:
    """Open `url` in the preview window. Returns 'edge' or 'browser'."""
    edge = edge_path()
    if edge is not None:
        from jarvis.config import get_data_dir

        profile = get_data_dir() / "preview-browser"
        profile.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(edge_args(edge, url, profile, geometry), creationflags=NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "edge"
        except OSError:
            pass
    webbrowser.open(url)
    return "browser"
