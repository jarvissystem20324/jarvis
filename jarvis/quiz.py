"""Quiz me and flashcards — study from a topic, a file or the open document.

The model writes the questions once, as JSON; after that the quiz runs here.
Multiple choice is graded locally (instant, no request per answer, no model
deciding generously that "B-ish" was right), with the explanation shown after
each answer. Flashcards are saved as a CSV that Anki and Quizlet import.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from .config import get_output_dir

LETTERS = "ABCD"
QUIZ_PROMPT = """Write a multiple-choice quiz of {count} questions {about}.

Return JSON only, a list of objects:
[{{"q": "question", "options": ["...", "...", "...", "..."], "answer": 0, "why": "one-sentence explanation"}}]
- exactly 4 options, "answer" is the index (0-3) of the correct one
- one clearly correct option; plausible wrong ones; vary the correct position
- mix easy and hard; test understanding, not trivia
- write in the language of the topic/material{level}
"""
CARDS_PROMPT = """Make {count} study flashcards {about}.

Return JSON only: [{{"front": "question or term", "back": "short answer"}}]
- one fact or idea per card, backs under 25 words
- write in the language of the topic/material
"""


class QuizError(Exception):
    pass


def parse_json_list(text: str) -> list:
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1)
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        raise QuizError("The questions didn't come back in a usable form. Try again.")
    try:
        data = json.loads(body[start:end + 1])
    except ValueError as exc:
        raise QuizError("The questions didn't come back in a usable form. Try again.") from exc
    return data if isinstance(data, list) else []


def questions_from(text: str) -> list[dict]:
    out = []
    for item in parse_json_list(text):
        try:
            options = [str(o).strip() for o in item["options"]][:4]
            answer = int(item["answer"])
            if len(options) == 4 and 0 <= answer < 4 and str(item["q"]).strip():
                out.append({"q": str(item["q"]).strip(), "options": options,
                            "answer": answer, "why": str(item.get("why", "")).strip()})
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise QuizError("No usable questions came back. Try again, or a narrower topic.")
    return out


def cards_from(text: str) -> list[tuple[str, str]]:
    cards = []
    for item in parse_json_list(text):
        if isinstance(item, dict) and item.get("front") and item.get("back"):
            cards.append((str(item["front"]).strip(), str(item["back"]).strip()))
    if not cards:
        raise QuizError("No flashcards came back. Try again.")
    return cards


@dataclass
class Quiz:
    topic: str
    questions: list[dict]
    index: int = 0
    score: int = 0
    missed: list[dict] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.index >= len(self.questions)

    def ask(self) -> str:
        q = self.questions[self.index]
        options = "\n".join(f"  {LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
        return f"Q{self.index + 1}/{len(self.questions)}. {q['q']}\n{options}"

    def choice(self, reply: str) -> int | None:
        """Which option a reply means: 'b', 'B)', '2', or the option's text."""
        text = reply.strip().strip(".)!").lower()
        text = re.sub(r"^(?:it'?s|answer|option|the answer is|cevap)\s*:?\s*", "", text)
        if len(text) == 1 and text in "abcd":
            return "abcd".index(text)
        if text in {"1", "2", "3", "4"}:
            return int(text) - 1
        options = [o.lower() for o in self.questions[self.index]["options"]]
        if text in options:
            return options.index(text)
        close = [i for i, o in enumerate(options) if len(text) >= 3 and (text in o or o in text)]
        return close[0] if len(close) == 1 else None

    def answer(self, reply: str) -> str:
        pick = self.choice(reply)
        if pick is None:
            return "Answer with A, B, C or D (or 'skip', 'stop')."
        q = self.questions[self.index]
        right = q["answer"]
        if pick == right:
            self.score += 1
            verdict = "✅ Correct."
        else:
            self.missed.append(q)
            verdict = f"❌ It's {LETTERS[right]}) {q['options'][right]}."
        self.index += 1
        return verdict + (f" {q['why']}" if q.get("why") else "")

    def skip(self) -> str:
        q = self.questions[self.index]
        self.missed.append(q)
        self.index += 1
        return f"Skipped. It was {LETTERS[q['answer']]}) {q['options'][q['answer']]}."

    def result(self) -> str:
        answered = self.index
        pct = self.score / answered * 100 if answered else 0
        grade = "🏆 Perfect!" if answered and self.score == answered else "Nice work." if pct >= 70 else "Keep going."
        lines = [f"Score: {self.score}/{answered} ({pct:.0f}%) on {self.topic}. {grade}"]
        if self.missed:
            lines.append("To review:")
            lines += [f"  • {q['q']} → {q['options'][q['answer']]}" for q in self.missed[:10]]
            lines.append("/quiz again retries the ones you missed · /flashcards makes cards")
        return "\n".join(lines)


def save_cards(cards: list[tuple[str, str]], topic: str):
    folder = get_output_dir().parent / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]+", "-", topic, flags=re.UNICODE).strip("-")[:40] or "cards"
    path = folder / f"flashcards_{slug}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        for front, back in cards:
            writer.writerow([front, back])
    return path
