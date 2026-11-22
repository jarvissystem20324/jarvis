"""Agent teams (14.3): a lead agent does the work, sub-agents check it.

With teams on, the coding agent stops being one model talking to itself. A
lead writes each file; then one or more checkers — different models, so they
don't share the lead's blind spots — read what it wrote against what you
asked for. If a checker finds a real problem, the lead fixes it once before
moving on, and the report says who checked what.

You don't pick the models: JARVIS picks a team for the thinking mode you're
in. Low is quick (one fast checker), Mid and High have the strong lead with a
vision-capable reviewer, and Max, Hyperdrive and Security add a second checker.
Like every model choice in JARVIS, these are preferences: a model that is
missing a key, busy or retired falls through to the next one, then to the
usual provider chain, so a team never stops the work.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import get_setting

SETTING = "JARVIS_AGENT_TEAMS"

# The lead: Claude Opus 4.7 through LLMsRelay (the user's choice), then the
# agent's usual model, so a missing relay key still leaves a strong lead.
LEAD = (("llmsrelay", "claude-opus-4.7"), ("llmsrelay", "claude-opus-4.6"))
# The reviewer: NVIDIA Nemotron 3.5 Super VL, free on OpenRouter; the same
# model on NVIDIA's own API when there's no OpenRouter key; then Groq.
NEMOTRON = (("openrouter", "nvidia/nemotron-3.5-super-vl:free"),
            ("nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
            ("groq", "openai/gpt-oss-120b"))
GPT_OSS = (("groq", "openai/gpt-oss-120b"), ("cloudflare", "@cf/openai/gpt-oss-120b"))
MERCURY = (("inception", "mercury-2.5"),)

# Seconds a checker gets: a review is short, and the work waits for it.
CHECK_TIMEOUT = 90.0
MAX_ISSUES = 5


@dataclass(frozen=True)
class Member:
    name: str                      # "Reviewer", "Tester", "Security reviewer"
    targets: tuple[tuple[str, str], ...]
    focus: str = ""                # what this checker looks for, beyond the basics


@dataclass(frozen=True)
class Team:
    mode: str
    lead: tuple[tuple[str, str], ...]
    checkers: tuple[Member, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        lead = _pretty(self.lead[0]) if self.lead else "the mode's model"
        crew = ", ".join(f"{m.name}: {_pretty(m.targets[0])}" for m in self.checkers) or "no checkers"
        return f"Lead: {lead} · {crew}"


REVIEWER = Member("Reviewer", NEMOTRON)
TESTER = Member("Tester", GPT_OSS, "Walk through the code with real inputs, including empty, wrong and very large "
                                   "ones, and say exactly where it breaks.")
SECURITY = Member("Security reviewer", GPT_OSS, "Look for injection, secrets in code, unsafe file or network use, "
                                                "and input that is trusted without checking.")

TEAMS = {
    "low": Team("low", MERCURY + LEAD, (Member("Reviewer", GPT_OSS),)),
    "mid": Team("mid", LEAD, (REVIEWER,)),
    "high": Team("high", LEAD, (REVIEWER,)),
    "max": Team("max", LEAD, (REVIEWER, TESTER)),
    "hyperdrive": Team("hyperdrive", LEAD, (REVIEWER, TESTER)),
    "security": Team("security", LEAD, (SECURITY, REVIEWER)),
}

CHECK_PROMPT = """You are the {role} on a small coding team. The lead wrote the
file below for the task. Check it for real problems only: bugs, anything the
task asked for that is missing, broken links between files (a page loading a
script that has another name, a function called but never defined), and
security holes. {focus}Ignore style, naming and taste.

Reply with JSON only, no prose and no markdown fence:
{{"ok": true}}  when it is good enough to ship, or
{{"ok": false, "issues": ["the specific problem and how to fix it", ...]}}
with at most {max_issues} issues, the most important first."""


def enabled() -> bool:
    return get_setting(SETTING, "off").strip().lower() in {"on", "1", "true", "yes"}


def team_for(mode_name: str | None) -> Team:
    return TEAMS.get((mode_name or "").strip().lower(), TEAMS["mid"])


@dataclass
class Review:
    member: str
    model: str
    ok: bool
    issues: list[str]

    def line(self) -> str:
        who = f"{self.member} ({self.model})" if self.model else self.member
        if self.ok:
            return f"{who}: ✓ looks right"
        return f"{who}: found {len(self.issues)} issue(s)"


def parse_review(text: str) -> tuple[bool, list[str]]:
    """The checker's verdict. Anything unclear counts as a pass: a checker
    that rambles must never block the work, only one that names a problem."""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        return True, []
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return True, []
    issues = [str(i).strip() for i in (data.get("issues") or []) if str(i).strip()][:MAX_ISSUES]
    ok = bool(data.get("ok", not issues))
    return (ok or not issues), ([] if ok else issues)


def check(brain, member: Member, task: str, goal: str, path: str, content: str) -> Review:
    """One checker reads one file. Never raises: a failed check is a pass."""
    prompt = (CHECK_PROMPT.format(role=member.name.lower(), focus=f"{member.focus} " if member.focus else "",
                                  max_issues=MAX_ISSUES)
              + f"\n\nWhat the user asked: {task}\nGoal: {goal}\nFile: {path}\n\n```{path}\n{content[:30000]}\n```")
    try:
        try:
            reply = brain.ask_once(prompt, targets=member.targets, target_timeout=CHECK_TIMEOUT)
        except TypeError:
            reply = brain.ask_once(prompt)     # a brain without per-call targets (tests)
    except Exception:
        return Review(member.name, "", True, [])
    model = getattr(brain, "last_answered", lambda: "")() or ""
    ok, issues = parse_review(reply)
    return Review(member.name, model, ok, issues)


def _pretty(target: tuple[str, str]) -> str:
    provider, model = target
    names = {"claude-opus-4.7": "Claude Opus 4.7", "claude-opus-4.6": "Claude Opus 4.6",
             "nvidia/nemotron-3.5-super-vl:free": "Nemotron 3.5 Super VL",
             "nvidia/nemotron-3.5-super-vl-120b-a12b": "Nemotron 3.5 Super VL",
             "openai/gpt-oss-120b": "gpt-oss-120b", "@cf/openai/gpt-oss-120b": "gpt-oss-120b",
             "mercury-2.5": "Mercury 2.5"}
    where = {"llmsrelay": "LLMsRelay", "openrouter": "OpenRouter", "nvidia": "NVIDIA", "groq": "Groq",
             "cloudflare": "Cloudflare", "inception": "Inception"}
    return f"{names.get(model, model)} ({where.get(provider, provider)})"
