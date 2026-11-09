"""The Monte Carlo macro (apps_script/sensitivity.gs), run with macOS's JavaScript (osascript) against a stand-in
for Google's SpreadsheetApp (sensitivity_mock.js), and the Sensitivity tab that sets it up."""

import json
import os
import shutil
import statistics
import subprocess
import tempfile
import unittest
from unittest import mock

from support import *  # noqa: F401,F403 -- the interpreter's modules, and LispTestCase

import lisp_core
import lisp_financial_sensitivity as sensitivity
import lisp_google
from sheet_formulas import Sheets
from test_financial_asset_manager import build as build_asset_manager
from test_financial_bank_insurer import bank_facts, build as build_kind
from test_financial_model import build, TestModelByInSegment

HERE = os.path.dirname(os.path.abspath(__file__))
MACRO = os.path.join(HERE, "..", "apps_script", "sensitivity.gs")
MOCK = os.path.join(HERE, "sensitivity_mock.js")


def run_javascript(fixture=None):
    """What the scenarios of sensitivity_mock.js found, with the macro loaded: a dict. `fixture` is data for the
    scenario that runs the tab the three-statement model makes."""
    with open(MACRO) as macro, open(MOCK) as mock:
        program = "var FIXTURE = %s;\n%s\n%s" % (json.dumps(fixture), macro.read(), mock.read())
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "program.js")
        with open(path, "w") as file:
            file.write(program)
        done = subprocess.run(["osascript", "-l", "JavaScript", path], capture_output=True, text=True, timeout=300)
    output = (done.stdout or done.stderr).strip()
    try:
        return json.loads(output)
    except ValueError:
        raise AssertionError("the JavaScript did not run: %s" % output[:2000])


needs_javascript = unittest.skipUnless(shutil.which("osascript"), "macOS's JavaScript (osascript) is needed")


@needs_javascript
class TestTheMacro(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.found = run_javascript()

    def test_the_normal_distribution_functions_match_python(self):
        normal = statistics.NormalDist()
        for z, p in self.found["math"]["cdf"]:
            self.assertAlmostEqual(p, normal.cdf(z), delta=2e-7)
        for p, z in self.found["math"]["inverse"]:
            self.assertAlmostEqual(z, normal.inv_cdf(p), delta=2e-8)

    def test_uniform_values_are_equally_likely_from_low_to_high(self):
        sampled = self.found["math"]["sampled"]["uniform"]
        self.assertAlmostEqual(sampled["mean"], 6.0, delta=0.05)                  # (the average column is not used)
        self.assertAlmostEqual(sampled["deviation"], 8 / 12 ** 0.5, delta=0.05)
        self.assertGreaterEqual(sampled["min"], 2)
        self.assertLessEqual(sampled["max"], 10)

    def test_triangular_values_are_likeliest_at_the_average(self):
        sampled = self.found["math"]["sampled"]["triangular"]
        low, mode, high = 2, 3, 10
        self.assertAlmostEqual(sampled["mean"], (low + mode + high) / 3, delta=0.05)
        variance = (low ** 2 + mode ** 2 + high ** 2 - low * mode - low * high - mode * high) / 18
        self.assertAlmostEqual(sampled["deviation"], variance ** 0.5, delta=0.05)
        self.assertGreaterEqual(sampled["min"], low)
        self.assertLessEqual(sampled["max"], high)

    def test_normal_values_have_low_and_high_two_deviations_out_and_none_beyond(self):
        sampled = self.found["math"]["sampled"]["normal"]
        self.assertAlmostEqual(sampled["mean"], 5.0, delta=0.03)
        # (a deviation of 1.5 cut off at 2 deviations: about 0.88 of 1.5)
        truncated = statistics.NormalDist(0, 1)
        cut = truncated.cdf(2) - truncated.cdf(-2)
        expected = (1 - 2 * 2 * truncated.pdf(2) / cut) ** 0.5 * 1.5
        self.assertAlmostEqual(sampled["deviation"], expected, delta=0.03)
        self.assertGreaterEqual(sampled["min"], 2)
        self.assertLessEqual(sampled["max"], 8)

    def test_the_ends_and_middles_of_each_distribution(self):
        ends = self.found["math"]["ends"]
        self.assertEqual(ends["uniform"], [2, 6, 10])
        self.assertEqual(ends["triangular"][0], 2)
        self.assertEqual(ends["triangular"][2], 10)
        self.assertAlmostEqual(ends["normal"][0], 2, places=6)
        self.assertAlmostEqual(ends["normal"][1], 5, places=6)
        self.assertAlmostEqual(ends["normal"][2], 8, places=6)
        self.assertEqual(ends["flat"], [4, 4, 4])
        self.assertTrue(all(0 <= value <= 10 for value in ends["skewed"]))          # (an average off center is allowed)

    def test_standard_normal_draws(self):
        draws = self.found["math"]["randomNormals"]
        self.assertAlmostEqual(draws["mean"], 0, delta=0.03)
        self.assertAlmostEqual(draws["deviation"], 1, delta=0.03)

    def test_the_same_seed_and_run_give_the_same_numbers_and_another_run_gives_others(self):
        self.assertEqual(self.found["math"]["sameSeedSameNumbers"], [True, True, False])

    def test_correlated_inputs_come_out_with_about_the_correlation_asked_for(self):
        found = self.found["correlation"]
        # (a uniform or triangular input, or a cut off normal, loses a little of the correlation)
        self.assertAlmostEqual(found["rho0.8"]["firstSecond"], 0.78, delta=0.04)
        self.assertAlmostEqual(found["rho-0.6"]["firstSecond"], -0.58, delta=0.05)
        self.assertAlmostEqual(found["rho0"]["firstSecond"], 0, delta=0.04)
        for key in ("rho0.8", "rho-0.6", "rho0"):
            self.assertAlmostEqual(found[key]["firstThird"], 0, delta=0.04)

    def test_correlations_that_cannot_all_be_true_are_refused_and_perfect_ones_work(self):
        found = self.found["correlation"]
        self.assertTrue(found["impossible"])
        self.assertEqual(found["perfect"], [[1, 0], [1, 0]])
        self.assertEqual(found["identity"], [[1, 0], [0, 1]])


@needs_javascript
class TestARun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.found = run_javascript()["run"]

    def test_it_finishes_with_a_note_of_the_seed_and_no_complaint(self):
        self.assertEqual(self.found["alerts"], [])
        self.assertEqual(self.found["status"], "Done: 400 runs, seed 123.")

    def test_the_header_is_run_then_each_input_and_each_output(self):
        self.assertEqual(self.found["header"], ["Run", "rate", "Model!B2", "total", "other"])

    def test_each_run_has_its_number_its_draws_and_what_the_model_made_of_them(self):
        for number, (run, rate, growth, total, other) in enumerate(self.found["runs"], start=1):
            self.assertEqual(run, number)
            self.assertTrue(0.03 <= rate <= 0.07)
            self.assertTrue(0.01 <= growth <= 0.04)
            self.assertAlmostEqual(total, 1000 * (1 + rate) * (1 + growth), places=9)
            self.assertAlmostEqual(other, rate + growth, places=12)
        self.assertEqual(self.found["lastRunNumber"], 400)
        self.assertEqual(self.found["afterTheLastRun"], "")

    def test_the_draws_follow_the_distributions_and_the_correlation(self):
        rates = [row[1] for row in self.found["runs"]]
        growths = [row[2] for row in self.found["runs"]]
        self.assertAlmostEqual(statistics.mean(rates), 0.05, delta=0.003)
        self.assertAlmostEqual(statistics.mean(growths), (0.01 + 0.02 + 0.04) / 3, delta=0.002)
        self.assertGreater(statistics.correlation(rates, growths), 0.6)

    def test_the_inputs_are_put_back_a_number_as_a_number_and_a_formula_as_a_formula(self):
        self.assertEqual(self.found["rateCell"], [0.05, ""])
        self.assertEqual(self.found["growthCell"], ["=rate/2", 0.025])
        self.assertIsNone(self.found["savedInputsLeft"])

    def test_the_summary_is_formulas_over_the_runs_and_the_columns_keep_their_formats(self):
        self.assertEqual(self.found["summaryLabels"][0], "Mean")
        self.assertEqual(self.found["summaryLabels"][-1], "Highest")
        self.assertEqual(self.found["summaryFormulas"], ["=AVERAGE(B31:B430)", "=PERCENTILE(D31:D430,0.05)", "=MAX(E31:E430)"])
        self.assertEqual(self.found["format"], "General")

    def test_the_same_seed_gives_the_same_runs(self):
        self.assertTrue(self.found["sameAgain"])

    def test_a_run_that_stops_for_time_continues_to_the_same_result(self):
        self.assertIn("Stopped after 1 of 400 runs", self.found["stoppedStatus"])
        self.assertIn("goes on by itself in a minute", self.found["stoppedStatus"])
        self.assertEqual(self.found["timerSet"], [{"name": "continueMonteCarlo", "after": 60000}])
        self.assertEqual(self.found["timersAfterwards"], [])
        self.assertEqual(self.found["stoppedAfter"], "")
        self.assertEqual(self.found["inputsBackWhenStopped"], [0.05, "=rate/2"])
        self.assertEqual(self.found["continuedStatus"], "Done: 400 runs, seed 123.")
        self.assertTrue(self.found["continuedSame"])
        self.assertEqual(self.found["continuedAlerts"], [])

    def test_mistakes_in_the_setup_are_explained_and_leave_the_model_alone(self):
        wanted = {
            "distribution": "uniform, triangular, or normal, not \"bell\"",
            "order": "Low, Average, High in order",
            "unknown": "no named range or cell called nothing_here",
            "noruns": "Number of runs",
            "notinput": "total is not one of the inputs",
            "itself": "can't be correlated with itself",
            "tooBig": "a number from -1 to 1",
            "noOutputs": "no outputs",
            "average": "Low, Average, High in order",
        }
        for name, text in wanted.items():
            mistake = self.found["mistakes"][name]
            self.assertEqual(len(mistake["alerts"]), 1, name)
            self.assertIn(text, mistake["alerts"][0], name)
            self.assertTrue(mistake["status"].startswith("Stopped: "), name)
            self.assertEqual((mistake["rate"], mistake["growth"]), (0.05, "=rate/2"), name)

    def test_the_inputs_can_be_put_back_by_hand_after_a_run_was_cut_off(self):
        self.assertEqual(self.found["putBack"]["rate"], 0.05)
        self.assertEqual(self.found["putBack"]["growth"], "=rate/2")
        self.assertIn("2 input cells are as they were", self.found["putBack"]["alerts"][0])
        self.assertIn("No input cells had been changed", self.found["putBackNothing"][0])

    def test_there_is_nothing_to_continue_before_a_first_run(self):
        self.assertIn("no run to continue", self.found["noRunToContinue"][0])


def tab_named(model, name):
    return next((tab for tab in model.sheets() if tab["name"] == name), None)


class TestTheModelsTabs(unittest.TestCase):
    """The tabs three-statement-model makes: the layout the macro expects, and the macro run on it."""

    def setUp(self):
        self.model = build()
        self.tab = tab_named(self.model, "Sensitivity")
        self.sheets = Sheets(self.model.sheets())

    def column_a(self):
        return [row[0][0] if row[0] else None for row in self.tab["cells"]]

    def table(self, title):
        """The rows (numbers, from 1) of the table under a title, after its header."""
        start = self.column_a().index(title) + 2
        end = start
        while end < len(self.tab["cells"]) and self.tab["cells"][end][0] is not None:        # (up to the empty row)
            end += 1
        return list(range(start + 1, end + 1))

    def test_the_tabs_follow_the_dcf_tab_and_a_company_without_a_dcf_has_neither(self):
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertEqual(names[names.index("DCF"):names.index("DCF") + 3], ["DCF", "Sensitivity", "Sensitivity Macro"])
        for kind_model in (build_kind(bank_facts(), "bank"),):
            self.assertNotIn("Sensitivity", [tab["name"] for tab in kind_model.sheets()])

    def test_the_option_leaves_them_out(self):
        self.model.sensitivity = False
        names = [tab["name"] for tab in self.model.sheets()]
        self.assertNotIn("Sensitivity", names)
        self.assertNotIn("Sensitivity Macro", names)

    def test_the_tab_has_the_parts_the_macro_looks_for(self):
        labels = self.column_a()
        for title in ("Inputs", "Correlations", "Outputs", "Results"):
            self.assertEqual(labels.count(title), 1, title)
        self.assertEqual(labels.index("Inputs") < labels.index("Correlations") < labels.index("Outputs") < labels.index("Results"), True)
        self.assertEqual(self.tab["cells"][labels.index("Inputs") + 1][0][0], "Input")
        self.assertEqual([self.tab["cells"][labels.index("Inputs") + 1][c][0] for c in range(1, 6)],
                         ["Distribution", "Low", "Average", "High", "What it is"])
        self.assertEqual(self.sheets.value("Sensitivity", labels.index("Number of runs"), 1), 1000)
        self.assertTrue(any(label and label.startswith("Random seed") for label in labels))
        self.assertTrue(any(label == "Status" for label in labels))

    def test_the_results_are_the_last_thing_so_the_macro_can_write_below_them(self):
        self.assertEqual(self.column_a()[-1], "Results")

    def test_the_inputs_are_named_cells_of_the_model_centered_on_its_own_numbers(self):
        names = {name for tab in self.model.sheets() for name, _ in tab.get("names", [])}
        inputs = self.table("Inputs")
        filled = [row for row in inputs if self.tab["cells"][row - 1][0][0]]
        self.assertEqual([self.tab["cells"][row - 1][0][0] for row in filled],
                         ["revenue_growth", "gross_margin", "beta", "risk_premium", "terminal_growth"])
        for row in filled:
            name = self.tab["cells"][row - 1][0][0]
            self.assertIn(name, names)
            low, average, high = [self.sheets.value("Sensitivity", row - 1, c) for c in (2, 3, 4)]
            self.assertAlmostEqual(average, self.sheets.at(*self.where(name)))
            self.assertLess(low, average)
            self.assertLess(average, high)
            self.assertIn(self.tab["cells"][row - 1][1][0], sensitivity.DISTRIBUTIONS)
        beta_row = filled[2]
        self.assertAlmostEqual(self.sheets.value("Sensitivity", beta_row - 1, 2), 0.75)
        self.assertAlmostEqual(self.sheets.value("Sensitivity", beta_row - 1, 4), 1.25)

    def where(self, name):
        for tab in self.model.sheets():
            for tab_name, address in tab.get("names", []):
                if tab_name == name:
                    return tab["name"], address

    def test_the_outputs_are_the_dcf_results(self):
        outputs = [self.tab["cells"][row - 1][0][0] for row in self.table("Outputs") if self.tab["cells"][row - 1][0][0]]
        self.assertEqual(outputs, ["sum_present_values", "present_terminal_value", "enterprise_value", "terminal_share",
                                   "equity_value", "value_per_share"])
        for name in outputs:
            self.assertEqual(self.where(name)[0], "DCF")

    def test_a_share_price_adds_the_comparison_with_it(self):
        priced = build()
        priced.share_price = 100.0
        outputs = [row[0][0] for row in tab_named(priced, "Sensitivity")["cells"] if row[0] and row[0][0] == "against_price"]
        self.assertEqual(outputs, ["against_price"])

    def test_a_model_by_segment_varies_the_segments_growth_and_an_asset_manager_its_assets_and_fee(self):
        by_segment = tab_named(build(segments=TestModelByInSegment.segments), "Sensitivity")
        names = [row[0][0] for row in by_segment["cells"][11:23] if row[0] and row[0][0]]
        self.assertEqual(names[:3], ["widgets_growth", "services_growth", "other_revenue_growth"])
        self.assertNotIn("revenue_growth", names)
        manager = tab_named(build_asset_manager(), "Sensitivity")
        names = [row[0][0] for row in manager["cells"][11:23] if row[0] and row[0][0]]
        self.assertEqual(names[:3], ["aum_growth", "fee_rate", "gross_margin"])

    def test_the_distribution_and_correlation_cells_have_drop_down_lists(self):
        validations = self.tab["validations"]
        inputs, correlations = self.table("Inputs"), self.table("Correlations")
        self.assertEqual(validations[0], {"range": "B%d:B%d" % (inputs[0], inputs[-1]), "choices": ["uniform", "triangular", "normal"]})
        self.assertEqual(validations[1], {"range": "A%d:B%d" % (correlations[0], correlations[-1]),
                                          "from": "$A$%d:$A$%d" % (inputs[0], inputs[-1])})

    def test_the_formulas_all_work_out(self):
        for row in range(len(self.tab["cells"])):
            for column in range(6):
                self.sheets.value("Sensitivity", row, column)

    def test_the_macro_tab_holds_the_script_in_one_cell_after_its_heading(self):
        macro = tab_named(self.model, "Sensitivity Macro")
        cells = [row[0][0] for row in macro["cells"] if row and row[0]]
        self.assertEqual(cells[-2], "The script")
        self.assertEqual(cells[-1], sensitivity.macro_text())
        self.assertLess(len(cells[-1]), 50000)
        self.assertTrue(any("Extensions > Apps Script" in text for text in cells))
        self.assertTrue(any("runMonteCarlo" in text for text in cells))

    def test_the_notes_say_what_the_tab_is_for(self):
        notes = self.model.sources_for_notes()
        self.assertTrue(any("The Sensitivity tab runs this valuation many times" in note for note in notes))
        self.model.sensitivity = False
        self.assertFalse(any("The Sensitivity tab" in note for note in self.model.sources_for_notes()))

    @needs_javascript
    def test_the_macro_runs_on_the_tab_as_it_is_made(self):
        runs = 30
        rows = []
        for r, row in enumerate(self.tab["cells"]):
            values = []
            for c in range(6):
                cell = row[c] if c < len(row) else None
                content = cell[0] if cell else None
                values.append(self.sheets.value("Sensitivity", r, c) if isinstance(content, str) and content.startswith("=") else content)
            rows.append(values)
        labels = self.column_a()
        rows[labels.index("Number of runs")][1] = runs
        rows[[n for n, label in enumerate(labels) if label and label.startswith("Random seed")][0]][1] = 7
        inputs = [rows[row - 1][0] for row in self.table("Inputs") if rows[row - 1][0]]
        outputs = [rows[row - 1][0] for row in self.table("Outputs") if rows[row - 1][0]]
        names = {}
        for tab in self.model.sheets():
            for name, address in tab.get("names", []):
                names[name] = self.sheets.at(tab["name"], address)
        found = run_javascript({"sensitivity": rows, "names": names, "inputs": inputs, "outputs": outputs,
                                "runs": runs, "statusRow": labels.index("Status") + 1})["fixture"]
        self.assertEqual(found["alerts"], [])
        self.assertEqual(found["status"], "Done: 30 runs, seed 7.")
        self.assertEqual(found["header"], ["Run"] + inputs + outputs)
        bounds = {rows[row - 1][0]: rows[row - 1][2:5] for row in self.table("Inputs") if rows[row - 1][0]}
        for number, run in enumerate(found["runs"], start=1):
            self.assertEqual(run[0], number)
            drawn = run[1:1 + len(inputs)]
            for name, value in zip(inputs, drawn):
                low, _, high = bounds[name]
                self.assertTrue(low <= value <= high, (name, low, value, high))
            expected = sum((n + 1) * value for n, value in enumerate(drawn))
            for value in run[1 + len(inputs):]:
                self.assertAlmostEqual(value, expected, places=9)
        self.assertEqual([cell[0] for cell in found["inputRanges"]], [names[name] for name in inputs])
        self.assertEqual([cell[1] for cell in found["inputRanges"]], [""] * len(inputs))


class TestAStandaloneWorkbook(LispTestCase):

    def setUp(self):
        super().setUp()
        self.requests = []
        for patcher in (mock.patch.object(lisp_google, "access_token", lambda *a: "token"),
                        mock.patch.object(lisp_google, "google_request", self.fake_request)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_request(self, method, url, who, headers, body=None):
        body = json.loads(body)
        self.requests.append((url, body))
        if url == lisp_google.SHEETS_URL:
            return {"spreadsheetId": "ID1", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/ID1/edit",
                    "sheets": [{"properties": {"sheetId": 7 + i}} for i in range(len(body["sheets"]))]}
        return {}

    def test_the_workbook_has_the_empty_tab_and_the_macro_and_drop_downs(self):
        url = self.run_lisp('(sensitivity-workbook "creds" "My analysis" :runs 250)')
        self.assertEqual(str(url), "https://docs.google.com/spreadsheets/d/ID1/edit")
        made = self.requests[0][1]
        self.assertEqual([sheet["properties"]["title"] for sheet in made["sheets"]], ["Sensitivity", "Sensitivity Macro"])
        edits = self.requests[1][1]["requests"]
        validations = [edit["setDataValidation"] for edit in edits if "setDataValidation" in edit]
        self.assertEqual(len(validations), 2)
        self.assertEqual(validations[0]["rule"]["condition"]["type"], "ONE_OF_LIST")
        self.assertEqual([v["userEnteredValue"] for v in validations[0]["rule"]["condition"]["values"]],
                         ["uniform", "triangular", "normal"])
        self.assertEqual(validations[0]["range"], {"sheetId": 7, "startRowIndex": 11, "endRowIndex": 23,
                                                   "startColumnIndex": 1, "endColumnIndex": 2})
        self.assertEqual(validations[1]["rule"]["condition"],
                         {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=$A$12:$A$23"}]})
        runs = edits[0]["updateCells"]["rows"][5]["values"][1]["userEnteredValue"]
        self.assertEqual(runs, {"numberValue": 250})

    def test_the_macro_is_available_as_text(self):
        text = self.run_lisp("(sensitivity-macro)")
        self.assertEqual(str(text), sensitivity.macro_text())
        self.assertIn("function runMonteCarlo", str(text))

    def test_runs_must_be_a_whole_number(self):
        for bad in ("0", "2.5", '"many"'):
            with self.assertRaises(lisp_core.LispError):
                self.run_lisp('(sensitivity-workbook "creds" "T" :runs %s)' % bad)


if __name__ == "__main__":
    unittest.main()
