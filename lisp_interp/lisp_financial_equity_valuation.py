"""The Valuation tab of a bank or insurer model (lisp_financial_bank.py, lisp_financial_insurer.py): what the shares
are worth, by the excess returns the forecast says the company will earn on what its shareholders own.

A bank's debt and deposits, and an insurer's reserves, are their raw material, not their financing, so a
free-cash-flow DCF (lisp_financial_dcf.py) means nothing for them. What their shareholders own is their tangible
equity -- for a bank, its tangible common equity (equity less preferred stock, minority interests, goodwill and
intangibles); for an insurer, its tangible book value (equity less goodwill and intangibles) -- and what they are paid
for is earning more on it than it costs them:

  equity charge  = the cost of equity times the tangible equity at the start of the period (for the period's share of
                   a year): what the shareholders could earn elsewhere, for the same risk
  excess return  = the shareholders' net income (a bank's after its preferred dividends) less the equity charge
  value          = tangible equity today
                   + the present value of the forecast's excess returns
                   + the present value of the excess returns after the forecast: the return on tangible equity of the
                     last forecast year (yours to change), less the cost of equity, times the tangible equity at the
                     end of the forecast, growing at the terminal growth rate forever, over (the cost of equity less
                     that growth)

A company that earns just its cost of equity is worth its tangible book value; one that earns more is worth more, and
the ratio of the two -- price to tangible book value -- is how banks and insurers are priced. In the long run it is
(return - growth) / (cost of equity - growth), which the tab shows; with the share price (:price) it shows the
return the price implies, the other way round.

This is the dividend discount model in another form: equity grows by net income less what is paid out (the forecast's
balance sheet does just that), so discounting the dividends gives the same value. It does not need the payouts.

The cost of equity is the risk-free rate plus beta times the market's risk premium: placeholders that you replace.
A last table shows the value per share for costs of equity a point or two either side and returns after the forecast
either side: the two numbers the value depends on most.
"""

import lisp_financial_dcf as dcf
import lisp_financial_model as model

INCOME, BALANCE, ASSUMPTIONS, DCF = model.INCOME, model.BALANCE, model.ASSUMPTIONS, model.DCF
column_letter = model.column_letter

TAB_NAME = "Valuation"
TERMINAL_GROWTH = 0.03
COST_STEPS = (-0.02, -0.01, 0.0, 0.01, 0.02)            # the costs of equity of the last table, around the assumed one
RETURN_STEPS = (-0.04, -0.02, 0.0, 0.02, 0.04)          # and its returns after the forecast, around the assumed one


class ExcessReturnValuation(dcf.Valuation):
    """The Valuation tab: its rows, in order, and the cells (laid out as the DCF tab's are). A kind of company says
    which of its lines are the shareholders' income and tangible equity, and what they are called."""

    COMPANY, A_COMPANY = "company", "a company"
    INCOME_KEY, INCOME_NAME = "net-income", "net income"                   # (the Income Statement's line)
    EQUITY_KEY, EQUITY_NAME = "tangible-book-value", "tangible book value"  # (the Balance Sheet's)
    BETA, BETA_NOTE = 1.0, "1 = moves with the market"

    def add_rows(self):
        self.add_inputs()
        self.blank()
        self.add_period_rows()
        self.add_excess_returns()
        self.blank()
        self.add_discounting()
        self.blank()
        self.add_value()
        self.blank()
        self.add_sensitivity()

    def add_inputs(self):
        self.section("inputs-header", "Cost of equity and growth (yellow cells are yours; the risk-free rate, beta, "
                     "risk premium, and growth are placeholders)")
        self.add("risk-free", "Risk-free rate (the 10-year Treasury yield)", self.one(dcf.RISK_FREE_RATE, "percent", "input"))
        self.add("beta", "Equity beta (%s)" % self.BETA_NOTE, self.one(self.BETA, "decimal", "input"))
        self.add("risk-premium", "Equity risk premium (the market's return over the risk-free rate)",
                 self.one(dcf.EQUITY_RISK_PREMIUM, "percent", "input"))
        self.add("cost-of-equity", "Cost of equity (risk-free rate + beta x risk premium)",
                 self.one(lambda: "=%s+%s*%s" % (self.single("risk-free"), self.single("beta"), self.single("risk-premium")),
                          "percent", "input-formula"), ("bold",))
        self.add("terminal-growth", "Growth of %s after the forecast, forever" % self.EQUITY_NAME,
                 self.one(TERMINAL_GROWTH, "percent", "input"))
        if self.price is not None:
            self.add("share-price", "Share price, today", self.one(self.price, "per-share", "input"))
        self.add("growth-check", "Check: cost of equity less terminal growth (must be positive)",
                 self.one(lambda: "=%s-%s" % (self.single("cost-of-equity"), self.single("terminal-growth")), "percent"),
                 ("italic",))

    def add_excess_returns(self):
        inc, bal, a = (lambda key, i: self.other(INCOME, key, i), lambda key, i: self.other(BALANCE, key, i),
                       lambda key, i: self.other(ASSUMPTIONS, key, i))
        self.section("excess-header", "Excess returns: what the shareholders earn above what their equity costs")
        self.add("common-income", self.INCOME_NAME[0].upper() + self.INCOME_NAME[1:],
                 self.every_period(lambda i: "=" + inc(self.INCOME_KEY, i)))
        self.add("tangible-equity", "%s at the end of the period" % (self.EQUITY_NAME[0].upper() + self.EQUITY_NAME[1:]),
                 self.every_period(lambda i: "=" + bal(self.EQUITY_KEY, i)))
        self.add("tangible-return", "Return on %s (a year's, on the average)" % self.EQUITY_NAME,
                 self.every_period(lambda i: '=IFERROR(%s*365/%s/AVERAGE(%s,%s),"")' % (
                     self.at("common-income", i), a("days", i), self.at("tangible-equity", i - 1),
                     self.at("tangible-equity", i)), "percent", 1), ("italic",))
        self.add("equity-charge", "Equity charge: the cost of equity on the %s at the start" % self.EQUITY_NAME,
                 self.forecast_periods(lambda i: "=%s*%s*%s/365" % (self.single("cost-of-equity"),
                                                                    self.at("tangible-equity", i - 1), a("days", i))))
        self.add("excess-return", "Excess return (%s less the equity charge)" % self.INCOME_NAME,
                 self.forecast_periods(lambda i: "=%s-%s" % (self.at("common-income", i), self.at("equity-charge", i)),
                                       "money", "total"), ("total",))

    def add_discounting(self):
        a = lambda key, i: self.other(ASSUMPTIONS, key, i)
        self.section("discount-header", "Present value of the forecast's excess returns (from the end of the last period "
                     "reported, %s)" % self.model.ends[self.history_count - 1].isoformat())
        self.add("last-reported-period", "Period number of the last period reported (row 5 of the other tabs)", self.one(-1, None))
        self.add("last-forecast-period", "Period number of the last forecast period", self.one(self.model.forecast_count - 1, None))

        def years_to_end(i):
            if i == self.first_forecast:
                return "=%s/365" % a("days", i)
            return "=%s+%s/365" % (self.at("years-to-end", i - 1), a("days", i))
        self.add("years-to-end", "Years from the valuation date to the end of the period",
                 self.forecast_periods(years_to_end, "decimal"))
        self.add("discount-factor", "Discount factor, 1 / (1 + cost of equity) to the power of the years",
                 self.forecast_periods(lambda i: "=1/(1+%s)^%s" % (self.single("cost-of-equity"), self.at("years-to-end", i)),
                                       "factor"))
        self.add("present-value", "Present value of the excess return",
                 self.forecast_periods(lambda i: "=%s*%s" % (self.at("excess-return", i), self.at("discount-factor", i))))

    def add_value(self):
        years, first = self.years, self.first_forecast
        equity = self.EQUITY_NAME
        self.section("value-header", "Value of the shares")
        self.add("tangible-equity-now", "%s at the end of the last period reported" % (equity[0].upper() + equity[1:]),
                 self.one(lambda: "=" + self.at_last_reported(BALANCE, self.EQUITY_KEY), "money"))
        self.add("sum-present-values", "Present value of the forecast's excess returns",
                 self.one(lambda: "=SUM(%s)" % self.forecast_range("present-value"), "money"))
        last_year = lambda: "SUM(%s)" % self.last_year("common-income")          # (made when the rows are all known)
        self.add("terminal-return", "Return on %s after the forecast (the last forecast year's, on the equity at its "
                 "start: type the cost of equity to say the advantage fades)" % equity,
                 self.one(lambda: '=IFERROR(%s/%s,0)' % (last_year(), self.before_last_forecast("tangible-equity", years)),
                          "percent", "input-formula"))
        self.add("terminal-excess", "Excess return of the year after the forecast ((return - cost of equity) x the "
                 "%s at the end of the forecast)" % equity,
                 self.one(lambda: "=(%s-%s)*%s" % (self.single("terminal-return"), self.single("cost-of-equity"),
                                                   self.at_last_forecast("tangible-equity")), "money"))
        self.add("terminal-value", "Value of the excess returns after the forecast, at its end (excess return / (cost "
                 "of equity - growth))",
                 self.one(lambda: "=%s/(%s-%s)" % (self.single("terminal-excess"), self.single("cost-of-equity"),
                                                   self.single("terminal-growth")), "money"))
        self.add("present-terminal-value", "Present value of the excess returns after the forecast",
                 self.one(lambda: "=%s*%s" % (self.single("terminal-value"), self.at_last_forecast("discount-factor")),
                          "money"))
        self.add("equity-value", "Value of the shares (%s + the present values)" % equity,
                 self.one(lambda: "=%s+%s+%s" % (self.single("tangible-equity-now"), self.single("sum-present-values"),
                                                 self.single("present-terminal-value")), "money", "total"), ("total",))
        self.add("book-share", "%s, as a share of the value" % (equity[0].upper() + equity[1:]),
                 self.one(lambda: '=IFERROR(%s/%s,"")' % (self.single("tangible-equity-now"), self.single("equity-value")),
                          "percent"), ("italic",))
        self.add("share-count", "Diluted shares, millions (the last period reported)",
                 self.one(lambda: "=" + self.at_last_reported(INCOME, "shares"), "decimal"))
        self.add("value-per-share", "Value per share",
                 self.one(lambda: "=%s/%s" % (self.single("equity-value"), self.single("share-count")), "per-share", "total"),
                 ("total",))
        self.add("tangible-book-per-share", "Tangible book value per share",
                 self.one(lambda: "=%s/%s" % (self.single("tangible-equity-now"), self.single("share-count")), "per-share"))
        self.add("price-to-tangible-book", "Value / tangible book value per share",
                 self.one(lambda: '=IFERROR(%s/%s,"")' % (self.single("value-per-share"),
                                                          self.single("tangible-book-per-share")), "decimal"))
        self.add("justified-multiple", "Price / tangible book of %s earning the return after the forecast forever "
                 "((return - growth) / (cost of equity - growth))" % self.A_COMPANY,
                 self.one(lambda: '=IFERROR((%s-%s)/(%s-%s),"")' % (
                     self.single("terminal-return"), self.single("terminal-growth"), self.single("cost-of-equity"),
                     self.single("terminal-growth")), "decimal"), ("italic",))
        if self.price is not None:
            last_reported_year = lambda: "SUM(%s:%s)" % (self.at("common-income", first - years),
                                                         self.at("common-income", first - 1))
            self.add("market-multiple", "Share price / tangible book value per share",
                     self.one(lambda: '=IFERROR(%s/%s,"")' % (self.single("share-price"),
                                                              self.single("tangible-book-per-share")), "decimal"))
            self.add("implied-return", "Return on %s the share price implies, forever (growth + price / tangible book "
                     "x (cost of equity - growth))" % equity,
                     self.one(lambda: '=IFERROR(%s+%s*(%s-%s),"")' % (
                         self.single("terminal-growth"), self.single("market-multiple"), self.single("cost-of-equity"),
                         self.single("terminal-growth")), "percent"), ("italic",))
            self.add("price-to-earnings", "Share price / the last year's earnings per share (%s)" % self.INCOME_NAME,
                     self.one(lambda: '=IFERROR(%s/(%s/%s),"")' % (self.single("share-price"), last_reported_year(),
                                                                   self.single("share-count")), "decimal"))
            self.add("against-price", "Value compared with the share price",
                     self.one(lambda: "=%s/%s-1" % (self.single("value-per-share"), self.single("share-price")), "percent"),
                     ("italic",))
        self.add_market_range()

    def add_sensitivity(self):
        self.section("sensitivity-header", "How the cost of equity and the return after the forecast change the value")
        for number, step in enumerate(COST_STEPS):
            key = "rate-%d" % number
            self.add(key, "Present value of the excess returns, at the cost of equity in column B",
                     self.sensitivity_row(key, step))
        self.blank()
        self.add("return-axis", "Value per share: cost of equity down, return after the forecast across",
                 self.return_axis(), ("bold",))
        for number in range(len(COST_STEPS)):
            self.add("grid-%d" % number, "", self.grid_row(number))

    def sensitivity_row(self, key, step):
        a = lambda key_, i: self.other(ASSUMPTIONS, key_, i)

        def cells():
            row = {1: self.styled("=%s%s" % (self.single("cost-of-equity"), "%+g" % step if step else ""), "percent")}
            for i in range(self.first_forecast, self.count):
                row[i + 1] = self.styled(self.written_in(i, lambda i: "=(%s-$B%d*%s*%s/365)/(1+$B%d)^%s" % (
                    self.at("common-income", i), self.row_of[key], self.at("tangible-equity", i - 1), a("days", i),
                    self.row_of[key], self.at("years-to-end", i))), "money")
            return row
        return cells

    def return_axis(self):
        def cells():
            return {dcf.SENSITIVITY_FIRST_COLUMN + number: self.styled(
                "=%s%s" % (self.single("terminal-return"), "%+g" % step if step else ""), "percent", "bold")
                for number, step in enumerate(RETURN_STEPS)}
        return cells

    def grid_row(self, number):
        def cells():
            rate_row = self.row_of["rate-%d" % number]
            cost = "$B%d" % rate_row
            row = {1: self.styled("=" + cost, "percent", "bold")}
            present = "SUM(%s:%s)" % (self.at("rate-%d" % number, self.first_forecast), self.at("rate-%d" % number, self.last))
            for column_number in range(len(RETURN_STEPS)):
                column = dcf.SENSITIVITY_FIRST_COLUMN + column_number
                tangible_return = "%s$%d" % (column_letter(column), self.row_of["return-axis"])
                after = "(%s-%s)*%s/(%s-%s)/(1+%s)^%s" % (
                    tangible_return, cost, self.at_last_forecast("tangible-equity"), cost, self.single("terminal-growth"),
                    cost, self.at_last_forecast("years-to-end"))
                row[column] = self.styled("=(%s+%s+%s)/%s" % (self.single("tangible-equity-now"), present, after,
                                                              self.single("share-count")), "per-share")
            return row
        return cells

    def sheet(self):
        sheet = super().sheet()
        sheet["name"] = TAB_NAME
        sheet["cells"][0][0] = ("%s (%s): Valuation by excess returns on %s"
                                % (self.model.company_name, self.model.ticker, self.EQUITY_NAME), ("title",))
        return sheet


class BankValuation(ExcessReturnValuation):
    """A bank's: on its tangible common equity, and its net income to common shareholders (after preferred dividends)."""

    COMPANY, A_COMPANY = "bank", "a bank"
    INCOME_KEY, INCOME_NAME = "income-to-common", "net income to common shareholders"
    EQUITY_KEY, EQUITY_NAME = "tangible-common-equity", "tangible common equity"
    BETA, BETA_NOTE = 1.1, "1 = moves with the market; banks' are mostly 1 to 1.3"
    WHAT_IT_OWNS = ("its tangible common equity (equity less preferred stock, minority interests, goodwill and "
                    "intangibles, on the Balance Sheet) and its net income to common shareholders (net income less "
                    "preferred dividends, on the Income Statement)")
    RAW_MATERIAL = "A bank's debt and deposits are its raw material, not its financing"


class InsurerValuation(ExcessReturnValuation):
    """An insurer's: on its tangible book value, and its net income."""

    COMPANY, A_COMPANY = "insurer", "an insurer"
    INCOME_KEY, INCOME_NAME = "net-income", "net income"
    EQUITY_KEY, EQUITY_NAME = "tangible-book-value", "tangible book value"
    BETA, BETA_NOTE = 0.8, "1 = moves with the market; property and casualty insurers' are mostly 0.6 to 1"
    WHAT_IT_OWNS = ("its tangible book value (equity less goodwill and intangibles, under the Balance Sheet) and its "
                    "net income")
    RAW_MATERIAL = "An insurer's reserves and float are its raw material, not its financing"


def valuation_notes(the_model, kind):
    """The Notes tab's lines about the Valuation tab, for a kind of company (BankValuation or InsurerValuation)."""
    equity, income, company, a_company = kind.EQUITY_NAME, kind.INCOME_NAME, kind.COMPANY, kind.A_COMPANY
    notes = [
        "%s, so it is valued by what its shareholders own and earn: %s." % (kind.RAW_MATERIAL, kind.WHAT_IT_OWNS),
        "The equity charge of a period is the cost of equity times the %s at its start (for the period's share of a year); the excess return is %s less that charge. The value of the shares is today's %s, plus the present value of the forecast's excess returns, plus the present value of those after the forecast, discounted at the cost of equity." % (equity, income, equity),
        "After the forecast the %s earns the return on %s of the last forecast year, on the equity at the end of the forecast, growing at the terminal growth rate: the excess return of the year after, over the cost of equity less the growth. Type the cost of equity over that return to say the advantage fades away (then the value is tangible book value plus the forecast's excess returns)." % (company, equity),
        "Price to tangible book value is how banks and insurers are priced: one earning its cost of equity is worth its tangible book; the tab shows the multiple of %s earning the return after the forecast forever, (return - growth) / (cost of equity - growth)%s." % (
            a_company, ", and the return the share price implies" if the_model.share_price is not None else ""),
        "This is the dividend discount model in another form: equity grows by net income less the payouts (the Balance Sheet's forecast does just that), so discounting dividends would give the same value without needing them.",
        "The risk-free rate, beta, equity risk premium, and terminal growth are placeholders: the SEC's data does not have them. The last table shows the value per share at other costs of equity and returns after the forecast.",
    ]
    if the_model.share_price is None:
        notes.append("The share price was not given (:price), so the value is not compared with it.")
    if the_model.sensitivity:
        notes.append("The Sensitivity tab runs this valuation many times with random values for the inputs you choose (beta, the risk premium, terminal growth, the return after the forecast, and the main assumptions to start with): each Low, Average, High and distribution (explained on the Distributions tab) is yours to change, inputs can be correlated, and the outputs recorded are the Valuation tab's results. It needs the macro on the Sensitivity Macro tab, installed once through Extensions > Apps Script.")
    return notes
