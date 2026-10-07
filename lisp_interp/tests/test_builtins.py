"""The general builtins: numbers, lists, strings, regular expressions, format, hash tables,
vectors and vector math, dates, the clock, trading days, and monthly time series.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


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


if __name__ == "__main__":
    unittest.main()
