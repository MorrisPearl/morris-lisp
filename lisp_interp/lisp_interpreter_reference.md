# Simple Lisp — Reference

A small Lisp for getting data from various sources and modeling it: fast
vector math and statistics, tables (filter, sort, group, join), monthly
time series, linear/logistic/spline regression with standard errors and
AUC, linear programming, SQLite, CSV files, downloads from any web API, FRED economic data,
real tastytrade broker data (futures and equity option chains,
futures-curve rich/cheap and calendar-spread carry analysis), and XY
charts — plus dates, macros, struct inheritance, hash tables, `catch-error`
error handling, a debugger (breakpoints, a debug hook), and an optional PyQt6 GUI. **Requires `numpy`**, unlike every other dependency mentioned in
this document (PyQt6, matplotlib, pandas, tastytrade), which are all
optional, feature-specific extras — numpy backs the vector datatype itself
(see "Vectors", below), so it's needed for even the plainest console/
batch-mode use of the interpreter.

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

- **Verbose flags** — `-v`, `-vv`, `-vvv` (levels 1–3), `--verbose` (level 1),
  or `--verbose=N` (N = 0–3) may come before the script name (or before
  `-`): `python3 lisp_interpreter.py -vv script.lsp` traces every procedure
  call as the script runs — see "Verbose mode and stack traces", below. The
  `LISP_VERBOSE` environment variable (0–3) does the same.
- **Errors** — in batch mode, an error ends the run with exit status 1 and
  prints, to stderr, the chain of procedure calls that led to it followed by
  the message (`Lisp traceback (most recent call last): ...` /
  `Error: ...`) — the same report the REPL, the GUI log, and Jupyter show.
  Set `LISP_PYTHON_TRACEBACK=1` to get Python's own traceback of the
  interpreter's internals as well.

Every fresh environment — batch mode, the console REPL, the GUI, and
Jupyter alike — loads two Lisp files before doing anything else:

1. `macros_init.lsp`, the standard macros, such as `while`, `do`, and
   `case` (see "Standard
   macros", below). It's part of the interpreter, so it's always loaded.
2. `init.lsp` (next to `lisp_interpreter.py`; override with the
   `LISP_INIT_FILE` environment variable), if it exists. It's entirely
   optional — a missing init file is silently skipped. Put your own
   always-available definitions/macros there instead of `(load ...)`-ing
   them by hand in every script.

- **From a Jupyter notebook, as its own native kernel, no GUI at all** —
  run `python3 install_lisp_kernel.py` once (see `lisp_kernel.py`), then
  pick "morris_lisp" from Jupyter's kernel picker / New menu, same as any
  other kernel; every cell is then plain Lisp source directly, no magic
  prefix needed. Charts render inline (a real `matplotlib`-rendered image,
  not a GUI chart tab or a `save-chart` file) and `(display-columns ...)`
  renders as a pandas `DataFrame` (a real HTML table) instead of the
  console's plain text table. One environment persists for the kernel's
  whole lifetime, the same as typing into the console REPL — restarting
  the kernel (Jupyter's own "Restart" button) starts a fresh one. Built as
  an `IPythonKernel` subclass specifically so `IPython.display.display()`
  (which the chart/table rendering uses, in `lisp_jupyter.py`) keeps
  resolving correctly — see `lisp_kernel.py`'s own docstring for why that
  specific base class matters, and what else is worth knowing about how it
  behaves (error display, tab-completion, history variables `_`/`__`/
  `___`/`_N`). Needs `pandas` and `ipykernel` in addition to matplotlib;
  falls back to the console's plain-text chart/table output if either
  isn't installed. Any of these builtins that fetch over the network
  (`tastytrade-*`, `sofr-calibration-data`) work fine here too -- they run
  their I/O via `asyncio`, and `_run_async()` (in `lisp_tastytrade.py`,
  and an identical twin in `term_structure/sofr_market_data.py`)
  specifically handles being called from inside a Jupyter kernel's own
  already-running event loop, which a bare `asyncio.run()` call can't do.

## Syntax

| Type | Example | Notes |
|---|---|---|
| Integer | `42`, `-7` | Python `int` |
| Float | `3.14`, `-0.5`, `nan`, `inf` | Python `float`. `nan` ("not a number", the missing-value marker) and `inf` (infinity) are numbers too, so they can't be used as names (see below) |
| String | `"hello"` | Double-quoted; `\n`, `\t`, `\r`, `\"`, `\\` escapes. The REPL prints a string the same way, in quotes and with `\"` and `\\` for a quote mark or backslash inside it, so what it prints can be typed back in (see `display`) |
| Boolean | `#t`, `#f` | Everything except `#f` counts as true |
| Symbol | `foo`, `list->vector` | Identifiers: anything that isn't read as a number or one of the types above |
| Keyword | `:name`, `:x` | A `Symbol` subtype, but SELF-EVALUATING (never needs `quote`) — used at call sites for keyword arguments; see "Keyword arguments", below |
| Pair / list | `(1 2 3)`, `'(a b c)` | Built from cons cells; `()` is the empty list |
| Dotted pair | `(1 . 2)`, `(a b . c)` | An IMPROPER list — `.` before the last element sets the final cdr directly instead of `()`. Mainly used for variadic parameter lists (see below), but works anywhere |
| Quasiquote | `` `(a ,b ,@c) `` | Like `quote`, but `,x` splices in the value of `x` and `,@x` splices in the elements of list `x` — see Macros below |
| Vector | `#(1 2 3)`, `(vector 1 2 3)` | Fixed-size; holds numbers, strings, and/or dates (not lists or booleans) |
| Date | `(date 2024 3 15)` | Prints as `2024-03-15` |
| Model | *(returned by regression)* | Prints as `#<linear-model ...>` etc. |

**Words that are numbers.** The reader reads a token as a number if
Python can read it as one, and that includes `nan`, `inf`, and
`infinity`, in any mix of upper and lower case (`NaN`, `Inf`, `Infinity`),
with or without a `+` or `-` in front. (Also `1_000`, which is `1000`.) So
none of these can be the name of a variable, parameter, or function.
Trying to use one as a name is an error, rather than something that
silently does nothing:

```lisp
(define nan 5)       ; an error: nan can't be used as a name -- a name must be a symbol
(let ((inf 1)) inf)  ; the same error
```

Comments run from `;` to end of line.

### Special forms

Special forms receive their argument *expressions* unevaluated — each one
decides what, if anything, to evaluate and when — which is what
distinguishes them from ordinary procedure calls (where every argument is
evaluated before the call happens).

#### `(quote expr)`
Returns `expr` completely unevaluated, as literal data. `'expr` is reader
sugar for this.

```lisp
(quote (a b c))                ; => (a b c)
'(a b c)                       ; => (a b c) -- the common way to write it
```

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

```lisp
(let ((x 3))
  `(x is ,x and doubled is ,(* x 2)))
; => (x is 3 and doubled is 6)

(let ((rest (list 2 3)))
  `(1 ,@rest 4))               ; => (1 2 3 4) -- splices the LIST's elements in
```

#### `(if test conseq [alt])`
Evaluates `test`; if it is not `#f` (everything else — including `0` and
`'()` — counts as true), evaluates and returns `conseq`; otherwise
evaluates and returns `alt`, or `'()` if `alt` was omitted.

```lisp
(if (> 3 2) 'yes 'no)          ; => yes
(if (> 2 3) 'yes)              ; => ()  -- no alt given, test was false
```

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

```lisp
(define x 10)                  ; => x
(define (square n) (* n n))    ; => square
(square 5)                     ; => 25
```

#### `(set! name expr)`
Evaluates `expr` and rebinds the *existing* binding of `name`, found by
walking outward through enclosing environments. Raises `LispError: unbound
symbol: ...` if `name` isn't bound anywhere in that chain — unlike
`define`, `set!` can never create a new binding, only change one that
already exists.

```lisp
(define x 10)
(set! x 20)
x                               ; => 20
```

#### `(lambda params body...)`
Creates and returns an anonymous procedure, closing over the environment
active where the `lambda` appears. `params` follows the same three shapes
`define`'s function form does (fixed, dotted, or a bare symbol collecting
every argument).

```lisp
((lambda (x y) (+ x y)) 3 4)   ; => 7
(define add1 (lambda (n) (+ n 1)))
(add1 41)                      ; => 42
```

#### `(begin expr...)`
Evaluates each expression in order, returning the value of the last one (or
`'()` if there are none). The last expression is in tail position.

```lisp
(begin (display "a") (display "b") 42)   ; prints ab, => 42
```

#### `(let ((name val)...) body...)`
Desugars to `((lambda (name...) body...) val...)`: every `val` is evaluated
in the *outer* environment (none of them can see each other's bindings),
then `body...` runs with all the names bound simultaneously.

```lisp
(let ((a 1) (b 2)) (+ a b))    ; => 3
```

#### `(let* ((name val)...) body...)`
Like `let`, but desugars to nested single-binding `let`s, so each `val`
expression can see every `let*` binding that came before it in the same
form.

```lisp
(let* ((a 1) (b (+ a 1))) (list a b))   ; => (1 2) -- b's val sees a
```

#### `(cond (test body...)... [(else body...)])`
Tries each clause's `test` in turn; for the first one that's true,
evaluates its `body...` and returns the value of the last expression. The
literal symbol `else` (not evaluated) always matches, if present. Returns
`'()` if no clause matches and there's no `else`.

```lisp
(cond ((= 1 2) 'no)
      ((= 1 1) 'yes)
      (else 'fallback))        ; => yes
```

#### `(and expr...)`
Evaluates each expression in order, stopping and returning `#f` as soon as
one is false; if every expression is true, returns the value of the last
one. `(and)` (zero arguments) returns `#t`.

```lisp
(and 1 2 3)                    ; => 3  -- every expr true, returns the last
(and 1 #f 3)                   ; => #f -- stops at the first false one
```

#### `(or expr...)`
Evaluates each expression in order, stopping and returning the value of the
first one that's true; if none are, returns `#f`. `(or)` (zero arguments)
returns `#f`.

```lisp
(or #f #f 3)                   ; => 3  -- first true value
(or #f #f)                     ; => #f -- none were true
```

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

For loops that aren't over a list, see `while` and `do` under "Standard
macros", below.

#### `(defmacro name (params...) body...)`
Defines `name` as a macro — see "Macros", below, for the full explanation.
`params` supports the same fixed/dotted/bare-symbol shapes `lambda` does,
plus `&key` — see "Keyword arguments", below. Returns `name`.

```lisp
(defmacro my-unless (test then) `(if (not ,test) ,then '()))
(my-unless (> 1 2) 'shown)     ; => shown -- see "Macros" for why this needs
                                ;    to be a macro, not a plain function
```

#### `(defstruct name slot...)`, `(defstruct (name (:include parent [slot-override...])) slot...)`
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
- `copy-<name>` — a shallow copy: a new, independent struct with the same
  slot values (the values themselves aren't copied). Accepts an instance
  of `name` or any type that `:include`s it, and copies using the
  instance's own actual type, so `(copy-point a-point-3d-instance)`
  correctly returns another `point-3d`, not a plain `point` missing its
  `z`.

**Naming gotcha:** `<name>-<slot>` is a fixed, predictable name — don't
`define` your own function under that exact name (e.g. as a slot's
`default-expr`, meaning to override it) expecting it to be preserved:
`defstruct` binds its own accessor under that name *after* recording the
slot's (still-unevaluated) default, so by the time the default actually
gets evaluated (when the constructor runs), the accessor has already taken
that name over. Give override-implementation functions a distinct name
instead (see the worked example under "Structs", below, for the pattern
this comes up in).

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

**Inheritance** — `(defstruct (name (:include parent)) slot...)` gives
`name` every one of `parent`'s slots (in `parent`'s own order) plus its own
new `slot`s appended after, exactly CL's `:include`. `parent` must already
be defined (with `defstruct`, earlier). Every accessor/setter/predicate
`parent` itself defined — `parent-<slot>`, `parent-<slot>-set!`, `parent?`
— also accepts an instance of `name` (or of anything that includes `name`,
transitively): a subtype instance can stand in anywhere an instance of its
supertype is expected, the same way a *value* can, so `parent-x` and
`name-x` read the identical slot on a `name` instance. `name?` is only true
for `name` (and its own descendants) — not for a plain `parent` instance,
which lacks `name`'s own new slots entirely.

```lisp
(defstruct point x y)
(defstruct (point-3d (:include point)) z)
(define p (make-point :x 1 :y 2))
(define c (make-point-3d :x 10 :y 20 :z 30))

(point-3d-x c)                 ; => 10
(point-x c)                    ; => 10   -- parent's own accessor works on a child instance
(point? c)                     ; => #t   -- c is-a point too
(point-3d? p)                  ; => #f   -- p is not a point-3d
```

An inherited slot's default can be overridden — its position in the slot
order doesn't change, only the default value a bare `(make-name)` call
gives it — either inside the `:include` clause itself, CL's own syntax
(`(:include parent (slot new-default))`), or, equivalently and more simply,
by just redeclaring that slot name in `name`'s own slot list:

```lisp
(defstruct animal (name "unknown") (legs 4))
(defstruct (bird (:include animal (legs 2))) can-fly)   ; CL's :include syntax
(defstruct (spider (:include animal)) (legs 8) has-web) ; equivalent: redeclare it below
```

Multi-level inheritance (a struct `:include`ing one that itself `:include`s
another) works the same way, transitively — a grandparent's accessors work
on a grandchild instance, and `grandparent?`/`parent?`/`child?` are all
true for it.

#### `(with-struct struct-expr body...)`
Evaluates `struct-expr` (once) — an instance of **any** `defstruct` type — and
binds **every one of its slot names** to that slot's value, exactly as `let`
would: in a fresh child scope, after which `body...` runs (implicit `begin`)
and its last value is returned. It saves writing `(point-x p)`, `(point-y p)`,
… for every slot a body uses, and it works the same way on every struct type,
because the names it binds come from the instance itself. For an instance of
a type that `:include`s another, the inherited slots are bound too.

```lisp
(defstruct point x y (label "origin"))
(define p (make-point :x 3 :y 4))

(with-struct p (sqrt (+ (* x x) (* y y))))   ; => 5.0
(with-struct p label)                        ; => "origin" -- every slot is bound,
                                              ;    including ones left at their default

(defstruct (point-3d (:include point)) z)
(with-struct (make-point-3d :x 1 :y 2 :z 3)
  (list x y z))                              ; => (1 2 3) -- inherited slots too
```

Because it's `let`, not a live alias:

- **The variables are copies of the slot values at entry.** `set!` on one
  changes only that local variable; to change the struct itself, use its
  setter (`point-x-set!`) or `struct-set!`. Likewise, a setter called inside
  the body doesn't update the already-bound variable.
- **Slot names shadow** same-named outer variables (and functions) inside
  the body, and only there — outside the form, nothing changes. Every other
  variable in scope stays visible. A slot named like a function you also
  call in the body (say, a slot called `list`) hides that function for the
  body, so it's worth knowing the struct's slot names at the call site.
- **`define` inside the body is local** to the `with-struct` scope.
- Closures created in the body (`lambda`) capture the bound slot variables.
- Forms nest; an inner struct's slots shadow an outer one's of the same name.
- The body is in **tail position**, like `let`'s: the last body expression
  is evaluated with no frame left behind, so a self-recursive loop written
  through `with-struct` runs in constant control-stack space.

Raises `LispError` if `struct-expr` isn't a struct instance, or if it's
missing entirely.

**Why a special form and not a `defmacro`?** Which names to bind depends on the
struct's *runtime value* (its type's slot list). A macro transformer only
receives the call site's unevaluated source — the symbol `p`, not the struct
`p` holds — and runs in its own defining environment rather than the caller's,
so it can't look inside a struct that lives in a local variable. It's the same
reason `breakpoint`, below, has to be a special form: it needs the caller's
real environment. See `with_struct_example.lsp` for a worked example.

#### `(breakpoint [message])`
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
The optional `message` argument is itself evaluated in that same caller's
environment and printed before the REPL opens — a plain string (`(breakpoint
"entering f...")`) works, but so does any expression whose *value* is worth
seeing right away (`(breakpoint (list "x=" x))`), without needing a separate
`(display ...)` call right before the breakpoint. If a debug hook is
registered, the hook is called instead of the REPL opening, with the kind
`breakpoint` and the message. See "Debugging", below, for the hook, for
`(break f)` (which stops at every call of a procedure without editing it),
for `(abort)`, and for the GUI limitation (the REPL is console-only).

#### `(backtrace)`
Prints the chain of procedure calls in progress right now, without needing
an error — see "Verbose mode and stack traces", under "Introspection /
debugging", below. Returns `'()`.

#### `(catch-error protected-expr (var) handler-body...)`
Evaluates `protected-expr`; if it raises an error, binds `var` to the
error's message (a string) and evaluates `handler-body...` (implicit
`begin`) instead, whose value becomes `catch-error`'s own. If
`protected-expr` succeeds, its value is returned directly and
`handler-body` never runs. Without this, any error — from `error`, or one
of the handful of builtins that raise a plain Python exception instead of
`LispError` (`sqrt` of a negative number, an out-of-range `vector-ref`,
...) — propagates all the way to the top and ends the script; this is the
only way Lisp code itself can catch one and keep going. Catches errors
from *any* of those sources uniformly (not just `LispError`), but not
things like running out of memory or the process being interrupted, which
keep propagating exactly as if this weren't here. To evaluate more than
one protected expression, wrap them in a `begin`.

```lisp
(catch-error (/ 1 0) (e) (display "division failed: ") (display e))
; prints: division failed: division by zero

(define (safe-sqrt x)
  (catch-error (sqrt x) (e) -1))     ; -1 instead of crashing on a negative x
(safe-sqrt -4)                       ; => -1
(safe-sqrt 16)                       ; => 4.0
```

#### `(unwind-protect protected-expr cleanup-expr...)`
Evaluates `protected-expr` and returns its value, but always runs the
`cleanup-expr`s afterwards, however `protected-expr` finishes: normally,
with an error, or by a `throw` (see `catch`, below). An error still
carries on after the cleanup runs; `unwind-protect` doesn't catch it, it
only makes sure the cleanup happens. Use it to release something that
must not be left behind, such as an open database connection or a
redirected output file. (`with-sqlite`, under "Standard macros", below, is
built on it.) To protect more than one expression, wrap them in a `begin`.

```lisp
(define log '())
(unwind-protect (+ 1 2)
  (set! log (cons 'cleaned-up log)))     ; => 3
log                                      ; => (cleaned-up)

(catch-error
  (unwind-protect (car 5)                ; an error...
    (set! log (cons 'again log)))        ; ...but this still runs
  (e) e)                                 ; => "car: not a pair: 5"
log                                      ; => (again cleaned-up)
```

Nested `unwind-protect`s run their cleanups innermost first. If a cleanup
expression itself has an error, that error is the one reported.

#### `(catch tag body...)` and `(throw tag [value])`
A way to jump out of the middle of something, such as a loop or a deep
chain of function calls, with a value. `catch` evaluates `tag`, then the
`body` forms, and normally returns the last one's value. But if
`(throw tag value)` runs while the body is running, whether in the body
itself or in any function it calls, everything in between stops at once,
and `catch` returns `value` (`'()` if there's no value). `throw` is an
ordinary function. `catch` and `throw` work as they do in Common Lisp.

```lisp
; The first negative number in a list, or '() if there isn't one --
; stopping as soon as it's found.
(define (first-negative lst)
  (catch 'found
    (dolist (x lst)
      (if (< x 0) (throw 'found x)))
    '()))
(first-negative (list 3 1 -4 1 -5))   ; => -4
(first-negative (list 3 1))           ; => ()

; Leaving a loop that would otherwise run forever.
(define i 0)
(catch 'stop
  (while #t
    (set! i (+ i 1))
    (if (= i 10) (throw 'stop i))))   ; => 10
```

- **Tags.** The tag is usually a quoted symbol, like `'found`. A throw goes
  to the innermost running `catch` whose tag matches: the same symbol,
  string, or number (`0` doesn't match `#f`, and `'x` doesn't match `:x`).
- **No catch.** A `throw` with no matching `catch` running is an error.
- **Cleanup still runs.** `unwind-protect` cleanups between the `throw`
  and the `catch` run on the way out.
- **Not an error.** A throw is not an error, so `catch-error` doesn't
  intercept it; and `catch` doesn't intercept errors (use `catch-error`
  for those).

```lisp
(catch 'a (catch 'b (throw 'a 1)) 2)                       ; => 1  (the outer catch gets it)
(catch 'x (catch-error (throw 'x 'ok) (e) 'not-this))      ; => ok
(throw 'nowhere 1)          ; an error: nothing catches nowhere
```

**How deep they can nest.** Like `catch-error`, `catch` and
`unwind-protect` run their body in a nested evaluation, which uses some of
Python's own stack while it's running. So they can be nested inside each
other only a few hundred deep: a function that calls itself *through* a
`catch`, starting a new `catch` on every call, stops with "maximum
recursion depth exceeded" after about 250 levels (about 330 for
`unwind-protect` and `catch-error`). A loop *inside* one `catch`, like the
examples above, can run any number of times.

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
; my-unless: the mirror image of `if` with no else-branch. Can't be
; written as a plain function -- a function would evaluate `then`
; regardless of whether `test` was true. (The standard `unless`, in
; macros_init.lsp, is the same idea with any number of body forms.)
(defmacro my-unless (test then)
  `(if (not ,test) ,then '()))
(my-unless (> 1 2) 'shown)     ; => shown

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

**What goes wrong without `gensym` — the old `while`.** `while` used to be
defined in `init.lsp` like this, with its loop function always named
`%loop`:

```lisp
(defmacro old-while (test body)
  `(let ()
     (define (%loop)
       (if ,test
           (begin ,body (%loop))
           '()))
     (%loop)))
```

It works — unless the caller's own code uses the name `%loop`. Suppose
you have a function that happens to have that name, and call it in the
loop's body:

```lisp
(define payments 0)
(define (%loop) (set! payments (+ payments 1)))   ; your function

(define month 0)
(old-while (< month 3)
  (begin
    (set! month (+ month 1))
    (%loop)))                  ; meant to call your function
payments                       ; => 0, not 3
```

`macroexpand-1` shows why:

```lisp
(let ()
  (define (%loop)
    (if (< month 3)
        (begin (begin (set! month (+ month 1))
                      (%loop))          ; your call...
               (%loop))                 ; ...and the macro's own call
        '()))
  (%loop))
```

Your body is pasted inside the macro's `let`, where `%loop` means the
macro's loop function. So your `(%loop)` calls that instead of your
function. It restarts the loop from inside its own body, `month` still
climbs to 3 and the loop ends, and your function never runs. There's no
error, just a wrong answer. A name starting with `%` is unlikely in code
you write yourself, which is why the old version usually worked, but
nothing stopped it from happening.

The `while` in `macros_init.lsp` asks `gensym` for the name instead, each
time the macro is expanded:

```lisp
(defmacro while (test . body)
  (let ((loop-name (gensym "while-loop")))
    `(let ()
       (define (,loop-name)
         (if ,test
             (begin ,@body (,loop-name))
             '()))
       (,loop-name))))
```

Each `while` now gets a symbol printed as something like
`%while-loop-12`. It can't be confused with anything the caller wrote,
even a function the caller named `%while-loop-12` (see `gensym`, below),
so the example above gives `3`. (It also takes any
number of body forms, via `. body` and `,@body`, so the `begin` isn't
needed.)

**Another example — a `while` variant that leaks its own loop
counter.** A fixed name can also capture one of the caller's *variables*.
A natural variation — a `while` that also exposes a running iteration
count to its body — shows this failure concretely:

```lisp
; count-while: like while, but the body can read `i` for "how many times
; has this loop run so far". Looks reasonable... until `i` collides with
; a variable the CALLER already had a different use for.
(defmacro count-while (test body)
  `(let ((i 0))
     (define (%loop)
       (if ,test
           (begin ,body (set! i (+ i 1)) (%loop))
           i))
     (%loop)))
```

Nest two of these to walk a 3x3 grid, using a variable also called `i` (an
extremely ordinary name to reach for) to total up how many inner-loop steps
ran across the whole grid:

```lisp
(define i 0)                   ; MY total inner-loop step count, unrelated
(define row 0)                 ; to count-while's own internal `i`
(count-while (< row 3)
  (begin
    (define col 0)
    (count-while (< col 3)
      (begin
        (set! i (+ i 1))       ; "increment my total" -- or so it looks
        (set! col (+ col 1))))
    (set! row (+ row 1))))
(display i)                    ; => 0, NOT 9 -- silently wrong, no error
```

Every `,body` gets spliced directly into the macro's own `(let ((i 0)) ...)`
template, so *every* `i` written inside a `count-while` body — at any
nesting depth — resolves to that call's own freshly bound `i`, not the
caller's outer variable of the same name. The outer `i` defined at the top
is never touched; `count-while`'s `set!` calls are all silently redirected
to internal counters that get thrown away the moment each `let` scope exits.
Nothing raises an error — the bug is a wrong answer, not a crash, which is
exactly what makes hand-written macro hygiene bugs painful to track down.

The fix: generate a fresh, guaranteed-unique symbol for the counter each
time the macro is *expanded* (not once at `defmacro` time — each call site
needs its own), and splice that symbol in everywhere the fixed name `i`
used to appear:

```lisp
(defmacro count-while (test body)
  (let ((cnt (gensym "count")))
    `(let ((,cnt 0))
       (define (%loop)
         (if ,test
             (begin ,body (set! ,cnt (+ ,cnt 1)) (%loop))
             ,cnt))
       (%loop))))
```

The outer `(let ((cnt (gensym "count"))) ...)` is the macro's OWN body —
ordinary Lisp code that runs once per expansion, computing a new symbol
like `%count-7`, unrelated to (and unable to collide with) anything a user
could type. Substituted via `,cnt`, that generated symbol — not the literal
name `i` — is what ends up bound by the template's `let`. Re-running the
exact same nested example above with this version now correctly prints `9`
— the caller's own `i` was never shadowed, because nothing inside either
`count-while` expansion is named `i` anymore. `(macroexpand-1 ...)` (see
Metaprogramming, below) is a good way to see this difference directly —
expanding a `count-while` call with each version shows the fixed `i` versus
a generated `%count-N` in exactly the position that matters.

A macro's own body, while it's still computing an expansion, is evaluated
by an ordinary (recursive) Python function call, not the fully
tail-call-optimized evaluator loop — so a transformer that itself did deep
non-tail recursion while *building* its expansion would be bounded by
Python's own recursion limit. This essentially never matters in practice
(a transformer builds a piece of code; it doesn't loop over runtime data),
and it does NOT affect the code a macro expands *to* — once the expansion
is produced, it's evaluated by the ordinary trampoline, tail calls and all
(see the tail-call note at the end of "Special forms", above).

### Standard macros

`while`, `do`, `when`, `unless`, `case`, `assert`, and `with-sqlite` are
macros written in Lisp, in `macros_init.lsp`, which every new environment
loads at startup (see
"Running it", above). The top of that file explains how macros are
written with backquote (`` ` ``), `,`, and `,@`, using these macros as the
examples, so it's a good place to start if you want to write your own.

`while` and `do` each turn into a small local function that calls itself
to go around the loop again. That call is a tail call, so a loop can run
any number of times without growing the stack. The function's name comes
from `gensym`, so it can't clash with a name in your code. To see what a
loop becomes, use `macroexpand-1`, e.g.
`(macroexpand-1 '(while (< i 3) (set! i (+ i 1))))`.

#### `(while test body...)`
Evaluates `test`; if it's true, evaluates the `body` forms, then starts
over. Stops the first time `test` is false, and returns `'()`. For
example, how many months until a balance falling 10% a month is below
500:

```lisp
(define balance 1000.0)
(define months 0)
(while (> balance 500)
  (set! balance (* balance 0.9))
  (set! months (+ months 1)))
months                         ; => 7
```

#### `(do ((var init [step])...) (end-test result...) body...)`
Common Lisp's `do` loop: a loop that steps one or more variables. It binds
each `var` to its `init`, then repeats:

1. If `end-test` is true, evaluate the `result` forms and return the value
   of the last one (`'()` if there are none).
2. Otherwise evaluate the `body` forms, give each `var` the value of its
   `step` (a `var` with no `step` keeps its value), and go back to 1.

The steps are all worked out before any variable changes, so every step
sees the values from the pass just finished. Often the steps do all the
work and there's no body:

```lisp
(do ((i 0 (+ i 1))
     (total 0 (+ total i)))
    ((= i 5) total))           ; => 10  (0 + 1 + 2 + 3 + 4)

(define (balance-after balance rate-percent payment n)
  (do ((month 0 (+ month 1))
       (b balance (- b (- payment (* b (/ rate-percent 1200))))))
      ((= month n) b)))
(round (balance-after 100000 6.0 599.55 12))   ; => 98772

; Fibonacci numbers: a's step uses the old b, and b's step the old a.
(do ((a 0 b)
     (b 1 (+ a b))
     (k 0 (+ k 1)))
    ((= k 10) a))              ; => 55
```

With a body, for side effects:

```lisp
(do ((year 2024 (+ year 1)))
    ((> year 2026))
  (display year)
  (newline))
```

prints `2024`, `2025`, and `2026` on separate lines.

Each variable must be written `(var init)` or `(var init step)`. Unlike
Common Lisp, a bare `var` (meaning "starts as `'()`") isn't accepted.

#### `(when test body...)`, `(unless test body...)`
`when` evaluates the `body` forms if `test` is true; `unless` evaluates
them if `test` is false. Either returns the last body form's value, or
`'()` if the body didn't run. Use them in place of an `if` that has no
else branch, especially when there's more than one thing to do, since
they need no `begin`:

```lisp
(define balance 1000)
(define payments 0)
(when (> balance 0)
  (set! balance (- balance 250))
  (set! payments (+ payments 1)))
(list balance payments)        ; => (750 1)

(unless (> balance 0) 'paid-off)   ; => ()
(when (> balance 0) 'still-owing)  ; => still-owing
```

Remember that only `#f` is false: `0` and `'()` count as true, so
`(when 0 'yes)` is `yes`.

#### `(case key-expr clause...)`
Picks one of several branches by matching a value against lists of
constants. It evaluates `key-expr` once, then finds the first clause whose
keys include that value, and evaluates that clause's body forms, returning
the last one's value. Each clause is one of:

| Clause | Matches |
|---|---|
| `((key1 key2 ...) body...)` | any of the keys |
| `(key body...)` | that one key |
| `(else body...)` | anything, if no clause before it matched; it must be the last clause (`otherwise` works the same, as in Common Lisp) |

The keys are symbols, numbers, or strings, **written without a quote**
(they aren't evaluated), and they're compared with `equal?`. If nothing
matches and there's no `else`, `case` returns `'()`.

```lisp
(define (region state)
  (case state
    (("CA" "OR" "WA") 'west)
    (("NY" "NJ" "CT") 'northeast)
    (else 'other)))
(region "OR")                  ; => west
(region "TX")                  ; => other

(define (months-in term)
  (case term
    ((annual yearly) 12)
    (quarterly 3)
    (monthly 1)))
(months-in 'quarterly)         ; => 3
(months-in 'weekly)            ; => ()
```

`case` is short for a `cond` that tests each clause with `member`; the
example above becomes (with a `gensym` name, so `state` is evaluated only
once):

```
(let ((%case-key-1 state))
  (cond ((member %case-key-1 '("CA" "OR" "WA")) 'west)
        ((member %case-key-1 '("NY" "NJ" "CT")) 'northeast)
        (else 'other)))
```

To choose by a test rather than by matching constants (for example, a
range of values), use `cond`.

#### `(assert test [message...])`
Does nothing (and returns `'()`) if `test` is true. If it's false, stops
with an error that shows the test itself, plus the message if you give
one. The message is any number of values, shown with spaces between them,
as `error` shows its arguments. Use it to check something that must be
true for the rest of the program to make sense, such as the input data
or a result along the way:

```lisp
(define balance -5)
(assert (>= balance 0))
; an error: assert: (>= balance 0) is false
(assert (>= balance 0) "balance went negative:" balance)
; an error: assert: (>= balance 0) is false: balance went negative: -5
(assert (< balance 0))         ; => ()
```

`assert` is a macro, not a function, so it can put the test's source code
into the message, not just its value (`#f`). The message is evaluated
only if the test fails.

#### `(with-sqlite (var path) body...)`
Opens the SQLite database at `path` (creating it if it doesn't exist),
binds `var` to the connection, and evaluates the `body` forms, returning
the last one's value. **The connection is always closed afterwards**, even
if the body stops with an error or a `throw`, so it's never left open:

```lisp
(with-sqlite (conn "loans.db")
  (sqlite-write-table conn "pools" pools 'replace)
  (sqlite-query conn "SELECT count(*) AS n FROM pools"))
```

It's `sqlite-open`, then the body inside an `unwind-protect` whose cleanup
is `sqlite-close`:

```
(let ((conn (sqlite-open "loans.db")))
  (unwind-protect
      (begin (sqlite-write-table conn "pools" pools 'replace)
             (sqlite-query conn "SELECT count(*) AS n FROM pools"))
    (sqlite-close conn)))
```

Changes are saved as each statement runs (connections use SQLite's
autocommit mode), so there's nothing to commit before the connection
closes. Once the body is done, `var` is gone and the connection is
closed, so return what you need from the database as the body's value.

---

## Built-in functions

### Arithmetic

All arithmetic functions reject non-numeric arguments (including booleans,
which Python treats as a subtype of `int` but this interpreter does not)
with `LispError: not a number: ...`, except where noted.

#### `(+ a b ...)`
Sum of zero or more numbers; `(+)` is `0`.

```lisp
(+ 1 2 3)                      ; => 6
(+)                            ; => 0
```

#### `(- a b ...)`
Subtracts left to right; `(- a)` (one argument) negates it. Raises
`LispError` if called with no arguments.

```lisp
(- 10 3 2)                     ; => 5   -- (10 - 3) - 2
(- 5)                          ; => -5
```

#### `(* a b ...)`
Product of zero or more numbers; `(*)` is `1`.

```lisp
(* 2 3 4)                      ; => 24
```

#### `(/ a b ...)`
Divides left to right (true/float division, not integer); `(/ a)` (one
argument) is `1/a`. Raises `LispError` if called with no arguments.

```lisp
(/ 20 2 5)                     ; => 2.0
(/ 4)                          ; => 0.25
```

#### `(mod a b)`, `(remainder a b)`
Both compute Python's `a % b` (floor-modulo — the result's sign follows the
divisor `b`). Despite the names, this interpreter does not give
`remainder` Scheme's usual distinct sign-follows-dividend behavior; the two
are identical here.

```lisp
(mod 7 3)                      ; => 1
(mod -7 3)                     ; => 2   -- sign follows the divisor
(remainder -7 3)               ; => 2   -- same as mod here, NOT -1
```

#### `(quotient a b)`
Truncating (toward zero) integer division: `int(a / b)`. Differs from `//`
for negative operands — e.g. `(quotient -7 2)` is `-3`, not `-4`.

```lisp
(quotient -7 2)                ; => -3
```

#### `(abs x)`
Absolute value.

```lisp
(abs -5)                       ; => 5
```

#### `(min a b ...)`, `(max a b ...)`
Minimum / maximum of the given arguments (at least one required).

```lisp
(min 3 1 4 1 5)                ; => 1
(max 3 1 4 1 5)                ; => 5
```

#### `(sqrt x)`
Square root. Raises a plain Python `ValueError` (not `LispError`) for
negative `x`.

```lisp
(sqrt 16)                      ; => 4.0
```

#### `(expt a b)`
`a` to the power `b`, via Python's `**` — stays an exact integer for
integer inputs, e.g. `(expt 2 10)` is `1024` (an int).

```lisp
(expt 2 10)                    ; => 1024
```

#### `(pow a b)`
`a` to the power `b`, via `math.pow` — always returns a float, e.g.
`(pow 2 10)` is `1024.0`.

```lisp
(pow 2 10)                     ; => 1024.0
```

#### `(log x [base])`
Natural log of `x`, or log base `base` if given, e.g. `(log 8 2)` is `3.0`.

```lisp
(log 8 2)                      ; => 3.0
```

#### `(exp x)`
e raised to the power `x`, via `math.exp`; always a float.

```lisp
(exp 1)                        ; => 2.718281828459045
```

#### `(erf x)`
The error function, via `math.erf` — what a standard normal CDF is built
from: `N(x) = 0.5 * (1 + erf(x / sqrt(2)))`. See `implied_vol.lsp`.

```lisp
(erf 0)                        ; => 0.0
```

#### `(floor x)`, `(ceiling x)`, `(round x)`, `(truncate x)`
Standard rounding. `round` uses banker's rounding (round-half-to-even) for
exact ties, matching Python's built-in `round`.

```lisp
(floor 3.7)                    ; => 3
(ceiling 3.2)                  ; => 4
(round 2.5)                    ; => 2   -- banker's rounding: ties go to even
(round 3.5)                    ; => 4
(truncate -3.7)                ; => -3
```

#### `(sigmoid z)`
`1 / (1 + e^-z)`, computed in a numerically stable way for very large
`|z|`. The same logistic function `logistic-regression`/`model-predict`
use internally, exposed directly for convenience.

```lisp
(sigmoid 0)                    ; => 0.5
```

### Random numbers

`random-float`/`random-int` draw from a single, shared random number
generator (Python's own `random` module) — every call anywhere in a
session advances the SAME underlying sequence, so `random-seed` affects
every subsequent draw, not just calls made right after it. (This is a
separate generator from `vectors-shuffle`'s own optional `seed` argument,
which — see "Vectors" — always creates its own independent, one-off
generator rather than touching this shared one, so shuffling a vector with
an explicit seed never disturbs the sequence `random-float`/`random-int`
are on.)

#### `(random-seed [n])`
Seeds the shared generator, so every `random-float`/`random-int` call from
here on (in this session) produces a reproducible sequence — the same seed
always produces the same sequence of draws. `(random-seed)` with no
argument re-seeds unpredictably instead, from system entropy (the state
the generator is already in before this is ever called, so this is only
useful to intentionally "forget" an earlier seed mid-session). Returns
`'()`.

```lisp
(random-seed 42)
(random-float)                 ; => 0.6394267984578837
(random-seed 42)
(random-float)                 ; => 0.6394267984578837 again -- same seed, same draw
```

#### `(random-float [lo hi])`
A random float, uniformly distributed over `[lo, hi)` — default `[0, 1)`
when neither is given. Both bounds must be given together; there's no
"just `hi`, `lo` defaults to 0" shorthand.

```lisp
(random-float)                 ; => e.g. 0.256 -- somewhere in [0, 1)
(random-float 10 20)           ; => e.g. 16.4  -- somewhere in [10, 20)
```

#### `(random-int lo hi)`
A random integer, uniformly distributed over `[lo, hi]` — **inclusive of
both endpoints** (unlike `random-float`'s half-open range above), matching
Python's own `random.randint`. `lo` and `hi` must both be plain integers;
raises `LispError` if `lo > hi`.

```lisp
(random-int 1 6)                ; => one of 1, 2, 3, 4, 5, 6 -- a die roll
(random-int 0 0)                ; => 0 -- a degenerate single-value range is fine
```

### Comparison / equality / booleans

#### `(= a b ...)`, `(< a b ...)`, `(> a b ...)`, `(<= a b ...)`, `(>= a b ...)`
Chained numeric comparisons — true only if the comparison holds between
*every* consecutive pair of arguments, e.g. `(< 1 2 3)` checks both `1<2`
and `2<3`. With 0 or 1 arguments, always `#t`.

```lisp
(< 1 2 3)                      ; => #t
(< 1 3 2)                      ; => #f -- 3<2 fails
```

#### `(not x)`
`#t` if `x` is `#f`; `#f` for everything else (including `0` and `'()`).

```lisp
(not #f)                       ; => #t
(not 0)                        ; => #f -- 0 is truthy here
```

#### `(eq? a b)`, `(equal? a b)`
Both are implemented as value equality here (`a is b or a == b` for `eq?`;
plain `a == b` for `equal?`) — this interpreter does **not** give `eq?`
Scheme's usual identity-only semantics. `(eq? '(1 2) (list 1 2))` is `#t`
here, where in most Schemes it would be `#f`. For most purposes the two are
interchangeable in this interpreter.

```lisp
(eq? '(1 2) (list 1 2))        ; => #t
(equal? "abc" "abc")           ; => #t
```

#### `(boolean? x)`
`#t` only for `#t`/`#f`.

```lisp
(boolean? #t)                  ; => #t
(boolean? 0)                   ; => #f
```

#### `(number? x)`
`#t` for any `int` or `float`, explicitly excluding booleans.

```lisp
(number? 3.5)                  ; => #t
(number? #t)                   ; => #f
```

#### `(integer? x)`
`#t` for an `int` that isn't a boolean; `#f` for a float even with no
fractional part (e.g. `3.0`).

```lisp
(integer? 3)                   ; => #t
(integer? 3.0)                 ; => #f
```

#### `(string? x)`
`#t` only for a genuine Lisp string (something written as a `"..."`
literal, or returned by a function documented as returning a string) —
**not** for a plain single character as produced by `string->list`, which
are a different underlying type. If in doubt, `(string? (string->list
"ab"))`'s first element is `#f`, not `#t`.

```lisp
(string? "hi")                 ; => #t
```

#### `(symbol? x)`
`#t` for a symbol (an identifier like `foo` or `list->vector`) — also `#t`
for a keyword (`:name`), since a keyword is a kind of symbol here, same as
Common Lisp.

```lisp
(symbol? 'foo)                 ; => #t
(symbol? :foo)                 ; => #t -- keywords are symbols too
```

#### `(keyword? x)`
`#t` only for a keyword (`:name`) — narrower than `symbol?`.

```lisp
(keyword? :foo)                ; => #t
(keyword? 'foo)                ; => #f
```

#### `(procedure? x)`
`#t` for anything callable — a built-in procedure or a user-defined one
made with `lambda`/`define`. **`#f` for a macro** — a macro isn't callable
the way a procedure is (it must be invoked in operator position to expand,
not passed around as a value and applied).

```lisp
(procedure? car)               ; => #t
(procedure? (lambda (x) x))    ; => #t
```

#### `(pair? x)`
`#t` for a cons cell — including an *improper* (dotted) pair like
`(1 . 2)`, which isn't a proper list.

```lisp
(pair? (cons 1 2))             ; => #t
(pair? '())                    ; => #f
```

#### `(list? x)`
`#t` if `x` is `'()` or any cons cell — this does not verify the list is
*proper* (nil-terminated); `(list? (cons 1 2))` is `#t` even though
`(1 . 2)` is a dotted pair, not a real list.

```lisp
(list? '(1 2 3))               ; => #t
(list? (cons 1 2))             ; => #t -- even though (1 . 2) isn't proper
```

#### `(null? x)`
`#t` only for `'()`.

```lisp
(null? '())                    ; => #t
(null? (list))                 ; => #t
```

#### `(vector? x)`
`#t` for a vector (built with `vector`/`make-vector` or `#(...)`).

```lisp
(vector? #(1 2))               ; => #t
```

#### `(date? x)`
`#t` for a date value (built with `date` or `date-add-days`).

```lisp
(date? (date 2024 1 1))        ; => #t
```

#### `(model? x)`
`#t` for any fitted regression model — see "Regression models", below.

#### `(struct? x)`
`#t` for an instance of any `defstruct`-defined type — see "Structs",
below.

#### `(sqlite-connection? x)`, `(sqlite-cursor? x)`
`#t` for a connection returned by `sqlite-open`, or a cursor returned by
`sqlite-execute`, respectively — see "SQLite", below.

### Pairs and lists

#### `(cons a b)`
Builds and returns a new pair with `car = a`, `cdr = b`.

```lisp
(cons 1 2)                     ; => (1 . 2)
(cons 1 (cons 2 '()))          ; => (1 2) -- built by hand, same as (list 1 2)
```

#### `(car p)`, `(cdr p)`
First element / rest of a pair. Raises `LispError: car/cdr: not a pair:
...` if `p` isn't a pair (e.g. calling on `'()`).

```lisp
(car (cons 1 2))               ; => 1
(cdr (cons 1 2))               ; => 2
(car (list 10 20 30))          ; => 10
(cdr (list 10 20 30))          ; => (20 30)
```

#### `(set-car! p x)`, `(set-cdr! p x)`
Change a pair in place: `set-car!` replaces its car (for a list, the first
element) with `x`, and `set-cdr!` replaces its cdr (for a list, the rest of
the list). Both return `'()`. `p` must be a pair, so `'()` is an error.

```lisp
(define lst (list 1 2 3))
(set-car! lst 'a)
lst                            ; => (a 2 3)
(set-cdr! (cdr lst) (list 'x 'y))
lst                            ; => (a 2 x y)
```

The pair itself is changed, not a copy, so every variable and list that
shares it sees the change:

```lisp
(define a (list 1 2))
(define b a)                   ; b is the same list as a, not a copy
(set-car! a 9)
b                              ; => (9 2)
```

Three cautions:

- **Don't change a quoted list.** `'(1 2 3)` written in a function is
  part of that function's code. Change it with `set-car!`, and the
  function returns the changed list from then on. Build a list you'll
  change with `list` or `cons`.
- **Don't make a cycle.** `(set-cdr! p p)`, or any change that makes a
  list lead back into itself, gives a list with no end. Printing it,
  `length`, `equal?`, or anything else that walks to the end of it, runs
  forever.
- **Most code doesn't need these.** `map`, `filter`, `append`, and
  `reverse` build new lists and leave the old ones unchanged, which is
  usually easier to follow.

#### `(list a b ...)`
Builds a proper list from its arguments (zero or more).

```lisp
(list 1 2 3)                   ; => (1 2 3)
```

#### `(append l1 l2 ... ln)`
Concatenates any number of lists (all but the last are copied; the last is
reused as-is for the tail). `(append)` returns `'()`.

```lisp
(append (list 1 2) (list 3 4)) ; => (1 2 3 4)
```

#### `(reverse l)`
Returns a new list with `l`'s elements in reverse order.

```lisp
(reverse (list 1 2 3))         ; => (3 2 1)
```

#### `(length l)`
Number of elements in a proper list.

```lisp
(length (list 1 2 3))          ; => 3
```

#### `(list-ref l n)`
The `n`-th element (0-based). Raises `LispError: list-ref: index N out of
range (0..M)` if `n` is out of bounds.

```lisp
(list-ref (list 10 20 30) 1)   ; => 20
```

#### `(list-tail l n)`
The sublist of `l` starting at position `n` (0-based) — i.e. `l` with its
first `n` elements dropped. `(list-tail l 0)` is `l` itself;
`(list-tail l (length l))` is `'()`. Raises `LispError` if `n` is out of
range.

```lisp
(list-tail (list 1 2 3 4 5) 2) ; => (3 4 5)
```

#### `(assoc key alist)`
Searches `alist` — a list of `(key . value)` **pairs**, built with `cons`,
e.g. `(list (cons 'a 1) (cons 'b 2))` — for an entry whose key is `equal?`
to `key`. Returns the matching `(key . value)` pair (so its value is
`(cdr (assoc key alist))`), or `#f` — not `'()`, which is truthy here,
same as Scheme — if none match.

```lisp
(define al (list (cons 'a 1) (cons 'b 2)))
(assoc 'b al)                  ; => (b . 2)
(cdr (assoc 'b al))            ; => 2
(assoc 'z al)                  ; => #f
```

#### `(member x l)`
The sublist of `l` starting at the first element `equal?` to `x`, or `#f`
(not `'()`, same reasoning as `assoc`) if none match.

```lisp
(member 3 (list 1 2 3 4 5))    ; => (3 4 5)
(member 99 (list 1 2 3))       ; => #f
```

#### `(map f l)`
Applies `f` to each element of `l` in order, returning a new list of the
results.

```lisp
(map (lambda (x) (* x x)) (list 1 2 3))    ; => (1 4 9)
```

#### `(filter f l)`
Returns a new list of just the elements of `l` for which `(f x)` is true.

```lisp
(filter (lambda (x) (> x 2)) (list 1 2 3 4))   ; => (3 4)
```

#### `(sort seq [key])`
Returns a NEW list or vector with `seq`'s elements in ascending order;
`seq` itself is unchanged. The sort is stable (elements that compare equal
keep their original order). A vector of numbers is sorted with numpy, so
even millions of elements sort in a fraction of a second.

`key`, if given, is a procedure of one argument that returns what to
compare for each element — a number or string, anything `<` can compare —
so the elements themselves can be anything. Without `key`, the elements
themselves are compared. Raises an error if two elements (or keys) can't
be compared, e.g. a number and a string.

```lisp
(sort (list 3 1 2))                                  ; => (1 2 3)
(sort (vector 3 1 2.5))                              ; => #(1.0 2.5 3.0)
(sort (list "pear" "apple" "fig"))                   ; => ("apple" "fig" "pear")
(sort (list (list "b" 2) (list "a" 3) (list "c" 1))
      (lambda (row) (car (cdr row))))                ; => (("c" 1) ("b" 2) ("a" 3))
```

#### `(reduce f l [init])`
Left fold. With `init` given, starts the accumulator there and folds `f`
over every element of `l`; without it, uses `l`'s first element as the
initial accumulator and folds over the rest (an empty `l` with no `init`
has no first element to start from, and raises an error).

```lisp
(reduce + (list 1 2 3 4))      ; => 10
(reduce + (list 1 2 3 4) 100)  ; => 110
```

#### `(apply f arg1 arg2 ... args)`
Calls `f` with `arg1`, `arg2`, ... as individual leading arguments,
followed by the *elements* of the final argument `args` (a list).
`(apply f lst)` — no leading arguments — is the common case: spreading a
list into positional arguments, e.g. `(apply + (list 1 2 3))` is `6`, and
`(apply + 1 2 (list 3 4 5))` is `15`. Requires at least 2 arguments total
(`f` and one list).

```lisp
(apply + (list 1 2 3))         ; => 6
(apply + 1 2 (list 3 4 5))     ; => 15
```

### Hash tables

A mutable table for fast key lookup — reach for this instead of an `assoc`
list once you're doing many lookups against the same data, since `assoc`
is a linear scan and this isn't. Keys may be any *immutable* value: a
number, string, symbol, keyword, or date — not a list, vector, or struct
(none of those can be a Python `dict` key either, for the same underlying
reason: nothing stops them being mutated after insertion, which would
silently corrupt the table). Using one anyway raises a clear `LispError`
rather than a raw Python exception.

#### `(make-hash-table)`
Returns a new, empty hash table.

```lisp
(define h (make-hash-table))
```

#### `(hash-table-set! h key value)`
Sets `key`'s value in `h`, inserting it if new, overwriting it otherwise.
Returns `'()`.

```lisp
(hash-table-set! h 'name "Ada")
```

#### `(hash-table-ref h key [default])`
The value stored under `key`, or `default` if given and `key` isn't
present, or `#f` otherwise — not `'()`; see `assoc`'s docstring under
"Pairs and lists" for why. Since a stored value can itself legitimately be
`#f`, use `hash-table-has?` (not this) when you need to tell "no such key"
apart from "the key maps to `#f`".

```lisp
(hash-table-ref h 'name)               ; => "Ada"
(hash-table-ref h 'missing)            ; => #f
(hash-table-ref h 'missing "nobody")   ; => "nobody"
```

#### `(hash-table-has? h key)`
`#t` if `key` is present in `h` (regardless of its value).

```lisp
(hash-table-set! h 'flag #f)
(hash-table-has? h 'flag)      ; => #t  -- present, even though its value is #f
```

#### `(hash-table-remove! h key)`
Removes `key` from `h` if present; a no-op (not an error) if it wasn't
there. Returns `'()`.

#### `(hash-table-count h)`
The number of entries in `h`.

#### `(hash-table-keys h)`, `(hash-table-values h)`
A list of every key, or every value, in `h` (insertion order — the same
order Python's own `dict` iterates in).

#### `(hash-table->alist h)`
Every entry in `h` as a list of `(key . value)` pairs, ready for `assoc`.

```lisp
(hash-table->alist h)          ; => ((name . "Ada") (flag . #f))
```

#### `(hash-table-for-each f h)`
Calls `(f key value)` once for every entry in `h`, for side effects
(building a report, summing values, ...); returns `'()`.

```lisp
(define total 0)
(hash-table-for-each (lambda (k v) (set! total (+ total v))) h)
```

### Strings

#### `(string-append s1 s2 ...)`
Concatenates zero or more strings.

```lisp
(string-append "foo" "bar")    ; => "foobar"
```

#### `(string-length s)`
Character count.

```lisp
(string-length "hello")        ; => 5
```

#### `(substring s start [end])`
`s` from index `start` up to (not including) `end`, which defaults to the
end of the string. Out-of-range indices are silently clamped, like a
Python slice — not an error.

```lisp
(substring "hello world" 0 5)  ; => "hello"
(substring "hello" 2)          ; => "llo"
```

#### `(string=? a b)`, `(string<? a b)`, `(string>? a b)`
Two-argument lexicographic comparison (not chained/variadic like the
numeric comparisons).

```lisp
(string=? "abc" "abc")         ; => #t
(string<? "abc" "abd")         ; => #t
```

#### `(string->number s)`
Parses `s` as an `int` if it contains neither `.` nor `e`/`E`, otherwise as
a `float`. Raises a plain Python `ValueError` (not `LispError`) if `s`
isn't a valid number.

```lisp
(string->number "3.14")        ; => 3.14
(string->number "42")          ; => 42
```

#### `(number->string n)`
Converts a number to its display string, e.g. `3` → `"3"`, `3.0` →
`"3.0"`.

```lisp
(number->string 3)             ; => "3"
```

#### `(string->list s)`, `(list->string l)`
Convert between a string and a list of its individual characters.

```lisp
(string->list "ab")            ; => (a b)  -- a list of single characters
(list->string (string->list "ab"))   ; => "ab"
```

#### `(string-upcase s)`, `(string-downcase s)`
Case conversion.

```lisp
(string-upcase "hi")           ; => "HI"
(string-downcase "HI")         ; => "hi"
```

#### `(string->symbol s)`, `(symbol->string sym)`
Convert between a string and a symbol.

```lisp
(string->symbol "foo")         ; => foo
(symbol->string 'foo)          ; => "foo"
```

#### `(string c1 c2 ...)`
Builds a string by concatenating its arguments (typically single
characters from `string->list`) — the same operation as `string-append`.

```lisp
(string "a" "b" "c")           ; => "abc"
```

#### `(string-search haystack needle [start])`
The index of the first occurrence of `needle` in `haystack`, at or after
`start` (default `0`), or `#f` if there isn't one — not `-1`, and not
`'()` (which, like Scheme's, is truthy here — only `#f` is false), so a
match right at the very start (`0`) still tests true.

```lisp
(string-search "hello world" "world")   ; => 6
(string-search "hello world" "xyz")     ; => #f
(if (string-search s "xyz") "found" "not found")
```

#### `(string-contains? s sub)`
`#t` if `sub` occurs anywhere in `s`.

```lisp
(string-contains? "hello world" "wor")  ; => #t
```

#### `(string-split s [sep])`
`s` split into a list of pieces. With `sep` (an exact substring, not a
single character necessarily): splits on every occurrence, so consecutive
separators produce an empty piece between them. Without `sep`: splits on
runs of whitespace instead, with no empty pieces — for tokenizing
free-form text.

```lisp
(string-split "a,b,,c" ",")     ; => ("a" "b" "" "c")
(string-split "  foo  bar ")    ; => ("foo" "bar")
```

#### `(string-replace s old new)`
`s` with every occurrence of `old` replaced by `new`.

```lisp
(string-replace "foo bar foo" "foo" "X")   ; => "X bar X"
```

#### `(string-trim s)`
`s` with leading and trailing whitespace stripped.

```lisp
(string-trim "  hi  ")         ; => "hi"
```

### Formatting numbers and text

`format` builds a line of text, such as a report row, a log message, or a file
name, with numbers rounded to a set number of decimals, grouped with
commas, and lined up in fixed-width fields. It fills each `{}` placeholder
in a template string with the next argument:

```lisp
(format "{} loans, {:,.2f} total balance" 42 12345678.9)   ; => "42 loans, 12,345,678.90 total balance"
```

**Format specs.** The text after the colon in `{:spec}` is a **format
spec**: how to lay out that value. It's the spec language of Python's
`format()`, and the same one `*column-number-format*` uses (see
"Columns"). A spec is made of these parts, each optional, in this order:

| Part | Meaning | Spec | Value | Result |
|---|---|---|---|---|
| fill and alignment | `<` left, `^` center, or `>` right in the field, optionally after a fill character (default: a space) | `*^9` | `"mid"` | `"***mid***"` |
| sign | `+` puts a `+` on positive numbers | `+.1f` | `3.14` | `"+3.1"` |
| `0` | pad a number with zeros, not spaces | `05d` | `42` | `"00042"` |
| width | the field's width, in characters | `>8` | `"CA"` | `"      CA"` |
| `,` | group the thousands with commas | `,` | `1234567` | `"1,234,567"` |
| `.N` | for a number (with `f` or `%`), the number of decimals; for text, the most characters to keep | `.2f` | `6.256` | `"6.26"` |
| type | `f` fixed decimals, `%` a percentage (× 100, followed by `%`), `d` a whole number, `e` scientific notation | `.2%` | `0.0525` | `"5.25%"` |

So `>12,.2f` means "right-justified in 12 characters, with commas and 2
decimals", and `<20` means "left-justified in 20 characters". Things to
know:

- With a width but no alignment, numbers are right-justified and text is
  left-justified, which is usually what a table wants.
- A value longer than its field isn't cut off; the field just grows. For
  text, `.N` cuts it to `N` characters (`<8.3` of `"abcdef"` is
  `"abc     "`).
- Rounding is to the nearest value; a tie goes to the even digit, as with
  `round`: `{:.1f}` of `6.25` is `"6.2"`. This rarely comes up, because
  most decimals (like `6.35`) aren't stored exactly, so they're not a
  true tie.
- `d` needs a whole number; to round a fraction to a whole number, use
  `.0f`. Number-only parts (`f`, `%`, `d`, `,`, `.N` with a type) on text
  are an error.
- A value that isn't a number (a string, date, symbol, list, `#t`, ...)
  is laid out as its display text, as `display` would show it, so the
  width and alignment parts work on it. `nan` is written `nan`.

#### `(format template arg...)`
`template` with each `{}` replaced by the next argument's display text,
and each `{:spec}` by the next argument laid out by `spec`. There must be
exactly one argument per placeholder. For a literal `{` or `}`, write
`{{` or `}}`. Returns the string; show it with `display`.

```lisp
(format "{:,.2f}" 1234567.891)                               ; => "1,234,567.89"
(format "[{:<8}] [{:^8}] [{:>8}]" "CA" "NY" "TX")            ; => "[CA      ] [   NY   ] [      TX]"
(format "[{:>10,.2f}]" 1234.5)                               ; => "[  1,234.50]"
(format "WAC {:.3f}%, as of {}" 6.2604165 (date 2023 1 1))   ; => "WAC 6.260%, as of 2023-01-01"
(format "{:.2%}" 0.0525)                                     ; => "5.25%"
(format "{:+.1f} {:05d} {:*^9}" 3.14159 42 "mid")            ; => "+3.1 00042 ***mid***"
(format "{{}} is a placeholder")                              ; => "{} is a placeholder"
(format "{} {}" 1)          ; an error: two placeholders, one argument
(format "{:.2f}" "CA")      ; an error: .2f is for numbers
```

A small report, one `format` per line (`apply` passes each row's
elements as the arguments):

```lisp
(define rows (list (list "CA" 1234567.5 6.25)
                   (list "NY" 987654.25 5.875)
                   (list "TX" 45000 7.1)))
(display (format "{:<6}{:>15}{:>8}\n" "State" "Balance" "WAC"))
(dolist (r rows)
  (display (apply format "{:<6}{:>15,.2f}{:>8.3f}\n" r)))
```

prints

```
State         Balance     WAC
CA       1,234,567.50   6.250
NY         987,654.25   5.875
TX          45,000.00   7.100
```

#### `(format-value x [spec])`
One value as a string, laid out by `spec`, or as its display text if
there's no spec. `(format-value x ",.2f")` is the same as
`(format "{:,.2f}" x)`. It's handy when the spec is worked out as the
program runs, such as a width chosen from the data:

```lisp
(format-value 1234567.891 ",.2f")          ; => "1,234,567.89"
(format-value "abcdef" "<8.3")             ; => "abc     "
(define width 10)
(format-value "CA" (format ">{}" width))   ; => "        CA"
```

#### Format specs in templates: `{{name:spec}}`
`template.lsp`'s `template-render` (see its header comment, and "SQLite",
below) takes the same specs. `{{name}}` inserts the value bound to `name`,
and `{{name:spec}}` inserts it laid out by `spec`. Everything after the
colon is the spec, exactly as written.

```lisp
(load "template.lsp")
(template-render "Pool {{pool}}: {{loans:,}} loans, balance {{upb:,.2f}}, WAC {{wac:.3f}}%"
                 (template-bindings (pool "P1") (loans 1204) (upb 245678901.5) (wac 6.2604)))
; => "Pool P1: 1,204 loans, balance 245,678,901.50, WAC 6.260%"
```

In `template-render-sql`, a spec is an error: there, `{{name}}` becomes a
`?` parameter, and the value goes to SQLite as it is, not as text.

### Vectors

Vectors are fixed-size and mutable, holding numbers, strings, and/or dates
(not lists or booleans) — an attempt to put anything else in one raises
`LispError: not a number, string, or date: ...`. `vector-ref`/`vector-set!`
do **not** bounds-check their index; an out-of-range index raises a plain
Python `IndexError`, not a `LispError`.

This section covers making, reading, and changing vectors. Arithmetic,
comparisons, statistics, and time-series functions on whole vectors are in
the next section, "Vector math and statistics"; a vector of numbers with a
value missing holds NaN there (written `nan`).

**Memory: vectors are backed by numpy, not a Python list.** This matters
once a vector reaches into the millions of elements — e.g. a large
loan-level dataset pulled in via `sqlite-query`, or a big Monte-Carlo path
array — where it's the difference between a couple of GB and a couple
dozen. A plain Python list of numbers costs ~32 bytes per element (an
8-byte pointer plus a 24-byte float/int object); a packed numpy array costs
as little as 1 byte per element, depending on what's actually in it:

| What the vector holds | dtype | bytes/element | vs. a Python list |
|---|---|---|---|
| Only the integers 0 and/or 1 (a flag column) | `int8` | 1 | 32x smaller |
| Plain integers, not all 0/1 | `int32` | 4 | 8x smaller |
| At least one non-integer number | `float32` | 4 | 8x smaller |
| Any string or date (text or date columns, or a mix) | `object` | ~32 | no change |

A vector's dtype is picked automatically the moment it's built, from
whatever's actually in it — nothing to configure at the Lisp level. It can
also *widen* later: `vector-set!`/`vector-fill!` will transparently
upgrade a vector's dtype in place if you write in a value its current
dtype can't hold exactly (e.g. writing `50000` into a vector that's so far
only ever held `0`/`1`, or writing a date into a numeric vector) — this
comes up naturally with `column_engine.lsp`'s `calculate-all`, which
pre-allocates a column with `(make-vector n initial-value)` and fills it in
row by row, long before the real range of values it'll end up holding is
known.

**Precision: `float32`, not `float64`.** A `float32` element carries about
7 significant decimal digits — plenty for a residential-mortgage-scale
dollar figure (comfortably under $1,000,000) or a rate/ratio that only
ever needs 3-4 significant figures, which is what this default is tuned
for, but *not* enough to distinguish amounts to the penny once a single
figure reaches into the tens of millions (e.g. a pool-level balance total).
A value only ever loses precision once, at the moment it's written into a
vector — every read and every downstream computation after that (including
`linear-regression`/`logistic-regression`'s own fitting, which works from
full-precision numbers pulled back out of the vector) happens at full
double precision, same as always; the compact storage doesn't compound
error across computations. A value read back out of a vector (by
`vector-ref`, `table-row`, ...) comes back as the short decimal the
`float32` holds — `0.964`, not the `0.9639999866485596` it would widen to.

If a dataset needs more precision than this default gives — dollar figures
in the billions, say — the fix is a one-line, interpreter-wide change in
`lisp_core.py` itself, not something adjustable from Lisp code:
`FLOAT_DTYPE`/`INT_DTYPE`/`BOOL_INT_DTYPE` are the first three lines of the
`LispVector` class definition. Changing `FLOAT_DTYPE = np.float32` to
`np.float64` there reverts every vector in the interpreter to full double
precision, at the original 4x-smaller-than-a-list memory savings instead of
8x/32x.

#### `(vector a b ...)`, `#(a b ...)`
Builds a vector from its arguments. `#(...)` is reader syntax for a vector
*literal* (its contents are NOT evaluated, unlike `(vector ...)`'s
arguments, which are).

```lisp
(vector 1 2 3)                 ; => #(1 2 3)
#(1 2 3)                       ; => #(1 2 3)
```

#### `(make-vector n [fill])`
A new vector of `n` copies of `fill` (default `0`).

```lisp
(make-vector 3)                ; => #(0 0 0)
(make-vector 3 9)               ; => #(9 9 9)
```

#### `(vector-ref v i)`
Element at index `i` (no bounds check — see caveat above).

```lisp
(vector-ref #(10 20 30) 1)     ; => 20
```

#### `(vector-set! v i x)`
Mutates element `i` to `x` in place. Returns `'()`.

```lisp
(define v (vector 1 2 3))
(vector-set! v 1 99)
v                               ; => #(1 99 3)
```

#### `(vector-length v)`
Number of elements.

```lisp
(vector-length #(1 2 3))       ; => 3
```

#### `(vector-fill! v x)`
Mutates every element of `v` to `x` in place. Returns `'()`.

```lisp
(define v (vector 1 2 3))
(vector-fill! v 0)
v                               ; => #(0 0 0)
```

#### `(vector-copy v)`
A new, independent shallow copy.

```lisp
(vector-copy #(1 2 3))         ; => #(1 2 3), a distinct vector
```

#### `(vector-map f v)`
Applies `f` to each element of `v` (one vector only — no index argument),
returning a new vector of the results. See `vectors-map`, below, for the
multi-vector version.

```lisp
(vector-map (lambda (x) (* x x)) #(1 2 3))   ; => #(1 4 9)
```

#### `(vector-append v1 v2 ...)`
Concatenates any number of vectors into a new one.

```lisp
(vector-append #(1 2) #(3 4))  ; => #(1 2 3 4)
```

#### `(vector->list v)`, `(list->vector l)`
Convert between a vector and a proper list.

```lisp
(vector->list #(1 2 3))        ; => (1 2 3)
(list->vector (list 1 2 3))    ; => #(1 2 3)
```

#### `(vector-iterate first count f)`
Builds a `count`-element vector: the first element is `first`, and each
following element is `(f previous-element)`. Works for numbers or dates
(e.g. with `date-add-days` as `f`, to build a vector of consecutive dates).
Raises `LispError` if `count` is negative.

```lisp
(vector-iterate 1 5 (lambda (x) (* x 2)))    ; => #(1 2 4 8 16)
```

#### `(vector-slice v start [end])`
Sub-vector from `start` up to (not including) `end`, which defaults to the
end of the vector.

```lisp
(vector-slice #(1 2 3 4 5) 1 3)   ; => #(2 3)
```

#### `(vector-take v n)`
The first `n` elements, as a new vector.

```lisp
(vector-take #(1 2 3 4 5) 2)   ; => #(1 2)
```

#### `(vector-drop v n)`
All but the first `n` elements, as a new vector.

```lisp
(vector-drop #(1 2 3 4 5) 2)   ; => #(3 4 5)
```

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

### Vector math and statistics

(In `lisp_vector_math.py`.) These work on a whole vector at once, as one
numpy operation, so they're fast even on millions of values — far faster
than a Lisp loop over `vector-ref`. Use them in place of `vector-map` with
a lambda whenever there's one that does the job.

**Vectors and numbers.** Arithmetic and comparisons take two vectors of
the **same length** (a different length is an error), or a vector and a
single number, which is used with every element. A date counts as its day
number, so subtracting two vectors of dates gives the days between them.

**Missing values** are NaN, "not a number", which you write as `nan`:
a SQLite NULL in a numeric column, a blank in a CSV column of numbers, a
division by zero, or a lag that reaches before the start of a series.
Arithmetic involving NaN gives NaN, and **every statistic below skips NaN
values** (so `vector-mean` is the average of the values that are present).
In a vector of strings or dates, `'()` plays the same role.

**Results** are stored like any other vector (see "Vectors", above): whole
numbers stay integers, anything with a fraction is `float32`, and a
comparison gives a vector of `0` and `1`.

#### Arithmetic

#### `(vector-add a b)`, `(vector-sub a b)`, `(vector-mul a b)`, `(vector-div a b)`, `(vector-pow a b)`
`a + b`, `a - b`, `a * b`, `a / b`, and `a` to the power `b`, element by
element. Either argument (but not both) may be a single number. Dividing by
zero gives `inf` or `nan` rather than an error.

```lisp
(vector-add #(1 2 3) #(10 20 30))    ; => #(11 22 33)
(vector-sub #(10 20 30) 1)           ; => #(9 19 29)
(vector-mul #(1 2 3) 2.5)            ; => #(2.5 5.0 7.5)
(vector-div #(1 2 3) #(2 0 4))       ; => #(0.5 inf 0.75)
(vector-pow #(1 2 3) 2)              ; => #(1.0 4.0 9.0)
(vector-add #(1 2 3) #(10 20))       ; an error: the vectors have different lengths
```

#### `(vector-log v)`, `(vector-exp v)`, `(vector-sqrt v)`, `(vector-abs v)`
The natural log, e to the power, square root, and absolute value of each
element. The log or square root of a negative number is `nan`.

```lisp
(vector-sqrt #(1 4 9))               ; => #(1.0 2.0 3.0)
(vector-abs #(-2 3))                 ; => #(2 3)
```

#### `(vector-round v [decimals])`
Each element rounded to `decimals` places (default 0). An exact half rounds
to the even neighbor, like `round`.

```lisp
(vector-round #(1.26 2.5 3.5) 1)     ; => #(1.3 2.5 3.5)
(vector-round #(2.5 3.5))            ; => #(2.0 4.0)
```

#### `(vector-clip v low high)`
Each element limited to the range `low` to `high`; pass `'()` for no limit
on one side. Useful for capping outliers, e.g. an LTV over 150.

```lisp
(vector-clip #(5 50 150) 10 100)     ; => #(10 50 100)
(vector-clip #(5 50 150) '() 100)    ; => #(5 50 100)
```

#### Comparisons, masks, and picking elements

A comparison gives a **mask**: a vector of `1` (true) and `0` (false), one
per element. Masks combine with `vector-and`, `vector-or`, and
`vector-not`; `vector-select` keeps the elements where a mask is true, and
`table-filter` keeps the rows of a table where it's true.

#### `(vector= a b)`, `(vector/= a b)`, `(vector< a b)`, `(vector<= a b)`, `(vector> a b)`, `(vector>= a b)`
Compare element by element: equal, not equal, less than, and so on. Either
argument may be a single value. `vector=` and `vector/=` also work on
strings and dates; ordering a number against a string is an error. A NaN
is never equal to anything.

```lisp
(vector> #(1 5 10) 4)                        ; => #(0 1 1)
(vector= (vector "CA" "NY" "CA") "CA")       ; => #(1 0 1)
(vector<= (vector (date 2020 1 1) (date 2021 1 1)) (date 2020 6 1))   ; => #(1 0)
```

#### `(vector-and m1 m2 ...)`, `(vector-or m1 m2 ...)`, `(vector-not m)`
Combine masks: `1` where every mask is true, where any is true, or where
the mask is false. Any nonzero number counts as true; `0` and `nan` count
as false.

```lisp
(define rates #(3.5 6.0 7.2))
(vector-and (vector> rates 4) (vector< rates 7))   ; => #(0 1 0)
(vector-or #(1 0 0) #(0 0 1))                      ; => #(1 0 1)
(vector-not #(1 0 1))                              ; => #(0 1 0)
```

#### `(vector-where mask a b)`
Element by element, `a` where the mask is true and `b` where it's false.
`a` and `b` are vectors or single values (numbers, strings, or dates).

```lisp
(vector-where (vector> #(1 5 10) 4) "big" "small")        ; => #("small" "big" "big")
(vector-where (vector> #(1 5 10) 4) #(100 200 300) 0)     ; => #(0 200 300)
```

#### `(vector-select v mask)`
Just the elements of `v` where the mask is true, in order.

```lisp
(vector-select #(10 20 30 40) #(1 0 1 0))   ; => #(10 30)
```

#### `(vector-nan? v)`, `(vector-fill-nan v value)`, `(vector-fill-forward v)`
`vector-nan?` gives a mask of the missing elements. `vector-fill-nan`
replaces each missing element with `value`. `vector-fill-forward` replaces
each with the nearest earlier value that isn't missing (missing values
before the first real one stay missing) — e.g. to carry a monthly value
through months with no new data.

```lisp
(vector-nan? (vector 1.5 nan 3))                   ; => #(0 1 0)
(vector-fill-nan (vector 1.5 nan 3) 0)             ; => #(1.5 0.0 3.0)
(vector-fill-forward (vector nan 1.5 nan nan 3))   ; => #(nan 1.5 1.5 1.5 3.0)
```

#### Statistics

Each of these skips missing values; with no values present, the result is
`nan`.

#### `(vector-sum v)`, `(vector-count v)`
The total of the values, and how many values aren't missing.

```lisp
(vector-sum #(1 2 3 4))              ; => 10
(vector-sum (vector 1.5 nan 2))      ; => 3.5
(vector-count (vector 1.5 nan 2))    ; => 2
```

#### `(vector-mean v)`, `(vector-median v)`
The average, and the middle value (the average of the two middle values
when there's an even number).

```lisp
(vector-mean (vector 1 2 3 nan))     ; => 2.0
(vector-median #(5 1 3 2))           ; => 2.5
```

#### `(vector-variance v [population?])`, `(vector-stdev v [population?])`
The variance and standard deviation. By default these are the *sample*
statistics (dividing by n − 1); pass `#t` for the population versions
(dividing by n).

```lisp
(vector-variance #(2 4 4 4 5 5 7 9))       ; => 4.571428571428571
(vector-stdev #(2 4 4 4 5 5 7 9) #t)       ; => 2.0
```

#### `(vector-min v)`, `(vector-max v)`
The smallest and largest value. These also work on vectors of dates or of
strings (alphabetical order).

```lisp
(vector-min #(3 1 2))                                    ; => 1
(vector-max (vector (date 2020 1 1) (date 2021 6 1)))    ; => 2021-06-01
(vector-min (vector "pear" "apple"))                     ; => "apple"
```

#### `(vector-quantile v q)`
The value below which a fraction `q` of the values fall (`q` between 0 and
1; 0.5 is the median), interpolating between values. `q` may be a vector of
fractions, giving a vector of results.

```lisp
(vector-quantile #(1 2 3 4 5) 0.25)            ; => 2.0
(vector-quantile #(1 2 3 4 5) #(0.1 0.5 0.9))  ; => #(1.4 3.0 4.6)
```

#### `(vector-weighted-mean v weights)`
`sum(v × w) / sum(w)` — e.g. a balance-weighted average coupon (WAC).
Positions where either value is missing are skipped.

```lisp
(vector-weighted-mean #(5 7) #(100 300))   ; => 6.5
```

#### `(vector-correlation a b)`, `(vector-covariance a b [population?])`
The (Pearson) correlation, between −1 and 1, and the sample covariance
(population with `#t`). Positions where either value is missing are
skipped.

```lisp
(vector-correlation #(1 2 3 4) #(2 4 6 8))   ; => 1.0
(vector-covariance #(1 2 3 4) #(2 4 6 8))    ; => 3.3333333333333335
```

#### Time series

These treat a vector as values in time order, one per period (e.g. one per
month). **Loan-level data** — many loans, each with its own run of months
— needs the optional `groups` argument (e.g. the loan-id column): then a
lag never reaches from one loan's rows into another's. For that, the rows
must be sorted by loan and then by month, with one row per month (see
`table-sort`).

#### `(vector-lag v [n default groups])`
Each element's value `n` periods earlier (`n` defaults to 1; a negative
`n` looks ahead instead). **Where that reaches before the start of the
vector — or into another group — the result is `default`**, which is
`nan` if you don't give one (`'()` for a vector of strings or dates).

```lisp
(vector-lag #(10 20 30 40))                   ; => #(nan 10.0 20.0 30.0)
(vector-lag #(10 20 30 40) 2 0)               ; => #(0 0 10 20)
(vector-lag #(10 20 30 40) -1)                ; => #(20.0 30.0 40.0 nan)
(vector-lag #(10 20 30 40 50) 1 0 (vector "a" "a" "a" "b" "b"))   ; => #(0 10 20 0 40)
```

The last example lags each loan's balance separately: loan `"b"`'s first
month gets the default `0`, not loan `"a"`'s last value. That's how to get
each loan's **beginning-of-month balance** from its end-of-month balance.

#### `(vector-diff v [n groups])`, `(vector-pct-change v [n groups])`
The change from `n` periods earlier (default 1), and the fractional change
(`0.1` means up 10%). `nan` where there's no earlier value.

```lisp
(vector-diff #(100 103 101 110))       ; => #(nan 3.0 -2.0 9.0)
(vector-pct-change #(100 110 99))      ; => #(nan 0.1 -0.1)
```

#### `(vector-cumsum v)`, `(vector-cumprod v)`
Running totals and running products. `vector-cumprod` turns monthly
survival rates (1 − SMM) into the fraction of a pool still outstanding, or
monthly discount factors into cumulative ones. A missing value counts as 0
(for a sum) or 1 (for a product) but stays missing in the result.

```lisp
(vector-cumsum #(1 2 3 4))             ; => #(1 3 6 10)
(vector-cumprod #(0.5 0.5 0.5))        ; => #(0.5 0.25 0.125)
```

#### `(vector-rolling-mean v window)`, `(vector-rolling-sum v window)`
The average (or total) of each `window` consecutive values, ending at each
element; `nan` for the first `window − 1` elements. A window containing a
missing value is `nan`.

```lisp
(vector-rolling-mean #(1 2 3 4 5) 3)   ; => #(nan nan 2.0 3.0 4.0)
```

#### Building vectors

#### `(vector-range end)`, `(vector-range start end [step])`
The numbers from `start` (default 0) up to, but not including, `end`.

```lisp
(vector-range 5)            ; => #(0 1 2 3 4)
(vector-range 2 10 3)       ; => #(2 5 8)
```

#### `(vector-unique v)`
The distinct values of `v`, sorted.

```lisp
(vector-unique (vector 3 1 3 2 1))     ; => #(1 2 3)
(vector-unique (vector "b" "a" "b"))   ; => #("a" "b")
```

### Tables

(In `lisp_tables.py`.) A **table** is a list of `(name . vector)` columns,
all the same length — exactly what `sqlite-query`, `load-csv`,
`http-get-csv`, and `series-table` return, and what `display-columns` and
`write-columns-csv` accept. There's no separate table type, so a table is
ordinary Lisp data: `(car t)` is its first column, and `(cdr (car t))`
that column's vector.

The functions below select, filter, sort, group, join, and summarize
tables. Each returns a **new** table and leaves its argument unchanged.
They work on whole columns with numpy, so tables of millions of rows are
practical. Column names are strings; where a function takes several, pass
a list — `(list "state" "month")` — or just one name by itself.

To look at a table, use `(display-columns t)` — a text table in the
console, the Columns tab in the GUI, and a formatted table in Jupyter —
together with `table-head` for a big one.

Most examples in this section use this small table of loans:

```lisp
(define loans (make-table "id"      (vector "a" "a" "b" "b" "c")
                          "month"   #(1 2 1 2 1)
                          "state"   (vector "CA" "CA" "NY" "NY" "CA")
                          "balance" #(100 90 200 195 50)
                          "rate"    #(6.0 6.0 4.5 4.5 7.25)))
```

#### `(make-table name1 vector1 name2 vector2 ...)`
A table from alternating column names and vectors, which must all be the
same length.

```lisp
(make-table "x" #(1 2) "y" #(3 4))     ; => (("x" . #(1 2)) ("y" . #(3 4)))
```

#### `(table? x)`
`#t` if `x` is a table: a list of `(name . vector)` columns, all the same
length.

```lisp
(table? (make-table "x" #(1 2)))       ; => #t
(table? (list 1 2))                    ; => #f
```

#### `(table-column-names t)`, `(table-column t name)`, `(table-row-count t)`
The column names, the vector of one column (an error, listing the
columns, if there's none by that name), and the number of rows.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(table-column-names t)            ; => ("id" "balance")
(table-column t "balance")        ; => #(100 90)
(table-row-count t)               ; => 2
```

#### `(table-row t i)`
Row `i` (counting from 0) as an association list of `(name . value)`
pairs, so `(cdr (assoc "balance" row))` is that row's balance.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(table-row t 1)                   ; => (("id" . "b") ("balance" . 90))
```

#### `(table-head t [n])`, `(table-slice t start [end])`
The first `n` rows (default 10); and the rows from `start` up to, but not
including, `end` (default: to the end).

```lisp
(define t (make-table "x" #(10 20 30 40)))
(table-head t 2)                  ; => (("x" . #(10 20)))
(table-slice t 1 3)               ; => (("x" . #(20 30)))
```

#### `(table-select t names)`, `(table-drop-columns t names)`
Just the named columns, in the order given; or every column except those.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90) "rate" #(6.0 4.5)))
(table-select t (list "rate" "id"))   ; => (("rate" . #(6.0 4.5)) ("id" . #("a" "b")))
(table-drop-columns t "rate")         ; => (("id" . #("a" "b")) ("balance" . #(100 90)))
```

#### `(table-add-column t name values)`
The table with a column added at the end — or replaced, if it already has
one by that name. `values` is a vector with one value per row, or a single
value to put in every row. Compute a new column with the vector math
functions:

```lisp
(define t (make-table "balance" #(100 200) "rate" #(6.0 4.5)))
(table-add-column t "interest" (vector-div (vector-mul (table-column t "balance")
                                                       (table-column t "rate"))
                                           1200))   ; => (("balance" . #(100 200)) ("rate" . #(6.0 4.5)) ("interest" . #(0.5 0.75)))
(table-add-column t "pool" "P1")   ; => (("balance" . #(100 200)) ("rate" . #(6.0 4.5)) ("pool" . #("P1" "P1")))
```

#### `(table-rename-column t old new)`
The table with one column renamed.

```lisp
(table-rename-column (make-table "upb" #(100)) "upb" "balance")   ; => (("balance" . #(100)))
```

#### `(table-filter t mask)`
Just the rows where the mask is true. The mask is a vector of `1` and `0`,
one per row, as the vector comparisons make (see "Comparisons, masks, and
picking elements", above); combine conditions with `vector-and` and
`vector-or`.

```lisp
(define t (make-table "state" (vector "CA" "NY" "CA") "balance" #(100 200 50)))
(table-filter t (vector> (table-column t "balance") 75))   ; => (("state" . #("CA" "NY")) ("balance" . #(100 200)))
(table-filter t (vector-and (vector= (table-column t "state") "CA")
                            (vector< (table-column t "balance") 75)))   ; => (("state" . #("CA")) ("balance" . #(50)))
```

#### `(table-sort t names [descending?])`
The rows sorted by one column, or by several (by the first name, then ties
by the next, and so on). Ascending, unless `descending?` is `#t`. Rows that
tie keep their original order. Missing values sort last (first when
descending).

```lisp
(define t (make-table "state" (vector "NY" "CA" "CA") "balance" #(200 100 50)))
(table-sort t "balance")                 ; => (("state" . #("CA" "CA" "NY")) ("balance" . #(50 100 200)))
(table-sort t (list "state" "balance"))  ; => (("state" . #("CA" "CA" "NY")) ("balance" . #(50 100 200)))
(table-sort t "balance" #t)              ; => (("state" . #("NY" "CA" "CA")) ("balance" . #(200 100 50)))
```

#### `(table-append t1 t2 ...)`
The rows of each table, one table after another — e.g. to combine monthly
files. The tables must have the same column names (matched by name, in
the first table's order).

```lisp
(table-append (make-table "x" #(1 2)) (make-table "x" #(3)))   ; => (("x" . #(1 2 3)))
```

#### `(table-group-by t keys aggregations)`
One row per distinct value of the key column(s), sorted by key, holding
the key columns followed by one column per aggregation. Each aggregation
is a list:

| Aggregation | Result for each group |
|---|---|
| `(new-name 'count)` | the number of rows |
| `(new-name 'sum column)` | the total |
| `(new-name 'mean column)` | the average |
| `(new-name 'weighted-mean column weight-column)` | `sum(column × weight) / sum(weight)` — e.g. a balance-weighted coupon |
| `(new-name 'min column)`, `(new-name 'max column)` | the smallest and largest value (these work on strings and dates too) |
| `(new-name 'median column)`, `(new-name 'stdev column)` | the median, and the sample standard deviation |
| `(new-name 'first column)`, `(new-name 'last column)` | the value in the group's first or last row, in the table's order |

Missing values are skipped. The function name can also be a string, e.g.
`"sum"`.

```lisp
(define loans (make-table "state"   (vector "CA" "CA" "NY" "NY" "CA")
                          "balance" #(100 90 200 195 50)
                          "rate"    #(6.0 6.0 4.5 4.5 7.25)))
(table-group-by loans "state"
                (list (list "loans" 'count)
                      (list "upb" 'sum "balance")
                      (list "wac" 'weighted-mean "rate" "balance")))   ; => (("state" . #("CA" "NY")) ("loans" . #(3 2)) ("upb" . #(240 395)) ("wac" . #(6.2604165 4.5)))
```

Group by several columns by passing a list of keys, e.g.
`(table-group-by loans (list "state" "month") ...)`.

#### `(table-join left right keys [how])`
Combine the rows of two tables whose key column(s) match. Each output row
is a row of `left` followed by the other columns of the matching `right`
row. `how` is:

- `'inner` (the default) — keep only the `left` rows that have a match;
- `'left` — keep every `left` row; where there's no match, the `right`
  columns are missing (`nan`, or `'()` for strings and dates).

A `left` row that matches several `right` rows appears once for each. The
rows stay in `left`'s order. A `right` column with the same name as a
`left` one gets `_right` added to its name. The typical use is attaching
monthly market data to loan-month rows — see "Monthly time series", below.

```lisp
(define loans (make-table "id" (vector "a" "a" "b") "month" #(1 2 3)))
(define rates (make-table "month" #(1 2) "mortgage_rate" #(6.5 6.25)))
(table-join loans rates "month")   ; => (("id" . #("a" "a")) ("month" . #(1 2)) ("mortgage_rate" . #(6.5 6.25)))
(table-join loans rates "month" 'left)   ; => (("id" . #("a" "a" "b")) ("month" . #(1 2 3)) ("mortgage_rate" . #(6.5 6.25 nan)))
```

#### `(table-describe t)`
A table summarizing each numeric column: how many values are present,
their mean, standard deviation, minimum, 25th percentile (`p25`), median,
75th percentile (`p75`), and maximum. Missing values are skipped; columns
of strings or dates are left out. A quick first look at new data:

```lisp
(table-describe (make-table "id" (vector "a" "b" "c") "balance" #(100 200 300)))   ; => (("column" . #("balance")) ("count" . #(3)) ("mean" . #(200.0)) ("stdev" . #(100.0)) ("min" . #(100.0)) ("p25" . #(150.0)) ("median" . #(200.0)) ("p75" . #(250.0)) ("max" . #(300.0)))
```

### Monthly time series

(In `lisp_time_series.py`.) Mortgages work by the month, so the month is
the basic unit of time here.

**Month numbers.** A month is represented by a **month number**, the
integer `year × 12 + (month − 1)`: January 2020 is `24240`, February 2020
is `24241`, and January 2021 is `24252`. Because month numbers are plain
integers, month arithmetic is ordinary arithmetic — three months later is
`(+ m 3)`, a loan's age in months is `(- m first-payment-month)`, and
`vector-lag` by 1 is the previous month — and joining tables on them is
fast. The functions below convert dates, and the `YYYYMM` values loan-level
data uses for reporting periods (e.g. `202301`), to and from month
numbers. Each takes a single value or a whole vector.

**Series.** A time series is `(dates . values)`, a pair of vectors — the
shape `fred-series` returns. Build one from two table columns with
`(cons (table-column t "date") (table-column t "value"))`.

#### `(date->month-number d)`, `(month-number->date m)`
A date's month number (the day of the month is ignored), and the first day
of a month number's month.

```lisp
(date->month-number (date 2020 1 15))        ; => 24240
(month-number->date 24241)                   ; => 2020-02-01
(date->month-number (vector (date 2020 1 1) (date 2020 3 9)))   ; => #(24240 24242)
```

#### `(yyyymm->month-number n)`, `(month-number->yyyymm m)`
Convert between `YYYYMM` values, as loan-level data records reporting
periods, and month numbers. A month outside 01–12 is an error.

```lisp
(yyyymm->month-number 202301)                ; => 24276
(yyyymm->month-number #(202212 202301))      ; => #(24275 24276)
(month-number->yyyymm 24276)                 ; => 202301
```

#### `(date-add-months d n)`
The date `n` months after `d` (before, if `n` is negative), for one date or
a vector of dates. A day past the end of the new month becomes its last
day.

```lisp
(date-add-months (date 2020 1 31) 1)         ; => 2020-02-29
(date-add-months (date 2020 3 15) -3)        ; => 2019-12-15
```

#### `(months-between d1 d2)`
How many calendar months from `d1` to `d2` (the day of the month is
ignored). Either may be a vector.

```lisp
(months-between (date 2020 1 31) (date 2021 3 1))   ; => 14
```

#### `(month-range first last)`
A vector of every month number from `first` to `last`, inclusive; `first`
and `last` may be dates or month numbers.

```lisp
(month-range (date 2020 11 1) (date 2021 2 1))      ; => #(24250 24251 24252 24253)
```

#### `(series-monthly series [how])`
A daily or weekly series made monthly: one value per month that has data,
dated the first of the month. `how` chooses the value: `'mean` (the
default), `'last`, `'first`, `'sum`, `'min`, or `'max`. Missing values are
skipped.

```lisp
(define weekly (cons (vector (date 2023 1 5) (date 2023 1 12) (date 2023 2 2))
                     #(6.5 6.25 6.0)))
(series-monthly weekly)          ; => (#(2023-01-01 2023-02-01) . #(6.375 6.0))
(series-monthly weekly 'last)    ; => (#(2023-01-01 2023-02-01) . #(6.25 6.0))
```

#### `(series-values-at series months [fill-forward?])`
The series' value in each of the given months (a vector of month numbers,
or of dates). Several values in one month are averaged. A month with no
data gives `nan` — or, with `fill-forward?` `#t`, the latest earlier
month's value. This is the simplest way to attach a market series to every
loan-month row:

```lisp
(define weekly (cons (vector (date 2023 1 5) (date 2023 1 12) (date 2023 3 2))
                     #(6.5 6.25 6.0)))
(define months (month-range (date 2023 1 1) (date 2023 4 1)))
(series-values-at weekly months)       ; => #(6.375 nan 6.0 nan)
(series-values-at weekly months #t)    ; => #(6.375 6.375 6.0 6.0)
```

#### `(series-table (list (cons name series) ...) [fill-forward?])`
A table lining several series up by month, with the columns `"month"`
(month numbers), `"date"` (the first of each month), and one column per
series, named as given. The months run from the earliest month any series
has data to the latest, every month included. Several values in one month
are averaged; a month with no data is `nan` — or, with `fill-forward?` `#t`,
that series' latest earlier value.

```lisp
(define mortgage (cons (vector (date 2023 1 5) (date 2023 1 12) (date 2023 3 2))
                       #(6.5 6.25 6.0)))
(define cpi (cons (vector (date 2023 1 1) (date 2023 2 1)) #(300.5 301.1)))
(series-table (list (cons "mortgage" mortgage) (cons "cpi" cpi)))   ; => (("month" . #(24276 24277 24278)) ("date" . #(2023-01-01 2023-02-01 2023-03-01)) ("mortgage" . #(6.375 nan 6.0)) ("cpi" . #(300.5 301.1 nan)))
```

**Putting it together** — attach the 30-year mortgage rate and the
10-year Treasury yield, month by month, to loan-level rows (this needs a
FRED API key):

```lisp
(define market (series-table (list (cons "mortgage30" (fred-series "MORTGAGE30US" creds))
                                   (cons "dgs10" (fred-series "DGS10" creds)))
                             #t))
(define loans (sqlite-query conn "SELECT loan_id, monthly_reporting_period, current_interest_rate FROM loan_performance"))
(define loans (table-add-column loans "month"
                (yyyymm->month-number (table-column loans "monthly_reporting_period"))))
(define loans (table-join loans market "month" 'left))
(define loans (table-add-column loans "incentive"
                (vector-sub (table-column loans "current_interest_rate")
                            (table-column loans "mortgage30"))))
```

### Structs

See `(defstruct name slot...)` under "Special forms", above, for the
type-specific `make-<name>`/`<name>-<slot>`/`<name>-<slot>-set!`/`<name>?`/
`copy-<name>` names it generates. `struct?`, `struct-ref`, `struct-set!`,
and `struct-type-name` work generically on any struct instance, by
slot-name symbol, without needing to know its specific type; `call-method`
(below) is a different kind of generic tool, for the "lambda in a slot"
dispatch pattern struct inheritance enables — see its own entry. To use
*all* of an instance's slots inside a body as plain variables, see
`(with-struct struct-expr body...)` under "Special forms", above — it's a
special form (it needs the struct's runtime slot list to know which names to
bind), so it's documented there rather than here.

#### `(struct? x)`
`#t` for an instance of any `defstruct`-defined type.

```lisp
(defstruct point x y)
(struct? (make-point :x 1 :y 2))     ; => #t
(struct? 5)                          ; => #f
```

#### `(struct-ref s slot-name)`
Returns the value of `s`'s `slot-name` slot (a symbol, e.g. `'x`). Raises
`LispError` if `s` isn't a struct, or has no such slot.

```lisp
(defstruct point x y)
(define p (make-point :x 1 :y 2))
(struct-ref p 'x)              ; => 1
```

#### `(struct-set! s slot-name value)`
Mutates `s`'s `slot-name` slot in place. Same error conditions as
`struct-ref`. Returns `'()`.

```lisp
(struct-set! p 'x 99)
(struct-ref p 'x)              ; => 99
```

#### `(struct-type-name s)`
Returns `s`'s struct type's name, as a symbol (e.g. `'point`).

```lisp
(struct-type-name p)           ; => point
```

#### `(call-method accessor instance arg...)`
Calls the value stored in whichever slot `accessor` reads off `instance`
— `accessor` is a struct accessor **function value** (e.g. `animal-speak`,
evaluated normally, not quoted), not a symbol naming one — passing
`instance` as that value's own first argument, followed by any `arg`s.
`(call-method animal-speak d)` is exactly `((animal-speak d) d)`, just
without writing `d` twice; an ordinary function, so `instance` is only
ever evaluated once, same as any other function call.

**Putting a lambda in a slot, together with struct inheritance (see
`defstruct`, above), gives single-dispatch virtual-function-style
polymorphism** — `call-method` is the "method call" syntax for it. A
function written purely in terms of a *parent* type's accessor
automatically picks up a *child*'s override when handed a child instance,
because the accessor just reads whatever is actually stored in that slot
on the instance it's given:

```lisp
(defstruct animal (name "unknown") (speak (lambda (self) "...")))
(defstruct (dog (:include animal (speak (lambda (self) "Woof!")))))
(defstruct (cat (:include animal (speak (lambda (self) "Meow!")))))

(define (make-noise a) (call-method animal-speak a))  ; only ever mentions `animal`

(make-noise (make-dog))        ; => "Woof!"
(make-noise (make-cat))        ; => "Meow!"
(make-noise (make-animal))     ; => "..."          -- the un-overridden default
```

This genuinely dispatches per-instance (works through a mixed list of
animals, one call site, no `dog`/`cat`-specific code anywhere), but it's
missing two things a real `virtual` function gives you for free in a
language like C++: there's no implicit "self" — you always pass `instance`
by hand, as above — and there's no built-in way for an override to call
its parent's *original* implementation (a "super" call). For the second
one, since a slot's `default-expr` can be any expression, not just an
inline `lambda`, the fix is to name the base implementation and have the
override call it directly by name:

```lisp
(define (animal-speak-default self)
  (string-append (animal-name self) " makes a sound"))
(defstruct animal (name "unknown") (speak animal-speak-default))

; NOT (define (dog-speak self) ...) -- that name collides with the
; accessor defstruct generates for dog's OWN speak slot (dog-speak);
; since default-expr symbols aren't evaluated until the constructor
; actually runs, by which point the accessor has already taken that
; name, dog-speak the function would be silently shadowed. Give the
; override implementation a distinct name instead.
(define (dog-speak-impl self)
  (string-append (animal-speak-default self) ", specifically Woof!"))
(defstruct (dog (:include animal (speak dog-speak-impl))))

(call-method animal-speak (make-dog :name "Rex"))
; => "Rex makes a sound, specifically Woof!"
```

### Dates

#### `(date year month day)`
Builds a date. Raises `LispError: date: invalid date: ...` for an invalid
calendar date (month 13, Feb 30, etc.).

```lisp
(date 2024 3 15)               ; => 2024-03-15
```

#### `(date-year d)`, `(date-month d)`, `(date-day d)`
Integer accessors.

```lisp
(date-year (date 2024 3 15))   ; => 2024
(date-month (date 2024 3 15))  ; => 3
(date-day (date 2024 3 15))    ; => 15
```

#### `(date->string d)`
Converts to an ISO-format string, `"YYYY-MM-DD"`.

```lisp
(date->string (date 2024 3 15))    ; => "2024-03-15"
```

#### `(string->date s)`
Parses a `"YYYY-MM-DD"` string into a date. Raises `LispError:
string->date: invalid date string ... (want YYYY-MM-DD)` for any other
format or an invalid date.

```lisp
(string->date "2024-03-15")    ; => 2024-03-15
```

#### `(date-add-days d n)`
A new date `n` days after `d` (negative `n` goes earlier).

```lisp
(date-add-days (date 2024 3 15) 10)    ; => 2024-03-25
```

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

**Weighted fitting.** `linear-regression`, `logistic-regression`, and
`spline-regression` all take an optional trailing `weights` vector: one
non-negative number per observation, the same length as `y`. Omit it (or
pass `'()`) to weight every observation equally, exactly the original
behavior. Fitting still minimizes a sum of squared errors (or maximizes a
log-likelihood, for the logistic case) — weighting just means each
observation's contribution to that sum is multiplied by its own weight, so
a weight of `2` counts an observation as if it appeared twice, and a weight
of `0` excludes it entirely; only the weights' *relative* sizes matter, not
their absolute scale. This is the standard tool for fitting to **grouped**
data — e.g. one row per rate-incentive bucket rather than one row per loan
— where you want a bucket representing $500M of balance to influence the
fit far more than one representing $2M, and where a bucket's own average is
a more reliable (lower-variance) estimate the more balance stands behind
it:

```lisp
(define bucket-rate (vector 0.02 0.04 0.06 0.08))    ; one row per rate bucket
(define bucket-cpr   (vector 0.05 0.08 0.15 0.30))
(define bucket-balance (vector 450000000 12000000 8000000 300000000))
(define m (linear-regression bucket-rate bucket-cpr bucket-balance))
```

#### `(linear-regression x y [weights])`
Ordinary (or weighted) least-squares fit of `y = intercept +
sum(coefficients[i] * x[i])`. `x` is a vector, a list of vectors for
multiple predictors, **or a list of `(name . vector)` pairs** — exactly
`sqlite-query`'s own column-wise result shape, so a query's results can be
fed straight in with no manual name-stripping; `y` is a vector, or
likewise a `(name . vector)` pair, the same length as each predictor
vector; `weights` is the optional per-observation weight vector described
above. When `x`/`y` carry names this way, `model-report` (below) uses them
in place of the generic `x1`/`x2`/`y` placeholders. Returns a model of
kind `"linear"`. Raises an error if `x`/`y`/`weights` lengths mismatch, a
predictor has zero variance, the predictors are collinear, or a weight is
negative.

```lisp
; sqlite-query's result feeds straight in -- no (map cdr ...) needed:
(define rows (sqlite-query conn "select zero_flag, balance, loan_age from t"))
(define m (linear-regression (cdr rows) (car rows)))
(display (model-report m))   ; "Linear model:  zero_flag = ... + c*balance + c*loan_age"
```

**How the coefficients are found.** Fitting minimizes the (weighted) sum of
squared residuals —

```
sum over every observation i of:  weight[i] * (y[i] - prediction[i])^2
```

— the ordinary least-squares objective (with every `weight[i] = 1` unless
you pass your own, per "Weighted fitting" above). That objective is
*quadratic* in the coefficients, so its minimum has a closed-form solution:
setting its gradient to zero gives one linear equation per coefficient (the
"normal equations"), and the interpreter solves that linear system exactly,
in a single step, via Gauss-Jordan elimination with partial pivoting
(`solve_linear_system` in `lisp_regression.py`) — no searching, iterating,
or approximating, unlike `logistic-regression` below. (Predictors are
rescaled to mean 0 / unit variance first, purely to keep that linear system
numerically well-behaved regardless of a predictor's raw scale — a huge
ordinal date next to a small percentage, say — and the fitted coefficients
are converted back to the original scale afterward; this doesn't change
what's being minimized or the answer you get, only how reliably the solver
gets there.) Building the normal equations themselves is an O(n · p²)
reduction over every observation (`n` rows, `p` coefficients including the
intercept) — done with numpy matrix operations rather than a Python-level
loop, so a large `n` (e.g. a multi-million-row dataset pulled in via
`sqlite-query`) doesn't dominate fitting time; the actual `p`-by-`p` solve
afterward stays plain Python, since `p` (a handful of predictors) is never
the bottleneck.

```lisp
(define m (linear-regression prices demand))
(display (model-report m))
```

#### `(logistic-regression x y [weights])`
Maximum-likelihood fit of `p = sigmoid(intercept + sum(coefficients[i] *
x[i]))`, via Newton-Raphson (up to 50 iterations, or until convergence).
`x`/`y`/`weights` as `linear-regression`'s above (including `x`/`y`
accepting `(name . vector)` pairs); every value in `y` must be in `[0, 1]`
(a 0/1 label, or a probability) — values outside that range raise an
error. Returns a model of kind `"logistic"`. Near-perfect separability in
the data can prevent convergence and raises a descriptive error rather
than diverging silently.

**How the coefficients are found.** Fitting maximizes the (weighted)
log-likelihood of the data —

```
sum over every observation i of:
  weight[i] * ( y[i]*log(p[i]) + (1-y[i])*log(1-p[i]) )
```

— where `p[i]` is this model's own `sigmoid(...)` prediction for row `i`;
this is the standard maximum-likelihood objective for logistic regression
(equivalently, the negative of the weighted cross-entropy loss), with
every `weight[i] = 1` unless you pass your own. Unlike `linear-regression`'s
objective, this one is *not* quadratic in the coefficients, so there's no
closed-form solution — the interpreter instead finds the maximizing
coefficients iteratively, by Newton-Raphson (the same algorithm is also
called Iteratively Reweighted Least Squares, "IRLS", elsewhere). Starting
from all-zero coefficients, each iteration computes this objective's
gradient and Hessian at the current coefficients, solves for the step that
would exactly reach the maximum if the objective were quadratic right there
(via the very same linear-system solver `linear-regression` uses for its
one-shot solve), and takes that step; this repeats until a step is smaller
than `1e-8`, or 50 iterations pass without converging. If the data is
(nearly) perfectly separable by a predictor, the TRUE maximum sends that
coefficient toward infinity and the Hessian toward singular — caught and
reported as a descriptive error, rather than looping forever or silently
returning a runaway or meaningless answer. Each iteration's gradient/
Hessian (the same O(n · p²) shape as `linear-regression`'s normal
equations, above) is likewise built with numpy matrix operations, not a
Python-level loop — and since this whole computation repeats up to 50
times, it's where nearly all of `logistic-regression`'s fitting time goes
for a large dataset.

```lisp
(define m (logistic-regression prices demand))
(display (model-report m))
```

#### `(spline-regression x y [max-knots logistic? weights])`
A simple, dependency-free way to let a model bend instead of insisting on a
straight line. For each predictor `x`, a handful of "knot" locations are
chosen (automatically, at quantiles of `x`'s own values, or exactly where
you specify), and the model gets one extra *hinge* feature `max(0, x -
knot)` per knot alongside the plain linear term — or, for a predictor
marked `'categorical`, one 0/1 indicator column per non-baseline distinct
value instead of hinges. Fitting then just reuses `linear-regression`'s or
`logistic-regression`'s own fitting code on this expanded feature set.
Returns a model of kind `"spline"` (or `"spline-logistic"`). `x`/`y` accept
the same shapes `linear-regression`/`logistic-regression` do — including a
list of `(name . vector)` pairs for `x` and a `(name . vector)` pair for
`y` — and `model-report` (below) uses those names the same way.

**How the coefficients are found.** There's no separate spline-fitting
algorithm — `spline-regression` isn't a different way of minimizing
anything, it's a different set of *columns* to feed into one of the two
algorithms already described above. Every knot's hinge column and every
category's 0/1 indicator column (see the table below) is computed first;
those expanded columns are then handed to `fit_linear` (`logistic?` `#f`)
or `fit_logistic` (`logistic?` `#t`) exactly as if you had built those
columns yourself and called `linear-regression`/`logistic-regression`
directly on them — same objective, same closed-form-or-Newton-Raphson
solve, same optional `weights`, just applied to `x`'s expansion instead of
`x` itself.

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

For a predictor with EXACTLY two distinct values (e.g. a 0/1 flag),
`'categorical` and a knot count of `0` (plain linear) produce the
identical fitted model — a two-category `'categorical` expansion is just
one 0/1 indicator column for the non-baseline value, which for an
already-0/1 predictor is the same number, unchanged. The only real
difference is validation: `'categorical` requires at least 2 distinct
values up front and rejects an unseen category at `model-predict` time,
where plain linear accepts (and silently extrapolates/interpolates)
anything numeric.

`logistic?` (default `#f`) — if true, `y` must be in `[0, 1]`, and the
expanded basis is fit with logistic regression instead of OLS, so the
resulting `[0, 1]`-valued prediction, thanks to the non-linear basis,
doesn't have to be monotonic in `x` the way a plain `logistic-regression`
fit would be.

`weights` (optional, default: every observation weighted equally) — the
same per-observation weight vector `linear-regression`/`logistic-regression`
take (see "Weighted fitting", above); passed straight through to whichever
fit runs on the expanded basis.

```lisp
(define home-type (vector 0 1 0 1 1))          ; 0=own, 1=rent
(define m (spline-regression (list income home-type) happiness
                              (list 2 'categorical)))
(display (model-report m))
(model-predict m (list 50000 0))                ; predict for "own", income=50000
```

#### `(model-report m)`
Returns a multi-line string describing a fitted model: its equation, a
table of coefficients, and measures of fit. It uses the real predictor and
`y` names if the model was fit on `(name . vector)` pairs (see above),
otherwise `x1`, `x2`, ... and `y`.

The coefficient table has one row for the intercept and one per
predictor:

| Column | Meaning |
|---|---|
| `coefficient` | the fitted value |
| `std error` | its standard error: how much it would vary from sample to sample |
| `t value` / `z value` | the coefficient divided by its standard error |
| `p value` | the chance of a coefficient at least this far from 0 if the true value were 0 — a small p value (say under 0.05) means the predictor genuinely matters |

A linear model uses the t distribution with n − p degrees of freedom (p
counting the intercept); a logistic model uses the normal distribution
(z). **With weights**, a linear model's standard errors don't depend on
the weights' scale, only their relative sizes. For a logistic model, the
weights are rescaled to average 1 for the standard errors, so weighting
by balance in dollars doesn't make the model look vastly more certain
than its row count justifies — the weights say how much each row counts
relative to the others, not how many copies of it there are.

Measures of fit: for a linear model, R-squared and `n`. For a logistic
model, the log-likelihood, McFadden's pseudo-R-squared, the **AUC** (area
under the ROC curve: the chance that a randomly chosen row with y = 1 gets
a higher prediction than a randomly chosen row with y = 0; 0.5 is no
better than guessing, 1.0 is perfect ranking), the number of Newton-Raphson
iterations and whether it converged, and `n`.

For a spline model: its predictors, each with its knot locations (or
categories and baseline value) — flagging a purely linear predictor with 3
or fewer distinct values as a candidate for `'categorical` — then the same
coefficient table for the expanded features (each labeled with its
predictor's name, e.g. `income (knot 40000)` or `home_type = 1`), and the
same measures of fit.

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
  R-squared        = 0.998212
  n                = 5
```

#### `(model-coefficient-table m)`
The coefficient table from `model-report`, as a table (see "Tables") with
the columns `term`, `coefficient`, `std_error`, `t_value` (`z_value` for a
logistic model), and `p_value`. The first row is the intercept. Its
numbers are kept at full precision, so it's the way to use them in further
calculations — or `display-columns` it to see them.

```lisp
(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))
(table-column (model-coefficient-table m) "term")   ; => #("intercept" "x1")
```

#### `(model-lift-table m x y [bins weights])`
How well a model **ranks** rows — whether its highest predictions really
go with the highest outcomes, which is what matters when a model is used
to pick out or project the riskiest loans. The rows are sorted by
prediction, highest first, and split into `bins` groups of (nearly) equal
row count — 10 by default, i.e. deciles. The result is a table with one
row per group:

| Column | Meaning |
|---|---|
| `bin` | 1 holds the highest predictions |
| `rows` | the number of rows in the group |
| `weight` | their total weight (the row count, if no weights are given) |
| `mean_predicted` | the group's average prediction |
| `mean_actual` | the group's average actual `y` |
| `lift` | `mean_actual` divided by the overall average `y` |
| `cumulative_share` | the fraction of all `y` (e.g. of all payoffs) in groups 1 through this one |

With `weights` (e.g. balances), the averages are weighted. `x` and `y` are
as for `model-evaluate`; use held-out data to judge a model fairly. Good
ranking shows as `lift` well above 1 in the first bins and falling steadily.

```lisp
(define age #(1 2 3 4 5 6 7 8 9 10))
(define paid #(0 0 1 0 0 1 0 1 1 1))
(define m (logistic-regression age paid))
(table-column (model-lift-table m age paid 5) "lift")   ; => #(2.0 1.0 1.0 1.0 0.0)
```

#### `(model-evaluate m x y)`
Evaluates a fitted model's prediction quality against data — typically
held-out data it wasn't fit on — and returns a string report. `x`/`y`
follow the same shape rules as the fitting functions; the number of
predictor vectors in `x` must match the model's own predictor count. For a
non-probabilistic model (`"linear"`/`"spline"`): reports R-squared, RMSE,
and MAE against this new data. For a probabilistic model
(`"logistic"`/`"spline-logistic"`): reports log-likelihood, McFadden's
pseudo-R-squared (against an intercept-only model fit fresh on this new
data), AUC (see `model-report`), and classification accuracy at a 0.5
threshold — though for a rare outcome, such as a monthly payoff,
accuracy says little (predicting "no payoff" for every row is usually
99% accurate), and AUC or `model-lift-table` are more useful. Works
uniformly across every model kind, including spline models.

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

```lisp
(model-coefficients m)         ; => #(10.3)
```

#### `(model-intercept m)`
The model's fitted intercept (a plain number). Same linear/logistic-only
restriction as `model-coefficients`.

```lisp
(model-intercept m)            ; => -0.7
```

#### `(model-kind m)`
Returns `"linear"`, `"logistic"`, `"spline"`, or `"spline-logistic"`. Works
on any model.

```lisp
(model-kind m)                 ; => "linear"
```

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

[`model_utils.lsp`](model_utils.lsp)'s `(model->function m)` wraps this into
an ordinary Lisp function, one argument per predictor, instead of a list:

```lisp
(load "model_utils.lsp")
(define f (model->function m))
(f 50000 30)                           ; same as (model-predict m (list 50000 30))
```

#### `(model-slope m)`
Shorthand for "the (only) coefficient" — `(vector-ref (model-coefficients
m) 0)` — but raises a clear error if the model has more than one predictor
(use `model-coefficients` instead). Same linear/logistic-only restriction
as `model-coefficients`.

```lisp
(model-slope m)                ; => 10.3
```

#### `(model? x)`
`#t` for any fitted model (linear, logistic, spline, or spline-logistic).

```lisp
(model? m)                     ; => #t
(model? 5)                     ; => #f
```

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

### Linear programming

(In `lisp_simplex.py`, which uses the simplex solver in
`simplex/simplex_solver.py`, next to `lisp_interp/`.) These solve linear
programming problems: find the values of the variables `x1, x2, ...` that
**minimize** (or **maximize**) `c1·x1 + c2·x2 + ...`, subject to
constraints of the form `a1·x1 + a2·x2 + ... <= b` (or `>=`, or `=`), with
every variable at least 0. The variables can have names of your choosing,
such as `gnma_30`, so a problem with many variables stays readable.

**A problem** is an association list of six lists (the six things
`simplex_solver.py`'s `parse_lp_file` returns):

| Part | Holds |
|---|---|
| `"objective"` | the objective's coefficients, one per variable |
| `"constraints"` | one list per constraint, holding its coefficients, one per variable |
| `"relations"` | one per constraint: `"<="`, `">="`, or `"="` |
| `"rhs"` | one per constraint: its right-hand side |
| `"variables"` | the variables' names, one per variable (optional in `lp-solve`) |
| `"goal"` | `"minimize"` or `"maximize"` (optional in `lp-solve`: the default is `"minimize"`) |

`"objective"` and each list in `"constraints"` have one number for every
variable, in the same order as `"variables"`, with a `0.0` for a variable a
formula doesn't use. You don't have to write those zeros: `lp-read-file`
fills them in from a file that uses variable names. You can also build a
problem in Lisp; see `lp-solve`.

`linear_programming_example.lsp` is a worked example. It reads a problem
from `linear_programming_example.txt`: invest $100 million in four mortgage
pools for the most yield, within limits on concentration, average
duration, and credit risk. It solves the problem and prints the
allocation. Then it changes the problem in Lisp to see how the income
depends on the duration limit, and shows how an impossible limit is
reported. Run it from `lisp_interp/`:

```bash
python3 lisp_interpreter.py linear_programming_example.lsp
```

#### `(lp-read-file path)`
Reads a problem from a text file, and returns it as a problem list. The
file has this shape:

```
maximize
<the objective>
subject to
<constraint 1>
<constraint 2>
...
```

- The first line is `minimize` or `maximize` (in any mix of upper and
  lower case), and then a line with the objective. Maximizing is solved
  by minimizing the negative, and the optimal value is still reported as
  the maximum: see `lp-solve`.
- `subject to` starts the constraints, one per line. Each is a
  left-hand side, then a relation (`<=`, `>=`, or `=`), then the
  right-hand side, which is a single number.
- Blank lines, and lines starting with `#`, are ignored.
- All the numbers are read as floats.

The objective and the left-hand sides can be written either of two ways.
The objective decides which way the whole file uses.

**1. With variable names.** Write each as a formula, a sum of terms. A term
is a number and then a variable's name (`3 x`, `0.5 rate`), or just the
name (which means 1 times it). A file like this, the same problem as the
one in the second form below:

```
# Maximize 3x1 + 5x2
maximize
3 x1 + 5 x2
subject to
x1 <= 4
2 x2 <= 12
3 x1 + 2 x2 <= 18
```

The rules:

- **Spaces around everything.** Write `3 x1 + 5 x2`, not `3x1+5x2`: put a
  space between a number and a name, and around each `+` and `-`.
  (Something like `3x1` is an error that says so.)
- **Names** start with a letter or underscore, and have only letters,
  digits, and underscores (`gnma_30`, `rate2`, `_x`). Upper and lower case
  are different names. Use `_` where you'd use a space or a hyphen.
- **Order.** The variables are numbered in the order they first appear,
  starting with the objective, then the constraints. That's the order of
  `"variables"`, of the coefficients, and of the solution. A variable that
  appears only in a constraint costs nothing in the objective (its
  coefficient there is 0), and a variable a constraint doesn't mention has
  coefficient 0 in it.
- **A formula** can start with a `-` (`- x + 2 y`), and a name can appear
  more than once (`x + x` is `2 x`).

**2. With coefficients only.** Write a coefficient for every variable, in the
same order in every line, zeros included. The variables are named `x1`,
`x2`, and so on. A file for the same problem (`simplex/example_problem.txt`
is this file):

```
# Maximize 3x1 + 5x2, which is the same as minimizing -3x1 - 5x2
minimize
-3 -5
subject to
1 0 <= 4
0 2 <= 12
3 2 <= 18
```

Use this form for a problem with few variables. With many, the rows of
zeros are long, and easy to get wrong. Constraint lines here must all have
as many numbers as the objective does.

A file that doesn't follow the format is an error that names the problem
and shows the line. For the second file above:

```lisp
(define problem (lp-read-file "../simplex/example_problem.txt"))
problem
; => (("objective" -3.0 -5.0)
;     ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0))
;     ("relations" "<=" "<=" "<=")
;     ("rhs" 4.0 12.0 18.0)
;     ("variables" "x1" "x2")
;     ("goal" "minimize"))
(lp-solve problem)     ; => (("solution" 2.0 6.0) ("optimal-value" . -36.0))
```

For the first file, saved as `problem.txt`, the problem is the same, except
that the objective is `(3.0 5.0)` and the goal is `("maximize")`, and
solving it gives `(("solution" 2.0 6.0) ("optimal-value" . 36.0))`: the
same values of `x1` and `x2`, and the maximum, 36, of `3x1 + 5x2`.

`linear_programming_example.txt` is a larger example of the first form.

#### `(lp-solve problem [max-iterations])`
Solves a problem, returning

```
(("solution" x1 x2 ...) ("optimal-value" . v))
```

the value of each variable, in the same order as the problem's
`"variables"` and `"objective"`, and the optimal value of the objective:
its minimum, or, if the problem's goal is `"maximize"`, its maximum. Use
`assoc` to get each one. Here's a problem built in Lisp: minimize `x1 + x2`
subject to `x1 + 2x2 >= 4` and `3x1 + x2 >= 6`:

```lisp
(define problem
  (list (cons "objective"   (list 1 1))
        (cons "constraints" (list (list 1 2) (list 3 1)))
        (cons "relations"   (list ">=" ">="))
        (cons "rhs"         (list 4 6))))
(define result (lp-solve problem))
result                                 ; => (("solution" 1.6 1.2) ("optimal-value" . 2.8))
(cdr (assoc "solution" result))        ; => (1.6 1.2)
(cdr (assoc "optimal-value" result))   ; => 2.8
```

A quoted list works too. In it, the relations and the goal can be symbols
(`<=`, `maximize`) rather than strings (`"<="`, `"maximize"`), which
`lp-solve` also accepts:

```lisp
; Minimize 2x1 + 3x2 subject to x1 + x2 = 10 and x1 <= 6.
(lp-solve '(("objective" 2 3)
            ("constraints" (1 1) (1 0))
            ("relations" = <=)
            ("rhs" 10 6)))     ; => (("solution" 6.0 4.0) ("optimal-value" . 24.0))

; Maximize 3x1 + 5x2 subject to x1 <= 4, 2x2 <= 12, and 3x1 + 2x2 <= 18.
(lp-solve '(("objective" 3 5)
            ("constraints" (1 0) (0 2) (3 2))
            ("relations" <= <= <=)
            ("rhs" 4 12 18)
            ("goal" maximize)))  ; => (("solution" 2.0 6.0) ("optimal-value" . 36.0))
```

To print each value beside its variable's name, go through the two lists
together. For the problem read from the first file above:

```lisp
(define result (lp-solve problem))
(do ((names (cdr (assoc "variables" problem)) (cdr names))
     (values (cdr (assoc "solution" result)) (cdr values)))
    ((null? names))
  (display (format "{:<4}{:>8.2f}\n" (car names) (car values))))
```

prints

```
x1      2.00
x2      6.00
```

**The iteration limit.** The solver works in steps (pivots). Give
`max-iterations`, a whole number of at least 1, to stop it after that many
steps; if it isn't done by then, it's an error. If you don't, the limit
is **three times the number of variables the solver works with**. That's the
problem's own variables, plus the ones the solver adds: a slack variable
for each `<=` constraint, a surplus variable and an artificial variable for
each `>=` constraint, and an artificial variable for each `=` constraint.
A problem with 4 variables and 3 `<=` constraints has 7, so the limit is
21. Ordinary problems finish in far fewer steps than that.

It's an error, with a message saying why, if:

- the problem has no solution: "Problem is infeasible" (the constraints
  contradict each other), or "Problem is unbounded" (the objective can
  go down forever, or up forever if maximizing);
- the solver doesn't finish within the iteration limit ("did not
  converge within 21 iterations", say). This can also happen, though
  rarely, when a problem makes the solver go around in a circle, which
  no limit would cure;
- the problem is malformed: a missing part, a constraint with the wrong
  number of coefficients, a count of relations or right-hand sides that
  doesn't match the constraints, a relation other than `<=`, `>=`, or
  `=`, a `"goal"` that isn't `"minimize"` or `"maximize"`, or a
  `"variables"` list that doesn't have one name for each variable.

Two things to know about the answers:

- **Rounding.** They're floats, so a value can come out as, say,
  `5.999999999999999` instead of `6`. Use `format` to show them rounded.
- **Large numbers are fine.** Costs and balances in dollars, even in the
  hundreds of millions, don't need to be scaled down. The solver uses the
  Big-M method, but it keeps M symbolic (as larger than any number)
  rather than choosing a particular big number that real costs could
  exceed. And it decides what counts as zero relative to the size of the
  problem's numbers.

```lisp
; Costs above a million: minimize 5,000,000 x1 subject to x1 >= 1.
(lp-solve '(("objective" 5000000) ("constraints" (1)) ("relations" >=) ("rhs" 1)))
                               ; => (("solution" 1.0) ("optimal-value" . 5000000.0))
```

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
`pairs` is a Lisp list where each element is either a `(name . vector)`
cons, or a 3-element `(name vector decimals)` list to pick a per-column
decimal-places count (rather than the global format, below) — each
becomes one displayed column, headed by `name`, in the order given. In
the GUI, this is the *only* way the "Columns" tab is populated — there's
no automatic scan of top-level variables (the tab uses a fixed-width font
with right-aligned cells, so a column of numbers lines up on its ones
place). In console/batch mode, prints a simple right-justified text table
instead; in Jupyter, a formatted table. Returns `'()`. A table (see
"Tables") is exactly this kind of list, so `(display-columns t)` shows
any table — use `(display-columns (table-head t 20))` for a big one.

```lisp
(define prices (vector 10 20 30))
(define squares (vector-map (lambda (x) (* x x)) prices))
(display-columns (list (cons "prices" prices) (cons "squares" squares)))

(define rate (vector 0.0435 0.041 0.038))
(display-columns (list (list "rate" rate 4) (cons "prices" prices)))  ; mixed forms are fine
```

A `(name . vector)` entry's numeric values are rendered through
`*column-number-format*`, a Lisp-settable global holding a Python
`str.format()` spec — defaults to `"{:,.0f}"` (comma-grouped integers,
e.g. `12,346`). `(set! *column-number-format* "{:,.2f}")` switches to two
decimal places for every subsequent `(name . vector)`-style entry that
doesn't specify its own `decimals`. Non-numeric values (dates, etc.) are
unaffected either way, always rendered plainly.

Deliberately low-level — it doesn't know anything about `defstruct` or any
particular notion of a "column". See `column_engine.lsp` (next to this
file) for a small example library, built on `defstruct` and `&key`, that
registers named `column` structs (each with its own `decimals` slot —
e.g. `0` for a dollar amount, `4`-`6` for an interest rate/CPR/SMM
column), calculates them row-by-row in dependency order, and calls
`display-columns` for you — demonstrated end-to-end in
`mortgage_amortization_example.lsp`. Inside a column's formula,
`(lag NAME n [default])` is column `NAME`'s value `n` rows back; for a row
before the first one (or past the last, with a negative `n`), it's
`default` — or an error saying so, if no default was given. For example,
`(lag balance 1 original_balance)` reads the previous row's balance, and
the original balance on the first row.

#### `(display-markdown string)`
Shows `string` as Markdown. In a Jupyter notebook (the `morris_lisp`
kernel) it renders as real Markdown — tables, headings, bold — so a cell
can build a Markdown table with `string-append` and display it neatly.
Anywhere else (console, GUI, `redirect-output`) the raw Markdown text is
written as ordinary output, which is still readable. Returns `'()`.

```lisp
(display-markdown
  (string-append "| name | value |\n"
                 "|---|---|\n"
                 "| a | 1 |\n"
                 "| b | 2 |\n"))
```

#### `(write-columns-csv filename pairs)`
Same `pairs` shape as `display-columns` (see above) — writes a CSV file
instead: header row = names, one data row per index, numbers rounded to
`decimals` when given (plain numeric CSV cells — `12346`, not `"12,346"`
— since this is for a spreadsheet or another program, not for on-screen
reading; a `decimals` of `0` writes a plain integer, not `12346.0`). A
missing value (`nan` or `'()`) is written as an empty cell, and a column
shorter than the longest one is padded with empty cells. Any table can be
written this way, and `load-csv` reads the file back into the same table.
Returns `'()`. `column_engine.lsp`'s `write-csv` wraps this for a list of column
structs directly — see that function and `mortgage_amortization_example.
lsp`'s `(write-csv "mortgage_amortization_example.csv" *columns*)` call.

```lisp
(write-columns-csv "out.csv" (list (list "rate" rate 4) (cons "prices" prices)))
```

### FRED (Federal Reserve Bank of St. Louis) data, and CSV loading

#### `(fred-series series-id [api-key] [start-date] [end-date])`
Fetches one FRED economic data series and returns `(dates-vector .
values-vector)` — a dotted pair (built with `cons`, not a 2-element list;
`(cdr result)` is the values vector directly, no extra `car` needed) —
parallel, row-aligned vectors of dates and numbers. Observations FRED
marks as missing are silently skipped, so both vectors stay the same
length.

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
(define gdp-values (cdr gdp))          ; NOT (car (cdr gdp)) -- (cdr gdp) IS
                                        ; the values vector already; fred-series
                                        ; returns a cons pair, not a 2-element list
(define gdp-n (vector-length gdp-values))   ; vector-length, not length -- these
                                             ; are vectors, not Lisp lists
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
(In `lisp_csv.py`.) Reads a CSV file into a table (see "Tables") — a list
of `(name . vector)` columns, the same shape `sqlite-query` returns. Every
column and every row is kept. Each column becomes:

- a vector of **numbers**, if every non-blank value is a number (integers
  if they all are); a blank is `nan`;
- a vector of **dates**, if every non-blank value is a date written
  `YYYY-MM-DD` or `MM/DD/YYYY` (the American order US government data
  uses); a blank is `'()`;
- otherwise a vector of **strings**; a blank is `'()`.

`has-header?` (default `#t`): if true, the first row names the columns;
with `#f`, they're named `Column1`, `Column2`, .... A row with more values
than there are columns is an error; a row with fewer is padded with blanks.

```lisp
(define pools (load-csv "synthetic_mbs_pools.csv"))
(table-column-names pools)
(define cpr (table-column pools "cpr"))
(define incentive (table-column pools "rate_incentive_pct"))
(plot-xy incentive (list cpr))

(define d2 (load-csv "no_header.csv" #f))   ; no header row -> Column1, Column2, ...
```

To write a table to a CSV file, see `write-columns-csv` under "Columns".

### Downloading data from the web

(In `lisp_http.py`.) These reach any web API that returns JSON, CSV, or
plain text — the New York Fed's SOFR history, the Treasury's yield curves,
the BLS, and so on — without writing any Python.

**Caching.** Each takes an optional `cache-hours`. Given a number of hours,
the download is saved on disk, and asking for the same URL again within
that many hours reads the saved copy instead of the network: reruns are
fast, you stay under the API's rate limits, and a notebook gives the same
answer twice. Without `cache-hours` (or with 0), every call downloads.
Saved copies go in `~/.cache/morris_lisp/http`, or the directory named by
the `LISP_HTTP_CACHE` environment variable.

**Headers.** Each also takes an optional `headers`: a list of
`(name . value)` pairs to send with the request, for an API that wants a
key in a header.

A failed download — a bad URL, no network, or an error status from the
server — raises a `LispError` giving the URL and the server's reason.

#### `(http-get-json url [cache-hours headers])`
The JSON at `url`, as Lisp data: a JSON object becomes a hash table with
string keys (read it with `hash-table-ref`), an array becomes a list,
`true`/`false` become `#t`/`#f`, and `null` becomes `'()`.

```lisp
; The latest three SOFR fixings, from the New York Fed (no API key needed):
(define reply (http-get-json "https://markets.newyorkfed.org/api/rates/secured/sofr/last/3.json" 12))
(define fixings (hash-table-ref reply "refRates"))
(map (lambda (f) (list (hash-table-ref f "effectiveDate") (hash-table-ref f "percentRate")))
     fixings)
; e.g. (("2026-09-23" 3.87) ("2026-09-22" 3.87) ("2026-09-21" 3.85))
```

#### `(http-get-csv url [has-header? cache-hours headers])`
The CSV file at `url`, as a table, read exactly as `load-csv` reads a file.

```lisp
; The Treasury's daily par yield curve for 2026 (dates are MM/DD/YYYY, read as dates):
(define ust (http-get-csv (string-append
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value=2026&page&_format=csv")
              #t 12))
(define ten-year (cons (table-column ust "Date") (table-column ust "10 Yr")))
(series-monthly ten-year)        ; monthly averages of the 10-year yield
```

#### `(http-get-text url [cache-hours headers])`
The page at `url`, as a string.

#### `(http-url base parameters)`
`base` with a query string built from `parameters` — a list of
`(name . value)` pairs, or a hash table. The values are encoded properly,
so spaces and symbols in them are safe.

```lisp
(http-url "https://x.org/data" (list (cons "series" "DGS10") (cons "limit" 5)))   ; => "https://x.org/data?series=DGS10&limit=5"
(http-url "https://x.org/data" (list (cons "q" "a b&c")))    ; => "https://x.org/data?q=a+b%26c"
```

#### `(http-clear-cache)`
Deletes every saved download, and returns how many there were.

### SQLite

(In `lisp_sqlite.py`.) Builtins for reading and writing a local SQLite
database file, built on Python's standard-library `sqlite3` module. There
are two ways to get a query's results, matching two different needs:

- `sqlite-query` runs a statement to completion and hands back the WHOLE
  result set at once as a table (see "Tables") — a list of
  `(name . vector)` columns.
- `sqlite-execute` + `sqlite-fetch-row` run a statement and then step
  through it one row at a time, for a result set you'd rather not
  materialize all at once, or want to process row-by-row in a loop.

`sqlite-write-table` goes the other way, saving a table as a SQLite table.

Both accept an optional trailing `params` argument — a Lisp list of values
bound, in order, to `?` placeholders in the SQL text, via SQLite's own
native parameter binding (not string-building), which is what makes this
safe against SQL injection no matter what a value contains. Writing the
placeholders and the query text that will fill them by hand is easy to get
out of sync on a query with more than a couple of parameters; `template.lsp`
(next to this file) is a small templating engine built to generate both
together instead — write `{{name}}` right where a value belongs (e.g.
`"...WHERE state = {{state}}"`), and `template-render-sql` produces the
`"?"`-ified SQL text and the matching params list as one pair; `{{name}}` is
ALWAYS a bound parameter there, never text spliced into the query, so it
can't be used to build an unsafe query even by accident. `template.lsp` is
also a general-purpose text templating engine on its own (variable
substitution, with format specs as `format` takes them, `{{#each}}`
loops, `{{#if}}` conditionals) — see its own
header comment for the full syntax and worked examples, and
`sqlite-query-template`/`sqlite-execute-template` (also there) for running
a template against a connection in one call.

#### `(sqlite-open "path/to/db.sqlite")`
Opens (creating it first if it doesn't already exist, same as Python's
`sqlite3.connect`) a SQLite database file and returns a connection value —
pass it to `sqlite-query`, `sqlite-execute`, and `sqlite-close`. Raises
`LispError` if the file can't be opened as a SQLite database.

#### `(sqlite-close conn)`
Closes a connection opened by `sqlite-open`. Returns `'()`.

Rather than calling `sqlite-open` and `sqlite-close` yourself, you can use
`(with-sqlite (conn "path/to/db.sqlite") body...)` (see "Standard
macros"). It opens the database, runs the body, and closes the connection
even if the body stops with an error:

```lisp
(with-sqlite (conn "loans.db")
  (sqlite-query conn "SELECT * FROM pools WHERE state = ?" '() '() (list "CA")))
```

#### `(sqlite-query conn "SELECT ..." [dtypes max-rows params])`
Runs a SQL statement and returns its ENTIRE result set at once, column-wise:
a table — a Lisp list of `(name . vector)` columns, one per output
column, in query order, named as the query names them. Each column is read
the way `load-csv` reads a CSV column: if every value that isn't `NULL` is
a number, the column is a vector of numbers with `nan` for `NULL`; if
every one is text in the form `YYYY-MM-DD`, it's a vector of dates (SQLite
has no date type, so that's how `sqlite-write-table` stores dates);
otherwise the values come back as they are, with `NULL` as `'()`. Raises
`LispError` on a SQL error (bad syntax, unknown column/table, etc) or if
`conn` isn't a value from `sqlite-open`.

```lisp
(define conn (sqlite-open "donors.db"))
(define cols (sqlite-query conn "SELECT name, amount FROM donors ORDER BY amount DESC"))
(display-columns cols)                     ; straight into the Columns tab / console table
(write-columns-csv "donors.csv" cols)      ; or straight out to a CSV file
(sqlite-close conn)
```

**`dtypes` and `max-rows`** — two optional arguments for a *huge* result
(tens of millions of rows), where the ordinary path above — grow a plain
Python list per column as rows stream in, then have each column's vector
figure out its own dtype by scanning every value — means briefly holding
the whole result twice over (once as a list of individually-boxed values,
once as the final packed vector) and spending real time on that scan.

`dtypes`: a string with exactly one character per output column, in query
order — `"B"`/`"I"`/`"F"` (case-insensitive) for Boolean/Integer/Float,
forcing that column straight to a vector of
`LispVector.BOOL_INT_DTYPE`/`INT_DTYPE`/`FLOAT_DTYPE` (see "Vectors",
above) instead of inferring it from the data. Any other character —
conventionally `.` — leaves that one column un-hinted, inferred the normal
way, so a `dtypes` string only needs real letters over a query's numeric
columns; a text column, say, can be left un-hinted in an otherwise-hinted
query. **Hints are trusted, not verified against the data**: a value the
hinted dtype genuinely can't hold — a `NULL` in a `B`/`I` column (there's
no integer NaN), a string, a number too big for the dtype — raises a
`LispError` naming the row and column it happened at, but a value that
merely doesn't *match* — e.g. a fractional number arriving in an `"I"`
column — is silently truncated exactly the way an unchecked `vector-set!`
would be (see "Vectors" for the general dtype-widening machinery this
bypasses on purpose, for speed). A `NULL` in an `"F"` column becomes `NaN`
instead of erroring, matching numpy/pandas' own convention for a missing
float — no special handling needed for that case specifically.

`max-rows`: an upper bound on how many rows the query will return. Given
*together with* `dtypes`, every hinted column's vector is allocated once,
up front, at this size, and each row's values are written directly into it
as they stream from the cursor — no intermediate Python list for that
column at all, and no separate dtype-scanning pass afterward (an un-hinted
column, if any, still collects into a plain list either way, since its
eventual dtype isn't known until every value's been seen). If the query
actually returns *more* than `max-rows` rows, that's a `LispError` — raise
the bound, or drop `max-rows` to fall back to an ordinary, unbounded
collection — rather than silently reallocating past the bound you gave, or
silently dropping rows.

Measured on a 3-column, 2,000,000-row table: `dtypes` alone cuts query time
by about 4x (skipping the per-value wrapping and the dtype-inference scan);
adding `max-rows` on top cuts peak memory by roughly 45% further (skipping
the intermediate Python list entirely, for hinted columns).

```lisp
(define big (sqlite-query conn "SELECT id, balance, delinquent FROM loans"
                           "IFB" 10000000))    ; up to 10M rows expected
```

**`params`** (last argument, so existing 2/3/4-argument calls keep working
unchanged): a Lisp list of values bound, in order, to `?` placeholders in
`sql`, via SQLite's own parameter binding — the value is sent to SQLite
separately from the SQL text, so it's never interpreted as SQL syntax no
matter what it contains, which is what actually prevents SQL injection (as
opposed to splicing a value into the query string, safely or not). See
"SQLite", above, for `template.lsp`, a small templating engine for
generating the `"?"`-placeholder text and this params list together instead
of writing both by hand and keeping them in sync yourself.

```lisp
(sqlite-query conn "SELECT * FROM loans WHERE state = ? AND balance > ?"
              '() '() (list "CA" 100000))
```

#### `(sqlite-write-table conn name table [mode])`
Saves a table (a list of `(name . vector)` columns — see "Tables") as a
SQLite table called `name`, and returns how many rows were written.
`mode` says what to do if a table with that name already exists:

- `'create` (the default) — it's an error, so nothing is overwritten by
  accident;
- `'replace` — drop it and write the new table in its place;
- `'append` — add the rows to it (its columns must have the same names).

Each column gets the SQLite type `INTEGER`, `REAL`, or `TEXT` to match its
vector. Dates are stored as `YYYY-MM-DD` text, which `sqlite-query` reads
back as dates; `nan` and `'()` are stored as `NULL`. All the rows are
written in one transaction — fast, even for millions of rows — and if
anything goes wrong, the database is left unchanged. Table and column
names can contain spaces or other symbols; they're quoted.

```lisp
(define conn (sqlite-open ":memory:"))          ; a database held in memory
(define t (make-table "id" (vector "a" "b") "balance" (vector 100.5 nan)
                      "as_of" (vector (date 2024 1 1) (date 2024 2 1))))
(sqlite-write-table conn "loans" t)              ; => 2
(sqlite-query conn "SELECT * FROM loans")        ; => (("id" . #("a" "b")) ("balance" . #(100.5 nan)) ("as_of" . #(2024-01-01 2024-02-01)))
(sqlite-write-table conn "loans" t 'append)      ; => 2
```

#### `(sqlite-execute conn "SELECT ..." [params])`
Runs a SQL statement and returns a CURSOR immediately, without reading any
rows yet — pass it to `sqlite-fetch-row`, repeatedly, to pull one row at a
time. Also fine for a non-`SELECT` statement (`INSERT`/`UPDATE`/`CREATE
TABLE`/...); `sqlite-fetch-row` on the resulting cursor just returns `'()`
right away, since there's nothing to fetch. `params`: same as
`sqlite-query`'s. Raises `LispError` the same way `sqlite-query` does.

#### `(sqlite-fetch-row cursor)`
Pulls the next row from a cursor returned by `sqlite-execute`, as a Lisp
list of that row's values in column order (same NULL/text/number
conversion as `sqlite-query`), or `'()` once every row has already been
fetched — so a plain `while`/`null?` loop drains a cursor one row at a time:

```lisp
(define conn (sqlite-open "donors.db"))
(sqlite-execute conn "CREATE TABLE IF NOT EXISTS donors (name TEXT, amount REAL)")
(define cur (sqlite-execute conn "SELECT name, amount FROM donors ORDER BY name"))
(define row (sqlite-fetch-row cur))
(while (not (null? row))
  (begin
    (display (car row)) (display ": ") (display (car (cdr row))) (newline)
    (set! row (sqlite-fetch-row cur))))
(sqlite-close conn)
```

`sqlite-connection?` and `sqlite-cursor?` are the matching type predicates,
alongside `date?`/`vector?`/`struct?` and the rest (see "Comparison /
equality / booleans").

### tastytrade (real broker data)

Requires the `tastytrade` package (`pip install tastytrade`) and a
tastytrade account. This is the full data-and-analysis functionality of
the `tasty_api/` desktop app, ported here as plain synchronous builtins
(each one just wraps an internal `asyncio.run(...)` call, the same way
`fred-series` wraps a plain `urllib` call) — no PyQt6 dependency, and
nothing here needs a GUI running.

Four of the seven functions do real network I/O and take
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
behind the scenes). The other three take no `credentials-path` and do no
networking: `tastytrade-products` just returns a hardcoded list of known
product codes, and `tastytrade-curve-fit`/`tastytrade-leg-carry` are pure
analysis functions that operate on data already fetched by
`tastytrade-futures-curve-rows`, so you can fetch a curve once and re-run
either analysis as many times as you like with different rate/threshold
assumptions at no extra cost.

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

```lisp
(tastytrade-products)          ; => ("ES" "MES" "NQ" "MNQ" "YM" "MYM" ... "SR3" ...)
```

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

#### `(sofr-forward-curve curve-rows)`
Pure function — no networking. `curve-rows` is
`(tastytrade-futures-curve-rows creds "SR3" [n-months])` — one row per
listed CME 3-Month SOFR future. Bootstraps a 360-month (30-year) curve of
1-month forward rates implied by those futures prices, reusing
`term_structure/term_structure_model.py`'s `bootstrap_sofr_curve()`
as-is (see that function's docstring for the full methodology and its
documented simplifications — flat extrapolation beyond the last listed
contract, no convexity adjustment, a whole reference quarter treated as
one flat rate). Returns `(cons months-vector forward-rates-vector)`,
1-indexed by month: `(vector-ref forward-rates-vector (- month 1))`.
Needs `term_structure/term_structure_model.py` (next to this repo's
`lisp_interp/`); raises `LispError` if it isn't importable, or if
`curve-rows` is empty.

```lisp
(define curve (sofr-forward-curve (tastytrade-futures-curve-rows creds "SR3" 40)))
(define sofr-months (car curve))
(define sofr-forward-rates (cdr curve))
(plot-xy sofr-months (list sofr-forward-rates))
```

See `sofr_floating_rate_example.lsp` (next to this file) for feeding
`sofr-forward-rates` into `column_engine.lsp` to drive a floating-rate
note's coupon, period by period. `prepayment_model.lsp` (a simple
PSA-style CPR/SMM curve — see that file) is the mortgage-prepayment
counterpart, incorporated into `mortgage_amortization_example.lsp`'s
collateral cashflows; `prepayment_demo.lsp`/`term_structure/
mortgage_spread.py` show a data-fit (rather than textbook-PSA) CPR model
and a way to estimate the SOFR-to-mortgage spread the rate-incentive
input to either kind of model would need.

#### `(sofr-calibration-data credentials-path [n-futures n-underlyings n-strikes])`
Fetches a SOFR futures curve AND a spread of SOFR futures OPTIONS in one
tastytrade session, reusing `term_structure/sofr_market_data.py`'s
`fetch_sofr_calibration_data()` as-is (see that module for the full
selection methodology — options are spread evenly across every curve
quarter with a listed chain, not just the nearest few, so `sigma1`/
`sigma2` below are separately identifiable). A SEPARATE fetch from
`tastytrade-futures-curve-rows` — this one also pulls option chains, not
just futures prices. `n-futures`/`n-underlyings`/`n-strikes` default to
`40`/`10`/`3`.

Returns `(cons curve-futures-rows options-rows)`:
- `curve-futures-rows` — one row per SR3 contract month used for the
  curve: `(symbol start-months end-months rate)`. Feed to
  `sofr-bootstrap-curve`.
- `options-rows` — up to `n-underlyings * n-strikes * 2` near-the-money
  call/put pairs: `(type strike expiry-months quarter-start-months
  quarter-end-months market-price)`. Feed to `sofr-calibrate-model`.

Needs the `tastytrade` package, a tastytrade account, and a credentials
JSON file (see `tasty_api/README.md`).

```lisp
(define data (sofr-calibration-data creds 40 8 3))
(define curve-futures-rows (car data))
(define options-rows (cdr data))
```

#### `(sofr-bootstrap-curve curve-futures-rows)`
Pure function — no networking. Like `sofr-forward-curve`, but takes
`sofr-calibration-data`'s `curve-futures-rows` shape (`(symbol
start-months end-months rate)`) instead of `tastytrade-futures-curve-
rows`'s — no day-count reshaping needed, since these rows already carry
`start-months`/`end-months` directly. Same return shape: `(cons
months-vector forward-rates-vector)`.

```lisp
(define curve (sofr-bootstrap-curve curve-futures-rows))
(define sofr-forward-rates (cdr curve))
```

#### `(sofr-extend-curve-with-treasury forward-rates curve-real-months yield-3m yield-6m yield-1y yield-2y yield-5y yield-10y yield-30y [blend-months])`
Pure function — no networking. Replaces the flat-extrapolated tail of a
curve from `sofr-bootstrap-curve`/`sofr-forward-curve` — past
`curve-real-months`, everything is held at the last real futures rate —
with the SHAPE of a separate curve bootstrapped from Treasury par yields,
linearly blended in over `blend-months` (default `12`) so the splice
doesn't visibly kink. Reuses `term_structure_model.py`'s
`extend_curve_long_end()` (and, internally, `bootstrap_forward_curve()`
for the Treasury side) as-is.

CME only lists roughly a 5-year strip of SR3 contracts, so any SOFR curve
is flat past there; for anything priced off the far end of the curve (a
30-year MBS, say), the free, much longer-dated Treasury par curve on FRED
is a better long-end *shape* than a flat line. This does **not** attempt
a SOFR/Treasury basis adjustment — it borrows the Treasury curve's shape
as-is past `curve-real-months`, a simplification worth being aware of.

- `forward-rates` — the curve to extend, e.g. `sofr-bootstrap-curve`'s or
  `sofr-forward-curve`'s second return value.
- `curve-real-months` — same meaning as `sofr-calibrate-model`'s argument
  of the same name: how many months of `forward-rates` are backed by real
  market data.
- `yield-3m`/`6m`/`1y`/`2y`/`5y`/`10y`/`30y` — today's Treasury par
  yields, as DECIMALS (`0.045`, not `4.5`) — e.g. FRED's
  `DGS3MO`/`DGS6MO`/`DGS1`/`DGS2`/`DGS5`/`DGS10`/`DGS30`, each divided by
  100 (FRED reports those series in percent).
- `blend-months` (default `12`) — width, in months starting at
  `curve-real-months`, of the linear transition zone.

Returns a new forward-rates vector (same length as the input; the input
is not modified).

```lisp
(define extended-forward-rates
  (sofr-extend-curve-with-treasury sofr-forward-rates curve-real-months
                                    0.043 0.041 0.039 0.038 0.040 0.043 0.046))
```

#### `(sofr-calibrate-model forward-rates options-rows curve-real-months [n-paths seed n-grid n-rounds])`
Pure function — no networking (cheap to re-run with different settings
once you've fetched `options-rows` once). Fits the two-factor model's
mean-reversion speed `a` and both volatilities — `sigma1` (the short-rate
factor) and `sigma2` (the slower-moving mean-reversion-*level* factor) —
directly against real SOFR futures option prices, by a "zooming grid
search": try a grid of `(a, sigma1, sigma2)` combinations, keep whichever
prices the options closest, shrink the search window around it, repeat
`n-rounds` times. Reuses `term_structure_model.py`'s
`calibrate_sofr_model()` as-is — see that function's docstring for the
full methodology, including *why* it fits `a` against option prices
directly rather than against today's curve shape (found, on real data, to
meaningfully improve the fit) and how `theta_bar` (the long-run level the
model's second factor drifts toward) gets refit in closed form at every
candidate `a`.

- `forward-rates` — `sofr-forward-curve`'s or `sofr-bootstrap-curve`'s
  second return value.
- `options-rows` — `sofr-calibration-data`'s second return value (or
  anything shaped the same way).
- `curve-real-months` — how many months of `forward-rates` are the REAL
  (non-extrapolated) part of the curve, i.e. the largest `end-months`
  among the `curve-futures-rows` used to build it.
- `n-paths` (default `2000`) — Monte Carlo paths used to price EACH
  option at EACH candidate tried; an accuracy/speed trade-off for the
  *calibration* itself, separate from how many scenario paths
  `sofr-simulate-rate-paths` later generates.
- `seed` (default `42`), `n-grid` (default `7`), `n-rounds` (default
  `4`) — grid resolution per round / how many times to zoom in. Cost is
  roughly `O(n-grid³ × n-rounds × n-paths × number of options)` — the
  `term_structure_model.py` module docstring reports **ten to twenty
  seconds** for its own real-data test at these same defaults and a
  handful of options; turn `n-paths`/`n-grid`/`n-rounds` down for a
  quicker first pass. See `sofr_monte_carlo_example.lsp`.

Returns `(list a theta-bar sigma1 sigma2 error)` — `error` is the total
squared pricing error at the winning parameters.

```lisp
(define fit (sofr-calibrate-model sofr-forward-rates options-rows 24
                                   500 42 5 3))    ; turned down for speed
(define fitted-a (list-ref fit 0))
(define fitted-theta-bar (list-ref fit 1))
(define fitted-sigma1 (list-ref fit 2))
(define fitted-sigma2 (list-ref fit 3))
```

#### `(sofr-simulate-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths [seed a theta-bar])`
Pure function — no networking. Simulates `n-paths` Monte Carlo scenarios
of the two-factor model (a short-rate factor and a slower mean-reversion-
level factor — see `term_structure/term_structure_model.py`'s module
docstring) `horizon-years` forward, reusing that module's
`simulate_rate_paths()` as-is. `seed` defaults to `'()` (a fresh random
seed each call); an integer gives reproducible paths.

Pass `sofr-calibrate-model`'s fitted `a`/`theta-bar` (its first two
return values) for `a`/`theta-bar` when `forward-rates` came from
`sofr-bootstrap-curve`/`sofr-forward-curve` — leaving them `'()` uses
this function's own default (theta-bar as the average of `forward-
rates`' last 2 years), which for a SOFR curve anchors theta-bar at an
arbitrary flat-extrapolated value with no connection to real market data.

Returns `(list years-vector short-rate-paths ten-year-paths)`:
- `years-vector` — times in years: `0, 1/12, 2/12, ..., horizon-years`.
- `short-rate-paths` / `ten-year-paths` — each a Lisp LIST of
  `(horizon-years×12 + 1)`-element vectors, one per path. `ten-year-
  paths[i]` is path `i`'s approximate ten-year rate, a closed-form
  function of that path's state at each month, not a separately-
  simulated factor.

```lisp
(define sim (sofr-simulate-rate-paths sofr-forward-rates 0.005 0.01 5.0 20 42))
(define years (list-ref sim 0))
(define short-rate-paths (list-ref sim 1))
(plot-xy years short-rate-paths)   ; y-list already IS a list of vectors
```

#### `(sofr-simulate-mortgage-rate-paths forward-rates sigma1 sigma2 horizon-years n-paths mortgage-spread [seed a theta-bar tenor-years])`
Pure function — no networking. The same simulation as
`sofr-simulate-rate-paths`, plus a simple proxy mortgage rate per
path/month: `mortgage_rate = tenor-years-rate + mortgage-spread`
(`tenor-years` defaults to `10`, the usual rate-sensitivity proxy for a
30-year mortgage). Reuses `simulate_mortgage_rate_paths()` as-is.

**SIMPLIFICATION** (from the underlying model, not this bridge): a real
mortgage rate tracks current-coupon MBS yields — the whole curve,
prepayment risk, origination costs — not one flat spread over one tenor
point; `mortgage-spread` is a deliberate simplification, named so it's
obvious where to plug in something richer (`term_structure/
mortgage_spread.py`'s `fetch_current_mortgage_rate()` pulls FRED's
`MORTGAGE30US` for one way to estimate it from real data instead of
guessing).

Returns `(list years-vector short-rate-paths underlying-paths
mortgage-paths)` — `underlying-paths` is the `tenor-years` rate before
adding the spread; `mortgage-paths` is after.

**Example**: `sofr_monte_carlo_example.lsp` (next to this file) runs the
full pipeline end to end — `sofr-calibration-data` →
`sofr-bootstrap-curve` → `sofr-calibrate-model` →
`sofr-simulate-mortgage-rate-paths` — then charts a few paths and writes
all of them to CSV via `write-columns-csv` (see "Columns", above). Its
header comment sketches feeding one simulated path into
`mortgage_amortization_example.lsp` in place of the deterministic
SOFR-forward-curve-derived rate, for a single Monte Carlo scenario's
cashflows (looping over several paths, each with its own
`column_engine.lsp` registry, is the natural next step toward a full
Monte Carlo distribution of cashflows — not built out there).

That "loop over several paths" step is exactly what
[`oas_monte_carlo.lsp`](oas_monte_carlo.lsp) does, deliberately WITHOUT
`column_engine.lsp` (its per-row registry/topological-sort machinery is
built for readability on a single calculated table, not for generating
hundreds-to-thousands of per-path cashflow vectors fast). It adds:

- `annualized-realized-vol` — a historical-data cross-check for
  `sofr-calibrate-model`'s fitted `sigma1`/`sigma2` (or a quick sanity
  check with no options data at all), from a plain rate-level vector —
  see its docstring for a worked `fred-series "DFF"`/`"DGS10"` example.
- `simple-mortgage-cashflows` / `mortgage-cashflows-per-path` — a fast,
  direct (not `column_engine.lsp`-based) fixed-rate, PSA-prepaying
  pass-through cashflow generator, reusing `prepayment_model.lsp`'s
  `cpr`/`smm-from-cpr`, either for one path or for every path in a
  `sofr-simulate-mortgage-rate-paths` result at once.
- `path-present-value` / `oas-model-price` / `oas-solve` — the
  Option-Adjusted Spread engine itself: discounts a cashflow stream along
  one Monte Carlo path using that path's own simulated short rate plus a
  trial spread (the SAME discounting convention `term_structure_model.py`'s
  `price_callable_bond_mc()` uses), averages across paths for a model
  price, then bisects for whichever spread reproduces a target market
  price — the "solve for OAS" direction that function's own docstring
  flags as unimplemented. Works for a single shared cashflow vector (an
  ordinary bond) or a per-path list of cashflow vectors (a prepaying
  mortgage, whose cashflows are path-dependent).

See [`oas_monte_carlo_example.lsp`](oas_monte_carlo_example.lsp) for the
full pipeline end to end — curve extension → (illustrated) historical-vol
cross-check → `sofr-simulate-mortgage-rate-paths` →
`mortgage-cashflows-per-path` → `oas-solve` — runnable with no network
access or credentials (its curve/volatility/market-price numbers are all
illustrative, in the same spirit as `term_structure_model.py`'s own
`__main__` demo).

[`oas_monte_carlo_live_example.lsp`](oas_monte_carlo_live_example.lsp) is
the same pipeline against REAL data instead: the SOFR futures curve and
calibration options from tastytrade (`sofr-calibration-data`), the
Treasury par curve and the DFF/DGS10 historical-vol cross-check from
`fred-series`, and the mortgage note rate from FRED's `MORTGAGE30US` —
only the security's own market price has no live source wired up
anywhere in this codebase, so that one number stays an assumption.
Writes `oas_monte_carlo_live_report.txt` (and prints the same report to
the console) listing every fetched data point and every assumption the
run used, split into separate sections so it's clear which is which.
Needs a credentials file with both tastytrade fields and a
`"fred_api_key"` entry (`creds` in `init.lsp`).

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

```lisp
(display "hello") (newline) (display 42)
```
prints:
```
hello
42
```

A string inside a list or vector is shown the way you'd type it: in
quotes, with a backslash before any quote mark or backslash in it. The
REPL shows a result the same way. Newlines and tabs inside a string are
shown as they are.

```lisp
(display (list "CA" "say \"hi\""))
```
prints:
```
("CA" "say \"hi\"")
```

#### `(newline)`
Writes a single newline to the current output. Returns `'()`.

```lisp
(display "a") (newline) (display "b")   ; prints a, then a newline, then b
```

#### `(print x)`
Like `display`, but with a trailing newline.

```lisp
(print "one line")
(print "another")
```
prints:
```
one line
another
```

#### `(load "path.lsp")`
Reads and evaluates every top-level form in the file at `path`, in the
**same** (calling) global environment, so its `define`s/`defmacro`s become
available afterward exactly as if you'd typed them yourself. Returns
`'()`. This is the same mechanism the interpreter uses at startup to
auto-load `macros_init.lsp` and `init.lsp`.

```lisp
(load "column_engine.lsp")     ; defstruct column, register-column, ... now defined
```

#### `(redirect-output "path.txt" [append?])`
Retargets everything `display`/`newline`/`print` write (and the console/
no-GUI default chart-summary text) from the console/GUI log to the given
file, until `reset-output` switches back. Opens in overwrite mode by
default; pass `#t` for `append?` to append instead. If a prior
`redirect-output` is still active, its file is closed first (redirecting
twice in a row doesn't leak a file handle). Flushes after every write, so
output survives even if the script errors out before `reset-output`.

```lisp
(redirect-output "run.log")
(display "this goes to run.log, not the console")
(reset-output)
(display "back to the console")
```

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
Returns a new symbol that can't collide with any other name in the
program. The standard tool for avoiding accidental variable capture when
hand-writing a macro — see "Macros", above, for what goes wrong without it
(the old `while`) and how `while` uses it now. Used internally by
`dolist`'s own desugaring for the same reason.

It prints as `%prefix-N`, where `N` counts up (`prefix` defaults to
`"g"`), so different ones are easy to tell apart. But the name is only for
printing. As in Common Lisp, a gensym is an *uninterned* symbol: it's
equal only to itself. An ordinary symbol with the same name, whether you
typed it or made it with `string->symbol`, is a different symbol. So
even code that happens to use the name `%g-1` can't collide with it.

```lisp
(gensym)                        ; => %g-1  (an incrementing counter)
(gensym "tmp")                  ; => %tmp-2
(define g (gensym))
(eq? g g)                                          ; => #t
(eq? g (string->symbol (symbol->string g)))        ; => #f  (same name, different symbol)
```

If you copy a macro expansion from `macroexpand-1` and paste it into your
program, the pasted names are ordinary symbols, but every copy of each
name is the same symbol, so the pasted code still works.

#### `(load "path.lsp")`
See "Input / output", above — documented once there.

#### `(error message arg...)`
Raises `LispError` with a message built by rendering each argument the way
`display` would and joining them with spaces (so `(error "bad value:" x)`
reads naturally). For signaling a problem from your own Lisp code — e.g. a
library like `column_engine.lsp` reporting a circular dependency.

```lisp
(error "bad value:" 42)        ; raises LispError: bad value: 42
```

#### `(catch-error protected-expr (var) handler-body...)`
See "Special forms", above — documented once there (it's a special form,
not a function: `protected-expr` must NOT be evaluated eagerly, since the
whole point is to catch what happens when it's evaluated).

#### `(throw tag [value])`, `(catch tag body...)`, `(unwind-protect protected-expr cleanup-expr...)`
See "Special forms", above. `throw` jumps out to the matching `catch`;
`unwind-protect` makes sure cleanup code runs.

#### `(assert test [message...])`
See "Standard macros", above.

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
and doesn't remember your original whitespace/formatting. Raises
`LispError` if `name` isn't a user-defined function.

```lisp
(define (square n) (* n n))
(pretty-print-function square)
```
prints:
```
(define
 (square
  n
 )
 (*
  n
  n
 )
)
```

#### `(pretty-print-macro name)`
Same idea as `pretty-print-function`, but for a macro, reconstructing
`(defmacro name (params...) body...)`. Raises `LispError` if `name` isn't
a macro.

```lisp
(defmacro double-it (x) `(* 2 ,x))
(pretty-print-macro double-it)
```

#### `(macroexpand-1 'form)`, `(macroexpand 'form)`
Shows what a macro CALL turns into, without evaluating (or running any side
effect of) either the call or its expansion — the complement to
`pretty-print-macro`, which shows a macro's *definition* rather than one
particular *use* of it. `form` must be quoted (or otherwise already a piece
of Lisp data) yourself — like `eval`, neither function auto-quotes its
argument. `macroexpand-1` expands the outermost form exactly one level;
`macroexpand` keeps re-expanding the outermost form as long as it's still a
macro call (so a macro that itself expands into a call to another macro is
fully unwound in one step). Neither expands macro calls nested *inside* the
result — only the outermost form. Returns `form` unchanged if it isn't a
macro call at all.

```lisp
(defmacro my-unless (test then) `(if (not ,test) ,then '()))
(macroexpand-1 '(my-unless (> 1 2) 'shown))
                                ; => (if (not (> 1 2)) (quote shown) (quote ()))
```

See "why gensym is needed" in the Macros section, above, for a worked
example of using `macroexpand-1` to see exactly which name a
non-hygienic macro leaks into its expansion.

#### `(print-macroexpansion 'form)`
`(macroexpand form)`, pretty-printed (via `pretty-print`) instead of
returned as a value — the quickest way to actually look at a nested
expansion at a glance, rather than parsing a `to_string`-formatted result
back into your own head.

```lisp
(print-macroexpansion '(while (< i 10) (display i)))
```

#### `(defined-functions)`
Returns a list of every name currently bound, at the top level, to a
user-defined function (something made with `lambda`/`define` — not a
built-in), in the order each was first defined. There's no separate
registry to keep in sync — this just filters the live environment each
time it's called, so it's always exactly correct, including brand-new
definitions, automatically.

```lisp
(define (square n) (* n n))
(defined-functions)            ; => (square ...plus anything else you've defined)
```

#### `(defined-macros)`
The same idea, for user-defined macros — excludes this interpreter's own
`pretty-print-function`/`pretty-print-macro`/`debug-function`/
`undebug-function` convenience macros. It does include the standard
macros (`while`, `do`, `case`, and the others in "Standard macros"; they're
written in Lisp, in `macros_init.lsp`), and any macros from `init.lsp`.

```lisp
(defmacro double-it (x) `(* 2 ,x))
(defined-macros)               ; => (while do assert with-sqlite when unless case double-it)
```

#### `(bound-variables)`
Returns a list of every top-level name bound to a plain *value* rather
than a function, macro, or built-in procedure — i.e. ordinary `define`d
data: numbers, strings, lists, vectors, dates, and so on.

```lisp
(define pi 3.14159)
(bound-variables)              ; => (pi ...plus anything else you've define'd as data)
```

#### `(breakpoint [message])`
A special form: see "Special forms", above. It stops the program right where
it's written; see "Debugging", below, for what a stop does.

### Debugging

A running program can be **stopped**, to look at its variables, change
them, and see how it got there. There are three ways to stop it:

- **`(breakpoint)`**, written in your code, stops right where it is.
- **`(break f)`** stops each time the procedure `f` is called, without
  touching `f`'s code.
- **`(break-on-error #t)`** stops where an error happens, while the calls
  it's about to leave are still there to look at.

**What a stop does.** If no debug hook is registered, the **debug REPL**
opens. If one is (see `set-debug-hook!`), the hook is called instead, and
*it* decides: it can print something, look around with `(locals)`, and then
call `(debug-repl)` to open the debug REPL, call `(abort)` to give up, or
just return, and the program carries on. A hook needs no console, so hooks
work in scripts, in Jupyter, and in the GUI.

**The debug REPL** is a prompt, opened in the middle of the program. What
you type is evaluated in the scope where the program stopped: for a
procedure that's stopped by `break`, the scope where its parameters are
bound to the arguments of this call, so you can look at them and change
them with `set!`. These commands are also there:

| Type | What happens |
|---|---|
| `(continue)`, `(exit)`, or Ctrl-D | The program resumes. (At a stop for an error, that lets the error go on its way.) |
| `(abort)` | The whole computation is abandoned, back to the top level. |
| `(locals)` | The variables you can see, with their values. |
| `(backtrace)` | The chain of calls that led here (see "Verbose mode and stack traces"). |
| anything else | Evaluated, and the result printed (cut off after 2,000 characters, so a big vector doesn't flood the console). An error is reported, and you stay at the prompt. |

A session at the console:

```
lisp> (define (payment balance rate) (* balance (/ rate 12)))
payment
lisp> (break payment)
payment
lisp> (payment 1000 0.06)
--- break: entering payment(1000, 0.06) ---
--- payment: debug REPL -- (continue) resumes, (abort) abandons the computation, (locals) shows the variables ---
payment> (locals)
((balance . 1000) (rate . 0.06))
payment> (set! rate 0.12)
()
payment> (continue)
--- payment: resuming ---
10.0
```

The rate was changed from 0.06 to 0.12 at the stop, so the result is 10.0,
not 5.0. Calling a `break`-ed procedure from the debug REPL stops again,
one level deeper; `(continue)` returns to the stop above, and `(abort)`
ends them all.

`debugging_example.lsp` is a worked example that uses a hook, so it needs no
console: it logs calls, stops on a condition, and looks at the variables
where an error happened. Run it from `lisp_interp/`:

```bash
python3 lisp_interpreter.py debugging_example.lsp
```

#### `(break procedure-or-name [condition])`
Sets a breakpoint: from now on, the program stops each time a procedure
with this name is called, after its parameters are bound to the arguments
and before its body runs. Give the procedure itself or its name, as a
symbol or a string. `(break f)` and `(break 'f)` do the same thing, because
`(break f)` gets the procedure `f` and uses its name. Returns the name.

```lisp
(define (payment balance rate) (* balance (/ rate 12)))
(break payment)                    ; => payment
(break 'payment)                   ; => payment  (the same breakpoint)
(breakpoints)                      ; => ((payment))
```

- **It goes on the name.** Every procedure called `payment` stops,
  including one you define later, a local one, and a new definition that
  replaces the old one. Every call stops: recursive calls, tail calls, and
  calls made by `map` and other functions that take a procedure. If the name
  isn't a global function yet, `break` says so in a note, and the breakpoint
  is set anyway.
- **A condition.** The optional second argument is an expression, evaluated
  in the procedure's scope, so it can use the parameters by name. The program
  stops only when it's true. It's quoted, because `break` is a function and
  the expression is to be evaluated later, at each call. An error in the
  condition is an error of the program.

```lisp
(define (payment balance rate) (* balance (/ rate 12)))
(break payment)
(break payment '(> balance 5000))  ; => payment  (only for big loans; this replaces the old breakpoint)
(breakpoints)                      ; => ((payment (> balance 5000)))
```

- **Not for everything.** Only functions you define can have breakpoints:
  `(break car)` and a macro are errors, and so is a procedure with no name
  (a `lambda` that was never `define`d).
- **The stop** prints `--- break: entering payment(1000, 0.06) ---` and opens
  the debug REPL, or, if there's a hook, calls it with the kind `break`.

#### `(unbreak [procedure-or-name])`
Removes the breakpoint on a procedure. `(unbreak)` with no argument removes
every breakpoint. Removing one that isn't there does nothing. Returns `'()`.

```lisp
(define (payment balance rate) (* balance (/ rate 12)))
(break payment)
(unbreak payment)
(breakpoints)                      ; => ()
```

#### `(breakpoints)`
The breakpoints that are set, as a list with one entry for each: `(name)`,
or `(name condition)` if it has a condition. It has the same shape as the
`break` call that made it.

```lisp
(define (f x) x)
(define (g x) x)
(break f)
(break g '(> x 5))
(breakpoints)                      ; => ((f) (g (> x 5)))
```

#### `(set-debug-hook! procedure)`, `(debug-hook)`
`(set-debug-hook! procedure)` registers a **debug hook**: a procedure that's
called at every stop, in place of opening the debug REPL. It takes three
arguments:

| Argument | For `break` | For `breakpoint` | For `error` |
|---|---|---|---|
| `kind` | the symbol `break` | `breakpoint` | `error` |
| `name` | the procedure's name | the message given to `(breakpoint message)`, or `'()` | the error message, as a string |
| `args` | the list of the arguments | `'()` | `'()` |

`kind` is a symbol, so compare it with `eq?`: `(eq? kind 'error)`. The
hook's return value is ignored. What it does decides what happens next:

- **Just return** (after printing or counting something, say), and the
  program carries on. A hook that only prints is a way to trace particular
  procedures with your own output.
- **`(debug-repl)`** opens the debug REPL, at this stop.
- **`(abort)`** abandons the computation. **`(throw tag value)`** leaves it
  for a `catch` you wrote, so the program can recover.
- Inside the hook, **`(locals)`** gives the variables where the program
  stopped, and `(backtrace)` shows the calls that led there.

`(set-debug-hook! '())` removes the hook. `set-debug-hook!` returns the hook
that was there before (or `'()`), so you can put it back, and `(debug-hook)`
returns the current one. Something that isn't a procedure is an error.

```lisp
(define (payment balance rate) (* balance (/ rate 12)))
(define log '())
(define (note kind name args)
  (set! log (cons (list kind name args) log)))
(set-debug-hook! note)
(break payment)
(payment 1000 0.06)                ; => 5.0  (the hook returned, so the program went on)
log                                ; => ((break payment (1000 0.06)))
```

A hook that decides whether to open the debug REPL, here only for a large
loan:

```
(set-debug-hook!
  (lambda (kind name args)
    (display (format "called {} {}\n" name args))
    (if (> (car args) 5000)
        (debug-repl))))
```

Two more things to know. **Calls the hook itself makes never stop**, so a
hook can call a procedure that has a breakpoint without setting off
itself; the debug REPL is different, because you may want to stop there.
And **an error in the hook is an error of the program**, reported like any
other.

A hook that does nothing, `(set-debug-hook! (lambda (kind name args) '()))`,
silences every breakpoint, `(breakpoint)` forms included, without editing
any code.

#### `(debug-repl)`
Opens the debug REPL at the stop the program is at. It's for a debug hook:
when there's no hook, this is what a stop does anyway. Outside a stop it's an
error (to stop in your own code, write `(breakpoint)`). Returns `'()` when
the REPL is left with `(continue)`.

#### `(abort)`
Abandons the whole computation, and goes back to the top level, from the
debug REPL or from a hook (or anywhere else). What "the top level" is
depends on where you're running:

| Where | What `(abort)` does |
|---|---|
| The console REPL | Prints `Aborted -- back at the top level.` and gives you the next prompt. |
| A script | Ends the run, printing `Aborted.` on stderr, with exit status 1. (There's nothing to go back to, and going on with a computation whose result is missing would only produce more errors.) |
| The GUI | Writes `Aborted.` in the log; the window carries on. |
| Jupyter | The cell ends with an `Aborted` error. |

`catch-error` doesn't catch an abort, because it isn't an error, and
`unwind-protect` cleanups run on the way out, so a connection that
`with-sqlite` opened is still closed.

#### `(locals)`
The variables visible where the program is stopped, as an association list
of `(name . value)`, innermost scope first: for a procedure, its parameters
and internal definitions, then those of any procedures it's inside. Global
variables are left out, and so are the hidden `%` names the interpreter
makes for itself (for `dolist`, say). If a name is in two scopes, only the
innermost is shown. Use it in the debug REPL or in a hook; anywhere else it's
an error, because the program isn't stopped.

```
payment> (locals)
((balance . 1000) (rate . 0.06))
```

Values are returned as they are, so a hook that prints `(locals)` can print a
lot when a variable holds a big vector.

#### `(break-on-error [flag])`
`(break-on-error #t)` makes the program stop where an error happens, while
the calls it's about to leave are still in progress, so you can look at the
variables in the failing scope. `(break-on-error #f)` turns it off, and it's
off to begin with. `(break-on-error)` says which it is now. Setting it returns
the previous setting.

The stop has the kind `error`, and prints `--- error: car: not a pair: 5 ---`
before the debug REPL opens (or calls the hook, with the message as `name`).
The REPL says `(continue)` "lets the error go on": the error can't be undone,
so continuing is the same as if there had been no stop, and it's reported
in the usual way. `(abort)` leaves without the report.

Not every error stops. **An error that a `catch-error` will handle doesn't**,
because the program expects it, and neither does running out of stack. An
error typed at the debug REPL is just reported, without stopping again.

With a hook that prints, this gives an error report that includes the
variables at the failure, in any front end. This hook shows them and then
recovers with `throw`, as `debugging_example.lsp` does:

```
(set-debug-hook!
  (lambda (kind name args)
    (if (eq? kind 'error)
        (begin
          (display (format "stopped by an error: {}\n" name))
          (display (format "variables there: {}\n" (locals)))
          (throw 'gave-up 'no-payment)))))
(break-on-error #t)
(catch 'gave-up (level-payment 100000 0 360))
```

prints

```
stopped by an error: division by zero
variables there: ((r . 0.0) (balance . 100000) (annual-percent . 0) (months . 360))
```

and the `catch` returns `no-payment`.

#### `(debug-function name)`, `(undebug-function name)`
Older names for `(break name)` and `(unbreak name)`, as macros that take the
bare name, like `pretty-print-function`.

**Where the debug REPL works.** The debug REPL reads from the real console
with `input()`, the same as the top-level REPL. It works when you run
the interpreter in a terminal (with a script or interactively). In the
GUI, it would read from whatever stdin the GUI process has (usually none, or the
terminal it was launched from), and in Jupyter there's no console at all:
use a hook that prints, and don't call `(debug-repl)`, in those.

**Good to know.** Breakpoints, the hook, and `break-on-error` belong to the
whole interpreter, like `verbose`, not to one environment. They cost
nothing when there are no breakpoints. A breakpoint stops *procedures*
being called; to look at what a procedure does inside, put `(breakpoint)`
there, or use `(verbose 2)` to see every call and return.

### Verbose mode and stack traces

Two aids for finding out *what your program is doing* and *how it got
into trouble*, both built on the same thing: every call of a user-defined
procedure (or macro transformer) leaves a frame on the evaluator's control
stack recording **which procedure was called, with which arguments**.

**Names.** A procedure's name is whatever it was `define`d as:
`(define (f x) ...)` is named `f`; `(define g (lambda ...))` names that
lambda `g`, if it doesn't already have a name (so `(define h g)` doesn't
rename it); a `defstruct`'s `make-<name>` constructors are named. A
procedure never bound to a name is `<lambda>`. Procedures now print with
their name — `#<procedure square>` — and `#<procedure>` when anonymous.

#### `(verbose [level])`
Turns call tracing on and off. With no argument, returns the current level.
With one, sets it and returns the **previous** level, so you can restore it.
`#t` and `#f` mean levels 1 and 0.

| Level | Logged |
|---|---|
| `0` | nothing (the default) |
| `1` | each call of a user-defined procedure, **by name** |
| `2` | each call **with its arguments**, and each return **with its value** |
| `3` | everything in 2, plus every **macro expansion** |

```lisp
(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))
(verbose 2)
(fact 3)
(verbose 0)
```

```text
> (fact 3)
  > (fact 2)
    > (fact 1)
      > (fact 0)
      < (fact 0) => 1
    < (fact 1) => 1
  < (fact 2) => 2
< (fact 3) => 6
```

`>` is a call, `<` its return, indented by call depth. A call in **tail
position** is written `>>` instead: it *replaces* its caller's frame (which
is what makes tail calls constant-space), so it sits at the caller's depth,
and the eventual return line says how many calls it absorbed:

```text
> (count-down 3)
>> (count-down 2)
>> (count-down 1)
>> (count-down 0)
< (count-down 0) => done  [after 3 tail calls]
```

At level 3, a macro call also logs the form and what it expanded to:
`~ (unless #f (quote ran)) => (if #f (quote ()) (begin (quote ran)))`.

- Only **user-defined procedures** are traced — not built-ins like `+` or
  `car`, and not `let`/`let*`/`dolist` scopes (which are variable scopes,
  not calls; `dolist`'s hidden loop procedure does show up, as
  `%dolist-loop-N`). A callback run by a built-in (`map`, `filter`, ...) is
  traced like any other call.
- Values are **summarized**, never printed in full — a long list shows its
  first few elements and `...`, a big vector shows `#(7 7 7 ... n=1000000)` —
  so tracing a call on a large dataset stays fast and readable.
- Trace lines go **wherever `display` output goes**: the console, the GUI
  log, a Jupyter cell, or a file after `redirect-output`. Interleaved with
  your own output, in order.
- Level 0 costs nothing measurable, and turning tracing on mid-run is safe
  (indentation is counted from where you turned it on).
- Start a whole run traced with `-v`/`-vv`/`-vvv`/`--verbose=N` on the
  command line, or the `LISP_VERBOSE` environment variable.

```lisp
(define old (verbose 1))       ; tracing on; old is the previous level (0)
; ... run the suspicious code ...
(verbose old)                  ; restore whatever it was
```

#### Stack traces
When an error escapes, it is reported together with the chain of procedure
calls that led to it — oldest first, so the most recent call is right above
the message, like Python's:

```text
Lisp traceback (most recent call last):
  (outer 5)
  (middle 5)  [+1 tail call]
  (inner 5)
Error: car: not a pair: 5
```

This appears wherever errors are shown — batch mode (which then exits with
status 1), the console REPL, the GUI log, and Jupyter's error box — and it
is always on, whether or not `verbose` is. Each line is `(name arguments...)`
(summarized, as above), plus a note when there is something to explain:

- `[+N tail calls]` — that call replaced N earlier callers by tail-calling
  its way out (as in any tail-call-optimizing Lisp, a caller that tail-called
  is no longer on the stack, so it can't be listed; the count accounts for
  them). In the example, `helper` tail-called `middle`.
- `[arguments rejected]` — the call never started because its arguments
  were wrong (too few/many, an unknown `:keyword`): the trace names the
  procedure that was called incorrectly, e.g. `(make-point :z 1)`.
- `[macro transformer]` — the error happened while a macro was computing
  its expansion, rather than in the code it expanded to.

A very deep stack (say, runaway recursion) shows its outermost 10 and
innermost 30 calls with `... N more calls ...` between. An error raised
outside any procedure call has no chain, just the `Error:` line. A call
that is caught with `catch-error` leaves nothing behind.

#### `(backtrace)`
Prints the same chain for the **current** point in the program, without an
error — a special form, so it takes no arguments and can be dropped anywhere.
It sees through callbacks (`map`, `filter`, ...) and macro transformers, and
typed at a `(breakpoint)`'s debug prompt it shows the paused program's chain.
Returns `'()`.

```lisp
(define (c) (backtrace) 0)
(define (b) (list (c)))
(define (a) (list (b)))
(a)
```

```text
Lisp call stack (most recent call last):
  (a)
  (b)
  (c)
```

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

---

## How the code is organized

The interpreter is split into these Python files, all in `lisp_interp/`:

| File | What's in it |
|---|---|
| `lisp_interpreter.py` | The command line (what runs when you type `python3 lisp_interpreter.py ...`), the console REPL, and batch mode |
| `lisp_core.py` | The language itself: data types, the reader, environments, the evaluator and special forms, call tracing, and the printer. It imports none of the other files. |
| `lisp_builtins.py` | The general built-in procedures (numbers, lists, strings, making and reading vectors, dates, hash tables, output, ...) and `make_global_env()`, which builds a new environment containing every builtin |
| `lisp_vector_math.py` | Arithmetic, comparisons, statistics, and time-series functions on whole vectors (`vector-mul`, `vector>`, `vector-mean`, `vector-lag`, ...) |
| `lisp_tables.py` | Tables: `table-filter`, `table-sort`, `table-group-by`, `table-join`, ... |
| `lisp_time_series.py` | Month numbers and monthly series: `yyyymm->month-number`, `series-monthly`, `series-table`, ... |
| `lisp_debug.py` | `break`, `unbreak`, `set-debug-hook!`, `abort`, `locals`, `break-on-error`, ...: the debugging functions (the machinery is in `lisp_core.py`) |
| `lisp_regression.py` | `linear-regression`, `logistic-regression`, `spline-regression`, `model-report`, ... |
| `lisp_simplex.py` | `lp-read-file`, `lp-solve`: linear programming (uses `simplex/`) |
| `lisp_charts.py` | `plot-xy`, `plot-xy-regression`, `plot-xy-full`, `save-chart` |
| `lisp_csv.py` | `load-csv`, `write-columns-csv` |
| `lisp_sqlite.py` | `sqlite-open`, `sqlite-query`, `sqlite-write-table`, ... |
| `lisp_http.py` | `http-get-json`, `http-get-csv`, ... (downloads from any web API) |
| `lisp_fred.py` | `fred-series` (downloads from FRED) |
| `lisp_tastytrade.py` | `tastytrade-*` (downloads from tastytrade) |
| `lisp_sofr.py` | `sofr-*` interest-rate modeling (uses `term_structure/`) |
| `lisp_gui.py` | The PyQt6 window |
| `lisp_kernel.py`, `lisp_jupyter.py` | The Jupyter kernel |
| `test_lisp_interpreter.py` | The test suite: `python3 -m unittest test_lisp_interpreter` |

Two Lisp files are loaded into every new environment at startup (by
`load_init_file()` in `lisp_builtins.py`): `macros_init.lsp`, the standard
macros (see "Standard macros"), and then `init.lsp`, your own
definitions.

Each file that adds builtins ends with a `BUILTINS` table — a Python dict
from the Lisp name to the Python function that implements it — and
`make_global_env()` in `lisp_builtins.py` copies each of those tables into
every new environment.

## Running the tests

`test_lisp_interpreter.py`, in `lisp_interp/`, is the test suite. It has
about 420 tests covering:

- the language itself: the reader, special forms, tail calls, macros,
  structs, and error reports;
- every family of builtins, from numbers and strings to tables,
  regression, and SQLite;
- the Lisp libraries: `macros_init.lsp`, `template.lsp`,
  `column_engine.lsp`, and the others;
- the command line, the REPL, and the offline example scripts;
- **this reference manual**: every ` ```lisp ` example with a `; =>`
  result is run, and the test fails if the interpreter no longer returns
  that value. So when you change how something behaves, the test suite
  tells you which documented examples need updating.

It needs nothing beyond what the interpreter itself needs (numpy). It
never uses the network, your credentials, or any file outside a temporary
directory, so it's safe to run at any time. The whole suite takes about 30
seconds. Run it after changing the interpreter, a builtin, a `.lsp`
library, or this manual.

**Running it.** From the `lisp_interp` directory:

```bash
python3 -m unittest test_lisp_interpreter
```

It prints a dot for each test that passes, then `OK`, or a report of each
test that failed. Other ways to run it:

| Command (in `lisp_interp/`) | What it runs |
|---|---|
| `python3 -m unittest test_lisp_interpreter` | every test |
| `python3 -m unittest -v test_lisp_interpreter` | every test, printing each test's name and result |
| `python3 -m unittest test_lisp_interpreter.TestFormat` | one group of tests (a test class) |
| `python3 -m unittest test_lisp_interpreter.TestFormat.test_decimals_and_commas` | one test |
| `python3 -m unittest -k Format test_lisp_interpreter` | every test whose group or name contains `Format` (upper/lower case matters) |
| `python3 test_lisp_interpreter.py` | every test; this form works from any directory, e.g. `python3 lisp_interp/test_lisp_interpreter.py` |
| `python3 -m pytest test_lisp_interpreter.py` | every test, using pytest instead, if it's installed; add `-k format` to pick tests (upper/lower case doesn't matter) |

To see the names of the groups, run `grep -n "^class Test" test_lisp_interpreter.py`.
Each group's docstring says what it covers.

**The slow examples.** Two example scripts take a while
(`dolist_vectors_map_example.lsp`, about 15 seconds, and
`oas_monte_carlo_example.lsp`, about 60), so they're skipped unless you
set the `LISP_TEST_SLOW` environment variable:

```bash
LISP_TEST_SLOW=1 python3 -m unittest test_lisp_interpreter
```

**What isn't tested.** Anything that needs the network or an account:
`fred-series`, `tastytrade-*`, and `sofr-calibration-data`. The
`http-get-*` functions are tested against a small web server that the
tests start on your own computer. The GUI and the Jupyter kernel get only
a check that their error reports look right. The GUI check runs
off-screen, so no window opens. It's skipped if PyQt6 isn't installed, and
the Jupyter check is skipped if ipykernel isn't.

**Reading a failure.** Each failure names the test and shows what was
expected and what happened. For a test that ran Lisp code, it also shows
that code (`source: ...`). A failing reference-manual example is listed
like this:

```
block 239: (defined-macros)
      doc says: (double-it)
      got:      (while do double-it)
```

Here, either the example in the manual is out of date (fix the
manual), or the interpreter changed when it shouldn't have (fix the
code).

## Adding your own builtins

**First, consider writing it in Lisp.** If a new function can be written in
Lisp using the existing builtins, put it in a `.lsp` file (like
`solver.lsp` or `model_utils.lsp`) and `(load ...)` it, or add it to
`init.lsp` so every session has it. No Python changes needed.

Write a builtin in Python when it needs something Lisp can't do: a Python
package, a network or file format, or speed on large data. The steps:

**1. Create a module** — a new file next to the others, e.g.
`lisp_finance.py`. Write each builtin as an ordinary Python function, and
end the file with a `BUILTINS` table:

```python
"""Mortgage math builtins: level-payment and remaining-balance."""

from lisp_core import LispError


def level_payment(annual_rate_pct, months, principal):
    """(level-payment rate months principal) -- the fixed monthly payment
    that pays off `principal` over `months` at an annual rate in percent."""
    if months <= 0:
        raise LispError("level-payment: months must be positive")
    r = annual_rate_pct / 1200.0
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def remaining_balance(annual_rate_pct, months, principal, payments_made=0):
    """(remaining-balance rate months principal [payments-made]) -- the
    balance left after `payments-made` level payments (default 0)."""
    r = annual_rate_pct / 1200.0
    payment = level_payment(annual_rate_pct, months, principal)
    if r == 0:
        return principal - payment * payments_made
    growth = (1 + r) ** payments_made
    return principal * growth - payment * (growth - 1) / r


BUILTINS = {
    "level-payment": level_payment,
    "remaining-balance": remaining_balance,
}
```

**2. Register it** in `lisp_builtins.py`: import the module with the
others at the top of the file (`import lisp_finance`), and add one line to
`make_global_env()` next to the other modules' tables:

```python
    env.update(lisp_finance.BUILTINS)
```

**3. Try it** — restart the interpreter (or the Jupyter kernel):

```lisp
(level-payment 6.0 360 100000)             ; => 599.5505251527569
(remaining-balance 6.0 360 100000 12)      ; => 98771.98828772324
```

A builtin that works on a whole vector should use numpy on the vector's
`items`, as the functions in `lisp_vector_math.py` do, rather than a
Python loop — that's what keeps it fast on millions of values.

**4. Document and test it** — add an entry to this reference, in the
section where it belongs, and a test to `test_lisp_interpreter.py`. Any
`; =>` example you put in a ` ```lisp ` block here is checked by the test
suite, so the documentation can't drift out of date. Then run the tests
(see "Running the tests", above).

### What a builtin receives and returns

A builtin is called with its arguments already evaluated, as these Python
values (all defined in `lisp_core.py`):

| Lisp value | Python value |
|---|---|
| number | `int` or `float` |
| `#t` / `#f` | `True` / `False` — note that `'()` and `0` count as *true* in Lisp; only `#f` is false, so test with `x is not False` or `lisp_core.is_true(x)` |
| string | `LispString` (a `str` subclass) |
| symbol, keyword | `Symbol`, `Keyword` (also `str` subclasses) |
| list | a chain of `Pair` objects ending in `NIL` (which is `None`); convert with `pairs_to_list(p)` → Python list, and back with `list_to_pairs(items)` |
| vector | `LispVector`; its `.items` is a numpy array — use `.items.tolist()` for plain Python numbers, and `LispVector(python_list)` to build one |
| date | `LispDate`; its `.date` is a Python `datetime.date` |
| procedure | a Lisp procedure; call it with `apply_proc(f, [arg1, arg2])` |

A few conventions keep builtins consistent with the rest:

- **Errors:** raise `LispError("name: what went wrong")`. The message
  reaches the user just like any other Lisp error, and `catch-error` can
  catch it.
- **Optional arguments:** give the Python parameter a default value, as
  `sample=True` does above. Lisp passes arguments by position.
- **Returning nothing:** return `NIL`, the way `display` and `vector-set!`
  do.
- **Returning a string:** wrap it as `LispString(text)`, so Lisp sees a
  string rather than a symbol.
- **Optional Python packages:** import them inside `try: ... except
  ImportError:`, and have the builtin raise a `LispError` explaining what
  to install if it's missing (see how `lisp_tastytrade.py` handles the
  `tastytrade` package). That way the rest of the interpreter still starts
  without the package.
- **Naming:** Lisp names use dashes (`vector-mean`); a function that
  answers yes/no ends in `?` (`vector?`); one that changes its argument
  ends in `!` (`vector-set!`).

A builtin that needs its *environment* — to evaluate code, read a Lisp
variable, or write to the same place `display` does — can't be a plain
module-level function, because there's one environment per session. For
those, write a function that takes what it needs and returns a table,
the way `make_eval_builtins(env, out)` and
`lisp_charts.make_chart_builtins(plot)` do, and call it from
`make_global_env()`.
