; map_example.lsp
;
; Maps: the Census Bureau's outlines of states, counties, census tracts,
; and ZIP code areas (census-shapes), drawn with an equal-area projection
; (plot-map) -- each place colored by a value, a symbol on each sized by a
; value, or both. See "Maps" in the reference manual.
;
; The outlines need no key; the data here comes from the Census and the
; BEA, so it needs your credentials file ("us_census_api_key" and
; "bea_api_key"), whose path init.lsp sets as creds. In a notebook, each
; map is drawn; at the console, each prints a summary (save-chart saves the
; last one). Run it from the examples directory:
;   python3 ../lisp_interpreter.py map_example.lsp

; --- 1. The outlines ------------------------------------------------------------------
; A table, a row per place: its codes (GEOID), name, land and water areas,
; and outline (the shape column).
(define states (census-shapes "state"))
(display-table (table-head (table-select states '("GEOID" "STUSPS" "NAME" "ALAND")) 5)
               '(("ALAND" ",")))
(plot-map states :title "The states, on an equal-area projection")

; --- 2. Coloring places by a value ------------------------------------------------------
; Per capita personal income for every county (BEA), matched to the counties
; by the BEA's fips codes. A log scale, since a few counties are far above
; the rest; the states' borders drawn on top.
(define income (bea-regional creds "CAINC1" 3 "COUNTY" :start-year 2024 :end-year 2024))
(plot-map (census-shapes "county") :data income :key "fips" :fill "2024" :log #t :colors "YlGnBu"
          :format "${:,.0f}" :fill-label "per capita income" :borders states
          :title "Per capita personal income, 2024")

; --- 3. Colors from one source, symbols from another --------------------------------
; Each state colored by its poverty rate (the Census's American Community
; Survey), with a circle sized by its GDP (BEA, in millions of dollars).
; census-profile gives each state's code in its "state" column; the BEA
; writes a state's code as "36000", which matches "36" all the same.
(define profile (census-profile creds "state:*"))
(define gdp (bea-regional creds "SAGDP1" 3 "STATE" :start-year 2024 :end-year 2024))
(plot-map states :data profile :key "state" :fill "poverty-rate" :fill-label "poverty rate, %"
          :colors "YlOrRd" :symbol-data gdp :symbol-key "fips" :symbols "2024"
          :symbol-label "GDP, millions of dollars" :symbol-color "navy" :format "{:,.0f}"
          :title "Poverty and GDP, by state")

; --- 4. Symbols on ZIP code areas ----------------------------------------------------------
; How many people live in each ZIP code area (ZCTA) in New York: a circle on
; each, its area in proportion to the number, over the state's counties.
(define people (census-get creds "acs/acs5" '("B01003_001E") "zip code tabulation area:*"))
(plot-map (census-shapes "county" :state "NY") :symbols-on (census-shapes "zcta")
          :data people :key "zip code tabulation area" :symbols "B01003_001E" :symbol-label "people"
          :symbol-size 18 :format "{:,.0f}" :title "People in each ZIP code area, New York")

; --- 5. Census tracts -----------------------------------------------------------------------
; Manhattan's census tracts -- neighborhoods of about 4,000 people -- by
; median household income. A tract's code is its state's, its county's,
; and its own, which census-get gives in three columns.
(define incomes (census-get creds "acs/acs5" '("B19013_001E") "tract:*" :within "state:36 county:061"))
(define ny-tracts (census-shapes "tract" :state "NY"))
(define manhattan (table-where ny-tracts "COUNTYFP" "061"))
(plot-map manhattan :data incomes :key '("state" "county" "tract") :fill "B19013_001E"
          :fill-label "median household income" :format "${:,.0f}"
          :title "Median household income, Manhattan's census tracts")
