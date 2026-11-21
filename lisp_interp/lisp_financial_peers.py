"""Comparable companies, from the table ticker_industry (ticker, industry) of the database financial_data.db, for the Lisp
interpreter -- and the stocks' market capitalizations and latest prices that go with it, from the table stock_returns
(industry_returns.lsp makes both: see stock-returns-update).

  (comparable-companies "KEY" [:count n :industry i :database path])

When one company is compared with another, who it is compared with decides what the comparison says: a bank held up
against a software company says nothing. A company's peers are the companies that do what it does and are about as big
as it is, so they are chosen this way:

  1. The same industry, as ticker_industry has it (97 of them: "Bank", "Insurance (Prop/Cas.)", "Computer Software",
     "R.E.I.T.", ...). :industry says another, or a list of them: a bank may be "Bank" or "Bank (Regional)".
  2. Trading now: the database has a market capitalization and a price for the stock (a delisted company has none, and
     neither has a Canadian one that Schwab doesn't price).
  3. The nearest in size: by the ratio of the market capitalizations, so that one a third the size and one three times it
     are equally near. A company's multiples, margins, and growth depend on its size, and the nearest in size are the
     likeliest to be run and financed the way it is.

compare-companies (lisp_financial_compare.py) takes the nearest of these in turn that its SEC statements can be used
for, and skips those that are not -- a second share class of the same company (First Citizens has two stocks), a company
that files with the SEC on a form without these numbers, one that reports in another currency, a different kind of
company (a bank among the insurers), or one whose latest report is old -- and says why on its Notes tab.

The database is found in the current folder, or in the data folder of the interpreter's repository, unless :database
(a path) says; the program only reads it.
"""

import difflib
import math
import os
import sqlite3

from lisp_core import LispError, keyword_options
from lisp_data_common import text_list
from lisp_tables import column_vector, make_table_value

DATABASE_NAME = "financial_data.db"
DEFAULT_COUNT = 10                      # comparable-companies: how many to show
MILLION = 1e6


class Stock:
    """A row of ticker_industry, with what stock_returns has for it (None for what it hasn't): its industry, its market
    capitalization in dollars, its last price (and the day of it), and the dividend it pays a year at its current rate."""

    def __init__(self, ticker, industry, market_cap=None, price=None, price_date=None, dividend=None):
        self.ticker, self.industry = ticker, industry
        self.market_cap, self.price, self.price_date, self.dividend = market_cap, price, price_date, dividend

    @property
    def trades(self):
        """Whether it is a stock that trades now: the database has its market capitalization and a price."""
        return bool(self.market_cap) and self.market_cap > 0 and bool(self.price) and self.price > 0


def normal(ticker):
    """A ticker as the database writes it, to find it by: in capitals, a share class after a dot (BRK.B, not BRK-B)."""
    return str(ticker).strip().upper().replace("-", ".").replace("/", ".")


def database_folders():
    """Where the database is looked for: the current folder, and the data folder of the repository."""
    return [os.getcwd(), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")]


def locate_database(given=None):
    """The path of the database, or None if there isn't one: the path given, or the first folder of database_folders
    that has financial_data.db."""
    if given is not None:
        path = os.path.abspath(os.path.expanduser(str(given)))
        return path if os.path.isfile(path) else None
    for folder in database_folders():
        path = os.path.abspath(os.path.join(folder, DATABASE_NAME))
        if os.path.isfile(path):
            return path
    return None


def find_database(given, who):
    """The database's path, or an error that says where it looked."""
    path = locate_database(given)
    if path is None:
        raise LispError("%s: %s" % (who, "there is no database file %s" % given if given is not None else
                                    "no %s in the current folder or the repository's data folder: give :database, the path "
                                    "of the database that has the tables ticker_industry and stock_returns" % DATABASE_NAME))
    return path


def load_stocks(path, who):
    """Every stock of ticker_industry, as {normal ticker: Stock}, with what stock_returns has for it. Without that table
    (the stocks' returns have not been got yet: stock-returns-update) the stocks have no market capitalization."""
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error as problem:
        raise LispError("%s: can't open %s: %s" % (who, path, problem))
    try:
        try:
            industries = connection.execute("SELECT ticker, industry FROM ticker_industry").fetchall()
        except sqlite3.OperationalError:
            raise LispError("%s: %s has no table ticker_industry (ticker, industry)" % (who, path))
        try:
            facts = {str(row[0]): row[1:] for row in connection.execute(
                "SELECT ticker, market_cap, end_price, end_date, dividend FROM stock_returns").fetchall()}
        except sqlite3.OperationalError:
            facts = {}                      # (the stocks' returns have not been got yet)
    finally:
        connection.close()
    # (joined here, not by SQL: ticker_industry's tickers have a numeric affinity, so SQLite cannot use stock_returns's
    # index on them, and the join takes a second)
    rows = [(str(ticker), industry) + tuple(facts.get(str(ticker), (None, None, None, None))) for ticker, industry in industries]
    stocks = {}
    for ticker, industry, market_cap, price, price_date, dividend in rows:
        stocks[normal(ticker)] = Stock(str(ticker), str(industry), market_cap, price, price_date, dividend)
    return stocks


def industries_of(stocks):
    return sorted({stock.industry for stock in stocks.values()})


def chosen_industries(stocks, target, given, who):
    """The industries to look for peers in: those given (:industry, a name or a list: each must be one the table has),
    or the target's own."""
    if given is None:
        return [target.industry]
    wanted = text_list(given, who, ":industry")
    known = industries_of(stocks)
    for name in wanted:
        if name not in known:
            near = difflib.get_close_matches(name, known, n=5, cutoff=0.6) or \
                [industry for industry in known if name.lower() in industry.lower() or industry.lower() in name.lower()]
            raise LispError("%s: ticker_industry has no industry called %s%s" % (
                who, name, " -- did you mean %s?" % ", ".join(near[:5]) if near else
                " (the industries are %s)" % ", ".join(known[:6]) + ", ..."))
    return wanted


def find_target(stocks, ticker, who):
    """The target's Stock: an error if the table does not have it, or has no market capitalization for it to be
    near in size to."""
    target = stocks.get(normal(ticker))
    if target is None:
        raise LispError("%s: %s is not in the table ticker_industry, so its industry is not known: give the companies "
                        "to compare (compare-companies takes a list) or add it to the table" % (who, ticker))
    if not target.market_cap or target.market_cap <= 0:
        raise LispError("%s: the table stock_returns has no market capitalization for %s, so there is nothing to be "
                        "near in size to (stock-returns-update gets them from Schwab): give the companies to compare"
                        % (who, ticker))
    return target


def nearest_in_size(stocks, target, industries):
    """The stocks of the industries that trade now, other than the target, the nearest in market capitalization first:
    the smallest ratio of the larger to the smaller of the two market capitalizations."""
    found = [stock for stock in stocks.values()
             if stock.industry in industries and stock.trades and normal(stock.ticker) != normal(target.ticker)]
    found.sort(key=lambda stock: (abs(math.log(stock.market_cap / target.market_cap)), stock.ticker))
    return found


def comparable_companies(ticker, *options):
    """(comparable-companies ticker [:count n :industry i :database path]) -- the stocks in the same industry as the
    ticker, nearest in size first: a table of ticker, industry, market-cap (in millions of dollars), relative-size (its
    market capitalization over the ticker's: 1.1 is a tenth bigger, 0.5 half the size), price, and price-date. The
    industries and market capitalizations are from the tables ticker_industry and stock_returns of the database
    financial_data.db, found in the current folder or the repository's data folder, or at :database. :count is how many
    (10, unless you say); :industry, a name or a list of them, looks in those industries instead of the ticker's own
    (banks are in both "Bank" and "Bank (Regional)"). Only stocks that trade now are listed -- those with a market
    capitalization and a price. compare-companies with :peers chooses from these the ones its SEC statements can be
    used for."""
    who = "comparable-companies"
    options = keyword_options(options, ["count", "industry", "database"], who)
    count = options.get("count", DEFAULT_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise LispError("%s: :count is a whole number of companies" % who)
    stocks = load_stocks(find_database(options.get("database"), who), who)
    target = find_target(stocks, ticker, who)
    industries = chosen_industries(stocks, target, options.get("industry"), who)
    found = nearest_in_size(stocks, target, industries)[:count]
    columns = [
        ("ticker", [stock.ticker for stock in found]),
        ("industry", [stock.industry for stock in found]),
        ("market-cap", [stock.market_cap / MILLION for stock in found]),
        ("relative-size", [stock.market_cap / target.market_cap for stock in found]),
        ("price", [float(stock.price) for stock in found]),
        ("price-date", [str(stock.price_date) if stock.price_date else None for stock in found]),
    ]
    return make_table_value([(name, column_vector(values)) for name, values in columns])


BUILTINS = {
    "comparable-companies": comparable_companies,
}
