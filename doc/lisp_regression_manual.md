# Regression

A regression finds how one thing, `y`, depends on others, the predictors
`x`: how fast a pool of mortgages prepays at each rate incentive and loan
age, say, or how a mortgage rate moves with the 10-year Treasury yield.
The interpreter's regression functions are builtins (in
`lisp_interp/lisp_regression.py`), so there is nothing to load.

A regression is made of a few choices that don't depend on each other,
and this manual takes them one at a time:

1. **What is fit**: the kind of model, and what makes one fit better
   than another. Least squares makes the squared misses smallest; least
   absolute deviation makes their sizes smallest; logistic regression
   makes the data most likely; and so on. "The fits" has one section
   for each kind.
2. **Whether the line can bend**: five of the kinds can also be fit as a
   *spline*, a line that bends at knots. Bending works the same way
   whatever is fit: "Bending: spline models".
3. **How sure the coefficients are**: their standard errors, and what to
   tell the fit when the rows aren't each new information, because they
   come in groups (`:groups`) or follow each other in time (`:lags`).
   That works the same way for every kind: "Standard errors".
4. **What to do with a model**: report it, predict with it, evaluate it.
   The same functions work on every kind: "Using a model".
5. **How good it is**: the measures of fit, explained, and how well it
   predicts data it wasn't fit to: "How good is a model?" and
   "Predicting data a model wasn't fit to".

What every fitting function takes, the data and its weights, comes
first: "Giving a fit its data".

There are ten documents. The **language manual**,
[lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the
syntax, the special forms and macros, and the general builtins, including
the vectors and tables a regression is fit to, and `plot-chart`. The
**library manual**, [lisp_library_reference.md](lisp_library_reference.md),
covers getting data, the other models, and investments; its "Models fitted
to Freddie Mac's loans" are regressions of these kinds. The **example
programs**, [lisp_example_programs.md](lisp_example_programs.md), say how
whole programs are put together. The **CMO manual**
([lisp_cmo_manual.md](lisp_cmo_manual.md)), the **forecasting manual**
([lisp_forecasting_manual.md](lisp_forecasting_manual.md)), the **paths
manual** ([lisp_paths_manual.md](lisp_paths_manual.md)), the **macro
models manual** ([lisp_macro_models_manual.md](lisp_macro_models_manual.md)),
and the **data guide** ([economic_data_guide.md](economic_data_guide.md))
cover structured deals, forecasting questions, yield curves and paths,
models of the whole economy, and which agency publishes what data; the
**baseball manual** ([lisp_baseball_manual.md](lisp_baseball_manual.md))
plays baseball games from counted plays. **This
one is regression.** A section name in quotes is a section of this
manual, unless it says otherwise.

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [The functions at a glance](#the-functions-at-a-glance)
- [Giving a fit its data](#giving-a-fit-its-data)
  - [x and y](#x-and-y)
  - [Weights](#weights)
- [The fits](#the-fits)
  - [Least squares](#least-squares)
  - [Least absolute deviation](#least-absolute-deviation)
  - [A quantile](#a-quantile)
  - [Logistic](#logistic)
  - [A count](#a-count)
  - [Least squares, held back: ridge and lasso](#least-squares-held-back-ridge-and-lasso)
  - [A formula of your own](#a-formula-of-your-own)
- [Bending: spline models](#bending-spline-models)
  - [Knots: max-knots](#knots-max-knots)
  - [Smooth splines: :smooth](#smooth-splines-smooth)
  - [The spline functions](#the-spline-functions)
  - [Choosing knots](#choosing-knots)
- [Standard errors: how sure the coefficients are](#standard-errors-how-sure-the-coefficients-are)
  - [Rows that come in groups: :groups](#rows-that-come-in-groups-groups)
  - [Rows in time order: :lags](#rows-in-time-order-lags)
- [Using a model](#using-a-model)
- [How good is a model? The measures, explained](#how-good-is-a-model-the-measures-explained)
- [Predicting data a model wasn't fit to](#predicting-data-a-model-wasnt-fit-to)
- [Where to see them, and the code](#where-to-see-them-and-the-code)

## The functions at a glance

| | A straight line (or plane) | A line that bends at knots | The best fit is the one that... |
|---|---|---|---|
| Least squares | `linear-regression` | `spline-regression` | makes the sum of the squared misses smallest |
| Least absolute deviation | `lad-regression` | `spline-lad` | makes the sum of the misses' sizes smallest, so a few points far out barely move it |
| A quantile (the 90th percentile, say) | `quantile-regression` | `spline-quantile` | has that share of the points below it |
| Logistic, for a probability | `logistic-regression` | `spline-logistic` | makes what happened most likely, with a curve in the shape of an S |
| Poisson, for a count | `poisson-regression` | `spline-poisson` | makes the counts most likely, with an average that can't go below 0 |
| Least squares, held back | `ridge-regression`, `lasso-regression` | | makes the squared misses smallest, plus a cost for the coefficients' sizes |
| A formula of your own | `nonlinear-regression` | | makes the squared misses smallest, with whatever curve you write |

Every fitting function is called the same way: `x`, then `y`, then the
arguments of its own kind, then the weights, then keyword options.

| Function | After `x` and `y` | Keyword options |
|---|---|---|
| `linear-regression`, `lad-regression`, `poisson-regression` | `[weights]` | `:groups`, `:lags` |
| `quantile-regression` | `quantile [weights]` | `:groups`, `:lags` |
| `logistic-regression` | `[weights]` | `:floor`, `:ceiling`, `:groups`, `:lags` |
| `ridge-regression`, `lasso-regression` | `penalty [weights]` | `:folds`, `:seed` (for choosing among several penalties) |
| `nonlinear-regression` | `formula start [weights]` | `:groups`, `:lags` |
| `spline-regression`, `spline-lad`, `spline-poisson` | `[max-knots weights]` | `:smooth`, `:groups`, `:lags` |
| `spline-quantile` | `quantile [max-knots weights]` | `:smooth`, `:groups`, `:lags` |
| `spline-logistic` | `[max-knots weights]` | `:floor`, `:ceiling`, `:smooth`, `:groups`, `:lags` |

Each returns a model, which `model-report`, `model-predict`, and the other
functions of "Using a model" take, and which `model-kind` names:
`"linear"`, `"lad"`, `"quantile"`, `"logistic"`, `"poisson"`, `"ridge"`,
`"lasso"`, `"nonlinear"`, `"spline"`, `"spline-lad"`, `"spline-quantile"`,
`"spline-logistic"`, or `"spline-poisson"`.

`examples/regression_kinds_example.lsp` fits the kinds to the same made-up
data and charts them, one above another, with a floor and ceiling, a
quantile band, and a smooth spline, and cross-validates each.

## Giving a fit its data

### x and y

`x` is the predictors: a vector, for one; a list of vectors, `(list x1 x2
...)`, for several; or a list of `(name . vector)` pairs, which is how
`sqlite-query` gives a query's columns, so they can go straight in. `y` is
a vector, or a `(name . vector)` pair. Every vector must be the same
length, one value for each row. When the vectors have names, `model-report`
uses them in place of `x1`, `x2`, and `y`.

```lisp
(define rows (sqlite-query conn "select zero_flag, balance, loan_age from t"))
(define m (linear-regression (cdr rows) (car rows)))   ; zero_flag from balance and loan_age
(display (model-report m))   ; "Linear model:  zero_flag = ... + c*balance + c*loan_age"
```

A date, anywhere a number is expected, is taken as its day number. The
fits rescale each predictor to an average of 0 and a standard deviation of
1 before fitting, which keeps the arithmetic steady whatever the
predictors' units (a day number beside a percentage), and turn the
coefficients back into the predictors' own units afterward; it doesn't
change the answer. It is an error if the vectors aren't the same length,
a predictor never changes, or two predictors are so alike that the fit
can't tell them apart (for least squares; ridge and lasso are for that).

### Weights

Every fitting function takes an optional `weights` vector, after `x`, `y`,
and the arguments of its own kind: one number, 0 or more, for each row.
Leave it out (or give `'()`) to weight every row the same. Each row then
counts by its weight in what the fit makes smallest (or most likely): a
weight of 2 counts a row as if it were there twice, and a weight of 0
leaves it out. Only the weights' sizes relative to each other matter, not
their scale. That's the way to fit to grouped data -- a row for each
rate-incentive bucket rather than each loan -- where a bucket of $500
million of loans should count for far more than one of $2 million, its
average being that much surer:

```lisp
(define bucket-rate (vector 0.02 0.04 0.06 0.08))    ; one row per rate bucket
(define bucket-cpr   (vector 0.05 0.08 0.15 0.30))
(define bucket-balance (vector 450000000 12000000 8000000 300000000))
(define m (linear-regression bucket-rate bucket-cpr bucket-balance))
```

For a Poisson model, the weights have a second use: the number each count
is out of (see `poisson-regression`).

## The fits

One section for each kind: the model, what makes it the best fit, how
it's found, and what is particular about its standard errors and its
report. What all the kinds share -- bending, standard errors, the
functions that use a model -- is in the chapters after this one.

### Least squares

#### `(linear-regression x y [weights] [:groups g :lags l])`
The straight line (or plane), `y = intercept + sum(coefficients[i] *
x[i])`, that makes the sum of the squared misses,

```
sum over every row i of:  weight[i] * (y[i] - prediction[i])^2
```

smallest. The model's kind is `"linear"`.

**How it's found.** The sum of squares is a parabola in the coefficients,
so its lowest point has a formula: setting its slope in each coefficient
to 0 gives one linear equation for each (the "normal equations"), and they
are solved exactly, in one step, by Gauss-Jordan elimination with partial
pivoting (`solve_linear_system` in `lisp_regression.py`) -- no searching.
Building the equations is the work, about `n * p^2` for `n` rows and `p`
coefficients, and it's done with numpy, so millions of rows fit quickly.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(model-intercept m)            ; => -0.7
(model-slope m)                ; => 10.3
```

**Its standard errors** are the usual ones: the residual variance, the
sum of squares over `n - p`, times the inverse of the normal equations'
matrix. Its t values have `n - p` degrees of freedom.

### Least absolute deviation

#### `(lad-regression x y [weights] [:groups g :lags l])`
The straight line that makes the sum of the misses' sizes, `sum(weight[i]
* |y[i] - prediction[i]|)`, smallest, rather than the sum of their
squares. It's a robust regression: a few outliers barely move it. A point
far from the others pulls a least-squares fit toward it in proportion to
the *square* of its distance, but a LAD fit only in proportion to the
distance itself. (With no predictors, LAD would give the median of `y`, as
least squares gives the mean.) It suits small data where one or two points
are wild -- a bad print, a data error, a month with a one-off event -- and
you'd rather they didn't decide the answer. The model's kind is `"lad"`.

```lisp
(define x #(1 2 3 4 5 6 7 8 9 10))
(define y #(3 5 7 9 11 13 15 17 19 100))       ; y = 2x + 1, but for the last one
(model-slope (linear-regression x y))           ; => 6.30909090909091
(model-slope (lad-regression x y))              ; => 2.0
(model-intercept (lad-regression x y))          ; => 1.0
(model-residuals (lad-regression x y) x y)      ; => #(0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 79.0)
```

`model-residuals` shows which points the fit set aside: those with the
largest residuals.

**How it's found.** There's no formula for a LAD fit, but one fact makes it
easy to find: some best fit goes exactly through `p` of the points, `p`
being the number of coefficients counting the intercept -- for a line,
through two of them. So the fit starts through the `p` points closest to
the least-squares fit, and then, over and over, holds the fit at `p - 1`
of the points it goes through and swings it -- for a line, rotates it
about one point. How far to swing it is a weighted median, which lands the
fit on another of the points. When no swing lowers the sum of the misses'
sizes, no fit does. This is Wesolowsky's method (1981): each step is
exact, the answer is the exact LAD fit, and it usually takes only a few
steps -- a hundred thousand points take well under a second.

**Its standard errors** come from the usual large-sample formula for LAD,
which depends on how closely the misses crowd around 0. That's estimated
two ways -- as for normal errors, from the median absolute residual, and
from the residuals themselves, from how far apart their quantiles just
above and below the middle are -- and the larger is used. Neither depends
on the most extreme residuals, so moving an outlier further out doesn't
change the standard errors at all. In simulations with as few as 8
points, and with normal, heavy-tailed, or contaminated errors, the 95%
intervals they give held the true coefficient 92% to 97% of the time.
With `p` points or fewer, the fit is exact and the standard errors are
`nan`. The t values have `n - p` degrees of freedom.

**Its report** gives the MAE, the average size of a miss, and a pseudo
R-squared, 1 − the MAE / the MAE of predicting the median of `y` for every
row (Koenker and Machado's R1), and the number of steps.

```lisp
(define month #(1 2 3 4 5 6 7 8 9 10 11 12))
(define cpr #(4.5 5 6.5 6 7.5 8.5 8 9.5 30 10.5 11 12.5))   ; month 9 had a one-off payoff
(display (model-report (lad-regression month cpr)))
```
prints:
```
Least absolute deviation model:  y = 3.78571 + 0.714286*x1
  term        coefficient     std error    t value    p value
  intercept       3.78571      0.612654      6.179   0.000104
  x1             0.714286     0.0832433      8.581   6.34e-06
  MAE              = 1.98214    (perfect: 0; predicting the median of y for every row: 3.70833)
  pseudo R-squared = 0.46549    (perfect: 1; predicting the median of y for every row: 0)
  iterations       = 2 (converged)
  n                = 12
```
Least squares, pulled up by month 9, gives a slope of 1.03 with a standard
error of 0.50.

### A quantile

#### `(quantile-regression x y quantile [weights] [:groups g :lags l])`
The fit with `quantile` of the points below it: `0.9` for the line that 90%
of the points are under, the 90th percentile of `y` at each `x`. Least
squares fits the average; quantile regression fits a percentile, so two
of them -- the 10th and the 90th, say -- make a band around the data, which
can widen or narrow as `x` changes. For risk, that's often the question:
not what prepayment speeds are on average at a 2-point incentive, but how
fast they are in the fastest tenth of pools. `quantile` is a number between
0 and 1. The model's kind is `"quantile"`.

It makes the sum of the misses' *losses* smallest, where a point above the
fit costs `quantile` times its distance and one below it `1 - quantile`
times its distance: for `0.9`, being above the fit costs nine times as
much as being below, so the fit settles where 90% of the points are below
it. For `0.5` the two cost the same, and the fit is exactly
`lad-regression`'s: least absolute deviation is the 50% quantile. It's
found by LAD's method, with a weighted quantile in place of the weighted
median at each swing. Like LAD, it is barely moved by a point far out.

```lisp
(define x (vector-range 400))
(random-seed 3)
(define y (+ (/ x 2) (list->vector (map (lambda (i) (* 20 (- (random-float) 0.5))) (iota 400)))))  ; noise from -10 to 10
(define upper (quantile-regression x y 0.9))
(define lower (quantile-regression x y 0.1))
(list (format "{:.1f}" (model-intercept upper)) (format "{:.1f}" (model-intercept lower)))   ; => ("8.3" "-8.7")
(plot-chart (list (list "data" x y :symbol "circle")       ; the band, shaded from one fit to the other
                  (list "10th to 90th percentile" x (model-predict upper x) :fill (model-predict lower x)))
            :title "The band that 80% of the points are in")
```
(The noise is spread evenly from -10 to 10, so the 90th percentile is 8
above the line `y = x / 2`, and the 10th, 8 below it: these 400 points
give about that.) `plot-chart`'s `:fill` shades from one series' values to
another's, here from the 90th percentile's predictions down to the 10th's.

The band shows how spread out the points are at each `x`, not how sure the
fit is: more points won't make it narrower, only more exact. How sure the
fit is shows in the standard errors.

**Its standard errors** are found as LAD's are, for the quantile. Far from
the median they need more points to be right: with 30 points and
heavy-tailed errors, the 90th percentile's 95% intervals held the true
coefficient only about 80% of the time, but with 200, 94% of the time.

**Its report** gives the quantile; how many points are below the fit, on
it, and above it (with `n` points, at most `quantile * n` below it, and at
least that many below or on it); the average loss; and a pseudo
R-squared, as for LAD, with losses in place of the misses' sizes.

### Logistic

#### `(logistic-regression x y [weights] [:floor f :ceiling c :groups g :lags l])`
A model of a probability, `p = sigmoid(intercept + sum(coefficients[i] *
x[i]))`: an S-shaped curve from 0 to 1 (`sigmoid(z)` is `1 / (1 + e^-z)`).
Every `y` must be between 0 and 1: a 0 or a 1 (did each loan prepay?), or
a share (what share of a pool did?). The best fit is the one that makes
what happened most likely: it makes the (weighted) log-likelihood

```
sum over every row i of:  weight[i] * ( y[i]*log(p[i]) + (1-y[i])*log(1-p[i]) )
```

largest, `p[i]` being the model's chance for row `i`. The model's kind is
`"logistic"`.

**How it's found.** The log-likelihood isn't a parabola, so there's no
formula for its top. The coefficients are found by Newton-Raphson (also
called iteratively reweighted least squares, IRLS), from all zeros: each
step solves for the move that would reach the top if the log-likelihood
were a parabola where the coefficients are -- with the same linear-system
solver least squares uses -- and takes it, or half of it, or a quarter, if
the whole step would make the data less likely. It stops when a step is
smaller than `1e-8`, or after 50 steps. Sometimes the true top has a
coefficient of infinity: when a predictor separates the 0s from the 1s
perfectly, or every point of a spline's piece is at or beyond the floor or
ceiling, which the curve comes ever closer to by getting steeper. Then the
fit stops where it is, and `model-report` says it did NOT converge: its
predictions are near the limit the curve was heading for, but its
coefficients and standard errors mean little.

**A floor and a ceiling.** For a curve that flattens out at levels other
than 0 and 1 -- a chance of prepaying that rises from about 3% to about
48%, say -- give them as `:floor` and `:ceiling`, and the model is

```
y = floor + (ceiling - floor) * sigmoid(intercept + sum(coefficients[i] * x[i]))
```

One of the two can be left out: it is 0 or 1, as usual. The floor and
ceiling are yours to choose, from what you know of the data -- not its
smallest and largest values, which are often the points out of line. How
the model is fit depends on whether they are between 0 and 1:

- **Between 0 and 1, it is a probability** -- one that can't go below the
  floor or above the ceiling -- and every `y` must be between 0 and 1. It
  is fit by maximum likelihood, as it is, with `p` the curve above; the
  method (Fisher scoring) is the Newton-Raphson above, with a floor of 0
  and a ceiling of 1. A `y` beyond the floor or ceiling is just one that
  happened to be. `model-evaluate` treats the prediction as a probability.
- **Outside 0 and 1, it is a number, not a probability**: a price, a
  percentage, a count, that rises in an S from the floor to the ceiling.
  `y` is rescaled to `(y - floor) / (ceiling - floor)`, which goes from 0
  to 1, and that is fit as a probability would be. Data scatters about the
  levels a curve flattens out at, so some of it is beyond them: a `y` below
  the floor is taken to be at the floor, and one above the ceiling at the
  ceiling (`model-report` says how many were). `model-evaluate` treats the
  prediction as any other number.

A probability that can't go below the floor, or above the ceiling, also
limits what a point far from the curve can cost the fit: with them, the
curve is pulled much less by points out of line.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define m (logistic-regression x y :floor 0.03 :ceiling 0.48))
(vector-round (vector (model-intercept m) (model-slope m)) 6)   ; => #(-3.0 3.0)
(format "{:.3f}" (model-predict m 10))                          ; => "0.480"
(define percent (logistic-regression x (* 100 y) :floor 3 :ceiling 48))   ; the same, in percent
(format "{:.1f}" (model-predict percent 10))                     ; => "48.0"
```

**Fitting the floor and ceiling.** Give `'fit` for either, or both --
`:ceiling 'fit` -- and it is the one that makes the data most likely,
with the curve fit for it. For a probability only: every `y` must be
between 0 and 1. It's found by trying every 0.05 from 0 to 1, fitting the
curve for each, then every 0.01 near the best, and every 0.002 near the
best of those. `model-report` gives each fitted one, and its 95% range:
how far it could move, either way, before the data is clearly less likely
-- its log-likelihood lower by 1.92, which for 0s and 1s makes the range
roughly a 95% confidence interval. (That's in the units of the average
weight; and for shares, which scatter less than 0s and 1s, it's 1.92
times how much less, which narrows the range accordingly -- a "quasi-
likelihood" ratio. It doesn't allow for `:groups` or `:lags`, and it's
found to the nearest 0.002.) A ceiling is only well fitted where there is
data on the curve's flat top: with none, the range runs up to 1. A spline
can level off by itself, at its knots, so a `spline-logistic`'s fitted
ceiling is only loosely set. `model-floor` and `model-ceiling` give a
model's floor and ceiling.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define m (logistic-regression x y :floor 'fit :ceiling 'fit))
(list (model-floor m) (model-ceiling m))                        ; => (0.03 0.48)
```

**Its standard errors.** When `y` is all 0s and 1s, they are the usual
ones for logistic regression, from the inverse of the information (how
sharply the log-likelihood curves at its top), which takes each `y` to
scatter about its chance `p` by `p (1 - p)`, as a 0 or a 1 does. The
weights are first rescaled to average 1, so that weighting by balance in
dollars doesn't make the model look vastly surer than its rows justify:
the weights say how much each row counts relative to the others, not how
many copies of it there are. A **share** -- the part of a pool that
prepaid in a month -- is an average over many loans, and scatters far
less, so those would be much too large: when any `y` is between 0 and 1,
the standard errors come instead from how much `y` actually scatters about
the fit (the sandwich of "Standard errors", with each row its own group),
and `model-report` says so. For a `spline-logistic` model of the pools'
CPRs in `examples/synthetic_mbs_pools.csv`, the usual ones would be 10 to
25 times too large; and pools' months are alike too, so with each pool's
months a group (`:groups pool-id`) they are 2 to 4 times larger again. The
test is a z test, with the normal distribution.

**Its report** gives the log-likelihood, McFadden's pseudo R-squared, and
the AUC -- with R-squared, RMSE, and MAE first, if `y` is shares, whose
perfect log-likelihood, pseudo R-squared, and AUC are short of 0, 1, and 1
(see "How good is a model?") -- the floor and ceiling, if they aren't 0
and 1, and the number of steps and whether it converged.

### A count

#### `(poisson-regression x y [weights] [:groups g :lags l])`
A model of a count -- the defaults in a pool in a month, the trades in a
day -- whose average is `exp(intercept + sum(coefficients[i] * x[i]))`.
The average can't go below 0, as a straight line's could, and each
coefficient says how much the *logarithm* of the average changes with its
predictor: one more unit of the predictor multiplies the average count by
`exp(coefficient)`. The best fit makes the counts most likely, taking each
to be a Poisson count -- what you get by counting events that happen by
chance, independently, at a steady average rate -- whose average is the
model's. Every `y` must be 0 or more. The model's kind is `"poisson"`.

**Counts out of different numbers.** Pools of different sizes have
different numbers of defaults just from their sizes. Give `y` as the rate
-- the count divided by the number it's out of -- and the number as the
weights: the fit is then exactly the one the counts and their numbers
would give (with the logarithm of the number as an "offset"), and
`model-predict` gives the rate. `y` needn't be a whole number for that
reason.

```lisp
(define ltv #(0.6 0.7 0.8 0.9 1.0 1.1))                  ; each pool's loan-to-value
(define loans #(500 400 300 200 100 50))                 ; how many loans are in each
(define defaults #(3 7 4 8 2 4))                         ; and how many defaulted
(define m (poisson-regression ltv (/ defaults loans) loans))   ; the default rate, each pool counting by its loans
(format "{:.2f}" (model-slope m))                        ; => "4.16"
(format "{:.2f}" (exp (* 0.1 (model-slope m))))          ; => "1.52"
(format "{:.4f}" (model-predict m 0.95))                 ; => "0.0351"
```

Each 10 points of loan-to-value multiply the default rate by 1.52; at 95%,
it is 3.5%.

**How it's found** is as for logistic regression: Newton-Raphson, with
step halving, from every row's average being `y`'s average. When every
count is 0 for some range of a predictor -- all of one category, say --
the best coefficient is minus infinity; the fit stops, and `model-report`
says it did NOT converge.

**Its standard errors** are the likelihood's, from the information, times
the square root of the **dispersion**: how many times as much the counts
vary about the fit as Poisson counts would by chance alone (Pearson's
chi-squared, `sum(weight * (y - average)^2 / average)`, over `n - p`), as R's
`quasipoisson` does. Real counts often vary more than chance -- one pool's
loans are alike, and a bad month is bad for many of them -- and then the
likelihood's alone would be too small. With weights that are the numbers
the counts are out of, the dispersion is 1 for counts that vary only by
chance; with other weights, it's in their units, and the standard errors
don't depend on the weights' scale either way. The test is a z test.

**Its report** gives the dispersion, the mean deviance, the measure a
Poisson model makes smallest, and a pseudo R-squared from it (see "How
good is a model?"), and the number of steps.

### Least squares, held back: ridge and lasso

#### `(ridge-regression x y penalty [weights] [:folds 5 :seed 1])`
#### `(lasso-regression x y penalty [weights] [:folds 5 :seed 1])`
A straight line fit by least squares, but with a cost for each
coefficient's size, so that the coefficients come out smaller -- pulled
toward 0 -- and steadier. With predictors that go together, least squares
can give two nearly alike ones large coefficients of opposite signs, which
nearly cancel, and which a little noise swings about; ridge and lasso
don't. Lasso also leaves out the predictors that don't earn their place,
which is what it's for: give it many, and it picks. The model's kind is
`"ridge"` or `"lasso"`.

The cost is on the coefficients of the *standardized* predictors, each
rescaled to an average of 0 and a standard deviation of 1. There, a
coefficient is how much `y` changes for a change of one standard
deviation in its predictor, so each costs the same for the same effect,
whatever its predictor's units. The intercept costs nothing. With `W` the
total weight, the fit makes smallest

```
ridge   sum(weight * miss^2) / (2 W)  +  penalty / 2 * sum(standardized coefficient^2)
lasso   sum(weight * miss^2) / (2 W)  +  penalty * sum(|standardized coefficient|)
```

What the penalty does is clearest for predictors that don't go together at
all: each of ridge's standardized coefficients is then least squares'
divided by `1 + penalty`, and each of lasso's is least squares' moved
toward 0 by the penalty -- and is 0 if it was nearer 0 than that. So
ridge's penalty has no units, and lasso's is in `y`'s units. A penalty of 0
is least squares.

```lisp
(random-seed 1)
(define incentive (random-normal-vector 100))
(define age (random-normal-vector 100))
(define spread (+ incentive (* 0.05 (random-normal-vector 100))))   ; nearly the same as the incentive
(define cpr (+ (* 2 incentive) (* 0.5 age) (random-normal-vector 100)))
(define predictors (list incentive spread age))
(vector-round (model-coefficients (linear-regression predictors cpr)) 2)       ; => #(3.32 -1.39 0.55)
(vector-round (model-coefficients (ridge-regression predictors cpr 0.1)) 2)    ; => #(0.94 0.88 0.53)
(vector-round (model-coefficients (lasso-regression predictors cpr 0.1)) 2)    ; => #(1.83 0.0 0.48)
```

The CPR here is twice the incentive and half the age, and the spread is
nearly the incentive. Least squares can't tell the incentive from the
spread, and splits their effect wildly: 3.32 and -1.39, each with a
standard error of 2.3. Ridge shares it about evenly. Lasso gives it to one
of them and leaves the other out.

**How it's found.** Ridge's sum is a parabola, and is solved in one step,
as least squares is. Lasso's isn't -- the sizes `|coefficient|` have a
corner at 0 -- and it's found by coordinate descent: over and over, each
coefficient in turn is set to its best value with the others held where
they are, until a sweep through them all changes none of them by more
than a tiny amount. With the others held, a coefficient's best value is
easy: how hard what's left of `y` pulls on it, moved toward 0 by the
penalty, and 0 if the pull is weaker than the penalty.

**Choosing the penalty.** Give a list of penalties, and each is tried by
cross-validation, as `cross-validate` does it: the rows are dealt into
`:folds` folds (5, unless given), by `:seed` (1); for each penalty, a model
is fit to all the rows but each fold's in turn, and predicts that fold.
The penalty whose predictions have the smallest root mean squared error,
over every row, is used, and `model-report` lists each one's.

```lisp
(display (model-report (lasso-regression predictors cpr (list 0.01 0.03 0.1 0.3))))
```
prints:
```
Lasso model:  y = -0.234907 + 1.91146*x1 + 0*x2 + 0.558851*x3
  term        coefficient  standardized
  intercept     -0.234907
  x1              1.91146       1.91535
  x2                    0             0  (left out)
  x3             0.558851      0.568828
  penalty          = 0.01  (in y's units, on the standardized coefficients: at 1.98943 or more, every predictor is left out)
  predictors kept  = 2 of 3
  penalties tried, by 5-fold cross-validation:
    0.01          cross-validated RMSE 1.01434  (the best: chosen)
    0.03          cross-validated RMSE 1.0164
    0.1           cross-validated RMSE 1.0295
    0.3           cross-validated RMSE 1.114
  R-squared        = 0.819526   (perfect: 1; predicting the average of y for every row: 0)
  ...
```

**There are no standard errors**, and so no `:groups` or `:lags`: the
coefficients are pulled toward 0 on purpose, which the usual standard
errors don't allow for. Its report gives, beside each coefficient, its
standardized one, which the penalty is on; for lasso, the penalty at which
every predictor would be left out, and how many it kept.

### A formula of your own

#### `(nonlinear-regression x y formula start [weights] [:groups g :lags l])`
The parameters of a formula you write that make the sum of the squared
misses smallest: least squares for any curve, not only a straight line --
an S-curve of a shape you choose, a decay, a yield curve's. The model's
kind is `"nonlinear"`.

`formula` is a lambda of the predictors, then the parameters: `(lambda (x
a b c) ...)` for one predictor and three parameters, `(lambda (x1 x2 a b)
...)` for two and two. Its parameters' names are the names in the report.
It's called with each predictor's whole column, a vector, and a number for
each parameter, and gives a vector, a prediction for each row -- so write
it with arithmetic that works on vectors: `+`, `-`, `*`, `/`, `expt`,
`exp`, `log`, `sqrt`, `atan`, `sigmoid` (in the language manual), `max`, `min`, `abs`, `vector-where`;
not `if`, which takes one value. `start` is a list of numbers, a first
guess at each parameter.

```lisp
(define x (- (/ (vector-range 41) 10.0) 1))                        ; incentives from -1 to 3 points
(define y (+ 8 (* 20 (+ 0.5 (/ (atan (* 2.5 (- x 1))) pi)))))      ; an S, from 8% up to 28%, steepest at 1
(define (s-curve x low height steepness middle)
  (+ low (* height (+ 0.5 (/ (atan (* steepness (- x middle))) pi)))))
(define m (nonlinear-regression x y s-curve (list 5 10 1 0.5)))
(vector-round (model-coefficients m) 4)                            ; => #(8.0 20.0 2.5 1.0)
```

The same with noise, and names:

```lisp
(random-seed 3)
(define noisy (+ y (random-normal-vector 41)))
(display (model-report (nonlinear-regression (list (cons "incentive" x)) (cons "cpr" noisy) s-curve (list 5 10 1 0.5))))
```
prints:
```
Nonlinear model:  cpr = (+ low (* height (+ 0.5 (/ (atan (* steepness (- x middle))) pi))))
  (where x is incentive)
  parameter      estimate     std error    t value    p value
  low             8.21728       0.45051      18.24    4.4e-20
  height           19.237      0.794305      24.22   2.72e-24
  steepness       2.69767      0.380612      7.088   2.17e-08
  middle         0.945402     0.0310133      30.48   8.14e-28
  R-squared        = 0.984472   (perfect: 1; predicting the average of y for every row: 0)
  RMSE             = 0.871666   (perfect: 0; predicting the average of y for every row: 6.99515)
  MAE              = 0.708198   (perfect: 0; predicting the median of y for every row: 6.5855)
  iterations       = 12 (converged)
  n                = 41
```

**How it's found.** There's no formula for the answer, so it's found by
steps from the start (Levenberg and Marquardt's method). At each step, how
each prediction changes with each parameter -- the slopes, found by
nudging each parameter a little either way -- makes the formula a straight
line in the parameters, near where they are, and the step goes to where
least squares says that line is best. A step that goes too far, and makes
the sum of squares bigger, is replaced by a shorter one, more nearly
downhill; once steps succeed again, they lengthen. It stops when a step is
tiny, or no longer lowers the sum of squares by more than a tiny part of
it. A formula can have more than one best fit, or none, so the start
matters: a guess of the right sign and size is usually enough. A fit that
didn't converge says so, and suggests other start values.

**Its standard errors** are least squares', for that straight line at the
fit: the residual variance times the inverse of `J'WJ`, `J` being the
slopes. Its t values have `n - m` degrees of freedom, `m` being the number
of parameters. For a formula that is a straight line, they're
`linear-regression`'s. A nonlinear model has parameters, not an intercept
and coefficients: `model-coefficients` gives the parameters, in order, and
`model-intercept` and `model-slope` are errors. It can't be saved with
`save-variables`, since its formula is a procedure; save its parameters,
and fit it again from them.

## Bending: spline models

A straight line can't follow a curve: a prepayment rate that rises slowly
at small incentives, quickly in the middle, and slowly again once most
borrowers who can refinance have. A spline can. For each predictor, a
handful of **knots** are chosen, and the predictor gets an extra column
for each: a *hinge*, `max(0, x - knot)`, which is 0 to the knot's left and
rises from it. A straight line in the predictor and its hinges is a line
that bends at each knot. The fit itself is any of five kinds, on those
columns, just as if you had made them yourself:

| Function | Fit as | Kind |
|---|---|---|
| `spline-regression` | `linear-regression` | `"spline"` |
| `spline-lad` | `lad-regression` | `"spline-lad"` |
| `spline-quantile` | `quantile-regression` | `"spline-quantile"` |
| `spline-logistic` | `logistic-regression` | `"spline-logistic"` |
| `spline-poisson` | `poisson-regression` | `"spline-poisson"` |

So all that "The fits" says of a kind is true of its spline: what is made
smallest, how it's found, its standard errors (with `:groups` and
`:lags`), its measures of fit. The knots depend only on `x` and
`max-knots`, never on `y` or on how the fit is made, so the five bend in
the same places.

A spline model's coefficients are of the expanded columns, not of the
predictors, so `model-coefficients`, `model-intercept`, and `model-slope`
refuse one; `model-report` shows them, each labeled with its column, and
`model-predict` and the rest work as on any model.

### Knots: max-knots

`max-knots` (3, unless given) says how *every* predictor is expanded:

| Form | Meaning |
|---|---|
| an integer, e.g. `3` | that many knots, placed at quantiles of the predictor's values -- for every predictor, if there's more than one |
| `'categorical` (a symbol) | 0/1 columns, one for each value but the first (the smallest, the baseline) -- for every predictor, if there's more than one |
| a flat list of numbers or dates, e.g. `(list 25 35)` | the knots, **exactly** -- only when there is exactly **one** predictor |
| a list with one entry for each predictor, e.g. `(list 3 0)` or `(list (list 25 35) 'categorical)` | each predictor's own: an integer, a list of knots, or `'categorical`. `0` leaves that predictor a straight line |

A predictor marked `'categorical` -- a home type, a loan purpose -- gets a
0/1 column for each of its values but the baseline, instead of hinges: the
model's prediction moves up or down by that value's coefficient. A knot
count above 0 on a predictor with 3 or fewer distinct values is an error
(naming the predictor, since hinges mean nothing there and can make the
fit fail), which suggests `0` or `'categorical`. At `model-predict` time, a
category that wasn't seen while fitting is an error, naming the
categories that were. (For a predictor with exactly two values, a 0/1
flag, `'categorical` and `0` give the same model; `'categorical` only adds
the checks.)

```lisp
(define home-type (vector 0 1 0 1 1))          ; 0=own, 1=rent
(define m (spline-regression (list income home-type) happiness
                              (list 2 'categorical)))
(display (model-report m))
(model-predict m (list 50000 0))                ; predict for "own", income=50000
```

### Smooth splines: :smooth

The hinges make a curve of straight pieces, with a corner at each knot,
and its last piece goes on as far as you predict. `:smooth #t` makes a
*restricted cubic spline* (a "natural" spline) instead: cubic pieces that
join smoothly at the knots, with no corners, and a straight line below
the first knot and above the last. That's often truer to the data -- a
prepayment curve bends; it doesn't turn corners -- and safer beyond it,
since a straight line goes on as it was going, where a cubic might turn
anywhere. In place of a hinge at each knot, a predictor gets one curved
term for each knot but the last two (`restricted_cubic_terms` in
`lisp_regression.py` has the formula). So it takes at least 3 knots, and
with `k` knots it has `k - 1` coefficients for the predictor, where the
hinges have `k + 1`: with the same knots, it bends less freely. Every
spline function takes `:smooth`, and a categorical predictor stays
categorical.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; an S
(define smooth (spline-regression x y (list -1 0 1 2) :smooth #t))
(table-column (model-coefficient-table smooth) "term")   ; => #("intercept" "x1" "x1 (curve at knot -1)" "x1 (curve at knot 0)")
```

### The spline functions

#### `(spline-regression x y [max-knots weights] [:smooth #t :groups g :lags l])`
A spline fit by least squares, as `linear-regression` fits.

#### `(spline-lad x y [max-knots weights] [:smooth #t :groups g :lags l])`
A spline fit by least absolute deviation, as `lad-regression` fits: the
curve can bend, and a few outliers barely move it.

```lisp
(define xs (vector-range 21))
(define ys (vector-map (lambda (x) (abs (- x 10))) xs))     ; a V, bending at 10
(vector-set! ys 18 40)                                      ; and one outlier
(format "{:.2f}" (model-predict (spline-regression xs ys (list 10)) 20))   ; => "17.02"
(format "{:.2f}" (model-predict (spline-lad xs ys (list 10)) 20))          ; => "10.00"
```
(The least-squares spline's right arm is pulled up toward the outlier;
the LAD spline goes through the V's other points exactly.)

#### `(spline-quantile x y quantile [max-knots weights] [:smooth #t :groups g :lags l])`
A spline fit to a quantile, as `quantile-regression` fits: two of them,
at the 10th and 90th percentiles, make a band that can bend with the data.
A percentile far from the middle needs many points in each of the
spline's pieces, or it is set by the single highest or lowest point of a
piece.

#### `(spline-logistic x y [max-knots weights] [:floor f :ceiling c :smooth #t :groups g :lags l])`
A spline with a logistic link, fit as `logistic-regression` fits, with the
same `:floor` and `:ceiling` and the same rules for `y`. The prediction
stays between 0 and 1 (or the floor and the ceiling), but thanks to the
hinges it doesn't have to rise (or fall) all the way across, as a plain
logistic curve does.

```lisp
(define x (- (/ (vector-range 41) 8.0) 2))
(define y (vector-map (lambda (v) (+ 0.03 (/ 0.45 (+ 1 (exp (* -3 (- v 1))))))) x))   ; 3% to 48%
(define s (spline-logistic x y 2 :floor 0.03 :ceiling 0.48))
(format "{:.3f}" (model-predict s 1))                          ; => "0.255"
```

#### `(spline-poisson x y [max-knots weights] [:smooth #t :groups g :lags l])`
A spline of a count, fit as `poisson-regression` fits: the logarithm of
the average count bends at the knots, and the average stays above 0.

### Choosing knots

#### `(suggest-knots x y window n)`
Proposes up to `n` knot locations, from where `y` actually bends as `x`
changes, rather than at quantiles of `x`:

1. Averages `y` at each *distinct* `x` value -- which matters for data
   where many rows share an `x`; `window` counts steps along this curve of
   distinct `x`s, not rows.
2. Estimates that curve's second derivative at every interior point (a
   3-point formula that works for unevenly spaced `x`, dates included).
3. Smooths those with a centered moving average of `window` points.
4. Picks the points with the largest smoothed `|second derivative|`,
   skipping any within `window` of one already picked, so that each knot
   is a different bend.

`window` must be a positive integer, and `n` 0 or more (0 gives `'()`).
It needs at least 3 distinct `x` values. The result is a list of up to `n`
x-values, sorted, ready for any spline function as its knots.

```lisp
(define knots (suggest-knots x y 5 3))
(define m (spline-regression x y knots))
```

A larger `window` smooths away small wiggles and finds only broader bends,
further apart; a smaller one finds sharp, narrow bends, but can put knots
close together. `x` and `y` needn't be sorted. Since `window` is in
distinct-`x` steps, size it by how many distinct `x` values there are, not
by the number of rows.

## Standard errors: how sure the coefficients are

A coefficient's **standard error** is how much it would vary if the model
were fit to another sample of the same kind of data. Its **t value** (or
**z value**) is the coefficient divided by its standard error: how many
standard errors it is from 0. Its **p value** is the chance of a t value
at least that far from 0 if the predictor in fact had no effect; under
0.05 is the usual sign that the predictor matters. `model-report` and
`model-coefficient-table` give all three for each coefficient.

How each kind finds them is in its section of "The fits"; in short:

| Kind | Standard errors | Test |
|---|---|---|
| least squares | the residual variance times the inverse of the normal equations' matrix | t, `n - p` degrees of freedom |
| least absolute deviation, a quantile | from how thinly the misses are spread at the quantile | t, `n - p` |
| logistic | from the information, for 0s and 1s; from the scatter of `y` about the fit, for shares | z |
| Poisson | from the information, times the square root of the dispersion | z |
| ridge, lasso | none | |
| nonlinear | least squares', for the straight line the formula is near the fit | t, `n - m` |

A spline's are its kind's. Each takes every row to be new information.
When the rows aren't, two options allow for it; they change the standard
errors, not the fit, and only one of the two can be given.

### Rows that come in groups: :groups

Often the rows aren't each new information. Twenty-four months of one
loan are 24 rows, but one borrower, one house, one set of habits: if the
loan pays faster than the model says one month, it probably does the next
month too. The fit is still fine, but the standard errors, which take
every row to be new information, come out too small -- the model looks
surer than it is. `:groups` gives each row's group: a vector or list with
a value for each row -- a number, a string, or a date, such as the loan's
ID -- and rows with the same value are a group. The standard errors then
allow for a group's rows being alike ("clustered" standard errors), by
taking each *group* to be new information, not each row. `model-report`
says how many groups there were.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; 40 loans, 24 months of each
(define (for-each-loan make)                                                  ; one value for each loan, on each of its rows
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))           ; 3% to 7%
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))          ; how much faster or slower it pays
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (slope-error m) (format "{:.3f}" (vector-ref (table-column (model-coefficient-table m) "std_error") 1)))
(slope-error (linear-regression coupon speed))                  ; => "0.056"
(slope-error (linear-regression coupon speed :groups loan))     ; => "0.221"
```

The slope's standard error is four times as large: there are 40 loans'
worth of information about coupons, not 960 rows' worth. They're found by
the "sandwich" formula (`clustered_covariance` in `lisp_regression.py`
explains it), with the small-sample corrections Stata uses: `G / (G - 1)`,
`G` being the number of groups, and for least squares also `(n - 1) / (n -
p)`. The t values then have `G - 1` degrees of freedom. The standard
errors need a good many groups. In simulations with 20 to 50 groups of 12
rows each, their 95% intervals held the true coefficient 90% to 95% of the
time, where the plain ones held it only 60% to 76% of the time. With fewer
groups they're less to be trusted. With every row its own group --
`:groups (vector-range n)` -- they're the "robust" standard errors, which
allow for the misses being larger for some rows than others.
`cross-validate` takes `:groups` too, to keep each group's rows together.

### Rows in time order: :lags

A time series -- a rate week by week, a pool's CPR month by month -- has
the same trouble in another form. When the model misses one week, it
usually misses the next week the same way: the misses run in streaks,
because whatever the model leaves out changes slowly. Then each week isn't
new information either, and the usual standard errors are too small,
often by several times. `:lags l` allows for it: the rows must be in time
order, one for each week (or month, or day), and rows up to `l` apart are
taken to be alike. The standard errors are Newey and West's ("HAC"): the
sandwich formula, as for groups, but adding in each row's pull on the
coefficients times its neighbors' pulls, up to `l` rows away, the further
away the less (`newey_west_covariance` in `lisp_regression.py`). They have
Stata's small-sample correction for least squares, `n / (n - p)`, and the
t values keep `n - p` degrees of freedom.

```lisp
(random-seed 2)
(define (wander scale)                          ; a series that drifts: each week is last week's, plus a step
  (vector-cumsum (* scale (random-normal-vector 200))))
(define ten-year (+ 4 (wander 0.05)))
(define left-out (wander 0.03))                 ; what the model leaves out, which drifts too
(define mortgage (+ 1.7 ten-year left-out))     ; the true slope is 1
(define (slope m) (format "{:.3f}" (model-slope m)))
(define (slope-error m) (format "{:.3f}" (vector-ref (table-column (model-coefficient-table m) "std_error") 1)))
(slope (linear-regression ten-year mortgage))                  ; => "1.134"
(slope-error (linear-regression ten-year mortgage))            ; => "0.011"
(slope-error (linear-regression ten-year mortgage :lags 12))   ; => "0.027"
(define (changes v) (vector-drop (vector-diff v 1) 1))         ; each week's change
(slope (linear-regression (changes ten-year) (changes mortgage)))         ; => "1.056"
(slope-error (linear-regression (changes ten-year) (changes mortgage)))   ; => "0.044"
```

The fit of the levels says 1.134, with a standard error of 0.011: twelve
standard errors from the truth, a slope it is far surer of than it should
be. With `:lags 12` the standard error is 0.027, more honest, but the fit
is still off by five of them. That is the other danger of series that
drift: a regression of one level on another can look strong, and wrong,
when the two have drifted together, or apart, by chance -- here, what the
model leaves out drifted up while the 10-year did. The regression of the
changes on the changes is the test of whether they move together, and it
says 1.056, give or take 0.044: right, and as sure as it should be.
(`examples/sofr_and_mortgage_rates.lsp` does both, on the real rates.)

How many lags? Enough to cover how long the streaks last. For changes
over overlapping periods -- 4-week changes, measured every week -- each
change shares weeks with the 3 after it, so `:lags 3` at the least. A rule
of thumb is about `4 * (n / 100)^(2/9)`, 6 for 200 rows, but for series
that drift as slowly as rates do, more is safer: too few lags leaves the
standard errors too small, while too many only makes them a little less
exact.

## Using a model

These work on a model of any kind.

#### `(model-report m)`
A text report of a fitted model: its equation, a table of its
coefficients, and its measures of fit. It uses the predictors' and `y`'s
names if they were given as `(name . vector)` pairs, and otherwise `x1`,
`x2`, ... and `y`.

The coefficient table has a row for the intercept and one for each
predictor (for a nonlinear model, one for each parameter):

| Column | Meaning |
|---|---|
| `coefficient` | the fitted value (`estimate`, for a parameter) |
| `std error` | its standard error: how much it would vary from sample to sample |
| `t value` / `z value` | the coefficient divided by its standard error |
| `p value` | the chance of a coefficient at least this far from 0 if the true value were 0 |

(Ridge and lasso have no standard errors: beside each coefficient is its
standardized one.) Then the measures of fit, each beside what a
**perfect** model would get, one that predicted every `y` exactly, and
what a model would get that **predicts the same for every row**, the
average of `y`, say, as a model with no predictors would; where the
model's value is, between those two, says how good it is. Then whatever
its kind adds, the number of steps a fit found by steps took, `n`, and the
groups or lags the standard errors allow for.

| Kind | Its measures | It adds |
|---|---|---|
| least squares, ridge, lasso, nonlinear | R-squared, RMSE, MAE | the penalty, for ridge and lasso |
| least absolute deviation | MAE, pseudo R-squared | |
| a quantile | average loss, pseudo R-squared | the quantile, and how many points are below, on, and above the fit |
| logistic | log-likelihood, pseudo R-squared, AUC (after R-squared, RMSE, MAE, for shares) | the floor and ceiling |
| Poisson | mean deviance, pseudo R-squared | the dispersion |

"How good is a model?" explains each measure.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(display (model-report m))
```
prints:
```
Linear model:  y = -0.7 + 10.3*x1
  term        coefficient     std error    t value    p value
  intercept          -0.7      0.834666    -0.8387      0.463
  x1                 10.3      0.251661      40.93   3.21e-05
  R-squared        = 0.998212   (perfect: 1; predicting the average of y for every row: 0)
  RMSE             = 0.616441   (perfect: 0; predicting the average of y for every row: 14.5794)
  MAE              = 0.48       (perfect: 0; predicting the median of y for every row: 12.4)
  n                = 5
```

A spline model's report first lists its predictors, each with its knots
(or its categories and baseline) -- flagging a predictor that is a
straight line with 3 or fewer distinct values as one that might be
`'categorical` -- then the coefficient table for the expanded columns,
each labeled with its predictor's name (`income (knot 40000)`, `home_type
= 1`), and its kind's measures.

#### `(model-coefficient-table m)`
The coefficient table from `model-report`, as a table (see "Tables", in
the [language manual](lisp_interpreter_reference.md#tables)), with the
columns `term`, `coefficient`, `std_error`, `t_value` (`z_value` for a
logistic or Poisson model), and `p_value`. The first row is the intercept
(a nonlinear model has none: its rows are its parameters). A ridge or
lasso model's has `term`, `coefficient`, and `standardized`. Its numbers
are kept at full precision, so it's the way to use them in further
calculations -- or `display-table` it to see them.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(table-column (model-coefficient-table m) "term")   ; => #("intercept" "x1")
```

#### `(model-predict m x)`
What the model says `y` is, for one row or for many.

- **One row:** `x` is a number (or a date, or a category) for a model of
  one predictor, or `(list x1 x2 ...)`, one value for each predictor in the
  order the model was fit with. The prediction is a number.
- **Many rows:** `x` is a vector for a model of one predictor, or a list of
  vectors, one for each predictor, just as the model was fit with. The
  predictions are a vector, one for each row. A `(name . vector)` pair, as
  `sqlite-query` gives a column, will do for a vector. A number in the
  list, among the vectors, is that predictor's value in every row: hold
  every predictor but one where it is, and see what the model says as that
  one changes.

The prediction is the fitted value; for a logistic model, the
probability, between 0 and 1 or between its floor and ceiling; for a
Poisson model, the average count (or rate). It is an error if `x` doesn't
have a value for each of the model's predictors, or the vectors aren't
all the same length.

```lisp
(define a #(1 2 3 4 5 6))
(define b #(2 1 4 3 6 5))
(define m (linear-regression (list a b) (+ 1 (* 2 a) (* 3 b))))   ; y = 1 + 2a + 3b
(model-predict m (list 10 10))                 ; => 51.0
(model-predict m (list #(10 20) #(10 0)))      ; => #(51.0 41.0)
(model-predict m (list #(10 20 30) 0))         ; => #(21.0 41.0 61.0)
(define line (linear-regression a (+ 1 (* 2 a))))
(model-predict line 10)                        ; => 21.0
(model-predict line #(10 20))                  ; => #(21.0 41.0)
```

A fitted curve for a chart is the model's predictions at many points:
`(list "fitted" grid (model-predict m grid) :line #t)`.

[`model_utils.lsp`](../lisp_interp/lib/model_utils.lsp)'s `(model->function m)` makes
the model an ordinary Lisp function, with an argument for each predictor:

```lisp
(load "model_utils.lsp")
(define f (model->function m))
(f 50000 30)                           ; same as (model-predict m (list 50000 30))
```

#### `(model-evaluate m x y)`
How well a model predicts data -- usually data held out from fitting -- as
a text report. `x` and `y` are as the fitting functions take them, with
as many predictors as the model has. For a model of a number (every kind
but logistic, and a logistic one with a floor or ceiling outside 0 and 1):
R-squared, RMSE, and MAE on this data. For a model of a probability
(logistic, with its floor and ceiling, if any, between 0 and 1): the
log-likelihood, McFadden's pseudo R-squared, and the AUC -- after
R-squared, RMSE, and MAE, if `y` is shares -- and, if `y` is all 0s and
1s, the accuracy: how often a prediction of 0.5 or more went with a 1,
and one under 0.5 with a 0. As in `model-report`, each is beside a perfect
model's and that of predicting the same for every row -- here, the average
(or median) of *this* data's `y`; for accuracy, the commoner of 0 and 1.
For a rare outcome, such as a monthly payoff, accuracy says little:
predicting "no payoff" for every row is usually 99% accurate, and the
report shows that beside it.

```lisp
(define age #(1 2 3 4 5 6 7 8 9 10))
(define paid #(0 0 1 0 0 1 0 1 1 1))
(display (model-evaluate (logistic-regression age paid) age paid))
```
prints:
```
Evaluation on 10 held-out observation(s):
  log-likelihood   = -4.94158   (perfect: 0; predicting the average of y for every row: -6.93147)
  pseudo R-squared = 0.287081   (perfect: 1; predicting the average of y for every row: 0)
  AUC              = 0.84       (perfect: 1; predicting the same for every row: 0.5)
  accuracy         = 0.8        (perfect: 1; predicting the commoner outcome for every row: 0.5; a prediction of 0.5 or more counts as a 1)
```
(Here it's evaluated on the data it was fit to, to keep the example short;
held-out data is the fair test.)

```lisp
(define n-train (floor (* (vector-length x) 0.7)))
(define m (linear-regression (vector-take x n-train) (vector-take y n-train)))
(display (model-evaluate m (vector-drop x n-train) (vector-drop y n-train)))
```

#### `(model-residuals m x y)`
The residuals, `y` minus the model's prediction, for each row of `x` and
`y`, as a vector. `x` and `y` are as for `model-evaluate`. After a
`lad-regression`, the rows with the largest residuals are the outliers the
fit set aside.

```lisp
(define m (linear-regression #(1 2 3) #(1 3 2)))
(model-residuals m #(1 2 3) #(1 3 2))          ; => #(-0.5 1.0 -0.5)
```

#### `(model-lift-table m x y [bins weights])`
How well a model **ranks** rows -- whether its highest predictions really
go with the highest outcomes, which is what matters when a model is used
to pick out the riskiest loans. The rows are sorted by prediction, highest
first, and split into `bins` groups of (nearly) the same number of rows --
10 by default, tenths. The result is a table with a row for each group:

| Column | Meaning |
|---|---|
| `bin` | 1 holds the highest predictions |
| `rows` | the number of rows in the group |
| `weight` | their total weight (the number of rows, if no weights are given) |
| `mean_predicted` | the group's average prediction |
| `mean_actual` | the group's average actual `y` |
| `lift` | `mean_actual` divided by the overall average `y` |
| `cumulative_share` | the share of all `y` (of all payoffs, say) in groups 1 through this one |

With `weights` (balances, say), the averages are weighted. `x` and `y` are
as for `model-evaluate`; use held-out data to judge a model fairly. Good
ranking shows as a `lift` well above 1 in the first bins, falling
steadily.

```lisp
(define age #(1 2 3 4 5 6 7 8 9 10))
(define paid #(0 0 1 0 0 1 0 1 1 1))
(define m (logistic-regression age paid))
(table-column (model-lift-table m age paid 5) "lift")   ; => #(2.0 1.0 1.0 1.0 0.0)
```

#### `(model-coefficients m)`, `(model-intercept m)`, `(model-slope m)`
The coefficients, as a vector, one for each predictor in the order they
were given; the intercept, a number; and, for a model of one predictor,
its one coefficient. They're for the models whose coefficients are of the
predictors themselves:

| | `model-coefficients` | `model-intercept` | `model-slope` |
|---|---|---|---|
| a straight line of any kind | the coefficients | the intercept | the coefficient, with one predictor (an error with more) |
| a spline | an error: its coefficients are of the expanded columns (see `model-report`) | an error | an error |
| nonlinear | the parameters, in order | an error: it has none | an error |

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(model-coefficients m)         ; => #(10.3)
(model-intercept m)            ; => -0.7
(model-slope m)                ; => 10.3
```

#### `(model-floor m)`, `(model-ceiling m)`
A logistic or spline-logistic model's floor and ceiling: 0 and 1, unless
they were given, or fit with `'fit`.

#### `(model-kind m)`
The model's kind, a string: `"linear"`, `"lad"`, `"quantile"`,
`"logistic"`, `"poisson"`, `"ridge"`, `"lasso"`, `"nonlinear"`,
`"spline"`, `"spline-lad"`, `"spline-quantile"`, `"spline-logistic"`, or
`"spline-poisson"`.

```lisp
(model-kind (linear-regression #(1 2 3) #(2 4 7)))     ; => "linear"
```

#### `(model? x)`
`#t` for a fitted model, of any kind.

```lisp
(model? (linear-regression #(1 2 3) #(2 4 7)))         ; => #t
(model? 5)                                             ; => #f
```

**Saving a model.** `save-variables` saves a model of any kind but
nonlinear, and `load-variables` makes it again (see "Saving variables", in
the [language manual](lisp_interpreter_reference.md#saving-variables)).

## How good is a model? The measures, explained

Every measure of a model compares its predictions with what actually
happened. A number by itself says little: is an RMSE of 0.046 good? So
`model-report` and `model-evaluate` put two others beside each:

- **perfect**: what a model would get that predicted every row exactly.
- **predicting the same for every row**: what a model would get that
  knows nothing about the predictors and predicts one number for every
  row -- the average of `y`, say (or whichever one number does best on
  that measure).

A model is worth something to the extent that it's closer to perfect than
to predicting the same for every row. Here is the report of a
`spline-logistic` model of the monthly CPRs of 600 pools
(`examples/synthetic_mbs_pools.csv`; the predictors are the rate
incentive, the loan age, and whether the loans were refinancings):

```
  R-squared        = 0.811845   (perfect: 1; predicting the average of y for every row: 0)
  RMSE             = 0.0461904  (perfect: 0; predicting the average of y for every row: 0.106486)
  MAE              = 0.0287087  (perfect: 0; predicting the median of y for every row: 0.078044)
  log-likelihood   = -13302.8   (perfect: -13116; predicting the average of y for every row: -14355.8)
  pseudo R-squared = 0.0733469  (perfect: 0.0863629; predicting the average of y for every row: 0)
  AUC              = 0.693018   (perfect: 0.706028; predicting the same for every row: 0.5)
```

The pseudo R-squared of 0.073 looks dreadful next to the R-squared of 0.81.
But a perfect model would get only 0.086, so this one gets 85% of the
way there. Without the "perfect" beside it, it would be easy to throw out
a good model.

In what follows, a **residual** (or error, or miss) is one row's actual
`y` minus the model's prediction for it: positive when the model
predicted too little.

**Measures of a number** -- a price, a CPR, a spread:

- **RMSE**, the root mean squared error: the typical size of a miss, in
  `y`'s own units. Square each residual, average them, and take the
  square root. An RMSE of 0.046 for CPRs means the predictions are
  typically about 4.6 percentage points off. Squaring makes big misses
  count far more than small ones: one miss of 10 counts as much as a
  hundred misses of 1. Predicting the average for every row gives the
  standard deviation of `y`.
- **MAE**, the mean absolute error: the average size of a miss, ignoring
  whether it was too high or too low. Big misses count only by their
  size. If the RMSE is much larger than the MAE, a few rows are missed
  by a lot. Predicting the median of `y` for every row does best on MAE,
  so that's the comparison.
- **R-squared**: the share of the variation in `y` the model accounts
  for. It's 1 − (the RMSE / the RMSE of predicting the average)²: 0.81
  means the model's squared misses are 19% of what they'd be predicting
  the average for every row. 1 is perfect; 0 is no better than the
  average. On data the model wasn't fit to, it can be below 0: worse
  than the average.
- **pseudo R-squared, for LAD and quantile models**: the same idea, with
  what that model makes smallest -- the MAE for LAD, the average loss for
  a quantile model -- in place of squared misses.
- **average loss, for a quantile model**: a quantile fit is meant to
  have some of the points above it -- 10% for the 0.9 quantile -- so a
  miss above isn't simply bad. A point above the fit costs `quantile`
  times its distance, and one below it `1 − quantile` times its distance;
  this is the average cost. Predicting the quantile of `y` for every row
  is the comparison.

**Measures of a count** (a Poisson model):

- **mean deviance**: how far the counts are from the averages the model
  gives them, as the Poisson likelihood measures it: for each row, `2 *
  (y log(y / average) − (y − average))`, averaged over the rows (each
  counting by its weight). It's 0 when every count is its average, and
  it's what a Poisson fit makes smallest. A count of 10 where the model
  said 5 costs about 3.9; a count of 0 where it said 5 costs 10.
  Predicting the average count for every row is the comparison.
- **pseudo R-squared, for a Poisson model**: 1 − the mean deviance / that
  of predicting the average for every row: the share of the deviance the
  model accounts for.

**Measures of a probability** -- the chance a loan prepays, or the share
of a pool that does:

- **log-likelihood**: how likely the model found what actually happened.
  For each row it takes the log of the chance the model gave the
  outcome: for a loan that prepaid, log(p); for one that didn't, log(1 −
  p). Then it adds them up. A model that said 2% for a loan that then
  prepaid loses log(0.02) = −3.9 on that row; one that said 50% loses
  only −0.7. It's always 0 or less, and closer to 0 is better. The sum
  grows with the number of rows, so it means little by itself; compare
  it with the two beside it. For shares, a row with share `y` counts as
  `y` of a prepayment and `1 − y` of none.
- **log-loss** (in `cross-validate`): minus the log-likelihood divided by
  the number of rows -- the same, per row, so it can be compared across
  data of different sizes. Lower is better.
- **pseudo R-squared** (McFadden's): how far the log-likelihood has come
  from predicting the average chance for every row toward perfect, as R-
  squared does for squared misses. For 0s and 1s, perfect is 1. Even
  good models of rare events score low on it -- 0.2 to 0.4 is considered
  very good -- because no model can say which loans will prepay this
  month, only which are likelier to.
- **AUC** (the area under the ROC curve): how well the model *ranks*
  rows. Pick, at random, one loan that prepaid and one that didn't: the
  AUC is the chance the model gave the one that prepaid the higher
  chance. 0.5 is a coin toss, and is what predicting the same for every
  row gets; 1 is perfect ranking. It says nothing about whether the
  chances are the right *size*: doubling every prediction leaves it the
  same. For shares, each row is that share of a prepayment and the rest
  of none, so even perfect is short of 1.
- **accuracy** (in `model-evaluate`, for 0s and 1s): how often a
  prediction of 0.5 or more went with a 1, and one under 0.5 with a 0.
  For something rare, it's nearly useless: if 1% of loans prepay, a
  model that says "no" for every loan is 99% accurate, and knows
  nothing. The report puts that beside it ("predicting the commoner
  outcome for every row").

**Why perfect is short of 1 for shares.** A 0 or a 1 is an outcome a model
can be sure of: say 100% for a loan that prepays, and the row loses
nothing. A share of 0.1 isn't: even predicting exactly 0.1, the model
gives a 90% chance to "not prepaid" for that part of the pool, and the
log-likelihood can't reach 0. So with shares, judge the log-likelihood,
pseudo R-squared, and AUC against the perfect ones beside them, and look
at R-squared, RMSE, and MAE, which mean the same for shares as for any
number.

**The lift table** (`model-lift-table`) shows two things at once. It sorts
the rows by their prediction, highest first, and splits them into tenths.
For each tenth, compare `mean_predicted` with `mean_actual`: if they're
close all the way down, the predictions are the right size (the model is
"calibrated"). And `lift` -- each tenth's actual average divided by the
overall average -- should fall steadily from the top: the model puts the
rows that really prepay faster at the top. For the pool model above:

| bin | mean_predicted | mean_actual | lift |
|---|---|---|---|
| 1 | 0.343 | 0.340 | 2.10 |
| 2 | 0.287 | 0.300 | 1.86 |
| 5 | 0.137 | 0.123 | 0.76 |
| 10 | 0.046 | 0.057 | 0.35 |

The highest tenth prepaid at 2.1 times the average, the lowest at a third
of it, and each tenth's prediction is within a couple of percentage points
of what happened.

**Fit to its own data, or new data?** Every measure in `model-report` is
of the data the model was fit to, which flatters it: a model that bends
to every point looks perfect there, and predicts new data badly. The
honest numbers are from data the model hasn't seen: `model-evaluate` on
rows held out, or `cross-validate`, which does that for every row. When
choosing between models, compare those.

## Predicting data a model wasn't fit to

#### `(cross-validate fit x y [:folds 5 :seed 1 :groups g])`, `(cross-validate fit x y :times t [:last 1])`
How well the models `fit` makes predict data they *weren't* fit to. `fit`
is a procedure of `x` and `y` that returns a model -- `(lambda (x y)
(spline-lad x y 3))`, say, or a model of any other kind. The rows are
shuffled (by `:seed`, so it comes out the same every time) and dealt into
`:folds` groups; for each group, a model is fit to all the other rows and
predicts this group's `y`. The result is a table with a row for each fold
and a last row, `"all"`, for every row, each predicted by the model fit
without it. With `:groups`, each group's rows stay together, in one fold;
with `:times`, the model is fit to the earlier rows and predicts the
latest ones (both below).

| Column | What it holds |
|---|---|
| `fold` | `"1"`, `"2"`, ..., and `"all"` -- or, with `:times`, `time`: each of the latest times, and `"all"` |
| `rows` | how many rows were predicted |
| `groups` | with `:groups`, how many groups they're in |
| `rmse` | the root mean squared error |
| `mae` | the mean absolute error |
| `log-loss` | for a model of a probability: the mean of −(y log p + (1 − y) log(1 − p)), how unlikely it found what happened |
| `quantile-loss` | for a quantile model: the mean of the loss it makes smallest, at its quantile |

The lower, the better it predicts. That's the fair way to choose among
models, or numbers of knots: a model always fits the data it was fit to
better the more freely it can bend -- more knots, more predictors -- but
past some point it bends to the noise, and predicts new data worse.
Measured on its own data, that never shows; measured this way, it does.
(Ridge and lasso choose among penalties this way themselves, given a list
of them.) `x` and `y` can be in any shape the fitting functions take,
names and all.

```lisp
(random-seed 2)
(define x (vector-range 60))
(define y (+ (/ x 2) (list->vector (map (lambda (i) (* 20 (- (random-float) 0.5))) (iota 60)))))   ; a line, and noise
(define (overall measure table) (vector-ref (table-column table measure) (- (table-row-count table) 1)))
(define line (cross-validate (lambda (x y) (linear-regression x y)) x y))
(define wiggly (cross-validate (lambda (x y) (spline-regression x y 12)) x y))
(list (format "{:.2f}" (overall "rmse" line)) (format "{:.2f}" (overall "rmse" wiggly)))   ; => ("5.84" "6.41")
```
(The 12-knot spline fits these 60 points more closely than the line does,
but predicts the ones it hasn't seen less well: the data is a line, and
noise.)

**Rows in groups.** When the rows come in groups whose rows are alike --
the months of a loan -- dealing them out one by one isn't a fair test.
Each loan's other months are among the rows the model is fit to, so it is
predicting more months of loans it has seen, which is easier than
predicting new loans. A model that can bend to fit each loan -- many knots
-- looks better than it is. With `:groups` -- a value for each row, a
loan's ID, say, as the fitting functions take it (see "Rows that come in
groups") -- the groups are shuffled and dealt out instead of the rows:
each, in turn, to the fold with the fewest rows so far. A group's rows are
all in one fold, so the folds come out about the same size, but not
exactly. (Without `:groups`, every row is its own group, which deals the
rows out one by one.) Don't give `:groups` to the fitting procedure: it
gets only some of the rows, and the groups change the standard errors,
not the predictions.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; 40 loans, 24 months of each
(define (for-each-loan make)                                                  ; one value for each loan, on each of its rows
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))           ; 3% to 7%
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))          ; how much faster or slower it pays
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (overall table) (format "{:.2f}" (vector-ref (table-column table "rmse") (- (table-row-count table) 1))))
(define (line x y) (linear-regression x y))
(define (wiggly x y) (spline-regression x y 20))
(list (overall (cross-validate line coupon speed)) (overall (cross-validate wiggly coupon speed)))   ; => ("2.08" "1.73")
(list (overall (cross-validate line coupon speed :groups loan))
      (overall (cross-validate wiggly coupon speed :groups loan)))                                  ; => ("2.13" "3.59")
(table-column (cross-validate line coupon speed :groups loan :folds 3) "rows")                     ; => #(336 312 312 960)
```

A loan's speed here is twice its coupon, plus the loan's own habit, plus
noise; there are 40 coupons, one for each loan. Dealt out row by row, a
spline with 20 knots predicts better than the line: with knots between
the coupons, it learns each loan's habit from the loan's other months.
With each loan's months kept together, it predicts new loans far worse.

**The latest times.** `:times` gives each row's time -- a month, as a
number such as `202506` or `18`, a string such as `"2025-06"`, or a date
-- and the model is fit once, to every row before the latest `:last` times
(1, unless given), and predicts the rows of those times: the test of a
model that will be used on the months to come. The table has a row for
each of the latest times, in a `time` column in place of `fold`, and
`"all"`. Folds mix all the months, so they can't show a model that
predicts the months it was fit among well but the next ones badly,
because rates, the economy, or lenders' rules have changed; this can.
`:folds`, `:seed`, and `:groups` don't go with `:times`.

```lisp
(random-seed 4)
(define loan (vector-map (lambda (i) (floor (/ i 24))) (vector-range 960)))    ; as above
(define (for-each-loan make)
  (let ((value (list->vector (map (lambda (i) (make)) (iota 40)))))
    (vector-map (lambda (l) (vector-ref value l)) loan)))
(define coupon (for-each-loan (lambda () (+ 3 (* 4 (random-float))))))
(define habit (for-each-loan (lambda () (* 6 (- (random-float) 0.5)))))
(define speed (+ (* 2 coupon) habit (vector-map (lambda (l) (* 4 (- (random-float) 0.5))) loan)))
(define (overall table) (format "{:.2f}" (vector-ref (table-column table "rmse") (- (table-row-count table) 1))))
(define (line x y) (linear-regression x y))
(define month (vector-map (lambda (i) (+ 1 (mod i 24))) (vector-range 960)))      ; months 1 to 24, for each loan
(define faster (+ speed (vector-map (lambda (m) (if (> m 21) 3 0)) month)))     ; in the last 3, every loan pays faster
(overall (cross-validate line coupon faster :groups loan))                      ; => "2.36"
(define latest (cross-validate line coupon faster :times month :last 3))
(table-column latest "time")                                                   ; => #("22" "23" "24" "all")
(overall latest)                                                               ; => "3.62"
```

## Where to see them, and the code

- `examples/regression_kinds_example.lsp`: the kinds on the same made-up
  prepayment data, charted, with a floor and ceiling, a shaded quantile
  band, a smooth spline, and a table of how well each fits and predicts.
- `examples/prepayment_demo.lsp`: a whole modeling session on
  `synthetic_mbs_pools.csv` -- suggest knots, split the data, fit a
  `spline-logistic`, report it, evaluate it on the rows held out, chart it.
- `examples/sofr_and_mortgage_rates.lsp`: regressions of time series, the
  mortgage rate on SOFR and on the 10-year, levels and changes, with
  `:lags`.
- "Models fitted to Freddie Mac's loans", in the
  [library manual](lisp_library_reference.md#models-fitted-to-freddie-macs-loans):
  prepayment, default, and loss models fitted to millions of loan-months.
- `plot-chart`'s `:fit` draws a straight line fitted to a series, by least
  squares, least absolute deviation, or a logistic curve (see "Charting", in
  the [language manual](lisp_interpreter_reference.md#charting)).

The code is `lisp_interp/lisp_regression.py`: `fit_linear`, `fit_lad` and
`fit_quantile`, `fit_logistic`, `fit_poisson`, `fit_penalized`, and
`fit_nonlinear` are the fits; `clustered_covariance` and
`newey_west_covariance` the standard errors for groups and lags;
`_spline_expand_columns` the splines' columns; `measures_of_fit` the
measures; and `cross_validate` the folds. Its tests are in
`lisp_interp/tests/test_models.py`.
