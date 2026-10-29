"""lib/forecasting.lsp: the chance of each bin of a number, from a normal or lognormal distribution, from past
errors, and from call prices; how a "before the date" chance falls with the days left; combining forecasts; and
the Brier scores and the calibration table. Each is checked against the same sums done in plain Python."""

import random
import statistics

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


def normal_cdf(x):
    return statistics.NormalDist().cdf(x)


class ForecastingTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "forecasting.lsp")')

    def numbers(self, source):
        """A Lisp list or vector of numbers, as a Python list."""
        value = self.run_lisp(source)
        items = lisp_core.pairs_to_list(value) if isinstance(value, lisp_core.Pair) else value.items
        return [float(x) for x in items]

    def assertChances(self, source, expected, places=9):
        chances = self.numbers(source)
        self.assertEqual(len(chances), len(expected))
        for got, want in zip(chances, expected):
            self.assertAlmostEqual(got, want, places=places)
        self.assertAlmostEqual(sum(chances), 1, places=9)


class TestBins(ForecastingTestCase):

    def test_there_is_a_bin_below_the_first_edge_between_each_two_and_above_the_last(self):
        self.assertChances("(bin-probabilities '(1 2) (lambda (x) (/ x 4)))", [0.25, 0.25, 0.5])
        self.assertChances("(bin-probabilities '(5) (lambda (x) 0.3))", [0.3, 0.7])

    def test_normal_bins_are_the_differences_of_the_normal_curve(self):
        edges, mean, stdev = [2.75, 2.85, 2.95], 2.88, 0.12
        below = [0] + [normal_cdf((e - mean) / stdev) for e in edges] + [1]
        self.assertChances("(normal-bins '(2.75 2.85 2.95) 2.88 0.12)", [b - a for a, b in zip(below, below[1:])])

    def test_lognormal_bins_have_the_forward_as_their_mean(self):
        # The chance below each edge, as Black-Scholes has it: N(-d2).
        price, vol, years, rate = 100.0, 0.25, 0.5, 0.04
        forward = price * math.exp(rate * years)
        spread = vol * math.sqrt(years)
        edges = [90, 100, 110]
        below = [0] + [normal_cdf((math.log(e / forward) + spread ** 2 / 2) / spread) for e in edges] + [1]
        self.assertChances("(lognormal-bins '(90 100 110) 100 0.25 0.5 :rate 0.04)",
                           [b - a for a, b in zip(below, below[1:])])
        # Many bins, narrow: the chances weight the bins' middles to the forward.
        edges = [40 + i for i in range(150)]
        self.run_lisp("(define chances (lognormal-bins '(%s) 100 0.25 0.5 :rate 0.04))" % " ".join(map(str, edges)))
        chances = self.numbers("chances")
        middles = [39.5] + [e + 0.5 for e in edges[:-1]] + [190]
        self.assertAlmostEqual(sum(p * m for p, m in zip(chances, middles)), forward, delta=0.05)

    def test_empirical_bins_count_the_forecast_plus_each_past_error(self):
        # 2.9 plus each error: 2.7 2.8 2.9 2.9 3.0 3.2. A value on an edge counts in the bin above it.
        self.assertChances("(empirical-bins '(2.8 3.0) 2.9 '(-0.2 -0.1 0 0 0.1 0.3))", [1 / 6, 3 / 6, 2 / 6])

    def test_call_prices_give_back_the_chances_of_the_model_that_priced_them(self):
        self.run_lisp("(define strikes (map (lambda (i) (+ 80 i)) (iota 41)))")
        self.run_lisp("(define calls (vector->list (bsm-price \"call\" 100 (list->vector strikes) 0.5 0.04 0.25)))")
        self.assertChances("(call-price-bins '(90 100 110) strikes calls :discount (exp (* -0.04 0.5)))",
                           self.numbers("(lognormal-bins '(90 100 110) 100 0.25 0.5 :rate 0.04)"), places=3)

    def test_call_prices_that_slope_the_wrong_way_give_no_chance_less_than_zero(self):
        # The call at 105 is quoted above the one at 100: no price can make that so.
        chances = self.numbers("(call-price-bins '(100 105) '(95 100 105 110) '(8 4 5 1))")
        self.assertTrue(all(p >= 0 for p in chances))
        self.assertAlmostEqual(sum(chances), 1)

    def test_the_bin_table_labels_each_bin_and_gives_percents(self):
        self.run_lisp("(define t (bin-table '(2 2.5 3) '(0.1 0.25 0.4567 0.1933)))")
        self.assertShows('(table-column t "bin")', '#("below 2" "2 to 2.5" "2.5 to 3" "3 or more")')
        self.assertEqual(self.numbers('(table-column t "percent")'), [10.0, 25.0, 45.7, 19.3])


class TestBeforeTheDate(ForecastingTestCase):

    def test_the_chance_not_to_happen_shrinks_by_a_power_of_the_days(self):
        self.assertAlmostEqual(float(self.run_lisp("(probability-remaining 0.3 182 91)")), 1 - 0.7 ** 0.5)
        self.assertAlmostEqual(float(self.run_lisp("(probability-remaining 0.3 182 182)")), 0.3)
        self.assertAlmostEqual(float(self.run_lisp("(probability-remaining 0.3 182 0)")), 0)

    def test_the_schedule_starts_at_the_whole_chance_and_falls_each_step(self):
        self.run_lisp("(define s (decay-schedule 0.4 (date 2026 11 1) (date 2026 12 1) :every 7))")
        self.assertShows('(table-column s "date")', "#(2026-11-01 2026-11-08 2026-11-15 2026-11-22 2026-11-29)")
        self.assertEqual(self.numbers('(table-column s "days left")'), [30, 23, 16, 9, 2])
        percents = self.numbers('(table-column s "percent")')
        self.assertEqual(percents[0], 40.0)
        self.assertEqual(percents, [round(100 * (1 - 0.6 ** (d / 30)), 1) for d in (30, 23, 16, 9, 2)])


class TestCombining(ForecastingTestCase):

    def test_the_average_and_the_weighted_average(self):
        self.assertChances("(combine-forecasts '((0.2 0.8) (0.4 0.6)))", [0.3, 0.7])
        self.assertChances("(combine-forecasts '((0.1 0.2 0.7) (0.4 0.4 0.2)) :weights '(3 1))",
                           [0.175, 0.25, 0.575])

    def test_extremizing_moves_toward_the_favorite_and_a_power_of_one_changes_nothing(self):
        self.assertChances("(extremize '(0.7 0.3) 2)", [0.49 / 0.58, 0.09 / 0.58])
        self.assertChances("(extremize '(0.5 0.3 0.2) 1)", [0.5, 0.3, 0.2])
        timid = self.numbers("(extremize '(0.9 0.1) 0.5)")
        self.assertLess(timid[0], 0.9)


class TestScoring(ForecastingTestCase):

    def test_the_brier_score_adds_the_squares_of_the_misses(self):
        self.assertAlmostEqual(float(self.run_lisp("(brier-score '(0.7 0.3) 0)")), 0.18)
        self.assertAlmostEqual(float(self.run_lisp("(brier-score '(0.5 0.5) 1)")), 0.5)
        self.assertAlmostEqual(float(self.run_lisp("(brier-score '(1 0) 1)")), 2)
        self.assertAlmostEqual(float(self.run_lisp("(brier-score '(0.7 0.2 0.1) 2)")), 0.49 + 0.04 + 0.81)

    def test_the_ordered_score_averages_the_yes_or_no_score_at_each_cut(self):
        # The cuts of three bins: first | rest, and first two | last.
        def ordered(chances, outcome):
            scores = []
            for cut in range(1, len(chances)):
                below = sum(chances[:cut])
                happened = 1 if outcome < cut else 0
                scores.append(2 * (below - happened) ** 2)
            return sum(scores) / len(scores)
        rng = random.Random(7)
        for _ in range(20):
            raw = [rng.random() for _ in range(5)]
            chances = [x / sum(raw) for x in raw]
            outcome = rng.randrange(5)
            got = float(self.run_lisp("(ordered-brier-score '(%s) %d)" % (" ".join(map(repr, chances)), outcome)))
            self.assertAlmostEqual(got, ordered(chances, outcome))

    def test_a_near_miss_scores_better_than_a_far_one_in_order_but_not_otherwise(self):
        near = float(self.run_lisp("(ordered-brier-score '(0 0.7 0.3) 0)"))
        far = float(self.run_lisp("(ordered-brier-score '(0 0.3 0.7) 0)"))
        self.assertLess(near, far)
        self.assertAlmostEqual(float(self.run_lisp("(brier-score '(0 0.7 0.3) 0)")),
                               float(self.run_lisp("(brier-score '(0 0.3 0.7) 0)")))

    def test_the_calibration_table_has_a_row_for_each_bin_with_forecasts(self):
        self.run_lisp("(define t (calibration-table '(0.05 0.15 0.12 0.9 1.0 0.95) '(0 0 1 1 1 0) :bins 5))")
        self.assertShows('(table-column t "forecast")', '#("0 to 20%" "80 to 100%")')
        self.assertEqual(self.numbers('(table-column t "count")'), [3, 3])
        self.assertEqual(self.numbers('(table-column t "average forecast")'), [10.7, 95.0])
        self.assertEqual(self.numbers('(table-column t "percent happened")'), [33.3, 66.7])


if __name__ == "__main__":
    unittest.main()
