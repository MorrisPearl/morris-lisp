#!/usr/bin/env python3
"""A simple Lisp interpreter with numeric-vector and date datatypes, an XY
charting/regression facility, FRED economic-data access, and a PyQt6 GUI.

Supports:
  - integers, floats, strings, symbols, booleans
  - cons cells (pairs) and lists built from them
  - a vector datatype (of numbers and/or dates), written #(1 2 3) or built
    with (vector ...)
  - a simple date datatype: (date year month day)
  - special forms: quote, quasiquote (with unquote/unquote-splicing,
    written `, ,, and ,@), if, define, set!, lambda, begin, let, let*,
    cond, and, or, dolist, defmacro, defstruct
  - macros: (defmacro name (params...) body...) defines a macro --
    unlike a procedure, its arguments are the CALL SITE's UNEVALUATED
    source expressions, and its body's return value (typically built
    with quasiquote) becomes new code that's evaluated in place of the
    macro call. Lets you write control constructs (a custom `while`,
    `swap!`, `unless`, ...) that a plain function can't, because a
    function's arguments are always evaluated before it ever runs. Macro
    calls in tail position keep the same constant-stack-space guarantee
    ordinary tail calls get (see expand_macro() / the note below)
  - variadic procedures AND macros: a `lambda`/`define`/`defmacro`
    parameter list can be a proper list (a b c) (fixed arity, as before),
    a DOTTED list (a b . rest) (a and b fixed, rest collects every
    further argument into a list), or a single bare symbol not wrapped in
    parens at all, e.g. (lambda args ...) (every argument collected, no
    fixed ones) -- see parse_params(). The reader supports the dotted-pair
    syntax `(a . b)` generally, not just in parameter lists, so it also
    works as an ordinary way to build an improper cons cell from source
  - CL-style KEYWORD ARGUMENTS for `lambda`/`define`/`defmacro`: a
    parameter list's tail can be `&key name (name2 default-expr) ...`
    instead of a rest parameter -- e.g. (lambda (a &key (b 10) c) ...) --
    called as (f 1 :b 20 :c 30), in any order, each optional. A keyword
    symbol like :name is its own self-evaluating datatype (Keyword, a
    Symbol subclass), so it never needs quoting at a call site. See
    parse_params()/Env.__init__/Keyword
  - defstruct: (defstruct name slot...) -- CL-style record types, each
    slot a bare symbol (default '()) or (slot-name default-expr). Defines
    make-<name> (a keyword-argument constructor -- an ordinary example of
    the &key feature above, not a separate mechanism), <name>-<slot>
    accessors, <name>-<slot>-set! setters (mutable slots), and a <name>?
    predicate. See LispStruct/LispStructType and the "defstruct" case in
    eval_special_form. Generic struct-ref/struct-set!/struct-type-name/
    struct? builtins also work on any struct instance by slot-name symbol
  - metaprogramming builtins: (eval expr) evaluates a piece of Lisp code
    (data -- e.g. built with quasiquote, or read from a string/file) in
    the top-level environment; (apply f arg1 ... args) calls f with
    arg1... as individual arguments followed by the elements of the
    final list argument `args`; (gensym ["prefix"]) returns a symbol
    guaranteed not to collide with anything in the program, for writing
    your own hygienic macros by hand; (load "path.lsp") reads and
    evaluates a file's top-level forms into the current environment,
    exactly as if you'd typed them yourself
  - built-in arithmetic, comparison, list, string, date, and vector
    procedures (including vectors-map, the multi-vector generalization
    of vector-map: apply a procedure across corresponding elements of
    several vectors at once, with a choice of what to do when they're
    not all the same length -- stop at the shortest, or pad the rest
    with a default value)
  - linear, logistic, and piecewise-linear spline regression, with one or
    more X predictors (linear-regression / logistic-regression /
    spline-regression), a plain-language report of a fitted model
    (model-report), and evaluation of a model's quality on held-out data
    it wasn't fit on (model-evaluate) -- together with vector-take/
    vector-drop/vectors-shuffle for splitting data into a training subset
    and a remaining subset. spline-regression adds a bit of non-linearity
    by expanding each predictor into hinge (piecewise-linear) basis
    functions at a handful of knots -- with an exact, independent maximum
    knot count per predictor if wanted -- and can optionally fit that
    expanded basis with a logistic link instead of ordinary least squares,
    for a probability-in-[0,1] output
  - GUI builtins to plot one X vector against several Y vectors (each
    with its own marker symbol, optionally connected by line segments),
    with an optional single-predictor linear or logistic regression line,
    and a builtin (save-chart) to save the most recent chart to an image
    file (PNG/PDF/SVG), which works with or without the GUI running
  - a builtin to fetch a data series (as a pair of vectors: dates and
    values) from the FRED database at the Federal Reserve Bank of St. Louis,
    and a builtin (load-csv) to load a CSV file's columns as vectors
  - builtins to fetch real broker data from tastytrade (futures term
    structure, and option chains -- for CME futures products or for
    any equity symbol -- with streamed implied volatility), plus pure
    (no-networking) rich/cheap curve analysis of a fetched futures
    curve, via a local JSON credentials file -- see
    tastytrade-futures-curve, tastytrade-futures-curve-rows,
    tastytrade-option-chain, tastytrade-curve-fit,
    tastytrade-leg-carry, tastytrade-test-connection, and
    tastytrade-products (this is the full functionality of the
    tasty_api/ desktop app, ported here as plain builtins -- see
    tasty_api/relative_value.py for the methodology behind
    tastytrade-curve-fit/tastytrade-leg-carry). Requires the
    `tastytrade` package (pip install tastytrade) and a tastytrade
    account; see tasty_api/README.md for the one-time OAuth setup

The code favors clarity and simplicity over efficiency or completeness.

IMPORTANT: the evaluator (`seval`) does NOT use Python function recursion
to walk the Lisp expression tree. Instead it drives an explicit stack of
"control frames" (a plain Python list) in a loop. This means deeply
recursive Lisp programs -- even non-tail-recursive ones -- are limited only
by available memory, not by Python's own call-stack / recursion limit.

TAIL CALLS specifically get more than just "won't hit Python's recursion
limit": a procedure call in TAIL POSITION -- the last thing a function
body does, including through if/let/let*/cond/and/or/begin/dolist -- is
handled by pushing the callee's body directly on top of the SAME control
stack, with no leftover "resume the caller here" frame underneath. So a
self- or mutually-tail-recursive loop runs in CONSTANT control-stack
space, not space proportional to the number of iterations: e.g.
`(define (count-down n) (if (= n 0) 'done (count-down (- n 1))))` uses
the same tiny, fixed amount of control-stack space whether n is 10 or
10,000,000 (verified: the control stack's peak depth doesn't grow with
n). This falls out of the explicit-stack design above, not from any
special-cased "is this a tail call?" check. A MACRO call gets the same
treatment: its expansion is pushed as a plain EVAL frame rather than
evaluated right away, so a macro-defined looping construct used in tail
position (see the module docstring's `defmacro` entry) is just as
constant-stack-space as a hand-written one -- verified the same way, up
to hundreds of thousands of iterations.

CAVEAT: the constant-stack-space guarantee only covers ordinary
`(f arg...)` application syntax (which macro calls desugar into, via
their expansion) -- not calls made INDIRECTLY through a higher-order
builtin. `(apply f args)`, `(eval expr)`, `(load "file.lsp")`, a callback
passed to `map`/`filter`/`reduce`/`vector-map`/`vectors-map`, or a macro
transformer's OWN body while it's still being run to PRODUCE an expansion
(see `expand_macro`) all call back into `seval` via an ordinary
(recursive) Python function call (see `apply_proc`), so those paths are
still bounded by Python's own recursion limit. This is a real, narrower limitation, not an oversight:
trampolining those too would mean turning them into resumable coroutines
integrated with the same control stack, a much larger change than the
immediate need called for. In practice it rarely matters for macros
specifically -- a transformer builds a piece of code, it doesn't loop
over runtime data -- but it's worth knowing about.

GUI: running this file with no arguments opens a small PyQt6 window with
an input box, an output/history log, a QTableView "Columns" tab, and a
chart tab (with its own "Save Chart..." button). The Columns tab is
populated ONLY by an explicit call to the `display-columns` builtin --
(display-columns (list (cons "name1" vector1) (cons "name2" vector2) ...))
-- there's no automatic scan of top-level variables; see column_engine.lsp
for a defstruct/keyword-argument-based library that builds this list of
(name . vector) pairs from registered "column" struct instances (for e.g.
a mortgage amortization table). Calling one of the `plot-xy...` builtins
draws a chart in the Chart tab. PyQt6 is only imported when the GUI is
actually launched, so the console/batch mode below works fine without it;
matplotlib alone (no PyQt6 needed) is enough for save-chart to work even
in console/batch mode.

STARTUP INIT FILE: every fresh environment -- batch mode, the console
REPL, and the GUI alike -- automatically loads DEFAULT_INIT_FILE
(init.lsp, next to this script; override with the LISP_INIT_FILE
environment variable) before doing anything else, via load_init_file().
It's entirely optional: a missing init file is silently skipped, so this
doesn't change behavior for anyone who doesn't have one. Put your own
always-available definitions/macros there instead of re-(load)-ing them
by hand in every script.

OUTPUT REDIRECTION: (redirect-output "path.txt" [append?]) sends
everything display/newline/print write to a file instead of the console/
GUI log, until (reset-output) switches back -- see those builtins in
make_global_env(). Useful for a script that wants to log its own output
to disk (including from the init file, if you want every session logged).

"""

import sys
import os
import csv
import math
import json
import random
import asyncio
import concurrent.futures
import inspect
import calendar
import datetime
import sqlite3
import urllib.request
import urllib.parse

verbose_mode = 0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class Symbol(str):
    """A Lisp symbol. Subclassing str lets us reuse Python's string
    machinery while still being able to tell symbols apart from Lisp
    strings (which are represented by the separate LispString class)."""
    pass


class LispString(str):
    """A Lisp string literal. Kept as its own subclass of str (distinct
    from Symbol) so `string?` and `symbol?` can tell the two apart."""
    pass


class Keyword(Symbol):
    """A keyword symbol, e.g. :name -- written with a leading colon (kept
    as part of the stored name, so printing is free). Unlike an ordinary
    Symbol, a Keyword is SELF-EVALUATING (see seval()'s EVAL case), exactly
    like a number or #t/#f, so it can be used directly as a call-site
    marker in keyword-argument calls, e.g. (make-column :name "balance"
    ...), without needing to be quoted. See parse_params()/Env.__init__
    for the &key parameter-binding side of keyword arguments."""
    pass


class Pair:
    """A cons cell: the basic building block of Lisp lists."""
    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr

    def __eq__(self, other):
        return isinstance(other, Pair) and self.car == other.car and self.cdr == other.cdr

    def __repr__(self):
        return to_string(self)


NIL = None  # represents the empty list '()


class LispVector:
    """A fixed-size, mutable vector of numbers and/or dates -- e.g.
    #(1 2 3.5) or a vector of LispDate values. Kept deliberately simple:
    just a thin wrapper around a Python list."""

    def __init__(self, items):
        self.items = list(items)

    def __eq__(self, other):
        return isinstance(other, LispVector) and self.items == other.items

    def __repr__(self):
        return to_string(self)


class LispDate:
    """A simple calendar date, e.g. (date 2020 1 15). Wraps a Python
    datetime.date so charts can format it nicely on an axis."""

    def __init__(self, year, month, day):
        self.date = datetime.date(year, month, day)

    def __eq__(self, other):
        return isinstance(other, LispDate) and self.date == other.date

    def __lt__(self, other):
        return isinstance(other, LispDate) and self.date < other.date

    def __repr__(self):
        return self.date.isoformat()


class LispSQLiteConnection:
    """An open SQLite database, from (sqlite-open "path/to/db.sqlite").
    Thin wrapper around sqlite3.Connection so it's an ordinary, passable-
    around Lisp value (bound to a variable, stored in a struct, etc.) --
    see sqlite_open_fn/sqlite_query_fn/sqlite_execute_fn/sqlite_close_fn."""

    def __init__(self, path):
        self.path = str(path)
        # isolation_level=None -> autocommit: every statement (SELECT
        # or otherwise) takes effect immediately, with no separate
        # sqlite-commit/sqlite-rollback builtin needed. Without this,
        # sqlite3's default mode silently defers INSERT/UPDATE/DELETE
        # in an open transaction that's lost if the connection is
        # closed (or never committed) -- surprising for a single
        # (sqlite-execute conn "INSERT ...") call, which reads as a
        # complete, self-contained action.
        self.connection = sqlite3.connect(self.path, isolation_level=None)

    def __repr__(self):
        return "#<sqlite-connection %s>" % (self.path,)


class LispSQLiteCursor:
    """An in-progress SQL query, from (sqlite-execute conn "SELECT ...").
    Wraps a sqlite3.Cursor -- repeated (sqlite-fetch-row cursor) calls
    pull one row at a time until the query is exhausted."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __repr__(self):
        return "#<sqlite-cursor>"


class LispStructType:
    """The record type created by (defstruct name slot...) -- see
    eval_special_form()'s "defstruct" case. Just metadata: the type's
    name and its ordered slots (Symbol slot_name, default_expr_or_None).
    Slot order is preserved everywhere a struct of this type is printed
    or its constructor's keyword arguments are bound, matching the
    source's declaration order."""

    def __init__(self, name, slots):
        self.name = name            # Symbol
        self.slots = slots          # [(Symbol slot_name, default_expr_or_None), ...]

    def __repr__(self):
        return "#<struct-type %s>" % (self.name,)


class LispStruct:
    """An instance of a defstruct-defined record type: a struct_type plus
    a mutable dict of slot_name -> value. Structural equality (like
    Pair/LispVector) rather than CL's identity-based `eql`, since this
    language doesn't otherwise distinguish the two."""

    def __init__(self, struct_type, values):
        self.struct_type = struct_type
        self.values = values        # dict: Symbol slot_name -> value

    def __eq__(self, other):
        return (isinstance(other, LispStruct)
                and self.struct_type is other.struct_type
                and self.values == other.values)

    def __repr__(self):
        return to_string(self)


def _date_from_pydate(pydate):
    """Wrap an existing datetime.date as a LispDate without re-validating
    year/month/day (used by date-add-days and the FRED-data loader)."""
    obj = LispDate.__new__(LispDate)
    obj.date = pydate
    return obj


class Procedure:
    """A user-defined function (closure) created by `lambda` or `define`.

    rest_param (a Symbol, or None): if set, this procedure is variadic --
    it accepts any number of arguments beyond its fixed `params`, and
    they're collected into a list bound to rest_param. See parse_params()
    (which builds params/rest_param from source syntax like
    `(a b . rest)` or a bare `args`) and Env.__init__'s rest_param
    handling (which does the actual binding at call time)."""

    def __init__(self, params, body, env, rest_param=None, keyword_specs=None):
        self.params = params      # list of Symbol FIXED parameter names
        self.rest_param = rest_param
        self.keyword_specs = keyword_specs or []  # see parse_params()
        self.body = body          # list of body expressions
        self.env = env            # environment in which it was defined

    def __repr__(self):
        return "#<procedure>"


class Macro:
    """A macro transformer created by `defmacro`. Structurally identical
    to a Procedure (params/rest_param/body/env), but invoked completely
    differently: a Procedure call evaluates its arguments first and binds
    the results; a Macro call binds its parameters to the CALL SITE's
    argument expressions UNEVALUATED (as plain source-code data --
    Symbols, Pairs, literals), runs its body to compute a new expression
    (the "expansion"), and that expansion is evaluated in place of the
    original call, in the CALLING environment. See expand_macro() and the
    macro-call check in seval(). rest_param works the same way it does
    for a Procedure -- see that class's docstring -- except what it
    collects is unevaluated expressions rather than values."""

    def __init__(self, params, body, env, rest_param=None, keyword_specs=None):
        self.params = params
        self.rest_param = rest_param
        self.keyword_specs = keyword_specs or []  # see parse_params()
        self.body = body
        self.env = env

    def __repr__(self):
        return "#<macro>"


class LispError(Exception):
    """Raised for any runtime or parse error in the interpreter."""
    pass


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(text):
    """Turn source text into a flat list of token strings."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == ';':                      # comment runs to end of line
            while i < n and text[i] != '\n':
                i += 1
        elif c == '#' and i + 1 < n and text[i + 1] == '(':
            tokens.append("#(")             # start of a vector literal
            i += 2
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == "'":
            tokens.append("'")
            i += 1
        elif c == '`':
            tokens.append('`')
            i += 1
        elif c == ',':
            if i + 1 < n and text[i + 1] == '@':
                tokens.append(',@')
                i += 2
            else:
                tokens.append(',')
                i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    escapes = {'n': '\n', 't': '\t', '"': '"', '\\': '\\'}
                    buf.append(escapes.get(text[j + 1], text[j + 1]))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            tokens.append('"' + "".join(buf) + '"')
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n()'\"`," and text[j] != ';':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


# ---------------------------------------------------------------------------
# Reader / Parser
# ---------------------------------------------------------------------------

def parse(text):
    # This is a generator function, mainly so that if there is an
    # error we can see where the error is (by seeing what has already been
    # processed before the error.
    """Parse source text into a list of top-level Lisp expressions."""
    tokens = tokenize(text)
    while tokens:
        yield read_from(tokens)
    return

def read_from(tokens):
    if not tokens:
        raise LispError("unexpected end of input")
    token = tokens.pop(0)
    if token == "(":
        items = []
        tail = NIL
        while tokens and tokens[0] != ")":
            if tokens[0] == ".":
                tokens.pop(0)  # consume '.'
                tail = read_from(tokens)   # the dotted tail -- e.g. (a b . c)
                break
            items.append(read_from(tokens))
        if not tokens:
            raise LispError("missing ')'")
        tokens.pop(0)  # discard ")"
        result = tail
        for item in reversed(items):
            result = Pair(item, result)
        return result
    elif token == "#(":
        items = []
        while tokens and tokens[0] != ")":
            items.append(read_from(tokens))
        if not tokens:
            raise LispError("missing ')' for vector literal")
        tokens.pop(0)  # discard ")"
        return LispVector(items)
    elif token == ")":
        raise LispError("unexpected ')'")
    elif token == "'":
        return list_to_pairs([Symbol("quote"), read_from(tokens)])
    elif token == "`":
        return list_to_pairs([Symbol("quasiquote"), read_from(tokens)])
    elif token == ",":
        return list_to_pairs([Symbol("unquote"), read_from(tokens)])
    elif token == ",@":
        return list_to_pairs([Symbol("unquote-splicing"), read_from(tokens)])
    else:
        return atom(token)


def atom(token):
    """Convert a single token into a number, string, boolean, or symbol."""
    if token.startswith('"') and token.endswith('"'):
        return LispString(token[1:-1])
    if token == "#t":
        return True
    if token == "#f":
        return False
    if token.startswith(":") and len(token) > 1:
        return Keyword(token)
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return Symbol(token)


# ---------------------------------------------------------------------------
# Conversions between Python lists and Lisp (Pair-based) lists
# ---------------------------------------------------------------------------

def list_to_pairs(items):
    result = NIL
    for item in reversed(items):
        result = Pair(item, result)
    return result


def pairs_to_list(p):
    items = []
    while isinstance(p, Pair):
        items.append(p.car)
        p = p.cdr
    return items


def parse_params(params_expr):
    """Parse a lambda/define/defmacro parameter spec into (fixed_names,
    rest_name_or_None, keyword_specs) -- used to give Procedure and Macro
    variadic ("rest parameter") and keyword-argument support. params_expr
    may be:
      - a proper list, e.g. (a b c) -- fixed arity, no rest parameter;
        rest_name is None
      - an improper (dotted) list, e.g. (a b . rest) -- a and b are
        ordinary fixed parameters; rest is bound to a LIST of every
        additional argument beyond the fixed ones (possibly empty)
      - a single bare symbol not wrapped in parens at all, e.g. the
        `args` in (lambda args body) or (define (f . args) body) -- every
        argument, with no fixed ones at all, is collected into that name
      - a proper list whose tail is the marker symbol &key followed by
        keyword-parameter specs, e.g. (a b &key c (d 10)) -- a and b are
        ordinary fixed (positional) parameters; c and d are CL-style
        keyword parameters, supplied at the call site as :c value / :d
        value pairs AFTER the fixed arguments, in any order, each
        optional. A bare spec (c) means "default to '()"; a spec (name
        default-expr) supplies an explicit default, evaluated per call
        (see Env.__init__'s keyword_specs/default_eval handling). &key
        and a dotted/bare-symbol rest parameter are mutually exclusive in
        this implementation. keyword_specs is [] when &key isn't present.
    See Env.__init__ for how the actual binding at call time works.
    """
    if isinstance(params_expr, Symbol):
        return [], params_expr, []
    fixed = []
    p = params_expr
    while isinstance(p, Pair) and p.car != Symbol("&key"):
        fixed.append(p.car)
        p = p.cdr
    if isinstance(p, Pair) and p.car == Symbol("&key"):
        keyword_specs = []
        p = p.cdr
        while isinstance(p, Pair):
            spec = p.car
            if isinstance(spec, Pair):
                keyword_specs.append((spec.car, spec.cdr.car))
            else:
                keyword_specs.append((spec, None))
            p = p.cdr
        return fixed, None, keyword_specs
    return fixed, (p if p is not NIL else None), []


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class Env(dict):
    """A mapping of names to values, with a link to an enclosing (outer)
    environment. Together, a chain of Envs implements lexical scoping.
    (This chain follows *lexical nesting*, not call/recursion depth, so it
    stays shallow even for deeply recursive Lisp programs.)"""

    def __init__(self, params=(), args=(), outer=None, rest_param=None,
                 keyword_specs=None, default_eval=None):
        """params: the FIXED parameter names (never includes the rest
        parameter, if any). rest_param: None for an ordinary fixed-arity
        call (the original, unchanged behavior -- args must match params
        exactly in count), or a Symbol to bind to a list of every
        argument beyond the fixed ones (possibly empty) -- see
        parse_params(), which is what Procedure/Macro construction uses
        to split a parameter spec into these two pieces.

        keyword_specs (list of (Symbol name, default_expr_or_None), or
        None/empty for none): when non-empty, `params` are bound
        positionally as usual, and every arg beyond that is expected to
        come in :key value pairs (see parse_params()'s &key docs). Each
        keyword_specs name is bound from the matching pair if supplied;
        otherwise to `default_eval(default_expr, self)` if a default was
        given, else to NIL. default_eval lets the SAME binding logic serve
        both procedure calls (args already evaluated; a default should be
        evaluated too, in this new environment -- see the module-level
        eval_default()) and macro expansion (args are unevaluated source
        expressions; a default should be used as-is -- see
        raw_default())."""
        super().__init__()
        self.outer = outer
        params = list(params)
        args = list(args)
        if keyword_specs:
            n_fixed = len(params)
            if len(args) < n_fixed:
                raise LispError(
                    "expected at least %d argument(s), got %d" % (n_fixed, len(args)))
            for p, a in zip(params, args[:n_fixed]):
                self[p] = a
            tail = args[n_fixed:]
            if len(tail) % 2 != 0:
                raise LispError(
                    "keyword arguments must come in :key value pairs, got a "
                    "trailing unpaired argument: %r" % (tail[-1],))
            supplied = {}
            for i in range(0, len(tail), 2):
                k, v = tail[i], tail[i + 1]
                if not isinstance(k, Keyword):
                    raise LispError("expected a keyword (e.g. :name), got %r" % (k,))
                supplied[Symbol(str(k)[1:])] = v
            for name, default_expr in keyword_specs:
                if name in supplied:
                    self[name] = supplied.pop(name)
                elif default_expr is not None:
                    self[name] = default_eval(default_expr, self)
                else:
                    self[name] = NIL
            if supplied:
                raise LispError(
                    "unknown keyword argument(s): %s"
                    % ", ".join(":%s" % n for n in supplied))
        elif rest_param is None:
            if len(params) != len(args):
                raise LispError(
                    "expected %d argument(s), got %d" % (len(params), len(args)))
            for p, a in zip(params, args):
                self[p] = a
        else:
            if len(args) < len(params):
                raise LispError(
                    "expected at least %d argument(s), got %d" % (len(params), len(args)))
            for p, a in zip(params, args):
                self[p] = a
            self[rest_param] = list_to_pairs(args[len(params):])

    def find(self, name):
        """Return the innermost Env in which `name` is bound."""
        e = self
        while e is not None:
            if name in e:
                return e
            e = e.outer
        raise LispError("unbound symbol: %s" % name)

    def lookup_or_none(self, name):
        """Like find(), but returns None instead of raising when `name`
        isn't bound anywhere in the chain. Used by seval() to check
        whether an operator symbol names a macro without disturbing the
        ordinary "unbound symbol" error path for everything else (a
        symbol this returns None for just falls through to being
        evaluated as an operator/argument as usual, which raises that
        same error itself if it truly isn't bound)."""
        e = self
        while e is not None:
            if name in e:
                return e[name]
            e = e.outer
        return None


def eval_default(expr, env):
    """The default_eval strategy for an ordinary PROCEDURE call: a keyword
    argument's default expression is evaluated, like any other expression,
    in the new call environment (see Env.__init__)."""
    return seval(expr, env)


def raw_default(expr, env):
    """The default_eval strategy for a MACRO expansion: a keyword
    parameter's default is used AS-IS -- unevaluated source -- exactly
    like every other macro parameter binding (see expand_macro())."""
    return expr


# ---------------------------------------------------------------------------
# Evaluator -- explicit-stack version
# ---------------------------------------------------------------------------
#
# Rather than have seval() call itself recursively to evaluate sub-
# expressions (which would use up Python's own call stack), we keep an
# explicit "control stack" of pending work and an explicit "value stack" of
# results computed so far, and drive them with a plain while-loop.
#
# A control frame is a tuple whose first element is a tag string:
#
#   ('EVAL', expr, env)             -- evaluate expr in env
#   ('APPLY', nargs)                -- apply a procedure to nargs arguments
#   ('SEQ', remaining_exprs, env)   -- discard a value, then run the rest
#                                      of a body/begin sequence
#   ('IF', conseq, alt, env)        -- choose a branch once the test is in
#   ('DEFINE', name, env)           -- finish a (define name expr)
#   ('SET', name, env)              -- finish a (set! name expr)
#   ('COND', clauses, env)          -- try the next cond clause
#   ('COND_BRANCH', body, rest, env)-- act on a cond test's result
#   ('AND', exprs, env)             -- evaluate remaining `and` operands
#   ('AND_CHECK', rest, env)        -- act on one `and` operand's result
#   ('OR', exprs, env)              -- evaluate remaining `or` operands
#   ('OR_CHECK', rest, env)         -- act on one `or` operand's result
#
# Frames are pushed onto control_stack (a Python list) and popped off in
# LIFO order, exactly mirroring what Python's own call stack would have
# done -- except it is a plain list under our control, so its size is
# limited only by memory, not by sys.getrecursionlimit().

SPECIAL_FORMS = {
    "quote", "if", "define", "set!", "lambda",
    "begin", "let", "let*", "cond", "and", "or", "dolist",
    "defmacro", "quasiquote", "breakpoint", "defstruct",
}


def is_true(x):
    """Everything except #f counts as true (including '() and 0)."""
    return x is not False


def push_sequence(exprs, env, control_stack, value_stack):
    """Push frames to evaluate a body (list of expressions) in order,
    discarding all but the value of the last one. Used for `begin`,
    procedure bodies, and cond/let clause bodies."""
    if not exprs:
        value_stack.append(NIL)
    elif len(exprs) == 1:
        control_stack.append(('EVAL', exprs[0], env))
    else:
        control_stack.append(('SEQ', exprs[1:], env))
        control_stack.append(('EVAL', exprs[0], env))


def eval_cond(clauses, env, control_stack, value_stack):
    if not clauses:
        value_stack.append(NIL)
        return
    first, rest = clauses[0], clauses[1:]
    test = first.car
    body = pairs_to_list(first.cdr)
    if test == Symbol("else"):
        push_sequence(body, env, control_stack, value_stack)
    else:
        control_stack.append(('COND_BRANCH', body, rest, env))
        control_stack.append(('EVAL', test, env))


def eval_and(exprs, env, control_stack, value_stack):
    if not exprs:
        value_stack.append(True)
    elif len(exprs) == 1:
        control_stack.append(('EVAL', exprs[0], env))
    else:
        control_stack.append(('AND_CHECK', exprs[1:], env))
        control_stack.append(('EVAL', exprs[0], env))


def eval_or(exprs, env, control_stack, value_stack):
    if not exprs:
        value_stack.append(False)
    elif len(exprs) == 1:
        control_stack.append(('EVAL', exprs[0], env))
    else:
        control_stack.append(('OR_CHECK', exprs[1:], env))
        control_stack.append(('EVAL', exprs[0], env))


def desugar_let(args):
    """(let ((x1 v1) (x2 v2) ...) body...)
       => ((lambda (x1 x2 ...) body...) v1 v2 ...)"""
    bindings = pairs_to_list(args.car)
    body = args.cdr  # already a Pair-list, reused as the lambda's body
    names = [b.car for b in bindings]
    value_exprs = [b.cdr.car for b in bindings]
    lambda_expr = Pair(Symbol("lambda"), Pair(list_to_pairs(names), body))
    return Pair(lambda_expr, list_to_pairs(value_exprs))


def desugar_let_star(args):
    """(let* ((x1 v1) (x2 v2) ... (xn vn)) body...)
       => (let ((x1 v1)) (let* ((x2 v2) ... (xn vn)) body...))
       bottoming out at (let () body...).
       Note: this builds a nested AST (plain data); it does not recurse in
       Python to *evaluate* it -- that happens later, one level at a time,
       through the ordinary explicit-stack loop."""
    bindings = pairs_to_list(args.car)
    body = args.cdr
    if not bindings:
        lambda_expr = Pair(Symbol("lambda"), Pair(NIL, body))
        return Pair(lambda_expr, NIL)
    first, rest = bindings[0], bindings[1:]
    if rest:
        inner_letstar = Pair(Symbol("let*"), Pair(list_to_pairs(rest), body))
        inner_body = Pair(inner_letstar, NIL)
    else:
        inner_body = body
    return Pair(Symbol("let"), Pair(list_to_pairs([first]), inner_body))


_gensym_counter = [0]


def gensym(base="g"):
    """A symbol that can't collide with any name the user actually typed
    -- used internally by desugar_dolist() for its loop-helper name and
    loop-state parameter (so a `dolist` body that happens to use a
    similarly-named variable of its own can't be shadowed by accident),
    and exposed directly to Lisp code as the `gensym` builtin -- the
    standard tool for writing YOUR OWN hygienic macros by hand (build a
    fresh, guaranteed-unique name for anything your macro's expansion
    needs to bind internally, e.g. a temporary in a generated `let`, so
    it can't capture a variable of the same name from the macro's
    caller)."""
    _gensym_counter[0] += 1
    return Symbol("%%%s-%d" % (base, _gensym_counter[0]))


def desugar_dolist(args):
    """(dolist (var list-expr [result-expr]) body...)
       Common-Lisp-style list iteration: evaluates list-expr ONCE, then
       for each element in turn, binds var to it and evaluates body... for
       side effects (display, vector-set!, etc.) -- like `map`, but for
       when you want the looping and don't care about collecting a
       result. Once the list is exhausted, var is (re)bound to '() and
       result-expr is evaluated and returned (or '() itself, if no
       result-expr was given).

       Desugars entirely into forms the evaluator already knows about
       (let, define, if, car/cdr/null?) -- built as a self-recursive
       local helper, via an internal `define` inside a fresh (let () ...)
       scope so the helper doesn't leak into the surrounding environment:

           (let ()
             (define (%dolist-loop-N %dolist-remaining-N)
               (if (null? %dolist-remaining-N)
                   (let ((var '())) result-expr)
                   (let ((var (car %dolist-remaining-N)))
                     body...
                     (%dolist-loop-N (cdr %dolist-remaining-N)))))
             (%dolist-loop-N list-expr))

       Because the recursive call is the LAST expression of the `let`
       that binds var each iteration, it's in TAIL POSITION -- so it gets
       exactly the same constant-stack-space handling seval() gives any
       other tail call (see the module docstring), and dolist can walk
       arbitrarily long lists without growing the control stack.
       """
    spec = pairs_to_list(args.car)
    if len(spec) not in (2, 3):
        raise LispError(
            "dolist: expected (dolist (var list-expr [result-expr]) body...)")
    var = spec[0]
    list_expr = spec[1]
    result_expr = spec[2] if len(spec) == 3 else NIL
    body = pairs_to_list(args.cdr)

    loop_name = gensym("dolist-loop")
    remaining = gensym("dolist-remaining")

    def let1(name, value_expr, body_exprs):
        """(let ((name value_expr)) body_exprs...)"""
        binding = Pair(Pair(name, Pair(value_expr, NIL)), NIL)
        return Pair(Symbol("let"), Pair(binding, list_to_pairs(body_exprs)))

    car_remaining = Pair(Symbol("car"), Pair(remaining, NIL))
    cdr_remaining = Pair(Symbol("cdr"), Pair(remaining, NIL))
    recurse_call = Pair(loop_name, Pair(cdr_remaining, NIL))

    loop_branch = let1(var, car_remaining, body + [recurse_call])
    result_branch = let1(var, NIL, [result_expr])

    if_expr = Pair(
        Symbol("if"),
        Pair(Pair(Symbol("null?"), Pair(remaining, NIL)),
             Pair(result_branch, Pair(loop_branch, NIL))))

    loop_def = Pair(
        Symbol("define"),
        Pair(Pair(loop_name, Pair(remaining, NIL)), Pair(if_expr, NIL)))

    loop_call = Pair(loop_name, Pair(list_expr, NIL))
    return Pair(Symbol("let"), Pair(NIL, Pair(loop_def, Pair(loop_call, NIL))))


def eval_quasiquote(expr, env, depth=1):
    """Walk a quasiquoted template: `(unquote x)` is replaced by the
    result of evaluating x in env (once we're back at the matching
    quasiquote level, depth == 1); `(unquote-splicing x)` as a LIST
    ELEMENT is replaced by splicing in the elements of x's (list) value;
    everything else is copied as literal, unevaluated data -- standard
    Scheme quasiquote semantics. A nested `quasiquote` increases depth
    instead of being touched, so a nested unquote/unquote-splicing only
    "sees through" to its own matching level (decrementing depth rather
    than evaluating, until depth is back down to 1).

    This is plain Python recursion, not the seval() trampoline -- safe
    here because the recursion depth is bounded by how deeply NESTED the
    quasiquote TEMPLATE is in the source code (a fixed, small number),
    never by any runtime data size, unlike a Lisp-level loop. Each
    unquoted subexpression IS evaluated through the ordinary trampolined
    seval(), same as any other embedded evaluation call in this file
    (e.g. eval_cond's test expressions).

    The reader never produces an improper (dotted) list, so this doesn't
    need to handle a non-NIL, non-Pair tail.
    """
    if isinstance(expr, Pair):
        head = expr.car
        if head == Symbol("unquote") and isinstance(expr.cdr, Pair) and expr.cdr.cdr is NIL:
            if depth == 1:
                return seval(expr.cdr.car, env)
            return Pair(Symbol("unquote"),
                        Pair(eval_quasiquote(expr.cdr.car, env, depth - 1), NIL))
        if head == Symbol("quasiquote") and isinstance(expr.cdr, Pair) and expr.cdr.cdr is NIL:
            return Pair(Symbol("quasiquote"),
                        Pair(eval_quasiquote(expr.cdr.car, env, depth + 1), NIL))

        items = []
        rest = expr
        while isinstance(rest, Pair):
            item = rest.car
            is_splice = (isinstance(item, Pair) and item.car == Symbol("unquote-splicing")
                         and isinstance(item.cdr, Pair) and item.cdr.cdr is NIL)
            if is_splice and depth == 1:
                items.extend(pairs_to_list(seval(item.cdr.car, env)))
            elif is_splice:
                items.append(Pair(Symbol("unquote-splicing"),
                                   Pair(eval_quasiquote(item.cdr.car, env, depth - 1), NIL)))
            else:
                items.append(eval_quasiquote(item, env, depth))
            rest = rest.cdr
        tail = NIL if rest is NIL else eval_quasiquote(rest, env, depth)
        result = tail
        for item in reversed(items):
            result = Pair(item, result)
        return result

    if isinstance(expr, LispVector):
        return LispVector([eval_quasiquote(x, env, depth) for x in expr.items])

    return expr  # atoms (numbers, strings, symbols, booleans) are literal


def expand_macro(macro, arg_exprs):
    """Run a macro's transformer body with the call site's UNEVALUATED
    argument expressions (Symbols, Pairs, literals -- plain source code
    as data) bound to its parameters, and return the resulting
    expression -- the "expansion" -- which the caller (seval's macro-call
    check) pushes back onto the control stack to be evaluated exactly
    once, in the CALLING environment, in place of the original call.

    Structurally identical to apply_proc() for an ordinary Procedure,
    except the "arguments" are unevaluated expressions rather than
    values, and the result is code to be evaluated rather than a final
    answer. Like apply_proc(), this calls back into the evaluator via an
    ordinary (recursive) Python function call rather than the trampoline,
    so a macro transformer that itself did deep non-tail recursion while
    BUILDING its expansion would be bounded by Python's recursion limit
    -- the same documented limitation apply/map/filter/reduce/vector-map
    already have (see the module docstring). In practice this essentially
    never matters: a macro transformer builds a piece of code, it doesn't
    loop over runtime data. The code it PRODUCES, once pushed back onto
    the control stack for evaluation, gets the evaluator's usual fully
    tail-call-optimized treatment -- including a proper tail call if the
    macro expands to one (e.g. a macro-defined looping construct).
    """
    new_env = Env(macro.params, arg_exprs, macro.env, rest_param=macro.rest_param,
                  keyword_specs=macro.keyword_specs, default_eval=raw_default)
    return eval_body(macro.body, new_env)


def eval_special_form(op, args, env, control_stack, value_stack):
    """Handle one of the special forms in SPECIAL_FORMS by pushing whatever
    control frames are needed to carry out its evaluation."""
    if op == "quote":
        value_stack.append(args.car)

    elif op == "quasiquote":
        value_stack.append(eval_quasiquote(args.car, env))

    elif op == "breakpoint":
        # A special form (not a function/macro) specifically so it sees
        # `env` -- the REAL lexical environment at the call site (e.g. a
        # paused function's own parameters) -- see debug_repl()'s
        # docstring. A function/macro couldn't do this: a function only
        # ever gets already-evaluated VALUES, and a macro's transformer
        # runs in ITS OWN defining environment, not the caller's.
        # An optional argument -- e.g. (breakpoint "entering f...") or
        # (breakpoint (list "x=" x)) -- is evaluated in that SAME
        # caller's environment and printed before the REPL opens, so a
        # breakpoint hit deep in a loop or recursion can identify itself
        # (or show a value) without needing its own (display ...) call
        # right before it.
        if args is not NIL:
            print(to_display_string(seval(args.car, env)))
        debug_repl(env, label="breakpoint")
        value_stack.append(NIL)

    elif op == "defmacro":
        # (defmacro name (params...) body...) -- name and params are
        # never evaluated, exactly like `lambda`'s parameter list. params
        # may be fixed (a b), dotted/variadic (a b . rest), or a single
        # bare symbol (fully variadic) -- see parse_params().
        name = args.car
        fixed, rest, keyword_specs = parse_params(args.cdr.car)
        body = pairs_to_list(args.cdr.cdr)
        env[name] = Macro(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs)
        value_stack.append(name)

    elif op == "if":
        test, conseq = args.car, args.cdr.car
        alt_pair = args.cdr.cdr
        alt = alt_pair.car if isinstance(alt_pair, Pair) else NIL
        control_stack.append(('IF', conseq, alt, env))
        control_stack.append(('EVAL', test, env))

    elif op == "define":
        target = args.car
        if isinstance(target, Pair):
            # (define (name params...) body...) -- no evaluation needed.
            # params may be fixed, dotted/variadic, or (name . rest) for
            # a fully-variadic function -- see parse_params().
            name = target.car
            fixed, rest, keyword_specs = parse_params(target.cdr)
            body = pairs_to_list(args.cdr)
            env[name] = Procedure(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs)
            value_stack.append(name)
        else:
            name = target
            control_stack.append(('DEFINE', name, env))
            control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "set!":
        name = args.car
        control_stack.append(('SET', name, env))
        control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "lambda":
        # params may be fixed (a b), dotted/variadic (a b . rest), or a
        # single bare symbol (fully variadic) -- see parse_params().
        fixed, rest, keyword_specs = parse_params(args.car)
        body = pairs_to_list(args.cdr)
        value_stack.append(Procedure(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs))

    elif op == "begin":
        push_sequence(pairs_to_list(args), env, control_stack, value_stack)

    elif op == "let":
        control_stack.append(('EVAL', desugar_let(args), env))

    elif op == "let*":
        control_stack.append(('EVAL', desugar_let_star(args), env))

    elif op == "dolist":
        control_stack.append(('EVAL', desugar_dolist(args), env))

    elif op == "cond":
        eval_cond(pairs_to_list(args), env, control_stack, value_stack)

    elif op == "and":
        eval_and(pairs_to_list(args), env, control_stack, value_stack)

    elif op == "or":
        eval_or(pairs_to_list(args), env, control_stack, value_stack)

    elif op == "defstruct":
        # (defstruct name slot...) -- each slot is a bare symbol (default
        # value '()) or (slot-name default-expr), exactly CL's defstruct
        # slot-spec syntax (e.g. (visible #t)). Never evaluated itself,
        # like defmacro's params. Builds four things and binds them into
        # env, exactly as `define` binds a single name:
        #   make-<name>   -- an ordinary &key Procedure (see
        #                     parse_params()/Env.__init__) whose body calls
        #                     the %make-struct builtin with the struct
        #                     type (spliced in directly as a literal --
        #                     any non-Pair/non-Symbol value is self-
        #                     evaluating, see seval()'s EVAL case) and a
        #                     plist built from the bound slot params. So
        #                     struct construction is just an application
        #                     of the general keyword-argument machinery,
        #                     not a separate code path.
        #   <name>-<slot>       -- accessor
        #   <name>-<slot>-set!  -- setter (mutable slots; matches this
        #                          codebase's vector-set!-style naming,
        #                          not CL's setf)
        #   <name>?             -- predicate
        type_name = args.car
        slots = []
        p = args.cdr
        while isinstance(p, Pair):
            spec = p.car
            if isinstance(spec, Pair):
                slots.append((spec.car, spec.cdr.car))
            else:
                slots.append((spec, None))
            p = p.cdr
        struct_type = LispStructType(type_name, slots)

        plist_items = []
        for slot_name, _ in slots:
            plist_items.append(list_to_pairs([Symbol("quote"), slot_name]))
            plist_items.append(slot_name)
        list_call = Pair(Symbol("list"), list_to_pairs(plist_items))
        make_body = list_to_pairs([Symbol("%make-struct"), struct_type, list_call])
        env[Symbol("make-%s" % type_name)] = Procedure(
            [], [make_body], env, rest_param=None, keyword_specs=slots)

        def make_accessor(slot_name):
            def accessor(s):
                if not (isinstance(s, LispStruct) and s.struct_type is struct_type):
                    raise LispError("%s-%s: not a %s: %r" % (type_name, slot_name, type_name, s))
                return s.values[slot_name]
            return accessor

        def make_setter(slot_name):
            def setter(s, v):
                if not (isinstance(s, LispStruct) and s.struct_type is struct_type):
                    raise LispError("%s-%s-set!: not a %s: %r" % (type_name, slot_name, type_name, s))
                s.values[slot_name] = v
                return NIL
            return setter

        for slot_name, _ in slots:
            env[Symbol("%s-%s" % (type_name, slot_name))] = make_accessor(slot_name)
            env[Symbol("%s-%s-set!" % (type_name, slot_name))] = make_setter(slot_name)

        env[Symbol("%s?" % type_name)] = (
            lambda s, t=struct_type: isinstance(s, LispStruct) and s.struct_type is t)

        value_stack.append(type_name)

    else:
        raise LispError("unknown special form: %s" % op)


def seval(expr, env):
    """Evaluate a Lisp expression in an environment, using an explicit
    stack machine rather than Python recursion."""
    control_stack = [('EVAL', expr, env)]
    value_stack = []

    while control_stack:
        frame = control_stack.pop()
        tag = frame[0]

        if tag == 'EVAL':
            _, x, cur_env = frame
            if isinstance(x, Keyword):
                value_stack.append(x)          # self-evaluating, like #t/numbers
            elif isinstance(x, Symbol):
                value_stack.append(cur_env.find(x)[x])
            elif not isinstance(x, Pair):
                value_stack.append(x)          # self-evaluating literal
            else:
                op, args = x.car, x.cdr
                if isinstance(op, Symbol) and op in SPECIAL_FORMS:
                    eval_special_form(op, args, cur_env, control_stack, value_stack)
                    continue
                # Macro call? Check before evaluating anything -- a macro
                # gets its arguments as raw, UNEVALUATED expressions, not
                # values. Pushing the expansion as a plain EVAL frame
                # (rather than recursively evaluating it right here) means
                # a macro call in TAIL POSITION still gets the same
                # constant-stack-space handling as any other tail call --
                # see expand_macro()'s docstring.
                macro = cur_env.lookup_or_none(op) if isinstance(op, Symbol) else None
                if isinstance(macro, Macro):
                    expansion = expand_macro(macro, pairs_to_list(args))
                    control_stack.append(('EVAL', expansion, cur_env))
                else:
                    # Procedure application: evaluate operator, then each
                    # argument left-to-right, then apply. We push APPLY
                    # first (so it runs last), then the arguments in
                    # reverse (so they end up evaluated in order), then
                    # the operator last (so it is evaluated first).
                    arg_list = pairs_to_list(args)
                    control_stack.append(('APPLY', len(arg_list)))
                    for a in reversed(arg_list):
                        control_stack.append(('EVAL', a, cur_env))
                    control_stack.append(('EVAL', op, cur_env))

        elif tag == 'APPLY':
            _, nargs = frame
            collected = [value_stack.pop() for _ in range(nargs + 1)]
            collected.reverse()
            proc, arg_values = collected[0], collected[1:]
            if isinstance(proc, Procedure):
                new_env = Env(proc.params, arg_values, proc.env, rest_param=proc.rest_param,
                              keyword_specs=proc.keyword_specs, default_eval=eval_default)
                push_sequence(proc.body, new_env, control_stack, value_stack)
            elif callable(proc):
                value_stack.append(proc(*arg_values))
            else:
                raise LispError("in tag APPLY: not a procedure: %r" % (proc,))

        elif tag == 'SEQ':
            _, remaining, seq_env = frame
            value_stack.pop()  # discard the value of the expr just run
            push_sequence(remaining, seq_env, control_stack, value_stack)

        elif tag == 'IF':
            _, conseq, alt, if_env = frame
            branch = conseq if is_true(value_stack.pop()) else alt
            control_stack.append(('EVAL', branch, if_env))

        elif tag == 'DEFINE':
            _, name, def_env = frame
            def_env[name] = value_stack.pop()
            value_stack.append(name)

        elif tag == 'SET':
            _, name, set_env = frame
            set_env.find(name)[name] = value_stack.pop()
            value_stack.append(NIL)

        elif tag == 'COND':
            _, clauses, cond_env = frame
            eval_cond(clauses, cond_env, control_stack, value_stack)

        elif tag == 'COND_BRANCH':
            _, body, rest, cond_env = frame
            if is_true(value_stack.pop()):
                push_sequence(body, cond_env, control_stack, value_stack)
            else:
                eval_cond(rest, cond_env, control_stack, value_stack)

        elif tag == 'AND':
            _, exprs, and_env = frame
            eval_and(exprs, and_env, control_stack, value_stack)

        elif tag == 'AND_CHECK':
            _, rest, and_env = frame
            val = value_stack.pop()
            if not is_true(val):
                value_stack.append(False)
            else:
                eval_and(rest, and_env, control_stack, value_stack)

        elif tag == 'OR':
            _, exprs, or_env = frame
            eval_or(exprs, or_env, control_stack, value_stack)

        elif tag == 'OR_CHECK':
            _, rest, or_env = frame
            val = value_stack.pop()
            if is_true(val):
                value_stack.append(val)
            else:
                eval_or(rest, or_env, control_stack, value_stack)

        else:
            raise LispError("unknown control frame: %r" % (tag,))

    return value_stack.pop()


def eval_body(body, env):
    """Evaluate a list of expressions in env, returning the last value.
    Used by apply_proc to call back into a user-defined Procedure from a
    built-in higher-order function like `map` or `vector-map`."""
    return seval(Pair(Symbol("begin"), list_to_pairs(body)), env)


def apply_proc(proc, args):
    """Call a procedure -- either a user-defined Procedure (closure) or a
    built-in Python callable -- with a list of already-evaluated args.
    Used by higher-order builtins (map, filter, reduce, apply, vector-map)."""
    if isinstance(proc, Procedure):
        new_env = Env(proc.params, args, proc.env, rest_param=proc.rest_param,
                      keyword_specs=proc.keyword_specs, default_eval=eval_default)
        return eval_body(proc.body, new_env)
    if callable(proc):
        return proc(*args)
    raise LispError("in apply_proc: not a procedure: %r" % (proc,))


# ---------------------------------------------------------------------------
# Built-in procedures
# ---------------------------------------------------------------------------

def check_numbers(args, name):
    for a in args:
        if not isinstance(a, (int, float)) or isinstance(a, bool):
            raise LispError("%s: not a number: %r" % (name, a))


def check_vector_elements(args, name):
    """Vectors may hold numbers and/or LispDate values (but not booleans,
    strings, pairs, etc.)."""
    for a in args:
        if isinstance(a, bool) or not isinstance(a, (int, float, LispDate)):
            raise LispError("%s: not a number or date: %r" % (name, a))


def numeric_value(v):
    """Convert a vector element to a plain number for arithmetic: dates
    become their ordinal day count, numbers pass through unchanged."""
    if isinstance(v, LispDate):
        return v.date.toordinal()
    return v


# ---- date builtins (module-level: no closure over output/plot needed) ----

def date_fn(year, month, day):
    try:
        return LispDate(int(year), int(month), int(day))
    except ValueError as e:
        raise LispError("date: invalid date: %s" % e)


def date_year(d):
    return d.date.year


def date_month(d):
    return d.date.month


def date_day(d):
    return d.date.day


def date_to_string(d):
    return LispString(d.date.isoformat())


def string_to_date(s):
    try:
        y, m, d = str(s).split("-")
        return LispDate(int(y), int(m), int(d))
    except Exception:
        raise LispError("string->date: invalid date string %r (want YYYY-MM-DD)" % (str(s),))


def date_add_days(d, n):
    if not isinstance(d, LispDate):
        raise LispError("date-add-days: not a date: %r" % (d,))
    return _date_from_pydate(d.date + datetime.timedelta(days=int(n)))


# ---- regression models: linear and logistic, with one or more X
#      predictors (module-level: shared by the standalone regression
#      builtins and the chart-building code below) ----

class LispModel:
    """A fitted regression model: either "linear"
    (y = intercept + sum(coefficients[i] * x[i])) or "logistic"
    (p = sigmoid(intercept + sum(coefficients[i] * x[i]))).
    `coefficients` is always a list, one entry per predictor (even if
    there's only one). `stats` holds a few kind-specific fit diagnostics
    used by `model-report`."""

    def __init__(self, kind, coefficients, intercept, stats):
        self.kind = kind                    # "linear" or "logistic"
        self.coefficients = coefficients    # list of floats, one per predictor
        self.intercept = intercept
        self.k = len(coefficients)          # number of predictors
        self.stats = stats                  # dict of extra fit info, kind-specific

    def predict(self, xs):
        """xs: a list of numbers, one per predictor, in the same order the
        model was fit with."""
        z = self.intercept + sum(c * x for c, x in zip(self.coefficients, xs))
        return sigmoid(z) if self.kind == "logistic" else z

    def __repr__(self):
        return to_string(self)


def sigmoid(z):
    """Numerically stable logistic function 1 / (1 + e^-z)."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def solve_linear_system(matrix, rhs):
    """Solve `matrix @ x = rhs` by Gauss-Jordan elimination with partial
    pivoting. `matrix` is a list of `n` rows, each of length `n`; `rhs` is
    a list of length `n`. Returns the solution as a list of length `n`.
    Plain and O(n^3), which is plenty fast for the handful of predictors
    a small Lisp program will realistically use."""
    n = len(matrix)
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
            raise LispError(
                "regression: the predictors are collinear or there isn't "
                "enough data to fit this model")
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot_value = augmented[col][col]
        augmented[col] = [v / pivot_value for v in augmented[col]]
        for row in range(n):
            if row != col:
                factor = augmented[row][col]
                augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[col])]
    return [augmented[i][n] for i in range(n)]


def _standardize_columns(columns):
    """columns: a list of predictor columns (each a list of numbers, one
    per observation). Returns (standardized_columns, means, scales).
    Standardizing before fitting keeps both the normal-equations solve and
    Newton-Raphson well-behaved regardless of a predictor's raw scale
    (e.g. a huge ordinal date next to a small percentage)."""
    means, scales, standardized = [], [], []
    n = len(columns[0])
    for i, col in enumerate(columns):
        mean = sum(col) / n
        variance = sum((v - mean) ** 2 for v in col) / n
        if variance == 0:
            raise LispError("regression: predictor %d has no variation; cannot fit a model" % (i + 1,))
        scale = math.sqrt(variance)
        means.append(mean)
        scales.append(scale)
        standardized.append([(v - mean) / scale for v in col])
    return standardized, means, scales


def _unstandardize_coefficients(b0, betas, means, scales):
    """Convert coefficients fit in standardized-predictor space back to
    the original, unstandardized scale."""
    coefficients = [b / scale for b, scale in zip(betas, scales)]
    intercept = b0 - sum(b * mean / scale for b, mean, scale in zip(betas, means, scales))
    return coefficients, intercept


def fit_linear(columns, ys):
    """Ordinary least-squares fit of y = intercept + sum(coef[i]*x[i]).
    `columns` is a list of one or more predictor columns (each a list of
    plain numbers, one per observation); `ys` is the list of observed
    values. Returns a LispModel."""
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("linear-regression: no data to fit")
    for col in columns:
        if len(col) != n:
            raise LispError("linear-regression: all vectors must be the same length")

    std_columns, means, scales = _standardize_columns(columns)
    design_rows = [[1.0] + [std_columns[j][i] for j in range(k)] for i in range(n)]
    p = k + 1
    normal_matrix = [[sum(design_rows[i][a] * design_rows[i][b] for i in range(n))
                       for b in range(p)] for a in range(p)]
    normal_rhs = [sum(design_rows[i][a] * ys[i] for i in range(n)) for a in range(p)]
    solved = solve_linear_system(normal_matrix, normal_rhs)
    coefficients, intercept = _unstandardize_coefficients(solved[0], solved[1:], means, scales)

    model = LispModel("linear", coefficients, intercept, {})
    predictions = [model.predict([col[i] for col in columns]) for i in range(n)]
    mean_y = sum(ys) / n
    ss_total = sum((y - mean_y) ** 2 for y in ys)
    ss_residual = sum((y - p) ** 2 for y, p in zip(ys, predictions))
    model.stats = {
        "r_squared": (1 - ss_residual / ss_total) if ss_total > 0 else float("nan"),
        "n": n,
    }
    return model


def fit_logistic(columns, ys, max_iterations=50, tolerance=1e-8):
    """Fit p = sigmoid(intercept + sum(coef[i]*x[i])) by maximum
    likelihood, using Newton-Raphson (a.k.a. iteratively reweighted least
    squares). Each y must be in [0, 1] -- either a hard 0/1 label or a
    probability. `columns` is a list of one or more predictor columns."""
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("logistic-regression: no data to fit")
    for col in columns:
        if len(col) != n:
            raise LispError("logistic-regression: all vectors must be the same length")
    for y in ys:
        if y < 0 or y > 1:
            raise LispError(
                "logistic-regression: dependent-variable values must all be "
                "between 0 and 1 (got %r)" % (y,))

    std_columns, means, scales = _standardize_columns(columns)
    design_rows = [[1.0] + [std_columns[j][i] for j in range(k)] for i in range(n)]
    p = k + 1
    eps = 1e-12

    beta = [0.0] * p
    converged = False
    iterations_used = 0
    log_likelihood = 0.0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        gradient = [0.0] * p
        hessian = [[0.0] * p for _ in range(p)]
        log_likelihood = 0.0
        for i in range(n):
            row = design_rows[i]
            z = sum(beta[a] * row[a] for a in range(p))
            prob = sigmoid(z)
            error = prob - ys[i]
            weight = prob * (1 - prob)
            for a in range(p):
                gradient[a] += error * row[a]
                for b in range(p):
                    hessian[a][b] += weight * row[a] * row[b]
            log_likelihood += ys[i] * math.log(max(prob, eps)) + (1 - ys[i]) * math.log(max(1 - prob, eps))

        try:
            delta = solve_linear_system(hessian, gradient)
        except LispError:
            raise LispError(
                "logistic-regression: fitting failed to converge -- this "
                "usually means the data is perfectly (or almost perfectly) "
                "separable by one of the predictors, which sends the "
                "coefficients toward infinity; try more/noisier data")
        for a in range(p):
            beta[a] -= delta[a]
        if max(abs(d) for d in delta) < tolerance:
            converged = True
            break

    coefficients, intercept = _unstandardize_coefficients(beta[0], beta[1:], means, scales)

    # McFadden's pseudo R-squared, comparing against an intercept-only model.
    mean_y = min(max(sum(ys) / n, eps), 1 - eps)
    null_log_likelihood = sum(y * math.log(mean_y) + (1 - y) * math.log(1 - mean_y) for y in ys)
    pseudo_r_squared = (1 - log_likelihood / null_log_likelihood) if null_log_likelihood != 0 else float("nan")

    stats = {
        "log_likelihood": log_likelihood,
        "pseudo_r_squared": pseudo_r_squared,
        "iterations": iterations_used,
        "converged": converged,
        "n": n,
    }
    return LispModel("logistic", coefficients, intercept, stats)


def _coerce_predictors(x_arg):
    """Accept either a single vector (one predictor) or a Lisp list of
    vectors (multiple predictors), so `(linear-regression xs ys)` keeps
    working exactly as before, while `(linear-regression (list x1 x2) ys)`
    fits a multi-predictor model."""
    if isinstance(x_arg, LispVector):
        return [x_arg]
    if x_arg is NIL or isinstance(x_arg, Pair):
        vecs = pairs_to_list(x_arg)
        if not vecs:
            raise LispError("regression: at least one predictor vector is required")
        return vecs
    raise LispError("regression: expected a vector, or a list of vectors, of predictors")


def _predictor_columns(x_arg, n_expected):
    x_vecs = _coerce_predictors(x_arg)
    columns = []
    for xv in x_vecs:
        if not isinstance(xv, LispVector):
            raise LispError("regression: each predictor must be a vector")
        if len(xv.items) != n_expected:
            raise LispError("regression: all vectors must be the same length")
        columns.append([numeric_value(v) for v in xv.items])
    return columns


def linear_regression_fn(x_arg, y_vec):
    if not isinstance(y_vec, LispVector):
        raise LispError("linear-regression: y must be a vector")
    columns = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items]
    return fit_linear(columns, ys)


def logistic_regression_fn(x_arg, y_vec):
    if not isinstance(y_vec, LispVector):
        raise LispError("logistic-regression: y must be a vector")
    columns = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items]
    return fit_logistic(columns, ys)


def _is_model(x):
    return isinstance(x, (LispModel, LispSplineModel))


def _is_probabilistic(model):
    """True for models whose .predict() returns a probability in [0,1]
    (logistic, or a spline model fit with a logistic link)."""
    return model.kind in ("logistic", "spline-logistic")


def model_predict(model, x_arg):
    if not _is_model(model):
        raise LispError("model-predict: not a model: %r" % (model,))
    if isinstance(x_arg, Pair) or x_arg is NIL:
        xs = [numeric_value(v) for v in pairs_to_list(x_arg)]
    else:
        xs = [numeric_value(x_arg)]
    if len(xs) != model.k:
        raise LispError(
            "model-predict: model has %d predictor(s), but %d given"
            % (model.k, len(xs)))
    return model.predict(xs)


def model_slope(model):
    if isinstance(model, LispSplineModel):
        raise LispError("model-slope: not available for a spline model; use model-report instead")
    if not isinstance(model, LispModel):
        raise LispError("model-slope: not a model: %r" % (model,))
    if len(model.coefficients) != 1:
        raise LispError(
            "model-slope: this model has %d predictors; use model-coefficients instead"
            % len(model.coefficients))
    return model.coefficients[0]


def model_coefficients(model):
    if isinstance(model, LispSplineModel):
        raise LispError("model-coefficients: not available for a spline model; use model-report instead")
    if not isinstance(model, LispModel):
        raise LispError("model-coefficients: not a model: %r" % (model,))
    return LispVector(list(model.coefficients))


def model_report(model):
    """Produce a human-readable multi-line report of a fitted model's
    parameters (and a couple of fit-quality diagnostics)."""
    if isinstance(model, LispSplineModel):
        return LispString("\n".join(_spline_report_lines(model)))
    if not isinstance(model, LispModel):
        raise LispError("model-report: not a model: %r" % (model,))
    lines = []
    coefficient_lines = [
        "  x%d coefficient = %.6g" % (i + 1, c) for i, c in enumerate(model.coefficients)
    ]
    if model.kind == "linear":
        lines.append("Linear model:  y = %.6g + %s" % (
            model.intercept,
            " + ".join("%.6g*x%d" % (c, i + 1) for i, c in enumerate(model.coefficients))))
        lines.extend(coefficient_lines)
        lines.append("  intercept      = %.6g" % model.intercept)
        lines.append("  R-squared      = %.6g" % model.stats["r_squared"])
        lines.append("  n              = %d" % model.stats["n"])
    else:
        lines.append("Logistic model:  p = sigmoid(%.6g + %s)" % (
            model.intercept,
            " + ".join("%.6g*x%d" % (c, i + 1) for i, c in enumerate(model.coefficients))))
        lines.extend(coefficient_lines)
        lines.append("  intercept      = %.6g" % model.intercept)
        lines.append("  log-likelihood = %.6g" % model.stats["log_likelihood"])
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % model.stats["pseudo_r_squared"])
        lines.append("  iterations     = %d (%s)" % (
            model.stats["iterations"], "converged" if model.stats["converged"] else "did NOT converge"))
        lines.append("  n              = %d" % model.stats["n"])
    return LispString("\n".join(lines))


def model_evaluate(model, x_arg, y_vec):
    """Evaluate a fitted model's prediction quality against (typically
    held-out) data it was not fit on, and return a human-readable report.
    This is the "quality of the model on the remaining data" step of a
    train/test workflow."""
    if not _is_model(model):
        raise LispError("model-evaluate: not a model: %r" % (model,))
    if not isinstance(y_vec, LispVector):
        raise LispError("model-evaluate: y must be a vector")
    columns = _predictor_columns(x_arg, len(y_vec.items))
    if len(columns) != model.k:
        raise LispError(
            "model-evaluate: model has %d predictor(s), but %d given"
            % (model.k, len(columns)))
    ys = [numeric_value(v) for v in y_vec.items]
    n = len(ys)
    if n == 0:
        raise LispError("model-evaluate: no data to evaluate")
    predictions = [model.predict([col[i] for col in columns]) for i in range(n)]

    lines = ["Evaluation on %d held-out observation(s):" % n]
    if not _is_probabilistic(model):
        mean_y = sum(ys) / n
        ss_total = sum((y - mean_y) ** 2 for y in ys)
        ss_residual = sum((y - p) ** 2 for y, p in zip(ys, predictions))
        r_squared = (1 - ss_residual / ss_total) if ss_total > 0 else float("nan")
        rmse = math.sqrt(ss_residual / n)
        mae = sum(abs(y - p) for y, p in zip(ys, predictions)) / n
        lines.append("  R-squared = %.6g" % r_squared)
        lines.append("  RMSE      = %.6g" % rmse)
        lines.append("  MAE       = %.6g" % mae)
    else:
        eps = 1e-12
        log_likelihood = sum(
            y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
            for y, p in zip(ys, predictions))
        mean_y = min(max(sum(ys) / n, eps), 1 - eps)
        null_log_likelihood = sum(y * math.log(mean_y) + (1 - y) * math.log(1 - mean_y) for y in ys)
        pseudo_r_squared = (1 - log_likelihood / null_log_likelihood) if null_log_likelihood != 0 else float("nan")
        correct = sum(1 for y, p in zip(ys, predictions) if (p >= 0.5) == (y >= 0.5))
        accuracy = correct / n
        lines.append("  log-likelihood   = %.6g" % log_likelihood)
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % pseudo_r_squared)
        lines.append("  accuracy         = %.6g  (at a 0.5 threshold)" % accuracy)
    return LispString("\n".join(lines))


# ---- spline regression: piecewise-linear hinge basis, no external deps ----
#
# A simple, hand-rolled way to let a model bend: for each predictor x,
# pick a handful of "knot" locations (by default, evenly spaced quantiles
# of that predictor's own values -- or exact locations the user supplies)
# and add a hinge feature max(0, x - t) for each knot t, alongside the
# plain linear term. A predictor can also be marked "categorical" (for a
# variable like home-type, coded e.g. 0=own/1=rent) instead, in which case
# it's expanded into 0/1 indicator columns -- one per non-baseline value --
# rather than hinge features, since hinges/knots don't mean anything for a
# handful of discrete codes. Fitting the expanded basis is then just an
# ordinary (or logistic) regression -- reusing fit_linear/fit_logistic
# exactly as they are.

class _PredictorSpec:
    """How one predictor is expanded into features: either a set of
    hinge-function knots (mode "spline"), or a set of categories to
    dummy-encode (mode "categorical", one 0/1 indicator column per
    non-baseline category)."""

    def __init__(self, mode, knots=None, categories=None, n_distinct=None):
        self.mode = mode
        self.knots = knots or []
        self.categories = categories or []   # sorted; categories[0] is baseline
        self.n_distinct = n_distinct

    def n_features(self):
        return len(self.knots) + 1 if self.mode == "spline" else len(self.categories) - 1


def _choose_knots(column, n_knots):
    """Pick n_knots knot locations at roughly evenly spaced quantiles of
    column's values, staying strictly inside the data range (a knot at
    the max value would produce an all-zero, useless hinge column)."""
    if n_knots <= 0:
        return []
    values = sorted(column)
    n = len(values)
    if n < 3:
        return []  # too little data to place an interior knot meaningfully
    knots = []
    for i in range(1, n_knots + 1):
        q = i / (n_knots + 1)
        idx = int(round(q * (n - 1)))
        idx = min(max(idx, 1), n - 2)  # keep strictly interior
        knots.append(values[idx])
    return _dedupe_preserve_order(knots)


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _resolve_predictor_spec(spec, column, name):
    """Turn one raw per-predictor argument into a _PredictorSpec:
      - the symbol 'categorical  -> dummy-encode the distinct values seen
      - a Lisp list of numbers   -> use exactly those knot locations
      - a plain non-negative int -> auto-pick that many knots by quantile
    """
    n_distinct = len(set(column))
    if isinstance(spec, Symbol) and spec == "categorical":
        categories = sorted(set(column))
        if len(categories) < 2:
            raise LispError(
                "spline-regression: %s marked categorical, but only %d distinct "
                "value(s) were found (need at least 2)" % (name, len(categories)))
        return _PredictorSpec("categorical", categories=categories, n_distinct=n_distinct)

    if isinstance(spec, Pair) or spec is NIL:
        knots = _dedupe_preserve_order(sorted(numeric_value(v) for v in pairs_to_list(spec)))
    else:
        count = int(spec)
        if count < 0:
            raise LispError("spline-regression: knot counts must not be negative")
        knots = _choose_knots(column, count)

    if knots and n_distinct <= 3:
        # A knot placed among only 2-3 distinct values is liable to make a
        # hinge column identical (or near-identical) to the plain linear
        # term or to another hinge, making the fit singular -- and hinge
        # knots don't really mean anything for a handful of discrete
        # values anyway. Catch this up front with an actionable message,
        # rather than letting it surface later as a confusing "collinear"
        # error deep in the linear-algebra code.
        raise LispError(
            "spline-regression: %s has only %d distinct value(s), so hinge "
            "knots aren't meaningful there (and can make the fit singular). "
            "Use a knot count of 0 (stay linear) or mark it 'categorical "
            "instead." % (name, n_distinct))

    return _PredictorSpec("spline", knots=knots, n_distinct=n_distinct)


def _resolve_all_predictor_specs(max_knots, columns):
    """Resolve the `max-knots` argument into one _PredictorSpec per
    predictor. `max_knots` may be:
      - a single int or 'categorical, applied to every predictor
      - a flat list of numbers/dates, when there's exactly one predictor
        (shorthand for explicit knot locations on that one predictor)
      - a list with exactly one entry per predictor, where each entry is
        itself an int, 'categorical, or a list of explicit knot locations
    """
    k = len(columns)
    names = ["x%d" % (i + 1) for i in range(k)]

    def is_knot_value(v):
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(v, LispDate)

    if isinstance(max_knots, Pair) or max_knots is NIL:
        items = pairs_to_list(max_knots)
        all_knot_values = items and all(is_knot_value(v) for v in items)
        if k == 1 and all_knot_values:
            # A flat list of numbers/dates with one predictor: explicit knots.
            return [_resolve_predictor_spec(list_to_pairs(items), columns[0], names[0])]
        if len(items) != k:
            raise LispError(
                "spline-regression: the knot-spec list must have one entry per "
                "predictor (%d), got %d" % (k, len(items)))
        return [_resolve_predictor_spec(spec, col, name)
                for spec, col, name in zip(items, columns, names)]

    return [_resolve_predictor_spec(max_knots, col, name)
            for col, name in zip(columns, names)]


def _spline_expand_value(v, spec, name):
    if spec.mode == "categorical":
        if v not in spec.categories:
            raise LispError(
                "spline-regression: %s value %r was not one of the categories "
                "seen while fitting (%s)" % (
                    name, v, ", ".join("%.6g" % c for c in spec.categories)))
        return [1.0 if v == cat else 0.0 for cat in spec.categories[1:]]
    row = [v]
    for t in spec.knots:
        row.append(max(0.0, v - t))
    return row


def _spline_expand_row(values, specs):
    """values: one value per original predictor. Returns the expanded
    feature row (hinge features and/or 0/1 category indicators)."""
    row = []
    for i, (v, spec) in enumerate(zip(values, specs)):
        row.extend(_spline_expand_value(v, spec, "x%d" % (i + 1)))
    return row


def _spline_expand_columns(columns, specs):
    """columns: one column (list of n values) per original predictor.
    Returns the same expansion as _spline_expand_row, but column-wise."""
    n = len(columns[0]) if columns else 0
    rows = [_spline_expand_row([col[i] for col in columns], specs) for i in range(n)]
    n_features = len(rows[0]) if rows else 0
    return [[row[j] for row in rows] for j in range(n_features)]


class LispSplineModel:
    """A piecewise-linear spline model: an ordinary linear or logistic
    regression fit on top of a per-predictor feature expansion (hinge
    functions and/or categorical dummy encoding -- see _resolve_predictor_spec
    / _spline_expand_columns above), giving the model a bit of the same
    kind of bendable-curve flexibility as MARS, without any external
    dependency."""

    def __init__(self, inner_model, predictor_specs, k):
        self.inner_model = inner_model          # a LispModel fit on the expanded basis
        self.predictor_specs = predictor_specs  # list of k _PredictorSpec
        self.k = k                              # number of original predictors
        self.kind = "spline-logistic" if inner_model.kind == "logistic" else "spline"

    def predict(self, values):
        return self.inner_model.predict(_spline_expand_row(values, self.predictor_specs))

    def __repr__(self):
        return to_string(self)


def _spline_report_lines(model):
    lines = []
    if model.kind == "spline-logistic":
        lines.append("Piecewise-linear spline model, with a logistic link:")
    else:
        lines.append("Piecewise-linear spline model:")
    lines.append("  predictors = %d" % model.k)
    for i, spec in enumerate(model.predictor_specs):
        if spec.mode == "categorical":
            cats = ", ".join("%.6g" % c for c in spec.categories)
            lines.append("  x%d: categorical -- categories %s (baseline %.6g)"
                          % (i + 1, cats, spec.categories[0]))
        else:
            knot_text = ", ".join("%.6g" % t for t in spec.knots) if spec.knots else "(none -- plain linear)"
            hint = ""
            if spec.n_distinct is not None and spec.n_distinct <= 3:
                hint = "  [only %d distinct value(s) seen -- consider 'categorical]" % spec.n_distinct
            lines.append("  x%d: knots %s%s" % (i + 1, knot_text, hint))
    lines.append("")
    stats = model.inner_model.stats
    if model.kind == "spline-logistic":
        lines.append("Logistic fit on the expanded basis:")
        lines.append("  log-likelihood   = %.6g" % stats["log_likelihood"])
        lines.append("  pseudo R-squared = %.6g  (McFadden's)" % stats["pseudo_r_squared"])
        lines.append("  iterations       = %d (%s)" % (
            stats["iterations"], "converged" if stats["converged"] else "did NOT converge"))
    else:
        lines.append("Linear fit on the expanded basis:")
        lines.append("  R-squared = %.6g" % stats["r_squared"])
    lines.append("  n = %d" % stats["n"])
    return lines


def spline_regression_fn(x_arg, y_vec, max_knots=3, logistic=False):
    """Fit a piecewise-linear spline model. `x_arg` is a vector or list of
    vectors (predictors). `max_knots` controls how each predictor is
    expanded -- see _resolve_all_predictor_specs for the accepted forms
    (an auto knot count, explicit knot locations, or 'categorical). If
    `logistic` is true, `y` must be in [0, 1], and a logistic regression
    (instead of ordinary least squares) is fit on the expanded basis,
    giving a probability-in-[0,1] output."""
    if not isinstance(y_vec, LispVector):
        raise LispError("spline-regression: y must be a vector")

    columns = _predictor_columns(x_arg, len(y_vec.items))
    ys = [numeric_value(v) for v in y_vec.items]
    k = len(columns)
    n = len(ys)
    if n == 0:
        raise LispError("spline-regression: no data to fit")
    if logistic:
        for y in ys:
            if y < 0 or y > 1:
                raise LispError(
                    "spline-regression: with logistic #t, dependent-variable values "
                    "must all be between 0 and 1 (got %r)" % (y,))

    predictor_specs = _resolve_all_predictor_specs(max_knots, columns)
    expanded_columns = _spline_expand_columns(columns, predictor_specs)

    inner_model = fit_logistic(expanded_columns, ys) if logistic else fit_linear(expanded_columns, ys)
    return LispSplineModel(inner_model, predictor_specs, k)


def suggest_knots_fn(x_vec, y_vec, window, n):
    """Suggest n knot locations for spline-regression, based on where y
    curves most sharply as a function of x.

    Method: first aggregate y (by mean) onto each distinct x value seen
    (so `window` counts steps along the distinct-x curve, not raw rows --
    important for panel/pool data where many rows often share the same x).
    Estimate that curve's second derivative at each interior point (via
    the standard 3-point finite-difference formula, which works whether
    or not x is evenly spaced), smooth that sequence with a centered
    moving average of the given `window` size (to reduce sensitivity to
    single-point noise), then greedily pick the `window`-separated points
    with the largest smoothed |second derivative| -- "window-separated"
    meaning no two chosen points are within `window` of each other by
    index, so their smoothing windows don't overlap and they represent
    genuinely distinct bends rather than the same one picked twice.

    Returns a Lisp list of up to n x-values (fewer if there aren't that
    many usable candidates), sorted ascending -- ready to hand straight
    to spline-regression as an explicit knot list, e.g.
    (spline-regression x y (suggest-knots x y 5 2))."""
    if not isinstance(x_vec, LispVector) or not isinstance(y_vec, LispVector):
        raise LispError("suggest-knots: x and y must be vectors")
    if len(x_vec.items) != len(y_vec.items):
        raise LispError("suggest-knots: x and y must be the same length")

    window = int(window)
    n = int(n)
    if window < 1:
        raise LispError("suggest-knots: window must be a positive integer")
    if n < 0:
        raise LispError("suggest-knots: n must not be negative")
    if n == 0:
        return NIL

    # Sort by x, then aggregate y (by mean) onto each *distinct* x value.
    # Real/panel data routinely has many rows sharing the same x (e.g. many
    # pools observed at the same rate-incentive level); estimating a second
    # derivative needs distinct neighboring x's, and `window` is meant to
    # count "steps along the curve", not raw rows -- so we collapse to one
    # (x, mean-of-y) point per distinct x first. This also happens to be the
    # statistically sensible thing to do: it's the marginal curve of y
    # against x whose bends we want to find, not the scatter of every row.
    pairs = sorted(zip(x_vec.items, y_vec.items), key=lambda p: numeric_value(p[0]))
    groups = {}
    order = []
    for raw_xi, raw_yi in pairs:
        key = numeric_value(raw_xi)
        if key not in groups:
            groups[key] = {"raw_x": raw_xi, "ys": []}
            order.append(key)
        groups[key]["ys"].append(numeric_value(raw_yi))

    raw_x = [groups[k]["raw_x"] for k in order]
    xs = list(order)
    ys = [sum(groups[k]["ys"]) / len(groups[k]["ys"]) for k in order]
    m = len(xs)
    if m < 3:
        raise LispError(
            "suggest-knots: need at least 3 distinct x values to estimate curvature "
            "(found %d)" % m)

    # Second-derivative estimate at each interior point i (1 .. m-2):
    #   f''(x_i) ~= 2 * [ (y_{i+1}-y_i)/(x_{i+1}-x_i) - (y_i-y_{i-1})/(x_i-x_{i-1}) ]
    #               / (x_{i+1} - x_{i-1})
    # which reduces to the familiar (y_{i+1} - 2y_i + y_{i-1}) / h^2 when x
    # is evenly spaced by h, but also works for uneven spacing. Since x is
    # now strictly increasing (we've deduplicated), h1/h2 are always > 0.
    raw_d2 = [0.0] * m
    for i in range(1, m - 1):
        h1 = xs[i] - xs[i - 1]
        h2 = xs[i + 1] - xs[i]
        raw_d2[i] = 2.0 * ((ys[i + 1] - ys[i]) / h2 - (ys[i] - ys[i - 1]) / h1) / (xs[i + 1] - xs[i - 1])

    # Centered moving average of the second-derivative sequence.
    half_before = window // 2
    half_after = window - 1 - half_before
    smoothed = [0.0] * m
    for i in range(1, m - 1):
        lo = max(1, i - half_before)
        hi = min(m - 2, i + half_after)
        segment = raw_d2[lo:hi + 1]
        smoothed[i] = sum(segment) / len(segment)

    # Greedily take the largest-|smoothed-second-derivative| points,
    # skipping any candidate within `window` (by index) of one already
    # chosen.
    candidates = sorted(range(1, m - 1), key=lambda i: abs(smoothed[i]), reverse=True)
    selected = []
    for i in candidates:
        if smoothed[i] == 0.0:
            continue
        if any(abs(i - j) < window for j in selected):
            continue
        selected.append(i)
        if len(selected) == n:
            break

    selected.sort()
    return list_to_pairs([raw_x[i] for i in selected])


# ---- chart-spec building (module-level: pure data, no Qt involved) ----
# Charts only ever plot against a single X vector (a 2-D chart has one
# X axis), so any regression line drawn on a chart is single-predictor,
# even though linear-regression/logistic-regression themselves now
# support multiple predictors -- use model-report/model-evaluate for the
# multi-predictor case instead of a chart overlay.

def build_chart_spec(x_vec, y_vecs, labels, connect, title, regression_label, regression_kind="linear"):
    """Build a plain-data chart description dict from Lisp values. This is
    consumed by the GUI's ChartCanvas.plot(), or by the console fallback
    plotter -- neither of those needs to know anything about Lisp."""
    if not isinstance(x_vec, LispVector):
        raise LispError("plot: x must be a vector")
    if not y_vecs:
        raise LispError("plot: at least one y-vector is required")
    if regression_kind not in ("linear", "logistic"):
        raise LispError('plot: regression kind must be "linear" or "logistic"')

    xs_raw = x_vec.items
    n = len(xs_raw)
    x_is_date = any(isinstance(v, LispDate) for v in xs_raw)
    xs_plot = [v.date if isinstance(v, LispDate) else v for v in xs_raw]
    xs_numeric = [numeric_value(v) for v in xs_raw]

    series_list = []
    for i, y_vec in enumerate(y_vecs):
        if not isinstance(y_vec, LispVector):
            raise LispError("plot: each y must be a vector")
        if len(y_vec.items) != n:
            raise LispError("plot: every vector must be the same length as x")
        label = labels[i] if labels else ("Y%d" % (i + 1))
        series_list.append({"label": label, "y": list(y_vec.items), "connect": connect})

    spec = {
        "title": title,
        "x_label": "X",
        "x_is_date": x_is_date,
        "x": xs_plot,
        "series": series_list,
        "regression": None,
    }

    if regression_label is not None:
        target = next((s for s in series_list if s["label"] == regression_label), None)
        if target is None:
            raise LispError("plot: no y-series labeled %r to run regression on" % (regression_label,))

        model = (fit_logistic([xs_numeric], target["y"]) if regression_kind == "logistic"
                 else fit_linear([xs_numeric], target["y"]))

        x_min, x_max = min(xs_numeric), max(xs_numeric)
        if regression_kind == "logistic":
            # The fitted curve is an S-shape, not a straight line, so
            # sample enough points across the x-range to draw it smoothly.
            steps = 100
            sample_xs_num = [x_min + (x_max - x_min) * i / (steps - 1) for i in range(steps)]
        else:
            sample_xs_num = [x_min, x_max]  # a straight line only needs two points
        sample_ys = [model.predict([xv]) for xv in sample_xs_num]
        if x_is_date:
            sample_xs_plot = [datetime.date.fromordinal(int(round(v))) for v in sample_xs_num]
        else:
            sample_xs_plot = sample_xs_num

        spec["regression"] = {
            "label": regression_label,
            "kind": regression_kind,
            "model": model,
            "x": sample_xs_plot,
            "y": sample_ys,
        }

    return spec


# ---- FRED (Federal Reserve Bank of St. Louis) data access ----

# ---- chart rendering (module-level, needs only matplotlib -- not Qt) ----
#
# This is deliberately independent of the PyQt6 import below: as long as
# matplotlib is installed, `save-chart` and the console fallback can both
# render a chart to an image file even without PyQt6/a GUI at all. The GUI's
# ChartCanvas (further down) reuses the exact same draw_chart_on_axes()
# function so the on-screen chart and any saved image always match.

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False

# One marker shape per Y-series; cycles if there are more series than
# shapes. Matplotlib's own default color cycle distinguishes them too.
CHART_MARKERS = ["o", "s", "^", "D", "v", "P", "x", "*"]


def draw_chart_on_axes(fig, ax, spec):
    """Draw a chart spec (see build_chart_spec) onto an existing Matplotlib
    Figure/Axes: one X vector against one or more Y vectors, each with its
    own marker symbol and optionally connected by line segments, plus an
    optional dashed regression line/curve. Pure matplotlib -- no Qt."""
    ax.clear()

    xs = spec["x"]
    for i, s in enumerate(spec["series"]):
        marker = CHART_MARKERS[i % len(CHART_MARKERS)]
        linestyle = "-" if s["connect"] else "None"
        ax.plot(xs, s["y"], marker=marker, linestyle=linestyle,
                 markersize=7, label=s["label"])

    reg = spec.get("regression")
    if reg:
        model = reg["model"]
        label = "%s %s fit (slope=%.4g, intercept=%.4g)" % (
            reg["label"], reg["kind"], model.coefficients[0], model.intercept)
        ax.plot(reg["x"], reg["y"], linestyle="--", color="black",
                 linewidth=1.5, label=label)

    ax.set_xlabel(spec.get("x_label", "X"))
    ax.set_title(spec.get("title", "XY Chart"))
    ax.grid(True, alpha=0.3)
    ax.legend()
    if spec.get("x_is_date"):
        fig.autofmt_xdate()


def render_chart_to_file(spec, path, width=8.0, height=6.0, dpi=150):
    """Render a chart spec to a standalone image file (PNG, PDF, SVG, ...
    -- whatever matplotlib recognizes from the file extension). Uses a
    throwaway headless Figure, so this works with or without a GUI running."""
    if not _MATPLOTLIB_AVAILABLE:
        raise LispError("save-chart: matplotlib is not installed (pip install matplotlib)")
    fig = Figure(figsize=(width, height), dpi=dpi)
    FigureCanvasAgg(fig)  # attach a headless (non-interactive) canvas
    ax = fig.add_subplot(111)
    draw_chart_on_axes(fig, ax, spec)
    try:
        fig.savefig(path)
    except Exception as e:
        raise LispError("save-chart: could not save %r: %s" % (path, e))


def _parse_fred_observations(observations):
    """Turn FRED's list of {"date": "...", "value": "..."} dicts into a
    (dates-vector . values-vector) pair, skipping missing observations
    (FRED marks those with a value of ".")."""
    dates = []
    values = []
    for obs in observations:
        value_str = obs.get("value", ".")
        if value_str == ".":
            continue
        try:
            value = float(value_str)
        except (TypeError, ValueError):
            continue
        year, month, day = obs["date"].split("-")
        dates.append(LispDate(int(year), int(month), int(day)))
        values.append(value)
    return Pair(list_to_pairs(dates), Pair(list_to_pairs(values), NIL))


def _fred_api_key_from_file(path):
    """Load a "fred_api_key" entry out of a JSON credentials file -- the
    same file used for tastytrade-* credentials, so both APIs' keys can
    live in one place (see _tasty_load_credentials)."""
    try:
        with open(str(path)) as f:
            data = json.load(f)
    except OSError as e:
        raise LispError("fred-series: could not open credentials file %r: %s" % (str(path), e))
    except json.JSONDecodeError as e:
        raise LispError("fred-series: credentials file %r isn't valid JSON: %s" % (str(path), e))
    key = data.get("fred_api_key")
    if not key:
        raise LispError(
            "fred-series: credentials file %r has no \"fred_api_key\" entry" % (str(path),))
    return str(key).strip()


def fred_series(series_id, api_key=None, start_date=None, end_date=None):
    """Fetch one FRED data series and return (dates-vector . values-vector).

    `api_key` may be a literal FRED API key, or the path to a JSON
    credentials file with a "fred_api_key" entry (the same file used for
    tastytrade-* credentials, so both APIs' keys can live in one place).
    It may also be omitted entirely if the FRED_API_KEY environment
    variable is set. A free API key can be requested at
    https://fred.stlouisfed.org/docs/api/api_key.html
    `start_date` / `end_date`, if given, are "YYYY-MM-DD" strings (or
    LispDate values) limiting the observation range.
    """
    if api_key is not None and os.path.exists(str(api_key)):
        api_key = _fred_api_key_from_file(api_key)
    if api_key is None:
        api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise LispError(
            "fred-series: no API key given (pass one, pass the path to a "
            "credentials JSON file with a \"fred_api_key\" entry, or set "
            "the FRED_API_KEY environment variable)")

    params = {
        "series_id": str(series_id),
        "api_key": str(api_key),
        "file_type": "json",
    }
    if start_date is not None:
        params["observation_start"] = (
            start_date.date.isoformat() if isinstance(start_date, LispDate) else str(start_date))
    if end_date is not None:
        params["observation_end"] = (
            end_date.date.isoformat() if isinstance(end_date, LispDate) else str(end_date))

    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise LispError("fred-series: request failed: %s" % e)

    if "observations" not in data:
        raise LispError("fred-series: %s" % data.get("error_message", "unknown error from FRED"))

    return _parse_fred_observations(data["observations"])


def load_csv_fn(filename, has_header=True):
    """Load a CSV file's columns as vectors: returns
    (cons headers-list vectors-list), where headers-list is a Lisp list
    of column-name strings and vectors-list is the same-length Lisp list
    of the corresponding vectors.

    Each column is independently classified as numeric, as a date
    ("YYYY-MM-DD" text), or unusable (skipped, along with its header) if
    it's neither. A row is only included if every *usable* column has a
    non-blank value in that row, so all returned vectors stay the same
    length and row-aligned -- the same "skip missing observations"
    approach used by fred-series."""
    try:
        with open(str(filename), newline="") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        raise LispError("load-csv: could not open %r: %s" % (str(filename), e))

    if not rows:
        raise LispError("load-csv: %r is empty" % (str(filename),))

    if is_true(has_header):
        header, data_rows = rows[0], rows[1:]
    else:
        header, data_rows = None, rows

    if not data_rows:
        raise LispError("load-csv: %r has no data rows" % (str(filename),))

    n_cols = len(data_rows[0])
    if header is None:
        header = ["Column%d" % (i + 1) for i in range(n_cols)]

    def try_float(s):
        try:
            return float(s)
        except ValueError:
            return None

    def try_date(s):
        try:
            y, m, d = s.split("-")
            return LispDate(int(y), int(m), int(d))
        except Exception:
            return None

    column_kinds = []  # "number", "date", or None (unusable), per column
    for c in range(n_cols):
        non_blank = [row[c].strip() for row in data_rows if c < len(row) and row[c].strip() != ""]
        if non_blank and all(try_float(v) is not None for v in non_blank):
            column_kinds.append("number")
        elif non_blank and all(try_date(v) is not None for v in non_blank):
            column_kinds.append("date")
        else:
            column_kinds.append(None)

    usable = [c for c in range(n_cols) if column_kinds[c] is not None]
    if not usable:
        raise LispError("load-csv: no numeric or date (YYYY-MM-DD) columns found in %r" % (str(filename),))

    included_rows = [
        row for row in data_rows
        if len(row) >= n_cols and all(row[c].strip() != "" for c in usable)
    ]
    if not included_rows:
        raise LispError("load-csv: no complete rows found for the usable columns in %r" % (str(filename),))

    out_headers, out_vectors = [], []
    for c in usable:
        out_headers.append(LispString(header[c]))
        if column_kinds[c] == "number":
            items = [try_float(row[c].strip()) for row in included_rows]
        else:
            items = [try_date(row[c].strip()) for row in included_rows]
        out_vectors.append(LispVector(items))

    return Pair(list_to_pairs(out_headers), list_to_pairs(out_vectors))


def _sqlite_value_to_lisp(v):
    """Convert one value out of a sqlite3 row into the matching Lisp
    value: SQL NULL (None) becomes '(), TEXT becomes a LispString,
    everything else (INTEGER/REAL, already plain int/float) passes
    through unchanged. BLOB values (Python bytes) are decoded as UTF-8
    text on a best-effort basis -- this interpreter has no separate
    byte-vector type to hand them back as."""
    if v is None:
        return NIL
    if isinstance(v, bytes):
        return LispString(v.decode("utf-8", errors="replace"))
    if isinstance(v, str):
        return LispString(v)
    return v


def sqlite_open_fn(path):
    """(sqlite-open "path/to/db.sqlite") -- open a SQLite database file
    (creating it if it doesn't already exist, same as Python's own
    sqlite3.connect) and return a connection value to pass to
    sqlite-query / sqlite-execute / sqlite-close."""
    try:
        return LispSQLiteConnection(path)
    except sqlite3.Error as e:
        raise LispError("sqlite-open: could not open %r: %s" % (str(path), e))


def sqlite_close_fn(conn):
    """(sqlite-close conn) -- close a connection opened by sqlite-open.
    Safe to call on an already-closed connection."""
    if not isinstance(conn, LispSQLiteConnection):
        raise LispError("sqlite-close: not a sqlite connection: %r" % (conn,))
    conn.connection.close()
    return NIL


def _sqlite_run(conn, sql):
    if not isinstance(conn, LispSQLiteConnection):
        raise LispError("expected a sqlite connection (from sqlite-open), got %r" % (conn,))
    try:
        cursor = conn.connection.cursor()
        cursor.execute(str(sql))
        return cursor
    except sqlite3.Error as e:
        raise LispError("sqlite: %s" % e)


def sqlite_query_fn(conn, sql):
    """(sqlite-query conn "SELECT ...") -- run a SQL statement to
    completion and return its result set COLUMN-WISE: a Lisp list of
    (name . vector) pairs, one per output column, in query order --
    exactly the shape (display-columns ...) / (write-columns-csv ...)
    already expect, so a query's results can be shown or exported
    directly:
        (display-columns (sqlite-query conn "SELECT year, total FROM t"))
    Column names come from the query itself; SQL NULL becomes '() (see
    _sqlite_value_to_lisp). This reads the ENTIRE result set into memory
    before returning -- for a large result you'd rather step through one
    row at a time instead, see sqlite-execute / sqlite-fetch-row.

    Streams rows one at a time straight from the cursor into per-column
    lists, rather than fetchall()-ing the whole raw result set first and
    transposing it afterward -- avoids ever holding a full second copy
    of the result (as row-tuples) alongside the column-vectors being
    built from it."""
    cursor = _sqlite_run(conn, sql)
    names = [d[0] for d in cursor.description] if cursor.description else []
    columns = [[] for _ in names]
    for row in cursor:
        for column, v in zip(columns, row):
            column.append(_sqlite_value_to_lisp(v))
    return list_to_pairs([
        Pair(LispString(name), LispVector(column))
        for name, column in zip(names, columns)
    ])


def sqlite_execute_fn(conn, sql):
    """(sqlite-execute conn "SELECT ...") -- run a SQL statement and
    return a CURSOR without reading any rows yet. Call (sqlite-fetch-row
    cursor) repeatedly to pull one row at a time (as a Lisp list of that
    row's values, in column order) until it returns '(), meaning no rows
    are left -- useful for a result set too large to materialize all at
    once with sqlite-query, or when you'd rather process rows one by one
    (e.g. in a `while`/`dolist` loop). Fine for a non-SELECT statement
    too (INSERT/UPDATE/...); sqlite-fetch-row just returns '() right
    away since there's nothing to fetch."""
    return LispSQLiteCursor(_sqlite_run(conn, sql))


def sqlite_fetch_row_fn(cursor):
    """(sqlite-fetch-row cursor) -- pull the next row from a cursor
    returned by sqlite-execute, as a Lisp list of that row's values in
    column order, or '() once every row has already been fetched."""
    if not isinstance(cursor, LispSQLiteCursor):
        raise LispError("sqlite-fetch-row: not a sqlite cursor: %r" % (cursor,))
    row = cursor.cursor.fetchone()
    if row is None:
        return NIL
    return list_to_pairs([_sqlite_value_to_lisp(v) for v in row])


# ---- tastytrade (real broker data): futures curves and futures-option
#      chains, via the community `tastytrade` Python SDK. Modeled on
#      tasty_api/tastytrade_source.py, but with the PyQt6/QThread plumbing
#      stripped out -- these are plain synchronous functions (each just
#      wraps an `asyncio.run` internally, the same way `fred_series` above
#      wraps a plain urllib call), so this module keeps working without
#      PyQt6 installed. ----

try:
    from tastytrade import Session as _TTSession
    from tastytrade.instruments import get_future_option_chain as _tt_get_future_option_chain
    from tastytrade.instruments import get_option_chain as _tt_get_option_chain
    from tastytrade.market_data import get_market_data_by_type as _tt_get_market_data_by_type
    _TASTYTRADE_AVAILABLE = True
except ImportError:
    _TASTYTRADE_AVAILABLE = False

# ---- term_structure_model (SOFR forward curve, Monte Carlo path
#      simulation, and calibration): a pure (no networking, no broker
#      dependency) model reused as-is from ../term_structure/ -- see
#      sofr_forward_curve_fn() / sofr_simulate_rate_paths_fn() /
#      sofr_simulate_mortgage_rate_paths_fn() / sofr_calibrate_model_fn(),
#      below. ----
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "term_structure"))
    from term_structure_model import bootstrap_sofr_curve as _bootstrap_sofr_curve
    from term_structure_model import simulate_rate_paths as _simulate_rate_paths
    from term_structure_model import simulate_mortgage_rate_paths as _simulate_mortgage_rate_paths
    from term_structure_model import calibrate_sofr_model as _calibrate_sofr_model
    _TERM_STRUCTURE_AVAILABLE = True
except ImportError:
    _TERM_STRUCTURE_AVAILABLE = False

# ---- sofr_market_data (fetches the SOFR futures curve AND a spread of
#      SOFR futures OPTIONS, in one tastytrade session, shaped exactly
#      for calibrate_sofr_model() above): a SEPARATE, dedicated fetch
#      from tastytrade-futures-curve-rows -- see sofr_calibration_data_fn(),
#      below. Importing this module never itself requires the tastytrade
#      package to be installed (it checks that lazily, at call time --
#      see tt.TASTYTRADE_AVAILABLE inside fetch_sofr_calibration_data());
#      only numpy and tasty_api/tastytrade_source.py need to be
#      importable for THIS guard to pass. ----
try:
    from sofr_market_data import fetch_sofr_calibration_data as _fetch_sofr_calibration_data
    _SOFR_MARKET_DATA_AVAILABLE = True
except ImportError:
    _SOFR_MARKET_DATA_AVAILABLE = False

TASTY_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
TASTY_CODE_TO_MONTH = {v: k for k, v in TASTY_MONTH_CODES.items()}

# Supported products: code -> tastytrade root symbol. Kept in sync with
# tasty_api/tastytrade_source.py's PRODUCTS dict.
TASTY_PRODUCTS = {
"ES":"/ES",
"MES":"/MES",
"NQ":"/NQ",
"MNQ":"/MNQ",
"YM":"/YM",
"MYM":"/MYM",
"RTY":"/RTY",
"M2K":"/M2K",
"ZT":"/ZT",
"ZF":"/ZF",
"ZN":"/ZN",
"ZB":"/ZB",
"SR3":"/SR3",
"2YY":"/2YY",
"5YY":"/5YY",
"10Y":"/10Y",
"30Y":"/30Y",
"TN":"/TN",
"UB":"/UB",
"6E":"/6E",
"M6E":"/M6E",
"6J":"/6J",
"6B":"/6B",
"M6B":"/M6B",
"6C":"/6C",
"MCD":"/MCD",
"6A":"/6A",
"M6A":"/M6A",
"6M":"/6M",
"6S":"/6S",
"CL":"/CL",
"MCL":"/MCL",
"QM":"/QM",
"NG":"/NG",
"MNG":"/MNG",
"QG":"/QG",
"RB":"/RB",
"HO":"/HO",
"BZ":"/BZ",
"GC":"/GC",
"MGC":"/MGC",
"1OZ":"/1OZ",
"HG":"/HG",
"MHG":"/MHG",
"SI":"/SI",
"SIL":"/SIL",
"SIC":"/SIC",
"PL":"/PL",
"PA":"/PA",
"ZC":"/ZC",
"XC":"/XC",
"ZS":"/ZS",
"XK":"/XK",
"ZW":"/ZW",
"XW":"/XW",
"BTC":"/BTC",
"MBT":"/MBT",
"ETH":"/ETH",
"MET":"/MET",
"MXP":"/MXP",
"LE":"/LE",
"HE":"/HE",
"VX":"/VX",
"VXM":"/VXM"
}


async def _tasty_maybe_await(value):
    """Compatibility shim: the `tastytrade` SDK went async-only in v12.0.0,
    so older installed versions return plain results directly instead of a
    coroutine. See the identically-named helper in tasty_api/tastytrade_source.py."""
    if inspect.isawaitable(value):
        return await value
    return value


def _run_async(coro):
    """Run an asyncio coroutine to completion and return its result --
    works whether or not the calling thread already has its OWN running
    event loop. With no loop already running (a plain script, the
    console REPL, the GUI), this is exactly asyncio.run(coro). With one
    already running -- e.g. inside a Jupyter/IPython kernel, which runs
    one continuously; found by hitting it directly, calling any
    tastytrade-*/sofr-calibration-data builtin from a notebook cell blew
    up with "asyncio.run() cannot be called from a running event loop"
    -- asyncio.run() would raise exactly that, so this runs the
    coroutine to completion on a SEPARATE thread with its own fresh
    event loop instead, and blocks the calling thread until it's done.
    Either way, every caller of every _tasty_*_async coroutine in this
    file just gets a plain return value back, synchronously -- no
    awaiting, no nest_asyncio monkeypatching needed, no visible
    difference depending on which context it's called from. See the
    identical helper in term_structure/sofr_market_data.py, needed for
    the same reason for fetch_sofr_calibration_data()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _tasty_root(product, name):
    root = TASTY_PRODUCTS.get(str(product).upper())
    if root is None:
        raise LispError(
            "%s: unknown product %r (supported: %s)"
            % (name, str(product), ", ".join(TASTY_PRODUCTS)))
    return root


def _tasty_resolve_symbol(symbol):
    """Classifies a symbol for tastytrade-option-chain and returns
    (kind, resolved) where kind is "future" or "equity":

      - Already starts with "/" (tastytrade's own convention for
        futures) -> ("future", symbol as given). Works for ANY futures
        root, not just ones in TASTY_PRODUCTS -- no translation needed,
        per tastytrade's own convention.
      - A known short code from TASTY_PRODUCTS (e.g. "CL") -> ("future",
        "/CL"), for backward compatibility with existing scripts that
        pass the short code.
      - Anything else (e.g. "AAPL", "SPY") -> ("equity", symbol
        upper-cased), fetched via the equity option-chain endpoint.
    """
    s = str(symbol).strip()
    if s.startswith("/"):
        return ("future", s)
    upper = s.upper()
    root = TASTY_PRODUCTS.get(upper)
    if root is not None:
        return ("future", root)
    return ("equity", upper)


def _tasty_load_credentials(path):
    path = str(path)
    if not os.path.exists(path):
        raise LispError("tastytrade: credentials file not found: %s" % path)
    try:
        with open(path) as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        raise LispError("tastytrade: credentials file isn't valid JSON: %s" % e)
    for key in ("client_secret", "refresh_token"):
        if isinstance(creds.get(key), str):
            creds[key] = creds[key].strip()
    missing = [k for k in ("client_secret", "refresh_token") if not creds.get(k)]
    if missing:
        raise LispError("tastytrade: credentials file is missing: %s" % ", ".join(missing))
    return creds


def _tasty_session(credentials_path):
    if not _TASTYTRADE_AVAILABLE:
        raise LispError(
            "tastytrade: the 'tastytrade' package is not installed (pip install tastytrade)")
    creds = _tasty_load_credentials(credentials_path)
    return _TTSession(
        creds["client_secret"], creds["refresh_token"],
        is_test=bool(creds.get("is_test", False)))


def _tasty_pick_price(md):
    """Prefer settled/close price; fall back to last trade, then mark/mid."""
    for attr in ("close", "last", "mark", "mid"):
        val = getattr(md, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _tasty_option_type_label(option_type):
    val = getattr(option_type, "value", option_type)
    return "Call" if str(val).upper().startswith("C") else "Put"


def _tasty_days_to_expiration(opt, exp_date, today):
    """Prefers the SDK's own days_to_expiration field; falls back to
    computing it from the expiration date if that's not populated."""
    dte = getattr(opt, "days_to_expiration", None)
    if dte is not None:
        try:
            return int(dte)
        except (TypeError, ValueError):
            pass
    if hasattr(exp_date, "toordinal") and hasattr(today, "toordinal"):
        return (exp_date - today).days
    return None


def _tasty_parse_delivery_month(underlying_symbol, reference_date=None):
    """Parse a CME futures trading symbol (single-digit year, e.g.
    '/CLZ6') into its delivery month (first-of-month date). Returns None
    if unparseable. See tasty_api/tastytrade_source.py's
    parse_delivery_month for the full rationale."""
    if not underlying_symbol:
        return None
    sym = underlying_symbol.lstrip("/")
    if len(sym) < 3:
        return None
    year_digits = ""
    i = len(sym) - 1
    while i >= 0 and sym[i].isdigit():
        year_digits = sym[i] + year_digits
        i -= 1
    if not year_digits or i < 0:
        return None
    month_code = sym[i]
    if month_code not in TASTY_CODE_TO_MONTH:
        return None
    month = TASTY_CODE_TO_MONTH[month_code]

    reference_date = reference_date or datetime.date.today()
    if len(year_digits) >= 2:
        year = 2000 + int(year_digits[-2:])
    else:
        last_digit = int(year_digits)
        base_decade = (reference_date.year // 10) * 10
        year = base_decade + last_digit
        if year < reference_date.year - 2:
            year += 10
    try:
        return datetime.date(year, month, 1)
    except ValueError:
        return None


async def _tasty_test_connection_async(credentials_path):
    session = _tasty_session(credentials_path)
    from tastytrade import Account
    raw = Account.get(session)
    accounts = await _tasty_maybe_await(raw)
    if not accounts:
        return "Connected, but no accounts were found on this login."
    numbers = ", ".join(getattr(a, "account_number", str(a)) for a in accounts)
    return "Connected successfully. Account(s): %s." % numbers


def tastytrade_test_connection_fn(credentials_path):
    """(tastytrade-test-connection credentials-path) -> a status string.
    Raises a LispError on any authentication/connection failure."""
    return LispString(_run_async(_tasty_test_connection_async(credentials_path)))


async def _tasty_futures_curve_async(credentials_path, product, n_months):
    session = _tasty_session(credentials_path)
    root = _tasty_root(product, "tastytrade-futures-curve")

    today = datetime.date.today()
    y, m = today.year, today.month
    candidate_symbols, candidate_months = [], []
    for i in range(int(n_months)):
        total = (m - 1) + i
        mm = total % 12 + 1
        yyyy = y + total // 12
        code = TASTY_MONTH_CODES[mm]
        # tastytrade's plain trading symbol uses a single-digit year
        # (e.g. "/CLZ6" for Dec 2026), unlike the streamer symbol.
        candidate_symbols.append("%s%s%d" % (root, code, yyyy % 10))
        candidate_months.append(datetime.date(yyyy, mm, 1))

    market_data = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, futures=candidate_symbols))
    price_by_symbol = {md.symbol: _tasty_pick_price(md) for md in market_data}

    rows = []  # (delivery_date, symbol_without_slash, days_to_delivery, price)
    for sym, delivery in zip(candidate_symbols, candidate_months):
        price = price_by_symbol.get(sym)
        if price is None:
            continue
        rows.append((delivery, sym.lstrip("/"), (delivery - today).days, price))
    return rows


def tastytrade_futures_curve_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve credentials-path product [n-months]) ->
    (cons delivery-dates-vector last-prices-vector), one entry per upcoming
    contract month that actually has a price (guessed contract months that
    don't exist for this product -- e.g. non-quarterly months for ES/NQ/ZN
    -- are silently skipped). `product` is one of "CL", "MCL", "ES", "NQ",
    "SR3", "ZN", "ZQ". Feed the result straight into plot-xy,
    linear-regression, spline-regression, etc.
    See also tastytrade-futures-curve-rows, which additionally includes
    each contract's symbol and days-to-delivery -- needed by
    tastytrade-curve-fit and tastytrade-leg-carry."""
    rows = _run_async(_tasty_futures_curve_async(credentials_path, product, int(n_months)))
    dates = [LispDate(d.year, d.month, d.day) for d, _sym, _dte, _price in rows]
    prices = [price for _d, _sym, _dte, price in rows]
    return Pair(LispVector(dates), LispVector(prices))


def tastytrade_futures_curve_rows_fn(credentials_path, product, n_months=18):
    """(tastytrade-futures-curve-rows credentials-path product [n-months])
    -> a Lisp list of rows, each row a 4-element list:
       (delivery-month futures-symbol days-to-delivery last-price)
    one per upcoming contract month that actually has a price (same
    coverage as tastytrade-futures-curve, just with the extra fields
    tastytrade-curve-fit and tastytrade-leg-carry need). Fetch once with
    this, then call either analysis function as many times as you like
    with different rate/threshold assumptions, with no re-fetch needed --
    they're pure functions over the row data, no networking."""
    rows = _run_async(_tasty_futures_curve_async(credentials_path, product, int(n_months)))
    return list_to_pairs([
        list_to_pairs([
            LispDate(d.year, d.month, d.day),
            LispString(sym),
            int(dte),
            float(price),
        ])
        for d, sym, dte, price in rows
    ])


def _tasty_row_field(row, index):
    """row is a Python list already extracted via pairs_to_list(); pulls
    field `index` and unwraps a LispDate to a plain datetime.date where
    relevant, otherwise returns the raw value."""
    val = row[index]
    return val.date if isinstance(val, LispDate) else val


def tastytrade_curve_fit_fn(curve_rows, rich_cheap_threshold_pct=0.75, poly_degree=None):
    """(tastytrade-curve-fit curve-rows [rich-cheap-threshold-pct poly-degree])
    -> a Lisp list of rows, each row a 7-element list:
       (delivery-month futures-symbol days-to-delivery last-price
        fitted-price rich-cheap-pct signal)
    `curve-rows` is the output of tastytrade-futures-curve-rows (or
    anything shaped the same way). Fits ln(price) vs. days-to-delivery
    with a low-order polynomial (degree = min(3, n-1) unless
    `poly-degree` is given) across ALL rows, and flags each contract's
    deviation from that fitted curve: `signal` is "Rich" if the contract
    trades more than `rich-cheap-threshold-pct` above the fit, "Cheap" if
    that far below, else "Fair". This is a pure function -- no
    networking -- so it's cheap to re-run with different assumptions.
    Needs at least 3 rows; returns '() if there aren't enough."""
    import numpy as np

    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 3:
        return NIL

    rows = sorted(rows, key=lambda r: _tasty_row_field(r, 2))
    x = np.array([float(_tasty_row_field(r, 2)) for r in rows], dtype=float)
    y = np.log(np.array([float(_tasty_row_field(r, 3)) for r in rows], dtype=float))

    n = len(rows)
    degree = int(poly_degree) if poly_degree is not None and is_true(poly_degree) else min(3, max(1, n - 1))
    degree = max(1, min(degree, n - 1))

    coeffs = np.polyfit(x, y, degree)
    fitted_price = np.exp(np.polyval(coeffs, x))
    threshold = float(rich_cheap_threshold_pct)

    out_rows = []
    for r, fitted in zip(rows, fitted_price):
        last_price = float(_tasty_row_field(r, 3))
        pct = (last_price - fitted) / fitted * 100
        if pct > threshold:
            signal = "Rich"
        elif pct < -threshold:
            signal = "Cheap"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            r[0], r[1], r[2], r[3],
            float(fitted), float(pct), LispString(signal),
        ]))
    return list_to_pairs(out_rows)


def tastytrade_leg_carry_fn(curve_rows, funding_rate_pct, storage_cost_pct,
                             leg_signal_threshold_pct=1.0):
    """(tastytrade-leg-carry curve-rows funding-rate-pct storage-cost-pct
         [leg-signal-threshold-pct])
    -> a Lisp list of rows, each row a 9-element list:
       (near-month far-month near-price far-price days-between
        implied-carry-rate-pct implied-net-storage-cost-pct
        implied-convenience-yield-pct signal)
    Pairwise (adjacent contract month) implied cost-of-carry decomposition:
    for each pair, c = ln(far-price/near-price)/(days-between/365) is the
    OBSERVED implied annualized carry rate; given your `funding-rate-pct`
    (r) and `storage-cost-pct` (u) assumptions, net storage cost = c - r
    and convenience yield = r + u - c. `signal` flags a leg whose carry
    rate deviates from the MEDIAN carry rate across all legs by more than
    `leg-signal-threshold-pct` (percentage points), in either direction.
    `storage-cost-pct`/convenience-yield are only literally meaningful for
    a storable physical commodity (e.g. CL) -- for financial futures
    (ES, NQ, ZN, SR3...) there's no real storage, so read those two
    fields as an illustrative decomposition of implied carry, not an
    actual estimate; the carry rate itself is still meaningful either
    way. `curve-rows` is the output of tastytrade-futures-curve-rows.
    Pure function -- no networking. Needs at least 2 rows; returns '()
    if there aren't enough, or if no adjacent pair has positive spacing."""
    import numpy as np

    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if len(rows) < 2:
        return NIL

    rows = sorted(rows, key=lambda r: _tasty_row_field(r, 2))
    r = float(funding_rate_pct) / 100.0
    u = float(storage_cost_pct) / 100.0

    legs = []
    carries = []
    for i in range(len(rows) - 1):
        near, far = rows[i], rows[i + 1]
        near_days = float(_tasty_row_field(near, 2))
        far_days = float(_tasty_row_field(far, 2))
        days_between = far_days - near_days
        if days_between <= 0:
            continue
        near_price = float(_tasty_row_field(near, 3))
        far_price = float(_tasty_row_field(far, 3))
        dt_years = days_between / 365.0
        c = np.log(far_price / near_price) / dt_years
        net_storage = c - r
        convenience_yield = r + u - c
        carries.append(c)
        legs.append((near, far, near_price, far_price, days_between, c, net_storage, convenience_yield))

    if not legs:
        return NIL

    median_carry = float(np.median(carries))
    threshold = float(leg_signal_threshold_pct)

    out_rows = []
    for near, far, near_price, far_price, days_between, c, net_storage, convenience_yield in legs:
        pct_diff = (c - median_carry) * 100
        if pct_diff > threshold:
            signal = "Far month rich / near cheap"
        elif pct_diff < -threshold:
            signal = "Far month cheap / near rich"
        else:
            signal = "Fair"
        out_rows.append(list_to_pairs([
            near[0], far[0], near_price, far_price, int(days_between),
            float(c * 100), float(net_storage * 100), float(convenience_yield * 100),
            LispString(signal),
        ]))
    return list_to_pairs(out_rows)


# CME 3-Month SOFR (SR3) futures reference a 3-month accrual quarter that
# ENDS at the contract's delivery month -- see term_structure_model.
# bootstrap_sofr_curve()'s docstring for exactly what start_months/
# end_months mean and the simplifications baked into treating a whole
# quarter as one flat forward rate. Same day-count convention
# sofr_market_data.py uses, for consistency with the rest of that module.
_SOFR_DAYS_PER_MONTH = 30.436875


def sofr_forward_curve_fn(curve_rows):
    """(sofr-forward-curve curve-rows) -> (cons months-vector forward-rates-vector)
    curve-rows is the output of (tastytrade-futures-curve-rows creds "SR3"
    [n-months]) -- one row per listed CME 3-Month SOFR (SR3) futures
    contract: (delivery-month symbol days-to-delivery last-price).
    Bootstraps a 360-month (30-year) curve of 1-month forward rates
    implied by those futures prices, by reusing
    term_structure_model.bootstrap_sofr_curve() as-is (see
    term_structure/term_structure_model.py for the full methodology and
    its documented simplifications -- flat extrapolation beyond the last
    listed contract, no convexity adjustment, etc.) -- this function's
    only job is shaping tastytrade-futures-curve-rows's output into the
    {start_months, end_months, rate} dicts that function expects.

    months-vector is 1..360; forward-rates-vector[i] (0-indexed) is the
    annualized 1-month forward rate (decimal, e.g. 0.045) for month i+1
    -- (vector-ref forward-rates-vector (- month 1)). Feed straight into
    plot-xy, or read a period's rate by row index in a column's
    value_calculation for a floating-rate coupon or a mortgage
    prepayment model's rate-incentive calculation -- see
    sofr_floating_rate_example.lsp. Pure function -- no networking --
    so it's cheap to re-run against the same fetched curve-rows.
    Needs at least 1 row; raises LispError if curve-rows is empty, or if
    term_structure_model.py (and numpy) aren't importable."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-forward-curve: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_rows)]
    if not rows:
        raise LispError("sofr-forward-curve: curve-rows is empty")

    sofr_futures = []
    for r in rows:
        days = float(_tasty_row_field(r, 2))
        price = float(_tasty_row_field(r, 3))
        end_months = round(days / _SOFR_DAYS_PER_MONTH)
        sofr_futures.append({
            "start_months": end_months - 3,
            "end_months": end_months,
            "rate": (100.0 - price) / 100.0,
        })

    result = _bootstrap_sofr_curve(sofr_futures)
    months = LispVector([int(m) for m in result["months"]])
    forward_rates = LispVector([float(fr) for fr in result["forward_rates"]])
    return Pair(months, forward_rates)


def sofr_calibration_data_fn(credentials_path, n_futures=40, n_underlyings=10, n_strikes=3):
    """(sofr-calibration-data credentials-path [n-futures n-underlyings
    n-strikes]) -> (cons curve-futures-rows options-rows) -- everything
    needed to bootstrap a SOFR curve AND calibrate the two-factor model
    against real SOFR futures option prices, fetched in ONE tastytrade
    session. Reuses sofr_market_data.fetch_sofr_calibration_data() as-is
    (see term_structure/sofr_market_data.py for the full selection
    methodology: options spread evenly across every curve quarter that
    has a listed chain, not just the nearest few, so sigma1 and sigma2 --
    see sofr-calibrate-model -- are separately identifiable). A SEPARATE
    fetch from tastytrade-futures-curve-rows -- this one also pulls
    option chains, not just futures prices.

    curve-futures-rows: one row per SR3 contract month used for the
    curve, each (symbol start-months end-months rate) -- feed to
    sofr-bootstrap-curve.
    options-rows: up to n-underlyings*n-strikes*2 near-the-money call/put
    pairs spread across n-underlyings different quarterly contracts, each
    (type strike expiry-months quarter-start-months quarter-end-months
    market-price) -- feed to sofr-calibrate-model.

    Needs the `tastytrade` package, a tastytrade account, and a
    credentials JSON file -- see tasty_api/README.md. Raises LispError if
    sofr_market_data.py isn't importable (the tastytrade package itself,
    and any fetch failure, raise their own errors from inside
    fetch_sofr_calibration_data)."""
    if not _SOFR_MARKET_DATA_AVAILABLE:
        raise LispError(
            "sofr-calibration-data: sofr_market_data.py isn't available -- "
            "see term_structure/ next to lisp_interp/")
    curve, options = _fetch_sofr_calibration_data(
        str(credentials_path), int(n_futures), int(n_underlyings), int(n_strikes))
    curve_rows = list_to_pairs([
        list_to_pairs([LispString(c["symbol"]), int(c["start_months"]),
                        int(c["end_months"]), float(c["rate"])])
        for c in curve
    ])
    options_rows = list_to_pairs([
        list_to_pairs([LispString(o["type"]), float(o["strike"]), int(o["expiry_months"]),
                        int(o["quarter_start_months"]), int(o["quarter_end_months"]),
                        float(o["market_price"])])
        for o in options
    ])
    return Pair(curve_rows, options_rows)


def sofr_bootstrap_curve_fn(curve_futures_rows):
    """(sofr-bootstrap-curve curve-futures-rows) -> (cons months-vector
    forward-rates-vector). curve-futures-rows is sofr-calibration-data's
    FIRST return value (or anything shaped the same way: a list of
    (symbol start-months end-months rate) rows) -- bootstraps the
    360-month forward curve directly from it via
    term_structure_model.bootstrap_sofr_curve(), the same underlying
    function sofr-forward-curve uses, just taking sofr-calibration-data's
    row shape instead of tastytrade-futures-curve-rows's (no day-count
    reshaping needed here -- these rows already carry start-months/
    end-months directly). Pure function -- no networking. Raises
    LispError if curve-futures-rows is empty, or term_structure_model.py
    isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-bootstrap-curve: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    rows = [pairs_to_list(r) for r in pairs_to_list(curve_futures_rows)]
    if not rows:
        raise LispError("sofr-bootstrap-curve: curve-futures-rows is empty")
    sofr_futures = [
        {"start_months": int(r[1]), "end_months": int(r[2]), "rate": float(r[3])}
        for r in rows
    ]
    result = _bootstrap_sofr_curve(sofr_futures)
    months = LispVector([int(m) for m in result["months"]])
    forward_rates = LispVector([float(fr) for fr in result["forward_rates"]])
    return Pair(months, forward_rates)


def sofr_calibrate_model_fn(forward_rates, options_rows, curve_real_months,
                             n_paths=2000, seed=42, n_grid=7, n_rounds=4):
    """(sofr-calibrate-model forward-rates options-rows curve-real-months
    [n-paths seed n-grid n-rounds]) -> (list a theta-bar sigma1 sigma2
    error) -- fits the two-factor model's mean-reversion speed (a) and
    both volatilities (sigma1: the short-rate factor; sigma2: the
    slower-moving mean-reversion-LEVEL factor) directly against real SOFR
    futures option prices, by a "zooming grid search" (try a grid of
    (a, sigma1, sigma2) combinations, keep whichever prices the options
    closest, shrink the search window around it, repeat n-rounds times).
    Reuses term_structure_model.calibrate_sofr_model() as-is; see that
    function's docstring for the full methodology, including WHY it fits
    `a` against option prices directly rather than against today's curve
    shape (found, on real data, to noticeably improve the fit over a
    curve-shape-only fit) and theta-bar's role (refit in closed form, so
    cheap, at every candidate `a` tried).

    forward-rates: sofr-forward-curve's or sofr-bootstrap-curve's second
        return value.
    options-rows: sofr-calibration-data's second return value (or
        anything shaped the same way).
    curve-real-months: how many months of forward-rates are the REAL
        (non-extrapolated) part of the curve -- i.e. the largest
        end-months among the curve-futures-rows sofr-calibration-data
        (or sofr-bootstrap-curve) was given.
    n-paths: Monte Carlo paths used to price EACH option at EACH
        candidate (a, sigma1, sigma2) tried -- an accuracy/speed
        trade-off for the CALIBRATION itself, separate from how many
        SCENARIO paths sofr-simulate-rate-paths later generates.
    n-grid / n-rounds: grid resolution per round / how many times to zoom
        in -- cost is roughly O(n-grid^3 * n-rounds * n-paths * number of
        options), so raising these can get slow fast; the
        term_structure_model.py module docstring reports ten-to-twenty
        seconds for its own real-data test at these same defaults
        (n-paths 2000, n-grid 7, n-rounds 4) and a handful of options.

    Pure function -- no networking -- so it's cheap to re-run with
    different options-rows/settings once you've fetched once. Raises
    LispError if options-rows is empty, or term_structure_model.py isn't
    available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-calibrate-model: term_structure_model.py (and numpy) aren't "
            "available -- see term_structure/ next to lisp_interp/")
    options = [pairs_to_list(r) for r in pairs_to_list(options_rows)]
    if not options:
        raise LispError("sofr-calibrate-model: options-rows is empty")
    option_dicts = [{
        "type": str(o[0]), "strike": float(o[1]), "expiry_months": int(o[2]),
        "quarter_start_months": int(o[3]), "quarter_end_months": int(o[4]),
        "market_price": float(o[5]),
    } for o in options]
    forward_rates_list = [float(v) for v in forward_rates.items]
    a, theta_bar, sigma1, sigma2, error = _calibrate_sofr_model(
        forward_rates_list, option_dicts, int(curve_real_months),
        n_paths=int(n_paths), seed=int(seed), n_grid=int(n_grid), n_rounds=int(n_rounds))
    return list_to_pairs([float(a), float(theta_bar), float(sigma1), float(sigma2), float(error)])


def sofr_simulate_rate_paths_fn(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                 seed=None, a=None, theta_bar=None):
    """(sofr-simulate-rate-paths forward-rates sigma1 sigma2 horizon-years
    n-paths [seed a theta-bar]) -> (list years-vector short-rate-paths
    ten-year-paths) -- simulates n-paths Monte Carlo scenarios of the
    two-factor model (a short-rate factor and a slower mean-reversion-
    level factor -- see term_structure/term_structure_model.py's module
    docstring) forward horizon-years, reusing
    term_structure_model.simulate_rate_paths() as-is.

    years: a vector of times in years -- 0, 1/12, 2/12, ... out to
        horizon-years.
    short-rate-paths / ten-year-paths: each a Lisp LIST of
        (horizon-years*12 + 1)-element vectors, one vector per path:
        short-rate-paths[i] is Monte Carlo path i's short-rate factor
        over time; ten-year-paths[i] is that SAME path's approximate
        ten-year rate (a closed-form function of the path's state, not a
        separately-simulated factor).

    a / theta-bar: pass sofr-calibrate-model's fitted `a`/theta-bar (its
        first two return values) when forward-rates came from
        sofr-bootstrap-curve/sofr-forward-curve, rather than leaving
        these '() (this function's own default: a fixed mean-reversion
        speed, and theta-bar as the average of forward-rates' last 2
        years) -- a SOFR curve is flat-extrapolated past its last real
        futures quarter, so that default would anchor theta-bar at an
        arbitrary value with no connection to real market data. See
        calibrate_sofr_model()'s docstring in term_structure_model.py.
    seed: '() (the default) for a fresh random seed each call; an
        integer for reproducible paths.

    Pure function -- no networking. Raises LispError if
    term_structure_model.py isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-simulate-rate-paths: term_structure_model.py (and numpy) "
            "aren't available -- see term_structure/ next to lisp_interp/")
    forward_rates_list = [float(v) for v in forward_rates.items]
    kwargs = {}
    if a is not None:
        kwargs["a"] = float(a)
    if theta_bar is not None:
        kwargs["theta_bar"] = float(theta_bar)
    years, r_paths, ten_year_paths = _simulate_rate_paths(
        forward_rates_list, float(sigma1), float(sigma2), float(horizon_years), int(n_paths),
        seed=(int(seed) if seed is not None else None), **kwargs)
    years_vec = LispVector([float(y) for y in years])
    r_paths_list = list_to_pairs([LispVector([float(x) for x in row]) for row in r_paths])
    ten_year_list = list_to_pairs([LispVector([float(x) for x in row]) for row in ten_year_paths])
    return list_to_pairs([years_vec, r_paths_list, ten_year_list])


def sofr_simulate_mortgage_rate_paths_fn(forward_rates, sigma1, sigma2, horizon_years, n_paths,
                                          mortgage_spread, seed=None, a=None, theta_bar=None,
                                          tenor_years=10):
    """(sofr-simulate-mortgage-rate-paths forward-rates sigma1 sigma2
    horizon-years n-paths mortgage-spread [seed a theta-bar tenor-years])
    -> (list years-vector short-rate-paths underlying-paths
    mortgage-paths) -- the same simulation as sofr-simulate-rate-paths,
    plus a simple proxy mortgage rate per path/month:
        mortgage_rate = tenor-years-rate + mortgage-spread
    (tenor-years-rate is the model's approximate tenor-years rate --
    defaults to 10, the usual rate-sensitivity proxy for a 30-year
    mortgage; underlying-paths in the return is that same quantity,
    before adding the spread). Reuses term_structure_model.
    simulate_mortgage_rate_paths() as-is -- see its docstring, and
    sofr-simulate-rate-paths's, for a/theta-bar/seed.

    SIMPLIFICATION (from the underlying model, not this bridge): a real
    mortgage rate tracks current-coupon MBS yields -- the whole curve,
    prepayment risk, origination costs -- not one flat spread over one
    tenor point; mortgage-spread is a deliberate simplification, named so
    it's obvious where to plug in something richer (see term_structure/
    mortgage_spread.py for one way to estimate it from real data --
    fetch_current_mortgage_rate() there pulls FRED's MORTGAGE30US).

    Pure function -- no networking. Raises LispError if
    term_structure_model.py isn't available."""
    if not _TERM_STRUCTURE_AVAILABLE:
        raise LispError(
            "sofr-simulate-mortgage-rate-paths: term_structure_model.py (and "
            "numpy) aren't available -- see term_structure/ next to lisp_interp/")
    forward_rates_list = [float(v) for v in forward_rates.items]
    kwargs = {}
    if a is not None:
        kwargs["a"] = float(a)
    if theta_bar is not None:
        kwargs["theta_bar"] = float(theta_bar)
    years, r_paths, underlying_paths, mortgage_paths = _simulate_mortgage_rate_paths(
        forward_rates_list, float(sigma1), float(sigma2), float(horizon_years), int(n_paths),
        float(mortgage_spread), seed=(int(seed) if seed is not None else None),
        tenor_years=float(tenor_years), **kwargs)
    years_vec = LispVector([float(y) for y in years])
    r_paths_list = list_to_pairs([LispVector([float(x) for x in row]) for row in r_paths])
    underlying_list = list_to_pairs([LispVector([float(x) for x in row]) for row in underlying_paths])
    mortgage_list = list_to_pairs([LispVector([float(x) for x in row]) for row in mortgage_paths])
    return list_to_pairs([years_vec, r_paths_list, underlying_list, mortgage_list])


async def _tasty_collect_greeks(session, streamer_symbols, timeout):
    from tastytrade import DXLinkStreamer
    from tastytrade.dxfeed import Greeks
    collected = {}
    if not streamer_symbols:
        return collected

    async def _listen():
        async with DXLinkStreamer(session) as streamer:
            await _tasty_maybe_await(streamer.subscribe(Greeks, streamer_symbols))
            async for event in streamer.listen(Greeks):
                collected[event.event_symbol] = event
                if len(collected) >= len(streamer_symbols):
                    break

    try:
        await asyncio.wait_for(_listen(), timeout=timeout)
    except asyncio.TimeoutError:
        pass  # illiquid strikes may simply never publish greeks in time
    except Exception:
        pass  # streaming API mismatch/hiccup -- return whatever we got
    return collected


async def _tasty_price_and_iv_for_options(session, opts, price_kwarg, include_iv, greeks_timeout):
    """Shared tail end of both the futures- and equity-option fetches:
    looks up last/close price, volume, and open interest via one-shot
    REST calls (chunked at 100 symbols), then optionally streams implied
    volatility via Greeks. `price_kwarg` is "future_options" or
    "options", matching get_market_data_by_type's parameter names for
    each instrument type."""
    option_symbols = [s for s in (getattr(o, "symbol", None) for o in opts) if s]
    option_md = []
    for i in range(0, len(option_symbols), 100):
        chunk = option_symbols[i:i + 100]
        option_md.extend(await _tasty_maybe_await(
            _tt_get_market_data_by_type(session, **{price_kwarg: chunk})))
    option_price = {md.symbol: _tasty_pick_price(md) for md in option_md}
    option_volume = {md.symbol: getattr(md, "volume", None) for md in option_md}
    option_oi = {md.symbol: getattr(md, "open_interest", None) for md in option_md}

    greeks_by_symbol = {}
    if include_iv:
        streamer_symbols = [s for s in (getattr(o, "streamer_symbol", None) for o in opts) if s]
        greeks_by_symbol = await _tasty_collect_greeks(session, streamer_symbols, float(greeks_timeout))

    return option_price, option_volume, option_oi, greeks_by_symbol


def _tasty_option_row(opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
                       delivery=None, underlying_label=None):
    symbol = getattr(opt, "symbol", None)
    streamer_symbol = getattr(opt, "streamer_symbol", None)
    strike = getattr(opt, "strike_price", None)
    exp_date = getattr(opt, "expiration_date", None)
    option_type = getattr(opt, "option_type", None)
    dte = _tasty_days_to_expiration(opt, exp_date, today)

    greeks = greeks_by_symbol.get(streamer_symbol)
    iv = getattr(greeks, "volatility", None) if greeks is not None else None
    price = option_price.get(symbol)
    volume = option_volume.get(symbol)
    oi = option_oi.get(symbol)

    return [
        LispString(symbol) if symbol else NIL,
        LispString(_tasty_option_type_label(option_type)) if option_type is not None else NIL,
        float(strike) if strike is not None else NIL,
        LispString(exp_date.isoformat()) if hasattr(exp_date, "isoformat") else NIL,
        int(dte) if dte is not None else NIL,
        LispDate(delivery.year, delivery.month, delivery.day) if delivery else NIL,
        LispString(underlying_label) if underlying_label else NIL,
        float(price) if price is not None else NIL,
        float(iv) if iv is not None else NIL,
        int(volume) if volume is not None else NIL,
        int(oi) if oi is not None else NIL,
    ]


async def _tasty_future_option_chain_async(session, root, n_months,
                                            max_strikes_per_expiration, include_iv, greeks_timeout):
    chain = await _tasty_maybe_await(_tt_get_future_option_chain(session, root))

    today = datetime.date.today()
    by_delivery_month = {}
    for exp_date, options in chain.items():
        for opt in options:
            delivery = _tasty_parse_delivery_month(getattr(opt, "underlying_symbol", ""), today) \
                or (exp_date.replace(day=1) if hasattr(exp_date, "replace") else None)
            if delivery is None:
                continue
            by_delivery_month.setdefault(delivery, []).append(opt)

    kept_months = sorted(mo for mo in by_delivery_month if mo >= today.replace(day=1))[:int(n_months)]
    candidate_options = [opt for mo in kept_months for opt in by_delivery_month[mo]]
    if not candidate_options:
        return []

    future_symbols = sorted({
        getattr(o, "underlying_symbol", None) for o in candidate_options
    } - {None})
    future_md = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, futures=future_symbols))
    future_price = {md.symbol: _tasty_pick_price(md) for md in future_md}

    grouped = {}
    for opt in candidate_options:
        key = (getattr(opt, "underlying_symbol", None), getattr(opt, "expiration_date", None))
        grouped.setdefault(key, []).append(opt)

    max_strikes_per_expiration = int(max_strikes_per_expiration)
    filtered_options = []
    for (underlying, _exp), opts in grouped.items():
        ref_price = future_price.get(underlying)
        if ref_price is not None:
            opts_sorted = sorted(
                opts, key=lambda o: abs(float(getattr(o, "strike_price", 0) or 0) - ref_price))
            filtered_options.extend(opts_sorted[: max_strikes_per_expiration * 2])
        else:
            filtered_options.extend(opts[: max_strikes_per_expiration * 2])

    option_price, option_volume, option_oi, greeks_by_symbol = await _tasty_price_and_iv_for_options(
        session, filtered_options, "future_options", include_iv, greeks_timeout)

    rows = []
    for opt in filtered_options:
        underlying = getattr(opt, "underlying_symbol", None) or ""
        delivery = _tasty_parse_delivery_month(underlying, today)
        rows.append(_tasty_option_row(
            opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
            delivery=delivery, underlying_label=underlying.lstrip("/")))
    return rows


async def _tasty_equity_option_chain_async(session, symbol, n_months,
                                            max_strikes_per_expiration, include_iv, greeks_timeout):
    chain = await _tasty_maybe_await(_tt_get_option_chain(session, symbol))

    today = datetime.date.today()
    cutoff = _tasty_add_months(today, int(n_months))
    candidate_options = [
        opt for exp_date, options in chain.items()
        if exp_date is not None and today <= exp_date <= cutoff
        for opt in options
    ]
    if not candidate_options:
        return []

    equity_md = await _tasty_maybe_await(
        _tt_get_market_data_by_type(session, equities=[symbol]))
    ref_price = _tasty_pick_price(equity_md[0]) if equity_md else None

    grouped = {}
    for opt in candidate_options:
        grouped.setdefault(getattr(opt, "expiration_date", None), []).append(opt)

    max_strikes_per_expiration = int(max_strikes_per_expiration)
    filtered_options = []
    for _exp, opts in grouped.items():
        if ref_price is not None:
            opts_sorted = sorted(
                opts, key=lambda o: abs(float(getattr(o, "strike_price", 0) or 0) - ref_price))
            filtered_options.extend(opts_sorted[: max_strikes_per_expiration * 2])
        else:
            filtered_options.extend(opts[: max_strikes_per_expiration * 2])

    option_price, option_volume, option_oi, greeks_by_symbol = await _tasty_price_and_iv_for_options(
        session, filtered_options, "options", include_iv, greeks_timeout)

    return [
        _tasty_option_row(opt, today, option_price, option_volume, option_oi, greeks_by_symbol,
                          delivery=None, underlying_label=symbol)
        for opt in filtered_options
    ]


def _tasty_add_months(d, n):
    """d shifted forward by n months, clamped to the last valid day of
    the target month (e.g. Jan 31 + 1 month -> Feb 28/29, not Mar 3)."""
    month0 = d.month - 1 + int(n)
    year = d.year + month0 // 12
    month = month0 % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


async def _tasty_option_chain_async(credentials_path, symbol, n_months,
                                     max_strikes_per_expiration, include_iv, greeks_timeout):
    session = _tasty_session(credentials_path)
    kind, resolved = _tasty_resolve_symbol(symbol)
    if kind == "future":
        return await _tasty_future_option_chain_async(
            session, resolved, n_months, max_strikes_per_expiration, include_iv, greeks_timeout)
    else:
        return await _tasty_equity_option_chain_async(
            session, resolved, n_months, max_strikes_per_expiration, include_iv, greeks_timeout)


def tastytrade_option_chain_fn(credentials_path, symbol, n_months=12,
                                max_strikes_per_expiration=15, include_iv=True,
                                greeks_timeout=25.0):
    """(tastytrade-option-chain credentials-path symbol
         [n-months max-strikes-per-expiration include-iv? greeks-timeout])
    -> a Lisp list of rows, each row an 11-element list:
       (symbol type strike expiration-date days-to-expiration delivery-month
        underlying last-price implied-volatility volume open-interest)

    `symbol` can be:
      - A futures root starting with "/" (tastytrade's own convention,
        e.g. "/CL", "/ES") -- works for any futures product, not just
        ones with a curated short code.
      - A known short code from tastytrade-products (e.g. "CL"), kept
        for backward compatibility -- translated to "/CL" automatically.
      - Any other symbol (e.g. "AAPL", "SPY") -> fetched as an EQUITY
        option chain. No translation needed or done.

    `type` is the string "Call" or "Put". `delivery-month` and
    `underlying` are futures-specific: for equities, `delivery-month` is
    always '() and `underlying` is just the equity symbol itself. For
    equities, `n-months` limits results to expirations within that many
    months from today (there's no separate "delivery month" for an
    equity option the way there is for a futures option, so this is the
    closest equivalent). Missing values (e.g. no recent Greeks snapshot
    for implied-volatility) come back as '() (the empty list). Each
    expiration is trimmed to the `max-strikes-per-expiration` strikes
    nearest the underlying's price, since implied volatility comes from
    a live per-contract Greeks stream (`include-iv?` defaults to #t;
    pass #f to skip the stream entirely and fetch much faster).
    `greeks-timeout` (seconds) caps how long that stream is awaited."""
    rows = _run_async(_tasty_option_chain_async(
        credentials_path, symbol, int(n_months), int(max_strikes_per_expiration),
        is_true(include_iv), float(greeks_timeout)))
    return list_to_pairs([list_to_pairs(row) for row in rows])


def tastytrade_products_fn():
    """(tastytrade-products) -> a Lisp list of supported product code strings."""
    return list_to_pairs([LispString(code) for code in TASTY_PRODUCTS])


def make_global_env(output=None, plot=None, columns=None):
    """Build the global environment of built-in procedures.

    `output` is a one-argument function that receives raw text produced by
    `display`, `newline`, and `print`. `plot` is a one-argument function
    that receives a chart spec dict (see build_chart_spec) produced by the
    `plot-xy...` builtins. `columns` is a one-argument function that
    receives a list of (name, values) tuples produced by the
    `display-columns` builtin. All three default to plain-text console
    behavior, but the GUI supplies callbacks that update its on-screen log,
    chart tab, and columns table instead -- the interpreter core doesn't
    need to know anything about Qt for this to work.
    """
    if output is None:
        output = lambda s: print(s, end="")

    # A mutable "current sink" -- output_state["fn"] is what display/
    # newline/print (and the default no-GUI plot fallback below) actually
    # write to. Starts out equal to `output` (the console/GUI callback
    # this function was given), but the redirect-output/reset-output
    # builtins can retarget it to a file and back, without needing to
    # rebuild the whole environment. See those builtins, in the I/O
    # section below, for why it's structured this way.
    output_state = {"fn": output, "file": None}

    def emit(s):
        output_state["fn"](s)

    if plot is None:
        def plot(spec):
            lines = ["[chart] %s" % spec["title"]]
            for s in spec["series"]:
                how = "connected" if s["connect"] else "points only"
                lines.append("  %s: %d points (%s)" % (s["label"], len(s["y"]), how))
            if spec["regression"]:
                r = spec["regression"]
                lines.append(
                    "  %s regression on %s: slope=%.6g intercept=%.6g"
                    % (r["kind"], r["label"], r["model"].coefficients[0], r["model"].intercept))
            emit("\n".join(lines) + "\n")

    if columns is None:
        def columns(name_value_pairs):
            # name_value_pairs' values are already display-formatted
            # strings by this point (see display_columns_fn, below) --
            # right-justify each column to its own widest cell (header
            # included) so a column of numbers lines up on its ones
            # place, the same way the GUI's monospace/right-aligned
            # Columns tab does.
            widths = [max([len(name)] + [len(str(v)) for v in values])
                      for name, values in name_value_pairs]
            rows = max((len(values) for _, values in name_value_pairs), default=0)
            def row(cells):
                return "  ".join(str(c).rjust(w) for c, w in zip(cells, widths))
            lines = [row([name for name, _ in name_value_pairs])]
            for i in range(rows):
                lines.append(row(
                    values[i] if i < len(values) else ""
                    for _, values in name_value_pairs))
            emit("\n".join(lines) + "\n")

    env = Env()

    # ---- arithmetic ----
    def add(*args):
        check_numbers(args, "+")
        total = 0
        for a in args:
            total += a
        return total

    def sub(*args):
        check_numbers(args, "-")
        if not args:
            raise LispError("- needs at least one argument")
        if len(args) == 1:
            return -args[0]
        total = args[0]
        for a in args[1:]:
            total -= a
        return total

    def mul(*args):
        check_numbers(args, "*")
        total = 1
        for a in args:
            total *= a
        return total

    def div(*args):
        check_numbers(args, "/")
        if not args:
            raise LispError("/ needs at least one argument")
        if len(args) == 1:
            return 1 / args[0]
        total = args[0]
        for a in args[1:]:
            total /= a
        return total

    def chain_compare(op, args):
        for a, b in zip(args, args[1:]):
            if not op(a, b):
                return False
        return True

    env.update({
        "+": add,
        "-": sub,
        "*": mul,
        "/": div,
        "mod": lambda a, b: a % b,
        "quotient": lambda a, b: int(a / b),
        "remainder": lambda a, b: a % b,
        "abs": abs,
        "min": lambda *a: min(a),
        "max": lambda *a: max(a),
        "sqrt": math.sqrt,
        "pow": math.pow,
        "log": math.log,
        "expt": lambda a, b: a ** b,
        "floor": lambda x: math.floor(x),
        "ceiling": lambda x: math.ceil(x),
        "truncate": lambda x: math.trunc(x),
        "round": lambda x: round(x),
        "=": lambda *a: chain_compare(lambda x, y: x == y, a),
        "<": lambda *a: chain_compare(lambda x, y: x < y, a),
        ">": lambda *a: chain_compare(lambda x, y: x > y, a),
        "<=": lambda *a: chain_compare(lambda x, y: x <= y, a),
        ">=": lambda *a: chain_compare(lambda x, y: x >= y, a),
    })

    # ---- booleans / equality ----
    env.update({
        "not": lambda x: not is_true(x),
        "eq?": lambda a, b: a is b or a == b,
        "equal?": lambda a, b: a == b,
    })

    # ---- pairs / lists ----
    def car(p):
        if not isinstance(p, Pair):
            raise LispError("car: not a pair: %r" % (p,))
        return p.car

    def cdr(p):
        if not isinstance(p, Pair):
            raise LispError("cdr: not a pair: %r" % (p,))
        return p.cdr

    def append2(a, b):
        items = pairs_to_list(a)
        result = b
        for item in reversed(items):
            result = Pair(item, result)
        return result

    def lisp_append(*lists):
        result = NIL
        for lst in reversed(lists):
            result = append2(lst, result)
        return result

    def lisp_map(f, lst):
        return list_to_pairs([apply_proc(f, [x]) for x in pairs_to_list(lst)])

    def lisp_filter(f, lst):
        return list_to_pairs([x for x in pairs_to_list(lst) if is_true(apply_proc(f, [x]))])

    def lisp_reduce(f, lst, *init):
        items = pairs_to_list(lst)
        if init:
            acc = init[0]
        else:
            acc, items = items[0], items[1:]
        for x in items:
            acc = apply_proc(f, [acc, x])
        return acc

    def list_ref(lst, n):
        items = pairs_to_list(lst)
        n = int(n)
        if n < 0 or n >= len(items):
            raise LispError("list-ref: index %d out of range (0..%d)" % (n, len(items) - 1))
        return items[n]

    env.update({
        "cons": lambda a, b: Pair(a, b),
        "car": car,
        "cdr": cdr,
        "list": lambda *args: list_to_pairs(list(args)),
        "append": lisp_append,
        "reverse": lambda p: list_to_pairs(list(reversed(pairs_to_list(p)))),
        "length": lambda p: len(pairs_to_list(p)),
        "list-ref": list_ref,
        "null?": lambda p: p is NIL,
        "pair?": lambda p: isinstance(p, Pair),
        "list?": lambda p: p is NIL or isinstance(p, Pair),
        "map": lisp_map,
        "filter": lisp_filter,
        "reduce": lisp_reduce,
    })

    # ---- metaprogramming: eval, apply, gensym, load ----
    def lisp_apply(f, *args):
        """(apply f arg1 arg2 ... args) -- call f with arg1, arg2, ...
        as individual arguments, followed by the ELEMENTS of the final
        argument `args` (a list). (apply f lst) -- just the final list,
        no individual leading arguments -- is the common special case."""
        if not args:
            raise LispError("apply: expected at least 2 arguments (a procedure and a list)")
        *leading, last = args
        return apply_proc(f, list(leading) + pairs_to_list(last))

    def lisp_eval(expr):
        """(eval expr) -- evaluate a piece of Lisp code (as DATA -- e.g.
        something built with quasiquote/list/cons, or read from a string
        or file) in the top-level global environment. A macro's own
        expansion is already evaluated automatically by the evaluator;
        this is for the separate case of constructing or obtaining an
        expression some other way and wanting to run it directly."""
        return seval(expr, env)

    def lisp_macroexpand_1(form):
        """(macroexpand-1 'form) -- if `form` is a macro CALL (a list
        whose car names a macro currently bound in the top-level
        environment -- the same env `eval` uses), expand it ONE level
        and return the resulting expression as DATA, without evaluating
        it. Anything else (a non-list, or a list whose car isn't a
        macro) is returned unchanged, matching Common Lisp's
        macroexpand-1. Quote `form` yourself, the same way `eval`
        expects an already-built expression rather than auto-quoting
        its argument -- see "why gensym is needed" in the Macros
        section for a worked example of reading an expansion this way."""
        if not isinstance(form, Pair) or not isinstance(form.car, Symbol):
            return form
        macro = env.lookup_or_none(form.car)
        if not isinstance(macro, Macro):
            return form
        return expand_macro(macro, pairs_to_list(form.cdr))

    def lisp_macroexpand(form):
        """(macroexpand 'form) -- like macroexpand-1, but keeps
        re-expanding the OUTERMOST form as long as it's still a macro
        call, so a macro that itself expands into a call to another
        macro is fully unwound in one step (matching Common Lisp's
        macroexpand). Does NOT expand macro calls nested inside the
        result -- only the outermost form, same as macroexpand-1."""
        while isinstance(form, Pair) and isinstance(form.car, Symbol) \
                and isinstance(env.lookup_or_none(form.car), Macro):
            form = lisp_macroexpand_1(form)
        return form

    def lisp_print_macroexpansion(form):
        """(print-macroexpansion 'form) -- (macroexpand form), pretty-
        printed, for a readable look at exactly what a macro call turns
        into WITHOUT evaluating (or running any side effect of) either
        the call or its expansion."""
        emit(pretty_print_string(lisp_macroexpand(form)) + "\n")
        return NIL

    def lisp_gensym(*base):
        """(gensym ["prefix"]) -- a symbol guaranteed not to collide with
        any name in the program, for writing your own hygienic macros by
        hand (see gensym()'s docstring)."""
        return gensym(str(base[0]) if base else "g")

    def lisp_load(path):
        """(load "path/to/file.lsp") -- read and evaluate every top-level
        form in a file, in this SAME global environment, so its
        definitions become available afterward exactly as if you'd typed
        them yourself. Uses the same run_file() the interpreter's own
        startup init-file loading does (see load_init_file)."""
        run_file(str(path), env)
        return NIL

    env.update({
        "apply": lisp_apply,
        "eval": lisp_eval,
        "macroexpand-1": lisp_macroexpand_1,
        "macroexpand": lisp_macroexpand,
        "print-macroexpansion": lisp_print_macroexpansion,
        "gensym": lisp_gensym,
        "load": lisp_load,
    })

    # ---- structs (see defstruct in eval_special_form) ----
    def make_struct_fn(struct_type, plist):
        values = {}
        items = pairs_to_list(plist)
        for i in range(0, len(items), 2):
            values[items[i]] = items[i + 1]
        return LispStruct(struct_type, values)

    def struct_ref(s, slot_name):
        if not isinstance(s, LispStruct):
            raise LispError("struct-ref: not a struct: %r" % (s,))
        if slot_name not in s.values:
            raise LispError("struct-ref: %s has no slot %s" % (s.struct_type.name, slot_name))
        return s.values[slot_name]

    def struct_set(s, slot_name, value):
        if not isinstance(s, LispStruct):
            raise LispError("struct-set!: not a struct: %r" % (s,))
        if slot_name not in s.values:
            raise LispError("struct-set!: %s has no slot %s" % (s.struct_type.name, slot_name))
        s.values[slot_name] = value
        return NIL

    def lisp_error(*args):
        raise LispError(" ".join(to_display_string(a) for a in args))

    env.update({
        "%make-struct": make_struct_fn,
        "struct-ref": struct_ref,
        "struct-set!": struct_set,
        "struct-type-name": lambda s: s.struct_type.name,
        "error": lisp_error,
    })

    # ---- strings ----
    env.update({
        "string-append": lambda *a: LispString("".join(a)),
        "string-length": lambda s: len(s),
        "substring": lambda s, start, end=None: LispString(s[start:end]),
        "string=?": lambda a, b: a == b,
        "string<?": lambda a, b: a < b,
        "string>?": lambda a, b: a > b,
        "string->number": lambda s: (float(s) if ('.' in s or 'e' in s.lower()) else int(s)),
        "number->string": lambda n: LispString(to_display_string(n)),
        "string->list": lambda s: list_to_pairs(list(s)),
        "list->string": lambda p: LispString("".join(pairs_to_list(p))),
        "string-upcase": lambda s: LispString(s.upper()),
        "string-downcase": lambda s: LispString(s.lower()),
        "string->symbol": lambda s: Symbol(s),
        "symbol->string": lambda s: LispString(str(s)),
        "string": lambda *chars: LispString("".join(chars)),
    })

    # ---- vectors (fixed-size, mutable; holds numbers and/or dates) ----
    def make_vector_fn(*args):
        check_vector_elements(args, "vector")
        return LispVector(list(args))

    def make_vector(n, fill=0):
        check_vector_elements([fill], "make-vector")
        return LispVector([fill] * n)

    def vector_ref(v, i):
        if not isinstance(v, LispVector):
            raise LispError("vector-ref: not a vector: %r" % (v,))
        return v.items[i]

    def vector_set(v, i, x):
        if not isinstance(v, LispVector):
            raise LispError("vector-set!: not a vector: %r" % (v,))
        check_vector_elements([x], "vector-set!")
        v.items[i] = x
        return NIL

    def vector_fill(v, x):
        check_vector_elements([x], "vector-fill!")
        for i in range(len(v.items)):
            v.items[i] = x
        return NIL

    def vector_map(f, v):
        return LispVector([apply_proc(f, [x]) for x in v.items])

    def vector_append(*vs):
        items = []
        for v in vs:
            items.extend(v.items)
        return LispVector(items)

    def list_to_vector(p):
        items = pairs_to_list(p)
        check_vector_elements(items, "list->vector")
        return LispVector(items)

    def vector_iterate(first, count, f):
        """Build a vector of `count` elements: the first is `first`, and
        each following element is (f previous-element). Works for numbers
        or dates, since `f` can be e.g. date-add-days."""
        check_vector_elements([first], "vector-iterate")
        if count < 0:
            raise LispError("vector-iterate: count must not be negative")
        items = []
        current = first
        for i in range(count):
            if i > 0:
                current = apply_proc(f, [current])
                check_vector_elements([current], "vector-iterate")
            items.append(current)
        return LispVector(items)

    def vector_slice(v, start, end=None):
        if not isinstance(v, LispVector):
            raise LispError("vector-slice: not a vector: %r" % (v,))
        return LispVector(v.items[start:end])

    def vector_take(v, n):
        if not isinstance(v, LispVector):
            raise LispError("vector-take: not a vector: %r" % (v,))
        return LispVector(v.items[:n])

    def vector_drop(v, n):
        if not isinstance(v, LispVector):
            raise LispError("vector-drop: not a vector: %r" % (v,))
        return LispVector(v.items[n:])

    def vectors_shuffle(vec_list, seed=None):
        """(vectors-shuffle (list v1 v2 ...) [seed]) -> a Lisp list of new
        vectors, all permuted with the SAME random ordering -- so you can
        shuffle a set of x/y vectors together without losing the
        row-by-row alignment between them, before splitting into a
        training subset and a held-out subset."""
        vecs = pairs_to_list(vec_list)
        if not vecs:
            raise LispError("vectors-shuffle: at least one vector is required")
        n = len(vecs[0].items)
        for v in vecs:
            if not isinstance(v, LispVector):
                raise LispError("vectors-shuffle: every element must be a vector")
            if len(v.items) != n:
                raise LispError("vectors-shuffle: all vectors must be the same length")
        indices = list(range(n))
        rng = random.Random(seed) if seed is not None else random.Random()
        rng.shuffle(indices)
        shuffled = [LispVector([v.items[i] for i in indices]) for v in vecs]
        return list_to_pairs(shuffled)

    _NO_DEFAULT = object()  # sentinel: distinguishes "no default given" from "default given as NIL/0/etc."

    def vectors_map(f, vec_list, default=_NO_DEFAULT):
        """(vectors-map f (list v1 v2 ...) [default]) -> a new vector whose
        J-th element is (f (vector-ref v1 J) (vector-ref v2 J) ... J) -- the
        multi-vector generalization of vector-map (which only takes one
        vector).  The last argument to f is the integer J.

        If the input vectors aren't all the same length:
          - with no `default` argument (the default), stops at the
            length of the SHORTEST input vector -- elements beyond that
            are simply never visited.
          - with a `default` argument, the result runs out to the length
            of the LONGEST input vector, and any vector that's run out of
            real elements contributes `default` in its place for the
            remaining positions.
        """
        vecs = pairs_to_list(vec_list)
        if not vecs:
            raise LispError("vectors-map: at least one vector is required")
        for v in vecs:
            if not isinstance(v, LispVector):
                raise LispError("vectors-map: every element must be a vector")
        lengths = [len(v.items) for v in vecs]

        if default is _NO_DEFAULT:
            n = min(lengths)
            return LispVector([apply_proc(f, [v.items[j] for v in vecs] + [j]) for j in range(n)])

        n = max(lengths)
        result = []
        for j in range(n):
            row = [v.items[j] if j < len(v.items) else default for v in vecs] + [j]
            result.append(apply_proc(f, row))
        return LispVector(result)

    env.update({
        "vector": make_vector_fn,
        "make-vector": make_vector,
        "vector-ref": vector_ref,
        "vector-set!": vector_set,
        "vector-length": lambda v: len(v.items),
        "vector-fill!": vector_fill,
        "vector-copy": lambda v: LispVector(list(v.items)),
        "vector-map": vector_map,
        "vector-append": vector_append,
        "vector->list": lambda v: list_to_pairs(list(v.items)),
        "list->vector": list_to_vector,
        "vector-iterate": vector_iterate,
        "vector-sum": lambda v: sum(v.items),
        "vector-add": lambda a, b: LispVector([x + y for x, y in zip(a.items, b.items)]),
        "vector-sub": lambda a, b: LispVector([x - y for x, y in zip(a.items, b.items)]),
        "vector-scale": lambda v, s: LispVector([x * s for x in v.items]),
        "vector-slice": vector_slice,
        "vector-take": vector_take,
        "vector-drop": vector_drop,
        "vectors-shuffle": vectors_shuffle,
        "vectors-map": vectors_map,
    })

    # ---- dates ----
    env.update({
        "date": date_fn,
        "date-year": date_year,
        "date-month": date_month,
        "date-day": date_day,
        "date->string": date_to_string,
        "string->date": string_to_date,
        "date-add-days": date_add_days,
    })

    # ---- regression models: linear, logistic, and spline; single- or multi-predictor ----
    def model_intercept(m):
        if isinstance(m, LispSplineModel):
            raise LispError("model-intercept: not available for a spline model; use model-report instead")
        return m.intercept

    env.update({
        "linear-regression": linear_regression_fn,
        "logistic-regression": logistic_regression_fn,
        "spline-regression": spline_regression_fn,
        "suggest-knots": suggest_knots_fn,
        "model-report": model_report,
        "model-predict": model_predict,
        "model-evaluate": model_evaluate,
        "model-slope": model_slope,
        "model-coefficients": model_coefficients,
        "model-intercept": model_intercept,
        "model-kind": lambda m: LispString(m.kind),
        "model?": lambda x: _is_model(x),
        "sigmoid": lambda z: sigmoid(z),
    })

    # ---- FRED (Federal Reserve Bank of St. Louis) data, and CSV loading ----
    env.update({
        "fred-series": fred_series,
        "load-csv": load_csv_fn,
    })

    # ---- SQLite ----
    env.update({
        "sqlite-open": sqlite_open_fn,
        "sqlite-close": sqlite_close_fn,
        "sqlite-query": sqlite_query_fn,
        "sqlite-execute": sqlite_execute_fn,
        "sqlite-fetch-row": sqlite_fetch_row_fn,
    })

    # ---- tastytrade (real broker data): futures curves and futures-option chains ----
    env.update({
        "tastytrade-test-connection": tastytrade_test_connection_fn,
        "tastytrade-futures-curve": tastytrade_futures_curve_fn,
        "tastytrade-futures-curve-rows": tastytrade_futures_curve_rows_fn,
        "tastytrade-option-chain": tastytrade_option_chain_fn,
        "tastytrade-curve-fit": tastytrade_curve_fit_fn,
        "tastytrade-leg-carry": tastytrade_leg_carry_fn,
        "tastytrade-products": tastytrade_products_fn,
        "sofr-forward-curve": sofr_forward_curve_fn,
        "sofr-calibration-data": sofr_calibration_data_fn,
        "sofr-bootstrap-curve": sofr_bootstrap_curve_fn,
        "sofr-calibrate-model": sofr_calibrate_model_fn,
        "sofr-simulate-rate-paths": sofr_simulate_rate_paths_fn,
        "sofr-simulate-mortgage-rate-paths": sofr_simulate_mortgage_rate_paths_fn,
    })

    # ---- charting: plot one X vector against one or more Y vectors ----
    # `last_chart` remembers the most recently plotted chart spec, so
    # `save-chart` can render it to a file without needing to be told the
    # data all over again -- this works the same in the GUI and in plain
    # console/batch mode, since it only depends on render_chart_to_file.
    last_chart = {"spec": None}

    def plot_xy(x_vec, y_list):
        y_vecs = pairs_to_list(y_list)
        spec = build_chart_spec(x_vec, y_vecs, labels=None, connect=True,
                                 title="XY Chart", regression_label=None)
        last_chart["spec"] = spec
        plot(spec)
        return NIL

    def plot_xy_regression(x_vec, y_vec, label, kind="linear"):
        label = str(label)
        kind = str(kind)
        spec = build_chart_spec(
            x_vec, [y_vec], labels=[label], connect=False,
            title="%s vs X, with %s regression" % (label, kind),
            regression_label=label, regression_kind=kind)
        last_chart["spec"] = spec
        plot(spec)
        return NIL

    def plot_xy_full(x_vec, y_list, label_list, connect_flag, title, regression_label, regression_kind="linear"):
        y_vecs = pairs_to_list(y_list)
        labels = [str(s) for s in pairs_to_list(label_list)] if label_list is not NIL else None
        if labels is not None and len(labels) != len(y_vecs):
            raise LispError("plot-xy-full: the labels list must match the number of y-vectors")
        reg_label = None if regression_label is False else str(regression_label)
        spec = build_chart_spec(x_vec, y_vecs, labels, is_true(connect_flag),
                                 str(title), reg_label, str(regression_kind))
        last_chart["spec"] = spec
        plot(spec)
        return NIL

    def save_chart_fn(filename, width=8.0, height=6.0, dpi=150.0):
        if last_chart["spec"] is None:
            raise LispError("save-chart: no chart has been plotted yet (call plot-xy, "
                             "plot-xy-regression, or plot-xy-full first)")
        render_chart_to_file(last_chart["spec"], str(filename), float(width), float(height), int(dpi))
        return NIL

    env.update({
        "plot-xy": plot_xy,
        "plot-xy-regression": plot_xy_regression,
        "plot-xy-full": plot_xy_full,
        "save-chart": save_chart_fn,
    })

    # ---- columns (GUI's "Columns" tab / console text table / CSV export) ----
    def format_column_value(v, decimals=None):
        """Render one cell -- either with an explicit decimal-places
        count (decimals, e.g. from a column struct's `decimals` slot --
        see column_engine.lsp), or, when that's None, using the CURRENT
        value of the Lisp-settable *column-number-format* global (a
        Python str.format() spec, e.g. "{:,.0f}" for comma-grouped
        integers -- (set! *column-number-format* "{:,.2f}") changes it
        for every subsequent display-columns call that doesn't specify
        its own per-column decimals). Non-numeric values (dates, etc.)
        fall back to plain display formatting either way."""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return to_display_string(v)
        if decimals is not None:
            fmt = "{:,.%df}" % int(decimals)
        else:
            fmt = str(env.get(Symbol("*column-number-format*"), "{}"))
        try:
            return fmt.format(v)
        except (ValueError, TypeError):
            return to_display_string(v)

    def parse_column_pairs(name_value_pairs):
        """Shared by display-columns and write-columns-csv: each element
        of `name_value_pairs` is either (name . vector) -- a plain cons,
        decimals unspecified -- or (name vector decimals), a 3-element
        list picking a per-column decimal-places count instead of
        relying on the global *column-number-format* (this is the shape
        column_engine.lsp's calculate-all now builds, from each column
        struct's `decimals` slot). Returns a list of (name, items,
        decimals-or-None)."""
        out = []
        for p in pairs_to_list(name_value_pairs):
            name = str(p.car)
            rest = p.cdr
            if isinstance(rest, LispVector):
                out.append((name, rest.items, None))
            elif isinstance(rest, Pair) and isinstance(rest.car, LispVector):
                decimals = rest.cdr.car if isinstance(rest.cdr, Pair) else None
                out.append((name, rest.car.items, decimals))
            else:
                raise LispError(
                    "expected (name . vector) or (name vector decimals), got %r" % (p,))
        return out

    def display_columns_fn(name_value_pairs):
        """(display-columns pairs) -- pairs is a list of (name . vector)
        conses, or (name vector decimals) lists for a per-column decimal-
        places count (see column_engine.lsp's `decimals` slot); each
        becomes one displayed column, headed by name, in the order given,
        with every value rendered through format_column_value.
        Deliberately generic: doesn't know anything about the `column`
        struct some higher-level Lisp library (e.g. a column_engine.lsp-
        style modeling library) may define on top of this -- that mapping
        from a struct instance to a (name . vector) / (name vector
        decimals) entry happens entirely in Lisp. See the `columns`
        callback."""
        data = [(name, [format_column_value(v, decimals) for v in items])
                for name, items, decimals in parse_column_pairs(name_value_pairs)]
        columns(data)
        return NIL

    def write_columns_csv_fn(filename, name_value_pairs):
        """(write-columns-csv filename pairs) -- pairs is the SAME shape
        display-columns takes: a list of (name . vector) conses, or
        (name vector decimals) lists. Writes a CSV file: header row =
        names, one data row per index. Numbers are rounded to `decimals`
        places when given -- plain numeric CSV cells, not comma-grouped
        display strings; this is for feeding a spreadsheet or another
        program, not for on-screen reading (see display-columns for
        that). Rows are padded with an empty cell for any column shorter
        than the longest one. Returns '()."""
        parsed = parse_column_pairs(name_value_pairs)
        n_rows = max((len(items) for _, items, _ in parsed), default=0)
        with open(str(filename), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([name for name, _, _ in parsed])
            for i in range(n_rows):
                row = []
                for _, items, decimals in parsed:
                    if i >= len(items):
                        row.append("")
                        continue
                    v = items[i]
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        row.append(to_display_string(v))
                    elif decimals is not None:
                        d = int(decimals)
                        row.append(int(round(float(v))) if d == 0 else round(float(v), d))
                    else:
                        row.append(v)
                writer.writerow(row)
        return NIL

    env.update({
        "display-columns": display_columns_fn,
        "write-columns-csv": write_columns_csv_fn,
        "*column-number-format*": LispString("{:,.0f}"),
    })


    # ---- type predicates ----
    env.update({
        "number?": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "integer?": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "string?": lambda x: isinstance(x, LispString),
        "symbol?": lambda x: isinstance(x, Symbol),
        "keyword?": lambda x: isinstance(x, Keyword),
        "vector?": lambda x: isinstance(x, LispVector),
        "date?": lambda x: isinstance(x, LispDate),
        "procedure?": lambda x: callable(x) or isinstance(x, Procedure),
        "boolean?": lambda x: isinstance(x, bool),
        "struct?": lambda x: isinstance(x, LispStruct),
        "sqlite-connection?": lambda x: isinstance(x, LispSQLiteConnection),
        "sqlite-cursor?": lambda x: isinstance(x, LispSQLiteCursor),
    })

    # ---- I/O ----
    def lisp_display(x):
        emit(to_display_string(x))
        return NIL

    def lisp_newline():
        emit("\n")
        return NIL

    def lisp_print(x):
        emit(to_display_string(x) + "\n")
        return NIL

    def redirect_output(path, append=False):
        """(redirect-output "path.txt" [append?]) -- send everything
        display/newline/print (and the console/no-GUI default plot
        summary) write from now on to the given file instead of the
        console/GUI log, until (reset-output) is called. Opens in
        overwrite mode by default; pass #t for append. Closes whatever
        file a PRIOR redirect-output call opened first, so redirecting
        twice in a row doesn't leak an open file handle."""
        old_file = output_state["file"]
        if old_file is not None:
            old_file.close()
        f = open(str(path), "a" if is_true(append) else "w")

        def write_to_file(s):
            f.write(s)
            f.flush()  # so output shows up even if the script errors out before reset-output/exit

        output_state["fn"] = write_to_file
        output_state["file"] = f
        return NIL

    def reset_output():
        """(reset-output) -- undo redirect-output: close its file (if
        one is open) and go back to writing to the console/GUI log."""
        old_file = output_state["file"]
        if old_file is not None:
            old_file.close()
        output_state["fn"] = output
        output_state["file"] = None
        return NIL

    env.update({
        "display": lisp_display,
        "newline": lisp_newline,
        "print": lisp_print,
        "redirect-output": redirect_output,
        "reset-output": reset_output,
    })

    # ---- introspection, pretty-printing, and debugging ----
    def lisp_pretty_print(x):
        """(pretty-print x) -- verbose, paren-column-aligned printing of
        ANY value (see pretty_print_string()). A Procedure or Macro is
        shown as its reconstructed, name-free (lambda ...) / (defmacro
        <anonymous> ...) source; everything else is printed as-is."""
        if isinstance(x, Procedure):
            expr = reconstruct_procedure_source(x)
        elif isinstance(x, Macro):
            expr = reconstruct_macro_source(x)
        else:
            expr = x
        emit(pretty_print_string(expr) + "\n")
        return NIL

    def lisp_pretty_print_function_named(name, value):
        if not isinstance(value, Procedure) and name in debug_originals:
            value = debug_originals[name]  # show the real definition even while debug-wrapped
        if not isinstance(value, Procedure):
            raise LispError("pretty-print-function: %r is not a user-defined function" % (name,))
        emit(pretty_print_string(reconstruct_procedure_source(value, name)) + "\n")
        return NIL

    def lisp_pretty_print_macro_named(name, value):
        if not isinstance(value, Macro):
            raise LispError("pretty-print-macro: %r is not a macro" % (name,))
        emit(pretty_print_string(reconstruct_macro_source(value, name)) + "\n")
        return NIL

    def defined_functions():
        """(defined-functions) -- every name currently bound (in the top-
        level environment) to a user-defined Procedure -- i.e. something
        created by `lambda`/`define`, NOT a built-in. There's no separate
        registry to keep in sync: this just filters the live environment,
        so it's always exactly correct, in the order things were first
        defined (a redefinition doesn't move its entry)."""
        return list_to_pairs([name for name in env if isinstance(env[name], Procedure)])

    # The convenience macros bootstrapped below (pretty-print-function,
    # etc.) are technically ordinary Macro instances too, same as
    # anything the user writes with defmacro -- there's no type-level
    # "built-in macro" distinction the way there is for built-in
    # PROCEDURES (those are plain Python callables, so isinstance(...,
    # Procedure) already excludes them for free). Excluded by name here
    # instead, so defined-macros() reflects only what you actually wrote.
    _bootstrap_macro_names = set()

    def defined_macros():
        """(defined-macros) -- every name currently bound to a
        user-defined Macro (excluding this interpreter's own
        pretty-print-function/-macro/debug-function/undebug-function
        convenience macros -- see _bootstrap_macro_names above). Same
        live-filter approach as defined-functions()."""
        return list_to_pairs([
            name for name in env
            if isinstance(env[name], Macro) and name not in _bootstrap_macro_names
        ])

    def bound_variables():
        """(bound-variables) -- every top-level name bound to a plain
        VALUE (not a function, macro, or built-in procedure) -- i.e.
        ordinary `define`d data: numbers, strings, lists, vectors, dates,
        etc. Built-in procedures are excluded because they're plain
        Python callables, same as `callable(x)` already excludes them
        from defined-functions()/defined-macros() implicitly (only
        Procedure/Macro instances count as user-defined there)."""
        return list_to_pairs([
            name for name in env
            if not isinstance(env[name], (Procedure, Macro)) and not callable(env[name])
        ])

    # State for debug-function/undebug-function -- local to this
    # environment (like output_state above), so separate sessions in the
    # same process don't share debug state.
    debug_call_stack = []      # names of debug-function-wrapped calls currently in progress
    debug_originals = {}       # name -> the original Procedure, so undebug-function can restore it

    def debug_function_named(name):
        """(debug-function name) [macro -- see the bootstrap below]:
        wraps the named function so every future call opens a debug REPL
        (debug_repl) BEFORE running the body, in an environment where the
        function's own parameters are already bound to this call's real
        argument values -- inspect or (via set!) change them, then
        (continue) to actually run the body with whatever's in scope at
        that point. Also prints the chain of debug-function-wrapped calls
        currently in progress, as a lightweight "how was this called, and
        from where" trace -- NOT a full backtrace (this interpreter's
        tail-call optimization deliberately discards ordinary call-frame
        history; see the module docstring), just of the functions you've
        explicitly asked to watch.
        """
        proc = env.get(name)
        if not isinstance(proc, Procedure):
            raise LispError("debug-function: %r is not a user-defined function" % (name,))
        debug_originals[name] = proc

        def wrapper(*args):
            debug_call_stack.append(name)
            try:
                new_env = Env(proc.params, list(args), proc.env, rest_param=proc.rest_param,
                              keyword_specs=proc.keyword_specs, default_eval=eval_default)
                arg_strs = ", ".join(to_string(a) for a in args)
                chain = " -> ".join(str(n) for n in debug_call_stack)
                print("--- debug-function: entering %s(%s) ---" % (name, arg_strs))
                print("    call chain: %s" % chain)
                print("    arguments are bound in this scope -- inspect/set! them, then (continue)")
                debug_repl(new_env, label=str(name))
                return eval_body(proc.body, new_env)
            finally:
                debug_call_stack.pop()

        env[name] = wrapper
        return NIL

    def undebug_function_named(name):
        """(undebug-function name) [macro]: restore the original,
        un-wrapped definition debug-function saved before wrapping it.
        Does nothing if `name` was never debug-function-wrapped."""
        if name in debug_originals:
            env[name] = debug_originals.pop(name)
        return NIL

    env.update({
        "pretty-print": lisp_pretty_print,
        "pretty-print-function-named": lisp_pretty_print_function_named,
        "pretty-print-macro-named": lisp_pretty_print_macro_named,
        "defined-functions": defined_functions,
        "defined-macros": defined_macros,
        "bound-variables": bound_variables,
        "debug-function-named": debug_function_named,
        "undebug-function-named": undebug_function_named,
    })

    # Thin macros so callers can write the NAME directly (e.g.
    # `(pretty-print-function my-func)`) instead of quoting it -- built
    # out of ordinary defmacro/quasiquote, the same as any user macro
    # would be, rather than needing special evaluator support.
    for _bootstrap_src in (
        "(defmacro pretty-print-function (name) `(pretty-print-function-named ',name ,name))",
        "(defmacro pretty-print-macro (name) `(pretty-print-macro-named ',name ,name))",
        "(defmacro debug-function (name) `(debug-function-named ',name))",
        "(defmacro undebug-function (name) `(undebug-function-named ',name))",
    ):
        for _bootstrap_expr in parse(_bootstrap_src):
            seval(_bootstrap_expr, env)
            _bootstrap_macro_names.add(_bootstrap_expr.cdr.car)  # (defmacro NAME ...) -> NAME

    return env


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------

def to_display_string(x):
    """Render a value the way `display` would (strings without quotes)."""
    if x is True:
        return "#t"
    if x is False:
        return "#f"
    if x is NIL:
        return "()"
    if isinstance(x, LispString):
        return x
    if isinstance(x, (Pair, LispVector, LispDate, LispModel, LispSplineModel, LispStruct)):
        return to_string(x)
    return str(x)


def to_string(x):
    """Render a value the way the REPL would print it (strings quoted).
    Note: iterative rather than recursive, so very long lists print fine."""
    if x is True:
        return "#t"
    if x is False:
        return "#f"
    if x is NIL:
        return "()"
    if isinstance(x, LispString):
        return '"%s"' % x
    if isinstance(x, LispDate):
        return x.date.isoformat()
    if isinstance(x, LispSplineModel):
        total_knots = sum(len(s.knots) for s in x.predictor_specs if s.mode == "spline")
        n_categorical = sum(1 for s in x.predictor_specs if s.mode == "categorical")
        if n_categorical:
            return "#<%s-model predictors=%d knots=%d categorical=%d>" % (
                x.kind, x.k, total_knots, n_categorical)
        return "#<%s-model predictors=%d knots=%d>" % (x.kind, x.k, total_knots)
    if isinstance(x, LispModel):
        if len(x.coefficients) == 1:
            return "#<%s-model slope=%.6g intercept=%.6g>" % (x.kind, x.coefficients[0], x.intercept)
        coeffs = ", ".join("%.6g" % c for c in x.coefficients)
        return "#<%s-model coefficients=(%s) intercept=%.6g>" % (x.kind, coeffs, x.intercept)
    if isinstance(x, LispVector):
        return "#(" + " ".join(to_string(item) for item in x.items) + ")"
    if isinstance(x, LispStruct):
        parts = ["%s %s" % (Keyword(":" + slot_name), to_string(x.values.get(slot_name)))
                 for slot_name, _ in x.struct_type.slots]
        return "#S(%s %s)" % (x.struct_type.name, " ".join(parts)) if parts else "#S(%s)" % (x.struct_type.name,)
    if isinstance(x, Pair):
        parts = []
        p = x
        while isinstance(p, Pair):
            parts.append(to_string(p.car))
            p = p.cdr
        if p is NIL:
            return "(" + " ".join(parts) + ")"
        return "(" + " ".join(parts) + " . " + to_string(p) + ")"
    return str(x)


def pretty_print_string(expr):
    """Render expr (any Lisp value or expression -- a Pair/list, vector,
    or atom) as a deliberately VERBOSE, multi-line string: every list
    element goes on its own line, and a list's closing parenthesis is
    printed ALONE on its own line, directly below the COLUMN of its
    matching opening parenthesis. This isn't meant to be attractive for
    everyday reading -- to_string()/to_display_string() already do that
    -- it's meant to make a mismatched or misplaced parenthesis
    impossible to miss: scan straight down any closing paren's column and
    you can see exactly which opening paren it closes, and whether
    that's the one you meant.

    Also used (via reconstruct_procedure_source() / reconstruct_macro_source())
    to display a Procedure's or Macro's definition. That's what makes
    `pretty-print-function` possible: a Procedure/Macro stores its
    already-PARSED parameter list and body (the same Pairs/Symbols/
    literals seval() walks), which is enough to rebuild a semantically
    faithful, canonically-formatted (define ...) / (lambda ...) /
    (defmacro ...) form -- but NOT a byte-exact copy of what was
    originally typed, since the reader discards comments and doesn't
    remember the original whitespace/formatting.

    Plain Python recursion, like eval_quasiquote (not the seval()
    trampoline) -- safe here because recursion depth is bounded by how
    deeply NESTED the EXPRESSION is (fixed by the source code), never by
    runtime data size.
    """
    lines = ['']

    def col():
        return len(lines[-1])

    def emit_text(s):
        lines[-1] += s

    def break_line(indent):
        lines.append(' ' * indent)

    def write(x):
        if isinstance(x, Pair):
            open_col = col()
            emit_text('(')
            p = x
            first = True
            while isinstance(p, Pair):
                if not first:
                    break_line(open_col + 1)
                write(p.car)
                first = False
                p = p.cdr
            if p is not NIL:
                break_line(open_col + 1)
                emit_text('. ')
                write(p)
            break_line(open_col)
            emit_text(')')
        elif isinstance(x, LispVector):
            open_col = col()
            emit_text('#(')
            first = True
            for item in x.items:
                if not first:
                    break_line(open_col + 2)
                write(item)
                first = False
            break_line(open_col + 1)  # align under the '(' of '#(', not the '#'
            emit_text(')')
        else:
            emit_text(to_string(x))

    write(expr)
    return "\n".join(lines)


def _param_spec_from(params, rest_param, keyword_specs=()):
    """Rebuild the SOURCE-SYNTAX parameter spec (proper list, dotted
    list, bare symbol, or &key list) that parse_params() would have
    parsed INTO (params, rest_param, keyword_specs) -- the exact inverse
    of that function. Used by reconstruct_procedure_source()/
    reconstruct_macro_source()."""
    if keyword_specs:
        key_items = [Symbol("&key")]
        for name, default_expr in keyword_specs:
            key_items.append(Pair(name, Pair(default_expr, NIL)) if default_expr is not None else name)
        return list_to_pairs(list(params) + key_items)
    if rest_param is None:
        return list_to_pairs(params)
    if not params:
        return rest_param
    spec = rest_param
    for p in reversed(params):
        spec = Pair(p, spec)
    return spec


def reconstruct_procedure_source(proc, name=None):
    """Rebuild the (lambda (params...) body...) -- or, if `name` is
    given, (define (name params...) body...) -- source form for a
    Procedure. See pretty_print_string()'s docstring for exactly what
    "rebuild" does and doesn't preserve."""
    param_spec = _param_spec_from(proc.params, proc.rest_param, proc.keyword_specs)
    body = list_to_pairs(proc.body)
    if name is not None:
        return Pair(Symbol("define"), Pair(Pair(name, param_spec), body))
    return Pair(Symbol("lambda"), Pair(param_spec, body))


def reconstruct_macro_source(macro, name=None):
    """Rebuild the (defmacro name (params...) body...) source form for a
    Macro (name defaults to a placeholder if not given, since a Macro
    value on its own doesn't carry the name it may be bound under)."""
    param_spec = _param_spec_from(macro.params, macro.rest_param, macro.keyword_specs)
    body = list_to_pairs(macro.body)
    return Pair(Symbol("defmacro"),
                Pair(name if name is not None else Symbol("<anonymous>"),
                     Pair(param_spec, body)))


def debug_repl(env, label="debug"):
    """A nested REPL used by the `breakpoint` special form and
    `debug-function`: evaluates whatever the user types directly in
    `env` -- the ACTUAL lexical environment active at the point
    execution paused (e.g. a paused function's own parameters are
    variables in this env, inspectable AND, via set!, modifiable, exactly
    as they exist at that point in the running program). Type
    `(continue)` (or `(exit)`, or press Ctrl-D) to resume normal
    execution from where it paused.

    CONSOLE/BATCH MODE ONLY: this reads from the real console via
    input(), the same as the top-level REPL. Triggering a breakpoint from
    the GUI will try to read from whatever stdin the GUI process has
    (usually none, or the terminal it was launched from) rather than
    opening any kind of dialog in the GUI window itself -- there's no
    GUI-integrated debugger here, just this console one.
    """
    print("--- %s: entering debug REPL (type (continue) or press Ctrl-D to resume) ---" % label)
    buffer = ""
    while True:
        try:
            line = input("  ... " if buffer else "%s> " % label)
        except EOFError:
            print()
            break
        buffer += line + "\n"
        if buffer.count("(") <= buffer.count(")"):
            resume = False
            try:
                for expr in parse(buffer):
                    if isinstance(expr, Pair) and expr.car in (Symbol("continue"), Symbol("exit")):
                        resume = True
                        break
                    result = seval(expr, env)
                    print(to_string(result))
            except LispError as e:
                print("Error:", e)
            except Exception as e:
                print("Error:", e)
            buffer = ""
            if resume:
                break
    print("--- %s: resuming ---" % label)


# ---------------------------------------------------------------------------
# Console REPL / batch runner (no PyQt6 needed)
# ---------------------------------------------------------------------------

def run_file(path, env):
    with open(path) as f:
        text = f.read()
    for expr in parse(text):
        seval(expr, env)


# Loaded automatically into every fresh environment at startup (batch
# mode, the console REPL, and the GUI) -- see load_init_file(). Defaults
# to init.lsp next to this script, so it's easy to find; override with
# the LISP_INIT_FILE environment variable if you'd rather keep it
# somewhere else (e.g. a dotfile in your home directory).
DEFAULT_INIT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init.lsp")


def load_init_file(env, path=None):
    """Load the interpreter's init file into env, if it exists -- called
    once per fresh environment, right after make_global_env(), before any
    user script/REPL input/GUI interaction. Silently does nothing if the
    file isn't there (a fresh checkout with no init.lsp behaves exactly
    as if this function didn't exist), the same way a missing .bashrc
    doesn't stop a shell from starting. A LispError while loading it IS
    reported (to stderr) but doesn't prevent startup -- same reasoning:
    a broken init file shouldn't lock you out of the interpreter you'd
    need to open it and fix it.
    """
    path = path or os.environ.get("LISP_INIT_FILE", DEFAULT_INIT_FILE)
    if not path or not os.path.exists(path):
        return
    try:
        run_file(path, env)
    except LispError as e:
        sys.stderr.write("warning: error loading init file %r: %s\n" % (path, e))


def repl(env):
    print("Simple Lisp interpreter. Type (exit) to quit.")
    buffer = ""
    while True:
        try:
            line = input("  ... " if buffer else "lisp> ")
        except EOFError:
            print()
            break
        buffer += line + "\n"
        if buffer.count("(") <= buffer.count(")"):
            try:
                for expr in parse(buffer):
                    if isinstance(expr, Pair) and expr.car == Symbol("exit"):
                        return
                    result = seval(expr, env)
                    print(to_string(result))
            except LispError as e:
                print("Error:", e)
            except Exception as e:
                print("Error:", e)
            buffer = ""


# ---------------------------------------------------------------------------
# PyQt6 GUI
# ---------------------------------------------------------------------------
#
# PyQt6 and matplotlib are only imported here, and only used if the GUI is
# actually launched, so the interpreter above works standalone even on a
# machine without either installed.

try:
    from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
    from PyQt6.QtGui import QTextCursor, QFontDatabase
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPlainTextEdit, QPushButton, QTextEdit, QTableView, QSplitter,
        QTabWidget, QFileDialog, QMessageBox,
    )
    import matplotlib
    matplotlib.use("QtAgg")  # auto-detects the installed Qt binding (PyQt6 here)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    _PYQT_AVAILABLE = _MATPLOTLIB_AVAILABLE  # the GUI needs both PyQt6 and matplotlib
except ImportError:
    _PYQT_AVAILABLE = False


if _PYQT_AVAILABLE:

    class ChartCanvas(FigureCanvasQTAgg):
        """Renders a chart spec (see build_chart_spec): one X vector against
        one or more Y vectors, each with its own marker symbol and
        optionally connected by line segments, plus an optional dashed
        regression line/curve. Drawing itself is shared with the headless
        save-chart path via draw_chart_on_axes()."""

        def __init__(self):
            figure = Figure(figsize=(6, 5))
            super().__init__(figure)
            self.ax = figure.add_subplot(111)

        def plot(self, spec):
            draw_chart_on_axes(self.figure, self.ax, spec)
            self.draw()

    class VectorTableModel(QAbstractTableModel):
        """Displays a set of named number vectors as columns: one column
        per vector, headed by its variable name, one row per index."""

        def __init__(self):
            super().__init__()
            self.names = []    # column headers, in display order
            self.columns = []  # parallel list of plain Python number lists

        def set_vectors(self, name_value_pairs):
            """Replace the full set of displayed vectors.
            name_value_pairs: list of (name, list-of-numbers) tuples."""
            self.beginResetModel()
            self.names = [name for name, _ in name_value_pairs]
            self.columns = [values for _, values in name_value_pairs]
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return max((len(col) for col in self.columns), default=0)

        def columnCount(self, parent=QModelIndex()):
            return len(self.columns)

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            if role != Qt.ItemDataRole.DisplayRole:
                return None
            col = self.columns[index.column()]
            row = index.row()
            if row < len(col):
                # Values arriving here (via display-columns) are already
                # rendered strings -- see format_column_value() and the
                # *column-number-format* global -- so this is just a
                # pass-through; right-aligning them (above) in the
                # monospace font the GUI sets on this table (see
                # LispMainWindow.__init__) is what actually makes a
                # column of numbers line up on its ones place.
                return str(col[row])
            return ""

        def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
            if role != Qt.ItemDataRole.DisplayRole:
                return None
            if orientation == Qt.Orientation.Horizontal:
                return self.names[section]
            return str(section)

    class InputEdit(QPlainTextEdit):
        """A plain-text box that runs its contents on Ctrl+Enter, while
        letting a plain Enter insert a newline (so multi-line definitions
        are easy to type)."""

        def __init__(self, on_submit):
            super().__init__()
            self._on_submit = on_submit

        def keyPressEvent(self, event):
            is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            if is_enter and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self._on_submit()
                return
            super().keyPressEvent(event)

    WELCOME_MESSAGE = (
        "Simple Lisp, with vectors/dates, XY charts, and FRED data access.\n"
        "Try, for example:\n"
        "  (define prices (vector 10 20 30 40 50))\n"
        "  (define doubled (vector-map (lambda (x) (* x 2)) prices))\n"
        "  (define powers-of-two (vector-iterate 1 8 (lambda (x) (* x 2))))\n"
        "  (define squares #(1 4 9 16 25))\n"
        "  (define home-type (vector 0 1 0 1 1))  ; 0=own, 1=rent\n"
        "  (plot-xy prices (list doubled squares))\n"
        "  (plot-xy-regression prices squares \"Squares\")             ; linear\n"
        "  (define m (logistic-regression prices (vector 0 1 0 1 1)))  ; y in [0,1]\n"
        "  (display (model-report m))\n"
        "  (plot-xy-regression prices (vector 0 1 0 1 1) \"Y\" \"logistic\")\n"
        "  ; multiple predictors: pass a list of x-vectors instead of one\n"
        "  (define m2 (linear-regression (list prices squares) doubled))\n"
        "  (display (model-coefficients m2))\n"
        "  ; train/test split: fit on a subset, evaluate on the rest\n"
        "  (define n-train (floor (* (vector-length prices) 0.7)))\n"
        "  (define train-x (vector-take prices n-train))\n"
        "  (define test-x (vector-drop prices n-train))\n"
        "  (define m3 (linear-regression train-x (vector-take squares n-train)))\n"
        "  (display (model-evaluate m3 test-x (vector-drop squares n-train)))\n"
        "  (define d (fred-series \"GDP\" \"YOUR_FRED_API_KEY\"))\n"
        "  (plot-xy (car d) (list (cdr d)))\n"
        "  (save-chart \"chart.png\")   ; or use the Save Chart... button\n"
        "  ; spline-regression: a bit of non-linearity via hinge functions\n"
        "  (define m4 (spline-regression prices squares 3))  ; up to 3 auto knots\n"
        "  (display (model-report m4))\n"
        "  ; explicit knots (e.g. bracketing a critical range) instead of auto:\n"
        "  (define m5 (spline-regression prices squares (list 25 35)))\n"
        "  ; or let suggest-knots propose locations from the data itself:\n"
        "  (define knots (suggest-knots prices squares 2 2))\n"
        "  (define m5b (spline-regression prices squares knots))\n"
        "  ; different max knots per predictor: pass a list instead of one number\n"
        "  (define m6 (spline-regression (list prices squares) doubled (list 1 0)))\n"
        "  ; a 2-3-valued predictor (e.g. home-type: 0=own/1=rent) -> 'categorical\n"
        "  (define m7 (spline-regression (list prices home-type) doubled\n"
        "                                 (list 2 (quote categorical))))\n"
        "  (define m8 (spline-regression (vector 10 20 30 40 50 60 70 80 90 100 110 120)\n"
        "                                 (vector 0 0 1 0 1 1 0 1 1 1 0 1) 2 #t))\n"
        "  ; load-csv returns (cons headers vectors); e.g.:\n"
        "  ; (define d2 (load-csv \"data.csv\"))  (define cols (cdr d2))\n"
        "  ; tastytrade real broker data (needs a credentials JSON file --\n"
        "  ; see tasty_api/README.md for one-time OAuth setup):\n"
        "  (define creds \"tastytrade_credentials.json\")\n"
        "  (define curve (tastytrade-futures-curve creds \"CL\" 12))\n"
        "  (plot-xy (car curve) (list (cdr curve)))\n"
        "  (define chain (tastytrade-option-chain creds \"CL\" 3 10 #f))\n"
        "  (display (length chain))  ; #f above skips the slower IV stream\n"
        "  ; equity option chains work the same way -- any symbol not\n"
        "  ; starting with \"/\" and not a futures short code is fetched\n"
        "  ; as an equity chain, no translation needed:\n"
        "  (define aapl-chain (tastytrade-option-chain creds \"AAPL\" 2 10 #f))\n"
        "  ; rich/cheap curve analysis (fetch once, re-analyze free of charge\n"
        "  ; with different assumptions -- these two are pure, no networking):\n"
        "  (define rows (tastytrade-futures-curve-rows creds \"CL\" 12))\n"
        "  (define fit (tastytrade-curve-fit rows 0.75))\n"
        "  (define legs (tastytrade-leg-carry rows 4.25 3.0 1.0))\n"
        "  ; structs + keyword args (see column_engine.lsp for a full\n"
        "  ; mortgage-amortization example built on these):\n"
        "  (defstruct point x y (label \"\"))\n"
        "  (define p (make-point :x 1 :y 2))\n"
        "  (display (list (point-x p) (point-y p) (point? p)))\n"
        "  (display-columns (list (cons \"prices\" prices) (cons \"squares\" squares)))\n"
        "display-columns populates the Columns tab; plot-xy... calls draw\n"
        "into the Chart tab.\n"
        "Press Ctrl+Enter, or click Run, to evaluate.\n\n"
    )

    class LispMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Simple Lisp \u2014 vectors, charts, and FRED data")
            self.resize(1150, 620)

            self.env = make_global_env(
                output=self._write_output, plot=self._on_plot, columns=self._on_columns)
            load_init_file(self.env)

            central = QWidget()
            self.setCentralWidget(central)
            outer_layout = QVBoxLayout(central)

            input_row = QHBoxLayout()
            self.input_edit = InputEdit(self._on_run)
            self.input_edit.setPlaceholderText(
                "Enter one or more Lisp expressions, then press Ctrl+Enter or click Run...")
            self.input_edit.setFixedHeight(90)
            input_row.addWidget(self.input_edit, 1)

            run_button = QPushButton("Run (Ctrl+Enter)")
            run_button.clicked.connect(self._on_run)
            input_row.addWidget(run_button)

            outer_layout.addLayout(input_row)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            outer_layout.addWidget(splitter, 1)

            self.output_view = QTextEdit()
            self.output_view.setReadOnly(True)
            splitter.addWidget(self.output_view)

            self.tabs = QTabWidget()
            splitter.addWidget(self.tabs)

            self.table_model = VectorTableModel()
            self.table_view = QTableView()
            self.table_view.setModel(self.table_model)
            # Fixed-width font so a column of right-aligned numbers (see
            # VectorTableModel.data()'s TextAlignmentRole) lines up
            # vertically on its ones place, not just left-to-right.
            self.table_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            self.tabs.addTab(self.table_view, "Columns")

            chart_tab = QWidget()
            chart_layout = QVBoxLayout(chart_tab)
            chart_layout.setContentsMargins(0, 0, 0, 0)
            self.chart_canvas = ChartCanvas()
            chart_layout.addWidget(self.chart_canvas, 1)
            save_chart_button = QPushButton("Save Chart...")
            save_chart_button.clicked.connect(self._on_save_chart)
            chart_layout.addWidget(save_chart_button)
            self.tabs.addTab(chart_tab, "Chart")

            self.last_chart_spec = None
            splitter.setSizes([500, 650])

            self._append_text(WELCOME_MESSAGE)

        def _write_output(self, text):
            """Called directly by the Lisp `display` / `newline` / `print`
            builtins -- this is the only bit of "wiring" between the
            interpreter and the GUI."""
            self._append_text(text)

        def _on_plot(self, spec):
            """Called directly by the Lisp `plot-xy...` builtins with a
            plain-data chart spec (see build_chart_spec)."""
            self.last_chart_spec = spec
            self.chart_canvas.plot(spec)
            self.tabs.setCurrentIndex(1)

        def _on_columns(self, name_value_pairs):
            """Called directly by the Lisp `display-columns` builtin --
            the ONLY way the Columns tab is populated (there's no more
            automatic scan of top-level vector-valued variables; see the
            module docstring)."""
            self.table_model.set_vectors(name_value_pairs)
            self.tabs.setCurrentIndex(0)

        def _on_save_chart(self):
            if self.last_chart_spec is None:
                QMessageBox.information(
                    self, "No chart yet", "Plot a chart first, e.g. with plot-xy.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Chart", "chart.png",
                "PNG Image (*.png);;PDF Document (*.pdf);;SVG Image (*.svg);;All Files (*)")
            if not path:
                return
            try:
                render_chart_to_file(self.last_chart_spec, path)
                self._append_text("Chart saved to %s\n\n" % path)
            except LispError as e:
                QMessageBox.warning(self, "Save failed", str(e))

        def _append_text(self, text):
            self.output_view.moveCursor(QTextCursor.MoveOperation.End)
            self.output_view.insertPlainText(text)
            self.output_view.moveCursor(QTextCursor.MoveOperation.End)

        def _on_run(self):
            source = self.input_edit.toPlainText().strip()
            if not source:
                return
            self._append_text("lisp> " + source + "\n")
            try:
                result = NIL
                for expr in parse(source):
                    result = seval(expr, self.env)
                self._append_text("=> " + to_string(result) + "\n\n")
            except LispError as e:
                self._append_text("Error: %s\n\n" % e)
            except Exception as e:
                self._append_text("Error: %s\n\n" % e)
            self.input_edit.clear()


def launch_gui():
    if not _PYQT_AVAILABLE:
        print("PyQt6 and matplotlib are required for the GUI:\n\n    pip install PyQt6 matplotlib\n")
        print("Falling back to the console REPL.\n")
        env = make_global_env()
        load_init_file(env)
        repl(env)
        return
    app = QApplication(sys.argv)
    window = LispMainWindow()
    window.show()
    sys.exit(app.exec())


def main():
    if len(sys.argv) > 1:
        # run a script file from the console, no GUI needed.
        env = make_global_env()
        load_init_file(env)
        if (sys.argv[1] == "-"): # or just run interactively with no GUI
            repl(env)
        else:
            run_file(sys.argv[1], env)
    else:
        # Default: launch the PyQt6 GUI.
        launch_gui()


if __name__ == "__main__":
    main()
