# morris-lisp — Yield Curves and Simulated Paths

Questions about mortgages, bonds, options and investments are questions about what prices and
rates might do: not one forecast, but thousands of possible futures, each a **path**, day by
day or month by month. This manual is about making those paths, in two ways:

- **Paths of interest rates** start from today's **yield curve**, which says what the market
  expects rates to be, and spread out around it as much as **option prices** say rates are
  expected to move. They are made by a two-factor model of rates (`simulate-rate-paths`), and
  are what bonds, mortgages and structured deals are priced on.
- **Paths of an investment's price** are made from the investment's own **history**: pieces of
  its past, copied end to end (`bootstrap-path`), and, if you want, started at the market's
  volatility today (`volatility-model`).

Part 1 is what you do, from the very beginning, to make a set of paths of rates. Part 2 is what
the program does when you do it: where the forward rates come from, and how the volatility that
option prices imply becomes paths. Part 3 uses the paths, to price a bond, find its
option-adjusted spread and duration, and look at mortgage rates and callable bonds. Part 4 is
the paths made from history. Part 5 is the reference: every function, with what it takes and
gives.

The functions are built in, or in libraries that load themselves when first used: nothing here
needs a `load`. The numbers in the examples are from 2026-10-30 unless they say otherwise.

The other manuals: the language is in [lisp_interpreter_reference.md](lisp_interpreter_reference.md),
the rest of the library in [lisp_library_reference.md](lisp_library_reference.md), and structured
deals, which are priced on these paths, in [lisp_cmo_manual.md](lisp_cmo_manual.md).

## Contents

- [Part 1. Paths of interest rates, from the beginning](#part-1-paths-of-interest-rates-from-the-beginning)
  - [What you need](#what-you-need)
  - [Step 1. Today's curve](#step-1-todays-curve)
  - [Step 2. The model's three numbers](#step-2-the-models-three-numbers)
  - [Step 3. The paths](#step-3-the-paths)
  - [Step 4. Using them](#step-4-using-them)
  - [The whole program](#the-whole-program)
- [Part 2. What the program does](#part-2-what-the-program-does)
  - [Where the forward rates come from](#where-the-forward-rates-come-from)
  - [How a path is made](#how-a-path-is-made)
  - [How implied volatility sets the numbers](#how-implied-volatility-sets-the-numbers)
  - [How the paths compare with history](#how-the-paths-compare-with-history)
- [Part 3. Using the paths](#part-3-using-the-paths)
  - [How many paths](#how-many-paths)
  - [Pricing on the paths: a bond, its OAS and its duration](#pricing-on-the-paths-a-bond-its-oas-and-its-duration)
  - [Mortgage rates and callable bonds](#mortgage-rates-and-callable-bonds)
- [Part 4. Paths from history: investment prices](#part-4-paths-from-history-investment-prices)
  - [Simulating investment prices](#simulating-investment-prices)
  - [Starting paths from today's volatility](#starting-paths-from-todays-volatility)
- [Part 5. Reference](#part-5-reference)
  - [Yield curves](#yield-curves)
  - [Paths of rates](#paths-of-rates)
  - [Fitting to option prices](#fitting-to-option-prices)

## Part 1. Paths of interest rates, from the beginning

### What you need

- **Nothing, for paths with volatilities you choose.** The Treasury's yield curve is a free
  download, with no key.
- **A tastytrade account, to fit the volatilities to option prices.** The options on SOFR futures
  and on the 10-year Treasury note future come from tastytrade (see "tastytrade" in the library
  manual for the one-time setup). Reading prices is all it does.
- **A FRED key, for mortgage rates** (`"fred_api_key"` in the credentials file; see "FRED" in the
  library manual).

### Step 1. Today's curve

A path of rates starts on a **forward curve**: the rate for each month of the next thirty years,
as the market prices it today. The Treasury's is the one to use. Three calls make it:

```lisp
(define par (treasury-par-curve))                      ; the Treasury's par yields, a row a day, this year
(define zeros (treasury-zero-curve par))               ; the latest day, as zero rates
(define curve (curve-forward-rates zeros))             ; 360 months of forward rates: the forward curve
```

`curve` is a table with a row for each month: `months` (1 to 360), `discount` (what a dollar paid
at the end of that month is worth today), and `forward` (that month's rate). Check it against what
the Treasury published: `(curve-par-yield curve 10)` is the 10-year par yield the curve gives,
4.98%, which is what the Treasury published for that day.

For another day, give `treasury-zero-curve` a `:date`, and `treasury-par-curve` a `:start-date` that
reaches it. "Which curve to use" (Part 5) has the Fed's smoother curve, and the SOFR curve.

### Step 2. The model's three numbers

The model has three numbers that say how rates move:

- `a`, how fast the short rate follows the long-run level: a gap between them closes in about
  1/`a` years (a year for 1, four months for 2.75);
- `sigma1`, how hard the short rate is shocked, as a rate a year (0.031 is 3.1 points);
- `sigma2`, how hard the long-run level is shocked: the long end of the curve, the 10-year yield,
  and so mortgage rates follow it.

Either choose them, or **fit them to option prices**, which say how much the market expects rates
to move. Fitting takes the prices of two kinds of option from tastytrade:

```lisp
(define sofr-data (sofr-calibration-data creds 40 8 3))           ; SOFR futures and options on them
(define chain (tastytrade-option-chain creds "ZN" 12 12))         ; options on the 10-year note future
(define note-rows (note-option-rows chain :min-days 20 :max-days 120))
(define fit (calibrate-rate-model curve (cdr sofr-data) note-rows :fit '(sigma1 sigma2) :a 2.75))
(define (fitted name) (cdr (assoc name fit)))
(list (fitted 'sigma1) (fitted 'sigma2) (fitted 'sofr-error) (fitted 'note-error))
; (0.031 0.0117 0.090 0.028): the model's volatilities are 9% from the SOFR options' and 3% from the notes'
```

That takes about half a minute. `a` is held at 2.75 here, because the options don't tell `a` and
`sigma1` apart well (see "How implied volatility sets the numbers", in Part 2); leave out `:fit` and
`:a` to fit all three.

### Step 3. The paths

```lisp
(define paths (simulate-rate-paths curve (fitted 'sigma1) (fitted 'sigma2) 5 2000 :a (fitted 'a) :seed 1))
(define years (first paths))               ; 0, 1/12, ... 5: sixty-one months
(define short-rates (second paths))        ; a list of 2000 vectors, one per path: the short rate each month
(define ten-year-yields (third paths))     ; the same, for the 10-year par yield
(vector-ref (list-ref ten-year-yields 7) 24)     ; path 7 (the eighth), two years from now
```

Each path is a vector with a value for each month: element 0 is today, element 24 two years from
now. All the paths start where the market is (the first 10-year yield is the Treasury's), and then
spread out. `:seed` makes the same paths each time; leave it out for new ones. Chart some:

```lisp
(plot-chart (loop for path in ten-year-yields for number from 1 to 8 collect (list "path" years path))
            :legend #f :title "Eight paths of the 10-year yield" :y-format "{:.1%}")
```

### Step 4. Using them

A path is one possible future. Look at how widely they spread:

```lisp
(define yields-in-5-years (list->vector (map (lambda (path) (vector-ref path 60)) ten-year-yields)))
(vector-quantile yields-in-5-years (vector 0.1 0.5 0.9))       ; the 10-year yield in five years
```

or price something on them: Part 3 prices a bond, finds its option-adjusted spread and duration,
and makes mortgage rates and callable bonds. Structured deals are priced on these paths too (see
"Option-adjusted spread and effective duration" in [lisp_cmo_manual.md](lisp_cmo_manual.md)).

### The whole program

`examples/rate_model_example.lsp` is steps 1 to 3 in one program: the curve, the fit to both kinds
of option, and 200 paths, charted. `examples/rate_paths_example.lsp` takes the paths apart, a stage
at a time, with volatilities chosen. Run them from `examples/`:

```bash
python3 ../lisp_interpreter.py rate_paths_example.lsp
```

## Part 2. What the program does

### Where the forward rates come from

**The words.** A bond that pays a coupon every six months is a *par* bond if it is worth its face
value: its coupon is then its *par yield*, which is what the Treasury publishes. What a dollar paid
`t` years from now is worth today is the *discount factor* `D(t)`. The rate it earns,
`D(t) = exp(-z t)`, is the *zero rate* `z` (continuously compounded here, as the Fed's are). The
rate for a period between two dates, agreed now, is a *forward rate*: money kept from `t1` to `t2`
grows by `D(t1) / D(t2)`. A zero rate is an average of the forward rates before it. The numbers are
decimals everywhere: 0.043 is 4.3% (the Treasury and the Fed publish percents).

Here is what the three calls of Step 1 do.

**1. `treasury-par-curve` downloads the Treasury's file.** The Treasury publishes a CSV file for
each year (`https://home.treasury.gov/resource-center/data-chart-center/interest-rates/...`), with a
row for each business day and a column for each maturity it publishes: 1, 1.5, 2, 3, 4 and 6 months,
and 1, 2, 3, 5, 7, 10, 20 and 30 years. Each year is a download, kept for 12 hours. The yields are
divided by 100, and a maturity the Treasury didn't publish that year (the 20-year in the early 1990s,
the 30-year in 2003, the newer short ones) is `nan`.

**2. `treasury-zero-curve` turns a day's par yields into discount factors, by bootstrapping**
(`par-curve-zeros` does the work). A par yield is not a zero rate, but a series of them gives the
zero rates, one step of six months at a time:

- A bill of less than six months pays only at its end, and its yield is quoted simply, so
  `D(t) = 1 / (1 + yield × t)`.
- From six months on, the program makes a step every six months, to 30 years: 60 steps. The par
  yield at a step the Treasury doesn't publish (4 years, say) is read from a smooth curve through
  the ones it does: a *monotone cubic*, which bends smoothly but never rises above or falls below
  the points it joins (`interpolate` with `:smooth #t`). With straight lines between them, the
  forward rates that come out would jump where two lines meet. Past the last maturity it is flat.
- A par bond of `n` steps, with a coupon `c` (half the par yield) at each step and the face at the
  end, is worth exactly 1:

  ```text
  1 = c D(1) + c D(2) + ... + c D(n-1) + (1 + c) D(n)
  ```

  Every discount factor before step `n` is known already, from the steps before, so the one at
  step `n` is what is left:

  ```text
  D(n) = (1 - c × (D(1) + ... + D(n-1))) / (1 + c)
  ```

- The zero rate of each step is `-ln(D) / t`.

The result is the zero curve: a table of `years`, `par`, `discount` and `zero`.

**3. `curve-forward-rates` makes a forward rate for each month.** The zero rate of each month,
`m / 12` years, is read from a smooth curve (again the monotone cubic) through the zero curve's
points, and gives that month's discount factor, `D(m) = exp(-z × m / 12)`. A month's forward rate
is the rate that grows `D(m)` back to `D(m - 1)`, with monthly interest:

```text
1 + f(m) / 12 = D(m - 1) / D(m),   so   f(m) = 12 × (D(m - 1) / D(m) - 1)
```

That is the forward curve: 360 forward rates, and the discount factors they come from.

**The Fed's curve** (`gsw-curve`, `gsw-zero-curve`) skips the bootstrapping. The Fed's staff fit
six numbers each day, the parameters of a *Svensson curve*, to the prices of all the Treasuries,
and publish them. The zero rate at any maturity is a formula of them:

```text
z(t) = beta0 + beta1 s(t/tau1) + beta2 (s(t/tau1) - e^(-t/tau1)) + beta3 (s(t/tau2) - e^(-t/tau2)),   s(x) = (1 - e^-x) / x
```

`gsw-zero-curve` evaluates it at every month, and `curve-forward-rates` turns that into forward
rates as above. Because one smooth formula is fitted to every Treasury, its forward rates are
smooth; the Treasury's publishes only three maturities past 7 years, and a wiggle among them (a
20-year yield above the 30-year) is a swing in the forward rates. `examples/yield_curve_example.lsp`
charts both.

**SOFR futures** (`sofr-forward-curve`) give a forward curve directly. A 3-month SOFR future
settles to 100 less the average of SOFR over its quarter, so its price says what the market expects
that average to be: a price of 96.25 is a rate of 3.75%. The program takes that rate as the forward
rate of each month of the quarter; a month before the first quarter gets the first's rate, a gap
between quarters the earlier one's, and every month after the last quarter (about five years out)
the last one's. The simplifications: a quarter's rate is one flat rate, and there is no convexity
adjustment (a future's rate is a little above the true forward rate, by a few basis points within
two years). `extend-forward-curve` carries a SOFR curve on past the futures with the Treasury's:
SOFR's for the first months, then a straight-line change over a year to the Treasury's.

### How a path is made

A path is **today's curve, bent by two random numbers**. The two numbers, called the model's
*factors*, are how far the short rate (`delta-r`) and the long-run level (`delta-theta`, which
is the long end of the curve) have strayed from where today's curve has them. Both start at 0,
and each day each is shocked at random, by an amount that grows with `sigma1` and `sigma2`;
each is also pulled back, `delta-r` toward `delta-theta` at speed `a`, and `delta-theta` toward 0
slowly (at speed `b`, 0.15). On a given date on a given path, the factors bend today's
curve like this, at tau years after that date:

> forward rate = (today's rate for that date) + `delta-theta` × (1 − e<sup>−a·tau</sup>) + `delta-r` × e<sup>−a·tau</sup>

so the short end of the curve follows `delta-r`, the long end follows `delta-theta`, and `a` sets how
quickly the one gives way to the other. What a path reports each month is read from that
bent curve: the **short rate** is its first month, and the **10-year yield** is the par
yield of a 10-year note on it. Nothing else is random.

Each stage has a function that shows it:

| To see | Use |
|---|---|
| today's curve, as yields | `(curve-par-yield curve 10)`, for any tenor; `curve-forward-rates` for the whole curve, as a table |
| what today's curve implies for later | `(curve-par-yield curve 10 :start-months 24)`: the 10-year yield two years from now |
| a path with no randomness | `(simulate-rate-paths curve 0 0 5 1)`: **the curve itself, read forward in time** |
| the factors | `(simulate-rate-factors sigma1 sigma2 5 200 :a a :seed 1)` |
| the curve on a date, bent | `(rate-curve-on-date curve 36 delta-r delta-theta :a a)`: a table of today's curve for the dates after that, and the model's |
| what is read from it | the paths: `(simulate-rate-paths ...)` |

**With no volatility (`sigma1` and `sigma2` both 0) every path is the forward curve**,
read forward in time. The short rate in month 24 is the curve's forward rate for month 24, and the
10-year yield is the par yield of a 10-year note that starts then, on today's curve: the same as
`(curve-par-yield curve 10 :start-months 24)`. The paths with volatility wander around that
line (the black line in the chart of `rate_paths_example.lsp`). It is what today's curve expects rates
to do, and not a forecast.

For example (the Treasury's curve of 2026-10-15; `examples/rate_paths_example.lsp` prints these). On one path,
three years from now, the short rate had strayed 2.4 points above the curve's and the level 2.1 points. The curve
for the months from then on, which today says starts at 4.95% and reaches 6.10% at ten years, has become one that starts
at 7.33% and reaches 8.24%; and its 10-year par yield is 7.58%, where the curve with no volatility has 5.39%.

```lisp
(define on-date (rate-curve-on-date curve 36 0.0240 0.0212 :a 2.75))
(table-column on-date "model")              ; the bent curve, a month at a time
```

Two checks that the paths are consistent with the curve they start on. The first path value is
the curve's own (the 10-year yield at the start is exactly the Treasury's). And a security's price from the
paths (the paths' average discount factor) is close to its price from the curve: for a payment in 5 years,
on 2026-10-15, it was 3 basis points of yield away (4.84% against the curve's 4.87%). The remainder is the
*convexity* of the model, which it does not correct for.

**What the model leaves out**, which a path can show:
- Rates move in a bell curve of the same size at every level, so a path can go below 0
  or somewhere far: of 200 paths of 5 years, with the numbers above, one ended with a 10-year yield of 1.0% and another
  10.4%, and one came within 0.1% of 0 on the way.
- The two shocks are independent, so the short and long ends move together only because
  `delta-r` follows `delta-theta`. A correlation between them is not in the model.
- The volatilities are constants. The model's `sigma2` fits the options of one month to four, and a model
  with one volatility cannot match the smile (the market's volatility is higher for options far from the
  money).
- A curve shorter than the horizon plus the tenor (a 30-year mortgage's last month needs a curve to year 40)
  continues flat at its last forward rate.

**The arithmetic, exactly.** Here is what `simulate-rate-paths` computes, in the order it does it
(the code is `term_structure/term_structure_model.py`).

1. **The factors, a day at a time.** Both start at 0. Each day (`dt` = 1/365 of a year), with two
   independent random numbers `z1` and `z2` from a standard normal distribution:

   ```text
   delta-r     += a × (delta-theta - delta-r) × dt  +  sigma1 × sqrt(dt) × z1
   delta-theta += -b × delta-theta × dt             +  sigma2 × sqrt(dt) × z2
   ```

   `b` is 0.15: the long-run level drifts back toward today's curve over about seven years.
   Half the paths use `-z1` and `-z2` where the other half use `z1` and `z2`: the paths come in
   mirror-image pairs, so the factors average exactly 0, and the paths' average is close to the
   curve. A month is the day `round(m × 365 / 12)`.

2. **The curve on that day, bent.** At `T` years from now, on one path, the forward rate for a date
   `tau` years after `T` is today's forward rate for that date, plus the bend:

   ```text
   f(T, T + tau) = f_today(T + tau) + delta-theta × (1 - e^(-a tau)) + delta-r × e^(-a tau)
   ```

   The discount factors of that curve have a closed form, which is what the program uses:

   ```text
   D(T, T + tau) = D_today(T + tau) / D_today(T) × exp(-delta-theta × A(tau) - delta-r × B(tau))
   B(tau) = (1 - e^(-a tau)) / a,     A(tau) = tau - B(tau)
   ```

   `D_today` comes from the forward curve, the product of `1 / (1 + f / 12)` over the months, with
   its logarithm on a straight line within a month. A curve too short for `T + tau` continues at
   its last forward rate.

3. **What the path reports.** The **short rate** that month is the one-month rate of the bent curve:
   `12 × (1 / D(T, T + 1/12) - 1)`. The **10-year yield** is the par yield of a note on it, with
   coupons every six months to 10 years: for the discount factors `D1 ... D20` of its 20 payment
   dates,

   ```text
   yield = 2 × (1 - D20) / (D1 + D2 + ... + D20)
   ```

   which is the coupon that makes the note worth exactly its face value.

### How implied volatility sets the numbers

The market doesn't publish `sigma1` and `sigma2`. It publishes **option prices**, and an option on
something that moves more is worth more. Fitting the model means finding the numbers for which the
model's prices of real options, worked out on its own paths, are nearest the market's.

**From a price to a volatility.** An option's price depends on how far its strike is from the
future's price, how long it has to run, and how much the future is expected to move. To compare
options of different strikes, expiries and futures, each price is turned into the volatility it
implies: the *normal volatility* (Bachelier's), the standard deviation of the future's price in a
year, in points, for which the formula

```text
price = D × ((F - K) N(d) + v sqrt(t) n(d)),   d = (F - K) / (v sqrt(t))      (a call)
```

gives the market's price (`F` the future's price, `K` the strike, `t` the years to expiry, `D` the
discount factor to then, `N` and `n` the normal distribution's cumulative and density). The program
finds `v` by bisection.

**The model's price of an option** is worked out on its own paths, the way the market would
settle it:

1. Simulate the factors, a day at a time, to the option's expiry.
2. On each path, work out the future's price at expiry. For the **10-year note future**, it is the
   price of a note of 6.75 years on the bent curve (see "The note", below). For a **SOFR future**, it
   is today's price, less 100 times the factors' average bend over the future's quarter.
3. Center them: the future's price is expected to stay where it is (it is marked to market each
   day), so the prices on the paths are scaled (the note's) or shifted (SOFR's) to average today's
   price. That one adjustment absorbs what the model leaves out: the basis, the carry, the
   convexity.
4. The option's payoff on each path, `max(F - K, 0)` for a call, discounted to today along that
   path (`D_today(T) × exp(-sum of delta-r × dt)`), and averaged over the paths.

**The error.** For each option, the difference between the model's price and the market's, over
the option's *vega* (how much its price moves for a point of volatility) times its volatility. That
is the relative error of the volatility the model's price implies: 0.05 is 5% too much. Options
far from the money, whose price barely depends on volatility, are left out (more than 2 standard
deviations away), and so are those within 10 days of expiry, and SOFR options within 3 months. The
error of each kind is the root mean square of its options', and `calibrate-rate-model` minimizes
the square root of the sum of the two kinds' squares.

**The search** is Nelder–Mead's, in the logarithms of the numbers, so that none can go to 0 or
below. Every set of numbers tried is priced on the same random numbers, so that the error is a
smooth function of them, and the search isn't thrown by the noise of the simulation.

**So the paths are the options' paths.** Nothing about rates' history goes into them: today's
curve sets where they are centered, and option prices set how widely they spread. That is what
pricing needs (a price has to agree with the market's prices), and it is not a forecast. "How the
paths compare with history", below, shows the difference.

#### Which options, and what they found

Two kinds of option help, and which function to use follows from which you have:

| You have | Use | Finds |
|---|---|---|
| options on the 10-year note future (ZN: `note-option-rows`) | `calibrate-to-note-options` | `sigma2` (and, loosely, others) |
| those and options on SOFR futures (`sofr-calibration-data`) | `calibrate-rate-model` | `a`, `sigma1`, `sigma2`: **the one to use** |

The SOFR options show how much the *short* rate moves. A mortgage rate follows the *long* end, and
options on the 10-year note future (ZN, the most traded of the Treasury futures) say how much that
moves, directly. In this model the 10-year yield is about a tenth the short-rate factor and nine
tenths the level factor, so these options mostly pin down `sigma2`. They say little about `sigma1`
(the options go out only a few months), so they are best fitted *together with* the SOFR options:
`sigma1` and `a` from the SOFR options, `sigma2` from the notes', and a model that has to agree with both.

Both kinds of option are priced on the same paths, which are the ones `simulate-rate-paths` draws,
so the numbers fitted are the paths' own. Four things make the note future work, and none is obvious:

- **Today's curve is the center.** The model's own starting curve is too crude to match a
  note: on one real day it priced the 6% 10-year note at 99.3, where today's Treasury curve says 107.0
  and the market's future said 105.6 — a six-point error, many times the premium of an at-the-money
  option (about 0.9 points). So the paths keep only the model's *randomness* and add it to the forward
  rates the market gives today. Pass the **Treasury's** forward curve, not the SOFR curve: the future is
  a Treasury contract.
- **The note.** A ZN future is settled by delivering any of several notes, usually the cheapest
  to deliver: ones with 6½ to 8 years left (CME's specification), not the ten of the 6% notional note.
  Its price moves like a note of about seven years. The model takes the future to be one note of
  `:ctd-maturity` (6.75) years at the option's expiry, with the coupon that makes it a par bond on the
  forward curve: no basket of notes and no switch of the cheapest. The options cannot say which maturity is
  right, and it matters: `sigma2` is 0.0147, 0.0132 or 0.0118 for a note of 6, 6.75 or 7.5 years, at
  the same fit. If you know the cheapest to deliver's remaining maturity, give it.
- **The level of the future.** A future is marked to market daily, so its price is expected to
  stay where it is: the model's note price is scaled, at each expiry, so its average over the paths
  is the future's price today. That one scale absorbs what the model doesn't have — the conversion
  factor, the basis, the carry — and leaves the model to say how widely the price is spread around it.
- **Days.** The options expire from a week to four months out, so the paths step by the day, and
  an option expires on its own day. The model's options are European; the market's are American, which is
  worth under a third of a percent of a premium at these expiries.

On 2026-10-15, the Treasury curve and the 24 options expiring 2026-11-20 gave `sigma2` = 0.0134 and a 3.4% root
mean square volatility error: the model's 6.85 points of volatility against the market's 6.7–7.2, a yield
volatility of about 112 basis points a year at a duration of 5.8. What is left is the smile.

On 2026-10-30, fitted together with 20 SOFR options (three months out or more) and 96 note options, `sigma2`
was 0.011 to 0.013 however the other two were set: the note options decide it. **`a` and `sigma1` are not
told apart well.** A faster `a` with a larger `sigma1` fits the SOFR options a little better, and the fit
of all three ran to `a` = 7.2 and `sigma1` = 0.089, with the SOFR options' volatilities 6% from the
market's. Holding `a` at 2.75 gave `sigma1` = 0.031 and 9%; at 1.0, `sigma1` = 0.018 and 11%. The reason
is that a model whose volatility is the same at every date has to match options of three months and of
two years at once: a fast `a` lets a large shock die away before a far quarter, which is how it makes the
far options' volatility smaller than the near ones'. A short rate that wild (a standard deviation of 2.4
points about the curve) isn't believable, so hold `a` at a value you believe, with `:fit '(sigma1 sigma2)
:a 2.75`, and let the options set the two volatilities. Left in, the SOFR options of a month or two (whose
volatility, 18 basis points a year, is a fifth of those a year out) push `sigma1` to 0: a model with one
volatility cannot match the front of the market, where the Fed's next move is nearly known.

### How the paths compare with history

The model's volatilities come from option prices, which say how much the market expects rates to
move. How much they did move is another question, and `fred-table` answers it. With the numbers
of Part 1, the paths' 10-year yield changes over a year by a standard deviation of 1.07 points, and over
five years by 1.88. The Treasury's 10-year yield, month by month since 1990, changed over a year by
0.87 points and over five years by 1.43:

```lisp
(define history (series-monthly (fred-table creds "DGS10" :start-date "1990-01-01")))
(define yields (/ (vector-fill-forward (table-column history "DGS10")) 100))
(define (changes months) (- (vector-drop yields months) (vector-take yields (- (vector-length yields) months))))
(vector-stdev (changes 12))                       ; 0.0087
(define (model-changes month) (- (list->vector (map (lambda (p) (vector-ref p month)) ten-year-yields))
                                 (list->vector (map (lambda (p) (vector-ref p 0)) ten-year-yields))))
(vector-stdev (model-changes 12))                 ; 0.0107
```

So the options expect about a fifth more movement than history shows. That is usual: an option's
buyer pays for protection, so options imply more volatility than what follows, on average. For
pricing, use the options' (a price has to agree with the market's prices); for a forecast of how
widely rates will spread, the history is the better guide, and smaller volatilities, as
`(* 0.8 sigma2)`, give it.

## Part 3. Using the paths

### How many paths

A price from paths is an average, so it has an error that falls as the square root of the number
of paths. The paths come in mirror-image pairs (each path's random shocks, and the same shocks with
their signs turned), which makes the error smaller still. For the 5-year 4% bond of "Pricing on the
paths", on 2026-10-30, eight seeds gave prices within these ranges:

| Paths | Prices, over eight seeds | Making the paths took |
|---|---|---|
| 100 | 96.66 to 96.73 | three hundredths of a second |
| 1,000 | 96.68 to 96.70 | three hundredths of a second |
| 10,000 | 96.692 to 96.700 | a quarter of a second, and as long again to make them Lisp vectors |

200 paths are enough for a picture, a few thousand for a price, and ten thousand for a
difference of two prices, such as a duration, where the errors would otherwise be most of the
answer. For a difference, use the same `:seed` for both prices: then both have the same error,
which cancels.

### Pricing on the paths: a bond, its OAS and its duration

To price something on the paths, give it a cash flow for each month, discount each path's cash
flows by that path's short rates, and average over the paths: `path-present-values` does the
discounting, for all the paths at once. A 5-year Treasury with a 4% coupon, on the curve of
2026-10-30:

```lisp
(define curve (curve-forward-rates (treasury-zero-curve (treasury-par-curve))))
(define flows (vector-map (lambda (month) (+ (if (= (mod month 6) 0) 2.0 0.0) (if (= month 60) 100.0 0.0)))
                          (+ 1 (vector-range 60))))                 ; a coupon of 2 every six months, and the face
(define paths (simulate-rate-paths curve 0.031 0.0117 5 2000 :a 2.75 :seed 1))
(define (price-on paths oas) (vector-mean (path-present-values flows (second paths) oas)))
(price-on paths 0.0)                                                ; 96.70
(price-on (simulate-rate-paths curve 0 0 5 2) 0.0)                  ; 96.56: on the curve itself
```

The two prices differ by 14 cents, a little under 3 basis points of yield: that is the model's
*convexity*, which it does not correct for (an average of discount factors along paths that
spread out is a little more than the curve's discount factor).

**OAS.** The *option-adjusted spread* is the spread that, added to every short rate on every path,
makes the paths' price the market's. It is what a bond pays over the Treasury curve, after its
options (a call, a mortgage's prepayments) are paid for on the paths. Solve for it with `ridders`:

```lisp
(define oas (ridders (lambda (spread) (- (price-on paths spread) 99.0)) -0.05 0.05))    ; a price of 99: -0.0052
```

**Effective duration.** How much the price falls, in percent, for a rise of 1 in all rates: move
the whole curve up and down, keep the OAS, price again on paths with the same seed, and take the
difference:

```lisp
(define (moved bp) (simulate-rate-paths (+ (table-column curve "forward") bp) 0.031 0.0117 5 2000 :a 2.75 :seed 1))
(define up (price-on (moved 0.0025) oas))          ; 97.88
(define down (price-on (moved -0.0025) oas))       ; 100.14
(/ (- down up) (* 2 99.0 0.0025))                  ; 4.56 years
```

For a bond whose cash flows don't depend on rates, that is its ordinary duration. The point of
paths is the securities whose cash flows do: a callable bond, below, and the tranches of a
structured deal, whose prepayments depend on each path's mortgage rates
([lisp_cmo_manual.md](lisp_cmo_manual.md) does all of this for them).

### Mortgage rates and callable bonds

**Mortgage rates.** A mortgage rate moves with the 10-year yield (see
`examples/sofr_and_mortgage_rates.lsp`: from week to week it follows the 10-year, and not SOFR).
`simulate-mortgage-rate-paths` gives, with the paths, a mortgage rate on each: the 10-year par
yield plus a spread. Today's spread is today's mortgage rate less the curve's 10-year yield, so
that the paths start at today's rate:

```lisp
(define survey (fred-table creds "MORTGAGE30US" :start-date "2026-09-01"))
(define mortgage-rate (/ (vector-ref (table-column survey "MORTGAGE30US") (- (table-row-count survey) 1)) 100))
(define spread (- mortgage-rate (curve-par-yield curve 10)))         ; 7.24% - 4.98%: 2.26 points
(define mortgage-paths (fourth (simulate-mortgage-rate-paths curve 0.031 0.0117 5 2000 spread :a 2.75 :seed 1)))
(vector-quantile (list->vector (map (lambda (path) (vector-ref path 60)) mortgage-paths)) (vector 0.1 0.5 0.9))
; in five years: 5.4%, 7.8% and 10.2%
```

The spread is the same on every path and every month, which is the model's simplification: the
real one widens when rates move a lot, and narrows when banks want mortgages.

**Callable bonds.** `price-callable-bond` prices a bond that its issuer may call: on each path,
the issuer calls if the bond is worth more than the call price then, so the holder gets the
smaller of the two. A 10-year 5% bond callable at 100 in three years, at an OAS of 0, was worth
97.45 on 2026-10-30, against 100.75 for the same bond with no call: the call was worth 3.3
points to the issuer.

```lisp
(price-callable-bond curve 0.031 0.0117 10 0.05 3 100 0.0 :a 2.75 :seed 1)        ; 97.45
```

## Part 4. Paths from history: investment prices

Paths of rates spread as option prices say they should. Paths of an investment's price are made
another way: from the investment's own history. The first section copies pieces of the past, end
to end (a *block bootstrap*); the second starts the copied paths at the market's volatility today,
with a model of how volatility changes (*filtered historical simulation*). `examples/investment_paths_example.lsp`
does both, and "Checking option prices against simulated paths", in the library manual, uses them to
find options out of line with their underlying's history.

### Simulating investment prices

(In `lisp_investment_paths.py`.) An investment's possible futures, made from its own
past, by a **block bootstrap**. Tomorrow is likely to be something like
the days in the investment's history, so a future is built by copying pieces of
the past, end to end. Each piece is a *block* of consecutive days, rather
than one day at a time, so that a stretch of wild days (or calm ones)
stays together, as it does in life. These functions work one after
another:

1. `daily-returns` makes a table of returns from prices (and dividends).
2. `adjust-returns` takes out those returns' average and puts in the
   return you expect.
3. `dividend-schedule`, for an investment that pays dividends, lists the
   ones to come in the days of a path.
4. `bootstrap-path` makes one path of future prices from them. Call it
   once for each path you want. With `:volatility`, a model that
   `volatility-model` makes, a path starts at today's volatility, not the
   history's average: see "Starting paths from today's volatility".
5. `option-value` is what an option is worth, from a list of paths. And
   `option-payoffs` is what many options pay at once, from a list of
   paths, for a whole option chain: see "Checking option prices against
   simulated paths".

**The returns are log returns**, ln(today's price / yesterday's), which
add up: the price after a run of days is the starting price times *e* to
the sum of the days' log returns. So changing a set of returns' average is
a matter of subtracting one number and adding another. A table of returns
has a `date` and a `log-return` column.

#### `(daily-returns prices [:dividends table])`
An investment's daily log returns: a table of `date` and `log-return`, oldest
first, with a row for each day of `prices` but the first. `prices` is a
table with `date` and `close` columns, oldest first, as `schwab-price-history`
makes.

Schwab's prices are not adjusted for dividends: on the day an investment first
trades without its dividend (its ex-date) the price drops, and the return
from prices alone is low by what the investment pays. `:dividends`, a table with
`ex-date` and `amount` columns, as `alpha-vantage-dividends` makes, puts
them back: a dividend is part of the return of its ex-date, which is
ln((close + dividend) / yesterday's close). (A dividend on a day with no
price, such as a Saturday, goes with the next day there is a price. One
before the first price, or after the last, is left out.) The returns then
are an investment's *total* return, so a path made from them is the price with
its dividends reinvested.

```lisp
(define prices (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4)))
                     (cons "close" (vector 100.0 110.0 99.0))))
(define dividends (list (cons "ex-date" (vector (date 2024 1 4)))
                        (cons "amount" (vector 1.0))))
(table-column (daily-returns prices) "date")                                             ; => #(2024-01-03 2024-01-04)
(vector-round (table-column (daily-returns prices) "log-return") 4)                      ; => #(0.0953 -0.1054)
(vector-round (table-column (daily-returns prices :dividends dividends) "log-return") 4) ; => #(0.0953 -0.0953)
```

#### `(adjust-returns returns annual-return [:days-per-year n] [:volatility-scale x])`
`returns` with its `log-return` column changed (its other columns stay as
they are): the average is taken out, then a number is added so that the
investment's **expected annual return** is `annual-return`, 0.08 for 8%.
(An investment's history has the return it happened to have; this is the
one you expect from here.)

Not just `annual-return` spread over the days, though. The price rises by
the daily returns, not by the log returns, and their average is higher
than the log returns' by about half the variance (more for one that
jumps around). So the number added makes the average of the *daily
returns* come out at (1 + `annual-return`) ^ (1 / `:days-per-year`) - 1,
the one that makes a year of them 8%. `:days-per-year` is 252 trading
days, unless said otherwise. With blocks of a single day, the paths'
average price a year out is exactly right (apart from chance); with longer
blocks, close to right. `annual-return` must be above -1 (a loss of all of
it).

For several investments' returns, as `combine-returns` makes (see
"Portfolios"), `annual-return` is one number for all of them, or a list
of `(name . annual-return)`, one for each.

`:volatility-scale` (1, no change, unless given) multiplies the returns'
spread about their average, so that the volatility is that many times the
history's: 1.2 is 20% more, and 0.8 is 20% less. The expected annual
return is still `annual-return`. It is for when the volatility to
expect isn't the history's, as `check-option-chain`'s `:match-volatility`
finds for an option chain.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0))))
(define adjusted (adjust-returns returns 0.08))
(format "{:.6f}" (vector-mean (vector-exp (table-column adjusted "log-return"))))   ; => "1.000305"
(format "{:.6f}" (expt 1.08 (/ 1.0 252)))                                           ; => "1.000305"
(define wilder (adjust-returns returns 0.08 :volatility-scale 2))
(format "{:.4f}" (/ (vector-stdev (table-column wilder "log-return"))
                    (vector-stdev (table-column adjusted "log-return"))))           ; => "2.0000"
(format "{:.6f}" (vector-mean (vector-exp (table-column wilder "log-return"))))     ; => "1.000305"
```

#### `(dividend-schedule dividends start-date days [:repeat-last-year #t])`
The dividends an investment will pay in the `days` trading days of a path
that starts the day after `start-date` (the date of the path's start
price): a table of `ex-date`, `day` (the ex-date's number among those
trading days, 1 for the first), and `amount`, in order, ready for
`bootstrap-path`'s `:dividends`. `dividends` is a table of `ex-date` and
`amount` columns, as `alpha-vantage-dividends` makes. The days are
counted with the NYSE's calendar, "Trading days".

- By default the schedule has the dividends of the table that come after
  `start-date`, up to the path's last day: the ones announced, if the table
  has any. (One on `start-date` is in the start price already.)
- **`:repeat-last-year #t`** supposes that the dividends of the year up to
  `start-date` go on, every year after, **on the same dates and in the same
  amounts**. A date the market is closed, such as a Saturday, is the next
  day it's open. (February 29 is February 28 in a year that isn't a leap
  year.) It is the way to look ahead for an investment that pays about the
  same dividends on about the same dates, as most do. The table's dividends
  after `start-date` aren't used with it.

A dividend that comes after the path's last day isn't in the schedule, so
an option that ends before an ex-date doesn't have its dividend taken off.

```lisp
(define actual (list (cons "ex-date" (vector (date 2025 11 14) (date 2026 2 13) (date 2026 5 15) (date 2026 8 14)))
                     (cons "amount" (vector 0.50 0.50 0.52 0.52))))
(define schedule (dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #t))
(table-column schedule "ex-date")     ; => #(2026-11-16 2027-02-16 2027-05-17 2027-08-16)
(table-column schedule "day")         ; => #(30 91 154 216)
(table-column schedule "amount")      ; => #(0.5 0.5 0.52 0.52)
```
(The four dates of a year later are Saturdays; and the Monday after the
second, February 15, 2027, is Washington's Birthday.)

#### `(bootstrap-path returns start-price days block-size [:seed n] [:dividends schedule] [:volatility model] [:start-volatility x])`
One path of future prices, as a vector of `days` prices: the first is the
day after `start-price`'s. `returns` is a table with a `log-return`
column, such as `adjust-returns` makes. The path is made of blocks of
`block-size` consecutive returns, each starting at a day of the history
picked at random, put end to end until there are `days` of them (the last
block is cut short if it has to be). The prices are what `start-price`
becomes with those returns.

- **Paths wrap.** A block that runs past the end of the history carries on
  from its start, so every day of the history is as likely as any other to
  be in a block.
- **`block-size`** is how many days stay together: 1 draws days one at a
  time, as an ordinary bootstrap does, with no memory of the day before.
  Something like 10 or 20 keeps an investment's stretches of high and low
  volatility. It can't be more than the number of returns.
- **`:seed`**, a whole number, makes the path the same every time. It has
  the function's own random numbers (as `vectors-shuffle`'s seed does),
  so it doesn't change the shared generator that `random-float` and
  `random-int` use. **Give each path its own seed**, such as `(+ 1000 i)`
  for the path numbered `i`, or every path is the same one. Without
  `:seed`, the shared generator is used, so one `(random-seed 42)` before
  you make all the paths makes them the same each time.
- **`:dividends`** is a schedule, as `dividend-schedule` makes, of the
  dividends the investment pays: when one comes, the price falls by its
  amount, in every path, whatever the price has done (to 0 at the lowest,
  and a price of 0 stays there). A dividend after the path's last day
  does nothing. The returns for such a path are **total returns**, dividends
  included, as `daily-returns` gives with `:dividends`, so that all of the
  investment's return, dividends too, grows at the rate `adjust-returns`
  was given.
- **`:volatility`** is a volatility model, as `volatility-model` makes: the
  path starts at today's volatility, and its volatility changes from day
  to day as the model says, going back toward the history's. Its days'
  returns are the history's shocks times the path's own volatility. See
  "Starting paths from today's volatility". **`:start-volatility`**, for
  a year (0.12 for 12%), starts it somewhere else, such as at the
  volatility the market expects.
- A path can't have a day more extreme than the days of the history it
  is made from, so the longer a history (that is still like the future)
  the better.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0 0.005))))
(vector-length (bootstrap-path returns 100 252 3))                   ; => 252
(vector-round (bootstrap-path returns 100 5 2 :seed 1) 2)            ; => #(98.02 99.5 100.0 101.01 102.02)
(equal? (bootstrap-path returns 100 5 2 :seed 1)
        (bootstrap-path returns 100 5 2 :seed 1))                    ; => #t

; two dividends, 1.50 on the 2nd day and 3.00 on the 5th, with returns that are 0:
(define flat (list (cons "log-return" (vector 0.0 0.0))))
(define dividends (list (cons "day" (vector 2 5)) (cons "amount" (vector 1.5 3.0))))
(bootstrap-path flat 100 6 1 :dividends dividends)                   ; => #(100.0 98.5 98.5 98.5 95.5 95.5)
```

A thousand paths of an investment's next year, and where they end up. This
needs a Schwab sign-in, and `examples/investment_paths_example.lsp` has it all:

```lisp
(define prices (schwab-price-history creds "BRK/A"))        ; ten years, as Schwab gives them
(define returns (adjust-returns (daily-returns prices) 0.08))
(define start-price (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define paths (map (lambda (i) (bootstrap-path returns start-price 252 10 :seed (+ 1000 i)))
                   (iota 1000)))                            ; a list of 1000 vectors of 252 prices
(define year-ends (list->vector (map (lambda (path) (vector-ref path 251)) paths)))
(vector-quantile (vector-div year-ends start-price) #(0.05 0.5 0.95))   ; the 5th, 50th, and 95th percentiles
```

#### `(bootstrap-days returns days block-size [:seed n] [:volatility model] [:start-volatility x])`
The days of the history a path is made of, to see how it was built: a
table of `day` (1 for the path's first), the `date` of the history's day
it copies (if the table of returns has dates), and that day's returns.
With the same `:seed`, `bootstrap-path` (and `bootstrap-paths`) make their
paths from these days: a path's price on a day is its start price times *e*
to the sum of the returns up to that day. With `:volatility`, for one
investment's returns, three columns more say how the path's returns were
made from them: `shock`, the history's day's; `volatility`, the path's
that day, for a year; and `path-return`, the path's return, which is what
its prices are made of then.

```lisp
(define returns (make-table "date" (vector (date 2024 1 3) (date 2024 1 4) (date 2024 1 5))
                            "log-return" #(-0.02 0.03 0.0)))
(table-column (bootstrap-days returns 4 2 :seed 3) "date")   ; => #(2024-01-03 2024-01-04 2024-01-05 2024-01-03)
(vector-round (bootstrap-path returns 100 4 2 :seed 3) 2)    ; => #(98.02 101.01 101.01 99.0)
```
(The second block starts on the history's last day, and carries on from
its first.)

#### `(option-value paths payoff rate years)`
What an option is worth, estimated from simulated paths of its
investment's price. `paths` is a list of paths, vectors of prices, such as
`bootstrap-path` makes. `payoff` is a procedure of one argument, a path,
that returns what the option pays at the end of it: for a call, the final
price less the strike, or 0 if that's less. The value is the payoffs'
present values averaged, each discounted for `years` at `rate`, the
interest rate, continuously compounded (0.04 for 4%, as `bsm-price`
takes it).

It returns a list of two numbers: the value, and its **standard error**,
which says how far chance may have put the value from the one these paths
are a sample of. The value is probably within two standard errors of it;
four times as many paths halve the error.

The procedure is given the whole path, so an option that depends on how the
price got there is as easy as one that depends only on where it ended.
And what's paid doesn't have to be an option's: anything paid after a
path of prices is valued the same way.

```lisp
(define returns (list (cons "log-return" (vector 0.01 -0.02 0.015 0.0 0.005 -0.01 0.02))))
(define rate 0.04)
(define fair-returns (adjust-returns returns (- (exp rate) 1)))     ; see below
(define paths (map (lambda (i) (bootstrap-path fair-returns 100 252 1 :seed i)) (iota 2000)))
(define (call-pays path) (max 0 (- (vector-ref path 251) 100)))     ; a call struck at 100, a year out
(define (show-value v) (format "{:.2f} +/- {:.2f}" (first v) (second v)))
(show-value (option-value paths call-pays rate 1))                  ; => "10.00 +/- 0.33"
(show-value (option-value paths (lambda (path) (max 0 (- (vector-mean path) 100))) rate 1))   ; => "5.77 +/- 0.18"
(show-value (option-value paths (lambda (path) (if (< (vector-min path) 90) 0 (call-pays path))) rate 1))   ; => "8.25 +/- 0.33"
```
The second is an Asian call, paid on the average price along the way, and
the third a call that is worth nothing if the price ever falls below 90.

**For a fair value, the paths must grow at the interest rate.** A price
that grows at 8% when money earns 4% makes calls look worth more, and puts
less, than anyone would pay: that is what the option pays on average if
the investment does earn 8%, not what it costs to be paid in every case.
(In a test on ten years of BRK/A, a call valued with 8% growth came out
26% higher.)

- Make the paths from `(adjust-returns returns (- (exp rate) 1))`: the
  annual return that grows a price at the continuously compounded `rate`.
- **Dividends take money out of the price, so the paths must lose it
  too.** When the investment pays dividends, make the returns *with*
  `:dividends` (they are then total returns, which `adjust-returns` makes
  grow at the interest rate, as above), and give `bootstrap-path` a
  schedule of the dividends to come. The price of every path then falls by
  the same dollar amounts on the same days, which is what known dividends
  do, and what an option on the price is paid on. A dividend after the
  option expires is not counted, because the schedule stops at the path's
  last day. For dividends not yet declared, `dividend-schedule` can suppose
  that the last year's go on, on the same dates and in the same amounts.
- **A yield, instead.** When dividends are small, regular, and spread
  through the year, as an index's are, or their dates aren't known, a
  continuous yield `q` is simpler: use returns *without* `:dividends`, and
  the annual return `(- (exp (- rate q)) 1)`.
  But a yield takes a bit of dividend off every day, and in proportion to
  the price (a path where the price doubles has doubled dividends), where
  real dividends come all at once, in set amounts. That makes little
  difference to a one-year option and its quarterly dividends, but a lot
  to one shorter than the time between them. In Black-Scholes, for a
  one-year at-the-money call at 20% volatility on 100, with four quarterly
  dividends of 0.50, a 2% yield is 0.1% from the known dividends' value;
  for a call that expires before the first ex-date it is 3.5% low, as the
  yield takes off a dividend that never comes.

```lisp
; a 3-month (63 trading days) call on an investment that pays dividends, struck at today's price
(define actual-dividends (alpha-vantage-dividends creds "SPY"))
(define prices (schwab-price-history creds "SPY"))
(define fair-returns (adjust-returns (daily-returns prices :dividends actual-dividends) (- (exp rate) 1)))
(define last-day (vector-ref (table-column prices "date") (- (table-row-count prices) 1)))
(define schedule (dividend-schedule actual-dividends last-day 63 :repeat-last-year #t))
(define start-price (vector-ref (table-column prices "close") (- (table-row-count prices) 1)))
(define paths (map (lambda (i) (bootstrap-path fair-returns start-price 63 1 :seed i :dividends schedule))
                   (iota 5000)))
(option-value paths (lambda (path) (max 0 (- (vector-ref path 62) start-price))) rate (/ 63 252.0))
```

- A path has a price for each trading day, so `years` is its days divided
  by the days in a year, as `adjust-returns` takes them (252): `years` of 1
  for 252 days.

**Block size changes the answer.** Paths of blocks of one day average a
price a year out of just what `adjust-returns` set, and agree with
Black-Scholes. Longer blocks keep what the history did over several days:
if it often fell and then recovered, as it did in March 2020, so do the
paths, and over a year they spread less than a day's spread would suggest.
In ten years of BRK/A (to October 2026), a year's at-the-money call came
out at 73,073 (+/- 736) with blocks of 1 day, 68,090 (+/- 678) with blocks
of 10, and 65,471 (+/- 634) with blocks of 21; Black-Scholes, with the
history's volatility, gave 72,350. The paths' volatility over the year was
19.1%, 18.1%, and 17.5%. (The average price a year out is also a little
low with longer blocks, 0.3% to 0.4%.) What comes out is the value if the
future is like this history, which is not the market's price: the market's
is from the volatility it expects.

**Paths with blocks of a day agree with Black-Scholes only over long
times.** The paths have the history's own returns, and those aren't
normally distributed: they have fat tails, which means more days of big
moves than a normal distribution would have, and more quiet days too, for
the same volatility. So over a few days or weeks, the paths value an option
near the money lower than the formula does, and one far out of the money
higher. Over a year, many days add up to something close to normal, and the
two agree. On October 8, 2026, for BRK/A, with 20,000 paths at the
history's 19.0% volatility and an interest rate of 4%:

```
option                      black-scholes    tree  monte-carlo  standard-error  standard-errors-apart
1 year, call at the money          72,504  72,432       72,719             733                   +0.3
1 year, put 20% below               4,775   4,782        5,063             141                   +2.0
1 month, call at the money         17,887  17,866       17,658             181                   -1.3
1 month, put 10% below                351     350          481              28                   +4.6
```

The tree (`american-price` with `:early-exercise #f`) is the formula's own
model, made of steps, so it agrees with the formula, but for having only so
many steps. `lib/option_methods.lsp` values a stock's listed options all
three ways, next to their bids and asks, and gives the chance that each
ends in the money by each: see "Valuing options three ways". For BRK/B's, at the
close of October 7, with the stock at 506.20, a call struck at 515 and
expiring in 6 trading days was worth 2.83 by the formula and 2.53 (± 0.05)
on the paths. Both were well above the market's
ask, 1.01: the market expected less volatility than the history had.

#### `(option-payoffs paths days strikes calls)`
What many European options pay, on average, over a list of paths: a table
with a row for each option, and these columns:

| Column | What it holds |
|---|---|
| `payoff` | the average of what the option pays at expiration, before discounting |
| `payoff-error` | its standard error |
| `paths-paid` | how many paths it pays something on |

`paths` is a list of paths, vectors of prices that are all the same
length. `days`, `strikes`, and `calls` are vectors with an element for
each option: `days`, the number of the path's day it expires on (1 for the
first); `strikes`; and `calls`, 1 for a call and 0 for a put. A call pays
the price on its day less the strike, if that is more than 0, and a put
the strike less the price. Discount the payoffs for the time to
expiration, as `option-value` does for one option. All the options are
valued from the same paths, so what they say about one another is not
noise.

```lisp
(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0) #(10.0 10.0 10.0) #(10.0 12.0 14.0)))
; a call on day 3 struck at 10, a put on day 3 at 11, a call on day 1 at 10, and a put on day 2 at 11
(define payoffs (option-payoffs paths #(3 3 1 2) #(10 11 10 11) #(1 0 1 0)))
(table-column payoffs "payoff")        ; => #(1.5 1.0 0.0 0.75)
(table-column payoffs "paths-paid")    ; => #(2 2 0 2)
```

### Starting paths from today's volatility

(In `lisp_investment_paths.py`.) A path made by `bootstrap-path` copies
blocks from anywhere in the history, so it starts out as wild as the
history is on average, however calm or wild the market is today. In
October 2026, SPY's volatility over the last month was 10%, and over the
last ten years 18%: its paths started at 18%, while the market priced the
next weeks at about 10%. A **volatility model** makes a path start at
today's volatility instead. Then the path's volatility changes from day to
day, as the model says: a big move makes the days after it wild, calm days
let it settle, and on average it goes back toward the history's. So the
paths still differ in volatility, some turning wild and some staying calm,
but they all start from today's. This is called *filtered historical
simulation*, and it works in three steps:

1. **Each day's volatility in the history is estimated** from the day
   before's, and from how big the day before's *move* was (its return less
   the average return):

   ```
   tomorrow's variance = constant
                       + up-day-weight   x today's move squared   (if it went up)
                         or down-day-weight x today's move squared (if it went down)
                       + variance-weight x today's variance
   ```

   A variance is a volatility squared, here a day's. For SPY's ten years
   to October 2026, the weights that fit best are 0.036 for an up day,
   0.236 for a down day, and 0.827 for the variance: a fall raises the
   volatility more than six times as much as a rise of the same size. The
   constant pulls the variance back toward the history's: each day, on
   average, its difference from it shrinks to its **persistence** of
   itself (0.980 for SPY), so that half of the difference is gone in its
   **half-life** (34 trading days).
2. **Each day's return becomes a shock**: its move divided by that day's
   volatility, so how many of its own standard deviations it moved. A 3%
   drop on a calm day is a big shock; on a wild day, a small one. The
   shocks keep the history's fat tails and its crashes, but not the calm or
   the wild stretch each one came in.
3. **A path is made of shocks.** It copies blocks of the history's days,
   as before, but takes their shocks: each day's return is its shock times
   the path's own volatility that day, and then the path's volatility is
   updated by the formula, with the move the path just made. It starts at
   the volatility the model gives the day after the history's last, or at
   `:start-volatility`, if that's given.

What SPY's model expected, from the close of October 6, 2026 (with
`volatility-forecast`):

| Over the next | 1 day | 1 week | 1 month | 3 months | 6 months | 1 year |
|---|---|---|---|---|---|---|
| Volatility | 9.6% | 10.0% | 11.5% | 13.8% | 15.4% | 16.7% |

```lisp
(define returns (adjust-returns (daily-returns (schwab-price-history creds "SPY")) 0.08))
(define model (volatility-model returns))
(display-table model)
(define paths (map (lambda (i) (bootstrap-path returns 100 252 10 :seed (+ 1000 i) :volatility model))
                   (iota 1000)))
```

**How the weights are found.** `volatility-model` tries every set of
weights on a grid: 0 to 0.3 for an up day, 0 to 0.5 for a down day, and
0.5 to 0.99 for the variance, 0.02 apart; then sets 0.005 apart, near the
best of those; and then 0.001 apart, near the best of them. The best set is
the one under which the history is most likely. Each day's move is
supposed to come from a normal distribution with the variance the model
gives that day, and the set that makes the moves most probable wins: its
`log-likelihood` is the highest. A big move on a day the model called
calm counts against a set of weights, and so does a wild forecast for a
quiet day. The constant isn't searched for: it is set to make the variance
go back toward the history's (*variance targeting*). A set whose
persistence would be more than 0.998 isn't taken, since its volatility
would hardly go back at all. In the usual names, the formula is a
*GJR-GARCH(1,1)* model: `up-day-weight` is alpha, `down-day-weight` is
alpha + gamma, and `variance-weight` is beta.

**Two details.** The persistence is the variance weight plus the up-day
and down-day weights, each counted for its share of the shocks' squares:
`down-share` is the share on down days (0.585 for SPY). And the shocks are
scaled so that their squares average exactly 1, as a volatility's shocks
should (they come out within a few percent of it anyway). Then a path's
volatility is the size of its moves, on average, and it goes back toward
the history's volatility.

**The paths are lopsided.** `volatility-forecast` is the square root of
the average variance: what the paths have on average, taken all together.
But a few paths turn very wild, and most stay calmer, so the typical path
is calmer than the forecast. For SPY's next 59 trading days, from October
7, 2026: the forecast was 13.7%, and the middle path's volatility 10.7%.
The paths' own implied volatility (from what an option is worth on them,
by Black's formula) was 11.4% at the money, 16.4% for a put struck 10%
below, and 9.9% for a call struck 5% above. That is a skew, like the
market's, and it comes from the down days' bigger weight and from the
crashes among the shocks. An option at the money is priced by the typical
path more than by the average one.

**What it leaves out.**

- **Correlation.** Each investment's volatility is modeled, and
  `bootstrap-paths` copies the same days' shocks for all of them, so their
  correlation is the history's. But it is the same correlation, whatever
  the volatility: in a crash, investments usually move together more than
  they do on average.
- **The weights are fitted to one history**, by one simple formula. Ten
  other years would give other weights, and the half-life especially is
  only roughly known.
- **Blocks.** With blocks of more than one day, a block's shocks are
  consecutive days, and the drift and the forecast are close to right
  rather than exact, as for `bootstrap-path`.

#### `(volatility-model returns [:symmetric #t] [:days-per-year n])`
A model of each investment's volatility, fitted to its history: a table
with a row for each column of returns (one, `log-return`, for one
investment's table; one for each investment, for `combine-returns`'). It
takes at least 100 returns, and a fraction of a second. Its columns:

| Column | What it holds |
|---|---|
| `investment` | the name of the column of returns |
| `next-day-volatility` | the volatility the model gives the day after the history's last, for a year: today's |
| `long-run-volatility` | the history's volatility, for a year, which the model's goes back toward |
| `half-life` | how many days it takes for half of a difference from the long-run variance to go, on average |
| `up-day-weight`, `down-day-weight`, `variance-weight` | the weights in the formula above |
| `persistence` | how much of a difference from the long-run variance is left the next day, on average |
| `down-share` | the share of the shocks' squares that is on down days |
| `log-likelihood` | how well the weights fit the history: the higher the better, for comparing models of the same returns |
| `days-per-year` | how many days the volatilities are for a year of: 252, unless `:days-per-year` says |

`:symmetric #t` makes the up-day and down-day weights the same: compare
the two models' `log-likelihood` to see how much better treating them
differently fits. (For SPY it was 42 higher: much better.)

A model is just a table, and you can change it: `table-add-column`
replaces a column, so `(table-add-column model "variance-weight" 0.9)` is
the same model with another weight. `bootstrap-path` uses the three
weights and `days-per-year`, and works out the rest from the returns it is
given, as `volatility-model` does. So a model of an investment's returns
works for those returns after `adjust-returns`, too: their average doesn't
matter, and if their volatility is scaled, the paths' is scaled the same
way.

```lisp
(random-seed 7)
(define (made-up-day i) (* (if (< i 250) 0.06 0.02) (- (random-float) 0.5)))   ; wild for 250 days, then calm for 50
(define history (make-table "log-return" (list->vector (map made-up-day (iota 300)))))
(define model (volatility-model history))
(vector-round (table-column model "long-run-volatility") 3)   ; => #(0.261)
(vector-round (table-column model "next-day-volatility") 3)   ; => #(0.111)
(vector-round (volatility-forecast model #(1 21 252)) 3)       ; => #(0.111 0.123 0.194)
(table-column-names (bootstrap-days history 5 2 :seed 1 :volatility model))
                                       ; => ("day" "log-return" "shock" "volatility" "path-return")
(vector-round (table-column (bootstrap-days history 5 2 :seed 1 :volatility model :start-volatility 0.5)
                            "volatility") 3)                   ; => #(0.5 0.464 0.446 0.447 0.451)
```

#### `(volatility-history returns model)`
What a volatility model says about each day of one investment's history: a
table of `date` (if the returns have dates), the returns, `volatility` (the
model's estimate of the day's volatility, made the day before, for a
year), and `shock` (the day's move divided by that, as a day's). Chart
`volatility` against `date` to see the history's calm and wild stretches.
The shocks are what the paths copy, and their squares average 1.

```lisp
(define days (volatility-history history model))
(table-column-names days)                     ; => ("log-return" "volatility" "shock")
(< (abs (- (vector-mean (* (table-column days "shock") (table-column days "shock"))) 1)) 0.000001)   ; => #t
```

#### `(volatility-forecast model days [:start-volatility x])`
The volatility a model expects over the next `days` days, on average, for
a year: a number, or for a vector of days, a vector. `model` is one
investment's, a table of one row: `(table-where model "investment" "SPY")`
picks one from a model of several. The first day's volatility is the
model's `next-day-volatility`, or `:start-volatility`. After that, the
variance's difference from the long-run variance shrinks to `persistence`
of itself each day, so the average variance of the first *n* days is

    long-run + (first day's - long-run) x (1 - persistence^n) / (n x (1 - persistence))

and the forecast is its square root. It uses only `next-day-volatility`,
`long-run-volatility`, and `persistence`. With a persistence of 0, the
variance is back to the long run's the second day:

```lisp
(define made-up (make-table "investment" #("log-return") "next-day-volatility" #(0.1)
                            "long-run-volatility" #(0.2) "persistence" #(0.0)))
(vector-round (volatility-forecast made-up #(4)) 4)       ; => #(0.1803)
```
(The square root of (0.1² + 3 × 0.2²) / 4.)

## Part 5. Reference

### Yield curves

(In `lib/yield_curves.lsp`, and `lisp_rates.py` for SOFR.) Three sources of a curve, and the forward
rates a model starts from: the Treasury's par yield curve (`treasury-par-curve`, every business day since 1990,
official and out the same day); the Federal Reserve's fitted curve (`gsw-curve`, by Gürkaynak, Sack and Wright,
every day since 1961, smooth, a research product that lags a few days); and SOFR futures (`sofr-forward-curve`,
from tastytrade's prices, about five years). The history of SOFR itself, day by day, is `nyfed-rates` (see
"The New York Fed's reference rates" in the library manual).

#### Which curve to use
| For | Use | Why |
|---|---|---|
| paths of rates, mortgages, anything that depends on the long end | the Treasury's (`treasury-zero-curve`) | official, today's, and goes to 30 years |
| a smooth curve, or one from before 1990 | the Fed's (`gsw-zero-curve`) | fitted to every Treasury, so its forward rates don't jump; back to 1961 |
| a floating-rate note's coupons, for the next few years | SOFR futures (`sofr-forward-curve`) | it is the rate the coupons are set by |
| a SOFR curve that goes past the futures | `extend-forward-curve` of the SOFR curve and the Treasury's | the futures end about 5 years out |

SOFR and Treasury rates are not the same: SOFR sits a little below Treasury yields of the same
term, by a spread that moves. A curve here is one or the other, never both.

#### The forms of a curve
A curve comes in four forms here, each a step closer to what a model needs:

| Form | What it is | Made by |
|---|---|---|
| par yields | the coupon that makes a bond of each maturity worth its face value: what the Treasury publishes | `treasury-par-curve` (a table, a row a day); a deal's Treasury curve, `'((2 4.1) (10 4.5))` in percent |
| zero curve | a table of `years`, `par`, `discount` (what 1 paid then is worth now) and `zero` (the rate it earns) | `par-curve-zeros`, `treasury-zero-curve`, `gsw-zero-curve` |
| forward curve | a table of `months` (1 to 360), `discount`, and `forward`: the rate for each month, agreed today | `curve-forward-rates`, `sofr-forward-curve`, `forward-rates-table` |
| a vector of forward rates | the `forward` column alone | `(table-column curve "forward")` |

**The forward curve is the one the models take.** Every function of "Interest rate paths" takes a
forward curve, as the table or as the vector of its `forward` column: `simulate-rate-paths`,
`curve-par-yield`, `calibrate-rate-model` and the rest. To go from one form to the next:

| From | To | Use |
|---|---|---|
| a day of the Treasury's par yields | zero curve | `(treasury-zero-curve par-table :date d)` |
| any par yields | zero curve | `(par-curve-zeros years yields)` |
| a day of the Fed's curve | zero curve | `(gsw-zero-curve fed :date d)` |
| zero curve | forward curve | `(curve-forward-rates zeros)` |
| SOFR futures' prices | forward curve | `(sofr-forward-curve rows)` |
| a vector of forward rates | forward curve | `(forward-rates-table vector)` |
| forward curve | par yield of any tenor, today or later | `(curve-par-yield curve 10 :start-months 24)` |

#### From a download to a curve of forward rates
The Treasury's curve today, as forward rates (Part 1, Step 1):

```lisp
(define par (treasury-par-curve))                      ; this year, a row a day; yields as decimals
(define zeros (treasury-zero-curve par))               ; the latest day, as a zero curve
(define curve (curve-forward-rates zeros))             ; 360 months of forward rates
(curve-par-yield curve 10)                             ; 0.0498 on 2026-10-30: the 10-year yield it was made from
```

A day in the past, from the Fed's curve:

```lisp
(define fed (gsw-curve :start-date (date 2008 1 1) :end-date (date 2008 12 31)))
(define curve-2008 (curve-forward-rates (gsw-zero-curve fed :date (date 2008 9 15))))
```

SOFR futures, carried on past the last one by the Treasury's curve:

```lisp
(define sofr (sofr-forward-curve (tastytrade-futures-curve-rows creds "SR3" 40)))
(define sofr-30-years (extend-forward-curve sofr 60 curve))      ; SOFR's for 5 years, the Treasury's after
```

A structured deal keeps its Treasury curve as par yields in percent (see `deal-set-treasury-curve!`
in [lisp_cmo_manual.md](lisp_cmo_manual.md)); `latest-treasury-points` gives today's in that form.

`examples/yield_curve_example.lsp` draws the Treasury's and the Fed's curves for today, as zero
rates and as forward rates.

#### `(treasury-par-curve [:start-date d :end-date d :cache-hours h])`
The Treasury's daily par yield curve as a table, the oldest day first: a `date`
column, and a column for each maturity -- `1m`, `1.5m`, `2m`, `3m`, `4m`, `6m`, `1y`,
`2y`, `3y`, `5y`, `7y`, `10y`, `20y`, `30y` -- of the yield as a decimal, `nan` on a
day when the Treasury published none for a maturity (it hasn't always published every
one: the 20-year is missing in the early 1990s and the 30-year in 2003, and the
1-month, 2-month, 4-month, and 1.5-month came later). From `:start-date` to `:end-date`
(a date, or `"YYYY-MM-DD"`); by default this year so far. Each year is a download from
the Treasury's site, kept for `:cache-hours` (12).

```lisp
(define curve (treasury-par-curve :start-date (date 2020 1 1)))
(plot-chart (list (list "10 years" (table-column curve "date") (table-column curve "10y"))
                  (list "2 years" (table-column curve "date") (table-column curve "2y"))))
(table-where curve "date" (date 2026 10 15))      ; one day's curve
```

#### `(latest-treasury-points [:cache-hours h])`
The Treasury's most recent par yield curve, as `(day points)`: the last day in the last two weeks of the file that `treasury-par-curve` reads which has a yield, and
the points, `(years yield)`, of the maturities it has one for, the yield in percent. That is the form of the Treasury curve of a deal (see
`deal-set-treasury-curve!` in [lisp_cmo_manual.md](lisp_cmo_manual.md)); `(info deal)` has a button for it. The file is kept for `:cache-hours` (1).

```lisp
(define latest (latest-treasury-points))     ; a download, like treasury-par-curve
(deal-set-treasury-curve! deal (cadr latest))
```

#### `(par-curve-zeros years yields)`
The zero curve that par yields give, as a table. `years` are the maturities, rising,
and `yields` the par yield at each as decimals; a missing one (`nan`) is left out. The
table has a row for each maturity of less than six months and for every six months to
the last maturity, with the columns `years`; `par`, the yield given or on a smooth
curve through those given (and flat beyond them); `discount`, what 1 paid then is worth now;
and `zero`, `-ln(discount) / years`. A par curve that is 4% at every maturity has
discount factors that are powers of `1.02`, each coupon being 2% of face:

```lisp
(define flat (par-curve-zeros (vector 0.5 30) (vector 0.04 0.04)))
(table-row-count flat)                         ; => 60
(vector-ref (table-column flat "discount") 1)  ; => 0.96116877
(vector-ref (table-column flat "zero") 59)     ; => 0.039605256
(define bills (par-curve-zeros (vector 0.25 0.5 1) (vector 0.04 0.04 0.05)))
(table-column bills "years")                   ; => #(0.25 0.5 1.0)
(table-column bills "discount")                ; => #(0.990099 0.98039216 0.95169777)
```

#### `(treasury-zero-curve curve [:date d])`
The zero curve of the Treasury's par curve on a day, as `par-curve-zeros` makes it:
`curve` is a table as `treasury-par-curve` makes, and the day the last in it on or
before `:date` -- the latest, if none is given.

```lisp
(define zeros (treasury-zero-curve curve :date (date 2026 10 15)))
(display-table zeros '(("par" ".3%") ("discount" ".5f") ("zero" ".3%")) :max-rows 20)
```

#### `(curve-forward-rates zero-curve [:months n])`
The one-month forward rates of a zero curve, as a forward curve: a table, for each month to `:months`
(360, thirty years), of `months`, `discount`, and `forward`, the rate for the month that
ends then, as a rate for a year with monthly interest -- a month's money grows by
`1 + forward / 12`, so `discount[month - 1] / discount[month] = 1 + forward / 12`.
This table is what the functions of "Interest rate paths" take, and `sofr-forward-curve` makes the
same one. `zero-curve` is any table with columns `years` and `zero`, such as
`treasury-zero-curve` and `gsw-zero-curve` make; the zero rate of each month is on a
smooth curve through those given. The forward rates that come from the Treasury's par yields
are rougher than the Fed's smooth curve's, which is fitted to every Treasury: the Treasury
publishes only three maturities past 7 years (10, 20, and 30), and a wiggle in its
yields there, such as a 20-year yield higher than the 30-year, is a swing in the forward
rates. The example's second chart shows both.

```lisp
(define flat-zeros (make-table "years" (vector 1 30) "zero" (vector 0.05 0.05)))
(define forwards (curve-forward-rates flat-zeros :months 3))
(table-column forwards "months")                          ; => #(1 2 3)
(table-column forwards "discount")                        ; => #(0.995842 0.9917013 0.9875778)
(vector-round (table-column forwards "forward") 4)        ; => #(0.0501 0.0501 0.0501)
```

#### `(forward-rates-table forwards)`
A vector of monthly forward rates as a forward curve, the table `curve-forward-rates` makes:
`months`, `discount` and `forward`.

```lisp
(table-column (forward-rates-table (vector 0.06 0.06)) "discount")   ; => #(0.99502488 0.9900745)
```

#### `(gsw-curve [:start-date d :end-date d :cache-hours h])`
The Fed's fitted curve as a table, the oldest day first, from `:start-date` to
`:end-date` (all of it, if they aren't given: it begins in 1961). The columns are the
`date`; `beta0`, `beta1`, `beta2`, `beta3`, `tau1`, and `tau2`, the six numbers of the
Svensson curve (see `svensson-zero-rates`; the betas are decimals, the taus years);
and, for each whole number of years from 1 to 30, what the curve gives there:
`zero-1` ... `zero-30` (the zero rate, continuously compounded), `par-1` ... `par-30`
(the par yield), `forward-1` ... `forward-30` (the instantaneous forward rate), and
`year-forward-1`, `-4`, and `-9` (the rate for a year that starts that many years
ahead). A number the Fed gives as `NA` is `nan`: the curve didn't reach 30 years until
the 1980s. The file is one download of the whole history, 6 MB, kept for
`:cache-hours` (12).

```lisp
(define fed (gsw-curve :start-date (date 2026 1 1)))
(table-column fed "zero-10")                  ; the 10-year zero rate, each day this year
(plot-chart (list (list "10-year zero rate" (table-column fed "date") (table-column fed "zero-10"))))
```

#### `(gsw-parameters curve [:date d])`
The six numbers of the Svensson curve on a day, as a list `(beta0 beta1 beta2 beta3
tau1 tau2)`, from the last day of `curve` (a table as `gsw-curve` makes) on or before
`:date` -- the latest, if none is given.

#### `(svensson-zero-rates parameters years)`, `(svensson-forward-rates parameters years)`
The zero rates, and the instantaneous forward rates, of the Svensson curve with
those `parameters` (a list, as `gsw-parameters` gives it), at `years` -- a vector, or one
number. The curve is

```text
z(t) = beta0 + beta1 s(t/tau1) + beta2 (s(t/tau1) - e^(-t/tau1)) + beta3 (s(t/tau2) - e^(-t/tau2)),   s(x) = (1 - e^-x) / x
f(t) = beta0 + beta1 e^(-t/tau1) + beta2 (t/tau1) e^(-t/tau1) + beta3 (t/tau2) e^(-t/tau2)
```

`beta0` is the rate for the longest maturities, `beta0 + beta1` the rate for the
shortest, and the others add a hump and a second one, where the taus say. With the
Fed's numbers for 2026-10-09, which are, as decimals, the following, the curve gives
what the Fed publishes: zero rates of 4.4929%, 4.7593%, 4.9865%, 5.2514%, and 5.6402%
at 1, 2, 5, 10, and 30 years, and forward rates of 4.8753%, 5.1860%, 5.8903%, and
4.8251% at 1, 5, 10, and 30 years:

```lisp
(define parameters (list 0.0 0.0392393143398782 0.0493949592518691 0.170123153461406
                         1.93134743096879 15.7551507296816))
(svensson-zero-rates parameters (vector 1 2 5 10 30))     ; => #(0.044928584 0.047593325 0.049864825 0.052514374 0.05640215)
(svensson-forward-rates parameters (vector 1 5 10 30))    ; => #(0.048753448 0.051859632 0.058902528 0.048251)
(svensson-zero-rates parameters 10)                       ; => 0.0525143794928097
```

#### `(gsw-zero-curve curve [:date d :months n])`
The Fed's zero curve on a day, as a table of `years` and `zero` for each month to
`:months` (360): the Svensson curve of that day's parameters. `curve` is a table as
`gsw-curve` makes, and the day the last in it on or before `:date`, the latest if
none is given. It is what `curve-forward-rates` takes, for a smooth curve of
forward rates:

```lisp
(define forwards (curve-forward-rates (gsw-zero-curve fed)))
```

#### `(sofr-forward-curve curve-rows)`
(In `lisp_rates.py`.) Pure function — no networking. A forward curve, as `curve-forward-rates`
makes (`months`, `discount`, `forward`, for 360 months), from the prices of CME 3-Month SOFR
futures. `curve-rows` is one row per future, of either kind:

- `(tastytrade-futures-curve-rows creds "SR3" [n-months])`'s rows, `(delivery-month
  symbol days-to-delivery price)`, which need only the futures' prices; or
- the first part of `sofr-calibration-data`'s answer, `(symbol start-months
  end-months rate)`, when you've fetched the options too.

A future's price is 100 less the rate it expects for its quarter, and that rate is the forward
rate of each month of the quarter. The simplifications (see `bootstrap_sofr_curve()` in
`term_structure/term_structure_model.py`): a quarter's rate is one flat rate, with no convexity
adjustment, and past the last future the curve is flat (`extend-forward-curve` carries it on).
An error if `curve-rows` is empty.

```lisp
(define sofr (sofr-forward-curve (tastytrade-futures-curve-rows creds "SR3" 40)))
(plot-chart (list (list "SOFR forward" (table-column sofr "months") (table-column sofr "forward"))))
```

`examples/sofr_floating_rate_example.lsp` uses it for a floating-rate note's coupons, period by
period.

#### `(extend-forward-curve forwards real-months longer-forwards [:blend-months n])`
The forward rates of a curve that is only known to `real-months` -- the SOFR futures'
curve, which is flat beyond the last futures contract -- carried on by those of a longer
curve. `forwards` and `longer-forwards` are forward curves (tables, as `curve-forward-rates`
makes, or vectors of the rates), as long as each other (360 months, say). The
result has `forwards` for the first `real-months`, then a straight-line change over
`:blend-months` (12) to `longer-forwards`, so that there is no jump where they meet,
and `longer-forwards` from then on: a table if `forwards` is one, and otherwise a vector.

```lisp
(define short (make-vector 360 0.04))       ; a curve known for 5 years, flat after
(define long (make-vector 360 0.05))        ; the longer curve
(define both (extend-forward-curve short 60 long :blend-months 12))
(vector-ref both 59)                        ; => 0.04
(vector-ref both 66)                        ; => 0.045
(vector-ref both 72)                        ; => 0.05
```

### Paths of rates

(In `lisp_rates.py`, over `term_structure/term_structure_model.py`.) The functions are named for what they do:
`simulate-...` makes paths (or the pieces of them), `price-...` and `path-present-values` value things on them,
`rate-curve-on-date` and `curve-par-yield` read a curve, and `calibrate-...` fits the model to option prices
("Fitting to option prices", below).

#### `(simulate-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths [:a :b :seed :tenor-years])`
Pure function — no networking. Simulates `n-paths` Monte Carlo scenarios of the model, month
by month for `horizon-years`: the market's forward curve, bent by the two random factors (stepped
by the day), as the calibration prices options. See "How to generate paths" and "What a path
is made of". `forward-rates` is the Treasury's monthly forward curve (`curve-forward-rates`). The
yield at the end of a long horizon needs the curve `:tenor-years` beyond it (a 30-year mortgage's last month
needs a curve to year 40): where the curve is shorter, it continues at its last forward rate. `sigma1`
and `sigma2` are the volatilities, `:a` (1.0) and `:b` (0.15) the mean-reversion speeds, `:tenor-years` (10)
the note whose par yield is followed, and `:seed` (an integer) makes the paths the same each time (without it
they are new). `n-paths` is rounded up to an even number: the paths come in mirror-image pairs, so that
their average is the curve's own.

Returns `(list years short-rate-paths yield-paths)`: `years` is `0, 1/12, 2/12, ...`; the others are a list
with a vector for each path: the model's short rate (the first month of its curve that month), and the par
yield of the note of `:tenor-years` that day, as the Treasury publishes it. With `sigma1` and `sigma2` of 0
they are the curve itself.

```lisp
(define paths (simulate-rate-paths curve 0.031 0.0117 5 200 :a 2.75 :seed 1))
(define ten-year-yields (third paths))          ; 200 vectors of 61 monthly yields
```

#### `(simulate-mortgage-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths mortgage-spread [:a :b :seed :tenor-years])`
Pure function — no networking. The paths of `simulate-rate-paths` (the same arguments give the same
paths), and with them a mortgage rate on each: the par yield of the note of `:tenor-years` (10) plus
`mortgage-spread`, a decimal (0.0226 is 226 basis points). Returns `(list years short-rate-paths
yield-paths mortgage-rate-paths)`. See "Mortgage rates and callable bonds".

```lisp
(define spread (- 0.0724 (curve-par-yield curve 10)))
(define mortgage-paths (fourth (simulate-mortgage-rate-paths curve 0.031 0.0117 5 2000 spread :a 2.75)))
```

#### `(simulate-rate-factors sigma1 sigma2 horizon-years n-paths [:a :b :seed])`
Pure function — no networking. The model's two random factors along `n-paths` scenarios, which are all
there is to a path besides the market's curve (`simulate-rate-paths` adds them to it): `delta-r`, how
far the short rate has strayed from where today's curve has it, and `delta-theta`, how far the long-run level
has. Both start at 0. The short rate pulls back toward `delta-theta` at speed `:a` (1.0), and `delta-theta`
toward 0, slowly, at speed `:b` (0.15); `sigma1` and `sigma2` are the sizes of their random shocks.

Returns `(list years delta-r-paths delta-theta-paths)`: the years, as for the paths, and for each factor a Lisp
LIST of vectors, one per scenario, month by month, as rates (0.01 is a point). The same arguments and `:seed`
as a `simulate-rate-paths` call give the factors of its paths.

```lisp
(define factors (simulate-rate-factors 0.019 0.012 5 200 :a 2.75 :seed 1))
(vector-ref (list-ref (second factors) 140) 36)   ; delta-r of path 140, three years in: 0.0240
```

#### `(rate-curve-on-date forward-rates months-ahead delta-r delta-theta [:a :months])`
Pure function — no networking. The model's forward curve on a date `months-ahead` from today, when its
factors have the values `delta-r` and `delta-theta` (a path's, from `simulate-rate-factors`): today's
curve for the dates from then on, bent by them. The short end follows `delta-r`, the long end `delta-theta`,
and the two meet at the speed `:a` (1.0); with both 0 it is today's curve itself. It is the curve that a
path's short rate and 10-year yield are read from: the short rate is its first month, and the yield is its par yield.

Returns a table with a row for each month, with the columns `months` (1, 2, ...: the rate is for the month that
starts `months` − 1 months after the date), `today` (the market's forward rate for that month, an annual
rate, from `forward-rates`) and `model` (the model's, on the date). `:months` is how many rows (by default, all the months
`forward-rates` has after the date; a shorter curve continues at its last rate).

```lisp
(define on-date (rate-curve-on-date curve 36 0.0240 0.0212 :a 2.75))
(plot-chart (list (list "today's" (/ (table-column on-date "months") 12.0) (table-column on-date "today"))
                  (list "on that path" (/ (table-column on-date "months") 12.0) (table-column on-date "model"))))
```

#### `(curve-par-yield forward-rates tenor-years [:start-months])`
Pure function — no networking. The par yield a curve gives a note of `tenor-years` that starts `:start-months`
(0, today) from now: the coupon, an annual rate paid every six months, that makes the note worth its face value.
`forward-rates` must reach `:start-months` plus `tenor-years` (a 30-year curve, for a note of 10 years, to month 240).
With `:start-months` 0 it is the yield the Treasury would publish if the curve were its own; later, what the curve
implies for that yield then: the first value of each path with no volatility is this, for each month.

```lisp
(curve-par-yield curve 10)                       ; 0.0498 on 2026-10-30: today's 10-year yield
(curve-par-yield curve 10 :start-months 24)      ; what the curve implies for it in two years
```

#### `(path-present-values flows rate-paths oas [first-fraction])`
The value of cash flows on each path of rates, a vector, fast enough (it is a Python builtin) to be
solved for an option-adjusted spread many times. `flows` is a list of
vectors, one for each path (a cash flow for each month), or one vector that every path has; `rate-paths` a list of vectors
of the short rate (a decimal), as `simulate-rate-paths` gives them; `oas` a decimal added to every rate. A month's cash
flow is discounted by 1 / (1 + (rate + oas) / 12) for each month up to it. `first-fraction` (1 if it is left out) is how
much of a month the first payment is away: the first month's discount is to that power, so that a first payment 35 days
after the closing date can be discounted by 35/30 of a month. The average of the values is the price on the paths; the
spread that makes it the market's price is the OAS (see "Pricing on the paths"). Because the paths start on the curve and their average discount
factor is close to the curve's, cash flows that do not depend on the path have an OAS of about 0. The structured deals use it for
their tranches, whose cash flows do depend on the path, through prepayments (see "Option-adjusted spread and effective
duration" in [lisp_cmo_manual.md](lisp_cmo_manual.md)).

```lisp
(path-present-values (vector 1.0 1.0) (list (vector 0.0 0.0) (vector 0.12 0.12)) 0.0)    ; => #(2.0 1.970395059307911)
(path-present-values (list (vector 100.0 100.0) (vector 50.0 150.0)) (list (vector 0.03 0.03) (vector 0.06 0.06)) 0.01)    ; => #(199.00442599971302 197.9752191201696)
```

#### `(price-callable-bond forward-rates sigma1 sigma2 years coupon call-years call-price oas [:a :b :n-paths :seed])`
Pure function — no networking. The price, per 100 of face, of a bond of `years` paying `coupon` (a
decimal, every six months) that its issuer may call at `call-price` at `call-years`, on the short-rate
paths of `simulate-rate-paths` with `oas` (a decimal) added to every rate. On each path the issuer
calls if the bond's remaining payments are worth more than `call-price` then, so the holder gets the
smaller of the two. `:n-paths` (2000), `:seed` (123), `:a` (1.0), `:b` (0.15).

Two simplifications: one call date, where a real callable bond can usually be called on any coupon
date after the first; and the issuer decides on each path knowing that path's later rates, which
makes the call worth a little more than it is. A call price no one would pay (`100000`) gives the
bond with no call.

```lisp
(price-callable-bond curve 0.031 0.0117 10 0.05 3 100 0.0 :a 2.75 :seed 1)        ; 97.45
(price-callable-bond curve 0.031 0.0117 10 0.05 3 100000 0.0 :a 2.75 :seed 1)     ; 100.75: no call
```

### Fitting to option prices

See "How implied volatility sets the numbers", in Part 2, for what these do.

#### `(calibrate-rate-model forward-rates sofr-option-rows note-option-rows [:fit :sigma1 :sigma2 :a :sofr-paths :note-paths :seed :ctd-maturity :ctd-coupon :min-days :moneyness-window :sofr-min-months])`
Pure function — no networking. Fits the model to SOFR futures options and to options on the 10-year note
future together, both priced on the paths `simulate-rate-paths` draws. `forward-rates` is the Treasury's
curve (`curve-forward-rates`), which the paths are centered on; `sofr-option-rows` are the options of
`sofr-calibration-data` (its `cdr`), and `note-option-rows` those of `note-option-rows`. `:fit` is a list of `a`,
`sigma1` and `sigma2` (by default all three); the others keep the values of `:a`, `:sigma1` and `:sigma2` (1.0,
0.01, 0.01), which are also where the search of those fitted starts. `:sofr-paths` (2000) and `:note-paths` (10000)
are the numbers of paths for each kind. The error is that of `calibrate-to-note-options` for the notes, and the same
kind of relative volatility error for the SOFR options, the two put together as the square root of the sum of their
squares (so that neither kind is ignored).

SOFR options with fewer than `:sofr-min-months` (3) months to expiry are left out, for the reason in "Fitting
the model to option prices". The other options are as for `calibrate-to-note-options`.

Returns an association list: `((a . 2.75) (sigma1 . 0.031) (sigma2 . 0.0117) (sofr-error . 0.090) (note-error .
0.028) (error . 0.094) (sofr-options-used . 20) (note-options-used . 96) (evaluations . 40))`. Read a value with
`(cdr (assoc 'sigma2 fit))`.

```lisp
(define sofr-data (sofr-calibration-data creds 40 8 3))
(define fit (calibrate-rate-model curve (cdr sofr-data) note-rows :fit '(sigma1 sigma2) :a 2.75))
```

#### `(calibrate-to-note-options forward-rates option-rows [:fit :sigma1 :sigma2 :a :b :n-paths :seed :ctd-maturity :ctd-coupon :min-days :moneyness-window])`
Pure function — no networking. Fits the model to the options on the 10-year note future by finding the
parameters for which its Monte Carlo prices are nearest the market's (the root mean square of the options'
relative volatility errors; a Nelder–Mead search in the parameters' logarithms). `forward-rates` is the
Treasury's curve and `option-rows` those of `note-option-rows`. `:fit` is a list of the parameters to fit — any of
`a`, `b`, `sigma1` and `sigma2`; by default `'(sigma2)`. The others keep the values given by `:a`, `:b`, `:sigma1` and
`:sigma2` (1.0, 0.15, 0.01, 0.01), which are also where the search of those that are fitted starts. `:n-paths` (10000)
paths, `:seed` (42), `:ctd-maturity` (6.75) and `:ctd-coupon` (by default the coupon that makes the note a par bond
on the curve) are as for `note-option-comparison`. `:min-days` (10) and `:moneyness-window` (2) say which options
are used.

Returns an association list: `((a . 1.0) (b . 0.15) (sigma1 . 0.01) (sigma2 . 0.0134) (error . 0.034)
(options-used . 24) (evaluations . 36))`. Read a value with `(cdr (assoc 'sigma2 fit))`.

The same random numbers are priced at every set of parameters, so the Monte Carlo noise is the same at each and
the error is a smooth function of the parameters; the price is that the fit carries the noise of those numbers.
More paths make it smaller (as the square root of their number). A change of `:seed` shows how much is left.

```lisp
(define fit (calibrate-to-note-options curve rows))
(cdr (assoc 'sigma2 fit))                          ; 0.0134, on 2026-10-15
```

The ZN options reach only a few months, so `b` — how slowly the level reverts — cannot be told from them, and
`sigma1` only a little; fit `'(sigma2)`, or fit the others together with SOFR options (`calibrate-rate-model`).

#### `(note-option-comparison forward-rates option-rows sigma1 sigma2 [:a :b :n-paths :seed :ctd-maturity :ctd-coupon])`
Pure function — no networking. The model's price of each option on the 10-year note future next to the market's, as
a table, one row per option. `forward-rates` is a vector of monthly forward rates — the Treasury's.
`option-rows` are those of `note-option-rows`. The model's parameters are `a` (`:a`, 1.0) and `b` (`:b`, 0.15), the
speeds at which the short rate and the level revert, and the volatilities `sigma1` and `sigma2` — 0.01 each is a
start. `:n-paths` (10000) paths, `:seed` (42), `:ctd-maturity` (6.75), `:ctd-coupon` (by default the coupon that
makes the note a par bond on the curve).

The columns: `type`, `strike`, `days`, `futures-price`, `market-price`, `model-price`; `market-vol` and
`model-vol`, the volatility each price implies, in points of the future's price a year; `market-yield-vol` and
`model-yield-vol`, the same as a volatility of the *yield* of the note, in basis points a year (the price volatility
over the price and the note's duration); `duration`; and `error`, `model-vol / market-vol - 1`.

```lisp
(define comparison (note-option-comparison curve rows 0.01 0.0134))
(display-table comparison)
```

#### `(note-option-rows chain [:day d :min-days n :max-days n])`
Shapes a chain of options, as `(tastytrade-option-chain creds "ZN" months strikes)` makes it, into the rows the
functions above read: each is `(type strike days futures-price market-price)` — the type `"call"` or `"put"`, the
strike, the days from `:day` (today) until the option expires, the price of the future the option is on, and the middle of
the option's bid and ask. Options without a bid or an ask are left out, and those with fewer than `:min-days` (7) or
more than `:max-days` (400) days to expiry (the last few days are priced mostly on the next few days' news). A chain
has options on more than one future (the December options on the December future, the later ones on March's), and
each row carries the price of its own. In `note_options.lsp`.

```lisp
(define chain (tastytrade-option-chain creds "ZN" 12 12))
(define rows (note-option-rows chain))
```

#### `(sofr-calibration-data credentials-path [n-futures n-underlyings n-strikes])`
(In `lisp_rates.py`.) Fetches a SOFR futures curve and a spread of options on SOFR futures in one
tastytrade session (`term_structure/sofr_market_data.py`): the options are spread across every
quarter that has a listed chain, not just the nearest few, so that the model's volatilities can be
told apart. `n-futures`/`n-underlyings`/`n-strikes` default to `40`/`10`/`3`.

Returns `(cons curve-futures-rows options-rows)`:
- `curve-futures-rows`: one row per SR3 contract month, `(symbol start-months end-months rate)`,
  for `sofr-forward-curve`.
- `options-rows`: up to `n-underlyings * n-strikes * 2` near-the-money calls and puts, `(type strike
  expiry-months quarter-start-months quarter-end-months market-price future-price)`, the last being
  the price of the SOFR future the option is on, for `calibrate-rate-model`.

Needs the `tastytrade` package, a tastytrade account, and a credentials
JSON file (see `tasty_api/README.md`).

```lisp
(define data (sofr-calibration-data creds 40 8 3))
(define sofr-curve (sofr-forward-curve (car data)))
(define options-rows (cdr data))
```
