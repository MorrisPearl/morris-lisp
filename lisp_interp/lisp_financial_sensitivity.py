"""Monte Carlo (sensitivity) analysis in a Google Sheet.

  (sensitivity-workbook creds "My model" [:runs 1000])   a new spreadsheet with an empty Sensitivity tab and the macro
  (sensitivity-macro)                                    the macro's text (Google Apps Script)

A three-statement model with a DCF tab (lisp_financial_model.py) has these two tabs already, filled in for its DCF:

  Sensitivity         what to vary and what to record.  A table of inputs -- Input (a named range or a cell address),
                      Distribution (fourteen, from uniform to Poisson), Low, Average, High, Shape -- a table of the
                      possible values of the inputs that are "custom", a table of correlations between pairs of inputs,
                      a table of outputs, the number of runs, and a random seed.  Below them the macro writes the
                      results: a row for each run with the value of every input and every output, and above the rows a
                      summary of each column (mean, percentiles, lowest, highest).
  Distributions       what each distribution does with Low, Average, High, and Shape.
  Sensitivity Macro   the macro, and how to install it.

The macro (apps_script/sensitivity.gs) does not know anything about the three-statement model.  It draws the inputs, types
them into their cells, lets the spreadsheet work out the rest, and reads the outputs, as many times as asked, so it
does Monte Carlo analysis of any spreadsheet that has a Sensitivity tab laid out like this one.

Why a macro and not Python: the model is formulas in the sheet, and this program cannot make the sheet recalculate
except by changing a cell and reading the result, one request to Google for each, which would take minutes for a
thousand runs and need the program running.  The macro runs inside Google.

Installing the macro needs the person who owns the sheet: Google does not let a program add a script to a sheet unless
it has been given the right to run scripts as the user, which google-login does not ask for.  So the macro's text is
in a cell of the Sensitivity Macro tab to copy into Extensions > Apps Script (a cell, not many rows: copying rows puts
quotation marks around the lines that have them).

The inputs of a model's Sensitivity tab are formulas, so that they follow the model: Average is the model's own assumption
(=beta), and Low and High are a little either side of it (=D12-0.25).  Type numbers over them to choose your own.
"""

import os

from lisp_core import LispError, LispString, keyword_options
import lisp_financial_model as model
import lisp_google

ASSUMPTIONS, DCF = model.ASSUMPTIONS, model.DCF
SENSITIVITY, MACRO, DISTRIBUTIONS_TAB = "Sensitivity", "Sensitivity Macro", "Distributions"
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_script", "sensitivity.gs")
MOST_CELL_CHARACTERS = 50000            # what one cell of a Google sheet can hold
DISTRIBUTIONS = ("uniform", "triangular", "pert", "normal", "lognormal", "exponential", "gamma", "weibull", "beta",
                 "discrete uniform", "bernoulli", "binomial", "poisson", "custom")
INPUT_SLOTS, CUSTOM_SLOTS, CORRELATION_SLOTS, OUTPUT_SLOTS = 12, 8, 8, 12        # rows to fill in, at least
DEFAULT_RUNS = 1000
WIDTH = 7                               # columns A to G
COLUMN_WIDTHS = [(0, 0, 330), (1, 1, 190), (2, 5, 90), (6, 6, 520)]

# What each distribution does with the numbers of its row: (name, continuous or discrete, Low, Average, High, Shape, notes)
DISTRIBUTION_HELP = [
    ("uniform", "continuous", "smallest value", "(not used)", "largest value", "(not used)",
     "Every value from Low to High is equally likely."),
    ("triangular", "continuous", "smallest value", "most likely value", "largest value", "(not used)",
     "The chance rises in a straight line from Low to Average and falls in a straight line to High."),
    ("pert", "continuous", "smallest value", "most likely value", "largest value", "(not used)",
     "Like triangular but smoother, with more of the values near Average and fewer in the tails (the curve of project planning). Its mean is (Low + 4 x Average + High) / 6."),
    ("normal", "continuous", "2 deviations below Average; nothing is lower", "mean", "2 deviations above Average; nothing is higher", "(not used)",
     "The bell curve. The deviation is (High - Low) / 4, so about 95% of the values are between Low and High (and, if Average is off center, the mean moves a little when the ends are cut off)."),
    ("lognormal", "continuous", "smallest value (above 0)", "mean", "largest value", "(not used)",
     "Never negative and skewed to the right: many values a bit below Average and a few far above, like prices or anything that grows by percentages. The logarithm of the value is a bell curve with deviation (ln High - ln Low) / 4; nothing is outside Low and High."),
    ("exponential", "continuous", "smallest value (where it starts)", "mean", "largest value (the tail is cut off here)", "(not used)",
     "Waiting times: many small values and a few large ones, the chance of a value falling steadily as it grows. The mean is Average, counting from Low."),
    ("gamma", "continuous", "smallest value (where it starts)", "mean", "largest value (the tail is cut off here)", "bigger than 0: 1 is the exponential; bigger is more bell-shaped, with deviation (Average - Low) / the square root of Shape",
     "Skewed to the right, like the size of a loss or the time until several things have happened."),
    ("weibull", "continuous", "smallest value (where it starts)", "mean", "largest value (the tail is cut off here)", "bigger than 0: below 1 the chance of a value falls steeply at first; 1 is the exponential; above 1 it rises to a hump",
     "Lifetimes and times to failure: above 1, things wear out (the longer they have lasted, the likelier they are to end)."),
    ("beta", "continuous", "smallest value", "mean (between Low and High)", "largest value", "bigger than 0: how tightly the values bunch round Average (2 is very spread out, 50 is tight)",
     "A proportion or a value between two limits, such as a market share or a recovery rate."),
    ("discrete uniform", "discrete", "smallest whole number", "(not used)", "largest whole number", "(not used)",
     "Each whole number from Low to High is equally likely, like a die: 3 to 8 gives 3, 4, 5, 6, 7, or 8."),
    ("bernoulli", "discrete", "the value if it doesn't happen", "mean", "the value if it does happen", "(not used)",
     "Just two values, Low or High. The chance of High is (Average - Low) / (High - Low): with Low 0, High 1, and Average 0.2, it is 1 in 5 runs."),
    ("binomial", "discrete", "smallest whole number", "mean", "largest whole number", "(not used)",
     "Low plus how many of (High - Low) tries succeed, each with the same chance: Low 0, High 20, and Average 6 is how many of 20 prospects buy when 30% do."),
    ("poisson", "discrete", "smallest whole number", "mean", "largest whole number (counts above it are left out)", "(not used)",
     "Low plus a count of events that happen at random, such as defaults or claims in a year; the mean count is Average - Low."),
    ("custom", "discrete", "(not used)", "(not used)", "(not used)", "(not used)",
     "You list the possible values and how likely each is in the Custom values table, like scenarios: a recession at 20%, a base case at 60%, a boom at 20%."),
]

# How the starting Low and High of an assumption follow its Average (which is the model's own number):
# (key of the assumption on the Assumptions tab, distribution, what is added to or done to the Average for Low and High)
ASSUMPTION_SPREADS = [
    ("growth", "triangular", "-0.03", "+0.03"),                 # (revenue growth, if the model is of total revenue)
    ("segment-growth-0", "triangular", "-0.03", "+0.03"),
    ("segment-growth-1", "triangular", "-0.03", "+0.03"),
    ("segment-growth-2", "triangular", "-0.03", "+0.03"),
    ("aum-growth", "triangular", "-0.03", "+0.03"),             # (an asset manager's)
    ("fee-rate", "normal", "*0.9", "*1.1"),
    ("gross-margin", "normal", "-0.02", "+0.02"),
]
# and the DCF tab's: (key, distribution, Low, High, number format, what it is)
DCF_SPREADS = [
    ("beta", "triangular", "-0.25", "+0.25", "decimal", "Equity beta (DCF tab)"),
    ("risk-premium", "normal", "-0.01", "+0.01", "percent", "Equity risk premium (DCF tab)"),
    ("terminal-growth", "uniform", "-0.01", "+0.01", "percent", "Growth of free cash flow after the forecast, forever (DCF tab)"),
]
DCF_OUTPUTS = [
    ("sum-present-values", "Present value of the forecast free cash flow"),
    ("present-terminal-value", "Present value of the terminal value"),
    ("enterprise-value", "Enterprise value"),
    ("terminal-share", "Terminal value, as a share of the enterprise value"),
    ("equity-value", "Equity value"),
    ("value-per-share", "Value per share"),
    ("against-price", "Value compared with the share price"),
]


# ---------------------------------------------------------------------------
# The macro
# ---------------------------------------------------------------------------

def macro_text():
    """The macro, as the text of apps_script/sensitivity.gs."""
    with open(SCRIPT_PATH, encoding="utf-8") as script:
        return script.read()


def macro_tab():
    """The tab with the macro in a cell, and how to put it in the spreadsheet."""
    text = macro_text()
    if len(text) > MOST_CELL_CHARACTERS:
        raise LispError("sensitivity: the macro is longer than a cell of a Google sheet can hold")
    instructions = [
        "Install the macro once in this spreadsheet:",
        "1. Choose Extensions > Apps Script. A window opens with a file called Code.gs.",
        "2. Select everything in Code.gs and delete it.",
        "3. Come back here, double-click the cell below the heading The script, press Ctrl+A (Cmd+A on a Mac) to select its text, and copy it. Paste it into Code.gs and click the Save icon.",
        "4. Reload this spreadsheet. A Sensitivity menu appears beside Help. The first time you choose Sensitivity > Run Monte Carlo, Google asks you to allow the script: it is your own, so choose Advanced, then Go to the project (unsafe), then Allow.",
        "5. For a button instead of the menu: Insert > Drawing, draw a button, Save and Close, click the three dots on it, choose Assign script, and type runMonteCarlo.",
        "The cell is the way to copy it because copying several rows puts quotation marks around the lines that have them.",
        "The same script works for any spreadsheet that has a tab called Sensitivity laid out like the one here: copy that tab to the other spreadsheet (right-click its name, Copy to) and install the script there. The name of the tab is at the top of the script (SHEET_NAME).",
    ]
    rows = [[("Sensitivity macro (Google Apps Script)", ("title",))], [None]]
    rows += [[(line, ("bold",) if number == 0 else ("wrap",))] for number, line in enumerate(instructions)]
    rows += [[None], [("The script", ("section",))], [(text, ())]]
    return {"name": MACRO, "cells": rows, "widths": [(0, 0, 900)]}


# ---------------------------------------------------------------------------
# The Sensitivity tab
# ---------------------------------------------------------------------------

def value_cell(value, number_format=None):
    """A cell to fill in, yellow: a number (blue), or a formula (black), or empty."""
    styles = ["input-formula" if isinstance(value, str) and value.startswith("=") else "input"]
    if number_format:
        styles.append(number_format)
    return (value, tuple(styles))


def section_row(title, labels=()):
    """A title row in column A, shaded across the tab, and the header row under it."""
    title_row = [(title, ("section",))] + [(None, ("section",))] * (WIDTH - 1)
    header_row = [(label, ("bold",)) for label in labels] + [None] * (WIDTH - len(labels))
    return [title_row, header_row]


def sensitivity_tab(inputs=(), outputs=(), correlations=(), runs=DEFAULT_RUNS, seed=None, title="Sensitivity analysis"):
    """The Sensitivity tab, as lisp_google.google_workbook takes it.
      inputs        (name, distribution, low, average, high, shape, what it is, number format): the name of a range or
                    a cell address; low, average, and high numbers or formulas (in which {row} is the input's own row,
                    so that Low can be =D{row}-0.25); the last three may be left off
      outputs       (name, what it is)
      correlations  (first input's name, second input's name, correlation)
    Rows are left empty to add more, and so is the table of custom values."""
    rows, first_row = [], {}

    def add(*new_rows):
        rows.extend(new_rows)

    def pad(row):
        return list(row) + [None] * (WIDTH - len(row))

    add([(title, ("title",))],
        [("Choose the cells to vary and the cells to record, then Sensitivity > Run Monte Carlo (the macro is on the Sensitivity Macro tab). Each run draws a value for every input, recalculates the spreadsheet, and records the inputs and the outputs below Results.", ("italic",))],
        [("Choose each input's distribution from the list. Whatever it is, nothing is lower than Low or higher than High. The Distributions tab says what Low, Average, High, and Shape mean for each: uniform, triangular, pert, normal, lognormal, exponential, gamma, weibull, beta, discrete uniform, bernoulli, binomial, poisson, and custom (your own values and chances, in the Custom values table).", ("italic",))],
        [("An input or output is a named range (Data > Named ranges) or a cell address such as DCF!B9. The macro types each draw into the input's cell, and puts back its number or formula at the end. A correlation makes two inputs move together (above 0) or in opposite directions (below 0).", ("italic",))],
        [None])
    add(pad([("Number of runs", ()), value_cell(runs)]),
        pad([("Random seed", ()), value_cell(seed),
             ("Empty for a different one each time; the same seed gives the same runs.", ("italic",))]),
        pad([("Status", ()), (None, ("italic",))]),
        [None])

    add(*section_row("Inputs", ["Input", "Distribution", "Low", "Average", "High", "Shape", "What it is"]))
    first_row["inputs"] = len(rows) + 1
    for number in range(max(INPUT_SLOTS, len(inputs))):
        if number < len(inputs):
            name, distribution, low, average, high, shape, description, number_format = (list(inputs[number]) + [None] * 8)[:8]
            own_row = str(len(rows) + 1)
            low, average, high = [value.replace("{row}", own_row) if isinstance(value, str) else value
                                  for value in (low, average, high)]
            add(pad([(name, ("input",)), (distribution, ("input",)), value_cell(low, number_format),
                     value_cell(average, number_format), value_cell(high, number_format), value_cell(shape),
                     (description, ())]))
        else:
            add(pad([(None, ("input",))] * 6))
    last_input_row = len(rows)
    add([None])

    title_row, header_row = section_row("Custom values", ["Input", "Value", "Chance"])
    header_row[3] = ("Only for inputs whose distribution is custom: a row for each value it can have, and its chance. Chances are relative: 2, 7, and 1 mean 20%, 70%, and 10%.", ("italic",))
    add(title_row, header_row)
    first_row["custom"] = len(rows) + 1
    add(*[pad([(None, ("input",))] * 3) for _ in range(CUSTOM_SLOTS)])
    last_custom_row = len(rows)
    add([None])

    add(*section_row("Correlations", ["Input", "Input", "Correlation (-1 to 1)"]))
    first_row["correlations"] = len(rows) + 1
    for number in range(max(CORRELATION_SLOTS, len(correlations))):
        if number < len(correlations):
            first, second, correlation = correlations[number]
            add(pad([(first, ("input",)), (second, ("input",)), (correlation, ("input",))]))
        else:
            add(pad([(None, ("input",))] * 3))
    last_correlation_row = len(rows)
    add([None])

    add(*section_row("Outputs", ["Output", "What it is"]))
    for number in range(max(OUTPUT_SLOTS, len(outputs))):
        if number < len(outputs):
            name, description = outputs[number]
            add(pad([(name, ("input",)), (description, ())]))
        else:
            add(pad([(None, ("input",))]))
    add([None])
    add(*section_row("Results")[:1])          # (the macro writes everything below the title)

    validations = [
        {"range": "B%d:B%d" % (first_row["inputs"], last_input_row), "choices": list(DISTRIBUTIONS)},
        {"range": "A%d:A%d" % (first_row["custom"], last_custom_row),
         "from": "$A$%d:$A$%d" % (first_row["inputs"], last_input_row)},
        {"range": "A%d:B%d" % (first_row["correlations"], last_correlation_row),
         "from": "$A$%d:$A$%d" % (first_row["inputs"], last_input_row)},
    ]
    return {"name": SENSITIVITY, "cells": rows, "widths": COLUMN_WIDTHS, "validations": validations}


def distributions_tab():
    """The tab that says what each distribution does with Low, Average, High, and Shape."""
    heading = ["Distribution", "Kind", "Low", "Average", "High", "Shape", "What it is"]
    rows = [[("Distributions of the Sensitivity tab", ("title",))],
            [("Nothing is ever lower than Low or higher than High, whichever distribution an input has. Average is the mean, except where it says most likely value. Leave a column empty when it says (not used). Shape is only for gamma, weibull, and beta.", ("italic",))],
            [None],
            [(label, ("bold",)) for label in heading]]
    for name, kind, low, average, high, shape, notes in DISTRIBUTION_HELP:
        rows.append([(name, ("bold", "wrap")), (kind, ("wrap",)), (low, ("wrap",)), (average, ("wrap",)),
                     (high, ("wrap",)), (shape, ("wrap",)), (notes, ("wrap",))])
    return {"name": DISTRIBUTIONS_TAB, "cells": rows, "widths": [(0, 0, 130), (1, 1, 85), (2, 4, 190), (5, 5, 230), (6, 6, 520)]}


def model_setup(the_model):
    """(inputs, outputs) for a three-statement model's DCF: the assumptions that move the forecast the most, and the
    DCF's own, each centered on the model's number; and the DCF's results."""
    lines = {line.key: line for line in the_model.layouts[ASSUMPTIONS].lines if line is not None}
    inputs = []

    def add(name, distribution, low, high, number_format, description):
        # ({row} is the input's own row in the table: Low and High are formulas of the Average, in column D)
        inputs.append((name, distribution, "=D{row}" + low, "=" + name, "=D{row}" + high, None, description, number_format))

    for key, distribution, low, high in ASSUMPTION_SPREADS:
        line = lines.get(key)
        if line is not None and line.editable and (ASSUMPTIONS, key) in the_model.range_names:
            add(the_model.range_names[(ASSUMPTIONS, key)], distribution, low, high, line.number_format,
                "%s (the first forecast period's; the later periods follow it)" % line.label)
    for key, distribution, low, high, number_format, description in DCF_SPREADS:
        add(the_model.range_names[(DCF, key)], distribution, low, high, number_format, description)
    outputs = [(the_model.range_names[(DCF, key)], description) for key, description in DCF_OUTPUTS
               if (DCF, key) in the_model.range_names]
    return inputs, outputs


def model_tabs(the_model):
    """The Sensitivity tab and the macro's tab, for a model that has a DCF tab (so its names are made)."""
    inputs, outputs = model_setup(the_model)
    title = "%s (%s): Sensitivity analysis" % (the_model.company_name, the_model.ticker)
    return [sensitivity_tab(inputs, outputs, title=title), distributions_tab(), macro_tab()]


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------

def sensitivity_macro():
    """(sensitivity-macro) -- the Monte Carlo macro (Google Apps Script), as text: save it in a file, or paste it
    into Extensions > Apps Script of a spreadsheet that has a Sensitivity tab (see sensitivity-workbook)."""
    return LispString(macro_text())


def sensitivity_workbook(credentials_path, title, *options):
    """(sensitivity-workbook creds title [:runs n]) -- a new Google spreadsheet with an empty Sensitivity tab, a tab
    that explains the distributions, and a tab with the macro and how to install it. Put the model you want to analyze in the same spreadsheet (copy its tabs
    here: right-click a tab, Copy to), name the cells, and fill in the tables. You need to be signed in to Google:
    (google-login creds). Returns the spreadsheet's address."""
    who = "sensitivity-workbook"
    options = keyword_options(options, ["runs"], who)
    runs = options.get("runs", DEFAULT_RUNS)
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
        raise LispError("%s: :runs is a whole number, 1 or more" % who)
    return LispString(lisp_google.google_workbook(credentials_path, str(title), [sensitivity_tab(runs=runs), distributions_tab(), macro_tab()]))


BUILTINS = {
    "sensitivity-macro": sensitivity_macro,
    "sensitivity-workbook": sensitivity_workbook,
}
