; baseball.lsp
; ============
; Major league baseball as a chain of states, from the plays that Retrosheet has: how often each thing happened to a batter against a pitcher, and games
; played from it. The arithmetic is in lisp_baseball.py (see the top of it for what a state and an outcome are); this library reads the plays from the database
; that load_retrosheet_data/build_retrosheet_db.py makes (see the README there) and asks for the matrices of players:
;
;   (define model (fit-baseball-model))                           ; the league's matrix and how much players differ, from 2015 to 2025
;   (define judge (baseball-batter-matrix model "judga001"))      ; Aaron Judge's probabilities: what happens, from each state
;   (define skubal (baseball-pitcher-matrix model "skubt001"))
;   (simulate-baseball-games model home away :games 10000)        ; teams are made with make-baseball-team
;
; A PLAYER'S MATRIX is the probabilities of what happens in each of 336 states: the league's, tilted toward the mix of results (strikeouts, walks, singles,
; doubles, triples, home runs, other) that the player had in the seasons of the model, with the league's mix as a prior worth as many turns as the model's
; batter-strength (or pitcher-strength): see "WHAT MAKES A PLAYER DIFFERENT" in lisp_baseball.py.
;
; The information used here was obtained free of charge from and is copyrighted by Retrosheet.  Interested parties may contact Retrosheet at 20 Sunset Rd.,
; Newark, DE 19711.  (retrosheet-notice) shows it.

(define retrosheet-database "/Users/morris/retrosheet_data/retrosheet.db")
; the database that build_retrosheet_db.py makes

(define retrosheet-statement
  "The information used here was obtained free of charge from and is copyrighted by Retrosheet.  Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.")

(define (retrosheet-notice)
  "Show the statement that Retrosheet asks to appear wherever its information is used."
  (display retrosheet-statement)
  (newline))

(defstruct baseball-model
  database          ; an open connection to the database
  first-season      ; the seasons its turns are from
  last-season
  league-counts     ; how many times each outcome followed each state, in all of them
  league            ; the probabilities of those, smoothed
  batter-strength   ; how many turns the league's probabilities are worth as a prior for a batter's
  pitcher-strength  ;  and for a pitcher's
  batters           ; the matrices that have been made, by player (a hash table)
  pitchers)

(defstruct baseball-team
  lineup            ; the nine batters' ids, in the order they bat
  starter           ; the starting pitcher's id
  bullpen           ; the team (as Retrosheet abbreviates it, "NYA") whose relievers pitch after the starter, or '() for relievers in general
  starter-batters)  ; how many batters the starter faces, or '() for as many as he did in his starts in the seasons of the model

(define baseball--turn-columns "home_batting, outs, bases, score_difference, new_outs, new_bases, runs, result")

(define (baseball--where model extra)
  "The condition for turns of the model's seasons, regular season, and extra (an SQL condition, or \"1\")."
  (format "gametype = 'regular' AND season BETWEEN {} AND {} AND {}"
          (baseball-model-first-season model) (baseball-model-last-season model) extra))

(define (baseball--kinds-of-turns conn where params)
  "A table of the kinds of turn the SQL condition where picks, and how many there are of each (the column count)."
  (sqlite-query conn (format "SELECT {}, COUNT(*) AS count FROM turns WHERE {} GROUP BY {}" baseball--turn-columns where baseball--turn-columns)
                '() '() params))

(define (baseball--players-results conn player-column where)
  "A table of how many turns each player (the column player) had with each result."
  (sqlite-query conn (format "SELECT {} AS player, result, COUNT(*) AS count FROM turns WHERE {} GROUP BY {}, result" player-column where player-column)))

(define (fit-baseball-model &key (database retrosheet-database) (first-season 2015) (last-season 2025))
  "The league's matrix from the turns of the seasons, and how strongly players are pulled toward it (batter-strength and pitcher-strength): a baseball-model.
database is the file build_retrosheet_db.py made. It takes a few seconds."
  (let* ((conn (sqlite-open database))
         (model (make-baseball-model :database conn :first-season first-season :last-season last-season
                                     :batters (make-hash-table) :pitchers (make-hash-table)))
         (counts (transition-counts (baseball--kinds-of-turns conn (baseball--where model "1") '())))
         (league (smooth-transitions counts)))
    (baseball-model-league-counts-set! model counts)
    (baseball-model-league-set! model league)
    (baseball-model-batter-strength-set!
     model (prior-strength (baseball--players-results conn "batter" (baseball--where model "1")) "player" league))
    (baseball-model-pitcher-strength-set!
     model (prior-strength (baseball--players-results conn "pitcher" (baseball--where model "1")) "player" league))
    model))

(define (baseball--player-matrix model players player-column id strength extra params)
  "The matrix of a player, or a group of players, whose turns are those where player-column = id (and extra): made once, then kept in the hash table players."
  (let ((key (format "{}|{}" id extra)))
    (if (hash-table-has? players key)
        (hash-table-ref players key)
        (let* ((results (sqlite-query (baseball-model-database model)
                                      (format "SELECT result, COUNT(*) AS count FROM turns WHERE {} GROUP BY result"
                                              (baseball--where model (format "{} AND {}" player-column extra)))
                                      '() '() params))
               (matrix (tilt-transitions (baseball-model-league model) results strength)))
          (hash-table-set! players key matrix)
          matrix))))

(define (baseball-batter-matrix model batter)
  "A batter's probabilities, from his turns at bat in the model's seasons: batter is his Retrosheet id (find the id with baseball-players)."
  (baseball--player-matrix model (baseball-model-batters model) "batter = ?" batter (baseball-model-batter-strength model) "1" (list batter)))

(define (baseball-pitcher-matrix model pitcher)
  "A pitcher's probabilities, from the turns he pitched in the model's seasons."
  (baseball--player-matrix model (baseball-model-pitchers model) "pitcher = ?" pitcher (baseball-model-pitcher-strength model) "1" (list pitcher)))

(define (baseball-bullpen-matrix model &key (team '()))
  "The probabilities of relievers (who did not start the game) together: of a team's, if team (as Retrosheet abbreviates it, \"NYA\") is given, or of all."
  (if (null? team)
      (baseball--player-matrix model (baseball-model-pitchers model) "starter = 0" "relievers" (baseball-model-pitcher-strength model) "1" '())
      (baseball--player-matrix model (baseball-model-pitchers model) "starter = 0" team (baseball-model-pitcher-strength model) "pitching_team = ?" (list team))))

(define (baseball-matchup model batter pitcher)
  "The probabilities of a batter's (a matrix, baseball-batter-matrix makes) turn against a pitcher's (baseball-pitcher-matrix)."
  (combine-transitions batter pitcher (baseball-model-league model)))

(define (baseball-players model name)
  "A table of the players whose last name is name (or begins with it, if it ends with %): their id, name, how they bat and throw, and their first and last seasons."
  (sqlite-query (baseball-model-database model)
                "SELECT id, first, last, bats, throws, first_season, last_season FROM players WHERE last LIKE ? ORDER BY last, first" '() '() (list name)))

(define (baseball-starter-batters model starter)
  "How many batters a starting pitcher faced, per game he started, in the model's seasons (22 if he did not start one)."
  (let* ((found (sqlite-query (baseball-model-database model)
                              (format "SELECT COUNT(*) AS turns, COUNT(DISTINCT gid) AS starts FROM turns WHERE {}" (baseball--where model "pitcher = ? AND starter = 1"))
                              '() '() (list starter)))
         (starts (vector-ref (table-column found "starts") 0)))
    (if (= starts 0)
        22
        (/ (vector-ref (table-column found "turns") 0) starts))))

(define (baseball--team-pitching model team)
  "A list of a team's starter's matrix, its relievers', and how many batters the starter faces."
  (list (baseball-pitcher-matrix model (baseball-team-starter team))
        (baseball-bullpen-matrix model :team (baseball-team-bullpen team))
        (if (null? (baseball-team-starter-batters team))
            (baseball-starter-batters model (baseball-team-starter team))
            (baseball-team-starter-batters team))))

(define (baseball--matchups model team pitcher)
  "The matrices of a team's nine batters, in batting order, against a pitcher's."
  (map (lambda (batter) (baseball-matchup model (baseball-batter-matrix model batter) pitcher)) (baseball-team-lineup team)))

(define (baseball--team-batting model team opposing-pitching own-batters-faced)
  "A team in the form simulate-games takes: its nine batters' matchups with the opposing starter and with the opposing relievers (opposing-pitching is a list
baseball--team-pitching makes), and the batters its own starter faces (own-batters-faced)."
  (list (baseball--matchups model team (car opposing-pitching))
        (baseball--matchups model team (cadr opposing-pitching))
        own-batters-faced))

(define (simulate-baseball-games model home away &key (games 10000) (seed '()) (ghost-runner #t))
  "Play games between two baseball-teams (make-baseball-team), the home team and the visitors: a table with a row for each game, with the columns home_runs,
visiting_runs and innings. The same seed gives the same games."
  (let* ((home-pitching (baseball--team-pitching model home))
         (away-pitching (baseball--team-pitching model away)))
    (simulate-games (baseball--team-batting model home away-pitching (caddr home-pitching))
                    (baseball--team-batting model away home-pitching (caddr away-pitching))
                    :games games :seed seed :ghost-runner ghost-runner)))

(define (home-win-probability results)
  "How often the home team won, of the games in results (from simulate-baseball-games), not counting games that were stopped tied."
  (let ((home (table-column results "home_runs"))
        (visitors (table-column results "visiting_runs")))
    (/ (vector-sum (vector> home visitors))
       (+ (vector-sum (vector> home visitors)) (vector-sum (vector> visitors home))))))

; Trying the model on a season it was not fitted to
; -------------------------------------------------
; (define model (fit-baseball-model :last-season 2024))
; (define tried (baseball-backtest model 2025 :games-per-game 500))
; (baseball-scores tried)
;
; Each game of the season is played out games-per-game times, with the batting orders and starting pitchers that the game really had, and the model says
; how often the home team won. The relievers are the team's, as in the seasons of the model.

(define (baseball--add-to-list! table key value)
  (hash-table-set! table key (append (hash-table-ref table key '()) (list value))))

(define (baseball--games-condition season gid)
  "The SQL condition for the turns of the regular season games of a season, or of the one game gid (of any kind, if it is not '()), and its parameter."
  (if (null? gid) (list "gametype = 'regular' AND season = ?" season) (list "gid = ?" gid)))

(define (baseball--real-lineups model season &key (gid '()))
  "A hash table of the batting orders of the games of a season (or of the one game gid): the key \"gid|1\" for the home team's, \"gid|0\" for the visitors', and the
value a list of the first nine batters who batted for the team, in the order they first did (a batting order, give or take a pinch hitter early on)."
  (let* ((condition (baseball--games-condition season gid))
         (lineups (make-hash-table))
         (rows (sqlite-query (baseball-model-database model)
                             (format "WITH firsts AS (SELECT gid, home_batting, batter, MIN(rowid) AS first_turn FROM turns
                                                      WHERE {} GROUP BY gid, home_batting, batter),
                                           ranked AS (SELECT gid, home_batting, batter, first_turn,
                                                             ROW_NUMBER() OVER (PARTITION BY gid, home_batting ORDER BY first_turn) AS slot FROM firsts)
                                      SELECT gid, home_batting, batter FROM ranked WHERE slot <= 9 ORDER BY gid, home_batting, slot"
                                     (car condition))
                             '() '() (list (cadr condition)))))
    (loop for game across (table-column rows "gid")
          for home-batting across (table-column rows "home_batting")
          for batter across (table-column rows "batter")
          do (baseball--add-to-list! lineups (format "{}|{}" game home-batting) batter))
    lineups))

(define (baseball--real-starters model season &key (gid '()))
  "A hash table of the starting pitchers of the games of a season (or of the one game gid), and the team: the key \"gid|1\" for the home team's, and the value
(pitcher team)."
  (let* ((condition (baseball--games-condition season gid))
         (starters (make-hash-table))
         (rows (sqlite-query (baseball-model-database model)
                             (format "SELECT DISTINCT gid, 1 - home_batting AS home_pitching, pitcher, pitching_team FROM turns
                                      WHERE {} AND starter = 1"
                                     (car condition))
                             '() '() (list (cadr condition)))))
    (loop for game across (table-column rows "gid")
          for home-pitching across (table-column rows "home_pitching")
          for pitcher across (table-column rows "pitcher")
          for team across (table-column rows "pitching_team")
          do (hash-table-set! starters (format "{}|{}" game home-pitching) (list pitcher team)))
    starters))

(define (baseball--real-team lineups starters gid home)
  "The baseball-team that played in a game, or #f if the data does not have nine batters and a starter for it (home is 1 for the home team, 0 for the visitors)."
  (let ((lineup (hash-table-ref lineups (format "{}|{}" gid home) '()))
        (starter (hash-table-ref starters (format "{}|{}" gid home) #f)))
    (if (and starter (= (length lineup) 9))
        (make-baseball-team :lineup lineup :starter (car starter) :bullpen (cadr starter) :starter-batters '())
        #f)))

(define (baseball-team-in-game model gid home)
  "The baseball-team that played in a game of the database (gid is its Retrosheet id, \"NYA202509280\"): the home team's if home is 1, the visitors' if 0. Its
batting order and starting pitcher are the game's; its relievers are its team's. #f if the data does not have nine batters and a starter for it."
  (baseball--real-team (baseball--real-lineups model 0 :gid gid) (baseball--real-starters model 0 :gid gid) gid home))

(define (baseball-team-in-last-game model team season)
  "The baseball-team that a team (as Retrosheet abbreviates it, \"NYA\") fielded in its last regular season game of the season: a batting order and a starting
pitcher to try out. #f if it played no game."
  (let ((last (sqlite-query (baseball-model-database model)
                            "SELECT gid, home_team = ? AS at_home FROM games WHERE gametype = 'regular' AND season = ? AND (home_team = ? OR visiting_team = ?)
                             ORDER BY date DESC, gid DESC LIMIT 1"
                            '() '() (list team season team team))))
    (if (= (table-row-count last) 0)
        #f
        (baseball-team-in-game model (vector-ref (table-column last "gid") 0) (vector-ref (table-column last "at_home") 0)))))

(define (baseball-backtest model season &key (games-per-game 500) (max-games '()))
  "For each game of the season, what the model says were the chances of the home team winning, with the batting orders and starting pitchers the game had:
a table with the columns gid, date, home_win_probability, home_won (1 or 0), and expected_runs (both teams'). The model should not have been fitted to the
season. max-games, if given, stops after that many games."
  (let* ((lineups (baseball--real-lineups model season))
         (starters (baseball--real-starters model season))
         (games (sqlite-query (baseball-model-database model)
                              "SELECT gid, date, home_runs, visiting_runs FROM games WHERE gametype = 'regular' AND season = ? ORDER BY date, gid"
                              '() '() (list season)))
         (gids '()) (dates '()) (chances '()) (won '()) (runs '()) (count 0))
    (loop for gid across (table-column games "gid")
          for date across (table-column games "date")
          for home-runs across (table-column games "home_runs")
          for visiting-runs across (table-column games "visiting_runs")
          while (or (null? max-games) (< count max-games))
          do (let ((home (baseball--real-team lineups starters gid 1))
                   (away (baseball--real-team lineups starters gid 0)))
               (if (and home away (not (= home-runs visiting-runs)))
                   (let ((played (simulate-baseball-games model home away :games games-per-game)))
                     (set! count (+ count 1))
                     (set! gids (cons gid gids))
                     (set! dates (cons date dates))
                     (set! chances (cons (home-win-probability played) chances))
                     (set! won (cons (if (> home-runs visiting-runs) 1 0) won))
                     (set! runs (cons (+ (vector-mean (table-column played "home_runs")) (vector-mean (table-column played "visiting_runs"))) runs))))))
    (make-table "gid" (list->vector (reverse gids)) "date" (list->vector (reverse dates))
                "home_win_probability" (list->vector (reverse chances)) "home_won" (list->vector (reverse won))
                "expected_runs" (list->vector (reverse runs)))))

(define (baseball-scores tried)
  "How well the chances in a table that baseball-backtest made did: a table with the rows model and home-field (always saying the home team wins as often as
it did in the table), and the columns log_loss (lower is better; 0.693 is a coin flip) and brier."
  (let* ((chance (table-column tried "home_win_probability"))
         (won (table-column tried "home_won"))
         (home-field (vector-mean won))
         (score (lambda (chances)
                  (list (- (vector-mean (vectors-map (lambda (p w i) (if (= w 1) (log p) (log (- 1 p)))) (list chances won))))
                        (vector-mean (vectors-map (lambda (p w i) (* (- p w) (- p w))) (list chances won)))))))
    (let ((model-score (score chance))
          (field-score (score (vector-map (lambda (w) home-field) won))))
      (make-table "forecast" (vector "model" "home-field")
                  "log_loss" (vector (car model-score) (car field-score))
                  "brier" (vector (cadr model-score) (cadr field-score))))))
