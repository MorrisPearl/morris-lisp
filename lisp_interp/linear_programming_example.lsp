; linear_programming_example.lsp
;
; Linear programming with lp-read-file and lp-solve (see "Linear
; programming" in lisp_interpreter_reference.md).
;
; The problem, in linear_programming_example.txt: invest $100 million in
; four mortgage pools, earning as much yield as possible, within limits on
; concentration, average duration, and credit risk. The amounts are in
; dollars; the solver handles numbers this size without scaling them down.
;
; Run it from this directory:
;   python3 lisp_interpreter.py linear_programming_example.lsp

(define pool-names (list "GNMA 30-year" "FNMA 30-year" "Non-agency prime" "CMO Z-tranche"))
(define pool-yields (list 0.054 0.058 0.066 0.072))
(define total-invested 100000000)

; --- 1. Read the problem from the file ---------------------------------

(define problem (lp-read-file "linear_programming_example.txt"))

(display "The problem, as lp-read-file returns it:") (newline)
(dolist (part problem)
  (display (format "  {:<12} {}\n" (car part) (cdr part))))
(newline)

; --- 2. Solve it, and show how the money is invested --------------------

(define result (lp-solve problem))
(define amounts (cdr (assoc "solution" result)))

; The objective is the negative of the yearly income, so the most income
; is the negative of the objective's minimum.
(define income (- (cdr (assoc "optimal-value" result))))

(define (show-allocation amounts)
  "Print each pool's name, the amount invested in it, and its yield."
  (display (format "  {:<18}{:>16}{:>8}\n" "Pool" "Amount" "Yield"))
  (do ((names pool-names (cdr names))
       (yields pool-yields (cdr yields))
       (amounts amounts (cdr amounts)))
      ((null? names))
    (display (format "  {:<18}{:>16,.0f}{:>8.1%}\n" (car names) (car amounts) (car yields)))))

(display "The best allocation:") (newline)
(show-allocation amounts)
(display (format "  {:<18}{:>16,.0f}{:>8.2%}\n" "Total" total-invested (/ income total-invested)))
(display (format "Yearly income: ${:,.0f}\n\n" income))

; --- 3. Change the problem in Lisp, and solve it again ------------------
; A problem is ordinary Lisp data, so it's easy to change. Here the limit
; on average duration -- the sixth constraint, so element 5 of "rhs" --
; is changed, to see how much income a longer average duration buys.

(define (replace-nth lst n value)
  "A copy of lst with element n (counting from 0) replaced by value."
  (if (= n 0)
      (cons value (cdr lst))
      (cons (car lst) (replace-nth (cdr lst) (- n 1) value))))

(define (problem-with-duration-limit years)
  "The problem, with the average duration limited to years (5.5 in the file)."
  (define rhs (cdr (assoc "rhs" problem)))
  (list (assoc "objective" problem)
        (assoc "constraints" problem)
        (assoc "relations" problem)
        (cons "rhs" (replace-nth rhs 5 (* years total-invested)))))

(display "The most income for each limit on average duration:") (newline)
(display (format "  {:>6}{:>14}{:>8}\n" "Limit" "Income" "Yield"))
(dolist (years (list 5.0 5.25 5.5 5.75 6.0 6.5))
  (let ((income (- (cdr (assoc "optimal-value" (lp-solve (problem-with-duration-limit years)))))))
    (display (format "  {:>6.2f}{:>14,.0f}{:>8.2%}\n" years income (/ income total-invested)))))
(display "Past 6 years the duration limit stops mattering: the $40 million limit on") (newline)
(display "the Z-tranche and the $50 million limit on credit risk hold the income down.") (newline)
(newline)

; --- 4. A problem with no solution ---------------------------------------
; No mix of these pools has an average duration under 4.5 years (the
; shortest pool's), so a limit of 4 years can't be met. lp-solve reports
; that as an error, which catch-error can catch.

(display "With the average duration limited to 4 years: ")
(display (catch-error (lp-solve (problem-with-duration-limit 4.0))
                      (e) e))
(newline)
