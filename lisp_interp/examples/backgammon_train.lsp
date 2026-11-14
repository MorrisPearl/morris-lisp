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
; Run it from the examples directory. The arguments are the number of games,
; the number of hidden units, the file for the network and the number of games
; to play first against the heuristic player (the rest are self-play):
;   python3 ../lisp_interpreter.py backgammon_train.lsp 1000 40 backgammon_net.txt 0
; The defaults are 1000 games, 40 hidden units, backgammon_net.txt and 0
; heuristic games (all self-play). Expect
; a game to take a second or two, so 1000 games take a while (the reports
; show how far it has got). Then play it with backgammon_play.lsp.

(destructuring-bind (&optional (games "1000") (hidden "40") (file "backgammon_net.txt") (heuristic-games "0"))
    (command-line-arguments)
  (let ((games (string->number games))
        (heuristic-games (string->number heuristic-games))
        (net (backgammon-new-net :hidden (string->number hidden)))
        (played 0))
    (random-seed 1)
    (display (format "Training a network with {} hidden units for {} games; it is saved in {}\n"
                     (string->number hidden) games file))
    (if (> heuristic-games 0)
        (display (format "The first {} games are against the heuristic player, the rest self-play\n"
                         heuristic-games)))
    (loop while (< played games)
          do (let* ((against-heuristic (< played heuristic-games))
                    (stage-end (if against-heuristic heuristic-games games))
                    (batch (min 100 (- stage-end played)))
                    (average-moves (if against-heuristic
                                       (backgammon-train-against-heuristic! net batch)
                                       (backgammon-train! net batch))))
               (set! played (+ played batch))
               (display (format "{} games: {:.1f} moves a game\n" played average-moves))
               (if (= (mod played 500) 0)
                   (display (format "    points a game against random play: {:+.2f}   against the heuristic: {:+.2f}\n"
                                    (backgammon-match (backgammon-network-policy net)
                                                      (backgammon-random-policy) 20)
                                    (backgammon-match (backgammon-network-policy net)
                                                      (backgammon-heuristic-policy) 20))))
               (backgammon-save-net net file)))
    (display (format "Saved in {}\n" file))))
