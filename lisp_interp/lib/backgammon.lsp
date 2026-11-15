; backgammon.lsp
;
; The rules of backgammon: the board, the dice, the legal plays, the game's
; bookkeeping (checkers borne off, the pip count), and the board written as
; text. The neural network that learns to play is in backgammon_net.lsp; the
; example programs that use both are examples/backgammon_train.lsp and
; examples/backgammon_play.lsp.
;
; THE BOARD. A position is a vector of 26 numbers, written from the point of
; view of the player whose turn it is to move (the MOVER):
;
;   index 0        the mover's checkers on the bar (a count, 0 or more)
;   index 1 to 24  the points. A positive count is the mover's checkers on that
;                  point; a negative count is the opponent's (-2 is two of them)
;   index 25       the opponent's checkers on the bar, as a negative count
;
; The mover moves from point 24 down to point 1 and bears off past point 1;
; its home board is points 1 to 6. The opponent moves the other way, so its
; point p is the mover's point 25 - p. Checkers borne off are not stored: the
; count is 15 less the checkers still on the board (backgammon-off).
;
; Turning the board around, so that the other player is the mover, is
; backgammon-flip: each count changes sign, and point p becomes point 25 - p.
; A play's board is the position after the play, still from the mover's point
; of view; the opponent sees it flipped.
;
; A PLAY is what a player does with one roll. The dice are used one at a time,
; each die moving one checker, and as many dice as possible must be used (and
; the higher die, if only one of them can be used). Different orders of the
; same moves often give the same board, so backgammon-plays keeps one play for
; each distinct board. A play has its board and its steps, in the order made.
; Each step is (from to die): from 0 is the bar and to 0 is bearing off, so the
; step (24 18 3) moves a checker from point 24 to point 18 with a 3.

(define backgammon-checkers 15)

; The points 1 to 24 as a vector, so that a pip count is one dot product.
(define backgammon-point-numbers (list->vector (map (lambda (x) (+ x 1)) (iota 24))))

; The positions 25, 24, ... 0: taking them from a board in this order turns it around.
(define backgammon-flip-positions (list->vector (reverse (iota 26))))

(defstruct backgammon-play board steps)

(define (backgammon-start)
  "The starting position from the mover's point of view: two checkers on the
24 point, five on 13, three on 8 and five on 6, and the opponent's the same
from its side."
  (let ((board (make-vector 26 0)))
    (vector-set! board 24 2)
    (vector-set! board 13 5)
    (vector-set! board 8 3)
    (vector-set! board 6 5)
    (vector-set! board 1 -2)
    (vector-set! board 12 -5)
    (vector-set! board 17 -3)
    (vector-set! board 19 -5)
    board))

(define (backgammon-flip board)
  "The same position from the other player's point of view: each count's sign
is changed and each point p becomes point 25 - p (the bar stays the bar)."
  (vector-mul -1 (vector-gather board backgammon-flip-positions)))

(define (backgammon-highest-point board)
  "The highest-numbered point the mover has a checker on, or 0 if none."
  (vector-max (vector-mul (> (vector-slice board 1 25) 0) backgammon-point-numbers)))

(define (backgammon-off board)
  "How many of the mover's checkers have been borne off."
  (let ((on-board (vector-sum (vector-clip (vector-slice board 1 25) 0 '()))))
    (- backgammon-checkers (+ on-board (vector-ref board 0)))))

(define (backgammon-opponent-off board)
  "How many of the opponent's checkers have been borne off."
  (let ((on-board (vector-sum (vector-clip (vector-sub 0 (vector-slice board 1 25)) 0 '()))))
    (- backgammon-checkers (+ on-board (- (vector-ref board 25))))))

(define (backgammon-pips board)
  "The mover's pip count: how far its checkers are from being borne off. A
checker on point p is p pips away, and one on the bar is 25."
  (let ((mine (vector-clip (vector-slice board 1 25) 0 '())))
    (+ (* 25 (vector-ref board 0))
       (vector-sum (vector-mul mine backgammon-point-numbers)))))

(define (backgammon-opponent-pips board)
  "The opponent's pip count, from its own point of view: its checker on the
mover's point p is 25 - p pips away."
  (let ((theirs (vector-clip (vector-sub 0 (vector-slice board 1 25)) 0 '())))
    (+ (* 25 (- (vector-ref board 25)))
       (vector-sum (vector-mul theirs (vector-sub 25 backgammon-point-numbers))))))

(define (backgammon-open? board point)
  "Whether the mover may land on point: it is not held by two or more of the
opponent's checkers."
  (> (vector-ref board point) -2))

(define (backgammon-checker-moves board die)
  "The single moves of one checker by die, each a list (from to). With a
checker on the bar, only entering is possible. Otherwise a checker moves
down by die, and may bear off only when all the mover's checkers are in its
home board: with the exact die, or with a higher die from the highest point."
  (let ((moves '()))
    (if (> (vector-ref board 0) 0)
        (let ((entry (- 25 die)))
          (if (backgammon-open? board entry)
              (set! moves (list (list 0 entry)))))
        (let* ((highest (backgammon-highest-point board))
               (all-home (<= highest 6))
               (occupied (vector->list (vector-select backgammon-point-numbers
                                                      (> (vector-slice board 1 25) 0)))))
          (dolist (point occupied)
            (let ((target (- point die)))
              (cond ((>= target 1)
                     (if (backgammon-open? board target)
                         (set! moves (cons (list point target) moves))))
                    ((and all-home (or (= target 0) (= point highest)))
                     (set! moves (cons (list point 0) moves))))))))
    moves))

(define (backgammon-move-checker board from to)
  "The position after one checker moves from (0 for the bar) to a point (0 for
off). Landing on a single opponent checker hits it: it goes to the bar."
  (let ((moved (vector-copy board)))
    (if (= from 0)
        (vector-set! moved 0 (- (vector-ref moved 0) 1))
        (vector-set! moved from (- (vector-ref moved from) 1)))
    (if (> to 0)
        (if (= (vector-ref moved to) -1)
            (begin
              (vector-set! moved to 1)
              (vector-set! moved 25 (- (vector-ref moved 25) 1)))
            (vector-set! moved to (+ (vector-ref moved to) 1))))
    moved))

(define (backgammon--without dice die)
  "The dice with one die of that value taken out."
  (let ((rest '()) (dropped #f))
    (dolist (d dice)
      (if (and (not dropped) (= d die))
          (set! dropped #t)
          (set! rest (cons d rest))))
    (reverse rest)))

(define (backgammon--sequences board dice steps)
  "Every way to play the dice from this board, one die at a time, as a list
of (board steps) for each way that ends with no die that can be played. steps
are the moves so far, most recent first."
  (let ((ends '()) (tried '()))
    (dolist (die dice)
      (if (not (member die tried))
          (begin
            (set! tried (cons die tried))
            (dolist (move (backgammon-checker-moves board die))
              (let ((after (backgammon-move-checker board (first move) (second move))))
                (set! ends
                      (append ends
                              (backgammon--sequences
                               after
                               (backgammon--without dice die)
                               (cons (list (first move) (second move) die) steps)))))))))
    (if (null? ends)
        (list (list board steps))
        ends)))

(define (backgammon-plays board dice)
  "The plays the mover can make with these dice: a list of backgammon-play
structures, each with its board and its steps. A play must use as many dice
as it can, and when only one die can be used it must be the higher one, if
that can be used. Plays with the same board are kept once. If no die can be
played, the one play is to stay put, with no steps. The dice are a list such
as (3 1), or (4 4 4 4) for doubles."
  (let* ((ends (backgammon--sequences board dice '()))
         (most (apply max (map (lambda (end) (length (second end))) ends)))
         (kept (filter (lambda (end) (= (length (second end)) most)) ends))
         (higher (apply max dice)))
    (if (and (= most 1) (not (= (first dice) (second dice))))
        (let ((with-higher (filter (lambda (end) (member higher (map third (second end)))) kept)))
          (if (not (null? with-higher)) (set! kept with-higher))))
    (let ((plays '()))
      (dolist (end kept)
        (if (not (member (first end) (map backgammon-play-board plays)))
            (set! plays (cons (make-backgammon-play :board (first end)
                                                    :steps (reverse (second end)))
                              plays))))
      (reverse plays))))

(define (backgammon-roll)
  "A roll of two dice as a list such as (3 1), or four equal dice for doubles."
  (let ((a (random-int 1 6)) (b (random-int 1 6)))
    (if (= a b) (list a a a a) (list a b))))

(define (backgammon-opening-roll)
  "The first roll of a game: two different dice (a double is rolled again).
The higher die is played first, and the player who rolls it starts."
  (let ((a (random-int 1 6)) (b (random-int 1 6)))
    (if (= a b)
        (backgammon-opening-roll)
        (list (max a b) (min a b)))))

(define (backgammon-game-over? board)
  "Whether the mover has borne off all its checkers, so has won."
  (= (backgammon-off board) backgammon-checkers))

(define (backgammon-result board)
  "How much a finished game is worth, as a multiple of the cube: 1 for a
single game, 2 for a gammon (the opponent has borne off no checkers), or 3 for
a backgammon (no checkers off, and one still on the bar or in the winner's home
board). board is the position after the winner's last move, from its point of
view."
  (cond ((> (backgammon-opponent-off board) 0) 1)
        ((or (< (vector-ref board 25) 0) (< (vector-min (vector-slice board 1 7)) 0)) 3)
        (else 2)))

; ---------------------------------------------------------------------------
; Plays in backgammon notation, and reading them back
; ---------------------------------------------------------------------------

(define (backgammon-step-text step)
  "A step in the usual notation, as in 24/18, bar/20 or 3/off."
  (let ((from (first step)) (to (second step)))
    (string-append (if (= from 0) "bar" (number->string from))
                   "/"
                   (if (= to 0) "off" (number->string to)))))

(define (backgammon-play-text play)
  "A play's steps in the order they were made, in the usual notation: 13/7 8/5."
  (string-join (map backgammon-step-text (backgammon-play-steps play)) " "))

(define (backgammon-parse-steps text)
  "Reads moves written in the usual notation (24/18 13/11, bar/20, 3/off) into
a list of steps (from to). Anything else is an error."
  (map (lambda (word)
         (let ((parts (string-split word "/")))
           (if (not (= (length parts) 2))
               (error (format "not a move: {} (write moves as 24/18, bar/20 or 3/off)" word)))
           (let ((from (if (string=? (first parts) "bar") 0 (string->number (first parts))))
                 (to (if (string=? (second parts) "off") 0 (string->number (second parts)))))
             (if (not (and (number? from) (number? to)))
                 (error (format "not a move: {}" word)))
             (list from to))))
       (string-split (string-trim text) " ")))

(define (backgammon--steps-key steps)
  "The steps as one string in a fixed order, so the same moves written in a
different order give the same key."
  (string-join (sort (map backgammon-step-text steps)) " "))

(define (backgammon--join-steps steps)
  "The steps with each checker's consecutive steps made one: 13/10 10/8 becomes
13/8. A step joins an earlier one when it starts where that one ended on the
board (not off the board)."
  (let ((joined '()))
    (dolist (step steps)
      (let ((earlier (find-if (lambda (other) (and (> (second other) 0) (= (second other) (first step))))
                              joined)))
        (if earlier
            (set! joined (map (lambda (other)
                                (if (eq? other earlier) (list (first other) (second step)) other))
                              joined))
            (set! joined (append joined (list step))))))
    joined))

(define (backgammon-find-play plays steps)
  "The play whose moves are these steps (in any order), or #f if there is none.
A checker's moves may be written as one: with a roll of 3-2, 13/8 is the play
13/10 10/8 or 13/11 11/8, whichever the board allows."
  (let ((key (backgammon--steps-key steps)) (found #f))
    (dolist (play plays)
      (if (and (not found)
               (or (string=? key (backgammon--steps-key (backgammon-play-steps play)))
                   (string=? key (backgammon--steps-key
                                  (backgammon--join-steps (backgammon-play-steps play))))))
          (set! found play)))
    found))

(define (backgammon--count-cell count)
  "A three-character cell showing a count of more than five checkers."
  (if (< count 10)
      (format " {:d} " count)
      (format "{:d} " count)))

(define (backgammon-show board)
  "Draws the board from the mover's point of view: its checkers are X and the
opponent's O. Points 24 to 13 run along the top and 12 to 1 along the bottom,
so the mover's home board is at the bottom. Checkers are stacked from the
number of their point toward the middle of the board. A point with more than
five checkers shows its count in the cell farthest from the number."
  (let* ((top (loop for point from 24 downto 13 collect point))
         (bottom (loop for point from 1 to 12 collect point))
         (cell (lambda (point row)
                 (let ((count (vector-ref board point)))
                   (cond ((and (> count 0) (<= row count))
                          (if (and (= row 5) (> count 5)) (backgammon--count-cell count) " X "))
                         ((and (< count 0) (<= row (- count)))
                          (if (and (= row 5) (< count -5)) (backgammon--count-cell (- count)) " O "))
                         (else " . ")))))
         (line (lambda (points row)
                 (string-join (map (lambda (point) (cell point row)) points) "")))
         (label (lambda (point)
                  (if (< point 10) (format "  {:d}" point) (format " {:d}" point)))))
    (display (format "bar: X {}  O {}      off: X {}  O {}\n"
                     (vector-ref board 0) (- (vector-ref board 25))
                     (backgammon-off board) (backgammon-opponent-off board)))
    (display (format " {}\n" (string-join (map label top) "")))
    (loop for row from 1 to 5
          do (display (format " {}\n" (line top row))))
    (display " ---------------------------------------\n")
    (loop for row from 5 downto 1
          do (display (format " {}\n" (line bottom row))))
    (display (format " {}\n" (string-join (map label bottom) "")))))
