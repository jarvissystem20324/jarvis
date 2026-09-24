"""Plain-language requests that are really commands.

"pause music", "volume 30", "open spotify", "remind me in 20 minutes to…",
"timer 10 minutes", "weather tomorrow in Istanbul", "find my CV pdf",
"why is my PC slow" — each of these has an exact, local answer, and sending
it to a language model would be slower, cost a request, and could only
*describe* pausing the music rather than pause it.

This only recognises; it never acts. route() turns a sentence into the
equivalent slash command, and says whether it is sure. When it is not sure
("open the pod bay doors") the command gets to try, and if it finds nothing
the sentence goes to the AI as normal.

Deliberately conservative: every pattern is anchored to the whole message,
so "what is the volume of a sphere" and "find the derivative of x²" are
never mistaken for commands.
"""

from __future__ import annotations

import re

from .pc import KINDS

_PREFIX = re.compile(r"^(?:hey\s+)?(?:jarvis[,:]?\s+)?(?:please\s+|can you\s+|could you\s+)?", re.I)

MEDIA = {
    "pause": "pause", "play": "play", "resume": "play", "unpause": "play",
    "next": "next", "skip": "next", "previous": "previous", "prev": "previous",
    "back": "previous", "stop": "stop", "mute": "mute", "unmute": "mute",
}


def _clean(text: str) -> str:
    text = " ".join(text.strip().split())
    text = _PREFIX.sub("", text)
    return text.rstrip(" .!?")


def route(text: str) -> tuple[str, bool] | None:
    """(slash command, fall back to chat if it finds nothing) or None."""
    t = _clean(text)
    low = t.lower()
    if not low or low.startswith("/"):
        return None

    # --- media and volume ---
    m = re.fullmatch(
        r"(pause|play|resume|unpause|stop|next|skip|previous|prev|back)"
        r"(?:\s+(?:the\s+)?(?:music|song|track|video|media|spotify|youtube|it))?", low)
    if m and not (m.group(1) in {"stop", "back"} and low == m.group(1)):
        return f"/media {MEDIA[m.group(1)]}", False
    if re.fullmatch(r"(?:next|skip)(?:\s+(?:this\s+)?(?:song|track))|(?:previous|last)\s+(?:song|track)", low):
        return f"/media {'previous' if low.startswith(('previous', 'last')) else 'next'}", False
    if low in {"mute", "unmute", "mute it", "unmute it", "mute the sound", "sesi kapat"}:
        return "/media mute", False
    m = re.fullmatch(r"(?:set\s+)?(?:the\s+)?(?:volume|ses)(?:\s+(?:to|at|level))?\s+(\d{1,3})\s*(?:%|percent)?", low) \
        or re.fullmatch(r"(?:turn|set)\s+(?:the\s+)?volume\s+to\s+(\d{1,3})\s*(?:%|percent)?", low)
    if m and int(m.group(1)) <= 100:
        return f"/volume {int(m.group(1))}", False
    if re.fullmatch(r"(?:turn\s+(?:it|the\s+volume|the\s+music)\s+up|volume\s+up|louder|turn\s+up\s+the\s+volume)", low):
        return "/volume up", False
    if re.fullmatch(r"(?:turn\s+(?:it|the\s+volume|the\s+music)\s+down|volume\s+down|quieter|turn\s+down\s+the\s+volume)", low):
        return "/volume down", False

    # --- reminders, timers, alarms ---
    # "remind me what we said" is a question, not a reminder: /remind hands
    # anything without a time back to the conversation.
    m = re.match(r"^remind\s+me\s+(.+)$", t, re.I)
    if m:
        return f"/remind {m.group(1)}", True
    m = re.fullmatch(r"(?:set\s+(?:a\s+|an\s+)?)?timer\s+(?:for\s+)?(.+)", t, re.I) \
        or re.fullmatch(r"(?:set\s+)?(?:a\s+)?(\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|dakika|dk)(?:\s+.+)?)\s+timer", t, re.I)
    if m:
        return f"/timer {m.group(1)}", False
    m = re.fullmatch(r"(?:set\s+(?:an\s+|the\s+)?)?alarm\s+(?:for\s+|at\s+)?(.+)", t, re.I) \
        or re.fullmatch(r"wake\s+me(?:\s+up)?\s+(?:at\s+)?(.+)", t, re.I)
    if m:
        return f"/alarm {m.group(1)}", False

    # --- weather ---
    if re.match(r"^(?:what'?s|what\s+is|how'?s|how\s+is)?\s*(?:the\s+)?(?:weather|forecast)\b", low) \
            or re.match(r"^will\s+it\s+(?:rain|snow)\b", low) or low.startswith("hava durumu"):
        return f"/weather {t}", True

    # --- notes ---
    # Only explicit forms. "Note that the API changed…" is usually said to
    # the AI about code, not a note to keep.
    m = re.fullmatch(r"(?:take\s+a\s+note|make\s+a\s+note|jot\s+down|not\s+al)[:,]?\s+(.+)", t, re.I) \
        or re.fullmatch(r"note:\s*(.+)", t, re.I)
    if m:
        return f"/note {m.group(1)}", False

    # --- PC status ---
    if re.fullmatch(r"why\s+is\s+(?:my\s+|the\s+|this\s+)?(?:pc|computer|laptop|system)\s+(?:so\s+|running\s+)?slow", low) \
            or re.fullmatch(r"(?:pc|computer|system)\s+(?:status|health|stats)", low) \
            or re.fullmatch(r"what'?s\s+(?:slowing\s+(?:down\s+)?my\s+(?:pc|computer)|using\s+(?:all\s+)?my\s+(?:memory|ram|cpu))(?:\s+down)?", low):
        return "/pc why", False

    # --- files ---
    m = re.fullmatch(r"(open|show)\s+(?:file\s+|result\s+|number\s+)?#?(\d{1,2})", low)
    if m:
        return f"/locate {'open' if m.group(1) == 'open' else 'show'} {m.group(2)}", False
    m = re.fullmatch(r"(?:find|locate|search\s+for|where\s+is|where'?s|where\s+are)\s+(.+)", t, re.I)
    if m:
        what = m.group(1).lower()
        words = set(re.findall(r"[a-z]+", what))
        if what.startswith("my ") or words & {"file", "files", "folder", "document"} or words & set(KINDS):
            return f"/locate {m.group(1)}", False

    # --- image tools ---
    # "make it shorter" is about the last answer; only a request naming an
    # image operation is taken as one.
    if re.match(r"^(?:make|resize|convert|compress|crop|rotate|flip|mirror|shrink|turn|save)\s+"
                r"(?:this|it|that|the\s+(?:image|photo|picture|pic))\b", low) and re.search(
                r"\d+\s*(?:px|kb|%)|\b(?:jpe?g|png|webp|gif|bmp|crop|square|rotate|compress|"
                r"resize|grayscale|greyscale|black and white|wide|tall|flip|mirror|pixels?)\b", low):
        return f"/img {t}", True

    # --- reading aloud ---
    if re.fullmatch(r"read\s+(?:that|it|this|the\s+(?:last\s+)?(?:answer|reply))\s+(?:out\s+loud|aloud|to\s+me)", low):
        return "/readaloud last", False
    m = re.fullmatch(r"read\s+(.+?)\s+(?:out\s+loud|aloud|to\s+me)", t, re.I)
    if m:
        return f"/readaloud {m.group(1)}", True

    # --- opening apps and folders (last: the loosest) ---
    m = re.fullmatch(r"(?:open|launch|start)\s+(?:up\s+)?(.+)", t, re.I)
    if m and len(m.group(1)) <= 60:
        return f"/app {m.group(1)}", True
    return None
