"""The DCF tab of a three-statement model (see lisp_financial_model.py): what the company is worth, by discounting
the free cash flow the forecast says it will make.

  free cash flow = operating income less the taxes on it (NOPAT), plus depreciation and amortization, less capital
                   expenditures, less the growth of working capital -- what the business throws off, before any
                   payment to those who lent it money or own it. (Stock compensation is not added back: it is a cost
                   to the shareholders.)
  each period's free cash flow is divided by (1 + the discount rate) raised to the years until it arrives
  terminal value = the free cash flow of the year after the forecast, which is the last year's grown at a rate you
                   assume forever, divided by (the discount rate less that rate). (A company whose last forecast year
                   is still one of fast growth spends more on growth than it will at the slower growth after, so the
                   last year's free cash flow understates what is to come: type 1 for the method that instead grows
                   the last year's operating income after taxes and takes off what it takes to grow it, the growth
                   rate times the invested capital.)
  enterprise value = the present values of the free cash flows and of the terminal value added up
  equity value     = enterprise value less the debt, plus the cash, at the end of the last period reported
  value per share  = equity value over the diluted shares

The discount rate is the weighted average cost of capital (WACC): the cost of equity -- the risk-free rate plus the
equity's beta times the market's risk premium -- and the after-tax cost of debt, weighted by how much of the company's
value each is. The cost of debt and the tax rate start from the model's own assumptions; the risk-free rate, beta,
risk premium, and terminal growth are placeholders (the SEC's data has no beta or market rates) that you replace, as you
do the debt weight if you did not give the share price (:price), which makes it the debt over the debt and the market
value of the shares. Every one is yellow, and the WACC itself can be typed over.

A last table shows the value per share for discount rates a point or two either side of the WACC and growth rates
either side of the terminal growth, which is how much to trust the number: terminal value is most of a company's value.

The periods' labels, ends, and numbers are above the first row that has a value in each period (free cash flow), not at the
top, because the rows above are single values.

Every value on the tab has a name (wacc, terminal_growth, enterprise_value), and every row of periods (fcf, discount_factor)
is reached as OFFSET(name,0,the period number), as on the other tabs (the period number row here is not row 5); only the
table at the bottom has addresses.

Above the discounting, the returns on invested capital: ROIC, economic profit (operating income after taxes less the WACC
on the capital), the reinvestment rate, and the incremental margin. With the share price, a reverse DCF below the value:
the terminal growth the price implies, and the growth forever from today's free cash flow it implies. With the options'
implied volatility too, the range the options market expects for the price in a year.

Banks and insurers have no DCF tab: their debt is their raw material, not financing, so free cash flow to the firm
means nothing for them. A bank or an insurer has a Valuation tab in its place (lisp_financial_equity_valuation.py), built the same way.
"""

import lisp_financial_model as model

Line = model.Line
INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS, DCF = model.INCOME, model.BALANCE, model.CASH_FLOW, model.ASSUMPTIONS, model.DCF
column_letter = model.column_letter

# placeholders for the assumptions that the SEC's data cannot supply
RISK_FREE_RATE = 0.045
EQUITY_RISK_PREMIUM = 0.05
BETA = 1.0
TERMINAL_GROWTH = 0.025
DEBT_WEIGHT = 0.20                  # (if the share price is not given)
RATE_STEPS = (-0.02, -0.01, 0.0, 0.01, 0.02)            # the discount rates of the last table, around the WACC
GROWTH_STEPS = (-0.01, -0.005, 0.0, 0.005, 0.01)        # and its terminal growth rates, around the assumed one
FIRST_ROW = 4                                           # (the title, the units, and an empty row come first)
SENSITIVITY_FIRST_COLUMN = 2                            # (the grid's growth rates are in columns C to G)


class Valuation:
    """The DCF tab of a Model: its rows, in order, and the cells."""

    def __init__(self, the_model):
        self.model = the_model
        self.history_count, self.count = the_model.history_count, the_model.count
        self.first_forecast, self.last = the_model.history_count, the_model.count - 1
        self.years = the_model.lag                                  # periods in a year
        self.price = the_model.share_price
        # each row: (key, label, label style, the function that gives its cells), or None for an empty one
        self.rows = []
        self.row_of = {}
        self.add_rows()
        for position, row in enumerate(self.rows):
            if row is not None:
                self.row_of[row[0]] = FIRST_ROW + position
        the_model.period_number_row[DCF] = self.row_of["period-number"]       # (the formulas find the period here, not in row 5)
        self.names = []                                 # (name, address) of each value and row that has a name
        for row in self.rows:
            kind = getattr(row[3], "kind", None) if row is not None else None
            if kind == "single":
                self.names.append((the_model.register_name(DCF, row[0], model.range_name(row[0])), "B%d" % self.row_of[row[0]]))
            elif kind == "periods":
                self.names.append((the_model.register_name(DCF, row[0], model.range_name(row[0])),
                                   self.at(row[0], self.first_forecast)))
        self.own_names = {name for name, _ in self.names}

    # --- addresses

    def name_of(self, key):
        return self.model.range_names[(DCF, key)]

    def single(self, key):
        """A value kept in column B, by its name."""
        return self.name_of(key)

    def at(self, key, i):
        """A row's cell in period i: by the row's name, as in the other tabs, unless it is the row's own in an earlier
        period, or the row has no name (then its address)."""
        own_earlier_period = key == self.model.here_key and i != self.model.here
        if self.model.here is not None and (DCF, key) in self.model.range_names and not own_earlier_period:
            return self.model.named_ref(DCF, key, i, self.model.period_number_row[DCF])
        return "%s%d" % (column_letter(i + 1), self.row_of[key])

    def at_last_forecast(self, key):
        """A row's cell in the last forecast period."""
        return "OFFSET(%s,0,%s)" % (self.name_of(key), self.name_of("last-forecast-period"))

    def before_last_forecast(self, key, periods):
        """A row's cell `periods` before the last forecast period."""
        return "OFFSET(%s,0,%s-%d)" % (self.name_of(key), self.name_of("last-forecast-period"), periods)

    def at_last_reported(self, tab, key):
        """A line of another tab in the last period reported (the date of the valuation)."""
        return "OFFSET(%s,0,%s)" % (self.model.range_names[(tab, key)], self.name_of("last-reported-period"))

    def at_last_forecast_of(self, tab, key):
        return "OFFSET(%s,0,%s)" % (self.model.range_names[(tab, key)], self.name_of("last-forecast-period"))

    def last_year(self, key):
        """The range of a row's cells in the last year of the forecast (the last period, for annual)."""
        first = self.at(key, self.last - self.years + 1)
        return first if self.years == 1 else "%s:%s" % (first, self.at(key, self.last))

    def other(self, tab, key, i):
        """A line of another tab in period i (by its name; in the period of the cell being written)."""
        return self.model.ref(tab, key, i, DCF)

    def forecast_range(self, key):
        return "%s:%s" % (self.at(key, self.first_forecast), self.at(key, self.last))

    # --- the cells of the rows

    def styled(self, value, number_format, *more):
        """(value, styles) for a cell: its format, and the green of a link to another tab."""
        styles = [number_format] if number_format else []
        if model.is_formula(value) and model.is_plain_link(value) and value[1:] not in self.own_names:
            styles.append("link")                                # (a link to another tab, not to a value of this one)
        return (value, tuple(styles) + more)

    def written_in(self, i, formula):
        """The formula for period i, which names the lines of the period it is written in."""
        self.model.here = i
        try:
            return formula(i)
        finally:
            self.model.here = None

    def periods_row(self, formula, number_format, first, more):
        def cells():
            return {i + 1: self.styled(self.written_in(i, formula), number_format, *more) for i in range(first, self.count)}
        cells.kind = "periods"
        return cells

    def every_period(self, formula, number_format="money", start=0, *more):
        """The cells of a row that has a formula in every period from `start`."""
        return self.periods_row(formula, number_format, start, more)

    def forecast_periods(self, formula, number_format="money", *more):
        return self.periods_row(formula, number_format, self.first_forecast, more)

    def one(self, value, number_format, *more):
        """A single value in column B."""
        def cells():
            return {1: self.styled(value() if callable(value) else value, number_format, *more)}
        cells.kind = "single"
        return cells

    def add(self, key, label, cells, label_style=()):
        self.rows.append((key, label, tuple(label_style), cells))

    def blank(self):
        self.rows.append(None)

    def section(self, key, label):
        self.add(key, label, lambda: {i + 1: (None, ("section",)) for i in range(self.count)}, ("section",))

    def add_rows(self):
        self.add_inputs()
        self.blank()
        self.add_period_rows()
        self.add_free_cash_flow()
        self.blank()
        self.add_returns()
        self.blank()
        self.add_discounting()
        self.blank()
        self.add_value()
        self.blank()
        if self.price is not None:
            self.add_price_implies()
            self.blank()
        self.add_sensitivity()

    def add_inputs(self):
        m = self.model
        first = self.first_forecast
        a = lambda key: self.model.range_names[(ASSUMPTIONS, key)]     # (the name is of the first forecast period's cell)
        bal = lambda key: self.at_last_reported(BALANCE, key)
        self.section("inputs-header", "Discount rate and terminal growth (yellow cells are yours; the risk-free rate, beta, risk premium, and growth are placeholders)")
        self.add("risk-free", "Risk-free rate (the 10-year Treasury yield)", self.one(RISK_FREE_RATE, "percent", "input"))
        self.add("beta", "Equity beta (1 = moves with the market)", self.one(BETA, "decimal", "input"))
        self.add("risk-premium", "Equity risk premium (the market's return over the risk-free rate)",
                 self.one(EQUITY_RISK_PREMIUM, "percent", "input"))
        self.add("cost-of-equity", "Cost of equity (risk-free rate + beta x risk premium)",
                 self.one(lambda: "=%s+%s*%s" % (self.single("risk-free"), self.single("beta"), self.single("risk-premium")),
                          "percent"))
        self.add("cost-of-debt", "Cost of debt before taxes (the interest rate assumed for the first forecast period)",
                 self.one(lambda: "=" + a("interest-rate"), "percent", "input-formula"))
        self.add("tax-rate", "Tax rate (assumed for the first forecast period)",
                 self.one(lambda: "=" + a("tax-rate"), "percent", "input-formula"))
        self.add("debt-cost-after-tax", "Cost of debt after taxes",
                 self.one(lambda: "=%s*(1-%s)" % (self.single("cost-of-debt"), self.single("tax-rate")), "percent"))
        if self.price is not None:
            self.add("share-price", "Share price, today", self.one(self.price, "per-share", "input"))
            self.add("market-value", "Market value of the shares (price x diluted shares, millions)",
                     self.one(lambda: "=%s*%s" % (self.single("share-price"), self.at_last_reported(INCOME, "shares")), "money"))
            self.add("debt-weight", "Debt, as a share of debt and the market value of the shares",
                     self.one(lambda: "=(%s+%s)/(%s+%s+%s)" % (bal("current-debt"), bal("long-term-debt"), bal("current-debt"),
                                                                bal("long-term-debt"), self.single("market-value")),
                              "percent", "input-formula"))
        else:
            self.add("debt-weight", "Debt, as a share of debt and the market value of the shares (a guess: give :price)",
                     self.one(DEBT_WEIGHT, "percent", "input"))
        self.add("wacc", "Weighted average cost of capital (WACC)",
                 self.one(lambda: "=(1-%s)*%s+%s*%s" % (self.single("debt-weight"), self.single("cost-of-equity"),
                                                       self.single("debt-weight"), self.single("debt-cost-after-tax")),
                          "percent", "input-formula"), ("bold",))
        self.add("terminal-growth", "Growth of free cash flow after the forecast, forever",
                 self.one(TERMINAL_GROWTH, "percent", "input"))
        self.add("terminal-method", "Free cash flow after the forecast: 0 = the last year's, grown; 1 = after-tax operating income, grown, less growth x invested capital",
                 self.one(0, "decimal", "input"))
        self.add("mid-period", "Cash flows arrive in the middle of each period (1) or at its end (0)",
                 self.one(0, "decimal", "input"))
        self.add("growth-check", "Check: WACC less terminal growth (must be positive)",
                 self.one(lambda: "=%s-%s" % (self.single("wacc"), self.single("terminal-growth")), "percent"), ("italic",))

    def add_period_rows(self):
        """The periods' labels, ends, and numbers, above the rows that have a value in each period (the rows above
        them are single values, for which the periods are in the way)."""
        for key, row in zip(("period", "period-ends", "period-number"), self.model.period_rows()):
            label, label_style = row[0]
            self.add(key, label, lambda row=row: {column: cell for column, cell in enumerate(row) if column > 0}, label_style)

    def add_free_cash_flow(self):
        inc, cf, a = (lambda key, i: self.other(INCOME, key, i), lambda key, i: self.other(CASH_FLOW, key, i),
                      lambda key, i: self.other(ASSUMPTIONS, key, i))
        self.section("fcf-header", "Free cash flow (before payments to lenders and shareholders)")
        self.add("operating-income", "Operating income", self.every_period(lambda i: "=" + inc("operating-income", i)))
        self.add("tax-rate-of-period", "Tax rate", self.every_period(lambda i: "=" + a("tax-rate", i), "percent"))
        self.add("taxes", "Taxes on operating income",
                 self.every_period(lambda i: "=-%s*%s" % (self.at("operating-income", i), self.at("tax-rate-of-period", i))))
        self.add("nopat", "Operating income after taxes (NOPAT)",
                 self.every_period(lambda i: "=%s+%s" % (self.at("operating-income", i), self.at("taxes", i)), "money", 0, "total"),
                 ("total",))
        self.add("depreciation", "Depreciation and amortization",
                 self.every_period(lambda i: "=%s+%s" % (cf("depreciation", i), cf("amortization", i))))
        self.add("capital-expenditures", "Capital expenditures", self.every_period(lambda i: "=" + cf("capital-expenditures", i)))
        self.add("working-capital", "Change in working capital (receivables, inventory, payables)",
                 self.every_period(lambda i: "=%s+%s+%s" % (cf("change-in-receivables", i), cf("change-in-inventory", i),
                                                           cf("change-in-payables", i)), "money", 1))
        self.add("fcf", "Free cash flow",
                 self.every_period(lambda i: "=%s+%s+%s+%s" % (self.at("nopat", i), self.at("depreciation", i),
                                                              self.at("capital-expenditures", i), self.at("working-capital", i)),
                                   "money", 1, "total"), ("total",))

    def add_returns(self):
        """What the company earns on the capital it has put into the business, against what that capital costs: the
        return on invested capital (ROIC) and the economic profit; and how much of its operating income after taxes
        it reinvests, and the growth that buys."""
        bal, inc, a = (lambda key, i: self.other(BALANCE, key, i), lambda key, i: self.other(INCOME, key, i),
                       lambda key, i: self.other(ASSUMPTIONS, key, i))
        lag = self.years
        self.section("returns-header", "Returns on invested capital (what the business earns on the capital put into it)")
        self.add("invested-capital-of-period", "Invested capital at the end of the period (plant, goodwill, intangibles, "
                 "receivables and inventory, less payables)",
                 self.every_period(lambda i: "=%s+%s+%s+%s+%s-%s" % tuple(bal(key, i) for key in (
                     "property-plant-equipment", "goodwill", "intangible-assets", "receivables", "inventory",
                     "accounts-payable"))))
        self.add("roic", "Return on invested capital (a year's operating income after taxes / the invested capital at the start)",
                 self.every_period(lambda i: '=IFERROR(%s*365/%s/%s,"")' % (
                     self.at("nopat", i), a("days", i), self.at("invested-capital-of-period", i - 1)), "percent", 1),
                 ("italic",))
        self.add("economic-profit", "Economic profit (operating income after taxes less the WACC on the invested capital "
                 "at the start): above 0, growth adds value",
                 self.every_period(lambda i: "=%s-%s*%s*%s/365" % (
                     self.at("nopat", i), self.single("wacc"), self.at("invested-capital-of-period", i - 1), a("days", i)),
                     "money", 1))
        self.add("net-investment", "Net investment (the growth of invested capital)",
                 self.every_period(lambda i: "=%s-%s" % (self.at("invested-capital-of-period", i),
                                                         self.at("invested-capital-of-period", i - 1)), "money", 1))
        self.add("reinvestment-rate", "Reinvestment rate (net investment / operating income after taxes)",
                 self.every_period(lambda i: '=IFERROR(%s/%s,"")' % (self.at("net-investment", i), self.at("nopat", i)),
                                   "percent", 1), ("italic",))
        self.add("reinvestment-growth", "Growth that reinvestment buys (ROIC x reinvestment rate, a year's)",
                 self.every_period(lambda i: '=IFERROR(%s*%s,"")' % (self.at("roic", i), self.at("reinvestment-rate", i)),
                                   "percent", 1), ("italic",))
        self.add("incremental-margin", "Incremental margin (growth of operating income / growth of revenue, over a year)",
                 self.every_period(lambda i: '=IFERROR((%s-%s)/(%s-%s),"")' % (
                     inc("operating-income", i), inc("operating-income", i - lag), inc("revenue", i),
                     inc("revenue", i - lag)), "percent", lag), ("italic",))

    def add_discounting(self):
        a = lambda key, i: self.other(ASSUMPTIONS, key, i)
        self.section("discount-header", "Present value of the forecast free cash flow (from the end of the last period reported, %s)"
                     % self.model.ends[self.history_count - 1].isoformat())
        self.add("last-reported-period", "Period number of the last period reported (row 5 of the other tabs)", self.one(-1, None))
        self.add("last-forecast-period", "Period number of the last forecast period", self.one(self.model.forecast_count - 1, None))

        def years_to_end(i):
            if i == self.first_forecast:
                return "=%s/365" % a("days", i)
            return "=%s+%s/365" % (self.at("years-to-end", i - 1), a("days", i))
        self.add("years-to-end", "Years from the valuation date to the end of the period",
                 self.forecast_periods(years_to_end, "decimal"))
        self.add("years-to-cash", "Years to the cash flow (half a period earlier, if the cash flows arrive mid-period)",
                 self.forecast_periods(lambda i: "=%s-%s*%s/365/2" % (self.at("years-to-end", i), self.single("mid-period"),
                                                                      a("days", i)), "decimal"))
        self.add("discount-factor", "Discount factor, 1 / (1 + WACC) to the power of the years",
                 self.forecast_periods(lambda i: "=1/(1+%s)^%s" % (self.single("wacc"), self.at("years-to-cash", i)), "factor"))
        self.add("present-value", "Present value of the free cash flow",
                 self.forecast_periods(lambda i: "=%s*%s" % (self.at("fcf", i), self.at("discount-factor", i))))

    def add_value(self):
        m, first, last = self.model, self.first_forecast, self.last
        bal = lambda key: self.at_last_reported(BALANCE, key)
        self.section("value-header", "Value of the company")
        self.add("sum-present-values", "Present value of the forecast free cash flow",
                 self.one(lambda: "=SUM(%s)" % self.forecast_range("present-value"), "money"))
        self.add("last-year-fcf", "Free cash flow of the last year of the forecast",
                 self.one(lambda: "=SUM(%s)" % self.last_year("fcf"), "money"))
        self.add("last-year-nopat", "Operating income after taxes of the last year of the forecast",
                 self.one(lambda: "=SUM(%s)" % self.last_year("nopat"), "money"))
        self.add("invested-capital", "Invested capital at the end of the forecast (plant, goodwill, intangibles, receivables and inventory, less payables)",
                 self.one(lambda: "=%s+%s+%s+%s+%s-%s" % tuple(self.at_last_forecast_of(BALANCE, key) for key in (
                     "property-plant-equipment", "goodwill", "intangible-assets", "receivables", "inventory", "accounts-payable")),
                          "money"))
        self.add("terminal-fcf", "Free cash flow of the year after the forecast (by the method above)",
                 self.one(lambda: "=" + self.terminal_flow(self.single("terminal-growth")), "money"))
        self.add("terminal-value", "Terminal value, at the end of the forecast (free cash flow / (WACC - growth))",
                 self.one(lambda: "=%s/(%s-%s)" % (self.single("terminal-fcf"), self.single("wacc"),
                                                   self.single("terminal-growth")), "money"))
        self.add("present-terminal-value", "Present value of the terminal value",
                 self.one(lambda: "=%s*%s" % (self.single("terminal-value"), self.at_last_forecast("discount-factor")), "money"))
        self.add("enterprise-value", "Enterprise value",
                 self.one(lambda: "=%s+%s" % (self.single("sum-present-values"), self.single("present-terminal-value")),
                          "money", "total"), ("total",))
        self.add("terminal-share", "Terminal value, as a share of the enterprise value",
                 self.one(lambda: "=%s/%s" % (self.single("present-terminal-value"), self.single("enterprise-value")), "percent"),
                 ("italic",))
        self.add("terminal-multiple", "Terminal value / the last year's operating income plus depreciation and amortization",
                 self.one(lambda: "=%s/(SUM(%s)+SUM(%s))" % (self.single("terminal-value"), self.last_year("operating-income"),
                                                             self.last_year("depreciation")), "decimal"), ("italic",))
        self.add("last-year-roic", "Return on invested capital of the last forecast year (its operating income after "
                 "taxes / the invested capital at its start)",
                 self.one(lambda: '=IFERROR(SUM(%s)/%s,"")' % (self.last_year("nopat"),
                                                             self.before_last_forecast("invested-capital-of-period", self.years)),
                          "percent"), ("italic",))
        self.add("needed-reinvestment", "Reinvestment rate that the terminal growth needs at that return (growth / ROIC; "
                 "compare the last year's, below)",
                 self.one(lambda: '=IFERROR(%s/%s,"")' % (self.single("terminal-growth"), self.single("last-year-roic")),
                          "percent"), ("italic",))
        self.add("last-year-reinvestment", "Reinvestment rate of the last forecast year",
                 self.one(lambda: '=IFERROR(SUM(%s)/SUM(%s),"")' % (self.last_year("net-investment"),
                                                                  self.last_year("nopat")), "percent"), ("italic",))
        self.add("less-debt", "Less: debt at the end of the last period reported",
                 self.one(lambda: "=-(%s+%s)" % (bal("current-debt"), bal("long-term-debt")), "money"))
        self.add("plus-cash", "Plus: cash and short-term investments",
                 self.one(lambda: "=%s+%s" % (bal("cash"), bal("short-term-investments")), "money"))
        self.add("equity-value", "Equity value",
                 self.one(lambda: "=%s+%s+%s" % (self.single("enterprise-value"), self.single("less-debt"),
                                                 self.single("plus-cash")), "money", "total"), ("total",))
        self.add("shares", "Diluted shares, millions (the last period reported)",
                 self.one(lambda: "=" + self.at_last_reported(INCOME, "shares"), "decimal"))
        self.add("value-per-share", "Value per share",
                 self.one(lambda: "=%s/%s" % (self.single("equity-value"), self.single("shares")), "per-share", "total"),
                 ("total",))
        if self.price is not None:
            self.add("against-price", "Value compared with the share price",
                     self.one(lambda: "=%s/%s-1" % (self.single("value-per-share"), self.single("share-price")), "percent"),
                     ("italic",))
        self.add_market_range()

    def add_market_range(self):
        """With the share price and the implied volatility of its options (:price and :volatility), the range the
        options market expects the price to be in a year from now, about two chances in three -- the price times e to
        the minus and the plus the volatility -- and how far outside it the value is, in standard deviations."""
        volatility = getattr(self.model, "share_volatility", None)
        if self.price is None or volatility is None:
            return
        self.add("implied-volatility", "Implied volatility of the options (a year's; :volatility)",
                 self.one(volatility, "percent", "input"))
        self.add("price-low", "Low end of the options market's range for the price in a year (about 2 chances in 3 "
                 "of being inside: price x e^-volatility)",
                 self.one(lambda: "=%s*EXP(-%s)" % (self.single("share-price"), self.single("implied-volatility")),
                          "per-share"))
        self.add("price-high", "High end (price x e^volatility)",
                 self.one(lambda: "=%s*EXP(%s)" % (self.single("share-price"), self.single("implied-volatility")),
                          "per-share"))
        self.add("value-in-deviations", "Value against the price, in the options' standard deviations (beyond 1 or -1, "
                 "outside the range the market expects)",
                 self.one(lambda: '=IFERROR(LN(%s/%s)/%s,"")' % (self.single("value-per-share"), self.single("share-price"),
                                                                self.single("implied-volatility")), "decimal"),
                 ("italic",))

    def add_price_implies(self):
        """A reverse DCF: the growth that the share price implies, worked out backward from it in closed form. The
        enterprise value at the price is the market value of the shares plus the debt less the cash; less the present
        value of the forecast's free cash flow, and moved to the end of the forecast, it is the terminal value the
        price pays for; and the terminal growth that gives that terminal value, by the method chosen, is

            g = (terminal value x WACC - A) / (terminal value + A - method x invested capital)

        where A is the year after's free cash flow before its growth (the last year's free cash flow, or with method 1
        its operating income after taxes). The second is simpler still: the growth forever, from the last reported
        year's free cash flow, that the price implies with no forecast at all, (EV x WACC - FCF) / (EV + FCF)."""
        first, years = self.first_forecast, self.years
        method = lambda: self.single("terminal-method")          # (made when the rows are all known)
        self.section("implied-header", "What the share price implies (a reverse DCF: the growth the price pays for)")
        self.add("price-enterprise-value", "Enterprise value at the share price (market value + debt - cash)",
                 self.one(lambda: "=%s-%s-%s" % (self.single("market-value"), self.single("less-debt"),
                                                 self.single("plus-cash")), "money"))
        self.add("price-terminal-value", "Terminal value the price pays for, at the end of the forecast ((that - the "
                 "present value of the forecast) / the last discount factor)",
                 self.one(lambda: '=IFERROR((%s-%s)/%s,"")' % (self.single("price-enterprise-value"),
                                                               self.single("sum-present-values"),
                                                               self.at_last_forecast("discount-factor")), "money"))
        base = lambda: "((1-%s)*%s+%s*%s)" % (method(), self.single("last-year-fcf"), method(), self.single("last-year-nopat"))
        self.add("implied-terminal-growth", "Growth after the forecast, forever, that the price implies (with this forecast)",
                 self.one(lambda: '=IFERROR((%s*%s-%s)/(%s+%s-%s*%s),"")' % (
                     self.single("price-terminal-value"), self.single("wacc"), base(), self.single("price-terminal-value"),
                     base(), method(), self.single("invested-capital")), "percent"), ("bold",))
        self.add("reported-year-fcf", "Free cash flow of the last reported year",
                 self.one(lambda: "=SUM(%s:%s)" % (self.at("fcf", first - years), self.at("fcf", first - 1)), "money"))
        self.add("implied-steady-growth", "Growth of free cash flow forever, from the last reported year's, that the "
                 "price implies with no forecast at all ((EV x WACC - FCF) / (EV + FCF))",
                 self.one(lambda: '=IFERROR((%s*%s-%s)/(%s+%s),"")' % (
                     self.single("price-enterprise-value"), self.single("wacc"), self.single("reported-year-fcf"),
                     self.single("price-enterprise-value"), self.single("reported-year-fcf")), "percent"), ("bold",))

    def add_sensitivity(self):
        first, last = self.first_forecast, self.last
        self.section("sensitivity-header", "How the discount rate and the terminal growth change the value")
        # the free cash flow discounted at each of the other rates
        for number, step in enumerate(RATE_STEPS):
            key = "rate-%d" % number
            self.add(key, "Present value of the free cash flow, at the discount rate in column B",
                     self.sensitivity_row(key, step))
        self.blank()
        self.add("growth-axis", "Value per share: discount rate down, terminal growth across", self.growth_axis(), ("bold",))
        for number in range(len(RATE_STEPS)):
            self.add("grid-%d" % number, "", self.grid_row(number))

    def sensitivity_row(self, key, step):
        def cells():
            row = {1: self.styled("=%s%s" % (self.single("wacc"), "%+g" % step if step else ""), "percent")}
            for i in range(self.first_forecast, self.count):
                row[i + 1] = self.styled(self.written_in(i, lambda i: "=%s/(1+$B%d)^%s" % (
                    self.at("fcf", i), self.row_of[key], self.at("years-to-cash", i))), "money")
            return row
        return cells

    def growth_axis(self):
        def cells():
            return {SENSITIVITY_FIRST_COLUMN + number: self.styled(
                "=%s%s" % (self.single("terminal-growth"), "%+g" % step if step else ""), "percent", "bold")
                for number, step in enumerate(GROWTH_STEPS)}
        return cells

    def grid_row(self, number):
        def cells():
            rate_row = self.row_of["rate-%d" % number]
            row = {1: self.styled("=$B%d" % rate_row, "percent", "bold")}
            for column_number in range(len(GROWTH_STEPS)):
                column = SENSITIVITY_FIRST_COLUMN + column_number
                growth = "%s$%d" % (column_letter(column), self.row_of["growth-axis"])
                rate = "$B%d" % rate_row
                present = "SUM(%s)" % ("%s:%s" % (self.at("rate-%d" % number, self.first_forecast),
                                                  self.at("rate-%d" % number, self.last)))
                terminal = "%s/(%s-%s)/(1+%s)^%s" % (self.terminal_flow(growth), rate, growth, rate,
                                                     self.at_last_forecast("years-to-cash"))
                row[column] = self.styled("=(%s+%s+%s+%s)/%s" % (present, terminal, self.single("less-debt"),
                                                                  self.single("plus-cash"), self.single("shares")), "per-share")
            return row
        return cells

    def terminal_flow(self, growth):
        """The free cash flow of the year after the forecast, as a formula, if the free cash flow grows at `growth`
        (the address of a cell): the last year's grown, or (method 1) its after-tax operating income grown, less
        the investment to make it grow."""
        method = self.single("terminal-method")
        return "((1-%s)*%s*(1+%s)+%s*(%s*(1+%s)-%s*%s))" % (
            method, self.single("last-year-fcf"), growth, method, self.single("last-year-nopat"), growth, growth,
            self.single("invested-capital"))

    # --- the sheet

    def sheet(self):
        class Title:
            title = "Discounted cash flow valuation"
        width = max(self.count + 1, SENSITIVITY_FIRST_COLUMN + len(GROWTH_STEPS) + 1)
        cells = [list(row) + [None] * (width - len(row)) for row in self.model.title_rows(Title)]
        cells.append([None] * width)
        for row in self.rows:
            line = [None] * width
            if row is not None:
                key, label, label_style, make_cells = row
                line[0] = (label, label_style)
                self.model.here_key = key
                for column, cell in make_cells().items():
                    line[column] = cell
                self.model.here_key = None
            cells.append(line)
        return {"name": DCF, "cells": cells, "frozen_columns": 1,
                "widths": [(0, 0, model.LABEL_WIDTH + 80), (1, width - 1, model.PERIOD_WIDTH)], "names": self.names}


def valuation_sheet(the_model):
    """The DCF tab of a Model, as lisp_google.google_workbook takes it."""
    return Valuation(the_model).sheet()


def valuation_notes(the_model):
    """The Notes tab's lines about the DCF tab."""
    notes = [
        "The DCF tab values the company by discounting the free cash flow of the forecast: operating income less the taxes on it, plus depreciation and amortization, less capital expenditures, less the growth of working capital. Stock compensation is not added back (it is a cost to the shareholders); the interest and the debt are the lenders', so they are not in it.",
        "Each period's free cash flow is divided by one plus the WACC, raised to the years until it arrives, counted from the end of the last period reported. The terminal value is the free cash flow of the year after the forecast (the last year's, grown at the terminal growth rate) over the WACC less that growth, discounted with the last period's factor%s." % (
            ", and for quarters the last four quarters stand for the year" if the_model.lag > 1 else ""),
        "By default the terminal free cash flow is the last forecast year's grown at the terminal growth rate. If that year still has fast growth, its capital expenditures and working capital are too high for slower growth afterward: set the method to 1 and the terminal free cash flow is the last year's operating income after taxes, grown, less the terminal growth rate times the invested capital (plant, goodwill, intangibles, receivables and inventory less payables).",
        "Enterprise value less the debt, plus the cash and short-term investments, at the end of the last period reported is the equity value; over the diluted shares, the value per share. Minority interests, leases, pensions, and the like are not taken off.",
        "The risk-free rate, beta, equity risk premium, and terminal growth are placeholders: the SEC's data does not have them, and the answer depends on them a great deal. The cost of debt and the tax rate start from the Assumptions tab, and the WACC can be typed over.",
    ]
    if the_model.share_price is None:
        notes.append("The share price was not given (:price), so the weight of debt in the WACC is a guess, and the value is not compared with the price.")
    else:
        notes.append("The weight of debt in the WACC is the debt over the debt and the market value of the shares at the price given.")
    if the_model.sensitivity:
        notes.append("The Sensitivity tab runs this valuation many times with random values for the inputs you choose (beta, the risk premium, terminal growth, and the main assumptions to start with): each Low, Average, High and distribution (uniform, triangular, normal, and a dozen more, explained on the Distributions tab) is yours to change, inputs can be correlated, and the outputs recorded are the DCF's results. It needs the macro on the Sensitivity Macro tab, installed once through Extensions > Apps Script.")
    notes.append("The last table shows the value per share at other discount rates and growth rates. The terminal value is usually most of the enterprise value (the row below it says how much): a forecast that ends before the company's growth has slowed will overstate it.")
    return notes
