"""Test coverage: (coverage-on) notes the functions that are defined, and counts their calls; (coverage-report) says which were never called
(lisp_coverage.py, and the section "Coverage" of lisp_core.py)."""

import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class CoverageCase(LispTestCase):

    def library(self, text, name="lib_cov.lsp"):
        """A file of Lisp in a directory of its own, and its path."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def rows(self, options=""):
        """(coverage-results) as a list of (function, file, calls)."""
        columns = dict((name, v.items.tolist()) for name, v in lisp_tables.table_columns(self.run_lisp("(coverage-results %s)" % options), "test"))
        return list(zip(columns["function"], columns["file"], columns["calls"]))

    def report(self):
        self.out.clear()
        self.run_lisp("(coverage-report)")
        return "".join(self.out)


LIBRARY = """(define (used x) (helper x))
(define (helper x) (* x 2))
(define (never-called x) x)
(defstruct shape name)
(defstruct circle)
(defgeneric area (s))
(defmethod area ((s circle)) 1)
(defmethod area ((s shape)) 2)
(define (outer) (define (inner) 1) (inner))
"""


class TestWhatIsFound(CoverageCase):

    def test_the_functions_defined_after_it_is_on_are_listed_with_their_calls(self):
        path = self.library(LIBRARY)
        self.run_lisp("(define (before) 1)")                          # defined before it was on: not covered
        self.run_lisp('(coverage-on) (load "%s")' % path)
        self.run_lisp("(used 3) (used 4) (area (make-circle)) (outer) (before)")
        self.assertEqual(self.rows(), [("used", "lib_cov.lsp", 2), ("helper", "lib_cov.lsp", 2), ("never-called", "lib_cov.lsp", 0),
                                       ("area (circle)", "lib_cov.lsp", 1), ("area (shape)", "lib_cov.lsp", 0), ("outer", "lib_cov.lsp", 1)])
        self.assertEqual(self.rows(":uncalled #t"), [("never-called", "lib_cov.lsp", 0), ("area (shape)", "lib_cov.lsp", 0)])

    def test_a_function_called_by_map_apply_or_a_tail_call_is_called(self):
        self.run_lisp("(coverage-on)")
        self.run_lisp("(define (f x) x) (define (g x) (f x)) (define (h x) (g x)) (define (k x) x) (define (loop n) (if (= n 0) 0 (loop (- n 1))))")
        self.run_lisp("(map f '(1 2 3)) (h 1) (apply k '(1)) (loop 5)")
        self.assertEqual({name: calls for name, _, calls in self.rows()}, {"f": 4, "g": 1, "h": 1, "k": 1, "loop": 6})

    def test_what_is_typed_in_has_no_file_and_a_function_defined_again_counts_once_as_the_latest(self):
        self.run_lisp("(coverage-on) (define (f) 1) (f) (define (f) 2)")
        self.assertEqual(self.rows(), [("f", "(typed in)", 0)])                 # (the new one has not been called)

    def test_a_function_made_inside_another_and_a_lambda_are_left_out(self):
        self.run_lisp("(coverage-on) (define (outer) (define (inner) 1) (inner)) (outer) (define twice (lambda (x) (* 2 x))) (twice 1) (let ((a 1)) (define (in-let) a))")
        self.assertEqual([name for name, _, _ in self.rows()], ["outer"])

    def test_a_file_loaded_by_a_file_is_its_own(self):
        inner = self.library("(define (from-inner) 1)", "inner.lsp")
        outer = self.library('(define (from-outer) 1) (load "%s") (define (also-outer) 2)' % inner, "outer.lsp")
        self.run_lisp('(coverage-on) (load "%s")' % outer)
        self.assertEqual(self.rows(), [("from-outer", "outer.lsp", 0), ("also-outer", "outer.lsp", 0), ("from-inner", "inner.lsp", 0)])

    def test_it_starts_from_nothing_each_time_it_is_turned_on_and_reset_forgets(self):
        self.run_lisp("(coverage-on) (define (a) 1) (a)")
        self.run_lisp("(coverage-on) (define (b) 1)")
        self.assertEqual([name for name, _, _ in self.rows()], ["b"])
        self.run_lisp("(coverage-reset!) (define (c) 1) (c)")
        self.assertEqual(self.rows(), [("c", "(typed in)", 1)])


class TestOffAndOn(CoverageCase):

    def test_nothing_is_noted_when_it_is_off_and_what_was_found_is_kept_when_it_is_turned_off(self):
        self.run_lisp("(define (before) 1) (before)")
        self.assertEqual(self.rows(), [])
        self.assertFalse(lisp_core._profiling)                                      # (the evaluator tests one flag, which is off)
        self.run_lisp("(coverage-on)")
        self.assertTrue(lisp_core._profiling)
        self.run_lisp("(define (a) 1) (a) (coverage-off) (define (b) 1) (a)")
        self.assertFalse(lisp_core._profiling)
        self.assertEqual(self.rows(), [("a", "(typed in)", 1)])                      # (b was defined after, and a's second call not counted)

    def test_the_profiler_and_coverage_can_be_on_together_and_turning_one_off_leaves_the_other(self):
        self.run_lisp("(define (f x) x) (profile 'f) (coverage-on) (define (g x) (f x)) (g 1) (coverage-off)")
        self.assertTrue(lisp_core._profiling)                                       # (f is still profiled)
        self.run_lisp("(f 2)")
        self.assertEqual(self.run_lisp("(table-column (profile-results) \"calls\")").items.tolist(), [2])
        self.run_lisp("(unprofile)")
        self.assertFalse(lisp_core._profiling)

    def test_a_program_that_is_not_covered_runs_with_the_flag_off(self):
        self.run_lisp("(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2))))) (fib 12)")
        self.assertFalse(lisp_core._profiling)
        self.assertEqual(lisp_core.coverage_state.calls, {})


class TestTheReport(CoverageCase):

    def test_it_says_how_many_were_called_and_lists_the_others_by_file(self):
        path = self.library(LIBRARY)
        self.run_lisp('(coverage-on) (load "%s") (define (typed) 1) (used 1) (area (make-circle)) (outer)' % path)
        report = self.report()
        self.assertIn("4 of 7 functions were called (57%).", report)
        self.assertIn("lib_cov.lsp: 2 of 6 never called\n  never-called\n  area (shape)\n", report)
        self.assertIn("(typed in): 1 of 1 never called\n  typed\n", report)

    def test_a_file_whose_functions_were_all_called_is_left_out_and_nothing_defined_is_said(self):
        self.assertIn("No function has been defined since coverage-on.", self.report())
        self.run_lisp("(coverage-on) (define (a) 1) (a)")
        self.assertEqual(self.report(), "1 of 1 functions were called (100%).\n")
        self.run_lisp("(coverage-off)")
        self.assertIn("; coverage is off", self.report())


if __name__ == "__main__":
    unittest.main()
