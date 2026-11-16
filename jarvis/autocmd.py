"""Commands without the slash (10.5.2).

intents.py already turns a few dozen fixed phrasings into commands ("pause
music", "make a poster for…"), but JARVIS has over 300 commands and nobody
says them the way a pattern expects. This is the step after the patterns:

1. The first word is a command name that isn't an ordinary word
   ("tripbudget rome 5 days", "kdv 1000"): run it, no model needed.
2. The message asks for something to be done ("plan a 5-day trip to Rome
   on 20,000 TL", "make me a worksheet on fractions"), or starts with a
   command's name: a short list of likely commands is picked locally, and a
   fast free model (Gemini 3.5 Flash-Lite, Groq as backup) chooses one of
   them, or none. None means it was conversation, and it goes to the chat.

The reply says which command ran ("↪ /tripbudget rome | 5"), so a wrong
guess is visible and the slash form is learnt along the way.

Only commands that can't do harm by mistake are chosen this way: nothing
that deletes, sends, installs, prints, changes the firewall or controls a
device. Those still need their slash. A message holding a key or password
(by redact.py's reckoning) never goes to the router; questions never do.
"""

from __future__ import annotations

import json
import re

from . import providers, registry

SETTING = "JARVIS_AUTO_COMMANDS"
TIMEOUT = 8.0
MAX_CANDIDATES = 12

# Whole groups that act on the world rather than make or look something up.
DENY_GROUPS = {"Automation", "Phone"}
DENY = {
    "shred", "decrypt", "encrypt", "firewall", "stripmeta", "avschedule", "avupdate", "defender", "cleanup",
    "rename", "autosort", "declutter", "winget", "startup", "pip", "vscode", "runcode", "buildexe", "branch",
    "github", "docker", "mcp", "whatsapp", "print", "mailmerge", "pdfsign", "errors", "persona", "handsfree",
    "inbox", "gcal", "dnd", "wallpaper", "darkmode", "awake", "unzip", "zip", "fileconvert", "pdfcompress",
    "pdfrotate", "pdfpages", "pdfnumber", "pdfwatermark", "exceledit", "imgs", "focusapps",
}

_PREFIX = re.compile(
    r"^(?:hey\s+)?(?:jarvis[,:]?\s+)?(?:please\s+|pls\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|"
    r"i\s+(?:want|need)\s+(?:you\s+to\s+)?|i'?d\s+like\s+(?:you\s+to\s+)?|lütfen\s+)*", re.I)

# A request to do something starts with one of these (English and Turkish).
VERBS = {
    "make", "create", "build", "generate", "write", "draft", "plan", "design", "draw", "convert", "calculate",
    "compute", "count", "check", "scan", "show", "list", "give", "track", "log", "add", "set", "start",
    "turn", "record", "summarize", "summarise", "translate", "rewrite", "grade", "mark", "compare", "find",
    "estimate", "split", "prepare", "format", "test", "quiz", "organize", "organise", "watch", "alert",
    "measure", "solve", "plot", "remove", "resize", "edit", "improve", "change", "analyse", "analyze",
    "review", "outline", "schedule", "brainstorm",
    "yap", "oluştur", "hazırla", "çevir", "hesapla", "göster", "bul", "yaz", "planla", "çiz", "özetle", "ekle",
    "başlat", "kontrol", "tasarla",
}
QUESTION = re.compile(r"^(?:what|why|how|who|when|where|which|whose|is|are|was|were|do|does|did|should|"
                      r"would|will|can\s+i|could\s+i|ne|neden|nasıl|kim|nerede|hangi)\b", re.I)
_WORD = re.compile(r"[a-zçğıöşü0-9]+", re.I)


def enabled() -> bool:
    from .config import get_setting

    return get_setting(SETTING, "on").lower() not in {"off", "no", "false", "0"}


def _clean(text: str) -> str:
    return _PREFIX.sub("", " ".join(text.split())).rstrip(" .!")


def _stem(word: str) -> str:
    word = word.lower()
    for ending in ("ing", "ies", "es", "ed", "s"):
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def allowed(tool: registry.Tool) -> bool:
    return tool.group not in DENY_GROUPS and tool.name not in DENY and not tool.chat


def _tools() -> dict[str, registry.Tool]:
    """Every name and alias that may be chosen, to its tool."""
    names: dict[str, registry.Tool] = {}
    for tool in registry.TOOLS.values():
        if allowed(tool):
            for name in tool.names or (tool.name,):
                names[name.lower()] = tool
    return names


def _is_word(word: str) -> bool:
    """Is this an ordinary English or Turkish word? Unknown counts as yes."""
    if any(ch.isdigit() for ch in word):
        return False
    try:
        from . import spelling

        return not spelling.check(word, "en-US")
    except Exception:
        return True


_ABOUT_LAST = re.compile(r"^\S+\s+(?:it|this|that|them|these|those|bunu|şunu|onu)\b", re.I)


def looks_like_task(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned or cleaned.startswith("/") or cleaned.endswith("?") or QUESTION.match(cleaned):
        return False
    words = cleaned.lower().split()
    # "make it shorter", "translate this": about the last answer, which only
    # the chat knows.
    if len(words) <= 5 and _ABOUT_LAST.match(cleaned):
        return False
    # Turkish puts the verb last: "çalışma planı hazırla".
    return words[0] in VERBS or words[-1] in VERBS or words[0] in _tools()


def direct(text: str) -> str | None:
    """'tripbudget rome 5 days' → '/tripbudget rome 5 days', with no model."""
    cleaned = _clean(text)
    first, _, rest = cleaned.partition(" ")
    tool = _tools().get(first.lower())
    if tool is None or _is_word(first):
        return None
    return f"/{tool.name} {rest}".rstrip()


def candidates(text: str, limit: int = MAX_CANDIDATES) -> list[registry.Tool]:
    """The commands most likely meant, by words shared with their names and help."""
    words = {_stem(w) for w in _WORD.findall(_clean(text)) if len(w) > 2} - {_stem(v) for v in VERBS}
    if not words:
        return []
    scored = []
    seen = set()
    for tool in _tools().values():
        if tool.name in seen:
            continue
        seen.add(tool.name)
        names = {_stem(n) for n in tool.names or (tool.name,)}
        about = {_stem(w) for w in _WORD.findall(" ".join((tool.title, tool.help, tool.keywords, tool.usage)))}
        score = 3 * len(words & names) + len(words & about)
        if score:
            scored.append((score, tool.name, tool))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [tool for _score, _name, tool in scored[:limit]]


PROMPT = """You map one request to a JARVIS command, or to none.

Commands (name — usage — what it does):
{menu}

Request: {request}

Reply with JSON only, no other text:
{{"command": "<name>", "args": "<the arguments, following the usage, in the request's own words and language>"}}
or {{"command": null}} when the request is a question, a conversation, or doesn't clearly fit one command."""


def _one(name: str, prompt: str) -> str:
    provider = providers.BY_NAME.get(name)
    if provider is None or not providers.has_key(provider):
        return ""
    client = providers.get_client(provider).with_options(timeout=TIMEOUT, max_retries=0)
    reply = client.chat.completions.create(
        model=providers.model_for(provider), max_completion_tokens=600, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return (reply.choices[0].message.content or "").strip()


def _ask_model(prompt: str) -> str:
    """Gemini Flash-Lite and Groq at once; the first useful answer wins.

    One after the other, a stalled free tier cost 8 seconds before the other
    was even asked. '' when neither answers in time.
    """
    import concurrent.futures as futures

    pool = futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="autocmd")
    jobs = [pool.submit(_one, name, prompt) for name in ("gemini", "groq")]
    try:
        for job in futures.as_completed(jobs, timeout=TIMEOUT + 1):
            try:
                text = job.result()
            except Exception:
                continue
            if "{" in text:
                return text
    except futures.TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return ""


def choose(text: str) -> str | None:
    """The command to run for a plain request, or None for the chat."""
    shortlist = candidates(text)
    if shortlist:
        menu = "\n".join(f"{t.name} — {t.usage} — {t.help}" for t in shortlist)
    else:
        # Nothing shares a word with it (often Turkish, against English help
        # text): the model gets every allowed command, briefly.
        shortlist = list({t.name: t for t in _tools().values()}.values())
        menu = "\n".join(f"{t.name} — {t.usage}" for t in shortlist)
    answer = _ask_model(PROMPT.format(menu=menu, request=_clean(text)))
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        return None
    try:
        picked = json.loads(match.group(0))
    except ValueError:
        return None
    name = str(picked.get("command") or "").strip().lstrip("/").lower()
    tool = next((t for t in shortlist if name in {n.lower() for n in (t.names or (t.name,))}), None)
    if tool is None:
        return None
    args = " ".join(str(picked.get("args") or "").split())
    return f"/{tool.name} {args}".rstrip()


def _has_secret(text: str) -> bool:
    from . import redact

    redactor = redact.Redactor()
    redactor.mask_messages([{"role": "user", "content": text}])
    return bool(redactor.total)


def route(text: str) -> str | None:
    """A slash command for this plain message, or None."""
    if not enabled() or not looks_like_task(text) or _has_secret(text):
        return None
    return direct(text) or choose(text)
