; symbolic_algebra_example.lsp
;
; Symbolic algebra with polynomials in a canonical form, after chapter 15 of
; Peter Norvig's "Paradigms of Artificial Intelligence Programming" (1992),
; which follows the canonical simplifier of MACSYMA. Norvig's Common Lisp
; code is at https://github.com/norvig/paip-lisp (MIT license); this is
; written afresh for this interpreter.
;
; The idea: turn every expression into one standard (canonical) form, in
; which two expressions that are equal look exactly alike. Then simplifying
; is just converting to the canonical form and back, and (x - 1) * (x + 1)
; and x ^ 2 - 1 come out the same.
;
;   (canon '((x + 1) * (x - 1)))                ; => "x^2 - 1"
;   (canon '(d (3 * x ^ 2 + 2 * x + 1) / d x))  ; => "6*x + 2"
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py symbolic_algebra_example.lsp

; ---------------------------------------------------------------------------
; 1. The canonical form
; ---------------------------------------------------------------------------
; A polynomial is either a number, or a list of its main variable and its
; coefficients, the constant term first:
;
;   5                  5
;   (x 0 1)            x
;   (x 30 20 10 5)     5*x^3 + 10*x^2 + 20*x + 30
;
; (The book uses vectors; this interpreter's vectors hold only numbers, so
; these are lists.) A coefficient can itself be a polynomial, in a variable
; that comes LATER in the alphabet: x + y is (x (y 0 1) 1) -- a polynomial
; in x whose constant term is y. Never (y (x 0 1) 1), which is why each
; expression has just one form.
;
; The form is kept tidy: no zero coefficients at the top (so the degree is
; right), and a polynomial of degree 0 is just its constant term.

(define (main-var p) (car p))
(define (coefs p) (cdr p))

(define (var< a b)
  "Whether variable a comes before variable b: a polynomial in a can have
coefficients in b, but not the other way around."
  (string<? (symbol->string a) (symbol->string b)))

(define (drop-leading-zeros items)
  (if (and (pair? items) (equal? (car items) 0))
      (drop-leading-zeros (cdr items))
      items))

(define (make-poly var coefficients)
  "The polynomial in var with these coefficients, in canonical form."
  (let ((trimmed (reverse (drop-leading-zeros (reverse coefficients)))))
    (cond ((null? trimmed) 0)
          ((null? (cdr trimmed)) (car trimmed))
          (else (cons var trimmed)))))

; ---------------------------------------------------------------------------
; 2. Adding, multiplying, and raising to a power
; ---------------------------------------------------------------------------
; Each of these looks at which polynomial has the earlier main variable. If
; they share one, the coefficients are combined; otherwise the one with the
; later variable is just a constant as far as the other is concerned.

(define (poly+poly p q)
  (cond ((number? p) (k+poly p q))
        ((number? q) (k+poly q p))
        ((eq? (main-var p) (main-var q)) (poly+same p q))
        ((var< (main-var p) (main-var q)) (k+poly q p))
        (else (k+poly p q))))

(define (k+poly k p)
  "Add k, which doesn't contain p's main variable, to p: it goes into p's
constant term."
  (cond ((equal? k 0) p)
        ((number? p) (+ k p))
        (else (make-poly (main-var p) (cons (poly+poly k (car (coefs p))) (cdr (coefs p)))))))

(define (add-coefficients a b)
  "Two lists of coefficients, added term by term."
  (cond ((null? a) b)
        ((null? b) a)
        (else (cons (poly+poly (car a) (car b)) (add-coefficients (cdr a) (cdr b))))))

(define (poly+same p q)
  (make-poly (main-var p) (add-coefficients (coefs p) (coefs q))))

(define (poly*poly p q)
  (cond ((number? p) (k*poly p q))
        ((number? q) (k*poly q p))
        ((eq? (main-var p) (main-var q)) (poly*same p q))
        ((var< (main-var p) (main-var q)) (k*poly q p))
        (else (k*poly p q))))

(define (k*poly k p)
  "Multiply p by k, which doesn't contain p's main variable: every
coefficient of p, times k."
  (cond ((equal? k 0) 0)
        ((equal? k 1) p)
        ((number? p) (* k p))
        (else (make-poly (main-var p) (map (lambda (c) (poly*poly k c)) (coefs p))))))

(define (poly*same p q)
  "Multiply two polynomials in the same variable: each term of p times all
of q, moved up to that term's power, all added up."
  (define (add-terms p-coefs zeros total)
    (if (null? p-coefs)
        total
        (add-terms (cdr p-coefs) (cons 0 zeros)
                   (add-coefficients total
                                     (append zeros (map (lambda (c) (poly*poly (car p-coefs) c))
                                                        (coefs q)))))))
  (make-poly (main-var p) (add-terms (coefs p) '() '())))

(define (poly^n p n)
  "p to the nth power, n a whole number: p times itself, n times. (The
book shows that squaring, for an even n, is slower here, and that the
binomial theorem is faster still.)"
  (if (= n 0)
      1
      (poly*poly p (poly^n p (- n 1)))))

; ---------------------------------------------------------------------------
; 3. Derivatives
; ---------------------------------------------------------------------------
; With only + and * to deal with, the derivative is short: for the main
; variable, d(a + b*x + c*x^2)/dx is b + 2*c*x; for a variable that comes
; later, each coefficient is differentiated; and a variable that comes
; earlier than p's main variable isn't in p at all.

(define (deriv-poly p x)
  "The derivative of p with respect to the variable x."
  (cond ((number? p) 0)
        ((var< x (main-var p)) 0)
        ((eq? (main-var p) x)
         (let ((higher (cdr (coefs p))))
           (make-poly x (map poly*poly (loop for i from 1 to (length higher) collect i) higher))))
        (else (make-poly (main-var p) (map (lambda (c) (deriv-poly c x)) (coefs p))))))

; ---------------------------------------------------------------------------
; 4. Reading expressions: infix to prefix to canonical form
; ---------------------------------------------------------------------------
; Expressions are written in infix, as lists: (3 * x ^ 2 + 2 * x + 1).
; Leave spaces around the operators -- x-1 would be one symbol -- and use a
; nested list for parentheses. A derivative is written (d expression / d x).
; infix->prefix turns that into prefix, (+ (+ (* 3 (^ x 2)) (* 2 x)) 1),
; with * before +, ^ before *, and ^ grouping to the right.

(define (infix->prefix expression)
  "An infix expression (a list, or a single number or symbol), as prefix."
  (let ((tokens (if (pair? expression) expression (list expression))))
    (define (peek) (if (null? tokens) '() (car tokens)))
    (define (next!) (pop tokens))
    (define (sum)                       ; product + product - product ...
      (define (more left)
        (cond ((eq? (peek) '+) (next!) (more (list '+ left (product))))
              ((eq? (peek) '-) (next!) (more (list '- left (product))))
              (else left)))
      (more (product)))
    (define (product)                   ; factor * factor ...
      (define (more left)
        (if (eq? (peek) '*)
            (begin (next!) (more (list '* left (factor))))
            left))
      (more (factor)))
    (define (factor)                    ; - factor, or power
      (if (eq? (peek) '-)
          (begin (next!) (list '- (factor)))
          (power)))
    (define (power)                     ; primary ^ factor
      (let ((base (primary)))
        (if (eq? (peek) '^)
            (begin (next!) (list '^ base (factor)))
            base)))
    (define (primary)                   ; a number, a variable, (...), or d(...)/dx
      (when (null? tokens)
        (error "infix->prefix: the expression ends too soon:" expression))
      (let ((token (next!)))
        (cond ((and (eq? token 'd) (pair? (peek)))
               (let ((inner (next!)))
                 (unless (and (eq? (next!) '/) (eq? (next!) 'd))
                   (error "infix->prefix: write a derivative as (d expression / d x)"))
                 (list 'd (infix->prefix inner) (next!))))
              ((pair? token) (infix->prefix token))
              (else token))))
    (let ((result (sum)))
      (unless (null? tokens)
        (error "infix->prefix: can't make sense of" tokens "in" expression))
      result)))

(define (prefix->canon e)
  "A prefix expression in canonical form."
  (cond ((number? e) e)
        ((symbol? e) (make-poly e '(0 1)))
        (else
         (let ((op (car e))
               (args (map prefix->canon (cdr e))))
           (case op
             ((+) (poly+poly (first args) (second args)))
             ((-) (if (null? (cdr args))
                      (poly*poly -1 (first args))
                      (poly+poly (first args) (poly*poly -1 (second args)))))
             ((*) (poly*poly (first args) (second args)))
             ((^) (poly^n (first args) (third e)))
             ((d) (deriv-poly (first args) (third e)))
             (else (error "prefix->canon: not a polynomial:" e)))))))

; ---------------------------------------------------------------------------
; 5. Writing it out
; ---------------------------------------------------------------------------
; The highest power first; a coefficient that is itself a polynomial goes
; in front of its power of the main variable, in parentheses if it has more
; than one term: (5*y + 1)*x^2.

(define (power-text x i)
  (cond ((= i 0) "")
        ((= i 1) (symbol->string x))
        (else (format "{}^{}" x i))))

(define (term-text c x i)
  "One term of a polynomial in x: c times x to the i."
  (let ((c-text (poly->string c))
        (x-text (power-text x i)))
    (cond ((= i 0) c-text)
          ((equal? c 1) x-text)
          ((equal? c -1) (string-append "-" x-text))
          ((regex-search " [+-] " c-text) (format "({})*{}" c-text x-text))
          (else (format "{}*{}" c-text x-text)))))

(define (poly->string p)
  "p written out in the usual way, such as \"5*x^3 - 2*x + 1\"."
  (if (number? p)
      (to-string p)
      (let ((terms (loop for c in (coefs p)
                         for i from 0
                         unless (equal? c 0)
                         collect (term-text c (main-var p) i))))
        (regex-replace "\+ -" (string-join (reverse terms) " + ") "- "))))

(define (canon expression)
  "Simplify an infix expression, by way of its canonical form."
  (poly->string (prefix->canon (infix->prefix expression))))

; ---------------------------------------------------------------------------
; 6. Examples
; ---------------------------------------------------------------------------

(dolist (expression '((3 + x + 4 - x)
                      (x + y + y + x)
                      (3 * x + 4 * x)
                      (3 * x + y + z + x + 4 * x)
                      ((x + 1) * (x - 1))
                      ((x + 1) ^ 10)
                      ((x + 1) ^ 10 + (x - 1) ^ 10)
                      ((x + 1) ^ 10 - (x - 1) ^ 10)
                      (3 * x ^ 3 + 4 * x * y * (x - 1) + x ^ 2 * (x + y))
                      (3 * x ^ 3 + 4 * x * w * (x - 1) + x ^ 2 * (x + w))
                      (d (3 * x ^ 2 + 2 * x + 1) / d x)
                      (d (z + 3 * x + 3 * z * x ^ 2 + z ^ 2 * x ^ 3) / d z)))
  (display (format "{}\n    = {}\n" expression (canon expression))))

; The book's benchmark raises (1 + x + y + z) to the 15th power. That takes a
; while in this interpreter, so here it's the 6th -- 84 terms:
(define big (poly^n (prefix->canon (infix->prefix '(1 + x + y + z))) 6))
(display (format "\n(1 + x + y + z) ^ 6 has {} terms.\n"
                 (length (regex-split " [+-] " (poly->string big)))))
