"""The built-in procedures, and make_global_env(), which builds the global
environment every Lisp program runs in.

Most builtins are plain functions, grouped by topic below; each group ends
with a table mapping Lisp names to functions (NUMBER_BUILTINS,
LIST_BUILTINS, ...). A few builtins need something belonging to one
environment -- the environment itself (eval, load) or where its output
goes (display) -- so the make_..._builtins() functions near the end create
them per environment. make_global_env() puts all of these, plus the other
modules' BUILTINS tables, into a new environment.

To add builtins of your own, see "Adding your own builtins" in
lisp_interpreter_reference.md."""

import datetime
import math
import numbers
import operator
import os
import random
import string
import sys

import numpy as np

from lisp_core import (
    Env, Keyword, LispAbort, LispDate, LispError, LispHashTable, LispString, LispStruct,
    LispVector, Macro, NIL, Pair, Procedure, Symbol,
    _brief, _date_from_pydate, _lisp_scalar, _vector_widen_for,
    apply_proc, builtin_names, check_numbers, plural, check_vector_elements, expand_macro, gensym,
    get_verbose_level, is_true,
    list_to_pairs, pairs_to_list, parse, pretty_print_string,
    reconstruct_macro_source, reconstruct_procedure_source, run_file, seval,
    set_verbose_level, throw_to, to_display_string, to_string,
)
import lisp_charts
import lisp_csv
import lisp_debug
import lisp_fred
import lisp_http
import lisp_regression
import lisp_simplex
import lisp_sofr
import lisp_sqlite
import lisp_tables
import lisp_tastytrade
import lisp_time_series
import lisp_vector_math
from lisp_csv import parse_column_pairs


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
#
# The arithmetic builtins work on vectors too: when an argument is a vector,
# the work is done element by element with numpy (lisp_vector_math.elementwise
# and compare), and a single number is used with every element. So
# (* balance rate) multiplies every balance by the rate, and (< v 0) gives a
# mask: 1 where the element is negative, 0 where it isn't.

def any_vector(args):
    for a in args:
        if isinstance(a, LispVector):
            return True
    return False


def add(*args):
    if any_vector(args):
        return lisp_vector_math.elementwise("+", args, operator.add)
    check_numbers(args, "+")
    total = 0
    for a in args:
        total += a
    return total


def sub(*args):
    if not args:
        raise LispError("- needs at least one argument")
    if any_vector(args):
        if len(args) == 1:
            args = (0,) + args          # (- v) is (- 0 v)
        return lisp_vector_math.elementwise("-", args, operator.sub)
    check_numbers(args, "-")
    if len(args) == 1:
        return -args[0]
    total = args[0]
    for a in args[1:]:
        total -= a
    return total


def mul(*args):
    if any_vector(args):
        return lisp_vector_math.elementwise("*", args, operator.mul)
    check_numbers(args, "*")
    total = 1
    for a in args:
        total *= a
    return total


def div(*args):
    """(/ a b ...) -- a divided by b, and so on. For vectors, dividing by
    zero gives NaN or infinity rather than an error."""
    if not args:
        raise LispError("/ needs at least one argument")
    if any_vector(args):
        if len(args) == 1:
            args = (1,) + args          # (/ v) is (/ 1 v)
        return lisp_vector_math.elementwise("/", args, operator.truediv)
    check_numbers(args, "/")
    if len(args) == 1:
        return 1 / args[0]
    total = args[0]
    for a in args[1:]:
        total /= a
    return total


def quotient(a, b):
    """(quotient a b) -- a divided by b, truncated toward zero: (quotient 7 2)
    is 3, and (quotient -7 2) is -3."""
    if any_vector((a, b)):
        return lisp_vector_math.elementwise("quotient", (a, b), lisp_vector_math.truncated_quotient)
    check_numbers((a, b), "quotient")
    if isinstance(a, int) and isinstance(b, int):
        q = abs(a) // abs(b)            # exact, however large the numbers are
        return q if (a < 0) == (b < 0) else -q
    return math.trunc(a / b)


def remainder(a, b):
    """(remainder a b) -- what's left over after (quotient a b):
    a - b * (quotient a b). It has the sign of a: (remainder -7 2) is -1."""
    if any_vector((a, b)):
        return lisp_vector_math.elementwise("remainder", (a, b), np.fmod)
    check_numbers((a, b), "remainder")
    if isinstance(a, int) and isinstance(b, int):
        return a - b * quotient(a, b)
    return math.fmod(a, b)


def mod(a, b):
    """(mod a b) -- a modulo b, which has the sign of b: (mod -7 2) is 1,
    and (mod 7 -2) is -1."""
    if any_vector((a, b)):
        return lisp_vector_math.elementwise("mod", (a, b), np.mod)
    check_numbers((a, b), "mod")
    return a % b


def expt(a, b):
    """(expt a b) -- a raised to the power b."""
    if any_vector((a, b)):
        return lisp_vector_math.elementwise("expt", (a, b), lisp_vector_math.power)
    return a ** b


def lisp_pow(a, b):
    """(pow a b) -- a raised to the power b, always as a floating-point number."""
    if any_vector((a, b)):
        return lisp_vector_math.elementwise("pow", (a, b), lisp_vector_math.power)
    return math.pow(a, b)


def lisp_sqrt(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.unary("sqrt", x, np.sqrt)
    return math.sqrt(x)


def lisp_exp(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.unary("exp", x, np.exp)
    return math.exp(x)


def lisp_log(x, base=None):
    """(log x [base]) -- the natural logarithm of x, or its logarithm to base."""
    if base is None:
        if isinstance(x, LispVector):
            return lisp_vector_math.unary("log", x, np.log)
        return math.log(x)
    if any_vector((x, base)):
        return lisp_vector_math.elementwise("log", (x, base), lambda v, b: np.log(v) / np.log(b))
    return math.log(x, base)


def lisp_abs(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.unary("abs", x, np.abs)
    return abs(x)


def lisp_floor(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.whole_number_results("floor", x, np.floor)
    return math.floor(x)


def lisp_ceiling(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.whole_number_results("ceiling", x, np.ceil)
    return math.ceil(x)


def lisp_truncate(x):
    if isinstance(x, LispVector):
        return lisp_vector_math.whole_number_results("truncate", x, np.trunc)
    return math.trunc(x)


def lisp_round(x):
    """(round x) -- the nearest whole number; a half rounds to the even one, so
    (round 2.5) is 2 and (round 3.5) is 4."""
    if isinstance(x, LispVector):
        return lisp_vector_math.whole_number_results("round", x, np.round)
    return round(x)


def lisp_min(*args):
    """(min x ...) -- the smallest. With vectors, the smallest at each
    position: (min v 100) limits every element to at most 100. (For the
    smallest element of one vector, use vector-min.)"""
    if not args:
        raise LispError("min: expected at least 1 argument, got 0")
    if any_vector(args):
        return lisp_vector_math.elementwise("min", args, np.minimum)
    return min(args)


def lisp_max(*args):
    """(max x ...) -- the largest. With vectors, the largest at each
    position: (max v 0) replaces every negative element with 0. (For the
    largest element of one vector, use vector-max.)"""
    if not args:
        raise LispError("max: expected at least 1 argument, got 0")
    if any_vector(args):
        return lisp_vector_math.elementwise("max", args, np.maximum)
    return max(args)


def chain_compare(op, args):
    """(< a b c) is true if a < b and b < c -- the same for =, >, <=, >=."""
    for a, b in zip(args, args[1:]):
        if not op(a, b):
            return False
    return True


def comparison(name, operation):
    """The builtin for one comparison, such as <. With a vector it gives a
    mask, compared element by element (see lisp_vector_math.compare)."""
    def compare(*args):
        if any_vector(args):
            return lisp_vector_math.compare(name, args, operation)
        return chain_compare(operation, args)
    return compare


# One shared pseudo-random number generator (Python's own `random`
# module). vectors-shuffle takes its own optional per-call seed instead.

def random_seed_fn(n=None):
    random.seed(n)
    return NIL


def random_float_fn(lo=0.0, hi=1.0):
    return random.uniform(lo, hi)


def random_int_fn(lo, hi):
    try:
        return random.randint(lo, hi)
    except (ValueError, TypeError) as e:
        raise LispError("random-int: %s" % e)


NUMBER_BUILTINS = {
    "+": add,
    "-": sub,
    "*": mul,
    "/": div,
    "mod": mod,
    "quotient": quotient,
    "remainder": remainder,
    "abs": lisp_abs,
    "min": lisp_min,
    "max": lisp_max,
    "sqrt": lisp_sqrt,
    "pow": lisp_pow,
    "log": lisp_log,
    "exp": lisp_exp,
    "erf": math.erf,
    "expt": expt,
    "floor": lisp_floor,
    "ceiling": lisp_ceiling,
    "truncate": lisp_truncate,
    "round": lisp_round,
    "=": comparison("=", operator.eq),
    "<": comparison("<", operator.lt),
    ">": comparison(">", operator.gt),
    "<=": comparison("<=", operator.le),
    ">=": comparison(">=", operator.ge),
    "random-seed": random_seed_fn,
    "random-float": random_float_fn,
    "random-int": random_int_fn,
}


# ---------------------------------------------------------------------------
# Booleans, equality, and type predicates
# ---------------------------------------------------------------------------

BOOLEAN_BUILTINS = {
    "not": lambda x: not is_true(x),
    "eq?": lambda a, b: a is b or a == b,
    "equal?": lambda a, b: a == b,
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
}


# ---------------------------------------------------------------------------
# Pairs and lists
# ---------------------------------------------------------------------------

def car(p):
    if not isinstance(p, Pair):
        raise LispError("car: not a pair: %s" % (to_string(p),))
    return p.car


def cdr(p):
    if not isinstance(p, Pair):
        raise LispError("cdr: not a pair: %s" % (to_string(p),))
    return p.cdr


def set_car(p, x):
    """(set-car! p x) -- change the car of the pair p (the first element, if p
    is a list) to x, in place. Returns '()."""
    if not isinstance(p, Pair):
        raise LispError("set-car!: not a pair: %s" % (to_string(p),))
    p.car = x
    return NIL


def set_cdr(p, x):
    """(set-cdr! p x) -- change the cdr of the pair p (the rest of the list,
    if p is a list) to x, in place. Returns '()."""
    if not isinstance(p, Pair):
        raise LispError("set-cdr!: not a pair: %s" % (to_string(p),))
    p.cdr = x
    return NIL


def list_items(x, who):
    """The elements of the list x, as a Python list. An error if x isn't a
    list -- a vector, say -- rather than treating it as an empty list."""
    items = []
    p = x
    while isinstance(p, Pair):
        items.append(p.car)
        p = p.cdr
    if p is not NIL:
        raise LispError("%s: expected a list, got %s" % (who, _brief(x)))
    return items


def sequence_items(x, who):
    """The elements of x, a list or a vector, as a Python list."""
    if isinstance(x, LispVector):
        return [_lisp_scalar(item) for item in x.items]
    return list_items(x, who)


def lisp_length(x):
    """(length x) -- how many elements the list or vector x has, or how many
    characters the string x has."""
    if isinstance(x, LispVector):
        return len(x.items)
    if isinstance(x, LispString):
        return len(x)
    return len(list_items(x, "length"))


def lisp_reverse(x):
    """(reverse x) -- a new list, vector, or string with x's elements (or
    characters) in the opposite order."""
    if isinstance(x, LispVector):
        return LispVector(x.items[::-1])
    if isinstance(x, LispString):
        return LispString(x[::-1])
    return list_to_pairs(list_items(x, "reverse")[::-1])


def lisp_append(*sequences):
    """(append a b ...) -- the lists joined into one new list. The last one
    isn't copied, and can be any value, as in Common Lisp. Given only
    vectors, a new vector; given only strings, a new string."""
    if sequences and all(isinstance(s, LispVector) for s in sequences):
        return vector_append(*sequences)
    if sequences and all(isinstance(s, LispString) for s in sequences):
        return LispString("".join(sequences))
    if not sequences:
        return NIL
    result = sequences[-1]
    for lst in reversed(sequences[:-1]):
        for item in reversed(list_items(lst, "append")):
            result = Pair(item, result)
    return result


def lisp_map(f, seq):
    """(map f seq) -- (f x) for each element x of seq: a list for a list, a
    vector for a vector."""
    if isinstance(seq, LispVector):
        return vector_map(f, seq)
    return list_to_pairs([apply_proc(f, [x]) for x in list_items(seq, "map")])


def lisp_filter(f, seq):
    """(filter f seq) -- the elements x of seq, a list or vector, for which
    (f x) is true, in order, as the same kind of sequence."""
    if isinstance(seq, LispVector):
        keep = [is_true(apply_proc(f, [_lisp_scalar(x)])) for x in seq.items]
        return LispVector(seq.items[np.array(keep, dtype=bool)])
    return list_to_pairs([x for x in list_items(seq, "filter") if is_true(apply_proc(f, [x]))])


def lisp_sort(seq, key=None):
    """(sort seq [key]) -- a new list or vector with seq's elements in
    ascending order; seq itself is unchanged, and equal elements keep their
    order. `key`, if given, is a procedure returning what to compare for
    each element (a number or string), e.g. (sort people person-age)."""
    if isinstance(seq, LispVector):
        if key is None and seq.items.dtype != object:
            return LispVector(np.sort(seq.items, kind="stable"))
        items = [_lisp_scalar(x) for x in seq.items]
        build = LispVector
    elif seq is NIL or isinstance(seq, Pair):
        items = pairs_to_list(seq)
        build = list_to_pairs
    else:
        raise LispError("sort: expected a list or a vector, got %r" % (seq,))
    try:
        if key is None:
            return build(sorted(items))
        keyed = [(apply_proc(key, [x]), x) for x in items]
        keyed.sort(key=lambda pair: pair[0])
        return build([x for _, x in keyed])
    except TypeError:
        raise LispError("sort: elements (or their keys) can't be compared with <")


def lisp_reduce(f, seq, *init):
    """(reduce f seq [initial]) -- combine the elements of seq, a list or a
    vector, from left to right: (f (f (f initial x1) x2) x3) ... Without an
    initial value, the first element is used."""
    items = sequence_items(seq, "reduce")
    if init:
        acc = init[0]
    elif not items:
        raise LispError("reduce: nothing to combine -- the sequence is empty and no initial value was given")
    else:
        acc, items = items[0], items[1:]
    for x in items:
        acc = apply_proc(f, [acc, x])
    return acc


def list_ref(lst, n):
    items = list_items(lst, "list-ref")
    n = int(n)
    if n < 0 or n >= len(items):
        raise LispError("list-ref: index %d out of range (0..%d)" % (n, len(items) - 1))
    return items[n]


def list_tail(lst, n):
    items = list_items(lst, "list-tail")
    n = int(n)
    if n < 0 or n > len(items):
        raise LispError("list-tail: index %d out of range (0..%d)" % (n, len(items)))
    return list_to_pairs(items[n:])


def lisp_assoc(key, alist):
    """(assoc key alist) -- the first (key . value) pair in alist whose key is
    equal to `key`, or #f if there's none. Returns #f rather than '()
    because '() counts as true in this Lisp; only #f is false."""
    for entry in list_items(alist, "assoc"):
        if not isinstance(entry, Pair):
            raise LispError("assoc: alist element is not a pair: %r" % (entry,))
        if entry.car == key:
            return entry
    return False


def lisp_member(x, lst):
    """(member x lst) -- the part of lst starting at the first element equal
    to x, or #f if there's none."""
    items = list_items(lst, "member")
    for i, item in enumerate(items):
        if item == x:
            return list_to_pairs(items[i:])
    return False


LIST_BUILTINS = {
    "cons": lambda a, b: Pair(a, b),
    "car": car,
    "cdr": cdr,
    "set-car!": set_car,
    "set-cdr!": set_cdr,
    "list": lambda *args: list_to_pairs(list(args)),
    "append": lisp_append,
    "reverse": lisp_reverse,
    "length": lisp_length,
    "list-ref": list_ref,
    "list-tail": list_tail,
    "assoc": lisp_assoc,
    "member": lisp_member,
    "null?": lambda p: p is NIL,
    "pair?": lambda p: isinstance(p, Pair),
    "list?": lambda p: p is NIL or isinstance(p, Pair),
    "map": lisp_map,
    "filter": lisp_filter,
    "sort": lisp_sort,
    "reduce": lisp_reduce,
}


# ---------------------------------------------------------------------------
# Procedures, errors, and tracing
# ---------------------------------------------------------------------------

def lisp_apply(f, *args):
    """(apply f arg1 ... args) -- call f with arg1 ... followed by the
    elements of the list `args`. Usually just (apply f lst)."""
    if not args:
        raise LispError("apply: expected at least 2 arguments (a procedure and a list)")
    *leading, last = args
    return apply_proc(f, list(leading) + sequence_items(last, "apply"))


def lisp_gensym(*base):
    """(gensym ["prefix"]) -- a new symbol that can't collide with any name in
    the program, for macros that need temporary names. It's equal only to
    itself, even compared with a symbol of the same name."""
    return gensym(str(base[0]) if base else "g")


def lisp_error(*args):
    raise LispError(" ".join(to_display_string(a) for a in args))


def lisp_throw(tag, value=NIL):
    """(throw tag [value]) -- leave the innermost (catch tag ...) now, making
    it return value (default '()). An error if no catch for tag is running."""
    throw_to(tag, value)


def lisp_verbose(*args):
    """(verbose) returns the current trace level; (verbose n) sets it -- 0 off,
    1 procedure names, 2 also arguments and return values, 3 also macro
    expansions (#f/#t mean 0/1) -- and returns the previous level, so you can
    restore it: (define old (verbose 2)) ... (verbose old)."""
    if len(args) > 1:
        raise LispError("verbose: expected (verbose [level])")
    if args:
        return set_verbose_level(args[0])
    return get_verbose_level()


PROCEDURE_BUILTINS = {
    "apply": lisp_apply,
    "gensym": lisp_gensym,
    "error": lisp_error,
    "throw": lisp_throw,
    "verbose": lisp_verbose,
}


# ---------------------------------------------------------------------------
# Structs (see defstruct in lisp_core.eval_special_form)
# ---------------------------------------------------------------------------

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


def call_method(accessor, instance, *args):
    """(call-method accessor instance arg...) -- call the procedure stored in
    one of instance's slots, passing instance itself as the first argument.
    (call-method animal-speak d) is ((animal-speak d) d), without writing d
    twice. `accessor` is the accessor function itself, not its name."""
    method = apply_proc(accessor, [instance])
    return apply_proc(method, [instance] + list(args))


STRUCT_BUILTINS = {
    "%make-struct": make_struct_fn,
    "struct-ref": struct_ref,
    "struct-set!": struct_set,
    "struct-type-name": lambda s: s.struct_type.name,
    "call-method": call_method,
}


# ---------------------------------------------------------------------------
# Hash tables
# ---------------------------------------------------------------------------

def _require_hash_table(h, name):
    if not isinstance(h, LispHashTable):
        raise LispError("%s: not a hash table: %r" % (name, h))


def hash_table_set(h, key, value):
    _require_hash_table(h, "hash-table-set!")
    try:
        h.table[key] = value
    except TypeError:
        raise LispError("hash-table-set!: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))
    return NIL


def hash_table_ref(h, key, *default):
    _require_hash_table(h, "hash-table-ref")
    try:
        if key in h.table:
            return h.table[key]
    except TypeError:
        raise LispError("hash-table-ref: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))
    return default[0] if default else False


def hash_table_has(h, key):
    _require_hash_table(h, "hash-table-has?")
    try:
        return key in h.table
    except TypeError:
        raise LispError("hash-table-has?: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))


def hash_table_remove(h, key):
    _require_hash_table(h, "hash-table-remove!")
    h.table.pop(key, None)
    return NIL


def hash_table_for_each(f, h):
    _require_hash_table(h, "hash-table-for-each")
    for key, value in list(h.table.items()):
        apply_proc(f, [key, value])
    return NIL


HASH_TABLE_BUILTINS = {
    "make-hash-table": lambda: LispHashTable(),
    "hash-table?": lambda x: isinstance(x, LispHashTable),
    "hash-table-set!": hash_table_set,
    "hash-table-ref": hash_table_ref,
    "hash-table-has?": hash_table_has,
    "hash-table-remove!": hash_table_remove,
    "hash-table-count": lambda h: len(h.table),
    "hash-table-keys": lambda h: list_to_pairs(list(h.table.keys())),
    "hash-table-values": lambda h: list_to_pairs(list(h.table.values())),
    "hash-table->alist": lambda h: list_to_pairs([Pair(k, v) for k, v in h.table.items()]),
    "hash-table-for-each": hash_table_for_each,
}


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def string_search(haystack, needle, start=0):
    """(string-search haystack needle [start]) -- the index where needle first
    occurs in haystack, at or after start, or #f if it doesn't. (#f rather
    than -1, so (if (string-search ...) ...) works.)"""
    idx = str(haystack).find(str(needle), int(start))
    return idx if idx >= 0 else False


def string_split(s, sep=None):
    """(string-split s [sep]) -- s split at each occurrence of sep (so "a,,b"
    split on "," gives three pieces), or, with no sep, at runs of whitespace."""
    pieces = str(s).split(str(sep)) if sep is not None else str(s).split()
    return list_to_pairs([LispString(p) for p in pieces])


def string_to_number(s):
    """(string->number s) -- the number written in the string s, such as
    "42", "-3.5", or "1e6"."""
    text = str(s).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise LispError("string->number: %s isn't a number" % (to_string(s),))


def format_value(value, spec=""):
    """(format-value x [spec]) -- x as a string, laid out by spec, which is a
    Python format spec: e.g. ",.2f" (commas, 2 decimals), ">12" (right-
    justified in 12 characters), "^8" (centered), "<20" (left-justified).
    A number is formatted as a number; anything else (a string, date, list,
    ...) is formatted as its display text."""
    spec = str(spec)
    is_number = isinstance(value, numbers.Number) and not isinstance(value, bool)
    text_or_number = value if is_number else to_display_string(value)
    try:
        return LispString(format(text_or_number, spec))
    except ValueError as e:
        if not is_number:
            raise LispError('format: can\'t format %s with "%s" -- it isn\'t a number, so '
                            'only a width, alignment, and .N (maximum length) apply'
                            % (to_string(value), spec))
        raise LispError('format: can\'t format %s with "%s" (%s)' % (to_string(value), spec, e))


def lisp_format(template, *args):
    """(format template arg...) -- template with each {} or {:spec}
    placeholder replaced by the next argument, formatted as format-value
    formats it with that spec. {{ and }} stand for a literal { and }."""
    try:
        parts = list(string.Formatter().parse(str(template)))
    except ValueError as e:
        raise LispError("format: bad template %s (%s)" % (to_string(template), e))
    pieces = []
    next_arg = 0
    for literal_text, field_name, spec, conversion in parts:
        pieces.append(literal_text)
        if field_name is None:     # the text after the last placeholder
            continue
        if field_name != "" or conversion is not None:
            raise LispError("format: write each placeholder as {} or {:spec}, not {%s%s%s}"
                            % (field_name, "!" + conversion if conversion else "",
                               ":" + spec if spec else ""))
        if next_arg == len(args):
            raise LispError("format: the template has more placeholders than the %d argument%s given"
                            % (len(args), "" if len(args) == 1 else "s"))
        pieces.append(format_value(args[next_arg], spec))
        next_arg += 1
    if next_arg < len(args):
        raise LispError("format: %d arguments given, but the template has only %d placeholder%s"
                        % (len(args), next_arg, "" if next_arg == 1 else "s"))
    return LispString("".join(pieces))


STRING_BUILTINS = {
    "string-append": lambda *a: LispString("".join(a)),
    "to-string": lambda a: LispString(to_display_string(a)),
    "string-length": lambda s: len(s),
    "substring": lambda s, start, end=None: LispString(s[start:end]),
    "string=?": lambda a, b: a == b,
    "string<?": lambda a, b: a < b,
    "string>?": lambda a, b: a > b,
    "string->number": string_to_number,
    "number->string": lambda n: LispString(to_display_string(n)),
    "string->list": lambda s: list_to_pairs(list(s)),
    "list->string": lambda p: LispString("".join(list_items(p, "list->string"))),
    "string-upcase": lambda s: LispString(s.upper()),
    "string-downcase": lambda s: LispString(s.lower()),
    "string->symbol": lambda s: Symbol(s),
    "symbol->string": lambda s: LispString(str(s)),
    "string": lambda *chars: LispString("".join(chars)),
    "string-search": string_search,
    "string-contains?": lambda s, sub: str(sub) in str(s),
    "string-split": string_split,
    "string-replace": lambda s, old, new: LispString(str(s).replace(str(old), str(new))),
    "string-trim": lambda s: LispString(str(s).strip()),
    "format": lisp_format,
    "format-value": format_value,
}


# ---------------------------------------------------------------------------
# Vectors: making, reading, and changing them (the math is in lisp_vector_math.py)
# ---------------------------------------------------------------------------

def require_vector(v, name):
    if not isinstance(v, LispVector):
        raise LispError("%s: expected a vector, got %s" % (name, _brief(v)))


def make_vector_fn(*args):
    check_vector_elements(args, "vector")
    return LispVector(list(args))


def make_vector(n, fill=0):
    check_vector_elements([fill], "make-vector")
    return LispVector([fill] * n)


def check_index(v, i, name):
    """An error unless i is a position in the vector v: 0 to its length - 1."""
    if isinstance(i, bool) or not isinstance(i, int):
        raise LispError("%s: the index must be a whole number, not %s" % (name, _brief(i)))
    if not 0 <= i < len(v.items):
        raise LispError("%s: index %d is out of range -- the vector has %s"
                        % (name, i, plural(len(v.items), "element")))


def vector_ref(v, i):
    require_vector(v, "vector-ref")
    check_index(v, i, "vector-ref")
    return _lisp_scalar(v.items[i])


def vector_set(v, i, x):
    require_vector(v, "vector-set!")
    check_index(v, i, "vector-set!")
    check_vector_elements([x], "vector-set!")
    _vector_widen_for(v, x)
    v.items[i] = x
    return NIL


def vector_fill(v, x):
    check_vector_elements([x], "vector-fill!")
    _vector_widen_for(v, x)
    v.items[:] = x   # numpy broadcast -- fills every slot in one pass
    return NIL


def vector_map(f, v):
    require_vector(v, "vector-map")
    return LispVector([apply_proc(f, [_lisp_scalar(x)]) for x in v.items])


def vector_append(*vs):
    items = []
    for v in vs:
        require_vector(v, "vector-append")
        items.extend(v.items.tolist())
    return LispVector(items)


def vector_length(v):
    require_vector(v, "vector-length")
    return len(v.items)


def vector_to_list(v):
    require_vector(v, "vector->list")
    return list_to_pairs([_lisp_scalar(x) for x in v.items])


def list_to_vector(p):
    items = list_items(p, "list->vector")
    check_vector_elements(items, "list->vector")
    return LispVector(items)


def vector_iterate(first, count, f):
    """(vector-iterate first count f) -- a vector of `count` elements: first,
    (f first), (f (f first)), ... Works for dates too, e.g. with date-add-days."""
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
    """(vectors-shuffle (list v1 v2 ...) [seed]) -- new vectors, all shuffled
    into the SAME random order, so rows stay lined up across them -- e.g.
    before splitting x and y vectors into training and test sets."""
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
    # v.items[indices] builds the whole reordered array in one numpy step.
    shuffled = [LispVector(v.items[indices]) for v in vecs]
    return list_to_pairs(shuffled)


_NO_DEFAULT = object()  # sentinel: distinguishes "no default given" from "default given as NIL/0/etc."


def vectors_map(f, vec_list, default=_NO_DEFAULT):
    """(vectors-map f (list v1 v2 ...) [default]) -- a new vector whose j-th
    element is (f v1[j] v2[j] ... j); vector-map for several vectors at
    once. If the vectors differ in length, it stops at the shortest -- or,
    given `default`, runs to the longest, using default for missing values."""
    vecs = pairs_to_list(vec_list)
    if not vecs:
        raise LispError("vectors-map: at least one vector is required")
    for v in vecs:
        if not isinstance(v, LispVector):
            raise LispError("vectors-map: every element must be a vector")
    lengths = [len(v.items) for v in vecs]

    if default is _NO_DEFAULT:
        n = min(lengths)
        return LispVector([apply_proc(f, [_lisp_scalar(v.items[j]) for v in vecs] + [j])
                           for j in range(n)])

    n = max(lengths)
    result = []
    for j in range(n):
        row = [_lisp_scalar(v.items[j]) if j < len(v.items) else default for v in vecs] + [j]
        result.append(apply_proc(f, row))
    return LispVector(result)


VECTOR_BUILTINS = {
    "vector": make_vector_fn,
    "make-vector": make_vector,
    "vector-ref": vector_ref,
    "vector-set!": vector_set,
    "vector-length": vector_length,
    "vector-fill!": vector_fill,
    "vector-copy": lambda v: LispVector(v.items),
    "vector-map": vector_map,
    "vector-append": vector_append,
    "vector->list": vector_to_list,
    "list->vector": list_to_vector,
    "vector-iterate": vector_iterate,
    "vector-slice": vector_slice,
    "vector-take": vector_take,
    "vector-drop": vector_drop,
    "vectors-shuffle": vectors_shuffle,
    "vectors-map": vectors_map,
}


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

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


DATE_BUILTINS = {
    "date": date_fn,
    "date-year": date_year,
    "date-month": date_month,
    "date-day": date_day,
    "date->string": date_to_string,
    "string->date": string_to_date,
    "date-add-days": date_add_days,
}


# ---------------------------------------------------------------------------
# Output: where display/newline/print text goes
# ---------------------------------------------------------------------------

class OutputChannel:
    """Where one environment's display/newline/print text goes: normally the
    callback make_global_env() was given (the console, the GUI log, or a
    notebook cell), or a file while (redirect-output "file") is in effect."""

    def __init__(self, write_to_default):
        self.write_to_default = write_to_default
        self.file = None

    def write(self, text):
        if self.file is not None:
            self.file.write(text)
            self.file.flush()   # so the output survives even if the script errors out later
        else:
            self.write_to_default(text)

    def redirect_to_file(self, path, append):
        self.close_file()
        self.file = open(path, "a" if append else "w")

    def close_file(self):
        if self.file is not None:
            self.file.close()
            self.file = None

    def is_redirected(self):
        return self.file is not None


# ---------------------------------------------------------------------------
# Builtins that belong to one particular environment
# ---------------------------------------------------------------------------
#
# Each function below creates builtins that need something belonging to one
# environment -- the environment itself, or its output channel -- and
# returns them as a {lisp-name: function} table, the same shape as the
# tables above.

def make_output_builtins(out, markdown):
    """display, newline, print, redirect-output, reset-output, and
    display-markdown. `markdown` is the callback that renders Markdown
    (the Jupyter kernel supplies one), or None."""

    def lisp_display(x):
        out.write(to_display_string(x))
        return NIL

    def lisp_newline():
        out.write("\n")
        return NIL

    def lisp_print(x):
        out.write(to_display_string(x) + "\n")
        return NIL

    def redirect_output(path, append=False):
        """(redirect-output "path" [append?]) -- send display/newline/print output
        to a file (overwriting it, unless append? is #t) until (reset-output)."""
        out.redirect_to_file(str(path), is_true(append))
        return NIL

    def reset_output():
        """(reset-output) -- close the redirect-output file and go back to the
        console/GUI/notebook."""
        out.close_file()
        return NIL

    def display_markdown(text):
        """(display-markdown string) -- rendered as Markdown in a Jupyter
        notebook; elsewhere (console, GUI, redirected output) the Markdown text
        is written as it is, which is still readable."""
        if not isinstance(text, LispString):
            raise LispError("display-markdown: expected a string, got %r" % (text,))
        if markdown is not None and not out.is_redirected():
            markdown(str(text))
        else:
            out.write(str(text) + "\n")
        return NIL

    return {
        "display": lisp_display,
        "newline": lisp_newline,
        "print": lisp_print,
        "redirect-output": redirect_output,
        "reset-output": reset_output,
        "display-markdown": display_markdown,
    }


def make_display_columns_builtin(env, columns):
    """display-columns, which formats each value using the environment's
    current *column-number-format* and hands the table to `columns` (the
    GUI's Columns tab, a notebook table, or the console)."""

    def format_column_value(v, decimals=None):
        """One table cell as text: a number with `decimals` decimal places if
        given, otherwise formatted by *column-number-format* (a Python format
        string, "{:,.0f}" by default -- set! it to change every later table).
        Anything else is shown as display would show it."""
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

    def display_columns(name_value_pairs):
        """(display-columns pairs) -- show columns side by side: pairs is a list
        of (name . vector), or (name vector decimals). Where the table appears
        depends on the environment: the GUI's Columns tab, a notebook table, or
        a text table on the console."""
        data = [(name, [format_column_value(v, decimals) for v in items])
                for name, items, decimals in parse_column_pairs(name_value_pairs)]
        columns(data)
        return NIL

    return {"display-columns": display_columns}


def make_eval_builtins(env, out):
    """eval, macroexpand-1, macroexpand, print-macroexpansion, and load --
    each works in `env`, the top-level environment."""

    def lisp_eval(expr):
        """(eval expr) -- evaluate expr (code as data, e.g. built with quasiquote)
        in the top-level environment."""
        return seval(expr, env)

    def lisp_macroexpand_1(form):
        """(macroexpand-1 'form) -- if form is a call to a macro, expand it one
        level and return the new code without evaluating it; otherwise return
        form unchanged. Quote the form, as with eval."""
        if not isinstance(form, Pair) or not isinstance(form.car, Symbol):
            return form
        macro = env.lookup_or_none(form.car)
        if not isinstance(macro, Macro):
            return form
        return expand_macro(macro, pairs_to_list(form.cdr))

    def lisp_macroexpand(form):
        """(macroexpand 'form) -- keep expanding the outermost form while it's
        still a macro call. Macro calls nested inside the result aren't expanded."""
        while isinstance(form, Pair) and isinstance(form.car, Symbol) \
                and isinstance(env.lookup_or_none(form.car), Macro):
            form = lisp_macroexpand_1(form)
        return form

    def lisp_print_macroexpansion(form):
        """(print-macroexpansion 'form) -- print (macroexpand form), pretty-printed,
        without evaluating it."""
        out.write(pretty_print_string(lisp_macroexpand(form)) + "\n")
        return NIL

    def lisp_load(path):
        """(load "file.lsp") -- evaluate every form in a file, in the top-level
        environment, as if you'd typed them. See find_lisp_file for where it
        looks for the file."""
        run_file(find_lisp_file(path), env)
        return NIL

    return {
        "eval": lisp_eval,
        "macroexpand-1": lisp_macroexpand_1,
        "macroexpand": lisp_macroexpand,
        "print-macroexpansion": lisp_print_macroexpansion,
        "load": lisp_load,
    }


def make_introspection_builtins(env, out):
    """pretty-print, pretty-print-function-named, pretty-print-macro-named,
    defined-functions, defined-macros, and bound-variables -- each looks at
    the top-level environment `env`."""

    def lisp_pretty_print(x):
        """(pretty-print x) -- print x spread out, one element per line (see
        pretty_print_string). A procedure or macro is shown as its source."""
        if isinstance(x, Procedure):
            expr = reconstruct_procedure_source(x)
        elif isinstance(x, Macro):
            expr = reconstruct_macro_source(x)
        else:
            expr = x
        out.write(pretty_print_string(expr) + "\n")
        return NIL

    def lisp_pretty_print_function_named(name, value):
        if not isinstance(value, Procedure):
            raise LispError("pretty-print-function: %r is not a user-defined function" % (name,))
        out.write(pretty_print_string(reconstruct_procedure_source(value, name)) + "\n")
        return NIL

    def lisp_pretty_print_macro_named(name, value):
        if not isinstance(value, Macro):
            raise LispError("pretty-print-macro: %r is not a macro" % (name,))
        out.write(pretty_print_string(reconstruct_macro_source(value, name)) + "\n")
        return NIL

    def defined_functions():
        """(defined-functions) -- the names of the procedures you've defined (not
        builtins), in the order they were first defined."""
        return list_to_pairs([name for name in env if isinstance(env[name], Procedure)])

    def defined_macros():
        """(defined-macros) -- the names of the macros defined in the top-level
        environment, in the order they were defined: the standard macros
        (macros_init.lsp and loop.lsp) first, then any of yours."""
        return list_to_pairs([name for name in env if isinstance(env[name], Macro)])

    def bound_variables():
        """(bound-variables) -- the names bound to plain values (numbers, strings,
        lists, vectors, ...) rather than to procedures or macros."""
        return list_to_pairs([
            name for name in env
            if not isinstance(env[name], (Procedure, Macro)) and not callable(env[name])
        ])

    return {
        "pretty-print": lisp_pretty_print,
        "pretty-print-function-named": lisp_pretty_print_function_named,
        "pretty-print-macro-named": lisp_pretty_print_macro_named,
        "defined-functions": defined_functions,
        "defined-macros": defined_macros,
        "bound-variables": bound_variables,
    }


# ---------------------------------------------------------------------------
# The global environment
# ---------------------------------------------------------------------------

def print_columns_table(name_value_pairs, write):
    """The console's version of display-columns: a plain text table, each
    column right-justified to its widest cell (header included) so numbers
    line up on their ones place. The values are already formatted strings."""
    widths = [max([len(name)] + [len(str(v)) for v in values])
              for name, values in name_value_pairs]
    n_rows = max((len(values) for _, values in name_value_pairs), default=0)

    def row(cells):
        return "  ".join(str(c).rjust(w) for c, w in zip(cells, widths))

    lines = [row([name for name, _ in name_value_pairs])]
    for i in range(n_rows):
        lines.append(row(values[i] if i < len(values) else "" for _, values in name_value_pairs))
    write("\n".join(lines) + "\n")


def make_global_env(output=None, plot=None, columns=None, markdown=None):
    """Build a fresh global environment holding every built-in procedure.

    The four optional arguments say where this environment's output goes,
    so the same interpreter can run in the console, the GUI, or Jupyter:
      output    receives the text written by display/newline/print
      plot      receives each chart spec from plot-xy... (see lisp_charts)
      columns   receives each table from display-columns, as a list of
                (name, formatted-values) tuples
      markdown  receives each string from display-markdown
    Any left out get the plain console behavior: print the text, print a
    one-line chart summary, print a text table, print the raw Markdown.
    """
    if output is None:
        output = lambda text: print(text, end="")
    out = OutputChannel(output)

    if plot is None:
        plot = lambda spec: out.write(lisp_charts.chart_summary_text(spec))
    if columns is None:
        columns = lambda name_value_pairs: print_columns_table(name_value_pairs, out.write)

    env = Env()
    env.trace_emit = out.write      # verbose-mode trace lines go where display output does

    # Builtins that are the same in every environment.
    env.update(NUMBER_BUILTINS)
    env.update(BOOLEAN_BUILTINS)
    env.update(LIST_BUILTINS)
    env.update(PROCEDURE_BUILTINS)
    env.update(STRUCT_BUILTINS)
    env.update(HASH_TABLE_BUILTINS)
    env.update(STRING_BUILTINS)
    env.update(VECTOR_BUILTINS)
    env.update(DATE_BUILTINS)
    env.update(lisp_vector_math.BUILTINS)
    env.update(lisp_tables.BUILTINS)
    env.update(lisp_time_series.BUILTINS)
    env.update(lisp_csv.BUILTINS)
    env.update(lisp_regression.BUILTINS)
    env.update(lisp_sqlite.BUILTINS)
    env.update(lisp_fred.BUILTINS)
    env.update(lisp_http.BUILTINS)
    env.update(lisp_tastytrade.BUILTINS)
    env.update(lisp_sofr.BUILTINS)
    env.update(lisp_simplex.BUILTINS)

    # Builtins that belong to this environment.
    env.update(make_output_builtins(out, markdown))
    env.update(make_display_columns_builtin(env, columns))
    env.update(lisp_charts.make_chart_builtins(plot))
    env.update(make_eval_builtins(env, out))
    env.update(make_introspection_builtins(env, out))
    env.update(lisp_debug.make_debug_builtins(env, out))

    # Remember each builtin's Lisp name, for error messages (see
    # lisp_core.builtin_error).
    for name, value in env.items():
        if callable(value):
            builtin_names.setdefault(value, str(name))

    # A global variable: how display-columns formats numbers (see
    # format_column_value in make_display_columns_builtin).
    env[Symbol("*column-number-format*")] = LispString("{:,.0f}")

    load_standard_macros(env)
    return env


# ---------------------------------------------------------------------------
# The standard macros, the init file, and where load looks for files
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

# The standard macros, which make_global_env loads into every new
# environment: let, dolist, while, case, ... (macros_init.lsp), and then loop
# (loop.lsp, which uses them).
MACROS_INIT_FILE = os.path.join(HERE, "macros_init.lsp")
LOOP_FILE = os.path.join(HERE, "loop.lsp")
STANDARD_MACRO_FILES = (MACROS_INIT_FILE, LOOP_FILE)

# Your own definitions, which every new environment loads next. Set the
# LISP_INIT_FILE environment variable to use a different file.
DEFAULT_INIT_FILE = os.path.join(HERE, "init.lsp")

# Where load looks, after the current directory and LISP_PATH: the Lisp
# libraries, then the examples, that come with the interpreter.
LIBRARY_DIRECTORIES = (os.path.join(HERE, "lib"), os.path.join(HERE, "examples"))

_standard_macro_forms = []      # the standard macro files, parsed (once: parsing is the slow part)


def load_standard_macros(env):
    """Evaluate the standard macro files (macros_init.lsp and loop.lsp) in env."""
    if not _standard_macro_forms:
        for path in STANDARD_MACRO_FILES:
            with open(path) as f:
                _standard_macro_forms.extend(parse(f.read()))
    for form in _standard_macro_forms:
        seval(form, env)


def load_init_file(env, path=None):
    """Load the init file (path, or LISP_INIT_FILE, or init.lsp) into env.
    Called once for each new environment, before anything else runs. A
    missing file is silently skipped. An error in it (or an (abort)) is
    reported to stderr but doesn't stop the interpreter starting, so you can
    still fix it."""
    init_path = path or os.environ.get("LISP_INIT_FILE", DEFAULT_INIT_FILE)
    if not init_path or not os.path.exists(init_path):
        return
    try:
        run_file(init_path, env)
    except LispError as e:
        sys.stderr.write("warning: error loading init file %r: %s\n" % (init_path, e))
    except LispAbort:
        sys.stderr.write("warning: init file %r was aborted\n" % (init_path,))


def load_path():
    """The directories load searches after the current directory: those in
    the LISP_PATH environment variable (separated by colons, as in PATH),
    then LIBRARY_DIRECTORIES."""
    from_environment = [os.path.expanduser(d) for d in os.environ.get("LISP_PATH", "").split(os.pathsep) if d]
    return from_environment + list(LIBRARY_DIRECTORIES)


def find_lisp_file(path):
    """The file (load path) means: path itself, if it's absolute or is in the
    current directory; otherwise the first directory in load_path() that has
    it."""
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        candidates = [path]
    else:
        candidates = [path] + [os.path.join(d, path) for d in load_path()]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    if os.path.isabs(path):
        raise LispError("load: there's no file %s" % (path,))
    raise LispError("load: can't find %s in the current directory or in %s"
                    % (path, ", ".join(load_path())))
