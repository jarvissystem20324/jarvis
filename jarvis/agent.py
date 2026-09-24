"""Agent mode — JARVIS plans a job, you approve it, then it does the work.

The shape of this is set by one decision: **you approve a plan, not forty
prompts.** Asking permission for every file write and every command is right
for a chat assistant and useless for an agent — a ten-step task becomes ten
dialogs, and a person who is clicking Allow without reading is less safe than
one who read a single plan carefully.

So the contract is:

  1. JARVIS writes a plan and shows it in full: every file it will read, every
     file it will write, every command it will run.
  2. You approve that plan once, or you don't.
  3. It executes only what the plan said. Wanting to touch a file the plan did
     not name is not a prompt — it is a stop, reported back to you.
  4. Every step goes to the audit log as it happens, and Stop ends it between
     any two steps.

The plan is therefore a boundary, not a suggestion, and the code below treats
it that way: `_permitted` is checked before every single write and command,
against the approved plan and nothing else.

Nothing here runs a shell. Commands are matched against a fixed table of
actions — run the tests, ask git something — and anything else is refused, so
an approved plan cannot smuggle in an arbitrary command string.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import security

# A runaway loop is the failure mode that matters, so it is bounded twice:
# by the plan the user approved and by this.
MAX_STEPS = 24
# Untracked files that are never anyone's work in progress.
_CLUTTER = re.compile(r"(^|/)(__pycache__|\.pytest_cache)(/|$)|\.pyc$|\.jarvis-\d{8}_\d{6}\.bak$")
MAX_FIX_ROUNDS = 4
STEP_TIMEOUT = 300
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PLANNER_PROMPT = """You are planning a software task that will be carried out
by an agent with a fixed, small set of abilities. Reply with JSON only — no
prose, no markdown fence.

{
  "goal": "one sentence restating what will be done",
  "steps": [
    {"action": "read",  "target": "path/to/file.py", "why": "short reason"},
    {"action": "write", "target": "path/to/file.py", "why": "short reason"},
    {"action": "test",  "target": "",                "why": "short reason"},
    {"action": "git",   "target": "status",          "why": "short reason"}
  ],
  "risk": "what could go wrong, in one sentence"
}

Rules:
- Only these actions exist: read, write, test, git. Nothing else.
- git targets may only be: status, diff, log.
- Every file you intend to change must appear as a "write" step. A file not
  listed cannot be written later.
- Read a file before writing it, unless you are creating it.
- Prefer the smallest plan that does the job. Five steps beats fifteen.
- A plan may contain several write/test cycles, so "fix it and check,
  then fix the next thing and check again" is expressible. What you
  cannot do is decide later to touch a file this plan does not list.
- You are given the actual failure output when there is one, so plan
  against what really happened rather than describing a loop.
- If the request is unclear or cannot be done with these actions, return
  {"goal": "...", "steps": [], "risk": "why this cannot be planned"}.
"""

WORKER_PROMPT = """You are carrying out one step of an approved plan.

Return the COMPLETE new contents of the file inside a single fenced block
whose info line is the file's path, exactly:

```path/to/file.py
...complete file...
```

Never abbreviate, never write "... rest unchanged ...". The block replaces the
file wholesale, so anything you leave out is deleted. If you cannot do the
step, say so in plain text with no fenced block."""


@dataclass
class Step:
    action: str
    target: str
    why: str = ""
    status: str = "pending"     # pending | done | failed | skipped
    detail: str = ""

    def line(self) -> str:
        mark = {"done": "+", "failed": "!", "skipped": "-"}.get(self.status, " ")
        target = f" {self.target}" if self.target else ""
        return f"  {mark} {self.action}{target}" + (f"  — {self.why}" if self.why else "")


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    risk: str = ""
    # Filled in by the agent before approval: on a branch, or in place.
    where: str = ""
    # Which provider and model wrote this plan. Shown before approval,
    # because the model that plans is the one the code is sent to.
    model: str = ""

    @property
    def writes(self) -> list[str]:
        return [s.target for s in self.steps if s.action == "write" and s.target]

    @property
    def reads(self) -> list[str]:
        return [s.target for s in self.steps if s.action == "read" and s.target]

    @property
    def commands(self) -> list[str]:
        out = []
        for s in self.steps:
            if s.action == "test":
                out.append("run the project's test suite")
            elif s.action == "git":
                out.append(f"git {s.target}")
        return out

    def describe(self) -> str:
        """What the approval prompt shows. Everything, nothing hidden."""
        lines = [f"Goal: {self.goal}", "", "Steps:"]
        lines += [s.line() for s in self.steps]
        if self.writes:
            lines += ["", f"Files it will CHANGE ({len(self.writes)}):"]
            lines += [f"  {w}" for w in self.writes]
        else:
            lines += ["", "It will not change any files."]
        if self.commands:
            lines += ["", "Commands it will run:"]
            lines += [f"  {c}" for c in dict.fromkeys(self.commands)]
        if self.where:
            lines += ["", f"Where: {self.where}"]
        if self.model:
            lines += [f"Model: {self.model}"]
        if self.risk:
            lines += ["", f"Risk: {self.risk}"]
        return "\n".join(lines)

    def summary(self) -> str:
        """One line, for the permission dialog's detail field."""
        return (
            f"{len(self.steps)} steps, "
            f"{len(self.writes)} file(s) changed, "
            f"{len(set(self.commands))} command(s)"
        )


class AgentError(Exception):
    """Something the user needs to read, not a crash."""


def parse_plan(text: str) -> Plan:
    """Turn the model's answer into a Plan, tolerating a stray fence."""
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise AgentError("I couldn't turn that into a plan — no JSON came back.")
    try:
        data = json.loads(body[start:end + 1])
    except ValueError as exc:
        raise AgentError(f"The plan wasn't valid JSON: {exc}")

    steps: list[Step] = []
    for raw in data.get("steps") or []:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action", "")).strip().lower()
        if action not in {"read", "write", "test", "git"}:
            continue
        steps.append(Step(
            action=action,
            target=str(raw.get("target", "")).strip(),
            why=str(raw.get("why", "")).strip(),
        ))
    return Plan(
        goal=str(data.get("goal") or "").strip() or "(no goal given)",
        steps=steps[:MAX_STEPS],
        risk=str(data.get("risk") or "").strip(),
    )


class Agent:
    """Plans and carries out a task inside one project folder."""

    # git subcommands that only read. Anything that writes to the repository
    # is deliberately absent: an agent that can commit is a different
    # conversation from one that can read, and this one only reads.
    GIT_READS = {"status", "diff", "log", "branch", "show"}

    def __init__(self, jarvis):
        self.jarvis = jarvis
        self.plan: Plan | None = None
        # Every model that did some of the work, in order, for the report.
        self.models_used: list[str] = []
        # Why the agent's own model (GLM-5 Turbo by default) was passed over.
        self.fallback_note = ""
        self.root: Path | None = None
        self.written: list[tuple[Path, Path | None]] = []
        # (original branch, work branch) after a run that used one.
        self.last_branch: tuple[str, str] | None = None

    # --- project ----------------------------------------------------------

    def _code_addon(self):
        for entry in self.jarvis.addons.loaded:
            if entry.addon.name == "code-mode":
                return entry.addon
        return None

    def _resolve(self, relative: str) -> Path:
        """A path inside the project, or an error. '../' never escapes."""
        if self.root is None:
            raise AgentError("No project is open. Use /project <folder> first.")
        candidate = (self.root / relative.strip().strip('"').strip("'")).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise AgentError(f"Bad path '{relative}': {exc}")
        if self.root not in resolved.parents and resolved != self.root:
            raise AgentError(
                f"'{relative}' is outside {self.root}. The agent only ever "
                "touches files inside the open project."
            )
        return resolved

    # --- planning ---------------------------------------------------------

    def make_plan(self, goal: str) -> Plan:
        addon = self._code_addon()
        self.root = getattr(addon, "root", None) if addon else None
        if self.root is None:
            raise AgentError(
                "No project is open, so there is nothing for me to work on.\n"
                "Open one with /project <folder>, then try again."
            )

        layout = addon._tree_text(limit=40) if addon else ""
        self.models_used = []
        self.fallback_note = ""
        answer = self._ask(
            f"{PLANNER_PROMPT}\n\nProject: {self.root}\n"
            f"Layout:\n{layout}\n\nTask: {goal}"
        )
        plan = parse_plan(answer)
        plan.model = self.models_used[-1] if self.models_used else ""
        if self.fallback_note:
            plan.model += f"\n  ({self.fallback_note})"
        if not plan.steps:
            raise AgentError(
                f"I couldn't turn that into a plan.\n\n{plan.risk or plan.goal}"
            )
        _will, plan.where = self.branch_plan()
        self.plan = plan
        return plan

    def _ask(self, prompt: str) -> str:
        """One model call, on the agent's own model when it answers.

        JARVIS_AGENT_MODEL names it (GLM-5 Turbo through Blueminds by
        default). If that model refuses or stays silent, the brain skips it
        for the session and the current mode's models answer instead.
        """
        from . import modes

        brain = self.jarvis.brain
        try:
            answer = brain.ask_once(
                prompt, targets=modes.agent_targets(), target_timeout=modes.AGENT_TIMEOUT
            )
        except TypeError:
            # A brain without per-call targets (the tests' stand-in).
            answer = brain.ask_once(prompt)
        used = getattr(brain, "last_answered", lambda: "")()
        if used:
            self.models_used.append(used)
        # Say why the chosen model did not do the work, once, in plain words.
        wanted = modes.agent_targets()
        if wanted and used and not any(model in used for _p, model in wanted) and not self.fallback_note:
            reasons = [p for p in getattr(brain, "last_problems", []) or []
                       if any(model in p for _p, model in wanted)]
            if reasons:
                inside = re.search(r"\(([^()]*)\)\s*$", reasons[0])
                why = inside.group(1) if inside else reasons[0].split(": ", 1)[-1]
            else:
                why = "it failed earlier this session, so it is skipped until restart"
            self.fallback_note = f"{wanted[0][1]} ({wanted[0][0]}) was not used — {why}"
        return answer

    def _permitted(self, action: str, target: str) -> bool:
        """Is this exact action on this exact target in the approved plan?

        Checked before every write and every command, so a step the model
        invents mid-run cannot execute just because the plan as a whole was
        approved.
        """
        if self.plan is None:
            return False
        return any(
            s.action == action and s.target == target for s in self.plan.steps
        )

    # --- execution --------------------------------------------------------

    # --- working on a branch ----------------------------------------------
    # When the project is a git repository with a clean working tree, the
    # agent does its work on a fresh branch, commits it there, and switches
    # back. Your working tree is never touched: the result is a branch you can
    # diff, merge or delete. The *harness* does these git writes — the model's
    # plan still cannot run any git command that changes anything.

    def _git(self, *args: str) -> tuple[int, str]:
        from . import vcs

        try:
            return vcs._run(self.root, *args)
        except vcs.GitError as exc:
            return 1, str(exc)

    def branch_plan(self) -> tuple[bool, str]:
        """(will branch, sentence explaining the decision)."""
        if self.root is None or not (self.root / ".git").exists():
            return False, "Not a git repository, so changes are made in place (/undo reverts them)."
        # Clutter does not count: __pycache__ and the agent's own .bak
        # backups made one /fix run enough to stop every later run from
        # branching. Your own untracked files still do — if the plan wrote
        # one on a branch, switching back would take it out of your folder.
        code, status = self._git("status", "--porcelain")
        dirty = "\n".join(
            line for line in status.splitlines()
            if line.strip() and not (line.startswith("??") and _CLUTTER.search(line[3:].strip().strip('"')))
        )
        if code != 0:
            return False, "git is unavailable, so changes are made in place (/undo reverts them)."
        if dirty.strip():
            # Branching now would carry your uncommitted edits along and mix
            # them with the agent's, which is the opposite of isolation.
            return False, (
                "Your working tree has uncommitted changes, so I'll work in "
                "place rather than on a branch (/undo reverts my changes)."
            )
        code, head = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if code != 0 or head.strip() in {"", "HEAD"}:
            return False, "No branch is checked out, so changes are made in place."
        return True, "Works on a new branch and commits there; your working tree is left alone."

    def _start_branch(self) -> tuple[str, str] | None:
        will, _why = self.branch_plan()
        if not will:
            return None
        _code, original = self._git("rev-parse", "--abbrev-ref", "HEAD")
        original = original.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", self.plan.goal.lower()).strip("-")[:40] or "task"
        from datetime import datetime

        name = f"jarvis/{slug}-{datetime.now():%H%M%S}"
        code, out = self._git("switch", "-c", name)
        if code != 0:
            code, out = self._git("checkout", "-b", name)
        if code != 0:
            return None
        security.audit.record("agent branch", name, f"from {original}")
        return original, name

    def _finish_branch(self, original: str, name: str) -> str:
        """Commit what was written onto the branch, then go back."""
        from . import vcs

        if not self.written:
            self._git("switch", original)
            self._git("branch", "-D", name)
            return "Nothing was changed, so the work branch was removed."

        relative = [str(path.relative_to(self.root)) for path, _backup in self.written]
        self._git("add", "--", *relative)

        leaks = vcs._secret_check(self.root)
        if leaks:
            # Do not commit, and do not switch back: switching would carry the
            # uncommitted changes onto your branch.
            return (
                f"I did NOT commit: the changes on {name} contain what looks "
                f"like a credential. You are still on {name} with the changes "
                "staged. Remove it, then commit or discard by hand."
            )

        code, out = self._git("commit", "-m", f"JARVIS agent: {self.plan.goal[:120]}")
        if code != 0:
            return (
                f"The changes are on {name} but could not be committed:\n{out[:300]}\n"
                f"You are still on {name}."
            )
        self._git("switch", original)
        security.audit.record("agent commit", name, f"{len(relative)} file(s)")

        # The files on your branch were never touched, so there is nothing
        # for the file-level undo to restore; /undo deletes the branch instead.
        # The .bak copies are redundant now — the commit is the record — and
        # were left behind as clutter in your project.
        for _path, backup in self.written:
            if backup is not None:
                try:
                    backup.unlink()
                except OSError:
                    pass
        self.written = []
        self.last_branch = (original, name)
        return (
            f"The work is on branch {name} ({len(relative)} file(s), one commit).\n"
            f"You are back on {original}, unchanged.\n"
            f"  Review:  /git diff {original}..{name}\n"
            f"  Keep:    git merge {name}\n"
            f"  Discard: /undo"
        )

    def run(self, on_progress=None, should_continue=None) -> str:
        """Carry out the approved plan. Returns a report."""
        if self.plan is None:
            raise AgentError("There is no approved plan to run.")

        self.last_branch = None
        branch = self._start_branch()
        report = self._run_steps(on_progress, should_continue)
        if branch is not None:
            report += "\n\n" + self._finish_branch(*branch)
        return report

    def _run_steps(self, on_progress=None, should_continue=None) -> str:
        def say(text: str) -> None:
            if on_progress is not None:
                on_progress(text)

        self.written = []
        context: list[str] = []
        done = 0

        for index, step in enumerate(self.plan.steps, 1):
            if should_continue is not None and not should_continue():
                step.status = "skipped"
                security.audit.record("agent", "stopped by user", f"at step {index}")
                return self._report("Stopped.")

            say(f"[{index}/{len(self.plan.steps)}] {step.action} {step.target}".strip())
            try:
                if step.action == "read":
                    context.append(self._do_read(step))
                elif step.action == "write":
                    context.append(self._do_write(step, context))
                elif step.action == "test":
                    context.append(self._do_test(step))
                elif step.action == "git":
                    context.append(self._do_git(step))
                step.status = step.status if step.status != "pending" else "done"
                done += 1
            except AgentError as exc:
                step.status = "failed"
                step.detail = str(exc)
                security.audit.record("agent", f"{step.action} {step.target}", "FAILED")
                return self._report(f"Stopped at step {index}: {exc}")

            # Keep the context from growing without bound on a long plan.
            context = context[-6:]

        # "Finished" is not the same as "worked". If the plan ended on a
        # test step that did not pass, say so first — otherwise a report
        # full of plus signs reads like success.
        tests = [s for s in self.plan.steps if s.action == "test"]
        if tests and tests[-1].detail not in ("passed", ""):
            return self._report(
                f"Ran all {done} steps, but the tests still do not pass "
                f"({tests[-1].detail}). The changes are on disk — /undo "
                f"reverts them."
            )
        return self._report(f"Finished all {done} steps.")

    def _do_read(self, step: Step) -> str:
        path = self._resolve(step.target)
        if not path.is_file():
            raise AgentError(f"{step.target} does not exist.")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AgentError(f"Could not read {step.target}: {exc}")
        security.audit.record("agent read", step.target, f"{len(text)} chars")
        step.detail = f"{len(text.splitlines())} lines"
        return f"--- {step.target} ---\n{text[:40000]}"

    def _do_write(self, step: Step, context: list[str]) -> str:
        if not self._permitted("write", step.target):
            raise AgentError(
                f"{step.target} is not in the approved plan, so I did not write it."
            )
        path = self._resolve(step.target)

        answer = self._ask(
            f"{WORKER_PROMPT}\n\nGoal: {self.plan.goal}\n"
            f"This step: {step.why or 'update ' + step.target}\n"
            f"File to produce: {step.target}\n\n"
            + "\n\n".join(context[-4:])
        )
        addon = self._code_addon()
        blocks = addon._blocks(answer) if addon else []
        body = next((b for p, b in blocks if p == step.target), None)
        if body is None and blocks:
            body = blocks[-1][1]      # only one block, wrong label
        if body is None:
            raise AgentError(
                f"I couldn't produce new contents for {step.target}. "
                f"It said:\n{answer[:300]}"
            )
        if not body.strip():
            # An empty file is a real thing — tests/__init__.py exists to be
            # empty. Creating one is fine; emptying a file that currently has
            # something in it is almost always a mistake, so that is refused.
            existing = ""
            if path.exists():
                try:
                    existing = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    existing = ""
            if existing.strip():
                raise AgentError(
                    f"It produced an empty {step.target}, which currently has "
                    f"{len(existing.splitlines())} lines in it. Refusing to "
                    "blank an existing file."
                )

        import shutil
        from datetime import datetime

        backup = None
        if path.exists():
            backup = path.with_name(
                f"{path.name}.jarvis-{datetime.now():%Y%m%d_%H%M%S}.bak"
            )
            try:
                shutil.copy2(path, backup)
            except OSError as exc:
                raise AgentError(f"Could not back up {step.target}, so I stopped: {exc}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            raise AgentError(f"Writing {step.target} failed: {exc}")

        self.written.append((path, backup))
        security.audit.record("agent write", step.target,
                              "new file" if backup is None else f"backup {backup.name}")
        step.detail = f"{len(body.splitlines())} lines"
        return f"--- {step.target} (now written) ---\n{body[:20000]}"

    def _do_test(self, step: Step) -> str:
        if not self._permitted("test", step.target):
            raise AgentError("Running the tests was not part of the approved plan.")
        addon = self._code_addon()
        if addon is None:
            raise AgentError("The code-mode addon is not loaded, so I cannot run tests.")
        detected = addon._detect_test_command()
        if detected is None:
            raise AgentError("I can't tell how this project runs its tests.")
        command, label = detected
        security.audit.record("agent test", " ".join(command))
        try:
            proc = subprocess.run(
                command, cwd=str(self.root), capture_output=True, text=True,
                timeout=STEP_TIMEOUT, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW,
            )
        except FileNotFoundError:
            raise AgentError(f"{label} is not installed.")
        except subprocess.TimeoutExpired:
            raise AgentError(f"{label} was still running after {STEP_TIMEOUT}s.")
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        step.status = "done" if proc.returncode == 0 else "failed"
        step.detail = "passed" if proc.returncode == 0 else f"exit {proc.returncode}"
        if proc.returncode != 0:
            # A failing test is information, not a reason to stop: the next
            # step is usually the fix.
            step.status = "done"
        return f"--- {label} (exit {proc.returncode}) ---\n{output[-8000:]}"

    def _do_git(self, step: Step) -> str:
        sub = (step.target or "status").split()[0].lower()
        if sub not in self.GIT_READS:
            raise AgentError(
                f"'git {sub}' is not something the agent may run. It only reads: "
                + ", ".join(sorted(self.GIT_READS))
            )
        if not self._permitted("git", step.target):
            raise AgentError(f"'git {step.target}' was not in the approved plan.")
        security.audit.record("agent git", sub)
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.root), sub],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise AgentError(f"git {sub} failed: {exc}")
        step.detail = "ok"
        return f"--- git {sub} ---\n{(proc.stdout or '')[:8000]}"

    # --- results ----------------------------------------------------------

    def _report(self, headline: str) -> str:
        lines = [headline, ""]
        for step in self.plan.steps:
            row = step.line()
            if step.detail:
                row += f"   [{step.detail}]"
            lines.append(row)
        if self.written:
            lines.append("")
            lines.append(f"{len(self.written)} file(s) changed — /undo puts them back.")
        used = list(dict.fromkeys(self.models_used))
        if used:
            lines.append("Model: " + ", then ".join(used))
        if self.fallback_note:
            lines.append(f"  ({self.fallback_note})")
        return "\n".join(lines)

    def undo(self) -> str:
        """Put every file this run touched back the way it was."""
        if self.last_branch and not self.written:
            original, name = self.last_branch
            code, out = self._git("branch", "-D", name)
            self.last_branch = None
            if code != 0:
                return f"Could not delete {name}: {out[:200]}"
            security.audit.record("agent undo", f"deleted {name}")
            return f"Deleted branch {name}. {original} was never changed."
        if not self.written:
            return "The agent hasn't written anything to undo."
        import shutil

        restored, failed = [], []
        for path, backup in reversed(self.written):
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                    restored.append(f"removed {path.name}")
                else:
                    shutil.copy2(backup, path)
                    restored.append(f"restored {path.name}")
            except OSError as exc:
                failed.append(f"{path.name}: {exc}")
        self.written = []
        text = "Rolled back: " + ", ".join(restored) if restored else ""
        if failed:
            text += "\nCould NOT roll back: " + "; ".join(failed)
        security.audit.record("agent undo", f"{len(restored)} file(s)")
        return text
