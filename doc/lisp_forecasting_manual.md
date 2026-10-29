# morris-lisp — Forecasting

Forecasting sites such as [Good Judgment Open](https://www.gjopen.com/) and the prediction markets ask two kinds of question about
politics and the economy. One is "**will this happen before a date?**": will the Fed cut rates by March, will a ceasefire be signed by June.
The other is "**in which range will this number be?**": what will the CPI be in December, where will the S&P 500 close the year. A forecast
is a chance for each answer, and it is scored, when the question is decided, by how far those chances were from what happened.

`lib/forecasting.lsp` has the arithmetic for both kinds: the chance of each range from a distribution of the number, how a "before the date"
chance falls as the weeks go by without the thing happening, combining forecasts made different ways, and scoring them. The functions are
loaded when you call one of them (see `lazy-load`), so there is nothing to load.

There are other documents. The **language manual**, [lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the syntax and
the general builtins. The **library manual**, [lisp_library_reference.md](lisp_library_reference.md), covers getting data (FRED, BLS, BEA,
tastytrade and others), models, and investments. The **example programs**, [lisp_example_programs.md](lisp_example_programs.md), say how
whole programs are put together. **This one is about forecasting questions.**

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [How a forecast is scored, and what follows from it](#how-a-forecast-is-scored-and-what-follows-from-it)
- [A way of working](#a-way-of-working)
- [Questions about a number](#questions-about-a-number)
  - [Bins, and their edges](#bins-and-their-edges)
  - [A forecast and its usual error](#a-forecast-and-its-usual-error)
  - [A price on a date](#a-price-on-a-date)
- [Will it happen before the date?](#will-it-happen-before-the-date)
- [Combining forecasts](#combining-forecasts)
- [Scoring, and keeping a record](#scoring-and-keeping-a-record)
- [Where the numbers come from](#where-the-numbers-come-from)

## How a forecast is scored, and what follows from it

Good Judgment Open scores a forecast with the **Brier score**: for each answer, the square of how far its chance was from what happened (1
for the answer that came true, 0 for the others), added up. 0 is perfect and 2 is as wrong as can be. A forecast of 70% for "yes" on a
question that comes out yes scores 0.3² + 0.3² = 0.18; one of 50% scores 0.5, whatever happens. Lower is better.

Four things follow from the way it is used:

- **Every day counts.** The score of a question is the average of the scores of each day it was open, and on each day the forecast is
  the last one you made. A good first forecast that is never changed goes stale. Coming back after news, and every week or two in any
  case, is worth as much as being right the first time.
- **You are compared with the crowd.** Beside your score is the median forecaster's. Agreeing with the crowd scores the same as the crowd;
  to do better you have to be earlier than it, or bolder than it when the evidence is good.
- **"Before the date" questions should drift toward no.** If nothing happens, the chance that something happens in the time that is left
  shrinks as the time does (see [Will it happen before the date?](#will-it-happen-before-the-date)). Many forecasters leave their
  forecast where it was; following the calendar down is one of the easiest ways to beat them.
- **Being sure costs a lot when you're wrong.** 100% on an answer that doesn't happen scores 2. But on something that really is close to
  certain, 3% instead of 10% for the other answer saves a little on each of many questions. Don't use 0 or 100, and don't stay between 10
  and 90 out of timidity.

Questions whose answers are ranges in order (the CPI below 2.5%, 2.5 to 3%, ...) are scored so that being one range off costs less than
being three ranges off: see `ordered-brier-score`, below.

## A way of working

This is the method of the "superforecasters" that Philip Tetlock found in the forecasting tournaments that Good Judgment came from (his
book *Superforecasting* tells the story):

1. **Read the question's rules for deciding it,** word for word, and the source it names. Whether a bill was "passed" or "signed", which
   release of a figure counts, whether it is rounded, and what time zone a date is in decide many questions.
2. **Start from a base rate** (the "outside view"): how often things of this kind happen. How often does a sitting leader lose an
   election? How often does a bill at this stage become law within six months? How often has the Fed moved when futures gave it a 20%
   chance?
3. **Then the particulars** (the "inside view"): what is different about this case. Move from the base rate by a little, not a lot.
4. **The status quo is a strong favorite.** Most "will it happen by a date" questions are decided no: things take longer than announced,
   and talks drag on. A crowd tends to overrate the dramatic answer just after it has been in the news.
5. **Break a question into steps** whose chances are easier to think about: the chance a bill passes is the chance it gets a vote, times
   the chance it passes if it does, times the chance it's signed.
6. **Make the forecast more than one way** (from the base rate, from a market, from a model) and average them (`combine-forecasts`).
7. **Keep a record** of each forecast and why, and check later how well calibrated you were (`calibration-table`).

For the economic questions, markets have usually done much of the work already: options give the chances of each range of a price, and
futures the chances of each Fed decision. The functions below turn those, or a forecast and its usual error, into the chances of the
question's bins.

## Questions about a number

### Bins, and their edges

The ranges a question offers are given here by their **edges**: the edges `(2.0 2.5 3.0)` make four bins, below 2.0, from 2.0 to 2.5, from
2.5 to 3.0, and 3.0 or more. Each of the `...-bins` functions takes the edges and answers with a list of the bins' chances, one more than
there are edges, adding up to 1.

#### `(bin-probabilities edges cdf)`
The chance of each bin, for any distribution: `(cdf x)` is the chance that the number is below `x`. The other functions are this, with a
cdf made for you. For a number equally likely to be anywhere from 0 to 3:

```lisp
(bin-probabilities '(1 2) (lambda (x) (/ x 3)))      ; => (0.33333333 0.33333333 0.33333333)
```

#### `(bin-table edges chances)`
The bins and their chances as a table, to look at: a label for each bin, and its chance in percent, to a tenth.

```lisp
(table-column (bin-table '(2.0 2.5) '(0.25 0.5 0.25)) "bin")     ; => #("below 2" "2 to 2.5" "2.5 or more")
(table-column (bin-table '(2.0 2.5) '(0.25 0.5 0.25)) "percent") ; => #(25.0 50.0 25.0)
```

**Figures that are rounded.** The CPI, the unemployment rate and payrolls are published rounded: a CPI of 2.84% is published as 2.8%. A
question's bin "2.8% to 2.9%, inclusive", for a figure rounded to a tenth, takes in everything from 2.75 to 2.95. So give the edges halfway
between the published values -- `(2.75 2.85 2.95 3.05)` for the bins "2.7 or less", "2.8", "2.9", "3.0" and "3.1 or more" -- and read
the question's rules on which bin a value on an edge is in.

### A forecast and its usual error

For a figure that is about to be published -- the CPI, payrolls, GDP -- start from the forecasts that are already made: the economists'
consensus, and the Federal Reserve banks' nowcasts (the Cleveland Fed's of inflation, the Atlanta Fed's GDPNow). How far from them the
figure lands is the question; the history of how far it has landed before answers it.

#### `(normal-bins edges mean stdev)`
The chance of each bin if the number is the forecast `mean`, off by a normally distributed error whose standard deviation is `stdev`. The
consensus is 2.9% for the CPI, and the surprises in the past have had a standard deviation of 0.1:

```lisp
(normal-bins '(2.75 2.85 2.95 3.05) 2.9 0.1)   ; => (0.066807201 0.24173034 0.38292492 0.24173034 0.066807201)
```

which, with `bin-table`, is

```text
bin           percent
------------  -------
below 2.75        6.7
2.75 to 2.85     24.2
2.85 to 2.95     38.3
2.95 to 3.05     24.2
3.05 or more      6.7
```

#### `(empirical-bins edges center errors)`
The chance of each bin if the number is `center` plus one of the past `errors`, each as likely as any other. The errors are the actual
figures less the forecasts made just before them, from as many past releases as you have; they are used just as they were, with no normal
curve assumed, so if the surprises have tended to be on one side, or now and then large, so is this forecast. Twelve months of surprises:

```lisp
(define surprises '(-0.2 -0.1 -0.1 0 0 0 0 0.1 0.1 0.1 0.2 0.3))
(empirical-bins '(2.75 2.85 2.95 3.05) 2.9 surprises)   ; => (0.083333333 0.16666667 0.33333333 0.25 0.16666667)
```

A dozen errors give chances only in twelfths; use as many years as the figure has been measured the same way. Rounded errors, as here, put
the forecast plus an error right on an edge; such a value counts in the bin above the edge.

### A price on a date

A question about where a price will be on a date -- a stock index, oil, a currency, a Treasury yield -- is a question the options market
answers every day, with money on it.

#### `(lognormal-bins edges price volatility years [:rate r])`
The chance of each bin for the price `years` from now, if it moves the way the Black-Scholes model of option prices assumes: its logarithm
normally distributed, spread by `volatility` (0.16 for 16% a year), and expected to grow at `rate` (an interest rate less a dividend yield;
for a few months, 0 is near enough). Take the volatility from options that expire close to the date the question is decided: the implied
volatility of those near the money, which tastytrade's option chain has. The S&P 500 at 6,700 now, in three months, with a volatility of
16%:

```lisp
(lognormal-bins '(6000 6500 7000) 6700 0.16 0.25)   ; => (0.090228263 0.27714558 0.35420318 0.27842297)
```

A 9% chance it is below 6,000, a 28% chance it is above 7,000.

#### `(call-price-bins edges strikes call-prices [:discount d])`
The chance of each bin for a price on the day options on it expire, read from the prices of the calls themselves, so that the market's
"smile" -- its larger fear of a crash than of a jump -- is in the chances, which a single volatility leaves out. A call at strike K pays
what the price ends above K, so a call a dollar higher in strike is worth a dollar times the chance that the price ends above K less: the
chance is the slope of the call prices as the strike rises. `strikes` rise, `call-prices` are the middle of the bid and the ask, and
`discount` is what a dollar paid on the day they expire is worth now (0.99 for a year at 1%). Strikes close together around the edges give
the best answer.

Calls priced by Black-Scholes at the volatility above give back about the same chances, as they should:

```lisp
(define strikes '(5900 6000 6100 6400 6500 6600 6900 7000 7100))
(define calls (vector->list (bsm-price "call" 6700 (list->vector strikes) 0.25 0 0.16)))
(call-price-bins '(6000 6500 7000) strikes calls)   ; => (0.091705556 0.27626693 0.35241877 0.27960874)
```

With real prices, the chance below 6,000 comes out higher than `lognormal-bins` gives: that is the smile. Quotes that are stale or wide
can make the slope go the wrong way between two strikes; such a chance is taken as 0, and the bins still add up to 1.

## Will it happen before the date?

#### `(probability-remaining chance days-total days-left)`
If a thing had the given `chance` of happening in all of `days-total` days, and is as likely on any day as on another, the chance that it
happens in the `days-left` still to go. A 30% chance over six months is a 16% chance over the last three, if the first three pass quietly:

```lisp
(probability-remaining 0.3 182 91)      ; => 0.16333997
```

The chance of it not happening is what shrinks by a power: 70% of not happening in 182 days is 0.7^(91/182) = 84% of not happening in 91.
That a thing is as likely on one day as another is seldom quite true -- a law is more likely to pass just before a recess, a ceasefire
after a round of talks that are on the calendar -- so use this as the drift to follow when there is no news, and move off it when there
is.

#### `(decay-schedule chance start-date end-date [:every days])`
What to forecast each week (or every `days` days) from `start-date` until `end-date`, if the thing has the given `chance` of happening in
all that time and hasn't happened yet: a table of the date, the days left, and the chance in percent.

```lisp
(table-column (decay-schedule 0.3 (date 2026 11 1) (date 2027 5 1) :every 30) "percent")   ; => #(30.0 25.7 21.2 16.4 11.3 5.9 0.2)
```

The whole table, with `display-table`:

```text
date        days left  percent
----------  ---------  -------
2026-11-01        181     30.0
2026-12-01        151     25.7
2026-12-31        121     21.2
2027-01-30         91     16.4
2027-03-01         61     11.3
2027-03-31         31      5.9
2027-04-30          1      0.2
```

## Combining forecasts

#### `(combine-forecasts forecasts [:weights weights])`
The average of several forecasts of one question, each a list of chances (one for each answer), weighted by `weights` if they're given
(they needn't add up to 1). A forecast from a base rate, one from a prediction market, and one of your own:

```lisp
(combine-forecasts '((0.2 0.8) (0.35 0.65) (0.3 0.7)))                       ; => (0.28333333 0.71666667)
(combine-forecasts '((0.2 0.8) (0.35 0.65) (0.3 0.7)) :weights '(2 1 1))     ; => (0.2625 0.7375)
```

Forecasts made different ways are wrong in different ways, and their average is usually better than any of them -- the reason Good
Judgment's own forecasts are averages.

#### `(extremize chances power)`
The forecast made bolder: each chance is raised to `power`, and they are scaled to add up to 1 again. A power above 1 moves the forecast
toward its favorite; below 1, toward even.

```lisp
(extremize '(0.7 0.3) 2)              ; => (0.84482759 0.15517241)
(extremize '(0.5 0.3 0.2) 1.5)        ; => (0.58216021 0.27056361 0.14727618)
```

An average of the forecasts of people who each know a different part of the story is too timid: none of them knew all of it, and each
held back for what they didn't know. The tournaments found that a power of about 1.5 to 2.5 corrects it. Don't extremize an average of
forecasts that all came from the same information, such as a market and someone who read its price.

## Scoring, and keeping a record

#### `(brier-score chances outcome)`
The Brier score of a forecast: `chances` has one for each answer, and `outcome` is the number of the answer that happened, 0 for the first.

```lisp
(brier-score '(0.7 0.3) 0)            ; => 0.18
(brier-score '(0.7 0.2 0.1) 2)        ; => 1.34
```

#### `(ordered-brier-score chances outcome)`
The score of a forecast whose answers are bins in order, as Good Judgment Open scores such questions: at each place between two bins, the
bins are split into those below and those above it, the forecast is scored as the yes-or-no question of which side the number is on, and
the score is the average of those. The number ended in the first of three bins; the forecast that put most of its chance in the next bin
does better than the one that put it in the last, though the plain Brier score can't tell them apart:

```lisp
(ordered-brier-score '(0 0.7 0.3) 0)  ; => 1.09
(ordered-brier-score '(0 0.3 0.7) 0)  ; => 1.49
(brier-score '(0 0.7 0.3) 0)          ; => 1.58
(brier-score '(0 0.3 0.7) 0)          ; => 1.58
```

So on these questions, spread the chance over the bins around the one you favor, not all into it.

#### `(calibration-table chances outcomes [:bins n])`
How well calibrated a record of yes-or-no forecasts is. `chances` are the chances you gave for yes, and `outcomes` are 1 where it happened
and 0 where it didn't. The forecasts are put in `n` bins by their chance (10, unless you say: 0 to 10%, 10 to 20%, ...), and for each bin
with any forecasts the table has how many there were, their average chance, and the percent of them that happened, both in percent.

```lisp
(define given    '(0.05 0.1 0.15 0.3 0.35 0.6 0.7 0.75 0.9 0.95))
(define happened '(0    0   1    0   1    1   0   1    1   1))
(table-column (calibration-table given happened :bins 5) "percent happened")    ; => #(33.3 50.0 66.7 100.0)
```

The whole table, with `display-table`:

```text
forecast    count  average forecast  percent happened
----------  -----  ----------------  ----------------
0 to 20%        3              10.0              33.3
20 to 40%       2              32.5              50.0
60 to 80%       3              68.3              66.7
80 to 100%      2              92.5             100.0
```

Well calibrated, the last two columns are close; here, the forecasts at 10% came true a third of the time. It takes many forecasts --
dozens in each bin -- before a difference means much; with a few, as here, it is mostly luck. Keep the record in a table (a CSV file, or
a SQLite database, as in "SQLite" in the [library manual](lisp_library_reference.md#sqlite)), with the question, the date, the chance,
and why, and add the outcome when the question is decided.

## Where the numbers come from

The library manual has the functions that get these:

- **Economic figures and their history**, for `empirical-bins` and `normal-bins`: [FRED](lisp_library_reference.md#fred-federal-reserve-bank-of-st-louis-data)
  for most series, and [BLS](lisp_library_reference.md#bls-data) and [BEA](lisp_library_reference.md#bea-data) for the CPI, jobs, and
  GDP at the source.
- **Option prices and implied volatilities**, for `lognormal-bins` and `call-price-bins`:
  [tastytrade](lisp_library_reference.md#tastytrade-real-broker-data). Options on futures (oil, gold, the 10-year note) are there too.
- **Interest rates**: [Yield curves](lisp_library_reference.md#yield-curves-the-treasurys-and-the-feds) for the Treasury's curve, and the
  SOFR futures in [Interest rate paths](lisp_library_reference.md#interest-rate-paths-the-two-factor-model) for what the market expects
  of the Fed.

And elsewhere, to read in a browser or with `http-get-json`:

- **The consensus forecasts and nowcasts** for each release: the Cleveland Fed's inflation nowcast, the Atlanta Fed's GDPNow, the New York
  Fed's Staff Nowcast.
- **What the market expects the Fed to do**: CME's FedWatch, from the fed funds futures.
- **Prediction markets** -- Kalshi and Polymarket -- which list many of the same questions, the economic ones especially. Their prices are
  a strong place to start, less a little for the fees and for long shots, which they tend to price too high.
- **For political questions**: polling averages and the election models built on them (allowing that polls miss by several points more
  often than their margins of error say), the calendars of legislatures and courts, and the official texts -- a court's docket, the
  Federal Register -- which often settle a question before the news reports it.
