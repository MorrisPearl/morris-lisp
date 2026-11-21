"""The valuation rows of compare-companies (lisp_financial_compare.py): the market's view of each company at the share
prices given, against what the company earns, owns, and pays out -- at the bottom of the sheet, below the ratios.

Each row is a formula of the rows above it, in each company's column, so a number can be changed (a price, a share
count) and the multiples follow. A row is one of (see lisp_financial_compare.py):

  ("section", label)
  ("absolute", key, label, None, format)       a number the market gives (the share price, an analyst's estimate)
  ("ratio", key, label, formula)               formula(cell, year) -> text, where cell(key) is the address of a row's cell in
                                               this company's column and year is 365 over the days of the period
  ("implied", key, label, formula)             the target's column only: formula(cell, median, year) -> text, where
                                               median(key) is the address of a row's cell in the peers' median column
  ("implied-median", key, label)               the median of the implied rows above it; ("implied-gap", ...) how far it is
                                               from the share price

A MULTIPLE is empty where its denominator is not above 0: a company that lost money has no price / earnings, and a
negative one would mean nothing. A YIELD is the inverse of a multiple, and has no such gap: it says what a company that
lost money earns on its price (less than nothing), which is how to compare it with the others.

The measures, in the order of the sheet, for an ordinary company:

  Market value and enterprise value (market value + debt - cash and short-term investments)
  Enterprise value over a year's EBITDA, operating income (EBIT), revenue, and free cash flow: what the whole business,
      debt and all, is priced at, which compares companies with different debt.
  Price over sales, earnings, and cash earnings (net income plus depreciation and amortization, which for a REIT is
      close to its funds from operations, FFO, the measure its price is usually read against).
  Earnings yield and free cash flow yield; dividend, buyback, and shareholder yield (dividends and buybacks over market
      value): the cash returned, for those that pay it.
  Price over book value and tangible book value (without goodwill and intangibles).
  Return on invested capital (operating income after taxes over the plant, goodwill, intangibles, receivables, and
      inventory less payables the business uses) and enterprise value over that capital: a business that earns
      more on its capital is worth more per dollar of it.
  PEG: price over earnings, over the growth of earnings per share in points (annual periods; empty where earnings fell).

A bank's are those a bank is priced by: price over earnings, book, and tangible book value (its tangible common equity,
without preferred stock, minority interests, goodwill, and intangibles), the return on that equity, market value over a
year's profit before credit losses (the cushion that takes the losses), and over its deposits. An insurer's: price over
earnings, book, tangible book, and premiums.

With :estimates, what analysts expect for the coming fiscal years: earnings per share, price over them (forward P/E),
the growth expected, and the forward PEG.

With peers chosen (:peers), the target's column shows what the target would be worth at the peers' median multiples.
"""

# the first-column row keys that are amounts in millions, not ratios
MONEY_KEYS = ("market-value", "enterprise-value", "tangible-common-equity", "tangible-book-value")
MULTIPLES = ("ev-to-ebitda", "ev-to-ebit", "ev-to-revenue", "ev-to-free-cash-flow", "ev-to-invested-capital",
             "price-to-sales", "price-to-earnings", "price-to-cash-earnings", "price-to-book", "price-to-tangible-book",
             "price-to-ppnr", "market-to-deposits", "price-to-premiums", "peg", "forward-price-to-earnings",
             "forward-price-to-earnings-2", "forward-peg")
PERCENT_KEYS = ("earnings-yield", "free-cash-flow-yield", "dividend-yield", "buyback-yield", "shareholder-yield", "roic",
                "return-on-tangible-equity", "expected-eps-growth")
TAX_RATE_MOST = 0.40                    # (the most of a company's tax rate that its return on invested capital takes off)


def quotient(numerator, denominator):
    """A yield-like ratio: numerator over denominator (each a function of (cell, year) that gives an expression), or empty."""
    return lambda cell, year: '=IFERROR((%s)/(%s),"")' % (numerator(cell, year), denominator(cell, year))


def multiple(numerator, denominator):
    """A multiple: numerator over denominator, empty where the denominator is not above 0."""
    return lambda cell, year: '=IFERROR(IF((%s)>0,(%s)/(%s),""),"")' % (
        denominator(cell, year), numerator(cell, year), denominator(cell, year))


def key(name):
    """The expression for a row's cell."""
    return lambda cell, year: cell(name)


def per_year(*names):
    """The sum of rows, as a year's: (a+b)*year."""
    return lambda cell, year: "(%s)*%s" % ("+".join(cell(name) for name in names), year)


def negative_per_year(*names):
    """What a company paid out (a cash flow below 0) over a year, as a positive number."""
    return lambda cell, year: "-(%s)*%s" % ("+".join(cell(name) for name in names), year)


def market_value():
    return key("market-value")


def sum_of(*names):
    """Rows added up: a name that begins with a minus sign is taken off."""
    def expression(cell, year):
        text = ""
        for name in names:
            text += ("-" if name.startswith("-") else "+") + cell(name.lstrip("-"))
        return text.lstrip("+")
    return expression


# --- the rows every kind of company has: the price, the market value, and what it pays out

def price_rows():
    return [
        ("section", "Valuation (at the share prices given)"),
        ("absolute", "price", "Share price", None, "per-share"),
        ("ratio", "market-value", "Market value of the shares, millions (price x diluted shares)",
         lambda cell, year: '=IFERROR(%s*%s,"")' % (cell("price"), cell("shares"))),
    ]


def payout_rows():
    return [
        ("ratio", "dividend-yield", "Dividend yield (a year's dividends paid / market value)",
         quotient(negative_per_year("dividends"), market_value())),
        ("ratio", "buyback-yield", "Buyback yield (a year's shares repurchased / market value)",
         quotient(negative_per_year("repurchases"), market_value())),
        ("ratio", "shareholder-yield", "Shareholder yield (dividends and buybacks / market value)",
         quotient(negative_per_year("dividends", "repurchases"), market_value())),
    ]


def earnings_rows():
    return [
        ("ratio", "price-to-earnings", "Price / a year's earnings per share (empty if it is not above 0)",
         multiple(key("price"), per_year("eps"))),
        ("ratio", "earnings-yield", "Earnings yield (a year's earnings per share / price)",
         quotient(per_year("eps"), key("price"))),
    ]


# --- an ordinary company

def general_rows():
    enterprise = key("enterprise-value")
    ebitda = per_year("operating-income", "depreciation", "amortization")
    free_cash_flow = per_year("operating-cash-flow", "capital-expenditures")
    tangible_book = sum_of("equity", "-goodwill", "-intangible-assets")
    capital_used = sum_of("property-plant-equipment", "goodwill", "intangible-assets", "receivables", "inventory",
                          "-accounts-payable")

    def roic(cell, year):
        tax = "MIN(MAX(%s,0),%g)" % (cell("tax-rate"), TAX_RATE_MOST)
        return '=IFERROR(%s*(1-%s)/(%s),"")' % (per_year("operating-income")(cell, year), tax, capital_used(cell, year))

    return price_rows() + [
        ("ratio", "enterprise-value", "Enterprise value, millions (market value + debt - cash and short-term investments)",
         lambda cell, year: '=IFERROR(%s+%s+%s-%s-%s,"")' % (cell("market-value"), cell("current-debt"), cell("long-term-debt"),
                                                             cell("cash"), cell("short-term-investments"))),
        ("ratio", "ev-to-ebitda", "Enterprise value / a year's EBITDA (operating income + depreciation and amortization)",
         multiple(enterprise, ebitda)),
        ("ratio", "ev-to-ebit", "Enterprise value / a year's operating income (EBIT)",
         multiple(enterprise, per_year("operating-income"))),
        ("ratio", "ev-to-revenue", "Enterprise value / a year's revenue", multiple(enterprise, per_year("revenue"))),
        ("ratio", "ev-to-free-cash-flow", "Enterprise value / a year's free cash flow (cash from operations less capital "
         "expenditures)", multiple(enterprise, free_cash_flow)),
        ("ratio", "price-to-sales", "Price / sales (market value / a year's revenue)",
         multiple(market_value(), per_year("revenue"))),
    ] + earnings_rows() + [
        ("ratio", "price-to-cash-earnings", "Price / cash earnings (market value / a year's net income plus depreciation "
         "and amortization: for a REIT, near price / funds from operations)",
         multiple(market_value(), per_year("net-income", "depreciation", "amortization"))),
        ("ratio", "free-cash-flow-yield", "Free cash flow yield (a year's free cash flow / market value)",
         quotient(free_cash_flow, market_value())),
    ] + payout_rows() + [
        ("ratio", "price-to-book", "Price / book value (market value / equity; empty if it is not above 0)",
         multiple(market_value(), key("equity"))),
        ("ratio", "price-to-tangible-book", "Price / tangible book value (market value / equity less goodwill and "
         "intangibles; empty if that is not above 0)", multiple(market_value(), tangible_book)),
        ("ratio", "roic", "Return on invested capital (a year's operating income after taxes / plant, goodwill, intangibles, "
         "receivables and inventory, less payables)", roic),
        ("ratio", "ev-to-invested-capital", "Enterprise value / that invested capital", multiple(enterprise, capital_used)),
    ]


def growth_rows():
    """PEG (for annual periods: it needs the earnings per share of the year before, which the sheet has as a row)."""
    def peg(cell, year):
        """Price over earnings over the growth in points: empty unless earnings are growing from a profit (a negative PEG
        means nothing)."""
        return '=IFERROR(IF(AND(%s>0,%s>%s),%s/((%s/%s-1)*100),""),"")' % (
            cell("eps-before"), cell("eps"), cell("eps-before"), cell("price-to-earnings"), cell("eps"), cell("eps-before"))
    return [
        ("absolute", "eps-before", "Earnings per share, diluted, the year before", None, "per-share"),
        ("ratio", "peg", "PEG: price / earnings, over the growth of earnings per share in points (under 1 is cheap for "
         "the growth)", peg),
    ]


# --- a bank

def bank_rows():
    tangible_equity = key("tangible-common-equity")
    return price_rows() + earnings_rows() + [
        ("ratio", "price-to-book", "Price / book value (market value / equity; empty if it is not above 0)",
         multiple(market_value(), key("equity"))),
        ("ratio", "tangible-common-equity", "Tangible common equity, millions (equity less preferred stock, minority "
         "interests, goodwill, and intangibles)", lambda cell, year: "=%s-%s-%s" % (
             cell("equity"), cell("preferred-and-minority"), cell("goodwill-and-intangibles"))),
        ("ratio", "price-to-tangible-book", "Price / tangible book value (market value / tangible common equity; empty "
         "if that is not above 0)", multiple(market_value(), tangible_equity)),
        ("ratio", "return-on-tangible-equity", "Return on tangible common equity (a year's net income to common "
         "shareholders / tangible common equity)", quotient(per_year("income-to-common"), tangible_equity)),
        ("ratio", "price-to-ppnr", "Market value / a year's profit before credit losses (pre-provision net revenue)",
         multiple(market_value(), per_year("pre-provision-profit"))),
        ("ratio", "market-to-deposits", "Market value / deposits (what the market pays for a bank's deposit franchise)",
         multiple(market_value(), key("deposits"))),
    ] + payout_rows()


# --- an insurer

def insurer_rows():
    return price_rows() + earnings_rows() + [
        ("ratio", "price-to-book", "Price / book value (market value / equity; empty if it is not above 0)",
         multiple(market_value(), key("equity"))),
        ("ratio", "tangible-book-value", "Tangible book value, millions (equity less goodwill and intangibles)",
         lambda cell, year: "=%s-%s-%s" % (cell("equity"), cell("goodwill"), cell("intangible-assets"))),
        ("ratio", "price-to-tangible-book", "Price / tangible book value (market value / tangible book value; empty if "
         "that is not above 0)", multiple(market_value(), key("tangible-book-value"))),
        ("ratio", "price-to-premiums", "Market value / a year's premiums earned",
         multiple(market_value(), per_year("premiums-earned"))),
    ] + payout_rows()


# --- analysts' estimates

def forward_rows():
    """The estimates of earnings per share of the next two fiscal years (alpha-vantage-estimates), and what they say."""
    def growth(cell, year):
        return '=IFERROR(IF(%s>0,%s/%s-1,""),"")' % (cell("eps"), cell("eps-forward-1"), cell("eps"))

    def forward_peg(cell, year):
        return '=IFERROR(IF(%s>0,%s/(%s*100),""),"")' % (cell("expected-eps-growth"), cell("forward-price-to-earnings"),
                                                          cell("expected-eps-growth"))
    return [
        ("section", "Analysts' estimates of earnings per share (Alpha Vantage)"),
        ("absolute", "eps-forward-1", "Estimate for the next fiscal year (not yet reported)", None, "per-share"),
        ("absolute", "eps-forward-2", "Estimate for the fiscal year after that", None, "per-share"),
        ("ratio", "expected-eps-growth", "Growth of earnings per share the estimate expects, over the last period "
         "reported", growth),
        ("ratio", "forward-price-to-earnings", "Price / the estimate for the next fiscal year (forward P/E)",
         multiple(key("price"), key("eps-forward-1"))),
        ("ratio", "forward-price-to-earnings-2", "Price / the estimate for the fiscal year after that",
         multiple(key("price"), key("eps-forward-2"))),
        ("ratio", "forward-peg", "Forward PEG: forward P/E over the growth expected in points", forward_peg),
    ]


# --- what the target would be worth at the peers' median multiples

def priced_at(median_key, metric, per_share=False):
    """An implied row's formula: the price per share at the peers' median of the multiple, for a multiple of the
    market value (a price / book, a market value / deposits): the median times the target's metric over its shares; or,
    if the metric is already per share (the earnings per share), the median times it."""
    def formula(cell, median, year):
        shares = "" if per_share else "/%s" % cell("shares")
        return '=IFERROR(IF((%s)>0,%s*(%s)%s,""),"")' % (metric(cell, year), median(median_key), metric(cell, year), shares)
    return formula


def priced_at_enterprise(median_key, metric):
    """The same for a multiple of the enterprise value: the median times the metric, less the debt, plus the cash."""
    def formula(cell, median, year):
        return '=IFERROR(IF((%s)>0,(%s*(%s)-%s-%s+%s+%s)/%s,""),"")' % (
            metric(cell, year), median(median_key), metric(cell, year), cell("current-debt"), cell("long-term-debt"),
            cell("cash"), cell("short-term-investments"), cell("shares"))
    return formula


def implied_summary():
    return [
        ("implied-median", "implied-median", "Median of these prices"),
        ("implied-gap", "implied-gap", "That median against the share price (above 0: cheaper than its peers)"),
    ]


def implied_general_rows():
    return [
        ("section", "What the target would be worth at the peers' median multiples (per share)"),
        ("implied", "implied-price-to-earnings", "At the peers' median price / earnings",
         priced_at("price-to-earnings", per_year("eps"), per_share=True)),
        ("implied", "implied-ev-to-ebitda", "At the peers' median enterprise value / EBITDA",
         priced_at_enterprise("ev-to-ebitda", per_year("operating-income", "depreciation", "amortization"))),
        ("implied", "implied-ev-to-ebit", "At the peers' median enterprise value / operating income",
         priced_at_enterprise("ev-to-ebit", per_year("operating-income"))),
        ("implied", "implied-ev-to-revenue", "At the peers' median enterprise value / revenue",
         priced_at_enterprise("ev-to-revenue", per_year("revenue"))),
        ("implied", "implied-ev-to-free-cash-flow", "At the peers' median enterprise value / free cash flow",
         priced_at_enterprise("ev-to-free-cash-flow", per_year("operating-cash-flow", "capital-expenditures"))),
        ("implied", "implied-price-to-book", "At the peers' median price / book value",
         priced_at("price-to-book", key("equity"))),
    ] + implied_summary()


def implied_bank_rows():
    return [
        ("section", "What the target would be worth at the peers' median multiples (per share)"),
        ("implied", "implied-price-to-earnings", "At the peers' median price / earnings",
         priced_at("price-to-earnings", per_year("eps"), per_share=True)),
        ("implied", "implied-price-to-book", "At the peers' median price / book value",
         priced_at("price-to-book", key("equity"))),
        ("implied", "implied-price-to-tangible-book", "At the peers' median price / tangible book value",
         priced_at("price-to-tangible-book", key("tangible-common-equity"))),
        ("implied", "implied-price-to-ppnr", "At the peers' median market value / profit before credit losses",
         priced_at("price-to-ppnr", per_year("pre-provision-profit"))),
        ("implied", "implied-market-to-deposits", "At the peers' median market value / deposits",
         priced_at("market-to-deposits", key("deposits"))),
    ] + implied_summary()


def implied_insurer_rows():
    return [
        ("section", "What the target would be worth at the peers' median multiples (per share)"),
        ("implied", "implied-price-to-earnings", "At the peers' median price / earnings",
         priced_at("price-to-earnings", per_year("eps"), per_share=True)),
        ("implied", "implied-price-to-book", "At the peers' median price / book value",
         priced_at("price-to-book", key("equity"))),
        ("implied", "implied-price-to-tangible-book", "At the peers' median price / tangible book value",
         priced_at("price-to-tangible-book", key("tangible-book-value"))),
        ("implied", "implied-price-to-premiums", "At the peers' median market value / premiums earned",
         priced_at("price-to-premiums", per_year("premiums-earned"))),
    ] + implied_summary()


VALUATION_ROWS = {"general": general_rows, "bank": bank_rows, "insurer": insurer_rows}
IMPLIED_ROWS = {"general": implied_general_rows, "bank": implied_bank_rows, "insurer": implied_insurer_rows}


def rows_for(kind, period, estimates, peers):
    """The valuation rows to add to the bottom of a comparison of this kind: the market's rows, PEG (an ordinary
    company's, annual periods), the analysts' estimates (:estimates), and what the target would be worth at its peers'
    medians (the target's peers having been chosen)."""
    rows = VALUATION_ROWS[kind]()
    if kind == "general" and period == "annual":
        rows += growth_rows()
    if estimates:
        rows += forward_rows()
    if peers:
        rows += IMPLIED_ROWS[kind]()
    return rows
