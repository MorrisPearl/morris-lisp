"""Profiling: (profile 'f) counts and times the calls of a function, whether you defined it or it comes with
the interpreter, and (profile-results) says what it found."""

import time

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class ProfilingTestCase(LispTestCase):

    def entry(self, name):
        """The numbers for a function, from the profiler itself: (calls, total, own) in full precision."""
        found = [e for e in lisp_core.profile_state.entries() if e.name == name]
        self.assertEqual(len(found), 1, "no single entry for %s in %s" % (name, [e.name for e in lisp_core.profile_state.entries()]))
        return found[0].calls, found[0].total, found[0].own

    def results(self):
        """(profile-results) as a dict: function name -> row (a dict of the other columns)."""
        columns = dict((name, v.items.tolist()) for name, v in
                       lisp_tables.table_columns(self.run_lisp("(profile-results)"), "test"))
        return {name: {key: columns[key][i] for key in columns} for i, name in enumerate(columns["function"])}


class TestCounting(ProfilingTestCase):

    def test_calls_are_counted(self):
        self.run_lisp("(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))")
        self.assertShows("(profile 'fib)", "(fib)")
        self.assertShows("(fib 10)", "55")
        self.assertEqual(self.entry("fib")[0], 177)
        self.run_lisp("(fib 5)")
        self.assertEqual(self.entry("fib")[0], 177 + 15)               # counts go on adding

    def test_a_function_can_be_given_as_its_name_or_the_procedure_itself(self):
        self.run_lisp("(define (f x) x)")
        self.run_lisp("(profile f)")
        self.run_lisp("(f 1) (f 2)")
        self.run_lisp('(profile "f")')                                  # the same function: no second entry
        self.run_lisp("(f 3)")
        self.assertEqual(self.entry("f")[0], 3)

    def test_a_function_is_found_by_its_name_wherever_it_is_and_however_often_it_is_defined(self):
        self.run_lisp("(profile 'helper)")
        self.assertIn("no function named helper is defined yet", "".join(self.out))
        self.run_lisp("(define (outer n) (define (helper x) (* x 2)) (helper n))")             # a local function
        self.run_lisp("(outer 1) (outer 2)")
        self.run_lisp("(define (helper x) x)")                                                  # and a global one
        self.run_lisp("(helper 5)")
        self.assertEqual(self.entry("helper")[0], 3)

    def test_counting_alone_is_cheaper_and_has_no_times(self):
        self.run_lisp("(define (f x) (* x 2))")
        self.run_lisp("(profile 'f :time #f)")
        self.run_lisp("(f 1) (f 2) (f 3)")
        row = self.results()["f"]
        self.assertEqual(row["calls"], 3)
        for column in ("total_s", "self_s", "ms_per_call"):
            self.assertTrue(row[column] != row[column], column)         # missing: nan

    def test_calls_made_by_map_filter_and_apply_are_counted_too(self):
        self.run_lisp("(define (double x) (* 2 x))")
        self.run_lisp("(define (small? x) (< x 3))")
        self.run_lisp("(profile 'double 'small?)")
        self.run_lisp("(map double '(1 2 3 4)) (apply double '(5)) (filter small? '(1 2 3 4 5))")
        self.assertEqual(self.entry("double")[0], 5)
        self.assertEqual(self.entry("small?")[0], 5)

    def test_a_built_in_function_is_counted(self):
        self.run_lisp("(profile 'vector-add 'sqrt)")
        self.run_lisp("(vector-add #(1 2) #(3 4)) (vector-add #(1) #(1)) (sqrt 4)")
        self.assertEqual(self.entry("vector-add")[0], 2)
        self.assertEqual(self.entry("sqrt")[0], 1)
        self.run_lisp("(profile 'sqrt)")                                 # again: nothing changes
        self.run_lisp("(sqrt 9)")
        self.assertEqual(self.entry("sqrt")[0], 2)

    def test_a_tail_call_is_counted_and_a_loop_does_not_use_more_of_the_stack(self):
        sizes = {}
        self.env[lisp_core.Symbol("stack-size")] = lambda: len(lisp_core._active_stacks[-1])
        self.run_lisp("(define (spin n) (if (= n 0) (stack-size) (spin (- n 1))))")
        self.run_lisp("(profile 'spin)")
        sizes[10] = self.run_lisp("(spin 10)")
        sizes[20000] = self.run_lisp("(spin 20000)")
        self.assertEqual(sizes[10], sizes[20000])
        self.assertEqual(self.entry("spin")[0], 11 + 20001)
        self.run_lisp("(profile 'spin :time #f)")                        # counting alone adds no frames either
        self.assertEqual(self.run_lisp("(spin 20000)"), self.run_lisp("(spin 5)"))

    def test_unprofile_stops_counting_one_function_or_all(self):
        self.run_lisp("(define (f) 1) (define (g) 2) (profile 'f 'g) (f) (g)")
        self.run_lisp("(unprofile 'f)")
        self.run_lisp("(f) (g)")
        self.assertEqual(self.entry("g")[0], 2)
        self.assertEqual([e.name for e in lisp_core.profile_state.entries()], ["g"])
        self.run_lisp("(unprofile)")
        self.assertEqual(lisp_core.profile_state.entries(), [])
        self.assertFalse(lisp_core._profiling)
        self.run_lisp("(f) (g)")                                         # nothing to count, and nothing goes wrong

    def test_profile_reset_sets_the_counts_and_times_to_zero_and_goes_on(self):
        self.run_lisp("(define (f) 1) (profile 'f) (f) (f)")
        self.run_lisp("(profile-reset!)")
        self.assertEqual(self.entry("f"), (0, 0.0, 0.0))
        self.run_lisp("(f)")
        self.assertEqual(self.entry("f")[0], 1)

    def test_a_call_that_ends_in_an_error_is_counted_and_what_follows_is_still_right(self):
        self.run_lisp("(define (risky n) (if (= n 0) (error \"boom\") n))")
        self.run_lisp("(define (careful n) (catch-error (risky n) (message) 'caught))")
        self.run_lisp("(profile 'risky 'careful)")
        for _ in range(3):
            self.assertShows("(careful 0)", "caught")
        self.assertShows("(careful 5)", "5")
        self.assertEqual(self.entry("risky")[0], 4)
        self.assertEqual(self.entry("careful")[0], 4)
        calls, total, own = self.entry("careful")
        self.assertGreaterEqual(own, 0.0)
        self.assertLessEqual(own, total + 1e-9)

    def test_things_that_cannot_be_profiled_say_so(self):
        for source, fragment in [
                ("(profile)", "expected at least one function"),
                ("(profile 5)", "expected a function or its name"),
                ("(profile '(1 2))", "expected a function or its name"),
                ("(profile 'when)", "is a macro"),
                ("(profile (lambda (x) x))", "has no name"),
                ("(profile 'car :speed 3)", "isn't an option"),
                ("(profile 'car :time)", ":name value pairs"),
                ("(unprofile 5)", "expected a function or its name"),
        ]:
            with self.subTest(source=source):
                self.assertLispError(source, fragment)


class TestTiming(ProfilingTestCase):

    def burn(self, seconds=0):
        """Gives the Lisp program (pause seconds), to make a function take a known time."""
        self.env[lisp_core.Symbol("pause")] = lambda s: time.sleep(s) or lisp_core.NIL

    def test_the_time_of_a_function_is_the_time_in_its_calls(self):
        self.burn()
        self.run_lisp("(define (slow) (pause 0.02) 1)")
        self.run_lisp("(profile 'slow)")
        self.run_lisp("(slow) (slow) (slow)")
        calls, total, own = self.entry("slow")
        self.assertEqual(calls, 3)
        self.assertGreater(total, 0.058)
        self.assertLess(total, 0.5)
        self.assertAlmostEqual(own, total, delta=1e-9)                  # it calls no other function being profiled

    def test_a_functions_own_time_leaves_out_the_profiled_functions_it_calls(self):
        self.burn()
        self.run_lisp("(define (inner) (pause 0.03) 1)")
        self.run_lisp("(define (outer) (pause 0.01) (+ (inner) (inner)))")
        self.run_lisp("(profile 'outer 'inner)")
        self.run_lisp("(outer)")
        _, outer_total, outer_own = self.entry("outer")
        _, inner_total, inner_own = self.entry("inner")
        self.assertGreater(inner_total, 0.058)
        self.assertGreater(outer_total, inner_total + 0.009)
        self.assertAlmostEqual(outer_own, outer_total - inner_total, delta=1e-9)
        self.assertAlmostEqual(inner_own, inner_total, delta=1e-9)
        self.assertLess(outer_own, 0.03)

    def test_a_function_that_is_not_profiled_is_part_of_its_callers_own_time(self):
        self.burn()
        self.run_lisp("(define (hidden) (pause 0.03) 1)")
        self.run_lisp("(define (visible) (hidden))")
        self.run_lisp("(profile 'visible)")
        self.run_lisp("(visible)")
        calls, total, own = self.entry("visible")
        self.assertGreater(own, 0.029)

    def test_a_recursive_function_counts_each_call_but_its_time_only_once(self):
        self.run_lisp("(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))")
        self.run_lisp("(profile 'fib)")
        start = time.perf_counter()
        self.run_lisp("(fib 14)")
        wall = time.perf_counter() - start
        calls, total, own = self.entry("fib")
        self.assertEqual(calls, 1219)
        self.assertLessEqual(total, wall)                               # not the sum over 1219 nested calls
        self.assertGreater(total, 0.5 * wall)
        self.assertAlmostEqual(own, total, delta=1e-6)                  # all its own time, once the inner calls are taken out

    def test_the_time_of_a_built_in_function_includes_the_functions_it_calls(self):
        self.burn()
        self.run_lisp("(define (slow x) (pause 0.02) x)")
        self.run_lisp("(profile 'map 'slow)")
        self.run_lisp("(map slow '(1 2 3))")
        _, map_total, map_own = self.entry("map")
        _, slow_total, slow_own = self.entry("slow")
        self.assertGreater(slow_total, 0.058)
        self.assertGreaterEqual(map_total, slow_total)
        self.assertAlmostEqual(map_own, map_total - slow_total, delta=1e-9)
        self.assertLess(map_own, 0.05)

    def test_a_loop_that_calls_itself_in_tail_position_is_timed_as_one_call_in_progress(self):
        self.burn()
        self.run_lisp("(define (loop n) (if (= n 0) 'done (begin (pause 0.002) (loop (- n 1)))))")
        self.run_lisp("(profile 'loop)")
        self.run_lisp("(loop 10)")
        calls, total, own = self.entry("loop")
        self.assertEqual(calls, 11)
        self.assertGreater(total, 0.019)

    def test_times_are_there_after_an_error_has_cut_calls_short(self):
        self.burn()
        self.run_lisp("(define (fails) (pause 0.01) (error \"no\"))")
        self.run_lisp("(define (steady) (pause 0.02) 1)")
        self.run_lisp("(profile 'fails 'steady)")
        self.run_lisp("(catch-error (fails) (m) 'x)")
        self.run_lisp("(steady)")
        _, total, own = self.entry("steady")
        self.assertGreater(total, 0.019)
        self.assertAlmostEqual(own, total, delta=1e-9)


class TestResults(ProfilingTestCase):

    def test_the_results_are_a_table_sorted_by_own_time(self):
        self.env[lisp_core.Symbol("pause")] = lambda s: time.sleep(s) or lisp_core.NIL
        self.run_lisp("(define (quick) 1) (define (slow) (pause 0.02) 1) (define (middling) (pause 0.005) (quick))")
        self.run_lisp("(profile 'quick 'slow 'middling)")
        self.run_lisp("(quick) (slow) (middling) (middling)")
        columns = dict((n, v.items.tolist()) for n, v in
                       lisp_tables.table_columns(self.run_lisp("(profile-results)"), "test"))
        self.assertEqual(list(columns), ["function", "calls", "total_s", "self_s", "ms_per_call"])
        self.assertEqual(columns["function"], ["slow", "middling", "quick"])
        self.assertEqual(columns["calls"], [1, 2, 3])                   # quick: once by itself, and once in each middling
        self.assertAlmostEqual(columns["total_s"][0], 0.02, delta=0.02)
        self.assertAlmostEqual(columns["ms_per_call"][1], 5.0, delta=4.0)

    def test_the_results_can_be_sorted_another_way(self):
        self.run_lisp("(define (a) 1) (define (b) (a) (a)) (profile 'a 'b) (b)")
        for key, expected in [("calls", ["a", "b"]), ("name", ["a", "b"]), ("total", ["b", "a"]), ("self", None)]:
            with self.subTest(sort=key):
                names = lisp_tables.table_columns(self.run_lisp("(profile-results :sort '%s)" % key), "test")[0][1].items.tolist()
                if expected:
                    self.assertEqual(names, expected)
                self.assertEqual(sorted(names), ["a", "b"])
        self.assertLispError("(profile-results :sort 'speed)", "one of self, total, calls, name")

    def test_the_results_are_an_ordinary_table(self):
        self.run_lisp("(define (f) 1) (profile 'f) (f) (f) (f)")
        self.assertShows('(table-column (profile-results) "calls")', "#(3)")
        self.assertShows('(table-column (table-where (profile-results) "function" "f") "calls")', "#(3)")

    def test_show_profile_prints_the_table(self):
        self.run_lisp("(define (f) 1) (profile 'f) (f)")
        self.run_lisp("(show-profile)")
        printed = "".join(self.out)
        for expected in ["function", "calls", "total_s", "self_s", "ms_per_call", "f"]:
            self.assertIn(expected, printed)

    def test_no_function_profiled_gives_an_empty_table(self):
        self.assertShows('(table-row-count (profile-results))', "0")
