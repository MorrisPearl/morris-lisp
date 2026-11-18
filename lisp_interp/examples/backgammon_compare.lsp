; backgammon_compare.lsp
;
; Plays two backgammon players against each other, with the doubling cube and
; gammons, the first player moving first in every other game, and reports the
; points a game the first player wins, with its standard error, the games it
; won, and how the games ended (a dropped double, the last checker borne off,
; or cut off after 1000 moves). Each player is a file of a trained network, or
; heuristic or random (see backgammon_train.lsp). The arguments are the two
; players, the number of games (1000 by default), 1 or 0 for whether the
; networks use the exact chances of winning in end games (1, the default; see
; EXACT END GAMES in lib/backgammon_net.lsp), and 1 or 0 for whether the cube is
; used (1, the default). Without the cube nobody doubles and every game is played
; to the end, so the points are a better measure of how well the players move: a
; network that doubles when its position is worth 0.6 or more, against one that
; drops when the double is above 0.5, often ends the game with the first double.
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py backgammon_compare.lsp net_a.txt net_b.txt 500

(define (compare-player name cube)
  "The policy for a player given by name: heuristic, random or the file of a network. Without the cube it never doubles and always takes."
  (let ((policy (cond ((= name "heuristic") (backgammon-heuristic-policy))
                      ((= name "random") (backgammon-random-policy))
                      (else (backgammon-network-policy (backgammon-load-net name))))))
    (if cube
        policy
        (make-backgammon-policy :choose (backgammon-policy-choose policy)
                                :double (lambda (board) #f)
                                :take (lambda (board) #t)))))

(destructuring-bind (player-a player-b &optional (games "1000") (exact "1") (cube "1")) (command-line-arguments)
  (let* ((games (string->number games))
         (cube (= (string->number cube) 1))
         (policy-a (compare-player player-a cube))
         (policy-b (compare-player player-b cube))
         (total 0)
         (sum-of-squares 0)
         (wins 0))
    (backgammon-use-exact-endgames! (= (string->number exact) 1))
    (random-seed 7)
    (backgammon-reset-game-endings!)
    (dotimes (game games)
      (let ((points (backgammon--play-game policy-a policy-b (even? game))))
        (set! total (+ total points))
        (set! sum-of-squares (+ sum-of-squares (* points points)))
        (if (> points 0) (set! wins (+ wins 1)))))
    (let* ((mean (/ total games))
           (variance (/ (- sum-of-squares (* games mean mean)) (- games 1))))
      (display (format "{} against {} over {} games: {:+.3f} points a game for {} (standard error {:.3f}); {} games won by {}\n"
                       player-a player-b games mean player-a (sqrt (/ variance games)) wins player-a))
      (display (format "    {} games ended by a dropped double, {} by bearing off the last checker, {} cut off\n"
                       backgammon-games-ended-by-drop backgammon-games-ended-by-bear-off
                       (- games backgammon-games-ended-by-drop backgammon-games-ended-by-bear-off))))))
