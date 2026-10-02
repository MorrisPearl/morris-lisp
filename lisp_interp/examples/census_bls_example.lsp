; census_bls_example.lsp
;
; Demographic and economic data from the US Census Bureau (population,
; income, poverty, education, housing ... for every state, county, and
; neighborhood) and from the Bureau of Labor Statistics (prices, jobs, and
; pay). See "Census data" and "BLS data" in the reference manual.
;
; It needs your credentials file, with "us_census_api_key" and
; "bureau_of_labor_statistics_api_key" entries; creds is set to its path in
; init.lsp. Run it from the examples directory:
;   python3 ../lisp_interpreter.py census_bls_example.lsp

; --- 1. A profile of every state ---------------------------------------------------
; census-profile gives the same set of numbers for each place, from the
; Census's American Community Survey (5-year estimates). Rates are percents.
(define states (census-profile creds "state:*"))
(display "The ten states with the highest median household income:\n")
(display-table (table-head (table-sort (table-select states '("name" "population" "median-household-income"
                                                              "poverty-rate" "bachelors-degree-or-higher"
                                                              "median-home-value"))
                                       "median-household-income" #t)
                           10)
               '(("population" ",.0f") ("median-household-income" ",.0f") ("median-home-value" ",.0f")))

; --- 2. Every county in the country -------------------------------------------------
; "county:*" within "state:*" is all 3,000-odd counties, in one request.
(define counties (census-profile creds "county:*" :within "state:*"))
(define (county-column name) (table-column counties name))
(display (format "\nAcross {} counties, the correlation of income with the share of college graduates: {:.2f}\n"
                 (table-row-count counties)
                 (vector-correlation (county-column "median-household-income")
                                     (county-column "bachelors-degree-or-higher"))))

; --- 3. Any of the Census's numbers ------------------------------------------------
; census-variables finds a variable; census-get gets any variables, for any
; places. Here, the median rent as a percent of income (B25071_001E), with
; the population (B01003_001E), for New York's counties (state 36). The
; places' codes come back as text, leading zeros and all.
(display "\nVariables about rent as a percent of income:\n")
(display-table (table-select (census-variables creds "acs/acs5" "median gross rent as a percentage")
                             '("name" "label" "concept")))
(define rent (census-get creds "acs/acs5" '("NAME" "B01003_001E" "B25071_001E") "county:*" :within "state:36"))
(display "\nNew York's largest counties:\n")
(display-table (table-head (table-sort (table-select rent '("NAME" "county" "B01003_001E" "B25071_001E"))
                                       "B01003_001E" #t)
                           6)
               '(("B01003_001E" ",.0f")))

; --- 4. The economy, from the BLS ------------------------------------------------
; bls-series takes series IDs, or short names for the ones most often wanted
; (bls-names lists them). Each row is a month. vector-pct-change gives each
; month's change from 12 months before, as a fraction (0.03 is 3%).
(define economy (bls-series creds '("cpi" "core-cpi" "average-hourly-earnings" "unemployment-rate")
                            :start-year 2024))
(define (yearly-change name) (vector-pct-change (table-column economy name) 12))
(define changes (make-table "month" (table-column economy "date")
                            "inflation" (yearly-change "cpi")
                            "core inflation" (yearly-change "core-cpi")
                            "wage growth" (yearly-change "average-hourly-earnings")
                            "real wage growth" (- (yearly-change "average-hourly-earnings") (yearly-change "cpi"))
                            "unemployment" (/ (table-column economy "unemployment-rate") 100)))
(display "\nPrices and pay, each compared with a year before:\n")
(display-table (table-tail changes 12)
               '(("inflation" ".1%") ("core inflation" ".1%") ("wage growth" ".1%")
                 ("real wage growth" ".1%") ("unemployment" ".1%")))

; --- 5. Census places, BLS numbers --------------------------------------------------
; bls-local-area takes a state's or county's FIPS code -- the codes the
; Census gives -- for its labor force and unemployment each month.
(define manhattan (bls-local-area creds (string-append "36" "061") :start-year 2025))
(display "\nNew York County (Manhattan), the last six months:\n")
(display-table (table-tail manhattan 6)
               '(("labor-force" ",.0f") ("employed" ",.0f") ("unemployed" ",.0f")))

; A list of codes gives a row per place per month, with a fips column: here
; New York City's five counties (its boroughs), in the latest month.
(define boroughs (bls-local-area creds '("36005" "36047" "36061" "36081" "36085") :start-year 2026))
(define last-month (vector-ref (table-column boroughs "date") (- (table-row-count boroughs) 1)))
(display "\nNew York City's boroughs, the latest month:\n")
(display-table (table-where boroughs "date" last-month)
               '(("labor-force" ",.0f") ("employed" ",.0f") ("unemployed" ",.0f")))
