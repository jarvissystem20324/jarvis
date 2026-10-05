"""10.0 coding: run code in many languages, regex, cURL to Python, JSON to
types, URLs, formatting, project stats, .gitignore, git branches and history,
GitHub, error search, starters, pip, EXE builds, VS Code, Python docs,
shortcut sheets and Python lessons.

Every command that runs a program or writes into a project asks first, and
none of them goes through a shell: programs are started with an argument
list, so a file name can never smuggle in a second command.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from .. import kit, security, shield
from ..registry import command, field, split

G = "Coding"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode", ".mypy_cache",
        ".pytest_cache", "target", "bin", "obj", ".next", "coverage"}
LANGS = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript",
         ".tsx": "TypeScript", ".jsx": "JavaScript", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++",
         ".hpp": "C++", ".cc": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
         ".swift": "Swift", ".kt": "Kotlin", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".sql": "SQL",
         ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch", ".md": "Markdown", ".json": "JSON", ".yml": "YAML",
         ".yaml": "YAML", ".toml": "TOML", ".xml": "XML", ".vue": "Vue", ".dart": "Dart", ".lua": "Lua", ".r": "R"}
COMMENT = {"Python": "#", "Ruby": "#", "Shell": "#", "PowerShell": "#", "YAML": "#", "TOML": "#", "R": "#",
           "SQL": "--", "Lua": "--"}


class CodingError(Exception):
    pass


def project_root(jarvis, given: str = "") -> Path:
    raw = (given or "").strip().strip('"')
    if raw:
        path = Path(raw).expanduser()
        if path.is_dir():
            return path
        raise CodingError(f"No folder {raw}")
    root = None
    try:
        root = jarvis._root()
    except Exception:
        pass
    if root is None:
        raise CodingError("No project open. Open a folder on the Coding page, or /project <folder>.")
    return Path(root)


def run_program(argv: list[str], cwd: Path | None = None, timeout: int = 60, stdin: str = "") -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, timeout=timeout,
                              input=stdin.encode() if stdin else None, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise CodingError(f"{argv[0]} isn't installed (or isn't on PATH).") from None
    except subprocess.TimeoutExpired:
        return -1, f"(stopped after {timeout} s)"
    except OSError as exc:                     # there, but it wouldn't start (blocked, needs admin…)
        raise CodingError(f"{Path(argv[0]).name} wouldn't start: {exc}") from None
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out[-20000:]


# --- running code -------------------------------------------------------------------

def python_for(folder: Path | None) -> str:
    """The project's own venv Python if it has one; otherwise this one."""
    if folder is not None:
        for candidate in (folder / "venv" / "Scripts" / "python.exe", folder / ".venv" / "Scripts" / "python.exe",
                          folder / "venv" / "bin" / "python", folder / ".venv" / "bin" / "python"):
            if candidate.exists():
                return str(candidate)
    if getattr(sys, "frozen", False):
        # Not shutil.which("python") alone: on many PCs that's the Microsoft Store's stub,
        # which opens the Store instead of running anything.
        from ..devtools import find_python

        return find_python() or "python"
    return sys.executable


def runner_for(path: Path) -> tuple[list[list[str]], str]:
    """How to run a file: a list of commands (compile, then run) and a label."""
    suffix = path.suffix.lower()
    folder = path.parent
    out = str(folder / (path.stem + (".exe" if os.name == "nt" else "")))
    which = shutil.which
    if suffix == ".py":
        return [[python_for(folder), str(path)]], "Python"
    if suffix in {".js", ".mjs", ".cjs"}:
        return [[which("node") or "node", str(path)]], "Node.js"
    if suffix == ".ts":
        if which("tsx"):
            return [[which("tsx"), str(path)]], "tsx"
        return [[which("npx") or "npx", "--yes", "tsx", str(path)]], "npx tsx"
    if suffix == ".java":
        return [[which("java") or "java", str(path)]], "Java (single file)"
    if suffix == ".c":
        compiler = which("gcc") or which("clang") or "gcc"
        return [[compiler, str(path), "-o", out], [out]], Path(compiler).stem
    if suffix in {".cpp", ".cc"}:
        compiler = which("g++") or which("clang++") or "g++"
        return [[compiler, str(path), "-o", out], [out]], Path(compiler).stem
    if suffix == ".go":
        return [[which("go") or "go", "run", str(path)]], "Go"
    if suffix == ".rs":
        return [[which("rustc") or "rustc", str(path), "-o", out], [out]], "Rust"
    if suffix == ".rb":
        return [[which("ruby") or "ruby", str(path)]], "Ruby"
    if suffix == ".php":
        return [[which("php") or "php", str(path)]], "PHP"
    if suffix == ".ps1":
        return [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)]], "PowerShell"
    if suffix in {".bat", ".cmd"}:
        return [["cmd", "/d", "/c", str(path)]], "Batch"
    if suffix == ".cs":
        return [[which("dotnet") or "dotnet", "run", "--project", str(folder)]], ".NET"
    if suffix == ".lua":
        return [[which("lua") or "lua", str(path)]], "Lua"
    raise CodingError(f"I don't know how to run {suffix or 'that'} files.")


def run_file(path: Path, stdin: str = "", timeout: int = 60) -> tuple[int, str, str]:
    steps, label = runner_for(path)
    output = []
    code = 0
    for argv in steps:
        code, text = run_program(argv, cwd=path.parent, timeout=timeout, stdin=stdin)
        output.append(text)
        if code != 0:
            break
    return code, "".join(output).strip(), label


# --- regex ---------------------------------------------------------------------------

def regex_test(pattern: str, text: str, flags: str = "") -> dict:
    value = 0
    for letter in flags.lower():
        value |= {"i": re.I, "m": re.M, "s": re.S, "x": re.X}.get(letter, 0)
    compiled = re.compile(pattern, value)
    matches = []
    for m in compiled.finditer(text):
        matches.append({"match": m.group(0), "span": m.span(), "groups": m.groups(),
                        "named": m.groupdict()})
        if len(matches) >= 200:
            break
    return {"count": len(matches), "matches": matches}


REGEX_PARTS = [(r"\\d", "a digit"), (r"\\w", "a letter, digit or _"), (r"\\s", "whitespace"), (r"\\b", "a word edge"),
               (r"\.", "any character"), (r"\^", "start of line"), (r"\$", "end of line"), (r"\+", "one or more"),
               (r"\*", "zero or more"), (r"\?", "optional"), (r"\{(\d+)(,\d*)?\}", "repeated")]


# --- cURL ----------------------------------------------------------------------------

def curl_to_python(command: str) -> str:
    text = command.strip().replace("\\\n", " ").replace("^\n", " ")
    if text.startswith("curl"):
        text = text[4:]
    try:
        parts = shlex.split(text, posix=True)
    except ValueError as exc:
        raise CodingError(f"I couldn't read that command: {exc}") from None
    method = ""
    url = ""
    headers: dict[str, str] = {}
    data = None
    json_body = None
    auth = None
    files: dict[str, str] = {}
    insecure = False  # curl -k: the generated code skips certificate checks, as the command did
    params_get = False
    i = 0
    while i < len(parts):
        part = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        if part in {"-X", "--request"}:
            method, i = nxt.upper(), i + 2
            continue
        if part in {"-H", "--header"}:
            key, _, value = nxt.partition(":")
            headers[key.strip()] = value.strip()
            i += 2
            continue
        if part in {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"}:
            data = nxt if data is None else f"{data}&{nxt}"
            i += 2
            continue
        if part == "--json":
            json_body = nxt
            i += 2
            continue
        if part in {"-u", "--user"}:
            user, _, password = nxt.partition(":")
            auth = (user, password)
            i += 2
            continue
        if part in {"-F", "--form"}:
            key, _, value = nxt.partition("=")
            files[key] = value
            i += 2
            continue
        if part in {"-k", "--insecure"}:
            insecure = True
        elif part in {"-G", "--get"}:
            params_get = True
        elif part in {"-A", "--user-agent"}:
            headers["User-Agent"] = nxt
            i += 2
            continue
        elif part in {"-b", "--cookie"}:
            headers["Cookie"] = nxt
            i += 2
            continue
        elif part in {"-e", "--referer"}:
            headers["Referer"] = nxt
            i += 2
            continue
        elif not part.startswith("-") and not url:
            url = part
        i += 1
    if not url:
        raise CodingError("No URL in that cURL command.")
    if data is not None and headers.get("Content-Type", headers.get("content-type", "")).startswith("application/json"):
        json_body, data = data, None
    method = method or ("POST" if (data is not None or json_body or files) and not params_get else "GET")
    lines = ["import requests", ""]
    args = [repr(url)]
    if headers:
        lines.append("headers = " + json.dumps(headers, indent=4, ensure_ascii=False))
        args.append("headers=headers")
    if json_body:
        try:
            parsed = json.loads(json_body)
            lines.append("payload = " + _pyrepr(parsed))
        except ValueError:
            lines.append(f"payload = {json_body!r}")
        args.append("json=payload")
        headers.pop("Content-Type", None)
    elif data is not None:
        if params_get:
            lines.append(f"params = dict(urllib.parse.parse_qsl({data!r}))")
            lines.insert(0, "import urllib.parse")
            args.append("params=params")
        else:
            pairs = urllib.parse.parse_qsl(data, keep_blank_values=True)
            if pairs and "=" in data and not data.strip().startswith(("{", "[")):
                lines.append("data = " + json.dumps(dict(pairs), indent=4, ensure_ascii=False))
            else:
                lines.append(f"data = {data!r}")
            args.append("data=data")
    if files:
        entries = ", ".join(f"{k!r}: open({v[1:]!r}, 'rb')" if v.startswith("@") else f"{k!r}: (None, {v!r})"
                            for k, v in files.items())
        lines.append(f"files = {{{entries}}}")
        args.append("files=files")
    if auth:
        args.append(f"auth={auth!r}")
    if insecure:
        args.append("verify=False")
    lines += ["", f"response = requests.{method.lower() if method in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'} else 'request'}("
              + ("" if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"} else f"{method!r}, ")
              + ", ".join(args) + ", timeout=30)", "response.raise_for_status()", "print(response.status_code)",
              "print(response.text[:2000])"]
    return "\n".join(lines)


def _pyrepr(value, indent: int = 0) -> str:
    return json.dumps(value, indent=4, ensure_ascii=False).replace("true", "True").replace("false", "False") \
        .replace("null", "None")


# --- JSON to types -------------------------------------------------------------------

def _pascal(name: str) -> str:
    words = re.split(r"[^0-9A-Za-z]+", name)
    out = "".join(w[:1].upper() + w[1:] for w in words if w)
    return out if out and not out[0].isdigit() else f"T{out}"


def _snake(name: str) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "_", name)
    text = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", text).lower().strip("_")
    return text if text and not text[0].isdigit() else f"f_{text}"


def json_to_types(data, language: str = "python", root: str = "Root") -> str:
    language = language.lower().strip()
    language = {"py": "python", "ts": "typescript", "golang": "go", "c#": "csharp", "cs": "csharp"}.get(language,
                                                                                                    language)
    if language not in {"python", "typescript", "go", "csharp", "java"}:
        raise CodingError(f"I can write types for python, typescript, go, csharp or java — not '{language}'.")
    classes: list[tuple[str, list[tuple[str, str, bool]]]] = []

    def kind(value, name: str) -> str:
        if isinstance(value, bool):
            return {"python": "bool", "typescript": "boolean", "go": "bool", "csharp": "bool", "java": "boolean"}[language]
        if isinstance(value, int):
            return {"python": "int", "typescript": "number", "go": "int64", "csharp": "long", "java": "long"}[language]
        if isinstance(value, float):
            return {"python": "float", "typescript": "number", "go": "float64", "csharp": "double", "java": "double"}[language]
        if isinstance(value, str):
            return {"python": "str", "typescript": "string", "go": "string", "csharp": "string", "java": "String"}[language]
        if value is None:
            return {"python": "Any", "typescript": "unknown", "go": "interface{}", "csharp": "object", "java": "Object"}[language]
        if isinstance(value, list):
            inner = kind(_merge(value), name[:-1] if name.endswith("s") else f"{name}Item") if value else \
                {"python": "Any", "typescript": "unknown", "go": "interface{}", "csharp": "object", "java": "Object"}[language]
            return {"python": f"list[{inner}]", "typescript": f"{inner}[]", "go": f"[]{inner}",
                    "csharp": f"List<{inner}>", "java": f"List<{inner}>"}[language]
        if isinstance(value, dict):
            cls = _pascal(name)
            fields = [(k, kind(v, k), v is None) for k, v in value.items()]
            if not any(c[0] == cls for c in classes):
                classes.append((cls, fields))
            return cls
        return "Any"

    if isinstance(data, list):
        data = _merge(data) if data else {}
    kind(data, root)
    out: list[str] = []
    if language == "python":
        out += ["from __future__ import annotations", "", "from dataclasses import dataclass", "from typing import Any", ""]
        for cls, fields in reversed(classes):
            out += ["@dataclass", f"class {cls}:"]
            out += [f"    {_snake(k)}: {t}" + (" | None = None" if optional else "") for k, t, optional in fields] or \
                ["    pass"]
            out.append("")
    elif language == "typescript":
        for cls, fields in reversed(classes):
            out.append(f"export interface {cls} {{")
            out += [f"  {k if re.fullmatch(r'[A-Za-z_$][\w$]*', k) else json.dumps(k)}{'?' if optional else ''}: {t};"
                    for k, t, optional in fields]
            out += ["}", ""]
    elif language == "go":
        for cls, fields in reversed(classes):
            out.append(f"type {cls} struct {{")
            out += [f"\t{_pascal(k)} {('*' if optional else '') + t} `json:\"{k}\"`" for k, t, optional in fields]
            out += ["}", ""]
    elif language == "csharp":
        out += ["using System.Collections.Generic;", "using System.Text.Json.Serialization;", ""]
        for cls, fields in reversed(classes):
            out.append(f"public class {cls}\n{{")
            out += [f"    [JsonPropertyName(\"{k}\")]\n    public {t}{'?' if optional else ''} {_pascal(k)} {{ get; set; }}"
                    for k, t, optional in fields]
            out += ["}", ""]
    elif language == "java":
        out += ["import java.util.List;", ""]
        for cls, fields in reversed(classes):
            out.append(f"public class {cls} {{")
            out += [f"    public {t} {_camel(k)};" for k, t, _ in fields]
            out += ["}", ""]
    else:
        raise CodingError("Languages: python, typescript, go, csharp, java")
    return "\n".join(out).rstrip() + "\n"


def _camel(name: str) -> str:
    p = _pascal(name)
    return p[:1].lower() + p[1:]


def _merge(items: list):
    """One representative value for a list: dicts merged so every key appears."""
    dicts = [i for i in items if isinstance(i, dict)]
    if dicts:
        merged: dict = {}
        for d in dicts:
            for k, v in d.items():
                if k not in merged or merged[k] is None:
                    merged[k] = v
        for k in merged:
            if any(k not in d for d in dicts) and merged[k] is not None:
                pass
        return merged
    return items[0]


# --- markdown preview ------------------------------------------------------------------

def markdown_to_html(text: str, title: str = "Preview") -> str:
    import html

    out = []
    in_code = False
    in_list = None
    for raw in text.splitlines():
        if raw.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                out.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw))
            continue
        line = html.escape(raw)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", line)
        line = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        bullet = re.match(r"^\s*[-*+]\s+(.*)", line)
        number = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if bullet or number:
            tag = "ul" if bullet else "ol"
            if in_list != tag:
                if in_list:
                    out.append(f"</{in_list}>")
                out.append(f"<{tag}>")
                in_list = tag
            out.append(f"<li>{(bullet or number).group(1)}</li>")
            continue
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            n = len(heading.group(1))
            out.append(f"<h{n}>{heading.group(2)}</h{n}>")
        elif line.strip().startswith("&gt;"):
            out.append(f"<blockquote>{line.strip()[4:].strip()}</blockquote>")
        elif re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", line):
            out.append("<hr>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append(f"</{in_list}>")
    if in_code:
        out.append("</code></pre>")
    style = ("body{font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin:40px auto;line-height:1.6;"
             "color:#1f2430;padding:0 16px}pre{background:#f4f6fa;padding:12px;border-radius:8px;overflow:auto}"
             "code{font-family:Consolas,monospace;background:#f4f6fa;padding:1px 4px;border-radius:4px}"
             "blockquote{border-left:4px solid #c9d3e3;margin:0;padding-left:12px;color:#555}img{max-width:100%}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{style}</style></head><body>{''.join(out)}</body></html>")


# --- project stats ---------------------------------------------------------------------

def project_stats(root: Path, limit: int = 20000) -> dict:
    by_lang: dict[str, dict[str, int]] = {}
    biggest: list[tuple[int, str]] = []
    files = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for name in names:
            path = Path(folder) / name
            lang = LANGS.get(path.suffix.lower())
            if not lang:
                continue
            files += 1
            if files > limit:
                break
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            marker = COMMENT.get(lang, "//")
            blank = sum(1 for l in lines if not l.strip())
            comment = sum(1 for l in lines if l.strip().startswith((marker, "/*", "*", "<!--", '"""')))
            row = by_lang.setdefault(lang, {"files": 0, "code": 0, "comment": 0, "blank": 0})
            row["files"] += 1
            row["blank"] += blank
            row["comment"] += comment
            row["code"] += len(lines) - blank - comment
            biggest.append((len(lines), str(path.relative_to(root))))
    biggest.sort(reverse=True)
    return {"files": files, "languages": by_lang, "biggest": biggest[:8]}


# --- .gitignore ------------------------------------------------------------------------

GITIGNORE = {
    "python": "__pycache__/\n*.py[cod]\n*.egg-info/\n.eggs/\nbuild/\ndist/\n.venv/\nvenv/\nenv/\n.pytest_cache/\n"
              ".mypy_cache/\n.ruff_cache/\n.coverage\nhtmlcov/\n.ipynb_checkpoints/\n.env\n",
    "node": "node_modules/\nnpm-debug.log*\nyarn-debug.log*\nyarn-error.log*\npnpm-debug.log*\n.next/\nout/\ndist/\n"
            "build/\n.cache/\ncoverage/\n.env\n.env.local\n",
    "java": "*.class\n*.jar\n*.war\ntarget/\nbuild/\n.gradle/\nout/\nhs_err_pid*\n",
    "csharp": "bin/\nobj/\n*.user\n*.suo\n.vs/\n*.nupkg\nTestResults/\n",
    "go": "*.exe\n*.test\n*.out\nvendor/\ngo.work\n",
    "rust": "target/\nCargo.lock\n**/*.rs.bk\n",
    "cpp": "*.o\n*.obj\n*.exe\n*.out\n*.a\n*.lib\n*.so\n*.dll\nbuild/\ncmake-build-*/\n",
    "unity": "[Ll]ibrary/\n[Tt]emp/\n[Oo]bj/\n[Bb]uild/\n[Bb]uilds/\n[Ll]ogs/\n[Uu]ser[Ss]ettings/\n*.csproj\n*.sln\n",
    "vscode": ".vscode/*\n!.vscode/settings.json\n!.vscode/extensions.json\n",
    "jetbrains": ".idea/\n*.iml\n",
    "windows": "Thumbs.db\nehthumbs.db\nDesktop.ini\n$RECYCLE.BIN/\n",
    "macos": ".DS_Store\n.AppleDouble\n._*\n",
    "secrets": ".env\n.env.*\n!.env.example\n*.pem\n*.key\nsecrets.json\n",
}
GITIGNORE_ALIASES = {"py": "python", "js": "node", "javascript": "node", "typescript": "node", "ts": "node",
                     "react": "node", "vue": "node", "c#": "csharp", "dotnet": "csharp", ".net": "csharp",
                     "c++": "cpp", "c": "cpp", "vs": "vscode", "code": "vscode", "pycharm": "jetbrains",
                     "intellij": "jetbrains", "mac": "macos", "win": "windows", "env": "secrets"}


def gitignore(choices: list[str]) -> str:
    keys = []
    for choice in choices:
        key = GITIGNORE_ALIASES.get(choice.lower().strip(), choice.lower().strip())
        if key in GITIGNORE and key not in keys:
            keys.append(key)
    if not keys:
        raise CodingError("Pick from: " + ", ".join(GITIGNORE))
    return "\n".join(f"# {k}\n{GITIGNORE[k]}" for k in keys)


# --- starters ---------------------------------------------------------------------------

STARTERS = {
    "python-cli": {"main.py": 'import argparse\n\n\ndef main() -> None:\n    parser = argparse.ArgumentParser(description="{name}")\n'
                              '    parser.add_argument("name", nargs="?", default="world")\n    args = parser.parse_args()\n'
                              '    print(f"Hello, {{args.name}}!")\n\n\nif __name__ == "__main__":\n    main()\n',
                   "requirements.txt": "", "README.md": "# {name}\n\n```\npython main.py\n```\n",
                   ".gitignore": GITIGNORE["python"]},
    "flask": {"app.py": 'from flask import Flask, render_template\n\napp = Flask(__name__)\n\n\n@app.route("/")\ndef home():\n'
                        '    return render_template("index.html", title="{name}")\n\n\nif __name__ == "__main__":\n'
                        '    app.run(debug=True)\n',
              "templates/index.html": "<!doctype html>\n<html><head><meta charset='utf-8'><title>{{{{ title }}}}</title>"
                                      "\n<link rel='stylesheet' href='/static/style.css'></head>\n<body><h1>{{{{ title }}}}"
                                      "</h1><p>It works.</p></body></html>\n",
              "static/style.css": "body { font-family: system-ui, sans-serif; margin: 40px; }\n",
              "requirements.txt": "flask>=3.0\n", "README.md": "# {name}\n\n```\npip install -r requirements.txt\n"
                                                             "python app.py\n```\n", ".gitignore": GITIGNORE["python"]},
    "fastapi": {"main.py": 'from fastapi import FastAPI\n\napp = FastAPI(title="{name}")\n\n\n@app.get("/")\ndef root():\n'
                           '    return {{"message": "Hello from {name}"}}\n',
                "requirements.txt": "fastapi>=0.110\nuvicorn[standard]>=0.29\n",
                "README.md": "# {name}\n\n```\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n",
                ".gitignore": GITIGNORE["python"]},
    "node-express": {"index.js": "const express = require('express');\n\nconst app = express();\napp.use(express.json());\n\n"
                                 "app.get('/', (req, res) => res.json({{ message: 'Hello from {name}' }}));\n\n"
                                 "app.listen(3000, () => console.log('http://localhost:3000'));\n",
                     "package.json": '{{\n  "name": "{slug}",\n  "version": "1.0.0",\n  "main": "index.js",\n'
                                     '  "scripts": {{ "start": "node index.js" }},\n  "dependencies": {{ "express": "^4.19.0" }}\n}}\n',
                     "README.md": "# {name}\n\n```\nnpm install\nnpm start\n```\n", ".gitignore": GITIGNORE["node"]},
    "static-site": {"index.html": "<!doctype html>\n<html lang='en'>\n<head>\n<meta charset='utf-8'>\n<meta name='viewport' "
                                  "content='width=device-width, initial-scale=1'>\n<title>{name}</title>\n<link rel='stylesheet' "
                                  "href='style.css'>\n</head>\n<body>\n<header><h1>{name}</h1></header>\n<main><p>Start here."
                                  "</p></main>\n<script src='script.js'></script>\n</body>\n</html>\n",
                    "style.css": "* {{ box-sizing: border-box; }}\nbody {{ font-family: system-ui, sans-serif; margin: 0; "
                                 "padding: 40px; }}\n", "script.js": "console.log('{name} loaded');\n"},
    "tkinter-app": {"app.py": 'import tkinter as tk\n\n\ndef main() -> None:\n    root = tk.Tk()\n    root.title("{name}")\n'
                              '    tk.Label(root, text="Hello from {name}", font=("Segoe UI", 16)).pack(padx=40, pady=30)\n'
                              '    tk.Button(root, text="Quit", command=root.destroy).pack(pady=(0, 20))\n'
                              '    root.mainloop()\n\n\nif __name__ == "__main__":\n    main()\n',
                    "README.md": "# {name}\n\n```\npython app.py\n```\n", ".gitignore": GITIGNORE["python"]},
    "discord-bot": {"bot.py": 'import os\n\nimport discord\n\nintents = discord.Intents.default()\nintents.message_content = True\n'
                              'client = discord.Client(intents=intents)\n\n\n@client.event\nasync def on_message(message):\n'
                              '    if message.author == client.user:\n        return\n    if message.content == "!ping":\n'
                              '        await message.channel.send("pong")\n\n\nclient.run(os.environ["DISCORD_TOKEN"])\n',
                    "requirements.txt": "discord.py>=2.3\n", ".env.example": "DISCORD_TOKEN=\n",
                    "README.md": "# {name}\n\nPut your bot token in `.env` (see `.env.example`) — never commit it.\n",
                    ".gitignore": GITIGNORE["python"] + GITIGNORE["secrets"]},
}


# --- shortcuts ----------------------------------------------------------------------------

SHORTCUTS = {
    "vscode": [("Ctrl+P", "Go to file"), ("Ctrl+Shift+P", "Command palette"), ("Ctrl+D", "Select next match"),
               ("Alt+↑/↓", "Move line"), ("Shift+Alt+↓", "Copy line down"), ("Ctrl+/", "Toggle comment"),
               ("F12", "Go to definition"), ("Shift+F12", "Find references"), ("F2", "Rename symbol"),
               ("Ctrl+`", "Terminal"), ("Ctrl+B", "Sidebar"), ("Ctrl+Shift+F", "Search in files"),
               ("Alt+Click", "Add a cursor"), ("Ctrl+Shift+K", "Delete line"), ("Shift+Alt+F", "Format document"),
               ("F5", "Debug"), ("Ctrl+K Ctrl+S", "All shortcuts")],
    "pycharm": [("Shift Shift", "Search everywhere"), ("Ctrl+Shift+A", "Find action"), ("Ctrl+B", "Go to declaration"),
                ("Alt+F7", "Find usages"), ("Shift+F6", "Rename"), ("Ctrl+Alt+L", "Reformat"), ("Ctrl+/", "Comment"),
                ("Ctrl+D", "Duplicate line"), ("Ctrl+Y", "Delete line"), ("Shift+F10", "Run"), ("Shift+F9", "Debug"),
                ("Alt+Enter", "Quick fix"), ("Ctrl+E", "Recent files"), ("Ctrl+Alt+T", "Surround with")],
    "visualstudio": [("Ctrl+,", "Go to all"), ("F12", "Go to definition"), ("Shift+F12", "Find references"),
                     ("Ctrl+R Ctrl+R", "Rename"), ("Ctrl+K Ctrl+D", "Format document"), ("Ctrl+K Ctrl+C", "Comment"),
                     ("Ctrl+K Ctrl+U", "Uncomment"), ("F5", "Start debugging"), ("Ctrl+F5", "Run without debugging"),
                     ("F9", "Breakpoint"), ("F10", "Step over"), ("F11", "Step into"), ("Ctrl+.", "Quick actions")],
    "vim": [("i / a", "Insert before / after"), ("Esc", "Normal mode"), (":w / :q / :wq", "Save / quit / both"),
            ("dd / yy / p", "Delete / copy / paste line"), ("u / Ctrl+R", "Undo / redo"), ("/word", "Search"),
            ("n / N", "Next / previous match"), ("gg / G", "Top / bottom"), ("w / b", "Next / previous word"),
            ("ciw", "Change word"), (".", "Repeat"), (":%s/a/b/g", "Replace all")],
    "jarvis": [("Ctrl+S", "Save the file"), ("F5", "Run the file"), ("Ctrl+F", "Find in the file"),
               ("Ctrl+Shift+F", "Find in the project"), ("Ctrl+N", "New file"), ("Ctrl+W", "Close the tab"),
               ("Ctrl+/", "Comment or uncomment"), ("Tab / Shift+Tab", "Indent / outdent"),
               ("Ctrl+Enter", "Ask the agent about the selection")],
}


# --- Python lessons ------------------------------------------------------------------------

LESSONS = [
    {"id": "print", "title": "1. Hello, print", "text": "print() shows text. Text goes in quotes.\n\n    print('Hello')\n",
     "task": "Print exactly: Hello, JARVIS", "start": "", "check": {"stdout": "Hello, JARVIS"}},
    {"id": "variables", "title": "2. Variables", "text": "A variable keeps a value under a name.\n\n    age = 15\n"
                                                         "    print(age + 1)\n",
     "task": "Make a variable city = 'Istanbul' and print it.", "start": "city = \n", "check": {"stdout": "Istanbul"}},
    {"id": "math", "title": "3. Numbers", "text": "+ - * / work like a calculator; // divides to a whole number and "
                                                  "% gives the remainder; ** is power.\n",
     "task": "Print 17 // 5 and 17 % 5 on separate lines.", "start": "", "check": {"stdout": "3\n2"}},
    {"id": "input", "title": "4. Strings", "text": "Strings have methods: 'hi'.upper(), len('hi'), f'{name}!'.\n",
     "task": "name = 'ada'. Print it in capitals using .upper().", "start": "name = 'ada'\n", "check": {"stdout": "ADA"}},
    {"id": "if", "title": "5. if / else", "text": "if decides:\n\n    if x > 10:\n        print('big')\n    else:\n"
                                                  "        print('small')\n",
     "task": "x = 7. Print 'odd' if x is odd, otherwise 'even'.", "start": "x = 7\n", "check": {"stdout": "odd"}},
    {"id": "for", "title": "6. for loops", "text": "for repeats:\n\n    for i in range(3):\n        print(i)\n",
     "task": "Print the numbers 1 to 5, one per line.", "start": "", "check": {"stdout": "1\n2\n3\n4\n5"}},
    {"id": "lists", "title": "7. Lists", "text": "A list holds many values: nums = [3, 1, 2]; nums.append(5); "
                                                "sorted(nums); sum(nums).\n",
     "task": "nums = [4, 8, 15, 16, 23, 42]. Print their sum.", "start": "nums = [4, 8, 15, 16, 23, 42]\n",
     "check": {"stdout": "108"}},
    {"id": "functions", "title": "8. Functions", "text": "def makes a reusable function:\n\n    def double(n):\n"
                                                         "        return n * 2\n",
     "task": "Write square(n) that returns n squared.", "start": "def square(n):\n    pass\n",
     "check": {"tests": "assert square(3) == 9\nassert square(-4) == 16\nassert square(0) == 0"}},
    {"id": "dicts", "title": "9. Dictionaries", "text": "A dict maps keys to values: ages = {'ali': 15}; ages['ali'].\n",
     "task": "Write count_letters(word) returning a dict of letter → count.",
     "start": "def count_letters(word):\n    counts = {}\n    return counts\n",
     "check": {"tests": "assert count_letters('banana') == {'b': 1, 'a': 3, 'n': 2}\nassert count_letters('') == {}"}},
    {"id": "while", "title": "10. while", "text": "while repeats until its condition is false. Make sure it ends!\n",
     "task": "Write countdown(n) returning a list from n down to 1.",
     "start": "def countdown(n):\n    result = []\n    return result\n",
     "check": {"tests": "assert countdown(3) == [3, 2, 1]\nassert countdown(1) == [1]"}},
    {"id": "files", "title": "11. Errors", "text": "try/except catches errors so a program can carry on.\n\n"
                                                   "    try:\n        int('x')\n    except ValueError:\n        ...\n",
     "task": "Write safe_int(text) returning int(text), or 0 if it isn't a number.",
     "start": "def safe_int(text):\n    pass\n",
     "check": {"tests": "assert safe_int('42') == 42\nassert safe_int('abc') == 0\nassert safe_int('-7') == -7"}},
    {"id": "classes", "title": "12. Classes", "text": "A class bundles data and functions:\n\n    class Dog:\n"
                                                      "        def __init__(self, name):\n            self.name = name\n",
     "task": "Write class Counter with add() and value (starts at 0).",
     "start": "class Counter:\n    def __init__(self):\n        pass\n",
     "check": {"tests": "c = Counter()\nc.add(); c.add()\nassert c.value == 2"}},
]
LESSON_PROGRESS = kit.Store("python_lessons.json", {})


def check_lesson(lesson: dict, code: str, python: str | None = None) -> tuple[bool, str]:
    import tempfile

    check = lesson["check"]
    program = code
    if "tests" in check:
        program = code + "\n\n" + check["tests"] + "\nprint('ALL TESTS PASSED')\n"
    folder = Path(tempfile.mkdtemp(prefix="jarvis-lesson-"))
    path = folder / "lesson.py"
    path.write_text(program, encoding="utf-8")
    code_, out = run_program([python or python_for(None), "-I", str(path)], cwd=folder, timeout=10)
    out = out.strip()
    if "tests" in check:
        ok = code_ == 0 and out.endswith("ALL TESTS PASSED")
        return ok, ("✔ All tests passed!" if ok else out[-1500:] or "Not yet.")
    ok = code_ == 0 and out.replace("\r\n", "\n") == check["stdout"]
    return ok, ("✔ Correct!" if ok else f"Your output:\n{out[-800:]}\n\nExpected:\n{check['stdout']}")


class Coding:
    @command("runcode", "runfile", group=G, usage="/runcode <file> [| input]",
             help="runs a file in its language (Python, JS, TS, Java, C, C++, Go, Rust, Ruby, PHP, PowerShell…)",
             title="Run a file in any language", icon="▶", page="code",
             fields=(field("file", "file", "File"), field("stdin", "long", "Input for the program", optional=True)),
             keywords="execute node javascript java c++ go")
    def runcode_cmd(self, args: str, routed: bool = False):
        path_text, stdin = split(args, 2)
        path = kit.path_arg(path_text)
        if path is None or not path.is_file():
            return "Usage: /runcode <file>"
        try:
            steps, label = runner_for(path)
        except CodingError as exc:
            return str(exc)
        if not security.permissions.ask(security.RUN_COMMAND, " && ".join(" ".join(s) for s in steps),
                                        context="/runcode"):
            return "Not run."
        started = time.monotonic()
        try:
            code, output, label = run_file(path, stdin)
        except CodingError as exc:
            return str(exc)
        security.audit.record("runcode", path.name, f"exit {code}")
        return (f"▶ {path.name} ({label}) — exit {code} in {time.monotonic() - started:.1f} s\n\n" +
                (output or "(no output)"))

    @command("regex", group=G, usage="/regex <pattern> | <text> [| flags im] · /regex build <description>",
             help="test a regular expression, or have one written", title="Regex builder and tester", icon=".*",
             page="code", fields=(field("pattern", "text", "Pattern (or: build <description>)", r"\b\d{3}-\d{4}\b"),
                                  field("text", "long", "Text to test", "call 555-1234 or 555-9876"),
                                  field("flags", "text", "Flags (i m s x)", optional=True)))
    def regex_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower().startswith("build "):
            data = kit.ask_json(self.brain, (
                "Write a Python regular expression for this. JSON only: {\"pattern\": str, \"explain\": str, "
                "\"examples_match\": [3 strings], \"examples_no_match\": [2 strings]}\n\n" + text[6:]))
            if not isinstance(data, dict) or not data.get("pattern"):
                return "No pattern came back — try describing it differently."
            pattern = data["pattern"]
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                return f"The AI's pattern doesn't compile ({exc}): {pattern}"
            checks = [f"  {'✔' if compiled.search(s) else '✘'} should match: {s}" for s in data.get("examples_match", [])]
            checks += [f"  {'✔' if not compiled.search(s) else '✘'} should not: {s}" for s in data.get("examples_no_match", [])]
            return f".* {pattern}\n{data.get('explain', '')}\n\nTested here:\n" + "\n".join(checks)
        pattern, sample, flags = split(text, 3)
        if not pattern:
            return "Usage: /regex <pattern> | <text>   or   /regex build <what it should match>"
        try:
            result = regex_test(pattern, sample, flags)
        except re.error as exc:
            return f"That pattern has an error: {exc}"
        if not result["count"]:
            return "No matches."
        lines = [f".* {result['count']} match(es):"]
        for m in result["matches"][:30]:
            extra = f"  groups {m['groups']}" if m["groups"] else ""
            lines.append(f"  [{m['span'][0]}:{m['span'][1]}] {m['match']!r}{extra}")
        return "\n".join(lines)

    @command("curl2py", "curltopython", group=G, usage="/curl2py <curl command>",
             help="turns a cURL command into Python requests code", title="cURL to Python", icon="🐍", page="code",
             fields=(field("curl", "long", "cURL command", "curl -X POST https://api.example.com/items -H "
                                                         "'Content-Type: application/json' -d '{\"name\": \"pen\"}'"),))
    def curl2py_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /curl2py curl https://…"
        try:
            return "```python\n" + curl_to_python(args) + "\n```"
        except CodingError as exc:
            return str(exc)

    @command("json2types", "jsontypes", group=G, usage="/json2types <json or file> | python|typescript|go|csharp|java",
             help="classes or types from a JSON example", title="JSON to classes and types", icon="🧬", page="code",
             fields=(field("json", "long", "JSON (or a .json file)", '{"id": 1, "name": "Ada", "tags": ["x"]}'),
                     field("language", "choice", "Language", "python", ("python", "typescript", "go", "csharp", "java")),
                     field("root", "text", "Root name", "Root")))
    def json2types_cmd(self, args: str, routed: bool = False):
        body, language, root = split(args, 3)
        path = kit.path_arg(body) if len(body) < 300 else None
        if path is not None and path.is_file():
            body = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(body)
        except ValueError as exc:
            return f"That isn't valid JSON: {exc}"
        try:
            code = json_to_types(data, language or "python", root or "Root")
        except CodingError as exc:
            return str(exc)
        fence = {"python": "python", "typescript": "ts", "go": "go", "csharp": "csharp", "java": "java"}.get(
            (language or "python").lower(), "")
        return f"```{fence}\n{code}```"

    @command("url", "urlcode", group=G, usage="/url encode|decode|parse <text>",
             help="URL-encode, decode, or take a link apart", title="URL encode and decode", icon="🔗", page="code",
             fields=(field("action", "choice", "Action", "decode", ("encode", "decode", "parse")),
                     field("text", "long", "Text or URL")), template="{action} {text}")
    def url_cmd(self, args: str, routed: bool = False):
        action, _, text = args.strip().partition(" ")
        action = action.lower()
        if action == "encode":
            return urllib.parse.quote(text, safe="")
        if action == "decode":
            return urllib.parse.unquote_plus(text)
        if action == "parse":
            p = urllib.parse.urlparse(text.strip())
            lines = [f"scheme: {p.scheme}", f"host: {p.hostname}", f"port: {p.port or ''}", f"path: {p.path}"]
            if p.query:
                lines.append("query:")
                lines += [f"  {k} = {v}" for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)]
            if p.fragment:
                lines.append(f"fragment: {p.fragment}")
            return "\n".join(lines)
        return "Usage: /url encode|decode|parse <text>"

    @command("preview", "mdpreview", group=G, usage="/preview <file.md|.html>",
             help="opens Markdown or HTML in your browser, rendered", title="HTML and Markdown preview", icon="👁",
             page="code", fields=(field("file", "file", "File", types=(("Markdown or HTML", "*.md *.html *.htm"),)),))
    def preview_cmd(self, args: str, routed: bool = False):
        import webbrowser

        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /preview <file.md or .html>"
        if path.suffix.lower() in {".md", ".markdown", ".txt"}:
            html_path = kit.output_dir("documents") / f"{path.stem}_preview.html"
            html_path.write_text(markdown_to_html(path.read_text(encoding="utf-8", errors="replace"), path.stem),
                                 encoding="utf-8")
        else:
            html_path = path
        webbrowser.open(html_path.resolve().as_uri())
        return f"👁 Opened {html_path.name} in your browser."

    @command("formatcode", "fmt", group=G, usage="/formatcode <file.py>",
             help="formats Python with Black or Ruff if installed (tidies whitespace either way)",
             title="Format Python code", icon="🧹", page="code", fields=(field("file", "file", "Python file",
                                                                             types=(("Python", "*.py"),)),))
    def formatcode_cmd(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        if path is None or path.suffix.lower() != ".py":
            return "Usage: /formatcode <file.py>"
        if not security.permissions.ask(security.WRITE_FILE, str(path), context="/formatcode"):
            return "Left it as it was."
        python = python_for(path.parent)
        for tool in (["-m", "ruff", "format"], ["-m", "black", "-q"]):
            code, out = run_program([python, *tool, str(path)], timeout=60)
            if code == 0:
                return f"🧹 Formatted with {tool[1]}: {path.name}"
        original = path.read_text(encoding="utf-8")
        tidy = "\n".join(line.rstrip().replace("\t", "    ") for line in original.splitlines()).rstrip() + "\n"
        tidy = re.sub(r"\n{4,}", "\n\n\n", tidy)
        if tidy != original:
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_text(original, encoding="utf-8")
            path.write_text(tidy, encoding="utf-8")
            return (f"🧹 Tidied {path.name} (trailing spaces, tabs, blank lines; backup {backup.name}). For full "
                    "formatting: /pip install black")
        return "Already tidy. For full formatting install Black: /pip install black"

    @command("projectstats", "loc", group=G, usage="/projectstats [folder]",
             help="lines of code by language, comments, biggest files", title="Project stats", icon="📊", page="code",
             fields=(field("folder", "folder", "Folder (blank: the open project)", optional=True),))
    def projectstats_cmd(self, args: str, routed: bool = False):
        try:
            root = project_root(self, args)
        except CodingError as exc:
            return str(exc)
        stats = project_stats(root)
        if not stats["files"]:
            return f"No code files in {root.name}."
        rows = sorted(stats["languages"].items(), key=lambda kv: -kv[1]["code"])
        total = sum(r["code"] for _, r in rows) or 1
        lines = [f"📊 {root.name}: {stats['files']} files, {total:,} lines of code"]
        for lang, r in rows:
            lines.append(f"  {lang:<11} {r['files']:>5} files  {r['code']:>8,} code  {r['comment']:>6,} comments  "
                         f"{100 * r['code'] / total:4.0f}%")
        lines.append("Biggest files: " + ", ".join(f"{name} ({n:,})" for n, name in stats["biggest"][:5]))
        return "\n".join(lines)

    @command("gitignore", group=G, usage="/gitignore python, node, vscode [| write]",
             help="a .gitignore for your languages and tools", title=".gitignore maker", icon="🙈", page="code",
             fields=(field("for", "text", "Languages and tools", "python, vscode, windows"),
                     field("write", "choice", "Write it into the open project?", "no", ("no", "write"))))
    def gitignore_cmd(self, args: str, routed: bool = False):
        choices, write = split(args, 2)
        try:
            body = gitignore([c for c in re.split(r"[,\s]+", choices) if c])
        except CodingError as exc:
            return str(exc)
        if write.strip().lower() == "write":
            try:
                root = project_root(self)
            except CodingError as exc:
                return str(exc)
            target = root / ".gitignore"
            if not security.permissions.ask(security.WRITE_FILE, str(target), context="/gitignore"):
                return body
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            new = [line for line in body.splitlines() if line and line not in existing.splitlines()]
            target.write_text(existing.rstrip() + ("\n\n" if existing else "") + "\n".join(new) + "\n", encoding="utf-8")
            return f"🙈 Added {len(new)} line(s) to {target}"
        return "```gitignore\n" + body + "```"

    def _git(self, root: Path, *argv: str, timeout: int = 30) -> tuple[int, str]:
        git = shutil.which("git")
        if not git:
            raise CodingError("Git isn't installed.")
        return run_program([git, *argv], cwd=root, timeout=timeout)

    @command("branch", "branches", group=G, usage="/branch [list] · /branch new <name> · /branch switch <name> · /branch delete <name> · /branch merge <name>",
             help="your git branches: list, create, switch, delete, merge", title="Git branch manager", icon="🌿",
             page="code", fields=(field("action", "choice", "Action", "list", ("list", "new", "switch", "delete",
                                                                               "merge")),
                                  field("name", "text", "Branch", optional=True)),
             template="{action} {name}")
    def branch_cmd(self, args: str, routed: bool = False):
        verb, _, name = args.strip().partition(" ")
        verb = (verb or "list").lower()
        name = name.strip()
        try:
            root = project_root(self)
            if verb in {"list", ""}:
                code, out = self._git(root, "branch", "-vv", "--sort=-committerdate")
                return "🌿 Branches:\n" + out if code == 0 else out
            if not re.fullmatch(r"[\w./-]{1,100}", name or ""):
                return "Give a branch name (letters, numbers, - _ / .)."
            argv = {"new": ["switch", "-c", name], "switch": ["switch", name], "delete": ["branch", "-d", name],
                    "merge": ["merge", "--no-ff", name]}.get(verb)
            if argv is None:
                return "Usage: /branch list|new|switch|delete|merge <name>"
            if not security.permissions.ask(security.RUN_COMMAND, "git " + " ".join(argv), context="/branch"):
                return "Nothing changed."
            code, out = self._git(root, *argv)
            security.audit.record("branch", f"{verb} {name}", f"exit {code}")
            return ("🌿 " if code == 0 else "⚠ ") + (out.strip() or f"{verb} {name}: done")
        except CodingError as exc:
            return str(exc)

    @command("gitgraph", "gitlog", group=G, usage="/gitgraph [n]", help="the commit history as a graph",
             title="Git history graph", icon="🕸", page="code", fields=(field("count", "number", "Commits", "40"),))
    def gitgraph_cmd(self, args: str, routed: bool = False):
        n = re.search(r"\d+", args or "")
        try:
            root = project_root(self)
            code, out = self._git(root, "log", "--graph", "--oneline", "--decorate", "--all", "--date=short",
                                  "--format=%h %ad %an  %s%d", f"-n{n.group(0) if n else 40}")
        except CodingError as exc:
            return str(exc)
        return "```\n" + out.strip() + "\n```" if code == 0 else out

    @command("github", "repo", group=G, usage="/github <owner/repo or link>",
             help="a GitHub repository at a glance: stars, issues, languages, latest release",
             title="GitHub repo info", icon="🐙", page="code",
             fields=(field("repo", "text", "owner/repo or link", "python/cpython"),))
    def github_cmd(self, args: str, routed: bool = False):
        m = re.search(r"(?:github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", args.strip())
        if not m:
            return "Usage: /github owner/repo"
        owner, repo = m.group(1), m.group(2)
        from ..config import get_setting

        token = get_setting("GITHUB_TOKEN", "").strip()
        headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
        base = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            info = kit.get_json(base, headers=headers)
        except kit.KitError as exc:
            return f"GitHub didn't answer for {owner}/{repo}: {exc}"
        try:
            languages = kit.get_json(base + "/languages", headers=headers)
        except kit.KitError:
            languages = {}
        try:
            release = kit.get_json(base + "/releases/latest", headers=headers)
        except kit.KitError:
            release = {}
        total = sum(languages.values()) or 1
        langs = ", ".join(f"{k} {100 * v / total:.0f}%" for k, v in list(languages.items())[:5])
        return "\n".join(filter(None, [
            f"🐙 {info.get('full_name')} — {info.get('description') or ''}",
            f"  ★ {info.get('stargazers_count', 0):,}  ⑂ {info.get('forks_count', 0):,}  "
            f"open issues+PRs {info.get('open_issues_count', 0):,}  watchers {info.get('subscribers_count', 0):,}",
            f"  Languages: {langs}" if langs else "",
            f"  Latest release: {release.get('tag_name')} ({(release.get('published_at') or '')[:10]})" if release.get(
                "tag_name") else "",
            f"  Last push: {(info.get('pushed_at') or '')[:10]} · licence {((info.get('license') or {}).get('spdx_id')) or '—'}"
            f" · default branch {info.get('default_branch')}",
            f"  {info.get('html_url')}"]))

    @command("errorsearch", "searcherror", group=G, usage="/errorsearch <error message>",
             help="searches the web for an error and sums up the likely fix", title="Search an error on the web",
             icon="🧯", page="code", fields=(field("error", "long", "Error message"),))
    def errorsearch_cmd(self, args: str, routed: bool = False):
        from .. import websearch

        error = args.strip()
        if not error:
            return "Usage: /errorsearch <the error message>"
        key = error.splitlines()[-1][:200] if "\n" in error else error[:200]
        query = f"{key} site:stackoverflow.com OR site:github.com"
        try:
            results = websearch.search(query)
        except Exception as exc:
            return f"The web search failed: {exc}"
        if not results:
            return self.web(f"How do I fix this error: {key}")
        listing = "\n".join(f"- {r.title}: {r.url}\n  {r.snippet[:300]}" for r in results[:6])
        wrapped, _ = shield.wrap(listing, "search results")
        summary = self.brain.ask_once(f"{shield.RULE}\nFrom these search results, give the most likely cause and fix "
                                      f"for this error in 4-6 lines, citing which result.\nError: {key}\n\n{wrapped}")
        return f"🧯 {summary.strip()}\n\n" + "\n".join(f"  • {r.url}" for r in results[:5])

    @command("starter", "newproject", group=G, usage="/starter <flask|fastapi|node-express|static-site|python-cli|tkinter-app|discord-bot> | <folder> | [name]",
             help="a new project with the files to get going", title="Project starters", icon="🧱", page="code",
             fields=(field("kind", "choice", "Kind", "flask", tuple(STARTERS)),
                     field("folder", "folder", "Where (a new folder is made inside)"),
                     field("name", "text", "Project name", "my-app")))
    def starter_cmd(self, args: str, routed: bool = False):
        kind, folder, name = split(args, 3)
        kind = kind.lower().strip()
        if kind not in STARTERS:
            return "Starters: " + ", ".join(STARTERS)
        parent = Path(folder.strip().strip('"')).expanduser() if folder else Path.home() / "Projects"
        name = (name or "my-app").strip()
        target = parent / kit.slug(name)
        if target.exists() and any(target.iterdir()):
            return f"{target} already exists and isn't empty."
        if not security.permissions.ask(security.WRITE_FILE, str(target), context="/starter"):
            return "Nothing written."
        for rel, body in STARTERS[kind].items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.format(name=name, slug=kit.slug(name).lower()), encoding="utf-8")
        security.audit.record("starter", kind, str(target))
        return f"🧱 {kind} project created:\n  {target}\nOpen it on the Coding page."

    @command("pip", group=G, usage="/pip list|outdated|show <pkg>|install <pkg>|uninstall <pkg>",
             help="Python packages for the open project (or JARVIS's Python)", title="Pip package manager", icon="📦",
             page="code", fields=(field("action", "choice", "Action", "list", ("list", "outdated", "show", "install",
                                                                               "uninstall")),
                                  field("package", "text", "Package", optional=True)),
             template="{action} {package}")
    def pip_cmd(self, args: str, routed: bool = False):
        verb, _, package = args.strip().partition(" ")
        verb = (verb or "list").lower()
        package = package.strip()
        try:
            root = project_root(self)
        except CodingError:
            root = None
        python = python_for(root)
        try:
            if verb in {"list", "outdated"}:
                argv = [python, "-m", "pip", "list", "--disable-pip-version-check"] + \
                    (["--outdated"] if verb == "outdated" else [])
                code, out = run_program(argv, timeout=120)
                return f"📦 {python}\n" + out
            if not re.fullmatch(r"[A-Za-z0-9._\-\[\],<>=!~ ]{1,120}", package or ""):
                return "Give a package name, e.g. /pip install requests"
            if verb == "show":
                return run_program([python, "-m", "pip", "show", package], timeout=60)[1]
            if verb not in {"install", "uninstall"}:
                return "Usage: /pip list|outdated|show|install|uninstall <package>"
            argv = [python, "-m", "pip", verb, "--disable-pip-version-check"] + \
                (["-y"] if verb == "uninstall" else []) + package.split()
            if not security.permissions.ask(security.RUN_COMMAND, " ".join(argv), context="/pip"):
                return "Nothing installed."
            code, out = run_program(argv, timeout=600)
        except CodingError as exc:
            return f"📦 {exc}"
        security.audit.record("pip", f"{verb} {package}", f"exit {code}")
        return ("📦 " if code == 0 else "⚠ ") + out[-3000:]

    @command("buildexe", "pyinstaller", group=G, usage="/buildexe <script.py> | [onefile] | [windowed] | [icon.ico]",
             help="a Windows .exe from a Python script (PyInstaller)", title="Build an EXE from a script", icon="🏗",
             page="code", fields=(field("script", "file", "Script", types=(("Python", "*.py"),)),
                                  field("onefile", "choice", "Package", "onefile", ("onefile", "folder")),
                                  field("window", "choice", "Console", "console", ("console", "windowed")),
                                  field("icon", "file", "Icon (.ico)", optional=True, types=(("Icon", "*.ico"),))))
    def buildexe_cmd(self, args: str, routed: bool = False):
        script_text, onefile, window, icon = split(args, 4)
        script = kit.path_arg(script_text)
        if script is None or script.suffix.lower() != ".py":
            return "Usage: /buildexe <script.py> | onefile | windowed"
        python = python_for(script.parent)
        code, _ = run_program([python, "-m", "PyInstaller", "--version"], timeout=60)
        if code != 0:
            return "PyInstaller isn't installed for that Python. Install it first: /pip install pyinstaller"
        argv = [python, "-m", "PyInstaller", "--noconfirm", "--clean", str(script)]
        if (onefile or "onefile") == "onefile":
            argv.insert(4, "--onefile")
        if (window or "").lower() == "windowed":
            argv.insert(4, "--windowed")
        icon_path = kit.path_arg(icon) if icon else None
        if icon_path is not None:
            argv[4:4] = ["--icon", str(icon_path)]
        if not security.permissions.ask(security.RUN_COMMAND, " ".join(argv), context="/buildexe"):
            return "Not built."
        code, out = run_program(argv, cwd=script.parent, timeout=1800)
        exe = script.parent / "dist" / (script.stem + ".exe")
        if code == 0 and exe.exists():
            return f"🏗 Built {exe.name} ({kit.size(exe.stat().st_size)}):\n  {exe}"
        if code == 0:
            return f"🏗 Built into {script.parent / 'dist' / script.stem}"
        return "⚠ The build failed:\n" + out[-3000:]

    @command("vscode", group=G, usage="/vscode [folder or file]", help="opens the project (or a file) in VS Code",
             title="Open in VS Code", icon="🟦", page="code", fields=(field("path", "text", "Folder or file (blank: the "
                                                                                       "open project)", optional=True),))
    def vscode_cmd(self, args: str, routed: bool = False):
        target = args.strip().strip('"')
        if not target:
            try:
                target = str(project_root(self))
            except CodingError as exc:
                return str(exc)
        code_cli = shutil.which("code")
        if not code_cli:
            for candidate in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                              Path(os.environ.get("ProgramFiles", "")) / "Microsoft VS Code" / "bin" / "code.cmd"):
                if candidate.exists():
                    code_cli = str(candidate)
                    break
        if not code_cli:
            return "VS Code isn't installed (or `code` isn't on PATH). Get it from code.visualstudio.com."
        try:
            subprocess.Popen([code_cli, target], creationflags=NO_WINDOW)
        except OSError as exc:
            return f"VS Code wouldn't start: {exc}"
        return f"🟦 Opened {target} in VS Code."

    @command("pydoc", "pyhelp", group=G, usage="/pydoc <name>   e.g. /pydoc str.split · /pydoc pathlib",
             help="Python's own documentation for a module, function or method", title="Python docs lookup", icon="📘",
             page="code", fields=(field("name", "text", "Name", "str.split"),))
    def pydoc_cmd(self, args: str, routed: bool = False):
        import pydoc

        name = args.strip()
        if not re.fullmatch(r"[A-Za-z_][\w.]*", name):
            return "Usage: /pydoc str.split"
        try:
            obj, _ = pydoc.resolve(name)
            text = pydoc.render_doc(obj, renderer=pydoc.plaintext)
        except Exception:
            return f"Python has no built-in docs for {name}. Try: https://docs.python.org/3/search.html?q={name}"
        text = re.sub(r".\x08", "", text)
        head = text[:3500]
        module = name.split(".")[0]
        return f"📘 {head}\n\n…more: https://docs.python.org/3/library/{module}.html" if len(text) > 3500 else f"📘 {text}"

    @command("ideshortcuts", "shortcutsheet", group=G, usage="/ideshortcuts <vscode|pycharm|visualstudio|vim|jarvis>",
             help="keyboard shortcut cheat sheets for editors", title="IDE shortcut cheat sheets", icon="⌨", page="code",
             fields=(field("editor", "choice", "Editor", "vscode", tuple(SHORTCUTS)),))
    def ideshortcuts_cmd(self, args: str, routed: bool = False):
        editor = args.strip().lower().replace(" ", "").replace("code", "vscode").replace("vsvscode", "vscode")
        if editor not in SHORTCUTS:
            return "Editors: " + ", ".join(SHORTCUTS)
        return f"⌨ {editor}:\n" + "\n".join(f"  {k:<16} {v}" for k, v in SHORTCUTS[editor])

    @command("pylesson", "learnpython", group=G, usage="/pylesson [n]", help="Python lessons with exercises that check "
             "themselves (best on the Coding page)", title="Learn Python", icon="🎓", page="code",
             fields=(field("lesson", "number", "Lesson", "1"),))
    def pylesson_cmd(self, args: str, routed: bool = False):
        progress = LESSON_PROGRESS.load()
        m = re.search(r"\d+", args or "")
        if not m:
            return "🎓 Python lessons:\n" + "\n".join(f"  {'✔' if progress.get(l['id']) else '○'} {l['title']}"
                                                     for l in LESSONS) + "\nOpen one: /pylesson 3 (or use the Coding page)"
        n = max(1, min(len(LESSONS), int(m.group(0))))
        lesson = LESSONS[n - 1]
        return f"🎓 {lesson['title']}\n\n{lesson['text']}\nTask: {lesson['task']}\n\nStart with:\n" \
               f"```python\n{lesson['start'] or '# your code'}\n```\nCheck it on the Coding page → Learn Python."
