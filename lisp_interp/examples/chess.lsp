; chess.lsp
;
; A chess program, simple enough to read and see how it works. It draws the
; board with the chess pieces that Unicode has -- ♔ ♕ ♖ ♗ ♘ ♙ for white and
; ♚ ♛ ♜ ♝ ♞ ♟ for black -- on light and dark squares in a Jupyter notebook,
; and as text elsewhere. It takes your moves in algebraic notation (e4, Nf3,
; exd5, O-O, e8=Q), and chooses its own by looking ahead: at each of its
; moves, each of your replies, each of its answers to those, and so on, with
; minimax and alpha-beta pruning. Where it stops looking ahead, it keeps
; going through the captures that are still possible, until the position is
; quiet enough for a simple evaluation -- counting material, and a little
; about where the pieces stand -- to judge it.
;
; It knows all the rules of moving: castling, en passant, promotion, check,
; checkmate, and stalemate. It doesn't know the draws by repetition, by the
; fifty-move rule, or by too little material.
;
; To play it -- at the console or in a Jupyter notebook -- (load
; "chess.lsp"), then (play-chess). You are white; (play-chess :human black)
; to be black. It looks 2 moves ahead, taking a few seconds a move;
; (play-chess :depth 3) has it look 3 ahead, which plays better but takes
; ten to thirty seconds a move. chess_example.lsp shows it at work on a
; few positions.

; ---------------------------------------------------------------------------
; 1. The board
; ---------------------------------------------------------------------------
; The board is a vector of 120 numbers: the 64 squares, with a border two
; squares deep around them, so that a move off the board -- even a knight's
; jump -- lands on a border square rather than wrapping around.
;
;   91 92 93 94 95 96 97 98      a8 ... h8
;   ...                          ...
;   21 22 23 24 25 26 27 28      a1 ... h1
;
; So moving one square up the board (toward black) is adding 10, one square
; right is adding 1, and a knight's jump is adding one of the numbers in
; knight-jumps.
;
; A white piece is a positive number, a black one negative: a white knight
; is 2, a black knight -2. An empty square is 0, and a border square 7.

(define white 1)
(define black -1)

(define empty 0)
(define pawn 1)
(define knight 2)
(define bishop 3)
(define rook 4)
(define queen 5)
(define king 6)
(define off-board 7)

(define knight-jumps '(-21 -19 -12 -8 8 12 19 21))
(define diagonals '(-11 -9 9 11))
(define straights '(-10 -1 1 10))
(define all-directions '(-11 -10 -9 -1 1 9 10 11))

(define (square file rank)
  "The square on file 0 to 7 (a to h) and rank 0 to 7 (1 to 8)."
  (+ 21 file (* 10 rank)))

(define (file-of square) (- (mod square 10) 1))
(define (rank-of square) (- (quotient square 10) 2))

(define all-squares
  (loop for square from 21 to 98
        when (<= 1 (mod square 10) 8)
        collect square))

(define (file-letter file)
  (substring "abcdefgh" file (+ file 1)))

(define (square-name square)
  "The square's name, such as \"e4\"."
  (format "{}{}" (file-letter (file-of square)) (+ (rank-of square) 1)))

(define (enemy? piece side)
  "Whether piece belongs to side's opponent."
  (and (not (= piece off-board)) (< (* piece side) 0)))

; A position is the board, whose move it is, which castling moves are still
; allowed, and the square a pawn has just skipped over by moving two
; squares, if one has: an enemy pawn can capture it there, en passant, on
; the very next move.

(defstruct position
  board             ; the vector of 120 numbers
  side              ; white or black: whose move it is
  castling          ; a list of the castling moves still allowed
  en-passant)       ; the square a pawn just skipped over, or #f

; Each castling move, and the squares from which moving anything -- the king,
; or the rook -- or onto which capturing anything ends it for good.
(define castling-squares
  '((white-kingside 25 28) (white-queenside 25 21)
    (black-kingside 95 98) (black-queenside 95 91)))

; The letter for each castling move in Forsyth-Edwards Notation (below).
(define castling-letters
  '((white-kingside "K") (white-queenside "Q") (black-kingside "k") (black-queenside "q")))

(define (fen->position fen)
  "A position from Forsyth-Edwards Notation, the usual way to write one on
a line: the ranks from 8 down to 1, separated by /, each a letter for a
piece (upper case for white, lower for black) or a digit for that many
empty squares; then w or b for whose move it is; the castling moves still
allowed (K and Q for white, k and q for black, - for none); and the en
passant square, or -."
  (let* ((fields (string-split fen))
         (board (make-vector 120 off-board))
         (rank 7)
         (file 0))
    (dolist (square all-squares)
      (vector-set! board square empty))
    (dolist (c (regex-find-all "." (first fields)))       ; each character, as a string
      (cond ((string=? c "/") (set! rank (- rank 1)) (set! file 0))
            ((string-search "12345678" c) (set! file (+ file (string->number c))))
            (else
             (let ((kind (string-search "PNBRQK" (string-upcase c))))
               (vector-set! board (square file rank)
                            (* (+ kind 1) (if (string=? c (string-upcase c)) white black)))
               (set! file (+ file 1))))))
    (make-position
      :board board
      :side (if (string=? (second fields) "w") white black)
      :castling (loop for entry in castling-letters
                      when (string-contains? (third fields) (second entry))
                      collect (first entry))
      :en-passant (if (string=? (fourth fields) "-")
                      #f
                      (square (string-search "abcdefgh" (substring (fourth fields) 0 1))
                              (- (string->number (substring (fourth fields) 1 2)) 1))))))

(define (initial-position)
  (fen->position "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"))

; ---------------------------------------------------------------------------
; 2. Drawing the board
; ---------------------------------------------------------------------------

(define (piece-symbol piece)
  (cond ((= piece empty) "·")
        ((> piece 0) (substring " ♙♘♗♖♕♔" piece (+ piece 1)))
        (else (substring " ♟♞♝♜♛♚" (- piece) (+ (- piece) 1)))))

(define (ranks-seen-from side)
  "The ranks from the top of the board down, as side sees it."
  (if (= side white) '(7 6 5 4 3 2 1 0) '(0 1 2 3 4 5 6 7)))

(define (files-seen-from side)
  "The files from left to right, as side sees them."
  (if (= side white) '(0 1 2 3 4 5 6 7) '(7 6 5 4 3 2 1 0)))

(define (piece-on position file rank)
  (vector-ref (position-board position) (square file rank)))

(define (board-text position from-side)
  "The board as lines of text, each square a piece's symbol or a dot."
  (let ((lines '()))
    (dolist (rank (ranks-seen-from from-side))
      (set! lines (cons (format "  {}  {}" (+ rank 1)
                                (string-join (map (lambda (file) (piece-symbol (piece-on position file rank)))
                                                  (files-seen-from from-side))))
                        lines)))
    (set! lines (cons (format "     {}" (string-join (map file-letter (files-seen-from from-side))))
                      lines))
    (string-join (reverse lines) "\n")))

; In HTML, each square is a table cell, light or dark, with the piece's
; symbol large, in one of the fonts that have chess pieces.
(define light-square "#f0d9b5")
(define dark-square "#b58863")
(define square-style
  (string-append "width:40px; height:40px; padding:0; text-align:center; vertical-align:middle; "
                 "font-size:33px; line-height:40px; color:black; "
                 "font-family:'DejaVu Sans','Segoe UI Symbol','Apple Symbols','Noto Sans Symbols 2',serif"))
(define label-style "padding:0 8px; text-align:center; vertical-align:middle; font-weight:bold")

(define (board-html position from-side)
  "The board as an HTML table."
  (define (square-cell file rank)
    (let ((piece (piece-on position file rank)))
      (format "<td style=\"{}; background-color:{}\">{}</td>"
              square-style
              (if (even? (+ file rank)) dark-square light-square)     ; a1 is dark
              (if (= piece empty) "" (piece-symbol piece)))))
  (define (label-cell text)
    (format "<td style=\"{}\">{}</td>" label-style text))
  (define (row cells)                   ; background:none, so the notebook doesn't stripe the rows
    (string-append "<tr style=\"background:none\">" (string-join cells "") "</tr>"))
  (let ((rows (map (lambda (rank)
                     (row (cons (label-cell (+ rank 1))
                                (map (lambda (file) (square-cell file rank)) (files-seen-from from-side)))))
                   (ranks-seen-from from-side))))
    (string-append "<table style=\"border-collapse:collapse\">"
                   (string-join rows "")
                   (row (cons (label-cell "") (map (lambda (file) (label-cell (file-letter file)))
                                                   (files-seen-from from-side))))
                   "</table>")))

(define (draw-board position &key (from-side white))
  "Draw the board as side from-side sees it, with its own pieces at the
bottom: in a Jupyter notebook, in HTML; elsewhere, as text."
  (display-html (board-html position from-side) (board-text position from-side)))

; ---------------------------------------------------------------------------
; 3. Moves
; ---------------------------------------------------------------------------
; A move is a list: (from to), or (from to piece) for a pawn that reaches
; the far rank and becomes piece. Castling is written as the king's move,
; two squares toward the rook: (25 27) is white castling kingside.
;
; candidate-moves finds the moves each piece can make by the way it moves.
; That isn't quite the legal moves: a move that leaves the mover's own king
; in check isn't allowed. legal-moves checks each one, by making the move
; and seeing whether the king is then attacked.

(define (move-from move) (first move))
(define (move-to move) (second move))
(define (move-promotion move) (if (null? (cddr move)) #f (third move)))

(define (candidate-moves position)
  "Every move of the side to move that follows the way each piece moves,
whether or not it leaves that side's own king in check."
  (let ((board (position-board position))
        (side (position-side position))
        (moves '()))
    (define (add! from to)
      (set! moves (cons (list from to) moves)))
    (define (add-pawn-move! from to)
      (if (or (= (rank-of to) 7) (= (rank-of to) 0))
          (dolist (piece (list queen knight rook bishop))
            (set! moves (cons (list from to piece) moves)))
          (add! from to)))
    (define (steps! from directions)            ; a knight or a king: one step
      (dolist (direction directions)
        (let ((to (+ from direction)))
          (when (or (= (vector-ref board to) empty) (enemy? (vector-ref board to) side))
            (add! from to)))))
    (define (slides! from directions)           ; a bishop, rook, or queen: any distance
      (dolist (direction directions)
        (let ((to (+ from direction)))
          (while (= (vector-ref board to) empty)
            (add! from to)
            (set! to (+ to direction)))
          (when (enemy? (vector-ref board to) side)
            (add! from to)))))
    (define (pawn-moves! from)
      (let ((ahead (+ from (* 10 side))))
        (when (= (vector-ref board ahead) empty)
          (add-pawn-move! from ahead)
          (when (and (= (rank-of from) (if (= side white) 1 6))
                     (= (vector-ref board (+ ahead (* 10 side))) empty))
            (add! from (+ ahead (* 10 side)))))
        (dolist (to (list (- ahead 1) (+ ahead 1)))
          (when (or (enemy? (vector-ref board to) side)
                    (equal? to (position-en-passant position)))
            (add-pawn-move! from to)))))
    (define (castling-moves! from)
      (let ((rights (position-castling position)))
        (when (and (member (if (= side white) 'white-kingside 'black-kingside) rights)
                   (= (vector-ref board (+ from 1)) empty)
                   (= (vector-ref board (+ from 2)) empty)
                   (not (attacked? board from (- side)))
                   (not (attacked? board (+ from 1) (- side))))
          (add! from (+ from 2)))
        (when (and (member (if (= side white) 'white-queenside 'black-queenside) rights)
                   (= (vector-ref board (- from 1)) empty)
                   (= (vector-ref board (- from 2)) empty)
                   (= (vector-ref board (- from 3)) empty)
                   (not (attacked? board from (- side)))
                   (not (attacked? board (- from 1) (- side))))
          (add! from (- from 2)))))
    (dolist (from (squares-of board side))
      (let ((kind (abs (vector-ref board from))))
        (cond ((= kind pawn) (pawn-moves! from))
              ((= kind knight) (steps! from knight-jumps))
              ((= kind bishop) (slides! from diagonals))
              ((= kind rook) (slides! from straights))
              ((= kind queen) (slides! from all-directions))
              ((= kind king) (steps! from all-directions) (castling-moves! from)))))
    moves))

(define square-numbers (vector-range 120))       ; #(0 1 2 ... 119)

(define (squares-of board side)
  "The squares of side's pieces: the square numbers, selected where the
board holds one of them -- a number between 0 and off-board, once it's
multiplied by side so that side's pieces are positive. (Vector arithmetic
does this for the whole board at once, far faster than looking at each
square in turn.)"
  (let ((own (* side board)))
    (vector->list (vector-select square-numbers (vector-and (> own 0) (< own off-board))))))

(define (king-square board side)
  "The square of side's king."
  (vector-ref (vector-select square-numbers (= board (* side king))) 0))

(define (any? test items)
  "Whether test is true of any of the items."
  (and (pair? items)
       (or (test (car items)) (any? test (cdr items)))))

(define (attacked? board square by)
  "Whether one of side by's pieces attacks square."
  (define (piece-at offset)
    (vector-ref board (+ square offset)))
  (define (first-piece-toward direction)
    (let ((s (+ square direction)))
      (while (= (vector-ref board s) empty)
        (set! s (+ s direction)))
      (vector-ref board s)))
  (let ((behind (* -10 by)))            ; by's pawns attack from one rank behind
    (or (= (piece-at (- behind 1)) (* by pawn))
        (= (piece-at (+ behind 1)) (* by pawn))
        (any? (lambda (jump) (= (piece-at jump) (* by knight))) knight-jumps)
        (any? (lambda (step) (= (piece-at step) (* by king))) all-directions)
        (any? (lambda (direction)
                (let ((piece (first-piece-toward direction)))
                  (or (= piece (* by bishop)) (= piece (* by queen)))))
              diagonals)
        (any? (lambda (direction)
                (let ((piece (first-piece-toward direction)))
                  (or (= piece (* by rook)) (= piece (* by queen)))))
              straights))))

(define (in-check? position side)
  "Whether side's king is attacked."
  (let ((board (position-board position)))
    (attacked? board (king-square board side) (- side))))

(define (make-move position move)
  "The position after move -- a new one; position itself is unchanged."
  (let* ((board (vector-copy (position-board position)))
         (side (position-side position))
         (from (move-from move))
         (to (move-to move))
         (piece (vector-ref board from)))
    ; A pawn capturing en passant takes the pawn beside it, not one on to.
    (when (and (= piece (* side pawn)) (equal? to (position-en-passant position)))
      (vector-set! board (- to (* 10 side)) empty))
    ; Castling: the rook jumps to the other side of the king.
    (when (and (= piece (* side king)) (= (abs (- to from)) 2))
      (let ((rook-from (if (> to from) (+ from 3) (- from 4)))
            (rook-to (if (> to from) (+ from 1) (- from 1))))
        (vector-set! board rook-to (vector-ref board rook-from))
        (vector-set! board rook-from empty)))
    (vector-set! board to (if (move-promotion move) (* side (move-promotion move)) piece))
    (vector-set! board from empty)
    (make-position
      :board board
      :side (- side)
      :castling (filter (lambda (right)
                          (let ((squares (cdr (assoc right castling-squares))))
                            (not (or (member from squares) (member to squares)))))
                        (position-castling position))
      :en-passant (if (and (= piece (* side pawn)) (= (abs (- to from)) 20))
                      (quotient (+ from to) 2)
                      #f))))

(define (legal? position move)
  "Whether move, one of the candidate moves, doesn't leave the mover's king in check."
  (not (in-check? (make-move position move) (position-side position))))

(define (legal-moves position)
  (filter (lambda (move) (legal? position move))
          (candidate-moves position)))

(define (capture? position move)
  "Whether move captures a piece -- perhaps en passant."
  (let ((board (position-board position)))
    (or (not (= (vector-ref board (move-to move)) empty))
        (and (= (abs (vector-ref board (move-from move))) pawn)
             (equal? (move-to move) (position-en-passant position))))))

(define (count-positions position depth)
  "How many different sequences of depth legal moves there are from
position. Chess programmers call this perft, and use it to check a move
generator: the right numbers for many positions are known. From the
opening, they're 20, 400, 8902, 197281, ..."
  (if (= depth 0)
      1
      (loop for move in (legal-moves position)
            sum (count-positions (make-move position move) (- depth 1)))))

; ---------------------------------------------------------------------------
; 4. Algebraic notation
; ---------------------------------------------------------------------------
; A move is written as the piece's letter (none for a pawn), an x if it
; captures, and the square it goes to: Nf3, Bxe5, e4. A pawn that captures
; is named by its file: exd5. If two pieces of a kind could go to the
; square, the one moving is named by its file or rank too: Nbd2, R1e2.
; Castling is O-O (kingside) or O-O-O; promotion adds =Q; and + or # at the
; end says the move gives check, or checkmate.
;
; To read a move that's typed, the program doesn't parse the notation: it
; writes each legal move in notation, and looks for the one that was typed.

(define piece-letters " PNBRQK")

(define (piece-letter kind)
  (substring piece-letters kind (+ kind 1)))

(define (move->notation position move)
  "move, which must be legal in position, in algebraic notation -- without
the + or # for check."
  (let* ((board (position-board position))
         (from (move-from move))
         (to (move-to move))
         (kind (abs (vector-ref board from)))
         (takes (if (capture? position move) "x" "")))
    (cond ((and (= kind king) (= (- to from) 2)) "O-O")
          ((and (= kind king) (= (- to from) -2)) "O-O-O")
          ((= kind pawn)
           (string-append (if (= (file-of from) (file-of to)) "" (substring (square-name from) 0 1))
                          takes
                          (square-name to)
                          (if (move-promotion move) (string-append "=" (piece-letter (move-promotion move))) "")))
          (else
           (string-append (piece-letter kind) (which-one position move) takes (square-name to))))))

(define (which-one position move)
  "What tells move's piece apart from others of its kind that could go to
the same square: \"\" if there are none, else its file if that's enough,
else its rank if that's enough, else both."
  (let* ((board (position-board position))
         (from (move-from move))
         (rivals (loop for other in (candidate-moves position)
                       when (and (= (move-to other) (move-to move))
                                 (not (= (move-from other) from))
                                 (= (vector-ref board (move-from other)) (vector-ref board from))
                                 (legal? position other))
                       collect (move-from other))))
    (cond ((null? rivals) "")
          ((not (loop for rival in rivals thereis (= (file-of rival) (file-of from))))
           (substring (square-name from) 0 1))
          ((not (loop for rival in rivals thereis (= (rank-of rival) (rank-of from))))
           (substring (square-name from) 1 2))
          (else (square-name from)))))

(define (move->text position move)
  "move in algebraic notation, with + for check or # for checkmate."
  (let ((after (make-move position move)))
    (string-append (move->notation position move)
                   (cond ((not (in-check? after (position-side after))) "")
                         ((null? (legal-moves after)) "#")
                         (else "+")))))

(define (move->squares move)
  "move as the squares it goes from and to, such as e2e4 or e7e8Q."
  (string-append (square-name (move-from move))
                 (square-name (move-to move))
                 (if (move-promotion move) (piece-letter (move-promotion move)) "")))

(define (plain text)
  "Notation without what doesn't matter for telling moves apart: x, +, #,
=, -, !, ?, and spaces. Zeros are read as O (0-0 is O-O), and a lower-case
promotion letter as upper case (e7e8q is e7e8Q)."
  (let ((text (regex-replace "0" (string-trim text) "O")))
    (regex-replace "[x+#=!?\s-]" (regex-replace "(?<=[18])[qrbn]$" text (lambda (m) (string-upcase (car m)))) "")))

(define (find-move position text)
  "The legal move that text names -- in algebraic notation (Nf3), or by
its squares (g1f3) -- or #f."
  (let ((typed (plain text))
        (found #f))
    (dolist (move (legal-moves position))
      (when (or (string=? typed (plain (move->notation position move)))
                (string=? typed (move->squares move)))
        (set! found move)))
    found))

(define (play-moves position moves)
  "The position after the moves, in notation, such as '(\"e4\" \"e5\" \"Nf3\")."
  (dolist (text moves)
    (let ((move (find-move position text)))
      (unless move
        (error "play-moves: not a legal move here:" text))
      (set! position (make-move position move))))
  position)

; ---------------------------------------------------------------------------
; 5. Judging a position
; ---------------------------------------------------------------------------
; The static evaluation: a number that says how good the position is for
; white, in hundredths of a pawn, without looking ahead at all. It counts
; material -- a knight is worth about three pawns, a queen nine -- and adds
; a little for pieces on good squares: knights and bishops in the center,
; pawns that have advanced, a king tucked away in a corner. It's worked out
; for the whole board at once with vector arithmetic, as in the Othello
; example: (= board knight) is a vector with 1 on each square that has a
; white knight, 0 elsewhere.

(define piece-values '(0 100 320 330 500 900 0))     ; for each kind, pawn to king

(define (board-table rows)
  "A 120-square vector from eight rows of eight numbers, laid out as white
sees the board: rank 8 first, rank 1 last."
  (let ((table (make-vector 120 0)))
    (loop for row in rows
          for rank from 7 downto 0
          do (loop for value in row
                   for file from 0
                   do (vector-set! table (square file rank) value)))
    table))

(define (flipped table)
  "The table turned around for black, whose rank 8 is white's rank 1."
  (let ((result (make-vector 120 0)))
    (dolist (s all-squares)
      (vector-set! result (square (file-of s) (- 7 (rank-of s))) (vector-ref table s)))
    result))

(define center-bonus
  (board-table '((-20 -10 -10 -10 -10 -10 -10 -20)
                 (-10   0   0   0   0   0   0 -10)
                 (-10   0  10  10  10  10   0 -10)
                 (-10   5  10  20  20  10   5 -10)
                 (-10   5  10  20  20  10   5 -10)
                 (-10   0  10  10  10  10   0 -10)
                 (-10   0   0   0   0   0   0 -10)
                 (-20 -10 -10 -10 -10 -10 -10 -20))))

(define white-pawn-bonus
  (board-table '((  0   0   0   0   0   0   0   0)
                 ( 50  50  50  50  50  50  50  50)
                 ( 20  20  25  30  30  25  20  20)
                 ( 10  10  15  25  25  15  10  10)
                 (  5   5  10  20  20  10   5   5)
                 (  5   0   5  10  10   5   0   5)
                 (  0   0   0 -20 -20   0   0   0)
                 (  0   0   0   0   0   0   0   0))))
(define black-pawn-bonus (flipped white-pawn-bonus))

(define white-king-bonus
  (board-table '((-30 -40 -40 -50 -50 -40 -40 -30)
                 (-30 -40 -40 -50 -50 -40 -40 -30)
                 (-30 -40 -40 -50 -50 -40 -40 -30)
                 (-30 -40 -40 -50 -50 -40 -40 -30)
                 (-20 -30 -30 -40 -40 -30 -30 -20)
                 (-10 -20 -20 -20 -20 -20 -20 -10)
                 (  0   0 -10 -10 -10 -10   0   0)
                 ( 10  20  10   0   0  10  20  10))))
(define black-king-bonus (flipped white-king-bonus))

(define (white-advantage board)
  "How much better white stands than black, in hundredths of a pawn."
  (+ (loop for kind from pawn to queen
           sum (* (list-ref piece-values kind)
                  (- (vector-sum (= board kind)) (vector-sum (= board (- kind))))))
     (vector-sum (* center-bonus (- (+ (= board knight) (= board bishop))
                                    (+ (= board (- knight)) (= board (- bishop))))))
     (vector-sum (* white-pawn-bonus (= board pawn)))
     (- (vector-sum (* black-pawn-bonus (= board (- pawn)))))
     (vector-sum (* white-king-bonus (= board king)))
     (- (vector-sum (* black-king-bonus (= board (- king)))))))

(define (evaluate position)
  "How good position is for the side whose move it is."
  (* (position-side position) (white-advantage (position-board position))))

; ---------------------------------------------------------------------------
; 6. Looking ahead: minimax, with alpha-beta pruning
; ---------------------------------------------------------------------------
; Minimax: to judge a position, look at every move; judge the position after
; each, from the opponent's side; and assume the player to move picks the
; move that's best for them -- which is the worst for the opponent. So a
; position's value to the player to move is the most, over their moves, of
; minus its value to the opponent after the move. After depth moves, stop
; and judge the position statically.
;
; Alpha-beta pruning gets the same answer while looking at far fewer
; positions. alpha is the value the player to move is already sure of,
; from the moves looked at so far; beta is the most the opponent will
; allow, since they have a better choice earlier on. Once a move is found
; that's worth beta or more, the rest of the moves needn't be looked at:
; the opponent won't let the game come here. It prunes most when the best
; moves are looked at first, so captures of big pieces by small ones go
; first.
;
; Just stopping after depth moves works badly in chess: the last move
; might be a queen taking a pawn that's defended, and a static evaluation
; would count that as a pawn won. So at depth 0 the search keeps going,
; looking only at captures (quiescence search), until there are no good
; ones left -- a "quiet" position, which the evaluation can judge fairly.
; Except for checkmate, which no evaluation of the pieces sees: so at depth
; 0, a king in check with no way out counts as checkmated.

(define checkmate-value 100000)
(define *positions-searched* 0)

(define (guess-value position move)
  "How promising a move looks, before searching it: capturing a valuable
piece with a cheap one is best, and promoting is good."
  (let ((board (position-board position)))
    (+ (* 10 (list-ref piece-values (abs (vector-ref board (move-to move)))))
       (- (abs (vector-ref board (move-from move))))
       (if (move-promotion move) (list-ref piece-values (move-promotion move)) 0))))

(define (best-first position moves)
  (sort moves (lambda (move) (- (guess-value position move)))))

(define (alpha-beta position depth alpha beta)
  "The value of position to the side to move, looking depth moves ahead:
exactly, if it's between alpha and beta; otherwise alpha or less, or beta
or more."
  (set! *positions-searched* (+ *positions-searched* 1))
  (cond
    ((and (= depth 0) (checkmated? position))
     (- checkmate-value))
    ((= depth 0)
     (quiescence position alpha beta))
    (else
      (let ((side (position-side position))
            (any-legal-move #f))
        (loop for move in (best-first position (candidate-moves position))
              while (< alpha beta)
              do (let ((next (make-move position move)))
                   (unless (in-check? next side)            ; not a legal move
                     (set! any-legal-move #t)
                     (let ((value (- (alpha-beta next (- depth 1) (- beta) (- alpha)))))
                       (when (> value alpha)
                         (set! alpha value))))))
        (cond (any-legal-move alpha)
              ; No legal move: checkmate -- the sooner, the worse -- or stalemate.
              ((in-check? position side) (- (+ checkmate-value depth)))
              (else 0))))))

(define (checkmated? position)
  (and (in-check? position (position-side position))
       (null? (legal-moves position))))

(define (quiescence position alpha beta)
  "The value of position to the side to move, looking only at captures
(and promotions). The side to move needn't capture, so the static
evaluation is the least it's worth."
  (set! *positions-searched* (+ *positions-searched* 1))
  (let ((side (position-side position))
        (stand-pat (evaluate position)))
    (when (> stand-pat alpha)
      (set! alpha stand-pat))
    (loop for move in (best-first position (filter (lambda (move) (or (capture? position move)
                                                                      (move-promotion move)))
                                                   (candidate-moves position)))
          while (< alpha beta)
          do (let ((next (make-move position move)))
               (unless (in-check? next side)
                 (let ((value (- (quiescence next (- beta) (- alpha)))))
                   (when (> value alpha)
                     (set! alpha value))))))
    alpha))

(define (choose-move position depth)
  "The best move for the side to move, looking depth moves ahead, and its
value: a list (move value)."
  (let ((best-move #f)
        (best-value (- (* 2 checkmate-value))))
    (dolist (move (best-first position (legal-moves position)))
      (let ((value (- (alpha-beta (make-move position move) (- depth 1)
                                  (- (* 2 checkmate-value)) (- best-value)))))
        (when (or (not best-move) (> value best-value))
          (set! best-move move)
          (set! best-value value))))
    (list best-move best-value)))

; ---------------------------------------------------------------------------
; 7. Playing a game
; ---------------------------------------------------------------------------

(define (side-name side) (if (= side white) "White" "Black"))

(define (game-over-message position)
  "#f if the side to move has a legal move; otherwise how the game ended."
  (cond ((not (null? (legal-moves position))) #f)
        ((in-check? position (position-side position))
         (format "Checkmate: {} wins." (side-name (- (position-side position)))))
        (else "Stalemate: a draw.")))

(define (value->text value side)
  "What a search's value for side says: its score in pawns, such as
\"+0.35 pawns for White\", or the checkmate it foresees."
  (cond ((> value (/ checkmate-value 2)) "it sees a checkmate")
        ((< value (- (/ checkmate-value 2))) "it sees it will be checkmated")
        (else (format "{:+.2f} pawns for {}" (/ value 100) (side-name side)))))

(define (computer-move position depth)
  "The computer's move, after saying what it is and how long it took."
  (set! *positions-searched* 0)
  (let* ((start (current-time))
         (choice (choose-move position depth))
         (move (first choice)))
    (display (format "{} plays {}   ({}; looked at {} positions in {}s)\n"
                     (side-name (position-side position)) (move->text position move)
                     (value->text (second choice) (position-side position))
                     *positions-searched* (seconds-between start (current-time))))
    move))

(define (human-move position)
  "Ask for a move until a legal one is typed; #f to stop the game."
  (let ((move #f)
        (asking #t))
    (while asking
      (let* ((answer (read-line "Your move (or moves, or quit): "))
             (text (if answer (string-trim answer) "quit")))      ; #f: the input has ended
        (cond ((member text '("quit" "resign"))
               (set! asking #f))
              ((string=? text "moves")
               (display (format "Legal moves: {}\n"
                                (string-join (sort (map (lambda (m) (move->notation position m))
                                                        (legal-moves position)))))))
              (else
               (set! move (find-move position text))
               (if move
                   (set! asking #f)
                   (display (format "\"{}\" isn't a legal move here.\n" text)))))))
    move))

(define (game-text moves first-side)
  "The moves, in notation, as a game is written: 1.e4 e5 2.Nf3 ...
first-side is the side that made the first of them."
  (let ((words '())
        (number 1)
        (side first-side))
    (dolist (move moves)
      (cond ((= side white) (set! words (cons (format "{}.{}" number move) words)))
            ((null? words) (set! words (cons (format "{}...{}" number move) words)))
            (else (set! words (cons move words))))
      (when (= side black)
        (set! number (+ number 1)))
      (set! side (- side)))
    (string-join (reverse words))))

(define (play-chess &key (human white) (depth 2) (position (initial-position)))
  "Play a game against the computer: you're white, unless :human is black.
The computer looks :depth moves ahead (and then at the captures). Type
your moves in algebraic notation -- e4, Nf3, exd5, O-O, e8=Q -- or by
their squares, e2e4; moves lists the legal moves, and quit stops. To
start from some other position, give it as :position."
  (let ((first-side (position-side position))
        (moves-made '())                ; in notation
        (playing #t))
    (while playing
      (let ((over (game-over-message position)))
        (cond (over
               (newline)
               (draw-board position :from-side human)
               (display (format "{}\n" over))
               (set! playing #f))
              (else
               (when (= (position-side position) human)
                 (newline)
                 (draw-board position :from-side human))
               (let ((move (if (= (position-side position) human)
                               (human-move position)
                               (computer-move position depth))))
                 (if move
                     (begin
                       (set! moves-made (append moves-made (list (move->text position move))))
                       (set! position (make-move position move)))
                     (set! playing #f)))))))
    (display (format "The game: {}\n" (game-text moves-made first-side)))))
