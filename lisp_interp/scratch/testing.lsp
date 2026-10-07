
(define gdp_series (fred-series "GDP" api-key))
(define cpi_series (fred-series "CPIAUCSL" api-key))
(define unemployment_series (fred-series "UNRATE" api-key))
(define ten_year_treasury_series (fred-series "GS10" api-key))

(define date_list (vector->list (car cpi_series)))
(define d1 (car date_list))
(define d2 (car (cdr date_list)))


(define (make_master_dates d_list  n)
    (if
     ( <= n 0)
     d_list
     (make_master_dates (cons (prev_month (car d_list)) d_list) (- n 1))
     )
  )

(define master_dates
    (
     make_master_dates (list (date 2026 8 1))
		       361
		       )
  )

(define dates_matched (lineup_time_series master_dates (vector->list (car cpi_series)) (vector->list (cdr cpi_series)) () ))
