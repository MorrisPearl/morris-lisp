"""lisp_runner.py: running Lisp from a Python program -- a new environment, a file, some text, or the console."""

from support import *

import lisp_runner

NO_INIT_FILE = {"LISP_INIT_FILE": os.path.join(tempfile.gettempdir(), "no-such-init.lsp")}


class TestRunningLispFromPython(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.dict(os.environ, NO_INIT_FILE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lisp_builtins.set_command_line_arguments, [])
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def lisp_file(self, text, name="program.lsp"):
        path = os.path.join(self.folder, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_run_file_returns_the_value_of_the_last_form(self):
        path = self.lisp_file("(define (square x) (* x x))\n(square 12)\n")
        self.assertEqual(lisp_runner.run_file(path), 144)

    def test_a_file_gets_the_arguments_as_its_command_line_words(self):
        path = self.lisp_file("(command-line-arguments)")
        value = lisp_runner.run_file(path, arguments=["KO", "6"])
        self.assertEqual(lisp_core.pairs_to_list(value), ["KO", "6"])

    def test_what_the_program_displays_goes_where_the_environment_says(self):
        texts = []
        env = lisp_runner.new_environment(output=texts.append)
        lisp_runner.run_file(self.lisp_file('(display "hello ") (print (+ 1 2))'), env)
        self.assertEqual("".join(texts), "hello 3\n")

    def test_one_environment_for_several_things_in_turn(self):
        env = lisp_runner.new_environment(output=lambda text: None)
        lisp_runner.run_file(self.lisp_file("(define rate 0.05)"), env)
        self.assertEqual(lisp_runner.run_text("(* rate 100)", env), 5.0)
        self.assertEqual(lisp_core.to_string(lisp_runner.run_text("(list 1 2) (vector 3 4)", env)), "#(3 4)")

    def test_the_environment_has_the_libraries_functions(self):
        env = lisp_runner.new_environment(output=lambda text: None)
        self.assertTrue(lisp_runner.run_text("(procedure? industry-returns)", env))

    def test_an_error_is_a_lisp_error_with_the_report_the_console_shows(self):
        path = self.lisp_file("(define (inner x) (car x))\n(define (outer x) (list (inner x)))\n(outer 5)\n")
        with self.assertRaises(lisp_core.LispError) as raised:
            lisp_runner.run_file(path)
        self.assertEqual(lisp_core.format_error_report(raised.exception),
                         "Lisp traceback (most recent call last):\n  (outer 5)\n  (inner 5)\nError: car: not a pair: 5\n")

    def test_another_python_program_can_import_it_and_run_a_file(self):
        program = os.path.join(self.folder, "uses_lisp.py")
        with open(program, "w") as f:
            f.write("import sys\n"
                    "sys.path.insert(0, %r)\n"
                    "import lisp_runner\n"
                    "value = lisp_runner.run_file(sys.argv[1], arguments=sys.argv[2:])\n"
                    "print('the value:', value)\n" % HERE)
        path = self.lisp_file('(display (string-append "words: " (string-join (command-line-arguments) " ")))\n'
                              "(newline)\n(* 6 7)\n")
        result = subprocess.run([sys.executable, program, path, "a", "b"], capture_output=True, text=True,
                                cwd=self.folder, env=dict(os.environ, **NO_INIT_FILE), timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "words: a b\nthe value: 42\n")


class TestTheConsole(unittest.TestCase):
    """lisp_runner.repl, with what is typed coming from standard input."""

    def console(self, typed):
        env = dict(os.environ, **NO_INIT_FILE)
        result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import lisp_runner; lisp_runner.repl()" % HERE],
                                input=typed, capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_a_form_is_run_when_it_is_finished(self):
        out = self.console('(+ 1\n 2)\n(display "(")\n(list "a)"\n "b")\n(exit)\n')
        self.assertIn("lisp>   ... 3\n", out)                  # the ( inside a string isn't counted, nor the ) in "a)"
        self.assertIn('lisp> (()\n', out)
        self.assertIn('lisp>   ... ("a)" "b")\n', out)

    def test_a_syntax_error_is_said_and_the_console_carries_on(self):
        out = self.console("(+ 1 2))\n(+ 3 4)\n(exit)\n")
        self.assertIn("Error: unexpected ')' on line 1 -- there are more )s than (s before it\n", out)
        self.assertIn("lisp> 7\n", out)


if __name__ == "__main__":
    unittest.main()
