"""Thinking modes — how hard JARVIS works on an answer.

A mode is three things: which model to reach for first, how much room the
answer gets, and an instruction describing how to think. The last is what
actually separates Low from Max — the same model told to be terse and told to
be exhaustive behaves very differently, and that works on every provider
rather than only on ones exposing a reasoning-effort knob.

Targets are *preferences*, never requirements. A mode names the models it
would like, and anything unavailable falls through to the normal provider
chain — which matters because providers retire models and revoke keys without
warning. A mode whose preferred model is gone still answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mode:
    name: str
    label: str
    blurb: str
    # Appended to the system prompt. This is the mode's actual character.
    style: str
    max_tokens: int
    temperature: float
    # Preferred (provider name, model id), tried in order before the chain.
    targets: tuple[tuple[str, str], ...] = ()
    # Seconds allowed for the first target specifically. Hyperdrive uses this
    # to give a very slow model a long leash before moving on.
    first_target_timeout: float | None = None
    # Seconds for ordinary requests in this mode.
    timeout: float = 120.0
    # Seconds allowed for each fallback once the preferred target is out.
    # Kept separate because Hyperdrive's long leash is meant for kimi alone —
    # applying 200s to every provider behind it turned one slow model into a
    # multi-minute wait for an answer the chain could have given in seconds.
    fallback_timeout: float = 90.0
    accent: str = "#00d4ff"


LOW = Mode(
    name="low",
    label="Low",
    blurb="Fast and brief. Good for quick questions.",
    style=(
        "Answer in as few words as the question honestly allows — often a "
        "sentence or two. State the conclusion first. Do not explain your "
        "reasoning, list alternatives, or add caveats unless the answer is "
        "wrong without them."
    ),
    max_tokens=512,
    temperature=0.3,
    timeout=60.0,
    accent="#4ade80",
)

MID = Mode(
    name="mid",
    label="Mid",
    blurb="Balanced. The everyday default.",
    style=(
        "Answer directly, then add only the context that changes what the "
        "user would do. Aim for a short paragraph or a few bullets. Mention a "
        "caveat only when ignoring it would cause a real problem."
    ),
    max_tokens=1536,
    temperature=0.7,
    accent="#00d4ff",
)

HIGH = Mode(
    name="high",
    label="High",
    blurb="Thinks it through and shows the reasoning.",
    style=(
        "Work the problem through before answering. Say what you considered "
        "and why you rejected it, name the trade-offs, and flag assumptions "
        "you had to make. Prefer being clear about uncertainty over sounding "
        "confident."
    ),
    max_tokens=3072,
    temperature=0.7,
    accent="#f59e0b",
)

MAX = Mode(
    name="max",
    label="Max",
    blurb="Exhaustive. Slow, thorough, considers edge cases.",
    style=(
        "Be thorough. Consider alternative approaches and say why the one you "
        "chose is better. Cover edge cases and failure modes. Where something "
        "could be wrong, say exactly what would have to be true for it to be "
        "wrong. Length is fine if every part earns its place — padding is not."
    ),
    max_tokens=6144,
    temperature=0.8,
    timeout=180.0,
    accent="#f472b6",
)

HYPERDRIVE = Mode(
    name="hyperdrive",
    label="Hyperdrive",
    blurb="Reaches for kimi-k3 first, waits 200s, then drops back to Max.",
    style=MAX.style,
    max_tokens=6144,
    temperature=0.8,
    # kimi-k3 is enormous and, on NVIDIA's free tier, frequently never
    # answers at all. It gets one long attempt and then we move on rather
    # than leaving the user staring at a spinner.
    targets=(("nvidia", "moonshotai/kimi-k3"),),
    first_target_timeout=200.0,
    timeout=200.0,
    accent="#a855f7",
)

ALL: tuple[Mode, ...] = (LOW, MID, HIGH, MAX, HYPERDRIVE)
BY_NAME = {m.name: m for m in ALL}
DEFAULT = MID


def get(name: str | None) -> Mode:
    """Look up a mode, falling back to the default."""
    return BY_NAME.get((name or "").strip().lower(), DEFAULT)


def next_mode(current: str) -> Mode:
    """The mode after this one, wrapping — for a click-to-cycle button."""
    names = [m.name for m in ALL]
    try:
        index = names.index(current)
    except ValueError:
        return DEFAULT
    return ALL[(index + 1) % len(ALL)]
