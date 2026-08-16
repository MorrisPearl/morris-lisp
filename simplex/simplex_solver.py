"""
simplex_solver.py
==================

A small, easy-to-read implementation of the Simplex algorithm (Big-M method)
for solving linear minimization problems, with a reader for a simple flat
text file format.

The code favors clarity over performance: it uses plain Python lists and
loops instead of numpy, and it does the tableau pivoting step by step so
each part of the algorithm can be followed easily.

------------------------------------------------------------------
FLAT FILE FORMAT
------------------------------------------------------------------
Lines starting with '#' are treated as comments and ignored, as are
blank lines. The file has two sections:

    minimize
    <objective coefficients, space separated>
    subject to
    <constraint row 1>
    <constraint row 2>
    ...

Each constraint row is a list of coefficients, followed by a relation
('<=', '>=', or '=') and a right-hand-side value. All variables are
assumed to be >= 0 (standard form).

Example (2 variables, 3 constraints):

    # Maximize 3x1 + 5x2  ==  minimize -3x1 - 5x2
    minimize
    -3 -5
    subject to
    1 0 <= 4
    0 2 <= 12
    3 2 <= 18

------------------------------------------------------------------
"""

import sys


def parse_lp_file(filepath):
    """
    Read a flat file describing a linear minimization problem and return:
        c          - list of objective coefficients
        A          - list of lists, one row of coefficients per constraint
        relations  - list of strings, one of '<=', '>=', '=' per constraint
        b          - list of right-hand-side values

    See the module docstring above for the expected file format.
    """
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    if not lines or lines[0].lower() != "minimize":
        raise ValueError("File must start with a 'minimize' line (after comments/blank lines).")

    c = [float(token) for token in lines[1].split()]

    if lines[2].lower() != "subject to":
        raise ValueError("Expected a 'subject to' line after the objective coefficients.")

    A = []
    relations = []
    b = []
    for line in lines[3:]:
        tokens = line.split()
        relation = tokens[-2]
        rhs = float(tokens[-1])
        coefficients = [float(t) for t in tokens[:-2]]

        if relation not in ("<=", ">=", "="):
            raise ValueError(f"Unrecognized relation '{relation}' in line: {line}")
        if len(coefficients) != len(c):
            raise ValueError(f"Constraint has {len(coefficients)} coefficients, "
                              f"expected {len(c)}: {line}")

        A.append(coefficients)
        relations.append(relation)
        b.append(rhs)

    if not A:
        raise ValueError("No constraints were found after 'subject to'.")

    return c, A, relations, b


def solve_simplex(c, A, relations, b, big_m=1e6, max_iterations=1000):
    """
    Solve:  minimize   c^T x
            subject to A x {<=, >=, =} b
                       x >= 0

    using the Simplex algorithm with the Big-M method, which lets us
    handle '<=', '>=' and '=' constraints uniformly by adding slack,
    surplus, and artificial variables.

    Returns (solution, optimal_value) where `solution` is a list giving
    the value of each original variable, in the same order as `c`.

    Raises RuntimeError if the problem is infeasible, unbounded, or the
    algorithm does not converge within `max_iterations`.
    """
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

    # --- Step 4: build the objective row ---
    # We keep the classic tableau convention: the objective row holds
    # -(objective coefficient) for the problem being MAXIMIZED, and the
    # algorithm improves the solution while some entry is negative.
    #
    # To minimize c^T x with the Big-M method, artificial variables get a
    # huge cost `big_m` in the minimization sense. Working through the
    # sign convention, that means:
    #   - original variables get coefficient c[j]      in the objective row
    #   - slack / surplus variables get coefficient 0
    #   - artificial variables get coefficient big_m
    obj_row = [0.0] * (total_vars + 1)
    obj_row[:n_vars] = c
    for col in range(artificial_start, total_vars):
        obj_row[col] = big_m

    # The artificial variables are currently basic, but the objective row
    # above doesn't reflect that (their column should read 0 since they're
    # basic). Fix this by subtracting big_m times each artificial row from
    # the objective row -- standard "canonicalization" step of Big-M.
    for i, basic_col in enumerate(basis):
        if obj_row[basic_col] != 0.0:
            factor = obj_row[basic_col]
            for j in range(total_vars + 1):
                obj_row[j] -= factor * tableau[i][j]

    tableau.append(obj_row)  # objective row lives at the end of the tableau

    # --- Step 5: the main simplex loop ---
    for _ in range(max_iterations):
        obj_row = tableau[-1]

        # Choose the entering variable: the most negative coefficient in
        # the objective row means increasing that variable improves the
        # (implicit) objective the most.
        entering_col = min(range(total_vars), key=lambda j: obj_row[j])
        if obj_row[entering_col] >= -1e-9:
            break  # no negative coefficients left: we're optimal

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
        # the objective row).
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
        raise RuntimeError("Simplex did not converge within the iteration limit.")

    # --- Step 6: check feasibility ---
    # If an artificial variable is still basic with a positive value, the
    # original problem had no feasible solution.
    for i, basic_col in enumerate(basis):
        if basic_col >= artificial_start and tableau[i][-1] > 1e-7:
            raise RuntimeError("Problem is infeasible.")

    # --- Step 7: read off the solution ---
    solution = [0.0] * n_vars
    for i, basic_col in enumerate(basis):
        if basic_col < n_vars:
            solution[basic_col] = tableau[i][-1]

    optimal_value = sum(c[j] * solution[j] for j in range(n_vars))
    return solution, optimal_value


def solve_lp_file(filepath):
    """Convenience function: parse a flat file and solve it in one call."""
    c, A, relations, b = parse_lp_file(filepath)
    return solve_simplex(c, A, relations, b)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "example_problem.txt"
    solution, optimal_value = solve_lp_file(path)

    print(f"Solved problem from: {path}")
    for i, value in enumerate(solution, start=1):
        print(f"  x{i} = {value:.6g}")
    print(f"Optimal objective value = {optimal_value:.6g}")
