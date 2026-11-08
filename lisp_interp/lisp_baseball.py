"""A baseball game as a chain of states, for the Lisp interpreter.

  (transition-counts table)              count the turns at bat of a table: a matrix of counts
  (smooth-transitions counts [:weight w]) the counts as probabilities, a rare state borrowing from the states like it
  (tilt-transitions league profile strength)
                                         a player's probabilities: the league's, tilted toward what the player does
  (combine-transitions batter pitcher league)
                                         the probabilities of a batter against a pitcher
  (prior-strength table group league)    how strongly the players' profiles are pulled toward the league's
  (prior-strength-loglik table group league strength)
                                         how well that strength explains the players
  (run-expectancy matrix [:weights counts])
                                         the runs that are expected in the rest of an inning, from each of the 24 outs-and-runners
  (transition-table matrix)              a matrix as a table: a row for each state and outcome that is possible
  (transition-row matrix home-batting outs bases score-difference)
                                         one state's row of the matrix
  (state-transition-table matrix)        the matrix as a state to state table
  (simulate-games home away [:games n] [:seed n] [:ghost-runner #t])
                                         play many games, between two teams of nine batters and their pitchers

THE STATE is what is known at the moment a batter steps up:

  home-batting       0 if the visiting team is batting (the top of an inning), 1 if the home team is
  outs               0, 1 or 2
  bases              the runners, as a number from 0 to 7: 1 for a runner on first, 2 on second, 4 on third, added up (5 is first and third)
  score-difference   the batting team's score less the other team's, from -3 (for -3 or less) to 3 (for 3 or more)

That is 2 x 3 x 8 x 7 = 336 states.

THE OUTCOME is what has happened by the time the batter's turn is over (his plate appearance, and a steal or a wild pitch during it):

  new-outs           0, 1, 2 or 3 (3 ends the inning)
  new-bases          the runners then (0 if the inning is over: the runners left on base do not matter any more)
  runs               how many runs scored, 0 to 4

That is 4 x 8 x 5 = 160 outcomes, most of which cannot happen from most of the states.

A MATRIX has a row for each state and a column for each outcome, and holds either COUNTS, how many times that happened, or PROBABILITIES, whose rows add
up to 1. The matrix of states and next states that one thinks of follows from it: after an outcome the next state has the new outs and runners, the score
difference changed by the runs (and still 3 or -3 if it was), and when the inning is over it is the other team's turn to bat, with no outs and no
runners and the score difference turned around.

THE RESULT of a turn is what the batter did: "strikeout", "walk" (a walk, a hit by pitch, or interference), "single", "double", "triple", "home run",
"other" (any other plate appearance: an out on a ball in play, an error, a fielder's choice, a sacrifice), or "none" (the inning ended on a steal before
the plate appearance was over). The counts of the league are of each outcome of each state, and of each result: from "walk" the outcome from a state with
no one on is a runner on first; from "single" it may be that, or a runner on first and one on third, and so on. The outcome says what happened to the
runners and the outs, and the result what the batter did to make it happen.

WHAT MAKES A PLAYER DIFFERENT is mostly the mix of his results: a batter who strikes out a lot, or hits home runs, does so from every state. So a
player's matrix is not made by counting his own turns state by state (336 states, and few turns in each), but from the mix of his results over all of
them, which many turns tell about, and what the league does with each result in each state:

  1. The player's profile is how many turns he had with each result. The prior is the league's mix of results, worth `strength` turns (prior-strength
     finds how many: the one that best explains how the players differ). The player's shares are his results' counts plus the prior's, over his turns plus
     the strength: the mean of a Dirichlet distribution of the results that started out as the league's and learned what the player did. A player with
     no turns has the league's shares, and one with many has nearly his own.
  2. Each of the league's counts is multiplied by the player's share of its result over the league's, so that a batter with twice as many home runs
     as the league has twice as many of the outcomes that home runs make, from every state. Each state's row is then scaled to add up to 1.

SMOOTHING: some states are rare. The league's counts are turned into probabilities by adding to each state's a few imaginary ones, spread as the counts of
the states with the same outs and runners are (whoever is batting, whatever the score), so that a state that never happened gets theirs, and an outcome
that is possible in a state like it is possible in it.

A BATTER AGAINST A PITCHER: the batter's probabilities, the pitcher's, and the league's are combined state by state, outcome by outcome: each outcome's
probability is the batter's times the pitcher's divided by the league's, and then the row is scaled to add up to 1. If a batter and a pitcher were each
twice as likely as the league to get a strikeout, the matchup is four times as likely, before scaling. ("log5", for more than two outcomes.)

THE GAME: simulate-games plays a game turn by turn, for each turn drawing an outcome from the row for the state it is in, from the matrix for the batter
who is up against the pitcher who is on the mound. The visiting team bats first; a game goes nine innings, and on while they are tied; the home team does not
bat in the bottom of the last inning if it is ahead, and the game ends when it takes the lead in it. In extra innings a runner starts on second base, the rule
since 2020, unless :ghost-runner #f.

RANDOM NUMBERS: with :seed the same games are played every time; without it, the shared generator that random-float uses, which (random-seed n) makes
reproducible.
"""

import random

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

from lisp_core import LispError, NIL, Pair, keyword_options, pairs_to_list
from lisp_tables import find_column, make_table_value, table_columns
from lisp_vector_math import floats_of, is_number, to_vector

SIDES, OUTS, BASES, DIFFERENCES = 2, 3, 8, 7                    # the parts of a state
STATES = SIDES * OUTS * BASES * DIFFERENCES                     # 336
NEW_OUTS, MAX_RUNS = 4, 4                                       # the parts of an outcome (and the runners, BASES)
RUNS = MAX_RUNS + 1
OUTCOMES = NEW_OUTS * BASES * RUNS                              # 160
LARGEST_DIFFERENCE = 3                                          # a score difference of more is the same as 3
STATE_COLUMNS = ["home_batting", "outs", "bases", "score_difference"]
OUTCOME_COLUMNS = ["new_outs", "new_bases", "runs"]
GHOST_RUNNER_BASES = 2                                          # the runner who starts an extra inning, on second base
LAST_REGULAR_INNING = 9
LAST_INNING_PLAYED = 30                                         # a game that is still tied then is stopped (and counted as a tie)


# ---------------------------------------------------------------------------
# States and outcomes, as numbers
# ---------------------------------------------------------------------------

def state_number(home_batting, outs, bases, score_difference):
    """The number of a state (0 to 335), from arrays of its parts. A score difference of more than 3 either way is 3."""
    difference = np.clip(score_difference, -LARGEST_DIFFERENCE, LARGEST_DIFFERENCE) + LARGEST_DIFFERENCE
    return ((home_batting * OUTS + outs) * BASES + bases) * DIFFERENCES + difference


def state_parts(state):
    """The parts of a state number, as arrays: home batting, outs, bases, score difference."""
    difference = state % DIFFERENCES - LARGEST_DIFFERENCE
    rest = state // DIFFERENCES
    return rest // (OUTS * BASES), (rest // BASES) % OUTS, rest % BASES, difference


def outcome_number(new_outs, new_bases, runs):
    """The number of an outcome (0 to 159), from arrays of its parts."""
    return (new_outs * BASES + new_bases) * RUNS + runs


def outcome_parts(outcome):
    """The parts of an outcome number, as arrays: new outs, new bases, runs."""
    return outcome // (BASES * RUNS), (outcome // RUNS) % BASES, outcome % RUNS


def next_state(state, outcome):
    """The state that follows from a state and an outcome (arrays of the same shape): see the top of this file."""
    home_batting, outs, bases, difference = state_parts(state)
    new_outs, new_bases, runs = outcome_parts(outcome)
    inning_over = new_outs == 3
    return np.where(inning_over,
                    state_number(1 - home_batting, 0, 0, -(difference + runs)),
                    state_number(home_batting, new_outs, new_bases, difference + runs))


# ---------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------

class Transitions:
    """A matrix of the states (rows) and outcomes (columns): of counts (kind "counts") or probabilities (kind "probabilities").

    values is the matrix, 336 x 160. The league's also has joint, 336 x 160 x (the number of results): the same, for each result, with the results' names
    in results, and shares, the share of each result over all the turns. (A player's matrix, and a matchup's, has no joint: it was made from the league's.)"""

    def __init__(self, kind, values, results=("all",), joint=None, shares=None):
        self.kind = kind
        self.values = values
        self.results = results
        self.joint = joint
        self.shares = shares

    def __repr__(self):
        if self.kind == "counts":
            return "#<transition-counts %d turns>" % round(self.values.sum())
        return "#<transition-probabilities>"


def require_matrix(value, kind, who):
    if not isinstance(value, Transitions):
        raise LispError("%s: expected a matrix of %s, such as transition-counts makes, not %s" % (who, kind, value))
    if kind != "either" and value.kind != kind:
        raise LispError("%s: expected a matrix of %s, not of %s" % (who, kind, value.kind))
    return value


def require_league(value, who):
    """The league's matrix of probabilities: the one smooth-transitions makes of counts with a column result."""
    value = require_matrix(value, "probabilities", who)
    if value.joint is None:
        raise LispError("%s: expected the league's probabilities, from smooth-transitions of counts that have a column result" % who)
    return value


def whole_numbers(column, low, high, what, who):
    """A column of a table as integers, which must all be from low to high."""
    values = floats_of(column, who)
    if not np.all(values == np.round(values)) or values.min(initial=low) < low or values.max(initial=high) > high:
        raise LispError("%s: %s must be whole numbers from %d to %d" % (who, what, low, high))
    return values.astype(np.int64)


def count_column(columns, who):
    """The column count of a table, or a count of 1 for each row if it has none."""
    if any(name == "count" for name, _ in columns):
        counts = floats_of(find_column(columns, "count", who), who)
        if np.any(counts < 0):
            raise LispError("%s: the column count must not be negative" % who)
        return counts
    return np.ones(len(columns[0][1].items) if columns else 0)


def turn_columns(columns, who):
    """The state numbers, the outcome numbers and the counts of a table of turns at bat (a count of 1 for each row, if it has no column count)."""
    parts = {}
    for name, low, high in (("home_batting", 0, 1), ("outs", 0, 2), ("bases", 0, 7), ("new_outs", 0, 3), ("new_bases", 0, 7), ("runs", 0, MAX_RUNS)):
        parts[name] = whole_numbers(find_column(columns, name, who), low, high, "the column " + name, who)
    difference = floats_of(find_column(columns, "score_difference", who), who)
    if not np.all(difference == np.round(difference)):
        raise LispError("%s: the column score_difference must be whole numbers" % who)
    new_bases = np.where(parts["new_outs"] == 3, 0, parts["new_bases"])            # the runners left on base when the inning ends do not matter
    states = state_number(parts["home_batting"], parts["outs"], parts["bases"], difference.astype(np.int64))
    outcomes = outcome_number(parts["new_outs"], new_bases, parts["runs"])
    return states, outcomes, count_column(columns, who)


def result_names(columns, who):
    """The result of each row of a table, as text."""
    return [str(name) for name in find_column(columns, "result", who).items.tolist()]


def transition_counts(table):
    """(transition-counts table) -- how many times each outcome followed each state: a matrix of counts. The table has a row for each turn at bat, or for
    each kind of turn with the number of them in a column count, and the columns home_batting, outs, bases, score_difference (the state it began in),
    new_outs, new_bases and runs (what it came to), and result (what the batter did) if the matrix will be used for a league, as the table turns in the
    database lib/baseball.lsp reads has."""
    who = "transition-counts"
    columns = table_columns(table, who)
    states, outcomes, counts = turn_columns(columns, who)
    if any(name == "result" for name, _ in columns):
        results = result_names(columns, who)
        names = tuple(sorted(set(results)))
        result_numbers = np.array([names.index(result) for result in results], dtype=np.int64)
    else:
        names, result_numbers = ("all",), np.zeros(len(states), dtype=np.int64)
    joint = np.zeros((STATES, OUTCOMES, len(names)))
    np.add.at(joint, (states, outcomes, result_numbers), counts)
    return Transitions("counts", joint.sum(axis=2), names, joint, joint.sum(axis=(0, 1)) / max(joint.sum(), 1))


def row_totals(matrix):
    return matrix.sum(axis=-1, keepdims=True)


def smooth_transitions(counts, *options):
    """(smooth-transitions counts [:weight w]) -- counts as probabilities, with a few imaginary counts added to each state's: w of them (20, if not
    given), spread as the counts of the states with the same outs and runners are, whoever is batting and whatever the score. A state that never
    happened gets those states' probabilities."""
    who = "smooth-transitions"
    weight = keyword_options(options, ["weight"], who).get("weight", 20)
    counts = require_matrix(counts, "counts", who)
    if not is_number(weight) or weight < 0:
        raise LispError("%s: :weight must be a number, 0 or more, not %s" % (who, weight))
    joint = counts.joint
    results = joint.shape[2]
    by_outs_and_runners = joint.reshape(SIDES, OUTS, BASES, DIFFERENCES, OUTCOMES, results).sum(axis=(0, 3))        # 3 x 8 x outcomes x results
    totals = by_outs_and_runners.sum(axis=(2, 3), keepdims=True)
    if np.any(totals == 0):
        raise LispError("%s: there are no turns with some outs and runners (every one of the 24 has to have some)" % who)
    pooled = by_outs_and_runners / totals
    pooled_for_state = np.broadcast_to(pooled[None, :, :, None], (SIDES, OUTS, BASES, DIFFERENCES, OUTCOMES, results)).reshape(STATES, OUTCOMES, results)
    smoothed = (joint + weight * pooled_for_state) / (joint.sum(axis=(1, 2))[:, None, None] + weight)
    return Transitions("probabilities", smoothed.sum(axis=2), counts.results, smoothed, counts.shares)


def profile_counts(profile, results, who):
    """How many turns a player had with each of the results (a vector, in the order of the league's results), from a table of rows with the columns result
    and count."""
    columns = table_columns(profile, who)
    counts = np.zeros(len(results))
    for result, count in zip(result_names(columns, who), count_column(columns, who)):
        if result not in results:
            raise LispError("%s: %s is not a result the league has (it has %s)" % (who, result, ", ".join(results)))
        counts[results.index(result)] += count
    return counts


def player_shares(profile_counts, league_shares, strength):
    """A player's share of each result: his counts plus the prior's (the league's shares times the strength), over his turns plus the strength."""
    return (profile_counts + strength * league_shares) / (profile_counts.sum() + strength)


def tilt_transitions(league, profile, strength):
    """(tilt-transitions league profile strength) -- a player's probabilities: the league's, with each result's counts multiplied by the player's share of the
    result over the league's (see "WHAT MAKES A PLAYER DIFFERENT" at the top of this file), and each state's row scaled to add up to 1. profile is a table of
    the player's turns, with a row for each result and its number of turns in the column count; strength is how many turns the prior is worth."""
    who = "tilt-transitions"
    league = require_league(league, who)
    if not is_number(strength) or strength <= 0:
        raise LispError("%s: the strength must be a number above 0, not %s" % (who, strength))
    shares = player_shares(profile_counts(profile, list(league.results), who), league.shares, strength)
    tilted = league.joint * (shares / league.shares)[None, None, :]
    values = tilted.sum(axis=2)
    return Transitions("probabilities", values / row_totals(values))


def combine_transitions(batter, pitcher, league):
    """(combine-transitions batter pitcher league) -- the probabilities of a batter against a pitcher, from the probabilities of each: see the top of this file."""
    who = "combine-transitions"
    batter = require_matrix(batter, "probabilities", who).values
    pitcher = require_matrix(pitcher, "probabilities", who).values
    league = require_matrix(league, "probabilities", who).values
    combined = np.divide(batter * pitcher, league, out=np.zeros_like(league), where=league > 0)
    totals = row_totals(combined)
    return Transitions("probabilities", np.where(totals > 0, combined / np.where(totals > 0, totals, 1), league))


# ---------------------------------------------------------------------------
# How strongly players are pulled toward the league
# ---------------------------------------------------------------------------

def players_profiles(table, group_column, league, who):
    """A table of the results of players' turns (columns group, result and count) as a matrix with a row for each player and a column for each of the league's results."""
    columns = table_columns(table, who)
    players = [str(name) for name in find_column(columns, group_column, who).items.tolist()]
    player_numbers = np.unique(players, return_inverse=True)[1]
    results = list(league.results)
    result_numbers = []
    for result in result_names(columns, who):
        if result not in results:
            raise LispError("%s: %s is not a result the league has (it has %s)" % (who, result, ", ".join(results)))
        result_numbers.append(results.index(result))
    profiles = np.zeros((player_numbers.max(initial=-1) + 1, len(results)))
    np.add.at(profiles, (player_numbers, np.array(result_numbers, dtype=np.int64)), count_column(columns, who))
    return profiles


def strength_loglik(profiles, shares, strength):
    """The log of the probability of the players' results if each player's shares were drawn from a Dirichlet distribution whose mean is the league's and
    whose strength is given, and his turns from those shares (a Dirichlet-multinomial distribution; the sum of the log-gamma terms of its probability)."""
    prior_counts = strength * shares
    return float((gammaln(strength) - gammaln(profiles.sum(axis=1) + strength)).sum() + (gammaln(profiles + prior_counts) - gammaln(prior_counts)).sum())


def prior_strength_loglik(table, group_column, league, strength):
    """(prior-strength-loglik table group league strength) -- how well a strength explains how the players differ: the log of the probability of their
    results if each player's shares of the results were drawn from a Dirichlet distribution with the league's as its mean and this strength. The higher the
    better. table has a row for each player and result, with the columns group (whose it is), result and count."""
    who = "prior-strength-loglik"
    league = require_league(league, who)
    if not is_number(strength) or strength <= 0:
        raise LispError("%s: the strength must be a number above 0, not %s" % (who, strength))
    return strength_loglik(players_profiles(table, str(group_column), league, who), league.shares, strength)


def prior_strength(table, group_column, league):
    """(prior-strength table group league) -- the strength that explains best how the players differ (the one prior-strength-loglik is highest at): the number
    of turns the league's mix of results is worth when it is the prior for a player's. table has a row for each player and result, with the columns group
    (whose it is), result and count. The bigger it is, the more alike the players are."""
    who = "prior-strength"
    league = require_league(league, who)
    profiles = players_profiles(table, str(group_column), league, who)
    best = minimize_scalar(lambda log_strength: -strength_loglik(profiles, league.shares, np.exp(log_strength)), bounds=(np.log(1.0), np.log(1.0e6)), method="bounded")
    return float(np.exp(best.x))


# ---------------------------------------------------------------------------
# Looking at a matrix
# ---------------------------------------------------------------------------

def transition_table(matrix):
    """(transition-table matrix) -- a matrix as a table with a row for each state and outcome that is possible: the columns of the state, then of the
    outcome (home_batting, outs, bases, score_difference, new_outs, new_bases, runs), and value (the count, or the probability)."""
    who = "transition-table"
    values = require_matrix(matrix, "either", who).values
    states, outcomes = np.nonzero(values)
    return table_of_entries(states, outcomes, values[states, outcomes])


def table_of_entries(states, outcomes, values):
    home_batting, outs, bases, difference = state_parts(states)
    new_outs, new_bases, runs = outcome_parts(outcomes)
    parts = [home_batting, outs, bases, difference, new_outs, new_bases, runs]
    return make_table_value([(name, to_vector(part)) for name, part in zip(STATE_COLUMNS + OUTCOME_COLUMNS, parts)] + [("value", to_vector(values))])


def transition_row(matrix, home_batting, outs, bases, score_difference):
    """(transition-row matrix home-batting outs bases score-difference) -- one state's row of the matrix: a table of the outcomes that happened (new_outs,
    new_bases, runs) and their value (count or probability), most likely first."""
    who = "transition-row"
    values = require_matrix(matrix, "either", who).values
    for what, value, low, high in (("home-batting", home_batting, 0, 1), ("outs", outs, 0, 2), ("bases", bases, 0, 7)):
        if not is_number(value) or value != round(value) or not low <= value <= high:
            raise LispError("%s: %s must be a whole number from %d to %d, not %s" % (who, what, low, high, value))
    if not is_number(score_difference) or score_difference != round(score_difference):
        raise LispError("%s: score-difference must be a whole number, not %s" % (who, score_difference))
    state = int(state_number(int(home_batting), int(outs), int(bases), int(score_difference)))
    row = values[state]
    outcomes = np.flatnonzero(row)
    outcomes = outcomes[np.argsort(-row[outcomes], kind="stable")]
    new_outs, new_bases, runs = outcome_parts(outcomes)
    return make_table_value([("new_outs", to_vector(new_outs)), ("new_bases", to_vector(new_bases)), ("runs", to_vector(runs)),
                             ("value", to_vector(row[outcomes]))])


def state_transition_table(matrix):
    """(state-transition-table matrix) -- the matrix as one of states to next states: a table with a row for each pair of a state and a next state that
    follows from it, with the columns of the state (home_batting, outs, bases, score_difference), those of the next state (next_home_batting,
    next_outs, next_bases, next_score_difference), and value. Outcomes that lead to the same next state are added up."""
    who = "state-transition-table"
    values = require_matrix(matrix, "either", who).values
    states, outcomes = np.nonzero(values)
    following = next_state(states, outcomes)
    keys, key_of_entry = np.unique(states * STATES + following, return_inverse=True)
    added_up = np.bincount(key_of_entry, weights=values[states, outcomes])
    from_parts = state_parts(keys // STATES)
    to_parts = state_parts(keys % STATES)
    columns = list(zip(STATE_COLUMNS, from_parts)) + list(zip(["next_" + name for name in STATE_COLUMNS], to_parts)) + [("value", added_up)]
    return make_table_value([(name, to_vector(part)) for name, part in columns])


def run_expectancy(matrix, *options):
    """(run-expectancy matrix [:weights counts]) -- the runs that are expected to score in the rest of an inning, starting from each of the 24 combinations
    of outs and runners: a table of outs, bases and runs. The 336 states are put together into these 24 by the weights, counts (a matrix of counts) of how
    often each is, which are the matrix's own if it is of counts. (Put a player's probabilities in, and the league's counts as weights, and it is the
    runs that player's turns are worth in the situations the league is in.)"""
    who = "run-expectancy"
    weights = keyword_options(options, ["weights"], who).get("weights")
    matrix = require_matrix(matrix, "either", who)
    if weights is None:
        if matrix.kind != "counts":
            raise LispError("%s: a matrix of probabilities needs :weights, a matrix of counts" % who)
        weights = matrix
    weight_of_state = require_matrix(weights, "counts", who).values.sum(axis=1)
    rows = matrix.values / (row_totals(matrix.values) if matrix.kind == "counts" else 1)
    weighted = rows * weight_of_state[:, None]
    # Put the states together: a row for each of the 24 combinations of outs and runners, a column for each outcome.
    together = weighted.reshape(SIDES, OUTS, BASES, DIFFERENCES, OUTCOMES).sum(axis=(0, 3)).reshape(OUTS * BASES, OUTCOMES)
    total_weight = weight_of_state.reshape(SIDES, OUTS, BASES, DIFFERENCES).sum(axis=(0, 3)).reshape(OUTS * BASES)
    if np.any(total_weight == 0):
        raise LispError("%s: some outs and runners never happen in the weights" % who)
    probabilities = together / total_weight[:, None]
    new_outs, new_bases, runs = outcome_parts(np.arange(OUTCOMES))
    continues = new_outs < 3
    next_combination = np.where(continues, new_outs * BASES + new_bases, 0)
    # The expected runs R of each combination satisfy R = (expected runs of the turn) + (the chance of each combination next) x R.
    chance_of_next = np.zeros((OUTS * BASES, OUTS * BASES))
    for outcome in np.flatnonzero(continues):
        chance_of_next[:, next_combination[outcome]] += probabilities[:, outcome]
    turn_runs = probabilities @ runs
    expected = np.linalg.solve(np.eye(OUTS * BASES) - chance_of_next, turn_runs)
    combination = np.arange(OUTS * BASES)
    return make_table_value([("outs", to_vector(combination // BASES)), ("bases", to_vector(combination % BASES)), ("runs", to_vector(expected))])


# ---------------------------------------------------------------------------
# Playing games
# ---------------------------------------------------------------------------

def team_of(team, who):
    """A team for simulate-games: a list of a list of nine matrices (its batters against the other team's starting pitcher), a list of nine (against the
    other team's relievers), and the number of batters that its own starting pitcher faces before a reliever comes in. Cumulative probabilities
    (shape 2 x 9 x states x outcomes) and the batters."""
    if not isinstance(team, Pair) or len(pairs_to_list(team)) != 3:
        raise LispError("%s: a team is a list of three things: nine matrices against the starter, nine against the relievers, and the batters the starter "
                        "faces" % who)
    against_starter, against_relievers, starter_batters = pairs_to_list(team)
    lineups = []
    for lineup in (against_starter, against_relievers):
        matrices = pairs_to_list(lineup) if isinstance(lineup, Pair) else []
        if len(matrices) != 9:
            raise LispError("%s: a team's batters are nine, not %d" % (who, len(matrices)))
        lineups.append(np.array([require_matrix(matrix, "probabilities", who).values for matrix in matrices]))
    if not is_number(starter_batters) or starter_batters < 1:
        raise LispError("%s: the batters a starter faces must be a number, 1 or more, not %s" % (who, starter_batters))
    cumulative = np.cumsum(np.array(lineups), axis=3)
    cumulative /= cumulative[..., -1:]
    return cumulative, float(starter_batters)


def simulate_games(home, away, *options):
    """(simulate-games home away [:games n] [:seed n] [:ghost-runner #t]) -- play games between two teams, and give the results as a table with a row for each
    game: home_runs, visiting_runs and innings. A team is a list of three things: a list of nine matrices of probabilities, those of its batters in the order
    they bat against the other team's starting pitcher (combine-transitions makes each); a list of nine, against the other team's relievers; and the number of
    batters that its own starter faces before a reliever comes in."""
    who = "simulate-games"
    options = keyword_options(options, ["games", "seed", "ghost-runner"], who)
    games = options.get("games", 10000)
    if not is_number(games) or games < 1 or games != round(games):
        raise LispError("%s: :games must be a whole number, 1 or more, not %s" % (who, games))
    games = int(games)
    ghost_runner = options.get("ghost-runner", True) is not False
    seed = options.get("seed", NIL)
    generator = np.random.default_rng(int(seed) if seed is not NIL else random.getrandbits(63))
    # Index 0 of each array is the visiting team, 1 the home team.
    visiting_cumulative, visiting_starter_batters = team_of(away, who)
    home_cumulative, home_starter_batters = team_of(home, who)
    cumulative = np.array([visiting_cumulative, home_cumulative])           # team x (starter or relievers) x slot x state x outcome
    starter_batters = np.array([visiting_starter_batters, home_starter_batters])

    inning = np.ones(games, dtype=np.int64)
    batting = np.zeros(games, dtype=np.int64)                               # 0: the visitors, 1: the home team
    outs = np.zeros(games, dtype=np.int64)
    bases = np.zeros(games, dtype=np.int64)
    score = np.zeros((games, 2), dtype=np.int64)
    slot = np.zeros((games, 2), dtype=np.int64)                             # who is up next in each team's order
    faced = np.zeros((games, 2), dtype=np.int64)                            # how many batters each team's starter has faced
    innings_played = np.zeros(games, dtype=np.int64)
    playing = np.arange(games)                                              # the games not over
    while len(playing):
        team = batting[playing]
        other = 1 - team
        game_slot = slot[playing, team]
        reliever = (faced[playing, other] >= starter_batters[other]).astype(np.int64)
        difference = score[playing, team] - score[playing, other]
        rows = cumulative[team, reliever, game_slot, state_number(team, outs[playing], bases[playing], difference)]
        draws = generator.random(len(playing))
        outcome = np.minimum((rows < draws[:, None]).sum(axis=1), OUTCOMES - 1)
        new_outs, new_bases, runs = outcome_parts(outcome)

        score[playing, team] += runs
        slot[playing, team] = (game_slot + 1) % 9
        faced[playing, other] += 1
        outs[playing], bases[playing] = new_outs, new_bases

        home_ahead = score[playing, 1] > score[playing, 0]
        walk_off = (team == 1) & (inning[playing] >= LAST_REGULAR_INNING) & home_ahead
        inning_over = (new_outs == 3) & ~walk_off
        late = inning[playing] >= LAST_REGULAR_INNING
        decided = (score[playing, 1] != score[playing, 0])
        # the game is over when the home team wins in the bottom of the last inning, or when the top of it ends with the home team ahead, or
        # when the bottom of it ends with someone ahead
        over = walk_off | (inning_over & late & ((team == 0) & home_ahead | (team == 1) & decided))
        over |= inning_over & (team == 1) & (inning[playing] >= LAST_INNING_PLAYED)

        innings_played[playing[over]] = inning[playing[over]]
        # the next half inning begins
        next_batting = np.where(inning_over, 1 - team, team)
        next_inning = inning[playing] + (inning_over & (team == 1))
        batting[playing] = next_batting
        inning[playing] = next_inning
        outs[playing] = np.where(inning_over, 0, outs[playing])
        starts_with_runner = ghost_runner & (next_inning > LAST_REGULAR_INNING)
        bases[playing] = np.where(inning_over, np.where(starts_with_runner, GHOST_RUNNER_BASES, 0), bases[playing])
        playing = playing[~over]
    return make_table_value([("home_runs", to_vector(score[:, 1])), ("visiting_runs", to_vector(score[:, 0])), ("innings", to_vector(innings_played))])


BUILTINS = {
    "transition-counts": transition_counts,
    "smooth-transitions": smooth_transitions,
    "tilt-transitions": tilt_transitions,
    "combine-transitions": combine_transitions,
    "prior-strength": prior_strength,
    "prior-strength-loglik": prior_strength_loglik,
    "run-expectancy": run_expectancy,
    "transition-table": transition_table,
    "transition-row": transition_row,
    "state-transition-table": state_transition_table,
    "simulate-games": simulate_games,
}
