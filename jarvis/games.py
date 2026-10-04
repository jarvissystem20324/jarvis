"""The Arcade's games (10.0): 2048, Snake, the daily word game in Turkish
and English, and the emoji quiz. Only the rules live here — the Arcade page
draws them, and the word game and quiz can also be played in the chat.
"""

from __future__ import annotations

import difflib
import hashlib
import random
import re
from datetime import date

from . import kit

# --- 2048 ------------------------------------------------------------------------------------------


class Game2048:
    def __init__(self, size: int = 4, seed: int | None = None) -> None:
        self.size = size
        self.rng = random.Random(seed)
        self.grid = [[0] * size for _ in range(size)]
        self.score = 0
        self.won = False
        self.spawn()
        self.spawn()

    def spawn(self) -> None:
        empty = [(r, c) for r in range(self.size) for c in range(self.size) if not self.grid[r][c]]
        if empty:
            r, c = self.rng.choice(empty)
            self.grid[r][c] = 4 if self.rng.random() < 0.1 else 2

    @staticmethod
    def slide(row: list[int]) -> tuple[list[int], int]:
        """One row pushed left: [2, 2, 4, 0] → [4, 4, 0, 0], scoring 4. Each tile merges once."""
        tiles = [v for v in row if v]
        out, gained, i = [], 0, 0
        while i < len(tiles):
            if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
                out.append(tiles[i] * 2)
                gained += tiles[i] * 2
                i += 2
            else:
                out.append(tiles[i])
                i += 1
        return out + [0] * (len(row) - len(out)), gained

    def move(self, direction: str) -> bool:
        """Slide every tile left/right/up/down; False if nothing moved."""
        n = self.size
        if direction in {"left", "right"}:
            lines = [list(row) for row in self.grid]
        else:
            lines = [[self.grid[r][c] for r in range(n)] for c in range(n)]
        if direction in {"right", "down"}:
            lines = [line[::-1] for line in lines]
        moved, gained = False, 0
        result = []
        for line in lines:
            new, points = self.slide(line)
            moved |= new != line
            gained += points
            result.append(new)
        if not moved:
            return False
        if direction in {"right", "down"}:
            result = [line[::-1] for line in result]
        if direction in {"left", "right"}:
            self.grid = result
        else:
            self.grid = [[result[c][r] for c in range(n)] for r in range(n)]
        self.score += gained
        self.won |= any(v >= 2048 for row in self.grid for v in row)
        self.spawn()
        return True

    def over(self) -> bool:
        n = self.size
        for r in range(n):
            for c in range(n):
                v = self.grid[r][c]
                if not v or (c + 1 < n and self.grid[r][c + 1] == v) or (r + 1 < n and self.grid[r + 1][c] == v):
                    return False
        return True


# --- Snake ------------------------------------------------------------------------------------------

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class Snake:
    def __init__(self, width: int = 24, height: int = 16, seed: int | None = None) -> None:
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        mid = (width // 2, height // 2)
        self.body = [mid, (mid[0] - 1, mid[1]), (mid[0] - 2, mid[1])]   # head first
        self.direction = "right"
        self._queued: list[str] = []
        self.score = 0
        self.alive = True
        self.food = self._place_food()

    def _place_food(self) -> tuple[int, int] | None:
        free = [(x, y) for x in range(self.width) for y in range(self.height) if (x, y) not in self.body]
        return self.rng.choice(free) if free else None

    def turn(self, direction: str) -> None:
        """Queue a turn; reversing straight into yourself is ignored, as in every Snake."""
        last = self._queued[-1] if self._queued else self.direction
        dx, dy = DIRECTIONS[direction]
        lx, ly = DIRECTIONS[last]
        if (dx, dy) != (-lx, -ly) and direction != last and len(self._queued) < 3:
            self._queued.append(direction)

    def step(self) -> bool:
        """Move one square; False once the snake has hit a wall or itself."""
        if not self.alive:
            return False
        if self._queued:
            self.direction = self._queued.pop(0)
        dx, dy = DIRECTIONS[self.direction]
        head = (self.body[0][0] + dx, self.body[0][1] + dy)
        eating = head == self.food
        body = self.body if eating else self.body[:-1]
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height) or head in body:
            self.alive = False
            return False
        self.body = [head] + body
        if eating:
            self.score += 1
            self.food = self._place_food()
        return True

    def delay(self) -> int:
        """Milliseconds between steps: quicker as it grows."""
        return max(55, 140 - self.score * 4)


# --- the daily word game ----------------------------------------------------------------------------

_EN = """apple beach bread brain chair cloud crane dance dream earth eagle field flame fruit ghost glass
grape green heart horse house juice knife laugh lemon light magic money mouse music night ocean paint
party peace piano pilot plant queen radio river robot salad sheep shirt smile snake space spoon sport
storm sugar sunny table tiger toast tower train truck water whale world write zebra actor adult alarm
album angel anger angle apron arrow badge baker beard bench berry blade blank blaze bloom board boost
brave brick bride brush cabin cable camel candy canoe cargo chalk charm chess chest chief child clock
coast coral couch cream crown cycle daisy depth diary dough draft drama drink eager elbow enjoy entry
fable faith fancy feast fence fever flock flour focus forge frame fresh frost giant glove grain grass
guard guest guide happy honey hotel humor image index jelly jewel joint kayak koala label lucky lunch
maple march medal metal minor model mango nerve noble novel nurse olive orbit otter owner panda paper
pearl phone photo pizza plaza pride prize proud puppy quiet quilt raven ready relax rhyme ruler scale
scarf scene shark shell shine skate skill slide smoke solar sound spark spice spine squad stage stamp
steam stone sweet swing teach thumb trail treat trust tulip uncle unity value video vivid voice wagon
wheat wheel witty woman yacht young youth"""

_TR = """kitap kalem deniz bulut güneş çiçek araba elmas armut kiraz limon şeker çorba ekmek simit börek
kebap pilav salça tatlı kahve sabah akşam öğlen hafta yayla orman nehir liman köprü sokak cadde şehir
çarşı pazar fırın sınıf hocam sınav kağıt silgi çanta resim müzik şarkı türkü davul zurna gitar keman
sahne hakem takım yarış yüzme dalış kayak tekne vapur metro taksi bilet yolcu şoför pilot asker polis
hakim terzi memur müdür prens saray duvar bahçe salon yatak dolap perde lamba kablo ekran radyo video
haber dergi roman masal yazar sanat bilim tarih kimya fizik rakam bölme kesir üçgen daire hacim dünya
roket gölge yeşil beyaz siyah pembe altın gümüş bakır demir çelik çamur buzul sıcak soğuk serin nemli
ıslak temiz kirli güzel büyük küçük geniş derin hafif hızlı yavaş kolay yaşlı mutlu üzgün sakin cesur
nazik kibar komik ciddi tuzlu tadım duygu sevgi komşu teyze kuzen bebek çocuk oğlan kadın insan vatan
zafer barış savaş hukuk kanun kural düzen model örnek fikir bilgi cevap sorun çözüm fiyat kredi banka
vergi hesap sepet poşet paket kargo adres tatil çadır fener burun boğaz zirve şahin serçe tavuk horoz
ördek köpek koyun aslan tilki geyik kirpi yılan balık yunus sinek böcek kavun çilek incir ceviz badem
biber soğan havuç marul nohut sucuk köfte döner mantı lokum helva ayran"""

TR_LOWER = str.maketrans("ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ", "abcçdefgğhıijklmnoöprsştuüvyz")
TR_UPPER = str.maketrans("abcçdefgğhıijklmnoöprsştuüvyz", "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ")


def words(lang: str) -> list[str]:
    raw = _TR if lang == "tr" else _EN
    seen, out = set(), []
    for word in raw.split():
        if len(word) == 5 and word not in seen:
            seen.add(word)
            out.append(word)
    return out


def lower(text: str, lang: str) -> str:
    return text.translate(TR_LOWER) if lang == "tr" else text.lower()


def upper(text: str, lang: str) -> str:
    return text.translate(TR_UPPER) if lang == "tr" else text.upper()


def daily_word(lang: str, day: date | None = None) -> str:
    """The same word for everyone on the same day (and a different one tomorrow)."""
    day = day or date.today()
    pool = words(lang)
    digest = hashlib.sha256(f"jarvis-word-{lang}-{day.isoformat()}".encode()).hexdigest()
    return pool[int(digest, 16) % len(pool)]


def score_guess(guess: str, answer: str) -> list[str]:
    """Per letter: "green" (right place), "yellow" (elsewhere), "grey" — with
    repeated letters counted as often as the answer has them."""
    marks = ["grey"] * len(guess)
    left: dict[str, int] = {}
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            marks[i] = "green"
        else:
            left[a] = left.get(a, 0) + 1
    for i, g in enumerate(guess):
        if marks[i] != "green" and left.get(g, 0):
            marks[i] = "yellow"
            left[g] -= 1
    return marks


WORD_GAMES = kit.Store("word_game.json", {})
TILES = {"green": "🟩", "yellow": "🟨", "grey": "⬛"}


class WordGame:
    """Today's game in one language: six guesses, kept across restarts."""

    def __init__(self, lang: str = "tr", day: date | None = None) -> None:
        self.lang = lang
        self.day = (day or date.today()).isoformat()
        self.answer = daily_word(lang, day)
        saved = WORD_GAMES.load().get(f"{lang}:{self.day}", {})
        self.guesses: list[str] = saved.get("guesses", [])

    @property
    def won(self) -> bool:
        return bool(self.guesses) and self.guesses[-1] == self.answer

    @property
    def done(self) -> bool:
        return self.won or len(self.guesses) >= 6

    def guess(self, word: str) -> str:
        """"" if taken; otherwise why it wasn't."""
        word = lower(word.strip(), self.lang)
        letters = "a-zçğıöşü" if self.lang == "tr" else "a-z"
        if self.done:
            return "Today's game is over — come back tomorrow."
        if not re.fullmatch(f"[{letters}]{{5}}", word):
            return "Five letters, please."
        if word in self.guesses:
            return "You've tried that one."
        self.guesses.append(word)
        data = WORD_GAMES.load()
        data[f"{self.lang}:{self.day}"] = {"guesses": self.guesses}
        WORD_GAMES.save(data)
        return ""

    def grid(self) -> list[list[tuple[str, str]]]:
        return [list(zip(upper(g, self.lang), score_guess(g, self.answer))) for g in self.guesses]

    def letter_states(self) -> dict[str, str]:
        """The best each letter has done so far, for colouring a keyboard."""
        rank = {"grey": 0, "yellow": 1, "green": 2}
        out: dict[str, str] = {}
        for g in self.guesses:
            for letter, mark in zip(g, score_guess(g, self.answer)):
                if letter not in out or rank[mark] > rank[out[letter]]:
                    out[letter] = mark
        return out

    def share(self) -> str:
        title = "Kelime" if self.lang == "tr" else "Word"
        result = f"{len(self.guesses)}/6" if self.won else "X/6"
        return f"JARVIS {title} {self.day} {result}\n" + "\n".join(
            "".join(TILES[m] for m in score_guess(g, self.answer)) for g in self.guesses)


def streak(lang: str, today: date | None = None) -> int:
    from datetime import timedelta

    data = WORD_GAMES.load()
    day = today or date.today()
    count = 0
    while True:
        saved = data.get(f"{lang}:{day.isoformat()}")
        if not saved or not saved.get("guesses") or saved["guesses"][-1] != daily_word(lang, day):
            if day == (today or date.today()):
                day -= timedelta(days=1)     # today not played yet doesn't break the streak
                continue
            return count
        count += 1
        day -= timedelta(days=1)


# --- the emoji quiz ---------------------------------------------------------------------------------

PUZZLES = [
    # (emojis, answer, other accepted answers, category, language)
    ("🦁👑", "The Lion King", ("Aslan Kral",), "film", "en"),
    ("🕷️🧑", "Spider-Man", ("Örümcek Adam", "spiderman"), "film", "en"),
    ("❄️👸", "Frozen", ("Karlar Ülkesi",), "film", "en"),
    ("🚢🧊💔", "Titanic", (), "film", "en"),
    ("🦖🏝️", "Jurassic Park", (), "film", "en"),
    ("🧸🤠🚀", "Toy Story", ("Oyuncak Hikayesi",), "film", "en"),
    ("🐠🔍", "Finding Nemo", ("Kayıp Balık Nemo", "Nemo"), "film", "en"),
    ("⚡👓🧙", "Harry Potter", (), "film", "en"),
    ("👽📞🏠", "E.T.", ("ET",), "film", "en"),
    ("🐼🥋", "Kung Fu Panda", (), "film", "en"),
    ("🐭👨‍🍳", "Ratatouille", ("Ratatuy",), "film", "en"),
    ("🦈🌊", "Jaws", (), "film", "en"),
    ("🤖❤️🌱", "WALL-E", ("Wall E",), "film", "en"),
    ("🧙‍♂️💍🌋", "The Lord of the Rings", ("Yüzüklerin Efendisi", "Lord of the Rings"), "film", "en"),
    ("🏴‍☠️🌊⚓", "Pirates of the Caribbean", ("Karayip Korsanları",), "film", "en"),
    ("🍫🏭", "Charlie and the Chocolate Factory", ("Charlie'nin Çikolata Fabrikası",), "film", "en"),
    ("⏰💰", "Time is money", (), "saying", "en"),
    ("🍎📅👨‍⚕️", "An apple a day keeps the doctor away", (), "saying", "en"),
    ("🐦✋🌳", "A bird in the hand is worth two in the bush", (), "saying", "en"),
    ("🌧️🐱🐶", "It's raining cats and dogs", ("raining cats and dogs",), "saying", "en"),
    ("💧💧🌊", "Damlaya damlaya göl olur", (), "atasözü", "tr"),
    ("🌊🐍🤝", "Denize düşen yılana sarılır", (), "atasözü", "tr"),
    ("🍯👅🐍🕳️", "Tatlı dil yılanı deliğinden çıkarır", (), "atasözü", "tr"),
    ("👀↔️❤️", "Gözden ırak olan gönülden de ırak olur", ("Gözden ırak gönülden ırak",), "atasözü", "tr"),
    ("🍐⬇️🌳", "Armut dibine düşer", (), "atasözü", "tr"),
    ("🧠⬆️🧠", "Akıl akıldan üstündür", (), "atasözü", "tr"),
    ("⏰🌅🚶", "Erken kalkan yol alır", (), "atasözü", "tr"),
    ("🐱🍖🙅", "Kedi uzanamadığı ciğere mundar der", (), "atasözü", "tr"),
    ("🐺🐺⛰️", "Kurtlar Vadisi", (), "dizi", "tr"),
    ("🏫😂👨‍🎓", "Hababam Sınıfı", (), "film", "tr"),
    ("👽🛸😂", "G.O.R.A.", ("Gora",), "film", "tr"),
    ("👨👦❤️", "Babam ve Oğlum", (), "film", "tr"),
    ("🦋💭", "Kelebeğin Rüyası", (), "film", "tr"),
    ("👑💯📅", "Muhteşem Yüzyıl", (), "dizi", "tr"),
]


def _fold(text: str) -> str:
    text = text.lower().translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    return " ".join(text.split())


def check_answer(guess: str, puzzle: tuple) -> bool:
    """Right if it matches the answer or an alternative, ignoring case, accents,
    punctuation and "the" — and forgiving a typo or two."""
    said = _fold(guess)
    if not said:
        return False
    for option in (puzzle[1], *puzzle[2]):
        want = _fold(option)
        if said == want or difflib.SequenceMatcher(None, said, want).ratio() >= 0.85:
            return True
    return False


def quiz_round(lang: str = "all", count: int = 10, seed: int | None = None) -> list[tuple]:
    pool = [p for p in PUZZLES if lang == "all" or p[4] == lang]
    rng = random.Random(seed)
    return rng.sample(pool, min(count, len(pool)))
