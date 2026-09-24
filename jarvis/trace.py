"""Reading a pasted traceback: which files, which lines, and what is there.

The model is good at explaining an error when it can see the code and bad
when it cannot — handed a bare traceback it guesses at what line 42 of a file
it has never seen probably contains. So this does the part that needs no
model at all: pull every frame out of the traceback, keep the ones that are
in your project rather than in the standard library, and read the real lines
around each. Only then is anything sent.

Python and JavaScript/TypeScript stacks are recognised. Anything else still
gets explained, just without the code attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# File "C:\proj\src\calc.py", line 12, in add
PYTHON_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?')
# at add (/proj/src/calc.js:12:5)   or   at /proj/src/calc.js:12:5
JS_FRAME = re.compile(r"at (?:(?P<func>[^\s(]+) \()?(?P<file>[^\s()]+?):(?P<line>\d+):\d+\)?")
# The last line of a Python traceback: "ZeroDivisionError: division by zero"
PYTHON_ERROR = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt|Exit))(?::\s*(?P<msg>.*))?$")

CONTEXT_LINES = 8
MAX_FRAMES = 4

# Frames from here are the language's own code, not the user's.
LIBRARY_MARKERS = (
    "site-packages", "dist-packages", "lib/python", "lib\\python",
    "node_modules", "<frozen", "<string>", "internal/",
)


@dataclass
class Frame:
    file: str
    line: int
    func: str = ""
    resolved: Path | None = None
    code: str = ""

    @property
    def in_project(self) -> bool:
        return self.resolved is not None

    def label(self) -> str:
        where = str(self.resolved) if self.resolved else self.file
        return f"{where}:{self.line}" + (f" in {self.func}" if self.func else "")


def frames(text: str) -> list[Frame]:
    """Every frame in the traceback, in the order they appear."""
    found: list[Frame] = []
    for pattern in (PYTHON_FRAME, JS_FRAME):
        for match in pattern.finditer(text):
            found.append(Frame(
                file=match.group("file"),
                line=int(match.group("line")),
                func=(match.group("func") or "").strip(),
            ))
        if found:
            break
    return found


def error_line(text: str) -> str:
    """The error itself — the line that says what actually went wrong."""
    for line in reversed([l.strip() for l in text.strip().splitlines() if l.strip()]):
        if PYTHON_ERROR.match(line):
            return line
        if re.match(r"^(Uncaught )?[A-Z]\w*Error\b", line):
            return line
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def resolve(frame: Frame, root: Path | None) -> Path | None:
    """Find the frame's file on disk, preferring the open project.

    A traceback from another machine carries that machine's paths, so an
    absolute path that does not exist here is matched by its tail against
    the project instead: /home/ci/app/src/calc.py finds src/calc.py.
    """
    raw = frame.file.replace("\\", "/")
    if any(marker in raw for marker in LIBRARY_MARKERS):
        return None

    candidate = Path(frame.file)
    if candidate.is_file():
        if root is None:
            return candidate
        try:
            candidate.resolve().relative_to(root.resolve())
            return candidate
        except ValueError:
            pass

    if root is None:
        return None
    parts = [p for p in raw.split("/") if p and p not in {".", ".."}]
    for start in range(len(parts)):
        attempt = root.joinpath(*parts[start:])
        if attempt.is_file():
            return attempt
    return None


def read_around(path: Path, line: int, span: int = CONTEXT_LINES) -> str:
    """The lines around `line`, numbered, with the failing one marked."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(1, line - span)
    end = min(len(lines), line + span)
    return "\n".join(
        f"{'>>' if number == line else '  '} {number:4} | {lines[number - 1]}"
        for number in range(start, end + 1)
    )


def analyse(text: str, root: Path | None) -> tuple[str, list[Frame]]:
    """(error line, the project frames with their code read in)."""
    everything = frames(text)
    for frame in everything:
        frame.resolved = resolve(frame, root)
        if frame.resolved is not None:
            frame.code = read_around(frame.resolved, frame.line)
    # The innermost project frames are where the fix usually belongs.
    ours = [f for f in everything if f.in_project][-MAX_FRAMES:]
    return error_line(text), ours
