"""Code mode — turns JARVIS into a coding agent for one project folder.

`/code` (built in) swaps the butler persona for an engineer's. This addon
supplies the other half: `/project <folder>` points JARVIS at real code, it
reads the files it needs to answer, and proposes edits as complete file
contents that `/apply` writes to disk.

Two deliberate limits, both because an agent that edits your work is a
different risk from one that talks about it:

  * It only ever touches files inside the folder you opened. Paths that
    escape it, and files that are not text, are refused.
  * Writes are never silent. `/apply` shows what changed and keeps a backup
    of the previous contents, which `/undo` restores.
"""

from __future__ import annotations

import difflib
import shutil
from datetime import datetime
from pathlib import Path

from jarvis.addons import Addon, Command

CODE_PERSONA = """You are JARVIS in code mode: a senior software engineer
pair-programming with the user.

How to behave:
- Answer with working code, not sketches. Include imports and error handling.
- When you change an existing file, return the COMPLETE new contents of that
  file inside one fenced block whose info line is the file's path, exactly:
  ```path/to/file.py
  ...complete file...
  ```
  The user applies it with /apply. A fragment or an ellipsis makes that fail,
  so never abbreviate the body of a file you are rewriting.
- Before changing code you have not seen, ask for it or say which file you
  need. Do not guess at contents.
- Say what you are uncertain about rather than sounding confident. If a change
  could break something else, name what.
- Skip pleasantries. No "certainly, sir" in this mode."""

# Read as text; anything else is refused rather than mangled.
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sh", ".ps1", ".bat",
    ".html", ".css", ".scss", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".sql", ".xml", ".env", ".spec", "",
}
MAX_FILE_CHARS = 120_000
MAX_LISTED = 400


class CodeMode(Addon):
    name = "code-mode"
    version = "1.0"
    description = "Coding agent: reads your project and writes the edits it proposes."

    def __init__(self):
        self.root: Path | None = None
        self.opened: dict[str, str] = {}      # relative path -> contents sent
        self.last_backup: tuple[Path, Path] | None = None

    def commands(self):
        return [
            Command("project", self.open_project, "Open a project folder", "/project <folder>"),
            Command("files", self.list_files, "List files in the project", "/files [filter]"),
            Command("show", self.show_file, "Read a file into the conversation", "/show <path>"),
            Command("apply", self.apply, "Write the last proposed file", "/apply"),
            Command("undo", self.undo, "Restore what /apply overwrote", "/undo"),
        ]

    # --- mode -------------------------------------------------------------

    def toggle(self, ctx, args: str) -> str:
        brain = getattr(ctx.jarvis, "brain", None)
        if brain is None:
            return "Code mode needs a running assistant."

        brain.code_mode = not getattr(brain, "code_mode", False)
        brain.persona_override = CODE_PERSONA if brain.code_mode else None

        window = getattr(ctx.jarvis, "window", None)
        if window is not None:
            try:
                window.after(0, window.refresh_code_mode)
            except Exception:
                pass

        if not brain.code_mode:
            return "Code mode off. Back to normal."
        where = f"\nProject: {self.root}" if self.root else (
            "\nNo project open — use /project <folder> so I can read your code."
        )
        return (
            "Code mode on. I'll answer as an engineer and return complete files "
            "you can /apply." + where
        )

    # --- project ----------------------------------------------------------

    def open_project(self, ctx, args: str) -> str:
        raw = args.strip().strip('"').strip("'")
        if not raw:
            return (
                "Usage: /project <folder>\n"
                "Example: /project C:\\Users\\me\\myapp\n"
                + (f"Currently open: {self.root}" if self.root else "Nothing open.")
            )
        path = Path(raw).expanduser()
        if not path.exists():
            return f"No such folder:\n  {path}"
        if not path.is_dir():
            return f"That's a file, not a folder. Try /show {path}"

        self.root = path.resolve()
        self.opened.clear()
        files = self._walk()
        kinds: dict[str, int] = {}
        for f in files:
            kinds[f.suffix or "(none)"] = kinds.get(f.suffix or "(none)", 0) + 1
        top = sorted(kinds.items(), key=lambda kv: -kv[1])[:6]
        summary = ", ".join(f"{n}× {ext}" for ext, n in top) or "no text files"
        return (
            f"Project open: {self.root}\n"
            f"{len(files)} readable files — {summary}\n"
            "Use /files to browse, /show <path> to read one into the conversation."
        )

    def _walk(self) -> list[Path]:
        if self.root is None:
            return []
        skip = {".git", "venv", ".venv", "node_modules", "__pycache__", "dist",
                "build", ".idea", ".vscode", "release"}
        out: list[Path] = []
        for p in self.root.rglob("*"):
            if len(out) >= MAX_LISTED:
                break
            if not p.is_file():
                continue
            if any(part in skip for part in p.parts):
                continue
            if p.suffix.lower() in TEXT_SUFFIXES:
                out.append(p)
        return out

    def list_files(self, ctx, args: str) -> str:
        if self.root is None:
            return "No project open. Use /project <folder> first."
        needle = args.strip().lower()
        files = self._walk()
        rel = [str(f.relative_to(self.root)) for f in files]
        if needle:
            rel = [r for r in rel if needle in r.lower()]
        if not rel:
            return f"Nothing matches '{needle}'." if needle else "No readable files."
        shown = sorted(rel)[:60]
        more = f"\n  ... and {len(rel) - len(shown)} more" if len(rel) > len(shown) else ""
        return f"{len(rel)} files:\n" + "\n".join(f"  {r}" for r in shown) + more

    # --- reading ----------------------------------------------------------

    def _resolve(self, raw: str) -> tuple[Path | None, str]:
        """Resolve a path inside the project, or explain why not."""
        if self.root is None:
            return None, "No project open. Use /project <folder> first."
        candidate = (self.root / raw.strip().strip('"').strip("'")).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            return None, f"Bad path: {exc}"
        # The whole point of scoping to a project: '../' must not escape it.
        if self.root not in resolved.parents and resolved != self.root:
            return None, (
                f"'{raw}' is outside the project folder. Code mode only touches "
                f"files under {self.root}"
            )
        return resolved, ""

    def show_file(self, ctx, args: str) -> str:
        path, err = self._resolve(args)
        if err:
            return err
        if not path.is_file():
            return f"Not a file: {path}"
        if path.suffix.lower() not in TEXT_SUFFIXES:
            return f"'{path.suffix}' isn't a text format I can read safely."
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Couldn't read it: {exc}"

        rel = str(path.relative_to(self.root))
        self.opened[rel] = text[:MAX_FILE_CHARS]
        return (
            f"Read {rel} — {len(text.splitlines())} lines, {len(text):,} chars. "
            "It's in context now; ask me about it or tell me what to change."
        )

    def enrich_prompt(self, ctx, text: str) -> str | None:
        brain = getattr(ctx.jarvis, "brain", None)
        if not getattr(brain, "code_mode", False) or not self.opened:
            return None
        blocks = [
            f"--- {rel} ---\n{body}" for rel, body in list(self.opened.items())[-4:]
        ]
        return (
            f"Files open from {self.root} (use these exact contents):\n\n"
            + "\n\n".join(blocks)
        )

    # --- writing ----------------------------------------------------------

    def _last_proposal(self, ctx) -> tuple[str, str] | None:
        """Pull the newest ```<path> block out of the last assistant reply."""
        brain = getattr(ctx.jarvis, "brain", None)
        for turn in reversed(getattr(brain, "history", []) or []):
            if turn.get("role") != "assistant":
                continue
            lines = (turn.get("content") or "").splitlines()
            path = None
            body: list[str] = []
            found: tuple[str, str] | None = None
            for line in lines:
                if line.startswith("```"):
                    info = line[3:].strip()
                    if path is None and ("/" in info or "\\" in info or "." in info):
                        path, body = info, []
                    elif path is not None:
                        found = (path, "\n".join(body))
                        path = None
                elif path is not None:
                    body.append(line)
            if found:
                return found
        return None

    def apply(self, ctx, args: str) -> str:
        if self.root is None:
            return "No project open. Use /project <folder> first."
        proposal = self._last_proposal(ctx)
        if proposal is None:
            return (
                "I can't find a file to write in my last reply. I need a fenced "
                "block whose first line is the file path, like ```src/app.py"
            )
        rel, body = proposal
        path, err = self._resolve(rel)
        if err:
            return err
        if not body.strip():
            return f"The proposed contents for {rel} are empty — refusing to write that."

        before = ""
        if path.exists():
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
            backup = path.with_name(
                f"{path.name}.jarvis-{datetime.now():%Y%m%d_%H%M%S}.bak"
            )
            try:
                shutil.copy2(path, backup)
                self.last_backup = (path, backup)
            except OSError as exc:
                return f"Couldn't back up {rel} first, so I did not write: {exc}"
        else:
            self.last_backup = (path, None)  # type: ignore[assignment]

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            return f"Write failed: {exc}"

        diff = list(difflib.unified_diff(
            before.splitlines(), body.splitlines(),
            fromfile=f"{rel} (before)", tofile=f"{rel} (after)", lineterm="", n=1,
        ))
        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        preview = "\n".join(diff[:24])
        tail = f"\n  ... {len(diff) - 24} more diff lines" if len(diff) > 24 else ""
        return (
            f"Wrote {rel}  (+{added} / -{removed} lines)\n"
            f"{'Backup: ' + self.last_backup[1].name if self.last_backup[1] else 'New file.'}"
            f"  —  /undo restores it\n\n{preview}{tail}"
        )

    def undo(self, ctx, args: str) -> str:
        if not self.last_backup:
            return "Nothing to undo — I haven't written anything this session."
        path, backup = self.last_backup
        try:
            if backup is None:
                path.unlink(missing_ok=True)
                self.last_backup = None
                return f"Removed {path.name} — it was newly created."
            shutil.copy2(backup, path)
            self.last_backup = None
            return f"Restored {path.name} from {backup.name}."
        except OSError as exc:
            return f"Undo failed: {exc}"


ADDON = CodeMode()
