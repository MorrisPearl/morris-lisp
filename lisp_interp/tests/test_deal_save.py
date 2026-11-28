"""save-deal and load-deal (lib/deal_save.lsp): a deal saved in a file, as the data it is made from, and made again from the file. A deal with
every kind of split, prices and settings comes back with the same tranches, cash flows and prices; a kind of split of your own comes back once it is
defined; and what cannot be saved, or is not a saved deal, is an error that says so."""

import os
import shutil
import tempfile

from deal_support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, LispTestCase, and the deals the tests make

import lisp_widgets

# A deal with each of the seven kinds of split (a PAC, and a sequential with a Z bond and accretion directed under it, a premium and discount, an
# IO and PO, a floater and inverse floater, a pro rata, and one by average life), a tranche that has not been given a parent, settings that are
# not the ones a deal begins with, and a price, a yield, a spread and a delay given to tranches.
EVERY_KIND = """
(define deal (new-deal "Every kind 2026-1" :first-payment (date 2026 12 25) :closing-date (date 2026 11 20)
                       :collateral '((100000000.0 6.5 6.0 360) (50000000.0 7.0 6.0 240 12))
                       :treasury-curve '((1 4.0) (2 4.1) (5 4.2) (10 4.4) (30 4.6))))
(define (balance-of name) (vector-ref (node-balance (get-node deal name)) 0))
(deal-pac! deal "POOL" "PAC" "SUP" 100 300)
(define pac (balance-of "PAC"))
(deal-floater-inverse! deal "SUP" "SF" "SI" :cap 0.09 :margin 0.005)
(deal-sequential! deal "PAC" (list (list "PA1" (* 0.4 pac)) (list "PA2" (* 0.5 pac)) (list "PZ" (* 0.1 pac) 'z)) :accretion-to "PA1")
(deal-premium-discount! deal "PA1" "PA1-P" "PA1-D" :premium-coupon 0.07 :discount-coupon 0.05)
(deal-io-po! deal "PA2" "PA2-IO" "PA2-PO")
(define floater (balance-of "SF"))
(deal-pro-rata! deal "SF" (list (list "SF1" (* 0.5 floater)) (list "SF2" (* 0.5 floater))))
(deal-average-life! deal "SI" '(("SI1" 10) ("SI2")))
(deal-add-tranche! deal "LOOSE" 1000.0)
(deal-set-home-price-growth! deal 2.0)
(deal-set-mortgage-spread! deal 1.5)
(deal-set-liquidation-lag! deal 12)
(deal-set-rate-model! deal (make-rate-model :a 2.5))
(deal-run! deal :index 0.04)
(deal-set-price! deal "PA1-P" 101.5)
(deal-set-yield! deal "PZ" 5.25)
(deal-set-spread! deal "PA2-PO" 85)
(deal-set-delay! deal "SF1" 0)
"""

# A kind of split of your own: it pays its children in the reverse of their order, the last first.
LAST_FIRST = """
(defstruct (last-first-split (:include split)))
(defmethod pay-principal ((split last-first-split) deal parent t)
  (let ((cash (vector-ref (node-principal parent) t)))
    (dolist (child (reverse (split-children split)))
      (set! cash (pay-child! (get-node deal child) t cash)))))
"""

TOY_POOL = '(new-deal "Toy" :collateral (quote ((120.0 0.0 0.0 6))) :speed (prepayment-speed (quote cpr) 0))'


class SaveAndLoadTest(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(require "deal_save.lsp")')
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = os.path.join(self.directory, "deal.deal")

    def save(self, deal="deal"):
        self.run_lisp('(save-deal %s "%s")' % (deal, self.path))

    def load(self, env=None):
        return self.run_lisp('(define loaded (load-deal "%s"))' % self.path, env)

    def text(self, src):
        """What a Lisp expression's value is written as."""
        return str(self.run_lisp("(write-to-string %s)" % src))

    def file_text(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def rewrite_file(self, old, new):
        """Changes the saved file, as a person might by hand: old, in its text, becomes new."""
        text = self.file_text()
        self.assertIn(old, text)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))

    def test_a_deal_with_every_kind_of_split_comes_back_as_it_was(self):
        self.run_lisp(EVERY_KIND)
        self.save()
        self.load()
        self.assertEqual(self.text("(deal-outline loaded)"), self.text("(deal-outline deal)"))
        self.assertEqual(self.text("(deal-names loaded)"), self.text("(deal-names deal)"))          # (the order they were added in)
        self.run_lisp("(deal-run! deal :index 0.04) (deal-run! loaded :index 0.04)")
        self.assertIs(self.run_lisp("(deal-check loaded)"), True)
        for table in ("deal-principal-table", "deal-interest-table", "deal-accrual-table"):
            self.assertEqual(self.text("(%s loaded)" % table), self.text("(%s deal)" % table), table)
        for name, priced_by in (("PA1-P", "price"), ("PZ", "yield"), ("PA2-PO", "spread")):
            self.assertEqual(self.text('(node-priced-by (get-node loaded "%s"))' % name), priced_by)
            for slot in ("price", "yield", "spread", "duration", "money"):
                self.assertEqual(self.text('(node-%s (get-node loaded "%s"))' % (slot, name)),
                                 self.text('(node-%s (get-node deal "%s"))' % (slot, name)), (name, slot))
        self.assertEqual(self.run_lisp('(node-delay (get-node loaded "SF1"))'), 0)
        for setting in ("home-price-growth", "mortgage-spread", "liquidation-lag", "rate-model", "first-payment", "closing-date",
                        "treasury-curve", "pricing-speed", "collateral", "index"):
            self.assertEqual(self.text("(deal-%s loaded)" % setting), self.text("(deal-%s deal)" % setting), setting)
        self.assertIs(self.run_lisp('(deal-in-tree? loaded "LOOSE")'), False)

    def test_the_dates_are_written_as_dates_and_a_file_that_has_them_as_text_is_read_too(self):
        self.run_lisp('(define deal (new-deal "Dated" :first-payment (date 2026 12 25) :collateral (quote ((120.0 0.0 0.0 6)))))')
        self.save()
        self.assertIn(" :first-payment 2026-12-25\n", self.file_text())
        self.rewrite_file(" :first-payment 2026-12-25\n", ' :first-payment "2026-12-25"\n')       # (as the first files had them)
        self.load()
        self.assertShows("(equal? (deal-first-payment loaded) (date 2026 12 25))", "#t")

    def test_a_deal_that_is_loaded_into_is_the_one_from_the_file_and_keeps_its_views(self):
        self.run_lisp('(define deal %s) (deal-sequential! deal "POOL" (quote (("A" 40.0) ("B" 80.0))))' % TOY_POOL)
        self.save()
        self.run_lisp('(define other (new-deal "Other" :collateral (quote ((60.0 0.0 0.0 3)))))'
                      '(define refreshed 0) (deal-add-view! other (quote (tranches)) (lambda () (set! refreshed (+ refreshed 1))))'
                      '(define same other)')
        self.run_lisp('(deal-load! other "%s")' % self.path)
        self.assertShows("(deal-name same)", '"Toy"')                                # (what had the deal has the one from the file)
        self.assertShows("(deal-names same)", '("POOL" "A" "B")')
        self.assertShows("refreshed", "1")                                         # (its view showed it)
        self.run_lisp('(deal-delete-split! other "POOL")')
        self.assertShows("refreshed", "2")                                         # (and still shows it as it changes)

    def test_a_tranche_priced_by_its_oas_keeps_it_for_when_the_paths_are_run(self):
        self.run_lisp('(define deal %s) (deal-sequential! deal "POOL" (quote (("A" 40.0) ("B" 80.0))))' % TOY_POOL)
        self.run_lisp('(node-priced-by-set! (get-node deal "A") (quote oas)) (node-oas-set! (get-node deal "A") 50)')     # (as deal-set-oas! leaves it)
        self.save()
        self.load()
        self.assertEqual(self.text('(node-priced-by (get-node loaded "A"))'), "oas")
        self.assertEqual(self.run_lisp('(node-oas (get-node loaded "A"))'), 50)

    def test_the_file_is_text_that_a_person_can_read_and_that_is_read_as_data(self):
        self.run_lisp('(define deal %s) (deal-sequential! deal "POOL" (quote (("A" 40.0) ("B" 80.0))))' % TOY_POOL)
        self.save()
        text = self.file_text()
        self.assertTrue(text.startswith('; The deal "Toy", saved by save-deal.'))
        for line in ['#S(deal-file', ' :name "Toy"', ' :first-payment ()',
                     ' :pricing-speed #S(speed-curve :type cpr :pieces ((0 0 ())))',
                     '  ("A" :priced-by () :value () :delay 24)',
                     ' (("POOL" (("A" 40.0 :z #f :notional #f :follows ()) ("B" 80.0 :z #f :notional #f :follows ())) '
                     '#S(sequential-split :children ("A" "B") :loss-rule reverse :accretion-to ())))']:
            self.assertIn(line + "\n", text)

    def test_a_kind_of_split_of_your_own_is_saved_and_comes_back_once_it_is_defined(self):
        self.run_lisp(LAST_FIRST)
        self.run_lisp('(define deal %s) (deal-add-plan! deal "POOL" (make-split-plan :tranches (quote (("A" 40.0) ("B" 80.0))) '
                      ':split (make-last-first-split :children (quote ("A" "B")))))' % TOY_POOL)
        self.save()
        self.assertIn('#S(last-first-split :children ("A" "B") :loss-rule reverse)', self.file_text())
        elsewhere = lisp_builtins.make_global_env(output=lambda text: None)          # (another session, which has not defined it)
        lisp_core.run_file(os.path.join(LIB, "autoloads.lsp"), elsewhere)
        with self.assertRaisesRegex(lisp_core.LispError, "there is no struct type called last-first-split"):
            self.load(elsewhere)
        self.run_lisp('(require "deal_save.lsp")' + LAST_FIRST, elsewhere)
        self.load(elsewhere)
        self.run_lisp("(deal-run! loaded)", elsewhere)
        self.assertEqual(lisp_widgets.to_python(self.run_lisp('(vector->list (node-principal (get-node loaded "B")))', elsewhere)),
                         [20.0, 20.0, 20.0, 20.0, 0.0, 0.0])                         # (B, the last child, is paid first)

    def add_kept_split(self, rule):
        """Divides the deal's pool by a split of a kind of one's own, whose rule slot holds rule (Lisp source)."""
        self.run_lisp("(defstruct (kept-split (:include split)) rule)"
                      "(defmethod pay-principal ((split kept-split) deal parent t) #f)"
                      '(deal-add-plan! deal "POOL" (make-split-plan :tranches (quote (("A" 400.0) ("B" 600.0))) '
                      ':split (make-kept-split :children (quote ("A" "B")) :rule %s)))' % rule)

    def test_what_does_not_read_back_as_it_is_is_not_saved(self):
        self.run_lisp('(define deal %s)' % psa_deal("demo", 1000.0, 6.0, term=12))
        self.add_kept_split("((lambda (n) (lambda (x) (* x n))) 2)")        # a closure: its code doesn't have n
        with self.assertRaisesRegex(lisp_core.LispError, r"save-deal: the splits of the deal cannot be saved: the function "
                                                         r"#.\(lambda \(x\) \(\* x n\)\) uses n, a variable of the place where it was made"):
            self.save()
        self.assertFalse(os.path.exists(self.path))                                  # (nothing is written)
        self.run_lisp('(kept-split-rule-set! (node-split (get-node deal "POOL")) %struct-type-kept-split)')    # (not data at all)
        with self.assertRaisesRegex(lisp_core.LispError, "save-deal: the splits of the deal cannot be saved: #<struct-type kept-split> is not data"):
            self.save()
        self.run_lisp(HAND_DEAL + hand_deal([100.0, 50.0, 0.0], [50.0, 50.0], name="handmade", variable="handmade"))
        with self.assertRaisesRegex(lisp_core.LispError, "was given its cash flows, not pieces of collateral"):
            self.save("handmade")

    def test_a_function_made_at_the_top_level_is_saved_as_its_code(self):
        self.run_lisp('(define deal %s)' % psa_deal("demo", 1000.0, 6.0, term=12))
        self.run_lisp("(define (double x) (* 2 x))")
        self.add_kept_split("(lambda (x) (double x))")
        self.save()
        self.assertIn("#S(kept-split :children (\"A\" \"B\") :loss-rule reverse :rule #.(lambda (x) (double x)))", self.file_text())
        self.load()
        self.assertEqual(self.run_lisp('((kept-split-rule (node-split (get-node loaded "POOL"))) 21)'), 42)

    def test_a_prepayment_model_and_an_index_function_are_saved_unless_they_are_closures(self):
        self.run_lisp('(define deal %s)' % TOY_POOL)
        self.run_lisp("(define (flat-model piece path) (vector-fill (collateral-piece-wam piece) 5.0))"
                      "(deal-set-prepayment-model! deal flat-model)"
                      "(deal-set-index-function! deal (lambda (short-rates) (+ short-rates 0.001)))")
        self.save()
        self.assertNotIn("is not saved", "".join(self.out))
        self.assertIn(" :prepayment-model #.(lambda (piece path) (vector-fill (collateral-piece-wam piece) 5.0))\n", self.file_text())
        self.assertIn(" :index-function #.(lambda (short-rates) (+ short-rates 0.001))\n", self.file_text())
        self.load()
        self.assertEqual(self.text("(deal-prepayment-model loaded)"), self.text("flat-model"))
        self.assertEqual(self.text("((deal-index-function loaded) (vector 0.02 0.03))"), "#(0.021 0.031)")
        self.run_lisp("(define (index-over spread) (lambda (short-rates) (+ short-rates spread)))"
                      "(deal-set-index-function! deal (index-over 0.002))")
        self.save()
        self.assertIn("save-deal: the deal's index function is not saved (the function #.(lambda (short-rates) (+ short-rates spread)) "
                      "uses spread, a variable of the place where it was made", "".join(self.out))
        self.assertIn("give it to the loaded deal again, with deal-set-index-function!", "".join(self.out))
        self.load()
        self.assertEqual(self.text("(deal-index-function loaded)"), "()")
        self.assertEqual(self.text("(deal-prepayment-model loaded)"), self.text("flat-model"))

    def test_what_is_not_a_saved_deal_is_an_error_and_nothing_in_it_is_run(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('(display "this is run")')
        with self.assertRaisesRegex(lisp_core.LispError, "is not a deal saved by save-deal"):
            self.load()
        self.assertNotIn("this is run", "".join(self.out))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("(((")
        with self.assertRaisesRegex(lisp_core.LispError, "cannot be read as a saved deal"):
            self.load()
        self.run_lisp('(define deal %s)' % TOY_POOL)
        self.save()
        self.rewrite_file(" :version 1\n", " :version 99\n")
        with self.assertRaisesRegex(lisp_core.LispError, "was saved in version 99 of the way deals are saved, and this is version 1"):
            self.load()

    def test_a_tranche_that_does_not_come_out_the_size_it_was_is_an_error(self):
        """A PAC's size is worked out from the collateral: a file whose PAC was another size (made by hand, or by a later change to how a
        PAC is sized) does not load as something else."""
        self.run_lisp('(define deal %s) (deal-pac! deal "POOL" "PAC" "SUP" 100 300)' % psa_deal("demo", 100000000.0, 6.5))
        self.save()
        pac = self.run_lisp('(write-to-string (vector-ref (node-balance (get-node deal "PAC")) 0))')
        self.rewrite_file('("PAC" %s ' % pac, '("PAC" 50000000.0 ')
        with self.assertRaisesRegex(lisp_core.LispError, "the file gives PAC a balance of 50,000,000.00, and the deal made from it gives it"):
            self.load()


if __name__ == "__main__":
    unittest.main()
