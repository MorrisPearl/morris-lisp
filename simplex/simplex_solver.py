"""
simplex_solver.py
==================

A small, easy-to-read implementation of the Simplex algorithm (Big-M method)
for solving linear minimization and maximization problems, with a reader for
a simple flat text file format.

The code favors clarity over performance: it uses plain Python lists and
loops instead of numpy, and it does the tableau pivoting step by step so
each part of the algorithm can be followed easily.

------------------------------------------------------------------
FLAT FILE FORMAT
------------------------------------------------------------------
Lines starting with '#' are treated as comments and ignored, as are
blank lines. The file has two sections:

    minimize                       (or: maximize)
    <the objective>
    subject to
    <constraint 1>
    <constraint 2>
    ...

Each constraint is a left-hand side, then a relation ('<=', '>=', or '='),
then a right-hand-side number. All variables are assumed to be >= 0.

There are two ways to write the objective and the constraints' left-hand
sides. Use whichever you like; the objective's form decides which one the
whole file uses.

1. WITH VARIABLE NAMES. Write each as a sum of terms, like a formula. A
   term is a number and a variable's name ("3 x", "0.5 rate") or just the
   name (meaning 1 times it). Put spaces around everything, including the
   + and - between terms. A name starts with a letter or underscore and
   has only letters, digits, and underscores. A variable that isn't in a
   constraint just isn't mentioned in it. The variables are numbered in the
   order they first appear, objective first.

    # Maximize 3x1 + 5x2
    maximize
    3 x1 + 5 x2
    subject to
    x1 <= 4
    2 x2 <= 12
    3 x1 + 2 x2 <= 18

2. WITH COEFFICIENTS ONLY. Write one coefficient for each variable, in the
   same order every time, including the zeros. The variables are named x1,
   x2, ... .

    # Maximize 3x1 + 5x2  ==  minimize -3x1 - 5x2
    minimize
    -3 -5
    subject to
    1 0 <= 4
    0 2 <= 12
    3 2 <= 18

Both of these files describe the same problem. "maximize" is solved by
minimizing the negative of the objective; the optimal value is still
reported as the maximum.

------------------------------------------------------------------
"""

import sys


def is_variable_name(token):
    """Whether token is a variable's name: a letter or underscore, then
    letters, digits, and underscores."""
    return token.isidentifier()


def read_number(token, line, what="a number"):
    """The number that token spells. A token that isn't a number is an
    error, and the message shows the whole line. `what` says what the
    token should have been, for the message."""
    if not is_variable_name(token):     # (a name like "inf" is a name, not a number)
        try:
            return float(token)
        except ValueError:
            pass
    raise ValueError(f"'{token}' is not {what}: {line}")


def split_constraint_line(line):
    """Split a constraint like "3 x + 2 y <= 18" into its three parts:
    (the tokens of the left-hand side, the relation, the right-hand side)."""
    tokens = line.split()
    if len(tokens) < 3:
        raise ValueError(f"A constraint needs a left-hand side, a relation, and a number "
                         f"on the right: {line}")
    relation = tokens[-2]
    if relation not in ("<=", ">=", "="):
        raise ValueError(f"Unrecognized relation '{relation}' in line: {line}")
    return tokens[:-2], relation, read_number(tokens[-1], line)


def parse_numbered_problem(objective_line, constraint_lines):
    """Read the objective and constraints of a file written with coefficients
    only (form 2 in the module docstring). Returns
    (variable_names, c, A, relations, b) -- see parse_lp_file."""
    c = [read_number(token, objective_line) for token in objective_line.split()]
    variable_names = [f"x{j}" for j in range(1, len(c) + 1)]

    A = []
    relations = []
    b = []
    for line in constraint_lines:
        left_side, relation, rhs = split_constraint_line(line)
        coefficients = [read_number(token, line,
                                    "a number (the objective has no variable names, "
                                    "so the constraints can't either)")
                        for token in left_side]
        if len(coefficients) != len(c):
            raise ValueError(f"Constraint has {len(coefficients)} coefficients, "
                              f"expected {len(c)}: {line}")
        A.append(coefficients)
        relations.append(relation)
        b.append(rhs)

    return variable_names, c, A, relations, b


def parse_expression(tokens, line):
    """Read a sum of terms, such as "3 x + y - 2.5 z" (already split into
    tokens), into a dictionary from each variable's name to its coefficient.
    A variable that appears twice gets both coefficients added. `line` is
    the whole line, for error messages."""
    coefficients = {}
    sign = 1.0
    position = 0

    # An optional sign in front of the first term.
    if tokens and tokens[0] in ("+", "-"):
        sign = 1.0 if tokens[0] == "+" else -1.0
        position = 1

    while True:
        # One term: a name, or a number and then a name.
        size = 1.0
        if position < len(tokens) and not is_variable_name(tokens[position]):
            size = read_number(tokens[position], line,
                               "a number or a variable name (put spaces around "
                               "every number, name, +, and -)")
            position += 1
        if position == len(tokens) or not is_variable_name(tokens[position]):
            raise ValueError(f"Expected a variable name in: {line}")
        name = tokens[position]
        coefficients[name] = coefficients.get(name, 0.0) + sign * size
        position += 1

        # Then the end of the formula, or + or - and another term.
        if position == len(tokens):
            return coefficients
        if tokens[position] not in ("+", "-"):
            raise ValueError(f"Expected + or - after '{name}', but found '{tokens[position]}': {line}")
        sign = 1.0 if tokens[position] == "+" else -1.0
        position += 1


def parse_named_problem(objective_line, constraint_lines):
    """Read the objective and constraints of a file written with variable
    names (form 1 in the module docstring). Returns
    (variable_names, c, A, relations, b) -- see parse_lp_file."""
    objective = parse_expression(objective_line.split(), objective_line)

    constraint_terms = []       # for each constraint, a dictionary from name to coefficient
    relations = []
    b = []
    for line in constraint_lines:
        left_side, relation, rhs = split_constraint_line(line)
        constraint_terms.append(parse_expression(left_side, line))
        relations.append(relation)
        b.append(rhs)

    # Number the variables in the order they first appear: the objective's
    # first, then each constraint's. (A dictionary keeps its keys in the
    # order they were added, so it works as an ordered set.)
    seen = {}
    for terms in [objective] + constraint_terms:
        for name in terms:
            seen[name] = None
    variable_names = list(seen)

    # A variable that a formula doesn't mention has coefficient 0 in it.
    c = [objective.get(name, 0.0) for name in variable_names]
    A = [[terms.get(name, 0.0) for name in variable_names] for terms in constraint_terms]
    return variable_names, c, A, relations, b


def parse_lp_file(filepath):
    """
    Read a flat file describing a linear programming problem and return:
        c              - list of objective coefficients
        A              - list of lists, one row of coefficients per constraint
        relations      - list of strings, one of '<=', '>=', '=' per constraint
        b              - list of right-hand-side values
        variable_names - list of the variables' names, in the order of c
                         (x1, x2, ... if the file doesn't name them)
        maximize       - True if the file says "maximize", False for "minimize"
                         (c is as written in the file, not negated)

    See the module docstring above for the expected file format.
    """
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    if not lines or lines[0].lower() not in ("minimize", "maximize"):
        raise ValueError("File must start with a 'minimize' or 'maximize' line "
                         "(after comments/blank lines).")
    maximize = lines[0].lower() == "maximize"

    if len(lines) < 2 or lines[1].lower() == "subject to":
        raise ValueError(f"Expected the objective on the line after '{lines[0]}'.")
    if len(lines) < 3 or lines[2].lower() != "subject to":
        raise ValueError("Expected a 'subject to' line after the objective.")
    objective_line = lines[1]
    constraint_lines = lines[3:]
    if not constraint_lines:
        raise ValueError("No constraints were found after 'subject to'.")

    # A file that uses variable names has at least one in its objective.
    if any(is_variable_name(token) for token in objective_line.split()):
        variable_names, c, A, relations, b = parse_named_problem(objective_line, constraint_lines)
    else:
        variable_names, c, A, relations, b = parse_numbered_problem(objective_line, constraint_lines)

    return c, A, relations, b, variable_names, maximize


def solve_simplex(c, A, relations, b, maximize=False, max_iterations=None):
    """
    Solve:  minimize   c^T x
            subject to A x {<=, >=, =} b
                       x >= 0

    using the Simplex algorithm with the Big-M method, which lets us
    handle '<=', '>=' and '=' constraints uniformly by adding slack,
    surplus, and artificial variables. M is kept symbolic -- treated as
    larger than any number -- rather than set to a particular big number
    (see Step 4).

    If `maximize` is True, maximize c^T x instead. (That is done by
    minimizing -c^T x; the optimal value returned is still the maximum of
    c^T x.)

    Returns (solution, optimal_value) where `solution` is a list giving
    the value of each original variable, in the same order as `c`.

    `max_iterations` is how many pivots to try before giving up. By
    default it is three times the total number of variables: the original
    variables plus the slack, surplus, and artificial ones (see Step 2).

    Raises RuntimeError if the problem is infeasible, unbounded, or the
    algorithm does not converge within `max_iterations`.
    """
    original_c = c
    if maximize:
        c = [-cost for cost in c]   # maximizing c^T x is minimizing -c^T x

    n_vars = len(c)
    n_constraints = len(A)
    A = [row[:] for row in A]   # work on copies so we don't mutate caller's data
    b = list(b)
    relations = list(relations)

    # --- Step 1: make every right-hand side non-negative ---
    # (If b[i] is negative, flip the sign of the whole row and swap the
    # relation so the RHS becomes non-negative.)
    flip = {"<=": ">=", ">=": "<=", "=": "="}
    for i in range(n_constraints):
        if b[i] < 0:
            A[i] = [-a for a in A[i]]
            b[i] = -b[i]
            relations[i] = flip[relations[i]]

    # --- Step 2: decide how many slack / surplus / artificial variables we need ---
    # '<=' rows get one slack variable (+1, already feasible as a basic variable)
    # '>=' rows get one surplus variable (-1) plus one artificial variable (+1)
    # '='  rows get one artificial variable (+1)
    n_slack = relations.count("<=")
    n_surplus = relations.count(">=")
    n_artificial = relations.count(">=") + relations.count("=")
    total_vars = n_vars + n_slack + n_surplus + n_artificial

    # Column layout:
    #   [0, n_vars)                                  original variables
    #   [n_vars, n_vars+n_slack)                      slack variables
    #   [n_vars+n_slack, n_vars+n_slack+n_surplus)    surplus variables
    #   [n_vars+n_slack+n_surplus, total_vars)        artificial variables
    slack_col = n_vars
    surplus_col = n_vars + n_slack
    artificial_col = n_vars + n_slack + n_surplus
    artificial_start = artificial_col  # remember where artificial columns begin

    # --- Step 3: build the constraint rows of the tableau ---
    tableau = []
    basis = []  # basis[i] = column index of the variable that is basic in row i

    for i in range(n_constraints):
        row = [0.0] * (total_vars + 1)  # last entry is the right-hand side
        row[:n_vars] = A[i]
        row[-1] = b[i]

        if relations[i] == "<=":
            row[slack_col] = 1.0
            basis.append(slack_col)
            slack_col += 1
        elif relations[i] == ">=":
            row[surplus_col] = -1.0
            surplus_col += 1
            row[artificial_col] = 1.0
            basis.append(artificial_col)
            artificial_col += 1
        else:  # '='
            row[artificial_col] = 1.0
            basis.append(artificial_col)
            artificial_col += 1

        tableau.append(row)

    # --- Step 4: build the objective rows ---
    # We keep the classic tableau convention: the objective row holds
    # -(objective coefficient) for the problem being MAXIMIZED, and the
    # algorithm improves the solution while some entry is negative.
    #
    # To minimize c^T x with the Big-M method, artificial variables get a
    # cost of M, a number so large that getting rid of them comes before
    # anything else. Working through the sign convention, that means:
    #   - original variables get coefficient c[j]  in the objective row
    #   - slack / surplus variables get coefficient 0
    #   - artificial variables get coefficient M
    #
    # We don't pick an actual number for M. Too small, and a real cost
    # bigger than M makes a feasible problem look infeasible; too big, and
    # floating point loses the real costs added to it. Instead M is kept
    # symbolic, as larger than any number: every objective-row entry is
    #     (M part) * M + (ordinary part)
    # and the two parts are kept in two separate rows:
    #   obj_row - the ordinary parts: c[j] for original variables, else 0
    #   m_row   - the M parts: 1 for artificial variables, else 0
    # Both are pivoted just like the constraint rows.
    obj_row = [0.0] * (total_vars + 1)
    obj_row[:n_vars] = c
    m_row = [0.0] * (total_vars + 1)
    for col in range(artificial_start, total_vars):
        m_row[col] = 1.0

    # The artificial variables are currently basic, but m_row doesn't
    # reflect that (their column should read 0 since they're basic). Fix
    # this by subtracting each artificial row from m_row -- the standard
    # "canonicalization" step of Big-M. (obj_row needs no fixing: it's
    # already 0 in every basic column, since the basic variables all start
    # out as slack or artificial variables.)
    for i, basic_col in enumerate(basis):
        if m_row[basic_col] != 0.0:
            factor = m_row[basic_col]
            for j in range(total_vars + 1):
                m_row[j] -= factor * tableau[i][j]

    tableau.append(obj_row)  # the two objective rows live at the end of the tableau
    tableau.append(m_row)

    # --- Step 5: the main simplex loop ---
    # How many pivots to allow before giving up. total_vars counts every
    # column of the tableau: the original, slack, surplus, and artificial
    # variables.
    if max_iterations is None:
        max_iterations = 3 * total_vars

    # How close to 0 a number must be to count as 0. Rounding errors grow
    # with the size of the numbers -- with costs in the hundreds of
    # millions, an entry of obj_row that should be exactly 0 can come out
    # as -0.00000003 -- so each tolerance grows with the numbers it's
    # compared against:
    #   cost_tolerance  - for entries of obj_row, which are sized like the costs
    #   value_tolerance - for the variables' values, sized like the right-hand sides
    cost_tolerance = 1e-9 * max([1.0] + [abs(cost) for cost in c])
    value_tolerance = 1e-7 * max([1.0] + b)

    for _ in range(max_iterations):
        obj_row = tableau[-2]
        m_row = tableau[-1]

        # Choose the entering variable: the most negative entry in the
        # objective row means increasing that variable improves the
        # (implicit) objective the most. Since M is larger than any number,
        # the M parts decide first:
        #   - if some column's M part is negative, take the most negative;
        #   - otherwise, among the columns with no M part, take the one
        #     whose ordinary part is most negative. (A column with a
        #     positive M part is worth about +M, so it's never negative.)
        entering_col = min(range(total_vars), key=lambda j: m_row[j])
        if m_row[entering_col] >= -1e-9:
            # No M part is negative, so the artificial variables are as
            # small as they can be made. If one is still positive, no
            # values of the variables satisfy all the constraints.
            for i, basic_col in enumerate(basis):
                if basic_col >= artificial_start and tableau[i][-1] > value_tolerance:
                    raise RuntimeError("Problem is infeasible.")

            columns_without_m = [j for j in range(total_vars) if m_row[j] <= 1e-9]
            entering_col = min(columns_without_m, key=lambda j: obj_row[j])
            if obj_row[entering_col] >= -cost_tolerance:
                break  # no negative entries left: we're optimal

        # Ratio test: choose the leaving variable as the row with the
        # smallest non-negative ratio of RHS to the entering column's
        # coefficient (this keeps all RHS values non-negative).
        leaving_row = None
        best_ratio = float("inf")
        for i in range(n_constraints):
            coeff = tableau[i][entering_col]
            if coeff > 1e-9:
                ratio = tableau[i][-1] / coeff
                if ratio < best_ratio - 1e-9:
                    best_ratio = ratio
                    leaving_row = i

        if leaving_row is None:
            raise RuntimeError("Problem is unbounded.")

        # Pivot: scale the pivot row so the entering column reads 1, then
        # eliminate the entering column from every other row (including
        # both objective rows).
        pivot_value = tableau[leaving_row][entering_col]
        tableau[leaving_row] = [v / pivot_value for v in tableau[leaving_row]]
        for i in range(len(tableau)):
            if i != leaving_row:
                factor = tableau[i][entering_col]
                if factor != 0.0:
                    tableau[i] = [tableau[i][j] - factor * tableau[leaving_row][j]
                                  for j in range(total_vars + 1)]

        basis[leaving_row] = entering_col
    else:
        raise RuntimeError(f"Simplex did not converge within {max_iterations} iterations.")

    # --- Step 6: check feasibility ---
    # If an artificial variable is still basic with a positive value, the
    # original problem had no feasible solution.
    for i, basic_col in enumerate(basis):
        if basic_col >= artificial_start and tableau[i][-1] > value_tolerance:
            raise RuntimeError("Problem is infeasible.")

    # --- Step 7: read off the solution ---
    solution = [0.0] * n_vars
    for i, basic_col in enumerate(basis):
        if basic_col < n_vars:
            solution[basic_col] = tableau[i][-1]

    optimal_value = sum(original_c[j] * solution[j] for j in range(n_vars))
    return solution, optimal_value


def solve_lp_file(filepath):
    """Convenience function: parse a flat file and solve it in one call.
    Returns (variable_names, solution, optimal_value)."""
    c, A, relations, b, variable_names, maximize = parse_lp_file(filepath)
    solution, optimal_value = solve_simplex(c, A, relations, b, maximize)
    return variable_names, solution, optimal_value


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "example_problem.txt"
    variable_names, solution, optimal_value = solve_lp_file(path)

    print(f"Solved problem from: {path}")
    for name, value in zip(variable_names, solution):
        print(f"  {name} = {value:.6g}")
    print(f"Optimal objective value = {optimal_value:.6g}")
