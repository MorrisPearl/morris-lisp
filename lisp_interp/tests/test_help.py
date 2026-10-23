"""Help from inside the interpreter (lisp_help.py): (help name), (documentation name) and (apropos text), for functions, macros, special
forms, variables, structs and generic functions, and for library functions that are not loaded yet; and the Jupyter kernel's Tab
(completion) and Shift-Tab (the help of the name at the cursor), called directly and through a real kernel."""

import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

import lisp_help


class TestDocumentation(LispTestCase):

    def documentation(self, name):
        return lisp_help.documentation(self.env, name)

    def test_a_function_s_docstring_is_under_how_it_is_called(self):
        self.run_lisp('(define (square x &key (times 1)) "The square of x, times times." (* x x times))')
        self.assertEqual(self.documentation("square"), "(square x &key (times 1))\n  The square of x, times times.")

    def test_a_body_that_is_only_a_string_has_no_docstring(self):
        self.run_lisp('(define (greeting) "hello")')
        self.assertEqual(self.documentation("greeting"), "(greeting)")

    def test_a_builtin_s_docstring_says_how_it_is_called(self):
        self.assertTrue(self.documentation("sort").startswith("(sort seq [key]) -- a new list or vector"))

    def test_a_special_form_or_macro_without_a_docstring_has_its_manual_section(self):
        text = self.documentation("dolist")
        self.assertTrue(text.startswith("(dolist (var list-expr [result-expr]) body...)\n  Common-Lisp-style iteration"))
        self.assertTrue(text.endswith("(From lisp_interpreter_reference.md.)"))
        self.assertTrue(self.documentation("if").startswith("(if test conseq [alt])"))

    def test_a_long_manual_section_is_cut_short(self):
        text = lisp_help.manual_section("define")
        self.assertLessEqual(len(text.splitlines()), lisp_help.MOST_MANUAL_LINES + 2)

    def test_a_variable_shows_its_value(self):
        self.run_lisp("(define rate 0.05)")
        self.assertEqual(self.documentation("rate"), "rate is a variable. Its value is 0.05")
        self.run_lisp("(define long (iota 500))")
        self.assertTrue(self.documentation("long").endswith(" ..."))

    def test_a_name_that_is_not_defined_has_none(self):
        self.assertIsNone(self.documentation("no-such-name"))
        self.assertShows("(documentation 'no-such-name)", "#f")

    def test_the_functions_a_defstruct_makes_say_what_they_do(self):
        self.run_lisp("(defstruct point x y)")
        self.assertEqual(self.documentation("point-x"), "(point-x point) -- the x slot of a point (made by defstruct).")
        self.assertEqual(self.documentation("point-y-set!"), "(point-y-set! point value) -- sets the y slot of a point (made by defstruct).")
        self.assertEqual(self.documentation("make-point"), "(make-point &key x y) -- a new point, with each slot given by its keyword (made by defstruct).")
        self.assertTrue(self.documentation("point?").startswith("(point? x) -- whether x is a point"))
        self.assertTrue(self.documentation("copy-point").startswith("(copy-point point) -- a new point"))
        self.assertShows("(make-point :x 1 :y 2)", "#S(point :x 1 :y 2)")             # (the docstring changes nothing it does)

    def test_a_generic_function_has_what_defgeneric_was_given(self):
        self.run_lisp('(defgeneric area (shape) "The area of a shape.")')
        self.assertEqual(self.documentation("area"), "(area shape)\n  The area of a shape.")
        self.run_lisp("(defgeneric perimeter (shape))")
        self.assertIn("its method is chosen by the type of its first argument", self.documentation("perimeter"))

    def test_documentation_gives_the_text_and_takes_a_symbol_a_string_or_the_function(self):
        self.run_lisp('(define (square x) "The square of x." (* x x))')
        for argument in ("'square", '"square"', "square"):
            with self.subTest(argument=argument):
                self.assertEqual(self.run_lisp("(documentation %s)" % argument), "(square x)\n  The square of x.")
        self.assertTrue(str(self.run_lisp("(documentation car)")).startswith("(car"))
        self.assertLispError("(documentation 5)", "documentation: expected a name")


class TestLibraryFunctionsNotLoadedYet(LispTestCase):
    """The documentation of a name that a lazy-load stands in for is read from the library's file, which is not loaded."""

    def setUp(self):
        super().setUp()
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "shapes.lsp")
        with open(self.path, "w") as f:
            f.write('''(set! loads (+ loads 1))
(defstruct circle radius (color "red"))
; a round shape: its radius, and its color
; (the comment under a defstruct says what it is)

(define (circle-area c &key (pi 3.14159))
  "The area of the circle: pi times the square of its radius."
  (* pi (circle-radius c) (circle-radius c)))

(define (no-docstring c) (circle-radius c))
''')
        self.run_lisp('(define loads 0) (lazy-load "%s" circle-area no-docstring make-circle circle-color unknown-one)' % self.path)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)
        super().tearDown()

    def test_a_function_s_docstring_comes_from_its_definition_without_loading_the_file(self):
        self.assertEqual(lisp_help.documentation(self.env, "circle-area"),
                         "(circle-area c &key (pi 3.14159))\n  The area of the circle: pi times the square of its radius.\n"
                         "It is in %s, which is loaded the first time it is called." % self.path)
        self.assertEqual(lisp_help.documentation(self.env, "no-docstring"),
                         "(no-docstring c)\nIt is in %s, which is loaded the first time it is called." % self.path)
        self.assertShows("loads", "0")

    def test_a_function_a_defstruct_makes_shows_the_defstruct_and_its_comment(self):
        text = lisp_help.documentation(self.env, "circle-color")
        self.assertEqual(text.splitlines()[:4], [
            "(circle-color circle) -- the color slot of a circle (made by defstruct).",
            '  (defstruct circle radius (color "red"))',
            "  ; a round shape: its radius, and its color",
            "  ; (the comment under a defstruct says what it is)"])
        self.assertTrue(lisp_help.documentation(self.env, "make-circle").startswith("(make-circle &key radius color)"))
        self.assertShows("loads", "0")

    def test_once_loaded_it_is_the_function_s_own_docstring(self):
        self.run_lisp("(circle-area (make-circle :radius 1.0))")
        self.assertShows("loads", "1")
        self.assertEqual(lisp_help.documentation(self.env, "circle-area"),
                         "(circle-area c &key (pi 3.14159))\n  The area of the circle: pi times the square of its radius.")

    def test_a_name_the_file_does_not_define_or_a_file_not_found_is_said(self):
        self.assertEqual(lisp_help.documentation(self.env, "unknown-one"), "unknown-one is defined in %s." % self.path)
        self.run_lisp('(lazy-load "no_such_library.lsp" lost-function)')
        self.assertEqual(lisp_help.documentation(self.env, "lost-function"), "lost-function is in no_such_library.lsp, which is not found.")

    def test_the_libraries_that_come_with_the_interpreter(self):
        self.run_lisp('(load "autoloads.lsp")')
        text = lisp_help.documentation(self.env, "deal-hedge")
        self.assertTrue(text.startswith("(deal-hedge deal name)\n  The hedge of the tranche called name"))
        self.assertTrue(text.endswith("It is in deal_hedge.lsp, which is loaded the first time it is called."))
        self.assertTrue(lisp_help.documentation(self.env, "hedge-instrument-price").startswith(
            "(hedge-instrument-price hedge-instrument) -- the price slot of a hedge-instrument"))


class TestHelpAndApropos(LispTestCase):

    def test_help_shows_the_documentation_and_takes_the_name_quoted_or_not(self):
        self.run_lisp('(define (square x) "The square of x." (* x x))')
        for form in ("(help square)", "(help 'square)"):
            self.out.clear()
            self.assertIs(self.run_lisp(form), lisp_core.NIL)
            self.assertEqual(self.printed(), "(square x)\n  The square of x.\n")
        self.out.clear()
        self.run_lisp("(help if)")                                      # a special form, which is not a variable
        self.assertTrue(self.printed().startswith("(if test conseq [alt])"))

    def test_help_of_a_name_that_is_not_defined_says_how_to_find_one(self):
        self.run_lisp("(help squre)")
        self.assertEqual(self.printed(), 'squre is not defined. (apropos "squre") lists the names that have "squre" in them.\n')

    def test_apropos_lists_the_names_that_have_the_text_in_them_with_how_each_is_called(self):
        self.run_lisp('(define (vector-shuffle-twice v) "Shuffles v twice." v) (define (%vector-hidden v) v) (define (vector--inside v) v)')
        self.run_lisp('(apropos "VECTOR-SHUF")')
        lines = self.printed().splitlines()
        names = [line.split()[0] for line in lines]
        self.assertEqual(names, sorted(names))
        self.assertIn("vector-shuffle-twice", names)
        self.assertNotIn("%vector-hidden", names)                         # (the names used inside are left out)
        self.assertNotIn("vector--inside", names)
        self.assertIn("vector-shuffle-twice  (vector-shuffle-twice v)", lines)

    def test_apropos_finds_library_functions_that_are_not_loaded(self):
        self.run_lisp('(load "autoloads.lsp")')
        self.run_lisp("(apropos 'deal-hedge)")
        self.assertIn("deal-hedge        (deal-hedge deal name)", self.printed().splitlines())

    def test_apropos_says_when_nothing_has_the_text(self):
        self.run_lisp('(apropos "zzqq")')
        self.assertEqual(self.printed(), 'No name has "zzqq" in it.\n')


class TestTheKernelsTabAndShiftTab(LispTestCase):
    """do_complete and do_inspect of lisp_kernel.LispKernel, called directly, on the notebook's environment."""

    def setUp(self):
        super().setUp()
        try:
            import lisp_kernel
        except ImportError:
            self.skipTest("ipykernel is not installed")
        import lisp_jupyter
        self.kernel = lisp_kernel.LispKernel.__new__(lisp_kernel.LispKernel)
        self.notebook_env = lisp_jupyter.get_env()

    def test_tab_gives_the_names_that_begin_with_what_is_before_the_cursor(self):
        code = "(vector-cl"
        reply = self.kernel.do_complete(code, len(code))
        self.assertIn("vector-clip", reply["matches"])
        self.assertTrue(all(name.startswith("vector-cl") for name in reply["matches"]))
        self.assertEqual((reply["cursor_start"], reply["cursor_end"]), (1, len(code)))

    def test_tab_in_the_middle_of_a_line_and_after_nothing(self):
        code = "(list (string-up x) 2)"
        reply = self.kernel.do_complete(code, code.index(" x"))
        self.assertEqual(reply["matches"], ["string-upcase"])
        self.assertEqual(reply["cursor_start"], code.index("string-up"))
        self.assertEqual(self.kernel.do_complete("(list ", 6)["matches"], [])

    def test_shift_tab_shows_the_help_of_the_name_at_the_cursor(self):
        code = "(vector-clip v 0 1)"
        for position in (1, 5, len("(vector-clip")):
            with self.subTest(position=position):
                reply = self.kernel.do_inspect(code, position)
                self.assertTrue(reply["found"])
                self.assertTrue(reply["data"]["text/plain"].startswith("(vector-clip v low high)"))
        self.assertFalse(self.kernel.do_inspect("(no-such-name 1)", 3)["found"])
        self.assertFalse(self.kernel.do_inspect("(  )", 2)["found"])


class TestTabAndShiftTabInARealKernel(unittest.TestCase):
    """The complete_request and inspect_request of a real kernel, as JupyterLab sends them."""

    @classmethod
    def setUpClass(cls):
        from test_debugging import start_test_kernel
        cls.tmp = tempfile.mkdtemp()
        cls.frontend = start_test_kernel(cls.tmp, "lisp-help-test")

    @classmethod
    def tearDownClass(cls):
        cls.frontend.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_complete_and_inspect_requests(self):
        kc = self.frontend.kc
        self.frontend.run('(define (my-own-function x) "What my own function does." x)')
        completed = kc.complete("(my-own-f", 9, reply=True, timeout=20)["content"]
        self.assertEqual(completed["matches"], ["my-own-function"])
        inspected = kc.inspect("(my-own-function 1)", 3, reply=True, timeout=20)["content"]
        self.assertTrue(inspected["found"])
        self.assertEqual(inspected["data"]["text/plain"], "(my-own-function x)\n  What my own function does.")


if __name__ == "__main__":
    unittest.main()
