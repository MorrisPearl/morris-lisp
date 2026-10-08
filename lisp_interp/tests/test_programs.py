"""Whole programs: the command line, the GUI's error report, the KenKen solver, the chess
program, and the example scripts.
support.py says how to run them."""

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
        "linear_programming_example.lsp",
        "debugging_example.lsp",
        "stratify_example.lsp",
        "eliza_example.lsp",
        "symbolic_algebra_example.lsp",
        "nlp_parsing_example.lsp",
        "unification_grammar_example.lsp",
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

    def test_the_kenken_example_solves_its_9_by_9_puzzle(self):
        if "kenken_example.lsp" not in self.results:
            self.skipTest("kenken_example.lsp is slow: set LISP_TEST_SLOW to run it")
        out = self.results["kenken_example.lsp"].stdout
        self.assertEqual(out.count("Its one solution"), 3)
        self.assertIn("|  1     4  |  5     3     7  |  2     9  |  6  |  8  |", out)

    def test_the_with_struct_example_produces_its_documented_output(self):
        out = self.results["with_struct_example.lsp"].stdout
        self.assertIn("30yr 6% $300k payment: 179865 cents/month", out)
        self.assertIn("300000 tail calls -> 300000", out)


if __name__ == "__main__":
    unittest.main()
