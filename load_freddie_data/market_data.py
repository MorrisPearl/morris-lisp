"""
market_data.py

What the market was doing, month by month, that a loan's prepayments are
compared with:

  MortgageRates  the average, over a calendar month, of Freddie Mac's weekly
                 survey (PMMS) of the rate on a new 30-year fixed-rate
                 mortgage, from a CSV with the columns observation_date and
                 MORTGAGE30US (as FRED gives it)
  HomePrices     the Zillow Home Value Index, from zhvi_data/zhvi.db: for a
                 3-digit zip code, the average of the index of the zip codes
                 that start with it, and for the whole country

A month is the text "YYYYMM", as Freddie's files have it.
"""

import csv
import sqlite3
from collections import defaultdict


def add_months(month, n):
    """The month n months after month ("YYYYMM"); n can be negative."""
    count = int(month[:4]) * 12 + int(month[4:]) - 1 + n
    return "%04d%02d" % (count // 12, count % 12 + 1)


def months_between(earlier, later):
    """How many months later is after earlier."""
    return (int(later[:4]) - int(earlier[:4])) * 12 + int(later[4:]) - int(earlier[4:])


class MortgageRates:
    """The average survey rate (percent) of each calendar month."""

    def __init__(self, csv_path):
        weekly = defaultdict(list)
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["MORTGAGE30US"]:
                    weekly[row["observation_date"][:4] + row["observation_date"][5:7]].append(float(row["MORTGAGE30US"]))
        self.monthly = {month: sum(rates) / len(rates) for month, rates in weekly.items()}

    def rate(self, month):
        """The average survey rate in the month, or None if the survey has none for it."""
        return self.monthly.get(month)


class HomePrices:
    """The Zillow Home Value Index of each month, for 3-digit zip codes and for the United States."""

    def __init__(self, zhvi_db):
        conn = sqlite3.connect(f"file:{zhvi_db}?mode=ro", uri=True)
        totals = defaultdict(float)
        counts = defaultdict(int)
        for key, date, value in conn.execute("SELECT key, date, value FROM zhvi WHERE type = 'Z' AND value IS NOT NULL"):
            index = (key[:3], date[:4] + date[5:7])
            totals[index] += value
            counts[index] += 1
        self.zip3 = {index: totals[index] / counts[index] for index in totals}
        self.country = {date[:4] + date[5:7]: value
                        for date, value in conn.execute("SELECT date, value FROM zhvi WHERE type = 'U' AND value IS NOT NULL")}
        conn.close()

    def change(self, zip3, start, end):
        """How many times what home prices were in the start month they are in the end month, in the 3-digit zip code if the index
        has both months for it, and otherwise in the whole country; None if neither has both."""
        if (zip3, start) in self.zip3 and (zip3, end) in self.zip3:
            return self.zip3[(zip3, end)] / self.zip3[(zip3, start)]
        if start in self.country and end in self.country:
            return self.country[end] / self.country[start]
        return None
