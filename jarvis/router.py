"""Smart router (13.4.2): each message goes to the cheapest model that can do it.

In Mid, the everyday mode, every message used to go to the same model. Most
are small ("thanks", "what's 15% of 340", "translate this word") and a fast
small model answers them as well as a big one; a few (a bug, a proof, an
essay plan) need the big one. The router reads the message itself — no model
call, so it costs nothing and adds no wait — and sorts it into one of three
tiers:

    light     short, simple, small talk      the Low mode's fast model
    standard  everything else                Mid's own model
    heavy     code, maths, long reasoning    Groq gpt-oss-120b, then Gemini, then NVIDIA's 120B

Only the order changes: if the tier's model is busy, the usual chain answers,
so routing can never leave a message unanswered.

The savings readout (/router) is an estimate. Every provider in the chain is
on a free tier, so what you "save" is what the same tokens would have cost on
a paid model — GPT-5 mini's list price by default, set your own with
JARVIS_ROUTER_BASELINE=<$ per million input>,<$ per million output>.
"""

from __future__ import annotations

import re
import threading
import time

from . import modes
from .config import get_setting

SETTING = "JARVIS_ROUTER"
TIERS = ("light", "standard", "heavy")

# Words that mean a message needs the big model. Turkish alongside English:
# the same person asks in both.
_HEAVY = re.compile(
    r"```|\btraceback\b|\bexception\b|\bstack ?trace\b|\berror\b|\bbug\b|\bdebug\b|\brefactor\b|\bfunction\b"
    r"|\bdef |\bclass |\bimport |\bSELECT\b|\bregex\b|\balgorithm\b|\bcomplexity\b|\bpython\b|\bjavascript\b"
    r"|\btypescript\b|\bc\+\+|\bjava\b|\bsql\b|\bapi\b|\bcompile\b"
    r"|\bprove\b|\bproof\b|\bderivative\b|\bintegral\b|\bequation\b|\bsolve\b|\bcalculate\b|\bprobability\b"
    r"|\bstep by step\b|\banaly[sz]e\b|\banalysis\b|\bcompare\b|\bcomparison\b|\bpros and cons\b|\bin detail\b"
    r"|\bdetailed\b|\bessay\b|\bplan (a|my|the)\b|\bstrategy\b|\bexplain why\b|\bwhy does\b|\bhow does .{3,40} work\b"
    r"|\bhata\b|\bkod\b|\bfonksiyon\b|\bkanıtla\b|\btürev\b|\bintegral\b|\bdenklem\b|\bçöz\b|\bhesapla\b"
    r"|\badım adım\b|\banaliz\b|\bkarşılaştır\b|\bdetaylı\b|\bayrıntılı\b|\bkompozisyon\b|\bmakale\b|\bneden\b",
    re.IGNORECASE,
)
_MATHS = re.compile(r"\d\s*[\^*/=]\s*\d|\bx\s*[\^²]|√|∫|∑")
_LIGHT = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|thx|ok|okay|cool|nice|good (morning|night|evening)|bye|yo|sup"
    r"|merhaba|selam|teşekkürler|sağ ?ol|tamam|günaydın|iyi geceler|naber)\b",
    re.IGNORECASE,
)

LIGHT_MAX_CHARS = 90
HEAVY_MIN_CHARS = 700

# The heavy tier's models, best first. Overridable like a mode's targets:
#     JARVIS_ROUTER_HEAVY=groq:openai/gpt-oss-120b,nvidia:nvidia/nemotron-3-super-120b-a12b
HEAVY_DEFAULT = "groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash-lite,nvidia:nvidia/nemotron-3-super-120b-a12b"

# GPT-5 mini's list price, $ per million tokens (input, output).
BASELINE_DEFAULT = (0.25, 2.00)


def enabled() -> bool:
    return get_setting(SETTING, "on").strip().lower() not in {"off", "0", "false", "no"}


def applies(brain) -> bool:
    """Only Mid routes: every other mode is a choice the user made on purpose."""
    return enabled() and getattr(getattr(brain, "mode", None), "name", "") == modes.MID.name \
        and not getattr(brain, "persona_override", None)


def classify(text: str) -> str:
    """'light', 'standard' or 'heavy', from the message alone."""
    body = (text or "").strip()
    if not body:
        return "standard"
    if len(body) >= HEAVY_MIN_CHARS or _HEAVY.search(body) or _MATHS.search(body) or body.count("\n") >= 6:
        return "heavy"
    if _LIGHT.match(body) or (len(body) <= LIGHT_MAX_CHARS and "\n" not in body):
        return "light"
    return "standard"


def targets(tier: str) -> tuple[tuple[str, str], ...]:
    """The (provider, model) pairs to try first for a tier."""
    if tier == "light":
        return modes.targets_for(modes.LOW)
    if tier == "heavy":
        return modes.parse_targets(get_setting("JARVIS_ROUTER_HEAVY", HEAVY_DEFAULT))
    return ()  # standard: Mid's own model, which the mode tries anyway


def baseline() -> tuple[float, float]:
    raw = get_setting("JARVIS_ROUTER_BASELINE", "")
    try:
        first, second = (float(part) for part in raw.split(",", 1))
        if first >= 0 and second >= 0:
            return first, second
    except ValueError:
        pass
    return BASELINE_DEFAULT


# --- the readout --------------------------------------------------------------

_lock = threading.Lock()


def _store():
    from . import kit

    return kit.Store("router.json", {})


def record(tier: str, prompt_chars: int, reply_chars: int, seconds: float, answered_by: str = "") -> None:
    """Count one routed reply. Best effort: the readout must never break a chat."""
    try:
        with _lock:
            store = _store()
            data = store.load()
            row = data.setdefault(tier, {"count": 0, "in": 0, "out": 0, "seconds": 0.0})
            row["count"] += 1
            # About four characters to a token, in English and Turkish alike.
            row["in"] += max(1, prompt_chars // 4)
            row["out"] += max(1, reply_chars // 4)
            row["seconds"] = round(row["seconds"] + seconds, 2)
            if answered_by:
                row["last"] = answered_by
            data["since"] = data.get("since") or time.time()
            store.save(data)
    except Exception:
        pass


def stats() -> dict:
    try:
        return _store().load()
    except Exception:
        return {}


def reset() -> None:
    with _lock:
        _store().save({})


def readout() -> str:
    data = stats()
    rows = [(tier, data[tier]) for tier in TIERS if isinstance(data.get(tier), dict)]
    state = "on" if enabled() else "off"
    head = f"🧭 Smart router: {state} (it routes in Mid, the everyday mode)."
    if not rows:
        return head + "\nNothing routed yet. Ask a few things in Mid and come back."
    price_in, price_out = baseline()
    total = sum(r["count"] for _, r in rows)
    tokens_in = sum(r["in"] for _, r in rows)
    tokens_out = sum(r["out"] for _, r in rows)
    saved = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    lines = [head, f"{total} message(s) routed:"]
    names = {"light": "Light (fast small model)", "standard": "Standard (Mid's model)",
             "heavy": "Heavy (big model)"}
    for tier, row in rows:
        avg = row["seconds"] / row["count"] if row["count"] else 0
        share = 100 * row["count"] / total
        last = f", last answered by {row['last']}" if row.get("last") else ""
        lines.append(f"  {names[tier]:<26} {row['count']:>4}  ({share:.0f}%)  avg {avg:.1f}s{last}")
    lines.append(f"≈ {tokens_in + tokens_out:,} tokens on free tiers. At ${price_in:g}/${price_out:g} per million "
                 f"(a paid model's list price) that would have cost ≈ ${saved:.2f} — saved.")
    light = next((r for t, r in rows if t == "light"), None)
    if light and light["count"]:
        lines.append(f"{light['count']} simple message(s) skipped the big model entirely, which keeps its free "
                     "daily limit for the questions that need it.")
    lines.append("/router off · /router on · /router reset")
    return "\n".join(lines)
