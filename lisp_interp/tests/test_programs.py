"""Whole programs: the command line, the GUI's error report, the KenKen solver, the chess
program, and the example scripts.
support.py says how to run them."""

import random
import sqlite3

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


def run_cli(*args, stdin=None, env_extra=None, cwd=None):
    """Run the interpreter as a subprocess with no init file, no GUI."""
    env = dict(os.environ, LISP_INIT_FILE=os.path.join(tempfile.gettempdir(), "no-such-init.lsp"))
    env.update(env_extra or {})
    return subprocess.run([sys.executable, INTERPRETER] + list(args), input=stdin,
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=120)


class TestCommandLine(unittest.TestCase):

    def test_batch_mode_runs_a_script_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hello.lsp")
            with open(path, "w") as f:
                f.write('(display "hello ") (display (+ 1 2)) (newline)')
            r = run_cli(path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "hello 3\n")

    def test_a_script_gets_the_words_after_its_name(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "words.lsp")
            with open(path, "w") as f:
                f.write("(print (command-line-arguments))")
            self.assertEqual(run_cli(path, "KO", "6").stdout, '("KO" "6")\n')
            self.assertEqual(run_cli(path).stdout, "()\n")
            self.assertEqual(run_cli("-v", path, "--verbose").stdout.splitlines()[-1], '("--verbose")')
        r = run_cli("-", "KO", stdin="(command-line-arguments)\n")
        self.assertIn('("KO")', r.stdout)

    def test_a_script_error_gives_a_nonzero_exit_and_names_the_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.lsp")
            with open(path, "w") as f:
                f.write('(display "before")\n(error "kaboom" 1)\n(display "never")')
            r = run_cli(path)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kaboom 1", r.stderr)
        self.assertIn("before", r.stdout)
        self.assertNotIn("never", r.stdout)

    def test_the_init_file_env_var_is_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            init = os.path.join(d, "my_init.lsp")
            script = os.path.join(d, "s.lsp")
            with open(init, "w") as f:
                f.write("(define from-init 77)")
            with open(script, "w") as f:
                f.write("(display from-init)")
            r = run_cli(script, env_extra={"LISP_INIT_FILE": init})
        self.assertEqual(r.stdout, "77")

    def test_interactive_mode_evaluates_typed_expressions(self):
        r = run_cli("-", stdin="(+ 1 2)\n(define x 5)\n(* x x)\n(exit)\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3", r.stdout)
        self.assertIn("25", r.stdout)

    def test_interactive_mode_survives_an_error_and_keeps_going(self):
        r = run_cli("-", stdin="(car '())\n(+ 20 22)\n(exit)\n")
        self.assertIn("42", r.stdout)


class TestCommandLineTracing(unittest.TestCase):
    """The -v/--verbose flags, LISP_VERBOSE, and how batch mode and the REPL
    report an error (the Lisp call chain, not a dump of Python internals)."""

    SCRIPT = "(define (f n) (if (= n 0) 'done (f (- n 1))))\n(define (g) (list (f 1)))\n(g)\n"

    def run_script(self, *flags, source=None, env_extra=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.lsp")
            with open(path, "w") as fh:
                fh.write(source if source is not None else self.SCRIPT)
            return run_cli(*(list(flags) + [path]), env_extra=env_extra)

    def test_no_flag_means_no_trace(self):
        self.assertEqual(self.run_script().stdout, "")

    def test_dash_v_traces_procedure_names(self):
        r = self.run_script("-v")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "> g\n  > f\n  >> f\n")

    def test_dash_vv_adds_arguments_and_return_values(self):
        out = self.run_script("-vv").stdout
        self.assertIn("> (g)", out)
        self.assertIn("  >> (f 0)", out)
        self.assertIn("< (g) => (done)", out)

    def test_dash_vvv_and_the_long_form_agree(self):
        self.assertEqual(self.run_script("-vvv").stdout, self.run_script("--verbose=3").stdout)
        self.assertEqual(self.run_script("-v").stdout, self.run_script("--verbose").stdout)

    def test_verbose_zero_is_off(self):
        self.assertEqual(self.run_script("--verbose=0").stdout, "")

    def test_an_invalid_level_is_rejected_with_status_2(self):
        r = self.run_script("--verbose=9")
        self.assertEqual(r.returncode, 2)
        self.assertIn("must be 0, 1, 2, or 3", r.stderr)

    def test_the_lisp_verbose_environment_variable(self):
        self.assertEqual(self.run_script(env_extra={"LISP_VERBOSE": "1"}).stdout, "> g\n  > f\n  >> f\n")
        self.assertEqual(self.run_script(env_extra={"LISP_VERBOSE": "nonsense"}).stdout, "")

    def test_a_script_can_turn_tracing_on_and_off_itself(self):
        r = self.run_script(source="(define (f) 1)\n(f)\n(verbose 1)\n(f)\n(verbose 0)\n(f)\n")
        self.assertEqual(r.stdout, "> f\n")

    def test_a_lisp_error_is_reported_as_the_call_chain_then_the_message(self):
        r = self.run_script(source="(define (inner x) (car x))\n(define (outer x) (list (inner x)))\n(outer 5)\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr,
                         "Lisp traceback (most recent call last):\n  (outer 5)\n  (inner 5)\n"
                         "Error: car: not a pair: 5\n")

    def test_a_lisp_error_does_not_dump_a_python_traceback(self):
        r = self.run_script(source="(error \"plain\")")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, "Error: plain\n")

    def test_the_python_traceback_is_available_on_request(self):
        r = self.run_script(source="(error \"plain\")", env_extra={"LISP_PYTHON_TRACEBACK": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Traceback (most recent call last):", r.stderr)
        self.assertIn("LispError: plain", r.stderr)

    def test_output_before_the_error_is_kept_and_ordered_before_the_report(self):
        r = self.run_script(source='(display "before")\n(error "x")')
        self.assertEqual(r.stdout, "before")

    def test_a_python_exception_in_a_builtin_is_reported_as_a_lisp_error(self):
        r = self.run_script(source="(define (f x) (/ 1 x))\n(list (f 0))\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, "Lisp traceback (most recent call last):\n  (f 0)\n"
                                   "Error: /: division by zero\n")

    def test_the_python_exception_behind_a_builtins_error_is_in_the_python_traceback(self):
        r = self.run_script(source="(define (f x) (/ 1 x))\n(list (f 0))\n",
                            env_extra={"LISP_PYTHON_TRACEBACK": "1"})
        self.assertIn("ZeroDivisionError: division by zero", r.stderr)
        self.assertIn("LispError: /: division by zero", r.stderr)

    def test_the_repl_shows_the_call_chain_for_an_error_and_keeps_going(self):
        r = run_cli("-", stdin="(define (f x) (car x))\n(list (f 5))\n(+ 20 22)\n(exit)\n")
        self.assertIn("Lisp traceback (most recent call last):\n  (f 5)\nError: car: not a pair: 5", r.stdout)
        self.assertIn("42", r.stdout)

    def test_verbose_flag_works_with_the_repl_too(self):
        r = run_cli("-v", "-", stdin="(define (f) 1)\n(f)\n(exit)\n")
        self.assertIn("> f", r.stdout)


class TestDebuggerCommandLine(unittest.TestCase):
    """What (abort) does at each top level of the console interpreter."""

    def test_abort_in_the_repl_goes_back_to_the_prompt_and_the_session_carries_on(self):
        r = run_cli("-", stdin="(define (f x) (* x 2))\n(break f)\n(f 5)\n(abort)\n(+ 1 2)\n(exit)\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--- break: entering f(5) ---", r.stdout)
        self.assertRegex(r.stdout, r"Aborted -- back at the top level\.\nlisp> 3\n")

    def test_the_repl_stop_shows_the_variables_and_can_be_resumed(self):
        r = run_cli("-", stdin="(define (f x) (* x 2))\n(break f)\n(f 5)\n(locals)\n(continue)\n(exit)\n")
        self.assertIn("((x . 5))", r.stdout)
        self.assertIn("--- f: resuming ---", r.stdout)
        self.assertRegex(r.stdout, r"resuming ---\n10\n")

    def test_abort_in_a_script_ends_the_run_with_status_1(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.lsp")
            with open(path, "w") as f:
                f.write('(define (f x) (* x 2)) (break f) (display "before ") (f 5) (display "after")')
            r = run_cli(path, stdin="(abort)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("before", r.stdout)
        self.assertNotIn("after", r.stdout)
        self.assertIn("Aborted.", r.stderr)

    def test_a_debug_hook_works_in_a_script_with_no_console_input(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.lsp")
            with open(path, "w") as f:
                f.write("(define (f x) (* x 2))\n(break f)\n"
                        "(set-debug-hook! (lambda (kind name args) (display (list kind name args)) (newline)))\n"
                        "(display (f 5)) (newline)\n")
            r = run_cli(path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "(break f (5))\n10\n")


class TestGuiErrorReport(unittest.TestCase):
    """The GUI's log shows the same call-chain error report as the console.
    Runs in a subprocess on Qt's offscreen platform so no window ever opens
    and no QApplication lingers in the test process."""

    PROGRAM = r"""
import sys
sys.path.insert(0, %r)
import lisp_gui
if not lisp_gui.PYQT_AVAILABLE:
    print("NO-QT"); sys.exit(0)
from PyQt6.QtWidgets import QApplication
app = QApplication([])
w = lisp_gui.LispMainWindow()
w.output_view.clear()
w.input_edit.setPlainText("(define (inner x) (car x)) (define (outer x) (list (inner x))) (outer 5)")
w._on_run()
print(w.output_view.toPlainText())
w.output_view.clear()
w.input_edit.setPlainText("(verbose 2) (define (sq n) (* n n)) (sq 4)")
w._on_run()
w.output_view.clear()
w.input_edit.setPlainText("(sq 3)")
w._on_run()
print("=====")
print(w.output_view.toPlainText())
w.input_edit.setPlainText('(display-table (make-table "id" (vector "a" "b") "n" #(1.5 2)) (list (list "n" ".2f")))')
w._on_run()
print("=====")
print(w.table_model.names, w.table_model.columns, w.table_model.aligns, w.tabs.tabText(w.tabs.currentIndex()))
""" % HERE

    def test_the_gui_log_shows_the_traceback_and_the_verbose_trace(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   LISP_INIT_FILE=os.path.join(tempfile.gettempdir(), "no-such-init.lsp"))
        r = subprocess.run([sys.executable, "-c", self.PROGRAM], capture_output=True, text=True,
                           env=env, timeout=120)
        if "NO-QT" in r.stdout:
            self.skipTest("PyQt6/matplotlib not installed")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        failing, traced, table = r.stdout.split("=====")
        self.assertIn("Lisp traceback (most recent call last):\n  (outer 5)\n  (inner 5)\nError: car: not a pair: 5",
                      failing)
        self.assertIn("> (sq 3)\n< (sq 3) => 9\n=> 9", traced)
        self.assertEqual(table.strip(), "['id', 'n'] [['a', 'b'], ['1.50', '2.00']] ['left', 'right'] Table")

    ABORT_PROGRAM = r"""
import sys
sys.path.insert(0, %r)
import lisp_gui
if not lisp_gui.PYQT_AVAILABLE:
    print("NO-QT"); sys.exit(0)
from PyQt6.QtWidgets import QApplication
app = QApplication([])
w = lisp_gui.LispMainWindow()
w.output_view.clear()
w.input_edit.setPlainText("(define (f x) x) (abort) (f 1)")
w._on_run()
print(w.output_view.toPlainText())
w.output_view.clear()
w.input_edit.setPlainText("(+ 1 2)")
w._on_run()
print("=====")
print(w.output_view.toPlainText())
""" % HERE

    def test_abort_in_the_gui_says_so_and_the_window_carries_on(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   LISP_INIT_FILE=os.path.join(tempfile.gettempdir(), "no-such-init.lsp"))
        r = subprocess.run([sys.executable, "-c", self.ABORT_PROGRAM], capture_output=True, text=True,
                           env=env, timeout=120)
        if "NO-QT" in r.stdout:
            self.skipTest("PyQt6/matplotlib not installed")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        aborted, next_run = r.stdout.split("=====")
        self.assertIn("Aborted.", aborted)
        self.assertIn("=> 3", next_run)


class TestKenKen(unittest.TestCase):
    """examples/kenken_example.lsp's solver. Its definitions are loaded once --
    the file up to where it solves its own puzzles, which takes a while for
    the 9 x 9 one (that runs with the slow examples)."""

    @classmethod
    def setUpClass(cls):
        cls.out = []
        cls.env = lisp_builtins.make_global_env(output=cls.out.append)
        with open(os.path.join(EXAMPLES, "kenken_example.lsp")) as f:
            source = f.read()
        cls.run_lisp(source[:source.index('(solve-and-show "A 4 x 4 puzzle"')])

    @classmethod
    def run_lisp(cls, src):
        result = lisp_core.NIL
        for expr in lisp_core.parse(src):
            result = lisp_core.seval(expr, cls.env)
        return result

    def show(self, src):
        return lisp_core.to_string(self.run_lisp(src))

    def test_the_4_by_4_and_6_by_6_puzzles(self):
        self.assertEqual(self.show("(kenken-solutions 4 puzzle-4)"), "(((4 3 1 2) (3 2 4 1) (2 1 3 4) (1 4 2 3)))")
        self.assertEqual(self.show("(solve-kenken 6 puzzle-6)"),
                         "((3 6 5 1 4 2) (4 1 6 5 2 3) (6 4 3 2 1 5) (5 3 2 4 6 1) (1 2 4 3 5 6) (2 5 1 6 3 4))")

    def test_a_puzzle_with_two_solutions_and_one_with_none(self):
        self.assertEqual(self.show("(kenken-solutions 2 '(((11 12 21 22) (+ 6))))"), "(((1 2) (2 1)) ((2 1) (1 2)))")
        self.assertEqual(self.show("(kenken-solutions 2 '(((11 12 21 22) (+ 6))) :limit 1)"), "(((1 2) (2 1)))")
        self.assertEqual(self.show("(solve-kenken 2 '(((11 12) (+ 3)) ((21 22) (* 3))))"), "#f")

    def test_the_operations(self):
        for src, expected in [("(comes-out? '+ 17 '(9 8))", "#t"), ("(comes-out? '* 12 '(3 4))", "#t"),
                              ("(comes-out? '- 2 '(3 5))", "#t"), ("(comes-out? '/ 3 '(6 2))", "#t"),
                              ("(comes-out? '/ 3 '(2 6))", "#t"), ("(comes-out? '/ 3 '(4 2))", "#f"),
                              ("(comes-out? '- 1 '(6 2 3))", "#t"), ("(comes-out? '/ 2 '(12 3 2))", "#t"),
                              ("(comes-out? '= 4 '(4))", "#t")]:
            with self.subTest(src=src):
                self.assertEqual(self.show(src), expected)
        # no digit twice in a row or column, even within a cage -- but twice in a
        # cage is fine, when the cells don't share a row or column (11 and 22)
        self.assertEqual(self.show("(combinations-for '(11 12 22) '+ 5 3)"), "((1 3 1) (2 1 2))")

    def test_a_puzzle_that_isnt_well_formed(self):
        for src, message in [
                ("(solve-kenken 2 '(((11 12) (+ 3)) ((12 21 22) (+ 3))))", "cell 12 is in two cages"),
                ("(solve-kenken 2 '(((11 12) (+ 3)) ((21) (= 1))))", "cell 22 isn't in any cage"),
                ("(solve-kenken 2 '(((11 12) (% 3)) ((21 22) (+ 3))))", "the operation must be + - * / or =, not %"),
                ("(solve-kenken 2 '(((11 12) (= 3)) ((21 22) (+ 3))))", "an = cage has just one cell"),
                ("(solve-kenken 2 '(((11) (- 1)) ((12 21 22) (+ 3))))", "a - or / cage needs at least two cells"),
                ("(solve-kenken 2 '(((11 13) (+ 3)) ((21 22) (+ 3))))", "there's no cell 13 in a 2 x 2 grid")]:
            with self.subTest(src=src):
                with self.assertRaises(lisp_core.LispError) as caught:
                    self.run_lisp(src)
                self.assertIn(message, str(caught.exception))

    def test_drawing_a_puzzle_as_text(self):
        del self.out[:]
        self.run_lisp("(show-kenken 4 puzzle-4 :solution (solve-kenken 4 puzzle-4))")
        self.assertEqual("".join(self.out).splitlines()[:7],
                         ["+-----+-----+-----+-----+",
                          "|9+   |3×         |2    |",
                          "|  4  |  3     1  |  2  |",
                          "+     +-----+-----+-----+",
                          "|           |9+         |",
                          "|  3     2  |  4     1  |",
                          "+-----+-----+-----+     +"])


class TestChessProgram(unittest.TestCase):
    """examples/chess.lsp: its move generator gets the known perft counts, it
    reads and writes algebraic notation, and its search finds a mate."""

    @classmethod
    def setUpClass(cls):
        cls.out = []
        cls.env = lisp_builtins.make_global_env(output=cls.out.append)
        cls.run_lisp('(load "chess.lsp")')

    @classmethod
    def run_lisp(cls, src):
        result = lisp_core.NIL
        for expr in lisp_core.parse(src):
            result = lisp_core.seval(expr, cls.env)
        return result

    def show(self, src):
        return lisp_core.to_string(self.run_lisp(src))

    def assertLispError(self, src, fragment):
        with self.assertRaises(lisp_core.LispError, msg="source: %s" % src) as caught:
            self.run_lisp(src)
        self.assertIn(fragment, str(caught.exception))

    def test_the_number_of_move_sequences_is_right(self):
        """perft: the counts every chess program must get, from positions with
        castling, en passant, promotions, and pins."""
        for fen, depth, expected in [
                ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -", 2, 400),
                ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -", 1, 48),
                ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -", 2, 191),
                ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq -", 2, 264),
                ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ -", 1, 44)]:
            with self.subTest(fen=fen):
                self.assertEqual(self.show('(count-positions (fen->position "%s") %d)' % (fen, depth)),
                                 str(expected))

    def test_moves_are_written_in_algebraic_notation(self):
        def notation(fen):
            return self.show('(let ((p (fen->position "%s"))) '
                             '(sort (map (lambda (m) (move->text p m)) (legal-moves p))))' % fen)
        # two knights and two rooks that can reach the same square
        self.assertEqual(notation("4k3/8/8/8/R7/8/8/RN2KN2 w - -"),
                         '("Kd1" "Kd2" "Ke2" "Kf2" "Na3" "Nbd2" "Nc3" "Ne3" "Nfd2" "Ng3" "Nh2" "R1a2" '
                         '"R1a3" "R4a2" "R4a3" "Ra5" "Ra6" "Ra7" "Ra8+" "Rb4" "Rc4" "Rd4" "Re4+" "Rf4" '
                         '"Rg4" "Rh4")')
        # promotion, with and without a capture
        self.assertEqual(notation("3r4/4P3/8/8/8/8/k7/4K3 w - -"),
                         '("Ke2" "Kf1" "Kf2" "e8=B" "e8=N" "e8=Q" "e8=R" "exd8=B" "exd8=N" "exd8=Q" "exd8=R")')

    def test_typed_moves_are_found(self):
        self.run_lisp("""(define e (play-moves (initial-position) '("e4" "Nf6" "e5" "d5")))""")
        self.assertEqual(self.show('(move->text e (find-move e "exd6"))'), '"exd6"')     # en passant
        self.assertEqual(self.show('(find-move e "e5xd6")'), "(65 74)")
        self.assertEqual(self.show('(find-move e "exd6 e.p.")'), "#f")
        self.assertEqual(self.show('(find-move e "nc3")'), "#f")                    # N is a knight; n isn't
        self.run_lisp('(define c (fen->position "r3k2r/8/8/8/8/8/8/R3K2R w KQkq -"))')
        self.assertEqual(self.show('(move->text c (find-move c "0-0-0"))'), '"O-O-O"')
        self.assertEqual(self.show('(move->text c (find-move c "O-O"))'), '"O-O"')
        self.run_lisp('(define p (fen->position "8/4P3/8/8/8/8/k7/4K3 w - -"))')
        self.assertEqual(self.show('(move->text p (find-move p "e7e8q"))'), '"e8=Q"')
        self.assertEqual(self.show('(move->text p (find-move p "e8N"))'), '"e8=N"')

    def test_castling_rights_and_the_en_passant_square_follow_the_moves(self):
        self.run_lisp("""(define p (play-moves (initial-position) '("e4" "e5" "Ke2" "d5" "Nf3" "d4" "c4")))""")
        self.assertEqual(self.show("(position-castling p)"), "(black-kingside black-queenside)")
        self.assertEqual(self.show("(square-name (position-en-passant p))"), '"c3"')
        self.assertEqual(self.show('(move->text p (find-move p "dxc3"))'), '"dxc3"')

    def test_the_search_finds_mate_in_one_and_mate_in_two(self):
        self.run_lisp("""(define scholars (play-moves (initial-position) '("e4" "e5" "Bc4" "Nc6" "Qh5" "Nf6")))""")
        self.assertEqual(self.show("(move->text scholars (first (choose-move scholars 2)))"), '"Qxf7#"')
        self.run_lisp('(define back-rank (fen->position "2r3k1/5ppp/8/8/8/8/3R1PPP/3R2K1 w - -"))')
        self.assertEqual(self.show("(move->text back-rank (first (choose-move back-rank 3)))"), '"Rd8+"')

    def test_the_game_is_over_at_checkmate_and_stalemate(self):
        self.run_lisp("""(define mated (play-moves (initial-position) '("f3" "e5" "g4" "Qh4")))""")
        self.assertEqual(self.show("(game-over-message mated)"), '"Checkmate: Black wins."')
        self.run_lisp('(define stalemate (fen->position "7k/5Q2/6K1/8/8/8/8/8 b - -"))')
        self.assertEqual(self.show("(game-over-message stalemate)"), '"Stalemate: a draw."')
        self.assertEqual(self.show("(game-over-message (initial-position))"), "#f")

    def test_a_game_against_the_computer(self):
        """play-chess reads moves with read-line: here a bad move, a good one,
        and quit."""
        typed = iter(["Ke3", "f3", "quit"])
        with mock.patch("builtins.input", lambda prompt="": next(typed)):
            self.run_lisp("(play-chess)")
        out = "".join(self.out)
        self.assertIn('"Ke3" isn\'t a legal move here.', out)
        self.assertIn("Black plays ", out)
        self.assertIn("The game: 1.f3 ", out)
        self.assertIn("  1  ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖", out)


    # -- finding only the captures ---------------------------------------------------------------

    SPARSE_POSITIONS = {      # few pieces, with captures to make: quick to search
        "queens": "4k3/pp3ppp/8/3q4/3P4/2N5/PP3PPP/3QK3 w - -",
        "rooks and a knight": "2r1k3/pp3ppp/2n5/3p4/3P1B2/2N5/PP3PPP/2R1K3 w - -",
    }
    MIDDLEGAMES = {          # all the pieces: a minute or so to search them
        "Italian game": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6", "d3", "d6"],
        "Sicilian": ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6", "Be3", "e5", "Nb3", "Be6"],
    }

    def test_capture_moves_are_the_candidate_moves_that_capture_or_promote(self):
        """The faster generator finds what finding every candidate move and keeping the captures and the
        promotions does, in the same order: on positions with promotions (with a capture, and without),
        en passant, castling, and check, and on every position of some games of random moves."""
        self.run_lisp("""
          (define (by-filtering p)
            (filter (lambda (m) (or (capture? p m) (move-promotion m))) (candidate-moves p)))
          (define (same-captures? p) (equal? (capture-moves p) (by-filtering p)))
          (define (squares-of-captures fen) (sort (map move->squares (capture-moves (fen->position fen)))))""")
        for fen in ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
                    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -",
                    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -",
                    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq -",
                    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ -",
                    "rnbqkbnr/pppp1ppp/8/3Pp3/8/8/PPP1PPPP/RNBQKBNR w KQkq e6",
                    "rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3",
                    "8/P6k/8/8/8/8/p6K/8 w - -", "8/P6k/8/8/8/8/p6K/8 b - -",
                    "1n2k3/P7/8/8/8/8/8/4K3 w - -", "4k3/8/8/8/8/8/p7/1N2K3 b - -",
                    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq -", "r3k2r/8/8/8/8/8/8/R3K2R b KQkq -",
                    "4k3/8/8/8/8/8/4q3/4K3 w - -"]:
            with self.subTest(fen=fen):
                self.assertEqual(self.show('(same-captures? (fen->position "%s"))' % fen), "#t")
        # and these really are the kinds of move being checked
        self.assertEqual(self.show('(squares-of-captures "8/P6k/8/8/8/8/p6K/8 w - -")'), '("a7a8B" "a7a8N" "a7a8Q" "a7a8R")')
        self.assertEqual(self.show('(length (capture-moves (fen->position "1n2k3/P7/8/8/8/8/8/4K3 w - -")))'), "8")
        self.assertEqual(self.show('(squares-of-captures "rnbqkbnr/pppp1ppp/8/3Pp3/8/8/PPP1PPPP/RNBQKBNR w KQkq e6")'), '("d5e6")')
        self.assertEqual(self.show('(squares-of-captures "r3k2r/8/8/8/8/8/8/R3K2R w KQkq -")'), '("a1a8" "h1h8")')   # not O-O
        self.assertEqual(self.show('(squares-of-captures "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")'), "()")
        self.run_lisp("""
          (random-seed 11)
          (define checked 0)
          (define all-the-same #t)
          (loop for game from 1 to 12
                do (let ((position (initial-position)) (ply 0) (moves '()))
                     (while (and (< ply 60) (begin (set! moves (legal-moves position)) (not (null? moves))))
                       (unless (same-captures? position) (set! all-the-same #f))
                       (incf checked)
                       (set! position (make-move position (list-ref moves (random-int 0 (- (length moves) 1)))))
                       (incf ply))))""")
        self.assertEqual(self.show("all-the-same"), "#t")
        self.assertGreater(self.run_lisp("checked"), 500)

    # -- a key for a position ------------------------------------------------------------------------

    def test_a_position_s_key_is_the_same_for_the_same_position_however_it_was_reached(self):
        key = lambda src: self.show("(position-key %s)" % src)
        self.assertEqual(key("""(play-moves (initial-position) '("e4" "e5" "Nf3"))"""),
                         key("""(play-moves (initial-position) '("Nf3" "e5" "e4"))"""))         # the other way round
        self.assertNotEqual(key("""(play-moves (initial-position) '("e4" "e5" "Nf3"))"""),
                            key("""(play-moves (initial-position) '("e4" "e5" "Nc3"))"""))
        self.assertNotEqual(key('(fen->position "4k3/8/8/8/8/8/8/4K3 w - -")'),
                            key('(fen->position "4k3/8/8/8/8/8/8/4K3 b - -")'))                  # whose move it is
        self.assertNotEqual(key('(fen->position "r3k2r/8/8/8/8/8/8/R3K2R w KQkq -")'),
                            key('(fen->position "r3k2r/8/8/8/8/8/8/R3K2R w Qkq -")'))            # castling
        # a square skipped by a pawn counts only if a pawn could capture there
        self.assertEqual(key("""(play-moves (initial-position) '("e4"))"""),
                         key('(fen->position "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")'))
        self.assertNotEqual(key('(fen->position "rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3")'),
                            key('(fen->position "rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq -")'))
        self.assertEqual(self.show('(string? (position-key (initial-position)))'), "#t")
        self.run_lisp('(hash-table-set! (make-hash-table) (position-key (initial-position)) 1)')       # a string can be a key

    # -- remembering what the search of captures found -----------------------------------------------

    def test_a_remembered_entry_answers_only_a_search_it_is_enough_for(self):
        for entry, alpha, beta, expected in [
                ("(30 exact)", -100, 100, "(30)"), ("(30 exact)", 50, 80, "(30)"),
                ("(30 lower)", -100, 20, "(30)"), ("(30 lower)", -100, 30, "(30)"), ("(30 lower)", -100, 31, "#f"),
                ("(30 upper)", 40, 100, "(30)"), ("(30 upper)", 30, 100, "(30)"), ("(30 upper)", 29, 100, "#f")]:
            with self.subTest(entry=entry, alpha=alpha, beta=beta):
                self.assertEqual(self.show("(entry-answer '%s %d %d)" % (entry, alpha, beta)), expected)

    def test_only_the_last_few_moves_are_remembered(self):
        self.addCleanup(self.run_lisp, "(forget-positions!)")
        self.run_lisp("(forget-positions!)")
        self.run_lisp("""(hash-table-set! (first *tables*) "old" '(1 exact))""")
        self.run_lisp("(remember-a-new-move!)")
        self.run_lisp("(remember-a-new-move!)")
        self.assertEqual(self.show("(list (length *tables*) moves-remembered)"), "(3 3)")
        self.assertEqual(self.show('(remembered-answer "old" -10 10)'), "(1)")          # in the oldest table still
        self.run_lisp("(remember-a-new-move!)")
        self.assertEqual(self.show("(length *tables*)"), "3")
        self.assertEqual(self.show('(remembered-answer "old" -10 10)'), "#f")           # and now it's gone
        self.run_lisp("""(hash-table-set! (first *tables*) "new" '(2 exact))""")
        self.run_lisp("(forget-positions!)")
        self.assertEqual(self.show('(remembered-answer "new" -10 10)'), "#f")

    def test_remembering_changes_no_move_or_value_and_saves_searching(self):
        """Three searches in a row -- the computer's move, a reply, and its next move -- with and without
        the table: the same moves and values, and fewer positions searched with it."""
        self.addCleanup(self.run_lisp, "(set! use-table #t)")
        self.run_lisp("""
          (define (three-searches position depth)
            (set! *positions-searched* 0)
            (let* ((c1 (choose-move position depth))
                   (p1 (make-move position (first c1)))
                   (c2 (choose-move p1 depth))
                   (p2 (make-move p1 (first c2)))
                   (c3 (choose-move p2 depth)))
              (list (map (lambda (c) (list (move->squares (first c)) (second c))) (list c1 c2 c3))
                    *positions-searched*)))""")
        positions = [(name, '(fen->position "%s")' % fen, depth) for name, fen in self.SPARSE_POSITIONS.items()
                     for depth in (2, 3)]
        positions += [(name, "(play-moves (initial-position) '(%s))" % " ".join('"%s"' % m for m in moves), 2)
                      for name, moves in self.MIDDLEGAMES.items()]
        for name, position, depth in positions:
            with self.subTest(position=name, depth=depth):
                self.run_lisp("(set! use-table #f)")
                without = self.run_lisp("(three-searches %s %d)" % (position, depth))
                self.assertEqual(self.show("(hash-table-count (first *tables*))"), "0")        # nothing was kept
                self.run_lisp("(set! use-table #t) (forget-positions!)")
                with_table = self.run_lisp("(three-searches %s %d)" % (position, depth))
                self.assertEqual(lisp_core.to_string(with_table.car), lisp_core.to_string(without.car))
                self.assertLess(with_table.cdr.car, without.cdr.car)

    # -- variety -------------------------------------------------------------------------------------

    def test_the_wiggle_is_small_the_same_every_time_and_other_with_other_tastes(self):
        self.addCleanup(self.run_lisp, "(set-variety! 0)")
        self.run_lisp("""
          (random-seed 5)
          (define boards '())
          (loop for game from 1 to 3
                do (let ((position (initial-position)) (ply 0) (moves '()))
                     (while (and (< ply 40) (begin (set! moves (legal-moves position)) (not (null? moves))))
                       (set! boards (cons (position-board position) boards))
                       (set! position (make-move position (list-ref moves (random-int 0 (- (length moves) 1)))))
                       (incf ply))))
          (define (wiggles) (map wiggle boards))
          (set-variety! 0)
          (define none (wiggles))
          (set-variety! 3)
          (define games-tastes (wiggles))
          (define again (wiggles))
          (set-variety! 3)
          (define other-tastes (wiggles))""")
        # a new game's tastes mean what was remembered, scored with the old ones, is forgotten
        self.run_lisp("""(hash-table-set! (first *tables*) "kept" '(1 exact))""")
        self.assertEqual(self.show('(remembered-answer "kept" -10 10)'), "(1)")
        self.run_lisp("(set-variety! 3)")
        self.assertEqual(self.show('(remembered-answer "kept" -10 10)'), "#f")
        self.assertEqual(self.show("(apply + none)"), "0")                       # no variety, no wiggle
        wiggles = [int(w) for w in lisp_core.pairs_to_list(self.run_lisp("games-tastes"))]
        self.assertGreater(len(wiggles), 100)
        self.assertEqual(set(wiggles), {-3, -2, -1, 0, 1, 2, 3})               # all of them, ...
        self.assertLess(max(wiggles.count(w) for w in set(wiggles)), 2.2 * len(wiggles) / 7)    # ... about evenly
        self.assertAlmostEqual(sum(wiggles) / len(wiggles), 0, delta=0.4)
        self.assertEqual(self.show("(equal? games-tastes again)"), "#t")          # the same board, the same wiggle
        self.assertEqual(self.show("(equal? games-tastes other-tastes)"), "#f")   # another game, other wiggles
        self.assertEqual(self.show("(integer? (first games-tastes))"), "#t")

    def test_the_score_is_wiggled_by_no_more_than_the_variety(self):
        self.addCleanup(self.run_lisp, "(set-variety! 0)")
        self.run_lisp("""
          (define sample (play-moves (initial-position) '("e4" "e5" "Nf3" "Nc6" "Bc4")))
          (set-variety! 0)
          (define score-without (evaluate sample))
          (set-variety! 4)
          (define score-with (evaluate sample))""")
        self.assertLessEqual(abs(self.run_lisp("(- score-with score-without)")), 4)

    def test_variety_varies_the_play_but_never_by_much(self):
        """Without it the program always plays e4 from the opening; with it, e4 or d4, which are equally
        good to look 2 moves ahead, depending on the game. And any move it plays is worth at least the best
        less twice the variety, for every score is within the variety of what it would be without."""
        self.addCleanup(self.run_lisp, "(set-variety! 0)")
        self.run_lisp("""
          (define big (* 2 checkmate-value))
          (define (plain-values position depth)
            (map (lambda (move) (cons (move->squares move)
                                      (- (alpha-beta (make-move position move) (- depth 1) (- big) big))))
                 (legal-moves position)))
          (define (choice-in-game position depth seed amount)
            (random-seed seed)
            (set-variety! amount)
            (move->squares (first (choose-move position depth))))
          (define start-position (initial-position))
          (define queens (fen->position "%s"))""" % self.SPARSE_POSITIONS["queens"])
        self.assertEqual(self.show("(choice-in-game start-position 2 1 0)"), '"e2e4"')              # without variety, always this
        chosen = {str(self.run_lisp("(choice-in-game start-position 2 %d 3)" % seed)) for seed in range(1, 11)}
        self.assertEqual(chosen, {"e2e4", "d2d4"})
        self.run_lisp("(set-variety! 0) (define queens-values (plain-values queens 2)) "
                      "(define queens-best (apply max (map cdr queens-values)))")
        for seed in range(1, 11):
            with self.subTest(seed=seed):
                self.run_lisp("(define queens-pick (choice-in-game queens 2 %d 3))" % seed)
                self.run_lisp("(set-variety! 0)")
                self.assertGreaterEqual(self.run_lisp("(cdr (assoc queens-pick queens-values))"),
                                        self.run_lisp("queens-best") - 6)

    def test_remembering_changes_no_move_with_variety_either(self):
        """The same tastes give a position the same score every time, so the table is as right with them."""
        self.addCleanup(self.run_lisp, "(set! use-table #t)")
        self.addCleanup(self.run_lisp, "(set-variety! 0)")
        for name, fen in self.SPARSE_POSITIONS.items():
            for depth in (2, 3):
                answers = []
                for table in ("#f", "#t"):
                    self.run_lisp("(random-seed 8) (set-variety! 3) (set! use-table %s)" % table)
                    answers.append(self.show('(choose-move (fen->position "%s") %d)' % (fen, depth)))
                with self.subTest(position=name, depth=depth):
                    self.assertEqual(answers[0], answers[1])

    # -- the opening book ----------------------------------------------------------------------------

    def test_a_book_has_the_winner_s_moves_under_the_positions_they_were_played_in(self):
        self.run_lisp("""
          (define tiny (make-book '((white "e2e4 e7e5 g1f3 b8c6")
                                    (white "e2e4 c7c5 g1f3")
                                    (black "d2d4 g8f6 c2c4 e7e6"))))
          (define (book-squares book position) (sort (map move->squares (hash-table-ref book (position-key position) '()))))
          (define (after . moves) (play-moves (initial-position) moves))""")
        # white's moves from the games white won; black's from the game black won
        self.assertEqual(self.show("(book-squares tiny (initial-position))"), '("e2e4" "e2e4")')       # two games played it
        self.assertEqual(self.show('(book-squares tiny (after "e4" "e5"))'), '("g1f3")')
        self.assertEqual(self.show('(book-squares tiny (after "e4" "c5"))'), '("g1f3")')
        self.assertEqual(self.show('(book-squares tiny (after "e4"))'), "()")        # black lost both: not black's moves
        self.assertEqual(self.show('(book-squares tiny (after "d4"))'), '("g8f6")')  # black won this one
        self.assertEqual(self.show('(book-squares tiny (after "d4" "Nf6" "c4"))'), '("e7e6")')
        self.assertEqual(self.show('(book-squares tiny (after "d4" "Nf6"))'), "()")  # white lost it: not white's
        self.assertEqual(self.show('(hash-table-count tiny)'), "5")      # the opening; after 1.e4 e5; after 1.e4 c5; after 1.d4; after 1.d4 Nf6 2.c4
        # the same position the other way round is the same entry
        self.assertEqual(self.show('(book-squares tiny (after "e4" "e5"))'), self.show('(book-squares tiny (play-moves (initial-position) \'("e4" "e5")))'))
        # a move that isn't legal is an error, not a book that plays it
        self.assertLispError('(make-book \'((white "e2e4 e7e5 e1e3")))', "isn't legal here")
        self.assertLispError('(make-book \'((white "e2e5")))', "isn't legal here")
        # nor one the pieces can make but that leaves the king in check: 1.e4 f6 2.Qh5+ and Black ignores it
        self.assertLispError('(make-book \'((white "e2e4 f7f6 d1h5 b8c6")))', "isn't legal here")
        self.run_lisp('(make-book \'((white "e2e4 f7f6 d1h5 g7g6")))')                 # (g6 blocks the check: that's fine)

    def test_the_book_plays_one_of_the_moves_at_random_and_none_off_the_book(self):
        self.run_lisp("""
          (set! *book* (make-book '((white "e2e4 e7e5") (white "e2e4") (white "d2d4") (white "g1f3"))))
          (random-seed 2)
          (define book-draws (map (lambda (i) (move->squares (book-move (initial-position)))) (iota 200)))""")
        self.addCleanup(self.run_lisp, "(set! *book* #f)")
        draws = [str(d) for d in lisp_core.pairs_to_list(self.run_lisp("book-draws"))]
        self.assertEqual(set(draws), {"e2e4", "d2d4", "g1f3"})
        self.assertGreater(draws.count("e2e4"), draws.count("d2d4"))              # two games played it, one played d4
        self.assertEqual(self.show("""(book-move (play-moves (initial-position) '("a4")))"""), "#f")
        # a transposition is in the book
        self.run_lisp("""(set! *book* (make-book '((black "e2e4 e7e5 g1f3 b8c6"))))""")
        self.assertEqual(self.show("""(move->squares (book-move (play-moves (initial-position) '("Nf3" "e5" "e4"))))"""), '"b8c6"')

    def test_the_book_that_comes_with_the_program(self):
        """chess_book.lsp: every move is legal where it's played; as many games won by each color; the
        same number of the winner's moves in each."""
        self.run_lisp('(load "chess_book.lsp") (define shipped (make-book book-games))')
        games = lisp_core.pairs_to_list(self.run_lisp("book-games"))
        winners = [str(g.car) for g in games]
        self.assertEqual((winners.count("white"), winners.count("black")), (len(games) // 2, len(games) // 2))
        self.assertGreaterEqual(len(games), 12)
        moves_by_winner = {len(str(g.cdr.car).split()) for g in games if str(g.car) == "white"}, \
            {len(str(g.cdr.car).split()) for g in games if str(g.car) == "black"}
        self.assertEqual(len(moves_by_winner[0]), 1)                               # (white's last move is ply 2n - 1)
        self.assertEqual(moves_by_winner[1], {min(moves_by_winner[0]) + 1})        # (black's is ply 2n)
        self.assertGreaterEqual(min(moves_by_winner[0]), 11)
        # the opening position is in it, with a move for white
        self.assertGreater(self.run_lisp("(length (hash-table-ref shipped (position-key (initial-position)) '()))"), 3)

    def test_computer_move_uses_the_book_if_asked_to_and_searches_otherwise(self):
        self.addCleanup(self.run_lisp, "(set! *book* #f)")
        self.out.clear()
        self.run_lisp("(set! *book* (make-book '((white \"e2e4\"))))")
        move = self.run_lisp("(computer-move (initial-position) 1 :book #t)")
        self.assertEqual(self.show("(move->squares (computer-move (initial-position) 1 :book #t))"), '"e2e4"')
        self.assertIn("White plays e4   (from the opening book)", "".join(self.out))
        self.assertEqual(lisp_core.to_string(move), "(35 55)")             # e2 to e4
        self.out.clear()
        self.run_lisp("(computer-move (initial-position) 1 :book #f)")                  # not asked to: it looks
        self.assertIn("looked at", "".join(self.out))
        self.assertNotIn("opening book", "".join(self.out))
        self.out.clear()
        self.run_lisp("""(computer-move (play-moves (initial-position) '("a4")) 1 :book #t)""")      # not in the book: it looks
        self.assertIn("looked at", "".join(self.out))

    def test_a_game_opens_from_the_book_and_leaves_the_variety_off_afterwards(self):
        typed = iter(["e4", "quit"])
        self.out.clear()
        self.run_lisp("(random-seed 5)")
        with mock.patch("builtins.input", lambda prompt="": next(typed)):
            self.run_lisp("(play-chess)")
        out = "".join(self.out)
        self.assertIn("Black plays ", out)
        self.assertIn("(from the opening book)", out)
        self.assertEqual(self.show("*variety*"), "0")
        # :book #f and :variety are keywords of play-chess
        typed = iter(["quit"])
        self.out.clear()
        with mock.patch("builtins.input", lambda prompt="": next(typed)):
            self.run_lisp("(play-chess :human black :book #f :variety 0)")
        self.assertNotIn("opening book", "".join(self.out))


class TestChessBookTool(unittest.TestCase):
    """tools/make_chess_book.py: reading PGN files, choosing games, and writing the book with chess.lsp's
    own reading of the moves."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("make_chess_book", os.path.join(HERE, "tools", "make_chess_book.py"))
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    WHITE_WINS = ("1. e4 { [%eval 0.2] [%clk 1:59:55] } 1... e5 { [%clk 1:59:50] } 2. Nf3 $1 Nc6 "
                  "3. Bb5 (3. Bc4 Bc5 (3... Nf6 4. d3)) 3... a6!? 4. Ba4 Nf6 5. O-O Be7 6. Bxc6 dxc6 7. d3 Nd7 "
                  "8. Nc3 O-O 9. Be3 1-0")
    BLACK_WINS = ("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. d3 d6 6. c3 g6 7. O-O Bg7 8. Re1 O-O 9. Nbd2 0-1")

    def pgn(self, moves, result="1-0", opening="Ruy Lopez: Closed", white="Alpha, Ann", black="Beta, Bob",
            elo=(2700, 2650), time_control="40/7200:0+10", url="https://lichess.org/broadcast/test/round-3/AAAA/BBBB"):
        """One game as PGN text, with the moves as given and result as the tags say."""
        tags = [("Event", "Test Open"), ("Site", "Somewhere"), ("Date", "2026.01.02"), ("Round", "3.1"),
                ("White", white), ("Black", black), ("Result", result), ("WhiteElo", elo[0]), ("BlackElo", elo[1]),
                ("TimeControl", time_control), ("ECO", "C85"), ("Opening", opening), ("GameURL", url)]
        return "\n".join('[%s "%s"]' % tag for tag in tags) + "\n\n" + moves + "\n"

    def test_the_moves_are_read_from_movetext_with_everything_else_taken_out(self):
        moves = self.tool.moves_of(
            "1. e4 { [%eval 0.2] [%clk 1:59:55] } 1... e5 { [%clk 1:59:50] } 2. Nf3 $1 Nc6 "
            "3. Bb5 (3. Bc4 Bc5 (3... Nf6 4. d3)) 3... a6!? 4. Ba4 Nf6 5. O-O Be7 ; to the end of the line\n"
            "6. Bxc6 dxc6 7.d3 Nd7 8. Nc3 Rae1 e8=Q+ Qh4xe1# 0-0-0 1-0")
        self.assertEqual(moves, ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Bxc6", "dxc6", "d3",
                                 "Nd7", "Nc3", "Rae1", "e8=Q+", "Qh4xe1#", "0-0-0"])
        for result in ("1-0", "0-1", "1/2-1/2", "*"):
            self.assertEqual(self.tool.moves_of("1. e4 e5 " + result), ["e4", "e5"])
        for bad in ("1. e4 Zf3", "1. e4 e9", "1. e4 hello", "1. e4 Nf3x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.tool.moves_of(bad)

    def test_games_are_split_and_quick_ones_are_known(self):
        text = self.pgn(self.WHITE_WINS) + "\n" + self.pgn(self.BLACK_WINS, result="0-1", white="Gamma, Gus")
        games = list(self.tool.games_in(text))
        self.assertEqual(len(games), 2)
        self.assertEqual((games[0][0]["White"], games[1][0]["White"]), ("Alpha, Ann", "Gamma, Gus"))
        self.assertEqual(games[0][0]["GameURL"], "https://lichess.org/broadcast/test/round-3/AAAA/BBBB")
        self.assertEqual(self.tool.moves_of(games[1][1]), self.tool.moves_of(self.BLACK_WINS))
        for time_control, quick in [("600+0", True), ("180+2", True), ("1799+0", True), ("1800+0", False),
                                    ("5400+30", False), ("40/7200:0+10", False), (None, False), ("", False),
                                    ("120 minutes for the first 40 moves, followed by 30 minutes", False)]:
            with self.subTest(time_control=time_control):
                self.assertEqual(self.tool.is_quick(time_control), quick)

    def test_only_long_decisive_slow_games_of_strong_players_are_candidates(self):
        long_game = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 1-0"          # 8 plies: 4 moves
        texts = [
            self.pgn(long_game, white="Kept, White"),
            self.pgn(long_game, result="1/2-1/2", white="Drawn, Game"),
            self.pgn("1. e4 e5 2. Nf3 1-0", white="Short, Game"),
            self.pgn(long_game, time_control="600+0", white="Quick, Game"),
            self.pgn(long_game, elo=(2700, 2599), white="Weak, Opponent"),
            self.pgn(long_game, result="*", white="Unfinished, Game"),
            self.pgn(long_game.replace("1-0", "0-1"), result="0-1", white="Kept, Black"),
        ]
        found = self.tool.candidates(["\n".join(texts)], min_moves=4, min_rating=2600)
        self.assertEqual([g.headers["White"] for g in found], ["Kept, White", "Kept, Black"])
        self.assertEqual([g.winner for g in found], ["white", "black"])
        self.assertEqual(len(found[0].moves), 8)
        self.assertEqual(len(self.tool.candidates(["\n".join(texts)], min_moves=5, min_rating=2600)), 0)   # needs 9 plies

    def test_the_openings_and_games_are_chosen_by_the_rules(self):
        Game = self.tool.Game
        game = lambda name, opening, winner: Game({"White": name, "Opening": opening}, ["e4"], winner)
        games = [
            game("a1", "Sicilian Defense: Najdorf", "white"), game("a2", "Sicilian Defense: Taimanov", "white"),
            game("a3", "Sicilian Defense: Najdorf", "black"),
            game("b1", "French Defense: Tarrasch", "white"), game("b2", "French Defense: Winawer", "white"),
            game("c1", "Italian Game: Classical", "black"), game("c2", "Italian Game: Evans", "white"),
            game("d1", "Caro-Kann Defense", "white"),
            game("e1", "English Opening: Symmetrical", "white"), game("e2", "English Opening: Symmetrical", "black"),
            game("e3", "English Opening: Four Knights", "black"),
        ]
        self.assertEqual(self.tool.family(games[0]), "Sicilian Defense")
        # the English and the Sicilian (3 games each, the English first, alphabetically), then the Italian (2):
        # both colors have won a game in each; the French and Caro-Kann have not
        chosen = self.tool.choose(games, openings=3)
        self.assertEqual([g.headers["White"] for g in chosen], ["e1", "e3", "a1", "a3", "c2", "c1"])
        # (the English: black's game in another variation than white's, e3 not e2; the Sicilian had no other)
        self.assertEqual([g.headers["White"] for g in self.tool.choose(games, openings=1)], ["e1", "e3"])
        self.assertEqual([g.winner for g in chosen], ["white", "black"] * 3)
        self.assertEqual(self.tool.choose(games[3:5], openings=5), [])          # white won both: no opening qualifies
        # the same number of games: alphabetical
        pairs = [game("z1", "Zukertort Opening", "white"), game("z2", "Zukertort Opening", "black"),
                 game("m1", "Modern Defense", "white"), game("m2", "Modern Defense", "black")]
        self.assertEqual([g.headers["White"] for g in self.tool.choose(pairs, openings=1)], ["m1", "m2"])

    def test_how_much_of_a_game_is_kept(self):
        Game = self.tool.Game
        long_white = Game({}, ["m"] * 60, "white")
        long_black = Game({}, ["m"] * 60, "black")
        self.assertEqual(self.tool.plies_to_keep(long_white, 8), 15)             # through white's 8th move
        self.assertEqual(self.tool.plies_to_keep(long_black, 8), 16)             # through black's
        self.assertEqual(self.tool.plies_to_keep(Game({}, ["m"] * 10, "white"), 8), 10)
        self.assertEqual(self.tool.plies_to_keep(long_white, 1), 1)
        self.assertEqual(self.tool.plies_to_keep(long_black, 1), 2)

    def test_notation_and_comments(self):
        self.assertEqual(self.tool.standard_notation(["e4", "e5", "Nf3"]), "1.e4 e5 2.Nf3")
        self.assertEqual(self.tool.surname("Caruana, Fabiano"), "Caruana")
        self.assertEqual(self.tool.surname("Praggnanandhaa R"), "Praggnanandhaa R")
        lines = self.tool.wrap_comment("word " * 60, width=40)
        self.assertGreater(len(lines), 5)
        self.assertTrue(all(line.startswith("; ") and len(line) <= 40 for line in lines))
        self.assertEqual(" ".join(line[2:] for line in lines), ("word " * 60).strip())
        # a | between two words keeps them together, wherever the line would have broken
        lines = self.tool.wrap_comment("Chess 2026 | Masters and more", width=17)
        self.assertTrue(any("2026 | Masters" in line for line in lines))
        self.assertFalse(any(line.endswith("|") or line.startswith("; |") for line in lines))

    def test_the_book_is_written_with_the_squares_the_program_reads_from_the_moves(self):
        games = self.tool.candidates([self.pgn(self.WHITE_WINS, opening="Ruy Lopez: Delayed Exchange") + "\n" +
                                      self.pgn(self.BLACK_WINS, result="0-1", opening="Ruy Lopez: Anderssen",
                                               white="Gamma, Gus", black="Delta, Dee")], min_moves=5, min_rating=2600)
        chosen = self.tool.choose(games, openings=1)
        self.assertEqual([g.winner for g in chosen], ["white", "black"])
        text = self.tool.book_text(chosen, 3, self.tool.engine())
        # white's 3 moves, and black's 3: the moves before them are there to get to them
        self.assertIn('    (white "e2e4 e7e5 g1f3 b8c6 f1b5")', text)
        self.assertIn('    (black "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6")', text)
        self.assertIn("; 1.e4 e5 2.Nf3 Nc6 3.Bb5", text)                         # the annotations are gone: a6!? is a6
        self.assertIn("; Ruy Lopez: Delayed Exchange (C85) -- Alpha v Beta, Test Open. White won.", text)
        self.assertIn("; https://lichess.org/broadcast/test/round-3/AAAA/BBBB", text)
        self.assertIn("2 games, each won by white or by black", text)
        # and the program can make a book of it: the winner's 3 moves in each game, in 6 positions
        env = lisp_builtins.make_global_env(output=lambda s: None)
        for source in ('(load "chess.lsp")', text, "(define book (make-book book-games))"):
            for expression in lisp_core.parse(source):
                lisp_core.seval(expression, env)
        self.assertEqual(lisp_core.seval(next(iter(lisp_core.parse("(hash-table-count book)"))), env), 6)

    def test_a_game_the_program_cannot_read_to_the_end_stops_the_book(self):
        """Even past the moves the book keeps: 9. Ke3 isn't a legal move there."""
        bad = self.BLACK_WINS.replace("9. Nbd2", "9. Ke3 Nbd7 10. Ke5")
        games = [self.tool.Game(self.tool.games_in(self.pgn(bad, result="0-1"))
                                .__next__()[0], self.tool.moves_of(bad), "black")]
        with self.assertRaises(lisp_core.LispError) as caught:
            self.tool.book_text(games, 3, self.tool.engine())
        self.assertIn("not a legal move here", str(caught.exception))

    def test_the_script_runs_on_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "games.pgn")
            with open(path, "w") as f:
                f.write(self.pgn(self.WHITE_WINS, opening="Ruy Lopez: Delayed Exchange") + "\n" +
                        self.pgn(self.BLACK_WINS, result="0-1", opening="Ruy Lopez: Anderssen", white="Gamma, Gus"))
            run = lambda *args: subprocess.run([sys.executable, "-I", os.path.join(HERE, "tools", "make_chess_book.py"),
                                                path, *args], capture_output=True, text=True, cwd=directory)
            done = run("--positions", "3", "--min-moves", "5")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('(white "e2e4 e7e5 g1f3 b8c6 f1b5")', done.stdout)
            self.assertTrue(done.stdout.rstrip().endswith("))"))
            nothing = run("--min-moves", "50")
            self.assertNotEqual(nothing.returncode, 0)
            self.assertIn("no game qualifies", nothing.stderr)


class TestSqlProgram(unittest.TestCase):
    """examples/sql.lsp, the SQL interpreter. Its answers are compared with those of Python's own sqlite3 on
    the same data: a list of queries, hundreds of random conditions (to test the way NULL makes a comparison
    neither true nor false), random GROUP BY and join queries, and changes to the data. The places where it
    does something different on purpose (the names of columns made from expressions, and where NULL sorts)
    are tested by themselves."""

    # the data: a table of 60 rows with a NULL here and there, a table to join it to, a table of text keys
    TEXTS = ["apple", "Apple pie", "banana", "cherry", "it's", "Ab", "ab", "b"]

    @classmethod
    def setUpClass(cls):
        cls.out = []
        cls.env = lisp_builtins.make_global_env(output=cls.out.append)
        cls.run_lisp('(load "sql.lsp")')
        cls.lite = sqlite3.connect(":memory:")
        rng = random.Random(7)

        def maybe(value):
            return None if rng.random() < 0.15 else value
        t_rows = [(i, maybe(rng.choice(["a", "B", "c", "d"])), maybe(rng.randint(0, 9)),
                   maybe(rng.randint(-80, 400) / 4), maybe(rng.choice(cls.TEXTS)), maybe(rng.randint(1, 6)))
                  for i in range(1, 61)]
        u_rows = ([(k, rng.choice(["one", "two", "three"]), rng.randint(1, 40) / 4) for k in range(1, 9)]
                  + [(None, "nokey", 1.5), (3, "again", 2.0)])
        g_rows = [("a", "first", 1), ("B", "second", 2), ("c", "third", None), (None, "none", 4), ("zz", "unused", 5)]
        for name, columns, rows in [("t", "id INTEGER, grp TEXT, n INTEGER, x REAL, s TEXT, k INTEGER", t_rows),
                                    ("w", "id INTEGER, grp TEXT, n INTEGER, x REAL, s TEXT, k INTEGER", t_rows),
                                    ("u", "k INTEGER, label TEXT, w REAL", u_rows),
                                    ("g", "grp TEXT, descr TEXT, rank INTEGER", g_rows)]:
            cls.both("CREATE TABLE %s (%s)" % (name, columns))
            cls.both("INSERT INTO %s VALUES %s" % (name, ", ".join("(" + ", ".join(cls.literal(v) for v in r) + ")" for r in rows)))

    @staticmethod
    def literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return repr(value)

    @classmethod
    def run_lisp(cls, src, env=None):
        result = lisp_core.NIL
        for expr in lisp_core.parse(src):
            result = lisp_core.seval(expr, env or cls.env)
        return result

    @classmethod
    def fresh_env(cls):
        """An interpreter of its own, with its own (empty) database, for a test that changes the whole of it."""
        env = lisp_builtins.make_global_env(output=lambda text: None)
        cls.run_lisp('(load "sql.lsp")', env)
        return env

    @classmethod
    def mine(cls, text, env=None):
        """What (sql text) gives: a sentence, or the column names and the rows of the table, with
        missing values as None."""
        result = lisp_core.apply_proc((env or cls.env)[lisp_core.Symbol("sql")], [lisp_core.LispString(text)])
        if isinstance(result, (str, lisp_core.LispString)):
            return str(result)
        columns = lisp_tables.table_columns(result, "test")
        data = [[None if (v is None or (isinstance(v, float) and v != v)) else (v if isinstance(v, (int, float)) else str(v))
                 for v in vector.items.tolist()] for _, vector in columns]
        return [name for name, _ in columns], [list(row) for row in zip(*data)]

    @classmethod
    def sqlite(cls, text):
        cursor = cls.lite.execute(text)
        if cursor.description is None:
            return cursor.rowcount
        return [d[0] for d in cursor.description], [list(r) for r in cursor.fetchall()]

    @classmethod
    def both(cls, text):
        """Runs a statement that changes data in both; returns the number of rows changed in each."""
        cursor = cls.lite.execute(text)
        return cls.mine(text), cursor.rowcount

    @staticmethod
    def same_value(a, b):
        if a is None or b is None:
            return a is None and b is None
        if isinstance(a, str) or isinstance(b, str):
            return a == b
        return math.isclose(a, b, rel_tol=2e-6, abs_tol=1e-6)         # the interpreter's numbers are 32-bit floats

    @staticmethod
    def sort_key(row):
        return [(v is None, isinstance(v, str), v if v is not None else 0) for v in row]

    def assertSameAsSqlite(self, text, ordered=False):
        """The rows (not the names of the columns) are the same, in the same order if `ordered`."""
        _, mine = self.mine(text)
        _, theirs = self.sqlite(text)
        if not ordered:
            mine, theirs = sorted(mine, key=self.sort_key), sorted(theirs, key=self.sort_key)
        self.assertEqual(len(mine), len(theirs), "number of rows in: %s" % text)
        for a, b in zip(mine, theirs):
            self.assertTrue(len(a) == len(b) and all(self.same_value(x, y) for x, y in zip(a, b)),
                            "%s\n  mine:   %s\n  sqlite: %s" % (text, a, b))

    def assertLispError(self, text, fragment, env=None):
        with self.assertRaises(lisp_core.LispError, msg="statement: %s" % text) as caught:
            self.mine(text, env)
        self.assertIn(fragment, str(caught.exception))

    def shown(self, text):
        """What (show-sql text) prints."""
        del self.out[:]
        self.run_lisp('(show-sql "%s")' % text.replace('"', '\\"'))
        return "".join(self.out)

    # -- the same answers as sqlite ----------------------------------------------------------------

    UNORDERED = [
        "SELECT * FROM t",
        "SELECT id, grp, x FROM t WHERE x > 50",
        "SELECT id FROM t WHERE x <= 0 OR n = 3",
        "SELECT id FROM t WHERE NOT (x > 50)",
        "SELECT id FROM t WHERE NOT (x > 50 AND n < 5)",
        "SELECT id FROM t WHERE NOT (x > 50 OR grp = 'a')",
        "SELECT id FROM t WHERE grp <> 'a'",
        "SELECT id FROM t WHERE grp = 'a' AND n >= 2",
        "SELECT id FROM t WHERE grp < 'c'",
        "SELECT id FROM t WHERE s >= 'b'",
        "SELECT id FROM t WHERE x BETWEEN 10 AND 20",
        "SELECT id FROM t WHERE x NOT BETWEEN 10 AND 20",
        "SELECT id FROM t WHERE n IN (1, 3, 5)",
        "SELECT id FROM t WHERE n NOT IN (1, 3, 5)",
        "SELECT id FROM t WHERE grp IN ('a', 'B')",
        "SELECT id FROM t WHERE s LIKE 'a%'",
        "SELECT id FROM t WHERE s LIKE '%an%'",
        "SELECT id FROM t WHERE s NOT LIKE '%a%'",
        "SELECT id FROM t WHERE s LIKE '_b'",
        "SELECT id FROM t WHERE s LIKE 'it''s'",
        "SELECT id FROM t WHERE s IS NULL",
        "SELECT id FROM t WHERE s IS NOT NULL AND x IS NULL",
        "SELECT id, x + n, x - n, x * 2, n * n, -x FROM t",
        "SELECT id, x / 4, x / 0.5, x / 0 FROM t",
        "SELECT id, n % 3, (n + 1) % 4 FROM t",
        "SELECT id, 2 + 3 * 4, (2 + 3) * 4, 10 - 4 - 3, -2 * -3 FROM t WHERE id < 4",
        "SELECT id, upper(s), lower(s), length(s) FROM t",
        "SELECT id, abs(x), round(x), round(x / 3, 2) FROM t",
        "SELECT id, coalesce(x, 0), coalesce(s, grp, 'none'), coalesce(n, k, -1) FROM t",
        "SELECT 1, 2.5, 'x', NULL, 1 + 2",
        "SELECT DISTINCT grp FROM t",
        "SELECT DISTINCT grp, n FROM t",
        "SELECT DISTINCT n % 2 FROM t",
        "SELECT COUNT(*), COUNT(x), COUNT(grp), SUM(x), AVG(x), MIN(x), MAX(x), SUM(n), MIN(s), MAX(s) FROM t",
        "SELECT COUNT(*), SUM(x), AVG(x), MIN(x), MAX(s), COUNT(n) FROM t WHERE id < 0",
        "SELECT grp, COUNT(*), COUNT(x), SUM(x), AVG(x), MIN(n), MAX(n) FROM t GROUP BY grp",
        "SELECT grp, k, COUNT(*), SUM(n) FROM t GROUP BY grp, k",
        "SELECT n % 3 AS m, COUNT(*), SUM(x) FROM t GROUP BY n % 3",
        "SELECT grp, SUM(x) * 2, MAX(x) - MIN(x), COUNT(*) + 1 FROM t GROUP BY grp",
        "SELECT grp, COUNT(*) FROM t GROUP BY grp HAVING COUNT(*) > 10",
        "SELECT grp, SUM(x) AS total FROM t GROUP BY grp HAVING SUM(x) > 100 AND grp <> 'B'",
        "SELECT grp, COUNT(*) FROM t WHERE x > 0 GROUP BY grp",
        "SELECT k, SUM(x) FROM t WHERE n > 100 GROUP BY k",
        "SELECT t.id, t.x, u.label, u.w FROM t JOIN u ON t.k = u.k",
        "SELECT t.id, u.label FROM t INNER JOIN u ON t.k = u.k WHERE u.w > 3",
        "SELECT t.id, u.label, u.w FROM t LEFT JOIN u ON t.k = u.k",
        "SELECT u.k, u.label, t.id FROM u LEFT JOIN t ON t.k = u.k",
        "SELECT u.label, COUNT(*), SUM(t.x) FROM t JOIN u ON t.k = u.k GROUP BY u.label",
        "SELECT u.label, COUNT(t.id), COUNT(*) FROM u LEFT OUTER JOIN t ON u.k = t.k GROUP BY u.label",
        "SELECT a.id, b.id FROM t a JOIN t b ON a.k = b.k AND a.grp = b.grp WHERE a.id < b.id AND a.id < 10",
        "SELECT a.id, b.id FROM t AS a JOIN t AS b ON a.n = b.k WHERE a.id < 20",
        "SELECT a.id, u.label, v.label FROM t a JOIN u ON a.k = u.k JOIN u v ON a.n = v.k WHERE a.id < 30",
        "SELECT t.id, g.descr, g.rank FROM t JOIN g ON t.grp = g.grp",
        "SELECT t.id, g.descr, g.rank FROM t LEFT JOIN g ON t.grp = g.grp",
        "SELECT g.descr, COUNT(t.id) FROM g LEFT JOIN t ON g.grp = t.grp GROUP BY g.descr",
        "SELECT * FROM t JOIN u ON t.k = u.k WHERE t.id < 8",
        "SELECT u.* FROM t JOIN u ON t.k = u.k WHERE t.id < 8",
        "SELECT t.*, u.w FROM t JOIN u ON t.k = u.k WHERE t.id < 8",
        "SELECT id AS ident, x AS value FROM t WHERE id < 5",
        "SELECT id ident FROM t WHERE id < 5",
        "SELECT x FROM t WHERE id IN (3, 4) OR x > 99",
    ]
    ORDERED = [
        "SELECT id, x FROM t ORDER BY id",
        "SELECT id, x FROM t WHERE x IS NOT NULL ORDER BY x, id",
        "SELECT id, x FROM t WHERE x IS NOT NULL ORDER BY x DESC, id",
        "SELECT id, grp, n FROM t WHERE grp IS NOT NULL AND n IS NOT NULL ORDER BY grp, n DESC, id",
        "SELECT id, grp FROM t WHERE grp IS NOT NULL ORDER BY grp DESC, id DESC",
        "SELECT id, x * -1 AS neg FROM t WHERE x IS NOT NULL ORDER BY neg, id",
        "SELECT id, x FROM t WHERE x IS NOT NULL ORDER BY x * x DESC, id",
        "SELECT id, x FROM t WHERE x IS NOT NULL ORDER BY 2, 1",
        "SELECT id, x FROM t WHERE x IS NOT NULL ORDER BY 2 DESC, 1 DESC LIMIT 7",
        "SELECT id FROM t ORDER BY id LIMIT 5",
        "SELECT id FROM t ORDER BY id LIMIT 5 OFFSET 10",
        "SELECT id FROM t ORDER BY id LIMIT 100 OFFSET 55",
        "SELECT id FROM t ORDER BY id LIMIT 0",
        "SELECT id FROM t ORDER BY id LIMIT 5 OFFSET 200",
        "SELECT grp, COUNT(*) AS n FROM t WHERE grp IS NOT NULL GROUP BY grp ORDER BY n DESC, grp",
        "SELECT grp, SUM(x) FROM t WHERE grp IS NOT NULL GROUP BY grp ORDER BY SUM(x) DESC",
        "SELECT grp, COUNT(*) FROM t WHERE grp IS NOT NULL GROUP BY grp ORDER BY COUNT(*), grp",
        "SELECT grp FROM t WHERE grp IS NOT NULL GROUP BY grp ORDER BY MAX(x) DESC, grp",
        "SELECT DISTINCT grp, n FROM t WHERE grp IS NOT NULL AND n IS NOT NULL ORDER BY n DESC, grp",
        "SELECT u.label, t.id FROM t JOIN u ON t.k = u.k ORDER BY u.label DESC, t.id LIMIT 12",
        "SELECT label, w FROM u WHERE k IS NOT NULL ORDER BY label, w DESC",
        "SELECT id, x FROM t WHERE x IS NOT NULL AND n IS NOT NULL ORDER BY n, x DESC, id",
    ]

    def test_queries_give_the_rows_sqlite_gives(self):
        for text in self.UNORDERED:
            with self.subTest(query=text):
                self.assertSameAsSqlite(text)

    def test_ordered_queries_give_the_rows_in_the_order_sqlite_does(self):
        for text in self.ORDERED:
            with self.subTest(query=text):
                self.assertSameAsSqlite(text, ordered=True)

    # --- random queries ---

    NUMBERS = ["id", "n", "x", "k"]
    WORDS = ["grp", "s"]

    def random_atom(self, rng, prefix):
        number = lambda: rng.choice(["0", "1", "3", "5", "-2", "10.5", "40", "99.25"])          # noqa: E731
        word = lambda: rng.choice(["'a'", "'B'", "'c'", "'apple'", "'Ab'", "'banana'", "'b'", "''"])   # noqa: E731
        column = lambda names: prefix + rng.choice(names)                                      # noqa: E731
        r = rng.random()
        if r < 0.30:
            return "%s %s %s" % (column(self.NUMBERS), rng.choice(["=", "<>", "<", "<=", ">", ">=", "!="]),
                                 rng.choice([number(), column(self.NUMBERS)]))
        if r < 0.45:
            return "%s %s %s" % (column(self.WORDS), rng.choice(["=", "<>", "<", "<=", ">", ">="]),
                                 rng.choice([word(), column(self.WORDS)]))
        if r < 0.55:
            return "%s IS %sNULL" % (column(self.NUMBERS + self.WORDS), rng.choice(["", "NOT "]))
        if r < 0.65:
            return "%s %sIN (%s)" % (column(self.NUMBERS), rng.choice(["", "NOT "]),
                                     ", ".join(number() for _ in range(rng.randint(1, 4))))
        if r < 0.72:
            return "%s %sIN (%s)" % (column(self.WORDS), rng.choice(["", "NOT "]),
                                     ", ".join(word() for _ in range(rng.randint(1, 3))))
        if r < 0.82:
            return "%s %sBETWEEN %s AND %s" % (column(self.NUMBERS), rng.choice(["", "NOT "]), number(), number())
        if r < 0.92:
            return "%s %sLIKE '%s'" % (column(self.WORDS), rng.choice(["", "NOT "]),
                                       rng.choice(["a%", "%a", "%an%", "_b", "B", "%", "a_", "it''s", "%e%"]))
        return "%s + %s %s %s" % (column(self.NUMBERS), column(self.NUMBERS), rng.choice(["<", ">", "=", "<>"]), number())

    def random_condition(self, rng, prefix="", depth=0):
        r = rng.random()
        if depth >= 3 or r < 0.35:
            return self.random_atom(rng, prefix)
        if r < 0.60:
            return "(%s AND %s)" % (self.random_condition(rng, prefix, depth + 1), self.random_condition(rng, prefix, depth + 1))
        if r < 0.85:
            return "(%s OR %s)" % (self.random_condition(rng, prefix, depth + 1), self.random_condition(rng, prefix, depth + 1))
        return "NOT (%s)" % self.random_condition(rng, prefix, depth + 1)

    def test_random_conditions_keep_the_rows_sqlite_keeps(self):
        """Conditions of comparisons with AND, OR, and NOT, over columns with NULLs in them: NOT of a comparison
        with a NULL is not true."""
        rng = random.Random(11)
        for _ in range(400):
            text = "SELECT id FROM t WHERE " + self.random_condition(rng)
            with self.subTest(query=text):
                self.assertSameAsSqlite(text)

    def test_random_groups_give_the_groups_sqlite_gives(self):
        rng = random.Random(23)
        group_choices = ["grp", "k", "n % 3", "s", "id % 4"]
        aggregates = ["COUNT(*)", "COUNT(x)", "COUNT(s)", "SUM(x)", "SUM(n)", "AVG(x)", "AVG(n)", "MIN(x)", "MAX(x)", "MIN(s)",
                      "MAX(s)", "MIN(n)", "SUM(x * 2)", "MAX(x) - MIN(x)", "COUNT(*) + 1", "SUM(x) / COUNT(x)"]
        havings = ["COUNT(*) > 3", "SUM(x) > 100", "MIN(n) < 5", "MAX(x) >= 50 AND COUNT(*) > 1", "AVG(x) < 40 OR COUNT(x) = 0"]
        for _ in range(150):
            groups = rng.sample(group_choices, rng.randint(0, 2))
            chosen = rng.sample(aggregates, rng.randint(1, 4))
            text = "SELECT " + ", ".join(groups + chosen) + " FROM t"
            if rng.random() < 0.5:
                text += " WHERE " + self.random_condition(rng)
            if groups:
                text += " GROUP BY " + ", ".join(groups)
            if rng.random() < 0.4:
                text += " HAVING " + rng.choice(havings)
            with self.subTest(query=text):
                self.assertSameAsSqlite(text)

    def test_random_joins_give_the_rows_sqlite_gives(self):
        rng = random.Random(31)
        for _ in range(100):
            kind = rng.choice(["JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN"])
            if rng.random() < 0.5:
                other, on, columns = "u", rng.choice(["t.k = u.k", "u.k = t.k", "t.k = u.k AND t.n = u.k", "t.n = u.k AND t.k = u.k"]), "t.id, u.label, u.w"
            else:
                other, on, columns = "g", rng.choice(["t.grp = g.grp", "g.grp = t.grp"]), "t.id, g.descr, g.rank"
            text = "SELECT %s FROM t %s %s ON %s" % (columns, kind, other, on)
            if rng.random() < 0.6:
                text += " WHERE " + self.random_condition(rng, prefix="t.")
            with self.subTest(query=text):
                self.assertSameAsSqlite(text)

    def test_changes_to_data_leave_the_table_sqlite_leaves(self):
        """Each change is made in both, and the number of rows it says it changed, and the whole table afterward, are the same."""
        for text in [
                "INSERT INTO w (id, grp) VALUES (1001, 'z'), (1002, NULL)",
                "INSERT INTO w SELECT id + 2000, grp, n, x, s, k FROM w WHERE id < 6",
                "INSERT INTO w (id, x) SELECT id + 3000, x / 2 FROM w WHERE id < 4",
                "UPDATE w SET x = x * 2 WHERE n > 5",
                "UPDATE w SET grp = upper(grp), n = n + 1 WHERE grp = 'a'",
                "UPDATE w SET x = NULL WHERE id % 7 = 0",
                "UPDATE w SET s = 'new', k = id WHERE s IS NULL",
                "UPDATE w SET n = k, k = n WHERE id < 10",
                "UPDATE w SET x = 1 WHERE 1 = 0",
                "DELETE FROM w WHERE x IS NULL AND n < 3",
                "DELETE FROM w WHERE grp = 'c' OR s LIKE 'a%'",
                "DELETE FROM w WHERE id > 5000",
                "DELETE FROM w WHERE NOT (n < 4)",
                "INSERT INTO w VALUES (7000, 'q', 1, 2.5, 'text', 3)",       # into a table that has had its rows deleted
                "DELETE FROM w",
                "INSERT INTO w VALUES (8000, 'only', NULL, NULL, NULL, NULL)",
        ]:
            with self.subTest(statement=text):
                sentence, changed = self.both(text)
                self.assertTrue(sentence.startswith("%d row" % changed), "%s said %r; sqlite changed %d" % (text, sentence, changed))
                self.assertSameAsSqlite("SELECT * FROM w")

    def test_like_treats_the_characters_of_a_regular_expression_as_themselves(self):
        self.both("CREATE TABLE special (s TEXT)")
        self.both("INSERT INTO special VALUES ('a.c'), ('abc'), ('(x)'), ('[ab]'), ('a+b'), ('100%'), ('a_b'), ('^start'), ('end$'), ('back\\slash'), ('A.C'), ('')")
        for pattern in ["a.c", "a%c", "(x)", "[ab]", "a+b", "%.%", "%+%", "100%", "a_b", "a__b", "^%", "%$", "%\\%", "%[%", "_", "", "%"]:
            with self.subTest(pattern=pattern):
                self.assertSameAsSqlite("SELECT s FROM special WHERE s LIKE '%s'" % pattern.replace("'", "''"))
                self.assertSameAsSqlite("SELECT s FROM special WHERE s NOT LIKE '%s'" % pattern.replace("'", "''"))

    def test_rounding_goes_away_from_zero_on_halves(self):
        self.both("CREATE TABLE halves (v REAL)")
        self.both("INSERT INTO halves VALUES (0.5), (1.5), (2.5), (-0.5), (-1.5), (-2.5), (0.25), (-0.75), (3.0), (NULL), (1234.5)")
        self.assertSameAsSqlite("SELECT v, round(v) FROM halves")
        self.assertSameAsSqlite("SELECT v, round(v, 1), round(v, 2) FROM halves")

    # -- the differences, on purpose ------------------------------------------------------------

    def test_the_columns_of_a_result_are_named_for_the_expressions(self):
        self.assertEqual(self.mine("SELECT id, grp AS g, x * 2, upper(s), id + 1 - 2, 2 * (id + 1), -id, id < 3, x IS NULL, "
                                   "NOT (id < 3 OR x > 1), (x + 1) * (x - 1) FROM t")[0],
                         ["id", "g", "x * 2", "upper(s)", "id + 1 - 2", "2 * (id + 1)", "-id", "id < 3", "x is null",
                          "not (id < 3 or x > 1)", "(x + 1) * (x - 1)"])
        self.assertEqual(self.mine("SELECT sum(x), COUNT(*), avg(x * 2), MAX(x) - MIN(x) FROM t")[0],
                         ["sum(x)", "count(*)", "avg(x * 2)", "max(x) - min(x)"])
        self.assertEqual(self.mine("SELECT t.id, T.GRP, X FROM t")[0], ["id", "grp", "x"])
        self.assertEqual(self.mine("SELECT u.* FROM t JOIN u ON t.k = u.k")[0], ["k", "label", "w"])
        self.assertEqual(self.mine("SELECT * FROM t JOIN u ON t.k = u.k")[0], ["id", "grp", "n", "x", "s", "t.k", "u.k", "label", "w"])
        self.assertEqual(self.mine("SELECT t.id, u.k, t.k, u.w AS id FROM t JOIN u ON t.k = u.k")[0], ["id", "k", "k_2", "id_2"])

    def test_a_missing_value_sorts_last_and_in_descending_order_first(self):
        values = [r[0] for r in self.mine("SELECT x FROM t ORDER BY x")[1]]
        missing = values.count(None)
        self.assertGreater(missing, 0)
        self.assertEqual(values[-missing:], [None] * missing)
        self.assertEqual(values[:-missing], sorted(values[:-missing]))
        descending = [r[0] for r in self.mine("SELECT x FROM t ORDER BY x DESC")[1]]
        self.assertEqual(descending[:missing], [None] * missing)
        self.assertEqual(descending[missing:], sorted(descending[missing:], reverse=True))

    def test_division_is_exact_and_a_remainder_has_the_sign_of_the_divisor(self):
        self.assertEqual(self.mine("SELECT 7 / 2, -7 / 2, 7 % 2, 1 / 0")[1], [[3.5, -3.5, 1, None]])
        self.assertEqual(self.mine("SELECT -7 % 3, 7 % -3")[1], [[2, -2]])        # SQLite's are -1 and 1

    # -- details of the language ------------------------------------------------------------------

    def test_names_and_keywords_do_not_depend_on_case(self):
        self.assertEqual(self.mine("select ID, Grp from T where X > 99 order by iD")[1],
                         self.mine("SELECT id, grp FROM t WHERE x > 99 ORDER BY id")[1])
        self.assertEqual(self.mine("SELECT 'CA' = 'ca', 'CA' = 'CA'")[1], [[0, 1]])           # but text is

    def test_text_in_quotes_and_numbers(self):
        self.assertEqual(self.mine("SELECT 'it''s', '', 'a b', 2.50, 1.5 + 1, - 3, 'x;y'")[1], [["it's", "", "a b", 2.5, 2.5, -3, "x;y"]])

    def test_select_without_from_is_one_row(self):
        self.assertEqual(self.mine("SELECT 1 + 2 AS three")[1], [[3]])
        self.assertEqual(self.mine("SELECT COUNT(*), SUM(5)")[1], [[1, 5]])
        self.assertEqual(self.mine("SELECT 1 WHERE 1 = 0")[1], [])

    def test_the_sum_of_nothing_but_nulls_is_null_and_the_count_of_nothing_is_zero(self):
        self.assertEqual(self.mine("SELECT SUM(x), AVG(x), MIN(x), MAX(x), COUNT(x), COUNT(*) FROM t WHERE x IS NULL")[1],
                         [[None, None, None, None, 0, self.sqlite("SELECT COUNT(*) FROM t WHERE x IS NULL")[1][0][0]]])
        self.assertEqual(self.mine("SELECT SUM(x), COUNT(*), COUNT(x), MAX(x) FROM t WHERE id < 0")[1], [[None, 0, 0, None]])
        self.assertEqual(self.mine("SELECT grp, SUM(x) FROM t WHERE id < 0 GROUP BY grp")[1], [])

    def test_a_group_of_missing_keys_is_one_group(self):
        self.assertSameAsSqlite("SELECT k, grp, COUNT(*) FROM t GROUP BY k, grp")

    def test_a_missing_value_in_a_join_column_matches_nothing(self):
        mine = self.mine("SELECT t.id, u.label FROM t JOIN u ON t.k = u.k WHERE t.k IS NULL")[1]
        self.assertEqual(mine, [])
        self.assertEqual(self.mine("SELECT COUNT(*) FROM u LEFT JOIN u v ON u.k = v.k")[1], self.sqlite("SELECT COUNT(*) FROM u LEFT JOIN u v ON u.k = v.k")[1])

    def test_statements_are_all_read_before_any_is_run(self):
        self.mine("CREATE TABLE atomic (x INTEGER)")
        with self.assertRaises(lisp_core.LispError):
            self.mine("INSERT INTO atomic VALUES (1); INSERT INTO atomic VALUES (2) WHERE")
        self.assertEqual(self.mine("SELECT COUNT(*) FROM atomic")[1], [[0]])
        self.assertEqual(self.mine("INSERT INTO atomic VALUES (1); INSERT INTO atomic VALUES (2),(3);"), "2 rows added")    # the last result
        self.assertEqual(self.mine("SELECT SUM(x) FROM atomic;;")[1], [[6]])
        self.assertEqual(self.mine(""), "nothing to do")

    def test_create_and_drop(self):
        self.assertEqual(self.mine("CREATE TABLE made (a integer, b VARCHAR(20), c real, d date)"), "table made created")
        self.assertEqual(self.mine("SELECT COUNT(*) FROM made")[1], [[0]])
        self.assertEqual(self.mine("CREATE TABLE IF NOT EXISTS made (z integer)"), "table made is already there")
        self.assertLispError("CREATE TABLE made (z integer)", "table made already exists")
        self.assertEqual(self.mine("INSERT INTO made VALUES (1, 'x', 2.5, date('2024-03-05'))"), "1 row added")
        self.assertEqual(self.mine("SELECT a, b, c, d FROM made WHERE d > date('2024-01-01')")[1], [[1, "x", 2.5, "2024-03-05"]])
        self.assertEqual(self.mine("DROP TABLE made"), "table made dropped")
        self.assertEqual(self.mine("DROP TABLE IF EXISTS made"), "there is no table made")
        self.assertLispError("DROP TABLE made", "no such table: made")
        self.assertLispError("SELECT * FROM made", "no such table: made")

    def test_inserting_checks_the_kind_of_value_and_fills_in_nulls(self):
        self.mine("CREATE TABLE kinds (n INTEGER, s TEXT, r REAL)")
        self.assertLispError("INSERT INTO kinds VALUES ('x', 'a', 1)", "column n holds numbers, not x")
        self.assertLispError("INSERT INTO kinds VALUES (1, 2, 1)", "column s holds text, not 2")
        self.assertLispError("INSERT INTO kinds VALUES (1, 'a')", "a row has 2 values for 3 columns")
        self.assertLispError("INSERT INTO kinds (n, nope) VALUES (1, 2)", "no such column: nope")
        self.mine("INSERT INTO kinds (s) VALUES ('only text')")
        self.mine("INSERT INTO kinds (r, n) VALUES (2.5, 3)")
        self.mine("INSERT INTO kinds VALUES (NULL, NULL, NULL)")
        self.assertEqual(self.mine("SELECT n, s, r FROM kinds ORDER BY r")[1],
                         [[3, None, 2.5], [None, "only text", None], [None, None, None]])
        self.assertEqual(self.mine("SELECT COUNT(*), COUNT(n), COUNT(s), COUNT(r), SUM(n) FROM kinds")[1], [[3, 1, 1, 1, 3]])

    def test_an_update_sees_the_values_from_before_it(self):
        self.mine("CREATE TABLE swap (a INTEGER, b INTEGER)")
        self.mine("INSERT INTO swap VALUES (1, 2), (3, 4)")
        self.assertEqual(self.mine("UPDATE swap SET a = b, b = a"), "2 rows changed")
        self.assertEqual(self.mine("SELECT a, b FROM swap ORDER BY a")[1], [[2, 1], [4, 3]])

    # -- mistakes ----------------------------------------------------------------------------------

    def test_mistakes_are_errors_that_say_what_is_wrong(self):
        for text, fragment in [
                ("SELECT nope FROM t", "no such column: nope"),
                ("SELECT x.id FROM t", "no such column: x.id"),
                ("SELECT * FROM nope", "no such table: nope"),
                ("SELECT k FROM t JOIN u ON t.k = u.k", "ambiguous column name: k"),
                ("SELECT 1 FROM t a JOIN u a ON a.k = a.k", "a is the name of two tables in the query"),
                ("SELECT u.* FROM t", "no such table: u"),
                ("SELEC 1", "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP or the end of the statement but found SELEC"),
                ("SELECT 1 +", "expected a column, number, or text but found the end of the statement"),
                ("SELECT (1", "expected ) but found the end of the statement"),
                ("SELECT 1 FROM", "expected a table name but found the end of the statement"),
                ("SELECT 1 FROM t WHERE", "expected an expression but found the end of the statement"),
                ("SELECT 1 @ 2", "expected ; or the end of the statement but found @ (at character 9)"),
                ("SELECT 'abc", "a quote that never ends"),
                ("SELECT \"id\" FROM t", "expected *, a table name or an expression but found \" (at character 7)"),
                ("SELECT 1 NOT 2", "expected LIKE, BETWEEN or IN but found 2"),
                ("SELECT 5 BETWEEN 1", "expected AND"),
                ("SELECT x IN (SELECT 1) FROM t", "expected an expression but found SELECT"),
                ("SELECT foo(1)", "unknown function: foo"),
                ("SELECT sum(*) FROM t", "sum needs a column or expression, not *"),
                ("SELECT COUNT(DISTINCT id) FROM t", "count(DISTINCT x) isn't supported"),
                ("SELECT grp, SUM(x) FROM t", "t.grp can't be used here"),
                ("SELECT id FROM t GROUP BY grp", "t.id can't be used here"),
                ("SELECT id FROM t WHERE SUM(x) > 1", "sum() can't be used here"),
                ("SELECT id FROM t ORDER BY 9", "ORDER BY 9 is not a column of the result"),
                ("SELECT DISTINCT grp FROM t ORDER BY x", "t.x can't be used here"),
                ("SELECT id FROM t WHERE s LIKE grp", "LIKE needs a pattern in quotes"),
                ("SELECT id FROM t LIMIT x", "expected a number but found x"),
                ("SELECT t.id FROM t JOIN u ON t.k < u.k", "ON must be equalities"),
                ("SELECT t.id FROM t JOIN u ON t.k = t.n", "must compare a column of one table with a column of the other"),
                ("SELECT t.id FROM t JOIN u", "expected ON"),
                ("SELECT id + s FROM t", "isn't a number"),
                ("SELECT id FROM t WHERE s < 3", "can't compare"),
                ("INSERT INTO t VALUES (1)", "a row has 1 values for 6 columns"),
                ("INSERT INTO t VALUES (id, 1, 1, 1, 'a', 1)", "no such column: id"),
                ("INSERT INTO t", "expected VALUES or SELECT"),
                ("UPDATE t SET nope = 1", "no such column: nope"),
                ("UPDATE t SET", "expected a column name"),
                ("UPDATE nope SET a = 1", "no such table: nope"),
                ("DELETE t", "expected FROM"),
                ("DELETE FROM nope", "no such table: nope"),
                ("CREATE TABLE c (x blob)", "unknown column type: blob"),
                ("CREATE TABLE c (x integer PRIMARY KEY)", "constraints such as PRIMARY KEY"),
                ("CREATE TABLE c ()", "expected a column name"),
                ("CREATE INDEX i", "expected TABLE"),
                ("SELECT 1 FROM t t2 t3", "expected ; or the end of the statement but found t3"),
        ]:
            with self.subTest(statement=text):
                self.assertLispError(text, fragment)

    # -- tables that are the interpreter's ----------------------------------------------------------

    def test_a_table_made_by_the_interpreter_can_be_asked_about_and_the_answer_is_a_table(self):
        env = self.fresh_env()
        self.run_lisp("""
          (define bonds (make-table "issuer" (vector "AAA Corp" "B Inc" "AAA Corp" "C LLC" "B Inc")
                                    "coupon" (vector 5.5 7.25 5.0 nan 7.0)
                                    "maturity" (vector (date 2030 1 15) (date 2028 6 1) (date 2035 3 1) (date 2027 1 1) (date 2029 9 9))
                                    "face" #(100 250 300 50 75)))
          (sql-register-table! "Bonds" bonds)""", env)
        self.assertEqual(self.run_lisp("(sql-table-names)", env).car, "bonds")                    # a name is lower case
        self.assertEqual(self.mine("SELECT issuer, SUM(face) AS face, AVG(coupon) AS coupon FROM BONDS GROUP BY issuer ORDER BY face DESC", env)[1],
                         [["AAA Corp", 400, 5.25], ["B Inc", 325, 7.125], ["C LLC", 50, None]])
        self.assertEqual(self.mine("SELECT issuer FROM bonds WHERE maturity < date('2029-01-01') AND coupon IS NOT NULL", env)[1], [["B Inc"]])
        self.assertEqual(self.mine("SELECT issuer, maturity FROM bonds ORDER BY maturity LIMIT 2", env)[1],
                         [["C LLC", "2027-01-01"], ["B Inc", "2028-06-01"]])
        self.assertEqual(self.mine("UPDATE bonds SET coupon = 6 WHERE coupon IS NULL", env), "1 row changed")
        # the answer is a table the other functions work with, and a table can be given a name
        self.assertEqual(self.run_lisp('(vector-sum (table-column (sql "SELECT face FROM bonds WHERE face > 80") "face"))', env), 650)
        self.assertEqual(self.run_lisp('(table-row-count (sql-table "bonds"))', env), 5)
        self.assertEqual(str(self.run_lisp('(table-column (table-sort (sql "SELECT issuer, face FROM bonds") "face" #t) "issuer")', env)),
                         '#("AAA Corp" "B Inc" "AAA Corp" "B Inc" "C LLC")')
        self.run_lisp('(sql-register-table! "big" (sql "SELECT issuer, face FROM bonds WHERE face >= 250"))', env)
        self.assertEqual(self.mine("SELECT issuer, face FROM big ORDER BY face", env)[1], [["B Inc", 250], ["AAA Corp", 300]])
        self.run_lisp("(sql-reset!)", env)
        self.assertLispError("SELECT * FROM bonds", "no such table: bonds", env)

    def test_a_column_name_with_capitals_can_be_asked_for_in_any_case(self):
        self.run_lisp('(sql-register-table! "pool" (make-table "PoolID" #(1 2) "WAC" #(6.5 7.0)))')
        self.assertEqual(self.mine("SELECT poolid, wac FROM pool WHERE WAC > 6.6")[1], [[2, 7.0]])
        self.assertEqual(self.mine("SELECT * FROM pool")[0], ["PoolID", "WAC"])

    def test_show_sql_prints_the_result_of_each_statement(self):
        printed = self.shown("CREATE TABLE shown (a integer); INSERT INTO shown VALUES (1), (2); SELECT a, a * 2 AS twice FROM shown;")
        self.assertEqual(printed, "table shown created\n2 rows added\n"
                                  "a  twice\n-  -----\n1      2\n2      4\n(2 rows)\n")
        self.assertIn("(1 row)", self.shown("SELECT 1"))
        self.assertIn("(0 rows)", self.shown("SELECT a FROM shown WHERE a > 5"))

    def test_a_longer_result_is_not_cut_short_by_the_default_display(self):
        self.assertEqual(self.shown("SELECT COUNT(*) FROM t").count("\n"), 4)

    def test_the_repl_reads_statements_that_end_with_a_semicolon(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "repl.lsp")
            with open(path, "w") as f:
                f.write('(load "%s")\n(sql-repl)\n(display "after the repl\\n")\n' % os.path.join(EXAMPLES, "sql.lsp"))
            r = run_cli(path, stdin="create table a (x integer);\ninsert into a values (1), (2),\n  (3);\n"
                                    "select sum(x) as total from a;\nselect nope from a;\nquit;\nselect 99;\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        for expected in ["table a created", "3 rows added", "total", "(1 row)", "Error: sql: no such column: nope", "after the repl"]:
            self.assertIn(expected, r.stdout)
        self.assertNotIn("99", r.stdout)                         # after quit;

    def test_the_repl_ends_at_the_end_of_the_input(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "repl.lsp")
            with open(path, "w") as f:
                f.write('(load "%s")\n(sql-repl)\n(display "done\\n")\n' % os.path.join(EXAMPLES, "sql.lsp"))
            r = run_cli(path, stdin="select 1 + 1 as two;\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("two", r.stdout)
        self.assertIn("done", r.stdout)


class TestExampleScripts(unittest.TestCase):
    """Smoke tests: each offline example must run to completion. Every
    script runs ONCE (in setUpClass), in a temporary copy of the examples
    directory's .lsp, .csv, and .txt files, so anything it writes lands
    there, never in the repository. The libraries they load (lib/) are
    found where they are, by load's search.

    The two slowest examples (about 15s and 60s) only run when the
    environment variable LISP_TEST_SLOW is set."""

    FAST_EXAMPLES = [
        "macros_example.lsp",
        "with_struct_example.lsp",
        "trace_example.lsp",
        "metaprogramming_example.lsp",
        "prepayment_demo.lsp",
        "regression_kinds_example.lsp",
        "linear_programming_example.lsp",
        "debugging_example.lsp",
        "stratify_example.lsp",
        "eliza_example.lsp",
        "symbolic_algebra_example.lsp",
        "nlp_parsing_example.lsp",
        "unification_grammar_example.lsp",
        "sql_example.lsp",
        "parser_example.lsp",
        "option_payoffs_example.lsp",
        "deal_example.lsp",
    ]
    SLOW_EXAMPLES = [
        "dolist_vectors_map_example.lsp",
        "oas_monte_carlo_example.lsp",
        "othello_example.lsp",
        "chess_example.lsp",
        "kenken_example.lsp",
    ]

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for name in os.listdir(EXAMPLES):
            if name.endswith((".lsp", ".csv", ".txt")):
                shutil.copy(os.path.join(EXAMPLES, name), cls.tmp)
        names = cls.FAST_EXAMPLES + (cls.SLOW_EXAMPLES if os.environ.get("LISP_TEST_SLOW") else [])
        cls.results = {name: run_cli(os.path.join(cls.tmp, name), cwd=cls.tmp) for name in names}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_each_offline_example_runs_cleanly(self):
        for name, r in self.results.items():
            with self.subTest(example=name):
                self.assertEqual(r.returncode, 0, "%s failed:\n%s" % (name, r.stderr[-1500:]))

    def test_the_stratify_example_makes_its_tables(self):
        out = self.results["stratify_example.lsp"].stdout
        self.assertEqual(out.count("\ntotal "), 8)                 # eight tables, each with a total row
        self.assertIn("under 3.0 ", out)
        self.assertIn("5000  2,103,258,327   100.0%", out)

    def test_the_sql_example_asks_its_questions_of_both_kinds_of_table(self):
        out = self.results["sql_example.lsp"].stdout
        for expected in ["9 rows added", "West           4  1425000.0", "AK         0", "2 rows changed", "1 row deleted",
                         "sql: loans.state can't be used here",
                         "750.0   15666  0.16380147836078132", "(5 rows)", "#(0.1561 0.1594 0.1638 0.1609)", "800.0  0.16094742424242423"]:
            self.assertIn(expected, out)

    def test_the_deal_example_pays_the_bonds_off_in_order_and_faster_when_prepayments_are_faster(self):
        out = self.results["deal_example.lsp"].stdout
        for expected in ["Demo, 100% PSA: the principal adds up in every month: #t", "A1  is paid off in month  57",
                         "A2  is paid off in month 148", "Demo, 400% PSA: the principal adds up in every month: #t",
                         "A1  is paid off in month  27", "237,210", "B1  is paid off in month 360",
                         "The PAC is 162,827,265 of the pool's 250,000,000", "300                101     98,475,185   98,475,185",
                         "600                 33     98,475,185   46,471,481", "50                360     98,475,185  121,287,872",
                         "Two PACs: PAC1 is paid on schedule", "120                                     0                            16,663,232",
                         "200                                     0                                     0",
                         "B, 100,000,000 at 6.25%, is divided into a floater of 69,444,444", "0.00%    0.500%   19.318%      6.250%   #t",
                         "12.00%    9.000%    0.000%      6.250%   #t",
                         "Two pieces of collateral, G1 and G2; the bonds are S1, S2, T1, T2; the principal and the interest add up: #t"]:
            self.assertIn(expected, out)

    def test_the_parser_example_reads_a_calculator_and_a_settings_file(self):
        out = self.results["parser_example.lsp"].stdout
        for expected in ["2 + 3 * 4  =>  (+ 2 (* 3 4))  =>  14", "100 - 30 - 20  =>  (- (- 100 30) 20)  =>  50",
                         "-2 * (7 - 10) / 4  =>  (/ (* (- 2) (- 7 10)) 4)  =>  1.5",
                         "2 +  =>  parse error: expected a number, - or ( but found the end of the input",
                         "2 3  =>  parse error: expected *, /, +, - or the end of the input but found 3 (at character 2)",
                         "data     folder    /Users/ada/pools", "model    folds     5", "One of its settings: #(5)",
                         "parse error: expected a number, a name, or text in quotes but found newline (at character 16)"]:
            self.assertIn(expected, out)

    def test_the_macros_example_produces_its_documented_output(self):
        out = self.results["macros_example.lsp"].stdout
        self.assertIn("after swap!:  p=2 q=1", out)
        self.assertIn("my-while summed 0..199999 -> 19999900000", out)

    def test_the_linear_programming_example_finds_the_best_allocation(self):
        out = self.results["linear_programming_example.lsp"].stdout
        self.assertIn("Yearly income: $6,200,000", out)
        self.assertIn("  cmo_z                   20,000,000    7.2%", out)
        self.assertIn("    6.00     6,320,000   6.32%", out)
        self.assertIn("limited to 4 years: lp-solve: Problem is infeasible.", out)

    def test_the_debugging_example_logs_calls_and_reports_the_error_stop(self):
        out = self.results["debugging_example.lsp"].stdout
        self.assertIn("   called: level-payment (200000 6.0 360)\n   called: monthly-rate (6.0)\n", out)
        self.assertIn("   payment = 1199.1\n", out)
        self.assertIn("The breakpoints are ((level-payment (> balance 500000)))\n"
                      "   called: level-payment (800000 6.0 360)\n", out)
        self.assertNotIn("called: level-payment (200000 6.0 360)\n\n2.", out)
        self.assertIn("   stopped by an error: /: division by zero\n", out)
        self.assertIn("   variables there: ((r . 0.0) (balance . 100000) (annual-percent . 0) (months . 360))\n", out)
        self.assertIn("   result = no-payment\n", out)

    def test_the_trace_example_produces_its_documented_output(self):
        out = self.results["trace_example.lsp"].stdout
        self.assertIn("< (count-down 0) => done  [after 3 tail calls]", out)
        self.assertIn("Lisp call stack (most recent call last):\n  (a)\n  (b)\n  (c)\n", out)
        self.assertIn("caught: car: not a pair: 5", out)

    def test_the_trace_examples_documented_error_report_is_what_really_happens(self):
        """The example's comment shows the report an uncaught (outer 5)
        prints; run it for real (the file plus that one line) and compare."""
        with open(os.path.join(self.tmp, "trace_example.lsp")) as f:
            source = f.read().replace("; (outer 5)", "(outer 5)")
        path = os.path.join(self.tmp, "trace_example_fails.lsp")
        with open(path, "w") as f:
            f.write(source)
        r = run_cli(path, cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr,
                         "Lisp traceback (most recent call last):\n  (outer 5)\n"
                         "  (middle 5)  [+1 tail call]\n  (inner 5)\n"
                         "Error: car: not a pair: 5\n")

    def test_the_eliza_example_answers_from_its_rules(self):
        out = self.results["eliza_example.lsp"].stdout
        self.assertIn("ELIZA: Why do you say your boyfriend made you come here?\n", out)
        self.assertIn("ELIZA: How long have you been depressed much of the time?\n", out)
        self.assertIn("ELIZA: Does it please you to believe I am not very helpful?\n", out)

    def test_eliza_talks_with_whoever_types_until_bye(self):
        """(eliza) reads lines with read-line: here, from standard input."""
        with open(os.path.join(self.tmp, "eliza_example.lsp")) as f:
            source = f.read()
        path = os.path.join(self.tmp, "eliza_interactive.lsp")
        with open(path, "w") as f:
            f.write(source + "\n(random-seed 1)\n(eliza)\n")
        r = run_cli(path, stdin="I need a long vacation\nbye\n", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a long vacation", r.stdout.split("ELIZA: Hello.")[-1])
        self.assertTrue(r.stdout.endswith("ELIZA: Goodbye.\n"))

    def test_the_symbolic_algebra_example_simplifies(self):
        out = self.results["symbolic_algebra_example.lsp"].stdout
        self.assertIn("((x + 1) * (x - 1))\n    = x^2 - 1\n", out)
        self.assertIn("    = 20*x^9 + 240*x^7 + 504*x^5 + 240*x^3 + 20*x\n", out)
        self.assertIn("(d (3 * x ^ 2 + 2 * x + 1) / d x)\n    = 6*x + 2\n", out)
        self.assertIn("(1 + x + y + z) ^ 6 has 84 terms.", out)

    def test_the_nlp_parsing_example_finds_every_reading(self):
        out = self.results["nlp_parsing_example.lsp"].stdout
        self.assertIn("((the man) ((saw (the woman)) (with (the telescope))))\n"
                      "((the man) (saw ((the woman) (with (the telescope)))))\n", out)
        self.assertIn("  42 readings: the man saw the woman in the park with the telescope on the hill by the table", out)
        self.assertIn("(S (NP (D the) (N glorp)) (VP (V blicked) (NP (D a) (N dog))))", out)
        self.assertIn("  two plus three times four: (20 14)\n", out)

    def test_the_unification_grammar_example_parses_and_generates(self):
        out = self.results["unification_grammar_example.lsp"].stdout
        self.assertIn("  ways to append two lists to make (1 2 3): ((() (1 2 3)) ((1) (2 3)) ((1 2) (3)) ((1 2 3) ()))", out)
        self.assertIn("  The cats chase a dog.\n      ((the ?x (cat ?x) (some ?y (dog ?y) (chase ?x ?y))))\n", out)
        self.assertIn("  The dogs sleeps.  ()\n", out)
        self.assertIn("  Every dog barks.\n      (every dog barks)\n      (all dogs bark)\n", out)

    def test_the_othello_example_plays_its_games(self):
        if "othello_example.lsp" not in self.results:
            self.skipTest("othello_example.lsp is slow: set LISP_TEST_SLOW to run it")
        out = self.results["othello_example.lsp"].stdout
        self.assertIn("From the opening, looking 3 moves ahead: minimax 1, alpha-beta 1\n", out)
        self.assertIn(" moves; ", out)

    def test_the_chess_example_checks_its_rules_and_finds_the_tactics(self):
        if "chess_example.lsp" not in self.results:
            self.skipTest("chess_example.lsp is slow: set LISP_TEST_SLOW to run it")
        out = self.results["chess_example.lsp"].stdout
        self.assertIn("  (20 400 8902)\n", out)
        self.assertIn("  (48 2039)\n", out)
        self.assertIn("White plays Qxf7#", out)
        self.assertIn("White plays Nxc7+", out)
        self.assertIn("White plays Rd8+   (it sees a checkmate;", out)
        first_moves = out.split("from the book:\n  ")[1].split("\n")[0].split()
        self.assertEqual(len(first_moves), 10)
        self.assertTrue(set(first_moves) <= {"e4", "d4", "Nf3"})
        self.assertIn("  without: e4 e4 e4 e4 e4 e4\n", out)
        with_variety = out.split("  with:    ")[1].split("\n")[0].split()
        self.assertEqual(set(with_variety), {"e4", "d4"})

    def test_the_kenken_example_solves_its_9_by_9_puzzle(self):
        if "kenken_example.lsp" not in self.results:
            self.skipTest("kenken_example.lsp is slow: set LISP_TEST_SLOW to run it")
        out = self.results["kenken_example.lsp"].stdout
        self.assertEqual(out.count("Its one solution"), 3)
        self.assertIn("|  1     4  |  5     3     7  |  2     9  |  6  |  8  |", out)

    def test_the_option_payoffs_example_ranks_the_kinds_and_saves_its_charts(self):
        out = self.results["option_payoffs_example.lsp"].stdout
        self.assertIn("XYZ is at 104.00. The best position of each kind expiring 2026-11-20, if it is at 108.00 then;", out)
        self.assertIn(" 17 positions.\n", out)
        self.assertIn("Owning the stock (long-stock) is number ", out)
        # the made-up chain has strikes every 5, so that the best butterfly and condor are the ones with wings of 5
        self.assertIn("buy 1 105.00 call, sell 2 110.00 calls, buy 1 115.00 call", out)
        self.assertIn("buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call", out)
        for chart in ("option_payoff_condor.png", "option_payoffs_compared.png", "option_payoffs_hedged.png",
                      "option_payoffs_verticals.png", "option_payoffs_butterflies.png", "option_payoffs_shares.png"):
            self.assertTrue(is_a_png(os.path.join(self.tmp, chart)), chart)
        self.assertIn("[chart] Iron condor on XYZ, expiring 2026-11-20\n", out)
        self.assertIn("[chart] The vertical spreads and the single options\n  panel 1: bull-call: ", out)
        self.assertIn("  panel 4: collar: buy 100 shares, ", out)                         # (the last of "with shares")

    def test_the_with_struct_example_produces_its_documented_output(self):
        out = self.results["with_struct_example.lsp"].stdout
        self.assertIn("30yr 6% $300k payment: 179865 cents/month", out)
        self.assertIn("300000 tail calls -> 300000", out)


if __name__ == "__main__":
    unittest.main()
