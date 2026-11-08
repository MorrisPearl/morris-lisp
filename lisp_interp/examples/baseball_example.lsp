; Baseball as a chain of states (lib/baseball.lsp; the "Baseball" manual, doc/lisp_baseball_manual.md).
;
; Fits the model to the 2015-2025 regular seasons, shows what an inning is worth in each state, and plays a real game many times, with the batting
; orders and starting pitchers it had. It needs the database that load_retrosheet_data/build_retrosheet_db.py makes.
;
;   python3 lisp_interpreter.py examples/baseball_example.lsp            Game 7 of the 2025 World Series
;   python3 lisp_interpreter.py examples/baseball_example.lsp NYA202509280   another game: Retrosheet's id for it

(load "baseball.lsp")

(destructuring-bind (&optional (game "TOR202511010")) (command-line-arguments)
  (define model (fit-baseball-model))
  (display "Runs expected in the rest of an inning, from each number of outs and runners on base (1 is a runner on first, 2 on second, 4 on third):")
  (newline)
  (display-table (run-expectancy (baseball-model-league-counts model)) :max-rows 24)
  (let ((home (baseball-team-in-game model game 1))
        (visitors (baseball-team-in-game model game 0)))
    (display "The home team's batting order: ") (display (baseball-team-lineup home)) (newline)
    (display "and its starter: ") (display (baseball-team-starter home)) (newline)
    (display "The visitors' batting order: ") (display (baseball-team-lineup visitors)) (newline)
    (display "and its starter: ") (display (baseball-team-starter visitors)) (newline)
    (let ((played (simulate-baseball-games model home visitors :games 20000 :seed 1)))
      (display "How often the home team won, in 20000 games: ")
      (display (home-win-probability played)) (newline)
      (display "Runs per game, home and visitors: ")
      (display (vector-mean (table-column played "home_runs"))) (display " ")
      (display (vector-mean (table-column played "visiting_runs"))) (newline)))
  (retrosheet-notice))
