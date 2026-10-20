"""lib/deal.lsp: Z (accrual) bonds, accretion directed bonds, and interest-only and principal-only bonds. The small deals are worked out
by hand: the collateral pays 20 or 25 of principal a month, and interest at 12% a year, 1% a month, on its balance."""

import numpy as np

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase
from test_deal_interest import InterestTestCase


class StripsTestCase(InterestTestCase):

    def deal_of(self, amount, months=5):
        self.a_deal(coupon=0.12, months=months, amount=amount)

    def accrual(self, name):
        return self.vector('(node-accrual (get-node deal "%s"))' % name)


class TestZBonds(StripsTestCase):

    def test_a_z_bond_accrues_its_interest_and_what_it_accrues_is_paid_as_principal_to_the_bond_ahead_of_it(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        np.testing.assert_allclose(self.interest("A"), [0.4, 0.194, 0, 0, 0], atol=1e-12)
        np.testing.assert_allclose(self.interest("Z"), [0] * 5)                             # (no cash interest)
        np.testing.assert_allclose(self.accrual("Z"), [0.6, 0.606, 0.6, 0.4, 0.2], atol=1e-12)
        np.testing.assert_allclose(self.principal("A"), [20.6, 19.4, 0, 0, 0], atol=1e-12)  # (the pool's 20 and the 0.6 that Z accrued)
        np.testing.assert_allclose(self.principal("Z"), [0, 1.206, 20.6, 20.4, 20.2], atol=1e-12)
        np.testing.assert_allclose(self.balance("A"), [40, 19.4, 0, 0, 0, 0], atol=1e-12)
        np.testing.assert_allclose(self.balance("Z"), [60, 60.6, 60.0, 40, 20, 0], atol=1e-12)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_parents_balance_and_interest_are_not_changed_by_what_its_z_bond_accrues(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        np.testing.assert_allclose(self.balance("POOL"), [100, 80, 60, 40, 20, 0])
        np.testing.assert_allclose(self.balance("A") + self.balance("Z"), self.balance("POOL"), atol=1e-12)
        np.testing.assert_allclose(self.interest("A") + self.accrual("Z"), self.interest("POOL"), atol=1e-12)

    def test_the_z_bond_is_owed_what_it_accrues_this_month_so_it_can_be_paid_its_own_accrual(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        self.assertAlmostEqual(self.principal("Z")[2], 20.6)             # (A is paid off: the pool's 20 and its own 0.6)
        self.assertAlmostEqual(self.balance("Z")[-1], 0.0)

    def test_the_accretion_directed_bond_is_paid_what_the_z_bond_accrues_before_the_order(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 30.0) ("B" 30.0) ("Z" 40.0 z)) :accretion-to "B") (deal-run! deal)""")
        self.assertAlmostEqual(self.principal("B")[0], 0.4)               # (what Z accrued, though A is first in the order)
        self.assertAlmostEqual(self.principal("A")[0], 20.0)
        self.assertShows("(deal-check deal)", "#t")
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 30.0) ("B" 30.0) ("Z" 40.0 z))) (deal-run! deal)""")
        self.assertAlmostEqual(self.principal("A")[0], 20.4)              # (without it, all in the order)
        self.assertAlmostEqual(self.principal("B")[0], 0.0)

    def test_a_z_bond_can_be_anywhere_in_the_order_and_there_can_be_more_than_one(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 20.0) ("Z1" 30.0 z) ("B" 25.0) ("Z2" 25.0 z))) (deal-run! deal)""")
        self.assertShows("(deal-check deal)", "#t")
        for name in ("A", "Z1", "B", "Z2"):
            self.assertAlmostEqual(self.balance(name)[-1], 0.0, msg=name)
        self.assertGreater(self.accrual("Z1").sum(), 0)
        self.assertGreater(self.accrual("Z2").sum(), 0)

    def test_the_children_of_a_z_bonds_parent_and_siblings_work_as_usual(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("X" 70.0) ("Y" 30.0)))
                         (deal-sequential! deal "X" '(("A" 30.0) ("Z" 40.0 z)))
                         (deal-pro-rata! deal "Y" '(("Y1" 10.0) ("Y2" 20.0)))
                         (deal-run! deal)""")
        self.assertShows("(deal-check deal)", "#t")

    def test_the_accruals_are_in_a_table(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        np.testing.assert_allclose(self.vector('(table-column (deal-accrual-table deal) "Z")'), [0.6, 0.606, 0.6, 0.4, 0.2], atol=1e-12)

    def test_deal_check_finds_a_z_bond_that_was_not_accrued_as_owed(self):
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z))) (deal-run! deal)""")
        self.run_lisp('(vector-increment! (node-accrual (get-node deal "Z")) 1 0.1)')
        self.assertLispError("(deal-check deal)", "the children of POOL were paid")

    def test_a_pac_is_sized_from_what_its_parent_is_paid_with_the_accrual_of_a_z_bond_beside_it(self):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 300000000.0 6.0 :term 360 :psa 200))
                         (define deal (start-deal "pac and z" pool))
                         (deal-sequential! deal "POOL" (list (list "Q" 200000000.0) (list "Z" 100000000.0 'z)))
                         (deal-pac! deal "Q" "PQ" "CQ" 100 300)
                         (deal-run! deal)''')
        self.assertShows("(deal-check deal)", "#t")
        schedule = self.vector('(pac-split-schedule (node-split (get-node deal "Q")))')
        np.testing.assert_allclose(self.balance("PQ"), schedule, atol=1e-4)        # (on schedule at 200: the accrual is in the sizes)

    def test_the_principal_at_another_speed_leaves_the_accruals_of_the_deal_as_they_were(self):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 300000000.0 6.0 :term 360 :psa 200))
                         (define deal (start-deal "z" pool))
                         (deal-sequential! deal "POOL" (list (list "Q" 200000000.0) (list "Z" 100000000.0 'z)))
                         (deal-run! deal)''')
        before = {n: (self.accrual(n).copy(), self.principal(n).copy(), self.interest(n).copy(), self.balance(n).copy())
                  for n in ("POOL", "Q", "Z")}
        self.run_lisp('(deal-principal-at deal "Q" 400)')
        for name, vectors in before.items():
            for was, now in zip(vectors, (self.accrual(name), self.principal(name), self.interest(name), self.balance(name))):
                np.testing.assert_array_equal(now, was)

    def test_what_a_z_bond_wont_do(self):
        self.deal_of(20.0)
        self.assertLispError("""(deal-pro-rata! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)))""", "Z is a Z bond, which can only be the child of a sequential split")
        self.assertShows("(deal-names deal)", '("POOL")')                                  # (nothing was added)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)))""")
        self.assertLispError("""(deal-sequential! deal "Z" '(("Z1" 30.0) ("Z2" 30.0)))""", "Z is a Z bond, which is not divided")
        self.assertLispError("""(deal-io-po! deal "Z" "IO" "PO")""", "Z is a Z bond, which is not divided")
        self.assertLispError("""(deal-pro-rata! deal "Z" '(("Z1" 30.0) ("Z2" 30.0)))""", "Z is a Z bond, which is not divided")

    def test_the_accretion_must_be_directed_to_a_bond_that_is_not_a_z_bond(self):
        self.deal_of(20.0)
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)) :accretion-to "B")""", "directed to B, which is not one of the children")
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)) :accretion-to "Z")""", "which is a Z bond")
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_child_is_written_with_a_z_or_not(self):
        self.deal_of(20.0)
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 40.0) ("B" 60.0 "z")))""", "a child is (name balance), or (name balance z)")
        self.assertLispError("""(deal-sequential! deal "POOL" '(("A" 40.0 z z) ("B" 60.0)))""", "a child is (name balance)")


class TestInterestOnlyAndPrincipalOnly(StripsTestCase):

    def a_strip(self, **options):
        self.deal_of(25.0, months=4)
        words = "".join(" :%s %r" % (k.replace("_", "-"), v) for k, v in options.items())
        self.run_lisp('(deal-io-po! deal "POOL" "IO" "PO"%s) (deal-run! deal)' % words)

    def test_the_po_is_paid_all_the_principal_and_the_io_the_interest_on_a_notional_balance_that_follows_it(self):
        self.a_strip()
        np.testing.assert_allclose(self.principal("PO"), [25] * 4)
        np.testing.assert_allclose(self.principal("IO"), [0] * 4)
        np.testing.assert_allclose(self.balance("PO"), [100, 75, 50, 25, 0])
        np.testing.assert_allclose(self.balance("IO"), [100, 75, 50, 25, 0])               # (the notional balance)
        np.testing.assert_allclose(self.interest("IO"), [1.0, 0.75, 0.5, 0.25])            # (the whole coupon, 1% of the notional)
        np.testing.assert_allclose(self.interest("PO"), [0] * 4)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_io_and_the_po_are_both_as_big_as_the_parent_and_the_io_is_a_notional_bond_that_follows_the_po(self):
        self.a_strip()
        self.assertShows('(node-notional-flag (get-node deal "IO"))', "#t")
        self.assertShows('(node-notional-flag (get-node deal "PO"))', "#f")
        self.assertShows('(node-follows (get-node deal "IO"))', '"PO"')
        self.assertShows("(deal-leaves deal)", '("IO" "PO")')

    def test_a_partial_strip_pays_the_io_its_coupon_and_the_po_the_rest_of_the_parents(self):
        self.a_strip(io_coupon=0.05)
        np.testing.assert_allclose(self.rates("IO"), [0.05] * 4)
        np.testing.assert_allclose(self.rates("PO"), [0.07] * 4)
        np.testing.assert_allclose(self.interest("IO"), np.array([100, 75, 50, 25]) * 0.05 / 12)
        np.testing.assert_allclose(self.interest("PO"), np.array([100, 75, 50, 25]) * 0.07 / 12)
        self.assertShows("(deal-check deal)", "#t")

    def test_the_io_of_a_floater_floats(self):
        self.a_deal(coupon=0.06, months=4, amount=25.0)
        self.run_lisp('''(deal-floater-inverse! deal "POOL" "F" "I" :cap 0.10 :margin 0.01)
                         (deal-io-po! deal "F" "FIO" "FPO")
                         (deal-run! deal :index 0.03)''')
        np.testing.assert_allclose(self.rates("FIO"), [0.04] * 4)
        np.testing.assert_allclose(self.rates("FPO"), [0.0] * 4)
        self.assertShows("(deal-check deal)", "#t")

    def test_a_po_can_be_divided_in_order_and_an_io_in_parts_of_its_notional(self):
        self.a_strip()
        self.run_lisp("""(deal-sequential! deal "PO" '(("P1" 60.0) ("P2" 40.0)))
                         (deal-sequential! deal "IO" '(("IO1" 40.0) ("IO2" 60.0)))
                         (deal-run! deal)""")
        np.testing.assert_allclose(self.principal("P1"), [25, 25, 10, 0])
        np.testing.assert_allclose(self.principal("P2"), [0, 0, 15, 25])
        np.testing.assert_allclose(self.balance("IO1"), [40, 30, 20, 10, 0])                  # (40% of the notional of the IO)
        np.testing.assert_allclose(self.balance("IO2"), [60, 45, 30, 15, 0])
        np.testing.assert_allclose(self.interest("IO1"), [0.4, 0.3, 0.2, 0.1])
        for name in ("IO1", "IO2"):
            self.assertShows('(node-notional-flag (get-node deal "%s"))' % name, "#t")
            np.testing.assert_allclose(self.principal(name), [0] * 4)
        self.assertShows("(deal-check deal)", "#t")

    def test_an_io_can_be_divided_in_proportion_too(self):
        self.a_strip()
        self.run_lisp("""(deal-pro-rata! deal "IO" '(("IO1" 30.0) ("IO2" 70.0))) (deal-run! deal)""")
        np.testing.assert_allclose(self.balance("IO2"), [70, 52.5, 35, 17.5, 0])
        self.assertShows("(deal-check deal)", "#t")

    def test_the_collateral_a_pac_and_a_floater_can_each_be_divided_into_an_io_and_a_po(self):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 200000000.0 6.0 :term 360 :psa 200))
                         (define deal (start-deal "strips" pool))
                         (deal-pac! deal "POOL" "PAC" "COMP" 100 300)
                         (deal-io-po! deal "PAC" "PIO" "PPO")
                         (deal-io-po! deal "COMP" "CIO" "CPO")
                         (deal-run! deal)''')
        self.assertShows("(deal-check deal)", "#t")
        total = self.interest("PIO") + self.interest("CIO")
        np.testing.assert_allclose(total, self.interest("POOL"), rtol=1e-10, atol=1e-6)
        self.run_lisp('(define whole (start-deal "whole" (collateral-from-psa "P" 100000000.0 6.0 :term 360 :psa 100))) '
                      '(deal-io-po! whole "P" "IO" "PO") (deal-run! whole)')
        self.assertShows("(deal-check whole)", "#t")

    def test_deal_check_finds_a_notional_bond_that_has_principal_or_is_not_what_it_follows(self):
        self.a_strip()
        self.run_lisp('(vector-set! (node-balance (get-node deal "IO")) 2 49.0)')
        self.assertLispError("(deal-check deal)", "the notional balance of IO is 49.0 in month 2")
        self.run_lisp("(deal-run! deal)")
        self.run_lisp('(vector-increment! (node-principal (get-node deal "IO")) 1 1.0) (vector-increment! (node-principal (get-node deal "PO")) 1 -1.0)')
        self.assertLispError("(deal-check deal)", "IO is a notional bond, and was paid 1.0 of principal in month 1")

    def test_what_an_io_po_split_wont_divide(self):
        self.a_strip()
        self.assertLispError('(deal-io-po! deal "IO" "X" "Y")', "IO is an interest-only bond, which is not divided into an IO and a PO")
        self.assertLispError('(deal-io-po! deal "PO" "X" "Y")', "PO is a principal-only bond, which is not divided into an IO and a PO")
        self.assertShows("(deal-names deal)", '("POOL" "IO" "PO")')
        self.deal_of(20.0)
        self.run_lisp("""(deal-sequential! deal "POOL" '(("A" 40.0) ("Z" 60.0 z)))""")
        self.assertLispError('(deal-io-po! deal "Z" "X" "Y")', "Z is a Z bond, which is not divided")

    def test_an_io_or_a_po_is_not_divided_into_a_z_bond(self):
        self.a_strip()
        self.assertLispError("""(deal-sequential! deal "PO" '(("P1" 60.0) ("Z" 40.0 z)))""", "PO is an IO or a PO, which is not divided into a Z bond")
        self.assertLispError("""(deal-sequential! deal "IO" '(("I1" 60.0) ("Z" 40.0 z)))""", "IO is an IO or a PO, which is not divided into a Z bond")
        self.assertShows("(deal-names deal)", '("POOL" "IO" "PO")')

    def test_a_hand_made_io_po_split_needs_the_io_to_follow_the_po(self):
        self.deal_of(25.0, months=4)
        self.run_lisp('(deal-add-tranche! deal "IO" 100.0) (deal-add-tranche! deal "PO" 100.0)')
        self.assertLispError("""(deal-add-split! deal "POOL" (make-io-po-split :children '("IO" "PO")))""", "the IO of an IO/PO split is a notional bond that follows the PO")
        self.run_lisp('(deal-forget-node! deal "IO") (deal-forget-node! deal "PO")')
        self.run_lisp('(deal-add-tranche! deal "IO" 100.0 :notional #t :follows "PO") (deal-add-tranche! deal "PO" 100.0)')
        self.run_lisp("""(deal-add-split! deal "POOL" (make-io-po-split :children '("IO" "PO")))""")
        self.run_lisp("(deal-run! deal)")
        self.assertShows("(deal-check deal)", "#t")


class TestAZAndAStripTogether(StripsTestCase):

    def test_a_po_split_in_order_and_a_z_bond_beside_it(self):
        self.run_lisp('''(define pool (collateral-from-psa "POOL" 300000000.0 6.0 :term 360 :psa 150))
                         (define deal (start-deal "z and strip" pool))
                         (deal-sequential! deal "POOL" (list (list "X" 200000000.0) (list "Z" 100000000.0 'z)))
                         (deal-io-po! deal "X" "XIO" "XPO")
                         (deal-sequential! deal "XPO" (list (list "S1" 120000000.0) (list "S2" 80000000.0)))
                         (deal-run! deal)''')
        self.assertShows("(deal-check deal)", "#t")
        total = sum(self.principal(n) for n in ("S1", "S2", "Z"))
        accrued = self.accrual("Z")
        np.testing.assert_allclose(total, self.principal("POOL") + accrued, rtol=1e-12, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
