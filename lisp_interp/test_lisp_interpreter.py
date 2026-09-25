#!/usr/bin/env python3
"""Test suite for lisp_interpreter.py and the .lsp libraries next to it.

Run it from this directory (or anywhere) with either of:

    python3 -m unittest test_lisp_interpreter          # add -v for names
    python3 -m pytest test_lisp_interpreter.py         # if pytest is installed

It uses only the standard library (plus numpy, which the interpreter itself
needs), and it never touches the network, the GUI, your credentials, or any
file outside a temporary directory -- so it is safe to run anywhere, anytime.
The two slowest example scripts (about 15s and 60s) are skipped unless you
set LISP_TEST_SLOW=1. Not covered on purpose: anything that needs a network
connection or an account (fred-series, tastytrade-*, sofr-calibration-data).
The GUI and the Jupyter kernel get only a check of their error reports.
"Running the tests" in lisp_interpreter_reference.md lists more ways to run
it, e.g. one test class at a time.

Layout: the first half tests the LANGUAGE (reader, special forms, tail
calls, macros, structs, errors); the second half tests the BUILT-IN
FUNCTION families (numbers, lists, strings, hash tables, vectors, dates,
regression, SQLite), then the .lsp libraries, the command line, the example
scripts, and finally every `expr ; => value` example in
lisp_interpreter_reference.md, so the documentation can't silently drift out
of date with the interpreter.

Most tests use the helpers on LispTestCase: run a snippet of Lisp source in
a fresh global environment, and compare either the raw result, its printed
form (`show`, i.e. what the REPL would print), or the text the program
displayed (`printed`).
"""

import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lisp_builtins  # noqa: E402  (these need the sys.path line above)
import lisp_core     # noqa: E402

INTERPRETER = os.path.join(HERE, "lisp_interpreter.py")
REFERENCE_DOC = os.path.join(HERE, "lisp_interpreter_reference.md")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class LispTestCase(unittest.TestCase):
    """Every test gets a fresh global environment (no init.lsp loaded) whose
    display/print output is captured rather than written to the console."""

    def setUp(self):
        lisp_core.set_verbose_level(0)         # verbosity is process-wide: never leak it between tests
        self.addCleanup(lisp_core.set_verbose_level, 0)
        self.out = []
        self.env = lisp_builtins.make_global_env(output=self.out.append)

    # -- running code ------------------------------------------------------

    def run_lisp(self, src, env=None):
        """Evaluate every top-level form in `src`; return the last value."""
        env = self.env if env is None else env
        result = lisp_core.NIL
        for expr in lisp_core.parse(src):
            result = lisp_core.seval(expr, env)
        return result

    def show(self, src):
        """The last value's printed (REPL) form, e.g. '(1 2 3)'."""
        return lisp_core.to_string(self.run_lisp(src))

    def printed(self):
        """Everything display/newline/print have written so far."""
        return "".join(self.out)

    # -- assertions --------------------------------------------------------

    def assertShows(self, src, expected):
        self.assertEqual(self.show(src), expected, msg="source: %s" % src)

    def assertLispError(self, src, fragment=""):
        """`src` must raise the interpreter's own LispError whose message
        contains `fragment`."""
        with self.assertRaises(lisp_core.LispError, msg="source: %s" % src) as cm:
            self.run_lisp(src)
        self.assertIn(fragment, str(cm.exception))

    def assertRaisesFromLisp(self, exc_type, src):
        """`src` must raise `exc_type` (for the few builtins documented as
        raising a raw Python exception rather than a LispError)."""
        with self.assertRaises(exc_type, msg="source: %s" % src):
            self.run_lisp(src)


# ---------------------------------------------------------------------------
# 1. The reader
# ---------------------------------------------------------------------------

class TestReader(LispTestCase):

    def test_numbers(self):
        self.assertEqual(self.run_lisp("42"), 42)
        self.assertEqual(self.run_lisp("-7"), -7)
        self.assertEqual(self.run_lisp("3.14"), 3.14)
        self.assertIsInstance(self.run_lisp("3"), int)
        self.assertIsInstance(self.run_lisp("3.0"), float)

    def test_booleans(self):
        self.assertIs(self.run_lisp("#t"), True)
        self.assertIs(self.run_lisp("#f"), False)

    def test_strings_and_escapes(self):
        self.assertEqual(self.run_lisp(r'"hello"'), "hello")
        self.assertEqual(self.run_lisp(r'"a\nb"'), "a\nb")
        self.assertEqual(self.run_lisp(r'"a\tb"'), "a\tb")
        self.assertEqual(self.run_lisp(r'"a\rb"'), "a\rb")
        self.assertEqual(self.run_lisp(r'"say \"hi\""'), 'say "hi"')
        self.assertEqual(self.run_lisp(r'"back\\slash"'), "back\\slash")
        self.assertTrue(lisp_core.is_true(self.run_lisp('(string? "x")')))

    def test_quote_shorthand(self):
        self.assertShows("'x", "x")
        self.assertShows("'(1 2 3)", "(1 2 3)")
        self.assertEqual(lisp_core.to_string(list(lisp_core.parse("'x"))[0]), "(quote x)")

    def test_quasiquote_shorthand_reads_as_expected_forms(self):
        self.assertEqual(lisp_core.to_string(list(lisp_core.parse("`(a ,b ,@c)"))[0]),
                         "(quasiquote (a (unquote b) (unquote-splicing c)))")

    def test_dotted_pairs(self):
        self.assertShows("'(1 . 2)", "(1 . 2)")
        self.assertShows("'(1 2 . 3)", "(1 2 . 3)")

    def test_empty_list_and_nesting(self):
        self.assertShows("'()", "()")
        self.assertShows("'(1 (2 (3)) ())", "(1 (2 (3)) ())")

    def test_vector_literal_is_not_evaluated(self):
        self.assertShows("#(1 2 3)", "#(1 2 3)")
        self.assertShows("(vector (+ 1 1) 3)", "#(2 3)")

    def test_keywords_are_self_evaluating_symbols(self):
        v = self.run_lisp(":name")
        self.assertIsInstance(v, lisp_core.Keyword)
        self.assertShows("(keyword? :name)", "#t")
        self.assertShows("(keyword? 'name)", "#f")
        self.assertShows("(symbol? :name)", "#t")

    def test_comments_are_ignored(self):
        self.assertEqual(self.run_lisp("; nothing here\n(+ 1 ; inline\n 2)"), 3)

    def test_multiple_top_level_forms(self):
        self.assertEqual(len(list(lisp_core.parse("1 2 (+ 3 4)"))), 3)

    def test_empty_source(self):
        self.assertEqual(list(lisp_core.parse("")), [])
        self.assertEqual(list(lisp_core.parse("; only a comment")), [])

    def test_unbalanced_parens_raise(self):
        with self.assertRaises(lisp_core.LispError):
            list(lisp_core.parse("(1 2"))
        with self.assertRaises(lisp_core.LispError):
            list(lisp_core.parse(")"))


# ---------------------------------------------------------------------------
# 2. Special forms
# ---------------------------------------------------------------------------

class TestSpecialForms(LispTestCase):

    def test_quote(self):
        self.assertShows("(quote (a b))", "(a b)")

    def test_nan_inf_and_infinity_are_read_as_numbers(self):
        self.assertShows("(list nan inf -inf NaN Infinity 1_000)", "(nan inf -inf nan inf 1000)")

    def test_a_number_or_keyword_cannot_be_a_name(self):
        for src in ["(define nan 5)", "(define (f inf) 1)", "(define (g . infinity) 1)",
                    "(define (h &key (nan 1)) 1)", "((lambda (inf) inf) 7)", "(let ((nan 1)) nan)",
                    "(dolist (inf (list 1)) inf)", "(set! -inf 3)"]:
            with self.subTest(src=src):
                self.assertLispError(src, "(nan, inf, and infinity are read as numbers)")
        self.assertLispError("(define 5 3)", "5 can't be used as a name")
        self.assertLispError("(define (5) 3)", "5 can't be used as a name")
        self.assertLispError("(define :k 1)", ":k can't be used as a name")

    def test_quasiquote_unquote_and_splicing(self):
        self.assertShows("`(1 ,(+ 1 1) ,@(list 3 4) 5)", "(1 2 3 4 5)")
        self.assertShows("(let ((rest (list 2 3))) `(1 ,@rest 4))", "(1 2 3 4)")

    def test_if(self):
        self.assertShows("(if #t 1 2)", "1")
        self.assertShows("(if #f 1 2)", "2")
        self.assertShows("(if #f 1)", "()")          # no alternative -> '()

    def test_only_false_is_false(self):
        # 0 and '() and "" are all TRUE in this Lisp, like Scheme.
        self.assertShows("(if 0 'y 'n)", "y")
        self.assertShows("(if '() 'y 'n)", "y")
        self.assertShows('(if "" \'y \'n)', "y")
        self.assertShows("(not 0)", "#f")

    def test_define_variable_and_function(self):
        self.assertShows("(define x 5) x", "5")
        self.assertShows("(define (add a b) (+ a b)) (add 2 3)", "5")

    def test_define_returns_the_name(self):
        self.assertShows("(define x 1)", "x")
        self.assertShows("(define (f) 1)", "f")

    def test_set_bang(self):
        self.assertShows("(define x 1) (set! x 2) x", "2")

    def test_set_bang_updates_the_binding_in_scope(self):
        self.assertShows("(define x 1) (define (f) (set! x 9)) (f) x", "9")

    def test_set_bang_on_unbound_name_is_an_error(self):
        self.assertLispError("(set! nope 1)", "unbound symbol")

    def test_lambda_and_closure(self):
        self.assertShows("((lambda (x y) (* x y)) 3 4)", "12")
        self.assertShows("(define (adder n) (lambda (x) (+ x n))) ((adder 10) 5)", "15")

    def test_closures_keep_independent_state(self):
        self.run_lisp("""
          (define (make-counter)
            (let ((n 0)) (lambda () (set! n (+ n 1)) n)))
          (define c1 (make-counter))
          (define c2 (make-counter))
          (c1) (c1) (c2)""")
        self.assertShows("(list (c1) (c2))", "(3 2)")

    def test_begin(self):
        self.assertShows("(begin 1 2 3)", "3")
        self.assertShows("(begin)", "()")

    def test_let_binds_in_parallel(self):
        # every value is evaluated in the OUTER scope: y sees the outer x
        self.assertShows("(define x 1) (let ((x 2) (y x)) (list x y))", "(2 1)")

    def test_let_star_binds_sequentially(self):
        self.assertShows("(let* ((a 1) (b (+ a 1)) (c (* b 10))) (list a b c))", "(1 2 20)")

    def test_let_scope_does_not_leak(self):
        self.assertLispError("(let ((tmp 1)) tmp) tmp", "unbound symbol")

    def test_let_body_may_have_several_forms(self):
        self.assertShows("(let ((a 1)) (define b 2) (+ a b))", "3")

    def test_cond(self):
        self.assertShows("(cond (#f 1) ((> 2 1) 2) (else 3))", "2")
        self.assertShows("(cond (#f 1) (else 2 3))", "3")
        self.assertShows("(cond (#f 1))", "()")

    def test_and_or_return_values_and_short_circuit(self):
        self.assertShows("(and)", "#t")
        self.assertShows("(or)", "#f")
        self.assertShows("(and 1 2 3)", "3")
        self.assertShows("(and 1 #f 3)", "#f")
        self.assertShows("(or #f #f 3)", "3")
        self.assertShows("(or #f #f)", "#f")
        # the untaken operand must never run
        self.assertShows("(define n 0) (and #f (set! n 1)) (or #t (set! n 2)) n", "0")

    def test_dolist(self):
        self.run_lisp("(define total 0) (dolist (x (list 1 2 3 4 5)) (set! total (+ total x)))")
        self.assertShows("total", "15")

    def test_dolist_result_expression(self):
        self.assertShows("(dolist (x (list 1 2) 'done) x)", "done")
        self.assertShows("(dolist (x (list 1 2)) x)", "()")

    def test_dolist_evaluates_list_once(self):
        self.run_lisp("(define n 0) (define (lst) (set! n (+ n 1)) (list 1 2 3))")
        self.run_lisp("(dolist (x (lst)) x)")
        self.assertShows("n", "1")

    def test_special_forms_are_recognised_by_name(self):
        for name in ("quote", "quasiquote", "if", "define", "set!", "lambda", "begin",
                     "let", "let*", "cond", "and", "or", "dolist", "defmacro",
                     "defstruct", "with-struct", "catch-error", "breakpoint"):
            self.assertIn(name, lisp_core.SPECIAL_FORMS)


# ---------------------------------------------------------------------------
# 3. Tail calls and deep recursion
# ---------------------------------------------------------------------------

class TestTailCallsAndRecursion(LispTestCase):

    def test_deep_non_tail_recursion_needs_no_python_recursion(self):
        # far beyond Python's default recursion limit of 1000
        self.assertShows("(define (sum-to n) (if (= n 0) 0 (+ n (sum-to (- n 1))))) (sum-to 20000)",
                         str(20000 * 20001 // 2))

    def test_tail_recursion_runs_in_constant_space(self):
        self.assertShows("(define (loop n acc) (if (= n 0) acc (loop (- n 1) (+ acc 1)))) (loop 100000 0)",
                         "100000")

    def test_mutual_tail_recursion(self):
        self.assertShows("""
          (define (even2? n) (if (= n 0) #t (odd2? (- n 1))))
          (define (odd2? n)  (if (= n 0) #f (even2? (- n 1))))
          (even2? 50001)""", "#f")

    def test_tail_position_through_cond_and_or_let_begin(self):
        self.assertShows("""
          (define (f n)
            (cond ((= n 0) 'done)
                  (else (let ((m (- n 1)))
                          (begin (and #t (or #f (f m))))))))
          (f 30000)""", "done")

    def test_control_stack_depth_does_not_grow_with_tail_iterations(self):
        """Not just 'doesn't crash': the explicit control stack's peak depth
        is the same for 100 iterations as for 5000."""
        def peak_depth(n):
            peak = [0]
            real = lisp_core.push_sequence

            def spy(exprs, env, control_stack, value_stack):
                peak[0] = max(peak[0], len(control_stack))
                return real(exprs, env, control_stack, value_stack)

            with mock.patch.object(lisp_core, "push_sequence", spy):
                self.run_lisp("(define (loop n) (if (= n 0) 'ok (loop (- n 1)))) (loop %d)" % n)
            return peak[0]

        self.assertEqual(peak_depth(100), peak_depth(5000))

    def test_macro_expansion_in_tail_position_is_also_constant_space(self):
        self.run_lisp("""
          (defmacro my-while (test body)
            `(let ()
               (define (%loop) (if ,test (begin ,body (%loop)) '()))
               (%loop)))
          (define i 0)
          (define total 0)
          (my-while (< i 30000) (begin (set! total (+ total i)) (set! i (+ i 1))))""")
        self.assertShows("total", str(sum(range(30000))))

    def test_dolist_over_a_long_list(self):
        self.assertShows("""
          (define (build n acc) (if (= n 0) acc (build (- n 1) (cons n acc))))
          (define total 0)
          (dolist (x (build 20000 '())) (set! total (+ total x)))
          total""", str(sum(range(1, 20001))))


# ---------------------------------------------------------------------------
# 4. Variadic and keyword arguments
# ---------------------------------------------------------------------------

class TestVariadicAndKeywordArgs(LispTestCase):

    def test_fixed_arity_is_enforced(self):
        self.assertLispError("((lambda (a) a) 1 2)", "expected 1 argument(s), got 2")
        self.assertLispError("((lambda (a b) a) 1)", "expected 2 argument(s), got 1")

    def test_dotted_rest_parameter(self):
        self.run_lisp("(define (f a . rest) (list a rest))")
        self.assertShows("(f 1)", "(1 ())")
        self.assertShows("(f 1 2 3)", "(1 (2 3))")

    def test_bare_symbol_collects_every_argument(self):
        self.assertShows("((lambda args args) 1 2 3)", "(1 2 3)")
        self.assertShows("((lambda args args))", "()")

    def test_rest_needs_at_least_the_fixed_arguments(self):
        self.assertLispError("((lambda (a b . r) a) 1)", "expected at least 2")

    def test_keyword_arguments_any_order(self):
        self.run_lisp("(define (f a &key (b 10) c) (list a b c))")
        self.assertShows("(f 1)", "(1 10 ())")
        self.assertShows("(f 1 :c 30 :b 20)", "(1 20 30)")
        self.assertShows("(f 1 :c 30)", "(1 10 30)")

    def test_keyword_default_can_refer_to_earlier_parameters(self):
        self.run_lisp("(define (f &key (a 1) (b (+ a 1))) (list a b))")
        self.assertShows("(f)", "(1 2)")
        self.assertShows("(f :a 10)", "(10 11)")

    def test_unknown_keyword_is_an_error(self):
        self.run_lisp("(define (f &key (b 10)) b)")
        self.assertLispError("(f :nope 1)", "unknown keyword")

    def test_unpaired_keyword_is_an_error(self):
        self.run_lisp("(define (f &key (b 10)) b)")
        self.assertLispError("(f :b)", "unpaired")

    def test_non_keyword_where_keyword_expected_is_an_error(self):
        self.run_lisp("(define (f &key (b 10)) b)")
        self.assertLispError("(f 5 6)", "expected a keyword")


# ---------------------------------------------------------------------------
# 5. Macros
# ---------------------------------------------------------------------------

class TestMacros(LispTestCase):

    def test_arguments_are_not_evaluated_before_expansion(self):
        self.run_lisp("(defmacro my-unless (test then) `(if (not ,test) ,then '()))")
        self.assertShows("(my-unless (> 1 2) 'shown)", "shown")
        self.assertShows("(my-unless (> 2 1) 'shown)", "()")
        # `then` would blow up if it were ever evaluated
        self.assertShows("(my-unless #t (boom-if-this-ever-runs))", "()")

    def test_macro_can_mutate_the_callers_variables(self):
        self.run_lisp("""
          (defmacro swap! (a b) `(let ((tmp ,a)) (set! ,a ,b) (set! ,b tmp)))
          (define p 1) (define q 2) (swap! p q)""")
        self.assertShows("(list p q)", "(2 1)")

    def test_expansion_is_evaluated_in_the_callers_environment(self):
        self.run_lisp("(defmacro show-x () 'x)")
        self.assertShows("(define x 7) (show-x)", "7")
        self.assertShows("(let ((x 99)) (show-x))", "99")

    def test_variadic_macro(self):
        self.run_lisp("(defmacro my-or (. exprs) (if (null? exprs) #f `(let ((t ,(car exprs))) (if t t (my-or ,@(cdr exprs))))))")
        self.assertShows("(my-or #f #f 3)", "3")
        self.assertShows("(my-or)", "#f")

    def test_keyword_arguments_for_macros(self):
        self.run_lisp("(defmacro m (a &key (b 10)) `(list ,a ,b))")
        self.assertShows("(m 1)", "(1 10)")
        self.assertShows("(m 1 :b 2)", "(1 2)")

    def test_macro_expanding_into_another_macro(self):
        self.run_lisp("""
          (defmacro m1 (x) `(+ ,x 1))
          (defmacro m2 (x) `(m1 ,x))""")
        self.assertShows("(m2 5)", "6")

    def test_macroexpand_1_expands_one_step(self):
        self.run_lisp("""
          (defmacro m1 (x) `(+ ,x 1))
          (defmacro m2 (x) `(m1 ,x))""")
        self.assertShows("(macroexpand-1 '(m2 5))", "(m1 5)")

    def test_macroexpand_unwinds_the_outermost_form_fully(self):
        self.run_lisp("""
          (defmacro m1 (x) `(+ ,x 1))
          (defmacro m2 (x) `(m1 ,x))""")
        self.assertShows("(macroexpand '(m2 5))", "(+ 5 1)")

    def test_macroexpand_leaves_non_macro_forms_alone(self):
        self.assertShows("(macroexpand-1 '(+ 1 2))", "(+ 1 2)")

    def test_print_macroexpansion_writes_to_output(self):
        self.run_lisp("(defmacro m1 (x) `(+ ,x 1)) (print-macroexpansion '(m1 5))")
        self.assertIn("+", self.printed())

    def test_gensym_symbols_are_unique_and_unwritable(self):
        self.assertShows("(eq? (gensym) (gensym))", "#f")
        self.assertTrue(self.show("(gensym)").startswith("%"))
        self.assertTrue(self.show('(gensym "tmp")').startswith("%tmp-"))

    def test_a_gensym_is_equal_only_to_itself(self):
        self.run_lisp("(define g (gensym))")
        self.assertShows("(symbol? g)", "#t")
        self.assertShows("(list (eq? g g) (equal? g g))", "(#t #t)")
        self.assertShows("(list (eq? g (string->symbol (symbol->string g)))"
                         "      (equal? g (string->symbol (symbol->string g))))", "(#f #f)")

    def test_a_gensym_cannot_collide_with_a_name_the_program_uses(self):
        # Give a function the exact name the next while loop's gensym will
        # print as; the loop body's call must still reach that function.
        lisp_core.run_file(lisp_builtins.MACROS_INIT_FILE, self.env)
        next_name = "%%while-loop-%d" % (lisp_core._gensym_counter[0] + 1)
        self.run_lisp("(define calls 0) (define (%s) (set! calls (+ calls 1))) (define i 0)" % next_name)
        self.run_lisp("(while (< i 3) (set! i (+ i 1)) (%s))" % next_name)
        self.assertShows("calls", "3")

    def test_a_pasted_macro_expansion_still_works(self):
        lisp_core.run_file(lisp_builtins.MACROS_INIT_FILE, self.env)
        expansion = self.show("(macroexpand-1 '(while (< i 3) (set! i (+ i 1))))")
        self.run_lisp("(define i 0)")
        self.run_lisp(expansion)                 # the printed names read back as ordinary symbols
        self.assertShows("i", "3")

    def test_hygiene_with_gensym(self):
        """A macro that binds a temporary must not capture the caller's own
        variable of the same name -- the standard reason gensym exists."""
        self.run_lisp("""
          (defmacro my-twice (expr)
            (let ((g (gensym)))
              `(let ((,g ,expr)) (+ ,g ,g))))
          (define g 100)""")
        self.assertShows("(my-twice (+ g 1))", "202")

    def test_a_macro_is_not_a_procedure(self):
        self.run_lisp("(defmacro m (x) x)")
        self.assertShows("(procedure? m)", "#f")

    def test_defmacro_returns_the_name(self):
        self.assertShows("(defmacro m (x) x)", "m")

    def test_defined_macros_lists_user_macros(self):
        self.run_lisp("(defmacro my-mac (x) x)")
        self.assertIn("my-mac", self.show("(defined-macros)"))


# ---------------------------------------------------------------------------
# 6. Structs (defstruct) and with-struct
# ---------------------------------------------------------------------------

class TestStructs(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("(defstruct point x y (label \"origin\"))")

    def test_constructor_accessors_and_defaults(self):
        self.run_lisp("(define p (make-point :x 1 :y 2))")
        self.assertShows("(point-x p)", "1")
        self.assertShows("(point-y p)", "2")
        self.assertShows("(point-label p)", '"origin"')

    def test_slot_without_default_is_the_empty_list(self):
        self.run_lisp("(define p (make-point))")
        self.assertShows("(point-x p)", "()")

    def test_keyword_arguments_may_come_in_any_order(self):
        self.assertShows("(point-y (make-point :y 9 :x 8))", "9")

    def test_unknown_slot_keyword_is_an_error(self):
        self.assertLispError("(make-point :z 1)", "unknown keyword")

    def test_defaults_are_evaluated_per_call_and_may_see_earlier_slots(self):
        self.run_lisp("(defstruct box w (h w))")
        self.assertShows("(box-h (make-box :w 4))", "4")
        self.run_lisp("(define n 0) (defstruct stamp (id (begin (set! n (+ n 1)) n)))")
        self.assertShows("(list (stamp-id (make-stamp)) (stamp-id (make-stamp)))", "(1 2)")

    def test_setters_mutate_in_place(self):
        self.run_lisp("(define p (make-point :x 1 :y 2)) (point-x-set! p 99)")
        self.assertShows("(point-x p)", "99")

    def test_predicate(self):
        self.assertShows("(point? (make-point))", "#t")
        self.assertShows("(point? 5)", "#f")
        self.assertShows("(point? '(1 2))", "#f")

    def test_copy_is_shallow_and_independent(self):
        self.run_lisp("(define p (make-point :x 1 :y 2)) (define q (copy-point p)) (point-x-set! q 50)")
        self.assertShows("(list (point-x p) (point-x q))", "(1 50)")

    def test_structural_equality(self):
        self.assertShows("(equal? (make-point :x 1 :y 2) (make-point :x 1 :y 2))", "#t")
        self.assertShows("(equal? (make-point :x 1 :y 2) (make-point :x 1 :y 3))", "#f")

    def test_printed_form_lists_slots_in_declared_order(self):
        self.assertShows("(make-point :x 1 :y 2)", '#S(point :x 1 :y 2 :label "origin")')

    def test_generic_struct_builtins(self):
        self.run_lisp("(define p (make-point :x 1 :y 2))")
        self.assertShows("(struct? p)", "#t")
        self.assertShows("(struct? 5)", "#f")
        self.assertShows("(struct-type-name p)", "point")
        self.assertShows("(struct-ref p 'y)", "2")
        self.run_lisp("(struct-set! p 'y 20)")
        self.assertShows("(point-y p)", "20")

    def test_generic_struct_builtins_reject_bad_input(self):
        self.run_lisp("(define p (make-point))")
        self.assertLispError("(struct-ref p 'nope)", "no slot")
        self.assertLispError("(struct-ref 5 'x)", "not a struct")
        self.assertLispError("(struct-set! p 'nope 1)", "no slot")

    def test_accessor_rejects_the_wrong_type(self):
        self.assertLispError("(point-x 5)", "not a point")
        self.run_lisp("(defstruct other a)")
        self.assertLispError("(point-x (make-other :a 1))", "not a point")

    def test_two_struct_types_are_distinct(self):
        self.run_lisp("(defstruct pt2 x y)")
        self.assertShows("(equal? (make-point :x 1 :y 2 :label ()) (make-pt2 :x 1 :y 2))", "#f")

    def test_defstruct_returns_the_type_name(self):
        self.assertShows("(defstruct thing a)", "thing")


class TestStructInheritance(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (defstruct point x y)
          (defstruct (point-3d (:include point)) z)
          (define p (make-point :x 1 :y 2))
          (define c (make-point-3d :x 10 :y 20 :z 30))""")

    def test_child_has_parent_slots_first_then_its_own(self):
        self.assertShows("c", "#S(point-3d :x 10 :y 20 :z 30)")

    def test_parent_accessors_work_on_child_instances(self):
        self.assertShows("(point-x c)", "10")
        self.assertShows("(point-3d-x c)", "10")
        self.run_lisp("(point-x-set! c 11)")
        self.assertShows("(point-3d-x c)", "11")          # the identical slot

    def test_predicates_follow_the_is_a_relationship(self):
        self.assertShows("(point? c)", "#t")
        self.assertShows("(point-3d? c)", "#t")
        self.assertShows("(point-3d? p)", "#f")

    def test_child_only_accessor_rejects_a_plain_parent(self):
        self.assertLispError("(point-3d-z p)", "not a point-3d")

    def test_copy_of_a_child_through_the_parent_keeps_the_childs_type(self):
        self.assertShows("(point-3d? (copy-point c))", "#t")
        self.assertShows("(point-3d-z (copy-point c))", "30")

    def test_default_override_inside_the_include_clause(self):
        self.run_lisp("""
          (defstruct animal (name "unknown") (legs 4))
          (defstruct (bird (:include animal (legs 2))) can-fly)""")
        self.assertShows("(animal-legs (make-bird))", "2")
        self.assertShows("(bird-name (make-bird))", '"unknown"')

    def test_default_override_by_redeclaring_the_slot(self):
        self.run_lisp("""
          (defstruct animal (name "unknown") (legs 4))
          (defstruct (spider (:include animal)) (legs 8) has-web)""")
        self.assertShows("(spider-legs (make-spider))", "8")
        # slot order is unchanged: still name, legs, has-web
        self.assertShows("(make-spider)", '#S(spider :name "unknown" :legs 8 :has-web ())')

    def test_multi_level_inheritance(self):
        self.run_lisp("(defstruct (point-4d (:include point-3d)) w) (define d (make-point-4d :x 1 :y 2 :z 3 :w 4))")
        self.assertShows("(list (point? d) (point-3d? d) (point-4d? d))", "(#t #t #t)")
        self.assertShows("(point-x d)", "1")

    def test_including_an_undefined_parent_is_an_error(self):
        self.assertLispError("(defstruct (child (:include nonexistent)) a)", "not a known struct type")

    def test_unsupported_defstruct_option_is_an_error(self):
        self.assertLispError("(defstruct (child (:bogus 1)) a)", "unsupported option")

    def test_call_method_dispatches_on_the_instance(self):
        self.run_lisp("""
          (defstruct animal (name "unknown") (speak (lambda (self) "...")))
          (defstruct (dog (:include animal (speak (lambda (self) "Woof!")))))
          (defstruct (cat (:include animal (speak (lambda (self) "Meow!")))))
          (define (make-noise a) (call-method animal-speak a))""")
        self.assertShows("(make-noise (make-dog))", '"Woof!"')
        self.assertShows("(make-noise (make-cat))", '"Meow!"')
        self.assertShows("(make-noise (make-animal))", '"..."')

    def test_call_method_passes_the_instance_and_extra_arguments(self):
        self.run_lisp("""
          (defstruct acct (balance 100) (deposit (lambda (self n) (+ (acct-balance self) n))))""")
        self.assertShows("(call-method acct-deposit (make-acct) 5)", "105")


class TestWithStruct(LispTestCase):
    """(with-struct struct-expr body...) -- bind every slot as a variable."""

    def setUp(self):
        super().setUp()
        self.run_lisp("(defstruct point x y (label \"origin\")) (define p (make-point :x 3 :y 4))")

    def test_binds_every_slot_including_defaults(self):
        self.assertShows("(with-struct p (list x y label))", '(3 4 "origin")')

    def test_body_can_compute_with_the_slots(self):
        self.assertShows("(with-struct p (sqrt (+ (* x x) (* y y))))", "5.0")

    def test_struct_expression_is_evaluated_exactly_once(self):
        self.run_lisp("""
          (define n 0)
          (define (fresh) (set! n (+ n 1)) (make-point :x 1 :y 2))
          (with-struct (fresh) (+ x y))""")
        self.assertShows("n", "1")

    def test_works_on_any_struct_type(self):
        self.run_lisp("(defstruct loan balance rate) (defstruct pair-of a b)")
        self.assertShows("(with-struct (make-loan :balance 100 :rate 5) (* balance rate))", "500")
        self.assertShows("(with-struct (make-pair-of :a 1 :b 2) (list b a))", "(2 1)")

    def test_inherited_slots_are_bound_too(self):
        self.run_lisp("(defstruct (point-3d (:include point)) z)")
        self.assertShows("(with-struct (make-point-3d :x 1 :y 2 :z 3) (list x y z label))",
                         '(1 2 3 "origin")')

    def test_works_when_the_struct_is_a_function_parameter(self):
        self.run_lisp("(define (norm2 pt) (with-struct pt (+ (* x x) (* y y))))")
        self.assertShows("(norm2 p)", "25")

    def test_slot_names_shadow_outer_variables_only_inside_the_body(self):
        self.run_lisp("(define x 100)")
        self.assertShows("(with-struct p x)", "3")
        self.assertShows("x", "100")

    def test_other_variables_in_scope_stay_visible(self):
        self.run_lisp("(define k 10)")
        self.assertShows("(with-struct p (+ x k))", "13")

    def test_values_are_a_snapshot_taken_at_entry(self):
        self.assertShows("(with-struct p (begin (point-x-set! p 999) (list x (point-x p))))", "(3 999)")

    def test_set_bang_on_a_bound_name_does_not_write_back(self):
        self.run_lisp("(with-struct p (set! y 0))")
        self.assertShows("(point-y p)", "4")

    def test_define_inside_the_body_stays_local(self):
        self.run_lisp("(with-struct p (define tmp 99))")
        self.assertLispError("tmp", "unbound symbol")

    def test_empty_body_returns_the_empty_list(self):
        self.assertShows("(with-struct p)", "()")

    def test_multiple_body_forms_return_the_last(self):
        self.assertShows("(with-struct p (display \"side effect\") (+ x y))", "7")
        self.assertEqual(self.printed(), "side effect")

    def test_closures_capture_the_bound_slots(self):
        self.run_lisp("(define add-x (with-struct p (lambda (k) (+ x k))))")
        self.assertShows("(add-x 10)", "13")

    def test_a_lambda_stored_in_a_slot_is_callable_by_its_slot_name(self):
        self.run_lisp("(defstruct thing (f (lambda (n) (* n 3))))")
        self.assertShows("(with-struct (make-thing) (f 4))", "12")

    def test_forms_nest_and_the_inner_struct_wins(self):
        self.run_lisp("(defstruct a v w) (defstruct b v)")
        self.assertShows("(with-struct (make-a :v 1 :w 2) (list v w (with-struct (make-b :v 10) (list v w))))",
                         "(1 2 (10 2))")

    def test_usable_inside_a_macro_expansion(self):
        self.run_lisp("(defmacro norm-of (s) `(with-struct ,s (sqrt (+ (* x x) (* y y)))))")
        self.assertShows("(norm-of (make-point :x 3 :y 4))", "5.0")

    def test_usable_inside_dolist(self):
        self.run_lisp("""
          (define pts (list (make-point :x 1 :y 1) (make-point :x 2 :y 2)))
          (define total 0)
          (dolist (pt pts) (with-struct pt (set! total (+ total x y))))""")
        self.assertShows("total", "6")

    def test_a_slot_named_like_a_function_hides_it_inside_the_body(self):
        self.run_lisp("(defstruct weird list)")
        self.assertLispError("(with-struct (make-weird :list 5) (list 1 2))", "not a procedure")
        self.assertShows("(list 1 2)", "(1 2)")                   # unaffected outside

    def test_non_struct_argument_is_an_error(self):
        self.assertLispError("(with-struct 42 x)", "not a struct")
        self.assertLispError("(with-struct '(1 2) x)", "not a struct")

    def test_missing_argument_is_an_error(self):
        self.assertLispError("(with-struct)", "expected (with-struct struct-expr body...)")

    def test_body_is_in_tail_position(self):
        self.run_lisp("""
          (defstruct counter n limit)
          (define (spin c)
            (with-struct c
              (if (>= n limit) n (spin (make-counter :n (+ n 1) :limit limit)))))""")
        self.assertShows("(spin (make-counter :n 0 :limit 20000))", "20000")


# ---------------------------------------------------------------------------
# 7. Errors and catch-error
# ---------------------------------------------------------------------------

class TestErrorsAndCatchError(LispTestCase):

    def test_unbound_symbol(self):
        self.assertLispError("nope", "unbound symbol: nope")

    def test_calling_a_non_procedure(self):
        self.assertLispError("(5 3)", "not a procedure")

    def test_error_builtin_joins_its_arguments_display_style(self):
        self.assertLispError('(error "bad value:" 42 "and text")', "bad value: 42 and text")

    def test_catch_error_binds_the_message(self):
        self.assertShows('(catch-error (error "boom" 1) (e) e)', '"boom 1"')

    def test_catch_error_returns_the_protected_value_on_success(self):
        self.assertShows("(catch-error (+ 1 2) (e) 'handler-ran)", "3")

    def test_catch_error_handler_body_is_an_implicit_begin(self):
        self.assertShows("(catch-error (error \"x\") (e) (display \"handled \") 'value)", "value")
        self.assertEqual(self.printed(), "handled ")

    def test_catch_error_also_catches_plain_python_exceptions(self):
        self.assertShows("(catch-error (sqrt -1) (e) 'caught)", "caught")
        self.assertShows("(catch-error (/ 1 0) (e) 'caught)", "caught")
        self.assertShows("(catch-error (vector-ref #(1 2 3) 10) (e) 'caught)", "caught")
        self.assertShows("(catch-error (string->number \"abc\") (e) 'caught)", "caught")

    def test_catch_error_scope_does_not_leak_the_handler_variable(self):
        self.run_lisp("(catch-error (error \"x\") (err) 1)")
        self.assertLispError("err", "unbound symbol")

    def test_uncaught_errors_propagate(self):
        self.assertLispError("(begin (catch-error 1 (e) 2) (error \"escapes\"))", "escapes")

    def test_catch_error_inside_a_function_does_not_stop_the_caller(self):
        self.run_lisp("""
          (define (safe-div a b) (catch-error (/ a b) (e) 'div-by-zero))""")
        self.assertShows("(list (safe-div 6 3) (safe-div 1 0))", "(2.0 div-by-zero)")

    def test_errors_inside_callbacks_propagate_out_of_map(self):
        self.assertLispError("(map (lambda (x) (error \"in callback\" x)) (list 1 2))", "in callback 1")

    def test_wrong_argument_count_to_a_builtin_is_reported(self):
        with self.assertRaises(Exception):
            self.run_lisp("(car 1 2)")


class TestUnwindProtect(LispTestCase):
    """(unwind-protect protected-expr cleanup-expr...): cleanup always runs."""

    def setUp(self):
        super().setUp()
        self.run_lisp("(define log '()) (define (note x) (set! log (cons x log)))")

    def test_returns_the_protected_value_and_runs_the_cleanup(self):
        self.assertShows("(unwind-protect (+ 1 2) (note 'a) (note 'b))", "3")
        self.assertShows("log", "(b a)")

    def test_cleanup_runs_when_there_is_an_error(self):
        self.assertLispError("(unwind-protect (car 5) (note 'cleaned))", "car: not a pair")
        self.assertShows("log", "(cleaned)")

    def test_cleanup_runs_when_there_is_a_throw(self):
        self.assertShows("(catch 'out (unwind-protect (throw 'out 42) (note 'cleaned)))", "42")
        self.assertShows("log", "(cleaned)")

    def test_cleanup_runs_when_an_error_comes_from_deep_inside_a_call(self):
        self.run_lisp("(define (f n) (if (= n 0) (error \"bottom\") (+ 1 (f (- n 1)))))")
        self.assertShows("(catch-error (unwind-protect (f 100) (note 'cleaned)) (e) e)", '"bottom"')
        self.assertShows("log", "(cleaned)")

    def test_nested_cleanups_run_innermost_first(self):
        self.assertLispError("(unwind-protect (unwind-protect (error \"x\") (note 'inner)) (note 'outer))", "x")
        self.assertShows("log", "(outer inner)")

    def test_an_error_in_the_cleanup_is_reported(self):
        self.assertLispError("(unwind-protect 1 (error \"cleanup failed\"))", "cleanup failed")

    def test_malformed(self):
        self.assertLispError("(unwind-protect)", "expected (unwind-protect")


class TestCatchAndThrow(LispTestCase):
    """(catch tag body...) and (throw tag [value])."""

    def test_throw_leaves_the_catch_with_its_value(self):
        self.assertShows("(catch 'done (throw 'done 42) 'not-reached)", "42")

    def test_catch_without_a_throw_returns_its_body_value(self):
        self.assertShows("(catch 'done 1 2 3)", "3")

    def test_throw_without_a_value_gives_nil(self):
        self.assertShows("(catch 'done (throw 'done))", "()")

    def test_early_exit_from_a_loop(self):
        self.run_lisp("""
          (define (first-negative lst)
            (catch 'found
              (dolist (x lst) (if (< x 0) (throw 'found x)))
              '()))""")
        self.assertShows("(first-negative (list 3 1 -4 1 -5))", "-4")
        self.assertShows("(first-negative (list 3 1))", "()")

    def test_throw_from_deep_inside_calls_and_callbacks(self):
        self.run_lisp("(define (dig n) (if (= n 0) (throw 'deep 'bottom) (+ 1 (dig (- n 1)))))")
        self.assertShows("(catch 'deep (dig 5000))", "bottom")
        self.assertShows("(catch 'out (map (lambda (x) (if (< x 0) (throw 'out x) x)) (list 1 -2 3)))", "-2")

    def test_the_innermost_matching_catch_gets_the_throw(self):
        self.assertShows("(catch 'a (catch 'b (throw 'a 1)) 2)", "1")
        self.assertShows("(catch 'a (catch 'a (throw 'a 1)) 2)", "2")

    def test_tags_must_match_in_type_and_value(self):
        self.assertShows('(catch "t" (throw "t" 7))', "7")
        self.assertLispError("(catch 0 (throw #f 1))", "nothing catches #f")
        self.assertLispError("(catch 'x (throw :x 1))", "nothing catches :x")

    def test_catch_error_does_not_catch_a_throw(self):
        self.assertShows("(catch 'x (catch-error (throw 'x 'passed) (e) 'wrongly-caught))", "passed")

    def test_catch_does_not_catch_an_error(self):
        self.assertLispError("(catch 'x (car 5))", "car: not a pair")

    def test_a_throw_with_no_catch_is_an_error(self):
        self.assertLispError("(throw 'nowhere 1)", "nothing catches nowhere")
        self.assertLispError("(begin (catch 'x 1) (throw 'x 2))", "nothing catches x")   # that catch has finished

    def test_malformed(self):
        self.assertLispError("(catch)", "expected (catch tag body...)")


class TestPrintingStrings(LispTestCase):
    """How strings print: in quotes, with quote marks and backslashes escaped."""

    def test_quote_marks_and_backslashes_are_escaped(self):
        self.assertShows(r'"say \"hi\""', r'"say \"hi\""')
        self.assertShows(r'"C:\\data"', r'"C:\\data"')
        self.assertShows(r'(list "a\"b" "c")', r'("a\"b" "c")')

    def test_the_printed_form_reads_back_as_the_same_string(self):
        for text in ['say "hi"', "C:\\data", 'both \\ and "', "two\nlines"]:
            printed = lisp_core.to_string(lisp_core.LispString(text))
            self.assertEqual(list(lisp_core.parse(printed))[0], text)

    def test_display_and_print_show_the_string_itself(self):
        self.run_lisp(r'(display "say \"hi\"") (newline) (print "C:\\data")')
        self.assertEqual(self.printed(), 'say "hi"\nC:\\data\n')


# ---------------------------------------------------------------------------
# 8. Arithmetic, comparison, equality
# ---------------------------------------------------------------------------

class TestNumbers(LispTestCase):

    def test_addition_and_multiplication_identities(self):
        self.assertShows("(+)", "0")
        self.assertShows("(*)", "1")
        self.assertShows("(+ 1 2 3)", "6")
        self.assertShows("(* 2 3 4)", "24")

    def test_subtraction(self):
        self.assertShows("(- 10 3 2)", "5")
        self.assertShows("(- 5)", "-5")
        self.assertLispError("(-)")

    def test_division_is_true_division(self):
        self.assertShows("(/ 20 2 5)", "2.0")
        self.assertShows("(/ 7 2)", "3.5")
        self.assertShows("(/ 4)", "0.25")
        self.assertLispError("(/)")

    def test_division_by_zero_is_a_python_zerodivisionerror(self):
        self.assertRaisesFromLisp(ZeroDivisionError, "(/ 1 0)")

    def test_mod_and_remainder_both_follow_the_divisor(self):
        self.assertShows("(mod 7 3)", "1")
        self.assertShows("(mod -7 3)", "2")
        self.assertShows("(remainder -7 3)", "2")

    def test_quotient_truncates_toward_zero(self):
        self.assertShows("(quotient 7 2)", "3")
        self.assertShows("(quotient -7 2)", "-3")

    def test_abs_min_max(self):
        self.assertShows("(abs -5)", "5")
        self.assertShows("(min 3 1 4 1 5)", "1")
        self.assertShows("(max 3 1 4 1 5)", "5")

    def test_sqrt(self):
        self.assertShows("(sqrt 16)", "4.0")
        self.assertRaisesFromLisp(ValueError, "(sqrt -1)")

    def test_expt_is_exact_for_integers_and_pow_is_always_float(self):
        self.assertShows("(expt 2 10)", "1024")
        self.assertShows("(pow 2 10)", "1024.0")
        self.assertShows("(expt 2 0.5)", str(2 ** 0.5))

    def test_log(self):
        self.assertShows("(log 8 2)", "3.0")
        self.assertAlmostEqual(self.run_lisp("(log 2.718281828459045)"), 1.0)

    def test_rounding_family(self):
        self.assertShows("(floor 3.7)", "3")
        self.assertShows("(ceiling 3.2)", "4")
        self.assertShows("(truncate -3.7)", "-3")
        self.assertShows("(round 3.5)", "4")
        self.assertShows("(round 2.5)", "2")                    # banker's rounding

    def test_sigmoid(self):
        self.assertShows("(sigmoid 0)", "0.5")
        self.assertAlmostEqual(self.run_lisp("(sigmoid 1000)"), 1.0)
        self.assertAlmostEqual(self.run_lisp("(sigmoid -1000)"), 0.0)

    def test_arithmetic_rejects_non_numbers_including_booleans(self):
        self.assertLispError('(+ 1 "a")', "not a number")
        self.assertLispError("(+ 1 #t)", "not a number")
        self.assertLispError("(* 2 '())", "not a number")

    def test_number_string_conversion(self):
        self.assertShows("(number->string 3)", '"3"')
        self.assertShows("(number->string 3.0)", '"3.0"')
        self.assertShows('(string->number "42")', "42")
        self.assertShows('(string->number "3.14")', "3.14")

    def test_integers_stay_exact_and_large(self):
        self.assertShows("(* 99999999999 99999999999)", str(99999999999 ** 2))


class TestRandom(LispTestCase):

    def test_seeding_makes_the_sequence_reproducible(self):
        self.run_lisp("(random-seed 42)")
        first = self.run_lisp("(random-float)")
        self.run_lisp("(random-seed 42)")
        self.assertEqual(self.run_lisp("(random-float)"), first)

    def test_random_float_range(self):
        self.run_lisp("(random-seed 1)")
        for _ in range(50):
            v = self.run_lisp("(random-float 10 20)")
            self.assertTrue(10 <= v < 20)

    def test_random_int_is_inclusive_of_both_endpoints(self):
        self.run_lisp("(random-seed 3)")
        seen = {self.run_lisp("(random-int 1 3)") for _ in range(200)}
        self.assertEqual(seen, {1, 2, 3})

    def test_random_int_degenerate_range_and_bad_range(self):
        self.assertShows("(random-int 5 5)", "5")
        self.assertLispError("(random-int 6 1)")


class TestComparisonAndPredicates(LispTestCase):

    def test_numeric_comparisons_are_chained(self):
        self.assertShows("(< 1 2 3)", "#t")
        self.assertShows("(< 1 3 2)", "#f")
        self.assertShows("(<= 1 1 2)", "#t")
        self.assertShows("(>= 3 3 1)", "#t")
        self.assertShows("(= 2 2 2)", "#t")
        self.assertShows("(= 2 2 3)", "#f")
        self.assertShows("(> 3 2 1)", "#t")

    def test_comparison_with_zero_or_one_argument_is_true(self):
        self.assertShows("(<)", "#t")
        self.assertShows("(< 1)", "#t")

    def test_not(self):
        self.assertShows("(not #f)", "#t")
        self.assertShows("(not #t)", "#f")
        self.assertShows("(not 0)", "#f")
        self.assertShows("(not '())", "#f")

    def test_eq_and_equal_are_both_value_equality(self):
        self.assertShows("(eq? '(1 2) (list 1 2))", "#t")
        self.assertShows('(equal? "abc" "abc")', "#t")
        self.assertShows("(equal? '(1 (2 3)) (list 1 (list 2 3)))", "#t")
        self.assertShows("(equal? 1 2)", "#f")

    def test_type_predicates(self):
        cases = {
            "(boolean? #t)": "#t", "(boolean? 0)": "#f",
            "(number? 3.5)": "#t", "(number? #t)": "#f", "(number? \"3\")": "#f",
            "(integer? 3)": "#t", "(integer? 3.0)": "#f",
            "(string? \"hi\")": "#t", "(string? 'hi)": "#f",
            "(symbol? 'foo)": "#t", "(symbol? \"foo\")": "#f",
            "(procedure? car)": "#t", "(procedure? (lambda (x) x))": "#t", "(procedure? 5)": "#f",
            "(pair? (cons 1 2))": "#t", "(pair? '())": "#f",
            "(list? '())": "#t", "(list? '(1 2))": "#t", "(list? 5)": "#f",
            "(null? '())": "#t", "(null? (list 1))": "#f",
            "(vector? #(1 2))": "#t", "(vector? '(1 2))": "#f",
            "(date? (date 2024 1 1))": "#t", "(date? 5)": "#f",
        }
        for src, expected in cases.items():
            self.assertShows(src, expected)


# ---------------------------------------------------------------------------
# 9. Lists
# ---------------------------------------------------------------------------

class TestLists(LispTestCase):

    def test_cons_car_cdr(self):
        self.assertShows("(cons 1 2)", "(1 . 2)")
        self.assertShows("(cons 1 (cons 2 '()))", "(1 2)")
        self.assertShows("(car (list 10 20 30))", "10")
        self.assertShows("(cdr (list 10 20 30))", "(20 30)")

    def test_car_and_cdr_of_a_non_pair_are_errors(self):
        self.assertLispError("(car '())", "car: not a pair: ()")
        self.assertLispError("(cdr 5)", "cdr: not a pair: 5")

    def test_set_car_and_set_cdr_change_the_pair_in_place(self):
        self.run_lisp("(define lst (list 1 2 3))")
        self.assertShows("(set-car! lst 'a)", "()")
        self.assertShows("lst", "(a 2 3)")
        self.run_lisp("(set-cdr! (cdr lst) (list 'x 'y))")
        self.assertShows("lst", "(a 2 x y)")
        self.assertShows("(define p (cons 1 2)) (set-cdr! p 3) p", "(1 . 3)")

    def test_set_car_is_seen_through_every_reference_to_the_pair(self):
        self.assertShows("(define a (list 1 2)) (define b a) (set-car! a 9) b", "(9 2)")

    def test_set_car_and_set_cdr_of_a_non_pair_are_errors(self):
        self.assertLispError("(set-car! '() 1)", "set-car!: not a pair: ()")
        self.assertLispError("(set-cdr! 5 1)", "set-cdr!: not a pair: 5")

    def test_list_append_reverse_length(self):
        self.assertShows("(list)", "()")
        self.assertShows("(append)", "()")
        self.assertShows("(append (list 1 2) (list 3 4) (list 5))", "(1 2 3 4 5)")
        self.assertShows("(reverse (list 1 2 3))", "(3 2 1)")
        self.assertShows("(length (list 1 2 3))", "3")
        self.assertShows("(length (list))", "0")

    def test_append_does_not_mutate_its_arguments(self):
        self.run_lisp("(define a (list 1 2)) (define b (append a (list 3)))")
        self.assertShows("a", "(1 2)")

    def test_list_ref_and_list_tail(self):
        self.assertShows("(list-ref (list 10 20 30) 1)", "20")
        self.assertShows("(list-tail (list 1 2 3 4 5) 2)", "(3 4 5)")
        self.assertShows("(list-tail (list 1 2) 0)", "(1 2)")
        self.assertShows("(list-tail (list 1 2) 2)", "()")
        self.assertLispError("(list-ref (list 1 2) 5)", "out of range")

    def test_assoc_and_member_return_false_not_nil_when_absent(self):
        self.run_lisp("(define al (list (cons 'a 1) (cons 'b 2)))")
        self.assertShows("(assoc 'b al)", "(b . 2)")
        self.assertShows("(cdr (assoc 'b al))", "2")
        self.assertShows("(assoc 'z al)", "#f")
        self.assertShows("(member 3 (list 1 2 3 4 5))", "(3 4 5)")
        self.assertShows("(member 99 (list 1 2 3))", "#f")

    def test_assoc_uses_equal_so_strings_work(self):
        self.assertShows('(assoc "k" (list (cons "k" 1)))', '("k" . 1)')

    def test_map_filter_reduce(self):
        self.assertShows("(map (lambda (x) (* x x)) (list 1 2 3))", "(1 4 9)")
        self.assertShows("(map (lambda (x) x) '())", "()")
        self.assertShows("(filter (lambda (x) (> x 2)) (list 1 2 3 4))", "(3 4)")
        self.assertShows("(reduce + (list 1 2 3 4))", "10")
        self.assertShows("(reduce + (list 1 2 3 4) 100)", "110")
        self.assertShows("(reduce + '() 7)", "7")

    def test_reduce_folds_left(self):
        self.assertShows("(reduce - (list 10 3 2))", "5")            # (10 - 3) - 2

    def test_apply(self):
        self.assertShows("(apply + (list 1 2 3))", "6")
        self.assertShows("(apply + 1 2 (list 3 4 5))", "15")
        self.assertShows("(apply max (list 4 9 2))", "9")

    def test_map_accepts_a_user_procedure_by_name(self):
        self.assertShows("(define (double x) (* 2 x)) (map double (list 1 2 3))", "(2 4 6)")

    def test_long_lists_print_without_recursion_problems(self):
        n = 5000
        self.run_lisp("(define (iota n acc) (if (= n 0) acc (iota (- n 1) (cons n acc))))")
        self.assertEqual(len(self.show("(iota %d '())" % n).split()), n)


# ---------------------------------------------------------------------------
# 10. Strings and symbols
# ---------------------------------------------------------------------------

class TestStrings(LispTestCase):

    def test_append_length_substring(self):
        self.assertShows('(string-append "foo" "bar")', '"foobar"')
        self.assertShows("(string-append)", '""')
        self.assertShows('(string-length "hello")', "5")
        self.assertShows('(substring "hello world" 0 5)', '"hello"')
        self.assertShows('(substring "hello" 2)', '"llo"')

    def test_substring_clamps_out_of_range_indices(self):
        self.assertShows('(substring "abc" 1 100)', '"bc"')

    def test_comparisons(self):
        self.assertShows('(string=? "abc" "abc")', "#t")
        self.assertShows('(string=? "abc" "abd")', "#f")
        self.assertShows('(string<? "abc" "abd")', "#t")
        self.assertShows('(string>? "abd" "abc")', "#t")

    def test_case_conversion(self):
        self.assertShows('(string-upcase "hi")', '"HI"')
        self.assertShows('(string-downcase "HI")', '"hi"')

    def test_string_list_round_trip(self):
        self.assertShows('(list->string (string->list "ab"))', '"ab"')
        self.assertShows('(string "a" "b" "c")', '"abc"')

    def test_characters_from_string_to_list_are_not_strings(self):
        self.assertShows('(string? (car (string->list "ab")))', "#f")

    def test_symbol_conversion(self):
        self.assertShows('(string->symbol "foo")', "foo")
        self.assertShows("(symbol->string 'foo)", '"foo"')

    def test_search_contains_split_replace_trim(self):
        self.assertShows('(string-search "hello world" "world")', "6")
        self.assertShows('(string-search "hello world" "xyz")', "#f")
        self.assertShows('(string-search "hello" "h")', "0")        # 0 is still true here
        self.assertShows('(string-contains? "hello world" "wor")', "#t")
        self.assertShows('(string-contains? "hello" "z")', "#f")
        self.assertShows('(string-split "a,b,,c" ",")', '("a" "b" "" "c")')
        self.assertShows('(string-split "  foo  bar ")', '("foo" "bar")')
        self.assertShows('(string-replace "foo bar foo" "foo" "X")', '"X bar X"')
        self.assertShows('(string-trim "  hi  ")', '"hi"')

    def test_display_shows_strings_without_quotes_and_print_adds_a_newline(self):
        self.run_lisp('(display "hi") (display " ") (display 42) (newline) (print "x")')
        self.assertEqual(self.printed(), "hi 42\nx\n")

    def test_string_escapes_survive_a_round_trip(self):
        self.assertShows(r'(string-length "a\nb")', "3")


class TestFormat(LispTestCase):
    """format and format-value: Python format specs applied to Lisp values."""

    def test_decimals_and_commas(self):
        self.assertShows('(format "{:,.2f}" 1234567.891)', '"1,234,567.89"')
        self.assertShows('(format "{:,}" 1234567)', '"1,234,567"')
        self.assertShows('(format "{:.0f}" 2.7)', '"3"')
        self.assertShows('(format "{:.2%}" 0.0525)', '"5.25%"')

    def test_left_center_and_right_justification_of_text_and_numbers(self):
        self.assertShows('(format "[{:<6}][{:^6}][{:>6}]" "ab" "ab" "ab")', '"[ab    ][  ab  ][    ab]"')
        self.assertShows('(format "[{:<8.1f}][{:^8,}][{:>8.2f}]" 1.25 1000 3)',
                         '"[1.2     ][ 1,000  ][    3.00]"')

    def test_default_alignment_is_right_for_numbers_and_left_for_text(self):
        self.assertShows('(format "[{:5}][{:5}]" 42 "ab")', '"[   42][ab   ]"')

    def test_fill_character_sign_and_zero_padding(self):
        self.assertShows('(format "{:*^9}" "mid")', '"***mid***"')
        self.assertShows('(format "{:+.1f}" 3.14159)', '"+3.1"')
        self.assertShows('(format "{:05d}" 42)', '"00042"')

    def test_text_precision_truncates_and_long_values_are_not_cut(self):
        self.assertShows('(format "[{:<6.3}]" "abcdef")', '"[abc   ]"')
        self.assertShows('(format "[{:>3}]" "abcdef")', '"[abcdef]"')

    def test_non_numbers_are_formatted_as_their_display_text(self):
        self.assertShows('(format "{} {} {} {}" "hi" (date 2023 1 1) \'sym (list 1 "a"))',
                         r'"hi 2023-01-01 sym (1 \"a\")"')     # a list shows as display shows it
        self.assertShows("(format \"{:>4}|{:>4}|{}\" #t #f '())", '"  #t|  #f|()"')

    def test_values_read_from_vectors_and_nan(self):
        self.assertShows('(format "{:.2f}" (vector-ref #(1.5 2.25) 1))', '"2.25"')
        self.assertShows('(format "{:,.2f}" nan)', '"nan"')

    def test_literal_braces(self):
        self.assertShows('(format "{{}} and {{x}} {}" 1)', '"{} and {x} 1"')

    def test_argument_count_must_match_the_placeholders(self):
        self.assertLispError('(format "{} {}" 1)', "more placeholders")
        self.assertLispError('(format "{}" 1 2)', "only 1 placeholder")

    def test_only_plain_placeholders_are_allowed(self):
        self.assertLispError('(format "{0}" 1)', "{} or {:spec}")
        self.assertLispError('(format "{name}" 1)', "{} or {:spec}")
        self.assertLispError('(format "{!r}" 1)', "{} or {:spec}")
        self.assertLispError('(format "oops }" 1)', "bad template")

    def test_a_number_spec_on_text_or_a_bad_spec_is_an_error(self):
        self.assertLispError('(format "{:.2f}" "CA")', "isn't a number")
        self.assertLispError('(format "{:d}" 5.5)', "can't format 5.5")

    def test_format_value(self):
        self.assertShows('(format-value 1234567.891 ",.2f")', '"1,234,567.89"')
        self.assertShows('(format-value 5.5)', '"5.5"')
        self.assertShows('(format-value "CA" (format ">{}" 4))', '"  CA"')


# ---------------------------------------------------------------------------
# 11. Hash tables
# ---------------------------------------------------------------------------

class TestHashTables(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("(define h (make-hash-table))")

    def test_set_and_ref(self):
        self.run_lisp("(hash-table-set! h 'name \"Ada\")")
        self.assertShows("(hash-table-ref h 'name)", '"Ada"')

    def test_missing_key_gives_false_or_the_default(self):
        self.assertShows("(hash-table-ref h 'missing)", "#f")
        self.assertShows('(hash-table-ref h \'missing "nobody")', '"nobody"')

    def test_has_distinguishes_absent_from_false(self):
        self.run_lisp("(hash-table-set! h 'flag #f)")
        self.assertShows("(hash-table-has? h 'flag)", "#t")
        self.assertShows("(hash-table-has? h 'other)", "#f")

    def test_overwrite_remove_and_count(self):
        self.run_lisp("(hash-table-set! h 'a 1) (hash-table-set! h 'a 2) (hash-table-set! h 'b 3)")
        self.assertShows("(hash-table-count h)", "2")
        self.assertShows("(hash-table-ref h 'a)", "2")
        self.run_lisp("(hash-table-remove! h 'a) (hash-table-remove! h 'never-there)")
        self.assertShows("(hash-table-count h)", "1")

    def test_keys_values_alist_preserve_insertion_order(self):
        self.run_lisp("(hash-table-set! h 'x 1) (hash-table-set! h 'y 2)")
        self.assertShows("(hash-table-keys h)", "(x y)")
        self.assertShows("(hash-table-values h)", "(1 2)")
        self.assertShows("(hash-table->alist h)", "((x . 1) (y . 2))")

    def test_for_each(self):
        self.run_lisp("""
          (hash-table-set! h 'a 1) (hash-table-set! h 'b 2)
          (define total 0)
          (hash-table-for-each (lambda (k v) (set! total (+ total v))) h)""")
        self.assertShows("total", "3")

    def test_various_immutable_key_types(self):
        self.run_lisp('(hash-table-set! h "s" 1) (hash-table-set! h 5 2) (hash-table-set! h (date 2024 1 1) 3)')
        self.assertShows('(hash-table-ref h "s")', "1")
        self.assertShows("(hash-table-ref h 5)", "2")
        self.assertShows("(hash-table-ref h (date 2024 1 1))", "3")

    def test_mutable_keys_are_rejected_with_a_clear_error(self):
        self.assertLispError("(hash-table-set! h (list 1) 2)", "not a hashable key")
        self.assertLispError("(hash-table-set! h (vector 1) 2)", "not a hashable key")

    def test_hash_table_predicate(self):
        self.assertShows("(hash-table? h)", "#t")
        self.assertShows("(hash-table? 5)", "#f")


# ---------------------------------------------------------------------------
# 12. Vectors
# ---------------------------------------------------------------------------

class TestVectors(LispTestCase):

    def test_construction(self):
        self.assertShows("(vector 1 2 3)", "#(1 2 3)")
        self.assertShows("(make-vector 3)", "#(0 0 0)")
        self.assertShows("(make-vector 3 9)", "#(9 9 9)")
        self.assertShows("(list->vector (list 1 2 3))", "#(1 2 3)")
        self.assertShows("(vector->list #(1 2 3))", "(1 2 3)")

    def test_ref_set_length_fill(self):
        self.run_lisp("(define v (vector 1 2 3))")
        self.assertShows("(vector-ref v 1)", "2")
        self.assertShows("(vector-length v)", "3")
        self.run_lisp("(vector-set! v 1 99)")
        self.assertShows("v", "#(1 99 3)")
        self.run_lisp("(vector-fill! v 0)")
        self.assertShows("v", "#(0 0 0)")

    def test_copy_is_independent(self):
        self.run_lisp("(define a (vector 1 2 3)) (define b (vector-copy a)) (vector-set! b 0 100)")
        self.assertShows("a", "#(1 2 3)")

    def test_map_append_iterate_sum(self):
        self.assertShows("(vector-map (lambda (x) (* x x)) #(1 2 3))", "#(1 4 9)")
        self.assertShows("(vector-append #(1 2) #(3 4))", "#(1 2 3 4)")
        self.assertShows("(vector-iterate 1 5 (lambda (x) (* x 2)))", "#(1 2 4 8 16)")
        self.assertShows("(vector-sum #(1 2 3 4))", "10")

    def test_elementwise_arithmetic(self):
        self.assertShows("(vector-add #(1 2 3) #(10 20 30))", "#(11 22 33)")
        self.assertShows("(vector-sub #(10 20 30) #(1 2 3))", "#(9 18 27)")
        self.assertShows("(vector-mul #(1 2 3) 10)", "#(10 20 30)")

    def test_arithmetic_needs_equal_lengths(self):
        self.assertLispError("(vector-add #(1 2 3) #(10 20))", "different lengths")

    def test_slicing(self):
        self.assertShows("(vector-slice #(1 2 3 4 5) 1 3)", "#(2 3)")
        self.assertShows("(vector-slice #(1 2 3 4 5) 3)", "#(4 5)")
        self.assertShows("(vector-take #(1 2 3 4 5) 2)", "#(1 2)")
        self.assertShows("(vector-drop #(1 2 3 4 5) 2)", "#(3 4 5)")

    def test_vectors_map_stops_at_shortest_or_pads_with_default(self):
        self.assertShows("(vectors-map (lambda (a b i) (+ a b)) (list (vector 1 2 3) (vector 10 20)))",
                         "#(11 22)")
        self.assertShows("(vectors-map (lambda (a b i) (+ a b)) (list (vector 1 2 3) (vector 10 20)) 0)",
                         "#(11 22 3)")

    def test_vectors_map_passes_the_index_last(self):
        self.assertShows("(vectors-map (lambda (a b i) (list a b i)) (list (vector 10 20) (vector 1 2)))",
                         "#((10 1 0) (20 2 1))")

    def test_only_numbers_strings_and_dates_are_allowed(self):
        self.assertShows('(vector 1 "a" (date 2024 1 1))', '#(1 "a" 2024-01-01)')
        self.assertLispError("(vector 1 #t)", "not a number, string, or date")
        self.assertLispError("(vector 1 (list 2))", "not a number, string, or date")

    def test_out_of_range_index_raises_indexerror(self):
        self.assertRaisesFromLisp(IndexError, "(vector-ref #(1 2 3) 10)")

    def test_dtype_is_chosen_from_the_contents_and_widens_on_demand(self):
        V = lisp_core.LispVector
        self.assertEqual(self.run_lisp("(vector 0 1 1 0)").items.dtype, V.BOOL_INT_DTYPE)
        self.assertEqual(self.run_lisp("(vector 1 2 300)").items.dtype, V.INT_DTYPE)
        self.assertEqual(self.run_lisp("(vector 1 2.5)").items.dtype, V.FLOAT_DTYPE)
        # a 0/1 flag vector transparently widens when a bigger value is written
        self.run_lisp("(define flags (vector 0 1 0))")
        self.run_lisp("(vector-set! flags 0 50000)")
        self.assertShows("(vector-ref flags 0)", "50000")

    def test_dates_in_vectors(self):
        self.assertShows("(vector-ref (vector (date 2024 1 1) (date 2024 2 1)) 1)", "2024-02-01")
        self.assertShows("(vector-iterate (date 2024 1 30) 3 (lambda (d) (date-add-days d 1)))",
                         "#(2024-01-30 2024-01-31 2024-02-01)")

    def test_shuffle_keeps_aligned_vectors_aligned_and_is_seedable(self):
        self.run_lisp("""
          (define xs (vector 1 2 3 4 5 6))
          (define ys (vector 10 20 30 40 50 60))
          (define s1 (vectors-shuffle (list xs ys) 42))
          (define s2 (vectors-shuffle (list xs ys) 42))""")
        self.assertShows("(equal? s1 s2)", "#t")
        self.assertShows("(vector-sub (car (cdr s1)) (vector-mul (car s1) 10))", "#(0 0 0 0 0 0)")
        self.assertShows("(vector-sum (car s1))", "21")


# ---------------------------------------------------------------------------
# 12b. Vector math, tables, monthly series, CSV files, and downloads
# ---------------------------------------------------------------------------

class TestVectorMath(LispTestCase):
    """lisp_vector_math.py: arithmetic, masks, statistics, and time series."""

    def test_arithmetic_with_vectors_and_numbers(self):
        self.assertShows("(vector-add #(1 2 3) 10)", "#(11 12 13)")
        self.assertShows("(vector-sub 10 #(1 2 3))", "#(9 8 7)")
        self.assertShows("(vector-mul #(1 2 3) #(2 2 2))", "#(2 4 6)")
        self.assertShows("(vector-div #(1 2) #(2 0))", "#(0.5 inf)")
        self.assertShows("(vector-pow #(2 3) 2)", "#(4.0 9.0)")
        self.assertShows("(vector-sub (vector (date 2020 1 11)) (vector (date 2020 1 1)))", "#(10.0)")

    def test_integer_arithmetic_does_not_overflow_small_storage(self):
        # a 0/1 vector is stored in one byte per element; 1 * 200 must not wrap
        self.assertShows("(vector-mul #(0 1 1) 200)", "#(0 200 200)")
        self.assertShows("(vector-add #(1 1) #(127 127))", "#(128 128)")

    def test_unary_math_and_clip(self):
        self.assertShows("(vector-sqrt #(4 9))", "#(2.0 3.0)")
        self.assertShows("(vector-log #(-1))", "#(nan)")
        self.assertShows("(vector-round #(1.26 2.5) 1)", "#(1.3 2.5)")
        self.assertShows("(vector-clip #(5 50 150) 10 100)", "#(10 50 100)")
        self.assertShows("(vector-clip #(5 150) '() 100)", "#(5 100)")

    def test_needs_a_vector_and_equal_lengths(self):
        self.assertLispError("(vector-add 1 2)", "at least one vector")
        self.assertLispError("(vector-mul #(1 2) #(1 2 3))", "different lengths")
        self.assertLispError('(vector-add (vector "a") 1)', "isn't a number")

    def test_comparisons_make_masks(self):
        self.assertShows("(vector> #(1 5 10) 4)", "#(0 1 1)")
        self.assertShows("(vector<= #(1 5) #(1 4))", "#(1 0)")
        self.assertShows('(vector= (vector "CA" "NY") "CA")', "#(1 0)")
        self.assertShows('(vector/= (vector "CA" "NY") "CA")', "#(0 1)")
        self.assertShows("(vector= (vector 1 nan) nan)", "#(0 0)")
        self.assertShows("(vector< (vector (date 2020 1 1) (date 2022 1 1)) (date 2021 1 1))", "#(1 0)")
        self.assertLispError('(vector< #(1 2) "a")', "can't compare")

    def test_combining_masks_and_selecting(self):
        self.assertShows("(vector-and #(1 1 0) #(1 0 0))", "#(1 0 0)")
        self.assertShows("(vector-or #(1 0 0) #(0 0 1) #(0 1 0))", "#(1 1 1)")
        self.assertShows("(vector-not (vector 1 0 nan))", "#(0 1 1)")
        self.assertShows("(vector-select #(10 20 30) #(0 1 1))", "#(20 30)")
        self.assertShows('(vector-where #(1 0) "yes" "no")', '#("yes" "no")')
        self.assertShows("(vector-where #(1 0) #(1 2) #(10 20))", "#(1 20)")

    def test_missing_values(self):
        self.assertShows("(vector-nan? (vector 1 nan))", "#(0 1)")
        self.assertShows('(vector-nan? (vector "a" "b"))', "#(0 0)")
        self.assertShows("(vector-fill-nan (vector 1.5 nan) 0)", "#(1.5 0.0)")
        self.assertShows("(vector-fill-forward (vector nan 1.5 nan 2 nan))", "#(nan 1.5 1.5 2.0 2.0)")

    def test_statistics_skip_missing_values(self):
        self.assertShows("(vector-sum (vector 1 nan 2))", "3.0")
        self.assertShows("(vector-count (vector 1 nan 2))", "2")
        self.assertShows("(vector-mean (vector 1 nan 3))", "2.0")
        self.assertShows("(vector-median #(3 1 2 10))", "2.5")
        self.assertShows("(vector-mean (vector nan))", "nan")
        self.assertAlmostEqual(self.run_lisp("(vector-variance #(2 4 4 4 5 5 7 9))"), 32 / 7)
        self.assertAlmostEqual(self.run_lisp("(vector-stdev #(2 4 4 4 5 5 7 9) #t)"), 2.0)
        self.assertShows("(vector-quantile #(1 2 3 4 5) 0.5)", "3.0")
        self.assertLispError("(vector-quantile #(1 2) 1.5)", "between 0 and 1")
        self.assertShows("(vector-weighted-mean (vector 5 7 nan) #(1 3 100))", "6.5")
        self.assertAlmostEqual(self.run_lisp("(vector-correlation #(1 2 3) #(3 2 1))"), -1.0)
        self.assertAlmostEqual(self.run_lisp("(vector-covariance #(1 2 3) #(2 4 6))"), 2.0)

    def test_min_and_max_work_on_numbers_strings_and_dates(self):
        self.assertShows("(vector-min (vector 3 nan 1))", "1.0")
        self.assertShows('(vector-max (vector "a" "c" "b"))', '"c"')
        self.assertShows("(vector-min (vector (date 2021 1 1) (date 2020 5 5)))", "2020-05-05")

    def test_lag_default_and_groups(self):
        self.assertShows("(vector-lag #(10 20 30))", "#(nan 10.0 20.0)")
        self.assertShows("(vector-lag #(10 20 30) 1 0)", "#(0 10 20)")
        self.assertShows("(vector-lag #(10 20 30) 5 -1)", "#(-1 -1 -1)")
        self.assertShows("(vector-lag #(10 20 30) -2)", "#(30.0 nan nan)")
        self.assertShows('(vector-lag #(1 2 3 4) 1 0 (vector "x" "x" "y" "y"))', "#(0 1 0 3)")
        self.assertShows('(vector-lag (vector "a" "b"))', '#(() "a")')
        self.assertShows('(vector-lag (vector "a" "b") 1 "none")', '#("none" "a")')

    def test_differences_and_running_values(self):
        self.assertShows("(vector-diff #(1 4 9))", "#(nan 3.0 5.0)")
        self.assertShows('(vector-diff #(1 4 9 1 3) 1 (vector "a" "a" "a" "b" "b"))', "#(nan 3.0 5.0 nan 2.0)")
        self.assertShows("(vector-pct-change #(100 150))", "#(nan 0.5)")
        self.assertShows("(vector-cumsum (vector 1 nan 2))", "#(1.0 nan 3.0)")
        self.assertShows("(vector-cumprod #(2 3 4))", "#(2.0 6.0 24.0)")
        self.assertShows("(vector-rolling-sum #(1 2 3 4) 2)", "#(nan 3.0 5.0 7.0)")
        self.assertShows("(vector-rolling-mean #(1 2) 5)", "#(nan nan)")

    def test_range_and_unique(self):
        self.assertShows("(vector-range 3)", "#(0 1 2)")
        self.assertShows("(vector-range 1 2 0.5)", "#(1.0 1.5)")
        self.assertShows("(vector-unique (vector 2 1 2))", "#(1 2)")
        self.assertShows('(vector-unique (vector "b" "a" "b"))', '#("a" "b")')

    def test_a_single_float_comes_back_as_its_short_decimal(self):
        self.assertShows("(vector-ref (vector 0.964 2.5) 0)", "0.964")


class TestTables(LispTestCase):
    """lisp_tables.py: tables are lists of (name . vector) columns."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define loans (make-table "id"      (vector "a" "a" "b" "b" "c")
                                    "month"   #(1 2 1 2 1)
                                    "state"   (vector "CA" "CA" "NY" "NY" "CA")
                                    "balance" #(100 90 200 195 50)
                                    "rate"    (vector 6.0 6.0 4.5 nan 7.25)))""")

    def test_looking_at_a_table(self):
        self.assertShows("(table-column-names loans)", '("id" "month" "state" "balance" "rate")')
        self.assertShows('(table-column loans "balance")', "#(100 90 200 195 50)")
        self.assertShows("(table-row-count loans)", "5")
        self.assertShows('(cdr (assoc "state" (table-row loans 2)))', '"NY"')
        self.assertShows('(table-column (table-head loans 2) "id")', '#("a" "a")')
        self.assertShows('(table-column (table-slice loans 3) "id")', '#("b" "c")')
        self.assertShows("(table? loans)", "#t")
        self.assertShows("(table? (list 1))", "#f")
        self.assertLispError('(table-column loans "nope")', "no column named")
        self.assertLispError("(table-row loans 99)", "out of range")
        self.assertLispError('(make-table "a" #(1 2) "b" #(1))', "different lengths")

    def test_choosing_and_changing_columns(self):
        self.assertShows('(table-column-names (table-select loans (list "rate" "id")))', '("rate" "id")')
        self.assertShows('(table-column-names (table-drop-columns loans (list "rate" "id")))',
                         '("month" "state" "balance")')
        self.assertShows('(table-column (table-add-column loans "one" 1) "one")', "#(1 1 1 1 1)")
        self.assertShows('(table-column-names (table-add-column loans "month" #(9 9 9 9 9)))',
                         '("id" "month" "state" "balance" "rate")')
        self.assertLispError('(table-add-column loans "x" #(1 2))', "5 rows")
        self.assertShows('(table-column-names (table-rename-column loans "id" "loan"))',
                         '("loan" "month" "state" "balance" "rate")')

    def test_filter_and_sort(self):
        self.assertShows('(table-column (table-filter loans (vector> (table-column loans "balance") 95)) "id")',
                         '#("a" "b" "b")')
        self.assertShows('(table-column (table-sort loans "balance" #t) "balance")', "#(200 195 100 90 50)")
        self.assertShows('(table-column (table-sort loans (list "state" "balance")) "balance")',
                         "#(50 90 100 195 200)")
        self.assertShows('(table-column (table-sort loans "rate") "rate")', "#(4.5 6.0 6.0 7.25 nan)")
        self.assertLispError("(table-filter loans #(1 0))", "mask has 2")

    def test_append(self):
        self.assertShows('(table-column (table-append (table-head loans 1) (table-slice loans 4)) "id")',
                         '#("a" "c")')
        self.assertLispError('(table-append loans (make-table "x" #(1)))', "different columns")

    def test_group_by(self):
        self.run_lisp("""
          (define g (table-group-by loans "state"
                       (list (list "n" 'count) (list "upb" 'sum "balance")
                             (list "wac" 'weighted-mean "rate" "balance")
                             (list "avg" "mean" "rate") (list "lo" 'min "balance")
                             (list "last_id" 'last "id") (list "med" 'median "balance"))))""")
        self.assertShows('(table-column g "state")', '#("CA" "NY")')
        self.assertShows('(table-column g "n")', "#(3 2)")
        self.assertShows('(table-column g "upb")', "#(240 395)")
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column g "wac") 1)'), 4.5)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column g "wac") 0)'),
                               (100 * 6 + 90 * 6 + 50 * 7.25) / 240, places=5)
        self.assertShows('(table-column g "avg")', "#(6.4166665 4.5)")
        self.assertShows('(table-column g "lo")', "#(50 195)")
        self.assertShows('(table-column g "last_id")', '#("c" "b")')
        self.assertShows('(table-column g "med")', "#(90.0 197.5)")
        self.assertShows('(table-column (table-group-by loans (list "state" "month") (list (list "n" (quote count)))) "n")',
                         "#(2 1 1 1)")
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'bogus \"rate\")))", "unknown function")
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'weighted-mean \"rate\")))", "weight column")

    def test_join(self):
        self.run_lisp('(define rates (make-table "month" #(1 2) "mkt" #(6.5 6.25) "rate" #(1 2)))')
        self.assertShows('(table-column (table-join loans rates "month") "mkt")', "#(6.5 6.25 6.5 6.25 6.5)")
        self.assertShows('(table-column (table-join loans rates "month") "rate_right")', "#(1 2 1 2 1)")
        self.run_lisp('(define few (make-table "month" #(2) "mkt" #(6.25)))')
        self.assertShows('(table-row-count (table-join loans few "month"))', "2")
        self.assertShows('(table-column (table-join loans few "month" (quote left)) "mkt")',
                         "#(nan 6.25 nan 6.25 nan)")
        # a left row matching two right rows appears twice, in left order
        self.run_lisp('(define two (make-table "k" (vector "x" "x") "v" #(10 20)))')
        self.assertShows('(table-column (table-join (make-table "k" (vector "x" "y")) two "k" (quote left)) "v")',
                         "#(10.0 20.0 nan)")
        self.assertShows('(table-column (table-join (make-table "k" (vector "y")) two "k") "v")', "#()")
        self.assertLispError('(table-join loans rates "month" (quote outer))', "how must be")

    def test_describe(self):
        self.run_lisp("(define d (table-describe loans))")
        self.assertShows('(table-column d "column")', '#("month" "balance" "rate")')
        self.assertShows('(table-column d "count")', "#(5 5 4)")
        self.assertShows('(table-column d "max")', "#(2.0 200.0 7.25)")


class TestTimeSeries(LispTestCase):
    """lisp_time_series.py: month numbers and monthly series."""

    def test_month_numbers(self):
        self.assertShows("(date->month-number (date 2020 1 31))", "24240")
        self.assertShows("(month-number->date 24252)", "2021-01-01")
        self.assertShows("(yyyymm->month-number #(202001 202012))", "#(24240 24251)")
        self.assertShows("(month-number->yyyymm 24251)", "202012")
        self.assertShows("(yyyymm->month-number (vector 202001 nan))", "#(24240.0 nan)")
        self.assertLispError("(yyyymm->month-number 202000)", "YYYYMM")
        self.assertLispError("(date->month-number 5)", "not a date")

    def test_month_arithmetic(self):
        self.assertShows("(date-add-months (date 2020 1 31) 1)", "2020-02-29")
        self.assertShows("(date-add-months (date 2020 1 15) -13)", "2018-12-15")
        self.assertShows("(date-add-months (vector (date 2020 1 1)) 2)", "#(2020-03-01)")
        self.assertShows("(months-between (date 2020 12 31) (date 2021 1 1))", "1")
        self.assertShows("(months-between (vector (date 2020 1 1)) (date 2020 6 1))", "#(5)")
        self.assertShows("(month-range 24240 24242)", "#(24240 24241 24242)")

    def test_series(self):
        self.run_lisp("""
          (define s (cons (vector (date 2023 1 5) (date 2023 1 20) (date 2023 3 1) (date 2023 3 9))
                          (vector 6.0 7.0 nan 5.0)))""")
        self.assertShows("(series-monthly s)", "(#(2023-01-01 2023-03-01) . #(6.5 5.0))")
        self.assertShows("(series-monthly s 'first)", "(#(2023-01-01 2023-03-01) . #(6.0 5.0))")
        self.assertShows("(series-monthly s 'sum)", "(#(2023-01-01 2023-03-01) . #(13.0 5.0))")
        self.assertLispError("(series-monthly s 'median)", "how must be")
        self.assertShows("(series-values-at s (month-range (date 2022 12 1) (date 2023 4 1)))",
                         "#(nan 6.5 nan 5.0 nan)")
        self.assertShows("(series-values-at s (month-range (date 2022 12 1) (date 2023 4 1)) #t)",
                         "#(nan 6.5 6.5 5.0 5.0)")
        self.assertShows("(series-values-at s (vector (date 2023 1 1)))", "#(6.5)")

    def test_series_table(self):
        self.run_lisp("""
          (define a (cons (vector (date 2023 1 1) (date 2023 3 1)) #(1 3)))
          (define b (cons (vector (date 2023 2 15)) #(20)))
          (define t (series-table (list (cons "a" a) (cons "b" b))))""")
        self.assertShows("(table-column-names t)", '("month" "date" "a" "b")')
        self.assertShows('(table-column t "month")', "#(24276 24277 24278)")
        self.assertShows('(table-column t "a")', "#(1.0 nan 3.0)")
        self.assertShows('(table-column t "b")', "#(nan 20.0 nan)")
        self.assertShows('(table-column (series-table (list (cons "b" b) (cons "a" a)) #t) "b")',
                         "#(nan 20.0 20.0)")
        self.assertLispError("(series-table (list (cons \"a\" 5)))", "a pair of vectors")


class TestCsvFiles(LispTestCase):
    """lisp_csv.py: load-csv reads a table, write-columns-csv writes one."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_columns_become_numbers_dates_or_strings(self):
        path = self.write("a.csv", "id,when,us_date,amount,count\n"
                                   "x,2024-01-31,01/31/2024,1.5,3\n"
                                   "y,,02/29/2024,,4\n")
        self.run_lisp('(define t (load-csv "%s"))' % path)
        self.assertShows('(table-column t "id")', '#("x" "y")')
        self.assertShows('(table-column t "when")', "#(2024-01-31 ())")
        self.assertShows('(table-column t "us_date")', "#(2024-01-31 2024-02-29)")
        self.assertShows('(table-column t "amount")', "#(1.5 nan)")
        self.assertShows('(table-column t "count")', "#(3 4)")

    def test_no_header_and_short_rows(self):
        path = self.write("b.csv", "1,2\n3\n")
        self.assertShows('(load-csv "%s" #f)' % path, '(("Column1" . #(1 3)) ("Column2" . #(2.0 nan)))')
        self.assertLispError('(load-csv "%s")' % self.write("c.csv", "a\n1,2\n"), "only 1 columns")

    def test_write_then_read_back(self):
        path = os.path.join(self.dir, "out.csv")
        self.run_lisp('''(write-columns-csv "%s" (make-table "id" (vector "a" "b")
                                                  "x" (vector 1.5 nan)
                                                  "d" (vector (date 2024 1 1) (date 2024 2 1))))''' % path)
        with open(path) as f:
            self.assertEqual(f.read().splitlines(), ["id,x,d", "a,1.5,2024-01-01", "b,,2024-02-01"])
        self.assertShows('(load-csv "%s")' % path,
                         '(("id" . #("a" "b")) ("x" . #(1.5 nan)) ("d" . #(2024-01-01 2024-02-01)))')


class TestHttp(LispTestCase):
    """lisp_http.py, against a small web server on this machine -- the test
    suite never touches the internet."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            hits = []

            def do_GET(self):
                Handler.hits.append(self.path)
                if self.path.startswith("/data.json"):
                    body, kind = b'{"rates": [{"date": "2024-01-02", "rate": 5.3}], "ok": true, "none": null}', "json"
                elif self.path.startswith("/data.csv"):
                    body, kind = b"date,rate\n01/02/2024,5.3\n01/03/2024,5.31\n", "csv"
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"no such thing")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/" + kind)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.handler = Handler
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        super().setUp()
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        patcher = mock.patch.dict(os.environ, {"LISP_HTTP_CACHE": cache})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.handler.hits.clear()

    def test_json_becomes_hash_tables_and_lists(self):
        self.run_lisp('(define r (http-get-json "%s/data.json"))' % self.base)
        self.assertShows('(hash-table-ref r "ok")', "#t")
        self.assertShows('(hash-table-ref r "none")', "()")
        self.assertShows('(hash-table-ref (car (hash-table-ref r "rates")) "rate")', "5.3")

    def test_csv_becomes_a_table(self):
        self.assertShows('(table-column (http-get-csv "%s/data.csv") "date")' % self.base,
                         "#(2024-01-02 2024-01-03)")

    def test_text_and_errors(self):
        self.assertIn("rates", self.show('(http-get-text "%s/data.json")' % self.base))
        self.assertLispError('(http-get-text "%s/missing")' % self.base, "HTTP 404")

    def test_cache_is_used_only_when_asked_for(self):
        url = "%s/data.json" % self.base
        self.run_lisp('(http-get-text "%s") (http-get-text "%s")' % (url, url))
        self.assertEqual(len(self.handler.hits), 2)             # no cache-hours: downloads each time
        self.run_lisp('(http-get-text "%s" 1) (http-get-text "%s" 1)' % (url, url))
        self.assertEqual(len(self.handler.hits), 3)             # the second call read the cache
        self.assertShows("(http-clear-cache)", "1")
        self.run_lisp('(http-get-text "%s" 1)' % url)
        self.assertEqual(len(self.handler.hits), 4)

    def test_url_building(self):
        self.assertShows('(http-url "https://x.org/a" (list (cons "q" "a b&c") (cons "n" 5)))',
                         '"https://x.org/a?q=a+b%26c&n=5"')
        self.assertShows('(http-url "https://x.org/a?k=1" (list (cons "n" 5)))', '"https://x.org/a?k=1&n=5"')


# ---------------------------------------------------------------------------
# 13. Dates
# ---------------------------------------------------------------------------

class TestDates(LispTestCase):

    def test_construction_and_printing(self):
        self.assertShows("(date 2024 3 15)", "2024-03-15")

    def test_accessors(self):
        self.assertShows("(date-year (date 2024 3 15))", "2024")
        self.assertShows("(date-month (date 2024 3 15))", "3")
        self.assertShows("(date-day (date 2024 3 15))", "15")

    def test_string_conversion_both_ways(self):
        self.assertShows("(date->string (date 2024 3 15))", '"2024-03-15"')
        self.assertShows('(string->date "2024-03-15")', "2024-03-15")

    def test_add_days_including_across_month_and_year_and_negative(self):
        self.assertShows("(date-add-days (date 2024 3 15) 10)", "2024-03-25")
        self.assertShows("(date-add-days (date 2024 12 31) 1)", "2025-01-01")
        self.assertShows("(date-add-days (date 2024 3 1) -1)", "2024-02-29")     # 2024 is a leap year

    def test_invalid_dates_are_lisp_errors(self):
        self.assertLispError("(date 2024 13 1)", "invalid date")
        self.assertLispError("(date 2023 2 29)", "invalid date")
        self.assertLispError('(string->date "not-a-date")', "invalid date string")

    def test_dates_compare_and_are_equal_by_value(self):
        self.assertShows("(< (date 2024 1 1) (date 2024 2 1))", "#t")
        self.assertShows("(equal? (date 2024 1 1) (date 2024 1 1))", "#t")
        self.assertShows("(equal? (date 2024 1 1) (date 2024 1 2))", "#f")


# ---------------------------------------------------------------------------
# 14. Regression models
# ---------------------------------------------------------------------------

class TestRegression(LispTestCase):

    def test_linear_fit_recovers_an_exact_line(self):
        self.run_lisp("(define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 11)))")   # y = 2x + 1
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        self.assertAlmostEqual(self.run_lisp("(model-predict m 10)"), 21.0)
        self.assertShows("(model-kind m)", '"linear"')
        self.assertShows("(model? m)", "#t")

    def test_multiple_predictors(self):
        # y = 1 + 2*a + 3*b
        self.run_lisp("""
          (define a (vector 1 2 3 4 5 6))
          (define b (vector 2 1 4 3 6 5))
          (define y (vector-map (lambda (i) i) (vector 0 0 0 0 0 0)))
          (define ys (vectors-map (lambda (x1 x2 i) (+ 1 (* 2 x1) (* 3 x2))) (list a b)))
          (define m (linear-regression (list a b) ys))""")
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0, places=3)
        c = self.run_lisp("(model-coefficients m)")
        self.assertAlmostEqual(float(c.items[0]), 2.0, places=3)
        self.assertAlmostEqual(float(c.items[1]), 3.0, places=3)
        self.assertAlmostEqual(self.run_lisp("(model-predict m (list 10 10))"), 51.0, places=2)

    def test_weights_of_zero_exclude_an_observation(self):
        # the outlier at x=5 is weighted out, so the line through the rest is exact
        self.run_lisp("""
          (define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 500) #(1 1 1 1 0)))""")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)

    def test_mismatched_lengths_are_an_error(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(linear-regression #(1 2 3) #(1 2))")

    def test_constant_predictor_is_an_error(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(linear-regression #(2 2 2 2) #(1 2 3 4))")

    def test_logistic_fit_is_monotonic_and_bounded(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8) #(0 0 0 1 0 1 1 1)))")
        self.assertShows("(model-kind m)", '"logistic"')
        lo = self.run_lisp("(model-predict m 1)")
        hi = self.run_lisp("(model-predict m 8)")
        self.assertTrue(0.0 < lo < hi < 1.0)

    def test_logistic_rejects_y_outside_zero_one(self):
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(logistic-regression #(1 2 3 4) #(0 1 2 1))")

    def test_spline_fit_bends_where_a_line_cannot(self):
        # y = |x - 5| : a straight line fits this badly, a spline should not
        self.run_lisp("""
          (define xs (vector-iterate 0 11 (lambda (x) (+ x 1))))
          (define ys (vector-map (lambda (x) (abs (- x 5))) xs))
          (define line (linear-regression xs ys))
          (define spl (spline-regression xs ys (list 5)))""")
        line_err = abs(self.run_lisp("(model-predict line 0)") - 5)
        spline_err = abs(self.run_lisp("(model-predict spl 0)") - 5)
        self.assertLess(spline_err, line_err)
        self.assertLess(spline_err, 1e-3)
        self.assertShows("(model-kind spl)", '"spline"')

    def test_spline_models_refuse_flat_coefficient_accessors(self):
        self.run_lisp("(define spl (spline-regression (vector-iterate 0 11 (lambda (x) (+ x 1))) "
                      "(vector-map (lambda (x) (abs (- x 5))) (vector-iterate 0 11 (lambda (x) (+ x 1)))) (list 5)))")
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp("(model-slope spl)")

    def test_model_report_and_evaluate_run(self):
        self.run_lisp("(define m (linear-regression #(1 2 3 4 5) #(3 5 7 9 11)))")
        self.assertIn("linear", self.show("(model-report m)").lower())
        self.run_lisp("(model-evaluate m #(6 7) #(13 15))")

    def test_standard_errors_and_p_values(self):
        # Checked against statsmodels: OLS of (10 20 29 41 51) on (1 2 3 4 5).
        self.run_lisp("(define m (linear-regression (vector 1 2 3 4 5) (vector 10 20 29 41 51)))")
        self.run_lisp("(define ct (model-coefficient-table m))")
        self.assertShows('(table-column ct "term")', '#("intercept" "x1")')
        std_errors = self.run_lisp('(table-column ct "std_error")').items.tolist()
        p_values = self.run_lisp('(table-column ct "p_value")').items.tolist()
        self.assertAlmostEqual(std_errors[0], 0.834666, places=5)
        self.assertAlmostEqual(std_errors[1], 0.251661, places=5)
        self.assertAlmostEqual(p_values[1] / 3.209778e-05, 1.0, places=5)     # statsmodels' value
        report = self.show("(model-report m)")
        self.assertIn("std error", report)
        self.assertIn("t value", report)

    def test_logistic_report_has_z_values_and_auc(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8) #(0 0 1 0 0 1 1 1)))")
        self.assertIn("z value", self.show("(model-report m)"))
        self.assertIn("AUC", self.show("(model-report m)"))
        self.assertShows('(table-column-names (model-coefficient-table m))',
                         '("term" "coefficient" "std_error" "z_value" "p_value")')
        self.assertIn("AUC              = 0.875", self.show("(model-evaluate m #(1 2 3 4 5 6 7 8) #(0 0 1 0 0 1 1 1))"))

    def test_lift_table(self):
        self.run_lisp("(define m (logistic-regression #(1 2 3 4 5 6 7 8 9 10) #(0 0 1 0 0 1 0 1 1 1)))")
        self.run_lisp("(define lt (model-lift-table m #(1 2 3 4 5 6 7 8 9 10) #(0 0 1 0 0 1 0 1 1 1) 5))")
        self.assertShows('(table-column lt "rows")', "#(2 2 2 2 2)")
        self.assertShows('(table-column lt "mean_actual")', "#(1.0 0.5 0.5 0.5 0.0)")
        self.assertShows('(table-column lt "cumulative_share")', "#(0.4 0.6 0.8 1.0 1.0)")
        self.assertLispError("(model-lift-table m #(1 2) #(0 1) 5)", "bins must be")

    def test_spline_report_has_the_coefficient_table(self):
        self.run_lisp("(define spl (spline-regression (list (cons \"x\" (vector-range 11))) "
                      "(vector-map (lambda (x) (abs (- x 5))) (vector-range 11)) (list 5)))")
        self.assertIn("x (knot 5)", self.show("(model-report spl)"))
        self.assertShows('(table-column (model-coefficient-table spl) "term")', '#("intercept" "x" "x (knot 5)")')

    def test_train_test_split_helpers(self):
        self.assertShows("(vector-take #(1 2 3 4 5) 3)", "#(1 2 3)")
        self.assertShows("(vector-drop #(1 2 3 4 5) 3)", "#(4 5)")


class TestLinearProgramming(LispTestCase):
    """lp-read-file and lp-solve (lisp_simplex.py, using simplex/simplex_solver.py)."""

    EXAMPLE_FILE = os.path.join(HERE, "..", "simplex", "example_problem.txt")

    def write_problem_file(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "problem.txt")
        with open(path, "w") as f:
            f.write(text)
        return path.replace("\\", "/")

    def test_read_the_example_file(self):
        self.run_lisp('(define problem (lp-read-file "%s"))' % self.EXAMPLE_FILE.replace("\\", "/"))
        self.assertShows("problem",
                         '(("objective" -3.0 -5.0) ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0)) '
                         '("relations" "<=" "<=" "<=") ("rhs" 4.0 12.0 18.0))')

    def test_solve_the_example_file(self):
        self.run_lisp('(define result (lp-solve (lp-read-file "%s")))' % self.EXAMPLE_FILE.replace("\\", "/"))
        self.assertShows('(cdr (assoc "solution" result))', "(2.0 6.0)")
        self.assertShows('(cdr (assoc "optimal-value" result))', "-36.0")

    def test_read_skips_comments_and_blank_lines_and_handles_every_relation(self):
        path = self.write_problem_file("# a comment\n\nminimize\n2 3\n\nsubject to\n1 1 = 10\n"
                                       "1 0 <= 6\n0 1 >= 1\n")
        self.assertShows('(cdr (assoc "relations" (lp-read-file "%s")))' % path, '("=" "<=" ">=")')
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 6.0 4.0) ("optimal-value" . 24.0))')

    def test_read_errors_say_what_is_wrong(self):
        self.assertLispError('(lp-read-file "/definitely/not/here.txt")', "No such file")
        path = self.write_problem_file("maximize\n1 2\nsubject to\n1 1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "must start with a 'minimize' line")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "expected 2")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 1 < 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "Unrecognized relation")

    def test_solve_a_problem_built_in_lisp(self):
        self.assertShows("""(lp-solve (list (cons "objective" (list 1 1))
                                            (cons "constraints" (list (list 1 2) (list 3 1)))
                                            (cons "relations" (list ">=" ">="))
                                            (cons "rhs" (list 4 6))))""",
                         '(("solution" 1.6 1.2) ("optimal-value" . 2.8))')

    def test_relations_can_be_symbols_in_a_quoted_problem(self):
        self.assertShows("""(lp-solve '(("objective" 2 3) ("constraints" (1 1) (1 0))
                                        ("relations" = <=) ("rhs" 10 6)))""",
                         '(("solution" 6.0 4.0) ("optimal-value" . 24.0))')

    def test_infeasible_and_unbounded_problems_are_errors(self):
        self.assertLispError("""(lp-solve '(("objective" 1) ("constraints" (1) (1))
                                            ("relations" <= >=) ("rhs" 1 2)))""", "infeasible")
        self.assertLispError("""(lp-solve '(("objective" -1) ("constraints" (1))
                                            ("relations" >=) ("rhs" 1)))""", "unbounded")

    def test_malformed_problems_are_errors(self):
        cases = [
            ("""'(("objective" 1 1) ("constraints" (1 2)) ("relations" <=))""", 'no "rhs" list'),
            ("""'(("objective" 1 1) ("constraints" (1)) ("relations" <=) ("rhs" 4))""",
             "a constraint has 1 coefficients, but the objective has 2"),
            ("""'(("objective" 1 1) ("constraints" (1 1) (1 0)) ("relations" <=) ("rhs" 4))""",
             "2 constraints, 1 relations, and 1 rhs values"),
            ("""'(("objective" 1 1) ("constraints" (1 1)) ("relations" <) ("rhs" 4))""",
             'a relation must be "<=", ">=", or "="'),
            ("""'(("objective" 1 "a") ("constraints" (1 1)) ("relations" <=) ("rhs" 4))""",
             '"objective" must hold only numbers, but it has "a"'),
            ("""'(("objective" 1 1) ("constraints" 5) ("relations" <=) ("rhs" 4))""",
             '"constraints" must be a list, not 5'),
            ("""'(("objective") ("constraints" (1)) ("relations" <=) ("rhs" 4))""", '"objective" is empty'),
        ]
        for problem, message in cases:
            with self.subTest(problem=problem):
                self.assertLispError("(lp-solve %s)" % problem, message)

    def test_costs_and_balances_in_the_millions(self):
        # Costs above a million once looked infeasible (the Big-M method with M = 1e6).
        self.assertShows("""(lp-solve '(("objective" 5000000) ("constraints" (1)) ("relations" >=) ("rhs" 1)))""",
                         '(("solution" 1.0) ("optimal-value" . 5000000.0))')
        # Rates on balances in the hundreds of millions.
        self.assertShows("""(lp-solve '(("objective" 0.065 0.07) ("constraints" (1 1) (1 0))
                                        ("relations" >= <=) ("rhs" 250000000 100000000)))""",
                         '(("solution" 100000000.0 150000000.0) ("optimal-value" . 17000000.0))')
        # Costs in the hundreds of millions, where rounding once made a solvable problem look unbounded.
        self.assertShows("""(round (cdr (assoc "optimal-value"
                                (lp-solve '(("objective" 300000000 -100000000 700000000 -400000000)
                                            ("constraints" (-3 3 -1 2) (0 -2 4 2) (-2 6 6 2) (-2 0 6 2))
                                            ("relations" <= <= >= <=)
                                            ("rhs" 1 18 20 4))))))""",
                         "-1900000000")

    def test_small_fractional_costs(self):
        self.assertShows("""(lp-solve '(("objective" 0.001 0.002) ("constraints" (1 1) (1 0))
                                        ("relations" >= >=) ("rhs" 3 0.5)))""",
                         '(("solution" 3.0 0.0) ("optimal-value" . 0.003))')

    def test_an_infeasible_problem_is_not_called_unbounded(self):
        # 0 * x1 = 20 can't hold; the old solver reported "unbounded".
        self.assertLispError("""(lp-solve '(("objective" -1) ("constraints" (2) (0))
                                            ("relations" >= =) ("rhs" 1 20)))""", "infeasible")

    def test_solving_does_not_change_the_problem(self):
        self.run_lisp("""(define problem (list (cons "objective" (list 1 1))
                                                (cons "constraints" (list (list 1 1)))
                                                (cons "relations" (list ">="))
                                                (cons "rhs" (list -4))))""")
        self.run_lisp("(lp-solve problem)")      # a negative rhs makes the solver flip the row
        self.assertShows("problem", '(("objective" 1 1) ("constraints" (1 1)) ("relations" ">=") ("rhs" -4))')


# ---------------------------------------------------------------------------
# 15. SQLite
# ---------------------------------------------------------------------------

class TestSqlite(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define conn (sqlite-open ":memory:"))
          (sqlite-execute conn "CREATE TABLE t (id INTEGER, name TEXT, amount REAL)")
          (sqlite-execute conn "INSERT INTO t VALUES (1, 'ann', 10.5)")
          (sqlite-execute conn "INSERT INTO t VALUES (2, 'bob', 20.0)")
          (sqlite-execute conn "INSERT INTO t VALUES (3, 'cy', 30.25)")""")

    def tearDown(self):
        self.run_lisp("(sqlite-close conn)")

    def test_query_returns_column_wise_name_vector_pairs(self):
        self.assertShows('(sqlite-query conn "SELECT id, name FROM t ORDER BY id")',
                         '(("id" . #(1 2 3)) ("name" . #("ann" "bob" "cy")))')

    def test_query_with_bound_parameters(self):
        self.assertShows("(sqlite-query conn \"SELECT name FROM t WHERE id = ?\" '() '() (list 2))",
                         '(("name" . #("bob")))')

    def test_execute_with_bound_parameters_then_read_back(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (?, ?, ?)" (list 4 "dee" 1.5))')
        self.assertShows("(vector-sum (cdr (car (sqlite-query conn \"SELECT id FROM t\"))))", "10")

    def test_fetch_row_steps_through_a_result_then_returns_empty(self):
        self.run_lisp('(define cur (sqlite-execute conn "SELECT id FROM t ORDER BY id"))')
        self.assertShows("(list (sqlite-fetch-row cur) (sqlite-fetch-row cur) (sqlite-fetch-row cur) (sqlite-fetch-row cur))",
                         "((1) (2) (3) ())")

    def test_null_in_a_text_column_is_the_empty_list(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (9, NULL, 1.0)")')
        self.assertShows('(vector-ref (cdr (car (sqlite-query conn "SELECT name FROM t WHERE id = 9"))) 0)', "()")

    def test_dtype_hints_force_vector_types(self):
        cols = self.run_lisp('(sqlite-query conn "SELECT id, amount FROM t ORDER BY id" "IF" 10)')
        self.assertEqual(cols.car.cdr.items.dtype, lisp_core.LispVector.INT_DTYPE)
        self.assertEqual(cols.cdr.car.cdr.items.dtype, lisp_core.LispVector.FLOAT_DTYPE)

    def test_max_rows_bound_is_enforced(self):
        self.assertLispError('(sqlite-query conn "SELECT id FROM t" "I" 2)')

    def test_predicates(self):
        self.assertShows("(sqlite-connection? conn)", "#t")
        self.assertShows("(sqlite-connection? 5)", "#f")
        self.assertShows('(sqlite-cursor? (sqlite-execute conn "SELECT 1"))', "#t")

    def test_sql_errors_are_lisp_errors(self):
        self.assertLispError('(sqlite-query conn "SELECT nope FROM missing")', "sqlite")

    def test_a_non_connection_is_rejected(self):
        self.assertLispError('(sqlite-query 5 "SELECT 1")', "sqlite connection")

    def test_a_hostile_value_is_data_not_sql_when_bound(self):
        self.run_lisp("""(sqlite-execute conn "INSERT INTO t VALUES (?, ?, ?)"
                          (list 7 "x'); DROP TABLE t; --" 0.0))""")
        # the table still exists, and the hostile text was stored verbatim
        self.assertShows("(vector-length (cdr (car (sqlite-query conn \"SELECT id FROM t\"))))", "4")
        self.assertShows("(vector-ref (cdr (car (sqlite-query conn \"SELECT name FROM t WHERE id = 7\"))) 0)",
                         '"x\'); DROP TABLE t; --"')

    def test_null_in_a_numeric_column_is_nan(self):
        self.run_lisp('(sqlite-execute conn "INSERT INTO t VALUES (9, NULL, NULL)")')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT amount FROM t ORDER BY id")))',
                         "#(10.5 20.0 30.25 nan)")

    def test_write_table_round_trip(self):
        self.run_lisp("""
          (define tbl (make-table "id" (vector "a" "b") "x" (vector 1.5 nan)
                                  "d" (vector (date 2024 1 1) (date 2024 2 1)) "odd \\"name\\"" #(1 2)))""")
        self.assertShows('(sqlite-write-table conn "w" tbl)', "2")
        self.assertShows('(sqlite-query conn "SELECT id, x, d FROM w")',
                         '(("id" . #("a" "b")) ("x" . #(1.5 nan)) ("d" . #(2024-01-01 2024-02-01)))')
        names = self.run_lisp('(table-column-names (sqlite-query conn "SELECT * FROM w"))')
        self.assertEqual(lisp_core.pairs_to_list(names)[-1], 'odd "name"')     # quoted safely

    def test_write_table_modes(self):
        self.run_lisp('(define tbl (make-table "n" #(1 2)))')
        self.run_lisp('(sqlite-write-table conn "w" tbl)')
        self.assertLispError('(sqlite-write-table conn "w" tbl)', "already exists")
        self.run_lisp('(sqlite-write-table conn "w" tbl (quote append))')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT count(*) AS n FROM w")))', "#(4)")
        self.run_lisp('(sqlite-write-table conn "w" (make-table "n" #(9)) (quote replace))')
        self.assertShows('(cdr (car (sqlite-query conn "SELECT n FROM w")))', "#(9)")

    def test_a_failed_write_changes_nothing(self):
        self.run_lisp('(sqlite-write-table conn "w" (make-table "n" #(1)))')
        self.assertLispError('(sqlite-write-table conn "w" (make-table "other" #(5)) (quote append))',
                             "no column named other")
        self.assertShows('(cdr (car (sqlite-query conn "SELECT count(*) AS n FROM w")))', "#(1)")


# ---------------------------------------------------------------------------
# 16. Metaprogramming, output, loading files
# ---------------------------------------------------------------------------

class TestMetaprogrammingAndIO(LispTestCase):

    def test_eval_runs_constructed_code_in_the_global_environment(self):
        self.assertShows("(eval (list '+ 1 2 (list '* 3 4)))", "15")

    def test_eval_cannot_see_local_variables(self):
        self.assertLispError("(let ((local 5)) (eval 'local))", "unbound symbol")

    def test_eval_of_define_creates_a_global(self):
        self.run_lisp("(eval (list 'define 'made-by-eval 42))")
        self.assertShows("made-by-eval", "42")

    def test_defined_functions_and_bound_variables(self):
        self.run_lisp("(define (square x) (* x x)) (define answer 42)")
        self.assertIn("square", self.show("(defined-functions)"))
        self.assertIn("answer", self.show("(bound-variables)"))

    def test_load_evaluates_a_file_into_the_current_environment(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lib.lsp")
            with open(path, "w") as f:
                f.write('(define loaded-value 42)\n(define (loaded-fn x) (* x 2))\n')
            self.run_lisp('(load "%s")' % path)
        self.assertShows("(loaded-fn loaded-value)", "84")

    def test_load_of_a_missing_file_is_an_error(self):
        with self.assertRaises(Exception):
            self.run_lisp('(load "/definitely/not/here.lsp")')

    def test_redirect_output_sends_display_to_a_file_until_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.txt")
            self.run_lisp('(display "before ") (redirect-output "%s") (display "to-file") (newline) '
                          '(reset-output) (display "after")' % path)
            with open(path) as f:
                self.assertEqual(f.read(), "to-file\n")
        self.assertEqual(self.printed(), "before after")

    def test_redirect_output_can_append(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.txt")
            self.run_lisp('(redirect-output "%s") (display "one") (reset-output)' % path)
            self.run_lisp('(redirect-output "%s" #t) (display "two") (reset-output)' % path)
            with open(path) as f:
                self.assertEqual(f.read(), "onetwo")

    def test_pretty_print_of_a_value_goes_to_output(self):
        self.run_lisp("(pretty-print '(a (b c)))")
        self.assertIn("a", self.printed())
        self.assertIn("c", self.printed())

    def test_pretty_print_function_shows_a_user_functions_source(self):
        self.run_lisp("(define (square x) (* x x)) (pretty-print-function square)")
        self.assertIn("square", self.printed())
        self.assertIn("*", self.printed())

    def test_pretty_print_function_rejects_a_builtin(self):
        self.assertLispError("(pretty-print-function car)", "not a user-defined function")


class TestStandardMacros(LispTestCase):
    """macros_init.lsp: while and do."""

    def setUp(self):
        super().setUp()
        lisp_core.run_file(lisp_builtins.MACROS_INIT_FILE, self.env)

    def test_while_runs_several_body_forms_until_the_test_is_false(self):
        self.run_lisp('(define i 0) (define out "")')
        self.assertShows('(while (< i 3) (set! out (string-append out (number->string i))) (set! i (+ i 1)))',
                         "()")
        self.assertShows("out", '"012"')

    def test_while_whose_test_starts_false_never_runs_its_body(self):
        self.assertShows("(define ran #f) (while #f (set! ran #t)) ran", "#f")

    def test_nested_whiles(self):
        self.assertShows("""(define r 0) (define total 0)
                            (while (< r 3)
                              (define c 0)
                              (while (< c 3) (set! total (+ total 1)) (set! c (+ c 1)))
                              (set! r (+ r 1)))
                            total""", "9")

    def test_while_loop_name_does_not_capture_the_callers_names(self):
        self.run_lisp("(define %loop 'mine) (define i 0) (define seen '())")
        self.run_lisp("(while (< i 2) (set! seen (cons %loop seen)) (set! i (+ i 1)))")
        self.assertShows("seen", "(mine mine)")

    def test_a_long_while_loop_does_not_grow_the_stack(self):
        self.assertShows("(define n 0) (while (< n 100000) (set! n (+ n 1))) n", "100000")

    def test_do_steps_its_variables_and_returns_the_result(self):
        self.assertShows("(do ((i 0 (+ i 1)) (total 0 (+ total i))) ((= i 5) total))", "10")

    def test_do_runs_its_body_and_every_result_form(self):
        self.assertShows("""(define n 0)
                            (do ((i 0 (+ i 1))) ((= i 4) (set! n (* n 10)) n) (set! n (+ n 1)))""", "40")

    def test_do_with_no_result_forms_returns_nil(self):
        self.assertShows("(do ((i 0 (+ i 1))) ((= i 3)))", "()")

    def test_do_variable_without_a_step_keeps_its_value(self):
        self.assertShows("(do ((i 0 (+ i 1)) (fixed 7)) ((= i 3) fixed))", "7")

    def test_do_steps_all_use_the_old_values(self):
        self.assertShows("(do ((a 1 b) (b 2 a) (k 0 (+ k 1))) ((= k 1) (list a b)))", "(2 1)")

    def test_do_with_no_variables(self):
        self.assertShows("(define x 0) (do () ((> x 2) x) (set! x (+ x 1)))", "3")

    def test_nested_do_loops(self):
        self.assertShows("""(define pairs '())
                            (do ((i 0 (+ i 1))) ((= i 2))
                              (do ((j 0 (+ j 1))) ((= j 2))
                                (set! pairs (cons (list i j) pairs))))
                            (reverse pairs)""", "((0 0) (0 1) (1 0) (1 1))")

    def test_a_long_do_loop_does_not_grow_the_stack(self):
        self.assertShows("(do ((i 0 (+ i 1))) ((= i 100000) i))", "100000")

    def test_do_rejects_a_malformed_variable_or_end_clause(self):
        self.assertLispError("(do ((i)) ((= i 3)))", "(var init) or (var init step)")
        self.assertLispError("(do ((i 0 1 2)) ((= i 3)))", "(var init) or (var init step)")
        self.assertLispError("(do ((i 0 (+ i 1))) done)", "(end-test result...)")

    def test_when_runs_its_body_only_when_the_test_is_true(self):
        self.run_lisp("(define log '())")
        self.assertShows("(when (> 2 1) (set! log (cons 'a log)) (set! log (cons 'b log)) 'done)", "done")
        self.assertShows("log", "(b a)")
        self.assertShows("(when #f (error \"never\"))", "()")
        self.assertShows("(when 0 'yes)", "yes")          # only #f is false

    def test_unless_runs_its_body_only_when_the_test_is_false(self):
        self.assertShows("(unless #f 1 2 3)", "3")
        self.assertShows("(unless (> 2 1) (error \"never\"))", "()")

    def test_case_picks_the_clause_whose_keys_match(self):
        self.run_lisp("""
          (define (region state)
            (case state
              (("CA" "OR" "WA") 'west)
              (("NY" "NJ" "CT") 'northeast)
              (else 'other)))""")
        self.assertShows('(list (region "OR") (region "NJ") (region "TX"))', "(west northeast other)")

    def test_case_with_symbol_and_number_keys_and_single_keys(self):
        self.assertShows("(case 'quarterly ((annual yearly) 12) (quarterly 3) (monthly 1))", "3")
        self.assertShows("(case 3 ((1 2) 'low) ((3 4) 'mid))", "mid")

    def test_case_otherwise_is_the_same_as_else(self):
        self.assertShows("(case 9 ((1 2) 'low) (otherwise 'high))", "high")

    def test_case_with_no_match_and_no_else_returns_nil(self):
        self.assertShows("(case 'weekly (monthly 1))", "()")

    def test_case_evaluates_its_key_once_and_runs_every_body_form(self):
        self.run_lisp("(define n 0) (define log '())")
        self.assertShows("(case (begin (set! n (+ n 1)) 5) ((1) 'one) ((5) (set! log (cons 'five log)) 'b))", "b")
        self.assertShows("(list n log)", "(1 (five))")

    def test_case_rejects_a_misplaced_else_or_a_malformed_clause(self):
        self.assertLispError("(case 1 (else 'x) ((1) 'one))", "the else clause must be the last one")
        self.assertLispError("(case 1 5)", "each clause must be")

    def test_assert_does_nothing_when_the_test_is_true(self):
        self.assertShows("(assert (= 1 1))", "()")

    def test_assert_names_the_failed_test(self):
        self.run_lisp("(define balance -5)")
        self.assertLispError("(assert (>= balance 0))", "assert: (>= balance 0) is false")

    def test_assert_adds_the_message(self):
        self.run_lisp("(define balance -5)")
        self.assertLispError('(assert (>= balance 0) "balance went negative:" balance)',
                             "assert: (>= balance 0) is false: balance went negative: -5")

    def test_assert_evaluates_the_message_only_when_the_test_fails(self):
        self.run_lisp('(define evaluated #f) (assert #t (begin (set! evaluated #t) "msg"))')
        self.assertShows("evaluated", "#f")

    def test_with_sqlite_returns_the_body_value_and_closes_the_connection(self):
        self.run_lisp("""
          (define saved '())
          (define result
            (with-sqlite (conn ":memory:")
              (set! saved conn)
              (sqlite-execute conn "CREATE TABLE t (x)")
              (sqlite-execute conn "INSERT INTO t VALUES (7)")
              (sqlite-query conn "SELECT x FROM t")))""")
        self.assertShows("result", '(("x" . #(7)))')
        self.assertLispError('(sqlite-query saved "SELECT 1")', "closed database")

    def test_with_sqlite_closes_the_connection_after_an_error(self):
        self.run_lisp("(define saved '())")
        self.assertLispError("(with-sqlite (conn \":memory:\") (set! saved conn) (car 5))", "car: not a pair")
        self.assertLispError('(sqlite-query saved "SELECT 1")', "closed database")

    def test_with_sqlite_closes_the_connection_after_a_throw(self):
        self.run_lisp("(define saved '())")
        self.assertShows("(catch 'out (with-sqlite (conn \":memory:\") (set! saved conn) (throw 'out 'left)))",
                         "left")
        self.assertLispError('(sqlite-query saved "SELECT 1")', "closed database")

    def test_with_sqlite_changes_are_saved_in_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db").replace("\\", "/")
            self.run_lisp("""
              (with-sqlite (conn "%s")
                (sqlite-write-table conn "pools" (make-table "upb" #(100 200))))""" % path)
            self.assertShows("""(with-sqlite (conn "%s")
                                  (cdr (car (sqlite-query conn "SELECT sum(upb) AS total FROM pools"))))""" % path,
                             "#(300)")

    def test_with_sqlite_rejects_a_malformed_spec(self):
        self.assertLispError("(with-sqlite conn 1)", "expected (with-sqlite (var path) body...)")


class TestInitFileAndRunFile(LispTestCase):

    def test_load_init_file_defines_things(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "init.lsp")
            with open(path, "w") as f:
                f.write("(define from-init 123)\n(defmacro twice (x) `(* 2 ,x))\n")
            lisp_builtins.load_init_file(self.env, path)
        self.assertShows("(twice from-init)", "246")

    def test_a_missing_init_file_is_silently_skipped(self):
        lisp_builtins.load_init_file(self.env, "/definitely/not/here/init.lsp")     # must not raise

    def test_a_broken_init_file_warns_but_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "init.lsp")
            with open(path, "w") as f:
                f.write("(define ok 1)\n(error \"broken init\")\n(define never 2)\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lisp_builtins.load_init_file(self.env, path)
        self.assertIn("broken init", err.getvalue())
        self.assertShows("ok", "1")                                    # ran up to the error
        self.assertLispError("never", "unbound symbol")               # ...and stopped there

    def test_the_shipped_startup_files_load_cleanly_and_define_while_and_do(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            lisp_builtins.load_init_file(self.env, lisp_builtins.DEFAULT_INIT_FILE)
        self.assertEqual(err.getvalue(), "")
        self.assertShows("(define i 0) (while (< i 5) (set! i (+ i 1))) i", "5")
        self.assertShows("(do ((i 0 (+ i 1))) ((= i 5) i))", "5")

    def test_the_standard_macros_load_even_without_an_init_file(self):
        lisp_builtins.load_init_file(self.env, "/definitely/not/here/init.lsp")
        self.assertShows("(define i 0) (while (< i 5) (set! i (+ i 1))) i", "5")

    def test_the_standard_macros_load_before_the_init_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "init.lsp")
            with open(path, "w") as f:
                f.write("(define n 0)\n(while (< n 3) (set! n (+ n 1)))\n")
            lisp_builtins.load_init_file(self.env, path)
        self.assertShows("n", "3")

    def test_run_file_evaluates_every_form(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.lsp")
            with open(path, "w") as f:
                f.write("(define a 1)\n(define b (+ a 1))\n(display b)\n")
            lisp_core.run_file(path, self.env)
        self.assertEqual(self.printed(), "2")


# ---------------------------------------------------------------------------
# 17. The .lsp libraries that ship with the interpreter
# ---------------------------------------------------------------------------

class TestTemplateLibrary(LispTestCase):
    """template.lsp: text templating plus a SQL mode that can only ever
    produce bound parameters, never spliced-in text."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "%s")' % os.path.join(HERE, "template.lsp"))

    def test_variable_substitution(self):
        self.assertShows('(template-render "Hello, {{name}}! {{count}} new{{s}}." '
                         '(template-bindings (name "Ada") (count 3) (s "!")))',
                         '"Hello, Ada! 3 new!."')

    def test_each_loop_with_separator(self):
        self.assertShows('(template-render "[{{#each x in xs sep comma}}{{x}}{{/each}}]" '
                         '(template-bindings (xs (list 1 2 3)) (comma ", ")))',
                         '"[1, 2, 3]"')

    def test_if_else(self):
        tpl = '"{{#if flag}}yes{{else}}no{{/if}}"'
        self.assertShows("(template-render %s (template-bindings (flag #t)))" % tpl, '"yes"')
        self.assertShows("(template-render %s (template-bindings (flag #f)))" % tpl, '"no"')

    def test_if_on_a_missing_binding_is_false(self):
        self.assertShows('(template-render "{{#if maybe}}yes{{else}}no{{/if}}" (template-bindings))', '"no"')

    def test_nested_loops(self):
        self.assertShows('(template-render "{{#each r in rows}}<{{#each c in r}}{{c}}{{/each}}>{{/each}}" '
                         '(template-bindings (rows (list (list 1 2) (list 3 4)))))',
                         '"<12><34>"')

    def test_sql_mode_turns_every_placeholder_into_a_question_mark(self):
        self.assertShows('(template-render-sql "SELECT * FROM loans WHERE state = {{state}} AND balance > {{min}}" '
                         '(template-bindings (state "CA") (min 100000)))',
                         '("SELECT * FROM loans WHERE state = ? AND balance > ?" "CA" 100000)')

    def test_sql_mode_in_list(self):
        self.assertShows('(template-render-sql "id IN ({{#each x in ids sep comma}}{{x}}{{/each}})" '
                         '(template-bindings (ids (list 1 2 3)) (comma ", ")))',
                         '("id IN (?, ?, ?)" 1 2 3)')

    def test_hostile_value_can_never_reach_the_sql_text(self):
        hostile = "x'; DROP TABLE t; --"
        rendered = self.run_lisp('(template-render-sql "SELECT * FROM t WHERE name = {{n}}" '
                                 '(template-bindings (n "%s")))' % hostile)
        sql, params = lisp_core.to_display_string(rendered.car), lisp_core.to_string(rendered.cdr)
        self.assertEqual(sql, "SELECT * FROM t WHERE name = ?")
        self.assertNotIn("DROP", sql)
        self.assertIn("DROP", params)

    def test_sqlite_query_template_end_to_end_with_a_hostile_value(self):
        self.run_lisp("""
          (define conn (sqlite-open ":memory:"))
          (sqlite-execute conn "CREATE TABLE t (name TEXT)")
          (sqlite-execute conn "INSERT INTO t VALUES ('safe')")
          (define r (sqlite-query-template conn "SELECT name FROM t WHERE name = {{n}}"
                      (template-bindings (n "safe' OR '1'='1"))))""")
        # the injection attempt matches nothing (a real injection would return 'safe')
        self.assertShows("(vector-length (cdr (car r)))", "0")

    def test_format_spec_in_a_tag(self):
        self.assertShows('(template-render "{{state:<6}}{{upb:>15,.2f}}{{wac:>8.3f}}" '
                         '(template-bindings (state "CA") (upb 1234567.5) (wac 6.25)))',
                         '"CA       1,234,567.50   6.250"')

    def test_format_spec_inside_an_each_loop(self):
        self.assertShows('(template-render "{{#each x in xs}}[{{x:^7,}}]{{/each}}" '
                         '(template-bindings (xs (list 1000 25))))',
                         '"[ 1,000 ][  25   ]"')

    def test_spaces_around_the_name_are_ignored(self):
        self.assertShows('(template-render "{{ n :>4}}|" (template-bindings (n 5)))', '"   5|"')

    def test_a_bad_format_spec_in_a_tag_is_an_error(self):
        self.assertLispError('(template-render "{{x:.2f}}" (template-bindings (x "CA")))', "isn't a number")

    def test_sql_mode_rejects_a_format_spec(self):
        self.assertLispError('(template-render-sql "WHERE a = {{a:.2f}}" (template-bindings (a 5)))',
                             "{{a:.2f}}")

    def test_parse_once_render_many_times(self):
        self.run_lisp('(define parsed (template-parse "n={{n}}"))')
        self.assertShows("(template-render parsed (template-bindings (n 1)))", '"n=1"')
        self.assertShows("(template-render parsed (template-bindings (n 2)))", '"n=2"')


class TestColumnEngineLibrary(LispTestCase):
    """column_engine.lsp: a small defstruct/&key-based row-by-row calculator.

    Each column's declared :name (e.g. "period") becomes a real global
    variable while calculate-all runs -- so it must differ from the Lisp
    variable holding the column struct itself (period-col), or the struct
    would be overwritten by the row value. (column_engine.lsp's header
    documents this caveat.)"""

    def setUp(self):
        lisp_core.set_verbose_level(0)
        self.tables = []
        self.out = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, columns=self.tables.append)
        self.run_lisp('(load "%s")' % os.path.join(HERE, "column_engine.lsp"))

    def test_columns_chain_and_lag_across_rows(self):
        self.run_lisp("""
          (defcolumn period-col :name "period" :initial_value 0 :value_calculation (+ period 1))
          (defcolumn double-col :name "double" :initial_value 0 :value_calculation (* 2 period))
          (defcolumn running-col :name "running" :initial_value 0
                     :value_calculation (+ (lag running 1) double))
          (calculate-all *columns* 5)""")
        self.assertShows("(column-series period-col)", "#(0 1 2 3 4)")
        self.assertShows("(column-series double-col)", "#(0 2 4 6 8)")
        self.assertShows("(column-series running-col)", "#(0 2 6 12 20)")

    def test_display_columns_receives_only_the_visible_columns(self):
        self.run_lisp("""
          (defcolumn a-col :name "a" :initial_value 1 :value_calculation (+ a 1))
          (defcolumn hidden-col :name "hidden" :initial_value 0 :visible #f
                     :value_calculation (+ hidden 1))
          (calculate-all *columns* 3)""")
        self.assertEqual(len(self.tables), 1)
        self.assertEqual([row[0] for row in self.tables[0]], ["a"])

    def test_lag_default_before_the_first_row(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 1 :value_calculation (+ (lag n 1) 1))
          (defcolumn back-col :name "back" :initial_value 0 :after n-col
                     :value_calculation (lag n 2 -1))
          (calculate-all *columns* 4)""")
        self.assertShows("(column-series back-col)", "#(0 -1 1 2)")

    def test_lag_without_a_default_before_the_first_row_is_an_error(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 1 :value_calculation (+ (lag n 1) 1))
          (defcolumn bad-col :name "bad" :initial_value 0 :after n-col :value_calculation (lag n 2))""")
        self.assertLispError("(calculate-all *columns* 3)", "give lag a default")

    def test_after_orders_columns_by_dependency_not_declaration(self):
        self.run_lisp("""
          (defcolumn base-col :name "base" :initial_value 1 :value_calculation (+ base 1))
          (defcolumn derived-col :name "derived" :after base-col :initial_value 0
                     :value_calculation (* base 10))
          (calculate-all (reverse *columns*) 4)""")
        self.assertShows("(column-series derived-col)", "#(0 20 30 40)")

    def test_a_circular_dependency_is_reported(self):
        self.run_lisp("""
          (define c1 (make-column :name "c1" :initial_value 0 :value_calculation '(+ 1 1) :after '()))
          (define c2 (make-column :name "c2" :initial_value 0 :value_calculation '(+ 1 1) :after c1))
          (column-after-set! c1 c2)""")
        self.assertLispError("(calculate-all (list c1 c2) 3)", "circular or missing")

    def test_write_csv_writes_the_visible_columns(self):
        self.run_lisp("""
          (defcolumn n-col :name "n" :initial_value 0 :value_calculation (+ n 1))
          (calculate-all *columns* 3)""")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            self.run_lisp('(write-csv "%s" *columns*)' % path)
            with open(path) as f:
                lines = f.read().split()
        self.assertEqual(lines[0], "n")
        self.assertEqual(lines[1:], ["0", "1", "2"])


# ---------------------------------------------------------------------------
# 17b. Procedure names, verbose call tracing, and Lisp stack traces
# ---------------------------------------------------------------------------

class TestProcedureNames(LispTestCase):

    def test_define_names_a_function(self):
        self.assertEqual(str(self.run_lisp("(define (f x) x) f").name), "f")

    def test_defining_an_anonymous_lambda_names_it_after_its_first_definition(self):
        self.assertEqual(str(self.run_lisp("(define g (lambda (x) x)) g").name), "g")

    def test_an_alias_keeps_the_original_name(self):
        self.run_lisp("(define (f x) x) (define alias f)")
        self.assertEqual(str(self.run_lisp("alias").name), "f")

    def test_a_closure_is_named_by_the_variable_it_is_first_defined_as(self):
        self.run_lisp("(define (make-adder n) (lambda (x) (+ x n))) (define add5 (make-adder 5))")
        self.assertEqual(str(self.run_lisp("add5").name), "add5")

    def test_an_unbound_lambda_stays_anonymous(self):
        self.assertIsNone(self.run_lisp("(lambda (x) x)").name)

    def test_struct_constructors_are_named(self):
        self.run_lisp("(defstruct point x y)")
        self.assertEqual(str(self.run_lisp("make-point").name), "make-point")

    def test_procedures_print_with_their_name(self):
        self.assertShows("(define (square x) (* x x)) square", "#<procedure square>")
        self.assertShows("(lambda (x) x)", "#<procedure>")

    def test_macros_remember_their_name(self):
        self.assertEqual(str(self.run_lisp("(defmacro m (x) x) m").name), "m")

    def test_let_scopes_are_flagged_and_real_lambdas_are_not(self):
        exprs = list(lisp_core.parse("(let ((x 1)) x)"))
        self.assertIn("%scope-lambda", lisp_core.to_string(lisp_core.desugar_let(exprs[0].cdr)))
        self.assertFalse(self.run_lisp("(lambda (x) x)").is_scope)

    def test_naming_does_not_change_behavior(self):
        self.assertShows("(define (f x) (* 2 x)) (procedure? f)", "#t")
        self.assertShows("(map f (list 1 2 3))", "(2 4 6)")


class TestVerboseBuiltin(LispTestCase):

    def test_default_level_is_off(self):
        self.assertShows("(verbose)", "0")

    def test_setting_returns_the_previous_level(self):
        self.assertShows("(verbose 2)", "0")
        self.assertShows("(verbose 3)", "2")
        self.assertShows("(verbose)", "3")

    def test_booleans_mean_off_and_calls(self):
        self.run_lisp("(verbose #t)")
        self.assertShows("(verbose)", "1")
        self.run_lisp("(verbose #f)")
        self.assertShows("(verbose)", "0")

    def test_the_previous_level_can_be_restored(self):
        self.run_lisp("(define old (verbose 2)) (verbose old)")
        self.assertShows("(verbose)", "0")

    def test_invalid_levels_are_rejected(self):
        for bad in ("5", "-1", "1.5", '"x"', "'()"):
            self.assertLispError("(verbose %s)" % bad, "level must be")
        self.assertLispError("(verbose 1 2)", "expected (verbose [level])")
        self.assertShows("(verbose)", "0")                       # unchanged by the failures

    def test_level_zero_prints_nothing(self):
        self.run_lisp("(define (f) 1) (f) (f)")
        self.assertEqual(self.printed(), "")


class TestCallTracing(LispTestCase):

    FACT = "(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))\n"

    def trace_of(self, level, src):
        """Everything the call trace wrote while running `src` at `level`."""
        self.run_lisp("(verbose %d)" % level)
        del self.out[:]
        self.run_lisp(src)
        return self.printed()

    def test_level_1_logs_each_call_by_name_indented_by_depth(self):
        self.run_lisp(self.FACT)
        self.assertEqual(self.trace_of(1, "(fact 3)"),
                         "> fact\n  > fact\n    > fact\n      > fact\n")

    def test_level_2_adds_arguments_and_return_values(self):
        self.run_lisp(self.FACT)
        self.assertEqual(self.trace_of(2, "(fact 3)"),
                         "> (fact 3)\n"
                         "  > (fact 2)\n"
                         "    > (fact 1)\n"
                         "      > (fact 0)\n"
                         "      < (fact 0) => 1\n"
                         "    < (fact 1) => 1\n"
                         "  < (fact 2) => 2\n"
                         "< (fact 3) => 6\n")

    def test_a_tail_call_replaces_its_callers_frame_and_is_marked(self):
        self.run_lisp("(define (count-down n) (if (= n 0) 'done (count-down (- n 1))))")
        self.assertEqual(self.trace_of(2, "(count-down 3)"),
                         "> (count-down 3)\n"
                         ">> (count-down 2)\n"
                         ">> (count-down 1)\n"
                         ">> (count-down 0)\n"
                         "< (count-down 0) => done  [after 3 tail calls]\n")

    def test_level_1_marks_tail_calls_too_but_logs_no_returns(self):
        self.run_lisp("(define (count-down n) (if (= n 0) 'done (count-down (- n 1))))")
        self.assertEqual(self.trace_of(1, "(count-down 2)"), "> count-down\n>> count-down\n>> count-down\n")

    def test_level_3_also_logs_macro_expansions(self):
        self.run_lisp("(defmacro my-unless (test then) `(if (not ,test) ,then '()))")
        text = self.trace_of(3, "(my-unless #f 'ran)")
        self.assertEqual(text, "~ (my-unless #f (quote ran)) => (if (not #f) (quote ran) (quote ()))\n")

    def test_macro_expansions_are_not_logged_below_level_3(self):
        self.run_lisp("(defmacro my-unless (test then) `(if (not ,test) ,then '()))")
        self.assertEqual(self.trace_of(2, "(my-unless #f 'ran)"), "")

    def test_anonymous_procedures_show_as_lambda(self):
        self.assertEqual(self.trace_of(2, "((lambda (x) (* x 2)) 21)"),
                         "> (<lambda> 21)\n< (<lambda> 21) => 42\n")

    def test_let_dolist_and_builtins_are_not_calls(self):
        self.assertEqual(self.trace_of(3, "(let ((x 1)) (let* ((y 2)) (+ x y)))"), "")
        self.run_lisp("(define total 0)")
        lines = self.trace_of(1, "(dolist (x (list 1 2)) (set! total (+ total x)))").splitlines()
        # only dolist's own loop helper is a real procedure -- no <lambda> lines from its lets
        self.assertTrue(lines)
        for line in lines:
            self.assertIn("%dolist-loop", line)
        self.assertNotIn("<lambda>", "\n".join(lines))

    def test_callbacks_run_by_builtins_are_traced(self):
        self.run_lisp("(define (double x) (* 2 x))")
        text = self.trace_of(2, "(map double (list 1 2))")
        self.assertIn("> (double 1)", text)
        self.assertIn("< (double 2) => 4", text)

    def test_calls_made_inside_a_callback_nest_under_it(self):
        self.run_lisp("(define (inner x) (+ x 1)) (define (outer xs) (map (lambda (x) (+ 1 (inner x))) xs))")
        text = self.trace_of(1, "(outer (list 1))")
        self.assertEqual(text, "> outer\n  > <lambda>\n    > inner\n")

    def test_long_values_are_summarized_not_printed(self):
        self.run_lisp("(define (f a b c) 0) (define big (make-vector 100000 7))")
        text = self.trace_of(2, '(f big (list 1 2 3 4 5 6 7 8 9) "%s")' % ("x" * 200))
        self.assertIn("#(7 7 7 ... n=100000)", text)
        self.assertIn("(1 2 3 4 5 6 ...)", text)
        self.assertLess(max(len(line) for line in text.splitlines()), 160)

    def test_structs_and_nested_lists_are_summarized(self):
        self.run_lisp("(defstruct rec a b c d e f) (define (f r) 0)")
        text = self.trace_of(2, "(f (make-rec :a 1 :b 2 :c 3 :d 4 :e 5 :f 6))")
        self.assertIn("#S(rec :a 1 :b 2 :c 3 :d 4 ...)", text)
        self.assertIn("(...)", self.trace_of(2, "(f '(1 (2 (3 (4 (5))))))"))

    def test_depth_stays_balanced_after_a_caught_error(self):
        self.run_lisp("(define (boom) (car 0)) (define (safe) (catch-error (boom) (e) 'recovered)) (define (id x) x)")
        text = self.trace_of(1, "(safe) (id 1)")
        self.assertEqual(text, "> safe\n  > boom\n> id\n")

    def test_depth_resets_after_an_uncaught_error(self):
        self.run_lisp("(define (boom) (car 0))")
        self.run_lisp("(verbose 1)")
        with self.assertRaises(Exception):
            self.run_lisp("(boom)")
        self.assertEqual(lisp_core._call_depth, 0)

    def test_turning_tracing_on_from_inside_a_running_call_is_safe(self):
        self.run_lisp("(define (g) 1) (define (f) (verbose 1) (g))")
        del self.out[:]
        self.assertShows("(f)", "1")
        self.assertIn(">> g", self.printed())

    def test_trace_output_follows_redirect_output(self):
        self.run_lisp("(define (f) 1)")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "trace.txt")
            self.run_lisp('(verbose 1) (redirect-output "%s") (f) (reset-output)' % path)
            with open(path) as fh:
                self.assertEqual(fh.read(), "> f\n")
        self.assertEqual(self.printed(), "")                       # none went to the console

    def test_tracing_does_not_change_results(self):
        self.run_lisp(self.FACT)
        plain = self.show("(fact 10)")
        self.run_lisp("(verbose 3)")
        self.assertEqual(self.show("(fact 10)"), plain)

    def test_each_environment_writes_to_its_own_output(self):
        other_out = []
        other = lisp_builtins.make_global_env(output=other_out.append)
        self.run_lisp("(define (f) 1)")
        self.run_lisp("(define (g) 2)", env=other)
        self.run_lisp("(verbose 1)")
        self.run_lisp("(f)")
        self.run_lisp("(g)", env=other)
        self.assertEqual(self.printed(), "> f\n")
        self.assertEqual("".join(other_out), "> g\n")


class TestStackTraces(LispTestCase):

    def error_of(self, src):
        """Run `src`, which must raise; return the exception."""
        with self.assertRaises(Exception) as cm:
            self.run_lisp(src)
        return cm.exception

    def test_the_trace_lists_the_call_chain_outermost_first(self):
        self.run_lisp("""
          (define (inner x) (car x))
          (define (middle x) (+ 1 (inner x)))
          (define (outer x) (list (middle x)))""")
        e = self.error_of("(outer 5)")
        self.assertEqual(lisp_core.format_lisp_traceback(e),
                         "Lisp traceback (most recent call last):\n"
                         "  (outer 5)\n  (middle 5)\n  (inner 5)\n")

    def test_error_report_is_the_trace_then_the_message(self):
        self.run_lisp("(define (f x) (car x))")
        self.assertEqual(lisp_core.format_error_report(self.error_of("(+ 1 (f 5))")),
                         "Lisp traceback (most recent call last):\n  (f 5)\nError: car: not a pair: 5\n")

    def test_no_trace_when_the_error_is_outside_any_procedure(self):
        e = self.error_of("(car 5)")
        self.assertEqual(lisp_core.format_lisp_traceback(e), "")
        self.assertEqual(lisp_core.format_error_report(e), "Error: car: not a pair: 5\n")

    def test_a_caller_that_tail_calls_is_replaced_and_counted(self):
        self.run_lisp("(define (inner x) (car x)) (define (helper x) (inner x)) (define (outer x) (helper x))")
        e = self.error_of("(list (outer 5))")
        self.assertEqual(lisp_core.format_lisp_traceback(e),
                         "Lisp traceback (most recent call last):\n  (inner 5)  [+2 tail calls]\n")

    def test_a_self_recursive_tail_loop_shows_one_frame_with_a_count(self):
        self.run_lisp("(define (loop n) (if (= n 0) (car n) (loop (- n 1))))")
        e = self.error_of("(list (loop 1000))")
        self.assertEqual(lisp_core.format_lisp_traceback(e),
                         "Lisp traceback (most recent call last):\n  (loop 0)  [+1000 tail calls]\n")

    def test_a_deep_non_tail_recursion_is_elided_in_the_middle(self):
        self.run_lisp("(define (dive n) (if (= n 0) (car 0) (+ 1 (dive (- n 1)))))")
        lines = lisp_core.format_lisp_traceback(self.error_of("(dive 100)")).splitlines()
        self.assertEqual(len(lines), 1 + 10 + 1 + 30)               # title, outermost, gap, innermost
        self.assertEqual(lines[1], "  (dive 100)")                  # outermost kept
        self.assertEqual(lines[-1], "  (dive 0)")                   # innermost kept
        self.assertIn("... 61 more calls ...", lines[11])

    def test_errors_inside_a_callback_include_the_callback_and_its_caller(self):
        self.run_lisp("(define (check n) (if (> n 2) (error \"too big:\" n) n)) "
                      "(define (run xs) (map (lambda (n) (+ 0 (check n))) xs)) (define (go) (list (run (list 1 3))))")
        e = self.error_of("(go)")
        text = lisp_core.format_lisp_traceback(e)
        for expected in ("(go)", "(run (1 3))", "(<lambda> 3)", "(check 3)"):
            self.assertIn(expected, text)
        self.assertLess(text.index("(go)"), text.index("(run"))
        self.assertLess(text.index("(run"), text.index("(<lambda>"))
        self.assertLess(text.index("(<lambda>"), text.index("(check 3)"))

    def test_an_error_inside_a_macro_transformer_names_the_macro(self):
        self.run_lisp("(defmacro bad (x) (car x)) (define (user) (list (bad 5)))")
        text = lisp_core.format_lisp_traceback(self.error_of("(user)"))
        self.assertIn("(bad 5)  [macro transformer]", text)
        self.assertIn("(user)", text)

    def test_a_call_rejected_for_its_arguments_is_named(self):
        self.run_lisp("(define (needs-two a b) (list a b)) (define (caller) (list (needs-two 1)))")
        self.assertEqual(lisp_core.format_error_report(self.error_of("(caller)")),
                         "Lisp traceback (most recent call last):\n"
                         "  (caller)\n  (needs-two 1)  [arguments rejected]\n"
                         "Error: expected 2 argument(s), got 1\n")

    def test_an_unknown_keyword_names_the_constructor(self):
        self.run_lisp("(defstruct point x y)")
        self.assertIn("(make-point :z 1)  [arguments rejected]",
                      lisp_core.format_lisp_traceback(self.error_of("(make-point :z 1)")))

    def test_a_rejected_callback_call_is_named_too(self):
        self.run_lisp("(define (needs-two a b) (list a b))")
        self.assertIn("(needs-two 1)  [arguments rejected]",
                      lisp_core.format_lisp_traceback(self.error_of("(map needs-two (list 1 2))")))

    def test_a_macro_called_with_the_wrong_argument_count_is_named(self):
        self.run_lisp("(defmacro one-arg (x) x)")
        self.assertIn("(one-arg)  [arguments rejected]", lisp_core.format_lisp_traceback(self.error_of("(one-arg)")))

    def test_plain_python_exceptions_from_builtins_get_a_trace_too(self):
        self.run_lisp("(define (f x) (/ 1 x))")
        e = self.error_of("(list (f 0))")
        self.assertIsInstance(e, ZeroDivisionError)
        self.assertIn("(f 0)", lisp_core.format_lisp_traceback(e))

    def test_a_caught_error_leaves_no_trace_behind_for_the_next_one(self):
        self.run_lisp("(define (boom) (car 0)) (define (safe) (catch-error (boom) (e) 'ok)) (define (other) (car 1))")
        self.run_lisp("(safe)")
        text = lisp_core.format_lisp_traceback(self.error_of("(list (other))"))
        self.assertIn("(other)", text)
        self.assertNotIn("boom", text)
        self.assertNotIn("safe", text)

    def test_let_and_dolist_scopes_never_appear_as_calls(self):
        self.run_lisp("(define (f xs) (let ((y 1)) (dolist (x xs) (car x)) y))")
        text = lisp_core.format_lisp_traceback(self.error_of("(list (f (list 5)))"))
        self.assertIn("(f (5))", text)
        self.assertNotIn("<lambda>", text)

    def test_the_trace_is_stored_innermost_first_on_the_exception(self):
        self.run_lisp("(define (inner) (car 0)) (define (outer) (list (inner)))")
        trace = self.error_of("(outer)").lisp_trace
        self.assertEqual([str(entry[0].name) for entry in trace], ["inner", "outer"])

    def test_control_stack_depth_is_still_constant_for_tail_calls(self):
        """The CALL frames must not undo tail-call optimization: a 3-way
        mutually tail-recursive loop uses the same control-stack depth for
        100 iterations as for 3000."""
        def peak_depth(n):
            peak = [0]
            real = lisp_core.push_sequence

            def spy(exprs, env, control_stack, value_stack):
                peak[0] = max(peak[0], len(control_stack))
                return real(exprs, env, control_stack, value_stack)

            with mock.patch.object(lisp_core, "push_sequence", spy):
                self.run_lisp("""
                  (define (a n) (if (= n 0) 'ok (b (- n 1))))
                  (define (b n) (if (= n 0) 'ok (c (- n 1))))
                  (define (c n) (if (= n 0) 'ok (a (- n 1))))
                  (a %d)""" % n)
            return peak[0]

        self.assertEqual(peak_depth(99), peak_depth(3000))

    def test_deep_non_tail_recursion_still_works_with_call_frames(self):
        self.assertShows("(define (s n) (if (= n 0) 0 (+ n (s (- n 1))))) (s 20000)", str(20000 * 20001 // 2))


class TestBacktrace(LispTestCase):

    def test_backtrace_prints_the_current_call_chain(self):
        self.run_lisp("(define (a) (list (b))) (define (b) (list (c))) (define (c) (backtrace) 0) (a)")
        self.assertEqual(self.printed(),
                         "Lisp call stack (most recent call last):\n  (a)\n  (b)\n  (c)\n")

    def test_backtrace_returns_the_empty_list(self):
        self.assertShows("(backtrace)", "()")

    def test_backtrace_outside_any_call_says_so(self):
        self.run_lisp("(backtrace)")
        self.assertIn("not inside any procedure call", self.printed())

    def test_backtrace_shows_arguments_and_tail_counts(self):
        self.run_lisp("(define (f n) (if (= n 0) (backtrace) (f (- n 1)))) (list (f 3))")
        self.assertIn("(f 0)  [+3 tail calls]", self.printed())

    def test_backtrace_inside_a_callback(self):
        self.run_lisp("(define (each x) (list (backtrace) x)) (define (run) (list (map each (list 7))))  (run)")
        self.assertIn("(run)", self.printed())
        self.assertIn("(each 7)", self.printed())


class TestDebugReplBacktrace(LispTestCase):
    """The breakpoint debugger's own (backtrace) shows the PAUSED program's calls."""

    def run_with_input(self, src, lines):
        feed = iter(lines)
        stdout = io.StringIO()
        with mock.patch("builtins.input", lambda prompt="": next(feed)):
            with contextlib.redirect_stdout(stdout):
                self.run_lisp(src)
        return stdout.getvalue()

    def test_backtrace_at_a_breakpoint_shows_the_paused_programs_calls(self):
        self.run_with_input(
            "(define (inner) (breakpoint) 1) (define (outer) (list (inner))) (outer)",
            ["(backtrace)", "(continue)"])
        # (backtrace) writes to the environment's display channel, like display does
        text = self.printed()
        self.assertIn("Lisp call stack (most recent call last):", text)
        self.assertIn("  (outer)", text)
        self.assertIn("  (inner)", text)

    def test_errors_typed_at_a_breakpoint_are_reported_with_their_trace(self):
        text = self.run_with_input(
            "(define (f x) (breakpoint) x) (f 1)",
            ["(define (boom) (car 0)) (define (wrap) (list (boom))) (wrap)", "(continue)"])
        self.assertIn("(wrap)", text)
        self.assertIn("(boom)", text)
        self.assertIn("Error: car: not a pair", text)


class TestKernelErrorReply(unittest.TestCase):
    """The Jupyter kernel's error box now carries the Lisp call chain."""

    def setUp(self):
        try:
            import lisp_kernel
        except ImportError:
            self.skipTest("ipykernel is not installed")
        self.kernel = lisp_kernel.LispKernel.__new__(lisp_kernel.LispKernel)
        self.sent = []
        self.kernel.send_response = lambda stream, msg_type, content: self.sent.append((msg_type, content))
        self.kernel.iopub_socket = None             # a real one only exists in a running kernel
        self.kernel.execution_count = 1

    def test_error_reply_includes_the_lisp_traceback_lines_then_the_message(self):
        reply = self.kernel._error_reply("LispError", "boom", "Lisp traceback (most recent call last):\n  (f 1)\n")
        self.assertEqual(reply["traceback"],
                         ["Lisp traceback (most recent call last):", "  (f 1)", "LispError: boom"])
        self.assertEqual(self.sent[0][0], "error")
        self.assertEqual(self.sent[0][1]["traceback"], reply["traceback"])

    def test_error_reply_without_a_trace_is_just_the_message(self):
        self.assertEqual(self.kernel._error_reply("LispError", "boom")["traceback"], ["LispError: boom"])

    def test_do_execute_reports_the_call_chain_of_a_failing_cell(self):
        import lisp_jupyter
        lisp_core.set_verbose_level(0)
        lisp_jupyter.get_env()
        reply = self.kernel.do_execute("(define (kf x) (car x)) (list (kf 5))", silent=False)
        self.assertEqual(reply["status"], "error")
        self.assertIn("  (kf 5)", reply["traceback"])
        self.assertEqual(reply["traceback"][-1], "LispError: car: not a pair: 5")


# ---------------------------------------------------------------------------
# 18. The command line
# ---------------------------------------------------------------------------

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

    def test_a_python_level_exception_prints_the_lisp_chain_then_pythons_traceback(self):
        r = self.run_script(source="(define (f x) (/ 1 x))\n(list (f 0))\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(r.stderr.startswith("Lisp traceback (most recent call last):\n  (f 0)\n"), r.stderr)
        self.assertIn("ZeroDivisionError", r.stderr)

    def test_the_repl_shows_the_call_chain_for_an_error_and_keeps_going(self):
        r = run_cli("-", stdin="(define (f x) (car x))\n(list (f 5))\n(+ 20 22)\n(exit)\n")
        self.assertIn("Lisp traceback (most recent call last):\n  (f 5)\nError: car: not a pair: 5", r.stdout)
        self.assertIn("42", r.stdout)

    def test_verbose_flag_works_with_the_repl_too(self):
        r = run_cli("-v", "-", stdin="(define (f) 1)\n(f)\n(exit)\n")
        self.assertIn("> f", r.stdout)


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
""" % HERE

    def test_the_gui_log_shows_the_traceback_and_the_verbose_trace(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   LISP_INIT_FILE=os.path.join(tempfile.gettempdir(), "no-such-init.lsp"))
        r = subprocess.run([sys.executable, "-c", self.PROGRAM], capture_output=True, text=True,
                           env=env, timeout=120)
        if "NO-QT" in r.stdout:
            self.skipTest("PyQt6/matplotlib not installed")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        failing, traced = r.stdout.split("=====")
        self.assertIn("Lisp traceback (most recent call last):\n  (outer 5)\n  (inner 5)\nError: car: not a pair: 5",
                      failing)
        self.assertIn("> (sq 3)\n< (sq 3) => 9\n=> 9", traced)


# ---------------------------------------------------------------------------
# 19. The example scripts (offline ones only) still run
# ---------------------------------------------------------------------------

class TestExampleScripts(unittest.TestCase):
    """Smoke tests: each offline example must run to completion. Every
    script runs ONCE (in setUpClass), in a temporary copy of the .lsp,
    .csv, and .txt files so anything it writes lands there, never in the
    repository.

    The two slowest examples (about 15s and 60s) only run when the
    environment variable LISP_TEST_SLOW is set."""

    FAST_EXAMPLES = [
        "macros_example.lsp",
        "with_struct_example.lsp",
        "trace_example.lsp",
        "metaprogramming_example.lsp",
        "prepayment_demo.lsp",
        "linear_programming_example.lsp",
    ]
    SLOW_EXAMPLES = [
        "dolist_vectors_map_example.lsp",
        "oas_monte_carlo_example.lsp",
    ]

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for name in os.listdir(HERE):
            if name.endswith((".lsp", ".csv", ".txt")):
                shutil.copy(os.path.join(HERE, name), cls.tmp)
        names = cls.FAST_EXAMPLES + (cls.SLOW_EXAMPLES if os.environ.get("LISP_TEST_SLOW") else [])
        cls.results = {name: run_cli(os.path.join(cls.tmp, name), cwd=cls.tmp) for name in names}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_each_offline_example_runs_cleanly(self):
        for name, r in self.results.items():
            with self.subTest(example=name):
                self.assertEqual(r.returncode, 0, "%s failed:\n%s" % (name, r.stderr[-1500:]))

    def test_the_macros_example_produces_its_documented_output(self):
        out = self.results["macros_example.lsp"].stdout
        self.assertIn("after swap!:  p=2 q=1", out)
        self.assertIn("my-while summed 0..199999 -> 19999900000", out)

    def test_the_linear_programming_example_finds_the_best_allocation(self):
        out = self.results["linear_programming_example.lsp"].stdout
        self.assertIn("Yearly income: $6,200,000", out)
        self.assertIn("  CMO Z-tranche           20,000,000    7.2%", out)
        self.assertIn("    6.00     6,320,000   6.32%", out)
        self.assertIn("limited to 4 years: lp-solve: Problem is infeasible.", out)

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

    def test_the_with_struct_example_produces_its_documented_output(self):
        out = self.results["with_struct_example.lsp"].stdout
        self.assertIn("30yr 6% $300k payment: 179865 cents/month", out)
        self.assertIn("300000 tail calls -> 300000", out)


# ---------------------------------------------------------------------------
# 20. The reference document's own examples
# ---------------------------------------------------------------------------
#
# Every fenced ```lisp block in lisp_interpreter_reference.md is run, and each
# top-level form written as   (expr)   ; => value   must print as `value`.
# That keeps the documentation honest: if a builtin's behavior changes, this
# fails until the doc (or the interpreter) is fixed.

# blocks that would block on stdin, need the network/GUI, or touch the disk
_RISKY_BLOCK_WORDS = (
    "breakpoint", "fred-series", "tastytrade", "sofr-", "(load ", "redirect-output", "sqlite-open", "with-sqlite", "lp-read-file",
    "plot-xy", "save-chart", "load-csv", "write-columns-csv", "display-columns",
    "debug-function", "input", "exit", "load-init", "http-get", "http-clear-cache",
)
# examples whose documented value is illustrative rather than exact
_ILLUSTRATIVE_PREFIXES = ("e.g.", "one of", "some", "a ", "an ", "somewhere", "error", "raises",
                          "Lisp", "prints", "(same", "same")
# examples that depend on global counters / what else has been defined
_SKIPPED_FORMS = ("(gensym", "(defined-functions)", "(bound-variables)")


def _split_doc_forms(block):
    """Yield (form_text, expected_or_None) for each top-level form in a doc
    code block; `expected` is the text after a trailing `; =>` comment."""
    i, n = 0, len(block)
    while i < n:
        c = block[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == ";":
            j = block.find("\n", i)
            i = n if j < 0 else j
            continue
        start, depth, in_str = i, 0, False
        while i < n:
            c = block[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == ";":
                    j = block.find("\n", i)
                    i = n if j < 0 else j
                    continue
                elif c in "([":
                    depth += 1
                elif c in ")]":
                    depth -= 1
                elif depth == 0 and c in " \t\r\n":
                    break
                if depth == 0 and c in ")]":
                    i += 1
                    break
            i += 1
        eol = block.find("\n", i)
        eol = n if eol < 0 else eol
        m = re.match(r"\s*;\s*=>\s*(.*)$", block[i:eol])
        yield block[start:i], (m.group(1).strip() if m else None)


def _doc_value_matches(actual, documented):
    """Exact, or exact followed by explanatory prose ('3  -- because ...')."""
    if documented == actual:
        return True
    return documented.startswith(actual) and documented[len(actual):len(actual) + 1] in (" ", ",", "\t")


class TestReferenceDocExamples(unittest.TestCase):

    MIN_VERIFIED = 150          # guard: the checker must not silently verify nothing

    def test_every_documented_result_is_what_the_interpreter_returns(self):
        self.addCleanup(lisp_core.set_verbose_level, 0)     # some doc examples turn tracing on
        with open(REFERENCE_DOC, encoding="utf-8") as f:
            blocks = re.findall(r"```lisp\n(.*?)```", f.read(), re.S)
        self.assertGreater(len(blocks), 100, "found no lisp code blocks in the reference doc")

        use_alarm = hasattr(signal, "SIGALRM")
        verified, failures = 0, []
        # A throwaway working directory: even a doc example that writes a file
        # (a database, a log, a CSV) can then never leave anything behind in
        # the repository.
        scratch = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        os.chdir(scratch)

        def on_alarm(signum, frame):
            raise TimeoutError("doc example ran too long")

        if use_alarm:
            signal.signal(signal.SIGALRM, on_alarm)

        for bi, block in enumerate(blocks):
            if any(word in block for word in _RISKY_BLOCK_WORDS):
                continue
            env = lisp_builtins.make_global_env(output=lambda s: None)
            lisp_core.run_file(lisp_builtins.MACROS_INIT_FILE, env)     # while, do
            if use_alarm:
                signal.alarm(10)
            try:
                for text, documented in _split_doc_forms(block):
                    try:
                        exprs = lisp_core.parse(text)
                    except lisp_core.LispError:
                        break
                    stop = False
                    for expr in exprs:
                        try:
                            value = lisp_core.seval(expr, env)
                        except TimeoutError:
                            raise
                        except Exception as e:
                            # an example whose setup lives in an earlier block, or one
                            # that documents an error, has nothing to compare here
                            if documented is not None and "unbound symbol" not in str(e):
                                failures.append("block %d: %s  raised %s: %s"
                                                % (bi, text.replace("\n", " ")[:80], type(e).__name__, e))
                            stop = True
                            break
                        if documented is None or documented.startswith(_ILLUSTRATIVE_PREFIXES) \
                                or "again" in documented or any(s in text for s in _SKIPPED_FORMS):
                            continue
                        if (_doc_value_matches(lisp_core.to_string(value), documented)
                                or _doc_value_matches(lisp_core.to_display_string(value), documented)):
                            verified += 1
                        else:
                            failures.append("block %d: %s\n      doc says: %s\n      got:      %s"
                                            % (bi, text.replace("\n", " ")[:80], documented,
                                               lisp_core.to_string(value)))
                    if stop:
                        break
            except TimeoutError:
                failures.append("block %d timed out" % bi)
            finally:
                if use_alarm:
                    signal.alarm(0)

        os.chdir(old_cwd)
        shutil.rmtree(scratch, ignore_errors=True)

        self.assertEqual(failures, [], "documented examples that no longer hold:\n" + "\n".join(failures))
        self.assertGreaterEqual(verified, self.MIN_VERIFIED,
                                "only %d doc examples were verified" % verified)


if __name__ == "__main__":
    unittest.main()
