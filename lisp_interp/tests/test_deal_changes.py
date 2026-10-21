"""Changing the split of a node of a deal, and taking one away (lib/deal.lsp: deal-replace-split!, deal-trial-of-plan,
deal-delete-split!). A change is checked against a deal made in one go with the new inputs: it must be the same deal, node
for node, so that what is below the split that was changed has been worked out again, to the leaves."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class DealChangesCase(LispTestCase):

    LIBRARY = '''
      (load "deal.lsp")

      (define (a-deal name) (new-deal name :collateral '((100000000.0 6.5 6.5 360)) :speed (prepayment-speed 'psa 150)))

      ; POOL -> A, B;  A -> floater AF and inverse AI;  AF -> PAC AP and companion AC
      (define (make-demo &key (a 60000000.0) (b 40000000.0) (cap 0.095))
        (let ((deal (a-deal "Demo")))
          (deal-sequential! deal "POOL" (list (list "A" a) (list "B" b)))
          (deal-floater-inverse! deal "A" "AF" "AI" :cap cap)
          (deal-pac! deal "AF" "AP" "AC" 100 300)
          deal))

      ; everything that a split decides, for every node, to the cent and a billionth: what has to be the same
      (define (signature deal)
        (map (lambda (name)
               (let ((node (get-node deal name)))
                 (list name
                       (round (* 100 (vector-ref (node-balance node) 0)))
                       (if (null? (node-coupon node))
                           '()
                           (list (round (* 1e9 ((node-coupon node) 0.02))) (round (* 1e9 ((node-coupon node) 0.07)))))
                       (if (null? (node-split node)) '() (list (split-label (node-split node)) (split-children (node-split node))))
                       (round (* 1e9 (node-share node)))
                       (node-notional-flag node)
                       (node-z-flag node))))
             (deal-names deal)))

      (define (run-and-check deal) (deal-run! deal :index 0.04) (deal-check deal))
      (define (principal-sum deal name) (vector-sum (node-principal (get-node deal name))))
      '''

    def setUp(self):
        super().setUp()
        self.run_lisp(self.LIBRARY)

    def signature(self, deal="deal"):
        return self.show("(signature %s)" % deal)


class TestReplacingASplit(DealChangesCase):

    def test_a_change_at_the_top_is_a_change_all_the_way_down(self):
        self.run_lisp('''(define deal (make-demo))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 70000000.0) ("B" 30000000.0))))
                         (define direct (make-demo :a 70000000.0 :b 30000000.0))''')
        self.assertEqual(self.signature("deal"), self.signature("direct"))
        self.assertShows("(list (run-and-check deal) (run-and-check direct))", "(#t #t)")
        for name in ("AF", "AI", "AP", "AC", "B"):                  # (the run is the same too, so the PAC has its new schedule)
            self.assertAlmostEqual(self.run_lisp('(principal-sum deal "%s")' % name), self.run_lisp('(principal-sum direct "%s")' % name), places=4)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "AF")) 0)'), 70000000.0 * 0.065 / 0.095, places=4)

    def test_a_change_of_the_cap_of_a_floater_changes_its_children_and_theirs(self):
        self.run_lisp('''(define deal (make-demo))
                         (deal-replace-split! deal "A" (floater-inverse-plan "AF" "AI" :cap 0.10))
                         (define direct (make-demo :cap 0.10))''')
        self.assertEqual(self.signature("deal"), self.signature("direct"))
        self.assertShows("(list (run-and-check deal) (run-and-check direct))", "(#t #t)")
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "AF")) 0)'), 60000000.0 * 0.065 / 0.10, places=4)
        self.assertAlmostEqual(self.run_lisp('(principal-sum deal "AP")'), self.run_lisp('(principal-sum direct "AP")'), places=4)

    def test_a_tranche_that_stays_is_the_same_node_with_what_is_under_it(self):
        self.run_lisp('''(define deal (make-demo))
                         (define af (get-node deal "AF"))
                         (define ap (get-node deal "AP"))
                         (deal-replace-split! deal "A" (floater-inverse-plan "AF" "AI" :cap 0.10))''')
        self.assertShows('(eq? af (get-node deal "AF"))', "#t")
        self.assertShows('(eq? ap (get-node deal "AP"))', "#t")
        self.assertShows('(split-children (node-split (get-node deal "AF")))', '("AP" "AC")')

    def test_the_split_can_be_of_another_kind_with_the_same_children(self):
        self.run_lisp('''(define deal (make-demo))
                         (define companion (- (vector-ref (node-balance (get-node deal "AF")) 0) 20000000.0))
                         (deal-replace-split! deal "AF" (pro-rata-plan (list (list "AP" 20000000.0) (list "AC" companion))))''')
        self.assertShows('(split-label (node-split (get-node deal "AF")))', '"pro rata"')
        self.assertShows("(run-and-check deal)", "#t")

    def test_tranches_can_be_added_and_left_out_when_they_have_nothing_under_them(self):
        self.run_lisp('''(define deal (make-demo))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 50000000.0) ("B" 30000000.0) ("C" 20000000.0))))''')
        self.assertShows("(deal-names deal)", '("POOL" "A" "B" "AF" "AI" "AP" "AC" "C")')
        self.assertShows('(split-children (node-split (get-node deal "POOL")))', '("A" "B" "C")')
        self.assertShows("(run-and-check deal)", "#t")
        self.run_lisp('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("B" 40000000.0))))''')
        self.assertShows("(deal-names deal)", '("POOL" "A" "B" "AF" "AI" "AP" "AC")')
        self.assertEqual(self.signature("deal"), self.signature("(make-demo)"))

    def test_a_tranche_can_be_renamed_if_it_has_nothing_under_it(self):
        self.run_lisp('''(define deal (make-demo))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("BB" 40000000.0))))''')
        self.assertShows("(deal-names deal)", '("POOL" "A" "AF" "AI" "AP" "AC" "BB")')

    def test_a_tranche_that_has_a_split_cannot_be_left_out(self):
        self.run_lisp("(define deal (make-demo))")
        before = self.signature()
        self.assertLispError('''(deal-replace-split! deal "POOL" (sequential-plan '(("B" 100000000.0))))''',
                             "A is divided, so it cannot be left out: take away its split first")
        self.assertEqual(self.signature(), before)

    def test_a_node_that_has_no_split_has_none_to_change(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertLispError('''(deal-replace-split! deal "B" (sequential-plan '(("B1" 20000000.0) ("B2" 20000000.0))))''', "B has no split to change: add one")

    def test_a_name_that_is_in_the_deal_already_is_an_error(self):
        self.run_lisp("(define deal (make-demo))")
        before = self.signature()
        self.assertLispError('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("AF" 40000000.0))))''',
                             "the deal already has a node called AF")
        self.assertLispError('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("A" 40000000.0))))''',
                             "not all called by different names")
        self.assertEqual(self.signature(), before)

    def test_nothing_is_changed_if_anything_is_wrong(self):
        self.run_lisp("(define deal (make-demo))")
        before = self.signature()
        original_split = self.run_lisp('(node-split (get-node deal "POOL"))')
        for src, message in (
                ('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 70000000.0) ("B" 40000000.0))))''', "add up to 110000000.0"),
                ('''(deal-replace-split! deal "A" (floater-inverse-plan "AF" "AI" :cap 0.06))''', "must be above the coupon"),
                ('''(deal-replace-split! deal "A" (floater-inverse-plan "AF" "AI"))''', "give the :cap of the floater"),
                ('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("Z" 40000000.0 z)) :accretion-to "Z"))''', "which is a Z bond")):
            with self.subTest(src=src):
                self.assertLispError(src, message)
                self.assertEqual(self.signature(), before)
                self.assertEqual(self.run_lisp('(node-split (get-node deal "POOL"))'), original_split)
        self.assertShows("(run-and-check deal)", "#t")

    def test_a_split_below_that_cannot_be_worked_out_again_stops_the_whole_change(self):
        """A premium and discount split of a bond with a coupon between theirs, divided again, so that the change of the coupons
        of the first makes the second impossible."""
        self.run_lisp('''(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-premium-discount! deal "A" "AP" "AD" :premium-coupon 0.08 :discount-coupon 0.05)
                         (deal-premium-discount! deal "AP" "AP1" "AP2" :premium-coupon 0.09 :discount-coupon 0.07)''')
        before = self.signature()
        self.assertLispError('(deal-replace-split! deal "A" (premium-discount-plan "AP" "AD" :premium-coupon 0.07 :discount-coupon 0.05))',
                             "must be between the discount coupon")
        self.assertEqual(self.signature(), before)
        self.run_lisp('(deal-replace-split! deal "A" (premium-discount-plan "AP" "AD" :premium-coupon 0.075 :discount-coupon 0.05))')
        self.assertShows('((node-coupon (get-node deal "AP1")) 0.0)', "0.09")
        self.assertEqual(self.run_lisp('(split-children (node-split (get-node deal "AP")))').car, "AP1")

    def test_a_split_that_was_given_the_sizes_of_its_children_keeps_the_share_of_the_parent_that_each_was(self):
        self.run_lisp('''(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-sequential! deal "A" '(("A1" 40000000.0) ("A2" 20000000.0)))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 75000000.0) ("B" 25000000.0))))''')
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "A1")) 0)'), 50000000.0, places=4)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "A2")) 0)'), 25000000.0, places=4)
        self.assertShows("(run-and-check deal)", "#t")

    def test_a_node_whose_children_have_no_balance_cannot_have_them_scaled(self):
        self.run_lisp('''(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-sequential! deal "A" '(("A1" 40000000.0) ("A2" 20000000.0)))
                         (vector-set! (node-balance (get-node deal "A1")) 0 0.0)
                         (vector-set! (node-balance (get-node deal "A2")) 0 0.0)''')
        self.assertLispError('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 75000000.0) ("B" 25000000.0))))''', "have no balance to scale")

    def test_the_children_of_an_interest_only_bond_follow_it_when_it_changes_size(self):
        self.run_lisp('''(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-io-po! deal "B" "BIO" "BPO")
                         (deal-sequential! deal "BPO" '(("P1" 25000000.0) ("P2" 15000000.0)))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 50000000.0) ("B" 50000000.0))))
                         (define direct (a-deal "Direct"))
                         (deal-sequential! direct "POOL" '(("A" 50000000.0) ("B" 50000000.0)))
                         (deal-io-po! direct "B" "BIO" "BPO")
                         (deal-sequential! direct "BPO" '(("P1" 31250000.0) ("P2" 18750000.0)))''')
        self.assertEqual(self.signature("deal"), self.signature("direct"))
        self.assertShows("(list (run-and-check deal) (run-and-check direct))", "(#t #t)")

    def test_the_children_that_are_left_out_may_be_gone_when_the_new_split_is_sized(self):
        """A PAC is sized from what its parent is paid, which is found by running the deal: the old split of the parent, whose
        children are no longer there, must not be in the way."""
        self.run_lisp("""(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("X" 60000000.0) ("Y" 40000000.0)))
                         (deal-replace-split! deal "POOL" (pac-plan "P" "C" 100 300))
                         (define direct (a-deal "Demo"))
                         (deal-pac! direct "POOL" "P" "C" 100 300)""")
        self.assertShows("(deal-names deal)", '("POOL" "P" "C")')
        self.assertEqual(self.signature("deal"), self.signature("direct"))

    def test_the_children_of_a_split_of_an_interest_only_bond_follow_it_when_it_changes_size(self):
        self.run_lisp("""(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-io-po! deal "B" "BIO" "BPO")
                         (deal-sequential! deal "BIO" '(("IO1" 25000000.0) ("IO2" 15000000.0)))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 50000000.0) ("B" 50000000.0))))
                         (define direct (a-deal "Direct"))
                         (deal-sequential! direct "POOL" '(("A" 50000000.0) ("B" 50000000.0)))
                         (deal-io-po! direct "B" "BIO" "BPO")
                         (deal-sequential! direct "BIO" '(("IO1" 31250000.0) ("IO2" 18750000.0)))""")
        self.assertEqual(self.signature("deal"), self.signature("direct"))
        self.assertShows('(node-follows (get-node deal "IO1"))', '"BIO"')
        self.assertShows("(list (run-and-check deal) (run-and-check direct))", "(#t #t)")

    def test_a_z_bond_can_be_made_and_unmade_by_a_change(self):
        self.run_lisp('''(define deal (a-deal "Demo"))
                         (deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("B" 40000000.0 z))))''')
        self.assertShows('(node-z-flag (get-node deal "B"))', "#t")
        self.assertShows("(run-and-check deal)", "#t")
        self.run_lisp('''(deal-replace-split! deal "POOL" (sequential-plan '(("A" 60000000.0) ("B" 40000000.0))))''')
        self.assertShows('(node-z-flag (get-node deal "B"))', "#f")
        self.assertShows("(run-and-check deal)", "#t")


class TestTryingAPlan(DealChangesCase):

    def test_the_trial_is_a_copy_and_the_deal_is_not_changed(self):
        self.run_lisp("(define deal (make-demo))")
        before = self.signature()
        leverage = self.show('(floater-inverse-split-leverage (node-split (get-node deal "A")))')
        self.run_lisp('(define trial (deal-trial-of-plan deal "A" (floater-inverse-plan "AF" "AI" :cap 0.10)))')
        self.assertEqual(self.signature(), before)
        self.assertEqual(self.show('(floater-inverse-split-leverage (node-split (get-node deal "A")))'), leverage)
        self.assertNotEqual(self.show('(floater-inverse-split-leverage (node-split (get-node trial "A")))'), leverage)
        self.assertNotEqual(self.signature("trial"), before)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node trial "AF")) 0)'), 60000000.0 * 0.065 / 0.10, places=4)
        self.assertAlmostEqual(self.run_lisp('(vector-ref (node-balance (get-node deal "AF")) 0)'), 60000000.0 * 0.065 / 0.095, places=4)

    def test_a_trial_that_works_out_what_is_below_leaves_the_splits_below_as_they_were(self):
        """The splits below the one that changes are worked out again: a PAC's schedule, a floater's leverage. On the copy, and only there."""
        self.run_lisp("(define deal (make-demo))")
        schedule = self.show('(pac-split-schedule (node-split (get-node deal "AF")))')
        leverage = self.show('(floater-inverse-split-leverage (node-split (get-node deal "A")))')
        self.run_lisp("""(define trial (deal-trial-of-plan deal "POOL" (sequential-plan '(("A" 70000000.0) ("B" 30000000.0)))))""")
        self.assertEqual(self.show('(pac-split-schedule (node-split (get-node deal "AF")))'), schedule)
        self.assertEqual(self.show('(floater-inverse-split-leverage (node-split (get-node deal "A")))'), leverage)
        self.assertNotEqual(self.show('(pac-split-schedule (node-split (get-node trial "AF")))'), schedule)

    def test_a_trial_of_a_plan_for_a_node_with_no_split_adds_it_to_the_copy(self):
        self.run_lisp("(define deal (make-demo))")
        before = self.signature()
        self.run_lisp('(define trial (deal-trial-of-plan deal "B" (sequential-plan (list (list "B1" 30000000.0) (list "B2" 10000000.0)))))')
        self.assertEqual(self.signature(), before)
        self.assertShows("(deal-names trial)", '("POOL" "A" "B" "AF" "AI" "AP" "AC" "B1" "B2")')
        self.assertShows("(deal-names deal)", '("POOL" "A" "B" "AF" "AI" "AP" "AC")')

    def test_a_plan_that_cannot_be_applied_is_an_error_from_the_trial(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertLispError('(deal-trial-of-plan deal "B" (sequential-plan (list (list "B1" 30000000.0) (list "B2" 20000000.0))))', "add up to")
        self.assertLispError('(deal-trial-of-plan deal "A" (floater-inverse-plan "AF" "AI" :cap 0.01))', "must be above the coupon")

    def test_the_principal_of_a_node_does_not_depend_on_what_is_not_above_it(self):
        """A PAC is sized from what its parent is paid, which the splits above it decide. What a node beside it, or the node itself, is
        divided into is of no matter, and in a deal that is being changed it may not add up yet."""
        self.run_lisp("(define deal (make-demo))")
        right_b = self.run_lisp('(deal-principal-at deal "B" 150)')
        right_af = self.run_lisp('(deal-principal-at deal "AF" 250)')
        self.run_lisp('''(vector-set! (node-balance (get-node deal "AP")) 0 5.0)                ; (what is under A no longer adds up)
                         (vector-set! (node-balance (get-node deal "AI")) 0 7.0)''')
        with self.assertRaises(lisp_core.LispError):                       # (the deal itself would not run)
            self.run_lisp("(run-and-check deal)")
        np.testing.assert_allclose(self.run_lisp('(deal-principal-at deal "B" 150)').items, right_b.items)     # (B is beside A)
        self.run_lisp("(define deal (make-demo))")
        self.run_lisp('(vector-set! (node-balance (get-node deal "AP")) 0 5.0)')                              # (under AF, which is the node)
        np.testing.assert_allclose(self.run_lisp('(deal-principal-at deal "AF" 250)').items, right_af.items)
        self.run_lisp('(vector-set! (node-balance (get-node deal "AI")) 0 7.0)')                              # (beside AF, which is above it)
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp('(deal-principal-at deal "AF" 250)')


class TestTakingASplitAway(DealChangesCase):

    def test_the_split_and_everything_below_it_is_taken_away(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertShows('(deal-delete-split! deal "A")', '("AF" "AP" "AC" "AI")')
        self.assertShows("(deal-names deal)", '("POOL" "A" "B")')
        self.assertShows('(node-split (get-node deal "A"))', "()")
        self.assertShows('(split-children (node-split (get-node deal "POOL")))', '("A" "B")')
        self.assertShows("(deal-leaves deal)", '("A" "B")')
        self.assertShows("(run-and-check deal)", "#t")
        self.assertLispError('(get-node deal "AP")', "no node called AP")

    def test_it_is_the_same_as_a_deal_that_never_had_it(self):
        self.run_lisp('''(define deal (make-demo))
                         (deal-delete-split! deal "A")
                         (define direct (a-deal "Demo"))
                         (deal-sequential! direct "POOL" '(("A" 60000000.0) ("B" 40000000.0)))''')
        self.assertEqual(self.signature("deal"), self.signature("direct"))

    def test_a_split_that_is_one_level_down_leaves_the_levels_above(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertShows('(deal-delete-split! deal "AF")', '("AP" "AC")')
        self.assertShows("(deal-names deal)", '("POOL" "A" "B" "AF" "AI")')
        self.assertShows('(split-children (node-split (get-node deal "A")))', '("AF" "AI")')
        self.assertShows("(run-and-check deal)", "#t")

    def test_the_split_of_the_collateral_can_be_taken_away_and_made_again(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertShows('(deal-delete-split! deal "POOL")', '("A" "AF" "AP" "AC" "AI" "B")')
        self.assertShows("(deal-names deal)", '("POOL")')
        self.run_lisp('''(deal-sequential! deal "POOL" '(("A" 60000000.0) ("B" 40000000.0)))
                         (deal-floater-inverse! deal "A" "AF" "AI" :cap 0.095)
                         (deal-pac! deal "AF" "AP" "AC" 100 300)''')
        self.assertEqual(self.signature("deal"), self.signature("(make-demo)"))

    def test_a_node_with_no_split_has_none_to_take_away(self):
        self.run_lisp("(define deal (make-demo))")
        self.assertLispError('(deal-delete-split! deal "B")', "B has no split to take away")
        self.assertLispError('(deal-delete-split! deal "NOPE")', "no node called NOPE")


class TestPlansAndTheOutline(DealChangesCase):
    """A split is made in two steps, a plan and adding it, so that the first can be looked at; and the outline is the deal as rows."""

    BUILDERS = {
        "sequential": ('(deal-sequential! %s "POOL" (list (list "A" 50000000.0) (list "B" 30000000.0) (list "Z" 20000000.0 (quote z))) :accretion-to "A" :losses (quote forward))',
                       '(sequential-plan (list (list "A" 50000000.0) (list "B" 30000000.0) (list "Z" 20000000.0 (quote z))) :accretion-to "A" :losses (quote forward))'),
        "pro rata": ('(deal-pro-rata! %s "POOL" (list (list "A" 70000000.0) (list "B" 30000000.0)) :losses (quote reverse))',
                     '(pro-rata-plan (list (list "A" 70000000.0) (list "B" 30000000.0)) :losses (quote reverse))'),
        "PAC": ('(deal-pac! %s "POOL" "P" "C" 90 250 :losses (quote pro-rata))',
                '(pac-plan "P" "C" 90 250 :losses (quote pro-rata))'),
        "floater": ('(deal-floater-inverse! %s "POOL" "F" "I" :cap 0.09 :margin 0.005)',
                    '(floater-inverse-plan "F" "I" :cap 0.09 :margin 0.005)'),
        "premium": ('(deal-premium-discount! %s "POOL" "P" "D" :premium-coupon 0.08 :discount-coupon 0.05)',
                    '(premium-discount-plan "P" "D" :premium-coupon 0.08 :discount-coupon 0.05)'),
        "IO/PO": ('(deal-io-po! %s "POOL" "IO" "PO" :io-coupon 0.02)',
                  '(io-po-plan "IO" "PO" :io-coupon 0.02)'),
    }

    def test_adding_a_plan_is_what_the_builder_of_that_kind_does(self):
        for kind, (builder, plan) in self.BUILDERS.items():
            with self.subTest(kind=kind):
                self.run_lisp('(define built (a-deal "Demo")) (define planned (a-deal "Demo"))')
                self.run_lisp(builder % "built")
                self.run_lisp('(deal-add-plan! planned "POOL" %s)' % plan)
                self.assertEqual(self.signature("built"), self.signature("planned"))
                self.assertShows("(list (run-and-check built) (run-and-check planned))", "(#t #t)")

    def test_the_sizes_of_a_plan_are_those_it_would_have_and_the_deal_is_not_changed(self):
        self.run_lisp('(define deal (a-deal "Demo"))')
        before = self.signature()
        parent = '(get-node deal "POOL")'
        self.assertShows('(split-plan-sizes deal %s (sequential-plan (list (list "A" 1.0) (list "B" 2.0))))' % parent, "(1.0 2.0)")
        self.assertShows('(split-plan-sizes deal %s (io-po-plan "IO" "PO"))' % parent, "(100000000.0 100000000.0)")
        floater = self.run_lisp('(split-plan-sizes deal %s (floater-inverse-plan "F" "I" :cap 0.0975))' % parent)
        self.assertAlmostEqual(floater.car, 100000000.0 * 0.065 / 0.0975, places=4)
        self.assertAlmostEqual(floater.cdr.car, 100000000.0 * (1 - 0.065 / 0.0975), places=4)
        pac = self.run_lisp('(split-plan-sizes deal %s (pac-plan "P" "C" 100 300))' % parent)
        self.assertAlmostEqual(pac.car + pac.cdr.car, 100000000.0, places=4)
        self.assertEqual(self.signature(), before)
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_plan_that_cannot_be_added_adds_nothing(self):
        self.run_lisp('(define deal (a-deal "Demo"))')
        self.assertLispError('(deal-add-plan! deal "POOL" (sequential-plan (list (list "A" 50000000.0) (list "B" 30000000.0))))', "add up to 80000000.0")
        self.assertLispError('(deal-add-plan! deal "POOL" (floater-inverse-plan "F" "I"))', "give the :cap")
        self.assertLispError('(deal-add-plan! deal "POOL" (premium-discount-plan "P" "D" :premium-coupon 0.08))', "give the :premium-coupon and the :discount-coupon")
        self.assertShows("(deal-names deal)", '("POOL")')

    def test_a_plan_is_made_of_its_tranches_and_its_split(self):
        self.run_lisp('(define plan (io-po-plan "IO" "PO" :io-coupon 0.02))')
        self.assertShows("(split-plan-tranches plan)", '(("IO" 0.0 :notional #t :follows "PO") ("PO" 0.0))')
        self.assertShows("(io-po-split? (split-plan-split plan))", "#t")
        self.assertShows("(split-children (split-plan-split plan))", '("IO" "PO")')

    def test_the_outline_has_a_row_for_each_node_under_its_parent_with_the_kind_of_split(self):
        self.run_lisp("(define deal (make-demo))")
        column = lambda name: self.run_lisp('(table-column (deal-outline deal) "%s")' % name).items
        self.assertEqual(list(column("tranche")), ["POOL", "  A", "    AF", "      AP", "      AC", "    AI", "  B"])
        self.assertEqual(list(column("split")), ["sequential", "floater and inverse floater", "PAC and companion", "", "", "", ""])
        np.testing.assert_allclose(column("balance")[:2], [100000000.0, 60000000.0])
        self.assertShows("(deal-outline-entries deal)", '(("POOL" . 0) ("A" . 1) ("AF" . 2) ("AP" . 3) ("AC" . 3) ("AI" . 2) ("B" . 1))')

    def test_the_balances_of_the_outline_are_to_the_cent(self):
        self.run_lisp("(define deal (make-demo))")
        balances = self.run_lisp("(table-column (deal-outline deal) \"balance\")")
        self.assertEqual(float(balances.items[2]), round(60000000.0 * 0.065 / 0.095, 2))

    def test_a_split_of_a_kind_of_your_own_is_labelled_split_unless_it_says_otherwise(self):
        self.run_lisp('''(defstruct (my-split (:include split)))
                         (defstruct (my-other-split (:include sequential-split)))
                         (defmethod split-label ((split my-other-split)) "mine")''')
        self.assertShows('(split-label (make-my-split :children (list "A")))', '"split"')
        self.assertShows('(split-label (make-my-other-split :children (list "A")))', '"mine"')
        self.assertShows('(split-label (make-sequential-split :children (list "A")))', '"sequential"')
