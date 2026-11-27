; deal_tree_example.lsp
;
; Builds a structured deal by clicking on a drawing of its tree, in a window of its own (see deal_tree.lsp, and "Building a deal on
; its tree" in lisp_cmo_manual.md). The deal begins as its collateral alone, a pool of 100 million: click it, choose a kind of split,
; fill in the pop-up, calculate the sizes, and add the tranches. Close the window when the deal is built, and its tranches are shown.
; Needs PyQt6. Run it from the examples directory:
;   python3 ../lisp_interpreter.py deal_tree_example.lsp

(require "deal_tree.lsp")

(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 12 25) :closing-date (date 2026 11 20)
                       :collateral '((100000000 6.5 6.0 360))))     ; a piece: balance, wac and pass-through coupon in percent, wam

(deal-tree deal)                         ; (returns when the window is closed)

(display-table (deal-outline deal))
