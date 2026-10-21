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
- [Losses and shortfalls](#losses-and-shortfalls)
  - [Losses](#losses)
  - [Interest shortfalls](#interest-shortfalls)
  - [What is not modeled](#what-is-not-modeled)
- [Checking a deal](#checking-a-deal)
- [Making another kind of split](#making-another-kind-of-split)
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

The pool here pays 30 of principal each month for four months, and is divided into a bond `A`, which is paid first, and `B`:

```lisp
(define pool (make-collateral :name "POOL" :balance #(120.0 90.0 60.0 30.0 0.0) :principal #(30.0 30.0 30.0 30.0)))
(define deal (start-deal "Demo" pool))
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

A deal can have **more than one piece of collateral**, each the root of a tree of its own. All of it is in **double precision**:
`start-deal` refuses single (see `set-vector-precision!`), because a bond of hundreds of millions has to keep its cents.

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
names, in the order they were added; `(deal-leaves deal)` are the bonds; `(deal-roots deal)` are the names of the collateral, and
`(deal-root-of deal name)` is the collateral at the root of the tree a node is in.

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

Each month, for each tree, `deal-run!` does these things in this order:

1. **the interest**: the split of the collateral divides the interest it was paid among its children, and each of them divides what it was
   paid, down to the bonds;
2. **the principal**, in the same way (a Z bond has accrued what it is owed in interest, in 1, which is paid as principal here: that is why the
   interest is first);
3. **the loss**, in the same way, of what the bonds have left;
4. **the balances** for next month: a balance is its last, and what it accrues, less what it was paid in principal and written down by; a
   notional bond's balance is a share of the one it follows.

A split does only its own part: it does not call the splits of its children. `deal-run!` walks the tree.

### Amounts, and what is equal

Amounts that should be equal are, if they are within `deal-tolerance` (a billionth) of the balance of all the collateral. It is a fraction, not
an amount of money, so it does not matter whether a deal is in dollars or millions.

## Building a deal

### The collateral

`(collateral-from-psa name balance rate [:term 360] [:age 0] [:psa 100])` makes the collateral node for a pool of level-pay mortgages with this
balance, this annual `rate` in percent, and a `term` and `age` in months, prepaying at `psa` percent of the PSA curve (100 is the standard
curve, 0 none; see `prepayment_model.lsp`). It has its cash flows worked out, for the `term - age` months that are to run: `collateral-principal`,
`collateral-interest` (at its rate) and `collateral-balance`. `(pool-cash-flows balance rate term age psa)` gives the same three vectors as a
list. Its coupon is its rate, as a decimal.

**Collateral from another source** is made by `make-collateral`, with the balance (one element more than the months), the principal and the
interest for each month, the coupon the interest is at, and, if there is any, the loss:

```lisp
(make-collateral :name "POOL" :balance balances :principal principals :interest interests
                 :coupon (constant-coupon 0.06) :loss losses)
```

The cash flows only have to be right for the splits to divide: where they come from does not matter, and a deal does not look into them. A
collateral with no coupon makes a deal of principal only, and one with no loss has none. (Collateral that is to be run at another speed, as a PAC
needs, is made by `collateral-from-psa`, which knows the rate and the term.)

`(start-deal name collateral [:shortfalls #t])` makes a deal whose root is the collateral, and `(deal-add-collateral! deal collateral)` adds
another piece, the root of a tree of its own. It pays for as many months as the first: pad the vectors with zeros if need be.

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
(define deal (start-deal "Demo" (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa 150)))
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
(define deal (start-deal "Demo" (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa 150)))
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

`(deal-run! deal [:index index])` works out what each node is paid, and owes, in every month. It can be run again, with another index, or after a
change. `(deal-check deal)` is `#t` if everything adds up, and an error that says where if not (see "Checking a deal").

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
of its schedule. The collateral must be made by `collateral-from-psa`. A PAC split has two children, the PAC and the companion, in that order,
which can be divided again.

```lisp
(define pool (collateral-from-psa "POOL" 100000000.0 6.5 :term 360 :psa 200))
(define deal (start-deal "PAC demo" pool))
(deal-pac! deal "POOL" "PAC" "COMP" 100 300)
(deal-run! deal)
(format "{:.1f}%" (* 100 (/ (vector-ref (node-balance (get-node deal "PAC")) 0) 1e8)))   ; => "64.9%"
(vector-max (abs (- (node-balance (get-node deal "PAC")) (pac-split-schedule (node-split pool)))))   ; => 0.0
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
(define pool (make-collateral :name "POOL" :balance #(100.0 80.0 60.0 40.0 20.0 0.0) :principal #(20.0 20.0 20.0 20.0 20.0)
                              :interest #(1.0 0.8 0.6 0.4 0.2) :coupon (constant-coupon 0.12)))
(define deal (start-deal "Z" pool))
(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)))
(deal-run! deal)
(node-accrual (get-node deal "Z"))          ; => #(0.6 0.606 0.6 0.4 0.2)
(node-principal (get-node deal "A"))        ; => #(20.6 19.4 0.0 0.0 0.0)
(node-balance (get-node deal "Z"))          ; => #(60.0 60.6 60.0 40.0 20.0 0.0)
(deal-check deal)                           ; => #t
```

In the first month `Z` is owed 0.6 (1% of 60), which is not paid to it; and `A` is paid 20.6, the pool's 20 and what `Z` accrued. The sequential split
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
(define pool (make-collateral :name "POOL" :balance #(100.0 75.0 50.0 25.0 0.0) :principal #(25.0 25.0 25.0 25.0)
                              :interest #(1.0 0.75 0.5 0.25) :coupon (constant-coupon 0.12)))
(define deal (start-deal "Strip" pool))
(deal-io-po! deal "POOL" "IO" "PO")
(deal-run! deal)
(node-balance (get-node deal "IO"))         ; => #(100.0 75.0 50.0 25.0 0.0)
(node-interest (get-node deal "IO"))        ; => #(1.0 0.75 0.5 0.25)
(node-principal (get-node deal "PO"))       ; => #(25.0 25.0 25.0 25.0)
(deal-check deal)                           ; => #t
```

The node may be anything but a Z bond, an IO or a PO: the collateral, a PAC, a floater. The IO and the PO can be divided in turn, in any way, except
into a Z bond: a PO in order, say, or in proportion, and an IO in parts of its notional balance (the children of an IO are notional bonds too, each
following the IO, in the share of it that is its size: `(deal-sequential! deal "IO" '(("IO1" 40.0) ("IO2" 60.0)))` makes one with 40% of the
notional, and one with 60%).

## Losses and shortfalls

Both apply to some deals only. A deal with no losses has none, and a deal is only run with shortfalls if it asks for them.

### Losses

A **loss** is balance written off, with no cash: the collateral's `loss` vector (`make-collateral :loss`) says how much, each month. A deal whose
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

```lisp
(define pool (make-collateral :name "POOL" :balance #(100.0 80.0 35.0 20.0 10.0 0.0) :principal #(20.0 20.0 15.0 10.0 10.0)
                              :loss #(0.0 25.0 0.0 0.0 0.0) :interest #(1.0 0.8 0.35 0.2 0.1) :coupon (constant-coupon 0.12)))
(define deal (start-deal "Senior and subordinate" pool))
(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))
(deal-sequential! deal "A" '(("A1" 50.0) ("A2" 30.0)) :losses 'pro-rata)
(deal-sequential! deal "B" '(("B1" 15.0) ("B2" 5.0)))
(deal-run! deal)
(node-loss (get-node deal "B2"))            ; => #(0.0 5.0 0.0 0.0 0.0)
(node-loss (get-node deal "B1"))            ; => #(0.0 15.0 0.0 0.0 0.0)
(node-loss (get-node deal "A1"))            ; => #(0.0 1.25 0.0 0.0 0.0)
(node-loss (get-node deal "A2"))            ; => #(0.0 3.75 0.0 0.0 0.0)
(deal-check deal)                           ; => #t
```

The pool loses 25 in the second month. `B2` is written down by its 5 and `B1` by its 15; the other 5 is shared by the `A` bonds: after that month's
principal `A1` has 10 left and `A2` 30, so `A1` is written down by a quarter of it, and `A2` by three quarters. The `A` bonds are paid principal in
order, all the same.

A loss that the bonds have not enough left to take is an error (the collateral's balance is its own, and a loss of more than it has is wrong).
`(deal-loss-table deal)` has what each node was written down by. A write-down is permanent: there is no write-up from a later recovery.

### Interest shortfalls

Each bond is owed a twelfth of its coupon on its balance, and the cash for it is the interest of the collateral, which a collateral's own model may
say is less. A deal that is right owes exactly what it is paid, and by default it is an error if it does not (a deal with coupons that do not add
up to the collateral's has a mistake in it). A deal started with **`:shortfalls #t`** is one in which that can be so, and the interest that the bonds
are owed and are not paid is their **shortfall**:

```lisp
(define pool (make-collateral :name "POOL" :balance #(100.0 80.0 60.0 40.0 20.0 0.0) :principal #(20.0 20.0 20.0 20.0 20.0)
                              :interest #(0.9 0.8 0.70201 0.4 0.2) :coupon (constant-coupon 0.12)))
(define deal (start-deal "Short" pool :shortfalls #t))
(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))
(deal-run! deal)
(node-interest (get-node deal "B"))         ; => #(0.1 0.2 0.30201 0.2 0.2)
(node-shortfall (get-node deal "B"))        ; => #(0.1 0.101 0.0 0.0 0.0)
(deal-check deal)                           ; => #t
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

## Building a deal by clicking

`lib/deal_builder.lsp` is a way to build a deal in a Jupyter notebook (the `morris_lisp` kernel, with `ipywidgets` and `ipydatagrid`; see "Widgets in
a notebook") by clicking, instead of by writing the builders. The deal begins as the collateral alone, one tranche with the cash flows of the pool:

```lisp
(define pool (collateral-from-psa "POOL" 100000000 6.5 :term 360 :age 0 :psa 150))
(define deal (start-deal "Demo 2026-1" pool))
(display-widget (deal-builder deal))
```

`(deal-builder deal [:style "tabs"] [:forms forms])` makes a **grid** with a row for each tranche of the deal (the rows of `deal-outline`: name, balance,
and the kind of split), and a panel under it.

- **Click a tranche that is not divided**, and the panel has a tab (or, with `:style "accordion"`, a section) for each kind of split: **Sequential**, **Pro rata**,
  **PAC**, **Floater/inverse**, **Premium/discount** and **IO/PO**, each with the fields that kind needs, and names to start with that are made from the
  tranche's. The tranches of a sequential or a pro-rata split are written one to a line, the name and the balance (`A1 60,000,000`), with `z`
  after the balance for a Z bond, and the last can leave its balance out and be what is left. A PAC has two speeds, a floater and an inverse floater a cap and a
  margin (in percent), a premium and a discount bond their coupons, and an IO and a PO an IO coupon, or none, for the parent's.
- **Calculate the sizes** shows what the tranches would be, as a table, without changing the deal: the tranches of the split and any under them, their balances,
  and the share of their parents' that each is. It is the plan applied to a copy of the deal (`deal-trial-of-plan`), so what is wrong with the fields is said here,
  and what would be wrong when the tranches are added is too.
- **Add the tranches to the deal** adds them (`deal-add-plan!`). They appear in the grid under the tranche that was divided, so that the rows are the tree of the
  deal, depth first, and the panel is put away.
- **Click a tranche that is divided**, and the panel shows its split, with the fields as it was made: its tab is in front, with the tranches, the speeds, the cap
  that it has. Change them, and **Calculate the sizes** shows what is under the split as it is, and as it would be (a column, *was*, for the tranches that are
  in the deal already), and **Change the split** makes the change (`deal-replace-split!`): the tranches of the split are worked out again, and so are those under
  them, to the leaves. Another tab will change the split to a split of another kind, with the same tranches or others.
- **Take away this split, and all under it** is under the panel whenever a tranche that is divided is chosen. It says which tranches would go, and asks; **Yes**
  takes them away (`deal-delete-split!`), and **No** keeps them.

What is wrong is shown as a line under the buttons, with no traceback: the names that are in the deal already, balances that do not add up, a cap below the coupon,
a tranche left out that has a split under it. The deal is the one that was given, and is changed as the buttons are pressed: nothing has been run, so `deal-run!` and
`deal-check` are for when it is built. `notebooks/deal_builder.ipynb` is a notebook that does this.

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
(display-widget (deal-builder deal :forms (append (standard-split-forms) (list halves))))
```

## An example program

`examples/deal_example.lsp` builds a deal of two levels and runs it at two prepayment speeds; divides a pool into a PAC and its companion and shows
what the PAC owes at five speeds; divides the companion into a second PAC; divides a bond into a floater and an inverse floater and shows their
coupons at five levels of the index; has a Z bond and an accretion directed bond; strips a bond into an IO and a PO and divides the PO; and has two
pieces of collateral. The example programs document describes it.
