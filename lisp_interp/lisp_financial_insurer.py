"""A three-statement model of a property and casualty insurer (see lisp_financial_model.py, which this builds on).

An insurer collects premiums now and pays claims later, and invests the money in between (the "float"). It earns
on two things: underwriting (the premiums less the claims and the costs of selling and running the business)
and the return on its investments. So the model's drivers are:

  Premiums earned grow at the rate you assume (from the same quarter a year before, for quarters).
  Losses and loss adjustment expense are the loss ratio times premiums; the other underwriting, acquisition,
    and operating costs are the expense ratio times premiums. Together they are the combined ratio: under
    100% the insurer makes money underwriting.
  Net investment income is a yield times the investments and cash at the END of the period before (so nothing
    refers to itself). Realized gains are an amount you type (0 to begin with; they cannot be forecast).
  Loss reserves (what is owed on claims not yet paid) are an assumed number of years of losses, unearned
    premiums (premiums received for coverage still to come) a percentage of a year's premiums, premiums
    receivable some days of premiums, reinsurance recoverables a percentage of the reserves, deferred
    acquisition costs a percentage of unearned premiums.
  The growth of the reserves and the unearned premiums is cash the insurer holds before it is paid out: the
    cash flow statement starts with net income and adds it. What is left after the payouts (dividends and
    repurchases) and borrowing is invested, in the share you assume (all of it, to begin with), so investments
    grow by it; the rest stays as cash.
  Equity is last period's plus net income, less dividends and repurchases. (Unrealized gains and losses on
    bonds, which move equity when interest rates do, are not forecast.)
  Goodwill, intangibles, the other assets and the other liabilities stay as they were.

THE SEC'S FACTS: the model needs premiums earned, losses incurred, net investment income, revenues,
investments, loss reserves, unearned premiums, total assets, and equity, for every period; without them
the company is modeled as an ordinary one. That happens to Berkshire Hathaway, whose insurance and
railroad, utility, and manufacturing businesses are in one set of statements without these lines, and to
life insurers, whose lines are different. (The model is for property and casualty insurers: Travelers,
Chubb, Progressive.)
"""

import lisp_sec
import lisp_financial_model as model

Line, SheetLayout = model.Line, model.SheetLayout
INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS = model.INCOME, model.BALANCE, model.CASH_FLOW, model.ASSUMPTIONS
safe_ratio = model.safe_ratio

INSURER_SIC_CODES = (6331, 6351)       # fire, marine and casualty insurance; surety insurance
RATIO_LIMITS = (0.0, 2.0)              # losses and expenses, as a fraction of premiums
EXPENSE_LIMITS = (-0.5, 2.0)
YEARS_OF_LOSSES_LIMITS = (0.0, 20.0)


def shared(*keys):
    """The items of an ordinary company's list with these keys."""
    by_key = {item[0]: item for item in lisp_sec.LINE_ITEMS}
    return [by_key[key] for key in keys]


INSURER_ITEMS = shared(
    "revenue", "interest-expense", "pretax-income", "income-tax", "net-income", "shares-basic", "shares-diluted",
    "goodwill", "intangible-assets", "total-assets", "total-liabilities", "stockholders-equity",
    "equity-including-minority", "liabilities-and-equity",
    "operating-cash-flow", "investing-cash-flow", "financing-cash-flow", "dividends-paid", "share-repurchases",
) + [
    ("premiums-earned", "Premiums earned", "income",
     ["PremiumsEarnedNet", "SupplementaryInsuranceInformationPremiumRevenue", "PremiumsEarnedNetPropertyAndCasualty"], None),
    ("net-investment-income", "Net investment income", "income",
     ["NetInvestmentIncome", "InvestmentIncomeNet", "InvestmentIncomeInterestAndDividend"], None),
    ("realized-gains", "Realized investment gains (losses)", "income",
     ["RealizedInvestmentGainsLosses", "GainLossOnInvestments"], None),
    ("losses", "Losses and loss adjustment expense", "income",
     ["PolicyholderBenefitsAndClaimsIncurredNet", "IncurredClaimsPropertyCasualtyAndLiability",
      "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpenseIncurredClaims1",
      "PolicyholderBenefitsAndClaimsIncurredNetOfReinsurance"], None),
    ("cash", "Cash and equivalents", "balance",
     ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalentsAtCarryingValue"], None),
    ("investments", "Investments", "balance", ["Investments"], None),
    ("premiums-receivable", "Premiums receivable", "balance",
     ["PremiumsReceivableAtCarryingValue", "PremiumsAndOtherReceivablesNet", "PremiumsReceivableNet"], None),
    ("reinsurance-recoverable", "Reinsurance recoverables", "balance",
     ["ReinsuranceRecoverables", "ReinsuranceRecoverablesOnPaidAndUnpaidLosses",
      "ReinsuranceRecoverableForUnpaidClaimsAndClaimsAdjustments", "ReinsuranceRecoverableGross"], None),
    ("deferred-acquisition-costs", "Deferred policy acquisition costs", "balance",
     ["DeferredPolicyAcquisitionCosts", "DeferredPolicyAcquisitionCostsNet"], None),
    ("loss-reserves", "Loss and loss adjustment expense reserves", "balance",
     ["LiabilityForClaimsAndClaimsAdjustmentExpense", "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpense"], None),
    ("unearned-premiums", "Unearned premiums", "balance", ["UnearnedPremiums"], None),
    ("debt", "Debt", "balance",
     ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt", "LongTermDebtNoncurrent", "SeniorNotes",
      "DebtInstrumentCarryingAmount"], None),
    ("short-term-debt", "Short-term borrowings", "balance", ["ShortTermBorrowings"], None),
]

INSURER_REQUIRED = [
    ("premiums-earned",), ("losses",), ("net-investment-income",), ("revenue",), ("investments",),
    ("loss-reserves",), ("unearned-premiums",), ("total-assets",), ("equity-including-minority", "stockholders-equity"),
]


class InsurerHistory:
    """The reported numbers as the insurer model's lines, each a list with a number for every period reported;
    the 'other' lines are what is left between the lines shown and the reported totals."""

    def __init__(self, reported, segments=None):
        r = reported
        z = r.zero_filled
        count = len(r.periods)
        self.count = count
        self.segments = []
        # --- income statement
        self.premiums = z("premiums-earned")
        self.investment_income = z("net-investment-income")
        self.gains = z("realized-gains")
        self.revenue = z("revenue")
        self.other_revenue = [rev - p - nii - g for rev, p, nii, g in
                              zip(self.revenue, self.premiums, self.investment_income, self.gains)]
        self.losses = z("losses")
        self.interest_expense = z("interest-expense")
        self.income_tax = z("income-tax")
        self.net_income = z("net-income")
        self.pretax_income = [r.values["pretax-income"][i] if r.values["pretax-income"][i] is not None
                              else self.net_income[i] + self.income_tax[i] for i in range(count)]
        self.other_expenses = [rev - losses - interest - pretax for rev, losses, interest, pretax in
                               zip(self.revenue, self.losses, self.interest_expense, self.pretax_income)]
        self.other_net_income = [ni - (pre - tax) for ni, pre, tax in zip(self.net_income, self.pretax_income, self.income_tax)]
        self.shares = z("shares-diluted")
        # --- balance sheet
        self.cash, self.investments = z("cash"), z("investments")
        self.premiums_receivable, self.reinsurance_recoverable = z("premiums-receivable"), z("reinsurance-recoverable")
        self.deferred_acquisition_costs = z("deferred-acquisition-costs")
        self.goodwill, self.intangible_assets = z("goodwill"), z("intangible-assets")
        self.total_assets = [r.values["total-assets"][i] if r.values["total-assets"][i] is not None
                             else r.values["liabilities-and-equity"][i] for i in range(count)]
        listed = [sum(x) for x in zip(self.cash, self.investments, self.premiums_receivable, self.reinsurance_recoverable,
                                      self.deferred_acquisition_costs, self.goodwill, self.intangible_assets)]
        self.other_assets = [total - amount for total, amount in zip(self.total_assets, listed)]
        self.loss_reserves, self.unearned_premiums = z("loss-reserves"), z("unearned-premiums")
        self.debt = [a + b for a, b in zip(z("debt"), z("short-term-debt"))]
        self.equity = []
        for i in range(count):
            equity = r.values["equity-including-minority"][i]
            self.equity.append(r.values["stockholders-equity"][i] if equity is None else equity)
        self.other_liabilities = [assets - equity - reserves - unearned - debt for assets, equity, reserves, unearned, debt
                                  in zip(self.total_assets, self.equity, self.loss_reserves, self.unearned_premiums, self.debt)]
        # --- cash flow statement
        self.dividends = [-x for x in z("dividends-paid")]
        self.repurchases = [-x for x in z("share-repurchases")]

        def change(values, supplies_cash):
            """The change in a balance sheet line, as cash (None in the first period)."""
            sign = 1 if supplies_cash else -1
            return [None] + [sign * (values[i] - values[i - 1]) for i in range(1, count)]

        self.change_in_reserves = change(self.loss_reserves, True)
        self.change_in_unearned = change(self.unearned_premiums, True)
        self.change_in_receivable = change(self.premiums_receivable, False)
        self.change_in_reinsurance = change(self.reinsurance_recoverable, False)
        self.change_in_acquisition_costs = change(self.deferred_acquisition_costs, False)
        listed_changes = [sum(x or 0.0 for x in group) for group in
                          zip(self.change_in_reserves, self.change_in_unearned, self.change_in_receivable,
                              self.change_in_reinsurance, self.change_in_acquisition_costs)]
        self.other_operating = [cfo - ni - changes for cfo, ni, changes in
                                zip(z("operating-cash-flow"), self.net_income, listed_changes)]
        self.investment_purchases = change(self.investments, False)
        self.other_investing = [cfi - (purchases or 0.0) for cfi, purchases in
                                zip(z("investing-cash-flow"), self.investment_purchases)]
        self.borrowing_and_other_financing = [cff - div - rep for cff, div, rep in
                                              zip(z("financing-cash-flow"), self.dividends, self.repurchases)]


class InsurerModel(model.Model):
    """The model of a property and casualty insurer: the same tabs as an ordinary company's, with an insurer's lines."""

    has_valuation = False                  # (no DCF tab: see lisp_financial_dcf.py)

    # --- Assumptions

    def assumption_series(self):
        h, n, lag, days = self.h, self.history_count, self.lag, self.days_in_period
        year_fraction = days / 365
        a = self.refs(ASSUMPTIONS, ASSUMPTIONS)
        inc, bal = self.refs(INCOME, ASSUMPTIONS), self.refs(BALANCE, ASSUMPTIONS)

        def sec(numerator, denominator):
            return "=IFERROR(%s/%s,0)" % (numerator, denominator)

        def ratio_to_premiums(key, income_line, values, limits, label):
            return (key, label, "percent", [safe_ratio(values[i], h.premiums[i]) for i in range(n)], limits,
                    lambda i: sec(inc(income_line, i), inc("premiums-earned", i)))

        growth = [safe_ratio(h.premiums[i], h.premiums[i - lag]) if i >= lag else None for i in range(n)]
        annual = lambda i: "(%s*365/%s)" % (inc("premiums-earned", i), a("days", i))        # a year's premiums
        annual_losses = lambda i: "(%s*365/%s)" % (inc("losses", i), a("days", i))
        rows = [
            ("premium-growth", "Growth of premiums earned" + (" (over a year before)" if self.period == "quarterly" else ""),
             "percent", [None if g is None else g - 1 for g in growth], model.GROWTH_LIMITS,
             lambda i: "=IFERROR(%s/%s-1,0)" % (inc("premiums-earned", i), inc("premiums-earned", i - lag)) if i >= lag else None),
            ("investment-yield", "Net investment income (a year's), % of last period's investments and cash", "percent",
             [None if i < 1 or not (h.investments[i - 1] + h.cash[i - 1]) else
              h.investment_income[i] / ((h.investments[i - 1] + h.cash[i - 1]) * year_fraction) for i in range(n)],
             model.YIELD_LIMITS,
             lambda i: sec(inc("net-investment-income", i), "((%s+%s)*%s/365)" % (
                 bal("investments", i - 1), bal("cash", i - 1), a("days", i))) if i >= 1 else None),
            ("realized-gains", "Realized investment gains (losses), millions", "money", [None] * n, model.NO_LIMITS,
             lambda i: "=%s" % inc("realized-gains", i)),
            ratio_to_premiums("other-revenue-percent", "other-revenue", h.other_revenue, model.NO_LIMITS, "Other revenue, % of premiums earned"),
            ratio_to_premiums("loss-ratio", "losses", h.losses, RATIO_LIMITS, "Loss ratio: losses and loss adjustment expense, % of premiums earned"),
            ratio_to_premiums("expense-ratio", "other-expenses", h.other_expenses, EXPENSE_LIMITS,
                              "Expense ratio: acquisition, underwriting, and other costs, % of premiums earned"),
            ("interest-rate", "Interest rate on debt (a year's, on last period's debt)", "percent",
             [None if i < 1 or not h.debt[i - 1] else h.interest_expense[i] / (h.debt[i - 1] * year_fraction) for i in range(n)],
             model.INTEREST_RATE_LIMITS,
             lambda i: sec(inc("interest-expense", i), "(%s*%s/365)" % (bal("debt", i - 1), a("days", i))) if i >= 1 else None),
            ("loss-reserve-years", "Loss reserves, in years of losses", "decimal",
             [None if not h.losses[i] else h.loss_reserves[i] / (h.losses[i] / year_fraction) for i in range(n)],
             YEARS_OF_LOSSES_LIMITS, lambda i: sec(bal("loss-reserves", i), annual_losses(i))),
            ("unearned-percent", "Unearned premiums, % of a year's premiums earned", "percent",
             [None if not h.premiums[i] else h.unearned_premiums[i] / (h.premiums[i] / year_fraction) for i in range(n)],
             model.NO_LIMITS, lambda i: sec(bal("unearned-premiums", i), annual(i))),
            ("receivable-days", "Premiums receivable, days of premiums earned", "decimal",
             [None if not h.premiums[i] else h.premiums_receivable[i] / h.premiums[i] * days for i in range(n)],
             model.NO_LIMITS, lambda i: sec("%s*%s" % (bal("premiums-receivable", i), a("days", i)), inc("premiums-earned", i))),
            ("reinsurance-percent", "Reinsurance recoverables, % of loss reserves", "percent",
             [safe_ratio(h.reinsurance_recoverable[i], h.loss_reserves[i]) for i in range(n)], model.NO_LIMITS,
             lambda i: sec(bal("reinsurance-recoverable", i), bal("loss-reserves", i))),
            ("acquisition-cost-percent", "Deferred acquisition costs, % of unearned premiums", "percent",
             [safe_ratio(h.deferred_acquisition_costs[i], h.unearned_premiums[i]) for i in range(n)], model.NO_LIMITS,
             lambda i: sec(bal("deferred-acquisition-costs", i), bal("unearned-premiums", i))),
        ]
        rows += self.common_assumption_rows()
        return rows

    def assumptions_layout(self):
        lines = []

        def section(key, label, keys):
            lines.append(Line(key, label, "money", ("section",), None))
            for assumption in keys:
                lines.append(self.main_line_from_series(assumption))
            lines.append(None)

        section("premiums-header", "Premiums and the income statement",
                ["premium-growth", "loss-ratio", "expense-ratio", "other-revenue-percent", "tax-rate"])
        lines.append(Line("investment-header", "Investments", "money", ("section",), None))
        for assumption in ("investment-yield", "realized-gains"):
            lines.append(self.main_line_from_series(assumption))
        invest_share = Line("invest-share", "Share of cash flow after payouts that is invested", "percent", (),
                            self.held_cells("invest-share", 1.0, lambda i: None))
        invest_share.editable = True
        lines.append(invest_share)
        lines.append(None)
        section("balance-header", "The balance sheet",
                ["loss-reserve-years", "unearned-percent", "receivable-days", "reinsurance-percent",
                 "acquisition-cost-percent"])
        lines.append(Line("financing-header", "Debt, shares, and payouts", "money", ("section",), None))
        for assumption in ("interest-rate", "share-growth", "dividend-payout", "buyback-payout"):
            lines.append(self.main_line_from_series(assumption))
        lines.append(self.net_borrowing_line())
        lines += [None, self.days_line()]
        return SheetLayout(ASSUMPTIONS, "Assumptions", lines)

    def net_borrowing_line(self):
        bal = self.refs(BALANCE, ASSUMPTIONS)
        line = Line("net-borrowing", "Debt borrowed (repaid), millions", "money", (),
                    self.held_cells("net-borrowing", 0.0,
                                    lambda i: None if i == 0 else "=%s-%s" % (bal("debt", i), bal("debt", i - 1))))
        line.editable = True
        return line

    # --- Income statement

    def income_layout(self):
        h, lag = self.h, self.lag
        a = self.refs(ASSUMPTIONS, INCOME)
        inc = self.refs(INCOME, INCOME)
        bal = self.refs(BALANCE, INCOME)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def times_premiums(assumption):
            return lambda i: "=%s*%s" % (a(assumption, i), inc("premiums-earned", i))

        def average(key, i):
            return bal(key, i) if i == 0 else "AVERAGE(%s,%s)" % (bal(key, i - 1), bal(key, i))

        lines = [
            line("premiums-earned", "Premiums earned", h.premiums,
                 lambda i: "=%s*(1+%s)" % (inc("premiums-earned", i - lag), a("premium-growth", i))),
            line("net-investment-income", "Net investment income", h.investment_income,
                 lambda i: "=%s*(%s+%s)*%s/365" % (a("investment-yield", i), bal("investments", i - 1), bal("cash", i - 1),
                                                   a("days", i))),
            line("realized-gains", "Realized investment gains (losses)", h.gains, lambda i: "=%s" % a("realized-gains", i)),
            line("other-revenue", "Other revenue", h.other_revenue, times_premiums("other-revenue-percent")),
            Line("revenue", "Total revenues", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (inc("premiums-earned", i), inc("other-revenue", i))),
            line("losses", "Losses and loss adjustment expense", h.losses, times_premiums("loss-ratio")),
            line("other-expenses", "Policy acquisition, underwriting, and other expenses", h.other_expenses,
                 times_premiums("expense-ratio")),
            line("interest-expense", "Interest expense", h.interest_expense,
                 lambda i: "=%s*%s*%s/365" % (a("interest-rate", i), bal("debt", i - 1), a("days", i))),
            Line("pretax-income", "Income before taxes", "money", ("total",),
                 lambda i: "=%s-%s-%s-%s" % (inc("revenue", i), inc("losses", i), inc("other-expenses", i),
                                             inc("interest-expense", i))),
            line("income-tax", "Income taxes", h.income_tax, lambda i: "=%s*%s" % (a("tax-rate", i), inc("pretax-income", i))),
            line("other-net-income", "Minority interests, preferred dividends, other", h.other_net_income, lambda i: 0.0),
            Line("net-income", "Net income", "money", ("total",),
                 lambda i: "=%s-%s+%s" % (inc("pretax-income", i), inc("income-tax", i), inc("other-net-income", i))),
            None,
            line("shares", "Diluted shares, millions", h.shares,
                 lambda i: "=%s*(1+%s)" % (inc("shares", i - 1), a("share-growth", i))),
            Line("eps", "Earnings per share, diluted", "per-share", (),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("net-income", i), inc("shares", i))),
            None,
            Line("ratios-header", "Underwriting and ratios", "money", ("section",), None),
            Line("underwriting-income", "Underwriting income (premiums less losses and other expenses)", "money", ("italic",),
                 lambda i: "=%s-%s-%s" % (inc("premiums-earned", i), inc("losses", i), inc("other-expenses", i))),
            Line("loss-ratio", "Loss ratio", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("losses", i), inc("premiums-earned", i))),
            Line("expense-ratio", "Expense ratio", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("other-expenses", i), inc("premiums-earned", i))),
            Line("combined-ratio", "Combined ratio (under 100% is an underwriting profit)", "percent", ("italic",),
                 lambda i: '=IFERROR((%s+%s)/%s,"")' % (inc("losses", i), inc("other-expenses", i), inc("premiums-earned", i))),
            Line("return-on-equity", "Return on equity (a year's net income / average equity)", "percent", ("italic",),
                 lambda i: '=IFERROR(%s*365/%s/%s,"")' % (inc("net-income", i), a("days", i), average("equity", i))),
        ]
        return SheetLayout(INCOME, "Income Statement", lines)

    # --- Balance sheet

    def balance_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, BALANCE)
        inc = self.refs(INCOME, BALANCE)
        bal = self.refs(BALANCE, BALANCE)
        cf = self.refs(CASH_FLOW, BALANCE)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def same_as_before(key):
            return lambda i: "=%s" % bal(key, i - 1)

        def years(i):
            return "365/%s" % a("days", i)

        lines = [
            line("cash", "Cash and equivalents", h.cash, lambda i: "=%s" % cf("cash-end", i)),
            line("investments", "Investments", h.investments,
                 lambda i: "=%s-%s" % (bal("investments", i - 1), cf("investment-purchases", i))),
            line("premiums-receivable", "Premiums receivable", h.premiums_receivable,
                 lambda i: "=%s*%s/%s" % (inc("premiums-earned", i), a("receivable-days", i), a("days", i))),
            line("reinsurance-recoverable", "Reinsurance recoverables", h.reinsurance_recoverable,
                 lambda i: "=%s*%s" % (bal("loss-reserves", i), a("reinsurance-percent", i))),
            line("deferred-acquisition-costs", "Deferred policy acquisition costs", h.deferred_acquisition_costs,
                 lambda i: "=%s*%s" % (bal("unearned-premiums", i), a("acquisition-cost-percent", i))),
            line("goodwill", "Goodwill", h.goodwill, same_as_before("goodwill")),
            line("intangible-assets", "Intangible assets", h.intangible_assets, same_as_before("intangible-assets")),
            line("other-assets", "Other assets", h.other_assets, same_as_before("other-assets")),
            Line("total-assets", "Total assets", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (bal("cash", i), bal("other-assets", i))),
            None,
            line("loss-reserves", "Loss and loss adjustment expense reserves", h.loss_reserves,
                 lambda i: "=%s*%s*%s" % (inc("losses", i), years(i), a("loss-reserve-years", i))),
            line("unearned-premiums", "Unearned premiums", h.unearned_premiums,
                 lambda i: "=%s*%s*%s" % (inc("premiums-earned", i), years(i), a("unearned-percent", i))),
            line("debt", "Debt", h.debt, lambda i: "=%s+%s" % (bal("debt", i - 1), cf("borrowing", i))),
            line("other-liabilities", "Other liabilities", h.other_liabilities, same_as_before("other-liabilities")),
            Line("total-liabilities", "Total liabilities", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (bal("loss-reserves", i), bal("other-liabilities", i))),
            line("equity", "Stockholders' equity (with minority interests)", h.equity,
                 lambda i: "=%s+%s+%s+%s" % (bal("equity", i - 1), inc("net-income", i), cf("dividends", i),
                                             cf("repurchases", i))),
            Line("total-liabilities-and-equity", "Total liabilities and equity", "money", ("total",),
                 lambda i: "=%s+%s" % (bal("total-liabilities", i), bal("equity", i))),
            None,
            Line("check", "Check: assets less liabilities and equity (should be 0)", "money", ("italic",),
                 lambda i: "=ROUND(%s-%s,3)" % (bal("total-assets", i), bal("total-liabilities-and-equity", i))),
            None,
            Line("ratios-header", "Ratios", "money", ("section",), None),
            Line("premiums-to-equity", "A year's premiums earned / equity", "decimal", ("italic",),
                 lambda i: '=IFERROR(%s*%s/%s,"")' % (inc("premiums-earned", i), years(i), bal("equity", i))),
            Line("reserves-to-equity", "Loss reserves / equity", "decimal", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (bal("loss-reserves", i), bal("equity", i))),
            Line("investments-to-equity", "Investments and cash / equity", "decimal", ("italic",),
                 lambda i: '=IFERROR((%s+%s)/%s,"")' % (bal("investments", i), bal("cash", i), bal("equity", i))),
        ]
        return SheetLayout(BALANCE, "Balance Sheet", lines)

    # --- Cash flow statement

    def cash_flow_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, CASH_FLOW)
        inc = self.refs(INCOME, CASH_FLOW)
        bal = self.refs(BALANCE, CASH_FLOW)
        cf = self.refs(CASH_FLOW, CASH_FLOW)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def change(key, increase_uses_cash):
            """The change in a balance sheet line from the period before, as cash: an increase in an asset uses it,
            and an increase in a liability supplies it."""
            def cell(i):
                if i == 0:
                    return None
                now, before = bal(key, i), bal(key, i - 1)
                return "=%s-%s" % ((before, now) if increase_uses_cash else (now, before))
            return cell

        def purchases(i):
            """The history: what the investments grew by. The forecast: the share of the cash left after the payouts."""
            if i == 0:
                return None
            if not self.is_forecast(i):
                return "=%s-%s" % (bal("investments", i - 1), bal("investments", i))
            return "=-%s*(%s+%s)" % (a("invest-share", i), cf("operating-cash-flow", i), cf("financing-cash-flow", i))

        lines = [
            Line("net-income", "Net income", "money", (), lambda i: "=%s" % inc("net-income", i)),
            Line("change-in-reserves", "Increase in loss reserves", "money", (), change("loss-reserves", False)),
            Line("change-in-unearned", "Increase in unearned premiums", "money", (), change("unearned-premiums", False)),
            Line("change-in-receivable", "Increase in premiums receivable", "money", (), change("premiums-receivable", True)),
            Line("change-in-reinsurance", "Increase in reinsurance recoverables", "money", (),
                 change("reinsurance-recoverable", True)),
            Line("change-in-acquisition-costs", "Increase in deferred acquisition costs", "money", (),
                 change("deferred-acquisition-costs", True)),
            line("other-operating", "Other operating activities", h.other_operating, lambda i: 0.0),
            Line("operating-cash-flow", "Cash from operations", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("net-income", i), cf("other-operating", i))),
            None,
            Line("investment-purchases", "Net purchases of investments", "money", (), purchases),
            line("other-investing", "Other investing activities", h.other_investing, lambda i: 0.0),
            Line("investing-cash-flow", "Cash from investing", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("investment-purchases", i), cf("other-investing", i))),
            None,
            line("borrowing", "Debt borrowed (repaid) and other financing", h.borrowing_and_other_financing,
                 lambda i: "=%s" % a("net-borrowing", i)),
            line("dividends", "Dividends paid", h.dividends,
                 lambda i: "=-%s*MAX(%s,0)" % (a("dividend-payout", i), inc("net-income", i))),
            line("repurchases", "Shares repurchased", h.repurchases,
                 lambda i: "=-%s*MAX(%s,0)" % (a("buyback-payout", i), inc("net-income", i))),
            Line("financing-cash-flow", "Cash from financing", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("borrowing", i), cf("repurchases", i))),
            None,
            Line("net-change-in-cash", "Net change in cash", "money", ("total",),
                 lambda i: "=%s+%s+%s" % (cf("operating-cash-flow", i), cf("investing-cash-flow", i),
                                          cf("financing-cash-flow", i))),
            Line("cash-begin", "Cash at the start of the period", "money", (),
                 lambda i: "=%s" % bal("cash", i - 1) if self.is_forecast(i) else None),
            Line("cash-end", "Cash at the end of the period", "money", ("total",),
                 lambda i: "=%s+%s" % (cf("cash-begin", i), cf("net-change-in-cash", i)) if self.is_forecast(i) else None),
        ]
        return SheetLayout(CASH_FLOW, "Cash Flow Statement", lines)

    def forecast_notes(self):
        return [
            "An insurer collects premiums now, pays claims later, and invests in between. Premiums earned grow at the rate on the Assumptions tab (from the same quarter a year before, for quarters).",
            "Losses and loss adjustment expense are the loss ratio times premiums earned. The other underwriting, acquisition, and operating costs are the expense ratio times premiums. Together they are the combined ratio.",
            "Net investment income is the yield times last period's investments and cash, so no formula refers to itself. Realized gains cannot be forecast: they are an amount you type, 0 to begin with.",
            "Loss reserves are an assumed number of years of losses; unearned premiums a percentage of a year's premiums; premiums receivable some days of premiums; reinsurance recoverables a percentage of the reserves; deferred acquisition costs a percentage of unearned premiums.",
            "The cash flow statement starts with net income and adds the growth of the reserves and unearned premiums (money held before it is paid out). The share you assume of what is left after dividends, repurchases, and borrowing is invested; the rest stays as cash.",
            "Equity is last period's plus net income, less dividends and repurchases. Unrealized gains and losses on bonds, which move equity when interest rates do, are not forecast. Goodwill, intangibles, and the other assets and liabilities stay as they were.",
            "This is a model of a property and casualty insurer. A life or health insurer's lines (policy benefits, annuities) are different.",
        ]


TEMPLATE = model.Template("insurer", "a property and casualty insurer", INSURER_ITEMS, InsurerHistory, InsurerModel,
                          INSURER_REQUIRED, INSURER_SIC_CODES)
