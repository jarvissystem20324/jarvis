"""13.4.2: learning and the future — a coding tutor that explains your errors
and sets small exercises, a spoken language partner that corrects you, and a
university and career explorer with sources."""

from __future__ import annotations

import re

from .. import kit, shield
from ..registry import command, field, split, split_free

G = "Learn"

LANGUAGES = {"english": "en", "turkish": "tr", "türkçe": "tr", "ingilizce": "en", "german": "de", "almanca": "de",
             "deutsch": "de", "french": "fr", "fransızca": "fr", "spanish": "es", "ispanyolca": "es", "italian": "it",
             "italyanca": "it", "portuguese": "pt", "dutch": "nl", "russian": "ru", "rusça": "ru", "arabic": "ar",
             "arapça": "ar", "japanese": "ja", "japonca": "ja", "chinese": "zh", "çince": "zh", "korean": "ko",
             "korece": "ko", "hindi": "hi", "azerbaijani": "az", "polish": "pl", "ukrainian": "uk", "persian": "fa",
             "greek": "el", "swedish": "sv"}

ERROR_HINTS = re.compile(r"traceback|error|exception|errno|undefined|not defined|cannot|can't|failed|"
                         r"syntaxerror|typeerror|nameerror|hata", re.I)
CODE_HINTS = re.compile(r"\b(def|class|import|return|function|const|let|var|public|static|void|#include|for|while)\b|[{};]")


def language_code(name: str) -> str | None:
    word = (name or "").strip().lower()
    if word in LANGUAGES.values():
        return word
    return LANGUAGES.get(word)


def sourced(jarvis, request: str, queries: list[str], how: str, limit: int = 6) -> str:
    """Search, read the top pages, and answer with numbered sources."""
    from .. import websearch

    found, seen = [], set()
    for query in queries:
        try:
            results = websearch.search(query, limit=4)
        except Exception:
            continue
        for item in results:
            if item.url not in seen:
                seen.add(item.url)
                found.append(item)
    sources = []
    for item in found[:limit + 2]:
        if len(sources) >= limit:
            break
        try:
            title, text = websearch.fetch(item.url)
        except Exception:
            title, text = item.title, item.snippet
        if text.strip():
            sources.append((title or item.title, item.url, text[:3500]))
    if not sources:
        material = "(no web results — answer from general knowledge and say clearly that it must be checked)"
    else:
        material = "\n\n".join(f"[{i}] {t} — {u}\n{shield.wrap(x, u)[0]}" for i, (t, u, x) in enumerate(sources, 1))
    with kit.more_room(jarvis.brain, 3500):
        answer = jarvis.brain.ask_once(
            f"{shield.RULE}\n{how}\nRequest: {request}\nCite facts with source numbers like [1]. Requirements, fees "
            "and deadlines change every year: say so and point to the official page. Same language as the "
            f"request.\n\n{material}")
    legend = "\n".join(f"  [{i}] {t[:70]} — {u}" for i, (t, u, _x) in enumerate(sources, 1))
    return answer.strip() + (f"\n\nSources:\n{legend}" if legend else "")


class Learn:
    # --- coding tutor -------------------------------------------------------------------

    @command("codetutor", "explainerror", "codecoach", group=G, usage="/codetutor <error, code or topic> · "
             "/codetutor check <your answer>", help="a coding tutor: explains your error in plain words, shows the "
             "fix, and gives you small exercises", title="Coding tutor", icon="🧑\u200d🏫", page="study",
             fields=(field("what", "long", "Your error message, code, or a topic",
                           hint="paste a traceback · a function · “python lists”"),
                     field("language", "text", "Language (optional)", optional=True, hint="Python")),
             keywords="programming learn error explain exercise python javascript")
    def codetutor_cmd(self, args: str, routed: bool = False):
        what, language = split_free(args, 2)
        what = what.strip()
        if not what:
            return ("Usage: /codetutor <paste your error or code, or name a topic>\n"
                    "Then try the exercise and send it with /codetutor check <your code>.")
        lang = language.strip() or "the language the code is in (Python if unsure)"
        if what.lower().startswith("check "):
            exercise = getattr(self, "_code_exercise", "")
            if not exercise:
                return "No exercise yet. /codetutor <topic> gives you one."
            answer, _ = shield.wrap(what[6:], "the student's answer")
            return self.brain.ask_once(
                f"{shield.RULE}\nYou are a patient coding tutor for an 18-20 year old. The exercise was:\n{exercise}\n\n"
                f"Their answer:\n{answer}\n\nSay if it works (trace it on an example), what is good, the one most "
                "important thing to improve, and a hint — not the full solution — if it is wrong. End with a "
                "slightly harder follow-up exercise.").strip()
        material, _ = shield.wrap(what[:12000], "the student's code or error")
        if ERROR_HINTS.search(what):
            task = ("Explain this error in plain words: what it means, the line that causes it and why, and the fix "
                    "(a short corrected snippet). Then teach the idea behind it in 3 lines.")
        elif CODE_HINTS.search(what) and "\n" in what:
            task = ("Explain what this code does, step by step but briefly, point out bugs or bad habits with "
                    "fixes, and suggest one improvement.")
        else:
            task = "Teach this topic briefly with one tiny example."
        reply = self.brain.ask_once(
            f"{shield.RULE}\nYou are a patient coding tutor for an 18-20 year old learning {lang}. {task}\n"
            "Finish with a section '🏋 Exercises' with two small exercises (easy, then a bit harder) that practise "
            "exactly this, with example input and output but no solutions.\n\n" + material).strip()
        self._code_exercise = reply.split("🏋", 1)[-1][:3000] if "🏋" in reply else reply[-1500:]
        return reply + "\n\nSend your attempt with /codetutor check <your code>."

    # --- spoken language partner ------------------------------------------------------------

    @command("partner", "languagepartner", "speakpractice", group=G, usage="/partner <language> [A1-C2] · "
             "/partner off", help="spoken language practice: talk, JARVIS answers out loud in that language and "
             "corrects your mistakes", title="Language partner (spoken)", icon="🗣", page="study",
             fields=(field("language", "text", "Language", "English"),
                     field("level", "choice", "Level", "B1", ("A1", "A2", "B1", "B2", "C1", "C2")),
                     field("topic", "text", "Topic (optional)", optional=True, hint="travel, job interview, …")),
             keywords="speak practice conversation pronunciation voice tutor")
    def partner_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower() in {"off", "stop", "end", "kapat"}:
            self.brain.instructions = ""
            self.speak_language = None
            self.partner_on = False
            return "🗣 Language partner off. Voice replies are back to normal."
        if "|" in text:
            language, level, topic = split(text, 3)
        else:
            words = text.split()
            language = words[0] if words else "English"
            level = next((w for w in words[1:] if re.fullmatch(r"[ABC][12]", w, re.I)), "")
            topic = " ".join(w for w in words[1:] if w != level)
        level_match = re.search(r"\b([ABC][12])\b", level or "", re.I)
        level_text = level_match.group(1).upper() if level_match else "B1"
        name = (language or "English").strip().title()
        code = language_code(name)
        if code is None:
            return f"I don't have a voice for {name}. Try English, German, French, Spanish, Italian, Arabic, Japanese…"
        self.speak_language = code
        self.partner_on = True
        self.voice_enabled = True
        self.brain.instructions = (
            f"You are my spoken {name} conversation partner. My level is {level_text}. "
            + (f"We talk about: {topic.strip()}. " if topic.strip() else "")
            + f"Always answer in {name} at my level in 1-3 short spoken sentences (no lists, no emojis, no "
            "markdown — they are read aloud), and end with a question. My messages come from speech recognition, "
            "so ignore missing punctuation. After your answer add a new line starting with '✏' and list my "
            "grammar or word mistakes as 'wrong → right' in English, or '✏ none'.")
        return (f"🗣 Language partner: {name} ({level_text}). Speak to me — hold the push-to-talk key or press "
                f"🎧 Hands-free — and I'll answer out loud in {name} and show your mistakes after ✏. "
                "/partner off to stop.")

    def spoken_part(self, text: str) -> str:
        """What is read aloud: in partner mode, the answer without the corrections."""
        if getattr(self, "partner_on", False):
            return text.split("✏", 1)[0].strip()
        return text

    # --- university and career -------------------------------------------------------------

    @command("uni", "university", "universities", group=G, usage="/uni <what to study> | [country or city] | "
             "[your scores]", help="university programmes for what you want to study: requirements, scores, "
             "deadlines — with sources", title="University explorer", icon="🎓", page="study",
             fields=(field("subject", "text", "What you want to study", "Computer engineering"),
                     field("where", "text", "Where", optional=True, hint="Türkiye, Istanbul, Germany, UK…"),
                     field("scores", "text", "Your scores (optional)", optional=True,
                           hint="YKS rank 25000 · IELTS 7 · SAT 1400")),
             keywords="university college programme yks sat ielts admission scholarship")
    def uni_cmd(self, args: str, routed: bool = False):
        subject, where, scores = split_free(args, 3)
        if not subject.strip():
            return "Usage: /uni computer engineering | Istanbul | YKS rank 30000"
        request = f"Study {subject.strip()}" + (f" in {where.strip()}" if where.strip() else "") + \
            (f"; the student's scores: {scores.strip()}" if scores.strip() else "")
        place = where.strip() or "Türkiye"
        queries = [f"{subject} programme {place} admission requirements", f"{subject} {place} university ranking",
                   f"{subject} {place} application deadline scholarship"]
        if re.search(r"türk|turk|istanbul|ankara|izmir", place, re.I):
            queries.append(f"{subject} YKS taban puan başarı sırası")
        return "🎓 " + sourced(self, request, queries,
                              "Suggest 4-6 suitable university programmes. For each: university, programme, "
                              "language of teaching, entry requirements (score or rank, language test), fees if "
                              "stated, deadline. Then: which are a reach / a match / safe for the student's scores "
                              "if given, and 3 next steps.")

    @command("career", "careers", group=G, usage="/career <job or field> | [country]",
             help="a career explored: what the work is, skills, pay, how to start — with sources",
             title="Career explorer", icon="🧭", page="study",
             fields=(field("field", "text", "Job or field", "Data scientist"),
                     field("where", "text", "Country", "Türkiye", optional=True)),
             keywords="job career salary skills internship future")
    def career_cmd(self, args: str, routed: bool = False):
        job, where = split_free(args, 2)
        if not job.strip():
            return "Usage: /career data scientist | Türkiye"
        place = where.strip() or "Türkiye"
        return "🧭 " + sourced(self, f"{job.strip()} in {place}",
                              [f"{job} career path skills", f"{job} salary {place}", f"{job} internship {place}"],
                              "Explain this career for an 18-20 year old: what the work is day to day, the skills "
                              "and tools, which degrees lead there, starting and mid-career pay in the country "
                              "(say which year the figure is from), and a 6-month plan to get a first internship.")

    @command("internshipcv", "internshipresume", group=G, usage="/internshipcv <your details> | <role>",
             help="a one-page internship CV in Word and PDF, built around your projects and skills",
             title="Internship CV", icon="📄", page="study",
             fields=(field("details", "long", "Everything about you",
                           hint="name, school, year, projects, skills, languages, clubs, email"),
                     field("role", "text", "Internship you want", "Software engineering intern", optional=True)),
             keywords="cv resume internship staj application")
    def internshipcv_cmd(self, args: str, routed: bool = False):
        details, role = split_free(args, 2)
        if not details.strip():
            return "Usage: /internshipcv <your details> | <the internship you want>"
        from .. import writer

        return self._document(f"""{writer.PROMPT}
Write a one-page internship CV for a student{f' applying for: {role.strip()}' if role.strip() else ''}.
With little work experience, lead with a 2-line profile aimed at the role, then Projects (what was built, the tools,
the result with numbers when given), Education (school, programme, expected graduation, relevant courses),
Skills (grouped), Activities and volunteering, Languages, and a contact line at the top. Strong action verbs.
Never invent employers, dates, grades or results.
Details: {details.strip()}""")
