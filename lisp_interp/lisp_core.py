"""The core of the Lisp interpreter: the data types, the reader (text ->
Lisp data), the environment, the evaluator, and the printer (Lisp data ->
text). Everything else -- the built-in procedures, regression, charts,
SQLite, FRED, tastytrade, the GUI -- is built on top of this module, and
this module imports none of them.

Sections, in order:
  Data types        Symbol, LispString, Keyword, Pair, LispVector, LispDate,
                    LispHashTable, LispStructType/LispStruct, Procedure,
                    Macro, LispError
  Reader            tokenize(), parse(), read_from(), atom()
  Environment       Env: name -> value bindings, with lexical scoping
  Call tracing      (verbose n) logging, and the Lisp-level stack traces
                    shown when an error escapes
  Evaluator         seval() and the special forms
  Helpers           check_numbers(), check_vector_elements(), numeric_value()
  Printer           to_string(), to_display_string(), pretty_print_string()
  Debugging         debug_repl() -- used by (breakpoint) and debug-function
  Running files     run_file()

HOW THE EVALUATOR WORKS: seval() does NOT use Python function recursion to
walk the Lisp expression tree. Instead it drives an explicit stack of
"control frames" (a plain Python list) in a loop, so deeply recursive Lisp
programs -- even non-tail-recursive ones -- are limited only by available
memory, not by Python's own recursion limit.

TAIL CALLS get more than that: a procedure call in TAIL POSITION -- the
last thing a function body does, including through if/let/let*/cond/and/
or/begin/dolist -- pushes the callee's body directly onto the SAME control
stack, with no leftover "resume the caller here" frame underneath. So a
tail-recursive loop runs in CONSTANT stack space: e.g.
`(define (count-down n) (if (= n 0) 'done (count-down (- n 1))))` uses the
same small, fixed amount of stack whether n is 10 or 10,000,000. A MACRO
call gets the same treatment: its expansion is pushed as a plain EVAL
frame rather than evaluated right away.

CAVEAT: that guarantee only covers ordinary `(f arg...)` calls. `(apply f
args)`, `(eval expr)`, `(load "file.lsp")`, a callback passed to `map`/
`filter`/`reduce`/`vector-map`/`vectors-map`, and a macro transformer's own
body while it is building its expansion all call back into seval() with an
ordinary Python function call (see apply_proc()), so those paths are still
bounded by Python's recursion limit. In practice this rarely matters.
"""

import os
import sys
import datetime

import numpy as np    # LispVector's backing store -- see its class docstring


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
    #(1 2 3.5) or a vector of LispDate values.

    `items` is backed by a numpy array (not a Python list) specifically
    for memory: a Python list of N float64 objects costs ~32 bytes per
    element (an 8-byte pointer in the list plus a 24-byte float object),
    while a packed numpy array costs as little as 1-8 bytes per element
    depending on dtype (see the *_DTYPE class attributes below) -- this
    matters once vectors reach into the millions of elements (e.g. a
    large loan-level dataset pulled in via sqlite-query, or a big
    Monte-Carlo path array): a couple of GB of Python-list vectors would
    otherwise balloon toward a couple dozen. numpy also lets a handful
    of builtins below (vector-add/vector-sub/vector-scale, and the
    regression fitting code in fit_linear/fit_logistic) do real
    elementwise/matrix math in optimized C instead of a Python-level
    loop, which is separately a speed win for those specific operations.

    DTYPE POLICY -- change these three lines to retune memory vs.
    precision for every vector in the interpreter at once; nothing else
    needs to change. Defaults chosen for residential mortgage loan-level
    data: individual balances well under $1,000,000 (float32 carries
    ~7 significant decimal digits, comfortably enough for a sub-$1M
    dollar figure or a rate/ratio that only ever needs 3-4 significant
    figures), and the many 0/1 flag columns (delinquency, modification,
    etc.) common in that kind of data, which fit in a single byte each.
    Bump these back up (e.g. FLOAT_DTYPE = np.float64) if a future
    dataset needs more precision than that -- e.g. dollar figures in the
    billions, where float32's ~7 digits stop covering the cents place.

    Two things every one of this class's callers has to get right, as a
    direct consequence of using numpy underneath:
      1. A numeric-dtype array's elements come back from indexing/
         iteration as numpy SCALAR objects (e.g. np.float32/np.int32),
         not Python's own float/int -- and unlike np.float64 (which
         happens to subclass Python's float), NONE of the narrower
         dtypes above subclass anything this interpreter's own
         isinstance(x, (int, float))-style checks would recognize, so
         relying on subclassing would be fragile even in the one case
         where it happens to work. Every place a single element crosses
         back out to "the rest of the interpreter" as a first-class Lisp
         value goes through _lisp_scalar() (below) to convert it to a
         genuine Python int/float first -- note this also means a value
         only ever *loses* precision once, at the moment it's WRITTEN
         into a vector; every read and every downstream computation
         after that (regression fitting included, since it works from
         plain Python lists produced by .tolist()) happens at full
         Python float (i.e. C double / numpy float64) precision, same
         as always. Bulk extraction (reading a WHOLE vector out as a
         plain Python list) uses `.tolist()` instead, which does the
         equivalent conversion for every element at once, in one fast
         C-level pass.
      2. Unlike a Python list, slicing a numpy array (v.items[a:b]) or
         array-based math (v.items + w.items) produces a VIEW or a fresh
         array respectively, not automatically the same
         always-copy-on-construction behavior list(items) gave for
         free. To keep every LispVector fully independent once
         constructed -- exactly the old contract, since these are
         MUTABLE vectors and nothing should silently alias another
         vector's storage -- the constructor below always makes an
         independent copy of whatever it's given: a fast native
         .copy() when handed an already-built numpy array (the normal
         case for a slice or an arithmetic result), or a dtype-inferring
         _infer_array(list(items)) when handed a plain Python
         list/iterable of Lisp values (the normal case for new vectors
         built by a list comprehension elsewhere in this file)."""

    FLOAT_DTYPE = np.float32     # any vector containing a non-integer number
    INT_DTYPE = np.int32         # an all-integer vector, not all 0/1
    BOOL_INT_DTYPE = np.int8     # an all-integer vector of ONLY 0 and/or 1

    def __init__(self, items):
        if isinstance(items, np.ndarray):
            self.items = items.copy()
        else:
            self.items = LispVector._infer_array(list(items))

    @staticmethod
    def _infer_array(items):
        """Build the numpy array for a NEW vector from a plain Python
        list of Lisp values (numbers and/or dates) -- not from an
        already-built numpy array; __init__ handles that case
        separately, above, with a plain .copy(). Picks the narrowest
        dtype the FLOAT_DTYPE/INT_DTYPE/BOOL_INT_DTYPE policy above
        allows, preserving Lisp's own int-vs-float distinction (a float
        value that happens to be a whole number, e.g. 5.0, still makes
        the vector a FLOAT_DTYPE vector -- it does NOT get treated as
        the integer 5); falls back to dtype=object -- exactly as
        memory-hungry as the old list-based representation, but no less
        correct -- for anything that isn't a plain, homogeneous-enough
        number: an empty vector, a LispDate anywhere, a mix of numbers
        AND dates, an integer too big for INT_DTYPE to hold (Python ints
        are arbitrary-precision; INT_DTYPE isn't), or (see read_from's
        "#(" case) unevaluated vector-literal syntax that can hold
        arbitrary Symbols/Pairs."""
        if items and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in items):
            if all(isinstance(v, int) for v in items):
                dtype = (LispVector.BOOL_INT_DTYPE if all(v in (0, 1) for v in items)
                         else LispVector.INT_DTYPE)
            else:
                dtype = LispVector.FLOAT_DTYPE
            if all(_value_fits_dtype(v, dtype) for v in items):
                return np.array(items, dtype=dtype)
        return np.array(items, dtype=object)

    def __eq__(self, other):
        return isinstance(other, LispVector) and np.array_equal(self.items, other.items)

    def __repr__(self):
        return to_string(self)


def _lisp_scalar(x):
    """Convert one element pulled out of a LispVector's numpy-array
    `items` back into a genuine Python value, the way the rest of the
    interpreter (and any isinstance(x, int)-style check in it) expects.
    A numeric-dtype array hands back a numpy scalar (np.float32/
    np.int32/np.int8) on indexing -- .item() converts that to the
    equivalent native Python float/int. An object-dtype array (holding
    LispDate, or anything else that isn't a plain number) already hands
    back the real underlying Python object directly, with no numpy
    wrapper to strip, so those pass through unchanged."""
    return x.item() if isinstance(x, np.generic) else x


def _narrow_vector_result(arr):
    """After a numpy elementwise operation combining two LispVector
    `items` arrays (vector-add/vector-sub/vector-scale, below), clamp a
    float64 RESULT back down to LispVector.FLOAT_DTYPE. numpy's own
    type-promotion rules upgrade e.g. an int32 array combined with a
    float32 array -- or with a plain Python float scalar, as
    vector-scale's `s` usually is -- to float64, even though every
    individual value involved already fit in float32; left alone, that
    would silently defeat the point of running these on a large vector.
    Integer-dtype results are left alone -- this policy's int8/int32
    tiers never overshoot each other, only mixing in a float does."""
    return arr.astype(LispVector.FLOAT_DTYPE) if arr.dtype == np.float64 else arr


def _value_fits_dtype(x, dtype):
    """Would writing plain Lisp number `x` into a numpy array of this
    dtype preserve it EXACTLY? Checked explicitly, rather than just
    trying the assignment and catching an exception, because numpy
    doesn't always raise on a bad fit: writing a float into an
    integer-dtype array SILENTLY TRUNCATES instead of erroring (e.g.
    arr[i] = 0.5 on an int8 array quietly becomes 0) -- exactly the kind
    of silent corruption this has to prevent, not just the loud
    OverflowError case (an int too big for the dtype's range, e.g. 1000
    into an int8 array, which numpy DOES raise on)."""
    if dtype == object:
        return True
    if np.issubdtype(dtype, np.integer):
        if not isinstance(x, int):
            return False   # a float (even a whole-number one, e.g. 5.0)
                            # would silently truncate -- see docstring
        info = np.iinfo(dtype)
        return info.min <= x <= info.max
    return isinstance(x, (int, float))   # a float dtype: any number fits
                                          # (float32 may lose PRECISION for
                                          # a very large value, same as
                                          # for any other float-vector
                                          # element -- not new corruption)


def _vector_widen_for(v, x):
    """Before writing `x` into LispVector `v`'s numpy-array `items`
    (vector-set!/vector-fill!, below): widen `items` to a dtype that can
    actually hold `x`, if its current one can't (a no-op in the
    overwhelmingly common case where it already can). This matters more
    than it might look: column_engine.lsp's calculate-all pre-allocates
    a column's series via (make-vector n initial_value) -- often 0 or
    0.0 -- then fills it in row by row via vector-set! as each row gets
    computed, so the array's dtype gets picked from the INITIAL value
    alone, long before the real range of values it'll end up holding is
    known -- e.g. a column that starts out looking like a 0/1 flag
    (BOOL_INT_DTYPE), until some row's computed value turns out to
    genuinely need more range.

    Re-infers a dtype the same way a brand-new vector would -- a fresh
    _infer_array call over this vector's EXISTING contents (read back
    out via .tolist(), so it sees plain Python values, not numpy
    scalars) plus the new value -- rather than jumping straight to
    dtype=object, so e.g. a 0/1-flag-looking column widens to a plain
    int vector for a bigger int, not all the way to a memory-hungry
    object array. Falls back to dtype=object only if even that freshly
    re-inferred dtype still can't hold `x` (in practice: `x` is a
    LispDate mixed into an established numeric vector -- _infer_array's
    own number-or-date homogeneity rule sends that straight to
    dtype=object already -- or a plain int too big for even INT_DTYPE,
    e.g. a huge ID or a nanosecond timestamp)."""
    if _value_fits_dtype(x, v.items.dtype):
        return
    new_dtype = LispVector._infer_array(v.items.tolist() + [x]).dtype
    if not _value_fits_dtype(x, new_dtype):
        new_dtype = object
    v.items = v.items.astype(new_dtype)


class LispDate:
    """A simple calendar date, e.g. (date 2020 1 15). Wraps a Python
    datetime.date so charts can format it nicely on an axis."""

    def __init__(self, year, month, day):
        self.date = datetime.date(year, month, day)

    def __eq__(self, other):
        return isinstance(other, LispDate) and self.date == other.date

    def __hash__(self):
        # A date is immutable (its .date is never reassigned after
        # construction -- date-add-days, etc. build a NEW LispDate
        # rather than mutating one in place), so unlike Pair/LispVector/
        # LispStruct -- genuinely mutable, deliberately left unhashable,
        # the same rule Python's own dict/set keys follow -- there's no
        # risk of a date's hash changing after it's used as a
        # hash-table key. Delegates to the wrapped datetime.date's own
        # hash, which is already correct and consistent with __eq__.
        return hash(self.date)

    def __lt__(self, other):
        return isinstance(other, LispDate) and self.date < other.date

    def __repr__(self):
        return self.date.isoformat()


class LispHashTable:
    """A mutable hash table (make-hash-table / hash-table-*, below).
    Thin wrapper around a Python dict -- keys must be hashable Lisp
    values: numbers, strings, symbols, keywords, dates (all immutable,
    or -- Symbol/LispString/Keyword -- backed by Python's own str,
    already hashable). Lists, vectors, and structs are all deliberately
    left unhashable (see e.g. Pair's docstring) since they're mutable;
    the hash_table_set!/-ref builtins below catch Python's TypeError for
    an unhashable key and re-raise a clear LispError instead of leaking
    it raw."""

    def __init__(self):
        self.table = {}

    def __repr__(self):
        return "#<hash-table %d entr%s>" % (len(self.table), "y" if len(self.table) == 1 else "ies")


class LispStructType:
    """The record type created by (defstruct name slot...) or
    (defstruct (name (:include parent)) slot...) -- see
    eval_special_form()'s "defstruct" case. Just metadata: the type's
    name, its parent LispStructType (or None for a plain, non-including
    defstruct), and its full ordered slot list (Symbol slot_name,
    default_expr_or_None) -- inherited slots first, in the PARENT's own
    order (a child slot with the same name as an inherited one replaces
    that slot's default in place rather than duplicating it, exactly CL's
    :include behavior), then the child's own new slots, in declared
    order. Slot order is preserved everywhere a struct of this type is
    printed or its constructor's keyword arguments are bound.

    `slots` is deliberately the single, already-flattened list any
    consumer (the constructor, accessors, to_string, ...) needs -- none
    of them have to know or care that some of it came from a parent;
    only defstruct itself (building this list, below) and is_a
    (checking substructure-of relationships for accessor/predicate
    sharing) look at `parent` directly."""

    def __init__(self, name, own_slots, parent=None):
        self.name = name              # Symbol
        self.parent = parent          # LispStructType or None
        self.own_slots = own_slots    # this type's own slot declarations, unmerged
        self.slots = LispStructType._merge_slots(parent, own_slots)

    @staticmethod
    def _merge_slots(parent, own_slots):
        if parent is None:
            return list(own_slots)
        own_by_name = dict(own_slots)
        merged = [(name, own_by_name.get(name, default)) for name, default in parent.slots]
        inherited_names = set(name for name, _ in parent.slots)
        merged.extend((name, default) for name, default in own_slots if name not in inherited_names)
        return merged

    def is_a(self, other_type):
        """True if this type IS other_type, or (:include-)descends from
        it -- i.e. an instance of this type can stand in anywhere an
        instance of other_type is expected: other_type's accessors,
        setters, and predicate all accept it, exactly CL's struct
        substructure relationship."""
        t = self
        while t is not None:
            if t is other_type:
                return True
            t = t.parent
        return False

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
    handling (which does the actual binding at call time).

    name (a Symbol, or None if anonymous): only used to label this
    procedure in call traces and stack traces (see the "Call tracing"
    section, below) -- never affects behavior. `define` sets it, and so
    does defining an anonymous lambda's value under a name
    ((define f (lambda ...))) if it doesn't have one yet; the
    make-<struct> constructors defstruct builds are named too.

    is_scope: True only for the throwaway procedure `let`/`let*`/`dolist`
    desugar into ((lambda (x...) body...) v...). It's an implementation
    detail of those forms -- a variable scope, not a real call -- so it is
    left out of call traces and stack traces."""

    def __init__(self, params, body, env, rest_param=None, keyword_specs=None,
                 name=None, is_scope=False):
        self.params = params      # list of Symbol FIXED parameter names
        self.rest_param = rest_param
        self.keyword_specs = keyword_specs or []  # see parse_params()
        self.body = body          # list of body expressions
        self.env = env            # environment in which it was defined
        self.name = name
        self.is_scope = is_scope

    def __repr__(self):
        return "#<procedure %s>" % (self.name,) if self.name is not None else "#<procedure>"


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
    collects is unevaluated expressions rather than values.

    name: the macro's name, used only to label its transformer in stack
    traces (see Procedure.name)."""

    def __init__(self, params, body, env, rest_param=None, keyword_specs=None, name=None):
        self.params = params
        self.rest_param = rest_param
        self.keyword_specs = keyword_specs or []  # see parse_params()
        self.body = body
        self.env = env
        self.name = name

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
                    escapes = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
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
    stays shallow even for deeply recursive Lisp programs.)

    trace_emit: only ever set on a GLOBAL environment (by make_global_env):
    the function verbose-mode trace lines are written with, so they land
    wherever that environment's display output does. See _trace_write()."""

    trace_emit = None

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
# Call tracing and Lisp-level stack traces
# ---------------------------------------------------------------------------
#
# Two debugging aids, both built on one small idea: every call of a
# user-defined procedure (or a macro transformer) leaves a ('CALL', proc,
# args, tails) frame on the evaluator's control stack -- see seval() -- so
# "what procedure are we in, and what was it called with?" is always
# answerable by looking at the stack.
#
#   * VERBOSE MODE -- (verbose n) -- logs calls as they happen:
#         0  off (the default)
#         1  each call, by procedure NAME
#         2  each call with its ARGUMENTS, and each return with its VALUE
#         3  everything in 2, plus every macro expansion
#     Lines are indented by call depth. A call in tail position is marked
#     `>>` instead of `>` (see below). Output goes wherever display output
#     goes (console, GUI log, Jupyter cell, a redirect-output file).
#
#   * STACK TRACES -- when an error escapes, seval() copies the CALL
#     frames it finds into the exception (exc.lisp_trace), so wherever the
#     error is finally reported (REPL, batch mode, GUI, Jupyter) it can be
#     shown with the chain of calls that led to it -- see
#     format_lisp_traceback(). `(backtrace)` prints the same thing for
#     the CURRENT call chain, on demand, without an error.
#
# TAIL CALLS AND THE STACK: a call in tail position REPLACES the caller's
# CALL frame instead of adding one under it (that is exactly what makes a
# tail call constant-space -- see the module docstring), so a stack trace,
# like one from any tail-call-optimizing Lisp, doesn't list a caller that
# tail-called its way out. The replacing frame counts how many calls it
# absorbed, and traces show it as "[+N tail calls]" so the missing callers
# are accounted for. let/let*/dolist scopes (Procedure.is_scope) are not
# calls and get no frame.

VERBOSE_OFF, VERBOSE_CALLS, VERBOSE_ARGS, VERBOSE_MACROS = 0, 1, 2, 3
_verbose_level = 0      # current verbosity; change ONLY via set_verbose_level()
_call_depth = 0         # nesting depth of traced calls, for indentation

TRACE_MAX_FRAMES = 40   # a longer stack trace keeps the outermost 10 and innermost 30
_BRIEF_MAX_ITEMS = 6    # list/vector elements shown before "..."
_BRIEF_MAX_DEPTH = 3    # nesting shown before "(...)"
_BRIEF_MAX_STRING = 40  # string characters shown before "..."


def set_verbose_level(level):
    """Set the verbosity -- 0/1/2/3, or #f/#t for 0/1 -- and return the
    PREVIOUS level (so callers can restore it). Restarts the indentation,
    since depth is only meaningful counted from when tracing began."""
    global _verbose_level, _call_depth
    if level is True:
        level = VERBOSE_CALLS
    elif level is False:
        level = VERBOSE_OFF
    if isinstance(level, bool) or not isinstance(level, int) or not VERBOSE_OFF <= level <= VERBOSE_MACROS:
        raise LispError("verbose: level must be 0, 1, 2, 3, #f, or #t, got %s" % (to_string(level),))
    previous = _verbose_level
    _verbose_level = level
    _call_depth = 0
    return previous


def get_verbose_level():
    """The current verbosity level (0-3) -- see set_verbose_level()."""
    return _verbose_level


def _initial_verbose_level():
    """The LISP_VERBOSE environment variable, if it holds 0-3."""
    text = os.environ.get("LISP_VERBOSE", "").strip()
    return int(text) if text in ("0", "1", "2", "3") else 0


_verbose_level = _initial_verbose_level()


def _brief(x, depth=0):
    """A short, bounded rendering of any value for trace lines. Unlike
    to_string(), the work done is limited no matter how big x is -- a
    million-element vector or a long list is summarized, never walked in
    full -- so tracing a call that receives huge data stays cheap."""
    if x is True:
        return "#t"
    if x is False:
        return "#f"
    if x is NIL:
        return "()"
    if isinstance(x, LispString):
        text = str(x)
        return '"%s"' % (text if len(text) <= _BRIEF_MAX_STRING else text[:_BRIEF_MAX_STRING] + "...")
    if isinstance(x, Pair):
        if depth >= _BRIEF_MAX_DEPTH:
            return "(...)"
        parts, p = [], x
        while isinstance(p, Pair) and len(parts) < _BRIEF_MAX_ITEMS:
            parts.append(_brief(p.car, depth + 1))
            p = p.cdr
        if isinstance(p, Pair):
            parts.append("...")
        elif p is not NIL:
            parts.append(". " + _brief(p, depth + 1))
        return "(" + " ".join(parts) + ")"
    if isinstance(x, LispVector):
        n = len(x.items)
        if n <= _BRIEF_MAX_ITEMS:
            return "#(" + " ".join(to_string(item) for item in x.items) + ")"
        return "#(" + " ".join(to_string(item) for item in x.items[:3]) + " ... n=%d)" % n
    if isinstance(x, LispStruct):
        if depth >= _BRIEF_MAX_DEPTH:
            return "#S(%s ...)" % (x.struct_type.name,)
        slots = x.struct_type.slots
        parts = ["%s %s" % (Keyword(":" + str(name)), _brief(x.values.get(name), depth + 1))
                 for name, _ in slots[:4]]
        if len(slots) > 4:
            parts.append("...")
        return "#S(%s%s)" % (x.struct_type.name, "".join(" " + part for part in parts))
    if isinstance(x, (Procedure, Macro)):
        return repr(x)
    if isinstance(x, LispDate):
        return to_string(x)
    text = str(x)
    return text if len(text) <= 60 else text[:57] + "..."


def _proc_name(proc):
    name = getattr(proc, "name", None)
    if name is not None:
        return str(name)
    return "<macro>" if isinstance(proc, Macro) else "<lambda>"


def _call_text(proc, args, with_args=True):
    """`(name arg...)` -- or just `name` -- for one call. A macro's
    "arguments" are its unevaluated source expressions."""
    if not with_args:
        return _proc_name(proc)
    return "(" + " ".join([_proc_name(proc)] + [_brief(a) for a in args]) + ")"


def _trace_write(env, text):
    """Write one trace line to `env`'s own display channel (the same
    place display/print output goes -- console, GUI log, Jupyter cell,
    redirect-output file), found on the global environment's trace_emit;
    stderr if there isn't one."""
    while env is not None:
        emit = env.trace_emit
        if emit is not None:
            emit(text + "\n")
            return
        env = env.outer
    sys.stderr.write(text + "\n")


def _trace_enter(proc, args, is_tail):
    """Log the start of a call; a non-tail call also deepens the nesting.
    A tail call takes over the frame of the call it replaces, so it is
    indented at THAT call's depth (one level up from the current
    nesting), the same depth the eventual return line will have."""
    global _call_depth
    indent = "  " * (max(0, _call_depth - 1) if is_tail else _call_depth)
    _trace_write(proc.env, "%s%s %s" % (
        indent, ">>" if is_tail else ">",
        _call_text(proc, args, _verbose_level >= VERBOSE_ARGS)))
    if not is_tail:
        _call_depth += 1


def _trace_leave(proc, args, tails, value):
    """A call returned `value`: undo its nesting and, at level 2+, log it."""
    global _call_depth
    _call_depth = max(0, _call_depth - 1)
    if _verbose_level >= VERBOSE_ARGS:
        note = "  [after %d tail call%s]" % (tails, "" if tails == 1 else "s") if tails else ""
        _trace_write(proc.env, "%s< %s => %s%s" % (
            "  " * _call_depth, _call_text(proc, args), _brief(value), note))


def _trace_macro_expansion(macro, form, expansion):
    _trace_write(macro.env, "%s~ %s => %s" % ("  " * _call_depth, _brief(form), _brief(expansion)))


def _stack_calls(control_stack):
    """Every call in progress on a control stack, innermost first, as
    (proc, args, tails, rejected) -- rejected is always False here; see
    _record_rejected_call."""
    return [(f[1], f[2], f[3], False) for f in reversed(control_stack) if f[0] == 'CALL' or f[0] == 'MCALL']


_active_stacks = []     # the control stack of every seval() currently running, outermost first


def _current_calls():
    """Every call in progress right now, across ALL running evaluators
    (a callback run by map, a macro transformer, eval, a breakpoint's own
    debug REPL, ... each run in a nested seval with a stack of its own),
    innermost first. What `(backtrace)` shows."""
    calls = []
    for stack in reversed(_active_stacks):
        calls.extend(_stack_calls(stack))
    return calls


def _record_rejected_call(exc, proc, args):
    """`proc` was called with `args` but binding them to its parameters
    failed (wrong argument count, unknown keyword, ...) -- so the call
    never got a frame of its own. Put it on exc's trace anyway, as its
    innermost entry: the error is about THAT call, and the trace should
    name the procedure that was called wrongly, not just its caller."""
    trace = getattr(exc, "lisp_trace", None)
    if trace is None:
        try:
            trace = exc.lisp_trace = []
        except AttributeError:
            return
    trace.append((proc, args, 0, True))


def _record_lisp_trace(exc, control_stack):
    """Called as an error unwinds through a seval(): append that
    evaluator's calls in progress to exc.lisp_trace. Nested evaluators
    (a callback run by map, a macro transformer, eval, ...) each add
    theirs as the error passes back out through them, so the finished list
    runs innermost-first across all of them."""
    trace = getattr(exc, "lisp_trace", None)
    if trace is None:
        try:
            trace = exc.lisp_trace = []
        except AttributeError:      # an exception type that won't take attributes
            return
    trace.extend(_stack_calls(control_stack))


def _trace_line(proc, args, tails, rejected=False):
    text = _call_text(proc, args)
    if rejected:
        text += "  [arguments rejected]"
    elif isinstance(proc, Macro):
        text += "  [macro transformer]"
    if tails:
        text += "  [+%d tail call%s]" % (tails, "" if tails == 1 else "s")
    return "  " + text


def format_call_stack(calls, title="Lisp traceback (most recent call last):"):
    """Render calls (as _stack_calls / exc.lisp_trace give them, innermost
    first) Python-style: outermost call first, so the most recent call
    ends up right next to the error message printed after it. A very long
    stack keeps its outermost and innermost frames and elides the middle.
    Returns "" for an empty stack."""
    if not calls:
        return ""
    ordered = list(reversed(calls))
    if len(ordered) > TRACE_MAX_FRAMES:
        head, tail = ordered[:10], ordered[-(TRACE_MAX_FRAMES - 10):]
        hidden = len(ordered) - len(head) - len(tail)
        lines = [_trace_line(*c) for c in head]
        lines.append("  ... %d more calls ..." % hidden)
        lines.extend(_trace_line(*c) for c in tail)
    else:
        lines = [_trace_line(*c) for c in ordered]
    return title + "\n" + "\n".join(lines) + "\n"


def format_lisp_traceback(exc):
    """The Lisp call chain that led to `exc`, as text ("" if there was
    none) -- see the section comment above."""
    return format_call_stack(getattr(exc, "lisp_trace", None) or [])


def format_error_report(exc):
    """A complete, human-readable report of an error: the call chain (if
    any), then `Error: message`. What the REPL, batch mode, and the GUI
    show."""
    return format_lisp_traceback(exc) + "Error: %s\n" % (exc,)


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
#   ('WITH_STRUCT', body, env)      -- bind a just-evaluated struct's slots
#                                      as variables, then run `body`
#   ('CALL', proc, args, tails)     -- marks a user procedure's body: which
#                                      procedure, its arguments, and how
#                                      many tail calls it replaced. Popped
#                                      on return; replaced by a tail call
#                                      (see "Call tracing", above)
#   ('MCALL', macro, exprs, 0)      -- the same for a macro transformer's
#                                      body; never replaced, never logged
#
# Frames are pushed onto control_stack (a Python list) and popped off in
# LIFO order, exactly mirroring what Python's own call stack would have
# done -- except it is a plain list under our control, so its size is
# limited only by memory, not by sys.getrecursionlimit().

SPECIAL_FORMS = {
    "quote", "if", "define", "set!", "lambda",
    "begin", "let", "let*", "cond", "and", "or", "dolist",
    "defmacro", "quasiquote", "breakpoint", "defstruct", "catch-error",
    "with-struct", "%scope-lambda", "backtrace",
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
       => ((lambda (x1 x2 ...) body...) v1 v2 ...)
       where that lambda is really the internal %scope-lambda form: it
       builds the very same Procedure `lambda` does, just flagged
       is_scope so call traces don't mistake a `let` for a call."""
    bindings = pairs_to_list(args.car)
    body = args.cdr  # already a Pair-list, reused as the lambda's body
    names = [b.car for b in bindings]
    value_exprs = [b.cdr.car for b in bindings]
    lambda_expr = Pair(Symbol("%scope-lambda"), Pair(list_to_pairs(names), body))
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
        lambda_expr = Pair(Symbol("%scope-lambda"), Pair(NIL, body))
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
        # .tolist(), not a bare iteration over expr.items: a vector
        # literal with no unquotes in it (unusual, but legal) is
        # otherwise already a compact numeric-dtype array by the time
        # quasiquote sees it, and iterating that directly would hand
        # each element to eval_quasiquote (and then back into
        # LispVector(...), below) as a numpy scalar rather than a
        # plain Python int/float -- which _infer_array's own
        # isinstance(v, (int, float)) check doesn't recognize, so the
        # rebuilt vector would fall back to a dtype=object array
        # instead of picking a compact dtype again.
        return LispVector([eval_quasiquote(x, env, depth) for x in expr.items.tolist()])

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
    try:
        new_env = Env(macro.params, arg_exprs, macro.env, rest_param=macro.rest_param,
                      keyword_specs=macro.keyword_specs, default_eval=raw_default)
    except Exception as exc:
        _record_rejected_call(exc, macro, arg_exprs)
        raise
    return eval_body(macro.body, new_env, call=(macro, arg_exprs))


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
        env[name] = Macro(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs, name=name)
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
            env[name] = Procedure(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs,
                                  name=name)
            value_stack.append(name)
        else:
            name = target
            control_stack.append(('DEFINE', name, env))
            control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "set!":
        name = args.car
        control_stack.append(('SET', name, env))
        control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "lambda" or op == "%scope-lambda":
        # params may be fixed (a b), dotted/variadic (a b . rest), or a
        # single bare symbol (fully variadic) -- see parse_params().
        # %scope-lambda is what let/let*/dolist desugar into (see
        # desugar_let): the very same Procedure, flagged is_scope so call
        # traces don't count it as a call.
        fixed, rest, keyword_specs = parse_params(args.car)
        body = pairs_to_list(args.cdr)
        value_stack.append(Procedure(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs,
                                     is_scope=(op == "%scope-lambda")))

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
        # (defstruct name slot...), or, to inherit from an existing
        # struct type, (defstruct (name (:include parent)) slot...) --
        # exactly CL's defstruct name-and-options / :include syntax
        # (only :include is supported here; CL has several other
        # options this doesn't need). Each slot is a bare symbol
        # (default value '()) or (slot-name default-expr), exactly CL's
        # slot-spec syntax (e.g. (visible #t)). Never evaluated itself,
        # like defmacro's params. Builds four things and binds them into
        # env, exactly as `define` binds a single name:
        #   make-<name>   -- an ordinary &key Procedure (see
        #                     parse_params()/Env.__init__) whose body calls
        #                     the %make-struct builtin with the struct
        #                     type (spliced in directly as a literal --
        #                     any non-Pair/non-Symbol value is self-
        #                     evaluating, see seval()'s EVAL case) and a
        #                     plist built from the bound slot params
        #                     (ALL of them -- inherited and own alike;
        #                     LispStructType.slots is already the flat,
        #                     merged list, see its own docstring). So
        #                     struct construction is just an application
        #                     of the general keyword-argument machinery,
        #                     not a separate code path.
        #   <name>-<slot>       -- accessor, one per slot in the FULL
        #                          (inherited + own) slot list
        #   <name>-<slot>-set!  -- setter (mutable slots; matches this
        #                          codebase's vector-set!-style naming,
        #                          not CL's setf)
        #   <name>?             -- predicate
        # Every one of the four accepts not just an instance of exactly
        # this type, but also an instance of any type that (:include)s
        # it, directly or transitively (LispStructType.is_a) -- so a
        # parent's own accessor works on a child instance too, matching
        # CL's struct substructure relationship: (parent-x child-instance)
        # and (child-x child-instance) read the very same slot. A NEWLY
        # child-only slot's accessor, naturally, still only accepts an
        # instance of the child (or a further descendant) -- a plain
        # parent instance was never given a value for it.
        name_form = args.car
        parent_type = None
        own_slots = []
        if isinstance(name_form, Pair):
            type_name = name_form.car
            opt_p = name_form.cdr
            while isinstance(opt_p, Pair):
                opt = opt_p.car
                if (isinstance(opt, Pair) and isinstance(opt.car, Keyword)
                        and opt.car == ":include" and isinstance(opt.cdr, Pair)):
                    parent_name = opt.cdr.car
                    parent_type = env.lookup_or_none(Symbol("%%struct-type-%s" % parent_name))
                    if parent_type is None:
                        raise LispError(
                            "defstruct: :include parent %r is not a known struct type "
                            "(define it with defstruct first)" % (parent_name,))
                    # (:include parent (slot new-default) ...) -- CL lets you
                    # override an inherited slot's default right here, as an
                    # alternative to just redeclaring that slot name in the
                    # main slot list below (which works exactly the same way,
                    # via LispStructType._merge_slots -- both end up in
                    # own_slots, and a name in there always overrides that
                    # inherited slot's default in place rather than
                    # duplicating it).
                    override_p = opt.cdr.cdr
                    while isinstance(override_p, Pair):
                        override_spec = override_p.car
                        if not isinstance(override_spec, Pair):
                            raise LispError(
                                "defstruct: malformed :include slot override %r "
                                "(expected (slot-name default-expr))" % (override_spec,))
                        own_slots.append((override_spec.car, override_spec.cdr.car))
                        override_p = override_p.cdr
                else:
                    raise LispError("defstruct: unsupported option in %r (only :include is supported)"
                                     % (name_form,))
                opt_p = opt_p.cdr
        else:
            type_name = name_form

        p = args.cdr
        while isinstance(p, Pair):
            spec = p.car
            if isinstance(spec, Pair):
                own_slots.append((spec.car, spec.cdr.car))
            else:
                own_slots.append((spec, None))
            p = p.cdr
        struct_type = LispStructType(type_name, own_slots, parent=parent_type)
        slots = struct_type.slots
        env[Symbol("%%struct-type-%s" % type_name)] = struct_type  # for a later defstruct's :include

        plist_items = []
        for slot_name, _ in slots:
            plist_items.append(list_to_pairs([Symbol("quote"), slot_name]))
            plist_items.append(slot_name)
        list_call = Pair(Symbol("list"), list_to_pairs(plist_items))
        make_body = list_to_pairs([Symbol("%make-struct"), struct_type, list_call])
        env[Symbol("make-%s" % type_name)] = Procedure(
            [], [make_body], env, rest_param=None, keyword_specs=slots,
            name=Symbol("make-%s" % type_name))

        def make_accessor(slot_name):
            def accessor(s):
                if not (isinstance(s, LispStruct) and s.struct_type.is_a(struct_type)):
                    raise LispError("%s-%s: not a %s: %r" % (type_name, slot_name, type_name, s))
                return s.values[slot_name]
            return accessor

        def make_setter(slot_name):
            def setter(s, v):
                if not (isinstance(s, LispStruct) and s.struct_type.is_a(struct_type)):
                    raise LispError("%s-%s-set!: not a %s: %r" % (type_name, slot_name, type_name, s))
                s.values[slot_name] = v
                return NIL
            return setter

        for slot_name, _ in slots:
            env[Symbol("%s-%s" % (type_name, slot_name))] = make_accessor(slot_name)
            env[Symbol("%s-%s-set!" % (type_name, slot_name))] = make_setter(slot_name)

        env[Symbol("%s?" % type_name)] = (
            lambda s, t=struct_type: isinstance(s, LispStruct) and s.struct_type.is_a(t))

        def copier(s, t=struct_type):
            # A shallow copy (a new LispStruct, a fresh values dict, but
            # the slot VALUES themselves aren't themselves copied --
            # matching CL's copy-<name>) -- accepts a descendant
            # instance too (same is_a rule as every other accessor
            # here), and copies using the INSTANCE's own actual type
            # (s.struct_type), not necessarily `t` itself, so
            # copy-point on a point-3d instance correctly produces
            # another point-3d, not a point missing its z.
            if not (isinstance(s, LispStruct) and s.struct_type.is_a(t)):
                raise LispError("copy-%s: not a %s: %r" % (type_name, type_name, s))
            return LispStruct(s.struct_type, dict(s.values))
        env[Symbol("copy-%s" % type_name)] = copier

        value_stack.append(type_name)

    elif op == "backtrace":
        # (backtrace) -- print the CURRENT chain of procedure calls, oldest
        # first, exactly as an error's traceback would (see
        # format_call_stack), without needing an error. Covers every running
        # evaluator (see _current_calls), so it works inside a callback or a
        # breakpoint too. (A special form only so it needs no operator
        # lookup -- and so a user procedure named `backtrace` can't hide it.)
        text = format_call_stack(_current_calls(), "Lisp call stack (most recent call last):")
        _trace_write(env, (text or "Lisp call stack: (empty -- not inside any procedure call)\n").rstrip("\n"))
        value_stack.append(NIL)

    elif op == "with-struct":
        # (with-struct struct-expr body...) -- evaluate struct-expr ONCE;
        # it must yield a struct instance of ANY defstruct type. Then bind
        # EVERY one of that instance's slot names, as a plain variable,
        # to the slot's current value -- in a fresh child scope, exactly
        # as `let` would -- and run body... there (implicit begin, like
        # let's), returning the last body value.
        #
        # A special form rather than a defmacro-defined macro, for the same
        # reason `breakpoint` is one: the names to bind depend on the
        # struct's RUNTIME VALUE (its type's slot list), which a macro
        # transformer can never see -- it only gets the call site's
        # unevaluated source (`p`, `(make-point ...)`, whatever), and runs
        # in its own defining environment rather than the caller's, so
        # it couldn't even evaluate that source to peek at the value when
        # the struct lives in a local variable. Here the struct is
        # evaluated normally in the caller's env (pushed as an ordinary
        # EVAL frame), and the WITH_STRUCT frame, in seval(), does the
        # binding once its value is on the value stack.
        if not isinstance(args, Pair):
            raise LispError("with-struct: expected (with-struct struct-expr body...)")
        control_stack.append(('WITH_STRUCT', pairs_to_list(args.cdr), env))
        control_stack.append(('EVAL', args.car, env))

    elif op == "catch-error":
        # (catch-error protected-expr (var) handler-body...) -- evaluate
        # protected-expr; if it raises ANY exception (this interpreter's
        # own LispError, or one of the handful of builtins documented as
        # raising a raw Python exception instead -- e.g. sqrt's
        # ValueError for a negative argument, vector-ref's out-of-range
        # IndexError), bind `var` to its message (a string) in a fresh
        # child scope and evaluate handler-body there instead (implicit
        # begin, like dolist's body), whose value becomes catch-error's
        # own. If protected-expr succeeds, its value is returned
        # directly and handler-body never runs. Deliberately catches
        # Python's broad `Exception` rather than just LispError, since
        # from Lisp code's perspective both kinds are just "something
        # went wrong in there" -- but NOT the handful of exception types
        # Python itself doesn't derive from Exception (KeyboardInterrupt,
        # SystemExit, RecursionError, MemoryError, ...), which keep
        # propagating unchanged, same as if this weren't here.
        #
        # Needs a real Python try/except boundary, which nothing else in
        # this trampoline-based evaluator has -- control_stack frames
        # can't "catch" an exception raised while a LATER frame runs, so
        # this calls seval() directly (a nested, non-tail call), exactly
        # the same pattern the eval/apply/load builtins already use to
        # run Lisp code from inside Python code. One real consequence: a
        # tail call made from inside protected-expr is tail-optimized
        # only up to the boundary of THIS nested seval() call, not all
        # the way out through catch-error itself -- the same limitation
        # already true of a callback invoked from map/filter/vector-map.
        protected_expr = args.car
        var_name = args.cdr.car.car
        handler_body = pairs_to_list(args.cdr.cdr)
        try:
            result = seval(protected_expr, env)
        except Exception as e:
            handler_env = Env(outer=env)
            handler_env[var_name] = LispString(str(e))
            result = eval_body(handler_body, handler_env)
        value_stack.append(result)

    else:
        raise LispError("unknown special form: %s" % op)


def seval(expr, env, call=None):
    """Evaluate a Lisp expression in an environment, using an explicit
    stack machine rather than Python recursion.

    call (optional): (procedure_or_macro, args) -- what is being run by
    this evaluation, when it isn't just a bare expression: apply_proc()
    (a callback run by map/filter/...) and expand_macro() pass it so the
    procedure or macro transformer gets a call frame of its own, exactly
    as one called from Lisp code does, and so appears in stack traces and
    verbose-mode traces. See "Call tracing" above.

    If an error escapes, the calls in progress on this evaluator's stack
    are recorded on the exception (exc.lisp_trace) on its way out."""
    global _call_depth
    control_stack = [('EVAL', expr, env)]
    value_stack = []
    entry_depth = _call_depth
    if call is not None:
        proc, args = call
        if isinstance(proc, Macro):
            control_stack.insert(0, ('MCALL', proc, args, 0))
        else:
            control_stack.insert(0, ('CALL', proc, args, 0))
            if _verbose_level:
                _trace_enter(proc, args, False)
    _active_stacks.append(control_stack)
    try:
        return _run_eval_loop(control_stack, value_stack)
    except Exception as exc:
        _record_lisp_trace(exc, control_stack)
        _call_depth = entry_depth
        raise
    finally:
        _active_stacks.pop()


def _run_eval_loop(control_stack, value_stack):
    """The evaluator proper -- see seval(), its only caller."""
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
                    if _verbose_level >= VERBOSE_MACROS:
                        _trace_macro_expansion(macro, x, expansion)
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
                try:
                    new_env = Env(proc.params, arg_values, proc.env, rest_param=proc.rest_param,
                                  keyword_specs=proc.keyword_specs, default_eval=eval_default)
                except Exception as exc:
                    if not proc.is_scope:
                        _record_rejected_call(exc, proc, arg_values)
                    raise
                if not proc.is_scope:
                    # Leave a CALL frame under the body, naming this call for
                    # stack traces (see "Call tracing" above). If the top of
                    # the stack is already a CALL frame, nothing else was
                    # waiting on the body's value: this is a TAIL call, so
                    # the new frame REPLACES that one -- keeping tail calls
                    # constant-space -- and just counts the call it absorbed.
                    tails = 0
                    if control_stack and control_stack[-1][0] == 'CALL':
                        tails = control_stack.pop()[3] + 1
                        if _verbose_level:
                            _trace_enter(proc, arg_values, True)
                    elif _verbose_level:
                        _trace_enter(proc, arg_values, False)
                    control_stack.append(('CALL', proc, arg_values, tails))
                push_sequence(proc.body, new_env, control_stack, value_stack)
            elif callable(proc):
                value_stack.append(proc(*arg_values))
            else:
                raise LispError("in tag APPLY: not a procedure: %r" % (proc,))

        elif tag == 'CALL':
            # A procedure's body just finished; its value is on top of the
            # value stack. (Only a normal return gets here: a tail call
            # replaced this frame instead of ever popping it.)
            if _verbose_level:
                _trace_leave(frame[1], frame[2], frame[3], value_stack[-1])

        elif tag == 'MCALL':
            pass    # a macro transformer finished; nothing to log or unwind

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
            value = value_stack.pop()
            if isinstance(value, Procedure) and value.name is None and not value.is_scope:
                value.name = name       # (define f (lambda ...)) -- f labels it in traces
            def_env[name] = value
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

        elif tag == 'WITH_STRUCT':
            _, body, outer_env = frame
            s = value_stack.pop()
            if not isinstance(s, LispStruct):
                raise LispError("with-struct: not a struct: %r" % (s,))
            # The instance's own (flattened, inherited-slots-included)
            # type decides which names get bound -- so this works for any
            # struct, including a subtype instance seen through a parent.
            struct_env = Env(outer=outer_env)
            for slot_name, _default in s.struct_type.slots:
                struct_env[slot_name] = s.values[slot_name]
            # Same tail-call treatment as let's body: the last expression
            # is pushed as a plain EVAL frame, nothing left to resume.
            push_sequence(body, struct_env, control_stack, value_stack)

        else:
            raise LispError("unknown control frame: %r" % (tag,))

    return value_stack.pop()


def eval_body(body, env, call=None):
    """Evaluate a list of expressions in env, returning the last value.
    Used by apply_proc to call back into a user-defined Procedure from a
    built-in higher-order function like `map` or `vector-map`. `call` is
    seval()'s: what is being run, for stack traces."""
    return seval(Pair(Symbol("begin"), list_to_pairs(body)), env, call)


def apply_proc(proc, args):
    """Call a procedure -- either a user-defined Procedure (closure) or a
    built-in Python callable -- with a list of already-evaluated args.
    Used by higher-order builtins (map, filter, reduce, apply, vector-map)."""
    if isinstance(proc, Procedure):
        try:
            new_env = Env(proc.params, args, proc.env, rest_param=proc.rest_param,
                          keyword_specs=proc.keyword_specs, default_eval=eval_default)
        except Exception as exc:
            _record_rejected_call(exc, proc, args)
            raise
        return eval_body(proc.body, new_env, call=(proc, args))
    if callable(proc):
        return proc(*args)
    raise LispError("in apply_proc: not a procedure: %r" % (proc,))


# ---------------------------------------------------------------------------
# Helpers for checking and converting builtin arguments
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
    if isinstance(x, (Pair, LispVector, LispDate, LispStruct)):
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
    if isinstance(x, LispVector):
        # Deliberately NOT x.items.tolist() -- str() on a numpy float32
        # scalar prints the shortest decimal that round-trips to that
        # SAME float32 value (e.g. "0.964"), which is what a value
        # stored in a float32-backed vector actually IS; converting to
        # a native Python float first (.item()/.tolist()) promotes to
        # float64 precision and would print the long, noisy float64
        # value closest to that float32 bit pattern instead (e.g.
        # "0.9639999866485596") -- numerically consistent, but a much
        # worse READING experience for no benefit, since to_string's
        # final `return str(x)` fallback (below) handles a numpy scalar
        # just fine without hitting any of the isinstance checks above it.
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
            for item in x.items:   # see to_string's LispVector branch for why not .tolist()
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


# ---------------------------------------------------------------------------
# Debugging: the nested REPL used by (breakpoint) and debug-function
# ---------------------------------------------------------------------------

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

    `(backtrace)` typed at this prompt shows the paused program's chain of
    calls: the paused evaluators are still running (registered in
    _active_stacks) underneath the one this REPL evaluates your input with.
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
            except Exception as e:
                print(format_error_report(e), end="")
            buffer = ""
            if resume:
                break
    print("--- %s: resuming ---" % label)


# ---------------------------------------------------------------------------
# Running a file of Lisp source
# ---------------------------------------------------------------------------

def run_file(path, env):
    with open(path) as f:
        text = f.read()
    for expr in parse(text):
        seval(expr, env)

