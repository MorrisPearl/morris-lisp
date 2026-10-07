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
connection or an account (fred-table, tastytrade-*, sofr-calibration-data).
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

import base64
import contextlib
import datetime
import importlib.util
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lisp_alpha_vantage  # noqa: E402
import lisp_calendar  # noqa: E402
import lisp_investment_paths  # noqa: E402
import lisp_options  # noqa: E402
import lisp_builtins  # noqa: E402  (these need the sys.path line above)
import lisp_core     # noqa: E402
import lisp_charts  # noqa: E402
import lisp_clock  # noqa: E402
import lisp_plot_chart  # noqa: E402
import lisp_fred  # noqa: E402
import lisp_http  # noqa: E402
import lisp_jupyter_debug  # noqa: E402
import lisp_tastytrade  # noqa: E402
import lisp_tables  # noqa: E402
import lisp_time_series  # noqa: E402
import lisp_vector_math  # noqa: E402

INTERPRETER = os.path.join(HERE, "lisp_interpreter.py")
LIB = os.path.join(HERE, "lib")                 # the Lisp libraries that come with the interpreter
EXAMPLES = os.path.join(HERE, "examples")
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
        lisp_core.debug_state.reset()          # so are breakpoints and the debug hook
        self.addCleanup(lisp_core.debug_state.reset)
        # A stop that opens the debug REPL reads the keyboard. Tests that expect
        # one use run_with_input; any other must fail, not wait for a person.
        patcher = mock.patch("builtins.input", side_effect=AssertionError(
            "the debug REPL asked for input -- use run_with_input to answer it"))
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def run_with_input(self, src, lines):
        """Run `src` with the debug REPL reading `lines` as if they were typed;
        return what was printed to the console (the REPL's own output), and
        keep it in self.console and the value in self.result. If the program
        stops more often than there are lines, input() raises StopIteration, so
        the test fails instead of waiting for the keyboard."""
        feed = iter(lines)
        self.console = io.StringIO()
        with mock.patch("builtins.input", lambda prompt="": next(feed)):
            with contextlib.redirect_stdout(self.console):
                self.result = self.run_lisp(src)
        return self.console.getvalue()

    # -- assertions --------------------------------------------------------

    def assertShows(self, src, expected):
        self.assertEqual(self.show(src), expected, msg="source: %s" % src)

    def assertLispError(self, src, fragment=""):
        """`src` must raise the interpreter's own LispError whose message
        contains `fragment`."""
        with self.assertRaises(lisp_core.LispError, msg="source: %s" % src) as cm:
            self.run_lisp(src)
        self.assertIn(fragment, str(cm.exception))

    def assertAborts(self, src):
        """`src` must be abandoned by (abort), which no catch-error stops."""
        with self.assertRaises(lisp_core.LispAbort, msg="source: %s" % src):
            self.run_lisp(src)

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
                     "cond", "and", "or", "defmacro",
                     "defstruct", "with-struct", "catch-error", "breakpoint"):
            self.assertIn(name, lisp_core.SPECIAL_FORMS)

    def test_let_let_star_and_dolist_are_macros_from_macros_init(self):
        for name in ("let", "let*", "dolist"):
            self.assertNotIn(name, lisp_core.SPECIAL_FORMS)
            self.assertIsInstance(self.env[lisp_core.Symbol(name)], lisp_core.Macro)


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
        self.assertLispError("((lambda (a) a) 1 2)", "<lambda>: expected 1 argument, got 2")
        self.assertLispError("((lambda (a b) a) 1)", "<lambda>: expected 2 arguments, got 1")

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
        next_name = "%%while-loop-%d" % (lisp_core._gensym_counter[0] + 1)
        self.run_lisp("(define calls 0) (define (%s) (set! calls (+ calls 1))) (define i 0)" % next_name)
        self.run_lisp("(while (< i 3) (set! i (+ i 1)) (%s))" % next_name)
        self.assertShows("calls", "3")

    def test_a_pasted_macro_expansion_still_works(self):
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


class TestMacroExpansionCache(LispTestCase):
    """A macro call is expanded once, the first time it's evaluated, and the
    expansion is remembered for that call."""

    def setUp(self):
        super().setUp()
        self.run_lisp("(define expansions 0)"
                      "(defmacro counted (x) (set! expansions (+ expansions 1)) x)")

    def test_a_call_in_a_function_is_expanded_once_however_often_it_runs(self):
        self.run_lisp("(define (f) (counted 5))")
        self.assertShows("(list (f) (f) (f))", "(5 5 5)")
        self.assertShows("expansions", "1")

    def test_a_call_in_a_loop_body_is_expanded_once(self):
        self.run_lisp("(define n 0) (while (< n 100) (counted 1) (set! n (+ n 1)))")
        self.assertShows("expansions", "1")

    def test_separate_calls_of_the_same_macro_are_expanded_separately(self):
        self.run_lisp("(define (f) (counted 1)) (define (g) (counted 2)) (f) (g) (f) (g)")
        self.assertShows("expansions", "2")

    def test_the_same_source_typed_twice_is_two_calls(self):
        self.run_lisp("(counted 1)")
        self.run_lisp("(counted 1)")
        self.assertShows("expansions", "2")

    def test_redefining_the_macro_makes_old_calls_expand_again(self):
        self.run_lisp("(defmacro m () 1) (define (f) (m))")
        self.assertShows("(f)", "1")
        self.run_lisp("(defmacro m () 2)")
        self.assertShows("(f)", "2")

    def test_a_macro_that_fails_is_not_remembered(self):
        self.run_lisp("(define fail #t) (defmacro m () (if fail (error \"not yet\") 7)) (define (f) (m))")
        self.assertLispError("(f)", "not yet")
        self.run_lisp("(set! fail #f)")
        self.assertShows("(f)", "7")

    def test_macroexpand_always_expands_afresh(self):
        self.run_lisp("(macroexpand-1 '(counted 1)) (macroexpand-1 '(counted 1)) (macroexpand '(counted 1))")
        self.assertShows("expansions", "3")

    def test_an_expansion_can_hold_a_gensym_and_run_many_times(self):
        self.run_lisp("(defmacro with-tmp (value body) (let ((tmp (gensym))) `(let ((,tmp ,value)) (+ ,tmp ,body))))"
                      "(define (f x) (with-tmp x 1))")
        self.assertShows("(list (f 1) (f 2) (f 3))", "(2 3 4)")

    def test_a_recursive_function_using_a_macro_works(self):
        self.run_lisp("(defmacro twice (x) `(* 2 ,x)) (define (f n) (if (= n 0) 0 (+ (twice 1) (f (- n 1)))))")
        self.assertShows("(f 50)", "100")

    def test_verbose_level_3_logs_an_expansion_when_it_is_made(self):
        self.run_lisp("(defmacro m1 (x) `(+ ,x 1)) (define (f) (m1 5))")
        lisp_core.set_verbose_level(3)
        self.run_lisp("(f)")
        self.assertEqual(self.printed().count("~ (m1 5) => (+ 5 1)"), 1)            # expanded, and logged
        self.run_lisp("(f)")
        self.assertEqual(self.printed().count("~ (m1 5) => (+ 5 1)"), 1)            # remembered: nothing to log

    def test_calls_a_macro_makes_while_expanding_are_not_traced(self):
        self.run_lisp("(define (helper x) x) (defmacro m2 (x) (helper x)) (define (f) (m2 5))")
        lisp_core.set_verbose_level(2)
        self.assertShows("(f)", "5")
        self.assertEqual(self.printed(), "> (f)\n< (f) => 5\n")

    def test_the_cache_is_emptied_when_it_gets_too_big(self):
        with mock.patch.object(lisp_core, "EXPANSION_CACHE_LIMIT", 10):
            for i in range(25):
                self.run_lisp("(counted %d)" % i)
            self.assertLessEqual(len(lisp_core._expansion_cache), 10)
        self.assertShows("expansions", "25")


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


class TestErrorMessages(LispTestCase):
    """An error names the procedure or special form that went wrong."""

    def test_a_builtin_given_the_wrong_number_of_arguments(self):
        self.assertLispError("(cons 1)", "cons: expected 2 arguments, got 1")
        self.assertLispError("(car 1 2)", "car: expected 1 argument, got 2")
        self.assertLispError("(substring)", "substring: expected 2 to 3 arguments, got 0")

    def test_a_builtin_given_the_wrong_type_of_value(self):
        self.assertLispError('(string-append "a" 1)',
                             'string-append: an argument is the wrong type of value, in (string-append "a" 1)')

    def test_a_python_exception_becomes_a_lisp_error_naming_the_builtin(self):
        self.assertLispError("(sqrt -1)", "sqrt: ")
        self.assertLispError("(/ 1 0)", "/: division by zero")

    def test_a_builtin_called_by_map_is_named(self):
        self.assertLispError("(map sqrt (list -1))", "sqrt: ")

    def test_a_procedure_given_the_wrong_number_of_arguments(self):
        self.run_lisp("(define (f a b) a)")
        self.assertLispError("(f 1)", "f: expected 2 arguments, got 1")
        self.assertLispError("(map f (list 1))", "f: expected 2 arguments, got 1")

    def test_a_procedure_given_an_unknown_keyword(self):
        self.run_lisp("(define (g &key a) a)")
        self.assertLispError("(g :b 1)", "g: unknown keyword argument(s): :b")

    def test_a_struct_accessor_is_named(self):
        self.run_lisp("(defstruct point x y)")
        self.assertLispError("(point-x)", "point-x: expected 1 argument, got 0")

    def test_a_badly_formed_special_form(self):
        self.assertLispError("(define x)", "define: badly formed: (define x)")
        self.assertLispError("(if)", "if: badly formed: (if)")

    def test_a_badly_formed_let(self):
        self.assertLispError("(let ((x)) x)", "let: each binding must be (name value), not (x)")
        self.assertLispError("(let loop ((i 0)) i)", "let: expected a list of bindings")
        self.assertLispError("(let* ((x 1) y) x)", "let*: each binding must be (name value), not y")

    def test_calling_something_that_is_not_a_procedure(self):
        self.assertLispError("(5 1)", "not a procedure: 5")

    def test_string_to_number(self):
        self.assertShows('(string->number "42")', "42")
        self.assertShows('(string->number " -3.5 ")', "-3.5")
        self.assertShows('(string->number "1e3")', "1000.0")
        self.assertLispError('(string->number "abc")', 'string->number: "abc" isn\'t a number')

    def test_catch_error_sees_the_message(self):
        self.assertShows('(catch-error (cons 1) (e) e)', '"cons: expected 2 arguments, got 1"')


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

class TestCommonLispListFunctions(LispTestCase):
    """remove, count, some, every, find-if, position, remove-duplicates, the
    set functions, append-map, for-each, iota; hash-table-copy and
    hash-table-update!; gcd and lcm; and the push, pop, incf, decf macros."""

    def test_remove_and_count(self):
        self.assertShows("(remove 2 '(1 2 3 2))", "(1 3)")
        self.assertShows("(remove 2 #(1 2 3))", "#(1 3)")                       # a vector for a vector
        self.assertShows("(remove-if odd? '(1 2 3 4))", "(2 4)")
        self.assertShows("(remove \"a\" (list \"a\" 'a))", "(a)")             # a string isn't a symbol
        self.assertShows("(count 2 '(1 2 2.0))", "2")                          # 2 and 2.0 are equal?
        self.assertShows("(count-if even? #(1 2 4))", "2")
        self.assertLispError("(remove 1 5)", "remove: expected a list, got 5")

    def test_some_every_find_position(self):
        self.assertShows("(some (lambda (x) (and (> x 2) (* x 10))) '(1 3 5))", "30")
        self.assertShows("(some odd? '(2 4))", "#f")
        self.assertShows("(some = '(1 2) '(3 2))", "#t")                       # in step, as map
        self.assertShows("(every odd? '(1 3))", "#t")
        self.assertShows("(every odd? '(1 2))", "#f")
        self.assertShows("(every odd? '())", "#t")
        self.assertShows("(find-if even? '(1 4 6))", "4")
        self.assertShows("(find-if even? '(1 3))", "#f")
        self.assertShows("(position 'c '(a b c))", "2")
        self.assertShows("(position 9 #(1 2))", "#f")
        self.assertShows("(position-if string? (list 1 \"a\"))", "1")
        self.assertLispError("(some odd?)", "some: expected at least 1 list or vector after the procedure")

    def test_remove_duplicates_and_sets(self):
        self.assertShows("(remove-duplicates (list 1 2 1.0 #t 1 \"a\" 'a \"a\" '(1) '(1)))",
                         '(1 2 #t "a" a (1))')                                 # #t isn't 1; "a" isn't a
        self.assertShows("(remove-duplicates #(3 1 3 2))", "#(3 1 2)")         # in order, unlike vector-unique
        self.assertShows("(union '(1 2 2) '(2 3))", "(1 2 3)")
        self.assertShows("(intersection '(1 2 3 2) '(3 2 5))", "(2 3)")
        self.assertShows("(set-difference '(1 2 3) '(2))", "(1 3)")
        self.assertShows("(intersection '((1) (2)) '((2)))", "((2))")          # lists, compared with equal?

    def test_append_map_for_each_iota(self):
        self.assertShows("(append-map (lambda (x) (list x x)) '(1 2))", "(1 1 2 2)")
        self.assertShows("(append-map list '(1 2) '(a b))", "(1 a 2 b)")
        self.assertShows("(append-map list '())", "()")
        self.run_lisp("(for-each (lambda (x y) (display (+ x y))) '(1 2) '(10 20))")
        self.assertEqual(self.printed(), "1122")
        self.assertShows("(iota 4)", "(0 1 2 3)")
        self.assertShows("(iota 3 1)", "(1 2 3)")
        self.assertShows("(iota 3 0 5)", "(0 5 10)")
        self.assertShows("(iota 0)", "()")
        self.assertLispError("(iota -1)", "iota: count must be a whole number, 0 or more")

    def test_list_tail_is_the_lists_own(self):
        self.assertShows("(let ((l (list 1 2 3))) (eq? (list-tail l 1) (cdr l)))", "#t")

    def test_hash_table_copy_and_update(self):
        self.run_lisp("(define h (make-hash-table)) (hash-table-set! h \"a\" 1) (define c (hash-table-copy h))"
                      "(hash-table-set! c \"a\" 2)")
        self.assertShows('(list (hash-table-ref h "a") (hash-table-ref c "a"))', "(1 2)")
        self.assertShows('(hash-table-update! h "a" (lambda (n) (+ n 10)))', "11")
        self.assertShows('(hash-table-update! h "b" (lambda (n) (+ n 1)) 0)', "1")
        self.assertShows('(hash-table-ref h "b")', "1")
        self.assertLispError('(hash-table-update! h "z" (lambda (n) n))',
                             'hash-table-update!: "z" isn\'t in the table, and there\'s no default')

    def test_gcd_and_lcm(self):
        self.assertShows("(gcd 12 18)", "6")
        self.assertShows("(gcd 12 18 8)", "2")
        self.assertShows("(lcm 4 6)", "12")
        self.assertShows("(gcd 12.0 18)", "6")
        self.assertShows("(list (gcd) (lcm))", "(0 1)")
        self.assertLispError("(gcd 1.5 3)", "gcd: expected whole numbers, got 1.5")

    def test_push_pop_incf_decf(self):
        self.run_lisp("(define stack '())")
        self.assertShows("(push 1 stack)", "(1)")
        self.assertShows("(push 2 stack)", "(2 1)")
        self.assertShows("(pop stack)", "2")
        self.assertShows("stack", "(1)")
        self.run_lisp("(define n 10)")
        self.assertShows("(incf n)", "11")
        self.assertShows("(incf n 4)", "15")
        self.assertShows("(decf n)", "14")
        self.assertShows("(decf n 10)", "4")
        # in a function, on a local variable
        self.assertShows("(let ((total 0)) (dolist (x '(1 2 3)) (incf total x)) total)", "6")
        # pop's own temporary can't clash with the program's names
        self.assertShows("(let ((first-item '(a b))) (pop first-item))", "a")
        self.assertLispError("(push 1 (car stack))", "push: expected a variable to push onto, not (car stack)")
        self.assertLispError("(incf 5)", "incf: expected a variable, not 5")


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

    def test_even_odd_zero_positive_negative(self):
        self.assertShows("(list (even? 4) (even? 3) (odd? -3) (odd? 0) (even? 4.0))", "(#t #f #t #f #t)")
        self.assertShows("(list (zero? 0) (zero? 0.0) (zero? 1))", "(#t #t #f)")
        self.assertShows("(list (positive? 2) (positive? 0) (negative? -0.5) (negative? 0))", "(#t #f #t #f)")
        self.assertLispError("(even? 4.5)", "even?: expected a whole number, got 4.5")
        self.assertLispError('(zero? "0")', "zero?: not a number")

    def test_division_is_true_division(self):
        self.assertShows("(/ 20 2 5)", "2.0")
        self.assertShows("(/ 7 2)", "3.5")
        self.assertShows("(/ 4)", "0.25")
        self.assertLispError("(/)")

    def test_division_by_zero_is_an_error_naming_the_builtin(self):
        self.assertLispError("(/ 1 0)", "/: division by zero")

    def test_mod_has_the_sign_of_the_divisor_and_remainder_of_the_dividend(self):
        self.assertShows("(mod 7 3)", "1")
        self.assertShows("(mod -7 3)", "2")
        self.assertShows("(mod 7 -3)", "-2")
        self.assertShows("(remainder -7 3)", "-1")
        self.assertShows("(remainder 7 -3)", "1")
        self.assertShows("(remainder 7.5 2)", "1.5")

    def test_quotient_truncates_toward_zero(self):
        self.assertShows("(quotient 7 2)", "3")
        self.assertShows("(quotient -7 2)", "-3")
        self.assertShows("(quotient 7.5 2)", "3")
        self.assertShows("(+ (* 2 (quotient -7 2)) (remainder -7 2))", "-7")

    def test_quotient_is_exact_for_big_whole_numbers(self):
        self.assertShows("(quotient 1000000000000000001 1)", "1000000000000000001")
        self.assertShows("(remainder 1000000000000000001 10)", "1")

    def test_integer_division_by_zero_is_an_error(self):
        self.assertLispError("(quotient 1 0)", "quotient: ")
        self.assertLispError("(mod 1 0)", "mod: ")

    def test_abs_min_max(self):
        self.assertShows("(abs -5)", "5")
        self.assertShows("(min 3 1 4 1 5)", "1")
        self.assertShows("(max 3 1 4 1 5)", "5")

    def test_sqrt(self):
        self.assertShows("(sqrt 16)", "4.0")
        self.assertLispError("(sqrt -1)", "sqrt: ")

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


class TestArithmeticOnVectors(LispTestCase):
    """+, -, *, /, the comparisons, and the math functions, given vectors:
    element by element, with a single number used for every element."""

    def test_the_four_operations(self):
        self.assertShows("(+ #(1 2 3) 10)", "#(11 12 13)")
        self.assertShows("(- #(10 20) #(1 2))", "#(9 18)")
        self.assertShows("(* #(1 2) #(3 4) 2)", "#(6 16)")
        self.assertShows("(/ #(1 2) 4)", "#(0.25 0.5)")
        self.assertShows("(+ 1 2 #(10 20))", "#(13 23)")

    def test_one_argument_negates_or_inverts(self):
        self.assertShows("(- #(1 -2))", "#(-1 2)")
        self.assertShows("(/ #(2 4))", "#(0.5 0.25)")

    def test_dividing_a_vector_by_zero_gives_infinity_not_an_error(self):
        self.assertShows("(/ #(1 0) 0)", "#(inf nan)")

    def test_the_vectors_must_be_the_same_length(self):
        self.assertLispError("(+ #(1 2) #(1 2 3))", "+: the vectors have different lengths: 2, 3")

    def test_only_numbers_and_vectors(self):
        self.assertLispError('(* #(1 2) "a")', '*: not a number or a vector: "a"')

    def test_comparisons_give_masks(self):
        self.assertShows("(< #(1 5 3) 4)", "#(1 0 1)")
        self.assertShows("(= #(1 2 3) #(1 0 3))", "#(1 0 1)")
        self.assertShows("(>= #(1 2 3) 2)", "#(0 1 1)")

    def test_a_chained_comparison_tests_every_pair(self):
        self.assertShows("(< 0 #(-1 0.5 2) 1)", "#(0 1 0)")

    def test_a_mask_picks_rows(self):
        self.assertShows("(vector-select #(10 20 30) (> #(1 2 3) 1))", "#(20 30)")

    def test_math_functions(self):
        self.assertShows("(sqrt #(4 9))", "#(2.0 3.0)")
        self.assertShows("(abs #(-1 2))", "#(1 2)")
        self.assertShows("(expt #(2 3) 2)", "#(4.0 9.0)")
        self.assertShows("(log #(1 100) 10)", "#(0.0 2.0)")
        self.assertShows("(exp #(0))", "#(1.0)")

    def test_rounding_gives_whole_numbers(self):
        self.assertShows("(floor #(1.5 -1.5))", "#(1 -2)")
        self.assertShows("(ceiling #(1.5 -1.5))", "#(2 -1)")
        self.assertShows("(truncate #(1.5 -1.5))", "#(1 -1)")
        self.assertShows("(round #(2.5 3.5))", "#(2 4)")
        self.assertShows("(floor #(1.5 nan))", "#(1.0 nan)")        # a missing value stays missing

    def test_min_and_max_work_position_by_position(self):
        self.assertShows("(max #(-1 2 -3) 0)", "#(0 2 0)")
        self.assertShows("(min #(1 5) #(3 2))", "#(1 2)")

    def test_integer_division(self):
        self.assertShows("(quotient #(7 -7 8) 2)", "#(3 -3 4)")
        self.assertShows("(remainder #(7 -7) 2)", "#(1 -1)")
        self.assertShows("(mod #(7 -7) 2)", "#(1 1)")

    def test_the_arguments_are_not_changed(self):
        self.run_lisp("(define v (vector 1 2 3)) (define w (* v 2))")
        self.assertShows("v", "#(1 2 3)")

    def test_the_vector_names_still_work(self):
        self.assertShows("(vector-add #(1 2) 1)", "#(2 3)")
        self.assertShows("(vector< #(1 5) 3)", "#(1 0)")


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

    def test_a_string_is_never_equal_to_a_symbol(self):
        """Both are Python strs underneath, but not the same Lisp value."""
        self.assertShows("(equal? \"a\" 'a)", "#f")
        self.assertShows("(eq? 'a \"a\")", "#f")
        self.assertShows("(equal? '(a) (list \"a\"))", "#f")
        self.assertShows("(member 'a (list \"a\" 'a))", "(a)")
        self.assertShows("(case \"x\" ((x) 'symbol) ((\"x\") 'string))", "string")

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
        # the sublist is l's own, not a copy
        self.assertShows("(let ((l (list 1 2 3))) (eq? (member 2 l) (cdr l)))", "#t")

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


class TestSequenceFunctions(LispTestCase):
    """The list functions that also work on vectors and strings -- and a clear
    error, not a wrong answer, for anything else."""

    def test_length(self):
        self.assertShows("(length (list 1 2 3))", "3")
        self.assertShows("(length #(1 2 3))", "3")
        self.assertShows('(length "abcd")', "4")
        self.assertLispError("(length 5)", "length: expected a list, got 5")
        self.assertLispError("(length '(1 2 . 3))", "length: expected a list, got (1 2 . 3)")

    def test_reverse(self):
        self.assertShows("(reverse #(1 2 3))", "#(3 2 1)")
        self.assertShows('(reverse "abc")', '"cba"')

    def test_map_over_a_vector_gives_a_vector(self):
        self.assertShows("(map (lambda (x) (* x 10)) #(1 2))", "#(10 20)")

    def test_filter_over_a_vector_gives_a_vector(self):
        self.assertShows("(filter (lambda (x) (> x 1)) #(1 2 3))", "#(2 3)")
        self.assertShows("(filter (lambda (x) (> x 5)) #(1 2 3))", "#()")

    def test_reduce_over_a_vector(self):
        self.assertShows("(reduce + #(1 2 3))", "6")
        self.assertShows("(reduce + #() 0)", "0")
        self.assertLispError("(reduce + '())", "reduce: nothing to combine")

    def test_append_vectors_or_strings(self):
        self.assertShows("(append #(1) #(2 3))", "#(1 2 3)")
        self.assertShows('(append "ab" "cd")', '"abcd"')
        self.assertShows("(append (list 1) (list 2) 3)", "(1 2 . 3)")
        self.assertLispError("(append #(1) (list 2))", "append: expected a list, got #(1)")

    def test_apply_to_a_vector(self):
        self.assertShows("(apply + #(1 2 3))", "6")

    def test_list_only_functions_reject_a_vector(self):
        self.assertLispError("(member 2 #(1 2))", "member: expected a list, got #(1 2)")
        self.assertLispError("(list-ref #(1 2) 0)", "list-ref: expected a list")
        self.assertLispError("(assoc 1 #(1 2))", "assoc: expected a list")

    def test_vector_functions_reject_a_list(self):
        self.assertLispError("(vector-length (list 1))", "vector-length: expected a vector, got (1)")
        self.assertLispError("(vector->list (list 1))", "vector->list: expected a vector")

    def test_dolist_over_a_vector(self):
        self.assertShows("(let ((s 0)) (dolist (x #(1 2 3) s) (set! s (+ s x))))", "6")
        self.assertLispError("(dolist (x 5) x)", "dolist: expected a list or a vector, not 5")


class TestEqual(LispTestCase):

    def test_long_lists(self):
        self.run_lisp("(define a (loop for i from 1 to 20000 collect i))")
        self.assertShows("(equal? a (loop for i from 1 to 20000 collect i))", "#t")
        self.assertShows("(equal? a (cdr a))", "#f")

    def test_lists_of_different_lengths_or_tails(self):
        self.assertShows("(equal? (list 1 2) (list 1 2 3))", "#f")
        self.assertShows("(equal? (list 1 2 3) (list 1 2))", "#f")
        self.assertShows("(equal? '(1 . 2) '(1 . 2))", "#t")
        self.assertShows("(equal? '(1 . 2) '(1 2))", "#f")

    def test_nested_lists(self):
        self.assertShows("(equal? '(1 (2 3) #(4)) (list 1 (list 2 3) #(4)))", "#t")


class TestBooleansAreNotNumbers(LispTestCase):
    """Python counts True as 1 and False as 0; Lisp doesn't."""

    def test_equal_and_eq(self):
        self.assertShows("(equal? #f 0)", "#f")
        self.assertShows("(equal? #t 1)", "#f")
        self.assertShows("(eq? #f 0)", "#f")
        self.assertShows("(equal? #f #f)", "#t")
        self.assertShows("(eq? #t #t)", "#t")
        self.assertShows("(equal? 1 1.0)", "#t")            # numbers still compare as numbers

    def test_inside_lists_and_structs(self):
        self.assertShows("(equal? '(1 #f) '(1 0))", "#f")
        self.assertShows("(equal? '(1 #f) (list 1 #f))", "#t")
        self.assertShows("(equal? '(a . #t) '(a . 1))", "#f")
        self.run_lisp("(defstruct flag value)")
        self.assertShows("(equal? (make-flag :value #f) (make-flag :value 0))", "#f")
        self.assertShows("(equal? (make-flag :value #f) (make-flag :value #f))", "#t")

    def test_member_assoc_and_case(self):
        self.assertShows("(member 0 '(#f 1 0))", "(0)")
        self.assertShows("(member #f '(0 #f))", "(#f)")
        self.assertShows("(assoc 1 (list (cons #t 'a) (cons 1 'b)))", "(1 . b)")
        self.assertShows("(case #f ((0) 'zero) (else 'other))", "other")

    def test_comparisons_reject_booleans(self):
        self.assertLispError("(= #f 0)", "=: #f isn't a number -- to test for #t or #f, use eq?")
        self.assertLispError("(< #t 2)", "<: #t isn't a number")
        self.assertLispError("(> #(1 2) #f)", ">: #f isn't a number")

    def test_booleans_cannot_be_hash_table_keys(self):
        self.run_lisp("(define h (make-hash-table)) (hash-table-set! h 1 'one)")
        self.assertLispError("(hash-table-set! h #t 'yes)", "hash-table-set!: #t and #f can't be hash-table keys")
        self.assertLispError("(hash-table-ref h #t)", "hash-table-ref: #t and #f can't be hash-table keys")
        self.assertShows("(hash-table-ref h 1)", "one")


class TestCxrAndPositions(LispTestCase):
    """cadr, caar, ... and first, second, third, fourth, rest."""

    def test_every_combination_up_to_four_letters_exists(self):
        names = lisp_builtins.cxr_names()
        self.assertEqual(len(names), 28)
        self.assertIn("cddddr", names)
        for name in names:
            self.assertIn(lisp_core.Symbol(name), self.env)

    def test_what_they_do(self):
        self.assertShows("(cadr '(1 2 3))", "2")
        self.assertShows("(caddr '(1 2 3))", "3")
        self.assertShows("(caar '((1 2) 3))", "1")
        self.assertShows("(cdar '((1 2) 3))", "(2)")
        self.assertShows("(cddr '(1 2 3))", "(3)")
        self.assertShows("(cadddr '(1 2 3 4))", "4")
        self.assertShows("(caddar '((1 2 3)))", "3")
        self.assertShows("(map cadr '((a 1) (b 2)))", "(1 2)")

    def test_first_to_fourth_and_rest(self):
        self.assertShows("(list (first '(a b c d)) (second '(a b c d)) (third '(a b c d)) (fourth '(a b c d)))",
                         "(a b c d)")
        self.assertShows("(rest '(a b c))", "(b c)")

    def test_asking_for_a_part_that_isnt_there(self):
        self.assertLispError("(cadr '(1))", "cadr: (1) doesn't have that part -- it would take the car of ()")
        self.assertLispError("(third '(a b))", "third: (a b) doesn't have that part")
        self.assertLispError("(first 5)", "first: 5 doesn't have that part -- it would take the car of 5")


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

    def test_string_join(self):
        self.assertShows('(string-join (list "a" "b" "c") ", ")', '"a, b, c"')
        self.assertShows("(string-join '(i am 42))", '"i am 42"')     # symbols and numbers as display shows them
        self.assertShows('(string-join (vector 1 2) "+")', '"1+2"')
        self.assertShows("(string-join '())", '""')

    def test_read_line_returns_the_typed_line_after_the_prompt(self):
        with mock.patch("builtins.input", return_value="hello there") as fake_input:
            self.assertShows('(read-line "You: ")', '"hello there"')
        fake_input.assert_called_once_with("You: ")

    def test_read_line_returns_false_at_the_end_of_the_input(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertShows("(read-line)", "#f")


class TestRegularExpressions(LispTestCase):
    """lisp_regex.py: regex-search, regex-match, regex-find-all,
    regex-replace, regex-split, and regex-quote."""

    def test_search_gives_the_match_and_its_groups(self):
        self.assertShows('(regex-search "(\\d+)-(\\d+)" "pages 12-34 and 56-78")', '("12-34" "12" "34")')
        self.assertShows('(regex-search "x(y)?z" "xz")', '("xz" ())')
        self.assertShows('(regex-search "\\d+" "no digits")', "#f")

    def test_match_must_match_the_whole_string(self):
        self.assertShows('(regex-match "\\d{4}-\\d{2}-\\d{2}" "2026-09-29")', '("2026-09-29")')
        self.assertShows('(regex-match "\\d+" "12a")', "#f")

    def test_find_all(self):
        self.assertShows('(regex-find-all "\\d+" "a1 b22 c333")', '("1" "22" "333")')
        self.assertShows('(regex-find-all "(\\w)\\d" "a1 b2")', '("a" "b")')
        self.assertShows('(regex-find-all "(\\w)(\\d)" "a1 b2")', '(("a" "1") ("b" "2"))')

    def test_replace(self):
        self.assertShows('(regex-replace "\\s+" "too   many    spaces" " ")', '"too many spaces"')
        self.assertShows('(regex-replace "(\\w+)@(\\w+)" "joe@example" "\\2 at \\1")', '"example at joe"')
        self.assertShows('(regex-replace "a" "banana" "o" 2)', '"bonona"')
        self.assertShows('(regex-replace "\\d+" "a1 b22" (lambda (m) (* 2 (string->number (car m)))))', '"a2 b44"')

    def test_split_and_quote(self):
        self.assertShows('(regex-split "[,;]\\s*" "a, b;c")', '("a" "b" "c")')
        self.assertShows('(regex-quote "3.5+x")', '"3\\\\.5\\\\+x"')
        self.assertShows('(regex-search (regex-quote "3.5+x") "y = 3.5+x")', '("3.5+x")')

    def test_flags_go_in_the_pattern(self):
        self.assertShows('(regex-search "(?i)hello" "Say HELLO")', '("HELLO")')

    def test_a_bad_pattern(self):
        self.assertLispError('(regex-search "(" "x")', 'regex-search: "(" isn\'t a valid regular expression')

    def test_a_backslash_before_an_ordinary_character_is_kept(self):
        self.assertEqual(self.run_lisp('"\\d"'), "\\d")          # so "\d+" is the pattern \d+
        self.assertEqual(self.run_lisp('"\\\\d"'), "\\d")      # and "\\d" too
        self.assertEqual(self.run_lisp('"a\\tb"'), "a\tb")       # \t is still a tab


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

    def test_an_index_out_of_range_is_an_error(self):
        self.assertLispError("(vector-ref #(1 2 3) 10)", "vector-ref: index 10 is out of range -- the vector has 3 elements")
        self.assertLispError("(vector-ref #(1 2 3) -1)", "index -1 is out of range")
        self.assertLispError("(vector-set! (vector 1 2) 2 0)", "vector-set!: index 2 is out of range")
        self.assertLispError("(vector-ref #(1 2 3) 1.5)", "the index must be a whole number")

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
        self.run_lisp("(define (same-ignoring-case? a b) (string=? (string-downcase a) (string-downcase b)))")

    def test_looking_at_a_table(self):
        self.assertShows("(table-column-names loans)", '("id" "month" "state" "balance" "rate")')
        self.assertShows('(table-column loans "balance")', "#(100 90 200 195 50)")
        self.assertShows("(table-row-count loans)", "5")
        self.assertShows('(row-ref (table-row loans 2) "state")', '"NY"')
        self.assertShows('(table-column (table-head loans 2) "id")', '#("a" "a")')
        self.assertShows('(table-column (table-slice loans 3) "id")', '#("b" "c")')
        self.assertShows('(table-column (table-tail loans 2) "id")', '#("b" "c")')
        self.assertShows('(table-column (table-tail loans) "id")', '#("a" "a" "b" "b" "c")')     # fewer than 10
        self.assertShows('(table-row-count (table-tail loans 0))', "0")

    def test_with_columns(self):
        self.assertShows("(with-columns (balance rate) loans (vector-weighted-mean rate balance))",
                         "5.4602272727272725")              # the missing rate is skipped
        self.assertShows('(with-columns ((amount "balance") id) loans (list (vector-ref id 2) (vector-sum amount)))',
                         '("b" 635)')
        self.assertShows('(with-columns (SP500) (make-table "SP500" #(1 2)) SP500)', "#(1 2)")      # case kept
        self.run_lisp('(define prices (make-table "date" (vector (date 2024 1 2) (date 2024 1 3)) "close" #(100 104)))')
        self.assertShows('(with-columns ((day "date") close) prices (vector-select close (>= day (date 2024 1 3))))',
                         "#(104)")                          # renamed, so the date function still works
        self.run_lisp("(define made 0)")
        self.run_lisp("(define (get-loans) (set! made (+ made 1)) loans)")
        self.assertShows("(with-columns (id month balance) (get-loans) (set! made (+ made 10)) (vector-sum month))", "7")
        self.assertShows("made", "11")                      # the table expression ran once; every body form ran
        self.assertLispError("(with-columns (balance) loans balance) balance", "unbound")   # local to the body
        self.assertLispError("(with-columns (balanse) loans balanse)", "no column named 'balanse' (the columns are:")
        self.assertLispError("(with-columns ((amount balance)) loans amount)",
                             'each column must be a name, or (variable "column"), not (amount balance)')
        self.assertLispError("(with-columns balance loans balance)", "expected (with-columns (column...) table body...)")
        self.assertIsInstance(self.env[lisp_core.Symbol("with-columns")], lisp_core.Macro)

    def test_drawdowns(self):
        self.run_lisp("(define dd-dates (vector (date 2020 1 1) (date 2020 1 2) (date 2020 1 3) (date 2020 1 4)"
                      " (date 2020 1 5) (date 2020 1 6) (date 2020 1 7) (date 2020 1 8)))")
        self.run_lisp("(define dd (vector-drawdowns dd-dates #(100 95 85 88 80 101 120 100) 10))")
        self.assertShows("(table-row-count dd)", "2")
        self.assertShows('(table-column dd "peak")', "#(100.0 120.0)")
        self.assertShows('(table-column dd "below-date")', "#(2020-01-03 2020-01-08)")
        self.assertShows('(table-column dd "trough-date")', "#(2020-01-05 2020-01-08)")
        self.assertShows('(table-column dd "trough")', "#(80.0 100.0)")
        self.assertAlmostEqual(float(self.run_lisp('(vector-ref (table-column dd "drop-pct") 1)')), 100 / 6, places=4)
        self.assertShows('(table-column dd "recovery-date")', "#(2020-01-06 ())")     # the second hasn't recovered
        self.assertShows("(table-row-count (vector-drawdowns dd-dates #(100 95 85 88 80 101 120 100) 25))", "0")
        self.assertShows("(table-row-count (vector-drawdowns #(1 2 3) #(100 nan 85) 10))", "1")   # NaN skipped
        self.assertLispError("(vector-drawdowns #(1 2) #(1 2 3) 10)", "dates has 2 elements but values has 3")
        self.assertLispError("(vector-drawdowns #(1 2) #(100 -5) 10)", "must be above 0")

    def test_where_with_key_and_test(self):
        self.assertShows('(table-column (table-where loans "state" "ny" :key string-downcase) "balance")', "#(200 195)")
        self.assertShows('(table-column (table-where loans "id" (list "A" "C") :key string-downcase) "balance")',
                         "#(100 90 50)")
        self.assertShows('(table-column (table-where loans "state" "ny" :test same-ignoring-case?) "balance")',
                         "#(200 195)")
        self.assertShows('(table-column (table-where loans "rate" 6 :key floor) "id")', '#("a" "a")')   # a missing rate matches nothing
        # the test is given the value, then the cell
        self.assertShows('(table-column (table-where loans "balance" 150 :test (lambda (value cell) (> cell value))) "id")',
                         '#("b" "b")')
        # and what the key made of each, with both given
        self.assertShows('(table-column (table-where loans "state" "Nevada" :key (lambda (s) (substring s 0 1))'
                         ' :test string=?) "balance")', "#(200 195)")
        self.assertLispError('(table-where loans "state" "NY" :test 5)', ":test must be a procedure of two values")
        self.assertLispError('(table-where loans "state" "NY" :key "downcase")', ":key must be a procedure of one value")
        self.assertLispError('(table-where loans "state" "NY" :tset string=?)', ":tset isn't an option -- the options are :key, :test")
        self.assertLispError('(table-where loans "state" "NY" :key (lambda (s) (list s)))', ":key must return a number, string, or date")
        # the key is applied once to each distinct value, not once to each row
        self.run_lisp("(define calls 0)")
        self.run_lisp("(define (counting-downcase s) (set! calls (+ calls 1)) (string-downcase s))")
        self.run_lisp('(table-where loans "state" "ny" :key counting-downcase)')
        self.assertShows("calls", "3")                      # "ny", and the column's two distinct values, CA and NY

    def test_rows_where_a_column_holds_a_value(self):
        self.assertShows('(table-column (table-where loans "state" "NY") "balance")', "#(200 195)")
        self.assertShows('(table-column (table-where loans "id" (list "a" "c")) "balance")', "#(100 90 50)")
        self.assertShows('(table-column (table-where loans "rate" 7.25) "id")', '#("c")')          # a decimal
        self.assertShows('(table-row-count (table-where loans "state" "TX"))', "0")
        self.assertShows('(= (table-column loans "state") "CA")', "#(1 1 0 0 1)")           # text, element by element
        self.assertShows("(table? loans)", "#t")
        self.assertShows("(table? (list 1))", "#f")
        self.assertLispError('(table-column loans "nope")', "no column named")
        self.assertLispError("(table-row loans 99)", "table-row: there's no row 99 -- the table has 5 rows")
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
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'bogus \"rate\")))",
                             "table-group-by: bogus isn't a summary")
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'weighted-mode \"rate\")))",
                             "table-group-by: weighted-mode needs a weight column")

    def test_group_by_the_other_statistics(self):
        self.assertShows("(table-group-by loans \"state\" (list (list \"id\" 'representative \"id\")"
                         " (list \"most\" 'weighted-mode \"id\" \"balance\")"
                         " (list \"wm\" 'weighted-median \"balance\" \"balance\")"
                         " (list \"p90\" '(percentile 90) \"balance\")))",
                         '(("state" . #("CA" "NY")) ("id" . #("a" "b")) ("most" . #("a" "b"))'
                         ' ("wm" . #(90.0 200.0)) ("p90" . #(98.0 199.5)))')
        self.assertLispError("(table-group-by loans \"state\" (list (list \"x\" 'weighted-mean \"rate\")))", "weight column")

    def test_group_by_with_key_and_test(self):
        self.run_lisp('(define names (make-table "name" (vector "b" "A" "a" "B" "c") "v" #(1 2 3 4 5)))')
        aggregations = ('(list (list "total" (quote sum) "v") (list "first" (quote first) "v")'
                        ' (list "last" (quote last) "v"))')
        # :key -- rows whose keyed values are equal share a group, which shows the keyed value;
        # each group's rows stay in the table's order (so "B" comes after "b" in the table, but is the last)
        self.assertShows('(table-group-by names "name" %s :key string-downcase)' % aggregations,
                         '(("name" . #("a" "b" "c")) ("total" . #(5 5 5)) ("first" . #(2 1 5)) ("last" . #(3 4 5)))')
        # :test -- a group shows its first key value in sorted order
        self.assertShows('(table-group-by names "name" %s :test same-ignoring-case?)' % aggregations,
                         '(("name" . #("A" "B" "c")) ("total" . #(5 5 5)) ("first" . #(2 1 5)) ("last" . #(3 4 5)))')
        # with several key columns, every one must match
        self.run_lisp('(define two-keys (make-table "name" (vector "A" "a" "A" "b") "m" #(1 1 2 1)))')
        self.assertShows('(table-column (table-group-by two-keys (list "name" "m") (list (list "n" (quote count)))'
                         ' :test (lambda (a b) (if (string? a) (same-ignoring-case? a b) (= a b)))) "n")', "#(2 1 1)")
        self.assertShows('(table-column (table-group-by (table-head names 0) "name" (list (list "n" (quote count)))'
                         ' :test same-ignoring-case?) "n")', "#()")
        self.assertLispError('(table-group-by names "name" %s :test 5)' % aggregations, ":test must be a procedure")

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

    def test_join_with_key(self):
        self.run_lisp("""
          (define holdings (make-table "name" (vector "Apple Inc." "BROWN-FORMAN CORP" "Microsoft" "Tesla")
                                       "weight" #(7.25 0.5 5.8 1.2)))
          (define industries (make-table "name" (vector "APPLE INC" "brown forman corp" "microsoft" "Nvidia")
                                         "industry" (vector "Tech" "Beverages" "Tech" "Chips")))
          (define (plain s) (string-downcase (regex-replace "[.,]" (regex-replace "-" s " ") "")))""")
        self.assertShows('(table-column (table-join holdings industries "name") "industry")', "#()")
        self.assertShows('(table-column (table-join holdings industries "name" :key string-downcase) "industry")',
                         '#("Tech")')                       # only Microsoft differs from its twin in just its case
        self.assertShows('(table-column (table-join holdings industries "name" :key plain) "industry")',
                         '#("Tech" "Beverages" "Tech")')
        self.assertShows('(table-column (table-join holdings industries "name" :key plain) "name")',
                         '#("Apple Inc." "BROWN-FORMAN CORP" "Microsoft")')    # the left table's own key values
        self.assertShows("(table-column (table-join holdings industries \"name\" 'left :key plain) \"industry\")",
                         '#("Tech" "Beverages" "Tech" ())')
        # numbers, with a key that makes them match
        self.assertShows('(table-column (table-join (make-table "x" #(1 2 3)) (make-table "x" #(11 12 20) "j" #(7 8 9)) "x"'
                         ' :key (lambda (n) (mod n 10))) "j")', "#(7 8)")
        # with several key columns, every one must match
        self.run_lisp('(define a (make-table "k" (vector "x" "x" "y") "m" #(1 2 1) "n" #(1 2 3)))')
        self.run_lisp('(define b (make-table "k" (vector "X" "X" "Y") "m" #(1 2 2) "v" #(10 20 30)))')
        self.assertShows('(table-column (table-join a b (list "k" "m") :key (lambda (x) (if (string? x) (string-downcase x) x))) "v")',
                         "#(10 20)")
        self.assertLispError('(table-join holdings industries "name" :key 5)', ":key must be a procedure of one value")
        self.assertLispError('(table-join holdings industries "name" :key list)', ":key must return a number, string, or date")

    def test_join_with_test(self):
        self.run_lisp('(define left (make-table "k" (vector "x" "X" "y" "z") "n" #(1 2 3 4)))')
        self.run_lisp('(define right (make-table "k" (vector "X" "x" "Y") "v" #(10 20 30)))')
        # each left row gets the right rows that match it, in the left table's order and then the right's
        self.assertShows('(table-column (table-join left right "k" :test same-ignoring-case?) "v")', "#(10 20 10 20 30)")
        self.assertShows('(table-column (table-join left right "k" :test same-ignoring-case?) "k")', '#("x" "x" "X" "X" "y")')
        self.assertShows("(table-column (table-join left right \"k\" 'left :test same-ignoring-case?) \"v\")",
                         "#(10.0 20.0 10.0 20.0 30.0 nan)")
        # the test is given the left value, then the right
        self.assertShows('(table-column (table-join (make-table "k" #(1 5)) (make-table "k" #(3 4) "v" #(30 40)) "k"'
                         ' :test (lambda (left right) (< left right))) "v")', "#(30 40)")
        # numbers that are close; a decimal such as 4.01 reaches the test as 4.01
        self.assertShows('(table-column (table-join (make-table "x" (vector 4.01 5.5)) (make-table "x" (vector 4.0 5.49) "j" #(7 8))'
                         ' "x" :test (lambda (a b) (< (abs (- a b)) 0.05))) "j")', "#(7 8)")
        # with several key columns, every one must match
        self.run_lisp('(define a (make-table "k" (vector "x" "x" "y") "m" #(1 2 1) "n" #(1 2 3)))')
        self.run_lisp('(define b (make-table "k" (vector "X" "X" "Y") "m" #(1 2 2) "v" #(10 20 30)))')
        self.assertShows('(table-column (table-join a b (list "k" "m") :test (lambda (p q) (if (string? p) (same-ignoring-case? p q) (= p q)))) "v")',
                         "#(10 20)")
        # after :key, the test is given what the key made
        self.assertShows('(table-column (table-join (make-table "k" (vector "Ab" "cD")) (make-table "k" (vector "AB " "cd") "v" #(1 2))'
                         ' "k" :key string-downcase :test (lambda (a b) (string-starts-with? b a))) "v")', "#(1 2)")
        # no rows on one side
        self.assertShows('(table-row-count (table-join (table-head left 0) right "k" :test same-ignoring-case?))', "0")
        self.assertShows('(table-row-count (table-join left (table-head right 0) "k" :test same-ignoring-case?))', "0")
        self.assertShows("(table-column (table-join left (table-head right 0) \"k\" 'left :test same-ignoring-case?) \"v\")",
                         "#(nan nan nan nan)")
        self.assertLispError('(table-join left right "k" :test 5)', ":test must be a procedure of two values")
        self.assertLispError('(table-join left right "k" :test)', "after the first arguments come :name value pairs")
        self.assertLispError("(table-join left right \"k\" 'outer :test same-ignoring-case?)", "how must be")

    def test_join_with_test_applies_it_to_distinct_key_values(self):
        # loans has 2 distinct months and so does rates: 2 x 2 = 4 calls, not 5 x 2 = 10
        self.run_lisp('(define rates (make-table "month" #(1 2) "mkt" #(6.5 6.25)))')
        self.run_lisp("(define calls 0)")
        self.run_lisp("(define (counting-equal a b) (set! calls (+ calls 1)) (= a b))")
        self.assertShows('(table-column (table-join loans rates "month" :test counting-equal) "mkt")', "#(6.5 6.25 6.5 6.25 6.5)")
        self.assertShows("calls", "4")

    def test_a_missing_key_never_reaches_key_or_test(self):
        # the missing ones would make string-downcase and same-ignoring-case? fail; a missing key matches only another
        self.run_lisp("""
          (define with-missing (table-join (make-table "n" #(1 2 3)) (make-table "n" #(1 3) "k" (vector "x" "y")) "n" (quote left)))
          (define other-missing (table-join (make-table "m" #(1 2)) (make-table "m" #(1) "k" (vector "X")) "m" (quote left)))""")
        self.assertShows('(table-column with-missing "k")', '#("x" () "y")')
        self.assertShows('(table-column (table-join with-missing other-missing "k" (quote left) :key string-downcase) "m")',
                         "#(1.0 2.0 nan)")
        self.assertShows('(table-column (table-join with-missing other-missing "k" (quote left) :test same-ignoring-case?) "m")',
                         "#(1.0 2.0 nan)")
        self.assertShows('(table-column (table-where with-missing "k" "X" :key string-downcase) "n")', "#(1)")
        self.assertShows('(table-column (table-group-by with-missing "k" (list (list "rows" (quote count))) :key string-upcase) "k")',
                         '#("X" "Y" ())')

    def test_describe(self):
        self.run_lisp("(define d (table-describe loans))")
        self.assertShows('(table-column d "column")', '#("month" "balance" "rate")')
        self.assertShows('(table-column d "count")', "#(5 5 4)")
        self.assertShows('(table-column d "max")', "#(2.0 200.0 7.25)")


class TestTableRows(LispTestCase):
    """A table seen a row at a time: table-rows, table-row, row-ref, and
    table-from-rows."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""(define t (make-table "id" (vector "a" "b" "c")
                                             "balance" #(100 90 200)
                                             "rate" (vector 6.0 nan 7.5)))""")

    def test_table_rows_gives_one_row_per_table_row(self):
        self.assertShows("(length (table-rows t))", "3")
        self.assertShows("(car (table-rows t))", '#S(row :id "a" :balance 100 :rate 6.0)')

    def test_a_row_is_a_struct(self):
        self.assertShows("(struct? (table-row t 0))", "#t")
        self.assertShows("(struct-ref (table-row t 0) 'balance)", "100")

    def test_row_ref_takes_a_string_or_a_symbol(self):
        self.assertShows('(row-ref (table-row t 1) "id")', '"b"')
        self.assertShows("(row-ref (table-row t 1) 'balance)", "90")
        self.assertShows('(row-ref (table-row t 1) "rate")', "nan")         # a missing value
        self.assertLispError('(row-ref (table-row t 1) "nope")',
                             "row-ref: the row has no column nope -- its columns are id, balance, rate")
        self.assertLispError('(row-ref 5 "id")', "row-ref: not a row: 5")

    def test_with_struct_makes_each_column_a_variable(self):
        self.assertShows("(with-struct (table-row t 2) (list id (* balance 2)))", '("c" 400)')

    def test_filtering_rows_with_a_predicate(self):
        self.run_lisp("(define big (filter (lambda (r) (with-struct r (> balance 95))) (table-rows t)))")
        self.assertShows("(map (lambda (r) (row-ref r 'id)) big)", '("a" "c")')

    def test_table_row_checks_the_row_number(self):
        self.assertLispError("(table-row t 3)", "table-row: there's no row 3 -- the table has 3 rows")
        self.assertLispError("(table-row t 1.5)", "there's no row 1.5")

    def test_rows_back_into_a_table(self):
        self.assertShows("(table-from-rows (table-rows t))",
                         '(("id" . #("a" "b" "c")) ("balance" . #(100 90 200)) ("rate" . #(6.0 nan 7.5)))')
        self.assertShows("(table-from-rows (table-rows t) '(\"balance\" \"id\"))",
                         '(("balance" . #(100 90 200)) ("id" . #("a" "b" "c")))')

    def test_a_table_from_lists(self):
        self.assertShows("""(table-from-rows (list (list "x" 1 "2024-01-31") (list "y" '() "2024-02-29"))
                                             (list "name" "n" "day"))""",
                         '(("name" . #("x" "y")) ("n" . #(1.0 nan)) ("day" . #(2024-01-31 2024-02-29)))')

    def test_hash_tables_such_as_json_objects_become_rows(self):
        self.run_lisp("""
          (define a (make-hash-table))
          (hash-table-set! a "symbol" "SPY")
          (hash-table-set! a "bid" 765.5)
          (hash-table-set! a "is-etf" #t)
          (hash-table-set! a "tags" (list 1 2))           ; a list: left out
          (define b (make-hash-table))
          (hash-table-set! b "symbol" "BRK/B")
          (hash-table-set! b "is-etf" #f)
          (hash-table-set! b "listed" "1996-05-09")""")
        self.assertShows("(table-from-rows (list a b))",
                         '(("symbol" . #("SPY" "BRK/B")) ("bid" . #(765.5 nan)) ("is-etf" . #(1 0)) '
                         '("listed" . #(() 1996-05-09)))')
        self.assertShows('(table-from-rows (list a b) (list "bid" "symbol"))',
                         '(("bid" . #(765.5 nan)) ("symbol" . #("SPY" "BRK/B")))')
        self.assertLispError("(table-from-rows (list a 5))", "every row must be")

    def test_table_from_rows_errors(self):
        self.assertLispError("(table-from-rows (list (list 1 2)))", "give the column names")
        self.assertLispError("(table-from-rows (list (list 1 2)) (list \"a\"))",
                             "the row (1 2) has 2 values, but there are 1 column names")
        self.assertLispError("(table-from-rows (list (list #t)) (list \"a\"))",
                             "a table holds numbers, strings, and dates, not #t (in column a)")
        self.assertLispError("(table-from-rows (list 5) (list \"a\"))", "a row must be a row")

    def test_no_rows(self):
        self.assertShows("(table-from-rows '() (list \"a\"))", '(("a" . #()))')
        self.assertShows("(table-rows (table-filter t (> (table-column t \"balance\") 1000)))", "()")


class TestPlotChart(LispTestCase):
    """plot-chart: several (X, Y) series on one X axis, each with symbols,
    a line, or bars."""

    def setUp(self):
        super().setUp()
        self.specs = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)

    def drawn(self, src):
        """The axes plot-chart's chart is drawn on (with matplotlib, off screen)."""
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.run_lisp(src)
        self.fig = lisp_charts.Figure()
        lisp_charts.FigureCanvasAgg(self.fig)
        ax = self.fig.add_subplot(111)
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        return ax

    def legend_texts(self):
        legends = [a.get_legend() for a in self.fig.axes if a.get_legend()]
        self.assertEqual(len(legends), 1)
        return [t.get_text() for t in legends[0].get_texts()]

    def test_a_fitted_line_follows_its_series(self):
        self.run_lisp('(plot-chart (list (list "y" #(1 2 3 4) #(3 5 7 9) :symbol #t :fit "linear")))')
        data, fit = self.specs[-1]["series"]
        self.assertEqual(fit["label"], "y, linear fit")
        self.assertEqual((fit["x"], fit["line"], fit["symbol"]), ([1.0, 4.0], "dashed", None))
        np.testing.assert_allclose(fit["y"], [3.0, 9.0])          # y = 2x + 1
        self.assertIsNone(data["line"])                           # (the series itself is only symbols)

    def test_a_least_absolute_deviation_fit_isnt_pulled_by_an_outlier(self):
        self.run_lisp('(plot-chart (list (list "y" #(1 2 3 4 5) #(3 5 7 9 100) :symbol #t :fit "lad")))')
        fit = self.specs[-1]["series"][1]
        self.assertEqual(fit["label"], "y, lad fit")
        np.testing.assert_allclose(fit["y"], [3.0, 11.0], atol=1e-6)   # y = 2x + 1, despite the 100

    def test_a_logistic_fit_is_an_s_shaped_curve(self):
        self.run_lisp('(plot-chart (list (list "p" #(1 2 3 4 5 6) #(0 0 1 0 1 1) :symbol #t :fit "logistic")))')
        fit = self.specs[-1]["series"][1]
        self.assertEqual(len(fit["x"]), 100)
        self.assertTrue(all(0 < y < 1 for y in fit["y"]))
        self.assertEqual(fit["y"], sorted(fit["y"]))                # rising, for these

    def test_a_fit_against_dates_and_what_fit_wont_take(self):
        self.run_lisp('(plot-chart (list (list "d" (vector (date 2024 1 1) (date 2024 7 1)) #(1 2) :fit "linear")))')
        self.assertEqual(self.specs[-1]["series"][1]["x"], [datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)])
        self.assertLispError('(plot-chart (list (list "y" #(1 2 3) #(1 2 3) :fit "cubic")))', ':fit is "linear", "lad", or "logistic"')
        self.assertLispError('(plot-chart (list (list "y" (vector "a" "b" "c") #(1 2 3) :fit "linear")))',
                             "for X values that are numbers or dates")

    def test_series_and_how_each_is_drawn(self):
        self.run_lisp('(plot-chart (list (list "a" (vector (date 2024 1 1) (date 2024 2 1) (date 2024 3 1))'
                      '                        (vector 1 nan 3))'
                      '                  (list "b" (list (date 2024 1 1)) (list 5) :bars #t :symbol #t'
                      '                        :line "dashed" :color "red" :line-width 3))'
                      '            :title "T" :symbol-size 9)')
        spec = self.specs[-1]
        self.assertEqual((spec["kind"], spec["title"], spec["x_kind"]), ("plot-chart", "T", "date"))
        a, b = spec["series"]
        self.assertEqual(a["x"], [datetime.date(2024, 1, 1), datetime.date(2024, 3, 1)])   # the NaN is left out
        self.assertEqual(a["y"], [1.0, 3.0])
        self.assertEqual((a["line"], a["symbol"], a["bars"]), ("solid", None, False))      # a line, unless told
        self.assertEqual((a["line_width"], a["symbol_size"]), (1.5, 9.0))
        self.assertEqual((b["line"], b["symbol"], b["bars"], b["color"]), ("dashed", "square", True, "red"))
        self.assertEqual(b["line_width"], 3.0)          # #t: the second series gets the second symbol
        self.assertEqual(spec["legend"], "best")

    def test_text_is_categories_in_the_order_they_first_appear(self):
        self.run_lisp('(plot-chart (list (list "a" #("NY" "TX") #(1 2) :bars #t)'
                      '                  (list "b" #("CA" "TX") #(3 4) :symbol "star")) :legend #f)')
        self.assertEqual(self.specs[-1]["categories"], ["NY", "TX", "CA"])
        self.assertIsNone(self.specs[-1]["legend"])

    def test_mistakes(self):
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2)) (list "b" #("x") #(1))))',
                             "the X values must be all dates, all numbers, or all text")
        self.assertLispError('(plot-chart (list (list "a" (list 1 "x") #(1 2))))',
                             "series a's X values are a mix of text and number")
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2 3))))', "has 2 X values but 3 Y values")
        self.assertLispError('(plot-chart (list (list "a" #(1 1) #(1 2) :bars #t)))',
                             "can have only one Y value for each X")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :symbol "hexagon")))', "there's no symbol")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :line "wavy")))', "there's no line style")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :size 3)))', ":size isn't an option")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :bars "piled")', ':bars must be "grouped"')
        self.assertLispError('(plot-chart (list (list "a" #(1))))', "each series is a list (name x y [options])")
        self.assertLispError("(plot-chart '())", "there are no series to plot")

    def test_grouped_bars_sit_side_by_side(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q") #(1 2) :bars #t)'
                        '                  (list "b" #("p" "q") #(3 4) :bars #t)))')
        bars = [(round(p.get_x(), 6), round(p.get_width(), 6), p.get_height()) for p in ax.patches]
        # 0.8 of the room between categories, shared by the two series
        self.assertEqual(bars, [(-0.4, 0.4, 1), (0.6, 0.4, 2), (0.0, 0.4, 3), (1.0, 0.4, 4)])

    def test_stacked_bars_build_up_from_zero_and_down_from_it(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(1 -2) :bars #t)'
                        '                  (list "b" #(1 2) #(3 -1) :bars #t)'
                        '                  (list "c" #(1 2) #(-5 4) :bars #t)) :bars "stacked")')
        bottoms = [(p.get_x() + p.get_width() / 2, p.get_y(), p.get_height()) for p in ax.patches]
        self.assertEqual([(round(x, 6), y, h) for x, y, h in bottoms],
                         [(1, 0, 1), (2, 0, -2),          # a
                          (1, 1, 3), (2, -2, -1),         # b, on top of a (below it, if negative)
                          (1, 0, -5), (2, 0, 4)])         # c: the first below 0 at 1, the first above at 2

    def test_monthly_and_quarterly_dates_share_the_axis(self):
        ax = self.drawn('(plot-chart (list (list "m" (vector (date 2024 1 1) (date 2024 2 1) (date 2024 3 1)'
                        '                                    (date 2024 4 1)) #(1 2 3 4) :symbol "dot")'
                        '                  (list "q" (vector (date 2024 1 1) (date 2024 4 1)) #(5 6) :bars #t)))')
        january, april = [p.get_x() + p.get_width() / 2 for p in ax.patches]
        self.assertAlmostEqual(april - january, 91)                  # days: on a calendar
        self.assertAlmostEqual(ax.patches[0].get_width(), 0.8 * 91)  # the quarterly bars' room, not the months'
        line = ax.get_lines()[0]
        self.assertEqual(list(line.get_xdata())[3], april)

    def test_a_secondary_axis_has_its_own_scale(self):
        ax = self.drawn('(plot-chart (list (list "big" #(1 2 3) #(1000 2000 3000) :bars #t)'
                        '                  (list "small" #(1 2 3) #(0.1 0.2 0.3) :secondary #t))'
                        '            :y-label "dollars" :secondary-label "percent")')
        self.assertEqual(len(self.fig.axes), 2)
        right = self.fig.axes[1]
        for found, expected in zip(right.get_lines()[0].get_ydata(), [0.1, 0.2, 0.3]):
            self.assertAlmostEqual(found, expected, places=6)      # (vectors hold 32-bit numbers)
        self.assertEqual(len(ax.get_lines()), 1)                  # just the line at 0 for the bars
        self.assertEqual((ax.get_ylabel(), right.get_ylabel()), ("dollars", "percent"))
        self.assertEqual(self.legend_texts(), ["big", "small (right)"])       # one legend, in order

    def test_bars_on_both_axes(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(10 20) :bars #t)'
                        '                  (list "b" #(1 2) #(1 2) :bars #t :secondary #t)'
                        '                  (list "c" #(1 2) #(5 5) :line #t)))')
        right = self.fig.axes[1]
        # grouped: side by side, though on two scales
        self.assertEqual([round(p.get_x(), 6) for p in ax.patches], [0.6, 1.6])
        self.assertEqual([round(p.get_x(), 6) for p in right.patches], [1.0, 2.0])
        self.assertGreater(ax.get_zorder(), right.get_zorder())   # so the secondary bars don't hide c's line
        ax = self.drawn('(plot-chart (list (list "a" #(1) #(10) :bars #t) (list "b" #(1) #(1) :bars #t :secondary #t)'
                        '                  (list "c" #(1) #(5) :bars #t)) :bars "stacked")')
        self.assertEqual([p.get_y() for p in ax.patches], [0, 10])               # a, then c on top of it
        self.assertEqual([p.get_y() for p in self.fig.axes[1].patches], [0])     # b: its own stack

    def test_horizontal_charts(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q" "r") #(1 2 3) :bars #t)'
                        '                  (list "b" #("p" "q") #(30 40) :symbol #t :secondary #t))'
                        '            :horizontal #t :x-label "place" :y-label "amount")')
        bars = [(p.get_y() + p.get_height() / 2, round(p.get_height(), 6), p.get_width()) for p in ax.patches]
        self.assertEqual(bars, [(0, 0.8, 1), (1, 0.8, 2), (2, 0.8, 3)])     # going across
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["p", "q", "r"])
        self.assertTrue(ax.yaxis_inverted())                                 # p at the top
        self.assertEqual((ax.get_ylabel(), ax.get_xlabel()), ("place", "amount"))
        top = self.fig.axes[1]
        self.assertEqual(list(top.get_lines()[0].get_xdata()), [30, 40])     # the Y values across the top
        self.assertEqual(self.legend_texts(), ["a", "b (top)"])

    def test_limits_ticks_and_log_scales(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2 3) #(1000 2000 3000) :bars #t)'
                        '                  (list "b" #(1 2 3) #(2 40 900) :secondary #t))'
                        '            :y-min 0 :y-max 4000 :y-ticks (list 0 1500 3000) :secondary-log #t)')
        self.assertEqual(ax.get_ylim(), (0, 4000))
        self.assertEqual(list(ax.get_yticks()), [0, 1500, 3000])
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["0", "1,500", "3,000"])
        right = self.fig.axes[1]
        self.assertEqual(right.get_yscale(), "log")
        low, high = right.get_ylim()
        self.assertEqual(list(right.get_yticks()), lisp_plot_chart.log_ticks(low, high, 8))
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(5 7) :bars #t)) :y-log #t :horizontal #t :y-max 100)')
        self.assertEqual((ax.get_xscale(), ax.get_xlim()[1]), ("log", 100))    # across, when horizontal
        self.assertEqual(ax.get_lines(), [])                                    # no line at 0 on a log scale
        ax = self.drawn('(plot-chart (list (list "a" #(1 2 3) #(0 50 100))) :y-ticks 3)')
        low, high = ax.get_ylim()
        self.assertEqual([t for t in ax.get_yticks() if low <= t <= high], [0, 50, 100])   # about 3, round

    def test_axis_mistakes(self):
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 -2))) :y-log #t)',
                             "series a has values of 0 or less, which a log scale can't show")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :secondary #t)) :secondary-log #t :secondary-min 0)',
                             "a log scale's :secondary-min must be more than 0")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-min 5 :y-max 1)', ":y-min must be less than :y-max")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-ticks 1)', ":y-ticks is about how many ticks")
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(1 -2))) :secondary-log #t)')   # nothing's on that axis

    def test_round_numbers_for_ticks(self):
        self.assertEqual([lisp_plot_chart.tick_text(v) for v in (1500, 0.25, -5.5e-17, 0.30000000000000004, -1250.5)],
                         ["1,500", "0.25", "0", "0.3", "-1,250.5"])
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.assertEqual(lisp_plot_chart.log_ticks(23, 340, 8), [30, 50, 100, 200, 300])        # 1, 2, 3, 5
        self.assertEqual(lisp_plot_chart.log_ticks(0.5, 2000, 8), [1, 3, 10, 30, 100, 300, 1000])
        self.assertEqual(lisp_plot_chart.log_ticks(1, 1e12, 5), [1, 1e3, 1e6, 1e9, 1e12])     # every third power
        self.assertEqual(lisp_plot_chart.log_ticks(130, 335, 8), [150, 200, 250, 300])         # within a decade

    def test_reference_lines_shading_and_notes(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q" "r") #(1 5 3) :bars #t))'
                        '            :y-lines (list 2 (list 4 "target" "red")) :x-lines (list "q")'
                        '            :shade (list (list "q" "r" "late")) :notes (list (list "q" 5 "the most")))')
        lines = [(list(line.get_xdata()), list(line.get_ydata())) for line in ax.get_lines()]
        self.assertIn(([0, 1], [2, 2]), lines)                     # across, at Y = 2 (x in axes fractions)
        self.assertIn(([0, 1], [4, 4]), lines)
        self.assertIn(([1, 1], [0, 1]), lines)                     # up and down, at "q"
        texts = [t.get_text() for t in ax.texts]
        self.assertEqual(texts, ["late", "target", "the most"])
        span = [p for p in ax.patches if p.get_x() == 0.5]           # "q" and "r", whole: 0.5 to 2.5
        self.assertEqual(span[0].get_width(), 2)

    def test_formats_and_x_limits(self):
        ax = self.drawn('(plot-chart (list (list "a" #(0 1000 2000) #(0.05 0.1 0.15)))'
                        '            :y-format "{:.0%}" :y-ticks (list 0.05 0.1) :x-format "${:,.0f}" :x-max 3000)')
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["5%", "10%"])
        self.assertEqual(ax.xaxis.get_major_formatter()(1500, 0), "$1,500")
        self.assertEqual(ax.get_xlim()[1], 3000)
        ax = self.drawn('(plot-chart (list (list "a" (vector (date 2024 1 1) (date 2024 6 1)) #(1 2)))'
                        '            :x-min (date 2023 1 1) :y-format ",d")')
        self.assertEqual(ax.get_xlim()[0], lisp_plot_chart.x_positions(self.specs[-1], [datetime.date(2023, 1, 1)])[0])
        self.assertEqual(ax.yaxis.get_major_formatter()(1234.6, 0), "1,235")       # a whole number, rounded
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-format "{:q}")', "isn't a format for numbers")
        self.assertLispError('(plot-chart (list (list "a" #("p") #(1))) :x-min 1)', ":x-min is for X values that are dates")
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2))) :x-lines (list (date 2024 1 1)))',
                             ":x-lines must be a number, like the chart's X values")
        self.assertLispError('(plot-chart (list (list "a" #("p") #(1))) :x-lines (list "z"))', "the chart has no category")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :shade (list 1 2))', "each :shade entry is a list")

    def test_areas_and_bands(self):
        ax = self.drawn('(plot-chart (list (list "area" #(1 2 3) #(1 3 2) :fill #t)'
                        '                  (list "band" #(1 2 3) #(4 5 6) :fill (list 5 nan 8) :line #t)))')
        area, band = ax.collections
        self.assertEqual(sorted({tuple(v) for v in area.get_paths()[0].vertices}),
                         [(1, 0), (1, 1), (2, 0), (2, 3), (3, 0), (3, 2)])           # down to 0
        self.assertEqual(sorted({tuple(v) for v in band.get_paths()[0].vertices}),
                         [(1, 4), (1, 5), (3, 6), (3, 8)])                           # X = 2 is left out
        self.assertEqual(len(self.specs[-1]["series"][1]["x"]), 2)
        self.assertEqual(self.legend_texts(), ["area", "band"])
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2) :fill #(1))))', "a's :fill has 1 values, for 2")

    def test_values_printed_on_bars_and_points(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q") #(1500 25.5) :bars #t :labels #t)'
                        '                  (list "b" #("p" "q") #(0.25 0.5) :labels "{:.0%}" :secondary #t)))')
        self.assertEqual([t.get_text() for t in ax.texts], ["1,500", "25.5"])
        self.assertEqual([t.get_text() for t in self.fig.axes[1].texts], ["25%", "50%"])

    def test_histograms(self):
        self.run_lisp('(plot-histogram #(1 2 2 3 3 3 nan 9) :bins (list 0 2 4 10))')
        spec = self.specs[-1]
        self.assertEqual(spec["series"][0]["x"], [1.0, 3.0, 7.0])                    # the bins' middles
        self.assertEqual(spec["series"][0]["y"], [1.0, 5.0, 1.0])                    # 2 counts in [2, 4)
        self.assertEqual((spec["bar_width"], spec["legend"], spec["y_axis"]["lines"]), (1.0, None, []))
        self.run_lisp('(plot-histogram (list (list "a" #(1 1 2 2)) (list "b" #(2 2 2 2) :color "red"))'
                      '                :bins 2 :percent #t :title "T")')
        spec = self.specs[-1]
        self.assertEqual([s["y"] for s in spec["series"]], [[50.0, 50.0], [0.0, 100.0]])
        self.assertEqual((spec["series"][1]["color"], spec["title"], spec["legend"]), ("red", "T", "best"))
        self.assertEqual(spec["y_label"], "percent")
        self.assertLispError("(plot-histogram #())", "there are no values to count")
        self.assertLispError('(plot-histogram #(1 2) :bins 0)', ":bins is how many bins there are")

    def test_panels_share_the_x_axis(self):
        ax = self.drawn('(plot-panels (list (list (list (list "a" #(1 2 3) #(1 2 3))) :title "top" :y-log #t)'
                        '                   (list (list (list "b" #(2 3 4) #(5 6 7) :bars #t)'
                        '                               (list "c" #(2 3 4) #(1 1 1) :secondary #t))))'
                        '             :title "Both" :heights (list 3 1) :x-label "x" :shade (list (list 2 3)))')
        spec = self.specs[-1]
        self.assertEqual((spec["height"], spec["heights"]), (6.0, [3.0, 1.0]))
        top, bottom, right = self.fig.axes
        self.assertIs(ax, top)
        self.assertEqual((top.get_title(), top.get_yscale(), bottom.get_xlabel(), top.get_xlabel()),
                         ("top", "log", "x", ""))
        self.assertEqual(top.get_xlim(), bottom.get_xlim())                         # one X axis
        self.assertEqual(self.fig.get_suptitle(), "Both")
        self.assertEqual([len([p for p in a.patches if p.get_x() == 2]) for a in (top, bottom)], [1, 1])  # shaded
        self.assertFalse(any(t.get_visible() and t.get_text() for t in top.get_xticklabels()))
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')                # the GUI's next chart
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        self.assertEqual((self.fig.axes, self.fig.get_suptitle()), ([ax], ""))
        self.assertEqual(ax.get_subplotspec().get_geometry(), (1, 1, 0, 0))

    def test_panel_mistakes_and_summary(self):
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))) :x-min 0)))', ":x-min isn't an option")
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))))) :heights (list 1 2))',
                             ":heights is a list of the panels' heights")
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))))'
                             '                   (list (list (list "b" #("p") #(1))))))', "share one X axis")
        self.run_lisp('(plot-panels (list (list (list (list "a" #(1) #(1))))'
                      '                   (list (list (list "b" #(1) #(1))) :legend "upper left")) :legend #f)')
        self.assertEqual([panel["legend"] for panel in self.specs[-1]["panels"]], [None, "upper left"])
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(plot-panels (list (list (list (list "a" #(1) #(1))) :title "A")'
                      '                   (list (list (list "b" #(1) #(2) :fill #t)))) :title "Two")')
        self.assertEqual(self.printed(), "[chart] Two\n  panel 1: A\n    a: 1 points (line)\n"
                                         "  panel 2:\n    b: 1 points (filled)\n")

    def test_chart_size(self):
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))) :width 9 :height 2.5)')
        self.assertEqual((self.specs[-1]["width"], self.specs[-1]["height"]), (9.0, 2.5))
        self.env[lisp_core.Symbol("names")] = lisp_core.LispVector([lisp_core.LispString("s%d" % i)
                                                                    for i in range(40)])
        self.run_lisp('(plot-chart (list (list "a" names (vector-map (lambda (n) 1) names) :bars #t)) :horizontal #t)')
        self.assertEqual(self.specs[-1]["height"], 1.5 + 0.25 * 40)          # tall enough for 40 labels
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :width 0)', ":width is the chart's width")

    def test_a_new_chart_in_the_same_figure_starts_fresh(self):
        """The GUI draws each chart on the same axes."""
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(3 4) :bars #t :secondary #t)) :horizontal #t)')
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        self.assertEqual(self.fig.axes, [ax])
        self.assertFalse(ax.yaxis_inverted())
        self.assertEqual(ax.get_zorder(), 0)

    def test_the_console_summary_and_saving(self):
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4) :bars #t :symbol #t)'
                      '                  (list "b" #(1 2) #(3 4) :secondary #t)) :title "Two" :width 4 :height 2)')
        self.assertEqual(self.printed(), "[chart] Two\n  a: 2 points (symbols, bars)\n"
                                         "  b: 2 points (line, on the secondary axis)\n")
        if lisp_charts.MATPLOTLIB_AVAILABLE:
            import matplotlib.image
            folder = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, folder, True)
            self.run_lisp('(save-chart "%s" 4 3 50)' % os.path.join(folder, "given.png"))
            self.assertEqual(matplotlib.image.imread(os.path.join(folder, "given.png")).shape[:2], (150, 200))
            self.run_lisp('(save-chart "%s" \'() \'() 50)' % os.path.join(folder, "own.png"))   # the chart's size
            self.assertEqual(matplotlib.image.imread(os.path.join(folder, "own.png")).shape[:2], (100, 200))


def shapefile_zip(records, fields):
    """A zipped shapefile, as the Census's are, for testing: records are
    (rings, values) -- rings a list of closed rings of (x, y) points, or []
    for a record without a shape -- and fields are (name, kind, width)."""
    import struct
    import zipfile
    contents = []
    for rings, _ in records:
        if not rings:
            contents.append(struct.pack("<i", 0))
            continue
        points = [point for ring in rings for point in ring]
        starts = [sum(len(r) for r in rings[:i]) for i in range(len(rings))]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        contents.append(struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(points))
                        + struct.pack("<%di" % len(rings), *starts)
                        + b"".join(struct.pack("<2d", x, y) for x, y in points))
    body = b"".join(struct.pack(">2i", i + 1, len(c) // 2) + c for i, c in enumerate(contents))
    shp = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2) + struct.pack("<2i8d", 1000, 5, *[0.0] * 8) + body
    header_length, record_length = 32 + 32 * len(fields) + 1, 1 + sum(width for _, _, width in fields)
    dbf = struct.pack("<4BIHH20x", 3, 126, 1, 1, len(records), header_length, record_length)
    for name, kind, width in fields:
        dbf += struct.pack("<11sc4xBB14x", name.encode(), kind.encode(), width, 0)
    dbf += b"\r"
    for _, values in records:
        dbf += b" " + b"".join((str(v).ljust(w) if k == "C" else str(v).rjust(w)).encode()
                               for v, (_, k, w) in zip(values, fields))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("cb_test.shp", shp)
        z.writestr("cb_test.dbf", dbf + b"\x1a")
        z.writestr("cb_test.cpg", "UTF-8")
    return archive.getvalue()


def square(lon, lat, size=1.0):
    """A closed ring around a square, clockwise (as a shapefile's outside rings go)."""
    return [(lon, lat), (lon, lat + size), (lon + size, lat + size), (lon + size, lat), (lon, lat)]


class TestMaps(LispTestCase):
    """lisp_maps: reading the Census's shapefiles (made up here, with the
    Census's server played by a fake), the equal-area projection, and
    plot-map."""

    FIELDS = [("STATEFP", "C", 2), ("GEOID", "C", 5), ("NAME", "C", 20), ("ALAND", "N", 14)]
    # Three made-up counties -- two in "state 36" (one with a lake in it), one in 06 -- and a record
    # with no shape.
    RECORDS = [([square(-75, 42, 2), [(-74.5, 42.5), (-73.5, 42.5), (-73.5, 43.5), (-74.5, 43.5), (-74.5, 42.5)]],
                ["36", "36001", "Albany", 5000]),
               ([square(-73, 42)], ["36", "36003", "Bronx", 1500]),
               ([square(-120, 37)], ["06", "06001", "Alameda", 2000]),
               ([], ["06", "06003", "Alpine", ""])]

    def setUp(self):
        super().setUp()
        import lisp_maps
        self.lisp_maps = lisp_maps
        self.specs = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)
        self.urls = []
        archive = shapefile_zip(self.RECORDS, self.FIELDS)

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            self.urls.append(url)
            if "GENZ2026" in url or "GENZ2025" in url:
                raise lisp_core.LispError("%s: %s returned HTTP 404 Not Found" % (who, url))
            return archive
        self.kept = tempfile.mkdtemp()               # where the boundary files are kept, for these tests
        self.addCleanup(shutil.rmtree, self.kept, True)
        for patcher in (mock.patch.object(lisp_maps.lisp_http, "download", fake_download),
                        mock.patch.dict(os.environ, {"LISP_MAPS_DIRECTORY": self.kept})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_reading_a_shapefile(self):
        names, rows, shapes = self.lisp_maps.read_shapefile(shapefile_zip(self.RECORDS, self.FIELDS), "t")
        self.assertEqual(names, ["STATEFP", "GEOID", "NAME", "ALAND"])
        self.assertEqual(rows[0], ["36", "36001", "Albany", 5000])
        self.assertEqual(rows[3][3], None)                                   # a blank number
        self.assertEqual([len(shape.rings) for shape in shapes], [2, 1, 1, 0])
        self.assertEqual(shapes[1].rings[0].tolist(), [list(p) for p in square(-73, 42)])
        self.assertEqual(str(shapes[0]), "#<shape: 2 rings>")
        renamed = shapefile_zip([([square(0, 0)], ["10027"])], [("GEOID20", "C", 5)])
        self.assertEqual(self.lisp_maps.read_shapefile(renamed, "t")[0], ["GEOID"])     # 2020's "20" dropped

    def test_census_shapes(self):
        self.run_lisp('(define c (census-shapes "county"))')
        self.assertShows("(table-column-names c)", '("STATEFP" "GEOID" "NAME" "ALAND" "shape")')
        self.assertShows('(table-column c "GEOID")', '#("36001" "36003" "06001" "06003")')
        self.assertTrue(self.urls[-1].endswith("GENZ2024/shp/cb_2024_us_county_20m.zip"))   # the latest there is
        self.run_lisp('(define ny (census-shapes "county" :state "NY"))')
        self.assertShows('(table-column ny "NAME")', '#("Albany" "Bronx")')
        self.assertTrue(self.urls[-1].endswith("cb_2024_us_county_500k.zip"))   # one state: more detail
        self.run_lisp('(census-shapes "tract" :state 6 :year 2023)')
        self.assertTrue(self.urls[-1].endswith("GENZ2023/shp/cb_2023_06_tract_500k.zip"))
        self.run_lisp('(census-shapes "zip")')
        self.assertTrue(self.urls[-1].endswith("GENZ2020/shp/cb_2020_us_zcta520_500k.zip"))
        self.assertLispError('(census-shapes "tract")', "give :state")
        self.assertLispError('(census-shapes "county" :state "XX")', "isn't a state's postal abbreviation")
        self.assertLispError('(census-shapes "parish")', "the levels are")

    def test_boundary_files_are_kept_for_good(self):
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # 2026 and 2025: none yet; 2024
        self.assertEqual(os.listdir(self.kept), ["cb_2024_us_county_20m.zip"])
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # kept: not downloaded again
        shutil.copy(os.path.join(self.kept, "cb_2024_us_county_20m.zip"),
                    os.path.join(self.kept, "cb_2025_us_county_20m.zip"))
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # the newest kept: 2025's
        self.run_lisp('(census-shapes "county" :year 2023)')
        self.assertTrue(self.urls[-1].endswith("cb_2023_us_county_20m.zip"))
        with open(os.path.join(self.kept, "cb_2023_us_county_20m.zip"), "wb") as f:
            f.write(b"not a zip file")
        self.assertLispError('(census-shapes "county" :year 2023)', "delete it, and it will be downloaded again")
        with mock.patch.dict(os.environ, {"LISP_MAPS_DIRECTORY": ""}):
            self.assertEqual(self.lisp_maps.maps_directory(),
                             os.path.join(os.path.expanduser("~"), ".cache", "morris_lisp", "maps"))

    def test_the_projection_keeps_areas(self):
        """A one-degree square's area on the map is its area on the earth:
        R squared, times its width in radians, times the difference of the
        sines of its latitudes -- wherever it is."""
        R = self.lisp_maps.EARTH_RADIUS_KM
        edge = np.linspace(0, 1, 400)
        for lon, lat, parameters in ((-100, 30, (-96, 37.5, 29.5, 45.5)), (-80, 60, (-96, 37.5, 29.5, 45.5)),
                                     (179.5, 52, (-154, 50, 55, 65))):        # (across the 180th meridian)
            lons = np.concatenate([lon + 0 * edge, lon + edge, lon + 1 + 0 * edge, lon + 1 - edge])
            lats = np.concatenate([lat + edge, lat + 1 + 0 * edge, lat + 1 - edge, lat + 0 * edge])
            x, y = self.lisp_maps.albers(lons, lats, *parameters)
            area = abs(self.lisp_maps.ring_area(np.column_stack([x, y])))
            on_earth = R ** 2 * math.radians(1) * (math.sin(math.radians(lat + 1)) - math.sin(math.radians(lat)))
            self.assertAlmostEqual(area / on_earth, 1, places=5)
        self.assertAlmostEqual(float(self.lisp_maps.longitude_difference(179.8, -154)), -26.2, places=6)  # the short way

    def test_where_places_go_on_a_map_of_the_country(self):
        shape = self.lisp_maps.Shape
        places = {"contiguous": shape([np.array(square(-100, 40))]), "alaska": shape([np.array(square(-150, 62))]),
                  "hawaii": shape([np.array(square(-157, 20, 0.5))]), "puerto rico": shape([np.array(square(-66.5, 18, 0.3))]),
                  "pacific": shape([np.array(square(144.6, 13.3, 0.3))])}                    # Guam
        for region, place in places.items():
            self.assertEqual(self.lisp_maps.place_region(place), region)
        project = self.lisp_maps.map_projection(list(places.values()))
        self.assertIsNone(project(places["pacific"]))                        # not drawn
        alaska = project(places["alaska"])[0]
        center_lon, origin_lat, p1, p2, scale = self.lisp_maps.NATIONAL_PROJECTIONS["alaska"]
        corners = np.array(square(-150, 62))
        own = np.column_stack(self.lisp_maps.albers(corners[:, 0], corners[:, 1], center_lon, origin_lat, p1, p2))
        self.assertAlmostEqual(abs(self.lisp_maps.ring_area(alaska)) / abs(self.lisp_maps.ring_area(own)),
                               0.35 ** 2)                                     # Alaska, at 35% of the scale
        one_state = self.lisp_maps.map_projection([places["contiguous"]])     # a smaller map: fitted to it
        x, y = one_state(places["contiguous"])[0].mean(axis=0)
        self.assertLess(abs(x), 60)                                           # (its middle is near the middle)

    def test_matching_data_to_places(self):
        codes = ["06", "36", "48"]
        self.env[lisp_core.Symbol("data")] = lisp_tables.make_table_value([
            ("fips", lisp_core.LispVector([lisp_core.LispString("36000"), lisp_core.LispString("06000")])),
            ("value", lisp_core.LispVector([5.0, 7.0]))])
        values = self.lisp_maps.values_for_places(None, codes, self.run_lisp("data"), None, "value", "t")
        self.assertEqual(values, [7.0, 5.0, None])                           # BEA's state codes: 36000 is 36
        self.assertEqual(self.lisp_maps.normalized_code(6, 2), "06")
        self.assertEqual(self.lisp_maps.normalized_code(1001.0, 5), "01001")
        self.env[lisp_core.Symbol("twice")] = lisp_tables.make_table_value([
            ("state", lisp_core.LispVector([lisp_core.LispString("36"), lisp_core.LispString("36")])),
            ("county", lisp_core.LispVector([lisp_core.LispString("001"), lisp_core.LispString("001")])),
            ("value", lisp_core.LispVector([1, 2]))])
        with self.assertRaises(lisp_core.LispError) as caught:
            self.lisp_maps.values_for_places(None, ["36001"], self.run_lisp("twice"), lisp_core.list_to_pairs(
                [lisp_core.LispString("state"), lisp_core.LispString("county")]), "value", "t")
        self.assertIn("more than one row for 36001", str(caught.exception))

    def test_a_map_colored_by_values_with_symbols(self):
        self.run_lisp('(define c (census-shapes "county"))'
                      '(define d (make-table "state" #("36" "36" "06") "county" #("001" "003" "001")'
                      '                      "income" #(50000 80000 nan) "people" #(1000 4000 0)))')
        self.run_lisp('(plot-map c :data d :key (list "state" "county") :fill "income" :symbols "people"'
                      '          :format "${:,.0f}" :title "T")')
        spec = self.specs[-1]
        self.assertEqual((spec["kind"], spec["title"], len(spec["places"])), ("map", "T", 3))   # Alpine: no shape
        self.assertEqual(spec["fill"]["values"], [50000.0, 80000.0, None])
        self.assertEqual([p[2] for p in spec["symbols"]["points"]], [1000.0, 4000.0])          # 0: no symbol
        self.assertEqual(spec["symbols"]["legend_values"], [2500.0, 1000.0, 250.0])   # round numbers
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            return
        fig = lisp_charts.Figure()
        lisp_charts.FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        lisp_charts.draw_chart_on_axes(fig, ax, spec)
        places, = ax.collections[:1]
        self.assertEqual(len(places.get_paths()), 3)
        symbols = [c for c in ax.collections if c is not places and len(c.get_sizes()) == 2][0]
        sizes = sorted(symbols.get_sizes())
        self.assertAlmostEqual(sizes[1] / sizes[0], 4.0)                     # areas in proportion to the values
        self.assertEqual(len(fig.axes), 2)                                   # the map, and its color bar
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertEqual(legend, ["no data", "$2,500", "$1,000", "$250"])
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')        # the GUI's next chart
        lisp_charts.draw_chart_on_axes(fig, ax, self.specs[-1])
        self.assertEqual((fig.axes, ax.axison, ax.get_aspect()), ([ax], True, "auto"))

    def test_symbols_on_other_places_and_mistakes(self):
        self.run_lisp('(define c (census-shapes "county"))'
                      '(define d (make-table "GEOID" #("36003" "06001") "n" #(9 5)))')
        self.run_lisp('(plot-map (table-head c 2) :symbols-on c :data d :symbols "n")')    # New York's two
        spec = self.specs[-1]
        self.assertEqual(len(spec["places"]), 2)
        self.assertEqual([value for _, _, value in spec["symbols"]["points"]], [9.0])   # not California's: off the map
        self.assertLispError('(plot-map c :data d :fill "n" :colors "rainbows")', "isn't one of matplotlib's color maps")
        self.assertLispError('(plot-map (make-table "a" #(1)))', "must be a table from census-shapes")
        self.assertLispError('(plot-map c :data (make-table "code" #("1")) :fill "code")', "give :key")
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(define c (census-shapes "county"))'
                      '(plot-map c :data (make-table "GEOID" #("36003") "n" #(9)) :fill "n" :title "M")')
        self.assertEqual(self.printed(), "[map] M\n  3 places, 1 colored by n\n")

    def test_where_a_symbol_goes(self):
        big, small = np.array(square(0, 0, 10), dtype=float), np.array(square(20, 0, 1), dtype=float)
        self.assertEqual(self.lisp_maps.center_of([small, big]).tolist(), [5.0, 5.0])    # the largest piece's middle
        self.assertEqual(self.lisp_maps.round_number_below(217075), 200000)
        self.assertEqual(self.lisp_maps.round_number_below(0.03), 0.025)


class TestDisplayHtml(LispTestCase):
    """display-html: HTML in a notebook, the plain text anywhere else."""

    def test_the_console_gets_the_plain_text(self):
        self.run_lisp('(display-html "<b>bold</b>" "bold")')
        self.assertEqual(self.printed(), "bold\n")

    def test_without_plain_text_the_console_gets_the_html(self):
        self.run_lisp('(display-html "<b>bold</b>")')
        self.assertEqual(self.printed(), "<b>bold</b>\n")

    def test_a_notebook_gets_the_html(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, html=shown.append)
        self.run_lisp('(display-html "<b>bold</b>" "bold")', env)
        self.assertEqual(shown, ["<b>bold</b>"])
        self.assertEqual(self.printed(), "")

    def test_the_notebook_callback_shows_it_as_html(self):
        try:
            import lisp_jupyter
            from IPython.display import HTML
        except ImportError:
            self.skipTest("IPython is not installed")
        with mock.patch.object(lisp_jupyter, "_ipy_display") as fake_display:
            lisp_jupyter._notebook_html("<b>bold</b>")
        shown = fake_display.call_args[0][0]
        self.assertIsInstance(shown, HTML)
        self.assertEqual(shown.data, "<b>bold</b>")

    def test_it_needs_strings(self):
        self.assertLispError("(display-html 5)", "display-html: expected a string for html, got 5")


class TestDisplayTable(LispTestCase):
    """display-table: a table, or a list of rows, with each column's numbers
    laid out by a format spec."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""(define t (make-table "symbol" (vector "SPY C" "SPY|P")
                                             "strike" #(450 455)
                                             "iv" (vector 0.2345 nan)
                                             "volume" #(12345 67)))""")

    def test_the_console_table(self):
        self.run_lisp("(display-table t '((\"strike\" \",.2f\") (\"iv\" \".1%\") (\"volume\" \",\")))")
        self.assertEqual(self.printed(),
                         "symbol  strike     iv  volume\n"
                         "------  ------  -----  ------\n"
                         "SPY C   450.00  23.4%  12,345\n"
                         "SPY|P   455.00             67\n")

    def test_without_formats_numbers_are_shown_as_display_shows_them(self):
        self.run_lisp("(display-table t)")
        self.assertIn("SPY C      450  0.2345   12345", self.printed())

    def test_a_format_may_be_written_as_a_dotted_pair(self):
        self.run_lisp("(display-table t '((\"strike\" . \",.1f\")))")
        self.assertIn("450.0", self.printed())

    def test_a_format_for_a_column_the_table_lacks_is_not_used(self):
        self.run_lisp("(display-table (table-select t \"symbol\") '((\"strike\" \",.2f\")))")
        self.assertEqual(self.printed(), "symbol\n------\nSPY C\nSPY|P\n")

    def test_a_list_of_rows(self):
        self.run_lisp("(display-table (table-rows t) '((\"strike\" \",.2f\")))")
        self.assertIn("SPY C   450.00", self.printed())

    def test_an_empty_table(self):
        self.run_lisp("(display-table '())")
        self.assertEqual(self.printed(), "(an empty table)\n")

    def test_errors(self):
        self.assertLispError("(display-table 5)", "display-table: not a table")
        self.assertLispError("(display-table t '(5))", "each format must be (name spec)")
        self.assertLispError("(display-table t '((\"symbol\" \".2f\")))", "display-table: column symbol: format:")
        self.assertLispError("(display-table t :max-rows -1)", ":max-rows must be a whole number, 0 or more, or #f")
        self.assertLispError("(display-table t :rows 5)", ":rows isn't an option -- the options are :max-rows")

    def test_a_long_table_shows_its_first_rows_and_says_so(self):
        self.run_lisp("(display-table t :max-rows 1)")
        self.assertEqual(self.printed(), "symbol  strike      iv  volume\n"
                                         "------  ------  ------  ------\n"
                                         "SPY C      450  0.2345   12345\n"
                                         "(the first 1 of 2 rows -- :max-rows shows more)\n")

    def test_twenty_rows_unless_max_rows_says_otherwise(self):
        self.run_lisp('(define long (make-table "n" (list->vector (iota 25))))')
        self.run_lisp("(display-table long)")
        self.assertTrue(self.printed().endswith("19\n(the first 20 of 25 rows -- :max-rows shows more)\n"))
        self.out.clear()
        self.run_lisp('(display-table long \'(("n" ",")) :max-rows #f)')         # after formats; #f: every row
        self.assertTrue(self.printed().endswith("\n23\n24\n"), self.printed())
        self.out.clear()
        self.run_lisp("(display-table long :max-rows 0)")
        self.assertEqual(self.printed(), "n\n-\n(the first 0 of 25 rows -- :max-rows shows more)\n")

    def test_a_hidden_column_is_left_out(self):
        self.run_lisp("(display-table t '((\"strike\" hide) (\"iv\" \"hide\") (\"volume\" \",\")))")
        self.assertEqual(self.printed(), "symbol  volume\n------  ------\nSPY C   12,345\nSPY|P       67\n")
        self.out.clear()
        self.run_lisp("(display-table t '((\"symbol\" hide) (\"strike\" hide) (\"iv\" hide) (\"volume\" hide)))")
        self.assertEqual(self.printed(), "(every column is hidden)\n")
        self.assertShows('(table-column-names t)', '("symbol" "strike" "iv" "volume")')      # the table is unchanged

    def test_what_the_table_callback_receives(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, table=shown.append)
        self.run_lisp("(display-table (make-table \"id\" (vector \"a\") \"n\" #(1.5)) '((\"n\" \".2f\")))",
                      env=env)
        self.assertEqual(shown, [[("id", ["a"], "left"), ("n", ["1.50"], "right")]])

    def test_the_markdown_a_notebook_shows(self):
        columns = [("id", ["a", "b|c"], "left"), ("n", ["1.50", ""], "right")]
        self.assertEqual(lisp_builtins.markdown_table(columns),
                         "| id | n |\n|:---|---:|\n| a | 1.50 |\n| b\\|c |  |")

    def test_markdown_characters_in_a_table_are_shown_as_they_are(self):
        """In a notebook, a pair of $ makes a formula -- "revenue ($bn)" and
        "free cash flow ($bn)" in one row turned the text between them into
        one and broke the table -- and * and _ make emphasis. Each is
        backslashed, which Markdown shows as the character itself."""
        columns = [("revenue ($bn)", ["K*sqrt(T)_x"], "left"), ("free cash flow ($bn)", ["<1> `a` ~b~"], "left")]
        self.assertEqual(lisp_builtins.markdown_table(columns).splitlines()[0],
                         "| revenue (\\$bn) | free cash flow (\\$bn) |")
        self.assertEqual(lisp_builtins.markdown_table(columns).splitlines()[2],
                         "| K\\*sqrt(T)\\_x | \\<1\\> \\`a\\` \\~b\\~ |")


class TestSaveVariables(LispTestCase):
    """save-variables and load-variables: variables saved in a JSON file,
    and defined again from it -- here, in a new environment, as in a later
    session."""

    VALUES = """
      (defstruct point x y)
      (define n 42)
      (define rate 0.0625)
      (define missing nan)
      (define big -inf)
      (define name "Pool \\"A\\" \u2014 2024")
      (define flags (list #t #f '()))
      (define sym 'balance)
      (define key :max-rows)
      (define day (date 2024 1 2))
      (define nested (list 1 (list 2 3) (vector 4 5) "six"))
      (define dotted (cons 'a 1))
      (define improper (cons 1 (cons 2 3)))
      (define v-float (vector 1.5 nan 0.1))
      (define v-int #(1 2 300))
      (define v-bits #(1 0 1))
      (define v-text (vector-lag (vector "a" "b" "c")))
      (define v-dates (vector (date 2024 1 2) (date 2024 2 1)))
      (define loans (make-table "id" (vector "a" "b") "balance" #(100.5 90) "start" (vector (date 2020 1 1) (date 2021 6 30))))
      (define pairs (list (cons 'a #(1 2)) (cons 'b #(3 4))))     ; symbols, so not a table
      (define h (make-hash-table))
      (hash-table-set! h "CA" 1)
      (hash-table-set! h 'NY (list 1 2))
      (hash-table-set! h (date 2024 1 1) "new year")
      (define p (make-point :x 1 :y (vector 2 3)))
      (define rows (table-rows loans))"""
    NAMES = ("n rate missing big name flags sym key day nested dotted improper v-float v-int v-bits v-text "
             "v-dates loans pairs h p rows")

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.path = os.path.join(folder, "work.json")
        self.env[lisp_core.Symbol("path")] = lisp_core.LispString(self.path)
        self.later = lisp_builtins.make_global_env(output=self.out.append)       # a later session
        self.later[lisp_core.Symbol("path")] = lisp_core.LispString(self.path)

    def test_every_kind_of_data_comes_back_as_it_was(self):
        self.run_lisp(self.VALUES)
        self.assertShows("(save-variables path %s)" % self.NAMES, "(%s)" % self.NAMES)
        self.run_lisp("(defstruct point x y)", env=self.later)
        names = self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(lisp_core.to_string(names), "(%s)" % self.NAMES)
        for name in self.NAMES.split():
            symbol = lisp_core.Symbol(name)
            self.assertEqual(lisp_core.to_string(self.later[symbol]), lisp_core.to_string(self.env[symbol]), name)
        for name in ("v-float", "v-int", "v-bits", "v-text", "v-dates"):            # stored the same way
            symbol = lisp_core.Symbol(name)
            self.assertEqual(self.later[symbol].items.dtype, self.env[symbol].items.dtype, name)
        self.assertEqual(self.later[lisp_core.Symbol("v-float")].items[2], np.float32(0.1))
        self.assertEqual(self.run_lisp("(list (hash-table-ref h 'NY) (hash-table-ref h (date 2024 1 1)) (point? p)"
                                       " (point-x p) (row-ref (cadr rows) \"start\") (table? loans) (table? pairs))",
                                       env=self.later),
                         self.run_lisp("(list (hash-table-ref h 'NY) (hash-table-ref h (date 2024 1 1)) (point? p)"
                                       " (point-x p) (row-ref (cadr rows) \"start\") (table? loans) (table? pairs))"))

    def test_the_file_is_plain_json(self):
        self.run_lisp(self.VALUES)
        self.run_lisp("(save-variables path missing big sym day loans p)")
        def refuse(constant):
            raise AssertionError("not plain JSON: " + constant)
        with open(self.path, encoding="utf-8") as f:
            document = json.load(f, parse_constant=refuse)
        self.assertEqual((document["format"], document["version"]), ("morris-lisp variables", 1))
        self.assertEqual(document["variables"], {
            "missing": None, "big": {"number": "-inf"}, "sym": {"symbol": "balance"}, "day": {"date": "2024-01-02"},
            "loans": {"table": [["id", ["a", "b"]], ["balance", [100.5, 90.0]],
                                ["start", [{"date": "2020-01-01"}, {"date": "2021-06-30"}]]]},
            "p": {"struct": "point", "slots": {"x": 1, "y": {"vector": [2, 3]}}}})

    def test_load_variables_defines_them_at_the_top_level(self):
        self.run_lisp("(define rate 0.05) (save-variables path rate)")
        self.run_lisp("(define (restore) (load-variables path)) (restore)", env=self.later)
        self.assertShows("rate", "0.05")
        self.assertEqual(self.later[lisp_core.Symbol("rate")], 0.05)

    def test_models_predict_and_report_the_same(self):
        self.run_lisp("""
          (define x (cons "income" #(10 20 30 40 50 60 70 80)))
          (define kind (cons "kind" (vector "own" "rent" "own" "rent" "own" "rent" "own" "rent")))
          (define y (cons "spend" #(9 15 33 38 52 58 74 77)))
          (define linear (linear-regression (list x) y))
          (define lad (lad-regression (list x) y))
          (define logistic (logistic-regression (list x) (cons "default" #(0 0 1 0 1 0 1 1))))
          (define spline (spline-regression (list x kind) y (list 1 'categorical)))""")
        self.run_lisp("(save-variables path linear lad logistic spline)")
        self.run_lisp("(load-variables path)", env=self.later)
        for model in ("linear", "lad", "logistic"):
            for src in ("(model-predict %s (list 45))" % model, "(model-report %s)" % model):
                self.assertEqual(self.run_lisp(src, env=self.later), self.run_lisp(src), src)
        for src in ('(model-predict spline (list 45 "rent"))', "(model-report spline)"):
            self.assertEqual(self.run_lisp(src, env=self.later), self.run_lisp(src), src)
        self.assertIn("kind: categorical -- categories own, rent (baseline own)", self.run_lisp("(model-report spline)"))

    def test_what_cant_be_saved(self):
        self.run_lisp("(define rate 0.05) (save-variables path rate)")
        self.run_lisp("(define (f x) x) (define stuff (list 1 f))")
        self.assertLispError("(save-variables path rate stuff)",
                             "save-variables: can't save stuff: it is or holds #<procedure f>, which isn't data")
        self.run_lisp("(load-variables path)", env=self.later)                   # the earlier file, as it was
        self.assertEqual(self.later[lisp_core.Symbol("rate")], 0.05)
        self.assertLispError("(save-variables path (+ 1 2))", "save-variables: expected the names of variables, not (+ 1 2)")
        self.assertLispError("(save-variables path)",
                             "expected (save-variables path name... [:leave-out-procedures #t]), with at least one name")
        self.assertLispError("(save-variables path nowhere)", "unbound")

    def test_a_structs_procedures_can_be_left_out_and_come_back_as_their_defaults(self):
        tranche = "(defstruct tranche (children ()) (money 0.0) (f (lambda (x) (* x 3))))"
        self.run_lisp(tranche)
        self.run_lisp("(define senior (make-tranche :money 100.0 :children (list (make-tranche :money 40.0))))")
        self.assertLispError("(save-variables path senior)",
                             "can't save senior: it is or holds a tranche whose f slot holds #<procedure>, which "
                             "isn't data -- to leave a struct's procedures out of the file, give save-variables "
                             ":leave-out-procedures #t")
        self.assertShows("(save-variables path senior :leave-out-procedures #t)", "(senior)")
        with open(self.path, encoding="utf-8") as f:
            saved = json.load(f)["variables"]["senior"]
        self.assertEqual(saved["slots"], {"children": [{"struct": "tranche", "slots": {"children": [], "money": 40.0}}],
                                          "money": 100.0})
        self.run_lisp(tranche, env=self.later)
        self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(lisp_core.to_string(self.run_lisp(
            "(list (tranche-money senior) ((tranche-f senior) 2) ((tranche-f (car (tranche-children senior))) 5))",
            env=self.later)), "(100.0 6 15)")

    def test_a_slot_the_file_doesnt_have_gets_its_default_as_make_gives_it(self):
        self.run_lisp("(defstruct loan balance) (define big (make-loan :balance 200000)) (save-variables path big)")
        self.run_lisp("(defstruct loan balance (fee (* balance 0.01)))", env=self.later)   # a slot gained since
        self.run_lisp("(load-variables path)", env=self.later)
        self.assertEqual(self.run_lisp("(loan-fee big)", env=self.later), 2000.0)        # from the saved balance

    def test_leaving_out_procedures_is_only_for_a_structs_slots(self):
        self.run_lisp("(define (f x) x) (define h (make-hash-table)) (hash-table-set! h 'rule f)")
        self.assertLispError("(save-variables path f :leave-out-procedures #t)", "can't save f: it is or holds #<procedure f>")
        self.assertLispError("(save-variables path h :leave-out-procedures #t)", "can't save h: it is or holds #<procedure f>")
        self.assertLispError("(save-variables path h :skip #t)", ":skip isn't an option -- the options are :leave-out-procedures")
        self.assertLispError("(save-variables path :leave-out-procedures #t)", "with at least one name")

    def test_what_cant_be_loaded(self):
        self.run_lisp(self.VALUES)
        self.run_lisp("(save-variables path rate p)")
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_lisp("(load-variables path)", env=self.later)
        self.assertIn("load-variables: can't load p: there's no point struct type -- define it with defstruct first",
                      str(caught.exception))
        self.assertNotIn(lisp_core.Symbol("rate"), self.later)                     # nothing defined
        self.run_lisp("(defstruct point x)", env=self.later)                         # it has lost its y slot
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_lisp("(load-variables path)", env=self.later)
        self.assertIn("can't load p: the saved point has slots a point doesn't have now: y", str(caught.exception))
        with open(self.path, "w") as f:
            f.write('{"rate": 0.05}')
        self.assertLispError("(load-variables path)", "isn't a file save-variables wrote")
        with open(self.path, "w") as f:
            f.write("not JSON")
        self.assertLispError("(load-variables path)", "isn't a JSON file")
        self.assertLispError('(load-variables "/no/such/file.json")', "couldn't read /no/such/file.json")


class TestOptionChainTable(LispTestCase):
    """tastytrade-option-chain's rows become a table (no network needed to
    test that part), and examples/option_chain_example.lsp runs on one."""

    @staticmethod
    def rows():
        def row(symbol, kind, strike, expiration, days, price, iv, volume, oi):
            S = lisp_core.LispString
            bid, ask = round(price - 0.05, 2), round(price + 0.05, 2)
            return [S(symbol), S(kind), strike, S(expiration), days, None, S("SPY"), 655.0,
                    bid, ask, price, price, iv, None, None, volume, oi]
        return [
            row("SPY C660 OCT", "Call", 660.0, "2025-10-17", 19, 9.10, 0.18, 1200, 5000),
            row("SPY C660 NOV", "Call", 660.0, "2025-10-31", 33, 12.40, 0.19, 800, 2500),
            row("SPY C670 NOV", "Call", 670.0, "2025-10-31", 33, 7.25, 0.17, 400, 90),
            row("SPY C670 DEC", "Call", 670.0, "2025-11-21", 54, 10.05, None, 150, 300),
            row("SPY P650 NOV", "Put", 650.0, "2025-10-31", 33, 6.80, 0.23, 950, 4100),
            row("SPY P640 DEC", "Put", 640.0, "2025-11-21", 54, 0.95, 0.26, 70, 800),
            row("SPY P650 DEC", "Put", 650.0, "2025-11-21", 54, 9.30, 0.22, 300, None),
        ]

    def test_the_rows_become_a_table_with_named_columns(self):
        self.env[lisp_core.Symbol("chain")] = lisp_tastytrade.option_chain_table(self.rows())
        self.assertShows("(table-column-names chain)",
                         '("symbol" "type" "strike" "expiration-date" "days-to-expiration" "delivery-month" '
                         '"underlying" "underlying-price" "bid" "ask" "mid" "last-price" "implied-volatility" '
                         '"delta" "vega" "volume" "open-interest")')
        self.assertShows("(table-row-count chain)", "7")
        self.assertShows('(table-column chain "expiration-date")',
                         "#(2025-10-17 2025-10-31 2025-10-31 2025-11-21 2025-10-31 2025-11-21 2025-11-21)")
        self.assertShows('(vector-ref (table-column chain "implied-volatility") 3)', "nan")

    def test_an_empty_chain_is_a_table_with_no_rows(self):
        self.env[lisp_core.Symbol("chain")] = lisp_tastytrade.option_chain_table([])
        self.assertShows("(table-row-count chain)", "0")

    def test_the_option_chain_example_runs(self):
        chain = lisp_tastytrade.option_chain_table(self.rows())
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda *args: chain
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("no-credentials-needed.json")
        lisp_core.run_file(os.path.join(EXAMPLES, "option_chain_example.lsp"), self.env)
        out = self.printed()
        self.assertIn("SPY: 7 options", out)
        # part 2: the calls with 20-60 days and open interest of at least 100, cheapest per day first
        part2 = out.split("cheapest per day first:\n")[1].split("\n\n")[0]
        self.assertEqual([line.split("  ")[0] for line in part2.splitlines()[2:]],
                         ["SPY C670 DEC", "SPY C660 NOV"])
        # part 3: the puts over 20% volatility and $1
        self.assertIn("Puts with implied volatility over 20% and a price over $1: 2", out)
        self.assertIn("  SPY P650 NOV expires 2025-10-31: 6.75 bid, 6.85 ask, at 23.0% volatility", out)
        # part 4: by expiration
        self.assertIn("2025-10-31             3       19.7%          6,690", out)


class FakeTastytrade:
    """A stand-in for tastytrade's API, for testing lisp_tastytrade without
    the network: a session whose requests are answered from `answers`, a
    function (path, params) -> (HTTP status, JSON body). It keeps every
    request it's asked, as (path, params)."""

    class Response:
        def __init__(self, status, body):
            self.status_code = status
            self.body = body

        def json(self):
            if isinstance(self.body, str):
                raise ValueError("not JSON")
            return self.body

    def __init__(self, answers):
        self.answers = answers
        self.requests = []
        fake = self

        class Client:
            async def get(self, path, params=None):
                fake.requests.append((path, dict(params or {})))
                return FakeTastytrade.Response(*fake.answers(path, dict(params or {})))

        class Session:
            _client = Client()

            async def refresh(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def serialize(self):
                return "{}"
        self.session = Session()

    def __enter__(self):
        self.credentials = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.credentials.write('{"client_secret": "x", "refresh_token": "y"}')
        self.credentials.close()
        self.patch = mock.patch.object(lisp_tastytrade, "_tasty_session", lambda path: self.session)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        os.unlink(self.credentials.name)


class TestSecFinancials(LispTestCase):
    """lisp_sec, on a made-up company's facts -- no network. XYZ Corp's fiscal
    year is the calendar year. It reported revenue as Revenues for 2022 and
    as RevenueFromContractWithCustomerExcludingAssessedTax for 2023; restated
    2022's net income in its 2023 10-K; and gave its operating cash flow
    and capital spending, as most companies do, only for the year to date."""

    @staticmethod
    def fact(start, end, value, form, filed, fy, fp, accn):
        if value >= 1000:
            value = int(value)                  # the SEC gives whole dollars as integers
        f = {"end": end, "val": value, "form": form, "filed": filed, "fy": fy, "fp": fp, "accn": accn}
        if start:
            f["start"] = start
        return f

    def company_facts(self):
        F = self.fact
        k22 = ("10-K", "2023-02-15", 2022, "FY", "k22")
        k23 = ("10-K", "2024-02-15", 2023, "FY", "k23")
        q1, q2, q3 = (("10-Q", "2023-05-01", 2023, "Q1", "q1"), ("10-Q", "2023-08-01", 2023, "Q2", "q2"),
                      ("10-Q", "2023-11-01", 2023, "Q3", "q3"))
        usd = lambda *facts: {"label": "", "units": {"USD": list(facts)}}
        per_share = lambda *facts: {"label": "", "units": {"USD/shares": list(facts)}}
        return {"cik": 1234, "entityName": "XYZ Corp", "facts": {"us-gaap": {
            "Revenues": usd(F("2022-01-01", "2022-12-31", 100e6, *k22)),
            "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
                F("2023-01-01", "2023-03-31", 25e6, *q1), F("2023-04-01", "2023-06-30", 30e6, *q2),
                F("2023-07-01", "2023-09-30", 32e6, *q3), F("2023-01-01", "2023-09-30", 87e6, *q3),
                F("2023-01-01", "2023-12-31", 120e6, *k23)),
            "CostOfRevenue": usd(F("2023-01-01", "2023-12-31", 70e6, *k23)),
            "NetIncomeLoss": usd(F("2022-01-01", "2022-12-31", 10e6, *k22),
                                 F("2022-01-01", "2022-12-31", 11e6, *k23),        # restated
                                 F("2023-01-01", "2023-12-31", 15e6, *k23)),
            "EarningsPerShareDiluted": per_share(
                F("2023-01-01", "2023-03-31", 0.5, *q1), F("2023-04-01", "2023-06-30", 0.6, *q2),
                F("2023-07-01", "2023-09-30", 0.7, *q3), F("2023-01-01", "2023-12-31", 2.4, *k23)),
            "NetCashProvidedByUsedInOperatingActivities": usd(
                F("2023-01-01", "2023-03-31", 10e6, *q1), F("2023-01-01", "2023-06-30", 22e6, *q2),
                F("2023-01-01", "2023-09-30", 35e6, *q3), F("2023-01-01", "2023-12-31", 50e6, *k23)),
            "PaymentsToAcquirePropertyPlantAndEquipment": usd(
                F("2023-01-01", "2023-03-31", 2e6, *q1), F("2023-01-01", "2023-06-30", 5e6, *q2),
                F("2023-01-01", "2023-09-30", 9e6, *q3), F("2023-01-01", "2023-12-31", 12e6, *k23)),
            "Assets": usd(F(None, "2022-12-31", 500e6, *k22), F(None, "2023-03-31", 510e6, *q1),
                          F(None, "2023-06-30", 520e6, *q2), F(None, "2023-09-30", 540e6, *q3),
                          F(None, "2023-12-31", 560e6, *k23)),
            "LiabilitiesAndStockholdersEquity": usd(F(None, "2023-12-31", 560e6, *k23)),
            "StockholdersEquity": usd(F(None, "2023-12-31", 200e6, *k23)),
        }}}

    TICKERS = {"0": {"cik_str": 1234, "ticker": "XYZ", "title": "XYZ Corp"},
               "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}

    def setUp(self):
        super().setUp()
        import lisp_sec
        self.lisp_sec = lisp_sec
        lisp_sec._parsed_facts.clear()
        self.addCleanup(lisp_sec._parsed_facts.clear)
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"sec_user_agent": "Test Person test@example.com"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        facts = self.company_facts()
        self.downloads = []
        self.real_sec_download = lisp_sec.sec_download

        def fake_download(url, credentials_path, who):
            self.downloads.append(url)
            if url == lisp_sec.TICKERS_URL:
                return self.TICKERS
            if url == lisp_sec.COMPANY_FACTS_URL % 1234:
                return facts
            raise lisp_core.LispError("%s: %s returned HTTP 404 Not Found" % (who, url))
        patcher = mock.patch.object(lisp_sec, "sec_download", fake_download)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_annual_income_statement(self):
        self.run_lisp('(define t (sec-income-statement creds "XYZ" :in-millions #f))')
        self.assertShows("(table-column-names t)", '("item" "2023-12-31" "2022-12-31" "unit" "source")')
        items = self.column("t", "item")
        row = lambda label: {name: self.column("t", name)[items.index(label)] for name in ("2023-12-31", "2022-12-31")}
        self.assertEqual(row("Revenue"), {"2023-12-31": 120e6, "2022-12-31": 100e6})      # a concept for each year
        self.assertEqual(row("Net income"), {"2023-12-31": 15e6, "2022-12-31": 11e6})     # the restated 2022
        self.assertEqual(row("Gross profit")["2023-12-31"], 50e6)                       # worked out
        self.assertIn("revenue - cost-of-revenue", self.column("t", "source")[items.index("Gross profit")])
        self.assertNotIn("Interest expense", items)                                     # a line with no values
        # in millions, unless :in-millions is #f -- but never a per-share amount
        self.run_lisp('(define m (sec-income-statement creds "XYZ"))')
        self.assertEqual(self.column("m", "2023-12-31")[:2], [120.0, 70.0])

    def test_quarters_from_year_to_date_figures(self):
        self.run_lisp('(define f (sec-financials creds "XYZ" :period "quarterly" :count 4))')
        self.assertShows('(table-column f "fiscal-period")', '#("Q1" "Q2" "Q3" "Q4")')
        self.assertEqual(self.column("f", "revenue"), [25e6, 30e6, 32e6, 33e6])        # Q4: 120 less 87
        self.assertEqual(self.column("f", "operating-cash-flow"), [10e6, 12e6, 13e6, 15e6])
        self.assertEqual(self.column("f", "free-cash-flow"), [8e6, 9e6, 9e6, 12e6])
        eps = self.column("f", "eps-diluted")
        for found, expected in zip(eps[:3], [0.5, 0.6, 0.7]):
            self.assertAlmostEqual(found, expected, places=6)
        self.assertTrue(math.isnan(eps[3]))       # no fourth-quarter EPS: an average isn't a difference

    def test_balance_sheet_and_worked_out_liabilities(self):
        self.run_lisp('(define b (sec-balance-sheet creds "XYZ" :in-millions #f))')
        items = self.column("b", "item")
        self.assertEqual(self.column("b", "2023-12-31")[items.index("Total liabilities")], 360e6)
        self.assertEqual(self.column("b", "2022-12-31")[items.index("Total assets")], 500e6)
        self.run_lisp('(define q (sec-balance-sheet creds "XYZ" :period "quarterly"))')
        self.assertShows("(table-column-names q)",
                         '("item" "2023-12-31" "2023-09-30" "2023-06-30" "2023-03-31" "unit" "source")')

    def test_sec_financials_has_a_row_per_period(self):
        self.run_lisp('(define f (sec-financials creds "XYZ"))')
        self.assertShows('(table-column f "period-end")', "#(2022-12-31 2023-12-31)")
        self.assertShows('(table-column f "fiscal-year")', "#(2022 2023)")
        # period-end, fiscal-year, fiscal-period, and a column for each line item
        self.assertShows('(length (table-column-names f))', str(3 + len(self.lisp_sec.LINE_ITEMS)))

    def test_facts_concepts_and_company(self):
        self.run_lisp('(define facts (sec-facts creds "XYZ" "NetIncomeLoss"))')
        self.assertShows('(table-column facts "value")', "#(10000000 11000000 15000000)")
        self.assertShows('(table-column facts "filed")', "#(2023-02-15 2024-02-15 2024-02-15)")
        self.assertShows('(table-row-count (sec-concepts creds "XYZ"))', "10")
        self.assertShows('(hash-table-ref (sec-company creds 1234) "name")', '"XYZ Corp"')
        self.assertLispError('(sec-facts creds "XYZ" "Goodwill")', "the company has never reported Goodwill")

    def test_tickers(self):
        self.assertEqual(self.lisp_sec.company_cik(self.credentials, lisp_core.LispString("brk.b"), "t"), 1067983)
        self.assertEqual(self.lisp_sec.company_cik(self.credentials, lisp_core.LispString("0000001234"), "t"), 1234)
        self.assertLispError('(sec-income-statement creds "NOPE")', "the SEC has no company with the ticker NOPE")
        self.assertLispError('(sec-income-statement creds 999)', "the SEC has no XBRL financial data for CIK 999")

    def test_options_and_quarters_for_a_company_with_only_annual_reports(self):
        self.assertLispError('(sec-income-statement creds "XYZ" :period "monthly")', ':period is "annual" or "quarterly"')
        self.assertLispError('(sec-income-statement creds "XYZ" :periods 3)', ":periods isn't an option")
        facts = self.company_facts()
        for entry in facts["facts"]["us-gaap"].values():
            entry["units"] = {u: [f for f in fs if f["form"] == "10-K"] for u, fs in entry["units"].items()}
        self.lisp_sec._parsed_facts[1234] = (time.time(), facts)
        self.assertLispError('(sec-income-statement creds "XYZ" :period "quarterly")',
                             "the SEC has no quarterly reports (10-Qs) for this company")

    def test_the_contact_goes_in_the_user_agent(self):
        sent = []

        def fake_http_download(url, cache_hours, headers, who, shown_url=None):
            sent.append(dict((str(p.car), str(p.cdr)) for p in lisp_core.pairs_to_list(headers)))
            return json.dumps(self.TICKERS).encode()
        with mock.patch.object(lisp_http, "download", fake_http_download):
            self.assertEqual(self.real_sec_download(self.lisp_sec.TICKERS_URL, self.credentials, "t"), self.TICKERS)
        self.assertEqual(sent, [{"User-Agent": "Test Person test@example.com"}])
        with open(self.credentials, "w") as f:
            json.dump({"fred_api_key": "x"}, f)
        with self.assertRaises(lisp_core.LispError) as caught:
            self.lisp_sec.user_agent(self.credentials, "sec-facts")
        self.assertIn('the credentials file has no "sec_user_agent" entry', str(caught.exception))


class TestFdic(LispTestCase):
    """lisp_fdic, with the FDIC's API played by a fake -- no network. Bank
    1234's Call Reports give interest income (in thousands) only for the
    year to date, as they do; net income both ways (NETINC, NETINCQ)."""

    QUARTERS = [   # REPDTE, INTINC (year to date), NETINC (ytd), NETINCQ, ASSET, ROA (ytd), ROAQ
        ("20231231", 400, 100, 30, 10000, 1.0, 1.2),
        ("20240331", 110, 25, 25, 10200, 0.98, 0.98),
        ("20240630", 230, 55, 30, 10400, 1.05, 1.12),
        ("20240930", 350, 80, 25, 10500, 1.02, 0.95),
        ("20241231", 480, 110, 30, 10800, 1.03, 1.1),
    ]
    BANKS = [{"CERT": 1234, "NAME": "First Test Bank", "CITY": "Springfield", "STALP": "IL", "ASSET": 10800,
              "ACTIVE": 1, "NAMEHCR": "TEST BANCORP", "REPDTE": "12/31/2024"},
             {"CERT": 5678, "NAME": "First Test Bank West", "CITY": "Boise", "STALP": "ID", "ASSET": 900,
              "ACTIVE": 1, "NAMEHCR": "", "REPDTE": "12/31/2024"},
             {"CERT": 9999, "NAME": "First Test Savings", "CITY": "Gary", "STALP": "IN", "ASSET": 50,
              "ACTIVE": 0, "NAMEHCR": "", "REPDTE": "03/31/2010"}]

    def setUp(self):
        super().setUp()
        import lisp_fdic
        self.lisp_fdic = lisp_fdic
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"fdic_api_key": "secret-key-123"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_fdic_request = lisp_fdic.fdic_request

        def fake_request(credentials_path, dataset, params, who):
            self.requests.append((dataset, dict(params)))
            if dataset == "financials":
                records = [{"REPDTE": d, "NAME": "First Test Bank", "INTINC": i, "NETINC": n, "NETINCQ": nq,
                            "ASSET": a, "ROA": r, "ROAQ": rq}
                           for d, i, n, nq, a, r, rq in reversed(self.QUARTERS)]        # newest first
            elif dataset == "institutions":
                words = params.get("search", "").split(":", 1)[-1].lower()
                records = [b for b in self.BANKS if words in b["NAME"].lower()]
            else:
                records = [{"ID": i, "N": i * 10} for i in range(1234)]
            offset, limit = int(params.get("offset", 0)), int(params.get("limit", 10))
            return {"meta": {"total": len(records)}, "data": [{"data": r} for r in records[offset:offset + limit]]}
        patcher = mock.patch.object(lisp_fdic, "fdic_request", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def assertClose(self, found, expected):
        """Decimals, as vectors store them (in 32 bits: 0.98 is 0.9800000190734863)."""
        self.assertEqual(len(found), len(expected))
        for f, e in zip(found, expected):
            self.assertAlmostEqual(f, e, places=5)

    def test_quarters_from_year_to_date_figures(self):
        self.run_lisp('(define f (fdic-financials creds 1234 :count 4))')
        self.assertShows('(table-column f "report-date")', "#(2024-03-31 2024-06-30 2024-09-30 2024-12-31)")
        self.assertEqual(self.column("f", "interest-income"), [110000, 120000, 120000, 130000])   # in dollars
        self.assertEqual(self.column("f", "net-income"), [25000, 30000, 25000, 30000])            # NETINCQ
        self.assertClose(self.column("f", "return-on-assets"), [0.98, 1.12, 0.95, 1.1])           # ROAQ
        self.assertEqual(self.column("f", "total-assets"), [10200000, 10400000, 10500000, 10800000])

    def test_years(self):
        self.run_lisp('(define f (fdic-financials creds 1234 :period "annual"))')
        self.assertShows('(table-column f "report-date")', "#(2023-12-31 2024-12-31)")
        self.assertEqual(self.column("f", "interest-income"), [400000, 480000])     # the whole year
        self.assertEqual(self.column("f", "net-income"), [100000, 110000])
        self.assertClose(self.column("f", "return-on-assets"), [1.0, 1.03])         # ROA, not ROAQ

    def test_reports_laid_out_as_statements(self):
        self.run_lisp('(define i (fdic-income-statement creds 1234 :count 2))')
        self.assertShows("(table-column-names i)", '("item" "2024-12-31" "2024-09-30" "unit" "field")')
        items = self.column("i", "item")
        self.assertClose([self.column("i", "2024-12-31")[items.index("Interest income")]], [0.13])   # in millions
        self.assertEqual(self.column("i", "field")[items.index("Net income")], "NETINCQ")
        self.run_lisp('(define r (fdic-ratios creds 1234 :period "annual" :count 1))')
        items = self.column("r", "item")
        self.assertClose([self.column("r", "2024-12-31")[items.index("Return on assets")]], [1.03])
        self.assertEqual(self.column("r", "unit")[items.index("Return on assets")], "percent")
        self.run_lisp('(define b (fdic-balance-sheet creds 1234 :count 1 :in-millions #f))')
        items = self.column("b", "item")
        self.assertEqual(self.column("b", "2024-12-31")[items.index("Total assets")], 10800000)

    def test_banks_by_name(self):
        self.run_lisp('(define found (fdic-find-bank creds "first test"))')
        self.assertEqual(self.column("found", "cert"), [1234, 5678, 9999])
        self.assertShows('(table-column found "last-report")', "#(2024-12-31 2024-12-31 2010-03-31)")
        self.assertEqual(self.lisp_fdic.bank_cert(self.credentials, lisp_core.LispString("first test bank"), "t"), 1234)
        self.assertEqual(self.lisp_fdic.bank_cert(self.credentials, lisp_core.LispString("first test bank west"), "t"), 5678)
        self.assertLispError('(fdic-ratios creds "First Test")',
                             "2 banks have names like First Test -- give the certificate number of one")
        self.assertLispError('(fdic-ratios creds "Savings")', "no bank open now has a name like Savings")

    def test_fdic_get_reads_every_page(self):
        self.run_lisp('(define t (fdic-get creds "failures" (list (cons "fields" "ID,N"))))')
        self.assertShows("(table-row-count t)", "1234")
        self.assertEqual([params["offset"] for _, params in self.requests], [0])      # 10,000 a page
        del self.requests[:]
        self.run_lisp('(define t (fdic-get creds "failures"))')                         # every field: 500 a page
        self.assertEqual([params["offset"] for _, params in self.requests], [0, 500, 1000])
        self.run_lisp('(define t (fdic-get creds "failures" (list (cons "limit" "3"))))')
        self.assertShows("(table-row-count t)", "3")
        self.assertLispError('(fdic-get creds "banks")', "there's no dataset banks")

    def test_what_the_fields_mean(self):
        if importlib.util.find_spec("yaml") is None:
            self.skipTest("the yaml package isn't installed")
        definitions = ("properties:\n  data:\n    properties:\n"
                       "      ASSET:\n        title: Total assets\n        description: All assets.\n"
                       "      DEPUNA:\n        title: Uninsured deposits\n        description: >-\n"
                       "          Deposits over the\n          insured limit.\n")
        with mock.patch.object(lisp_http, "download", lambda *args: definitions.encode()):
            self.run_lisp('(define all (fdic-fields creds "financials"))'
                          '(define some (fdic-fields creds "financials" "uninsured"))')
        self.assertShows('(table-column all "field")', '#("ASSET" "DEPUNA")')
        self.assertShows('(table-column some "description")', '#("Deposits over the insured limit.")')

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            raise lisp_core.LispError("%s: %s returned HTTP 500" % (who, shown_url))
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_fdic_request(self.credentials, "financials", {"filters": "CERT:1"}, "fdic-get")
        self.assertIn("api_key=secret-key-123", seen[0][0])
        self.assertNotIn("secret-key-123", seen[0][1])
        self.assertNotIn("secret-key-123", str(caught.exception))


class TestCensus(LispTestCase):
    """lisp_census, with the Census's API played by a fake -- no network.
    The fake has ACS data for 2024 and earlier, for two counties in New
    York; a variable it isn't told about is "10" everywhere."""

    COUNTIES = {
        "001": {"NAME": "Albany County, New York", "B01003_001E": "5000", "B19013_001E": "85333",
                "B17001_002E": "150", "B17001_001E": "1000",
                "B15003_022E": "100", "B15003_023E": "50", "B15003_024E": "20", "B15003_025E": "30",
                "B15003_001E": "800", "B01002_001E": "40.5"},
        "061": {"NAME": "New York County, New York", "B01003_001E": "1600000", "B19013_001E": "-666666666",
                "B17001_002E": "0", "B17001_001E": "0", "B01002_001E": "38.9"},
    }

    def setUp(self):
        super().setUp()
        import lisp_census
        self.lisp_census = lisp_census
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"us_census_api_key": "census-key-456"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_census_download = lisp_census.census_download

        def fake_download(credentials_path, url, params, cache_hours, who):
            self.requests.append((url, dict(params)))
            if url.endswith("/geography.json"):
                if int(url.split("/data/")[1].split("/")[0]) > 2024:
                    raise lisp_core.LispError("%s: %s returned HTTP 404" % (who, url))
                return {"fips": [{"name": "state"}, {"name": "county", "requires": ["state"], "wildcard": ["state"]}]}
            if url.endswith("/variables.json"):
                return {"variables": {
                    "for": {"label": "Census API FIPS 'for' clause"},
                    "B19013_001E": {"label": "Estimate!!Median household income", "concept": "Median Household Income",
                                    "group": "B19013", "predicateType": "int"},
                    "B01003_001E": {"label": "Estimate!!Total", "concept": "Total Population",
                                    "group": "B01003", "predicateType": "int"}}}
            if url == lisp_census.CATALOG_URL:
                return {"dataset": [
                    {"title": "ACS 5-Year", "c_vintage": 2024, "description": "The ACS.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/2024/acs/acs5"}]},
                    {"title": "ACS 5-Year", "c_vintage": 2023, "description": "The ACS.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/2023/acs/acs5"}]},
                    {"title": "Housing starts", "description": "Construction.",
                     "distribution": [{"accessURL": "http://api.census.gov/data/timeseries/eits/resconst"}]}]}
            wanted = params["for"].split(":")[1]
            variables = params["get"].split(",")
            rows = [variables + ["state", "county"]]
            for code, values in self.COUNTIES.items():
                if wanted in ("*", code):
                    rows.append([values.get(v, "10") for v in variables] + ["36", code])
            return rows if len(rows) > 1 else []
        for patcher in (mock.patch.object(lisp_census, "census_download", fake_download),
                        mock.patch.dict(lisp_census._latest_years, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_numbers_are_numbers_and_codes_keep_their_zeros(self):
        self.run_lisp('(define t (census-get creds "acs/acs5" (list "NAME" "B19013_001E") "county:*"'
                      ' :within "state:36"))')
        self.assertShows("(table-column-names t)", '("NAME" "B19013_001E" "state" "county")')
        self.assertShows('(table-column t "county")', '#("001" "061")')
        self.assertShows('(table-column t "state")', '#("36" "36")')
        income = self.column("t", "B19013_001E")
        self.assertEqual(income[0], 85333)
        self.assertTrue(math.isnan(income[1]))         # -666666666: the Census has no number for it
        url, params = self.requests[-1]
        self.assertTrue(url.endswith("/data/2024/acs/acs5"))     # the latest year there's data for
        self.assertEqual((params["for"], params["in"]), ("county:*", "state:36"))

    def test_predicates_come_back_as_text(self):
        def fake_download(credentials_path, url, params, cache_hours, who):
            return [["EMP", "NAICS2017", "time", "state"], ["1200", "52", "2024", "36"], ["900", "00", "2024", "36"]]
        with mock.patch.object(self.lisp_census, "census_download", fake_download):
            self.run_lisp('(define t (census-get creds "2023/cbp" "EMP" "state:36"'
                          '                      :predicates (list (cons "NAICS2017" "52") (cons "time" "2024"))))')
        self.assertShows('(table-column t "NAICS2017")', '#("52" "00")')     # codes, as they were given
        self.assertEqual(self.column("t", "EMP"), [1200, 900])
        self.assertEqual(self.column("t", "time"), [2024, 2024])               # time isn't a code

    def test_a_year_or_a_full_path(self):
        self.run_lisp('(census-get creds "acs/acs5" "NAME" "county:001" :within "state:36" :year 2019)')
        self.assertTrue(self.requests[-1][0].endswith("/data/2019/acs/acs5"))
        self.run_lisp('(census-get creds "2020/acs/acs5" "NAME" "county:001" :within "state:36")')
        self.assertTrue(self.requests[-1][0].endswith("/data/2020/acs/acs5"))
        self.assertLispError('(census-get creds "acs/acs5" "NAME" "county:999" :within "state:36" :year 2019)',
                             "the Census found nothing for that")

    def test_profile(self):
        self.run_lisp('(define p (census-profile creds "county:*" :within "state:36"))')
        self.assertShows('(table-column p "name")', '#("Albany County, New York" "New York County, New York")')
        self.assertShows('(table-column p "county")', '#("001" "061")')
        self.assertEqual(self.column("p", "population"), [5000, 1600000])
        poverty = self.column("p", "poverty-rate")
        self.assertAlmostEqual(poverty[0], 15.0, places=5)     # 150 of 1,000
        self.assertTrue(math.isnan(poverty[1]))                # 0 of 0
        self.assertAlmostEqual(self.column("p", "bachelors-degree-or-higher")[0], 25.0, places=5)  # 200 of 800
        self.assertAlmostEqual(self.column("p", "median-age")[0], 40.5, places=5)
        self.assertTrue(math.isnan(self.column("p", "median-household-income")[1]))

    def test_variables_places_and_datasets(self):
        self.run_lisp('(define v (census-variables creds "acs/acs5" "household income"))')
        self.assertShows('(table-column v "name")', '#("B19013_001E")')
        self.assertShows('(table-column v "label")', '#("Estimate - Median household income")')
        self.run_lisp('(define v (census-variables creds "acs/acs5" :year 2022))')
        self.assertShows('(table-column v "name")', '#("B01003_001E" "B19013_001E")')     # not "for"
        self.assertTrue(self.requests[-1][0].endswith("/data/2022/acs/acs5/variables.json"))
        self.run_lisp('(define g (census-geographies creds "acs/acs5"))')
        self.assertShows('(table-column g "within")', '#("" "state")')
        self.run_lisp('(define d (census-datasets creds))')
        self.assertShows('(table-column d "dataset")', '#("acs/acs5" "acs/acs5" "timeseries/eits/resconst")')
        self.assertShows('(table-column (census-datasets creds "housing") "title")', '#("Housing starts")')

    def test_places_named_by_within(self):
        self.assertEqual(self.lisp_census.place_names(["tract:*", "state:36 county:061"]), {"tract", "state", "county"})
        self.assertEqual(self.lisp_census.place_names(["zip code tabulation area:10027"]),
                         {"zip code tabulation area"})

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            raise lisp_core.LispError("%s: %s returned HTTP 400" % (who, shown_url))
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_census_download(self.credentials, self.lisp_census.API_URL + "2024/acs/acs5",
                                          {"get": "NAME", "for": "state:*"}, 1, "census-get")
        self.assertIn("key=census-key-456", seen[0][0])
        self.assertNotIn("census-key-456", seen[0][1])
        self.assertNotIn("census-key-456", str(caught.exception))


class TestBls(LispTestCase):
    """lisp_bls, with the BLS's API played by a fake -- no network. Its CPI
    is monthly, 100 + (year - 2020) + month / 100, with March 2021
    missing ("-"); productivity is quarterly; both have annual averages."""

    def setUp(self):
        super().setUp()
        import lisp_bls
        self.lisp_bls = lisp_bls
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"bureau_of_labor_statistics_api_key": "bls-key-789"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_bls_request = lisp_bls.bls_request

        def fake_request(credentials_path, series_ids, start_year, end_year, who, catalog=False, annual=False):
            self.requests.append((list(series_ids), start_year, end_year))
            answer = []
            for series_id in series_ids:
                data = []
                for year in range(start_year, end_year + 1):
                    if series_id == "PRS85006092":
                        periods = ["Q01", "Q02", "Q03", "Q04"] + (["Q05"] if annual else [])
                    else:
                        periods = ["M%02d" % m for m in range(1, 13)] + (["M13"] if annual else [])
                    for period in periods:
                        value = "%.2f" % (100 + (year - 2020) + int(period[1:]) / 100)
                        if (year, period) == (2021, "M03"):
                            value = "-"
                        data.append({"year": str(year), "period": period, "value": value})
                catalog_data = {"series_title": "Title of " + series_id} if catalog and series_id[:3] != "JTS" else None
                answer.append({"seriesID": series_id, "data": data, "catalog": catalog_data})
            return answer
        patcher = mock.patch.object(lisp_bls, "bls_request", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_months_and_quarters_line_up_by_date(self):
        self.run_lisp('(define t (bls-series creds (list "cpi" "productivity" "lns14000000")'
                      ' :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)", '("date" "cpi" "productivity" "LNS14000000")')
        self.assertShows('(vector-ref (table-column t "date") 0)', "2021-01-01")
        self.assertShows("(table-row-count t)", "12")
        cpi = self.column("t", "cpi")
        self.assertAlmostEqual(cpi[0], 101.01, places=4)
        self.assertTrue(math.isnan(cpi[2]))                          # March: "-"
        productivity = self.column("t", "productivity")
        self.assertAlmostEqual(productivity[3], 101.02, places=4)    # April 1: the second quarter
        self.assertTrue(math.isnan(productivity[1]))                 # nothing for February
        self.assertEqual(self.requests, [(["CUSR0000SA0", "LNS14000000", "PRS85006092"], 2021, 2021)])

    def test_annual_averages(self):
        self.run_lisp('(define t (bls-series creds (list "cpi" "productivity") :start-year 2020'
                      ' :end-year 2021 :annual #t))')
        self.assertShows('(table-column t "date")', "#(2020-01-01 2021-01-01)")
        self.assertAlmostEqual(self.column("t", "cpi")[1], 101.13, places=4)          # M13
        self.assertAlmostEqual(self.column("t", "productivity")[0], 100.05, places=4)  # Q05

    def test_requests_of_at_most_50_series_and_20_years(self):
        ids = ["CUUR0000SA0%02d" % i for i in range(60)]
        self.env[lisp_core.Symbol("ids")] = lisp_core.list_to_pairs([lisp_core.LispString(i) for i in ids])
        self.run_lisp('(define t (bls-series creds ids :start-year 1990 :end-year 2025))')
        self.assertEqual([(len(s), a, b) for s, a, b in self.requests],
                         [(50, 1990, 2009), (50, 2010, 2025), (10, 1990, 2009), (10, 2010, 2025)])
        self.assertShows("(table-row-count t)", str(36 * 12))
        import lisp_data_common
        first, last = lisp_data_common.year_range({}, "t")
        self.assertEqual(last - first, 9)                                     # the last 10 years

    def test_local_area(self):
        self.run_lisp('(define t (bls-local-area creds "36" :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)",
                         '("date" "labor-force" "employed" "unemployed" "unemployment-rate")')
        self.assertEqual(self.requests[-1][0], ["LASST360000000000003", "LASST360000000000004",
                                                "LASST360000000000005", "LASST360000000000006"])
        self.run_lisp('(bls-local-area creds "36061" :start-year 2021 :end-year 2021)')
        self.assertIn("LAUCN360610000000003", self.requests[-1][0])      # counties: not seasonally adjusted
        self.run_lisp('(bls-local-area creds 6 :start-year 2021 :end-year 2021)')
        self.assertIn("LASST060000000000003", self.requests[-1][0])
        self.assertLispError('(bls-local-area creds "NY")', "isn't a state's FIPS code")

    def test_local_area_for_several_places(self):
        self.run_lisp('(define t (bls-local-area creds (list "36" "36061" 6 "36") :start-year 2021 :end-year 2021))')
        self.assertShows("(table-column-names t)",
                         '("fips" "date" "labor-force" "employed" "unemployed" "unemployment-rate")')
        self.assertEqual(self.column("t", "fips"), ["36"] * 12 + ["36061"] * 12 + ["06"] * 12)   # each place once
        self.assertEqual(len(self.requests), 1)                              # 12 series: one request
        del self.requests[:]
        counties = lisp_core.list_to_pairs([lisp_core.LispString("36%03d" % (2 * i + 1)) for i in range(13)])
        self.env[lisp_core.Symbol("counties")] = counties
        self.run_lisp('(bls-local-area creds counties :start-year 2021 :end-year 2021)')
        self.assertEqual([len(ids) for ids, _, _ in self.requests], [50, 2])   # 52 series: two requests

    def test_names_and_info(self):
        self.assertShows('(vector-ref (table-column (bls-names) "name") 0)', '"cpi"')
        self.run_lisp('(define i (bls-series-info creds (list "cpi" "job-openings")))')
        self.assertShows('(table-column i "series-id")', '#("CUSR0000SA0" "JTS000000000000000JOL")')
        titles = self.column("i", "title")
        self.assertEqual(titles[0], "Title of CUSR0000SA0")
        self.assertTrue(titles[1].startswith("Job openings"))      # the BLS gives no title: bls-names's description
        self.assertLispError('(bls-series creds "not a series!")', "isn't a series ID or one of the short names")

    def test_the_api_key_is_sent_but_never_shown(self):
        sent = []

        def fake_download(url, cache_hours, headers, who, shown_url=None, body=None):
            sent.append(body)
            return json.dumps({"status": "REQUEST_NOT_PROCESSED",
                               "message": ["The key bls-key-789 has reached its daily limit."]}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bls_request(self.credentials, ["CUSR0000SA0"], 2020, 2021, "bls-series")
        self.assertEqual(json.loads(sent[0])["registrationkey"], "bls-key-789")
        self.assertNotIn("bls-key-789", str(caught.exception))
        self.assertIn("daily limit", str(caught.exception))

    def test_a_series_the_bls_does_not_have(self):
        def fake_download(url, cache_hours, headers, who, shown_url=None, body=None):
            return json.dumps({"status": "REQUEST_SUCCEEDED", "message": ["Invalid Series for Series XYZ1"],
                               "Results": {"series": [{"seriesID": "XYZ1", "data": []}]}}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bls_request(self.credentials, ["XYZ1"], 2020, 2021, "bls-series")
        self.assertIn("the BLS has no such series: XYZ1", str(caught.exception))


class TestDataCommon(unittest.TestCase):
    """lisp_data_common: what the data modules share."""

    def credentials_file(self, text):
        path = os.path.join(tempfile.mkdtemp(), "credentials.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_reading_the_credentials_file(self):
        import lisp_data_common as common
        path = self.credentials_file('{"bea_api_key": " abc ", "empty": ""}')
        self.assertEqual(common.credential(path, "bea_api_key", "t"), "abc")          # spaces trimmed
        self.assertIsNone(common.credential(path, "fdic_api_key", "t"))             # optional: None
        self.assertIsNone(common.credential(path, "empty", "t"))
        with self.assertRaises(lisp_core.LispError) as caught:
            common.credential(path, "sec_user_agent", "t", "the SEC asks for a name")
        self.assertIn('the credentials file has no "sec_user_agent" entry -- the SEC asks for a name',
                      str(caught.exception))
        for text, message in (("{not json", "isn't valid JSON"), ("[1, 2]", "must hold a JSON object")):
            with self.assertRaises(lisp_core.LispError) as caught:
                common.credential(self.credentials_file(text), "x", "t")
            self.assertIn(message, str(caught.exception))
        with self.assertRaises(lisp_core.LispError) as caught:
            common.credential("/no/such/file.json", "x", "t")
        self.assertIn("couldn't open the credentials file", str(caught.exception))

    def test_dated_tables_and_records(self):
        import lisp_data_common as common
        table = common.dated_table([("a", {datetime.date(2024, 2, 1): 2.0, datetime.date(2024, 1, 1): 1.0}),
                                    ("b", {datetime.date(2024, 2, 1): 5.0})])
        columns = dict((p.car, p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(table))
        self.assertEqual([str(d.date) for d in columns["date"]], ["2024-01-01", "2024-02-01"])
        self.assertTrue(math.isnan(columns["b"][0]))
        table = common.records_table([{"n": 1, "ok": True, "x": {"y": 2}}, {"n": 2, "s": "t"}])
        columns = dict((p.car, p.cdr.items.tolist()) for p in lisp_core.pairs_to_list(table))
        self.assertEqual((columns["n"], columns["ok"][0], columns["x"][0], columns["s"][1]), ([1, 2], 1, '{"y": 2}', "t"))


class TestBea(LispTestCase):
    """lisp_bea, with the BEA's API played by a fake -- no network. Its NIPA
    tables: T10101 (quarterly and annual), whose lines 3 and 17 are both
    "Goods"; T10105 (in millions); T20600 (monthly only) and T20100
    (quarterly and annual), with the saving rate on line 35. A value is
    year + its period's number / 100 (2025Q2 is 2025.02)."""

    TABLES = {   # table -> (frequencies, [(line, description, UNIT_MULT)])
        "T10101": ("QA", [(1, "Gross domestic product", "0"), (3, "Goods", "0"), (17, "Goods", "0")]),
        "T10105": ("QA", [(1, "Gross domestic product", "6")]),
        "T20600": ("M", [(1, "Personal income", "6"), (35, "Personal saving rate", "0")]),
        "T20100": ("QA", [(1, "Personal income", "6"), (35, "Personal saving rate", "0")]),
    }

    def setUp(self):
        super().setUp()
        import lisp_bea
        self.lisp_bea = lisp_bea
        self.credentials = os.path.join(tempfile.mkdtemp(), "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"bea_api_key": "bea-key-321"}, f)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.credentials), True)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        self.real_bea_request = lisp_bea.bea_request
        patcher = mock.patch.object(lisp_bea, "bea_request", self.fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_request(self, credentials_path, params, cache_hours, who):
        self.requests.append(dict(params))
        method = params["method"]
        if method == "GetData" and params["DataSetName"] == "NIPA":
            frequencies, lines = self.TABLES.get(params["TableName"], ("", []))
            if params["Frequency"] not in frequencies:
                raise lisp_core.LispError("%s: the BEA says: Data for this table and frequency are not "
                                          "currently available." % who)
            periods = {"A": [""], "Q": ["Q1", "Q2", "Q3", "Q4"], "M": ["M%02d" % m for m in range(1, 13)]}
            data = []
            for year in params["Year"].split(","):
                for number, period in enumerate(periods[params["Frequency"]], 1):
                    for line, description, multiplier in lines:
                        value = "{:,.2f}".format(int(year) + number / 100) if (year, period) != ("2024", "Q3") else "(NA)"
                        data.append({"LineNumber": str(line), "LineDescription": description, "SeriesCode": "S%d" % line,
                                     "TimePeriod": year + period, "CL_UNIT": "Level", "UNIT_MULT": multiplier,
                                     "DataValue": value})
            return {"Data": data}
        if method == "GetData" and params["DataSetName"] == "Regional":
            places = [("36000", "New York"), ("02000", "Alaska *")]
            years = ["2023", "2024"] if params["Year"] == "LAST5" else params["Year"].split(",")
            return {"Data": [{"GeoFips": fips, "GeoName": name, "TimePeriod": year, "CL_UNIT": "Dollars",
                              "DataValue": "{:,}".format(int(year) * 10 + i)}
                             for i, (fips, name) in enumerate(places) for year in years]}
        if method == "GetParameterValuesFiltered":
            return {"ParamValue": [{"Key": "1", "Desc": "[SAINC1] Personal income"},
                                   {"Key": "3", "Desc": "[SAINC1] Per capita personal income"}]}
        if method == "GetParameterValues":
            return {"ParamValue": [{"TableName": "T10101", "Description": "Table 1.1.1. Real GDP"},
                                   {"TableName": "T20600", "Description": "Table 2.6. Personal Income, Monthly"}]}
        if method == "GetDataSetList":
            return {"Dataset": [{"DatasetName": "NIPA", "DatasetDescription": "Standard NIPA tables"}]}
        if method == "GetParameterList":
            return {"Parameter": [{"ParameterName": "Year", "ParameterDescription": "Years",
                                   "ParameterIsRequiredFlag": "1", "MultipleAcceptedFlag": "1", "AllValue": "X"}]}
        raise AssertionError("no fake for %r" % params)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_a_nipa_table(self):
        self.run_lisp('(define t (bea-nipa creds "T10101" :start-year 2024 :end-year 2025))')
        self.assertShows("(table-column-names t)", '("date" "Gross domestic product" "Goods (line 3)" "Goods (line 17)")')
        self.assertShows('(vector-ref (table-column t "date") 1)', "2024-04-01")         # quarterly first
        gdp = self.column("t", "Gross domestic product")
        self.assertAlmostEqual(gdp[0], 2024.01, places=2)
        self.assertTrue(math.isnan(gdp[2]))                                            # "(NA)"
        self.assertEqual(self.requests[-1]["Year"], "2024,2025")
        self.run_lisp('(define t (bea-nipa creds "T10105" :lines 1 :frequency "A" :start-year 2025 :end-year 2025))')
        self.assertAlmostEqual(self.column("t", "Gross domestic product")[0], 2.02501, places=4)   # millions -> billions
        self.run_lisp('(define t (bea-nipa creds "T20600" :lines (list 35) :start-year 2025 :end-year 2025))')
        self.assertEqual([r["Frequency"] for r in self.requests[-2:]], ["Q", "M"])     # no quarters: months
        self.assertShows("(table-row-count t)", "12")                                   # monthly, the only kind
        self.assertLispError('(bea-nipa creds "T10101" :lines (list 2))', "table T10101 has no line 2")

    def test_short_names(self):
        self.run_lisp('(define t (bea-series creds (list "real-gdp-growth" "personal-saving-rate")'
                      ' :start-year 2025 :end-year 2025))')
        self.assertShows("(table-column-names t)", '("date" "real-gdp-growth" "personal-saving-rate")')
        self.assertShows("(table-row-count t)", "12")                      # quarters fall on months
        self.assertTrue(math.isnan(self.column("t", "real-gdp-growth")[1]))   # nothing for February
        self.run_lisp('(define t (bea-series creds "personal-saving-rate" :frequency "A" :start-year 2025 :end-year 2025))')
        self.assertEqual(self.requests[-1]["TableName"], "T20100")         # its annual table
        self.assertLispError('(bea-series creds "gdp" :frequency "M")', "gdp isn't published monthly")
        self.assertLispError('(bea-series creds "gnp")', "there's no series named gnp")
        self.assertShows('(vector-ref (table-column (bea-names) "name") 0)', '"gdp"')

    def test_regional(self):
        self.run_lisp('(define t (bea-regional creds "SAINC1" 3 (list "36" "02")))')
        self.assertShows("(table-column-names t)", '("fips" "name" "2023" "2024" "unit")')
        self.assertShows('(table-column t "name")', '#("New York" "Alaska")')     # the footnote's * is gone
        self.assertEqual(self.column("t", "2024"), [20240, 20241])
        self.assertEqual((self.requests[-1]["GeoFips"], self.requests[-1]["Year"]), ("36000,02000", "LAST5"))
        self.run_lisp('(bea-regional creds "CAINC1" 3 "ny" :start-year 2020 :end-year 2021)')
        self.assertEqual((self.requests[-1]["GeoFips"], self.requests[-1]["Year"]), ("NY", "2020,2021"))
        self.assertShows('(table-column (bea-regional-lines creds "SAINC1") "line")', "#(1 3)")

    def test_finding_things(self):
        self.assertShows('(table-column (bea-datasets creds) "name")', '#("NIPA")')
        self.assertShows('(table-column (bea-parameters creds "NIPA") "required")', "#(#t)")
        self.assertShows('(table-column (bea-parameter-values creds "NIPA" "TableName" "monthly") "value")',
                         '#("T20600")')
        self.run_lisp('(define t (bea-get creds "NIPA" (list (cons "TableName" "T10105") (cons "Frequency" "A")'
                      '                                 (cons "Year" "2025"))))')
        self.assertAlmostEqual(self.column("t", "DataValue")[0], 2025.01, places=2)   # as the BEA sends it

    def test_the_api_key_is_sent_but_never_shown(self):
        seen = []

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            seen.append((url, shown_url))
            return json.dumps({"BEAAPI": {"Request": {"RequestParam": [{"ParameterName": "USERID",
                                                                        "ParameterValue": "bea-key-321"}]},
                                          "Error": {"APIErrorDescription": "Error retrieving NIPA data.",
                                                    "ErrorDetail": {"Description": "Invalid TableName for bea-key-321"}}}}).encode()
        with mock.patch.object(lisp_http, "download", fake_download):
            with self.assertRaises(lisp_core.LispError) as caught:
                self.real_bea_request(self.credentials, {"method": "GetData"}, 1, "bea-nipa")
        self.assertIn("UserID=bea-key-321", seen[0][0])
        self.assertNotIn("bea-key-321", seen[0][1])
        self.assertIn("Invalid TableName", str(caught.exception))
        self.assertNotIn("bea-key-321", str(caught.exception))


class TestSchwab(LispTestCase):
    """lisp_schwab, with Schwab played by a fake -- no network, no sign-in
    window. The two made-up accounts end 1111 and 2222; the first is named
    "Brokerage", and the second has no name."""

    ACCOUNTS = [{"accountNumber": "10001111", "hashValue": "HASH1"}, {"accountNumber": "20002222", "hashValue": "HASH2"}]
    POSITIONS = {"10001111": [{"longQuantity": 100.0, "shortQuantity": 0.0, "averagePrice": 150.0, "marketValue": 23000.0,
                               "longOpenProfitLoss": 8000.0, "currentDayProfitLoss": 120.0,
                               "instrument": {"symbol": "AAPL", "description": "APPLE INC", "assetType": "EQUITY",
                                              "cusip": "037833100"}}],
                 "20002222": [{"longQuantity": 0.0, "shortQuantity": 5.0, "averagePrice": 2.5, "marketValue": -700.0,
                               "shortOpenProfitLoss": -450.0, "currentDayProfitLoss": -20.0,
                               "instrument": {"symbol": "SPY   261218C00700000", "description": "SPY CALL",
                                              "assetType": "OPTION"}}]}

    def setUp(self):
        super().setUp()
        import lisp_schwab
        self.lisp_schwab = lisp_schwab
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.credentials = os.path.join(folder, "credentials.json")
        with open(self.credentials, "w") as f:
            json.dump({"Schwab_Client_ID": "app-key", "Schwab_Client_Secret": "app-secret"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(self.credentials)
        self.requests = []
        patcher = mock.patch.object(lisp_schwab, "schwab_request", self.fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_request(self, method, url, who, headers, body=None):
        self.requests.append((method, url, headers, body))
        path = url.split("?")[0].replace(self.lisp_schwab.API_URL, "")
        if path == "/v1/oauth/token":
            return 200, {}, {"access_token": "access-%d" % len(self.requests), "refresh_token": "refresh-1",
                             "expires_in": 1800}
        if path == "/trader/v1/accounts/accountNumbers":
            return 200, {}, self.ACCOUNTS
        if path == "/trader/v1/userPreference":
            return 200, {}, {"accounts": [{"accountNumber": "10001111", "nickName": "Brokerage"},
                                          {"accountNumber": "20002222", "nickName": ""}]}
        if path == "/trader/v1/orders":
            return 200, {}, [{"accountNumber": 10001111, "orderId": 555, "status": "FILLED", "quantity": 10.0,
                              "orderLegCollection": [{"instruction": "BUY", "instrument": {"symbol": "AAPL"}}]}]
        if path == "/trader/v1/accounts":
            return 200, {}, [{"securitiesAccount": {"accountNumber": a["accountNumber"], "type": "MARGIN",
                                                    "currentBalances": {"liquidationValue": 1000.0, "cashBalance": 50.0},
                                                    "positions": self.POSITIONS[a["accountNumber"]]}}
                             for a in self.ACCOUNTS]
        if path == "/trader/v1/accounts/HASH2":
            return 200, {}, {"securitiesAccount": {"accountNumber": "20002222", "positions": self.POSITIONS["20002222"]}}
        if path == "/trader/v1/accounts/HASH1":
            return 200, {}, {"securitiesAccount": {"accountNumber": "10001111", "positions": self.POSITIONS["10001111"]}}
        if path == "/marketdata/v1/quotes":
            return 200, {}, {"AAPL": {"quote": {"bidPrice": 229.9, "askPrice": 230.1, "lastPrice": 230.0},
                                      "reference": {"description": "Apple Inc"}}}
        if path == "/marketdata/v1/pricehistory":
            return 200, {}, {"candles": [{"datetime": 1704175200000, "open": 1, "high": 2, "low": 0.5, "close": 1.5,
                                          "volume": 100}]}           # 2024-01-02, 06:00 UTC
        if path == "/trader/v1/accounts/HASH1/orders" and method == "POST":
            return 201, {"Location": self.lisp_schwab.API_URL + "/trader/v1/accounts/HASH1/orders/98765"}, None
        if method == "DELETE":
            return 200, {}, None
        raise AssertionError("no fake for %s %s" % (method, url))

    def sign_in(self):
        with mock.patch.object(self.lisp_schwab, "has_web_engine", lambda: True), \
                mock.patch.object(self.lisp_schwab, "login_in_window",
                                  lambda url, callback: "https://127.0.0.1/?code=C0DE%40&session=s"):
            self.run_lisp("(schwab-login creds)")

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_signing_in(self):
        self.assertLispError("(schwab-accounts creds)", "not signed in to Schwab -- sign in with (schwab-login creds)")
        self.sign_in()
        method, url, headers, body = self.requests[0]
        self.assertEqual((method, url), ("POST", self.lisp_schwab.TOKEN_URL))
        self.assertEqual(headers["Authorization"], "Basic " + base64.b64encode(b"app-key:app-secret").decode())
        self.assertIn("code=C0DE%40", body.decode())                         # the code, decoded and sent back
        self.assertIn("redirect_uri=https%3A%2F%2F127.0.0.1", body.decode())
        path = self.lisp_schwab.token_file(self.credentials)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")        # readable only by you
        self.run_lisp("(schwab-accounts creds)")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer access-1")

    def test_tokens_are_renewed_and_run_out(self):
        self.sign_in()
        tokens = self.lisp_schwab.load_tokens(self.credentials, "t")
        self.lisp_schwab.save_tokens(self.credentials, dict(tokens, access_expires=0))      # 30 minutes later
        sent = len(self.requests)
        self.run_lisp("(schwab-accounts creds)")
        renewal = self.requests[sent]                      # renewed first, then asked
        self.assertIn("grant_type=refresh_token", renewal[3].decode())
        self.assertNotEqual(self.requests[-1][2]["Authorization"], "Bearer access-1")
        tokens = self.lisp_schwab.load_tokens(self.credentials, "t")
        self.lisp_schwab.save_tokens(self.credentials, dict(tokens, access_expires=0, refresh_expires=0))  # a week later
        self.assertLispError("(schwab-accounts creds)", "the Schwab sign-in has run out")

    def test_accounts_and_positions(self):
        self.sign_in()
        self.run_lisp("(define a (schwab-accounts creds))")
        self.assertShows('(table-column a "account")', '#("Brokerage" "...2222")')     # names, not numbers
        self.assertEqual(self.column("a", "value"), [1000.0, 1000.0])
        self.run_lisp("(define p (schwab-positions creds))")
        self.assertShows('(table-column p "symbol")', '#("AAPL" "SPY   261218C00700000")')
        self.assertEqual(self.column("p", "quantity"), [100.0, -5.0])          # short: negative
        self.assertEqual(self.column("p", "unrealized-gain"), [8000.0, -450.0])
        self.run_lisp('(define p (schwab-positions creds :account "2222"))')      # by its last digits
        self.assertShows('(table-column p "account")', '#("...2222")')
        self.assertShows('(table-column (schwab-positions creds) "account")', '#("Brokerage" "...2222")')
        self.assertShows('(table-column (schwab-positions creds :account "brokerage") "symbol")',
                         '#("AAPL")')                                                 # by its name
        self.assertLispError('(schwab-positions creds :account "9999")',
                             "no account matches '9999' -- the accounts are Brokerage, ...2222")

    def test_quotes_and_prices(self):
        self.sign_in()
        self.run_lisp('(define q (schwab-quotes creds (list "AAPL" "NOPE")))')
        self.assertAlmostEqual(self.column("q", "bid")[0], 229.9, places=4)
        self.assertTrue(math.isnan(self.column("q", "bid")[1]))                   # unknown: NaN
        self.assertIn("symbols=AAPL%2CNOPE", self.requests[-1][1])
        self.run_lisp('(define h (schwab-price-history creds "AAPL" :start-date "2024-01-01"))')
        self.assertShows('(table-column h "date")', "#(2024-01-02)")
        self.assertIn("startDate=1704067200000", self.requests[-1][1])

    def test_orders(self):
        self.sign_in()
        self.run_lisp("(define listed (schwab-orders creds))")
        self.assertShows('(table-column listed "account")', '#("Brokerage")')     # its number is a number here
        self.assertShows('(table-column listed "symbol")', '#("AAPL")')
        self.run_lisp('(define o (schwab-order "buy" "aapl" 10 :type "LIMIT" :price 150))')
        order = self.lisp_schwab.lisp_to_json(self.run_lisp("o"))
        self.assertEqual(order["orderLegCollection"][0], {"instruction": "BUY", "quantity": 10,
                                                          "instrument": {"symbol": "AAPL", "assetType": "EQUITY"}})
        self.assertEqual((order["orderType"], order["price"], order["duration"]), ("LIMIT", 150, "DAY"))
        self.assertLispError('(schwab-order "BUY" "AAPL" 10 :type "LIMIT")', "a LIMIT order needs :price")
        self.assertLispError('(schwab-order "BUY_TO_OPEN" "AAPL" 1)', "an equity order's instruction is one of")
        sent = len(self.requests)
        self.assertLispError('(schwab-place-order creds "1111" o)', "nothing was sent")
        self.assertEqual(len(self.requests), sent)                             # not one request
        self.assertShows('(schwab-place-order creds "1111" o :confirm #t)', "98765")
        method, url, headers, body = self.requests[-1]
        self.assertEqual((method, json.loads(body)), ("POST", order))
        self.assertShows('(schwab-cancel-order creds "Brokerage" 98765)', "#t")
        self.assertEqual(self.requests[-1][:2], ("DELETE", self.lisp_schwab.API_URL + "/trader/v1/accounts/HASH1/orders/98765"))


class TestTastytrade(LispTestCase):
    """lisp_tastytrade, with tastytrade's API played by FakeTastytrade."""

    def run_with_api(self, src, answers):
        with FakeTastytrade(answers) as api:
            self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(api.credentials.name)
            result = self.run_lisp(src)
        self.api = api
        return result

    def test_get_returns_the_data_with_decimal_text_made_numbers(self):
        def answers(path, params):
            return 200, {"data": {"symbol": "SPY", "bid": "765.53", "cusip": "78462F103", "id": "27854",
                                  "is-etf": True, "open-interest": 10095, "dividend": None,
                                  "items": [{"strike-price": "375.0"}]}}
        data = self.run_with_api('(tastytrade-get creds "/instruments/equities/SPY")', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(hash-table-ref data "bid")', "765.53")
        self.assertShows('(hash-table-ref data "cusip")', '"78462F103"')       # text without a decimal point stays text
        self.assertShows('(hash-table-ref data "id")', '"27854"')
        self.assertShows('(hash-table-ref data "is-etf")', "#t")
        self.assertShows('(hash-table-ref data "open-interest")', "10095")
        self.assertShows('(hash-table-ref data "dividend")', "()")
        self.assertShows('(hash-table-ref (car (hash-table-ref data "items")) "strike-price")', "375.0")

    def test_the_path_and_parameters(self):
        answers = lambda path, params: (200, {"data": {}})
        self.run_with_api('(tastytrade-get creds (list "option-chains" "BRK/B"))', answers)
        self.assertEqual(self.api.requests, [("/option-chains/BRK%2FB", {})])
        self.run_with_api("""(tastytrade-get creds "market-data/by-type"
                               (list (cons "equity" (list "SPY" "QQQ")) (cons "index" "SPX")
                                     (cons "from" (date 2026 1 2)) (cons "all" #t)))""", answers)
        self.assertEqual(self.api.requests, [("/market-data/by-type", {"equity": ["SPY", "QQQ"], "index": "SPX",
                                                                       "from": "2026-01-02", "all": "true"})])

    def test_an_answer_in_pages_is_put_together(self):
        def answers(path, params):
            page = int(params.get("page-offset", 0))
            return 200, {"data": {"items": [{"n": page * 2}, {"n": page * 2 + 1}]},
                         "pagination": {"page-offset": page, "total-pages": 3}}
        data = self.run_with_api('(tastytrade-get creds "/transactions")', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(map (lambda (item) (hash-table-ref item "n")) (hash-table-ref data "items"))',
                         "(0 1 2 3 4 5)")
        self.assertEqual(len(self.api.requests), 3)
        data = self.run_with_api('(tastytrade-get creds "/transactions" (list (cons "page-offset" 1)))', answers)
        self.env[lisp_core.Symbol("data")] = data
        self.assertShows('(map (lambda (item) (hash-table-ref item "n")) (hash-table-ref data "items"))', "(2 3)")

    def test_errors_say_what_tastytrade_said(self):
        refused = lambda path, params: (403, {"error": {"message": "Token has insufficient scopes for this request"}})
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_with_api('(tastytrade-get creds "/instruments/equity-options")', refused)
        self.assertEqual(str(caught.exception),
                         "tastytrade-get: HTTP 403: Token has insufficient scopes for this request "
                         "(asking for /instruments/equity-options)")
        missing = lambda path, params: (404, "<html>404 Not Found</html>")
        with self.assertRaises(lisp_core.LispError) as caught:
            self.run_with_api('(tastytrade-get creds "/no-such-thing")', missing)
        self.assertIn("HTTP 404: there's no such request -- check the path", str(caught.exception))

    def test_get_table(self):
        items = lambda path, params: (200, {"data": {"items": [{"symbol": "SPY", "iv-rank": "0.35"},
                                                               {"symbol": "QQQ", "iv-rank": "0.47"}]}})
        self.env[lisp_core.Symbol("t")] = self.run_with_api('(tastytrade-get-table creds "/market-metrics")', items)
        self.assertShows("t", '(("symbol" . #("SPY" "QQQ")) ("iv-rank" . #(0.35 0.47)))')
        one = lambda path, params: (200, {"data": {"symbol": "SPY", "is-etf": True}})
        self.env[lisp_core.Symbol("t")] = self.run_with_api('(tastytrade-get-table creds "/instruments/equities/SPY")', one)
        self.assertShows("t", '(("symbol" . #("SPY")) ("is-etf" . #(1)))')

    def test_the_kind_of_instrument_a_symbol_names(self):
        kinds = {symbol: lisp_tastytrade._instrument_type(symbol) for symbol in
                 ["SPY", "BRK/B", "SPX", "SPY   261218C00700000", "/CLZ6", "./CLX6 LO1X6 261117P60", "BTC/USD"]}
        self.assertEqual(kinds, {"SPY": "equity", "BRK/B": "equity", "SPX": "equity",
                                 "SPY   261218C00700000": "equity-option", "/CLZ6": "future",
                                 "./CLX6 LO1X6 261117P60": "future-option", "BTC/USD": "cryptocurrency"})

    def test_quotes(self):
        def answers(path, params):
            return 200, {"data": {"items": [
                {"symbol": "SPY", "instrument-type": "Equity", "bid": "765.53", "ask": "765.54", "mid": "765.535"},
                {"symbol": "SPY   261218C00700000", "instrument-type": "Equity Option", "bid": "73.4",
                 "ask": "76.98", "volatility": "0.2616", "delta": "0.787", "open-interest": 10095}]}}
        self.env[lisp_core.Symbol("q")] = self.run_with_api(
            '(tastytrade-quotes creds (list "SPY   261218C00700000" "NOSUCH" "SPY"))', answers)
        self.assertEqual(self.api.requests, [("/market-data/by-type", {
            "equity-option": ["SPY   261218C00700000"], "equity": ["NOSUCH", "SPY"]})])
        self.assertShows('(table-column q "symbol")', '#("SPY   261218C00700000" "NOSUCH" "SPY")')
        self.assertShows('(table-column q "bid")', "#(73.4 nan 765.53)")
        self.assertShows('(table-column q "implied-volatility")', "#(0.2616 nan nan)")
        self.assertShows('(table-column q "open-interest")', "#(10095.0 nan nan)")
        self.assertShows("(car (table-column-names q))", '"symbol"')

    def test_quotes_ask_for_100_symbols_at_a_time(self):
        answers = lambda path, params: (200, {"data": {"items": []}})
        self.run_with_api('(tastytrade-quotes creds (loop for i from 0 below 250 collect (format "S{}" i)))', answers)
        self.assertEqual([len(params["equity"]) for _path, params in self.api.requests], [100, 100, 50])

    def test_option_chain(self):
        def option(strike, kind, expiration):
            occ = "SPY   %s%s%08d" % (expiration[2:].replace("-", ""), kind, strike * 1000)
            return {"symbol": occ, "option-type": kind,
                    "strike-price": "%s.0" % strike, "expiration-date": expiration,
                    "days-to-expiration": 30, "underlying-symbol": "SPY"}
        chain = [option(strike, kind, expiration) for strike in (90, 95, 100, 105, 110)
                 for kind in ("P", "C") for expiration in ("2099-01-16", "2099-02-20", "2199-01-16")]

        def answers(path, params):
            if path == "/option-chains/SPY":
                return 200, {"data": {"items": chain}}
            if params.get("equity") == ["SPY"]:
                return 200, {"data": {"items": [{"symbol": "SPY", "bid": "101.0", "ask": "102.0", "mid": "101.5"}]}}
            return 200, {"data": {"items": [{"symbol": s, "bid": "1.0", "ask": "1.2", "mid": "1.1",
                                             "volatility": "0.2", "delta": "0.5"}
                                            for s in params["equity-option"]]}}
        with mock.patch.object(lisp_tastytrade.datetime, "date", wraps=datetime.date) as fake_date:
            fake_date.today.return_value = datetime.date(2098, 12, 1)
            self.env[lisp_core.Symbol("chain")] = self.run_with_api('(tastytrade-option-chain creds "SPY" 3 2)', answers)
        # the 2 strikes nearest 101.5 (100 and 105), calls and puts, for the two
        # expirations within 3 months, in order
        self.assertShows('(table-column chain "symbol")',
                         '#("SPY   990116C00100000" "SPY   990116P00100000" "SPY   990116C00105000" '
                         '"SPY   990116P00105000" "SPY   990220C00100000" "SPY   990220P00100000" '
                         '"SPY   990220C00105000" "SPY   990220P00105000")')
        self.assertShows('(table-column chain "type")', '#("Call" "Put" "Call" "Put" "Call" "Put" "Call" "Put")')
        self.assertShows('(vector-ref (table-column chain "underlying-price") 0)', "101.5")
        self.assertShows('(vector-ref (table-column chain "ask") 0)', "1.2")
        self.assertShows('(vector-ref (table-column chain "implied-volatility") 0)', "0.2")

    def test_test_connection_names_the_accounts(self):
        answers = lambda path, params: (200, {"data": {"items": [{"account": {"account-number": "5WT0001"}},
                                                                 {"account": {"account-number": "5WT0002"}}]}})
        self.assertEqual(self.run_with_api("(tastytrade-test-connection creds)", answers),
                         "Connected successfully. Account(s): 5WT0001, 5WT0002.")


class TestDateArithmetic(LispTestCase):
    """days-between, date-add-years, date-end-of-month, date-day-of-week."""

    def test_days_between(self):
        self.assertShows("(days-between (date 2024 1 31) (date 2024 3 1))", "30")
        self.assertShows("(days-between (date 2024 3 1) (date 2024 1 31))", "-30")
        self.assertShows("(days-between (date 2024 3 1) (vector (date 2024 1 31) (date 2025 3 1)))", "#(-30 365)")
        self.assertLispError("(days-between 5 (date 2024 1 1))", "days-between: not a date: 5")

    def test_date_add_years(self):
        self.assertShows("(date-add-years (date 2024 2 29) 1)", "2025-02-28")
        self.assertShows("(date-add-years (date 2024 2 29) 4)", "2028-02-29")
        self.assertShows("(date-add-years (vector (date 2020 5 5)) -4)", "#(2016-05-05)")

    def test_end_of_month_and_day_of_week(self):
        self.assertShows("(date-end-of-month (date 2024 2 10))", "2024-02-29")
        self.assertShows("(date-end-of-month (date 2023 12 1))", "2023-12-31")
        self.assertShows("(date-day-of-week (date 2026 9 28))", "1")         # a Monday
        self.assertShows("(date-day-of-week (date 2026 9 27))", "7")         # a Sunday


class TestClock(LispTestCase):
    """lisp_clock.py: current-time, today, time-add, seconds-between,
    time->string, next-time, sleep, and sleep-until -- mostly against a
    pretend clock, so nothing really waits."""

    def pretend_clock(self, start):
        """Make lisp_clock see `start` (a datetime) as now, with time.sleep
        moving the pretend clock forward instead of waiting. Returns the list
        that each sleep's length is added to."""
        clock = {"now": start}
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += datetime.timedelta(seconds=seconds)

        for patcher in (mock.patch.object(lisp_clock, "now", lambda: clock["now"]),
                        mock.patch.object(lisp_clock.time, "sleep", fake_sleep)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return sleeps

    def test_current_time_and_today(self):
        self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 37, 5, 250000))
        self.assertShows("(current-time)", "(2026 9 28 14 37 5)")
        self.assertShows("(today)", "2026-09-28")

    def test_the_real_current_time(self):
        before = datetime.datetime.now().replace(microsecond=0)
        shown = datetime.datetime(*lisp_core.pairs_to_list(self.run_lisp("(current-time)")))
        self.assertTrue(before <= shown <= datetime.datetime.now())

    def test_time_add_and_seconds_between(self):
        self.assertShows("(time-add '(2026 12 31 23 59 30) 45)", "(2027 1 1 0 0 15)")
        self.assertShows("(time-add '(2026 9 28 12 0 0) (* -60 60))", "(2026 9 28 11 0 0)")
        self.assertShows("(time-add '(2026 9 28) (* 60 60 36))", "(2026 9 29 12 0 0)")      # hour and on left off
        self.assertShows("(time-add (date 2026 9 28) 90)", "(2026 9 28 0 1 30)")            # a date is midnight
        self.assertShows("(seconds-between '(2026 9 28 14 0 0) '(2026 9 28 15 30 0))", "5400")
        self.assertShows("(seconds-between '(2026 9 28 15 30 0) '(2026 9 28 14 0 0))", "-5400")

    def test_time_to_string(self):
        self.assertShows("(time->string '(2026 9 28 14 37 5))", '"2026-09-28 14:37:05"')

    def test_next_time(self):
        self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 37, 5))
        self.assertShows("(next-time 15)", "(2026 9 28 15 0 0)")              # later today
        self.assertShows("(next-time 9 30)", "(2026 9 29 9 30 0)")            # already past: tomorrow
        self.assertShows("(next-time 14 37 5)", "(2026 9 29 14 37 5)")        # now counts as past
        self.assertLispError("(next-time 24)", "next-time: 24:0:0 isn't a time of day")

    def test_sleep(self):
        sleeps = self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 0, 0))
        self.assertShows("(sleep 2.5)", "()")
        self.assertEqual(sleeps, [2.5])
        self.assertLispError("(sleep -1)", "sleep: can't wait -1 seconds")
        self.assertLispError('(sleep "1")', "sleep: the number of seconds must be a number")

    def test_sleep_until_looks_at_the_clock_at_least_once_a_minute(self):
        sleeps = self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 0, 0))
        self.run_lisp("(sleep-until '(2026 9 28 14 2 30))")
        self.assertEqual(sleeps, [60, 60, 30])
        self.assertShows("(current-time)", "(2026 9 28 14 2 30)")

    def test_sleep_until_a_time_already_past_returns_at_once(self):
        sleeps = self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 0, 0))
        self.assertShows("(sleep-until '(2026 9 28 13 0 0))", "()")
        self.assertEqual(sleeps, [])

    def test_sleep_until_wakes_on_time_after_the_computer_was_asleep(self):
        sleeps = self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 0, 0))
        real_fake_sleep = lisp_clock.time.sleep

        def sleep_through_a_closed_lid(seconds):
            real_fake_sleep(seconds + 600)          # the computer slept for 10 minutes in there
        with mock.patch.object(lisp_clock.time, "sleep", sleep_through_a_closed_lid):
            self.run_lisp("(sleep-until '(2026 9 28 14 5 0))")
        # It asked for a minute, woke 11 minutes on, saw 14:05 was past, and stopped.
        self.assertEqual(len(sleeps), 1)
        self.assertShows("(current-time)", "(2026 9 28 14 11 0)")

    def test_checking_every_hour_on_the_hour(self):
        self.pretend_clock(datetime.datetime(2026, 9, 28, 14, 37, 5))
        self.run_lisp("""
          (define checked '())
          (define (next-hour)
            (let ((now (current-time)))
              (time-add (list (first now) (second now) (third now) (fourth now) 0 0) (* 60 60))))
          (loop repeat 3
                do (set! checked (cons (time->string (current-time)) checked))
                   (sleep-until (next-hour)))""")
        self.assertShows("(reverse checked)",
                         '("2026-09-28 14:37:05" "2026-09-28 15:00:00" "2026-09-28 16:00:00")')

    def test_bad_times(self):
        self.assertLispError("(time-add 5 1)", "time-add: a time is a list of whole numbers")
        self.assertLispError("(time-add '(2026 2 30) 1)", "time-add: (2026 2 30) isn't a real time")
        self.assertLispError("(sleep-until '(2026 9))", "sleep-until: a time is a list of whole numbers")


class TestDayCounts(LispTestCase):
    """day-count and year-fraction under each basis (lisp_finance.py)."""

    def test_30_360(self):
        self.assertShows('(day-count (date 2024 1 31) (date 2024 3 1) "30/360")', "31")
        self.assertShows('(day-count (date 2024 1 31) (date 2024 3 31) "30/360")', "60")
        self.assertShows('(day-count (date 2024 1 29) (date 2024 3 31) "30/360")', "62")     # the 31st stays
        self.assertShows('(day-count (date 2024 1 29) (date 2024 3 31) "30E/360")', "61")    # ...but not in 30E
        self.assertShows('(year-fraction (date 2024 1 15) (date 2024 7 15) "30/360")', "0.5")

    def test_actual_bases(self):
        self.assertShows('(day-count (date 2024 1 1) (date 2024 7 1) "ACT/360")', "182")
        self.assertShows("(year-fraction (date 2024 1 1) (date 2024 7 1) 'act/360)", "0.5055555555555555")
        self.assertShows('(year-fraction (date 2024 1 1) (date 2025 1 1) "ACT/365")', "1.0027397260273974")
        self.assertShows('(year-fraction (date 2024 1 1) (date 2025 1 1) "ACT/ACT")', "1.0")
        self.assertAlmostEqual(self.run_lisp('(year-fraction (date 2023 7 1) (date 2024 7 1) "ACT/ACT")'),
                               184 / 365 + 182 / 366)

    def test_vectors_of_dates(self):
        self.assertShows('(day-count (date 2024 1 1) (vector (date 2024 2 1) (date 2024 3 1)) "30/360")', "#(30 60)")

    def test_an_unknown_basis(self):
        self.assertLispError('(year-fraction (date 2024 1 1) (date 2024 7 1) "bus/252")',
                             "year-fraction: unknown day count basis \"bus/252\" -- use one of 30/360, 30E/360, "
                             "ACT/360, ACT/365, ACT/ACT")


class TestCashFlowMath(LispTestCase):
    """npv, irr, xnpv, xirr, payment, present-value, yield, duration,
    modified-duration, convexity, and bond-cashflows (lisp_finance.py)."""

    def value(self, src):
        return self.run_lisp(src)

    def test_npv_counts_the_first_cash_flow_as_now(self):
        self.assertAlmostEqual(self.value("(npv 0.1 (list -100 60 60))"), -100 + 60 / 1.1 + 60 / 1.21)
        self.assertAlmostEqual(self.value("(npv 0.1 #(-100 60 60))"), -100 + 60 / 1.1 + 60 / 1.21)

    def test_irr(self):
        rate = self.value("(irr (list -100 60 60))")
        self.assertAlmostEqual(rate, 0.1306623862918975, places=10)
        self.assertAlmostEqual(self.value("(npv %r (list -100 60 60))" % rate), 0, places=8)

    def test_irr_of_a_long_monthly_series(self):
        # a 30-year loan of 300,000 at 6.5%: the monthly irr of its cash flows is 6.5% / 12
        rate = self.value("(irr (cons -300000 (loop repeat 360 collect (payment (/ 0.065 12) 360 300000))))")
        self.assertAlmostEqual(rate, 0.065 / 12, places=10)

    def test_irr_with_no_answer(self):
        self.assertLispError("(irr (list 100 60))", "irr: no rate from -99% to 1000% a period gives a value of 0")

    def test_irr_between_given_rates(self):
        # -100, 230, -132 has two irrs, 10% and 20%; without low and high, the one nearer 0
        self.assertAlmostEqual(self.value("(irr (list -100 230 -132))"), 0.1, places=10)
        self.assertAlmostEqual(self.value("(irr (list -100 230 -132) 0.15 0.5)"), 0.2, places=10)

    def test_xnpv_and_xirr_match_excel(self):
        self.run_lisp("""(define dates (list (date 2008 1 1) (date 2008 3 1) (date 2008 10 30)
                                                (date 2009 2 15) (date 2009 4 1)))
                         (define flows (list -10000 2750 4250 3250 2750))""")
        self.assertAlmostEqual(self.value("(xnpv 0.09 dates flows)"), 2086.6476020315, places=6)
        self.assertAlmostEqual(self.value("(xirr dates flows)"), 0.373362535, places=8)
        self.assertLispError("(xirr (list (date 2008 1 1)) flows)", "xirr: there are 1 dates but 5 cash flows")

    def test_payment(self):
        self.assertAlmostEqual(self.value("(payment (/ 0.065 12) 360 300000)"), 1896.2040704789, places=8)
        self.assertShows("(payment 0 12 1200)", "100.0")
        self.assertLispError("(payment 0.01 0 1000)", "the number of periods must be more than 0")

    def test_a_bond(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        self.assertShows("flows", "#(3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 3.0 103.0)")
        price = self.value("(present-value 0.05 2 flows)")
        self.assertAlmostEqual(price, 104.3760319655, places=8)
        self.assertAlmostEqual(self.value("(yield %r 2 flows)" % price), 0.05, places=10)
        self.assertAlmostEqual(self.value("(present-value 0.06 2 flows)"), 100, places=10)   # par, at the coupon

    def test_duration_and_convexity(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        # the same measures, straight from their definitions
        v = [1.025 ** -t for t in range(1, 11)]
        c = [3.0] * 9 + [103.0]
        price = sum(ci * vi for ci, vi in zip(c, v))
        macaulay = sum(t / 2 * ci * vi for t, ci, vi in zip(range(1, 11), c, v)) / price
        convexity = sum(t * (t + 1) * ci * vi for t, ci, vi in zip(range(1, 11), c, v)) / (price * 1.025 ** 2 * 4)
        self.assertAlmostEqual(self.value("(duration 0.05 2 flows)"), macaulay, places=10)
        self.assertAlmostEqual(self.value("(modified-duration 0.05 2 flows)"), macaulay / 1.025, places=10)
        self.assertAlmostEqual(self.value("(convexity 0.05 2 flows)"), convexity, places=10)

    def test_duration_predicts_a_small_price_change(self):
        self.run_lisp("(define flows (bond-cashflows 0.06 5 2))")
        p0 = self.value("(present-value 0.05 2 flows)")
        p1 = self.value("(present-value 0.0501 2 flows)")
        d = self.value("(modified-duration 0.05 2 flows)")
        cx = self.value("(convexity 0.05 2 flows)")
        self.assertAlmostEqual((p1 - p0) / p0, -d * 0.0001 + cx * 0.0001 ** 2 / 2, places=9)

    def test_bad_cash_flows(self):
        self.assertLispError("(npv 0.1 '())", "npv: there are no cash flows")
        self.assertLispError("(npv 0.1 (list 1 \"a\"))", 'npv: every cash flow must be a number, not "a"')
        self.assertLispError("(npv 0.1 (vector 1 nan))", "every cash flow must be a number, not nan")
        self.assertLispError("(bond-cashflows 0.05 1.3 2)", "whole number of periods")


class TestMoreListAndStringFunctions(LispTestCase):
    """last, butlast, map over several lists, signum, and the string tests."""

    def test_last_and_butlast(self):
        self.assertShows("(last '(1 2 3))", "(3)")
        self.assertShows("(car (last '(1 2 3)))", "3")
        self.assertShows("(last '(1 2 3) 2)", "(2 3)")
        self.assertShows("(last '())", "()")
        self.assertShows("(butlast '(1 2 3))", "(1 2)")
        self.assertShows("(butlast '(1 2 3) 2)", "(1)")
        self.assertShows("(butlast '(1 2 3) 5)", "()")
        self.assertLispError("(last #(1 2))", "last: expected a list")

    def test_map_over_several_lists_or_vectors(self):
        self.assertShows("(map + '(1 2 3) '(10 20))", "(11 22)")
        self.assertShows("(map list '(1 2) '(a b) '(x y))", "((1 a x) (2 b y))")
        self.assertShows("(map * #(1 2) #(3 4))", "#(3 8)")
        self.assertLispError("(map + '(1 2) #(1 2))", "map: give it all lists or all vectors")

    def test_signum(self):
        self.assertShows("(signum -2.5)", "-1.0")
        self.assertShows("(signum 0)", "0")
        self.assertShows("(signum 7)", "1")
        self.assertShows("(signum #(-3 0 2))", "#(-1 0 1)")

    def test_string_starts_and_ends_with(self):
        self.assertShows('(string-starts-with? "#each x" "#each")', "#t")
        self.assertShows('(string-starts-with? "x #each" "#each")', "#f")
        self.assertShows('(string-ends-with? "report.csv" ".csv")', "#t")


class TestSolverLibrary(LispTestCase):
    """lib/solver.lsp: Ridders' method and Nelder-Mead."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "%s")' % os.path.join(LIB, "solver.lsp"))

    def test_ridders_finds_a_root(self):
        self.assertAlmostEqual(self.run_lisp("(ridders (lambda (x) (- (* x x) 2)) 0 2)"), 2 ** 0.5, places=10)
        self.assertLispError("(ridders (lambda (x) (+ (* x x) 1)) 0 2)", "no root is bracketed")

    def test_nelder_mead_finds_the_minimum_of_the_rosenbrock_function(self):
        self.run_lisp("""(define (rosenbrock p)
                           (let ((x (car p)) (y (car (cdr p))))
                             (+ (expt (- 1 x) 2) (* 100 (expt (- y (* x x)) 2)))))""")
        point, value = lisp_core.pairs_to_list(self.run_lisp("(nelder-mead rosenbrock (list -1.2 1.0))"))
        x, y = lisp_core.pairs_to_list(point)
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 1.0, places=6)
        self.assertLess(value, 1e-12)

    def test_implied_volatility_round_trip(self):
        self.run_lisp('(define price (bsm-price "call" 100 105 0.5 0.04 0.25))')
        self.assertAlmostEqual(self.run_lisp('(implied-vol price "call" 100 105 0.5 0.04)'), 0.25, places=8)


class TestStratify(LispTestCase):
    """lisp_stratify.py: stratify and stratify-all."""

    def setUp(self):
        super().setUp()
        self.run_lisp("""
          (define loans
            (make-table "rate"    #(3.25 4.5 5.125 5.75 6.25 6.5 7.0 7.25 3.99 nan)
                        "balance" #(100000 250000 175000 300000 125000 90000 400000 60000 210000 50000)
                        "age"     #(12 24 36 6 48 60 3 72 18 30)
                        "ltv"     #(80 75 90 60 95 70 85 65 78 88)
                        "state"   (vector "CA" "NY" "CA" "TX" "CA" "NY" "FL" "TX" "CA" "WA")
                        "first"   (vector (date 2019 3 1) (date 2020 5 1) (date 2021 1 1) (date 2019 7 1)
                                          (date 2022 2 1) (date 2018 9 1) (date 2023 4 1) (date 2020 8 1)
                                          (date 2021 6 1) (date 2022 11 1))))
          (define summaries '(("rate" weighted-mean "WAC") ("age" weighted-mean "WALA")))""")

    def strat(self, by, extra=':weight "balance"'):
        return "(stratify loans '%s summaries %s)" % (by, extra)

    def column(self, by, name, extra=':weight "balance"'):
        return self.show('(table-column %s "%s")' % (self.strat(by, extra), name))

    def test_breakpoints(self):
        by = '("rate" (4.0 5.0 6.0 7.0))'
        self.assertEqual(self.column(by, "rate"),
                         '#("under 4.0" "4.0 to 5.0" "5.0 to 6.0" "6.0 to 7.0" "7.0 and over" "missing" "total")')
        self.assertEqual(self.column(by, "count"), "#(2 1 2 2 2 1 10)")
        self.assertEqual(self.column(by, "total balance"),
                         "#(310000.0 250000.0 475000.0 215000.0 460000.0 50000.0 1760000.0)")
        self.assertEqual(self.show("(table-column-names %s)" % self.strat(by)),
                         '("rate" "count" "total balance" "percent" "WAC" "WALA")')
        wac = self.run_lisp('(vector-ref (table-column %s "WAC") 0)' % self.strat(by))
        self.assertAlmostEqual(wac, (3.25 * 100000 + 3.99 * 210000) / 310000, places=5)
        percent = self.run_lisp('(vector-ref (table-column %s "percent") 0)' % self.strat(by))
        self.assertAlmostEqual(percent, 310000 / 1760000)

    def test_a_row_is_in_the_bucket_its_value_starts(self):
        self.run_lisp("(define t (make-table \"x\" #(4.0 5.0) \"w\" #(1 1)))")
        self.assertShows("(table-column (stratify t '(\"x\" (4.0 5.0)) '() :total #f) \"x\")",
                         '#("4.0 to 5.0" "5.0 and over")')

    def test_equal_count(self):
        by = '("age" (equal-count 3))'
        self.assertEqual(self.column(by, "age"), '#("3 to 12" "18 to 36" "48 to 72" "total")')
        self.assertEqual(self.column(by, "count"), "#(3 4 3 10)")

    def test_equal_weight(self):
        by = '("ltv" (equal-weight 3))'
        self.assertEqual(self.column(by, "ltv"), '#("60 to 70" "75 to 80" "85 to 95" "total")')
        self.assertEqual(self.column(by, "total balance"), "#(450000.0 560000.0 750000.0 1760000.0)")

    def test_equal_buckets_keep_equal_values_together(self):
        self.run_lisp("(define t (make-table \"x\" #(1 2 2 2 2 2 3 4) \"w\" #(1 1 1 1 1 1 1 1)))")
        self.assertShows("(table-column (stratify t '(\"x\" (equal-count 4)) '()) \"x\")",
                         '#("1 to 1" "2 to 2" "3 to 4" "total")')

    def test_top_and_each(self):
        self.assertEqual(self.column('("state" (top 2))', "state"), '#("CA" "FL" "other" "total")')
        self.assertShows("(table-column (stratify loans '(\"state\" (top 2)) '()) \"state\")",
                         '#("CA" "NY" "other" "total")')                     # by rows, without a weight
        self.assertEqual(self.column('("state" each)', "state"), '#("CA" "FL" "NY" "TX" "WA" "total")')
        self.assertEqual(self.column('("rate" (top 2))', "rate"), '#(7.0 5.75 "other" "missing" "total")')

    def test_year_and_date_breakpoints(self):
        self.assertEqual(self.column('("first" year)', "first"),
                         '#(2018 2019 2020 2021 2022 2023 "total")')
        self.assertShows("(table-column (stratify loans (list \"first\" (list (date 2020 1 1) (date 2022 1 1)))"
                         " summaries :weight \"balance\") \"first\")",
                         '#("under 2020-01-01" "2020-01-01 to 2022-01-01" "2022-01-01 and over" "total")')
        self.assertLispError(self.strat('("rate" year)'), "stratify: bucketing rate by year needs a column of dates")

    def test_several_columns_at_once(self):
        by = '(("state" (top 2)) ("rate" (5.0)))'
        self.assertEqual(self.column(by, "state"), '#("CA" "CA" "FL" "other" "other" "other" "total")')
        self.assertEqual(self.column(by, "rate"),
                         '#("under 5.0" "5.0 and over" "5.0 and over" "under 5.0" "5.0 and over" "missing" "")')
        self.assertEqual(self.column(by, "count"), "#(2 2 1 1 3 1 10)")

    def test_without_a_weight(self):
        self.assertEqual(self.show("(table-column-names (stratify loans '(\"state\" each) '((\"age\" mean))))"),
                         '("state" "count" "percent" "age (mean)")')
        self.assertLispError("(stratify loans '(\"state\" each) summaries)", "a weighted-mean needs a weight")
        self.assertLispError("(stratify loans '(\"ltv\" (equal-weight 3)) '())", "equal-weight buckets need a weight")

    def test_no_total_row(self):
        self.assertEqual(self.column('("state" (top 2))', "count", ':weight "balance" :total #f'), "#(4 1 5)")

    def test_totals_are_kept_in_full_precision(self):
        self.run_lisp("(define t (make-table \"x\" #(1 2) \"w\" (vector 16777216.0 1.0)))")
        self.assertShows("(table-column (stratify t '(\"x\" each) '((\"w\" sum)) :weight \"w\") \"total w\")",
                         "#(16777216.0 1.0 16777217.0)")      # 32-bit storage would round the total to ...216
        self.assertShows("(table-column (stratify t '(\"x\" each) '((\"w\" sum)) :weight \"w\") \"w (sum)\")",
                         "#(16777216.0 1.0 16777217.0)")

    def test_stratifying_by_the_weight_column(self):
        self.assertEqual(self.column('("balance" (100000 200000))', "balance"),
                         '#("under 100000" "100000 to 200000" "200000 and over" "total")')

    def test_representative_and_mode_for_columns_that_cannot_be_averaged(self):
        by = '("rate" (5.0))'
        summaries = "'((\"state\" representative) (\"state\" mode \"most loans\") (\"state\" weighted-mode \"most balance\"))"
        table = "(stratify loans '%s %s :weight \"balance\")" % (by, summaries)
        self.assertShows('(table-column %s "state (representative)")' % table, '#("CA" "CA" "WA" "CA")')
        self.assertShows('(table-column %s "most loans")' % table, '#("CA" "CA" "WA" "CA")')
        self.assertShows('(table-column %s "most balance")' % table, '#("CA" "FL" "WA" "CA")')

    def test_medians_and_percentiles(self):
        self.run_lisp("(define t (make-table \"x\" #(1 1 1 2) \"fico\" #(700 720 730 640)"
                      " \"w\" #(100 250 210 50)))")
        table = ("(stratify t '(\"x\" each) '((\"fico\" median) (\"fico\" weighted-median)"
                 " (\"fico\" (percentile 10)) (\"fico\" (weighted-percentile 90))) :weight \"w\")")
        self.assertShows('(table-column-names %s)' % table,
                         '("x" "count" "total w" "percent" "fico (median)" "fico (weighted-median)"'
                         ' "fico (percentile 10)" "fico (weighted-percentile 90)")')
        self.assertShows('(table-column %s "fico (median)")' % table, "#(720.0 640.0 710.0)")
        self.assertShows('(table-column %s "fico (weighted-median)")' % table, "#(720.0 640.0 720.0)")
        self.assertShows('(table-column %s "fico (percentile 10)")' % table, "#(704.0 640.0 658.0)")
        self.assertShows('(table-column %s "fico (weighted-percentile 90)")' % table, "#(730.0 640.0 730.0)")

    def test_bad_percentiles(self):
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" (percentile 120))))",
                             "a percentile is written (percentile p) or (weighted-percentile p)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" percentile)))",
                             "say which percentile, e.g. (percentile 90)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" weighted-median)))",
                             "a weighted-median needs a weight")

    def test_stratify_all(self):
        tables = self.run_lisp("(stratify-all loans '((\"state\" (top 2)) (\"age\" (equal-count 3))) "
                               "summaries :weight \"balance\")")
        names = [lisp_core.to_string(lisp_core.pairs_to_list(t)[0].car) for t in lisp_core.pairs_to_list(tables)]
        self.assertEqual(names, ['"state"', '"age"'])

    def test_errors(self):
        self.assertLispError(self.strat('("rate" (between 1 2))'), "stratify: can't bucket rate by (between 1 2)")
        self.assertLispError(self.strat('("nope" each)'), "no column named")
        self.assertLispError(self.strat('("rate")'), "each way of bucketing is (column how)")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" average)))",
                             "stratify: average isn't a summary")
        self.assertLispError("(stratify loans '(\"rate\" each) '((\"age\" mean \"count\")))",
                             "two columns would both be called count")
        self.assertLispError("(stratify loans '(\"rate\" each) '() :weigth \"balance\")", ":weigth isn't an option")


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
          (define s (make-table "date" (vector (date 2023 1 5) (date 2023 1 20) (date 2023 3 1) (date 2023 3 9))
                                "rate" (vector 6.0 7.0 nan 5.0)))""")
        self.assertShows('(series-monthly s)',
                         '(("month" . #(24276 24278)) ("date" . #(2023-01-01 2023-03-01)) ("rate" . #(6.5 5.0)))')
        self.assertShows("(table-column (series-monthly s :how 'first) \"rate\")", "#(6.0 5.0)")
        self.assertShows("(table-column (series-monthly s :how 'last) \"rate\")", "#(7.0 5.0)")
        self.assertShows("(table-column (series-monthly s :how 'sum) \"rate\")", "#(13.0 5.0)")
        self.assertLispError("(series-monthly s :how 'median)", ":how must be")
        self.assertShows("(series-values-at s (month-range (date 2022 12 1) (date 2023 4 1)))",
                         "#(nan 6.5 nan 5.0 nan)")
        self.assertShows("(series-values-at s (month-range (date 2022 12 1) (date 2023 4 1)) :fill-forward #t)",
                         "#(nan 6.5 6.5 5.0 5.0)")
        self.assertShows("(series-values-at s (vector (date 2023 1 1)))", "#(6.5)")

    def test_a_series_can_have_several_columns_and_its_dates_another_name(self):
        self.run_lisp("""
          (define prices (make-table "Date" (vector (date 2023 1 3) (date 2023 1 31) (date 2023 2 1))
                                     "close" #(10.0 12.0 11.0) "volume" #(100 300 200)))""")
        self.assertShows("(table-column-names (series-monthly prices :how 'last))", '("month" "date" "close" "volume")')
        self.assertShows("(table-column (series-monthly prices :how 'last) \"close\")", "#(12.0 11.0)")
        self.assertShows("(series-values-at prices (vector (date 2023 2 1)) :column \"volume\")", "#(200.0)")
        self.assertLispError("(series-values-at prices (vector (date 2023 2 1)))", "say which with :column")
        self.assertLispError("(series-values-at prices (vector (date 2023 2 1)) :column \"open\")", "no column of numbers named open")
        self.assertLispError("(series-monthly (make-table \"x\" #(1 2)))", "a table with a column of dates")

    def test_series_table(self):
        self.run_lisp("""
          (define a (make-table "date" (vector (date 2023 1 1) (date 2023 3 1)) "a" #(1 3)))
          (define b (make-table "date" (vector (date 2023 2 15)) "b" #(20)))
          (define t (series-table (list a b)))""")
        self.assertShows("(table-column-names t)", '("month" "date" "a" "b")')
        self.assertShows('(table-column t "month")', "#(24276 24277 24278)")
        self.assertShows('(table-column t "a")', "#(1.0 nan 3.0)")
        self.assertShows('(table-column t "b")', "#(nan 20.0 nan)")
        self.assertShows('(table-column (series-table (list b a) :fill-forward #t) "b")', "#(nan 20.0 20.0)")
        self.assertLispError("(series-table (list a a))", "two of the tables have a column named a")
        self.assertLispError("(series-table 5)", "expected a list of tables")


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
                elif self.path.startswith("/fred?") and "series_id=NOPE" in self.path:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error_code":400,"error_message":"Bad Request.  The series does not exist."}')
                    return
                elif self.path.startswith("/alpha?") and "symbol=NOPE" in self.path:
                    body, kind = (b'{"Information": "Thank you for using Alpha Vantage! The limit for KEY123 is 25 requests a day."}'), "json"
                elif self.path.startswith("/alpha?") and "symbol=NONE" in self.path:
                    body, kind = b'{"symbol": "NONE", "data": []}', "json"
                elif self.path.startswith("/alpha?"):
                    body, kind = (b'{"symbol": "X", "data": ['
                                  b'{"ex_dividend_date": "2024-03-15", "declaration_date": "2024-02-01",'
                                  b' "record_date": "2024-03-16", "payment_date": "2024-04-01", "amount": "0.25"},'
                                  b'{"ex_dividend_date": "2023-12-14", "declaration_date": "None",'
                                  b' "record_date": "None", "payment_date": "None", "amount": "0.2"}]}'), "json"
                elif self.path == "/broken" or (self.path == "/flaky" and Handler.hits.count("/flaky") == 1):
                    self.send_response(503)                 # the server's own trouble (the first time, for /flaky)
                    self.end_headers()
                    self.wfile.write(b"try again later")
                    return
                elif self.path == "/flaky":
                    body, kind = b'{"ok": true}', "json"
                elif self.path.startswith("/fred?"):
                    body, kind = (b'{"observations": [{"date": "2024-01-01", "value": "5.33"},'
                                  b' {"date": "2024-02-01", "value": "."},'
                                  b' {"date": "2024-03-01", "value": "5.31"}]}'), "json"
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
        for patcher in (mock.patch.dict(os.environ, {"LISP_HTTP_CACHE": cache}),
                        mock.patch.object(lisp_http, "RETRY_SECONDS", 0)):
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

    def test_a_failure_that_may_pass_is_tried_once_more(self):
        self.assertShows('(hash-table-ref (http-get-json "%s/flaky") "ok")' % self.base, "#t")
        self.assertEqual(self.handler.hits, ["/flaky", "/flaky"])           # 503, then fine
        self.handler.hits.clear()
        self.assertLispError('(http-get-text "%s/broken")' % self.base, "HTTP 503")
        self.assertEqual(len(self.handler.hits), 2)
        self.handler.hits.clear()
        self.assertLispError('(http-get-text "%s/missing")' % self.base, "HTTP 404")
        self.assertEqual(len(self.handler.hits), 1)                         # a 404 won't pass: no second try

    def test_old_downloads_are_deleted(self):
        cache = os.environ["LISP_HTTP_CACHE"]
        now = time.time()
        for file_name, days in (("old", 40), ("recent", 10)):
            with open(os.path.join(cache, file_name), "w") as f:
                f.write("saved")
            os.utime(os.path.join(cache, file_name), (now - days * 24 * 3600,) * 2)
        self.run_lisp('(http-get-text "%s/data.json" 1)' % self.base)           # saving one cleans up
        remaining = os.listdir(cache)
        self.assertNotIn("old", remaining)
        self.assertIn("recent", remaining)
        self.assertEqual(len(remaining), 2)                                  # recent, and the new download

    def test_url_building(self):
        self.assertShows('(http-url "https://x.org/a" (list (cons "q" "a b&c") (cons "n" 5)))',
                         '"https://x.org/a?q=a+b%26c&n=5"')
        self.assertShows('(http-url "https://x.org/a?k=1" (list (cons "n" 5)))', '"https://x.org/a?k=1&n=5"')


# ---------------------------------------------------------------------------
# 13. Dates
# ---------------------------------------------------------------------------


    def test_fred_table_lines_series_up_by_date(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "credentials.json"), "w") as f:
            json.dump({"fred_api_key": "KEY123"}, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(folder, "credentials.json"))
        with mock.patch.object(lisp_fred, "FRED_URL", self.base + "/fred"):
            self.run_lisp('(define t (fred-table creds (list "SOFR" "DGS10") :start-date (date 2024 1 1)))')
            self.run_lisp('(fred-table creds (list "SOFR" "DGS10") :start-date (date 2024 1 1))')
            self.assertLispError('(fred-table creds "NOPE")', "fred-table: ")
        self.assertShows("(table-column-names t)", '("date" "SOFR" "DGS10")')
        self.assertShows('(table-column t "date")', "#(2024-01-01 2024-03-01)")      # FRED's "." is left out
        self.assertShows('(table-column t "DGS10")', "#(5.33 5.31)")
        fred_hits = [hit for hit in self.handler.hits if hit.startswith("/fred")]
        self.assertEqual(len(fred_hits), 3)                     # two series, then kept; then NOPE
        self.assertIn("observation_start=2024-01-01", fred_hits[0])

    def test_a_fred_error_says_what_fred_said_without_the_api_key(self):
        self.use_credentials({"fred_api_key": "KEY123"})
        with mock.patch.object(lisp_fred, "FRED_URL", self.base + "/fred"):
            with self.assertRaises(lisp_core.LispError) as cm:
                self.run_lisp('(fred-table creds "NOPE")')
        self.assertIn("The series does not exist", str(cm.exception))
        self.assertNotIn("KEY123", str(cm.exception))

    def use_credentials(self, entries):
        """creds, in the Lisp environment, is a credentials file with these entries."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "credentials.json"), "w") as f:
            json.dump(entries, f)
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString(os.path.join(folder, "credentials.json"))

    def test_alpha_vantage_dividends_are_a_table_oldest_first(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(define d (alpha-vantage-dividends creds "BRK/B"))')
        self.assertShows("(table-column-names d)",
                         '("ex-date" "declaration-date" "record-date" "payment-date" "amount")')
        self.assertShows('(table-column d "ex-date")', "#(2023-12-14 2024-03-15)")
        self.assertShows('(table-column d "declaration-date")', "#(() 2024-02-01)")      # "None" is missing
        self.assertShows('(table-column d "payment-date")', "#(() 2024-04-01)")
        self.assertShows('(table-column d "amount")', "#(0.2 0.25)")
        hit = [hit for hit in self.handler.hits if hit.startswith("/alpha")][0]
        self.assertIn("function=DIVIDENDS", hit)
        self.assertIn("symbol=BRK-B", hit)                      # as Alpha Vantage writes a share class
        self.assertIn("apikey=KEY123", hit)

    def test_a_stock_with_no_dividends_has_a_table_with_no_rows(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(define d (alpha-vantage-dividends creds "NONE"))')
        self.assertShows("(table-row-count d)", "0")
        self.assertShows("(length (table-column-names d))", "5")

    def test_alpha_vantage_says_why_without_the_api_key_and_a_problem_is_not_kept(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            for _ in range(2):
                with self.assertRaises(lisp_core.LispError) as cm:
                    self.run_lisp('(alpha-vantage-dividends creds "NOPE")')
                self.assertIn("Alpha Vantage says: Thank you for using Alpha Vantage! The limit for", str(cm.exception))
                self.assertNotIn("KEY123", str(cm.exception))
        self.assertEqual(len([hit for hit in self.handler.hits if hit.startswith("/alpha")]), 2)   # not cached

    def test_good_dividends_are_kept_for_a_while(self):
        self.use_credentials({"alpha_vantage_api_key": "KEY123"})
        with mock.patch.object(lisp_alpha_vantage, "ALPHA_VANTAGE_URL", self.base + "/alpha"):
            self.run_lisp('(alpha-vantage-dividends creds "X") (alpha-vantage-dividends creds "X")')
        self.assertEqual(len([hit for hit in self.handler.hits if hit.startswith("/alpha")]), 1)

    def test_alpha_vantage_needs_its_key_in_the_credentials_file(self):
        self.use_credentials({"fred_api_key": "x"})
        self.assertLispError('(alpha-vantage-dividends creds "X")', 'no "alpha_vantage_api_key" entry')

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


class TestLadRegression(LispTestCase):
    """lad-regression: least absolute deviation, which a few outliers
    barely move."""

    def test_an_outlier_pulls_least_squares_but_not_lad(self):
        # y = 2x + 1, except at x = 10
        self.run_lisp("(define x #(1 2 3 4 5 6 7 8 9 10))"
                      "(define y #(3 5 7 9 11 13 15 17 19 100))"
                      "(define m (lad-regression x y))")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        self.assertGreater(self.run_lisp("(model-slope (linear-regression x y))"), 5)
        self.assertShows("(model-kind m)", '"lad"')
        self.assertShows("(model-residuals m x y)", "#(0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 79.0)")

    def test_the_fit_is_the_least_absolute_deviation_one(self):
        """Some best fit goes through p of the points, so the best of all the
        fits through p points is the answer: compare with that, for many
        small data sets, with ties, repeated x values, and weights."""
        import itertools
        import numpy as np
        import lisp_regression
        rng = np.random.default_rng(1)
        for trial in range(150):
            n, k = int(rng.integers(4, 15)), int(rng.integers(1, 3))
            columns = rng.normal(size=(k, n)) * 10
            if trial % 4 == 0:
                columns = np.round(columns / 5)                 # repeated x values
            X = np.column_stack([np.ones(n), columns.T])
            if np.linalg.matrix_rank(X) < k + 1 or np.any(columns.std(axis=1) == 0):
                continue
            y = X @ rng.normal(size=k + 1) + rng.standard_t(2, size=n)
            if trial % 3 == 0:
                y = np.round(y)                                 # ties
            w = rng.uniform(0.5, 3, n) if trial % 2 else np.ones(n)
            model = lisp_regression.fit_lad(columns.tolist(), y.tolist(), w.tolist())
            best = min(float((w * abs(y - X @ np.linalg.solve(X[list(rows)], y[list(rows)]))).sum())
                       for rows in itertools.combinations(range(n), k + 1)
                       if abs(np.linalg.det(X[list(rows)])) > 1e-9)
            with self.subTest(trial=trial):
                self.assertTrue(model.stats["converged"])
                self.assertAlmostEqual(model.stats["sum_abs_deviations"] / best, 1.0, places=9)

    def test_weights_count_rows_as_copies(self):
        self.run_lisp("(define x #(1 2 3 4 5 6))"
                      "(define y #(2 3 7 8 13 12))"
                      "(define weighted (lad-regression x y #(1 3 1 1 2 1)))"
                      "(define copied (lad-regression #(1 2 2 2 3 4 5 5 6) #(2 3 3 3 7 8 13 13 12)))")
        self.assertAlmostEqual(self.run_lisp("(model-slope weighted)"), self.run_lisp("(model-slope copied)"))
        self.assertAlmostEqual(self.run_lisp("(model-intercept weighted)"),
                               self.run_lisp("(model-intercept copied)"))
        # a weight of 0 leaves a row out
        self.run_lisp("(define m (lad-regression #(1 2 3 4 5) #(3 5 7 9 500) #(1 1 1 1 0)))")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)

    def test_several_predictors(self):
        # y = 1 + 2a - 3b, but for one outlier
        self.run_lisp("(define a #(1 2 3 4 5 6 7 8))"
                      "(define b #(2 1 4 3 6 5 8 9))"
                      "(define y (+ 1 (* 2 a) (* -3 b)))"
                      "(vector-set! y 3 50)"
                      "(define m (lad-regression (list a b) y))")
        self.assertAlmostEqual(self.run_lisp("(model-intercept m)"), 1.0)
        c = self.run_lisp("(model-coefficients m)").items.tolist()
        self.assertAlmostEqual(c[0], 2.0)
        self.assertAlmostEqual(c[1], -3.0)
        self.assertAlmostEqual(self.run_lisp("(model-predict m (list 10 10))"), -9.0)

    def test_the_report_and_standard_errors_ignore_how_far_out_the_outlier_is(self):
        def report(outlier):
            return self.show('(model-report (lad-regression (list (cons "month" #(1 2 3 4 5 6 7 8 9 10))) '
                             '(cons "cpr" #(3 5.5 6.5 9 11 13.5 14.5 17 19 %s))))' % outlier)
        near, far = report(60), report(600)
        self.assertIn("Least absolute deviation model:  cpr = ", near)
        self.assertIn("month", near)
        self.assertIn("sum |residuals|", near)
        self.assertIn("iterations       = ", near)
        std_error_lines = [line for line in near.splitlines() if line.startswith(("  intercept", "  month"))]
        self.assertEqual(std_error_lines,
                         [line for line in far.splitlines() if line.startswith(("  intercept", "  month"))])

    def test_standard_errors_are_undefined_for_an_exact_fit(self):
        self.run_lisp("(define m (lad-regression #(1 2 3) #(3 5 7)))")
        self.assertShows('(table-column (model-coefficient-table m) "std_error")', "#(nan nan)")
        self.assertAlmostEqual(self.run_lisp("(model-slope m)"), 2.0)

    def test_errors(self):
        self.assertLispError("(lad-regression #(1) #(1))", "too few to fit 2 coefficients")
        self.assertLispError("(lad-regression #(1 2 3) #(1 2))", "must be the same length")
        self.assertLispError("(lad-regression #(2 2 2) #(1 2 3))", "no variation")
        self.assertLispError("(lad-regression #(1 2 3) #(1 2 3) #(1 -1 1))", "must not be negative")

    def test_model_residuals_works_for_every_kind_of_model(self):
        self.run_lisp("(define m (linear-regression #(1 2 3) #(1 3 2)))")
        self.assertShows("(model-residuals m #(1 2 3) #(1 3 2))", "#(-0.5 1.0 -0.5)")
        self.assertLispError("(model-residuals m (list #(1 2) #(3 4)) #(1 2))", "model has 1 predictor(s), but 2 given")


class TestOptionPrices(LispTestCase):
    """lisp_options.py: Black-Scholes-Merton, Black's formula, implied volatility, the Greeks, and
    American options by binomial tree."""

    def price(self, src):
        return float(self.run_lisp(src))

    def test_black_scholes_prices_the_textbook_option(self):
        # S = K = 100, a year, 5%, 20% volatility: the call is 10.4506 and the put 5.5735
        self.assertAlmostEqual(self.price('(bsm-price "call" 100 100 1 0.05 0.2)'), 10.450584, places=5)
        self.assertAlmostEqual(self.price('(bsm-price "put" 100 100 1 0.05 0.2)'), 5.573526, places=5)
        self.assertAlmostEqual(self.price('(bsm-price "Call" 100 100 1 0.05 0.2)'), 10.450584, places=5)    # any case
        self.assertAlmostEqual(self.price('(bsm-price #t 100 100 1 0.05 0.2)'), 10.450584, places=5)
        self.assertAlmostEqual(self.price("(normal-cdf 0)"), 0.5, places=12)
        self.assertAlmostEqual(self.price("(normal-cdf 1.96)"), 0.9750021, places=6)

    def test_put_call_parity_holds_with_a_dividend_yield(self):
        call = self.price('(bsm-price "call" 100 110 0.75 0.04 0.3 :dividend-yield 0.02)')
        put = self.price('(bsm-price "put" 100 110 0.75 0.04 0.3 :dividend-yield 0.02)')
        self.assertAlmostEqual(call - put, 100 * math.exp(-0.02 * 0.75) - 110 * math.exp(-0.04 * 0.75), places=8)

    def test_black_s_formula_is_bsm_on_the_forward(self):
        forward, discount = 100 * math.exp(0.04 * 0.5), math.exp(-0.04 * 0.5)
        self.assertAlmostEqual(self.price('(black-price "put" %r 95 0.5 %r 0.25)' % (forward, discount)),
                               self.price('(bsm-price "put" 100 95 0.5 0.04 0.25)'), places=10)

    def test_vectors_price_many_options_at_once(self):
        prices = self.run_lisp('(bsm-price (vector "Call" "Put") 100 #(95 105) 0.5 0.04 0.25)')
        self.assertEqual(len(prices.items), 2)
        self.assertAlmostEqual(float(prices.items[1]), self.price('(bsm-price "put" 100 105 0.5 0.04 0.25)'), places=4)
        self.assertLispError('(bsm-price "call" 100 #(95 105 110) 0.5 0.04 #(0.2 0.3))', "the same length")

    def test_implied_volatility_gives_back_the_volatility(self):
        self.assertAlmostEqual(self.price('(implied-vol (bsm-price "put" 100 90 0.25 0.03 0.4) "put" 100 90 0.25 0.03)'),
                               0.4, places=9)
        vols = self.run_lisp("(black-implied-vol #(1 0) (black-price #(1 0) 100 #(110 95) 0.25 0.99 #(0.25 0.4)) "
                             "100 #(110 95) 0.25 0.99)")
        np.testing.assert_allclose(np.array(vols.items, dtype=float), [0.25, 0.4], atol=1e-6)
        self.assertShows('(implied-vol 1.0 "call" 100 90 0.5 0.0)', "nan")      # below what it pays now: no volatility

    def test_the_greeks_are_the_derivatives_of_the_price(self):
        h = 1e-4

        def bsm(kind, spot=100.0, time=0.5, rate=0.04, vol=0.25):
            return self.price('(bsm-price "%s" %r 105 %r %r %r :dividend-yield 0.01)' % (kind, spot, time, rate, vol))
        for kind in ("call", "put"):
            greek = lambda name: self.price('(bsm-%s "%s" 100 105 0.5 0.04 0.25 :dividend-yield 0.01)' % (name, kind))
            with self.subTest(kind=kind):
                self.assertAlmostEqual(greek("delta"), (bsm(kind, spot=100 + h) - bsm(kind, spot=100 - h)) / (2 * h), places=6)
                self.assertAlmostEqual(greek("gamma"), (bsm(kind, spot=100 + h) - 2 * bsm(kind) + bsm(kind, spot=100 - h)) / h ** 2,
                                       places=3)
                self.assertAlmostEqual(greek("vega"), (bsm(kind, vol=0.25 + h) - bsm(kind, vol=0.25 - h)) / (2 * h) / 100,
                                       places=6)          # for a volatility point
                self.assertAlmostEqual(greek("theta"), -(bsm(kind, time=0.5 + h) - bsm(kind, time=0.5 - h)) / (2 * h) / 365,
                                       places=6)          # for a day
                self.assertAlmostEqual(greek("rho"), (bsm(kind, rate=0.04 + h) - bsm(kind, rate=0.04 - h)) / (2 * h) / 100,
                                       places=6)          # for a point of interest

    def test_an_american_put_is_worth_more_than_a_european_one(self):
        american = self.price('(american-price "put" 100 100 1 0.05 0.2)')
        self.assertAlmostEqual(american, 6.09, delta=0.01)                     # the textbook value
        european = self.price('(american-price "put" 100 100 1 0.05 0.2 :early-exercise #f)')
        self.assertAlmostEqual(european, self.price('(bsm-price "put" 100 100 1 0.05 0.2)'), delta=0.015)   # the tree's error
        self.assertGreater(american - european, 0.4)

    def test_an_american_call_without_dividends_is_never_exercised_early(self):
        self.assertAlmostEqual(self.price('(american-price "call" 100 100 1 0.05 0.2)'),
                               self.price('(american-price "call" 100 100 1 0.05 0.2 :early-exercise #f)'), places=10)

    def test_a_dividend_can_make_it_worth_exercising_a_call_early(self):
        dividends = '(make-table "time" #(0.5) "amount" #(5.0))'
        american = self.price('(american-price "call" 100 100 1 0.05 0.2 :dividends %s)' % dividends)
        european = self.price('(american-price "call" 100 100 1 0.05 0.2 :dividends %s :early-exercise #f)' % dividends)
        self.assertGreater(american - european, 0.2)
        # the European one is Black's formula on the price less the dividend's present value
        forward = (100 - 5 * math.exp(-0.05 * 0.5)) * math.exp(0.05)
        self.assertAlmostEqual(european, self.price('(black-price "call" %r 100 1 %r 0.2)' % (forward, math.exp(-0.05))),
                               delta=0.02)
        later = self.price('(american-price "call" 100 100 0.4 0.05 0.2 :dividends %s)' % dividends)
        self.assertAlmostEqual(later, self.price('(bsm-price "call" 100 100 0.4 0.05 0.2)'), delta=0.02)   # (it's after expiring)

    def test_american_implied_volatility_gives_back_the_volatility(self):
        self.assertAlmostEqual(self.price('(american-implied-vol (american-price "put" 100 110 0.5 0.04 0.3 :steps 100) '
                                          '"put" 100 110 0.5 0.04 :steps 100)'), 0.3, places=7)

    def test_what_the_option_functions_wont_take(self):
        self.assertLispError('(bsm-price "straddle" 100 100 1 0.05 0.2)', 'an option type is "call" or "put"')
        self.assertLispError('(bsm-price "call" "100" 100 1 0.05 0.2)', "spot must be a number or a vector")
        self.assertLispError('(bsm-price "call" 100 100 1 0.05 0.2 :dividend-yield "2%")', ":dividend-yield must be a number")
        self.assertLispError('(bsm-delta "call" 100 100 0 0.05 0.2)', "the time and the volatility must be above 0")
        self.assertLispError('(american-price "put" 100 100 1 0.05 0.2 :steps 0)', ":steps must be a whole number")
        self.assertLispError('(american-price "put" 100 100 1 0.9 0.01 :steps 2)', "too few")
        self.assertLispError('(american-price "put" 100 100 1 0.05 0.2 :dividends (make-table "when" #(0.5) "amount" #(1.0)))',
                             "no column named 'time'")


class TestVolSmile(LispTestCase):
    """lib/vol_smile.lsp, on a made-up option chain whose implied volatilities
    follow a known smile, Y = a + b K + c K^2 for each expiration, with one
    option priced 2 volatility points too high."""

    RATE = 0.045
    SPOT = 100.0
    SMILES = {30: (0.0033, -0.02, 0.10), 60: (0.0066, -0.03, 0.12), 90: (0.0099, -0.035, 0.11)}

    @staticmethod
    def black(call, forward, strike, T, discount, vol):
        """Black's formula, written independently of vol_smile.lsp's."""
        N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        d1 = math.log(forward / strike) / (vol * math.sqrt(T)) + vol * math.sqrt(T) / 2
        d2 = d1 - vol * math.sqrt(T)
        if call:
            return discount * (forward * N(d1) - strike * N(d2))
        return discount * (strike * N(-d2) - forward * N(-d1))

    def chain(self, smiles=None):
        """The made-up chain, as a table with the columns vol_smile.lsp uses."""
        columns = {name: [] for name in ("symbol", "type", "strike", "expiration-date", "days-to-expiration",
                                         "underlying-price", "bid", "ask", "mid", "volume", "open-interest")}
        for days, smile in (smiles or self.SMILES).items():
            T = days / 365
            discount = math.exp(-self.RATE * T)
            forward = self.SPOT / discount
            expiration = datetime.date(2099, 1, 1) + datetime.timedelta(days=days)
            for strike in range(85, 120, 5):
                for kind in ("Call", "Put"):
                    K = math.log(strike / forward)
                    vol = math.sqrt(smile(T, K) / T) if callable(smile) else \
                        math.sqrt((smile[0] + smile[1] * K + smile[2] * K * K) / T)
                    symbol = "XYZ %dd %s%d" % (days, kind[0], strike)
                    if symbol == "XYZ 30d C110":
                        vol += 0.02                          # the option out of line
                    mid = self.black(kind == "Call", forward, strike, T, discount, vol)
                    for name, value in (("symbol", lisp_core.LispString(symbol)),
                                        ("type", lisp_core.LispString(kind)), ("strike", float(strike)),
                                        ("expiration-date", lisp_core.LispDate(expiration.year, expiration.month,
                                                                               expiration.day)),
                                        ("days-to-expiration", days), ("underlying-price", self.SPOT),
                                        ("bid", mid - 0.002), ("ask", mid + 0.002), ("mid", mid),
                                        ("volume", 0 if symbol == "XYZ 60d C115" else 10),
                                        ("open-interest", 100)):
                        columns[name].append(value)
        return lisp_tables.make_table_value([(name, lisp_core.LispVector(values))
                                              for name, values in columns.items()])

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "vol_smile.lsp")')

    def test_dividends_present_value_counts_those_after_the_date_and_before_each_expiration(self):
        self.run_lisp("""(define dividends (list (cons "ex-date" (vector (date 2026 1 10) (date 2026 3 10) (date 2026 6 10)))
                                                (cons "amount" (vector 1.0 2.0 4.0))))""")
        values = self.run_lisp("(dividends-present-value (vector (date 2026 2 1) (date 2026 5 1) (date 2026 12 1)) 0.05 "
                               "dividends (date 2026 2 1))").items
        march = 2.0 * math.exp(-0.05 * 37 / 365)                 # (the one in January is before the date)
        june = 4.0 * math.exp(-0.05 * 129 / 365)
        np.testing.assert_allclose(np.array(values, dtype=float), [0.0, march, march + june], rtol=1e-6)
        self.assertShows("(dividends-present-value (vector (date 2026 5 1)) 0.05 '() (date 2026 2 1))", "#(0.0)")

    def test_black_price_and_implied_volatility(self):
        self.assertAlmostEqual(self.run_lisp("(vector-ref (black-price #(1) #(100) #(100) #(1) #(1) #(0.2)) 0)"),
                               7.965567, places=4)
        self.assertAlmostEqual(self.run_lisp("(vector-ref (black-price #(0) #(100) #(90) #(0.5) #(0.98) #(0.3)) 0)"),
                               self.black(False, 100, 90, 0.5, 0.98, 0.3), places=4)
        vols = self.run_lisp("(black-implied-vol #(1 0) (black-price #(1 0) #(100 100) #(110 95) #(0.25 0.25) "
                             "#(0.99 0.99) #(0.25 0.4)) #(100 100) #(110 95) #(0.25 0.25) #(0.99 0.99))")
        self.assertAlmostEqual(float(vols.items[0]), 0.25, places=5)
        self.assertAlmostEqual(float(vols.items[1]), 0.4, places=5)
        # a price below what the option is worth at expiration fits no volatility
        self.assertShows("(black-implied-vol #(1) #(5) #(110) #(100) #(0.5) #(1))", "#(nan)")

    def test_each_expirations_smile_is_found_and_the_option_out_of_line_is_rich(self):
        self.env[lisp_core.Symbol("chain")] = self.chain()
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045))"
                      "(define options (vol-smile-fit-options fit))"
                      "(define expirations (vol-smile-fit-expirations fit))")
        def column(table, name):
            return self.run_lisp('(table-column %s "%s")' % (table, name)).items.tolist()
        for i, (days, (a, b, c)) in enumerate(sorted(self.SMILES.items())):
            with self.subTest(days=days):
                self.assertAlmostEqual(column("expirations", "intercept")[i], a, places=5)
                self.assertAlmostEqual(column("expirations", "K")[i], b, places=4)
                self.assertAlmostEqual(column("expirations", "K^2")[i], c, places=3)
                self.assertAlmostEqual(column("expirations", "atm-vol")[i], math.sqrt(a / (days / 365)), places=4)
                self.assertAlmostEqual(column("expirations", "parity-forward")[i] / column("expirations", "forward")[i],
                                       1.0, places=5)
        signals = dict(zip(column("options", "symbol"), column("options", "signal")))
        self.assertEqual({symbol: signal for symbol, signal in signals.items() if signal}, {"XYZ 30d C110": "rich"})
        self.run_lisp('(define out (table-filter options (= (table-column options "symbol") "XYZ 30d C110")))')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column out "iv-residual") 0)'), 0.02, places=3)
        T, discount = 30 / 365, math.exp(-self.RATE * 30 / 365)
        a, b, c = self.SMILES[30]
        K = math.log(110 / (100 / discount))
        true_price = self.black(True, 100 / discount, 110, T, discount, math.sqrt((a + b * K + c * K * K) / T))
        self.assertAlmostEqual(self.run_lisp('(vector-ref (table-column out "model-price") 0)'), true_price, places=3)
        # only liquid, out-of-the-money options: no 60-day 115 call (no volume), and
        # no calls below the forward or puts above it
        self.assertShows('(vector-length (vector-select (table-column options "symbol") '
                         '(= (table-column options "symbol") "XYZ 60d C115")))', "0")
        self.assertShows('(vector-sum (vector-and (= (table-column options "type") "Put") '
                         '(> (table-column options "K") 0)))', "0")

    def test_all_the_expirations_at_once(self):
        """With five terms and three expirations, one fit to them all."""
        def smile(T, K):
            return 0.001 + 0.03 * T + 0.002 * math.sqrt(T) - 0.01 * K - 0.04 * K * math.sqrt(T) + 0.1 * K * K
        self.env[lisp_core.Symbol("chain")] = self.chain({30: smile, 60: smile, 90: smile})
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045 :by-expiration #f))")
        self.assertEqual(len(lisp_core.pairs_to_list(self.run_lisp("(vol-smile-fit-models fit)"))), 3)
        coefficients = self.run_lisp("(model-coefficients (cdr (car (vol-smile-fit-models fit))))").items.tolist()
        for found, expected in zip(coefficients, [0.03, 0.002, -0.01, -0.04, 0.1]):
            self.assertAlmostEqual(found, expected, places=3)
        self.assertShows("(table-column-names (vol-smile-fit-expirations fit))",
                         '("expiration-date" "days" "forward" "parity-forward" "options" "atm-vol" "intercept" '
                         '"T" "sqrt(T)" "K" "K*sqrt(T)" "K^2")')

    def test_the_example_runs(self):
        """examples/vol_smile_example.lsp, with the made-up chain in place of
        tastytrade's."""
        chain = self.chain()
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda *args: chain
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("no-credentials-needed.json")
        lisp_core.run_file(os.path.join(EXAMPLES, "vol_smile_example.lsp"), self.env)
        out = self.printed()
        rich = out.split("ask below it (cheap):\n")[1].split("\n\n")[0]
        self.assertEqual([line.split("  ")[0] for line in rich.splitlines()[2:]], ["XYZ 30d C110"])
        self.assertIn("Least absolute deviation model:  Y = ", out)
        self.assertIn("[chart] Implied volatility, ", out)

    def test_too_few_options_and_unknown_terms(self):
        self.env[lisp_core.Symbol("chain")] = self.chain()
        self.run_lisp("(define fit (fit-vol-smiles chain :rate 0.045 :max-vol-spread 0.0001))")
        self.assertShows('(table-column (vol-smile-fit-expirations fit) "intercept")', "#(nan nan nan)")
        self.assertShows("(table-row-count (vol-smile-fit-options fit))", "0")
        self.assertLispError('(fit-vol-smiles chain :terms (list "K^3"))', "there's no term K^3")


class TestTradingCalendar(LispTestCase):
    """lisp_calendar.py: the NYSE's trading days."""

    def holidays(self, year):
        return self.show("(nyse-holidays %d)" % year)

    def vector_of(self, *dates):
        return "#(" + " ".join(dates) + ")"

    def test_the_holidays_the_nyse_publishes_for_2026_through_2028(self):
        # from https://www.nyse.com/trade/hours-calendars, read on 2026-10-07
        self.assertEqual(self.holidays(2026), self.vector_of(
            "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
            "2026-09-07", "2026-11-26", "2026-12-25"))
        self.assertEqual(self.holidays(2027), self.vector_of(
            "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
            "2027-09-06", "2027-11-25", "2027-12-24"))
        self.assertEqual(self.holidays(2028), self.vector_of(              # (January 1 is a Saturday: not kept)
            "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
            "2028-11-23", "2028-12-25"))

    def test_holidays_of_other_years(self):
        self.assertEqual(self.holidays(2021), self.vector_of(              # no Juneteenth yet
            "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31", "2021-07-05", "2021-09-06",
            "2021-11-25", "2021-12-24"))
        self.assertEqual(self.holidays(2022), self.vector_of(
            "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30", "2022-06-20", "2022-07-04", "2022-09-05",
            "2022-11-24", "2022-12-26"))
        self.assertEqual(self.holidays(2023), self.vector_of(              # January 1 is a Sunday: the 2nd
            "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19", "2023-07-04",
            "2023-09-04", "2023-11-23", "2023-12-25"))
        self.assertEqual(self.show("(vector-length (nyse-holidays 1997))"), "8")      # no Martin Luther King Jr. Day yet

    def test_easter_is_right_for_good_friday(self):
        for year, good_friday in ((2000, "2000-04-21"), (2019, "2019-04-19"), (2024, "2024-03-29"),
                                  (2025, "2025-04-18"), (2038, "2038-04-23")):
            with self.subTest(year=year):
                self.assertIn(good_friday, self.holidays(year))

    def test_trading_days(self):
        for day, answer in (("(date 2026 10 7)", "#t"),                  # an ordinary Wednesday
                            ("(date 2026 10 10)", "#f"),                 # a Saturday
                            ("(date 2026 10 11)", "#f"),                 # a Sunday
                            ("(date 2026 11 26)", "#f"),                 # Thanksgiving
                            ("(date 2026 11 27)", "#t"),                 # the day after, closing early
                            ("(date 2026 7 3)", "#f"),                   # July 4 is a Saturday
                            ("(date 2027 12 31)", "#t")):                # January 1, 2028 is a Saturday, not kept
            self.assertShows("(trading-day? %s)" % day, answer)

    def test_the_next_trading_day(self):
        self.assertShows("(next-trading-day (date 2026 10 7))", "2026-10-07")
        self.assertShows("(next-trading-day (date 2026 11 14))", "2026-11-16")          # a Saturday
        self.assertShows("(next-trading-day (date 2026 11 26))", "2026-11-27")          # Thanksgiving
        self.assertShows("(next-trading-day (date 2027 2 13))", "2027-02-16")           # a Saturday, then a holiday

    def test_adding_trading_days(self):
        for start, n, answer in (((2026, 11, 20), 1, "2026-11-23"),       # a Friday: the Monday
                                 ((2026, 11, 20), 3, "2026-11-25"),
                                 ((2026, 11, 20), 4, "2026-11-27"),       # over Thanksgiving
                                 ((2026, 11, 30), -1, "2026-11-27"),
                                 ((2026, 11, 30), -2, "2026-11-25"),
                                 ((2026, 11, 21), 1, "2026-11-23"),       # from a Saturday
                                 ((2026, 11, 21), -1, "2026-11-20"),
                                 ((2026, 11, 21), 0, "2026-11-21")):      # (itself, trading day or not)
            with self.subTest(start=start, n=n):
                self.assertShows("(add-trading-days (date %d %d %d) %d)" % (start + (n,)), answer)

    def test_counting_trading_days(self):
        self.assertShows("(trading-days-between (date 2026 11 20) (date 2026 11 23))", "1")    # Friday to Monday
        self.assertShows("(trading-days-between (date 2026 11 20) (date 2026 11 30))", "5")    # over Thanksgiving
        self.assertShows("(trading-days-between (date 2026 11 20) (date 2026 11 20))", "0")
        self.assertShows("(trading-days-between (date 2026 11 23) (date 2026 11 20))", "-1")
        self.assertShows("(trading-days-between (date 2026 11 21) (date 2026 11 22))", "0")    # a weekend
        self.assertShows("(trading-days-between (date 2025 12 31) (date 2026 12 31))", "251")  # 261 weekdays less 10 holidays

    def test_adding_and_counting_agree(self):
        # (counting back from a day the market is closed isn't the opposite of counting forward: the
        # trading days "after" a Saturday don't include that Saturday's own Friday)
        for start, counts in (("(date 2026 10 5)", (-300, -7, -1, 1, 5, 252, 700)),
                              ("(date 2026 11 21)", (1, 5, 252, 700)),         # a Saturday
                              ("(date 2027 12 24)", (1, 5, 252, 700))):        # Christmas, kept on a Friday
            for n in counts:
                with self.subTest(start=start, n=n):
                    self.assertShows("(trading-days-between %s (add-trading-days %s %d))" % (start, start, n), str(n))

    def test_what_the_calendar_wont_take(self):
        self.assertLispError("(trading-day? 5)", "the date must be a date, or YYYY-MM-DD text")
        self.assertShows('(next-trading-day "2026-10-10")', "2026-10-12")         # (text is a date too)
        self.assertLispError('(next-trading-day "October 10")', "must be a date")
        self.assertLispError("(add-trading-days (date 2026 10 7) 2.5)", "whole number")
        self.assertLispError("(add-trading-days (date 2026 10 7) #t)", "whole number")
        self.assertLispError("(trading-days-between (date 2026 10 7) 3)", "the end must be a date")
        self.assertLispError("(nyse-holidays 2026.0)", "the year must be a whole number")
        self.assertLispError("(nyse-holidays 0)", "the year must be a whole number")


class TestInvestmentPaths(LispTestCase):
    """lisp_investment_paths.py: daily-returns, adjust-returns, and bootstrap-path."""

    PRICES = """(define prices (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3) (date 2024 1 4)
                                                     (date 2024 1 5) (date 2024 1 8)))
                                    (cons "close" (vector 100.0 110.0 99.0 99.0 108.9))))"""
    # (a Saturday's ex-date, the 6th, goes with the next day there's a price, the 8th)
    DIVIDENDS = """(define dividends (list (cons "ex-date" (vector (date 2023 12 1) (date 2024 1 4)
                                                               (date 2024 1 6) (date 2024 2 1)))
                                           (cons "amount" (vector 5.0 1.0 2.0 7.0))))"""

    def numbers(self, src):
        return [float(x) for x in self.run_lisp(src).items]

    def assertNumbers(self, src, expected, places=6):
        actual = self.numbers(src)
        self.assertEqual(len(actual), len(expected), msg=src)
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=places, msg=src)

    def make_returns(self, name, values):
        """A table of log returns, called `name` in the Lisp environment."""
        table = lisp_tables.make_table_value([("log-return", lisp_vector_math.to_vector(np.array(values)))])
        self.env[lisp_core.Symbol(name)] = table

    def a_year_of_returns(self, name="history"):
        self.make_returns(name, np.random.default_rng(1).normal(0.0008, 0.012, 400))

    # -- daily-returns ------------------------------------------------------

    def test_daily_returns_are_log_returns_from_the_second_day(self):
        self.run_lisp(self.PRICES)
        self.assertShows("(table-column-names (daily-returns prices))", '("date" "log-return")')
        self.assertShows('(table-column (daily-returns prices) "date")', "#(2024-01-03 2024-01-04 2024-01-05 2024-01-08)")
        self.assertNumbers('(table-column (daily-returns prices) "log-return")',
                           [math.log(1.1), math.log(0.9), 0.0, math.log(1.1)])

    def test_a_dividend_is_part_of_the_return_of_the_day_it_goes_ex(self):
        self.run_lisp(self.PRICES + self.DIVIDENDS)
        self.assertNumbers('(table-column (daily-returns prices :dividends dividends) "log-return")',
                           [math.log(1.1), math.log((99 + 1) / 110), 0.0, math.log((108.9 + 2) / 99)])
        # (the ones before the first price and after the last count for nothing)

    def test_dividends_on_one_day_add_up(self):
        self.run_lisp(self.PRICES + """(define dividends (list (cons "ex-date" (vector (date 2024 1 4) (date 2024 1 4)))
                                                              (cons "amount" (vector 1.0 0.5))))""")
        self.assertNumbers('(table-column (daily-returns prices :dividends dividends) "log-return")',
                           [math.log(1.1), math.log((99 + 1.5) / 110), 0.0, math.log(1.1)])

    def test_no_dividends_changes_nothing(self):
        self.run_lisp(self.PRICES + """(define none (list (cons "ex-date" (vector)) (cons "amount" (vector))))""")
        plain = self.show("(daily-returns prices)")
        self.assertEqual(self.show("(daily-returns prices :dividends none)"), plain)
        self.assertEqual(self.show("(daily-returns prices :dividends '())"), plain)

    def test_what_daily_returns_wont_take(self):
        self.run_lisp(self.PRICES + self.DIVIDENDS)
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 3) (date 2024 1 2)))
                                                      (cons "close" (vector 1.0 2.0))))""", "oldest first")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 2)))
                                                      (cons "close" (vector 1.0 2.0))))""", "oldest first")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3)))
                                                      (cons "close" (vector 1.0 0.0))))""", "above 0")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2) (date 2024 1 3)))
                                                      (cons "close" (vector 1.0 nan))))""", "above 0")
        self.assertLispError("""(daily-returns (list (cons "date" (vector (date 2024 1 2)))
                                                      (cons "close" (vector 1.0))))""", "at least two prices")
        self.assertLispError('(daily-returns (table-drop-columns prices "close"))', "no column named 'close'")
        self.assertLispError('(daily-returns prices :dividends (table-drop-columns dividends "amount"))',
                             "no column named 'amount'")
        self.assertLispError("""(daily-returns prices :dividends (list (cons "ex-date" (vector (date 2024 1 4)))
                                                                      (cons "amount" (vector -1.0))))""", "0 or more")
        self.assertLispError("(daily-returns prices :dividend dividends)", ":dividend isn't an option")

    # -- adjust-returns -----------------------------------------------------

    def test_the_adjusted_returns_average_what_was_asked(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column adjusted "log-return")))')
        self.assertAlmostEqual(average_growth, 1.08 ** (1 / 252), places=7)
        self.run_lisp("(define in-days (adjust-returns history -0.5 :days-per-year 365))")
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column in-days "log-return")))')
        self.assertAlmostEqual(average_growth, 0.5 ** (1 / 365), places=7)

    def test_adjusting_moves_the_returns_without_spreading_them(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        before = self.run_lisp('(vector-stdev (table-column history "log-return"))')
        self.assertAlmostEqual(self.run_lisp('(vector-stdev (table-column adjusted "log-return"))'), before, places=7)
        self.assertShows("(table-row-count adjusted)", "400")

    def test_a_volatility_scale_spreads_the_returns_and_keeps_the_average_return(self):
        self.a_year_of_returns()
        self.run_lisp("(define scaled (adjust-returns history 0.08 :volatility-scale 1.5))")
        before = self.run_lisp('(vector-stdev (table-column history "log-return"))')
        self.assertAlmostEqual(self.run_lisp('(vector-stdev (table-column scaled "log-return"))'), 1.5 * before, places=6)
        average_growth = self.run_lisp('(vector-mean (vector-exp (table-column scaled "log-return")))')
        self.assertAlmostEqual(average_growth, 1.08 ** (1 / 252), places=7)
        self.run_lisp("(define unscaled (adjust-returns history 0.08 :volatility-scale 1))")
        self.assertEqual(self.show('(table-column unscaled "log-return")'),
                         self.show('(table-column (adjust-returns history 0.08) "log-return")'))

    def test_adjusting_keeps_the_other_columns(self):
        self.run_lisp(self.PRICES + "(define adjusted (adjust-returns (daily-returns prices) 0.08))")
        self.assertShows("(table-column-names adjusted)", '("date" "log-return")')
        self.assertShows('(table-column adjusted "date")', "#(2024-01-03 2024-01-04 2024-01-05 2024-01-08)")

    def test_what_adjust_returns_wont_take(self):
        self.a_year_of_returns()
        self.assertLispError("(adjust-returns history -1)", "above -1")
        self.assertLispError('(adjust-returns history "8%")', "above -1")
        self.assertLispError("(adjust-returns history 0.08 :days-per-year 0)", ":days-per-year must be a number above 0")
        self.assertLispError("(adjust-returns (list (cons \"x\" (vector 1.0))) 0.08)", "no column named 'log-return'")
        self.assertLispError("(adjust-returns history 0.08 :days 252)", ":days isn't an option")
        self.assertLispError("(adjust-returns history 0.08 :volatility-scale 0)", ":volatility-scale must be a number above 0")
        self.assertLispError('(adjust-returns history 0.08 :volatility-scale "2")', ":volatility-scale must be a number above 0")

    # -- bootstrap-path -----------------------------------------------------

    def log_returns_along(self, path, start_price):
        """The log return of each step of a path (a LispVector of prices)."""
        return np.diff(np.log(np.concatenate([[start_price], np.array(path.items, dtype=np.float64)])))

    def test_a_path_is_blocks_of_consecutive_returns_that_wrap_around(self):
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        self.make_returns("five", returns)
        for seed in range(30):
            path = self.run_lisp("(bootstrap-path five 100 7 3 :seed %d)" % seed)
            self.assertEqual(len(path.items), 7)
            steps = self.log_returns_along(path, 100)
            which = [int(np.argmin(np.abs(np.array(returns) - step))) for step in steps]
            for step, day in zip(steps, which):
                self.assertAlmostEqual(step, returns[day], places=5)
            for block in (0, 3):                                # two blocks of 3, then one day of a third
                self.assertEqual(which[block + 1], (which[block] + 1) % 5)
                self.assertEqual(which[block + 2], (which[block] + 2) % 5)

    def test_every_start_is_possible_including_the_last_days_of_the_history(self):
        self.make_returns("three", [0.01, 0.02, 0.03])
        turns = set()
        for seed in range(40):
            path = self.run_lisp("(bootstrap-path three 100 3 3 :seed %d)" % seed)
            turns.add(tuple(np.round(self.log_returns_along(path, 100), 2)))
        self.assertEqual(turns, {(0.01, 0.02, 0.03), (0.02, 0.03, 0.01), (0.03, 0.01, 0.02)})

    def test_a_path_has_the_days_asked_for(self):
        self.a_year_of_returns()
        for days, block in ((252, 10), (1, 10), (10, 10), (11, 10), (5, 1), (400, 400)):
            with self.subTest(days=days, block=block):
                self.assertShows("(vector-length (bootstrap-path history 50 %d %d))" % (days, block), str(days))

    def test_a_seed_gives_the_same_path_every_time(self):
        self.a_year_of_returns()
        path = lambda seed: self.show("(bootstrap-path history 100 50 5 :seed %d)" % seed)
        self.assertEqual(path(3), path(3))
        self.assertNotEqual(path(3), path(4))

    def test_without_a_seed_the_paths_come_from_the_shared_generator(self):
        self.a_year_of_returns()
        self.run_lisp("(random-seed 7)")
        first = self.show("(bootstrap-path history 100 50 5)")
        second = self.show("(bootstrap-path history 100 50 5)")
        self.assertNotEqual(first, second)
        self.run_lisp("(random-seed 7)")
        self.assertEqual(self.show("(bootstrap-path history 100 50 5)"), first)

    def test_a_seeded_path_leaves_the_shared_generator_alone(self):
        self.a_year_of_returns()
        self.run_lisp("(random-seed 7)")
        expected = self.run_lisp("(random-float)")
        self.run_lisp("(random-seed 7)")
        self.run_lisp("(bootstrap-path history 100 50 5 :seed 1)")
        self.assertEqual(self.run_lisp("(random-float)"), expected)

    def test_the_expected_price_after_a_year_is_the_expected_return(self):
        self.a_year_of_returns()
        self.run_lisp("(define adjusted (adjust-returns history 0.08))")
        # exactly right for blocks of one day (the 4000 paths' average is within about 0.003 of it,
        # while leaving out the adjustment for the log returns' spread is off by 0.02); for longer
        # blocks it depends on the history's own ups and downs in a row, so only close
        for block, delta in ((1, 0.008), (21, 0.03)):
            with self.subTest(block=block):
                finals = self.run_lisp("""(vector-mean (list->vector
                    (map (lambda (i) (vector-ref (bootstrap-path adjusted 100 252 %d :seed i) 251))
                         (iota 4000))))""" % block)
                self.assertAlmostEqual(finals / 100, 1.08, delta=delta)

    def test_what_bootstrap_path_wont_take(self):
        self.make_returns("five", [0.01, 0.02, 0.03, 0.04, 0.05])
        self.assertLispError("(bootstrap-path five 100 0 3)", "days must be a whole number, 1 or more")
        self.assertLispError("(bootstrap-path five 100 2.5 3)", "days must be a whole number")
        self.assertLispError("(bootstrap-path five 100 7 0)", "block-size must be a whole number, 1 or more")
        self.assertLispError("(bootstrap-path five 100 7 6)", "block-size 6 is more than the 5 returns")
        self.assertLispError("(bootstrap-path five 0 7 3)", "start price must be a number above 0")
        self.assertLispError('(bootstrap-path five "100" 7 3)', "start price must be a number above 0")
        self.assertLispError("(bootstrap-path five 100 7 3 :seed -1)", ":seed must be a whole number, 0 or more")
        self.assertLispError("(bootstrap-path five 100 7 3 :seed 1.5)", ":seed must be a whole number")
        self.assertLispError("(bootstrap-path five 100 7 3 :wrap #f)", ":wrap isn't an option")
        self.assertLispError('(bootstrap-path (list (cons "x" (vector 1.0))) 100 7 3)', "no column named 'log-return'")
        self.assertLispError('(bootstrap-path (list (cons "log-return" (vector 0.01 nan))) 100 7 1)', "not missing or infinite")
        self.assertLispError('(bootstrap-path (list (cons "log-return" (vector))) 100 7 1)', "there are no returns")

    # -- option-value -------------------------------------------------------

    def make_paths(self, count=3000, rate=0.04, block=1):
        """`paths`, in the Lisp environment: paths of a year growing at the interest rate."""
        self.a_year_of_returns()
        self.run_lisp("(define paths (map (lambda (i) (bootstrap-path (adjust-returns history (- (exp %s) 1)) 100 252 %d :seed i))"
                      "                   (iota %d)))" % (rate, block, count))

    def final_prices(self):
        return self.numbers("(list->vector (map (lambda (path) (vector-ref path 251)) paths))")

    def value_and_error(self, src):
        """The two numbers in an (option-value ...)'s answer."""
        value, error = lisp_core.pairs_to_list(self.run_lisp(src))
        return float(value), float(error)

    def test_a_payoff_is_discounted_for_the_years_at_the_interest_rate(self):
        self.make_paths(count=10)
        value, error = self.value_and_error("(option-value paths (lambda (path) 5) 0.04 2)")
        self.assertAlmostEqual(value, 5 * math.exp(-0.08), places=9)
        self.assertAlmostEqual(error, 0.0, places=9)

    def test_the_value_is_the_discounted_average_payoff_and_its_error_the_standard_error(self):
        self.make_paths(count=500)
        finals = np.array(self.final_prices())
        calls = np.maximum(finals - 100, 0) * math.exp(-0.05 * 1.5)
        value, error = self.value_and_error(
            "(option-value paths (lambda (path) (max 0 (- (vector-ref path 251) 100))) 0.05 1.5)")
        self.assertAlmostEqual(value, calls.mean(), places=5)
        self.assertAlmostEqual(error, calls.std(ddof=1) / math.sqrt(500), places=5)

    def test_a_payoff_can_depend_on_the_whole_path(self):
        self.make_paths(count=200)
        value, _ = self.value_and_error("(option-value paths (lambda (path) (max 0 (- (vector-mean path) 100))) 0 1)")
        by_hand = self.numbers("(list->vector (map (lambda (path) (max 0 (- (vector-mean path) 100))) paths))")
        self.assertAlmostEqual(value, float(np.mean(by_hand)), places=5)

    def test_paths_growing_at_the_interest_rate_are_worth_todays_price(self):
        # what an investment is worth is what it costs now, when it grows at the interest rate: the
        # average discounted final price is the start price (to within a few of its own standard errors)
        self.make_paths()
        value, error = self.value_and_error("(option-value paths (lambda (path) (vector-ref path 251)) 0.04 1)")
        self.assertAlmostEqual(value, 100, delta=3 * error)
        self.assertLess(error, 0.5)

    def test_what_option_value_wont_take(self):
        self.make_paths(count=5)
        payoff = "(lambda (path) 1)"
        self.assertLispError("(option-value 5 %s 0.04 1)" % payoff, "paths must be a list of vectors")
        self.assertLispError("(option-value (list 1 2) %s 0.04 1)" % payoff, "paths must be a list of vectors")
        self.assertLispError("(option-value (list (car paths)) %s 0.04 1)" % payoff, "at least two paths")
        self.assertLispError("(option-value paths %s \"4%%\" 1)" % payoff, "interest rate must be a number")
        self.assertLispError("(option-value paths %s 0.04 0)" % payoff, "years must be a number above 0")
        self.assertLispError("(option-value paths 5 0.04 1)", "not a procedure")
        self.assertLispError("(option-value paths (lambda (path) \"x\") 0.04 1)", "must return a number")
        self.assertLispError("(option-value paths (lambda (path) nan) 0.04 1)", "must return a number")

    # -- dividend-schedule and bootstrap-path's :dividends --------------------

    ACTUAL = """(define actual (list (cons "ex-date" (vector (date 2025 6 20) (date 2025 11 14) (date 2026 2 13)
                                                         (date 2026 5 15) (date 2026 8 14)))
                                    (cons "amount" (vector 0.40 0.50 0.50 0.52 0.52))))"""

    def schedule_rows(self, src):
        """A dividend schedule's rows, as (ex-date, day, amount)."""
        columns = lisp_tables.table_columns(self.run_lisp(src), "test")
        dates, days, amounts = [list(vector.items) for _, vector in columns]
        return [(str(d), int(day), round(float(a), 4)) for d, day, a in zip(dates, days, amounts)]

    def test_a_schedule_has_the_known_dividends_after_the_start_up_to_the_last_day(self):
        self.run_lisp(self.ACTUAL)
        self.assertShows("(table-column-names (dividend-schedule actual (date 2026 1 2) 100))", '("ex-date" "day" "amount")')
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 1 2) 100)"),
                         [("2026-02-13", 29, 0.5), ("2026-05-15", 92, 0.52)])      # (2026-08-14 is after day 100)
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 2 13) 100)"),
                         [("2026-05-15", 63, 0.52)])                              # not the one that day: it's in the price

    def test_a_schedule_can_repeat_the_last_years_dividends_on_the_same_dates(self):
        self.run_lisp(self.ACTUAL)
        # the last year, to October 5, 2026, had four: next year's are on a Saturday (the 14th, the 13th, the
        # 15th, and the 14th), so the next day the market is open: the Monday -- or, the Monday being
        # Washington's Birthday, the Tuesday
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #t)"),
                         [("2026-11-16", 30, 0.5), ("2027-02-16", 91, 0.5),
                          ("2027-05-17", 154, 0.52), ("2027-08-16", 216, 0.52)])
        self.assertEqual(self.schedule_rows("(dividend-schedule actual (date 2026 10 5) 252 :repeat-last-year #f)"),
                         [])                                                      # nothing is known after October 5

    def test_repeating_goes_on_for_as_many_years_as_the_path_lasts(self):
        self.run_lisp("""(define yearly (list (cons "ex-date" (vector (date 2026 3 2))) (cons "amount" (vector 1.0))))""")
        rows = self.schedule_rows("(dividend-schedule yearly (date 2026 10 5) 800 :repeat-last-year #t)")
        self.assertEqual([row[0] for row in rows], ["2027-03-02", "2028-03-02", "2029-03-02"])
        self.assertEqual(self.schedule_rows("(dividend-schedule yearly (date 2026 10 5) 100 :repeat-last-year #t)"), [])

    def test_a_dividend_on_the_start_date_is_in_the_price_but_comes_again_next_year(self):
        self.run_lisp("""(define on-start (list (cons "ex-date" (vector (date 2026 10 5))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule on-start (date 2026 10 5) 300)"), [])
        self.assertEqual(self.schedule_rows("(dividend-schedule on-start (date 2026 10 5) 300 :repeat-last-year #t)"),
                         [("2027-10-05", 251, 1.0)])

    def test_a_dividend_on_the_29th_of_february_comes_on_the_28th_in_other_years(self):
        self.run_lisp("""(define leap (list (cons "ex-date" (vector (date 2028 2 29))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule leap (date 2028 6 1) 252 :repeat-last-year #t)"),
                         [("2029-02-28", 186, 1.0)])

    def test_a_known_ex_date_the_market_is_closed_is_the_next_day_it_is_open(self):
        self.run_lisp("""(define odd (list (cons "ex-date" (vector (date 2026 11 26))) (cons "amount" (vector 1.0))))""")
        self.assertEqual(self.schedule_rows("(dividend-schedule odd (date 2026 11 20) 10)"), [("2026-11-27", 4, 1.0)])

    def test_a_schedule_without_dividends_is_a_table_without_rows(self):
        self.run_lisp(self.ACTUAL)
        self.assertShows("(table-row-count (dividend-schedule actual (date 2024 1 2) 100 :repeat-last-year #t))", "0")
        self.assertShows("(length (table-column-names (dividend-schedule actual (date 2024 1 2) 100)))", "3")

    def test_what_dividend_schedule_wont_take(self):
        self.run_lisp(self.ACTUAL)
        self.assertLispError("(dividend-schedule actual 5 100)", "the start date must be a date")
        self.assertLispError("(dividend-schedule actual (date 2026 1 2) 0)", "days must be a whole number")
        self.assertLispError('(dividend-schedule (table-drop-columns actual "amount") (date 2026 1 2) 100)',
                             "no column named 'amount'")
        self.assertLispError('(dividend-schedule (list (cons "ex-date" (vector (date 2026 1 5))) (cons "amount" (vector -1.0)))'
                             " (date 2026 1 2) 100)", "0 or more")
        self.assertLispError("(dividend-schedule actual (date 2026 1 2) 100 :repeat #t)", ":repeat isn't an option")

    def schedule(self, days_and_amounts):
        """A dividend schedule, as `schedule` in the Lisp environment."""
        self.env[lisp_core.Symbol("schedule")] = lisp_tables.make_table_value([
            ("day", lisp_vector_math.to_vector(np.array([d for d, _ in days_and_amounts]))),
            ("amount", lisp_vector_math.to_vector(np.array([a for _, a in days_and_amounts], dtype=np.float64)))])

    def test_a_dividend_takes_its_amount_off_the_price_on_its_day(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(2, 1.5), (2, 0.5), (5, 3.0)])                # (two on day 2)
        self.assertNumbers("(bootstrap-path flat 100 8 1 :dividends schedule)", [100, 98, 98, 98, 95, 95, 95, 95])

    def test_the_price_grows_between_dividends_and_a_dividend_is_taken_off_what_it_has_grown_to(self):
        self.make_returns("steady", [0.01, 0.01])
        self.schedule([(3, 2.0), (6, 1.0)])
        price, expected = 100.0, []
        for day in range(1, 9):
            price *= math.exp(0.01)
            price -= {3: 2.0, 6: 1.0}.get(day, 0.0)
            expected.append(price)
        self.assertNumbers("(bootstrap-path steady 100 8 2 :dividends schedule)", expected, places=3)

    def test_the_schedule_may_be_out_of_order_and_go_on_past_the_path(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(5, 3.0), (2, 2.0), (50, 40.0)])
        self.assertNumbers("(bootstrap-path flat 100 6 1 :dividends schedule)", [100, 98, 98, 98, 95, 95])

    def test_the_price_stops_at_0(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.schedule([(2, 500.0), (4, 1.0)])
        self.assertNumbers("(bootstrap-path flat 100 5 1 :dividends schedule)", [100, 0, 0, 0, 0])

    def test_no_dividends_in_the_schedule_is_no_change(self):
        self.a_year_of_returns()
        self.run_lisp(self.ACTUAL + "(define none (dividend-schedule actual (date 2024 1 2) 100))")
        plain = self.show("(bootstrap-path history 100 100 5 :seed 3)")
        self.assertEqual(self.show("(bootstrap-path history 100 100 5 :seed 3 :dividends none)"), plain)
        self.assertEqual(self.show("(bootstrap-path history 100 100 5 :seed 3 :dividends '())"), plain)

    def test_dividends_that_are_the_same_in_every_path_leave_the_expected_price_less_what_they_grow_to(self):
        # growing at the interest rate every day, as the returns are, the average price the last day is the
        # start price grown, less each dividend grown from its day on: S g^T - sum of D g^(T - t)
        self.a_year_of_returns()
        self.run_lisp("(define fair (adjust-returns history (- (exp 0.04) 1)))")
        self.schedule([(60, 1.0), (150, 2.0)])
        growth = math.exp(0.04 / 252)
        expected = 100 * growth ** 252 - 1.0 * growth ** (252 - 60) - 2.0 * growth ** (252 - 150)
        finals = self.run_lisp("""(vector-mean (list->vector
            (map (lambda (i) (vector-ref (bootstrap-path fair 100 252 1 :seed i :dividends schedule) 251))
                 (iota 4000))))""")
        self.assertAlmostEqual(finals, expected, delta=0.8)               # (about 3 standard errors)
        self.assertGreater(abs(100 * growth ** 252 - expected), 2.9)      # (without them it would be 3 off)

    def test_what_a_schedule_must_be(self):
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.run_lisp(self.ACTUAL)
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends actual)", "as dividend-schedule makes")
        self.schedule([(0, 1.0)])
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends schedule)", "must be a whole number, 1 or more")
        self.make_returns("flat", [0.0, 0.0, 0.0])
        self.run_lisp("""(define fraction (list (cons "day" (vector 1.5)) (cons "amount" (vector 1.0))))""")
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends fraction)", "must be a whole number, 1 or more")
        self.schedule([(2, -1.0)])
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends schedule)", "0 or more")
        self.assertLispError("(bootstrap-path flat 100 5 1 :dividends 5)", "not a table")


class TestOptionCheck(LispTestCase):
    """option-payoffs, and lib/option_check.lsp, on made-up option chains priced as
    paths from a made-up history say they should be, with some options priced out of line."""

    SPOT = 100.0
    RATE = 0.04

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "option_check.lsp")')
        values = np.random.default_rng(5).normal(0.0, 0.2 / math.sqrt(252), 2500)    # a history with 20% volatility
        self.volatility = values.std(ddof=1) * math.sqrt(252)
        self.env[lisp_core.Symbol("returns")] = lisp_tables.make_table_value(
            [("log-return", lisp_vector_math.to_vector(values))])

    def make_chain(self, start, planted=None, dividend=None, trading_days=(25, 60, 120), name="chain", priced_at=None,
                   vol_shift=None, vol_scale=1.0, american=False):
        """A chain, as `chain`, of options on 100 at these numbers of trading days after start, priced as
        paths of this history say they should be (Black's formula, with the volatility the paths have in
        calendar time) -- times a number, for the options in `planted`, {(expiration number, type, strike):
        number}. dividend, a (date, amount), is paid before the expirations after it. priced_at is the price of
        the underlying when the options were priced, if it isn't the 100 the chain says it is. vol_shift is
        {expiration number: volatility added to every option's of that expiration}; vol_scale, a number
        every option's volatility is multiplied by. american prices them as options that can be exercised
        early (by lisp_options' binomial tree)."""
        rows = []
        for number, trading in enumerate(trading_days):
            expiration = lisp_calendar.trading_days_after(start, trading)
            calendar_days = (expiration - start).days
            T = calendar_days / 365
            vol = self.volatility * math.sqrt((trading / 252) / T) * vol_scale + (vol_shift or {}).get(number, 0.0)
            discount = math.exp(-self.RATE * T)
            present_value = 0.0
            if dividend and dividend[0] <= expiration:
                present_value = dividend[1] * math.exp(-self.RATE * (dividend[0] - start).days / 365)
            forward = ((priced_at or self.SPOT) - present_value) / discount
            for strike in range(80, 125, 5):
                for kind in ("Call", "Put"):
                    if american:
                        price = lisp_options.tree_price(kind == "Call", self.SPOT, strike, T, self.RATE, vol, 0.0,
                                                        np.zeros(0), np.zeros(0), 200, True)
                    else:
                        price = TestVolSmile.black(kind == "Call", forward, strike, T, discount, vol)
                    rows.append(("X%d%s%d" % (number, kind[0], strike), kind, float(strike), expiration, calendar_days,
                                 price * (planted or {}).get((number, kind, strike), 1.0)))
        columns = {
            "symbol": [lisp_core.LispString(r[0]) for r in rows], "type": [lisp_core.LispString(r[1]) for r in rows],
            "strike": [r[2] for r in rows],
            "expiration-date": [lisp_core.LispDate(r[3].year, r[3].month, r[3].day) for r in rows],
            "days-to-expiration": [r[4] for r in rows], "underlying-price": [self.SPOT] * len(rows),
            "bid": [r[5] * 0.985 for r in rows], "ask": [r[5] * 1.015 for r in rows], "mid": [r[5] for r in rows],
            "volume": [100.0] * len(rows), "open-interest": [100.0] * len(rows)}
        self.env[lisp_core.Symbol(name)] = lisp_tables.make_table_value(
            [(heading, lisp_tables.column_vector(values)) for heading, values in columns.items()])

    START = datetime.date(2026, 10, 5)
    CHECK = ("(define checked (check-option-chain chain returns :start-date (date 2026 10 5) :rate 0.04 "
             ":paths 3000 :block-size 1 :seed 7 %s))")
    PLANTED = {(1, "Call", 105): 1.3, (1, "Call", 110): 1.3, (2, "Put", 90): 0.7, (2, "Put", 95): 0.7}

    def column(self, name, table="checked"):
        return list(self.run_lisp('(table-column %s "%s")' % (table, name)).items)

    # -- option-payoffs -------------------------------------------------------

    def test_what_options_pay_on_average_over_the_paths(self):
        self.run_lisp("(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0) #(10.0 10.0 10.0) #(10.0 12.0 14.0)))")
        self.assertShows("(table-column-names (option-payoffs paths #(3) #(10) #(1)))", '("payoff" "payoff-error" "paths-paid")')
        # the options, and what each pays on the four paths:
        #   a call on day 3, struck at 10:  2, 0, 0, and 4
        #   a put on day 3, struck at 11:   0, 3, 1, and 0
        #   a call on day 1, struck at 10:  0, 0, 0, and 0
        #   a put on day 2, struck at 11:   0, 2, 1, and 0
        pays = [[2, 0, 0, 4], [0, 3, 1, 0], [0, 0, 0, 0], [0, 2, 1, 0]]
        answer = "(option-payoffs paths #(3 3 1 2) #(10 11 10 11) #(1 0 1 0))"
        for column, expected in (("payoff", [np.mean(p) for p in pays]),
                                 ("payoff-error", [np.std(p, ddof=1) / 2 for p in pays]),
                                 ("paths-paid", [sum(1 for x in p if x > 0) for p in pays])):
            with self.subTest(column=column):
                actual = self.run_lisp('(table-column %s "%s")' % (answer, column)).items
                np.testing.assert_allclose(np.array(actual, dtype=np.float64), expected, rtol=1e-5)

    def test_what_option_payoffs_wont_take(self):
        self.run_lisp("(define paths (list #(10.0 11.0 12.0) #(10.0 9.0 8.0)))")
        self.assertLispError("(option-payoffs 5 #(1) #(10) #(1))", "paths must be a list of vectors")
        self.assertLispError("(option-payoffs (list #(1.0 2.0)) #(1) #(10) #(1))", "at least two paths")
        self.assertLispError("(option-payoffs (list #(1.0 2.0) #(1.0)) #(1) #(10) #(1))", "the same length")
        self.assertLispError("(option-payoffs paths #(1 2) #(10) #(1))", "an element for each option")
        self.assertLispError("(option-payoffs paths #(4) #(10) #(1))", "from 1 to the paths' 3 days")
        self.assertLispError("(option-payoffs paths #(0) #(10) #(1))", "from 1 to the paths' 3 days")
        self.assertLispError("(option-payoffs paths #(1.5) #(10) #(1))", "whole number")

    # -- check-option-chain -----------------------------------------------------

    def test_the_options_priced_out_of_line_come_first_and_are_rich_or_cheap(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        symbols = self.column("symbol")
        self.assertEqual({str(x) for x in symbols[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        signals = {str(symbol): str(signal) for symbol, signal in zip(symbols, self.column("signal"))}
        self.assertEqual({symbol: signal for symbol, signal in signals.items() if signal},
                         {"X1C105": "rich", "X1C110": "rich", "X2P90": "cheap", "X2P95": "cheap"})
        distances = [abs(float(x)) for x in self.column("iv-residual")]
        self.assertEqual(distances, sorted(distances, reverse=True))
        self.assertShows("(table-column-names checked)", '("symbol" "type" "expiration-date" "days-to-expiration" "strike" '
                         '"bid" "ask" "iv-bid" "iv-mid" "iv-ask" "model-price" "standard-error" "paths-paid" "model-iv" '
                         '"iv-residual" "iv-vs-expiration" "signal" "edge")')

    def test_options_priced_as_the_paths_say_are_not_out_of_line(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)         # within a volatility point
        self.assertEqual({str(x) for x in self.column("signal")}, {""})

    def test_the_edge_is_how_far_the_bid_or_ask_is_from_the_value(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        for symbol, signal, edge, bid, ask, price in zip(*[self.column(name) for name in
                                                          ("symbol", "signal", "edge", "bid", "ask", "model-price")]):
            if str(signal) == "rich":
                self.assertAlmostEqual(float(edge), float(bid) - float(price), places=4)
            elif str(signal) == "cheap":
                self.assertAlmostEqual(float(edge), float(price) - float(ask), places=4)
            else:
                self.assertEqual(float(edge), 0.0)

    def test_only_the_out_of_the_money_options_unless_asked_for_all(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        only = int(self.run_lisp("(table-row-count checked)"))
        # (the forwards are 100.3 to 101.8, and the strikes are 80, 85, ..., 120)
        for kind, strike in zip(self.column("type"), self.column("strike")):
            if str(kind) == "Call":
                self.assertGreaterEqual(float(strike), 105)
            else:
                self.assertLessEqual(float(strike), 100)
        self.run_lisp(self.CHECK.replace("(define checked", "(define everything") % ":out-of-the-money-only #f")
        self.assertGreater(int(self.run_lisp("(table-row-count everything)")), only)

    def test_the_options_the_paths_say_too_little_about_are_left_out(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":min-paths-paid 1")
        everything = int(self.run_lisp("(table-row-count checked)"))
        self.run_lisp(self.CHECK % ":min-paths-paid 600")
        self.assertLess(int(self.run_lisp("(table-row-count checked)")), everything)
        self.assertGreaterEqual(min(float(x) for x in self.column("paths-paid")), 600)

    def test_the_same_seed_gives_the_same_check(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        first = self.show("checked")
        self.run_lisp(self.CHECK % "")
        self.assertEqual(self.show("checked"), first)

    def test_dividends_the_last_year_had_are_taken_off_the_options_that_expire_after_their_dates(self):
        today = datetime.date.today()
        last_year = today - datetime.timedelta(days=100)
        ex_date = lisp_calendar.first_trading_day_from(lisp_time_series.months_later(last_year, 12))
        self.make_chain(today, dividend=(ex_date, 2.0), trading_days=(60, 130, 220))
        self.env[lisp_core.Symbol("actual")] = lisp_tables.make_table_value([
            ("ex-date", lisp_core.LispVector([lisp_core.LispDate(last_year.year, last_year.month, last_year.day)])),
            ("amount", lisp_vector_math.to_vector(np.array([2.0])))])
        check = ("(define checked (check-option-chain chain returns :rate 0.04 :paths 3000 :block-size 1 :seed 7 "
                 ":dividends %s))")
        self.run_lisp(check % "actual")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)
        self.assertEqual({str(x) for x in self.column("signal")}, {""})
        self.run_lisp(check % "'()")                       # without them the later options are out of line
        self.assertGreater(max(abs(float(x)) for x in self.column("iv-residual")), 0.02)

    def test_an_expiration_the_market_prices_for_more_volatility_is_out_of_line_by_the_same_amount_in_all_its_options(self):
        # the second expiration is priced 3 volatility points above what the paths say, all of it: iv-residual
        # shows it, and iv-vs-expiration doesn't, since that is for what's out of line with the rest of an expiration
        self.make_chain(self.START, vol_shift={1: 0.03}, planted={(1, "Call", 110): 1.3})
        self.run_lisp(self.CHECK % "")
        expirations = self.column("expiration-date")
        residuals = [float(x) for x in self.column("iv-residual")]
        relative = [float(x) for x in self.column("iv-vs-expiration")]
        symbols = [str(x) for x in self.column("symbol")]
        for symbol, residual, relative_residual in zip(symbols, residuals, relative):
            if symbol.startswith("X1") and symbol != "X1C110":
                self.assertAlmostEqual(residual, 0.03, delta=0.01)
                self.assertLess(abs(relative_residual), 0.01)
            elif symbol.startswith("X0") or symbol.startswith("X2"):
                self.assertLess(abs(residual), 0.01)
        index = symbols.index("X1C110")                    # and the one priced out of line in it is, in both
        self.assertGreater(residuals[index], 0.04)
        self.assertGreater(relative[index], 0.015)

    def test_the_middle_iv_residual_of_each_expiration(self):
        self.make_chain(self.START, vol_shift={1: 0.03})
        self.run_lisp(self.CHECK % "")
        self.run_lisp("(define by-expiration (option-check-expirations checked))")
        self.assertShows("(table-column-names by-expiration)",
                         '("expiration-date" "days-to-expiration" "options" "median-iv-residual" "rich" "cheap")')
        self.assertEqual(int(self.run_lisp("(table-row-count by-expiration)")), 3)
        medians = [float(x) for x in self.column("median-iv-residual", "by-expiration")]
        self.assertAlmostEqual(medians[0], 0.0, delta=0.01)
        self.assertAlmostEqual(medians[1], 0.03, delta=0.01)
        self.assertAlmostEqual(medians[2], 0.0, delta=0.01)
        self.assertEqual(sum(int(x) for x in self.column("options", "by-expiration")),
                         int(self.run_lisp("(table-row-count checked)")))

    def test_a_dividend_after_the_start_date_counts_though_today_is_after_it(self):
        # the chain is priced as of October 5, 2026, and the dividend, the last year's, comes again on October 6
        last_year = datetime.date(2025, 10, 6)
        self.make_chain(self.START, dividend=(datetime.date(2026, 10, 6), 2.0))
        self.env[lisp_core.Symbol("actual")] = lisp_tables.make_table_value([
            ("ex-date", lisp_core.LispVector([lisp_core.LispDate(last_year.year, last_year.month, last_year.day)])),
            ("amount", lisp_vector_math.to_vector(np.array([2.0])))])
        self.run_lisp(self.CHECK % ":dividends actual")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)

    def test_with_early_exercise_in_the_money_options_can_be_checked_too(self):
        self.make_chain(self.START, american=True)                # (prices of options that can be exercised early)
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f")
        self.assertGreater(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)   # the in-the-money puts
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f :early-exercise #t")
        residuals = [abs(float(x)) for x in self.column("iv-residual")]
        self.assertLess(max(residuals), 0.01)
        self.assertEqual({str(x) for x in self.column("signal")}, {""})
        premiums = {str(symbol): float(premium) for symbol, premium
                    in zip(self.column("symbol"), self.column("early-exercise"))}
        self.assertGreater(premiums["X2P110"], 0.3)              # a put in the money: worth exercising early
        self.assertLess(max(premium for symbol, premium in premiums.items() if "C" in symbol), 1e-6)  # calls: never

    def test_with_early_exercise_the_bid_and_ask_are_the_market_s_and_the_value_includes_it(self):
        self.make_chain(self.START, american=True)
        self.run_lisp(self.CHECK % ":out-of-the-money-only #f :early-exercise #t :expected-return (- (exp 0.04) 1)")
        market = {str(symbol): (float(bid), float(ask)) for symbol, bid, ask
                  in zip(*[list(self.run_lisp('(table-column chain "%s")' % name).items) for name in ("symbol", "bid", "ask")])}
        for symbol, bid, ask, price, error, expected in zip(*[self.column(name) for name in
                                                              ("symbol", "bid", "ask", "model-price", "standard-error",
                                                               "expected-value")]):
            self.assertAlmostEqual(float(bid), market[str(symbol)][0], places=4)
            self.assertAlmostEqual(float(ask), market[str(symbol)][1], places=4)
            self.assertAlmostEqual(float(expected), float(price), places=4)
            mid = (float(bid) + float(ask)) / 2                    # the value is the market's, to the paths' noise
            self.assertLess(abs(float(price) - mid), 3 * float(error) + 0.01 * mid)

    def test_the_time_to_expiration_is_counted_from_the_start_date(self):
        # a chain priced as of Monday, October 5, 2026, whose own days-to-expiration were counted from some day
        # long after that: the check counts from the start date, so it isn't thrown off
        self.make_chain(self.START)
        self.run_lisp('(define chain (table-add-column chain "days-to-expiration" 1))')
        self.run_lisp(self.CHECK % "")
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)

    def test_an_underlying_price_that_does_not_fit_the_options_is_refused_unless_it_is_given_right(self):
        self.make_chain(self.START, priced_at=101.0)                  # (the underlying's price says 100)
        with self.assertRaises(lisp_core.LispError) as raised:
            self.run_lisp(self.CHECK % "")
        message = str(raised.exception)
        self.assertIn("don't fit the underlying's price of 100.00", message)
        self.assertIn("put-call parity", message)
        self.assertRegex(message, r"about 10[01]\.\d\d when they were made")      # the price they were made at: 101
        suggested = float(re.search(r"about ([\d.]+) when they were made", message).group(1))
        self.assertAlmostEqual(suggested, 101.0, delta=0.05)
        self.run_lisp(self.CHECK % ":start-price 101.0")             # (their price, as the message says)
        self.assertLess(max(abs(float(x)) for x in self.column("iv-residual")), 0.01)
        self.run_lisp(self.CHECK % ":forward-tolerance 0.05")        # or a looser test
        self.assertGreater(int(self.run_lisp("(table-row-count checked)")), 0)

    def test_what_check_option_chain_wont_take(self):
        self.make_chain(self.START)
        self.assertLispError("(check-option-chain chain returns :start-date (date 2030 1 1))", "no option that expires after")
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :max-vol-spread -1)",
                             "no option is liquid enough")
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :paths 1)", "at least two paths")

    # -- :match-volatility and :expected-return ---------------------------------------

    def test_without_matching_the_market_s_higher_volatility_makes_every_option_rich(self):
        self.make_chain(self.START, vol_scale=1.3)               # the market has 30% more volatility than the history
        self.run_lisp(self.CHECK % "")
        self.assertAlmostEqual(float(self.run_lisp('(vector-median (table-column checked "iv-residual"))')),
                               0.06, delta=0.01)                 # 0.3 of 20 volatility points
        self.assertGreater(sum(1 for x in self.column("signal") if str(x) == "rich"), 0.7 * len(self.column("signal")))

    def test_matching_the_volatility_finds_the_market_s_overall_level(self):
        self.make_chain(self.START, planted=self.PLANTED, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t")
        scales = [float(x) for x in self.column("volatility-scale")]
        self.assertAlmostEqual(scales[0], 1.3, delta=0.03)
        self.assertEqual(len(set(scales)), 1)                    # (one number, in every row)
        self.assertAlmostEqual(float(self.run_lisp('(vector-median (table-column checked "iv-residual"))')),
                               0.0, delta=0.005)
        symbols = self.column("symbol")
        self.assertEqual({str(x) for x in symbols[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        self.assertEqual({str(s) for s, signal in zip(symbols, self.column("signal")) if str(signal)},
                         {"X1C105", "X1C110", "X2P90", "X2P95"})

    def test_matching_a_chain_the_paths_already_fit_changes_nothing_much(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":match-volatility #t")
        self.assertAlmostEqual(float(self.column("volatility-scale")[0]), 1.0, delta=0.02)

    def test_there_must_be_an_option_to_match_the_volatility_with(self):
        self.make_chain(self.START)
        self.assertLispError("(check-option-chain chain returns :start-date (date 2026 10 5) :paths 500 :min-paths-paid 100000 "
                             ":match-volatility #t)", "no option to match the volatility with")

    def test_no_expected_return_no_expected_columns(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % "")
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertNotIn("expected-value", names)
        self.assertNotIn("volatility-scale", names)

    def test_an_expected_return_above_the_interest_rate_raises_calls_and_lowers_puts(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":expected-return 0.15")
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertEqual(names[-3:], ["expected-value", "favors", "expected-profit"])
        for kind, price, expected in zip(self.column("type"), self.column("model-price"), self.column("expected-value")):
            if str(kind) == "Call":
                self.assertGreaterEqual(float(expected), float(price))      # (the same paths, growing faster)
            else:
                self.assertLessEqual(float(expected), float(price))

    def test_the_expected_return_that_is_the_interest_rate_changes_nothing_so_favors_is_signal(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % ":expected-return (- (exp 0.04) 1)")
        for price, expected in zip(self.column("model-price"), self.column("expected-value")):
            self.assertAlmostEqual(float(expected), float(price), places=5)
        words = {"rich": "selling", "cheap": "buying", "": ""}
        for signal, favors in zip(self.column("signal"), self.column("favors")):
            self.assertEqual(str(favors), words[str(signal)])

    def test_with_matched_volatility_the_expected_return_paths_have_the_same_volatility(self):
        self.make_chain(self.START, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t :expected-return (- (exp 0.04) 1)")
        for price, expected in zip(self.column("model-price"), self.column("expected-value")):
            self.assertAlmostEqual(float(expected), float(price), places=5)

    def test_a_much_higher_expected_return_favors_buying_calls_and_selling_puts(self):
        self.make_chain(self.START)
        self.run_lisp(self.CHECK % ":expected-return 0.6")
        favors = [(str(kind), str(side)) for kind, side in zip(self.column("type"), self.column("favors"))]
        self.assertIn(("Call", "buying"), favors)
        self.assertIn(("Put", "selling"), favors)
        self.assertNotIn(("Call", "selling"), favors)
        self.assertNotIn(("Put", "buying"), favors)
        for side, profit, expected, bid, ask in zip(*[self.column(name) for name in
                                                       ("favors", "expected-profit", "expected-value", "bid", "ask")]):
            if str(side) == "buying":
                self.assertAlmostEqual(float(profit), float(expected) - float(ask), places=4)
            elif str(side) == "selling":
                self.assertAlmostEqual(float(profit), float(bid) - float(expected), places=4)
            else:
                self.assertEqual(float(profit), 0.0)

    def test_showing_the_volatility_scale_and_the_expected_profit(self):
        self.make_chain(self.START, vol_scale=1.3)
        self.run_lisp(self.CHECK % ":match-volatility #t :expected-return 0.3")
        self.run_lisp("(show-option-check checked :count 3)")
        shown = self.printed()
        self.assertIn("The paths' volatility was multiplied by 1.", shown)
        self.assertIn("The 3 options with the most expected profit if the underlying earns its expected return", shown)

    # -- check-option-prices and show-option-check --------------------------------

    def test_check_option_prices_gets_the_chain_the_prices_and_the_dividends(self):
        today = datetime.date.today()
        self.make_chain(today, planted=self.PLANTED)
        dates, price, closes = [], 100.0, []
        values = np.random.default_rng(5).normal(0.0, 0.2 / math.sqrt(252), 2500)
        day = lisp_calendar.trading_days_after(today, 0)
        while not lisp_calendar.is_trading_day(day):
            day -= datetime.timedelta(days=1)
        for value in values[::-1]:
            dates.append(lisp_core.LispDate(day.year, day.month, day.day))
            closes.append(price)
            price *= math.exp(-value)
            day = lisp_calendar.trading_days_after(day, -1)
        prices = lisp_tables.make_table_value([("date", lisp_core.LispVector(dates[::-1])),
                                               ("close", lisp_vector_math.to_vector(np.array(closes[::-1])))])
        asked = []
        self.env[lisp_core.Symbol("tastytrade-option-chain")] = lambda creds, symbol, months, strikes: (
            asked.append(("chain", str(creds), str(symbol), months, strikes)) or self.env[lisp_core.Symbol("chain")])
        self.env[lisp_core.Symbol("schwab-price-history")] = lambda creds, symbol: (
            asked.append(("prices", str(creds), str(symbol))) or prices)
        self.env[lisp_core.Symbol("alpha-vantage-dividends")] = lambda creds, symbol: (
            asked.append(("dividends", str(creds), str(symbol))) or lisp_tables.make_table_value([
                ("ex-date", lisp_core.LispVector([])), ("amount", lisp_vector_math.to_vector(np.array([], dtype=np.float64)))]))
        self.run_lisp('(define checked (check-option-prices "creds.json" "XYZ" :months 4 :strikes 9 :paths 3000 '
                      ':block-size 1 :seed 7))')
        self.assertEqual(sorted(asked), [("chain", "creds.json", "XYZ", 4, 9), ("dividends", "creds.json", "XYZ"),
                                         ("prices", "creds.json", "XYZ")])
        self.assertEqual({str(x) for x in self.column("symbol")[:4]}, {"X1C105", "X1C110", "X2P90", "X2P95"})
        self.run_lisp('(define checked (check-option-prices "creds.json" "XYZ" :paths 2000 :block-size 1 :seed 7 '
                      ':expected-return 0.08 :match-volatility #t :early-exercise #t))')
        names = [str(x) for x in lisp_core.pairs_to_list(self.run_lisp("(table-column-names checked)"))]
        self.assertIn("expected-value", names)
        self.assertIn("volatility-scale", names)
        self.assertIn("early-exercise", names)

    def test_showing_the_check(self):
        self.make_chain(self.START, planted=self.PLANTED)
        self.run_lisp(self.CHECK % "")
        self.run_lisp("(show-option-check checked :count 3)")
        shown = self.printed()
        self.assertIn("The middle iv-residual, the market's volatility less the paths', in each expiration:", shown)
        self.assertIn("The 3 options furthest from the paths' values", shown)
        self.assertIn("The 3 furthest from the middle iv-residual of their expiration", shown)
        self.assertIn("Options whose bid is above the paths' value (rich) or ask below it (cheap):", shown)
        for symbol in ("X1C105", "X2P95"):
            self.assertIn(symbol, shown)


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
                         '("relations" "<=" "<=" "<=") ("rhs" 4.0 12.0 18.0) '
                         '("variables" "x1" "x2") ("goal" "minimize"))')

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
        path = self.write_problem_file("optimize\n1 2\nsubject to\n1 1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "must start with a 'minimize' or 'maximize' line")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 <= 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "expected 2")
        path = self.write_problem_file("minimize\n1 2\nsubject to\n1 1 < 4\n")
        self.assertLispError('(lp-read-file "%s")' % path, "Unrecognized relation")

    NAMED_FILE = """
        # Maximize 3x1 + 5x2
        maximize
        3 x1 + 5 x2
        subject to
        x1 <= 4
        2 x2 <= 12
        3 x1 + 2 x2 <= 18
    """

    def test_read_a_file_with_variable_names(self):
        path = self.write_problem_file(self.NAMED_FILE)
        self.assertShows('(lp-read-file "%s")' % path,
                         '(("objective" 3.0 5.0) ("constraints" (1.0 0.0) (0.0 2.0) (3.0 2.0)) '
                         '("relations" "<=" "<=" "<=") ("rhs" 4.0 12.0 18.0) '
                         '("variables" "x1" "x2") ("goal" "maximize"))')

    def test_a_maximize_problem_gives_the_maximum(self):
        path = self.write_problem_file(self.NAMED_FILE)
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 2.0 6.0) ("optimal-value" . 36.0))')

    def test_maximize_and_negated_minimize_agree(self):
        # Maximizing 3x1 + 5x2, and minimizing -3x1 - 5x2 in the coefficients-only form.
        self.assertShows('(cdr (assoc "solution" (lp-solve (lp-read-file "%s"))))'
                         % self.write_problem_file(self.NAMED_FILE), "(2.0 6.0)")
        self.assertShows('(cdr (assoc "solution" (lp-solve (lp-read-file "%s"))))'
                         % self.EXAMPLE_FILE.replace("\\", "/"), "(2.0 6.0)")

    def test_variables_are_numbered_in_order_of_first_appearance(self):
        # z appears in a constraint but not the objective; it costs nothing (coefficient 0).
        path = self.write_problem_file("minimize\nb + a\nsubject to\na + z >= 3\nz <= 2\nb >= 1\n")
        self.assertShows('(cdr (assoc "variables" (lp-read-file "%s")))' % path, '("b" "a" "z")')
        self.assertShows('(cdr (assoc "objective" (lp-read-file "%s")))' % path, "(1.0 1.0 0.0)")
        self.assertShows('(cdr (assoc "constraints" (lp-read-file "%s")))' % path,
                         "((0.0 1.0 1.0) (0.0 0.0 1.0) (1.0 0.0 0.0))")

    def test_a_name_used_twice_in_a_formula_has_its_coefficients_added(self):
        path = self.write_problem_file("minimize\nx + x + y\nsubject to\nx + y >= 3\ny <= 5\n")
        self.assertShows('(cdr (assoc "objective" (lp-read-file "%s")))' % path, "(2.0 1.0)")

    def test_a_formula_can_start_with_a_sign_and_use_minus(self):
        path = self.write_problem_file("minimize\n- x + 2 y\nsubject to\nx <= 3\ny >= 1\n")
        self.assertShows('(lp-solve (lp-read-file "%s"))' % path,
                         '(("solution" 3.0 1.0) ("optimal-value" . -1.0))')

    def test_names_can_have_underscores_and_digits_and_are_case_sensitive(self):
        path = self.write_problem_file("minimize\ngnma_30 + GNMA_30 + _x2\nsubject to\n"
                                       "gnma_30 + GNMA_30 + _x2 >= 1\n")
        self.assertShows('(cdr (assoc "variables" (lp-read-file "%s")))' % path, '("gnma_30" "GNMA_30" "_x2")')

    def test_the_header_words_are_not_case_sensitive(self):
        path = self.write_problem_file("MAXIMIZE\n2 x\nSubject To\nx <= 4\n")
        self.assertShows('(cdr (assoc "optimal-value" (lp-solve (lp-read-file "%s"))))' % path, "8.0")

    def test_named_file_errors_say_what_is_wrong(self):
        head = "maximize\n3 x + 5 y\nsubject to\n"
        cases = [
            (head + "3x + 2 y <= 4\n", "'3x' is not a number or a variable name"),
            (head + "x+y <= 4\n", "'x+y' is not a number or a variable name"),
            (head + "x y <= 4\n", "Expected + or - after 'x', but found 'y'"),
            (head + "3 + 2 y <= 4\n", "Expected a variable name"),
            (head + "3 x + <= 4\n", "Expected a variable name"),
            (head + "x + y < 4\n", "Unrecognized relation '<'"),
            (head + "x + y <= many\n", "'many' is not a number"),
            (head + "x <=\n", "A constraint needs a left-hand side"),
            ("maximize\n3 x\nsubject to\n", "No constraints were found"),
            ("maximize\nsubject to\nx <= 4\n", "Expected the objective"),
            ("maximize\n3 x\nx <= 4\n", "Expected a 'subject to' line"),
            ("minimize\n1 2\nsubject to\nx + y <= 4\n", "the objective has no variable names"),
        ]
        for text, message in cases:
            with self.subTest(text=text):
                self.assertLispError('(lp-read-file "%s")' % self.write_problem_file(text), message)

    def test_a_problem_built_in_lisp_can_say_maximize_by_string_or_symbol(self):
        for goal in ['"maximize"', "maximize"]:
            with self.subTest(goal=goal):
                self.assertShows("""(lp-solve '(("objective" 3 5) ("constraints" (1 0) (0 2) (3 2))
                                                ("relations" <= <= <=) ("rhs" 4 12 18) ("goal" %s)))""" % goal,
                                 '(("solution" 2.0 6.0) ("optimal-value" . 36.0))')

    def test_a_problem_with_no_goal_is_minimized(self):
        self.assertShows("""(lp-solve '(("objective" 1 1) ("constraints" (1 2) (3 1))
                                        ("relations" >= >=) ("rhs" 4 6)))""",
                         '(("solution" 1.6 1.2) ("optimal-value" . 2.8))')

    def test_a_bad_goal_or_variables_list_is_an_error(self):
        base = '("objective" 1 1) ("constraints" (1 1)) ("relations" <=) ("rhs" 4)'
        self.assertLispError("(lp-solve '(%s (\"goal\" \"largest\")))" % base, '"goal" must be "minimize" or "maximize"')
        self.assertLispError("(lp-solve '(%s (\"goal\")))" % base, '"goal" must be "minimize" or "maximize"')
        self.assertLispError("(lp-solve '(%s (\"variables\" \"x\")))" % base,
                             '"variables" has 1 names, but the objective has 2 coefficients')

    def test_the_default_iteration_limit_is_three_times_the_number_of_variables(self):
        # Beale's example makes this solver cycle forever. It has 4 variables and 3 constraints,
        # each of which adds a slack variable: 7 in all, so the default limit is 21.
        beale = """'(("objective" -0.75 20 -0.5 6)
                      ("constraints" (0.25 -8 -1 9) (0.5 -12 -0.5 3) (0 0 1 0))
                      ("relations" <= <= <=) ("rhs" 0 0 1))"""
        self.assertLispError("(lp-solve %s)" % beale, "did not converge within 21 iterations")
        self.assertLispError("(lp-solve %s 50)" % beale, "did not converge within 50 iterations")

    def test_slack_surplus_and_artificial_variables_count_toward_the_default_limit(self):
        # The same cycling problem, plus all-zero rows, which don't change the pivoting but do
        # add columns. ">=" adds a surplus and an artificial variable, and "=" an artificial one.
        def beale_with(extra_relations):
            rows = "".join(" (0 0 0 0)" for _ in extra_relations)
            return """'(("objective" -0.75 20 -0.5 6)
                        ("constraints" (0.25 -8 -1 9) (0.5 -12 -0.5 3) (0 0 1 0)%s)
                        ("relations" <= <= <= %s) ("rhs" 0 0 1%s))""" % (
                rows, " ".join(extra_relations), " 0" * len(extra_relations))
        # 4 variables + 3 slack = 7, so 21
        self.assertLispError("(lp-solve %s)" % beale_with([]), "within 21 iterations")
        # + 1 surplus + 1 artificial = 9, so 27
        self.assertLispError("(lp-solve %s)" % beale_with([">="]), "within 27 iterations")
        # + 1 artificial = 8, so 24
        self.assertLispError("(lp-solve %s)" % beale_with(["="]), "within 24 iterations")
        # 4 + 3 + 1 surplus + 2 artificial = 10, so 30
        self.assertLispError("(lp-solve %s)" % beale_with([">=", "="]), "within 30 iterations")

    def test_max_iterations_can_be_given_and_must_be_a_positive_whole_number(self):
        self.assertLispError("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                            ("relations" <= <= <=) ("rhs" 4 12 18)) 1)""",
                             "did not converge within 1 iterations")
        self.assertShows("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                        ("relations" <= <= <=) ("rhs" 4 12 18)) 10)""",
                         '(("solution" 2.0 6.0) ("optimal-value" . -36.0))')
        self.assertShows("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                        ("relations" <= <= <=) ("rhs" 4 12 18)) '())""",
                         '(("solution" 2.0 6.0) ("optimal-value" . -36.0))')
        for bad in ["0", "-3", "2.5", '"many"', "#t"]:
            with self.subTest(max_iterations=bad):
                self.assertLispError("""(lp-solve '(("objective" -3 -5) ("constraints" (1 0) (0 2) (3 2))
                                                    ("relations" <= <= <=) ("rhs" 4 12 18)) %s)""" % bad,
                                     "max-iterations must be a whole number of at least 1")

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


class TestLoadPath(LispTestCase):
    """load looks in the current directory, then in the LISP_PATH
    directories, then in the interpreter's lib and examples directories."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(os.path.join(self.dir, "mine.lsp"), "w") as f:
            f.write("(define from-mine 7)")

    def test_a_file_in_a_lisp_path_directory(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with mock.patch.dict(os.environ, {"LISP_PATH": other + os.pathsep + self.dir}):
            self.run_lisp('(load "mine.lsp")')
        self.assertShows("from-mine", "7")

    def test_the_first_directory_that_has_the_file_wins(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with open(os.path.join(other, "mine.lsp"), "w") as f:
            f.write("(define from-mine 8)")
        with mock.patch.dict(os.environ, {"LISP_PATH": other + os.pathsep + self.dir}):
            self.run_lisp('(load "mine.lsp")')
        self.assertShows("from-mine", "8")

    def test_the_libraries_that_come_with_the_interpreter_are_found(self):
        with mock.patch.dict(os.environ, {"LISP_PATH": ""}):
            self.run_lisp('(load "solver.lsp")')
        self.assertIn("ridders", self.show("(defined-functions)"))

    def test_a_library_can_load_another_from_anywhere(self):
        # option_check.lsp does (load "vol_smile.lsp"); it must work from any directory.
        with mock.patch.dict(os.environ, {"LISP_PATH": ""}):
            cwd = os.getcwd()
            os.chdir(self.dir)
            try:
                self.run_lisp('(load "option_check.lsp")')
            finally:
                os.chdir(cwd)
        self.assertIn("fit-vol-smiles", self.show("(defined-functions)"))

    def test_a_missing_file_says_where_it_looked(self):
        with mock.patch.dict(os.environ, {"LISP_PATH": self.dir}):
            self.assertLispError('(load "nowhere.lsp")', "load: can't find nowhere.lsp in the current directory or in " + self.dir)
        self.assertLispError('(load "/definitely/not/here.lsp")', "load: there's no file /definitely/not/here.lsp")


class TestStandardMacros(LispTestCase):
    """macros_init.lsp: while and do."""

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


class TestLoop(LispTestCase):
    """loop.lsp: the Common Lisp loop macro."""

    def assertAll(self, cases):
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertShows(source, expected)

    # -- stepping ----------------------------------------------------------

    def test_counting(self):
        self.assertAll([
            ("(loop for i from 1 to 5 collect i)", "(1 2 3 4 5)"),
            ("(loop for i to 3 collect i)", "(0 1 2 3)"),
            ("(loop for i upto 3 collect i)", "(0 1 2 3)"),
            ("(loop for i below 3 collect i)", "(0 1 2)"),
            ("(loop for i from 2 below 5 collect i)", "(2 3 4)"),
            ("(loop for i upfrom 2 to 4 collect i)", "(2 3 4)"),
            ("(loop for i from 0 to 10 by 5 collect i)", "(0 5 10)"),
            ("(loop for i from 0 below 10 by 3 collect i)", "(0 3 6 9)"),
            ("(loop for i from 1 to 0 collect i)", "()"),
        ])

    def test_counting_down(self):
        self.assertAll([
            ("(loop for i from 10 downto 7 collect i)", "(10 9 8 7)"),
            ("(loop for i from 5 above 2 collect i)", "(5 4 3)"),
            ("(loop for i downfrom 3 to 1 collect i)", "(3 2 1)"),
            ("(loop for i downfrom 3 above 0 collect i)", "(3 2 1)"),
            ("(loop for i from 6 downto 0 by 2 collect i)", "(6 4 2 0)"),
            ("(loop for i downfrom 6 by 2 repeat 3 collect i)", "(6 4 2)"),
            ("(loop for i from 1 downto 3 collect i)", "()"),
        ])

    def test_counting_with_no_end_goes_on_until_something_stops_it(self):
        self.assertShows("(loop for i from 1 until (> i 4) collect i)", "(1 2 3 4)")
        self.assertShows("(loop for i from 5 repeat 3 collect i)", "(5 6 7)")

    def test_counting_uses_a_limit_and_a_step_evaluated_once(self):
        self.run_lisp("(define calls 0) (define (limit) (set! calls (+ calls 1)) 3) (define (step) (set! calls (+ calls 10)) 1)")
        self.assertShows("(loop for i from 1 to (limit) by (step) collect i)", "(1 2 3)")
        self.assertShows("calls", "11")

    def test_counting_by_a_fraction(self):
        self.assertShows("(loop for x from 0 to 1 by 0.25 collect x)", "(0 0.25 0.5 0.75 1.0)")

    def test_for_in_steps_through_a_list(self):
        self.assertAll([
            ("(loop for x in '(1 2 3) collect (* x 10))", "(10 20 30)"),
            ("(loop for x in '() collect x)", "()"),
            ("(loop for x in (list 1 2) for y in (list 3 4) collect (+ x y))", "(4 6)"),
            ("(loop for x in '(1 2 3) for y in '(a b) collect (list x y))", "((1 a) (2 b))"),
        ])

    def test_the_list_is_evaluated_once(self):
        self.run_lisp("(define calls 0) (define (items) (set! calls (+ calls 1)) (list 1 2 3))")
        self.assertShows("(loop for x in (items) collect x)", "(1 2 3)")
        self.assertShows("calls", "1")

    def test_for_on_steps_through_the_tails(self):
        self.assertShows("(loop for x on '(1 2 3) collect x)", "((1 2 3) (2 3) (3))")
        self.assertShows("(loop for x on '(1 2 3 4) when (> (length x) 2) collect (car x))", "(1 2)")

    def test_for_across_steps_through_a_vector(self):
        self.assertAll([
            ("(loop for x across #(1 2 3) sum x)", "6"),
            ("(loop for x across (vector) collect x)", "()"),
            ("(loop for x across #(1.5 2.5) collect (* x 2))", "(3.0 5.0)"),
        ])

    def test_for_equals_then(self):
        self.assertAll([
            ("(loop for x = 1 then (* x 2) repeat 5 collect x)", "(1 2 4 8 16)"),
            ("(loop for x = 5 repeat 3 collect x)", "(5 5 5)"),
            ("(loop for i from 1 to 3 for x = (* i 10) collect x)", "(10 20 30)"),
            ("(loop for i from 1 to 3 for prev = 0 then i collect (list i prev))", "((1 0) (2 2) (3 3))"),
            ("(loop for a = 1 then b for b = 2 then (+ a b) repeat 4 collect (list a b))", "((1 2) (2 4) (4 8) (8 16))"),
        ])

    def test_for_equals_without_then_is_evaluated_each_time(self):
        self.run_lisp("(define n 0) (define (next!) (set! n (+ n 1)) n)")
        self.assertShows("(loop for x = (next!) repeat 3 collect x)", "(1 2 3)")

    def test_for_over_a_hash_table(self):
        self.run_lisp("(define h (make-hash-table)) (hash-table-set! h 'a 1) (hash-table-set! h 'b 2)")
        self.assertAll([
            ("(loop for k being the hash-keys of h collect k)", "(a b)"),
            ("(loop for v being the hash-values of h sum v)", "3"),
            ("(loop for k being the hash-keys in h using (hash-value v) collect (list k v))", "((a 1) (b 2))"),
            ("(loop for v being each hash-value of h using (hash-key k) collect (list v k))", "((1 a) (2 b))"),
        ])

    def test_patterns_take_a_list_apart(self):
        self.assertAll([
            ("(loop for (a b) in '((1 2) (3 4)) collect (+ a b))", "(3 7)"),
            ("(loop for (k . v) in '((a . 1) (b . 2)) collect (list v k))", "((1 a) (2 b))"),
            ("(loop for (a (b c)) in '((1 (2 3))) collect (list c b a))", "((3 2 1))"),
            ("(loop for (a () c) in '((1 2 3)) collect (list a c))", "((1 3))"),
            ("(loop for (a b) on '(1 2 3) collect (list a b))", "((1 2) (2 3) (3 ()))"),
            ("(loop for (a b c) in '((1) (2 3)) collect (list a b c))", "((1 () ()) (2 3 ()))"),
            ("(loop for (a . b) in '((1 2 3) (4)) collect (list a b))", "((1 (2 3)) (4 ()))"),
            ("(loop for (a b) in '(5 (6 7)) collect (list a b))", "((() ()) (6 7))"),
            ("(loop for (a b) = '(1 2) repeat 2 collect (+ a b))", "(3 3)"),
        ])

    def test_repeat(self):
        self.assertAll([
            ("(loop repeat 3 collect 'x)", "(x x x)"),
            ("(loop repeat 0 collect 'x)", "()"),
            ("(loop repeat (+ 1 1) sum 5)", "10"),
        ])

    def test_variables_take_the_last_value_they_were_given_after_the_loop(self):
        self.assertShows("(loop for i from 1 to 3 finally (return i))", "3")

    # -- accumulating ------------------------------------------------------

    def test_collect_append_sum_count_maximize_minimize(self):
        self.assertAll([
            ("(loop for x in '(1 2 3) collect x)", "(1 2 3)"),
            ("(loop for x in '((1 2) (3) (4 5)) append x)", "(1 2 3 4 5)"),
            ("(loop for x in '((1 2) (3) (4 5)) nconc x)", "(1 2 3 4 5)"),
            ("(loop for x in '(1 2 3) sum x)", "6"),
            ("(loop for x in '(1.5 2.5) sum x)", "4.0"),
            ("(loop for x in '(3 1 4 1 5) count (> x 2))", "3"),
            ("(loop for x in '(3 1 4 1 5) maximize x)", "5"),
            ("(loop for x in '(3 1 4 1 5) minimize x)", "1"),
            ("(loop for x in '(3 1 4 1 5) maximize (- x))", "-1"),
        ])

    def test_an_empty_loop_returns_the_starting_value(self):
        self.assertAll([
            ("(loop for x in '() collect x)", "()"),
            ("(loop for x in '() append x)", "()"),
            ("(loop for x in '() sum x)", "0"),
            ("(loop for x in '() count x)", "0"),
            ("(loop for x in '() maximize x)", "()"),
            ("(loop for x in '() minimize x)", "()"),
        ])

    def test_the_words_can_be_written_as_participles(self):
        self.assertAll([
            ("(loop for x in '(1 2) collecting x)", "(1 2)"),
            ("(loop for x in '((1) (2)) appending x)", "(1 2)"),
            ("(loop for x in '(1 2) summing x)", "3"),
            ("(loop for x in '(1 2) counting (> x 1))", "1"),
            ("(loop for x in '(1 2) maximizing x)", "2"),
            ("(loop for x in '(1 2) minimizing x)", "1"),
            ("(loop as x in '(1 2) collect x)", "(1 2)"),
            ("(loop for x in '(1 2) doing (display x))", "()"),
        ])

    def test_into_accumulates_in_a_named_variable_and_the_loop_returns_nothing_itself(self):
        self.assertShows("(loop for x in '(1 2 3) collect x into xs)", "()")
        self.assertAll([
            ("(loop for x in '(1 2 3) collect x into xs finally (return xs))", "(1 2 3)"),
            ("(loop for x in '(1 2 3) sum x into total finally (return total))", "6"),
            ("(loop for x in '(3 1 4) maximize x into m finally (return (* m 10)))", "40"),
            ("(loop for x in '(1 2 3) collect x into a collect (* x 10) into b finally (return (list a b)))",
             "((1 2 3) (10 20 30))"),
            ("(loop for x in '(1 2 3) sum x into s count #t into n finally (return (/ s n)))", "2.0"),
        ])

    def test_an_into_list_is_in_order_and_usable_while_the_loop_runs(self):
        self.assertShows("(loop for x in '(1 2 3) collect x into xs collect (length xs) into lengths "
                         "finally (return lengths))", "(1 2 3)")

    def test_several_collects_share_one_list_and_collect_mixes_with_append(self):
        self.assertAll([
            ("(loop for x in '(1 2) collect x collect (* x 10))", "(1 10 2 20)"),
            ("(loop for x in '(1 2) collect x append (list x x))", "(1 1 1 2 2 2)"),
            ("(loop for x in '(1 2 3) sum x count #t)", "9"),
        ])

    def test_accumulators_do_not_change_the_list_they_were_given(self):
        self.run_lisp("(define xs (list 1 2 3))")
        self.assertShows("(loop for x in xs collect x into copy finally (return (list xs copy)))", "((1 2 3) (1 2 3))")
        self.run_lisp("(define ys (loop for x in xs append (list x)))")
        self.run_lisp("(set-car! ys 99)")
        self.assertShows("xs", "(1 2 3)")

    def test_a_big_collect_is_fast_enough_and_correct(self):
        self.assertShows("(length (loop for i from 1 to 20000 collect i))", "20000")
        self.assertShows("(loop for i from 1 to 20000 sum i)", "200010000")

    # -- conditionals ------------------------------------------------------

    def test_when_unless_if(self):
        self.assertAll([
            ("(loop for x in '(1 2 3 4 5 6) when (> x 3) collect x)", "(4 5 6)"),
            ("(loop for x in '(1 2 3 4 5 6) if (> x 3) collect x)", "(4 5 6)"),
            ("(loop for x in '(1 2 3 4 5 6) unless (> x 3) collect x)", "(1 2 3)"),
            ("(loop for i from 1 to 6 when (= (mod i 2) 0) sum i)", "12"),
        ])

    def test_else_and_end(self):
        self.assertAll([
            ("(loop for x in '(1 2 3 4) if (< x 3) collect x else collect (- x))", "(1 2 -3 -4)"),
            ("(loop for x in '(1 2 3 4) unless (< x 3) collect x else collect (- x))", "(-1 -2 3 4)"),
            ("(loop for x in '(1 2 3 4) when (< x 3) collect x else collect (- x) end collect 0)",
             "(1 0 2 0 -3 0 -4 0)"),
            ("(loop for x in '(1 2 3 4) when (> x 2) do (display x) end collect x)", "(1 2 3 4)"),
        ])
        self.assertEqual(self.printed(), "34")

    def test_and_joins_clauses_in_a_branch(self):
        self.assertShows("(loop for x in '(1 2 3 4 5) when (> x 2) collect x and sum x into total "
                         "finally (return total))", "12")
        self.assertShows("(loop for x in '(1 2 3 4) if (< x 3) collect x into small and count #t into n "
                         "else collect x into big finally (return (list small big n)))", "((1 2) (3 4) 2)")

    def test_when_can_be_nested_and_an_else_belongs_to_the_nearest_when(self):
        self.assertAll([
            ("(loop for x in '(1 2 3 4 5 6) when (> x 1) when (< x 5) collect x)", "(2 3 4)"),
            # the else goes with the inner when, as in Common Lisp...
            ("(loop for x in '(1 2 3 4 5 6) when (> x 1) when (< x 5) collect x else collect 0)", "(2 3 4 0 0)"),
            # ...unless an end closes the inner one first
            ("(loop for x in '(1 2 3 4 5 6) when (> x 1) when (< x 5) collect x end else collect 0)", "(0 2 3 4)"),
        ])

    def test_when_can_hold_do_with_several_forms(self):
        self.run_lisp("(define seen '())")
        self.run_lisp("(loop for x in '(1 2 3) when (> x 1) do (set! seen (cons x seen)) (set! seen (cons 'x seen)))")
        self.assertShows("seen", "(x 3 x 2)")

    # -- do, initially, finally, with --------------------------------------

    def test_do_runs_its_forms_and_the_loop_returns_nothing(self):
        self.assertShows("(loop for i from 1 to 3 do (display i))", "()")
        self.assertEqual(self.printed(), "123")

    def test_do_takes_several_forms_and_stops_at_the_next_word(self):
        self.assertShows("(loop for i from 1 to 2 do (display i) (display \"-\") collect i)", "(1 2)")
        self.assertEqual(self.printed(), "1-2-")

    def test_initially_and_finally(self):
        self.assertShows("(loop initially (display \"[\") for i from 1 to 3 do (display i) finally (display \"]\"))", "()")
        self.assertEqual(self.printed(), "[123]")

    def test_finally_can_return_the_answer(self):
        self.assertShows("(loop for i from 1 to 5 sum i into total finally (return (* total 2)))", "30")

    def test_finally_runs_after_a_while_or_until_stops_the_loop(self):
        self.assertShows("(loop for i from 1 to 10 while (< i 4) finally (return i))", "4")

    def test_with_binds_variables_once(self):
        self.assertAll([
            ("(loop with x = 10 for i from 1 to 3 collect (+ x i))", "(11 12 13)"),
            ("(loop with a = 1 and b = 2 for i from 1 to 2 collect (+ a b i))", "(4 5)"),
            ("(loop with a = 1 with b = (+ a 1) for i from 1 to 2 collect (list a b))", "((1 2) (1 2))"),
            ("(loop with n = 3 for i from 1 to n collect i)", "(1 2 3)"),
            ("(loop with x for i from 1 to 2 collect x)", "(() ())"),
        ])

    def test_with_can_hold_state_changed_by_the_body(self):
        self.assertShows("(loop with total = 0 for x in '(1 2 3) do (set! total (+ total x)) finally (return total))", "6")

    # -- stopping ----------------------------------------------------------

    def test_while_and_until(self):
        self.assertAll([
            ("(loop for i from 1 to 10 while (< i 4) collect i)", "(1 2 3)"),
            ("(loop for i from 1 to 10 until (> i 3) collect i)", "(1 2 3)"),
            ("(loop for x in '(1 2 3 4) while (< x 3) collect x)", "(1 2)"),
            ("(loop for i from 1 to 3 collect i while (< i 2))", "(1 2)"),
        ])

    def test_a_while_in_the_middle_ends_the_pass_at_that_point(self):
        self.run_lisp("(define log '())")
        self.run_lisp("(loop for i from 1 to 5 do (set! log (cons (list 'a i) log)) while (< i 2) do (set! log (cons (list 'b i) log)))")
        self.assertShows("(reverse log)", "((a 1) (b 1) (a 2))")

    def test_always_never_thereis(self):
        self.assertAll([
            ("(loop for x in '(1 2 3) always (> x 0))", "#t"),
            ("(loop for x in '(1 2 3) always (> x 1))", "#f"),
            ("(loop for x in '() always #f)", "#t"),
            ("(loop for x in '(1 2 3) never (> x 5))", "#t"),
            ("(loop for x in '(1 2 3) never (> x 2))", "#f"),
            ("(loop for x in '(1 2 3) thereis (> x 2))", "#t"),
            ("(loop for x in '(1 2 3) thereis (> x 5))", "#f"),
            ("(loop for x in '(1 2 3 4) thereis (and (> x 2) (* x 10)))", "30"),
        ])

    def test_always_stops_at_the_first_failure(self):
        self.run_lisp("(define seen '())")
        self.run_lisp("(loop for x in '(1 2 3 4) do (set! seen (cons x seen)) always (< x 2))")
        self.assertShows("seen", "(2 1)")

    def test_a_failed_always_skips_finally(self):
        self.run_lisp("(define ran #f)")
        self.assertShows("(loop for x in '(1 2) always (> x 1) finally (set! ran #t))", "#f")
        self.assertShows("ran", "#f")
        self.assertShows("(loop for x in '(2 3) always (> x 1) finally (set! ran #t))", "#t")
        self.assertShows("ran", "#t")

    # -- return, named loops, the simple loop ------------------------------

    def test_return_leaves_the_loop_with_a_value(self):
        self.assertAll([
            ("(loop for x in '(1 2 3 4) do (if (= x 3) (return x)))", "3"),
            ("(loop for x in '(1 2 3 4) when (> x 2) return x)", "3"),
            ("(loop for x in '(1 2 3 4) when (> x 9) return x)", "()"),
            ("(loop for x in '(1 2 3) do (return))", "()"),
            ("(loop for x in '(1 2 3) collect x do (return 'early))", "early"),
        ])

    def test_return_skips_finally_and_the_accumulated_value(self):
        self.run_lisp("(define ran #f)")
        self.assertShows("(loop for x in '(1 2 3) collect x do (if (= x 2) (return 'stopped)) finally (set! ran #t))", "stopped")
        self.assertShows("ran", "#f")

    def test_return_can_be_deep_inside_the_forms_of_the_loop(self):
        self.assertAll([
            ("(loop for x in '(1 2 3 4) do (let ((y (* x 10))) (if (> y 25) (return y))))", "30"),
            ("(loop for x in '(1 2 3 4) do (map (lambda (n) (if (> n 25) (return n))) (list (* x 10))))", "30"),
        ])

    def test_a_return_in_a_function_the_loop_calls_is_not_found(self):
        # Like return in Common Lisp, it belongs to the loop it's written in. (The loop only
        # sets up a place for it to go when it sees a return in its own clauses.)
        self.run_lisp("(define (check x) (if (> x 2) (return x)))")
        self.assertLispError("(loop for x in '(1 2 3 4) do (check x))", "nothing catches loop-nil")
        self.assertShows("(catch 'loop-nil (loop for x in '(1 2 3 4) do (check x)))", "3")     # throw and catch do it

    def test_return_leaves_only_the_innermost_loop(self):
        self.assertShows("(loop for i from 1 to 3 collect (loop for j from 1 to 5 do (if (> j i) (return j))))", "(2 3 4)")

    def test_a_named_loop_and_return_from(self):
        self.assertShows("(loop named search for i from 1 to 3 do (loop for j from 1 to 3 "
                         "do (if (= (* i j) 6) (return-from search (list i j)))))", "(2 3)")
        self.assertShows("(loop named outer for i from 1 to 3 do (loop for j from 1 to 3 "
                         "do (if (= (* i j) 4) (return-from outer (list i j)))))", "(2 2)")

    def test_return_from_an_outer_loop_can_be_used_with_an_inner_unnamed_one(self):
        self.assertShows("(loop named a for i from 1 to 3 collect (loop for j from 1 to 3 "
                         "do (if (= i 2) (return-from a 'gone)) (if (= j 2) (return j))))", "gone")

    def test_the_simple_loop_repeats_until_return(self):
        self.assertAll([
            ("(loop (return 5))", "5"),
            ("(begin (define i 0) (loop (set! i (+ i 1)) (if (> i 4) (return i))))", "5"),
            ("(begin (define j 0) (loop (set! j (+ j 1)) (if (> j 3) (return (* j 2)))))", "8"),
        ])

    def test_return_and_return_from_outside_a_loop_are_errors(self):
        self.assertLispError("(return 5)", "nothing catches loop-nil")
        self.assertLispError("(return-from nowhere 5)", "nothing catches nowhere")

    def test_return_works_from_a_loop_in_a_function_called_again_and_again(self):
        self.run_lisp("(define (first-big xs) (loop for x in xs when (> x 10) return x))")
        self.assertShows("(list (first-big '(1 20 3)) (first-big '(1 2 3)) (first-big '(50)))", "(20 () 50)")

    # -- hygiene and scope -------------------------------------------------

    def test_the_hidden_variables_do_not_clash_with_yours(self):
        # the names the loop makes for itself all start with %, and can't be typed
        self.run_lisp("(define rest '(9 9)) (define result 'mine) (define tail 'mine) (define next 'mine) (define limit 'mine)")
        self.assertShows("(loop for x in '(1 2 3) collect x)", "(1 2 3)")
        self.assertShows("(loop for i from 1 to 3 sum i)", "6")
        self.assertShows("(list rest result tail next limit)", "((9 9) mine mine mine mine)")

    def test_nested_loops_over_the_same_variable_names(self):
        self.assertShows("(loop for i from 1 to 2 collect (loop for i from 1 to 3 collect (* i 10)))",
                         "((10 20 30) (10 20 30))")

    def test_the_loop_variable_is_not_visible_outside_the_loop(self):
        self.run_lisp("(loop for zzz from 1 to 3 collect zzz)")
        self.assertLispError("zzz", "unbound symbol")

    def test_a_loop_variable_can_shadow_a_global_one(self):
        self.run_lisp("(define x 'global)")
        self.assertShows("(loop for x in '(1 2) collect x)", "(1 2)")
        self.assertShows("x", "global")

    def test_a_loop_in_a_recursive_function(self):
        self.run_lisp("(define (depth tree) (if (pair? tree) (+ 1 (loop for child in tree maximize (depth child))) 0))")
        self.assertShows("(depth '((1 2) ((3)) 4))", "3")

    def test_closures_made_in_a_loop_share_the_variable(self):
        # As in Common Lisp, a loop steps one variable, it doesn't make a new one on each pass.
        self.run_lisp("(define fs (loop for i from 1 to 3 collect (lambda () i)))")
        self.assertShows("(map (lambda (f) (f)) fs)", "(3 3 3)")

    def test_a_loop_can_be_used_where_a_value_is_wanted(self):
        self.assertShows("(+ 1 (loop for i from 1 to 3 sum i))", "7")
        self.assertShows("(list (loop repeat 2 collect 'a) (loop repeat 1 collect 'b))", "((a a) (b))")

    def test_a_long_loop_does_not_use_up_the_stack(self):
        self.assertShows("(loop for i from 1 to 50000 count (> i 25000))", "25000")

    # -- clauses happen in order -------------------------------------------

    def test_clauses_happen_in_order(self):
        # a stepping clause after a body clause steps at that point of each pass
        self.assertShows("(loop for i from 1 to 3 collect i for j = (* i 10) collect j)", "(1 10 2 20 3 30)")

    # -- reading the clauses -----------------------------------------------

    def test_a_loop_with_no_body_clauses_just_runs(self):
        self.assertShows("(loop for i from 1 to 3)", "()")

    def test_keyword_words_can_also_be_variable_names_in_expressions(self):
        self.run_lisp("(define count 5) (define sum 7)")
        self.assertShows("(loop for i from 1 to 2 collect (+ count sum i))", "(13 14)")

    def test_a_pasted_expansion_still_works(self):
        expansion = self.show("(macroexpand-1 '(loop for i from 1 to 3 collect i))")
        self.assertShows(expansion, "(1 2 3)")

    def test_it_is_expanded_only_once_however_often_it_runs(self):
        self.run_lisp("(define n 0) (define (f) (loop for i from 1 to 2 sum i)) (define calls 0)")
        before = lisp_core._gensym_counter[0]
        self.run_lisp("(f)")
        after_first = lisp_core._gensym_counter[0]
        self.run_lisp("(f) (f) (f)")
        self.assertGreater(after_first, before)
        self.assertEqual(lisp_core._gensym_counter[0], after_first)     # no new expansion, so no new gensyms

    # -- mistakes get clear messages ---------------------------------------

    def test_errors_say_what_is_wrong(self):
        cases = [
            ("(loop for x in '(1 2) frobnicate x)", "don't know the loop word frobnicate"),
            ("(loop for x in '(1 2) (print x))", "needs do in front of it"),
            ("(loop for x in)", "the clauses ended where a list after in was expected"),
            ("(loop for x)", "the clauses ended where"),
            ("(loop for)", "the clauses ended where a variable after for was expected"),
            ("(loop for x in '(1 2) collect)", "an expression after collect was expected"),
            ("(loop for x in '(1 2) collect x into)", "a variable after into was expected"),
            ("(loop for x in '(1 2) collect x sum x)", "can't accumulate a number and a list in the same variable"),
            ("(loop for x in '(1 2) maximize x minimize x)", "can't accumulate a minimize and a maximize"),
            ("(loop for i downto 1 collect i)", "counting down needs a starting value"),
            ("(loop for (a b) from 1 to 3 collect a)", "counting needs a single variable"),
            ("(loop for x in '(1) for y in '(2) and z in '(3) collect x)", "and can only join clauses inside a when"),
            ("(loop for x in '(1 2) when (> x 1) while (< x 5) collect x)", "while can't be inside a when"),
            ("(loop for x in '(1 2) when (> x 1) for y in '(3) collect y)", "for can't be inside a when"),
            ("(loop for x being the elements of '(1 2) collect x)", "expected hash-keys or hash-values, not elements"),
            ("(loop for x in '(1 2) when)", "the clauses ended where a test after when"),
            ("(loop named)", "a name after named was expected"),
            ("(loop with)", "a variable after with was expected"),
            ("(loop repeat)", "a number after repeat was expected"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                self.assertLispError(source, message)


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

    def test_the_shipped_startup_files_load_cleanly_and_define_while_do_and_loop(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            lisp_builtins.load_init_file(self.env, lisp_builtins.DEFAULT_INIT_FILE)
        self.assertEqual(err.getvalue(), "")
        self.assertShows("(define i 0) (while (< i 5) (set! i (+ i 1))) i", "5")
        self.assertShows("(do ((i 0 (+ i 1))) ((= i 5) i))", "5")
        self.assertShows("(loop for i from 1 to 3 collect i)", "(1 2 3)")

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
        self.run_lisp('(load "%s")' % os.path.join(LIB, "template.lsp"))

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
        self.env = lisp_builtins.make_global_env(output=self.out.append, table=self.tables.append)
        self.run_lisp('(load "%s")' % os.path.join(LIB, "column_engine.lsp"))

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

    def test_display_table_receives_only_the_visible_columns(self):
        self.run_lisp("""
          (defcolumn a-col :name "a" :initial_value 1 :value_calculation (+ a 1))
          (defcolumn hidden-col :name "hidden" :initial_value 0 :visible #f
                     :value_calculation (+ hidden 1))
          (calculate-all *columns* 3)""")
        self.assertEqual(len(self.tables), 1)
        self.assertEqual(self.tables[0], [("a", ["1", "2", "3"], "right")])     # decimals 0, with commas

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
        self.assertShows("(macroexpand '(let ((x 1)) x))", "((%scope-lambda (x) x) 1)")
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
        # let and let* are macros: level 3 shows how they expand, but no calls.
        text = self.trace_of(3, "(let ((x 1)) (let* ((y 2)) (+ x y)))")
        self.assertTrue(text)
        for line in text.splitlines():
            self.assertTrue(line.lstrip().startswith("~ "), line)
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
                         "Error: needs-two: expected 2 arguments, got 1\n")

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
        self.assertIsInstance(e, lisp_core.LispError)
        self.assertEqual(str(e), "/: division by zero")
        self.assertIsInstance(e.__cause__, ZeroDivisionError)       # the original, for LISP_PYTHON_TRACEBACK
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


class TestBreakpoints(LispTestCase):
    """(break ...), (unbreak ...), and (breakpoints): stop when a procedure is called."""

    def test_break_stops_at_the_call_with_the_arguments_bound(self):
        text = self.run_with_input("(define (f x) (* x 2)) (break f) (f 5)", ["x", "(continue)"])
        self.assertIn("--- break: entering f(5) ---", text)
        self.assertIn("5", text.splitlines())               # typing x showed its value
        self.assertEqual(self.result, 10)

    def test_the_debug_repl_can_change_an_argument_before_the_body_runs(self):
        self.run_with_input("(define (f x) (* x 2)) (break f) (f 5)", ["(set! x 100)", "(continue)"])
        self.assertEqual(self.result, 200)

    def test_it_stops_at_every_call_including_recursive_and_tail_calls(self):
        text = self.run_with_input(
            "(define (fact n acc) (if (= n 0) acc (fact (- n 1) (* n acc)))) (break fact) (fact 2 1)",
            ["(continue)"] * 3)
        self.assertEqual(text.count("entering fact("), 3)
        self.assertEqual(self.result, 2)

    def test_it_stops_at_calls_made_by_map_and_other_builtins(self):
        text = self.run_with_input("(define (f x) x) (break f) (map f (list 1 2))", ["(continue)"] * 2)
        self.assertEqual(text.count("entering f("), 2)

    def test_the_breakpoint_stays_when_the_function_is_redefined(self):
        self.run_lisp("(define (f x) x) (break f) (define (f x) (+ x 100))")
        text = self.run_with_input("(f 1)", ["(continue)"])
        self.assertIn("entering f(1)", text)
        self.assertEqual(self.result, 101)

    def test_a_function_made_by_define_and_lambda_can_have_a_breakpoint(self):
        text = self.run_with_input("(define k (lambda (x) x)) (break k) (k 3)", ["(continue)"])
        self.assertIn("entering k(3)", text)

    def test_a_condition_makes_it_stop_only_when_it_is_true(self):
        text = self.run_with_input("(define (f x) x) (break f '(> x 5)) (list (f 1) (f 9))", ["(continue)"])
        self.assertEqual(text.count("entering f("), 1)
        self.assertIn("entering f(9)", text)

    def test_a_condition_that_fails_is_an_error(self):
        self.run_lisp("(define (f x) x) (break f '(> x no-such-variable))")
        self.assertLispError("(f 1)", "unbound symbol")

    def test_break_takes_the_procedure_a_symbol_or_a_string(self):
        self.run_lisp("(define (f x) x) (define (g x) x) (define (h x) x)")
        self.assertShows("(break f)", "f")
        self.assertShows("(break 'g)", "g")
        self.assertShows('(break "h")', "h")
        self.assertShows("(breakpoints)", "((f) (g) (h))")

    def test_breakpoints_lists_each_with_its_condition(self):
        self.run_lisp("(define (f x) x) (define (g x) x) (break f) (break g '(> x 5))")
        self.assertShows("(breakpoints)", "((f) (g (> x 5)))")

    def test_break_again_replaces_the_condition(self):
        self.run_lisp("(define (f x) x) (break f '(> x 5)) (break f)")
        self.assertShows("(breakpoints)", "((f))")

    def test_unbreak_removes_one_breakpoint_or_all_of_them(self):
        self.run_lisp("(define (f x) x) (define (g x) x) (break f) (break g)")
        self.run_lisp("(unbreak f)")
        self.assertShows("(breakpoints)", "((g))")
        self.run_lisp("(break f) (unbreak)")
        self.assertShows("(breakpoints)", "()")
        self.run_with_input("(f 1) (g 1)", [])              # no stops: there's no input to answer one
        self.run_lisp("(unbreak 'never-set)")              # removing what isn't there is fine
        self.assertLispError("(unbreak 'f 'g)", "at most one argument")

    def test_a_name_that_is_not_defined_yet_gets_a_note_but_the_breakpoint_applies_later(self):
        self.assertShows("(break 'later)", "later")
        self.assertIn("no function named later is defined yet", self.printed())
        text = self.run_with_input("(define (later x) x) (later 1)", ["(continue)"])
        self.assertIn("entering later(1)", text)

    def test_break_rejects_builtins_macros_unnamed_procedures_and_other_values(self):
        self.run_lisp("(defmacro m (x) x)")
        self.assertLispError("(break car)", "built-in")
        self.assertLispError("(break m)", "a macro can't have a breakpoint")
        self.assertLispError("(break (lambda (x) x))", "has no name")
        self.assertLispError("(break 5)", "expected a procedure or its name")

    def test_a_stop_inside_a_stop_works_when_a_broken_function_is_called_from_the_repl(self):
        text = self.run_with_input("(define (f x) (* x 2)) (define (g y) y) (break f) (break g) (f 1)",
                                   ["(g 7)", "(continue)", "(continue)"])
        self.assertIn("entering g(7)", text)
        self.assertEqual(self.result, 2)
        self.assertIsNone(lisp_core.current_pause())


class TestDebugHook(LispTestCase):
    """(set-debug-hook! ...): a procedure that decides what happens at a stop."""

    def test_a_hook_is_called_with_the_kind_the_name_and_the_arguments(self):
        self.run_lisp("(define log '()) (define (f x y) (+ x y))"
                      "(set-debug-hook! (lambda (kind name args) (set! log (cons (list kind name args) log))))"
                      "(break f)")
        self.assertShows("(f 1 2)", "3")                   # the hook returned, so the program carried on
        self.assertShows("log", "((break f (1 2)))")

    def test_a_hook_decides_to_open_the_debug_repl_by_calling_it(self):
        text = self.run_with_input(
            "(define (f x) (* x 2)) (break f)"
            "(set-debug-hook! (lambda (kind name args) (if (> (car args) 5) (debug-repl))))"
            "(list (f 1) (f 9))",
            ["x", "(continue)"])
        self.assertEqual(text.count("debug REPL"), 1)         # for (f 9) only
        self.assertIn("9", text.splitlines())               # x, typed in the REPL
        self.assertEqual(lisp_core.to_string(self.result), "(2 18)")

    def test_a_hook_sees_breakpoint_forms_with_their_message(self):
        self.run_lisp("(define log '())"
                      "(set-debug-hook! (lambda (kind name args) (set! log (list kind name args))))"
                      "(define (h z) (breakpoint (list \"z is\" z)) z)")
        self.assertShows("(h 3)", "3")
        self.assertShows("log", '(breakpoint ("z is" 3) ())')
        self.run_lisp("(breakpoint)")
        self.assertShows("log", "(breakpoint () ())")

    def test_a_hook_that_does_nothing_silences_every_breakpoint(self):
        self.run_with_input("(set-debug-hook! (lambda (k n a) '()))"
                            "(define (f x) (breakpoint) x) (break f) (f 4)", [])
        self.assertEqual(self.result, 4)

    def test_set_debug_hook_returns_the_previous_hook_and_can_remove_it(self):
        self.assertShows("(debug-hook)", "()")
        self.assertShows("(set-debug-hook! (lambda (k n a) 1))", "()")
        self.assertShows("(procedure? (debug-hook))", "#t")
        self.run_lisp("(define first-hook (debug-hook))")
        self.assertShows("(eq? (set-debug-hook! (lambda (k n a) 2)) first-hook)", "#t")
        self.run_lisp("(set-debug-hook! '())")
        self.assertShows("(debug-hook)", "()")

    def test_the_hook_must_be_a_procedure(self):
        self.assertLispError("(set-debug-hook! 5)", "expected a procedure")

    def test_calls_the_hook_makes_do_not_stop_again(self):
        self.run_lisp("(define count 0) (define (helper x) x) (define (f x) x) (break helper) (break f)"
                      "(set-debug-hook! (lambda (k n a) (set! count (+ count 1)) (helper 1)))")
        self.run_lisp("(f 1)")
        self.assertShows("count", "1")
        self.run_lisp("(helper 2)")                        # outside the hook, it stops again
        self.assertShows("count", "2")

    def test_a_hook_can_leave_the_computation_with_throw(self):
        self.run_lisp("(define (f x) x) (break f) (set-debug-hook! (lambda (k n a) (throw 'out 'thrown)))")
        self.assertShows("(catch 'out (list (f 1) 'not-reached))", "thrown")
        self.assertIsNone(lisp_core.current_pause())
        self.assertFalse(lisp_core.debug_state.hook_running)
        self.run_lisp("(set-debug-hook! '()) (unbreak)")
        self.assertShows("(f 2)", "2")                      # the debugger is back to normal

    def test_an_error_in_the_hook_is_an_error_of_the_program(self):
        self.run_lisp("(define (f x) x) (break f) (set-debug-hook! (lambda (k n a) (error \"hook failed\")))")
        self.assertLispError("(f 1)", "hook failed")
        self.assertIsNone(lisp_core.current_pause())
        self.assertFalse(lisp_core.debug_state.hook_running)

    def test_debug_repl_and_locals_need_a_stop(self):
        self.assertLispError("(debug-repl)", "isn't stopped anywhere")
        self.assertLispError("(locals)", "isn't stopped anywhere")

    def test_locals_lists_the_variables_innermost_first_without_globals(self):
        self.run_lisp("(define global-one 1) (define log '())"
                      "(set-debug-hook! (lambda (k n a) (set! log (locals))))"
                      "(define (f x) (let ((y 2)) (breakpoint) y))")
        self.run_lisp("(f 5)")
        self.assertShows("log", "((y . 2) (x . 5))")

    def test_locals_shows_only_the_innermost_of_two_variables_with_one_name(self):
        self.run_lisp("(define log '())"
                      "(set-debug-hook! (lambda (k n a) (set! log (locals))))"
                      "(define (f x) (let ((x 9)) (breakpoint)))")
        self.run_lisp("(f 1)")
        self.assertShows("log", "((x . 9))")

    def test_locals_leaves_out_the_evaluators_own_hidden_names(self):
        self.run_lisp("(define log '())"
                      "(set-debug-hook! (lambda (k n a) (set! log (locals))))"
                      "(define (f xs) (dolist (x xs) (breakpoint)))")
        self.run_lisp("(f (list 10 20))")
        self.assertShows("log", "((x . 20) (xs 10 20))")

    def test_locals_includes_the_scope_of_an_enclosing_function(self):
        self.run_lisp("(define log '())"
                      "(set-debug-hook! (lambda (k n a) (set! log (map car (locals)))))"
                      "(define (outer a) (define (inner b) (breakpoint) b) (inner (+ a 1)))")
        self.run_lisp("(outer 1)")
        self.assertShows("log", "(b a inner)")

    def test_the_debug_repl_cuts_off_a_very_long_result(self):
        text = self.run_with_input("(breakpoint)", ["(vector-range 5000)", "(continue)"])
        self.assertIn("more characters]", text)
        self.assertLess(len(text), 3000)


class TestAbort(LispTestCase):
    """(abort): abandon the computation and go back to the top level."""

    def test_abort_is_not_caught_by_catch_error_but_unwind_protect_cleans_up(self):
        self.run_lisp("(define cleaned #f)")
        self.assertAborts("(unwind-protect (catch-error (abort) (e) 'caught) (set! cleaned #t))")
        self.assertShows("cleaned", "#t")

    def test_abort_typed_in_the_debug_repl_abandons_the_whole_computation(self):
        self.run_lisp("(define (f x) (* x 2)) (define (g y) (list (f y) 'not-reached)) (break f)")
        with self.assertRaises(lisp_core.LispAbort):
            self.run_with_input("(g 5)", ["(abort)"])
        self.assertIsNone(lisp_core.current_pause())        # the debugger is no longer stopped
        self.assertFalse(lisp_core.debug_state.hook_running)
        self.assertEqual(lisp_core._active_stacks, [])      # no evaluator is left half-run
        self.run_lisp("(unbreak)")
        self.assertShows("(g 5)", "(10 not-reached)")       # and the interpreter works as before

    def test_abort_called_by_a_hook(self):
        self.run_lisp("(define (f x) x) (break f) (set-debug-hook! (lambda (k n a) (abort)))")
        self.assertAborts("(f 1)")
        self.assertIsNone(lisp_core.current_pause())
        self.assertFalse(lisp_core.debug_state.hook_running)

    def test_abort_ends_a_stop_inside_a_stop(self):
        self.run_lisp("(define (f x) x) (define (g y) y) (break f) (break g)")
        with self.assertRaises(lisp_core.LispAbort):
            self.run_with_input("(f 1)", ["(g 2)", "(abort)"])
        self.assertIsNone(lisp_core.current_pause())


class TestBreakOnError(LispTestCase):
    """(break-on-error #t): stop where an error happens."""

    RISKY = ("(define (risky a) (let ((c (+ a 1))) (car c)))"
             "(define (outer n) (list (risky n)))")

    def test_it_is_off_until_turned_on_and_returns_the_previous_setting(self):
        self.assertShows("(break-on-error)", "#f")
        self.assertShows("(break-on-error #t)", "#f")
        self.assertShows("(break-on-error)", "#t")
        self.assertShows("(break-on-error #f)", "#t")
        self.assertLispError("(break-on-error #t #t)", "at most one argument")

    def test_nothing_stops_for_an_error_while_it_is_off(self):
        self.run_lisp(self.RISKY + "(set-debug-hook! (lambda (k n a) (error \"stopped\")))")
        self.assertLispError("(outer 1)", "car: not a pair")

    def test_it_stops_where_the_error_happened_with_the_variables_there(self):
        self.run_lisp(self.RISKY + "(define seen '())"
                      "(set-debug-hook! (lambda (k n a) (set! seen (list k n (locals)))))"
                      "(break-on-error #t)")
        self.assertLispError("(outer 1)", "car: not a pair: 2")      # the error still goes on
        self.assertShows("seen", '(error "car: not a pair: 2" ((c . 2) (a . 1)))')

    def test_it_leaves_alone_an_error_that_catch_error_will_handle(self):
        self.run_lisp(self.RISKY + "(define count 0)"
                      "(set-debug-hook! (lambda (k n a) (set! count (+ count 1))))"
                      "(break-on-error #t)")
        self.assertShows("(catch-error (outer 1) (e) 'handled)", "handled")
        self.assertShows("count", "0")
        self.assertLispError("(outer 1)", "car: not a pair")
        self.assertShows("count", "1")

    def test_an_error_in_a_catch_error_handler_is_not_protected_by_it(self):
        self.run_lisp("(define count 0)"
                      "(set-debug-hook! (lambda (k n a) (set! count (+ count 1))))"
                      "(break-on-error #t)")
        self.assertLispError("(catch-error (car 1) (e) (cdr 2))", "cdr: not a pair")
        self.assertShows("count", "1")                      # only the handler's error stopped

    def test_it_stops_once_as_the_error_passes_out_of_nested_evaluations(self):
        self.run_lisp("(define count 0) (define seen '())"
                      "(set-debug-hook! (lambda (k n a) (set! count (+ count 1)) (set! seen (locals))))"
                      "(define (f xs) (map (lambda (x) (car x)) xs))"
                      "(break-on-error #t)")
        self.assertLispError("(f (list 1))", "car: not a pair")
        self.assertShows("count", "1")
        self.assertShows("seen", "((x . 1) (xs 1))")        # the callback's scope, where it happened, then f's

    def test_a_python_error_from_a_builtin_stops_too(self):
        self.run_lisp("(define count 0) (set-debug-hook! (lambda (k n a) (set! count (+ count 1))))"
                      "(break-on-error #t)")
        self.assertLispError("(/ 1 0)", "/: division by zero")
        self.assertShows("count", "1")

    def test_the_debug_repl_for_an_error_can_be_left_with_continue_and_the_error_goes_on(self):
        self.run_lisp("(break-on-error #t)")
        with self.assertRaises(lisp_core.LispError):
            self.run_with_input("(car 5)", ["(continue)"])
        text = self.console.getvalue()
        self.assertIn("--- error: car: not a pair: 5 ---", text)
        self.assertIn("(continue) lets the error go on", text)

    def test_an_error_typed_in_the_debug_repl_is_reported_and_does_not_stop_again(self):
        self.run_lisp("(break-on-error #t)")
        text = self.run_with_input("(define (f x) (breakpoint) x) (f 1)", ["(car 5)", "(continue)"])
        self.assertIn("Error: car: not a pair: 5", text)
        self.assertEqual(text.count("--- error:"), 0)
        self.assertEqual(self.result, 1)

    def test_a_hook_can_abort_at_an_error(self):
        self.run_lisp("(set-debug-hook! (lambda (k n a) (abort))) (break-on-error #t)")
        self.assertAborts("(car 5)")
        self.assertIsNone(lisp_core.current_pause())

    def test_running_out_of_stack_is_not_debugged(self):
        self.run_lisp("(define count 0) (set-debug-hook! (lambda (k n a) (set! count (+ count 1))))"
                      "(break-on-error #t)")
        self.assertRaisesFromLisp(RecursionError, "(eval '(define (loop-forever) (+ 1 (eval '(loop-forever)))))"
                                                  " (eval '(loop-forever))")
        self.assertShows("count", "0")


class TestDebugReplFunction(LispTestCase):
    """set_debug_repl: a front end with no console installs its own debug REPL."""

    def test_a_stop_opens_the_installed_repl_with_where_and_why(self):
        opened = []
        previous = lisp_core.set_debug_repl(lambda env, label, resume: opened.append((label, resume, env)))
        self.addCleanup(lisp_core.set_debug_repl, previous)
        self.run_lisp("(define (f x) (* x 2)) (break f) (define answer (f 5))")
        self.assertShows("answer", "10")
        self.assertEqual([(label, resume) for label, resume, _ in opened], [("f", "resumes")])
        self.assertEqual(lisp_core.to_string(lisp_core.visible_variables(opened[0][2])), "((x . 5))")

    def test_an_error_stop_says_that_continuing_lets_the_error_go_on(self):
        opened = []
        previous = lisp_core.set_debug_repl(lambda env, label, resume: opened.append((label, resume)))
        self.addCleanup(lisp_core.set_debug_repl, previous)
        self.run_lisp("(break-on-error #t)")
        self.assertLispError("(car 5)", "not a pair")
        self.assertEqual(opened, [("error", "lets the error go on")])

    def test_calls_made_in_the_installed_repl_can_stop_again(self):
        stops = []

        def repl(env, label, resume):
            stops.append(label)
            if label == "f":
                lisp_core.seval(list(lisp_core.parse("(g 1)"))[0], env)      # what typing (g 1) would do

        previous = lisp_core.set_debug_repl(repl)
        self.addCleanup(lisp_core.set_debug_repl, previous)
        self.run_lisp("(define (f x) x) (define (g x) x) (break f) (break g) (f 1)")
        self.assertEqual(stops, ["f", "g"])

    def test_the_installed_repl_can_abort(self):
        def repl(env, label, resume):
            raise lisp_core.LispAbort()
        previous = lisp_core.set_debug_repl(repl)
        self.addCleanup(lisp_core.set_debug_repl, previous)
        self.run_lisp("(define (f x) x) (break f)")
        self.assertAborts("(f 1)")
        self.assertIsNone(lisp_core.current_pause())
        self.assertFalse(lisp_core.debug_state.hook_running)


class FakeShellFrame:
    """What zmq gives the kernel for a message part: something with .bytes."""
    def __init__(self, data):
        self.bytes = data


class FakeKernel:
    """Just enough of an ipykernel for KernelMessagePump: a queue of shell
    messages, a session to read them with, and the parent-message calls."""

    def __init__(self):
        import queue
        from jupyter_client.session import Session
        self.session = Session()
        self.msg_queue = queue.Queue()
        self.shell_stream = mock.Mock()
        self._parent_ident = {"shell": b"the-cell"}
        self.parent = {"header": {"msg_id": "the-cell's-execute-request"}}
        self.set_parent_calls = []
        self.handled = []              # the types of the messages the kernel handled
        self.counter = 0

    def get_parent(self, channel=None):
        return self.parent

    def set_parent(self, ident, parent, channel="shell"):
        self.set_parent_calls.append((ident, parent, channel))
        self._parent_ident[channel] = ident
        self.parent = parent

    def queue_message(self, msg_type):
        frames = [FakeShellFrame(b"client"), FakeShellFrame(b"<IDS|MSG>")] + \
                 [FakeShellFrame(part) for part in self.session.serialize(self.session.msg(msg_type, {}))[1:]]
        kernel = self

        async def dispatch(message_frames):
            kernel.handled.append(msg_type)
        self.counter += 1
        self.msg_queue.put_nowait((self.counter, dispatch, (frames,)))

    def queued_types(self):
        types = []
        for item in list(self.msg_queue.queue):
            types.append(lisp_jupyter_debug.KernelMessagePump(self).message_type(item[2]))
        return types


class TestKernelMessagePump(unittest.TestCase):
    """The pump handles the widget messages that reach a kernel while a cell is
    running, and leaves everything else in the queue, in order."""

    def setUp(self):
        try:
            self.kernel = FakeKernel()
        except ImportError:
            self.skipTest("jupyter_client is not installed")
        self.pump = lisp_jupyter_debug.KernelMessagePump(self.kernel)

    def test_widget_messages_are_handled_and_the_others_stay_queued_in_order(self):
        for msg_type in ["execute_request", "comm_msg", "execute_request", "comm_open",
                         "kernel_info_request", "comm_close", "comm_info_request"]:
            self.kernel.queue_message(msg_type)
        self.pump.handle_widget_messages()
        self.assertEqual(self.kernel.handled, ["comm_msg", "comm_open", "comm_close", "comm_info_request"])
        self.assertEqual(self.kernel.queued_types(), ["execute_request", "execute_request", "kernel_info_request"])

    def test_messages_that_arrive_later_come_after_the_ones_that_were_held(self):
        self.kernel.queue_message("execute_request")
        self.pump.handle_widget_messages()
        self.kernel.queue_message("execute_request")
        self.kernel.queue_message("comm_msg")
        self.pump.handle_widget_messages()
        self.assertEqual(self.kernel.handled, ["comm_msg"])
        ids = [item[0] for item in list(self.kernel.msg_queue.queue)]
        self.assertEqual(ids, sorted(ids))                          # still in the order they came

    def test_it_asks_the_stream_for_the_messages_that_are_waiting(self):
        self.pump.handle_widget_messages()
        self.kernel.shell_stream.flush.assert_called_once()

    def test_an_empty_queue_is_fine(self):
        self.pump.handle_widget_messages()
        self.assertEqual(self.kernel.handled, [])

    def test_the_cell_is_the_current_message_again_afterwards(self):
        cell = self.kernel.parent
        self.kernel.queue_message("comm_msg")
        self.pump.handle_widget_messages()
        self.assertEqual(self.kernel.set_parent_calls, [(b"the-cell", cell, "shell")])
        self.assertIs(self.kernel.get_parent(), cell)

    def test_a_message_that_cannot_be_read_stays_queued(self):
        self.kernel.msg_queue.put_nowait((1, None, ([FakeShellFrame(b"garbage")],)))
        self.pump.handle_widget_messages()
        self.assertEqual(self.kernel.msg_queue.qsize(), 1)

    def test_a_widget_message_that_would_have_to_wait_is_an_error(self):
        import asyncio
        kernel = self.kernel
        kernel.queue_message("comm_msg")
        item = kernel.msg_queue.get_nowait()

        async def dispatch_that_waits(frames):
            await asyncio.Future()
        kernel.msg_queue.put_nowait((item[0], dispatch_that_waits, item[2]))
        with self.assertRaises(RuntimeError):
            self.pump.handle_widget_messages()

    def test_a_kernel_without_the_pieces_is_refused(self):
        with self.assertRaises(RuntimeError):
            lisp_jupyter_debug.KernelMessagePump(object())


class TestWidgetDebugRepl(LispTestCase):
    """The debug REPL made with ipywidgets: what the buttons and the text area do.
    No kernel is needed; the pump is played by a fake."""

    def setUp(self):
        super().setUp()
        try:
            import ipywidgets
        except ImportError:
            self.skipTest("ipywidgets is not installed")
        self.widgets = ipywidgets
        # Like a notebook's, this environment's display output goes to stdout.
        self.env = lisp_builtins.make_global_env(output=lambda text: print(text, end=""))
        self.run_lisp("(define (f x) (* x 2)) (define x 5)")
        # interact asks matplotlib for its backend, which a test process shouldn't
        patcher = mock.patch("ipywidgets.widgets.interaction.show_inline_matplotlib_plots")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repl = lisp_jupyter_debug.WidgetDebugRepl(self.env, "f", "resumes")
        with contextlib.redirect_stdout(io.StringIO()):         # display() prints, outside a notebook
            self.repl.show()

    def transcript(self):
        return "".join(o.get("text", "") for o in self.repl.transcript.outputs)

    def button(self, description):
        for control in self.repl.controls:
            if isinstance(control, self.widgets.Button) and control.description == description:
                return control
        self.fail("no %s button" % description)

    def text_area(self):
        return [c for c in self.repl.controls if isinstance(c, self.widgets.Textarea)][0]

    def test_it_shows_a_text_area_and_the_buttons(self):
        descriptions = sorted(c.description for c in self.repl.controls if isinstance(c, self.widgets.Button))
        self.assertEqual(descriptions, ["Abort", "Backtrace", "Continue", "Locals", "Run"])
        self.assertEqual(self.transcript(), "")                 # nothing has been run yet

    def test_typing_and_pressing_run_evaluates_in_the_stopped_scope(self):
        self.text_area().value = "(* x 3)"
        self.button("Run").click()
        self.assertEqual(self.transcript(), "f> (* x 3)\n15\n")

    def test_what_is_typed_can_change_variables_and_call_functions(self):
        self.repl.run_text("(set! x 20)")
        self.repl.run_text("(f x)")
        self.assertEqual(self.transcript(), "f> (set! x 20)\n()\nf> (f x)\n40\n")
        self.assertShows("x", "20")

    def test_what_the_lisp_displays_goes_in_the_transcript(self):
        self.repl.run_text('(display "hi") (+ 1 2)')
        self.assertEqual(self.transcript(), 'f> (display "hi") (+ 1 2)\nhi()\n3\n')

    def test_an_error_is_reported_and_stops_the_rest_of_what_was_typed(self):
        self.repl.run_text("(car 5) (+ 1 2)")
        self.assertIn("Error: car: not a pair: 5", self.transcript())
        self.assertNotIn("\n3\n", self.transcript())
        self.assertIsNone(self.repl.action)                     # and we're still stopped

    def test_a_long_result_is_cut_off(self):
        self.repl.run_text("(vector-range 5000)")
        self.assertIn("more characters]", self.transcript())
        self.assertLess(len(self.transcript()), 2200)

    def test_blank_input_does_nothing(self):
        self.repl.run_text("   \n ")
        self.assertEqual(self.transcript(), "")

    def test_typing_continue_or_exit_chooses_to_continue(self):
        self.repl.run_text("(continue)")
        self.assertEqual(self.repl.action, "continue")
        other = lisp_jupyter_debug.WidgetDebugRepl(self.env, "f", "resumes")
        other.transcript = self.widgets.Output()
        other.run_text("(exit)")
        self.assertEqual(other.action, "continue")

    def test_typing_abort_chooses_to_abort(self):
        self.repl.run_text("(+ 1 1) (abort) (+ 2 2)")
        self.assertEqual(self.repl.action, "abort")
        self.assertNotIn("4", self.transcript().split("\n"))     # the rest wasn't run

    def test_the_buttons_choose_and_the_first_choice_stands(self):
        self.button("Continue").click()
        self.button("Abort").click()
        self.assertEqual(self.repl.action, "continue")

    def test_the_locals_and_backtrace_buttons_run_those_commands(self):
        self.button("Locals").click()
        self.assertIn("f> (locals)\n", self.transcript())
        self.button("Backtrace").click()
        self.assertIn("f> (backtrace)\n", self.transcript())

    def test_wait_looks_for_widget_messages_until_a_choice_is_made(self):
        looks = []

        class Pump:
            def handle_widget_messages(pump):
                looks.append(1)
                if len(looks) == 3:
                    self.repl.choose("continue")

        with mock.patch.object(lisp_jupyter_debug, "POLL_SECONDS", 0):
            self.repl.wait(Pump())
        self.assertEqual(len(looks), 3)
        self.assertTrue(all(control.disabled for control in self.repl.controls))
        self.assertTrue(self.transcript().endswith("--- f: resuming ---\n"))

    def test_wait_raises_lispabort_when_the_choice_is_abort(self):
        class Pump:
            def handle_widget_messages(pump):
                self.repl.choose("abort")

        with mock.patch.object(lisp_jupyter_debug, "POLL_SECONDS", 0):
            with self.assertRaises(lisp_core.LispAbort):
                self.repl.wait(Pump())
        self.assertTrue(all(control.disabled for control in self.repl.controls))
        self.assertTrue(self.transcript().endswith("--- f: aborted ---\n"))

    def test_interrupt_kernel_while_waiting_aborts(self):
        class Pump:
            def handle_widget_messages(pump):
                raise KeyboardInterrupt

        with mock.patch.object(lisp_jupyter_debug, "POLL_SECONDS", 0):
            with self.assertRaises(lisp_core.LispAbort):
                self.repl.wait(Pump())

    def test_the_controls_are_switched_off_even_when_the_program_is_thrown_out(self):
        class Pump:
            def handle_widget_messages(pump):
                raise lisp_core.LispThrow("out", 1)

        with mock.patch.object(lisp_jupyter_debug, "POLL_SECONDS", 0):
            with self.assertRaises(lisp_core.LispThrow):
                self.repl.wait(Pump())
        self.assertTrue(all(control.disabled for control in self.repl.controls))

    def test_a_stop_inside_a_stop_evaluates_in_the_inner_scope(self):
        # typing (g 1) in the REPL for f stops in g, whose own REPL evaluates there
        previous = lisp_core.set_debug_repl(lambda env, label, resume: self.repl.run_text("y"))
        self.addCleanup(lisp_core.set_debug_repl, previous)
        self.run_lisp("(define (g y) (+ y 100)) (break g)")
        self.repl.run_text("(g 41)")
        self.assertIn("141", self.transcript())


class TestOpeningTheWidgetReplFromAKernel(LispTestCase):

    def test_without_ipywidgets_the_program_just_resumes_with_a_message(self):
        console = io.StringIO()
        with mock.patch("importlib.util.find_spec", return_value=None):
            with contextlib.redirect_stdout(console):
                lisp_jupyter_debug.open_widget_debug_repl(object(), self.env, "f", "resumes")
        self.assertIn("needs ipywidgets", console.getvalue())
        self.assertIn("resuming", console.getvalue())

    def test_a_kernel_that_is_not_running_just_resumes_with_a_message(self):
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            lisp_jupyter_debug.open_widget_debug_repl(object(), self.env, "f", "resumes")
        self.assertIn("can only open while a notebook cell is running", console.getvalue())


class ScriptedFrontend:
    """A stand-in for JupyterLab, for testing the debug REPL against a real kernel:
    it runs cells, watches for the widgets they show, and types and clicks in
    them the way the browser would (by sending the widgets' comm messages)."""

    class Cell:
        def __init__(self, msg_id):
            self.msg_id = msg_id
            self.streams, self.results, self.errors = [], [], []
            self.done = False
            self.finished_at = None

    def __init__(self, kernel_name):
        from jupyter_client.manager import start_new_kernel
        self.km, self.kc = start_new_kernel(kernel_name=kernel_name, startup_timeout=60)
        self.cells = {}
        self.widgets = []       # (comm id, model name, description), in the order made
        self.outputs = {}       # comm id -> the text of that Output widget

    def close(self):
        self.kc.stop_channels()
        self.km.shutdown_kernel(now=True)

    def start(self, code):
        cell = self.Cell(self.kc.execute(code))
        self.cells[cell.msg_id] = cell
        return cell

    def run(self, code, timeout=20):
        """Run a cell that doesn't stop, and wait for it."""
        cell = self.start(code)
        self.wait_for(lambda: cell.done, timeout)
        return cell

    def process(self, wait=0.2):
        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=wait)
            except Exception:
                return
            wait = 0.01
            kind, content = msg["msg_type"], msg["content"]
            cell = self.cells.get(msg["parent_header"].get("msg_id"))
            if kind == "comm_open":
                state = content["data"].get("state", {})
                self.widgets.append((content["comm_id"], state.get("_model_name"), state.get("description", "")))
            elif kind == "comm_msg":
                state = content["data"].get("state", {})
                if "outputs" in state:
                    self.outputs[content["comm_id"]] = "".join(
                        o.get("text", "") for o in state["outputs"] if o.get("output_type") == "stream")
            elif cell is not None:
                if kind == "stream":
                    cell.streams.append(content["text"])
                elif kind == "execute_result":
                    cell.results.append(content["data"]["text/plain"])
                elif kind == "error":
                    cell.errors.append("%s: %s" % (content["ename"], content["evalue"]))
                elif kind == "status" and content["execution_state"] == "idle":
                    cell.done = True
                    cell.finished_at = time.time()

    def wait_for(self, condition, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.process()
            if condition():
                return True
        return False

    def buttons(self, description):
        return [w[0] for w in self.widgets if w[1] == "ButtonModel" and w[2] == description]

    def text_area(self):
        return [w[0] for w in self.widgets if w[1] == "TextareaModel"][-1]

    def transcript(self):
        """The text in the debug REPL's transcript (the last Output widget made)."""
        ids = [w[0] for w in self.widgets if w[1] == "OutputModel"]
        return self.outputs.get(ids[-1], "") if ids else ""

    def stopped(self, how_many=1, timeout=20):
        """Wait for the debug REPL to be shown."""
        return self.wait_for(lambda: len(self.buttons("Continue")) >= how_many, timeout)

    def type_and_run(self, text):
        comm = self.kc.shell_channel
        comm.send(self.kc.session.msg("comm_msg", {"comm_id": self.text_area(), "data": {
            "method": "update", "state": {"value": text}, "buffer_paths": []}}))
        self.click(self.buttons("Run")[-1])

    def click(self, comm_id):
        self.kc.shell_channel.send(self.kc.session.msg("comm_msg", {"comm_id": comm_id, "data": {
            "method": "custom", "content": {"event": "click"}}}))

    def transcript_has(self, text, timeout=10):
        return self.wait_for(lambda: text in self.transcript(), timeout)


def start_test_kernel(tmp, name):
    """A ScriptedFrontend for a new kernel running lisp_kernel.py with no init
    file. Its kernel spec is written in the directory tmp, which is removed
    (and the test class skipped) if the kernel can't be started."""
    for module in ("ipykernel", "ipywidgets", "jupyter_client"):
        if importlib.util.find_spec(module) is None:
            shutil.rmtree(tmp, ignore_errors=True)
            raise unittest.SkipTest("%s is needed" % module)
    spec_dir = os.path.join(tmp, "kernels", name)
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "kernel.json"), "w") as f:
        json.dump({"argv": [sys.executable, os.path.join(HERE, "lisp_kernel.py"), "-f", "{connection_file}"],
                   "display_name": name, "language": "scheme",
                   "env": {"LISP_INIT_FILE": os.path.join(tmp, "no-such-init.lsp")}}, f)
    try:
        with mock.patch.dict(os.environ, {"JUPYTER_PATH": tmp}):
            return ScriptedFrontend(name)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise unittest.SkipTest("couldn't start a kernel: %s" % e)


class TestKernelReadLine(unittest.TestCase):
    """read-line in a real Jupyter kernel: the kernel asks the notebook for the
    line (an input_request), as input() does in a Python notebook."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.frontend = start_test_kernel(cls.tmp, "lisp-read-line-test")

    @classmethod
    def tearDownClass(cls):
        cls.frontend.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_read_line_asks_the_notebook_for_the_line(self):
        fe = self.frontend
        cell = fe.start('(string-append "Hello, " (read-line "Name? "))')
        request = fe.kc.get_stdin_msg(timeout=20)
        self.assertEqual(request["msg_type"], "input_request")
        self.assertEqual(request["content"]["prompt"], "Name? ")
        fe.kc.input("Kim")
        self.assertTrue(fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.errors, [])
        self.assertEqual(cell.results, ['"Hello, Kim"'])


class TestJupyterDebugger(unittest.TestCase):
    """The debug REPL in a real Jupyter kernel, with a scripted frontend: a stop
    in the middle of a cell shows widgets, the widgets work while the cell is
    still running, and the cell carries on, or is abandoned, as they say."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.frontend = start_test_kernel(cls.tmp, "lisp-debug-test")

    @classmethod
    def tearDownClass(cls):
        cls.frontend.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.fe = self.frontend
        self.fe.widgets.clear()
        self.fe.outputs.clear()
        self.fe.run("(unbreak) (break-on-error #f) (set-debug-hook! '()) "
                    "(define (f x) (* x 2)) (define (g y) (+ y 1)) (break f)")

    def tearDown(self):
        self.fe.process(0.05)
        self.fe.run("(unbreak) (break-on-error #f) (set-debug-hook! '())")

    def test_the_repl_is_shown_while_the_cell_runs_and_its_widgets_work(self):
        cell = self.fe.start("(f 5)")
        self.assertTrue(self.fe.stopped())
        self.assertFalse(cell.done)                                # the cell is still running
        self.assertEqual(cell.streams, ["--- break: entering f(5) ---\n"])
        self.fe.type_and_run("(locals)")
        self.assertTrue(self.fe.transcript_has("((x . 5))"))
        self.fe.type_and_run("(set! x 100)")
        self.assertTrue(self.fe.transcript_has("f> (set! x 100)\n()\n"))
        self.fe.click(self.fe.buttons("Continue")[-1])
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, ["200"])                    # the argument was changed at the stop
        self.assertEqual(cell.errors, [])
        self.assertEqual(self.fe.transcript(), "f> (locals)\n((x . 5))\nf> (set! x 100)\n()\n--- f: resuming ---\n")

    def test_the_abort_button_abandons_the_cell(self):
        cell = self.fe.start("(list (f 5) 'not-reached)")
        self.assertTrue(self.fe.stopped())
        self.fe.click(self.fe.buttons("Abort")[-1])
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, [])
        self.assertEqual(cell.errors, ["Aborted: the computation was abandoned by (abort)"])
        self.assertTrue(self.fe.transcript_has("--- f: aborted ---"))

    def test_typing_continue_or_abort_works_like_the_buttons(self):
        cell = self.fe.start("(f 6)")
        self.fe.stopped()
        self.fe.type_and_run("(continue)")
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, ["12"])
        self.fe.widgets.clear()
        cell = self.fe.start("(f 6)")
        self.fe.stopped()
        self.fe.type_and_run("(abort)")
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.errors, ["Aborted: the computation was abandoned by (abort)"])

    def test_output_errors_and_long_results_go_in_the_transcript(self):
        cell = self.fe.start("(f 8)")
        self.fe.stopped()
        self.fe.type_and_run('(display "hello") (car 5)')
        self.assertTrue(self.fe.transcript_has("Error: car: not a pair: 5"))
        self.assertIn("hello", self.fe.transcript())
        self.fe.type_and_run("(vector-range 5000)")
        self.assertTrue(self.fe.transcript_has("more characters]"))
        self.fe.click(self.fe.buttons("Backtrace")[-1])
        self.assertTrue(self.fe.transcript_has("(f 8)"))           # the call stack, with the stopped call in it
        self.fe.click(self.fe.buttons("Continue")[-1])
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, ["16"])

    def test_cells_queued_behind_a_paused_cell_wait_for_it(self):
        first = self.fe.start("(f 7)")
        self.fe.stopped()
        second = self.fe.start("(+ 1 2)")                          # as Run All would queue it
        self.assertFalse(self.fe.wait_for(lambda: second.done, timeout=1.5))
        self.fe.click(self.fe.buttons("Continue")[-1])
        self.assertTrue(self.fe.wait_for(lambda: first.done and second.done))
        self.assertEqual((first.results, second.results), (["14"], ["3"]))
        self.assertLessEqual(first.finished_at, second.finished_at)

    def test_a_stop_inside_a_stop(self):
        self.fe.run("(break g)")
        cell = self.fe.start("(f 9)")
        self.fe.stopped(1)
        self.fe.type_and_run("(g 41)")
        self.assertTrue(self.fe.stopped(2))                        # g's REPL, inside f's
        outer_continue, inner_continue = self.fe.buttons("Continue")[-2:]
        self.fe.click(inner_continue)
        self.assertTrue(self.fe.wait_for(lambda: "42" in "".join(self.fe.outputs.values())))
        self.assertFalse(cell.done)                                # f is still stopped
        self.fe.click(outer_continue)
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, ["18"])

    def test_break_on_error_shows_the_variables_and_continuing_lets_the_error_go_on(self):
        self.fe.run("(unbreak) (break-on-error #t)")
        cell = self.fe.start("(let ((c 2)) (car c))")
        self.assertTrue(self.fe.stopped())
        self.fe.click(self.fe.buttons("Locals")[-1])
        self.assertTrue(self.fe.transcript_has("((c . 2))"))
        self.fe.click(self.fe.buttons("Continue")[-1])
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.errors, ["LispError: car: not a pair: 2"])

    def test_interrupt_kernel_while_stopped_abandons_the_cell(self):
        cell = self.fe.start("(f 10)")
        self.fe.stopped()
        self.fe.km.interrupt_kernel()
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.errors, ["Aborted: the computation was abandoned by (abort)"])
        after = self.fe.run("(+ 20 22)")
        self.assertEqual(after.results, ["42"])                    # the kernel is fine afterwards

    def test_a_debug_hook_takes_the_place_of_the_widgets(self):
        cell = self.fe.run('(set-debug-hook! (lambda (kind name args) (display "hooked "))) (f 3)')
        self.assertEqual(cell.results, ["6"])
        self.assertIn("hooked ", "".join(cell.streams))
        self.assertEqual(self.fe.buttons("Continue"), [])

    def test_the_hook_can_still_open_the_repl_with_debug_repl(self):
        cell = self.fe.start('(set-debug-hook! (lambda (kind name args) (if (> (car args) 5) (debug-repl)))) '
                             '(list (f 1) (f 9))')
        self.assertTrue(self.fe.stopped())
        self.assertFalse(cell.done)
        self.fe.click(self.fe.buttons("Continue")[-1])
        self.assertTrue(self.fe.wait_for(lambda: cell.done))
        self.assertEqual(cell.results, ["(2 18)"])

    def test_drawing_a_chart_still_works_in_the_kernel(self):
        # the kernel sets matplotlib's backend early, for ipywidgets.interact's sake
        cell = self.fe.run('(plot-chart (list (list "squares" #(1 2 3) #(1 4 9))))')
        self.assertEqual(cell.errors, [])


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

    def test_do_execute_reports_an_abort_as_an_error_reply(self):
        import lisp_jupyter
        lisp_jupyter.get_env()
        reply = self.kernel.do_execute("(abort)", silent=False)
        self.assertEqual(reply["status"], "error")
        self.assertEqual(reply["ename"], "Aborted")

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


# ---------------------------------------------------------------------------
# 19. The example scripts (offline ones only) still run
# ---------------------------------------------------------------------------

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
    "(breakpoint)", "(breakpoint (", '(breakpoint "', "(abort", "debug-repl",
    "fred-table", "tastytrade", "schwab-", "alpha-vantage-", "sofr-", "(sec-", "(fdic-", "(census-", "(bls-", "(bea-", "(sleep", "(load ", "redirect-output", "sqlite-open", "with-sqlite", "lp-read-file",
    "save-chart", "load-csv", "write-columns-csv",
    "input", "(read-line", "exit", "load-init", "http-get", "http-clear-cache",
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
        self.addCleanup(lisp_core.debug_state.reset)        # ...and set breakpoints and hooks
        # An example that stops the program and opens the debug REPL would wait
        # for the keyboard. Make that a failure instead.
        patcher = mock.patch("builtins.input", side_effect=AssertionError(
            "a doc example opened the debug REPL"))
        patcher.start()
        self.addCleanup(patcher.stop)
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
            lisp_core.debug_state.reset()       # breakpoints belong to the whole process, not one block
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
