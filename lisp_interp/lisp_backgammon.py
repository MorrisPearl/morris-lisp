"""The exact chance of winning a backgammon end game, for the Lisp interpreter.

  (backgammon-bearoff-chance board)
        the chance that the player on roll wins, if the position is one of the
        end games below; #f if it is not

The positions are those where nothing can be hit and neither side has a checker
outside its own home board, and each side either has 1 to 6 checkers left (on
any of its six points), or has up to 14 checkers all on its 1 point (a stack).
Each side has borne off at least one checker, so there are no gammons: the
game is a pure race, won by the side that bears off its last checker first.
The player on roll chooses, for each of the 36 rolls, the play that gives the
best chance of winning, so the chances are found by working backwards from the
positions where a side has borne off every checker (see work_out_chances).

There are 931 ways for a side to have its checkers (its SIDE STATES), so 931 x 931
positions. They take a few seconds to work out, the first time one is asked for.

The board is as in lib/backgammon.lsp: a vector of 26 numbers, the bar (0), points 1
to 24 and the opponent's bar (25), the checkers of the player on roll positive and
the opponent's negative, the player on roll moving down from 24 toward 1.
So the player on roll's checkers are on points 1 to 6, and the opponent's on
points 19 to 24 (its own points 6 down to 1).
"""

import numpy as np

from lisp_core import LispError
from lisp_vector_math import numbers_of

MOST_CHECKERS = 6       # a side's checkers may be on any of its points when it has this many or fewer
LARGEST_STACK = 14      # or all on its 1 point, up to this many (the 15th would mean it has borne off none)


def compositions(total, parts):
    """Every way of writing total as a list of parts whole numbers (0 or more)."""
    if parts == 1:
        return [(total,)]
    ways = []
    for first in range(total + 1):
        for rest in compositions(total - first, parts - 1):
            ways.append((first,) + rest)
    return ways


def side_states():
    """The ways one side can have its checkers: a count for each of its points 1 to 6."""
    states = []
    for checkers in range(1, MOST_CHECKERS + 1):
        states.extend(compositions(checkers, 6))
    for checkers in range(MOST_CHECKERS + 1, LARGEST_STACK + 1):
        states.append((checkers, 0, 0, 0, 0, 0))
    return states


def state_key(counts):
    """One number for a side state: its counts as the digits of a number in base 16."""
    return sum(count << (4 * point) for point, count in enumerate(counts))


def play_one_die(counts, die):
    """The side states that playing one die can lead to, from the state counts.
    A checker moves down by the die, or is borne off by a die as large as its
    point, or larger if no checker is on a higher point."""
    highest = max(point for point in range(6) if counts[point] > 0) if any(counts) else -1
    results = set()
    for point in range(6):
        if counts[point] == 0:
            continue
        if point + 1 > die:
            to_point = point - die
        elif point + 1 == die or point == highest:
            to_point = None                 # borne off
        else:
            continue
        new = list(counts)
        new[point] -= 1
        if to_point is not None:
            new[to_point] += 1
        results.add(tuple(new))
    return results


def play_dice(counts, dice):
    """The side states that playing all of these dice, in this order, can lead
    to. A side with no checkers left has won: it stays as it is."""
    states = {counts}
    for die in dice:
        next_states = set()
        for state in states:
            if any(state):
                next_states |= play_one_die(state, die)
            else:
                next_states.add(state)
        states = next_states
    return states


def rolls():
    """The 21 different rolls: the dice to play (four for a double) and the chance of the roll."""
    all_rolls = []
    for low in range(1, 7):
        for high in range(low, 7):
            if low == high:
                all_rolls.append(([low] * 4, 1 / 36))
            else:
                all_rolls.append(([low, high], 2 / 36))
    return all_rolls


FINISHED = -1       # in the successors: the side has borne off its last checker
NOT_A_STATE = -2    # in the successors: padding, to make every row the same length


class BearoffTable:
    """The chance of winning, for every pair of side states: chances[i, j] is the
    chance that the player on roll wins, when its checkers are in side state i and its
    opponent's are in side state j."""

    def __init__(self):
        self.states = side_states()
        self.index = {state_key(state): i for i, state in enumerate(self.states)}
        self.chances = work_out_chances(self.states, self.index)


def work_out_chances(states, index):
    """The matrix of chances. For every side state and roll, the side states
    the roll can lead to are found first (they do not depend on the opponent).
    Then the positions are taken in order of their total pips: a play always
    lowers the player on roll's pips, and the opponent then rolls, so every
    position needs only positions with fewer pips in all."""
    count = len(states)
    pips = np.array([sum((point + 1) * n for point, n in enumerate(state)) for state in states])
    roll_list = rolls()
    successors = []
    for dice, chance in roll_list:
        results = []
        for state in states:
            # the dice may be played in either order (the same, for a double)
            results_of_roll = play_dice(state, dice) | play_dice(state, dice[::-1])
            leads_to = [FINISHED if not any(new) else index[state_key(new)] for new in results_of_roll]
            results.append(sorted(leads_to))
        width = max(len(row) for row in results)
        successors.append(np.array([row + [NOT_A_STATE] * (width - len(row)) for row in results]))
    weights = [chance for dice, chance in roll_list]

    chances = np.zeros((count, count))
    total_pips = pips[:, None] + pips[None, :]
    for total in np.unique(total_pips):
        player, opponent = np.nonzero(total_pips == total)
        chance = np.zeros(len(player))
        for after, weight in zip(successors, weights):
            leads_to = after[player]                                    # one row for each position
            real = leads_to >= 0
            # the chance of winning is 1 if the roll finishes, else 1 minus what the opponent has
            value = np.where(real, 1.0 - chances[opponent[:, None], np.where(real, leads_to, 0)], 1.0)
            value = np.where(leads_to == NOT_A_STATE, -1.0, value)
            chance += weight * value.max(axis=1)
        chances[player, opponent] = np.clip(chance, 0.0, 1.0)     # rounding can leave 1.0000000000000002
    return chances


table = None


def bearoff_table():
    """The table, worked out the first time it is needed."""
    global table
    if table is None:
        table = BearoffTable()
    return table


def bearoff_chance(board):
    """(backgammon-bearoff-chance board) -- the chance that the player on roll wins this end game
    (see the top of lisp_backgammon.py), or #f if the position is not one of them."""
    items = numbers_of(board, "backgammon-bearoff-chance")
    if len(items) != 26:
        raise LispError("backgammon-bearoff-chance: a board has 26 numbers, not %d" % len(items))
    # a quick way out for almost every position: a checker on the bar, or outside its side's home board
    if items[0] != 0 or items[25] != 0 or np.any(items[7:19] != 0) or np.any(items[1:7] < 0) or np.any(items[19:25] > 0):
        return False
    mover = items[1:7].astype(int)
    opponent = -items[19:25][::-1].astype(int)      # the opponent's counts on its points 1 to 6
    table = bearoff_table()
    mover_state = table.index.get(state_key(mover))
    opponent_state = table.index.get(state_key(opponent))
    if mover_state is None or opponent_state is None:
        return False
    return float(table.chances[mover_state, opponent_state])


BUILTINS = {
    "backgammon-bearoff-chance": bearoff_chance,
}
