"""The Quality and Risk tab of a three-statement model of an ordinary company or an asset manager (see
lisp_financial_model.py): measures of how sound the company's earnings and balance sheet are, worked out by formulas
from the other tabs in every period, reported and forecast, so that a forecast that would make a company riskier shows.

  Debt and interest   EBITDA (operating income plus depreciation and amortization), net debt (debt less cash and
                      short-term investments), net debt over a year's EBITDA, interest coverage (operating income
                      over interest), debt over equity, current assets over current liabilities.
  Quality of earnings free cash flow over net income (a company whose earnings don't turn into cash for years is a
                      worry), the accruals ratio (net income less cash from operations, over average assets), stock
                      compensation over revenue (a real cost that "adjusted" earnings leave out), the growth of the
                      share count, the cash conversion cycle (days of receivables and inventory less days of payables),
                      the incremental margin (the growth of operating income over the growth of revenue), and the
                      compensation ratio, where the company reports its compensation.
  Altman Z'' score    6.56 x working capital / assets + 3.26 x retained earnings / assets + 6.72 x a year's operating
                      income / assets + 1.05 x equity / liabilities: the version of Altman's distress score for any
                      company (the first one was for manufacturers, and needs the market value of the shares). Above
                      2.6 is safe, below 1.1 is distress, between is grey. Retained earnings, in the forecast, are the
                      period before's plus net income less dividends and repurchases (a company that retires the
                      shares it buys back takes them off its retained earnings; one that holds them as treasury stock
                      does not, so for it the forecast's score is a little low).
  Piotroski F-score   nine tests against the same period a year before, 1 for each passed: profitable, cash from
                      operations positive, return on assets up, cash from operations above net income, long-term debt
                      down (as a share of assets), current ratio up, no more shares, gross margin up, revenue over
                      assets up. 8 or 9 is strong, 0 to 2 weak. (Assets are at the end of the period, here.)
"""

import lisp_financial_model as model

Line, SheetLayout = model.Line, model.SheetLayout
INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS, QUALITY = model.INCOME, model.BALANCE, model.CASH_FLOW, model.ASSUMPTIONS, model.QUALITY

# Altman's Z'' (for any company): the weights of its four ratios, and where its zones begin
ALTMAN_WEIGHTS = {"working-capital": 6.56, "retained": 3.26, "operating-income": 6.72, "equity": 1.05}
ALTMAN_SAFE, ALTMAN_DISTRESS = 2.6, 1.1
RATIO_DIGITS = 9                        # (the Piotroski tests compare ratios rounded to this many places)


def quality_layout(the_model):
    """The Quality and Risk tab's lines."""
    m = the_model
    lag = m.lag
    inc, bal, cf, a = (m.refs(INCOME, QUALITY), m.refs(BALANCE, QUALITY), m.refs(CASH_FLOW, QUALITY),
                       m.refs(ASSUMPTIONS, QUALITY))
    q = m.refs(QUALITY, QUALITY)
    reported = m.reported.values

    def year(i):
        """How many of the period make a year (365 / its days), as a formula."""
        return "365/%s" % a("days", i)

    def from_period(first, formula):
        """A line's cells: the formula from period `first` on."""
        return lambda i: formula(i) if i >= first else None

    def line(key, label, number_format, cell, label_style=()):
        return Line(key, label, number_format, label_style, cell)

    def debt(i):
        return "(%s+%s)" % (bal("current-debt", i), bal("long-term-debt", i))

    lines = [
        line("debt-header", "Debt and interest", "money", None, ("section",)),
        line("ebitda", "EBITDA (operating income plus depreciation and amortization)", "money",
             lambda i: "=%s+%s+%s" % (inc("operating-income", i), cf("depreciation", i), cf("amortization", i))),
        line("net-debt", "Net debt (debt less cash and short-term investments)", "money",
             lambda i: "=%s-%s-%s" % (debt(i), bal("cash", i), bal("short-term-investments", i))),
        line("net-debt-to-ebitda", "Net debt / a year's EBITDA (above 3 or 4 is a lot of debt)", "decimal",
             lambda i: '=IFERROR(%s/(%s*%s),"")' % (q("net-debt", i), q("ebitda", i), year(i)), ("italic",)),
        line("interest-coverage", "Interest coverage: operating income / interest (below 2 or 3 is thin)", "decimal",
             lambda i: '=IFERROR(%s/%s,"")' % (inc("operating-income", i), inc("interest-expense", i)), ("italic",)),
        line("debt-to-equity", "Debt / equity", "decimal",
             lambda i: '=IFERROR(%s/%s,"")' % (debt(i), bal("equity", i)), ("italic",)),
        line("current-ratio", "Current assets / current liabilities", "decimal",
             lambda i: '=IFERROR(%s/%s,"")' % (bal("current-assets", i), bal("current-liabilities", i)), ("italic",)),
        None,
        line("earnings-header", "Quality of earnings", "money", None, ("section",)),
        line("cash-conversion", "Free cash flow / net income (well under 100% for years is a warning)", "percent",
             lambda i: '=IFERROR(%s/%s,"")' % (cf("free-cash-flow", i), inc("net-income", i)), ("italic",)),
        line("accruals-ratio", "Accruals: (net income less cash from operations) / average assets (high is a warning)",
             "percent", from_period(1, lambda i: '=IFERROR((%s-%s)/AVERAGE(%s,%s),"")' % (
                 inc("net-income", i), cf("operating-cash-flow", i), bal("total-assets", i - 1), bal("total-assets", i))),
             ("italic",)),
        line("stock-compensation-share", "Stock compensation / revenue (a cost that adjusted earnings leave out)",
             "percent", lambda i: '=IFERROR(%s/%s,"")' % (cf("stock-compensation", i), inc("revenue", i)), ("italic",)),
        line("share-change", "Growth of the share count over a year (dilution, or buybacks if below 0)", "percent",
             from_period(lag, lambda i: '=IFERROR(%s/%s-1,"")' % (inc("shares", i), inc("shares", i - lag))),
             ("italic",)),
        line("cash-conversion-cycle", "Cash conversion cycle, days (receivables and inventory, less payables)",
             "decimal", lambda i: "=%s+%s-%s" % (a("receivable-days", i), a("inventory-days", i), a("payable-days", i)),
             ("italic",)),
        line("incremental-margin", "Incremental margin: growth of operating income / growth of revenue, over a year",
             "percent", from_period(lag, lambda i: '=IFERROR((%s-%s)/(%s-%s),"")' % (
                 inc("operating-income", i), inc("operating-income", i - lag), inc("revenue", i),
                 inc("revenue", i - lag))), ("italic",)),
    ]
    compensation = reported.get("compensation")
    if compensation and any(value is not None for value in compensation):
        lines.append(line("compensation-share", "Compensation / revenue, as reported (the comp ratio of an asset "
                          "manager or a services company)", "percent",
                          lambda i: None if m.is_forecast(i) or compensation[i] is None or not m.h.revenue[i] else
                          compensation[i] / m.h.revenue[i], ("italic",)))
    lines += [None] + altman_lines(m, inc, bal, cf, a, q, year) + [None] + piotroski_lines(m, inc, bal, cf, q)
    return SheetLayout(QUALITY, "Quality and risk", lines)


def altman_lines(m, inc, bal, cf, a, q, year):
    """Altman's Z'' score, and the four ratios it weighs. Without retained earnings in the SEC's facts there is none."""
    retained = m.reported.values.get("retained-earnings")
    if not retained or retained[m.history_count - 1] is None:
        return [Line("altman-header", "Altman Z'' score: none, because the company does not report its retained "
                     "earnings to the SEC", "money", ("section",), None)]

    def retained_cell(i):
        if not m.is_forecast(i):
            return retained[i]
        return "=%s+%s+%s+%s" % (q("retained-earnings", i - 1), inc("net-income", i), cf("dividends", i),
                                 cf("repurchases", i))

    def ratio(numerator, denominator):
        return lambda i: '=IFERROR(%s/%s,"")' % (numerator(i), denominator(i))

    assets = lambda i: bal("total-assets", i)
    weights = ALTMAN_WEIGHTS
    return [
        Line("altman-header", "Altman Z'' score: %g x working capital + %g x retained earnings + %g x a year's operating "
             "income, each over assets, + %g x equity / liabilities (above %g safe, below %g distress)"
             % (weights["working-capital"], weights["retained"], weights["operating-income"], weights["equity"],
                ALTMAN_SAFE, ALTMAN_DISTRESS), "money", ("section",), None),
        Line("retained-earnings", "Retained earnings (in the forecast, the period before's plus net income less dividends "
             "and repurchases)",
             "money", (), retained_cell),
        Line("altman-working-capital", "Working capital / assets", "decimal", ("italic",),
             ratio(lambda i: "(%s-%s)" % (bal("current-assets", i), bal("current-liabilities", i)), assets)),
        Line("altman-retained", "Retained earnings / assets", "decimal", ("italic",),
             ratio(lambda i: q("retained-earnings", i), assets)),
        Line("altman-operating-income", "A year's operating income / assets", "decimal", ("italic",),
             ratio(lambda i: "%s*%s" % (inc("operating-income", i), year(i)), assets)),
        Line("altman-equity", "Equity / liabilities", "decimal", ("italic",),
             ratio(lambda i: bal("equity", i), lambda i: bal("total-liabilities", i))),
        Line("altman-z", "Altman Z'' score", "decimal", ("bold",),
             lambda i: '=IFERROR(%g*%s+%g*%s+%g*%s+%g*%s,"")' % (
                 weights["working-capital"], q("altman-working-capital", i), weights["retained"], q("altman-retained", i),
                 weights["operating-income"], q("altman-operating-income", i), weights["equity"], q("altman-equity", i))),
        Line("altman-zone", "Zone", None, ("italic",),
             lambda i: '=IF(%s="","",IF(%s>%g,"safe",IF(%s<%g,"distress","grey")))' % (
                 q("altman-z", i), q("altman-z", i), ALTMAN_SAFE, q("altman-z", i), ALTMAN_DISTRESS)),
    ]


def piotroski_lines(m, inc, bal, cf, q):
    """Piotroski's F-score: nine tests against the same period a year before, each 1 if passed."""
    lag = m.lag

    def test(key, label, condition):
        """A test's line: 1 if condition(i, i - lag) -- a formula's text -- holds, else 0."""
        return Line(key, label, "decimal", (),
                    lambda i: "=IFERROR(IF(%s,1,0),0)" % condition(i, i - lag) if i >= lag else None)

    def over(numerator, denominator):
        """A ratio, rounded so that two that are the same but for the last digits (a forecast that holds a margin) are
        equal, in Sheets and here alike: a test of "up" is then not passed by rounding."""
        return lambda i: "ROUND(%s/%s,%d)" % (numerator(i), denominator(i), RATIO_DIGITS)

    roa = over(lambda i: inc("net-income", i), lambda i: bal("total-assets", i))
    leverage = over(lambda i: bal("long-term-debt", i), lambda i: bal("total-assets", i))
    liquidity = over(lambda i: bal("current-assets", i), lambda i: bal("current-liabilities", i))
    margin = over(lambda i: inc("gross-profit", i), lambda i: inc("revenue", i))
    turnover = over(lambda i: inc("revenue", i), lambda i: bal("total-assets", i))
    tests = [
        test("f-profitable", "Net income above 0", lambda i, before: "%s>0" % inc("net-income", i)),
        test("f-cash", "Cash from operations above 0", lambda i, before: "%s>0" % cf("operating-cash-flow", i)),
        test("f-return", "Return on assets (net income / assets) up", lambda i, before: "%s>%s" % (roa(i), roa(before))),
        test("f-accruals", "Cash from operations above net income",
             lambda i, before: "%s>%s" % (cf("operating-cash-flow", i), inc("net-income", i))),
        test("f-leverage", "Long-term debt / assets down (or the same)",
             lambda i, before: "%s<=%s" % (leverage(i), leverage(before))),
        test("f-liquidity", "Current assets / current liabilities up",
             lambda i, before: "%s>%s" % (liquidity(i), liquidity(before))),
        test("f-shares", "No more shares", lambda i, before: "%s<=%s" % (inc("shares", i), inc("shares", before))),
        test("f-margin", "Gross margin up", lambda i, before: "%s>%s" % (margin(i), margin(before))),
        test("f-turnover", "Revenue / assets up", lambda i, before: "%s>%s" % (turnover(i), turnover(before))),
    ]
    first_test, last_test = tests[0].key, tests[-1].key
    score = Line("f-score", "Piotroski F-score (8 or 9 strong, 0 to 2 weak)", "decimal", ("bold",),
                 lambda i: "=SUM(%s:%s)" % (q(first_test, i, True), q(last_test, i, True)) if i >= lag else None)
    header = Line("piotroski-header", "Piotroski F-score: nine tests against the same period a year before (1 for each "
                  "passed)", "money", ("section",), None)
    return [header] + tests + [score]


def notes(the_model):
    """The Notes tab's lines on the Quality and Risk tab."""
    return [
        "The Quality and Risk tab",
        "Measures of how sound the company's earnings and balance sheet are, as formulas of the other tabs in every period, the forecast's too: a forecast that adds debt or lets receivables grow shows here.",
        "Debt and interest: EBITDA (operating income plus depreciation and amortization), net debt (debt less cash and short-term investments) over a year's EBITDA, interest coverage (operating income over interest), debt over equity, and the current ratio.",
        "Quality of earnings: free cash flow over net income; accruals, net income less cash from operations over average assets (earnings that are not cash are the ones most often reversed); stock compensation over revenue; the growth of the share count over a year; the cash conversion cycle; and the incremental margin, how much of a year's added revenue became operating income.",
        "The Altman Z'' score is the version of Altman's distress score for any company: %g x working capital / assets + %g x retained earnings / assets + %g x a year's operating income / assets + %g x equity / liabilities. Above %g is safe, below %g is distress. In the forecast, retained earnings are the period before's plus net income less dividends and repurchases (as a company that retires the shares it buys back records them; one that keeps them as treasury stock does not, so its forecast score is a little low)." % (
            ALTMAN_WEIGHTS["working-capital"], ALTMAN_WEIGHTS["retained"], ALTMAN_WEIGHTS["operating-income"],
            ALTMAN_WEIGHTS["equity"], ALTMAN_SAFE, ALTMAN_DISTRESS),
        "The Piotroski F-score is nine tests against the same period a year before, 1 for each passed: profitable, cash from operations above 0, return on assets up, cash from operations above net income, long-term debt over assets down, current ratio up, no more shares, gross margin up, and revenue over assets up. 8 or 9 is strong, 0 to 2 weak. (Assets are at the end of each period here; Piotroski used those at the start.)",
    ]
