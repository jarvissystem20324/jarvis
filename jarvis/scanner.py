"""Static analysis: what is wrong with this code, and what would it do?

Two jobs, one engine.

`scan()` answers "is there a security problem here" — hardcoded secrets,
injection, unsafe deserialization, TLS turned off. Every rule below exists
because it is a bug someone actually ships, and one of them (`shell=True` with
user text) is a bug this project itself shipped and had to fix.

`capabilities()` answers "what would this do if I ran it" — the network it
touches, the files it writes, the processes it spawns, whether it is
obfuscated. That is Sandbox Mode: JARVIS reads untrusted code and tells you
what it is for, and never executes it. Analysis cannot be escaped by a program
that behaves differently when watched, because nothing is ever running.

A found secret is reported by *shape*, never by value. The whole point is to
warn you without copying the key somewhere new.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_SCAN_BYTES = 400_000
# Folders whose contents are not the user's code and would drown the report.
SKIP_DIRS = {
    ".git", "venv", ".venv", "node_modules", "__pycache__", "dist", "build",
    ".idea", ".vscode", "release", "site-packages", ".mypy_cache", ".pytest_cache",
}
SCAN_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".cs",
    ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat", ".html", ".sql",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".txt", ".md",
}


@dataclass
class Finding:
    level: str        # "high" | "warn" | "info"
    rule: str
    detail: str
    file: str = ""
    line: int = 0
    excerpt: str = ""

    def format(self) -> str:
        where = f"{self.file}:{self.line}" if self.file else ""
        head = f"  [{self.level.upper():4}] {self.rule}"
        if where:
            head += f"  ({where})"
        body = f"\n         {self.detail}"
        snippet = f"\n         > {self.excerpt}" if self.excerpt else ""
        return head + body + snippet


# --- secrets --------------------------------------------------------------
# Matched by prefix and length, which is what makes a key recognisable
# without ever needing to print one.

SECRET_RULES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "OpenAI"),
    ("Groq key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), "Groq"),
    ("NVIDIA key", re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"), "NVIDIA"),
    ("Google API key", re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}"), "Google"),
    ("Google OAuth key", re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}"), "Google"),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}"), "GitHub"),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"), "GitHub"),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS"),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack"),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic"),
)

GENERIC_SECRET = re.compile(
    r"""(?ix)
    \b (?: api[_-]?key | secret | passwd | password | token | auth )
    \s* [:=] \s*
    ['"] ([^'"\s]{16,}) ['"]
    """
)
# Values that look like secrets but are placeholders, not leaks.
PLACEHOLDER = re.compile(
    r"(?i)^(your|my|the)?[_\-]?(api|key|token|secret|xxx+|placeholder|example|"
    r"changeme|insert|todo|none|null|test|dummy|sample|\.\.\.)"
)


def _mask(value: str) -> str:
    """Show enough to find it, never enough to use it."""
    value = value.strip()
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 12}{value[-3:]}  ({len(value)} chars)"


# --- dangerous code -------------------------------------------------------
# (level, rule, pattern, explanation, which file suffixes it applies to)

CODE_RULES: tuple[tuple[str, str, re.Pattern, str, tuple[str, ...]], ...] = (
    ("high", "Shell injection risk", re.compile(r"shell\s*=\s*True"),
     "With shell=True, any & | ; or backtick in the command string is executed "
     "by the shell. Pass a list of arguments instead.", (".py",)),
    ("high", "os.system with a built string", re.compile(r"os\.system\s*\(\s*[^)'\"]*[f'\"+%]"),
     "os.system always goes through the shell, so anything interpolated into "
     "it can run its own commands.", (".py",)),
    ("high", "eval on runtime data", re.compile(r"\beval\s*\("),
     "eval runs whatever it is handed. If any part of the string came from "
     "outside the program, so does the code.", (".py", ".js", ".ts", ".jsx", ".tsx")),
    ("high", "exec on runtime data", re.compile(r"\bexec\s*\("),
     "Same problem as eval: arbitrary code, decided at runtime.", (".py",)),
    ("high", "Unsafe deserialization", re.compile(r"\bpickle\.loads?\s*\(|\byaml\.load\s*\((?![^)]*Safe)"),
     "pickle and yaml.load execute code while decoding. A malicious file is a "
     "malicious program. Use json, or yaml.safe_load.", (".py",)),
    ("high", "TLS verification disabled", re.compile(r"verify\s*=\s*False|_create_unverified_context"),
     "This accepts any certificate, so the connection can be read and altered "
     "by whatever is in the middle of it.", (".py",)),
    ("high", "SQL built by string formatting",
     re.compile(r"""(?i)(execute|executemany|query)\s*\(\s*(?:f['"]|['"][^'"]*['"]\s*[%+]|['"][^'"]*\{)"""),
     "Values pasted into SQL text become SQL. Use parameters (?, %s) and let "
     "the driver do the quoting.", (".py", ".js", ".ts", ".go", ".rb", ".php")),
    ("high", "Command execution from a string", re.compile(r"child_process\.(exec|execSync)\s*\("),
     "exec runs through a shell. Use execFile or spawn with an argument list.",
     (".js", ".ts", ".jsx", ".tsx")),
    ("high", "HTML built from data", re.compile(r"\.innerHTML\s*=|document\.write\s*\(|dangerouslySetInnerHTML"),
     "Text inserted as HTML can carry script. Set textContent, or escape it.",
     (".js", ".ts", ".jsx", ".tsx", ".html")),
    ("warn", "World-writable permissions", re.compile(r"chmod\s*\([^,)]*,\s*0o?7[0-7]7"),
     "Anyone on the machine can modify this file.", (".py",)),
    ("warn", "Predictable temp filename", re.compile(r"tempfile\.mktemp\s*\("),
     "mktemp leaves a gap between the name being chosen and the file being "
     "created. Use NamedTemporaryFile or mkstemp.", (".py",)),
    ("warn", "Weak hash", re.compile(r"(?i)hashlib\.(md5|sha1)\s*\("),
     "MD5 and SHA-1 are broken for anything security-related. Fine for a "
     "checksum, wrong for passwords or signatures.", (".py",)),
    ("warn", "Plain HTTP address", re.compile(r"""(?i)['"]http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)"""),
     "Traffic to this address can be read and modified in transit.",
     (".py", ".js", ".ts", ".json", ".yml", ".yaml", ".env", ".cfg", ".ini")),
    ("warn", "Binding to every interface", re.compile(r"""['"]0\.0\.0\.0['"]|host\s*=\s*['"]0\.0\.0\.0"""),
     "This listens on every network the machine is on, not just localhost.",
     (".py", ".js", ".ts", ".yml", ".yaml")),
    ("warn", "Debug mode enabled", re.compile(r"(?i)debug\s*=\s*True|FLASK_DEBUG\s*=\s*1"),
     "Debug mode exposes tracebacks and, in Flask, an interactive console.",
     (".py", ".env", ".cfg", ".ini")),
)


# --- what would this do ---------------------------------------------------

CAPABILITY_RULES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("Network access",
     re.compile(r"(?i)\b(requests\.(get|post|put|delete)|urllib|httpx|aiohttp|socket\.|"
                r"fetch\s*\(|axios|XMLHttpRequest|curl\s|wget\s|Invoke-WebRequest)"),
     "sends or receives data over the internet"),
    ("Writes files",
     re.compile(r"""(?i)(open\s*\([^)]*['"][wax]|write_text|write_bytes|\.write\s*\(|"""
                r"""shutil\.(copy|move)|fs\.writeFile|Out-File|Set-Content)"""),
     "creates or modifies files on disk"),
    ("Deletes files",
     re.compile(r"(?i)(os\.(remove|unlink)|shutil\.rmtree|\.unlink\s*\(|rmdir|"
                r"Remove-Item|fs\.unlink|rm\s+-rf)"),
     "removes files or folders"),
    ("Runs other programs",
     re.compile(r"(?i)(subprocess\.|os\.system|os\.popen|child_process|Start-Process|"
                r"ShellExecute|CreateProcess)"),
     "launches separate processes"),
    ("Reads environment or credentials",
     re.compile(r"(?i)(os\.environ|getenv|process\.env|\.ssh[/\\]|id_rsa|"
                r"Login\s*Data|Cookies|credentials|\.aws[/\\]|keyring)"),
     "looks at environment variables, keys or stored logins"),
    ("Installs itself to start automatically",
     re.compile(r"(?i)(CurrentVersion\\\\Run|winreg|schtasks|crontab|LaunchAgents|"
                r"systemctl\s+enable|Startup[/\\])"),
     "arranges to run again after a reboot"),
    ("Obfuscated or encoded content",
     re.compile(r"(?i)(base64\.b64decode|codecs\.decode|fromCharCode|atob\s*\(|"
                r"exec\s*\(\s*compile|marshal\.loads|zlib\.decompress)"),
     "decodes or unpacks something before running it — the real behaviour is hidden"),
    ("Keyboard or screen capture",
     re.compile(r"(?i)(pynput|keyboard\.|GetAsyncKeyState|ImageGrab|screenshot|"
                r"mss\(\)|SetWindowsHookEx)"),
     "can record what you type or what is on screen"),
    ("Encrypts files",
     re.compile(r"(?i)(Fernet|AES\.new|cryptography\.|CryptEncrypt|\.encrypt\s*\()"),
     "encrypts data — legitimate in a backup tool, the core of ransomware"),
)


# --- engine ---------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_comment(line: str, suffix: str) -> bool:
    stripped = line.strip()
    if suffix == ".py":
        return stripped.startswith("#")
    return stripped.startswith("//") or stripped.startswith("*")


def _code_only(text: str) -> list[str] | None:
    """Python source with every string and comment blanked out.

    Code rules must not fire on prose. Without this, a file that *documents*
    a vulnerability is reported as having one — this scanner flagged its own
    rule table, and tools.py was flagged for the docstring explaining how the
    injection bug there was fixed.

    Secrets are matched against the original line instead, because a
    hardcoded key *is* a string literal. Returns None if the file does not
    parse, in which case the caller falls back to the raw text.
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None

    lines = text.splitlines()
    blanked = list(lines)
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            index = row - 1
            if not 0 <= index < len(blanked):
                continue
            line = blanked[index]
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else len(line)
            blanked[index] = line[:begin] + " " * (finish - begin) + line[finish:]
    return blanked


def scan_text(text: str, name: str = "", suffix: str = "") -> list[Finding]:
    """Every finding in one file's contents."""
    findings: list[Finding] = []
    lines = text.splitlines()
    suffix = (suffix or Path(name).suffix).lower()

    # Secrets are looked for in the real text; code rules in a copy with the
    # strings and comments removed, so documentation is not a vulnerability.
    code_lines = _code_only(text) if suffix == ".py" else None

    for number, line in enumerate(lines, 1):
        if len(line) > 2000:          # minified bundle; rules would only misfire
            continue

        for rule_name, pattern, owner in SECRET_RULES:
            match = pattern.search(line)
            if match:
                findings.append(Finding(
                    "high", rule_name,
                    f"A {owner} credential appears in this file. Rotate it, then "
                    "move it to .env and make sure .env is git-ignored.",
                    name, number, _mask(match.group(0)),
                ))

        generic = GENERIC_SECRET.search(line)
        if generic and not PLACEHOLDER.match(generic.group(1)):
            # An assignment from another variable is not a hardcoded secret.
            if not re.search(r"[:=]\s*['\"]?\s*(os\.|process\.|getenv|config)", line):
                findings.append(Finding(
                    "warn", "Possible hardcoded credential",
                    "This looks like a secret written into the source. If it is "
                    "one, move it to .env.",
                    name, number, _mask(generic.group(1)),
                ))

        if _is_comment(line, suffix):
            continue

        subject = line
        if code_lines is not None:
            subject = code_lines[number - 1] if number <= len(code_lines) else ""
            if not subject.strip():
                continue

        for level, rule_name, pattern, why, suffixes in CODE_RULES:
            if suffixes and suffix not in suffixes:
                continue
            if pattern.search(subject):
                findings.append(Finding(
                    level, rule_name, why, name, number, line.strip()[:120],
                ))
    return findings


def scan_file(path: Path, root: Path | None = None) -> list[Finding]:
    text = _read(path)
    if not text:
        return []
    name = str(path.relative_to(root)) if root and root in path.parents else path.name
    return scan_text(text, name, path.suffix.lower())


def scan_project(root: Path, max_files: int = 400) -> tuple[list[Finding], int]:
    """Scan a folder. Returns (findings, files actually read)."""
    findings: list[Finding] = []
    seen = 0
    for path in sorted(root.rglob("*")):
        if seen >= max_files:
            break
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        seen += 1
        findings.extend(scan_file(path, root))
    return findings, seen


def capabilities(text: str) -> list[tuple[str, str, list[str]]]:
    """What this code can do. Returns (capability, meaning, example lines)."""
    out: list[tuple[str, str, list[str]]] = []
    lines = text.splitlines()
    for title, pattern, meaning in CAPABILITY_RULES:
        hits = [
            f"line {n}: {line.strip()[:90]}"
            for n, line in enumerate(lines, 1)
            if pattern.search(line)
        ]
        if hits:
            out.append((title, meaning, hits[:3]))
    return out


def risk_level(findings: list[Finding], caps: list) -> str:
    """One word for the top of the report."""
    if any(f.level == "high" for f in findings):
        return "HIGH"
    names = {c[0] for c in caps}
    if "Obfuscated or encoded content" in names and len(names) > 2:
        return "HIGH"
    if {"Installs itself to start automatically", "Keyboard or screen capture"} & names:
        return "HIGH"
    if any(f.level == "warn" for f in findings) or len(names) >= 3:
        return "MEDIUM"
    return "LOW"


def format_report(findings: list[Finding], limit: int = 25) -> str:
    """Findings, worst first, capped so one noisy file cannot bury the rest."""
    if not findings:
        return "  Nothing found."
    order = {"high": 0, "warn": 1, "info": 2}
    ranked = sorted(findings, key=lambda f: (order.get(f.level, 3), f.file, f.line))
    shown = ranked[:limit]
    text = "\n\n".join(f.format() for f in shown)
    if len(ranked) > limit:
        text += f"\n\n  ... and {len(ranked) - limit} more."
    return text
