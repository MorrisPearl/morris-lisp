"""Tests of turns.py: turns at bat made from rows that are made here by hand, the way Retrosheet's parsed play-by-play has them.

    python3 -m unittest test_turns.py
"""

import unittest

from turns import TURN_COLUMNS, game_of, turns_of_game


def row(event="K", inning=1, top_bot=0, batter="batter1", pitcher="pitcherA", batteam="VIS", pitteam="HOM", pa=1, outs_pre=0, outs_post=1,
        pre=(0, 0, 0), post=(0, 0, 0), runs=0, score_v=0, score_h=0, **flags):
    """A row of the file: a play. pre and post are whether there is a runner on first, second and third, before and after."""
    result = {"gid": "HOM202604010", "date": "20260401", "gametype": "regular", "event": event, "inning": str(inning), "top_bot": str(top_bot),
              "vis_home": str(top_bot), "batter": batter, "pitcher": pitcher, "batteam": batteam, "pitteam": pitteam, "pa": str(pa),
              "outs_pre": str(outs_pre), "outs_post": str(outs_post), "runs": str(runs), "score_v": str(score_v), "score_h": str(score_h)}
    for base, (before, after) in enumerate(zip(pre, post), start=1):
        result["br%d_pre" % base] = "runner" if before else ""
        result["br%d_post" % base] = "runner" if after else ""
    for flag in ("k", "walk", "hbp", "xi", "single", "double", "triple", "hr"):
        result[flag] = "1" if flags.get(flag) else "0"
    return result


def as_dict(turn):
    return dict(zip(TURN_COLUMNS, turn))


class TestTurns(unittest.TestCase):

    def test_a_strikeout_is_a_turn_from_one_state_to_the_next(self):
        turns, _ = turns_of_game([row(k=True)])
        turn = as_dict(turns[0])
        self.assertEqual((turn["outs"], turn["bases"], turn["new_outs"], turn["new_bases"], turn["runs"], turn["result"], turn["plate_appearance"]),
                         (0, 0, 1, 0, 0, "strikeout", 1))

    def test_bases_are_one_for_first_two_for_second_and_four_for_third(self):
        turns, _ = turns_of_game([row("S8", single=True, outs_pre=1, outs_post=1, pre=(1, 0, 1), post=(1, 0, 1), runs=1, score_v=0, score_h=2)])
        turn = as_dict(turns[0])
        self.assertEqual((turn["bases"], turn["new_bases"], turn["runs"], turn["result"]), (5, 5, 1, "single"))

    def test_the_score_difference_is_the_batting_teams(self):
        visitors, _ = turns_of_game([row(top_bot=0, score_v=1, score_h=4)])
        home, _ = turns_of_game([row(top_bot=1, score_v=1, score_h=4)])
        self.assertEqual((as_dict(visitors[0])["score_difference"], as_dict(home[0])["score_difference"]), (-3, 3))

    def test_a_steal_during_the_at_bat_is_part_of_the_turn(self):
        rows = [row("SB2", pa=0, outs_pre=0, outs_post=0, pre=(1, 0, 0), post=(0, 1, 0)),
                row("S7", single=True, outs_pre=0, outs_post=0, pre=(0, 1, 0), post=(1, 0, 1), runs=0)]
        turns, _ = turns_of_game(rows)
        self.assertEqual(len(turns), 1)
        turn = as_dict(turns[0])
        self.assertEqual((turn["bases"], turn["new_bases"], turn["result"]), (1, 5, "single"))

    def test_runs_in_the_steal_and_the_plate_appearance_add_up(self):
        rows = [row("SB3", pa=0, outs_pre=1, outs_post=1, pre=(0, 0, 1), post=(0, 0, 0), runs=1),          # (stealing home)
                row("K", k=True, outs_pre=1, outs_post=2, runs=0)]
        turn = as_dict(turns_of_game(rows)[0][0])
        self.assertEqual((turn["runs"], turn["new_outs"]), (1, 2))

    def test_a_runner_caught_for_the_third_out_ends_the_turn_without_a_plate_appearance(self):
        rows = [row("CS2", pa=0, outs_pre=2, outs_post=3, pre=(1, 0, 0), post=(0, 0, 0)),
                row("K", batter="batter2", k=True, inning=1, top_bot=1, batteam="HOM", pitteam="VIS", pitcher="pitcherB", outs_pre=0, outs_post=1)]
        turns, _ = turns_of_game(rows)
        first = as_dict(turns[0])
        self.assertEqual((first["new_outs"], first["plate_appearance"], first["result"]), (3, 0, "none"))
        self.assertEqual(len(turns), 2)

    def test_the_runners_left_on_base_when_the_inning_ends_are_forgotten(self):
        turn = as_dict(turns_of_game([row("K", k=True, outs_pre=2, outs_post=3, pre=(1, 1, 1), post=(1, 1, 1))])[0][0])
        self.assertEqual((turn["new_outs"], turn["new_bases"]), (3, 0))

    def test_a_no_play_row_is_not_a_turn(self):
        rows = [row("NP", pa=0, outs_pre=0, outs_post=0), row(k=True), row("NP", pa=0, outs_pre=3, outs_post=3)]
        turns, _ = turns_of_game(rows)
        self.assertEqual(len(turns), 1)

    def test_results(self):
        for flags, expected in ((dict(walk=True), "walk"), (dict(hbp=True), "walk"), (dict(xi=True), "walk"), (dict(double=True), "double"),
                                (dict(triple=True), "triple"), (dict(hr=True), "home run"), (dict(), "other")):
            self.assertEqual(as_dict(turns_of_game([row(**flags)])[0][0])["result"], expected)

    def test_the_first_pitcher_each_team_used_started(self):
        rows = [row(k=True), row("K", k=True, pitcher="pitcherA", outs_pre=1, outs_post=2),
                row("K", k=True, pitcher="reliever", outs_pre=2, outs_post=3, inning=2)]
        turns, _ = turns_of_game(rows)
        self.assertEqual([as_dict(t)["starter"] for t in turns], [1, 1, 0])

    def test_a_turn_knows_how_many_batters_its_pitcher_faced_and_whether_he_is_replaced_after_it(self):
        rows = [row(k=True), row("K", k=True, outs_pre=1, outs_post=2),
                row("K", k=True, outs_pre=2, outs_post=3),
                row("K", k=True, inning=2, pitcher="reliever", outs_pre=0, outs_post=1),
                row("K", k=True, inning=2, pitcher="reliever", outs_pre=1, outs_post=2),
                row("K", k=True, batter="other", top_bot=1, batteam="HOM", pitteam="VIS", pitcher="pitcherB", outs_pre=0, outs_post=1)]
        turns, _ = turns_of_game(rows)
        self.assertEqual([(as_dict(t)["batters_faced"], as_dict(t)["removed_after"]) for t in turns],
                         [(0, 0), (1, 0), (2, 1), (0, 0), (1, 0), (0, 0)])

    def test_the_game_is_the_final_score(self):
        rows = [row(top_bot=0, runs=1, hr=True, score_v=2, score_h=3, inning=9, outs_pre=0, outs_post=0),
                row(top_bot=1, batteam="HOM", pitteam="VIS", runs=2, hr=True, score_v=3, score_h=3, inning=9, outs_pre=1, outs_post=1, pre=(1, 0, 0))]
        game = game_of(rows)
        self.assertEqual(game, ("HOM202604010", 2026, "20260401", "regular", "VIS", "HOM", 3, 5, 9))


if __name__ == "__main__":
    unittest.main()
