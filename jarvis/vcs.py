"""Git, from inside JARVIS.

Reading the repository is free. Changing it — staging, committing, branching,
pushing — asks first, every time, because those are the operations you cannot
quietly undo later.

Two rules that are not negotiable:

  * **No shell.** Every call is an argument list. A branch name or commit
    message containing `; rm -rf ~` is a branch name containing punctuation,
    not a second command.
  * **Nothing commits a secret.** Before a commit is made, the staged diff
    goes through the same scanner `/scan` uses. A hardcoded key stops the
    commit — which is the near-miss this project already had once, when a
    `.env.backup-*` file was staged and caught by hand.

`push` is the one operation that leaves the machine, so it is called out
separately in the prompt rather than treated as just another git command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import scanner, security

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TIMEOUT = 90

# Everything that only looks.
READ_ONLY = {
    "status", "diff", "log", "branch", "show", "remote", "config",
    "describe", "shortlog", "blame", "ls-files",
}
# Everything that changes the repository. Each asks.
WRITES = {"add", "commit", "checkout", "switch", "branch-create", "push", "pull", "reset"}


class GitError(Exception):
    """Readable failure, not a traceback."""


def _run(root: Path, *args: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
        )
    except FileNotFoundError:
        raise GitError("git is not installed, or is not on PATH.")
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0] if args else ''} took longer than {timeout}s.")
    except OSError as exc:
        raise GitError(f"git failed to start: {exc}")
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def status(root: Path) -> str:
    code, out = _run(root, "status", "--short", "--branch")
    if code != 0:
        raise GitError(out or "git status failed.")
    return out or "Working tree clean."


def staged_diff(root: Path) -> str:
    _code, out = _run(root, "diff", "--cached")
    return out


def _secret_check(root: Path) -> list:
    """Findings in what is about to be committed."""
    diff = staged_diff(root)
    if not diff.strip():
        return []
    added = "\n".join(
        line[1:] for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return [f for f in scanner.scan_text(added, "staged changes", ".txt")
            if f.level == "high"]


def handle(root: Path, args: str) -> str:
    """Run one git command. Writes ask permission; reads do not."""
    if not is_repo(root):
        return f"{root.name} is not a git repository."

    parts = args.strip().split()
    if not parts:
        return (
            "Usage: /git <command>\n\n"
            "  Reads (no prompt):  " + ", ".join(sorted(READ_ONLY)) + "\n"
            "  Writes (each asks): add, commit -m \"msg\", branch <name>, "
            "checkout <name>, push\n\n"
            + status(root)
        )

    sub = parts[0].lower()
    rest = parts[1:]

    if sub in READ_ONLY:
        extra = ["--short", "--branch"] if sub == "status" else []
        if sub == "log" and not rest:
            extra = ["--oneline", "-15"]
        code, out = _run(root, sub, *extra, *rest)
        if code != 0 and not out:
            raise GitError(f"git {sub} failed.")
        return out or f"(git {sub} said nothing)"

    if sub == "add":
        target = " ".join(rest) or "."
        if not security.permissions.ask(
            security.WRITE_FILE, f"git add {target}", context="/git"
        ):
            return "Denied. Nothing was staged."
        code, out = _run(root, "add", *(rest or ["."]))
        security.audit.record("git add", target, "ok" if code == 0 else "failed")
        if code != 0:
            raise GitError(out or "git add failed.")
        return "Staged.\n\n" + status(root)

    if sub == "commit":
        message = _message(rest)
        if not message:
            return 'Usage: /git commit -m "what changed and why"'

        leaks = _secret_check(root)
        if leaks:
            security.audit.record("git commit", "blocked", f"{len(leaks)} secret(s)")
            return (
                "Refusing to commit — the staged changes contain what look "
                f"like credentials ({len(leaks)} found):\n\n"
                + scanner.format_report(leaks, 5)
                + "\n\nUnstage them, move the value into .env, and make sure "
                ".env is git-ignored."
            )
        if not staged_diff(root).strip():
            return "Nothing is staged, so there is nothing to commit. /git add first."

        if not security.permissions.ask(
            security.WRITE_FILE,
            f'git commit -m "{message[:160]}"\n\n{status(root)}',
            context="/git",
        ):
            return "Denied. Nothing was committed."
        code, out = _run(root, "commit", "-m", message)
        security.audit.record("git commit", message[:80], "ok" if code == 0 else "failed")
        if code != 0:
            raise GitError(out or "git commit failed.")
        return out

    if sub in {"checkout", "switch"}:
        if not rest:
            return f"Usage: /git {sub} <branch>"
        name = rest[0]
        if not security.permissions.ask(
            security.WRITE_FILE, f"git {sub} {name}", context="/git"
        ):
            return "Denied."
        code, out = _run(root, sub, *rest)
        security.audit.record(f"git {sub}", name, "ok" if code == 0 else "failed")
        return out or f"Now on {name}."

    if sub == "push":
        # The only one that leaves this machine, so it is asked as a network
        # action rather than as another repository edit.
        _code, remote = _run(root, "remote", "-v")
        if not security.permissions.ask(
            security.NETWORK,
            "git push — this publishes your commits.\n\n" + (remote or "(no remote)"),
            context="/git",
        ):
            return "Denied. Nothing was pushed."
        code, out = _run(root, "push", *rest, timeout=300)
        security.audit.record("git push", " ".join(rest) or "default",
                              "ok" if code == 0 else "failed")
        if code != 0:
            raise GitError(out or "git push failed.")
        return out or "Pushed."

    return (
        f"'{sub}' is not a git command JARVIS runs. Reads: "
        + ", ".join(sorted(READ_ONLY))
        + ". Writes: add, commit, checkout, push."
    )


def _message(rest: list[str]) -> str:
    """Pull the message out of `-m "..."` or just the remaining words."""
    if rest and rest[0] in {"-m", "--message"}:
        rest = rest[1:]
    return " ".join(rest).strip().strip('"').strip("'")
