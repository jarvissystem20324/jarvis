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

    # --- 7.0: exact answers ---
    from . import calc

    if calc.looks_like_math(t):
        return f"/calc {t}", True
    m = re.fullmatch(r"(?:what\s+time\s+is\s+it|what'?s\s+the\s+time|time|saat\s+kaç)\s+(?:now\s+)?in\s+(.+)", t, re.I)
    if m:
        return f"/clock {m.group(1)}", True
    m = re.fullmatch(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:in\s+)?([a-z][\w .]+?)\s+(?:in|to)\s+([a-z][\w .]+?)(?:\s+time)?", t, re.I)
    if m and re.search(r":|am$|pm$", m.group(1).lower().replace(" ", "")):
        return f"/clock {t}", True

    # --- 7.0: images, files, the day ---
    if re.fullmatch(r"(?:what'?s|what\s+is)\s+(?:in|on)\s+(?:this|the|that)\s+(?:image|picture|photo|pic|screenshot)"
                    r"|describe\s+(?:this|the|that)\s+(?:image|picture|photo|pic|screenshot)"
                    r"|what\s+(?:do\s+you\s+see|does\s+(?:this|the)\s+(?:image|picture|photo)\s+show)", low):
        return "/look", True
    m = re.fullmatch(r"(?:tidy|clean)\s+up\s+(?:my\s+)?downloads(?:\s+folder)?|(?:tidy|organi[sz]e|sort)\s+(?:my\s+)?downloads(?:\s+folder)?", low)
    if m:
        return "/tidy", False
    if low in {"good morning", "morning briefing", "brief me", "daily briefing", "günaydın", "briefing"}:
        return "/briefing", False
    m = re.fullmatch(r"(?:make|create|generate)\s+(?:a\s+)?qr(?:\s+code)?\s+(?:for|of|with)\s+(.+)", t, re.I)
    if m:
        return f"/qr {m.group(1)}", False
    m = re.fullmatch(r"(start|stop|pause|reset|lap)\s+(?:the\s+|a\s+)?stopwatch", low)
    if m:
        return f"/stopwatch {m.group(1)}", False
    if re.fullmatch(r"(?:copy|grab|read|get)\s+(?:the\s+)?text\s+(?:from|on|off)\s+(?:the\s+|my\s+)?screen", low):
        return "/ocr", False
    if re.fullmatch(r"(?:generate|make|create|give\s+me)\s+(?:a\s+|me\s+a\s+)?(?:strong\s+|new\s+|random\s+)?password", low):
        return "/password", False
    if low in {"lock", "lock jarvis", "lock the app", "lock yourself"}:
        return "/lock", False

    # --- 7.1: study, video, money, the PC ---
    m = re.fullmatch(r"(?:quiz|test)\s+me(?:\s+(?:on|about)\s+(.+))?", t, re.I)
    if m:
        return f"/quiz {m.group(1) or ''}".rstrip(), False
    m = re.fullmatch(r"(?:make|create|give\s+me)\s+(?:some\s+)?(\d+\s+)?flash\s?cards\s+(?:for|on|about|from)\s+(.+)", t, re.I)
    if m:
        return f"/flashcards {m.group(1) or ''}{m.group(2)}", False
    from . import youtube

    link = re.search(r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/\S+", t)
    if link and youtube.video_id(link.group(0)):
        rest = (t[:link.start()] + " " + t[link.end():]).strip(" :,-")
        if re.fullmatch(r"(?:(?:please\s+)?(?:summari[sz]e|sum\s+up|tl;?dr|watch|özetle)(?:\s+(?:this|the|that))?(?:\s+(?:video|one))?(?:\s+for\s+me)?)?", rest, re.I):
            rest = ""
        return f"/yt {link.group(0)} {rest}".rstrip(), False
    if re.fullmatch(r"(?:start\s+)?record(?:ing)?\s+(?:this|the|my)\s+(?:lecture|meeting|class|lesson|call|talk)|start\s+recording|dersi\s+kaydet", low):
        return "/record start", False
    if re.fullmatch(r"stop\s+(?:the\s+)?recording|(?:finish|end)\s+(?:the\s+)?recording", low):
        return "/record stop", False
    m = re.fullmatch(r"(?:i\s+)?(?:just\s+)?(?:spent|paid)\s+(.*\d.*)", t, re.I)
    if m and not re.search(r"\d\s*(?:hours?|hrs?|minutes?|mins?|days?|weeks?|months?|years?|saat|dakika|gün)\b", low):
        return f"/spent {m.group(1)}", False
    m = re.fullmatch(r"how\s+much\s+(?:did|have)\s+i\s+spen[td](?:\s+(today|this\s+week|this\s+month|last\s+month|this\s+year))?(?:\s+so\s+far)?", low)
    if m:
        return f"/spent {m.group(1) or 'month'}", False
    if low in {"my spending", "show my spending", "spending", "my expenses", "expenses"}:
        return "/spent month", False
    if re.fullmatch(r"(?:how\s+fast\s+is\s+(?:my|the)\s+(?:internet|wi-?fi|connection)|(?:run\s+an?\s+|do\s+an?\s+)?(?:internet\s+)?speed\s*test"
                    r"|(?:check|test)\s+(?:my\s+|the\s+)?(?:internet|wi-?fi|connection)(?:\s+speed)?|internet\s+speed|internet\s+hızı)", low):
        return "/speedtest", False
    pc_word = r"(?:the\s+|my\s+|this\s+)?(?:pc|computer|laptop|bilgisayar(?:ı)?)"
    m = re.fullmatch(rf"(shut\s*down|turn\s+off|power\s+off|restart|reboot)\s+{pc_word}(\s+(?:in|at)\s+.+)?", low)
    if m:
        action = "restart" if m.group(1) in {"restart", "reboot"} else "shutdown"
        return f"/power {action}{m.group(2) or ''}", False
    m = re.fullmatch(rf"(?:put\s+{pc_word}\s+to\s+sleep|sleep\s+{pc_word})(\s+(?:in|at)\s+.+)?", low)
    if m:
        return f"/power sleep{m.group(1) or ''}", False
    if re.fullmatch(rf"lock\s+(?:{pc_word}|(?:the\s+|my\s+)?(?:screen|windows|workstation))", low):
        return "/power lock", False
    if re.fullmatch(r"(?:cancel|abort|stop)\s+(?:the\s+)?(?:shutdown|shut\s+down|restart|reboot|sleep)", low):
        return "/power cancel", False

    # --- opening apps and folders (last: the loosest) ---
    m = re.fullmatch(r"(?:open|launch|start)\s+(?:up\s+)?(.+)", t, re.I)
    if m and len(m.group(1)) <= 60:
        return f"/app {m.group(1)}", True
    return None
