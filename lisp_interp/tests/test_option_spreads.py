"""lib/option_spreads.lsp and lib/option_positions.lsp: of the options expiring on one day, the best position of a
kind -- a spread (vertical, butterfly, condor, straddle, strangle), a single option, shares with an option or two, or
the stock alone -- by the profit at the price expected on the day as a share of the most that can be lost; the
kinds compared; and the orders for them."""

import datetime
import itertools

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


NAN = float("nan")
KINDS = ["bull-call", "bear-call", "bull-put", "bear-put", "call-butterfly", "put-butterfly", "iron-condor",
         "iron-butterfly", "long-straddle", "long-strangle",
         "long-call", "long-put", "cash-secured-put", "long-stock", "covered-call", "protective-put", "collar"]

# What each kind is, for the plain calculation below: its legs from the lowest strike up, as (C or P, how many
# bought -- a minus sign for sold), with the shares as S, first.
LEGS = {"bull-call": [("C", 1), ("C", -1)], "bear-call": [("C", -1), ("C", 1)],
        "bull-put": [("P", 1), ("P", -1)], "bear-put": [("P", -1), ("P", 1)],
        "call-butterfly": [("C", 1), ("C", -2), ("C", 1)], "put-butterfly": [("P", 1), ("P", -2), ("P", 1)],
        "iron-condor": [("P", 1), ("P", -1), ("C", -1), ("C", 1)],
        "iron-butterfly": [("P", 1), ("P", -1), ("C", -1), ("C", 1)],
        "long-straddle": [("C", 1), ("P", 1)], "long-strangle": [("P", 1), ("C", 1)],
        "long-call": [("C", 1)], "long-put": [("P", 1)], "cash-secured-put": [("P", -1)],
        "long-stock": [("S", 1)], "covered-call": [("S", 1), ("C", -1)], "protective-put": [("S", 1), ("P", 1)],
        "collar": [("S", 1), ("P", 1), ("C", -1)]}


class OptionSpreadsTestCase(OptionChainTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "option_spreads.lsp")')

    def spreads(self, call):
        """The table of spreads that the call (Lisp source) finds, as a dict of columns, as Python lists."""
        self.run_lisp("(define search %s)" % call)
        table = self.run_lisp("(spread-search-spreads search)")
        return {str(name): list(vector.items) for name, vector in lisp_tables.table_columns(table, "test")}


class TestSpreadsByHand(OptionSpreadsTestCase):
    """A chain with calls and puts at 90 to 120, and the spreads of every kind, worked out by hand."""

    #           strike  call bid, ask   put bid, ask
    QUOTES = [(90, (14.9, 15.1), (0.05, 0.2)), (95, (10.4, 10.6), (0.4, 0.6)), (100, (6.0, 6.2), (1.4, 1.6)),
              (105, (3.0, 3.2), (3.7, 3.9)), (110, (1.2, 1.4), (6.8, 7.0)), (115, (0.3, 0.5), (11.0, 11.2)),
              (120, (0.05, 0.15), (15.2, 15.4))]

    def setUp(self):
        super().setUp()
        rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in self.QUOTES:
            rows.append({"strike": strike, "bid": call_bid, "ask": call_ask})
            rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.make_chain(rows)

    def row(self, kind, strikes, expected=108, options=""):
        """The spread of the kind with exactly these strikes (lowest first), as a dict of its numbers."""
        table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) %s %s)" % (kind, expected, options))
        found = [i for i in range(len(table["ratio"]))
                 if tuple(table["strike-%d" % (n + 1)][i] for n in range(len(strikes))) == tuple(strikes)]
        self.assertEqual(len(found), 1, "%s %s: %d such spreads" % (kind, strikes, len(found)))
        return {name: column[found[0]] for name, column in table.items()}

    # kind, strikes, then: cost, max-loss, max-profit, worth, profit, breakeven-1, breakeven-2
    WORKED = [
        # buy the 100 call at its ask 6.2, sell the 110 at its bid 1.2: pay 5.0; at 108 worth 8 - 0; the most lost is
        # the 5.0 (with the stock at 100 or less) and the most made is 10 - 5 = 5; even at 100 + 5
        ("bull-call", (100, 110), 5.0, 5.0, 5.0, 8.0, 3.0, 105.0, NAN),
        # sell the 110 call at 1.2, buy the 115 at 0.5: get 0.7; at 108 both worthless; lose at most 5 - 0.7 = 4.3
        ("bear-call", (110, 115), -0.7, 4.3, 0.7, 0.0, 0.7, 110.7, NAN),
        # buy the 100 put at 1.6, sell the 105 at 3.7: get 2.1; worthless at 108; lose at most 5 - 2.1 = 2.9
        ("bull-put", (100, 105), -2.1, 2.9, 2.1, 0.0, 2.1, 102.9, NAN),
        # sell the 110 put at 6.8, buy the 120 at 15.4: pay 8.6; at 108 the 120 is worth 12 and the 110 owes 2: worth 10
        ("bear-put", (110, 120), 8.6, 8.6, 1.4, 10.0, 1.4, 111.4, NAN),
        # buy the 105 at 3.2, sell two 110s at 1.2, buy the 115 at 0.5: pay 3.2 - 2.4 + 0.5 = 1.3; at 108, 3 - 0 + 0
        # the most made is 5 - 1.3 = 3.7, with the stock at 110; even at 105 + 1.3 and 115 - 1.3
        ("call-butterfly", (105, 110, 115), 1.3, 1.3, 3.7, 3.0, 1.7, 106.3, 113.7),
        # buy the 100 put at 1.6, sell two 105s at 3.7, buy the 110 at 7.0: pay 1.6 - 7.4 + 7.0 = 1.2; at 108 only the 110
        # put is worth anything, 2; the most made is 5 - 1.2 = 3.8; even at 100 + 1.2 and 110 - 1.2
        ("put-butterfly", (100, 105, 110), 1.2, 1.2, 3.8, 2.0, 0.8, 101.2, 108.8),
        # buy the 100 put at 1.6, sell the 105 put at 3.7, sell the 110 call at 1.2, buy the 115 at 0.5: get 2.8; at 108
        # all are worthless; lose at most 5 - 2.8 = 2.2; even at 105 - 2.8 and 110 + 2.8
        ("iron-condor", (100, 105, 110, 110 + 5), -2.8, 2.2, 2.8, 0.0, 2.8, 102.2, 112.8),
        # buy the 105 put at 3.9, sell the 110 put at 6.8, sell the 110 call at 1.2, buy the 115 at 0.5: get 3.6; at 108
        # the sold 110 put is worth 2, which is owed: worth -2; lose at most 5 - 3.6 = 1.4; even at 110 -/+ 3.6
        ("iron-butterfly", (105, 110, 110, 115), -3.6, 1.4, 3.6, -2.0, 1.6, 106.4, 113.6),
        # buy the 100 call at 6.2 and the 100 put at 1.6: pay 7.8; at 108 the call is worth 8; no limit to the gain;
        # the loss is greatest at the strike, 7.8; even at 100 - 7.8 and 100 + 7.8
        ("long-straddle", (100, 100), 7.8, 7.8, NAN, 8.0, 0.2, 92.2, 107.8),
        # buy the 95 put at 0.6 and the 105 call at 3.2: pay 3.8; at 108 the call is worth 3; even at 95 - 3.8, 105 + 3.8
        ("long-strangle", (95, 105), 3.8, 3.8, NAN, 3.0, -0.8, 91.2, 108.8),
        # buy the 100 call at its ask 6.2: pay 6.2, the most that can be lost (the stock at 100 or less); at 108 it is
        # worth 8, a profit of 1.8; there is no limit to the gain; even at 100 + 6.2
        ("long-call", (100,), 6.2, 6.2, NAN, 8.0, 1.8, 106.2, NAN),
        # buy the 110 put at 7.0: at 108 it is worth 2, a loss of 5; the most made is 110 - 7 = 103, with the stock at 0;
        # even at 110 - 7
        ("long-put", (110,), 7.0, 7.0, 103.0, 2.0, -5.0, 103.0, NAN),
        # sell the 105 put at its bid 3.7: get 3.7, the most that can be made (the stock at 105 or more); at 108 the put
        # expires worthless; the most lost is the strike less the 3.7, 101.3, with the stock at 0; even at 105 - 3.7
        ("cash-secured-put", (105,), -3.7, 101.3, 3.7, 0.0, 3.7, 101.3, NAN),
        # buy a share at the stock's price, 104: at 108 it is worth 108, a profit of 4; the most lost is all 104; there
        # is no limit to the gain; even at 104
        ("long-stock", (), 104.0, 104.0, NAN, 108.0, 4.0, 104.0, NAN),
        # buy a share at 104 and sell the 110 call at 1.2: pay 102.8; at 108 the share is worth 108 and the call nothing, a
        # profit of 5.2; the most made is 110 - 102.8 = 7.2 (the stock at 110 or more); the most lost is the whole 102.8;
        # even at 102.8
        ("covered-call", (110,), 102.8, 102.8, 7.2, 108.0, 5.2, 102.8, NAN),
        # buy a share at 104 and the 100 put at 1.6: pay 105.6; at 108 the share is worth 108 and the put nothing, a
        # profit of 2.4; the most lost is 105.6 - 100 = 5.6 (the stock at 100 or less); there is no limit to the gain; even
        # at 105.6
        ("protective-put", (100,), 105.6, 5.6, NAN, 108.0, 2.4, 105.6, NAN),
        # buy a share at 104, buy the 100 put at 1.6, sell the 110 call at 1.2: pay 104 + 1.6 - 1.2 = 104.4; at 108 the share
        # is worth 108: a profit of 3.6; the most lost is 104.4 - 100 = 4.4; the most made is 110 - 104.4 = 5.6; even at 104.4
        ("collar", (100, 110), 104.4, 4.4, 5.6, 108.0, 3.6, 104.4, NAN),
    ]

    def test_each_kind_of_spread_by_hand(self):
        for kind, strikes, cost, max_loss, max_profit, worth, profit, breakeven_1, breakeven_2 in self.WORKED:
            with self.subTest(kind=kind):
                got = self.row(kind, strikes)
                for name, expected in [("cost", cost), ("max-loss", max_loss), ("max-profit", max_profit), ("worth", worth),
                                       ("profit", profit), ("ratio", profit / max_loss), ("breakeven-1", breakeven_1),
                                       ("breakeven-2", breakeven_2)]:
                    np.testing.assert_allclose(got[name], expected, rtol=1e-5, atol=1e-5, equal_nan=True, err_msg=name)

    def test_the_options_of_each_spread_are_named_in_the_order_of_the_kinds_legs(self):
        symbol = lambda kind, strike: "XYZ   261120%s%08d" % (kind, strike * 1000)
        for kind, strikes, symbols in [
                ("bull-call", (100, 110), ["C100", "C110"]), ("bear-put", (110, 120), ["P110", "P120"]),
                ("call-butterfly", (105, 110, 115), ["C105", "C110", "C115"]),
                ("iron-condor", (100, 105, 110, 115), ["P100", "P105", "C110", "C115"]),
                ("iron-butterfly", (105, 110, 110, 115), ["P105", "P110", "C110", "C115"]),
                ("long-straddle", (100, 100), ["C100", "P100"]), ("long-strangle", (95, 105), ["P95", "C105"]),
                ("long-call", (100,), ["C100"]), ("long-put", (110,), ["P110"]), ("cash-secured-put", (105,), ["P105"]),
                ("covered-call", (110,), ["C110"]), ("protective-put", (100,), ["P100"]),
                ("collar", (100, 110), ["P100", "C110"])]:
            with self.subTest(kind=kind):
                got = self.row(kind, strikes)
                self.assertEqual([str(got["symbol-%d" % (n + 1)]) for n in range(len(symbols))],
                                 [symbol(s[0], int(s[1:])) for s in symbols])
        # the prices are the ask of each bought and the bid of each sold
        got = self.row("call-butterfly", (105, 110, 115))
        np.testing.assert_allclose([got["price-1"], got["price-2"], got["price-3"]], [3.2, 1.2, 0.5], rtol=1e-5)

    def test_the_best_spread_is_first_and_the_ranking_follows_the_expected_price(self):
        # a butterfly pays most with the stock at its middle strike: the best one follows the expected price
        for expected, middle in [(100, 100), (105, 105), (110, 110)]:
            with self.subTest(expected=expected):
                table = self.spreads("(option-spreads-for-chain chain 'call-butterfly (date 2026 11 20) %d)" % expected)
                self.assertEqual(table["strike-2"][0], middle)
                self.assertEqual(table["ratio"], sorted(table["ratio"], reverse=True))

    def test_what_the_search_knows_of_the_rest(self):
        self.run_lisp("(define search (option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108))")
        for expression, expected in [("(spread-search-kind search)", "iron-condor"), ("(spread-search-stock search)", '"XYZ"'),
                                     ("(spread-search-stock-price search)", "104.0"), ("(spread-search-expiration search)", "2026-11-20"),
                                     ("(spread-search-expected-price search)", "108"), ("(spread-search-prices search)", "bid-ask")]:
            self.assertShows(expression, expected)
        table = self.spreads("(option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108)")
        self.assertEqual(list(table), ["symbol-1", "symbol-2", "symbol-3", "symbol-4", "strike-1", "strike-2", "strike-3", "strike-4",
                                       "price-1", "price-2", "price-3", "price-4", "cost", "max-loss", "max-profit", "worth",
                                       "profit", "ratio", "breakeven-1", "breakeven-2"])
        table = self.spreads("(option-spreads-for-chain chain 'bull-put (date 2026 11 20) 108)")
        self.assertEqual(list(table), ["symbol-1", "symbol-2", "strike-1", "strike-2", "price-1", "price-2", "cost", "max-loss",
                                       "max-profit", "worth", "profit", "ratio", "breakeven-1", "breakeven-2"])
        # the shares are not a leg with a symbol, strike, and price of their own: the cost has them in it
        table = self.spreads("(option-spreads-for-chain chain 'collar (date 2026 11 20) 108)")
        self.assertEqual(list(table), ["symbol-1", "symbol-2", "strike-1", "strike-2", "price-1", "price-2", "cost", "max-loss",
                                       "max-profit", "worth", "profit", "ratio", "breakeven-1", "breakeven-2"])
        table = self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108)")
        self.assertEqual(list(table), ["cost", "max-loss", "max-profit", "worth", "profit", "ratio", "breakeven-1", "breakeven-2"])
        self.assertEqual(len(table["cost"]), 1)

    def test_prices_at_the_middle(self):
        """The bull call 100/110 at middles of 6.1 and 1.3 costs 4.8."""
        got = self.row("bull-call", (100, 110), options=":prices 'mid")
        np.testing.assert_allclose([got["price-1"], got["price-2"], got["cost"]], [6.1, 1.3, 4.8], rtol=1e-5)
        self.assertShows("(spread-search-prices search)", "mid")

    def test_a_spread_that_cannot_make_a_profit_has_no_breakeven(self):
        """The bull call 90/95 costs 15.1 - 10.4 = 4.7 and is worth 5 at most: it can make 0.3. But 105/110 costs
        3.2 - 1.2 = 2.0 and 100/105 costs 6.2 - 3.0 = 3.2; make one that costs more than its width: 95/100."""
        self.make_chain([{"strike": 95, "bid": 10.0, "ask": 10.2}, {"strike": 100, "bid": 4.9, "ask": 5.1}])
        table = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 110)")
        # 95/100 costs 10.2 - 4.9 = 5.3 for a worth of 5 at most: a loss of 0.3, whatever the stock does
        np.testing.assert_allclose(table["cost"], [5.3], rtol=1e-5)
        np.testing.assert_allclose(table["max-profit"], [-0.3], atol=1e-5)
        self.assertTrue(table["breakeven-1"][0] != table["breakeven-1"][0])               # (missing)
        np.testing.assert_allclose(table["ratio"], [-0.3 / 5.3], rtol=1e-4)

    def test_a_straddle_or_strangle_has_no_limit_to_what_it_makes(self):
        for kind in ("long-straddle", "long-strangle"):
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertTrue(all(x != x for x in table["max-profit"]), kind)                # all missing
            self.assertTrue(all(x == x for x in table["breakeven-1"]), kind)
            self.assertTrue(all(x == x for x in table["breakeven-2"]), kind)
            self.assertTrue(all(a < b for a, b in zip(table["breakeven-1"], table["breakeven-2"])), kind)
        # and the others have a limit on both
        for kind in KINDS[:8] + ["long-put", "cash-secured-put", "covered-call", "collar"]:
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertTrue(all(x == x for x in table["max-profit"]), kind)
            self.assertTrue(all(x > 0 for x in table["max-loss"]), kind)

    def test_the_single_options_and_shares_that_have_no_limit_to_what_they_make(self):
        """The profit rises with the stock for ever when more is held that rises with it than is sold that does: a call
        bought, shares, and no call sold against them. A single breakeven, above the strike or the price paid."""
        for kind in ("long-call", "long-stock", "protective-put"):
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertTrue(all(x != x for x in table["max-profit"]), kind)
            self.assertTrue(all(x == x for x in table["breakeven-1"]), kind)
            self.assertTrue(all(x != x for x in table["breakeven-2"]), kind)
        # a put sold or bought, shares with a call sold, or a collar, gain nothing more past the highest strike
        for kind in ("long-put", "cash-secured-put", "covered-call", "collar"):
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertTrue(all(x == x for x in table["max-profit"]), kind)

    def test_the_credit_spreads_are_paid_and_the_debit_spreads_pay(self):
        for kind, credit in [("bull-call", False), ("bear-call", True), ("bull-put", True), ("bear-put", False),
                             ("iron-condor", True), ("iron-butterfly", True), ("long-straddle", False), ("long-strangle", False),
                             ("long-call", False), ("long-put", False), ("cash-secured-put", True)]:
            with self.subTest(kind=kind):
                table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
                self.assertEqual(all(c < 0 for c in table["cost"]), credit)
                if credit:                                 # the most it can make is the credit it is paid
                    np.testing.assert_allclose(table["max-profit"], [-c for c in table["cost"]], rtol=1e-4)
                else:                                      # the most it can lose is the debit it costs
                    np.testing.assert_allclose(table["max-loss"], table["cost"], rtol=1e-4)

    def test_which_options_a_kind_uses(self):
        """Puts for the put spreads, calls for the call spreads, both for the kinds that use both."""
        for kind, types in [("bull-call", {"C"}), ("bear-put", {"P"}), ("iron-condor", {"C", "P"}), ("long-straddle", {"C", "P"}),
                            ("long-call", {"C"}), ("long-put", {"P"}), ("cash-secured-put", {"P"}), ("covered-call", {"C"}),
                            ("protective-put", {"P"}), ("collar", {"C", "P"}), ("long-stock", set())]:
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            used = {str(s)[12] for column in table if column.startswith("symbol-") for s in table[column]}
            self.assertEqual(used, types, kind)


class TestQuotesAndErrors(OptionSpreadsTestCase):

    BASE = [{"strike": 100, "bid": 6.0, "ask": 6.2}, {"strike": 105, "bid": 3.0, "ask": 3.2},
            {"strike": 110, "bid": 1.2, "ask": 1.4},
            {"strike": 100, "bid": 1.4, "ask": 1.6, "type": "Put"}, {"strike": 105, "bid": 3.7, "ask": 3.9, "type": "Put"},
            {"strike": 110, "bid": 6.8, "ask": 7.0, "type": "Put"}]

    def strike_set(self, kind, rows, options="", expected=108):
        self.make_chain(rows)
        table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) %s %s)" % (kind, expected, options))
        return sorted({s for name in table if name.startswith("strike-") for s in table[name]})

    def test_every_option_of_a_spread_must_have_a_quote_open_interest_and_volume(self):
        extra = lambda **fields: self.BASE + [dict({"strike": 115, "bid": 0.3, "ask": 0.5}, **fields),
                                              dict({"strike": 115, "bid": 11.0, "ask": 11.2, "type": "Put"}, **fields)]
        for kind in ("bull-call", "iron-condor", "long-strangle", "long-call", "cash-secured-put", "covered-call", "collar"):
            with self.subTest(kind=kind):
                whole = self.strike_set(kind, extra())
                self.assertIn(115, whole)
                for bad in ({"bid": 0.0}, {"ask": NAN}, {"open_interest": 0}, {"volume": 0}, {"open_interest": NAN}, {"volume": NAN}):
                    self.assertNotIn(115, self.strike_set(kind, extra(**bad)), bad)
                self.assertIn(115, self.strike_set(kind, extra(volume=0), ":min-volume 0"))
                self.assertIn(115, self.strike_set(kind, extra(open_interest=0), ":min-open-interest 0"))
                self.assertNotIn(115, self.strike_set(kind, extra(open_interest=3), ":min-open-interest 4"))
                self.assertNotIn(115, self.strike_set(kind, extra(volume=3), ":min-volume 4"))

    def test_only_options_that_expire_on_the_day_count(self):
        december = datetime.date(2026, 12, 18)
        rows = self.BASE + [{"strike": 102.5, "bid": 7.0, "ask": 7.2, "expiration": december},
                            {"strike": 102.5, "bid": 2.0, "ask": 2.2, "type": "Put", "expiration": december}]
        for kind in ("bull-call", "bull-put", "iron-condor", "long-straddle", "long-put", "covered-call", "collar"):
            self.assertNotIn(102.5, self.strike_set(kind, rows), kind)
        self.make_chain(rows)
        table = self.spreads("(option-spreads-for-chain chain 'bull-call \"2026-12-18\" 108)")      # (the day may be text)
        self.assertEqual(len(table["ratio"]), 0)                  # only one December call: no spread

    def test_a_kind_that_needs_a_type_of_option_the_day_does_not_have_is_an_error(self):
        self.make_chain([r for r in self.BASE if r["type" if "type" in r else "bid"] != "Put"])      # no puts at all
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")["ratio"]), 3)
        for kind in ("bull-put", "bear-put", "put-butterfly", "iron-condor", "long-straddle", "long-strangle",
                     "long-put", "cash-secured-put", "protective-put", "collar"):
            with self.subTest(kind=kind):
                self.assertLispError("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind,
                                     "the chain has no puts expiring on 2026-11-20; its puts expire on no day at all")
        # the kinds that need only calls, or no option at all, are not stopped by it
        for kind, rows in [("long-call", 3), ("covered-call", 3), ("long-stock", 1)]:
            self.assertEqual(len(self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)["ratio"]), rows, kind)
        self.make_chain(self.BASE)
        self.assertLispError("(option-spreads-for-chain chain 'bull-call (date 2026 11 27) 108)",
                             "no calls expiring on 2026-11-27; its calls expire on 2026-11-20")

    def test_options_of_different_roots_are_not_mixed(self):
        """SPX and SPXW options have the same strikes and expirations, and are not the same contract."""
        rows = []
        for root, shift in (("XYZ", 0.0), ("XYZW", 0.1)):
            for strike, call, put in [(100, 6.1, 1.5), (105, 3.1, 3.8), (110, 1.3, 6.9)]:
                symbol = lambda kind: "%-6s261120%s%08d" % (root, kind, strike * 1000)
                rows.append({"strike": strike, "bid": call - 0.1 + shift, "ask": call + 0.1 + shift, "symbol": symbol("C")})
                rows.append({"strike": strike, "bid": put - 0.1 + shift, "ask": put + 0.1 + shift, "type": "Put", "symbol": symbol("P")})
        self.make_chain(rows)
        # (the totals: three strikes of each type, in each of the two roots; the stock has no root)
        for kind, total in [("bull-call", 6), ("call-butterfly", 2), ("iron-condor", 0), ("long-straddle", 6),
                            ("long-strangle", 6), ("long-call", 6), ("cash-secured-put", 6), ("covered-call", 6),
                            ("protective-put", 6), ("collar", 6), ("long-stock", 1)]:
            with self.subTest(kind=kind):
                table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
                self.assertEqual(len(table["ratio"]), total)
                for i in range(len(table["ratio"])):
                    roots = {str(table[column][i])[:6].strip() for column in table if column.startswith("symbol-")}
                    self.assertEqual(len(roots), 0 if kind == "long-stock" else 1,
                                     [table[c][i] for c in table if c.startswith("symbol-")])

    def test_max_width_leaves_out_the_wide_spreads(self):
        self.make_chain(self.BASE)
        wide = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")
        narrow = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :max-width 5)")
        self.assertEqual(len(wide["ratio"]), 3)
        self.assertEqual(sorted(zip(narrow["strike-1"], narrow["strike-2"])), [(100, 105), (105, 110)])
        none = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :max-width 4.99)")
        self.assertEqual(len(none["ratio"]), 0)
        butterfly = self.spreads("(option-spreads-for-chain chain 'call-butterfly (date 2026 11 20) 108 :max-width 5)")
        self.assertEqual(len(butterfly["ratio"]), 1)
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'call-butterfly (date 2026 11 20) 108 :max-width 4)")["ratio"]), 0)
        # a strangle's width is the distance between its strikes, and a collar's
        strangle = self.spreads("(option-spreads-for-chain chain 'long-strangle (date 2026 11 20) 108 :max-width 5)")
        self.assertEqual(sorted(zip(strangle["strike-1"], strangle["strike-2"])), [(100, 105), (105, 110)])
        collar = self.spreads("(option-spreads-for-chain chain 'collar (date 2026 11 20) 108 :max-width 5)")
        self.assertEqual(sorted(zip(collar["strike-1"], collar["strike-2"])), [(100, 105), (105, 110)])
        # a single option, or shares with one, has no width
        for kind in ("long-call", "covered-call", "protective-put", "long-stock"):
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108 :max-width 0)" % kind)
            self.assertEqual(len(table["ratio"]), 1 if kind == "long-stock" else 3, kind)

    def test_min_risk_leaves_out_the_spreads_that_cannot_lose_much(self):
        self.make_chain(self.BASE)
        table = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :min-risk 2.5)")
        np.testing.assert_allclose(sorted(table["max-loss"]), [3.2, 5.0], rtol=1e-5)
        table = self.spreads("(option-spreads-for-chain chain 'bull-put (date 2026 11 20) 108 :min-risk 3)")
        self.assertTrue(all(x >= 3 for x in table["max-loss"]))
        # a long call can lose what it costs: 6.2, 3.2, and 1.4; and the stock, all 104
        table = self.spreads("(option-spreads-for-chain chain 'long-call (date 2026 11 20) 108 :min-risk 3)")
        np.testing.assert_allclose(sorted(table["max-loss"]), [3.2, 6.2], rtol=1e-5)
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108 :min-risk 105)")["ratio"]), 0)
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108 :min-risk 104)")["ratio"]), 1)

    def test_a_spread_with_nothing_to_lose_comes_from_quotes_that_disagree_and_is_left_out(self):
        # selling the 100 put above its width over the 105 put: buy the 100 put at 1.6, sell the 105 put at 6.8 -- a credit
        # of 5.2 for a spread that can lose nothing (5 - 5.2 < 0)
        self.make_chain([{"strike": 100, "bid": 1.4, "ask": 1.6, "type": "Put"}, {"strike": 105, "bid": 6.8, "ask": 7.0, "type": "Put"}])
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bull-put (date 2026 11 20) 108)")["ratio"]), 0)

    def test_a_credit_as_big_as_the_width_is_no_spread_even_when_the_rounding_leaves_a_sliver(self):
        """Selling the 70 call at 34.92 and buying the 77.5 at 27.42 pays 7.50, the whole width: it can't lose. In 32-bit
        numbers that is a credit of 7.499998 and a loss of 0.000002, and a ratio of millions if the stock is expected
        to fall: left out, as a tenth of a cent is no risk."""
        self.make_chain([{"strike": 70, "bid": 34.92, "ask": 35.0}, {"strike": 77.5, "bid": 27.3, "ask": 27.42}])
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bear-call (date 2026 11 20) 60)")["ratio"]), 0)
        self.make_chain([{"strike": 100, "bid": 8.0, "ask": 8.2}, {"strike": 105, "bid": 2.8, "ask": 3.0}])
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bear-call (date 2026 11 20) 60)")["ratio"]), 0)
        # a cent short of the width is a spread, with a loss of a cent
        self.make_chain([{"strike": 100, "bid": 7.99, "ask": 8.2}, {"strike": 105, "bid": 2.8, "ask": 3.0}])
        table = self.spreads("(option-spreads-for-chain chain 'bear-call (date 2026 11 20) 60)")
        np.testing.assert_allclose(table["max-loss"], [0.01], rtol=1e-3)

    def test_a_search_with_no_option_to_use_finds_an_empty_table_with_the_columns(self):
        """A spread of n options has 3n columns (a symbol, strike, and price for each) and 8 more."""
        self.make_chain(self.BASE)
        for kind, options in [("bull-call", 2), ("call-butterfly", 3), ("iron-condor", 4), ("long-straddle", 2),
                              ("long-call", 1), ("covered-call", 1), ("collar", 2)]:
            with self.subTest(kind=kind):
                table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108 :min-volume 6)" % kind)
                self.assertEqual(len(table["ratio"]), 0)
                self.assertEqual(len(table), 3 * options + 8)
                self.assertEqual(list(table)[-8:], ["cost", "max-loss", "max-profit", "worth", "profit", "ratio",
                                                    "breakeven-1", "breakeven-2"])

    def test_fewer_options_than_a_spread_needs_make_none(self):
        self.make_chain(self.BASE[:1] + self.BASE[3:4])
        for kind in KINDS[:8]:
            with self.subTest(kind=kind):
                self.assertEqual(len(self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)["ratio"]),
                                 1 if kind == "long-straddle" else 0)
        # the chain's only options at the strikes, with nothing quoted
        self.make_chain([{"strike": 100, "bid": 0.0, "ask": 6.2}, {"strike": 105, "bid": 3.0, "ask": 3.2}])
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")["ratio"]), 0)

    def test_one_option_is_enough_for_a_single_option_or_for_shares_with_one(self):
        self.make_chain(self.BASE[:1] + self.BASE[3:4])                  # a call and a put, both at 100
        for kind in ("long-call", "long-put", "cash-secured-put", "covered-call", "protective-put", "long-straddle", "long-stock"):
            with self.subTest(kind=kind):
                self.assertEqual(len(self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)["ratio"]), 1)
        for kind in ("collar", "long-strangle", "bull-call"):
            with self.subTest(kind=kind):
                self.assertEqual(len(self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)["ratio"]), 0)

    def test_the_shares_are_bought_at_the_stock_price_in_the_chain_or_the_one_given(self):
        self.make_chain(self.BASE)                                       # the stock is at 104
        table = self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108)")
        self.assertAlmostEqual(table["cost"][0], 104.0, places=4)
        self.assertShows("(spread-search-stock-price search)", "104.0")
        for kind, strike, cost in [("covered-call", 110, 104.0 - 1.2), ("protective-put", 100, 104.0 + 1.6)]:
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertAlmostEqual(table["cost"][table["strike-1"].index(strike)], cost, places=4)
        # a price given is used, in the cost, in what the search knows, and in the profit
        table = self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108 :stock-price 104.05)")
        self.assertAlmostEqual(table["cost"][0], 104.05, places=4)
        self.assertAlmostEqual(table["profit"][0], 3.95, places=4)
        self.assertShows("(spread-search-stock-price search)", "104.05")
        table = self.spreads("(option-spreads-for-chain chain 'collar (date 2026 11 20) 108 :stock-price 100)")
        best = [c for c, a, b in zip(table["cost"], table["strike-1"], table["strike-2"]) if (a, b) == (100, 110)]
        self.assertAlmostEqual(best[0], 100 + 1.6 - 1.2, places=4)
        # the kinds with no shares don't use it
        with_it = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :stock-price 50)")
        without = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")
        self.assertEqual(with_it["cost"], without["cost"])

    def test_the_stock_price_must_be_a_good_one(self):
        self.make_chain(self.BASE)
        for bad in ("0", "-5", '"104"'):
            self.assertLispError("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108 :stock-price %s)" % bad,
                                 ":stock-price is the price of a share, a number above 0")
        # a chain that doesn't have the stock's price (tastytrade's, perhaps) can't price shares, but can the options
        self.make_chain(self.BASE, price=NAN)
        for kind in ("long-stock", "covered-call", "protective-put", "collar"):
            self.assertLispError("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind,
                                 "the chain has no price for the stock; give :stock-price")
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108 :stock-price 104)")["ratio"]), 1)
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")["ratio"]), 3)
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'long-call (date 2026 11 20) 108)")["ratio"]), 3)

    def test_what_it_will_not_take(self):
        self.make_chain(self.BASE)
        self.assertLispError("(option-spreads-for-chain chain 'bull-calls (date 2026 11 20) 108)",
                             "bull-calls isn't a kind of spread; the kinds are bull-call, bear-call, bull-put, bear-put, "
                             "call-butterfly, put-butterfly, iron-condor, iron-butterfly, long-straddle, long-strangle, "
                             "long-call, long-put, cash-secured-put, long-stock, covered-call, protective-put, collar")
        self.assertLispError("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :prices 'last)",
                             ":prices is 'bid-ask or 'mid")
        self.assertLispError("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :size 2)", "unknown keyword")

    def test_the_kinds_are_listed(self):
        table = {str(n): list(v.items) for n, v in lisp_tables.table_columns(self.run_lisp("(option-spread-kinds)"), "test")}
        self.assertEqual([str(k) for k in table["kind"]], KINDS)
        self.assertEqual(str(table["legs"][0]), "buy call, sell call")
        self.assertEqual(str(table["legs"][4]), "buy call, sell 2 call, buy call")
        self.assertEqual(str(table["legs"][6]), "buy put, sell put, sell call, buy call")
        self.assertEqual([str(l) for l in table["legs"][10:]],
                         ["buy call", "buy put", "sell put", "buy shares", "buy shares, sell call", "buy shares, buy put",
                          "buy shares, buy put, sell call"])
        self.assertEqual([str(s) for s in table["schwab"]],
                         ["VERTICAL"] * 4 + ["BUTTERFLY"] * 2 + ["IRON_CONDOR"] * 2 + ["STRADDLE", "STRANGLE"]
                         + ["a plain order"] * 4 + ["an order for each part"] * 3)
        self.assertTrue(all(len(str(a)) > 40 for a in table["about"]))
        self.assertEqual(list(table), ["kind", "label", "legs", "schwab", "about"])


class TestAgainstAPlainCalculation(OptionSpreadsTestCase):
    """Every spread of every kind, from the definition, in plain Python -- finding the most that can be lost and made
    and the breakevens by looking at the profit at every price from 0 to four times the highest strike in steps
    of a quarter, not from the strikes, as the library does -- on random chains."""

    GRID = np.arange(0, 4 * 130 + 0.25, 0.25)

    def random_rows(self, seed, roots=("XYZ",)):
        rng = np.random.default_rng(seed)
        rows = []
        for root in roots:
            for strike in np.arange(70, 130.01, 2.5):
                if rng.uniform() < 0.25:
                    continue                                               # a gap in the strikes
                for type in ("Call", "Put"):
                    intrinsic = max(104 - strike, 0) if type == "Call" else max(strike - 104, 0)
                    price = intrinsic + rng.uniform(0.3, 4)
                    half = rng.choice([0.05, 0.1, 0.15])
                    row = {"strike": float(strike), "type": type, "bid": round(max(price - half, 0), 2), "ask": round(price + half, 2),
                           "open_interest": int(rng.choice([0, 3, 10, 10, 50, 50])), "volume": int(rng.choice([0, 1, 5, 5, 20])),
                           "symbol": "%-6s261120%s%08d" % (root, type[0], round(strike * 1000))}
                    luck = rng.uniform()
                    if luck < 0.04:
                        row["bid"] = 0.0
                    elif luck < 0.07:
                        row["ask"] = NAN
                    elif luck < 0.09:
                        row["open_interest"] = NAN
                    elif luck < 0.11:
                        row["volume"] = NAN
                    row["mid"] = (row["bid"] + row["ask"]) / 2
                    rows.append(row)
        return rows

    def reference(self, rows, kind, expected, prices="bid-ask", min_oi=1, min_volume=1, min_risk=0.0, max_width=None,
                  stock_price=104.0):
        """{(symbols of the position's options): (strikes, prices, cost, max-loss, max-profit, worth, profit, ratio,
        breakeven-1, breakeven-2)}, as the definition gives them."""
        f32 = lambda x: float(np.float32(x))
        zero = lambda x: 0 if x != x else x
        counts = lambda r: zero(r["open_interest"]) >= min_oi and zero(r["volume"]) >= min_volume
        usable = [r for r in rows if r["bid"] > 0 and r["ask"] == r["ask"] and r["ask"] > 0 and counts(r)]
        legs = LEGS[kind]
        shares = sum(q for t, q in legs if t == "S")
        option_legs = [leg for leg in legs if leg[0] != "S"]
        slope = shares + sum(q for t, q in option_legs if t == "C")      # the profit's slope with the stock very high
        found = {}
        # (each root's options make their own positions; the stock alone has no root, and is one position)
        roots = [None] if not option_legs else sorted({r["symbol"][:6] for r in usable})
        for root in roots:
            options = {t: sorted((r for r in usable if r["symbol"][:6] == root and r["type"][0] == t), key=lambda r: r["strike"])
                       for t in "CP"}
            for combo in self.combos(kind, options, max_width):
                price = lambda r, q: r["mid"] if prices == "mid" else (r["ask"] if q > 0 else r["bid"])
                # (the library's numbers are 32-bit)
                cost = f32(shares * f32(stock_price) + sum(q * f32(price(r, q)) for (t, q), r in zip(option_legs, combo)))
                intrinsic = lambda S: shares * S + sum(q * (np.maximum(S - r["strike"], 0) if t == "C" else np.maximum(r["strike"] - S, 0))
                                                       for (t, q), r in zip(option_legs, combo))
                profit_on_grid = intrinsic(self.GRID) - cost
                max_loss = -profit_on_grid.min()
                if not (max_loss > 0.001 and max_loss >= min_risk):
                    continue
                max_profit = NAN if slope > 0 else profit_on_grid.max()
                roots_of_profit = []
                for a, b, pa, pb in zip(self.GRID[:-1], self.GRID[1:], profit_on_grid[:-1], profit_on_grid[1:]):
                    if (pa < 0 <= pb) or (pa > 0 >= pb):
                        roots_of_profit.append(a + (b - a) * (-pa) / (pb - pa))
                first, last = (min(roots_of_profit), max(roots_of_profit)) if roots_of_profit else (NAN, NAN)
                worth = float(intrinsic(expected))
                found[tuple(r["symbol"] for r in combo)] = (
                    [r["strike"] for r in combo], [f32(price(r, q)) for (t, q), r in zip(option_legs, combo)], cost, max_loss,
                    max_profit, worth, worth - cost, (worth - cost) / max_loss, first, NAN if last == first else last)
        return found

    def combos(self, kind, options, max_width):
        """The options that make the kind's positions, as a tuple of one for each of its option legs, from the
        options of one root: {"C": the calls, "P": the puts}, each by strike."""
        calls, puts = options["C"], options["P"]
        within = lambda width: max_width is None or width <= max_width
        shape = {"bull-call": "vertical", "bear-call": "vertical", "bull-put": "vertical", "bear-put": "vertical",
                 "call-butterfly": "butterfly", "put-butterfly": "butterfly", "iron-condor": "condor",
                 "iron-butterfly": "condor", "long-straddle": "straddle", "long-strangle": "strangle",
                 "long-call": "single", "long-put": "single", "cash-secured-put": "single", "long-stock": "stock",
                 "covered-call": "single", "protective-put": "single", "collar": "strangle"}[kind]
        option_legs = [leg for leg in LEGS[kind] if leg[0] != "S"]
        own = calls if option_legs and option_legs[0][0] == "C" else puts
        if shape == "stock":
            yield ()
        elif shape == "single":
            for a in own:
                yield (a,)
        elif shape == "vertical":
            for a, b in itertools.combinations(own, 2):
                if within(b["strike"] - a["strike"]):
                    yield (a, b)
        elif shape == "butterfly":
            for a, b, c in itertools.combinations(own, 3):
                if b["strike"] - a["strike"] == c["strike"] - b["strike"] and within(b["strike"] - a["strike"]):
                    yield (a, b, c)
        elif shape == "condor":
            for p1, p2 in itertools.combinations(puts, 2):
                for c1, c2 in itertools.combinations(calls, 2):
                    wing = p2["strike"] - p1["strike"]
                    touching = p2["strike"] == c1["strike"]
                    if wing == c2["strike"] - c1["strike"] and within(wing) and (touching if kind == "iron-butterfly"
                                                                                   else p2["strike"] < c1["strike"]):
                        yield (p1, p2, c1, c2)
        elif shape == "straddle":
            for c in calls:
                for p in puts:
                    if c["strike"] == p["strike"]:
                        yield (c, p)
        else:
            for p in puts:
                for c in calls:
                    if p["strike"] < c["strike"] and within(c["strike"] - p["strike"]):
                        yield (p, c)

    def compare(self, kind, rows, expected, options, **python):
        table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) %s %s)" % (kind, expected, options))
        mine = self.reference(rows, kind, expected, **python)
        legs = len([leg for leg in LEGS[kind] if leg[0] != "S"])                    # (the shares have no columns)
        self.assertEqual(len(table["ratio"]), len(mine), "%s %s: number of positions" % (kind, options))
        seen = set()
        for i in range(len(table["ratio"])):
            key = tuple(str(table["symbol-%d" % (n + 1)][i]) for n in range(legs))
            self.assertNotIn(key, seen)
            seen.add(key)
            strikes, prices, *numbers = mine[key]
            got = [table["strike-%d" % (n + 1)][i] for n in range(legs)] + [table["price-%d" % (n + 1)][i] for n in range(legs)] + \
                  [table[c][i] for c in ("cost", "max-loss", "max-profit", "worth", "profit", "ratio", "breakeven-1", "breakeven-2")]
            np.testing.assert_allclose(got, strikes + prices + numbers, rtol=3e-4, atol=3e-4, equal_nan=True,
                                       err_msg="%s %s" % (kind, key))
        self.assertEqual(table["ratio"], sorted(table["ratio"], reverse=True))                 # best first
        return len(mine)

    VARIATIONS = [("", {}), (":prices 'mid", {"prices": "mid"}),
                  (":min-open-interest 10 :min-volume 5", {"min_oi": 10, "min_volume": 5}),
                  (":min-open-interest 0 :min-volume 0 :min-risk 1.5", {"min_oi": 0, "min_volume": 0, "min_risk": 1.5}),
                  (":max-width 12.5", {"max_width": 12.5}),
                  (":stock-price 99.25", {"stock_price": 99.25})]

    def test_every_kind_agrees_with_the_plain_calculation_on_random_chains(self):
        total = {kind: 0 for kind in KINDS}
        for seed in range(3):
            rows = self.random_rows(seed)
            self.make_chain(rows)
            for kind in KINDS:
                for expected in (104, 96.5, 111):
                    for options, python in self.VARIATIONS:
                        with self.subTest(seed=seed, kind=kind, expected=expected, options=options):
                            total[kind] += self.compare(kind, rows, expected, options, **python)
        for kind in KINDS:
            # (the comparison was of something: the stock alone is one position in each of the 54 searches)
            self.assertGreater(total[kind], 40 if kind == "long-stock" else 100, kind)

    def test_and_with_two_roots_in_the_chain(self):
        for seed in (10, 11):
            rows = self.random_rows(seed, roots=("XYZ", "XYZW"))
            self.make_chain(rows)
            for kind in KINDS:
                with self.subTest(seed=seed, kind=kind):
                    self.assertGreater(self.compare(kind, rows, 106, ""), 0)


class TestOrders(OptionSpreadsTestCase):

    WORKED = TestSpreadsByHand.QUOTES

    def setUp(self):
        super().setUp()
        rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in self.WORKED:
            rows.append({"strike": strike, "bid": call_bid, "ask": call_ask})
            rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.make_chain(rows)

    def order(self, kind, call="(option-spread-order search)", expected=108, options=""):
        """The order as Python (the JSON Schwab takes), for the best position of the kind, and the search that found it.
        (A list of orders is a list.)"""
        import lisp_schwab
        self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) %s %s))" % (kind, expected, options))
        with mock.patch.object(lisp_schwab, "schwab_request", side_effect=AssertionError("preparing an order must send nothing")):
            return lisp_schwab.lisp_to_json(self.run_lisp(call))

    def legs(self, order):
        return [(leg["instruction"], leg["instrument"]["symbol"].replace(" ", "_"), leg["quantity"])
                for leg in order["orderLegCollection"]]

    def test_a_debit_spread_is_a_net_debit_order_for_what_it_costs(self):
        order = self.order("bull-call")
        self.assertEqual(order, {
            "session": "NORMAL", "duration": "DAY", "orderType": "NET_DEBIT", "complexOrderStrategyType": "VERTICAL",
            "price": 5.0, "orderStrategyType": "SINGLE",
            "orderLegCollection": [
                {"instruction": "BUY_TO_OPEN", "quantity": 1, "instrument": {"symbol": "XYZ   261120C00100000", "assetType": "OPTION"}},
                {"instruction": "SELL_TO_OPEN", "quantity": 1, "instrument": {"symbol": "XYZ   261120C00110000", "assetType": "OPTION"}}]})
        self.assertEqual(self.order("long-straddle")["orderType"], "NET_DEBIT")

    def test_a_credit_spread_is_a_net_credit_order_for_what_it_pays(self):
        order = self.order("bear-call")
        self.assertEqual((order["orderType"], order["complexOrderStrategyType"], order["price"]), ("NET_CREDIT", "VERTICAL", 0.7))
        self.assertEqual(self.legs(order), [("SELL_TO_OPEN", "XYZ___261120C00110000", 1), ("BUY_TO_OPEN", "XYZ___261120C00115000", 1)])
        order = self.order("iron-condor")
        self.assertEqual((order["orderType"], order["complexOrderStrategyType"], order["price"]), ("NET_CREDIT", "IRON_CONDOR", 2.8))
        self.assertEqual(self.legs(order), [("BUY_TO_OPEN", "XYZ___261120P00100000", 1), ("SELL_TO_OPEN", "XYZ___261120P00105000", 1),
                                            ("SELL_TO_OPEN", "XYZ___261120C00110000", 1), ("BUY_TO_OPEN", "XYZ___261120C00115000", 1)])

    def test_a_butterfly_sells_its_middle_option_twice_as_many_times(self):
        order = self.order("call-butterfly", "(option-spread-order search :contracts 3)")
        self.assertEqual((order["orderType"], order["complexOrderStrategyType"], order["price"]), ("NET_DEBIT", "BUTTERFLY", 1.3))
        self.assertEqual(self.legs(order), [("BUY_TO_OPEN", "XYZ___261120C00105000", 3), ("SELL_TO_OPEN", "XYZ___261120C00110000", 6),
                                            ("BUY_TO_OPEN", "XYZ___261120C00115000", 3)])

    def test_each_kinds_order_has_the_strategy_and_legs_of_its_kind(self):
        for kind, strategy, instructions in [
                ("bull-call", "VERTICAL", ["BUY_TO_OPEN", "SELL_TO_OPEN"]), ("bear-call", "VERTICAL", ["SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("bull-put", "VERTICAL", ["BUY_TO_OPEN", "SELL_TO_OPEN"]), ("bear-put", "VERTICAL", ["SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("call-butterfly", "BUTTERFLY", ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("put-butterfly", "BUTTERFLY", ["BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("iron-condor", "IRON_CONDOR", ["BUY_TO_OPEN", "SELL_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("iron-butterfly", "IRON_CONDOR", ["BUY_TO_OPEN", "SELL_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_OPEN"]),
                ("long-straddle", "STRADDLE", ["BUY_TO_OPEN", "BUY_TO_OPEN"]), ("long-strangle", "STRANGLE", ["BUY_TO_OPEN", "BUY_TO_OPEN"])]:
            with self.subTest(kind=kind):
                order = self.order(kind)
                self.assertEqual(order["complexOrderStrategyType"], strategy)
                self.assertEqual([leg[0] for leg in self.legs(order)], instructions)

    def test_the_order_is_for_the_row_asked_for_at_the_price_asked_for(self):
        best = self.order("bull-call")
        second = self.order("bull-call", "(option-spread-order search :row 1 :contracts 2)")
        self.assertNotEqual(self.legs(best), self.legs(second))
        self.assertTrue(all(leg[2] == 2 for leg in self.legs(second)))
        self.assertEqual(self.order("bull-call", "(option-spread-order search :price 4.85)")["price"], 4.85)
        self.assertEqual(self.order("iron-condor", "(option-spread-order search :price 3.1)")["price"], 3.1)

    def test_a_strategy_name_may_be_given_instead(self):
        import lisp_schwab
        self.run_lisp("(define search (option-spreads-for-chain chain 'iron-butterfly (date 2026 11 20) 108))")
        order = lisp_schwab.lisp_to_json(self.run_lisp('(option-spread-order search :strategy "IRON_CONDOR")'))
        self.assertEqual(order["complexOrderStrategyType"], "IRON_CONDOR")
        self.assertLispError('(option-spread-order search :strategy "IRON_BUTTERFLY")', "the strategy is one of")

    def test_what_the_order_will_not_take(self):
        self.run_lisp("(define search (option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108))")
        self.assertLispError("(option-spread-order search :row 99)", "there is no row 99: the search found 21 spreads")
        for bad in ("0", "1.5", "-1"):
            self.assertLispError("(option-spread-order search :contracts %s)" % bad, "whole number of spreads, 1 or more")
        self.assertLispError("(option-spread-order search :price 0)", "the net debit must be a number above 0")
        self.run_lisp("(define credit (option-spreads-for-chain chain 'bear-call (date 2026 11 20) 108))")
        self.assertLispError("(option-spread-order credit :price -1)", "the net credit must be a number above 0")

    def plain(self, instruction, symbol, quantity, price, asset_type):
        """A plain limit order for one thing, as Python: what schwab-order makes."""
        return {"session": "NORMAL", "duration": "DAY", "orderType": "LIMIT", "orderStrategyType": "SINGLE", "price": price,
                "orderLegCollection": [{"instruction": instruction, "quantity": quantity,
                                        "instrument": {"symbol": symbol, "assetType": asset_type}}]}

    def test_a_single_option_is_a_plain_limit_order_at_its_price(self):
        self.assertEqual(self.order("long-call"), self.plain("BUY_TO_OPEN", "XYZ   261120C00100000", 1, 6.2, "OPTION"))
        self.assertEqual(self.order("long-put", "(option-spread-order search :contracts 3)"),
                         self.plain("BUY_TO_OPEN", "XYZ   261120P00120000", 3, 15.4, "OPTION"))
        # a put sold is sold at its bid
        self.assertEqual(self.order("cash-secured-put"), self.plain("SELL_TO_OPEN", "XYZ   261120P00110000", 1, 6.8, "OPTION"))
        # the next best, and a price of one's own
        self.assertEqual(self.order("long-call", "(option-spread-order search :row 1 :price 10.55)"),
                         self.plain("BUY_TO_OPEN", "XYZ   261120C00095000", 1, 10.55, "OPTION"))
        # at the middle of the bid and ask, if the search is, rounded to the cent
        self.assertEqual(self.order("long-call", options=":prices 'mid")["price"], 6.1)

    def test_a_limit_price_is_rounded_to_the_cent(self):
        """The middle of a bid and an ask, and the stock's price in a chain, can have more than two decimals; a limit
        price has two."""
        rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in self.WORKED:
            rows.append({"strike": strike, "bid": call_bid, "ask": call_ask,
                         "mid": {100: 6.1234, 110: 1.2345}.get(strike, (call_bid + call_ask) / 2)})
            rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.make_chain(rows)
        self.assertEqual(self.order("long-call", options=":prices 'mid")["price"], 6.12)
        orders = self.order("covered-call", "(option-position-orders search)", options=":prices 'mid :stock-price 104.0567")
        self.assertEqual([order["price"] for order in orders], [104.06, 1.23])
        self.assertEqual(self.order("long-stock", options=":stock-price 104.0567")["price"], 104.06)
        self.assertEqual(self.order("long-call", "(option-spread-order search :price 6.126)", options=":prices 'mid")["price"], 6.13)

    def test_the_long_stock_is_a_plain_limit_order_for_a_hundred_shares_to_a_contract(self):
        self.assertEqual(self.order("long-stock"), self.plain("BUY", "XYZ", 100, 104.0, "EQUITY"))
        self.assertEqual(self.order("long-stock", "(option-spread-order search :contracts 3)"),
                         self.plain("BUY", "XYZ", 300, 104.0, "EQUITY"))
        self.assertEqual(self.order("long-stock", "(option-spread-order search :price 103.5)")["price"], 103.5)
        self.assertEqual(self.order("long-stock", options=":stock-price 104.05")["price"], 104.05)

    def test_a_single_order_has_no_strategy_to_name(self):
        for kind in ("long-call", "long-stock"):
            self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
            self.assertLispError('(option-spread-order search :strategy "VERTICAL")', "is a plain order, with no strategy")

    def test_shares_with_options_are_an_order_for_each_part(self):
        for kind in ("covered-call", "protective-put", "collar"):
            self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
            self.assertLispError("(option-spread-order search)", "is an order for each part, its shares and options: option-position-orders makes them")
        shares = self.plain("BUY", "XYZ", 100, 104.0, "EQUITY")
        self.assertEqual(self.order("covered-call", "(option-position-orders search)"),
                         [shares, self.plain("SELL_TO_OPEN", "XYZ   261120C00110000", 1, 1.2, "OPTION")])
        self.assertEqual(self.order("protective-put", "(option-position-orders search)"),
                         [shares, self.plain("BUY_TO_OPEN", "XYZ   261120P00100000", 1, 1.6, "OPTION")])
        self.assertEqual(self.order("collar", "(option-position-orders search)"),
                         [shares, self.plain("BUY_TO_OPEN", "XYZ   261120P00100000", 1, 1.6, "OPTION"),
                          self.plain("SELL_TO_OPEN", "XYZ   261120C00105000", 1, 3.0, "OPTION")])

    def test_the_orders_for_shares_with_options_are_for_a_hundred_shares_to_a_contract_at_the_prices_of_the_search(self):
        self.assertEqual(self.order("covered-call", "(option-position-orders search :contracts 2)", options=":stock-price 104.05"),
                         [self.plain("BUY", "XYZ", 200, 104.05, "EQUITY"),
                          self.plain("SELL_TO_OPEN", "XYZ   261120C00110000", 2, 1.2, "OPTION")])
        # the next best covered call: the 115 call, which pays 0.3
        self.assertEqual(self.order("covered-call", "(option-position-orders search :row 1)")[1],
                         self.plain("SELL_TO_OPEN", "XYZ   261120C00115000", 1, 0.3, "OPTION"))
        # the middle prices, rounded to the cent: the 110 call at 1.3
        self.assertEqual(self.order("covered-call", "(option-position-orders search)", options=":prices 'mid")[1]["price"], 1.3)

    def test_the_orders_of_a_spread_or_a_single_option_are_a_list_of_the_one_order(self):
        for kind in ("bull-call", "iron-condor", "long-call", "cash-secured-put", "long-stock"):
            with self.subTest(kind=kind):
                one = self.order(kind)
                self.assertEqual(self.order(kind, "(option-position-orders search)"), [one])
                self.assertEqual(self.order(kind, "(option-position-orders search :contracts 2)"),
                                 [self.order(kind, "(option-spread-order search :contracts 2)")])

    def test_what_the_orders_of_shares_with_options_will_not_take(self):
        self.run_lisp("(define search (option-spreads-for-chain chain 'covered-call (date 2026 11 20) 108))")
        self.assertLispError("(option-position-orders search :row 99)", "option-position-orders: there is no row 99: the search found 7 spreads")
        for bad in ("0", "1.5", "-1"):
            self.assertLispError("(option-position-orders search :contracts %s)" % bad, "whole number of spreads, 1 or more")
        self.assertLispError("(option-position-orders search :price 1)", "unknown keyword")

    def test_an_order_can_be_read_in_words_before_it_is_sent(self):
        for kind, call, expected, instructions in [
                ("bull-call", "(option-spread-order search :contracts 3)",
                 "a day order to open 3 spreads, with a limit on the net debit of 5.00 a share (500.00 for each, 1,500.00 in all, at most):",
                 ["  BUY_TO_OPEN   3 x XYZ   261120C00100000\n", "  SELL_TO_OPEN  3 x XYZ   261120C00110000\n"]),
                ("iron-condor", "(option-spread-order search :contracts 2)",
                 "a day order to open 2 iron condors, with a limit on the net credit of 2.80 a share (280.00 for each, 560.00 in all, at least):",
                 ["  BUY_TO_OPEN   2 x XYZ   261120P00100000\n", "  SELL_TO_OPEN  2 x XYZ   261120C00110000\n"]),
                ("call-butterfly", "(option-spread-order search)",
                 "a day order to open 1 butterfly, with a limit on the net debit of 1.30 a share (130.00 for each, 130.00 in all, at most):",
                 ["  SELL_TO_OPEN  2 x XYZ   261120C00110000\n"]),
                ("long-straddle", "(option-spread-order search :contracts 2)", "to open 2 straddles", []),
                ("long-strangle", "(option-spread-order search)", "to open 1 strangle", [])]:
            with self.subTest(kind=kind):
                self.out.clear()
                self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
                self.run_lisp("(show-spread-order %s)" % call)
                shown = self.printed()
                self.assertIn("This order has not been sent. If it were: ", shown)
                self.assertIn(expected, shown)
                for line in instructions:
                    self.assertIn(line, shown)

    def test_a_plain_order_and_a_list_of_orders_can_be_read_in_words_too(self):
        for kind, call, expected in [
                ("long-stock", "(option-spread-order search :contracts 2)",
                 ["This order has not been sent. If it were: a day order with a limit of 104.00 a share (20,800.00 in all, at most):\n",
                  "  BUY           200 x XYZ\n"]),
                ("long-call", "(option-spread-order search :contracts 3)",
                 ["This order has not been sent. If it were: a day order with a limit of 6.20 a share (1,860.00 in all, at most):\n",
                  "  BUY_TO_OPEN   3 x XYZ   261120C00100000\n"]),
                ("cash-secured-put", "(option-spread-order search)",
                 ["a day order with a limit of 6.80 a share (680.00 in all, at least):\n", "  SELL_TO_OPEN  1 x XYZ   261120P00110000\n"]),
                ("collar", "(option-position-orders search)",
                 ["These 3 orders have not been sent. If they were, you would send them in this order, each one filled before the next:\n",
                  "\n1. a day order with a limit of 104.00 a share (10,400.00 in all, at most):\n  BUY           100 x XYZ\n",
                  "\n2. a day order with a limit of 1.60 a share (160.00 in all, at most):\n  BUY_TO_OPEN   1 x XYZ   261120P00100000\n",
                  "\n3. a day order with a limit of 3.00 a share (300.00 in all, at least):\n  SELL_TO_OPEN  1 x XYZ   261120C00105000\n"])]:
            with self.subTest(kind=kind):
                self.out.clear()
                self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
                self.run_lisp("(show-spread-order %s)" % call)
                for text in expected:
                    self.assertIn(text, self.printed())
        # an order that is neither a spread's nor a limit order is said plainly
        self.out.clear()
        self.run_lisp('(show-spread-order (schwab-order "BUY" "XYZ" 5))')
        self.assertIn("a day market order:\n  BUY           5 x XYZ\n", self.printed())

    def test_an_order_from_the_older_functions_is_read_in_words_too(self):
        self.run_lisp('(show-spread-order (schwab-spread-order "XYZ   261120C00100000" "XYZ   261120C00105000" 2 1.5 :duration "good_till_cancel"))')
        self.assertIn("a good_till_cancel order to open 2 spreads", self.printed())


class TestGettingTheChain(OptionSpreadsTestCase):

    def setUp(self):
        super().setUp()
        rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in TestSpreadsByHand.QUOTES:
            rows.append({"strike": strike, "bid": call_bid, "ask": call_ask})
            rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.rows = rows
        self.make_chain(rows)
        self.asked = []
        self.env[lisp_core.Symbol("schwab-option-chain")] = lambda creds, symbol, *options: (
            self.asked.append((str(creds), str(symbol), [lisp_core.to_string(o) for o in options])) or self.env[lisp_core.Symbol("chain")])
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("credentials.json")

    def test_it_asks_schwab_for_the_calls_the_puts_or_both_as_the_kind_needs(self):
        for kind, contracts in [("bull-call", '"CALL"'), ("call-butterfly", '"CALL"'), ("bull-put", '"PUT"'), ("bear-put", '"PUT"'),
                                ("put-butterfly", '"PUT"'), ("iron-condor", '"ALL"'), ("iron-butterfly", '"ALL"'),
                                ("long-straddle", '"ALL"'), ("long-strangle", '"ALL"'),
                                ("long-call", '"CALL"'), ("long-put", '"PUT"'), ("cash-secured-put", '"PUT"'),
                                ("long-stock", '"CALL"'), ("covered-call", '"CALL"'), ("protective-put", '"PUT"'),
                                ("collar", '"ALL"')]:
            with self.subTest(kind=kind):
                del self.asked[:]
                table = self.spreads('(option-spreads creds "XYZ" \'%s "2026-11-20" 108 :prices \'mid :min-risk 0.5)' % kind)
                self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", contracts])])
                self.assertGreater(len(table["ratio"]), 0)
                self.assertShows("(spread-search-prices search)", "mid")                  # its options were passed on
                self.assertShows("(spread-search-kind search)", kind)

    def test_it_gives_the_stock_price_to_the_search(self):
        table = self.spreads('(option-spreads creds "XYZ" \'long-stock "2026-11-20" 108 :stock-price 104.05)')
        self.assertAlmostEqual(table["cost"][0], 104.05, places=4)
        self.assertShows("(spread-search-stock-price search)", "104.05")

    def test_it_takes_only_options_that_have_traded_today_unless_told_otherwise(self):
        rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in TestSpreadsByHand.QUOTES:
            rows.append({"strike": strike, "bid": call_bid, "ask": call_ask, "volume": 0 if strike == 100 else 5})
        self.make_chain(rows)
        for options, strikes in [("", {95, 105, 110, 115, 90, 120}), (":min-volume 0", {90, 95, 100, 105, 110, 115, 120})]:
            with self.subTest(options=options):
                table = self.spreads('(option-spreads creds "XYZ" \'bull-call (date 2026 11 20) 108 %s)' % options)
                self.assertEqual({s for c in ("strike-1", "strike-2") for s in table[c]}, strikes)

    def test_it_says_when_the_market_is_closed(self):
        for moment, closed in [(datetime.datetime(2026, 10, 14, 10, 30), False), (datetime.datetime(2026, 10, 14, 9, 29), True),
                               (datetime.datetime(2026, 10, 14, 16, 0), True), (datetime.datetime(2026, 10, 17, 11, 0), True)]:
            with self.subTest(moment=moment):
                self.out.clear()
                with mock.patch.object(lisp_clock, "now", lambda moment=moment: moment):
                    self.run_lisp('(option-spreads creds "XYZ" \'iron-condor (date 2026 11 20) 108)')
                self.assertEqual("The market is closed now: the bids and asks are from its last close." in self.printed(), closed)

    def test_showing_the_spreads(self):
        for kind, expected_lines in [
                ("bull-call", ["XYZ is at 104.00. Bull call spreads expiring 2026-11-20, if it is at 108.00 then; bought and sold at the ask and bid prices.",
                               "The best: buy 1 100.00 call at 6.20, sell 1 110.00 call at 1.20.",
                               "It costs 5.00 a share: 500.00 for one contract of each option. The most you can lose is 5.00 a share (500.00).",
                               "With XYZ at 108.00 on 2026-11-20, it is worth 8.00 a share, a profit of 3.00 (300.00): 60% of the most you can lose.",
                               "The most it can make is 5.00 a share (500.00). It breaks even with XYZ at 105.00."]),
                ("iron-condor", ["Iron condors expiring 2026-11-20",
                                 "The best: buy 1 100.00 put at 1.60, sell 1 105.00 put at 3.70, sell 1 110.00 call at 1.20, buy 1 115.00 call at 0.50.",
                                 "It pays you 2.80 a share: 280.00 for one contract of each option. The most you can lose is 2.20 a share (220.00).",
                                 "It breaks even with XYZ at 102.20 and at 112.80."]),
                ("call-butterfly", ["Call butterflies expiring", "buy 1 105.00 call at 3.20, sell 2 110.00 calls at 1.20, buy 1 115.00 call at 0.50"]),
                ("long-straddle", ["Long straddles expiring", "There is no limit to what it can make. It breaks even with XYZ at"])]:
            with self.subTest(kind=kind):
                self.out.clear()
                self.run_lisp("(show-option-spreads (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
                shown = self.printed()
                for line in expected_lines:
                    self.assertIn(line, shown)
                self.assertIn("(define order (option-spread-order search :contracts 1))", shown)
                self.assertIn("(schwab-place-order creds \"your account\" order :confirm #t)", shown)
                self.assertNotIn("XYZ   2611", shown)                              # (the symbols are not in the table)
        self.out.clear()
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'bear-put (date 2026 11 20) 108 :prices 'mid) :count 2)")
        self.assertIn("middle prices", self.printed())
        self.assertIn("The best 2, by", self.printed())

    def test_showing_the_single_options_and_the_positions_with_shares(self):
        for kind, expected_lines in [
                ("covered-call", ["XYZ is at 104.00. Covered calls expiring 2026-11-20, if it is at 108.00 then; bought and sold at the ask and bid prices, the shares at 104.00. 7 positions.",
                                  "The best: buy 100 shares at 104.00, sell 1 110.00 call at 1.20.",
                                  "It costs 102.80 a share: 10,280.00 for 100 shares and one contract. The most you can lose is 102.80 a share (10,280.00).",
                                  "With XYZ at 108.00 on 2026-11-20, it is worth 108.00 a share, a profit of 5.20 (520.00): 5% of the most you can lose.",
                                  "The most it can make is 7.20 a share (720.00). It breaks even with XYZ at 102.80."]),
                ("collar", ["Collars expiring 2026-11-20", "21 positions.",
                            "The best: buy 100 shares at 104.00, buy 1 100.00 put at 1.60, sell 1 105.00 call at 3.00.",
                            "It costs 102.60 a share: 10,260.00 for 100 shares and one contract of each option. The most you can lose is 2.60 a share (260.00)."]),
                ("protective-put", ["Protective puts expiring", "The best: buy 100 shares at 104.00, buy 1 100.00 put at 1.60.",
                                    "There is no limit to what it can make. It breaks even with XYZ at 105.60."]),
                ("long-call", ["Long calls expiring 2026-11-20, if it is at 108.00 then; bought and sold at the ask and bid prices. 7 positions.",
                               "The best: buy 1 100.00 call at 6.20.",
                               "It costs 6.20 a share: 620.00 for one contract. The most you can lose is 6.20 a share (620.00)."]),
                ("cash-secured-put", ["Cash-secured puts expiring", "The best: sell 1 110.00 put at 6.80.",
                                      "It pays you 6.80 a share: 680.00 for one contract. The most you can lose is 103.20 a share (10,320.00)."]),
                ("long-stock", ["XYZ is at 104.00. Owning 100 shares of it, if it is at 108.00 on 2026-11-20. 1 position.",
                                "The best: buy 100 shares at 104.00.",
                                "It costs 104.00 a share: 10,400.00 for 100 shares. The most you can lose is 104.00 a share (10,400.00).",
                                "There is no limit to what it can make. It breaks even with XYZ at 104.00."])]:
            with self.subTest(kind=kind):
                self.out.clear()
                self.run_lisp("(show-option-spreads (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
                shown = self.printed()
                for line in expected_lines:
                    self.assertIn(line, shown)
                self.assertNotIn("XYZ   2611", shown)
                # how to go on to an order: one order, or an order for each part
                if kind in ("covered-call", "collar", "protective-put"):
                    self.assertIn("(define orders (option-position-orders search :contracts 1))", shown)
                    self.assertIn("(dolist (order orders) (schwab-preview-order creds \"your account\" order))", shown)
                    self.assertIn("(schwab-place-order creds \"your account\" (first orders) :confirm #t)", shown)
                    self.assertNotIn("(option-spread-order search", shown)
                else:
                    self.assertIn("(define order (option-spread-order search :contracts 1))", shown)

    def test_every_search_but_the_stocks_says_how_owning_the_stock_would_do(self):
        for kind in ("bull-call", "iron-condor", "long-call", "covered-call", "collar"):
            with self.subTest(kind=kind):
                self.out.clear()
                self.run_lisp("(show-option-spreads (option-spreads-for-chain chain '%s (date 2026 11 20) 108))" % kind)
                self.assertIn("For comparison, owning the stock instead (100 shares at 104.00): a profit of 4.00 a share (400.00) "
                              "with XYZ at 108.00, 3.8% of the 104.00 a share they could lose.", self.printed())
        # (at the price given, if one is, and a loss as the number it is)
        self.out.clear()
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'long-call (date 2026 11 20) 100 :stock-price 105))")
        self.assertIn("(100 shares at 105.00): a loss of 5.00 a share (500.00) with XYZ at 100.00, -4.8% of the 105.00", self.printed())
        # (the best long call for 100 is the 90, worth 10 for the 15.10 paid)
        self.assertIn("it is worth 10.00 a share, a loss of 5.10 (510.00): -34% of the most you can lose.", self.printed())
        self.out.clear()
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'long-stock (date 2026 11 20) 108))")
        self.assertNotIn("For comparison", self.printed())

    def test_showing_a_search_that_found_nothing_says_why(self):
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108 :min-volume 6))")
        self.assertIn("No such spread can be made", self.printed())
        self.assertIn("give :min-volume 0", self.printed())
        self.assertIn("prices. 0 spreads.", self.printed())
        self.out.clear()
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'covered-call (date 2026 11 20) 108 :min-volume 6))")
        self.assertIn("No such position can be made", self.printed())
        self.assertIn("0 positions.", self.printed())

    def test_one_spread_is_not_spreads(self):
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108 :max-width 5 "
                      ":min-risk 4.6))")
        self.assertIn("prices. 1 spread.", self.printed())

    def test_the_example_charts_as_many_positions_as_there_are(self):
        def run(kind):
            lisp_builtins.set_command_line_arguments(["XYZ", kind, "2026-11-20", "108"])
            with in_a_temporary_folder() as folder:
                lisp_core.run_file(os.path.join(EXAMPLES, "option_spreads_example.lsp"), self.env)
                return sorted(os.listdir(folder))
        try:
            self.assertEqual(run("long-stock"), ["option_spreads_profit.png"])          # (one position: nothing to compare it with)
            self.assertEqual(run("iron-condor"), ["option_spreads_compared.png", "option_spreads_profit.png"])
            self.out.clear()
            self.make_chain([dict(row, bid=0.0) for row in self.rows])                   # no option has a bid: no position
            self.assertEqual(run("iron-condor"), [])
            self.assertIn("No such spread can be made", self.printed())
        finally:
            lisp_builtins.set_command_line_arguments([])

    def test_the_example_takes_the_stock_the_kind_the_day_and_the_price_from_the_command_line(self):
        try:
            lisp_builtins.set_command_line_arguments(["XYZ", "iron-condor", "2026-11-20", "108"])
            with in_a_temporary_folder() as folder:
                lisp_core.run_file(os.path.join(EXAMPLES, "option_spreads_example.lsp"), self.env)
                for chart in ("option_spreads_profit.png", "option_spreads_compared.png"):
                    self.assertTrue(is_a_png(os.path.join(folder, chart)), chart)
            self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", '"ALL"'])])
            self.assertIn("Iron condors expiring 2026-11-20", self.printed())
            self.assertIn("[chart] Iron condor on XYZ, expiring 2026-11-20\n", self.printed())
            self.assertIn("[chart] Iron condors on XYZ, expiring 2026-11-20: the best 3 compared\n", self.printed())
            for bad in (["XYZ"], ["XYZ", "iron-condor", "2026-11-20"]):
                lisp_builtins.set_command_line_arguments(bad)
                with self.assertRaises(lisp_core.LispError) as caught:
                    lisp_core.run_file(os.path.join(EXAMPLES, "option_spreads_example.lsp"), self.env)
                self.assertIn("Give the stock, the kind of spread", str(caught.exception))
            lisp_builtins.set_command_line_arguments(["XYZ", "iron-bat", "2026-11-20", "108"])
            with self.assertRaises(lisp_core.LispError) as caught:
                lisp_core.run_file(os.path.join(EXAMPLES, "option_spreads_example.lsp"), self.env)
            self.assertIn("iron-bat isn't a kind of spread", str(caught.exception))
        finally:
            lisp_builtins.set_command_line_arguments([])


class TestComparingTheKinds(OptionSpreadsTestCase):
    """lib/option_positions.lsp: the best position of each kind, ranked together, with owning the stock among them."""

    DAY = datetime.date(2026, 11, 20)

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "option_positions.lsp")')
        self.rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in TestSpreadsByHand.QUOTES:
            self.rows.append({"strike": strike, "bid": call_bid, "ask": call_ask})
            self.rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.make_chain(self.rows)
        self.asked = []
        self.env[lisp_core.Symbol("schwab-option-chain")] = lambda creds, symbol, *options: (
            self.asked.append((str(creds), str(symbol), [lisp_core.to_string(o) for o in options])) or self.env[lisp_core.Symbol("chain")])
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("credentials.json")

    def positions(self, call):
        """The table of the comparison that the call (Lisp source) makes, as a dict of columns, as Python lists."""
        self.run_lisp("(define comparison %s)" % call)
        table = self.run_lisp("(position-comparison-positions comparison)")
        return {str(name): list(vector.items) for name, vector in lisp_tables.table_columns(table, "test")}

    def kinds_of(self, table):
        return sorted(str(kind) for kind in table["kind"])

    COMPARE = "(option-positions-for-chain chain (date 2026 11 20) 108%s)"

    def test_the_best_position_of_each_kind_is_a_row_best_first(self):
        table = self.positions(self.COMPARE % "")
        self.assertEqual(self.kinds_of(table), sorted(KINDS))
        self.assertEqual(list(table), ["kind", "position", "cost", "max-loss", "max-profit", "worth", "profit", "ratio",
                                       "breakeven-1", "breakeven-2"])
        self.assertEqual(table["ratio"], sorted(table["ratio"], reverse=True))
        for i, kind in enumerate(table["kind"]):                       # each row is the best of its kind's search
            best = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            for column in ("cost", "max-loss", "max-profit", "worth", "profit", "ratio", "breakeven-1", "breakeven-2"):
                np.testing.assert_allclose(table[column][i], best[column][0], rtol=1e-5, equal_nan=True, err_msg="%s %s" % (kind, column))

    def test_the_numbers_of_some_of_the_kinds_by_hand(self):
        """With the stock at 108: the iron condor of the 100, 105, 110, and 115 gets 2.8 and can lose 2.2; the bull
        call spread of the 100 and 110 costs 5.0 and makes 3.0; the collar of the 100 put and the 105 call costs
        104 + 1.6 - 3.0 = 102.6, is worth 105, and can lose 2.6; and so on."""
        table = self.positions(self.COMPARE % "")
        row = {str(kind): i for i, kind in enumerate(table["kind"])}
        for kind, profit, loss in [("iron-condor", 2.8, 2.2), ("bull-call", 3.0, 5.0), ("collar", 2.4, 2.6),
                                   ("protective-put", 2.4, 5.6), ("long-call", 1.8, 6.2), ("covered-call", 5.2, 102.8),
                                   ("cash-secured-put", 4.8, 103.2), ("long-stock", 4.0, 104.0)]:
            with self.subTest(kind=kind):
                self.assertAlmostEqual(table["ratio"][row[kind]], profit / loss, places=4)
                self.assertAlmostEqual(table["profit"][row[kind]], profit, places=4)
                self.assertAlmostEqual(table["max-loss"][row[kind]], loss, places=4)
        for kind, words in [("iron-condor", "buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call"),
                            ("collar", "buy 100 shares, buy 1 100.00 put, sell 1 105.00 call"),
                            ("call-butterfly", "buy 1 105.00 call, sell 2 110.00 calls, buy 1 115.00 call"),
                            ("covered-call", "buy 100 shares, sell 1 110.00 call"), ("long-stock", "buy 100 shares"),
                            ("cash-secured-put", "sell 1 110.00 put")]:
            self.assertEqual(str(table["position"][row[kind]]), words)

    def test_owning_the_stock_is_a_row_like_the_others(self):
        for expected, options, price in [(108, "", 104.0), (108, " :stock-price 100", 100.0), (90, "", 104.0), (104, "", 104.0)]:
            with self.subTest(expected=expected, options=options):
                table = self.positions("(option-positions-for-chain chain (date 2026 11 20) %s%s)" % (expected, options))
                i = [str(kind) for kind in table["kind"]].index("long-stock")
                self.assertAlmostEqual(table["cost"][i], price, places=4)
                self.assertAlmostEqual(table["max-loss"][i], price, places=4)
                self.assertAlmostEqual(table["profit"][i], expected - price, places=4)
                self.assertAlmostEqual(table["ratio"][i], (expected - price) / price, places=5)
                self.assertAlmostEqual(table["breakeven-1"][i], price, places=4)
                self.assertTrue(table["max-profit"][i] != table["max-profit"][i])                 # (no limit)
                self.assertTrue(table["breakeven-2"][i] != table["breakeven-2"][i])

    def test_the_kinds_may_be_chosen(self):
        table = self.positions(self.COMPARE % " :kinds '(covered-call long-stock iron-condor)")
        self.assertEqual(self.kinds_of(table), ["covered-call", "iron-condor", "long-stock"])
        self.assertEqual(self.kinds_of(self.positions(self.COMPARE % " :kinds '(collar)")), ["collar"])
        self.assertLispError(self.COMPARE % " :kinds '(covered-call put-spread)", "put-spread isn't a kind of spread")

    def test_the_options_of_the_search_are_those_of_option_spreads(self):
        """:prices, :min-open-interest, :min-volume, :min-risk, :max-width, and :stock-price go to each kind's search."""
        for options in (" :prices 'mid", " :min-risk 3", " :max-width 5", " :min-volume 0 :min-open-interest 0",
                        " :stock-price 101.5"):
            with self.subTest(options=options):
                table = self.positions(self.COMPARE % options)
                for i, kind in enumerate(table["kind"]):
                    best = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108%s)" % (kind, options))
                    np.testing.assert_allclose(table["ratio"][i], best["ratio"][0], rtol=1e-5, err_msg=str(kind))
        self.assertLessEqual(min(self.positions(self.COMPARE % " :min-risk 3")["max-loss"]) + 1e-6, 104.0)
        self.assertGreaterEqual(min(self.positions(self.COMPARE % " :min-risk 3")["max-loss"]), 3.0)

    def test_the_kinds_the_chain_cannot_make_are_left_out(self):
        # no puts on the day: the kinds that need puts are left out, not an error
        self.make_chain([row for row in self.rows if row.get("type") != "Put"])
        table = self.positions(self.COMPARE % "")
        self.assertEqual(self.kinds_of(table), ["bear-call", "bull-call", "call-butterfly", "covered-call", "long-call", "long-stock"])
        # no calls
        self.make_chain([row for row in self.rows if row.get("type") == "Put"])
        self.assertEqual(self.kinds_of(self.positions(self.COMPARE % "")),
                         ["bear-put", "bull-put", "cash-secured-put", "long-put", "long-stock", "protective-put", "put-butterfly"])
        # no options on the day at all: the stock alone
        self.make_chain([dict(row, expiration=datetime.date(2026, 12, 18)) for row in self.rows])
        self.assertEqual(self.kinds_of(self.positions(self.COMPARE % "")), ["long-stock"])
        # options, but none that count: the stock alone
        self.make_chain(self.rows)
        self.assertEqual(self.kinds_of(self.positions(self.COMPARE % " :min-volume 6")), ["long-stock"])
        # one call: no spread, but the kinds of one option
        self.make_chain(self.rows[:1])
        self.assertEqual(self.kinds_of(self.positions(self.COMPARE % "")), ["covered-call", "long-call", "long-stock"])

    def test_the_searches_are_kept_to_look_closer_or_to_order_from(self):
        self.run_lisp("(define comparison %s)" % (self.COMPARE % ""))
        self.run_lisp("(define search (position-comparison-search comparison 'covered-call))")
        self.assertShows("(spread-search-kind search)", "covered-call")
        self.assertShows("(table-row-count (spread-search-spreads search))", "7")
        orders = lisp_schwab_json(self.run_lisp("(option-position-orders search)"))
        self.assertEqual([order["orderLegCollection"][0]["instruction"] for order in orders], ["BUY", "SELL_TO_OPEN"])
        for expression, expected in [("(position-comparison-stock comparison)", '"XYZ"'),
                                     ("(position-comparison-stock-price comparison)", "104.0"),
                                     ("(position-comparison-expiration comparison)", "2026-11-20"),
                                     ("(position-comparison-expected-price comparison)", "108"),
                                     ("(position-comparison-prices comparison)", "bid-ask"),
                                     ("(table-row-count (position-comparison-positions comparison))", "17"),
                                     ("(length (position-comparison-searches comparison))", "17")]:
            self.assertShows(expression, expected)
        self.assertLispError("(position-comparison-search comparison 'bull-calls)", "the comparison has no bull-calls; it has ")
        self.run_lisp("(define small %s)" % (self.COMPARE % " :kinds '(collar long-stock) :stock-price 101"))
        self.assertShows("(position-comparison-stock-price small)", "101")
        self.assertLispError("(position-comparison-search small 'covered-call)",
                             "the comparison has no covered-call; it has collar, long-stock")

    def test_showing_the_comparison(self):
        self.run_lisp("(show-option-positions (option-positions-for-chain chain (date 2026 11 20) 108))")
        shown = self.printed()
        for text in ["XYZ is at 104.00. The best position of each kind expiring 2026-11-20, if it is at 108.00 then; "
                     "options bought and sold at the ask and bid prices, shares at 104.00. 17 positions.",
                     "Ranked by the ratio of profit to the most that can be lost (prices are for a share):",
                     "Owning the stock (long-stock) is number 16 of 17, with a ratio of 3.8%: 15 of the positions make more for "
                     "each dollar they could lose, with XYZ at 108.00 on 2026-11-20.",
                     "(define search (position-comparison-search comparison 'covered-call))"]:
            self.assertIn(text, shown)
        lines = shown.split("\n")
        header = [line for line in lines if line.startswith("kind ")][0]
        for column in ("position", "cost", "max-loss", "max-profit", "profit", "ratio", "breakeven-1", "breakeven-2"):
            self.assertIn(column, header)
        self.assertNotIn("worth", header)
        condor = [line for line in lines if line.startswith("iron-condor ")][0]
        for text in ("buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call", "-2.80", "2.20", "2.80", "127.3%",
                     "102.20", "112.80"):
            self.assertIn(text, condor)
        self.assertEqual(sum(1 for line in lines if line.startswith(tuple(KINDS))), 17)          # a row for each kind
        self.assertNotIn("XYZ   2611", shown)

    def test_showing_the_first_few_and_the_other_ways_it_can_be_asked_for(self):
        self.run_lisp("(show-option-positions (option-positions-for-chain chain (date 2026 11 20) 108) :count 3)")
        lines = self.printed().split("\n")
        self.assertEqual(sum(1 for line in lines if line.startswith(tuple(KINDS))), 3)
        self.assertIn("is number 16 of 17", self.printed())                  # (the stock is still placed)
        self.out.clear()
        self.run_lisp("(show-option-positions (option-positions-for-chain chain (date 2026 11 20) 108 :prices 'mid :stock-price 100))")
        self.assertIn("options bought and sold at the middle prices, shares at 100.00.", self.printed())
        self.out.clear()
        self.run_lisp("(show-option-positions %s)" % (self.COMPARE % " :kinds '(covered-call collar)"))
        self.assertIn("2 positions.", self.printed())
        self.assertIn("Owning the stock is not among them.", self.printed())
        self.out.clear()
        self.run_lisp("(show-option-positions %s)" % (self.COMPARE % " :kinds '(long-stock)"))
        self.assertIn("1 position.", self.printed())
        self.assertIn("Owning the stock (long-stock) is number 1 of 1, with a ratio of 3.8%: 0 of the positions make more", self.printed())

    def test_showing_a_comparison_of_nothing_says_why(self):
        self.run_lisp("(show-option-positions %s)" % (self.COMPARE % " :kinds '(bull-call) :min-volume 6"))
        self.assertIn("0 positions.", self.printed())
        self.assertIn("No position can be made", self.printed())
        self.assertIn("give :min-volume 0", self.printed())

    def test_it_asks_schwab_for_the_calls_and_puts_that_the_kinds_need(self):
        for options, contracts in [("", '"ALL"'), (" :kinds '(long-call covered-call long-stock)", '"CALL"'),
                                   (" :kinds '(long-put)", '"PUT"'), (" :kinds '(long-stock)", '"CALL"'),
                                   (" :kinds '(covered-call protective-put)", '"ALL"')]:
            with self.subTest(options=options):
                del self.asked[:]
                self.run_lisp('(define comparison (option-positions creds "XYZ" "2026-11-20" 108%s))' % options)
                self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", contracts])])
                self.assertShows("(position-comparison-expected-price comparison)", "108")
        table = self.positions('(option-positions creds "XYZ" (date 2026 11 20) 108 :stock-price 99 :prices \'mid :min-volume 0)')
        i = [str(kind) for kind in table["kind"]].index("long-stock")
        self.assertAlmostEqual(table["cost"][i], 99.0, places=4)
        self.assertShows("(position-comparison-prices comparison)", "mid")

    def test_it_says_when_the_market_is_closed(self):
        for moment, closed in [(datetime.datetime(2026, 10, 14, 10, 30), False), (datetime.datetime(2026, 10, 14, 16, 0), True)]:
            with self.subTest(moment=moment):
                self.out.clear()
                with mock.patch.object(lisp_clock, "now", lambda moment=moment: moment):
                    self.run_lisp('(option-positions creds "XYZ" (date 2026 11 20) 108)')
                self.assertEqual("The market is closed now: the bids and asks are from its last close." in self.printed(), closed)

    def test_the_example_takes_the_stock_the_day_and_the_price_from_the_command_line(self):
        try:
            lisp_builtins.set_command_line_arguments(["XYZ", "2026-11-20", "108"])
            with in_a_temporary_folder() as folder:
                lisp_core.run_file(os.path.join(EXAMPLES, "option_positions_example.lsp"), self.env)
                for chart in ("option_positions_profit.png", "option_positions_hedged.png"):
                    self.assertTrue(is_a_png(os.path.join(folder, chart)), chart)
            self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", '"ALL"'])])
            self.assertIn("The best position of each kind expiring 2026-11-20", self.printed())
            self.assertIn("Owning the stock (long-stock) is number 16 of 17", self.printed())
            self.assertIn("[chart] The best position of each kind on XYZ, expiring 2026-11-20\n  put-butterfly (profit 4.60)", self.printed())
            self.assertIn("  long-stock (profit 4.00): ", self.printed())
            lisp_builtins.set_command_line_arguments(["XYZ", "2026-11-20"])
            with self.assertRaises(lisp_core.LispError) as caught:
                lisp_core.run_file(os.path.join(EXAMPLES, "option_positions_example.lsp"), self.env)
            self.assertIn("Give the stock, the expiration day, and the price you expect", str(caught.exception))
        finally:
            lisp_builtins.set_command_line_arguments([])


def lisp_schwab_json(value):
    """A Lisp value (a hash table of an order, or a list of them) as the Python JSON Schwab takes."""
    import lisp_schwab
    return lisp_schwab.lisp_to_json(value)


def profit_of(kind, strikes, cost, price):
    """The profit, for a share, of a position of the kind with these strikes (lowest first) that cost this, on the
    expiration day with the stock at the price, by the definition: what it is worth then, less the cost."""
    legs = LEGS[kind]
    shares = sum(q for t, q in legs if t == "S")
    options = [leg for leg in legs if leg[0] != "S"]
    worth = shares * price + sum(q * (max(price - k, 0) if t == "C" else max(k - price, 0))
                                 for (t, q), k in zip(options, strikes))
    return worth - cost


class TestProfitCharts(OptionSpreadsTestCase):
    """The charts of a position's profit on the expiration day, up the side, against the price of the stock then,
    along the bottom: option-profit-curve, plot-option-profit, option-profit-panel, plot-option-positions, and
    plot-call-spreads."""

    EXPECTED = "(date 2026 11 20) 108"

    def setUp(self):
        super().setUp()
        self.specs = []                                     # the charts that are plotted
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)
        for library in ("option_spreads.lsp", "option_positions.lsp", "call_spreads.lsp"):
            self.run_lisp('(load "%s")' % library)
        self.rows = []
        for strike, (call_bid, call_ask), (put_bid, put_ask) in TestSpreadsByHand.QUOTES:
            self.rows.append({"strike": strike, "bid": call_bid, "ask": call_ask})
            self.rows.append({"strike": strike, "bid": put_bid, "ask": put_ask, "type": "Put"})
        self.make_chain(self.rows)

    def position(self, kind, options=""):
        """The first position of the kind: its strikes, cost, and breakevens, from the search (which is `search`)."""
        table = self.spreads("(option-spreads-for-chain chain '%s %s %s)" % (kind, self.EXPECTED, options))
        option_legs = len([leg for leg in LEGS[kind] if leg[0] != "S"])
        return ([table["strike-%d" % (n + 1)][0] for n in range(option_legs)], table["cost"][0],
                [b for b in (table["breakeven-1"][0], table["breakeven-2"][0]) if b == b])

    def curve(self, call):
        """The table that the call (Lisp source) makes, as a dict of columns, as Python lists."""
        table = self.run_lisp(call)
        return {str(name): list(vector.items) for name, vector in lisp_tables.table_columns(table, "test")}

    def labels(self, spec):
        return [series["label"] for series in spec["series"]]

    # -- the numbers: option-profit-curve ---------------------------------------------------------------------

    def test_the_profit_curve_is_the_profit_at_each_price_for_every_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                strikes, cost, breakevens = self.position(kind)
                curve = self.curve("(option-profit-curve search)")
                prices, profits = curve["price"], curve["profit"]
                self.assertEqual(list(curve), ["price", "profit"])
                self.assertTrue(all(a < b for a, b in zip(prices, prices[1:])), "prices rise")
                self.assertGreaterEqual(len(prices), 200)
                np.testing.assert_allclose(profits, [profit_of(kind, strikes, cost, price) for price in prices], atol=1e-3)
                # through every strike and breakeven, where the line bends or crosses 0
                for price in strikes + breakevens:
                    self.assertTrue(any(abs(p - price) < 1e-4 for p in prices), "%s is charted" % price)
                # from 15% below the lowest price that matters to 15% above the highest
                matter = strikes + breakevens + [104.0, 108.0]            # (the stock now, and expected)
                self.assertAlmostEqual(prices[0], max(0, 0.85 * min(matter)), places=3)
                self.assertAlmostEqual(prices[-1], 1.15 * max(matter), places=3)

    def test_the_prices_can_be_chosen(self):
        """The iron condor of the 100, 105, 110, and 115 breaks even at 102.2 and 112.8."""
        self.position("iron-condor")
        curve = self.curve("(option-profit-curve search :low 90 :high 120 :points 7)")
        np.testing.assert_allclose(curve["price"], [90, 95, 100, 102.2, 105, 110, 112.8, 115, 120], atol=1e-4)
        np.testing.assert_allclose(curve["profit"], [-2.2, -2.2, -2.2, 0, 2.8, 2.8, 0, -2.2, -2.2], atol=1e-4)
        # a range that leaves some of the strikes out leaves them out
        curve = self.curve("(option-profit-curve search :low 101 :high 111 :points 3)")
        np.testing.assert_allclose(curve["price"], [101, 102.2, 105, 106, 110, 111], atol=1e-4)
        # the next best position, and the best of another kind
        second = self.curve("(option-profit-curve search :row 1 :points 5)")
        self.assertNotEqual(second["profit"], self.curve("(option-profit-curve search :points 5)")["profit"])
        self.position("long-stock")
        np.testing.assert_allclose(self.curve("(option-profit-curve search :low 100 :high 110 :points 3)")["profit"],
                                   [-4, 0, 1, 6], atol=1e-4)                      # at 100, 104 (breakeven), 105, 110

    def test_what_the_curve_will_not_take(self):
        self.position("bull-call")
        self.assertEqual(len(self.curve("(option-profit-curve search :row 20)")["price"]) > 200, True)      # (the last of 21)
        for call, fragment in [("(option-profit-curve search :row 21)", "there is no row 21: the search found 21 positions"),
                               ("(option-profit-curve search :row 99)", "there is no row 99: the search found 21 positions"),
                               ("(option-profit-curve search :row -1)", "there is no row -1"),
                               ("(option-profit-curve search :points 1)", ":points is how many prices to chart, 2 or more"),
                               ("(option-profit-curve search :points 2.5)", ":points is how many prices to chart, 2 or more"),
                               ('(option-profit-curve search :low "a")', ":low is a price of the stock, a number"),
                               ('(option-profit-curve search :high "a")', ":high is a price of the stock, a number"),
                               ("(option-profit-curve search :low 120 :high 100)", ":low must be less than :high"),
                               ("(option-profit-curve search :low 100 :high 100)", ":low must be less than :high"),
                               ("(option-profit-curve search :size 3)", "unknown keyword")]:
            with self.subTest(call=call):
                self.assertLispError(call, fragment)

    # -- the chart of one position ---------------------------------------------------------------------------------

    def test_the_chart_of_one_position_by_hand(self):
        """The iron condor of the 100, 105, 110, and 115 pays 2.8 and can lose 2.2: it is worth most, 2.8, with the
        stock from 105 to 110, and breaks even at 102.2 and 112.8; at 108 it has made 2.8."""
        self.position("iron-condor")
        self.run_lisp("(plot-option-profit search)")
        spec = self.specs[-1]
        self.assertEqual(spec["title"], "Iron condor on XYZ, expiring 2026-11-20\n"
                                        "buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call")
        self.assertEqual((spec["x_label"], spec["y_label"]), ("price of XYZ on 2026-11-20", "profit, for a share"))
        self.assertEqual((spec["width"], spec["height"], spec["x_kind"]), (8.0, 5.5, "number"))
        self.assertEqual(self.labels(spec), ["gain", "loss", "profit at expiration", "breakeven", "XYZ at 108.00: profit 2.80"])
        gain, loss, line, breakevens, expected = spec["series"]
        # the same prices for the gain, the loss, and the line: above 0 the gain, below it the loss
        self.assertEqual(gain["x"], line["x"])
        self.assertEqual(loss["x"], line["x"])
        np.testing.assert_allclose(gain["y"], [max(y, 0) for y in line["y"]], atol=1e-6)
        np.testing.assert_allclose(loss["y"], [min(y, 0) for y in line["y"]], atol=1e-6)
        self.assertEqual((gain["fill"], gain["color"], loss["fill"], loss["color"]), (True, "green", True, "red"))
        self.assertEqual(gain["fill_to"], [0.0] * len(line["x"]))
        self.assertEqual((line["line"], line["color"], line["line_width"], line["fill"]), ("solid", "black", 2.0, False))
        np.testing.assert_allclose(line["y"], [profit_of("iron-condor", [100, 105, 110, 115], -2.8, x) for x in line["x"]], atol=1e-4)
        for price in (100, 105, 110, 115, 102.2, 112.8):                      # the line bends, and crosses 0, there
            self.assertTrue(any(abs(x - price) < 1e-4 for x in line["x"]), price)
        self.assertEqual((breakevens["symbol"], breakevens["line"], breakevens["color"]), ("circle", None, "black"))
        np.testing.assert_allclose(breakevens["x"], [102.2, 112.8], atol=1e-4)
        self.assertEqual(breakevens["y"], [0.0, 0.0])
        self.assertEqual((expected["symbol"], expected["line"], expected["color"]), ("diamond", None, "blue"))
        np.testing.assert_allclose(expected["x"], [108.0])
        np.testing.assert_allclose(expected["y"], [2.8], atol=1e-5)
        # the lines across the chart: the stock now and the price expected; 0, the most it can make, and the most it can lose
        self.assertEqual(spec["x_lines"], [{"at": 104.0, "label": "now", "color": "gray"},
                                           {"at": 108.0, "label": "expected", "color": "black"}])
        self.assertEqual([(l["label"], l["color"]) for l in spec["y_axis"]["lines"]],
                         [("", "gray"), ("most it can make 2.80", "green"), ("most it can lose 2.20", "red")])
        np.testing.assert_allclose([l["at"] for l in spec["y_axis"]["lines"]], [0, 2.8, -2.2], atol=1e-5)
        # room above the most it can make, for its label, and below the most it can lose: 16% and 8% of the 5.0 between
        np.testing.assert_allclose([spec["y_axis"]["min"], spec["y_axis"]["max"]], [-2.2 - 0.4, 2.8 + 0.8], atol=1e-5)
        self.assertEqual(spec["legend"], "upper left")                 # (the profit is low on the left)

    def test_a_loss_at_the_price_expected_is_a_loss(self):
        self.position("bull-call")
        self.run_lisp("(plot-option-profit search)")
        self.assertEqual(self.labels(self.specs[-1])[-1], "XYZ at 108.00: profit 3.00")
        # with the stock expected at 100, the 100 and 105 call spread is worth nothing, and cost 3.2
        table = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 100)")
        row = [i for i in range(len(table["ratio"])) if (table["strike-1"][i], table["strike-2"][i]) == (100, 105)][0]
        self.run_lisp("(plot-option-profit search :rows (list %d))" % row)
        self.assertEqual(self.labels(self.specs[-1])[-1], "XYZ at 100.00: loss 3.20")

    def test_the_chart_shows_the_most_it_can_make_and_lose_where_they_are_in_it(self):
        for kind, lines in [("bull-call", ["most it can make 5.00", "most it can lose 5.00"]),
                            ("long-call", ["most it can lose 6.20"]),                  # (no limit to what it can make)
                            ("long-put", ["most it can lose 15.40"]),                  # (it makes most with the stock at 0)
                            ("long-stock", []),                                        # (it can lose all 104, at 0)
                            ("covered-call", ["most it can make 7.20"]),
                            ("cash-secured-put", ["most it can make 6.80"]),
                            ("protective-put", ["most it can lose 5.60"]),
                            ("collar", ["most it can make 2.40", "most it can lose 2.60"])]:
            with self.subTest(kind=kind):
                self.position(kind)
                self.run_lisp("(plot-option-profit search)")
                shown = [l["label"] for l in self.specs[-1]["y_axis"]["lines"]]
                self.assertEqual(shown, [""] + lines)                                   # (0 first)

    def test_a_position_that_never_breaks_even_has_no_breakeven_marked(self):
        """The bull call spread of the 95 and 100, which costs 5.3 for a worth of 5 at most."""
        self.make_chain([{"strike": 95, "bid": 10.0, "ask": 10.2}, {"strike": 100, "bid": 4.9, "ask": 5.1}])
        self.run_lisp("(define search (option-spreads-for-chain chain 'bull-call (date 2026 11 20) 110))")
        self.run_lisp("(plot-option-profit search)")
        self.assertEqual(self.labels(self.specs[-1]), ["gain", "loss", "profit at expiration", "XYZ at 110.00: loss 0.30"])
        self.assertTrue(all(y <= 0 for y in self.specs[-1]["series"][2]["y"]))       # (a loss everywhere)
        self.assertTrue(all(y == 0 for y in self.specs[-1]["series"][0]["y"]))        # (and no gain)

    def test_a_range_that_leaves_out_the_marks_leaves_them_out_of_the_chart(self):
        self.position("iron-condor")                                    # it breaks even at 102.2 and 112.8, and expected is 108
        self.run_lisp("(plot-option-profit search :low 103 :high 112)")
        self.assertEqual(self.labels(self.specs[-1]), ["gain", "loss", "profit at expiration", "XYZ at 108.00: profit 2.80"])
        self.run_lisp("(plot-option-profit search :low 85 :high 107)")
        self.assertEqual(self.labels(self.specs[-1]), ["gain", "loss", "profit at expiration", "breakeven"])
        np.testing.assert_allclose(self.specs[-1]["series"][3]["x"], [102.2], atol=1e-4)

    def test_the_legend_goes_where_the_profit_is_not(self):
        for kind, corner in [("bull-call", "upper left"), ("bear-call", "lower left"), ("long-put", "lower left"),
                             ("long-call", "upper left"), ("covered-call", "upper left"), ("iron-condor", "upper left")]:
            with self.subTest(kind=kind):
                self.position(kind)
                self.run_lisp("(plot-option-profit search)")
                self.assertEqual(self.specs[-1]["legend"], corner)

    # -- several positions on one chart -----------------------------------------------------------------------------

    def test_several_positions_are_lines_on_one_chart(self):
        self.position("bull-call")
        self.run_lisp("(plot-option-profit search :rows (list 0 1 2))")
        spec = self.specs[-1]
        self.assertEqual(spec["title"], "Bull call spreads on XYZ, expiring 2026-11-20: the best 3 compared")
        self.assertEqual(self.labels(spec), ["buy 1 100.00 call, sell 1 110.00 call", "buy 1 100.00 call, sell 1 105.00 call",
                                             "buy 1 105.00 call, sell 1 110.00 call"])
        for series, strikes, cost in zip(spec["series"], [(100, 110), (100, 105), (105, 110)], [5.0, 3.2, 2.0]):
            self.assertEqual((series["line"], series["line_width"], series["fill"], series["symbol"]), ("solid", 2.0, False, None))
            self.assertEqual(series["x"], spec["series"][0]["x"])                     # the same prices for each
            np.testing.assert_allclose(series["y"], [profit_of("bull-call", strikes, cost, x) for x in series["x"]], atol=1e-4)
        self.assertEqual([l["label"] for l in spec["y_axis"]["lines"]], [""])         # only the line at 0
        self.assertEqual([l["label"] for l in spec["x_lines"]], ["now", "expected"])
        self.assertEqual(spec["legend"], "best")
        np.testing.assert_allclose([spec["y_axis"]["min"], spec["y_axis"]["max"]], [-5 - 0.08 * 10, 5 + 0.16 * 10], atol=1e-5)
        # the prices have the strikes of each, and the breakevens
        for price in (100, 105, 110, 103.2, 105.0, 107.0):
            self.assertTrue(any(abs(x - price) < 1e-4 for x in spec["series"][0]["x"]), price)

    def test_what_the_chart_will_not_take(self):
        self.position("bull-call")
        for call, fragment in [("(plot-option-profit search :rows (list 0 99))", "there is no row 99"),
                               ("(plot-option-profit search :rows '())", ":rows is a list of rows of the search"),
                               ("(plot-option-profit search :rows (list 0.5))", "there is no row 0.5"),
                               ("(plot-option-profit search :points 1)", ":points is how many prices to chart"),
                               ("(plot-option-profit search :low 130 :high 90)", ":low must be less than :high"),
                               ("(option-profit-panel search :row 99)", "option-profit-panel: there is no row 99")]:
            with self.subTest(call=call):
                self.assertLispError(call, fragment)
        self.assertEqual(len(self.specs), 0)                                 # (nothing was plotted)

    # -- a panel, for plot-panels ---------------------------------------------------------------------------------

    def test_panels_of_different_kinds_line_up(self):
        self.position("bull-call")
        self.run_lisp("(define first-search search)")
        self.position("iron-condor")
        self.run_lisp("(plot-panels (list (option-profit-panel first-search :low 85 :high 130) "
                      "                   (option-profit-panel search :low 85 :high 130)) :x-min 85 :x-max 130)")
        spec = self.specs[-1]
        self.assertEqual(spec["kind"], "panels")
        self.assertEqual([panel["title"] for panel in spec["panels"]],
                         ["bull-call: buy 1 100.00 call, sell 1 110.00 call",
                          "iron-condor: buy 1 100.00 put, sell 1 105.00 put, sell 1 110.00 call, buy 1 115.00 call"])
        for panel in spec["panels"]:
            self.assertEqual([s["label"] for s in panel["series"]][:3], ["gain", "loss", "profit at expiration"])
            self.assertIsNone(panel["legend"])                              # (a panel has none)
            line = panel["series"][2]
            self.assertEqual((line["x"][0], line["x"][-1]), (85.0, 130.0))
            self.assertEqual([l["label"] for l in panel["x_lines"]], ["now", "expected"])
            self.assertEqual((panel["x_min"], panel["x_max"]), (85.0, 130.0))

    def test_a_panel_is_the_series_and_options_of_the_chart(self):
        self.position("collar")
        panel = self.run_lisp("(option-profit-panel search)")
        items = lisp_core.pairs_to_list(panel)
        self.assertEqual(len(lisp_core.pairs_to_list(items[0])), 5)             # the series: gain, loss, profit, breakeven, expected
        options = [str(x) for x in items[1::2]]
        self.assertEqual(options, [":title", ":x-lines", ":y-lines", ":legend", ":y-min", ":y-max"])
        self.assertEqual(lisp_core.to_string(items[2]), '"collar: buy 100 shares, buy 1 100.00 put, sell 1 105.00 call"')
        self.assertIs(items[8], False)                                           # :legend #f

    # -- the chart of the best of several kinds --------------------------------------------------------------------

    def comparison(self, options=""):
        self.run_lisp("(define comparison (option-positions-for-chain chain %s %s))" % (self.EXPECTED, options))

    def test_the_best_few_of_the_kinds_with_no_shares_are_charted(self):
        self.comparison()
        self.run_lisp("(plot-option-positions comparison)")
        spec = self.specs[-1]
        self.assertEqual(spec["title"], "The best position of each kind on XYZ, expiring 2026-11-20")
        self.assertEqual(self.labels(spec), ["put-butterfly (profit 4.60)", "call-butterfly (profit 1.70)",
                                             "iron-condor (profit 2.80)", "iron-butterfly (profit 1.60)"])
        self.assertEqual([(s["line"], s["color"]) for s in spec["series"]], [("solid", None)] * 4)
        self.run_lisp("(plot-option-positions comparison :count 2)")
        self.assertEqual(self.labels(self.specs[-1]), ["put-butterfly (profit 4.60)", "call-butterfly (profit 1.70)"])
        # (the collar is fifth by the ratio, but has shares, so the fifth chart is the one after it: the bull put spread)
        self.run_lisp("(plot-option-positions comparison :count 5)")
        self.assertEqual(self.labels(self.specs[-1])[3:], ["iron-butterfly (profit 1.60)", "bull-put (profit 2.10)"])
        # each line is its position's profit, at the same prices
        self.run_lisp("(define search (position-comparison-search comparison 'iron-condor))")
        strikes, cost, _ = self.position("iron-condor")
        self.comparison()
        self.run_lisp("(plot-option-positions comparison)")
        condor = self.specs[-1]["series"][2]
        np.testing.assert_allclose(condor["y"], [profit_of("iron-condor", strikes, cost, x) for x in condor["x"]], atol=1e-4)
        for series in self.specs[-1]["series"]:
            self.assertEqual(series["x"], condor["x"])

    def test_the_kinds_with_shares_are_charted_together_with_the_stock_dashed(self):
        self.comparison()
        self.run_lisp("(plot-option-positions comparison :kinds '(long-stock covered-call protective-put collar))")
        spec = self.specs[-1]
        self.assertEqual(self.labels(spec), ["long-stock (profit 4.00)", "covered-call (profit 5.20)",
                                             "protective-put (profit 2.40)", "collar (profit 2.40)"])
        self.assertEqual([(s["line"], s["color"]) for s in spec["series"]],
                         [("dashed", "black"), ("solid", None), ("solid", None), ("solid", None)])
        stock = spec["series"][0]
        np.testing.assert_allclose(stock["y"], [x - 104 for x in stock["x"]], atol=1e-4)      # its profit is the stock's change
        # the order asked for is the order of the lines
        self.run_lisp("(plot-option-positions comparison :kinds '(collar long-stock))")
        self.assertEqual(self.labels(self.specs[-1]), ["collar (profit 2.40)", "long-stock (profit 4.00)"])

    def test_the_chart_of_the_kinds_says_what_it_will_not_take(self):
        self.comparison()
        self.assertLispError("(plot-option-positions comparison :kinds '(bull-calls))", "the comparison has no bull-calls; it has ")
        self.comparison(":kinds '(bull-call) :min-volume 6")
        self.assertLispError("(plot-option-positions comparison)", "the comparison has no positions to chart")
        self.comparison()
        for bad in ("0", "1.5", "-1"):
            self.assertLispError("(plot-option-positions comparison :count %s)" % bad, ":count is how many kinds to chart, 1 or more")
        self.assertLispError("(plot-option-positions comparison :points 1)", ":points is how many prices to chart")
        self.assertEqual(len(self.specs), 0)

    # -- the call spreads' chart -----------------------------------------------------------------------------------------

    def test_the_call_spreads_chart_is_the_bull_call_charts(self):
        self.run_lisp("(define classic (call-spreads-for-chain chain %s))" % self.EXPECTED)
        self.run_lisp("(define engine (option-spreads-for-chain chain 'bull-call %s))" % self.EXPECTED)
        for options in ("", " :rows (list 0 1 2)", " :low 90 :high 120 :points 30"):
            with self.subTest(options=options):
                self.run_lisp("(plot-call-spreads classic%s)" % options)
                self.run_lisp("(plot-option-profit engine%s)" % options)
                self.assertEqual(self.specs[-2], self.specs[-1])
        self.assertEqual(self.specs[-1]["x_lines"][1]["label"], "expected")

    def test_a_call_spread_that_costs_more_than_its_width_has_no_breakeven_in_the_chart(self):
        """The 95 and 100 costs 5.3, and is worth 5 at most: this file's breakeven, 100.3, is above the higher strike."""
        self.make_chain([{"strike": 95, "bid": 10.0, "ask": 10.2}, {"strike": 100, "bid": 4.9, "ask": 5.1}])
        self.run_lisp("(define classic (call-spreads-for-chain chain (date 2026 11 20) 110))")
        self.run_lisp("(plot-call-spreads classic)")
        self.assertEqual(self.labels(self.specs[-1]), ["gain", "loss", "profit at expiration", "XYZ at 110.00: loss 0.30"])

    # -- saving a chart -------------------------------------------------------------------------------------------------

    def test_the_charts_can_be_drawn_and_saved(self):
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.position("collar")
        self.comparison()
        self.run_lisp("(plot-option-profit search)")
        self.run_lisp("(plot-option-profit search :rows (list 0 1 2))")
        self.run_lisp("(plot-option-positions comparison)")
        self.run_lisp("(plot-panels (list (option-profit-panel search) (option-profit-panel search :row 1)))")
        self.assertEqual(len(self.specs), 4)
        with in_a_temporary_folder() as folder:
            for number, spec in enumerate(self.specs):
                path = os.path.join(folder, "chart%d.png" % number)
                lisp_charts.render_chart_to_file(spec, path)
                self.assertTrue(is_a_png(path), path)
            # and by the builtin that saves the last one
            self.run_lisp('(save-chart "last.png")')
            self.assertTrue(is_a_png(os.path.join(folder, "last.png")))

    def test_the_chart_is_drawn_with_its_lines_and_marks(self):
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.position("iron-condor")
        self.run_lisp("(plot-option-profit search)")
        fig = lisp_charts.Figure()
        lisp_charts.FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        lisp_charts.draw_chart_on_axes(fig, ax, self.specs[-1])
        legend = ax.get_legend()
        self.assertEqual([t.get_text() for t in legend.get_texts()],
                         ["gain", "loss", "profit at expiration", "breakeven", "XYZ at 108.00: profit 2.80"])
        self.assertEqual((ax.get_xlabel(), ax.get_ylabel()), ("price of XYZ on 2026-11-20", "profit, for a share"))
        low, high = ax.get_ylim()
        self.assertAlmostEqual(low, -2.6, places=4)
        self.assertAlmostEqual(high, 3.6, places=4)
        dashed = [line for line in ax.lines if line.get_linestyle() == "--"]      # (the reference lines)
        horizontal = sorted(round(float(line.get_ydata()[0]), 2) for line in dashed
                            if line.get_ydata()[0] == line.get_ydata()[1])
        self.assertEqual(horizontal, [-2.2, 0.0, 2.8])                           # at 0, and the most it can lose and make
        vertical = sorted(float(line.get_xdata()[0]) for line in dashed if line.get_xdata()[0] == line.get_xdata()[1])
        self.assertEqual(vertical, [104.0, 108.0])                               # now, and expected


class TestCallSpreadsAreTheBullCallKind(OptionSpreadsTestCase):
    """call_spreads.lsp is option_spreads.lsp's bull-call kind, under its own names: the same spreads, the same numbers."""

    def test_the_same_spreads_and_numbers(self):
        self.run_lisp('(load "call_spreads.lsp")')
        rows = TestAgainstAPlainCalculation.random_rows(self, 5)
        self.make_chain(rows)
        classic = self.spreads("(call-spreads-for-chain chain (date 2026 11 20) 104)")
        general = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 104)")
        self.assertGreater(len(classic["ratio"]), 20)
        for old, new in [("long-symbol", "symbol-1"), ("short-symbol", "symbol-2"), ("long-strike", "strike-1"),
                         ("short-strike", "strike-2"), ("long-price", "price-1"), ("short-price", "price-2"),
                         ("cost", "cost"), ("worth", "worth"), ("profit", "profit"), ("ratio", "ratio"), ("max-profit", "max-profit")]:
            self.assertEqual([str(x) for x in classic[old]], [str(x) for x in general[new]], old)
        np.testing.assert_allclose(classic["cost"], general["max-loss"], rtol=1e-6)
        self.assertShows("(spread-search-kind (call-spreads-for-chain chain (date 2026 11 20) 104))", "bull-call")
