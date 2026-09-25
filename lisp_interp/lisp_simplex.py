"""Linear programming for the Lisp interpreter: the lp-read-file and
lp-solve builtins, which bridge to simplex/simplex_solver.py (the simplex
algorithm, Big-M method, in plain Python).

  lp-read-file   read a problem from a text file, in the format described
                 at the top of simplex_solver.py
  lp-solve       solve a problem: minimize (or maximize) the objective,
                 subject to the constraints, with every variable >= 0

A problem, as lp-read-file returns it and lp-solve takes it, is a Lisp
association list of six lists -- the six things
simplex_solver.parse_lp_file returns (c, A, relations, b, variable names,
and whether to maximize):

  (("objective"   c1 c2 ...)              the objective's coefficients
   ("constraints" (a11 a12 ...) ...)      each constraint's coefficients
   ("relations"   "<=" ">=" "=" ...)      each constraint's relation
   ("rhs"         b1 b2 ...)              each constraint's right-hand side
   ("variables"   "x1" "x2" ...)          each variable's name
   ("goal"        "minimize"))            "minimize" or "maximize"

The first four are required. "variables" and "goal" are optional for
lp-solve: with no "goal" the problem is minimized. lp-solve doesn't use the
names; they're for the reader of the problem and its solution.

If simplex/ isn't next to this directory, the builtins raise a clear error
when called.
"""

import os
import sys

from lisp_core import NIL, LispError, LispString, Pair, list_to_pairs, pairs_to_list, to_string

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "simplex"))

try:
    from simplex_solver import parse_lp_file, solve_simplex
    _SIMPLEX_AVAILABLE = True
except ImportError:
    _SIMPLEX_AVAILABLE = False


def _require_simplex(name):
    if not _SIMPLEX_AVAILABLE:
        raise LispError("%s: simplex/simplex_solver.py isn't available -- see simplex/ next to lisp_interp/"
                        % name)


def lp_read_file(path):
    """(lp-read-file path) -- read a linear programming problem from a text
    file and return it as a problem list (see the top of this file)."""
    _require_simplex("lp-read-file")
    try:
        c, A, relations, b, variable_names, maximize = parse_lp_file(str(path))
    except (OSError, ValueError) as e:
        raise LispError("lp-read-file: %s: %s" % (path, e))
    return list_to_pairs([
        Pair(LispString("objective"), list_to_pairs(c)),
        Pair(LispString("constraints"), list_to_pairs([list_to_pairs(row) for row in A])),
        Pair(LispString("relations"), list_to_pairs([LispString(r) for r in relations])),
        Pair(LispString("rhs"), list_to_pairs(b)),
        Pair(LispString("variables"), list_to_pairs([LispString(name) for name in variable_names])),
        Pair(LispString("goal"), list_to_pairs([LispString("maximize" if maximize else "minimize")])),
    ])


def _find_part(problem, name):
    """The part of a problem stored under name, e.g. "objective", as a
    Python list, or None if the problem has no part by that name."""
    for entry in pairs_to_list(problem):
        if isinstance(entry, Pair) and entry.car == name:
            return _list_items(entry.cdr, name)
    return None


def _problem_part(problem, name):
    """Like _find_part, but the problem must have this part."""
    part = _find_part(problem, name)
    if part is None:
        raise LispError('lp-solve: the problem has no "%s" list -- it needs "objective", '
                        '"constraints", "relations", and "rhs"' % name)
    return part


def _list_items(x, name):
    """The elements of the Lisp list x, as a Python list."""
    if not (isinstance(x, Pair) or x is NIL):
        raise LispError('lp-solve: "%s" must be a list, not %s' % (name, to_string(x)))
    return pairs_to_list(x)


def _numbers(items, name):
    """items (a Python list of Lisp values), checked to be numbers, as floats."""
    for x in items:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise LispError('lp-solve: "%s" must hold only numbers, but it has %s' % (name, to_string(x)))
    return [float(x) for x in items]


def _goal_is_maximize(problem):
    """Whether the problem's "goal" is "maximize" (True) or "minimize", which
    is also what a problem with no "goal" means (False)."""
    goal = _find_part(problem, "goal")
    if goal is None:
        return False
    if len(goal) != 1 or str(goal[0]) not in ("minimize", "maximize"):
        raise LispError('lp-solve: "goal" must be "minimize" or "maximize", not %s'
                        % to_string(list_to_pairs(goal)))
    return str(goal[0]) == "maximize"


def _check_max_iterations(max_iterations):
    """The iteration limit for lp-solve, or None for the solver's default
    (given as nothing, or '())."""
    if max_iterations is None or max_iterations is NIL:
        return None
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or max_iterations < 1:
        raise LispError("lp-solve: max-iterations must be a whole number of at least 1, not %s"
                        % to_string(max_iterations))
    return max_iterations


def lp_solve(problem, max_iterations=None):
    """(lp-solve problem [max-iterations]) -- minimize (or, if the problem's
    goal is "maximize", maximize) the problem's objective subject to its
    constraints, with every variable >= 0. Returns
    (("solution" x1 x2 ...) ("optimal-value" . v)): the value of each
    variable, in the objective's order, and the objective's optimal value.
    max-iterations is how many steps the solver may take before giving up;
    the default is three times the number of variables it works with."""
    _require_simplex("lp-solve")
    c = _numbers(_problem_part(problem, "objective"), "objective")
    A = [_numbers(_list_items(row, "constraints"), "constraints")
         for row in _problem_part(problem, "constraints")]
    relations = [str(r) for r in _problem_part(problem, "relations")]
    b = _numbers(_problem_part(problem, "rhs"), "rhs")
    maximize = _goal_is_maximize(problem)
    max_iterations = _check_max_iterations(max_iterations)
    variables = _find_part(problem, "variables")

    if not c:
        raise LispError('lp-solve: "objective" is empty')
    if not A:
        raise LispError('lp-solve: "constraints" is empty')
    if not len(A) == len(relations) == len(b):
        raise LispError('lp-solve: there are %d constraints, %d relations, and %d rhs values '
                        '-- they must be the same' % (len(A), len(relations), len(b)))
    for row in A:
        if len(row) != len(c):
            raise LispError("lp-solve: a constraint has %d coefficients, but the objective has %d"
                            % (len(row), len(c)))
    if variables is not None and len(variables) != len(c):
        raise LispError('lp-solve: "variables" has %d names, but the objective has %d coefficients'
                        % (len(variables), len(c)))
    for r in relations:
        if r not in ("<=", ">=", "="):
            raise LispError('lp-solve: a relation must be "<=", ">=", or "=", not %s' % (r,))

    try:
        solution, optimal_value = solve_simplex(c, A, relations, b, maximize, max_iterations)
    except RuntimeError as e:
        raise LispError("lp-solve: %s" % e)
    return list_to_pairs([
        Pair(LispString("solution"), list_to_pairs(solution)),
        Pair(LispString("optimal-value"), optimal_value),
    ])


BUILTINS = {
    "lp-read-file": lp_read_file,
    "lp-solve": lp_solve,
}
