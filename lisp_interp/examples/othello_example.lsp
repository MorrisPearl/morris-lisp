; othello_example.lsp
;
; Othello, and programs that play it -- from random moves up to searching
; ahead with minimax and alpha-beta pruning -- after chapter 18 of Peter
; Norvig's "Paradigms of Artificial Intelligence Programming" (1992). Norvig's
; Common Lisp code is at https://github.com/norvig/paip-lisp (MIT license);
; this is written afresh for this interpreter, with its own weights.
;
; The rules: black and white take turns putting a piece on the 8x8 board.
; A move must trap a line of the opponent's pieces -- across, down, or
; diagonally -- between the new piece and another of the mover's, and those
; pieces are flipped to the mover's color. A player with no such move
; passes; when neither can move, whoever has more pieces wins.
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py othello_example.lsp
; To play against the program, (load "othello_example.lsp"), then
;   (othello human (alpha-beta-searcher 2 weighted-squares) #t)

; ---------------------------------------------------------------------------
; 1. The board
; ---------------------------------------------------------------------------
; The board is a vector of 100 numbers: a 10x10 grid, whose outside rows and
; columns are a border, so that a step off the board lands on a border
; square instead of wrapping around. Square 11 is the top-left corner, 18
; the top-right, 88 the bottom-right. Moving one square in a direction is
; adding one of these numbers:

(define all-directions '(-11 -10 -9 -1 1 9 10 11))

(define empty 0)
(define black 1)
(define white 2)
(define outer 3)

(define (name-of piece) (substring ".@O?" piece (+ piece 1)))
(define (opponent player) (if (= player black) white black))

(define all-squares
  (loop for square from 11 to 88
        when (<= 1 (mod square 10) 8)
        collect square))

(define (initial-board)
  "A board with the four pieces in the middle that a game starts with."
  (let ((board (make-vector 100 outer)))
    (dolist (square all-squares) (vector-set! board square empty))
    (vector-set! board 44 white)
    (vector-set! board 45 black)
    (vector-set! board 54 black)
    (vector-set! board 55 white)
    board))

(define (count-pieces player board)
  (vector-sum (= board player)))

(define (count-difference player board)
  "How many more pieces player has than the opponent."
  (- (count-pieces player board) (count-pieces (opponent player) board)))

(define (print-board board)
  (display (format "     1 2 3 4 5 6 7 8   [{}={} {}={} ({:+d})]\n"
                   (name-of black) (count-pieces black board)
                   (name-of white) (count-pieces white board)
                   (count-difference black board)))
  (loop for row from 1 to 8
        do (display (format "  {} " (* 10 row)))
           (loop for column from 1 to 8
                 do (display (format " {}" (name-of (vector-ref board (+ (* 10 row) column))))))
           (newline)))

; ---------------------------------------------------------------------------
; 2. Moves
; ---------------------------------------------------------------------------

(define (find-bracketing-piece square player board direction)
  "Going from square in direction over the opponent's pieces, the square of
player's own piece that ends them -- or #f if there isn't one."
  (let ((piece (vector-ref board square)))
    (cond ((= piece player) square)
          ((= piece (opponent player))
           (find-bracketing-piece (+ square direction) player board direction))
          (else #f))))

(define (would-flip? move player board direction)
  "Would this move flip any pieces in this direction? If so, the square of
the piece at the far end."
  (let ((next (+ move direction)))
    (and (= (vector-ref board next) (opponent player))
         (find-bracketing-piece (+ next direction) player board direction))))

(define (legal? move player board)
  (and (= (vector-ref board move) empty)
       (loop for direction in all-directions
             thereis (would-flip? move player board direction))))

(define (legal-moves player board)
  (filter (lambda (move) (legal? move player board)) all-squares))

(define (any-legal-move? player board)
  (loop for move in all-squares thereis (legal? move player board)))

(define (make-move move player board)
  "Put player's piece on move, and flip what it traps. Changes board."
  (vector-set! board move player)
  (dolist (direction all-directions)
    (let ((far-end (would-flip? move player board direction)))
      (when far-end
        (loop for square from (+ move direction) by direction
              until (= square far-end)
              do (vector-set! board square player)))))
  board)

(define (next-to-play board previous-player)
  "Who moves next: the other player, unless they have no move, when
previous-player goes again; #f when neither can move -- the game is over."
  (let ((other (opponent previous-player)))
    (cond ((any-legal-move? other board) other)
          ((any-legal-move? previous-player board) previous-player)
          (else #f))))

; ---------------------------------------------------------------------------
; 3. Playing a game
; ---------------------------------------------------------------------------
; A strategy is a procedure: given the player and (a copy of) the board, it
; returns the square to move to.

(define (othello black-strategy white-strategy show?)
  "Play a game. Returns black's final lead in pieces (negative if white won).
With show? true, it shows each move and the board after it."
  (let ((board (initial-board))
        (player black))
    (while player
      (let* ((strategy (if (= player black) black-strategy white-strategy))
             (move (strategy player (vector-copy board))))
        (unless (legal? move player board)
          (error "othello: illegal move" move "by" (name-of player)))
        (make-move move player board)
        (when show?
          (display (format "{} moves to {}.\n" (name-of player) move))
          (print-board board))
        (set! player (next-to-play board player))))
    (count-difference black board)))

(define (random-strategy player board)
  (let ((moves (legal-moves player board)))
    (list-ref moves (random-int 0 (- (length moves) 1)))))

(define (human player board)
  "A strategy that asks you: type the number of a square, such as 34. It
asks again until the answer is one of the legal moves."
  (print-board board)
  (let ((moves (legal-moves player board))
        (move #f))
    (while (not (member move moves))
      (let ((answer (read-line (format "{} to move -- one of {}: " (name-of player) moves))))
        (unless answer
          (error "othello: the input ended"))
        (set! move (if (regex-match "\s*\d+\s*" answer) (string->number answer) #f))))
    move))

; ---------------------------------------------------------------------------
; 4. Judging positions
; ---------------------------------------------------------------------------
; maximizer makes a strategy that takes the move whose result an evaluation
; function likes best. The simplest function counts pieces; better is to
; weigh the squares, since some are worth far more than others: a corner
; can never be flipped, while the squares next to it give the opponent a
; way into it.

(define (maximizer evaluate)
  "A strategy that takes the move whose result evaluate scores highest."
  (lambda (player board)
    (let ((best-move #f)
          (best-score #f))
      (dolist (move (legal-moves player board))
        (let ((score (evaluate player (make-move move player (vector-copy board)))))
          (when (or (not best-score) (> score best-score))
            (set! best-move move)
            (set! best-score score))))
      best-move)))

; One weight per square (the border squares are 0), from the top-left.
(define *weights*
  (list->vector
    '(0   0   0   0   0   0   0   0   0   0
      0 100 -25  12   6   6  12 -25 100   0
      0 -25 -50  -3  -2  -2  -3 -50 -25   0
      0  12  -3   3   1   1   3  -3  12   0
      0   6  -2   1   1   1   1  -2   6   0
      0   6  -2   1   1   1   1  -2   6   0
      0  12  -3   3   1   1   3  -3  12   0
      0 -25 -50  -3  -2  -2  -3 -50 -25   0
      0 100 -25  12   6   6  12 -25 100   0
      0   0   0   0   0   0   0   0   0   0)))

(define (weighted-squares player board)
  "The weights of player's squares, less the weights of the opponent's --
worked out for the whole board at once, with vector arithmetic."
  (vector-sum (* *weights* (- (= board player) (= board (opponent player))))))

; ---------------------------------------------------------------------------
; 5. Searching ahead
; ---------------------------------------------------------------------------
; Minimax: look ply moves ahead. At each level, the player to move takes the
; move that is best for them -- which is worst for the other, so a position's
; value to one player is minus its value to the other. At the bottom, the
; evaluation function scores the position. At the end of the game, a win is
; worth more than any position.

(define winning-value 1000000000)
(define losing-value -1000000000)

(define (final-value player board)
  (let ((lead (count-difference player board)))
    (cond ((> lead 0) winning-value)
          ((< lead 0) losing-value)
          (else 0))))

(define (minimax player board ply evaluate)
  "The best move for player, looking ply moves ahead, and its value: a list
(value move)."
  (if (= ply 0)
      (list (evaluate player board) #f)
      (let ((moves (legal-moves player board)))
        (if (null? moves)
            (if (any-legal-move? (opponent player) board)
                (list (- (car (minimax (opponent player) board (- ply 1) evaluate))) #f)
                (list (final-value player board) #f))
            (let ((best-value #f)
                  (best-move #f))
              (dolist (move moves)
                (let ((value (- (car (minimax (opponent player)
                                              (make-move move player (vector-copy board))
                                              (- ply 1) evaluate)))))
                  (when (or (not best-value) (> value best-value))
                    (set! best-value value)
                    (set! best-move move))))
              (list best-value best-move))))))

(define (minimax-searcher ply evaluate)
  (lambda (player board) (cadr (minimax player board ply evaluate))))

; Alpha-beta: the same answer as minimax, from fewer positions. alpha is the
; value player is already sure of, from moves looked at so far; beta is the
; most the opponent will allow. Once a move is worth beta or more, the rest
; needn't be looked at: the opponent won't let the game get here.

(define (alpha-beta player board alpha beta ply evaluate)
  "The best move for player and its value, (value move), looking ply moves
ahead, but only for values between alpha and beta."
  (if (= ply 0)
      (list (evaluate player board) #f)
      (let ((moves (legal-moves player board)))
        (if (null? moves)
            (if (any-legal-move? (opponent player) board)
                (list (- (car (alpha-beta (opponent player) board (- beta) (- alpha) (- ply 1) evaluate))) #f)
                (list (final-value player board) #f))
            (let ((best-move (car moves)))
              (loop for move in moves
                    while (< alpha beta)
                    do (let ((value (- (car (alpha-beta (opponent player)
                                                        (make-move move player (vector-copy board))
                                                        (- beta) (- alpha) (- ply 1) evaluate)))))
                         (when (> value alpha)
                           (set! alpha value)
                           (set! best-move move))))
              (list alpha best-move))))))

(define (alpha-beta-searcher ply evaluate)
  (lambda (player board) (cadr (alpha-beta player board losing-value winning-value ply evaluate))))

; ---------------------------------------------------------------------------
; 6. Some games
; ---------------------------------------------------------------------------

; Alpha-beta finds the same best value as minimax, looking at fewer positions:
(display (format "From the opening, looking 3 moves ahead: minimax {}, alpha-beta {}\n\n"
                 (car (minimax black (initial-board) 3 weighted-squares))
                 (car (alpha-beta black (initial-board) losing-value winning-value 3 weighted-squares))))

(random-seed 3)
(display "A random player (black) against one that looks ahead 2 moves (white):\n\n")
(define lead (othello random-strategy (alpha-beta-searcher 2 weighted-squares) #f))
(display (format "Black's lead at the end: {}\n\n" lead))

(define (record-of strategy-a strategy-b games)
  "How many of `games` games strategy-a wins with black, against strategy-b."
  (loop repeat games count (> (othello strategy-a strategy-b #f) 0)))

(display (format "Counting pieces (maximize the difference) against random, as black: won {} of 5\n"
                 (record-of (maximizer count-difference) random-strategy 5)))
(display (format "Weighing squares against counting pieces, as black: won {} of 2\n"
                 (record-of (maximizer weighted-squares) (maximizer count-difference) 2)))

(display "\nWeighing squares (black) against looking 2 moves ahead (white) -- the final board:\n")
(define board (initial-board))
(define player black)
(define moves-made 0)
(while player
  (let ((move ((if (= player black) (maximizer weighted-squares) (alpha-beta-searcher 2 weighted-squares))
               player (vector-copy board))))
    (make-move move player board)
    (incf moves-made)
    (set! player (next-to-play board player))))
(print-board board)
(display (format "{} moves; {}\n" moves-made
                 (let ((lead (count-difference black board)))
                   (cond ((> lead 0) "black won") ((< lead 0) "white won") (else "a draw")))))
