; backgammon_train.lsp
;
; Teaches a neural network to play backgammon by playing against itself, as
; TD-Gammon did (Tesauro, 1995). It starts knowing nothing: its weights are
; random, so at first it plays badly. Each game is the network against
; itself, and after every move it learns from the position it reached, using
; TD(lambda) (see lib/backgammon_net.lsp). Every 100 games it reports its
; average game length, and every 500 games the points a game it wins against
; a player that chooses moves at random and against a simple heuristic player
; that counts hits, points and blots. Games are scored with gammons and the
; doubling cube (the network doubles by its own expected score, see
; lib/backgammon_net.lsp). The network is saved in a file after each report,
; so a run can be stopped and the file played against.
;
; Run it from the examples directory. The arguments are, in order: the number
; of games, the number of hidden units, the file for the network, the number of
; games to play first against the heuristic player (the rest are self-play), a
; random seed, and the trace decay (lambda) at the start and at the end of
; training. The trace decay changes in a straight line over the games; equal
; values keep it constant:
;   python3 ../lisp_interpreter.py backgammon_train.lsp 5000 40 net.txt 0 1 0.9 0.3
; The defaults are 1000 games, 40 hidden units, backgammon_net.txt, 0 heuristic
; games, seed 1 and a trace decay of 0.7 throughout. Expect a game to take a
; few seconds, so 1000 games take a while (the reports show how far it has got).
; Then play it with backgammon_play.lsp.

(destructuring-bind (&optional (games "1000") (hidden "40") (file "backgammon_net.txt")
                     (heuristic-games "0") (seed "1") (lambda-start "0.7") (lambda-end "0.7"))
    (command-line-arguments)
  (let ((games (string->number games))
        (heuristic-games (string->number heuristic-games))
        (lambda-start (string->number lambda-start))
        (lambda-end (string->number lambda-end))
        (played 0))
    (random-seed (string->number seed))
    (let ((net (backgammon-new-net :hidden (string->number hidden))))
      (display (format "Training a network with {} hidden units for {} games; it is saved in {}\n"
                       (string->number hidden) games file))
      (if (> heuristic-games 0)
          (display (format "The first {} games are against the heuristic player, the rest self-play\n"
                           heuristic-games)))
      (loop while (< played games)
            do (let* ((against-heuristic (< played heuristic-games))
                      (stage-end (if against-heuristic heuristic-games games))
                      (batch (min 100 (- stage-end played)))
                      ; the trace decay for this batch, at its middle game
                      (decay (+ lambda-start (* (- lambda-end lambda-start)
                                                (/ (+ played (/ batch 2)) games))))
                      (average-moves (if against-heuristic
                                         (backgammon-train-against-heuristic! net batch :trace-decay decay)
                                         (backgammon-train! net batch :trace-decay decay))))
                 (set! played (+ played batch))
                 (display (format "{} games: {:.1f} moves a game, trace decay {:.2f}\n"
                                  played average-moves decay))
                 (if (= (mod played 500) 0)
                     (display (format "    points a game against random play: {:+.2f}   against the heuristic: {:+.2f}\n"
                                      (backgammon-match (backgammon-network-policy net)
                                                        (backgammon-random-policy) 20)
                                      (backgammon-match (backgammon-network-policy net)
                                                        (backgammon-heuristic-policy) 20))))
                 (backgammon-save-net net file)))
      (display (format "Saved in {}\n" file)))))
