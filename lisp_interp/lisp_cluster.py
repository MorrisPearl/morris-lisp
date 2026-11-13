"""table-cluster: group the rows of a table that look alike, and say which group each row is in.

(table-cluster table columns k [:name "cluster"] [:scale #t] [:seed 0])

The rows are grouped by k-means: each row is a point whose coordinates are its values in the chosen columns, and the
groups are found by repeating two steps --
  1. give each row to the nearest group center,
  2. move each center to the average of the rows it was given --
until no row changes group. Where the centers start matters, so the whole thing is done 10 times from different
random starts (the first center of a start is a random row; each other is a row chosen with a better chance the
farther it is from the centers so far, which spreads them out) and the grouping with the rows closest to their
centers wins.

The result is the table with one more column. Its values are the numbers 1 to k, with 1 the group with the most rows.
A row that is missing a value in any of the chosen columns is in no group: its value is NaN.
"""

import numpy as np

from lisp_core import LispError, LispVector, keyword_options
from lisp_tables import find_column, names_argument, row_count, table_columns, table_add_column
from lisp_vector_math import floats_of, missing_mask

STARTS = 10                 # how many times the grouping is tried from a different start
MOST_STEPS = 300            # the most times the two steps are repeated in one try


def standardize(points):
    """Each column of points, shifted to average 0 and divided by its standard deviation, so that a column of dollars
    does not count for more than a column of rates. A column whose values are all the same is left at 0."""
    spread = points.std(axis=0)
    spread[spread == 0] = 1.0
    return (points - points.mean(axis=0)) / spread


def starting_centers(points, k, random):
    """k rows of points to start from: the first at random, each next chosen with a chance in proportion to its squared
    distance from the nearest center chosen so far."""
    centers = [points[random.integers(len(points))]]
    while len(centers) < k:
        nearest = np.min([((points - c) ** 2).sum(axis=1) for c in centers], axis=0)
        if nearest.sum() == 0:                  # every row is on a center already: any row will do
            centers.append(points[random.integers(len(points))])
        else:
            centers.append(points[random.choice(len(points), p=nearest / nearest.sum())])
    return np.array(centers)


def group_once(points, k, random):
    """One try: the group of each row, and the sum of the squared distances from the rows to their centers."""
    centers = starting_centers(points, k, random)
    groups = None
    for _ in range(MOST_STEPS):
        distances = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)       # row by center
        new_groups = distances.argmin(axis=1)
        if groups is not None and np.array_equal(new_groups, groups):
            break
        groups = new_groups
        for g in range(k):
            members = points[groups == g]
            if len(members):                    # a center with no rows stays where it is
                centers[g] = members.mean(axis=0)
    total = ((points - centers[groups]) ** 2).sum()
    return groups, total


def number_by_size(groups, k):
    """The group numbers 1 to k, with 1 the group with the most rows (of equal groups, the one whose first row comes first)."""
    first_row = [np.argmax(groups == g) if (groups == g).any() else len(groups) for g in range(k)]
    order = sorted(range(k), key=lambda g: (-(groups == g).sum(), first_row[g]))
    number = np.empty(k, dtype=np.int64)
    for place, g in enumerate(order):
        number[g] = place + 1
    return number[groups]


def table_cluster(table, column_names, k, *options):
    """(table-cluster table columns k [:name "cluster"] [:scale #t] [:seed 0]) -- the table with a column added that says
    which of k groups of alike rows each row is in. columns is the name of a column, or a list of names, to compare rows by.
    The new column is called "cluster", unless :name says. The columns are first each put on the same scale (see
    lisp_cluster.py); :scale #f compares the values as they are. :seed is any whole number: the same seed gives the same
    groups again."""
    given = keyword_options(options, ("name", "scale", "seed"), "table-cluster")
    new_name = str(given.get("name", "cluster"))
    scale = given.get("scale", True) is not False
    seed = given.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise LispError("table-cluster: :seed is a whole number")
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise LispError("table-cluster: k, the number of groups, is a whole number of 1 or more")

    columns = table_columns(table, "table-cluster")
    names = names_argument(column_names, "table-cluster")
    vectors = [find_column(columns, name, "table-cluster") for name in names]
    points = np.column_stack([floats_of(v, "table-cluster") for v in vectors])
    present = ~np.any([missing_mask(v) for v in vectors], axis=0)
    if present.sum() < k:
        raise LispError("table-cluster: %d groups were asked for, but only %d rows have a value in every one of %s"
                        % (k, present.sum(), ", ".join(names)))

    points = points[present]
    if scale:
        points = standardize(points)
    random = np.random.default_rng(seed)
    best_groups, best_total = None, None
    for _ in range(STARTS):
        groups, total = group_once(points, k, random)
        if best_total is None or total < best_total:
            best_groups, best_total = groups, total

    cluster = np.full(row_count(columns), np.nan)
    cluster[present] = number_by_size(best_groups, k)
    if present.all():
        cluster = cluster.astype(np.int64)
    return table_add_column(table, new_name, LispVector(cluster))


BUILTINS = {
    "table-cluster": table_cluster,
}
