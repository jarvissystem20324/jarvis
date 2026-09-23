"""Codebase index — answering "where is X handled?" across a whole project.

Until now JARVIS could only see files you had opened with `/show`, so asking
where something lived got a confident guess at a plausible filename. This
walks the project once, records every definition and where it is, and keeps
the result on disk so the next question is instant.

Deliberately not embeddings. A vector index would need a model, a key, and a
few seconds per file, and it would send your entire codebase to a provider to
build. Symbol names plus the lines around them answer "where is X" perfectly
well, cost nothing, work offline, and leave the code on the machine — only
the handful of matching snippets are ever sent, and only when you ask.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_data_dir

MAX_FILES = 1500
MAX_FILE_BYTES = 400_000
# Enough context to recognise a match without pasting whole files into a prompt.
SNIPPET_LINES = 14

SKIP_DIRS = {
    ".git", "venv", ".venv", "node_modules", "__pycache__", "dist", "build",
    ".idea", ".vscode", "release", "site-packages", ".mypy_cache",
    ".pytest_cache", "target", "vendor", ".next", "coverage",
}
CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sh", ".ps1",
    ".sql", ".html", ".css", ".scss", ".vue", ".md", ".yml", ".yaml", ".toml",
}

# One pattern per language family. Not a parser — a parser for nine languages
# would be a project of its own, and the name and line number is all that is
# needed to point someone at the right place.
SYMBOL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),                  # python
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),                             # python/js/java
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
    re.compile(r"^\s*(?:public|private|protected|static|\s)*[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),             # go
    re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)"),                     # rust
)

# Only for .md: in Python this pattern matches every comment, which filled
# the index with prose like "# Past this the log is rotated...".
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")


@dataclass
class Symbol:
    name: str
    file: str
    line: int


@dataclass
class Index:
    root: str
    built: float = 0.0
    files: dict[str, int] = field(default_factory=dict)      # path -> line count
    symbols: list[Symbol] = field(default_factory=list)

    @property
    def age(self) -> str:
        if not self.built:
            return "never"
        minutes = (time.time() - self.built) / 60
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{int(minutes)} minutes ago"
        if minutes < 1440:
            return f"{int(minutes / 60)} hours ago"
        return f"{int(minutes / 1440)} days ago"


def _store(root: Path) -> Path:
    """One index file per project, keyed by path so two projects don't clash."""
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    folder = get_data_dir() / "index"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def build(root: Path) -> Index:
    """Walk the project and record every definition. Nothing leaves the machine."""
    index = Index(root=str(root), built=time.time())
    for path in sorted(root.rglob("*")):
        if len(index.files) >= MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        relative = str(path.relative_to(root)).replace("\\", "/")
        lines = text.splitlines()
        index.files[relative] = len(lines)
        for number, line in enumerate(lines, 1):
            if len(line) > 400:
                continue
            patterns = (
                (MARKDOWN_HEADING,) if path.suffix.lower() == ".md"
                else SYMBOL_PATTERNS
            )
            for pattern in patterns:
                match = pattern.match(line)
                if match:
                    name = match.group(1).strip()
                    if name and len(name) < 120:
                        index.symbols.append(Symbol(name, relative, number))
                    break
    save(index)
    return index


def save(index: Index) -> None:
    try:
        _store(Path(index.root)).write_text(json.dumps({
            "root": index.root,
            "built": index.built,
            "files": index.files,
            "symbols": [[s.name, s.file, s.line] for s in index.symbols],
        }), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def load(root: Path) -> Index | None:
    path = _store(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return Index(
        root=str(data.get("root") or root),
        built=float(data.get("built") or 0),
        files=dict(data.get("files") or {}),
        symbols=[
            Symbol(str(s[0]), str(s[1]), int(s[2]))
            for s in data.get("symbols") or []
            if isinstance(s, list) and len(s) == 3
        ],
    )


def search(index: Index, query: str, limit: int = 12) -> list[tuple[Symbol, str]]:
    """Symbols matching `query`, best first, each with the code around it."""
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
    if not words:
        return []

    scored: list[tuple[float, Symbol]] = []
    for symbol in index.symbols:
        low = symbol.name.lower()
        score = 0.0
        for word in words:
            if low == word:
                score += 10
            elif low.startswith(word) or low.endswith(word):
                score += 5
            elif word in low:
                score += 3
            if word in symbol.file.lower():
                score += 2
        if not score:
            continue

        # A markdown heading is a whole sentence, so it collides with far more
        # of the question than a function name does and wins on volume alone.
        # "where is the permission prompt shown" returned eleven headings out
        # of PUBLISHING.md and not one line of code. Documentation is worth
        # finding, but it should never outrank the implementation.
        if symbol.file.lower().endswith((".md", ".txt")):
            score *= 0.3
        # Likewise a long name matches by accident more often than a short one.
        if len(symbol.name) > 40:
            score *= 0.5
        scored.append((score, symbol))

    scored.sort(key=lambda pair: -pair[0])
    root = Path(index.root)
    out: list[tuple[Symbol, str]] = []
    seen: set[tuple[str, int]] = set()
    for _score, symbol in scored:
        key = (symbol.file, symbol.line)
        if key in seen:
            continue
        seen.add(key)
        out.append((symbol, _snippet(root / symbol.file, symbol.line)))
        if len(out) >= limit:
            break
    return out


def _snippet(path: Path, line: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(0, line - 2)
    return "\n".join(lines[start:start + SNIPPET_LINES])


def describe(index: Index) -> str:
    kinds: dict[str, int] = {}
    for name in index.files:
        suffix = Path(name).suffix or "(none)"
        kinds[suffix] = kinds.get(suffix, 0) + 1
    top = sorted(kinds.items(), key=lambda kv: -kv[1])[:6]
    total_lines = sum(index.files.values())
    return (
        f"{len(index.files)} files, {total_lines:,} lines, "
        f"{len(index.symbols)} definitions — "
        + ", ".join(f"{n}x {ext}" for ext, n in top)
        + f"\nBuilt {index.age}."
    )
