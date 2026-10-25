"""The language itself: the reader, special forms, tail calls, keyword arguments, macros,
structs, errors, the standard macros and loop, and loading and running files.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


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
        self.assertEqual(self.run_lisp(r'"a\fb"'), "a\fb")
        self.assertEqual(self.run_lisp(r'"say \"hi\""'), 'say "hi"')
        self.assertEqual(self.run_lisp(r'"back\\slash"'), "back\\slash")
        self.assertTrue(lisp_core.is_true(self.run_lisp('(string? "x")')))

    def test_a_string_may_be_written_between_vertical_bars(self):
        self.assertEqual(self.run_lisp(r'|hello|'), "hello")
        self.assertEqual(self.run_lisp(r'|say "hi" and "bye"|'), 'say "hi" and "bye"')       # (the point: no \" everywhere)
        self.assertEqual(self.run_lisp(r'|a\nb\tc|'), "a\nb\tc")                                 # (the same escapes)
        self.assertEqual(self.run_lisp(r'|back\\slash|'), "back\\slash")
        self.assertEqual(self.run_lisp(r'|a \| bar|'), "a | bar")
        self.assertEqual(self.run_lisp(r'||'), "")
        self.assertTrue(lisp_core.is_true(self.run_lisp('(string? |x|)')))
        self.assertShows(r'(list |a "b"| "c |d")', '("a \\"b\\"" "c |d")')                 # (a bar inside a "..." string is a bar)
        self.assertShows(r'(string-length |"|)', "1")

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

    def test_rest_is_the_same_as_a_dot(self):
        self.run_lisp("(define (f a &rest r) (list a r)) (define (g a &body r) (list a r))")
        self.assertShows("(f 1 2 3)", "(1 (2 3))")
        self.assertShows("(f 1)", "(1 ())")
        self.assertShows("(g 1 2)", "(1 (2))")
        self.assertShows("((lambda (&rest r) r) 1 2)", "(1 2)")
        self.assertLispError("(f)", "expected at least 1")

    def test_a_rest_marker_needs_exactly_one_name(self):
        self.assertLispError("(define (f a &rest) a)", "&rest must be followed by one name")
        self.assertLispError("(define (f a &rest r s) a)", "&rest must be followed by one name")

    def test_optional_parameters_may_be_left_off_and_then_have_their_defaults(self):
        self.run_lisp("(define (f a &optional (b (* a 2)) c) (list a b c))")
        self.assertShows("(f 1)", "(1 2 ())")
        self.assertShows("(f 1 5)", "(1 5 ())")
        self.assertShows("(f 1 5 6)", "(1 5 6)")
        self.assertLispError("(f)", "expected at least 1 argument, got 0")
        self.assertLispError("(f 1 2 3 4)", "expected 1 to 3 arguments, got 4")

    def test_optional_parameters_can_be_followed_by_a_rest_parameter_or_by_keywords(self):
        self.run_lisp("(define (g a &optional (b 10) &rest more) (list a b more))"
                      "(define (h a &optional (b 10) . more) (list a b more))"
                      "(define (k a &optional (b 10) &key (c 3)) (list a b c))")
        self.assertShows("(g 1)", "(1 10 ())")
        self.assertShows("(g 1 2 3 4)", "(1 2 (3 4))")
        self.assertShows("(h 1 2 3)", "(1 2 (3))")
        self.assertShows("(k 1)", "(1 10 3)")
        self.assertShows("(k 1 2 :c 4)", "(1 2 4)")
        self.assertLispError("(k 1 2 :d 4)", "unknown keyword")

    def test_optional_parameters_in_a_lambda_and_a_macro(self):
        self.assertShows("((lambda (&optional (x 3)) x))", "3")
        self.assertShows("((lambda (&optional (x 3)) x) 8)", "8")
        self.run_lisp("(defmacro twice (a &optional (n 2)) `(* ,a ,n))")
        self.assertShows("(twice 5)", "10")
        self.assertShows("(twice 5 3)", "15")

    def test_the_parts_of_a_parameter_list_come_in_order(self):
        self.assertLispError("(define (f &key a &optional b) 1)", "out of place")
        self.assertLispError("(define (f &rest r &optional b) 1)", "&rest must be followed by one name")
        self.assertLispError("(define (f &optional (a 1 2)) 1)", "(name default)")

    def test_a_procedure_with_optional_parameters_is_shown_as_it_was_written(self):
        self.run_lisp("(define (f a &optional (b 2) c) a) (define (g a &optional b &rest r) a) (define (h a &optional b &key (c 1)) a)")
        for name, text in (("f", "(define (f a &optional (b 2) c)"), ("g", "(define (g a &optional b &rest r)"),
                           ("h", "(define (h a &optional b &key (c 1))")):
            self.out.clear()
            self.run_lisp("(pretty-print-function %s)" % name)
            shown = " ".join(self.printed().split()).replace("( ", "(").replace(" )", ")")
            self.assertIn(text, shown)


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


class TestDestructuringBind(LispTestCase):
    """destructuring-bind, from macros_init.lsp: a list's parts bound to the variables of a pattern."""

    def test_the_variables_take_the_list_s_shape(self):
        self.assertShows("(destructuring-bind (a b c) '(1 2 3) (list c b a))", "(3 2 1)")
        self.assertShows("(destructuring-bind ((a b) (c (d))) '((1 2) (3 (4))) (list a b c d))", "(1 2 3 4)")
        self.assertShows("(destructuring-bind (a b . more) '(1 2 3 4) (list a b more))", "(1 2 (3 4))")
        self.assertShows("(destructuring-bind (a . more) '(1) (list a more))", "(1 ())")
        self.assertShows("(destructuring-bind (a) '(1))", "()")                    # no body
        self.assertShows("(destructuring-bind (a) '(1) (define b 2) (+ a b))", "3")

    def test_optional_elements_have_defaults_that_can_use_the_variables_before_them(self):
        self.assertShows("(destructuring-bind (a &optional (b (* a 2) b-given) c) '(5) (list a b b-given c))",
                         "(5 10 #f ())")
        self.assertShows("(destructuring-bind (a &optional (b (* a 2) b-given) c) '(5 6 7) (list a b b-given c))",
                         "(5 6 #t 7)")
        self.assertShows("(destructuring-bind (&optional ((x y) '(1 2))) '() (list x y))", "(1 2)")
        self.assertShows("(destructuring-bind (&optional ((x y) '(1 2))) '((3 4)) (list x y))", "(3 4)")

    def test_rest_body_and_keys(self):
        self.assertShows("(destructuring-bind (a &rest r) '(1 2 3) (list a r))", "(1 (2 3))")
        self.assertShows("(destructuring-bind (name &body forms) '(f (x) (y)) (list name forms))", "(f ((x) (y)))")
        self.assertShows("(destructuring-bind (&key x (y 9 y-given)) '(:x 2) (list x y y-given))", "(2 9 #f)")
        self.assertShows("(destructuring-bind (&key x (y 9 y-given)) '(:y 3 :x 2) (list x y y-given))", "(2 3 #t)")
        self.assertShows("(destructuring-bind (a &rest r &key x) '(1 :x 2) (list a r x))", "(1 (:x 2) 2)")
        self.assertShows("(destructuring-bind (&key x &allow-other-keys) '(:z 1 :x 2) x)", "2")
        self.assertShows("(destructuring-bind (&key x) '(:x 1 :x 2) x)", "1")       # the first, if it's there twice
        self.assertShows("(destructuring-bind (a &aux (b (+ a 1)) c) '(1) (list a b c))", "(1 2 ())")
        self.assertShows("(destructuring-bind (&whole w a (&whole inner b)) '(1 (2)) (list w a inner b))",
                         "((1 (2)) 1 (2) 2)")

    def test_the_expression_is_evaluated_once_and_defaults_only_when_needed(self):
        self.run_lisp("(define count 0) (define (counted x) (set! count (+ count 1)) x)")
        self.assertShows("(destructuring-bind (a b) (counted '(1 2)) (list a b count))", "(1 2 1)")
        self.assertShows("(destructuring-bind (a &optional (b (counted 0))) '(1 2) (list b count))", "(2 1)")
        self.assertShows("(destructuring-bind (&key (b (counted 0))) '() (list b count))", "(0 2)")

    def test_a_list_that_doesn_t_fit(self):
        self.assertLispError("(destructuring-bind (a b c) '(1 2) a)",
                             "destructuring-bind: (1 2) doesn't fit the pattern (a b c): it has too few elements")
        self.assertLispError("(destructuring-bind (a b) '(1 2 3) a)", "(1 2 3) doesn't fit the pattern (a b): it has too many")
        self.assertLispError("(destructuring-bind (a b) 5 a)", "5 doesn't fit the pattern (a b): it isn't a list")
        self.assertLispError("(destructuring-bind (a (b c)) '(1 2) a)", "2 doesn't fit the pattern (b c): it isn't a list")
        self.assertLispError("(destructuring-bind (&key x) '(:y 1) x)", ":y isn't one of the pattern's keys")
        self.assertLispError("(destructuring-bind (&key x) '(:x) x)", "keyword arguments must be :name value pairs")
        self.assertLispError("(destructuring-bind (a &optional b) '(1 2 3) a)", "it has too many elements")

    def test_a_pattern_that_isn_t_one(self):
        self.assertLispError("(destructuring-bind (a &optional b &optional c) '(1) a)", "&optional can't be there")
        self.assertLispError("(destructuring-bind (a &key x &rest r) '(1) a)", "&rest can't be there")
        self.assertLispError("(destructuring-bind (a :b) '(1 2) a)", "a pattern's variables must be names, not :b")
        self.assertLispError("(destructuring-bind (a &rest) '(1 2) a)", "expected a variable after &rest")
        self.assertLispError("(destructuring-bind (&key 5) '() 1)", "a key's variable must be a name")

    def test_it_expands_to_a_let_star(self):
        expansion = lisp_core.to_string(self.run_lisp("(macroexpand-1 '(destructuring-bind (a b) x (+ a b)))"))
        self.assertTrue(expansion.startswith("(let* ((%list-"), expansion)
        self.assertIn("(a (destructuring--next %rest-", expansion)
        self.assertIn("(destructuring--end %rest-", expansion)


class TestLazyLoad(LispTestCase):
    """lazy-load, from macros_init.lsp, and lib/autoloads.lsp, which uses it for the libraries."""

    def write_library(self, directory, text):
        path = os.path.join(directory, "lib1.lsp")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_the_first_call_loads_the_file_and_calls_what_it_defines(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write_library(d, """
              (set! loads (+ loads 1))
              (define (twice x &key (by 2)) (* x by))
              (define (thrice x) (* 3 x))""")
            self.run_lisp("(define loads 0)")
            self.assertShows('(lazy-load "%s" twice thrice)' % path, "(twice thrice)")
            self.assertShows("loads", "0")                       # not loaded yet
            self.assertShows("(twice 5 :by 3)", "15")             # keyword arguments too
            self.assertShows("(list (thrice 5) (twice 1) loads)", "(15 2 1)")   # loaded once, for both

    def test_a_stub_called_while_another_stub_s_arguments_are_worked_out_does_not_load_the_file_again(self):
        """In (show (make)), the stub of show is looked up first, and the call of make loads the file. The stub of show
        must not load it a second time: that would make the file's structs new types, and the thing make made would not
        be one of them."""
        with tempfile.TemporaryDirectory() as d:
            path = self.write_library(d, """
              (set! loads (+ loads 1))
              (defstruct thing size)
              (define (make) (make-thing :size 3))
              (define (show t) (* 10 (thing-size t)))""")
            self.run_lisp("(define loads 0)")
            self.run_lisp('(lazy-load "%s" make show thing-size)' % path)
            self.assertShows("(show (make))", "30")
            self.assertShows("loads", "1")
            # (and a stub kept from before the load is still good, and doesn't load it either)
            self.run_lisp('(lazy-load "%s" make2 show2)' % self.write_library(d, """
              (set! loads2 (+ loads2 1))
              (define (make2) 2)
              (define (show2 x) (+ x 1))"""))
            self.run_lisp("(define loads2 0) (define kept show2)")
            self.assertShows("(list (make2) (kept 5) (kept 6) (show2 1) loads2)", "(2 6 7 2 1)")

    def test_a_stub_says_what_it_will_load(self):
        self.run_lisp('(lazy-load "solver.lsp" ridders)')
        self.run_lisp("(pretty-print-function ridders)")
        self.assertIn('"Loads solver.lsp, which defines ridders, and calls it."', self.printed())

    def test_a_file_that_doesn_t_define_the_name(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write_library(d, "(define (something-else) 1)")
            self.run_lisp('(lazy-load "%s" missing)' % path)
            self.assertLispError("(missing 1)", "lazy-load: %s didn't define missing" % path)

    def test_what_lazy_load_won_t_take(self):
        self.assertLispError('(lazy-load "solver.lsp")', "expected (lazy-load file name...), with at least one name")
        self.assertLispError('(lazy-load "solver.lsp" ridders 5)', "expected the names of functions, not 5")
        self.assertLispError('(lazy-load "solver.lsp" :ridders)', "expected the names of functions, not :ridders")

    def test_the_autoloads_name_functions_their_libraries_define(self):
        with open(os.path.join(HERE, "lib", "autoloads.lsp")) as f:
            forms = [form for form in lisp_core.parse(f.read())
                     if isinstance(form, lisp_core.Pair) and form.car == lisp_core.Symbol("lazy-load")]
        self.assertGreater(len(forms), 5)
        builtins = lisp_builtins.make_global_env(output=lambda text: None)
        seen = set()
        for form in forms:
            file, names = form.cdr.car, lisp_core.pairs_to_list(form.cdr.cdr)
            env = lisp_builtins.make_global_env(output=lambda text: None)
            lisp_core.seval(next(iter(lisp_core.parse('(load "%s")' % file))), env)
            for name in names:
                self.assertFalse(name in builtins, "%s would hide a builtin" % name)
                self.assertFalse(name in seen, "%s is in two lazy-loads" % name)
                seen.add(name)
                value = env.get(name)                   # a procedure, or a struct's accessor (a Python function)
                self.assertTrue(isinstance(value, lisp_core.Procedure) or
                                (callable(value) and not isinstance(value, lisp_core.Macro)),
                                "%s doesn't define a function %s" % (file, name))
        self.run_lisp('(load "autoloads.lsp")')
        self.assertAlmostEqual(self.run_lisp("(ridders (lambda (x) (- (* x x) 2)) 0 2)"), math.sqrt(2), places=8)


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

    def test_a_slot_declared_twice_is_an_error(self):
        self.assertLispError("(defstruct coll rate (balance 100) balance)", "the slot balance of coll is given twice")
        self.run_lisp("(defstruct animal (name 1) (legs 4))")
        self.assertLispError("(defstruct (bird (:include animal (legs 2))) (legs 3))", "the slot legs of bird is given twice")
        self.assertLispError("(defstruct (bird (:include animal (legs 2) (legs 3))))", "the slot legs of bird is given twice")
        self.run_lisp("(defstruct (spider (:include animal)) (legs 8))")           # (naming an inherited slot once is allowed)
        self.assertShows("(spider-legs (make-spider))", "8")

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

    ANIMALS = """
      (defstruct animal (name "unknown") (speak (lambda (self) (string-append (animal-name self) " makes a sound"))))
      (defstruct (dog (:include animal (speak (lambda (self) (string-append (call-super dog-speak self) ", woof"))))))
      (defstruct (puppy (:include dog (speak (lambda (self) (string-append (call-super puppy-speak self) ", yip"))))))
      (defstruct (cat (:include animal)) (speak (lambda (self) "meow")))"""

    def test_call_super_calls_the_parents_version_at_every_level_of_inheritance(self):
        self.run_lisp(self.ANIMALS)
        self.assertShows('(call-method animal-speak (make-animal :name "Rex"))', '"Rex makes a sound"')
        self.assertShows('(call-method animal-speak (make-dog :name "Rex"))', '"Rex makes a sound, woof"')
        self.assertShows('(call-method animal-speak (make-puppy :name "Rex"))', '"Rex makes a sound, woof, yip"')

    def test_call_super_goes_from_the_type_the_override_is_in_not_the_type_of_the_instance(self):
        # a puppy that does not override speak runs dog's, whose super is animal's (not dog's own again)
        self.run_lisp(self.ANIMALS + """
          (defstruct (pup (:include dog)))""")
        self.assertShows('(call-method animal-speak (make-pup :name "Bit"))', '"Bit makes a sound, woof"')

    def test_call_super_passes_the_instance_and_the_extra_arguments(self):
        self.run_lisp("""
          (defstruct acct (balance 100) (deposit (lambda (self n) (+ (acct-balance self) n))))
          (defstruct (fee-acct (:include acct (deposit (lambda (self n) (- (call-super fee-acct-deposit self n) 1))))))""")
        self.assertShows("(call-method fee-acct-deposit (make-fee-acct) 5)", "104")
        self.assertShows("(call-super fee-acct-deposit (make-fee-acct :balance 10) 5)", "15")

    def test_the_parents_version_can_be_a_named_function(self):
        self.run_lisp("""
          (define (base-speak self) "base")
          (defstruct animal (speak base-speak))
          (defstruct (dog (:include animal (speak (lambda (self) (string-append (call-super dog-speak self) "+dog"))))))""")
        self.assertShows("(call-method animal-speak (make-dog))", '"base+dog"')

    def test_a_method_given_to_one_instance_can_still_call_the_super_of_its_type(self):
        self.run_lisp(self.ANIMALS)
        self.assertShows('(call-method dog-speak (make-dog :name "Al" :speak (lambda (self) (string-append "custom, " (call-super dog-speak self)))))',
                         '"custom, Al makes a sound"')

    def test_call_super_is_given_a_struct_accessor_and_an_instance_of_its_type(self):
        self.run_lisp(self.ANIMALS)
        self.assertLispError("(call-super car (make-dog))", "expected a struct accessor")
        self.assertLispError("(call-super 5 (make-dog))", "expected a struct accessor")
        self.assertLispError("(call-super dog-speak (make-animal))", "expected an instance of dog")
        self.assertLispError("(call-super dog-speak 3)", "expected an instance of dog")

    def test_call_super_needs_a_parent_that_has_the_slot_and_a_default_for_it(self):
        self.run_lisp(self.ANIMALS + """
          (defstruct (fish (:include animal)) fins)
          (defstruct bare speak)
          (defstruct (shy (:include bare (speak (lambda (self) 1)))))""")
        self.assertLispError('(call-super animal-speak (make-animal))', "animal has no parent type")
        self.assertLispError("(call-super fish-fins (make-fish))", "has no slot fins")
        self.assertLispError("(call-super shy-speak (make-shy))", "no default for speak")

    def test_a_parent_default_that_needs_another_slot_cannot_be_called_as_a_super_method(self):
        self.run_lisp("""
          (defstruct thing (n 1) (f (if (> n 3) (lambda (self) "big") (lambda (self) "small"))))
          (defstruct (sub (:include thing (f (lambda (self) (call-super sub-f self))))))""")
        self.assertShows("(call-method thing-f (make-thing :n 5))", '"big"')
        self.assertShows("(call-method thing-f (make-thing))", '"small"')
        self.assertLispError("(call-method thing-f (make-sub))", "couldn't get thing's default for f")


class TestGenericFunctions(LispTestCase):
    """defgeneric and defmethod: a function whose method is chosen by the type of its first argument, as Common Lisp's generic
    functions are (with the one argument that chooses, and the struct types of defstruct to choose among)."""

    SHAPES = """
      (defstruct shape (name "shape"))
      (defstruct (circle (:include shape)) (r 1))
      (defstruct (unit-circle (:include circle)))
      (defstruct (square (:include shape)) (side 1))
      (defmethod area ((s circle)) (* 3 (circle-r s) (circle-r s)))
      (defmethod area ((s square)) (* (square-side s) (square-side s)))"""

    def setUp(self):
        super().setUp()
        self.run_lisp(self.SHAPES)

    def test_the_method_is_chosen_by_the_type_of_the_first_argument(self):
        self.assertShows("(area (make-circle :r 2))", "12")
        self.assertShows("(area (make-square :side 5))", "25")
        self.assertShows("(map area (list (make-circle) (make-square :side 2)))", "(3 4)")

    def test_a_type_that_includes_another_has_its_methods_unless_it_has_its_own(self):
        self.assertShows("(area (make-unit-circle :r 2))", "12")
        self.run_lisp("(defmethod area ((s unit-circle)) 99)")
        self.assertShows("(area (make-unit-circle))", "99")
        self.assertShows("(area (make-circle))", "3")

    def test_a_method_for_t_or_for_no_type_is_for_any_other_argument(self):
        self.run_lisp('(defmethod describe-it (x) "something") (defmethod describe-it ((s shape)) "a shape")'
                      '(defmethod describe-it ((x t)) "something else")')
        self.assertShows("(describe-it 5)", '"something else"')
        self.assertShows("(describe-it (make-square))", '"a shape"')
        self.assertShows("(describe-it (list 1 2))", '"something else"')

    def test_call_next_method_calls_the_method_of_the_type_this_one_extends(self):
        self.run_lisp("""
          (defmethod label ((s shape)) (string-append "shape " (shape-name s)))
          (defmethod label ((s circle)) (string-append "circle, " (call-next-method)))
          (defmethod label ((s unit-circle)) (string-append "unit " (call-next-method)))""")
        self.assertShows('(label (make-unit-circle :name "u"))', '"unit circle, shape u"')
        self.assertShows('(label (make-circle :name "c"))', '"circle, shape c"')
        self.assertShows('(label (make-square :name "q"))', '"shape q"')

    def test_call_next_method_may_be_given_other_arguments_and_the_method_may_have_options(self):
        self.run_lisp("""
          (defmethod scaled ((s shape) k &optional (plus 0)) (+ (* k 10) plus))
          (defmethod scaled ((s circle) k &optional (plus 0)) (call-next-method s (+ k 1) (+ plus 100)))
          (defmethod keyed ((s shape) &key (a 1) (b 2)) (list a b))
          (defmethod gathered ((s shape) &rest more) more)""")
        self.assertShows("(scaled (make-circle) 1)", "120")
        self.assertShows("(scaled (make-square) 1 5)", "15")
        self.assertShows("(keyed (make-square) :b 7)", "(1 7)")
        self.assertShows("(gathered (make-square) 1 2 3)", "(1 2 3)")

    def test_next_method_p_says_whether_there_is_one(self):
        self.run_lisp("""
          (defmethod chain ((s shape)) (next-method-p))
          (defmethod chain ((s circle)) (list (next-method-p) (call-next-method)))""")
        self.assertShows("(chain (make-circle))", "(#t #f)")

    def test_call_next_method_from_inside_a_lambda_in_the_method(self):
        self.run_lisp("""
          (defmethod total ((s shape)) 1)
          (defmethod total ((s circle)) (apply + (map (lambda (k) (+ k (call-next-method))) '(10 20))))""")
        self.assertShows("(total (make-circle))", "32")

    def test_without_a_next_method_call_next_method_is_an_error(self):
        self.assertLispError("(begin (defmethod only ((s shape)) (call-next-method)) (only (make-square)))",
                             "there is no next method for only")

    def test_a_method_in_tail_position_runs_in_constant_stack_space(self):
        self.run_lisp("(defmethod count-down ((s shape) n) (if (= n 0) 'done (count-down s (- n 1))))")
        self.assertShows("(count-down (make-square) 100000)", "done")

    def test_an_error_in_a_method_shows_the_generic_functions_name_in_the_trace(self):
        self.run_lisp("(defmethod broken ((s shape)) (error \"bad\"))")
        with self.assertRaises(lisp_core.LispError) as raised:
            self.run_lisp("(broken (make-square))")
        self.assertIn("broken", lisp_core.format_lisp_traceback(raised.exception))

    def test_a_method_defined_again_replaces_the_old_one(self):
        self.run_lisp("(defmethod area ((s square)) 0)")
        self.assertShows("(area (make-square :side 9))", "0")
        self.assertShows("(generic-function-methods area)", "(circle square)")

    def test_a_struct_defined_again_keeps_its_methods(self):
        self.run_lisp("(defstruct (circle (:include shape)) (r 1) (extra 0))")
        self.assertShows("(area (make-circle :r 3))", "27")

    def test_the_generic_function_is_a_value(self):
        self.assertShows("(generic-function? area)", "#t")
        self.assertShows("(generic-function? car)", "#f")
        self.assertShows("(procedure? area)", "#t")
        self.assertShows("(generic-function-methods area)", "(circle square)")
        self.assertShows("area", "#<generic-function area>")
        self.run_lisp("(defmethod anything ((x t)) 1) (defmethod anything ((s square)) 2)")
        self.assertShows("(generic-function-methods anything)", "(t square)")

    def test_defgeneric_makes_the_function_and_keeps_its_methods_when_it_is_evaluated_again(self):
        self.run_lisp("(defgeneric area (shape)) (defgeneric perimeter (shape))")
        self.assertShows("(area (make-square :side 2))", "4")                    # (still there)
        self.assertShows("(generic-function-methods perimeter)", "()")
        self.assertLispError("(perimeter (make-square))", "there is no method for a square (it has methods for nothing yet)")

    def test_defgeneric_replaces_a_function_that_is_not_generic_but_defmethod_will_not(self):
        self.run_lisp("(define (stand-in x) 'stand-in)")
        self.assertLispError("(defmethod stand-in ((s square)) 1)", "already a function that is not generic")
        self.run_lisp("(defgeneric stand-in (x)) (defmethod stand-in ((s square)) 1)")
        self.assertShows("(stand-in (make-square))", "1")

    def test_what_a_generic_function_wont_take(self):
        self.assertLispError("(area)", "called with at least one argument")
        self.assertLispError("(area 5)", "area: there is no method for 5 (it has methods for circle, square)")
        self.assertLispError("(area (make-shape))", "there is no method for a shape")
        self.assertLispError("(defmethod area ((s nonsense)) 1)", "nonsense is not a struct type")
        self.assertLispError("(defmethod area ((s 5)) 1)", "5 is not a struct type")
        self.assertLispError("(defmethod area ((s circle extra)) 1)", "the first parameter is (name type)")
        self.assertLispError("(defmethod area)", "expected (defmethod name")
        self.assertLispError("(defmethod area x 1)", "expected (defmethod name")
        self.assertLispError("(defgeneric)", "expected (defgeneric name")
        self.assertLispError("(generic-function-methods 5)", "expected a generic function")
        self.assertLispError("(area (make-circle) 5)", "expected 1 argument")           # (the method's own parameters)


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

    def test_catch_error_only_catches_the_kinds_of_error_it_names(self):
        self.assertShows("(catch-error (error :kind 'network \"site down\") (m) :only (network) (list 'caught m))", '(caught "site down")')
        self.assertShows("(catch-error (error :kind 'network \"site down\") (m) :only network m)", '"site down"')     # one kind, not in a list
        self.assertShows("(catch-error (error :kind 'late \"x\") (m) :only (network late) 'either)", "either")
        self.assertShows("(catch-error (+ 1 2) (m) :only (network) 'not-run)", "3")

    def test_an_error_of_another_kind_or_of_none_passes_on(self):
        self.assertLispError("(catch-error (car 5) (m) :only (network) 'caught)", "car: not a pair: 5")
        self.assertLispError("(catch-error (error :kind 'other \"x\") (m) :only (network) 'caught)", "x")
        self.assertLispError("(catch-error (sqrt \"x\") (m) :only (network) 'caught)", "sqrt")                # (a builtin's Python error)
        self.assertShows("(catch-error (catch-error (car 5) (m) :only (network) 'inner) (m) (list 'outer m))", '(outer "car: not a pair: 5")')
        self.assertShows("(catch-error (error :kind 'network \"x\") (m) 'caught)", "caught")              # (without :only, every error)

    def test_the_kinds_and_the_error_s_kind_are_checked(self):
        self.assertLispError("(catch-error 1 (m) :only)", "catch-error: :only is followed by the kinds of error to catch")
        self.assertLispError("(catch-error 1 (m) :only (5) 'x)", "a kind of error, such as network, or a list of them, not (5)")
        self.assertLispError("(catch-error 1 (m) :only :network 'x)", "a kind of error")
        self.assertLispError("(error :kind)", "error: :kind is followed by the kind of error, a symbol")
        self.assertLispError('(error :kind "network" "x")', "error: :kind is followed by the kind of error, a symbol")

    def test_the_kind_is_kept_on_the_error(self):
        with self.assertRaises(lisp_core.LispError) as raised:
            self.run_lisp("(error :kind 'network \"site down\" 42)")
        self.assertEqual((str(raised.exception), raised.exception.kind), ("site down 42", "network"))
        with self.assertRaises(lisp_core.LispError) as raised:
            self.run_lisp('(error "plain")')
        self.assertIsNone(raised.exception.kind)

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

    def test_named_let_is_a_loop_or_a_recursion(self):
        self.assertShows("(let count ((i 0) (total 0)) (if (< i 5) (count (+ i 1) (+ total i)) total))", "10")
        self.assertShows("(let fact ((n 5)) (if (= n 0) 1 (* n (fact (- n 1)))))", "120")
        self.assertShows("(let go () 3)", "3")                                      # no variables
        self.assertShows("(let loop ((i 0)) (if (< i 100000) (loop (+ i 1)) i))", "100000")   # a tail call doesn't grow the stack
        self.assertShows("(let loop ((i 0) (seen '())) (if (< i 3) (loop (+ i 1) (cons i seen)) (reverse seen)))", "(0 1 2)")
        # the values are evaluated outside the loop, where its name isn't yet anything
        self.run_lisp("(define loop-count 7)")
        self.assertShows("(let loop-count ((n loop-count) (acc '())) (if (> n 0) (loop-count (- n 1) (cons n acc)) acc))",
                         "(1 2 3 4 5 6 7)")
        self.assertShows("(let loop ((i 0)) (if (< i 3) (loop (+ i 1)) (let loop ((j 10)) (+ j i))))", "13")
        self.assertShows("(let ((x 1) (y 2)) (+ x y))", "3")                       # an ordinary let is as it was
        self.assertLispError("(let 5 ((i 0)) i)", "let: expected a list of bindings")

    def test_a_badly_formed_let(self):
        self.assertLispError("(let ((x)) x)", "let: each binding must be (name value), not (x)")
        self.assertLispError("(let loop 5 i)", "let: expected a list of bindings")
        self.assertLispError("(let loop ((i)) i)", "let: each binding must be (name value), not (i)")
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


class TestMetaprogrammingAndIO(LispTestCase):

    def test_eval_runs_constructed_code_in_the_global_environment(self):
        self.assertShows("(eval (list '+ 1 2 (list '* 3 4)))", "15")

    def test_eval_cannot_see_local_variables(self):
        self.assertLispError("(let ((local 5)) (eval 'local))", "unbound symbol")

    def test_read_from_string_reads_the_text_as_data_and_eval_runs_it(self):
        self.assertShows('(read-from-string "(+ 1 2)")', "(+ 1 2)")
        self.assertShows('(eval (read-from-string "(+ 1 2)"))', "3")
        self.assertShows('(read-from-string "  \'(a #(1 2) \\"s\\") ; a comment")', '(quote (a #(1 2) "s"))')
        self.assertShows('(car (read-from-string "(define (f x) x)"))', "define")
        self.assertShows('(read-from-string "(1 2 3)")', "(1 2 3)")

    def test_read_from_string_reads_one_expression_and_says_what_is_wrong(self):
        self.assertLispError('(read-from-string "1 2")', "the text has 2 expressions, and it reads one")
        self.assertLispError('(read-from-string "")', "the text has 0 expressions")
        self.assertLispError('(read-from-string "(1 2")', "read-from-string: missing ')'")
        self.assertLispError("(read-from-string 5)", "expected a string, not 5")

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

    def test_require_loads_a_file_the_first_time_and_load_always_loads_it(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "counted.lsp")
            with open(path, "w") as f:
                f.write('(set! loads (+ loads 1))\n')
            self.run_lisp("(define loads 0)")
            self.assertShows('(require "%s")' % path, "()")
            self.run_lisp('(require "%s") (require "%s")' % (path, path))
            self.assertShows("loads", "1")
            self.run_lisp('(load "%s")' % path)                        # (load is asked to, so it does)
            self.assertShows("loads", "2")
            self.run_lisp('(require "%s")' % path)
            self.assertShows("loads", "2")

    def test_require_does_not_load_what_load_has_loaded_or_a_lazy_load_has(self):
        """Loading a library again makes its structs new types, and what was made of the old ones is not one of them."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "thing.lsp")
            with open(path, "w") as f:
                f.write("(defstruct thing size) (define (make) (make-thing :size 3))\n")
            self.run_lisp('(lazy-load "%s" make thing-size)' % path)
            self.run_lisp("(define t (make))")                         # (loads the file)
            self.run_lisp('(require "%s")' % path)                     # (a library that needs it)
            self.assertShows("(thing-size t)", "3")
            self.assertShows("(thing? t)", "#t")
            self.run_lisp('(load "%s")' % path)                        # (while load does make them new)
            self.assertLispError("(thing-size t)", "thing")

    def test_each_environment_has_its_own_files_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "one.lsp")
            with open(path, "w") as f:
                f.write("(define one 1)\n")
            self.run_lisp('(require "%s")' % path)
            other = lisp_builtins.make_global_env(output=lambda text: None)
            self.run_lisp('(require "%s")' % path, env=other)
            self.assertShows("one", "1")
            self.assertEqual(self.run_lisp("one", env=other), 1)

    def test_require_of_a_missing_file_is_an_error(self):
        self.assertLispError('(require "/definitely/not/here.lsp")', "there's no file")
        self.assertLispError('(require "definitely_not_here.lsp")', "can't find definitely_not_here.lsp")

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

    def test_a_short_list_of_atoms_is_printed_on_one_line(self):
        self.run_lisp("(pretty-print '(a (b c) (d (e f) g)))")
        self.assertEqual(self.printed(), "(a\n (b c)\n (d\n  (e f)\n  g\n )\n)\n")      # (b c) and (e f): no sublists
        self.out.clear()
        self.run_lisp("(pretty-print '(1 2 3 4 5 6 7 8))")                                  # 8 atoms: the limit
        self.run_lisp("(pretty-print '(a . b))")
        self.run_lisp("(pretty-print #(1 2 3))")
        self.run_lisp("(pretty-print '())")
        self.assertEqual(self.printed(), "(1 2 3 4 5 6 7 8)\n(a . b)\n#(1 2 3)\n()\n")
        self.out.clear()
        self.run_lisp("(pretty-print '(1 2 3 4 5 6 7 8 9))")                                # one more: spread out
        self.assertEqual(self.printed(), "(1\n 2\n 3\n 4\n 5\n 6\n 7\n 8\n 9\n)\n")
        self.out.clear()
        self.run_lisp("(pretty-print '(a #(1 2) b))")                                       # a vector is a sublist
        self.assertEqual(self.printed(), "(a\n #(1 2)\n b\n)\n")
        self.assertEqual(lisp_core.PRETTY_PRINT_ONE_LINE_LIMIT, 8)

    def test_the_other_pretty_printers_do_the_same(self):
        self.run_lisp("(define (square n) (* n n)) (pretty-print-function square)")
        self.assertEqual(self.printed(), "(define\n (square n)\n (* n n)\n)\n")
        self.out.clear()
        self.run_lisp("(defmacro twice (x) `(begin ,x ,x)) (pretty-print-macro twice)")
        self.assertEqual(self.printed(), "(defmacro\n twice\n (x)\n (quasiquote\n  (begin\n   (unquote x)\n   (unquote x)\n  )\n )\n)\n")
        self.out.clear()
        self.run_lisp("(print-macroexpansion '(unless done (display 1)))")
        self.assertIn("(display 1)", self.printed())

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

    def test_load_variables_looks_for_a_file_where_load_does(self):
        saved = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, saved, ignore_errors=True)
        cwd = os.getcwd()
        os.chdir(saved)
        try:
            self.run_lisp('(define kept #(1 2 3)) (save-variables "kept.json" kept)')
        finally:
            os.chdir(cwd)
        self.run_lisp("(define kept '())")
        with mock.patch.dict(os.environ, {"LISP_PATH": saved}):
            self.assertShows('(load-variables "kept.json")', "(kept)")                # (not in the current directory: in LISP_PATH)
        self.assertShows("kept", "#(1 2 3)")
        with mock.patch.dict(os.environ, {"LISP_PATH": ""}):
            self.assertLispError('(load-variables "kept.json")', "couldn't read kept.json")

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


if __name__ == "__main__":
    unittest.main()
