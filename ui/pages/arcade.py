"""The Arcade (10.0): chess against JARVIS, Snake, 2048, the daily word game
in Turkish and English, and the emoji quiz.

The rules are in jarvis/chess.py and jarvis/games.py; this page only draws
them on Tk canvases and turns keys and clicks into moves. Each game is built
the first time it is picked, and the engine's chess moves are worked out on
a worker thread so the board never freezes while JARVIS thinks.
"""

from __future__ import annotations

import tkinter

import customtkinter as ctk

from jarvis import chess, games, prefs
from ui.pages.base import Hub, button, label, plain, text_font

GAMES = (("chess", "♟ Chess"), ("snake", "🐍 Snake"), ("2048", "🔢 2048"), ("word", "🔤 Word"),
         ("emoji", "🤔 Emoji quiz"))


class ArcadePage(Hub):
    key = "arcade"
    title = "Arcade"
    icon = "🕹"
    subtitle = "Chess against JARVIS, Snake, 2048, the daily word game in Türkçe and English, and an emoji quiz."
    columns = 1

    def build_body(self) -> None:
        self.picker = ctk.CTkSegmentedButton(self.body, values=[name for _, name in GAMES],
                                             command=lambda v: self.pick(dict((n, k) for k, n in GAMES)[v]))
        self.place(self.picker)
        self.stage = plain(self.body)
        self.place(self.stage)
        self.games: dict[str, tkinter.Frame] = {}
        self.current = ""
        self.pick("chess")

    def pick(self, key: str, option: str = "") -> None:
        for game in self.games.values():
            game.pack_forget()
            if hasattr(game, "pause"):
                game.pause()
        if key not in self.games:
            self.games[key] = {"chess": ChessGame, "snake": SnakeGame, "2048": Game2048View,
                               "word": WordView, "emoji": EmojiQuiz}[key](self.stage, self)
        game = self.games[key]
        game.pack(fill="both", expand=True)
        self.current = key
        self.picker.set(dict(GAMES)[key])
        if option and hasattr(game, "option"):
            game.option(option)
        self.after(50, game.focus_game)

    def open_target(self, part: str) -> None:
        key, _, option = part.partition("/")
        if key in dict(GAMES):
            self.pick(key, option)

    def on_hide(self) -> None:
        for game in self.games.values():
            if hasattr(game, "pause"):
                game.pause()


class _Game(tkinter.Frame):
    def __init__(self, parent, page: ArcadePage) -> None:
        super().__init__(parent, bg=page.colors["panel"], bd=0, highlightthickness=0)
        self.page = page
        self.c = page.colors

    def focus_game(self) -> None:
        canvas = getattr(self, "canvas", None)
        if canvas is not None:
            canvas.focus_set()

    def _bind_keys(self, widget, handler) -> None:
        for key in ("Up", "Down", "Left", "Right"):
            widget.bind(f"<{key}>", lambda e, k=key.lower(): handler(k))
        for key, direction in (("w", "up"), ("s", "down"), ("a", "left"), ("d", "right")):
            widget.bind(f"<KeyPress-{key}>", lambda e, d=direction: handler(d))


# --- chess -------------------------------------------------------------------------------------------

class ChessGame(_Game):
    SIZE = 62
    LIGHT, DARK = "#ebecd0", "#779556"

    def __init__(self, parent, page) -> None:
        super().__init__(parent, page)
        c = self.c
        self.board = chess.Board()
        self.level = "medium"
        self.human = "w"
        self.flipped = False
        self.selected: int | None = None
        self.thinking = False
        self.canvas = tkinter.Canvas(self, width=self.SIZE * 8, height=self.SIZE * 8, bg=c["panel"],
                                     highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left", padx=16, pady=16)
        self.canvas.bind("<Button-1>", self.click)
        side = plain(self)
        side.pack(side="left", fill="both", expand=True, pady=16)
        self.status = label(side, "", size=14, bold=True, wrap=320)
        self.status.pack(anchor="w")
        row = plain(side)
        row.pack(fill="x", pady=8)
        self.level_menu = ctk.CTkOptionMenu(row, values=["easy", "medium", "hard"], width=100, fg_color=c["bg"],
                                            button_color=c["accent_dim"], command=self.set_level)
        self.level_menu.set(self.level)
        self.level_menu.pack(side="left")
        button(row, "New (White)", lambda: self.new("w"), height=28).pack(side="left", padx=4)
        button(row, "New (Black)", lambda: self.new("b"), height=28).pack(side="left")
        row = plain(side)
        row.pack(fill="x")
        button(row, "↶ Undo", self.undo, height=28).pack(side="left")
        button(row, "⇅ Flip", self.flip, height=28).pack(side="left", padx=4)
        self.moves = tkinter.Text(side, height=14, width=36, wrap="word", bd=0, bg=c["bg"], fg=c["text"],
                                  font=text_font(self, 12)[0], highlightthickness=0)
        self.moves.pack(fill="both", expand=True, pady=(10, 0))
        self.font = ("Segoe UI Symbol", int(self.SIZE * 0.6))
        self.draw()
        self.say()

    def option(self, value: str) -> None:
        if value in chess.LEVELS:
            self.set_level(value)
            self.level_menu.set(value)

    def set_level(self, value: str) -> None:
        self.level = value

    def new(self, side: str) -> None:
        if self.thinking:
            return
        self.board = chess.Board()
        self.human = side
        self.flipped = side == "b"
        self.selected = None
        self.draw()
        self.say()
        if side == "b":
            self.reply()

    def flip(self) -> None:
        self.flipped = not self.flipped
        self.draw()

    def undo(self) -> None:
        if self.thinking or not self.board.moves_played:
            return
        self.board.pop()
        if self.board.moves_played and self.board.turn != self.human:
            self.board.pop()
        self.selected = None
        self.draw()
        self.say()

    def _xy(self, sq: int) -> tuple[int, int]:
        f, r = sq % 8, sq // 8
        if self.flipped:
            return (7 - f) * self.SIZE, r * self.SIZE
        return f * self.SIZE, (7 - r) * self.SIZE

    def _square_at(self, x: int, y: int) -> int | None:
        f, row = x // self.SIZE, y // self.SIZE
        if not (0 <= f < 8 and 0 <= row < 8):
            return None
        return (row * 8 + 7 - f) if self.flipped else ((7 - row) * 8 + f)

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        last = self.board.moves_played[-1] if self.board.moves_played else None
        targets = {m.end for m in self.board.legal_moves() if m.start == self.selected} if self.selected is not None \
            else set()
        check = self.board.king(self.board.turn) if self.board.in_check() else None
        for sq in range(64):
            x, y = self._xy(sq)
            light = (sq % 8 + sq // 8) % 2 == 1
            colour = self.LIGHT if light else self.DARK
            if last is not None and sq in (last.start, last.end):
                colour = "#f5f682" if light else "#b9ca43"
            if sq == self.selected:
                colour = "#82c3f5"
            if sq == check:
                colour = "#e06666"
            canvas.create_rectangle(x, y, x + self.SIZE, y + self.SIZE, fill=colour, width=0)
            piece = self.board.squares[sq]
            if piece != ".":
                glyph = chess.GLYPHS[piece.lower()]          # the solid shapes, coloured by side
                cx, cy = x + self.SIZE // 2, y + self.SIZE // 2 + 2
                fill, edge = ("#ffffff", "#202020") if piece.isupper() else ("#1b1b1b", "#d8d8d8")
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    canvas.create_text(cx + dx, cy + dy, text=glyph, font=self.font, fill=edge)
                canvas.create_text(cx, cy, text=glyph, font=self.font, fill=fill)
            if sq in targets:
                r = self.SIZE // 7 if piece == "." else self.SIZE // 2 - 3
                width = 0 if piece == "." else 4
                canvas.create_oval(x + self.SIZE / 2 - r, y + self.SIZE / 2 - r, x + self.SIZE / 2 + r,
                                   y + self.SIZE / 2 + r, fill="#1e293b" if piece == "." else "",
                                   outline="#1e293b", width=width, stipple="gray50" if piece == "." else "")
        for i in range(8):           # coordinates along two edges
            file_sq = i if not self.flipped else 7 - i
            canvas.create_text(i * self.SIZE + self.SIZE - 6, 8 * self.SIZE - 7, text=chess.FILES[file_sq],
                               font=("Segoe UI", 8, "bold"), fill="#4b5563", anchor="e")
            rank = 8 - i if not self.flipped else i + 1
            canvas.create_text(4, i * self.SIZE + 8, text=str(rank), font=("Segoe UI", 8, "bold"), fill="#4b5563",
                               anchor="w")

    def say(self) -> None:
        outcome = self.board.outcome()
        if outcome:
            self.status.configure(text=outcome[0].upper() + outcome[1:] + ".")
        elif self.thinking:
            self.status.configure(text="JARVIS is thinking…")
        elif self.board.turn == self.human:
            self.status.configure(text="Your move" + (" — check!" if self.board.in_check() else "."))
        self.moves.configure(state="normal")
        self.moves.delete("1.0", "end")
        replay = chess.Board()
        parts = []
        for i, move in enumerate(self.board.moves_played):
            text = replay.san(move)
            parts.append(f"{i // 2 + 1}. {text}" if i % 2 == 0 else text)
            replay.push(move)
        self.moves.insert("1.0", "  ".join(parts))
        self.moves.configure(state="disabled")
        self.moves.see("end")

    def click(self, event) -> None:
        if self.thinking or self.board.turn != self.human or self.board.outcome():
            return
        sq = self._square_at(event.x, event.y)
        if sq is None:
            return
        piece = self.board.squares[sq]
        mine = piece != "." and chess.Board.colour_of(piece) == self.human
        if self.selected is not None and not mine:
            moves = [m for m in self.board.legal_moves() if m.start == self.selected and m.end == sq]
            if moves:
                move = next((m for m in moves if m.promo in {"", "q"}), moves[0])   # promotions become queens
                self.board.push(move)
                self.selected = None
                self.draw()
                self.say()
                if not self.board.outcome():
                    self.reply()
                return
        self.selected = sq if mine and sq != self.selected else None
        self.draw()

    def reply(self) -> None:
        self.thinking = True
        self.say()
        engine = chess.Engine(self.level)
        position = chess.Board(self.board.fen())
        position.seen = dict(self.board.seen)

        def done(move):
            self.thinking = False
            if isinstance(move, chess.Move) and self.board.fen() == position.fen():
                self.board.push(move)
            self.draw()
            self.say()

        self.page.run(lambda: engine.choose(position), done, lambda exc: done(None))


# --- Snake -------------------------------------------------------------------------------------------

class SnakeGame(_Game):
    CELL = 24

    def __init__(self, parent, page) -> None:
        super().__init__(parent, page)
        self.game = games.Snake()
        self.running = False
        self._job = None
        top = plain(self)
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.score = label(top, "", size=14, bold=True)
        self.score.pack(side="left")
        button(top, "▶ Play", self.start, accent=True, height=28).pack(side="right")
        self.canvas = tkinter.Canvas(self, width=self.game.width * self.CELL, height=self.game.height * self.CELL,
                                     bg=self.c["bg"], highlightthickness=0)
        self.canvas.pack(padx=16, pady=12, anchor="w")
        self._bind_keys(self.canvas, self.game_turn)
        self.canvas.bind("<space>", lambda e: self.toggle())
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())
        self.draw()

    def game_turn(self, direction: str) -> None:
        if not self.running and self.game.alive:
            self.running = True
            self.tick()
        self.game.turn(direction)

    def start(self) -> None:
        self.pause()
        self.game = games.Snake()
        self.running = True
        self.canvas.focus_set()
        self.tick()

    def toggle(self) -> None:
        if self.running:
            self.pause()
        elif self.game.alive:
            self.running = True
            self.tick()

    def pause(self) -> None:
        self.running = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tkinter.TclError:
                pass
            self._job = None

    def tick(self) -> None:
        self._job = None
        if not self.running:
            return
        if not self.game.step():
            self.running = False
            best = prefs.get("best_snake", 0)
            if self.game.score > best:
                prefs.set("best_snake", self.game.score)
        self.draw()
        if self.running:
            self._job = self.after(self.game.delay(), self.tick)

    def draw(self) -> None:
        c, size, canvas = self.c, self.CELL, self.canvas
        canvas.delete("all")
        if self.game.food is not None:
            fx, fy = self.game.food
            canvas.create_oval(fx * size + 4, fy * size + 4, fx * size + size - 4, fy * size + size - 4,
                               fill="#f87171", width=0)
        for i, (x, y) in enumerate(self.game.body):
            canvas.create_rectangle(x * size + 1, y * size + 1, x * size + size - 1, y * size + size - 1,
                                    fill=c["accent"] if i == 0 else c["accent_dim"], width=0)
        best = max(prefs.get("best_snake", 0), self.game.score)
        self.score.configure(text=f"Score {self.game.score}   ·   Best {best}")
        if not self.game.alive:
            canvas.create_text(self.game.width * size / 2, self.game.height * size / 2, fill=c["text"],
                               text="Game over — press Play", font=("Segoe UI", 20, "bold"))
        elif not self.running:
            canvas.create_text(self.game.width * size / 2, self.game.height * size / 2, fill=c["muted"],
                               text="Arrow keys or Play to start · Space pauses", font=("Segoe UI", 13))


# --- 2048 --------------------------------------------------------------------------------------------

TILE_COLOURS = {0: "#cdc1b4", 2: "#eee4da", 4: "#ede0c8", 8: "#f2b179", 16: "#f59563", 32: "#f67c5f", 64: "#f65e3b",
                128: "#edcf72", 256: "#edcc61", 512: "#edc850", 1024: "#edc53f", 2048: "#edc22e"}


class Game2048View(_Game):
    TILE = 96

    def __init__(self, parent, page) -> None:
        super().__init__(parent, page)
        self.game = games.Game2048()
        top = plain(self)
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.score = label(top, "", size=14, bold=True)
        self.score.pack(side="left")
        button(top, "New game", self.new, height=28).pack(side="right")
        side = self.TILE * 4 + 10 * 5
        self.canvas = tkinter.Canvas(self, width=side, height=side, bg="#bbada0", highlightthickness=0)
        self.canvas.pack(padx=16, pady=12, anchor="w")
        self._bind_keys(self.canvas, self.slide)
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())
        self.note = label(self, "Arrow keys (or WASD) slide every tile; equal tiles merge.", size=11, muted=True)
        self.note.pack(anchor="w", padx=16, pady=(0, 12))
        self.draw()

    def new(self) -> None:
        self.game = games.Game2048()
        self.canvas.focus_set()
        self.draw()

    def slide(self, direction: str) -> None:
        if self.game.over():
            return
        if self.game.move(direction):
            best = prefs.get("best_2048", 0)
            if self.game.score > best:
                prefs.set("best_2048", self.game.score)
            self.draw()

    def draw(self) -> None:
        canvas, tile, gap = self.canvas, self.TILE, 10
        canvas.delete("all")
        for r in range(4):
            for col in range(4):
                value = self.game.grid[r][col]
                x, y = gap + col * (tile + gap), gap + r * (tile + gap)
                canvas.create_rectangle(x, y, x + tile, y + tile, fill=TILE_COLOURS.get(value, "#3c3a32"), width=0)
                if value:
                    size = 32 if value < 100 else 26 if value < 1000 else 20
                    canvas.create_text(x + tile / 2, y + tile / 2, text=str(value),
                                       font=("Segoe UI", size, "bold"), fill="#776e65" if value <= 4 else "#f9f6f2")
        best = max(prefs.get("best_2048", 0), self.game.score)
        self.score.configure(text=f"Score {self.game.score}   ·   Best {best}" + ("   🏆 2048!" if self.game.won else ""))
        if self.game.over():
            side = tile * 4 + gap * 5
            canvas.create_rectangle(0, 0, side, side, fill="#eee4da", stipple="gray50", width=0)
            canvas.create_text(side / 2, side / 2, text="No moves left", font=("Segoe UI", 24, "bold"),
                               fill="#776e65")


# --- the word game ------------------------------------------------------------------------------------

KEYBOARDS = {"tr": ("ertyuıopğü", "asdfghjklşi", "zcvbnmöç"), "en": ("qwertyuiop", "asdfghjkl", "zxcvbnm")}
MARK_COLOURS = {"green": "#538d4e", "yellow": "#b59f3b", "grey": "#3a3a3c"}


class WordView(_Game):
    def __init__(self, parent, page) -> None:
        super().__init__(parent, page)
        c = self.c
        self.lang = "tr"
        self.typed = ""
        top = plain(self)
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.lang_switch = ctk.CTkSegmentedButton(top, values=["Türkçe", "English"],
                                                  command=lambda v: self.set_lang("tr" if v == "Türkçe" else "en"))
        self.lang_switch.set("Türkçe")
        self.lang_switch.pack(side="left")
        button(top, "⧉ Share", self.share, height=28).pack(side="right")
        self.status = label(self, "", size=13, bold=True)
        self.status.pack(anchor="w", padx=16, pady=(8, 0))
        self.grid_box = tkinter.Frame(self, bg=c["panel"])
        self.grid_box.pack(anchor="w", padx=16, pady=8)
        font = ("Segoe UI", 20, "bold")
        self.cells = [[tkinter.Label(self.grid_box, text="", width=3, height=1, font=font, bg=c["bg"], fg="#ffffff",
                                     bd=0) for _ in range(5)] for _ in range(6)]
        for r, row in enumerate(self.cells):
            for col, cell in enumerate(row):
                cell.grid(row=r, column=col, padx=3, pady=3, ipady=6)
        self.keys_box = tkinter.Frame(self, bg=c["panel"])
        self.keys_box.pack(anchor="w", padx=16, pady=(4, 14))
        self.canvas = self.grid_box       # what gets the keyboard focus
        self.grid_box.configure(takefocus=1)
        self.grid_box.bind("<Key>", self.key)
        self.grid_box.bind("<Button-1>", lambda e: self.grid_box.focus_set())
        self.set_lang("tr")

    def set_lang(self, lang: str) -> None:
        self.lang = lang
        self.game = games.WordGame(lang)
        self.typed = ""
        self.draw_keys()
        self.draw()
        self.grid_box.focus_set()

    def draw_keys(self) -> None:
        for child in self.keys_box.winfo_children():
            child.destroy()
        self.key_buttons: dict[str, tkinter.Label] = {}
        font = ("Segoe UI", 12, "bold")
        rows = KEYBOARDS[self.lang]
        for r, letters in enumerate(rows):
            line = tkinter.Frame(self.keys_box, bg=self.c["panel"])
            line.pack(anchor="w", padx=(r * 14, 0), pady=2)
            if r == 2:
                self._key(line, "Enter", "Gir" if self.lang == "tr" else "Enter", font, 6)
            for letter in letters:
                self.key_buttons[letter] = self._key(line, letter, games.upper(letter, self.lang), font, 3)
            if r == 2:
                self._key(line, "BackSpace", "⌫", font, 5)

    def _key(self, parent, value: str, text: str, font, width: int) -> tkinter.Label:
        key = tkinter.Label(parent, text=text, width=width, font=font, bg="#818384", fg="#ffffff", bd=0,
                            cursor="hand2")
        key.pack(side="left", padx=2, ipady=6)
        key.bind("<Button-1>", lambda e, v=value: self.press(v))
        return key

    def key(self, event) -> None:
        if event.keysym in {"Return", "KP_Enter"}:
            self.press("Enter")
        elif event.keysym == "BackSpace":
            self.press("BackSpace")
        elif event.char and event.char.strip():
            self.press(games.lower(event.char, self.lang))

    def press(self, value: str) -> None:
        if self.game.done:
            return
        if value == "Enter":
            if len(self.typed) < 5:
                self.status.configure(text="Beş harf yaz." if self.lang == "tr" else "Five letters, please.")
                return
            problem = self.game.guess(self.typed)
            if problem:
                self.status.configure(text=problem)
                return
            self.typed = ""
        elif value == "BackSpace":
            self.typed = self.typed[:-1]
        elif len(value) == 1 and value in "".join(KEYBOARDS[self.lang]) and len(self.typed) < 5:
            self.typed += value
        self.draw()

    def draw(self) -> None:
        tr = self.lang == "tr"
        rows = self.game.grid()
        for r in range(6):
            for col in range(5):
                cell = self.cells[r][col]
                if r < len(rows):
                    letter, mark = rows[r][col]
                    cell.configure(text=letter, bg=MARK_COLOURS[mark])
                elif r == len(rows) and col < len(self.typed) and not self.game.done:
                    cell.configure(text=games.upper(self.typed[col], self.lang), bg="#565758")
                else:
                    cell.configure(text="", bg=self.c["bg"])
        states = self.game.letter_states()
        for letter, key in self.key_buttons.items():
            key.configure(bg=MARK_COLOURS[states[letter]] if letter in states else "#818384")
        if self.game.won:
            text = (f"🎉 Bildin! {len(self.game.guesses)}/6 · seri {games.streak(self.lang)} gün" if tr else
                    f"🎉 Got it in {len(self.game.guesses)}/6 · streak {games.streak(self.lang)}")
        elif self.game.done:
            text = (f"Kelime: {games.upper(self.game.answer, self.lang)} — yarın yeni kelime" if tr else
                    f"It was {self.game.answer.upper()} — a new word tomorrow")
        else:
            text = "Günün kelimesi: 5 harf, 6 hak. Yaz ve Enter'a bas." if tr else \
                "Today's word: 5 letters, 6 tries. Type and press Enter."
        self.status.configure(text=text)

    def share(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.game.share())
        self.status.configure(text="Panoya kopyalandı." if self.lang == "tr" else "Copied to the clipboard.")


# --- the emoji quiz -----------------------------------------------------------------------------------

class EmojiQuiz(_Game):
    def __init__(self, parent, page) -> None:
        super().__init__(parent, page)
        c = self.c
        top = plain(self)
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.lang_switch = ctk.CTkSegmentedButton(top, values=["All", "Türkçe", "English"],
                                                  command=lambda v: self.new_round())
        self.lang_switch.set("All")
        self.lang_switch.pack(side="left")
        button(top, "New round", self.new_round, height=28).pack(side="right")
        self.progress = label(self, "", size=12, muted=True)
        self.progress.pack(anchor="w", padx=16, pady=(10, 0))
        self.picture = tkinter.Label(self, bg=c["panel"], fg=c["text"], font=("Segoe UI Emoji", 44), bd=0)
        self.picture.pack(anchor="w", padx=16, pady=8)
        self.category = label(self, "", size=12, muted=True)
        self.category.pack(anchor="w", padx=16)
        row = plain(self)
        row.pack(fill="x", padx=16, pady=8)
        self.entry = ctk.CTkEntry(row, placeholder_text="Your answer…", width=380, fg_color=c["bg"])
        self.entry.pack(side="left")
        self.entry.bind("<Return>", lambda e: self.answer())
        button(row, "Check", self.answer, accent=True, height=28).pack(side="left", padx=6)
        button(row, "Skip", self.skip, height=28).pack(side="left")
        self.feedback = label(self, "", size=13, bold=True)
        self.feedback.pack(anchor="w", padx=16, pady=(0, 14))
        self.new_round()

    def focus_game(self) -> None:
        self.entry.focus_set()

    def new_round(self) -> None:
        lang = {"Türkçe": "tr", "English": "en"}.get(self.lang_switch.get(), "all")
        self.round = games.quiz_round(lang, 10)
        self.index = 0
        self.right = 0
        self.feedback.configure(text="")
        self.show()

    def show(self) -> None:
        if self.index >= len(self.round):
            self.picture.configure(text="🏁", image="")
            self.category.configure(text="")
            self.progress.configure(text=f"Round over: {self.right} of {len(self.round)} right.")
            return
        puzzle = self.round[self.index]
        image = self._picture(puzzle[0])
        self.picture.configure(image=image or "", text="" if image else puzzle[0])
        self._image = image
        self.category.configure(text=puzzle[3])
        self.progress.configure(text=f"{self.index + 1} of {len(self.round)}   ·   {self.right} right")
        self.entry.delete(0, "end")

    def _picture(self, emojis: str):
        """The whole clue in colour, drawn by Pillow from the Windows emoji font."""
        from ui.pages.base import _EMOJI_FONT

        if not _EMOJI_FONT.exists():
            return None
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageTk

            glyphs = emojis.replace("️", "").replace("‍", "")
            font = ImageFont.truetype(str(_EMOJI_FONT), 56)
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            left, top, right, bottom = probe.textbbox((0, 0), glyphs, font=font, embedded_color=True)
            picture = Image.new("RGBA", (right - left + 8, bottom - top + 8), (0, 0, 0, 0))
            ImageDraw.Draw(picture).text((4 - left, 4 - top), glyphs, font=font, embedded_color=True)
            return ImageTk.PhotoImage(picture, master=self)
        except Exception:
            return None

    def answer(self) -> None:
        if self.index >= len(self.round):
            return
        puzzle = self.round[self.index]
        if games.check_answer(self.entry.get(), puzzle):
            self.right += 1
            self.feedback.configure(text=f"✅ Yes — {puzzle[1]}!", text_color=self.c["ok"])
            self.index += 1
            self.show()
        else:
            self.feedback.configure(text="❌ Not quite — try again or Skip.", text_color=self.c["error"])

    def skip(self) -> None:
        if self.index < len(self.round):
            self.feedback.configure(text=f"It was: {self.round[self.index][1]}", text_color=self.c["muted"])
            self.index += 1
            self.show()
