; vendor_financing.lsp
; ====================
; How much of a company's sales its own money pays for: the stakes it buys in other companies (often its customers), the profits it
; books when those stakes rise in value, and the debts of others it guarantees, beside its revenue, quarter by quarter, from what it
; reports to the SEC (sec-values).
;
;   (vendor-financing creds "NVDA")              a table: a row per quarter
;   (vendor-financing creds "NVDA" :count 12)    ... for the last twelve quarters
;
; The SEC's data say how much a company holds in other companies' shares, not which of those companies are its customers: the filing's
; notes say that (sec-filings and sec-filing-text read them). doc/lisp_macro_models_manual.md, "A shock to the AI companies", uses it for
; Nvidia.

; The concepts read, from the US-GAAP list. Companies don't all use them: a column a company has no value for is missing.
(define vendor-financing-concepts
  '(("revenue"        "Revenues")                                                    ; sales, in the quarter
    ("pretax income"  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest")
    ("private stakes" "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount")   ; shares of companies not traded: at the quarter's end
    ("public stakes"  "EquitySecuritiesFvNi")                                        ; shares of traded companies, at their price
    ("gains on stakes" "GainLossOnInvestments")                                      ; what rises (or falls) in their value added to income
    ("guarantees"     "GuaranteeObligationsMaximumExposure")))                       ; the most it could have to pay for others' debts

(define (vendor-financing creds ticker &key (count 8))
  "A company's stakes in other companies, the gains on them, and the debts of others it guarantees, beside its revenue, for the last count
quarters (oldest first), in billions of dollars:
  revenue              sales in the quarter
  year's revenue       sales in the four quarters up to this one
  private stakes       shares of companies that aren't traded, at the end of the quarter (at cost, adjusted when they sell shares)
  public stakes        shares of traded companies, at their price at the end of the quarter
  new money in stakes  how much the stakes grew in the quarter, less the gains on them: roughly, what the company paid for new stakes
  per dollar of sales  new money in stakes over revenue
  gains on stakes      what the rise in the stakes' value added to the quarter's income before taxes
  gains share          gains on stakes over income before taxes
  guarantees           the most the company could have to pay if others it guarantees don't pay their debts (leases, loans)
A missing value is a number the company didn't report under these concepts (vendor-financing-concepts)."
  (let* ((values (sec-values creds ticker (map second vendor-financing-concepts) :period "quarterly" :count (+ count 3)))
         (column (lambda (label) (vector-div (table-column values (second (assoc label vendor-financing-concepts))) 1e9)))
         (revenue (column "revenue"))
         (stakes (vector-add (column "private stakes") (column "public stakes")))
         (gains (column "gains on stakes"))
         (quarters (table-row-count values))
         (year-revenue (vector-map (lambda (k) (if (< k 3) nan (vector-sum (vector-slice revenue (- k 3) (+ k 1)))))
                                   (vector-range 0 quarters)))
         (new-money (vector-map (lambda (k) (if (= k 0) nan (- (vector-ref stakes k) (vector-ref stakes (- k 1)) (vector-ref gains k))))
                                (vector-range 0 quarters)))
         (rounded (lambda (v) (vector-slice (vector-round v 2) 3 quarters))))
    (make-table "quarter end" (vector-slice (table-column values "period-end") 3 quarters)
                "revenue" (rounded revenue)
                "year's revenue" (rounded year-revenue)
                "private stakes" (rounded (column "private stakes"))
                "public stakes" (rounded (column "public stakes"))
                "new money in stakes" (rounded new-money)
                "per dollar of sales" (rounded (vector-div new-money revenue))
                "gains on stakes" (rounded gains)
                "gains share" (rounded (vector-div gains (column "pretax income")))
                "guarantees" (rounded (column "guarantees")))))
