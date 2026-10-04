"""Chess for the Arcade (10.0): the rules, and an opponent.

Written here rather than taken from python-chess, which is GPL and would bind
the whole app to it. The rules are complete — castling, en passant,
promotion, check, mate, stalemate, the fifty-move rule, insufficient material
and threefold repetition — and are checked against the standard "perft" move
counts in the tests. The opponent is an alpha-beta search over material and
piece-square tables, three levels deep at most: it plays a sensible game and
answers in about a second, which is the point of a game in a side panel.
"""

from __future__ import annotations

import random
import time

FILES = "abcdefgh"
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}
GLYPHS = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
          "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}

KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
STRAIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _table(offsets) -> list[list[int]]:
    out = []
    for sq in range(64):
        f, r = sq % 8, sq // 8
        out.append([(r + dr) * 8 + f + df for df, dr in offsets if 0 <= f + df < 8 and 0 <= r + dr < 8])
    return out


def _rays(directions) -> list[list[list[int]]]:
    out = []
    for sq in range(64):
        f, r = sq % 8, sq // 8
        rays = []
        for df, dr in directions:
            ray, ff, rr = [], f + df, r + dr
            while 0 <= ff < 8 and 0 <= rr < 8:
                ray.append(rr * 8 + ff)
                ff, rr = ff + df, rr + dr
            rays.append(ray)
        out.append(rays)
    return out


KNIGHT_MOVES = _table(KNIGHT)
KING_MOVES = _table(KING)
DIAG_RAYS = _rays(DIAGONAL)
LINE_RAYS = _rays(STRAIGHT)

# Piece-square tables (white's view, a1 first), from the "simplified
# evaluation function": knights to the centre, pawns forward, kings tucked away.
_PST_TEXT = {
    "p": """0 0 0 0 0 0 0 0 | 5 10 10 -20 -20 10 10 5 | 5 -5 -10 0 0 -10 -5 5 | 0 0 0 20 20 0 0 0 |
            5 5 10 25 25 10 5 5 | 10 10 20 30 30 20 10 10 | 50 50 50 50 50 50 50 50 | 0 0 0 0 0 0 0 0""",
    "n": """-50 -40 -30 -30 -30 -30 -40 -50 | -40 -20 0 5 5 0 -20 -40 | -30 5 10 15 15 10 5 -30 |
            -30 0 15 20 20 15 0 -30 | -30 5 15 20 20 15 5 -30 | -30 0 10 15 15 10 0 -30 |
            -40 -20 0 0 0 0 -20 -40 | -50 -40 -30 -30 -30 -30 -40 -50""",
    "b": """-20 -10 -10 -10 -10 -10 -10 -20 | -10 5 0 0 0 0 5 -10 | -10 10 10 10 10 10 10 -10 |
            -10 0 10 10 10 10 0 -10 | -10 5 5 10 10 5 5 -10 | -10 0 5 10 10 5 0 -10 |
            -10 0 0 0 0 0 0 -10 | -20 -10 -10 -10 -10 -10 -10 -20""",
    "r": """0 0 0 5 5 0 0 0 | -5 0 0 0 0 0 0 -5 | -5 0 0 0 0 0 0 -5 | -5 0 0 0 0 0 0 -5 |
            -5 0 0 0 0 0 0 -5 | -5 0 0 0 0 0 0 -5 | 5 10 10 10 10 10 10 5 | 0 0 0 0 0 0 0 0""",
    "q": """-20 -10 -10 -5 -5 -10 -10 -20 | -10 0 5 0 0 0 0 -10 | -10 5 5 5 5 5 0 -10 |
            0 0 5 5 5 5 0 -5 | -5 0 5 5 5 5 0 -5 | -10 0 5 5 5 5 0 -10 | -10 0 0 0 0 0 0 -10 |
            -20 -10 -10 -5 -5 -10 -10 -20""",
    "k": """20 30 10 0 0 10 30 20 | 20 20 0 0 0 0 20 20 | -10 -20 -20 -20 -20 -20 -20 -10 |
            -20 -30 -30 -40 -40 -30 -30 -20 | -30 -40 -40 -50 -50 -40 -40 -30 |
            -30 -40 -40 -50 -50 -40 -40 -30 | -30 -40 -40 -50 -50 -40 -40 -30 | -30 -40 -40 -50 -50 -40 -40 -30""",
}
PST = {piece: [int(v) for v in text.replace("|", " ").split()] for piece, text in _PST_TEXT.items()}


def square(name: str) -> int:
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])


def name_of(sq: int) -> str:
    return f"{FILES[sq % 8]}{sq // 8 + 1}"


class Move(tuple):
    """(from, to, promotion) — a tuple, so moves compare and hash simply."""

    def __new__(cls, start: int, end: int, promo: str = ""):
        return super().__new__(cls, (start, end, promo))

    @property
    def start(self) -> int:
        return self[0]

    @property
    def end(self) -> int:
        return self[1]

    @property
    def promo(self) -> str:
        return self[2]

    def uci(self) -> str:
        return name_of(self[0]) + name_of(self[1]) + self[2]


class Board:
    def __init__(self, fen: str = START) -> None:
        self.load(fen)

    # --- position --------------------------------------------------------------------------------
    def load(self, fen: str) -> None:
        parts = fen.split()
        self.squares = ["."] * 64
        for rank_index, row in enumerate(parts[0].split("/")):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    self.squares[(7 - rank_index) * 8 + f] = ch
                    f += 1
        self.turn = parts[1] if len(parts) > 1 else "w"
        self.castling = set(parts[2]) - {"-"} if len(parts) > 2 else set()
        self.ep = square(parts[3]) if len(parts) > 3 and parts[3] != "-" else None
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self.history: list[tuple] = []
        self.moves_played: list[Move] = []
        self.seen: dict[str, int] = {self.key(): 1}

    def fen(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                piece = self.squares[r * 8 + f]
                if piece == ".":
                    empty += 1
                else:
                    row += (str(empty) if empty else "") + piece
                    empty = 0
            rows.append(row + (str(empty) if empty else ""))
        castling = "".join(c for c in "KQkq" if c in self.castling) or "-"
        ep = name_of(self.ep) if self.ep is not None else "-"
        return f"{'/'.join(rows)} {self.turn} {castling} {ep} {self.halfmove} {self.fullmove}"

    def key(self) -> str:
        """The position for repetition: pieces, side, castling, en passant (cheap: every move makes one)."""
        return "".join(self.squares) + self.turn + "".join(sorted(self.castling)) + str(self.ep)

    def king(self, colour: str) -> int:
        return self.squares.index("K" if colour == "w" else "k")

    @staticmethod
    def colour_of(piece: str) -> str:
        return "w" if piece.isupper() else "b"

    # --- attacks ---------------------------------------------------------------------------------
    def attacked(self, sq: int, by: str) -> bool:
        s = self.squares
        pawn, knight, king = ("P", "N", "K") if by == "w" else ("p", "n", "k")
        bishop_like = ("B", "Q") if by == "w" else ("b", "q")
        rook_like = ("R", "Q") if by == "w" else ("r", "q")
        f = sq % 8
        # A white pawn attacks upward, so it sits one rank below the square.
        source_rank = sq // 8 - 1 if by == "w" else sq // 8 + 1
        if 0 <= source_rank < 8:
            for df in (-1, 1):
                if 0 <= f + df < 8 and s[source_rank * 8 + f + df] == pawn:
                    return True
        if any(s[t] == knight for t in KNIGHT_MOVES[sq]):
            return True
        if any(s[t] == king for t in KING_MOVES[sq]):
            return True
        for ray in DIAG_RAYS[sq]:
            for t in ray:
                if s[t] != ".":
                    if s[t] in bishop_like:
                        return True
                    break
        for ray in LINE_RAYS[sq]:
            for t in ray:
                if s[t] != ".":
                    if s[t] in rook_like:
                        return True
                    break
        return False

    def in_check(self, colour: str | None = None) -> bool:
        colour = colour or self.turn
        return self.attacked(self.king(colour), "b" if colour == "w" else "w")

    # --- moves -----------------------------------------------------------------------------------
    def pseudo_moves(self, captures_only: bool = False) -> list[Move]:
        s, turn, out = self.squares, self.turn, []
        mine = str.isupper if turn == "w" else str.islower
        theirs = str.islower if turn == "w" else str.isupper
        for sq in range(64):
            piece = s[sq]
            if piece == "." or not mine(piece):
                continue
            kind = piece.lower()
            if kind == "p":
                self._pawn_moves(sq, out, captures_only)
            elif kind in "nk":
                for t in (KNIGHT_MOVES if kind == "n" else KING_MOVES)[sq]:
                    target = s[t]
                    if target == "." and not captures_only or target != "." and theirs(target):
                        out.append(Move(sq, t))
                if kind == "k" and not captures_only:
                    self._castles(sq, out)
            else:
                rays = (DIAG_RAYS[sq] if kind == "b" else LINE_RAYS[sq] if kind == "r" else
                        DIAG_RAYS[sq] + LINE_RAYS[sq])
                for ray in rays:
                    for t in ray:
                        target = s[t]
                        if target == ".":
                            if not captures_only:
                                out.append(Move(sq, t))
                            continue
                        if theirs(target):
                            out.append(Move(sq, t))
                        break
        return out

    def _pawn_moves(self, sq: int, out: list, captures_only: bool) -> None:
        s = self.squares
        white = self.turn == "w"
        step, start_rank, last_rank = (8, 1, 7) if white else (-8, 6, 0)
        f, r = sq % 8, sq // 8
        theirs = str.islower if white else str.isupper

        def add(t: int) -> None:
            if t // 8 == last_rank:
                out.extend(Move(sq, t, p) for p in "qrbn")
            else:
                out.append(Move(sq, t))

        one = sq + step
        if not captures_only and s[one] == ".":
            add(one)
            if r == start_rank and s[one + step] == ".":
                out.append(Move(sq, one + step))
        elif captures_only and s[one] == "." and one // 8 == last_rank:
            add(one)            # a promotion is worth searching like a capture
        for df in (-1, 1):
            if 0 <= f + df < 8:
                t = one + df
                if s[t] != "." and theirs(s[t]) or t == self.ep:
                    add(t)

    def _castles(self, sq: int, out: list) -> None:
        s, white = self.squares, self.turn == "w"
        enemy = "b" if white else "w"
        home = 4 if white else 60
        if sq != home or self.attacked(home, enemy):
            return
        rook = "R" if white else "r"
        if ("K" if white else "k") in self.castling and s[home + 1] == s[home + 2] == "." and \
                s[home + 3] == rook and not self.attacked(home + 1, enemy) and not self.attacked(home + 2, enemy):
            out.append(Move(home, home + 2))
        if ("Q" if white else "q") in self.castling and s[home - 1] == s[home - 2] == s[home - 3] == "." and \
                s[home - 4] == rook and not self.attacked(home - 1, enemy) and not self.attacked(home - 2, enemy):
            out.append(Move(home, home - 2))

    def push(self, move: Move) -> None:
        s = self.squares
        piece, captured = s[move.start], s[move.end]
        ep_capture = None
        if piece in "Pp" and move.end == self.ep and captured == ".":
            ep_capture = move.end - 8 if piece == "P" else move.end + 8     # the pawn taken in passing
            captured = s[ep_capture]
            s[ep_capture] = "."
        record = (move, captured, set(self.castling), self.ep, self.halfmove, self.fullmove, ep_capture)
        s[move.end] = (move.promo.upper() if piece == "P" else move.promo) if move.promo else piece
        s[move.start] = "."
        if piece in "Kk" and abs(move.end - move.start) == 2:          # castling: bring the rook
            rook_from, rook_to = (move.start + 3, move.start + 1) if move.end > move.start else \
                (move.start - 4, move.start - 1)
            s[rook_to], s[rook_from] = s[rook_from], "."
        for corner, right in ((0, "Q"), (7, "K"), (56, "q"), (63, "k")):
            if move.start == corner or move.end == corner:
                self.castling.discard(right)
        if piece == "K":
            self.castling -= {"K", "Q"}
        elif piece == "k":
            self.castling -= {"k", "q"}
        self.ep = (move.start + move.end) // 2 if piece in "Pp" and abs(move.end - move.start) == 16 else None
        self.halfmove = 0 if piece in "Pp" or captured != "." else self.halfmove + 1
        if self.turn == "b":
            self.fullmove += 1
        self.turn = "b" if self.turn == "w" else "w"
        self.history.append(record)
        self.moves_played.append(move)
        key = self.key()
        self.seen[key] = self.seen.get(key, 0) + 1

    def pop(self) -> Move:
        key = self.key()
        self.seen[key] -= 1
        if not self.seen[key]:
            del self.seen[key]
        move, captured, castling, ep, halfmove, fullmove, ep_capture = self.history.pop()
        self.moves_played.pop()
        s = self.squares
        piece = s[move.end]
        if move.promo:
            piece = "P" if piece.isupper() else "p"
        s[move.start] = piece
        if ep_capture is not None:
            s[move.end] = "."
            s[ep_capture] = captured
        else:
            s[move.end] = captured
        if piece in "Kk" and abs(move.end - move.start) == 2:
            rook_from, rook_to = (move.start + 3, move.start + 1) if move.end > move.start else \
                (move.start - 4, move.start - 1)
            s[rook_from], s[rook_to] = s[rook_to], "."
        self.castling, self.ep, self.halfmove, self.fullmove = castling, ep, halfmove, fullmove
        self.turn = "b" if self.turn == "w" else "w"
        return move

    def legal_moves(self, captures_only: bool = False) -> list[Move]:
        out = []
        mover = self.turn
        for move in self.pseudo_moves(captures_only):
            self.push(move)
            if not self.attacked(self.king(mover), self.turn):
                out.append(move)
            self.pop()
        return out

    # --- the end of the game ---------------------------------------------------------------------
    def insufficient_material(self) -> bool:
        pieces = [p for p in self.squares if p not in ".Kk"]
        if not pieces:
            return True
        if len(pieces) == 1 and pieces[0] in "BbNn":
            return True
        return False

    def outcome(self) -> str:
        """"" while the game goes on; else what ended it, said plainly."""
        if not self.legal_moves():
            if self.in_check():
                return "checkmate — " + ("Black" if self.turn == "w" else "White") + " wins"
            return "stalemate — a draw"
        if self.halfmove >= 100:
            return "fifty moves without a capture or pawn move — a draw"
        if self.insufficient_material():
            return "not enough pieces left to mate — a draw"
        if self.seen.get(self.key(), 0) >= 3:
            return "the same position three times — a draw"
        return ""

    # --- notation --------------------------------------------------------------------------------
    def san(self, move: Move) -> str:
        """Standard notation: Nf3, exd5, O-O, e8=Q+."""
        s = self.squares
        piece = s[move.start]
        kind = piece.upper()
        if kind == "K" and abs(move.end - move.start) == 2:
            text = "O-O" if move.end > move.start else "O-O-O"
        else:
            capture = s[move.end] != "." or (kind == "P" and move.end == self.ep)
            if kind == "P":
                text = (FILES[move.start % 8] + "x" if capture else "") + name_of(move.end)
                if move.promo:
                    text += "=" + move.promo.upper()
            else:
                rivals = [m for m in self.legal_moves() if m.end == move.end and m.start != move.start
                          and s[m.start] == piece]
                hint = ""
                if rivals:
                    if all(m.start % 8 != move.start % 8 for m in rivals):
                        hint = FILES[move.start % 8]
                    elif all(m.start // 8 != move.start // 8 for m in rivals):
                        hint = str(move.start // 8 + 1)
                    else:
                        hint = name_of(move.start)
                text = kind + hint + ("x" if capture else "") + name_of(move.end)
        self.push(move)
        if self.in_check():
            text += "#" if not self.legal_moves() else "+"
        self.pop()
        return text

    def parse(self, text: str) -> Move | None:
        """A move as typed: e2e4, e7e8q, Nf3, exd5, O-O."""
        text = text.strip().replace("0", "O")
        legal = self.legal_moves()
        raw = text.lower().replace("-", "").replace("x", "")
        for move in legal:
            if move.uci() == raw or move.uci() == text.lower():
                return move
        clean = text.rstrip("+#!?")
        for move in legal:
            if self.san(move).rstrip("+#") == clean:
                return move
        return None

    def evaluate(self) -> int:
        """Centipawns, from the side to move's point of view."""
        score = 0
        for sq, piece in enumerate(self.squares):
            if piece == ".":
                continue
            kind = piece.lower()
            if piece.isupper():
                score += VALUES[kind] + PST[kind][sq]
            else:
                score -= VALUES[kind] + PST[kind][(7 - sq // 8) * 8 + sq % 8]
        return score if self.turn == "w" else -score


# --- the opponent -----------------------------------------------------------------------------------

MATE = 100000
LEVELS = {"easy": 1, "medium": 2, "hard": 3}


class Engine:
    def __init__(self, level: str = "medium", seconds: float = 4.0) -> None:
        self.depth = LEVELS.get(level, 2)
        self.level = level
        self.seconds = seconds
        self.nodes = 0
        self._deadline = 0.0

    def _order(self, board: Board, moves: list[Move]) -> list[Move]:
        s = board.squares

        def score(m: Move) -> int:
            victim = s[m.end]
            gain = VALUES[victim.lower()] * 10 - VALUES[s[m.start].lower()] if victim != "." else 0
            return gain + (800 if m.promo == "q" else 0)

        return sorted(moves, key=score, reverse=True)

    def _quiet(self, board: Board, alpha: int, beta: int, depth: int = 0) -> int:
        self.nodes += 1
        stand = board.evaluate()
        if stand >= beta or depth >= 4:
            return stand
        alpha = max(alpha, stand)
        for move in self._order(board, board.legal_moves(captures_only=True)):
            board.push(move)
            score = -self._quiet(board, -beta, -alpha, depth + 1)
            board.pop()
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def _search(self, board: Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        moves = board.legal_moves()
        if not moves:
            return -(MATE - ply) if board.in_check() else 0
        if board.halfmove >= 100 or board.seen.get(board.key(), 0) >= 3:
            return 0
        if depth <= 0 or time.time() > self._deadline:
            return self._quiet(board, alpha, beta)
        best = -MATE * 2
        for move in self._order(board, moves):
            board.push(move)
            score = -self._search(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            if score > best:
                best = score
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best

    def choose(self, board: Board) -> Move | None:
        """The engine's move for the side to play (a copy is searched, the board is untouched)."""
        work = Board(board.fen())
        work.seen = dict(board.seen)
        moves = work.legal_moves()
        if not moves:
            return None
        self.nodes = 0
        self._deadline = time.time() + self.seconds
        scored = []
        alpha = -MATE * 2
        for move in self._order(work, moves):
            work.push(move)
            # Easy scores every move fully so it can pick a merely good one;
            # the others only need the best, so they narrow the window as they go.
            floor = -MATE * 2 if self.level == "easy" else alpha
            score = -self._search(work, self.depth - 1, -MATE * 2, -floor, 1)
            work.pop()
            scored.append((score, move))
            alpha = max(alpha, score)
        if self.level != "easy":
            # Only the best move's score is exact (the rest are bounds), so take it.
            return max(scored, key=lambda item: item[0])[1]
        # Easy plays a reasonable move rather than the best one, and never walks into mate.
        best = max(score for score, _ in scored)
        options = [m for score, m in scored if score >= best - 120 and (score > -MATE // 2 or score == best)]
        return random.choice(options)


def perft(board: Board, depth: int) -> int:
    """How many move sequences of this length there are — the standard test of a move generator."""
    if depth == 0:
        return 1
    total = 0
    for move in board.legal_moves():
        board.push(move)
        total += perft(board, depth - 1)
        board.pop()
    return total
