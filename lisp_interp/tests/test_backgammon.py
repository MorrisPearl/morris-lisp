"""backgammon.lsp (the rules, and the board as text) and backgammon_net.lsp (the
network, its inputs, TD(lambda) learning, matches, saving, and play against
it).

The rules are checked on positions small enough to work out by hand. The
network's gradients are checked against finite differences. Learning is checked
with a short run that shows it works, not how well it plays: that is what
examples/backgammon_train.lsp is for, and it takes a long time."""

import os
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


def board_source(mover=(), opponent=(), bar=0, opponent_bar=0):
    """A position as Lisp source, from the mover's point of view. mover and opponent map
    a point (1 to 24) to a count of checkers on it; bar and opponent_bar are checkers
    on the bar."""
    cells = [0] * 26
    cells[0] = bar
    for point, count in dict(mover).items():
        cells[point] = count
    for point, count in dict(opponent).items():
        cells[point] = -count
    cells[25] = -opponent_bar
    return "(vector %s)" % " ".join(str(c) for c in cells)


class TestBackgammonRules(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "backgammon.lsp")')

    def play_texts(self, board, dice):
        """Every play for these dice as its text, sorted, joined by semicolons."""
        return self.run_lisp(
            "(string-join (sort (map backgammon-play-text (backgammon-plays %s '(%s)))) \"; \")"
            % (board, " ".join(map(str, dice))))

    def test_the_starting_position_has_167_pips_each_and_nothing_off(self):
        self.assertShows("(backgammon-pips (backgammon-start))", "167")
        self.assertShows("(backgammon-opponent-pips (backgammon-start))", "167")
        self.assertShows("(backgammon-off (backgammon-start))", "0")
        self.assertShows("(backgammon-opponent-off (backgammon-start))", "0")

    def test_turning_the_board_around_twice_gives_the_same_board(self):
        self.assertShows("(equal? (backgammon-flip (backgammon-flip (backgammon-start))) (backgammon-start))", "#t")
        self.assertShows("(backgammon-flip (backgammon-start))",
                         "#(0 -2 0 0 0 0 5 0 3 0 0 0 -5 5 0 0 0 -3 0 -5 0 0 0 0 2 0)")

    def test_the_opening_6_5_has_seven_plays(self):
        self.assertEqual(self.play_texts("(backgammon-start)", [6, 5]),
                         "13/7 13/8; 13/7 7/2; 13/7 8/3; 24/18 13/8; 24/18 18/13; 24/18 8/3; 8/2 8/3")

    def test_each_play_moves_the_pips_by_the_dice(self):
        # nothing is hit or borne off from the start, so every play of 3-1 leaves 4 fewer pips
        self.assertShows("(let ((plays (backgammon-plays (backgammon-start) '(3 1))))"
                         " (= (length (filter (lambda (p) (= (backgammon-pips (backgammon-play-board p)) 163)) plays))"
                         "    (length plays)))", "#t")

    def test_doubles_are_played_four_times(self):
        self.assertShows("(length (backgammon-play-steps (car (backgammon-plays (backgammon-start) '(6 6 6 6)))))",
                         "4")

    def test_when_only_one_die_can_be_used_it_must_be_the_higher(self):
        # the checker on 10 can go to 4 with a 6, or to 7 with a 3, but not on from either: 4 to 1 and
        # 7 to 1 are held by two of the opponent's, so only one die can be used, and it must be the 6
        board = board_source(mover={10: 1}, opponent={1: 2})
        self.assertEqual(self.play_texts(board, [6, 3]), "10/4")

    def test_with_no_legal_move_the_only_play_stays_put(self):
        board = board_source(mover={10: 1}, opponent={9: 2, 8: 2})
        self.assertShows("(backgammon-play-steps (car (backgammon-plays %s '(2 1))))" % board, "()")
        self.assertShows("(equal? (backgammon-play-board (car (backgammon-plays %s '(2 1)))) %s)" % (board, board),
                         "#t")

    def test_a_checker_on_the_bar_must_enter_first(self):
        board = board_source(mover={24: 2}, opponent={20: 2}, bar=1)
        texts = self.play_texts(board, [3, 1])
        self.assertIn("bar/22", texts)
        for text in texts.split("; "):
            self.assertTrue(text.startswith("bar/"), text)

    def test_a_blot_is_hit_and_goes_to_the_bar(self):
        board = board_source(mover={24: 2}, opponent={18: 1})
        self.assertShows("(vector-ref (backgammon-move-checker %s 24 18) 18)" % board, "1")
        self.assertShows("(vector-ref (backgammon-move-checker %s 24 18) 25)" % board, "-1")
        self.assertShows("(vector-ref (backgammon-move-checker %s 24 18) 24)" % board, "1")

    def test_a_point_with_two_of_the_opponents_cannot_be_landed_on(self):
        board = board_source(mover={24: 2}, opponent={18: 2})
        self.assertEqual(self.play_texts(board, [6, 6]), "")      # 24 to 18 is blocked, and nothing else moves

    def test_bearing_off_with_a_higher_die_only_from_the_highest_point(self):
        board = board_source(mover={3: 1, 2: 1}, opponent={20: 13})
        texts = self.play_texts(board, [6, 5]).split("; ")
        self.assertIn("3/off 2/off", texts)                       # the 6 takes the 3 off, then the 5 the 2
        self.assertEqual(len(texts), len(set(texts)))            # a play is listed once, however it is ordered

    def test_no_bearing_off_while_a_checker_is_outside_the_home_board(self):
        board = board_source(mover={6: 1, 9: 1}, opponent={20: 13})
        self.assertNotIn("off", self.play_texts(board, [1, 1]))    # four 1s can't bring both inside the home board

    def test_the_pip_counts_of_both_sides(self):
        board = board_source(mover={6: 2, 1: 1}, opponent={24: 3}, bar=1)
        self.assertShows("(backgammon-pips %s)" % board, str(25 + 12 + 1))
        self.assertShows("(backgammon-opponent-pips %s)" % board, str(3 * 1))

    def test_parsing_moves_in_the_usual_notation(self):
        self.assertShows('(backgammon-parse-steps "24/18 bar/20 3/off")', "((24 18) (0 20) (3 0))")
        self.assertLispError('(backgammon-parse-steps "24-18")', "not a move")

    def test_a_typed_play_is_found_whatever_the_order_of_its_moves(self):
        self.assertShows("(backgammon-play-text (backgammon-find-play (backgammon-plays (backgammon-start) "
                         "'(6 5)) '((13 8) (24 18))))", '"24/18 13/8"')
        self.assertShows("(backgammon-find-play (backgammon-plays (backgammon-start) '(6 5)) '((24 1)))", "#f")

    def test_both_dice_may_be_typed_as_one_move_if_either_order_is_legal(self):
        roll = "'(3 2)"
        # from the start 13/8 can be 13/10 10/8 or 13/11 11/8
        self.assertNotEqual(self.show("(backgammon-find-play (backgammon-plays (backgammon-start) %s) '((13 8)))" % roll), "#f")
        # with the 10 point blocked it is still legal by way of the 11 point
        blocked_one = board_source(mover={13: 1}, opponent={10: 2})
        self.assertNotEqual(self.show("(backgammon-find-play (backgammon-plays %s %s) '((13 8)))" % (blocked_one, roll)), "#f")
        # with both blocked it is not
        blocked_both = board_source(mover={13: 1}, opponent={10: 2, 11: 2})
        self.assertShows("(backgammon-find-play (backgammon-plays %s %s) '((13 8)))" % (blocked_both, roll), "#f")
        # the steps written one at a time still work
        self.assertNotEqual(self.show("(backgammon-find-play (backgammon-plays (backgammon-start) %s) '((13 10) (10 8)))" % roll), "#f")

    def test_checkers_are_drawn_next_to_the_number_of_their_point(self):
        self.run_lisp("(backgammon-show (backgammon-start))")
        lines = self.printed().rstrip("\n").split("\n")
        cell = lambda line, point_index: line[1 + 3 * point_index: 4 + 3 * point_index]
        # top: point 24 (two checkers) is the first column, the rows count down from the numbers
        self.assertEqual(cell(lines[2], 0), " X ")
        self.assertEqual(cell(lines[3], 0), " X ")
        self.assertEqual(cell(lines[4], 0), " . ")
        # bottom: point 8 (three checkers) is the eighth column, the rows count up toward the numbers
        self.assertEqual(cell(lines[-2], 7), " X ")
        self.assertEqual(cell(lines[-4], 7), " X ")
        self.assertEqual(cell(lines[-5], 7), " . ")

    def test_the_board_is_drawn_from_the_players_point_of_view(self):
        self.run_lisp("(backgammon-show (backgammon-start))")
        text = self.printed()
        self.assertTrue(text.startswith("bar: X 0  O 0      off: X 0  O 0"), text)
        self.assertIn(" 24 23 22 21 20 19 18 17 16 15 14 13", text)
        self.assertIn("  1  2  3  4  5  6  7  8  9 10 11 12", text)
        board_rows = text.split("\n")[1:]                 # the header line also has an X and an O
        self.assertEqual("".join(board_rows).count("X"), 15)
        self.assertEqual("".join(board_rows).count("O"), 15)


class TestBackgammonNetwork(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "backgammon.lsp")')
        self.run_lisp('(load "backgammon_net.lsp")')
        self.run_lisp("(random-seed 7)")

    def test_the_inputs_are_216_numbers_ending_in_the_constant_one(self):
        self.assertShows("(vector-length (backgammon-features (backgammon-start)))", "216")
        self.assertShows("(vector-ref (backgammon-features (backgammon-start)) 215)", "1.0")

    def test_the_raw_inputs_follow_tesauros_encoding(self):
        # 4 units for each point of each side: on the starting board the mover has 2 on 24, so the
        # first unit of point 24 (index 23) is 1, its second too, and its third (exactly three) is 0
        features = "(backgammon-features (backgammon-start))"
        self.assertShows("(vector-ref %s 23)" % features, "1.0")
        self.assertShows("(vector-ref %s 47)" % features, "1.0")     # second unit, point 24
        self.assertShows("(vector-ref %s 71)" % features, "0.0")     # third unit, point 24
        # the mover's 5 on point 6 (index 5): its fourth unit is 0.5 * (5 - 3) = 1, at index 72 + 5
        self.assertShows("(vector-ref %s 77)" % features, "1.0")

    def test_the_crafted_features_count_blots_and_points(self):
        # a mover with one blot on point 6 and a point made on 4: one blot, two points made
        board = board_source(mover={6: 1, 4: 2}, opponent={20: 12, 3: 1})   # the opponent's checker on 3 is a contact
        features = "(backgammon-features %s)" % board
        raw = 198
        self.assertShows("(vector-ref %s %d)" % (features, raw), "0.16666666666666666")     # 1 blot / 6
        self.assertShows("(vector-ref %s %d)" % (features, raw + 1), "0.08333333333333333")  # 1 point made / 12

    def test_a_position_is_a_race_once_no_checker_can_hit_another(self):
        self.assertShows("(backgammon-contact? (backgammon-start))", "#t")
        # the mover's checkers on point 5 are below the opponent's on point 10: nothing can be hit
        self.assertShows("(backgammon-contact? %s)" % board_source(mover={5: 15}, opponent={10: 15}), "#f")
        # a checker on the bar is still in contact
        self.assertShows("(backgammon-contact? %s)" % board_source(mover={5: 14}, bar=1, opponent={10: 15}), "#t")

    def test_in_a_race_the_contact_features_are_zero_and_the_race_features_count(self):
        features = "(backgammon-features %s)" % board_source(mover={5: 15}, opponent={10: 15})
        self.assertShows("(vector-ref %s 210)" % features, "1.0")          # the race flag
        self.assertShows("(vector-ref %s 198)" % features, "0.0")          # blots, gated to contact
        self.assertShows("(vector-ref %s 211)" % features, "0.2")          # the mover's 15 in its home board: 15 quarters of 75
        self.assertShows("(vector-ref %s 212)" % features, "0.6")          # the opponent's 15 on its point 15 (our point 10), in its third quarter: 45 of 75

    def test_crossovers_count_the_quarters_each_checker_still_has_to_travel(self):
        # a checker on the bar is 5 quarters, one in the home board 1, one in the opponent's home board 4
        board = board_source(bar=1, mover={1: 2, 19: 1})
        self.assertShows("(* 75 (backgammon--side-crossovers %s))" % board, "11.0")

    def test_wastage_counts_the_checkers_beyond_two_on_points_one_and_two(self):
        # 5 on point 1 wastes 3, 3 on point 2 wastes 1; the 2 on point 5 are not counted
        board = board_source(mover={1: 5, 2: 3, 5: 2})
        self.assertShows("(* 15 (backgammon--side-wastage %s))" % board, "4.0")

    def test_the_longest_prime_counts_the_points_in_a_row(self):
        self.assertShows("(backgammon--longest-prime #(2 2 2 0 2 2 2 2 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0))", "4.0")
        self.assertShows("(backgammon--longest-prime (make-vector 24 0))", "0.0")

    def test_the_transposed_product_sums_the_rows_weighted_by_the_vector(self):
        self.assertShows("(transpose-matrix-vector-product #(1 2 3 4 5 6) #(1 10))", "#(41.0 52.0 63.0)")

    def test_the_gradients_agree_with_finite_differences(self):
        # the hidden gradient for output k is the block k of the gradients: unit j, input i at k * 3 * 216 + j * 216 + i
        self.run_lisp("(define net (backgammon-new-net :hidden 3))")
        self.run_lisp("(define board (backgammon-start))")
        self.run_lisp("(define gradients (backgammon--outputs-and-gradients net board))")
        self.run_lisp("(define epsilon 0.000001)")
        self.run_lisp("""(define (numeric-change weights-of k weight gradient-value)
                           (let* ((w (weights-of net)) (base (vector-ref w weight)))
                             (vector-set! w weight (+ base epsilon))
                             (let ((up (vector-ref (backgammon-outcomes net board) k)))
                               (vector-set! w weight base)
                               (< (abs (- (/ (- up (vector-ref (first gradients) k)) epsilon) gradient-value)) 0.000001))))""")
        # hidden weights: block k of the gradients (k * 3 * 216 long) holds output k's gradient for each weight
        for k, unit, input in ((1, 2, 50), (4, 0, 23), (2, 1, 200)):
            weight = unit * 216 + input
            gradient = "(vector-ref (second gradients) %d)" % (k * 3 * 216 + weight)
            self.assertShows("(numeric-change backgammon-net-hidden-weights %d %d %s)" % (k, weight, gradient), "#t")
        # output weights: row k holds the gradients for output k, of 4 weights (3 hidden units and the bias)
        for k, weight in ((0, 2), (3, 0), (4, 3)):
            gradient = "(vector-ref (third gradients) %d)" % (k * 4 + weight)
            self.assertShows("(numeric-change backgammon-net-output-weights %d %d %s)" % (k, k * 4 + weight, gradient), "#t")

    def test_the_outputs_are_five_and_their_equity_is_in_points(self):
        self.run_lisp("(define net (backgammon-new-net :hidden 4))")
        self.assertShows("(vector-length (backgammon-outcomes net (backgammon-start)))", "5")
        self.assertShows("(backgammon-equity-of #(1 0 0 0 0))", "1")       # a single win
        self.assertShows("(backgammon-equity-of #(1 1 0 0 0))", "2")       # a gammon
        self.assertShows("(backgammon-equity-of #(1 1 1 0 0))", "3")       # a backgammon
        self.assertShows("(backgammon-equity-of #(0 0 0 0 0))", "-1")      # a single loss
        self.assertShows("(backgammon-equity-of #(0 0 0 1 0))", "-2")      # a gammon lost
        self.assertShows("(backgammon-equity-of #(0 0 0 1 1))", "-3")      # a backgammon lost

    def test_the_outcome_of_a_game_and_its_mirror_for_the_other_player(self):
        self.assertShows("(backgammon-outcome 1)", "#(1.0 0.0 0.0 0.0 0.0)")
        self.assertShows("(backgammon-outcome 2)", "#(1.0 1.0 0.0 0.0 0.0)")
        self.assertShows("(backgammon-mirror (backgammon-outcome 2))", "#(0.0 0.0 0.0 1.0 0.0)")
        self.assertShows("(backgammon-mirror (backgammon-outcome 3))", "#(0.0 0.0 0.0 1.0 1.0)")
        # the mirror of a position is the opponent's view of it: its equity is the negative
        self.assertShows("(backgammon-equity-of (backgammon-mirror #(0.9 0.5 0.2 0.1 0.05)))", "-1.35")

    def test_a_game_is_worth_1_2_or_3_by_the_gammon_and_backgammon_rules(self):
        # a winner with the opponent's 15 checkers on the board, none off: a gammon
        self.assertShows("(backgammon-result (vector 0 0 0 0 0 0 0 -15 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0))", "2")
        # the same, with one of them still on the bar: a backgammon
        self.assertShows("(backgammon-result (vector 0 0 0 0 0 0 0 -14 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 -1))", "3")
        # the opponent has borne off a checker: a single game
        self.assertShows("(backgammon-result (vector 0 0 0 0 0 0 0 -14 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0))", "1")

    def test_a_new_network_has_its_weights_and_repeats_with_a_seed(self):
        self.assertShows("(vector-length (backgammon-net-hidden-weights (backgammon-new-net :hidden 5)))",
                         str(5 * 216))
        self.assertShows("(vector-length (backgammon-net-output-weights (backgammon-new-net :hidden 5)))", "30")
        first = self.show("(begin (random-seed 3) (backgammon-value (backgammon-new-net :hidden 5) (backgammon-start)))")
        second = self.show("(begin (random-seed 3) (backgammon-value (backgammon-new-net :hidden 5) (backgammon-start)))")
        self.assertEqual(first, second)

    def test_a_self_play_game_ends_and_teaches_the_network(self):
        self.run_lisp("(define net (backgammon-new-net :hidden 8))")
        before = self.show("(vector-sum (backgammon-net-hidden-weights net))")
        self.run_lisp("(define average (backgammon-train! net 2))")
        self.assertGreater(float(self.show("average")), 1)
        self.assertNotEqual(self.show("(vector-sum (backgammon-net-hidden-weights net))"), before)

    def test_a_game_against_the_heuristic_ends_and_teaches_the_network_only_its_own_moves(self):
        self.run_lisp("(define net (backgammon-new-net :hidden 8))")
        before = self.show("(vector-sum (backgammon-net-hidden-weights net))")
        self.run_lisp("(define average (backgammon-train-against-heuristic! net 2))")
        self.assertGreater(float(self.show("average")), 1)
        self.assertNotEqual(self.show("(vector-sum (backgammon-net-hidden-weights net))"), before)

    def test_a_game_that_runs_past_the_stall_limit_is_counted_and_scored_as_a_loss_for_both(self):
        self.run_lisp("(define net (backgammon-new-net :hidden 8))")
        self.run_lisp("(set! backgammon-stall-limit 3)")
        before = self.show("(vector-sum (backgammon-net-hidden-weights net))")
        self.run_lisp("(backgammon-train! net 2)")
        self.assertShows("backgammon-stalled-games", "2")
        self.assertShows("backgammon-stalled-races", "0")
        self.assertTrue(int(float(self.show("backgammon-stalled-borne-off"))) >= 0)
        self.assertNotEqual(self.show("(vector-sum (backgammon-net-hidden-weights net))"), before)
        self.run_lisp("(backgammon-train-against-heuristic! net 2)")
        self.assertShows("backgammon-stalled-games", "2")
        self.run_lisp("(set! backgammon-stall-limit 300)")

    def test_a_stalled_race_and_the_checkers_borne_off_are_counted(self):
        self.run_lisp("(backgammon--reset-stall-counts!)")
        self.run_lisp("(backgammon--note-stall! %s)" % board_source(mover={5: 10}, opponent={10: 11}))
        self.assertShows("backgammon-stalled-games", "1")
        self.assertShows("backgammon-stalled-races", "1")
        self.assertShows("backgammon-stalled-borne-off", "9")

    def small_endgames(self):
        """An endgame-set of two side states: one checker on the 1 point, and two."""
        self.run_lisp('(load "backgammon_endgames.lsp")')
        self.run_lisp("(define states '((1 0 0 0 0 0) (2 0 0 0 0 0)))")
        self.run_lisp("(define endgames (make-endgame-set :count 2 "
                      ":mover-rows (apply vector-append (map backgammon--mover-row states)) "
                      ":opponent-rows (apply vector-append (map backgammon--opponent-row states)) "
                      ":chances (make-vector 4 0.0)))")
        self.run_lisp("(dotimes (i 2) (dotimes (j 2) (vector-set! (endgame-set-chances endgames) (+ (* i 2) j) "
                      "(backgammon-endgame-chance (backgammon-endgame-board endgames i j)))))")

    def test_exact_end_game_chances_match_the_ones_worked_out_by_hand(self):
        self.run_lisp('(load "backgammon_endgames.lsp")')
        # 3 checkers against 1, all on the 1 points: the player on roll needs doubles (1 in 6)
        three_against_one = board_source(mover={1: 3}, opponent={24: 1})
        self.assertAlmostEqual(float(self.show("(backgammon-endgame-chance %s)" % three_against_one)), 1 / 6, places=9)
        # one checker on the 1 point bears off with any roll, so it wins
        one_against_five = board_source(mover={1: 1}, opponent={24: 5})
        self.assertAlmostEqual(float(self.show("(backgammon-endgame-chance %s)" % one_against_five)), 1.0, places=9)

    def test_end_game_chances_of_stacks_on_the_one_point_follow_the_recursion(self):
        self.run_lisp('(load "backgammon_endgames.lsp")')

        def chance(a, b):
            if a <= 2:
                return 1.0
            doubles = 1.0 if a <= 4 else 1 - chance(b, a - 4)
            others = 1 - chance(b, a - 2)
            return doubles / 6 + others * 5 / 6

        for a, b in [(5, 5), (6, 4), (8, 10)]:
            board = board_source(mover={1: a}, opponent={24: b})
            self.assertAlmostEqual(float(self.show("(backgammon-endgame-chance %s)" % board)), chance(a, b), places=9)

    def test_teaching_the_network_end_games_moves_it_toward_the_exact_chances(self):
        self.small_endgames()
        self.run_lisp("(define net (backgammon-new-net :hidden 6))")
        self.run_lisp("(random-seed 3)")
        # pair 3 (2 checkers against 2) is not held out; pair 0 is
        before = float(self.show("(abs (- (backgammon-endgame-network-chance net (backgammon-endgame-board endgames 1 1)) "
                                 "(vector-ref (endgame-set-chances endgames) 3)))"))
        self.run_lisp("(backgammon-learn-endgames! net endgames 600 0.1)")
        after = float(self.show("(abs (- (backgammon-endgame-network-chance net (backgammon-endgame-board endgames 1 1)) "
                                "(vector-ref (endgame-set-chances endgames) 3)))"))
        self.assertLess(after, before)
        self.assertLess(after, 0.1)

    def test_self_play_training_can_include_end_games(self):
        self.small_endgames()
        self.run_lisp("(define net (backgammon-new-net :hidden 4))")
        self.run_lisp("(define average (backgammon-train! net 1 :endgames endgames :endgame-steps 5))")
        self.assertGreater(float(self.show("average")), 1)

    def test_a_network_saved_and_loaded_gives_the_same_values(self):
        self.run_lisp("(define net (backgammon-new-net :hidden 4))")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            self.run_lisp('(backgammon-save-net net "%s")' % path)
            self.run_lisp('(define again (backgammon-load-net "%s"))' % path)
        self.assertShows("(backgammon-value again (backgammon-start))",
                         self.show("(backgammon-value net (backgammon-start))"))
        self.assertShows("(backgammon-net-hidden again)", "4")

    def test_a_file_that_is_not_a_network_or_has_the_old_outputs_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "other.txt")
            with open(path, "w") as f:
                f.write("(something else)")
            self.assertLispError('(backgammon-load-net "%s")' % path, "not a saved backgammon network")
            # a network with 2 hidden units for 216 inputs, but one output, as before the cube
            hidden = " ".join(["0.1"] * (2 * 216))
            one_output = os.path.join(d, "one_output.txt")
            with open(one_output, "w") as f:
                f.write("(backgammon-net 2 #(%s) #(1 2 3))" % hidden)
            self.assertLispError('(backgammon-load-net "%s")' % one_output, "wrong number of output weights")
            # a network trained on the 211 inputs of the old layout is refused
            old_inputs = " ".join(["0.1"] * (2 * 211))
            old = os.path.join(d, "old.txt")
            with open(old, "w") as f:
                f.write("(backgammon-net 2 #(%s) #(%s))" % (old_inputs, " ".join(["0.1"] * 15)))
            self.assertLispError('(backgammon-load-net "%s")' % old, "wrong number of hidden weights")

    def test_the_random_policy_never_doubles_and_always_takes(self):
        self.assertShows("((backgammon-policy-double (backgammon-random-policy)) (backgammon-start))", "#f")
        self.assertShows("((backgammon-policy-take (backgammon-random-policy)) (backgammon-start))", "#t")

    def test_a_policy_that_doubles_on_the_first_roll_wins_a_point_when_dropped(self):
        self.run_lisp("(define doubler (make-backgammon-policy :choose (lambda (b plays) (car plays))"
                      " :double (lambda (b) #t) :take (lambda (b) #f)))")
        self.run_lisp("(define dropper (make-backgammon-policy :choose (lambda (b plays) (car plays))"
                      " :double (lambda (b) #f) :take (lambda (b) #f)))")
        self.assertShows("(backgammon--play-game doubler dropper #t)", "1")      # A doubles, B drops: A wins 1
        self.assertShows("(backgammon--play-game dropper doubler #f)", "-1")     # B doubles, A drops: B wins 1

    def test_a_taken_double_doubles_the_points_of_the_game(self):
        self.run_lisp("(define taker (make-backgammon-policy :choose (lambda (b plays) (car plays))"
                      " :double (lambda (b) #t) :take (lambda (b) #t)))")
        points = int(self.show("(backgammon--play-game taker (backgammon-random-policy) #t)"))
        self.assertIn(abs(points), (2, 4, 6))          # the cube at 2, times a single game, gammon or backgammon

    def test_matches_score_the_points_a_policy_wins_and_the_heuristic_beats_random_play(self):
        self.run_lisp("(random-seed 2)")
        points = float(self.show("(backgammon-match (backgammon-heuristic-policy) (backgammon-random-policy) 8)"))
        self.assertGreater(points, 0)

    def test_the_player_can_quit_at_the_first_roll(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            self.run_lisp('(backgammon-save-net (backgammon-new-net :hidden 4) "%s")' % path)
            self.run_with_input('(play-backgammon :file "%s")' % path, ["", "quit"])
        self.assertIn("You rolled", self.printed())
        self.assertEqual(str(self.result), "quit")

    def test_a_move_that_is_not_one_of_the_plays_is_refused_and_asked_again(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            self.run_lisp('(backgammon-save-net (backgammon-new-net :hidden 4) "%s")' % path)
            self.run_with_input('(play-backgammon :file "%s")' % path, ["", "24/1", "quit"])
        self.assertIn("is not one of the plays", self.printed())

    def test_the_board_is_shown_after_the_computers_move_before_the_person_is_asked_to_double(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            self.run_lisp('(backgammon-save-net (backgammon-new-net :hidden 4) "%s")' % path)
            answers = iter(["", "quit"])
            shown_when_asked = []

            def fake_input(prompt=""):
                if "Double the cube" in prompt:
                    shown_when_asked.append(self.printed())
                return next(answers)

            with mock.patch("builtins.input", fake_input):
                self.run_lisp('(play-backgammon :file "%s" :human-first #f)' % path)
        text = shown_when_asked[0]
        self.assertIn("The computer plays", text)
        self.assertGreater(text.rindex("bar: X"), text.index("The computer plays"))

    def test_the_moves_the_cubes_and_the_result_can_be_logged_to_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            log = os.path.join(d, "log.txt")
            self.run_lisp('(backgammon-save-net (backgammon-new-net :hidden 4) "%s")' % path)
            self.run_with_input('(play-backgammon :file "%s" :human-first #f :log-file "%s")' % (path, log),
                                ["double", "quit"])
            lines = [line.split("\t") for line in open(log).read().splitlines()]
        kinds = [line[1] for line in lines]
        self.assertEqual(kinds[0], "game")
        self.assertEqual(lines[0][2], "computer first")
        self.assertIn("move", kinds)
        move = lines[kinds.index("move")]
        self.assertEqual(move[2:4], ["1", "computer"])
        self.assertEqual(len(move[6].split()), 26)               # the position before the move
        self.assertEqual(kinds[-1], "result")
        self.assertEqual(lines[-1][2:], ["quit", "0"])
        self.assertIn("cube", kinds)                              # the person doubled, and was taken or dropped

    def test_the_person_can_double_and_the_computer_takes_or_drops(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "net.txt")
            self.run_lisp('(backgammon-save-net (backgammon-new-net :hidden 4) "%s")' % path)
            self.run_with_input('(play-backgammon :file "%s")' % path, ["double", "quit"])
        text = self.printed()
        self.assertTrue("The computer take" in text or "The computer drops" in text, text)

    def test_the_person_is_asked_to_take_or_drop_until_they_answer(self):
        self.run_with_input("(backgammon--human-takes? 1)", ["maybe", "take"])
        self.assertTrue(self.result)                       # "maybe" is asked again, then "take"
        self.run_with_input("(backgammon--human-takes? 1)", ["drop"])
        self.assertFalse(self.result)
