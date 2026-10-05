"""8.0 — Coding tools: JSON/YAML, ports, snippets, README and docstring
writers, code translation, a Python scratchpad, Docker, .env checks, and
Base64/JWT/UUID helpers (hashing lives in /hash).

Docstrings are inserted here, at the lines Python's own parser reports, so
the model can only ever add text — it never rewrites the code around it.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import kit, security, shield
from .registry import command

G = "Coding"
SNIPPETS = kit.Store("snippets.json", {})
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXTENSIONS = {"python": ".py", "javascript": ".js", "typescript": ".ts", "java": ".java", "c#": ".cs", "csharp": ".cs",
              "go": ".go", "rust": ".rs", "c++": ".cpp", "cpp": ".cpp", "c": ".c", "kotlin": ".kt", "swift": ".swift",
              "php": ".php", "ruby": ".rb", "dart": ".dart", "lua": ".lua", "bash": ".sh", "powershell": ".ps1"}
SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode", "target", ".next"}


def _text_or_file(text: str) -> tuple[str, Path | None]:
    path = kit.path_arg(text)
    if path is not None and path.is_file():
        return path.read_text(encoding="utf-8-sig", errors="replace"), path
    return text, None


def decode_jwt(token: str) -> tuple[dict, dict]:
    parts = token.strip().split(".")
    if len(parts) < 2:
        raise ValueError("A JWT has three parts separated by dots.")

    def part(raw: str) -> dict:
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    return part(parts[0]), part(parts[1])


def listening_ports() -> list[tuple[int, int, str]]:
    import psutil

    out = []
    for conn in psutil.net_connections(kind="inet"):
        if conn.status == psutil.CONN_LISTEN and conn.laddr:
            try:
                name = psutil.Process(conn.pid).name() if conn.pid else "?"
            except psutil.Error:
                name = "?"
            out.append((conn.laddr.port, conn.pid or 0, name))
    return sorted(set(out))


def missing_docstrings(source: str) -> list[ast.AST]:
    tree = ast.parse(source)
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node) is None]


def insert_docstrings(source: str, docs: dict[str, str]) -> tuple[str, int]:
    """Put each docstring under its def/class line, bottom-up so line numbers hold."""
    lines = source.splitlines(keepends=True)
    nodes = [n for n in missing_docstrings(source) if n.name in docs and docs[n.name].strip()]
    added = 0
    for node in sorted(nodes, key=lambda n: n.body[0].lineno, reverse=True):
        first = node.body[0]
        if first.lineno == node.lineno:          # one-line body, e.g. def f(): return 1
            continue
        indent = re.match(r"\s*", lines[first.lineno - 1]).group(0)
        text = docs[node.name].strip().replace('"""', "'''").replace("\\", "\\\\")
        body = text.splitlines()
        if len(body) == 1:
            block = f'{indent}"""{body[0]}"""\n'
        else:
            inner = "".join(f"{indent}{line}\n" if line.strip() else "\n" for line in body[1:])
            block = f'{indent}"""{body[0]}\n{inner}{indent}"""\n'
        lines.insert(first.lineno - 1, block)
        added += 1
    return "".join(lines), added


def find_python() -> str | None:
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("py", "python", "python3"):
        found = shutil.which(name)
        if found and "windowsapps" not in found.lower():
            return found
    return None


def env_keys(path: Path) -> dict[str, bool]:
    """{key: has a value} — values themselves are never read out."""
    keys = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if m:
            keys[m.group(1)] = bool(m.group(2).strip().strip('"').strip("'"))
    return keys


class DevTools:
    def _project(self, text: str = "") -> Path | None:
        folder = kit.path_arg(text) if text.strip() else None
        if folder is not None and folder.is_dir():
            return folder
        root = self._root() if hasattr(self, "_root") else None
        return Path(root) if root else None

    @command("json", group=G, usage="/json <file|text> [min|yaml]", help="formats and validates JSON (or converts to YAML)")
    def json_tool(self, args: str, routed: bool = False):
        text = args.strip()
        mode = ""
        m = re.search(r"\s+(min|minify|yaml|to yaml)$", text, re.I)
        if m:
            mode, text = m.group(1).lower(), text[:m.start()]
        if not text:
            return "Usage: /json <file or text> [min|yaml]"
        raw, path = _text_or_file(text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            lines = raw.splitlines()
            near = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
            return f"❌ Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}\n  {near[:120]}\n  {' ' * (exc.colno - 1)}^"
        if "yaml" in mode:
            import yaml

            out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            suffix = ".yaml"
        else:
            out = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if mode.startswith("min") else \
                json.dumps(data, ensure_ascii=False, indent=2)
            suffix = ".json"
        saved = ""
        if path is not None:
            target = kit.output_dir("code") / f"{path.stem}{'.min' if mode.startswith('min') else '.formatted'}{suffix}"
            target.write_text(out, encoding="utf-8")
            saved = f"\nSaved to {target}"
        shown = out if len(out) < 6000 else out[:6000] + "\n…"
        return f"✅ Valid JSON.\n```{'yaml' if 'yaml' in mode else 'json'}\n{shown}\n```{saved}"

    @command("yaml", group=G, usage="/yaml <file|text> [json]", help="validates YAML (or converts to JSON)")
    def yaml_tool(self, args: str, routed: bool = False):
        import yaml

        text = args.strip()
        to_json = bool(re.search(r"\s+(json|to json)$", text, re.I))
        text = re.sub(r"\s+(json|to json)$", "", text, flags=re.I)
        if not text:
            return "Usage: /yaml <file or text> [json]"
        raw, path = _text_or_file(text)
        try:
            documents = list(yaml.safe_load_all(raw))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            return f"❌ Invalid YAML{where}: {getattr(exc, 'problem', exc)}"
        data = documents[0] if len(documents) == 1 else documents
        if to_json:
            out = json.dumps(data, ensure_ascii=False, indent=2, default=str)
            return f"```json\n{out[:6000]}\n```"
        return f"✅ Valid YAML ({len(documents)} document{'s' if len(documents) != 1 else ''})." + \
            (f" Top-level keys: {', '.join(map(str, data))[:300]}" if isinstance(data, dict) else "")

    @command("port", "ports", group=G, usage="/port 3000 · /port kill 3000 · /ports", help="what's using a port, and stopping it")
    def port(self, args: str, routed: bool = False):
        import psutil

        text = args.strip().lower()
        kill = text.startswith(("kill", "free", "stop"))
        number = re.search(r"\d{1,5}", text)
        ports = listening_ports()
        if not number:
            dev = [p for p in ports if p[0] >= 1024]
            if not dev:
                return "Nothing is listening on a port above 1024."
            return "Listening ports:\n" + "\n".join(f"  :{p:<6} {name} (pid {pid})" for p, pid, name in dev[:40])
        n = int(number.group(0))
        users = [(p, pid, name) for p, pid, name in ports if p == n]
        if not users:
            return f"Nothing is listening on port {n}. It's free."
        if not kill:
            details = []
            for _, pid, name in users:
                try:
                    cmd = " ".join(psutil.Process(pid).cmdline())[:160]
                except psutil.Error:
                    cmd = ""
                details.append(f"  {name} (pid {pid})  {cmd}")
            return f"Port {n} is used by:\n" + "\n".join(details) + f"\n/port kill {n} stops it."
        _, pid, name = users[0]
        if not security.permissions.ask(security.RUN_COMMAND, f"stop {name} (pid {pid}) to free port {n}", context="/port"):
            return "Denied."
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
        except psutil.Error as exc:
            return f"Couldn't stop it: {exc}"
        return f"Stopped {name} (pid {pid}). Port {n} is free."

    @command("snippet", "snippets", group=G, usage="/snippet save <name> = <code> · /snippet <name> · /snippets",
             help="your library of code snippets")
    def snippet(self, args: str, routed: bool = False):
        text = args.strip()
        items = SNIPPETS.load()
        m = re.match(r"^(?:save|add)\s+(\S+)(?:\s+(\w+))?\s*=\s*(.+)$", text, re.S | re.I)
        if m:
            code = re.sub(r"^```\w*\n|\n?```$", "", m.group(3).strip())
            items[m.group(1)] = {"code": code, "lang": (m.group(2) or "").lower(), "at": time.time()}
            SNIPPETS.save(items)
            return f"Saved snippet '{m.group(1)}' ({len(code.splitlines())} lines)."
        if text.lower().startswith(("delete ", "remove ")):
            name = text.split(None, 1)[1]
            if items.pop(name, None) is None:
                return f"No snippet '{name}'."
            SNIPPETS.save(items)
            return f"Deleted '{name}'."
        if text and text in items:
            s = items[text]
            return f"```{s.get('lang', '')}\n{s['code']}\n```"
        matches = {k: v for k, v in items.items() if not text or text.lower() in k.lower() or text.lower() in v["code"].lower()}
        if not matches:
            return ("No snippets" + (f" matching '{text}'" if text else "") + ".\n"
                    "  /snippet save fetchjson js = const r = await fetch(url); const data = await r.json();")
        return "Snippets:\n" + "\n".join(f"  {k:<20} {v.get('lang', ''):<8} {v['code'].splitlines()[0][:50] if v['code'] else ''}"
                                         for k, v in sorted(matches.items())) + "\n/snippet <name> shows one (with a Copy button)."

    @command("readme", group=G, usage="/readme [folder]", help="writes a README for your project")
    def readme(self, args: str, routed: bool = False):
        root = self._project(args)
        if root is None:
            return "Open a project first (/project <folder>) or give a folder: /readme <folder>"
        tree, keyfiles = [], []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if any(part in SKIP or part.startswith(".") for part in rel.parts) or len(rel.parts) > 3:
                continue
            if len(tree) < 150:
                tree.append(("  " * (len(rel.parts) - 1)) + rel.name + ("/" if path.is_dir() else ""))
            if path.is_file() and path.name.lower() in {"package.json", "pyproject.toml", "requirements.txt", "setup.py", "cargo.toml",
                                                        "go.mod", "pom.xml", "build.gradle", "main.py", "app.py", "index.js",
                                                        "server.js", "manage.py", "dockerfile", "docker-compose.yml", "makefile"}:
                keyfiles.append(f"--- {rel} ---\n{path.read_text(encoding='utf-8', errors='replace')[:3000]}")
        material, _ = shield.wrap("\n".join(tree) + "\n\n" + "\n\n".join(keyfiles[:8]), str(root))
        answer = self.brain.ask_once(f"""{shield.RULE}
Write a README.md for this project: name and one-line description, features, tech stack, getting started
(prerequisites, install, run — exact commands from the files), project structure, configuration (env vars named
in the files, never values), scripts/commands, contributing and license placeholders. Only claim what the files show.

{material}""")
        body = re.sub(r"^```(?:markdown|md)?\n|\n```$", "", answer.strip())
        target = root / ("README.generated.md" if (root / "README.md").exists() else "README.md")
        if not security.permissions.ask(security.WRITE_FILE, str(target), context="/readme"):
            return f"Denied. Here it is instead:\n\n{body}"
        target.write_text(body + "\n", encoding="utf-8")
        return f"📘 Wrote {target}" + (" (your README.md was left untouched)" if target.name != "README.md" else "")

    @command("docstrings", "docstring", group=G, usage="/docstrings <file.py>", help="adds missing docstrings to a Python file")
    def docstrings(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        if path is None or path.suffix != ".py":
            return "Usage: /docstrings <file.py>   — only missing ones are added; your code isn't touched."
        source = path.read_text(encoding="utf-8")
        try:
            missing = missing_docstrings(source)
        except SyntaxError as exc:
            return f"{path.name} doesn't parse: {exc}"
        if not missing:
            return f"Every function and class in {path.name} already has a docstring. 👌"
        lines = source.splitlines()
        pieces = []
        for node in missing[:60]:
            end = getattr(node, "end_lineno", node.lineno + 20)
            pieces.append("\n".join(lines[node.lineno - 1:min(end, node.lineno + 40)]))
        material, _ = shield.wrap("\n\n".join(pieces), path.name)
        try:
            docs = kit.ask_json(self.brain, f"""{shield.RULE}
Write a concise Google-style docstring for each of these Python functions/classes ({', '.join(n.name for n in missing[:60])}).
One summary line; Args/Returns/Raises sections only where useful. JSON object: {{"name": "docstring text without quotes"}}.

{material}""")
        except kit.KitError as exc:
            return str(exc)
        if not isinstance(docs, dict):
            return "No docstrings came back."
        updated, added = insert_docstrings(source, {str(k): str(v) for k, v in docs.items()})
        try:
            ast.parse(updated)
        except SyntaxError:
            return "The result didn't parse, so nothing was written."
        if not security.permissions.ask(security.WRITE_FILE, f"add {added} docstring(s) to {path}", context="/docstrings"):
            return "Denied."
        backup = path.with_suffix(path.suffix + ".jarvis-bak")
        backup.write_text(source, encoding="utf-8")
        path.write_text(updated, encoding="utf-8")
        return f"📝 Added {added} docstring(s) to {path.name}. The previous version is in {backup.name}."

    @command("translatecode", "convertcode", group=G, usage="/translatecode <file> to <language>",
             help="rewrites a file in another programming language")
    def translate_code(self, args: str, routed: bool = False):
        m = re.match(r'^("[^"]+"|.+?)\s+(?:to|into)\s+([\w#+]+)$', args.strip(), re.I)
        path = kit.path_arg(m.group(1)) if m else None
        if path is None or not path.is_file():
            return "Usage: /translatecode <file> to <language>   e.g. /translatecode utils.py to typescript"
        language = m.group(2).lower()
        source = path.read_text(encoding="utf-8", errors="replace")
        if len(source) > 60000:
            return "That file is too big to translate in one go (60k characters max)."
        material, _ = shield.wrap(source, path.name)
        answer = self.brain.ask_once(f"""{shield.RULE}
Translate this code to idiomatic {language}. Keep behaviour identical; use the standard library or the most common
equivalent packages; keep names and comments. Output only the code in one fenced block, then one line listing any
dependencies to install.

{material}""")
        code = re.search(r"```[\w#+-]*\n(.*?)```", answer, re.S)
        if not code:
            return answer
        out = kit.output_dir("code") / f"{path.stem}{EXTENSIONS.get(language, '.' + language)}"
        out.write_text(code.group(1), encoding="utf-8")
        tail = answer[code.end():].strip()
        return f"🔁 {path.name} → {language}:\n  {out}" + (f"\n{tail}" if tail else "")

    @command("py", "python", group=G, usage="/py <code>", help="runs a Python snippet (15 s limit)")
    def python_scratch(self, args: str, routed: bool = False):
        code = re.sub(r"^```(?:python|py)?\n|\n?```$", "", args.strip())
        if not code:
            return "Usage: /py <python code>   e.g. /py print(sum(i*i for i in range(10)))"
        interpreter = find_python()
        if interpreter is None:
            return "No Python found on this PC. Install it from python.org (tick 'Add to PATH')."
        if not security.permissions.ask(security.RUN_COMMAND, f"run this Python:\n{code[:400]}", context="/py"):
            return "Denied."
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "scratch.py"
            script.write_text(code, encoding="utf-8")
            started = time.time()
            try:
                result = subprocess.run([interpreter, "-I", str(script)], cwd=folder, capture_output=True, text=True,
                                        timeout=15, creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                return "⏱ Stopped after 15 seconds."
        output = (result.stdout + (("\n" + result.stderr) if result.stderr else "")).strip() or "(no output)"
        if len(output) > 5000:
            output = output[:5000] + "\n…"
        return f"```\n{output}\n```\n{'✅' if result.returncode == 0 else '❌ exit ' + str(result.returncode)} in {time.time() - started:.2f}s"

    @command("docker", group=G, usage="/docker [ps|images|logs <name>|stop <name>|start <name>]", help="your containers")
    def docker(self, args: str, routed: bool = False):
        exe = shutil.which("docker")
        if exe is None:
            return "Docker isn't installed (or not on PATH)."
        verb, _, name = args.strip().partition(" ")
        verb = verb.lower() or "ps"
        commands = {"ps": ["ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
                    "images": ["images", "--format", "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"],
                    "logs": ["logs", "--tail", "60", name], "stop": ["stop", name], "start": ["start", name],
                    "restart": ["restart", name], "stats": ["stats", "--no-stream"]}
        if verb not in commands or (verb in {"logs", "stop", "start", "restart"} and not name):
            return "Usage: /docker ps · images · stats · logs <name> · stop|start|restart <name>"
        if verb in {"stop", "start", "restart"} and not security.permissions.ask(security.RUN_COMMAND, f"docker {verb} {name}", context="/docker"):
            return "Denied."
        try:
            result = subprocess.run([exe, *commands[verb]], capture_output=True, text=True, timeout=30,
                                    creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return "Docker didn't answer in 30 seconds — is Docker Desktop running?"
        out = (result.stdout or result.stderr).strip()
        if "cannot connect" in out.lower() or "is the docker daemon running" in out.lower():
            return "Docker Desktop isn't running. Start it and try again."
        return f"```\n{out[-5000:] or '(nothing)'}\n```"

    @command("envcheck", group=G, usage="/envcheck [folder]", help="compares .env with .env.example (never shows values)")
    def env_check(self, args: str, routed: bool = False):
        root = self._project(args) or Path.cwd()
        env = root / ".env"
        example = next((root / n for n in (".env.example", ".env.sample", ".env.template", "example.env") if (root / n).exists()), None)
        if not env.exists() and example is None:
            return f"No .env or .env.example in {root}."
        lines = [f"🔎 {root}"]
        have = env_keys(env) if env.exists() else {}
        if example is not None:
            wanted = env_keys(example)
            missing = [k for k in wanted if k not in have]
            extra = [k for k in have if k not in wanted]
            lines.append(f"  missing from .env: {', '.join(missing) or 'none ✓'}")
            lines.append(f"  in .env but not in {example.name}: {', '.join(extra) or 'none ✓'}")
        empty = [k for k, filled in have.items() if not filled]
        if empty:
            lines.append(f"  empty in .env: {', '.join(empty)}")
        gitignore = root / ".gitignore"
        if env.exists() and (not gitignore.exists() or not re.search(r"^\s*\.env\s*$|^\s*\.env\*|^\s*\*\.env", gitignore.read_text(encoding="utf-8", errors="replace"), re.M)):
            lines.append("  ⚠ .env is not in .gitignore — add it before you commit.")
        if env.exists() and shutil.which("git"):
            try:
                tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"], cwd=root, capture_output=True,
                                         timeout=20, creationflags=NO_WINDOW).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                tracked = False
            if tracked:
                lines.append("  🚨 .env is committed to git! Remove it (git rm --cached .env) and rotate every key in it.")
        lines.append("(Values are never read out.)")
        return "\n".join(lines)

    @command("b64", "base64", group=G, usage="/b64 encode|decode <text>", help="Base64 encode and decode")
    def b64(self, args: str, routed: bool = False):
        verb, _, text = args.strip().partition(" ")
        if verb.lower() in {"encode", "enc", "e"}:
            return base64.b64encode(text.encode("utf-8")).decode("ascii")
        if verb.lower() in {"decode", "dec", "d"}:
            try:
                raw = base64.b64decode(text.strip() + "=" * (-len(text.strip()) % 4), altchars=b"-_" if "-" in text or "_" in text else None)
                return raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return "That isn't valid Base64 text."
        return "Usage: /b64 encode <text>  ·  /b64 decode <base64>"

    @command("jwt", group=G, usage="/jwt <token>", help="decodes a JWT's header and claims (not verified)")
    def jwt(self, args: str, routed: bool = False):
        try:
            header, claims = decode_jwt(args)
        except (ValueError, json.JSONDecodeError) as exc:
            return f"Couldn't decode it: {exc}"
        notes = []
        for key in ("iat", "nbf", "exp"):
            if isinstance(claims.get(key), (int, float)):
                moment = datetime.fromtimestamp(claims[key])
                notes.append(f"  {key}: {moment:%Y-%m-%d %H:%M:%S}" + (" — EXPIRED" if key == "exp" and claims[key] < time.time() else ""))
        return (f"Header:\n```json\n{json.dumps(header, indent=2)}\n```\nClaims:\n```json\n{json.dumps(claims, indent=2, ensure_ascii=False)}\n```\n"
                + "\n".join(notes) + "\n⚠ Decoded only — the signature was not verified. Don't paste production tokens anywhere you don't trust.")

    @command("uuid", group=G, usage="/uuid [n]", help="random UUIDs")
    def uuid_cmd(self, args: str, routed: bool = False):
        n = min(int(args.strip()) if args.strip().isdigit() else 1, 50)
        return "\n".join(str(uuid.uuid4()) for _ in range(n))
