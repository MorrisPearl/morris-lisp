"""Tests of loan_months.py: the months of a loan made by hand, as Freddie's files would have them, with numbers that can be worked out on paper.
Run with:  python3 -m unittest test_loan_months.py   (in this directory)"""

import unittest

from loan_months import loan_months, sample_bucket, scheduled_principal
from market_data import add_months, months_between


class FlatRates:
    """A survey rate of 5% in every month, but 4% in the months listed."""

    def __init__(self, lower_months=()):
        self.lower_months = set(lower_months)

    def rate(self, month):
        return 4.0 if month in self.lower_months else 5.0


class RisingPrices:
    """Home prices 1% higher each month after 2020-01, in every zip code."""

    def change(self, zip3, start, end):
        return 1.01 ** months_between(start, end)


LOAN = {"loan_id": "F20Q10000001", "first_payment": "202002", "orig_upb": 100000.0, "orig_rate": 6.0, "orig_ltv": 80, "orig_term": 360,
        "credit_score": 760, "dti": 30, "mi_percent": 0, "borrowers": 2, "first_time_buyer": 0, "occupancy": "P", "purpose": "P", "property_type": "SF",
        "channel": "R", "state": "NY", "zip3": "100"}


def month(period, upb, age, remaining, code=None, delinquent=0, modified=False, deferred=0.0, rate=6.0, forbearance=False, loss=None, removal=None):
    return {"period": period, "upb": upb, "months_delinquent": delinquent, "reo_acquired": False, "loan_age": age, "remaining_months": remaining,
            "modified": modified, "zero_balance_code": code, "rate": rate, "deferred_upb": deferred, "freddie_ltv": None,
            "in_forbearance": forbearance, "actual_loss": loss, "removal_upb": removal}


def scheduled_history(months, extra=None):
    """The rows of LOAN for this many months, from age 0 (2020-01), paying as scheduled, with extra principal paid in the months given
    ({age: amount})."""
    extra = extra or {}
    rows = [month("202001", 100000.0, 0, 360)]
    balance = 100000.0
    for age in range(1, months + 1):
        balance -= scheduled_principal(balance, 6.0, 360 - age + 1) + extra.get(age, 0.0)
        rows.append(month(add_months("202001", age), round(balance, 2), age, 360 - age))
    return rows


class TestScheduledPayments(unittest.TestCase):

    def test_the_principal_of_a_level_payment(self):
        # 100,000 at 6% for 30 years: a payment of 599.55, of which 500.00 is interest
        self.assertAlmostEqual(scheduled_principal(100000.0, 6.0, 360), 599.5505 - 500.0, places=3)
        self.assertEqual(scheduled_principal(1000.0, 6.0, 1), 1000.0)
        self.assertEqual(scheduled_principal(1200.0, 0.0, 12), 100.0)

    def test_a_loan_that_pays_as_scheduled_prepays_nothing(self):
        rows = loan_months(LOAN, scheduled_history(12), FlatRates(), RisingPrices())
        self.assertEqual(len(rows), 12)                                       # (the row of age 0 has no month before it)
        self.assertEqual([r["loan_age"] for r in rows], list(range(1, 13)))
        for r in rows:
            self.assertAlmostEqual(r["prepaid"], 0.0, places=1)
            self.assertAlmostEqual(r["scheduled_upb"], r["end_upb"], places=1)
        self.assertEqual(rows[0]["start_upb"], 100000.0)
        self.assertEqual(rows[0]["period"], "2020-02-01")


class TestPrepayments(unittest.TestCase):

    def test_a_payoff_prepays_the_whole_scheduled_balance(self):
        rows = scheduled_history(10)
        rows.append(month("202012", 0.0, 10, 350, code="01"))           # (Freddie repeats the age of the month before)
        last = loan_months(LOAN, rows, FlatRates(), RisingPrices())[-1]
        self.assertEqual(last["loan_age"], 11)
        self.assertEqual(last["payoff"], 1)
        self.assertEqual(last["smm"], 1.0)
        self.assertAlmostEqual(last["prepaid"], rows[-2]["upb"] - scheduled_principal(rows[-2]["upb"], 6.0, 350))

    def test_a_curtailment_is_seen_once_the_balances_are_exact(self):
        rows = loan_months(LOAN, scheduled_history(12, extra={9: 1000.0, 5: 1000.0}), FlatRates(), RisingPrices())
        self.assertAlmostEqual(rows[8]["prepaid"], 1000.0, places=1)
        self.assertAlmostEqual(rows[8]["smm"], 1000.0 / rows[8]["scheduled_upb"])
        self.assertEqual(rows[8]["curtailment_seen"], 1)
        self.assertEqual(rows[4]["prepaid"], 0.0)                          # (in the first six months the balances are rounded)
        self.assertEqual(rows[4]["curtailment_seen"], 0)
        self.assertEqual(rows[8]["payoff"], 0)

    def test_catching_up_after_being_delinquent_is_not_a_prepayment(self):
        rows = scheduled_history(12)
        rows[9] = dict(rows[9], upb=rows[8]["upb"], months_delinquent=1)   # (no payment in month 9; months 10 pays two)
        result = loan_months(LOAN, rows, FlatRates(), RisingPrices())
        self.assertEqual(result[9]["prepaid"], 0.0)
        self.assertEqual(result[9]["months_delinquent"], 1)
        self.assertEqual(result[8]["prepaid"], 0.0)                        # (a balance that did not fall is not a negative prepayment)

    def test_a_default_is_not_a_prepayment(self):
        rows = scheduled_history(10)
        rows.append(month("202012", 0.0, 10, 350, code="03"))
        last = loan_months(LOAN, rows, FlatRates(), RisingPrices())[-1]
        self.assertEqual((last["prepaid"], last["payoff"], last["exit_code"]), (0.0, 0, "03"))


def stops_paying(rows, from_age, forbearance=False):
    """The rows, with the loan paying nothing from the month of from_age on: delinquent one more month each month."""
    stuck = rows[from_age - 1]["upb"]
    return rows[:from_age] + [dict(r, upb=stuck, months_delinquent=r["loan_age"] - from_age + 1, in_forbearance=forbearance) for r in rows[from_age:]]


class TestDefaults(unittest.TestCase):

    def test_a_loan_defaults_in_the_month_it_is_six_months_delinquent_and_only_once(self):
        rows = loan_months(LOAN, stops_paying(scheduled_history(20), 10), FlatRates(), RisingPrices())
        by_age = {r["loan_age"]: r for r in rows}
        self.assertEqual([age for age, r in by_age.items() if r["defaulted"]], [15])        # (delinquent 1 month at age 10, 6 at age 15)
        self.assertEqual([age for age, r in by_age.items() if r["after_default"]], list(range(16, 21)))
        self.assertEqual(by_age[15]["ltv_at_default"], by_age[15]["current_ltv"])
        self.assertEqual(by_age[18]["months_since_default"], 3)
        self.assertIsNone(by_age[14]["months_since_default"])

    def test_six_months_delinquent_in_forbearance_is_not_a_default(self):
        rows = loan_months(LOAN, stops_paying(scheduled_history(20), 10, forbearance=True), FlatRates(), RisingPrices())
        self.assertEqual(sum(r["defaulted"] for r in rows), 0)
        self.assertEqual(rows[-1]["in_forbearance"], 1)

    def test_a_short_sale_before_six_months_is_a_default_with_its_loss_and_severity(self):
        rows = stops_paying(scheduled_history(12), 10)
        rows.append(month(add_months("202001", 13), 0.0, 12, 348, code="03", delinquent=3, loss=30000.0, removal=rows[-1]["upb"]))
        last = loan_months(LOAN, rows, FlatRates(), RisingPrices())[-1]
        self.assertEqual((last["defaulted"], last["after_default"], last["months_since_default"]), (1, 0, 0))
        self.assertEqual(last["loss"], 30000.0)
        self.assertAlmostEqual(last["severity"], 30000.0 / rows[-2]["upb"])
        self.assertEqual(last["prepaid"], 0.0)

    def test_an_reo_sale_after_the_default_has_the_months_since_it(self):
        rows = stops_paying(scheduled_history(24), 10)
        rows.append(month(add_months("202001", 25), 0.0, 24, 336, code="09", delinquent=None, loss=-500.0, removal=rows[-1]["upb"]))
        result = loan_months(LOAN, rows, FlatRates(), RisingPrices())
        last = result[-1]
        self.assertEqual((last["defaulted"], last["after_default"], last["months_since_default"]), (0, 1, 10))        # (defaulted at age 15, sold at 25)
        self.assertLess(last["severity"], 0)                                 # (a sale for more than was owed is a gain)
        self.assertEqual(sum(r["defaulted"] for r in result), 1)

    def test_a_loan_paid_off_in_the_month_it_would_have_defaulted_has_not_defaulted(self):
        rows = stops_paying(scheduled_history(14), 10)
        rows.append(month(add_months("202001", 15), 0.0, 14, 346, code="01", delinquent=6))
        self.assertEqual(sum(r["defaulted"] for r in loan_months(LOAN, rows, FlatRates(), RisingPrices())), 0)

    def test_a_payoff_and_a_note_sale_of_a_performing_loan_are_not_defaults(self):
        rows = scheduled_history(10)
        rows.append(month("202012", 0.0, 10, 350, code="16", removal=rows[-1]["upb"]))
        last = loan_months(LOAN, rows, FlatRates(), RisingPrices())[-1]
        self.assertEqual((last["defaulted"], last["loss"], last["severity"]), (0, None, None))
        self.assertEqual(last["removal_upb"], rows[-2]["upb"])


class TestWhatAModelLooksAt(unittest.TestCase):

    def test_the_incentive_is_the_rate_less_the_survey_rate_of_the_month_before(self):
        rows = loan_months(LOAN, scheduled_history(3), FlatRates(lower_months=["202002"]), RisingPrices())
        self.assertEqual([r["incentive"] for r in rows], [1.0, 2.0, 1.0])     # (March is compared with February's survey rate)

    def test_burnout_counts_the_earlier_months_in_the_money_after_the_first_year(self):
        lower = [add_months("202001", age) for age in range(0, 30)]
        rows = loan_months(LOAN, scheduled_history(20), FlatRates(lower_months=lower), RisingPrices())
        burnout = {r["loan_age"]: r["burnout"] for r in rows}
        self.assertEqual(burnout[13], 0)
        self.assertEqual(burnout[14], 1)                                   # (month 13, the first after the first year, came before it)
        self.assertEqual(burnout[20], 7)

    def test_sato_and_the_loan_to_value_now(self):
        rows = loan_months(LOAN, scheduled_history(12), FlatRates(lower_months=["201912"]), RisingPrices())
        self.assertEqual(rows[0]["sato"], 2.0)                             # (6% when the survey, two months before the first payment, was 4%)
        r = rows[11]
        self.assertAlmostEqual(r["current_ltv"], 80 * (r["start_upb"] / 100000.0) / 1.01 ** 12)
        self.assertAlmostEqual(r["home_price_change"], 1.01 ** 12)

    def test_the_sample_bucket_is_the_same_for_every_month_of_a_loan(self):
        rows = loan_months(LOAN, scheduled_history(5), FlatRates(), RisingPrices())
        self.assertEqual({r["sample_bucket"] for r in rows}, {sample_bucket("F20Q10000001")})
        self.assertTrue(0 <= sample_bucket("F20Q10000001") < 100)


if __name__ == "__main__":
    unittest.main()
