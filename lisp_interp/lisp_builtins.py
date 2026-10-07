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
import itertools
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
    apply_proc, builtin_names, check_numbers, lisp_equal, plural, check_vector_elements, expand_macro, gensym,
    get_verbose_level, is_true, keyword_options,
    list_to_pairs, pairs_to_list, parse, pretty_print_string,
    reconstruct_macro_source, reconstruct_procedure_source, run_file, seval,
    set_verbose_level, throw_to, to_display_string, to_string,
)
import lisp_alpha_vantage
import lisp_bea
import lisp_bls
import lisp_calendar
import lisp_census
import lisp_charts
import lisp_clock
import lisp_csv
import lisp_debug
import lisp_fdic
import lisp_finance
import lisp_fred
import lisp_http
import lisp_investment_paths
import lisp_maps
import lisp_regex
import lisp_regression
import lisp_save
import lisp_schwab
import lisp_sec
import lisp_simplex
import lisp_sofr
import lisp_sqlite
import lisp_stratify
import lisp_tables
import lisp_tastytrade
import lisp_time_series
import lisp_vector_math


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


def parity(n, who):
    """n modulo 2 -- 0 or 1 -- for a whole number n (4, or 4.0)."""
    check_numbers((n,), who)
    if isinstance(n, float) and not n.is_integer():
        raise LispError("%s: expected a whole number, got %r" % (who, n))
    return n % 2


def check_number(x, who):
    check_numbers((x,), who)
    return x


def whole_numbers(numbers, who):
    """numbers, which must be whole (4, or 4.0), as Python ints."""
    check_numbers(numbers, who)
    for n in numbers:
        if isinstance(n, float) and not n.is_integer():
            raise LispError("%s: expected whole numbers, got %r" % (who, n))
    return [int(n) for n in numbers]


def lisp_gcd(*numbers):
    """(gcd a b ...) -- the greatest common divisor of whole numbers; 0 for none."""
    return math.gcd(*whole_numbers(numbers, "gcd"))


def lisp_lcm(*numbers):
    """(lcm a b ...) -- the least common multiple of whole numbers; 1 for none."""
    return math.lcm(*whole_numbers(numbers, "lcm"))


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


def lisp_erf(x):
    """(erf x) -- the error function; for a vector, of each element."""
    if isinstance(x, LispVector):
        return lisp_vector_math.unary("erf", x, np.vectorize(math.erf, otypes=[float]))
    return math.erf(x)


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


def signum(x):
    """(signum x) -- -1, 0, or 1, as x is negative, zero, or positive (as a
    floating-point number if x is one); for a vector, of each element."""
    if isinstance(x, LispVector):
        return lisp_vector_math.unary("signum", x, np.sign)
    check_numbers([x], "signum")
    sign = (x > 0) - (x < 0)
    return float(sign) if isinstance(x, float) else sign


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
    mask, compared element by element (see lisp_vector_math.compare). #t and
    #f are an error: they aren't numbers, though Python would treat them as
    1 and 0, making (= #f 0) true."""
    def compare(*args):
        for a in args:
            if isinstance(a, bool):
                raise LispError("%s: %s isn't a number -- to test for #t or #f, use eq?"
                                % (name, to_string(a)))
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
    "signum": signum,
    "gcd": lisp_gcd,
    "lcm": lisp_lcm,
    "even?": lambda n: parity(n, "even?") == 0,
    "odd?": lambda n: parity(n, "odd?") == 1,
    "zero?": lambda x: check_number(x, "zero?") == 0,
    "positive?": lambda x: check_number(x, "positive?") > 0,
    "negative?": lambda x: check_number(x, "negative?") < 0,
    "min": lisp_min,
    "max": lisp_max,
    "sqrt": lisp_sqrt,
    "pow": lisp_pow,
    "log": lisp_log,
    "exp": lisp_exp,
    "erf": lisp_erf,
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
    "eq?": lambda a, b: a is b or lisp_equal(a, b),
    "equal?": lisp_equal,
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


def make_cxr(name, cxr_name=None):
    """The function called name, which does what a c...r name such as cadr
    says: car and cdr applied right to left, as the letters between c and r
    say, so (cadr x) is (car (cdr x)), the second element of a list.
    cxr_name is that c...r name, if name isn't one itself."""
    steps = (cxr_name or name)[1:-1][::-1]      # "cadr" -> "da": first cdr, then car

    def cxr(x):
        value = x
        for step in steps:
            if not isinstance(value, Pair):
                raise LispError("%s: %s doesn't have that part -- it would take the %s of %s"
                                % (name, to_string(x), "car" if step == "a" else "cdr", to_string(value)))
            value = value.car if step == "a" else value.cdr
        return value
    return cxr


def cxr_names():
    """caar, cadr, cdar, cddr, caaar, ..., cddddr: every name with two to
    four a's and d's between c and r."""
    names = []
    for length in (2, 3, 4):
        for letters in itertools.product("ad", repeat=length):
            names.append("c" + "".join(letters) + "r")
    return names


CXR_BUILTINS = {name: make_cxr(name) for name in cxr_names()}

# first, second, ...: the same as car, cadr, ..., with names that say which
# element they are. rest is cdr.
POSITION_BUILTINS = {
    "first": make_cxr("first", "car"),
    "second": make_cxr("second", "cadr"),
    "third": make_cxr("third", "caddr"),
    "fourth": make_cxr("fourth", "cadddr"),
    "rest": make_cxr("rest", "cdr"),
}


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


def lisp_map(f, *sequences):
    """(map f seq ...) -- (f x) for each element x of seq: a list for a list,
    a vector for a vector. Given several lists (or several vectors),
    (f x y ...) for their elements in step, stopping at the end of the
    shortest: (map + '(1 2) '(10 20)) is (11 22)."""
    if not sequences:
        raise LispError("map: expected at least 1 list or vector after the procedure")
    if all(isinstance(s, LispVector) for s in sequences):
        columns = [[_lisp_scalar(x) for x in v.items] for v in sequences]
        return LispVector([apply_proc(f, list(args)) for args in zip(*columns)])
    if any(isinstance(s, LispVector) for s in sequences):
        raise LispError("map: give it all lists or all vectors, not a mixture")
    lists = [list_items(s, "map") for s in sequences]
    return list_to_pairs([apply_proc(f, list(args)) for args in zip(*lists)])


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


def lisp_last(lst, n=1):
    """(last lst [n]) -- the end of lst: its last n elements (1 unless
    given), as a list, as in Common Lisp. So (last '(1 2 3)) is (3), and
    (car (last lst)) is the last element."""
    items = list_items(lst, "last")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise LispError("last: n must be a whole number, 0 or more, not %s" % (_brief(n),))
    tail = lst
    for _ in range(max(0, len(items) - n)):
        tail = tail.cdr
    return tail


def lisp_butlast(lst, n=1):
    """(butlast lst [n]) -- a new list of all but the last n elements of lst
    (1 unless given): (butlast '(1 2 3)) is (1 2)."""
    items = list_items(lst, "butlast")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise LispError("butlast: n must be a whole number, 0 or more, not %s" % (_brief(n),))
    return list_to_pairs(items[:max(0, len(items) - n)])


def list_tail(lst, n):
    """(list-tail lst n) -- lst without its first n elements: lst's own
    pairs from the nth on, not a copy."""
    items = list_items(lst, "list-tail")
    n = int(n)
    if n < 0 or n > len(items):
        raise LispError("list-tail: index %d out of range (0..%d)" % (n, len(items)))
    tail = lst
    for _ in range(n):
        tail = tail.cdr
    return tail


def lisp_assoc(key, alist):
    """(assoc key alist) -- the first (key . value) pair in alist whose key is
    equal to `key`, or #f if there's none. Returns #f rather than '()
    because '() counts as true in this Lisp; only #f is false."""
    for entry in list_items(alist, "assoc"):
        if not isinstance(entry, Pair):
            raise LispError("assoc: alist element is not a pair: %r" % (entry,))
        if lisp_equal(entry.car, key):
            return entry
    return False


def lisp_member(x, lst):
    """(member x lst) -- the part of lst starting at the first element equal
    to x (lst's own pairs, not a copy), or #f if there's none."""
    p = lst
    while isinstance(p, Pair):
        if lisp_equal(p.car, x):
            return p
        p = p.cdr
    if p is not NIL:
        raise LispError("member: expected a list, got %s" % _brief(lst))
    return False


# More sequence functions, as Common Lisp has them. Each takes a list or a
# vector, and those that return a sequence return the same kind.

def same_kind(seq, items):
    """items, a Python list, as the same kind of sequence as seq: a vector
    for a vector, otherwise a list."""
    return LispVector(items) if isinstance(seq, LispVector) else list_to_pairs(items)


def lisp_remove(item, seq):
    """(remove item seq) -- seq without the elements equal? to item."""
    return same_kind(seq, [x for x in sequence_items(seq, "remove") if not lisp_equal(x, item)])


def lisp_remove_if(f, seq):
    """(remove-if f seq) -- seq without the elements x for which (f x) is
    true: the opposite of filter."""
    return same_kind(seq, [x for x in sequence_items(seq, "remove-if") if not is_true(apply_proc(f, [x]))])


def lisp_count(item, seq):
    """(count item seq) -- how many elements of seq are equal? to item."""
    return sum(1 for x in sequence_items(seq, "count") if lisp_equal(x, item))


def lisp_count_if(f, seq):
    """(count-if f seq) -- how many elements x of seq make (f x) true."""
    return sum(1 for x in sequence_items(seq, "count-if") if is_true(apply_proc(f, [x])))


def elements_in_step(sequences, who):
    """The elements of one or more sequences, in step, as map takes them: a
    list of argument lists, stopping at the end of the shortest."""
    if not sequences:
        raise LispError("%s: expected at least 1 list or vector after the procedure" % who)
    return [list(args) for args in zip(*[sequence_items(s, who) for s in sequences])]


def lisp_some(f, *sequences):
    """(some f seq ...) -- the first true value of (f x ...) for the elements
    of seq (taken in step, given several), or #f if there's none."""
    for args in elements_in_step(sequences, "some"):
        value = apply_proc(f, args)
        if is_true(value):
            return value
    return False


def lisp_every(f, *sequences):
    """(every f seq ...) -- #t if (f x ...) is true for every element of seq
    (taken in step, given several), else #f. #t for no elements at all."""
    return all(is_true(apply_proc(f, args)) for args in elements_in_step(sequences, "every"))


def lisp_find_if(f, seq):
    """(find-if f seq) -- the first element x of seq for which (f x) is
    true, or #f if there's none."""
    for x in sequence_items(seq, "find-if"):
        if is_true(apply_proc(f, [x])):
            return x
    return False


def lisp_position(item, seq):
    """(position item seq) -- the index of the first element of seq equal?
    to item, counting from 0, or #f if there's none."""
    for i, x in enumerate(sequence_items(seq, "position")):
        if lisp_equal(x, item):
            return i
    return False


def lisp_position_if(f, seq):
    """(position-if f seq) -- the index of the first element x of seq for
    which (f x) is true, or #f if there's none."""
    for i, x in enumerate(sequence_items(seq, "position-if")):
        if is_true(apply_proc(f, [x])):
            return i
    return False


def distinct_key(x):
    """What tells x apart from other elements, as equal? does, for a set:
    its kind and its value. (Python alone would call #t equal to 1, and a
    string equal to the symbol with the same name.)"""
    if isinstance(x, bool):
        return ("boolean", x)
    if isinstance(x, (int, float)):
        return ("number", x)              # 1 and 1.0 are equal?, and so is their key
    return (type(x).__name__, x)


def distinct(items):
    """items with each element once (as equal? sees them), in the order
    they first appear. Numbers, strings, symbols, and dates are checked
    with a set, so long sequences of them are quick; lists one by one."""
    seen, seen_unhashable, result = set(), [], []
    for x in items:
        try:
            key = distinct_key(x)
            if key in seen:
                continue
            seen.add(key)
        except TypeError:
            if any(lisp_equal(x, y) for y in seen_unhashable):
                continue
            seen_unhashable.append(x)
        result.append(x)
    return result


def lisp_remove_duplicates(seq):
    """(remove-duplicates seq) -- seq with each element once, where it first
    appears."""
    return same_kind(seq, distinct(sequence_items(seq, "remove-duplicates")))


def lisp_union(a, b):
    """(union a b) -- every element of a or b, once each, in the order they
    first appear (a's first)."""
    return same_kind(a, distinct(sequence_items(a, "union") + sequence_items(b, "union")))


def lisp_intersection(a, b):
    """(intersection a b) -- the elements of a that are also in b, once each,
    in a's order."""
    in_b = sequence_items(b, "intersection")
    return same_kind(a, distinct([x for x in sequence_items(a, "intersection")
                                  if any(lisp_equal(x, y) for y in in_b)]))


def lisp_set_difference(a, b):
    """(set-difference a b) -- the elements of a that aren't in b, once each,
    in a's order."""
    in_b = sequence_items(b, "set-difference")
    return same_kind(a, distinct([x for x in sequence_items(a, "set-difference")
                                  if not any(lisp_equal(x, y) for y in in_b)]))


def lisp_append_map(f, *sequences):
    """(append-map f seq ...) -- the lists (f x ...) returns for the elements
    of seq, appended into one: (append-map (lambda (x) (list x x)) '(1 2)) is
    (1 1 2 2)."""
    results = [apply_proc(f, args) for args in elements_in_step(sequences, "append-map")]
    return lisp_append(*results) if results else NIL


def lisp_for_each(f, *sequences):
    """(for-each f seq ...) -- call (f x ...) for each element of seq (in step,
    given several), for what it does; returns '()."""
    for args in elements_in_step(sequences, "for-each"):
        apply_proc(f, args)
    return NIL


def lisp_iota(count, start=0, step=1):
    """(iota count [start step]) -- a list of count numbers: start (0 unless
    given), start + step, start + 2 step, ...: (iota 4) is (0 1 2 3)."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise LispError("iota: count must be a whole number, 0 or more, not %s" % (_brief(count),))
    check_numbers((start, step), "iota")
    return list_to_pairs([start + i * step for i in range(count)])


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
    "last": lisp_last,
    "butlast": lisp_butlast,
    "assoc": lisp_assoc,
    "member": lisp_member,
    "null?": lambda p: p is NIL,
    "pair?": lambda p: isinstance(p, Pair),
    "list?": lambda p: p is NIL or isinstance(p, Pair),
    "map": lisp_map,
    "filter": lisp_filter,
    "sort": lisp_sort,
    "reduce": lisp_reduce,
    "remove": lisp_remove,
    "remove-if": lisp_remove_if,
    "count": lisp_count,
    "count-if": lisp_count_if,
    "some": lisp_some,
    "every": lisp_every,
    "find-if": lisp_find_if,
    "position": lisp_position,
    "position-if": lisp_position_if,
    "remove-duplicates": lisp_remove_duplicates,
    "union": lisp_union,
    "intersection": lisp_intersection,
    "set-difference": lisp_set_difference,
    "append-map": lisp_append_map,
    "for-each": lisp_for_each,
    "iota": lisp_iota,
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


def check_key(h, key, name):
    """An error unless h is a hash table and key isn't #t or #f. (Python
    treats True and False as the numbers 1 and 0, so #t would find 1's
    entry. The other keys a hash table can't have -- lists, vectors, structs
    -- Python itself refuses.)"""
    _require_hash_table(h, name)
    if isinstance(key, bool):
        raise LispError("%s: #t and #f can't be hash-table keys -- use a number, string, "
                        "symbol, keyword, or date" % name)


def hash_table_set(h, key, value):
    check_key(h, key, "hash-table-set!")
    try:
        h.table[key] = value
    except TypeError:
        raise LispError("hash-table-set!: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))
    return NIL


def hash_table_ref(h, key, *default):
    check_key(h, key, "hash-table-ref")
    try:
        if key in h.table:
            return h.table[key]
    except TypeError:
        raise LispError("hash-table-ref: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))
    return default[0] if default else False


def hash_table_has(h, key):
    check_key(h, key, "hash-table-has?")
    try:
        return key in h.table
    except TypeError:
        raise LispError("hash-table-has?: not a hashable key (lists/vectors/structs "
                        "can't be hash-table keys): %r" % (key,))


def hash_table_remove(h, key):
    check_key(h, key, "hash-table-remove!")
    h.table.pop(key, None)
    return NIL


def hash_table_for_each(f, h):
    _require_hash_table(h, "hash-table-for-each")
    for key, value in list(h.table.items()):
        apply_proc(f, [key, value])
    return NIL


def hash_table_copy(h):
    """(hash-table-copy h) -- a new hash table with h's keys and values (the
    values themselves aren't copied)."""
    _require_hash_table(h, "hash-table-copy")
    copy = LispHashTable()
    copy.table.update(h.table)
    return copy


def hash_table_update(h, key, f, *default):
    """(hash-table-update! h key f [default]) -- set key's value to (f value),
    where value is key's value now -- or default, if key has none (an error
    if there's no default either). Returns the new value:
    (hash-table-update! counts word (lambda (n) (+ n 1)) 0) counts a word."""
    check_key(h, key, "hash-table-update!")
    if hash_table_has(h, key):
        value = h.table[key]
    elif default:
        value = default[0]
    else:
        raise LispError("hash-table-update!: %s isn't in the table, and there's no default" % (_brief(key),))
    new_value = apply_proc(f, [value])
    h.table[key] = new_value
    return new_value


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
    "hash-table-copy": hash_table_copy,
    "hash-table-update!": hash_table_update,
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


def string_join(strings, separator=" "):
    """(string-join strings [separator]) -- the strings in a list or vector
    joined into one, with separator (a space, unless given) between them.
    Anything that isn't a string is joined as display shows it, so a list
    of symbols makes a sentence."""
    return LispString(str(separator).join(str(to_display_string(x))
                                          for x in sequence_items(strings, "string-join")))


def read_line(prompt=""):
    """(read-line [prompt]) -- a line typed by the user, as a string (without
    the newline), after showing prompt; #f at the end of the input (Ctrl-D
    at a terminal). In a Jupyter notebook, the notebook asks for the line."""
    try:
        return LispString(input(str(to_display_string(prompt))))
    except EOFError:
        return False


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
    "string-starts-with?": lambda s, prefix: str(s).startswith(str(prefix)),
    "string-ends-with?": lambda s, suffix: str(s).endswith(str(suffix)),
    "string-split": string_split,
    "string-replace": lambda s, old, new: LispString(str(s).replace(str(old), str(new))),
    "string-trim": lambda s: LispString(str(s).strip()),
    "string-join": string_join,
    "read-line": read_line,
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

def make_output_builtins(out, markdown, html):
    """display, newline, print, redirect-output, reset-output,
    display-markdown, and display-html. `markdown` and `html` are the
    callbacks that render Markdown and HTML (the Jupyter kernel supplies
    them), or None."""

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

    def display_html(html_text, text=None):
        """(display-html html [text]) -- html rendered in a Jupyter notebook;
        elsewhere (console, GUI, redirected output), text is written instead:
        the same thing without HTML. Without text, the HTML itself is written."""
        for name, value in (("html", html_text), ("text", text)):
            if value is not None and not isinstance(value, LispString):
                raise LispError("display-html: expected a string for %s, got %r" % (name, value))
        if html is not None and not out.is_redirected():
            html(str(html_text))
        else:
            out.write(str(html_text if text is None else text) + "\n")
        return NIL

    return {
        "display": lisp_display,
        "newline": lisp_newline,
        "print": lisp_print,
        "redirect-output": redirect_output,
        "reset-output": reset_output,
        "display-markdown": display_markdown,
        "display-html": display_html,
    }


DISPLAY_TABLE_MAX_ROWS = 20    # display-table's :max-rows, unless it's given
HIDDEN = "hide"                 # the format that leaves a column out of display-table


def make_display_table_builtin(out, show_table):
    """display-table, which formats a table's values as text and hands them
    to show_table (the GUI's Table tab, a notebook, or the console). What it
    hands over is a list of (column name, the cells' text, alignment)
    tuples; the alignment is "right" for a column of numbers, else "left"."""

    def display_table(data, *arguments):
        """(display-table table [formats] [:max-rows n]) -- show a table, or a
        list of rows (see table-rows), with each column's numbers laid out by
        a format spec, e.g. '(("balance" ",.2f") ("rate" ".3%")). A column
        whose format is hide isn't shown. Shows the first :max-rows rows (20,
        unless given; #f for all of them), and a note if there are more."""
        formats = NIL
        if arguments and not isinstance(arguments[0], Keyword):
            formats, arguments = arguments[0], arguments[1:]
        options = keyword_options(arguments, ["max-rows"], "display-table")
        max_rows = options.get("max-rows", DISPLAY_TABLE_MAX_ROWS)
        if max_rows is not False and (isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 0):
            raise LispError("display-table: :max-rows must be a whole number, 0 or more, or #f for every row, not %s"
                            % (_brief(max_rows),))

        columns = lisp_tables.table_columns(lisp_tables.table_or_rows(data, "display-table"), "display-table")
        specs = format_specs(formats)
        n_rows = lisp_tables.row_count(columns)
        shown = n_rows if max_rows is False else min(n_rows, max_rows)
        cells = [(name, [cell_text(value, specs.get(name), name) for value in lisp_tables.column_values(v)[:shown]],
                  column_alignment(v))
                 for name, v in columns if specs.get(name) != HIDDEN]
        if not cells:
            out.write("(every column is hidden)\n" if columns else "(an empty table)\n")
            return NIL
        show_table(cells)
        if shown < n_rows:
            out.write("(the first %s of %s rows -- :max-rows shows more)\n"
                      % (format(shown, ","), format(n_rows, ",")))
        return NIL

    return {"display-table": display_table}


def format_specs(formats):
    """display-table's formats -- a list of (name spec), or (name . spec) --
    as a dict from column name to spec. A format for a column the table
    doesn't have is simply not used, so one list of formats can serve every
    view of the same data. The spec hide (a symbol, or the string "hide")
    becomes "hide", like any other spec."""
    specs = {}
    for entry in list_items(formats, "display-table"):
        if not isinstance(entry, Pair):
            raise LispError('display-table: each format must be (name spec), such as ("balance" ",.2f"), not %s'
                            % (_brief(entry),))
        spec = entry.cdr.car if isinstance(entry.cdr, Pair) else entry.cdr
        specs[str(entry.car)] = str(spec)
    return specs


def cell_text(value, spec, column_name):
    """One table cell as text: blank if the value is missing (NaN, or '() in
    a column of strings or dates); laid out by spec if there is one (as
    format-value does it); otherwise as display shows it."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if spec is None:
        return str(to_display_string(value))
    try:
        return str(format_value(value, spec))
    except LispError as e:
        raise LispError("display-table: column %s: %s" % (column_name, e))


def column_alignment(v):
    """"right" for a column of numbers (so they line up on their last
    digit), "left" for anything else."""
    values = [x for x in lisp_tables.column_values(v) if x is not None]
    if all(lisp_vector_math.is_number(x) for x in values):
        return "right"
    return "left"


def print_table(columns, write):
    """The console's display-table: a plain text table, each column as wide
    as its widest cell, numbers right-justified and text left-justified."""
    widths = [max([len(name)] + [len(cell) for cell in cells]) for name, cells, _ in columns]
    n_rows = max((len(cells) for _, cells, _ in columns), default=0)

    def line(texts):
        parts = [text.rjust(width) if align == "right" else text.ljust(width)
                 for text, width, (_, _, align) in zip(texts, widths, columns)]
        return "  ".join(parts).rstrip()

    lines = [line([name for name, _, _ in columns]), line(["-" * width for width in widths])]
    for i in range(n_rows):
        lines.append(line([cells[i] for _, cells, _ in columns]))
    write("\n".join(lines) + "\n")


def markdown_text(text):
    """text, to show as it is in a Markdown table: each character Markdown
    gives a meaning to -- a | ends a cell, a pair of $ makes a formula in a
    notebook, * and _ make emphasis, ... -- backslashed, which Markdown
    shows as the character itself."""
    return "".join("\\" + c if c in "\\`*_$|~<>" else c for c in text)


def markdown_table(columns):
    """display-table's table as Markdown text, which is how a notebook shows
    it: numbers right-aligned, text left-aligned."""
    def line(texts):
        return "| " + " | ".join(markdown_text(text) for text in texts) + " |"

    n_rows = max((len(cells) for _, cells, _ in columns), default=0)
    lines = [line([name for name, _, _ in columns]),
             "|" + "|".join("---:" if align == "right" else ":---" for _, _, align in columns) + "|"]
    for i in range(n_rows):
        lines.append(line([cells[i] for _, cells, _ in columns]))
    return "\n".join(lines)


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

def make_global_env(output=None, plot=None, table=None, markdown=None, html=None):
    """Build a fresh global environment holding every built-in procedure.

    The five optional arguments say where this environment's output goes,
    so the same interpreter can run in the console, the GUI, or Jupyter:
      output    receives the text written by display/newline/print
      plot      receives each chart spec from plot-xy... (see lisp_charts)
      table     receives each table from display-table, as a list of
                (name, cell texts, alignment) tuples
      markdown  receives each string from display-markdown
      html      receives the HTML from each display-html
    Any left out get the plain console behavior: print the text, print a
    one-line chart summary, print a text table, print the raw Markdown,
    print display-html's plain text.
    """
    if output is None:
        output = lambda text: print(text, end="")
    out = OutputChannel(output)

    if plot is None:
        plot = lambda spec: out.write(lisp_charts.chart_summary_text(spec))
    if table is None:
        table = lambda columns: print_table(columns, out.write)

    env = Env()
    env.trace_emit = out.write      # verbose-mode trace lines go where display output does

    # Builtins that are the same in every environment.
    env.update(NUMBER_BUILTINS)
    env.update(BOOLEAN_BUILTINS)
    env.update(LIST_BUILTINS)
    env.update(CXR_BUILTINS)
    env.update(POSITION_BUILTINS)
    env.update(PROCEDURE_BUILTINS)
    env.update(STRUCT_BUILTINS)
    env.update(HASH_TABLE_BUILTINS)
    env.update(STRING_BUILTINS)
    env.update(lisp_regex.BUILTINS)
    env.update(VECTOR_BUILTINS)
    env.update(DATE_BUILTINS)
    env.update(lisp_vector_math.BUILTINS)
    env.update(lisp_tables.BUILTINS)
    env.update(lisp_stratify.BUILTINS)
    env.update(lisp_time_series.BUILTINS)
    env.update(lisp_csv.BUILTINS)
    env.update(lisp_regression.BUILTINS)
    env.update(lisp_sqlite.BUILTINS)
    env.update(lisp_fred.BUILTINS)
    env.update(lisp_sec.BUILTINS)
    env.update(lisp_fdic.BUILTINS)
    env.update(lisp_census.BUILTINS)
    env.update(lisp_bls.BUILTINS)
    env.update(lisp_bea.BUILTINS)
    env.update(lisp_maps.BUILTINS)
    env.update(lisp_schwab.BUILTINS)
    env.update(lisp_alpha_vantage.BUILTINS)
    env.update(lisp_http.BUILTINS)
    env.update(lisp_tastytrade.BUILTINS)
    env.update(lisp_sofr.BUILTINS)
    env.update(lisp_simplex.BUILTINS)
    env.update(lisp_investment_paths.BUILTINS)
    env.update(lisp_finance.BUILTINS)
    env.update(lisp_clock.BUILTINS)
    env.update(lisp_calendar.BUILTINS)

    # Builtins that belong to this environment.
    env.update(make_output_builtins(out, markdown, html))
    env.update(make_display_table_builtin(out, table))
    env.update(lisp_charts.make_chart_builtins(plot))
    env.update(make_eval_builtins(env, out))
    env.update(lisp_save.make_save_builtins(env))
    env.update(make_introspection_builtins(env, out))
    env.update(lisp_debug.make_debug_builtins(env, out))

    # Remember each builtin's Lisp name, for error messages (see
    # lisp_core.builtin_error).
    for name, value in env.items():
        if callable(value):
            builtin_names.setdefault(value, str(name))

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
