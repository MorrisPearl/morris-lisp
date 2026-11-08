"""A small spreadsheet calculator, to test the formulas of a generated Google Sheet without Google.

It reads the tabs as lisp_google.google_workbook is given them (a list of dicts with "name" and
"cells") and works out every formula. It knows what the model's formulas use: numbers, text in
quotes, cell references (A1, or 'Tab name'!A1), ranges of them in SUM, AVERAGE, MAX, MIN, ROUND, IFERROR,
the operators + - * /, and parentheses. Anything else is an error, so a formula that uses
something new says so here.
"""

import re

TOKEN = re.compile(r"""\s*(?:
    (?P<number>\d+\.?\d*(?:[eE][+-]?\d+)?)
  | (?P<text>"[^"]*")
  | (?P<reference>(?:'[^']+'!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<function>[A-Z]+)\(
  | (?P<symbol>[-+*/(),])
)""", re.VERBOSE)


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
        for tab in tabs:
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
        return value

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else (None, None)

    def take(self):
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expression(self):
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
        return self.primary()

    def primary(self):
        kind, text = self.take()
        if kind == "number":
            return float(text)
        if kind == "text":
            return text[1:-1]
        if kind == "reference":
            return self.reference(text)
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
            return [self.sheets.value(tab, row, column) for row in range(row1, row2 + 1)
                    for column in range(column1, column2 + 1)]
        return self.sheets.at(tab, text)

    def function(self, name):
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
        numbers = []
        for argument in arguments:
            numbers += [number(x) for x in argument] if isinstance(argument, list) else [number(argument)]
        if name == "SUM":
            return sum(numbers)
        if name == "AVERAGE":
            return sum(numbers) / len(numbers)
        if name == "MAX":
            return max(numbers)
        if name == "MIN":
            return min(numbers)
        if name == "ROUND":
            return round(numbers[0], int(numbers[1]))
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
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError("%r isn't a number" % (x,))
    return x
