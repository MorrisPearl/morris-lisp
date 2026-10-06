#!/usr/bin/env python3
"""
download_spy_holdings.py

Downloads the daily holdings of the SPDR S&P 500 ETF Trust (SPY) from State
Street (an .xlsx file) and writes them to a CSV file that has just the column
headings and the data rows.

The spreadsheet has a few lines about the fund above the column headings
(fund name, ticker, "as of" date) and pages of legal disclaimers below the
data. Neither is copied to the CSV; the "as of" date is printed instead.

In the spreadsheet a "-" means "no value" (for example SPY's Sector column, or
the ticker of the US DOLLAR cash line). It is written as an empty CSV field.

Usage:
    python3 download_spy_holdings.py
    python3 download_spy_holdings.py --xlsx spy.xlsx --csv spy.csv

Requires openpyxl (pip install openpyxl).
"""

import argparse
import csv
import shutil
import urllib.request
from decimal import Decimal

import openpyxl

URL = ("https://www.ssga.com/us/en/individual/library-content/products/"
       "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx")

# The first cell of the row that holds the column headings.
HEADING_ROW_START = "Name"


def download_file(url, path):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with open(path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)


def plain_number(number):
    """Write a float as a plain decimal: 294213963.0 -> 294213963, 3e-06 -> 0.000003."""
    if number.is_integer():
        return str(int(number))
    return format(Decimal(repr(number)), "f")


def clean_cell(cell):
    if cell == "-":
        return ""
    if isinstance(cell, float):
        return plain_number(cell)
    return cell


def read_holdings(xlsx_path):
    """Return (about_fund, headings, holdings) from the SSGA holdings spreadsheet.

    about_fund is a dict of the lines above the headings, such as
    {"Fund Name:": ..., "Ticker Symbol:": ..., "Holdings:": "As of 05-Oct-2026"}.
    """
    sheet = openpyxl.load_workbook(xlsx_path).active
    rows = sheet.iter_rows(values_only=True)

    # Lines above the column headings.
    about_fund = {}
    for row in rows:
        if row[0] == HEADING_ROW_START:
            break
        if row[0]:
            about_fund[row[0]] = row[1]
    else:
        raise ValueError(f"No row starting with '{HEADING_ROW_START}' found in {xlsx_path}")

    headings = [cell for cell in row if cell is not None]

    # Data rows run up to the first blank row; the disclaimers come after it.
    holdings = []
    for row in rows:
        if all(cell is None for cell in row):
            break
        holdings.append([clean_cell(cell) for cell in row[:len(headings)]])

    if not holdings:
        raise ValueError(f"No holdings found in {xlsx_path}")
    return about_fund, headings, holdings


def write_csv(csv_path, headings, holdings):
    with open(csv_path, "w", newline="", encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(headings)
        writer.writerows(holdings)


def main():
    parser = argparse.ArgumentParser(description="Download SPY holdings and save them as a CSV file.")
    parser.add_argument("--xlsx", default="spy_holdings.xlsx", help="where to save the downloaded spreadsheet")
    parser.add_argument("--csv", default="spy_holdings.csv", help="where to write the CSV file")
    args = parser.parse_args()

    download_file(URL, args.xlsx)
    about_fund, headings, holdings = read_holdings(args.xlsx)
    write_csv(args.csv, headings, holdings)

    print(f"{about_fund.get('Holdings:')}: wrote {len(holdings)} holdings to {args.csv}")


if __name__ == "__main__":
    main()
