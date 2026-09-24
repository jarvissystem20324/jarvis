"""The 7.0 commands: exact answers, tools, the conversation, and code review.

A second mixin beside everyday.py, for the same reason: assistant.py is
long enough. Methods return text, a JarvisResponse, or None where a
plain-language request turned out not to be a command.
"""

from __future__ import annotations

import base64
import io
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import (
    calc, clock, history, modes, notes, ocr, pc, providers, reminders, security, shield,
    tidy, weather, websearch,
)
from .config import get_setting

CLIP_ACTIONS = {
    "explain": "Explain this clearly and briefly. If it is code, say what it does and anything risky.",
    "summarize": "Summarise this in a few bullet points, most important first.",
    "summarise": "Summarise this in a few bullet points, most important first.",
    "fix": "Correct the spelling, grammar and punctuation. Keep the wording and tone. Return only the corrected text.",
    "reply": "Write a short, friendly reply to this message, in the same language.",
    "simplify": "Rewrite this in plain, simple words, keeping the meaning.",
    "bullets": "Turn this into a clear bulleted list.",
    "tweet": "Turn this into a single post under 280 characters.",
    "formal": "Rewrite this to sound professional and polite.",
}
TODO = re.compile(r"(?:#|//|/\*|--|<!--|;)\s*(TODO|FIXME|HACK|XXX|BUG)\b[:\s-]*(.*)")
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs", ".c", ".cpp", ".h",
                 ".hpp", ".rb", ".php", ".swift", ".kt", ".sql", ".sh", ".ps1", ".html", ".css", ".vue", ".lua"}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode",
             "target", "bin", "obj", ".next", ".tox", "site-packages"}


class Extras:
    """Mixed into Jarvis alongside Everyday."""

    def extras_command(self, name: str, args: str, routed: bool = False):
        handlers = {
            "calc": lambda: self.calculate(args, routed),
            "convert": lambda: self.calculate(args, routed),
            "clock": lambda: self.world_clock(args, routed),
            "instructions": lambda: self.set_instructions(args),
            "pin": lambda: self.pin(args),
            "pins": lambda: self.list_pins(args),
            "clip": lambda: self.clipboard_action(args),
            "ocr": lambda: self.read_text(args),
            "briefing": lambda: self.briefing(args),
            "tidy": lambda: self.tidy(args),
            "qr": lambda: self.qr(args),
            "stopwatch": lambda: self.stopwatch(args),
            "review": lambda: self.review(args),
            "changes": lambda: self.agent_changes(args),
            "revert": lambda: self.agent_revert(args),
            "explain": lambda: self.explain(args),
            "todo": lambda: self.todos(args),
            "pr": lambda: self.pull_request(args),
            "look": lambda: self.look(args, routed),
            "offline": lambda: self.offline(args),
            "suggest": lambda: self.suggest_setting(args),
        }
        handler = handlers.get(name)
        return handler() if handler else None

    # --- exact answers ----------------------------------------------------

    def calculate(self, args: str, routed: bool = False):
        text = args.strip()
        if not text:
            return ("Usage: /calc <sum>   e.g. /calc (12.5*4)^2/3, 15% of 240, 5 miles to km,\n"
                    "       100 usd to try, days until christmas")
        try:
            return calc.solve(text)
        except calc.CalcError as exc:
            return None if routed else str(exc)

    def world_clock(self, args: str, routed: bool = False):
        try:
            return clock.answer(args)
        except clock.ClockError as exc:
            return None if routed else str(exc)

    # --- the conversation --------------------------------------------------

    def set_instructions(self, args: str) -> str:
        text = args.strip()
        if not text or text.lower() == "show":
            current = self.brain.instructions
            return (f"Instructions for this conversation:\n  {current}\n\n/instructions clear removes them."
                    if current else
                    "No standing instructions for this conversation.\n"
                    "  /instructions you are my Turkish tutor — correct every mistake I make\n"
                    "They apply to this conversation only, and are saved with it.")
        if text.lower() in {"clear", "off", "none", "remove"}:
            self.brain.instructions = ""
            self.save_history()
            return "Instructions cleared for this conversation."
        self.brain.instructions = text[:2000]
        self.save_history()
        return f"From now on in '{history.current_name()}': {text[:200]}"

    def pin(self, args: str) -> str:
        text = args.strip()
        if not text:
            text = next((m["content"] for m in reversed(self.brain.history)
                         if m.get("role") == "assistant"), "")
        if not text:
            return "Nothing to pin yet. /pin pins JARVIS's last answer, or /pin <text>."
        return notes.add_pin(text, history.current_name())

    def list_pins(self, args: str) -> str:
        verb, _, rest = args.strip().partition(" ")
        if verb.lower() in {"delete", "remove", "unpin"}:
            return notes.delete_pin(rest)
        return notes.list_pins(args.strip())

    def forget_last_exchange(self) -> str:
        """For edit-and-re-ask: the question being replaced, or ''."""
        question = ""
        while self.brain.history and self.brain.history[-1].get("role") == "assistant":
            self.brain.history.pop()
        if self.brain.history and self.brain.history[-1].get("role") == "user":
            question = self.brain.history.pop().get("content", "")
        return question

    def suggest_enabled(self) -> bool:
        return get_setting("JARVIS_SUGGEST", "on").strip().lower() not in {"off", "0", "false", "no"}

    def suggest_setting(self, args: str) -> str:
        wanted = args.strip().lower()
        if wanted in {"on", "off"}:
            self._write_setting("JARVIS_SUGGEST", wanted)
            return f"Follow-up suggestions {wanted}."
        return (f"Follow-up suggestions are {'on' if self.suggest_enabled() else 'off'}: three "
                "clickable next questions under each answer, from the fast Low model. /suggest on|off")

    def _quick_ask(self, prompt: str) -> str:
        """A small side question on the fast model, without moving the status line."""
        brain = self.brain
        active, last = brain._active, brain._last_model
        try:
            return brain.ask_once(prompt, targets=modes.targets_for(modes.LOW), target_timeout=20)
        finally:
            brain._active, brain._last_model = active, last

    def follow_ups(self, question: str, reply: str) -> list[str]:
        """Three short next questions, or [] when they would be noise."""
        if (not self.suggest_enabled() or security.privacy.on or self.brain.code_mode
                or question.startswith("/") or len(reply) < 120 or providers.offline_mode()):
            return []
        answer = self._quick_ask(
            "Suggest exactly three short follow-up questions the user is likely to ask next "
            "about this exchange. Each under 60 characters, in the user's language, one per "
            "line, no numbering, no quotes, nothing else.\n\n"
            f"User: {question[:1500]}\n\nAssistant: {reply[:3000]}"
        )
        lines = [re.sub(r"^[\s\-*\d.)]+", "", line).strip().strip('"') for line in answer.splitlines()]
        good = [line for line in lines if 6 <= len(line) <= 90 and not line.lower().startswith(("i couldn", "no ai"))]
        return good[:3]

    def title_conversation(self) -> str:
        """Name an unnamed conversation (chat-3) after its first exchange."""
        name = history.current_name()
        if not history.needs_title(name) or len(self.brain.history) < 2 or security.privacy.on:
            return ""
        first_q = self.brain.history[0].get("content", "")[:600]
        first_a = self.brain.history[1].get("content", "")[:600]
        title = self._quick_ask(
            "Give this conversation a title of two to five words, in the user's language. "
            "Reply with the title only — no quotes, no punctuation at the end.\n\n"
            f"User: {first_q}\nAssistant: {first_a}"
        ).strip().strip('"').strip("'").rstrip(".")
        title = re.sub(r"[^\w\s\-']", "", title, flags=re.UNICODE).strip()[:40]
        if not title or len(title.split()) > 8 or title.lower().startswith(("i couldn", "no ai")):
            return ""
        self.save_history()
        if history.rename_chat(name, title):
            return ""
        return title

    def export_as(self, kind: str) -> str:
        from . import writer

        if not self.brain.history:
            return "Nothing to export yet."
        title = history.current_name()
        parts = [f"# {title}", f"*Exported {datetime.now():%d %B %Y, %H:%M}*", ""]
        for message in self.brain.history:
            who = "You" if message.get("role") == "user" else "JARVIS"
            parts += [f"## {who}", "", (message.get("content") or "").strip(), ""]
        markdown = "\n".join(parts)
        folder = writer.documents_dir()
        safe = re.sub(r"[^\w-]+", "-", title)[:40]
        stem = f"chat_{safe}_{datetime.now():%Y%m%d_%H%M%S}"
        if kind == "pdf":
            path = writer.to_pdf(markdown, folder / f"{stem}.pdf")
        else:
            path = folder / f"{stem}.html"
            path.write_text(to_html(markdown, title), encoding="utf-8")
        security.audit.record("export", path.suffix)
        return f"Conversation saved as {kind.upper()}:\n  {path}"

    # --- clipboard and screen -------------------------------------------------

    def clipboard_action(self, args: str):
        from .assistant import JarvisResponse

        head, _, payload = args.partition("\n")
        words = head.strip().split(maxsplit=1)
        action = (words[0].lower() if words else "explain")
        extra = words[1] if len(words) > 1 else ""
        if not payload.strip():
            actions = ", ".join(sorted(CLIP_ACTIONS)) + ", translate <language>"
            return f"The clipboard is empty, or not text.\nUsage: /clip <action> — {actions}"
        if action == "translate":
            instruction = f"Translate this into {extra or 'English'}. Return only the translation."
        elif action in CLIP_ACTIONS:
            instruction = CLIP_ACTIONS[action] + (f" ({extra})" if extra else "")
        else:
            instruction = f"{head.strip()}."
        cleaned = shield.clean(payload[:20000], "the clipboard")
        reply = self.brain.chat(
            f"[clipboard: {action}] {instruction}",
            extra_context=f"{shield.RULE}\nThe text the user copied:\n{cleaned.wrapped()}",
        )
        warning = cleaned.warning()
        self._maybe_speak(reply)
        return JarvisResponse(text=reply + (f"\n\n{warning}" if warning else ""))

    def read_text(self, args: str) -> str:
        target = args.strip().strip('"')
        try:
            if not target or target.lower() == "screen":
                text = ocr.read_region(None)
                source = "the screen"
            else:
                path = Path(target).expanduser()
                if not path.is_file():
                    return f"No such image:\n  {path}"
                text = ocr.read_image(path)
                source = path.name
        except ocr.OcrError as exc:
            return str(exc)
        security.audit.record("ocr", source, f"{len(text)} chars")
        if not text:
            return f"No text found in {source}."
        self._last_ocr = text
        return f"Text from {source} (read on this PC, nothing uploaded):\n\n{text}"

    # --- briefing ------------------------------------------------------------

    def briefing(self, args: str) -> str:
        text = args.strip().lower()
        m = re.fullmatch(r"(?:at|every day at|daily at)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text)
        if text and m:
            parsed = reminders.parse_clock(m.group(1))
            if parsed is None:
                return "Usage: /briefing at 8:00"
            reminders.board.cancel_kind("briefing")
            item = reminders.board.add("briefing", "Morning briefing", parsed[0].timestamp())
            return f"I'll give you the briefing every day at {parsed[0]:%H:%M}, starting {item.when()}."
        if text in {"off", "stop", "cancel"}:
            removed = reminders.board.cancel_kind("briefing")
            return "Daily briefing off." if removed else "There was no daily briefing set."

        now = datetime.now()
        part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
        lines = [f"Good {part}. It's {now:%A %d %B}, {now:%H:%M}."]
        if weather.home_city():
            try:
                forecast = weather.report("today").splitlines()
                lines += ["", "Weather", *[f"  {l.strip()}" for l in forecast[:2]]]
            except weather.WeatherError:
                pass
        else:
            lines += ["", "Weather: set a home city with /weather city <name>."]
        end = now.replace(hour=23, minute=59, second=59)
        today = [r for r in reminders.board.items if r.due <= end.timestamp() and r.kind != "briefing"]
        lines += ["", "Today"] + ([r.line() for r in today] if today else ["  Nothing scheduled."])
        saved = notes.load_notes()
        if saved:
            lines += ["", f"Notes: {len(saved)}. Latest: {saved[-1]['text'][:80]}"]
        if (self.autoweb_enabled() and not security.privacy.on and not providers.offline_mode()):
            news = headlines()
            if news:
                lines += ["", "Headlines"] + [f"  • {title}" for title in news]
        security.audit.record("briefing", f"{len(today)} item(s) today")
        return "\n".join(lines)

    # --- files ----------------------------------------------------------------

    def tidy(self, args: str) -> str:
        text = args.strip()
        if text.lower() == "undo":
            result = tidy.undo()
            security.audit.record("tidy undo", result.splitlines()[0])
            return result
        go = text.lower().startswith("go")
        target = text[2:].strip() if go else text
        folder = Path(target).expanduser() if target else pc.known_folder("downloads")
        if folder is None or not folder.is_dir():
            return f"No such folder: {target or 'Downloads'}"
        moves = tidy.plan(folder)
        if not go or not moves:
            self._tidy_folder = folder
            return tidy.describe(folder, moves)
        if not security.permissions.ask(
            security.WRITE_FILE, f"move {len(moves)} file(s) in {folder} into subfolders "
            "(nothing is deleted; /tidy undo puts them back)", context="/tidy",
        ):
            return "Denied. Nothing was moved."
        moved, failed = tidy.apply(moves)
        security.audit.record("tidy", str(folder), f"{moved} moved")
        text = f"Moved {moved} file(s) in {folder}. /tidy undo puts them all back."
        if failed:
            text += "\nSkipped:\n" + "\n".join(f"  {f}" for f in failed[:8])
        return text

    def qr(self, args: str):
        from .assistant import JarvisResponse
        from .config import get_output_dir

        text = args.strip()
        if not text:
            return "Usage: /qr <text or link>"
        try:
            import qrcode
        except ImportError:
            return "QR codes need the qrcode package (pip install qrcode)."
        image = qrcode.make(text, border=2)
        path = get_output_dir() / f"qr_{datetime.now():%Y%m%d_%H%M%S}.png"
        image.save(path)
        self.current_image = path
        return JarvisResponse(text=f"QR code for: {text[:120]}\nSaved to {path}", image_path=path,
                              image_paths=[path])

    def stopwatch(self, args: str) -> str:
        verb = args.strip().lower() or "status"
        state = getattr(self, "_stopwatch", None) or {"start": None, "elapsed": 0.0, "laps": []}
        self._stopwatch = state
        running = state["start"] is not None
        now = time.monotonic()
        total = state["elapsed"] + ((now - state["start"]) if running else 0)
        show = lambda seconds: f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{seconds % 60:05.2f}"  # noqa: E731
        if verb in {"start", "go", "resume"}:
            if running:
                return f"Already running: {show(total)}"
            state["start"] = now
            return "⏱ Stopwatch started." if not state["elapsed"] else f"⏱ Resumed at {show(total)}."
        if verb in {"stop", "pause"}:
            if not running:
                return f"Not running. {show(total)} on the clock."
            state["elapsed"], state["start"] = total, None
            return f"⏱ Stopped at {show(total)}."
        if verb == "lap":
            if not running:
                return "Start it first: /stopwatch start"
            state["laps"].append(total)
            return f"Lap {len(state['laps'])}: {show(total)}"
        if verb == "reset":
            self._stopwatch = None
            return "Stopwatch reset."
        laps = "".join(f"\n  lap {i}: {show(l)}" for i, l in enumerate(state["laps"], 1))
        return f"⏱ {show(total)} ({'running' if running else 'stopped'}){laps}\n/stopwatch start|stop|lap|reset"

    # --- code --------------------------------------------------------------------

    def _root(self):
        addon = self._project_addon()
        return getattr(addon, "root", None) if addon else None

    def review(self, args: str) -> str:
        from . import vcs

        root = self._root()
        if root is None:
            return "No project open. Use /project <folder> first."
        if not vcs.is_repo(root):
            return f"{root.name} is not a git repository, so there is no diff to review."
        _c, diff = vcs._run(root, "diff", "HEAD")
        _c, stat = vcs._run(root, "diff", "HEAD", "--stat")
        # git's line-ending notices arrive in the same output; they are not
        # part of the change and made the heading read "warning: in the…".
        stat = "\n".join(l for l in stat.splitlines() if not l.startswith("warning:"))
        diff = "\n".join(l for l in diff.splitlines() if not l.startswith("warning:"))
        if not diff.strip():
            return "There are no uncommitted changes to review."
        if not security.permissions.ask(security.SEND_CODE, f"your uncommitted changes, for review:\n{stat[-600:]}",
                                        context="/review"):
            return "Denied. Nothing was sent."
        security.audit.record("review", stat.strip().splitlines()[-1].strip() if stat.strip() else "")
        verdict = self.brain.ask_once(
            "Review this uncommitted diff before it is committed. List real problems only, most "
            "serious first: bugs, broken edge cases, security issues, secrets, leftover debug "
            "output, and changes a test should cover. Name the file and line for each. If it "
            "looks fine, say so in one sentence rather than inventing issues.\n\n"
            + args.strip() + "\n\n" + diff[:24000]
        )
        return f"Review of {stat.strip().splitlines()[-1].strip() if stat.strip() else 'your changes'}\n\n{verdict}"

    def agent_changes(self, args: str) -> str:
        import difflib

        worker = getattr(self, "_agent", None)
        if worker is None or (not worker.written and not worker.last_branch):
            return "The agent hasn't changed anything this session."
        if worker.last_branch and not worker.written:
            original, name = worker.last_branch
            _code, stat = worker._git("diff", "--stat", f"{original}..{name}")
            return f"The agent's work is on {name}:\n{stat}\n\n/git diff {original}..{name} to read it, /undo to discard."
        lines = [f"Files the agent changed ({len(worker.written)}):"]
        for path, backup in worker.written:
            relative = path.relative_to(worker.root) if worker.root else path
            if backup is None:
                lines.append(f"  + {relative}  (new file)")
                continue
            try:
                before = backup.read_text(encoding="utf-8", errors="replace").splitlines()
                after = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines.append(f"  ? {relative}")
                continue
            diff = list(difflib.unified_diff(before, after, lineterm="", n=0))
            added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
            removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
            lines.append(f"  ~ {relative}  (+{added} -{removed})")
            if args.strip() in {"full", "diff"}:
                lines += [f"      {d}" for d in diff[2:60]]
        lines += ["", "/revert <file> puts one back, /undo puts them all back, /changes full shows the diff."]
        return "\n".join(lines)

    def agent_revert(self, args: str) -> str:
        import shutil

        worker = getattr(self, "_agent", None)
        target = args.strip().strip('"').replace("\\", "/")
        if worker is None or not worker.written:
            return "There is nothing of the agent's to revert."
        if not target:
            return "Usage: /revert <file>   (see /changes)"
        for index, (path, backup) in enumerate(worker.written):
            relative = str(path.relative_to(worker.root)).replace("\\", "/") if worker.root else str(path)
            if relative == target or path.name == target:
                try:
                    if backup is None:
                        path.unlink(missing_ok=True)
                        done = f"Removed {relative} (the agent had created it)."
                    else:
                        shutil.copy2(backup, path)
                        done = f"Put {relative} back as it was."
                except OSError as exc:
                    return f"Couldn't revert {relative}: {exc}"
                worker.written.pop(index)
                security.audit.record("agent revert", relative)
                return done + (f" {len(worker.written)} other change(s) kept." if worker.written else "")
        return f"The agent didn't change '{target}'. /changes lists what it did."

    def explain(self, args: str) -> str:
        from . import index

        root = self._root()
        target = args.strip().strip('"')
        if not target:
            return "Usage: /explain <file>, /explain <file>:<line>, or /explain <function name>"
        m = re.fullmatch(r"(.+?):(\d+)", target)
        path_text, line = (m.group(1), int(m.group(2))) if m else (target, None)
        candidate = Path(path_text).expanduser()
        if root is not None and not candidate.is_absolute():
            candidate = root / path_text
        if candidate.is_file():
            try:
                lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                return f"Couldn't read it: {exc}"
            if line:
                start = max(0, line - 31)
                snippet = "\n".join(f"{n + 1:>5}  {l}" for n, l in enumerate(lines[start:line + 30], start))
                focus = f"Focus on line {line} and the code around it."
            else:
                snippet = "\n".join(lines)[:24000]
                focus = "Explain what the file is for, its main parts, and how they fit together."
            label = candidate.name + (f":{line}" if line else "")
        else:
            if root is None:
                return f"No such file: {target}. Open a project with /project to look up names."
            built = index.load(root) or index.build(root)
            hits = index.search(built, target)
            if not hits:
                return f"Nothing called '{target}' in {root.name}."
            symbol, snippet = hits[0]
            label = f"{symbol.name} ({symbol.file}:{symbol.line})"
            focus = f"Explain {symbol.name}: what it does, its inputs and outputs, and anything surprising."
        if not security.permissions.ask(security.SEND_CODE, f"{label}, to be explained", context="/explain"):
            return "Denied. Nothing was sent."
        security.audit.record("explain", label[:120])
        answer = self.brain.ask_once(f"{focus} Be clear and concrete; skip the obvious.\n\n--- {label} ---\n{snippet}")
        return f"{label}\n\n{answer}"

    def todos(self, args: str) -> str:
        root = self._root()
        if args.strip():
            root = Path(args.strip().strip('"')).expanduser()
        if root is None or not Path(root).is_dir():
            return "No project open. Use /project <folder>, or /todo <folder>."
        found: list[tuple[str, str, int, str]] = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in files:
                path = Path(folder) / name
                if path.suffix.lower() not in CODE_SUFFIXES:
                    continue
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        for number, text in enumerate(handle, 1):
                            m = TODO.search(text)
                            if m:
                                found.append((m.group(1).upper(), str(path.relative_to(root)), number,
                                              m.group(2).strip()[:100]))
                except OSError:
                    continue
                if len(found) >= 300:
                    break
        if not found:
            return f"No TODO, FIXME, HACK or XXX comments in {Path(root).name}."
        order = {"BUG": 0, "FIXME": 1, "HACK": 2, "XXX": 3, "TODO": 4}
        found.sort(key=lambda f: (order.get(f[0], 9), f[1], f[2]))
        counts: dict[str, int] = {}
        for kind, *_ in found:
            counts[kind] = counts.get(kind, 0) + 1
        lines = [f"{len(found)} marker(s) in {Path(root).name}: "
                 + ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9)))]
        lines += [f"  {kind:<5} {file}:{line}  {text}" for kind, file, line, text in found[:80]]
        if len(found) > 80:
            lines.append(f"  … and {len(found) - 80} more")
        return "\n".join(lines)

    def pull_request(self, args: str) -> str:
        from . import vcs

        root = self._root()
        if root is None or not vcs.is_repo(root):
            return "Open a git project first: /project <folder>."
        _c, branch = vcs._run(root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch.strip()
        base = args.strip() or next((b for b in ("main", "master", "develop")
                                     if vcs._run(root, "rev-parse", "--verify", "--quiet", b)[0] == 0), "")
        if not base:
            return "I couldn't find main or master. Name the base: /pr <branch>"
        if branch == base:
            return f"You're on {base} itself. Switch to the feature branch, then /pr."
        _c, log = vcs._run(root, "log", "--oneline", f"{base}..HEAD")
        _c, diff = vcs._run(root, "diff", f"{base}...HEAD")
        if not log.strip():
            return f"{branch} has no commits that {base} doesn't already have."
        if not security.permissions.ask(security.SEND_CODE, f"the changes on {branch} since {base}, to write a PR description",
                                        context="/pr"):
            return "Denied. Nothing was sent."
        security.audit.record("pr description", f"{branch} -> {base}")
        text = self.brain.ask_once(
            "Write a pull request for these changes: a title line under 70 characters, then "
            "'## Summary' (why, in two or three sentences), '## Changes' (bullets), and "
            "'## Testing' (what was run or should be). Be accurate to the diff; do not invent.\n\n"
            f"Commits:\n{log[:3000]}\n\nDiff:\n{diff[:20000]}"
        )
        return f"Pull request: {branch} → {base}\n\n{text}"

    # --- images and models -------------------------------------------------------

    def look(self, args: str, routed: bool = False):
        source = getattr(self, "current_image", None)
        if source is None or not Path(source).exists():
            if routed:
                return None
            return "Drop or attach an image first (or generate one), then ask about it."
        from PIL import Image

        with Image.open(source) as opened:
            image = opened.convert("RGB")
        image.thumbnail((1280, 1280))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        question = args.strip() or "Describe this image. Mention any text in it."
        security.audit.record("look", Path(source).name)
        return self.brain.ask_once(question, image_b64=base64.b64encode(buffer.getvalue()).decode("ascii"))

    def offline(self, args: str) -> str:
        wanted = args.strip().lower()
        models = providers.ollama_models(refresh=True)
        if wanted in {"on", "off"}:
            if wanted == "on" and not models:
                return ("Ollama isn't running on this PC, so there is nothing to answer offline.\n"
                        "  1. Install it: https://ollama.com/download\n"
                        "  2. In a terminal: ollama pull llama3.2\n"
                        "Then /offline on.")
            self._write_setting("JARVIS_OFFLINE", wanted)
            self.brain.reset_failures()
            return ("Offline mode on: only the model on this PC answers. Nothing is sent anywhere, "
                    "web search is off, and speech uses the Windows voice." if wanted == "on"
                    else "Offline mode off. The cloud providers answer again; Ollama stays as the last resort.")
        state = "ON" if providers.offline_mode() else "off"
        found = f"running, with {', '.join(models[:5])}" if models else "not running"
        return (f"Offline mode is {state}. Ollama is {found}.\n"
                "When Ollama is running it is always the last resort if every cloud provider fails. "
                "/offline on uses it alone.")


def headlines(limit: int = 4) -> list[str]:
    """Top headlines from a news feed — BBC World, or TRT Haber in Turkish.

    A web search for "top news today" returns news sites' home pages, not
    news; an RSS feed returns the actual headlines. JARVIS_NEWS_FEED picks
    another feed. Only the feed address is requested; nothing is sent.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    from . import i18n, net

    default = ("https://www.trthaber.com/manset_articles.rss" if i18n.current() == "tr"
               else "https://feeds.bbci.co.uk/news/world/rss.xml")
    url = get_setting("JARVIS_NEWS_FEED", default)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JARVIS briefing)"})
        with net.urlopen(request, timeout=8) as response:
            root = ET.fromstring(response.read())
    except Exception:
        return []
    titles = [" ".join((item.findtext("title") or "").split()) for item in root.findall(".//item")]
    return [t for t in titles if t][:limit]


def to_html(markdown: str, title: str) -> str:
    """A self-contained, readable HTML page. No scripts, no external files."""
    import html

    from . import writer

    def inline(text: str) -> str:
        out = []
        for kind, piece in writer.runs(text):
            piece = html.escape(piece)
            out.append(f"<strong>{piece}</strong>" if kind == "b" else f"<em>{piece}</em>" if kind == "i"
                       else f"<code>{piece}</code>" if kind == "code" else piece)
        return "".join(out)

    body: list[str] = []
    open_list = ""
    for kind, payload in writer.blocks(markdown):
        wanted = "ul" if kind == "li" else "ol" if kind == "ol" else ""
        if open_list and wanted != open_list:
            body.append(f"</{open_list}>")
            open_list = ""
        if wanted and not open_list:
            body.append(f"<{wanted}>")
            open_list = wanted
        if kind == "h":
            level, text = payload
            body.append(f"<h{level}>{inline(text)}</h{level}>")
        elif kind in {"li", "ol"}:
            body.append(f"<li>{inline(payload)}</li>")
        elif kind == "p":
            body.append(f"<p>{inline(payload)}</p>")
        elif kind == "quote":
            body.append(f"<blockquote>{inline(payload)}</blockquote>")
        elif kind == "code":
            body.append(f"<pre><code>{html.escape(payload)}</code></pre>")
        elif kind == "table":
            rows = "".join("<tr>" + "".join(f"<{'th' if r == 0 else 'td'}>{inline(c)}</{'th' if r == 0 else 'td'}>"
                                            for c in row) + "</tr>" for r, row in enumerate(payload))
            body.append(f"<table>{rows}</table>")
        elif kind == "hr":
            body.append("<hr>")
    if open_list:
        body.append(f"</{open_list}>")
    style = ("body{font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin:40px auto;padding:0 16px;"
             "line-height:1.55;color:#1f2937}h1{color:#0e7490}h2{margin-top:28px;font-size:15px;"
             "text-transform:uppercase;letter-spacing:.06em;color:#64748b}pre{background:#0f172a;color:#e2e8f0;"
             "padding:12px;border-radius:8px;overflow:auto}code{background:#f1f5f9;padding:1px 4px;border-radius:4px}"
             "pre code{background:none;padding:0}table{border-collapse:collapse}td,th{border:1px solid #cbd5e1;"
             "padding:4px 8px}blockquote{border-left:3px solid #94a3b8;margin:0;padding-left:12px;color:#475569}")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
            f"<style>{style}</style></head><body>{''.join(body)}</body></html>")
