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
    """A Lisp symbol. A str subclass, kept distinct from LispString so
    symbol? and string? can tell them apart."""
    pass


class LispString(str):
    """A Lisp string. A str subclass, kept distinct from Symbol."""
    pass


class Keyword(Symbol):
    """A keyword, e.g. :name (the colon is part of the stored name). Unlike
    a symbol, a keyword evaluates to itself, so keyword-argument calls such
    as (make-point :x 1) need no quoting."""
    pass


class UninternedSymbol(Symbol):
    """A symbol made by gensym, equal only to itself. An ordinary symbol with
    the same name -- one the reader made from text, or string->symbol made
    -- is a different symbol, so nothing a program says can refer to it by
    accident. (Common Lisp's gensym makes the same kind of symbol.) As a
    dictionary key, e.g. in an Env, it's found only by itself."""

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return id(self)


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
    """A fixed-size, mutable vector of numbers, strings, and/or dates, e.g.
    #(1 2 3.5).

    `items` is a numpy array rather than a Python list, to save memory on
    large data (a million float32 values take 4 MB, versus about 32 MB as a
    Python list) and so the vector math builtins can use numpy.

    DTYPE POLICY: the three *_DTYPE attributes below set how every vector
    stores its numbers. The defaults suit loan-level mortgage data: float32
    keeps about 7 significant digits, enough for balances under $1,000,000
    and for rates. Set FLOAT_DTYPE = np.float64 if you need more precision.
    A vector holding strings or dates is stored as Python objects.

    Two rules for code that uses `items`:
      1. Indexing a numeric array returns a numpy scalar (np.float32, ...),
         which the interpreter's isinstance(x, (int, float)) checks don't
         recognize. Convert one element with _lisp_scalar(), or a whole
         array with .tolist(). (So a value loses precision only once, when
         it's stored; arithmetic on it afterward is in full double precision.)
      2. A numpy slice is a view, not a copy. The constructor always copies
         what it's given, so no two vectors ever share storage."""

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
        """Build the numpy array for a new vector from a Python list of Lisp
        values, using the narrowest dtype that holds every value exactly:
        BOOL_INT_DTYPE if they're all 0 or 1, INT_DTYPE for other integers, and
        FLOAT_DTYPE if any is a float (5.0 counts as a float). Anything else --
        an empty list, a string or date, an integer too big for INT_DTYPE, or the
        unevaluated contents of a #(...) literal -- gets dtype=object."""
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
    """Convert one element of a vector's `items` into a plain Python value:
    a numpy scalar becomes an int or float, and anything else (such as a
    LispDate in an object array) is returned unchanged. A float32 becomes
    the float of its shortest decimal form -- 4.01, not the
    4.010000228881836 it would widen to -- which is also the closer value to
    the number that was originally stored."""
    if isinstance(x, np.float32):
        return float(str(x))
    return x.item() if isinstance(x, np.generic) else x


def _narrow_vector_result(arr):
    """Convert a float64 result of numpy arithmetic back to
    LispVector.FLOAT_DTYPE. Numpy promotes int32 + float32, or float32 times
    a Python float, to float64, which would double a large vector's memory
    for no benefit."""
    return arr.astype(LispVector.FLOAT_DTYPE) if arr.dtype == np.float64 else arr


def _value_fits_dtype(x, dtype):
    """True if number x can be stored in a numpy array of this dtype
    exactly. Checked beforehand because numpy doesn't always complain:
    storing 0.5 in an integer array silently stores 0."""
    if dtype == object:
        return True
    if np.issubdtype(dtype, np.integer):
        if not isinstance(x, int):
            return False   # even 5.0 -- numpy would truncate a float
        info = np.iinfo(dtype)
        return info.min <= x <= info.max
    return isinstance(x, (int, float))   # a float dtype holds any number (perhaps rounded)


def _vector_widen_for(v, x):
    """Before storing x in vector v (vector-set!, vector-fill!), switch v to a
    wider dtype if its current one can't hold x exactly. This is needed
    because a vector's dtype comes from its initial contents -- e.g.
    (make-vector n 0) starts as a 1-byte integer array -- before the values
    it will eventually hold are known. The new dtype is chosen the same way
    as for a new vector, or dtype=object if even that can't hold x (a date,
    or a huge integer)."""
    if _value_fits_dtype(x, v.items.dtype):
        return
    new_dtype = LispVector._infer_array(v.items.tolist() + [x]).dtype
    if not _value_fits_dtype(x, new_dtype):
        new_dtype = object
    v.items = v.items.astype(new_dtype)


class LispDate:
    """A calendar date, e.g. (date 2020 1 15). Wraps a Python datetime.date."""

    def __init__(self, year, month, day):
        self.date = datetime.date(year, month, day)

    def __eq__(self, other):
        return isinstance(other, LispDate) and self.date == other.date

    def __hash__(self):
        # Dates never change once made, so they can be hash-table keys.
        return hash(self.date)

    def __lt__(self, other):
        return isinstance(other, LispDate) and self.date < other.date

    def __le__(self, other):
        return isinstance(other, LispDate) and self.date <= other.date

    def __gt__(self, other):
        return isinstance(other, LispDate) and self.date > other.date

    def __ge__(self, other):
        return isinstance(other, LispDate) and self.date >= other.date

    def __repr__(self):
        return self.date.isoformat()


class LispHashTable:
    """A mutable hash table (make-hash-table, hash-table-*): a thin wrapper
    around a Python dict. Keys must be immutable Lisp values -- numbers,
    strings, symbols, keywords, or dates. Lists, vectors, and structs can
    change, so they can't be keys."""

    def __init__(self):
        self.table = {}

    def __repr__(self):
        return "#<hash-table %d entr%s>" % (len(self.table), "y" if len(self.table) == 1 else "ies")


class LispStructType:
    """The record type made by (defstruct name slot...) or
    (defstruct (name (:include parent)) slot...).

    `slots` is the complete, ordered list of (slot_name, default_expr)
    pairs: the parent's slots first (a child slot with the same name just
    replaces the parent's default), then the child's new ones. Everything
    that uses a struct type reads `slots`; only is_a() looks at `parent`."""

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
        """True if this type is other_type, or includes it directly or through
        a chain of parents -- so an instance of this type can be used wherever
        other_type is expected."""
        t = self
        while t is not None:
            if t is other_type:
                return True
            t = t.parent
        return False

    def __repr__(self):
        return "#<struct-type %s>" % (self.name,)


class LispStruct:
    """An instance of a defstruct type: its type plus a dict of slot values.
    Two structs are equal if they have the same type and equal slot values."""

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
    """Wrap a Python datetime.date as a LispDate."""
    obj = LispDate.__new__(LispDate)
    obj.date = pydate
    return obj


class Procedure:
    """A user-defined function, made by `lambda` or `define`.

      params          the fixed parameter names
      rest_param      for a variadic procedure, the name bound to a list of the
                      extra arguments; otherwise None (see parse_params)
      keyword_specs   the &key parameters, as (name, default_expr) pairs
      body, env       the body expressions, and the environment it was defined in
      name            used only to label it in traces and stack traces
      is_scope        True for the procedure let/let*/dolist turn into. It's a
                      variable scope, not a real call, so traces leave it out."""

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
    """A macro, made by `defmacro`. It has the same parts as a Procedure,
    but when it's called, its parameters are bound to the call's UNEVALUATED
    argument expressions, and its body returns new code (the "expansion"),
    which is then evaluated in place of the call. See expand_macro()."""

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
    """Raised for any error in a Lisp program: reading, evaluating, or in a builtin."""
    pass


class LispThrow(BaseException):
    """Raised by (throw tag value) and caught by the matching (catch tag ...).
    It's a BaseException, not an Exception, because a throw isn't an error:
    catch-error, and any `except Exception` in a builtin, let it pass."""

    def __init__(self, tag, value):
        super().__init__(tag, value)
        self.tag = tag
        self.value = value


# The tags of the (catch tag ...) forms now running, innermost last, so that
# throw can report an error when nothing will catch it.
_active_catch_tags = []


def catch_tags_match(a, b):
    """Whether a throw to tag a is caught by a catch of tag b: the same
    object, or equal values of the same type (so 'done matches 'done, but 0
    doesn't match #f)."""
    return a is b or (type(a) is type(b) and a == b)


def throw_to(tag, value):
    """(throw tag [value]) -- see "catch" in eval_special_form."""
    if not any(catch_tags_match(tag, active) for active in _active_catch_tags):
        raise LispError("throw: nothing catches %s -- a throw must happen inside (catch %s ...)"
                        % (to_string(tag), to_string(tag)))
    raise LispThrow(tag, value)


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
    """Parse source text into top-level Lisp expressions, one at a time. (A
    generator, so a file's forms before a syntax error still get run.)"""
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


def check_name(name):
    """Raise a clear error unless name can be a variable's name: a symbol,
    but not a keyword. Catches (define nan 5), which would otherwise bind
    nothing useful, since the reader turns nan, inf, and infinity into
    numbers."""
    if isinstance(name, Symbol) and not isinstance(name, Keyword):
        return
    note = " (nan, inf, and infinity are read as numbers)" if isinstance(name, float) else ""
    raise LispError("%s can't be used as a name -- a name must be a symbol%s" % (to_string(name), note))


def parse_params(params_expr):
    """Split a lambda/define/defmacro parameter list into
    (fixed_names, rest_name_or_None, keyword_specs):

      (a b c)               three fixed parameters
      (a b . rest)          a and b fixed; rest gets a list of any extra arguments
      args                  (a bare symbol) every argument, as a list
      (a b &key c (d 10))   a and b fixed; c and d are keyword parameters, passed
                            as :c value :d value in any order. c defaults to '(),
                            d to 10.

    &key can't be combined with a rest parameter. Env.__init__ does the
    binding when the procedure is called."""
    if isinstance(params_expr, Symbol):
        check_name(params_expr)
        return [], params_expr, []
    fixed = []
    p = params_expr
    while isinstance(p, Pair) and p.car != Symbol("&key"):
        check_name(p.car)
        fixed.append(p.car)
        p = p.cdr
    if isinstance(p, Pair) and p.car == Symbol("&key"):
        keyword_specs = []
        p = p.cdr
        while isinstance(p, Pair):
            spec = p.car
            if isinstance(spec, Pair):
                check_name(spec.car)
                keyword_specs.append((spec.car, spec.cdr.car))
            else:
                check_name(spec)
                keyword_specs.append((spec, None))
            p = p.cdr
        return fixed, None, keyword_specs
    if p is NIL:
        return fixed, None, []
    check_name(p)
    return fixed, p, []


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class Env(dict):
    """The name -> value bindings of one scope, plus a link to the enclosing
    scope (`outer`). The chain of Envs follows how the code is nested, not
    how calls are nested, so it stays short even in deep recursion.

    trace_emit is set only on a global environment (by make_global_env): the
    function that writes verbose-mode trace lines."""

    trace_emit = None

    def __init__(self, params=(), args=(), outer=None, rest_param=None,
                 keyword_specs=None, default_eval=None):
        """Bind a call's arguments to its parameters.

        `params` are the fixed parameter names. With rest_param, any extra
        arguments are bound to it as a list; without it, the argument count must
        match exactly. With keyword_specs, the arguments after the fixed ones
        must be :name value pairs, and a keyword parameter that isn't passed gets
        default_eval(default_expr, self) -- or '() if it has no default.
        default_eval is eval_default for a procedure call (defaults are
        evaluated) and raw_default for a macro (defaults stay as code)."""
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
        """The innermost Env in which `name` is bound; an error if there's none."""
        e = self
        while e is not None:
            if name in e:
                return e
            e = e.outer
        raise LispError("unbound symbol: %s" % name)

    def lookup_or_none(self, name):
        """The value of `name`, or None if it isn't bound anywhere. Used to
        check whether an operator names a macro, without raising an error."""
        e = self
        while e is not None:
            if name in e:
                return e[name]
            e = e.outer
        return None


def eval_default(expr, env):
    """How a procedure call fills in a missing keyword argument: evaluate the
    default expression in the new call environment. (See Env.__init__.)"""
    return seval(expr, env)


def raw_default(expr, env):
    """How a macro call fills in a missing keyword argument: use the default
    expression as-is, since macro arguments are unevaluated code."""
    return expr


# ---------------------------------------------------------------------------
# Call tracing and Lisp-level stack traces
# ---------------------------------------------------------------------------
#
# Every call of a user-defined procedure (or macro transformer) leaves a
# ('CALL', proc, args, tails) frame on the evaluator's control stack --
# see seval(). That gives two debugging aids:
#
#   VERBOSE MODE -- (verbose n) -- logs calls as they happen:
#       0 off (the default), 1 procedure names, 2 also arguments and
#       return values, 3 also macro expansions.
#     Lines are indented by call depth; a tail call is marked >> not >.
#     Output goes wherever display output goes.
#
#   STACK TRACES -- when an error escapes, seval() copies the CALL frames
#     into the exception (exc.lisp_trace), so the REPL, batch mode, GUI,
#     and Jupyter can show the chain of calls that led to the error.
#     (backtrace) shows the current chain without an error.
#
# A tail call REPLACES its caller's CALL frame (that's what keeps a tail call
# constant-space), so a caller that tail-called its way out isn't listed.
# The replacing frame counts them instead, shown as "[+N tail calls]".
# let/let*/dolist scopes (Procedure.is_scope) aren't calls and get no frame.

VERBOSE_OFF, VERBOSE_CALLS, VERBOSE_ARGS, VERBOSE_MACROS = 0, 1, 2, 3
_verbose_level = 0      # current verbosity; change ONLY via set_verbose_level()
_call_depth = 0         # nesting depth of traced calls, for indentation

TRACE_MAX_FRAMES = 40   # a longer stack trace keeps the outermost 10 and innermost 30
_BRIEF_MAX_ITEMS = 6    # list/vector elements shown before "..."
_BRIEF_MAX_DEPTH = 3    # nesting shown before "(...)"
_BRIEF_MAX_STRING = 40  # string characters shown before "..."


def set_verbose_level(level):
    """Set the verbosity -- 0, 1, 2, 3, or #f/#t for 0/1 -- and return the
    previous level, so the caller can restore it."""
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
    """A short rendering of a value for trace lines. Unlike to_string(), it
    never walks all of a big list or vector, so tracing stays cheap."""
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
    """`(name arg...)`, or just `name`, for one call. A macro's arguments
    are its unevaluated source expressions."""
    if not with_args:
        return _proc_name(proc)
    return "(" + " ".join([_proc_name(proc)] + [_brief(a) for a in args]) + ")"


def _trace_write(env, text):
    """Write one trace line wherever `env`'s display output goes (the
    global environment's trace_emit), or to stderr if there's nowhere."""
    while env is not None:
        emit = env.trace_emit
        if emit is not None:
            emit(text + "\n")
            return
        env = env.outer
    sys.stderr.write(text + "\n")


def _trace_enter(proc, args, is_tail):
    """Log the start of a call. A tail call takes the place of the call it
    ends, so it's indented at that call's depth instead of one deeper."""
    global _call_depth
    indent = "  " * (max(0, _call_depth - 1) if is_tail else _call_depth)
    _trace_write(proc.env, "%s%s %s" % (
        indent, ">>" if is_tail else ">",
        _call_text(proc, args, _verbose_level >= VERBOSE_ARGS)))
    if not is_tail:
        _call_depth += 1


def _trace_leave(proc, args, tails, value):
    """A call returned `value`: undo its indentation and, at level 2+, log it."""
    global _call_depth
    _call_depth = max(0, _call_depth - 1)
    if _verbose_level >= VERBOSE_ARGS:
        note = "  [after %d tail call%s]" % (tails, "" if tails == 1 else "s") if tails else ""
        _trace_write(proc.env, "%s< %s => %s%s" % (
            "  " * _call_depth, _call_text(proc, args), _brief(value), note))


def _trace_macro_expansion(macro, form, expansion):
    _trace_write(macro.env, "%s~ %s => %s" % ("  " * _call_depth, _brief(form), _brief(expansion)))


def _stack_calls(control_stack):
    """Every call in progress on one control stack, innermost first, as
    (proc, args, tails, rejected) tuples."""
    return [(f[1], f[2], f[3], False) for f in reversed(control_stack) if f[0] == 'CALL' or f[0] == 'MCALL']


_active_stacks = []     # the control stack of every seval() currently running, outermost first


def _current_calls():
    """Every call in progress right now, innermost first -- across all the
    evaluators running (a map callback, a macro transformer, eval, ... each
    run in a nested seval with its own stack). This is what (backtrace) shows."""
    calls = []
    for stack in reversed(_active_stacks):
        calls.extend(_stack_calls(stack))
    return calls


def _record_rejected_call(exc, proc, args):
    """Add a call whose arguments couldn't be bound (wrong count, unknown
    keyword, ...) to exc's trace. The error is about that call, but it never
    got a frame of its own, so it wouldn't otherwise appear."""
    trace = getattr(exc, "lisp_trace", None)
    if trace is None:
        try:
            trace = exc.lisp_trace = []
        except AttributeError:
            return
    trace.append((proc, args, 0, True))


def _record_lisp_trace(exc, control_stack):
    """As an error passes out of a seval(), add that evaluator's calls in
    progress to exc.lisp_trace. Nested evaluators each add theirs on the way
    out, so the list ends up innermost-first."""
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
    """Format calls (innermost first) the way Python formats a traceback:
    outermost first, so the most recent call is next to the error message.
    A very long stack keeps its first and last frames. "" for no calls."""
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
    """The chain of Lisp calls that led to `exc`, as text ("" if none)."""
    return format_call_stack(getattr(exc, "lisp_trace", None) or [])


def format_error_report(exc):
    """The report shown for an error by the REPL, batch mode, and the GUI:
    the chain of calls (if any), then `Error: message`."""
    return format_lisp_traceback(exc) + "Error: %s\n" % (exc,)


# ---------------------------------------------------------------------------
# Evaluator -- explicit-stack version
# ---------------------------------------------------------------------------
#
# seval() doesn't call itself to evaluate sub-expressions. It keeps an
# explicit "control stack" of work still to do and a "value stack" of
# results, and runs a loop, so how deeply Lisp code can recurse is limited
# by memory rather than by Python's recursion limit. Each control frame is
# a tuple starting with a tag:
#
#   ('EVAL', expr, env)             evaluate expr in env
#   ('APPLY', nargs)                apply a procedure to nargs arguments
#   ('SEQ', remaining_exprs, env)   discard a value, then run the rest of a body
#   ('IF', conseq, alt, env)        choose a branch once the test's value is in
#   ('DEFINE', name, env)           finish a (define name expr)
#   ('SET', name, env)              finish a (set! name expr)
#   ('COND', clauses, env)          try the next cond clause
#   ('COND_BRANCH', body, rest, env) act on a cond test's value
#   ('AND', exprs, env)             evaluate the remaining `and` operands
#   ('AND_CHECK', rest, env)        act on one `and` operand's value
#   ('OR', exprs, env)              evaluate the remaining `or` operands
#   ('OR_CHECK', rest, env)         act on one `or` operand's value
#   ('WITH_STRUCT', body, env)      bind a struct's slots as variables, then run body
#   ('CALL', proc, args, tails)     marks a user procedure's body, for traces; a
#                                   tail call replaces it (see "Call tracing")
#   ('MCALL', macro, exprs, 0)      the same for a macro's body; never replaced

SPECIAL_FORMS = {
    "quote", "if", "define", "set!", "lambda",
    "begin", "let", "let*", "cond", "and", "or", "dolist",
    "defmacro", "quasiquote", "breakpoint", "defstruct", "catch-error",
    "unwind-protect", "catch", "with-struct", "%scope-lambda", "backtrace",
}


def is_true(x):
    """Everything except #f counts as true (including '() and 0)."""
    return x is not False


def push_sequence(exprs, env, control_stack, value_stack):
    """Push frames to evaluate a body (a list of expressions) in order,
    keeping only the last value. Used for begin, procedure bodies, and the
    bodies of cond clauses."""
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
    """(let ((x1 v1) (x2 v2)) body...)  =>  ((%scope-lambda (x1 x2) body...) v1 v2)
    %scope-lambda makes the same Procedure `lambda` does, marked is_scope so
    traces don't count a let as a call."""
    bindings = pairs_to_list(args.car)
    body = args.cdr  # already a Pair-list, reused as the lambda's body
    names = [b.car for b in bindings]
    value_exprs = [b.cdr.car for b in bindings]
    lambda_expr = Pair(Symbol("%scope-lambda"), Pair(list_to_pairs(names), body))
    return Pair(lambda_expr, list_to_pairs(value_exprs))


def desugar_let_star(args):
    """(let* ((x1 v1) (x2 v2) ...) body...)
      =>  (let ((x1 v1)) (let* ((x2 v2) ...) body...)), ending with (let () body...)."""
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
    """A new symbol that can't collide with any name in the program: an
    UninternedSymbol, named %base-N (N counts up, so the names are easy to
    tell apart when printed). dolist uses it for its loop variables, and Lisp
    code gets it as (gensym), for macros that need temporary names."""
    _gensym_counter[0] += 1
    return UninternedSymbol("%%%s-%d" % (base, _gensym_counter[0]))


def desugar_dolist(args):
    """(dolist (var list-expr [result-expr]) body...) runs body once for each
    element of the list, with var bound to that element, then returns
    result-expr (or '()). It's rewritten into a local recursive loop:

        (let ()
          (define (%dolist-loop-N %dolist-remaining-N)
            (if (null? %dolist-remaining-N)
                (let ((var '())) result-expr)
                (let ((var (car %dolist-remaining-N)))
                  body...
                  (%dolist-loop-N (cdr %dolist-remaining-N)))))
          (%dolist-loop-N list-expr))

    The recursive call is a tail call, so a long list doesn't grow the stack."""
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
    """The value of a quasiquoted template: (unquote x) is replaced by x's
    value, (unquote-splicing x) inside a list by the elements of x's value,
    and everything else is copied as-is. A nested quasiquote increases the
    depth, and unquote only evaluates at depth 1 -- the same as Scheme.

    This recursion is in Python, which is fine: its depth is how deeply the
    template is nested in the source code, never the size of any data."""
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
        # .tolist() gives plain Python numbers rather than numpy scalars, so the
        # rebuilt vector gets a compact dtype again.
        return LispVector([eval_quasiquote(x, env, depth) for x in expr.items.tolist()])

    return expr  # atoms (numbers, strings, symbols, booleans) are literal


def expand_macro(macro, arg_exprs):
    """Run a macro's body with the call's unevaluated argument expressions
    bound to its parameters, and return the expansion (the new code). The
    caller then evaluates the expansion in place of the macro call."""
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
        # A special form so it sees the caller's actual environment (a paused
        # function's own variables) -- a function or macro can't. An optional
        # argument is evaluated there and printed first, to say where we stopped.
        if args is not NIL:
            print(to_display_string(seval(args.car, env)))
        debug_repl(env, label="breakpoint")
        value_stack.append(NIL)

    elif op == "defmacro":
        # (defmacro name params body...) -- params as in lambda (see parse_params).
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
            # (define (name params...) body...) -- params as in lambda.
            name = target.car
            check_name(name)
            fixed, rest, keyword_specs = parse_params(target.cdr)
            body = pairs_to_list(args.cdr)
            env[name] = Procedure(fixed, body, env, rest_param=rest, keyword_specs=keyword_specs,
                                  name=name)
            value_stack.append(name)
        else:
            name = target
            check_name(name)
            control_stack.append(('DEFINE', name, env))
            control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "set!":
        name = args.car
        check_name(name)
        control_stack.append(('SET', name, env))
        control_stack.append(('EVAL', args.cdr.car, env))

    elif op == "lambda" or op == "%scope-lambda":
        # See parse_params() for the forms params can take. %scope-lambda is what
        # let/let*/dolist turn into: the same Procedure, marked is_scope.
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
        # (defstruct name slot...) or (defstruct (name (:include parent)) slot...).
        # Each slot is a symbol (default '()) or (slot default-expr). Defines:
        #   make-<name>          a constructor taking one keyword argument per slot --
        #                        an ordinary &key Procedure whose body calls %make-struct
        #   <name>-<slot>        an accessor for each slot, inherited slots included
        #   <name>-<slot>-set!   a setter for each slot
        #   <name>?              a predicate
        #   copy-<name>          a shallow copy
        # Each accepts an instance of this type or of any type that includes it.
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
                    # (:include parent (slot new-default) ...) changes an inherited slot's
                    # default, the same as redeclaring that slot in the main slot list.
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
            # A shallow copy, of the instance's own type -- so copying a child
            # instance through a parent's copy-<name> keeps its extra slots.
            if not (isinstance(s, LispStruct) and s.struct_type.is_a(t)):
                raise LispError("copy-%s: not a %s: %r" % (type_name, type_name, s))
            return LispStruct(s.struct_type, dict(s.values))
        env[Symbol("copy-%s" % type_name)] = copier

        value_stack.append(type_name)

    elif op == "backtrace":
        # (backtrace) prints the current chain of calls, as an error report would.
        # A special form so a user procedure named backtrace can't hide it.
        text = format_call_stack(_current_calls(), "Lisp call stack (most recent call last):")
        _trace_write(env, (text or "Lisp call stack: (empty -- not inside any procedure call)\n").rstrip("\n"))
        value_stack.append(NIL)

    elif op == "with-struct":
        # (with-struct struct-expr body...) binds each slot of the struct as a
        # variable, in a new scope, then runs body. A special form rather than a
        # macro because which names to bind depends on the struct's type, which
        # isn't known until struct-expr is evaluated; the WITH_STRUCT frame does
        # the binding once its value is ready.
        if not isinstance(args, Pair):
            raise LispError("with-struct: expected (with-struct struct-expr body...)")
        control_stack.append(('WITH_STRUCT', pairs_to_list(args.cdr), env))
        control_stack.append(('EVAL', args.car, env))

    elif op == "catch-error":
        # (catch-error protected-expr (var) handler-body...): if evaluating
        # protected-expr raises an error -- a LispError or a Python exception from a
        # builtin, such as sqrt's ValueError -- bind var to the message and return
        # handler-body's value instead. (KeyboardInterrupt and the like still
        # propagate.) This needs a real Python try/except, so protected-expr runs in
        # a nested seval(); tail calls inside it are optimized only up to that
        # boundary.
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

    elif op == "unwind-protect":
        # (unwind-protect protected-expr cleanup-expr...): evaluate protected-expr
        # and return its value, but run the cleanup expressions afterwards however
        # protected-expr finishes -- normally, with an error, or by a throw. Like
        # catch-error, this needs a Python try (here, try/finally), so
        # protected-expr runs in a nested seval().
        if not isinstance(args, Pair):
            raise LispError("unwind-protect: expected (unwind-protect protected-expr cleanup-expr...)")
        protected_expr = args.car
        cleanup_body = pairs_to_list(args.cdr)
        try:
            result = seval(protected_expr, env)
        finally:
            eval_body(cleanup_body, env)
        value_stack.append(result)

    elif op == "catch":
        # (catch tag body...): evaluate tag, then body. If (throw tag value) runs
        # during body -- directly, or in any function body calls -- stop right
        # there and return value; otherwise return body's value. The innermost
        # catch with a matching tag (see catch_tags_match) gets the throw. The
        # body runs in a nested seval() inside a Python try, as for catch-error.
        if not isinstance(args, Pair):
            raise LispError("catch: expected (catch tag body...)")
        tag = seval(args.car, env)
        body = pairs_to_list(args.cdr)
        _active_catch_tags.append(tag)
        try:
            result = eval_body(body, env)
        except LispThrow as thrown:
            if not catch_tags_match(thrown.tag, tag):
                raise
            result = thrown.value
        finally:
            _active_catch_tags.pop()
        value_stack.append(result)

    else:
        raise LispError("unknown special form: %s" % op)


def seval(expr, env, call=None):
    """Evaluate a Lisp expression in an environment -- with an explicit stack
    rather than Python recursion (see the comment above SPECIAL_FORMS).

    call (optional): (procedure_or_macro, args) when this evaluation is
    running a procedure or macro body -- apply_proc() and expand_macro() pass
    it so that call gets a frame of its own and shows up in traces.

    If an error escapes, the calls in progress are recorded on the exception
    (exc.lisp_trace) on its way out."""
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
    except LispThrow:
        _call_depth = entry_depth      # a throw isn't an error, so it gets no stack trace
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
                # A macro gets its arguments unevaluated, so check for one before
                # evaluating anything. Its expansion is pushed as an ordinary EVAL frame,
                # so a macro call in tail position is still a proper tail call.
                macro = cur_env.lookup_or_none(op) if isinstance(op, Symbol) else None
                if isinstance(macro, Macro):
                    expansion = expand_macro(macro, pairs_to_list(args))
                    if _verbose_level >= VERBOSE_MACROS:
                        _trace_macro_expansion(macro, x, expansion)
                    control_stack.append(('EVAL', expansion, cur_env))
                else:
                    # A procedure call: push APPLY first (so it runs last), then the
                    # arguments in reverse, then the operator (so it's evaluated first).
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
                    # Leave a CALL frame under the body, naming this call for traces. If
                    # the top of the stack is already a CALL frame, nothing is waiting for
                    # the caller's value: this is a TAIL call, so it replaces that frame
                    # (keeping tail calls constant-space) and counts the call it absorbed.
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
            # A procedure's body finished normally; its value is on the value stack.
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
            # The instance's own type decides which names are bound, so a child
            # instance gets its extra slots too.
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
    """Evaluate a list of expressions in env and return the last value."""
    return seval(Pair(Symbol("begin"), list_to_pairs(body)), env, call)


def apply_proc(proc, args):
    """Call a procedure -- a Lisp Procedure or a Python builtin -- with a
    list of already-evaluated arguments. Used by builtins that take a
    procedure argument (map, filter, sort, apply, ...)."""
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
    """Vectors hold numbers, strings, and dates -- not booleans or lists."""
    for a in args:
        if isinstance(a, bool) or not isinstance(a, (int, float, LispString, LispDate)):
            raise LispError("%s: not a number, string, or date: %r" % (name, a))


def numeric_value(v):
    """A vector element as a plain number: a date becomes its day number
    (date.toordinal()); a number is returned unchanged."""
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
    """A value as the REPL prints it (strings in quotes). Loops rather than
    recursing along a list, so a very long list prints fine."""
    if x is True:
        return "#t"
    if x is False:
        return "#f"
    if x is NIL:
        return "()"
    if isinstance(x, LispString):
        # A backslash or quote mark inside the string is written with a backslash
        # before it, as you'd type it, so the printed form reads back as the same
        # string. Newlines and tabs are left as they are, so long text stays readable.
        return '"%s"' % x.replace("\\", "\\\\").replace('"', '\\"')
    if isinstance(x, LispDate):
        return x.date.isoformat()
    if isinstance(x, LispVector):
        # Not .tolist(): str() of a float32 prints the short value it actually
        # holds (0.964), while a Python float would print 0.9639999866485596.
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
    """A value or expression as a deliberately spread-out, multi-line string:
    each list element on its own line, and each closing parenthesis on its
    own line directly below its opening one. Not meant to be pretty -- it
    makes a misplaced parenthesis easy to spot.

    Also used to show a procedure's or macro's definition (see
    reconstruct_procedure_source), rebuilt from its parsed parameters and
    body -- so comments and the original formatting aren't kept."""
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
    """Rebuild the source form of a parameter list from (params, rest_param,
    keyword_specs) -- the reverse of parse_params()."""
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
    """(lambda (params...) body...) for a Procedure -- or, given a name,
    (define (name params...) body...)."""
    param_spec = _param_spec_from(proc.params, proc.rest_param, proc.keyword_specs)
    body = list_to_pairs(proc.body)
    if name is not None:
        return Pair(Symbol("define"), Pair(Pair(name, param_spec), body))
    return Pair(Symbol("lambda"), Pair(param_spec, body))


def reconstruct_macro_source(macro, name=None):
    """(defmacro name (params...) body...) for a Macro. A Macro doesn't know
    the name it's bound to, so pass it in."""
    param_spec = _param_spec_from(macro.params, macro.rest_param, macro.keyword_specs)
    body = list_to_pairs(macro.body)
    return Pair(Symbol("defmacro"),
                Pair(name if name is not None else Symbol("<anonymous>"),
                     Pair(param_spec, body)))


# ---------------------------------------------------------------------------
# Debugging: the nested REPL used by (breakpoint) and debug-function
# ---------------------------------------------------------------------------

def debug_repl(env, label="debug"):
    """A nested REPL, used by (breakpoint) and debug-function. What you type is
    evaluated in `env` -- the actual environment where the program paused,
    so you can inspect, and set!, the paused function's own variables. Type
    (continue), (exit), or Ctrl-D to resume. (backtrace) shows how the
    program got here.

    It reads from the console with input(), even when the GUI is running;
    there's no GUI debugger."""
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

