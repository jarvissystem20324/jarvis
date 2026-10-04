"""Every command JARVIS has, as one list the window can show (10.0).

Commands from 8.0 on describe themselves through registry.command. The ones
before that were dispatched from hand-written tables in assistant.py,
everyday.py, extras.py, toolkit.py and tools.py, so they are described here
instead — and addons describe their own commands when they load.

The Tools page, the Ctrl+K palette and the chips under the chat box all read
from tools(); none of them keeps a list of its own, which is what lets a new
command appear in all three just by being registered.
"""

from __future__ import annotations

import re
import time

from . import kit, registry
from .registry import Tool, field

# Group → (icon, short blurb) for the Tools page.
GROUP_ICONS = {
    "Make and write": "✍", "Design": "🖌", "Documents": "📄", "Study": "🎓", "Everyday": "☀",
    "Live info": "📡", "PC and files": "🖥", "Security": "🛡", "Coding": "⌨", "Automation": "⚙",
    "Media": "🎬", "Music and games": "🎮", "Health and money": "💚", "Travel": "🧭", "Türkiye": "🇹🇷",
    "Phone": "📱", "Productivity": "✅", "Voice, connections and fun": "🎧", "Chat and AI": "💬",
}

# (names, group, usage, help, icon, chat?) for the commands older than the registry.
_LEGACY = [
    ("help", "Chat and AI", "/help", "every command, grouped", "❓", False),
    ("clear", "Chat and AI", "/clear", "forget this conversation", "🗑", True),
    ("export", "Chat and AI", "/export [html|pdf]", "save the conversation as Markdown, HTML or PDF", "↧", True),
    ("retry", "Chat and AI", "/retry [low|mid|high|max]", "ask the last question again", "↻", True),
    ("edit", "Chat and AI", "/edit", "put your last question back in the box", "✎", True),
    ("chat chats", "Chat and AI", "/chat new|<name>", "start, switch or list conversations", "💬", True),
    ("recall", "Chat and AI", "/recall <words>", "find something said in an earlier chat", "🔎", False),
    ("instructions", "Chat and AI", "/instructions <standing rules>", "rules this chat always follows", "📜", True),
    ("pin", "Chat and AI", "/pin", "pin the last answer", "📌", True),
    ("pins", "Chat and AI", "/pins", "everything you pinned", "📌", False),
    ("suggest", "Chat and AI", "/suggest on|off", "follow-up suggestions after answers", "💡", False),
    ("mode", "Chat and AI", "/mode low|mid|high|max|hyperdrive|security", "how hard JARVIS thinks", "⚡", False),
    ("code", "Coding", "/code", "engineer persona on or off", "⌨", True),
    ("image", "Make and write", "/image <prompt>", "generate a picture", "🎨", False),
    ("vary", "Make and write", "/vary [n]", "variations of the last picture", "🎨", False),
    ("compare", "Chat and AI", "/compare <question>", "several models answer side by side", "⚖", False),
    ("lang", "Chat and AI", "/lang [en|tr|…]", "the language JARVIS answers in", "🌐", False),
    ("voice", "Voice, connections and fun", "/voice", "spoken answers on or off", "🔊", False),
    ("addons", "Chat and AI", "/addons", "what the addons add", "🧩", False),
    ("stats", "Chat and AI", "/stats", "how much you have used each AI", "📊", False),
    ("health", "Chat and AI", "/health", "check every AI provider and key", "🩺", False),
    ("bench", "Chat and AI", "/bench", "speed-test the providers", "⏱", False),
    ("mini", "Chat and AI", "/mini", "a small window that stays on top", "▣", False),
    ("zoom", "Chat and AI", "/zoom in|out", "chat text size", "🔍", False),
    ("memory", "Chat and AI", "/memory", "edit what JARVIS remembers", "🧠", False),
    ("lock", "Security", "/lock [set|off]", "PIN lock for JARVIS", "🔒", True),
    ("password", "Security", "/password [length]", "a strong password, straight to the clipboard", "🔑", False),
    ("privacy", "Security", "/privacy", "privacy mode: nothing recorded", "🙈", False),
    ("redact", "Security", "/redact <text|file>", "hide names, numbers and secrets in text", "⬛", False),
    ("security", "Security", "/security", "JARVIS's own security settings", "🛡", False),
    ("audit", "Security", "/audit [n]", "what JARVIS has done, step by step", "📋", False),
    ("scan", "Security", "/scan [folder]", "look for leaked keys and secrets in files", "🔍", False),
    ("sandbox", "Security", "/sandbox <file>", "run a script in a locked-down sandbox", "📦", False),
    ("autoweb", "Live info", "/autoweb <what to do on a site>", "JARVIS works a web page for you", "🕸", True),
    ("agent", "Coding", "/agent <what you want done>", "plan a coding job, approve it, it does it", "🤖", True),
    ("fix", "Coding", "/fix [error]", "fix the last error in your project", "🩹", True),
    ("trace", "Coding", "/trace <error or log>", "explain a stack trace and point at the line", "🧵", False),
    ("testgen", "Coding", "/testgen <file>", "write tests for a file", "🧪", True),
    ("index", "Coding", "/index", "index the open project for questions", "🗂", False),
    ("where", "Coding", "/where <thing>", "where something is in the project", "📍", False),
    ("git", "Coding", "/git <question>", "ask about the repository", "🌿", False),
    ("commit", "Coding", "/commit", "a commit message for the staged changes", "✔", True),
    ("review", "Coding", "/review", "review the uncommitted changes", "👀", False),
    ("pr", "Coding", "/pr", "a pull request description", "🔀", False),
    ("explain", "Coding", "/explain <file|name>", "explain code", "📖", False),
    ("todo", "Coding", "/todo", "TODOs in the project", "☑", False),
    ("changes", "Coding", "/changes", "what the agent changed", "📝", False),
    ("revert", "Coding", "/revert <file>", "undo the agent's change to a file", "↩", True),
    ("release", "Coding", "/release [version]", "a release checklist and notes", "🚀", False),
    ("docs", "Documents", "/docs <folder>", "ask questions about a folder of documents", "📚", False),
    ("run", "PC and files", "/run <command>", "run a safe shell command (asks first)", "▶", True),
    ("open", "Live info", "/open <url>", "open a web page", "🌍", False),
    ("search", "Live info", "/search <words>", "search the web", "🔎", False),
    ("web", "Live info", "/web <question>", "answer from a live web search", "🌐", False),
    ("time", "Everyday", "/time", "the time and date", "🕒", False),
    ("date", "Everyday", "/date", "today's date", "📅", False),
    ("system", "PC and files", "/system", "system information", "🖥", False),
    ("media", "Everyday", "/media play|pause|next|previous", "control music and video", "⏯", False),
    ("volume", "Everyday", "/volume <0-100|up|down|mute>", "PC volume", "🔊", False),
    ("app", "PC and files", "/app <name>", "open an app or folder", "🚀", False),
    ("locate", "PC and files", "/locate <what>", "find your files by description", "🔎", False),
    ("pc", "PC and files", "/pc", "why is my PC slow: CPU, memory, disk", "🖥", False),
    ("remind", "Everyday", "/remind <when> <what>", "a reminder", "⏰", False),
    ("reminders", "Everyday", "/reminders", "upcoming reminders", "⏰", False),
    ("timer", "Everyday", "/timer <minutes> [label]", "a countdown timer", "⏲", False),
    ("alarm", "Everyday", "/alarm <time> [label]", "an alarm", "⏰", False),
    ("timers", "Everyday", "/timers", "running timers and alarms", "⏲", False),
    ("weather", "Everyday", "/weather [place] [tomorrow]", "the forecast, no key needed", "⛅", False),
    ("task tasks", "Automation", "/task add <name> <minutes> <command> | list | remove <name>",
     "run a command every few minutes while JARVIS is open", "⏱", False),
    ("note", "Productivity", "/note <text>", "a quick note", "🗒", False),
    ("notes", "Productivity", "/notes [search]", "your notes", "🗒", False),
    ("t", "Make and write", "/t <template> <text>", "prompt templates", "🧾", False),
    ("translate", "Make and write", "/translate <language>|off", "live translation of everything said", "🌐", True),
    ("readaloud", "Voice, connections and fun", "/readaloud <file|url>", "read a document out loud", "🗣", False),
    ("makedoc", "Documents", "/makedoc <what>", "a Word document and PDF", "📄", False),
    ("docx", "Documents", "/docx <what>", "a Word document", "📄", False),
    ("pdf", "Documents", "/pdf <what>", "a PDF document", "📕", False),
    ("data", "Documents", "/data <file.csv|xlsx> | <question>", "exact answers and charts from a sheet", "📊", False),
    ("img", "Media", "/img <what to do to the last image>", "resize, crop, convert the last picture", "🖼", False),
    ("calc convert", "Everyday", "/calc <sum or conversion>", "exact maths and unit conversion", "🧮", False),
    ("clock", "Everyday", "/clock <city> [time]", "time in another city", "🌍", False),
    ("clip", "Make and write", "/clip explain|summarize|translate <lang>|fix|reply", "work on your clipboard", "📋", False),
    ("ocr", "PC and files", "/ocr [image|screen]", "copy text from a picture or the screen", "🔤", False),
    ("briefing", "Everyday", "/briefing [at 8:00|off]", "weather, today's reminders, headlines", "🌅", False),
    ("tidy", "PC and files", "/tidy [folder|go|undo]", "tidy a folder: plan first, then go", "🧹", False),
    ("qr", "Make and write", "/qr <text or link>", "a QR code", "▦", False),
    ("stopwatch", "Everyday", "/stopwatch start|stop|lap|reset", "a stopwatch", "⏱", False),
    ("look", "Chat and AI", "/look [question]", "ask about the last picture", "👁", False),
    ("quiz", "Study", "/quiz <topic|file>", "a quiz; answer A to D", "❓", True),
    ("flashcards", "Study", "/flashcards <topic|file>", "flashcards for Anki or Quizlet", "🃏", False),
    ("yt youtube", "Study", "/yt <YouTube link> [question]", "summary with timestamps", "▶", False),
    ("record", "Study", "/record [stop|status|cancel]", "record a lecture, then notes", "🎙", False),
    ("spent spending", "Health and money", "/spent <amount> <what> | month | export", "track what you spend", "💸", False),
    ("speedtest", "PC and files", "/speedtest", "internet speed", "🚀", False),
    ("power", "PC and files", "/power shutdown|restart|sleep|lock [in 30 min]|cancel", "shut down, restart, sleep", "⏻", True),
]

# The window answers a few itself; they still belong on the Tools page.
_UI_ONLY = {"find": ("Chat and AI", "/find <words>", "find text in this chat", "⌕"),
            "copy": ("Chat and AI", "/copy [code]", "copy the last answer", "⧉"),
            "keys": ("Chat and AI", "/keys", "keyboard shortcuts", "⌨"),
            "setup": ("Chat and AI", "/setup", "how to set up keys and providers", "🔧"),
            "tour": ("Chat and AI", "/tour", "the welcome tour", "🧭")}

# Friendly names for the tiles of commands that were named for typing.
_TITLES = """20q=Twenty questions|2fa=2FA codes|addons=Addons|agent=Coding agent|air=Air quality|alarm=Alarm|
alert=Price alert|app=Open an app|audit=Activity log|autoweb=Web autopilot|b64=Base64|bench=Speed-test AIs|
brand=Brand kit|briefing=Morning briefing|cal=Calendar|calc=Calculator|camcheck=Camera and mic check|
cards=Flashcard review|changes=Agent changes|chapters=Book chapters|chat=Conversations|checklink=Link checker|
cite=Citation|cleanup=Disk clean-up|clear=Clear chat|clip=Clipboard helper|clock=World time|code=Code mode|
commit=Commit message|compare=Compare AIs|comparison=Comparison table|copy=Copy last answer|coverletter=Cover letter|
critique=Design critique|crypto=Crypto prices|cv=CV maker|darkmode=Windows dark mode|data=Data from a sheet|
date=Today's date|decrypt=Decrypt a file|define=Dictionary|design=Design anything|diagram=Diagram|dilekce=Dilekçe|
dnd=Do not disturb|docker=Docker|docs=Ask a folder of documents|docstrings=Add docstrings|docx=Word document|
done=Tick off a task|edit=Edit last question|email=Email writer|encrypt=Encrypt a file|envcheck=.env check|
every=Repeating reminder|expand=Text expander|explain=Explain code|export=Export chat|familytree=Family tree|
fileconvert=Convert a file|find=Find in chat|fix=Fix an error|flashcards=Flashcards|flowchart=Flowchart|
fontpair=Font pairs|fridge=Recipe from my fridge|funfact=Fun fact|gantt=Gantt chart|gcal=Google Calendar|
gift=Gift ideas|git=Ask the repo|gold=Gold prices|grammar=Grammar check|greeting=Greeting card|handsfree=Hands-free|
hash=File hash|headline=Headlines|health=AI health check|help=All commands|holidays=Public holidays|
homework=Homework helper|image=Generate a picture|img=Edit last picture|imgs=Bulk image converter|inbox=Email inbox|
index=Index project|instructions=Chat rules|invitation=Invitation|invoice=Invoice|json=JSON tool|jwt=JWT decoder|
kanban=Kanban board|keys=Keyboard shortcuts|lang=Language|loan=Loan calculator|locate=Find my files|lock=Lock JARVIS|
logo=Logo maker|look=Ask about a picture|makedoc=Word + PDF document|mcp=Coding IDE hookup|mealplan=Meal plan|
media=Media controls|meds=Medicine reminders|meme=Meme maker|memory=Memory|menu=Menu designer|mindmap=Mind map|
mini=Mini mode|mode=Thinking mode|mylist=To-do list|news=News|note=Quick note|notes=Notes|ocr=Copy text from image|
open=Open a web page|orgchart=Org chart|outline=Essay outline|pack=Packing list|palette=Colour palette|
passcheck=Password strength|password=Password generator|pc=Why is my PC slow|pdf=PDF document|pdfmerge=Merge PDFs|
pdfsplit=Split a PDF|persona=Persona|pin=Pin answer|pins=Pinned answers|port=Ports|post=Social post|
poster=Poster|power=Shutdown and restart|pr=Pull request|prayer=Prayer times|pricewatch=Price watch|
privacy=Privacy mode|procscan=Process scan|pwned=Breached password check|py=Run Python|qr=QR code|quake=Earthquakes|
quiz=Quiz me|quizslides=Quiz slides|readaloud=Read aloud|readme=README writer|recall=Search old chats|
record=Record a lecture|redact=Redact text|release=Release checklist|remind=Reminder|reminders=Reminders|
rename=Batch rename|resize=Resize a design|retry=Ask again|revert=Revert agent change|review=Code review|
roll=Dice and coin|run=Run a command|sale=Sale poster|sandbox=Sandbox|scan=Secret scan|screentime=Screen time|
search=Web search|security=Security settings|setup=Setup help|shred=Shred a file|sleepcalc=Sleep calculator|
slides=Slides|snippet=Code snippets|solve=Equation solver|specs=PC specs|speedtest=Internet speed|spent=Spending|
split=Split a bill|startup=Startup apps|stats=AI usage|sticker=Sticker|stock=Stock quotes|stopwatch=Stopwatch|
studyplan=Study plan|suggest=Follow-up suggestions|sun=Sunrise and sunset|synonyms=Synonyms|system=System info|
t=Prompt templates|task=Scheduled commands|testgen=Write tests|thumbnail=YouTube thumbnail|tidy=Tidy a folder|
time=Time|timeline=Timeline|timer=Timer|timers=Timers|todo=Project TODOs|tour=Welcome tour|trace=Stack trace|
translate=Live translation|translatecode=Translate code|trivia=Trivia|tutor=Language tutor|typing=Typing test|
uuid=UUID|vary=Picture variations|voice=Voice on/off|volume=Volume|wallpaper=AI wallpaper|watches=Alerts and watches|
watchlist=Watchlist|watchpage=Watch a web page|weather=Weather|web=Web answer|website=Website maker|
whatsapp=WhatsApp message|where=Where in code|wifi=Wi-Fi info|wifisafe=Wi-Fi safety|wiki=Wikipedia|
wireframe=Wireframe|word=Word of the day|workout=Workout plan|yaml=YAML tool|yt=YouTube summary|
ytslides=Slides from YouTube|zoom=Text size"""
TITLES = dict(pair.strip().split("=", 1) for pair in _TITLES.replace("\n", "").split("|") if "=" in pair)

_FILEY = re.compile(r"<[^>]*(file|path|image|picture|photo|pdf|csv|xlsx|docx|video|audio)[^>]*>", re.I)
_FOLDERY = re.compile(r"<[^>]*folder[^>]*>|\[folder", re.I)
_CHOICES = re.compile(r"(?:^|\s)\[?([a-z0-9çğıöşü-]+(?:\|[a-z0-9çğıöşü<> -]+)+)\]?", re.I)


def _auto(tool: Tool) -> Tool:
    """A one-box form for a command that does not describe its own."""
    if tool.fields:
        return tool
    usage = tool.usage.split(None, 1)
    rest = usage[1] if len(usage) > 1 else ""
    if not rest:
        return tool
    kind = "folder" if _FOLDERY.search(rest) else "file" if _FILEY.search(rest) else "text"
    choices = []
    for match in _CHOICES.finditer(rest):
        choices += [c.strip() for c in match.group(1).split("|") if c.strip() and "<" not in c]
    optional = rest.startswith("[")
    tool.fields = (field("args", kind if kind != "text" else "text", "Details", optional=optional, hint=rest),)
    if choices:
        tool.extra["choices"] = choices[:8]
    if kind != "text":
        tool.extra["browse"] = kind
    return tool


# Registered commands that hold a conversation, or need a hidden box for a
# secret: their tile puts them in the chat instead of a form.
CHAT_TOOLS = {"tutor", "20q", "trivia", "typing", "cards", "handsfree", "passcheck", "pwned", "2fa", "homework",
              "persona", "whatsapp", "inbox"}

_cache: dict | None = None
# The window asks for one tool at a time (a page of 33 tool cards asked 33
# times), so the list with addons is kept too, for as long as the same
# addons with the same commands are loaded.
_with_addons: tuple | None = None


def _addons_key(addons) -> tuple:
    return (id(addons), len(registry.TOOLS),
            tuple(tuple(getattr(entry, "commands", {})) for entry in getattr(addons, "loaded", [])))


def tools(addons=None) -> dict[str, Tool]:
    """Every command, by primary name, aliases folded in."""
    global _cache, _with_addons
    if _cache is not None and addons is None:
        return _cache
    if addons is not None and _with_addons is not None and _with_addons[0] == _addons_key(addons):
        return _with_addons[1]
    from . import eight  # noqa: F401 — importing registers the 8.0+ commands

    found: dict[str, Tool] = {}
    for tool in registry.TOOLS.values():
        if tool.name in CHAT_TOOLS:
            tool.chat = True
        found[tool.name] = _auto(tool)
    taken = {n for t in found.values() for n in t.names}
    for names, group, usage, text, icon, chat in _LEGACY:
        split = names.split()
        if split[0] in taken:
            continue
        found[split[0]] = _auto(Tool(name=split[0], names=tuple(split), group=group, usage=usage, help=text,
                                     icon=icon, chat=chat))
        taken.update(split)
    for name, (group, usage, text, icon) in _UI_ONLY.items():
        if name not in taken:
            found[name] = _auto(Tool(name=name, names=(name,), group=group, usage=usage, help=text, icon=icon))
            taken.add(name)
    if addons is not None:
        for entry in getattr(addons, "loaded", []):
            for key, command in getattr(entry, "commands", {}).items():
                if key in taken:
                    continue
                found[key] = _auto(Tool(name=key, names=(key,), group="Chat and AI",
                                        usage=command.usage or f"/{key}", help=command.help, icon="🧩"))
                taken.add(key)
    for tool in found.values():
        if tool.group not in GROUP_ICONS:
            tool.group = "Chat and AI"
        if not tool.title and tool.name in TITLES:
            tool.title = TITLES[tool.name]
        if tool.icon in {"", "•"}:
            tool.icon = GROUP_ICONS.get(tool.group, "•")
    if addons is None:
        _cache = found
    else:
        _with_addons = (_addons_key(addons), found)
    return found


def groups(found: dict[str, Tool]) -> list[str]:
    order = list(GROUP_ICONS)
    present = {t.group for t in found.values()}
    return [g for g in order if g in present]


def _norm(text: str) -> str:
    table = str.maketrans("çğıöşüİâî", "cgiosuiai")
    return (text or "").lower().translate(table)


def score(tool: Tool, query: str) -> float:
    """How well a tool matches what was typed. 0 = not at all."""
    q = _norm(query).strip().lstrip("/")
    if not q:
        return 1.0
    words = q.split()
    name = _norm(" ".join(tool.names))
    title = _norm(tool.label())
    hay = " ".join([name, title, _norm(tool.help), _norm(tool.keywords), _norm(tool.group)])
    total = 0.0
    for word in words:
        if any(n == word for n in name.split()):
            total += 6
        elif any(n.startswith(word) for n in name.split()):
            total += 4
        elif title.startswith(word) or f" {word}" in f" {title}":
            total += 3
        elif word in hay:
            total += 1
        else:
            return 0.0
    return total


def search(query: str, found: dict[str, Tool] | None = None, limit: int = 30) -> list[Tool]:
    found = found if found is not None else tools()
    ranked = [(score(t, query), t.name, t) for t in found.values()]
    ranked = [r for r in ranked if r[0] > 0]
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return [r[2] for r in ranked[:limit]]


# --- recently used --------------------------------------------------------------

RECENT = kit.Store("recent_tools.json", [])


def used(name: str) -> None:
    items = [i for i in RECENT.load() if isinstance(i, dict) and i.get("name") != name]
    items.insert(0, {"name": name, "at": time.time()})
    try:
        RECENT.save(items[:24])
    except OSError:
        pass


def recent(limit: int = 8, found: dict[str, Tool] | None = None) -> list[Tool]:
    found = found if found is not None else tools()
    out = []
    for item in RECENT.load():
        tool = found.get(item.get("name", "")) if isinstance(item, dict) else None
        if tool is not None:
            out.append(tool)
        if len(out) >= limit:
            break
    return out


def suggest(text: str, limit: int = 4, found: dict[str, Tool] | None = None) -> list[Tool]:
    """Tools worth offering while someone types a plain sentence or a command."""
    text = (text or "").strip()
    if len(text) < 3:
        return []
    found = found if found is not None else tools()
    if text.startswith("/"):
        word = _norm(text[1:].split(" ", 1)[0])
        if " " in text[1:]:
            return []
        hits = [t for t in found.values() if any(_norm(n).startswith(word) for n in t.names)]
        hits.sort(key=lambda t: (min(len(n) for n in t.names), t.name))
        return hits[:limit]
    words = [w for w in re.findall(r"[\wçğıöşü]+", _norm(text)) if len(w) > 3]
    if not words:
        return []
    ranked = []
    for tool in found.values():
        hay = _norm(" ".join([" ".join(tool.names), tool.label(), tool.keywords]))
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", hay))
        if hits:
            ranked.append((hits, -len(tool.label()), tool))
    ranked.sort(key=lambda r: (-r[0], -r[1]))
    return [r[2] for r in ranked[:limit]]
