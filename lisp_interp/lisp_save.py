"""Saving variables in a file, and defining them again later, for the Lisp
interpreter:

  (save-variables path name... [:leave-out-procedures #t])
                                  save each named variable's value in a
                                  JSON file (a macro, in macros_init.lsp,
                                  that calls %save-variables, below)
  (load-variables path)           define each variable saved in the file
                                  again, at the top level

THE FILE is JSON, which any program can read, and loading one runs no
code. It looks like this:

  {"format": "morris-lisp variables", "version": 1, "saved": "2026-10-05 14:30:00",
   "variables": {
    "rate": 0.05,
    "loans": {"table": [["id", ["a", "b"]], ["balance", [100, 90]]]}
   }}

JSON has fewer kinds of values than Lisp, so a value JSON has no kind for
is written as an object that says what it is:

  Lisp                        JSON
  42, 2.5                     42, 2.5
  nan (a missing number)      null
  inf, -inf                   {"number": "inf"}, {"number": "-inf"}
  "text"                      "text"
  #t, #f                      true, false
  (1 2 3), '()                [1, 2, 3], []
  (a . 1)                     {"pair": [{"symbol": "a"}, 1]}
  balance, :max-rows          {"symbol": "balance"}, {"keyword": ":max-rows"}
  #(1 2 3)                    {"vector": [1, 2, 3]}
  2024-01-02                  {"date": "2024-01-02"}
  a table                     {"table": [["id", ["a", "b"]], ["balance", [100, 90]]]}
  a hash table                {"hash-table": [[key, value], ...]}
  a struct                    {"struct": "point", "slots": {"x": 1, "y": 2}}
  a regression model          {"model": {"kind": "linear", "coefficients": [...], ...}}

A procedure can't be saved: it holds its environment, not just data. Nor
can a SQLite connection, or a map's outlines (census-shapes reads those
again quickly, from the files it keeps). But with :leave-out-procedures
#t, a struct's slots that hold procedures are left out of the file, and
load-variables gives them their defaults: it makes each struct with its
constructor, make-NAME, which gives every slot it isn't given its default.
"""

import datetime
import json
import math
import os

import numpy as np

import lisp_regression
import lisp_tables
from lisp_core import (
    Keyword, LispDate, LispError, LispHashTable, LispString, LispStruct, LispVector, NIL, Pair, Procedure, Symbol,
    _brief, _date_from_pydate, _lisp_scalar, apply_proc, is_true, keyword_options, list_to_pairs, pairs_to_list,
)

FORMAT = "morris-lisp variables"
VERSION = 1

# The kinds of value written as an object that says what it is.
TAGS = ("number", "symbol", "keyword", "date", "vector", "table", "pair", "hash-table", "struct", "model")


# ---------------------------------------------------------------------------
# Lisp values as JSON's, and back
# ---------------------------------------------------------------------------

def is_proper_list(p):
    """Whether p is a list ending in '(), rather than in a dotted pair."""
    while isinstance(p, Pair):
        p = p.cdr
    return p is NIL


def is_procedure(value):
    """Whether value is a procedure, as procedure? says: a lambda or a builtin."""
    return isinstance(value, Procedure) or callable(value)


def with_article(word):
    """word, with a or an before it."""
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def is_table(value):
    """Whether value is a table: a list of (name . vector) columns, all the
    same length, each named by a string. (A list of (symbol . vector) pairs
    is saved as an ordinary list, so its symbols stay symbols.)"""
    lengths = set()
    p = value
    while isinstance(p, Pair):
        column = p.car
        if not (isinstance(column, Pair) and isinstance(column.car, str) and not isinstance(column.car, Symbol)
                and isinstance(column.cdr, LispVector)):
            return False
        lengths.add(len(column.cdr.items))
        p = p.cdr
    return p is NIL and len(lengths) == 1


def encode(value, leave_out_procedures=False):
    """A Lisp value as JSON's (see the table at the top). With
    leave_out_procedures, a struct's slots that hold procedures are left
    out. Raises LispError, saying what's wrong, for a value that isn't data."""
    if isinstance(value, np.generic):
        value = _lisp_scalar(value)
    if value is NIL:
        return []
    if isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return {"number": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, Keyword):
        return {"keyword": str(value)}
    if isinstance(value, Symbol):
        return {"symbol": str(value)}
    if isinstance(value, str):
        return str(value)
    if isinstance(value, LispDate):
        return {"date": value.date.isoformat()}
    if isinstance(value, LispVector):
        return {"vector": [encode(_lisp_scalar(x), leave_out_procedures) for x in value.items]}
    if isinstance(value, Pair):
        if is_table(value):
            return {"table": [[str(column.car), [encode(_lisp_scalar(x), leave_out_procedures)
                                                 for x in column.cdr.items]]
                              for column in pairs_to_list(value)]}
        if is_proper_list(value):
            return [encode(x, leave_out_procedures) for x in pairs_to_list(value)]
        return {"pair": [encode(value.car, leave_out_procedures), encode(value.cdr, leave_out_procedures)]}
    if isinstance(value, LispHashTable):
        return {"hash-table": [[encode(key, leave_out_procedures), encode(v, leave_out_procedures)]
                               for key, v in value.table.items()]}
    if isinstance(value, LispStruct):
        return {"struct": str(value.struct_type.name), "slots": encode_slots(value, leave_out_procedures)}
    if isinstance(value, (lisp_regression.LispModel, lisp_regression.LispSplineModel)):
        return {"model": encode_plain(lisp_regression.model_data(value))}
    raise LispError("it is or holds %s, which isn't data -- data is numbers, strings, symbols, lists, vectors, "
                    "tables, dates, hash tables, structs, and regression models" % (_brief(value),))


def encode_slots(struct, leave_out_procedures):
    """A struct's slots, as JSON's: an object with a member for each slot,
    except, with leave_out_procedures, the slots that hold procedures."""
    slots = {}
    for slot, value in struct.values.items():
        if is_procedure(value):
            if leave_out_procedures:
                continue
            raise LispError("it is or holds %s whose %s slot holds %s, which isn't data -- to leave a struct's "
                            "procedures out of the file, give save-variables :leave-out-procedures #t"
                            % (with_article(str(struct.struct_type.name)), slot, _brief(value)))
        slots[str(slot)] = encode(value, leave_out_procedures)
    return slots


def encode_plain(data):
    """A model's plain data (see lisp_regression.model_data) as JSON's:
    its dicts and lists as they are, and the values in them as encode
    writes them."""
    if isinstance(data, dict):
        return {key: encode_plain(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [encode_plain(value) for value in data]
    return encode(data)


def decode(data, env, row_types):
    """The Lisp value encode wrote as data. env is where to find a saved
    struct's type; row_types keeps the types made for table rows."""
    if data is None:
        return math.nan
    if isinstance(data, (bool, int, float)):
        return data
    if isinstance(data, str):
        return LispString(data)
    if isinstance(data, list):
        return list_to_pairs([decode(x, env, row_types) for x in data])
    if not isinstance(data, dict):
        raise LispError("not a value save-variables writes: %r" % (data,))
    if "number" in data:
        if data["number"] not in ("inf", "-inf"):
            raise LispError("not a number save-variables writes: %r" % (data["number"],))
        return math.inf if data["number"] == "inf" else -math.inf
    if "symbol" in data:
        return Symbol(data["symbol"])
    if "keyword" in data:
        return Keyword(data["keyword"])
    if "date" in data:
        return _date_from_pydate(datetime.date.fromisoformat(data["date"]))
    if "vector" in data:
        return LispVector([decode(x, env, row_types) for x in data["vector"]])
    if "table" in data:
        return list_to_pairs([Pair(LispString(name), LispVector([decode(x, env, row_types) for x in values]))
                              for name, values in data["table"]])
    if "pair" in data:
        car, cdr = data["pair"]
        return Pair(decode(car, env, row_types), decode(cdr, env, row_types))
    if "hash-table" in data:
        table = LispHashTable()
        for key, value in data["hash-table"]:
            table.table[decode(key, env, row_types)] = decode(value, env, row_types)
        return table
    if "struct" in data:
        return decode_struct(data, env, row_types)
    if "model" in data:
        return lisp_regression.model_from_data(decode_plain(data["model"], env, row_types))
    raise LispError("not a value save-variables writes: %s" % json.dumps(data)[:100])


def decode_plain(data, env, row_types):
    """encode_plain's JSON, as plain data again."""
    if isinstance(data, list):
        return [decode_plain(value, env, row_types) for value in data]
    if isinstance(data, dict) and not any(tag in data for tag in TAGS):
        return {key: decode_plain(value, env, row_types) for key, value in data.items()}
    return decode(data, env, row_types)


def decode_struct(data, env, row_types):
    """A saved struct, made by its type's constructor, make-NAME, as defstruct
    has defined it now. So a slot the file doesn't have -- one that held a
    procedure, left out by :leave-out-procedures, or one the defstruct has
    gained since -- gets its default, just as make-NAME gives it.

    A table's rows (see table-rows) have no constructor: they're structs of
    a type made for each table, so one is made for them here, the same for
    each set of columns."""
    name, slots = data["struct"], data["slots"]
    struct_type = env.lookup_or_none(Symbol("%%struct-type-%s" % name))
    if struct_type is None and name == "row":
        if tuple(slots) not in row_types:
            row_types[tuple(slots)] = lisp_tables.row_type(list(slots))
        return LispStruct(row_types[tuple(slots)],
                          {Symbol(slot): decode(value, env, row_types) for slot, value in slots.items()})
    constructor = env.lookup_or_none(Symbol("make-%s" % name))
    if struct_type is None or constructor is None:
        raise LispError("there's no %s struct type -- define it with defstruct first" % name)
    slot_names = [str(slot) for slot, _ in struct_type.slots]
    unknown = [slot for slot in slots if slot not in slot_names]
    if unknown:
        raise LispError("the saved %s has slots %s doesn't have now: %s"
                        % (name, with_article(name), ", ".join(unknown)))
    arguments = []
    for slot in slot_names:
        if slot in slots:
            arguments += [Keyword(":" + slot), decode(slots[slot], env, row_types)]
    return apply_proc(constructor, arguments)


# ---------------------------------------------------------------------------
# save-variables and load-variables
# ---------------------------------------------------------------------------

def save_variables(path, pairs, *options):
    """(%save-variables path pairs [:leave-out-procedures #t]) -- what
    (save-variables path name...) becomes: write each (name . value) of
    pairs in the JSON file at path, replacing the file if there is one, and
    return the names. The file is written only once every value is known to
    be data, so a value that can't be saved leaves an earlier file as it
    was."""
    who = "save-variables"
    options = keyword_options(options, ["leave-out-procedures"], who)
    leave_out_procedures = is_true(options.get("leave-out-procedures", False))
    names, lines = [], []
    for pair in pairs_to_list(pairs):
        name = str(pair.car)
        try:
            data = encode(pair.cdr, leave_out_procedures)
        except LispError as e:
            raise LispError("%s: can't save %s: %s" % (who, name, e))
        except RecursionError:
            raise LispError("%s: can't save %s: it holds itself (a list, vector, or struct inside itself)"
                            % (who, name))
        names.append(Symbol(name))
        lines.append("  %s: %s" % (json.dumps(name), json.dumps(data, ensure_ascii=False, allow_nan=False)))
    saved = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = ('{"format": %s, "version": %d, "saved": %s,\n "variables": {\n%s\n }}\n'
            % (json.dumps(FORMAT), VERSION, json.dumps(saved), ",\n".join(lines)))
    path = os.path.expanduser(str(path))
    try:
        with open(path + ".part", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(path + ".part", path)
    except OSError as e:
        raise LispError("%s: couldn't write %s: %s" % (who, path, e.strerror or e))
    return list_to_pairs(names)


def read_saved_variables(path, env, who):
    """The (name, value) of each variable saved in the file at path."""
    path = os.path.expanduser(str(path))
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except OSError as e:
        raise LispError("%s: couldn't read %s: %s" % (who, path, e.strerror or e))
    except ValueError as e:
        raise LispError("%s: %s isn't a JSON file: %s" % (who, path, e))
    if not (isinstance(document, dict) and document.get("format") == FORMAT):
        raise LispError("%s: %s isn't a file save-variables wrote" % (who, path))
    if document.get("version", 0) > VERSION:
        raise LispError("%s: %s was written by a newer version of save-variables (version %s)"
                        % (who, path, document.get("version")))
    row_types = {}
    values = []
    for name, data in document["variables"].items():
        try:
            values.append((Symbol(name), decode(data, env, row_types)))
        except (LispError, ValueError, KeyError, TypeError) as e:
            raise LispError("%s: can't load %s: %s" % (who, name, e))
    return values


def make_save_builtins(env):
    """%save-variables, and load-variables, which defines the variables in
    env, the top-level environment."""

    def load_variables(path):
        """(load-variables path) -- define again, at the top level, each
        variable that save-variables saved in the file at path. Returns their
        names. Nothing is defined unless every value can be read."""
        values = read_saved_variables(path, env, "load-variables")
        for name, value in values:
            env[name] = value
        return list_to_pairs([name for name, _ in values])

    return {
        "%save-variables": save_variables,
        "load-variables": load_variables,
    }
