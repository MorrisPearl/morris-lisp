"""The models of Freddie Mac's loans (lib/freddie_loans.lsp, freddie_prepayment.lsp and freddie_default.lsp), on small databases made here in the form that
load_freddie_data/ makes: months of loans whose prepayments and defaults are drawn from known curves, groups of them, and sales of defaulted loans with known
severities. The arithmetic (what is read, the rate of a month, what a model says of each row, the outcomes of the defaults) is checked against the same sums done
here, and the fitted curves against the curves the data were drawn from."""

import sqlite3
import tempfile

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

PREPAYMENT_PREDICTORS = ["incentive_bp", "loan_age", "loan_size_k", "credit_score", "current_ltv", "sato", "burnout",
                         "investor", "second_home", "cash_out", "refinance", "winter", "summer"]
DEFAULT_PREDICTORS = ["credit_score", "current_ltv", "loan_age", "dti", "sato", "incentive_bp", "loan_size_k",
                      "investor", "second_home", "cash_out", "refinance", "one_borrower"]
SEVERITY_PREDICTORS = ["ltv_at_default", "loan_size_k", "mi_percent", "months_since_default", "investor"]

LOAN_MONTH_COLUMNS = ["loan_id", "period", "sample_bucket", "calendar_month", "months_delinquent", "scheduled_upb", "start_upb", "smm", "incentive",
                      "loan_age", "credit_score", "current_ltv", "sato", "burnout", "occupancy", "purpose", "dti", "borrowers", "defaulted", "after_default",
                      "exit_code", "removal_upb", "loss", "severity", "ltv_at_default", "mi_percent", "months_since_default"]


def logistic(x):
    return 1 / (1 + np.exp(-x))


def chance_of_prepaying(incentive_bp):
    return logistic(-4.0 + 1.5 * incentive_bp / 100)


def chance_of_defaulting(current_ltv, credit_score):
    return logistic(-5.0 + 0.04 * (current_ltv - 80) - 0.01 * (credit_score - 720))


def drawn_severity(ltv_at_default):
    return 0.2 + 0.004 * (ltv_at_default - 60)


def write_loan_months(conn, rows):
    conn.execute("CREATE TABLE loan_months (%s)" % ", ".join(LOAN_MONTH_COLUMNS))
    conn.executemany("INSERT INTO loan_months VALUES (%s)" % ",".join("?" * len(LOAN_MONTH_COLUMNS)),
                     [[row.get(name) for name in LOAN_MONTH_COLUMNS] for row in rows])


def make_database(path, months=12, loans_a_month=2000, sales=600, seed=1):
    """A database with the tables loan_months and groups, with only the columns that the models read. A loan's chance of prepaying in a month rises with
    its incentive, and of defaulting with its loan-to-value and as its credit score falls; the severity of a sale rises with the loan-to-value at the default."""
    rng = np.random.default_rng(seed)
    rows = []
    for month in range(1, months + 1):
        for n in range(loans_a_month):
            incentive = rng.uniform(-1.5, 2.5)
            ltv, score = rng.uniform(40, 140), int(rng.integers(620, 820))
            balance = rng.uniform(100000, 400000)
            rows.append({"loan_id": "L%d-%d" % (month, n), "period": "2020-%02d-01" % month, "sample_bucket": int(rng.integers(0, 100)),
                         "calendar_month": month, "months_delinquent": int(rng.choice([0, 0, 0, 0, 5])), "scheduled_upb": balance, "start_upb": balance + 300,
                         "smm": 1.0 if rng.random() < chance_of_prepaying(incentive * 100) else 0.0, "incentive": incentive,
                         "loan_age": int(rng.integers(1, 200)), "credit_score": score, "current_ltv": ltv, "sato": rng.normal(0, 0.3),
                         "burnout": int(rng.integers(0, 30)), "occupancy": str(rng.choice(["P", "I", "S"])), "purpose": str(rng.choice(["P", "C", "N"])),
                         "dti": int(rng.integers(15, 50)), "borrowers": int(rng.choice([1, 2])),
                         "defaulted": 1 if rng.random() < chance_of_defaulting(ltv, score) else 0, "after_default": int(rng.random() < 0.05)})
    rows[0]["credit_score"] = None                                    # (a loan with no credit score is left out)
    for n in range(sales):
        ltv = rng.uniform(50, 150)
        removal = rng.uniform(50000, 300000)
        severity = drawn_severity(ltv) + rng.normal(0, 0.05)
        rows.append({"loan_id": "S%d" % n, "period": "%d-%02d-01" % (2010 + n % 4, 1 + n % 12), "sample_bucket": int(rng.integers(0, 100)),
                     "after_default": 1, "defaulted": 0, "exit_code": "09", "removal_upb": removal, "loss": severity * removal, "severity": severity,
                     "ltv_at_default": ltv, "mi_percent": int(rng.choice([0, 0, 25])), "months_since_default": int(rng.integers(6, 40)),
                     "occupancy": str(rng.choice(["P", "P", "I"])), "start_upb": removal, "scheduled_upb": removal})
    conn = sqlite3.connect(path)
    write_loan_months(conn, rows)
    conn.execute("""CREATE TABLE groups AS
                    SELECT period, CASE WHEN sample_bucket < 80 THEN 'fit' ELSE 'test' END AS part, calendar_month,
                           SUM(scheduled_upb) AS balance, SUM(smm * scheduled_upb) / SUM(scheduled_upb) AS smm,
                           SUM(scheduled_upb * incentive) / SUM(scheduled_upb) AS incentive,
                           SUM(scheduled_upb * loan_age) / SUM(scheduled_upb) AS loan_age,
                           SUM(scheduled_upb * start_upb) / SUM(scheduled_upb) AS loan_size,
                           SUM(scheduled_upb * credit_score) / SUM(CASE WHEN credit_score IS NOT NULL THEN scheduled_upb END) AS credit_score,
                           SUM(scheduled_upb * current_ltv) / SUM(scheduled_upb) AS current_ltv,
                           SUM(scheduled_upb * sato) / SUM(scheduled_upb) AS sato,
                           SUM(scheduled_upb * burnout) / SUM(scheduled_upb) AS burnout,
                           SUM(scheduled_upb * (occupancy = 'I')) / SUM(scheduled_upb) AS investor,
                           SUM(scheduled_upb * (occupancy = 'S')) / SUM(scheduled_upb) AS second_home,
                           SUM(scheduled_upb * (purpose = 'C')) / SUM(scheduled_upb) AS cash_out,
                           SUM(scheduled_upb * (purpose IN ('N', 'R'))) / SUM(scheduled_upb) AS refinance
                    FROM loan_months WHERE months_delinquent < 4 AND exit_code IS NULL
                    GROUP BY period, part, ROUND(incentive * 4)""")
    conn.commit()
    conn.close()


def make_outcomes_database(path):
    """Four loans that defaulted in 2020, of 100,000 each, and what became of them: one sold at a loss of 40,000 eight months later, one paid off, one sold as a
    note, and one not over yet; and one that defaulted in 2021 and was sold at a gain."""
    rows = [{"loan_id": loan, "period": "2020-03-01", "defaulted": 1, "start_upb": 100000.0} for loan in ("A", "B", "C", "D")]
    rows += [{"loan_id": "A", "period": "2020-11-01", "exit_code": "09", "removal_upb": 100000.0, "loss": 40000.0, "months_since_default": 8},
             {"loan_id": "B", "period": "2021-01-01", "exit_code": "01", "removal_upb": 100000.0},
             {"loan_id": "C", "period": "2021-06-01", "exit_code": "15", "removal_upb": 100000.0},
             {"loan_id": "E", "period": "2021-02-01", "defaulted": 1, "start_upb": 50000.0},
             {"loan_id": "E", "period": "2022-02-01", "exit_code": "03", "removal_upb": 50000.0, "loss": -1000.0, "months_since_default": 12}]
    conn = sqlite3.connect(path)
    write_loan_months(conn, rows)
    conn.commit()
    conn.close()


class ModelsCase(LispTestCase):

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.path = os.path.join(cls.folder, "loans.db")
        make_database(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "freddie_prepayment.lsp") (load "freddie_default.lsp") (define conn (sqlite-open "%s"))' % self.path)

    def vector(self, source):
        return np.array(self.run_lisp(source).items, dtype=float)

    def sql(self, query):
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute(query).fetchall()
        finally:
            conn.close()

    def names(self, names):
        return "(%s)" % " ".join('"%s"' % name for name in names)


class TestWhatTheModelsShare(ModelsCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('''(define data (freddie-loan-months conn "sample_bucket < 80"))
                         (define model (fit-prepayment-model data))''')

    def test_a_knot_without_data_on_both_sides_is_left_out(self):
        self.assertShows("(knots-within '(-100 0 300) (vector-range -150 251))", "(-100 0)")
        self.assertShows("(knots-within '(12) (vector 0.0 5.0))", "0")
        self.assertShows("(knots-within 0 (vector 0.0 5.0))", "0")
        self.assertShows("(knots-within '(5 99) (vector-range 0 100))", "(5)")         # (99 has only one value beyond it: a hundredth of them)
        self.assertIn("incentive_bp (knot 0)", self.run_lisp("(model-report model)"))
        self.assertNotIn("incentive_bp (knot 300)", self.run_lisp("(model-report model)"))   # (the incentives here are from -150 to 250 basis points)

    def test_what_the_model_says_of_each_row_is_its_prediction(self):
        predicted = self.vector("(predicted-outcomes model data)")
        first = self.run_lisp("(model-predict model (map (lambda (column) (vector-ref (cdr column) 0)) (loan-data-predictors data)))")
        self.assertAlmostEqual(predicted[0], first)
        self.assertTrue(((predicted > 0) & (predicted < 1)).all())

    def test_the_rate_of_a_month_is_of_all_its_loans_together_weighted_by_balance(self):
        self.run_lisp('(define months (rate-by-month model data "CPR"))')
        self.assertShows("(map car months)", '("month" "actual CPR" "predicted CPR")')
        self.assertShows('(vector-length (table-column months "month"))', "12")
        prepaid, balance = self.sql("""SELECT SUM(smm * scheduled_upb), SUM(scheduled_upb) FROM loan_months WHERE sample_bucket < 80 AND months_delinquent < 4
                                       AND credit_score IS NOT NULL AND exit_code IS NULL AND period = '2020-03-01'""")[0]
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column months "actual CPR") 2)'), 100 * (1 - (1 - prepaid / balance) ** 12))
        predicted, weights = self.vector("(predicted-outcomes model data)"), self.vector("(loan-data-weights data)")
        march = np.array([str(d) == "2020-03-01" for d in self.run_lisp("(loan-data-periods data)").items])
        smm = (predicted[march] * weights[march]).sum() / weights[march].sum()
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column months "predicted CPR") 2)'), 100 * (1 - (1 - smm) ** 12))

    def test_the_misses_are_the_average_distance_of_the_monthly_rates_before_and_after_a_date(self):
        self.run_lisp('''(define months (rate-by-month model data "CPR"))
                         (define misses (rate-misses (list (list "m" model data)) (date 2020 7 1) "CPR"))''')
        miss = np.abs(self.vector('(table-column months "predicted CPR")') - self.vector('(table-column months "actual CPR")'))
        self.assertShows("(map car misses)", '("model" "before 2020-07-01" "from 2020-07-01 on")')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column misses "before 2020-07-01") 0)'), miss[:6].mean())
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column misses "from 2020-07-01 on") 0)'), miss[6:].mean())

    def test_a_curve_varies_one_predictor_and_keeps_the_others(self):
        curve = self.vector('(model-curve model prepayment-predictors typical-prepayment-loan "incentive_bp" (vector 0 100))')
        # (typical-prepayment-loan: three years old, $250,000, a credit score of 750, 70% loan-to-value, and the rest 0)
        at = lambda bp: self.run_lisp("(model-predict model (list %d 36 250 750 70 0 0 0 0 0 0 0 0))" % bp)
        np.testing.assert_allclose(curve, [at(0), at(100)])


class TestThePrepaymentModel(ModelsCase):

    def test_the_months_of_loans_are_read_with_the_predictors_in_order(self):
        self.run_lisp('(define data (freddie-loan-months conn "sample_bucket < 80"))')
        self.assertShows("(map car (loan-data-predictors data))", self.names(PREPAYMENT_PREDICTORS))
        expected = self.sql("""SELECT COUNT(*) FROM loan_months WHERE sample_bucket < 80 AND months_delinquent < 4 AND credit_score IS NOT NULL
                               AND exit_code IS NULL""")[0][0]
        self.assertEqual(len(self.vector("(loan-data-outcomes data)")), expected)        # (a loan four months delinquent, or with no credit score, is left out)

    def test_what_each_predictor_is_of_a_loan(self):
        self.run_lisp('(define data (freddie-loan-months conn "sample_bucket < 80"))')
        row = self.sql("""SELECT incentive * 100, start_upb / 1000, occupancy = 'I', purpose IN ('N', 'R'), calendar_month IN (1, 2), scheduled_upb, smm
                          FROM loan_months WHERE sample_bucket < 80 AND months_delinquent < 4 AND credit_score IS NOT NULL AND exit_code IS NULL LIMIT 1""")[0]
        cell = lambda name: self.run_lisp('(vector-ref (cdr (assoc "%s" (loan-data-predictors data))) 0)' % name)
        self.assertAlmostEqual(cell("incentive_bp"), row[0])
        self.assertAlmostEqual(cell("loan_size_k"), row[1])
        self.assertEqual((cell("investor"), cell("refinance"), cell("winter")), tuple(float(x) for x in row[2:5]))
        self.assertAlmostEqual(self.run_lisp("(vector-ref (loan-data-weights data) 0)"), row[5])
        self.assertAlmostEqual(self.run_lisp("(vector-ref (loan-data-outcomes data) 0)"), row[6])

    def test_the_groups_are_read_with_their_averages(self):
        self.run_lisp('''(define data (freddie-groups conn "part = 'fit'"))''')
        self.assertShows("(map car (loan-data-predictors data))", self.names(PREPAYMENT_PREDICTORS))
        self.assertEqual(len(self.vector("(loan-data-outcomes data)")), self.sql("SELECT COUNT(*) FROM groups WHERE part = 'fit'")[0][0])
        shares = self.vector('(cdr (assoc "investor" (loan-data-predictors data)))')
        self.assertTrue(((shares > 0) & (shares < 1)).any())                                 # (a group's investor is a share of its balance)

    def test_the_s_curve_is_the_one_the_loans_were_drawn_from(self):
        self.run_lisp('(define curve (prepayment-s-curve (fit-prepayment-model (freddie-loan-months conn "sample_bucket < 80"))))')
        incentives = self.vector('(table-column curve "incentive_bp")')
        np.testing.assert_allclose(incentives, np.arange(-200, 401, 25))
        cprs = dict(zip(incentives, self.vector('(table-column curve "CPR")')))
        for bp in (-100, 0, 100, 200):
            self.assertAlmostEqual(cprs[bp], 100 * (1 - (1 - chance_of_prepaying(bp)) ** 12), delta=6.0)
        self.assertTrue(cprs[-100] < cprs[0] < cprs[100] < cprs[200])

    def test_a_model_fitted_to_the_groups_can_be_tried_on_the_loans_and_the_charts_are_drawn(self):
        self.run_lisp('''(define by-loan (fit-prepayment-model (freddie-loan-months conn "sample_bucket < 80")))
                         (define by-group (fit-prepayment-model (freddie-groups conn "part = 'fit'")))
                         (define test-loans (freddie-loan-months conn "sample_bucket >= 80"))''')
        self.assertShows('(vector-length (table-column (rate-by-month by-group test-loans "CPR") "predicted CPR"))', "12")
        with mock.patch("matplotlib.pyplot.show"):
            self.run_lisp('(plot-rate-by-month (list (list "loan by loan" by-loan test-loans) (list "by groups" by-group test-loans)) "CPR")')
            self.run_lisp('(plot-prepayment-s-curves (list (list "loan by loan" by-loan) (list "by groups" by-group)))')


class TestTheDefaultModel(ModelsCase):

    def test_the_months_of_loans_that_have_not_defaulted_are_read(self):
        self.run_lisp('(define data (freddie-default-months conn "sample_bucket < 80"))')
        self.assertShows("(map car (loan-data-predictors data))", self.names(DEFAULT_PREDICTORS))
        expected, defaults, balance = self.sql("""SELECT COUNT(*), SUM(defaulted), SUM(start_upb) FROM loan_months WHERE sample_bucket < 80 AND after_default = 0
                                                  AND credit_score IS NOT NULL""")[0]
        self.assertEqual(len(self.vector("(loan-data-outcomes data)")), expected)          # (a month after a loan defaulted is not one that it can default in)
        self.assertEqual(self.vector("(loan-data-outcomes data)").sum(), defaults)
        self.assertAlmostEqual(self.vector("(loan-data-weights data)").sum(), balance, places=2)
        row = self.sql("""SELECT borrowers = 1, dti FROM loan_months WHERE sample_bucket < 80 AND after_default = 0 AND credit_score IS NOT NULL LIMIT 1""")[0]
        self.assertEqual(self.run_lisp('(vector-ref (cdr (assoc "one_borrower" (loan-data-predictors data))) 0)'), row[0])
        self.assertEqual(self.run_lisp('(vector-ref (cdr (assoc "dti" (loan-data-predictors data))) 0)'), row[1])

    def test_the_cdr_rises_with_the_loan_to_value_and_falls_with_the_credit_score_as_the_loans_did(self):
        self.run_lisp('''(define defaults (fit-default-model (freddie-default-months conn "sample_bucket < 80")))
                         (define curves (default-ltv-curves defaults :scores '(660 780)))''')
        self.assertShows("(map car curves)", '("current_ltv" "CDR, credit score 660" "CDR, credit score 780")')
        np.testing.assert_allclose(self.vector('(table-column curves "current_ltv")'), np.arange(40, 161, 10))
        low, high = self.vector('(table-column curves "CDR, credit score 660")'), self.vector('(table-column curves "CDR, credit score 780")')
        self.assertTrue((low > high)[1:-1].all())
        self.assertGreater(low[8], 3 * low[2])                     # (at 120% loan-to-value, against 60%)
        drawn = lambda ltv, score: 100 * (1 - (1 - chance_of_defaulting(ltv, score)) ** 12)
        self.assertAlmostEqual(low[6], drawn(100, 660), delta=0.5 * drawn(100, 660))
        with mock.patch("matplotlib.pyplot.show"):
            self.run_lisp("(plot-default-ltv-curves defaults)")
            self.run_lisp('(plot-rate-by-month (list (list "model" defaults (freddie-default-months conn "sample_bucket >= 80"))) "CDR")')


class TestTheSeverityModel(ModelsCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('''(define sales (freddie-liquidations conn "sample_bucket < 80"))
                         (define severity (fit-severity-model sales))''')

    def test_the_sales_are_read_by_year_with_their_severities_weighted_by_balance(self):
        self.assertShows("(map car (loan-data-predictors sales))", self.names(SEVERITY_PREDICTORS))
        self.assertEqual(sorted({str(d) for d in self.run_lisp("(loan-data-periods sales)").items}), ["2010-01-01", "2011-01-01", "2012-01-01", "2013-01-01"])
        self.run_lisp("(define years (severity-by-year severity sales))")
        loss, balance = self.sql("SELECT SUM(loss), SUM(removal_upb) FROM loan_months WHERE loss IS NOT NULL AND sample_bucket < 80 AND period LIKE '2011%'")[0]
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column years "actual severity") 1)'), 100 * loss / balance)

    def test_the_severity_rises_with_the_loan_to_value_at_the_default_as_the_sales_did(self):
        self.run_lisp("(define curve (severity-ltv-curve severity))")
        severities = dict(zip(self.vector('(table-column curve "ltv_at_default")'), self.vector('(table-column curve "severity")')))
        for ltv in (60, 100, 140):
            self.assertAlmostEqual(severities[ltv], 100 * drawn_severity(ltv), delta=5.0)


class TestWhatBecameOfTheDefaults(LispTestCase):

    def test_the_shares_of_each_year_the_severity_and_the_loss_given_default(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "outcomes.db")
        make_outcomes_database(path)
        self.run_lisp('(load "freddie_default.lsp") (define outcomes (default-outcomes (sqlite-open "%s")))' % path)
        self.assertShows("(map car outcomes)", '("year" "defaults" "balance" "sold at a loss" "note sold" "paid off" "sold, paying" "not over" "severity" '
                                               '"months to the sale" "loss given default")')
        column = lambda name: list(self.run_lisp('(table-column outcomes "%s")' % name).items)
        self.assertEqual([str(year) for year in column("year")], ["2020", "2021"])
        self.assertEqual(column("defaults"), [4, 1])
        self.assertEqual(column("balance"), [400000.0, 50000.0])
        self.assertEqual([column(name)[0] for name in ("sold at a loss", "note sold", "paid off", "sold, paying", "not over")], [25.0, 25.0, 25.0, 0.0, 25.0])
        self.assertEqual(column("severity"), [40.0, -2.0])                     # (a sale for more than was owed is a gain)
        self.assertEqual(column("months to the sale"), [8.0, 12.0])
        self.assertEqual(column("loss given default"), [10.0, -2.0])           # (the loss over all that defaulted, sold or not)


if __name__ == "__main__":
    unittest.main()
