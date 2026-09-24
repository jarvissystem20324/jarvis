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
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from jarvis import security
from jarvis.addons import Addon, Command


def _exe(name: str) -> str:
    """The real path of a tool, e.g. npm -> ...\\npm.cmd on Windows.

    npm, yarn, pnpm, mvn and gradle are .cmd scripts on Windows, and
    starting "npm" without a shell fails with "not found" even when it is
    installed — so /test and /fix never once ran a JavaScript project's
    tests on Windows. Resolving the full path first fixes that.
    """
    return shutil.which(name) or name

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
# A test run that has not finished in five minutes is stuck, not slow.
TEST_TIMEOUT = 300
MAX_TEST_OUTPUT = 12_000
MAX_DIFF_CHARS = 20_000
# Keep console windows from flashing up behind the GUI on Windows.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CodeMode(Addon):
    name = "code-mode"
    version = "1.0"
    description = "Coding agent: reads your project and writes the edits it proposes."

    def __init__(self):
        self.root: Path | None = None
        self.opened: dict[str, str] = {}      # relative path -> contents sent
        # Every file the last /apply wrote, with the backup it made (None
        # for a file that did not exist before). /undo walks this.
        self.backups: list[tuple[Path, Path | None]] = []

    def commands(self):
        return [
            Command("project", self.open_project, "Open a project folder", "/project <folder>"),
            Command("files", self.list_files, "List files in the project", "/files [filter]"),
            Command("show", self.show_file, "Read a file into the conversation", "/show <path>"),
            Command("apply", self.apply, "Write the files I proposed", "/apply [path]"),
            Command("undo", self.undo, "Restore what /apply overwrote", "/undo"),
            Command("tree", self.tree, "Show the project layout", "/tree"),
            Command("test", self.run_tests, "Run the tests and diagnose failures", "/test"),
            Command("diff", self.diff, "Review uncommitted changes", "/diff [raw]"),
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
        if not security.permissions.ask(
            security.READ_FILE, rel, context="/show"
        ):
            return f"Denied. {rel} was not read."
        security.audit.record("show", rel, f"{len(text)} chars")
        self.opened[rel] = text[:MAX_FILE_CHARS]
        return (
            f"Read {rel} — {len(text.splitlines())} lines, {len(text):,} chars. "
            "It's in context now; ask me about it or tell me what to change."
        )

    def enrich_prompt(self, ctx, text: str) -> str | None:
        brain = getattr(ctx.jarvis, "brain", None)
        if not getattr(brain, "code_mode", False) or self.root is None:
            return None

        parts: list[str] = []
        # The layout goes first and always. Without it JARVIS invents plausible
        # filenames when asked where something lives, because it genuinely has
        # no idea what else is in the project.
        layout = self._tree_text(limit=40)
        if layout:
            parts.append(f"Project layout ({self.root}):\n{layout}")
        if self.opened:
            blocks = [
                f"--- {rel} ---\n{body}" for rel, body in list(self.opened.items())[-4:]
            ]
            parts.append(
                "Files open (use these exact contents):\n\n" + "\n\n".join(blocks)
            )
        return "\n\n".join(parts) if parts else None

    # --- writing ----------------------------------------------------------

    @staticmethod
    def _blocks(content: str) -> list[tuple[str, str]]:
        """Every ```<path> ... ``` block in a reply, in order.

        A fence is treated as a file only when its info line looks like a
        path. ```python is a language tag and must not be mistaken for one,
        which is why a bare word without a dot or slash is ignored.
        """
        out: list[tuple[str, str]] = []
        path: str | None = None
        body: list[str] = []
        for line in content.splitlines():
            if line.lstrip().startswith("```"):
                info = line.lstrip()[3:].strip().strip("`")
                if path is None:
                    looks_like_path = "/" in info or "\\" in info or (
                        "." in info and not info.startswith(".")
                    )
                    if looks_like_path:
                        path, body = info, []
                    continue
                out.append((path, "\n".join(body)))
                path = None
                body = []
            elif path is not None:
                body.append(line)
        return out

    def _last_proposals(self, ctx) -> list[tuple[str, str]]:
        """The file blocks from the newest assistant reply that had any.

        One reply often changes several files — a module and its caller, or a
        function and its test. Applying only the first was the difference
        between a coding agent and a code printer.
        """
        brain = getattr(ctx.jarvis, "brain", None)
        for turn in reversed(getattr(brain, "history", []) or []):
            if turn.get("role") != "assistant":
                continue
            blocks = self._blocks(turn.get("content") or "")
            if blocks:
                return blocks
        return []

    def _write_one(self, rel: str, body: str) -> tuple[str, str | None]:
        """Write one file. Returns (report line, error) — error wins."""
        path, err = self._resolve(rel)
        if err:
            return "", err
        if not body.strip():
            return "", f"The proposed contents for {rel} are empty — not writing that."

        before = ""
        backup: Path | None = None
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
            except OSError as exc:
                return "", f"Couldn't back up {rel} first, so I did not write it: {exc}"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            return "", f"Write failed for {rel}: {exc}"

        self.backups.append((path, backup))
        diff = list(difflib.unified_diff(
            before.splitlines(), body.splitlines(), lineterm="", n=0,
        ))
        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        what = "new file" if backup is None else f"backup {backup.name}"
        return f"  {rel}  (+{added} / -{removed})  — {what}", None

    def apply(self, ctx, args: str) -> str:
        if self.root is None:
            return "No project open. Use /project <folder> first."
        proposals = self._last_proposals(ctx)
        if not proposals:
            return (
                "I can't find a file to write in my last reply. I need a fenced "
                "block whose info line is the file path, like ```src/app.py"
            )

        wanted = args.strip().strip('"').strip("'")
        if wanted:
            proposals = [(r, b) for r, b in proposals if r == wanted or r.endswith(wanted)]
            if not proposals:
                offered = ", ".join(r for r, _ in self._last_proposals(ctx))
                return f"'{wanted}' wasn't one of the files I proposed. I offered: {offered}"

        # Last block wins if a file appears twice, and nothing is written until
        # every path has been checked — a half-applied change is worse than none.
        latest: dict[str, str] = {}
        for rel, body in proposals:
            latest[rel] = body
        for rel in latest:
            _, err = self._resolve(rel)
            if err:
                return f"Nothing was written. {err}"

        names = ", ".join(latest)
        if not security.permissions.ask(
            security.WRITE_FILE, f"{len(latest)} file(s) in {self.root.name}: {names}",
            context="/apply",
        ):
            return f"Denied. Nothing was written."
        security.audit.record("apply", names, f"{len(latest)} file(s)")

        self.backups = []
        lines: list[str] = []
        for rel, body in latest.items():
            report, err = self._write_one(rel, body)
            if err:
                undone = self._restore_all()
                return f"{err}\n\n{undone}"
            lines.append(report)

        count = len(lines)
        return (
            f"Wrote {count} file{'s' if count != 1 else ''}:\n"
            + "\n".join(lines)
            + "\n\n/undo restores all of them."
        )

    def _restore_all(self) -> str:
        """Put every file this /apply touched back the way it was."""
        if not self.backups:
            return "Nothing had been written yet."
        restored: list[str] = []
        failed: list[str] = []
        for path, backup in reversed(self.backups):
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                    restored.append(f"removed {path.name}")
                else:
                    shutil.copy2(backup, path)
                    restored.append(f"restored {path.name}")
            except OSError as exc:
                failed.append(f"{path.name}: {exc}")
        self.backups = []
        text = "Rolled back: " + ", ".join(restored) if restored else ""
        if failed:
            text += "\nCould NOT roll back: " + "; ".join(failed)
        return text

    def undo(self, ctx, args: str) -> str:
        if not self.backups:
            return "Nothing to undo — I haven't written anything this session."
        return self._restore_all()

    # --- running the project ---------------------------------------------

    def _detect_test_command(self) -> tuple[list[str], str] | None:
        """Work out how this project runs its tests. Nothing else is run."""
        if self.root is None:
            return None
        root = self.root

        looks_like_python_tests = (
            (root / "pytest.ini").exists()
            or (root / "tests").is_dir()
            or any(root.glob("test_*.py"))
            or any(root.glob("*_test.py"))
        )
        if looks_like_python_tests:
            python = self._project_python()
            # Prefer pytest, but check it is actually importable rather than
            # assuming. Without this the runner "fails" with an exit code and
            # no output, and the real reason — pytest is not installed — is
            # never said out loud.
            if self._module_available(python, "pytest"):
                return [python, "-m", "pytest", "-q", "--tb=short"], "pytest"
            where = "tests" if (root / "tests").is_dir() else "."
            # -t . matters: without the top-level directory set to the
            # project root, discovery runs but imports fail and unittest
            # reports "NO TESTS RAN" rather than an error.
            return (
                [python, "-m", "unittest", "discover", "-s", where, "-t", ".", "-v"],
                "unittest",
            )

        package = root / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
            except (json.JSONDecodeError, OSError):
                scripts = {}
            if "test" in scripts:
                # The lockfile says which package manager the project uses.
                if (root / "pnpm-lock.yaml").is_file():
                    return [_exe("pnpm"), "test"], "pnpm test"
                if (root / "yarn.lock").is_file():
                    return [_exe("yarn"), "test"], "yarn test"
                return [_exe("npm"), "test", "--silent"], "npm test"

        if (root / "Cargo.toml").is_file():
            return [_exe("cargo"), "test"], "cargo test"
        if (root / "go.mod").is_file():
            return [_exe("go"), "test", "./..."], "go test"
        if any(root.glob("*.sln")) or any(root.glob("*.csproj")) or any(root.glob("*/*.csproj")):
            return [_exe("dotnet"), "test"], "dotnet test"
        if (root / "pom.xml").is_file():
            return [_exe("mvn"), "-q", "test"], "Maven"
        wrapper = root / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
        if wrapper.is_file():
            return [str(wrapper), "test"], "Gradle"
        if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
            return [_exe("gradle"), "test"], "Gradle"
        if (root / "deno.json").is_file() or (root / "deno.jsonc").is_file():
            return [_exe("deno"), "test"], "deno test"
        return None

    @staticmethod
    def _module_available(python: str, module: str) -> bool:
        try:
            proc = subprocess.run(
                [python, "-c", f"import {module}"],
                capture_output=True, timeout=30, creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def _project_python(self) -> str:
        """The project's own interpreter if it has one, else ours."""
        if self.root is not None:
            for candidate in (
                self.root / "venv" / "Scripts" / "python.exe",
                self.root / ".venv" / "Scripts" / "python.exe",
                self.root / "venv" / "bin" / "python",
                self.root / ".venv" / "bin" / "python",
            ):
                if candidate.is_file():
                    return str(candidate)
        return sys.executable

    def run_tests(self, ctx, args: str) -> str:
        """Run the project's tests and, if they fail, work out why.

        Only a recognised test runner is ever executed, and only inside the
        folder you opened — this is not a general 'run anything' command.
        """
        if self.root is None:
            return "No project open. Use /project <folder> first."
        detected = self._detect_test_command()
        if detected is None:
            return (
                "I can't tell how this project runs its tests. I look for "
                "pytest or unittest (a tests/ folder or test_*.py), an npm, "
                "yarn or pnpm 'test' script, Cargo.toml, go.mod, a .NET "
                "solution or project, pom.xml, Gradle, or deno.json."
            )
        command, label = detected
        if not security.permissions.ask(
            security.RUN_TESTS, f"{' '.join(command)}  (in {self.root})",
            context="/test",
        ):
            return "Denied. The tests were not run."
        security.audit.record("test", " ".join(command))

        try:
            proc = subprocess.run(
                command, cwd=str(self.root), capture_output=True, text=True,
                timeout=TEST_TIMEOUT, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW,
            )
        except FileNotFoundError:
            return f"{label} isn't installed, or isn't on PATH."
        except subprocess.TimeoutExpired:
            return f"{label} was still running after {TEST_TIMEOUT}s, so I stopped it."
        except OSError as exc:
            return f"Couldn't run {label}: {exc}"

        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        trimmed = output[-MAX_TEST_OUTPUT:]
        if len(output) > MAX_TEST_OUTPUT:
            trimmed = "...(earlier output trimmed)...\n" + trimmed

        if proc.returncode == 0:
            tail = "\n".join(trimmed.splitlines()[-6:])
            return f"{label}: everything passed.\n\n{tail}"

        verdict = ctx.ask(
            "These tests just failed. Say which test failed and why, then the "
            "smallest change that would fix it. If the output does not say "
            "enough, name the file you need to see. Be brief.\n\n"
            f"Command: {' '.join(command)}\nExit code: {proc.returncode}\n\n"
            f"{trimmed}"
        )
        tail = "\n".join(trimmed.splitlines()[-16:])
        return (
            f"{label} failed (exit {proc.returncode}).\n\n{verdict}\n\n"
            f"--- last lines of output ---\n{tail}"
        )

    def diff(self, ctx, args: str) -> str:
        """Show what has changed in the working tree, and review it."""
        if self.root is None:
            return "No project open. Use /project <folder> first."
        if not (self.root / ".git").exists():
            return f"{self.root.name} isn't a git repository, so there's nothing to diff."

        status = self._git("status", "--short")
        if status is None:
            return "git isn't installed, or isn't on PATH."
        if not status.strip():
            return "The working tree is clean — nothing changed since the last commit."

        patch = self._git("diff") or ""
        staged = self._git("diff", "--cached") or ""
        combined = (patch + "\n" + staged).strip()
        if not combined:
            return (
                "Files are added or removed, but nothing has a text diff yet:\n\n"
                + status
            )

        trimmed = combined[:MAX_DIFF_CHARS]
        note = "\n...(diff trimmed)..." if len(combined) > MAX_DIFF_CHARS else ""

        if args.strip().lower() in {"show", "raw"}:
            return f"Changes in {self.root.name}:\n\n{status}\n{trimmed}{note}"

        review = ctx.ask(
            "Review this diff as a careful colleague. Say what it changes, then "
            "anything that looks wrong: bugs, cases not handled, things the "
            "change breaks elsewhere. If it looks fine, say so plainly and "
            "briefly. Do not restate the diff.\n\n"
            f"{status}\n\n{trimmed}{note}"
        )
        files = len([line for line in status.splitlines() if line.strip()])
        return f"{files} file{'s' if files != 1 else ''} changed.\n\n{review}"

    def _git(self, *args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout or ""

    def tree(self, ctx, args: str) -> str:
        """The project's shape, as a tree."""
        if self.root is None:
            return "No project open. Use /project <folder> first."
        text = self._tree_text()
        if not text:
            return "No readable files in that folder."
        return f"{self.root}\n{text}"

    def _tree_text(self, limit: int = 120) -> str:
        """Directories and their file counts, deepest paths folded away.

        A flat list of 400 paths tells the model less than the shape does, and
        costs far more context.
        """
        files = self._walk()
        if not files:
            return ""
        groups: dict[str, list[str]] = {}
        for f in files:
            rel = f.relative_to(self.root)
            folder = str(rel.parent) if str(rel.parent) != "." else ""
            groups.setdefault(folder, []).append(rel.name)

        lines: list[str] = []
        for folder in sorted(groups):
            names = sorted(groups[folder])
            head = f"{folder}/" if folder else "(root)"
            shown = ", ".join(names[:8])
            more = f", +{len(names) - 8} more" if len(names) > 8 else ""
            lines.append(f"  {head}  [{len(names)}]  {shown}{more}")
            if len(lines) >= limit:
                lines.append(f"  ... {len(groups) - limit} more folders")
                break
        return "\n".join(lines)


ADDON = CodeMode()
