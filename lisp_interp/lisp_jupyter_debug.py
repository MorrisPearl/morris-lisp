"""The debug REPL for Jupyter (JupyterLab and Notebook): a version of debug_repl
(in lisp_core.py) that uses ipywidgets instead of the console, because a
notebook has no console to read from.

When the program stops -- at a (breakpoint), a (break f), or an error with
break-on-error -- and no debug hook takes over, the cell that is running shows

  - a text area and a Run button, made with ipywidgets' interact_manual.
    Type Lisp and press Run: it is evaluated in the scope where the program
    stopped, as at the console;
  - Continue and Abort buttons, and Locals and Backtrace buttons for the two
    commonest commands;
  - a transcript of what you typed and what came back.

The cell is still running all the while. Continue lets the program go on, and
Abort abandons the computation, as (abort) does.

HOW IT WORKS. A kernel handles one message at a time, so while a cell runs, a
click on a widget waits, with every other message, until the cell has
finished. A debug stop is in the middle of a cell and needs the clicks now. So
while it waits, the REPL takes the messages that are waiting for the kernel
and handles the widget ones itself, and the rest stay in the queue in order,
so that (for example) the cells below a paused cell in a "Run All" don't run until
the paused one has finished. Handling a widget message never has to wait for
anything, so it's run to completion on the spot, with no event loop: which also
means that a stop can be inside a stop, to any depth. See KernelMessagePump.

The pieces are separate so they can be tested apart: KernelMessagePump needs a
running kernel, and WidgetDebugRepl needs only ipywidgets.
"""

import contextlib
import html
import importlib.util
import io
import time

from lisp_core import (
    LispAbort, Pair, Symbol, cut_off, format_error_report, parse, seval, to_string,
)

# The messages that carry what widgets do: a click, a change to a text box.
WIDGET_MESSAGE_TYPES = ("comm_open", "comm_msg", "comm_close", "comm_info_request")

POLL_SECONDS = 0.02         # how long the REPL rests between looks for widget messages


class KernelMessagePump:
    """Handles the widget messages that reach a kernel while one of its cells is
    still running. handle_widget_messages() is called again and again, from
    inside the running cell."""

    def __init__(self, kernel):
        for needed in ("shell_stream", "msg_queue", "session"):
            if not hasattr(kernel, needed):
                raise RuntimeError("the kernel has no %s, so it isn't a running ipykernel 6" % needed)
        self.kernel = kernel

    def message_type(self, arguments):
        """The type of a queued shell message ('comm_msg', 'execute_request', ...),
        or None if it can't be read."""
        session = self.kernel.session
        try:
            _, frames = session.feed_identities(arguments[0], copy=False)
            return session.deserialize(frames, content=False, copy=False)["header"]["msg_type"]
        except Exception:
            return None

    def handle_widget_messages(self):
        """Handle every widget message that is waiting. Everything else stays queued,
        in order, for when the cell has finished."""
        kernel = self.kernel
        cells_ident = kernel._parent_ident["shell"]         # who the cell's output belongs to
        cells_parent = kernel.get_parent("shell")
        kernel.shell_stream.flush()                         # move the waiting messages into the queue

        other_messages = []
        while kernel.msg_queue.qsize():
            queued = kernel.msg_queue.get_nowait()
            dispatch, arguments = queued[1], queued[2]
            if self.message_type(arguments) in WIDGET_MESSAGE_TYPES:
                self.run_now(dispatch(*arguments))
            else:
                other_messages.append(queued)
        for queued in other_messages:
            kernel.msg_queue.put_nowait(queued)

        # Handling a message made it the kernel's current one, so that what it
        # prints belongs to it. Put the cell back, so that what the cell goes on
        # to print is shown in the cell.
        kernel.set_parent(cells_ident, cells_parent, "shell")

    def run_now(self, coroutine):
        """Run the kernel's handling of one message (a coroutine) to the end. A
        widget message never has to wait for anything, so it finishes at the
        first step, without an event loop."""
        try:
            coroutine.send(None)
        except StopIteration:
            return
        coroutine.close()
        raise RuntimeError("the kernel had to wait to handle a widget message")


class WidgetDebugRepl:
    """One debug REPL, shown in the output of the cell that is running.

    `env` is the scope where the program stopped, `label` names the stop (the
    procedure, for a break), and `resume` says what continuing does."""

    def __init__(self, env, label, resume):
        self.env = env
        self.label = label
        self.resume = resume
        self.action = None          # "continue" or "abort", once the user has chosen
        self.controls = []          # the widgets to switch off when it's over
        self.transcript = None      # an Output widget

    # -- what the widgets do -----------------------------------------------

    def write(self, text):
        """Add text to the transcript."""
        if text:
            self.transcript.append_stdout(text)

    def choose(self, action):
        """The user chose Continue or Abort (the first choice stands)."""
        if self.action is None:
            self.action = action

    def run_text(self, source):
        """Evaluate what was typed, as the console REPL does, and add it, and what
        came back, to the transcript."""
        source = source.strip()
        if not source:
            return
        self.write("%s> %s\n" % (self.label, source))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):       # what the Lisp displays belongs in the transcript
            try:
                self.evaluate_forms(source)
            except LispAbort:
                self.action = "abort"
        self.write(printed.getvalue())

    def evaluate_forms(self, source):
        try:
            for expr in parse(source):
                if isinstance(expr, Pair) and expr.car in (Symbol("continue"), Symbol("exit")):
                    self.choose("continue")
                    return
                print(cut_off(to_string(seval(expr, self.env))))
        except Exception as e:
            print(format_error_report(e), end="")

    # -- showing it ----------------------------------------------------------

    def show(self):
        """Display the REPL in the output of the running cell."""
        import ipywidgets as widgets
        from IPython.display import display

        title = widgets.HTML(
            "<b><code>%s&gt;</code></b> debug REPL &mdash; <code>(continue)</code> %s, "
            "<code>(abort)</code> abandons the computation, <code>(locals)</code> shows the variables"
            % (html.escape(self.label), html.escape(self.resume)))
        display(title)

        # The text area and the Run button. interact_manual runs the function
        # when Run is pressed (plain interact would run it at every keystroke).
        def evaluate(expression):
            self.run_text(expression)

        interact_manual = widgets.interact.options(manual=True, manual_name="Run")
        interact_manual(evaluate, expression=widgets.Textarea(
            description="%s>" % self.label, placeholder="a Lisp expression, such as (locals)", rows=2,
            style={"description_width": "initial"}, layout=widgets.Layout(width="95%")))
        self.controls.extend(child for child in evaluate.widget.children if hasattr(child, "disabled"))

        buttons = [("Continue", "success", "play", lambda: self.choose("continue")),
                   ("Abort", "danger", "stop", lambda: self.choose("abort")),
                   ("Locals", "", "", lambda: self.run_text("(locals)")),
                   ("Backtrace", "", "", lambda: self.run_text("(backtrace)"))]
        row = []
        for description, style, icon, action in buttons:
            button = widgets.Button(description=description, button_style=style, icon=icon)
            button.on_click(lambda _button, action=action: action())
            row.append(button)
        self.controls.extend(row)

        self.transcript = widgets.Output(
            layout=widgets.Layout(max_height="18em", overflow="auto", border="1px solid #ddd"))
        display(widgets.HBox(row), self.transcript)

    # -- waiting, and finishing ------------------------------------------------

    def wait(self, pump):
        """Wait until the user chooses Continue or Abort, letting the widgets work
        meanwhile. Returns to let the program go on; raises LispAbort to abandon it."""
        try:
            while self.action is None:
                pump.handle_widget_messages()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:                       # Interrupt Kernel, in the menu
            self.action = "abort"
        finally:
            self.finish()
        if self.action == "abort":
            raise LispAbort()

    def finish(self):
        """Switch the controls off, and say how it ended."""
        for control in self.controls:
            control.disabled = True
        self.write("--- %s: %s ---\n" % (self.label, "aborted" if self.action == "abort" else "resuming"))


def open_widget_debug_repl(kernel, env, label, resume):
    """The debug REPL for a Jupyter kernel (see the top of this file). Takes the
    place of debug_repl in lisp_core, and is called the same way."""
    try:
        if importlib.util.find_spec("ipywidgets") is None:
            raise ImportError("ipywidgets isn't installed")
        pump = KernelMessagePump(kernel)
    except ImportError as e:
        print("--- %s: the debug REPL in Jupyter needs ipywidgets (%s); resuming ---" % (label, e))
        return
    except RuntimeError as e:
        print("--- %s: the debug REPL can only open while a notebook cell is running (%s); "
              "resuming ---" % (label, e))
        return
    repl = WidgetDebugRepl(env, label, resume)
    repl.show()
    repl.wait(pump)
