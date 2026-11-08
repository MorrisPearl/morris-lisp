"""Turns at bat, made from Retrosheet's parsed play-by-play rows.

A ROW of Retrosheet's file is one event: a batter's plate appearance, or something that happens during one (a stolen base, a wild pitch, a pickoff).
A TURN is what the model counts: everything that happens from the moment a batter steps up until his plate appearance ends (or the inning does,
if a runner is caught stealing for the third out). So a steal during an at bat is part of that batter's turn, and a turn always begins in the state
that the turn before it ended in -- which is what makes the turns a chain a simulation can follow.

A turn has a START (the outs, the runners on base, and the score difference when it began) and an END (the outs and the runners when it ended, and how
many runs scored in between). The end is the whole of what a simulation needs to know: the next state is made from it.

Bases are a number from 0 to 7: 1 for a runner on first, 2 for second, 4 for third, added up (5 is runners on first and third).
"""

PITCHER_COLUMNS = ["batters_faced", "removed_after"]      # the last two columns: see add_pitcher_usage

TURN_COLUMNS = ["gid", "season", "date", "gametype", "inning", "home_batting", "batting_team", "pitching_team", "batter", "pitcher", "starter",
                "outs", "bases", "score_difference", "new_outs", "new_bases", "runs", "plate_appearance", "result", "batters_faced", "removed_after"]


def bases_of(row, when):
    """The runners on base in a row, before the play (when is 'pre') or after it ('post'), as a number from 0 to 7."""
    return ((1 if row["br1_" + when] else 0) + (2 if row["br2_" + when] else 0) + (4 if row["br3_" + when] else 0))


def score_difference(row):
    """The batting team's score less the other team's, at the start of the play."""
    visitors, home = int(row["score_v"]), int(row["score_h"])
    return home - visitors if row["vis_home"] == "1" else visitors - home


def result_of(last):
    """What the turn came to, from the row that ended it: "strikeout", "walk" (a walk, a hit by pitch, or interference), "single", "double", "triple",
    "home run", "other" (any other plate appearance: the ball in play for an out, or an error, a fielder's choice, a sacrifice) or "none" (the turn ended
    with the inning, in a steal that was caught, without the batter's plate appearance being over)."""
    if last["pa"] != "1":
        return "none"
    for column, result in (("k", "strikeout"), ("walk", "walk"), ("hbp", "walk"), ("xi", "walk"), ("single", "single"), ("double", "double"),
                           ("triple", "triple"), ("hr", "home run")):
        if last[column] == "1":
            return result
    return "other"


def turn_of(first, last, runs, starters):
    """The turn that begins with the row `first` and ends with the row `last`, in which `runs` scored (a tuple in the order of TURN_COLUMNS).
    starters says who started the game for each team: {pitching team: pitcher}."""
    outs_after = int(last["outs_post"])
    return (first["gid"], int(first["date"][:4]), first["date"], first["gametype"], int(first["inning"]), int(first["vis_home"]),
            first["batteam"], first["pitteam"], last["batter"], last["pitcher"], 1 if starters[last["pitteam"]] == last["pitcher"] else 0,
            int(first["outs_pre"]), bases_of(first, "pre"), score_difference(first),
            outs_after, 0 if outs_after == 3 else bases_of(last, "post"), runs, int(last["pa"]), result_of(last))


def add_pitcher_usage(turns):
    """The turns, each with two more values at the end: how many batters its pitcher had faced in the game before it (batters_faced), and whether he is replaced
    right after it (removed_after: 1 if the next turn of his team's pitching in the game is another pitcher's, 0 if it is his own or the game ends)."""
    pitching_team, pitcher = TURN_COLUMNS.index("pitching_team"), TURN_COLUMNS.index("pitcher")
    faced = {}                          # (team, pitcher) -> the batters he has faced
    last_of_team = {}                   # team -> the position in turns of its last turn so far
    removed = [0] * len(turns)
    for position, turn in enumerate(turns):
        previous = last_of_team.get(turn[pitching_team])
        if previous is not None and turns[previous][pitcher] != turn[pitcher]:
            removed[previous] = 1
        last_of_team[turn[pitching_team]] = position
    usage = []
    for position, turn in enumerate(turns):
        key = (turn[pitching_team], turn[pitcher])
        usage.append(turn + (faced.get(key, 0), removed[position]))
        faced[key] = faced.get(key, 0) + 1
    return usage


def turns_of_game(rows):
    """The turns of one game, from its rows in order; and the game's result: (turns, game), where game is
    (gid, season, date, gametype, visiting team, home team, visiting runs, home runs, innings)."""
    rows = [row for row in rows if row["event"] != "NP"]        # "no play": the file notes a substitution, and nothing happens
    turns = []
    starters = {}                       # the first pitcher each team used
    for row in rows:
        starters.setdefault(row["pitteam"], row["pitcher"])
    first = None                        # the first row of the turn that is going on
    runs = 0
    last = None
    for row in rows:
        if first is not None and (row["inning"], row["top_bot"]) != (first["inning"], first["top_bot"]):
            turns.append(turn_of(first, last, runs, starters))      # the inning ended without a plate appearance (can happen when a game ends)
            first = None
        if first is None:
            first, runs = row, 0
        runs += int(row["runs"])
        last = row
        if row["pa"] == "1" or int(row["outs_post"]) == 3:
            turns.append(turn_of(first, last, runs, starters))
            first = None
    if first is not None:
        turns.append(turn_of(first, last, runs, starters))
    return add_pitcher_usage(turns), game_of(rows)


def game_of(rows):
    """The result of a game: (gid, season, date, gametype, visiting team, home team, visiting runs, home runs, innings)."""
    first, last = rows[0], rows[-1]
    visiting_team = first["batteam"] if first["vis_home"] == "0" else first["pitteam"]
    home_team = first["pitteam"] if first["vis_home"] == "0" else first["batteam"]
    visiting_runs = int(last["score_v"]) + (int(last["runs"]) if last["vis_home"] == "0" else 0)
    home_runs = int(last["score_h"]) + (int(last["runs"]) if last["vis_home"] == "1" else 0)
    return (first["gid"], int(first["date"][:4]), first["date"], first["gametype"], visiting_team, home_team, visiting_runs, home_runs, int(last["inning"]))
