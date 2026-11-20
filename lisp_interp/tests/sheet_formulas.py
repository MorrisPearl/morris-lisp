"""A small spreadsheet calculator, to test the formulas of a generated Google Sheet without Google.

It reads the tabs as lisp_google.google_workbook is given them (a list of dicts with "name" and
"cells") and works out every formula. It knows what the model's formulas use: numbers, text in
quotes, cell references (A1, or 'Tab name'!A1), ranges of them in SUM, AVERAGE, MEDIAN, MAX, MIN, ROUND, IFERROR,
SUMPRODUCT, IF, the operators + - * / ^ and the comparisons = <> < > <= >=, parentheses, named cells (a tab's "names", such as tax_rate) and OFFSET(a name or cell, rows,
columns), which moves from it. Anything else is an error, so a formula that uses
something new says so here.
"""

import math
import re

TOKEN = re.compile(r"""\s*(?:
    (?P<number>\d+\.?\d*(?:[eE][+-]?\d+)?)
  | (?P<text>"[^"]*")
  | (?P<reference>(?:'[^']+'!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<function>[A-Z]+)\(
  | (?P<name>[a-z_][a-z0-9_]*)
  | (?P<compare><=|>=|<>|[<>=])
  | (?P<symbol>[-+*/^(),])
)""", re.VERBOSE)

class EmptyCell:
    """What a reference to an empty cell gives, inside a formula: as in Sheets, it is 0 to arithmetic, equal both to 0
    and to "", and false to IF. (A formula whose whole result is an empty cell gives 0, as =A1 does.)"""

    def __bool__(self):
        return False

    def __repr__(self):
        return "EMPTY"


EMPTY = EmptyCell()


def comparable(a, b):
    """The two sides of a comparison, with an empty cell made what the other side is: "" beside text, 0 beside a number."""
    if a is EMPTY:
        a = "" if isinstance(b, str) else 0
    if b is EMPTY:
        b = "" if isinstance(a, str) else 0
    return a, b


COMPARISONS = {"=": lambda a, b: a == b, "<>": lambda a, b: a != b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
               "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}


def column_number(letters):
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number - 1


def split_address(address):
    match = re.match(r"\$?([A-Z]{1,3})\$?(\d+)$", address)
    return int(match.group(2)) - 1, column_number(match.group(1))       # (row, column), from 0


class Sheets:
    """The values of the tabs' cells, with formulas worked out when they are asked for."""

    def __init__(self, tabs):
        self.cells = {}
        self.names = {}                  # name -> (tab, address)
        for tab in tabs:
            for name, address in tab.get("names", []):
                self.names[name] = (tab["name"], address)
            grid = {}
            for row_number, row in enumerate(tab["cells"]):
                for column_number_, cell in enumerate(row):
                    if cell is not None and cell[0] is not None:
                        grid[(row_number, column_number_)] = cell[0]
            self.cells[tab["name"]] = grid
        self.worked_out = {}
        self.working_on = set()

    def value(self, tab, row, column):
        """What the cell holds: a number or text, or 0 for an empty cell."""
        key = (tab, row, column)
        if key in self.worked_out:
            return self.worked_out[key]
        content = self.cells[tab].get((row, column))
        if isinstance(content, str) and content.startswith("="):
            if key in self.working_on:
                raise ValueError("circular reference at %s row %d column %d" % (tab, row + 1, column + 1))
            self.working_on.add(key)
            try:
                content = Formula(self, tab, content[1:]).result()
            finally:
                self.working_on.discard(key)
        elif content is None:
            content = 0
        self.worked_out[key] = content
        return content

    def cell_or_empty(self, tab, row, column):
        """A cell's value, as a formula that refers to it sees it: EMPTY if there is nothing in it."""
        if self.cells[tab].get((row, column)) is None:
            return EMPTY
        return self.value(tab, row, column)

    def at(self, tab, address):
        row, column = split_address(address)
        return self.value(tab, row, column)

    def has_formula(self, tab, address):
        row, column = split_address(address)
        content = self.cells[tab].get((row, column))
        return isinstance(content, str) and content.startswith("=")


class Formula:
    """One formula, being read and worked out from left to right."""

    def __init__(self, sheets, tab, text):
        self.sheets, self.tab = sheets, tab
        self.tokens = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if not match or match.end() == position:
                raise ValueError("can't read the formula =%s at: %s" % (text, text[position:]))
            kind = match.lastgroup
            self.tokens.append((kind, match.group(kind)))
            position = match.end()
        self.position = 0
        self.text = text

    def result(self):
        value = self.expression()
        if self.position != len(self.tokens):
            raise ValueError("extra text in =%s" % self.text)
        return 0 if value is EMPTY else value

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else (None, None)

    def take(self):
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expression(self):
        """A comparison, or just a sum (a comparison is true or false, as Sheets' are)."""
        value = self.sum()
        while self.peek()[0] == "compare":
            operator = self.take()[1]
            other = self.sum()
            value = COMPARISONS[operator](*comparable(value, other))
        return value

    def sum(self):
        value = self.term()
        while self.peek() in (("symbol", "+"), ("symbol", "-")):
            operator = self.take()[1]
            other = self.term()
            value = number(value) + number(other) if operator == "+" else number(value) - number(other)
        return value

    def term(self):
        value = self.unary()
        while self.peek() in (("symbol", "*"), ("symbol", "/")):
            operator = self.take()[1]
            other = self.unary()
            value = number(value) * number(other) if operator == "*" else number(value) / number(other)
        return value

    def unary(self):
        if self.peek() == ("symbol", "-"):
            self.take()
            return -number(self.unary())
        return self.power()

    def power(self):
        value = self.primary()
        while self.peek() == ("symbol", "^"):
            self.take()
            value = number(value) ** number(self.primary())
        return value

    def primary(self):
        kind, text = self.take()
        if kind == "number":
            return float(text)
        if kind == "text":
            return text[1:-1]
        if kind == "reference":
            return self.reference(text)
        if kind == "name":
            tab, address = self.sheets.names[text]
            return self.sheets.cell_or_empty(tab, *split_address(address))
        if kind == "function":
            return self.function(text)
        if (kind, text) == ("symbol", "("):
            value = self.expression()
            self.take()
            return value
        raise ValueError("unexpected %s in =%s" % (text, self.text))

    def reference(self, text):
        """A cell's value, or -- for a range -- a list of the cells' values."""
        tab = self.tab
        if "!" in text:
            name, text = text.split("!")
            tab = name.strip("'")
        if ":" in text:
            (row1, column1), (row2, column2) = [split_address(part) for part in text.split(":")]
            # (a range has its numbers: Sheets leaves out the empty cells, and the text, as SUM, AVERAGE and MEDIAN do)
            cells = [(row, column) for row in range(row1, row2 + 1) for column in range(column1, column2 + 1)]
            values = [self.sheets.value(tab, row, column) for row, column in cells if self.sheets.cells[tab].get((row, column)) is not None]
            return [v for v in values if isinstance(v, (int, float))]
        return self.sheets.cell_or_empty(tab, *split_address(text))

    def offset(self):
        """OFFSET(name or cell, rows, columns): the value of the cell that far from the first."""
        kind, text = self.take()
        if kind == "name":
            tab, address = self.sheets.names[text]
        elif kind == "reference" and ":" not in text:
            tab, address = (text.split("!")[0].strip("'") if "!" in text else self.tab), text.split("!")[-1]
        else:
            raise ValueError("OFFSET starts from a name or a cell, in =%s" % self.text)
        self.take()                                       # the comma
        rows = int(number(self.expression()))
        self.take()
        columns = int(number(self.expression()))
        self.take()                                       # the closing parenthesis
        row, column = split_address(address)
        if row + rows < 0 or column + columns < 0:
            raise ValueError("OFFSET goes off the sheet in =%s" % self.text)
        return self.sheets.cell_or_empty(tab, row + rows, column + columns)

    def range_cells(self, text):
        """Every cell of a range, in order, a number or 0 (text and empty cells are 0, as SUMPRODUCT takes them)."""
        tab = self.tab
        if "!" in text:
            name, text = text.split("!")
            tab = name.strip("'")
        (row1, column1), (row2, column2) = [split_address(part) for part in text.split(":")]
        values = [self.sheets.value(tab, row, column) for row in range(row1, row2 + 1) for column in range(column1, column2 + 1)]
        return [v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0 for v in values]

    def skip_to_end_of_call(self):
        """Move past the rest of a function's arguments and its closing parenthesis."""
        depth = 0
        while True:
            kind, text = self.take()
            if kind == "function" or (kind, text) == ("symbol", "("):
                depth += 1
            elif (kind, text) == ("symbol", ")"):
                if depth == 0:
                    return
                depth -= 1

    def function(self, name):
        if name == "OFFSET":
            return self.offset()
        if name == "IF":
            condition = self.expression()
            self.take()                                  # the comma
            if condition:
                value = self.expression()
                self.skip_to_end_of_call()
                return value
            self.skip_argument(self.position)
            self.take()                                  # the comma
            value = self.expression()
            self.take()
            return value
        if name == "ISBLANK":                            # (whether a cell has nothing in it: not even a formula)
            kind, text = self.take()
            if kind != "reference" or ":" in text:
                raise ValueError("ISBLANK of one cell only, in =%s" % self.text)
            self.take()                                  # the closing parenthesis
            tab = text.split("!")[0].strip("'") if "!" in text else self.tab
            return self.sheets.cells[tab].get(split_address(text.split("!")[-1])) is None
        if name == "SUMPRODUCT":
            ranges = []
            while True:
                kind, text = self.take()
                if kind != "reference" or ":" not in text:
                    raise ValueError("SUMPRODUCT of ranges only, in =%s" % self.text)
                ranges.append(self.range_cells(text))
                if self.take() == ("symbol", ")"):
                    break
            total = 0.0
            for values in zip(*ranges):
                product = 1.0
                for value in values:
                    product *= value
                total += product
            return total
        if name == "IFERROR":
            start = self.position
            try:
                value = self.expression()
                failed = False
            except (ZeroDivisionError, TypeError):
                failed = True
                self.skip_argument(start)
            self.take()                                  # the comma
            fallback = self.expression()
            self.take()                                  # the closing parenthesis
            return fallback if failed else value
        arguments = [self.expression()]
        while self.peek() == ("symbol", ","):
            self.take()
            arguments.append(self.expression())
        self.take()                                       # the closing parenthesis
        if name == "OR":
            return any(bool(argument) for argument in arguments)
        if name == "AND":
            return all(bool(argument) for argument in arguments)
        numbers = []
        for argument in arguments:
            numbers += [number(x) for x in argument] if isinstance(argument, list) else [number(argument)]
        if name == "SUM":
            return sum(numbers)
        if name == "MEDIAN":
            numbers.sort()
            middle = len(numbers) // 2
            return numbers[middle] if len(numbers) % 2 else (numbers[middle - 1] + numbers[middle]) / 2
        if name == "AVERAGE":
            return sum(numbers) / len(numbers)
        if name == "MAX":
            return max(numbers) if numbers else 0          # (as Sheets: MAX of no numbers is 0)
        if name == "MIN":
            return min(numbers) if numbers else 0
        if name == "ROUND":
            return round(numbers[0], int(numbers[1]))
        if name == "EXP":
            return math.exp(numbers[0])
        if name == "LN":
            if numbers[0] <= 0:
                raise ZeroDivisionError("LN of a number not above 0")      # (an error, as in Sheets: IFERROR catches it)
            return math.log(numbers[0])
        raise ValueError("the calculator doesn't know %s" % name)

    def skip_argument(self, start):
        """After an error inside IFERROR's first argument, move to its comma."""
        self.position = start
        depth = 0
        while True:
            kind, text = self.peek()
            if (kind, text) == ("symbol", ",") and depth == 0:
                return
            if kind == "function" or (kind, text) == ("symbol", "("):
                depth += 1
            elif (kind, text) == ("symbol", ")"):
                depth -= 1
            self.position += 1


def number(x):
    """A value as arithmetic takes it: an empty cell, and text with nothing in it, are 0, as in Sheets; other text is an
    error (#VALUE!)."""
    if x is EMPTY or x == "":
        return 0
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError("%r isn't a number" % (x,))
    return x
