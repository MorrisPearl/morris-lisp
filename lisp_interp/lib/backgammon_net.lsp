; backgammon_net.lsp
;
; A neural network that learns backgammon by playing itself, as TD-Gammon
; did (Tesauro, "Temporal Difference Learning and TD-Gammon", Communications
; of the ACM, 1995), with gammons and the doubling cube. The rules are in
; backgammon.lsp; this file has the network, its inputs, the learning, the
; policies that choose plays and cube decisions, the matches, and the game
; against the network.
;
; THE NETWORK. One hidden layer of sigmoid units, and five sigmoid outputs,
; each the chance of an event for the player who just moved to the position
; (the mover, as in backgammon.lsp):
;   output 0  the mover wins (a single game or more)
;   output 1  the mover wins a gammon or a backgammon
;   output 2  the mover wins a backgammon
;   output 3  the mover loses a gammon or a backgammon
;   output 4  the mover loses a backgammon
; These are cumulative events, as TD-Gammon's outputs are, so a good network
; keeps output 1 at most output 0, and output 2 at most output 1. From them,
; the expected score for the mover (backgammon-value, in points) is
;   2 * output 0 + output 1 + output 2 - 1 - output 3 - output 4:
; a single win is +1, a gammon +2, a backgammon +3, and the losses their
; negatives. The network plays by that score. A finished game's outcome is one
; of three vectors for its winner (backgammon-outcome), and the outputs of the
; loser are the mirror of the winner's (backgammon-mirror).
;
; THE INPUTS. 211 numbers, made by backgammon-features:
;   198 raw inputs, as TD-Gammon's board encoding: for each side, 24 points
;       times 4 units (one unit for at least one checker, one for at least two,
;       one for exactly three, and 0.5 times the checkers beyond three), then
;       the checkers on the bar (halved), the checkers borne off (divided by
;       15) and one unit for the side whose turn is next.
;   12 crafted features, for each side: blots (single checkers), points made,
;       points made in its home board, advanced anchors (points made in the
;       opponent's home board), the longest run of points made in a row (a
;       prime), and the pip count. These are concepts that expert players use
;       and that the raw board only shows indirectly.
;   1 constant 1, so that a unit's bias is one more weight.
;
; THE LEARNING. TD(lambda), with an eligibility trace for every weight, for
; each output. After each move, the network's outputs for the position just
; reached are compared with the target for the position before, which is the
; mirror of them (the opponent's view of the same position); at the end of a
; game the target is the winner's outcome. Each output's error moves every
; weight in proportion to that weight's trace for the output: the trace is how
; much the weight has helped that output lately, and it fades by trace-decay
; each move, so that an error reaches back over the moves that led to it.
; Learning uses no cube, as TD-Gammon's did: the cube is decided by the
; policies below, from the network's expected score.
;
; THE CUBE. The cube doubles the stakes: it starts at 1 and may be doubled to
; 2, 4, ... 64, by a player who owns it or when nobody does. The other player
; takes, and then owns the cube at its doubled value, or drops and loses the
; value it had. A policy doubles when the expected score for the player on roll
; is at least double-at, and below too-good (above that it plays on for the
; gammon). A taker takes unless the doubler's expected score is above 0.5: the
; taker's score then is worse than -0.5, and twice that is worse than the
; point it loses by dropping.

(define backgammon-inputs 211)
(define backgammon-outputs 5)

(defstruct backgammon-net hidden hidden-weights output-weights)

; How a player chooses. choose (board plays) returns the play to make; double
; (board) says whether to double, and take (board) whether to take a double.
; board is from the point of view of the player on roll, who is the doubler when
; take is asked.
(defstruct backgammon-policy choose double take)

(define (backgammon-new-net &key (hidden 40))
  "A network with the given number of hidden units and small random weights
(random-seed makes them repeatable). The hidden weights are one row of 211 for
each unit, as one flat vector. The output weights are one row for each output:
a weight for each hidden unit, then one for the bias, as one flat vector."
  (make-backgammon-net :hidden hidden
                       :hidden-weights (vector-mul 0.1 (random-normal-vector (* hidden backgammon-inputs)))
                       :output-weights (vector-mul 0.1 (random-normal-vector (* backgammon-outputs (+ hidden 1))))))

; ---------------------------------------------------------------------------
; The inputs
; ---------------------------------------------------------------------------

(define (backgammon--side-raw board on-roll)
  "The 99 raw inputs for the side whose checkers are positive in board (the
mover's point of view), with on-roll 1 if it is that side's turn."
  (let ((counts (vector-clip (vector-slice board 1 25) 0 '())))
    (vector-append (>= counts 1)
                   (>= counts 2)
                   (= counts 3)
                   (vector-mul 0.5 (vector-clip (vector-sub counts 3) 0 '()))
                   (vector (/ (vector-ref board 0) 2)
                           (/ (backgammon-off board) 15)
                           on-roll))))

(define (backgammon--longest-prime counts)
  "The longest run of consecutive points with two or more checkers, among the
24 points of counts (point 1 first). The points that are not made split the
points into runs: the gaps between them, from a point 0 before point 1 to a
point 25 after point 24, are one more than the runs."
  (let ((open-points (vector-select backgammon-point-numbers (< counts 2))))
    (- (vector-max (vector-diff (vector-append (vector 0) open-points (vector 25)))) 1)))

(define (backgammon--side-crafted board)
  "The 6 crafted features of the side whose checkers are positive in board."
  (let* ((counts (vector-clip (vector-slice board 1 25) 0 '()))
         (made (>= counts 2)))
    (vector (/ (vector-sum (= counts 1)) 6)
            (/ (vector-sum made) 12)
            (/ (vector-sum (vector-slice made 0 6)) 6)
            (/ (vector-sum (vector-slice made 18 24)) 6)
            (/ (backgammon--longest-prime counts) 6)
            (/ (backgammon-pips board) 167))))

(define (backgammon-features board)
  "The 211 inputs of the network for a position, from the point of view of the
player who just moved (the mover of board): the raw inputs, the crafted
features, and a constant 1."
  (let ((opponent (backgammon-flip board)))
    (vector-append (backgammon--side-raw board 0)
                   (backgammon--side-raw opponent 1)
                   (backgammon--side-crafted board)
                   (backgammon--side-crafted opponent)
                   (vector 1.0))))

; ---------------------------------------------------------------------------
; Evaluating a position
; ---------------------------------------------------------------------------

(define (backgammon-sigmoid z)
  "The squashing function 1 / (1 + e^-z), of a number or of each number in a vector."
  (/ 1 (+ 1 (exp (- z)))))

(define (backgammon--hidden-units net inputs)
  "The hidden units' outputs for these inputs, as a vector."
  (backgammon-sigmoid (matrix-vector-product (backgammon-net-hidden-weights net) inputs)))

(define (backgammon-outcomes net board)
  "The network's five outputs for a position (see the top of this file), from
the point of view of the player who just moved to it."
  (let ((hidden (backgammon--hidden-units net (backgammon-features board))))
    (backgammon-sigmoid (matrix-vector-product (backgammon-net-output-weights net)
                                               (vector-append hidden (vector 1.0))))))

(define (backgammon-equity-of outcomes)
  "The expected score in points for the mover, from its five outputs."
  (- (+ (* 2 (vector-ref outcomes 0)) (vector-ref outcomes 1) (vector-ref outcomes 2) -1)
     (vector-ref outcomes 3)
     (vector-ref outcomes 4)))

(define (backgammon-value net board)
  "The network's estimate of the expected score, in points, for the player who
just moved to this position: from -3 (a backgammon lost) to 3 (one won)."
  (backgammon-equity-of (backgammon-outcomes net board)))

(define (backgammon-expected-points net board)
  "The expected score, in points, for the player on roll at this position (the
mover of board, who has not moved yet): the other player's, negated."
  (- (backgammon-value net (backgammon-flip board))))

(define (backgammon-outcome result)
  "The outputs the network should have for a winner, given the result of the
game (1 for a single game, 2 for a gammon, 3 for a backgammon; see
backgammon-result)."
  (cond ((= result 1) (vector 1.0 0.0 0.0 0.0 0.0))
        ((= result 2) (vector 1.0 1.0 0.0 0.0 0.0))
        (else (vector 1.0 1.0 1.0 0.0 0.0))))

(define (backgammon-mirror outcomes)
  "The outputs for the other player, from those of the player who moved: its
wins are our losses, and the gammons of each side swap places."
  (vector (- 1 (vector-ref outcomes 0))
          (vector-ref outcomes 3)
          (vector-ref outcomes 4)
          (vector-ref outcomes 1)
          (vector-ref outcomes 2)))

(define (backgammon--outputs-and-gradients net board)
  "The network's five outputs for the position, and their gradients with
respect to the weights, as a list (outputs hidden-gradients output-gradients).
The hidden gradients are one block the size of the hidden weights for each
output, one after another; the output gradients are one row of the output
weights for each output. Back-propagation, all five outputs at once: the
error entries are one for each output and hidden unit, found by index vectors
(which output and which unit each entry is), so that one outer product gives
every hidden gradient."
  (let* ((inputs (backgammon-features board))
         (hidden (backgammon--hidden-units net inputs))
         (extended (vector-append hidden (vector 1.0)))
         (outputs (backgammon-sigmoid (matrix-vector-product (backgammon-net-output-weights net) extended)))
         (slopes (* outputs (- 1 outputs)))
         (hidden-slopes (* hidden (- 1 hidden)))
         (units (backgammon-net-hidden net))
         (row-length (+ units 1))
         (entries (list->vector (iota (* backgammon-outputs units))))
         (entry-unit (mod entries units))                 ; the hidden unit each entry is about
         (entry-output (quotient entries units))          ; the output each entry is about
         (to-hidden (vector-select (backgammon-net-output-weights net)     ; the output weights from the hidden units
                                   (< (mod (list->vector (iota (* backgammon-outputs row-length))) row-length) units)))
         (hidden-errors (* (vector-gather slopes entry-output)
                           (vector-mul to-hidden (vector-gather hidden-slopes entry-unit)))))
    (list outputs
          (vector-outer hidden-errors inputs)
          (vector-outer slopes extended))))

; ---------------------------------------------------------------------------
; Learning
; ---------------------------------------------------------------------------

(define (backgammon--learn! net traces outputs gradients target learning-rate trace-decay)
  "One TD(lambda) step. The error of each output is its target minus its value
at the position learned from (outputs). Each output's trace is its gradient
added to its trace faded by trace-decay, and each weight moves by learning-rate
times the sum over the outputs of their errors times their traces. traces and
gradients are each a list (hidden output), and the result is the new traces in
the same form."
  (let* ((gap (- target outputs))
         (hidden-trace (vector-add (vector-mul trace-decay (first traces)) (first gradients)))
         (output-trace (vector-add (vector-mul trace-decay (second traces)) (second gradients)))
         (row-length (+ (backgammon-net-hidden net) 1)))
    (setf (backgammon-net-hidden-weights net)
          (vector-add (backgammon-net-hidden-weights net)
                      (vector-mul learning-rate (transpose-matrix-vector-product hidden-trace gap))))
    (setf (backgammon-net-output-weights net)
          (vector-add (backgammon-net-output-weights net)
                      (vector-mul learning-rate
                                  (vector-mul (vector-outer gap (make-vector row-length 1.0))
                                              output-trace))))
    (list hidden-trace output-trace)))

(define (backgammon--zero-traces net)
  "Eligibility traces of zero, one for each weight of each output."
  (list (make-vector (* backgammon-outputs (vector-length (backgammon-net-hidden-weights net))) 0.0)
        (make-vector (vector-length (backgammon-net-output-weights net)) 0.0)))

(define (backgammon--best-play net plays)
  "The play whose position the network values most for the mover. Ties go to
the first such play."
  (let ((best (first plays)) (best-value -1000))
    (dolist (play plays)
      (let ((value (backgammon-value net (backgammon-play-board play))))
        (if (> value best-value)
            (begin
              (set! best play)
              (set! best-value value)))))
    best))

(define (backgammon--self-play-game! net learning-rate trace-decay)
  "One game of the network against itself, learning from every move. Returns
the number of moves made (plies). A game that runs past 1000 moves is cut off
and learns nothing from its end."
  (let* ((board (backgammon-start))
         (dice (backgammon-opening-roll))
         (traces (backgammon--zero-traces net))
         (previous #f)
         (moves 0)
         (finished #f))
    (loop while (not finished)
          do (let* ((play (backgammon--best-play net (backgammon-plays board dice)))
                    (after (backgammon-play-board play))
                    (current (backgammon--outputs-and-gradients net after)))
               (set! moves (+ moves 1))
               (if previous
                   (set! traces (backgammon--learn! net traces (first previous) (rest previous)
                                                    (backgammon-mirror (first current))
                                                    learning-rate trace-decay)))
               (cond ((backgammon-game-over? after)
                      (set! traces (backgammon--learn! net traces (first current) (rest current)
                                                       (backgammon-outcome (backgammon-result after))
                                                       learning-rate trace-decay))
                      (set! finished #t))
                     ((> moves 1000)
                      (set! finished #t))
                     (else
                      (set! previous current)
                      (set! board (backgammon-flip after))
                      (set! dice (backgammon-roll))))))
    moves))

(define (backgammon--heuristic-game! net learning-rate trace-decay)
  "One game of the network against the heuristic player, learning only from the
network's own moves. Each of the network's positions is learned from the next
position the network reaches, the heuristic's move in between being part of the
game the network learns from. Returns the number of moves made (plies), as
backgammon--self-play-game! does."
  (let* ((board (backgammon-start))
         (dice (backgammon-opening-roll))
         (heuristic (backgammon-policy-choose (backgammon-heuristic-policy)))
         (traces (backgammon--zero-traces net))
         (net-to-move (= (random-int 0 1) 0))
         (previous #f)
         (moves 0)
         (finished #f))
    (loop while (not finished)
          do (let* ((plays (backgammon-plays board dice))
                    (after (backgammon-play-board
                            (if net-to-move
                                (backgammon--best-play net plays)
                                (heuristic board plays))))
                    (over (backgammon-game-over? after))
                    (current (if net-to-move (backgammon--outputs-and-gradients net after) #f)))
               (set! moves (+ moves 1))
               (cond ((and net-to-move over)
                      (if previous
                          (set! traces (backgammon--learn! net traces (first previous) (rest previous)
                                                           (first current) learning-rate trace-decay)))
                      (set! traces (backgammon--learn! net traces (first current) (rest current)
                                                       (backgammon-outcome (backgammon-result after))
                                                       learning-rate trace-decay))
                      (set! finished #t))
                     (net-to-move
                      (if previous
                          (set! traces (backgammon--learn! net traces (first previous) (rest previous)
                                                           (first current) learning-rate trace-decay)))
                      (set! previous current))
                     (over
                      (if previous
                          (set! traces (backgammon--learn! net traces (first previous) (rest previous)
                                                           (backgammon-mirror (backgammon-outcome (backgammon-result after)))
                                                           learning-rate trace-decay)))
                      (set! finished #t))
                     (else #f))
               (if (and (not finished) (> moves 1000))
                   (set! finished #t))
               (if (not finished)
                   (begin
                     (set! board (backgammon-flip after))
                     (set! dice (backgammon-roll))
                     (set! net-to-move (not net-to-move))))))
    moves))

(define (backgammon-train-against-heuristic! net games &key (learning-rate 0.1) (trace-decay 0.7))
  "Like backgammon-train!, but each game is the network against the heuristic
player (backgammon-heuristic-policy), and the network learns only from its own
moves. Changes net in place and returns the average number of moves per game."
  (let ((total 0))
    (dotimes (game games)
      (set! total (+ total (backgammon--heuristic-game! net learning-rate trace-decay))))
    (/ total games)))

(define (backgammon-train! net games &key (learning-rate 0.1) (trace-decay 0.7))
  "Trains the network by playing GAMES games of itself (see the top of this
file). learning-rate is how far each step moves the weights, and trace-decay
(lambda) how far back in the game each move's error reaches. Changes net in
place and returns the average number of moves per game."
  (let ((total 0))
    (dotimes (game games)
      (set! total (+ total (backgammon--self-play-game! net learning-rate trace-decay))))
    (/ total games)))

; ---------------------------------------------------------------------------
; Policies: how a player chooses plays and cube decisions
; ---------------------------------------------------------------------------

(define (backgammon-network-policy net &key (double-at 0.6) (too-good 1.2))
  "A policy that plays by the network's expected score, and that doubles when
that score for the player on roll is at least double-at and below too-good.
It takes a double unless the doubler's expected score is above 0.5."
  (make-backgammon-policy
   :choose (lambda (board plays) (backgammon--best-play net plays))
   :double (lambda (board)
             (let ((points (backgammon-expected-points net board)))
               (and (>= points double-at) (< points too-good))))
   :take (lambda (board) (<= (backgammon-expected-points net board) 0.5))))

(define (backgammon-random-policy)
  "A policy that chooses plays at random, never doubles, and always takes."
  (make-backgammon-policy
   :choose (lambda (board plays) (nth (random-int 0 (- (length plays) 1)) plays))
   :double (lambda (board) #f)
   :take (lambda (board) #t)))

(define (backgammon--heuristic-score board)
  "A rough score for a position, from the mover's point of view: checkers on
the opponent's bar, points made and blots count for more than the pips."
  (+ (* 5 (- (vector-ref board 25)))
     (* 3 (vector-sum (>= (vector-slice board 1 25) 2)))
     (* -2 (vector-sum (= (vector-slice board 1 25) 1)))))

(define (backgammon-heuristic-policy)
  "A policy that chooses the play whose position counts hits, points and blots
the best: a simple benchmark for the network. It never doubles, and always takes."
  (make-backgammon-policy
   :choose (lambda (board plays)
             (let ((best (first plays)) (best-score -1000))
               (dolist (play plays)
                 (let ((score (backgammon--heuristic-score (backgammon-play-board play))))
                   (if (> score best-score)
                       (begin
                         (set! best play)
                         (set! best-score score)))))
               best))
   :double (lambda (board) #f)
   :take (lambda (board) #t)))

; ---------------------------------------------------------------------------
; Matches: games between two policies, with the cube
; ---------------------------------------------------------------------------

(define (backgammon--play-game policy-a policy-b a-first)
  "One game between two policies, A and B; a-first says whether A moves first.
Before each roll the player on roll may double the cube, if it is centered or
its own and below 64: the other player takes (owning the cube at twice its
value) or drops (the doubler wins the value it had). A game is worth the cube
times its result (1, 2 or 3). Returns the points A wins: positive if A wins,
negative if B does, and 0 for a game cut off after 1000 moves."
  (let ((board (backgammon-start))
        (dice (backgammon-opening-roll))
        (a-to-move a-first)
        (cube 1)
        (cube-owner 'none)
        (moves 0)
        (points 0)
        (winner 'draw))
    (loop while (and (eq? winner 'draw) (< moves 1000))
          do (let* ((mover (if a-to-move 'a 'b))
                    (other (if a-to-move 'b 'a))
                    (mover-policy (if a-to-move policy-a policy-b))
                    (other-policy (if a-to-move policy-b policy-a))
                    (may-double (and (< cube 64) (or (eq? cube-owner 'none) (eq? cube-owner mover)))))
               (if (and may-double ((backgammon-policy-double mover-policy) board))
                   (if ((backgammon-policy-take other-policy) board)
                       (begin
                         (set! cube (* 2 cube))
                         (set! cube-owner other))
                       (begin
                         (set! points (if (eq? mover 'a) cube (- cube)))
                         (set! winner mover))))
               (if (eq? winner 'draw)
                   (let* ((plays (backgammon-plays board dice))
                          (after (backgammon-play-board ((backgammon-policy-choose mover-policy) board plays))))
                     (set! moves (+ moves 1))
                     (if (backgammon-game-over? after)
                         (begin
                           (set! points (* cube (backgammon-result after)))
                           (if (eq? mover 'b) (set! points (- points)))
                           (set! winner mover))
                         (begin
                           (set! board (backgammon-flip after))
                           (set! dice (backgammon-roll))
                           (set! a-to-move (not a-to-move))))))))
    (if (eq? winner 'draw) 0 points)))

(define (backgammon-match policy-a policy-b games)
  "The average points per game that policy A wins against policy B over GAMES
games (negative if A loses), with A moving first in every other game so that
neither has the advantage of starting. A game cut off after 1000 moves scores 0."
  (let ((total 0))
    (dotimes (game games)
      (set! total (+ total (backgammon--play-game policy-a policy-b (even? game)))))
    (/ total games)))

; ---------------------------------------------------------------------------
; Saving and loading the network
; ---------------------------------------------------------------------------

(define (backgammon-save-net net file)
  "Writes the network to the file, as one Lisp list that holds its numbers
exactly: (backgammon-net hidden-units hidden-weights output-weights)."
  (write-text-file file
                   (to-string (list 'backgammon-net
                                    (backgammon-net-hidden net)
                                    (backgammon-net-hidden-weights net)
                                    (backgammon-net-output-weights net))))
  file)

(define (backgammon-load-net file)
  "The network saved in the file by backgammon-save-net. A network saved before
the gammons and the cube were added has one output, not five, and is refused."
  (let ((saved (read-from-string (read-text-file file))))
    (if (not (and (list? saved) (= (length saved) 4) (eq? (first saved) 'backgammon-net)))
        (error (format "{} is not a saved backgammon network" file)))
    (let ((net (make-backgammon-net :hidden (second saved)
                                    :hidden-weights (third saved)
                                    :output-weights (fourth saved))))
      (if (not (= (vector-length (backgammon-net-output-weights net))
                  (* backgammon-outputs (+ (backgammon-net-hidden net) 1))))
          (error (format "{} has the wrong number of output weights for this program" file)))
      net)))

; ---------------------------------------------------------------------------
; Playing against the network
; ---------------------------------------------------------------------------

(define (backgammon--view-point point)
  "A point as the other player numbers it: the bar (0) and off (0) stay as
they are, and point p is 25 - p."
  (if (= point 0) 0 (- 25 point)))

(define (backgammon--dice-text dice)
  "The dice of a roll as in 3-1, or 4-4 for doubles."
  (format "{:d}-{:d}" (first dice) (second dice)))

(define (backgammon--read-answer prompt)
  "A line typed by the person, trimmed; quit if the input has ended."
  (let ((line (read-line prompt)))
    (if line (string-trim line) "quit")))

(define (backgammon--ask-for-play plays dice)
  "Asks the person for a play until they give one of the plays, which is
returned. Returns 'quit if they stop the game."
  (let ((chosen #f))
    (loop while (not chosen)
          do (let ((text (backgammon--read-answer "Your move (e.g. 24/18 13/11; ? lists the plays; quit stops): ")))
               (cond ((string=? text "quit") (set! chosen 'quit))
                     ((string=? text "?")
                      (display (format "Plays with {}:\n" (backgammon--dice-text dice)))
                      (dolist (play plays)
                        (display (format "  {}\n" (backgammon-play-text play)))))
                     (else
                      (let* ((steps (catch-error (backgammon-parse-steps text)
                                                 (message)
                                                 (begin (display (format "{}\n" message)) #f)))
                             (play (if steps (backgammon-find-play plays steps) #f)))
                        (cond (play (set! chosen play))
                              (steps (display (format "{} is not one of the plays with {} (? lists them)\n"
                                                      text (backgammon--dice-text dice))))))))))
    chosen))

(define (backgammon--human-doubles? cube)
  "Asks the person whether to double the cube, which would become twice its value."
  (string=? (backgammon--read-answer (format "Double the cube to {:d}? (double, or Enter to roll): " (* 2 cube)))
            "double"))

(define (backgammon--human-takes? cube)
  "Asks the person to take or drop a double of the cube; true to take."
  (let ((answer #f))
    (loop while (not answer)
          do (let ((text (backgammon--read-answer (format "Take the double to {:d}, or drop? (take/drop): " (* 2 cube)))))
               (cond ((string=? text "take") (set! answer 'take))
                     ((string=? text "drop") (set! answer 'drop))
                     ((string=? text "quit") (set! answer 'drop)))))
    (eq? answer 'take)))

(define (backgammon--cube-decision human-to-move policy board cube)
  "Whether the player on roll doubles, and then whether the other side takes:
returns 'no-double, 'take or 'drop. The computer's decisions come from the
policy, the person's from the questions asked."
  (let ((doubles (if human-to-move
                     (backgammon--human-doubles? cube)
                     ((backgammon-policy-double policy) board))))
    (cond ((not doubles) 'no-double)
          (human-to-move
           (if ((backgammon-policy-take policy) board) 'take 'drop))
          (else
           (display (format "The computer doubles to {:d}.\n" (* 2 cube)))
           (if (backgammon--human-takes? cube) 'take 'drop)))))

(define (play-backgammon &key (file "backgammon_net.txt") (human-first #t))
  "Plays a game of backgammon against the network saved in file (see
backgammon-save-net, and examples/backgammon_train.lsp, which makes it). You
move with the moves written as in 24/18 13/11, bar/20 or 3/off, where the
points are as on the board you are shown: the points run 24 to 13 along the top
and 12 to 1 along the bottom, and you bear off past 1. The computer's moves
are shown the same way. Before each roll the player on roll may double the
cube: the computer doubles by its network, and you type double (the computer
then takes or drops by its network, and you are asked to take or drop its
double). Type ? for the plays with your dice, quit to stop. The game is worth
the cube times 1 for a single game, 2 for a gammon, or 3 for a backgammon.
Returns 'human or 'computer for the winner, or 'quit."
  (let* ((net (backgammon-load-net file))
         (policy (backgammon-network-policy net))
         (board (backgammon-start))
         (dice (backgammon-opening-roll))
         (human-to-move human-first)
         (cube 1)
         (cube-owner 'none)
         (result #f))
    (display (format "You play {}. Points are numbered as on the board you see.\n"
                     (if human-first "first" "second")))
    (loop while (not result)
          do (let* ((mover (if human-to-move 'human 'computer))
                    (other (if human-to-move 'computer 'human))
                    (may-double (and (< cube 64) (or (eq? cube-owner 'none) (eq? cube-owner mover))))
                    (decision (if may-double
                                  (backgammon--cube-decision human-to-move policy board cube)
                                  'no-double)))
               (cond ((eq? decision 'drop)
                      (display (format "{} drop{}; {} won {:d} point{}.\n"
                                       (if human-to-move "The computer" "You")
                                       (if human-to-move "s" "")
                                       (if human-to-move "You" "The computer")
                                       cube (if (= cube 1) "" "s")))
                      (set! result mover))
                     ((eq? decision 'take)
                      (display (format "{} take{}.\n" (if human-to-move "The computer" "You")
                                       (if human-to-move "s" "")))
                      (set! cube (* 2 cube))
                      (set! cube-owner other)))
               (if (not result)
                   (let* ((view (if human-to-move board (backgammon-flip board)))
                          (plays (backgammon-plays board dice))
                          (play #f))
                     (display "\n")
                     (backgammon-show view)
                     (display (format "Cube: {:d}, {}.\n" cube
                                      (cond ((eq? cube-owner 'none) "centered")
                                            ((eq? cube-owner 'human) "yours")
                                            (else "the computer's"))))
                     (display (format "{} rolled {}.\n"
                                      (if human-to-move "You" "The computer")
                                      (backgammon--dice-text dice)))
                     (cond ((null? (backgammon-play-steps (first plays)))
                            (display (format "{} no legal move.\n" (if human-to-move "You have" "The computer has")))
                            (set! play (first plays)))
                           (human-to-move
                            (set! play (backgammon--ask-for-play plays dice))
                            (if (eq? play 'quit) (set! result 'quit)))
                           (else
                            (set! play ((backgammon-policy-choose policy) board plays))
                            (display (format "The computer plays {}.\n"
                                             (string-join
                                              (map (lambda (step)
                                                     (backgammon-step-text
                                                      (list (backgammon--view-point (first step))
                                                            (backgammon--view-point (second step)))))
                                                   (backgammon-play-steps play))
                                              " ")))))
                     (if (and (not result) (not (eq? play 'quit)))
                         (let ((after (backgammon-play-board play)))
                           (if (backgammon-game-over? after)
                               (let ((points (* cube (backgammon-result after))))
                                 (backgammon-show (if human-to-move after (backgammon-flip after)))
                                 (display (format "{} won {:d} point{}.\n"
                                                  (if human-to-move "You" "The computer")
                                                  points (if (= points 1) "" "s")))
                                 (set! result mover))
                               (begin
                                 (set! board (backgammon-flip after))
                                 (set! dice (backgammon-roll))
                                 (set! human-to-move (not human-to-move))))))))))
    result))
