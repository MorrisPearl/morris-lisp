# morris-lisp — Macroeconomic Models

What happens to the US economy when the price of oil jumps? GDP, inflation, wages and the Fed's rate all respond, and each response feeds
the others: higher prices cut what wages buy, which cuts spending, which the Fed weighs against the higher inflation. A **macroeconomic
model** writes those links down as a few equations, so that the whole chain can be followed quarter by quarter, and so that you can ask
"what if?" by changing one link and watching what the rest does.

This document is about such models, built and run with [Dynare](https://www.dynare.org), a free program that economists at central banks
and universities use for exactly this. It assumes no econometrics: each idea is explained where it first comes up. `lib/macro_models.lsp`
has the functions; they are loaded when you call one of them (see `lazy-load`), so there is nothing to load.

There are other documents. The **language manual**, [lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the syntax and
the general builtins. The **library manual**, [lisp_library_reference.md](lisp_library_reference.md), covers getting data (FRED, BLS, BEA
and others), statistical models, and investments. The **example programs**, [lisp_example_programs.md](lisp_example_programs.md), say how
whole programs are put together. The **CMO manual**, [lisp_cmo_manual.md](lisp_cmo_manual.md), the **forecasting manual**,
[lisp_forecasting_manual.md](lisp_forecasting_manual.md), and the **paths manual**, [lisp_paths_manual.md](lisp_paths_manual.md), cover
structured deals, forecasting questions, and simulated paths of rates and prices. **This one is about models of the whole economy.**

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [The short version](#the-short-version)
- [What a model like this is](#what-a-model-like-this-is)
  - [Shocks, and the economy's responses to them](#shocks-and-the-economys-responses-to-them)
  - [What Dynare does](#what-dynare-does)
- [The oil model](#the-oil-model)
  - [Who is in it](#who-is-in-it)
  - [How an oil shock travels through it](#how-an-oil-shock-travels-through-it)
  - [The parameters](#the-parameters)
- [Running it](#running-it)
  - [Reading the results](#reading-the-results)
  - [Ten quarters or twenty](#ten-quarters-or-twenty)
- [Scenarios: what if?](#scenarios-what-if)
  - [Scenarios worth trying](#scenarios-worth-trying)
  - [Other kinds of surprise](#other-kinds-of-surprise)
- [What "estimated" means](#what-estimated-means)
  - [The idea](#the-idea)
  - [Priors and posteriors](#priors-and-posteriors)
  - [How Dynare does it](#how-dynare-does-it)
  - [The data](#the-data)
  - [Estimating the model](#estimating-the-model)
  - [Reading the estimates](#reading-the-estimates)
  - [Scenarios from the estimate](#scenarios-from-the-estimate)
- [The 1970s and the 2000s](#the-1970s-and-the-2000s)
- [What the model leaves out](#what-the-model-leaves-out)
- [The stock market crash model](#the-stock-market-crash-model)
  - [Who is in it, and the financial accelerator](#who-is-in-it-and-the-financial-accelerator)
  - [Running it](#running-it-1)
  - [Estimating it](#estimating-it)
  - [What this model leaves out](#what-this-model-leaves-out)
- [Wealth taxes](#wealth-taxes)
- [Reference](#reference)
  - [Setting up Dynare](#setting-up-dynare)
  - [The functions](#the-functions)
  - [The model files](#the-model-files)

## The short version

The notebook `lisp_interp/notebooks/oil_shock_model.ipynb` goes through these steps, a cell each.

```lisp
; What a 10% rise in the real price of oil does, with the model's parameters as chosen by hand
(define base (oil-model))
(plot-oil-shock base :rise 10)
(oil-shock-responses base :rise 10)          ; the same, as a table: a row a quarter

; What if real wages were slow to fall, as in the 1970s?
(define rigid (oil-model :parameters '((gamma . 0.9))))
(plot-oil-shock (list (list "wages adjust" base) (list "wages rigid" rigid)) :rise 10)

; The parameters estimated from US data, 1985 to 2008 (five minutes or so)
(define estimate (oil-model-estimate creds))
(show-oil-estimates estimate)
(plot-oil-shock estimate :rise 10)            ; with a band for how unsure the estimate is

; A scenario that starts from the estimate: what if the Fed looked only at headline inflation?
(plot-oil-shock (list (list "as estimated" estimate)
                      (list "Fed watches headline inflation" (oil-model :from estimate :parameters '((core_weight . 0)))))
                :rise 10)
```

## What a model like this is

### Shocks, and the economy's responses to them

Picture the economy in normal times: GDP growing at its usual pace, inflation at its usual rate, the Fed's rate where it usually is.
Economists call this the **steady state**. Every variable in the model is measured as a difference from it: "GDP is −0.2" means GDP is
0.2% below where it would have been.

Then something unexpected happens: OPEC cuts output and the price of oil jumps; a new technology makes workers more productive; the Fed
raises its rate by surprise. Each is a **shock** (or a surprise). The model says how everything else moves, quarter by quarter, until the
economy settles back to normal. That path is an **impulse response**: the response to an impulse. It is the main thing these models
produce, and it answers "what is the effect of X?" directly: the effect of an oil shock *is* the economy's response to it.

The economy settles back because the shocks fade. The price of oil, once up, comes down slowly (how slowly is a parameter, `rho_s`); a
surprise in the Fed's rate is undone by the Fed itself. A model like this is about the ups and downs around normal over a few years, not
about where the economy will be in twenty years.

### What Dynare does

Writing the equations down is the economist's job. The hard part is that everyone in them **looks ahead**: a firm setting its price
today thinks about its costs next year; households decide how much to spend by what they expect to earn. So what happens today depends
on what will happen tomorrow, which depends on what happens today. Dynare solves this: it finds the way the economy must move so that
what people expect is, on average, what then happens (economists call this **rational expectations**). You give it the equations; it
gives back the responses.

Dynare does three things this document uses:

- **Solving**: turning the equations into rules that say where each variable goes next quarter, given where things are now and the
  shocks that arrive. Dynare works with a *linear* version of the equations, accurate for the ordinary ups and downs of the economy. One
  consequence: a shock twice as big has responses exactly twice as big. That is why `:rise` can be any number.
- **Simulating**: following the economy after each kind of shock (the impulse responses), and working out how much of each
  variable's ups and downs comes from each kind of shock (the *variance decomposition*).
- **Estimating**: finding the values of the parameters that make the model behave most like the US economy did. See [What "estimated"
  means](#what-estimated-means).

Dynare runs inside GNU Octave, a free numerical language (MATLAB's open-source cousin). You don't need to know Octave: `dynare-run` runs
it, and returns what Dynare found as Lisp tables. See [Setting up Dynare](#setting-up-dynare) for installing them.

## The oil model

The model is a small "New Keynesian" model, the kind central banks use as the core of bigger ones, with oil added as Olivier Blanchard
and Jordi Galí did in a well-known paper, *The Macroeconomic Effects of Oil Price Shocks: Why are the 2000s so Different from the
1970s?* (2007). It is small enough that every equation can be read as a sentence; they are in `lisp_interp/dynare/oil_model.inc`, with
the sentences beside them.

### Who is in it

- **Households** buy domestic goods and oil (gasoline, heating oil), work, and save or borrow at the Fed's rate. When the real interest
  rate (the Fed's rate less inflation) is high, they spend less now and more later.
- **Firms** make domestic goods from labor and oil. They set their prices, but change them only now and then (each quarter, a firm has a
  chance `1 - theta` of being able to). So when costs rise, prices rise only gradually, and inflation lasts a while.
- **Workers** want a real wage that matches how much they work and how well off they are. But real wages may be slow to adjust: the
  parameter `gamma` says how much of last quarter's wage carries over. With `gamma` near 1, workers resist a cut in what their pay
  buys, as they did in the 1970s when many contracts were indexed to prices.
- **The Fed** follows a **Taylor rule**: it raises its rate when inflation is above normal (by `phi_pi` points for each point of
  inflation) and when GDP is above normal (by `phi_y`), moving a little each quarter (`rho_i`). The inflation it watches is a mix of
  **core** inflation (without oil and food) and **headline** inflation (everything), with `core_weight` on core.
- **Oil** comes from abroad, and its price, compared with the price of domestic goods, moves on its own: the oil shock.

### How an oil shock travels through it

When the real price of oil rises 10%:

1. **Headline inflation jumps at once**: oil is 2% of what households buy (`chi`), so prices rise about 0.2%, or 0.8 points of
   inflation at an annual rate, in that quarter. That part is over in a quarter: the price of oil stays high, but it doesn't keep rising.
2. **Firms' costs rise**: oil is 2% of the cost of making things (`alpha`), and, if real wages don't fall, labor costs in domestic goods
   rise too (pay must buy the dearer oil). Firms that can change their price raise it: **core inflation** rises, a little and for longer.
   How much depends on how sticky prices are (`theta`) and how rigid real wages are (`gamma`): with rigid wages, the cost shock is bigger
   and lasts longer.
3. **Households are poorer**: their pay buys less, and the country must send more goods abroad to pay for its oil. **Consumption falls.**
4. **The Fed raises its rate** in response to the higher inflation; how much depends on `phi_pi` and on whether it looks through the
   jump in headline inflation (`core_weight` near 1) or responds to it (`core_weight` near 0). A higher rate cuts spending further.
5. **Hours and GDP**: firms use less oil, and less labor if demand falls. But the goods sent abroad to pay for the oil count in GDP, so
   GDP can fall less than consumption, or even rise a little, while households are worse off. **GDP measures what is made, not how well
   off people are**; for that, look at consumption and the real wage.

Each of these is a channel you can turn up or down by changing a parameter, which is what [scenarios](#scenarios-what-if) are for.

### The parameters

The model's parameters, the values it starts with ("calibrated": chosen by hand from what economists usually find), and what they
mean. Quarterly rates are per quarter.

| Parameter | Starts at | What it is |
|---|---|---|
| `beta` | 0.99 | how much households value next quarter compared with this one (a real interest rate of 4% a year) |
| `sigma` | 1 | how much households dislike uneven spending; `1 / sigma` is how much spending moves with the real interest rate |
| `phi` | 1 | how fast the wish not to work grows with hours |
| `alpha` | 0.02 | oil's share of the cost of making domestic goods |
| `chi` | 0.02 | oil's share of what households buy |
| `markup` | 1.2 | firms' prices over their costs, in normal times |
| `theta` | 0.75 | the chance a firm can't change its price in a quarter (0.75: prices last a year, on average) |
| `gamma` | 0.5 | real wage rigidity: 0, wages adjust at once; near 1, they hardly adjust |
| `phi_pi` | 1.5 | the Fed's rate rise for a point of inflation (more than 1, so the real rate rises) |
| `phi_y` | 0.125 | the Fed's rate rise for a percent of GDP above normal |
| `rho_i` | 0.8 | how slowly the Fed moves its rate toward what its rule says |
| `core_weight` | 0.5 | the weight the Fed puts on core inflation (the rest is on headline) |
| `rho_s` | 0.95 | how long an oil price change lasts: 0.95 keeps 95% of it each quarter, so half is gone after 13 quarters |
| `rho_a`, `rho_z` | 0.95, 0.8 | how long a change in productivity, and in demand, lasts |
| `sigma_oil` | 12 | the typical size of an oil price surprise, in percent (and `sigma_a`, `sigma_z`, `sigma_i`, `sigma_p`, `sigma_w` for the others) |

## Running it

`(oil-model)` runs the model with these parameters and returns what Dynare found (a hash table; see [The functions](#the-functions)).
It takes a second or two. `oil-shock-responses` turns it into a table of what happens when the price of oil rises by `:rise` percent,
and `plot-oil-shock` draws that table as charts, a panel for GDP, consumption, headline and core inflation, the Fed's rate and the real
wage:

```lisp
(define base (oil-model))
(oil-shock-responses base :rise 10)
(plot-oil-shock base :rise 10)
```

### Reading the results

Each row of the table is a quarter after the rise; quarter 1 is the quarter it happens in. The columns:

- **GDP, consumption, hours, real wage**: percent difference from normal. −0.3 is 0.3% lower than it would have been.
- **headline inflation, core inflation, Fed rate**: percentage points *a year* above normal, the way they are reported. 0.8 means
  inflation is 0.8 points higher: 3.0% instead of 2.2%, say.
- **real oil price**: percent above normal; it starts at `:rise` and fades as `rho_s` says.

With the hand-chosen parameters, a 10% rise in the price of oil lowers GDP by about 0.05% and consumption by about 0.4%, raises
headline inflation by about 1 point for one quarter and core inflation by 0.1 to 0.2 points for a few years, and the Fed raises its rate
by about 0.15 points. These are small effects, which is what Blanchard and Galí found for the 2000s: the US uses less oil per dollar of
GDP than it did, wages no longer chase prices, and people trust the Fed to keep inflation down.

### Ten quarters or twenty

The model follows the economy for 20 quarters (five years) after a shock unless you say otherwise. `:quarters` sets it:

```lisp
(define short (oil-model :quarters 10))       ; two and a half years
(plot-oil-shock short :rise 10)
```

Twenty quarters shows the whole path back to normal for most shocks; ten shows the first years more closely. The first quarters are the
model's surest part; far out, the responses depend most on how long the shock itself is assumed to last (`rho_s`).

## Scenarios: what if?

A scenario is the same model with some parameters changed. `:parameters` takes a list of `(name . value)` pairs; everything else stays
as it was. To compare scenarios, give `plot-oil-shock` a list of `(label result)` pairs: each panel then has a line for each.

```lisp
(define base (oil-model))
(define hawk (oil-model :parameters '((phi_pi . 3))))              ; a Fed twice as tough on inflation
(define dove (oil-model :parameters '((phi_pi . 1.1))))            ; a Fed that barely moves
(plot-oil-shock (list (list "usual Fed" base) (list "tough Fed" hawk) (list "easy Fed" dove)) :rise 20)
```

### Scenarios worth trying

| Question | Change | What to look for |
|---|---|---|
| What if wages chase prices, as in the 1970s? | `(gamma . 0.9)` | a bigger, longer rise in core inflation, a bigger fall in GDP |
| What if the Fed looks through oil? | `(core_weight . 1)` against `(core_weight . 0)` | the Fed's rate, and how much GDP it costs to hold inflation down |
| What if the Fed is tougher, or easier? | `(phi_pi . 3)`, `(phi_pi . 1.1)` | less inflation for more lost output, and the other way round |
| What if prices change more often? | `(theta . 0.5)` | inflation rises faster and fades faster |
| What if the oil shock is temporary? | `(rho_s . 0.5)` | half of it gone each quarter: smaller effects, mostly on headline inflation |
| What if the economy used as much oil as in the 1970s? | `(alpha . 0.04) (chi . 0.04)` | everything about twice as large |

Several changes go in one list: `(oil-model :parameters '((gamma . 0.9) (alpha . 0.04) (chi . 0.04)))` is roughly the 1970s economy.

A scenario is not a forecast. It says how much difference one link makes, holding the others as they are, which is what a model is
best at. The size of an effect depends on the parameters; whether it is bigger or smaller under a change is usually what can be trusted.

### Other kinds of surprise

The model has six kinds of shock. `oil-model-responses` shows the response to a typical one of any of them:

| Shock | What it is |
|---|---|
| `"e_oil"` | the real price of oil |
| `"e_a"` | productivity: workers can make more with the same effort |
| `"e_z"` | demand: households want to spend more now |
| `"e_i"` | monetary policy: the Fed raises its rate by more than its rule says |
| `"e_p"` | cost-push: firms raise their prices more than their costs explain |
| `"e_w"` | wages: workers win higher pay than the labor market explains |

```lisp
(define base (oil-model))
(oil-model-responses base "e_i")              ; a quarter-point surprise rise in the Fed's rate
(hash-table-ref base "variance-decomposition") ; how much of each variable's ups and downs each kind of shock explains, in percent
```

## What "estimated" means

### The idea

The parameters in the table above were chosen by hand. **Estimating** them means letting the data choose: finding the values for which
the model, fed the surprises it needs, reproduces what the US economy actually did, quarter by quarter, for some years.

Here is the thought. Give the model a set of parameters. Then go through history a quarter at a time: from what GDP, inflation, wages,
the Fed's rate and the price of oil did up to last quarter, the model predicts this quarter; the difference between the prediction and
what happened is a surprise, which the model must explain as one of its shocks. A good set of parameters makes those surprises look like
what the model says surprises are: small, unrelated from one quarter to the next, and of the sizes it expects. A bad set needs large,
strange surprises to explain history. The **likelihood** is the number that says how well a set of parameters does this: how likely
the actual history is, if the model with those parameters were true. Estimation searches for parameters with a high likelihood.

### Priors and posteriors

Five or six series over a hundred quarters can't pin down a dozen and a half parameters very well. Some, the data say a lot about; some,
almost nothing. So the method used here, **Bayesian estimation**, starts from what is believed before looking at the data, and lets
the data change it:

- The **prior** for a parameter is what is believed beforehand: a range of likely values, given as a mean and a standard deviation.
  The prior for `theta` (sticky prices) has a mean of 0.66 and a standard deviation of 0.1: prices probably last two or three
  quarters, maybe more, maybe less. Priors come from other studies and from common sense (a share must be between 0 and 1).
- The **posterior** is what is believed after the data: the prior, weighed by the likelihood. Where the data have a lot to say, the
  posterior ends up far from the prior and narrow; where they have little, the posterior looks like the prior.

The estimate of a parameter is the **posterior mean**, and its **90% interval** is the range it lies in with a 90% chance, given the
prior and the data. A narrow interval means the data are sure; a wide one, that they aren't.

### How Dynare does it

Dynare does two things, which together take a few minutes:

1. **The posterior mode**: it searches for the single best set of parameters, the one that does best on prior and likelihood together.
2. **Draws**: to see how sure it can be, it then takes a long random walk through sets of parameters, each step a small change from the
   last, keeping a step more often when the new set does better ("Markov chain Monte Carlo", or MCMC). The sets it visits are a
   sample from the posterior: a parameter the data pin down hardly moves along the walk, and one they don't wanders widely. It walks
   twice (two **chains**), 20,000 steps each, and throws away the first half of each walk, while it was still finding its way.

From the draws come the means and intervals of the parameters, and also **bands** around the impulse responses: the responses of each
of thousands of sets of parameters, of which the band holds the middle 90%.

Dynare also reports the **log marginal density**: how well the model as a whole fits the data, priors included. It means nothing alone,
but between two models (or the same model with a change, estimated on the same data), the higher one fits better; a difference of more
than a few points is a lot.

### The data

`oil-model-data` gets six series from FRED, by the quarter, each as a percent per quarter:

| Column | FRED series | What it is |
|---|---|---|
| `dy_obs` | GDPC1 | real GDP growth |
| `dw_obs` | COMPRNFB | real wage growth (compensation an hour in the nonfarm business sector, in today's prices) |
| `pi_q_obs` | PCEPILFE | core inflation (PCE prices without food and energy, the Fed's favorite measure) |
| `pi_c_obs` | PCEPI | headline inflation (all PCE prices) |
| `i_obs` | FEDFUNDS | the federal funds rate, divided by 4 to make it per quarter |
| `ds_obs` | WTISPLC | the change in the real price of oil (West Texas Intermediate, less core inflation) |

Each column has its average over the sample taken away: the model explains the ups and downs, not the averages (why GDP grew 2.8% a
year in these years is another question). Headline inflation also has a **measurement error**, an allowance for its differences from
core that have nothing to do with oil, such as food prices.

The sample ends in 2008 by default, because from the end of 2008 to 2015 the Fed's rate was stuck at zero, which the model's Fed rule
can't capture (it would have wanted to go below zero). It starts in 1985, after the high inflation of the 1970s and its end under Paul
Volcker, which were a different economy (see [The 1970s and the 2000s](#the-1970s-and-the-2000s)).

### Estimating the model

```lisp
(define estimate (oil-model-estimate creds))                                           ; 1985 to 2008
(define estimate (oil-model-estimate creds :start (date 1966 1 1) :end (date 1984 10 1)))  ; another period
(define quick (oil-model-estimate creds :draws 2000))                                   ; a first look, in about two minutes
```

The dates are the first days of the first and last quarters. 20,000 draws in each chain take about five minutes; 2,000 are enough to see
roughly where the estimates are, though their intervals and bands are less reliable. `:echo #t` shows Dynare's progress as it works.

### Reading the estimates

`show-oil-estimates` shows, for each parameter, what it is, its prior mean, the estimate (the posterior mean), and the 90% interval:

```lisp
(show-oil-estimates estimate)
```

Things to look at:

- **Did the data move it?** Compare the estimate with the prior mean. If they are close and the interval is about as wide as the prior
  (mean ± 1.6 standard deviations), the data said little: the result is the prior coming back. The shocks' sizes and how long they last
  are always well estimated; how households and firms behave less so.
- **Is it believable?** Small models often find prices stickier than surveys of firms do (a `theta` of 0.9 or more says prices last
  ten quarters or more, where surveys say about a year). That is a sign the model is missing something that makes inflation sluggish, and
  `theta` is standing in for it. The responses can still be right even when one parameter is doing another's job.
- **The Fed**: `phi_pi`, `phi_y`, `rho_i` and `core_weight` are what the Fed did in those years, not what it should have done.

`(oil-shock-responses estimate :rise 10)` has the responses with their bands: a `GDP low` and a `GDP high` column beside `GDP`, and so on.
`plot-oil-shock` shades the band.

### Scenarios from the estimate

`:from` makes a scenario start from an estimate's parameters instead of the hand-chosen ones; `:parameters` then changes some of them:

```lisp
(define estimate (oil-model-estimate creds))
(define looks-through (oil-model :from estimate :parameters '((core_weight . 1))))
(define reacts (oil-model :from estimate :parameters '((core_weight . 0))))
(plot-oil-shock (list (list "as estimated" estimate) (list "Fed looks through oil" looks-through)
                      (list "Fed reacts to oil" reacts))
                :rise 20)
```

The scenario's responses have no bands: they are for one set of parameters, the estimated means with your changes.

## The 1970s and the 2000s

Blanchard and Galí asked why the oil shocks of the 1970s came with deep recessions and high inflation, and those of the 2000s, as large
or larger, with neither. Estimating the model on each period gives an answer of the same kind:

```lisp
(define early (oil-model-estimate creds :start (date 1966 1 1) :end (date 1984 10 1)))
(define recent (oil-model-estimate creds))
(plot-oil-shock (list (list "1966-1984" early) (list "1985-2008" recent)) :rise 10)
(show-oil-estimates early)
```

This is what came out, estimated with 20,000 draws in each chain in November 2026 (FRED revises its data now and then, so a new run
differs a little). After a 10% rise in the real price of oil:

| | 1966–1984 | 1985–2008 |
|---|---|---|
| core inflation, first quarter (points a year) | 0.17 | 0.03 |
| core inflation, after a year | 0.11 | 0.02 |
| the Fed's rate, first quarter (points a year) | 0.19 | 0.09 |
| consumption, first quarter (percent) | −0.35 | −0.31 |
| GDP, first quarter (percent) | 0.02 | 0.06 |

And the estimates behind them that differ most:

| Parameter | 1966–1984 | 1985–2008 | What it says |
|---|---|---|---|
| `gamma` | 0.97 (0.95 to 0.99) | 0.94 (0.92 to 0.97) | real wages were more rigid |
| `theta` | 0.89 (0.85 to 0.92) | 0.95 (0.93 to 0.96) | prices changed more often (high inflation makes firms change them more often) |
| `rho_i` | 0.75 | 0.84 | the Fed moved its rate faster... |
| `stderr e_i` | 0.35 | 0.12 | ...and surprised more: three times as much |
| `stderr e_z` | 4.0 | 2.7 | demand was more unsteady |

What this says:

- **Core inflation is where the periods differ.** The same oil shock raised core inflation about five times as much in 1966–1984, and
  for longer, and the Fed's rate twice as much. Most of the difference is wages: run the 1966–1984 estimate again with flexible real
  wages, `(oil-model :from early :parameters '((gamma . 0.2)))`, and the rise in core inflation all but goes away (0.005 points instead
  of 0.17), while the real wage falls at once (−0.37% in the first quarter instead of −0.02%). When workers accept the cut in what their
  pay buys, the oil shock doesn't become an inflation; when they resist it, it does. This is Blanchard and Galí's main point.
- **Consumption falls about as much in both.** Households are poorer by about the same amount: the oil shock is a loss of income either
  way.
- **GDP hardly moves in either, which is the model's limit, not history's.** The deep recessions of 1974–75 and 1980–82 came with the oil
  shocks, but this model can't make GDP fall much after one, because of how it pays for oil (see [What the model leaves out](#what-the-model-leaves-out)).
  Blanchard and Galí also found that much of the 1970s' trouble came from other shocks that happened at the same time, and from the
  Fed of the time; in this estimate, the 1966–1984 Fed's own surprises were three times as large.
- **Each estimate's log marginal density can't be compared with the other's**: they are fitted to different data.

## What the model leaves out

A small model is small on purpose: each part can be understood. But what it leaves out matters for how far to trust it.

- **Trade balances every quarter.** The US pays for its oil with goods sent abroad at once; it can't borrow from abroad for a while, as
  it really does. This makes GDP hold up better after an oil shock than it should, while consumption falls. It is the main reason the
  model's GDP response is small.
- **The US as an oil producer.** Here all oil is imported. Since about 2015 the US has produced about as much oil as it uses, so a higher
  oil price also raises the income of US producers, and their investment, which this model doesn't have.
- **No investment, no government, no exchange rate.** Spending is consumption and the goods sent abroad for oil. (The crash model has investment.)
- **The price of oil moves on its own.** In fact it often rises *because* the world economy is booming (Lutz Kilian's work shows that
  oil prices driven by demand and those driven by supply have quite different effects). Here every rise is a supply shock.
- **Linear.** Responses are proportional to the shock and the same up as down. A 100% rise is treated as ten 10% rises; in fact large
  shocks may do more than proportional harm.
- **No zero lower bound.** The Fed's rate can go below zero in the model; in fact it couldn't from 2008 to 2015 and in 2020-2021.
- **Rational expectations.** Everyone understands the model and expects its average outcome. People's actual expectations of
  inflation move more slowly and less evenly.

So use the model to understand *mechanisms* and to compare *scenarios*, not to forecast GDP.

## The stock market crash model

A second model, in `dynare/crash_model.inc`, asks what a fall in the stock market does. Its variables and parameters have descriptive
names (`net_worth`, `price_stickiness`, `accelerator`), so that the model file reads as a description of the economy.

### Who is in it, and the financial accelerator

- **Households** work, consume and save at the Fed's interest rate. Their spending also rises a little with the value of the shares they
  own (`wealth_effect`).
- **Firms** make goods from labor and capital, and set prices that change only now and then (`price_stickiness`), as in the oil model.
  They own the capital and pay for part of it with borrowed money.
- **Lenders** can't see how well a firm will do, so they charge more than the safe interest rate, and the more a firm borrows compared
  with its own **net worth** (what it owns less what it owes), the more they charge. That extra is the **credit spread** (the model's
  "external finance premium"), and `accelerator` is how much it rises when borrowing compared with net worth rises 1%.
- **The Fed** sets its rate by a rule that responds to inflation and GDP, a little at a time.

A fall in firms' net worth, such as a stock market crash, then works like this. The firms are more heavily in debt compared with what they
own, so the credit spread rises. With borrowing dearer, firms invest less. With less investment, the price of capital falls, and with it
firms' net worth again. The first blow is made bigger as it goes around: that is the **accelerator** (Bernanke, Gertler and Gilchrist,
1999). In the model, "the stock market" is firms' net worth.

### Running it

```lisp
(define base (crash-model))
(stock-crash-responses base :fall 20)            ; a table: what follows when firms' net worth is 20% below normal in quarter 1
(plot-stock-crash base :fall 20)                 ; the same, as charts

; The same crash in an economy without the accelerator: the whole financial channel shut
(define without (crash-model :parameters '((accelerator . 0))))
(plot-stock-crash (list (list "with the accelerator" base) (list "without" without)) :fall 20)
```

`crash-model` takes `:parameters`, `:from` (an estimate) and `:quarters` exactly as `oil-model` does, and the whole of [Scenarios: what
if?](#scenarios-what-if) applies. The responses are linear: a 40% fall does twice what a 20% fall does. The notebook
`lisp_interp/notebooks/stock_crash_model.ipynb` goes through these steps, a cell each.

Scenarios worth trying:

| Change | What it asks |
|---|---|
| `((accelerator . 0))` | What does the financial channel add to a crash? |
| `((leverage . 3))` against `((leverage . 1.5))` | Do crashes hurt more when firms borrow more? |
| `((fed_smoothing . 0.2))` against `((fed_smoothing . 0.9))` | Does it matter how fast the Fed cuts its rate? |
| `((wealth_effect . 0))` | How much of the fall in spending is households feeling poorer, and how much is firms' investment? |
| `((price_stickiness . 0.5))` | Do sticky prices matter? (with flexible prices, falling prices cushion the blow) |

Other kinds of surprise are tables of one typical surprise, from `(crash-model-responses base shock)`, `shock` being
`"net_worth_shock"`, `"lender_fear_shock"` (lenders' fears: the credit spread jumps for no other reason), `"demand_shock"`,
`"productivity_shock"`, `"fed_shock"` or `"cost_push_shock"`.

### Estimating it

```lisp
(define estimate (crash-model-estimate creds))     ; 1985-2008, about a quarter of an hour (:draws 1000 for a quick look)
(show-crash-estimates estimate)
(plot-stock-crash estimate :fall 20)               ; with a 90% band
(crash-model :from estimate :parameters '((accelerator . 0)))
```

The data (`crash-model-data`) are five quarterly series from FRED: the growth of consumption (PCECC96) and of investment (GPDIC1), core
inflation (PCEPILFE), the federal funds rate (FEDFUNDS), and the spread of Moody's Baa corporate bond yields over the 10-year Treasury
(BAA10YM), each less its average. The spread is how the data say how dear it is for firms to borrow. GDP growth is left out because, in
this model, GDP is exactly 80% consumption plus 20% investment, so all three series together would fit an exact equation, which real data
never do (Dynare would stop with a "singular" error).

#### What the data say

For 1985 to 2008 (4,000 draws in each chain, a quarter of an hour), the estimate is:

| Parameter | Prior mean | Estimate | 90% interval |
|---|---|---|---|
| `accelerator` | 0.05 | 0.002 | 0.002 to 0.003 |
| `wealth_effect` | 0.1 | 0.006 | 0.000 to 0.013 |
| `price_stickiness` | 0.66 | 0.75 | 0.67 to 0.84 |
| `capital_price_response` | 0.25 | 0.22 | 0.18 to 0.28 |
| `fed_inflation_response` | 1.5 | 1.42 | 1.33 to 1.51 |
| `fed_smoothing` | 0.75 | 0.68 | 0.62 to 0.73 |
| `demand_persistence` | 0.5 | 0.98 | 0.97 to 0.99 |

The headline: **the data of these years find almost no financial accelerator.** The estimate of `accelerator` is a twenty-fifth of the
prior's, and the interval is narrow. After a 20% fall in firms' net worth, the estimated model has GDP 0.28% below normal at first (90%
interval: 0.20% to 0.37%), investment 1.6% below, and consumption slightly *above*; the calibrated model, with `accelerator` at 0.05, has
GDP 2.2% below and investment 13% below. So the answer to "how much worse does a crash get through the financial channel?" depends
almost entirely on a parameter the data have not pinned down well, and the sample's answer is "hardly at all."

How far to trust that:

- **The sample has no great financial crisis.** It runs from 1985 to the third quarter of 2008: the stock crash of 1987, the savings and
  loan troubles, 1998, the dot-com bust. The model learns about the accelerator from the times that the credit spread moved with
  investment. Without a 2008 in the sample, it is not surprising that it finds the accelerator weak. The crisis itself can't be put in,
  because the Fed's rate hit zero, which the model can't represent.
- **Net worth is never observed.** The data have no series for it, so its surprises are identified only through the credit spread and
  investment. The estimate of a typical net worth surprise (26% a quarter, against a prior of 2%) is not believable as a description of
  the stock market; it is a sign that net worth carries little weight in the estimated economy, so its size is almost free to wander.
- **Some estimates are odd.** `fed_gdp_response` comes out negative (-0.05), meaning the Fed lowers its rate when GDP is above normal, and
  `demand_persistence` is 0.98, which says demand shocks are close to permanent. These are signs of misspecification: the model is a
  sketch, and what it can't explain tends to end up in whichever parameters are free to take it.
- **A short run.** 4,000 draws is enough for a first look, not a final answer; try `:draws 20000` (about an hour) before relying on a
  number.

So treat the calibrated model (`accelerator` 0.05, the value Bernanke, Gertler and Gilchrist use) as a picture of *how the channel
works*, and the estimate as a warning that US data since 1985, before the crisis, don't show it to be strong. Both can be compared
directly:

```lisp
(plot-stock-crash (list (list "calibrated" base) (list "estimated" estimate)) :fall 20)
```


### What this model leaves out

- **No banks, only firms' balance sheets.** Gertler and Karadi's model has banks whose own capital is the thing that is lost; the effect
  is similar, but a crash that hurts banks (2008) rather than firms (2000) has its own channels.
- **The stock market is firms' net worth.** The model has one kind of asset; real stock markets also move with what investors expect
  and what they will pay for it, which the model has no room for.
- **Linear, and no zero lower bound.** A big crash makes the Fed cut its rate to zero, and no further. The model can cut below zero, so
  for a big enough crash it makes the Fed do more than it could. This is why the estimate stops in 2008, and why it says little about the
  crash of 2008 itself.
- **Households hold shares and nothing else**, and they are all the same: the model can't say who loses.
- **Consumption can rise.** With the real interest rate lower after a crash, households save less; the wealth effect works against
  that, but it can be too weak to make consumption fall at first. Look at the estimate, not the calibration, for this.

## Wealth taxes

A wealth tax is a different kind of question. Its effects depend on *who* holds the wealth and how they respond (saving less, moving it,
avoiding the tax), and a model with one "representative" household, like these, can't say anything about who. It would treat a
wealth tax as a tax on capital: less saving, less capital, lower wages in the long run. Serious answers come from models with many
different households (Guvenen and others, *Use It or Lose It*, 2023, is one), and are about the long run rather than the next few years.
That is a project of its own, probably not in Dynare.

## Reference

### Setting up Dynare

Dynare runs inside GNU Octave. On a Mac, with Homebrew:

```bash
brew install octave dynare
octave-cli --eval "pkg install -forge io datatypes statistics"
```

The last line installs Octave Forge's statistics package, which Dynare needs; it builds from source and takes a minute or so. The Dynare
that the Dynare website offers as a Mac download, in `/Applications/Dynare`, is built for MATLAB, and Octave can't use it; Homebrew's
can. `dynare-run` looks for `octave-cli` on the PATH and in `/opt/homebrew/bin`, and for Dynare in Homebrew's folder; the environment
variables `OCTAVE` and `DYNARE_PATH` (the folder with `dynare.m`) say where they are, if they are somewhere else.

Octave crashes as it exits after an estimation, once Dynare is finished. `dynare-run` judges a run by whether its results file was
written, so the crash does no harm, but it is why an Octave error message about a "segmentation fault" can appear in the log.

### The functions

#### `(oil-model [:parameters p :from estimate :quarters n])`
Runs the oil model (`dynare/oil_irfs.mod`) and returns its responses to each kind of shock, as `dynare-run` returns them. The parameters
are as `dynare/oil_model.inc` chooses them, or, with `:from`, an estimate's (`oil-model-estimate`'s result) posterior means; then
`:parameters`, a list `((name . value) ...)`, changes any of them. `:quarters` is how many quarters to follow (20, unless it says).

#### `(oil-model-estimate creds [:start d :end d :data table :draws n :quarters n :echo #t])`
Estimates the oil model (`dynare/oil_estimate.mod`) on US data from `:start` to `:end` (the first days of the quarters; 1985-01-01 to
2008-07-01 unless they say), from `oil-model-data`, or on the table `:data`. Each of the two chains makes `:draws` draws (20,000); the
responses have 90% bands. `:echo #t` shows what Dynare prints as it works. Takes some minutes.

#### `(oil-model-data creds [:start d :end d])`
The table the model is estimated on: a `date` column and the six series of [The data](#the-data), from FRED, less their averages.

#### `(oil-shock-responses result [:rise r])`
What happens when the real price of oil rises `r` percent (10, unless it says), as a table: `quarter`, then `GDP`, `consumption`,
`hours`, `real wage` (percent from normal), `headline inflation`, `core inflation`, `Fed rate` (points a year from normal), and `real oil
price`; after an estimation, a `low` and a `high` column for each, its 90% band. The band is scaled by the same number as the
responses, so it leaves out how unsure the estimate is of the size of a typical oil surprise.

#### `(oil-model-responses result shock)`
The same table, for one typical surprise of any of the six kinds (`"e_oil"`, `"e_a"`, `"e_z"`, `"e_i"`, `"e_p"`, `"e_w"`; see [Other
kinds of surprise](#other-kinds-of-surprise)).

#### `(plot-oil-shock results [:rise r :title t])`
Charts of `oil-shock-responses`: a panel each for GDP, consumption, headline and core inflation, the Fed's rate and the real wage,
with the band of an estimate shaded. `results` is one result, or a list of `(label result)` to compare.

#### `(show-oil-estimates estimate)`
A table of an estimate's parameters: what each is, its prior mean, the estimate (posterior mean), and its 90% interval.

#### `(oil-model-estimated-parameters estimate)`
An estimate's parameters as a list `((name . value) ...)`, as `oil-model`'s `:from` uses them.

#### `(crash-model [:parameters p :from estimate :quarters n])`
Runs the stock market crash model (`dynare/crash_irfs.mod`) and returns its responses to each kind of shock, as `dynare-run` returns
them. `:parameters`, `:from` and `:quarters` are as for `oil-model`; `((accelerator . 0))` is an economy without the financial accelerator.

#### `(crash-model-estimate creds [:start d :end d :data table :draws n :quarters n :echo #t])`
Estimates the crash model (`dynare/crash_estimate.mod`) on US data, 1985-01-01 to 2008-07-01 unless `:start` and `:end` say, from
`crash-model-data`, or on the table `:data`; otherwise as `oil-model-estimate`, but each chain makes 4,000 draws by default (about a quarter of an hour).

#### `(crash-model-data creds [:start d :end d])`
The table the crash model is estimated on: a `date` column and the five series of [Estimating it](#estimating-it), less their averages.

#### `(stock-crash-responses result [:fall f])`
What happens when firms' net worth is `f` percent below normal in the first quarter (20, unless it says), as a table: `quarter`, then
`GDP`, `consumption`, `investment`, `hours`, `real wage`, `net worth`, `price of capital` (percent from normal), `inflation`, `Fed rate`
and `credit spread` (points a year from normal); after an estimation, a `low` and a `high` column for each.

#### `(crash-model-responses result shock)`
The same table, for one typical surprise of any of the six kinds (`"net_worth_shock"`, `"lender_fear_shock"`, `"demand_shock"`,
`"productivity_shock"`, `"fed_shock"`, `"cost_push_shock"`).

#### `(plot-stock-crash results [:fall f :title t])`
Charts of `stock-crash-responses`: a panel each for GDP, consumption, investment, inflation, the Fed's rate, the credit spread and net
worth. `results` is one result, or a list of `(label result)` to compare.

#### `(show-crash-estimates estimate)`
A table of a crash model estimate's parameters: what each is, its prior mean, the estimate, and its 90% interval.

#### `(dynare-run model-file [:parameters p :macros m :data table :directory d :echo #t :timeout seconds])`
Runs Dynare on any model file, for models of your own. `model-file` is a `.mod` file, or the name of one in `lisp_interp/dynare/`.
The files of its folder (`.mod`, `.inc`, `.m`) are copied into a new folder, or `:directory`, and Dynare runs there; the folder is kept,
with Dynare's own output files and its log, `dynare.log`. Returns a hash table:

| Key | What it holds |
|---|---|
| `"responses"` | a hash table from each shock's name to a table of the responses to one typical surprise: `quarter`, then a column for each variable; after an estimation with `bayesian_irf`, the posterior mean, with `<variable> low` and `<variable> high` columns |
| `"estimates"` | after an estimation: a row for each estimated parameter: `name`, `prior mean`, `prior stdev`, `mode`, `mean`, `low`, `high` |
| `"log-marginal-density"` | after an estimation: how well the model fits the data |
| `"variance-decomposition"` | after `stoch_simul`: a row for each variable, a column for each shock, in percent |
| `"parameters"` | every parameter's value as Dynare last had it |
| `"shocks"` | each shock's typical size (standard deviation) |
| `"folder"`, `"log"` | the folder it ran in, and everything Octave printed |

`:parameters` sets parameters after the model's calibration: they are written into the model at its line `// Parameters given by the
caller go here.`, which a model must have to take them. `:macros` sets Dynare's macro-variables (as `-Dname=value` on Dynare's command
line), such as the oil models' `draws` and `quarters`. `:data`, a table, is written to `data.csv` in the folder, for an estimation's
`datafile='data.csv'`. `:timeout` is in seconds (an hour, unless it says). If Dynare stops with an error, the error names its first
line and the log.

### The model files

In `lisp_interp/dynare/`:

| File | What it is |
|---|---|
| `oil_model.inc` | the oil model: its variables, shocks, parameters and their calibration, and its equations, each with a sentence saying what it means |
| `oil_irfs.mod` | the model's responses to each shock, for its calibrated (or given) parameters |
| `oil_estimate.mod` | the model estimated from `data.csv`: the observed variables, the priors, and the estimation's settings |
| `crash_model.inc`, `crash_irfs.mod`, `crash_estimate.mod` | the same three for the stock market crash model |
| `export_results.m` | run by `dynare-run` after Dynare, to write what it found for the Lisp side to read |

To write a model of your own, start from a copy of these: Dynare's own manual (<https://www.dynare.org/manual/>) describes the language,
and Johannes Pfeifer's collection of models (<https://github.com/JohannesPfeifer/DSGE_mod>) has well-documented versions of many
published ones.
