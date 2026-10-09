# morris-lisp — The language

A Lisp for investment analysis: getting data (prices, option chains, and
accounts from Schwab and tastytrade; economic and financial data from FRED,
the SEC, the FDIC, the BLS, the BEA, the Census Bureau, and Alpha Vantage;
any web API, CSV files, and SQLite), working with it as tables and vectors,
and modeling it: regression, simulated prices and portfolios, option
prices, the volatility smile, rates and mortgages, charts, and maps. It is
a whole Lisp too, with macros, structs, hash tables, error handling, and a
debugger, and it runs in a console, a small GUI, or a Jupyter notebook.
**Requires `numpy`**; everything else (PyQt6, matplotlib, pandas, the
tastytrade package) is needed only for the features that use it. The code
is meant to be read: "How the code is organized" says which file has what.

There are two manuals. **This one is the language**: its syntax, special
forms and macros, and the general builtins -- numbers, lists, strings, hash
tables, vectors and statistics, tables, dates, charts, input and output,
and the debugger. **The library manual,
[lisp_library_reference.md](lisp_library_reference.md)**, has the rest:
getting data, statistical models, dates and cash flows for finance, and
investments. Its first chapter, ["Where things are"](lisp_library_reference.md#where-things-are), is a map of them.

This document aims to cover **every builtin and special form** of the
language: what its arguments mean, what it returns, and any non-obvious
behavior or error conditions. For a quicker orientation, read "Running
it", "Syntax", and "Special forms and standard macros" first, then treat
"Built-in functions" as a reference to search rather than read start to
end.

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [Running it](#running-it)
- [Syntax](#syntax)
- [Special forms and standard macros](#special-forms-and-standard-macros)
  - [Defining variables and procedures](#defining-variables-and-procedures)
    - [define](#define)
    - [set!](#set)
    - [push, pop, incf, decf](#push-pop-incf-decf)
    - [lambda](#lambda)
    - [begin](#begin)
    - [lazy-load](#lazy-load)
  - [Variadic parameters](#variadic-parameters)
  - [Keyword arguments](#keyword-arguments)
  - [Local variables](#local-variables)
    - [let](#let)
    - [let*](#let-1)
    - [destructuring-bind](#destructuring-bind)
    - [with-columns](#with-columns)
  - [Choosing](#choosing)
    - [if](#if)
    - [cond](#cond)
    - [case](#case)
    - [when, unless](#when-unless)
    - [and](#and)
    - [or](#or)
  - [Looping](#looping)
    - [dolist](#dolist)
    - [while](#while)
    - [do](#do)
    - [loop](#loop)
  - [Structs](#structs)
    - [defstruct](#defstruct)
    - [with-struct](#with-struct)
  - [Errors and cleanup](#errors-and-cleanup)
    - [catch-error](#catch-error)
    - [unwind-protect](#unwind-protect)
    - [catch throw](#catch-throw)
    - [assert](#assert)
    - [with-sqlite](#with-sqlite)
  - [Quoting](#quoting)
    - [quote](#quote)
    - [quasiquote](#quasiquote)
  - [Macros](#macros)
    - [defmacro](#defmacro)
  - [Debugging](#debugging)
    - [breakpoint](#breakpoint)
    - [backtrace](#backtrace)
    - [pretty-print-function, pretty-print-macro](#pretty-print-function-pretty-print-macro)
- [Built-in functions](#built-in-functions)
  - [Arithmetic](#arithmetic)
  - [Random numbers](#random-numbers)
  - [Comparison / equality / booleans](#comparison--equality--booleans)
  - [Pairs and lists](#pairs-and-lists)
  - [Hash tables](#hash-tables)
  - [Strings](#strings)
  - [Regular expressions](#regular-expressions)
  - [Formatting numbers and text](#formatting-numbers-and-text)
  - [Vectors](#vectors)
  - [Vector math and statistics](#vector-math-and-statistics)
  - [Tables](#tables)
  - [Structs](#structs-1)
  - [Dates](#dates)
  - [The clock](#the-clock)
  - [Charting](#charting)
  - [Displaying tables](#displaying-tables)
  - [Input / output](#input--output)
  - [Saving variables](#saving-variables)
  - [Metaprogramming](#metaprogramming)
  - [Introspection / debugging](#introspection--debugging)
  - [Debugging](#debugging-1)
  - [Verbose mode and stack traces](#verbose-mode-and-stack-traces)
- [A short example](#a-short-example)
- [Examples after Norvig's *Paradigms of AI Programming*](#examples-after-norvigs-paradigms-of-ai-programming)
- [A chess program](#a-chess-program)
- [A KenKen solver](#a-kenken-solver)
- [How the code is organized](#how-the-code-is-organized)
- [Running the tests](#running-the-tests)
- [Adding your own builtins](#adding-your-own-builtins)
  - [What a builtin receives and returns](#what-a-builtin-receives-and-returns)

## Running it

- **No arguments** — `python3 lisp_interpreter.py` opens the PyQt6 GUI (an
  input box, an output log, a "Table" tab, and a chart tab). The
  Table tab is filled only by an explicit `(display-table ...)` call (see
  "Displaying tables", below) — there's no automatic scan of top-level
  variables. If PyQt6 or matplotlib isn't installed, it falls back to a
  plain console REPL instead.
- **A filename argument** — `python3 lisp_interpreter.py script.lsp` runs
  that file in batch mode (no GUI). `save-chart` still works in this mode
  as long as matplotlib is installed (PyQt6 is not required for it).
  - **Words after the file name** — `python3 lisp_interpreter.py script.lsp
    KO 6` gives the script the words `"KO"` and `"6"`: `(command-line-arguments)`
    returns `("KO" "6")`. `destructuring-bind` can name them, with defaults
    for any left off: `(destructuring-bind (&optional (symbol "BRK/B"))
    (command-line-arguments) ...)`, as `examples/option_methods_example.lsp`
    does. They're strings; `string->number` makes a number of one.
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
  The message starts with the name of the procedure, builtin, or special
  form that went wrong: `cons: expected 2 arguments, got 1`,
  `sqrt: expected a nonnegative input, got -1.0`,
  `define: badly formed: (define x)`. (A builtin is written in Python, and
  when Python itself objects to what it was given, the interpreter turns
  Python's message into one of these.) Set `LISP_PYTHON_TRACEBACK=1` to get
  Python's own traceback of the interpreter's internals as well, including
  the Python exception behind a builtin's error.

Every fresh environment — batch mode, the console REPL, the GUI, and
Jupyter alike — loads these Lisp files before doing anything else:

1. `macros_init.lsp` and `loop.lsp`, the standard macros, such as `let`,
   `dolist`, `while`, `case`, and `loop` (see "Special forms and standard
   macros", below).
   They're part of the interpreter: `make_global_env()` loads them into
   every new environment.
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
  not a GUI chart tab or a `save-chart` file) and `(display-table ...)`
  renders as a real table instead of the console's plain text table. One environment persists for the kernel's
  whole lifetime, the same as typing into the console REPL — restarting
  the kernel (Jupyter's own "Restart" button) starts a fresh one. Built as
  an `IPythonKernel` subclass specifically so `IPython.display.display()`
  (which the chart/table rendering uses, in `lisp_jupyter.py`) keeps
  resolving correctly — see `lisp_kernel.py`'s own docstring for why that
  specific base class matters, and what else is worth knowing about how it
  behaves (error display, tab-completion, history variables `_`/`__`/
  `___`/`_N`). Needs `pandas` and `ipykernel` in addition to matplotlib;
  falls back to the console's plain-text chart/table output if either
  isn't installed. A `(breakpoint)`, a `(break f)`, or an error with
  `break-on-error` opens a debug REPL made with `ipywidgets` in the
  running cell's output (see "Debugging", below). Any of these builtins that fetch over the network
  (`tastytrade-*`, `sofr-calibration-data`) work fine here too -- they run
  their I/O via `asyncio`, and `_run_async()` (in `lisp_tastytrade.py`,
  and an identical twin in `term_structure/sofr_market_data.py`)
  specifically handles being called from inside a Jupyter kernel's own
  already-running event loop, which a bare `asyncio.run()` call can't do.
- **Where `load` finds a file** — `(load "name.lsp")` looks in the current
  directory, then in each directory listed in the `LISP_PATH` environment
  variable (separated by colons, as in `PATH`), then in the interpreter's
  own `lib` and `examples` directories. So `(load "solver.lsp")` works from
  a notebook in any directory, and so does a library that loads another.
  To use your own directories, set `LISP_PATH` before starting Jupyter or
  the interpreter, e.g. `export LISP_PATH=~/models:~/models/common`.

## Syntax

| Type | Example | Notes |
|---|---|---|
| Integer | `42`, `-7` | Python `int` |
| Float | `3.14`, `-0.5`, `nan`, `inf` | Python `float`. `nan` ("not a number", the missing-value marker) and `inf` (infinity) are numbers too, so they can't be used as names (see below) |
| String | `"hello"` | Double-quoted; `\n`, `\t`, `\r`, `\"`, `\\` escapes. A backslash before any other character is kept, as in Python, so a regular expression can be written as it is: `"\d+"`. The REPL prints a string the same way, in quotes and with `\"` and `\\` for a quote mark or backslash inside it, so what it prints can be typed back in (see `display`) |
| Boolean | `#t`, `#f` | Everything except `#f` counts as true |
| Symbol | `foo`, `list->vector` | Identifiers: anything that isn't read as a number or one of the types above |
| quote | `'(a b c)` , `'(1 2 3)` , `'f`| Something that is not to be evaluated, but is treated as data |
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

## Special forms and standard macros

These are the forms that aren't ordinary procedure calls: `define`, `if`,
`let`, loops, error handling, and so on. Some are **special forms**, built
into the evaluator (`lisp_core.py`); the rest are **standard macros**,
written in Lisp in `macros_init.lsp` and `loop.lsp`, which every new
environment loads at startup (see "Running it", above). You use both the
same way, so they're described together here, grouped by what they're for.
For the curious, the macros are `let`, `let*`, `destructuring-bind`,
`lazy-load`, `dolist`, `while`, `do`, `loop`, `when`, `unless`, `case`,
`assert`, `with-sqlite`, `with-columns`, `pretty-print-function`, and
`pretty-print-macro`; everything else here is a special form.

What they have in common: a form receives its argument *expressions*
unevaluated, and decides what to evaluate and when — which is what
distinguishes it from an ordinary procedure call, where every argument is
evaluated before the call happens. A special form works on the expressions
directly; a macro rewrites them into other code (`let` into a call of a
`lambda`, `while` into a local function that calls itself), which is then
evaluated in its place. To see what a macro call becomes, use
`macroexpand-1`, e.g. `(macroexpand-1 '(while (< i 3) (set! i (+ i 1))))`.
The top of `macros_init.lsp` explains how its macros are written, as a
tutorial for writing your own (see also "Macros", below); `loop.lsp` is a
larger example, a macro that reads a small language of its own.

A form that isn't written correctly, such as `(define x)`, is an error that
says so: `define: badly formed: (define x)`.

**Tail calls.** A procedure call that's the last thing a body does — in
tail position, including through `if`, `cond`, `when`, `unless`, `case`,
`let`, `let*`, `begin`, `and`, `or`, and the loops — doesn't grow the
stack, so a loop written as a function that calls itself can run any
number of times. (`catch-error`, `catch`, and `unwind-protect` are the
exception: see "How deep they can nest", under "Errors and cleanup".)

### Defining variables and procedures

`define` gives a name a value, or defines a procedure; `set!` changes a
variable's value; `lambda` makes a procedure without a name; `begin` runs
several expressions where one is expected. What a parameter list can say
is in "Variadic parameters" and "Keyword arguments", next.

#### define
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

#### set!
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

#### push, pop, incf, decf
#### `(push item variable)`, `(pop variable)`, `(incf variable [n])`, `(decf variable [n])`
Standard macros for changing a variable, as in Common Lisp — but only a
variable, since there's no `setf` here. `push` puts `item` on the front
of the list in `variable`, and returns the new list; `pop` takes the first
element off, and returns it. `incf` adds `n` (1 unless given) to the
number in `variable`, `decf` takes it away, and each returns the new
value.

```lisp
(define stack '())
(push 1 stack)                  ; => (1)
(push 2 stack)                  ; => (2 1)
(pop stack)                     ; => 2
stack                           ; => (1)
(define n 10)
(incf n)                        ; => 11
(decf n 5)                      ; => 6
```

#### lambda
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

#### begin
#### `(begin expr...)`
Evaluates each expression in order, returning the value of the last one (or
`'()` if there are none). The last expression is in tail position.

```lisp
(begin (display "a") (display "b") 42)   ; prints ab, => 42
```

#### lazy-load
#### `(lazy-load file name...)`
A macro that makes each `name` a function that, the first time it's
called, loads `file` (as `load` does) and then calls the function of that
name the file defined, with the same arguments. So a library's functions
can be called without loading it first, and the file isn't read until one
of them is. (Emacs Lisp calls this `autoload`.) It returns the names.

```lisp
(lazy-load "solver.lsp" ridders nelder-mead)
(ridders (lambda (x) (- (* x x) 2)) 0 2)    ; loads solver.lsp, then calls its ridders
```

Each name is first a stand-in, a *stub*, which the file's own definition
replaces when it's loaded: the stubs of all the names at once, since the
file defines them all, so the file is loaded once. A stub that the file
doesn't replace is an error (`lazy-load: solver.lsp didn't define ...`),
not a loop. It works for functions, not for a file's macros or variables:
a macro is needed before the code that uses it runs, and a variable isn't
called. `lib/autoloads.lsp` has the lazy-loads for the libraries that come
with the interpreter, and `init.lsp` loads it, so that `(option-methods
creds "KO")` works without a `load`. `macros_init.lsp` shows what a stub
looks like.

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

### Local variables

`let` and `let*` give names to values for the length of a body — the
names exist only inside it. `destructuring-bind` names the parts of a
list.

#### let
#### `(let ((name val)...) body...)`
A macro that expands to `((lambda (name...) body...) val...)`: every `val`
is evaluated in the *outer* environment (none of them can see each other's
bindings), then `body...` runs with all the names bound simultaneously.
(The expansion uses `%scope-lambda`, a `lambda` that stack traces leave
out, since a `let` isn't a function call.) Each binding must be
`(name val)`; anything else is an error.

```lisp
(let ((a 1) (b 2)) (+ a b))    ; => 3
```

#### let*
#### `(let* ((name val)...) body...)`
Like `let`, but a macro that expands to nested single-binding `let`s, so
each `val` expression can see every `let*` binding that came before it in
the same form.

```lisp
(let* ((a 1) (b (+ a 1))) (list a b))   ; => (1 2) -- b's val sees a
```

#### destructuring-bind
#### `(destructuring-bind pattern expression body...)`
Evaluates `expression`, which gives a list, binds the variables in
`pattern` to its parts, and runs `body...` with them, as Common Lisp's
`destructuring-bind` does. The pattern has the shape of the list, and can
have, in this order:

| Part | What it binds |
|---|---|
| variables | one for each element, or a pattern of its own for an element that is a list: `(a (b c) d)` |
| `&optional` | then elements that may be missing: `x`, `(x default)`, or `(x default supplied-p)`. A missing one gets `default` (`'()` unless given), which can use the variables before it, and `supplied-p` is `#t` if it was there, `#f` if not. `x` can be a pattern |
| `&rest x`, `&body x`, or a dot, `(a b . x)` | `x` gets the rest of the list |
| `&key` | then keyword arguments, from `:name value` pairs in the rest of the list: `x`, `(x default)`, or `(x default supplied-p)`, for `:x`. Another key is an error, unless `&allow-other-keys` follows |
| `&aux` | then more variables, not from the list: `x`, or `(x value)` |

It can also start with `&whole x`, for `x` to get the whole list. A list
with too few elements, or more than the pattern has room for, or a key it
doesn't have, is an error that shows the list and the pattern.

```lisp
(destructuring-bind (a (b c) . more) '(1 (2 3) 4 5) (list a b c more))   ; => (1 2 3 (4 5))
(destructuring-bind (name &optional (count 1)) '("BRK/B") (list name count))   ; => ("BRK/B" 1)
(destructuring-bind (symbol &key (rate 0.04) (months 3)) '("KO" :months 6)
  (list symbol rate months))                                     ; => ("KO" 0.04 6)
(destructuring-bind (a b) '(1 2 3) a)   ; raises LispError: destructuring-bind: (1 2 3) doesn't fit the pattern (a b): it has too many elements
```

It expands to a `let*`, with a variable for what is left of the list as it
goes and a check wherever the list might not fit: `(macroexpand-1
'(destructuring-bind (a b) x (+ a b)))` shows it, and `macros_init.lsp`
explains it.

#### with-columns
#### `(with-columns (column...) table body...)`
A macro that binds a variable to each listed column of a table, as `let`
would, then evaluates the body: `(with-columns (balance rate) loans
...)`. See "Tables", below.

### Choosing

`if` chooses between two expressions; `cond` between any number, by
test; `case` by matching a value against constants; `when` and `unless`
run a body only if a test is true or false. `and` and `or` stop as soon as
the answer is known.

#### if
#### `(if test conseq [alt])`
Evaluates `test`; if it is not `#f` (everything else — including `0` and
`'()` — counts as true), evaluates and returns `conseq`; otherwise
evaluates and returns `alt`, or `'()` if `alt` was omitted.

```lisp
(if (> 3 2) 'yes 'no)          ; => yes
(if (> 2 3) 'yes)              ; => ()  -- no alt given, test was false
```

#### cond
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

#### case
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

#### when, unless
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

#### and
#### `(and expr...)`
Evaluates each expression in order, stopping and returning `#f` as soon as
one is false; if every expression is true, returns the value of the last
one. `(and)` (zero arguments) returns `#t`.

```lisp
(and 1 2 3)                    ; => 3  -- every expr true, returns the last
(and 1 #f 3)                   ; => #f -- stops at the first false one
```

#### or
#### `(or expr...)`
Evaluates each expression in order, stopping and returning the value of the
first one that's true; if none are, returns `#f`. `(or)` (zero arguments)
returns `#f`.

```lisp
(or #f #f 3)                   ; => 3  -- first true value
(or #f #f)                     ; => #f -- none were true
```

### Looping

`dolist` runs a body for each element of a list or vector; `while` runs a
body while a test is true; `do` steps variables until a test is true; and
`loop` is Common Lisp's loop, which can count, step through lists, collect,
sum, and more, in one form. `while`, `do`, and `dolist` each turn into a
small local function that calls itself to go around again; that call is a
tail call, so a loop can run any number of times without growing the
stack, and the function's name comes from `gensym`, so it can't clash with
a name in your code.

#### dolist
#### `(dolist (var list-expr [result-expr]) body...)`
Common-Lisp-style iteration over a list, or over a vector. Evaluates
`list-expr` exactly once, then for each element in turn binds `var` to it
and runs `body...` for side effects (`display`, `set!`, `vector-set!`, etc.
— like `map`, but for when you're looping for effect and don't want a
collected result). Once the elements are used up, `var` is rebound to `'()`
and `result-expr` is evaluated and returned (or `'()` if no `result-expr`
was given). A macro that expands into a self-recursive local function
(named with `gensym`, so it can't clash with your names), whose recursive
step is in tail position — so it runs in constant control-stack space no
matter how long the list is.

```lisp
(define total 0)
(dolist (x (list 1 2 3 4 5)) (set! total (+ total x)))
total                          ; => 15
(dolist (x #(10 20) total) (set! total (+ total x)))   ; => 45
```

For loops that aren't over a list, see `while` and `do` under "Standard
macros", below.

#### while
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

#### do
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

#### loop
#### `(loop clause...)`
Common Lisp's `loop`: a loop written as a list of **clauses**, which read a
little like English. Each clause says one thing: what to step through, what to
do on each pass, when to stop, what to give back. It's the loop to reach for
when you're stepping through a list or counting, and collecting, adding up,
or searching.

```lisp
(loop for i from 1 to 5 collect (* i i))                        ; => (1 4 9 16 25)
(loop for x in '(3 1 4 1 5) sum x)                              ; => 14
(loop for x in '(3 1 4 1 5) maximize x)                         ; => 5
(loop for x in '(1 2 3 4 5 6) when (> x 3) collect x)           ; => (4 5 6)
(loop for x in '(1 2 3) for y in '(a b c) collect (list x y))   ; => ((1 a) (2 b) (3 c))
(loop for x in '(1 2 3 4) thereis (and (> x 2) (* x 10)))       ; => 30

; Months until a balance growing 0.5% a month passes 300,000:
(loop for month from 1
      for balance = 200000 then (* balance 1.005)
      until (> balance 300000)
      finally (return month))                                   ; => 83
```

The loop goes round and round. On each **pass**, the clauses happen in the
order they're written. A stepping clause (`for x in list`) ends the loop when
it runs out. The loop's value is what its accumulating clause built up
(`collect` gives a list, `sum` a total), or, if it has none, `'()`, unless a
`return` or `finally` says otherwise. Write the stepping clauses (`for`,
`repeat`) first, and the clauses that do things after them, as in Common Lisp.
The **variables** are ones the loop makes: `x` and `i` above exist only in
the loop.

##### Stepping: `for`, `as`, `repeat`
`as` means the same as `for`. Give each `for` its own variable; `for x in
xs for y in ys` steps through both together and stops when the shorter runs
out.

| Clause | The variable is... |
|---|---|
| `for x in list` | each element of the list |
| `for x on list` | the list, then what follows its first element, and so on |
| `for x across vector` | each element of the vector |
| `for i from 1 to 10` | 1, 2, ... 10 (`upto` means `to`; leave out `from` to start at 0) |
| `for i from 1 below 10` | 1, 2, ... 9 |
| `for i from 10 downto 1` | 10, 9, ... 1 (also `above 1` to stop before 1, and `downfrom 10 to 1`) |
| `for i from 0 to 100 by 25` | 0, 25, 50, 75, 100 (`by` is a positive step, up or down) |
| `for x = a then b` | `a` on the first pass, then `b` (which can use `x`, and other variables) on each later one |
| `for x = a` | `a`, worked out again on every pass |
| `for k being the hash-keys of table` | each key of a hash table; add `using (hash-value v)` for the value too |
| `for v being the hash-values of table` | each value; add `using (hash-key k)` for the key too |
| `repeat n` | (no variable) go round `n` times |

The list, vector, hash table, start, end, and step are worked out once, when
the loop starts.

```lisp
(loop for i from 0 to 100 by 25 collect i)                      ; => (0 25 50 75 100)
(loop for i from 10 downto 7 collect i)                         ; => (10 9 8 7)
(loop for x on '(1 2 3) collect x)                              ; => ((1 2 3) (2 3) (3))
(loop for x across #(1 2 3) sum x)                              ; => 6
(loop for x = 1 then (* x 2) repeat 5 collect x)                ; => (1 2 4 8 16)
(loop repeat 3 collect 'x)                                      ; => (x x x)
```

A variable in `for x in`, `on`, and `=` can be a **pattern**, which takes each
element apart: `(a b)` for a two-element list, `(key . value)` for a pair.
A `()` in a pattern skips that part, and a pattern with more variables than
there are elements gives the extra ones the value `'()`.

```lisp
(loop for (a b) in '((1 2) (3 4)) collect (+ a b))              ; => (3 7)
(loop for (name . rate) in '((a . 5) (b . 6)) collect (* rate 2))   ; => (10 12)
(loop for (a b c) in '((1 2)) collect (list a b c))             ; => ((1 2 ()))
```

##### Accumulating: `collect`, `append`, `sum`, `count`, `maximize`, `minimize`
Each takes an expression, worked out on every pass. (The `-ing` forms
work too: `collecting`, `summing`, ...)

| Clause | The loop returns |
|---|---|
| `collect x` | a list of the values of `x` |
| `append x` | a list of all the elements of the lists `x` (the lists aren't changed; `nconc` means the same) |
| `sum x` | the total of the values of `x` (0 if there were none) |
| `count test` | how many times the test was true (0 if none) |
| `maximize x` / `minimize x` | the largest / smallest value of `x` (`'()` if there were none) |

```lisp
(loop for x in '((1 2) (3) (4 5)) append x)                     ; => (1 2 3 4 5)
(loop for x in '(3 1 4 1 5) count (> x 2))                      ; => 3
(loop for x in '(3 1 4 1 5) minimize x)                         ; => 1
(loop for x in '() sum x)                                       ; => 0
```

Several clauses that collect share one list, in order: `collect x collect (* 10
x)` gives `(1 10 2 20 ...)`. Ones of different kinds can't share: `collect` with `sum` is
an error.

**`into`.** End an accumulating clause with `into var`, and it builds up the
variable `var` instead. The loop makes `var`, so it can be used in the loop's
later clauses, and in `finally`. The loop then has no value of its own; use
`finally (return ...)` to return what you like.

```lisp
(loop for x in '(3 1 4 1 5)
      sum x into total
      count #t into n
      finally (return (/ total n)))                             ; => 2.8
```

##### Conditions: `when`, `unless`, `if`
`when test clause [and clause]... [else clause [and clause]...] [end]`. The
clauses inside can be `do`, `return`, an accumulating clause, or another
`when`. `and` joins clauses in one branch. `unless` is `when` with the
branches swapped, and `if` is another word for `when`. An `else` goes with the
nearest `when`; write `end` to close one early.

```lisp
(loop for x in '(1 2 3 4) if (< x 3) collect x else collect (- x))    ; => (1 2 -3 -4)
(loop for x in '(1 2 3 4 5) unless (= x 3) sum x)                     ; => 12
(loop for x in '(1 2 3 4 5)
      when (> x 2) collect x into big and sum x into total
      finally (return (list big total)))                              ; => ((3 4 5) 12)
```

##### Ending the loop
| Clause | What it does |
|---|---|
| `while test` | ends the loop, at that point in the pass, when the test is false |
| `until test` | ends the loop when the test is true |
| `always test` | if the test is ever false, the loop ends at once and returns `#f`; otherwise it returns `#t` |
| `never test` | the same, for a test that is ever true |
| `thereis test` | if the test is ever true, the loop ends at once and returns its value; otherwise it returns `#f` |
| `return value` | leaves the loop, returning the value |

```lisp
(loop for i from 1 to 10 while (< i 4) collect i)               ; => (1 2 3)
(loop for x in '(1 2 3) always (> x 0))                         ; => #t
(loop for x in '(1 2 3) never (> x 2))                          ; => #f
(loop for x in '(1 2 3 4 5) when (> x 3) return x)              ; => 4
```

The loop's clauses after `while` or `until` don't happen on the pass that
ends it, but `finally` does. **`return` skips `finally`**, and so does a
failed `always`, `never`, or `thereis`.

##### Doing things, and before and after
| Clause | |
|---|---|
| `do form...` | evaluate the forms on every pass (any number of them; a form that's a list is part of the `do`, and a word starts the next clause) |
| `with x = a [and y = b]...` | variables that get their value once, at the start (`with x` alone starts as `'()`), and that you can change with `set!` |
| `initially form...` | evaluate the forms once, before the first pass |
| `finally form...` | evaluate the forms once, after the last pass |

```lisp
(loop with total = 0
      for x in '(1 2 3)
      do (set! total (+ total x))
      finally (return total))                                   ; => 6
```

##### Leaving a loop: `return`, `return-from`, and `named`
`(return value)` leaves the nearest loop and makes it return the value.
`(loop named search ...)` gives a loop a name, and
`(return-from search value)` leaves that one, from inside a loop inside it, say.

```lisp
(loop named search
      for i from 1 to 3
      do (loop for j from 1 to 3
               do (if (= (* i j) 6) (return-from search (list i j)))))   ; => (2 3)
(loop for x in '(1 2 3 4) do (if (> x 2) (return x)))          ; => 3
```

A `(loop clauses...)` whose first clause is a list, not a word, is the
**simple loop**: it repeats those forms until one does `(return value)`. It
needs a `return`.

`return` and `return-from` are macros that `throw` to a `catch` around the
loop. The loop only makes that `catch` when it sees `return` or `return-from`
in its clauses, so **a `return` has to be written inside the loop**, as in Common
Lisp. Written in a separate function that the loop calls, it's an error:
"nothing catches loop-nil". (Use `throw` and `catch` yourself for that.) A
`return` outside a loop is the same error. They aren't available in `dolist`,
`do`, or `while`.

##### How it works, and how fast it is
`loop` is a macro that turns the clauses into ordinary code (a `let*` for the
variables, and a `while` round the pass), and the code is made once, the first
time the loop runs (see "A macro call is expanded once", under "Macros"). The
hidden variables it makes have `gensym` names, so they can't clash with
yours. To see the code for a loop, use `print-macroexpansion`:

```
(print-macroexpansion '(loop for x in prices when (> x 100) collect x))
```

`loop.lsp` explains the expansion, clause by clause. Each pass of a `loop`
does a little more bookkeeping than `do` does, so for simple work such as
adding numbers it takes about twice as long per pass. For the hottest loops over
numbers, use the vector functions (`vector-sum`, `vector-mul`, ...), which
work on a whole vector at once.

**Differences from Common Lisp.** The booleans are `#t` and `#f`, not `t` and
`nil`. Not supported: `for ... and for ...` (stepping in parallel), the
variable `it`, `by` with `in` and `on`, `being the elements of`, type
declarations, `loop-finish`, and multiple values. Clause words are not
case-sensitive in Common Lisp but are here, so write them in lower case.

### Structs

`defstruct` defines a record type with named slots (and its constructor,
accessors, and predicate); `with-struct` makes a struct's slots into
variables for the length of a body. The rows of a table (see
`table-rows`, under "Tables") are structs too.

#### defstruct
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

#### with-struct
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

### Errors and cleanup

`catch-error` catches an error and carries on; `unwind-protect` makes sure
cleanup code runs however a body finishes; `catch` and `throw` jump out of
a computation early; `assert` stops with an error if something that must be
true isn't; `with-sqlite` opens a database and always closes it.

#### catch-error
#### `(catch-error protected-expr (var) handler-body...)`
Evaluates `protected-expr`; if it raises an error, binds `var` to the
error's message (a string) and evaluates `handler-body...` (implicit
`begin`) instead, whose value becomes `catch-error`'s own. If
`protected-expr` succeeds, its value is returned directly and
`handler-body` never runs. Without this, any error — from `error`, or from
a builtin (`sqrt` of a negative number, an out-of-range `vector-ref`, ...)
— propagates all the way to the top and ends the script; this is the only
way Lisp code itself can catch one and keep going. Running out of memory,
or the process being interrupted, isn't caught: those keep propagating
exactly as if this weren't here. To evaluate more than one protected
expression, wrap them in a `begin`.

```lisp
(catch-error (/ 1 0) (e) (display "division failed: ") (display e))
; prints: division failed: /: division by zero

(define (safe-sqrt x)
  (catch-error (sqrt x) (e) -1))     ; -1 instead of crashing on a negative x
(safe-sqrt -4)                       ; => -1
(safe-sqrt 16)                       ; => 4.0
```

#### unwind-protect
#### `(unwind-protect protected-expr cleanup-expr...)`
Evaluates `protected-expr` and returns its value, but always runs the
`cleanup-expr`s afterwards, however `protected-expr` finishes: normally,
with an error, or by a `throw` (see `catch`, below). An error still
carries on after the cleanup runs; `unwind-protect` doesn't catch it, it
only makes sure the cleanup happens. Use it to release something that
must not be left behind, such as an open database connection or a
redirected output file. (`with-sqlite`, below, is built on it.) To protect more than one expression, wrap them in a `begin`.

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

#### catch throw
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

#### assert
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

#### with-sqlite
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

### Quoting

`quote` gives an expression as data, unevaluated; `quasiquote` does the
same with holes to fill in — the usual way to build code in a macro.

#### quote
#### `(quote expr)`
Returns `expr` completely unevaluated, as literal data. `'expr` is reader
sugar for this.

```lisp
(quote (a b c))                ; => (a b c)
'(a b c)                       ; => (a b c) -- the common way to write it
```

#### quasiquote
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

### Macros

`defmacro` defines a macro: a procedure that is given the code it was
called with and returns new code to run in its place.

#### defmacro
#### `(defmacro name (params...) body...)`
Defines `name` as a macro — see "Macros", below, for the full explanation.
`params` supports the same fixed/dotted/bare-symbol shapes `lambda` does,
plus `&key` — see "Keyword arguments", below. Returns `name`.

```lisp
(defmacro my-unless (test then) `(if (not ,test) ,then '()))
(my-unless (> 1 2) 'shown)     ; => shown -- see "Macros" for why this needs
                                ;    to be a macro, not a plain function
```

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

**A macro call is expanded once.** The first time a call such as
`(when (> x 0) ...)` is evaluated, the macro runs and produces the code, and
that code is remembered for that call. Every later evaluation of the same
call — the next time the function it's in is called, or the next time round a
loop — uses the remembered code, without running the macro again. A big macro
such as `loop` takes milliseconds to expand, so without this, a `loop` in a
function called 10,000 times would spend most of its time expanding. (The
`case` macro used to cost about nine times a hand-written `cond` for the same
reason.) Things to know:

- The macro sees only its arguments, and the expansion is the same each time,
  as it is in Common Lisp. A macro that also reads a global variable while
  it expands, or counts how often it's expanded, is expanded once, with
  whatever it found the first time.
- Redefining the macro with `defmacro` makes every existing call expand
  again, with the new definition. Redefining a *function* that the macro's
  body calls doesn't: the calls already in your functions keep their old
  expansions, until you `define` the function that contains the call again.
- `macroexpand` and `macroexpand-1` always expand afresh. `(verbose 3)`
  logs an expansion when it's made: the first time the call is evaluated.
- Two calls that only look alike are separate. Code you build and run with
  `eval` is a new list each time, so it's expanded each time.

A macro's own body, while it's still computing an expansion, is evaluated
by an ordinary (recursive) Python function call, not the fully
tail-call-optimized evaluator loop — so a transformer that itself did deep
non-tail recursion while *building* its expansion would be bounded by
Python's own recursion limit. This essentially never matters in practice
(a transformer builds a piece of code; it doesn't loop over runtime data),
and it does NOT affect the code a macro expands *to* — once the expansion
is produced, it's evaluated by the ordinary trampoline, tail calls and all
(see "Tail calls", at the start of "Special forms and standard macros").

### Debugging

`breakpoint` stops the program where it appears and opens the debug REPL;
`backtrace` shows the calls in progress. The debugging functions (`break`,
`set-debug-hook!`, `locals`, ...) are in "Debugging", under "Built-in
functions".

#### breakpoint
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

#### backtrace
#### `(backtrace)`
Prints the chain of procedure calls in progress right now, without needing
an error — see "Verbose mode and stack traces", under "Introspection /
debugging", below. Returns `'()`.

#### pretty-print-function, pretty-print-macro
#### `(pretty-print-function name)`, `(pretty-print-macro name)`
Print the definition of the procedure or macro called `name`, one element
per line. See "Introspection / debugging", under "Built-in functions".

---

## Built-in functions

### Arithmetic

All arithmetic functions reject non-numeric arguments (including booleans,
which Python treats as a subtype of `int` but this interpreter does not)
with `LispError: not a number: ...`, except where noted.

**Arithmetic on vectors.** `+`, `-`, `*`, `/`, `quotient`, `remainder`,
`mod`, `expt`, `pow`, `min`, `max`, `abs`, `sqrt`, `log`, `exp`, `floor`,
`ceiling`, `round`, `truncate`, and the comparisons `=`, `<`, `>`, `<=`,
`>=` all work on vectors too: when an argument is a vector, the work is
done element by element, with numpy, and a single number is used with
every element. The vectors must all be the same length. A comparison gives
a *mask*, a vector of 1 (true) and 0 (false), which `vector-select`,
`vector-where`, and `table-filter` use to pick elements or rows (see
"Vector math and statistics"). Dividing a vector by zero gives infinity or
NaN rather than an error, and a missing value (NaN) stays missing.

```lisp
(define balance #(1000 2000 3000))
(* balance 0.01)               ; => #(10.0 20.0 30.0)
(- balance #(100 200 300))     ; => #(900 1800 2700)
(max (- balance 1500) 0)       ; => #(0 500 1500)  -- never below 0
(> balance 1500)               ; => #(0 1 1)
(< 1500 balance 2500)          ; => #(0 1 0)  -- a mask for "between"
(vector-select balance (> balance 1500))   ; => #(2000 3000)
(sqrt #(4 9))                  ; => #(2.0 3.0)
```

This is far faster than a Lisp loop over `vector-ref`: pricing 1,000
paths of 360 monthly cashflows takes a few hundredths of a second as
vector arithmetic, and about ten seconds as a loop. The vector math
builtins (`vector-add`, `vector<`, ...) do the same things under their
own names.

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

#### `(quotient a b)`, `(remainder a b)`, `(mod a b)`
`quotient` divides and truncates toward zero, so `(quotient -7 2)` is `-3`,
not `-4`. `remainder` is what's left over: `a - b * (quotient a b)`, which
has the sign of `a`. `mod` is `a` modulo `b`, which has the sign of `b`.
The two differ only when `a` and `b` have different signs. Whole numbers
give exact results, however large they are. Dividing by zero is an error.

```lisp
(quotient 7 2)                 ; => 3
(quotient -7 2)                ; => -3   -- truncated toward zero
(remainder -7 2)               ; => -1   -- the sign of a
(mod -7 2)                     ; => 1    -- the sign of b
(mod 7 3)                      ; => 1
(remainder 7.5 2)              ; => 1.5
```

#### `(even? n)`, `(odd? n)`, `(zero? x)`, `(positive? x)`, `(negative? x)`
Tests of a number. `even?` and `odd?` need a whole number (`4` or
`4.0`); a negative one is even or odd as its absolute value is.

```lisp
(even? 4)                      ; => #t
(odd? -3)                      ; => #t
(zero? 0.0)                    ; => #t
(positive? -2)                 ; => #f
(negative? -2)                 ; => #t
```

#### `(gcd a b ...)`, `(lcm a b ...)`
The greatest common divisor and least common multiple of whole numbers.

```lisp
(gcd 12 18)                    ; => 6
(lcm 4 6)                      ; => 12
```

#### `(abs x)`
Absolute value.

```lisp
(abs -5)                       ; => 5
```

#### `(signum x)`
-1, 0, or 1, as `x` is negative, zero, or positive — a floating-point
number if `x` is one. For a vector, of each element.

```lisp
(signum -2.5)                  ; => -1.0
(signum 7)                     ; => 1
(signum #(-3 0 2))             ; => #(-1 0 1)
```

#### `(min a b ...)`, `(max a b ...)`
Minimum / maximum of the given arguments (at least one required). With
vectors, the smallest or largest *at each position*, so `(max v 0)`
replaces every negative element of `v` with 0. For the smallest or largest
element of one vector, use `vector-min` or `vector-max`.

```lisp
(min 3 1 4 1 5)                ; => 1
(max 3 1 4 1 5)                ; => 5
(max #(-1 2 -3) 0)             ; => #(0 2 0)
```

#### `(sqrt x)`
Square root. The square root of a negative number is an error (for a
vector, it's NaN).

```lisp
(sqrt 16)                      ; => 4.0
(sqrt #(4 9))                  ; => #(2.0 3.0)
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
from: `N(x) = 0.5 * (1 + erf(x / sqrt(2)))`, which is `normal-cdf`, under
"Option prices", in the [library manual](lisp_library_reference.md#option-prices). For a vector, of each element.

```lisp
(erf 0)                        ; => 0.0
```

#### `(floor x)`, `(ceiling x)`, `(round x)`, `(truncate x)`
Standard rounding. `round` uses banker's rounding (round-half-to-even) for
exact ties, matching Python's built-in `round`. For a vector, the results
are whole numbers, stored as integers unless some elements are missing
(NaN); `vector-round` rounds to a number of decimal places.

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
and `2<3`. With 0 or 1 arguments, always `#t`. `#t` or `#f` is an error —
they aren't numbers; to test for one, use `eq?`. With a vector, the
comparison is made element by element and gives a mask, a vector of 1 and
0 (see "Arithmetic on vectors", above). To ask whether two whole vectors
are the same, use `equal?`.

```lisp
(< 1 2 3)                      ; => #t
(< 1 3 2)                      ; => #f -- 3<2 fails
(= #(1 2 3) #(1 0 3))          ; => #(1 0 1)
(= #("CA" "NY" "CA") "CA")     ; => #(1 0 1) -- text too, element by element
(equal? #(1 2 3) #(1 0 3))     ; => #f
```

#### `(not x)`
`#t` if `x` is `#f`; `#f` for everything else (including `0` and `'()`).

```lisp
(not #f)                       ; => #t
(not 0)                        ; => #f -- 0 is truthy here
```

#### `(eq? a b)`, `(equal? a b)`
Both are value equality here — this interpreter does **not** give `eq?`
Scheme's usual identity-only semantics. `(eq? '(1 2) (list 1 2))` is `#t`
here, where in most Schemes it would be `#f`. For most purposes the two are
interchangeable in this interpreter.

`equal?` compares lists element by element, in a loop, so lists of any
length can be compared, and structs slot by slot. Numbers are equal if
they have the same value, so `(equal? 1 1.0)` is `#t`. `#t` and `#f` are
equal only to themselves: Python, underneath, counts them as the numbers
1 and 0, but here `(equal? #f 0)` is `#f`. And a string is never equal to
a symbol, even one with the same name. `member`, `assoc`, `case`, and the
sequence functions (`remove`, `count`, `position`, ...) compare the same
way.

```lisp
(eq? '(1 2) (list 1 2))        ; => #t
(equal? "abc" "abc")           ; => #t
(equal? #f 0)                  ; => #f
(equal? "a" 'a)                ; => #f
(equal? '(1 #f) (list 1 #f))   ; => #t
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
`#t` for any fitted regression model — see "Regression models", in the [library manual](lisp_library_reference.md#regression-models).

#### `(struct? x)`
`#t` for an instance of any `defstruct`-defined type — see "Structs",
below.

#### `(sqlite-connection? x)`, `(sqlite-cursor? x)`
`#t` for a connection returned by `sqlite-open`, or a cursor returned by
`sqlite-execute`, respectively — see "SQLite", in the [library manual](lisp_library_reference.md#sqlite).

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

#### `(cadr x)`, `(caar x)`, `(cddr x)`, ... `(cddddr x)`
`car` and `cdr` combined, as in Common Lisp: the letters between `c` and
`r` say which to take, read right to left, so `(cadr x)` is
`(car (cdr x))` — the second element of a list — and `(caddr x)` is the
third. Every combination of two to four `a`s and `d`s exists. Asking for a
part that isn't there is an error that says so.

```lisp
(cadr '(1 2 3))                ; => 2
(caddr '(1 2 3))               ; => 3
(cddr '(1 2 3))                ; => (3)
(caar '((a b) c))              ; => a
(map cadr '((x 1) (y 2)))      ; => (1 2)
```

#### `(first l)`, `(second l)`, `(third l)`, `(fourth l)`, `(rest l)`
The first to fourth elements of a list, and the list without its first
element: the same as `car`, `cadr`, `caddr`, `cadddr`, and `cdr`, with
names that say what they are.

```lisp
(second '(a b c))              ; => b
(rest '(a b c))                ; => (b c)
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

**Lists, vectors, and strings.** `length`, `reverse`, `append`, `map`,
`filter`, `reduce`, `apply`, and `sort` also work on vectors, and
`length`, `reverse`, and `append` on strings; each gives back the same kind
of thing it was given. The functions that only make sense for a list —
`car`, `list-ref`, `member`, `assoc`, and the rest — say so when given
anything else, rather than treating it as an empty list:
`(member 2 #(1 2))` is the error `member: expected a list, got #(1 2)`.

#### `(append l1 l2 ... ln)`
Concatenates any number of lists (all but the last are copied; the last is
reused as-is for the tail, and can be any value, as in Common Lisp).
`(append)` returns `'()`. Given only vectors, joins them into a new
vector; given only strings, into a new string.

```lisp
(append (list 1 2) (list 3 4)) ; => (1 2 3 4)
(append #(1 2) #(3))           ; => #(1 2 3)
(append "ab" "cd")             ; => "abcd"
```

#### `(reverse l)`
Returns a new list with `l`'s elements in reverse order — or, for a vector
or a string, a new vector or string.

```lisp
(reverse (list 1 2 3))         ; => (3 2 1)
(reverse #(1 2 3))             ; => #(3 2 1)
(reverse "abc")                ; => "cba"
```

#### `(length l)`
Number of elements in a proper list or a vector, or the number of
characters in a string. Anything else, including a dotted list such as
`(1 2 . 3)`, is an error.

```lisp
(length (list 1 2 3))          ; => 3
(length #(1 2 3))              ; => 3
(length "abcd")                ; => 4
```

#### `(list-ref l n)`
The `n`-th element (0-based). Raises `LispError: list-ref: index N out of
range (0..M)` if `n` is out of bounds.

```lisp
(list-ref (list 10 20 30) 1)   ; => 20
```

#### `(list-tail l n)`
The sublist of `l` starting at position `n` (0-based) — i.e. `l` with its
first `n` elements dropped: `l`'s own pairs, not a copy. `(list-tail l 0)` is `l` itself;
`(list-tail l (length l))` is `'()`. Raises `LispError` if `n` is out of
range.

```lisp
(list-tail (list 1 2 3 4 5) 2) ; => (3 4 5)
```

#### `(last l [n])`, `(butlast l [n])`
As in Common Lisp: `last` is the end of the list — its last `n` elements
(1 unless given), as a list, so `(car (last l))` is the last element.
`butlast` is a new list of all but the last `n` elements.

```lisp
(last (list 1 2 3))            ; => (3)
(car (last (list 1 2 3)))      ; => 3
(last (list 1 2 3) 2)          ; => (2 3)
(butlast (list 1 2 3))         ; => (1 2)
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
The sublist of `l` starting at the first element `equal?` to `x` — `l`'s
own pairs, not a copy — or `#f` (not `'()`, same reasoning as `assoc`) if
none match.

```lisp
(member 3 (list 1 2 3 4 5))    ; => (3 4 5)
(member 99 (list 1 2 3))       ; => #f
```

#### `(map f l ...)`
Applies `f` to each element of `l` in order, returning a new list of the
results. For a vector, returns a new vector (as `vector-map` does). Given
several lists (or several vectors), `f` gets one element from each, in
step, and the result stops at the end of the shortest. For arithmetic on
every element, `(* v 2)` is simpler and much faster than
`(map (lambda (x) (* x 2)) v)`.

```lisp
(map (lambda (x) (* x x)) (list 1 2 3))    ; => (1 4 9)
(map (lambda (x) (* x x)) #(1 2 3))        ; => #(1 4 9)
(map + (list 1 2 3) (list 10 20))          ; => (11 22)
(map list (list 1 2) (list 'a 'b))         ; => ((1 a) (2 b))
```

#### `(filter f l)`
Returns a new list of just the elements of `l` for which `(f x)` is true —
or, for a vector, a new vector.

```lisp
(filter (lambda (x) (> x 2)) (list 1 2 3 4))   ; => (3 4)
(filter (lambda (x) (> x 2)) #(1 2 3 4))       ; => #(3 4)
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
Left fold, over a list or a vector. With `init` given, starts the
accumulator there and folds `f` over every element of `l`; without it,
uses `l`'s first element as the initial accumulator and folds over the rest
(an empty `l` with no `init` has no first element to start from, and raises
an error).

```lisp
(reduce + (list 1 2 3 4))      ; => 10
(reduce + (list 1 2 3 4) 100)  ; => 110
(reduce max #(3 9 4))          ; => 9
```

The functions below are Common Lisp's. Each takes a list or a vector
(`seq`), and those that return a sequence return the same kind. Elements
are compared with `equal?`.

#### `(remove item seq)`, `(remove-if f seq)`
`seq` without the elements equal to `item`; and without the elements `x`
for which `(f x)` is true — the opposite of `filter`.

```lisp
(remove 2 (list 1 2 3 2))       ; => (1 3)
(remove-if odd? #(1 2 3 4))     ; => #(2 4)
```

#### `(count item seq)`, `(count-if f seq)`
How many elements are equal to `item`; how many make `(f x)` true.

```lisp
(count "CA" (list "CA" "NY" "CA"))   ; => 2
(count-if even? #(1 2 4))            ; => 2
```

#### `(find-if f seq)`, `(position item seq)`, `(position-if f seq)`
The first element `x` for which `(f x)` is true; the index (from 0) of the
first element equal to `item`; the index of the first for which `(f x)` is
true. Each is `#f` if there's none.

```lisp
(find-if even? (list 1 4 6))         ; => 4
(position 'c (list 'a 'b 'c))        ; => 2
(position-if string? (list 1 "a"))   ; => 1
(position 9 (list 1 2))              ; => #f
```

#### `(some f seq ...)`, `(every f seq ...)`
Whether `(f x)` is true for some element: the first true value it returns,
or `#f`. Whether it's true for every element: `#t` or `#f` (`#t` for no
elements). Given several sequences, `f` takes an element of each, in step,
as with `map`.

```lisp
(some (lambda (x) (and (> x 2) (* x 10))) (list 1 3 5))   ; => 30
(every odd? (list 1 3 5))                                 ; => #t
(some = (list 1 2) (list 3 2))                            ; => #t
```

#### `(remove-duplicates seq)`
`seq` with each element once, where it first appears.

```lisp
(remove-duplicates (list "CA" "NY" "CA" "TX"))   ; => ("CA" "NY" "TX")
```

#### `(union a b)`, `(intersection a b)`, `(set-difference a b)`
The elements in `a` or `b`; in both; in `a` but not `b`. Each element is
there once, in the order it first appears (in `a`, then `b`).

```lisp
(union (list 1 2) (list 2 3))              ; => (1 2 3)
(intersection (list 1 2 3) (list 3 2 5))   ; => (2 3)
(set-difference (list 1 2 3) (list 2))     ; => (1 3)
```

#### `(append-map f seq ...)`
The lists `(f x)` returns, for each element `x`, appended into one.

```lisp
(append-map (lambda (x) (list x x)) (list 1 2))   ; => (1 1 2 2)
```

#### `(for-each f seq ...)`
Calls `(f x)` for each element, for what it does; returns `'()`. (`dolist`
does the same with the body written in place.)

```lisp
(for-each print (list "a" "b"))   ; prints a, then b
```

#### `(iota count [start step])`
A list of `count` numbers, from `start` (0 unless given) by `step` (1
unless given).

```lisp
(iota 4)                        ; => (0 1 2 3)
(iota 3 1)                      ; => (1 2 3)
(iota 3 0 5)                    ; => (0 5 10)
```

#### `(apply f arg1 arg2 ... args)`
Calls `f` with `arg1`, `arg2`, ... as individual leading arguments,
followed by the *elements* of the final argument `args` (a list).
`(apply f lst)` — no leading arguments — is the common case: spreading a
list (or a vector) into positional arguments, e.g. `(apply + (list 1 2 3))` is `6`, and
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
silently corrupt the table), and not `#t` or `#f` (which Python would
treat as the keys 1 and 0). Using one anyway is an error.

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

#### `(hash-table-copy h)`
A new hash table with `h`'s keys and values; changing one doesn't change
the other. (The values themselves aren't copied.)

#### `(hash-table-update! h key f [default])`
Sets `key`'s value to `(f value)`, where `value` is its value now — or
`default` if it has none (an error, without a default). Returns the new
value. The way to count things:

```lisp
(define counts (make-hash-table))
(dolist (state (list "CA" "NY" "CA"))
  (hash-table-update! counts state (lambda (n) (+ n 1)) 0))
(hash-table-ref counts "CA")                                   ; => 2
(hash-table-update! counts "NY" (lambda (n) (* n 10)))         ; => 10
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
Parses `s` as a whole number if it is one, otherwise as a floating-point
number (`"3.14"`, `"1e6"`). Spaces around it are ignored. An error if `s`
isn't a number: `string->number: "abc" isn't a number`.

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

#### `(string-starts-with? s prefix)`, `(string-ends-with? s suffix)`
`#t` if `s` begins with `prefix`, or ends with `suffix`.

```lisp
(string-starts-with? "SPY 251017C" "SPY")    ; => #t
(string-ends-with? "report.csv" ".csv")      ; => #t
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

#### `(string-join items [separator])`
The strings in a list or vector joined into one, with `separator` (a
space, unless given) between them. An item that isn't a string is joined
as `display` shows it, so a list of symbols makes a sentence.

```lisp
(string-join (list "a" "b" "c") ", ")   ; => "a, b, c"
(string-join '(i am 42))                ; => "i am 42"
```

### Regular expressions

(In `lisp_regex.py`.) Searching, matching, replacing, and splitting text
with regular expressions — a thin layer over Python's `re` module, so the
patterns are Python's (see https://docs.python.org/3/library/re.html). A
backslash in a pattern can be written as it is: `"\d+"` is the pattern
`\d+` (one or more digits). Flags go at the start of the pattern: `(?i)`
to ignore case, `(?m)` for `^` and `$` to match at every line.

A **match** is a list: the text that matched, then the text of each group
(each part of the pattern in parentheses), or `'()` for a group that took
no part in the match. No match is `#f`, so a search can be the test of an
`if`.

#### `(regex-search pattern s)`
The first match of `pattern` anywhere in `s`.

```lisp
(regex-search "(\d+)-(\d+)" "pages 12-34 and 56-78")   ; => ("12-34" "12" "34")
(regex-search "x(y)?z" "xz")                            ; => ("xz" ())
(regex-search "\d+" "no digits")                        ; => #f
(regex-search "(?i)hello" "Say HELLO")                  ; => ("HELLO")
```

#### `(regex-match pattern s)`
A match of `pattern` against the whole of `s`, or `#f` — to check that a
string has a form, such as a date.

```lisp
(regex-match "\d{4}-\d{2}-\d{2}" "2026-09-29")          ; => ("2026-09-29")
(regex-match "\d+" "12a")                               ; => #f
```

#### `(regex-find-all pattern s)`
Every match, as a list: the matched texts if the pattern has no groups;
the text of the group, if it has one; or a list of the groups' texts for
each match, if it has several.

```lisp
(regex-find-all "\d+" "a1 b22 c333")                    ; => ("1" "22" "333")
(regex-find-all "(\w)(\d)" "a1 b2")                     ; => (("a" "1") ("b" "2"))
```

#### `(regex-replace pattern s replacement [count])`
`s` with each match of `pattern` replaced — only the first `count`, if
given. The replacement is a string, in which `\1` stands for what the first
group matched (and so on); or a procedure, which is given the match (a
list, as `regex-search` returns) and returns what to put in its place.

```lisp
(regex-replace "\s+" "too   many    spaces" " ")         ; => "too many spaces"
(regex-replace "(\w+)@(\w+)" "joe@example" "\2 at \1")  ; => "example at joe"
(regex-replace "\d+" "a1 b22" (lambda (m) (* 2 (string->number (car m)))))   ; => "a2 b44"
```

#### `(regex-split pattern s)`
The pieces of `s` between the matches of `pattern`.

```lisp
(regex-split "[,;]\s*" "a, b;c")                         ; => ("a" "b" "c")
```

#### `(regex-quote s)`
`s` with every character that has a special meaning in a pattern
backslashed, so a pattern made from it matches `s` exactly — for text
that comes from data.

```lisp
(regex-search (regex-quote "3.5+x") "y = 3.5+x")         ; => ("3.5+x")
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
`format()`, and the same one `display-table`'s formats use (see
"Displaying tables"). A spec is made of these parts, each optional, in
this order:

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
`template.lsp`'s `template-render` (see its header comment, and "SQLite", in the [library manual](lisp_library_reference.md#sqlite),
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
`LispError: not a number, string, or date: ...`. `vector-ref` and
`vector-set!` check their index: it must be a whole number from 0 to the
length minus 1, or it's an error such as
`vector-ref: index 5 is out of range -- the vector has 3 elements`.

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

**The ordinary operators work on vectors too.** `(* balance 0.01)` is the
same as `(vector-mul balance 0.01)`, and `(> balance 1500)` the same as
`(vector> balance 1500)` — see "Arithmetic on vectors", under
"Arithmetic". The `vector-` names below do the same thing, for two
arguments.

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

#### `(vector-drawdowns dates values percent)`
Each time `values` fell more than `percent` percent (e.g. `10` or `20`)
below their previous high — a market's or a portfolio's drawdowns.
`dates` and `values` are vectors of the same length, oldest first; the
values must be above 0, and missing ones are skipped. The result is a
table (in `lisp_tables.py`) with a row per drop:

| Column | What it is |
|---|---|
| `peak-date`, `peak` | the high the values fell from |
| `below-date` | the first date they were more than `percent` below it |
| `trough-date`, `trough` | the lowest point before they got back to the high |
| `drop-pct` | how far the trough is below the high, in percent |
| `recovery-date` | the first date they were back at the high or above; `'()` if they haven't been yet |

A drop is counted once: it lasts until the values get back to the high,
and only after that can the next one begin, from a new high.

```lisp
(define d (vector (date 2020 1 1) (date 2020 1 2) (date 2020 1 3) (date 2020 1 4)
                  (date 2020 1 5) (date 2020 1 6) (date 2020 1 7) (date 2020 1 8)))
(display-table (vector-drawdowns d #(100 95 85 88 80 101 120 100) 10))
; peak-date    peak  below-date  trough-date  trough   drop-pct  recovery-date
; ----------  -----  ----------  -----------  ------  ---------  -------------
; 2020-01-01  100.0  2020-01-03  2020-01-05     80.0       20.0  2020-01-06
; 2020-01-07  120.0  2020-01-08  2020-01-08    100.0  16.666666
```

With prices from FRED, say the S&P 500's 20% drops:

```lisp
(define sp (fred-table creds "SP500"))
(display-table (vector-drawdowns (table-column sp "date") (table-column sp "SP500") 20))
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
`http-get-csv`, `series-table`, and `tastytrade-option-chain` return, and
what `display-table` and `write-columns-csv` accept. There's no separate table type, so a table is
ordinary Lisp data: `(car t)` is its first column, and `(cdr (car t))`
that column's vector.

The functions below select, filter, sort, group, join, and summarize
tables. Each returns a **new** table and leaves its argument unchanged.
They work on whole columns with numpy, so tables of millions of rows are
practical. Column names are strings; where a function takes several, pass
a list — `(list "state" "month")` — or just one name by itself.

To look at a table, use `(display-table t)` — a text table in the
console, the Table tab in the GUI, and a rendered table in Jupyter — with
a format for each column's numbers, if you like (see "Displaying
tables"). To work with it a row at a time, see "Rows", below.

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

#### `(with-columns (column...) table body...)`
Evaluates `table` once, binds a variable to each column listed, and
evaluates the `body` forms, returning the last one's value. It saves
writing `(table-column t "...")` for each column a calculation uses, as
Common Lisp's `with-slots` does for an object's slots. Each column is
written as either:

- `name`: a variable called `name`, for the column of the same name. A
  name keeps its case, so `SP500` is the column `"SP500"`.
- `(variable "column")`: a variable called `variable`, for the column
  `"column"`. Use it when the column's name would hide a function the
  body calls, or can't be a variable at all, such as `"2024"` or a name
  with spaces.

**Watch out for `date`.** Variables and functions share one namespace, so
a variable named `date` hides the `date` function inside the body:
`(date 2024 1 3)` there fails with "not a procedure". Nearly every dated
table has a `date` column, so give it another name, as in
`((day "date") close)` below. Other column names that are also functions
include `last` (in `schwab-quotes`), and `count`, `min`, and `max` (in
`table-describe`).

```lisp
(define loans (make-table "balance" #(100 90 200 195 50)
                          "rate"    #(6.0 6.0 4.5 4.5 7.25)))
(with-columns (balance rate) loans
  (vector-weighted-mean rate balance))               ; => 5.165354330708661

(define prices (make-table "date"  (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4))
                           "close" #(100 104 102)))
(with-columns ((day "date") close) prices
  (vector-select close (>= day (date 2024 1 3))))    ; => #(104 102)
```

It's a standard macro (in `macros_init.lsp`). The last example becomes
this `let`, as `macroexpand-1` shows:

```
(let ((%with-columns-table-1 prices))
  (let ((day (table-column %with-columns-table-1 "date"))
        (close (table-column %with-columns-table-1 "close")))
    (vector-select close (>= day (date 2024 1 3)))))
```

- The variables exist only in the body, as with `let`.
- They're the table's own vectors, as `table-column` gives them, not
  copies: `vector-set!` on one changes the table. `set!` changes only the
  variable.
- A column that isn't in the table is an error that lists the table's
  columns.
- To work one row at a time, `with-struct` makes each of a row's values a
  variable (see "Rows", below).

**Rows.** A table is stored as columns, which suits formulas that work on
whole columns: `(* (table-column t "balance") 0.01)`. Some data is better
seen one row at a time — each option in an option chain is a thing of its
own. `table-rows` gives the rows of a table, each as a **row**: a struct
(see "Structs") whose slots are the table's columns. `row-ref` reads one
value from a row, `with-struct` makes each column a variable, `filter`
keeps the rows you want, and `display-table` shows a list of rows as a
table. `table-from-rows` makes a table from rows again. So you can use
whichever view suits the question:

```lisp
(define options
  (make-table "symbol" (vector "SPY C660" "SPY C670" "SPY P650" "SPY P640")
              "type"   (vector "Call" "Call" "Put" "Put")
              "strike" #(660 670 650 640)
              "iv"     #(0.18 0.17 0.23 0.26)
              "price"  #(12.40 7.25 6.80 0.95)))

; Whole columns at once: the options with implied volatility over 20%.
(table-column (table-filter options (> (table-column options "iv") 0.2)) "symbol")
                                   ; => #("SPY P650" "SPY P640")

; One row at a time: the same question, asked of each option.
(define (volatile? option)
  (with-struct option (> iv 0.2)))
(map (lambda (option) (row-ref option "symbol"))
     (filter volatile? (table-rows options)))     ; => ("SPY P650" "SPY P640")

(display-table (filter volatile? (table-rows options))
               '(("strike" ",.2f") ("iv" ".1%") ("price" ",.2f")))
```

The last line prints

```
symbol    type  strike     iv  price
--------  ----  ------  -----  -----
SPY P650  Put   650.00  23.0%   6.80
SPY P640  Put   640.00  26.0%   0.95
```

A row has one variable for each column, so in `with-struct` a column name
hides a procedure of the same name for the length of its body (a column
called `list` would hide `list`). `row-ref` works with any column name,
including one with a space in it.

#### `(table-rows t)`
The table's rows, in order, as a list of rows (see "Rows", above). A row
prints as `#S(row :name value ...)`.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(table-rows t)                    ; => (#S(row :id "a" :balance 100) #S(row :id "b" :balance 90))
```

#### `(table-row t i)`
Row `i` (counting from 0), as a row.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(table-row t 1)                   ; => #S(row :id "b" :balance 90)
(with-struct (table-row t 1) (list id balance))   ; => ("b" 90)
```

#### `(row-ref row name)`
The value in the row's column called `name`, a string or a symbol. An
error if the row has no such column (the message lists the columns it
has).

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(row-ref (table-row t 0) "balance")   ; => 100
```

#### `(table-from-rows rows [names])`
A table made from a list of rows. Each row is a row from `table-rows` or
`table-row` (or any struct), whose slots become the columns; given
`names`, just those columns, in that order. Or each row is a hash table —
such as a JSON object becomes, from `http-get-json` or `tastytrade-get` —
whose keys become the columns, in the order they first appear (a row
without a key is missing it); a key whose values include a hash table or
a list is left out, since a table can't hold those, and `#t`/`#f` become
1 and 0. Or each row is a list of values, one per column, and `names`
gives the columns' names. Each column is read the way `load-csv` reads
one: a column of numbers holds NaN where a row has `'()`, and a column of
`YYYY-MM-DD` strings becomes dates.

```lisp
(define t (make-table "id" (vector "a" "b") "balance" #(100 90)))
(table-from-rows (reverse (table-rows t)))    ; => (("id" . #("b" "a")) ("balance" . #(90 100)))
(table-from-rows (list (list "x" 1) (list "y" '())) (list "name" "n"))
                                              ; => (("name" . #("x" "y")) ("n" . #(1.0 nan)))
```

#### `(table-head t [n])`, `(table-tail t [n])`, `(table-slice t start [end])`
The first `n` rows (default 10); the last `n` rows (default 10), such as
the latest months of a time series; and the rows from `start` up to, but
not including, `end` (default: to the end).

```lisp
(define t (make-table "x" #(10 20 30 40)))
(table-head t 2)                  ; => (("x" . #(10 20)))
(table-tail t 2)                  ; => (("x" . #(30 40)))
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

#### `(table-where t column value [:key f] [:test predicate])`
Just the rows whose `column` holds `value`, or, if `value` is a list, any
of its values. It's the same as `table-filter` with an `=` mask, for the
commonest filter. Values match as `equal?` matches them: text, numbers,
and dates. To match some other way — ignoring case, say — give `:key` or
`:test` (see "Matching with `:key` and `:test`", below). `:key` is applied
to `value` as well as to the cells.

```lisp
(define t (make-table "state" (vector "CA" "NY" "TX") "balance" #(100 200 50)))
(table-where t "state" "NY")                ; => (("state" . #("NY")) ("balance" . #(200)))
(table-where t "state" (list "CA" "TX"))    ; => (("state" . #("CA" "TX")) ("balance" . #(100 50)))
(table-where t "state" "ny" :key string-downcase)   ; => (("state" . #("NY")) ("balance" . #(200)))
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

#### `(table-group-by t keys aggregations [:key f] [:test predicate])`
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
| `(new-name 'weighted-median column weight-column)` | the middle value by weight: the smallest value at which the running total of weight, from the smallest value up, reaches half the group's weight |
| `(new-name '(percentile p) column)` | the `p`th percentile (`p` from 0 to 100), interpolated between values, as a spreadsheet's does — the 50th is the median |
| `(new-name '(weighted-percentile p) column weight-column)` | the smallest value at which the running total of weight reaches `p`% of the group's weight |
| `(new-name 'mode column)`, `(new-name 'weighted-mode column weight-column)` | the most common value, or the value with the most weight (a tie goes to the smallest value); works on strings and dates too |
| `(new-name 'representative column)` | the group's first value (in the table's order) that isn't missing — a value that stands for the group, for a column such as a state, which can't be added or averaged |
| `(new-name 'first column)`, `(new-name 'last column)` | the value in the group's first or last row, in the table's order |

Missing values are skipped. The function name can also be a string, e.g.
`"sum"`. `stratify` uses the same functions (see "Stratification
tables").

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

To group values that differ only in case, say, give `:key` or `:test` (see
"Matching with `:key` and `:test`", below). With `:key`, the key columns
show what `f` made of each group's values — `"a"` for `"A"` and `"a"`, with
`string-downcase`. With `:test`, a group shows its first key value in sorted
order, and each value joins the first earlier group it matches.

```lisp
(define names (make-table "n" (vector "b" "A" "a") "v" #(1 2 3)))
(table-group-by names "n" (list (list "total" 'sum "v")) :key string-downcase)   ; => (("n" . #("a" "b")) ("total" . #(5 1)))
```

#### `(table-join left right keys [how] [:key f] [:test predicate])`
Combine the rows of two tables whose key column(s) match. Each output row
is a row of `left` followed by the other columns of the matching `right`
row. `how` is:

- `'inner` (the default) — keep only the `left` rows that have a match;
- `'left` — keep every `left` row; where there's no match, the `right`
  columns are missing (`nan`, or `'()` for strings and dates).

A `left` row that matches several `right` rows appears once for each. The
rows stay in `left`'s order. A `right` column with the same name as a
`left` one gets `_right` added to its name. The typical use is attaching
monthly market data to loan-month rows — see "Monthly time series", in the [library manual](lisp_library_reference.md#monthly-time-series).

```lisp
(define loans (make-table "id" (vector "a" "a" "b") "month" #(1 2 3)))
(define rates (make-table "month" #(1 2) "mortgage_rate" #(6.5 6.25)))
(table-join loans rates "month")   ; => (("id" . #("a" "a")) ("month" . #(1 2)) ("mortgage_rate" . #(6.5 6.25)))
(table-join loans rates "month" 'left)   ; => (("id" . #("a" "a" "b")) ("month" . #(1 2 3)) ("mortgage_rate" . #(6.5 6.25 nan)))
```

Key values match when they are equal. To match some other way — names
that differ in case or punctuation, say — give `:key` or `:test`, below.
The output keeps `left`'s own key values.

#### Matching with `:key` and `:test`
`table-where`, `table-group-by`, and `table-join` match values that are
equal. Each takes two optional keyword arguments, as in Common Lisp, to
match them some other way:

- `:key f` — a procedure of one value, applied to every value before they
  are compared; values that are equal afterward match. In `table-join` it is
  applied to both tables' key columns, in `table-where` to `value` and to
  the column, and in `table-group-by` to the key columns. `f` must return a
  number, a string, or a date (or `'()`, which is missing).
- `:test p` — a procedure of two values that says whether they match: in
  `table-join` it is given a `left` value and a `right` value, in
  `table-where` `value` and then a cell, and in `table-group-by` an earlier
  group's value and a later one's. Use it for matching that isn't "equal
  after changing each value", such as numbers within a tolerance.

Give both and `p` is given what `f` made of the values. A missing value is
never given to `f` or `p`: it matches only another missing value, as it
does without them. With several key columns, every one must match; `p` is
applied to each column in turn.

**Prefer `:key`.** `f` is applied once to each distinct value, and the
matching is still done a column at a time with numpy, so a join of a
500-row table to one of 10,000 distinct names takes about 0.01 seconds.
`p` can only be applied to *pairs* of distinct values — 5,000,000 of them
here — so the same join takes about 18 seconds.

```lisp
(define holdings (make-table "name" (vector "Apple Inc." "Microsoft" "Tesla") "weight" #(7.25 5.8 1.2)))
(define industries (make-table "name" (vector "APPLE INC" "microsoft") "industry" (vector "Tech" "Tech")))
(define (plain name) (string-downcase (regex-replace "[.,]" name "")))   ; ignore case, periods, and commas
(table-join holdings industries "name" :key plain)   ; => (("name" . #("Apple Inc." "Microsoft")) ("weight" . #(7.25 5.8)) ("industry" . #("Tech" "Tech")))
(table-join holdings industries "name" 'left :key plain)   ; => (("name" . #("Apple Inc." "Microsoft" "Tesla")) ("weight" . #(7.25 5.8 1.2)) ("industry" . #("Tech" "Tech" ())))
(table-where holdings "name" "APPLE INC" :key plain)   ; => (("name" . #("Apple Inc.")) ("weight" . #(7.25)))

(define (close? a b) (< (abs (- a b)) 0.05))   ; numbers within 0.05
(table-join (make-table "x" (vector 4.01 5.5)) (make-table "x" (vector 4.0 5.49) "j" #(7 8)) "x" :test close?)   ; => (("x" . #(4.01 5.5)) ("j" . #(7 8)))
```

`table-sort` doesn't take them: it orders values rather than matching them.

#### `(table-describe t)`
A table summarizing each numeric column: how many values are present,
their mean, standard deviation, minimum, 25th percentile (`p25`), median,
75th percentile (`p75`), and maximum. Missing values are skipped; columns
of strings or dates are left out. A quick first look at new data:

```lisp
(table-describe (make-table "id" (vector "a" "b" "c") "balance" #(100 200 300)))   ; => (("column" . #("balance")) ("count" . #(3)) ("mean" . #(200.0)) ("stdev" . #(100.0)) ("min" . #(100.0)) ("p25" . #(150.0)) ("median" . #(200.0)) ("p75" . #(250.0)) ("max" . #(300.0)))
```

### Structs

See `defstruct`, under "Structs" in "Special forms and standard macros", above, for the
type-specific `make-<name>`/`<name>-<slot>`/`<name>-<slot>-set!`/`<name>?`/
`copy-<name>` names it generates. `struct?`, `struct-ref`, `struct-set!`,
and `struct-type-name` work generically on any struct instance, by
slot-name symbol, without needing to know its specific type; `call-method`
(below) is a different kind of generic tool, for the "lambda in a slot"
dispatch pattern struct inheritance enables — see its own entry. To use
*all* of an instance's slots inside a body as plain variables, see
`with-struct`, under "Structs" in "Special forms and standard macros", above
— it's a special form (it needs the struct's runtime slot list to know which
names to bind), so it's documented there rather than here.

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

#### `(date-add-years d n)`
The date `n` years after `d` (or before, if `n` is negative). February 29
becomes February 28 in a year that isn't a leap year. `d` may be a vector
of dates. For months, see `date-add-months`, under "Monthly time series", in the [library manual](lisp_library_reference.md#monthly-time-series).

```lisp
(date-add-years (date 2024 2 29) 1)    ; => 2025-02-28
(date-add-years (date 2024 2 29) 4)    ; => 2028-02-29
```

#### `(days-between d1 d2)`
The actual number of days from `d1` to `d2` (negative if `d2` is earlier).
Either may be a vector of dates. For a day count basis such as 30/360, see
`day-count`, under "Day counts and cash flows", in the [library manual](lisp_library_reference.md#day-counts-and-cash-flows); for whole months,
`months-between`, under "Monthly time series", in the [library manual](lisp_library_reference.md#monthly-time-series).

```lisp
(days-between (date 2024 1 31) (date 2024 3 1))    ; => 30
(days-between (date 2024 1 1) (vector (date 2024 2 1) (date 2025 1 1)))   ; => #(31 366)
```

#### `(date-end-of-month d)`
The last day of `d`'s month. `d` may be a vector of dates.

```lisp
(date-end-of-month (date 2024 2 10))   ; => 2024-02-29
```

#### `(date-day-of-week d)`
The day of the week: 1 for Monday through 7 for Sunday. `d` may be a
vector of dates.

```lisp
(date-day-of-week (date 2026 9 28))    ; => 1
```

### The clock

(In `lisp_clock.py`.) What time it is, and waiting until a later time —
for example, to check something every hour.

A **time** is a list `(year month day hour minute second)`, in local
time, as `current-time` returns it: `(2026 9 28 14 37 5)` is 2:37:05 pm on
September 28, 2026. Wherever a time is expected, the hour, minute, and
second may be left off (they're then 0), and a date means midnight at its
start. Because a time is an ordinary list, `first`, `second`, `fourth`,
and the rest take it apart: `(fourth (current-time))` is the hour.

#### `(current-time)`, `(today)`
The time now, as a list, and today's date.

```lisp
(current-time)                 ; => e.g. (2026 9 28 14 37 5)
(today)                        ; => e.g. 2026-09-28
```

#### `(time-add time seconds)`, `(seconds-between time1 time2)`
`time-add` is the time `seconds` after `time` (before, if it's negative);
an hour is `(* 60 60)` seconds, and a day `(* 60 60 24)`.
`seconds-between` is the number of seconds from `time1` to `time2`.

```lisp
(time-add '(2026 12 31 23 59 30) 45)                       ; => (2027 1 1 0 0 15)
(time-add '(2026 9 28) (* 60 60 36))                       ; => (2026 9 29 12 0 0)
(seconds-between '(2026 9 28 14 0 0) '(2026 9 28 15 30 0))  ; => 5400
```

#### `(time->string time)`
The time as text, for a log or a report.

```lisp
(time->string '(2026 9 28 14 37 5))    ; => "2026-09-28 14:37:05"
```

#### `(next-time hour [minute second])`
The next time the clock will read `hour:minute:second` (on a 24-hour
clock): today, if that's still to come, otherwise tomorrow.

```lisp
(next-time 9 30)               ; => e.g. (2026 9 29 9 30 0), if it's already past 9:30 today
```

#### `(sleep seconds)`, `(sleep-until time)`
`sleep` waits `seconds` (a fraction is fine); `sleep-until` waits until
the clock reaches `time`, and returns at once if it already has. Both
return `'()`. `sleep-until` looks at the clock at least once a minute while
it waits, so it still wakes on time if the computer was asleep in between.

In a **Jupyter notebook** the cell keeps running while it waits, and what
it displays appears as it goes; Kernel → Interrupt stops it. At the
**console**, Ctrl-C stops it. In the **GUI**, the window doesn't respond
while it waits, so use the console or a notebook for this.

**Checking something every hour.** A loop that does the check, then
sleeps until the top of the next hour:

```lisp
; The next time the clock is on the hour.
(define (next-hour)
  (let ((now (current-time)))
    (time-add (list (first now) (second now) (third now) (fourth now) 0 0)
              (* 60 60))))

(define (check-rates)
  (let ((sofr (table-column (fred-table creds "SOFR" :cache-hours 0) "SOFR")))   ; (0: not a saved copy)
    (display (format "{}  SOFR {:.2f}%\n"
                     (time->string (current-time))
                     (vector-ref sofr (- (vector-length sofr) 1))))))

; Every hour, on the hour, for the next 8 hours:
(loop repeat 8
      do (check-rates)
         (sleep-until (next-hour)))
```

For every day at 9:30 am, use `(sleep-until (next-time 9 30))` instead;
for "an hour after this check finished", `(sleep (* 60 60))`.

### Charting

`plot-chart`, `plot-histogram`, `plot-panels`, and `plot-map` build a chart
and hand it to the GUI's chart tab (if it's running), a Jupyter cell (drawn
there), or the console (a plain text summary). Only the most recently
plotted chart is remembered, which is what `save-chart` saves to a file.
`plot-chart` draws any number of series, each with its own X values, as
symbols, lines, bars, or filled areas, and with a line fitted to a series
by regression (`:fit`); `plot-histogram` and `plot-panels` are built on
it. (`plot-map` is under "Maps", in the [library manual](lisp_library_reference.md#maps).)

#### `(plot-chart series [options])`
Several series on one chart, each with its own X values, drawn with any
combination of symbols, a line, bars, and a filled area. `series` is a
list, with one entry for each series:

```text
(list name x y [series options])
```

- `name` is what the legend calls the series.
- `x` and `y` are vectors (or lists) of the same length.
- A point whose X or Y is missing (`'()` or NaN) is left out. A line goes
  from the point before it to the point after it, so a quarterly column in
  a monthly table (NaN in the other months) still draws as a line.

**How the X values line up.** All the series share one X axis, so their
X values must be of one kind:

- **Dates** are placed on a calendar. Monthly, quarterly, and annual series
  line up by date: a quarter dated April 1 sits under the April point of a
  monthly series.
- **Numbers** are placed on a number line, as in a scatter plot.
- **Text** values are categories, such as state names. They are placed
  evenly, in the order they first appear, across all the series. If there
  are more than 6, their labels are slanted.

A series' line connects its points from left to right.

**Series options.** Any combination of these. With none of `:symbol`,
`:line`, `:bars`, and `:fill`, a series is a line.

| Option | Values |
|---|---|
| `:symbol` | a name: `"circle"`, `"square"`, `"triangle"`, `"diamond"`, `"down-triangle"`, `"plus"`, `"x"`, `"star"`, `"dot"`. `#t` means the next one in that order (the first series gets a circle, the second a square, ...). `#f` (the default) means none. |
| `:line` | `#t` (solid), `"solid"`, `"dashed"`, `"dotted"`, `"dash-dot"`, or `#f` (none) |
| `:bars` | `#t` for bars from 0 to each Y: up and down, or across on a horizontal chart. A series with bars can have only one Y for each X. |
| `:fill` | `#t` fills the area between the series and 0 (an area chart). A vector or list of values, one for each X, fills the band between the series and those values: a high–low range, or a confidence band around a fitted line. A point is left out where one of these values is missing. The fill is see-through, so what's behind it shows. |
| `:labels` | `#t` prints each value on the chart: at the end of each bar (in the middle, for stacked bars), or above each point. They're written in the axis's `:y-format`, if it has one. Otherwise, numbers from 100 up are whole numbers with commas, and smaller ones have three significant digits. A format (see `:y-format`) writes them that way. |
| `:color` | any matplotlib color: `"red"`, `"navy"`, `"#1f77b4"`, ... The default is the next color in matplotlib's cycle. The series' symbols, line, bars, and fill are all this color. |
| `:line-width`, `:symbol-size` | this series' own, in place of the chart's |
| `:fit` | `"linear"` draws the straight line fitted to the series by least squares (`linear-regression`); `"lad"`, by least absolute deviation (`lad-regression`), which a few outliers barely move; and `"logistic"` the S-shaped curve of a logistic regression (for Y values between 0 and 1), as a dashed black line named for the series and the fit. The X values must be numbers or dates. For a model with more than one predictor, see `model-report` and `model-predict` |
| `:secondary` | `#t` puts the series on the secondary axis, which has its own scale. That axis is on the right, or at the top of a horizontal chart. Use it for a series whose values are on a very different scale from the others, such as a rate beside amounts in dollars. The legend adds "(right)" or "(top)" to the series' name. |

**Chart options**, after the series:

| Option | Default | What it does |
|---|---|---|
| `:title` | none | The chart's title |
| `:x-label`, `:y-label`, `:secondary-label` | none | Labels for the axis of X values, the axis of Y values, and the secondary axis. On a horizontal chart, they label the same values, which are then on the other sides. |
| `:legend` | `#t` | `#t` shows the series' names wherever they fit best. A place puts them there: `"upper left"`, `"upper right"`, `"lower left"`, `"lower right"`, `"upper center"`, `"lower center"`, `"center left"`, `"center right"`, `"center"`, `"right"`, or `"best"`. `#f` shows no legend. |
| `:bars` | `"grouped"` | How the bars of different series at the same X are arranged: side by side (`"grouped"`, in the order of the series), or on top of one another (`"stacked"`). A stack builds up from 0 with the positive values and down from 0 with the negative ones. |
| `:bar-width` | `0.8` | The share of the room between neighboring X values that the bars at one X take, together |
| `:line-width` | `1.5` | Lines' width, in points |
| `:symbol-size` | `6` | Symbols' size, in points |
| `:grid` | `#t` | Faint grid lines |
| `:horizontal` | `#f` | `#t` turns the chart on its side. The X values go down the side, the first at the top, and the Y values go across. Bars go across, which leaves room for many bars and long category names. |
| `:width`, `:height` | 6 by 4 in a notebook, 8 by 6 saved | The chart's size, in inches. A horizontal chart of categories is made tall enough for every label: 1.5 inches plus a quarter inch for each category, unless `:height` says otherwise. `save-chart` uses this size unless it's given one. |

**The axis of X values.**

| Option | What it does |
|---|---|
| `:x-min`, `:x-max` | Where the axis starts and ends: dates or numbers, like the X values. Give either one, or both. To show just part of a long series, such as the last five years, give `:x-min`. |
| `:x-format` | For X values that are numbers: how their ticks are written, as with `:y-format`. Without it, they're written as matplotlib writes them (so years stay 2024, not 2,024). |

**The axes of Y values.** These options set up the primary axis. The
same options starting `:secondary-` instead of `:y-` set up the secondary
axis.

| Option | Default | What it does |
|---|---|---|
| `:y-min`, `:y-max` | fit the data | Where the axis starts and ends. Give either one, or both. |
| `:y-log` | `#f` | `#t` gives the axis a log scale, on which equal ratios are equal distances. A series on that axis must have only values above 0. |
| `:y-ticks` | chosen to fit | A number: about that many ticks, at round numbers (multiples of 1, 2, 2.5, or 5 times a power of 10). A list: ticks at just those values. |
| `:y-format` | plain numbers | How the ticks are written: a template like `format`'s, with `{}` where the number goes, such as `"${:,.0f}"` for `$150,000`, `"{:.0%}"` for `5%`, or `"{:,.0f}k"`. Or just a spec, as `display-table` takes, such as `",.0f"` or `".1%"`. A spec for whole numbers (`",d"`) rounds the values. |

Without `:y-format`, ticks are labeled with plain numbers, with commas:
`1,500` and `0.25`, never `1.5e3`. On a log scale, the ticks are at
round numbers too. The first sequence that gives no more ticks than
wanted (8, unless `:y-ticks` says) is used:

1. 1, 2, 3, 5, 10, 20, 30, 50, ...
2. 1, 2, 5, 10, ...
3. 1, 3, 10, 30, ...
4. powers of 10, or every second or third power of 10, and so on.

When the range is too narrow for three of these (such as 130 to 335),
the ticks are ordinary round numbers: 150, 200, 250, 300.

**Reference lines, shading, and notes.** These options mark the chart. A
label is optional; it's written in small print beside the line, or at the
top of the shading. A color is optional too: lines are dark gray and
dashed, and shading is light gray.

| Option | What it does |
|---|---|
| `:x-lines` | Lines across the chart at X values: an event, such as a policy change. A list of entries, each an X value or a list (x [label [color]]). |
| `:y-lines`, `:secondary-lines` | Lines across the chart at Y values: a target, a threshold, or an average. A list of entries, each a number or a list (y [label [color]]). |
| `:shade` | Shaded spans of X: recessions, or a forecast period. A list of entries, each a list (from to [label [color]]). For categories, the shading covers every category from `from` to `to`, inclusive. |
| `:notes` | Text with an arrow pointing at a point. A list of entries, each a list (x y text), with y on the primary axis. The text goes toward the middle of the chart from its point, so it stays inside. |

Every entry list here holds a list, even if there's only one entry:
`:y-lines (list (list 2 "target"))`. Written `:y-lines (list 2 "target")`,
it would be two lines, at 2 and at `"target"` (which isn't a number).

**Bars and lines.** The room for the bars at one X is the smallest gap
between neighboring X values that have bars. Quarterly bars are as wide
as a quarter allows, even with monthly points on the same chart.

- Grouped bars sit side by side, even when some are on the secondary axis.
- Stacked bars stack separately on each axis.
- A line is drawn at 0 on an axis with bars, unless the axis has a log scale.
- When the secondary axis has bars, the primary axis is drawn in front, so
  its lines aren't hidden behind them.

Returns `'()`.

```lisp
; A monthly line over grouped quarterly bars, from one BLS table
(define t (bls-series creds '("unemployment-rate" "productivity" "employment-cost-index")))
(define dates (table-column t "date"))
(plot-chart (list (list "unemployment rate" dates (table-column t "unemployment-rate") :symbol "dot")
                  (list "productivity growth" dates (table-column t "productivity") :bars #t))
            :title "Jobs and productivity" :y-label "percent")

; Stacked bars by category, labeled in dollars, with their total as a dashed line
(define states #("New York" "Texas" "California"))
(plot-chart (list (list "wages" states #(60000 50000 70000) :bars #t :labels #t)
                  (list "other income" states #(15000 12000 20000) :bars #t :labels #t)
                  (list "total" states #(75000 62000 90000) :line "dashed" :symbol "diamond" :color "black"))
            :bars "stacked" :legend "upper left" :y-format "${:,.0f}")

; Two scales: payrolls in thousands, the unemployment rate in percent
(define jobs (bls-series creds '("nonfarm-payrolls" "unemployment-rate") :start-year 2019))
(plot-chart (list (list "payrolls" (table-column jobs "date") (table-column jobs "nonfarm-payrolls"))
                  (list "unemployment rate" (table-column jobs "date") (table-column jobs "unemployment-rate")
                        :secondary #t))
            :y-label "thousands" :secondary-label "percent" :secondary-min 0)

; An area chart with a recession shaded, a line at 4%, and a note
(plot-chart (list (list "unemployment" (table-column jobs "date") (/ (table-column jobs "unemployment-rate") 100)
                        :fill #t :line #t))
            :shade (list (list (date 2020 2 1) (date 2020 4 30) "recession"))
            :y-lines (list (list 0.04 "4%")) :y-format "{:.0%}"
            :notes (list (list (date 2020 4 1) 0.148 "14.8% in April 2020")) :legend #f)

; A fitted line with a band around it
(define x #(1 2 3 4 5 6))
(define fit #(2.0 3.1 4.0 5.2 5.9 7.1))
(plot-chart (list (list "range" x (- fit 0.8) :fill (+ fit 0.8) :color "gray")
                  (list "fit" x fit :line #t :symbol #t)))

; Fifty states, across, richest at the top; a log scale for prices since 1950
(define states (table-sort (census-profile creds "state:*") "median-household-income" #t))
(plot-chart (list (list "median income" (table-column states "name")
                        (table-column states "median-household-income") :bars #t))
            :horizontal #t :y-ticks 5 :y-format "${:,.0f}" :legend #f)
(define cpi (bls-series creds "cpi-nsa" :start-year 1950 :annual #t))
(plot-chart (list (list "CPI" (table-column cpi "date") (table-column cpi "cpi-nsa"))) :y-log #t)
```

#### `(plot-histogram data [options])`
How many values fall in each range ("bin") of values, drawn as a bar for
each bin. `data` is a vector or list of numbers, for one histogram. Or it
is a list of groups to compare, each a list (name values [series
options]); their bars share the bins, side by side, or stacked with
`:bars "stacked"`. Missing values are left out.

| Option | Default | What it does |
|---|---|---|
| `:bins` | chosen by numpy | How many bins, of equal width, from the smallest value to the largest. Or a list of the bins' edges: `(list 0 10 20 50)` is 0 to 10, 10 to 20, and 20 to 50. (Bars of unequal bins are as wide as the narrowest bin.) |
| `:percent` | `#f` | `#t` gives each bin's share of the group's values, in percent, in place of its count |
| `:x-min`, `:x-max` | the values' range | The range the bins cover. Values outside it aren't counted, though they still count toward `:percent`'s total. |

It takes every `plot-chart` chart option too, such as `:title`,
`:x-label`, `:x-format`, `:y-log`, `:horizontal`, and `:x-lines`. The
bars touch (`:bar-width` is 1), the legend is shown only when there are
groups, and the Y axis is labeled `count` or `percent`. Returns `'()`.

```lisp
(define counties (census-profile creds "county:*" :within "state:*"))
(plot-histogram (table-column counties "median-household-income") :bins 30
                :x-format "${:,.0f}" :x-lines (list (list 80000 "US median")))
(plot-histogram (list (list "2023" returns-2023) (list "2024" returns-2024))
                :bins (list -0.1 -0.05 0 0.05 0.1) :percent #t)
```

#### `(plot-panels panels [options])`
Several charts, one above another, sharing one X axis: a price over its
volume, or several economic series over the same years. `panels` is a
list with one entry for each panel, from the top. Each entry is a list
(series [options]), just as `plot-chart` takes them. A panel can have
anything a `plot-chart` can (its own `:title`, `:y-label`, `:y-log`,
`:secondary` series, `:y-lines`, `:notes`, ...), except what belongs to
the shared X axis or the whole figure. A panel's option given to
`plot-panels` is every panel's, unless a panel says otherwise:
`:legend #f` there means no panel has a legend. These are `plot-panels`'
own options:

| Option | Default | What it does |
|---|---|---|
| `:title` | none | The figure's title, above every panel |
| `:x-label` | none | The X axis's label, under the bottom panel |
| `:x-min`, `:x-max`, `:x-format` | | As for `plot-chart`, for every panel |
| `:x-lines`, `:shade` | none | As for `plot-chart`, drawn on every panel (a panel can add its own) |
| `:heights` | equal | The panels' heights, relative to one another: `(list 2 1)` makes the top panel twice as tall as the bottom one |
| `:width`, `:height` | 2.5 inches a panel, plus 1 | The figure's size, in inches |

The panels' X values must all be the same kind; for categories, every
panel has every panel's categories, in the same places. The X axis's
labels are shown once, under the bottom panel. Returns `'()`.

```lisp
(define t (bls-series creds '("cpi-nsa" "unemployment-rate" "nonfarm-payrolls") :start-year 2005))
(define dates (table-column t "date"))
(plot-panels (list (list (list (list "CPI" dates (table-column t "cpi-nsa"))) :y-log #t :title "Prices")
                   (list (list (list "unemployment" dates (table-column t "unemployment-rate") :fill #t))
                         :y-label "percent")
                   (list (list (list "payrolls" dates (table-column t "nonfarm-payrolls"))) :y-label "thousands"))
             :heights (list 2 1 1) :legend #f
             :shade (list (list (date 2007 12 1) (date 2009 6 30) "recession")
                          (list (date 2020 2 1) (date 2020 4 30))))
```

#### `(save-chart filename [width height dpi])`
Renders the most recently plotted chart to a standalone image file. Format
is inferred from `filename`'s extension (`.png`, `.pdf`, `.svg`, and
anything else matplotlib recognizes). `width`/`height` default to the
chart's own size (`plot-chart`'s `:width` and `:height`) or else `8.0`/
`6.0` (inches); give `'()` for either to keep its default while giving
`dpi`, which defaults to `150.0`. Works with or without the GUI
running — needs only matplotlib, not PyQt6. Raises `LispError` if nothing
has been plotted yet this session, if matplotlib isn't installed, or on any
file-write failure. Returns `'()`.

```lisp
(plot-chart (list (list "squares" prices squares)))
(save-chart "chart.png")
(save-chart "chart.pdf" 10.0 7.5 300)   ; larger, higher-DPI PDF
```

### Displaying tables

#### `(display-table table [formats] [:max-rows n])`
Shows a table, with a heading for each column, numbers right-aligned and
text left-aligned, and nothing in a cell whose value is missing (NaN, or
`'()`). `table` is a table (see "Tables") or a list of rows (see
`table-rows`). Where it appears depends on where you are: in a **Jupyter
notebook**, a rendered table; in the **GUI**, the Table tab; at the
**console** or in a script, a text table. Returns `'()`. Headings and text
appear just as they are, `$`, `*`, `_`, and `|` included (a notebook's
Markdown would otherwise read them as a formula, emphasis, or a new cell).

`formats` says how to lay out each column's values: a list of
`(column-name spec)`, where `spec` is written the way `format` and
`format-value` write one (see "Formatting numbers and text"): `",.2f"` for
commas and two decimals, `".1%"` for a percentage, `","` for a whole number
with commas. A column with no format shows its values as `display` would. A
format for a column the table doesn't have isn't used, so one list of
formats can serve every view of the same data.

**Leaving out a column.** A column whose format is `hide` isn't shown:
`'(("shape" hide))` leaves out a map's outlines, say, without changing the
table or making another one.

**How many rows.** It shows the first 20 rows, and a note if there are
more. `:max-rows n` shows the first `n` instead, and `:max-rows #f` every
row. It comes after the formats, if there are any.

```lisp
(define loans (make-table "id" (vector "a" "b" "c")
                          "balance" #(125000 98000.5 250000)
                          "rate" #(0.0625 0.0575 0.07)))
(display-table loans '(("balance" ",.2f") ("rate" ".3%")))
```

prints, at the console,

```
id     balance    rate
--  ----------  ------
a   125,000.00  6.250%
b    98,000.50  5.750%
c   250,000.00  7.000%
```

and

```lisp
(display-table loans '(("id" hide) ("balance" ",.2f") ("rate" ".3%")) :max-rows 2)
```

prints

```
   balance    rate
----------  ------
125,000.00  6.250%
 98,000.50  5.750%
(the first 2 of 3 rows -- :max-rows shows more)
```

To show the columns in another order, use `table-select`; to show other
rows, `table-filter`, `table-tail`, or `table-slice`.
`display-table` has no knowledge of `defstruct` columns or any other
structure; `lib/column_engine.lsp` is a small example library, built on
`defstruct` and `&key`, that registers named `column` structs (each with
its own `decimals` slot — e.g. `0` for a dollar amount, `4`-`6` for an
interest rate/CPR/SMM column), calculates them row-by-row in dependency
order, and shows them with `display-table` for you — demonstrated
end-to-end in `mortgage_amortization_example.lsp`. Inside a column's
formula, `(lag NAME n [default])` is column `NAME`'s value `n` rows back;
for a row before the first one (or past the last, with a negative `n`),
it's `default` — or an error saying so, if no default was given. For
example, `(lag balance 1 original_balance)` reads the previous row's
balance, and the original balance on the first row.

#### `(display-markdown string)`
Shows `string` as Markdown. In a Jupyter notebook (the `morris_lisp`
kernel) it renders as real Markdown — tables, headings, bold — so a cell
can build a Markdown table with `string-append` and display it neatly.
Anywhere else (console, GUI, `redirect-output`) the raw Markdown text is
written as ordinary output, which is still readable. Returns `'()`. In a
notebook, text between two `$` signs is a formula; write `\$` for a
dollar sign. (`display-table` does that, and the like for `*`, `_`, and
Markdown's other special characters, for you.)

```lisp
(display-markdown
  (string-append "| name | value |\n"
                 "|---|---|\n"
                 "| a | 1 |\n"
                 "| b | 2 |\n"))
```

#### `(display-html html [text])`
Shows `html`, a string of HTML, in a Jupyter notebook (the `morris_lisp`
kernel), where it can be anything a web page can show: colors, pictures,
a layout of its own. Anywhere else (console, GUI, `redirect-output`),
`text` is written instead -- the same thing without HTML -- or, if there's
no `text`, the HTML itself. Returns `'()`. `chess.lsp` draws its board
this way: in a notebook, as a table of light and dark squares with large
pieces; at the console, as lines of text.

```lisp
(display-html "<span style=\"color:red; font-size:20px\">Stop</span>" "Stop")
```

#### `(write-columns-csv filename pairs)`
Writes a table to a CSV file. `pairs` is a table — a list of
`(name . vector)` — or a list in which some entries are
`(name vector decimals)`, to round that column to `decimals` places:
header row = names, one data row per index, numbers rounded to
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
(write-columns-csv "out.csv" (list (list "rate" #(0.0435 0.041) 4) (cons "prices" #(10 20))))
```

### Input / output

#### `(command-line-arguments)`
The words after the script's name on the command line, as a list of
strings: `("KO" "6")` for `python3 lisp_interpreter.py script.lsp KO 6`
(see "Running it"). `'()` if there are none, and in the GUI and Jupyter.

```lisp
(command-line-arguments)        ; => ()
```

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

#### `(read-line [prompt])`
Shows `prompt` (if given), waits for the user to type a line, and returns
it as a string, without the newline. At the end of the input (Ctrl-D at a
terminal, or the end of a file piped in) it returns `#f`. It works at the
console REPL, in batch mode (reading standard input), and in a Jupyter
notebook, where the notebook shows a box to type the line in -- but not in
the PyQt window.

```lisp
(define name (read-line "Your name? "))
(display (format "Hello, {}.\n" name))
```

#### `(load "path.lsp")`
Reads and evaluates every top-level form in the file at `path`, in the
**same** (calling) global environment, so its `define`s/`defmacro`s become
available afterward exactly as if you'd typed them yourself. Returns
`'()`. This is the same mechanism the interpreter uses at startup to
auto-load `macros_init.lsp`, `loop.lsp`, and `init.lsp`.

Unless `path` is absolute, `load` looks for it in the current directory,
then in each directory in the `LISP_PATH` environment variable (separated
by colons, as in `PATH`), then in the interpreter's `lib` and `examples`
directories, and loads the first one it finds. If there's none, the error
says where it looked.

```lisp
(load "column_engine.lsp")     ; from lib/: defstruct column, register-column, ... now defined
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
(plot-chart (list (list "CPR" incentive cpr :symbol #t)))

(define d2 (load-csv "no_header.csv" #f))   ; no header row -> Column1, Column2, ...
```

To write a table to a CSV file, see `write-columns-csv` under "Displaying tables".

### Saving variables

`save-variables` saves variables in a file, and `load-variables` defines
them again later: in the same session, or after the notebook's kernel has
restarted. The file is JSON, which any program can read (Python's `json`,
pandas, a text editor), and loading one runs no code.

#### `(save-variables path name... [:leave-out-procedures #t])`
Saves each named variable's value in the JSON file at `path` (replacing
the file, if there is one), and returns the names. It's a macro, so the
names aren't quoted: it saves both the names and the values.

```lisp
(define rates #(0.05 0.06))
(define loans (make-table "id" (vector "a" "b") "balance" #(100 90)))
(save-variables "work.json" loans rates)          ; => (loans rates)
```

It can save numbers (`nan` and `inf` included), strings, symbols,
keywords, `#t` and `#f`, lists, vectors, tables, dates, hash tables,
structs, and regression models, and any of those inside another. It can't
save a procedure, which holds its environment, not just data. Nor can it
save a SQLite connection, or a map's outlines (`census-shapes` reads them
again quickly). Trying to is an error naming the variable, and nothing is
written.

**A struct's procedures.** A struct with a procedure in a slot, such as
the `f` of `(defstruct tranche (money 0.0) (f (lambda (x) (* x 3))))`, can
be saved with `:leave-out-procedures #t`. The slots that hold procedures
are left out of the file, and `load-variables` gives them their defaults.
So a struct whose procedure wasn't its slot's default gets the default
back, not its own. A procedure anywhere but in a struct's slot is still an
error.

```lisp
(defstruct tranche (money 0.0) (f (lambda (x) (* x 3))))
(define senior (make-tranche :money 100.0))
(save-variables "tranches.json" senior :leave-out-procedures #t)   ; => (senior)
```

#### `(load-variables path)`
Defines each variable saved in the file again, at the top level (even
when it's called inside a function), and returns their names. Nothing is
defined unless every value can be read.

```lisp
(load-variables "work.json")                      ; => (loans rates)
```

A struct is made by its constructor, `make-NAME`, as `defstruct` has
defined it, so run the `defstruct` first. A slot that isn't in the file
gets its default, just as `make-NAME` gives it: a procedure left out by
`:leave-out-procedures #t`, or a slot the `defstruct` has gained since. (A
default can use the slots before it, such as `(fee (* balance 0.01))`.) A
saved slot that the struct type no longer has is an error. A table's rows
(see `table-rows`) need no `defstruct`.

```lisp
(defstruct tranche (money 0.0) (f (lambda (x) (* x 3))))
(load-variables "tranches.json")                  ; => (senior)
((tranche-f senior) 2)                            ; => 6, from the default
```

- A vector comes back stored the same way: float32 numbers stay float32,
  whole numbers stay whole numbers.
- Values are saved as copies. Two variables that held the same list hold
  two equal lists after loading. A list or struct that holds itself can't
  be saved.
- A table of 200,000 rows and four columns takes about a second to save
  and a second to load, in an 11 MB file. For tables of millions of rows,
  `sqlite-write-table` (see "SQLite", in the [library manual](lisp_library_reference.md#sqlite)) is faster and smaller.

**The file.** JSON has fewer kinds of values than Lisp, so a value JSON
has no kind for is written as an object that says what it is:

| Lisp | JSON |
|---|---|
| `42`, `2.5` | `42`, `2.5` |
| `nan` | `null` |
| `inf`, `-inf` | `{"number": "inf"}`, `{"number": "-inf"}` |
| `"text"` | `"text"` |
| `#t`, `#f` | `true`, `false` |
| `(1 2 3)`, `'()` | `[1, 2, 3]`, `[]` |
| `(a . 1)` | `{"pair": [{"symbol": "a"}, 1]}` |
| `balance`, `:max-rows` | `{"symbol": "balance"}`, `{"keyword": ":max-rows"}` |
| `#(1 2 3)` | `{"vector": [1, 2, 3]}` |
| `2024-01-02` | `{"date": "2024-01-02"}` |
| a table | `{"table": [["id", ["a", "b"]], ["balance", [100, 90]]]}` |
| a hash table | `{"hash-table": [[key, value], ...]}` |
| a struct | `{"struct": "point", "slots": {"x": 1, "y": 2}}` |
| a regression model | `{"model": {"kind": "linear", "coefficients": [...], ...}}` |

The file has a line per variable:

```
{"format": "morris-lisp variables", "version": 1, "saved": "2026-10-05 14:30:00",
 "variables": {
  "loans": {"table": [["id", ["a", "b"]], ["balance", [100, 90]]]},
  "rates": {"vector": [0.05, 0.06]}
 }}
```

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
(the old `while`) and how `while` uses it now. `dolist`, `do`, and `case`
use it for the same reason.

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
See "Errors and cleanup", above — documented once there (it's a special form,
not a function: `protected-expr` must NOT be evaluated eagerly, since the
whole point is to catch what happens when it's evaluated).

#### `(throw tag [value])`, `(catch tag body...)`, `(unwind-protect protected-expr cleanup-expr...)`
See "Errors and cleanup", above. `throw` jumps out to the matching `catch`;
`unwind-protect` makes sure cleanup code runs.

#### `(assert test [message...])`
See "Errors and cleanup", above.

### Introspection / debugging

`pretty-print-function` and `pretty-print-macro` are macros (in
`macros_init.lsp`, built with `defmacro` and backquote, the same as
anything you could write yourself) so that you can write the bare name
directly — `(pretty-print-function my-func)` — instead of quoting it.

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
The same idea, for macros: every macro defined at the top level, in the
order they were defined. The standard macros (`let`, `dolist`, `while`,
`case`, `loop`, and the others in "Special forms and standard macros"; they're written in
Lisp, in `macros_init.lsp` and `loop.lsp`) come first, then any macros
from `init.lsp`, then yours.

```lisp
(defmacro double-it (x) `(* 2 ,x))
(member 'double-it (defined-macros))      ; => (double-it)
(member 'loop (defined-macros))           ; => (loop return return-from double-it)
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
A special form: see "Debugging", under "Special forms and standard macros", above. It stops the program right where
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
opens (at a terminal, a prompt; in a Jupyter notebook, a set of widgets: see
"Where the debug REPL works", below). If one is (see `set-debug-hook!`),
the hook is called instead, and
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
where an error happened. Run it from `lisp_interp/examples/`:

```bash
python3 ../lisp_interpreter.py debugging_example.lsp
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
stopped by an error: /: division by zero
variables there: ((r . 0.0) (balance . 100000) (annual-percent . 0) (months . 360))
```

and the `catch` returns `no-payment`.

**Where the debug REPL works.** At a **terminal** (running a script, or
interactively) it reads the real console with `input()`, as described above.
In a **Jupyter notebook**, JupyterLab or Notebook, it's made of widgets, in the
output of the cell that's running (see below). In the **GUI**, it would read
from whatever stdin the GUI process has (usually none, or the terminal it was
launched from), so use a hook that prints there, and don't call `(debug-repl)`.

**The debug REPL in Jupyter.** When the program stops in a notebook cell, the
cell shows:

- the stop, `--- break: entering payment(1000, 0.06) ---`, and a heading such
  as `payment> debug REPL`;
- a **text area** with a **Run** button. Type Lisp and press Run, and it's
  evaluated in the scope where the program stopped, as at the console (any
  number of forms; an error stops the rest). The text stays in the box, so you can
  change it and run it again. The pair is made with ipywidgets'
  `interact_manual`, which runs its function when the button is pressed;
- **Continue** and **Abort** buttons (the same as typing `(continue)` or
  `(abort)`), and **Locals** and **Backtrace** buttons, for the two commonest
  commands;
- a **transcript** of what you typed and what came back, including what your
  Lisp `display`ed, and long results cut off as at the console.

The cell is still running the whole time (its `[*]` and the kernel's "Busy"
stay up), and the widgets work: that's the point. When you press Continue
or Abort, or leave with `(continue)` or `(abort)`, the controls switch
off, the transcript stays, and the cell carries on or ends with an
`Aborted` error. Some things to know:

- **Other cells wait their turn.** Cells you've already sent to the kernel,
  such as the ones below in "Run All", stay queued, in order, until the
  stopped cell is finished, exactly as they would if it were merely slow.
- **A stop inside a stop works.** Type a call to a procedure with a breakpoint
  and it stops again, with a second set of widgets (in the output of the Run that
  caused it). Continue that one to return to the first, and so on.
- **Interrupt Kernel and Restart Kernel** abort the computation, and close the
  REPL, instead of leaving the kernel waiting.
- It needs **ipywidgets**, which Jupyter installs. Without it, the
  debug REPL says so, and the program carries on. A debug hook
  that prints needs no widgets at all.
- This is the `morris_lisp` kernel (`lisp_kernel.py`). Running
  `python3 lisp_interpreter.py` in a terminal, in a notebook or not,
  still has the console REPL.

`lisp_jupyter_debug.py` has the details of how a widget click reaches the
kernel while a cell is still running, which a kernel normally doesn't allow.

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

At level 3, a macro call also logs the form and what it expanded to, when
the macro expands it (the first time the call is evaluated; see "Macros"):
`~ (unless #f (quote ran)) => (if #f (quote ()) (begin (quote ran)))`.
Since `let`, `let*`, and `dolist` are macros, their expansions show up too.

- Only **user-defined procedures** are traced — not built-ins like `+` or
  `car`, and not `let`/`let*`/`dolist` scopes (which are variable scopes,
  not calls; `dolist`'s hidden loop procedure does show up, as
  `%dolist-loop-N`). A callback run by a built-in (`map`, `filter`, ...) is
  traced like any other call. Calls a macro makes while it builds its
  expansion aren't traced: they're the macro's work, not your program's.
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

(plot-chart (list (list "Demand" prices demand :symbol #t :fit "logistic")))
(save-chart "demand.png")
```

## Examples after Norvig's *Paradigms of AI Programming*

Five programs in `examples/` follow chapters of Peter Norvig's
*Paradigms of Artificial Intelligence Programming* (1992), the classic
book of AI programs in Common Lisp. They're written afresh for this
interpreter -- with its own rules, grammars, and weights -- and show how
its lists, pattern matching, regular expressions, and vector math handle
that kind of work. (Norvig's own code is at
https://github.com/norvig/paip-lisp, under the MIT license.) Run one from
`examples/`, e.g. `python3 ../lisp_interpreter.py eliza_example.lsp`.

| File | Chapter | What it does |
|---|---|---|
| `eliza_example.lsp` | 5 | ELIZA, which holds a conversation by matching what you type against patterns such as `((?* ?x) i want (?* ?y))` and answering from templates, with your words swapped around ("my" becomes "your"). Runs a scripted conversation; to talk to it yourself, `(load "eliza_example.lsp")` and then `(eliza)`. |
| `symbolic_algebra_example.lsp` | 15 | Polynomials in a canonical form: `(canon '((x + 1) * (x - 1)))` is `"x^2 - 1"`, and `(canon '(d (3 * x ^ 2 + 2 * x + 1) / d x))` is `"6*x + 2"`. |
| `othello_example.lsp` | 18 | Othello, with players that move at random, count pieces, weigh squares, and search ahead with minimax and alpha-beta pruning. The board is a vector, so a position is scored with vector math. To play, `(load "othello_example.lsp")` and then `(othello human (alpha-beta-searcher 2 weighted-squares) #t)`. |
| `nlp_parsing_example.lsp` | 19 | A parser that finds every parse of a sentence, so it shows where the sentence is ambiguous ("the man saw the woman with the telescope" has two readings); remembering parses to make it fast; guessing at unknown words; and a grammar whose parses have meanings ("two plus three times four" is 20 or 14). |
| `unification_grammar_example.lsp` | 20, 21 | A small Prolog (unification and a prover), and a grammar written in it whose features make the subject and verb agree and whose parses are formulas of logic: "every dog chases a cat" is `(every ?x (dog ?x) (some ?y (cat ?y) (chase ?x ?y)))`. Run backwards, it turns a meaning into the sentences that say it. |

ELIZA and Othello read what you type with `read-line`, so they work at the
console REPL and in a Jupyter notebook.

## A chess program

`examples/chess.lsp` plays chess, and is meant to be read: every part of
it is short and explained.

- **The board** is a vector of 120 numbers: the 64 squares with a border
  around them, so a move off the board lands on a border square. A white
  piece is a positive number and a black one negative.
- **The rules** are all there: castling, en passant, promotion, check,
  checkmate, and stalemate. (Not draws by repetition, by the fifty-move
  rule, or by too little material.) `candidate-moves` finds the moves each
  piece can make, and a move is legal if, once it's made, the mover's king
  isn't attacked. `count-positions` checks them against the numbers every
  chess program must get.
- **Algebraic notation**: you type moves as `e4`, `Nf3`, `exd5`, `O-O`,
  `e8=Q`, or as their squares, `e2e4`. Rather than parse what's typed, the
  program writes each legal move in notation and looks for the one that
  matches.
- **Looking ahead**: minimax with alpha-beta pruning, `depth` moves ahead;
  then, so that the evaluation doesn't judge a position in the middle of
  an exchange, a search of the captures until the position is quiet. The
  evaluation counts material and adds a little for pieces on good squares,
  worked out with vector arithmetic.
- **The board is drawn** with the chess pieces Unicode has (♔ ♕ ♖ ♗ ♘ ♙,
  ♚ ♛ ♜ ♝ ♞ ♟): in a Jupyter notebook as an HTML table of light and dark
  squares (with `display-html`), and elsewhere as text.

To play it, at the console or in a notebook:

```lisp
(load "chess.lsp")
(play-chess)                     ; you're white; the computer looks 2 moves ahead
(play-chess :human black :depth 3)
```

At depth 2 the computer takes a few seconds a move; at depth 3, which
plays better, ten to thirty seconds. Type `moves` for a list of the legal
moves, and `quit` to stop. `fen->position` makes a position from
Forsyth-Edwards Notation, to start somewhere else with `:position`.
`examples/chess_example.lsp` shows the program checking its rules and
finding a checkmate, a knight fork, and a sacrifice that mates in two.

## A KenKen solver

`examples/kenken_example.lsp` solves KenKen puzzles: an N × N grid to fill
with the digits 1 to N, with no digit twice in any row or column, and each
cage — a group of cells outlined in the puzzle — coming out right: its
digits, combined by the cage's operation, give the cage's number. A cell
is written as its row and column (`23` is row 2, column 3), and a cage as
its cells and its arithmetic:

| Cage | Means |
|---|---|
| `((11 12 13 23) (+ 17))` | the four digits add up to 17 |
| `((31 41) (- 2))` | the larger digit less the smaller is 2 |
| `((32 33) (* 12))` | the digits multiply to 12 |
| `((34 44) (/ 3))` | the larger digit divided by the smaller is 3 |
| `((42) (= 4))` | the digit is 4 |

(A `-` or `/` cage of more than two cells works the same way: the largest
digit less, or divided by, all the others.) A puzzle is its size and a
list of its cages:

```lisp
(load "kenken_example.lsp")              ; solves its own three puzzles first
(define puzzle
  '(((11 21 22) (+ 9))  ((12 13) (* 3))     ((14) (= 2))
    ((23 24 34) (+ 9))  ((31 32 41) (+ 4))  ((33 43 44) (* 18))
    ((42) (= 4))))
(solve-kenken 4 puzzle)                  ; ((4 3 1 2) (3 2 4 1) (2 1 3 4) (1 4 2 3)), a list of rows
(length (kenken-solutions 4 puzzle))     ; 1 -- the puzzle has exactly one solution
(show-kenken 4 puzzle :solution (solve-kenken 4 puzzle))
```

`solve-kenken` returns the solution as a list of rows, or `#f` if there's
none; `kenken-solutions` returns up to `:limit` (default 2) solutions, so
its length says whether a puzzle has exactly one; `show-kenken` draws the
puzzle — in a Jupyter notebook as a grid with the cages outlined (with
`display-html`), elsewhere as text — with the digits of a solution if
`:solution` is given. A puzzle that isn't well formed (a cell in two cages
or none, say) is an error that says what's wrong.

How it solves them: for each cell, it keeps the digits the cell could
still be, and for each cage, the combinations of digits that make its
arithmetic come out. It rules out what can't be, over and over: a cage
combination that needs a digit a cell can no longer be; a digit no
combination puts in a cell; a digit already settled elsewhere in a row or
column. And a digit that can go in only one cell of a row or column goes
there. When that stalls, it guesses, at the cell with the fewest digits
left, and goes back if the guess leads to a contradiction. The 4 × 4 and
6 × 6 puzzles in the file take no guesses and well under a second; the
9 × 9 one, which gives no digits and has large cages, about 10 seconds.

---

## How the code is organized

The interpreter is split into these Python files, all in `lisp_interp/`,
along with the standard macros (`macros_init.lsp`, `loop.lsp`) and your
`init.lsp`. Three directories hold the rest:

| Directory | What's in it |
|---|---|
| `lib/` | Lisp libraries you can `load`: `solver.lsp` (Ridders and Nelder-Mead), `vol_smile.lsp` (fitting implied volatility smiles), `option_check.lsp` (option prices checked against simulated paths), `option_methods.lsp` (a stock's options valued three ways), `template.lsp`, `column_engine.lsp`, `prepayment_model.lsp`, `oas_monte_carlo.lsp`, `model_utils.lsp` |
| `examples/` | Example programs (`*_example.lsp`, `prepayment_demo.lsp`), with the data files they read -- among them the five after Norvig's *Paradigms of AI Programming*, a chess program, `chess.lsp`, and a KenKen solver (see the sections above). Run one from that directory: `python3 ../lisp_interpreter.py macros_example.lsp` |
| `notebooks/` | Jupyter notebooks that use the interpreter (on the `morris_lisp` kernel) |
| `scratch/` | Experiments: not part of the interpreter, and not tested |
| `tools/` | `make_contents.py`, which rebuilds both manuals' Contents from their headings (run it after adding a section); `build_pool_dataset.py`, which turns Freddie Mac loan-level files into a pool-level CSV; and `mbs_prepayment_data_guide.md`, which explains where that data comes from |

`load` finds files in `lib/` and `examples/` from anywhere (see "Where
`load` finds a file", under "Running it").

The Python files:

| File | What's in it |
|---|---|
| `lisp_interpreter.py` | The command line (what runs when you type `python3 lisp_interpreter.py ...`), the console REPL, and batch mode |
| `lisp_core.py` | The language itself: data types, the reader, environments, the evaluator and special forms, call tracing, and the printer. It imports none of the other files. |
| `lisp_builtins.py` | The general built-in procedures (numbers, lists, strings, making and reading vectors, dates, hash tables, output, ...) and `make_global_env()`, which builds a new environment containing every builtin |
| `lisp_vector_math.py` | Arithmetic, comparisons, statistics, and time-series functions on whole vectors (`vector-mul`, `vector>`, `vector-mean`, `vector-lag`, ...) |
| `lisp_regex.py` | Regular expressions: `regex-search`, `regex-replace`, ... |
| `lisp_tables.py` | Tables: `table-filter`, `table-sort`, `table-group-by`, `table-join`, ... |
| `lisp_stratify.py` | Stratification tables: `stratify`, `stratify-all` |
| `lisp_time_series.py` | Month numbers and monthly series: `yyyymm->month-number`, `series-monthly`, `series-table`, ... |
| `lisp_debug.py` | `break`, `unbreak`, `set-debug-hook!`, `abort`, `locals`, `break-on-error`, ...: the debugging functions (the machinery is in `lisp_core.py`) |
| `lisp_regression.py` | `linear-regression`, `lad-regression`, `quantile-regression`, `logistic-regression`, `spline-regression`, `spline-lad`, `spline-quantile`, `spline-logistic`, `model-report`, ... |
| `lisp_save.py` | `save-variables` (with its macro in `macros_init.lsp`) and `load-variables`: variables in a JSON file |
| `lisp_simplex.py` | `lp-read-file`, `lp-solve`: linear programming (uses `simplex/`) |
| `lisp_clock.py` | The clock: `current-time`, `today`, `time-add`, `sleep`, `sleep-until`, ... |
| `lisp_options.py` | `bsm-price`, `implied-vol`, the Greeks (`bsm-delta`, ...), `bsm-probability-in-the-money`, `black-price`, `american-price`, `binomial-tree`, `binomial-probability-in-the-money`, ...: option prices |
| `lisp_finance.py` | Day counts (`day-count`, `year-fraction`) and cash-flow math: `npv`, `irr`, `xnpv`, `xirr`, `payment`, `present-value`, `yield`, `duration`, `convexity`, ... |
| `lisp_charts.py` | The `plot-` builtins and `save-chart` (the charts themselves are in `lisp_plot_chart.py` and `lisp_maps.py`) |
| `lisp_plot_chart.py` | `plot-chart`, `plot-histogram`, `plot-panels`: charts of several series, with bars, areas, a secondary axis, reference lines, and panels |
| `lisp_maps.py` | `census-shapes`, `plot-map`: the Census's boundaries of states, counties, tracts, ZIP code areas, ..., and maps of them with an equal-area projection |
| `lisp_csv.py` | `load-csv`, `write-columns-csv` |
| `lisp_sqlite.py` | `sqlite-open`, `sqlite-query`, `sqlite-write-table`, ... |
| `lisp_http.py` | `http-get-json`, `http-get-csv`, ... (downloads from any web API) |
| `lisp_fred.py` | `fred-table` (downloads from FRED, through `lisp_http.py`) |
| `lisp_data_common.py` | What the data modules share: reading the credentials file, the years and lists of names they take, and making their tables |
| `lisp_sec.py` | `sec-income-statement`, `sec-balance-sheet`, `sec-financials`, ...: financial statements from the SEC's XBRL data |
| `lisp_fdic.py` | `fdic-balance-sheet`, `fdic-ratios`, `fdic-financials`, `fdic-get`, ...: banks' Call Report data from the FDIC |
| `lisp_census.py` | `census-get`, `census-profile`, `census-variables`, ...: demographic and economic data from the Census Bureau |
| `lisp_bls.py` | `bls-series`, `bls-local-area`, `bls-names`, ...: prices, jobs, and pay from the Bureau of Labor Statistics |
| `lisp_bea.py` | `bea-series`, `bea-nipa`, `bea-regional`, `bea-get`, ...: the national and regional accounts from the Bureau of Economic Analysis |
| `lisp_tastytrade.py` | `tastytrade-get`, `tastytrade-quotes`, `tastytrade-option-chain`, ... (data from tastytrade; read only) |
| `lisp_alpha_vantage.py` | `alpha-vantage-dividends`: a stock's dividends from Alpha Vantage, through `lisp_http.py` |
| `lisp_schwab.py` | `schwab-login`, `schwab-accounts`, `schwab-positions`, `schwab-quotes`, `schwab-price-history`, `schwab-orders`, ...: your Schwab accounts |
| `lisp_investment_paths.py` | `daily-returns`, `adjust-returns`, `dividend-schedule`, `bootstrap-path`, `bootstrap-days`, `volatility-model`, `volatility-history`, `volatility-forecast`, `option-value`, `option-payoffs`: simulated prices of an investment, with its volatility starting at today's if asked, and what options on it are worth |
| `lisp_calendar.py` | `trading-day?`, `add-trading-days`, `trading-days-between`, `nyse-holidays`, ...: the NYSE's trading days |
| `lisp_futures.py` | `futures-curve-fit`, `futures-leg-carry`: a futures curve's rich and cheap contracts, and its carry |
| `lisp_portfolio.py` | `combine-returns`, `bootstrap-paths`, `portfolio-value`, `covariance-matrix`, `correlation-matrix`, `minimum-variance-weights`, `mean-variance-weights`, ...: portfolios |
| `lisp_sofr.py` | `sofr-*` interest-rate modeling (uses `term_structure/`) |
| `lisp_gui.py` | The PyQt6 window |
| `lisp_kernel.py`, `lisp_jupyter.py` | The Jupyter kernel |
| `lisp_jupyter_debug.py` | The debug REPL in Jupyter, made with ipywidgets |
| `tests/` | The tests, a file for each part (see "Running the tests"): `python3 -m unittest discover -s tests` |

Some Lisp files are loaded into every new environment at startup:
`macros_init.lsp` and `loop.lsp`, the standard macros (see "Standard
macros"), by `make_global_env()`, and then `init.lsp`, your own
definitions, by `load_init_file()`. Both are in `lisp_builtins.py`.

Each file that adds builtins ends with a `BUILTINS` table — a Python dict
from the Lisp name to the Python function that implements it — and
`make_global_env()` in `lisp_builtins.py` copies each of those tables into
every new environment.

## Running the tests

The tests are in `lisp_interp/tests/`, a file for each part of the
interpreter, about 1,100 of them:

| File | What it tests |
|---|---|
| `test_language.py` | the reader, special forms, tail calls, macros, structs, errors, the standard macros and `loop`, and loading files |
| `test_builtins.py` | numbers, lists, strings, regular expressions, `format`, hash tables, vectors and vector math, dates, the clock, trading days, and monthly time series |
| `test_tables.py` | tables, displaying them, stratification, CSV files, SQLite, and saving variables |
| `test_charts.py` | charts and maps |
| `test_data_sources.py` | the data sources, each against a stand-in for its web API |
| `test_models.py` | regression, linear programming, the solver, day counts and cash flows, and the template and column-engine libraries |
| `test_investments.py` | option prices, futures curves, the volatility smile, simulated prices, option chains checked against them, and portfolios |
| `test_debugging.py` | tracing, stack traces, breakpoints, and the debug REPL, in the console and in Jupyter |
| `test_programs.py` | the command line, the GUI's error report, the chess and KenKen programs, and the example scripts |
| `test_reference_doc.py` | **the two manuals**, this one and `lisp_library_reference.md`: every ` ```lisp ` example with a `; =>` result is run, and the test fails if the interpreter no longer returns that value. So when you change how something behaves, the tests say which documented examples need updating |

`support.py` has what they all use: the interpreter's modules, and
`LispTestCase`, which gives each test a fresh global environment.

They need nothing beyond what the interpreter itself needs (numpy). They
never use the network, your credentials, or any file outside a temporary
directory, so they're safe to run at any time. All of them take about 75
seconds. Run them after changing the interpreter, a builtin, a `.lsp`
library, or a manual.

**Running them.** From the `lisp_interp` directory:

```bash
python3 -m unittest discover -s tests
```

It prints a dot for each test that passes, then `OK`, or a report of each
test that failed. Other ways to run them:

| Command (in `lisp_interp/`) | What it runs |
|---|---|
| `python3 -m unittest discover -s tests` | every test |
| `python3 -m unittest discover -s tests -v` | every test, printing each test's name and result |
| `python3 tests/test_builtins.py` | one file's tests |
| `python3 tests/test_builtins.py TestFormat` | one group of tests (a test class) |
| `python3 tests/test_builtins.py TestFormat.test_decimals_and_commas` | one test |
| `python3 -m pytest -q tests` | every test, using pytest instead, if it's installed; add `-k format` to pick tests (upper/lower case doesn't matter) |

To see the names of the groups, run `grep -n "^class Test" tests/*.py`.
Each group's docstring says what it covers.

**The slow examples.** Two example scripts take a while
(`dolist_vectors_map_example.lsp`, about 15 seconds, and
`oas_monte_carlo_example.lsp`, about 60), so they're skipped unless you
set the `LISP_TEST_SLOW` environment variable:

```bash
LISP_TEST_SLOW=1 python3 -m unittest discover -s tests
```

**What isn't tested.** Anything that needs the network or an account:
`fred-table`, `tastytrade-*`, and `sofr-calibration-data`. The
`http-get-*` functions are tested against a small web server that the
tests start on your own computer. The GUI gets only a check that its error
report looks right; it runs off-screen, so no window opens, and it's skipped
if PyQt6 isn't installed. The Jupyter kernel is tested by starting a real
one, which takes a few seconds: its error boxes, and the debug REPL, which a
scripted stand-in for the browser types into and clicks. Those tests are
skipped if ipykernel or ipywidgets isn't installed.

**Reading a failure.** Each failure names the test and shows what was
expected and what happened. For a test that ran Lisp code, it also shows
that code (`source: ...`). A failing example from a manual is listed
like this:

```
lisp_interpreter_reference.md, block 239: (defined-macros)
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
section where it belongs, and a test to the file in `tests/` for that part. Any
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
