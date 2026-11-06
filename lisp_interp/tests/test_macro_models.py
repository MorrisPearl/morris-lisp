"""lisp_dynare.py (dynare-run) and lib/macro_models.lsp (the oil model).

The first tests need nothing outside Python: they read a results.json such as export_results.m writes, put parameters into a model, and
make the data from a fake FRED. The rest run Dynare itself, under Octave, and are skipped where Octave or Dynare isn't installed. The
estimation test makes few draws, and still takes a minute or two."""

import json
import os
import shutil
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import numpy

import lisp_dynare
import lisp_fred


def dynare_installed():
    try:
        lisp_dynare.find_octave("test")
        lisp_dynare.find_dynare("test")
        return True
    except lisp_core.LispError:
        return False


def fake_fred_series(series_id, credentials_path, start_date, end_date, cache_hours, who, frequency=None):
    """A quarterly series for each FRED ID oil-model-data asks for, from 1984 to 2009: a trend with some noise (the same each run),
    and the last quarter missing for COMPRNFB, as FRED's real wage series is a quarter behind the others."""
    assert frequency == "quarterly"
    rng = numpy.random.default_rng(sum(map(ord, series_id)))
    dates = [lisp_core.LispDate(year, month, 1) for year in range(1984, 2010) for month in (1, 4, 7, 10)]
    if series_id == "FEDFUNDS":
        values = 5 + numpy.cumsum(rng.normal(0, 0.3, len(dates)))
    else:
        values = 100 * numpy.exp(numpy.cumsum(rng.normal(0.006, 0.01 if series_id != "WTISPLC" else 0.1, len(dates))))
    if series_id == "COMPRNFB":
        dates, values = dates[:-1], values[:-1]
    first = dates[0].date if start_date is None else lisp_core.date_argument(start_date, who, ":start-date")
    last = dates[-1].date if end_date is None else lisp_core.date_argument(end_date, who, ":end-date")
    kept = [k for k, day in enumerate(dates) if first <= day.date <= last]      # FRED sends only the quarters asked for
    return lisp_core.Pair(lisp_core.LispVector([dates[k] for k in kept]), lisp_core.LispVector([values[k] for k in kept]))


# The Fed's shares (percent) the fake Distributional Financial Accounts give, for the FRED series wealth-by-type asks for.
FAKE_WEALTH_SHARES = {"WFRBSB50215": 2.3, "WFRBSN40188": 28.8, "WFRBSN09161": 36.4, "WFRBST01134": 32.5,
                      "WFRBSB50203": 0.6, "WFRBSN40176": 11.4, "WFRBSN09149": 37.2, "WFRBST01122": 50.9}


def fake_wealth_series(series_id, credentials_path, start_date, end_date, cache_hours, who, frequency=None):
    """Six quarters of each series with the same share, and the last quarter missing for the top 1%'s net worth, as the Fed publishes
    some series later than others."""
    assert frequency == "quarterly"
    dates = [lisp_core.LispDate(year, month, 1) for year, month in ((2025, 1), (2025, 4), (2025, 7), (2025, 10), (2026, 1), (2026, 4))]
    values = [FAKE_WEALTH_SHARES[series_id]] * 6
    if series_id == "WFRBST01134":
        dates, values = dates[:-1], values[:-1]
    return lisp_core.Pair(lisp_core.LispVector(dates), lisp_core.LispVector(values))


def check_draws_of(test, draws_a_chain, parameters):
    """The estimate "est" has draws: two chains of the kept half, a column for each estimated number, whose means are the estimates."""
    test.assertShows('(table-row-count (hash-table-ref est "draws"))', str(2 * draws_a_chain // 2))
    columns = [str(p.car) for p in lisp_core.pairs_to_list(test.run_lisp('(hash-table-ref est "draws")'))]
    test.assertEqual(columns[:3], ["chain", "draw", "log posterior"])
    test.assertEqual(len(columns) - 3, parameters)
    names = [str(n) for n in test.run_lisp('(table-column (hash-table-ref est "estimates") "name")').items]
    means = test.run_lisp('(table-column (hash-table-ref est "estimates") "mean")').items
    for name, mean in zip(names, means):
        test.assertAlmostEqual(test.run_lisp('(vector-mean (table-column (hash-table-ref est "draws") "%s"))' % name), mean, places=8)


class TestReadingResults(unittest.TestCase):
    """What dynare-run makes of export_results.m's results.json, without running Dynare."""

    def test_a_response_name_is_split_at_the_shock_even_with_underscores_in_both(self):
        self.assertEqual(lisp_dynare.split_irf_name("pi_c_e_oil", ["y", "pi_c", "pi_q"], ["e_oil", "e_i"]), ("pi_c", "e_oil"))
        self.assertEqual(lisp_dynare.split_irf_name("y_e_i", ["y", "pi_c"], ["e_oil", "e_i"]), ("y", "e_i"))
        self.assertEqual(lisp_dynare.split_irf_name("nothing_here", ["y"], ["e_i"]), (None, None))

    def test_draws_make_a_table_with_the_chain_the_draw_and_its_log_posterior_before_a_column_for_each_parameter(self):
        results = {"prior_names": ["theta", "stderr e_oil"], "draws_per_chain": 2,
                   "draws": [[0.9, 12.0], [0.91, 12.5], [0.92, 13.0], [0.93, 13.5]], "draw_log_posterior": [-5, -6, -7, -8]}
        table = lisp_dynare.draws_table(results)
        columns = lisp_core.pairs_to_list(table)
        self.assertEqual([str(c.car) for c in columns], ["chain", "draw", "log posterior", "theta", "stderr e_oil"])
        self.assertEqual(list(columns[0].cdr.items), [1, 1, 2, 2])
        self.assertEqual(list(columns[1].cdr.items), [1, 2, 1, 2])
        self.assertEqual(list(columns[3].cdr.items), [0.9, 0.91, 0.92, 0.93])

    def test_responses_make_a_table_for_each_shock_with_zeros_for_what_dynare_left_out(self):
        results = {"endo_names": ["y", "pi_c", "s"], "shock_names": ["e_oil", "e_i"],
                   "param_names": ["beta"], "param_values": 0.99, "shock_stderr": [12, 0.25],
                   "irfs": {"y_e_oil": [-0.1, -0.05], "s_e_oil": [12, 11.4], "pi_c_e_oil": [0.3, 0.01],
                            "y_e_i": [-0.6, -0.3], "pi_c_e_i": [-0.2, -0.1]}}
        made = lisp_dynare.results_hash_table(results, "/tmp/x", "log")
        responses = made.table[lisp_core.LispString("responses")]
        oil = dict((str(p.car), p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(responses.table[lisp_core.LispString("e_oil")]))
        self.assertEqual(list(oil), ["quarter", "y", "pi_c", "s"])
        self.assertEqual(oil["quarter"], [1, 2])
        self.assertEqual(oil["s"], [12, 11.4])
        rate = dict((str(p.car), p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(responses.table[lisp_core.LispString("e_i")]))
        self.assertEqual(list(rate), ["quarter", "y", "pi_c"])         # s never moves after e_i, and Dynare left it out
        parameters = made.table[lisp_core.LispString("parameters")]
        self.assertEqual([str(p.car) for p in lisp_core.pairs_to_list(parameters)], ["name", "value"])

    def test_an_estimation_gives_a_row_for_each_estimated_parameter_and_bands_for_its_responses(self):
        results = {"endo_names": ["y"], "shock_names": ["e_oil"], "param_names": ["theta"], "param_values": [0.9],
                   "shock_stderr": [13],
                   "prior_names": ["stderr e_oil", "theta", "stderr pi_c_obs"], "prior_mean": [10, 0.66, 0.1],
                   "prior_stdev": [float("inf"), 0.1, float("inf")],
                   "posterior_mode": {"parameters": {"theta": 0.95}, "shocks_std": {"e_oil": 13.5},
                                      "measurement_errors_std": {"pi_c_obs": 0.2}},
                   "posterior_mean": {"parameters": {"theta": 0.94}, "shocks_std": {"e_oil": 13.7},
                                      "measurement_errors_std": {"pi_c_obs": 0.21}},
                   "posterior_hpdinf": {"parameters": {"theta": 0.92}, "shocks_std": {"e_oil": 12},
                                        "measurement_errors_std": {"pi_c_obs": 0.19}},
                   "posterior_hpdsup": {"parameters": {"theta": 0.96}, "shocks_std": {"e_oil": 15},
                                        "measurement_errors_std": {"pi_c_obs": 0.23}},
                   "marginal_density": {"LaplaceApproximation": -513.4},
                   "posterior_irf_mean": {"y_e_oil": [0.1, 0.2]}, "posterior_irf_low": {"y_e_oil": [0.0, 0.1]},
                   "posterior_irf_high": {"y_e_oil": [0.2, 0.3]}}
        made = lisp_dynare.results_hash_table(results, "/tmp/x", "log")
        estimates = dict((str(p.car), p.cdr.items.tolist())
                         for p in lisp_core.pairs_to_list(made.table[lisp_core.LispString("estimates")]))
        self.assertEqual(estimates["name"], ["stderr e_oil", "theta", "stderr pi_c_obs"])
        self.assertEqual(estimates["mean"], [13.7, 0.94, 0.21])
        self.assertEqual(estimates["low"], [12, 0.92, 0.19])
        self.assertEqual(estimates["mode"], [13.5, 0.95, 0.2])
        self.assertEqual(made.table[lisp_core.LispString("log-marginal-density")], -513.4)
        oil = lisp_core.pairs_to_list(made.table[lisp_core.LispString("responses")].table[lisp_core.LispString("e_oil")])
        self.assertEqual([str(p.car) for p in oil], ["quarter", "y", "y low", "y high"])


class TestPreparingTheFolder(unittest.TestCase):

    def setUp(self):
        self.source = tempfile.mkdtemp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source, True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        with open(os.path.join(self.source, "model.mod"), "w") as f:
            f.write('@#include "part.inc"\nstoch_simul;\n')
        with open(os.path.join(self.source, "part.inc"), "w") as f:
            f.write("parameters a;\na = 1;\n%s\nmodel(linear);\nend;\n" % lisp_dynare.PARAMETERS_MARKER)

    def test_parameters_go_at_the_marker_of_the_file_that_has_it(self):
        lisp_dynare.prepare_folder(os.path.join(self.source, "model.mod"), self.folder, [("a", 2.5)], None, "test")
        with open(os.path.join(self.folder, "part.inc")) as f:
            text = f.read()
        self.assertIn(lisp_dynare.PARAMETERS_MARKER + "\na = 2.5;\n", text)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "export_results.m")))
        with open(os.path.join(self.source, "part.inc")) as f:
            self.assertNotIn("2.5", f.read())                 # the model's own file is left as it was

    def test_another_models_file_with_a_marker_in_the_same_folder_is_left_alone(self):
        with open(os.path.join(self.source, "aaa_other.inc"), "w") as f:      # sorts before part.inc
            f.write("parameters a;\n%s\n" % lisp_dynare.PARAMETERS_MARKER)
        lisp_dynare.prepare_folder(os.path.join(self.source, "model.mod"), self.folder, [("a", 2.5)], None, "test")
        with open(os.path.join(self.folder, "aaa_other.inc")) as f:
            self.assertNotIn("2.5", f.read())
        with open(os.path.join(self.folder, "part.inc")) as f:
            self.assertIn("a = 2.5;", f.read())

    def test_parameters_need_a_marker_and_numbers(self):
        with open(os.path.join(self.source, "part.inc"), "w") as f:
            f.write("parameters a;\n")
        with self.assertRaises(lisp_core.LispError) as cm:
            lisp_dynare.prepare_folder(os.path.join(self.source, "model.mod"), self.folder, [("a", 2.5)], None, "test")
        self.assertIn("Parameters given by the caller go here", str(cm.exception))
        with self.assertRaises(lisp_core.LispError):
            lisp_dynare.number_text(lisp_core.LispString("x"), "test", "a")


class TestOilModelData(LispTestCase):

    def test_the_data_are_quarterly_growth_rates_less_their_averages_from_the_start_to_the_end(self):
        with mock.patch.object(lisp_fred, "download_series", fake_fred_series):
            self.run_lisp('(load "macro_models.lsp")'
                          '(define d (oil-model-data "creds.json" :start (date 1990 1 1) :end (date 1999 10 1)))')
        self.assertShows('(map car d)', '("date" "gdp_growth_data" "real_wage_growth_data" "core_inflation_data" "headline_inflation_data" "fed_rate_data" "real_oil_price_change_data")')
        self.assertShows('(table-row-count d)', '40')
        self.assertShows('(vector-ref (table-column d "date") 0)', '1990-01-01')
        for column in ("gdp_growth_data", "fed_rate_data", "real_oil_price_change_data"):
            self.assertAlmostEqual(self.run_lisp('(vector-mean (table-column d "%s"))' % column), 0, places=10)
        # GDP growth is the change in the log, in percent; the oil price is real (less core inflation)
        gdp = fake_fred_series("GDPC1", None, None, None, 0, "", "quarterly").cdr.items
        growth = 100 * numpy.diff(numpy.log(gdp))
        first = 4 * (1990 - 1984)                     # the quarter of 1990-01-01, less one, in the fake's series of growth rates
        expected = growth[first - 1:first - 1 + 40]
        self.assertTrue(numpy.allclose(self.run_lisp('(table-column d "gdp_growth_data")').items, expected - expected.mean()))


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestOilModel(LispTestCase):
    """The oil model, run by Dynare."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "macro_models.lsp")')

    def test_the_calibrated_model_responds_to_oil_as_its_equations_say(self):
        self.run_lisp('(define base (oil-model :quarters 10))'
                      '(define oil (oil-shock-responses base :rise 10))')
        self.assertShows('(table-row-count oil)', '10')
        oil = {name: self.run_lisp('(table-column oil "%s")' % name).items for name in
               ("real oil price", "headline inflation", "core inflation", "GDP", "consumption", "Fed rate")}
        self.assertAlmostEqual(oil["real oil price"][0], 10)
        self.assertAlmostEqual(oil["real oil price"][1], 9.5)               # oil_price_persistence is 0.95
        # Headline inflation is core plus oil's share (oil_consumption_share, 0.02) of the oil price's rise, both at an annual rate (times 4)
        self.assertAlmostEqual(oil["headline inflation"][0] - oil["core inflation"][0], 4 * 0.02 * 10)
        self.assertLess(oil["consumption"][0], 0)
        self.assertGreater(oil["core inflation"][0], 0)
        self.assertGreater(oil["Fed rate"][0], 0)
        # Linear: twice the rise, twice the responses
        twice = self.run_lisp('(table-column (oil-shock-responses base :rise 20) "GDP")').items
        self.assertTrue(numpy.allclose(twice, 2 * oil["GDP"]))

    def test_a_scenario_changes_the_parameters_it_names_and_no_others(self):
        self.run_lisp('(define base (oil-model))'
                      '(define rigid (oil-model :parameters (list (cons "wage_rigidity" 0.9))))'
                      '(define (value r name) (vector-ref (table-column (table-filter (hash-table-ref r "parameters")'
                      '                        (vector= (table-column (hash-table-ref r "parameters") "name") name)) "value") 0))')
        self.assertShows('(value rigid "wage_rigidity")', '0.9')
        self.assertShows('(value rigid "price_stickiness")', '0.75')
        base_core = self.run_lisp('(table-column (oil-shock-responses base) "core inflation")').items
        rigid_core = self.run_lisp('(table-column (oil-shock-responses rigid) "core inflation")').items
        self.assertGreater(rigid_core[0], base_core[0])     # rigid real wages make the rise in costs, and in core inflation, larger

    def test_every_shock_has_responses_and_a_variance_decomposition(self):
        self.run_lisp('(define base (oil-model))')
        self.assertShows('(sort (hash-table-keys (hash-table-ref base "responses")))',
                         '("cost_push_shock" "demand_shock" "fed_shock" "oil_price_shock" "productivity_shock" "wage_shock")')
        self.assertTrue(self.run_lisp('(vector-ref (table-column (oil-model-responses base "fed_shock") "Fed rate") 0)') > 0)
        self.assertLispError('(oil-model-responses base "e_x")', "no responses to e_x")
        shares = self.run_lisp('(hash-table-ref base "variance-decomposition")')
        rows = numpy.array([p.cdr.items for p in lisp_core.pairs_to_list(shares)[1:]], dtype=float)
        self.assertTrue(numpy.allclose(rows.sum(axis=0), 100))      # each variable's shares add up to 100%

    def test_a_model_with_an_error_says_what_dynare_said(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "broken.mod"), "w") as f:
            f.write("var y; varexo e; parameters r; r = 0.5;\nmodel; y = r * y(-1) + e + unknown_thing; end;\nstoch_simul;\n")
        self.env[lisp_core.Symbol("broken")] = lisp_core.LispString(os.path.join(folder, "broken.mod"))
        self.assertLispError('(dynare-run broken)', "unknown_thing")

    def test_plot_oil_shock_draws_a_panel_for_each_variable_and_a_line_for_each_result(self):
        charts = []
        env = lisp_builtins.make_global_env(output=self.out.append, plot=charts.append)
        self.run_lisp('(load "macro_models.lsp")'
                      '(plot-oil-shock (list (list "a" (oil-model)) (list "b" (oil-model :parameters (list (cons "fed_inflation_response" 3))))))', env)
        self.assertEqual(len(charts), 1)
        self.assertEqual(len(charts[0]["panels"]), 6)


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestOilModelEstimate(LispTestCase):
    """An estimation, with few draws (a minute or two): its estimates, its bands, and a scenario from it."""

    def test_an_estimate_has_estimates_bands_and_can_start_a_scenario(self):
        with mock.patch.object(lisp_fred, "download_series", fake_fred_series):
            self.run_lisp('(load "macro_models.lsp")'
                          '(define est (oil-model-estimate "creds.json" :draws 300 :quarters 10))')
        self.assertIn("Estimating the oil model on 95 quarters", self.printed())
        names = [str(n) for n in self.run_lisp('(table-column (hash-table-ref est "estimates") "name")').items]
        self.assertIn("price_stickiness", names)
        self.assertIn("stderr oil_price_shock", names)
        low, mean, high = (self.run_lisp('(table-column (hash-table-ref est "estimates") "%s")' % c).items for c in ("low", "mean", "high"))
        self.assertTrue(numpy.all(low <= mean) and numpy.all(mean <= high))
        oil = self.run_lisp('(oil-shock-responses est :rise 10)')
        columns = [str(p.car) for p in lisp_core.pairs_to_list(oil)]
        self.assertIn("GDP low", columns)
        self.assertIn("GDP high", columns)
        # The estimate's parameters, as a scenario takes them: the shocks' sizes by their parameter names, no measurement error
        parameters = dict((str(p.car), p.cdr) for p in lisp_core.pairs_to_list(self.run_lisp('(oil-model-estimated-parameters est)')))
        self.assertIn("oil_price_shock_size", parameters)
        self.assertNotIn("stderr headline_inflation_data", parameters)
        self.assertAlmostEqual(parameters["price_stickiness"], mean[names.index("price_stickiness")])
        self.run_lisp('(define scenario (oil-model :from est :parameters (list (cons "core_weight" 1))))')
        self.assertShows('(vector-ref (table-column (table-filter (hash-table-ref scenario "parameters")'
                         ' (vector= (table-column (hash-table-ref scenario "parameters") "name") "core_weight")) "value") 0)', '1.0')
        self.run_lisp('(show-oil-estimates est)')
        check_draws_of(self, 300, 18)


class TestCrashModelData(LispTestCase):

    def test_the_data_are_quarterly_growth_rates_and_the_spread_less_their_averages(self):
        with mock.patch.object(lisp_fred, "download_series", fake_fred_series):
            self.run_lisp('(load "macro_models.lsp")'
                          '(define d (crash-model-data "creds.json" :start (date 1990 1 1) :end (date 1999 10 1)))')
        self.assertShows('(map car d)', '("date" "consumption_growth_data" "investment_growth_data" "inflation_data" "fed_rate_data" "credit_spread_data")')
        self.assertShows('(table-row-count d)', '40')
        for column in ("consumption_growth_data", "investment_growth_data", "fed_rate_data", "credit_spread_data"):
            self.assertAlmostEqual(self.run_lisp('(vector-mean (table-column d "%s"))' % column), 0, places=10)
        # The spread is a rate a year, and the model's is a rate a quarter: a fourth of it, less its average
        spread = fake_fred_series("BAA10YM", None, None, None, 0, "", "quarterly").cdr.items[4 * (1990 - 1984):][:40] / 4
        self.assertTrue(numpy.allclose(self.run_lisp('(table-column d "credit_spread_data")').items, spread - spread.mean()))


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestCrashModel(LispTestCase):
    """The crash model (the financial accelerator), run by Dynare."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "macro_models.lsp")'
                      '(define base (crash-model :quarters 10))'
                      '(define flat (crash-model :quarters 10 :parameters (list (cons "accelerator" 0))))')

    def column(self, table, name):
        return self.run_lisp('(table-column %s "%s")' % (table, name)).items

    def test_a_crash_sets_net_worth_to_the_fall_asked_for_and_the_economy_slows(self):
        self.run_lisp('(define crash (stock-crash-responses base :fall 20))')
        self.assertShows('(table-row-count crash)', '10')
        self.assertAlmostEqual(self.column("crash", "net worth")[0], -20)
        self.assertLess(self.column("crash", "GDP")[0], 0)
        self.assertLess(self.column("crash", "investment")[0], 0)
        self.assertGreater(self.column("crash", "credit spread")[0], 0)      # lenders charge more
        self.assertLess(self.column("crash", "Fed rate")[0], 0)              # and the Fed cuts
        # Linear: twice the fall, twice the responses
        self.run_lisp('(define twice (stock-crash-responses base :fall 40))')
        self.assertTrue(numpy.allclose(self.column("twice", "GDP"), 2 * self.column("crash", "GDP")))

    def test_without_the_accelerator_the_same_crash_does_far_less_harm(self):
        self.run_lisp('(define crash (stock-crash-responses base :fall 20))'
                      '(define without (stock-crash-responses flat :fall 20))')
        self.assertTrue(abs(self.column("without", "GDP")[0]) < 0.25 * abs(self.column("crash", "GDP")[0]))
        self.assertTrue(abs(self.column("without", "credit spread")[0]) < 1e-6)     # no premium to rise when nu is 0
        self.assertGreater(self.column("without", "investment")[3], self.column("crash", "investment")[3])

    def test_every_shock_has_responses_and_a_variance_decomposition(self):
        self.assertShows('(sort (hash-table-keys (hash-table-ref base "responses")))',
                         '("cost_push_shock" "demand_shock" "fed_shock" "lender_fear_shock" "net_worth_shock" "productivity_shock")')
        self.assertLess(self.run_lisp('(vector-ref (table-column (crash-model-responses base "lender_fear_shock") "investment") 0)'), 0)
        self.assertLispError('(crash-model-responses base "oil_shock")', "no responses to oil_shock")
        shares = self.run_lisp('(hash-table-ref base "variance-decomposition")')
        rows = numpy.array([p.cdr.items for p in lisp_core.pairs_to_list(shares)[1:]], dtype=float)
        self.assertTrue(numpy.allclose(rows.sum(axis=0), 100))

    def test_plot_stock_crash_draws_a_panel_for_each_variable_and_a_line_for_each_result(self):
        charts = []
        env = lisp_builtins.make_global_env(output=self.out.append, plot=charts.append)
        self.run_lisp('(load "macro_models.lsp")'
                      '(plot-stock-crash (list (list "with" (crash-model)) (list "without" (crash-model :parameters (list (cons "accelerator" 0))))))', env)
        self.assertEqual(len(charts), 1)
        self.assertEqual(len(charts[0]["panels"]), 7)


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestCrashModelEstimate(LispTestCase):
    """An estimation of the crash model, with few draws: its estimates, its bands, and a scenario from it."""

    def test_an_estimate_has_estimates_bands_and_can_start_a_scenario(self):
        with mock.patch.object(lisp_fred, "download_series", fake_fred_series):
            self.run_lisp('(load "macro_models.lsp")'
                          '(define est (crash-model-estimate "creds.json" :draws 300 :quarters 10))')
        self.assertIn("Estimating the crash model on 95 quarters", self.printed())
        names = [str(n) for n in self.run_lisp('(table-column (hash-table-ref est "estimates") "name")').items]
        self.assertIn("accelerator", names)
        self.assertIn("stderr net_worth_shock", names)
        low, mean, high = (self.run_lisp('(table-column (hash-table-ref est "estimates") "%s")' % c).items for c in ("low", "mean", "high"))
        self.assertTrue(numpy.all(low <= mean) and numpy.all(mean <= high))
        columns = [str(p.car) for p in lisp_core.pairs_to_list(self.run_lisp('(stock-crash-responses est :fall 20)'))]
        self.assertIn("GDP low", columns)
        self.assertIn("GDP high", columns)
        parameters = dict((str(p.car), p.cdr) for p in lisp_core.pairs_to_list(self.run_lisp('(macro-models--estimated-parameters est crash-model-shocks)')))
        self.assertIn("net_worth_shock_size", parameters)
        self.assertNotIn("stderr credit_spread_data", parameters)
        self.assertAlmostEqual(parameters["accelerator"], mean[names.index("accelerator")])
        self.run_lisp('(define scenario (crash-model :from est :parameters (list (cons "accelerator" 0))))')
        self.assertShows('(vector-ref (table-column (table-filter (hash-table-ref scenario "parameters")'
                         ' (vector= (table-column (hash-table-ref scenario "parameters") "name") "accelerator")) "value") 0)', '0.0')
        self.run_lisp('(show-crash-estimates est)')
        check_draws_of(self, 300, 19)


class TestWealthByType(LispTestCase):

    def test_the_latest_quarter_all_the_series_have_gives_shares_that_add_to_1(self):
        with mock.patch.object(lisp_fred, "download_series", fake_wealth_series):
            self.run_lisp('(load "macro_models.lsp")(define w (wealth-by-type "creds.json"))')
        self.assertShows('(map car w)', '("group" "net worth share" "stock share")')
        self.assertShows('(table-column w "group")', '#("bottom 50%" "next 40% (50-90)" "next 9% (90-99)" "top 1%")')
        self.assertIn("quarter of 2026-01-01", "".join(self.out))       # 2026-04 lacks the top 1%'s net worth
        net_worth = numpy.array(self.run_lisp('(table-column w "net worth share")').items)
        stocks = numpy.array(self.run_lisp('(table-column w "stock share")').items)
        self.assertAlmostEqual(net_worth.sum(), 1)
        self.assertAlmostEqual(stocks.sum(), 1)
        self.assertAlmostEqual(net_worth[3], 0.325)
        self.assertAlmostEqual(stocks[3], 0.509 / 1.001)               # the Fed's 50.9%, made to add to 1 with the others


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestTypesModel(LispTestCase):
    """The crash model with four kinds of households, run by Dynare."""

    NO_DIFFERENCES = ('(list (cons "hand_to_mouth_bottom50" 0) (cons "hand_to_mouth_next40" 0) (cons "hand_to_mouth_next9" 0)'
                      ' (cons "hand_to_mouth_top1" 0) (cons "earnings_cyclicality_bottom50" 1) (cons "earnings_cyclicality_next40" 1)'
                      ' (cons "earnings_cyclicality_next9" 1) (cons "earnings_cyclicality_top1" 1))')

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "macro_models.lsp")'
                      '(define base (types-model :quarters 10))')

    def column(self, table, name):
        return numpy.array(self.run_lisp('(table-column %s "%s")' % (table, name)).items)

    def test_households_that_differ_in_nothing_but_their_stocks_add_up_to_the_crash_model(self):
        # With nobody living from paycheck to paycheck and every group's hours moving as the economy's, the groups' spending adds up to
        # the crash model's: the stocks they own are all that is left, and the wealth_effect they share out is the crash model's.
        self.run_lisp('(define same (types-model :quarters 10 :parameters %s))(define crash (crash-model :quarters 10))' % self.NO_DIFFERENCES)
        for shock in ("net_worth_shock", "fed_shock", "demand_shock", "productivity_shock"):
            for name in ("gdp", "consumption", "investment", "hours", "inflation", "fed_rate", "net_worth", "credit_spread"):
                ours = self.column('(hash-table-ref (hash-table-ref same "responses") "%s")' % shock, name)
                theirs = self.column('(hash-table-ref (hash-table-ref crash "responses") "%s")' % shock, name)
                self.assertTrue(numpy.allclose(ours, theirs, atol=1e-9), (shock, name))

    def test_a_crash_hurts_the_groups_as_their_jobs_and_stocks_say(self):
        self.run_lisp('(define crash (types-crash-responses base :fall 20))')
        self.assertAlmostEqual(self.column("crash", "net worth")[0], -20)
        income = [self.column("crash", "income: " + group)[0]
                  for group in ("bottom 50%", "next 40% (50-90)", "next 9% (90-99)", "top 1%")]
        self.assertEqual(income, sorted(income))                        # the bottom half loses the most income, the top 1% the least
        self.assertTrue(all(value < 0 for value in income))
        spending = [self.column("crash", "spending: " + group)[0]
                    for group in ("bottom 50%", "next 40% (50-90)", "next 9% (90-99)", "top 1%")]
        self.assertLess(spending[3], spending[0])                       # the top 1%, who own half the stocks, cut spending the most
        self.assertLess(spending[3], -5)
        # The groups' spending, added up by their weights, is the economy's
        weights = [0.29, 0.42, 0.21, 0.08]
        self.assertTrue(numpy.allclose(sum(w * self.column("crash", "spending: " + g)
                                           for w, g in zip(weights, ("bottom 50%", "next 40% (50-90)", "next 9% (90-99)", "top 1%"))),
                                       self.column("crash", "consumption")))
        # Linear: twice the fall, twice the responses
        self.run_lisp('(define twice (types-crash-responses base :fall 40))')
        self.assertTrue(numpy.allclose(self.column("twice", "spending: top 1%"), 2 * self.column("crash", "spending: top 1%")))

    def test_without_a_wealth_effect_the_top_1_percent_cuts_spending_much_less_than_with_it(self):
        self.run_lisp('(define crash (types-crash-responses base :fall 20))'
                      '(define without (types-crash-responses (types-model :quarters 10 :parameters (list (cons "wealth_effect" 0))) :fall 20))')
        # (Spending still changes without it: the real interest rate changes in the crash, and savers who own no stocks respond to that.)
        self.assertLess(self.column("crash", "spending: top 1%")[0], self.column("without", "spending: top 1%")[0] - 5)

    def test_the_stock_shares_of_the_fed_data_replace_the_defaults(self):
        # If every group owned a quarter of the stocks, the top 1% (8% of spending) would feel a much smaller wealth effect
        self.run_lisp('(define even (make-table "group" (vector "a" "b" "c" "d") "stock share" (vector 0.25 0.25 0.25 0.25)))'
                      '(define crash (types-crash-responses base :fall 20))'
                      '(define crash-even (types-crash-responses (types-model :quarters 10 :wealth even) :fall 20))')
        self.assertGreater(self.column("crash-even", "spending: top 1%")[0], self.column("crash", "spending: top 1%")[0])
        self.assertLess(self.column("crash-even", "spending: bottom 50%")[0], self.column("crash", "spending: bottom 50%")[0] + 1)

    def test_the_losses_table_has_a_row_for_each_group(self):
        self.run_lisp('(define losses (types-crash-losses base :fall 20 :quarters 4))')
        self.assertShows('(map car losses)', '("group" "income, first quarter" "spending, first quarter" "spending, worst" "spending, average of 4 quarters")')
        self.assertShows('(table-row-count losses)', '4')
        self.assertLess(self.column("losses", "income, first quarter")[0], -4)           # the bottom half's income falls 5%

    def test_another_kind_of_surprise_has_a_column_for_each_group(self):
        self.run_lisp('(define fed (types-model-responses base "fed_shock"))')
        self.assertEqual(self.run_lisp('(length (map car fed))'), 24)
        self.assertLess(self.column("fed", "GDP")[0], 0)                  # a rise in the Fed's rate slows the economy
        self.assertLess(self.column("fed", "income: bottom 50%")[0], self.column("fed", "income: top 1%")[0])

    def test_without_a_wealth_tax_the_tax_variables_stay_at_zero(self):
        self.run_lisp('(define crash (types-crash-responses base :fall 20))')
        for name in ("wealth tax", "tax revenue", "top 1% wealth lost", "government purchases"):
            self.assertTrue(numpy.allclose(self.column("crash", name), 0), name)

    def test_a_wealth_tax_collects_what_the_top_1_percent_owns_times_the_rate_less_what_is_avoided(self):
        self.run_lisp('(define tax-model (types-model :quarters 12))(define tax (wealth-tax-responses tax-model :rate 1))')
        self.assertAlmostEqual(self.column("tax", "wealth tax")[0], 1)
        self.assertAlmostEqual(self.column("tax", "tax revenue")[0], (1 - 0.2) * 1 * 0.325 * 5.6)         # % of GDP
        self.assertAlmostEqual(self.column("tax", "top 1% wealth lost")[0], (1 - 0.2) * 1 / 4)             # % of its wealth, a quarter's tax
        # Paid out equally to every household, it raises what the bottom half spends and lowers what the top 1% does
        self.assertGreater(self.column("tax", "spending: bottom 50%")[0], 1)
        self.assertLess(self.column("tax", "spending: top 1%")[0], 0)
        self.assertLess(self.column("tax", "spending: top 1%")[11], self.column("tax", "spending: top 1%")[0])       # poorer and poorer
        self.run_lisp('(define double (wealth-tax-responses tax-model :rate 2))')
        self.assertTrue(numpy.allclose(self.column("double", "GDP"), 2 * self.column("tax", "GDP")))

    def test_the_wealth_taxs_effects_follow_the_assumptions(self):
        nobody = '(list (cons "revenue_to_bottom50" 0) (cons "revenue_to_next40" 0) (cons "revenue_to_next9" 0) (cons "revenue_to_top1" 0)'
        self.run_lisp('(define avoided (wealth-tax-responses (types-model :quarters 8 :parameters (list (cons "tax_avoidance" 1))) :rate 1))'
                      '(define debt (wealth-tax-responses (types-model :quarters 8 :parameters %s)) :rate 1))' % nobody +
                      '(define spent (wealth-tax-responses (types-model :quarters 8 :parameters %s (cons "revenue_to_purchases" 1))) :rate 1))' % nobody)
        for name in ("tax revenue", "GDP", "spending: top 1%"):
            self.assertTrue(numpy.allclose(self.column("avoided", name), 0), name)       # all avoided, so nothing collected or changed
        self.assertTrue(numpy.allclose(self.column("debt", "spending: bottom 50%"), 0, atol=0.3))      # revenue to retire debt reaches nobody (it was 1.8 when paid out)
        self.assertTrue(numpy.allclose(self.column("spent", "government purchases"), self.column("spent", "tax revenue")))
        self.assertGreater(self.column("spent", "GDP")[0], self.column("debt", "GDP")[0])           # spending it supports demand

    def test_compare_wealth_taxes_has_a_row_for_each_result_and_quarter(self):
        self.run_lisp('(define table (compare-wealth-taxes (list (list "a" (types-model :quarters 10))'
                      ' (list "b" (types-model :quarters 10 :parameters (list (cons "tax_avoidance" 0.5))))) :quarters (list 1 5 10)))')
        self.assertShows('(table-row-count table)', '6')
        self.assertShows('(map car table)', '("assumptions" "quarter" "GDP" "investment" "consumption" "spending: bottom 50%" "spending: top 1%" "tax revenue")')
        revenue = self.column("table", "tax revenue")
        self.assertAlmostEqual(revenue[3], revenue[0] * 0.5 / 0.8, delta=0.02)          # half avoided rather than a fifth: five eighths the revenue

    def test_plot_wealth_tax_draws_six_panels(self):
        charts = []
        env = lisp_builtins.make_global_env(output=self.out.append, plot=charts.append)
        self.run_lisp('(load "macro_models.lsp")(plot-wealth-tax (types-model :quarters 8))', env)
        self.assertEqual(len(charts[0]["panels"]), 6)

    def test_plot_types_crash_draws_a_panel_for_the_groups_spending_and_income_and_the_economy(self):
        charts = []
        env = lisp_builtins.make_global_env(output=self.out.append, plot=charts.append)
        self.run_lisp('(load "macro_models.lsp")(plot-types-crash (types-model :quarters 6))', env)
        self.assertEqual(len(charts), 1)
        self.assertEqual(len(charts[0]["panels"]), 6)



class TestAiInvestmentData(LispTestCase):

    def test_computer_investment_is_shown_as_a_percent_of_gdp(self):
        with mock.patch.object(lisp_fred, "download_series", fake_fred_series):
            self.run_lisp('(load "macro_models.lsp")(define d (ai-investment-data "creds.json" :start (date 2000 1 1)))')
        self.assertShows('(map car d)', '("date" "GDP" "computer investment" "percent of GDP")')
        gdp = numpy.array(self.run_lisp('(table-column d "GDP")').items)
        computers = numpy.array(self.run_lisp('(table-column d "computer investment")').items)
        self.assertTrue(numpy.allclose(self.run_lisp('(table-column d "percent of GDP")').items, numpy.round(100 * computers / gdp, 2)))


@unittest.skipUnless(dynare_installed(), "needs GNU Octave and Dynare")
class TestAiBust(LispTestCase):
    """The shock to the AI companies, in the four-household model."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "macro_models.lsp")'
                      '(define solvency (second (second (ai-bust-scenarios))))')

    def column(self, table, name):
        return numpy.array(self.run_lisp('(table-column %s "%s")' % (table, name)).items)

    def test_without_an_ai_bust_the_ai_variables_stay_at_zero(self):
        self.run_lisp('(define crash (types-crash-responses (types-model :quarters 8) :fall 20))')
        for name in ("AI investment", "AI stocks", "AI productivity"):
            self.assertTrue(numpy.allclose(self.column("crash", name), 0), name)

    def test_the_bust_follows_its_parameters(self):
        # The solvency crisis: investment moves half way to a cut of 1% of GDP each quarter, as the bust fades by 0.98 a quarter
        self.run_lisp('(define r (ai-bust-responses (types-model :quarters 8 :parameters solvency)))')
        investment = self.column("r", "AI investment")
        self.assertAlmostEqual(investment[0], -0.5)
        self.assertAlmostEqual(investment[1], 0.5 * -0.5 - 0.5 * 1.0 * 0.98)
        self.assertAlmostEqual(self.column("r", "AI stocks")[0], -40)
        self.assertAlmostEqual(self.column("r", "AI stocks")[4], -40 * 0.98 ** 4)
        self.assertGreater(self.column("r", "credit spread")[0], 1)          # lenders' 1 point a year, and the accelerator adds to it
        self.assertLess(self.column("r", "GDP")[0], -0.5)
        self.assertLess(self.column("r", "spending: top 1%")[0], -5)         # the top 1% owns half the stocks

    def test_only_the_part_of_ai_investment_made_in_the_us_reaches_gdp(self):
        imported = '(append solvency (list (cons "ai_stock_fall" 0) (cons "ai_credit_stress" 0) (cons "ai_domestic_share" 0)))'
        self.run_lisp('(define r (ai-bust-responses (types-model :quarters 8 :parameters %s)))' % imported)
        self.assertLess(self.column("r", "AI investment")[0], -0.4)
        for name in ("GDP", "consumption", "investment", "Fed rate"):
            self.assertTrue(numpy.allclose(self.column("r", name), 0), name)

    def test_the_parts_add_up_to_the_whole(self):
        self.run_lisp('(define parts (ai-bust-parts (second (third (ai-bust-scenarios))) :quarters 8))'
                      '(define tables (map (lambda (entry) (ai-bust-responses (second entry))) parts))')
        self.assertShows('(map first parts)', '("all" "investment only" "stocks only" "credit only" "productivity only")')
        for name in ("GDP", "spending: bottom 50%", "Fed rate"):
            columns = [numpy.array(self.run_lisp('(table-column (list-ref tables %d) "%s")' % (k, name)).items) for k in range(5)]
            self.assertTrue(numpy.allclose(columns[0], sum(columns[1:])), name)
        # A scenario without a part leaves it out: the moratorium has no credit stress and no productivity gain
        self.assertShows('(map first (ai-bust-parts (second (first (ai-bust-scenarios))) :quarters 4))',
                         '("all" "investment only" "stocks only")')

    def test_compare_ai_busts_has_a_row_for_each_scenario_and_quarter(self):
        self.run_lisp('(define busts (ai-bust-models :quarters 8))(define table (compare-ai-busts busts :quarters (list 1 4)))')
        self.assertShows('(map first busts)', '("moratorium" "solvency crisis" "elastic demand")')
        self.assertShows('(table-row-count table)', '6')
        self.assertShows('(map car table)', '("scenario" "quarter" "GDP" "consumption" "other investment" "spending: bottom 50%" '
                         '"spending: top 1%" "Fed rate" "credit spread" "AI investment")')
        gdp = self.column("table", "GDP")
        self.assertLess(gdp[2], gdp[0])                       # the solvency crisis does more harm at first than the moratorium
        # :parameters changes every scenario: all of the investment imported, the moratorium's GDP is moved by its stocks alone
        self.run_lisp('(define imported (compare-ai-busts (ai-bust-models :quarters 8 :parameters (list (cons "ai_domestic_share" 0)))'
                      ' :quarters (list 1)))')
        self.assertNotAlmostEqual(self.column("imported", "GDP")[0], gdp[0])

    def test_the_plots_draw_six_panels(self):
        charts = []
        env = lisp_builtins.make_global_env(output=self.out.append, plot=charts.append)
        self.run_lisp('(load "macro_models.lsp")(define busts (ai-bust-models :quarters 6))'
                      '(plot-ai-busts busts)(plot-ai-bust (second (first busts)))', env)
        self.assertEqual(len(charts), 2)
        self.assertEqual([len(chart["panels"]) for chart in charts], [6, 6])


if __name__ == "__main__":
    unittest.main()
