"""The built-in procedures, and make_global_env(), which builds the global
environment every Lisp program runs in.

Most builtins are ordinary module-level functions, grouped by topic below,
each group ending in a table (a dict) mapping Lisp names to functions --
NUMBER_BUILTINS, LIST_BUILTINS, and so on. A few builtins need something
that belongs to ONE particular environment -- the environment itself
(eval, load), or where its output goes (display, redirect-output) -- so
they're created per environment by the make_..._builtins() functions near
the bottom. make_global_env() puts all of them, plus the tables from the
other modules (lisp_regression.BUILTINS, lisp_sqlite.BUILTINS, ...), into
a fresh environment.

To add builtins of your own, see "Adding your own builtins" in
lisp_interpreter_reference.md.
"""

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
    """(sort seq [key]) -- a NEW list or vector with seq's elements in
    ascending order (seq itself is not changed); the sort is stable.
    `key`, if given, is a procedure of one argument that returns what
    to compare for each element -- a number or string, anything `<`
    can compare -- so (sort people person-age) orders people by age."""
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
    """(assoc key alist) -- alist is a list of (key . value) PAIRS
    (built with cons, e.g. (list (cons 'a 1) (cons 'b 2)) -- NOT the
    (key value) two-element-list shape `let`-style bindings use).
    Returns the matching (key . value) pair (so its value is
    (cdr (assoc key alist))), or #f -- not '() -- if none match, so
    (if (assoc ...) ...) behaves correctly (this Lisp's '() is
    truthy, same as Scheme's; #f is the only false value)."""
    for entry in pairs_to_list(alist):
        if not isinstance(entry, Pair):
            raise LispError("assoc: alist element is not a pair: %r" % (entry,))
        if entry.car == key:
            return entry
    return False


def lisp_member(x, lst):
    """(member x lst) -- the sublist of lst starting at the first
    element equal? to x, or #f (not '()) if none match -- see
    assoc's docstring for why #f specifically."""
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
    """(apply f arg1 arg2 ... args) -- call f with arg1, arg2, ...
    as individual arguments, followed by the ELEMENTS of the final
    argument `args` (a list). (apply f lst) -- just the final list,
    no individual leading arguments -- is the common special case."""
    if not args:
        raise LispError("apply: expected at least 2 arguments (a procedure and a list)")
    *leading, last = args
    return apply_proc(f, list(leading) + pairs_to_list(last))


def lisp_gensym(*base):
    """(gensym ["prefix"]) -- a symbol guaranteed not to collide with
    any name in the program, for writing your own hygienic macros by
    hand (see gensym()'s docstring in lisp_core.py)."""
    return gensym(str(base[0]) if base else "g")


def lisp_error(*args):
    raise LispError(" ".join(to_display_string(a) for a in args))


def lisp_verbose(*args):
    """(verbose) -- the current verbosity level. (verbose n) -- set it
    (0 off, 1 procedure names, 2 + arguments and return values, 3 +
    macro expansions; #f/#t mean 0/1) and return the PREVIOUS level, so
    you can restore it: (define old (verbose 2)) ... (verbose old).
    See "Call tracing" in lisp_core.py."""
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
    """(call-method accessor instance arg...) -- calls the
    "method" (an ordinary lambda) stored in whichever slot
    `accessor` reads off `instance` -- `accessor` is a struct
    accessor FUNCTION VALUE (e.g. animal-speak, evaluated normally,
    not quoted), not a symbol naming one. Passes `instance` as the
    method's own first argument (its "self"), followed by any
    extra `args`:
        (call-method animal-speak d)
    is exactly
        ((animal-speak d) d)
    just without writing `d` twice -- an ordinary function (no
    macro needed, and so no risk of evaluating `instance` twice
    either): Lisp already evaluates every argument exactly once."""
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
    """(string-search haystack needle [start]) -- the index of the
    first occurrence of needle in haystack at or after start, or #f
    (not -1, not '()) if there isn't one -- so 0 is safe to test the
    same way (if (string-search ...) ...) is if the whole match sits
    at the very start, unlike -1, and unlike '() (which is truthy
    here, same as Scheme -- see assoc's docstring)."""
    idx = str(haystack).find(str(needle), int(start))
    return idx if idx >= 0 else False


def string_split(s, sep=None):
    """(string-split s [sep]) -- s split on every occurrence of sep
    (an exact substring -- consecutive separators produce an empty
    piece between them, e.g. splitting "a,,b" on "," gives 3 pieces),
    or, with sep omitted, on runs of whitespace with no empty pieces
    (Python's plain str.split() convention -- handy for tokenizing
    free-form text)."""
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


def vector_add(a, b):
    # Elementwise a+b, truncated to the shorter vector's length if
    # they differ (documented behavior -- not an error). a.items[:n]
    # + b.items[:n] is a single vectorized numpy operation, not a
    # Python-level loop.
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
    # v.items[indices] -- numpy "fancy indexing" with a list of
    # positions -- builds the whole permuted array in one vectorized
    # pass; LispVector(...)'s ndarray branch then makes its own
    # independent copy of that (fresh, not aliased to v.items).
    shuffled = [LispVector(v.items[indices]) for v in vecs]
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


def parse_column_pairs(name_value_pairs):
    """Shared by display-columns and write-columns-csv: each element
    of `name_value_pairs` is either (name . vector) -- a plain cons,
    decimals unspecified -- or (name vector decimals), a 3-element
    list picking a per-column decimal-places count instead of
    relying on the global *column-number-format* (this is the shape
    column_engine.lsp's calculate-all builds, from each column
    struct's `decimals` slot). Returns a list of (name, items,
    decimals-or-None)."""
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


CSV_BUILTINS = {
    "load-csv": load_csv_fn,
    "write-columns-csv": write_columns_csv_fn,
}


# ---------------------------------------------------------------------------
# Output: where display/newline/print text goes
# ---------------------------------------------------------------------------

class OutputChannel:
    """Where one environment's display/newline/print text goes. Normally
    that's the callback make_global_env() was given (the console, the GUI
    log, or a notebook cell); (redirect-output "file") sends it to a file
    instead, until (reset-output) switches back."""

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
        """(redirect-output "path.txt" [append?]) -- send everything
        display/newline/print (and the console's chart summary) write from
        now on to the given file instead of the console/GUI log, until
        (reset-output) is called. Opens in overwrite mode by default; pass
        #t for append. Closes whatever file a PRIOR redirect-output call
        opened first, so redirecting twice in a row doesn't leak an open
        file handle."""
        out.redirect_to_file(str(path), is_true(append))
        return NIL

    def reset_output():
        """(reset-output) -- undo redirect-output: close its file (if
        one is open) and go back to writing to the console/GUI log."""
        out.close_file()
        return NIL

    def display_markdown(text):
        """(display-markdown string) -- shows `string` as Markdown. In a
        Jupyter notebook it renders (tables, headings, bold, ...); with no
        renderer available (console, GUI, redirect-output) the raw
        Markdown text is written as ordinary output instead, which is
        still readable -- a Markdown table is legible as plain text."""
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

    def display_columns(name_value_pairs):
        """(display-columns pairs) -- pairs is a list of (name . vector)
        conses, or (name vector decimals) lists for a per-column decimal-
        places count (see column_engine.lsp's `decimals` slot); each
        becomes one displayed column, headed by name, in the order given,
        with every value rendered through format_column_value.
        Deliberately generic: doesn't know anything about the `column`
        struct some higher-level Lisp library (e.g. a column_engine.lsp-
        style modeling library) may define on top of this -- that mapping
        from a struct instance to a (name . vector) / (name vector
        decimals) entry happens entirely in Lisp."""
        data = [(name, [format_column_value(v, decimals) for v in items])
                for name, items, decimals in parse_column_pairs(name_value_pairs)]
        columns(data)
        return NIL

    return {"display-columns": display_columns}


def make_eval_builtins(env, out):
    """eval, macroexpand-1, macroexpand, print-macroexpansion, and load --
    each works in `env`, the top-level environment."""

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
        out.write(pretty_print_string(lisp_macroexpand(form)) + "\n")
        return NIL

    def lisp_load(path):
        """(load "path/to/file.lsp") -- read and evaluate every top-level
        form in a file, in this SAME global environment, so its
        definitions become available afterward exactly as if you'd typed
        them yourself. Uses the same run_file() the interpreter's own
        startup init-file loading does (see load_init_file)."""
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
        """(defined-functions) -- every name currently bound (in the top-
        level environment) to a user-defined Procedure -- i.e. something
        created by `lambda`/`define`, NOT a built-in. There's no separate
        registry to keep in sync: this just filters the live environment,
        so it's always exactly correct, in the order things were first
        defined (a redefinition doesn't move its entry)."""
        return list_to_pairs([name for name in env if isinstance(env[name], Procedure)])

    def defined_macros():
        """(defined-macros) -- every name currently bound to a
        user-defined Macro (leaving out BOOTSTRAP_MACROS, above). Same
        live-filter approach as defined-functions()."""
        return list_to_pairs([
            name for name in env
            if isinstance(env[name], Macro) and name not in BOOTSTRAP_MACROS
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

    def debug_function_named(name):
        """(debug-function name) [macro -- see BOOTSTRAP_MACROS]: wraps
        the named function so every future call opens a debug REPL
        (debug_repl) BEFORE running the body, in an environment where the
        function's own parameters are already bound to this call's real
        argument values -- inspect or (via set!) change them, then
        (continue) to actually run the body with whatever's in scope at
        that point. Also prints the chain of debug-function-wrapped calls
        currently in progress, as a lightweight "how was this called, and
        from where" trace, just of the functions you've explicitly asked
        to watch. For the FULL chain of procedure calls, type (backtrace)
        at the debug prompt (see "Call tracing" in lisp_core.py)."""
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
        """(undebug-function name) [macro]: restore the original,
        un-wrapped definition debug-function saved before wrapping it.
        Does nothing if `name` was never debug-function-wrapped."""
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

# Loaded automatically into every fresh environment at startup (batch
# mode, the console REPL, the GUI, and Jupyter) -- see load_init_file().
# Defaults to init.lsp next to this file; override with the
# LISP_INIT_FILE environment variable if you'd rather keep it somewhere
# else (e.g. a dotfile in your home directory).
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
