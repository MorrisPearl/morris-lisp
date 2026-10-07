"""Debugging: procedure names, tracing, stack traces, breakpoints, the debug hook, abort,
break-on-error, and the debug REPL in the console and in Jupyter.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


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


if __name__ == "__main__":
    unittest.main()
