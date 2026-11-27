"""The window of (deal-tree deal) (lib/deal_tree.lsp): a structured deal drawn as a tree, with PyQt6.

Each tranche is a box, a node of the tree, with its name and its balance: the collateral at the left, what its split divides it into to
the right of it, and so on to the bonds at the right, which are not divided. Each split is the set of lines that join a tranche to its
children, with the kind of split written on them.

Click a box, and a menu comes up. For a tranche that is not divided, the menu lists the kinds of split; choosing one opens a pop-up window
with the fields that kind of split asks for, and two buttons: "Calculate the sizes" shows what the tranches would be, and "Add the tranches
to the deal" adds them (it can be pressed only after the sizes have been calculated, for the fields as they are). For a tranche that is
divided, the menu offers to change the split (the same pop-up, filled in as the split is) or to take it away.

The window knows nothing about deals. Everything it does, it does by calling the Lisp functions it was given by deal-tree:

  nodes ()                         every node, depth first, as lists (name parent-name balance split-label kind)
  kinds ()                         the titles of the kinds of split, for the menu
  title-of-split (name)            the title of the kind of split that divides the node, or "" if none of the kinds is it
  asking (title name)              (heading help fields) for the pop-up: fields are (name kind label value [options]), as widget-actions takes them
  sizes (title name answers)       (heading columns rows): what the tranches below the node would be
  apply (title name answers)       divides the node (or changes its split), and returns a line that says what was done
  delete (name)                    takes away the split of the node, and returns a line that says what was taken away

answers is a list of (field-name . value), as widget-actions gives them. A Lisp error in any of these is shown in the window, as a line.

In a Jupyter notebook the kernel runs Qt's event loop between cells (ipykernel's "qt" event loop, which this turns on), so the cell that
opens the window finishes and the window stays open. Anywhere else, deal-tree-window-show runs the event loop until the window is closed.
"""

import math

from lisp_core import LispError, LispString, Pair, Procedure, apply_proc, keyword_options, list_to_pairs
from lisp_widgets import to_python

NODE_HEIGHT = 46                # pixels: the height of the box of a tranche
NODE_PADDING = 10               # pixels between the text of a box and its edge
NODE_MIN_WIDTH = 140            # pixels: the narrowest a box is
ROW_GAP = 14                    # pixels between the boxes of two tranches, one above the other
LABEL_MARGIN = 8                # pixels between the box of a tranche and the kind of split written on the line out of it
CHILD_STUB = 22                 # pixels: the length of the line from the trunk of a split to the box of a child
MIN_SPLIT_GAP = 90              # pixels: the least room between a tranche and its children
SCENE_MARGIN = 24               # pixels around the tree
TEXTAREA_LINES = 7              # lines of text that a field of several lines shows
SIZES_ROWS_SHOWN = 8            # rows of the table of sizes shown before it scrolls
WINDOW_MIN_WIDTH = 900          # pixels: the window is at least this wide when it opens, to have room for the tree to grow
WINDOW_MIN_HEIGHT = 600
WINDOW_FRAME = 80               # pixels the window needs besides the tree: the scroll bars, the status bar

COLLATERAL_COLOR = "#dcecd9"    # the fill of the box of the collateral
DIVIDED_COLOR = "#dde7f5"       # the fill of the box of a tranche that is divided
BOND_COLOR = "#ffffff"          # the fill of the box of a tranche that is not divided: a bond
BORDER_COLOR = "#5b6573"
LINE_COLOR = "#7a8694"          # the lines of a split
LABEL_COLOR = "#3c4a5c"         # the kind of split written on its lines
ERROR_COLOR = "#b00020"

FUNCTION_NAMES = ("nodes", "kinds", "title-of-split", "asking", "sizes", "apply", "delete")


# ---------------------------------------------------------------------------
# Qt, and the notebook's event loop
# ---------------------------------------------------------------------------

def _qt():
    """The PyQt6 modules, which are imported when the first window is made: (QtCore, QtGui, QtWidgets)."""
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
    except ImportError:
        raise LispError("deal-tree: this needs the PyQt6 package (pip install PyQt6)")
    return QtCore, QtGui, QtWidgets


def _running_kernel():
    """The Jupyter kernel this is running in, or None if it is not running in one."""
    try:
        from ipykernel.kernelapp import IPKernelApp
    except ImportError:
        return None
    if not IPKernelApp.initialized():
        return None
    return getattr(IPKernelApp.instance(), "kernel", None)


_the_application = None        # the QApplication this made, if it made one: kept here, or Python would throw it away


def _application():
    """The QApplication, made if there is none yet. In a notebook, the kernel is told to run Qt's event loop between cells first: the
    kernel makes the QApplication then."""
    QtCore, QtGui, QtWidgets = _qt()
    kernel = _running_kernel()
    if kernel is not None and not hasattr(kernel, "app"):
        from ipykernel.eventloops import enable_gui
        enable_gui("qt6", kernel)
    global _the_application
    if QtWidgets.QApplication.instance() is None:
        _the_application = QtWidgets.QApplication(["deal-tree"])
    return QtWidgets.QApplication.instance()


# ---------------------------------------------------------------------------
# Calling the Lisp functions
# ---------------------------------------------------------------------------

class LispCallFailed(Exception):
    """A Lisp function that the window called raised an error: the message is what went wrong, to show in the window."""


def call_lisp(function, *arguments):
    """Calls a Lisp function with the arguments (Lisp values) and returns what it returns, as a Python value (see to_python). A Lisp error,
    or any other, is raised as LispCallFailed: an exception that got out of a Qt callback would stop the whole program."""
    try:
        return to_python(apply_proc(function, list(arguments)))
    except LispError as error:
        raise LispCallFailed(str(error))
    except Exception as error:          # (a bug, not a mistake of the user's; it is said in the window all the same)
        raise LispCallFailed("%s: %s" % (type(error).__name__, error))


def lisp_answers(answers):
    """The answers of a pop-up, a list of (field-name, value) with Python values, as the Lisp list of (field-name . value) the forms take."""
    def lisp_value(value):
        return LispString(value) if isinstance(value, str) else value
    return list_to_pairs([Pair(LispString(name), lisp_value(value)) for name, value in answers])


def number_text(value):
    """A number for a field: a whole number without a decimal point (60000000, not 60000000.0 or 6e+07)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def money_text(value):
    """An amount of money, to the cent, with commas, or blank if it is missing (nan)."""
    if isinstance(value, (int, float)) and not math.isnan(value):
        return "{:,.2f}".format(value)
    return ""


# ---------------------------------------------------------------------------
# The pop-up window for a split
# ---------------------------------------------------------------------------

def make_split_dialog(window, title, node_name, divided):
    """The pop-up window for dividing the node called node_name by the kind of split called title (or for changing its split, if it is
    divided): the fields the kind asks for, the two buttons, the table of sizes, and a line for what went wrong. Returns the QDialog, or
    None if the Lisp function that says what to ask raised an error (which is then said in the status bar of the window)."""
    QtCore, QtGui, QtWidgets = _qt()
    try:
        heading, help_text, fields = call_lisp(window.functions["asking"], LispString(title), LispString(node_name))
    except LispCallFailed as error:
        window.say(str(error), error=True)
        return None

    dialog = QtWidgets.QDialog(window)
    dialog.setWindowTitle(title)
    layout = QtWidgets.QVBoxLayout(dialog)

    heading_label = QtWidgets.QLabel("<b>%s</b>" % heading)
    help_label = QtWidgets.QLabel(help_text)
    help_label.setWordWrap(True)
    layout.addWidget(heading_label)
    layout.addWidget(help_label)

    form_layout = QtWidgets.QFormLayout()
    layout.addLayout(form_layout)
    readers = []                         # (field name, label, kind, function that gives what is in the field)

    def field_changed():
        """A field was changed: the sizes shown are not those of the fields any more, so the tranches cannot be added until they are
        calculated again."""
        add_button.setEnabled(False)
        if sizes_table.isVisible():
            sizes_heading.setText("The fields have changed: calculate the sizes again.")

    for field in fields:
        name, kind, label, value = field[0], field[1], field[2], field[3]
        options = field[4] if len(field) > 4 else []
        if kind == "textarea":
            widget = QtWidgets.QPlainTextEdit(str(value))
            widget.setFixedHeight(widget.fontMetrics().lineSpacing() * TEXTAREA_LINES)
            widget.textChanged.connect(field_changed)
            read = widget.toPlainText
        elif kind == "dropdown":
            widget = QtWidgets.QComboBox()
            widget.addItems([str(option) for option in options])
            widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(field_changed)
            read = widget.currentText
        elif kind == "checkbox":
            widget = QtWidgets.QCheckBox()
            widget.setChecked(bool(value))
            widget.toggled.connect(field_changed)
            read = widget.isChecked
        elif kind in ("number", "integer"):
            widget = QtWidgets.QLineEdit(number_text(value))
            widget.textChanged.connect(field_changed)
            read = widget.text
        else:                                                       # text
            widget = QtWidgets.QLineEdit(str(value))
            widget.textChanged.connect(field_changed)
            read = widget.text
        form_layout.addRow(label, widget)
        readers.append((name, label, kind, read))

    buttons = QtWidgets.QHBoxLayout()
    calculate_button = QtWidgets.QPushButton("Calculate the sizes")
    add_button = QtWidgets.QPushButton("Change the split" if divided else "Add the tranches to the deal")
    cancel_button = QtWidgets.QPushButton("Cancel")
    add_button.setEnabled(False)
    calculate_button.setDefault(True)
    buttons.addWidget(calculate_button)
    buttons.addWidget(add_button)
    buttons.addStretch()
    buttons.addWidget(cancel_button)
    layout.addLayout(buttons)

    error_label = QtWidgets.QLabel("")
    error_label.setWordWrap(True)
    error_label.setStyleSheet("color: %s" % ERROR_COLOR)
    error_label.hide()
    layout.addWidget(error_label)

    sizes_heading = QtWidgets.QLabel("")
    sizes_table = QtWidgets.QTableWidget()
    sizes_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    sizes_table.verticalHeader().hide()
    sizes_heading.hide()
    sizes_table.hide()
    layout.addWidget(sizes_heading)
    layout.addWidget(sizes_table)

    def show_error(message):
        error_label.setText(message)
        error_label.show()

    def answers():
        """What is in the fields, as (field name, value): a number field's value is a number, or an error says what is not one."""
        result = []
        for name, label, kind, read in readers:
            value = read()
            if kind in ("number", "integer"):
                text = value.strip().replace(",", "")
                try:
                    value = int(text) if kind == "integer" else float(text)
                except ValueError:
                    raise LispCallFailed("%s is not a number, for %s" % (value, label))
            result.append((name, value))
        return result

    def calculate():
        """The button that shows the sizes, without changing the deal."""
        error_label.hide()
        try:
            heading, columns, rows = call_lisp(window.functions["sizes"], LispString(title), LispString(node_name), lisp_answers(answers()))
        except LispCallFailed as error:
            add_button.setEnabled(False)
            sizes_heading.hide()
            sizes_table.hide()
            show_error(str(error))
            return
        fill_sizes_table(sizes_table, columns, rows)
        sizes_heading.setText(heading)
        sizes_heading.show()
        sizes_table.show()
        add_button.setEnabled(True)
        add_button.setDefault(True)
        dialog.adjustSize()

    def add():
        """The button that adds the tranches to the deal (or changes the split): the window is drawn again, and the pop-up closes."""
        error_label.hide()
        try:
            message = call_lisp(window.functions["apply"], LispString(title), LispString(node_name), lisp_answers(answers()))
        except LispCallFailed as error:
            show_error(str(error))
            return
        dialog.accept()
        window.redraw()
        window.say(message + " Click a tranche to divide it, or to change its split.")

    calculate_button.clicked.connect(calculate)
    add_button.clicked.connect(add)
    cancel_button.clicked.connect(dialog.reject)
    return dialog


def fill_sizes_table(table, columns, rows):
    """Puts the sizes the Lisp function worked out in the table: the tranche (indented to show the tree), and its balance, what it was
    (if it was in the deal), its share of its parent, and its average life."""
    QtCore, QtGui, QtWidgets = _qt()
    table.clear()
    table.setColumnCount(len(columns))
    table.setRowCount(len(rows))
    table.setHorizontalHeaderLabels(columns)
    for row_number, row in enumerate(rows):
        for column_number, (column, value) in enumerate(zip(columns, row)):
            if column == "tranche":
                text = str(value)
            elif column == "share of its parent":
                text = "{:.2%}".format(value)
            elif column == "average life":
                text = "" if math.isnan(value) else "{:.2f}".format(value)
            else:
                text = money_text(value)
            item = QtWidgets.QTableWidgetItem(text)
            if column != "tranche":
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row_number, column_number, item)
    table.resizeColumnsToContents()
    shown = min(len(rows), SIZES_ROWS_SHOWN)
    table.setFixedHeight(table.horizontalHeader().height() + shown * table.verticalHeader().defaultSectionSize() + 2 * table.frameWidth())
    table.setMinimumWidth(table.horizontalHeader().length() + 2 * table.frameWidth())


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------

def tree_layout(nodes):
    """Where each node goes, as a dict: name -> (depth, row). The depth is how far down the tree it is (the collateral 0); the row is how
    far down the window, in rows of boxes: the nodes that are not divided take rows 0, 1, 2, ... in order, and a divided node is half way
    between its first child and its last. nodes are (name, parent-name, ...) lists, depth first, as the Lisp function gives them."""
    children = {}
    for node in nodes:
        children.setdefault(node[1], []).append(node[0])
    places = {}
    next_row = [0]

    def place(name, depth):
        below = children.get(name, [])
        if not below:
            row = next_row[0]
            next_row[0] += 1
        else:
            for child in below:
                place(child, depth + 1)
            row = (places[below[0]][1] + places[below[-1]][1]) / 2
        places[name] = (depth, row)

    for root in children.get("", []):
        place(root, 0)
    return places


def make_window(deal_name, functions):
    """The main window: the tree of the deal in a view that scrolls, and a status bar for what was done and what went wrong."""
    QtCore, QtGui, QtWidgets = _qt()

    class NodeBox(QtWidgets.QGraphicsRectItem):
        """The box of a tranche: clicking it brings up the menu for it."""

        def __init__(self, deal_window, node, rectangle):
            super().__init__(rectangle)
            self.deal_window = deal_window
            self.node = node
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self.setAcceptHoverEvents(True)
            self.setToolTip("Click to divide %s, or to change its split" % node[0])

        def mousePressEvent(self, event):
            # The menu is shown once this click has been dealt with: what is chosen in it may draw the tree again, which takes away this box.
            event.accept()
            position = event.screenPos()
            QtCore.QTimer.singleShot(0, lambda: self.deal_window.node_clicked(self.node, position))

        def hoverEnterEvent(self, event):
            self.setPen(QtGui.QPen(QtGui.QColor(BORDER_COLOR), 2.5))

        def hoverLeaveEvent(self, event):
            self.setPen(QtGui.QPen(QtGui.QColor(BORDER_COLOR), 1))

    class DealTreeWindow(QtWidgets.QMainWindow):

        def __init__(self):
            super().__init__()
            self.deal_name = deal_name
            self.functions = functions
            self.nodes = []
            self.closed = False
            self.setWindowTitle("Deal tree: %s" % deal_name)
            self.scene = QtWidgets.QGraphicsScene(self)
            self.view = QtWidgets.QGraphicsView(self.scene)
            self.view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            self.view.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
            self.setCentralWidget(self.view)
            self.name_font = QtGui.QFont()
            self.name_font.setBold(True)
            self.text_font = QtGui.QFont()
            self.label_font = QtGui.QFont()
            self.label_font.setItalic(True)
            self.redraw()
            self.say("Click a tranche to divide it, or to change or take away its split.")

        def __repr__(self):
            return "#<the deal tree window of %s>" % self.deal_name

        def closeEvent(self, event):
            self.closed = True
            super().closeEvent(event)

        def say(self, message, error=False):
            """A line in the status bar: what was done, or (in red) what went wrong."""
            self.statusBar().setStyleSheet("color: %s" % ERROR_COLOR if error else "")
            self.statusBar().showMessage(message)

        # -- drawing ----------------------------------------------------------

        def redraw(self):
            """Draws the tree of the deal as it is now (it is asked for it again)."""
            if self.closed:
                return
            try:
                self.nodes = call_lisp(self.functions["nodes"])
            except LispCallFailed as error:
                self.say(str(error), error=True)
                return
            self.scene.clear()
            name_metrics = QtGui.QFontMetrics(self.name_font)
            text_metrics = QtGui.QFontMetrics(self.text_font)
            label_metrics = QtGui.QFontMetrics(self.label_font)
            node_width = max([NODE_MIN_WIDTH] + [max(name_metrics.horizontalAdvance(self.name_line(node)),
                                                     text_metrics.horizontalAdvance(money_text(node[2]))) + 2 * NODE_PADDING
                                                 for node in self.nodes])
            split_gap = max([MIN_SPLIT_GAP] + [label_metrics.horizontalAdvance(node[3]) + 2 * LABEL_MARGIN + CHILD_STUB
                                               for node in self.nodes])
            places = tree_layout(self.nodes)

            def box_at(name):
                depth, row = places[name]
                return QtCore.QRectF(SCENE_MARGIN + depth * (node_width + split_gap), SCENE_MARGIN + row * (NODE_HEIGHT + ROW_GAP),
                                     node_width, NODE_HEIGHT)

            for node in self.nodes:
                self.draw_split_lines(node, box_at, split_gap)
            for node in self.nodes:
                self.draw_node(node, box_at(node[0]))
            self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))

        def name_line(self, node):
            """The first line of the box of a node: its name, and Z or notional if it is one."""
            name, kind = node[0], node[4]
            return "%s  (%s)" % (name, kind) if kind else name

        def draw_node(self, node, box):
            """The box of a tranche, with its name and its balance."""
            name, parent_name, split_label = node[0], node[1], node[3]
            fill = COLLATERAL_COLOR if parent_name == "" else DIVIDED_COLOR if split_label else BOND_COLOR
            item = NodeBox(self, node, box)
            item.setBrush(QtGui.QBrush(QtGui.QColor(fill)))
            item.setPen(QtGui.QPen(QtGui.QColor(BORDER_COLOR), 1))
            self.scene.addItem(item)
            name_text = QtWidgets.QGraphicsSimpleTextItem(self.name_line(node), item)
            name_text.setFont(self.name_font)
            name_text.setPos(box.left() + NODE_PADDING, box.top() + NODE_PADDING / 2)
            balance_text = QtWidgets.QGraphicsSimpleTextItem(money_text(node[2]), item)
            balance_text.setFont(self.text_font)
            balance_text.setPos(box.left() + NODE_PADDING, box.center().y())

        def draw_split_lines(self, node, box_at, split_gap):
            """The split of a tranche, if it is divided: a line out of its box to a trunk, and a line from the trunk to each child, with the
            kind of split written on the line out of the box."""
            name, split_label = node[0], node[3]
            if not split_label:
                return
            children = [other[0] for other in self.nodes if other[1] == name]
            parent_box = box_at(name)
            trunk_x = parent_box.right() + split_gap - CHILD_STUB
            pen = QtGui.QPen(QtGui.QColor(LINE_COLOR), 1.5)
            self.scene.addLine(parent_box.right(), parent_box.center().y(), trunk_x, parent_box.center().y(), pen)
            child_ys = [box_at(child).center().y() for child in children]
            self.scene.addLine(trunk_x, min(child_ys + [parent_box.center().y()]), trunk_x, max(child_ys + [parent_box.center().y()]), pen)
            for child in children:
                child_box = box_at(child)
                self.scene.addLine(trunk_x, child_box.center().y(), child_box.left(), child_box.center().y(), pen)
            label = self.scene.addSimpleText(split_label, self.label_font)
            label.setBrush(QtGui.QBrush(QtGui.QColor(LABEL_COLOR)))
            label.setPos(parent_box.right() + LABEL_MARGIN, parent_box.center().y() - label.boundingRect().height() - 1)

        # -- the menu ---------------------------------------------------------

        def node_clicked(self, node, screen_position):
            """A box was clicked: the menu for its tranche."""
            menu = self.node_menu(node)
            menu.exec(screen_position)

        def node_menu(self, node):
            """The menu for a tranche: the kinds of split, if it is not divided; to change or take away its split, if it is."""
            name, balance, split_label = node[0], node[2], node[3]
            menu = QtWidgets.QMenu(self)
            if split_label:
                try:
                    title = call_lisp(self.functions["title-of-split"], LispString(name))
                except LispCallFailed as error:
                    self.say(str(error), error=True)
                    title = ""
                if title:
                    menu.addAction("Change the %s split of %s..." % (split_label, name)).triggered.connect(
                        lambda checked=False: self.open_split_dialog(title, name, True))
                else:
                    menu.addAction("A %s split can be taken away here, but not changed" % split_label).setEnabled(False)
                menu.addAction("Take away the split of %s, and everything under it..." % name).triggered.connect(
                    lambda checked=False: self.ask_to_delete(name))
            elif balance == 0:
                menu.addAction("%s has no balance, so it cannot be divided: the collateral is entered first" % name).setEnabled(False)
            else:
                menu.addAction("Divide %s by:" % name).setEnabled(False)
                try:
                    kinds = call_lisp(self.functions["kinds"])
                except LispCallFailed as error:
                    self.say(str(error), error=True)
                    kinds = []
                for title in kinds:
                    menu.addAction("    %s..." % title).triggered.connect(
                        lambda checked=False, title=title: self.open_split_dialog(title, name, False))
            return menu

        def open_split_dialog(self, title, name, divided):
            """The pop-up for dividing the tranche (or changing its split) by the kind of split called title."""
            dialog = make_split_dialog(self, title, name, divided)
            if dialog is not None:
                dialog.exec()

        def names_below(self, name):
            """The names of the nodes under the node called name, depth first."""
            below = []
            for node in self.nodes:
                if node[1] == name:
                    below.append(node[0])
                    below.extend(self.names_below(node[0]))
            return below

        def ask_to_delete(self, name):
            """Asks whether to take away the split of the tranche, and every tranche under it, and does it if the answer is yes."""
            below = self.names_below(name)
            question = "Take away the split of %s, and %s: %s? That cannot be undone." % (
                name, "the tranche under it" if len(below) == 1 else "the %d tranches under it" % len(below), ", ".join(below))
            answer = QtWidgets.QMessageBox.question(self, "Take away a split", question)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                self.say("Kept the split of %s." % name)
                return
            try:
                message = call_lisp(self.functions["delete"], LispString(name))
            except LispCallFailed as error:
                self.say(str(error), error=True)
                return
            self.redraw()
            self.say(message)

    return DealTreeWindow()


# ---------------------------------------------------------------------------
# The builtins
# ---------------------------------------------------------------------------

def deal_tree_window(deal_name, *options):
    """(deal-tree-window deal-name :nodes f :kinds f :title-of-split f :asking f :sizes f :apply f :delete f) -- the window that draws a
    deal as a tree, made but not shown yet (see deal-tree-window-show). The functions are those at the top of lisp_deal_tree.py; deal-tree
    (lib/deal_tree.lsp) gives them."""
    functions = keyword_options(list(options), FUNCTION_NAMES, "deal-tree-window")
    missing = [name for name in FUNCTION_NAMES if name not in functions]
    if missing:
        raise LispError("deal-tree-window: it needs the functions %s" % ", ".join(":" + name for name in missing))
    for name, function in functions.items():
        if not callable(function) and not isinstance(function, Procedure):
            raise LispError("deal-tree-window: :%s is to be a function" % name)
    _application()
    return make_window(str(deal_name), functions)


def deal_tree_window_show(window):
    """(deal-tree-window-show window) -- shows the window, and returns it. In a notebook it returns at once, and the window stays open;
    anywhere else it returns when the window is closed."""
    application = _application()
    tree = window.view.sceneRect().size().toSize()
    screen = application.primaryScreen().availableSize()
    window.resize(min(max(tree.width() + WINDOW_FRAME, WINDOW_MIN_WIDTH), screen.width()),
                  min(max(tree.height() + WINDOW_FRAME, WINDOW_MIN_HEIGHT), screen.height()))
    window.show()
    window.raise_()
    if _running_kernel() is None:
        application.exec()
    return window


def deal_tree_window_redraw(window):
    """(deal-tree-window-redraw window) -- draws the deal again, as it is now (nothing, if the window has been closed)."""
    window.redraw()
    return window


BUILTINS = {
    "deal-tree-window": deal_tree_window,
    "deal-tree-window-show": deal_tree_window_show,
    "deal-tree-window-redraw": deal_tree_window_redraw,
}
