"""Thinking modes — how hard JARVIS works on an answer.

A mode is three things: which model to reach for first, how much room the
answer gets, and an instruction describing how to think.

Every tier names a different model, and that is deliberate. Until 3.1.1 only
Mid and Hyperdrive did, so Low, High and Max all fell to the top of the
provider chain and answered on the same model with a different prompt — the
tiers read as a real difference in the UI while being mostly cosmetic
underneath. The models below were chosen by measuring what these free tiers
actually serve, cheapest and fastest at the bottom, heaviest at the top.

The instruction still matters, and still works on providers that expose no
reasoning-effort knob. It is now half the story rather than all of it.

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
    # Seconds allowed for the first target specifically, and only the first:
    # a mode with several preferred models must not pay the long leash once
    # per model.
    first_target_timeout: float | None = None
    # Seconds for ordinary requests in this mode.
    timeout: float = 120.0
    # Seconds allowed for each fallback once the preferred target is out.
    # Kept separate because Hyperdrive's long leash is meant for kimi alone —
    # applying 200s to every provider behind it turned one slow model into a
    # multi-minute wait for an answer the chain could have given in seconds.
    fallback_timeout: float = 90.0
    # When set, the ordinary fallback chain is limited to these providers.
    # Hyperdrive uses it to stay on NVIDIA: falling through to Gemini or Groq
    # would quietly turn it into a different mode with the same name.
    only_providers: tuple[str, ...] = ()
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
    # Not a reasoning model, deliberately. gpt-oss-20b was the first choice
    # and had to be dropped: it spends its tokens thinking before it writes,
    # so at Low's 512-token budget it produced 2,276 characters of reasoning
    # and *zero* characters of answer. qwen answers in 1.2s with none of
    # that, which is what this tier is for.
    targets=(("groq", "qwen/qwen3.8-27b"),),
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
    # Mercury is a diffusion model and answers in about a second, which is
    # what you want from the tier you sit in all day. Still only a preference:
    # if the key is missing or the model is retired, the chain takes over.
    targets=(("inception", "mercury-2.5"),),
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
    # Measured at ~6s. Heavier than Mid's diffusion model and on a different
    # provider, so High is not just Mid with a longer prompt.
    targets=(("gemini", "gemini-3.6-flash"),),
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
    # 120B, ~10s. The heaviest model any of these free tiers will actually
    # serve — NVIDIA's larger ones accept the request and then never answer.
    targets=(("nvidia", "nvidia/nemotron-3-super-120b-a12b"),),
    timeout=180.0,
    accent="#f472b6",
)

HYPERDRIVE = Mode(
    name="hyperdrive",
    label="Hyperdrive",
    blurb="NVIDIA only: kimi-k3 first, then the 120B. Never falls back elsewhere.",
    style=MAX.style,
    max_tokens=6144,
    temperature=0.8,
    # The 200-second leash was written when kimi-k3 was expected to answer
    # eventually. It does not: measured at 40s, 60s and 200s, on three
    # separate occasions, it never replied once — and deepseek-v4.1-flash and
    # mistral-nemotron behave the same way, so this is NVIDIA's free tier
    # rather than one bad model. Waiting longer buys nothing.
    #
    # So Hyperdrive still reaches for the giant first, but on a short leash,
    # and Brain remembers a target that timed out for the rest of the
    # session. In practice: up to 30 seconds once, then never again.
    targets=(
        ("nvidia", "moonshotai/kimi-k3"),
        ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
    ),
    first_target_timeout=30.0,
    timeout=180.0,
    fallback_timeout=60.0,
    only_providers=("nvidia",),
    accent="#a855f7",
)

SECURITY = Mode(
    name="security",
    label="Security",
    blurb="Reads everything as an attacker would. Thorough and suspicious.",
    style=(
        "Answer as a security reviewer. Assume every input is hostile and every "
        "caller is untrusted until the code proves otherwise.\n"
        "- Name the specific weakness, not a category: say which line, what an "
        "attacker sends, and what they get.\n"
        "- Rank by what an attacker would actually reach first, not by how "
        "interesting the bug is.\n"
        "- Give the concrete fix, as code, not 'validate input'.\n"
        "- Say plainly when something is fine. Inventing findings to look "
        "thorough wastes the reader's time and trains them to ignore you.\n"
        "- Consider what the code does not do: missing authentication, missing "
        "limits, errors that leak internals, secrets in logs."
    ),
    max_tokens=6144,
    temperature=0.4,
    # The larger of Groq's two, and fast with it. Reviewing code wants
    # breadth rather than brevity, and this is the biggest model that
    # answers in seconds rather than tens of them.
    targets=(("groq", "openai/gpt-oss-120b"),),
    timeout=180.0,
    accent="#ef4444",
)

ALL: tuple[Mode, ...] = (LOW, MID, HIGH, MAX, HYPERDRIVE, SECURITY)
BY_NAME = {m.name: m for m in ALL}
DEFAULT = MID


def get(name: str | None) -> Mode:
    """Look up a mode, falling back to the default."""
    return BY_NAME.get((name or "").strip().lower(), DEFAULT)


def env_key(mode: Mode) -> str:
    """The .env setting that overrides this mode's model."""
    return f"JARVIS_MODE_{mode.name.upper()}"


def targets_for(mode: Mode) -> tuple[tuple[str, str], ...]:
    """This mode's models, with any override from .env applied.

    Providers retire models without warning — this project has lost three
    that way already — and until now the only fix was a new release. A line
    like

        JARVIS_MODE_HIGH=groq:qwen/qwen3.8-27b

    repoints a tier without touching the code, and the Settings window writes
    it for you. A malformed value is ignored rather than breaking the mode.
    """
    from .config import get_setting

    raw = get_setting(env_key(mode), "").strip()
    if not raw:
        return mode.targets

    picked: list[tuple[str, str]] = []
    for part in raw.split(","):
        provider, _, model = part.strip().partition(":")
        provider, model = provider.strip().lower(), model.strip()
        if provider and model:
            picked.append((provider, model))
    return tuple(picked) or mode.targets


def next_mode(current: str) -> Mode:
    """The mode after this one, wrapping — for a click-to-cycle button."""
    names = [m.name for m in ALL]
    try:
        index = names.index(current)
    except ValueError:
        return DEFAULT
    return ALL[(index + 1) % len(ALL)]
