"""A three-statement model of a bank (see lisp_financial_model.py, which this builds on).

A bank is not an ordinary company with different names for things. It does not sell a product: it borrows
money, mostly from depositors, lends it for more, and keeps what it earns on the difference, less what it
loses on loans that are not repaid. So the model's drivers are the balance sheet and the interest rates on it:

  Loans and deposits grow at the rates you assume; cash and securities are percentages of deposits.
  Borrowings are what is needed to fund the rest: total assets less deposits, other liabilities, and equity.
  Interest is a rate times the balance at the END of the period before (so nothing refers to itself):
    on loans, on securities and cash, on deposits, on borrowings. Net interest income is the difference.
    With the federal funds rate (from the New York Fed: build_model's find_fed_funds), each forecast rate is the
    period before's plus its beta times the change in the Fed's rate, which you type for the forecast; a beta is
    how much the rate moved over the biggest move of the Fed's rate in the history, over that move.
  Credit losses: the allowance for credit losses is a percentage of loans; the bank charges off a percentage
    of its loans a year; the provision on the income statement is what charge-offs and the growth of the
    allowance add up to -- the bank "provides" for the losses it expects and for the loans it has lost.
  Noninterest income (fees, trading, ...) grows at an assumed rate, and noninterest expense is an assumed
    percentage of net revenue (net interest income plus noninterest income): the "efficiency ratio".
  Equity is last period's plus net income, less dividends and share repurchases.
  The cash flow statement is the bank's balance sheet seen as flows: net income, less the growth of loans and
    securities, plus the growth of deposits and borrowings, less the payouts. It must end where the balance
    sheet's cash does -- the second check line on the balance sheet, 0 in every forecast period, says so.
  The other assets and liabilities (goodwill and intangibles, trading assets, premises, ...) stay as they were.
  Tangible common equity is equity less preferred stock, minority interests, goodwill and intangibles; net income
    to common shareholders is net income less preferred dividends. The Valuation tab values the common shares by
    the excess returns on tangible common equity (lisp_financial_equity_valuation.py).

So if loans grow faster than deposits, borrowings grow -- and if deposits grow faster than loans, they shrink,
and nothing keeps them from going negative: change the growth rates. The lines under the statements -- the
net interest margin, the efficiency ratio, return on equity and assets, loans to deposits, equity to assets
-- show whether the forecast is one a bank could live with. (The capital ratios that regulators watch use
risk-weighted assets, which the SEC's facts do not give.)

THE SEC'S FACTS for banks vary more than an ordinary company's: banks tag their loans, securities and
borrowings in several ways, and some leave out a total (Wells Fargo's loans since 2022). The model needs
interest income and expense (and their parts on loans and deposits), noninterest income and expense, loans,
deposits, total assets and equity, for every period; without them the company is modeled as an ordinary one.
Securities are available for sale and held to maturity (a bank's trading assets are in 'other assets');
borrowings are repurchase agreements, short-term borrowings and long-term debt.
"""

import lisp_sec
import lisp_financial_equity_valuation as equity_valuation
import lisp_financial_credit as credit
import lisp_financial_model as model

Line, SheetLayout = model.Line, model.SheetLayout
INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS = model.INCOME, model.BALANCE, model.CASH_FLOW, model.ASSUMPTIONS
safe_ratio = model.safe_ratio

BANK_SIC_CODES = (6021, 6022, 6029, 6035, 6036)     # national and state commercial banks, others, savings institutions
BALANCE_GROWTH_LIMITS = (-0.20, 0.30)               # the growth of a balance, in a year
ALLOWANCE_LIMITS = (0.0, 0.10)                      # of loans
SHARE_OF_DEPOSITS_LIMITS = (0.0, 2.0)               # cash, or securities, as a fraction of deposits
CHARGE_OFF_LIMITS = (-0.01, 0.15)                   # of loans, in a year
EFFICIENCY_LIMITS = (0.0, 2.0)                      # noninterest expense, as a fraction of net revenue
BETA_LIMITS = (0.0, 1.0)                            # the share of a change in the Fed's rate that a rate follows
LEAST_RATE_MOVE = 0.01                              # a move of the federal funds rate smaller than this tells nothing
RATE_CYCLE_TOLERANCE = 0.0025                       # (the end of a move: the last period still this near its rate)

# Each rate of the forecast, and its beta: (the rate's assumption, the beta's key, what it is, the beta if the history
# has no move of the Fed's rate to measure it by -- typical figures)
RATE_BETAS = [
    ("loan-yield", "loan-beta", "Loans", 0.50),
    ("securities-yield", "securities-beta", "Securities and cash", 0.60),
    ("deposit-cost", "deposit-beta", "Deposits", 0.35),
    ("borrowing-cost", "borrowing-beta", "Borrowings", 0.90),
]


# ---------------------------------------------------------------------------
# The lines of a bank
# ---------------------------------------------------------------------------

def shared(*keys):
    """The items of an ordinary company's list with these keys."""
    by_key = {item[0]: item for item in lisp_sec.LINE_ITEMS}
    return [by_key[key] for key in keys]


BANK_ITEMS = shared(
    "pretax-income", "income-tax", "net-income", "shares-basic", "shares-diluted",
    "total-assets", "total-liabilities", "stockholders-equity", "equity-including-minority", "liabilities-and-equity",
    "operating-cash-flow", "investing-cash-flow", "financing-cash-flow", "dividends-paid", "share-repurchases",
    "goodwill", "intangible-assets",
) + [
    # The income statement
    ("interest-income", "Interest income", "income",
     ["InterestAndDividendIncomeOperating", "InterestIncomeOperating"], None),
    ("loan-interest", "Interest and fees on loans", "income",
     ["InterestAndFeeIncomeLoansAndLeases", "InterestAndFeeIncomeLoansAndLeasesHeldInPortfolio"], None),
    ("interest-expense", "Interest expense", "income", ["InterestExpenseOperating", "InterestExpense"], None),
    ("deposit-interest", "Interest on deposits", "income", ["InterestExpenseDeposits"], None),
    ("provision", "Provision for credit losses", "income",
     ["ProvisionForLoanLeaseAndOtherLosses", "ProvisionForLoanLossesExpensed", "ProvisionForCreditLosses",
      "ProvisionForLoanAndLeaseLosses", "CreditLossExpenseReversal"], None),
    ("noninterest-income", "Noninterest income", "income", ["NoninterestIncome"], None),
    ("noninterest-expense", "Noninterest expense", "income", ["NoninterestExpense"], None),
    ("charge-offs", "Loans charged off", "income",
     ["FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoff",
      "FinancingReceivableAllowanceForCreditLossesWriteOffs", "AllowanceForLoanAndLeaseLossesWriteOffs"], None),
    ("recoveries", "Recoveries of loans charged off", "income",
     ["FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossRecovery",
      "FinancingReceivableAllowanceForCreditLossesRecovery", "AllowanceForLoanAndLeaseLossesRecoveriesOfBadDebts"], None),
    ("net-charge-offs", "Net charge-offs", "income",
     ["FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery"], None),
    # The balance sheet
    ("cash", "Cash and equivalents", "balance",
     ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalentsAtCarryingValue",
      "CashAndDueFromBanks"], None),
    ("securities-available-for-sale", "Securities available for sale", "balance",
     ["DebtSecuritiesAvailableForSaleExcludingAccruedInterest", "AvailableForSaleSecuritiesDebtSecurities",
      "AvailableForSaleSecurities"], None),
    ("securities-held-to-maturity", "Securities held to maturity", "balance",
     ["DebtSecuritiesHeldToMaturityExcludingAccruedInterestAfterAllowanceForCreditLoss", "HeldToMaturitySecurities"],
     None),
    ("loans", "Loans, before the allowance", "balance",
     ["FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss",
      "LoansAndLeasesReceivableGrossCarryingAmount", "LoansAndLeasesReceivableNetOfDeferredIncome",
      "FinancingReceivableBeforeAllowanceForCreditLosses"], None),
    ("loans-net", "Loans, net of the allowance", "balance",
     ["FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
      "LoansAndLeasesReceivableNetReportedAmount"], None),
    ("allowance", "Allowance for credit losses", "balance",
     ["FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest", "LoansAndLeasesReceivableAllowance",
      "FinancingReceivableAllowanceForCreditLosses"], None),
    ("deposits", "Deposits", "balance", ["Deposits"], None),
    ("repurchase-agreements", "Federal funds purchased and repurchase agreements", "balance",
     ["FederalFundsPurchasedAndSecuritiesSoldUnderAgreementsToRepurchase"], None),
    ("short-term-borrowings", "Short-term borrowings", "balance",
     ["ShortTermBorrowings", "OtherShortTermBorrowings", "CommercialPaper"], None),
    ("long-term-debt", "Long-term debt", "balance",
     ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
      "LongTermDebtAndCapitalLeaseObligations"], None),
    # What is not the common shareholders': preferred stock, minority interests (the equity of the whole company
    # less the parent's), and preferred dividends
    ("parent-equity", "Stockholders' equity, without minority interests", "balance", ["StockholdersEquity"], None),
    ("preferred-stock", "Preferred stock", "balance",
     ["PreferredStockValue", "PreferredStockValueOutstanding", "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount",
      "PreferredStockIncludingAdditionalPaidInCapital"], None),
    ("preferred-dividends", "Preferred dividends", "income",
     ["PreferredStockDividendsIncomeStatementImpact", "DividendsPreferredStock", "DividendsPreferredStockCash"], None),
    ("income-to-common", "Net income available to common shareholders", "income",
     ["NetIncomeLossAvailableToCommonStockholdersBasic"], None),
]

# Lines without which the model means nothing (of the alternatives in a tuple, one is enough)
BANK_REQUIRED = [
    ("interest-income",), ("loan-interest",), ("interest-expense",), ("deposit-interest",),
    ("noninterest-income",), ("noninterest-expense",), ("loans", "loans-net"), ("deposits",),
    ("total-assets",), ("equity-including-minority", "stockholders-equity"),
]


# ---------------------------------------------------------------------------
# The reported numbers, arranged
# ---------------------------------------------------------------------------

class BankHistory:
    """The reported numbers as the bank model's lines, each a list with a number for every period reported;
    the 'other' lines are what is left between the lines shown and the reported totals."""

    def __init__(self, reported, segments=None):
        r = reported
        z = r.zero_filled
        count = len(r.periods)
        self.count = count
        self.segments = []
        # --- income statement
        self.interest_on_loans = z("loan-interest")
        self.interest_income = z("interest-income")
        self.interest_on_securities = [total - loans for total, loans in zip(self.interest_income, self.interest_on_loans)]
        self.interest_on_deposits = z("deposit-interest")
        self.interest_expense = z("interest-expense")
        self.interest_on_borrowings = [total - deposits for total, deposits in
                                       zip(self.interest_expense, self.interest_on_deposits)]
        self.net_interest_income = [a - b for a, b in zip(self.interest_income, self.interest_expense)]
        self.noninterest_income = z("noninterest-income")
        self.noninterest_expense = z("noninterest-expense")
        self.provision = z("provision")
        self.income_tax = z("income-tax")
        self.net_income = z("net-income")
        self.pretax_income = [r.values["pretax-income"][i] if r.values["pretax-income"][i] is not None
                              else self.net_income[i] + self.income_tax[i] for i in range(count)]
        self.other_income = [pretax - (nii - provision + nonii - nonie) for pretax, nii, provision, nonii, nonie in
                             zip(self.pretax_income, self.net_interest_income, self.provision,
                                 self.noninterest_income, self.noninterest_expense)]
        self.other_net_income = [ni - (pre - tax) for ni, pre, tax in zip(self.net_income, self.pretax_income, self.income_tax)]
        self.shares = z("shares-diluted")
        # --- balance sheet
        self.cash = z("cash")
        self.securities = [a + b for a, b in zip(z("securities-available-for-sale"), z("securities-held-to-maturity"))]
        self.allowance = z("allowance")
        self.loans = [r.values["loans"][i] if r.values["loans"][i] is not None else z("loans-net")[i] + self.allowance[i]
                      for i in range(count)]
        self.net_loans = [loans - allowance for loans, allowance in zip(self.loans, self.allowance)]
        self.total_assets = [r.values["total-assets"][i] if r.values["total-assets"][i] is not None
                             else r.values["liabilities-and-equity"][i] for i in range(count)]
        self.goodwill_and_intangibles = [a + b for a, b in zip(z("goodwill"), z("intangible-assets"))]
        self.other_assets = [total - cash - securities - loans - goodwill for total, cash, securities, loans, goodwill in
                             zip(self.total_assets, self.cash, self.securities, self.net_loans,
                                 self.goodwill_and_intangibles)]
        self.deposits = z("deposits")
        self.borrowings = [sum(x) for x in zip(z("repurchase-agreements"), z("short-term-borrowings"),
                                               z("long-term-debt"))]
        self.equity = []
        for i in range(count):
            equity = r.values["equity-including-minority"][i]
            self.equity.append(r.values["stockholders-equity"][i] if equity is None else equity)
        self.other_liabilities = [assets - equity - deposits - borrowings for assets, equity, deposits, borrowings in
                                  zip(self.total_assets, self.equity, self.deposits, self.borrowings)]
        # --- what is not the common shareholders': preferred stock, and minority interests (the equity above less the
        # parent's own, where the company reports both); and the preferred dividends (as reported, or net income less
        # what is left for the common shareholders)
        self.preferred_and_minority = []
        for i in range(count):
            parent = r.values["parent-equity"][i]
            minority = self.equity[i] - parent if parent is not None and self.equity[i] > parent else 0.0
            self.preferred_and_minority.append(z("preferred-stock")[i] + minority)
        self.preferred_dividends = []
        for i in range(count):
            reported_dividends, to_common = r.values["preferred-dividends"][i], r.values["income-to-common"][i]
            if reported_dividends is not None:
                self.preferred_dividends.append(reported_dividends)
            elif to_common is not None and to_common <= self.net_income[i]:
                self.preferred_dividends.append(self.net_income[i] - to_common)
            else:
                self.preferred_dividends.append(0.0)
        self.fed_funds = None          # (the federal funds rate in each period, if the model is given it: set_fed_funds)
        # --- credit losses: net charge-offs as reported, or charge-offs less recoveries, or what the provision
        # and the growth of the allowance say they must have been
        self.net_charge_offs = []
        for i in range(count):
            if r.values["net-charge-offs"][i] is not None:
                self.net_charge_offs.append(r.values["net-charge-offs"][i])
            elif r.values["charge-offs"][i] is not None:
                self.net_charge_offs.append(r.values["charge-offs"][i] - z("recoveries")[i])
            elif i >= 1:
                self.net_charge_offs.append(self.provision[i] - (self.allowance[i] - self.allowance[i - 1]))
            else:
                self.net_charge_offs.append(0.0)
        # --- cash flow statement
        self.dividends = [-x for x in z("dividends-paid")]
        self.repurchases = [-x for x in z("share-repurchases")]
        self.other_operating = [cfo - ni for cfo, ni in zip(z("operating-cash-flow"), self.net_income)]
        self.change_in_loans = [None] + [-(self.net_loans[i] - self.net_loans[i - 1]) for i in range(1, count)]
        self.change_in_securities = [None] + [-(self.securities[i] - self.securities[i - 1]) for i in range(1, count)]
        self.other_investing = [cfi - (a or 0.0) - (b or 0.0) for cfi, a, b in
                                zip(z("investing-cash-flow"), self.change_in_loans, self.change_in_securities)]
        self.change_in_deposits = [None] + [self.deposits[i] - self.deposits[i - 1] for i in range(1, count)]
        self.change_in_borrowings = [None] + [self.borrowings[i] - self.borrowings[i - 1] for i in range(1, count)]
        self.other_financing = [cff - (a or 0.0) - (b or 0.0) - div - rep for cff, a, b, div, rep in
                                zip(z("financing-cash-flow"), self.change_in_deposits, self.change_in_borrowings,
                                    self.dividends, self.repurchases)]


def rate_cycle(fed_funds, first=1):
    """The periods of the history (from `first`, the first with interest rates) between which the federal funds rate
    moved the most -- (start, end), the end moved on to the last period whose rate was still within
    RATE_CYCLE_TOLERANCE of it, since the bank's rates follow the Fed's late -- or None if it never moved
    LEAST_RATE_MOVE."""
    best = None
    for i in range(first, len(fed_funds)):
        for j in range(i + 1, len(fed_funds)):
            if fed_funds[i] is None or fed_funds[j] is None:
                continue
            move = abs(fed_funds[j] - fed_funds[i])
            if best is None or move > best[0]:
                best = (move, i, j)
    if best is None or best[0] < LEAST_RATE_MOVE:
        return None
    _, start, end = best
    extreme = fed_funds[end]
    while end + 1 < len(fed_funds) and fed_funds[end + 1] is not None \
            and abs(fed_funds[end + 1] - extreme) <= RATE_CYCLE_TOLERANCE:
        end += 1
    return start, end


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

class BankModel(model.Model):
    """The model of a bank: the same tabs as an ordinary company's, with a bank's lines."""

    valuation_tab_name = equity_valuation.TAB_NAME    # (not a DCF: see lisp_financial_equity_valuation.py)


    def quality_layout(self):
        return None                        # (the Quality and Risk tab is an ordinary company's)
    def growth_limits(self):
        """Limits for the growth of a balance in one period (a year's, scaled to the period)."""
        return tuple(limit * self.days_in_period / 365 for limit in BALANCE_GROWTH_LIMITS)

    # --- Assumptions

    def assumption_series(self):
        h, n, lag, days = self.h, self.history_count, self.lag, self.days_in_period
        year_fraction = days / 365
        a = self.refs(ASSUMPTIONS, ASSUMPTIONS)
        inc, bal = self.refs(INCOME, ASSUMPTIONS), self.refs(BALANCE, ASSUMPTIONS)

        def sec(numerator, denominator):
            return "=IFERROR(%s/%s,0)" % (numerator, denominator)

        def growth_over_period(key, values):
            """A balance's growth from the period before: its series, and its formula."""
            series = [None if i < 1 or not values[i - 1] else values[i] / values[i - 1] - 1 for i in range(n)]
            return series, lambda i: sec_growth(key, i)

        def sec_growth(key, i):
            return "=IFERROR(%s/%s-1,0)" % (bal(key, i), bal(key, i - 1)) if i >= 1 else None

        def yearly_rate(amounts, balances):
            """A year's rate: an amount over a period, on the balance at the end of the period before."""
            return [None if i < 1 or not balances[i - 1] else amounts[i] / (balances[i - 1] * year_fraction)
                    for i in range(n)]

        def rate_formula(numerator, balance_keys):
            return lambda i: sec(numerator(i), "((%s)*%s/365)" % ("+".join(bal(key, i - 1) for key in balance_keys),
                                                                  a("days", i))) if i >= 1 else None

        earning = [c + s for c, s in zip(h.cash, h.securities)]
        rows = []
        for key, label, balance_key, values in (("loan-growth", "Growth of loans", "loans", h.loans),
                                                ("deposit-growth", "Growth of deposits", "deposits", h.deposits)):
            series, formula = growth_over_period(balance_key, values)
            rows.append((key, label + (" (over the quarter)" if self.period == "quarterly" else " (over the year)"),
                         "percent", series, self.growth_limits(), formula))
        for key, label, balance_key, values in (("cash-to-deposits", "Cash and equivalents, % of deposits", "cash", h.cash),
                                                ("securities-to-deposits", "Securities, % of deposits", "securities",
                                                 h.securities)):
            rows.append((key, label, "percent", [safe_ratio(values[i], h.deposits[i]) for i in range(n)], SHARE_OF_DEPOSITS_LIMITS,
                         lambda i, balance_key=balance_key: sec(bal(balance_key, i), bal("deposits", i))))
        rows.append(("loan-yield", "Interest rate on loans (a year's, on last period's loans)", "percent",
                     yearly_rate(h.interest_on_loans, h.loans), model.INTEREST_RATE_LIMITS,
                     rate_formula(lambda i: inc("interest-loans", i), ["loans"])))
        rows.append(("securities-yield", "Other interest income (securities, deposits at banks, trading), % of last period's cash and securities (a year's)", "percent",
                     yearly_rate(h.interest_on_securities, earning), model.INTEREST_RATE_LIMITS,
                     rate_formula(lambda i: inc("interest-securities", i), ["cash", "securities"])))
        rows.append(("deposit-cost", "Interest rate paid on deposits (a year's, on last period's deposits)", "percent",
                     yearly_rate(h.interest_on_deposits, h.deposits), model.INTEREST_RATE_LIMITS,
                     rate_formula(lambda i: inc("interest-deposits", i), ["deposits"])))
        rows.append(("borrowing-cost", "Interest rate paid on borrowings (a year's, on last period's borrowings)", "percent",
                     yearly_rate(h.interest_on_borrowings, h.borrowings), model.INTEREST_RATE_LIMITS,
                     rate_formula(lambda i: inc("interest-borrowings", i), ["borrowings"])))
        rows.append(("allowance-ratio", "Allowance for credit losses, % of loans", "percent",
                     [safe_ratio(h.allowance[i], h.loans[i]) for i in range(n)], ALLOWANCE_LIMITS,
                     lambda i: sec(bal("allowance", i), bal("loans", i))))
        rows.append(("charge-off-rate", "Net charge-offs (a year's), % of last period's loans", "percent",
                     yearly_rate(h.net_charge_offs, h.loans), CHARGE_OFF_LIMITS,
                     rate_formula(lambda i: inc("net-charge-offs", i), ["loans"])))
        growth = [safe_ratio(h.noninterest_income[i], h.noninterest_income[i - lag]) if i >= lag else None for i in range(n)]
        rows.append(("noninterest-growth", "Growth of noninterest income" +
                     (" (over a year before)" if self.period == "quarterly" else ""), "percent",
                     [None if g is None else g - 1 for g in growth], model.GROWTH_LIMITS,
                     lambda i: "=IFERROR(%s/%s-1,0)" % (inc("noninterest-income", i), inc("noninterest-income", i - lag))
                     if i >= lag else None))
        net_revenue = [nii + nonii for nii, nonii in zip(h.net_interest_income, h.noninterest_income)]
        rows.append(("efficiency", "Noninterest expense, % of net revenue", "percent",
                     [safe_ratio(h.noninterest_expense[i], net_revenue[i]) for i in range(n)], EFFICIENCY_LIMITS,
                     lambda i: sec(inc("noninterest-expense", i), inc("net-revenue", i))))
        rows += self.common_assumption_rows()
        return rows

    def assumptions_layout(self):
        lines = []

        def section(key, label, keys):
            lines.append(Line(key, label, "money", ("section",), None))
            for assumption in keys:
                lines.append(self.main_line_from_series(assumption))
            lines.append(None)

        section("balances-header", "The balance sheet (borrowings are what is needed to fund the rest)",
                ["loan-growth", "deposit-growth", "cash-to-deposits", "securities-to-deposits"])
        if self.h.fed_funds:
            lines.append(Line("rates-header", "Interest rates (each forecast rate is the period before's, plus its beta "
                              "times the change in the federal funds rate: type the rates you expect the Fed to set)",
                              "money", ("section",), None))
            lines.append(self.fed_funds_line())
            for rate_key, beta_key, _, _ in RATE_BETAS:
                lines.append(self.main_line_from_series(rate_key))
                self.follow_fed_funds(lines[-1], beta_key)
            lines.append(None)
            cycle = rate_cycle(self.h.fed_funds)
            lines.append(Line("betas-header", "Betas: the share of a change in the federal funds rate that each rate "
                              "follows" + (" (from %s, the biggest move of the Fed's rate in the history, to %s)"
                                           % (self.labels[cycle[0]], self.labels[cycle[1]]) if cycle else
                                           " (typical figures: the history has no move of the Fed's rate to measure them by)"),
                              "money", ("section",), None))
            for rate_key, beta_key, what, typical in RATE_BETAS:
                lines.append(self.beta_line(rate_key, beta_key, what, typical, cycle))
            lines.append(None)
        else:
            section("rates-header", "Interest rates", ["loan-yield", "securities-yield", "deposit-cost", "borrowing-cost"])
        section("credit-header", "Credit losses" + (" (the forecast's net charge-offs follow the scenario chosen on the "
                                                    "Credit Losses tab)" if self.loan_book else ""),
                ["allowance-ratio", "charge-off-rate"])
        if self.loan_book:
            self.follow_scenario(next(line for line in lines if line is not None and line.key == "charge-off-rate"))
        section("costs-header", "Fees, costs, and taxes", ["noninterest-growth", "efficiency", "tax-rate"])
        section("payout-header", "Shares and payouts", ["share-growth", "dividend-payout", "buyback-payout"])
        lines.pop()
        lines += [None, self.days_line()]
        return SheetLayout(ASSUMPTIONS, "Assumptions", lines)

    def fed_funds_line(self):
        """The federal funds rate: the average of each period reported (from the New York Fed), and in the forecast
        the last one's, held, for you to replace with the rates you expect."""
        fed_funds = self.h.fed_funds
        last = self.history_count - 1

        def cell(i):
            if not self.is_forecast(i):
                return fed_funds[i]
            return "=" + self.ref(ASSUMPTIONS, "fed-funds", i - 1 if i > self.history_count else last, ASSUMPTIONS)
        line = Line("fed-funds", "Federal funds rate (the average over the period; in the forecast, what you expect)",
                    "percent", (), cell)
        line.editable = True
        return line

    def beta_line(self, rate_key, beta_key, what, typical, cycle):
        """A rate's beta: how much it moved over the biggest move of the federal funds rate in the history, over that
        move (within BETA_LIMITS), or a typical figure; then the period before's."""
        a = self.refs(ASSUMPTIONS, ASSUMPTIONS)

        def cell(i):
            if not self.is_forecast(i):
                return None
            if i > self.history_count:
                return "=" + a(beta_key, i - 1)
            if cycle is None:
                return typical
            start, end = cycle
            return "=MIN(MAX(IFERROR((%s-%s)/(%s-%s),%s),%s),%s)" % (
                a(rate_key, end), a(rate_key, start), a("fed-funds", end), a("fed-funds", start), typical,
                BETA_LIMITS[0], BETA_LIMITS[1])
        line = Line(beta_key, "%s: the share of a change in the federal funds rate passed on" % what, "decimal", (), cell)
        line.editable = True
        return line

    def follow_fed_funds(self, line, beta_key):
        """A forecast rate: the period before's, plus its beta times the change in the federal funds rate."""
        history_cell = line.cell
        a = self.refs(ASSUMPTIONS, ASSUMPTIONS)

        def cell(i):
            if not self.is_forecast(i):
                return history_cell(i)
            return "=MAX(%s+%s*(%s-%s),0)" % (a(line.key, i - 1), a(beta_key, i), a("fed-funds", i), a("fed-funds", i - 1))
        line.cell = cell

    def follow_scenario(self, line):
        """The forecast's net charge-off rate: the Credit Losses tab's, for the scenario chosen there."""
        history_cell = line.cell
        line.cell = lambda i: credit.charge_off_formula(self, i) if self.is_forecast(i) else history_cell(i)

    # --- Income statement

    def income_layout(self):
        h, lag = self.h, self.lag
        a = self.refs(ASSUMPTIONS, INCOME)
        inc = self.refs(INCOME, INCOME)
        bal = self.refs(BALANCE, INCOME)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def interest(rate, balances):
            """A forecast amount of interest: the rate, times the balances at the end of the period before."""
            return lambda i: "=%s*(%s)*%s/365" % (a(rate, i), "+".join(bal(key, i - 1) for key in balances), a("days", i))

        def average(tab_ref, key, i):
            """The balance's average over the period (just its end, in the first period)."""
            if i == 0:
                return tab_ref(key, i)
            return "AVERAGE(%s,%s)" % (tab_ref(key, i - 1), tab_ref(key, i))

        def per_year(i):
            return "365/%s" % a("days", i)

        lines = [
            line("interest-loans", "Interest and fees on loans", h.interest_on_loans, interest("loan-yield", ["loans"])),
            line("interest-securities", "Interest on securities and other", h.interest_on_securities,
                 interest("securities-yield", ["cash", "securities"])),
            Line("interest-income", "Total interest income", "money", ("total",),
                 lambda i: "=%s+%s" % (inc("interest-loans", i), inc("interest-securities", i))),
            line("interest-deposits", "Interest on deposits", h.interest_on_deposits, interest("deposit-cost", ["deposits"])),
            line("interest-borrowings", "Interest on borrowings", h.interest_on_borrowings,
                 interest("borrowing-cost", ["borrowings"])),
            Line("interest-expense", "Total interest expense", "money", ("total",),
                 lambda i: "=%s+%s" % (inc("interest-deposits", i), inc("interest-borrowings", i))),
            Line("net-interest-income", "Net interest income", "money", ("total",),
                 lambda i: "=%s-%s" % (inc("interest-income", i), inc("interest-expense", i))),
            None,
            line("noninterest-income", "Noninterest income", h.noninterest_income,
                 lambda i: "=%s*(1+%s)" % (inc("noninterest-income", i - lag), a("noninterest-growth", i))),
            Line("net-revenue", "Net revenue (net interest income plus noninterest income)", "money", ("total",),
                 lambda i: "=%s+%s" % (inc("net-interest-income", i), inc("noninterest-income", i))),
            line("noninterest-expense", "Noninterest expense", h.noninterest_expense,
                 lambda i: "=%s*%s" % (a("efficiency", i), inc("net-revenue", i))),
            Line("pre-provision-profit", "Pre-provision net revenue (profit before credit losses)", "money", ("total",),
                 lambda i: "=%s-%s" % (inc("net-revenue", i), inc("noninterest-expense", i))),
            line("provision", "Provision for credit losses", h.provision,
                 lambda i: "=%s+%s-%s" % (inc("net-charge-offs", i), bal("allowance", i), bal("allowance", i - 1))),
            line("other-income", "Other income (expense)", h.other_income, lambda i: 0.0),
            Line("pretax-income", "Income before taxes", "money", ("total",),
                 lambda i: "=%s-%s+%s" % (inc("pre-provision-profit", i), inc("provision", i), inc("other-income", i))),
            line("income-tax", "Income taxes", h.income_tax, lambda i: "=%s*%s" % (a("tax-rate", i), inc("pretax-income", i))),
            line("other-net-income", "Minority interests, preferred dividends, other", h.other_net_income, lambda i: 0.0),
            Line("net-income", "Net income", "money", ("total",),
                 lambda i: "=%s-%s+%s" % (inc("pretax-income", i), inc("income-tax", i), inc("other-net-income", i))),
            line("preferred-dividends", "Preferred dividends (in the forecast, the period before's)", h.preferred_dividends,
                 lambda i: "=%s" % inc("preferred-dividends", i - 1)),
            Line("income-to-common", "Net income to common shareholders", "money", ("total",),
                 lambda i: "=%s-%s" % (inc("net-income", i), inc("preferred-dividends", i))),
            None,
            line("shares", "Diluted shares, millions", h.shares,
                 lambda i: "=%s*(1+%s)" % (inc("shares", i - 1), a("share-growth", i))),
            Line("eps", "Earnings per share, diluted (net income to common shareholders / shares)", "per-share", (),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("income-to-common", i), inc("shares", i))),
            None,
            Line("ratios-header", "Credit losses and ratios", "money", ("section",), None),
            line("net-charge-offs", "Net charge-offs (loans written off less recoveries)", h.net_charge_offs,
                 lambda i: "=%s*%s*%s/365" % (a("charge-off-rate", i), bal("loans", i - 1), a("days", i)), ("italic",)),
            Line("efficiency-ratio", "Efficiency ratio (noninterest expense / net revenue)", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (inc("noninterest-expense", i), inc("net-revenue", i))),
            Line("net-interest-margin", "Net interest margin (a year's net interest income / average cash, securities, loans)",
                 "percent", ("italic",),
                 lambda i: '=IFERROR(%s*%s/(%s+%s+%s),"")' % (
                     inc("net-interest-income", i), per_year(i), average(bal, "cash", i), average(bal, "securities", i),
                     average(bal, "loans", i))),
            Line("return-on-equity", "Return on equity (a year's net income / average equity)", "percent", ("italic",),
                 lambda i: '=IFERROR(%s*%s/%s,"")' % (inc("net-income", i), per_year(i), average(bal, "equity", i))),
            Line("return-on-assets", "Return on assets (a year's net income / average assets)", "percent", ("italic",),
                 lambda i: '=IFERROR(%s*%s/%s,"")' % (inc("net-income", i), per_year(i), average(bal, "total-assets", i))),
            Line("return-on-tangible-equity", "Return on tangible common equity (a year's net income to common "
                 "shareholders / average tangible common equity)", "percent", ("italic",),
                 lambda i: '=IFERROR(%s*%s/%s,"")' % (inc("income-to-common", i), per_year(i),
                                                      average(bal, "tangible-common-equity", i))),
        ]
        return SheetLayout(INCOME, "Income Statement", lines)

    # --- Balance sheet

    def balance_layout(self):
        h = self.h
        a = self.refs(ASSUMPTIONS, BALANCE)
        bal = self.refs(BALANCE, BALANCE)
        cf = self.refs(CASH_FLOW, BALANCE)
        inc = self.refs(INCOME, BALANCE)

        def line(key, label, history_values, forecast, label_style=()):
            return Line(key, label, "money", label_style,
                        lambda i: history_values[i] if not self.is_forecast(i) else forecast(i))

        def grown(key, assumption):
            return lambda i: "=%s*(1+%s)" % (bal(key, i - 1), a(assumption, i))

        def same_as_before(key):
            return lambda i: "=%s" % bal(key, i - 1)

        lines = [
            line("cash", "Cash and equivalents (including deposits at other banks)", h.cash,
                 lambda i: "=%s*%s" % (a("cash-to-deposits", i), bal("deposits", i))),
            line("securities", "Securities (available for sale and held to maturity)", h.securities,
                 lambda i: "=%s*%s" % (a("securities-to-deposits", i), bal("deposits", i))),
            line("loans", "Loans, before the allowance", h.loans, grown("loans", "loan-growth")),
            line("allowance", "Less: allowance for credit losses", h.allowance,
                 lambda i: "=%s*%s" % (a("allowance-ratio", i), bal("loans", i))),
            Line("net-loans", "Loans, net of the allowance", "money", ("total",),
                 lambda i: "=%s-%s" % (bal("loans", i), bal("allowance", i))),
            line("goodwill-and-intangibles", "Goodwill and intangible assets", h.goodwill_and_intangibles,
                 same_as_before("goodwill-and-intangibles")),
            line("other-assets", "Other assets (trading assets, premises, ...)", h.other_assets,
                 same_as_before("other-assets")),
            Line("total-assets", "Total assets", "money", ("total",),
                 lambda i: "=%s+%s+%s+%s+%s" % (bal("cash", i), bal("securities", i), bal("net-loans", i),
                                                bal("goodwill-and-intangibles", i), bal("other-assets", i))),
            None,
            line("deposits", "Deposits", h.deposits, grown("deposits", "deposit-growth")),
            line("borrowings", "Borrowings (repurchase agreements, short-term borrowings, long-term debt)", h.borrowings,
                 lambda i: "=%s-%s-%s-%s" % (bal("total-assets", i), bal("deposits", i), bal("other-liabilities", i),
                                             bal("equity", i))),
            line("other-liabilities", "Other liabilities", h.other_liabilities, same_as_before("other-liabilities")),
            Line("total-liabilities", "Total liabilities", "money", ("total",),
                 lambda i: "=%s+%s+%s" % (bal("deposits", i), bal("borrowings", i), bal("other-liabilities", i))),
            line("equity", "Stockholders' equity (with minority interests)", h.equity,
                 lambda i: "=%s+%s+%s+%s" % (bal("equity", i - 1), inc("net-income", i), cf("dividends", i),
                                             cf("repurchases", i))),
            Line("total-liabilities-and-equity", "Total liabilities and equity", "money", ("total",),
                 lambda i: "=%s+%s" % (bal("total-liabilities", i), bal("equity", i))),
            None,
            Line("check", "Check: assets less liabilities and equity (should be 0)", "money", ("italic",),
                 lambda i: "=ROUND(%s-%s,3)" % (bal("total-assets", i), bal("total-liabilities-and-equity", i))),
            Line("cash-check", "Check: cash here less cash at the end of the Cash Flow tab (should be 0)", "money", ("italic",),
                 lambda i: "=ROUND(%s-%s,3)" % (bal("cash", i), cf("cash-end", i)) if self.is_forecast(i) else None),
            None,
            Line("tangible-header", "What the common shareholders own (less goodwill and intangibles, which a bank "
                 "in trouble cannot sell)", "money", ("section",), None),
            line("preferred-and-minority", "Preferred stock and minority interests (held as they are)",
                 h.preferred_and_minority, same_as_before("preferred-and-minority")),
            Line("tangible-common-equity", "Tangible common equity (equity less preferred stock, minority interests, "
                 "goodwill and intangibles)", "money", ("total",),
                 lambda i: "=%s-%s-%s" % (bal("equity", i), bal("preferred-and-minority", i),
                                          bal("goodwill-and-intangibles", i))),
            None,
            Line("ratios-header", "Ratios", "money", ("section",), None),
            Line("tangible-equity-to-assets", "Tangible common equity / tangible assets", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/(%s-%s),"")' % (bal("tangible-common-equity", i), bal("total-assets", i),
                                                       bal("goodwill-and-intangibles", i))),
            Line("loans-to-deposits", "Loans / deposits", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (bal("loans", i), bal("deposits", i))),
            Line("borrowings-to-assets", "Borrowings / assets", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (bal("borrowings", i), bal("total-assets", i))),
            Line("equity-to-assets", "Equity / assets", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (bal("equity", i), bal("total-assets", i))),
            Line("allowance-to-loans", "Allowance / loans", "percent", ("italic",),
                 lambda i: '=IFERROR(%s/%s,"")' % (bal("allowance", i), bal("loans", i))),
        ]
        if self.loan_book and credit.has_capital(self.loan_book, self):
            lines.append(self.capital_ratio_line(bal))
        return SheetLayout(BALANCE, "Balance Sheet", lines)

    def capital_ratio_line(self, bal):
        """The common equity tier 1 ratio: the banks' own, from the FDIC, in the periods reported; in the forecast,
        their capital (on the Credit Losses tab) plus the growth of the company's equity since the date of that capital
        (the last period reported, unless the FDIC has no report for it yet), over their risk-weighted assets grown
        with the company's loans."""
        reported = credit.capital_ratios(self)
        last = credit.capital_period(self.loan_book, self)          # (the period the banks' capital is at)

        def cell(i):
            if not self.is_forecast(i):
                return reported[i]
            return ('=IFERROR((common_equity_capital+%s-%s)/(risk_weighted_assets*%s/%s),"")'
                    % (bal("equity", i), bal("equity", last), bal("loans", i), bal("loans", last)))
        return Line("capital-ratio", "Common equity tier 1 ratio (the banks', from the FDIC; estimated in the forecast)",
                    "percent", ("italic",), cell)

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
            """The change in a balance sheet line from the period before, as cash: more loans use it, more deposits supply it."""
            def cell(i):
                if i == 0:
                    return None
                now, before = bal(key, i), bal(key, i - 1)
                return "=%s-%s" % ((before, now) if increase_uses_cash else (now, before))
            return cell

        lines = [
            Line("net-income", "Net income", "money", (), lambda i: "=%s" % inc("net-income", i)),
            line("other-operating", "Other operating activities", h.other_operating, lambda i: 0.0),
            Line("operating-cash-flow", "Cash from operations", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("net-income", i, True), cf("other-operating", i, True))),
            None,
            Line("change-in-loans", "Increase in loans, net of the allowance", "money", (), change("net-loans", True)),
            Line("change-in-securities", "Increase in securities", "money", (), change("securities", True)),
            line("other-investing", "Other investing activities", h.other_investing, lambda i: 0.0),
            Line("investing-cash-flow", "Cash from investing", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("change-in-loans", i, True), cf("other-investing", i, True))),
            None,
            Line("change-in-deposits", "Increase in deposits", "money", (), change("deposits", False)),
            Line("change-in-borrowings", "Increase in borrowings", "money", (), change("borrowings", False)),
            line("dividends", "Dividends paid", h.dividends,
                 lambda i: "=-%s*MAX(%s,0)" % (a("dividend-payout", i), inc("net-income", i))),
            line("repurchases", "Shares repurchased", h.repurchases,
                 lambda i: "=-%s*MAX(%s,0)" % (a("buyback-payout", i), inc("net-income", i))),
            line("other-financing", "Other financing activities", h.other_financing, lambda i: 0.0),
            Line("financing-cash-flow", "Cash from financing", "money", ("total",),
                 lambda i: "=SUM(%s:%s)" % (cf("change-in-deposits", i, True), cf("other-financing", i, True))),
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
            "A bank's drivers are its balance sheet and the interest rates on it. Loans and deposits grow at the rates on the Assumptions tab (over the period: a year, or a quarter). Cash and securities are percentages of deposits.",
            "Borrowings are what funds the rest of the balance sheet: total assets less deposits, other liabilities, and equity. If loans grow faster than deposits they grow; if deposits grow faster they shrink, and nothing keeps them from going negative: change the growth rates.",
            "Interest is a rate times the balance at the end of the period before, so no formula refers to itself: on loans, on securities and cash, on deposits, on borrowings. Net interest income is the difference.",
            "The allowance for credit losses is a percentage of loans. Net charge-offs are a percentage of last period's loans. The provision is the charge-offs plus the growth of the allowance.",
            "Noninterest income grows at the rate assumed (from the same quarter a year before, for quarters). Noninterest expense is the efficiency ratio times net revenue (net interest income plus noninterest income).",
            "Equity is last period's plus net income, less dividends and repurchases. The Cash Flow tab is the balance sheet seen as flows (net income, less the growth of loans and securities, plus the growth of deposits and borrowings, less the payouts), and ends with the cash the balance sheet has: the second check line on the Balance Sheet says so.",
            "Other assets (trading assets, premises, goodwill, and the rest) and other liabilities stay as they were." +
            ("" if self.loan_book else " Regulatory capital ratios need risk-weighted assets, which the SEC's facts do not give (the FDIC's Call Reports do: see :fdic)."),
        ]

    def valuation_sheet(self):
        return equity_valuation.BankValuation(self).sheet()

    def valuation_notes(self):
        if self.has_valuation_tab():
            notes = ["The Valuation tab"] + equity_valuation.valuation_notes(self, equity_valuation.BankValuation)
        else:
            notes = super().valuation_notes()
        if self.loan_book:
            notes += [""] + credit.notes(self)
        return notes

    def sheets(self):
        """The tabs, with the Credit Losses and FDIC Call Reports tabs before the Notes tab if the model has the FDIC's loans."""
        tabs = super().sheets()
        if self.loan_book:
            at = next(n for n, tab in enumerate(tabs) if tab["name"] == model.NOTES)
            tabs[at:at] = credit.credit_tabs(self)
        return tabs


TEMPLATE = model.Template("bank", "a bank", BANK_ITEMS, BankHistory, BankModel, BANK_REQUIRED, BANK_SIC_CODES)
