"""
loan_months.py

The months of one loan, worked out from its rows in Freddie Mac's performance
file (see freddie_files.py) and the market data (see market_data.py): what it
owed at the start of each month, what it would have owed after its scheduled
payment, what it prepaid, and what a prepayment model looks at.

What is prepaid in a month
--------------------------
A month starts with the balance that the last month ended with. The scheduled
payment, at the loan's rate with the months that are left, pays some
principal; what the balance would then be is the SCHEDULED balance. What the
borrower pays beyond that is a prepayment:

  - the whole scheduled balance, if the loan was paid off (zero balance code
    01: "prepaid or matured");
  - the scheduled balance less the balance at the end of the month, if the
    borrower paid part of it early (a "curtailment"). That can only be seen
    when both balances are exact (Freddie rounds the balance to $1,000 in the
    first six months), when the loan was current at the start and at the end of
    the month (a borrower who catches up pays several payments at once, which
    is not a prepayment), and when nothing was modified or deferred;
  - nothing, if the loan ended in some other way (a short sale, a foreclosure,
    a repurchase: those are defaults and the like, not prepayments), or if a
    curtailment cannot be seen.

The single monthly mortality (smm) is what was prepaid over the scheduled
balance: 1 for a loan that was paid off. Over a pool, it is the prepaid
amounts added up over the scheduled balances added up, and the CPR is
1 - (1 - smm)^12.

What a prepayment model looks at
--------------------------------
  incentive      the loan's rate less the average survey rate of the month
                 before (percent): how much a borrower would save by
                 refinancing
  burnout        how many of the loan's earlier months had an incentive above
                 0.75 percent, after the first year: chances to refinance
                 that the borrower did not take
  sato           the loan's rate less the survey rate when it was made (two
                 months before its first payment), percent: a borrower who
                 paid more than the market had, most often, weaker credit
  current_ltv    the loan-to-value now (percent): the balance at the start of
                 the month over the original balance, times the original
                 loan-to-value, over how much home prices have changed in its
                 3-digit zip code since it was made
"""

import hashlib

from market_data import add_months, months_between

BURNOUT_INCENTIVE = 0.75     # percent: a month with an incentive above this is a chance to refinance
BURNOUT_FROM_AGE = 12        # months: chances are counted after the first year


def scheduled_principal(balance, rate, payments_left):
    """The principal that the month's scheduled payment pays, on a level-payment loan of this balance, at this rate (percent a year),
    with this many payments to go, this month's included."""
    if payments_left <= 1:
        return balance
    r = rate / 1200.0
    if r == 0:
        return balance / payments_left
    return balance * r / ((1 + r) ** payments_left - 1)


def sample_bucket(loan_id):
    """A number from 0 to 99 that depends only on the loan's id, so that "sample_bucket < 80" picks the same 80% of loans every time,
    with all of each one's months. (MD5 is used only because it is a well-mixed hash.)"""
    return int(hashlib.md5(loan_id.encode()).hexdigest(), 16) % 100


def as_date(month):
    """'YYYY-MM-01' for the month 'YYYYMM': SQLite has no dates, and the Lisp reads this form as one."""
    return f"{month[:4]}-{month[4:]}-01"


def curtailment_can_be_seen(previous, month):
    """Whether the balance at the end of the month says what the borrower paid early (see the top of the file)."""
    return (previous["loan_age"] >= 7
            and previous["months_delinquent"] == 0 and month["months_delinquent"] == 0
            and not previous["modified"] and not month["modified"]
            and previous["deferred_upb"] == month["deferred_upb"])


def loan_months(loan, months, rates, prices):
    """A dict for each month of the loan after its first row (which is the month before its first payment, when nothing is due), with a
    balance at its start: the columns of the table loan_months (see build_freddie_sample.py). loan is the loan's origination record,
    months its performance records in order, rates a MortgageRates and prices a HomePrices."""
    made = add_months(loan["first_payment"], -1)
    rate_when_made = rates.rate(add_months(loan["first_payment"], -2))
    sato = loan["orig_rate"] - rate_when_made if rate_when_made is not None else None
    loan_facts = {
        "loan_id": loan["loan_id"],
        "sample_bucket": sample_bucket(loan["loan_id"]),
        "first_payment": as_date(loan["first_payment"]),
        "orig_upb": loan["orig_upb"],
        "orig_rate": loan["orig_rate"],
        "orig_ltv": loan["orig_ltv"],
        "orig_term": loan["orig_term"],
        "credit_score": loan["credit_score"],
        "dti": loan["dti"],
        "borrowers": loan["borrowers"],
        "first_time_buyer": loan["first_time_buyer"],
        "occupancy": loan["occupancy"],
        "purpose": loan["purpose"],
        "property_type": loan["property_type"],
        "channel": loan["channel"],
        "state": loan["state"],
        "zip3": loan["zip3"],
        "sato": sato,
    }

    rows = []
    burnout = 0
    for previous, month in zip(months, months[1:]):
        start = previous["upb"]
        if start <= 0:
            continue
        # (Freddie gives the month a loan was paid off the same age as the month before it, so the age is counted from that month.)
        age = previous["loan_age"] + months_between(previous["period"], month["period"])
        scheduled = start - scheduled_principal(start, previous["rate"], previous["remaining_months"])
        code = month["zero_balance_code"]
        if code == "01":
            prepaid = scheduled
        elif code is None and curtailment_can_be_seen(previous, month):
            prepaid = max(scheduled - month["upb"], 0.0)
        else:
            prepaid = 0.0

        survey = rates.rate(add_months(month["period"], -1))
        incentive = month["rate"] - survey if survey is not None else None
        price_change = prices.change(loan["zip3"], made, month["period"])
        current_ltv = (loan["orig_ltv"] * (start / loan["orig_upb"]) / price_change
                       if loan["orig_ltv"] is not None and price_change else None)

        rows.append(dict(loan_facts,
                         period=as_date(month["period"]),
                         calendar_month=int(month["period"][4:]),
                         loan_age=age,
                         rate=month["rate"],
                         months_delinquent=previous["months_delinquent"],
                         exit_code=code,
                         start_upb=start,
                         scheduled_upb=scheduled,
                         end_upb=month["upb"],
                         prepaid=prepaid,
                         smm=prepaid / scheduled if scheduled > 0 else 0.0,
                         payoff=1 if code == "01" else 0,
                         curtailment_seen=1 if code is None and curtailment_can_be_seen(previous, month) else 0,
                         survey_rate=survey,
                         incentive=incentive,
                         burnout=burnout,
                         home_price_change=price_change,
                         current_ltv=current_ltv,
                         freddie_ltv=month["freddie_ltv"]))

        if incentive is not None and age > BURNOUT_FROM_AGE and incentive > BURNOUT_INCENTIVE:
            burnout += 1
    return rows
