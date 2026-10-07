# morris-lisp

A Lisp interpreter for investment analysis, written in Python, in
`lisp_interp/`. It gets data -- prices, option chains, and accounts from
Schwab and tastytrade; economic and financial data from FRED, the SEC, the
FDIC, the BLS, the BEA, the Census Bureau, and Alpha Vantage; any web API,
CSV files, and SQLite -- as tables, and models it: regression, simulated
prices and portfolios, option prices and the volatility smile, rates and
mortgages, charts, and maps. The code is meant to be read and understood.

## Getting started

It needs Python 3 and `numpy`; `matplotlib` for charts, `PyQt6` for the
GUI, and `ipykernel` and `pandas` for Jupyter.

    cd lisp_interp
    python3 lisp_interpreter.py              # the GUI (or the console, without PyQt6)
    python3 lisp_interpreter.py -            # the console
    python3 lisp_interpreter.py file.lsp     # run a file
    python3 install_lisp_kernel.py           # once, for a "morris_lisp" Jupyter kernel

The data functions read their keys from a credentials file, a JSON object
such as `{"fred_api_key": "...", "sec_user_agent": "Jane Smith jane@example.com"}`,
whose path is their first argument. Keep it out of the repository.

## Where to read

- `lisp_interp/lisp_interpreter_reference.md` -- the manual: every function,
  with examples that the tests run. Its chapter "Investment analysis: where
  things are" is a map, and "How the code is organized" says which file has
  what.
- `lisp_interp/economic_data_guide.md` -- which agency publishes what data,
  and which function gets it.
- `lisp_interp/examples/` -- programs that use it, such as
  `investment_paths_example.lsp` and `vol_smile_example.lsp`.

The tests, in `lisp_interp/tests/`: `cd lisp_interp; python3 -m unittest discover -s tests`
(or `python3 -m pytest -q tests`).

## The rest of this repository

Other projects, some of which the interpreter uses:

- `simplex/` -- the simplex method, for the interpreter's linear programming.
- `term_structure/` -- the two-factor SOFR model behind the interpreter's `sofr-*` functions.
- `tasty_api/` -- a desktop app for CME futures options and relative value, from tastytrade.
- `strats/` -- a desktop app for stratification reports.
- `load_freddie_data/` -- builds a dataset from Freddie Mac's loan-level data.
- `fec_data/` -- loads the FEC's bulk campaign-finance files into a database.
- `zhvi_data/`, `spy_holdings/`, `chalkboard_chart/`, `gmail_from_header_export/` -- smaller tools.
