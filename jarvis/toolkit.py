"""The 7.1 commands: study, YouTube, lecture notes, spending, speed, power.

A third mixin beside everyday.py and extras.py. Methods return text, a
JarvisResponse, or None where a plain-language request turned out not to be
a command after all.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import power, quiz as quiz_mod, recorder, reminders, security, shield, spending, speedtest, writer, youtube

QUIZ_STOP = {"stop", "quit", "end", "exit", "stop quiz", "end quiz", "quit quiz", "bitir", "dur"}
QUIZ_SKIP = {"skip", "pass", "next", "i don't know", "idk", "bilmiyorum", "geç"}
MATERIAL_CHARS = 30_000


class Toolkit:
    """Mixed into Jarvis alongside Everyday and Extras."""

    def toolkit_command(self, name: str, args: str, routed: bool = False):
        handlers = {
            "quiz": lambda: self.start_quiz(args),
            "flashcards": lambda: self.flashcards(args),
            "yt": lambda: self.youtube(args, routed),
            "youtube": lambda: self.youtube(args, routed),
            "record": lambda: self.record(args),
            "spent": lambda: self.spent(args),
            "spending": lambda: self.spent(args or "month"),
            "speedtest": lambda: self.speed_test(args),
            "power": lambda: self.power(args, routed),
        }
        handler = handlers.get(name)
        return handler() if handler else None

    # --- study ------------------------------------------------------------------

    def _material(self, source: str) -> tuple[str, str]:
        """(label, text) for a file path, 'doc' (whatever is open), or ('', '') for a topic."""
        source = source.strip().strip('"')
        doc = self._document_addon()
        if source.lower() in {"", "doc", "this", "it", "the document", "the video"} and doc is not None and doc.text:
            return doc._label(), doc.text
        path = Path(source).expanduser()
        if source and len(source) < 260 and path.is_file() and doc is not None:
            if not security.permissions.ask(security.READ_FILE, str(path), context="/quiz"):
                raise quiz_mod.QuizError("Denied. The file was not read.")
            try:
                return path.name, doc._extract(path)
            except Exception as exc:
                raise quiz_mod.QuizError(f"Couldn't read {path.name}: {exc}") from exc
        return "", ""

    def _about(self, label: str, text: str, topic: str) -> str:
        if not text:
            return f"about: {topic}"
        wrapped, _ = shield.wrap(text[:MATERIAL_CHARS], label)
        return f"based only on this material ({label}):\n{shield.RULE}\n\n{wrapped}\n"

    def start_quiz(self, args: str):
        text = args.strip()
        low = text.lower()
        current = getattr(self, "_quiz", None)
        if low in QUIZ_STOP:
            if current is None:
                return "No quiz running."
            self._quiz = None
            return current.result()
        if low in {"again", "retry", "missed"}:
            last = getattr(self, "_last_quiz", None)
            if last is None or not last.missed:
                return "Nothing to retry. /quiz <topic> starts a new one."
            self._quiz = quiz_mod.Quiz(last.topic, list(last.missed))
            self._last_quiz = self._quiz
            return "Retrying the ones you missed.\n\n" + self._quiz.ask()
        count = 8
        m = re.match(r"^(\d{1,2})\s+(?:questions?\s+)?(?:on\s+|about\s+)?(.*)$", text, re.I)
        if m:
            count, text = max(3, min(int(m.group(1)), 25)), m.group(2)
        text = re.sub(r"^(?:me\s+)?(?:on|about)\s+", "", text, flags=re.I).strip()
        try:
            label, material = self._material(text)
        except quiz_mod.QuizError as exc:
            return str(exc)
        if not text and not material:
            return ("Usage: /quiz <topic>        e.g. /quiz photosynthesis, /quiz 10 WW2 causes\n"
                    "       /quiz <file.pdf>     questions from your notes or slides\n"
                    "       /quiz                on the open document or YouTube video\n"
                    "Answer A-D · 'skip' · 'stop'. /flashcards <topic|file> makes Anki cards.")
        topic = label or text
        answer = self.brain.ask_once(quiz_mod.QUIZ_PROMPT.format(
            count=count, about=self._about(label, material, text), level=""))
        try:
            questions = quiz_mod.questions_from(answer)
        except quiz_mod.QuizError as exc:
            return str(exc)
        self._quiz = quiz_mod.Quiz(topic, questions)
        self._last_quiz = self._quiz
        security.audit.record("quiz", topic[:80], f"{len(questions)} questions")
        return (f"📝 Quiz on {topic} — {len(questions)} questions. Answer A-D, 'skip', or 'stop'.\n\n"
                + self._quiz.ask())

    def quiz_reply(self, text: str) -> str:
        """While a quiz is running, a plain message is an answer."""
        current = self._quiz
        low = text.strip().lower().rstrip(".!")
        if low in QUIZ_STOP:
            self._quiz = None
            return current.result()
        feedback = current.skip() if low in QUIZ_SKIP else current.answer(text)
        if feedback.startswith("Answer with"):
            return feedback
        if current.done:
            self._quiz = None
            return f"{feedback}\n\n{current.result()}"
        return f"{feedback}\n\n{current.ask()}"

    def flashcards(self, args: str) -> str:
        text = args.strip()
        count = 20
        m = re.match(r"^(\d{1,3})\s+(.*)$", text)
        if m:
            count, text = max(5, min(int(m.group(1)), 100)), m.group(2)
        last = getattr(self, "_last_quiz", None)
        try:
            label, material = self._material(text)
        except quiz_mod.QuizError as exc:
            return str(exc)
        if not text and not material:
            if last is None:
                return "Usage: /flashcards <topic or file>   e.g. /flashcards 30 Spanish food words"
            text = last.topic
        topic = label or text
        answer = self.brain.ask_once(quiz_mod.CARDS_PROMPT.format(
            count=count, about=self._about(label, material, text)))
        try:
            cards = quiz_mod.cards_from(answer)
        except quiz_mod.QuizError as exc:
            return str(exc)
        path = quiz_mod.save_cards(cards, topic)
        security.audit.record("flashcards", topic[:80], f"{len(cards)} cards")
        preview = "\n".join(f"  • {front} — {back}" for front, back in cards[:8])
        more = f"\n  … and {len(cards) - 8} more" if len(cards) > 8 else ""
        return (f"🗂 {len(cards)} flashcards on {topic}\n{preview}{more}\n\n{path}\n"
                "Import into Anki (File → Import) or Quizlet (paste, comma between term and definition).")

    # --- YouTube ------------------------------------------------------------------

    def youtube(self, args: str, routed: bool = False):
        text = args.strip()
        vid = youtube.video_id(text.split()[0]) if text else None
        if vid is None:
            last = getattr(self, "_video", None)
            if routed:
                return None
            if not text or last is None:
                return ("Usage: /yt <YouTube link> [question]   summary, or an answer about the video\n"
                        "       /yt <question>                  ask more about the last video")
            return self._ask_video(last, text)
        question = " ".join(text.split()[1:])
        if not security.permissions.ask(security.NETWORK, f"https://www.youtube.com/watch?v={vid}", context="/yt"):
            return "Denied. Nothing was fetched."
        try:
            language, transcript = youtube.transcript(vid)
        except youtube.YouTubeError as exc:
            return str(exc)
        title = youtube.title(vid)
        cleaned = shield.clean(transcript, f"YouTube {vid}")
        self._video = {"id": vid, "title": title, "text": cleaned.text}
        doc = self._document_addon()
        if doc is not None:
            doc.open_text(title, cleaned.text, f"https://youtu.be/{vid}")
        security.audit.record("youtube", title[:100], f"{len(transcript)} chars, {language}")
        answer = self._ask_video(self._video, question)
        warning = cleaned.warning()
        return (f"▶ {title}\nhttps://youtu.be/{vid}\n\n{answer}" + (f"\n\n{warning}" if warning else "")
                + "\n\nThe video stays open — ask follow-ups normally, or /quiz to test yourself on it.")

    def _ask_video(self, video: dict, question: str) -> str:
        ask = question or (
            "Summarise this video: one short paragraph, then the key points as bullets with their "
            "[m:ss] timestamps, then one line on who it is useful for.")
        wrapped, _ = shield.wrap(video["text"], f"YouTube {video['id']}")
        return self.brain.ask_once(
            f"{shield.RULE}\n\nThis is the transcript of the YouTube video \"{video['title']}\", "
            f"with [m:ss] timestamps. Cite timestamps when you point to a moment.\n\n"
            f"{ask}\n\n{wrapped}")

    # --- lecture / meeting notes --------------------------------------------------

    def _recorder(self) -> recorder.Recorder:
        if getattr(self, "_rec", None) is None:
            from .voice import BLOCK_SIZE, MIC_SAMPLE_RATE

            self._rec = recorder.Recorder(self.voice._transcribe, MIC_SAMPLE_RATE, BLOCK_SIZE)
        return self._rec

    def record(self, args: str) -> str:
        verb = args.strip().lower() or "start"
        rec = self._recorder()
        if verb in {"start", "on", "begin", "lecture", "meeting"}:
            if rec.running:
                return f"Already recording ({reminders.describe_seconds(rec.elapsed())}). /record stop writes the notes."
            if not self.voice.mic_available():
                return "No microphone found. Plug one in (or check Windows' privacy settings) and try again."
            if not self.voice.stt_available():
                return "Nothing can transcribe speech yet: add a GROQ_API_KEY (free) in /keys."
            rec.start()
            security.audit.record("record", "started")
            return ("🔴 Recording. I'll transcribe as we go; audio is never saved to disk.\n"
                    "/record stop writes the notes · /record status · /record cancel")
        if verb == "status":
            if not rec.running:
                return "Not recording. /record starts."
            return f"🔴 Recording for {reminders.describe_seconds(rec.elapsed())}, {len(rec.pieces)} part(s) transcribed so far."
        if verb in {"cancel", "discard"}:
            if not rec.running:
                return "Not recording."
            rec.stop(timeout=5)
            rec.pieces = []
            return "Recording discarded. Nothing was saved."
        if verb in {"stop", "end", "done", "finish"}:
            if not rec.running:
                return "Not recording. /record starts."
            length = rec.elapsed()
            transcript = rec.stop()
            problems = "\n".join(f"  {e}" for e in rec.errors[:3])
            if not transcript.strip():
                return "I didn't catch any speech." + (f"\n{problems}" if problems else "")
            answer = self.brain.ask_once(recorder.NOTES_PROMPT.format(transcript=transcript[:150_000]))
            markdown = writer.clean_markdown(answer)
            if not markdown.startswith("#"):
                markdown = f"# Recording {datetime.now():%d %B %Y %H:%M}\n\n{answer}"
            markdown += f"\n\n---\n\n## Transcript\n\n{transcript}\n"
            try:
                paths = writer.save(markdown, ("docx",))
            except writer.WriterError as exc:
                return str(exc)
            self._last_document = markdown
            doc = self._document_addon()
            if doc is not None:
                doc.open_text(writer.title_of(markdown), transcript, "your recording")
            security.audit.record("record", "notes written", f"{int(length)}s")
            notes_only = markdown.split("\n---\n")[0]
            return (f"{notes_only}\n\n📄 {paths[0]}\n({reminders.describe_seconds(length)} recorded; "
                    "the transcript is at the end of the file. Ask questions about it, or /quiz to revise.)"
                    + (f"\nSome parts failed:\n{problems}" if problems else ""))
        return "Usage: /record · /record stop · /record status · /record cancel"

    # --- spending -----------------------------------------------------------------

    def spent(self, args: str) -> str:
        text = args.strip()
        low = text.lower()
        if not text or low in {"month", "this month", "today", "week", "this week", "last month", "year",
                               "this year", "bugün", "bu hafta", "geçen ay", "bu yıl"}:
            return spending.summary(low or "month")
        if low in {"undo", "delete last", "remove last"}:
            return spending.undo()
        if low.startswith("budget"):
            value = low[6:].strip()
            if not value:
                limit = spending.budget()
                return (f"Monthly budget: {spending.money(limit, spending.default_currency())}."
                        if limit else "No budget set. /spent budget 5000")
            if value in {"off", "none", "0"}:
                self._write_setting("JARVIS_BUDGET", "")
                return "Budget off."
            try:
                amount = spending._number(re.sub(r"[^\d.,]", "", value))
            except ValueError:
                return "Usage: /spent budget 5000"
            self._write_setting("JARVIS_BUDGET", f"{amount:g}")
            return f"Monthly budget set to {spending.money(amount, spending.default_currency())}."
        if low.startswith("currency"):
            code = low[8:].strip()
            code = spending.CURRENCIES.get(code, code.upper())
            if not re.fullmatch(r"[A-Z]{3}", code or ""):
                return f"Usage: /spent currency try|usd|eur|gbp (now {spending.default_currency()})"
            self._write_setting("JARVIS_CURRENCY", code)
            return f"Amounts without a currency are now {code}."
        if low in {"export", "excel", "xlsx"}:
            path = writer.documents_dir() / f"spending_{spending.stamp()}.xlsx"
            try:
                count = spending.export(path)
            except spending.SpendingError as exc:
                return str(exc)
            return f"Exported {count} entries to\n  {path}"
        try:
            entry, entries = spending.add(text)
        except spending.SpendingError as exc:
            return str(exc)
        start, end, label = spending.period("month")
        month = spending.totals(entries, start, end).get(entry["currency"], {})
        note = spending.budget_note(entries, entry["currency"])
        return (f"💸 {spending.money(entry['amount'], entry['currency'])} · {entry['what']} ({entry['category']}). "
                f"{label}: {spending.money(sum(month.values()), entry['currency'])}."
                + (f"\n{note}" if note else "") + "\n/spent for the month · /spent undo")

    # --- internet speed -----------------------------------------------------------

    def speed_test(self, args: str) -> str:
        if not security.permissions.ask(security.NETWORK, speedtest.BASE, context="/speedtest"):
            return "Denied. Nothing was measured."
        try:
            result = speedtest.run()
        except speedtest.SpeedError as exc:
            return str(exc)
        security.audit.record("speed test", f"{result['down']:.0f}/{result['up']:.0f} Mbps")
        return "🌐 " + speedtest.describe(result)

    # --- power --------------------------------------------------------------------

    def power(self, args: str, routed: bool = False) -> str:
        action, rest = power.parse(args)
        if action not in power.ACTIONS:
            return ("Usage: /power shutdown|restart [in 30 min | at 23:00]\n"
                    "       /power sleep [in 20 min] · /power lock · /power cancel · /power status")
        if action == "status":
            pending = power.pending()
            if not pending:
                return "Nothing scheduled."
            return f"{pending['action'].capitalize()} at {datetime.fromtimestamp(pending['at']):%H:%M}. /power cancel stops it."
        if action == "cancel":
            removed = reminders.board.cancel_kind("sleep")
            result = power.cancel()
            return result if not removed or "Cancelled" in result else "Cancelled the sleep."
        if action == "lock":
            try:
                power.lock()
            except power.PowerError as exc:
                return str(exc)
            return "🔒 Locked."

        when = time.time()
        if rest:
            parsed = reminders.parse_reminder(rest)
            if parsed is None:
                return f"When? e.g. /power {action} in 30 minutes, or at 23:00"
            when = parsed[0]
        delay = max(0.0, when - time.time())
        moment = "now" if delay < 60 else f"at {datetime.fromtimestamp(when):%H:%M} (in {reminders.describe_seconds(delay)})"
        if not security.permissions.ask(security.RUN_COMMAND, f"{action} this PC {moment}", context="/power"):
            return "Denied. Nothing will happen."
        try:
            if action == "sleep":
                if delay < 60:
                    threading.Timer(3.0, self._sleep_safely).start()
                    return "💤 Going to sleep in 3 seconds."
                reminders.board.cancel_kind("sleep")
                reminders.board.add("sleep", "Sleep the PC", when)
                power._pending.update(action="sleep", at=when)
                return f"💤 I'll put the PC to sleep {moment}, if JARVIS is still open. /power cancel stops it."
            at = power.schedule(action, delay)
        except power.PowerError as exc:
            return str(exc)
        security.audit.record("power", action, moment)
        seconds = max(power.GRACE_SECONDS, round(delay))
        return (f"⏻ {action.capitalize()} in {reminders.describe_seconds(seconds)}"
                f"{'' if delay < 60 else f' (at {datetime.fromtimestamp(at):%H:%M})'}. "
                "Say 'cancel shutdown' or /power cancel to stop it. Save your work.")

    @staticmethod
    def _sleep_safely() -> None:
        try:
            power.sleep_now()
        except power.PowerError:
            pass
