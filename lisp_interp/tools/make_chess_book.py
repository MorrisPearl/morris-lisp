"""Make the opening book for examples/chess.lsp, examples/chess_book.lsp, from
games in PGN files:

    python3 tools/make_chess_book.py PGN_FILE... > examples/chess_book.lsp

The games are those of top tournaments, from lichess.org, which broadcasts
them and gives each as PGN, the usual way to write a game:

    https://lichess.org/api/broadcast/{tournament id}.pgn

It's run once, to make the book, and again for a new one. It takes:

 1. The games that one side won (not draws), in at least 20 moves, between
    players both rated 2600 or more, not at a quick time control (rapid or
    blitz: less than half an hour on the clock).
 2. The openings -- a game's is the text of its Opening tag before the colon:
    "Sicilian Defense" -- that both white and black have won a game in; the 8
    in which the most games were won, the most first (those with the same
    number in alphabetical order).
 3. Of each, a game white won and a game black won: the first of each in the
    files, with different variations of the opening, if there are any.
 4. Of each game, the moves up to the winner's 8th. The program plays the
    winner's, in the book (chess.lsp, section 7), so there are 8 positions
    in the book from each game; the other side's moves are there to get to
    them.

Every move of every game chosen -- not only the ones kept -- is read by
chess.lsp's own program, so the book can't have a move that isn't legal
there, and a game that is garbled, or that the program can't read to the
end, is found. (That takes a couple of minutes: reading a move in standard
notation takes the program about a tenth of a second.) The moves are
written as the squares each piece goes from and to, which the program reads
in a fraction of the time. Above each game, in comments, are who played it
and where, and its moves in standard notation, so that the book can be read.

Options: --positions N (8), --openings N (8), --min-moves N (20),
--min-rating N (2600).
"""

import argparse
import collections
import os
import re
import sys

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# A move in standard notation: O-O, Nf3, exd5, Rae1, e8=Q, with + or #, and ! or ? that annotators add.
MOVE = re.compile(r"^(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#]?[!?]*$")
RESULTS = ("1-0", "0-1", "1/2-1/2", "*")

# What chess.lsp does with a game's moves: the squares each goes from and to.
SQUARES_OF_LINE = """
(define (squares-of-line moves)
  (let ((position (initial-position))
        (squares '()))
    (dolist (text moves)
      (let ((move (find-move position text)))
        (unless move
          (error "not a legal move here:" text))
        (set! squares (cons (move->squares move) squares))
        (set! position (make-move position move))))
    (reverse squares)))
"""

Game = collections.namedtuple("Game", "headers moves winner")      # winner: "white" or "black"


# ---------------------------------------------------------------------------
# Reading PGN
# ---------------------------------------------------------------------------

def games_in(text):
    """(headers, movetext) of each game in the PGN text: the headers a dict
    of the tags, [Event "..."] and the others, and the movetext the rest of
    the game, as written."""
    for chunk in re.split(r"\n\s*\n(?=\[Event )", text.strip()):
        headers = dict(re.findall(r'^\[(\w+) "(.*)"\]\s*$', chunk, re.M))
        lines = [line for line in chunk.splitlines() if not line.startswith("[")]
        yield headers, " ".join(lines)


def moves_of(movetext):
    """The moves of a game, in standard notation, from the movetext: without
    the move numbers, the comments in braces (lichess puts the clock times
    and engine evaluations there) and after ; the variations in parentheses,
    the annotations ($1, and so on, and ! and ? after a move), or the result.
    A word that isn't a move is an error."""
    text = re.sub(r"\{[^}]*\}", " ", movetext)
    text = re.sub(r";[^\n]*", " ", text)
    while True:                                        # variations, which may have variations in them
        shorter = re.sub(r"\([^()]*\)", " ", text)
        if shorter == text:
            break
        text = shorter
    moves = []
    for word in text.split():
        word = re.sub(r"^\d+\.+", "", word)             # 12.Nf3 as well as 12. Nf3
        if word == "" or re.match(r"^\$\d+$", word) or word in RESULTS:
            continue
        if not MOVE.match(word):
            raise ValueError("not a move: %r" % word)
        moves.append(word.rstrip("!?"))
    return moves


def is_quick(time_control):
    """Whether a TimeControl tag is that of a quick game: some seconds
    plus an increment, as 600+0, with less than half an hour on the clock."""
    match = re.match(r"^(\d+)\+\d+$", time_control or "")
    return bool(match) and int(match.group(1)) < 1800


def candidates(texts, min_moves, min_rating):
    """The games in the PGN texts that one side won, in at least min_moves
    moves, between players both rated min_rating or more, at a slow time control."""
    found = []
    for text in texts:
        for headers, movetext in games_in(text):
            winner = {"1-0": "white", "0-1": "black"}.get(headers.get("Result"))
            if winner is None or is_quick(headers.get("TimeControl")):
                continue
            ratings = [int(headers.get(tag) or 0) for tag in ("WhiteElo", "BlackElo")]
            moves = moves_of(movetext)
            if min(ratings) >= min_rating and len(moves) >= 2 * min_moves - 1:
                found.append(Game(headers, moves, winner))
    return found


# ---------------------------------------------------------------------------
# Choosing the games
# ---------------------------------------------------------------------------

def family(game):
    """A game's opening: the text of its Opening tag before the colon."""
    return game.headers.get("Opening", "unknown").split(":")[0]


def choose(games, openings):
    """Of the openings that both colors won a game in, the `openings` with the
    most games won (the ones with the same number in alphabetical order); and of
    each, the first game white won and the first black won, the second of
    them in another variation of the opening than the first, if there is
    one. Returns the games, by opening, white's first."""
    by_family = collections.defaultdict(list)
    for game in games:
        by_family[family(game)].append(game)
    both = [name for name, won in by_family.items() if {g.winner for g in won} == {"white", "black"}]
    chosen = []
    for name in sorted(both, key=lambda name: (-len(by_family[name]), name))[:openings]:
        white = next(g for g in by_family[name] if g.winner == "white")
        blacks = [g for g in by_family[name] if g.winner == "black"]
        black = next((g for g in blacks if g.headers.get("Opening") != white.headers.get("Opening")), blacks[0])
        chosen += [white, black]
    return chosen


def plies_to_keep(game, positions):
    """How many of a game's first plies (a ply is one side's move) to keep:
    through the winner's `positions`th move."""
    return min(2 * positions - (1 if game.winner == "white" else 0), len(game.moves))


# ---------------------------------------------------------------------------
# Writing the book
# ---------------------------------------------------------------------------

def standard_notation(moves):
    """Moves as a game is written: 1.e4 e5 2.Nf3 ..."""
    words = []
    for ply, move in enumerate(moves):
        words.append(("%d.%s" % (ply // 2 + 1, move)) if ply % 2 == 0 else move)
    return " ".join(words)


def surname(name):
    return name.split(",")[0].strip()


def wrap_comment(text, width=100):
    """text as lines of a comment, each starting with "; "."""
    words = re.findall(r"\S+(?: \| \S+)*", text)        # (a | stays between its words: Norway Chess 2026 | Open)
    lines, line = [], ";"
    for word in words:
        if len(line) + 1 + len(word) > width:
            lines.append(line)
            line = ";"
        line += " " + word
    return lines + [line]


def engine():
    """chess.lsp, in an interpreter, and a function that writes a game's
    moves, in standard notation, as the squares they go from and to."""
    sys.path.insert(0, HERE)
    import lisp_builtins
    import lisp_core
    env = lisp_builtins.make_global_env(output=lambda text: None)
    for source in ('(load "chess.lsp")', SQUARES_OF_LINE):
        for expression in lisp_core.parse(source):
            lisp_core.seval(expression, env)

    def squares_of(moves):
        line = lisp_core.list_to_pairs([lisp_core.LispString(move) for move in moves])
        answer = lisp_core.apply_proc(env[lisp_core.Symbol("squares-of-line")], [line])
        return [str(square) for square in lisp_core.pairs_to_list(answer)]

    return squares_of


def book_text(games, positions, squares_of):
    """The book, as the text of chess_book.lsp."""
    events = sorted({game.headers.get("BroadcastName", game.headers.get("Event", "")) for game in games})
    about = ("The opening book for chess.lsp (section 7): %d games, each won by white or by black, and their "
             "first moves, through the winner's move number %d, as the squares each move goes from and to. The "
             "winner's moves are the book's; the other side's are there to get to the positions they were played "
             "in. The games are from %s, as broadcast at lichess.org/broadcast. Above each game are its "
             "opening, the players, the event, where to find it, and its moves in standard notation, as far "
             "as the book goes." % (len(games), positions, "; ".join(events)))
    lines = ["; chess_book.lsp", ";"] + wrap_comment(about) + [
        ";",
        "; Made by tools/make_chess_book.py, which says how the games were chosen.",
        "",
        "(define book-games",
        "  '(",
    ]
    for game in games:
        squares = squares_of(game.moves)                  # all of it: it must be a game the program can read to the end
        kept = game.moves[:plies_to_keep(game, positions)]
        headers = game.headers
        lines += wrap_comment("%s (%s) -- %s v %s, %s. %s won." % (
            headers.get("Opening", "?"), headers.get("ECO", "?"), surname(headers["White"]), surname(headers["Black"]),
            headers.get("BroadcastName", headers.get("Event", "")), game.winner.capitalize()))
        lines += ["; " + headers["GameURL"]] if "GameURL" in headers else []
        lines += wrap_comment(standard_notation(kept))
        lines.append('    (%s "%s")' % (game.winner, " ".join(squares[:len(kept)])))
        lines.append("")
    lines[-1:] = ["    ))"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Make chess_book.lsp from PGN files.")
    parser.add_argument("pgn", nargs="+", help="PGN files")
    parser.add_argument("--positions", type=int, default=8, help="the winner's moves kept in each game")
    parser.add_argument("--openings", type=int, default=8, help="how many openings")
    parser.add_argument("--min-moves", type=int, default=20, help="the fewest moves in a game")
    parser.add_argument("--min-rating", type=int, default=2600, help="the lowest rating of either player")
    args = parser.parse_args()
    texts = []
    for path in args.pgn:
        with open(path, encoding="utf-8") as f:
            texts.append(f.read())
    games = choose(candidates(texts, args.min_moves, args.min_rating), args.openings)
    if not games:
        sys.exit("make_chess_book: no game qualifies")
    sys.stdout.write(book_text(games, args.positions, engine()))


if __name__ == "__main__":
    main()
