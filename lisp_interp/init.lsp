; ---------------------------------------------------------------------
; init.lsp
;
; Loaded automatically, into a fresh global environment, every time the
; interpreter starts -- batch mode (python3 lisp_interpreter.py script.lsp),
; the console REPL, and the GUI all load this file first, before anything
; else runs. See load_init_file() / DEFAULT_INIT_FILE in lisp_interpreter.py.
;
; Put your own always-available definitions and macros here -- they'll
; be in scope for every script and REPL session without having to
; (load ...) them by hand each time. This file is optional: if it's
; empty (or you delete it), startup behaves exactly as if it didn't
; exist.
;
; To use a different init file instead of this one, either edit this
; file in place or set the LISP_INIT_FILE environment variable to another
; path.
; ---------------------------------------------------------------------

(define api-key "/Users/morris/credentials.json")

(defmacro while (test body)
  `(let ()
     (define (%loop)
       (if ,test
           (begin ,body (%loop))
           '()))
     (%loop)))

(define gdp_series (fred-series "GDP" api-key))
(define cpi_series (fred-series "CPIAUCSL" api-key))
(define unemployment_series (fred-series "UNRATE" api-key))
(define ten_year_treasury_series (fred-series "GS10" api-key))

(define date_list (car cpi_series))
(define d1 (car date_list))
(define d2 (car (cdr date_list)))

; compare two dates, just year and month.
; if they are different days in the same
; month, they count as equal.

(define (compare_month d1 d2)
    (cond 
      ((< (date-year d1) (date-year d2)) -1)
      ((> (date-year d1) (date-year d2)) 1)
      ((< (date-month d1) (date-month d2)) -1)
      ((> (date-month d1) (date-month d2)) 1)
      (#t 0)
      )
  )

(define (prev_month d)
    (cond
      ((<= (date-month d) 1)
       (date (- (date-year d) 1) 12 (date-day d)))
      (#t
       (date (date-year d) (- (date-month d) 1) (date-day d))
       )
      )
  )

(define (make_master_dates d_list  n)
    (cond
      (( <= n 0) d_list)
      (#t
       (make_master_dates (cons (prev_month (car d_list)) d_list) (- n 1))
       )
      )
  )

(define master_dates
    (
     make_master_dates (list (date 2026 8 1))
		       361
		       )
  )

(define (lineup_time_series md dates values result)
    (cond
      ((< (length md) 1) (reverse result))
      ((< (length dates) 1) (lineup_time_series (cdr md) dates values (cons -1.0 results))))
      ((< (car md) (car dates))
       (lineup_time_series (cdr md) dates values (cons -1.0 result)))
      ((> (car md) (car dates))
       (lineup_time_series md (cdr dates) (cdr values) result))
      (#t
       (lineup_time_series (cdr md) (cdr dates) (cdr values) (cons (car values) result)))
      )
  )

(define dates_matched (lineup_time_series master_dates (car cpi_series) (car (cdr cpi_series)) () ))


	   
  
