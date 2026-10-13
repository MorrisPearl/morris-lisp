; chess_book.lsp
;
; The opening book for chess.lsp (section 7): 16 games, each won by white or by black, and their
; first moves, through the winner's move number 8, as the squares each move goes from and to. The
; winner's moves are the book's; the other side's are there to get to the positions they were played
; in. The games are from FIDE Candidates 2026: Open; Norway Chess 2026 | Open; Tata Steel Chess
; 2026 | Masters, as broadcast at lichess.org/broadcast. Above each game are its opening, the
; players, the event, where to find it, and its moves in standard notation, as far as the book goes.
;
; Made by tools/make_chess_book.py, which says how the games were chosen.

(define book-games
  '(
; Queen's Gambit Declined: Three Knights Variation (D37) -- Sindarov v Esipenko, FIDE Candidates
; 2026: Open. White won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-1/uLCZwqAK/0DOOxhwM
; 1.d4 d5 2.c4 e6 3.Nf3 Nf6 4.Nc3 Be7 5.cxd5 exd5 6.Bf4 O-O 7.e3 c5 8.Bd3
    (white "d2d4 d7d5 c2c4 e7e6 g1f3 g8f6 b1c3 f8e7 c4d5 e6d5 c1f4 e8g8 e2e3 c7c5 f1d3")

; Queen's Gambit Declined: Harrwitz Attack, Main Line (D37) -- Praggnanandhaa R v Sindarov, FIDE
; Candidates 2026: Open. Black won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-3/SDizieNR/NUotXF78
; 1.d4 d5 2.c4 e6 3.Nc3 Be7 4.Nf3 Nf6 5.Bf4 O-O 6.e3 c5 7.dxc5 Bxc5 8.a3 Nc6
    (black "d2d4 d7d5 c2c4 e7e6 b1c3 f8e7 g1f3 g8f6 c1f4 e8g8 e2e3 c7c5 d4c5 e7c5 a2a3 b8c6")

; English Opening: Agincourt Defense (A13) -- Caruana v Nakamura, FIDE Candidates 2026: Open. White
; won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-1/uLCZwqAK/iGcbKclc
; 1.Nf3 d5 2.c4 e6 3.g3 d4 4.Bg2 Nc6 5.O-O Bc5 6.e3 Nge7 7.Nxd4 Nxd4 8.b4
    (white "g1f3 d7d5 c2c4 e7e6 g2g3 d5d4 f1g2 b8c6 e1g1 f8c5 e2e3 g8e7 f3d4 c6d4 b2b4")

; English Opening: Symmetrical Variation, Rubinstein Variation (A34) -- Aravindh v Niemann, Tata
; Steel Chess 2026 | Masters. Black won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-4/TU7qC17C/Ay87teqm
; 1.Nf3 Nf6 2.g3 c5 3.Bg2 Nc6 4.c4 d5 5.cxd5 Nxd5 6.Nc3 Nc7 7.O-O e5 8.a3 Rb8
    (black "g1f3 g8f6 g2g3 c7c5 f1g2 b8c6 c2c4 d7d5 c4d5 f6d5 b1c3 d5c7 e1g1 e7e5 a2a3 a8b8")

; Petrov's Defense: Paulsen Attack (C42) -- Caruana v Bluebaum, FIDE Candidates 2026: Open. White
; won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-5/liBI9Brw/wuNBfSXX
; 1.e4 e5 2.Nf3 Nf6 3.Nxe5 d6 4.Nc4 Nxe4 5.Nc3 Nxc3 6.dxc3 d5 7.Ne3 c6 8.Bd2
    (white "e2e4 e7e5 g1f3 g8f6 f3e5 d7d6 e5c4 f6e4 b1c3 e4c3 d2c3 d6d5 c4e3 c7c6 c1d2")

; Petrov's Defense: Modern Attack (C43) -- Esipenko v Wei, FIDE Candidates 2026: Open. Black won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-7/aVbIuZ7Q/GyvRkvrq
; 1.e4 e5 2.Nf3 Nf6 3.d4 Nxe4 4.Qe2 d5 5.Nxe5 Be7 6.f3 Nd6 7.Nc3 Nf5 8.Qf2 O-O
    (black "e2e4 e7e5 g1f3 g8f6 d2d4 f6e4 d1e2 d7d5 f3e5 f8e7 f2f3 e4d6 b1c3 d6f5 e2f2 e8g8")

; Sicilian Defense: Closed (B23) -- Praggnanandhaa R v Giri, FIDE Candidates 2026: Open. White won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-1/uLCZwqAK/qIPzQJgf
; 1.e4 c5 2.Nc3 d6 3.f4 g6 4.Nf3 Bg7 5.Bb5+ Bd7 6.a4 Nc6 7.O-O a6 8.Bc4
    (white "e2e4 c7c5 b1c3 d7d6 f2f4 g7g6 g1f3 f8g7 f1b5 c8d7 a2a4 b8c6 e1g1 a7a6 b5c4")

; Sicilian Defense: Najdorf Variation (B95) -- Esipenko v Giri, FIDE Candidates 2026: Open. Black
; won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-4/97di6JjX/xbSQ7kmG
; 1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4 Nf6 5.Nc3 a6 6.Bg5 e6 7.Bd3 Be7 8.Qe2 Nxe4
    (black "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 c1g5 e7e6 f1d3 f8e7 d1e2 f6e4")

; Italian Game: Giuoco Pianissimo, Normal (C50) -- Praggnanandhaa R v Firouzja, Norway Chess
; 2026 | Open. White won.
; https://lichess.org/broadcast/norway-chess-2026-open/round-7/5LeUiRvw/Vg6LNUgV
; 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.d3 Bc5 5.a3 a6 6.Be3 d6 7.Nbd2 O-O 8.Qe2
    (white "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3 f8c5 a2a3 a7a6 c1e3 d7d6 b1d2 e8g8 d1e2")

; Italian Game: Classical Variation, Giuoco Pianissimo (C54) -- Caruana v Giri, FIDE Candidates
; 2026: Open. Black won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-9/hTVc2Qgj/oK0Qfzp0
; 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.O-O Nf6 5.d3 O-O 6.Nbd2 d6 7.c3 a5 8.h3 Be6
    (black "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 e1g1 g8f6 d2d3 e8g8 b1d2 d7d6 c2c3 a7a5 h2h3 c8e6")

; Ruy Lopez: Closed, Delayed Exchange (C85) -- Abdusattorov v Gukesh D, Tata Steel Chess
; 2026 | Masters. White won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-6/9nR8UQz9/C1Xw30Qx
; 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7 6.Bxc6 dxc6 7.d3 Nd7 8.Nc3
    (white "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 a4c6 d7c6 d2d3 f6d7 b1c3")

; Ruy Lopez: Morphy Defense, Anderssen Variation (C77) -- Nguyen v Erdogmus, Tata Steel Chess
; 2026 | Masters. Black won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-9/4qFZzDfZ/FyPPToeR
; 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.d3 d6 6.c3 g6 7.O-O Bg7 8.Re1 O-O
    (black "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 d2d3 d7d6 c2c3 g7g6 e1g1 f8g7 f1e1 e8g8")

; Bishop's Opening: Paulsen Defense (C24) -- Sindarov v Erdogmus, Tata Steel Chess 2026 | Masters.
; White won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-5/pdNmUOnu/qgTrZGOi
; 1.e4 e5 2.Bc4 Nf6 3.d3 c6 4.Nf3 d5 5.Bb3 Bb4+ 6.Bd2 Bxd2+ 7.Nbxd2 Nbd7 8.O-O
    (white "e2e4 e7e5 f1c4 g8f6 d2d3 c7c6 g1f3 d7d5 c4b3 f8b4 c1d2 b4d2 b1d2 b8d7 e1g1")

; Bishop's Opening: Vienna Hybrid (C24) -- Wei v Sindarov, FIDE Candidates 2026: Open. Black won.
; https://lichess.org/broadcast/fide-candidates-2026-open/round-6/WmbQrSNz/lkyNaDkn
; 1.e4 e5 2.Nc3 Nc6 3.Bc4 Nf6 4.d3 Na5 5.a3 Nxc4 6.dxc4 Bc5 7.Nf3 d6 8.Qd3 Be6
    (black "e2e4 e7e5 b1c3 b8c6 f1c4 g8f6 d2d3 c6a5 a2a3 a5c4 d3c4 f8c5 g1f3 d7d6 d1d3 c8e6")

; Nimzo-Indian Defense: Classical Variation (E32) -- Fedoseev v Keymer, Tata Steel Chess
; 2026 | Masters. White won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-2/d9xZZYuT/ROZWDl43
; 1.d4 Nf6 2.c4 e6 3.Nc3 Bb4 4.Qc2 O-O 5.Nf3 c5 6.dxc5 Na6 7.g3 Nxc5 8.Bg2
    (white "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 d1c2 e8g8 g1f3 c7c5 d4c5 b8a6 g2g3 a6c5 f1g2")

; Nimzo-Indian Defense: Classical Variation, Noa Variation (E34) -- Fedoseev v Gukesh D, Tata Steel
; Chess 2026 | Masters. Black won.
; https://lichess.org/broadcast/tata-steel-chess-2026-masters/round-8/W4XtM3HF/gkHXfj30
; 1.d4 Nf6 2.c4 e6 3.Nc3 Bb4 4.Qc2 d5 5.Nf3 O-O 6.e3 b6 7.Be2 Bb7 8.cxd5 exd5
    (black "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4 d1c2 d7d5 g1f3 e8g8 e2e3 b7b6 f1e2 c8b7 c4d5 e6d5")
    ))
