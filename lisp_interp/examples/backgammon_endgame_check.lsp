; backgammon_endgame_check.lsp
;
; Checks a trained backgammon network on positions where the exact chance of
; winning is easy to work out: each side has some checkers left, all of them on
; its own 1 point (the mover's on point 1, the opponent's on point 24 of the
; board the mover sees), and each side has already borne off at least one
; checker, so no game can be a gammon. Every roll then bears off two checkers
; (four on doubles, a one in six chance), and whoever bears off the last one
; first wins. So the chance that the player on roll wins with a checkers
; against b is
;   P(a, b) = 1/6 * (1 if a <= 4, else 1 - P(b, a - 4))
;           + 5/6 * (1 if a <= 2, else 1 - P(b, a - 2))
; This compares that with the network's chance of a win in the same position,
; for the networks named on the command line:
;   python3 ../lisp_interpreter.py backgammon_endgame_check.lsp net1.txt net2.txt

(define largest 14)                          ; checkers left on each side, at most

(define (exact-table)
  "The exact chances P(a, b), for a and b from 0 to largest, in one vector: the
entry for a and b is at a * (largest + 1) + b. Positions are filled in order of
the total number of checkers, since each roll leaves fewer."
  (let ((table (make-vector (* (+ largest 1) (+ largest 1)) 0.0))
        (at (lambda (a b) (+ (* a (+ largest 1)) b))))
    (loop for total from 2 to (* 2 largest)
          do (loop for a from (max 1 (- total largest)) to (min largest (- total 1))
                   do (let* ((b (- total a))
                             (after-doubles (if (<= a 4) 1 (- 1 (vector-ref table (at b (- a 4))))))
                             (after-other-rolls (if (<= a 2) 1 (- 1 (vector-ref table (at b (- a 2)))))))
                        (vector-set! table (at a b)
                                     (+ (* (/ 1.0 6) after-doubles) (* (/ 5.0 6) after-other-rolls))))))
    table))

(define (endgame-board a b)
  "The position for the player on roll, with a checkers on its 1 point against
b checkers on the opponent's 1 point (point 24 of this board)."
  (let ((board (make-vector 26 0.0)))
    (vector-set! board 1 a)
    (vector-set! board 24 (- b))
    board))

(define (network-chance net a b)
  "The network's chance that the player on roll wins: one minus the chance it
gives the other player, who has just moved there in the flipped position."
  (- 1 (vector-ref (backgammon-network-outcomes net (backgammon-flip (endgame-board a b))) 0)))

(define exact (exact-table))

(define (exact-chance a b) (vector-ref exact (+ (* a (+ largest 1)) b)))

(define shown '(1 2 3 4 5 6 8 10 12 14))

(dolist (file (command-line-arguments))
  (let ((net (backgammon-load-net file))
        (error-sum 0) (error-count 0) (worst 0) (worst-at '()))
    (display (format "\n{}\nChance that the player on roll wins, with a checkers against b (exact / network):\n" file))
    (display "   a\\b  ")
    (dolist (b shown) (display (format "{:>12}" b)))
    (display "\n")
    (loop for a from 1 to largest
          do (begin
               (if (member a shown) (display (format "   {:>3}  " a)))
               (loop for b from 1 to largest
                     do (let ((gap (abs (- (network-chance net a b) (exact-chance a b)))))
                          (set! error-sum (+ error-sum gap))
                          (set! error-count (+ error-count 1))
                          (if (> gap worst) (begin (set! worst gap) (set! worst-at (list a b))))
                          (if (and (member a shown) (member b shown))
                              (display (format "  {:.2f}/{:.2f}" (exact-chance a b) (network-chance net a b))))))
               (if (member a shown) (display "\n"))))
    (display (format "average difference {:.3f}; worst {:.3f} at {} checkers against {}\n"
                     (/ error-sum error-count) worst (first worst-at) (second worst-at)))))
