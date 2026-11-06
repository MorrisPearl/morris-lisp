# morris-lisp

A Lisp interpreter for investment analysis, written in Python, in
`lisp_interp/`. It gets data -- prices, option chains, and accounts from
Schwab and tastytrade; economic and financial data from FRED, the SEC, the
FDIC, the BLS, the BEA, the Census Bureau, and Alpha Vantage; any web API,
CSV files, and SQLite -- as tables, and models it: regression, simulated
prices and portfolios, option prices and the volatility smile, rates and
mortgages, charts, and maps. The code is meant to be read and understood.

## Getting started

It needs Python 3 and `numpy`; `ipykernel` for Jupyter, `matplotlib` for
charts, and `pandas`, `ipywidgets` and `ipydatagrid` for widgets.

It is usually used in a Jupyter notebook. Install the kernel once:

    cd lisp_interp
    python3 install_lisp_kernel.py           # a "morris_lisp" Jupyter kernel

then choose "morris_lisp" in Jupyter's kernel picker; every cell is Lisp.
It also runs at a console, or on a file:

    python3 lisp_interpreter.py              # the console
    python3 lisp_interpreter.py file.lsp     # run a file

and from another Python program, with `lisp_interp/lisp_runner.py`:
`import lisp_runner; lisp_runner.run_file("file.lsp")` runs a file and
returns the value of its last form.

The data functions read their keys from a credentials file, a JSON object
such as `{"fred_api_key": "...", "sec_user_agent": "Jane Smith jane@example.com"}`,
whose path is their first argument. Keep it out of the repository.

## Where to read

The manuals are in `doc/`. Their examples are run by the tests, so what
they say the interpreter does is what it does.

- `doc/lisp_interpreter_reference.md` -- the language: its syntax, special
  forms and macros, and the general builtins (lists, strings, vectors and
  statistics, tables, dates, charts, input and output, the debugger).
  "Running it" says how to use it in a notebook, and "How the code is
  organized" says which file has what.
- `doc/lisp_library_reference.md` -- the library: getting data,
  statistical models, dates and cash flows, and investments. Its first
  chapter, "Where things are", is a map.
- `doc/lisp_example_programs.md` -- the example programs in
  `lisp_interp/examples/` (a chess player, a SQL interpreter, ELIZA, a
  Prolog, models of mortgages, and a script for each part of the library),
  and the programming techniques they show.
- `doc/lisp_cmo_manual.md` -- structured deals (CMOs): how to build one,
  how each kind of bond is paid, and how they are priced.
- `doc/lisp_paths_manual.md` -- yield curves (the Treasury's, the Fed's,
  SOFR futures'), and simulated paths: of interest rates, from today's curve
  and option prices, and of investment prices, from their own history. What
  you do to make them, and what the program does.
- `doc/lisp_forecasting_manual.md` -- forecasting questions, such as Good
  Judgment Open's: the chance of each range of a number, "before the date"
  chances, and combining and scoring forecasts.
- `doc/lisp_macro_models_manual.md` -- macroeconomic models run with Dynare:
  what happens to GDP, inflation, wages and the Fed's rate after an oil
  shock, scenarios, and what estimating a model from US data means.
- `doc/economic_data_guide.md` -- which agency publishes what data, and
  which function gets it.

The tests, in `lisp_interp/tests/`: `cd lisp_interp; python3 -m unittest discover -s tests`
(or `python3 -m pytest -q tests`).

## The rest of this repository

Other projects, some of which the interpreter uses:

- `simplex/` -- the simplex method, for the interpreter's linear programming.
- `term_structure/` -- the two-factor model of interest rates behind the interpreter's `simulate-rate-paths` and `calibrate-rate-model`: paths of
  rates that start on the Treasury's curve, and the model fitted to SOFR and 10-year note option prices.
- `tasty_api/` -- a desktop app for CME futures options and relative value, from tastytrade.
- `strats/` -- a desktop app for stratification reports.
- `load_freddie_data/` -- builds a dataset from Freddie Mac's loan-level data.
- `fec_data/` -- loads the FEC's bulk campaign-finance files into a database.
- `zhvi_data/`, `spy_holdings/`, `chalkboard_chart/`, `gmail_from_header_export/` -- smaller tools.
