"""A bank model's credit losses by type of loan, from the FDIC's Call Reports, and scenarios with more of them.

The SEC's facts tell how much a bank lost on all its loans, not on which. The FDIC's Call Reports (lisp_fdic.py)
tell both, for every insured bank since 1984: how much it has lent on houses, on apartment buildings, on offices
and shops, to businesses, on credit cards, and so on, how much of each it has charged off a year, and how much is
past due. A bank model (lisp_financial_bank.py) made with them has two more tabs:

  FDIC Call Reports  the Call Reports of the company's banks, added up: for each type of loan, the loans at the end of
                  each 12 months since 2001, the net charge-offs in them, the noncurrent loans, and the net
                  charge-offs as a percentage of the loans at the start; and the banks' capital, their funding (deposits,
                  uninsured, brokered, Federal Home Loan Bank advances), their securities at cost and at fair value,
                  the allowance, and commercial real estate as the regulators' concentration guidance counts it.
  Credit Losses   a row for each type: today's loans, how much has been lost on them a year (last year, the last
                  five years on average, the worst year), and three scenarios -- Base, Adverse, Severe -- each a
                  default rate (the share of the loans that stop paying in a year) and a recovery (how much of a
                  defaulted loan the bank gets back). A loss rate is the default rate times what is not recovered.
                  A cell chooses the scenario of the forecast, and another how many periods it lasts. Last, the
                  warning signs of the latest Call Report, beside the regulators' guides (or rules of thumb).

The forecast's net charge-offs (on the Assumptions tab) are the chosen scenario's loss rate for those periods, and
the base scenario's after; so a worse scenario raises the provision, lowers net income and equity, and with them
the common equity tier 1 ratio that the Balance Sheet now has (estimated from the banks' own: the FDIC has their
capital and risk-weighted assets). A table at the bottom of the Credit Losses tab shows all three scenarios side by
side, worked out from today's loans alone.

The scenarios start from the bank's own history: Base is its average loss rate over the last five years, Severe
its worst year since 2001 (for most banks, 2009 or 2010), Adverse halfway between; their recoveries start from a
typical figure for each type (the Call Report doesn't say what the bank recovers) and are lower in the worse
scenarios. Every one is a cell to type over: a higher default rate on commercial real estate alone, a lower
recovery on credit cards, ...
"""

from lisp_core import LispError
import lisp_fdic
import lisp_financial_model as model

ASSUMPTIONS, BALANCE = model.ASSUMPTIONS, model.BALANCE
CREDIT, FDIC_TAB = "Credit Losses", "FDIC Call Reports"
SCENARIOS = ("Base", "Adverse", "Severe")
STRESS_YEARS = 2                         # how long a scenario lasts, to start with
RECOVERY_CUTS = {"Adverse": 0.05, "Severe": 0.10}       # how much lower the recovery is than the base scenario's
MILLION = 1e6

# the names the tabs give their cells, for the model's formulas (see lisp_financial_bank.py)
NAMES = ("credit_scenario", "stress_periods", "base_loss_rate", "adverse_loss_rate", "severe_loss_rate",
         "chosen_loss_rate", "common_equity_capital", "risk_weighted_assets")


def column(index):
    """The letter of a column, counted from 0 (A)."""
    return model.column_letter(index)


def millions(value):
    return None if value is None else value / MILLION


def capital_date(book, the_model):
    """The date of the banks' capital that the model's capital ratio starts from: the last period the model reports,
    if the FDIC has a report for it, or else the FDIC's latest."""
    end = the_model.ends[the_model.history_count - 1]
    wanted = end.strftime("%Y%m%d")
    if wanted in book.reports and all(value is not None for value in book.capital(wanted)):
        return wanted
    return book.latest


def capital_period(book, the_model):
    """The period of the model's history that the banks' capital is at (the last one, if none is)."""
    date = capital_date(book, the_model)
    for i in range(the_model.history_count):
        if the_model.ends[i].strftime("%Y%m%d") == date:
            return i
    return the_model.history_count - 1


def has_capital(book, the_model):
    return all(value is not None for value in book.capital(capital_date(book, the_model)))


# ---------------------------------------------------------------------------
# The FDIC Call Reports tab
# ---------------------------------------------------------------------------

class FdicTab:
    """The FDIC Call Reports tab: its cells, and where its rows are (for the Credit Losses tab's formulas)."""

    def __init__(self, book, the_model):
        self.book, self.model = book, the_model
        self.ends = book.period_ends
        self.rows = []
        self.row_of = {}                    # (section, loan type key) -> row number
        self.build()

    def last_column(self):
        return column(len(self.ends))

    def address(self, section, key, period):
        """The address (on this tab) of a type's cell in a period (an index into the period ends)."""
        return "%s%d" % (column(period + 1), self.row_of[(section, key)])

    def add(self, row):
        self.rows.append(row + [None] * (len(self.ends) + 1 - len(row)))
        return len(self.rows)

    def amounts(self, section, title, amount_of, starts_with_first):
        """A section of amounts in $ millions: a row for each type (everything else being what they leave of all
        loans), and one for all loans."""
        self.add([(title, ("section",))] + [(None, ("section",))] * len(self.ends))
        keys = self.book.keys
        first_type = len(self.rows) + 1
        for key in keys + ["total"]:
            row_number = len(self.rows) + 1
            self.row_of[(section, key)] = row_number
            cells = [(self.book.labels.get(key, "All loans"), ("total",) if key == "total" else ())]
            for n, end in enumerate(self.ends):
                if n == 0 and not starts_with_first:
                    cells.append(None)
                elif key == lisp_fdic.EVERYTHING_ELSE[0]:
                    letter = column(n + 1)
                    total_row = first_type + len(keys)
                    cells.append(("=%s%d-SUM(%s%d:%s%d)" % (letter, total_row, letter, first_type, letter, row_number - 1),
                                  ("money",)))
                else:
                    value = millions(amount_of(key, end))
                    cells.append(None if value is None else (value, ("money", "data")))
            self.add(cells)
        self.add([None])

    def build(self):
        book, m = self.book, self.model
        month_day = lisp_fdic.report_date(book.latest).date.strftime("%B %d").replace(" 0", " ")
        self.add([("%s (%s): FDIC Call Reports, loans by type" % (m.company_name, m.ticker), ("title",))])
        self.add([("The Call Reports of %s, added up. $ millions. Each period is the 12 months to %s; loans and "
                   "noncurrent loans are at its end." % (book.bank_names(), month_day), ("italic",))])
        self.add([None])
        self.add([("12 months to", ("bold",))] +
                 [(lisp_fdic.report_date(end), ("date", "header")) for end in self.ends])
        self.add([None])
        self.amounts("loans", "Loans at the end of the period", book.balance, True)
        self.amounts("charge-offs", "Net charge-offs in the period (loans written off, less what was recovered)",
                     book.charge_offs, False)
        self.amounts("noncurrent", "Noncurrent loans at the end (90 days or more past due, or not accruing interest)",
                     book.noncurrent, True)
        self.add([("Net charge-offs, %% of the loans at the end of the period before (empty where the loans more than "
                   "%s in the period -- a bank bought, or a new kind of lending begun -- or were under %g%% of all loans "
                   "at its start)" % ("doubled" if lisp_fdic.MOST_GROWTH == 2 else "grew %g times" % lisp_fdic.MOST_GROWTH,
                                      lisp_fdic.LEAST_SHARE * 100), ("section",))] + [(None, ("section",))] * len(self.ends))
        for key in book.keys + ["total"]:
            self.row_of[("rates", key)] = len(self.rows) + 1
            cells = [(book.labels.get(key, "All loans"), ("total",) if key == "total" else ()), None]
            for n in range(1, len(self.ends)):
                start, end = self.address("loans", key, n - 1), self.address("loans", key, n)
                all_loans = self.address("loans", "total", n - 1)
                cells.append(('=IF(%s>%g*%s,"",IF(%s<%g*%s,"",IFERROR(%s/%s,"")))'
                              % (end, lisp_fdic.MOST_GROWTH, start, start, lisp_fdic.LEAST_SHARE, all_loans,
                                 self.address("charge-offs", key, n), start), ("percent",)))
            self.add(cells)
        self.add([None])
        self.add_capital()
        self.add([None])
        self.add_funding()
        self.add([None])
        self.add_securities()
        self.add([None])
        self.add_allowance()
        self.add([None])
        self.add_real_estate_concentration()

    # --- the rows after the loans

    def section(self, title):
        self.add([(title, ("section",))] + [(None, ("section",))] * len(self.ends))

    def reported_row(self, section, key, label, amount_of=None):
        """A row of amounts ($ millions) from the Call Reports: one of lisp_fdic.REPORT_FIELDS, or amount_of(date)."""
        self.row_of[(section, key)] = len(self.rows) + 1
        cells = [(label, ())]
        for end in self.ends:
            value = millions(amount_of(end) if amount_of else self.book.reported(key, end))
            cells.append(None if value is None else (value, ("money", "data")))
        self.add(cells)

    def formula_row(self, section, key, label, formula, number_format="percent", first=0):
        """A row with a formula in each period from `first`: formula(n) is period n's, without its = sign."""
        self.row_of[(section, key)] = len(self.rows) + 1
        style = ("italic",) if number_format == "percent" else ()
        self.add([(label, style)] + [None] * first +
                 [("=" + formula(n), (number_format,) + style) for n in range(first, len(self.ends))])

    def ratio_row(self, section, key, label, top, bottom):
        """A row of top / bottom, each (section, key) of a row of this tab; empty where top is (Sheets would make an
        empty cell 0, and the ratio 0%)."""
        self.formula_row(section, key, label, lambda n: 'IF(%s="","",IFERROR(%s/%s,""))' % (
            self.address(*top, n), self.address(*top, n), self.address(*bottom, n)))

    def add_capital(self):
        book = self.book
        self.section("The banks' capital")
        for key, label in (("common-equity", "Common equity tier 1 capital"),
                           ("risk-weighted-assets", "Risk-weighted assets")):
            self.reported_row("capital", key, label,
                              lambda end, key=key: book.capital(end)[0 if key == "common-equity" else 1])
        self.ratio_row("capital", "ratio", "Common equity tier 1 ratio (capital / risk-weighted assets)",
                       ("capital", "common-equity"), ("capital", "risk-weighted-assets"))
        self.reported_row("capital", "tier-1", "Tier 1 capital (common equity tier 1, and preferred stock)")
        self.reported_row("capital", "total-capital", "Total risk-based capital (tier 1, and tier 2: some debt and part of the allowance)")
        self.reported_row("capital", "assets", "Total assets")
        self.ratio_row("capital", "leverage", "Tier 1 capital / total assets (near the leverage ratio, which uses the "
                       "quarter's average assets)", ("capital", "tier-1"), ("capital", "assets"))

    def add_funding(self):
        self.section("Deposits and other funding, at the end of the period (who could take their money out, and how fast)")
        for key, label in (("deposits", "Deposits"),
                           ("noninterest-bearing", "Deposits that pay no interest (in the United States)"),
                           ("uninsured", "Uninsured deposits (above the FDIC's limit; the banks' estimate)"),
                           ("brokered", "Brokered deposits (placed by brokers, for the rate)"),
                           ("home-loan-bank", "Advances from the Federal Home Loan Banks")):
            self.reported_row("funding", key, label)
        self.ratio_row("funding", "noninterest-share", "Deposits that pay no interest, % of deposits",
                       ("funding", "noninterest-bearing"), ("funding", "deposits"))
        self.ratio_row("funding", "uninsured-share", "Uninsured deposits, % of deposits",
                       ("funding", "uninsured"), ("funding", "deposits"))
        self.ratio_row("funding", "brokered-share", "Brokered deposits, % of deposits",
                       ("funding", "brokered"), ("funding", "deposits"))
        self.ratio_row("funding", "home-loan-bank-share", "Federal Home Loan Bank advances, % of total assets",
                       ("funding", "home-loan-bank"), ("capital", "assets"))
        self.ratio_row("funding", "loans-to-deposits", "Loans / deposits", ("loans", "total"), ("funding", "deposits"))

    def add_securities(self):
        self.section("Securities: what they cost, and what they are worth (a rise in interest rates lowers what they are worth)")
        for key, label in (("available-for-sale-cost", "Available for sale, at cost (amortized)"),
                           ("available-for-sale-value", "Available for sale, at fair value"),
                           ("held-to-maturity-cost", "Held to maturity, at cost (amortized)"),
                           ("held-to-maturity-value", "Held to maturity, at fair value")):
            self.reported_row("securities", key, label)

        def gain(kind):
            value, cost = (lambda n: self.address("securities", kind + "-value", n),
                           lambda n: self.address("securities", kind + "-cost", n))
            return lambda n: 'IF(%s="","",%s-%s)' % (value(n), value(n), cost(n))
        self.formula_row("securities", "available-for-sale-gain", "Unrealized gain (loss), available for sale (already "
                         "in equity, through other comprehensive income)", gain("available-for-sale"), "money")
        self.formula_row("securities", "held-to-maturity-gain", "Unrealized gain (loss), held to maturity (in neither "
                         "equity nor capital)", gain("held-to-maturity"), "money")
        self.formula_row("securities", "gain-to-capital", "Unrealized gain (loss) on all securities, % of common equity "
                         "tier 1 capital", lambda n: 'IFERROR((%s+%s)/%s,"")' % (
                             self.address("securities", "available-for-sale-gain", n),
                             self.address("securities", "held-to-maturity-gain", n), self.address("capital", "common-equity", n)))
        self.formula_row("securities", "ratio-with-held-to-maturity", "Common equity tier 1 ratio counting the "
                         "held-to-maturity gain (loss), before taxes", lambda n: 'IFERROR((%s+%s)/%s,"")' % (
                             self.address("capital", "common-equity", n), self.address("securities", "held-to-maturity-gain", n),
                             self.address("capital", "risk-weighted-assets", n)))
        self.formula_row("securities", "ratio-with-all", "Common equity tier 1 ratio counting all the unrealized gains "
                         "(losses), before taxes (for a bank that leaves those available for sale out of its capital, "
                         "as banks under $700 billion may)", lambda n: 'IFERROR((%s+%s+%s)/%s,"")' % (
                             self.address("capital", "common-equity", n), self.address("securities", "held-to-maturity-gain", n),
                             self.address("securities", "available-for-sale-gain", n),
                             self.address("capital", "risk-weighted-assets", n)))

    def add_allowance(self):
        self.section("The allowance for credit losses on loans")
        self.reported_row("allowance", "allowance", "Allowance for credit losses")
        self.ratio_row("allowance", "to-loans", "Allowance, % of loans", ("allowance", "allowance"), ("loans", "total"))
        self.ratio_row("allowance", "to-noncurrent", "Allowance, % of noncurrent loans (coverage: under 100% means "
                       "less put aside than is already past due)", ("allowance", "allowance"), ("noncurrent", "total"))

    def add_real_estate_concentration(self):
        """Commercial real estate as the regulators' guidance of 2006 counts it: construction and land, multifamily,
        nonfarm nonresidential not occupied by its owner, and loans to finance real estate not secured by it; over the
        total risk-based capital. The guidance looks harder at a bank above 300% (if it grew 50% in 3 years), or with
        construction above 100%."""
        self.section("Commercial real estate concentration (the regulators look harder above 300% of capital, or "
                     "construction above 100%)")
        self.formula_row("real-estate", "construction", "Construction and land development loans",
                         lambda n: self.address("loans", "construction", n), "money")
        self.formula_row("real-estate", "multifamily", "Multifamily (apartment) loans",
                         lambda n: self.address("loans", "multifamily", n), "money")
        self.reported_row("real-estate", "nonresidential-not-owner-occupied",
                          "Nonfarm nonresidential loans not occupied by their owners (offices, shops, hotels, ...)")
        self.reported_row("real-estate", "real-estate-not-secured", "Loans to finance commercial real estate, not "
                          "secured by real estate")
        first = self.row_of[("real-estate", "construction")]
        # (empty before 2007, when the Call Report began to say which nonresidential loans their owners occupy)
        self.formula_row("real-estate", "total", "Commercial real estate, as the guidance counts it",
                         lambda n: 'IF(ISBLANK(%s),"",SUM(%s%d:%s%d))' % (
                             self.address("real-estate", "nonresidential-not-owner-occupied", n),
                             column(n + 1), first, column(n + 1), first + 3), "money")
        self.ratio_row("real-estate", "to-capital", "Commercial real estate, % of total risk-based capital (guidance: 300%)",
                       ("real-estate", "total"), ("capital", "total-capital"))
        self.ratio_row("real-estate", "construction-to-capital", "Construction and land, % of total risk-based capital "
                       "(guidance: 100%)", ("real-estate", "construction"), ("capital", "total-capital"))
        self.formula_row("real-estate", "growth", "Growth of commercial real estate over 3 years (guidance: 50%, with "
                         "the 300%)", lambda n: 'IF(OR(%s="",%s=""),"",IFERROR(%s/%s-1,""))' % (
                             self.address("real-estate", "total", n), self.address("real-estate", "total", n - 3),
                             self.address("real-estate", "total", n), self.address("real-estate", "total", n - 3)),
                         first=3)

    def sheet(self):
        return {"name": FDIC_TAB, "cells": self.rows, "frozen_rows": 4, "frozen_columns": 1,
                "widths": [(0, 0, 430), (1, len(self.ends), 90)]}


# ---------------------------------------------------------------------------
# The Credit Losses tab
# ---------------------------------------------------------------------------

# its table's columns: (key, heading)
COLUMNS = [
    ("type", "Loan type"), ("loans", "Loans ($ millions)"), ("share", "Share of all loans"),
    ("noncurrent", "Noncurrent now"), ("last", "Losses, last 12 months"), ("average", "Losses, average of the last 5 years"),
    ("worst", "Losses, worst year since %d" % lisp_fdic.FIRST_YEAR), ("recovery", "Base: recovery on a default"),
    ("base-default", "Base: defaults a year"), ("adverse-default", "Adverse: defaults a year"),
    ("adverse-recovery", "Adverse: recovery"), ("severe-default", "Severe: defaults a year"),
    ("severe-recovery", "Severe: recovery"), ("base-loss", "Base: losses a year"),
    ("adverse-loss", "Adverse: losses a year"), ("severe-loss", "Severe: losses a year"),
    ("chosen-loss", "In the scenario chosen"),
]
COLUMN_OF = {key: n for n, (key, _) in enumerate(COLUMNS)}


class CreditTab:
    """The Credit Losses tab."""

    def __init__(self, book, the_model, fdic):
        self.book, self.model, self.fdic = book, the_model, fdic
        self.rows, self.names, self.cell_of = [], [], {}
        self.build()

    def add(self, row):
        self.rows.append(row)
        return len(self.rows)

    def at(self, key, row):
        return "%s%d" % (column(COLUMN_OF[key]), row)

    def name_cell(self, name, address):
        self.names.append((name, address))

    def fdic_ref(self, address):
        return "%s!%s" % (model.quoted_tab(FDIC_TAB), address)

    def build(self):
        book, m, fdic = self.book, self.model, self.fdic
        tax_rate = m.range_names[(ASSUMPTIONS, "tax-rate")]
        days = m.range_names[(ASSUMPTIONS, "days")]
        latest = lisp_fdic.report_date(book.latest).date.isoformat()
        self.add([("%s (%s): Credit losses, and scenarios with more of them" % (m.company_name, m.ticker), ("title",))])
        self.add([("Loans by type from the FDIC's Call Reports of the company's banks (the FDIC Call Reports tab), at %s. "
                   "$ millions." % latest, ("italic",))])
        self.add([("Choose a scenario below: the forecast's net charge-offs (Assumptions tab) are its loss rate for "
                   "the periods of stress, and the base scenario's after. Every yellow cell can be typed over: a "
                   "higher default rate for one type of loan, a lower recovery for another.", ("italic",))])
        self.add([None])
        stress = STRESS_YEARS * model.PERIODS_PER_YEAR[m.period]
        scenario_row = self.add([("Scenario in the forecast (Base, Adverse, or Severe)", ("bold",)), ("Base", ("input",))])
        self.name_cell("credit_scenario", "B%d" % scenario_row)
        stress_row = self.add([("Periods of stress, from the first forecast period (%s)" %
                                ("years" if m.period == "annual" else "quarters"), ()), (stress, ("input", "decimal"))])
        self.name_cell("stress_periods", "B%d" % stress_row)
        self.scenario_row = scenario_row
        self.add([None])

        # --- the table
        self.add([("Loans by type, and their losses a year (net charge-offs, % of the loans at the start of the "
                   "year)", ("section",))] + [(None, ("section",))] * (len(COLUMNS) - 1))
        self.add([(heading, ("bold", "wrap")) for _, heading in COLUMNS])
        first = len(self.rows) + 1
        keys = book.keys
        total_row = first + len(keys)
        last_period = len(fdic.ends) - 1
        for n, key in enumerate(keys):
            row = first + n
            rates = "%s:%s" % (fdic.address("rates", key, 1), fdic.address("rates", key, last_period))
            recent = "%s:%s" % (fdic.address("rates", key, max(1, last_period - 4)), fdic.address("rates", key, last_period))
            cells = {
                "type": (book.labels[key], ()),
                "loans": ("=" + self.fdic_ref(fdic.address("loans", key, last_period)), ("money", "link")),
                "share": ('=IFERROR(%s/%s,0)' % (self.at("loans", row), self.at("loans", total_row)), ("percent",)),
                "noncurrent": ('=IFERROR(%s/%s,"")' % (self.fdic_ref(fdic.address("noncurrent", key, last_period)),
                                                        self.at("loans", row)), ("percent",)),
                "last": ('=IFERROR(%s+0,0)' % self.fdic_ref(fdic.address("rates", key, last_period)), ("percent",)),
                "average": ("=IFERROR(AVERAGE(%s),0)" % self.fdic_ref(recent), ("percent",)),
                "worst": ("=IFERROR(MAX(%s),0)" % self.fdic_ref(rates), ("percent",)),
                "recovery": (book.recoveries[key], ("percent", "input")),
                "base-default": ("=MAX(%s,0)/(1-%s)" % (self.at("average", row), self.at("recovery", row)),
                                 ("percent", "input-formula")),
                "adverse-default": ("=MAX((%s+%s)/2,0)/(1-%s)" % (self.at("average", row), self.at("worst", row),
                                                                   self.at("recovery", row)), ("percent", "input-formula")),
                "adverse-recovery": ("=MAX(%s-%s,0)" % (self.at("recovery", row), RECOVERY_CUTS["Adverse"]),
                                     ("percent", "input-formula")),
                "severe-default": ("=MAX(%s,0)/(1-%s)" % (self.at("worst", row), self.at("recovery", row)),
                                   ("percent", "input-formula")),
                "severe-recovery": ("=MAX(%s-%s,0)" % (self.at("recovery", row), RECOVERY_CUTS["Severe"]),
                                    ("percent", "input-formula")),
                "base-loss": ("=%s*(1-%s)" % (self.at("base-default", row), self.at("recovery", row)), ("percent",)),
                "adverse-loss": ("=%s*(1-%s)" % (self.at("adverse-default", row), self.at("adverse-recovery", row)),
                                 ("percent",)),
                "severe-loss": ("=%s*(1-%s)" % (self.at("severe-default", row), self.at("severe-recovery", row)),
                                ("percent",)),
                "chosen-loss": ('=IF(credit_scenario="Severe",%s,IF(credit_scenario="Adverse",%s,%s))'
                                % (self.at("severe-loss", row), self.at("adverse-loss", row), self.at("base-loss", row)),
                                ("percent",)),
            }
            self.add([cells[key_] for key_, _ in COLUMNS])
        # the totals: amounts added up, rates weighted by today's loans
        totals = [("All loans", ("total",))]
        shares = "%s:%s" % (self.at("share", first), self.at("share", total_row - 1))
        for key_, _ in COLUMNS[1:]:
            span = "%s:%s" % (self.at(key_, first), self.at(key_, total_row - 1))
            if key_ in ("loans",):
                totals.append(("=SUM(%s)" % span, ("money", "total")))
            elif key_ == "share":
                totals.append(("=SUM(%s)" % span, ("percent", "total")))
            else:
                totals.append(("=SUMPRODUCT(%s,%s)" % (shares, span), ("percent", "total")))
        self.add(totals)
        for name, key_ in (("base_loss_rate", "base-loss"), ("adverse_loss_rate", "adverse-loss"),
                           ("severe_loss_rate", "severe-loss"), ("chosen_loss_rate", "chosen-loss")):
            self.name_cell(name, self.at(key_, total_row))
        self.add([("The rates of all loans are the types' weighted by today's loans (so the worst year of all loans "
                   "is every type at its worst at once). A default rate is the share of the loans that stop paying in "
                   "a year; the loss rate is the default rate times the share not recovered. Base starts from the "
                   "average of the last 5 years, Severe from the worst year, Adverse from halfway between; the "
                   "recoveries are typical figures for each type, %d and %d points lower in the worse scenarios."
                   % (RECOVERY_CUTS["Adverse"] * 100, RECOVERY_CUTS["Severe"] * 100), ("italic", "wrap"))])
        self.add([None])
        self.total_loans = "$%s$%d" % (column(COLUMN_OF["loans"]), total_row)

        # --- the banks' capital, and what each scenario would do to it
        if has_capital(book, m):
            date = capital_date(book, m)
            common_equity, risk_weighted = book.capital(date)
            self.add([("The banks' capital (from the FDIC, at %s)" % lisp_fdic.report_date(date).date.isoformat(),
                       ("section",))] + [(None, ("section",))] * 3)
            row = self.add([("Common equity tier 1 capital ($ millions)", ()), (millions(common_equity), ("money", "data"))])
            self.name_cell("common_equity_capital", "B%d" % row)
            row = self.add([("Risk-weighted assets ($ millions)", ()), (millions(risk_weighted), ("money", "data"))])
            self.name_cell("risk_weighted_assets", "B%d" % row)
            self.add([None])
        self.add([("What each scenario costs, from today's loans alone (before the rest of the model)", ("section",))] +
                 [(None, ("section",))] * 3)
        self.add([None] + [(name, ("bold",)) for name in SCENARIOS])
        rate_row = self.add([("Losses a year, % of loans", ())] +
                            [("=%s_loss_rate" % name.lower(), ("percent", "link")) for name in SCENARIOS])
        loss_row = self.add([("Losses over the periods of stress ($ millions)", ())] +
                            [("=%s%d*%s*stress_periods*%s/365" % (column(n + 1), rate_row, self.total_loans, days),
                              ("money",)) for n in range(len(SCENARIOS))])
        extra_row = self.add([("More than the base scenario's, after taxes", ())] +
                             [("=(%s%d-$B%d)*(1-%s)" % (column(n + 1), loss_row, loss_row, tax_rate), ("money",))
                              for n in range(len(SCENARIOS))])
        if has_capital(book, m):
            self.add([("Common equity tier 1 ratio now", ())] +
                     [("=common_equity_capital/risk_weighted_assets", ("percent",)) for _ in SCENARIOS])
            self.add([("Common equity tier 1 ratio after those losses (if nothing else changed)", ())] +
                     [("=(common_equity_capital-%s%d)/risk_weighted_assets" % (column(n + 1), extra_row), ("percent",))
                      for n in range(len(SCENARIOS))])
            self.add([("A bank needs 4.5% at least, plus a buffer of 2.5% or more (more for the largest banks) to pay "
                       "dividends and buy back shares freely: about 7% is the least it can run on.", ("italic",))])
        self.add([None])
        self.add_warning_signs()

    # the measures of the last table: (FDIC tab section, key, label, the guide's number or None, its test, what to watch)
    WARNING_SIGNS = [
        ("real-estate", "to-capital", "Commercial real estate, % of total risk-based capital", 3.0, ">",
         "The regulators look harder at a bank above 300% (whose commercial real estate grew 50% in 3 years)"),
        ("real-estate", "construction-to-capital", "Construction and land, % of total risk-based capital", 1.0, ">",
         "And at one above 100%: construction loans lose the most in a downturn"),
        ("real-estate", "growth", "Growth of commercial real estate over the last 3 years", 0.5, ">",
         "Fast growth in commercial real estate preceded many of the bank failures of 2009-2011"),
        ("allowance", "to-loans", "Allowance, % of loans", None, None,
         "Compare with the losses a year of the scenarios above: an allowance smaller than a year of them is thin"),
        ("allowance", "to-noncurrent", "Allowance, % of noncurrent loans", 1.0, "<",
         "Under 100%: less is put aside than is already past due"),
        ("funding", "uninsured-share", "Uninsured deposits, % of deposits", 0.5, ">",
         "Uninsured depositors leave first in a scare; Silicon Valley Bank's were over 90%"),
        ("funding", "noninterest-share", "Deposits that pay no interest, % of deposits", None, None,
         "The cheapest funding, and the most likely to move to higher rates when rates rise"),
        ("funding", "brokered-share", "Brokered deposits, % of deposits", 0.1, ">",
         "Deposits bought for the rate: they leave for a better one"),
        ("funding", "home-loan-bank-share", "Federal Home Loan Bank advances, % of total assets", 0.1, ">",
         "Borrowing to replace deposits that left, or to grow faster than deposits"),
        ("funding", "loans-to-deposits", "Loans / deposits", 1.0, ">",
         "Above 100%: some loans are funded by borrowing"),
        ("securities", "gain-to-capital", "Unrealized gain (loss) on securities, % of common equity tier 1 capital",
         -0.25, "<", "What selling the securities would cost: a quarter of capital or more is a lot"),
        ("securities", "ratio-with-all", "Common equity tier 1 ratio counting the unrealized gains (losses) on "
         "securities", 0.07, "<", "Below about 7% the bank would be short of capital if it had to sell its securities"),
    ]

    def add_warning_signs(self):
        """A table of the measures from the latest Call Report that warn of trouble, with the guide the regulators use
        (or a rule of thumb) and a flag where the bank is past it."""
        fdic = self.fdic
        last_period = len(fdic.ends) - 1
        self.add([("Concentration, reserves, funding, and securities (latest Call Report: the FDIC Call Reports tab "
                   "has their history)", ("section",))] + [(None, ("section",))] * 3)
        self.add([(heading, ("bold", "wrap")) for heading in ("Measure", "The banks'", "Guide (the regulators', or a rule of thumb)", "Past it?", "What to watch")])
        for section, key, label, guide, test, watch in self.WARNING_SIGNS:
            row = len(self.rows) + 1
            measure = self.fdic_ref(fdic.address(section, key, last_period))
            value = ('=IF(%s="","",%s)' % (measure, measure), ("percent", "link"))
            if guide is None:
                self.add([(label, ()), value, None, None, (watch, ("italic",))])
            else:
                flag = '=IF(B%d="","",IF(B%d%s%s,"Yes",""))' % (row, row, test, "C%d" % row)
                self.add([(label, ()), value, (guide, ("percent",)), (flag, ("bold",)), (watch, ("italic",))])

    def sheet(self):
        width = len(COLUMNS)
        rows = [row + [None] * (width - len(row)) for row in self.rows]
        return {"name": CREDIT, "cells": rows, "names": self.names,
                "widths": [(0, 0, 330), (1, width - 1, 95)],
                "validations": [{"range": "B%d" % self.scenario_row, "choices": list(SCENARIOS)}]}


# ---------------------------------------------------------------------------
# What the bank model uses
# ---------------------------------------------------------------------------

def check_names(the_model):
    """The tabs' names must not be the name of a line of the model."""
    taken = set(the_model.range_names.values())
    clash = [name for name in NAMES if name in taken]
    if clash:
        raise LispError("three-statement-model: the model already has a line called %s" % ", ".join(clash))


def credit_tabs(the_model):
    """The Credit Losses and FDIC Call Reports tabs of a bank model that has the FDIC's loan book."""
    check_names(the_model)
    fdic = FdicTab(the_model.loan_book, the_model)
    return [CreditTab(the_model.loan_book, the_model, fdic).sheet(), fdic.sheet()]


def charge_off_formula(the_model, i):
    """The forecast's net charge-off rate in period i: the chosen scenario's for the periods of stress, the base
    scenario's after (the period number is in row 5 of the formula's column)."""
    return "=IF(%s$%d<stress_periods,chosen_loss_rate,base_loss_rate)" % (column(i + 1), model.PERIOD_NUMBER_ROW)


def capital_ratios(the_model):
    """The banks' common equity tier 1 ratio at the end of each period the model reports, from the FDIC (None where
    it has no report for that date)."""
    book = the_model.loan_book
    ratios = []
    for i in range(the_model.history_count):
        common_equity, risk_weighted = book.capital(the_model.ends[i].strftime("%Y%m%d"))
        ratios.append(common_equity / risk_weighted if common_equity is not None and risk_weighted else None)
    return ratios


def notes(the_model):
    """The Notes tab's section on the FDIC's data and the scenarios."""
    book = the_model.loan_book
    lines = [
        "Credit losses by type of loan (the Credit Losses and FDIC Call Reports tabs)",
        "The FDIC's Call Reports of the company's banks, added up: %s. The SEC's numbers are the holding company's, which may have loans outside its banks; the rates found from the banks' are used on the holding company's loans." % book.bank_names(),
        "The forecast's net charge-off rate (Assumptions tab) is the Credit Losses tab's: the chosen scenario's for the periods of stress, the base scenario's after. The provision is the charge-offs plus the growth of the allowance, so a worse scenario lowers net income, equity, and the common equity tier 1 ratio on the Balance Sheet.",
        "The allowance stays the percentage of loans assumed, though a bank expecting losses would raise it at the start (the provision would come sooner); interest is still earned on the loans that default. Both make the forecast a little kinder than it would be.",
        "A bank's history is the history of the banks it owns now, under their own certificates: banks it bought keep theirs, so the loans may jump in the year of a purchase. The rates are what matter here.",
    ]
    if has_capital(book, the_model):
        lines.append("The common equity tier 1 ratio of a forecast period is the banks' capital at %s plus the growth of the company's equity since, over the banks' risk-weighted assets grown with the company's loans since. It is an estimate: the holding company's own ratio (in its filings with the Federal Reserve) differs a little." % lisp_fdic.report_date(capital_date(book, the_model)).date.isoformat())
    return lines
