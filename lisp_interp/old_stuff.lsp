(define gdp_series (fred-series "GDP" api-key))
(define cpi_series (fred-series "CPIAUCSL" api-key))
(define unemployment_series (fred-series "UNRATE" api-key))
(define ten_year_treasury_series (fred-series "GS10" api-key))

(define date_list (car cpi_series))
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

(define (lineup_time_series md dates values result)
    (cond
      ((null? md) (reverse result))
      ((null? dates) (lineup_time_series (cdr md) dates values (cons -1.0 result)))

      ((< (car md) (car dates))
       (lineup_time_series (cdr md) dates values (cons -1.0 result)))
      ((> (car md) (car dates))
       (lineup_time_series md (cdr dates) (cdr values) result))
      (#t
       (lineup_time_series (cdr md) (cdr dates) (cdr values) (cons (car values) result)))
      )
  )

(define dates_matched (lineup_time_series master_dates (car cpi_series) (car (cdr cpi_series)) () ))
