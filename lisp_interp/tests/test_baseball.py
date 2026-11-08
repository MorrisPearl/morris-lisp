"""Baseball as a chain of states (lisp_baseball.py and lib/baseball.lsp). The arithmetic is checked against sums done here by hand: smoothing and shrinking,
combining a batter and a pitcher, run expectancy against a recursion, the strength of a prior against players drawn from a Dirichlet distribution of a
known strength. The games are checked on teams whose every turn is certain, so that the scores and the length of the game are known; and the library on a
small database made here in the form that load_retrosheet_data/ makes."""

import sqlite3
import tempfile

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase
import lisp_baseball as baseball

COLUMNS = ["home_batting", "outs", "bases", "score_difference", "new_outs", "new_bases", "runs"]


def table_of(rows, results=None):
    """A Lisp table from rows of (home_batting, outs, bases, score_difference, new_outs, new_bases, runs, count), and, if results is given, a column result."""
    array = np.array(rows, dtype=float)
    names = COLUMNS + ["count"]
    columns = [(name, lisp_vector_math.to_vector(array[:, i])) for i, name in enumerate(names)]
    if results is not None:
        columns.append(("result", lisp_core.LispVector(np.array(results, dtype=object))))
    return lisp_tables.make_table_value(columns)


def results_table(counts_by_result, player=None):
    """A table of a player's turns by result: a row for each result in the dictionary, with the number of turns in the column count."""
    columns = [("result", lisp_core.LispVector(np.array(list(counts_by_result), dtype=object))),
               ("count", lisp_vector_math.to_vector(np.array(list(counts_by_result.values()), dtype=float)))]
    return lisp_tables.make_table_value(columns)


def league_of_strikeouts_and_singles():
    """The league's probabilities, of counts in which every state has 3 strikeouts and 1 single: the shares of the results are 3/4 and 1/4."""
    rows, results = [], []
    for row in every_state_has_a_strikeout_and_a_single():
        rows.append(row)
        results.append("strikeout" if row[4] == row[1] + 1 else "single")
    return baseball.smooth_transitions(baseball.transition_counts(table_of(rows, results)))


def all_outs_and_runners():
    return [(outs, bases) for outs in range(3) for bases in range(8)]


def every_state_has_a_strikeout_and_a_single():
    """Rows with, for every state (home batting or not, outs, bases, score difference): a strikeout 3 times and a single once."""
    rows = []
    for home in range(2):
        for difference in range(-3, 4):
            for outs, bases in all_outs_and_runners():
                rows.append((home, outs, bases, difference, outs + 1, bases if outs < 2 else 0, 0, 3))
                rows.append((home, outs, bases, difference, outs, 1, 0, 1))
    return rows


def a_matrix(probabilities_by_state):
    """A matrix of probabilities (336 x 160) from a function of the state's (home_batting, outs, bases, difference) that gives {outcome: probability}."""
    values = np.zeros((baseball.STATES, baseball.OUTCOMES))
    for state in range(baseball.STATES):
        home, outs, bases, difference = (int(part) for part in baseball.state_parts(np.array(state)))
        for (new_outs, new_bases, runs), probability in probabilities_by_state(home, outs, bases, difference).items():
            values[state, baseball.outcome_number(new_outs, new_bases, runs)] = probability
    return baseball.Transitions("probabilities", values)


class TestStatesAndOutcomes(LispTestCase):

    def test_a_state_number_and_its_parts_are_the_same_thing(self):
        states = np.arange(baseball.STATES)
        home, outs, bases, difference = baseball.state_parts(states)
        self.assertEqual(list(baseball.state_number(home, outs, bases, difference)), list(states))
        self.assertEqual((home.max(), outs.max(), bases.max(), difference.min(), difference.max()), (1, 2, 7, -3, 3))

    def test_an_outcome_number_and_its_parts_are_the_same_thing(self):
        outcomes = np.arange(baseball.OUTCOMES)
        parts = baseball.outcome_parts(outcomes)
        self.assertEqual(list(baseball.outcome_number(*parts)), list(outcomes))

    def test_a_score_difference_of_more_than_three_is_three(self):
        self.assertEqual(baseball.state_number(0, 1, 2, 9), baseball.state_number(0, 1, 2, 3))
        self.assertEqual(baseball.state_number(0, 1, 2, -9), baseball.state_number(0, 1, 2, -3))

    def test_the_next_state_after_an_outcome(self):
        state = baseball.state_number(0, 1, 2, 3)
        # a single scoring from second: the runner is on first, and a run has scored (the difference stays 3: it is 3 or more)
        after_a_single = baseball.outcome_number(1, 1, 1)
        self.assertEqual(baseball.next_state(state, after_a_single), baseball.state_number(0, 1, 1, 3))
        # the third out: the other team bats, with no one out or on, and the lead the other way round (and the run that scored on the play counted)
        third_out = baseball.outcome_number(3, 0, 1)
        self.assertEqual(baseball.next_state(baseball.state_number(0, 2, 7, 0), third_out), baseball.state_number(1, 0, 0, -1))


class TestCounting(LispTestCase):

    def test_counts_are_added_up_by_state_and_outcome(self):
        counts = self.run_lisp("")  # nothing to check yet: this is only to have the environment
        table = table_of([(0, 0, 0, 0, 1, 0, 0, 2), (0, 0, 0, 0, 1, 0, 0, 3), (0, 0, 0, 0, 0, 1, 0, 4), (1, 2, 7, 3, 3, 0, 1, 5)])
        counts = baseball.transition_counts(table)
        self.assertEqual(repr(counts), "#<transition-counts 14 turns>")
        row = counts.values[baseball.state_number(0, 0, 0, 0)]
        self.assertEqual((row[baseball.outcome_number(1, 0, 0)], row[baseball.outcome_number(0, 1, 0)]), (5, 4))
        self.assertEqual(counts.values[baseball.state_number(1, 2, 7, 3), baseball.outcome_number(3, 0, 1)], 5)

    def test_a_row_without_a_count_column_is_one_turn(self):
        columns = [(name, lisp_vector_math.to_vector(np.array([value]))) for name, value in zip(COLUMNS, (0, 0, 0, 0, 1, 0, 0))]
        self.assertEqual(baseball.transition_counts(lisp_tables.make_table_value(columns)).values.sum(), 1)

    def test_the_runners_left_on_when_an_inning_ends_do_not_matter(self):
        table = table_of([(0, 2, 7, 0, 3, 7, 0, 1), (0, 2, 7, 0, 3, 0, 0, 1)])
        counts = baseball.transition_counts(table)
        self.assertEqual(counts.values[baseball.state_number(0, 2, 7, 0), baseball.outcome_number(3, 0, 0)], 2)

    def test_a_column_out_of_range_is_an_error(self):
        with self.assertRaisesRegex(lisp_core.LispError, "outs must be whole numbers from 0 to 2"):
            baseball.transition_counts(table_of([(0, 3, 0, 0, 3, 0, 0, 1)]))
        with self.assertRaisesRegex(lisp_core.LispError, "no column named 'home_batting'"):
            baseball.transition_counts(lisp_tables.make_table_value([("outs", lisp_vector_math.to_vector(np.array([1])))]))


class TestSmoothing(LispTestCase):

    def setUp(self):
        super().setUp()
        self.counts = baseball.transition_counts(table_of(every_state_has_a_strikeout_and_a_single()))

    def test_every_row_of_smoothed_counts_adds_up_to_one(self):
        league = baseball.smooth_transitions(self.counts)
        self.assertTrue(np.allclose(league.values.sum(axis=1), 1))

    def test_weight_0_gives_the_proportions_of_the_counts(self):
        league = baseball.smooth_transitions(self.counts, lisp_core.Keyword(":weight"), 0)
        state = baseball.state_number(1, 1, 0, 2)
        self.assertAlmostEqual(league.values[state, baseball.outcome_number(2, 0, 0)], 0.75)
        self.assertAlmostEqual(league.values[state, baseball.outcome_number(1, 1, 0)], 0.25)

    def test_a_state_that_never_happened_gets_the_probabilities_of_the_states_like_it(self):
        rows = [row for row in every_state_has_a_strikeout_and_a_single() if not (row[0] == 1 and row[3] == 3)]
        counts = baseball.transition_counts(table_of(rows))
        league = baseball.smooth_transitions(counts)
        self.assertTrue(np.allclose(league.values[baseball.state_number(1, 0, 0, 3)], league.values[baseball.state_number(0, 0, 0, 3)]))

    def test_smoothing_adds_the_weight_of_imaginary_counts_spread_as_the_pooled_states_are(self):
        # the state's own counts are 3 strikeouts and 1 single; the pooled states' are the same proportions, so the proportions do not change
        league = baseball.smooth_transitions(self.counts, lisp_core.Keyword(":weight"), 100)
        self.assertAlmostEqual(league.values[baseball.state_number(0, 0, 0, 0), baseball.outcome_number(1, 0, 0)], 0.75)

    def test_the_arguments_must_be_the_right_kind_of_matrix(self):
        with self.assertRaisesRegex(lisp_core.LispError, "expected a matrix of counts"):
            baseball.smooth_transitions(baseball.smooth_transitions(self.counts))


class TestTilting(LispTestCase):

    def setUp(self):
        super().setUp()
        self.league = league_of_strikeouts_and_singles()

    def test_the_leagues_shares_of_the_results_are_found_in_its_counts(self):
        self.assertEqual(self.league.results, ("single", "strikeout"))
        self.assertTrue(np.allclose(self.league.shares, [0.25, 0.75]))

    def test_a_players_shares_are_his_counts_plus_the_priors_over_his_turns_plus_the_strength(self):
        # 8 strikeouts and no singles, and a prior worth 12 turns: the shares are (8 + 12 x 3/4) / 20 and (0 + 12 x 1/4) / 20
        player = baseball.tilt_transitions(self.league, results_table({"strikeout": 8}), 12)
        state = baseball.state_number(1, 1, 0, 2)
        strikeout, single = baseball.outcome_number(2, 0, 0), baseball.outcome_number(1, 1, 0)
        # the league's counts of each result are multiplied by the player's share over the league's, and the row scaled to 1: so the row is the player's shares
        self.assertAlmostEqual(player.values[state, strikeout], 17 / 20)
        self.assertAlmostEqual(player.values[state, single], 3 / 20)

    def test_a_player_with_no_turns_has_the_leagues_probabilities(self):
        player = baseball.tilt_transitions(self.league, results_table({}), 12)
        self.assertTrue(np.allclose(player.values, self.league.values))

    def test_a_player_with_a_great_many_turns_has_nearly_his_own_shares(self):
        player = baseball.tilt_transitions(self.league, results_table({"strikeout": 5000, "single": 5000}), 12)
        self.assertAlmostEqual(player.values[baseball.state_number(0, 0, 0, 0), baseball.outcome_number(1, 0, 0)], 0.5, places=2)

    def test_a_result_the_league_does_not_have_is_an_error(self):
        with self.assertRaisesRegex(lisp_core.LispError, "walk is not a result the league has"):
            baseball.tilt_transitions(self.league, results_table({"walk": 3}), 12)

    def test_the_strength_must_be_above_zero_and_the_league_must_be_the_leagues(self):
        with self.assertRaisesRegex(lisp_core.LispError, "above 0"):
            baseball.tilt_transitions(self.league, results_table({"strikeout": 3}), 0)
        with self.assertRaisesRegex(lisp_core.LispError, "the league's probabilities"):
            baseball.tilt_transitions(baseball.combine_transitions(self.league, self.league, self.league), results_table({"strikeout": 3}), 12)


class TestCombining(LispTestCase):

    def setUp(self):
        super().setUp()
        self.league = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 0.6, (outs, 1, 0): 0.3, (outs, 0, 1): 0.1})

    def test_a_batter_and_a_pitcher_who_are_the_league_make_the_league(self):
        combined = baseball.combine_transitions(self.league, self.league, self.league)
        self.assertTrue(np.allclose(combined.values, self.league.values))

    def test_the_probabilities_are_multiplied_and_divided_by_the_leagues_and_scaled(self):
        batter = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 0.3, (outs, 1, 0): 0.4, (outs, 0, 1): 0.3})
        pitcher = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 0.7, (outs, 1, 0): 0.2, (outs, 0, 1): 0.1})
        combined = baseball.combine_transitions(batter, pitcher, self.league)
        unscaled = np.array([0.3 * 0.7 / 0.6, 0.4 * 0.2 / 0.3, 0.3 * 0.1 / 0.1])
        state = baseball.state_number(0, 0, 0, 0)
        outcomes = [baseball.outcome_number(1, 0, 0), baseball.outcome_number(0, 1, 0), baseball.outcome_number(0, 0, 1)]
        self.assertTrue(np.allclose(combined.values[state, outcomes], unscaled / unscaled.sum()))
        self.assertTrue(np.allclose(combined.values.sum(axis=1), 1))

    def test_an_outcome_the_league_says_cannot_happen_cannot(self):
        batter = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 0.5, (outs, 0, 4): 0.5})
        combined = baseball.combine_transitions(batter, self.league, self.league)
        self.assertEqual(combined.values[0, baseball.outcome_number(0, 0, 4)], 0)
        self.assertTrue(np.allclose(combined.values.sum(axis=1), 1))


class TestRunExpectancy(LispTestCase):

    def test_it_matches_a_recursion_on_a_chain_whose_runs_are_known(self):
        # In every state, half the turns are outs that leave the runners where they are; half clear the bases, and every runner and the batter score.
        def probabilities(home, outs, bases, difference):
            runners = bin(bases).count("1")
            return {(outs + 1, bases if outs < 2 else 0, 0): 0.5, (outs, 0, runners + 1): 0.5} if runners + 1 <= baseball.MAX_RUNS else {(outs + 1, 0, 0): 1.0}
        matrix = a_matrix(probabilities)
        weights = baseball.Transitions("counts", np.ones((baseball.STATES, baseball.OUTCOMES)))
        table = baseball.run_expectancy(matrix, lisp_core.Keyword(":weights"), weights)
        found = {(o, b): r for o, b, r in zip(*(c.cdr.items.tolist() for c in lisp_core.pairs_to_list(table)))}

        # With the bases emptied and a run for each runner, only the outs can end it: with nobody on, the runs from 0 outs are
        # 0.5 x 1 + 0.5 x (runs from 1 out), with the bases the same: R(2, b) = 0.5 x (runners + 1) + 0.5 x R(2, 0) x ... so solve it by value iteration.
        expected = {(o, b): 0.0 for o in range(3) for b in range(8)}
        for _ in range(200):
            new = {}
            for o in range(3):
                for b in range(8):
                    runners = bin(b).count("1")
                    out = expected[(o + 1, b if o < 2 else 0)] if o < 2 else 0.0
                    if runners + 1 <= baseball.MAX_RUNS:
                        new[(o, b)] = 0.5 * out + 0.5 * (runners + 1 + expected[(o, 0)])
                    else:
                        new[(o, b)] = out
            expected = new
        for key in expected:
            self.assertAlmostEqual(found[key], expected[key], places=6)

    def test_counts_are_their_own_weights_and_probabilities_need_weights(self):
        counts = baseball.transition_counts(table_of(every_state_has_a_strikeout_and_a_single()))
        table = baseball.run_expectancy(counts)
        runs = lisp_core.pairs_to_list(table)[2].cdr.items
        self.assertTrue(np.allclose(runs, 0))                      # no runs score in these turns
        with self.assertRaisesRegex(lisp_core.LispError, "needs :weights"):
            baseball.run_expectancy(baseball.smooth_transitions(counts))


class TestLookingAtAMatrix(LispTestCase):

    def setUp(self):
        super().setUp()
        self.counts = baseball.transition_counts(table_of(every_state_has_a_strikeout_and_a_single()))

    def test_a_row_lists_what_happened_most_often_first(self):
        row = lisp_core.pairs_to_list(baseball.transition_row(self.counts, 1, 1, 0, 2))
        columns = {str(c.car): c.cdr.items.tolist() for c in row}
        self.assertEqual(columns["new_outs"], [2, 1])
        self.assertEqual(columns["value"], [3, 1])

    def test_the_table_has_a_row_for_each_state_and_outcome_that_happened(self):
        table = lisp_core.pairs_to_list(baseball.transition_table(self.counts))
        self.assertEqual([str(c.car) for c in table], COLUMNS + ["value"])
        self.assertEqual(len(table[0].cdr.items), 2 * baseball.STATES)

    def test_the_state_to_state_table_follows_the_inning_to_the_other_team(self):
        counts = baseball.transition_counts(table_of([(0, 2, 0, 1, 3, 0, 0, 4)]))          # the visitors lead by 1, and make the third out
        table = {str(c.car): c.cdr.items.tolist() for c in lisp_core.pairs_to_list(baseball.state_transition_table(counts))}
        self.assertEqual([table[name] for name in ("next_home_batting", "next_outs", "next_bases", "next_score_difference", "value")], [[1], [0], [0], [-1], [4]])


class TestPriorStrength(LispTestCase):

    def draw_players(self, strength, players=400, turns=60, seed=3):
        """A table of the results of players whose shares were drawn from a Dirichlet distribution of this strength around the league's, with the league."""
        league = league_of_strikeouts_and_singles()
        generator = np.random.default_rng(seed)
        names, ids, counts = [], [], []
        for player in range(players):
            drawn = generator.multinomial(turns, generator.dirichlet(strength * league.shares))
            for result, count in zip(league.results, drawn):
                names.append(result)
                ids.append("player%d" % player)
                counts.append(count)
        table = lisp_tables.make_table_value([("player", lisp_core.LispVector(np.array(ids, dtype=object))),
                                              ("result", lisp_core.LispVector(np.array(names, dtype=object))),
                                              ("count", lisp_vector_math.to_vector(np.array(counts, dtype=float)))])
        return table, league

    def test_the_strength_that_players_were_drawn_with_is_found(self):
        table, league = self.draw_players(strength=50)
        found = baseball.prior_strength(table, "player", league)
        self.assertGreater(found, 50 * 0.75)
        self.assertLess(found, 50 * 1.25)

    def test_stronger_priors_are_found_stronger(self):
        weak = baseball.prior_strength(*self.draw_players(strength=20)[:1], "player", self.draw_players(strength=20)[1])
        strong = baseball.prior_strength(*self.draw_players(strength=300)[:1], "player", self.draw_players(strength=300)[1])
        self.assertGreater(strong, 4 * weak)

    def test_the_likelihood_is_highest_at_the_strength_found(self):
        table, league = self.draw_players(strength=50)
        found = baseball.prior_strength(table, "player", league)
        best = baseball.prior_strength_loglik(table, "player", league, found)
        for other in (found / 2, found * 2):
            self.assertGreater(best, baseball.prior_strength_loglik(table, "player", league, other))


def team_of_nine(matrix, starter_batters=100):
    """A team for simulate-games whose nine batters, against starter and relievers, all have this matrix."""
    nine = lisp_core.list_to_pairs([matrix] * 9)
    return lisp_core.list_to_pairs([nine, nine, starter_batters])


class TestGames(LispTestCase):

    def play(self, home, away, **options):
        arguments = []
        for name, value in options.items():
            arguments += [lisp_core.Keyword(":" + name.replace("_", "-")), value]
        results = baseball.simulate_games(home, away, *arguments)
        return {str(c.car): c.cdr.items for c in lisp_core.pairs_to_list(results)}

    def test_a_team_that_never_scores_against_one_that_scores_every_inning(self):
        def never_scores(home, outs, bases, difference):
            return {(outs + 1, bases if outs < 2 else 0, 0): 1.0}

        def scores_once_an_inning(home, outs, bases, difference):
            return {(1, 0, 1): 1.0} if outs == 0 else {(outs + 1, bases if outs < 2 else 0, 0): 1.0}
        # the home team's first batter each inning homers (and the next two make the outs: 3 outs, 1 run); the visitors never score
        results = self.play(team_of_nine(a_matrix(scores_once_an_inning)), team_of_nine(a_matrix(never_scores)), games=20, seed=1)
        # the home team is ahead after the top of the 9th, so does not bat: it scored in the first 8 innings
        self.assertEqual(set(results["home_runs"]), {8})
        self.assertEqual(set(results["visiting_runs"]), {0})
        self.assertEqual(set(results["innings"]), {9})

    def test_the_game_ends_when_the_home_team_takes_the_lead_in_the_last_inning(self):
        def scores_in_the_ninth(home, outs, bases, difference):
            return {(outs + 1, bases if outs < 2 else 0, 0): 1.0}
        # home batters score a run when they trail by 1: visitors score a run in the first inning only (they are +1 only after that). Here, the batting team scores
        # one run, with the batter out, whenever it trails (difference -1) or is tied at 0 outs with the bases empty... so we use the difference.
        def catches_up(home, outs, bases, difference):
            if home == 1 and difference == -1:
                return {(1, 0, 1): 1.0}
            if home == 0 and outs == 0 and bases == 0 and difference == 0:
                return {(1, 0, 1): 1.0}
            return {(outs + 1, bases if outs < 2 else 0, 0): 1.0}
        # the visitors score 1 in the top of the 1st (3 outs: the first scores, then the others make outs) and 0 when they lead after that;
        # the home team scores 1 to tie when they trail 0-1, and when tied nobody scores: tied until extra innings, when no one scores either:
        # they would play to the 30-inning stop. So the ghost runner must be off to keep this deterministic.
        results = self.play(team_of_nine(a_matrix(catches_up)), team_of_nine(a_matrix(catches_up)), games=10, seed=1, ghost_runner=False)
        self.assertEqual(set(results["innings"]), {baseball.LAST_INNING_PLAYED})
        self.assertEqual(set(results["home_runs"] - results["visiting_runs"]), {0})

    def test_extra_innings_start_with_a_runner_on_second(self):
        # nobody scores unless the runner is on second with nobody out; then the batting team scores 1 (visitors) or 2 (home)
        def only_the_ghost_runner_scores(home, outs, bases, difference):
            if outs == 0 and bases == 2:
                return {(1, 0, 2 if home == 1 else 1): 1.0}
            return {(outs + 1, bases if outs < 2 else 0, 0): 1.0}
        team = team_of_nine(a_matrix(only_the_ghost_runner_scores))
        results = self.play(team, team, games=10, seed=1)
        self.assertEqual((set(results["visiting_runs"]), set(results["home_runs"]), set(results["innings"])), ({1}, {2}, {10}))
        without = self.play(team, team, games=3, seed=1, ghost_runner=False)
        self.assertEqual(set(without["innings"]), {baseball.LAST_INNING_PLAYED})

    def test_the_starter_is_replaced_after_the_batters_he_faces(self):
        # against the starter the visitors never score; against the relievers they score a run with the first batter of each inning
        def never(home, outs, bases, difference):
            return {(outs + 1, bases if outs < 2 else 0, 0): 1.0}

        def first_batter_homers(home, outs, bases, difference):
            return {(0, 0, 1): 1.0} if False else ({(1, 0, 1): 1.0} if outs == 0 else {(outs + 1, bases if outs < 2 else 0, 0): 1.0})
        nine = lambda matrix: lisp_core.list_to_pairs([matrix] * 9)
        visitors = lisp_core.list_to_pairs([nine(a_matrix(never)), nine(a_matrix(first_batter_homers)), 100])
        home = lisp_core.list_to_pairs([nine(a_matrix(never)), nine(a_matrix(never)), 6])          # the home starter faces 6 batters: two innings
        results = self.play(home, visitors, games=5, seed=1)
        # the first two innings are against the starter; the other seven (the 9th is played: the home team trails) against relievers, each one run
        self.assertEqual(set(results["visiting_runs"]), {7})
        self.assertEqual(set(results["home_runs"]), {0})

    def test_the_same_seed_gives_the_same_games(self):
        matrix = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 0.7, (outs, 1, 0): 0.2, (outs, 0, 1): 0.1})
        first = self.play(team_of_nine(matrix), team_of_nine(matrix), games=50, seed=7)
        second = self.play(team_of_nine(matrix), team_of_nine(matrix), games=50, seed=7)
        self.assertEqual(list(first["home_runs"]), list(second["home_runs"]))
        self.assertEqual(list(first["visiting_runs"]), list(second["visiting_runs"]))

    def test_a_team_must_be_nine_batters(self):
        matrix = a_matrix(lambda home, outs, bases, difference: {(outs + 1, bases if outs < 2 else 0, 0): 1.0})
        short = lisp_core.list_to_pairs([lisp_core.list_to_pairs([matrix] * 8), lisp_core.list_to_pairs([matrix] * 9), 20])
        with self.assertRaisesRegex(lisp_core.LispError, "nine, not 8"):
            self.play(short, team_of_nine(matrix), games=1)


def small_database(path):
    """A database in the form load_retrosheet_data/ makes, of two seasons of games of a made-up league. Batters 'good' and 'poor' differ; every team's pitchers are
    alike. A batter's turn: an out, a walk (a runner on, or forced up), or a home run, with chances that depend on the batter."""
    generator = np.random.default_rng(11)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE turns (gid, season, date, gametype, inning, home_batting, batting_team, pitching_team, batter, pitcher, starter, outs, bases, "
                 "score_difference, new_outs, new_bases, runs, plate_appearance, result)")
    conn.execute("CREATE TABLE games (gid, season, date, gametype, visiting_team, home_team, visiting_runs, home_runs, innings)")
    conn.execute("CREATE TABLE players (id, last, first, bats, throws, first_season, last_season)")
    batters = ["good", "poor"] + ["extra%d" % i for i in range(3, 10)]                  # a team's batting order
    chances = {"good": (0.5, 0.2, 0.3), "poor": (0.9, 0.08, 0.02), "pitcher": (0.7, 0.15, 0.15)}       # out, single, home run
    chances.update({batter: chances["pitcher"] for batter in batters[2:]})
    for season in (2023, 2024):
        for game in range(300):
            gid = "AAA%d%04d" % (season, game)
            runs = {0: 0, 1: 0}
            up = {0: 0, 1: 0}                                                   # who is up next for each team
            for inning in range(1, 5):
                for home in (0, 1):
                    outs, bases = 0, 0
                    while outs < 3:
                        batter = batters[up[home]]
                        up[home] = (up[home] + 1) % 9
                        kind = generator.choice(3, p=chances[batter])
                        if kind == 0:
                            new_outs, new_bases, scored = outs + 1, bases, 0
                        elif kind == 1:
                            new_outs, new_bases, scored = outs, ((bases << 1) | 1) & 7, (bases >> 2) & 1
                        else:
                            new_outs, new_bases, scored = outs, 0, 1 + bin(bases).count("1")
                        scored = min(scored, baseball.MAX_RUNS)
                        new_bases = 0 if new_outs == 3 else new_bases
                        conn.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (gid, season, "%d0401" % season, "regular", inning, home, "AAA", "BBB", batter, "pitcher", 1 if game % 3 else 0,
                                      outs, bases, 0, new_outs, new_bases, scored, 1, ("other", "single", "home run")[kind]))
                        runs[home] += scored
                        outs, bases = new_outs, new_bases
            conn.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)", (gid, season, "%d0401" % season, "regular", "AAA", "BBB", runs[0], runs[1], 4))
    # the game turns reach only some combinations of outs and runners (a single moves everyone up a base), so fill in the rest
    for home in (0, 1):
        for outs in range(3):
            for bases in range(8):
                for repeat in range(8):
                    batter = "good" if repeat % 2 else "poor"
                    kind = generator.choice(3, p=chances[batter])
                    if kind == 0:
                        new_outs, new_bases, scored = outs + 1, bases, 0
                    elif kind == 1:
                        new_outs, new_bases, scored = outs, ((bases << 1) | 1) & 7, (bases >> 2) & 1
                    else:
                        new_outs, new_bases, scored = outs, 0, min(1 + bin(bases).count("1"), baseball.MAX_RUNS)
                    new_bases = 0 if new_outs == 3 else new_bases
                    conn.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 ("FILL", 2023, "20230401", "regular", 1, home, "AAA", "BBB", batter, "pitcher", 0,
                                  outs, bases, 0, new_outs, new_bases, scored, 1, ("other", "single", "home run")[kind]))
    conn.execute("INSERT INTO players VALUES ('good', 'Goodman', 'Gus', 'R', 'R', 2023, 2024)")
    conn.execute("INSERT INTO players VALUES ('poor', 'Poorman', 'Pat', 'L', 'L', 2023, 2024)")
    conn.commit()
    conn.close()


class TestTheLibrary(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = self.folder.name + "/retrosheet.db"
        small_database(self.database)
        self.run_lisp('(load "%s/baseball.lsp")' % LIB)
        self.run_lisp('(define model (fit-baseball-model :database "%s" :first-season 2023 :last-season 2024))' % self.database)

    def test_the_model_has_the_leagues_counts_and_strengths(self):
        conn = sqlite3.connect(self.database)
        turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        self.assertEqual(self.run_lisp("(vector-sum (table-column (transition-table (baseball-model-league-counts model)) \"value\"))"), turns)
        self.assertGreater(self.run_lisp("(baseball-model-batter-strength model)"), 0)
        self.assertGreater(self.run_lisp("(baseball-model-pitcher-strength model)"), 0)

    def test_a_batter_who_hits_more_home_runs_than_the_league_has_a_matrix_with_more_of_them(self):
        def home_run_chance(matrix):
            row = self.run_lisp('(transition-row %s 0 0 0 0)' % matrix)
            columns = {str(c.car): c.cdr.items.tolist() for c in lisp_core.pairs_to_list(row)}
            return {(o, b, r): v for o, b, r, v in zip(columns["new_outs"], columns["new_bases"], columns["runs"], columns["value"])}[(0, 0, 1)]
        league = home_run_chance("(baseball-model-league model)")
        good = home_run_chance('(baseball-batter-matrix model "good")')
        poor = home_run_chance('(baseball-batter-matrix model "poor")')
        self.assertGreater(good, league)
        self.assertGreater(league, poor)

    def test_a_good_lineup_is_worth_more_runs_an_inning_than_the_league_and_a_poor_one_less(self):
        def runs(matrix):
            return self.run_lisp('(vector-ref (table-column (run-expectancy %s :weights (baseball-model-league-counts model)) "runs") 0)' % matrix)
        self.assertGreater(runs('(baseball-batter-matrix model "good")'), runs("(baseball-model-league model)"))
        self.assertGreater(runs("(baseball-model-league model)"), runs('(baseball-batter-matrix model "poor")'))

    def test_a_batter_nobody_has_seen_has_the_leagues_probabilities(self):
        values = self.run_lisp('(vector-sum (vector-sub (table-column (transition-table (baseball-batter-matrix model "nobody")) "value") '
                               '(table-column (transition-table (baseball-model-league model)) "value")))')
        self.assertAlmostEqual(values, 0, places=9)

    def test_matrices_are_made_once(self):
        self.assertTrue(self.run_lisp('(eq? (baseball-batter-matrix model "good") (baseball-batter-matrix model "good"))'))

    def test_players_are_found_by_name(self):
        self.assertEqual(list(self.run_lisp('(table-column (baseball-players model "Good%") "id")').items), ["good"])

    def test_a_starter_faces_as_many_batters_as_he_did_per_start(self):
        conn = sqlite3.connect(self.database)
        turns, starts = conn.execute("SELECT COUNT(*), COUNT(DISTINCT gid) FROM turns WHERE pitcher = 'pitcher' AND starter = 1").fetchone()
        self.assertAlmostEqual(self.run_lisp('(baseball-starter-batters model "pitcher")'), turns / starts)
        self.assertEqual(self.run_lisp('(baseball-starter-batters model "nobody")'), 22)

    def test_a_better_lineup_wins_more_often(self):
        self.run_lisp('(define good (make-baseball-team :lineup (list "good" "good" "good" "good" "good" "good" "good" "good" "good") '
                      ':starter "pitcher" :bullpen "BBB" :starter-batters 100))')
        self.run_lisp('(define poor (make-baseball-team :lineup (list "poor" "poor" "poor" "poor" "poor" "poor" "poor" "poor" "poor") '
                      ':starter "pitcher" :bullpen "BBB" :starter-batters 100))')
        good_at_home = self.run_lisp("(home-win-probability (simulate-baseball-games model good poor :games 2000 :seed 5))")
        poor_at_home = self.run_lisp("(home-win-probability (simulate-baseball-games model poor good :games 2000 :seed 5))")
        self.assertGreater(good_at_home, 0.75)
        self.assertLess(poor_at_home, 0.25)

    def test_the_backtest_gives_a_chance_for_each_game_and_scores_it(self):
        tried = self.run_lisp('(baseball-backtest model 2024 :games-per-game 50 :max-games 10)')
        columns = {str(c.car): c.cdr.items for c in lisp_core.pairs_to_list(tried)}
        self.assertEqual(len(columns["gid"]), 10)
        self.assertTrue(np.all((columns["home_win_probability"] >= 0) & (columns["home_win_probability"] <= 1)))
        scores = self.run_lisp("(baseball-scores (baseball-backtest model 2024 :games-per-game 50 :max-games 10))")
        self.assertEqual(list(lisp_core.pairs_to_list(scores)[0].cdr.items), ["model", "home-field"])

    def test_the_notice_is_shown(self):
        self.run_lisp("(retrosheet-notice)")
        self.assertIn("copyrighted by Retrosheet", "".join(self.out))
        self.assertIn("20 Sunset Rd., Newark, DE 19711", "".join(self.out))
