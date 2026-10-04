"""10.0 phone and devices: the phone link's server (token, local-only,
uploads, ranges, casting), DLNA messages, Kasa's protocol, and the page."""

from __future__ import annotations

import json
import socket
import socketserver
import struct
import threading
import urllib.error
import urllib.request

import pytest

from jarvis import dlna, kasa, phonelink


@pytest.fixture
def link(base, tmp_path, monkeypatch):
    """A phone link of our own on 127.0.0.1, its inbox in a temp folder."""
    from jarvis.assistant import JarvisResponse

    monkeypatch.setattr(phonelink, "inbox", lambda: (tmp_path / "inbox").mkdir(exist_ok=True) or tmp_path / "inbox")
    monkeypatch.setattr(phonelink, "set_clipboard", lambda text: True)
    monkeypatch.setattr(phonelink, "get_clipboard", lambda: "from the PC")
    from jarvis import alerts

    monkeypatch.setattr(alerts, "post", lambda *a, **k: None)
    own = phonelink.Link()

    class Jarvis:
        def process(self, text):
            return JarvisResponse(text=f"echo: {text}")

    own.start(Jarvis(), host="127.0.0.1", port=0)
    yield own
    own.stop()


def _call(url, method="GET", data=None, headers=None):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_the_page_needs_the_token(link):
    root = f"http://127.0.0.1:{link.port}"
    assert _call(root + "/")[0] == 403
    assert _call(root + "/?t=wrong")[0] == 403
    status, headers, body = _call(link.url())
    assert status == 200 and link.token.encode() in body and "SameSite=Strict" in headers["Set-Cookie"]
    # The API wants the token in a header (a cookie alone isn't enough: another site can't set headers).
    cookie = {"Cookie": f"jarvis_link={link.token}"}
    assert _call(root + "/api/state", headers=cookie)[0] == 403
    assert _call(root + "/api/state", headers={"X-Jarvis-Token": link.token})[0] == 200


def test_chat_clipboard_and_uploads(link, tmp_path):
    root, token = f"http://127.0.0.1:{link.port}", {"X-Jarvis-Token": link.token}
    status, _, body = _call(root + "/api/ask", "POST", json.dumps({"text": "/flip"}).encode(), token)
    assert status == 200 and json.loads(body)["reply"] == "echo: /flip"
    _call(root + "/api/clip", "POST", json.dumps({"text": "a note from the phone"}).encode(), token)
    assert link.from_phone == "a note from the phone"
    assert json.loads(_call(root + "/api/clip", headers=token)[2])["text"] == "from the PC"
    photo = b"\xff\xd8" + b"x" * 300_000
    status, _, body = _call(root + "/api/upload?name=..%2F..%2Fevil%2FIMG_0001.jpg", "PUT", photo, token)
    saved = tmp_path / "inbox" / "IMG_0001.jpg"            # the path in the name is thrown away
    assert status == 200 and saved.read_bytes() == photo and link.received[0]["name"] == "IMG_0001.jpg"
    _call(root + "/api/upload?name=IMG_0001.jpg", "PUT", b"again", token)
    assert (tmp_path / "inbox" / "IMG_0001 (2).jpg").read_bytes() == b"again"


def test_shared_files_and_casting_support_ranges(link, tmp_path):
    clip = tmp_path / "holiday.mp4"
    clip.write_bytes(bytes(range(256)) * 40)
    key = link.share(clip)
    root, token = f"http://127.0.0.1:{link.port}", {"X-Jarvis-Token": link.token}
    status, headers, body = _call(f"{root}/files/{key}", headers=dict(token, Range="bytes=10-19"))
    assert status == 206 and body == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/10240"
    cast = link.cast_url(clip)
    status, headers, body = _call(cast)                        # a TV has no token; the secret URL is the key
    assert status == 200 and len(body) == 10240 and headers["Content-Type"] == "video/mp4"
    assert "DLNA.ORG_OP=01" in headers["contentFeatures.dlna.org"]
    assert _call(cast.rsplit("/", 2)[0] + "/not-the-secret/holiday.mp4")[0] == 404


def test_only_the_local_network():
    assert phonelink.is_local("192.168.1.20") and phonelink.is_local("10.0.0.5") and phonelink.is_local("127.0.0.1")
    assert not phonelink.is_local("8.8.8.8") and not phonelink.is_local("nonsense")
    assert phonelink.safe_name('..\\a/b<c>.txt') == "b_c_.txt"


# --- DLNA ---------------------------------------------------------------------------------------------

DESCRIPTION = """<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<friendlyName>[TV] Samsung 7 Series</friendlyName><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType><controlURL>/rc</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<controlURL>/upnp/control/AVTransport1</controlURL></service></serviceList></device></root>"""


def test_dlna_finding_and_telling_a_tv():
    headers = dlna.parse_ssdp(b"HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.40:9197/dmr\r\nST: x\r\n\r\n")
    assert headers["location"] == "http://192.168.1.40:9197/dmr"
    tv = dlna.parse_description(DESCRIPTION, "http://192.168.1.40:9197/dmr")
    assert tv["name"] == "[TV] Samsung 7 Series" and tv["control"] == "http://192.168.1.40:9197/upnp/control/AVTransport1"
    body = dlna.envelope("Play", tv["service"], {"InstanceID": 0, "Speed": 1}).decode()
    assert "<u:Play xmlns:u=\"urn:schemas-upnp-org:service:AVTransport:1\"><InstanceID>0</InstanceID>" in body
    assert "&lt;" in dlna.envelope("SetAVTransportURI", tv["service"], {"CurrentURIMetaData": "<x>"}).decode()
    assert "object.item.videoItem" in dlna.didl("http://pc/a.mp4", "A & B", "video/mp4")


def test_casting_sends_the_url_then_play(monkeypatch):
    actions = []
    monkeypatch.setattr(dlna, "soap", lambda device, action, **args: actions.append((action, args)))
    dlna.play({"name": "TV"}, "http://192.168.1.2:8765/cast/abc/a.mp4", "a", "video/mp4")
    assert [a for a, _ in actions] == ["SetAVTransportURI", "Play"]
    assert actions[0][1]["CurrentURI"].endswith("/cast/abc/a.mp4")


# --- Kasa -----------------------------------------------------------------------------------------------

def test_kasa_scrambling():
    packet = kasa.scramble('{"system":{"get_sysinfo":{}}}')
    assert packet[:8] == bytes([0xD0, 0xF2, 0x81, 0xF8, 0x8B, 0xFF, 0x9A, 0xF7])    # the well-known discovery bytes
    assert kasa.unscramble(packet) == '{"system":{"get_sysinfo":{}}}'
    plug = kasa.plug_from({"system": {"get_sysinfo": {"alias": "Desk lamp", "model": "HS103(EU)",
                                                      "relay_state": 1}}}, "192.168.1.50")
    assert plug == {"ip": "192.168.1.50", "name": "Desk lamp", "model": "HS103(EU)", "on": True}


def test_kasa_switching_over_tcp():
    seen = []

    class Plug(socketserver.BaseRequestHandler):
        def handle(self):
            length = struct.unpack(">I", self.request.recv(4))[0]
            seen.append(json.loads(kasa.unscramble(self.request.recv(length))))
            reply = kasa.scramble(json.dumps({"system": {"set_relay_state": {"err_code": 0}}}))
            self.request.sendall(struct.pack(">I", len(reply)) + reply)

    server = socketserver.TCPServer(("127.0.0.1", 0), Plug)
    threading.Thread(target=server.handle_request, daemon=True).start()
    assert kasa.set_power("127.0.0.1", True, port=server.server_address[1])
    server.server_close()
    assert seen == [{"system": {"set_relay_state": {"state": 1}}}]


# --- the commands and the page -------------------------------------------------------------------------

def test_phone_cast_and_plug_commands(base, allow, monkeypatch, tmp_path):
    from jarvis.ten import phone, shield10

    monkeypatch.setattr(shield10, "local_network", lambda: ("127.0.0.1", "127.0.0"))
    tool = phone.Phone()
    tool.process = lambda text: None
    assert "phone link is off" in phone.Phone().phone_cmd("").text
    try:
        reply = tool.phone_cmd("on")
        assert "Phone link on" in reply.text and reply.open_page == "phone" and phonelink.link.running
        clip = tmp_path / "movie.mp4"
        clip.write_bytes(b"x" * 10)
        played = []
        monkeypatch.setattr(dlna, "discover", lambda timeout=3.0: [{"name": "Living room TV", "control": "x",
                                                                    "service": dlna.AVTRANSPORT}])
        monkeypatch.setattr(dlna, "play", lambda tv, url, title, mime: played.append((tv["name"], url, mime)))
        assert "Playing movie.mp4 on Living room TV" in tool.cast_cmd(f"{clip} | living")
        assert played[0][2] == "video/mp4" and "/cast/" in played[0][1]
    finally:
        phonelink.link.stop()
    switched = []
    monkeypatch.setattr(kasa, "discover", lambda timeout=2.0: [{"ip": "192.168.1.50", "name": "Desk lamp",
                                                                 "model": "HS103", "on": False}])
    monkeypatch.setattr(kasa, "set_power", lambda ip, on, port=9999: switched.append((ip, on)) or True)
    assert "⚪ Desk lamp" in tool.plugs_cmd("")
    assert tool.plugs_cmd("on desk") == "🔌 Desk lamp is on." and switched == [("192.168.1.50", True)]
    assert "turn on Desk lamp" in allow[-1].detail


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_phone_page(app, monkeypatch):
    from jarvis.ten import shield10

    monkeypatch.setattr(shield10, "local_network", lambda: ("127.0.0.1", "127.0.0"))
    app._show_tab("phone")
    app.update()
    page = app.pages["phone"]
    assert "Off" in page.url.cget("text")
    try:
        page.link_var.set(True)
        page.toggle_link()
        assert phonelink.link.running and page.url.cget("text").startswith("http://127.0.0.1:")
        assert page._qr.width() == 220
    finally:
        page.link_var.set(False)
        page.toggle_link()
    assert not phonelink.link.running
