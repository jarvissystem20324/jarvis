"""8.0 — Study: homework from a photo, exact algebra, dictionary, Wikipedia,
a language tutor, word of the day, spaced flashcard review, exam plans, a
typing test and chapter-by-chapter book summaries.

Exact where it can be: equations are solved by SymPy, definitions come from
real dictionaries (dictionaryapi.dev, TDK), facts from Wikipedia, and the
flashcard schedule is SM-2 worked out here.
"""

from __future__ import annotations

import base64
import difflib
import io
import random
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

from . import i18n, kit, security, shield, writer
from .registry import command

G = "Study"

# --- exact algebra ---------------------------------------------------------------------

_ALLOWED_WORDS = {"sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "exp", "log", "ln", "sqrt",
                  "abs", "pi", "e", "oo", "factorial", "solve", "for", "and", "simplify", "factor", "expand",
                  "derivative", "differentiate", "diff", "integrate", "integral", "of", "limit", "as", "to", "d", "dx",
                  "wrt", "respect", "with", "the", "find", "x", "y", "z"}
_ALGEBRA_CHARS = re.compile(r"^[\w\s+\-*/^().,=<>!²³√π]*$")


class MathError(Exception):
    pass


def _sympify(text: str):
    """Parse maths with SymPy, after refusing anything that isn't maths.

    parse_expr evaluates Python, so the input is first limited to digits,
    operators, single-letter variables and a whitelist of function names:
    no quotes, no underscores, no attribute access — nothing that can reach
    Python itself.
    """
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                            standard_transformations)

    cleaned = text.replace("²", "**2").replace("³", "**3").replace("√", "sqrt").replace("π", "pi").replace("ln(", "log(")
    if "_" in cleaned or not _ALGEBRA_CHARS.match(cleaned):
        raise MathError("That doesn't look like maths I can read.")
    for word in re.findall(r"[A-Za-z]{2,}", cleaned):
        if word.lower() not in _ALLOWED_WORDS:
            raise MathError(f"I don't know '{word}' in an equation.")
    transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
    return parse_expr(cleaned, transformations=transformations, evaluate=True)


def solve_math(text: str) -> str:
    import sympy

    raw = text.strip().rstrip("?.")
    raw = re.sub(r"^(?:solve|find|calculate)\s+(?:for\s+[a-z]\s*:?\s*)?", "", raw, flags=re.I)
    low = raw.lower()
    m = re.match(r"^(?:the\s+)?(?:derivative|differentiate|diff)\s+(?:of\s+)?(.+?)(?:\s+(?:with respect to|wrt|d)\s*([a-z]))?$", low)
    if m:
        expr = _sympify(m.group(1))
        var = sympy.Symbol(m.group(2)) if m.group(2) else (sorted(expr.free_symbols, key=str) or [sympy.Symbol("x")])[0]
        return f"d/d{var} ({sympy.sstr(expr)}) = {sympy.sstr(sympy.simplify(sympy.diff(expr, var)))}"
    m = re.match(r"^(?:the\s+)?(?:integrate|integral)\s+(?:of\s+)?(.+?)(?:\s+from\s+(\S+)\s+to\s+(\S+))?(?:\s+d([a-z]))?$", low)
    if m:
        expr = _sympify(m.group(1))
        var = sympy.Symbol(m.group(4)) if m.group(4) else (sorted(expr.free_symbols, key=str) or [sympy.Symbol("x")])[0]
        if m.group(2):
            value = sympy.integrate(expr, (var, _sympify(m.group(2)), _sympify(m.group(3))))
            return f"∫ {sympy.sstr(expr)} d{var} from {m.group(2)} to {m.group(3)} = {sympy.sstr(sympy.simplify(value))}" + \
                (f" ≈ {float(value):.6g}" if value.is_number and not value.is_Integer else "")
        return f"∫ {sympy.sstr(expr)} d{var} = {sympy.sstr(sympy.integrate(expr, var))} + C"
    m = re.match(r"^(?:the\s+)?limit\s+(?:of\s+)?(.+?)\s+as\s+([a-z])\s+(?:->|to|approaches)\s+(\S+)$", low)
    if m:
        expr = _sympify(m.group(1))
        return f"lim {m.group(2)}→{m.group(3)} {sympy.sstr(expr)} = {sympy.sstr(sympy.limit(expr, sympy.Symbol(m.group(2)), _sympify(m.group(3))))}"
    for verb in ("simplify", "factor", "expand"):
        if low.startswith(verb + " "):
            expr = _sympify(raw[len(verb) + 1:])
            return f"{verb}: {sympy.sstr(getattr(sympy, verb)(expr))}"
    parts = [p for p in re.split(r"\s*(?:,|;|\band\b)\s*", raw) if p.strip()]
    equations = []
    for part in parts:
        if "=" in part:
            left, _, right = part.partition("=")
            equations.append(sympy.Eq(_sympify(left), _sympify(right)))
        else:
            equations.append(sympy.Eq(_sympify(part), 0))
    symbols = sorted(set().union(*(eq.free_symbols for eq in equations)), key=str)
    if not symbols:
        values = [sympy.simplify(eq.lhs - eq.rhs) for eq in equations]
        return "True" if all(v == 0 for v in values) else "False — the two sides differ."
    solutions = sympy.solve(equations if len(equations) > 1 else equations[0], symbols, dict=True)
    if not solutions:
        return "No solution."
    lines = []
    for solution in solutions:
        shown = []
        for var, value in solution.items():
            approx = ""
            if value.is_number and not value.is_Integer and not value.is_Rational:
                try:
                    approx = f" ≈ {complex(value).real:.6g}" if value.is_real else f" ≈ {complex(value):.4g}"
                except (TypeError, ValueError):
                    approx = ""
            shown.append(f"{var} = {sympy.sstr(value)}{approx}")
        lines.append(", ".join(shown))
    return "\n".join(lines)


# --- spaced repetition (SM-2) ------------------------------------------------------------

CARDS = kit.Store("cards.json", {})


def add_cards(deck: str, cards: list[tuple[str, str]]) -> int:
    decks = CARDS.load()
    existing = decks.setdefault(deck[:60], [])
    fronts = {c["front"] for c in existing}
    added = 0
    for front, back in cards:
        if front not in fronts:
            existing.append({"front": front, "back": back, "due": 0, "interval": 0, "ease": 2.5, "reps": 0})
            added += 1
    CARDS.save(decks)
    return added


def grade(card: dict, quality: int, today: date | None = None) -> dict:
    """SM-2: quality 1 (again) .. 4 (easy) mapped onto 0..5."""
    q = {1: 1, 2: 3, 3: 4, 4: 5}[quality]
    today = today or date.today()
    if q < 3:
        card["reps"], card["interval"] = 0, 1
    else:
        card["reps"] += 1
        card["interval"] = 1 if card["reps"] == 1 else 6 if card["reps"] == 2 else round(card["interval"] * card["ease"])
    card["ease"] = max(1.3, card["ease"] + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    card["due"] = (today + timedelta(days=card["interval"])).toordinal()
    return card


def due_cards(decks: dict, deck: str | None = None, today: date | None = None) -> list[tuple[str, int]]:
    day = (today or date.today()).toordinal()
    return [(name, i) for name, cards in decks.items() if deck is None or name.lower() == deck.lower()
            for i, c in enumerate(cards) if c.get("due", 0) <= day]


# --- typing test ----------------------------------------------------------------------------

PASSAGES = {
    "en": ["The quick brown fox jumps over the lazy dog while the sun sets slowly behind the hills.",
           "Good software is written twice: once to make it work, and once to make it clear to the next person.",
           "A small habit repeated every day will beat a big plan that never leaves the notebook.",
           "Typing fast is useful, but typing accurately saves far more time than it costs."],
    "tr": ["Küçük adımlar, her gün tekrarlandığında büyük değişikliklerin başlangıcı olur.",
           "İyi bir yazılım önce çalışır, sonra okunur ve en sonunda da kolayca değiştirilebilir.",
           "Sabah erken kalkan kişi günün sessiz saatlerinde en verimli işlerini bitirir."],
}


def typing_score(passage: str, typed: str, seconds: float) -> tuple[float, float]:
    """(words per minute, accuracy %) — a 'word' is five characters, as is standard."""
    minutes = max(seconds, 1.0) / 60
    matcher = difflib.SequenceMatcher(None, passage, typed)
    accuracy = matcher.ratio() * 100
    return len(typed) / 5 / minutes, accuracy


def chapters_of(text: str, limit: int = 30) -> list[tuple[str, str]]:
    """Split a book into (heading, text) by its chapter headings, or by size."""
    pattern = re.compile(r"^\s*((?:chapter|bölüm|kısım|part)\s+[\w\dIVXLC]+\b.*|#{1,2}\s+.+)$", re.I | re.M)
    marks = [m for m in pattern.finditer(text) if len(m.group(1)) < 90]
    pieces: list[tuple[str, str]] = []
    if len(marks) >= 2:
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            body = text[m.end():end].strip()
            if len(body) > 400:
                pieces.append((m.group(1).strip("# ").strip(), body))
    if len(pieces) < 2:
        size = max(12000, len(text) // limit + 1)
        pieces = [(f"Part {i + 1}", text[s:s + size]) for i, s in enumerate(range(0, len(text), size))]
    return pieces[:limit]


class Study:
    # --- homework and maths -----------------------------------------------------------

    @command("homework", "hw", group=G, usage="/homework [question]",
             help="solves the problem in the last image (or text) step by step")
    def homework(self, args: str, routed: bool = False):
        source = getattr(self, "current_image", None)
        question = args.strip()
        prompt = ("You are a patient tutor. Solve this homework problem step by step, explaining each step so a "
                  "student learns the method. Then give the final answer clearly marked 'Answer:'. If several "
                  "questions are shown, solve each. Answer in the student's language.")
        if source and Path(source).exists() and not (question and len(question) > 40):
            from PIL import Image

            with Image.open(source) as opened:
                image = opened.convert("RGB")
            image.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            security.audit.record("homework", Path(source).name)
            answer = self.brain.ask_once(f"{prompt}\n{question}",
                                         image_b64=base64.b64encode(buffer.getvalue()).decode("ascii"))
        elif question:
            answer = self.brain.ask_once(f"{prompt}\n\nProblem: {question}")
        else:
            return "Drop a photo of the problem into the window (or paste it), then /homework — or /homework <the problem>."
        check = ""
        final = re.search(r"Answer:\s*(.+)", answer)
        if final and "=" in question:
            try:
                check = f"\n\nChecked with SymPy: {solve_math(question)}"
            except Exception:
                pass
        return answer + check

    @command("solve", "equation", group=G, usage="/solve 2x+3=11 · x^2-5x+6=0 · derivative of x^3",
             help="exact algebra and calculus (SymPy)")
    def solve(self, args: str, routed: bool = False):
        if not args.strip():
            return ("Usage: /solve <equation>\n  /solve 2x + 3 = 11      /solve x^2 - 5x + 6 = 0\n"
                    "  /solve x + y = 10, x - y = 2        /solve derivative of x^3 sin(x)\n"
                    "  /solve integrate x^2 from 0 to 3   /solve limit of sin(x)/x as x to 0   /solve factor x^2-9")
        try:
            return solve_math(args)
        except ImportError:
            return "Exact algebra needs SymPy (pip install sympy)."
        except Exception as exc:
            if routed:
                return None
            return f"I couldn't solve that exactly: {exc}"

    # --- words and facts --------------------------------------------------------------

    @command("define", "dictionary", "meaning", group=G, usage="/define <word> [tr]",
             help="dictionary definitions (English, or Turkish from TDK)")
    def define(self, args: str, routed: bool = False):
        word = args.strip()
        turkish = bool(re.search(r"\s+tr$", word)) or bool(re.search(r"[çğıöşüÇĞİÖŞÜ]", word))
        word = re.sub(r"\s+(?:tr|en)$", "", word).strip()
        if not word:
            return "Usage: /define <word>   (Turkish words go to the TDK dictionary)"
        try:
            if turkish:
                data = kit.get_json("https://sozluk.gov.tr/gts", {"ara": word})
                if not isinstance(data, list):
                    return f"TDK has no entry for '{word}'."
                lines = [f"📖 {word} (TDK)"]
                for entry in data[:2]:
                    for i, meaning in enumerate(entry.get("anlamlarListe", [])[:5], 1):
                        lines.append(f"  {i}. {meaning.get('anlam', '')}")
                        for example in meaning.get("orneklerListe", [])[:1]:
                            lines.append(f"     “{example.get('ornek', '')}”")
                return "\n".join(lines)
            data = kit.get_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}")
        except kit.KitError:
            return f"No dictionary entry for '{word}'." if not routed else None
        if not isinstance(data, list):
            return f"No dictionary entry for '{word}'."
        entry = data[0]
        phonetic = entry.get("phonetic") or next((p.get("text") for p in entry.get("phonetics", []) if p.get("text")), "")
        lines = [f"📖 {entry.get('word', word)} {phonetic}".rstrip()]
        for meaning in entry.get("meanings", [])[:3]:
            lines.append(f"  {meaning.get('partOfSpeech', '')}")
            for i, d in enumerate(meaning.get("definitions", [])[:3], 1):
                lines.append(f"    {i}. {d.get('definition', '')}")
                if d.get("example"):
                    lines.append(f"       “{d['example']}”")
            synonyms = meaning.get("synonyms", [])[:6]
            if synonyms:
                lines.append(f"    synonyms: {', '.join(synonyms)}")
        return "\n".join(lines)

    @command("synonyms", "thesaurus", "antonyms", group=G, usage="/synonyms <word>", help="synonyms and antonyms")
    def synonyms(self, args: str, routed: bool = False):
        word = args.strip()
        if not word:
            return "Usage: /synonyms <word>"
        if re.search(r"[çğıöşüÇĞİÖŞÜ]", word) or i18n.current() == "tr" and not re.fullmatch(r"[a-zA-Z ]+", word):
            return self.brain.ask_once(f"Give Turkish synonyms (eş anlamlılar) and antonyms (zıt anlamlılar) of '{word}', "
                                       "as two short comma-separated lists.")
        try:
            same = [w["word"] for w in kit.get_json("https://api.datamuse.com/words", {"rel_syn": word, "max": 15})]
            opposite = [w["word"] for w in kit.get_json("https://api.datamuse.com/words", {"rel_ant": word, "max": 8})]
            similar = [w["word"] for w in kit.get_json("https://api.datamuse.com/words", {"ml": word, "max": 10})]
        except kit.KitError as exc:
            return str(exc)
        lines = [f"Synonyms of '{word}': {', '.join(same) or '—'}"]
        if not same and similar:
            lines = [f"Close in meaning to '{word}': {', '.join(similar)}"]
        lines.append(f"Antonyms: {', '.join(opposite) or '—'}")
        return "\n".join(lines)

    @command("wiki", "wikipedia", group=G, usage="/wiki <topic> [tr]", help="a quick summary from Wikipedia")
    def wiki(self, args: str, routed: bool = False):
        topic = args.strip()
        lang = "tr" if re.search(r"\s+tr$", topic) or i18n.current() == "tr" else "en"
        topic = re.sub(r"\s+(?:tr|en)$", "", topic)
        if not topic:
            return "Usage: /wiki <topic>"
        base = f"https://{lang}.wikipedia.org"
        try:
            found = kit.get_json(f"{base}/w/api.php", {"action": "opensearch", "search": topic, "limit": 1, "format": "json"})
            title = found[1][0] if len(found) > 1 and found[1] else topic
            page = kit.get_json(f"{base}/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}")
        except (kit.KitError, IndexError):
            return f"Wikipedia has no page for '{topic}'." if not routed else None
        extract = page.get("extract") or ""
        if not extract:
            return f"Wikipedia has no summary for '{topic}'."
        link = page.get("content_urls", {}).get("desktop", {}).get("page", f"{base}/wiki/{title}")
        description = f" — {page['description']}" if page.get("description") else ""
        return f"📚 {page.get('title', title)}{description}\n\n{extract}\n\n{link}"

    # --- language tutor ----------------------------------------------------------------

    @command("tutor", group=G, usage="/tutor <language> [A1-C2] · /tutor off",
             help="practise a language by chatting; mistakes are corrected")
    def tutor(self, args: str, routed: bool = False):
        text = args.strip()
        if text.lower() in {"off", "stop", "end"}:
            self.brain.instructions = ""
            return "Tutor mode off."
        if not text:
            return "Usage: /tutor spanish A2   — then just chat. /tutor off to stop."
        level = re.search(r"\b([ABC][12])\b", text, re.I)
        language = re.sub(r"\b[ABC][12]\b", "", text, flags=re.I).strip().title()
        level_text = level.group(1).upper() if level else "B1"
        self.brain.instructions = (
            f"You are my friendly {language} conversation tutor. My level is {level_text}. Always reply in {language} "
            f"at that level, in 2-4 sentences, and end with a question to keep the conversation going. After your "
            f"reply, add a line '✏ Corrections:' listing each mistake in my last message with the fix and a "
            f"one-line reason in English (or 'none'), then '📘 New word:' with one useful word, its meaning and an example.")
        return (f"🗣 Tutor mode: {language} ({level_text}). Write anything in {language} — I'll answer, correct your "
                "mistakes and teach a word each time. /tutor off to stop.")

    @command("word", "wotd", group=G, usage="/word [language]", help="a word of the day to learn")
    def word_of_the_day(self, args: str, routed: bool = False):
        language = args.strip() or "English"
        seen = kit.Store("words.json", []).load()
        try:
            data = kit.ask_json(self.brain, f"""Teach one useful, not-too-common {language} word for an intermediate learner.
Not any of: {', '.join(seen[-60:]) or 'none'}.
JSON: {{"word": "...", "pronunciation": "...", "meaning": "in English and Turkish", "example": "a natural sentence",
"tip": "a memory trick or collocation"}}""")
        except kit.KitError as exc:
            return str(exc)
        seen.append(str(data.get("word", "")))
        kit.Store("words.json", []).save(seen[-500:])
        return (f"📘 Word of the day ({language}): {data.get('word')}  {data.get('pronunciation', '')}\n"
                f"  {data.get('meaning', '')}\n  “{data.get('example', '')}”\n  💡 {data.get('tip', '')}")

    # --- flashcard review -----------------------------------------------------------------

    @command("cards", "review-cards", group=G, usage="/cards · /cards review [deck]",
             help="spaced-repetition review of your flashcards")
    def cards(self, args: str, routed: bool = False):
        text = args.strip()
        decks = CARDS.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() in {"review", "study", "go", "start"} or (text and verb.lower() not in {"delete", "list"}
                                                                 and text.lower() in {d.lower() for d in decks}):
            deck = rest.strip() or (text if verb.lower() not in {"review", "study", "go", "start"} else "") or None
            queue = due_cards(decks, deck)
            if not queue:
                return "Nothing is due. 🎉 Come back tomorrow." if decks else "No cards yet. /flashcards <topic> makes some."
            random.shuffle(queue)
            self._review = {"queue": queue[:50], "showing": False, "done": 0}
            self._intercept = self._review_reply
            return self._review_prompt()
        if verb.lower() == "delete" and rest.strip():
            name = next((d for d in decks if d.lower() == rest.strip().lower()), None)
            if not name:
                return f"No deck called '{rest.strip()}'."
            del decks[name]
            CARDS.save(decks)
            return f"Deleted the deck '{name}'."
        if not decks:
            return "No cards yet. /flashcards <topic or file> makes a deck and adds it here."
        day = date.today().toordinal()
        lines = ["Your decks:"]
        for name, cards in decks.items():
            due = sum(1 for c in cards if c.get("due", 0) <= day)
            lines.append(f"  {name}: {len(cards)} cards, {due} due")
        lines.append("/cards review [deck] starts · /cards delete <deck>")
        return "\n".join(lines)

    def _review_prompt(self) -> str:
        state = self._review
        name, index = state["queue"][0]
        card = CARDS.load()[name][index]
        return f"🃏 ({len(state['queue'])} left · {name})\n\n{card['front']}\n\nThink of the answer, then press Enter (or type it). 'stop' ends."

    def _review_reply(self, text: str) -> str:
        state = self._review
        low = text.strip().lower()
        if low in {"stop", "quit", "end", "exit"}:
            self._intercept = None
            return f"Review stopped. {state['done']} card(s) done."
        decks = CARDS.load()
        name, index = state["queue"][0]
        card = decks[name][index]
        if not state["showing"]:
            state["showing"] = True
            return f"Answer: {card['back']}\n\nHow well did you know it?  1 again · 2 hard · 3 good · 4 easy"
        if low not in {"1", "2", "3", "4"}:
            return "Rate it 1 (again), 2 (hard), 3 (good) or 4 (easy)."
        grade(card, int(low))
        CARDS.save(decks)
        state["queue"].pop(0)
        state["done"] += 1
        state["showing"] = False
        if int(low) == 1:
            state["queue"].append((name, index))
        if not state["queue"]:
            self._intercept = None
            return f"✅ Review done — {state['done']} card(s). See you tomorrow."
        return self._review_prompt()

    # --- planning and practice ----------------------------------------------------------------

    @command("studyplan", "examplan", group=G, usage="/studyplan <exam> on <date> [topics]",
             help="a day-by-day revision plan up to an exam, as a Word file")
    def study_plan(self, args: str, routed: bool = False):
        text = args.strip()
        if not text:
            return "Usage: /studyplan <exam> on <date> [topics, hours a day]   e.g. /studyplan Calculus final on 2026-12-18, 2 hours a day"
        prompt = (f"{writer.PROMPT}\nMake a realistic day-by-day revision plan from today ({date.today():%A %d %B %Y}) "
                  f"to the exam, for: {text}\nInclude: a short strategy, a table (Date | Topics | Tasks | Time) covering "
                  "every day, spaced review of earlier topics, practice exams in the last week, a light last day, and "
                  "tips. Title it '# Study plan: <exam>'.")
        return self._document(prompt, ("docx",))

    @command("typing", "typingtest", group=G, usage="/typing [tr]", help="a typing speed test (WPM and accuracy)")
    def typing_test(self, args: str, routed: bool = False):
        lang = "tr" if args.strip().lower() in {"tr", "turkish", "türkçe"} or (not args.strip() and i18n.current() == "tr") else "en"
        passage = random.choice(PASSAGES[lang])
        self._typing = {"passage": passage, "start": time.time()}
        self._intercept = self._typing_reply
        return f"⌨ Type this exactly, then press Enter. The clock starts now.\n\n{passage}"

    def _typing_reply(self, text: str) -> str:
        state, self._intercept = self._typing, None
        seconds = time.time() - state["start"]
        wpm, accuracy = typing_score(state["passage"], text.strip(), seconds)
        verdict = "🔥 Excellent!" if wpm >= 60 and accuracy > 95 else "👍 Good." if wpm >= 35 else "Keep practising."
        return f"{wpm:.0f} WPM · {accuracy:.0f}% accurate · {seconds:.1f}s. {verdict}  /typing for another."

    @command("chapters", "booksummary", group=G, usage="/chapters <book.pdf|epub|txt|docx>",
             help="a chapter-by-chapter summary of a book, as a Word file")
    def chapters(self, args: str, routed: bool = False):
        path = kit.path_arg(args)
        doc = self._document_addon()
        if path is None or doc is None:
            return "Usage: /chapters <book file>   (PDF, Word or text)"
        if not security.permissions.ask(security.READ_FILE, str(path), context="/chapters"):
            return "Denied. The book was not read."
        try:
            text = doc._extract(path)
        except Exception as exc:
            return f"Couldn't read {path.name}: {exc}"
        pieces = chapters_of(text)
        sections = [f"# {path.stem}: chapter summaries"]
        for heading, body in pieces:
            wrapped, _ = shield.wrap(body[:24000], path.name)
            summary = self.brain.ask_once(f"{shield.RULE}\n\nSummarise this part of a book in 4-7 bullet points "
                                          f"(plot or argument, key ideas, names). Bullets only.\n\n{wrapped}")
            sections.append(f"## {heading}\n\n{summary.strip()}")
        markdown = "\n\n".join(sections)
        try:
            paths = writer.save(markdown, ("docx",))
        except writer.WriterError as exc:
            return str(exc)
        security.audit.record("chapters", path.name, f"{len(pieces)} parts")
        return f"📚 {len(pieces)} chapter summaries of {path.name}:\n  {paths[0]}"
