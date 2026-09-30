; chess_example.lsp
;
; The chess program in chess.lsp at work: reading moves in algebraic
; notation, checking its rules against numbers every chess program must
; get, and looking ahead to find a checkmate, a fork, and a sacrifice.
;
; Run it from the examples directory (it takes about a minute):
;   python3 ../lisp_interpreter.py chess_example.lsp
; To play the program yourself, (load "chess.lsp"), then (play-chess).

(load "chess.lsp")

(define (show-legal-moves position)
  (display (format "{} can play: {}\n"
                   (side-name (position-side position))
                   (string-join (sort (map (lambda (move) (move->notation position move))
                                           (legal-moves position)))))))

; ---------------------------------------------------------------------------
; Moves in algebraic notation
; ---------------------------------------------------------------------------

(display "The Ruy Lopez: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7\n\n")
(define ruy-lopez
  (play-moves (initial-position) '("e4" "e5" "Nf3" "Nc6" "Bb5" "a6" "Ba4" "Nf6" "O-O" "Be7")))
(draw-board ruy-lopez)
(newline)
(show-legal-moves ruy-lopez)

; ---------------------------------------------------------------------------
; Checking the rules
; ---------------------------------------------------------------------------
; The number of ways to play n moves from a position is known for many
; positions; a program that gets them all right has the rules right. This
; one, from the chess programmers' wiki, has castling both ways for both
; sides, pins, en passant, and promotions not far off.

(display "\nWays to play 1, 2, and 3 moves from the opening (it should be 20, 400, 8902):\n")
(display (format "  {}\n" (map (lambda (n) (count-positions (initial-position) n)) '(1 2 3))))

(define kiwipete (fen->position "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -"))
(display "Ways to play 1 and 2 moves from this position (it should be 48, 2039):\n\n")
(draw-board kiwipete)
(display (format "  {}\n" (map (lambda (n) (count-positions kiwipete n)) '(1 2))))

; ---------------------------------------------------------------------------
; Looking ahead
; ---------------------------------------------------------------------------

(display "\n1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6 -- black has missed the threat to f7:\n\n")
(define scholars-mate (play-moves (initial-position) '("e4" "e5" "Bc4" "Nc6" "Qh5" "Nf6")))
(draw-board scholars-mate)
(computer-move scholars-mate 2)

(display "\nA knight fork: taking the pawn on c7 checks the king and attacks the rook,\n")
(display "which the knight takes next -- two moves ahead, and then a capture:\n\n")
(define fork (fen->position "r3kb1r/ppp2ppp/5n2/3N4/8/8/PPP2PPP/R3KB1R w KQkq -"))
(draw-board fork)
(computer-move fork 2)

(display "\nThe black rook guards the back rank -- but it can only take one of the\n")
(display "white rooks. A rook sacrifice mates in two, three moves ahead:\n\n")
(define back-rank (fen->position "2r3k1/5ppp/8/8/8/8/3R1PPP/3R2K1 w - -"))
(draw-board back-rank)
(computer-move back-rank 3)
