# Simple Lisp — Reference

A small Lisp with vectors, dates, linear/logistic regression, XY charting, and
FRED economic-data access, plus an optional PyQt6 GUI.

## Running it

- **No arguments** — `python3 lisp_interpreter.py` opens the PyQt6 GUI (an
  input box, an output log, a table of currently-defined vectors, and a
  chart tab). If PyQt6 or matplotlib isn't installed, it falls back to a
  plain console REPL instead.
- **A filename argument** — `python3 lisp_interpreter.py script.lsp` runs
  that file in batch mode (no GUI). `save-chart` still works in this mode
  as long as matplotlib is installed (PyQt6 is not required for it).

## Syntax

| Type | Example | Notes |
|---|---|---|
| Integer | `42`, `-7` | Python `int` |
| Float | `3.14`, `-0.5` | Python `float` |
| String | `"hello"` | Double-quoted; `\n`, `\t`, `\"`, `\\` escapes |
| Boolean | `#t`, `#f` | Everything except `#f` counts as true |
| Symbol | `foo`, `list->vector` | Identifiers |
| Pair / list | `(1 2 3)`, `'(a b c)` | Built from cons cells; `()` is the empty list |
| Vector | `#(1 2 3)`, `(vector 1 2 3)` | Fixed-size, holds numbers and/or dates |
| Date | `(date 2024 3 15)` | Prints as `2024-03-15` |
| Model | *(returned by regression)* | Prints as `#<linear-model ...>` etc. |

Comments run from `;` to end of line.

### Special forms

`quote`, `if`, `define`, `set!`, `lambda`, `begin`, `let`, `let*`, `cond`,
`and`, `or` — standard Scheme-like semantics. `(define (f x) ...)` defines a
function; `(define x 5)` defines a value. The evaluator uses an explicit
stack (not Python's call stack), so even deep non-tail recursion won't hit
a Python recursion-limit error, and tail calls run in constant stack space.

---

## Built-in functions

### Arithmetic

| Function | Description |
|---|---|
| `(+ a b ...)` | Sum (0+ args) |
| `(- a b ...)` | Subtract; `(- a)` negates |
| `(* a b ...)` | Product |
| `(/ a b ...)` | Divide; `(/ a)` is `1/a` |
| `(mod a b)`, `(remainder a b)` | `a % b` |
| `(quotient a b)` | Integer division |
| `(abs x)` | Absolute value |
| `(min a b ...)`, `(max a b ...)` | Minimum / maximum |
| `(sqrt x)` | Square root |
| `(expt a b)` | `a` to the power `b` |
| `(floor x)`, `(ceiling x)`, `(round x)`, `(truncate x)` | Rounding |
| `(sigmoid z)` | `1 / (1 + e^-z)` |

### Comparison / equality / booleans

| Function | Description |
|---|---|
| `(= a b ...)`, `(< ...)`, `(> ...)`, `(<= ...)`, `(>= ...)` | Chained numeric comparisons |
| `(eq? a b)`, `(equal? a b)` | Equality (both are value-equality here) |
| `(not x)` | Boolean negation |
| `(boolean? x)`, `(number? x)`, `(integer? x)`, `(string? x)`, `(symbol? x)`, `(procedure? x)`, `(pair? x)`, `(list? x)`, `(null? x)`, `(vector? x)`, `(date? x)`, `(model? x)` | Type predicates |

### Pairs and lists

| Function | Description |
|---|---|
| `(cons a b)` | Build a pair |
| `(car p)`, `(cdr p)` | First / rest |
| `(list a b ...)` | Build a list |
| `(append l1 l2 ...)` | Concatenate lists |
| `(reverse l)` | Reverse a list |
| `(length l)` | List length |
| `(map f l)` | Apply `f` to each element |
| `(filter f l)` | Keep elements where `(f x)` is true |
| `(reduce f l [init])` | Fold left over the list |
| `(apply f l)` | Call `f` with the elements of `l` as arguments |
| `(list-ref l n)` | The `n`-th element (0-based) |

### Strings

| Function | Description |
|---|---|
| `(string-append s1 s2 ...)` | Concatenate |
| `(string-length s)` | Length |
| `(substring s start [end])` | Substring |
| `(string=? a b)`, `(string<? a b)`, `(string>? a b)` | Compare |
| `(string->number s)`, `(number->string n)` | Convert |
| `(string->list s)`, `(list->string l)` | Convert to/from a list of characters |
| `(string-upcase s)`, `(string-downcase s)` | Case conversion |
| `(string->symbol s)`, `(symbol->string sym)` | Convert |
| `(string c1 c2 ...)` | Build a string from characters |

### Vectors

Vectors hold numbers and/or dates (not strings, pairs, etc.).

| Function | Description |
|---|---|
| `(vector a b ...)`, `#(a b ...)` | Build a vector |
| `(make-vector n [fill])` | Vector of `n` copies of `fill` (default 0) |
| `(vector-ref v i)`, `(vector-set! v i x)` | Get / set element `i` |
| `(vector-length v)` | Length |
| `(vector-fill! v x)` | Fill every element with `x` |
| `(vector-copy v)` | Shallow copy |
| `(vector-map f v)` | Apply `f` to each element |
| `(vector-append v1 v2 ...)` | Concatenate |
| `(vector->list v)`, `(list->vector l)` | Convert to/from a list |
| `(vector-slice v start [end])` | Sub-vector |
| `(vector-take v n)` | First `n` elements |
| `(vector-drop v n)` | All but the first `n` elements |
| `(vector-iterate first count f)` | `count`-element vector: `first`, then `(f prev)` repeatedly |
| `(vector-sum v)` | Sum of elements |
| `(vector-add v1 v2)`, `(vector-sub v1 v2)` | Elementwise add / subtract |
| `(vector-scale v s)` | Multiply every element by `s` |
| `(vectors-shuffle (list v1 v2 ...) [seed])` | Shuffle several vectors together with the *same* random permutation (keeps rows aligned); returns a list of new vectors |

### Dates

| Function | Description |
|---|---|
| `(date year month day)` | Build a date |
| `(date-year d)`, `(date-month d)`, `(date-day d)` | Accessors |
| `(date->string d)`, `(string->date s)` | Convert to/from `"YYYY-MM-DD"` |
| `(date-add-days d n)` | New date, `n` days later (negative goes earlier) |

### Regression models

`linear-regression`, `logistic-regression`, and `spline-regression` all
accept **one X vector, or a list of several** (`(list x1 x2 ...)`) for
multiple predictors, and return a `model` object.

| Function | Description |
|---|---|
| `(linear-regression x y)` | Ordinary least-squares fit: `y = intercept + sum(coef_i * x_i)` |
| `(logistic-regression x y)` | Maximum-likelihood fit: `p = sigmoid(intercept + sum(coef_i * x_i))`. Every value in `y` must be in `[0, 1]` |
| `(spline-regression x y [max-knots logistic?])` | A regression with a bit of built-in non-linearity, via a piecewise-linear hinge basis — see below |
| `(model-report m)` | Multi-line string: coefficients/terms, and fit diagnostics |
| `(model-predict m x)` | Predict at a new value. For a single-predictor model, `x` can be a bare number/date; for multiple predictors, pass `(list x1 x2 ...)` |
| `(model-coefficients m)` | Vector of coefficients, one per predictor (linear/logistic only) |
| `(model-intercept m)` | Intercept (linear/logistic only) |
| `(model-slope m)` | Same as the (only) coefficient — errors if the model has more than one predictor (linear/logistic only) |
| `(model-kind m)` | `"linear"`, `"logistic"`, `"spline"`, or `"spline-logistic"` |
| `(model-evaluate m x y)` | Evaluate a fitted model's quality against (typically held-out) data: R²/RMSE/MAE for regression-style models, log-likelihood/pseudo-R²/accuracy for probability-output models |

**Training on a subset, evaluating on the rest**, using `vector-take` /
`vector-drop` (or `vectors-shuffle` first, for a randomized split):

```lisp
(define n-train (floor (* (vector-length x) 0.7)))
(define m (linear-regression (vector-take x n-train) (vector-take y n-train)))
(display (model-evaluate m (vector-drop x n-train) (vector-drop y n-train)))
```

#### Spline regression (`spline-regression`)

A simple, dependency-free way to let a model bend instead of insisting on
a straight line — no external package required, unlike a full
Multivariate Adaptive Regression Splines implementation would need. For
each predictor `x`, a handful of "knot" locations are chosen (either
automatically, at evenly spaced quantiles of `x`'s own values, or exactly
where you specify), and the model gets one extra *hinge* feature
`max(0, x - knot)` per knot, alongside the plain linear term. Fitting is
then just an ordinary (or logistic) regression on that expanded set of
features — reusing `linear-regression`'s and `logistic-regression`'s own
fitting code underneath.

```lisp
(spline-regression x y [max-knots logistic?])
```

`max-knots` (default `3`) controls how *every* predictor is expanded, and
comes in a few interchangeable forms:

| Form | Meaning |
|---|---|
| an integer, e.g. `3` | that many knots, auto-placed at quantiles — applied to every predictor if there's more than one |
| a list of numbers, e.g. `(list 25 35)` | **exact** knot locations, when there's exactly one predictor — handy for putting a knot on either side of a range you know matters |
| `'categorical` | treat the predictor as a small set of categories (see below), instead of a continuous variable — applied to every predictor if there's more than one |
| a list with one entry per predictor, e.g. `(list 3 0)` or `(list (list 25 35) 'categorical)` | full control: each entry is itself an integer, an explicit knot list, or `'categorical`, for that one predictor. A count of `0` means that predictor stays purely linear |

Because the basis is built by this interpreter itself rather than
delegated to an external library, **a different maximum knot count (or
explicit knot locations) per variable is exact**, not an approximation.

- `logistic?` (default `#f`) — if true, `y` must be in `[0, 1]`, and the
  expanded basis is fit with logistic regression instead of ordinary
  least squares, giving a `[0, 1]`-valued prediction. Because the basis is
  non-linear, the resulting probability curve doesn't have to be
  monotonic in `x` the way a plain `logistic-regression` fit would be.

**Categorical predictors.** A variable with only a couple of distinct
values — e.g. `home-type` coded `0` for "own" and `1` for "rent" — isn't
really continuous, so hinge knots don't mean anything for it (and can
even make the fit singular, since a knot placed among only 2-3 values is
liable to exactly duplicate the plain linear column). Mark such a
predictor `'categorical` instead: it's expanded into one 0/1 indicator
column per non-baseline value (the smallest value seen becomes the
implicit baseline) rather than hinge features. `spline-regression`
proactively rejects a non-zero knot count on a predictor with 3 or fewer
distinct values, naming the predictor and suggesting `'categorical`,
rather than letting it fail later with a confusing "collinear" error.
`model-report` also flags (as a hint, not an error) any *linear*
(0-knot) predictor with 3 or fewer distinct values, in case you want to
switch it to `'categorical`. At predict time, a category value that
wasn't seen while fitting raises a clear error.

```lisp
(define home-type (vector 0 1 0 1 1))          ; 0=own, 1=rent
(define m (spline-regression (list income home-type) happiness
                              (list 2 'categorical)))
(display (model-report m))
(model-predict m (list 50000 0))                ; predict for "own"
```

`model-report` on a spline model lists, for each predictor, either its
knot locations (or that it was left purely linear) or its categories and
baseline, alongside the usual fit diagnostics.
`model-coefficients`/`model-slope`/`model-intercept` aren't available for
spline models (the fitted coefficients apply to the expanded basis, not
the original predictors, so they wouldn't mean what those names suggest)
— use `model-report` or `model-predict` instead.

#### Suggesting knot locations (`suggest-knots`)

```lisp
(suggest-knots x y window n)
```

Proposes up to `n` knot locations for `spline-regression`, based on where
`y` actually bends as a function of `x`, rather than guessing or using
generic quantiles:

1. Aggregate `y` (by mean) onto each *distinct* `x` value seen. This
   matters for panel/pool-style data, where many rows often share the same
   `x` (e.g. many pools observed at the same rate-incentive level) —
   `window` counts steps along this distinct-`x` curve, not raw rows.
2. Estimate that curve's second derivative at every interior point (a
   standard 3-point finite-difference formula, which works whether or not
   `x` is evenly spaced — so it's fine to use with date `x` values too).
3. Smooth that sequence with a centered moving average of `window` points,
   to avoid chasing single-point noise.
4. Greedily pick the points with the largest smoothed `|second derivative|`,
   skipping any candidate within `window` (by index, along the distinct-x
   curve) of a point already picked — so two knots are never chosen from
   the same window, and each picked knot represents a genuinely distinct
   bend.

Returns a Lisp list of up to `n` x-values (fewer if there aren't that many
usable candidates), sorted ascending, and ready to pass straight to
`spline-regression`:

```lisp
(define knots (suggest-knots x y 5 3))
(define m (spline-regression x y knots))
```

A larger `window` smooths away small wiggles and only flags broader bends
(and also forces suggested knots further apart); a smaller `window` is
more sensitive to sharp, narrow features but can suggest closely-spaced
knots. `x` and `y` don't need to be pre-sorted by `x` — this sorts them
internally first. Because `window` is measured in distinct-`x` steps,
choose it relative to how many distinct `x` values your data actually has
(e.g. `window=200` is far too large if `x` only takes ~200 distinct
values total) — not relative to the row count. A distinct `x` value
backed by very few rows has a noisier mean, and can occasionally attract
a spurious knot; trimming very sparse `x` tails before calling
`suggest-knots` is reasonable if that happens.

### Charting

| Function | Description |
|---|---|
| `(plot-xy x y-list)` | Plot X against each vector in `y-list`, connected lines, auto labels |
| `(plot-xy-regression x y label [kind])` | Plot one Y series plus its regression line/curve. `kind` is `"linear"` (default) or `"logistic"` |
| `(plot-xy-full x y-list labels connect? title reg-label [kind])` | Full control: custom labels, lines on/off, title, and which labeled series (or `#f`) gets a regression overlay |
| `(save-chart filename [width height dpi])` | Save the most recently plotted chart to an image file. Format is taken from the extension (`.png`, `.pdf`, `.svg`, ...). Works with or without the GUI running (needs matplotlib) |

Each Y series gets its own marker shape, cycling through circle, square,
triangle, diamond, etc.

### FRED (Federal Reserve Bank of St. Louis) data, and CSV loading

| Function | Description |
|---|---|
| `(fred-series series-id [api-key] [start-date] [end-date])` | Fetch a data series; returns `(cons dates-vector values-vector)`. `api-key` may be omitted if the `FRED_API_KEY` environment variable is set. `start-date`/`end-date` are optional `"YYYY-MM-DD"` strings or dates |
| `(load-csv filename [has-header?])` | Load a CSV's columns as vectors; returns `(cons headers-list vectors-list)`. Each column is auto-detected as numeric, as a date (`"YYYY-MM-DD"`), or skipped (along with its header) if neither. A row is included only if every kept column has a value there, so all returned vectors stay the same length and aligned. `has-header?` defaults to `#t` |

### tastytrade (real broker data)

Requires the `tastytrade` package (`pip install tastytrade`) and a
tastytrade account. All four functions take a `credentials-path` — a
local JSON file `{"client_secret": ..., "refresh_token": ..., "is_test":
false}` — as their first argument; see `tasty_api/README.md` for the
one-time OAuth setup (the same credentials file works for both `tasty_api`
and this interpreter). `product` is one of `"CL"`, `"MCL"`, `"ES"`,
`"NQ"`, `"SR3"`, `"ZN"`, `"ZQ"` — see `(tastytrade-products)`.

| Function | Description |
|---|---|
| `(tastytrade-test-connection credentials-path)` | Authenticate and return a status string (account number(s) found), or raise an error describing what went wrong |
| `(tastytrade-products)` | List of supported product code strings |
| `(tastytrade-futures-curve credentials-path product [n-months])` | Fetch the product's futures term structure; returns `(cons delivery-dates-vector last-prices-vector)`, one entry per upcoming contract month that actually has a price. `n-months` (default 18) is how many upcoming months to guess symbols for — months that don't exist for this product (e.g. non-quarterly months for ES/NQ/ZN) are silently skipped. Feed the result straight into `plot-xy`, `linear-regression`, `spline-regression`, etc. |
| `(tastytrade-option-chain credentials-path product [n-months max-strikes-per-expiration include-iv? greeks-timeout])` | Fetch a futures-option chain; returns a Lisp list of rows, each a 10-element list `(symbol type strike expiration-date delivery-month underlying-future last-price implied-volatility volume open-interest)`. `type` is `"Call"` or `"Put"`; missing values (e.g. no recent Greeks snapshot) come back as `'()`. Defaults: `n-months` 12, `max-strikes-per-expiration` 15 (strikes nearest the underlying's price, per expiration), `include-iv?` `#t`, `greeks-timeout` 25.0 seconds. Implied volatility comes from a live per-contract Greeks stream, so it's the slow part — pass `include-iv?` `#f` to skip it and fetch much faster when you only need prices/strikes |

```lisp
(define creds "tastytrade_credentials.json")
(define curve (tastytrade-futures-curve creds "CL" 12))
(plot-xy (car curve) (list (cdr curve)))

(define chain (tastytrade-option-chain creds "CL" 3 10 #f))  ; skip IV, fast
(display (length chain))
(display (car chain))   ; (symbol type strike expiration delivery underlying price iv volume oi)
```

### Input / output

| Function | Description |
|---|---|
| `(display x)` | Print without a trailing newline |
| `(newline)` | Print a newline |
| `(print x)` | Print with a trailing newline |

---

## A short example

```lisp
(define prices (vector 10 20 30 40 50))
(define demand (vector 0 0 1 0 1))          ; y in [0,1]

(define m (logistic-regression prices demand))
(display (model-report m))

(plot-xy-regression prices demand "Demand" "logistic")
(save-chart "demand.png")
```
