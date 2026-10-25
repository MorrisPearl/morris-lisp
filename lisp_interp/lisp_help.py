"""Help from inside the interpreter: (help name), (documentation name), and
(apropos text), and what the Jupyter kernel shows for Tab (the names that
begin with what was typed) and for Shift-Tab (the help of the name at the
cursor).

The documentation of a name comes from the first of these that has it:
  1. Its docstring. A Lisp function's is the string its body begins with,
     (define (f x) "What f does." ...); a builtin's is its Python docstring,
     which begins with how it is called, "(sort seq [key]) -- ...". A
     defgeneric's is the string after its parameters.
  2. For a library function that is not loaded yet (a stand-in made by
     lazy-load, see lib/autoloads.lsp), its definition in the library's file,
     which is read, not loaded: its parameters and docstring, or, for a
     function that a defstruct makes, the defstruct and the comment under it.
  3. The section of a manual whose heading is how it is called, such as
     "#### `(dolist (var list) body...)`": the special forms, the standard
     macros, and the builtins that have no docstring of their own.
"""
import inspect
import os
import re

from lisp_core import (
    NIL, SPECIAL_FORMS, GenericFunction, LispError, LispString, Macro, Pair, Procedure, Symbol,
    _param_spec_from, builtin_names, pairs_to_list, parse, struct_function_docs, to_string,
)

HERE = os.path.dirname(os.path.abspath(__file__))

# The manuals that help looks in, in this order, in the doc directory beside this one.
DOC_DIRECTORY = os.path.join(HERE, "..", "doc")
MANUALS = ["lisp_interpreter_reference.md", "lisp_library_reference.md", "lisp_cmo_manual.md"]

# The most lines of a manual's section that help shows.
MOST_MANUAL_LINES = 40

# The docstring of a lazy-load's stand-in (see lazy-load in macros_init.lsp).
STAND_IN_DOCSTRING = re.compile(r"^Loads (\S+), which defines (\S+), and calls it\.$")


# ---------------------------------------------------------------------------
# The documentation of a name
# ---------------------------------------------------------------------------

def documentation(env, name):
    """The documentation of the name (a string) in the environment, as text: how it is called, then what it does. None if there
    is none. (See the top of the file for where it comes from.)"""
    value = env.lookup_or_none(Symbol(name))
    if value is None:
        if name in SPECIAL_FORMS:
            return manual_section(name) or "%s is a special form: see \"Special forms and standard macros\" in lisp_interpreter_reference.md." % name
        return None
    if isinstance(value, (Procedure, Macro)):
        file = stand_in_file(value) if isinstance(value, Procedure) else None
        if file is not None:
            return library_documentation(name, file)
        text = docstring(value.body)
        if text and text.startswith("("):          # (a docstring that says how it is called itself, as make-point's does)
            return text
        if text:
            return joined(usage(name, value), text)
        return manual_section(name) or usage(name, value)
    if isinstance(value, GenericFunction):
        return joined(to_string(Pair(Symbol(name), value.parameters)),
                      value.documentation or "A generic function: its method is chosen by the type of its first argument.")
    if callable(value):
        python_doc = inspect.cleandoc(value.__doc__) if getattr(value, "__doc__", None) else ""
        if python_doc.startswith("("):
            return python_doc
        return manual_section(name) or python_doc or "%s is a builtin, which has no documentation." % name
    return "%s is a variable. Its value is %s" % (name, brief(value))


def usage(name, procedure):
    """How a Lisp function or macro is called, from its parameters: (name a b &key (c 1))."""
    parameters = _param_spec_from(procedure.params, procedure.rest_param, procedure.keyword_specs, procedure.optional_specs)
    return to_string(Pair(Symbol(name), parameters))


def docstring(body):
    """The docstring of a body, a list of expressions: its first expression, if it is a string and there is more after it (a
    body that is only a string returns it); otherwise None."""
    if len(body) > 1 and isinstance(body[0], (str, LispString)):
        return str(body[0])
    return None


def joined(how_called, text):
    """How a name is called, and below it the text, each line set in by two spaces."""
    return how_called + "\n" + "\n".join("  " + line if line else "" for line in text.splitlines())


def brief(value):
    """The value as the interpreter prints it, cut short if it is long."""
    text = to_string(value)
    return text if len(text) <= 200 else text[:200] + " ..."


# ---------------------------------------------------------------------------
# Library functions that are not loaded yet
# ---------------------------------------------------------------------------

def stand_in_file(procedure):
    """The library file that the procedure is a lazy-load's stand-in for, or None if it is not a stand-in."""
    text = docstring(procedure.body)
    found = STAND_IN_DOCSTRING.match(text) if text else None
    return found.group(1) if found else None


def library_documentation(name, file):
    """The documentation of name in the library file, read from its definition there, without loading the file."""
    from lisp_builtins import find_lisp_file
    where = "It is in %s, which is loaded the first time it is called." % file
    try:
        text, forms = library_file(find_lisp_file(file))
    except (LispError, OSError):
        return "%s is in %s, which is not found." % (name, file)
    definition = definition_in(forms, name)
    if definition is not None:
        return definition + "\n" + where
    made_by_defstruct = struct_documentation(text, forms, name, file)
    if made_by_defstruct is not None:
        return made_by_defstruct + "\n" + where
    return "%s is defined in %s." % (name, file)


_library_files = {}      # a file's path -> (when it was last changed, its text, its forms)


def library_file(path):
    """The text of the Lisp file at path, and its forms, read (not evaluated); kept until the file changes, so that apropos,
    which looks up many names, reads each file once."""
    changed = os.path.getmtime(path)
    kept = _library_files.get(path)
    if kept is None or kept[0] != changed:
        with open(path) as f:
            text = f.read()
        try:
            forms = list(parse(text))
        except LispError:
            forms = []
        kept = (changed, text, forms)
        _library_files[path] = kept
    return kept[1], kept[2]


def definition_in(forms, name):
    """The documentation of the function called name among the forms of a Lisp file, from its (define (name ...) "docstring" ...)
    or (defgeneric name (...) "docstring"); None if they have neither."""
    for form in forms:
        if not (isinstance(form, Pair) and isinstance(form.cdr, Pair)):
            continue
        head, second = form.car, form.cdr.car
        if head == Symbol("define") and isinstance(second, Pair) and second.car == Symbol(name):
            how_called = to_string(second)
            text = docstring(pairs_to_list(form.cdr.cdr))
            return joined(how_called, text) if text else how_called
        if head == Symbol("defgeneric") and second == Symbol(name):
            rest = pairs_to_list(form.cdr.cdr)
            how_called = to_string(Pair(second, rest[0])) if rest else "(%s ...)" % name
            return joined(how_called, str(rest[1])) if len(rest) > 1 else how_called
    return None


def struct_documentation(text, forms, name, file):
    """If name is one of the functions that a defstruct in the file makes (make-point, point-x, point-x-set!, point?, copy-point), what
    it does, and the defstruct and the comment lines under it in the file's text; otherwise None. (A slot that the struct includes from
    another is not among its own.)"""
    for form in forms:
        if not (isinstance(form, Pair) and form.car == Symbol("defstruct") and isinstance(form.cdr, Pair)):
            continue
        type_name = form.cdr.car.car if isinstance(form.cdr.car, Pair) else form.cdr.car
        slot_names = [str(slot.car) if isinstance(slot, Pair) else str(slot) for slot in pairs_to_list(form.cdr.cdr)]
        docs = struct_function_docs(str(type_name), slot_names)
        if name in docs:
            return docs[name] + "\n" + "\n".join("  " + line for line in defstruct_lines(text, str(type_name)))
    return None


def defstruct_lines(text, type_name):
    """The line of the text that begins (defstruct type_name ...), and the comment lines under it."""
    lines = text.splitlines()
    for number, line in enumerate(lines):
        if re.match(r"\(defstruct \(?" + re.escape(type_name) + r"[\s)]", line):
            shown = [line]
            for after in lines[number + 1:]:
                if not after.startswith(";"):
                    break
                shown.append(after)
            return shown
    return []


# ---------------------------------------------------------------------------
# The manuals
# ---------------------------------------------------------------------------

_manual_sections = None


def manual_sections():
    """Each section of the manuals, as (heading, lines of its text, manual), the heading without its #s; read once."""
    global _manual_sections
    if _manual_sections is None:
        _manual_sections = []
        for manual in MANUALS:
            path = os.path.join(DOC_DIRECTORY, manual)
            if not os.path.isfile(path):
                continue
            with open(path) as f:
                heading, body = None, []
                for line in f.read().splitlines():
                    if line.startswith("#"):
                        if heading is not None:
                            _manual_sections.append((heading, body, manual))
                        heading, body = line.lstrip("#").strip(), []
                    elif heading is not None:
                        body.append(line)
                if heading is not None:
                    _manual_sections.append((heading, body, manual))
    return _manual_sections


def manual_section(name):
    """The section of a manual whose heading shows how name is called, `(name ...)`, as text: the heading, its text (at most
    MOST_MANUAL_LINES lines of it), and the manual it is in. None if no heading does."""
    called = re.compile(r"`\(" + re.escape(name) + r"[ )`]")
    for heading, body, manual in manual_sections():
        if called.search(heading):
            while body and not body[0].strip():
                body = body[1:]
            while body and not body[-1].strip():
                body = body[:-1]
            shown = body[:MOST_MANUAL_LINES]
            more = " (more there)" if len(body) > MOST_MANUAL_LINES else ""
            return "%s\n%s\n(From %s%s.)" % (heading.replace("`", ""), "\n".join("  " + line if line else "" for line in shown),
                                              manual, more)
    return None


# ---------------------------------------------------------------------------
# Finding names
# ---------------------------------------------------------------------------

def visible_names(env):
    """The names a user calls, from the top-level environment and the special forms: not the ones that begin with % or have --
    in them, which the interpreter and the libraries use inside themselves."""
    names = {str(name) for name in env} | set(SPECIAL_FORMS)
    return sorted(name for name in names if not name.startswith("%") and "--" not in name)


def completions(env, prefix):
    """The visible names that begin with prefix, for the Tab key."""
    return [name for name in visible_names(env) if name.startswith(prefix)]


def summary(env, name):
    """One line about name, for apropos: the first line of its documentation."""
    text = documentation(env, name)
    first = text.splitlines()[0] if text else ""
    return first if len(first) <= 110 else first[:107] + "..."


def make_help_builtins(env, out):
    """documentation, apropos, and %show-help (which the help macro of macros_init.lsp calls), for the top-level environment env."""

    def name_of(x, who):
        if isinstance(x, Symbol):
            return str(x)
        if isinstance(x, (str, LispString)):
            return str(x)
        if isinstance(x, (Procedure, Macro)) and x.name is not None:
            return str(x.name)
        if callable(x) and x in builtin_names:
            return builtin_names[x]
        raise LispError("%s: expected a name, such as 'map or \"map\", not %s" % (who, brief(x)))

    def lisp_documentation(x):
        """(documentation name) -- the documentation of name (a symbol or a string), as a string: how it is called, then what it
        does, from its docstring, its library's file, or the manual. #f if there is none. (help name) shows it."""
        text = documentation(env, name_of(x, "documentation"))
        return LispString(text) if text is not None else False

    def show_help(x):
        name = name_of(x, "help")
        text = documentation(env, name)
        if text is None:
            text = "%s is not defined. (apropos \"%s\") lists the names that have \"%s\" in them." % (name, name, name)
        out.write(text + "\n")
        return NIL

    def lisp_apropos(text):
        """(apropos text) -- shows each name that has text in it (a string or a symbol; capitals are the same as small letters),
        with the first line of its documentation, which is usually how it is called. The library functions that are not loaded
        yet are among them. Returns nothing."""
        wanted = name_of(text, "apropos").lower()
        found = [name for name in visible_names(env) if wanted in name.lower()]
        if not found:
            out.write("No name has \"%s\" in it.\n" % wanted)
        width = max((len(name) for name in found), default=0)
        for name in found:
            out.write("%s  %s\n" % (name.ljust(width), summary(env, name)))
        return NIL

    return {
        "documentation": lisp_documentation,
        "apropos": lisp_apropos,
        "%show-help": show_help,
    }
