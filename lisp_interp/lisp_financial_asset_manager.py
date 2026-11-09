"""A three-statement model of an asset manager (see lisp_financial_model.py, which this builds on).

An asset manager's revenue is a small fee on a very large amount of other people's money: so many basis
points of the assets under management (AUM) -- 0.2% of an index fund, 1% of an equity fund. So the model's driver
is AUM, not revenue:

  AUM at the end of a period grows at the rate you assume, which is the market's appreciation plus the net
    money the clients put in (flows) -- the one number that matters most, and the one nobody knows. (Type a
    formula such as =0.06+0.02 in the cell if you want to see the two apart.)
  Revenue is the fee rate -- basis points of average AUM, a year's -- times the average of the AUM at the start
    and the end of the period. The fee rate drifts down as money moves from active funds to index funds, and
    the Assumptions tab shows what it has done.
  The rest is the model of an ordinary company: operating expenses (compensation, distribution, general and
    administrative) are percentages of revenue, so the operating margin is what you assume; receivables, payables,
    capital spending, depreciation and the amortization of intangibles, interest, taxes, dividends, and
    repurchases are as in "general".

ASSETS UNDER MANAGEMENT ARE NOT IN THE SEC'S DATA. The SEC's summary of a company's numbers has no AUM (T. Rowe
Price tagged it until 2022; BlackRock and the others never), and the numbers in the filings are in the text of the
annual report, not tagged. So you give them: `:aum` is the AUM, in billions, at the end of each period, oldest
first, ending with the latest period reported -- as many as you have, at most one for each period of history
(history is cut short to the periods that have one). Type the year-end figures from the annual report; they
are blue on the Assumptions tab, and you can change them there.
"""

from lisp_core import LispError, LispVector, Pair, pairs_to_list
import lisp_financial_model as model
import lisp_sec

Line, SheetLayout = model.Line, model.SheetLayout
INCOME, BALANCE, CASH_FLOW, ASSUMPTIONS = model.INCOME, model.BALANCE, model.CASH_FLOW, model.ASSUMPTIONS
safe_ratio = model.safe_ratio

ASSET_MANAGER_SIC_CODES = (6282,)               # investment advice
AUM_GROWTH_LIMITS = (-0.30, 0.40)               # in a year
FEE_RATE_LIMITS = (0.0, 1000.0)                 # basis points
AUM_CONCEPTS = ["AssetsUnderManagementCarryingAmount"]       # (T. Rowe Price's, to 2022)


def number_list(value, who):
    """A list or vector of numbers, as a Python list of floats."""
    if isinstance(value, Pair):
        items = pairs_to_list(value)
    elif isinstance(value, LispVector):
        items = list(value.items.tolist())             # (a numpy array)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = None
    if not items or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in items):
        raise LispError("%s: :aum is a list of numbers, the assets under management in billions at the end of each "
                        "period, oldest first, such as (8590 10010 11550)" % who)
    return [float(x) for x in items]


def aum_from_facts(facts, periods):
    """The AUM at the end of each period, in billions, if the SEC's facts have it for every period, else None."""
    for concept in AUM_CONCEPTS:
        values = [lisp_sec.ConceptFacts(facts, concept).balance_at(p.end) for p in periods]
        if all(v is not None for v in values):
            return [v / 1e9 for v in values]
    return None


class AssetManagerHistory(model.History):
    """The reported numbers of an ordinary company's, and the AUM at the end of each period (in billions)."""

    aum = None

    def set_aum(self, aum):
        self.aum = list(aum)


class AssetManagerModel(model.Model):
    """The model of an asset manager: the ordinary company's, with revenue from AUM and a fee rate."""

    def unit_description(self):
        return super().unit_description() + "; assets under management in billions"

    # --- Assumptions

    def assumption_series(self):
        rows = super().assumption_series()
        h, n, days = self.h, self.history_count, self.days_in_period
        a, inc = self.refs(ASSUMPTIONS, ASSUMPTIONS), self.refs(INCOME, ASSUMPTIONS)
        year_fraction = days / 365
        limits = tuple(x * year_fraction for x in AUM_GROWTH_LIMITS)
        rows.append(("aum-growth", "Growth of assets under management, market and net flows (over the %s)" %
                     ("quarter" if self.period == "quarterly" else "year"), "percent",
                     [None if i < 1 or not h.aum[i - 1] else h.aum[i] / h.aum[i - 1] - 1 for i in range(n)], limits,
                     lambda i: "=IFERROR(%s/%s-1,0)" % (a("aum", i), a("aum", i - 1)) if i >= 1 else None))
        rows.append(("fee-rate", "Revenue, basis points of average AUM (a year's)", "decimal",
                     [None if i < 1 or not (h.aum[i - 1] + h.aum[i]) else
                      h.revenue[i] * 10 / ((h.aum[i - 1] + h.aum[i]) / 2) / year_fraction for i in range(n)],
                     FEE_RATE_LIMITS,
                     lambda i: "=IFERROR(%s*10/AVERAGE(%s,%s)*365/%s,0)" % (inc("revenue", i), a("aum", i - 1), a("aum", i),
                                                                       a("days", i)) if i >= 1 else None))
        return rows

    def assumptions_layout(self):
        base = super().assumptions_layout()
        _, _, growth_format, _, _, growth_formula = self.assumptions["growth"]
        aum = Line("aum", "Assets under management at the end of the period, billions", "money", (),
                   lambda i: self.h.aum[i] if not self.is_forecast(i) else
                   "=%s*(1+%s)" % (self.ref(ASSUMPTIONS, "aum", i - 1, ASSUMPTIONS),
                                   self.ref(ASSUMPTIONS, "aum-growth", i, ASSUMPTIONS)))
        lines = []
        for line in base.lines:
            if line is not None and line.key == "growth":
                lines += [aum, self.main_line_from_series("aum-growth"), self.main_line_from_series("fee-rate"),
                          Line("growth", "Revenue growth, as AUM and the fee rate give", growth_format, (), growth_formula)]
            else:
                lines.append(line)
        return SheetLayout(ASSUMPTIONS, "Assumptions", lines)

    # --- Income statement

    def income_layout(self):
        layout = super().income_layout()
        a = self.refs(ASSUMPTIONS, INCOME)
        for position, line in enumerate(layout.lines):
            if line is not None and line.key == "revenue":
                layout.lines[position] = Line(
                    "revenue", "Revenue (fees on average assets under management)", "money", ("bold",),
                    lambda i: self.h.revenue[i] if not self.is_forecast(i) else
                    "=%s*AVERAGE(%s,%s)/10*%s/365" % (a("fee-rate", i), a("aum", i - 1), a("aum", i), a("days", i)))
            elif line is not None and line.key == "other-operating":
                line.label = "Other operating expenses (compensation, distribution, ...)"
        return layout

    def forecast_notes(self):
        return [
            "Assets under management (AUM, in billions) at the end of a period are the last period's times one plus the growth assumed: the market's appreciation plus the net money clients put in. Type a formula such as =0.06+0.02 to see the two apart.",
            "Revenue is the fee rate (basis points of average AUM, a year's) times the average of the AUM at the start and end of the period (and a quarter's worth, for quarters). The Assumptions tab shows the fee rate in the reported periods; it drifts down as money moves to index funds.",
            "The AUM is not in the SEC's data: it was given to the program (:aum), and can be changed on the Assumptions tab.",
            "Operating expenses (compensation, distribution, and general and administrative) are percentages of revenue, so the operating margin is an assumption. Interest uses last period's debt and cash, so no formula refers to itself.",
            "Receivables and payables follow days of revenue. Plant and equipment is last period's plus capital expenditures less depreciation; intangibles fall by their amortization. Debt is last period's plus what is borrowed (repaid), an assumption. Equity is last period's plus net income and stock compensation, less dividends and repurchases.",
            "Cash is last period's plus the net change in cash on the Cash Flow tab. Goodwill, investments, and the other assets and liabilities stay as they were.",
            "Nothing keeps cash from going negative if the payouts are more than the company earns: change the assumptions, or the borrowing.",
        ]


TEMPLATE = model.Template("asset-manager", "an asset manager", model.GENERAL_ITEMS, AssetManagerHistory,
                          AssetManagerModel, [("revenue",)], ASSET_MANAGER_SIC_CODES, needs_aum=True)
