# Simple Lisp — Reference

A small Lisp with vectors, dates, macros, linear/logistic/spline regression,
XY charting, FRED economic-data access, real tastytrade broker data (futures
and equity option chains, futures-curve rich/cheap and calendar-spread carry
analysis), and a built-in debugger — plus an optional PyQt6 GUI.

This document aims to cover **every builtin and special form** the
interpreter provides: what its arguments mean, what it returns, and any
non-obvious behavior or error conditions. For a quicker orientation, read
"Running it", "Syntax", and "Special forms" first, then treat "Built-in
functions" as a reference to search rather than read start to end.

## Running it

- **No arguments** — `python3 lisp_interpreter.py` opens the PyQt6 GUI (an
  input box, an output log, a "Columns" table, and a chart tab). The
  Columns table is populated only by an explicit `(display-columns ...)`
  call (see "Columns", below) — there's no automatic scan of top-level
  variables. If PyQt6 or matplotlib isn't installed, it falls back to a
  plain console REPL instead.
- **A filename argument** — `python3 lisp_interpreter.py script.lsp` runs
  that file in batch mode (no GUI). `save-chart` still works in this mode
  as long as matplotlib is installed (PyQt6 is not required for it).
  - **Argument just "-"** — `python3 lisp_interpreter.py -` runs
  interactively with no GUI. `save-chart` still works in this mode
  as long as matplotlib is installed (PyQt6 is not required for it).

Every fresh environment — batch mode, the console REPL, and the GUI alike —
automatically loads `init.lsp` (next to `lisp_interpreter.py`; override with
the `LISP_INIT_FILE` environment variable) before doing anything else, if it
exists. It's entirely optional — a missing init file is silently skipped.
Put your own always-available definitions/macros there instead of
`(load ...)`-ing them by hand in every script.

## Syntax

| Type | Example | Notes |
|---|---|---|
| Integer | `42`, `-7` | Python `int` |
| Float | `3.14`, `-0.5` | Python `float` |
| String | `"hello"` | Double-quoted; `\n`, `\t`, `\"`, `\\` escapes |
| Boolean | `#t`, `#f` | Everything except `#f` counts as true |
| Symbol | `foo`, `list->vector` | Identifiers |
| Keyword | `:name`, `:x` | A `Symbol` subtype, but SELF-EVALUATING (never needs `quote`) — used at call sites for keyword arguments; see "Keyword arguments", below |
| Pair / list | `(1 2 3)`, `'(a b c)` | Built from cons cells; `()` is the empty list |
| Dotted pair | `(1 . 2)`, `(a b . c)` | An IMPROPER list — `.` before the last element sets the final cdr directly instead of `()`. Mainly used for variadic parameter lists (see below), but works anywhere |
| Quasiquote | `` `(a ,b ,@c) `` | Like `quote`, but `,x` splices in the value of `x` and `,@x` splices in the elements of list `x` — see Macros below |
| Vector | `#(1 2 3)`, `(vector 1 2 3)` | Fixed-size, holds numbers and/or dates only (not strings, pairs, booleans) |
| Date | `(date 2024 3 15)` | Prints as `2024-03-15` |
| Model | *(returned by regression)* | Prints as `#<linear-model ...>` etc. |

Comments run from `;` to end of line.

### Special forms

Special forms receive their argument *expressions* unevaluated — each one
decides what, if anything, to evaluate and when — which is what
distinguishes them from ordinary procedure calls (where every argument is
evaluated before the call happens).

#### `(quote expr)`
Returns `expr` completely unevaluated, as literal data. `'expr` is reader
sugar for this.

#### `` (quasiquote template) ``
Like `quote`, but `(unquote expr)` (written `,expr`) inside the template is
replaced by the *value* of evaluating `expr`, and `(unquote-splicing expr)`
(written `,@expr`) as a list element splices in the *elements* of evaluating
`expr` (which must itself evaluate to a list) rather than the list itself.
`` `template `` is reader sugar for `(quasiquote template)`. Nested
quasiquotes shield their own `,`/`,@` from an outer one (each nesting level
increments a depth counter; an unquote only actually evaluates once depth is
back down to the matching level). Works inside vector literals too, splicing
each element. See "Macros", below, for why this matters.

#### `(if test conseq [alt])`
Evaluates `test`; if it is not `#f` (everything else — including `0` and
`'()` — counts as true), evaluates and returns `conseq`; otherwise
evaluates and returns `alt`, or `'()` if `alt` was omitted.

#### `(define name expr)` / `(define (name params...) body...)`
First form: evaluates `expr` and binds it to `name` in the current
environment (creating the binding if it doesn't already exist there).
Second form (function-definition sugar): defines `name` as a function with
the given parameter list and body, without evaluating anything at
definition time — equivalent to `(define name (lambda (params...)
body...))`. `params` may be a fixed list `(a b)`, a dotted/variadic list
`(a b . rest)`, or (using dotted-pair syntax directly in the target)
`(name . args)` for a fully-variadic function — see "Variadic parameters",
below. Returns `name`.

#### `(set! name expr)`
Evaluates `expr` and rebinds the *existing* binding of `name`, found by
walking outward through enclosing environments. Raises `LispError: unbound
symbol: ...` if `name` isn't bound anywhere in that chain — unlike
`define`, `set!` can never create a new binding, only change one that
already exists.

#### `(lambda params body...)`
Creates and returns an anonymous procedure, closing over the environment
active where the `lambda` appears. `params` follows the same three shapes
`define`'s function form does (fixed, dotted, or a bare symbol collecting
every argument).

#### `(begin expr...)`
Evaluates each expression in order, returning the value of the last one (or
`'()` if there are none). The last expression is in tail position.

#### `(let ((name val)...) body...)`
Desugars to `((lambda (name...) body...) val...)`: every `val` is evaluated
in the *outer* environment (none of them can see each other's bindings),
then `body...` runs with all the names bound simultaneously.

#### `(let* ((name val)...) body...)`
Like `let`, but desugars to nested single-binding `let`s, so each `val`
expression can see every `let*` binding that came before it in the same
form.

#### `(cond (test body...)... [(else body...)])`
Tries each clause's `test` in turn; for the first one that's true,
evaluates its `body...` and returns the value of the last expression. The
literal symbol `else` (not evaluated) always matches, if present. Returns
`'()` if no clause matches and there's no `else`.

#### `(and expr...)`
Evaluates each expression in order, stopping and returning `#f` as soon as
one is false; if every expression is true, returns the value of the last
one. `(and)` (zero arguments) returns `#t`.

#### `(or expr...)`
Evaluates each expression in order, stopping and returning the value of the
first one that's true; if none are, returns `#f`. `(or)` (zero arguments)
returns `#f`.

#### `(dolist (var list-expr [result-expr]) body...)`
Common-Lisp-style list iteration. Evaluates `list-expr` exactly once, then
for each element in turn binds `var` to it and runs `body...` for side
effects (`display`, `set!`, `vector-set!`, etc. — like `map`, but for when
you're looping for effect and don't want a collected result). Once the list
is exhausted, `var` is rebound to `'()` and `result-expr` is evaluated and
returned (or `'()` if no `result-expr` was given). Desugars entirely into
`let`/`define`/`if`/`car`/`cdr`/`null?` as a self-recursive local helper
(kept out of the surrounding scope), whose recursive step is in tail
position — so it runs in constant control-stack space no matter how long
the list is.

```lisp
(define total 0)
(dolist (x (list 1 2 3 4 5)) (set! total (+ total x)))
total                          ; => 15
```

#### `(defmacro name (params...) body...)`
Defines `name` as a macro — see "Macros", below, for the full explanation.
`params` supports the same fixed/dotted/bare-symbol shapes `lambda` does,
plus `&key` — see "Keyword arguments", below. Returns `name`.

#### `(defstruct name slot...)`
Common-Lisp-style record type. Each `slot` is either a bare symbol (default
value `'()`) or `(slot-name default-expr)` — e.g. `(visible #t)`. Defines,
and binds into the current environment:

- `make-<name>` — a keyword-argument constructor (`:slot-name value ...`,
  any order, each optional — an ordinary application of "Keyword
  arguments", below, not a separate mechanism). A slot's `default-expr` is
  evaluated once per call, in an environment where earlier slots are
  already bound (so later defaults can refer to them), if that slot's
  keyword wasn't supplied.
- `<name>-<slot>` — an accessor, for each slot.
- `<name>-<slot>-set!` — a setter, for each slot (slots are mutable).
- `<name>?` — a predicate.

```lisp
(defstruct point x y (label "origin"))
(define p (make-point :x 1 :y 2))
(point-x p)                    ; => 1
(point-label p)                ; => "origin"  (default, wasn't supplied)
(point-x-set! p 99)
(point-x p)                    ; => 99
(point? p)                     ; => #t
```

A struct prints as `#S(name :slot1 val1 :slot2 val2 ...)`, in declared slot
order. `struct?`, `struct-ref`, `struct-set!`, and `struct-type-name` (see
"Structs" under Built-in functions) work generically on any struct
instance by slot-name symbol, without needing the type-specific accessor
names — useful when writing code that works across struct types.

#### `(breakpoint)`
Opens a nested, blocking debug REPL right where it appears, evaluating
whatever you type directly in the **real lexical environment active at that
point** — e.g. if you put `(breakpoint)` inside a function body, that
function's own parameters are variables in the debug REPL, inspectable and
(via `set!`) modifiable exactly as they exist in the paused call. Type
`(continue)` (or `(exit)`, or press Ctrl-D) to resume normal execution.
`breakpoint` has to be a special form rather than a function or macro
specifically to get access to the caller's actual environment object — a
function only ever receives already-evaluated *values*, and a macro's
transformer body runs in its *own* defining environment, not the caller's.
See "Introspection / debugging", below, for the full writeup, including
`debug-function` (which inserts this automatically into an existing
function) and the GUI limitation (console/batch mode only).

### Variadic parameters

A `lambda`/`define`/`defmacro` parameter list can take three shapes:

| Form | Example | Meaning |
|---|---|---|
| Proper list | `(a b c)` | Fixed arity — exactly 3 arguments, as always |
| Dotted list | `(a b . rest)` | `a` and `b` are fixed; `rest` collects every additional argument into a list (possibly empty) |
| Bare symbol | `args` (no parens at all) | Every argument, with no fixed ones, collected into `args` |

```lisp
(define (f a b . rest) (list a b rest))
(f 1 2 3 4 5)                  ; => (1 2 (3 4 5))

(define sum-all (lambda nums (apply + nums)))
(sum-all 1 2 3 4)              ; => 10
```

This works identically for `defmacro` — a macro can take a variable number
of arguments the same way a function can. Calling a fixed-arity function or
macro with the wrong number of arguments raises `LispError: expected N
argument(s), got M`; a variadic one raises `LispError: expected at least N
argument(s), got M` if you supply fewer than its fixed parameters require.

### Keyword arguments

A fourth parameter-list shape, mutually exclusive with the dotted/bare-symbol
rest-parameter forms above: fixed positional parameters followed by `&key`
and a list of keyword-parameter specs, each a bare symbol (default `'()`) or
`(name default-expr)`:

```lisp
(define (f a &key (b 10) c) (list a b c))
(f 1)                           ; => (1 10 ())
(f 1 :c 30)                     ; => (1 10 30)
(f 1 :c 30 :b 20)               ; => (1 20 30)   -- any order, each optional
```

At the call site, every argument after the fixed positional ones must come
in `:keyword value` pairs (in any order); an unrecognized keyword, or a
missing value for the last one, raises a `LispError`. `default-expr` is
evaluated once per call, if that keyword wasn't supplied, in an environment
where earlier parameters and keyword slots are already bound — so a later
default can refer to an earlier one, same as Common Lisp.

A keyword like `:b` is its own self-evaluating datatype (`Keyword`, a
`Symbol` subtype — see the Syntax table above), so it's never quoted.
`keyword?` tells them apart from ordinary symbols (`symbol?` is still true
for a keyword too, same as Common Lisp).

`&key` works identically for `defmacro`: a keyword parameter is bound to
the call site's raw, unevaluated argument expression (or, if omitted, the
raw `default-expr` itself, also unevaluated) — consistent with how every
other macro parameter is bound (see "Macros", below).

`defstruct`'s generated `make-<name>` constructor (below) is built entirely
out of this feature — struct construction is just an ordinary `&key`
procedure, not a separate mechanism.

### Macros

`(defmacro name (params...) body...)` defines a macro. The difference from
a procedure: when you call `name`, its arguments are NOT evaluated first —
`params` are bound to the call site's raw, unevaluated source expressions
(as data: symbols, pairs, literals), `body...` runs to compute a new
expression from them (the "expansion"), and THAT expression is evaluated,
in your calling environment, in place of the original call. This lets a
macro see and rearrange the code it was called with, which a function
never can (a function's arguments are already values by the time it runs).

`` `template `` (quasiquote) is the natural way to build an expansion:
it's like `'template` (quote), except `,expr` inside it splices in the
*value* of `expr`, and `,@expr` splices in the *elements* of `expr` (which
must evaluate to a list) rather than the list itself. Quasiquote nests
correctly, and works outside of macros too — anywhere you want "mostly
literal data with a few computed pieces."

```lisp
; unless: the mirror image of `if` with no else-branch. Can't be written
; as a plain function -- a function would evaluate `then` regardless of
; whether `test` was true.
(defmacro unless (test then)
  `(if (not ,test) ,then '()))
(unless (> 1 2) 'shown)        ; => shown

; swap!: mutates two variables in place. No function could do this either
; -- a function only ever sees the VALUES of its arguments, never the
; variables (names) themselves, so it has nothing to set!.
(defmacro swap! (a b)
  `(let ((tmp ,a))
     (set! ,a ,b)
     (set! ,b tmp)))
(define p 1) (define q 2)
(swap! p q)
(list p q)                     ; => (2 1)
```

`defmacro` supports variadic parameters too (see above), so a macro that
takes a variable-length body can collect it with a dotted or bare-symbol
parameter instead of requiring the caller to wrap multiple statements in a
single `(begin ...)`:

```lisp
(defmacro my-or (. exprs)
  (if (null? exprs)
      #f
      `(let ((t ,(car exprs)))
         (if t t (my-or ,@(cdr exprs))))))
(my-or #f #f 3 4)              ; => 3
```

`gensym` (see Metaprogramming, below) is the standard tool for avoiding
accidental variable capture in a macro like this by hand — e.g. the `t`
above would shadow a caller's own variable named `t`; a hand-written macro
meant for wider use would bind `(gensym)`'s result instead of a fixed name.

A macro's own body, while it's still computing an expansion, is evaluated
by an ordinary (recursive) Python function call, not the fully
tail-call-optimized evaluator loop — so a transformer that itself did deep
non-tail recursion while *building* its expansion would be bounded by
Python's own recursion limit. This essentially never matters in practice
(a transformer builds a piece of code; it doesn't loop over runtime data),
and it does NOT affect the code a macro expands *to* — once the expansion
is produced, it's evaluated by the ordinary trampoline, tail calls and all
(see the tail-call note at the end of "Special forms", above).

---

## Built-in functions

### Arithmetic

All arithmetic functions reject non-numeric arguments (including booleans,
which Python treats as a subtype of `int` but this interpreter does not)
with `LispError: not a number: ...`, except where noted.

#### `(+ a b ...)`
Sum of zero or more numbers; `(+)` is `0`.

#### `(- a b ...)`
Subtracts left to right; `(- a)` (one argument) negates it. Raises
`LispError` if called with no arguments.

#### `(* a b ...)`
Product of zero or more numbers; `(*)` is `1`.

#### `(/ a b ...)`
Divides left to right (true/float division, not integer); `(/ a)` (one
argument) is `1/a`. Raises `LispError` if called with no arguments.

#### `(mod a b)`, `(remainder a b)`
Both compute Python's `a % b` (floor-modulo — the result's sign follows the
divisor `b`). Despite the names, this interpreter does not give
`remainder` Scheme's usual distinct sign-follows-dividend behavior; the two
are identical here.

#### `(quotient a b)`
Truncating (toward zero) integer division: `int(a / b)`. Differs from `//`
for negative operands — e.g. `(quotient -7 2)` is `-3`, not `-4`.

#### `(abs x)`
Absolute value.

#### `(min a b ...)`, `(max a b ...)`
Minimum / maximum of the given arguments (at least one required).

#### `(sqrt x)`
Square root. Raises a plain Python `ValueError` (not `LispError`) for
negative `x`.

#### `(expt a b)`
`a` to the power `b`, via Python's `**` — stays an exact integer for
integer inputs, e.g. `(expt 2 10)` is `1024` (an int).

#### `(pow a b)`
`a` to the power `b`, via `math.pow` — always returns a float, e.g.
`(pow 2 10)` is `1024.0`.

#### `(log x [base])`
Natural log of `x`, or log base `base` if given, e.g. `(log 8 2)` is `3.0`.

#### `(floor x)`, `(ceiling x)`, `(round x)`, `(truncate x)`
Standard rounding. `round` uses banker's rounding (round-half-to-even) for
exact ties, matching Python's built-in `round`.

#### `(sigmoid z)`
`1 / (1 + e^-z)`, computed in a numerically stable way for very large
`|z|`. The same logistic function `logistic-regression`/`model-predict`
use internally, exposed directly for convenience.

### Comparison / equality / booleans

#### `(= a b ...)`, `(< a b ...)`, `(> a b ...)`, `(<= a b ...)`, `(>= a b ...)`
Chained numeric comparisons — true only if the comparison holds between
*every* consecutive pair of arguments, e.g. `(< 1 2 3)` checks both `1<2`
and `2<3`. With 0 or 1 arguments, always `#t`.

#### `(not x)`
`#t` if `x` is `#f`; `#f` for everything else (including `0` and `'()`).

#### `(eq? a b)`, `(equal? a b)`
Both are implemented as value equality here (`a is b or a == b` for `eq?`;
plain `a == b` for `equal?`) — this interpreter does **not** give `eq?`
Scheme's usual identity-only semantics. `(eq? '(1 2) (list 1 2))` is `#t`
here, where in most Schemes it would be `#f`. For most purposes the two are
interchangeable in this interpreter.

#### `(boolean? x)`
`#t` only for `#t`/`#f`.

#### `(number? x)`
`#t` for any `int` or `float`, explicitly excluding booleans.

#### `(integer? x)`
`#t` for an `int` that isn't a boolean; `#f` for a float even with no
fractional part (e.g. `3.0`).

#### `(string? x)`
`#t` only for a genuine Lisp string (something written as a `"..."`
literal, or returned by a function documented as returning a string) —
**not** for a plain single character as produced by `string->list`, which
are a different underlying type. If in doubt, `(string? (string->list
"ab"))`'s first element is `#f`, not `#t`.

#### `(symbol? x)`
`#t` for a symbol (an identifier like `foo` or `list->vector`) — also `#t`
for a keyword (`:name`), since a keyword is a kind of symbol here, same as
Common Lisp.

#### `(keyword? x)`
`#t` only for a keyword (`:name`) — narrower than `symbol?`.

#### `(procedure? x)`
`#t` for anything callable — a built-in procedure or a user-defined one
made with `lambda`/`define`. **`#f` for a macro** — a macro isn't callable
the way a procedure is (it must be invoked in operator position to expand,
not passed around as a value and applied).

#### `(pair? x)`
`#t` for a cons cell — including an *improper* (dotted) pair like
`(1 . 2)`, which isn't a proper list.

#### `(list? x)`
`#t` if `x` is `'()` or any cons cell — this does not verify the list is
*proper* (nil-terminated); `(list? (cons 1 2))` is `#t` even though
`(1 . 2)` is a dotted pair, not a real list.

#### `(null? x)`
`#t` only for `'()`.

#### `(vector? x)`
`#t` for a vector (built with `vector`/`make-vector` or `#(...)`).

#### `(date? x)`
`#t` for a date value (built with `date` or `date-add-days`).

#### `(model? x)`
`#t` for any fitted regression model — see "Regression models", below.

#### `(struct? x)`
`#t` for an instance of any `defstruct`-defined type — see "Structs",
below.

### Pairs and lists

#### `(cons a b)`
Builds and returns a new pair with `car = a`, `cdr = b`.

#### `(car p)`, `(cdr p)`
First element / rest of a pair. Raises `LispError: car/cdr: not a pair:
...` if `p` isn't a pair (e.g. calling on `'()`).

#### `(list a b ...)`
Builds a proper list from its arguments (zero or more).

#### `(append l1 l2 ... ln)`
Concatenates any number of lists (all but the last are copied; the last is
reused as-is for the tail). `(append)` returns `'()`.

#### `(reverse l)`
Returns a new list with `l`'s elements in reverse order.

#### `(length l)`
Number of elements in a proper list.

#### `(list-ref l n)`
The `n`-th element (0-based). Raises `LispError: list-ref: index N out of
range (0..M)` if `n` is out of bounds.

#### `(map f l)`
Applies `f` to each element of `l` in order, returning a new list of the
results.

#### `(filter f l)`
Returns a new list of just the elements of `l` for which `(f x)` is true.

#### `(reduce f l [init])`
Left fold. With `init` given, starts the accumulator there and folds `f`
over every element of `l`; without it, uses `l`'s first element as the
initial accumulator and folds over the rest (an empty `l` with no `init`
has no first element to start from, and raises an error).

#### `(apply f arg1 arg2 ... args)`
Calls `f` with `arg1`, `arg2`, ... as individual leading arguments,
followed by the *elements* of the final argument `args` (a list).
`(apply f lst)` — no leading arguments — is the common case: spreading a
list into positional arguments, e.g. `(apply + (list 1 2 3))` is `6`, and
`(apply + 1 2 (list 3 4 5))` is `15`. Requires at least 2 arguments total
(`f` and one list).

### Strings

#### `(string-append s1 s2 ...)`
Concatenates zero or more strings.

#### `(string-length s)`
Character count.

#### `(substring s start [end])`
`s` from index `start` up to (not including) `end`, which defaults to the
end of the string. Out-of-range indices are silently clamped, like a
Python slice — not an error.

#### `(string=? a b)`, `(string<? a b)`, `(string>? a b)`
Two-argument lexicographic comparison (not chained/variadic like the
numeric comparisons).

#### `(string->number s)`
Parses `s` as an `int` if it contains neither `.` nor `e`/`E`, otherwise as
a `float`. Raises a plain Python `ValueError` (not `LispError`) if `s`
isn't a valid number.

#### `(number->string n)`
Converts a number to its display string, e.g. `3` → `"3"`, `3.0` →
`"3.0"`.

#### `(string->list s)`, `(list->string l)`
Convert between a string and a list of its individual characters.

#### `(string-upcase s)`, `(string-downcase s)`
Case conversion.

#### `(string->symbol s)`, `(symbol->string sym)`
Convert between a string and a symbol.

#### `(string c1 c2 ...)`
Builds a string by concatenating its arguments (typically single
characters from `string->list`) — the same operation as `string-append`.

### Vectors

Vectors are fixed-size and mutable, holding numbers and/or dates only (not
strings, pairs, or booleans) — an attempt to put anything else in one
raises `LispError: not a number or date: ...`. `vector-ref`/`vector-set!`
do **not** bounds-check their index; an out-of-range index raises a plain
Python `IndexError`, not a `LispError`.

#### `(vector a b ...)`, `#(a b ...)`
Builds a vector from its arguments. `#(...)` is reader syntax for a vector
*literal* (its contents are NOT evaluated, unlike `(vector ...)`'s
arguments, which are).

#### `(make-vector n [fill])`
A new vector of `n` copies of `fill` (default `0`).

#### `(vector-ref v i)`
Element at index `i` (no bounds check — see caveat above).

#### `(vector-set! v i x)`
Mutates element `i` to `x` in place. Returns `'()`.

#### `(vector-length v)`
Number of elements.

#### `(vector-fill! v x)`
Mutates every element of `v` to `x` in place. Returns `'()`.

#### `(vector-copy v)`
A new, independent shallow copy.

#### `(vector-map f v)`
Applies `f` to each element of `v` (one vector only — no index argument),
returning a new vector of the results. See `vectors-map`, below, for the
multi-vector version.

#### `(vector-append v1 v2 ...)`
Concatenates any number of vectors into a new one.

#### `(vector->list v)`, `(list->vector l)`
Convert between a vector and a proper list.

#### `(vector-iterate first count f)`
Builds a `count`-element vector: the first element is `first`, and each
following element is `(f previous-element)`. Works for numbers or dates
(e.g. with `date-add-days` as `f`, to build a vector of consecutive dates).
Raises `LispError` if `count` is negative.

#### `(vector-sum v)`
Sum of all elements.

#### `(vector-add v1 v2)`, `(vector-sub v1 v2)`
Elementwise addition/subtraction. If the two vectors have different
lengths, the result is only as long as the *shorter* one (extra elements
in the longer vector are silently ignored) — not an error.

#### `(vector-scale v s)`
A new vector with every element multiplied by `s`.

#### `(vector-slice v start [end])`
Sub-vector from `start` up to (not including) `end`, which defaults to the
end of the vector.

#### `(vector-take v n)`
The first `n` elements, as a new vector.

#### `(vector-drop v n)`
All but the first `n` elements, as a new vector.

#### `(vectors-shuffle (list v1 v2 ...) [seed])`
Returns a Lisp list of new vectors, all permuted with the *same* random
ordering — for shuffling a set of aligned x/y-style vectors together
without losing their row-by-row correspondence, e.g. before splitting into
a training subset and a held-out subset. All input vectors must be the
same length (`LispError` otherwise). `seed` (optional) makes the shuffle
reproducible; omitted, uses an unseeded random generator.

```lisp
(define shuffled (vectors-shuffle (list prices demand) 42))
(define prices2 (car shuffled))
(define demand2 (car (cdr shuffled)))
```

#### `(vectors-map f (list v1 v2 ...) [default])`
The multi-vector generalization of `vector-map`. Element `J` of the result
is `f` applied to `(vector-ref v1 J)`, `(vector-ref v2 J)`, ..., **followed
by the integer `J` itself as one extra, final argument** — so `f` needs
one parameter per input vector plus one more for the index. If the input
vectors aren't all the same length: with no `default` argument, stops at
the length of the *shortest* one (elements past that are never visited);
with a `default` argument, the result runs out to the length of the
*longest* one, and any vector that's run out of real elements contributes
`default` in its place for the remaining positions.

```lisp
(vectors-map (lambda (a b i) (list a b i))
             (list (vector 10 20) (vector 1 2 3)))
; => #((10 1 0) (20 2 1))           -- stops at the shorter vector (length 2)

; + would happily sum the index in too (it takes any number of numeric
; args) -- e.g. (+ 2 20 1) is 23, not 22 -- so when you don't actually
; want the index, use a small lambda that just ignores its last argument:
(vectors-map (lambda (a b i) (+ a b)) (list (vector 1 2 3) (vector 10 20)) 0)
; => #(11 22 3)
```

### Structs

See `(defstruct name slot...)` under "Special forms", above, for the
type-specific `make-<name>`/`<name>-<slot>`/`<name>-<slot>-set!`/`<name>?`
names it generates. These four builtins work generically on any struct
instance, by slot-name symbol, without needing to know its specific type:

#### `(struct? x)`
`#t` for an instance of any `defstruct`-defined type.

#### `(struct-ref s slot-name)`
Returns the value of `s`'s `slot-name` slot (a symbol, e.g. `'x`). Raises
`LispError` if `s` isn't a struct, or has no such slot.

#### `(struct-set! s slot-name value)`
Mutates `s`'s `slot-name` slot in place. Same error conditions as
`struct-ref`. Returns `'()`.

#### `(struct-type-name s)`
Returns `s`'s struct type's name, as a symbol (e.g. `'point`).

### Dates

#### `(date year month day)`
Builds a date. Raises `LispError: date: invalid date: ...` for an invalid
calendar date (month 13, Feb 30, etc.).

#### `(date-year d)`, `(date-month d)`, `(date-day d)`
Integer accessors.

#### `(date->string d)`
Converts to an ISO-format string, `"YYYY-MM-DD"`.

#### `(string->date s)`
Parses a `"YYYY-MM-DD"` string into a date. Raises `LispError:
string->date: invalid date string ... (want YYYY-MM-DD)` for any other
format or an invalid date.

#### `(date-add-days d n)`
A new date `n` days after `d` (negative `n` goes earlier).

### Regression models

`linear-regression`/`logistic-regression` fit a flat model of the form `y =
intercept + sum(coefficients[i] * x[i])` (linear) or `p =
sigmoid(intercept + sum(coefficients[i] * x[i]))` (logistic), where
`coefficients` always has one entry per predictor, even when there's only
one. `spline-regression` fits a *spline* model: internally it expands each
predictor into an extra set of features (piecewise-linear "hinge"
functions, or category-indicator columns — see below), then fits an
ordinary/logistic regression on that expanded basis — so a spline model's
coefficients apply to the expanded basis, not the original predictors, and
`model-coefficients`/`model-intercept`/`model-slope` refuse to operate on
one (use `model-report`/`model-predict` instead, which work on every model
kind). `model-kind` reports which flavor you have: `"linear"`,
`"logistic"`, `"spline"`, or `"spline-logistic"`.

All of `linear-regression`, `logistic-regression`, `spline-regression`,
`model-predict`, and `model-evaluate` accept **either a single vector of X
values (one predictor) or a Lisp list of several vectors** — `(list x1 x2
...)` — for multiple predictors. Every predictor vector and the Y vector
must be the same length. Predictors are standardized internally before
fitting (for numerical stability) and converted back to the original scale
afterward, so this is transparent to you; date values anywhere a number is
expected are silently converted to their ordinal day count.

#### `(linear-regression x y)`
Ordinary least-squares fit of `y = intercept + sum(coefficients[i] *
x[i])`. `x` is a vector, or a list of vectors for multiple predictors; `y`
is a vector the same length as each predictor vector. Returns a model of
kind `"linear"`. Raises an error if `x`/`y` lengths mismatch, a predictor
has zero variance, or the predictors are collinear.

```lisp
(define m (linear-regression prices demand))
(display (model-report m))
```

#### `(logistic-regression x y)`
Maximum-likelihood fit of `p = sigmoid(intercept + sum(coefficients[i] *
x[i]))`, via Newton-Raphson (up to 50 iterations, or until convergence).
`x` as above; every value in `y` must be in `[0, 1]` (a 0/1 label, or a
probability) — values outside that range raise an error. Returns a model
of kind `"logistic"`. Near-perfect separability in the data can prevent
convergence and raises a descriptive error rather than diverging silently.

```lisp
(define m (logistic-regression prices demand))
(display (model-report m))
```

#### `(spline-regression x y [max-knots logistic?])`
A simple, dependency-free way to let a model bend instead of insisting on a
straight line. For each predictor `x`, a handful of "knot" locations are
chosen (automatically, at quantiles of `x`'s own values, or exactly where
you specify), and the model gets one extra *hinge* feature `max(0, x -
knot)` per knot alongside the plain linear term — or, for a predictor
marked `'categorical`, one 0/1 indicator column per non-baseline distinct
value instead of hinges. Fitting then just reuses `linear-regression`'s or
`logistic-regression`'s own fitting code on this expanded feature set.
Returns a model of kind `"spline"` (or `"spline-logistic"`).

`max-knots` (default `3`) controls how *every* predictor is expanded:

| Form | Meaning |
|---|---|
| an integer, e.g. `3` | that many knots, auto-placed at quantiles of that predictor's values — applied to every predictor if there's more than one |
| `'categorical` (a symbol) | expand into 0/1 indicator columns, one per non-baseline distinct value (the smallest value becomes the implicit baseline) — applied to every predictor if there's more than one |
| a flat list of numbers/dates, e.g. `(list 25 35)` | **exact** knot locations — only valid shorthand when there is exactly **one** predictor |
| a list with one entry per predictor, e.g. `(list 3 0)` or `(list (list 25 35) 'categorical)` | full per-predictor control: each entry is itself an integer, an explicit knot list, or `'categorical`. An entry of `0` leaves that predictor purely linear |

A non-zero knot count on a predictor with 3 or fewer distinct values is
rejected up front (naming the predictor, since hinges are meaningless
there and can make the fit singular) — the error suggests `0` (stay
linear) or `'categorical` instead. At `model-predict` time, a categorical
value that wasn't seen while fitting raises a clear error naming the
predictor and the categories that were seen.

`logistic?` (default `#f`) — if true, `y` must be in `[0, 1]`, and the
expanded basis is fit with logistic regression instead of OLS, so the
resulting `[0, 1]`-valued prediction, thanks to the non-linear basis,
doesn't have to be monotonic in `x` the way a plain `logistic-regression`
fit would be.

```lisp
(define home-type (vector 0 1 0 1 1))          ; 0=own, 1=rent
(define m (spline-regression (list income home-type) happiness
                              (list 2 'categorical)))
(display (model-report m))
(model-predict m (list 50000 0))                ; predict for "own", income=50000
```

#### `(model-report m)`
Returns a multi-line string describing a fitted model. For `"linear"`: the
fitted equation, each coefficient, the intercept, R-squared, and `n`. For
`"logistic"`: the fitted `sigmoid(...)` equation, coefficients, intercept,
log-likelihood, McFadden's pseudo-R-squared, iteration count and
convergence status, and `n`. For a spline model (either kind): the
predictor count, then per-predictor either its knot locations (or "none —
plain linear") or its categories and baseline value — flagging, as a hint
rather than an error, any purely-linear predictor with 3 or fewer distinct
values as a candidate for `'categorical` — followed by the same
fit-quality stats as the equivalent linear/logistic case, computed on the
expanded basis.

#### `(model-evaluate m x y)`
Evaluates a fitted model's prediction quality against data — typically
held-out data it wasn't fit on — and returns a string report. `x`/`y`
follow the same shape rules as the fitting functions; the number of
predictor vectors in `x` must match the model's own predictor count. For a
non-probabilistic model (`"linear"`/`"spline"`): reports R-squared, RMSE,
and MAE against this new data. For a probabilistic model
(`"logistic"`/`"spline-logistic"`): reports log-likelihood, McFadden's
pseudo-R-squared (against an intercept-only model fit fresh on this new
data), and classification accuracy at a 0.5 threshold. Works uniformly
across every model kind, including spline models.

```lisp
(define n-train (floor (* (vector-length x) 0.7)))
(define m (linear-regression (vector-take x n-train) (vector-take y n-train)))
(display (model-evaluate m (vector-drop x n-train) (vector-drop y n-train)))
```

#### `(model-coefficients m)`
Returns a vector of the model's fitted coefficients, one per predictor, in
the order the predictors were given when fitting. Only valid for
`"linear"`/`"logistic"` models — raises an error on a spline model (use
`model-report` instead).

#### `(model-intercept m)`
The model's fitted intercept (a plain number). Same linear/logistic-only
restriction as `model-coefficients`.

#### `(model-kind m)`
Returns `"linear"`, `"logistic"`, `"spline"`, or `"spline-logistic"`. Works
on any model.

#### `(model-predict m x)`
Predicts the fitted value at a new point. `x` may be a bare number or date
when `m` has exactly one predictor, or `(list x1 x2 ...)` (in the same
order the model was fit with) for a multi-predictor model — a
single-predictor model accepts either form. Raises an error if the number
of values given doesn't match the model's predictor count. Returns a plain
number: the fitted value for `"linear"`/`"spline"` models, or a `[0, 1]`
probability for `"logistic"`/`"spline-logistic"` models.

```lisp
(define m (linear-regression (list income age) rent))
(model-predict m (list 50000 30))      ; two predictors -> a list
(define m2 (linear-regression income rent))
(model-predict m2 50000)               ; one predictor -> bare number is fine too
```

#### `(model-slope m)`
Shorthand for "the (only) coefficient" — `(vector-ref (model-coefficients
m) 0)` — but raises a clear error if the model has more than one predictor
(use `model-coefficients` instead). Same linear/logistic-only restriction
as `model-coefficients`.

#### `(model? x)`
`#t` for any fitted model (linear, logistic, spline, or spline-logistic).

#### `(suggest-knots x y window n)`
Proposes up to `n` knot locations for `spline-regression`, based on where
`y` actually bends as a function of `x`, rather than generic quantiles:

1. Aggregates `y` (by mean) onto each *distinct* `x` value seen — matters
   for panel/pool-style data where many rows share an `x`; `window` counts
   steps along this distinct-`x` curve, not raw rows.
2. Estimates that curve's second derivative at every interior point (a
   3-point finite-difference formula that works for unevenly spaced `x`,
   including date `x` values).
3. Smooths that sequence with a centered moving average of `window`
   points.
4. Greedily picks the points with the largest smoothed `|second
   derivative|`, skipping any candidate within `window` of one already
   picked, so chosen knots represent genuinely distinct bends.

`window` must be a positive integer; `n` must be non-negative (`n = 0`
returns `'()` immediately). Requires at least 3 distinct `x` values.
Returns a Lisp list of up to `n` x-values (fewer if there aren't that many
usable candidates), sorted ascending, ready to hand straight to
`spline-regression` as an explicit knot list.

```lisp
(define knots (suggest-knots x y 5 3))
(define m (spline-regression x y knots))
```

A larger `window` smooths away small wiggles and flags only broader bends
(forcing suggested knots further apart); a smaller `window` is more
sensitive to sharp, narrow features but can suggest closely-spaced knots.
`x`/`y` don't need to be pre-sorted. Because `window` is measured in
distinct-`x` steps, size it relative to how many distinct `x` values the
data actually has, not the row count.

### Charting

`plot-xy`/`plot-xy-regression`/`plot-xy-full` all build a chart and hand it
to either the GUI's chart tab (if running) or a plain text summary printed
to the console (if not) — either way, only the **most recently plotted**
chart is remembered, which is what `save-chart` re-renders to a file. All
charts have exactly one X vector; if it contains dates, the axis is
formatted as dates automatically. Each Y series gets its own cycling
marker shape (circle, square, triangle, diamond, ...). Charts only ever
plot against a single X vector, even though the regression functions
themselves support multiple predictors — for a multi-predictor model, use
`model-report`/`model-predict` instead of a chart overlay.

#### `(plot-xy x-vec y-list)`
Plots `x-vec` against every vector in `y-list` (a Lisp list of vectors, all
the same length as `x-vec`). Every series is connected with lines,
auto-labeled `"Y1"`, `"Y2"`, ..., title fixed as `"XY Chart"`, no
regression overlay. Returns `'()`.

```lisp
(define prices (vector 10 20 30 40 50))
(define squares (vector-map (lambda (x) (* x x)) prices))
(plot-xy prices (list squares))
```

#### `(plot-xy-regression x-vec y-vec label [kind])`
Plots one Y series (points only, not connected) against `x-vec`, plus a
regression line/curve fit to it. `label` becomes both the legend label and
part of the title. `kind` is `"linear"` (default) or `"logistic"` — any
other value raises an error. Returns `'()`.

```lisp
(plot-xy-regression prices demand "Demand" "logistic")
```

#### `(plot-xy-full x-vec y-list labels connect? title reg-label [reg-kind])`
Full control over a chart. `labels` is a Lisp list of strings (must be
exactly as long as `y-list`) or `'()` for auto labels. `connect?`
(`#t`/`#f`) applies to every series. `title` is the chart title. `reg-label`
is either `#f` (no regression overlay) or the label of one of the plotted
series to fit a line/curve to (raises an error if it doesn't match any
plotted series). `reg-kind` defaults to `"linear"` (same validation as
`plot-xy-regression`). Returns `'()`.

```lisp
(plot-xy-full prices (list doubled squares) (list "Doubled" "Squares")
              #t "Prices vs Derived" "Squares" "linear")
```

#### `(save-chart filename [width height dpi])`
Renders the most recently plotted chart to a standalone image file. Format
is inferred from `filename`'s extension (`.png`, `.pdf`, `.svg`, and
anything else matplotlib recognizes). `width`/`height` default to `8.0`/
`6.0` (inches), `dpi` defaults to `150.0`. Works with or without the GUI
running — needs only matplotlib, not PyQt6. Raises `LispError` if nothing
has been plotted yet this session, if matplotlib isn't installed, or on any
file-write failure. Returns `'()`.

```lisp
(plot-xy prices (list squares))
(save-chart "chart.png")
(save-chart "chart.pdf" 10.0 7.5 300)   ; larger, higher-DPI PDF
```

### Columns

#### `(display-columns pairs)`
`pairs` is a Lisp list of `(name . vector)` conses; each becomes one
displayed column, headed by `name`, in the order given. In the GUI, this
is the *only* way the "Columns" tab is populated — there's no automatic
scan of top-level variables. In console/batch mode, prints a simple
whitespace-aligned text table instead. Returns `'()`.

```lisp
(define prices (vector 10 20 30))
(define squares (vector-map (lambda (x) (* x x)) prices))
(display-columns (list (cons "prices" prices) (cons "squares" squares)))
```

Deliberately low-level — it doesn't know anything about `defstruct` or any
particular notion of a "column". See `column_engine.lsp` (next to this
file) for a small example library, built on `defstruct` and `&key`, that
registers named `column` structs, calculates them row-by-row in
dependency order (with a `lag` accessor for referring to a previous row),
and calls `display-columns` for you — demonstrated end-to-end in
`mortgage_amortization_example.lsp`.

### FRED (Federal Reserve Bank of St. Louis) data, and CSV loading

#### `(fred-series series-id [api-key] [start-date] [end-date])`
Fetches one FRED economic data series and returns a two element with
containing a list of dates and a list of values.
-— parallel, row-aligned lists of dates and numbers.
Observations FRED marks as missing are silently skipped, so both lists
stay the same length.

- `series-id` — the FRED series mnemonic, e.g. `"GDP"`, `"UNRATE"`,
  `"FEDFUNDS"`.
- `api-key` (optional) can be given three ways, tried in this order: (1) if
  it's a path that exists on disk, it's read as a JSON credentials file
  with a `"fred_api_key"` entry — the same file format `tastytrade-*`
  credentials use below, so one file can hold both; (2) otherwise, if it's
  a non-empty string, used as a literal API key directly; (3) if omitted,
  falls back to the `FRED_API_KEY` environment variable. A free key can be
  requested at https://fred.stlouisfed.org/docs/api/api_key.html.
- `start-date`/`end-date` (optional) restrict the observation range. Each
  may be a `date` value or a literal `"YYYY-MM-DD"` string — both forms
  work interchangeably and can be mixed.

Raises `LispError` on a missing/invalid credentials file, a missing API
key, a network/HTTP failure, or a FRED-side error (bad series ID, bad key,
etc).

**Example** (also runnable as [`fred_example.lsp`](fred_example.lsp) —
`python3 lisp_interpreter.py fred_example.lsp`). Exercises all three
argument forms:

```lisp
(define api-key "tastytrade_credentials.json")   ; edit to your credentials file's path

; A small helper to print a (dates . values) series returned by
; fred-series, one observation per line.
(define (print-series dates values i n)
  (if (< i n)
      (begin
        (display "  ") (display (vector-ref dates i))
        (display "  ") (display (vector-ref values i))
        (newline)
        (print-series dates values (+ i 1) n))
      #t))

; --- 1. fetch a full series: US Real Gross Domestic Product ("GDP") ---
(define gdp (fred-series "GDP" api-key))
(define gdp-dates (car gdp))
(define gdp-values (car (cdr gdp)))
(define gdp-n (length gdp-values))
(display "GDP: ") (display gdp-n) (display " quarterly observations") (newline)

; --- 2. a second series, restricted to a date range given as `date` values ---
(define unrate (fred-series "UNRATE" api-key (date 2020 1 1) (date 2020 12 31)))
(display "UNRATE, 2020 (civilian unemployment rate, %):") (newline)
(print-series (car unrate) (cdr unrate) 0 (vector-length (car unrate)))

; --- 3. a third series, with the date range as "YYYY-MM-DD" strings instead ---
(define fedfunds (fred-series "FEDFUNDS" api-key "2023-01-01" "2023-12-31"))
(display "FEDFUNDS, 2023 (effective federal funds rate, %):") (newline)
(print-series (car fedfunds) (cdr fedfunds) 0 (vector-length (car fedfunds)))

```

#### `(load-csv filename [has-header?])`
Loads a CSV file's columns as vectors. Returns `(cons headers-list
vectors-list)`: `headers-list` is a Lisp list of column-name strings,
`vectors-list` the parallel list of the corresponding vectors.

- `has-header?` (default `#t`) — if true, row 0 supplies column names and
  is excluded from the data; if false, synthetic headers `"Column1"`,
  `"Column2"`, ... are generated and every row is data.
- Each column is independently classified: **numeric** if every value in
  it parses as a number; else **date** if every value parses as
  `"YYYY-MM-DD"`; else the column (and its header) is **dropped entirely**
  — no string/categorical columns are ever returned. Raises `LispError` if
  no column is usable at all.
- A data row is included only if *every kept column* has a value in that
  row, so all returned vectors stay the same length and row-aligned (the
  same approach `fred-series` uses for missing observations). Raises
  `LispError` if no row survives that filter, or if the file is empty/
  unreadable/header-only.

```lisp
(define d (load-csv "data.csv"))
(define headers (car d))
(define cols (cdr d))
(define x (car cols))
(define y (car (cdr cols)))
(plot-xy x (list y))

(define d2 (load-csv "no_header.csv" #f))   ; no header row -> Column1, Column2, ...
```

### tastytrade (real broker data)

Requires the `tastytrade` package (`pip install tastytrade`) and a
tastytrade account. This is the full data-and-analysis functionality of
the `tasty_api/` desktop app, ported here as plain synchronous builtins
(each one just wraps an internal `asyncio.run(...)` call, the same way
`fred-series` wraps a plain `urllib` call) — no PyQt6 dependency, and
nothing here needs a GUI running.

Five of the seven functions do real network I/O and take
`credentials-path` first — a local JSON file:
```json
{"client_secret": "...", "refresh_token": "...", "is_test": false}
```
(`is_test` defaults to `false` if omitted). This is the same file
`fred-series` can read a `"fred_api_key"` entry from, so one JSON file can
hold both APIs' credentials. See `tasty_api/README.md` for the one-time
OAuth setup (create an OAuth application on tastytrade, save the client
secret, then use "Create Grant" to generate a refresh token — refresh
tokens don't expire; the SDK auto-renews the short-lived session token
behind the scenes). The other two, `tastytrade-curve-fit` and
`tastytrade-leg-carry`, are pure analysis functions — no
`credentials-path`, no networking — that operate on data already fetched
by `tastytrade-futures-curve-rows`, so you can fetch a curve once and
re-run either analysis as many times as you like with different rate/
threshold assumptions at no extra cost.

`product` (for `tastytrade-futures-curve` and `tastytrade-futures-curve-rows`)
must be one of the recognized futures short codes — call
`(tastytrade-products)` for the current full list (around 60 codes as of
this writing, spanning equity-index, rates, FX, energy, metals, grains,
crypto, and livestock futures, e.g. `"ES"`, `"CL"`, `"GC"`, `"6E"`,
`"ZC"`, `"BTC"`). An unrecognized product raises `LispError:
tastytrade-futures-curve: unknown product '...' (supported: ...)`,
naming the full current list. `tastytrade-option-chain`'s `symbol`
argument is more flexible than this — see its own entry below.

#### `(tastytrade-test-connection credentials-path)`
Authenticates and checks for accounts. Returns a status string naming the
account number(s) found (or noting that authentication succeeded but no
accounts were found). Raises on any connection/auth failure — run this
first to confirm your credentials work before spending time on real data
fetches.

```lisp
(display (tastytrade-test-connection "tastytrade_credentials.json"))
```

#### `(tastytrade-products)`
Takes no arguments. Returns the list of supported futures short-code
strings (around 60 of them) recognized by `tastytrade-futures-curve` and
`tastytrade-futures-curve-rows`, and (as short-code shorthand, for
backward compatibility) by `tastytrade-option-chain`. Call this to see
the exact current list rather than relying on this document to enumerate
every one.

#### `(tastytrade-futures-curve credentials-path product [n-months])`
Fetches the product's futures term structure. `n-months` (default `18`) is
how many upcoming calendar months to check for a listed contract — months
that don't exist for this product (e.g. non-quarterly months on ES/NQ/ZN)
are silently skipped, not an error. Returns `(cons delivery-dates-vector
last-prices-vector)`, one entry per contract month that actually returned
a price, sorted by delivery date — ready to feed straight into `plot-xy`,
`linear-regression`, `spline-regression`, etc.

```lisp
(define curve (tastytrade-futures-curve "tastytrade_credentials.json" "CL" 12))
(plot-xy (car curve) (list (cdr curve)))
```

See also `tastytrade-futures-curve-rows`, immediately below, which covers
the exact same contract months but returns richer rows (including each
contract's futures symbol and days-to-delivery) — that's what
`tastytrade-curve-fit` and `tastytrade-leg-carry` need as input.

#### `(tastytrade-futures-curve-rows credentials-path product [n-months])`
Fetches the same futures term structure as `tastytrade-futures-curve`
(same `product`/`n-months` semantics, same coverage), but returns a Lisp
list of rows instead of a dates/prices pair — each row a 4-element list:
```
(delivery-month futures-symbol days-to-delivery last-price)
```
`futures-symbol` has the leading `"/"` stripped (e.g. `"CLZ6"`, not
`"/CLZ6"`); `days-to-delivery` is an integer (negative if the contract's
first-of-month delivery date has already passed but it's still trading).
Sorted by delivery date. This is the raw input `tastytrade-curve-fit` and
`tastytrade-leg-carry` expect — fetch once with this, then call either
analysis function (repeatedly, with different assumptions) with no
re-fetch needed.

```lisp
(define rows (tastytrade-futures-curve-rows "tastytrade_credentials.json" "CL" 8))
(define fit (tastytrade-curve-fit rows 0.75))
```

#### `(tastytrade-option-chain credentials-path symbol [n-months max-strikes-per-expiration include-iv? greeks-timeout])`
Fetches an option chain — for a CME futures product **or for any equity
symbol**. Returns a Lisp list of rows, each an 11-element list:
```
(symbol type strike expiration-date days-to-expiration delivery-month
 underlying last-price implied-volatility volume open-interest)
```
`type` is `"Call"` or `"Put"`; `strike` is the exercise price;
`days-to-expiration` is an integer; any value tastytrade didn't report
(e.g. no recent implied-volatility snapshot) comes back as `'()`.

`symbol` is classified into one of three cases:

| Form | Treated as | Notes |
|---|---|---|
| Starts with `"/"`, e.g. `"/CL"` | Futures, using the root exactly as given | tastytrade's own convention — works for **any** futures root, not just ones in `tastytrade-products`; no short-code translation needed or done |
| A known short code, e.g. `"CL"` | Futures, translated to `"/CL"` | Kept for backward compatibility with the older, futures-only version of this function |
| Anything else, e.g. `"AAPL"`, `"SPY"` | Equity | No translation of any kind — the symbol is used exactly as given (upper-cased) |

For a **futures** chain: `delivery-month` is the contract's delivery
month (a `date` value, first-of-month) and `underlying` is the futures
symbol with its leading `"/"` stripped (e.g. `"CLZ6"`); `n-months` is how
many upcoming *delivery months* to include (same meaning as in
`tastytrade-futures-curve`).

For an **equity** chain: `delivery-month` is always `'()` (there's no
separate delivery month the way there is for a futures option) and
`underlying` is just the equity symbol itself; `n-months` instead limits
results to expirations within that many months from today — the closest
equivalent for a single underlying with no separate contract months.

The remaining parameters mean the same thing for both cases:

- `max-strikes-per-expiration` (default `15`) — each expiration is
  trimmed to the strikes nearest the underlying's current price (the
  futures price, or the equity's last/close price).
- `include-iv?` (default `#t`) — implied volatility only comes from
  tastytrade's live per-contract Greeks stream (no snapshot IV field in
  the REST market-data endpoint), which is the slow part of this call.
  Pass `#f` to skip it entirely — every row's `implied-volatility` comes
  back `'()`, but the call returns much faster.
- `greeks-timeout` (default `25.0` seconds) — how long to wait for the
  Greeks stream before giving up on stragglers; a timeout there isn't an
  error, those rows just get `'()` for IV.

```lisp
(define creds "tastytrade_credentials.json")
(define chain (tastytrade-option-chain creds "/CL" 2 5 #f))     ; futures, explicit root
(define chain2 (tastytrade-option-chain creds "CL" 2 5 #f))     ; futures, short code (same as above)
(define aapl (tastytrade-option-chain creds "AAPL" 2 10 #f))    ; equity
```

#### `(tastytrade-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])`
Pure function — no networking. Per-contract rich/cheap analysis: fits
`ln(price)` vs. `days-to-delivery` with a low-order polynomial across
every row in `curve-rows` (the output of `tastytrade-futures-curve-rows`,
or anything shaped the same way), then flags each contract's deviation
from that fitted curve. This is the futures-curve analogue of bond
rich/cheap-to-curve analysis — generic, and doesn't require any rate
assumption. Returns a Lisp list of rows, each a 7-element list:
```
(delivery-month futures-symbol days-to-delivery last-price
 fitted-price rich-cheap-pct signal)
```
`signal` is the string `"Rich"` if the contract trades more than
`rich-cheap-threshold-pct` (default `0.75`) above the fit, `"Cheap"` if
that far below, else `"Fair"`.

`poly-degree` (optional) controls the fit's polynomial degree; omit it,
or pass `#f`/`'()`, for the automatic default (`min(3, max(1, n-1))`,
where `n` is the row count) — or pass an integer to override it.

Needs at least 3 rows; returns `'()` if `curve-rows` has fewer.

```lisp
(define rows (tastytrade-futures-curve-rows creds "CL" 8))
(define fit (tastytrade-curve-fit rows 0.75))
(define fit-strict (tastytrade-curve-fit rows 0.25))   ; re-run, no re-fetch, tighter threshold
```

#### `(tastytrade-leg-carry curve-rows funding-rate-pct storage-cost-pct [leg-signal-threshold-pct])`
Pure function — no networking. Pairwise (adjacent contract month)
implied cost-of-carry decomposition. For each pair of adjacent months in
`curve-rows` (near, far) with positive spacing between them:
```
c = ln(far-price / near-price) / ((days-between) / 365)      -- OBSERVED
net storage cost  (u - y) = c - r                             -- given r
convenience yield  y = r + u - c                              -- given r AND u
```
where `r` = `funding-rate-pct` / 100 (your assumed annualized funding
rate) and `u` = `storage-cost-pct` / 100 (your assumed annualized storage
cost), both supplied by you as arguments — the model backs out what's
implied by the actual curve, and can't fully separate storage cost from
convenience yield without your `u` assumption too (that limitation is
inherent to the model). Returns a Lisp list of rows, each a 9-element
list:
```
(near-month far-month near-price far-price days-between
 implied-carry-rate-pct implied-net-storage-cost-pct
 implied-convenience-yield-pct signal)
```
`signal` is `"Far month rich / near cheap"` if that leg's implied carry
rate `c` exceeds the *median* carry rate across all legs by more than
`leg-signal-threshold-pct` percentage points (default `1.0`),
`"Far month cheap / near rich"` if that far below, else `"Fair"`.

**Important for non-commodity products:** "storage cost" and
"convenience yield" are physical-commodity concepts. For a storable
physical commodity (`CL`, `MCL`, ...) they have a real economic
interpretation. For financial futures (`ES`, `NQ`, `ZN`, `SR3`, ...)
there's no physical storage — the *math* (the implied carry rate `c`) is
still valid and meaningful, but the storage/convenience-yield split
doesn't map to anything real; read those two fields as "what a
storage-cost story would require to be true, if you insisted on one" for
those products, not as an actual estimate. `tastytrade-curve-fit`'s
per-contract rich/cheap view is the more broadly meaningful of the two
for non-commodity products.

Needs at least 2 rows; returns `'()` if `curve-rows` has fewer, or if no
adjacent pair has positive day spacing.

```lisp
(define legs (tastytrade-leg-carry rows 4.25 3.0 1.0))
```

**Example** (also runnable as [`tastytrade_example.lsp`](tastytrade_example.lsp) —
`python3 lisp_interpreter.py tastytrade_example.lsp`). Exercises all
seven `tastytrade-*` builtins:

```lisp
(define creds "tastytrade_credentials.json")   ; edit to your credentials file's path

(define (print-each lst)
  (if (null? lst)
      #t
      (begin
        (display "  ") (display (car lst)) (newline)
        (print-each (cdr lst)))))

; --- 1. which product codes are supported ---
(display "Supported products:") (newline)
(print-each (tastytrade-products))

; --- 2. confirm the credentials work before spending time on real fetches ---
(display "Connection test: ") (display (tastytrade-test-connection creds)) (newline)

; --- 3. WTI Crude Oil (CL) futures term structure, next 6 contract months ---
(define curve (tastytrade-futures-curve creds "CL" 6))
(display "CL futures curve (") (display (vector-length (car curve))) (display " months):") (newline)

; --- 4. option chain, fast path (include-iv? = #f) ---
(define chain (tastytrade-option-chain creds "CL" 2 5 #f))
(display "CL option chain, no IV (") (display (length chain)) (display " contracts):") (newline)
(print-each chain)

; --- 5. option chain with implied volatility, kept small so the Greeks
;        stream finishes quickly ---
(define chain-iv (tastytrade-option-chain creds "CL" 1 3 #t 20.0))
(display "CL option chain, with IV (") (display (length chain-iv)) (display " contracts):") (newline)
(print-each chain-iv)

; --- 6. option chain on an equity: any symbol that isn't a futures root
;        ("/..." or a known short code) is fetched as an equity chain
;        automatically -- no separate function, no translation ---
(define aapl-chain (tastytrade-option-chain creds "AAPL" 2 5 #f))
(display "AAPL option chain, no IV (") (display (length aapl-chain)) (display " contracts):") (newline)
(print-each aapl-chain)

; --- 7. rich/cheap curve-fit analysis -- fetch the curve rows once,
;        analyze for free (no networking in tastytrade-curve-fit) ---
(define curve-rows (tastytrade-futures-curve-rows creds "CL" 8))
(define fit (tastytrade-curve-fit curve-rows 0.75))
(display "CL curve-fit rich/cheap:") (newline)
(print-each fit)

; --- 8. implied calendar-spread carry, reusing curve-rows from step 7 ---
(define legs (tastytrade-leg-carry curve-rows 4.25 3.0 1.0))
(display "CL implied carry by leg:") (newline)
(print-each legs)
```

### Input / output

#### `(display x)`
Writes `x`'s display form (strings unquoted, e.g. `hello` not `"hello"`) to
the current output — the console, the GUI log, or a `redirect-output`
file, whichever is currently active — with no trailing newline. Returns
`'()`.

#### `(newline)`
Writes a single newline to the current output. Returns `'()`.

#### `(print x)`
Like `display`, but with a trailing newline.

#### `(load "path.lsp")`
Reads and evaluates every top-level form in the file at `path`, in the
**same** (calling) global environment, so its `define`s/`defmacro`s become
available afterward exactly as if you'd typed them yourself. Returns
`'()`. This is the same mechanism the interpreter uses at startup to
auto-load `init.lsp`.

#### `(redirect-output "path.txt" [append?])`
Retargets everything `display`/`newline`/`print` write (and the console/
no-GUI default chart-summary text) from the console/GUI log to the given
file, until `reset-output` switches back. Opens in overwrite mode by
default; pass `#t` for `append?` to append instead. If a prior
`redirect-output` is still active, its file is closed first (redirecting
twice in a row doesn't leak a file handle). Flushes after every write, so
output survives even if the script errors out before `reset-output`.

#### `(reset-output)`
Undoes `redirect-output`: closes whatever file is currently open (if any)
and returns to writing to the console/GUI log. Safe to call even if no
redirect is active.

### Metaprogramming

#### `(eval expr)`
Evaluates `expr` — a piece of Lisp code as *data*, e.g. built with
`quasiquote`/`list`/`cons`, or read from a string/file — in the top-level
global environment (not the caller's local/lexical environment). A
macro's own expansion is evaluated automatically already; `eval` is for
the separate case of constructing or obtaining an expression some other
way and wanting to run it directly.

```lisp
(define code (list '+ 1 2 (list '* 3 4)))
(eval code)                    ; => 15
```

#### `(apply f arg1 ... args)`
See "Pairs and lists", above — documented once there, since it's equally a
list operation and a metaprogramming tool.

#### `(gensym ["prefix"])`
Returns a symbol guaranteed not to collide with any name a user could
actually type (format `%prefix-N`, with an incrementing counter;
`prefix` defaults to `"g"`). The standard tool for avoiding accidental
variable capture when hand-writing a macro — see "Macros", above. Used
internally by `dolist`'s own desugaring for the same reason.

#### `(load "path.lsp")`
See "Input / output", above — documented once there.

#### `(error message arg...)`
Raises `LispError` with a message built by rendering each argument the way
`display` would and joining them with spaces (so `(error "bad value:" x)`
reads naturally). For signaling a problem from your own Lisp code — e.g. a
library like `column_engine.lsp` reporting a circular dependency.

### Introspection / debugging

`pretty-print-function`, `pretty-print-macro`, `debug-function`, and
`undebug-function` are macros (built with `defmacro`/quasiquote, the same
as anything you could write yourself) specifically so you can write the
bare name directly — `(pretty-print-function my-func)` — instead of
quoting it.

#### `(pretty-print x)`
Verbose, deliberately unattractive printing of any value: every list
element goes on its own line, and a list's closing parenthesis is printed
alone, on its own line, directly under the COLUMN of its matching opening
parenthesis. This is not meant for everyday reading — `display`/`print`
already do that — it's meant to make a misplaced or mismatched parenthesis
impossible to miss: scan straight down any closing paren's column and you
can see exactly which opening paren it closes. A procedure or macro value
is shown as its reconstructed, name-free `(lambda ...)`/`(defmacro
<anonymous> ...)` source (see `pretty-print-function`, below, for the
named version); anything else prints as-is, including plain nested lists.
Writes to the current output with a trailing newline. Returns `'()`.

```lisp
(pretty-print '(a (b c) (d (e f) g)))
```
prints:
```
(a
 (b
  c
 )
 (d
  (e
   f
  )
  g
 )
)
```

#### `(pretty-print-function name)`
Pretty-prints the reconstructed `(define (name params...) body...)` source
of the user-defined function currently bound to `name` — the tool for
visually hunting down a paren-matching mistake in a function definition.
Because a `Procedure` value stores its already-parsed parameter list and
body, this reconstruction is semantically faithful, but **not** a
byte-exact copy of what you originally typed: the reader discards comments
and doesn't remember your original whitespace/formatting. If `name` is
currently wrapped by `debug-function`, shows the original (pre-wrap)
definition, not the wrapper. Raises `LispError` if `name` isn't a
user-defined function.

#### `(pretty-print-macro name)`
Same idea as `pretty-print-function`, but for a macro, reconstructing
`(defmacro name (params...) body...)`. Raises `LispError` if `name` isn't
a macro.

#### `(defined-functions)`
Returns a list of every name currently bound, at the top level, to a
user-defined function (something made with `lambda`/`define` — not a
built-in), in the order each was first defined. There's no separate
registry to keep in sync — this just filters the live environment each
time it's called, so it's always exactly correct, including brand-new
definitions, automatically.

#### `(defined-macros)`
The same idea, for user-defined macros — excludes this interpreter's own
`pretty-print-function`/`pretty-print-macro`/`debug-function`/
`undebug-function` convenience macros, so it reflects only what you
actually wrote.

#### `(bound-variables)`
Returns a list of every top-level name bound to a plain *value* rather
than a function, macro, or built-in procedure — i.e. ordinary `define`d
data: numbers, strings, lists, vectors, dates, and so on.

#### `(breakpoint)`
A special form, not a function — see "Special forms", above, for the full
explanation of why. Repeated here for discoverability: opens a nested,
blocking debug REPL right where it appears, with the paused code's own
local variables live and modifiable in that REPL; type `(continue)` to
resume. Console/batch mode only (see below).

#### `(debug-function name)`
Wraps the user-defined function currently bound to `name` so that every
future call opens the same blocking debug REPL `breakpoint` uses — but
automatically, on every call, without editing the function's own source.
The debug REPL opens in an environment where the function's real
parameters for that specific call are already bound to the actual argument
values, so you can inspect them (or, via `set!`, change them) before
typing `(continue)` to actually run the body with whatever's currently in
scope. Also prints the chain of `debug-function`-wrapped calls currently
in progress, as a lightweight "how was this called, and from where" trace
— **not** a full backtrace (this interpreter's tail-call optimization
deliberately discards ordinary call-frame history — see the tail-call note
at the end of "Special forms"), just of the specific functions you've
asked to watch. Raises `LispError` if `name` isn't a user-defined
function. Saves the original definition internally so `undebug-function`
can restore it — while wrapped, `(pretty-print-function name)` still shows
the real definition, and `(defined-functions)` temporarily stops listing
`name` (it's a plain wrapper, not a `Procedure`, while wrapped).

```lisp
(define (square n) (* n n))
(debug-function square)
(square 5)    ; opens a debug REPL with n bound to 5; type (continue) to proceed
(undebug-function square)
```

#### `(undebug-function name)`
Restores the original, un-wrapped definition of `name` that
`debug-function` saved. Does nothing if `name` was never wrapped.

**Console/batch mode only, for both `breakpoint` and `debug-function`:**
the debug REPL reads from the real console via `input()`, the same as the
top-level REPL. Triggering it from the GUI will try to read from whatever
stdin the GUI process has (usually none, or the terminal it was launched
from) rather than opening any kind of dialog in the GUI window itself —
there's no GUI-integrated debugger, just this console one.

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
