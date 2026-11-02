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


class TestReadingResults(unittest.TestCase):
    """What dynare-run makes of export_results.m's results.json, without running Dynare."""

    def test_a_response_name_is_split_at_the_shock_even_with_underscores_in_both(self):
        self.assertEqual(lisp_dynare.split_irf_name("pi_c_e_oil", ["y", "pi_c", "pi_q"], ["e_oil", "e_i"]), ("pi_c", "e_oil"))
        self.assertEqual(lisp_dynare.split_irf_name("y_e_i", ["y", "pi_c"], ["e_oil", "e_i"]), ("y", "e_i"))
        self.assertEqual(lisp_dynare.split_irf_name("nothing_here", ["y"], ["e_i"]), (None, None))

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
        self.assertShows('(map car d)', '("date" "dy_obs" "dw_obs" "pi_q_obs" "pi_c_obs" "i_obs" "ds_obs")')
        self.assertShows('(table-row-count d)', '40')
        self.assertShows('(vector-ref (table-column d "date") 0)', '1990-01-01')
        for column in ("dy_obs", "i_obs", "ds_obs"):
            self.assertAlmostEqual(self.run_lisp('(vector-mean (table-column d "%s"))' % column), 0, places=10)
        # GDP growth is the change in the log, in percent; the oil price is real (less core inflation)
        gdp = fake_fred_series("GDPC1", None, None, None, 0, "", "quarterly").cdr.items
        growth = 100 * numpy.diff(numpy.log(gdp))
        first = 4 * (1990 - 1984)                     # the quarter of 1990-01-01, less one, in the fake's series of growth rates
        expected = growth[first - 1:first - 1 + 40]
        self.assertTrue(numpy.allclose(self.run_lisp('(table-column d "dy_obs")').items, expected - expected.mean()))


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
        self.assertAlmostEqual(oil["real oil price"][1], 9.5)               # rho_s is 0.95
        # Headline inflation is core plus oil's share (chi, 0.02) of the oil price's rise, both at an annual rate (times 4)
        self.assertAlmostEqual(oil["headline inflation"][0] - oil["core inflation"][0], 4 * 0.02 * 10)
        self.assertLess(oil["consumption"][0], 0)
        self.assertGreater(oil["core inflation"][0], 0)
        self.assertGreater(oil["Fed rate"][0], 0)
        # Linear: twice the rise, twice the responses
        twice = self.run_lisp('(table-column (oil-shock-responses base :rise 20) "GDP")').items
        self.assertTrue(numpy.allclose(twice, 2 * oil["GDP"]))

    def test_a_scenario_changes_the_parameters_it_names_and_no_others(self):
        self.run_lisp('(define base (oil-model))'
                      '(define rigid (oil-model :parameters (list (cons "gamma" 0.9))))'
                      '(define (value r name) (vector-ref (table-column (table-filter (hash-table-ref r "parameters")'
                      '                        (vector= (table-column (hash-table-ref r "parameters") "name") name)) "value") 0))')
        self.assertShows('(value rigid "gamma")', '0.9')
        self.assertShows('(value rigid "theta")', '0.75')
        base_core = self.run_lisp('(table-column (oil-shock-responses base) "core inflation")').items
        rigid_core = self.run_lisp('(table-column (oil-shock-responses rigid) "core inflation")').items
        self.assertGreater(rigid_core[0], base_core[0])     # rigid real wages make the rise in costs, and in core inflation, larger

    def test_every_shock_has_responses_and_a_variance_decomposition(self):
        self.run_lisp('(define base (oil-model))')
        self.assertShows('(sort (hash-table-keys (hash-table-ref base "responses")))',
                         '("e_a" "e_i" "e_oil" "e_p" "e_w" "e_z")')
        self.assertTrue(self.run_lisp('(vector-ref (table-column (oil-model-responses base "e_i") "Fed rate") 0)') > 0)
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
                      '(plot-oil-shock (list (list "a" (oil-model)) (list "b" (oil-model :parameters (list (cons "phi_pi" 3))))))', env)
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
        self.assertIn("theta", names)
        self.assertIn("stderr e_oil", names)
        low, mean, high = (self.run_lisp('(table-column (hash-table-ref est "estimates") "%s")' % c).items for c in ("low", "mean", "high"))
        self.assertTrue(numpy.all(low <= mean) and numpy.all(mean <= high))
        oil = self.run_lisp('(oil-shock-responses est :rise 10)')
        columns = [str(p.car) for p in lisp_core.pairs_to_list(oil)]
        self.assertIn("GDP low", columns)
        self.assertIn("GDP high", columns)
        # The estimate's parameters, as a scenario takes them: the shocks' sizes by their parameter names, no measurement error
        parameters = dict((str(p.car), p.cdr) for p in lisp_core.pairs_to_list(self.run_lisp('(oil-model-estimated-parameters est)')))
        self.assertIn("sigma_oil", parameters)
        self.assertNotIn("stderr pi_c_obs", parameters)
        self.assertAlmostEqual(parameters["theta"], mean[names.index("theta")])
        self.run_lisp('(define scenario (oil-model :from est :parameters (list (cons "core_weight" 1))))')
        self.assertShows('(vector-ref (table-column (table-filter (hash-table-ref scenario "parameters")'
                         ' (vector= (table-column (hash-table-ref scenario "parameters") "name") "core_weight")) "value") 0)', '1.0')
        self.run_lisp('(show-oil-estimates est)')


if __name__ == "__main__":
    unittest.main()
