# morris-lisp — The CMO model

A collateralized mortgage obligation divides the cash a pool of mortgages pays among bonds: this one's interest, that one's principal, a
floater and an inverse floater that together are worth what they were cut from. `lib/deal.lsp` models one as a **tree**. This manual says
what a deal is made of, how to build one, how each kind of bond is paid, and how losses and shortfalls are handled. The functions are loaded
when you call one of them (see `lazy-load`), so there is nothing to load; `(load "deal.lsp")` loads them all at once.

There are four documents. The **language manual**, [lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the syntax and the
general builtins (`defstruct`, `defmethod` and the vectors and tables a deal is made of are there). The **library manual**,
[lisp_library_reference.md](lisp_library_reference.md), covers getting data, models, and investments. The **example programs**,
[lisp_example_programs.md](lisp_example_programs.md), say how whole programs are put together; `examples/deal_example.lsp` is this model's.
**This one is about the deal model.** A section name in quotes is a section of the language manual, unless it says otherwise.

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [A deal in a few lines](#a-deal-in-a-few-lines)
- [The parts of a deal](#the-parts-of-a-deal)
  - [Nodes](#nodes)
  - [Splits](#splits)
  - [Coupons and the index](#coupons-and-the-index)
  - [The order of a month](#the-order-of-a-month)
  - [Amounts, and what is equal](#amounts-and-what-is-equal)
- [Building a deal](#building-a-deal)
  - [The collateral](#the-collateral)
  - [Pieces of collateral, and the pricing speed](#pieces-of-collateral-and-the-pricing-speed)
  - [Dividing a node](#dividing-a-node)
  - [Plans, and looking before adding](#plans-and-looking-before-adding)
  - [Changing a split, and taking one away](#changing-a-split-and-taking-one-away)
  - [Running a deal, and looking at it](#running-a-deal-and-looking-at-it)
- [The kinds of split](#the-kinds-of-split)
  - [Sequential, and pro rata](#sequential-and-pro-rata)
  - [A PAC and its companion](#a-pac-and-its-companion)
  - [A floater and an inverse floater](#a-floater-and-an-inverse-floater)
  - [A premium and a discount](#a-premium-and-a-discount)
  - [Z bonds, and accretion directed bonds](#z-bonds-and-accretion-directed-bonds)
  - [Interest-only and principal-only bonds](#interest-only-and-principal-only-bonds)
  - [Sequential by average life](#sequential-by-average-life)
- [Prices, yields and spreads](#prices-yields-and-spreads)
- [Option-adjusted spread and effective duration](#option-adjusted-spread-and-effective-duration)
- [The prepayment model](#the-prepayment-model)
- [Hedging a tranche](#hedging-a-tranche)
- [Losses and shortfalls](#losses-and-shortfalls)
  - [Defaults, from the default model](#defaults-from-the-default-model)
  - [Losses](#losses)
  - [Interest shortfalls](#interest-shortfalls)
  - [What is not modeled](#what-is-not-modeled)
- [Checking a deal](#checking-a-deal)
- [Making another kind of split](#making-another-kind-of-split)
- [The deal object, and its views in a notebook](#the-deal-object-and-its-views-in-a-notebook)
- [Building a deal by clicking](#building-a-deal-by-clicking)
- [An example program](#an-example-program)

## A deal in a few lines

A deal is a tree. The root is the **collateral**, the pool, which pays interest and principal each month. A **split** divides what a node
is paid among its **children**, which are **tranches**, and a child can be divided again, to any depth, until the **bonds** at the leaves,
which are what trades:

```
POOL (the collateral) -- sequential --> A -- sequential --> A1, A2, Z (an accrual bond)
                                        B -- floater and inverse floater --> B1, B2
```

The pool here is a toy, a piece of collateral of 120 at 0% that does not prepay, so it pays 30 of principal each month for four months. It is divided into a bond
`A`, which is paid first, and `B`:

```lisp
(define deal (new-deal "Demo" :collateral '((120.0 0.0 0.0 4)) :speed (prepayment-speed 'cpr 0)))
(deal-sequential! deal "POOL" '(("A" 50.0) ("B" 70.0)))
(deal-run! deal)
(node-principal (get-node deal "A"))        ; => #(30.0 20.0 0.0 0.0)
(node-principal (get-node deal "B"))        ; => #(0.0 10.0 30.0 30.0)
(node-balance (get-node deal "B"))          ; => #(70.0 70.0 60.0 30.0 0.0)
(deal-check deal)                           ; => #t
(deal-leaves deal)                          ; => ("A" "B")
```

`A` is paid the 30 of month 1, and 20 of month 2, when it is paid off; `B` gets the other 10 of month 2, and then everything. `deal-check`
says that the principal adds up, in every month and at every split.

The collateral is **data**, a table with a row for each **piece** of it (see "Pieces of collateral, and the pricing speed"), and the root of the tree is the cash
flows that the pieces pay together at a prepayment speed. All of it is in **double precision**: `new-deal` refuses single (see `set-vector-precision!`), because a bond
of hundreds of millions has to keep its cents.

## The parts of a deal

### Nodes

A **node** (`defstruct node`) has

- a `name`, a string, which is how it is found: `(get-node deal "A")`;
- a `balance` vector, one element a month and one more: `balance[t]` is what the node owes at the start of month `t` (0 is the start of the
  deal);
- a `principal` vector, `principal[t]` being what it is paid in month `t`, by the pool, or by its parent's split;
- an `interest` vector, in the same way;
- an `accrual` vector, what it adds to its balance instead of being paid interest (a Z bond; see below);
- a `loss` vector, what it is written down by (see "Losses");
- a `shortfall` vector, the interest that it was owed in the month and was not paid (see "Interest shortfalls");
- a `coupon`, a function of the index (see "Coupons and the index");
- a `split`, the one that divides it among its children, if it has one;
- the flags `z-flag` (a Z bond) and `notional-flag` (an interest-only bond), and, for a notional bond, `follows` and `share`.

A `collateral` and a `tranche` include `node`, so `node-balance`, `node-principal` and the rest work on either. A tranche with no split is a
**bond**, a leaf; one with a split passes on what it is paid. `(get-node deal name)` is the node called `name`; `(deal-names deal)` are all the
names, in the order they were added; `(deal-leaves deal)` are the bonds; `(deal-root deal)` is the name of the collateral, the root of the tree, and
`(deal-in-tree? deal name)` is `#f` for a tranche that has been added and not yet given a parent.

### Splits

A **split** (`defstruct split`) names its `children`, and divides what its parent was paid among them. What differs from one kind of split to
another is its **methods**, of five generic functions: `pay-principal`, `pay-interest`, `allocate-loss`, `calculate-sizes` and
`assign-coupons`, with `check-split` for what it will not divide. (They are described in "Making another kind of split".) The kinds there are:

| Kind | Made by | What it does |
|---|---|---|
| `sequential-split` | `deal-sequential!` | pays the first child until it is paid, and then the next; a child can be a Z bond |
| `pro-rata-split` | `deal-pro-rata!` | pays each child in proportion to what it still owes |
| `pac-split` | `deal-pac!` | a PAC paid on a schedule, and its companion |
| `floater-inverse-split` | `deal-floater-inverse!` | a floater and an inverse floater that together have the coupon of the node they come from |
| `premium-discount-split` | `deal-premium-discount!` | a bond with a higher coupon and one with a lower, that together have its coupon |
| `io-po-split` | `deal-io-po!` | an interest-only bond and a principal-only bond |

### Coupons and the index

The **coupon** of a node is a function of the **index**, `(coupon index)`, that gives the annual rate of interest the node is owed, a decimal
(0.06 is 6%), in a month in which the index is `index`. A twelfth of it is owed on the node's balance at the start of the month.
`(constant-coupon 0.06)` is a coupon that is 6% whatever the index is, and is the collateral's. A split gives its children their coupons when it
is added (`assign-coupons`): for most kinds, the parent's; for a floater and an inverse floater, formulas.

The index is what a coupon that floats is of. It is a number for each month, given to `deal-run!`: `(deal-run! deal :index (make-vector 360
0.04))`, or one number for every month: `:index 0.04`. A deal with nothing that floats needs none; a deal with a floater, run without one,
says so. There is one index; a floater's `:index-name` is for whoever reads the deal, and nothing uses it yet.

### The order of a month

Each month `deal-run!` does these things in this order:

1. **the interest**: the split of the collateral divides the interest it was paid among its children, and each of them divides what it was
   paid, down to the bonds;
2. **the principal**, in the same way (a Z bond has accrued what it is owed in interest, in 1, which is paid as principal here: that is why the
   interest is first);
3. **the loss**, in the same way, of what the bonds have left;
4. **the balances** for next month: a balance is its last, and what it accrues, less what it was paid in principal and written down by; a
   notional bond's balance is a share of the one it follows.

A split does only its own part: it does not call the splits of its children. `deal-run!` walks the tree.

### Amounts, and what is equal

Amounts that should be equal are, if they are within `deal-tolerance` (a billionth) of the balance of the collateral. It is a fraction, not
an amount of money, so it does not matter whether a deal is in dollars or millions.

## Building a deal

### The collateral

The collateral of a deal is **data**: a table with a row for each piece (a pool of loans, with its balance, its rates and the months it has left), and the root of the tree,
`POOL`, is the **cash flows** that they pay together, at a prepayment speed. `(new-deal name [:collateral pieces] [:speed speed] [:first-payment date] [:closing-date date]
[:shortfalls #t])` makes a deal with that one tranche. The cash flows are worked out when the collateral is given, at the **pricing speed**, and again, at whatever speed it
is given, every time `deal-run!` is called. The collateral can be given later, with `(deal-set-collateral! deal pieces)`, or in a notebook (see "The deal object, and its
views in a notebook").

```lisp
(define deal (new-deal "Demo" :collateral '((100000000.0 6.5 6.0 360)) :speed (prepayment-speed 'psa 150)))
(deal-names deal)                                          ; => ("POOL")
(vector-ref (node-balance (get-node deal "POOL")) 0)       ; => 100000000.0
(vector-length (node-principal (get-node deal "POOL")))    ; => 360
```

The root is a `collateral`, a kind of node with the principal, the interest and the balance that its pieces pay, and what is lost when its loans default, if the deal is told
that they do (see "Defaults, from the default model"; to begin with they do not, and nothing is lost). Its coupon is the pass-through coupon of its pieces (see below).

### Pieces of collateral, and the pricing speed

A pool is often several pieces, each with its own balance, coupon and maturity, that prepay at one speed. Each piece is projected at the speed, and the cash flows
are added up, month by month, so that the collateral pays what they pay together. A **piece** is `(balance wac coupon wam [age])`: the balance now; the **wac**, the weighted average coupon of the loans, in percent, which is what the
borrowers pay and what pays the loans off; the **pass-through coupon**, in percent, which is what the investors in the pool are paid, the wac less the fees that are
taken out (so it is no more than the wac: it is an error if it is); the **wam**, the weighted average maturity, the months that are left; and the age, the months the loans have gone
(0 if left out), which is what the PSA curve rises with. A piece with no balance is left out. The deal has as many months as its longest piece.

A piece is a struct too, a `collateral-piece` with the slots `balance`, `wac`, `coupon`, `wam` and `age`, and that is what the deal keeps: `(deal-pieces deal)` gives them. A list
is turned into one wherever a piece is wanted (`(collateral-piece-of '(50000000.0 7.0 6.5 240 12))`), so the two are the same, and a struct can be given where a list can.

**What the loans are like.** A piece has more slots, which say what its loans and borrowers are like, for a prepayment model to look at (see "Option-adjusted spread and effective duration": a model
is given the piece). The cash flows at a speed do not use them. Each is an average over the loans, weighted by their balances, as an agency's pool discloses it, and each is `'()` if it is not known,
which it is in a piece made from a list. They are the things that the model of `load_freddie_data/` (in the repository) is fitted on, with the same meanings.

| Slot | Is | Units |
|---|---|---|
| `loan-size` | the balance of a loan now: a small loan is refinanced less, as the costs are much the same and the saving is less | dollars |
| `credit-score` | the borrowers' credit score when the loans were made | 300 to 850 |
| `ltv` | the loan-to-value now, after what has been paid and what home prices have done: a borrower with little equity cannot refinance | percent |
| `sato` | the spread at origination: the wac less the survey rate of new mortgages when the loans were made (a borrower who paid more than the market, most often for weaker credit, refinances less) | percent |
| `burnout` | the months that the loans have already had a reason to refinance, an incentive above 0.75 percent after their first year, and did not | months |
| `investor-share`, `second-home-share` | the share of the balance on investment properties, and on second homes | 0 to 1 |
| `cash-out-share`, `refinance-share` | the share of the balance that was a cash-out refinance, and a refinance without cash out | 0 to 1 |

```lisp
(define piece (make-collateral-piece :balance 100000000.0 :wac 6.0 :coupon 5.5 :wam 360 :credit-score 750 :ltv 72.0 :investor-share 0.08))
(collateral-piece-age piece)                                                    ; => 0
(collateral-piece-ltv piece)                                                    ; => 72.0
(collateral-piece-wam (collateral-piece-of '(50000000.0 7.0 6.5 240 12)))       ; => 240
(define deal (new-deal "Demo" :collateral (list piece '(50000000.0 7.0 6.5 240 12)) :speed (prepayment-speed 'psa 150)))
(collateral-piece-age (cadr (deal-pieces deal)))                                ; => 12
(collateral-piece-credit-score (cadr (deal-pieces deal)))                       ; => ()
(vector-ref (node-principal (get-node deal "POOL")) 0)                          ; => 347773.9772172784
```

The table of collateral of a deal (see `collateral-table`, and the grid of `(collateral deal)`) has a column for each of them after the age, named as in `collateral-characteristics` (`"credit score"`,
`"investor share"`, ...), with `nan` where a piece does not say. A table read from a file needs only the columns balance, wac, coupon and wam; the others it has are used. Each value is checked when the
deal is given the pieces: a credit score is from 300 to 850, a share from 0 to 1, and the investor and second-home shares, or the two refinance shares, are no more than 1 together.

A **speed** has a type, which says what its number means, and a number that can change with time: `(prepayment-speed type spec)`. The types are `psa` (150 is 150% of
the standard curve, 0 to 6 CPR over 30 months of age, which is the curve of `prepayment_model.lsp`), `cpr` (the annual rate of prepayment, in percent),
`smm` (the share of what is left that prepays in a month, in percent) and `model` (105 is 105% of what the deal's prepayment model says, which looks at rates: see
"The prepayment model"). The `spec` is one number, which is the speed in every month, or a list of linear
pieces, each `(from to months)`: the speed goes in a straight line from `from` to `to`, and is `to` in the last of the months, so that the next piece starts from
there; a piece with no months, `(from to)` with the two the same, is for the rest of the time; and after the last piece the speed holds. The months are counted
from the first payment, and are the same for every piece of collateral. The PSA curve itself is `(prepayment-speed 'cpr '((0 6 30)))`, 0.2 CPR in the first
month and 6 CPR in the thirtieth.

```lisp
(speed-values (prepayment-speed 'cpr '((5 5 3) (5 20 3))) 9)    ; => #(5.0 5.0 5.0 10.0 15.0 20.0 20.0 20.0 20.0)
(describe-speed (prepayment-speed 'cpr '((5 5 3) (5 20 3))))    ; => "CPR: 5 for 3 months, then from 5 to 20 over 3 months"
(describe-speed (prepayment-speed 'psa 150))                     ; => "PSA 150"
```

The speed of the pieces is the **pricing speed** of the deal: it is what the cash flows of the collateral are, and what the average lives of an average-life split are
worked out at. A PAC is still sized at the two PSA speeds it is given, by projecting each of the pieces at them (see `deal-principal-at`).

```lisp
(define pieces '((100000000.0 6.0 5.5 360) (50000000.0 7.0 6.5 240 12)))
(define deal (new-deal "Demo" :collateral pieces :speed (prepayment-speed 'psa 150)))
(define pool (get-node deal "POOL"))
(vector-ref (node-balance pool) 0)             ; => 150000000.0
(vector-ref (node-principal pool) 0)           ; => 347773.9772172784
(vector-ref (node-interest pool) 0)            ; => 729166.6666666666
```

Each piece pays off as loans at its wac do, and pays the investors interest at its pass-through coupon on its balance, so the collateral's principal is the loans' and its interest
is the investors': 729,166.67 in the first month, which is 5.8333% of 150,000,000 for a month (the loans pay 791,666.67, at 6.3333%; the difference is the fees, which
are not modeled).

The collateral pays interest at the rate that the interest is of the balance in each month, so, if its pieces have different pass-through coupons, its **coupon is a vector**, one rate for each month (`(pool-coupons interest
balances)`), that changes as the pieces with the higher coupons pay off or prepay: 5.83% in the first month here, and 5.66% in the two hundredth. (If the pieces all have the same pass-through coupon
it is that, a fixed coupon, whatever their wacs are.) A coupon is a
function of the index, or a vector like this one (`(coupon-at coupon index month)`); the bonds under the collateral have it too, so a sequential split, a pro-rata
split, a PAC and an IO/PO split all work. A floater and an inverse floater, and a premium and a discount bond, are made from a fixed coupon, and say so if the
collateral has not got one. `(project-pieces pieces speed)` is the vectors the collateral is made of (principal, interest, balance, and the interest that the loans pay, at the wac), and
`(project-pool balance wac coupon months smms)` those of one pool that prepays by the monthly mortality of each month; `(project-pieces-with pieces smms-of)` is `project-pieces` with a function
from a piece to its vector of monthly mortalities in place of a speed (`(smms-from-cprs cprs months)` makes one from annual rates in percent), which is how a model of prepayments is used.

**The dates.** `(new-deal name :first-payment (date 2026 11 25))` gives the deal the date of its first payment, which is month 1. `(deal-payment-date deal month)`
is the date of a month, and `(deal-payment-dates deal)` a vector of them, the same day of each month (the end of the month, in one that is shorter).

```lisp
(define deal (new-deal "Demo" :collateral pieces :first-payment (date 2026 11 25)))
(vector-ref (deal-payment-dates deal) 1)       ; => 2026-12-25
(vector-ref (deal-payment-dates deal) 359)     ; => 2056-10-25
```

### Dividing a node

Each builder adds the children as tranches under the parent, and divides the parent among them. Nothing is added if there is something wrong.

- `(deal-sequential! deal parent-name children [:accretion-to name] [:losses rule])` and
  `(deal-pro-rata! deal parent-name children [:losses rule])`: `children` is a list of `(name balance)`, whose balances add up to the parent's.
  A child written `(name balance z)`, in a sequential split, is a Z bond.
- `(deal-pac! deal parent-name pac-name companion-name low-psa high-psa [:losses rule])`.
- `(deal-floater-inverse! deal parent-name floater-name inverse-name :cap c [:margin m] [:index-name "SOFR"])`.
- `(deal-premium-discount! deal parent-name premium-name discount-name :premium-coupon p :discount-coupon d)`.
- `(deal-io-po! deal parent-name io-name po-name [:io-coupon c])`.

These are made of two lower-level functions: `(deal-add-tranche! deal name balance [:z #t] [:notional #t] [:follows name])` adds a tranche, and
`(deal-add-split! deal parent-name split)` divides a node by a split among tranches that are already in the deal, after asking the split what
size they are to be (`calculate-sizes`), and checking that the children's balances add up to the node's, and giving them coupons
(`assign-coupons`). The splits are made by `make-sequential-split`, `make-pro-rata-split` and so on, which take `:children` and the kind's own
slots. A split is added only after the splits above it, because sizes and coupons go from the top down.

### Plans, and looking before adding

A builder is two steps, and the steps can be taken apart. A **plan**, a `split-plan`, is what is to be added under a parent: the tranches (each
the arguments of `deal-add-tranche!`) and the split that divides the parent among them. Each kind of split has a function that makes its plan, with
the arguments of its builder: `(sequential-plan children [:accretion-to name] [:losses rule])`, `(pro-rata-plan children [:losses rule])`,
`(pac-plan pac-name companion-name low-psa high-psa [:losses rule])`, `(floater-inverse-plan floater-name inverse-name :cap c [:margin m])`,
`(premium-discount-plan premium-name discount-name :premium-coupon p :discount-coupon d)` and `(io-po-plan io-name po-name [:io-coupon c])`.
`(deal-add-plan! deal parent-name plan)` adds one, and `(deal-sequential! deal parent children)` is `(deal-add-plan! deal parent (sequential-plan
children))`, and so on. Nothing is added if there is something wrong.

The reason for two steps is to look in between. `(split-plan-sizes deal parent plan)` is the balances the plan's tranches would have, as a list in their
order, without changing the deal (a PAC and its companion are sized from what the parent is paid at the two speeds, a floater and an inverse floater
from the cap, and the others are as they were given):

```lisp
(define deal (new-deal "Demo" :collateral '((100000000.0 6.5 6.5 360)) :speed (prepayment-speed 'psa 150)))
(define plan (floater-inverse-plan "F" "I" :cap 0.0975))
(split-plan-sizes deal (get-node deal "POOL") plan)     ; => (66666666.66666667 33333333.33333333)
(deal-names deal)                                       ; => ("POOL")
(deal-add-plan! deal "POOL" plan)
(deal-names deal)                                       ; => ("POOL" "F" "I")
```

A plan for a kind of split of your own is made with `(make-split-plan :tranches tranches :split split)`.

### Changing a split, and taking one away

`(deal-replace-split! deal parent-name plan)` changes the split that divides a node, to the one in the plan, which is made with the same functions.
The tranches that the plan names and the deal has already stay, with what is under them; those that it names and the deal has not are new; and a
tranche that was in the split and is not in the plan is left out, if it has nothing under it (if it is divided, it must have its split taken away
first: it is an error). Then everything is worked out again, from the top down: the children of the split are given their sizes and their coupons,
and so are the children of the splits below them, and so on to the leaves, because what a split works out depends on the size and the coupon of its
parent. A PAC under a floater is sized again when the floater's cap changes. A split that was given the sizes of its children (a sequential or a pro-rata
split, whose sizes are not worked out) keeps each in the share of its parent that it was. The change is tried on a copy of the deal first, so that if
anything is wrong, in the new split or in any split below it, an error says what, and the deal is as it was.

`(deal-delete-split! deal parent-name)` takes away the split of a node, and every node below it, to any depth. The node is a bond again, and can be
divided in another way. It returns the names that were taken away.

```lisp
(define deal (new-deal "Demo" :collateral '((100000000.0 6.5 6.5 360)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
(deal-floater-inverse! deal "A" "AF" "AI" :cap 0.095)
(deal-pac! deal "AF" "AP" "AC" 100 300)
(deal-replace-split! deal "POOL" (sequential-plan '(("A" 70000000.0) ("B" 30000000.0))))
(vector-ref (node-balance (get-node deal "AF")) 0)       ; => 47894736.84210526
(deal-delete-split! deal "A")                            ; => ("AF" "AP" "AC" "AI")
(deal-names deal)                                        ; => ("POOL" "A" "B")
```

`(deal-trial-of-plan deal parent-name plan)` is that copy: the deal with the plan applied to the node (added, if it has no split, and replacing its split, if it
has), for looking at what the change would make, and for the error if it cannot be made. The deal itself is not changed.

### Running a deal, and looking at it

`(deal-run! deal [speed] [:index index])` works out what each node is paid, and owes, in every month. It can be run again, with another speed or index, or after a
change. `speed` is a prepayment speed, made by `prepayment-speed`: the cash flows of the collateral are worked out again at that speed, every time the deal is run, and then the
tree is run; without one it is run at the pricing speed of the deal.
`(deal-check deal)` is `#t` if everything adds up, and an error that says where if not (see "Checking a deal").

The results are the vectors of the nodes, and tables, with a row for each month (from 1; the balances from 0) and a column for each node, to show
with `display-table`: `(deal-principal-table deal)`, `(deal-interest-table deal)`, `(deal-accrual-table deal)`, `(deal-loss-table deal)`,
`(deal-shortfall-table deal)`, `(deal-coupon-table deal)` (the coupon of each node in each month, at the index the deal was run with) and
`(deal-balance-table deal)`.

`(deal-outline deal)` is a table of the deal itself, a row for each node, each below its parent and before the node after it (depth first: the collateral, what
it is divided into, what each of those is divided into), with the name indented by how far down the tree it is, the balance it starts with, to the cent,
and the kind of split that divides it (`split-label`), if any. It is the picture that a deal builder shows (see "Building a deal by clicking"):

```text
tranche         balance  split
--------  --------------  ---------------------------
POOL      100,000,000.00  sequential
  A        60,000,000.00  floater and inverse floater
    AF     41,052,631.58  PAC and companion
      AP   19,736,607.91
      AC   21,316,023.67
    AI     18,947,368.42
  B        40,000,000.00
```

`(deal-outline-entries deal)` is the same order as a list of `(name . depth)`. `(split-label split)` is a generic function, like `pay-principal`,
that says in a few words what kind of split it is; a kind of your own has the label of the kind it includes, unless it has a method of its own.

## The kinds of split

### Sequential, and pro rata

A sequential split pays what its parent was paid to its first child, until the child is paid off, and then to its second, and so on. A pro-rata
split pays each child a share of it, in proportion to what each still owes.

### A PAC and its companion

`(deal-pac! deal "POOL" "PAC" "COMP" 100 300)` divides the collateral into a PAC and its companion. Its **size** is worked out from what the parent
is paid when the collateral prepays at the two speeds, 100% and 300% PSA: the least of the two principal payments is taken month by month, and the PAC
is the sum of those. That is what the parent pays at *both* speeds, so it can promise it. The companion is the rest of the parent. The PAC's
**schedule**, `(pac-split-schedule split)`, is the balance it is to have at the start of each month: its size, less the least of each month so far.

The parent need not be the collateral. A node below it is paid what the splits above it give it, which depends on the speed, so to find what it
is paid at each speed the deal is run at that speed, as it is, down to the parent: `(deal-principal-at deal name psa)` does that, on copies of the
nodes, and leaves the deal as it was (it includes the interest, and the loss of the collateral is left out: a PAC's schedule is of its cash flows). So
a second PAC can come out of the first one's companion, for a narrower range of speeds: `(deal-pac! deal "COMP1" "PAC2" "COMP2" 150 250)`. Each
PAC is then on its schedule at the speeds of its own bands.

Each month the PAC split pays, with the principal the parent was paid:

1. the PAC, like a sequential split, but only **down to its scheduled balance**: as much as it takes to bring its balance to what the schedule says
   it is to be after this month, not the whole of what it owes;
2. the companion, like a sequential split, what is left; and
3. the PAC, like a sequential split, what is then left.

So at any speed between the two the PAC is paid exactly its schedule, and the companion takes up the difference. If the pool pays less than the
schedule, the PAC is behind and is paid first to catch up. If more, the companion is paid off sooner, and then the PAC takes what is over, ahead
of its schedule. The deal must have collateral, because the PAC is sized by running its pieces at the two speeds. A PAC split has two children, the PAC and
the companion, in that order, which can be divided again.

```lisp
(define deal (new-deal "PAC demo" :collateral '((100000000.0 6.5 6.5 360)) :speed (prepayment-speed 'psa 200)))
(deal-pac! deal "POOL" "PAC" "COMP" 100 300)
(deal-run! deal)
(format "{:.1f}%" (* 100 (/ (vector-ref (node-balance (get-node deal "PAC")) 0) 1e8)))   ; => "64.9%"
(vector-max (abs (- (node-balance (get-node deal "PAC")) (pac-split-schedule (node-split (get-node deal "POOL"))))))   ; => 0.0
(deal-check deal)                                                                         ; => #t
```

At 200% PSA, between the two speeds, the PAC is never off its schedule.

### A floater and an inverse floater

`(deal-floater-inverse! deal "B" "F" "I" :cap 0.09 :margin 0.005)` divides `B`, which has a fixed coupon `c`, into a floater `F` and an inverse
floater `I`. The floater's coupon is the index plus the margin, to the cap; the inverse floater's is a constant less a multiple of the index, to 0.
They are sized, and their formulas worked out, so that together they pay `B`'s coupon on `B`'s balance at every index: with the balance `B` and
the cap `C`,

- the floater is `B c / C`,
- the inverse floater is the rest,
- its leverage is floater / inverse floater, and
- its constant is the leverage times `(C - margin)`.

(The leverage and the constant are slots of the split, `floater-inverse-split-leverage` and `-constant`.) The cap has to be above the coupon, and
the margin from 0 up to the cap; the index is taken as 0 if it is negative. The two are paid principal, and written down, **pro rata**, which keeps
them in the proportion that makes this so.

### A premium and a discount

`(deal-premium-discount! deal "B" "P" "D" :premium-coupon 0.09 :discount-coupon 0.05)` divides `B` into a bond with a coupon above `B`'s and a bond
with a coupon below it, in the sizes that make the two pay `B`'s coupon together (the premium bond is `B (c - d) / (p - d)`), and pays them principal
pro rata.

### Z bonds, and accretion directed bonds

A Z bond (an accrual bond) is not paid its interest: what it is owed is added to its balance, as its **accrual**, and is paid, as principal, to the bonds
that are paid ahead of it. Each month `balance[t+1] = balance[t] + accrual - principal - loss`. It is a child of a sequential split, written
`(name balance z)`:

```lisp
(define deal (new-deal "Z" :collateral '((100000000.0 6.0 6.0 360)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 40000000.0) ("Z" 60000000.0 z)))
(deal-run! deal)
(vector-ref (node-accrual (get-node deal "Z")) 0)         ; => 300000.0
(vector-ref (node-interest (get-node deal "Z")) 0)        ; => 0.0
(vector-ref (node-principal (get-node deal "POOL")) 0)    ; => 99550.52515275695
(vector-ref (node-principal (get-node deal "A")) 0)       ; => 399550.52515275695
(vector-ref (node-balance (get-node deal "Z")) 1)         ; => 60300000.0
(deal-check deal)                                         ; => #t
```

In the first month `Z` is owed 300,000 (half a percent of 60,000,000), which is not paid to it; and `A` is paid 399,550.53, the pool's 99,550.53 and what `Z` accrued. The sequential split
pays what its Z bonds accrue, with the principal its parent was paid, to its children in order, a Z bond too, in its place in the order (so a Z bond is
last, usually, and is paid when the bonds before it are paid off), and a Z bond is owed, in a month, what it accrues in it. The accrual is neither the
parent's interest nor its principal, so the parent's balance and interest are as they were: what the children are paid in principal is the parent's and
the accrual, and what they are paid in interest, with the accrual, is the parent's.

**An accretion directed bond** is paid what the Z bonds accrue first, before the order:
`(deal-sequential! deal "X" '(("A" 40.0) ("B" 30.0) ("Z" 30.0 z)) :accretion-to "B")`. `B` is paid the accrual, up to what it is owed, and then
the order is as before, `B` in its place.

A Z bond can only be a child of a sequential split, because only that pays an accrual, and it is not itself divided. An IO or a PO is not divided
into a Z bond, because it has no principal.

### Interest-only and principal-only bonds

`(deal-io-po! deal "X" "IO" "PO")` divides a node into an **interest-only** bond and a **principal-only** bond, each as big as the node. The PO is
paid all of the principal the node was paid, and none of the interest; the IO is paid all the interest, on a **notional balance**, and none of the
principal. The notional balance of the IO is a balance, but it follows another's: it is the balance of the PO (which is the node's), and declines as
the PO is paid. A tranche with `notional-flag` is such a bond. The IO is left out when a node's children are added up to its balance, and has no
principal and no loss; `deal-check` checks it follows. The IO has the coupon of the node, so that a floating coupon has a floating IO;
`:io-coupon 0.05` makes a partial strip, an IO that is paid 5%, and a PO that is paid the rest of the node's coupon.

```lisp
(define deal (new-deal "Strip" :collateral '((100000000.0 6.0 6.0 360)) :speed (prepayment-speed 'psa 150)))
(deal-io-po! deal "POOL" "IO" "PO")
(deal-run! deal)
(vector-ref (node-balance (get-node deal "IO")) 0)        ; => 100000000.0
(vector-ref (node-balance (get-node deal "IO")) 12)       ; => 97136864.58902393
(vector-ref (node-interest (get-node deal "IO")) 0)       ; => 500000.0
(vector-ref (node-principal (get-node deal "PO")) 0)      ; => 99550.52515275695
(deal-check deal)                                         ; => #t
```

The IO's notional balance is the PO's, so it is the pool's, and falls as the pool pays: 100,000,000 at the start, and 97,136,864.59 after a year. Its interest in the first month is a
twelfth of 6% of that, 500,000, and the PO is paid the pool's principal.

The node may be anything but a Z bond, an IO or a PO: the collateral, a PAC, a floater. The IO and the PO can be divided in turn, in any way, except
into a Z bond: a PO in order, say, or in proportion, and an IO in parts of its notional balance (the children of an IO are notional bonds too, each
following the IO, in the share of it that is its size: `(deal-sequential! deal "IO" '(("IO1" 40.0) ("IO2" 60.0)))` makes one with 40% of the
notional, and one with 60%).

### Sequential by average life

The **average life** of a bond is the time, in years, that each dollar of its principal is outstanding, on average: the months in which it is paid, the first payment
being month 1, each weighted by the amount paid in it, over 12. `(average-life principal)` is that of a vector of principal, and `(deal-average-life deal name)` that
of a node, after `deal-run!`.

```lisp
(average-life (vector 50.0 0.0 0.0 50.0))      ; => 0.20833333333333334
```

A **sequential split by average life** is a sequential split that works out the sizes of its children, from the average lives that they are to have: the user gives the
average life of every child but one, and the one that is not given one is what is left of the parent. `(deal-average-life! deal parent-name children [:losses rule])`
adds it: `children` is a list of `(name years)`, in the order that they are paid in, and one of them is `(name)`. It can be first, in the middle or last. The split
is a child of `sequential-split` (`average-life-split`, with the lives in `average-life-split-lives`): it pays in order, as a sequential split does, and has no Z bonds.

```lisp
(define deal (new-deal "Demo" :first-payment (date 2026 11 25) :speed (prepayment-speed 'psa 150)
                       :collateral '((100000000.0 6.0 5.5 360) (50000000.0 7.0 6.5 240 12))))
(deal-average-life! deal "POOL" '(("A1" 2.0) ("A2" 5.0) ("A3")))
(vector-ref (node-balance (get-node deal "A1")) 0)        ; => 36980402.10543777
(vector-ref (node-balance (get-node deal "A3")) 0)        ; => 76689806.9439642
(deal-run! deal)
(deal-average-life deal "A2")                              ; => 5.000000000000001
```

How it is done: a bigger child is outstanding longer, so the average life of a child grows with its size, and the sizes are found by halving the range. The principal of a child
that comes k-th is the principal of the parent, as it is paid at the pricing speed (found by running the splits above it on a copy of the deal: `deal-principal-now`), between
the total of the sizes of the ones before it and that total and its own size. The children before the one that is not given a life are found from the front, each from where the one
before it ended, and the children after it from the back, each to where the one after it begins. A life that the cash flows cannot give is an error, that says
what they can (the first child of a pool cannot have more than the pool's own average life, and the last cannot have less than its own last month), and so are lives that
leave nothing for the one that is left. The sizes are worked out again whenever the parent's are, so that the lives still hold after a change above (see "Changing a
split, and taking one away"). The lives are of the principal that the parent is paid at the pricing speed, so they are the lives of the bonds at that speed, not at any other.

## Prices, yields and spreads

A tranche has a **price**, a **yield** and a **spread**, and what follows from them: its **duration**, its **average life**, its **dv01**, its **money**, and a **delay**. They are slots
of the tranche (`node-price`, `node-yield`, `node-spread`, `node-oas`, `node-duration`, `node-effective-duration`, `node-average-life`, `node-dv01`, `node-money` and `node-delay`), and are worked out by
`lib/deal_pricing.lsp`. A price, a yield, a spread or an OAS is what is **given**, and the rest are worked out from it, from the cash flows that the tranche is paid when the deal is run
at its pricing speed, as of the closing date of the deal, which is when the buyer pays.

| Slot | Is | Units |
|---|---|---|
| `price` | what the buyer pays for each 100 of balance, without the accrued interest | 100 is par |
| `yield` | what the buyer earns: the bond equivalent yield of the cash flows | percent a year |
| `spread` | the yield over the Treasury curve at the average life of the tranche | basis points |
| `duration` | the modified duration | years |
| `oas` | the spread over the paths of rates that makes them worth the money (see "Option-adjusted spread and effective duration"); blank until they are run | basis points |
| `effective-duration` | the proportion the money falls by when rates rise, with the prepayments that follow; blank until the paths are run | years |
| `effective-convexity` | how much the effective duration changes as rates do: below 0 for a tranche that the borrowers' option shortens as rates fall; blank until the paths are run | years squared |
| `average-life` | the average life (see "Sequential by average life") | years |
| `dv01` | how much the money falls when the yield rises by a basis point, and nothing else is changed | dollars |
| `money` | what the buyer pays, in all: the balance times the price over 100, and the accrued interest | dollars |
| `delay` | the days from the end of the accrual period of its interest to the day it is paid (24 to begin with) | days |

```lisp
(define deal (new-deal "Demo 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :collateral '((100000000.0 6.5 6.0 360)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
(deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))    ; years, and yield in percent
(deal-set-price! deal "A" 100.5)                                              ; the rest of what A has is worked out
(node-yield (get-node deal "A"))               ; => 5.8457833561537464
(node-spread (get-node deal "A"))              ; => 155.92398872535912
(node-duration (get-node deal "A"))            ; => 3.9109519134294706
(node-average-life (get-node deal "A"))        ; => 4.730869378003109
(node-dv01 (get-node deal "A"))                ; => 23650.493554621935
(node-money (get-node deal "A"))               ; => 60490000.0
```

`(deal-set-price! deal name price)`, `(deal-set-yield! deal name yield)` and `(deal-set-spread! deal name spread)` give a tranche one of them, and work out the others;
`(deal-clear-price! deal name)` takes them away (the average life stays), and `(deal-set-delay! deal name days)` gives it a delay. Nothing is changed if something is wrong. A tranche
keeps **the one that was given**, as it was given: when the deal changes (its pricing speed, its collateral, its tranches, its dates, its index, its Treasury curve) the rest are worked out
again from it, so a price stays, and its yield follows the speed; a spread stays, and its yield follows the average life. `(deal-update-analytics! deal)` does it by hand: it returns a list of messages
for the tranches that could not be worked out (those have their slots cleared), which is empty if all is well. `(deal-pricing-table deal)` is a table of the slots, a row for each tranche, with
`nan` where a tranche has not got one.

**Accrued interest.** The buyer pays the interest that has accrued since the accrual period began, by the 30/360 day count (every month is 30 days, and a year 360;
`(days-360 from to)`): the balance times the coupon times the days over 360. The **delay** says where the period is: the first accrual period ends *delay* days before the
first payment date, and began a month before it ended. Here the first payment is 2026-12-25, so the period ends 2026-12-01 and began 2026-11-01, and 19 days have gone at the closing
date, 2026-11-20: 60,000,000 at 6% for 19 days is 190,000. A closing date after the end of the first period is an error, and nothing has accrued if the period has not begun.

```lisp
(accrued-interest deal (get-node deal "A"))    ; => 190000.0
(days-360 (date 2026 11 1) (date 2026 11 20))  ; => 19
```

**The yield** is a bond equivalent yield. The cash flows that the tranche is paid, its principal and its interest each month, on its payment dates (the first payment date, and a month
apart), are discounted by `(1 + yield / 200)` to the power of minus a sixth for each month from the closing date, the months being counted by the 30/360 day count; the money is what they
are worth, added up. The yield of a price is the one that makes them worth the money (found by Ridders' method, between -100% and 1000%), and the price of a yield is what the money
that they are worth is, less the accrued interest, per 100 of balance. The **duration** is the modified duration: the proportion that the money falls by for a rise of one (a hundred
percentage points) in the yield. The **dv01** is exactly what it says: the money at the yield, less the money at a yield a basis point (0.01 percent) higher, with the cash flows, and the
accrued interest, as they are.

**The spread** is the yield less the yield of the Treasury curve at the average life of the tranche, in basis points. The curve is a list of points, `(years yield)` with the yield in
percent, or a table with the columns `years` and `yield`, given to the deal with `(deal-set-treasury-curve! deal curve)` (or in `(info deal)`), and the yield at an average life is on a
straight line between the two points on either side of it, so that the yield for an average life of 2.25 is a quarter of the way from the two-year point to the three-year point; beyond the
ends of the curve it is that of the nearest point. A tranche that is paid no principal (an interest-only bond) has no average life, and no spread.

```lisp
(deal-set-treasury-curve! deal '((2 4.0) (3 5.0)))
(treasury-yield deal 2.25)                     ; => 4.25
(deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))
(treasury-yield deal 2.25)                     ; => 4.125
```

**+ and ?.** A price can be given as `"+"`, which sets the price of a tranche so that its money is exactly the money of its children, added up; and as `"?"`, which sets it so that the money of the tranche and of
all the tranches that are paid by the same split (its siblings) is exactly that of their parent. Each needs the others to be priced already. They give a price, and the tranche keeps it as a price.

```lisp
(deal-set-price! deal "A" 100.5)
(deal-set-spread! deal "B" 120)                ; B is to be 120 basis points over the curve at its average life
(deal-set-price! deal "POOL" "+")              ; the price of the pool that makes it worth what A and B are, together
(node-money (get-node deal "POOL"))            ; => 101974088.54376554
(deal-set-price! deal "POOL" 101.0)
(deal-set-price! deal "B" "?")                 ; the price of B that makes A and B together worth what the pool is
(node-price (get-node deal "B"))               ; => 101.75
(+ (node-money (get-node deal "A")) (node-money (get-node deal "B")))   ; => 101316666.66666667
(deal-set-delay! deal "A" 14)                  ; the accrued interest of A is less, so its money is: its price stays
(node-money (get-node deal "A"))               ; => 60390000.0
(node-price (get-node deal "A"))               ; => 100.5
```

**What it is as of, and what it is not.** The cash flows are those of the deal run at its pricing speed (and, for a tranche that floats, at the index that the deal was last run with: a deal
with a floating tranche that has not been run with an index cannot be priced, and says so). The slots are as of the closing date, so the deal needs a closing date and a first payment date. The
duration is the modified duration at that speed: nothing is done about what a change in rates would do to the speed (that is what the next section is for). A tranche is
priced by what it is paid: if the deal's loans default (see "Defaults, from the default model"), one that is written down is paid less, and its yield is less.

In a notebook the grid of the tranches, `(bonds deal)`, has a column for each slot beyond the cash flows (see "Building a deal by clicking"), and `(info deal)` a grid for the Treasury curve.

## Option-adjusted spread and effective duration

The yield of a tranche is of the cash flows it is paid if rates stay where they are, and the collateral prepays at the pricing speed whatever happens. It does not. When rates fall the
borrowers refinance, and a bond that was bought above par is paid back early, when it is worth most to keep; when rates rise they stay, and a bond bought below par is paid back late. A spread
over the Treasury curve leaves that out, and so does a modified duration. The **option-adjusted spread** (OAS) puts it in, and the **effective duration** says how much a bond falls in value when
rates rise, *with* the prepayments that follow.

The method is a simulation. The deal is run on many **paths of interest rates**, each a possible future (see "Interest rate paths" in the library manual). On each path the collateral is prepaid
by a **prepayment model**, which can look at the rates of the path, so the collateral pays differently on each, and so does every bond. A tranche is worth the **average**, over the paths, of
its cash flows, each discounted along its own path. The OAS of a tranche is the one spread, added to the short rate of every month of every path, that makes that average the money that the buyer pays.
An OAS of 0 is a price on the Treasury curve (the paths start on it, so their discount factors average to its); the more the borrowers' option is worth, the lower the OAS of a given price.
The code is in `lib/deal_paths.lsp`, and what a price says about it in `lib/deal_pricing.lsp`.

```lisp
(define deal (new-deal "Demo 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :collateral '((10000000.0 6.5 6.0 24)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
(deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))
(deal-run-paths! deal :paths 10)                             ; the deal is run on 10 paths, which prints how far it has got
(deal-set-price! deal "A" 100.5)                             ; the OAS and the effective duration are worked out with the yield and the rest
(node-yield (get-node deal "A"))                             ; => 4.674308479043608
(node-spread (get-node deal "A"))                            ; => 67.43084790436083
(node-oas (get-node deal "A"))                               ; => 66.1184998937952
(node-duration (get-node deal "A"))                          ; => 0.6427940046414851
(node-effective-duration (get-node deal "A"))                ; => 0.6552837891713873
```

`(deal-run-paths! deal :paths 200 :shift 0.0025 :seed 1)` runs the deal; the values written are the ones it has if they are left out. It needs the deal to have collateral made of pieces,
and a Treasury curve, which the paths start on (their forward rates are those of the curve: `(deal-forward-curve deal)`). **It takes a while.** The deal is run once for each path, and for
each of the two shifts of the curve below, three times in all, one after another; a run of a deal of 360 months takes about a second, so 200 paths take ten minutes or more, and the function says how
far it has got as it goes (`on the curve: 60 of 200 paths`). Nothing is done until it is called, and the paths are kept in the deal: a price, a yield or a spread that is given afterwards
has its OAS and its effective duration at once. A tranche that has a price already has them when the paths are run. `:paths` is how many paths (they come in mirror-image pairs, so that their average is the curve's own, and the number is made even);
`:seed` makes the same random numbers each time, so that a run can be repeated, and two tranches, or two deals, are compared on the same paths.

**An OAS can be given.** `(deal-set-oas! deal name oas)`, with the OAS in basis points, is a way to price a tranche, as a price, a yield and a spread are: the price is the one that makes the paths
worth what the OAS says, and the yield, spread, duration and the rest follow. It needs the paths to have been run.

```lisp
(define deal (new-deal "Demo 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :collateral '((10000000.0 6.5 6.0 24)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
(deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))
(deal-run-paths! deal :paths 10)
(deal-set-oas! deal "B" 50)                                  ; B is to be 50 basis points over the paths
(node-price (get-node deal "B"))                             ; => 101.94748948690255
(node-yield (get-node deal "B"))                             ; => 4.569726518502865
(node-spread (get-node deal "B"))                            ; => 50.53115736924801
(node-effective-duration (get-node deal "B"))                ; => 1.577949772214555
(node-priced-by (get-node deal "B"))                         ; => oas
(deal-set-price! deal "B" (node-price (get-node deal "B")))
(node-oas (get-node deal "B"))                               ; => 49.99999999999999
```

**The effective duration** is worked out with the curve moved up and down by the shift (0.0025, which is 25 basis points). The paths are made again on each moved curve, from the same random
numbers, the collateral is prepaid by the model on them, and the deal run; the tranche is valued on all three sets of paths at its OAS, which is held as it was. Its effective duration is the
proportion that its money falls by for a rise of one (a hundred percentage points) in rates: (money on the curve moved down, less money on the curve moved up) over twice the shift times the money on the curve. A
tranche whose cash flows do not change with rates has one near its modified duration (try a model that looks at no rates); one whose cash flows do is shorter or longer than that, because the prepayments change when rates do.

**The effective convexity** is of the same three values: (money on the curve moved down, plus money on the curve moved up, less twice the money on the curve) over the money times
the shift squared, in years squared. It says how much the effective duration changes as rates move. A bond whose cash flows do not change has a convexity above 0, at least its duration
squared: it gains more when rates fall than it loses when they rise. A tranche that the borrowers' option shortens as rates fall has one below 0: it gains less than it loses.
Some quote convexity divided by 100 (so that -150 here is -1.5 there).

**The parts.** Each is a slot of the deal, which the user can replace, and each has something to begin with.

| Part | Is | To begin with |
|---|---|---|
| rate model | the numbers that make the paths: `(make-rate-model :a 2.75 :b 0.15 :sigma1 0.019 :sigma2 0.012)`, as in `simulate-rate-paths` | the values in the library manual's fit; they are to be worked out from market data |
| prepayment model | a function `(model piece path)` of a `collateral-piece` and a `rate-path`, that gives the annual prepayment rate, in percent, of each month of the piece: a vector with as many months as its wam. A pricing speed of type `model` is a share of it; a pricing speed of another type does not look at rates, and the paths prepay at it (`static-prepayment-model`) | the one fitted to Freddie Mac's loans (see "The prepayment model") |
| index function | a function of the vector of short rates of a path, that gives the vector of the index that the floating tranches are of | the identity: the index is the short rate |

A `rate-path` has the two vectors `short-rates` and `long-yields`, a rate (a decimal) for the start of each month, from today: month 1 is the first payment, and the first rate is today's; and the date of the
first payment, `first-payment`. The model is free to look at them as it likes (it is given the piece, which says what the loans are: their wac, their age and so on), and it is called once for each piece on each
path. Here is one of one's own, which prepays at 5 CPR, and at more for every point that the short rate is under 4.5%; the pricing speed is made 100% of it:

```lisp
(define deal (new-deal "Demo 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :collateral '((10000000.0 6.5 6.0 24)) :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
(deal-set-treasury-curve! deal '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5)))
(deal-run-paths! deal :paths 10)
(deal-set-price! deal "A" 100.5)
(deal-set-oas! deal "B" 50)
(define (refinancing piece path)
  (let ((incentive (vector-clip (- 0.045 (vector-take (rate-path-short-rates path) (collateral-piece-wam piece))) 0.0 1.0)))
    (+ 5.0 (* 800.0 incentive))))
(deal-set-prepayment-model! deal refinancing)
(deal-set-pricing-speed! deal (prepayment-speed 'model 100)) ; this forgets the paths (see below)
(node-oas (get-node deal "A"))                               ; => ()
(deal-run-paths! deal :paths 10)
(node-price (get-node deal "A"))                             ; => 100.5
(node-oas (get-node deal "A"))                               ; => 49.56409369573326
(node-effective-duration (get-node deal "A"))                ; => 0.5223917758561567
(node-duration (get-node deal "A"))                          ; => 0.5878938713532995
(node-price (get-node deal "B"))                             ; => 101.86014674505945
```

A is bought at 100.5, above par: when the model has the borrowers prepay faster as rates fall, its option is worth more, its OAS is lower (49.6 basis points where 150 PSA on every path gave 66.1), and it falls less
in value when rates rise (an effective duration of 0.52 years, where its modified duration, of the cash flows that the model gives if rates follow the forward curve, is 0.59): it is called back before it can gain.
B was given its OAS, and it is the price that has changed, from 101.95 to 101.86.

`(deal-set-rate-model! deal model)`, `(deal-set-prepayment-model! deal model)` and `(deal-set-index-function! deal function)` give the deal its parts (`'()` takes one away, and the deal goes back to what it began with).

**What forgets the paths.** They belong to the deal as it is, so they are forgotten when it changes: its collateral, its tranches, its pricing speed, its dates, its Treasury curve, any of the three parts, or what
the prepayment model is told (the growth of home prices and the mortgage spread). The OAS and the
effective duration of the tranches are blank until `deal-run-paths!` is called again. A tranche that was given a price, a yield or a spread keeps it. One that was given an OAS keeps that, and has no price until
the paths are run, when it has one again. `(deal-forget-paths! deal)` does it by hand.

**How the numbers are worked out.** A month's cash flow is discounted by 1 / (1 + (short rate + OAS) / 12) for each month of its path up to it, as in "Mortgages and option-adjusted spread" in the library manual, except
that the first payment is the part of a month away that it is from the closing date (the same as the yield of a tranche, so that the two are alike when the rates do not change). `(path-present-values flows rate-paths oas [first-fraction])`
(a builtin: see the library manual) does the discounting of every path at once. The OAS of a price is found by Ridders' method, from -10000 to 50000 basis points, and is remembered for the price,
so the grid of a deal does not work it out again when it is redrawn. A deal with a floating tranche is run on each path with the index that the index function makes of that path's short rates.

In a notebook the grid of the tranches, `(bonds deal)`, has the columns `oas`, `effective duration` and `effective convexity` (see "Building a deal by clicking"), and an OAS is typed in the grid as a price is.


## The prepayment model

A pricing speed of type `model` is a share of a **prepayment model that looks at rates**: `(prepayment-speed 'model 105)` is 105% of what the model says, month by month (and,
as with any speed, the share can change with time: `(prepayment-speed 'model '((50 100 12)))` goes from 50% to 100% over a year). The model is the one fitted to a sample of
Freddie Mac's 30-year loans (see "Models fitted to Freddie Mac's loans" in the library manual, and `notebooks/freddie_prepayment_model.ipynb`), which comes with the library
in `lib/freddie_prepayment_fit.json`; a deal can be given one of its own instead, with `deal-set-prepayment-model!`.

**What it looks at.** For each piece of collateral, and each month, 1 to its wam (`(prepayment-model-columns piece path)`):

| What | Is |
|---|---|
| the incentive | the wac less the rate of a new mortgage at the start of the month: the 10-year Treasury yield of the path of rates, plus the **mortgage spread** of the deal (1.75 percent to begin with) |
| the age | the piece's, and a month more each month |
| the loan size, and the loan-to-value | the piece's, paid down by the scheduled payments; the loan-to-value falls, too, as home prices grow by the deal's **growth of home prices** (3 percent a year to begin with) |
| burnout | the piece's, and a month more for each month in the money (an incentive above 75 basis points, after the first year) |
| the credit score, the spread at origination, and the shares on investment properties and second homes and of refinances | the piece's, the same each month |
| the season | from the date of the first payment |

A piece that does not say what its loans are like (its slot is `'()`) is taken to be like `unknown-piece`: $250,000 loans, a credit score of 750, 70% loan-to-value, purchases of
homes to live in. The model's answer is the CPR of each month.

**Where the rates come from.** The cash flows at the pricing speed, which the yield, the spread and the duration are of, are what the model says if rates follow the
**forward curve** of the deal's Treasury curve (`(deal-forward-path deal months)`: the curve read forward, with no randomness), so a speed of the model needs a Treasury curve.
On the paths of rates that `deal-run-paths!` makes, the collateral prepays as the model says it does on each path, so the OAS and the effective duration take in what the
borrowers' option is worth. The two are what the deal tells the model of the future, and are its slots: `(deal-set-home-price-growth! deal percent)` and
`(deal-set-mortgage-spread! deal percent)`, or the fields under the pricing speed in `(info deal)`, where MODEL is a type of speed.

```lisp
(define deal (new-deal "Model 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :treasury-curve '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5))
                       :collateral (list (make-collateral-piece :balance 10000000.0 :wac 6.5 :coupon 6.0 :wam 60 :age 3
                                                                :credit-score 750 :ltv 75.0 :loan-size 350000))
                       :speed (prepayment-speed 'model 100)))
(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
(define (cpr-in-month month) (annual-rate (vector-ref (model-speed-smms deal (deal-pricing-speed deal) (car (deal-pieces deal))) (- month 1))))
(cpr-in-month 1)                                             ; => 8.740078153786657
(cpr-in-month 12)                                            ; => 19.432766343577747
(deal-set-mortgage-spread! deal 1.0)                         ; mortgage rates 0.75 lower: the loans are 100 basis points in the money
(cpr-in-month 1)                                             ; => 25.449261480205486
(deal-set-mortgage-spread! deal 1.75)
(deal-set-pricing-speed! deal (prepayment-speed 'model 150))
(cpr-in-month 1)                                             ; => 13.110117230680007
(deal-set-pricing-speed! deal (prepayment-speed 'model 100))
(deal-set-price! deal "A" 100.5)
(deal-run-paths! deal :paths 10)
(node-spread (get-node deal "A"))                            ; => 117.58752714778478
(node-oas (get-node deal "A"))                               ; => 78.91073186529778
(node-duration (get-node deal "A"))                          ; => 1.0064532280939644
(node-effective-duration (get-node deal "A"))                ; => 0.5797211881725738
```

The loans are 25 basis points in the money at first (6.5% against 4.5% + 1.75%), and season from 8.7 CPR to 19.4 in a year. A, bought above par, has an OAS 39 basis points
below its spread, and an effective duration of 0.58 years where its modified duration is 1.01: when rates fall the loans prepay faster, and A is paid back before it
can gain. For a 30-year pool of the same loans, divided the same way, with 20 paths:

| | 150 PSA | MODEL 100 |
|---|---|---|
| A, at 101: spread and OAS | 143 and 143 | 129 and 5 |
| A: duration and effective duration | 3.76 and 3.85 | 2.20 and 1.03 |
| B, at 99: spread and OAS | 155 and 170 | 162 and 85 |
| B: duration and effective duration | 9.73 and 9.91 | 8.10 and 4.50 |

At 150 PSA, the same on every path, the OAS is about the spread and the effective duration about the duration: nothing is worth anything but the curve. With the model,
the OAS is less by what the borrowers' option is worth, and the effective duration is about half the duration.


## Hedging a tranche

A tranche can be hedged with Treasuries and with the collateral of the deal: positions that, with the tranche, lose nothing for a small move in rates either way. `lib/deal_hedge.lsp`
works them out, from the effective durations and convexities of the paths of rates, so the tranche must be priced, and the paths run.

**The Treasuries.** `(treasury-measures deal)` is a table with a row for a par Treasury at each maturity of the deal's Treasury curve: its coupon is the curve's par yield there,
paid every six months, so that it is worth 100. It is valued off the zero curve that the par yields give (`par-curve-zeros`), and with all the zero rates moved up and down by the
shift that the paths were moved by, as the tranche is, so that its effective duration and effective convexity are the same measures as the tranche's. A Treasury's convexity is
above 0, and at least the square of its duration (more, the longer its cash flows are spread out: the 30-year's is 366, and its duration 16).

**The hedge.** A position of market value M (the money of the tranche), effective duration D and effective convexity C has a **dollar duration** of M x D, what it loses for a rise
of one in rates, and a **dollar convexity** of M x C. The hedge is positions h1 and h2, in dollars of market value (below 0 for what is sold), in two instruments, that make the dollar
duration and the dollar convexity of the tranche and the two together 0:

```text
M D + h1 D1 + h2 D2 = 0          M C + h1 C1 + h2 C2 = 0
```

Two instruments are enough to make both 0, and of every pair of the instruments (the Treasuries, and the collateral, if it has been priced, and is not the tranche itself), the hedge
is the one that does it with the least in all, |h1| + |h2|: a hedge is a cost to keep, and a big long and a big short that cancel are a bet on the difference between them.
`(deal-hedge deal name)` is a table of the tranche, the two positions, and the net of them all, whose dollar duration and dollar convexity are 0; `(deal-hedge-pairs deal name)` is
every pair, the one with the least in all first.

```lisp
(define deal (new-deal "Hedge 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :treasury-curve '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5) (30 4.8))
                       :collateral (list (make-collateral-piece :balance 10000000.0 :wac 6.5 :coupon 6.0 :wam 60 :age 3
                                                                :credit-score 750 :ltv 75.0))
                       :speed (prepayment-speed 'model 100)))
(deal-sequential! deal "POOL" '(("A" 6000000.0) ("B" 4000000.0)))
(deal-set-price! deal "POOL" 101.0)                          ; the collateral is priced, so it can be a hedge
(deal-set-price! deal "B" 100.0)
(deal-run-paths! deal :paths 10)
(node-effective-duration (get-node deal "B"))                ; => 2.3020023036820145
(node-effective-convexity (get-node deal "B"))               ; => -57.04650713969748
(define treasuries (treasury-measures deal))
(table-column treasuries "instrument")                       ; => #("1y Treasury" "2y Treasury" "3y Treasury" "5y Treasury" "10y Treasury" "30y Treasury")
(vector-ref (table-column treasuries "effective duration") 4)    ; => 8.149515477396818
(vector-ref (table-column treasuries "effective convexity") 4)   ; => 75.42947965357598
(define hedge (deal-hedge deal "B"))
(table-column hedge "position")                              ; => #("B" "10y Treasury" "POOL" "net")
(table-column hedge "market value")                          ; => #(4012666.6666666665 -619481.1685778834 -3580302.462053031 -187116.96396424808)
```

B, of a convexity below 0, is hedged mostly with the collateral, which has one below 0 too (-77), and a little of the 10-year Treasury: sell $3.58 million of the collateral and $0.62
million of the 10-year, for the $4.01 million of B. A tranche hedged with Treasuries alone needs a long one and a short one, as Treasuries have convexities above 0 and the tranche one
below: the one of greater convexity is bought, and the other sold.

The hedge is of small moves, as durations and convexities are: it is to be done again as rates move, and the tranche's duration with them. It is of the model, too: of its paths of
rates, and of its prepayment model, which the effective duration and convexity of a tranche of mortgages are mostly of.

## Losses and shortfalls

Both apply to some deals only. A deal with no losses has none, and a deal is only run with shortfalls if it asks for them.

A deal made from pieces of collateral loses nothing, to begin with: its collateral pays all of its principal, so every loss is 0, and the interest it pays is what its bonds are
owed. It can be told that its loans default, as the default model fitted to Freddie Mac's loans says (see the next section): then its collateral loses what is lost when the
homes of the loans that default are sold, and the tranches are written down by their rules. What follows that is what the tree does when the collateral loses something, or pays
less interest than the bonds are owed, which is a matter of the vectors of the collateral node, its `loss` and its `interest`.

### Defaults, from the default model

`(deal-set-defaults! deal 100)` makes the loans of the deal default as the default model fitted to Freddie Mac's loans says (see "Models fitted to Freddie Mac's loans" in the
library manual): 100 is the model, 200 is twice it, and 0, as to begin with, is no defaults. Each month, that share of the model's default rate of the loans that are still
being paid default. What the model looks at, for each piece of collateral and each month (`(default-model-columns piece path)`), is its credit score, its loan-to-value now (paid
down by the scheduled payments, and falling as home prices grow by the deal's growth of home prices: see "The prepayment model"), its age, its debt-to-income, the spread at
origination, the incentive, the loan size, the shares on investment properties and second homes, of cash-out and other refinances, and with one borrower; a piece that does not
say is taken to be like `unknown-piece`.

A loan that defaults stops paying. Its interest is advanced to the investors until its home is sold, `liquidation-lag` months later (18 to begin with,
`(deal-set-liquidation-lag! deal months)`): then what the sale brings back, 1 less the **severity** of its balance, is paid as principal, and the rest is a **loss** of the
collateral, which writes the tranches down by their loss rules (see "Losses", below). The severity is what the severity model says of the loans that default in the month: it
looks at their loan-to-value then, their balance, their mortgage insurance (the piece's `mi-percent`), the months to the sale, and the share on investment properties
(`(severity-model-columns piece path)`). It is Freddie's measure of what was lost: the balance, the unpaid interest (which the advances have paid) and the costs, less what the
home sold for and what mortgage insurance and others paid. The deal runs on for the months of the lag, until the last sale.

```lisp
(define deal (new-deal "Losses 2026-1" :closing-date (date 2026 11 20) :first-payment (date 2026 12 25)
                       :treasury-curve '((1 4.0) (2 4.1) (3 4.2) (5 4.3) (10 4.5) (30 4.8))
                       :collateral (list (make-collateral-piece :balance 100000000.0 :wac 6.5 :coupon 6.0 :wam 357 :age 3
                                                                :credit-score 700 :ltv 90.0 :loan-size 300000))
                       :speed (prepayment-speed 'psa 150)))
(deal-sequential! deal "POOL" '(("A" 85000000.0) ("M" 10000000.0) ("B" 5000000.0)))
(deal-set-defaults! deal 100)                          ; the default model, as it is
(deal-run! deal)
(deal-periods deal)                                    ; => 375
(define (lost name) (vector-sum (node-loss (get-node deal name))))
(lost "POOL")                                          ; => 1754714.9066060549
(lost "B")                                             ; => 1754714.9066060549
(lost "M")                                             ; => 0.0
(define (in-month month)                               ; the CDR and the severity of the loans that default in the month
  (let ((defaults (deal-piece-defaults deal (car (deal-pieces deal)) (deal-forward-path deal 357))))
    (list (annual-rate (vector-ref (car defaults) (- month 1))) (vector-ref (cadr defaults) (- month 1)))))
(in-month 36)                                          ; => (0.8337622193992256 0.3878215509270752)
(deal-set-home-price-growth! deal -5.0)                ; home prices fall 5% a year
(deal-run! deal)
(lost "POOL")                                          ; => 15732036.226627294
(lost "B")                                             ; => 5000000.0
(lost "M")                                             ; => 10000000.0
(lost "A")                                             ; => 732036.2266272897
(in-month 36)                                          ; => (2.8236214781029445 0.5072390617767402)
```

The loans, of 90% loan-to-value and a credit score of 700, default at under 1 CDR while home prices grow 3% a year, and lose about 40% when they are sold: the pool loses 1.75% of
its balance, all of it from B, the last of the sequence. If home prices fall 5% a year, the loan-to-value rises, more default (2.8 CDR in the third year), each loses more (51%),
and the pool loses 15.7%: B and M are written off, and A loses $732,036. The deal runs for 375 months: the 357 of the loans and the 18 to the last sale.

The default model looks at the rates read forward from the deal's Treasury curve, as the prepayment model does, so a deal whose loans default needs a curve; on the paths of
rates of `deal-run-paths!` they default as the model says on each path. In a notebook, `(info deal)` has the defaults, as a percent of the model, and the months from a default
to the sale. In an agency deal the agency buys a loan that defaults out of the pool: the bonds are paid all of it, as a prepayment, and the loss is the agency's. The losses
matter to a deal of loans that no one guarantees, and to the bonds that share an agency's losses.

### Losses

A **loss** is balance written off, with no cash: the collateral's `loss` vector (`node-loss` of the collateral) says how much, each month. A deal whose
collateral has none is not touched by any of this. Each month, after the principal, the loss is divided among the children of the collateral by its
split, and among theirs by theirs, down to the bonds, whose balances it reduces: a node's `loss` vector is what it was written down by, and a bond can
not be written down by more than it has left (its balance and what it accrues, less what it was paid that month). Interest is of the balance at the
start of the month, so the month's loss does not reduce that month's interest.

How a split divides a loss is its **loss rule**:

- `reverse`: the last child first, up to what it has left, and then the one before it. This is the rule of a sequential split, and of a PAC split (so
  the companion is written down before the PAC), unless it is made with another: the bonds paid last, the junior bonds, are written down first;
- `forward`: the first child first;
- `pro-rata`: in proportion to what each child has left. This is the rule of a pro-rata split, and so of a floater and inverse floater and of a premium
  and discount.

`:losses` on `deal-sequential!`, `deal-pro-rata!` and `deal-pac!` makes a split with another rule: `(deal-sequential! deal "A" '(("A1" 50.0) ("A2"
30.0)) :losses 'pro-rata)` pays the principal to `A1` first, and shares a loss between the two by what each has left. An IO/PO split writes the PO
down (the IO's notional balance follows the PO's, so it falls too).

A deal of **senior and subordinate bonds**, with `A` bonds that share a loss and `B` bonds that are written down from the bottom up, is a tree
of sequential splits, the first dividing the pool into the `A` bonds and the `B` bonds (reverse, so that the `B` bonds are written down first), and
one for each:

```text
POOL (100) -- sequential (reverse) --> A (80) -- sequential, :losses 'pro-rata --> A1 (50), A2 (30)
                                       B (20) -- sequential                     --> B1 (15), B2 (5)

The pool pays principal of 20, 20, 15, 10 and 10, and loses 25 in the second month:
  B2 is written down by 5 and B1 by 15, in that month; A1 by 1.25 and A2 by 3.75
```

The pool loses 25 in the second month. `B2` is written down by its 5 and `B1` by its 15; the other 5 is shared by the `A` bonds: after that month's
principal `A1` has 10 left and `A2` 30, so `A1` is written down by a quarter of it, and `A2` by three quarters. The `A` bonds are paid principal in
order, all the same.

A loss that the bonds have not enough left to take is an error (the collateral's balance is its own, and a loss of more than it has is wrong).
`(deal-loss-table deal)` has what each node was written down by. A write-down is permanent: there is no write-up from a later recovery.

### Interest shortfalls

Each bond is owed a twelfth of its coupon on its balance, and the cash for it is the interest of the collateral, which a collateral's own model may
say is less. A deal that is right owes exactly what it is paid, and by default it is an error if it does not (a deal with coupons that do not add
up to the collateral's has a mistake in it). A deal made with **`:shortfalls #t`** (`(new-deal name ... :shortfalls #t)`) is one in which that can be so, and the interest that the bonds
are owed and are not paid is their **shortfall**:

```text
POOL (100) pays 20 of principal a month, and interest of 0.9, 0.8, 0.70201, 0.4 and 0.2
POOL -- sequential --> A (80), B (20), both owed 12% a year, 1% a month, on their balances

B is paid interest of     0.1  0.2    0.30201  0.2  0.2
B has a shortfall of      0.1  0.101  0.0      0.0  0.0
```

- A bond (a node with nothing under it) is owed, in a month, its interest for the month, **and what it was owed and not paid the month before, with a
  month's interest on that at its coupon**: `0.2 + 0.1 x 1.01 = 0.301` for `B` in the second month. A node that is divided is owed what its children are.
- What there is is paid in the split's order of priority: a sequential split pays its first child what it is owed, and then the next, so the
  junior bonds go without; a pro-rata split pays each child the same share of what it is owed, so they share the shortfall.
- What a bond is owed and is not paid is its `shortfall` for the month, carried to the next. In the example the pool is 0.1 short in the first month,
  so `A` is paid in full and `B` has a shortfall of 0.1 (0.2 owed, 0.1 paid); in the third month the pool pays 0.70201, which is what is owed, and
  the shortfall is paid.
- A Z bond accrues only as much as there is cash for, after the bonds before it; the rest is its shortfall.
- Interest that there is more of than the bonds are owed is an error, with or without shortfalls: excess interest is not modeled.
- With shortfalls the interest the collateral is paid is not compared with what it is owed, since the collateral is paid what its model says;
  `deal-check` checks the bonds.

`(deal-shortfall-table deal)` has the shortfall of each bond at the end of each month.

### What is not modeled

Principal that is not paid is still owed, and a bond is not written down for it, so there is no principal shortfall. There are no recoveries after a
write-down, no triggers or turbo payments, no excess spread, no fees (the collateral's coupon is what the bonds are paid), and one index.

## Checking a deal

`(deal-check deal)` is `#t`, or an error that says what is wrong and where, if, in every month (to within the tolerance):

- no balance has gone below 0;
- the children of a split were paid, in principal, what their parent was paid, and what its Z bonds accrued;
- the children of a split were written down by what their parent was;
- every bond was paid, or accrued, or carried as a shortfall, exactly the interest it was owed; in a deal without shortfalls every node with a coupon
  was paid what its coupon says;
- the children of a split were paid, in interest and accrual, what their parent was paid;
- the coupons of the children of a split add up to the parent's, on their balances;
- a notional bond has no principal and no loss, and its balance is its share of the balance it follows.

A deal that is built with the builders and run is right, and `deal-check` is for the changes that are made to one by hand, and for the data it
was given. A mistake in a floater's cap, say, makes the coupons stop adding up, and is found.

## Making another kind of split

A split is a struct, a type that includes `split`, and what makes a kind of split what it is are its **methods**: functions chosen by the kind of the
split (see `defgeneric` and `defmethod` in the language manual). `(generic-function-methods pay-principal)` lists the kinds that have one.

- `(pay-principal split deal parent t)` divides the principal that `parent` was paid in month `t` among the split's children, by calling
  `(pay-child! child t cash [floor])` for each one it pays. That pays the child what it is still owed (`(node-owed child t)`) up to the `cash`, but not
  so that it owes less than the `floor` (0 unless given, so that it is paid off), and returns the cash left. It does not call the splits of the
  children.
- `(pay-interest split deal parent t)` does the same for the interest. The methods for `split`, any kind, and for `pro-rata-split` are made of
  `(settle-interest! deal split parent t pay)`, which works out what each child is owed (`node-interest-owed`), calls `(pay owed cash total)` for
  what each is paid, and does the rest: the Z bonds, the shortfalls, the errors.
- `(allocate-loss split deal parent t)` divides the loss of the month, by `(write-down-child! child t amount)`, which writes the child down by the
  amount, up to what it has left, and returns the amount left. The method for `split` is the loss rules above.
- `(calculate-sizes split deal parent)` works out how big the children are, as a list of their starting balances in the order of the children, or
  `'()` if it is not for the split to say (the method for `split`, any kind, does): the sizes are as the children were made. A PAC split sizes its PAC
  from what its parent is paid at two speeds, a floater and inverse floater split from a cap, and a premium and discount split from the two coupons.
- `(assign-coupons split deal parent)` gives the children their coupons, which for a split of any kind are the parent's.
- `(check-split split deal parent)` is an error if the split cannot divide the parent: a Z bond is only a child of a sequential split, and an IO/PO
  split needs an IO that follows its PO.
- `(split-label split)` says in a few words what kind of split it is (`"sequential"`, `"PAC and companion"`), for the outline of the deal and the deal builder.

A new kind includes `split`, or one of the kinds there are, and has methods of its own; `(call-next-method)` calls the method of the kind that it
extends. This one does what a sequential split does, and says what it is dividing:

```lisp
(defstruct (noting-split (:include sequential-split)))

(defmethod pay-principal ((split noting-split) deal parent t)
  (display (format "month {}: dividing {}\n" t (vector-ref (node-principal parent) t)))
  (call-next-method))
```

A kind with data of its own (a PAC has `low-psa`, `high-psa` and its `schedule`) has slots for it. A method is looked up by the kind of the first
argument, so a method for `sequential-split` is also the method for `noting-split`, until it has one of its own.

## The deal object, and its views in a notebook

A deal in a notebook is an object, `(new-deal name ...)`, that has the **data** of its collateral, and the tranches of its tree, and a few other things, and that is looked
at, and changed, in **views**, each in a cell of its own. The views of one deal can all be shown at once, and what is changed in one is shown in the others.

```lisp
(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25) :closing-date (date 2026 11 20)
                       :speed (prepayment-speed 'psa 150)
                       :collateral '((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.5 240 12))))
(deal-size deal)                                     ; => 150000000.0
(deal-periods deal)                                  ; => 360
(deal-sequential! deal "POOL" '(("A" 90000000.0) ("B" 60000000.0)))
(deal-run! deal)
(vector-ref (node-principal (get-node deal "POOL")) 0)    ; => 332955.9512527855
(describe-speed (deal-ran deal))                     ; => "PSA 150"
(deal-run! deal (prepayment-speed 'psa 300))
(vector-ref (node-principal (get-node deal "POOL")) 0)    ; => 490518.1687694521
(deal-check deal)                                    ; => #t
```

**What a deal has.**

- The **collateral**, as data: a table with a row for each piece, the columns `balance`, `wac`, `coupon`, `wam` and `age` (see "Pieces of collateral, and the pricing speed"),
  which `(collateral-table pieces)` makes from a list of pieces, and a table of your own, from a file, say, can be (it does not need the `age`). `:collateral` of
  `new-deal` is a table or a list of pieces, and `(deal-set-collateral! deal collateral)` changes it later: the cash flows are worked out again, and the tranches below are
  too. The collateral can be left out, and given later: a deal with none has no months to run for.
- The **tranches**, by name, which always begin with one, the special tranche that is the cash flows of the collateral, the root of the tree (it is called `POOL`, or
  `:collateral-name`). They are divided as before, with the builders and the plans.
- The **pricing speed** (`:speed`, 100 PSA to begin with, and `(deal-set-pricing-speed! deal speed)`): a prepayment speed, made by `prepayment-speed`, with a type, PSA, CPR or SMM, and
  a single number or linear pieces. It is what the cash flows of the collateral are, and what the sizes of the tranches that depend on them are worked out at (a bond sized by
  its average life, say); `deal-run!` is given the speed to run at, which is another matter, and does not change the sizes.
- The **first payment date** (month 1, `(deal-set-first-payment! deal date)`), the **closing date** (`(deal-set-closing-date! deal date)`) and the **name**.

**What changing the collateral does.** The cash flows of the collateral are worked out at the pricing speed, and the deal runs for as many months as its longest piece (every
tranche has its vectors made as long). The tranches below are given their sizes and coupons again, from the top down, as in "Changing a split, and taking one away": a tranche
whose size was given keeps the share of its parent that it was, and one whose size is worked out (a PAC, a floater, a bond sized by its average life) has it worked out again.
It is tried on a copy first, so that if anything below cannot be worked out, an error says what, and the deal is as it was. The same goes for a change of the pricing speed.

```lisp
(deal-set-collateral! deal '((200000000.0 6.5 6.0 360)))
(deal-size deal)                                     ; => 200000000.0
(vector-ref (node-balance (get-node deal "A")) 0)    ; => 120000000.0
```

**A floater from pieces.** The collateral pays interest at the pass-through coupon of its pieces, and if they all have the same one it is a **fixed coupon**, whatever their wacs are,
so a floater and an inverse floater, or a premium and a discount bond, can be made of it. If the coupons differ, the coupon changes from month to month as the pieces pay off, and a split
that needs a fixed coupon says so.

```lisp
(define two (new-deal "Two" :collateral '((100000000.0 6.5 6.0 360) (50000000.0 7.5 6.0 240 12))))
(deal-floater-inverse! two "POOL" "F" "I" :cap 0.0975)
(vector-ref (node-balance (get-node two "F")) 0)     ; => 92307692.3076923
(deal-ran two)                                       ; => #f
(deal-run! two :index 0.04)
(describe-speed (deal-ran two))                      ; => "PSA 100"
```

`(deal-ran deal)` is `#f` if the deal has been changed since it was run, and otherwise the speed that it was run at.

**The cash flows of a tranche.** `(deal-flows-table deal name [:months list])` is a table of what a tranche was paid and owed in the last run, a row for each month (or for the months
in the list): the month, the payment date, if the deal has a first payment date, the balance at the start of the month, the principal, the interest, and what it accrues, is written down by or
carries as a shortfall, if it ever does. `(deal-summary-months periods)` is the months to show when all of them are too many: the first, the last of each year, and the last.

```lisp
(map car (deal-flows-table deal "A"))                ; => ("month" "payment date" "balance" "principal" "interest")
(deal-summary-months 30)                             ; => (1 12 24 30)
```

**The views.** Each is a function that returns a widget, which a cell of a notebook shows (see "Widgets in a notebook"):

```lisp
(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25)))
(display-widget (info deal))          ; the name, the dates and the pricing speed
(display-widget (collateral deal))    ; the pieces of collateral, to type in
(display-widget (bonds deal))         ; the tranches, to divide them, and to look at their cash flows
```

- `(collateral deal [:rows 8])` (in `lib/deal_views.lsp`) is a **grid** of the collateral, a row for each piece, and empty rows to type in: its balance, its wac in percent (the weighted
  average coupon of the loans), its pass-through coupon in percent (what the investors are paid: the wac less the fees, so no more than the wac), its wam (the months that are left) and its age
  (the months the loans have gone, 0 if new), and then what the loans are like (see "Pieces of collateral, and the pricing speed"), a blank cell being not known. Double-click a cell to type in it.
  A row with no balance is left out. **Show the cash flows** adds up the cash flows of the pieces that are
  in the grid, at the pricing speed, and shows them: how many pieces there are, the balance, the wac, the pass-through coupon, the wam, the average life and the speed in words, and a table
  with a row for the first month and the end of each year (the payment date, the balance, the principal, the interest paid to the investors, the speed of the month, and the wac and the
  pass-through coupon of the pool, which change as the pieces with the higher rates pay off). **Update the deal** gives the deal what is in the grid (`deal-set-collateral!`).
- `(info deal)` is a few fields: the name, the closing date, the first payment date (written `2026-12-25`, or left blank), the Treasury curve (a grid of the years and the yield in percent of its points, with empty rows to type in, that a
  spread is over: see "Prices, yields and spreads"; **Get the latest curve** puts the Treasury's most recent par yield curve in the grid, from its website (`latest-treasury-points`), and **Update the deal** gives it to the deal), and the pricing speed, a type (PSA, CPR, SMM or MODEL) and a grid of
  pieces, each *from*, *to* and *months*, which is a speed that goes in a straight line from one to the other and is *to* in the last of the months; the last piece has 0 months, for the rest of
  the time, and one row with the same speed twice is a single speed. Under the speed are what the prepayment model is told, the growth of home prices and the mortgage spread
  (see "The prepayment model"); MODEL 100 is 100% of the model. The first row is always a piece, and any other row with nothing in it is left out. **Update the deal** gives the deal
  what is typed, and nothing is changed if something is wrong.
- `(bonds deal)` is the grid of the tranches (see "Building a deal by clicking"), with a column beside the split to click for the cash flows of a tranche.

What is wrong with what was typed is said as a line under the buttons: no collateral, a wac below 0, a pass-through coupon above the wac, a wam that is not a whole number of months, a date that is not
one, a speed that goes from one value to another with no months to do it in, a split below that cannot be worked out again. `notebooks/new_deal.ipynb` is a notebook with the three views.

**How the views are told.** A view is added to a deal with `(deal-add-view! deal kinds refresh)`: `kinds` is a list of the symbols `collateral`, `tranches` and `info`, and `(refresh)` is
called, to show the deal as it is now, whenever the deal changes in one of those kinds. `(deal-changed! deal kind ...)` says that it has: the functions that change a deal call it, and
an error in a view is said, and does not undo the change. A deal that has changed has not been run since: `deal-ran` is `#f`. The views of a notebook are made this way, and so can others be.

## Building a deal by clicking

`lib/deal_builder.lsp` is a way to build a deal in a Jupyter notebook (the `morris_lisp` kernel, with `ipywidgets` and `ipydatagrid`; see "Widgets in
a notebook") by clicking, instead of by writing the builders. The deal begins as the collateral alone, one tranche with the cash flows of the pool:

```lisp
(define deal (new-deal "Demo 2026-1" :first-payment (date 2026 11 25) :collateral '((100000000.0 6.5 6.0 360))))
(display-widget (bonds deal))
```

`(bonds deal [:style "tabs"] [:forms forms])` (also called `deal-builder`) makes a **grid** with a row for each tranche of the deal (the rows of `deal-outline`: name, balance,
and the kind of split, and a column of *view*, to look at the cash flows), and a panel under it. It is a view of the deal, like `(collateral deal)` and `(info deal)`: it can be shown
at the same time as they are, and shows what they change (the balance of the collateral, the sizes below it).

- **Click a tranche that is not divided**, and the panel has a tab (or, with `:style "accordion"`, a section) for each kind of split: **Sequential**, **Average life**,
  **Pro rata**, **PAC**, **Floater/inverse**, **Premium/discount** and **IO/PO**, each with the fields that kind needs, and names to start with that are made from the
  tranche's. The tranches of a sequential or a pro-rata split are written one to a line, the name and the balance (`A1 60,000,000`), with `z`
  after the balance for a Z bond, and the last can leave its balance out and be what is left. Those of an average-life split are written the name and the average
  life in years (`A1 2`), and the one that has none (`A3`), which can be anywhere, is what is left. A PAC has two speeds, a floater and an inverse floater a cap and a
  margin (in percent), a premium and a discount bond their coupons, and an IO and a PO an IO coupon, or none, for the parent's.
- **Calculate the sizes** shows what the tranches would be, as a table, without changing the deal: the tranches of the split and any under them, their balances,
  the share of their parents' that each is, and their average lives, at the pricing speed (a copy of the deal is run to find them). It is the plan applied to a copy of the deal (`deal-trial-of-plan`), so what is wrong with the fields is said here,
  and what would be wrong when the tranches are added is too.
- **Add the tranches to the deal** adds them (`deal-add-plan!`). They appear in the grid under the tranche that was divided, so that the rows are the tree of the
  deal, depth first, and the panel is put away.
- **Click a tranche that is divided**, and the panel shows its split, with the fields as it was made: its tab is in front, with the tranches, the speeds, the cap
  that it has. Change them, and **Calculate the sizes** shows what is under the split as it is, and as it would be (a column, *was*, for the tranches that are
  in the deal already), and **Change the split** makes the change (`deal-replace-split!`): the tranches of the split are worked out again, and so are those under
  them, to the leaves. Another tab will change the split to a split of another kind, with the same tranches or others.
- **Take away this split, and all under it** is under the panel whenever a tranche that is divided is chosen. It says which tranches would go, and asks; **Yes**
  takes them away (`deal-delete-split!`), and **No** keeps them.
- **Type a price, a yield or a spread, in the cell of a tranche** (double-click the cell, or click it and type: a price of `+` or `?` is typed after a double-click, which opens the cell), and the others are worked out (see "Prices, yields and spreads"): the grid has
  a column *balance chart* with a little chart of the balance of each tranche month by month, all on one scale (the biggest balance, over the months of the longest tranche, so that a small tranche is a small chart: see `sparklines` in the language manual),
  the columns *price*, *yield*, *spread*, *oas*, *duration*, *effective duration*, *effective convexity*, *average life*, *dv01*, *money* and *delay* after the cash flows, and a price, a yield, a spread, an OAS and the delay are typed
  (the OAS and the effective duration are blank until the paths of rates are run, with `(deal-run-paths! deal)`: see "Option-adjusted spread and effective duration"). A price can be typed as `+` or `?`, and
  a cell that is cleared takes the price away. What is typed in a column that is worked out is put back, with a line to say so, and so is text that is not a number. The Treasury curve that a spread is over is
  in `(info deal)`, and what is typed in the grid stays when the deal changes: the rest is worked out again.
- **Click *view*, in the column of cash flows beside the split**, and the cash flows of that tranche are shown under the grid: what it is, its average life, the speed that the deal was
  run at, and a table (see `deal-flows-table`) with a row for the first month and the end of each year. The deal is run first, at the pricing speed, if it has changed since it was last run (or if
  it was never); a deal that was run by hand, with `(deal-run! deal speed)`, shows that run, until it changes. A floater needs the index, so a deal with one must have been run with `:index`
  (the same index is used when it is run again).

What is wrong is shown as a line under the buttons, with no traceback: the names that are in the deal already, balances that do not add up, a cap below the coupon,
a tranche left out that has a split under it. The deal is the one that was given, and is changed as the buttons are pressed: `deal-run!` and `deal-check` are for when it is built (and
the cash flows column runs it). `notebooks/deal_builder.ipynb` is a notebook that does this.

**A form of your own.** Each tab is a `split-form`, made by `make-split-form`, with these slots:

| Slot | Is |
|---|---|
| `:title` | the title of the tab |
| `:label` | what `split-label` says of the splits that it makes: the tab that is shown for a split that is in the deal is the one with its label |
| `:help` | a line of HTML above the fields |
| `:fields` | the fields, each `(name kind label default [options])`: see `widget-actions` in the language manual (`number`, `integer`, `text`, `textarea`, `checkbox`, `dropdown`) |
| `:defaults` | `(lambda (parent) ...)`: a list of `(field-name . value)` to put in the fields when the tranche `parent` is chosen |
| `:describe` | `(lambda (deal split) ...)`: the list of `(field-name . value)` that makes a split that is in the deal; without it a tab shows its defaults for a split that is changed |
| `:plan` | `(lambda (parent answers) ...)`: the plan that divides the node `parent` as the answers, a list of `(field-name . value)`, say, or an error that says what is wrong |

`(standard-split-forms)` is the list that is used without `:forms`, and a form of your own is added to it (a kind of split of your own, with its methods, as in "Making another
kind of split", has a `split-label` method, and a form with that label):

```lisp
(define halves
  (make-split-form
    :title "Halves" :label "sequential" :help "Two tranches of half each."
    :fields (list (list "first" 'text "First" "") (list "second" 'text "Second" ""))
    :defaults (lambda (parent) (list (cons "first" (string-append (node-name parent) "-1"))
                                     (cons "second" (string-append (node-name parent) "-2"))))
    :plan (lambda (parent answers)
            (let ((half (/ (vector-ref (node-balance parent) 0) 2.0)))
              (sequential-plan (list (list (cdr (assoc "first" answers)) half)
                                     (list (cdr (assoc "second" answers)) half)))))))
(display-widget (bonds deal :forms (append (standard-split-forms) (list halves))))
```

## An example program

`examples/deal_example.lsp` builds a deal of two levels and runs it at two prepayment speeds; divides a pool into a PAC and its companion and shows
what the PAC owes at five speeds; divides the companion into a second PAC; divides a bond into a floater and an inverse floater and shows their
coupons at five levels of the index; has a Z bond and an accretion directed bond; strips a bond into an IO and a PO and divides the PO; and makes
a deal from two pieces of collateral that have different pass-through coupons. The example programs document describes it.
