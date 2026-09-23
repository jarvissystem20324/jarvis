"""Usage statistics, read back out of the audit log.

No new tracking. Every line this reads was already being written by
`security.audit` — which provider answered, how long it took, which mode was
in use — so turning that into a picture costs nothing and adds no new record
of what you do. Privacy mode still stops the writing, and this then simply
has less to show.

What it is actually for: the free tiers here fail in ways that are invisible
from inside a conversation. A provider that has quietly become the one
answering everything, a mode that is always three seconds slower than it used
to be, a key that stopped working on Tuesday — all of that is in the log
already and none of it is visible until someone counts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from . import security


def _parse(entry: dict) -> tuple[str, str, float, str] | None:
    """Pull (provider, model, seconds, mode) out of an 'answered' line."""
    if entry.get("action") != "answered":
        return None
    detail = str(entry.get("detail") or "")
    outcome = str(entry.get("outcome") or "")
    if " / " not in detail:
        return None
    provider, _, model = detail.partition(" / ")

    seconds, mode = 0.0, ""
    for part in outcome.split(","):
        part = part.strip()
        if part.endswith("s"):
            try:
                seconds = float(part[:-1])
            except ValueError:
                pass
        elif part:
            mode = part
    return provider.strip(), model.strip(), seconds, mode


def report(limit: int = 4000) -> str:
    """A readable summary of what JARVIS has been doing."""
    entries = security.audit.read(limit=limit)
    if not entries:
        if security.privacy.on:
            return (
                "Privacy mode is on, so nothing is being recorded and there "
                "is nothing to summarise."
            )
        return f"Nothing recorded yet. The log lives at {security.audit.path()}"

    answers = [p for p in (_parse(e) for e in entries) if p]
    by_provider: dict[str, list[float]] = defaultdict(list)
    by_mode: dict[str, list[float]] = defaultdict(list)
    by_model: dict[str, list[float]] = defaultdict(list)
    for provider, model, seconds, mode in answers:
        by_provider[provider].append(seconds)
        by_model[model].append(seconds)
        if mode:
            by_mode[mode].append(seconds)

    actions: dict[str, int] = defaultdict(int)
    denied = 0
    for entry in entries:
        action = str(entry.get("action") or "?")
        if action in {"answered", "permission"}:
            if action == "permission" and str(entry.get("outcome", "")).startswith("DENIED"):
                denied += 1
            continue
        actions[action] += 1

    first = str(entries[0].get("at") or "")[:16].replace("T", " ")
    last = str(entries[-1].get("at") or "")[:16].replace("T", " ")

    lines = [
        f"Usage — {len(entries)} recorded actions, {first} to {last}",
        "",
        f"{len(answers)} answers from {len(by_provider)} provider(s):",
    ]
    if answers:
        width = max(len(p) for p in by_provider)
        for provider, times in sorted(by_provider.items(), key=lambda kv: -len(kv[1])):
            share = 100 * len(times) / len(answers)
            average = sum(times) / len(times) if times else 0
            bar = "#" * max(1, round(share / 5))
            lines.append(
                f"  {provider:<{width}}  {len(times):>4}  {share:5.1f}%  "
                f"avg {average:5.1f}s  {bar}"
            )

        lines.append("")
        lines.append("By mode:")
        for mode, times in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
            average = sum(times) / len(times) if times else 0
            lines.append(f"  {mode:<12} {len(times):>4} answers   avg {average:5.1f}s")

        slowest = sorted(by_model.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])))[:3]
        if slowest:
            lines.append("")
            lines.append("Slowest models:")
            for model, times in slowest:
                lines.append(f"  {model[:40]:<40} avg {sum(times) / len(times):5.1f}s")

    if actions:
        lines.append("")
        lines.append("Other actions:")
        for action, count in sorted(actions.items(), key=lambda kv: -kv[1])[:10]:
            lines.append(f"  {action:<20} {count}")
    if denied:
        lines.append("")
        lines.append(f"{denied} permission request(s) denied.")

    lines.append("")
    lines.append(
        "Counted from the audit log — nothing extra is recorded to produce this."
    )
    return "\n".join(lines)
