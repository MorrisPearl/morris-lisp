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

import csv
import datetime
import math
import os
import random
import sys

import numpy as np

from lisp_core import (
    Env, Keyword, LispDate, LispError, LispHashTable, LispString, LispStruct,
    LispVector, Macro, NIL, Pair, Procedure, Symbol,
    _date_from_pydate, _lisp_scalar, _narrow_vector_result, _vector_widen_for,
    apply_proc, check_numbers, check_vector_elements, debug_repl, eval_body,
    eval_default, expand_macro, gensym, get_verbose_level, is_true,
    list_to_pairs, pairs_to_list, parse, pretty_print_string,
    reconstruct_macro_source, reconstruct_procedure_source, run_file, seval,
    set_verbose_level, to_display_string, to_string,
)
import lisp_charts
import lisp_fred
import lisp_regression
import lisp_sofr
import lisp_sqlite
import lisp_tastytrade


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

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
    """(< a b c) is true if a < b and b < c -- the same for =, >, <=, >=."""
    for a, b in zip(args, args[1:]):
        if not op(a, b):
            return False
    return True


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
    "mod": lambda a, b: a % b,
    "quotient": lambda a, b: int(a / b),
    "remainder": lambda a, b: a % b,
    "abs": abs,
    "min": lambda *a: min(a),
    "max": lambda *a: max(a),
    "sqrt": math.sqrt,
    "pow": math.pow,
    "log": math.log,
    "exp": math.exp,
    "erf": math.erf,
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


def list_tail(lst, n):
    items = pairs_to_list(lst)
    n = int(n)
    if n < 0 or n > len(items):
        raise LispError("list-tail: index %d out of range (0..%d)" % (n, len(items)))
    return list_to_pairs(items[n:])


def lisp_assoc(key, alist):
    """(assoc key alist) -- the first (key . value) pair in alist whose key is
    equal to `key`, or #f if there's none. Returns #f rather than '()
    because '() counts as true in this Lisp; only #f is false."""
    for entry in pairs_to_list(alist):
        if not isinstance(entry, Pair):
            raise LispError("assoc: alist element is not a pair: %r" % (entry,))
        if entry.car == key:
            return entry
    return False


def lisp_member(x, lst):
    """(member x lst) -- the part of lst starting at the first element equal
    to x, or #f if there's none."""
    items = pairs_to_list(lst)
    for i, item in enumerate(items):
        if item == x:
            return list_to_pairs(items[i:])
    return False


LIST_BUILTINS = {
    "cons": lambda a, b: Pair(a, b),
    "car": car,
    "cdr": cdr,
    "list": lambda *args: list_to_pairs(list(args)),
    "append": lisp_append,
    "reverse": lambda p: list_to_pairs(list(reversed(pairs_to_list(p)))),
    "length": lambda p: len(pairs_to_list(p)),
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
    return apply_proc(f, list(leading) + pairs_to_list(last))


def lisp_gensym(*base):
    """(gensym ["prefix"]) -- a new symbol that can't collide with any name in
    the program, for macros that need temporary names."""
    return gensym(str(base[0]) if base else "g")


def lisp_error(*args):
    raise LispError(" ".join(to_display_string(a) for a in args))


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


STRING_BUILTINS = {
    "string-append": lambda *a: LispString("".join(a)),
    "to-string": lambda a: LispString(to_display_string(a)),
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
    "string-search": string_search,
    "string-contains?": lambda s, sub: str(sub) in str(s),
    "string-split": string_split,
    "string-replace": lambda s, old, new: LispString(str(s).replace(str(old), str(new))),
    "string-trim": lambda s: LispString(str(s).strip()),
}


# ---------------------------------------------------------------------------
# Vectors (fixed-size, mutable; hold numbers and/or dates)
# ---------------------------------------------------------------------------

def make_vector_fn(*args):
    check_vector_elements(args, "vector")
    return LispVector(list(args))


def make_vector(n, fill=0):
    check_vector_elements([fill], "make-vector")
    return LispVector([fill] * n)


def vector_ref(v, i):
    if not isinstance(v, LispVector):
        raise LispError("vector-ref: not a vector: %r" % (v,))
    return _lisp_scalar(v.items[i])


def vector_set(v, i, x):
    if not isinstance(v, LispVector):
        raise LispError("vector-set!: not a vector: %r" % (v,))
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
    return LispVector([apply_proc(f, [_lisp_scalar(v.items[j])]) for j in range(len(v.items))])


def vector_append(*vs):
    items = []
    for v in vs:
        items.extend(v.items.tolist())
    return LispVector(items)


def list_to_vector(p):
    items = pairs_to_list(p)
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


def vector_add(a, b):
    # Elementwise a+b, as long as the shorter vector (documented behavior).
    n = min(len(a.items), len(b.items))
    return LispVector(_narrow_vector_result(a.items[:n] + b.items[:n]))


def vector_sub(a, b):
    n = min(len(a.items), len(b.items))
    return LispVector(_narrow_vector_result(a.items[:n] - b.items[:n]))


def vector_scale(v, s):
    return LispVector(_narrow_vector_result(v.items * s))


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
    "vector-length": lambda v: len(v.items),
    "vector-fill!": vector_fill,
    "vector-copy": lambda v: LispVector(v.items),
    "vector-map": vector_map,
    "vector-append": vector_append,
    "vector->list": lambda v: list_to_pairs(v.items.tolist()),
    "list->vector": list_to_vector,
    "vector-iterate": vector_iterate,
    "vector-sum": lambda v: _lisp_scalar(v.items.sum()),
    "vector-add": vector_add,
    "vector-sub": vector_sub,
    "vector-scale": vector_scale,
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
# CSV files: load-csv, write-columns-csv
# ---------------------------------------------------------------------------

def load_csv_fn(filename, has_header=True):
    """(load-csv filename [has-header?]) -- a CSV file's columns as vectors:
    (cons headers-list vectors-list). A column is kept if every non-blank
    value is a number, or every one is a YYYY-MM-DD date; other columns are
    skipped. A row is kept only if it has a value in every kept column, so
    the vectors stay the same length and lined up."""
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


def parse_column_pairs(name_value_pairs):
    """Read the column list display-columns and write-columns-csv take: each
    element is (name . vector), or (name vector decimals) to give that
    column a number of decimal places. Returns (name, items,
    decimals-or-None) tuples."""
    out = []
    for p in pairs_to_list(name_value_pairs):
        name = str(p.car)
        rest = p.cdr
        if isinstance(rest, LispVector):
            out.append((name, rest.items.tolist(), None))
        elif isinstance(rest, Pair) and isinstance(rest.car, LispVector):
            decimals = rest.cdr.car if isinstance(rest.cdr, Pair) else None
            out.append((name, rest.car.items.tolist(), decimals))
        else:
            raise LispError(
                "expected (name . vector) or (name vector decimals), got %r" % (p,))
    return out


def write_columns_csv_fn(filename, name_value_pairs):
    """(write-columns-csv filename pairs) -- write columns (the same list
    display-columns takes) to a CSV file: a header row of names, then one
    row per index. Numbers are plain CSV numbers, rounded to the column's
    decimals if it has any. A shorter column is padded with empty cells."""
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


CSV_BUILTINS = {
    "load-csv": load_csv_fn,
    "write-columns-csv": write_columns_csv_fn,
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
        environment, as if you'd typed them."""
        run_file(str(path), env)
        return NIL

    return {
        "eval": lisp_eval,
        "macroexpand-1": lisp_macroexpand_1,
        "macroexpand": lisp_macroexpand,
        "print-macroexpansion": lisp_print_macroexpansion,
        "load": lisp_load,
    }


# The small convenience macros every environment starts with, so you can
# write the NAME directly -- (pretty-print-function my-func) -- instead of
# quoting it. They're ordinary defmacro macros; defined-macros leaves them
# out, so it lists only the macros you wrote yourself.
BOOTSTRAP_MACROS = {
    "pretty-print-function": "(defmacro pretty-print-function (name) `(pretty-print-function-named ',name ,name))",
    "pretty-print-macro": "(defmacro pretty-print-macro (name) `(pretty-print-macro-named ',name ,name))",
    "debug-function": "(defmacro debug-function (name) `(debug-function-named ',name))",
    "undebug-function": "(defmacro undebug-function (name) `(undebug-function-named ',name))",
}


def make_introspection_builtins(env, out):
    """pretty-print, pretty-print-function-named, pretty-print-macro-named,
    defined-functions, defined-macros, bound-variables,
    debug-function-named, and undebug-function-named -- each looks at (or
    changes) the top-level environment `env`."""

    # State for debug-function/undebug-function, kept per environment so
    # separate sessions in the same process don't share it.
    debug_call_stack = []      # names of debug-function-wrapped calls currently in progress
    debug_originals = {}       # name -> the original Procedure, so undebug-function can restore it

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
        if not isinstance(value, Procedure) and name in debug_originals:
            value = debug_originals[name]  # show the real definition even while debug-wrapped
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
        """(defined-macros) -- the names of the macros you've defined (not the
        BOOTSTRAP_MACROS every environment starts with)."""
        return list_to_pairs([
            name for name in env
            if isinstance(env[name], Macro) and name not in BOOTSTRAP_MACROS
        ])

    def bound_variables():
        """(bound-variables) -- the names bound to plain values (numbers, strings,
        lists, vectors, ...) rather than to procedures or macros."""
        return list_to_pairs([
            name for name in env
            if not isinstance(env[name], (Procedure, Macro)) and not callable(env[name])
        ])

    def debug_function_named(name):
        """(debug-function name) -- from now on, every call to the function opens
        a debug REPL (see debug_repl) before its body runs, with the arguments
        already bound, so you can look at them or set! them, then (continue).
        It also prints the chain of debug-function calls in progress; type
        (backtrace) for the full chain of calls."""
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
                return eval_body(proc.body, new_env, call=(proc, list(args)))
            finally:
                debug_call_stack.pop()

        env[name] = wrapper
        return NIL

    def undebug_function_named(name):
        """(undebug-function name) -- undo debug-function. Does nothing if the
        function isn't being debugged."""
        if name in debug_originals:
            env[name] = debug_originals.pop(name)
        return NIL

    return {
        "pretty-print": lisp_pretty_print,
        "pretty-print-function-named": lisp_pretty_print_function_named,
        "pretty-print-macro-named": lisp_pretty_print_macro_named,
        "defined-functions": defined_functions,
        "defined-macros": defined_macros,
        "bound-variables": bound_variables,
        "debug-function-named": debug_function_named,
        "undebug-function-named": undebug_function_named,
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
    env.update(CSV_BUILTINS)
    env.update(lisp_regression.BUILTINS)
    env.update(lisp_sqlite.BUILTINS)
    env.update(lisp_fred.BUILTINS)
    env.update(lisp_tastytrade.BUILTINS)
    env.update(lisp_sofr.BUILTINS)

    # Builtins that belong to this environment.
    env.update(make_output_builtins(out, markdown))
    env.update(make_display_columns_builtin(env, columns))
    env.update(lisp_charts.make_chart_builtins(plot))
    env.update(make_eval_builtins(env, out))
    env.update(make_introspection_builtins(env, out))

    # A global variable: how display-columns formats numbers (see
    # format_column_value in make_display_columns_builtin).
    env[Symbol("*column-number-format*")] = LispString("{:,.0f}")

    for source in BOOTSTRAP_MACROS.values():
        for expr in parse(source):
            seval(expr, env)

    return env


# ---------------------------------------------------------------------------
# The startup init file
# ---------------------------------------------------------------------------

# The file every new environment loads first (see load_init_file). Set
# the LISP_INIT_FILE environment variable to use a different file.
DEFAULT_INIT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init.lsp")


def load_init_file(env, path=None):
    """Load the init file (init.lsp, or LISP_INIT_FILE) into env, if it exists.
    Called once for each new environment, before anything else runs. A
    missing file is silently skipped. An error in it is reported to stderr
    but doesn't stop the interpreter starting, so you can still fix it."""
    path = path or os.environ.get("LISP_INIT_FILE", DEFAULT_INIT_FILE)
    if not path or not os.path.exists(path):
        return
    try:
        run_file(path, env)
    except LispError as e:
        sys.stderr.write("warning: error loading init file %r: %s\n" % (path, e))
