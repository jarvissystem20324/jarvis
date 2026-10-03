"""JARVIS as an MCP server — its tools inside Antigravity, Claude Code or Cursor.

    JARVIS.exe --mcp

speaks the Model Context Protocol over stdin/stdout (newline-delimited
JSON-RPC 2.0), so the agent in a coding IDE can ask JARVIS to make slides
about a repo, draw an org chart or a Gantt plan, design a thumbnail, look
up the news or a word, or get a second opinion from JARVIS's own model chain.

What an IDE's agent can reach is deliberately narrower than the chat:
  - only the commands in SAFE_COMMANDS run — things that make files in
    Documents/JARVIS or look something up. Nothing that changes Windows,
    sends a message, deletes, encrypts, runs code or touches a password.
  - there is nobody to answer a permission prompt, so every prompt is a no.
  - nothing is written to stdout except protocol messages; stray prints go
    to stderr, where they can't corrupt the stream.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SAFE_COMMANDS = frozenset({
    # make and write
    "slides", "deck", "pptx", "email", "cv", "resume", "coverletter", "cover", "dilekce", "dilekçe", "petition",
    "cite", "citation", "outline", "grammar", "proofread", "mindmap", "flowchart", "flow", "post", "image", "qr",
    # design
    "design", "tasarla", "thumbnail", "ytthumbnail", "poster", "flyer", "logo", "greeting", "greetingcard", "menu",
    "invitation", "invite", "sticker", "badge", "sale", "saleposter", "diagram", "orgchart", "organigram",
    "familytree", "timeline", "gantt", "comparison", "comparetable", "kanban", "wireframe", "mockup", "ytslides",
    "videoslides", "quizslides", "quizdeck", "palette", "fontpair", "fonts", "headline", "headlines", "critique",
    "designreview", "resize", "magicresize",
    # study and look-ups
    "solve", "equation", "define", "dictionary", "meaning", "synonyms", "antonyms", "thesaurus", "wiki", "wikipedia",
    "word", "wotd", "studyplan", "examplan", "chapters", "translatecode", "convertcode",
    "weather", "calc", "convert", "translate", "time", "date",
    "prayer", "namaz", "ezan", "quake", "quakes", "earthquake", "deprem", "gold", "altin", "altın", "crypto", "stock",
    "stocks", "hisse", "holidays", "tatil", "news", "haber", "air", "aqi", "sun", "sunrise", "sunset",
    # small tools
    "json", "yaml", "b64", "base64", "jwt", "uuid", "port", "ports", "hash", "checksum", "checklink", "linkcheck",
    "phishing", "specs", "sysinfo", "roll", "dice", "flip", "coin", "pick", "random", "sleepcalc", "bedtime",
    "split", "loan", "kredi", "gift", "gifts", "pack", "packing", "mealplan", "workout", "fridge", "recipe",
    "recipes", "funfact", "fact",
})
INSTRUCTIONS = ("JARVIS is the user's desktop assistant. Use it to make things (slides, posters, logos, diagrams, "
                "documents) — they are saved in the user's Documents/JARVIS folder and open on JARVIS's Design page — "
                "or to look things up (news, definitions, prices, weather). jarvis_command lists what it can run.")


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS = [
    {"name": "jarvis_design", "title": "Design something",
     "description": "Design a poster, flyer, YouTube thumbnail, logo, greeting card, menu, invitation, sticker, sale "
                    "poster, slide deck or diagram from a description. Returns the saved design, a PNG preview and "
                    "the file paths. Optional kind forces one: " + ", ".join(
                        ("slides", "thumbnail", "poster", "logo", "card", "menu", "invitation", "sticker", "sale",
                         "orgchart", "familytree", "timeline", "gantt", "comparison", "kanban", "wireframe", "mindmap")),
     "inputSchema": _schema({"description": {"type": "string", "description": "What to make, with the real text, names, dates"},
                             "kind": {"type": "string", "description": "Optional: force a kind"}}, ["description"])},
    {"name": "jarvis_slides", "title": "Make a slide deck",
     "description": "A themed PowerPoint deck with speaker notes about a topic or from given material (paste the "
                    "README or notes in 'material'). Returns the .pptx path and a preview of the cover.",
     "inputSchema": _schema({"topic": {"type": "string"},
                             "material": {"type": "string", "description": "Optional text to base the slides on"},
                             "slides": {"type": "integer", "minimum": 3, "maximum": 20},
                             "theme": {"type": "string", "description": "midnight, paper, ocean, forest, sunset, royal, "
                                                                        "mono, candy, slate, coffee, neon or classroom"}},
                            ["topic"])},
    {"name": "jarvis_diagram", "title": "Draw a diagram",
     "description": "An editable diagram: orgchart, familytree, timeline, gantt, comparison, kanban, wireframe or "
                    "mindmap — from a description, or from structured text (an indented outline; 'task | start | "
                    "end' lines for gantt; 'date: event' lines for a timeline; 'a | b | c' rows for comparison).",
     "inputSchema": _schema({"kind": {"type": "string"}, "description": {"type": "string"}}, ["kind", "description"])},
    {"name": "jarvis_export", "title": "Export a design",
     "description": "Export a saved design (by title, or 'last') as pdf, png, jpg or pptx. Returns the file paths.",
     "inputSchema": _schema({"design": {"type": "string"}, "format": {"type": "string"}}, ["format"])},
    {"name": "jarvis_list_designs", "title": "List designs",
     "description": "The user's saved designs, newest first.", "inputSchema": _schema({}, [])},
    {"name": "jarvis_ask", "title": "Ask JARVIS",
     "description": "Ask JARVIS's own AI chain (Gemini, Groq, Mistral, Cloudflare and others the user set up) for a "
                    "second opinion or a quick answer. Not for long code generation.",
     "inputSchema": _schema({"prompt": {"type": "string"}}, ["prompt"])},
    {"name": "jarvis_command", "title": "Run a JARVIS command",
     "description": "Run one JARVIS slash command and return its answer, e.g. '/news AI chips', '/define entropy', "
                    "'/gold', '/weather Istanbul', '/solve x^2-5x+6=0', '/qr https://…', '/image a logo sketch'. "
                    "Only safe commands run (making things and looking things up); send '/' alone for the list.",
     "inputSchema": _schema({"command": {"type": "string"}}, ["command"])},
]
CLIENTS = ("antigravity", "cursor", "claude")


# --- where it is and how clients start it ----------------------------------------------------------------------

def launch() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]
    return sys.executable, [str(Path(__file__).resolve().parent.parent / "app.py"), "--mcp"]


def entry() -> dict:
    command, args = launch()
    return {"command": command, "args": args}


def config_paths(target: str) -> list[Path]:
    home = Path.home()
    if target == "antigravity":
        paths = [home / ".gemini" / "config" / "mcp_config.json"]
        legacy = home / ".gemini" / "antigravity"
        if legacy.is_dir():
            paths.append(legacy / "mcp_config.json")
        return paths
    if target == "cursor":
        return [home / ".cursor" / "mcp.json"]
    return []


def install(target: str) -> list[Path]:
    """Add (or update) the 'jarvis' entry in a client's MCP config, keeping everything else."""
    written = []
    for path in config_paths(target):
        data: dict = {}
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw) if raw.strip() else {}
            except ValueError:
                raise OSError(f"{path} isn't valid JSON — fix it or remove it first; nothing was changed.") from None
            path.with_suffix(path.suffix + ".bak").write_text(raw, encoding="utf-8")
        if not isinstance(data, dict):
            data = {}
        servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
        servers["jarvis"] = entry()
        data["mcpServers"] = servers
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written


def claude_command() -> str:
    command, args = launch()
    return f'claude mcp add jarvis -- "{command}" ' + " ".join(f'"{a}"' if " " in a else a for a in args)


def describe() -> str:
    snippet = json.dumps({"mcpServers": {"jarvis": entry()}}, indent=2)
    tools = "\n".join(f"  {t['name']:<20} {t['title']}" for t in TOOLS)
    return ("JARVIS can run as an MCP server, so the agent in Antigravity, Claude Code or Cursor can use it:\n"
            f"{tools}\n\n"
            "Set it up in one step:\n"
            "  /mcp setup antigravity   (adds JARVIS to ~/.gemini/config/mcp_config.json)\n"
            "  /mcp setup cursor        (~/.cursor/mcp.json)\n"
            "  /mcp setup claude        (prints the one-line `claude mcp add` command)\n\n"
            f"Or paste this into the client's MCP config yourself:\n{snippet}\n\n"
            "It only runs safe commands (making files and looking things up) and says no to anything that asks "
            "permission. Your keys stay in JARVIS's .env; the IDE never sees them.")


# --- the server --------------------------------------------------------------------------------------------------

class Server:
    def __init__(self, jarvis=None):
        self._jarvis = jarvis
        self._lock = threading.Lock()
        self.log_path: Path | None = None

    @property
    def jarvis(self):
        # Built on first use: initialize must answer at once, and building
        # JARVIS (providers, addons, the vault) takes a moment.
        if self._jarvis is None:
            from .assistant import Jarvis

            self._jarvis = Jarvis(voice_enabled=False)
        return self._jarvis

    # protocol -----------------------------------------------------------------------------------------------

    def handle(self, message):
        if isinstance(message, list):
            replies = [r for r in (self.handle(m) for m in message) if r is not None]
            return replies or None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid request")
        method, mid = message.get("method"), message.get("id")
        if mid is None:
            return None                               # a notification: initialized, cancelled…
        params = message.get("params") or {}
        try:
            if method == "initialize":
                asked = str(params.get("protocolVersion") or "")
                from . import __version__

                return _result(mid, {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                                     "capabilities": {"tools": {"listChanged": False}},
                                     "serverInfo": {"name": "jarvis", "title": "JARVIS", "version": __version__},
                                     "instructions": INSTRUCTIONS})
            if method == "ping":
                return _result(mid, {})
            if method == "tools/list":
                return _result(mid, {"tools": TOOLS})
            if method == "tools/call":
                name = params.get("name")
                if name not in {t["name"] for t in TOOLS}:
                    return _error(mid, -32602, f"Unknown tool: {name}")
                args = params.get("arguments") or {}
                if not isinstance(args, dict):
                    return _error(mid, -32602, "arguments must be an object")
                with self._lock:
                    content, failed = self.call(name, args)
                return _result(mid, {"content": content, "isError": failed})
            return _error(mid, -32601, f"Method not found: {method}")
        except Exception as exc:                       # a tool's bug must not take the server down
            self.log(traceback.format_exc())
            return _result(mid, {"content": [_text(f"JARVIS hit an error: {exc}")], "isError": True})

    # tools ----------------------------------------------------------------------------------------------------

    def call(self, name: str, args: dict) -> tuple[list[dict], bool]:
        if name == "jarvis_ask":
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                return [_text("Give a prompt.")], True
            return [_text(self.jarvis.brain.ask_once(prompt))], False
        if name == "jarvis_list_designs":
            from .design import model

            items = model.listing()
            if not items:
                return [_text("No designs yet.")], False
            return [_text("\n".join(f"{i['title']} — {i['format']}, {i['pages']} page(s): {i['path']}"
                                    for i in items[:40]))], False
        if name == "jarvis_design":
            kind = str(args.get("kind") or "").strip().lower()
            description = str(args.get("description") or "").strip()
            if kind in {"card", "greeting"}:
                return self.run(f"/greeting {description}")
            if kind == "slides":
                return self.run(f"/slides {description}")
            if kind in {"orgchart", "familytree", "timeline", "gantt", "comparison", "kanban", "wireframe", "mindmap"}:
                return self.run(f"/diagram {kind} {description}")
            if kind in {"thumbnail", "poster", "logo", "menu", "invitation", "sticker", "sale"}:
                return self.run(f"/{kind} {description}")
            return self.run(f"/design {description}")
        if name == "jarvis_slides":
            return self.slides(args)
        if name == "jarvis_diagram":
            return self.run(f"/diagram {args.get('kind', '')} {args.get('description', '')}")
        if name == "jarvis_export":
            fmt = str(args.get("format") or "pdf").lower()
            design = str(args.get("design") or "").strip()
            return self.run(f"/design export {fmt} {'' if design.lower() in {'', 'last'} else design}".strip())
        if name == "jarvis_command":
            text = str(args.get("command") or "").strip()
            if not text.startswith("/"):
                text = "/" + text
            name_, _, _ = text[1:].partition(" ")
            if not name_:
                return [_text("Commands available here: " + ", ".join(sorted(SAFE_COMMANDS)))], False
            if name_.lower() not in SAFE_COMMANDS:
                return [_text(f"/{name_} isn't available from the IDE — it changes the PC, sends something, "
                              "or needs a person to confirm. Run it in JARVIS itself.")], True
            return self.run(text)
        return [_text(f"Unknown tool: {name}")], True

    def slides(self, args: dict) -> tuple[list[dict], bool]:
        from . import shield
        from .design import ai, model, pptxio

        topic = str(args.get("topic") or "").strip()
        material = str(args.get("material") or "").strip()
        count = max(3, min(20, int(args.get("slides") or 8)))
        theme = str(args.get("theme") or "midnight").lower()
        if not topic:
            return [_text("Give a topic.")], True
        about = ""
        if material:
            wrapped, _ = shield.wrap(material[:30000], topic)
            about = f"based only on this material ({topic}):\n{shield.RULE}\n\n{wrapped}\n"
        try:
            design = ai.deck_from_topic(self.jarvis.brain, topic, count, theme, about)
        except ai.DesignAIError as exc:
            return [_text(str(exc))], True
        design["title"] = design.get("title") or topic
        pptx = pptxio.export_pptx(design, model.exports_dir() / f"{design['id']}.pptx")
        response = self.jarvis._deliver(design, f"PowerPoint: {pptx}")
        return self._content(response), False

    def run(self, command: str) -> tuple[list[dict], bool]:
        response = self.jarvis.process(command)
        return self._content(response), False

    @staticmethod
    def _content(response) -> list[dict]:
        content = [_text(getattr(response, "text", str(response)) or "(no answer)")]
        paths = list(getattr(response, "image_paths", None) or [])
        if not paths and getattr(response, "image_path", None):
            paths = [response.image_path]
        for path in paths[:2]:
            preview = _preview(Path(path))
            if preview:
                content.append(preview)
        return content

    def log(self, text: str) -> None:
        try:
            if self.log_path is None:
                from .config import get_data_dir

                self.log_path = get_data_dir() / "mcp.log"
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
        except OSError:
            pass


def _text(value: str) -> dict:
    return {"type": "text", "text": str(value)}


def _preview(path: Path) -> dict | None:
    try:
        from PIL import Image

        image = Image.open(path)
        image.thumbnail((1024, 1024))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "PNG", optimize=True)
        return {"type": "image", "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "mimeType": "image/png"}
    except Exception:
        return None


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


# --- running over stdio ------------------------------------------------------------------------------------------

def _std_streams():
    """Binary stdin/stdout — also for the windowed EXE, which Python starts with
    sys.stdin and sys.stdout set to None even when the client handed it pipes."""
    stdin = getattr(sys.stdin, "buffer", None)
    stdout = getattr(sys.stdout, "buffer", None)
    if stdin is not None and stdout is not None:
        return stdin, stdout
    if sys.platform != "win32":
        return os.fdopen(0, "rb", buffering=0), os.fdopen(1, "wb", buffering=0)
    import ctypes
    import msvcrt

    kernel = ctypes.windll.kernel32
    kernel.GetStdHandle.restype = ctypes.c_void_p
    handles = []
    for which, flags in ((-10, os.O_RDONLY), (-11, os.O_WRONLY)):
        handle = kernel.GetStdHandle(which)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError("No stdin/stdout — start JARVIS --mcp from an MCP client.")
        handles.append(msvcrt.open_osfhandle(handle, flags | os.O_BINARY))
    return os.fdopen(handles[0], "rb", buffering=0), os.fdopen(handles[1], "wb", buffering=0)


def serve(stdin, stdout, server: Server | None = None) -> None:
    server = server or Server()
    for raw in iter(stdin.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = _error(None, -32700, "Parse error")
        else:
            reply = server.handle(message)
        if reply is not None:
            stdout.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            stdout.flush()


def main() -> int:
    # Headless: no voice, no global shortcuts, no tour, no screen-time sampling.
    for name in ("JARVIS_HOTKEY", "JARVIS_DICTATE_HOTKEY", "JARVIS_QUICKASK_HOTKEY", "JARVIS_EXPAND_HOTKEY"):
        os.environ[name] = "off"
    os.environ.update({"JARVIS_VOICE": "false", "JARVIS_SCREENTIME": "off", "JARVIS_TOUR": "off",
                       "JARVIS_SUGGEST": "off"})
    stdin, stdout = _std_streams()
    # Anything printed from here on goes to stderr (or nowhere): stdout is the protocol.
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w", encoding="utf-8")
    from . import security

    security.permissions.set_asker(lambda request: False)
    server = Server()
    server.log("started")
    try:
        serve(stdin, stdout, server)
    finally:
        server.log("stopped")
    return 0
