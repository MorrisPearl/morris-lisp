; backgammon_play.lsp
;
; Plays backgammon against the network that backgammon_train.lsp saved.
; The board is shown before each of your moves: your checkers are X, the
; computer's are O, and the points run 24 to 13 along the top and 12 to 1
; along the bottom, so your home board is at the bottom and you bear off past
; point 1. Type your moves as the usual notation writes them: 24/18 13/11,
; bar/20 for a checker entering from the bar, and 3/off for bearing off.
; Type ? to list the plays your roll allows, and quit to stop. Before each roll
; either player may double the cube: type double to double (the computer takes
; or drops by its network), or press Enter to roll; when the computer doubles,
; type take or drop. A game is worth the cube times 1, 2 (a gammon) or 3 (a
; backgammon).
;
; Run it from the examples directory, after backgammon_train.lsp has made the
; network, with the file as the argument if it isn't backgammon_net.txt:
;   python3 ../lisp_interpreter.py backgammon_play.lsp
;   python3 ../lisp_interpreter.py backgammon_play.lsp backgammon_net.txt
; In a Jupyter notebook, (play-backgammon :file "backgammon_net.txt") does the
; same, and (play-backgammon :human-first #f) lets the computer start.

(destructuring-bind (&optional (file "backgammon_net.txt")) (command-line-arguments)
  (play-backgammon :file file))
