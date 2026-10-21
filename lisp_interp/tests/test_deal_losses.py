"""lib/deal.lsp, losses and shortfalls. The collateral is given a vector of losses (balance written off, with no cash), and, for
shortfalls, interest that is less than the bonds are owed. Every deal here is worked out by hand: the coupon is 12% a year, 1% a month."""

import numpy as np

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make
from test_deal import DealTestCase


class LossTestCase(DealTestCase):

    def a_deal(self, principal, loss=None, interest=None, shortfalls=False, coupon=0.12, balance=None):
        """A deal, called deal, whose collateral pays this principal and loses this each month, with the balances that follow, and (unless it
        is given) interest at the coupon on them, as the variable pool."""
        loss = loss or [0.0] * len(principal)
        if balance is None:
            balance = [sum(principal) + sum(loss)]
        balances = [float(balance[0])]
        for p, l in zip(principal, loss):
            balances.append(balances[-1] - p - l)
        interest = interest or [b * coupon / 12 for b in balances[:-1]]
        self.run_lisp(hand_deal(balances, principal, interest=interest, coupon=coupon, loss=loss, shortfalls=shortfalls))

    def losses(self, name):
        return self.vector('(node-loss (get-node deal "%s"))' % name)

    def interest(self, name):
        return self.vector('(node-interest (get-node deal "%s"))' % name)

    def shortfall(self, name):
        return self.vector('(node-shortfall (get-node deal "%s"))' % name)

    def accrual(self, name):
        return self.vector('(node-accrual (get-node deal "%s"))' % name)

    PRINCIPAL = [20.0, 20.0, 20.0, 20.0, 17.0]
    LOSS = [0.0, 3.0, 0.0, 0.0, 0.0]


class TestLosses(LossTestCase):

    def test_the_last_bond_in_the_order_is_written_down_first(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("B2"), [0, 3, 0, 0, 0])
        np.testing.assert_allclose(self.losses("B1"), [0] * 5)
        np.testing.assert_allclose(self.losses("A"), [0] * 5)
        np.testing.assert_allclose(self.balance("B2"), [5, 5, 2, 2, 2, 0])
        np.testing.assert_allclose(self.balance("B1"), [15, 15, 15, 15, 15, 0])
        np.testing.assert_allclose(self.balance("A"), [80, 60, 40, 20, 0, 0])
        np.testing.assert_allclose(self.principal("A"), [20, 20, 20, 20, 0])
        np.testing.assert_allclose(self.principal("B1"), [0, 0, 0, 0, 15])
        np.testing.assert_allclose(self.principal("B2"), [0, 0, 0, 0, 2])             # (what is left of it)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_interest_is_on_the_balance_that_the_loss_has_reduced(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("B2"), [0.05, 0.05, 0.02, 0.02, 0.02], atol=1e-12)
        np.testing.assert_allclose(self.interest("A"), [0.8, 0.6, 0.4, 0.2, 0.0], atol=1e-12)

    def test_a_loss_that_is_more_than_the_last_bond_has_goes_on_to_the_one_before(self):
        self.a_deal([20.0, 20.0, 20.0, 20.0, 13.0], [0.0, 7.0, 0.0, 0.0, 0.0])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("B2"), [0, 5, 0, 0, 0])
        np.testing.assert_allclose(self.losses("B1"), [0, 2, 0, 0, 0])
        np.testing.assert_allclose(self.losses("A"), [0] * 5)
        np.testing.assert_allclose(self.balance("B1"), [15, 15, 13, 13, 13, 0])
        self.assertShows("(deal-check deal)", "#t")

    def a_and_b_groups(self, a_losses="'pro-rata"):
        self.a_deal([20.0, 20.0, 15.0, 10.0, 10.0], [0.0, 25.0, 0.0, 0.0, 0.0])
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))
                         (deal-sequential! deal "A" '(("A1" 50.0) ("A2" 30.0)) :losses %s)
                         (deal-sequential! deal "B" '(("B1" 15.0) ("B2" 5.0)))
                         (deal-run! deal)''' % a_losses)

    def test_the_b_bonds_are_written_down_from_the_bottom_up_and_then_the_a_bonds_share_by_what_they_have_left(self):
        self.a_and_b_groups()
        np.testing.assert_allclose(self.losses("B2"), [0, 5, 0, 0, 0])
        np.testing.assert_allclose(self.losses("B1"), [0, 15, 0, 0, 0])
        np.testing.assert_allclose(self.losses("B"), [0, 20, 0, 0, 0])
        np.testing.assert_allclose(self.losses("A"), [0, 5, 0, 0, 0])                # (the 5 that is left)
        # A1 has 10 left that month, after its principal, and A2 30: shared 1 to 3
        np.testing.assert_allclose(self.losses("A1"), [0, 1.25, 0, 0, 0])
        np.testing.assert_allclose(self.losses("A2"), [0, 3.75, 0, 0, 0])
        np.testing.assert_allclose(self.balance("A1"), [50, 30, 8.75, 0, 0, 0])
        np.testing.assert_allclose(self.balance("A2"), [30, 30, 26.25, 20, 10, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_a_bonds_are_paid_principal_in_order_though_they_share_the_loss(self):
        self.a_and_b_groups()
        np.testing.assert_allclose(self.principal("A1"), [20, 20, 8.75, 0, 0])
        np.testing.assert_allclose(self.principal("A2"), [0, 0, 6.25, 10, 10])

    def test_a_split_made_with_another_rule_divides_the_loss_by_it(self):
        self.a_and_b_groups(a_losses="'forward")
        np.testing.assert_allclose(self.losses("A1"), [0, 5, 0, 0, 0])               # (the first first)
        np.testing.assert_allclose(self.losses("A2"), [0] * 5)
        self.assertShows("(deal-check deal)", "#t")
        self.a_and_b_groups(a_losses="'reverse")
        np.testing.assert_allclose(self.losses("A2"), [0, 5, 0, 0, 0])

    def test_a_pro_rata_split_divides_the_loss_pro_rata_unless_it_is_made_with_another_rule(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-pro-rata! deal "POOL" '(("X" 60.0) ("Y" 40.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("X"), [0, 1.8, 0, 0, 0])                # (36 and 24 left after the principal: 3 x 36 / 60)
        np.testing.assert_allclose(self.losses("Y"), [0, 1.2, 0, 0, 0])
        self.assertShows("(deal-check deal)", "#t")
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-pro-rata! deal "POOL" '(("X" 60.0) ("Y" 40.0)) :losses 'reverse) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("Y"), [0, 3, 0, 0, 0])

    def test_a_floater_and_inverse_floater_share_a_loss_pro_rata_and_stay_in_proportion(self):
        self.a_deal(self.PRINCIPAL, self.LOSS, coupon=0.06)
        self.run_lisp('(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.1 :margin 0.01) (deal-run! deal :index 0.03)')
        self.assertAlmostEqual(self.losses("F")[1], 1.8)
        self.assertAlmostEqual(self.losses("I")[1], 1.2)
        floater, inverse = self.balance("F")[:-1], self.balance("I")[:-1]
        np.testing.assert_allclose(floater / inverse, [1.5] * 5)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_pac_and_its_companion_are_written_down_the_companion_first(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(defstruct (given-pac-split (:include pac-split)))
                         (defmethod calculate-sizes ((split given-pac-split) deal parent) '())
                         (deal-add-tranche! deal "PAC" 60.0) (deal-add-tranche! deal "COMP" 40.0)
                         (deal-add-split! deal "POOL" (make-given-pac-split :children '("PAC" "COMP") :low-psa 100 :high-psa 300
                                                      :schedule (vector 60.0 40.0 20.0 0.0 0.0 0.0)))
                         (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("COMP"), self.LOSS)
        np.testing.assert_allclose(self.losses("PAC"), [0] * 5)
        np.testing.assert_allclose(self.balance("PAC"), [60, 40, 20, 0, 0, 0])
        np.testing.assert_allclose(self.balance("COMP"), [40, 40, 37, 37, 17, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_an_io_and_a_po_the_po_is_written_down_and_the_io_follows_it(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp('(deal-io-po! deal "POOL" "IO" "PO") (deal-run! deal)')
        np.testing.assert_allclose(self.losses("PO"), self.LOSS)
        np.testing.assert_allclose(self.losses("IO"), [0] * 5)
        np.testing.assert_allclose(self.balance("IO"), self.balance("PO"))
        np.testing.assert_allclose(self.balance("PO"), [100, 80, 57, 37, 17, 0])
        np.testing.assert_allclose(self.interest("IO"), [1.0, 0.8, 0.57, 0.37, 0.17], atol=1e-12)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_z_bond_at_the_end_of_the_order_is_written_down_first_and_what_it_has_left_includes_its_accrual(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("Z"), self.LOSS)
        np.testing.assert_allclose(self.losses("A"), [0] * 5)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_pacs_size_is_of_the_cash_flows_of_the_collateral_without_its_losses(self):
        self.run_lisp("(define a %s) (define b %s)" % (psa_deal("a", 100000000.0, 6.0, psa=200), psa_deal("b", 100000000.0, 6.0, psa=200)))
        self.run_lisp('''(define loss (make-vector 360 0.0))
                         (vector-set! loss 5 1000000.0)
                         (node-loss-set! (get-node b "POOL") loss)
                         (deal-pac! a "POOL" "PAC" "COMP" 100 300)
                         (deal-pac! b "POOL" "PAC" "COMP" 100 300)''')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node a "PAC")) 0)'),
                               self.run_lisp('(vector-ref (node-balance (get-node b "PAC")) 0)'), places=6)

    def test_a_loss_is_of_what_a_bond_has_left_including_what_a_z_bond_accrues_that_month(self):
        self.a_deal([20.0, 19.5], [60.5, 0.0])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("Z"), [60.5, 0.0])                    # (its 60, and the 0.6 it accrued, less 0.1)
        np.testing.assert_allclose(self.losses("A"), [0.0, 0.0])
        np.testing.assert_allclose(self.balance("Z"), [60, 0.1, 0.0], atol=1e-12)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_losses_of_the_collateral_do_not_change_what_a_pac_is_sized_from(self):
        self.run_lisp("(define a %s) (define b %s)" % (psa_deal("a", 100000000.0, 6.0, psa=200), psa_deal("b", 100000000.0, 6.0, psa=200)))
        self.run_lisp('''(define loss (make-vector 360 0.0))
                         (vector-set! loss 30 20000000.0)
                         (node-loss-set! (get-node b "POOL") loss)
                         (deal-pro-rata! a "POOL" '(("X" 50000000.0) ("Y" 50000000.0)) :losses 'reverse)
                         (deal-pro-rata! b "POOL" '(("X" 50000000.0) ("Y" 50000000.0)) :losses 'reverse)
                         (deal-pac! a "X" "PAC" "COMP" 100 300)
                         (deal-pac! b "X" "PAC" "COMP" 100 300)''')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node a "PAC")) 0)'),
                               self.run_lisp('(vector-ref (node-balance (get-node b "PAC")) 0)'), places=6)

    def test_the_losses_are_in_a_table(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.vector('(table-column (deal-loss-table deal) "B2")'), [0, 3, 0, 0, 0])
        np.testing.assert_allclose(self.vector('(table-column (deal-loss-table deal) "POOL")'), self.LOSS)

    def test_a_deal_without_losses_has_none_and_deal_check_finds_losses_that_were_not_divided(self):
        self.a_deal([25.0] * 4)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 60.0) ("B" 40.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.losses("B"), [0] * 4)
        self.assertShows("(deal-check deal)", "#t")
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        self.run_lisp('(vector-increment! (node-loss (get-node deal "B1")) 3 1.0)')
        self.assertLispError("(deal-check deal)", "the children of POOL were written down by 1.0 in month 3, and POOL by 0.0")

    def test_what_losses_wont_take(self):
        self.a_deal(self.PRINCIPAL, self.LOSS)
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)) :losses 'sideways)""", "the loss rule of a split is reverse, forward or pro-rata, not sideways")
        self.assertShows("(deal-names deal)", '("POOL")')
        self.assertLispError("""(deal-pro-rata! deal "POOL" '(("A" 80.0) ("B" 20.0)) :losses 5)""", "the loss rule of a split")

    def test_a_loss_that_the_bonds_have_not_enough_left_to_take_is_an_error(self):
        self.a_deal([20.0, 20.0], [5.0, 0.0], balance=[40.0])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 30.0) ("B" 10.0)))""")
        self.run_lisp('(vector-set! (node-loss pool) 0 50.0)')                         # (more than the pool had)
        self.assertLispError("(deal-run! deal)", "was allocated a loss of 30 that its children, which have too little left, cannot take, in month 0")


class TestShortfalls(LossTestCase):

    POOL_PRINCIPAL = [20.0] * 5

    def a_short_deal(self, interest, shortfalls=True):
        self.a_deal(self.POOL_PRINCIPAL, None, interest, shortfalls=shortfalls)

    def test_a_bond_that_is_not_paid_what_it_is_owed_has_a_shortfall_that_is_carried_with_interest_and_paid_when_there_is_cash(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("A"), [0.8, 0.6, 0.4, 0.2, 0.0], atol=1e-12)         # (the senior bond is paid first)
        np.testing.assert_allclose(self.interest("B"), [0.1, 0.2, 0.30201, 0.2, 0.2], atol=1e-12)
        np.testing.assert_allclose(self.shortfall("B"), [0.1, 0.101, 0, 0, 0], atol=1e-12)           # (0.2 - 0.1, then 0.2 + 0.1 x 1.01 - 0.2)
        np.testing.assert_allclose(self.shortfall("A"), [0] * 5)
        self.assertShows("(deal-check deal)", "#t")

    def test_without_the_switch_a_shortfall_is_an_error(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2], shortfalls=False)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))""")
        self.assertLispError("(deal-run! deal)", "was paid 0.9 of interest in month 0, and its children are owed 1 (there is not enough)")

    def test_interest_that_is_over_is_an_error_with_the_switch_too(self):
        self.a_short_deal([1.5, 0.8, 0.6, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0)))""")
        self.assertLispError("(deal-run! deal)", "(some is left over)")

    def test_a_pro_rata_split_shares_a_shortfall_by_what_each_is_owed(self):
        self.a_short_deal([0.9, 0.8, 0.6, 0.4, 0.2])
        self.run_lisp("""(deal-pro-rata! deal "POOL" '(("A" 60.0) ("B" 40.0))) (deal-run! deal)""")
        self.assertAlmostEqual(self.interest("A")[0], 0.54)
        self.assertAlmostEqual(self.interest("B")[0], 0.36)
        self.assertAlmostEqual(self.shortfall("A")[0], 0.06)
        self.assertAlmostEqual(self.shortfall("B")[0], 0.04)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_shortfalls_of_bonds_under_a_node_that_is_divided_are_those_of_the_bonds(self):
        self.a_short_deal([0.5, 0.8, 0.6, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("X" 70.0) ("Y" 30.0)))
                         (deal-sequential! deal "X" '(("X1" 40.0) ("X2" 30.0)))
                         (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("X"), [0.5, 0.7, 0.6, 0.4, 0.2][0:1] + list(self.interest("X")[1:]))
        self.assertAlmostEqual(self.interest("X1")[0], 0.4)
        self.assertAlmostEqual(self.interest("X2")[0], 0.1)
        self.assertAlmostEqual(self.shortfall("X2")[0], 0.2)                           # (0.3 owed, 0.1 paid)
        self.assertAlmostEqual(self.shortfall("Y")[0], 0.3)                            # (nothing left for it)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_z_bond_accrues_only_what_there_is_cash_for_and_the_rest_is_its_shortfall(self):
        self.a_short_deal([0.5, 0.8, 0.6, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        self.assertAlmostEqual(self.interest("A")[0], 0.4)
        self.assertAlmostEqual(self.accrual("Z")[0], 0.1)                              # (the cash that was left)
        self.assertAlmostEqual(self.shortfall("Z")[0], 0.5)
        self.assertAlmostEqual(self.principal("A")[0], 20.1)                           # (the pool's 20 and what Z accrued)
        self.assertAlmostEqual(self.balance("Z")[1], 60.1)
        self.assertShows("(deal-check deal)", "#t")

    def test_losses_and_shortfalls_together(self):
        self.a_deal(self.PRINCIPAL, self.LOSS, [0.9, 0.8, 0.6, 0.37, 0.17], shortfalls=True)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B1" 15.0) ("B2" 5.0))) (deal-run! deal)""")
        self.assertShows("(deal-check deal)", "#t")
        np.testing.assert_allclose(self.losses("B2"), self.LOSS)
        self.assertGreater(self.shortfall("B2").max(), 0)

    def test_deal_check_finds_a_shortfall_that_was_not_carried_as_it_should_be(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal)""")
        self.run_lisp('(vector-set! (node-shortfall (get-node deal "B")) 0 0.5)')
        self.assertLispError("(deal-check deal)", "B was paid")

    def test_the_shortfalls_are_in_a_table_and_a_deal_without_the_switch_has_none(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.vector('(table-column (deal-shortfall-table deal) "B")'), [0.1, 0.101, 0, 0, 0], atol=1e-12)
        self.a_deal(self.POOL_PRINCIPAL)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.shortfall("B"), [0] * 5)

    def test_a_bond_that_is_divided_after_a_run_has_no_shortfall_left_from_it(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal)""")
        self.assertGreater(self.shortfall("B").max(), 0)
        self.run_lisp("""(deal-sequential! deal "B" '(("B1" 12.0) ("B2" 8.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.shortfall("B"), [0] * 5)
        self.assertGreater(self.shortfall("B1").max() + self.shortfall("B2").max(), 0)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_shortfalls_of_the_deal_are_reset_when_it_is_run_again(self):
        self.a_short_deal([0.9, 0.8, 0.70201, 0.4, 0.2])
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 80.0) ("B" 20.0))) (deal-run! deal) (deal-run! deal)""")
        np.testing.assert_allclose(self.shortfall("B"), [0.1, 0.101, 0, 0, 0], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
