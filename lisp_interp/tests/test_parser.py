"""lib/parser.lsp, the framework for parsers of small languages: reading the tokens, each kind of item a rule
can have, trying alternatives and remembering what a rule found, the error messages, and the checks of a
grammar. Two grammars are compared with Python's own parsing: arithmetic with eval, and JSON with json."""

import json
import random

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class ParserTestCase(LispTestCase):
    """Every test starts with the library loaded."""

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "parser.lsp")')

    def parses(self, grammar, text, expected, start=None):
        source = '(grammar-parse %s "%s"%s)' % (grammar, text.replace("\\", "\\\\").replace('"', '\\"'),
                                                 " :start '%s" % start if start else "")
        self.assertEqual(self.show(source), expected, msg="text: %s" % text)

    def fails(self, grammar, text, fragment, start=None):
        source = '(grammar-parse %s "%s"%s)' % (grammar, text.replace("\\", "\\\\").replace('"', '\\"'),
                                                 " :start '%s" % start if start else "")
        self.assertLispError(source, fragment)


class TestTokens(ParserTestCase):

    def define(self, rows):
        self.run_lisp("(define-grammar g %s (rule start (end)))" % rows)

    def test_the_text_is_cut_into_tokens_and_the_skipped_ones_are_dropped(self):
        self.define('(token skip "\\\\s+") (token number "\\\\d+") (token word "[a-z]+") (token symbol "[-+()]")')
        self.assertShows('(grammar-tokens g "ab 12 + (cd)-3")',
                         '((word "ab") (number "12") (symbol "+") (symbol "(") (word "cd") (symbol ")") (symbol "-") (number "3"))')
        self.assertShows('(grammar-tokens g "")', "()")
        self.assertShows('(grammar-tokens g "   ")', "()")

    def test_a_character_no_row_matches_is_a_token_of_kind_unknown(self):
        self.define('(token skip "\\\\s+") (token word "[a-z]+")')
        self.assertShows('(grammar-tokens g "ab $ cd#")', '((word "ab") (unknown "$") (word "cd") (unknown "#"))')

    def test_the_first_row_that_matches_wins_not_the_longest(self):
        self.define('(token short "ab") (token long "abc") (token word "[a-z]+")')
        self.assertShows('(grammar-tokens g "abc ab")', '((short "ab") (word "c") (unknown " ") (short "ab"))')
        self.define('(token word "[a-z]+") (token short "ab")')
        self.assertShows('(grammar-tokens g "abc")', '((word "abc"))')

    def test_a_token_row_can_make_its_value_with_a_function(self):
        self.run_lisp("""
          (define-grammar g
            (token skip "\\\\s+")
            (token number "\\\\d+(?:\\\\.\\\\d+)?" string->number)
            (token word "[A-Za-z]+" string-downcase)
            (token string "'[^']*'" (lambda (text) (substring text 1 (- (string-length text) 1))))
            (rule items ((plus (or number word string)))))""")
        self.assertShows("""(grammar-parse g "12 3.5 Hello 'a b' WORLD")""", '(12 3.5 "hello" "a b" "world")')
        self.assertShows('(grammar-tokens g "Hello")', '((word "Hello"))')            # the text is the text; the value is made

    def test_a_flag_goes_inside_a_group_and_a_group_that_does_not_capture_is_fine(self):
        self.run_lisp("""(define-grammar g (token skip "\\\\s+") (token word "(?i:select|from)") (token other "(?:[a-z]+)|(?:\\\\d+)")
                           (rule r ((star word))))""")
        self.assertShows('(grammar-tokens g "SELECT From abc")', '((word "SELECT") (word "From") (other "abc"))')

    def test_the_value_function_can_stop_the_parse_with_an_error(self):
        self.run_lisp("""(define-grammar g (token skip "\\\\s+") (token word "[a-z]+")
                           (token bad "'" (lambda (text) (error "a quote that never ends")))
                           (rule r ((star word))))""")
        self.assertLispError('(grammar-parse g "ab \'cd")', "a quote that never ends")

    def test_a_long_text_is_cut_up_quickly(self):
        self.define('(token skip "\\\\s+") (token number "\\\\d+") (token symbol "[,]")')
        text = ", ".join(str(i) for i in range(20000))
        self.assertEqual(self.run_lisp('(length (grammar-tokens g "%s"))' % text), 39999)

    def test_a_grammar_with_bad_token_rows_is_an_error_when_it_is_made(self):
        for rows, fragment in [
                ('(token a "(x)")', "has a group that captures; use (?:...) instead of (...)"),
                ('(token a "x*")', "matches no text at all"),
                ('(token a "x") (token b "(?i)y")', "a flag such as (?i) belongs inside a group"),
                ('(token a "x") (token a "y")', "two token rows have the same kind"),
                ('(token a "[")', "the regular expression of a isn't valid"),
                ('(token unknown "x")', "can't be the kind of a token"),
                ('(token end "x")', "can't be the kind of a token"),
                ('(token "a" "x")', "a token's kind is a name"),
                ('(token a x)', "unbound symbol: x"),
        ]:
            with self.subTest(rows=rows):
                self.assertLispError("(define-grammar bad %s (rule r (a)))" % rows, fragment)
        self.assertLispError("(define-grammar bad (rule r (a)))", "needs at least one (token kind regular-expression) row")


class TestItems(ParserTestCase):
    """What each kind of item matches and gives, one grammar at a time."""

    TOKENS = '(token skip "\\\\s+") (token number "\\\\d+" string->number) (token word "[a-z]+") (token symbol "[-+*/(),;=]")'

    def grammar(self, *rows):
        self.run_lisp("(define-grammar g %s %s)" % (self.TOKENS, " ".join(rows)))

    def test_a_kind_has_the_tokens_value_and_a_text_has_none(self):
        self.grammar('(rule r (number "," word))')
        self.parses("g", "12 , ab", '(12 "ab")')

    def test_a_rule_with_no_action_gives_its_value_or_the_list_of_them_or_true(self):
        self.grammar("(rule one (number))", "(rule two (number number))", '(rule none ("," ";"))', "(rule empty ())")
        self.parses("g", "5", "5", start="one")
        self.parses("g", "5 6", "(5 6)", start="two")
        self.parses("g", ", ;", "#t", start="none")
        self.parses("g", "", "#t", start="empty")

    def test_an_action_gets_the_values_of_the_items_that_have_one(self):
        self.grammar('(rule r (number "," number "," word) (lambda (a b c) (list c b a)))')
        self.parses("g", "1, 2, x", '("x" 2 1)')
        self.grammar('(rule r ("(" "x" ")") (lambda () "no values"))')        # texts only: the action is given nothing
        self.parses("g", "( x )", '"no values"')

    def test_node_builder_makes_the_list_head_and_values(self):
        self.grammar("(rule r (number word) (node-builder 'pair))")
        self.parses("g", "3 x", '(pair 3 "x")')

    def test_opt_gives_the_value_of_its_items_or_nothing(self):
        self.grammar('(rule r (word (opt "=" number)))')
        self.parses("g", "a = 5", '("a" 5)')
        self.parses("g", "a", '("a" ())')
        self.grammar('(rule r (word (opt "=" number number)))')              # several values: the list of them
        self.parses("g", "a = 5 6", '("a" (5 6))')
        self.parses("g", "a", '("a" ())')
        self.grammar('(rule r ((opt "x")))')                                  # nothing but texts: true if it was there
        self.parses("g", "x", "#t")
        self.parses("g", "", "()")

    def test_flag_is_true_or_false(self):
        self.grammar('(rule r ((flag "-") number))')
        self.parses("g", "- 5", "(#t 5)")
        self.parses("g", "5", "(#f 5)")
        self.grammar('(rule r ((flag "a" "b") number))')                      # the items together
        self.parses("g", "a b 5", "(#t 5)")
        self.fails("g", "a 5", "expected b but found 5")                        # a flag's items are all or nothing... once begun

    def test_star_and_plus_give_the_list_of_the_values(self):
        self.grammar("(rule r ((star number)))", "(rule s ((plus number)))", '(rule t ((star "(" number ")")))')
        self.parses("g", "", "()", start="r")
        self.parses("g", "1 2 3", "(1 2 3)", start="r")
        self.parses("g", "1 2 3", "(1 2 3)", start="s")
        self.fails("g", "", "expected number but found the end of the input", start="s")
        self.parses("g", "(1) (2)", "(1 2)", start="t")
        self.fails("g", "(1) (", "expected number but found the end of the input", start="t")

    def test_a_star_of_something_that_can_read_nothing_stops(self):
        self.grammar('(rule r ((star (opt "x"))))')
        self.parses("g", "", "()")
        self.grammar('(rule r ((star (star number))) )')
        self.parses("g", "1 2", "((1 2))")

    def test_sep_by_is_one_or_more_with_a_separator_that_is_not_read_without_an_item_after_it(self):
        self.grammar('(rule r ((sep-by "," number)))')
        self.parses("g", "1", "(1)", start="r")
        self.parses("g", "1, 2 , 3", "(1 2 3)")
        self.fails("g", "", "expected number")
        self.fails("g", "1,", "expected number but found the end of the input")
        self.grammar('(rule r ((sep-by "," number) (opt ",")))')       # a trailing comma may be there
        self.parses("g", "1, 2,", "((1 2) #t)")
        self.grammar('(rule r ((sep-by (or "," ";") number word)))')
        self.parses("g", "1 a ; 2 b , 3 c", "((1 \"a\") (2 \"b\") (3 \"c\"))")

    def test_or_gives_the_first_item_that_matches(self):
        self.grammar("(rule r ((or number word)))")
        self.parses("g", "5", "5")
        self.parses("g", "ab", '"ab"')
        self.grammar('(rule r ((or "x" "y")))')                               # texts have no value: true
        self.parses("g", "y", "#t")
        self.grammar("(rule r ((or (seq number number) number) end))")        # a group in an or
        self.parses("g", "1 2", "(1 2)")
        self.parses("g", "1", "1")

    def test_one_of_gives_the_text_as_written_in_the_grammar(self):
        self.grammar('(rule r ((one-of "asc" "desc")))')
        self.parses("g", "desc", '"desc"')
        self.run_lisp('(define-grammar h (option ignore-case #t) (token skip "\\\\s+") (token word "[A-Za-z]+") '
                      '(rule r ((one-of "asc" "desc"))))')
        self.assertShows('(grammar-parse h "DESC")', '"desc"')                # the text of the grammar, not of the input

    def test_seq_and_drop(self):
        self.grammar("(rule r ((seq number word) number)) ")
        self.parses("g", "1 a 2", '((1 "a") 2)')
        self.grammar("(rule r ((drop number) word))")
        self.parses("g", "1 a", '"a"')
        self.grammar("(rule r ((drop (star number)) word))")
        self.parses("g", "1 2 3 a", '"a"')

    def test_not_looks_ahead_and_reads_nothing(self):
        self.run_lisp('(define-grammar k (token skip "\\\\s+") (token word "[a-z]+") (rule r ((star (not "if") word))))')
        self.assertShows('(grammar-parse k "a b c")', '("a" "b" "c")')
        self.assertLispError('(grammar-parse k "a if c")', "expected the end of the input but found if")

    def test_end_matches_only_the_end(self):
        self.grammar("(rule r (number end))")
        self.parses("g", "1", "1")
        self.fails("g", "1 2", "expected the end of the input but found 2")
        # inside a rule, end is what keeps an alternative from being the one when there's more to read
        self.grammar("(rule r (number end) (lambda (a) (list 'alone a)))", "(rule r (number number) (lambda (a b) (list 'pair a b)))")
        self.parses("g", "1", "(alone 1)")
        self.parses("g", "1 2", "(pair 1 2)")

    def test_chain_groups_from_the_left_with_a_symbol_or_a_procedure_for_each_operator(self):
        self.grammar('(rule r ((chain number ("-" . minus) ("+" . plus))))')
        self.parses("g", "1", "1")
        self.parses("g", "1 - 2 - 3", "(minus (minus 1 2) 3)")
        self.parses("g", "1 - 2 + 3 - 4", "(minus (plus (minus 1 2) 3) 4)")
        self.fails("g", "1 -", "expected number but found the end of the input")
        # a procedure for an operator can only be in a grammar made from a list of rows
        self.run_lisp("""(define h (make-grammar
                           (list (list 'token 'skip "\\\\s+") (list 'token 'number "\\\\d+" string->number) (list 'token 'symbol "[-+]")
                                 (list 'rule 'r (list (list 'chain 'number (cons "-" -) (cons "+" +)))))))""")
        self.assertShows('(grammar-parse h "10 - 3 + 4 - 1")', "10")
        self.assertShows('(grammar-parse h "10 - 3 - 3")', "4")

    def test_a_rule_can_use_itself_after_reading_something(self):
        self.grammar('(rule r ("(" (star r) ")"))')
        self.parses("g", "()", "()")
        self.parses("g", "( ( ) ( ( ) ) )", "(() (()))")
        self.fails("g", "(()", "expected ) but found the end of the input")

    def test_alternatives_are_tried_in_order_and_a_failed_one_is_backed_out_of(self):
        self.grammar("(rule r (number \"+\" number) (lambda (a b) (list 'sum a b)))",
                     "(rule r (number \"-\" number) (lambda (a b) (list 'difference a b)))",
                     "(rule r (number) (lambda (a) (list 'just a)))")
        self.parses("g", "1 + 2", "(sum 1 2)")
        self.parses("g", "1 - 2", "(difference 1 2)")
        self.parses("g", "7", "(just 7)")
        self.grammar("(rule r (word) (lambda (a) 'first))", "(rule r (word number) (lambda (a b) 'second))")
        self.fails("g", "a 5", "expected the end of the input but found 5")          # the first alternative won

    def test_the_start_rule_is_the_first_unless_the_option_or_the_keyword_says(self):
        self.grammar("(rule a (number))", "(rule b (word))")
        self.parses("g", "5", "5")
        self.parses("g", "x", '"x"', start="b")
        self.grammar("(option start b)", "(rule a (number))", "(rule b (word))")
        self.parses("g", "x", '"x"')
        self.parses("g", "5", "5", start="a")
        self.assertLispError("(grammar-parse g \"5\" :start 'nope)", "nope isn't a rule of the grammar")

    def test_ignore_case_applies_to_the_texts_in_rules(self):
        self.run_lisp('(define-grammar g (option ignore-case #t) (token skip "\\\\s+") (token word "[A-Za-z]+") (rule r ("select" word)))')
        self.assertShows('(grammar-parse g "SeLeCt x")', '"x"')
        self.run_lisp('(define-grammar g (token skip "\\\\s+") (token word "[A-Za-z]+") (rule r ("select" word)))')
        self.assertLispError('(grammar-parse g "SELECT x")', "expected select but found SELECT")

    def test_a_grammar_made_from_a_list_of_rows(self):
        self.run_lisp("""(define g (make-grammar (list '(token skip "\\\\s+") '(token number "\\\\d+" ) (list 'rule 'r '(number) (lambda (n) (list 'got n))))))""")
        self.assertShows('(grammar-parse g "12")', '(got "12")')


class TestEfficiency(ParserTestCase):

    def test_what_a_rule_finds_is_remembered_so_alternatives_that_start_alike_cost_nothing(self):
        """Each alternative of `e` begins with the same parenthesized e; without remembering, nesting n deep takes 3**n tries."""
        self.run_lisp("""
          (define calls 0)
          (define-grammar g
            (token skip "\\\\s+") (token number "\\\\d+") (token symbol "[-+()]")
            (rule e ("(" e ")" "+") (lambda (inner) inner))
            (rule e ("(" e ")" "-") (lambda (inner) inner))
            (rule e ("(" e ")") (lambda (inner) inner))
            (rule e (number) (lambda (n) (set! calls (+ calls 1)) n)))""")
        depth = 40
        self.assertShows('(grammar-parse g "%s7%s")' % ("(" * depth, ")" * depth), '"7"')
        self.assertEqual(self.run_lisp("calls"), 1)

    def test_a_rule_that_begins_with_itself_is_an_error_that_says_so(self):
        self.run_lisp('(define-grammar g (token skip "\\\\s+") (token number "\\\\d+") (token symbol "[-+]") '
                      '(rule sum (sum "+" number)) (rule sum (number)))')
        self.assertLispError('(grammar-parse g "1 + 2")', "rule sum begins with itself, so it would never stop")
        self.run_lisp('(define-grammar g (token skip "\\\\s+") (token number "\\\\d+") (rule a (b)) (rule b (a)))')
        self.assertLispError('(grammar-parse g "1")', "begins with itself")

    def test_a_long_text_takes_time_in_proportion(self):
        self.run_lisp('(define-grammar g (token skip "\\\\s+") (token number "\\\\d+" string->number) (token symbol "[,]") '
                      '(rule r ((sep-by "," number))))')
        n = 3000
        text = ", ".join(str(i) for i in range(n))
        self.assertEqual(self.run_lisp('(length (grammar-parse g "%s"))' % text), n)


class TestErrors(ParserTestCase):

    def define(self, *rows, options=""):
        self.run_lisp('(define-grammar g %s (token skip "\\\\s+") (token number "\\\\d+") (token word "[a-z]+") '
                      '(token symbol "[-+*/(),;=]") %s)' % (options, " ".join(rows)))

    def test_the_message_says_what_was_expected_where_the_text_stopped_fitting_and_what_was_there(self):
        self.define('(rule r (word "=" number ";"))')
        self.fails("g", "a = 5", "parse error: expected ; but found the end of the input")
        self.fails("g", "a = b ;", "parse error: expected number but found b (at character 4)")
        self.fails("g", "a + 5 ;", "parse error: expected = but found + (at character 2)")
        self.fails("g", "", "parse error: expected word but found the end of the input")
        self.fails("g", "a = 5 ; x", "parse error: expected the end of the input but found x (at character 8)")

    def test_alternatives_that_fail_at_the_same_place_are_all_named_once(self):
        self.define('(rule r ("(" word ")"))', '(rule r ("[" word "]"))', '(rule r (number "+"))', '(rule r (number "-"))')
        self.fails("g", "x", "expected (, [ or number but found x (at character 0)")
        self.fails("g", "5 *", "expected + or - but found * (at character 2)")

    def test_a_failure_further_on_is_the_one_reported(self):
        self.define('(rule r (word "=" number))', '(rule r (word "+"))')
        self.fails("g", "a = x", "expected number but found x (at character 4)")

    def test_a_part_that_is_optional_is_not_listed_unless_nothing_else_could_come(self):
        self.define('(rule r (number (star "+" number) ")"))')
        self.fails("g", "1 + 2", "expected ) but found the end of the input")            # not "+" as well
        self.fails("g", "1 + ", "expected number but found the end of the input")         # a + was read: a number is needed
        self.define('(rule r (number (opt "+" number) (opt "-" number)))')
        self.fails("g", "1 *", "expected +, - or the end of the input but found * (at character 2)")
        self.fails("g", "1 + 2 *", "expected - or the end of the input but found * (at character 6)")

    def test_a_description_replaces_what_a_rule_tried(self):
        self.define('(rule r (item item))', '(rule item (number))', '(rule item ("(" number ")"))',
                    '(describe item "a number or (number)")')
        self.fails("g", "5 x", "expected a number or (number) but found x (at character 2)")
        self.fails("g", "5 (", "expected number but found the end of the input")             # once past the start of an item

    def test_the_options_say_how_a_message_starts_and_what_the_end_is_called(self):
        self.define('(rule r (number ";"))', options='(option error-prefix "calc:") (option end-name "the end of the line")')
        self.fails("g", "1", "calc: expected ; but found the end of the line")
        self.fails("g", "1 ; 2", "calc: expected the end of the line but found 2")

    def test_texts_are_in_capitals_when_the_case_is_ignored(self):
        self.define('(rule r ("select" word "from" word))', options="(option ignore-case #t)")
        self.fails("g", "select a", "expected FROM but found the end of the input")

    def test_the_list_of_what_was_expected_is_cut_short(self):
        words = " ".join('(rule r ("%s"))' % w for w in "abcdefghijkl")
        self.define(words)
        self.fails("g", "z", "expected a, b, c, d, e, f, g, h, ... but found z (at character 0)")

    def test_a_token_of_spaces_is_named_by_its_kind(self):
        self.run_lisp('(define-grammar g (token skip "[ \\t]+") (token newline "\\n") (token word "[a-z]+") (rule r (word word)))')
        self.assertLispError('(grammar-parse g "ab\ncd")', "expected word but found newline (at character 2)")

    def test_a_character_nothing_matches_is_an_error_where_it_is(self):
        self.define('(rule r (number number))')
        self.fails("g", "1 $", "expected number but found $ (at character 2)")

    def test_a_mistake_in_a_grammar_is_found_when_it_is_made(self):
        for rows, fragment in [
                ("(rule r (nope))", "rule r uses nope which is neither a rule nor a kind of token"),
                ("(rule r ((star nope)))", "uses nope"),
                ("(rule r ((chain number (\"+\" . plus) nope)))", "(chain ...) takes an operand and then (text . node) pairs"),
                ("(rule r ((one-of number)))", "(one-of ...) is for texts"),
                ("(rule r ((frob number)))", "this isn't an item: (frob number)"),
                ("(rule r (12))", "this isn't an item: 12"),
                ("(rule number (word))", "number is the name of a rule, and of a kind of token"),
                ("(rule end (word))", "end is the name of a rule"),
                ("(describe nope \"x\") (rule r (word))", "(describe nope ...) is not a rule or a kind of token"),
                ("(option nope 1) (rule r (word))", "unknown option nope"),
                ("(option start nope) (rule r (word))", "the start rule nope isn't a rule"),
                ("(frob 1)", "a clause of define-grammar is"),
        ]:
            with self.subTest(rows=rows):
                self.assertLispError('(define-grammar bad (token number "\\\\d+") (token word "[a-z]+") %s)' % rows, fragment)
        self.assertLispError('(define-grammar bad (token word "[a-z]+"))', "needs at least one rule")


class TestGrammarsAgainstPython(ParserTestCase):
    """Two grammars, with the text of many random inputs read by Python as well."""

    ARITHMETIC = """
      (define-grammar arithmetic
        (token skip   "\\\\s+")
        (token number "\\\\d+(?:\\\\.\\\\d+)?" string->number)
        (token symbol "[-+*/()]")
        (rule expression ((chain term ("+" . +) ("-" . -))))
        (rule term       ((chain factor ("*" . *) ("/" . /))))
        (rule factor     ("-" factor) (node-builder '-))
        (rule factor     (number))
        (rule factor     ("(" expression ")")))"""

    def random_expression(self, rng, depth=0):
        if depth > 3 or rng.random() < 0.3:
            return rng.choice(["%d", "%d.5", "%d.25"]) % rng.randint(1, 9)
        r = rng.random()
        if r < 0.15:
            return "-" + self.random_expression(rng, depth + 1)
        if r < 0.30:
            return "(" + self.random_expression(rng, depth + 1) + ")"
        spaces = rng.choice(["", " ", "  "])
        return (self.random_expression(rng, depth + 1) + spaces + rng.choice("+-*/") + spaces
                + self.random_expression(rng, depth + 1))

    def test_arithmetic_is_the_value_python_gets(self):
        self.run_lisp(self.ARITHMETIC)
        rng = random.Random(5)
        checked = 0
        for _ in range(300):
            text = self.random_expression(rng)
            try:
                expected = eval(text)
            except ZeroDivisionError:
                continue
            value = self.run_lisp('(eval (grammar-parse arithmetic "%s"))' % text)       # the tree is Lisp: (+ 1 (* 2 3))
            with self.subTest(text=text):
                self.assertAlmostEqual(float(value), float(expected), delta=1e-4 * max(1.0, abs(expected)))
            checked += 1
        self.assertGreater(checked, 250)

    def test_arithmetic_trees_group_as_python_does(self):
        self.run_lisp(self.ARITHMETIC)
        self.assertShows('(grammar-parse arithmetic "1 - 2 - 3")', "(- (- 1 2) 3)")
        self.assertShows('(grammar-parse arithmetic "1 - 2 * 3")', "(- 1 (* 2 3))")
        self.assertShows('(grammar-parse arithmetic "8 / 4 / 2")', "(/ (/ 8 4) 2)")
        self.assertShows('(grammar-parse arithmetic "-2 * -3")', "(* (- 2) (- 3))")
        self.assertShows('(grammar-parse arithmetic "(1 + 2) * 3")', "(* (+ 1 2) 3)")

    JSON = """
      (define-grammar json
        (token skip   "\\\\s+")
        (token number "-?\\\\d+(?:\\\\.\\\\d+)?(?:[eE][-+]?\\\\d+)?")
        (token string "\\"(?:[^\\"\\\\\\\\]|\\\\\\\\.)*\\"")
        (token word   "true|false|null")
        (token symbol "[\\\\[\\\\]{},:]")
        (rule value (number))
        (rule value (string))
        (rule value (word))
        (rule value ("[" (opt (sep-by "," value)) "]") (lambda (items) (format "[{}]" (string-join items ","))))
        (rule value ("{" (opt (sep-by "," member)) "}") (lambda (members) (format "{{{}}}" (string-join members ","))))
        (rule member (string ":" value) (lambda (key value) (format "{}:{}" key value))))"""

    def random_json(self, rng, depth=0):
        r = rng.random()
        if depth > 3 or r < 0.35:
            return rng.choice([rng.randint(-50, 50), round(rng.uniform(-9, 9), 3), 1e21, True, False, None,
                               "plain", "with \"quotes\" and \\ slash", "tab\there", "", "unicode é ☃", "a,b:{c}[d]"])
        if r < 0.7:
            return [self.random_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]
        return {rng.choice(["a", "b c", "d\"e", "f", "g1"]) + str(i): self.random_json(rng, depth + 1)
                for i in range(rng.randint(0, 4))}

    def canonical(self, value, ascii_only):
        """The text the Lisp grammar makes: the JSON with no spaces, strings and numbers as they were written."""
        if isinstance(value, list):
            return "[" + ",".join(self.canonical(v, ascii_only) for v in value) + "]"
        if isinstance(value, dict):
            return "{" + ",".join(json.dumps(k, ensure_ascii=ascii_only) + ":" + self.canonical(v, ascii_only)
                                  for k, v in value.items()) + "}"
        return json.dumps(value, ensure_ascii=ascii_only)

    def test_json_is_read_as_python_reads_it(self):
        self.run_lisp(self.JSON)
        rng = random.Random(9)
        for i in range(120):
            value = self.random_json(rng)
            ascii_only = rng.random() < 0.5
            text = json.dumps(value, indent=rng.choice([None, 1, 2]), ensure_ascii=ascii_only)
            with self.subTest(text=text):
                got = self.run_lisp('(grammar-parse json "%s")' % text.replace("\\", "\\\\").replace('"', '\\"'))
                self.assertEqual(str(got), self.canonical(json.loads(text), ascii_only))

    def test_bad_json_is_an_error_python_agrees_is_one(self):
        self.run_lisp(self.JSON)
        for text in ['[1, 2', '{"a" 1}', '{"a": }', '[1,, 2]', '[1 2]', '{"a": 1,}', '[1, 2]]', '"abc', 'tru', '{1: 2}', '[,]']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    json.loads(text)
                self.assertLispError('(grammar-parse json "%s")' % text.replace('"', '\\"'), "parse error: expected")

    def test_json_nested_deeply_is_read(self):
        self.run_lisp(self.JSON)
        text = "[" * 60 + "1" + "]" * 60
        self.assertEqual(str(self.run_lisp('(grammar-parse json "%s")' % text)), text)
