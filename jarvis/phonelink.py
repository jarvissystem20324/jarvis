"""The phone link (10.0): your phone's browser talks to JARVIS over Wi-Fi —
chat with it, send photos and files to the PC, swap clipboards, and pick up
files the PC shares. The same small server hands a TV the file it's casting.

Nothing is installed on the phone: the Phone page shows a QR code, the phone
opens it, and that's the pairing. Rules, because this is a server:
  * it runs only while you've turned it on, and only on your local network
    (it answers private addresses — 192.168.x.x and friends — and nothing else);
  * every request needs the random token from the QR code (a new one each
    time the link starts); the page carries it in a header, so another site
    open in the phone's browser can't use the link behind your back;
  * whatever the phone asks JARVIS to do goes through the same permission
    prompts on the PC as typing it would;
  * uploads stream to "Downloads/JARVIS from phone" and are capped in size.
"""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import re
import secrets
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
MAX_UPLOAD = 4 * 1024 ** 3          # 4 GB — a long phone video
CHUNK = 1024 * 1024


def inbox() -> Path:
    from .pc import known_folder

    folder = (known_folder("downloads") or Path.home() / "Downloads") / "JARVIS from phone"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_name(name: str) -> str:
    name = Path(urllib.parse.unquote(name or "")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:150] or f"phone-{int(time.time())}"


def unique(folder: Path, name: str) -> Path:
    target = folder / name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def is_local(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


# --- the PC clipboard, from any thread ----------------------------------------------------------------

def get_clipboard() -> str:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""


def set_clipboard(text: str) -> bool:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        return False


# --- the link --------------------------------------------------------------------------------------

class Link:
    def __init__(self) -> None:
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.jarvis = None
        self.token = ""
        self.host = ""
        self.port = 0
        self.shared: dict[str, Path] = {}       # id → a file the PC offers the phone
        self.casts: dict[str, Path] = {}        # secret → a file a TV may fetch (TVs can't send tokens)
        self.received: list[dict] = []
        self.from_phone = ""
        self.last_seen = 0.0
        self._ask_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.server is not None

    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?t={self.token}" if self.running else ""

    def start(self, jarvis=None, host: str | None = None, port: int = PORT) -> str:
        if self.running:
            return self.url()
        if host is None:
            from .ten.shield10 import local_network

            found = local_network()
            if found is None:
                raise OSError("This PC isn't on a local network (Wi-Fi or cable).")
            host = found[0]
        self.jarvis = jarvis
        self.token = secrets.token_urlsafe(18)
        last = None
        for candidate in range(port, port + 10):
            try:
                self.server = ThreadingHTTPServer((host, candidate), _handler(self))
                break
            except OSError as exc:
                last = exc
        if self.server is None:
            raise OSError(f"No free port for the phone link ({last}).")
        self.server.daemon_threads = True
        self.host, self.port = host, self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="jarvis-phone-link")
        self.thread.start()
        return self.url()

    def stop(self) -> None:
        server, self.server = self.server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        self.token = ""
        self.casts.clear()

    def share(self, path: Path) -> str:
        key = secrets.token_urlsafe(6)
        self.shared[key] = Path(path)
        return key

    def cast_url(self, path: Path) -> str:
        if not self.running:
            raise OSError("The phone link isn't running.")
        secret = secrets.token_urlsafe(16)
        self.casts[secret] = Path(path)
        return f"http://{self.host}:{self.port}/cast/{secret}/{urllib.parse.quote(Path(path).name)}"

    def note_received(self, path: Path, size: int) -> None:
        from . import alerts

        self.received.insert(0, {"path": str(path), "name": path.name, "size": size, "at": time.time()})
        del self.received[50:]
        alerts.post(f"📱 From your phone: {path.name}", str(path.parent), page="phone")


link = Link()


def _handler(owner: Link):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JARVIS-PhoneLink"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:     # quiet: no console in the app
            pass

        # --- helpers ---------------------------------------------------------------------------
        def _send(self, status: int, body: bytes, kind: str = "application/json; charset=utf-8",
                  extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

        def _allowed(self, page: bool = False) -> bool:
            if not is_local(self.client_address[0]):
                self._send(403, b"Only devices on this network.", "text/plain")
                return False
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            offered = (self.headers.get("X-Jarvis-Token") or (query.get("t") or [""])[0]
                       if page else self.headers.get("X-Jarvis-Token") or "")
            if page and not offered:
                cookie = re.search(r"jarvis_link=([\w-]+)", self.headers.get("Cookie", ""))
                offered = cookie.group(1) if cookie else ""
            if not owner.token or not secrets.compare_digest(offered, owner.token):
                self._send(403, "Scan the QR code on JARVIS's Phone page again.".encode(), "text/plain; charset=utf-8")
                return False
            owner.last_seen = time.time()
            return True

        def _body(self, limit: int = 1_000_000) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > limit:
                raise ValueError("too large")
            return self.rfile.read(length)

        def _file(self, path: Path, dlna: bool = False) -> None:
            """A file with Range support (TVs and phones seek through video by asking for byte ranges)."""
            if not path.is_file():
                self._send(404, b"Gone.", "text/plain")
                return
            size = path.stat().st_size
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            ranged = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if ranged and (ranged.group(1) or ranged.group(2)):
                if ranged.group(1):
                    start = int(ranged.group(1))
                    end = int(ranged.group(2)) if ranged.group(2) else size - 1
                else:
                    start = max(0, size - int(ranged.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if dlna:
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS="
                                                             "01700000000000000000000000000000")
            else:
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{urllib.parse.quote(path.name)}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(CHUNK, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        # --- routes ----------------------------------------------------------------------------
        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            route = urllib.parse.urlparse(self.path).path
            if route.startswith("/cast/"):
                parts = route.split("/")
                path = owner.casts.get(parts[2]) if len(parts) > 2 else None
                if path is None or not is_local(self.client_address[0]):
                    self._send(404, b"Gone.", "text/plain")
                    return
                self._file(path, dlna=True)
                return
            if route == "/":
                if not self._allowed(page=True):
                    return
                body = PAGE.replace("{{TOKEN}}", owner.token).encode("utf-8")
                cookie = f"jarvis_link={owner.token}; HttpOnly; SameSite=Strict; Path=/"
                self._send(200, body, "text/html; charset=utf-8", {"Set-Cookie": cookie})
                return
            if not self._allowed():
                return
            if route == "/api/state":
                self._json({"shared": [{"id": k, "name": p.name, "size": p.stat().st_size if p.exists() else 0}
                                       for k, p in owner.shared.items()],
                            "received": [r["name"] for r in owner.received[:10]]})
            elif route == "/api/clip":
                self._json({"text": get_clipboard()})
            elif route.startswith("/files/"):
                path = owner.shared.get(route.split("/")[2])
                if path is None:
                    self._send(404, b"Gone.", "text/plain")
                else:
                    self._file(path)
            else:
                self._send(404, b"Not here.", "text/plain")

        def do_POST(self) -> None:
            if not self._allowed():
                return
            route = urllib.parse.urlparse(self.path).path
            try:
                data = json.loads(self._body() or b"{}")
            except ValueError:
                self._json({"error": "bad request"}, 400)
                return
            if route == "/api/ask":
                text = str(data.get("text", "")).strip()[:4000]
                if not text:
                    self._json({"reply": ""})
                    return
                if owner.jarvis is None:
                    self._json({"reply": "JARVIS isn't attached to the link."})
                    return
                with owner._ask_lock:               # one at a time, like the chat box
                    try:
                        response = owner.jarvis.process(text)
                        reply = getattr(response, "text", str(response))
                    except Exception as exc:
                        reply = f"Something went wrong: {exc}"
                self._json({"reply": reply})
            elif route == "/api/clip":
                text = str(data.get("text", ""))[:200_000]
                owner.from_phone = text
                ok = set_clipboard(text)
                self._json({"ok": ok})
            else:
                self._send(404, b"Not here.", "text/plain")

        def do_PUT(self) -> None:
            if not self._allowed():
                return
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/upload":
                self._send(404, b"Not here.", "text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_UPLOAD:
                self._json({"error": "That file is empty or too big (4 GB at most)."}, 413)
                return
            name = safe_name((urllib.parse.parse_qs(parsed.query).get("name") or [""])[0])
            target = unique(inbox(), name)
            partial = target.with_name(target.name + ".part")
            left = length
            with partial.open("wb") as handle:
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        break
                    handle.write(chunk)
                    left -= len(chunk)
            if left:
                partial.unlink(missing_ok=True)
                self._json({"error": "The upload was cut off."}, 400)
                return
            shutil.move(str(partial), str(target))
            owner.note_received(target, length)
            self._json({"ok": True, "saved": target.name})

    return Handler


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>JARVIS</title>
<meta name="jarvis-token" content="{{TOKEN}}">
<style>
:root{--bg:#0a0e17;--panel:#111827;--accent:#00d4ff;--text:#e2e8f0;--muted:#64748b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px system-ui,sans-serif}
header{padding:14px 16px;color:var(--accent);font-weight:700;font-size:20px}
nav{display:flex;gap:6px;padding:0 12px}nav button{flex:1;padding:10px;border:0;border-radius:10px;
background:var(--panel);color:var(--text);font-size:14px}nav button.on{background:#0e7490}
section{display:none;padding:12px}section.on{display:block}
.card{background:var(--panel);border-radius:14px;padding:14px;margin-bottom:12px}
textarea,input[type=text]{width:100%;background:var(--bg);color:var(--text);border:1px solid #1f2937;
border-radius:10px;padding:10px;font-size:16px}
.go{background:#0e7490;color:#fff;border:0;border-radius:10px;padding:11px 16px;font-size:15px;margin-top:8px}
#log div{margin:8px 0;white-space:pre-wrap}#log .me{color:var(--accent)}small,.muted{color:var(--muted)}
progress{width:100%}a{color:var(--accent)}
</style></head><body>
<header>JARVIS</header>
<nav><button data-tab="chat" class="on">Chat</button><button data-tab="send">Send</button>
<button data-tab="clip">Clipboard</button><button data-tab="files">Files</button></nav>
<section id="chat" class="on"><div class="card" id="log"><small>Ask anything, or type a /command.</small></div>
<div class="card"><textarea id="ask" rows="2" placeholder="Ask JARVIS…"></textarea>
<button class="go" id="askgo">Send</button></div></section>
<section id="send"><div class="card"><p>Photos and files go to <b>Downloads › JARVIS from phone</b> on the PC.</p>
<input type="file" id="pick" multiple><progress id="bar" value="0" max="1"></progress>
<div id="sent" class="muted"></div></div></section>
<section id="clip"><div class="card"><textarea id="cliptext" rows="5" placeholder="Text to put on the PC's clipboard"></textarea>
<button class="go" id="clipsend">Send to PC</button> <button class="go" id="clipget">Get PC's clipboard</button>
<div id="clipnote" class="muted"></div></div></section>
<section id="files"><div class="card"><p>Files the PC is sharing with you:</p><div id="list" class="muted">Nothing yet.</div></div></section>
<script>
const T=document.querySelector('meta[name=jarvis-token]').content;
const H={'X-Jarvis-Token':T,'Content-Type':'application/json'};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('nav button,section').forEach(x=>x.classList.remove('on'));
 b.classList.add('on');document.getElementById(b.dataset.tab).classList.add('on');if(b.dataset.tab=='files')files();});
function line(text,me){const d=document.createElement('div');if(me)d.className='me';d.textContent=text;
 document.getElementById('log').appendChild(d);d.scrollIntoView();}
document.getElementById('askgo').onclick=async()=>{const box=document.getElementById('ask');const t=box.value.trim();
 if(!t)return;box.value='';line('You: '+t,true);line('…');
 const r=await fetch('/api/ask',{method:'POST',headers:H,body:JSON.stringify({text:t})});const j=await r.json();
 const log=document.getElementById('log');log.removeChild(log.lastChild);line('JARVIS: '+(j.reply||j.error||''));};
document.getElementById('pick').onchange=async e=>{const files=[...e.target.files];let done=0;
 for(const f of files){await new Promise(ok=>{const x=new XMLHttpRequest();
  x.open('PUT','/api/upload?name='+encodeURIComponent(f.name));x.setRequestHeader('X-Jarvis-Token',T);
  x.upload.onprogress=p=>{document.getElementById('bar').value=(done+p.loaded/p.total)/files.length};
  x.onload=()=>{done++;document.getElementById('sent').textContent='Sent '+done+' of '+files.length;ok()};
  x.onerror=()=>{document.getElementById('sent').textContent='Failed: '+f.name;ok()};x.send(f);});}};
document.getElementById('clipsend').onclick=async()=>{const t=document.getElementById('cliptext').value;
 const r=await fetch('/api/clip',{method:'POST',headers:H,body:JSON.stringify({text:t})});const j=await r.json();
 document.getElementById('clipnote').textContent=j.ok?'On the PC clipboard.':'The PC clipboard was busy — try again.';};
document.getElementById('clipget').onclick=async()=>{const r=await fetch('/api/clip',{headers:H});const j=await r.json();
 document.getElementById('cliptext').value=j.text||'';document.getElementById('clipnote').textContent='Copied from the PC.';};
async function files(){const r=await fetch('/api/state',{headers:H});const j=await r.json();const list=document.getElementById('list');
 if(!j.shared.length){list.textContent='Nothing yet.';return}list.innerHTML='';
 for(const f of j.shared){const a=document.createElement('a');a.textContent=f.name+' ('+Math.round(f.size/1024)+' KB)';
  a.href='#';a.onclick=async ev=>{ev.preventDefault();const r=await fetch('/files/'+f.id,{headers:{'X-Jarvis-Token':T}});
  const b=await r.blob();const u=URL.createObjectURL(b);const d=document.createElement('a');d.href=u;d.download=f.name;d.click();};
  list.appendChild(a);list.appendChild(document.createElement('br'));}}
</script></body></html>"""
