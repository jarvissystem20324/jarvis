"""10.0 Arcade: chess rules checked against the standard perft counts, the
engine finds mates, and the other games' rules."""

from __future__ import annotations

import pytest

from jarvis import chess

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POSITION3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POSITION4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"


@pytest.mark.parametrize("fen,depth,count", [
    (chess.START, 1, 20), (chess.START, 2, 400), (chess.START, 3, 8902),
    (KIWIPETE, 1, 48), (KIWIPETE, 2, 2039),          # castling, en passant, pins
    (POSITION3, 1, 14), (POSITION3, 2, 191), (POSITION3, 3, 2812),   # en passant across checks
    (POSITION4, 1, 6), (POSITION4, 2, 264),          # promotions under check
])
def test_move_generation_matches_perft(fen, depth, count):
    board = chess.Board(fen)
    assert chess.perft(board, depth) == count
    assert board.fen() == fen          # push and pop leave the board exactly as it was


def test_notation_and_special_moves():
    board = chess.Board()
    for text in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"):
        board.push(board.parse(text))
    assert board.san(board.parse("O-O")) == "O-O"
    board.push(board.parse("e1g1"))
    assert board.squares[chess.square("f1")] == "R" and "K" not in board.castling
    ep = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    move = ep.parse("exd6")
    assert ep.san(move) == "exd6"
    ep.push(move)
    assert ep.squares[chess.square("d5")] == "." and ep.squares[chess.square("d6")] == "P"
    promo = chess.Board("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert promo.san(promo.parse("a7a8q")) == "a8=Q"


def test_the_end_of_a_game():
    mate = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")   # fool's mate
    assert mate.outcome() == "checkmate — Black wins"
    assert chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").outcome() == "stalemate — a draw"
    assert "not enough" in chess.Board("8/8/4k3/8/8/3NK3/8/8 w - - 0 1").outcome()
    board = chess.Board()
    for _ in range(2):
        for text in ("Nf3", "Nf6", "Ng1", "Ng8"):
            board.push(board.parse(text))
    assert "three times" in board.outcome()


@pytest.mark.parametrize("level", ["easy", "medium", "hard"])
def test_the_engine_takes_a_mate_in_one(level):
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")      # Rd8#
    move = chess.Engine(level).choose(board)
    assert board.san(move) == "Rd8#"


@pytest.mark.parametrize("level", ["medium", "hard"])
def test_the_engine_doesnt_hang_its_queen(level):
    # The rook attacks the queen, and the king guards the rook: Qxd2 loses the queen.
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 b - - 0 1")
    board.push(chess.Engine(level).choose(board))
    queen = board.squares.index("q")
    assert not [m for m in board.legal_moves() if m.end == queen]


# --- the other games ------------------------------------------------------------------------------

from jarvis import games  # noqa: E402


def test_2048_slides_and_merges_each_tile_once():
    assert games.Game2048.slide([2, 2, 4, 0]) == ([4, 4, 0, 0], 4)
    assert games.Game2048.slide([2, 2, 2, 2]) == ([4, 4, 0, 0], 8)
    assert games.Game2048.slide([4, 0, 0, 4]) == ([8, 0, 0, 0], 8)
    game = games.Game2048(seed=1)
    game.grid = [[2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    assert game.move("right") and game.grid[0][3] == 4 and game.score == 4
    assert sum(v > 0 for row in game.grid for v in row) == 2        # the merged tile and a new one
    game.grid = [[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]]
    assert game.over() and not game.move("left")


def test_snake_eats_grows_and_dies_at_the_wall():
    snake = games.Snake(width=8, height=5, seed=3)
    snake.food = (snake.body[0][0] + 1, snake.body[0][1])
    assert snake.step() and snake.score == 1 and len(snake.body) == 4
    snake.turn("left")                      # straight back into itself: ignored
    assert snake._queued == []
    while snake.step():
        pass
    assert not snake.alive and snake.body[0][0] == 7
    assert games.Snake().delay() > games.Snake().delay() - 1


def test_the_word_game_scores_repeated_letters_like_wordle():
    assert games.score_guess("speed", "abide") == ["grey", "grey", "yellow", "grey", "yellow"]
    assert games.score_guess("eerie", "there") == ["yellow", "grey", "yellow", "grey", "green"]
    assert games.score_guess("kalem", "kalem") == ["green"] * 5
    for lang in ("tr", "en"):
        pool = games.words(lang)
        assert len(pool) >= 150 and all(len(w) == 5 for w in pool)
        assert games.daily_word(lang) == games.daily_word(lang) and games.daily_word(lang) in pool
    assert games.upper("ışık", "tr") == "IŞIK" and games.upper("iyi", "tr") == "İYİ"
    assert games.lower("İSTANBUL", "tr") == "istanbul"


def test_a_daily_word_game_is_kept_and_shared(base):
    from datetime import date

    day = date(2026, 10, 4)
    game = games.WordGame("tr", day)
    wrong = next(w for w in games.words("tr") if w != game.answer)
    assert game.guess("abc") == "Five letters, please."
    assert game.guess(wrong) == "" and game.guess(wrong) == "You've tried that one."
    assert game.guess(games.upper(game.answer, "tr")) == "" and game.won and game.done
    again = games.WordGame("tr", day)
    assert again.guesses == [wrong, game.answer] and again.won
    assert again.share().endswith("🟩🟩🟩🟩🟩") and "2/6" in again.share()
    assert games.WordGame("en", day).guesses == []


def test_emoji_answers_forgive_case_accents_and_typos():
    lion = next(p for p in games.PUZZLES if p[1] == "The Lion King")
    assert games.check_answer("lion king", lion) and games.check_answer("Aslan kral", lion)
    assert games.check_answer("the lion kng", lion) and not games.check_answer("tiger", lion)
    proverb = next(p for p in games.PUZZLES if p[1].startswith("Damlaya"))
    assert games.check_answer("damlaya damlaya gol olur", proverb)
    assert len(games.quiz_round("tr", 5, seed=1)) == 5 and all(p[4] == "tr" for p in games.quiz_round("tr", 5))


def test_the_game_commands(base):
    from jarvis.ten import play

    p = play.Play()
    reply = p.chess_cmd("hard")
    assert reply.open_page == "arcade:chess/hard"
    assert p.snake_cmd("").open_page == "arcade:snake" and p.game2048_cmd("").open_page == "arcade:2048"
    board = p.kelime_cmd("")
    assert "Günün kelimesi" in board and "6 hakkın kaldı" in board
    assert "Beş harfli" in p.kelime_cmd("ab")
    asked = p.emojiquiz_cmd("")
    assert "What is it?" in asked
    puzzle = play._quiz
    assert p.emojiquiz_cmd(puzzle[1]).startswith("✅")


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_arcade_page(app, monkeypatch):
    app._show_tab("arcade")
    app.update()
    page = app.pages["arcade"]
    board = page.games["chess"]
    monkeypatch.setattr(board.page, "run", lambda work, done, error=None: done(work()))
    size = board.SIZE
    e2, e4 = chess.square("e2"), chess.square("e4")
    for sq in (e2, e4):
        x, y = board._xy(sq)
        board.click(type("E", (), {"x": x + size // 2, "y": y + size // 2})())
    assert board.board.moves_played[0] == chess.Move(e2, e4)
    assert len(board.board.moves_played) == 2          # JARVIS answered
    board.undo()
    assert board.board.moves_played == []
    app.follow_page(type("R", (), {"open_page": "arcade:2048"})())
    assert page.current == "2048"
    view = page.games["2048"]
    view.game.grid = [[2, 2, 0, 0], [0] * 4, [0] * 4, [0] * 4]
    view.slide("left")
    assert view.game.score == 4
    page.pick("word")
    word = page.games["word"]
    for letter in "kalem":
        word.press(letter)
    assert word.cells[0][0].cget("text") == "K"
    page.pick("snake")
    snake = page.games["snake"]
    snake.start()
    snake.tick()
    assert snake.game.alive and snake.running
    page.pick("emoji")
    quiz = page.games["emoji"]
    quiz.entry.insert(0, quiz.round[0][1])
    quiz.answer()
    assert quiz.right == 1
    page.on_hide()
    assert not snake.running
