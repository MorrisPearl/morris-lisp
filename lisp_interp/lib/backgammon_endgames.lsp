; backgammon_endgames.lsp
;
; End games of backgammon whose exact chance of winning can be worked out, and
; training the network on them. The positions are those where neither side has
; any checker outside its own home board, and each side has either at most
; three checkers left, or any number of checkers all on its 1 point (a "stack").
; Both sides have borne off at least one checker, so no game can be a gammon,
; and no checker can be hit, so the game is a pure race. From a position the
; player on roll chooses, for each of the 36 rolls, the play that gives the best
; chance of winning, so the chance of winning is found by working backwards from
; the positions where somebody has borne off every checker.
;
; The positions are kept in an endgame-set: the side states (the way one side
; can have its checkers), a board for each as the player on roll sees it and as
; the opponent sees it, and the chance of winning for the player on roll for
; every pair of side states.

(defstruct endgame-set
  count          ; the number of side states
  mover-rows     ; for each side state, a board (26 numbers) with its checkers positive: the player on roll
  opponent-rows  ; for each side state, a board with its checkers negative on points 19 to 24: the opponent
  chances)       ; the chance the player on roll wins, for the pair (i, j): entry i * count + j

(define backgammon-endgame-largest-stack 14)

(define backgammon-endgame-most-checkers 3)

(define (backgammon--compositions total parts)
  "Every list of parts whole numbers (0 or more) that add up to total."
  (if (= parts 1)
      (list (list total))
      (let ((lists '()))
        (loop for first-part from 0 to total
              do (dolist (rest-of-list (backgammon--compositions (- total first-part) (- parts 1)))
                   (set! lists (cons (cons first-part rest-of-list) lists))))
        (reverse lists))))

(define (backgammon--side-states)
  "The ways one side can have its checkers: as counts on its points 1 to 6,
every way of having 1 to backgammon-endgame-most-checkers checkers in the home
board, and stacks of more checkers on the 1 point."
  (let ((states '()))
    (loop for checkers from 1 to backgammon-endgame-most-checkers
          do (set! states (append states (backgammon--compositions checkers 6))))
    (loop for checkers from (+ backgammon-endgame-most-checkers 1) to backgammon-endgame-largest-stack
          do (set! states (append states (list (list checkers 0 0 0 0 0)))))
    states))

(define (backgammon--mover-row counts)
  "A board with these counts on points 1 to 6 as the checkers of the player on roll."
  (vector-append (vector 0.0) (list->vector counts) (make-vector 19 0.0)))

(define (backgammon--opponent-row counts)
  "A board with these counts on the opponent's points 1 to 6, which are points
24 down to 19 as the player on roll sees them, as negative numbers."
  (vector-append (make-vector 19 0.0) (vector-mul -1.0 (list->vector (reverse counts))) (vector 0.0)))

(define (backgammon-endgame-board endgames i j)
  "The position with the player on roll in side state i and the opponent in side state j."
  (let ((width 26))
    (vector-add (vector-slice (endgame-set-mover-rows endgames) (* i width) (* (+ i 1) width))
                (vector-slice (endgame-set-opponent-rows endgames) (* j width) (* (+ j 1) width)))))

; ---------------------------------------------------------------------------
; The exact chances
; ---------------------------------------------------------------------------

(define backgammon--endgame-rolls
  (let ((rolls '()))
    (loop for low from 1 to 6
          do (loop for high from low to 6
                   do (set! rolls (cons (if (= low high)
                                            (list (list low low low low) (/ 1.0 36))
                                            (list (list low high) (/ 2.0 36)))
                                        rolls))))
    rolls))

(define backgammon--endgame-chances-so-far (make-hash-table))

(define backgammon--mover-weights
  (vector-append (vector 0.0) (list->vector (map (lambda (k) (expt 16.0 k)) (iota 6))) (make-vector 19 0.0)))

(define backgammon--opponent-weights
  (vector-append (make-vector 19 0.0) (list->vector (map (lambda (k) (expt 16.0 k)) (iota 6))) (vector 0.0)))

(define (backgammon--endgame-key board)
  "One number for a position of this kind: the counts on the points of the
player on roll, and those of the opponent, each as the digits of a number in base 16."
  (- (* 16777216.0 (vector-sum (* board backgammon--mover-weights)))
     (vector-sum (* board backgammon--opponent-weights))))

(define (backgammon-endgame-chance board)
  "The chance that the player on roll wins this end game (see the top of this
file), when both sides play to win as often as they can."
  (let* ((key (backgammon--endgame-key board))
         (known (hash-table-ref backgammon--endgame-chances-so-far key)))
    (if known
        known
        (let ((chance 0.0))
          (dolist (roll backgammon--endgame-rolls)
            (let ((best 0.0))
              (dolist (play (backgammon-plays board (first roll)))
                (let* ((after (backgammon-play-board play))
                       (value (if (backgammon-game-over? after)
                                  1.0
                                  (- 1.0 (backgammon-endgame-chance (backgammon-flip after))))))
                  (if (> value best) (set! best value))))
              (set! chance (+ chance (* (second roll) best)))))
          (hash-table-set! backgammon--endgame-chances-so-far key chance)
          chance))))

(define (backgammon-endgames)
  "Every end game of the kind described at the top of this file, with the exact
chance of winning for the player on roll, as an endgame-set."
  (let* ((states (backgammon--side-states))
         (count (length states))
         (mover-rows (apply vector-append (map backgammon--mover-row states)))
         (opponent-rows (apply vector-append (map backgammon--opponent-row states)))
         (endgames (make-endgame-set :count count :mover-rows mover-rows :opponent-rows opponent-rows
                                     :chances (make-vector (* count count) 0.0))))
    (dotimes (i count)
      (dotimes (j count)
        (vector-set! (endgame-set-chances endgames) (+ (* i count) j)
                     (backgammon-endgame-chance (backgammon-endgame-board endgames i j)))))
    endgames))

; ---------------------------------------------------------------------------
; The network on end games
; ---------------------------------------------------------------------------

(define (backgammon-endgame-network-chance net board)
  "The network's chance that the player on roll wins: one minus the chance it
gives the other player, who has just moved to the position seen from his side."
  (- 1.0 (vector-ref (backgammon-outcomes net (backgammon-flip board)) 0)))

(define (backgammon-endgame-held-out? endgames k)
  "Whether pair number k (i * count + j) is kept out of the training, to see
how well the network does on positions it has not been taught: one in ten."
  (= (mod k 10) 0))

(define (backgammon-endgame-error net endgames held-out samples)
  "The average difference between the network's chance of winning and the exact
chance, over samples random positions that are held out of the training
(held-out #t) or are used in it (held-out #f)."
  (let ((total 0.0) (found 0) (count (endgame-set-count endgames)))
    (loop while (< found samples)
          do (let* ((k (random-int 0 (- (* count count) 1))))
               (if (eq? held-out (backgammon-endgame-held-out? endgames k))
                   (let ((board (backgammon-endgame-board endgames (quotient k count) (mod k count))))
                     (set! total (+ total (abs (- (backgammon-endgame-network-chance net board)
                                                  (vector-ref (endgame-set-chances endgames) k)))))
                     (set! found (+ found 1))))))
    (/ total samples)))

(define (backgammon-learn-endgames! net endgames steps learning-rate)
  "Teaches the network the exact chance of winning in steps random end games
that are not held out. Each step moves the weights toward the exact outputs for
the position as the opponent, who has just moved there, sees it: it wins with
the chance 1 minus the player on roll's, and there are no gammons."
  (let ((count (endgame-set-count endgames)) (done 0))
    (loop while (< done steps)
          do (let ((k (random-int 0 (- (* count count) 1))))
               (if (not (backgammon-endgame-held-out? endgames k))
                   (let* ((board (backgammon-endgame-board endgames (quotient k count) (mod k count)))
                          (seen (backgammon-flip board))
                          (current (backgammon--outputs-and-gradients net seen))
                          (chance (vector-ref (endgame-set-chances endgames) k)))
                     (backgammon--learn! net (backgammon--zero-traces net) (first current) (rest current)
                                         (vector (- 1.0 chance) 0.0 0.0 0.0 0.0)
                                         learning-rate 0.0)
                     (set! done (+ done 1))))))))
