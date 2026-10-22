"""The prepayment model of lib/freddie_prepayment.lsp, on a small database made here in the form that load_freddie_data/ makes: loan months whose
prepayments are drawn from a known S-curve, and groups. The arithmetic (what is read, the CPR of a month, what the model says of each row) is
checked against the same sums done here."""

import sqlite3
import tempfile

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

PREDICTORS = ["incentive_bp", "loan_age", "loan_size_k", "credit_score", "current_ltv", "sato", "burnout",
              "investor", "second_home", "cash_out", "refinance", "winter", "summer"]


def make_database(path, months=12, loans_a_month=2000, seed=1):
    """A database with the tables loan_months and groups, with only the columns that freddie_prepayment.lsp reads. A loan's chance of
    prepaying in a month rises with its incentive."""
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE loan_months (period TEXT, sample_bucket INTEGER, calendar_month INTEGER, months_delinquent INTEGER,
                    scheduled_upb REAL, start_upb REAL, smm REAL, incentive REAL, loan_age INTEGER, credit_score INTEGER, current_ltv REAL,
                    sato REAL, burnout INTEGER, occupancy TEXT, purpose TEXT)""")
    rows = []
    for month in range(1, months + 1):
        for _ in range(loans_a_month):
            incentive = rng.uniform(-1.5, 2.5)
            chance = 1 / (1 + np.exp(-(-4.0 + 1.5 * incentive)))
            balance = rng.uniform(100000, 400000)
            rows.append(("2020-%02d-01" % month, int(rng.integers(0, 100)), month, int(rng.choice([0, 0, 0, 0, 5])),
                         balance, balance + 300, 1.0 if rng.random() < chance else 0.0, incentive, int(rng.integers(1, 200)),
                         int(rng.integers(620, 820)), rng.uniform(40, 95), rng.normal(0, 0.3), int(rng.integers(0, 30)),
                         str(rng.choice(["P", "I", "S"])), str(rng.choice(["P", "C", "N"]))))
    rows[0] = rows[0][:9] + (None,) + rows[0][10:]                    # (a loan with no credit score is left out)
    conn.executemany("INSERT INTO loan_months VALUES (%s)" % ",".join("?" * 15), rows)
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
                    FROM loan_months WHERE months_delinquent < 4
                    GROUP BY period, part, ROUND(incentive * 4)""")
    conn.commit()
    conn.close()


class PrepaymentCase(LispTestCase):

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
        self.run_lisp('(load "freddie_prepayment.lsp") (define conn (sqlite-open "%s"))' % self.path)

    def vector(self, source):
        return np.array(self.run_lisp(source).items, dtype=float)

    def sql(self, query):
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute(query).fetchall()
        finally:
            conn.close()


class TestReadingTheData(PrepaymentCase):

    def test_the_months_of_loans_are_read_with_the_predictors_in_order(self):
        self.run_lisp('(define data (freddie-loan-months conn "sample_bucket < 80"))')
        self.assertShows("(map car (prepayment-data-predictors data))", "(%s)" % " ".join('"%s"' % name for name in PREDICTORS))
        expected = self.sql("SELECT COUNT(*) FROM loan_months WHERE sample_bucket < 80 AND months_delinquent < 4 AND credit_score IS NOT NULL")[0][0]
        self.assertEqual(len(self.vector("(prepayment-data-smm data)")), expected)          # (a loan four months delinquent, or with no credit score, is left out)

    def test_what_each_predictor_is_of_a_loan(self):
        self.run_lisp('(define data (freddie-loan-months conn "sample_bucket < 80"))')
        row = self.sql("""SELECT incentive * 100, start_upb / 1000, occupancy = 'I', purpose IN ('N', 'R'), calendar_month IN (1, 2), scheduled_upb
                          FROM loan_months WHERE sample_bucket < 80 AND months_delinquent < 4 AND credit_score IS NOT NULL LIMIT 1""")[0]
        cell = lambda name: self.run_lisp('(vector-ref (cdr (assoc "%s" (prepayment-data-predictors data))) 0)' % name)
        self.assertAlmostEqual(cell("incentive_bp"), row[0])
        self.assertAlmostEqual(cell("loan_size_k"), row[1])
        self.assertEqual((cell("investor"), cell("refinance"), cell("winter")), tuple(float(x) for x in row[2:5]))
        self.assertAlmostEqual(self.run_lisp("(vector-ref (prepayment-data-weights data) 0)"), row[5])

    def test_the_groups_are_read_with_their_averages(self):
        self.run_lisp('''(define data (freddie-groups conn "part = 'fit'"))''')
        self.assertShows("(map car (prepayment-data-predictors data))", "(%s)" % " ".join('"%s"' % name for name in PREDICTORS))
        self.assertEqual(len(self.vector("(prepayment-data-smm data)")), self.sql("SELECT COUNT(*) FROM groups WHERE part = 'fit'")[0][0])
        shares = self.vector('(cdr (assoc "investor" (prepayment-data-predictors data)))')
        self.assertTrue(((shares > 0) & (shares < 1)).any())                                 # (a group's investor is a share of its balance)


class TestTheModel(PrepaymentCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('''(define data (freddie-loan-months conn "sample_bucket < 80"))
                         (define model (fit-prepayment-model data))''')

    def test_a_cpr_is_twelve_months_of_an_smm(self):
        self.assertAlmostEqual(self.run_lisp("(cpr-of-smm 0.01)"), 100 * (1 - 0.99 ** 12))
        np.testing.assert_allclose(self.vector("(cpr-of-smm (vector 0.0 0.05))"), [0.0, 100 * (1 - 0.95 ** 12)])

    def test_what_the_model_says_of_each_row_is_its_prediction(self):
        predicted = self.vector("(predicted-smm model data)")
        first = self.run_lisp("(model-predict model (map (lambda (column) (vector-ref (cdr column) 0)) (prepayment-data-predictors data)))")
        self.assertAlmostEqual(predicted[0], first)
        self.assertTrue(((predicted > 0) & (predicted < 1)).all())

    def test_the_cpr_of_a_month_is_of_all_its_loans_together_weighted_by_balance(self):
        self.run_lisp("(define months (prepayment-cpr-by-month model data))")
        self.assertShows('(vector-length (table-column months "month"))', "12")
        prepaid, balance = self.sql("""SELECT SUM(smm * scheduled_upb), SUM(scheduled_upb) FROM loan_months
                                        WHERE sample_bucket < 80 AND months_delinquent < 4 AND credit_score IS NOT NULL AND period = '2020-03-01'""")[0]
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column months "actual CPR") 2)'), 100 * (1 - (1 - prepaid / balance) ** 12))
        predicted = self.vector("(predicted-smm model data)")
        weights = self.vector("(prepayment-data-weights data)")
        march = np.array([str(d) == "2020-03-01" for d in self.run_lisp("(prepayment-data-periods data)").items])
        smm = (predicted[march] * weights[march]).sum() / weights[march].sum()
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column months "predicted CPR") 2)'), 100 * (1 - (1 - smm) ** 12))

    def test_the_s_curve_rises_with_the_incentive_as_the_loans_did(self):
        self.run_lisp("(define curve (prepayment-s-curve model))")
        incentives = self.vector('(table-column curve "incentive_bp")')
        np.testing.assert_allclose(incentives, np.arange(-200, 401, 25))
        cprs = dict(zip(incentives, self.vector('(table-column curve "CPR")')))
        drawn = lambda bp: 100 * (1 - (1 - 1 / (1 + np.exp(-(-4.0 + 1.5 * bp / 100)))) ** 12)     # (the curve the loans were drawn from)
        for bp in (-100, 0, 100, 200):
            self.assertAlmostEqual(cprs[bp], drawn(bp), delta=6.0)
        self.assertTrue(cprs[-100] < cprs[0] < cprs[100] < cprs[200])

    def test_the_misses_are_the_average_distance_of_the_monthly_cprs_before_and_after_a_date(self):
        self.run_lisp('''(define months (prepayment-cpr-by-month model data))
                         (define misses (prepayment-cpr-misses (list (list "m" model data)) (date 2020 7 1)))''')
        miss = np.abs(self.vector('(table-column months "predicted CPR")') - self.vector('(table-column months "actual CPR")'))
        self.assertShows("(map car misses)", '("model" "before 2020-07-01" "from 2020-07-01 on")')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column misses "before 2020-07-01") 0)'), miss[:6].mean())
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column misses "from 2020-07-01 on") 0)'), miss[6:].mean())

    def test_a_knot_beyond_the_data_is_left_out(self):
        self.assertShows("(knots-within '(-100 0 300) (vector-range -150 251))", "(-100 0)")
        self.assertShows("(knots-within '(12) (vector 0.0 5.0))", "0")
        self.assertShows("(knots-within 0 (vector 0.0 5.0))", "0")
        self.assertShows("(knots-within '(5 99) (vector-range 0 100))", "(5)")       # (99 has only one value beyond it: a hundredth of them)
        self.assertIn("knot 0", self.run_lisp("(model-report model)"))
        self.assertNotIn("incentive_bp (knot 300)", self.run_lisp("(model-report model)"))     # (the incentives here are from -150 to 250 basis points)

    def test_a_model_fitted_to_the_groups_can_be_tried_on_the_loans_and_the_charts_are_drawn(self):
        self.run_lisp('''(define by-group (fit-prepayment-model (freddie-groups conn "part = 'fit'")))
                         (define test-loans (freddie-loan-months conn "sample_bucket >= 80"))''')
        self.assertShows('(vector-length (table-column (prepayment-cpr-by-month by-group test-loans) "predicted CPR"))', "12")
        with mock.patch("matplotlib.pyplot.show"):
            self.run_lisp('(plot-cpr-by-month (list (list "loan by loan" model test-loans) (list "by groups" by-group test-loans)))')
            self.run_lisp('(plot-prepayment-s-curves (list (list "loan by loan" model) (list "by groups" by-group)))')


if __name__ == "__main__":
    unittest.main()
