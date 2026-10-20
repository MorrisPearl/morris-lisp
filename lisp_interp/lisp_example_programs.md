# morris-lisp — The example programs

The programs in `examples/` are written to be read as well as run. This
document says what each one does, how to run it, and — for the programs that
teach something — explains the **programming techniques** they show: how a
chess program represents a board, how ELIZA matches patterns, how a Prolog is
a few dozen lines of Lisp, how a SQL interpreter can work on whole columns at
once. Several of the programs are after chapters of Peter Norvig's classic
*Paradigms of Artificial Intelligence Programming*; they're written afresh for
this interpreter, and the notes say where its rules (`#f` is the only false,
vectors hold only numbers, strings, and dates) change what the book does.

There are three documents. The **language manual**,
[lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the
syntax, the special forms and macros, and the general builtins. The **library
manual**, [lisp_library_reference.md](lisp_library_reference.md), covers
getting data, models, and investments. **This one is about the programs**: the
language and library documents say what each function does; this says how
whole programs are put together out of them. A section name in quotes is a
section of the language manual, unless it says otherwise.

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [Running the examples](#running-the-examples)
- [The examples at a glance](#the-examples-at-a-glance)
- [Techniques, and where to see them](#techniques-and-where-to-see-them)
- [Learning the language](#learning-the-language)
  - [Macros: code that writes code](#macros-code-that-writes-code)
  - [Metaprogramming: eval, apply, gensym](#metaprogramming-eval-apply-gensym)
  - [Structs and with-struct](#structs-and-with-struct)
  - [Loops and tail calls](#loops-and-tail-calls)
  - [Debugging and profiling](#debugging-and-profiling)
- [Programs after Norvig's *Paradigms of AI Programming*](#programs-after-norvigs-paradigms-of-ai-programming)
  - [ELIZA (chapter 5)](#eliza-chapter-5)
  - [Symbolic algebra (chapter 15)](#symbolic-algebra-chapter-15)
  - [Othello (chapter 18)](#othello-chapter-18)
  - [Parsing English (chapter 19)](#parsing-english-chapter-19)
  - [Unification, Prolog, and grammars that run both ways (chapters 11, 20, and 21)](#unification-prolog-and-grammars-that-run-both-ways-chapters-11-20-and-21)
- [A chess program](#a-chess-program)
- [A KenKen solver](#a-kenken-solver)
- [Languages](#languages)
  - [A language from a table: the parser framework](#a-language-from-a-table-the-parser-framework)
  - [SQL: an interpreter over tables](#sql-an-interpreter-over-tables)
- [Models of money](#models-of-money)
  - [Models as columns of formulas](#models-as-columns-of-formulas)
  - [Statistics and optimization](#statistics-and-optimization)
- [Prices, options, and trades](#prices-options-and-trades)
- [Economic data and pictures](#economic-data-and-pictures)
- [Writing an example](#writing-an-example)

## Running the examples

Run an example from the `examples/` directory (some read data files that sit
beside them):

```
cd lisp_interp/examples
python3 ../lisp_interpreter.py eliza_example.lsp
```

Or load it at the console, in the GUI, or in a Jupyter notebook; `load` finds
files in `examples/` and `lib/` from anywhere:

```lisp
(load "eliza_example.lsp")
```

- **Arguments.** An example that takes some reads them with
  `(command-line-arguments)`: `python3 ../lisp_interpreter.py call_spread_example.lsp SPY 2026-11-20 765`.
  (Not as arguments of `load`.)
- **Credentials.** Examples that fetch data read keys from the credentials file,
  whose path `init.lsp` sets as `creds`; each says which entries it needs. The
  *offline* examples — the language examples, the Norvig programs, chess, KenKen,
  the two languages, and the statistics and optimization examples — need neither a
  network nor a key. The tables below say which need what.
- **Programs and libraries.** An example's own file is a script: it defines
  things and then runs a demonstration. `chess.lsp`, `sql.lsp`, and the other
  files named without `_example` are programs to `load` and use, with a
  `_example` script that shows them at work (`chess_example.lsp`,
  `sql_example.lsp`).
- **The tests run them.** The offline examples run in the tests
  (`tests/test_programs.py`), most of them checking what they print; the five
  slowest (Othello, chess, KenKen, the OAS pipeline, and the tail-call example) only
  when `LISP_TEST_SLOW=1` is set.

## The examples at a glance

**Learning the language**

| File | What it shows | Needs |
|---|---|---|
| `macros_example.lsp` | `defmacro`, quasiquote, why `swap!` and `unless` can't be functions, a macro that is a loop | nothing |
| `metaprogramming_example.lsp` | variadic procedures, `eval`, `apply`, `gensym`, `load`, redirecting output | nothing |
| `with_struct_example.lsp` | binding all of a struct's slots at once | nothing |
| `dolist_vectors_map_example.lsp` | `dolist`, `vectors-map`, and loops of a million calls in constant stack | nothing (15 s) |
| `trace_example.lsp` | `(verbose n)` call tracing, `(backtrace)`, what an error report looks like | nothing |
| `debugging_example.lsp` | `break`, a debug hook, conditional breakpoints, `break-on-error` | nothing |

**After Norvig's *Paradigms of AI Programming***

| File | Chapter | What it shows | Needs |
|---|---|---|---|
| `eliza_example.lsp` | 5 | pattern matching, rules as data | nothing |
| `symbolic_algebra_example.lsp` | 15 | canonical forms, a recursive-descent reader | nothing |
| `othello_example.lsp` | 18 | a board in a vector, strategies as closures, minimax and alpha-beta | nothing |
| `nlp_parsing_example.lsp` | 19 | a grammar as data, every parse, memoizing, meanings | nothing |
| `unification_grammar_example.lsp` | 11, 20, 21 | unification, a small Prolog, a grammar in it that parses and generates | nothing |

**Games and puzzles**

| File | What it shows | Needs |
|---|---|---|
| `chess.lsp`, `chess_book.lsp`, `chess_example.lsp` | a complete chess program: rules, notation, search with alpha-beta and a table, an opening book | nothing |
| `kenken_example.lsp` | constraint propagation and backtracking | nothing |

**Languages**

| File | What it shows | Needs |
|---|---|---|
| `sql.lsp`, `sql_example.lsp` | an SQL interpreter over the interpreter's own tables | nothing |
| `parser_example.lsp` | the parser framework (`lib/parser.lsp`): a calculator, and a settings file read into a table | nothing |

**Models of money**

| File | What it shows | Needs |
|---|---|---|
| `mortgage_amortization_example.lsp` | a mortgage and a four-tranche deal, as columns of formulas (`lib/column_engine.lsp`) | tastytrade (for its SOFR section) |
| `sofr_floating_rate_example.lsp` | a floating-rate note driven by the SOFR futures curve | tastytrade |
| `oas_monte_carlo_example.lsp` | the whole option-adjusted-spread pipeline on made-up numbers | nothing (60 s) |
| `oas_monte_carlo_live_example.lsp` | the same on live data, written to a report | tastytrade, FRED |
| `rate_paths_example.lsp` | how paths of interest rates are made, a stage at a time: today's curve, the curve with no volatility, the model's two random factors, the curve they bend on a date, and many paths | nothing: a free download |
| `rate_model_example.lsp` | fitting the rate model to SOFR and 10-year note options together, then drawing and charting a few paths from it | tastytrade, the Treasury's curve |
| `note_option_example.lsp` | fitting the rate model to options on the 10-year note future: the model's prices next to the market's, and the volatility smile | tastytrade, the Treasury's curve |
| `prepayment_demo.lsp` | loading pool data, a spline-logistic model, a held-out test, a chart | nothing |
| `regression_kinds_example.lsp` | six kinds of regression on the same data, and cross-validation | nothing |
| `stratify_example.lsp` | stratification tables of 5,000 made-up loans | nothing |
| `linear_programming_example.lsp` | investing $100 million in four pools, from a problem file | nothing |

**Prices, options, and trades**

| File | What it shows | Needs |
|---|---|---|
| `investment_paths_example.lsp` | simulating prices by copying blocks of history; an option on them | Schwab, Alpha Vantage |
| `option_chain_example.lsp` | an option chain as a table: filtering by column, looking at rows | tastytrade |
| `vol_smile_example.lsp` | fitting the volatility smile to find options out of line | tastytrade |
| `option_methods_example.lsp` | a stock's options valued three ways, next to the market | tastytrade, Schwab, Alpha Vantage |
| `call_spread_example.lsp` | the best call spread for the price you expect, and a chart of its profit against the stock's price | Schwab |
| `option_spreads_example.lsp` | the best position of one of seventeen kinds (spread, butterfly, iron condor, covered call, ...) for the price you expect, with profit charts | Schwab |
| `option_positions_example.lsp` | the best of every kind side by side, with owning the stock among them, and profit charts | Schwab |
| `option_payoffs_example.lsp` | what each of the seventeen kinds pays: a chart of its profit against the stock's price, for a made-up chain | nothing: no network |
| `tastytrade_example.lsp` | quotes, futures curves, option chains, and market metrics | tastytrade |

**Economic data and pictures**

| File | What it shows | Needs |
|---|---|---|
| `fred_example.lsp`, `sec_example.lsp`, `fdic_example.lsp`, `census_bls_example.lsp`, `bea_example.lsp` | one data source each | the source's key |
| `yield_curve_example.lsp` | today's Treasury yield curve from the Treasury and from the Fed: zero rates and forward rates, charted | nothing: free downloads |
| `map_example.lsp` | maps colored by a value | Census and BEA keys |
| `plot_chart_example.lsp` | `plot-chart`: lines, symbols, bars, categories, two axes | nothing |
| `report_example.lsp` | a table written as a text report with control breaks: mortgages with subtotals by zip code and state and a grand total, on pages; a letter to each client | nothing |
| `deal_example.lsp` | a structured deal as a tree: a pool of mortgages divided by sequential and pro-rata splits into bonds, run at two prepayment speeds; and a PAC with its companion | nothing |

## Techniques, and where to see them

| Technique | Where |
|---|---|
| **Programs as data** — a table of rules that the program only interprets | [ELIZA](#eliza-chapter-5), [grammars](#parsing-english-chapter-19), [the parser framework](#a-language-from-a-table-the-parser-framework), [SQL's grammar](#sql-an-interpreter-over-tables) |
| **Pattern matching and unification** | [ELIZA](#eliza-chapter-5), [unification](#unification-prolog-and-grammars-that-run-both-ways-chapters-11-20-and-21) |
| **All the answers as a list** — nondeterminism without a backtracking machine | [parsing English](#parsing-english-chapter-19), [the prover](#unification-prolog-and-grammars-that-run-both-ways-chapters-11-20-and-21), [KenKen's cage combinations](#a-kenken-solver) |
| **Remembering** (memoization), and a table that forgets | [parsing English](#parsing-english-chapter-19), [the parser framework](#a-language-from-a-table-the-parser-framework), [chess's capture table](#a-chess-program) |
| **Recursive descent** | [the algebra reader](#symbolic-algebra-chapter-15), [the framework](#a-language-from-a-table-the-parser-framework), [SQL](#sql-an-interpreter-over-tables) |
| **Canonical forms** and constructors that keep a data structure tidy | [symbolic algebra](#symbolic-algebra-chapter-15) |
| **Closures and higher-order functions** — strategies, builders, tails | [Othello](#othello-chapter-18), [SQL's comparison tails](#sql-an-interpreter-over-tables) |
| **Whole-array arithmetic** instead of loops | [Othello](#othello-chapter-18), [chess](#a-chess-program), [SQL](#sql-an-interpreter-over-tables), [regression kinds' data](#statistics-and-optimization), [investment paths](#prices-options-and-trades) |
| **A board in a vector, with a border** | [Othello](#othello-chapter-18), [chess](#a-chess-program) |
| **Game-tree search** — negamax, alpha-beta, move ordering, quiescence | [Othello](#othello-chapter-18), [chess](#a-chess-program) |
| **Constraint propagation with backtracking** | [KenKen](#a-kenken-solver) |
| **Non-local exit** with `throw` and `catch` | [KenKen](#a-kenken-solver), [debugging](#debugging-and-profiling) |
| **Macros** — control forms, and small languages inside Lisp | [macros](#macros-code-that-writes-code), [unification's `<-` and `rule`](#unification-prolog-and-grammars-that-run-both-ways-chapters-11-20-and-21), [`define-grammar`](#a-language-from-a-table-the-parser-framework), [`defcolumn`](#models-as-columns-of-formulas) |
| **Code as data**, `eval` | [metaprogramming](#metaprogramming-eval-apply-gensym), [the calculator](#a-language-from-a-table-the-parser-framework), [the column engine](#models-as-columns-of-formulas) |
| **Structs** to give names to the parts | [with-struct](#structs-and-with-struct), [KenKen](#a-kenken-solver), [chess](#a-chess-program), [SQL](#sql-an-interpreter-over-tables) |
| **Tail calls** as loops that use no stack | [tail calls](#loops-and-tail-calls), [Othello](#othello-chapter-18) |
| **Reproducible randomness** with `random-seed` | [ELIZA](#eliza-chapter-5), [Othello](#othello-chapter-18), [regression kinds](#statistics-and-optimization), [stratification](#statistics-and-optimization) |
| **Testing**: known answers (perft), comparing with another program (sqlite3), random inputs, deliberate breakage | [chess](#a-chess-program), [SQL](#sql-an-interpreter-over-tables), [writing an example](#writing-an-example) |
| **A one-time tool that writes a data file**, checked by the program | [the chess opening book](#a-chess-program) |
| **A script as a thin layer over a library** with `(command-line-arguments)` | [option methods, call spreads, other option spreads](#prices-options-and-trades) |
| **Charting a function that bends**: the grid of prices plus its corners and zero crossings; gain and loss as two filled series; panels to compare shapes | [option payoffs](#prices-options-and-trades) |
| **Spreadsheet-like models**: a column per formula, ordered by dependence | [the column engine](#models-as-columns-of-formulas) |
| **Seeing what a program does**: tracing, breakpoints, profiling | [debugging and profiling](#debugging-and-profiling) |

---

## Learning the language

Six small scripts, each about one feature, with the output they print. They
are the quickest way to see the feature working; "Special forms and standard
macros" in the language manual has the reference.

### Macros: code that writes code

`macros_example.lsp`. A function receives the *values* of its arguments. A
macro receives the *source code* of its arguments, unevaluated, and returns
new code to be evaluated in place of the call. That lets a macro do three
things no function can:

- **Not evaluate an argument.** `my-unless` expands to `(if (not test) then '())`,
  so `then` never runs when the test is true. As a function, `then` would be
  evaluated before the call. The example proves it: its untaken branch calls a
  function that doesn't exist, and nothing happens.
- **Change the caller's variables.** `(swap! p q)` expands to a `let` and two
  `set!`s on `p` and `q` themselves. A function only ever sees what `p` and `q`
  hold, so it has nothing to set.
- **Make a new control structure.** `my-and2` expands to an `if`, so it stops at the
  first false (`(my-and2 #f (begin (set! ran-b #t) #t))` never runs the `begin`), and
  `my-while`, below, is a loop. Control structures like `if`, `when`, and `while` are the
  forms whose arguments mustn't all be evaluated at once.

The tool for building the new code is **quasiquote**: a template written with
a backquote, in which `,x` inserts the value of `x` and `,@xs` inserts the
elements of a list. Compare the two ways of writing `my-unless`:

```lisp
(defmacro my-unless (test then)
  `(if (not ,test) ,then '()))              ; the template looks like the code it makes

(defmacro my-unless-by-hand (test then)
  (list 'if (list 'not test) then ''()))    ; the same, by building lists
```

`macros_example.lsp` ends with `my-while`, a loop written as a macro whose
expansion calls itself in tail position, so it too runs in constant stack
space (200,000 iterations). Its name is `%loop`, which raises the classic
macro trap: a macro that introduces a variable can capture one of the
caller's. The standard `while` uses `gensym` for the loop's name instead;
"What goes wrong without gensym", in the language manual, shows the bug.

To see what a macro call becomes, without running it:
`(macroexpand-1 '(while (< i 3) (display i)))`.

### Metaprogramming: eval, apply, gensym

`metaprogramming_example.lsp`. The other half of code-as-data. A list that looks
like code *is* code: `(eval (list '+ 1 2))` is 3. The example shows:
variadic procedures (`(lambda args ...)` takes any number of arguments, and
`(a b . rest)` some fixed ones then the rest); a **variadic macro**, `my-or`, that
handles any number of expressions by expanding into a `let` and another `my-or` for
the rest, so it short-circuits at the first true one; `apply`, to call a procedure
with a list of arguments (`(apply + 1 2 (list 3 4 5))`); `eval` of code built as a
list; `gensym`, for a name no one else is using; `load`; and `redirect-output`, here
used to write a file and `load` it back. Programs in later chapters lean on these:
[the column engine](#models-as-columns-of-formulas) keeps each formula as a
quoted list and `eval`s it for each row, and the
[calculator in the parser framework](#a-language-from-a-table-the-parser-framework)
builds `(+ 2 (* 3 4))` as a tree that `eval` then runs.

### Structs and with-struct

`with_struct_example.lsp`. `defstruct` gives a record type and its accessors
(`point-x`, `point-y-set!`). A formula that uses six fields would otherwise be
six accessor calls on the same object. `(with-struct p body...)` binds *all* the
slots as variables for the length of the body, as `let` would:

```lisp
(defstruct loan balance rate months)
(define (monthly-payment ln)
  (with-struct ln
    (let ((r (/ rate 12.0)))
      (/ (* balance r) (- 1.0 (expt (+ 1.0 r) (- months)))))))
```

It is a special form, not a macro, for a reason worth knowing: *which names to
bind* depends on the struct that `ln` holds when the code runs, and a macro only
ever sees the symbol `ln`. The variables are copies, as with `let`: `set!` on
`balance` changes the variable and not the struct. Use `loan-balance-set!` for
that. The example also covers inherited slots (`:include`), nesting, closures
over the bound slots, and that the body is in tail position.

### Loops and tail calls

`dolist_vectors_map_example.lsp`. Three things:

- `dolist` for a loop whose job is its side effects, with an optional result
  expression.
- `vectors-map`, which is `vector-map` for several vectors at once: the procedure gets
  one element from each, and the element's index as a last argument.
- **Tail calls.** A call that is the last thing a function does doesn't need the
  function's frame any more, so this interpreter replaces the frame instead of
  adding one. A loop written as a recursive function therefore runs in constant
  space: `(count-down 1000000 0)` below finishes without growing the stack.

```lisp
(define (count-down n acc)
  (if (= n 0) acc (count-down (- n 1) (+ acc 1))))   ; the recursive call is the last thing done
```

`dolist` and `while` are macros that expand into exactly such a function (a local one,
with a name made by `gensym`, that calls itself as its last act; `macroexpand-1` shows
it), which is why they have no limit on how long they run. The examples that follow
use them freely.

### Debugging and profiling

`trace_example.lsp` and `debugging_example.lsp`. Three levels of looking at a
running program:

- **Tracing.** `(verbose 1)` logs each call by name, indented by depth; `(verbose 2)`
  adds arguments and results; `(verbose 3)` adds macro expansions. A tail call is
  marked `>>` and sits at its caller's depth, which shows the constant-space
  behavior above. `(verbose n)` returns the previous level, so you can trace one
  call and restore it. `(backtrace)` prints the chain of calls you are inside.
  When an error escapes a script, the interpreter prints that chain; a function
  that tail-called its way out isn't listed, and a "[+1 tail call]" note
  accounts for it.
- **Stopping.** `(break f)` stops each time `f` is called; `(break f '(> balance 500000))`
  only when a condition on its parameters is true; `(break-on-error #t)` stops where
  an error happens. What a stop does is up to a **hook**, a procedure called with
  the reason, the function's name, and its arguments. `debugging_example.lsp`'s hooks
  print what they find (with `(locals)`, the variables where the program stopped)
  and then either return, to carry on, or `throw` to a `catch` further out,
  to give up gracefully. Because the hook does the looking, the example works the same
  in a script, in Jupyter, and in the GUI.
- **Profiling.** To find out *where the time goes*, `(profile 'f 'g ...)` counts and
  times the calls of any functions, ones you wrote and built-in ones alike, and
  `(show-profile)` prints a table. "Profiling", in the language manual, has the
  details; it is how the cost of the parser framework below was examined.

---

## Programs after Norvig's *Paradigms of AI Programming*

Peter Norvig's *Paradigms of Artificial Intelligence Programming* (1992) is a
book of AI programs in Common Lisp, taught by building them. Five programs in
`examples/` follow its chapters. They're written afresh for this interpreter, with
their own rules, grammars, and weights; Norvig's code is at
https://github.com/norvig/paip-lisp (MIT license), and reading the book next to
these is the best way to use either.

A few differences between the languages run through all five:

- **`#f` is the only false.** In Common Lisp `NIL` is false *and* the empty list;
  here `'()` is a true value. The book's pattern matcher has to invent a
  `no-bindings` value (`((t . t))`) so that "matched, with nothing bound" isn't
  mistaken for "failed". Here an empty list of bindings is simply true, and
  failure is `#f`.
- **Vectors hold numbers, strings, and dates.** Where the book keeps a polynomial
  in a vector, these keep it in a list; where it keeps a board in a vector of
  numbers, these do too — and get whole-board arithmetic for free.
- **A search returns a list of its answers.** The book goes on to faster designs for
  its Prolog (and compiles the clauses to Lisp); these programs keep the first, simplest
  idea: *return a list of every answer*, built with `append-map`. It is shorter to read, and
  quick enough at this size.

### ELIZA (chapter 5)

`eliza_example.lsp`. Joseph Weizenbaum's 1966 program holds a conversation
without understanding anything: it finds a pattern that fits what you typed and
answers from a template, reusing some of your own words.

```
You:   Well, my boyfriend made me come here.
ELIZA: Why do you say your boyfriend made you come here?
```

**Rules as data.** The whole behavior is one quoted list, `*eliza-rules*`: each rule
a pattern and some responses, and the first rule whose pattern matches wins, so
the most particular patterns come first and `((?* ?x))`, which matches anything,
is last. To teach ELIZA something you add data, not code. This is the first and
most useful technique here: when a program's behavior is a table, the table is
the thing to read, extend, and test.

**Pattern matching.** A pattern is a list of words; `?x` matches any one word; and
`(?* ?x)` is a *segment variable*, matching any number of words, none included.
`pat-match` returns the bindings, an association list, or `#f`:

```lisp
(load "eliza_example.lsp")        ; also runs its scripted conversation
(pat-match '((?* ?x) need (?* ?y)) '(i really need a long vacation) '())
                                  ; => ((?y a long vacation) (?x i really))
(pat-match '(i need ?x) '(i need help) '())      ; => ((?x . help))
(pat-match '(i need ?x) '(you need help) '())    ; => #f
(pat-match '(hello) '(hello) '())                ; => ()   -- matched, nothing to bind: still true
(pat-match '(?x and ?x) '(a and b) '())          ; => #f   -- ?x can't be both
(pat-match '(?x and ?x) '(a and a) '())          ; => ((?x . a))
```

Read `pat-match` and `match-variable` together: a variable already bound must match
what it matched before, which is how `(?x and ?x)` works. The matcher is a
`cond` with one clause for each kind of pattern, calling itself on the `car` and
the `cdr`, threading the bindings through. The `cdr` is matched with the bindings
from matching the `car`, and `(eq? bindings #f)` first in the `cond` makes a
failure short-circuit the rest.

**Segment matching is backtracking.** `segment-match` gives the variable the first
0 words, tries to match the rest of the pattern, and if that fails gives it 1 word,
then 2, and so on. The function is a dozen lines and the idea is a general one: *try a
choice, and if the rest fails, undo it and try the next*. (The book finds the next
word of the pattern in the input first, which prunes the search; trying every
length is simpler and quick for a sentence.)

**Text in, text out, with regular expressions.** The input is cut into words by
`regex-find-all "[a-z0-9]+"`, contractions are spelled out with `regex-replace`
("i'm" to "i am", so the patterns need only plain words), and sentences are split
at punctuation by `regex-split`. The last step shows a feature worth knowing:
`regex-replace` takes either a replacement string or a **procedure**, called with
each match:

```lisp
(fill-in "Why do you want ?y?" '((?y . (my vacation))))   ; => "Why do you want your vacation?"
```

`fill-in` finds each `?y` in the response with the regular expression `\?[a-z]+`
and replaces it, by a function, with the words `?y` matched — passed through
`switch-viewpoint`, a lookup in an association list that swaps "my" and "your",
"i" and "you", so "you hate me" comes back as "I hate you".

**Choosing among the matching phrases.** Real input has several phrases ("Well, my
mother made me come here"). ELIZA matches each phrase, and answers the one that
matched the *earliest* rule: `(sort matches car)` on `(position rule bindings)`
triples. So the mother counts for more than "Well".

Randomness is part of ELIZA (it picks one of a rule's responses at random), so the
scripted conversation begins `(random-seed 5)`: with a seed, a program with random choices
gives the same run each time, which is what lets the tests check its output.
To talk to it yourself: `(load "eliza_example.lsp")`, then `(eliza)` (it uses
`read-line`, which works at the console and in a notebook).

### Symbolic algebra (chapter 15)

`symbolic_algebra_example.lsp`. Two expressions that are equal should look alike.
Then simplifying is just converting to a **canonical form** and back.

```lisp
(load "symbolic_algebra_example.lsp")
(canon '((x + 1) * (x - 1)))                  ; => "x^2 - 1"
(canon '(d (3 * x ^ 2 + 2 * x + 1) / d x))    ; => "6*x + 2"
(canon '(x + y + y + x))                      ; => "2*x + 2*y"
```

**The representation does the work.** A polynomial is either a number, or a list of
its main variable and its coefficients, constant term first: `5*x^3 + 10*x^2 + 20*x + 30`
is `(x 30 20 10 5)`. A coefficient can itself be a polynomial in a variable that
comes *later in the alphabet*, so `x + y` is `(x (y 0 1) 1)` — a polynomial in `x`
whose constant term is `y` — and never `(y (x 0 1) 1)`. That one rule is what makes
each expression have exactly one form:

```lisp
(prefix->canon (infix->prefix '(x + y)))      ; => (x (y 0 1) 1)
(prefix->canon (infix->prefix '(y + x)))      ; => (x (y 0 1) 1)
```

**A constructor that keeps the invariant.** `make-poly` is the only way polynomials
are built: it drops zero coefficients from the top and collapses a polynomial of
degree 0 to its constant term:

```lisp
(make-poly 'x '(5 0 0))                       ; => 5
(make-poly 'x '(1 2 3))                       ; => (x 1 2 3)
(poly+poly '(x 1 1) '(x -1 -1))               ; => 0     -- (x+1) + (-x-1), and the zero is a plain 0
```

Because every operation ends in `make-poly`, the rest of the code can assume the
form is tidy. Whenever a data structure has an invariant, funnel construction through
one function that establishes it.

**Recursion that mirrors the data.** `poly+poly` and `poly*poly` look at which of
the two polynomials has the earlier main variable: if they share one, combine
coefficients term by term (each coefficient pair is itself added with `poly+poly`
— recursion into the nested polynomials); otherwise the one with the later variable
is just a constant, as far as the other is concerned, and goes into its constant term.
The derivative follows the same cases. A handful of short functions (`poly+poly`,
`poly*poly`, `poly^n`, `deriv-poly`, and their helpers) do all of the algebra.

**Reading infix: a recursive-descent parser in 40 lines.** Expressions are typed as
lists, `(3 * x ^ 2 + 2 * x + 1)`. `infix->prefix` turns that into
`(+ (+ (* 3 (^ x 2)) (* 2 x)) 1)` with one small function per level of precedence:

```
sum      ->  product (( + | - ) product)*
product  ->  factor (* factor)*
factor   ->  - factor | power
power    ->  primary [ ^ factor ]          ; ^ groups to the right: 2^3^2 is 2^(3^2)
primary  ->  number | variable | ( ... ) | d(...)/dx
```

```lisp
(infix->prefix '(3 * x ^ 2 + 2 * x + 1))      ; => (+ (+ (* 3 (^ x 2)) (* 2 x)) 1)
(infix->prefix '(2 ^ 3 ^ 2))                  ; => (^ 2 (^ 3 2))
```

Each function calls the one below it, so lower precedence is *higher up the chain*,
and `more` loops to collect `+ product + product` from the left. The helpers
(`peek`, `next!`, `sum`, `product`, ...) are defined *inside* `infix->prefix`, so
they all share its list of tokens, which `next!` pops. That is an idiom to
borrow whenever a function needs several mutually-recursive helpers that share state.
This is the same method that [`lib/parser.lsp` turns into a table](#a-language-from-a-table-the-parser-framework).

**Dispatch with `case`.** `prefix->canon` converts a prefix tree by its operator:
a `case` on `+`, `-`, `*`, `^`, `d`, with an `error` for anything else. And
`poly->string` writes the result back out, using a regular expression to tidy
`+ -` into `-` and to decide whether a coefficient needs parentheses.

### Othello (chapter 18)

`othello_example.lsp`. Othello, and programs that play it, from random moves up to
a search of several moves ahead.

**The board is a vector with a border.** The 8 × 8 board is stored in a vector of
100 numbers, a 10 × 10 grid whose outside rows and columns are a *border* of
`outer` squares. Square 11 is the top left, 18 the top right, 88 the bottom right.
That one decision simplifies everything after it:

- **Moving in a direction is adding a number**: `(+ square 1)` is the next square
  to the right, `(+ square 10)` the one below, `(+ square 11)` down and to the right.
  `all-directions` is just the list `(-11 -10 -9 -1 1 9 10 11)`.
- **The edge needs no special case.** Stepping off the board lands on a border
  square, which holds `outer`, which is no one's piece and no empty square; so the
  loop that follows a line of pieces stops there with no bounds check.

**Whole-board arithmetic.** Comparisons on a vector give a vector of 0s and 1s, so
`(= board player)` marks every square that player owns. Counting pieces is
`(vector-sum (= board player))`, and the square-weighting evaluation,

```lisp
(define (weighted-squares player board)
  (vector-sum (* *weights* (- (= board player) (= board (opponent player))))))
```

scores a position with no loop: each owned square's weight minus each of the
opponent's. The weights capture something real — a corner can never be flipped
(+100), the squares beside it give the opponent a way in (-25 and -50) — which is
why this beats counting pieces. (`othello_example.lsp` plays them against each
other to show it.)

**Strategies are closures.** A strategy is a procedure of the player and a copy of the
board that returns a square. `random-strategy` is one; `human` is one (it asks
you); and `maximizer` is a *function that returns a strategy*:

```lisp
(define (maximizer evaluate)
  "A strategy that takes the move whose result evaluate scores highest."
  (lambda (player board)
    ...tries each legal move on a copy of the board, keeps the best...))
```

`(maximizer count-difference)` and `(maximizer weighted-squares)` are two different
players built from the same code; `(alpha-beta-searcher 2 weighted-squares)` is a
third. The game loop, `othello`, neither knows nor cares which it was given: it calls
`(strategy player (vector-copy board))`. Passing a **copy** is deliberate, because
`make-move` changes the board it is given, and a strategy that experiments with moves
mustn't change the real game. When behavior varies, pass a function.

**Minimax, written as negamax.** To pick a move, look at every move, judge the
result from the opponent's side, and take the move that is worst for them. Since
the opponent judges by the same rules, a position's value to one player is *minus*
its value to the other, so one function serves both players:

```lisp
(let ((value (- (car (minimax (opponent player) (make-move move player (vector-copy board))
                              (- ply 1) evaluate)))))
  ...)
```

**Alpha-beta** returns the same answer from fewer positions. `alpha` is the value the
mover is already sure of, `beta` the most the opponent will allow; once a move is
worth `beta` or more, the opponent will never let the game get here, so the remaining
moves are skipped. In negamax form the window flips with the player, which is why the
recursive call passes `(- beta) (- alpha)`. The example prints both searches' answer
from the opening, and they agree.

Details worth a look: passing is handled by `next-to-play`; `loop` is used with
`thereis`, `until`, `while`, `by`, `count`, and `repeat`, a good tour of what it can do;
and `record-of` plays a tournament, which is deterministic because of `random-seed`.

A few calls show the pieces at work: black's moves from the opening, a move flipping a
piece (`make-move` changes the board it's given), and the two searches agreeing:

```lisp
(load "othello_example.lsp")                  ; also plays its demonstration games (about 9 seconds)
(legal-moves black (initial-board))           ; => (34 43 56 65)
(define board (initial-board))
(vector-ref board 44)                         ; => 2     -- a white piece
(make-move 34 black board)
(vector-ref board 44)                         ; => 1     -- flipped: black's 34 and 54 trapped it
(count-pieces black board)                    ; => 4
(car (minimax black (initial-board) 3 weighted-squares))                                 ; => 1
(car (alpha-beta black (initial-board) losing-value winning-value 3 weighted-squares))   ; => 1
```

**Try it.** `(load "othello_example.lsp")`, then
`(othello human (alpha-beta-searcher 2 weighted-squares) #t)` to play.

### Parsing English (chapter 19)

`nlp_parsing_example.lsp`. A phrase-structure grammar says what a sentence is made
of, and a parser finds *every* way the words can be put together, so it shows where
a sentence is **ambiguous**.

**The grammar is data.** A rule is `(category -> right-hand-side)`: a list of
categories for a phrase, or a single word for a word's category.

```lisp
(S -> (NP VP))   (NP -> (D N))   (NP -> (NP PP))   (VP -> (V NP))   (PP -> (P NP))
(D -> the)       (N -> man)      (N -> telescope)  (V -> saw)        (P -> with)
```

Changing the language the parser reads is changing a list. (`*grammar*` is a
variable the parser reads each time, and the last section swaps in another list.)

**A parse is `(tree . remaining-words)`**, a tree for a first part of the words and
the words it didn't use, and the parser returns a *list* of them. `parse` works
bottom-up: it looks up what the first word can be, and `extend-parse` builds up from
there, each time parsing the rest of the words for the category that's needed next.
Wherever there is a choice — a word that is two categories, a rule that can be
applied two ways — `append-map` collects the results of *all* the choices into one list:

```lisp
(load "nlp_parsing_example.lsp")
(length (parser (sentence "the man saw the woman with the telescope")))    ; => 2
(map bracketing (parser (sentence "the man saw the woman with the telescope")))
  ; => (((the man) ((saw (the woman)) (with (the telescope)))) ((the man) (saw ((the woman) (with (the telescope))))))
```

The two readings: he used the telescope to see her, or she had the telescope. This
"return a list of every success" style is how a program without built-in backtracking
does search, and you'll see it again in [the Prolog prover](#unification-prolog-and-grammars-that-run-both-ways-chapters-11-20-and-21)
and in KenKen's `combinations-for`. Each extra prepositional phrase multiplies the
readings (2, 5, 14, 42 — the Catalan numbers, as the example prints).

**Remembering.** The same words are parsed again and again — "the telescope" once for
every way of reaching it. Because a parse is always of the *end* of the sentence,
the words left are identified by *how many* there are, so the memo is a hash table
keyed by `(length words)`. The example counts the calls: 365 with the table, 7,761
without it, for the longest sentence. (`*remember?*` turns the table off so you can
see.) That is **memoization** in its simplest form, and the
[parser framework](#a-language-from-a-table-the-parser-framework) uses it the same
way, keyed by rule and place.

**Unknown words.** Rather than give up on "glorp", `unknown-word-rules` tries it as
each *open* category — noun, verb, adjective, name — and lets the rest of the sentence
decide. `"the glorp blicked a dog"` parses with `glorp` a noun and `blicked` a verb.

**Meanings.** Give each rule a fourth part: for a word, its meaning; for a phrase, a
*procedure* that combines the meanings of its parts. The same parser finds the trees;
`meaning` works the value out, finding the rule that built each node (`find-if`) and
`apply`ing its procedure to the meanings of the children. The example's grammar is
spoken arithmetic, where `plus` means `+`:

```lisp
(set! *grammar* *arithmetic*)
(meanings "two plus three times four")        ; => (20 14)     -- (2+3)*4 or 2+(3*4)
(meanings "ten minus four minus three")       ; => (3 9)       -- (10-4)-3 or 10-(4-3)
```

Functions as grammar data (`+` and `-` are entries in the table) is the technique to
notice: the grammar is both syntax and a little program.

### Unification, Prolog, and grammars that run both ways (chapters 11, 20, and 21)

`unification_grammar_example.lsp`. Logic programming, built in three layers.

**Unification** finds values for variables that make two expressions the same:
`(likes ?x terry)` and `(likes kim ?y)` unify with `?x = kim`, `?y = terry`.
`unify` returns the bindings or `#f`, the same convention as ELIZA's matcher, but
this one is symmetric (variables on both sides) and does the **occurs check**: `?x`
can't equal `(f ?x)`, which would be an infinite structure. `substitute` applies the
bindings, following a variable to its value and that to its value. Both are one `cond`
over the shapes of their two arguments.

**A prover** (a small Prolog). A clause is `(head goal ...)`, true if all the goals are;
`(<- (member ?item (?item . ?rest)))` is a fact. The clauses are kept in a hash table
by predicate. To prove a goal, rename the variables in each clause for that predicate,
unify the goal with the head, and prove the body goals; `prove-all` threads the
bindings from one goal to the next, and everything returns a *list of every answer*:

```lisp
(load "unification_grammar_example.lsp")        ; runs its demonstration too (about 5 seconds)
(solve-for '?m '((member ?m (a b c))))                        ; => (a b c)
(solve-for '(?front ?back) '((append ?front ?back (1 2 3))))
  ; => ((() (1 2 3)) ((1) (2 3)) ((1 2) (3)) ((1 2 3) ()))    -- append, run backwards
(meanings "Every dog barks.")                   ; => ((every ?x (dog ?x) (bark ?x)))
(meanings "The dogs sleeps.")                   ; => ()
```

Two lessons: `rename-variables` (each use of a clause needs variables of its own, else
the second use of `member` would clash with the first) and **relations, not functions**.
The same `append` clause that joins two lists also *splits* one: because a clause is a
fact about three lists, any of them can be the unknown. The `<-` macro is a tiny
language feature: `(<- head goal ...)` quotes its arguments and adds the clause, so
facts read like Prolog.

**Grammar rules as clauses.** A rule like

```lisp
(rule (S ?meaning) --> (NP ?n ?x ?vp ?meaning) (VP ?n ?x ?vp))
```

becomes a clause by giving each part two more arguments, the words where it starts
and the words left when it's done (`?s0` to `?s2` for the sentence, `?s0` to `?s1` for the
NP, and so on): `grammar-rule->clause` does that, and the `rule` macro calls it. A
word `(:word dog)` becomes `(= ?s1 (dog . ?s2))`: the words start with `dog`, and
`?s2` is the rest. This **difference-list** encoding means no grammar-specific parser at
all: a sentence is parsed by *proving* `(S ?meaning (the dog sleeps) ())`.

**Features by unification.** `(NP ?n ...)` and `(VP ?n ...)` share the variable `?n`
for number, sg or pl, so "the dogs sleeps" can't unify and has no parse, with no code
written for agreement. The same variables carry meaning: a noun phrase takes a
*scope* (the rest of the sentence, as a formula about `?x`) and builds a quantified
formula around it, so "every dog chases a cat" means
`(every ?x (dog ?x) (some ?y (cat ?y) (chase ?x ?y)))`.

**Backwards.** Because it is logic, the same grammar goes the other way: leave the
words a variable and give the meaning, and the prover finds the sentences. Parsing a
sentence and then generating from its meaning gives every sentence that means the
same: from "Every dog barks." the example gets both `(every dog barks)` and
`(all dogs bark)`. One catch is instructive: the meaning's
variables must be *frozen* first (`?x` to plain `x`) or they'd unify with whatever
the generator found, which is why `freeze` exists.

---

## A chess program

`chess.lsp` (with `chess_book.lsp` and `chess_example.lsp`). A chess program,
simple enough to read, that knows all the rules (castling, en passant, promotion,
check, checkmate, stalemate; not draws by repetition, the fifty-move rule, or
too little material), takes moves in standard notation, and looks ahead. It is
about a thousand lines in eight sections, and each section's comment says what the
code is doing. The techniques, in the order the program uses them:

**The board, as in Othello but sharper.** A vector of 120 numbers, 64 squares with a
border two deep (a knight's jump of two files can't wrap around), and pieces as
signed numbers: a white knight is 2, a black one -2. Signed pieces mean one
expression serves both sides: `(* side board)` makes the mover's pieces positive.

```lisp
(load "chess.lsp")
(define start (initial-position))
(list (file-of 21) (rank-of 21))               ; => (0 0)    -- square 21 is a1
(square 4 0)                                   ; => 25       -- e1: file 4, rank 0
(squares-of (position-board start) white)      ; => (21 22 23 24 25 26 27 28 31 32 33 34 35 36 37 38)
```

`squares-of` finds a side's pieces *without a loop*: it selects the square numbers
(`vector-select square-numbers mask`) where the signed board is between 0 and the
border value. Whole-vector arithmetic is how the program stays fast enough.

**Move generation: a table of directions.** A piece's way of moving is data: a
knight steps by one of `knight-jumps`, a bishop slides along `diagonals`, a queen along
`all-directions`. `generate-moves` has one local helper for stepping pieces
(`steps!`) and one for sliders (`slides!`), and one `cond` that picks by piece. Its
`captures-only` flag is the other thing to notice: the **search of captures**
(below) wants only captures and promotions, and move generation is about three-quarters
of the time spent on a position, so generating every move to throw most of them away
is wasteful. The one generator can produce either, and `capture-moves` is the fast path
(measured: the program makes exactly the same moves, in less time).

**A position is never changed.** `make-move` returns a *new* position (a copy of the
board vector with the move made). That makes the search code short: there is no
"undo", and a move tried and rejected leaves no trace. Mutation (Othello's
`make-move`) is quicker and trickier; immutability trades a copy per move for
code you can reason about.

**Legal means "doesn't leave my king attacked".** `candidate-moves` generates by the
way pieces move; `legal-moves` makes each and asks `in-check?`. And `attacked?`
doesn't generate the enemy's moves: it looks *outward from the square* (a knight's
jump away, along each ray to the first piece), asking "is there an enemy piece
that could land here?" — a much smaller question.

**Reading notation by writing it.** A move is typed as `e4`, `Nf3`, `exd5`, `O-O`,
`e8=Q`. Rather than parse that, the program does the reverse: it writes *each legal
move* in standard notation, and looks for the one that matches what was typed.
Disambiguation (`Nbd2` against `Nfd2`) is then only needed in the writing direction,
where the program knows exactly which other piece could also move there.

```lisp
(sort (map (lambda (m) (move->notation start m)) (legal-moves start)))
  ; => ("Na3" "Nc3" "Nf3" "Nh3" "a3" "a4" "b3" "b4" "c3" "c4" "d3" "d4" "e3" "e4" "f3" "f4" "g3" "g4" "h3" "h4")
(find-move start "Nf3")                        ; => (27 46)
(move->squares (find-move start "Nf3"))        ; => "g1f3"
```

**Evaluation by vector arithmetic.** How good a position is for white, in hundredths of
a pawn: material (`(vector-sum (= board knight))` counts white knights), plus
piece-square tables — arrays of 120 bonuses, one per square, built from eight rows
laid out the way a chess board is drawn (`board-table`), and turned over for black
(`flipped`) — multiplied by the same masks. `evaluate` is from the mover's side:

```lisp
(evaluate start)                               ; => 0
(evaluate (make-move start (find-move start "e4")))   ; => -40   -- black to move, white is ahead
```

**Negamax and alpha-beta**, as in Othello, plus the two things that make them work in
chess. *Move ordering*: alpha-beta prunes most when the best moves come first, so
moves are tried in order of `guess-value` (take a big piece with a small one first).
*Quiescence*: stopping at a fixed depth would count a queen that takes a defended pawn
as a pawn won, so at depth 0 the search goes on through the **captures only** until
the position is quiet, and only then evaluates; a king in check with no move is
scored as checkmate, which no evaluation of pieces sees.

**A table that remembers, and forgets.** Almost all the positions searched are in that
search of captures, and many repeat. `quiescence` remembers the result for each
position under a **position key** (`position-key`: a string of the pieces, whose move,
the castling still allowed, and the en passant square only if a pawn could use it —
so positions reached by different move orders share an entry):

```lisp
(equal? (position-key (play-moves start '("Nf3" "e5" "e4")))
        (position-key (play-moves start '("e4" "e5" "Nf3"))))     ; => #t
```

The subtlety is *what* is remembered. A search is given a window, alpha to beta, and
only finds the value if it's inside; otherwise it finds only that the value is
at most alpha or at least beta. So each entry is a value and which of three it is —
`exact`, `lower` (worth at least this), `upper` (at most) — and answers a later search
only if that is enough. The tables of the last three moves are kept and the oldest is
dropped, so memory doesn't grow. Positions that still have moves left aren't remembered:
in a search this short none comes up twice, and the last move's search was two moves
too shallow to reuse. These choices were *measured*, and the tests check the speedups
change no move chosen: the two together take a quarter to a third off the time.

**An opening book, from data.** Looking two or three moves ahead can't tell a good
opening from a bad one, and would play the same one every game. `chess_book.lsp` holds
16 games, each won by white or by black, and for each the first moves through the
winner's eighth, written as squares (`g1f3`, quick to read, where standard notation
takes about a tenth of a second a move). The book is built, the first time it's wanted,
into a table keyed by `position-key` — **positions, not move sequences**, so a
transposition finds its entry. `tools/make_chess_book.py` makes the file from PGN
(the standard game format) files that lichess.org publishes: it picks the games, and
reads *every* move of each with the chess program's own rules, so a move that isn't
legal in this program can't get into the book.

**Variety, without breaking the search.** To avoid the same game every time, a position's
score gets a small wiggle. A fresh random number each time a position is scored
would be wrong: the search could score one position two ways and could never agree with
itself. Instead the wiggle is a *pure function of the position*: the board dotted with a
vector of random numbers drawn once for each game (`*tastes*`), whose fractional part
picks a whole number of hundredths of a pawn from -3 to 3. Within a game the same
position always gets the same wiggle; across games it differs. Anything inside a
search must be a function of its inputs.

**Testing a chess program.** Chess has a gift for testers: *perft*, the number of move
sequences of a given length from a position, is known for many positions, and
a program that gets them all right has the rules right (castling, en passant, pins, and
promotions included).

```lisp
(count-positions start 1)                      ; => 20
(count-positions start 2)                      ; => 400
```

`chess_example.lsp` checks depths 1 to 3 from the starting position (20, 400, 8,902) and
the "Kiwipete" position (48, 2,039), then finds a checkmate, a knight fork, and a
sacrifice that mates in two. The tests add what a rewrite needs: the faster generator
and the table must choose exactly the moves the plain ones did.

**Try it.** `(load "chess.lsp")`, then `(play-chess)` (you're white; at depth 2 it
thinks a few seconds a move; `(play-chess :depth 3)` plays better and takes ten to
thirty; `:human black`; `:book #f :variety 0` for the same game every time). Type
`moves` to list the legal moves, `quit` to stop. `fen->position` makes a position from
Forsyth-Edwards Notation. In a Jupyter notebook the board is an HTML table of light and
dark squares, with Unicode chess pieces.

---

## A KenKen solver

`kenken_example.lsp`. KenKen is an N × N grid to fill with the digits 1 to N, no digit
twice in a row or column, such that each *cage* (a group of cells outlined in the
puzzle) comes out right: its digits, combined by the cage's operation, give its number.
A cell is written as its row and column (`23` is row 2, column 3), a cage as its cells
and its arithmetic:

| Cage | Means |
|---|---|
| `((11 12 13 23) (+ 17))` | the four digits add up to 17 |
| `((31 41) (- 2))` | the larger digit less the smaller is 2 |
| `((32 33) (* 12))` | the digits multiply to 12 |
| `((34 44) (/ 3))` | the larger digit divided by the smaller is 3 |
| `((42) (= 4))` | the digit is 4 |

```lisp
(load "kenken_example.lsp")              ; solves its own three puzzles first (about ten seconds)
(define puzzle
  '(((11 21 22) (+ 9))  ((12 13) (* 3))     ((14) (= 2))
    ((23 24 34) (+ 9))  ((31 32 41) (+ 4))  ((33 43 44) (* 18))
    ((42) (= 4))))
(solve-kenken 4 puzzle)                  ; ((4 3 1 2) (3 2 4 1) (2 1 3 4) (1 4 2 3)), a list of rows
(length (kenken-solutions 4 puzzle))     ; 1 -- the puzzle has exactly one solution
(show-kenken 4 puzzle :solution (solve-kenken 4 puzzle))
```

(`kenken-solutions` returns up to `:limit` solutions, default 2, so its length says
whether a puzzle has exactly one; a puzzle that isn't well formed — a cell in two
cages, or none — is an error that says what's wrong. In a notebook, `show-kenken`
draws the grid with the cages outlined.)

A KenKen is a **constraint satisfaction** problem, and this is the classic way to
solve one: *propagate* what the constraints force, and only *guess* when that stalls.

**State: what each cell could still be.** The solver keeps a hash table from cell to
the list of digits it might be, and from cage to the list of digit combinations that
still make the cage's arithmetic come out. `combinations-for` computes a cage's
combinations once, up front, by trying digits cell by cell and dropping a partial
fill that can't work (`could-still-come-out?`: a partial sum already too big, a
partial product that no longer divides the target) — a **search that returns the list
of every success**, as in the Norvig chapters.

**Rules that only take things away.** Each rule is about one *group* of cells — a cage,
a row, or a column — and removes possibilities:

- A cage rule (`apply-cage!`): drop the combinations that need a digit some cell
  can't be, then restrict each cell to the digits that some remaining combination
  puts there.
- A line rule (`apply-line!`): a digit settled in one cell is out for the rest of
  the row or column; and a digit that fits in only one cell of the line goes there.

**A work list, not a sweep.** The obvious way to apply rules until nothing changes is
to keep sweeping over every group. `rule-out!` is smarter: a group's rule is worth
re-applying only if one of its cells *lost a digit* since it last ran, so groups wait
in a to-do list, and when a cell loses a digit, its cage, row, and column are put on
the list unless they're already on it (a hash table remembers who is waiting). This
**worklist algorithm** is how every constraint propagator and dataflow analyzer works.

**Contradiction is `throw`.** A rule that leaves a cell with no digits, or a cage with no
combinations, has found that this branch of the search is impossible. Deep inside the
rules, `(throw 'impossible #f)` abandons the whole propagation at once, to a
`(catch 'impossible ...)` in the solver. That is what non-local exit is for: no
error value is threaded back through a dozen functions, each checking.

**Guess, copy, backtrack.** When propagation stalls, `kenken-solutions` picks the
unsettled cell with the *fewest* digits left (the guess most likely to be forced),
tries each of its digits in turn on a **copy** of the state (`copy-of`, using
`hash-table-copy`), and propagates again. If the copy hits a contradiction it's simply
dropped — "going back" is just *not using the changed copy* — so there is no undo code.
The 4 × 4 and 6 × 6 puzzles in the file need no guesses at all, and take well under a
second; the 9 × 9 one, which gives no digits and has large cages, takes about 10 seconds
and some guessing (`*guesses*` counts them).

Three smaller techniques in the file: `defstruct` for `cage`, `group`, `puzzle`, and
`possibilities` (the state, so it can be copied as a unit); `loop for (cells . cage) in ...`
destructuring in a `loop` clause; and `check-puzzle`, which validates its input first and
raises precise `error`s, so a mistake in a puzzle never becomes a mystery in the solver.

---

## Languages

### A language from a table: the parser framework

`lib/parser.lsp` turns the hand-written recursive descent of the
[algebra reader](#symbolic-algebra-chapter-15) into a **table**: you write what the
tokens look like (regular expressions) and what each part of the language is made of
(rules with actions), and the library does the parsing. Its reference is "A parser
framework", in the language manual; `parser_example.lsp` is the guided tour, and the
SQL interpreter (below) is its largest user. The calculator from the manual:

```lisp
(load "parser.lsp")

(define-grammar calculator
  (token skip   "\\s+")                              ; spaces: read, and thrown away
  (token number "\\d+(?:\\.\\d+)?"  string->number)  ; the text is made a number
  (token symbol "[-+*/()]")

  (rule expression ((chain term ("+" . +) ("-" . -))))
  (rule term       ((chain factor ("*" . *) ("/" . /))))
  (rule factor     (number))
  (rule factor     ("(" expression ")")))

(grammar-parse calculator "2 + 3 * (4 - 1)")         ; => (+ 2 (* 3 (- 4 1)))
(eval (grammar-parse calculator "2 + 3 * (4 - 1)"))  ; => 11
```

What to see in it:

- **A grammar is a table of rows**, one per line: `token` rows and `rule` rows.
  `define-grammar` is a **macro** that turns the rows into data: it leaves the names and
  the rule bodies alone (quoted) and evaluates the regular expressions and actions.
  A DSL like this is the main reason to write a macro.
- **The tree is Lisp.** `("+" . +)` makes the node `(+ left right)`, so `eval` runs the
  parse. A calculator is a *compiler to Lisp* in six lines, and the same idea compiles a
  SQL condition or a spreadsheet formula.
- **Ordered choice with backtracking.** Rows with the same name are alternatives, tried
  in order, and a failed alternative is backed out of. This is a **parsing expression
  grammar** (PEG) — recursive descent without the burden of writing it.
- **Memoization makes it linear.** Alternatives that begin alike would be re-parsed (a
  parenthesized expression nested 40 deep, with three alternatives each beginning with
  `"(" e ")"`, would take 3⁴⁰ tries). The library remembers what each rule found at each
  place in the tokens, so the work is in proportion to the length of the text. The test
  that checks it counts how many times a rule's action runs.
- **The lexer is one regular expression.** The token rows are joined into one pattern with
  a group each, `regex-find-all` cuts the whole text in one pass, and the group that
  matched says which row did. A character no row matches becomes a token of kind
  `unknown`, which no rule accepts, so it is an error where it is.
- **Error messages are designed.** The parser remembers the *furthest* place it got to and
  what it was looking for there: `expected ) but found the end of the input`. Failures at
  the place where an *optional* part would have begun are kept apart and listed only
  if nothing else could come, so `(2 + 3` doesn't answer "expected one of + - * / ) ...".
  A `describe` row names a rule for messages (`"an expression"`), and a rule that
  begins with itself — which would loop forever — is detected and explained.

`parser_example.lsp` goes on to a second language: **a settings file** (`name = value`
lines in `[sections]`, `#` comments) whose result is a *table*, built with
`table-from-rows`, so it can be queried like any other: the parser is the bridge from
text in a file to the interpreter's tables. Look at how it deals with line ends: a
*rule* used as an item always passes its value to the rule that uses it, so the
end-of-line matcher is written inline, `(drop (or newline end))`, in each rule that
needs it — `drop` matches without producing a value.

### SQL: an interpreter over tables

`sql.lsp` (with `sql_example.lsp`). An SQL interpreter in about a thousand lines that
works on **the interpreter's own tables** — the ones `load-csv`, `load-sqlite`, and
every data source produce — and returns tables you can chart, fit a regression to, or
query again.

```lisp
(load "sql.lsp")
(sql "CREATE TABLE t (a INTEGER, b TEXT)")                       ; => "table t created"
(sql "INSERT INTO t VALUES (1, 'x'), (2, 'y'), (3, NULL)")        ; => "3 rows added"
(table-column (sql "SELECT a * 2 AS twice FROM t WHERE b IS NOT NULL") "twice")   ; => #(2 4)
```

With a table you already have, `(sql-register-table! "loans" (load-csv "loans.csv"))`
gives it a name, and `(show-sql "SELECT state, SUM(balance) AS upb FROM loans GROUP BY state")`
prints the answer. It handles `SELECT` (joins on equal columns, `GROUP BY`, `HAVING`,
`ORDER BY`, `LIMIT`, `DISTINCT`), `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE`, and
`DROP TABLE`; "An SQL interpreter" in the language manual lists exactly what it
understands and where it differs from most SQL databases. The file is in six sections,
each a technique:

**1. The database.** A hash table of tables, with the kind of value of each column
(number, text, date) kept beside it, because a table doesn't say, and an `INSERT`
needs to know that a missing number is `nan` and a missing piece of text is `'()`.

**2. The grammar.** The parser framework, as above: token rows (keywords are a kind
of their own, built from the list of reserved words, so a name can't be one) and about
sixty rule rows. Look at how the expression rules are layered from loosest to tightest
(`OR`, `AND`, `NOT`, comparisons, `+ -`, `* / %`, a minus sign, a primary), each rule a
`chain` of the next. The comparison rule is a good small study in **closures as parse
results**: `a LIKE 'x%'`, `a IS NULL`, `a BETWEEN 1 AND 5` each parse to a *procedure
that takes the left operand and builds the tree*, so one rule, `(sum (opt comparison-tail))`,
attaches whichever tail came:

```lisp
(rule comparison (sum (opt comparison-tail)) apply-tail)
(rule comparison-tail ("is" (flag "not") "null")
  (lambda (negated) (lambda (left) (list (if negated 'is-not-null 'is-null) left))))
```

The result is a tree of lists, `(add (col "x") (num 1))`, and a `select-query` struct.
All of a script is parsed before any of it runs, so a typo in the last statement
stops them all.

**3. Expressions — whole columns at a time.** `evaluate` takes a tree and a *table* and
returns a **vector with a value for each row**, built with the vector functions: a number
is a vector of that number repeated, a column is the table's column, `a + b` is
`vector-add`, and a condition is a *mask*, 1 for each row it's true of, which
`table-filter` uses. There is no loop over rows anywhere in the evaluator.

```lisp
(define t (table-from-rows '((1 "x") (2 "y") (3 ())) '("a" "b")))
(evaluate '(greater (col "a") (num 1)) t)             ; => #(0 1 1)
(evaluate '(add (col "a") (num 10)) t)                ; => #(11 12 13)
(evaluate '(is-null (col "b")) t)                     ; => #(0 0 1)
```

**NULL, and a lesson in three-valued logic.** In SQL a comparison with NULL is neither true
nor false but *unknown*, and `NOT unknown` is unknown, so `WHERE NOT (a > 5)` must not keep
the rows where `a` is missing. A vector of 0s and 1s has no way to say "unknown", so the
interpreter never applies `NOT` to a mask. It turns the condition around instead
(`opposite`), pushing the negation down to the comparisons, where the answer is right
because a comparison with a missing value is already false:

```lisp
(opposite '(less (col "a") (num 5)))                  ; => (greater-equal (col "a") (num 5))
(opposite '(and (less (col "a") (num 5)) (is-null (col "b"))))
  ; => (or (greater-equal (col "a") (num 5)) (is-not-null (col "b")))     -- De Morgan, too
```

That works because the vector comparisons treat a missing value as `nan` does: equal to
nothing, less and greater than nothing, and so only `/=` is true of it — a rule the
interpreter's comparison builtins follow for numbers, text, and dates alike, and which
building this program is what made them do.

**4. Groups.** `GROUP BY` and the aggregates are `table-group-by`, which wants columns
to group by and aggregates to find. The interpreter builds columns for everything it
needs (the group expressions, and what each aggregate adds up), calls it, and then
**rewrites the select list, `HAVING`, and `ORDER BY`** to refer to the new table's
columns, so `SUM(x) * 12` becomes "the column of sums, times 12". A column that is
neither grouped nor inside an aggregate has no column to refer to, which is exactly the
error SQL gives. (An aggregate over no rows, a `SUM` of nothing but NULLs, and the
rest of the corners are handled with the rules SQL has for them.) Rewriting a tree so
a later stage can evaluate it is a general **compiler** technique.

**5. SELECT.** The steps in the order SQL *means* them, each one table function:
`FROM` and `JOIN` (`table-join`, after turning the `ON` equalities into key columns),
`WHERE` (`table-filter`), groups, `HAVING` (`table-filter` again), the select list
(`evaluate`), `DISTINCT` (`table-group-by` on every column), `ORDER BY` (`table-sort`,
once for each key, last key first, which works because `table-sort` keeps ties in order),
and `LIMIT` (`table-slice`). Reading a query as a pipeline of table operations is the
way to understand SQL.

**6. The rest** — `INSERT`, `UPDATE` (every assignment sees the values from before), `DELETE`,
`CREATE`, `DROP` — and `sql`, `show-sql`, and `sql-repl` to run them.

**How it was tested.** The tests are worth reading as a method. The same statements are
run through Python's own **`sqlite3`** and through this interpreter, and the rows compared:
a list of queries; 400 random `WHERE` conditions with `AND`, `OR`, `NOT`, `IN`,
`BETWEEN`, `LIKE`, and NULLs; random `GROUP BY` and join queries; and every `UPDATE`,
`DELETE`, and `INSERT`, with the whole table compared afterward. Comparing with an
independent implementation on random inputs found bugs in the *builtins* underneath
(comparing text with a missing value was an error; a table with no rows spoiled the type
of what was appended to it), which were fixed there, not worked around. Then **deliberate
breakage**: the program was broken in 36 specific ways (turn `<` around, drop the
`NULL` check, reverse the sort order) and the tests had to notice each one. A test suite
that has never been seen to fail isn't known to test anything.

---

## Models of money

### Models as columns of formulas

`mortgage_amortization_example.lsp`, `sofr_floating_rate_example.lsp`, and the
library behind them, `lib/column_engine.lsp`. A structured-finance deal is a table in
which each column is a formula about the others and about its own previous row — a
spreadsheet. The column engine lets you write it that way:

```lisp
(load "column_engine.lsp")
(defcolumn interest
  :value_calculation (* (lag balance 1) 0.01))
(defcolumn principal
  :value_calculation (- 100 interest))
(defcolumn balance
  :initial_value 1000
  :value_calculation (- (lag balance 1) principal))
(calculate-all *columns* 4)       ; shows the table: interest, principal, balance for 4 rows
```

**Formulas are quoted data.** `defcolumn` is a macro that quotes `:value_calculation` for
you. (`make-column`, the plain constructor, is a function, so a formula given to it
unquoted would be evaluated once, immediately: an easy mistake the macro removes.) The engine stores each
formula as a *list* and `eval`s it, once per row, with each column's name bound to a
number — so a formula reads like the algebra: `(- 100 interest)`. `(lag balance 1)` is
the balance a row back.

**Ordering by dependence.** Columns can be written in any order. `calculate-all` sorts
them with a **topological sort** (Kahn's algorithm: repeatedly take the columns whose
prerequisites, the `:after` slot, are done), and says "circular or missing `after`
dependency" if it can't. `defcolumn` fills `:after` in with the previous column, so a
plain sequence chains in the order written, and only branch and merge points need it
spelled out.

**Two passes per row, so references both ways work.** Before a row's formulas run,
every column's name is bound to its *previous* row's value; then each formula runs in
sorted order and overwrites its binding with the fresh value. So a column sees the
*current* row's value of a column calculated before it and the *previous* row's of one
calculated after, with no unbound-variable errors.

**The same name again: a waterfall.** The four-tranche deal in
`mortgage_amortization_example.lsp` pays interest and principal to tranches in turn out
of a pool of `cash`. It does so by *redefining* the column `cash` after each payment:

```lisp
(defcolumn int_a :value_calculation (min cash (* (lag bal_a 1) periodic_mortgage_interest_rate)))
(defcolumn cash  :value_calculation (- cash int_a))     ; what's left after A's interest
(defcolumn int_b :value_calculation (min cash ...))
(defcolumn cash  :value_calculation (- cash int_b))
```

`find-column` resolves a name used more than once to the nearest definition at or before
the column being calculated, so each stage sees the cash left by the stage before — the
text of the program reads like the deal's "priority of payments". The Z bond
(accretion bond) section is a careful example of getting an either/or rule right
without branching in two places: while senior tranches are outstanding, its interest
isn't paid (it just isn't taken from the pool), so the cash is automatically available
to speed their principal.

**Caveats the file itself states.** A column's name becomes a real global variable while
it is calculated (so a column called `list` would shadow the builtin), and a column's
series is a vector, which holds numbers: use 1 and 0, not `#t` and `#f` (the example
says so beside `z_locked_out`). Read the file as an *approach*, not the only one.

The example also folds a prepayment model (`lib/prepayment_model.lsp`, PSA-style
speeds with a refinancing-incentive term) into the collateral's cash flows, driven by a
SOFR forward curve from `sofr-forward-curve`: market data flowing all the way through
into a deal's cash flows. It needs a tastytrade sign-in for that piece alone (comment out the
SOFR section to run it offline), and it writes the cash flow tape to a CSV with
`write-csv`.

### Statistics and optimization

These need no network. They are mostly *data in, library call, report out*, and each is
a short script to copy from.

- **`prepayment_demo.lsp`.** An end-to-end modeling session on `synthetic_mbs_pools.csv`
  (32,460 pool-months): load it with `load-csv`, suggest knots for the refinancing-incentive
  curve (`suggest-knots`), split the data 70/30 after shuffling the columns together
  (`vectors-shuffle`, with a seed, so the same rows move together), fit a
  `spline-logistic` model (a spline on the incentive, a spline on loan age, and a
  categorical predictor, whether the pool is for refinancing), report it
  (`model-report`), evaluate on the held-out part (`model-evaluate`), predict at a few
  incentives, and chart the fitted curve with `plot-chart`. The pattern — shuffle, split,
  fit, evaluate on data the model hasn't seen — is the discipline to copy.
- **`regression_kinds_example.lsp`.** Six kinds of regression on the same made-up data (a
  straight line by least squares and by least absolute deviation, a logistic S-curve, and
  splines fit each of the three ways), then the logistic ones again with a `:floor` and
  `:ceiling`, a band (`spline-quantile`), and a table comparing how well each model *fits*
  with how well it *predicts* data it wasn't fit to (`cross-validate`). Two points are put
  deliberately out of line (a pool sold off; a month the data was wrong), to show what
  least squares makes of an outlier and what least absolute deviation makes of it. The
  data is generated, with `random-seed`, and the vector arithmetic of
  `(+ (vector-map s-curve incentive) noise)` is a good example of building test data
  without a loop.
- **`stratify_example.lsp`.** A table of 5,000 made-up loans, built column by column with
  `make-table`, and the stratification report (`stratify-all`): eight small tables, each
  with a row per bucket of one column and, in every row, the loans' count, balance, share of
  the pool, and balance-weighted averages. Replace the made-up table with a
  `with-sqlite` query to run it on real data (the comment in the file shows how).
- **`linear_programming_example.lsp`.** Invest $100 million in four mortgage pools to earn
  as much as possible, within limits on concentration, duration, and credit risk. The
  problem is written in a text file (`linear_programming_example.txt`) in a small language
  (a variable for each pool, then the constraints, naming them), read by `lp-read-file`, and
  solved by `lp-solve`. The technique to notice is that **the problem comes back as ordinary
  Lisp data**, an association list with `"variables"`, `"objective"`, `"rhs"`, and so on,
  so the script can build a *changed copy* with `map` (a small `replace-nth` swaps one
  right-hand side) and solve again: "the most income for each limit on average duration" is
  a loop over six copies of the problem. It ends with a limit no mix of the pools can meet,
  and shows that `lp-solve` reports an infeasible problem as an error that `catch-error`
  catches. Separating the *problem* (data, in a file) from the *solver* (code) means a
  portfolio manager can edit the first without touching the second.
- **`oas_monte_carlo_example.lsp`** (60 seconds; the **live** version uses real data). The
  option-adjusted spread pipeline from `lib/oas_monte_carlo.lsp`: a forward curve from par
  yields, paths of a two-factor rate model that start on it, a mortgage cash flow for each path,
  and the spread that reproduces a market price. All of the inputs in this version are made up, which makes the pipeline
  runnable anywhere and its stages easy to follow; the live version
  (`oas_monte_carlo_live_example.lsp`) swaps in the Treasury's curve, a model fitted to option prices,
  and the mortgage rate and its spread over the 10-year yield, and writes a report that
  separates what was fetched from the one number (the price) that is still an assumption.

---

## Prices, options, and trades

Four of these scripts are **thin**: `option_methods_example.lsp` is 24 lines,
`call_spread_example.lsp` 38, `option_spreads_example.lsp` 47, and
`option_positions_example.lsp` 46, a few calls of a library, a display of the result, and
the charts of it. The
work, and the explanation, are in the library (`lib/option_methods.lsp`, `lib/call_spreads.lsp`,
`lib/option_spreads.lsp`, `lib/option_positions.lsp`), whose header says how it works; the
script is there to show the call. That is a deliberate convention for this project: put the work in `lib/*.lsp`
functions that can be called from a notebook, and keep the example to the call. The others
here are longer tours: a series of steps, each with a comment saying what it shows.

- **`option_methods_example.lsp`** takes a stock's symbol as a command-line argument
  (`(command-line-arguments)`, with `destructuring-bind` and `&optional` giving a default),
  and shows the stock's listed options valued three ways — Black-Scholes, a binomial tree,
  and Monte Carlo paths copied from the stock's own history — next to the market's bids and
  asks, and the chance each ends in the money by each method. A table of options, in
  columns, with one valuation per method: the library is `lib/option_methods.lsp`.
- **`call_spread_example.lsp`** takes a stock, an expiration, and the price you expect, and
  ranks every pair of calls (buy the lower strike, sell the higher) by the profit at your
  price as a share of the most you can lose. It shows the best spreads, and a chart of the
  best one's profit on the expiration day against the price the stock might have then (saved
  in `call_spread_profit.png`: flat at a loss below the lower strike, rising to a flat gain
  above the higher), and **sends no order**;
  the comments show how to go on to prepare one and have Schwab preview it. The library,
  `lib/call_spreads.lsp`, has tests that check its search against a plain brute force
  on random chains.
- **`option_spreads_example.lsp`** is the same for seventeen kinds of position: it takes a stock, a
  kind (`bull-call`, `bear-put`, `iron-condor`, `long-strangle`, `long-call`, `covered-call`,
  `collar`, ...), an expiration, and the price you expect, and ranks every position of the kind
  by the profit at your price as a share of the most you can lose. It sends no order either,
  and charts the best position in detail (`option_spreads_profit.png`) and the best three on
  one chart to compare (`option_spreads_compared.png`). The interesting part is in the
  library, `lib/option_spreads.lsp`: it finds the spreads of every kind without a loop over
  strikes — the strikes become whole numbers of cents, so that "the same strike" and "the
  same width" are exact comparisons, and three vector builtins do the matching:
  `vector-grid` makes every pair of positions, `vector-positions` finds where each wanted
  strike is in a column (-1 if it isn't), and `vector-gather` picks the rows — and then
  finds each spread's greatest loss, greatest gain, and breakevens for all the spreads at
  once, by using the fact that a spread's profit is a line that bends only at its strikes.
  The tests check every kind against a plain Python calculation that tries every price from
  0 up in steps of a quarter, on random chains with several roots.
- **`option_positions_example.lsp`** takes the same three words as `call_spread_example.lsp` --
  a stock, an expiration, and the price you expect -- and shows the best position of *every*
  kind in one ranking, with simply owning the stock among them. It is a layer over the one
  above: `lib/option_positions.lsp` runs the search of each kind (the same function, with the
  kind as the only difference) and puts the first row of each in a table, so there is no new
  mathematics, only a comparison. What it shows is how much the answer depends on what is
  compared: by the ratio of profit to the most you can lose, a butterfly or a condor tops the
  list if you expect the stock to end where it pays, and the stock itself, which can lose all of
  its price, is near the bottom; none of that says which is the better bet, only what each
  makes at the one price you gave. It charts the profits of the best few of the kinds that
  are options alone together (`option_positions_profit.png`), and the stock with what a
  covered call, a protective put, and a collar do to it (`option_positions_hedged.png`).
  Its kinds with shares are the lesson in how a plain
  position is built out of parts: the shares are one leg whose worth is the stock's price, the
  options are the others, the cost adds them, and the profit's slope at the top — the shares,
  and the calls bought less sold — says whether the gain is limited.
- **`option_payoffs_example.lsp`** needs no account or network: it makes up a stock and its
  options (Black-Scholes prices, with a bid and ask a little either side), finds the best
  position of each of the seventeen kinds for a price you expect, and draws what each pays: its
  profit on the expiration day, up the side, against the stock's price, along the bottom, green
  where it gains and red where it loses. It saves six pictures: one position in detail (the
  iron condor, with the points where it breaks even, the most it can make and lose, and the
  price expected marked); the best few options-only positions on one chart (the three butterflies
  come out nearly the same line: a butterfly of calls, of puts, or of both is the same bet); the
  stock and its three hedges; and a gallery of every kind in three figures, one panel for each.
  The pictures are not kept in the repository: run the script to make them. The charts are
  `plot-option-profit`, `plot-option-positions`, and `option-profit-panel` (for `plot-panels`)
  in `lib/option_spreads.lsp` and `lib/option_positions.lsp`. How they are drawn is the lesson:
  a position's profit is a line that bends only at its strikes, so the chart is drawn through
  the strikes and through the breakevens (where it crosses 0) as well as a grid of prices, which
  makes the corners sharp and the green and red meet exactly at 0, with no cleverness in the
  plotting: the gain and the loss are two filled series, the profit clipped above 0 and below it.
- **`investment_paths_example.lsp`** simulates an investment's future prices by copying blocks
  of consecutive days from its own history (a block bootstrap, which keeps the way returns
  cluster that independent days would lose), a thousand paths with a different seed for each so the
  run is repeatable, and then values an option on them. It also shows why dividends matter:
  Schwab's prices aren't adjusted for them, so a return computed from the prices alone is low
  by what the stock pays.
- **`option_chain_example.lsp`** treats an option chain as a *table*: one column per field.
  Part 2 filters it a column at a time: `with-columns` makes each column it names a variable
  holding the whole column, comparisons give masks, `vector-and` combines them, and
  `table-filter` keeps the rows. Part 3 looks at one option at a time: `table-rows` gives
  each as a row, and `with-struct` makes its fields variables, so a test reads like a
  sentence (`(> implied-volatility 0.20)`). Part 4 summarizes by expiration with
  `table-group-by`. A value tastytrade didn't report is missing, and a comparison with a
  missing value is false, so an option with no open interest never passes a test on open
  interest.
- **`vol_smile_example.lsp`** fits the model in `lib/vol_smile.lsp` to a chain: for each
  expiration, a least-absolute-deviation fit of total variance to log-moneyness and its
  square, and shows the options furthest out of line with the rest of their smile (the
  ones whose price, at the bid or the ask, the fit says is off: a possible trade). It then
  fits one surface across all the expirations at once, and draws the first smile.
- **`tastytrade_example.lsp`**, **`sofr_floating_rate_example.lsp`**: the live-data end of the same
  pipelines.
- **`rate_paths_example.lsp`** takes a path of interest rates apart, and needs no key. A path is today's
  forward curve (the Treasury's, downloaded) bent by two random numbers, and the program shows each stage and
  what is read from it: the curve's own par yields; a path with no volatility (which **is** the forward curve, read
  forward in time: the program checks the short rate and the 10-year yield against the curve's); the two
  factors; one path's curve three years on, next to today's (a chart); what the path reports from that curve;
  and 200 paths, whose average discount factor is the curve's (the program prints both, 3 basis points apart).
  The second chart shows seven paths, the one followed, and the curve with no volatility, over the factors of the
  path followed. The library manual's
  [Interest rate paths](lisp_library_reference.md#interest-rate-paths-the-two-factor-model) says how to make them.
- **`note_option_example.lsp`**: the same rate model, fitted to a different market: options on
  the 10-year Treasury note future (ZN). The SOFR options show how much the short rate moves; a
  mortgage depends on the long end, and these show how much that moves. It reads the options with
  `note-option-rows`, finds the volatility of the model's long-end factor for which the model's
  Monte Carlo prices are nearest the market's (`calibrate-to-note-options`), and prints the
  model's prices and implied volatilities beside the market's (`note-option-comparison`),
  then charts the volatility each price implies by strike: the market's is a smile, the
  model's nearly flat. The library manual's
  [Fitting the model to option prices](lisp_library_reference.md#fitting-the-model-to-option-prices)
  says how it works, and why the Treasury's curve, not SOFR's, is the one the paths are centered on.
- **`rate_model_example.lsp`**: the short version of the whole pipeline. It fits the model to SOFR
  options and to 10-year note options together (`calibrate-rate-model`), then draws 200 paths of
  rates with the fitted model (`simulate-rate-paths`) and charts eight of them: the 10-year
  yield and the short rate. The paths start where the market is today, and spread as the
  options say they should.

Most of these need the market open, for live bids and asks, and credentials; each file's
header says which. The libraries behind them, and the functions they call, are in the
[library manual](lisp_library_reference.md).

## Economic data and pictures

`fred_example.lsp`, `sec_example.lsp`, `fdic_example.lsp`, `census_bls_example.lsp`, and
`bea_example.lsp` show one data source each: a few calls and what they return. The
section for each is in the [library manual](lisp_library_reference.md#getting-data) and
[economic_data_guide.md](economic_data_guide.md) says which agency publishes what.
`census_bls_example.lsp` and `bea_example.lsp` show how the sources fit together: the
data functions return **tables**, so a Census table and a BEA table can be matched on a
shared key and charted, as `map_example.lsp` does.

`yield_curve_example.lsp` needs no key: it downloads the Treasury's daily par yield curve and
the Federal Reserve's fitted curve (`treasury-par-curve`, `gsw-curve`), works out the zero
rates of each -- the Treasury's by bootstrapping its par yields, the Fed's from its six-number
Svensson curve -- and charts them together, then the one-month forward rates a model of interest
rates starts from. The Treasury's are rougher than the Fed's smooth ones, as the second chart
shows. The functions are in the library manual's
[Yield curves](lisp_library_reference.md#yield-curves-the-treasurys-and-the-feds) section.

`plot_chart_example.lsp` needs nothing, and is a tour of `plot-chart` in eleven small
charts: a monthly line over grouped quarterly bars on one date axis; stacked bars with
their total; text X values as categories in order of first appearance; a scatter plot
with a fitted line (made with `linear-regression` and `model-predict`); two scales, with
the margin on a secondary axis (`:secondary #t`); bars on their side (`:horizontal #t`); a
log scale; shading, reference lines, and notes; a band and values printed on the bars; a
histogram (`plot-histogram`); and panels that share an X axis (`plot-panels`).
`map_example.lsp` draws the Census Bureau's outlines (`census-shapes`) with `plot-map`:
each place colored by a value (per capita income for every county, on a log scale) or a
symbol sized by one, with the states' borders drawn on top.

---

`report_example.lsp` needs nothing: it writes reports, `mortgage_report.txt`, `mortgage_report.md` and `client_letters.txt`, from made-up
tables, and shows them. A report is described by one value, a **spec**, made by `make-report-spec`, that holds its
templates (a page's header and footer, a row, and the header and footer of each group and of the whole report, with
`{{name}}` where a value goes) and the columns the groups are of (`make-report-break`); `write-report` does the rest. The
mortgage report has two levels of break, the state and the zip code within it, each with a footer of its totals (a count, a
sum, and a balance-weighted average rate), a header for the state that is written again, saying "(continued)", where a state
goes over to a new page, and a total for the whole report; its pages say "page X of Y", have a footer with the page's own
total and the running total so far, and each row shows the running total of its state. `write-report-html` writes the same
report as a web page (`mortgage_report.html`: open it in a browser) that shows a page at a time, with a bar at the bottom to
go to the next page, the one before, or any page; and `mortgage_report.md` is it as Markdown (`:markdown #t`), a table of the loans under a heading for each state. The letters have one level, the client, which starts a new page and numbers its pages
from 1, and a variable (the month) that a template can say. The library manual's
[Reports with control breaks](lisp_library_reference.md#reports-with-control-breaks) has everything a spec can say, and what
each template can use.

---

`notebooks/widgets_example.ipynb` is a notebook for the `morris_lisp` kernel (it needs `ipywidgets` and `ipydatagrid`) that shows what
widgets do: three sliders that work out a mortgage payment as they move, written with `widget-slider` and `widget-capture`; and a
table of loans in an editable grid (`table-grid`), with a function that hears each edit (`grid-on-edit`) and a button that shows
the table as the user has changed it (`grid-table`). The manual's [Widgets in a
notebook](lisp_interpreter_reference.md#widgets-in-a-notebook) has everything the functions take.
The last section of the notebook is a grid of CMO tranches: click one, and a panel of tabs opens under it (a floater's cap, the bands of a PAC, a split), with fields to fill in and a **Go** button, made by `widget-actions`.

---

`deal_example.lsp` needs nothing. It models a structured deal as a tree: the collateral, a pool of mortgages that pays principal each
month, is the root, and **splits** divide the principal among tranches, which can be divided again until the bonds at the leaves.
Here the pool goes to two tranches in order (`deal-sequential!`), the first to two bonds in order, and the second to two in proportion
to what each is owed (`deal-pro-rata!`). The program builds the deal for a slow and for a fast prepayment speed, runs it
(`deal-run!`), checks that the principal adds up in every month (`deal-check`), and shows the month each bond is paid off and the
first months' principal in a table. A second part divides a pool into a PAC and its companion (`deal-pac!`), sized from the pool at
100% and 300% PSA, and shows what the PAC owes after five years by schedule and in fact at five speeds: exactly on schedule at any
speed between the two, and off it outside; and a second PAC out of the first one's companion, sized from what the companion is paid at
two narrower speeds. The library manual's [Structured
deals](lisp_library_reference.md#structured-deals-a-tree-of-tranches) says what each part is and how to make another kind of split.

## Writing an example

The examples share conventions, which `CLAUDE.md` states as a purpose: *the software is
to help people understand things*, so code is written to be read.

- **A header comment** that says what the program does, how to run it (from the
  `examples/` directory, with its arguments), what it needs (credentials, network,
  market hours), and where it's documented. For a program with a design, say the design
  first, as `chess.lsp`, `kenken_example.lsp`, and `sql.lsp` do.
- **Numbered sections** with a comment block each, explaining *why*, not restating the
  code. `chess.lsp` has eight, `sql.lsp` six.
- **Docstrings** on functions (`(define (f x) "What it does." ...)`); a variable's
  description goes in a comment, because a string after a `define` of a variable
  would become its value.
- **A program and a script.** Put reusable work in a program or library file that
  can be `load`ed (`chess.lsp`, `lib/*.lsp`); keep the script to a demonstration.
  Take arguments with `(command-line-arguments)`.
- **Make it repeatable.** Seed random numbers (`random-seed`, or a seed argument) so
  a run, and a test of it, is the same each time.
- **Test it.** An offline example goes in `FAST_EXAMPLES` (or `SLOW_EXAMPLES` if it takes
  more than a few seconds) in `tests/test_programs.py`, with assertions on what it prints.
  A program with rules (chess, SQL, the parser framework) gets tests of its own, and the
  best tests are the ones in this document's examples: **known answers** (perft),
  **comparison with another implementation** (`sqlite3`, `eval`, `json`),
  **random inputs**, and **deliberate breakage** to see that the tests notice.
- **Add it here.** A new example gets a row in the tables at the top of this document and
  a section, and `python3 tools/make_contents.py` rebuilds the contents.
- **Keep this document honest.** `tests/test_reference_doc.py` runs every ` ```lisp ` block here
  that has a `; =>` result, and fails if the interpreter gives something else. The blocks of a
  section run one after another in one environment, so a section loads a program once, as a
  reader would; the quick programs can be loaded (the list is `_LOADABLE_IN_EXAMPLES_DOC`
  in that file), and a block that loads a slow one is not run. The same test checks that
  every link in the documents goes to a file and a heading that exist.
