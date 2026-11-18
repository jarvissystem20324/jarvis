"""Build it live (Bounty update): an idea said out loud becomes a website with a
small working app on it, shared on the room's Wi-Fi with a QR code.

Made for the stage: say "a website for a school recycling club with a quiz",
and a few seconds later the audience scans the code and has it on their
phones. The page is one self-contained HTML file (no outside scripts, so it
works on any Wi-Fi), kept in JARVIS's output folder. It is served only from
the folder of pages Build it live made, only while JARVIS is open, and only
after you agree to share it on your network.
"""

from __future__ import annotations

import functools
import http.server
import re
import socket
import socketserver
import threading
from pathlib import Path

from . import kit, security, shield

PORT = 8777

PROMPT = """Build a website for this idea: “{idea}”.

Return ONE complete HTML file and nothing else: <!doctype html> … </html>.
- A landing section: a strong title, a one-line pitch, three short feature cards.
- Below it, one small app that really works with plain JavaScript and fits the idea
  (a quiz, a calculator, a sign-up list kept in localStorage, a booking form, a game, a timer…).
- Modern and clean, made for phones first; nice colours, rounded cards, a system font stack.
- Everything inline: no external scripts, fonts, images or links (it runs on a local Wi-Fi).
- Text in the same language as the idea. No lorem ipsum, nothing childish, nothing unsafe."""


class LiveError(Exception):
    pass


def folder() -> Path:
    return kit.output_dir("live")


def extract_html(text: str) -> str:
    body = (text or "").strip()
    fence = re.search(r"```(?:html)?\s*(.*?)```", body, re.S | re.I)
    if fence:
        body = fence.group(1).strip()
    start = body.lower().find("<!doctype")
    if start < 0:
        start = body.lower().find("<html")
    end = body.lower().rfind("</html>")
    if start < 0 or end < 0:
        raise LiveError("The AI didn't return a web page. Try again, or describe the idea in a little more detail.")
    html = body[start:end + len("</html>")]
    # Nothing from outside: the page must work on a Wi-Fi with no internet, and load nothing it didn't ship.
    return re.sub(r"<script[^>]+src=[^>]*>\s*</script>", "", html, flags=re.I)


def build(brain, idea: str) -> Path:
    idea = (idea or "").strip()
    if len(idea) < 4:
        raise LiveError("Say what the website is for, e.g. “a site for our robotics team with a quiz”.")
    with kit.more_room(brain, 7000):
        html = extract_html(brain.ask_once(f"{shield.RULE}\n" + PROMPT.format(idea=idea[:600])))
    slug = kit.slug(idea, 32).lower() or "site"
    target = folder() / f"{slug}-{kit.stamp()[-6:]}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(html, encoding="utf-8")
    return target


def lan_ip() -> str:
    """This PC's address on the local network (nothing is sent to find it)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Live:
    def __init__(self) -> None:
        self.server = None
        self.allowed = False

    def serve(self) -> int:
        if self.server is None:
            handler = functools.partial(_Quiet, directory=str(folder()))
            self.server = _Server(("0.0.0.0", PORT), handler)
            threading.Thread(target=self.server.serve_forever, daemon=True, name="build-live").start()
        return self.server.server_address[1]

    def stop(self) -> str:
        if self.server is None:
            return "Nothing is being shared."
        self.server.shutdown()
        self.server.server_close()
        self.server = None
        return "Stopped sharing the live sites."

    def share(self, site: Path) -> str:
        if not self.allowed:
            if not security.permissions.ask(security.NETWORK, f"Share the pages Build it live made on your Wi-Fi "
                                            f"(port {PORT}) so phones in the room can open them", "/buildlive"):
                raise LiveError("Not shared. The site is saved on this PC: " + str(site / "index.html"))
            self.allowed = True
        port = self.serve()
        return f"http://{lan_ip()}:{port}/{site.name}/"


live = Live()


def qr(url: str, site: Path) -> Path:
    import qrcode

    image = qrcode.make(url, box_size=12, border=2)
    path = site / "qr.png"
    image.save(path)
    return path
