"""The 6.0 commands: everyday use, the PC, documents, and privacy switches.

Kept out of assistant.py, which was already the longest file in the project,
as a mixin the Jarvis class inherits. Every method here returns either text
or a JarvisResponse, and None only where a plain-language request turned out
not to be a command after all ("open the pod bay doors") and should go to
the AI instead.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import (
    data as data_mod, imagetools, intents, neural, notes, pc, redact, reminders,
    security, shield, weather, websearch, writer,
)
from .config import get_setting

LANGUAGES = {
    "english": "en", "turkish": "tr", "türkçe": "tr", "german": "de", "french": "fr",
    "spanish": "es", "italian": "it", "portuguese": "pt", "dutch": "nl", "russian": "ru",
    "arabic": "ar", "japanese": "ja", "chinese": "zh", "korean": "ko", "hindi": "hi",
    "azerbaijani": "az", "polish": "pl", "ukrainian": "uk", "persian": "fa", "greek": "el",
    "swedish": "sv",
}
NAMES = {code: name.capitalize() for name, code in LANGUAGES.items() if name != "türkçe"}

# Words that mean a question is about now, not about what a model learned.
_FRESH = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|this (?:week|month|year)|latest|newest|current(?:ly)?|"
    r"right now|recent(?:ly)?|news|headlines?|score|won|winner|price of|stock|release date|"
    r"just (?:released|announced)|20(?:2[6-9]|3\d)|bugün|dün|son dakika|güncel)\b",
    re.I,
)

HELP = """JARVIS commands — or just say it in plain words.

Everyday
  pause / next song / volume 30      media and volume
  open spotify / open downloads      apps and folders           /app
  find my CV pdf from last month     search your files           /locate
  why is my PC slow                  CPU, memory, disk, culprits /pc
  remind me in 20 min to call Ata    reminders                   /remind /reminders
  timer 10 minutes tea / alarm 7:30  timers and alarms           /timer /alarm /timers
  weather tomorrow in Istanbul       forecast (no key)           /weather
  note: buy milk                     quick notes                 /note /notes
  /t email-reply <text>              prompt templates            /t
  /translate turkish                 live translation, spoken    /translate off
  read that out loud                 read aloud                  /readaloud <file|url>

Documents and data
  /makedoc <what>    Word + PDF     /docx  /pdf     /makedoc revise: <change>
  /data <file.csv|xlsx>  then /data <question>   exact numbers and charts
  /read <url> [question]  a web page     /doc <file>  a document     /docs <folder>
  make this 800px wide as a JPG    image tools on the last image  /img
  what's in this picture?          ask about the last image       /look

Exact answers and tools
  15% of 240 · 100 usd to try · 5 miles to km · days until christmas     /calc
  what time is it in Tokyo · 3pm Istanbul in London                       /clock
  good morning — weather, today's reminders, headlines    /briefing [at 8:00|off]
  copy text from the screen — drag a box, read offline     /ocr [image|screen]
  tidy up my downloads — plan first, /tidy go, /tidy undo                  /tidy
  /clip explain|summarize|translate <lang>|fix|reply   works on your clipboard
  generate a password (to the clipboard, never shown)   /password [length]
  /qr <text>   /stopwatch start|stop|lap|reset   /memory — edit what I remember

Coding
  /project <folder>  /agent <task>  /fix  /trace  /testgen <file>  /commit
  /review  /pr  /explain <file|name>  /todo  /changes  /revert <file>
  /where <thing>  /index  /git  /test  /diff  /apply  /undo

Conversation
  /chat new|<name>  /chats  /recall <words>  /retry  /edit (or ↑)  /export [html|pdf]
  /instructions <standing rules for this chat>   /pin  /pins   /suggest on|off
  /mode low|mid|high|max|hyperdrive|security   /code   /image <prompt>  /vary
  /mini  /zoom in|out   Ctrl+Alt+Space: quick ask from anywhere

Privacy and security
  /privacy  /redact  /autoweb  /offline  /lock [set|off]  /security  /audit  /scan  /sandbox <file>

Setup
  /health  /bench  /compare <question>  /stats  /lang  /setup  /keys"""


class Everyday:
    """Mixed into Jarvis. Uses self.brain, self.voice, self.addons."""

    # --- dispatch -------------------------------------------------------

    def everyday_command(self, name: str, args: str, routed: bool = False):
        """Handle a 6.0 command. Returns text, a JarvisResponse, or None."""
        handlers = {
            "help": lambda: HELP,
            "media": lambda: pc.media(args or "toggle"),
            "volume": lambda: self.volume(args),
            "app": lambda: self.open_app(args, routed),
            "locate": lambda: self.locate(args),
            "pc": lambda: self.pc_status(args),
            "remind": lambda: self.remind(args, routed),
            "reminders": lambda: self.list_reminders(args),
            "timer": lambda: self.timer(args),
            "alarm": lambda: self.alarm(args),
            "timers": lambda: self.list_reminders(args, {"timer", "alarm"}),
            "weather": lambda: self.weather(args, routed),
            "note": lambda: notes.add_note(args),
            "notes": lambda: self.notes(args),
            "t": lambda: self.template(args),
            "makedoc": lambda: self.make_document(args, ("docx", "pdf")),
            "docx": lambda: self.make_document(args, ("docx",)),
            "pdf": lambda: self.make_document(args, ("pdf",)),
            "data": lambda: self.data(args),
            "img": lambda: self.image_tool(args, routed),
            "translate": lambda: self.translate_mode(args),
            "readaloud": lambda: self.read_aloud(args, routed),
            "commit": lambda: self.commit(args),
            "redact": lambda: self.redact_setting(args),
            "autoweb": lambda: self.autoweb_setting(args),
        }
        handler = handlers.get(name)
        return handler() if handler else None

    def route_plain(self, text: str):
        """A plain sentence that is really a command, handled. Else None."""
        routed = intents.route(text)
        if routed is None:
            return None
        command, may_fall_through = routed
        name, _, args = command[1:].partition(" ")
        result = self.everyday_command(name, args, routed=may_fall_through)
        if result is None:
            result = self.extras_command(name, args, routed=may_fall_through)
        return result

    # --- media, apps, files, PC ------------------------------------------

    def volume(self, args: str) -> str:
        wanted = args.strip().lower().rstrip("%")
        if wanted in {"up", "down"}:
            return pc.volume_step(wanted)
        if wanted in {"mute", "unmute"}:
            return pc.media("mute")
        if wanted.isdigit():
            security.audit.record("volume", wanted)
            return pc.set_volume(int(wanted))
        return "Usage: /volume <0-100|up|down|mute>"

    def open_app(self, args: str, routed: bool = False):
        target = args.strip()
        if not target:
            return "Usage: /app <name>   e.g. /app spotify, /app downloads"
        opened, message = pc.open_app(target, sure=0.8 if routed else 0.6)
        if not opened:
            if routed:
                return None      # not an app: let the AI have the sentence
            app, score = pc.find_app(target)
            hint = f" Closest: {app.name}." if app and score > 0.4 else ""
            return f"I couldn't find '{target}' in the Start menu.{hint}"
        security.audit.record("open app", target[:80])
        return message

    def locate(self, args: str) -> str:
        text = args.strip()
        m = re.fullmatch(r"(open|show)\s+(\d{1,2})", text.lower())
        if m:
            found = getattr(self, "_found", [])
            index = int(m.group(2)) - 1
            if not 0 <= index < len(found):
                return "Search for files first — e.g. 'find my CV pdf'."
            path = found[index].path
            if m.group(1) == "open":
                pc.open_path(path)
                security.audit.record("open file", path.name)
                return f"Opening {path.name}."
            pc.reveal_in_folder(path)
            return f"Showing {path.name} in its folder."
        if not text:
            return "Usage: /locate <words>   e.g. /locate my CV pdf from last month"
        started = time.monotonic()
        self._found = pc.find_files(text)
        security.audit.record("find files", f"{len(self._found)} found",
                              f"{time.monotonic() - started:.1f}s")
        return pc.describe_found(self._found, text)

    def pc_status(self, args: str) -> str:
        try:
            snapshot = pc.status_snapshot()
        except ImportError:
            return "PC status needs psutil (pip install psutil)."
        report = pc.format_status(snapshot)
        problems = pc.findings(snapshot)
        verdict = ("\n\nWhat stands out:\n" + "\n".join(f"  • {p}" for p in problems)) if problems \
            else "\n\nNothing stands out — memory, processor and disk all have room."
        if args.strip().lower() not in {"why", "explain"}:
            return report + verdict
        explanation = self.brain.ask_once(
            "Here are live readings from the user's Windows PC. In plain words, "
            "say what is most likely making it slow (or that nothing is), and "
            "the two or three things worth doing about it, most useful first. "
            "Name the programs. If a program looks unfamiliar, say what it "
            "usually is rather than guessing it is malware. Be brief.\n\n"
            f"{report}\n\nAutomatic findings: {problems or 'none'}"
        )
        return f"{report}{verdict}\n\n{explanation}"

    # --- reminders, timers, alarms -----------------------------------------

    def remind(self, args: str, routed: bool = False):
        parsed = reminders.parse_reminder(args)
        if parsed is None:
            if routed:
                return None
            return ("I couldn't tell when. Try:\n  remind me in 20 minutes to call Ata\n"
                    "  remind me at 17:30 to leave\n  remind me tomorrow at 9 to send the report")
        due, what = parsed
        item = reminders.board.add("reminder", what or "Reminder", due)
        security.audit.record("reminder set", item.when())
        return f"🔔 I'll remind you {item.when()}: {item.text}"

    def timer(self, args: str) -> str:
        parsed = reminders.parse_duration(args)
        if parsed is None or parsed[0] <= 0:
            return "Usage: /timer 10 minutes [label]   e.g. timer 90s, timer 1h30m pasta"
        seconds, label = parsed
        item = reminders.board.add("timer", label or f"{reminders.describe_seconds(seconds)} timer",
                                   time.time() + seconds)
        return f"⏱ Timer set for {reminders.describe_seconds(seconds)}" + (f" — {label}" if label else "") \
            + f". /timers to see it."

    def alarm(self, args: str) -> str:
        parsed = reminders.parse_clock(args)
        if parsed is None:
            return "Usage: /alarm 7:30 [label]   also 'alarm 6am', 'alarm tomorrow 6:45'"
        moment, label = parsed
        item = reminders.board.add("alarm", label or "Alarm", moment.timestamp())
        return f"⏰ Alarm set for {item.when()}" + (f" — {label}" if label else "") \
            + ". It rings only while JARVIS is open."

    def list_reminders(self, args: str, kinds: set[str] | None = None) -> str:
        verb, _, rest = args.strip().partition(" ")
        if verb.lower() in {"cancel", "delete", "remove", "stop"}:
            return reminders.board.cancel(rest or "all")
        return (reminders.board.describe(kinds)
                + "\n\n/reminders cancel <n|all>. They fire only while JARVIS is open.")

    # --- weather, notes, templates ----------------------------------------

    def weather(self, args: str, routed: bool = False):
        text = args.strip()
        m = re.fullmatch(r"(?:city|home|set city)\s+(.+)", text, re.I)
        if m:
            city = m.group(1).strip()
            try:
                label, _lat, _lon = weather.geocode(city)
            except weather.WeatherError as exc:
                return str(exc)
            self._write_setting("JARVIS_CITY", city)
            return f"Home city set to {label}. 'weather' now means there."
        try:
            return weather.report(text)
        except weather.WeatherError as exc:
            if routed and "couldn't find a place" in str(exc):
                return None
            return str(exc)

    def notes(self, args: str) -> str:
        verb, _, rest = args.strip().partition(" ")
        if verb.lower() in {"delete", "remove", "del"}:
            return notes.delete_note(rest)
        if verb.lower() == "clear":
            return notes.delete_note("all")
        return notes.list_notes(args)

    def template(self, args: str):
        from .assistant import JarvisResponse

        name, _, rest = args.strip().partition(" ")
        if not name:
            return notes.describe_templates()
        if name.lower() == "save":
            key, _, body = rest.strip().partition(" ")
            return notes.save_template(key, body)
        if name.lower() in {"delete", "remove"}:
            return notes.delete_template(rest.strip().lower())
        prompt = notes.expand(name, rest)
        if prompt is None:
            return f"No template called '{name}'. /t lists them."
        if "{input}" in notes.load_templates()[name.lower()] and not rest.strip():
            return f"/t {name} needs some text after it."
        reply = self.brain.chat(prompt, extra_context=self.addons.context_for(prompt) or None)
        self._maybe_speak(reply)
        return JarvisResponse(text=reply)

    # --- documents --------------------------------------------------------

    def make_document(self, args: str, formats: tuple[str, ...]) -> str:
        request = args.strip()
        if not request:
            return ("Usage: /makedoc <what to write>     Word + PDF\n"
                    "       /docx <what> or /pdf <what>   one format\n"
                    "       /makedoc revise: <change>   edit the last one\n"
                    "e.g. /makedoc a one-page cover letter for a junior developer job")
        revise = re.match(r"^(?:revise|edit|change)\s*:?\s*(.+)$", request, re.I | re.S)
        if revise and getattr(self, "_last_document", ""):
            answer = self.brain.ask_once(writer.REVISE.format(
                request=revise.group(1), document=self._last_document))
        else:
            answer = self.brain.ask_once(f"{writer.PROMPT}\nThe user asked for: {request}")
        markdown = writer.clean_markdown(answer)
        if not markdown.startswith("#") and len(markdown) < 200:
            return f"No document came back:\n{answer[:400]}"
        try:
            paths = writer.save(markdown, formats)
        except writer.WriterError as exc:
            return str(exc)
        self._last_document = markdown
        security.audit.record("document", writer.title_of(markdown)[:80],
                              ", ".join(p.suffix for p in paths))
        words = len(re.findall(r"\w+", markdown))
        listing = "\n".join(f"  {p}" for p in paths)
        return (f"📄 {writer.title_of(markdown)} — {words:,} words\n{listing}\n\n"
                "/makedoc revise: <change> edits it. Say 'open 1' after /locate, or open "
                "the folder with /app documents.")

    def data(self, args: str):
        from .assistant import JarvisResponse

        text = args.strip().strip('"')
        if not text:
            return ("Usage: /data <file.csv|.xlsx>   open a spreadsheet\n"
                    "       /data <question>         e.g. which region sold the most?\n"
                    "       /data chart <what>       e.g. chart revenue by month")
        candidate = Path(text).expanduser()
        if candidate.suffix.lower() in {".csv", ".tsv", ".xlsx", ".xlsm", ".txt"} and candidate.exists():
            try:
                self._table = data_mod.load(candidate)
            except data_mod.DataError as exc:
                return str(exc)
            security.audit.record("data open", candidate.name, f"{len(self._table.rows)} rows")
            return data_mod.profile(self._table) + "\n\nAsk with /data <question>, or /data chart <what>."
        table = getattr(self, "_table", None)
        if table is None:
            return "Open a spreadsheet first: /data <path to .csv or .xlsx>"

        if not security.permissions.ask(
            security.READ_FILE,
            f"column names, types and {data_mod.SAMPLE_ROWS} sample rows of {table.path.name} "
            "(the numbers are then worked out here, over every row)",
            context="/data",
        ):
            return "Denied. Nothing was sent."
        wants_chart = text.lower().startswith(("chart", "plot", "graph", "draw"))
        sample, warning = shield.wrap(data_mod.sample(table), table.path.name)
        answer = self.brain.ask_once(data_mod.QUERY_PROMPT.format(
            profile=data_mod.profile(table), sample=sample,
            question=text + (" (draw a chart)" if wants_chart else ""),
        ))
        try:
            query = data_mod.parse_query(answer)
            results, described = data_mod.run(table, query)
        except data_mod.DataError as exc:
            return f"{exc}\n\n{data_mod.profile(table)}"
        title = str(query.get("title") or text)[:80]
        body = f"{title}\n{data_mod.format_results(results)}\n\n({described})"
        if warning:
            body += f"\n\n{warning}"
        kind = str(query.get("chart") or "none").lower()
        if (wants_chart or kind in {"bar", "line"}) and len(results) > 1:
            from .config import get_output_dir

            out = get_output_dir() / f"chart_{time.strftime('%Y%m%d_%H%M%S')}.png"
            try:
                data_mod.chart(results, title, kind if kind in {"bar", "line"} else "bar", out)
                self.current_image = out
                return JarvisResponse(text=body + f"\n\nChart: {out}", image_path=out, image_paths=[out])
            except data_mod.DataError:
                pass
        return body

    def image_tool(self, args: str, routed: bool = False):
        from .assistant import JarvisResponse

        text = args.strip()
        source = None
        m = re.search(r"\s(?:on|for)\s+\"?([A-Za-z]:[\\/][^\"]+|/[^\"]+|~[^\"]+)\"?$", text)
        if m and Path(m.group(1)).expanduser().exists():
            source = Path(m.group(1)).expanduser()
            text = text[:m.start()]
        source = source or getattr(self, "current_image", None)
        if source is None or not Path(source).exists():
            if routed:
                return None
            return "Drop an image on the window first (or generate one), then say what to do with it."
        plan = imagetools.parse(text)
        if plan.empty and routed:
            return None
        try:
            out, done = imagetools.apply(Path(source), plan)
        except imagetools.ImageToolError as exc:
            return str(exc)
        security.audit.record("image tool", Path(source).name, ", ".join(done)[:120])
        self.current_image = out
        return JarvisResponse(text=f"Saved {out.name}\n  " + "\n  ".join(done) + f"\n\n{out}",
                              image_path=out, image_paths=[out])

    # --- reading ----------------------------------------------------------

    def read_url(self, url: str, question: str = "") -> str:
        """Fetch a page, open it like a document, and summarise or answer."""
        if not security.permissions.ask(security.NETWORK, url, context="/read"):
            return "Denied. Nothing was fetched."
        try:
            title, text = websearch.fetch(url)
        except websearch.SearchError as exc:
            return str(exc)
        security.audit.record("read page", url[:120], f"{len(text)} chars")
        cleaned = shield.clean(text, url)
        doc = self._document_addon()
        if doc is not None:
            doc.open_text(title or url, cleaned.text, url)
        ask = question or "Summarise this page in a short paragraph, then its key points as bullets."
        answer = self.brain.ask_once(
            f"{shield.RULE}\n\n{ask}\n\n{cleaned.wrapped()}"
        )
        warning = cleaned.warning()
        tail = "\n\nThe page stays open — ask follow-up questions normally. /docclose closes it."
        return f"{title}\n{url}\n\n{answer}" + (f"\n\n{warning}" if warning else "") + tail

    def read_aloud(self, args: str, routed: bool = False):
        text = args.strip()
        verb = text.lower()
        if verb in {"pause", "resume", "stop"}:
            if verb == "stop":
                self.voice.stop()
                return "Stopped reading."
            ok = self.voice.pause() if verb == "pause" else self.voice.resume()
            return ("Paused. /readaloud resume continues." if verb == "pause" else "Resumed.") if ok \
                else "Nothing is being read in the natural voice right now."
        if not text:
            return ("Usage: /readaloud <file or url>   /readaloud last   "
                    "/readaloud pause | resume | stop")
        if verb in {"last", "that", "it", "this"}:
            content = next((m["content"] for m in reversed(self.brain.history)
                            if m.get("role") == "assistant"), "")
            label = "the last answer"
        else:
            try:
                content, label = self._text_for_reading(text)
            except FileNotFoundError:
                if routed:
                    return None
                return f"I can't find '{text}' — give a full path, or a web address."
            except Exception as exc:
                return f"Couldn't read it: {exc}"
        if not content.strip():
            return "There's nothing to read."
        if not self.voice.tts_available():
            return "No voice is available on this PC."
        private = security.privacy.on or not neural.enabled()
        self.voice.speak(content[:200_000])
        minutes = max(1, round(len(content.split()) / 160))
        voice = "the offline Windows voice" if private else "the natural voice"
        return (f"🔊 Reading {label} in {voice} — about {minutes} min.\n"
                "/readaloud pause · resume · stop  (Escape also stops)")

    def _text_for_reading(self, target: str) -> tuple[str, str]:
        if re.match(r"^https?://", target, re.I):
            if not security.permissions.ask(security.NETWORK, target, context="/readaloud"):
                raise RuntimeError("denied")
            title, text = websearch.fetch(target)
            return shield.clean(text, target).text, title or target
        path = Path(target.strip('"')).expanduser()
        if not path.exists():
            doc = self._document_addon()
            if doc is not None and doc.text and target.lower() in {"document", "the document", "doc"}:
                return doc.text, doc.path.name if doc.path else "the document"
            raise FileNotFoundError(target)
        from . import library

        pages = library.read_document(path)
        return "\n\n".join(text for _page, text in pages), path.name

    def _document_addon(self):
        for entry in self.addons.loaded:
            if entry.addon.name == "document-qa":
                return entry.addon
        return None

    # --- translation --------------------------------------------------------

    def translate_mode(self, args: str) -> str:
        wanted = args.strip().lower()
        if wanted in {"", "status"}:
            current = getattr(self, "_translate_to", None)
            return (f"Live translation: {NAMES.get(current, current)}. /translate off to stop."
                    if current else "Usage: /translate <language>   e.g. /translate turkish\n"
                    "Everything you type or say is translated and read aloud; replies in "
                    "that language are translated back.")
        if wanted in {"off", "stop", "none"}:
            self._translate_to = None
            return "Live translation off."
        code = LANGUAGES.get(wanted, wanted if wanted in neural.BY_LANGUAGE else None)
        if code is None:
            return f"I don't know '{wanted}'. Try: {', '.join(sorted(LANGUAGES))}"
        self._translate_to = code
        mine = "tr" if self._home_language() == "tr" else "en"
        return (f"Live translation on: {NAMES.get(mine, mine)} ⇄ {NAMES.get(code, code)}.\n"
                "Type or speak normally — each line is translated and read aloud. "
                "/translate off to stop.")

    @staticmethod
    def _home_language() -> str:
        from . import i18n

        return i18n.current()

    def translate_line(self, text: str) -> str:
        target = self._translate_to
        home = "tr" if self._home_language() == "tr" else "en"
        if target == home:
            home = "en" if home == "tr" else "tr"
        answer = self.brain.ask_once(
            "You are a live interpreter. If the text is in "
            f"{NAMES.get(home, home)}, translate it into {NAMES.get(target, target)}; "
            f"otherwise translate it into {NAMES.get(home, home)}. Keep the tone and "
            "meaning, sound natural, and translate only — never answer it. "
            "Reply exactly as: <language code>|<translation>\n\n"
            f"Text: {text}"
        )
        code, sep, translation = answer.partition("|")
        code = code.strip().lower()[:2]
        if not sep or code not in neural.BY_LANGUAGE:
            code, translation = target, answer
        translation = translation.strip()
        if self.voice.tts_available():
            self.voice.speak(translation, language=code)
        return f"[{NAMES.get(code, code)}] {translation}"

    # --- web ---------------------------------------------------------------

    def autoweb_enabled(self) -> bool:
        return get_setting("JARVIS_AUTO_WEB", "on").strip().lower() not in {"0", "off", "false", "no"}

    def needs_fresh_facts(self, text: str) -> bool:
        if text.startswith("/") or len(text) > 400 or security.privacy.on:
            return False
        if self.brain.code_mode or not self.autoweb_enabled():
            return False
        from . import providers

        if providers.offline_mode():
            return False
        if not _FRESH.search(text):
            return False
        # A question, not a statement that happens to say "today".
        return "?" in text or bool(re.match(
            r"^(?:who|what|when|where|which|how|is|are|did|does|has|will|tell me|give me|show me|any)\b",
            text, re.I))

    def web_context(self, text: str) -> tuple[str, str]:
        """(context for the model, sources footer) — or ('', '') on failure.

        Automatic, so it does not ask: turning it on was the choice, it is
        off in Privacy mode, and every search is in the audit log and shown
        under the answer. Only the question is sent, to DuckDuckGo.
        """
        try:
            results = websearch.search(text)
        except Exception:
            return "", ""
        if not results:
            return "", ""
        security.audit.record("auto web search", f"{len(results)} results")
        material = "\n\n".join(f"--- {r.title} ({r.url}) ---\n{r.snippet}" for r in results)
        wrapped, _warning = shield.wrap(material, "web search results")
        context = (
            f"{shield.RULE}\nThese fresh web search results may help with the "
            "question. Prefer them over what you remember for anything recent, cite "
            f"the site you used, and say if they do not answer it.\n{wrapped}"
        )
        sources = "\n".join(f"  {r.title} — {r.url}" for r in results[:4])
        return context, f"\n\n🌐 Searched the web:\n{sources}"

    # --- git -----------------------------------------------------------------

    def commit(self, args: str) -> str:
        from . import vcs

        addon = self._project_addon()
        root = getattr(addon, "root", None) if addon else None
        if root is None:
            return "No project open. Use /project <folder> first."
        if not vcs.is_repo(root):
            return f"{root.name} is not a git repository."
        if args.strip().lower() == "all":
            if not security.permissions.ask(security.WRITE_FILE, "git add -u  (stage every tracked change)",
                                            context="/commit"):
                return "Denied. Nothing was staged."
            vcs._run(root, "add", "-u")
        diff = vcs.staged_diff(root)
        if not diff.strip():
            return ("Nothing is staged.\n  /commit all   stages every change to tracked files first\n"
                    "  /git add <file>   stages one\n\n" + vcs.status(root))
        leaks = vcs._secret_check(root)
        if leaks:
            from . import scanner

            security.audit.record("git commit", "blocked", f"{len(leaks)} secret(s)")
            return ("Refusing to commit — the staged changes contain what look like "
                    f"credentials:\n\n{scanner.format_report(leaks, 5)}")
        _code, files = vcs._run(root, "diff", "--cached", "--stat")
        _code, recent = vcs._run(root, "log", "--oneline", "-8")
        if not security.permissions.ask(
            security.SEND_CODE, f"the staged diff, to write a commit message:\n{files[-600:]}",
            context="/commit",
        ):
            return "Denied. Nothing was sent."
        message = self.brain.ask_once(
            "Write a git commit message for this staged diff. First line: what "
            "changed, imperative, at most 72 characters. Then a blank line and a "
            "short body saying why, wrapped at 72. Match the style of the recent "
            "commits. Output only the message — no fences, no quotes.\n\n"
            f"Recent commits:\n{recent}\n\nDiff:\n{diff[:14000]}"
        ).strip().strip("`").strip()
        if not message or len(message) < 8:
            return "No usable commit message came back."
        if not security.permissions.ask(
            security.WRITE_FILE, f"git commit with this message:\n\n{message}\n\nFiles:\n{files}",
            context="/commit",
        ):
            return f"Not committed. The message was:\n\n{message}"
        # One -m keeps the message's own line breaks, body included.
        code, out = vcs._run(root, "commit", "-m", message)
        security.audit.record("git commit", message.splitlines()[0][:80], "ok" if code == 0 else "failed")
        return (f"Committed.\n\n{message}\n\n{out}" if code == 0 else f"git commit failed:\n{out}")

    # --- privacy switches --------------------------------------------------

    def redact_setting(self, args: str) -> str:
        wanted = args.strip().lower()
        if wanted in {"on", "off"}:
            self._write_setting("JARVIS_REDACT", wanted)
            return f"Redaction {wanted}." + (
                " Keys, passwords, emails, phone and card numbers will be sent as-is." if wanted == "off" else "")
        last = getattr(self.brain, "last_redaction", None)
        state = "on" if redact.enabled() else "OFF"
        detail = last.describe() if last is not None else "nothing sent yet"
        return (f"Redaction is {state}. Last request: masked {detail}.\n"
                "Keys, passwords, emails, phone and card numbers leave as placeholders and "
                "are filled back in locally. /redact on|off")

    def autoweb_setting(self, args: str) -> str:
        wanted = args.strip().lower()
        if wanted in {"on", "off"}:
            self._write_setting("JARVIS_AUTO_WEB", wanted)
            return f"Automatic web search {wanted}."
        return (f"Automatic web search is {'on' if self.autoweb_enabled() else 'off'}. "
                "Questions about recent things search DuckDuckGo first and cite it; "
                "never in Privacy mode or code mode. /autoweb on|off")

    @staticmethod
    def _write_setting(name: str, value: str) -> None:
        import os

        os.environ[name] = value
        try:
            from ui.settings import write_env

            write_env({name: value})
        except Exception:
            pass
