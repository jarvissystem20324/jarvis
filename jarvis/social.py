"""8.0 — Voice, connections and fun: personas, hands-free conversation,
WhatsApp, an inbox summary, Google Calendar, trivia, twenty questions, a
watchlist and fun facts.

Nothing is sent on your behalf: WhatsApp opens with the message typed in and
you press Send; a Google Calendar event opens pre-filled and you press Save.
The inbox is read with an app password over IMAP, marked as unread exactly as
it was (BODY.PEEK), and the password is sealed in the vault, not in .env.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import html
import imaplib
import random
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from . import i18n, kit, quiz as quiz_mod, security, shield
from .registry import command

G = "Voice, connections and fun"
CONTACTS = kit.Store("whatsapp.json", {})
MAIL = kit.Store("mail.json", {})
GCAL = kit.Store("gcal.json", {})
WATCHLIST = kit.Store("watchlist.json", [])
FACTS_SEEN = kit.Store("facts.json", [])
PERSONAS = {
    "coach": "A motivating life and study coach: energetic, practical, holds me accountable, ends with one concrete next step.",
    "teacher": "A patient teacher: explains step by step with simple examples and checks my understanding with a question.",
    "friend": "A warm, casual friend: relaxed tone, a bit of humour, short replies, no lecturing.",
    "comedian": "A stand-up comedian: witty and playful, a joke in most replies — but still actually helpful.",
    "interviewer": "A job interviewer running a realistic mock interview: one question at a time, then feedback on my answer.",
    "debate": "A debate partner: takes the opposing side of what I say, argues it well and fairly, and points out weak spots.",
    "formal": "A formal executive assistant: concise, precise, polite, no small talk.",
    "pirate": "A pirate captain: talks like a pirate, cheerful, still gives correct answers.",
    "storyteller": "A storyteller: answers with vivid little stories and images while staying accurate.",
    "listener": "A supportive listener (not a therapist): empathetic, asks gentle questions, suggests professional help for serious issues.",
}
IMAP_HOSTS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "outlook.com": "outlook.office365.com",
              "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com", "msn.com": "outlook.office365.com",
              "yahoo.com": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
              "yandex.com": "imap.yandex.com", "yandex.com.tr": "imap.yandex.com", "proton.me": "127.0.0.1"}


def _decode(value: str) -> str:
    parts = []
    for text, charset in email.header.decode_header(value or ""):
        parts.append(text.decode(charset or "utf-8", "replace") if isinstance(text, bytes) else text)
    return "".join(parts).strip()


def _body(message) -> str:
    for part in message.walk() if message.is_multipart() else [message]:
        kind = part.get_content_type()
        if kind in {"text/plain", "text/html"} and not part.get_filename():
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", "replace")
            if kind == "text/html":
                text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", " ", text)))
            return re.sub(r"\s+", " ", text).strip()
    return ""


def fetch_mail(account: dict, limit: int = 15, hours: int = 36) -> list[dict]:
    box = imaplib.IMAP4_SSL(account["host"], 993, timeout=20)
    try:
        box.login(account["user"], account["password"])
        box.select("INBOX", readonly=True)
        since = (date.today() - timedelta(hours=hours // 24 or 1)).strftime("%d-%b-%Y")
        _, data = box.search(None, f'(SINCE "{since}")')
        ids = data[0].split()[-limit:]
        mails = []
        for mid in reversed(ids):
            _, parts = box.fetch(mid, "(FLAGS BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            flags = b"".join(p if isinstance(p, bytes) else p[0] for p in parts)
            message = email.message_from_bytes(raw)
            mails.append({"from": _decode(message.get("From", "")), "subject": _decode(message.get("Subject", "")),
                          "date": message.get("Date", ""), "unread": b"\\Seen" not in flags, "body": _body(message)[:700]})
        return mails
    finally:
        try:
            box.logout()
        except Exception:
            pass


def expand_ics(events: list[dict], raw: str, start: datetime, end: datetime) -> list[dict]:
    """Add the occurrences of simple repeating events (RRULE) inside [start, end)."""
    from .life import parse_ics

    unfolded = re.sub(r"\r?\n[ \t]", "", raw)
    out = []
    for block, event in zip(re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.S), parse_ics(raw)):
        rule = re.search(r"^RRULE:(.+)$", block, re.M)
        length = event["end"] - event["start"]
        if not rule:
            if start.timestamp() <= event["start"] < end.timestamp():
                out.append(event)
            continue
        params = dict(p.split("=", 1) for p in rule.group(1).strip().split(";") if "=" in p)
        freq, interval = params.get("FREQ", ""), int(params.get("INTERVAL", 1))
        count = int(params.get("COUNT", 0)) or 10000
        until = None
        if params.get("UNTIL"):
            try:
                until = datetime.strptime(params["UNTIL"][:8], "%Y%m%d") + timedelta(days=1)
            except ValueError:
                until = None
        days = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        byday = [days[d[-2:]] for d in params.get("BYDAY", "").split(",") if d[-2:] in days]
        moment = datetime.fromtimestamp(event["start"])
        n = 0
        while n < count and moment < end and (until is None or moment < until) and n < 2000:
            candidates = [moment]
            if freq == "WEEKLY" and byday:
                week_start = moment - timedelta(days=moment.weekday())      # same time of day
                candidates = [week_start + timedelta(days=d) for d in sorted(byday)]
            for c in candidates:
                if c < datetime.fromtimestamp(event["start"]):
                    continue
                n += 1
                if start <= c < end and (until is None or c < until):
                    out.append({**event, "start": c.timestamp(), "end": c.timestamp() + length})
            step = {"DAILY": timedelta(days=interval), "WEEKLY": timedelta(weeks=interval)}.get(freq)
            if step:
                moment += step
            elif freq == "MONTHLY":
                month = moment.month - 1 + interval
                moment = moment.replace(year=moment.year + month // 12, month=month % 12 + 1)
            elif freq == "YEARLY":
                moment = moment.replace(year=moment.year + interval)
            else:
                break
    return sorted(out, key=lambda e: e["start"])


class Social:
    # --- personas and voice --------------------------------------------------------------

    @command("persona", group=G, usage="/persona coach · /persona <describe one> · /persona off",
             help="changes how JARVIS talks (coach, teacher, friend, interviewer…)")
    def persona(self, args: str, routed: bool = False):
        text = args.strip()
        if not text or text.lower() == "list":
            current = f"\nNow: {self.brain.persona[:80]}" if self.brain.persona else ""
            return "Personas: " + ", ".join(PERSONAS) + "\n/persona <name> · /persona <describe your own> · /persona off" + current
        if text.lower() in {"off", "default", "none", "jarvis", "reset"}:
            self.brain.persona = ""
            return "Back to the usual JARVIS."
        self.brain.persona = PERSONAS.get(text.lower(), text[:600])
        return f"🎭 Persona: {text.lower() if text.lower() in PERSONAS else 'custom'}. /persona off to go back."

    @command("handsfree", "conversation", group=G, usage="/handsfree on|off",
             help="talk back and forth without pressing anything")
    def handsfree(self, args: str, routed: bool = False):
        return "Hands-free needs the window: type /handsfree there (or press the 🎧 button). Say 'stop listening' to end."

    # --- WhatsApp -------------------------------------------------------------------------

    @command("whatsapp", "wa", group=G, usage="/whatsapp <name or number>: <message> · /whatsapp add Ali +90…",
             help="opens WhatsApp with your message typed in; you press Send")
    def whatsapp(self, args: str, routed: bool = False):
        text = args.strip()
        contacts = CONTACTS.load()
        m = re.match(r"^add\s+(.+?)\s+(\+?[\d\s()-]{8,})$", text, re.I)
        if m:
            contacts[m.group(1).strip()] = re.sub(r"\D", "", m.group(2))
            CONTACTS.save(contacts)
            return f"Saved {m.group(1).strip()}."
        if text.lower() in {"", "contacts", "list"}:
            if not contacts:
                return "Usage: /whatsapp add Ali +905551112233, then /whatsapp Ali: running 10 min late"
            return "WhatsApp contacts: " + ", ".join(sorted(contacts))
        who, sep, message = text.partition(":")
        if not sep:
            m = re.match(r"^(\+?\d[\d\s-]{7,})\s+(.+)$", text)
            if not m:
                return "Usage: /whatsapp <name or number>: <message>"
            who, message = m.group(1), m.group(2)
        number = re.sub(r"\D", "", who) if re.search(r"\d{7,}", who.replace(" ", "")) else \
            next((v for k, v in contacts.items() if k.lower() == who.strip().lower()), "")
        if not number:
            return f"I don't have a number for {who.strip()}. /whatsapp add {who.strip()} +90…"
        if number.startswith("0") and len(number) == 11:
            number = "9" + number                  # 05xx… → 905xx…
        query = urllib.parse.urlencode({"phone": number, "text": message.strip()}, quote_via=urllib.parse.quote)
        import os
        import webbrowser

        try:
            os.startfile(f"whatsapp://send?{query}")                     # the desktop app
        except (OSError, AttributeError):
            webbrowser.open(f"https://wa.me/{number}?{urllib.parse.urlencode({'text': message.strip()}, quote_via=urllib.parse.quote)}")
        return f"💬 WhatsApp is open with your message to {who.strip()} — check it and press Send."

    # --- inbox ------------------------------------------------------------------------------

    @command("inbox", "mail", group=G, usage="/inbox · /inbox setup", help="a summary of your latest email (IMAP)")
    def inbox(self, args: str, routed: bool = False):
        account = MAIL.load()
        if args.strip().lower() in {"setup", "set up", "connect"} or not account.get("user"):
            return ("Type /inbox setup and press Enter — I'll ask for your address and an app password in a hidden box.\n"
                    "Gmail: myaccount.google.com/apppasswords (needs 2-step verification). Outlook: account.microsoft.com → "
                    "Security → App passwords.")
        if args.strip().lower() in {"forget", "remove", "disconnect"}:
            MAIL.save({})
            return "Forgot your email account."
        try:
            mails = fetch_mail(account)
        except imaplib.IMAP4.error as exc:
            return f"The mail server refused: {exc}. Check the app password with /inbox setup."
        except OSError as exc:
            return f"Couldn't reach {account.get('host')}: {exc}"
        if not mails:
            return "No email in the last day and a half."
        listing = "\n".join(f"  {'●' if m['unread'] else '○'} {m['from'][:30]} — {m['subject'][:70]}" for m in mails)
        material = "\n\n".join(f"From: {m['from']}\nSubject: {m['subject']}\nUnread: {m['unread']}\n{m['body']}" for m in mails)
        wrapped, warning = shield.wrap(material, "your inbox")
        summary = self.brain.ask_once(f"{shield.RULE}\n\nSummarise my recent email: first anything that needs action or a "
                                      "reply (who, what, by when), then the rest in one line each, and skip newsletters "
                                      f"and promotions in a single line at the end. Be brief.\n\n{wrapped}")
        security.audit.record("inbox", account.get("user", ""), f"{len(mails)} messages")
        return f"📬 {account['user']} — {sum(m['unread'] for m in mails)} unread of {len(mails)} recent\n\n{summary}\n\n{listing}" + \
            (f"\n\n{warning}" if warning else "")

    def setup_inbox(self, address: str, password: str) -> str:
        address = address.strip()
        if "@" not in address or not password:
            return "Setup cancelled."
        domain = address.split("@", 1)[1].lower()
        host = IMAP_HOSTS.get(domain, f"imap.{domain}")
        account = {"user": address, "password": password.replace(" ", ""), "host": host}
        try:
            box = imaplib.IMAP4_SSL(host, 993, timeout=20)
            box.login(account["user"], account["password"])
            box.logout()
        except imaplib.IMAP4.error:
            return ("The server refused that login. Use an app password, not your normal one (Gmail: myaccount.google.com/"
                    "apppasswords; IMAP must be on).")
        except OSError as exc:
            return f"Couldn't reach {host}: {exc}"
        MAIL.save(account)
        security.audit.record("inbox setup", address)
        return f"📬 Connected {address}. /inbox summarises your latest email. The app password is sealed on this PC."

    # --- Google Calendar --------------------------------------------------------------------

    @command("gcal", "googlecalendar", group=G, usage="/gcal [week] · /gcal add <what> <when> · /gcal setup",
             help="your Google Calendar; adding opens a pre-filled event")
    def gcal(self, args: str, routed: bool = False):
        text = args.strip()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            from .life import parse_when

            start, title = parse_when(rest)
            if start is None or not title:
                return "Usage: /gcal add <what> <when>   e.g. /gcal add dentist friday 14:00"
            end = start + timedelta(hours=1)
            utc = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
            url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
                {"action": "TEMPLATE", "text": title, "dates": f"{utc(start)}/{utc(end)}"})
            import webbrowser

            webbrowser.open(url)
            return f"📅 Google Calendar is open with '{title}' on {start:%a %d %b %H:%M} — press Save there."
        if verb.lower() in {"setup", "connect"} or not GCAL.load().get("url"):
            return ("Type /gcal setup and press Enter — I'll ask for your calendar's secret address in a hidden box.\n"
                    "Find it in Google Calendar → Settings → your calendar → Integrate calendar → "
                    "'Secret address in iCal format'. (Read-only; adding opens a pre-filled event for you to save.)")
        if verb.lower() in {"forget", "disconnect"}:
            GCAL.save({})
            return "Forgot your Google Calendar address."
        days = 7 if verb.lower() in {"week", "7"} else 1
        try:
            raw = kit.get_text(GCAL.load()["url"], limit=8_000_000)
        except kit.KitError as exc:
            return str(exc)
        start = datetime.combine(date.today(), datetime.min.time())
        end = start + timedelta(days=days)
        events = expand_ics([], raw, start, end)
        if not events:
            return f"Nothing in your Google Calendar {'this week' if days > 1 else 'today'}."
        lines = [f"📅 Google Calendar — {'next 7 days' if days > 1 else 'today'}:"]
        for e in events[:40]:
            moment = datetime.fromtimestamp(e["start"])
            lines.append(f"  {moment:%a %d %b %H:%M}  {e['title']}" + (f"  @ {e['where']}" if e.get("where") else ""))
        return "\n".join(lines)

    def setup_gcal(self, url: str) -> str:
        url = url.strip()
        if not re.match(r"https://calendar\.google\.com/calendar/ical/.+\.ics$", url):
            return "That doesn't look like the secret iCal address (it starts https://calendar.google.com/calendar/ical/ and ends .ics)."
        try:
            raw = kit.get_text(url, limit=8_000_000)
        except kit.KitError as exc:
            return str(exc)
        if "BEGIN:VCALENDAR" not in raw:
            return "That address didn't return a calendar."
        GCAL.save({"url": url})
        return "📅 Connected. /gcal shows today, /gcal week the next 7 days. The address is sealed on this PC."

    # --- games --------------------------------------------------------------------------------

    @command("trivia", group=G, usage="/trivia [science|history|sports|…] [hard]", help="a 10-question trivia game")
    def trivia(self, args: str, routed: bool = False):
        text = args.strip().lower()
        difficulty = next((d for d in ("easy", "medium", "hard") if d in text), "")
        topic = re.sub(r"\b(easy|medium|hard)\b", "", text).strip() or "general knowledge"
        questions = []
        if i18n.current() != "tr":
            categories = {"general knowledge": 9, "books": 10, "film": 11, "music": 12, "science": 17, "computers": 18,
                          "maths": 19, "math": 19, "sports": 21, "geography": 22, "history": 23, "animals": 27}
            params = {"amount": 10, "type": "multiple"}
            if topic in categories:
                params["category"] = categories[topic]
            if difficulty:
                params["difficulty"] = difficulty
            try:
                data = kit.get_json("https://opentdb.com/api.php", params) if topic in categories else {}
                for item in data.get("results", []):
                    options = [html.unescape(o) for o in item["incorrect_answers"]] + [html.unescape(item["correct_answer"])]
                    random.shuffle(options)
                    questions.append({"q": html.unescape(item["question"]), "options": options,
                                      "answer": options.index(html.unescape(item["correct_answer"])), "why": ""})
            except (kit.KitError, KeyError):
                questions = []
        if len(questions) < 5:
            try:
                with kit.more_room(self.brain):
                    questions = quiz_mod.questions_from(self.brain.ask_once(quiz_mod.QUIZ_PROMPT.format(
                        count=10, about=f"as a fun trivia game about {topic}", level=f"; difficulty: {difficulty or 'mixed'}")))
            except quiz_mod.QuizError as exc:
                return str(exc)
        self._quiz = quiz_mod.Quiz(f"trivia: {topic}", questions)
        self._last_quiz = self._quiz
        return f"🎯 Trivia — {topic}, {len(questions)} questions. Answer A-D.\n\n" + self._quiz.ask()

    @command("20q", "twentyquestions", group=G, usage="/20q", help="think of something; I guess it in 20 questions")
    def twenty_questions(self, args: str, routed: bool = False):
        self._twenty = {"turns": [], "asked": 0}
        self._intercept = self._twenty_reply
        return "🤔 Think of a thing, animal, person or place — don't tell me. Answer yes, no, maybe or don't know.\n\n" + \
            self._twenty_next()

    def _twenty_next(self) -> str:
        state = self._twenty
        history = "\n".join(f"Q{i}: {q} — {a}" for i, (q, a) in enumerate(state["turns"], 1)) or "(nothing yet)"
        try:
            move = kit.ask_json(self.brain, f"""We are playing twenty questions. I am thinking of something; you guess it.
So far:
{history}
Questions used: {state['asked']} of 20. If you're fairly sure, or at question 20, guess.
JSON: {{"question": "a yes/no question"}} or {{"guess": "your guess"}}. Language: {'Turkish' if i18n.current() == 'tr' else 'English'}.""")
        except kit.KitError:
            move = {"question": "Is it something you can hold in your hand?"}
        state["asked"] += 1
        if move.get("guess"):
            state["guess"] = str(move["guess"])
            return f"Q{state['asked']}: Is it… {state['guess']}? (yes / no)"
        state["question"] = str(move.get("question", "Is it alive?"))
        state.pop("guess", None)
        return f"Q{state['asked']}: {state['question']}"

    def _twenty_reply(self, text: str) -> str:
        state = self._twenty
        answer = text.strip().lower()
        if answer in {"stop", "quit", "end", "give up"}:
            self._intercept = None
            return "Game over. What was it? (Tell me and I'll learn nothing — I'm a goldfish between games.)"
        if state.get("guess"):
            if answer.startswith(("y", "e", "evet", "doğru")):
                self._intercept = None
                return f"🎉 Got it in {state['asked']} questions! /20q to play again."
            state["turns"].append((f"Is it {state['guess']}?", "no"))
        else:
            state["turns"].append((state.get("question", ""), text.strip()))
        if state["asked"] >= 20:
            self._intercept = None
            return "😵 20 questions and I'm out. You win! What was it?"
        return self._twenty_next()

    @command("watchlist", "movies", group=G, usage="/watchlist add <title> · /watchlist · /watchlist done <n> 8/10 · /watchlist suggest",
             help="films and series to watch, ratings, suggestions")
    def watchlist(self, args: str, routed: bool = False):
        text = args.strip()
        items = WATCHLIST.load()
        verb, _, rest = text.partition(" ")
        verb = verb.lower()
        if verb == "add" and rest.strip():
            items.append({"title": rest.strip(), "added": time.time(), "watched": False, "rating": None})
            WATCHLIST.save(items)
            return f"🎬 Added {rest.strip()}. {sum(not i['watched'] for i in items)} to watch."
        if verb in {"done", "watched", "seen"}:
            m = re.match(r"(\d+)(?:\s+(\d{1,2})(?:/10)?)?", rest.strip())
            todo = [i for i in items if not i["watched"]]
            if not m or not 1 <= int(m.group(1)) <= len(todo):
                return "Which one? /watchlist shows numbers."
            item = todo[int(m.group(1)) - 1]
            item["watched"], item["rating"] = True, int(m.group(2)) if m.group(2) else None
            WATCHLIST.save(items)
            return f"✔ Watched {item['title']}" + (f" — {item['rating']}/10" if item["rating"] else "") + "."
        if verb in {"delete", "remove"}:
            todo = [i for i in items if not i["watched"]]
            if not rest.strip().isdigit() or not 1 <= int(rest) <= len(todo):
                return "Which one? /watchlist shows numbers."
            items.remove(todo[int(rest) - 1])
            WATCHLIST.save(items)
            return "Removed."
        if verb in {"suggest", "recommend"}:
            liked = [f"{i['title']} ({i['rating']}/10)" for i in items if i["watched"] and (i["rating"] or 0) >= 7]
            listed = [i["title"] for i in items]
            return self.brain.ask_once(f"Recommend 6 films or series. I liked: {', '.join(liked) or 'nothing rated yet'}. "
                                       f"Don't suggest: {', '.join(listed) or '-'}. {rest.strip()}\nFor each: title (year), "
                                       "film or series, one line on why I'd like it.")
        todo = [i for i in items if not i["watched"]]
        seen = [i for i in items if i["watched"]][-8:]
        if not items:
            return "Your watchlist is empty. /watchlist add Dune Part Two · /watchlist suggest"
        lines = ["🎬 To watch:"] + [f"  {n}. {i['title']}" for n, i in enumerate(todo, 1)]
        if seen:
            lines += ["Watched:"] + [f"     {i['title']}" + (f" — {i['rating']}/10" if i["rating"] else "") for i in seen]
        lines.append("/watchlist done <n> 8 · /watchlist suggest")
        return "\n".join(lines)

    @command("funfact", "fact", group=G, usage="/funfact", help="a fun fact")
    def fun_fact(self, args: str, routed: bool = False):
        seen = FACTS_SEEN.load()
        fact = ""
        if i18n.current() != "tr":
            for _ in range(3):
                try:
                    candidate = kit.get_json("https://uselessfacts.jsph.pl/api/v2/facts/random", {"language": "en"}).get("text", "")
                except kit.KitError:
                    break
                if candidate and candidate not in seen:
                    fact = candidate
                    break
        if not fact:
            fact = self.brain.ask_once("Tell me one surprising, true fun fact I probably don't know, in one or two sentences. "
                                       f"Not one of: {'; '.join(seen[-20:]) or '-'}. Language: "
                                       f"{'Turkish' if i18n.current() == 'tr' else 'English'}.").strip()
        seen.append(fact)
        FACTS_SEEN.save(seen[-300:])
        return f"💡 {fact}"
