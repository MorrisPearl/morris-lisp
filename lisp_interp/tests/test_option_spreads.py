"""lib/option_spreads.lsp: of the options expiring on one day, the best spread of a kind -- a vertical spread, a
butterfly, an iron condor or iron butterfly, a straddle or strangle -- by the profit at the price expected on the day
as a share of the most that can be lost; and the order for it."""

import datetime
import itertools

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


NAN = float("nan")
KINDS = ["bull-call", "bear-call", "bull-put", "bear-put", "call-butterfly", "put-butterfly", "iron-condor",
         "iron-butterfly", "long-straddle", "long-strangle"]

# What each kind is, for the plain calculation below: its legs from the lowest strike up, as (C or P, how many
# bought -- a minus sign for sold), and how its strikes are related.
LEGS = {"bull-call": [("C", 1), ("C", -1)], "bear-call": [("C", -1), ("C", 1)],
        "bull-put": [("P", 1), ("P", -1)], "bear-put": [("P", -1), ("P", 1)],
        "call-butterfly": [("C", 1), ("C", -2), ("C", 1)], "put-butterfly": [("P", 1), ("P", -2), ("P", 1)],
        "iron-condor": [("P", 1), ("P", -1), ("C", -1), ("C", 1)],
        "iron-butterfly": [("P", 1), ("P", -1), ("C", -1), ("C", 1)],
        "long-straddle": [("C", 1), ("P", 1)], "long-strangle": [("P", 1), ("C", 1)]}


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
                ("long-straddle", (100, 100), ["C100", "P100"]), ("long-strangle", (95, 105), ["P95", "C105"])]:
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
        for kind in KINDS[:8]:
            table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
            self.assertTrue(all(x == x for x in table["max-profit"]), kind)
            self.assertTrue(all(x > 0 for x in table["max-loss"]), kind)

    def test_the_credit_spreads_are_paid_and_the_debit_spreads_pay(self):
        for kind, credit in [("bull-call", False), ("bear-call", True), ("bull-put", True), ("bear-put", False),
                             ("iron-condor", True), ("iron-butterfly", True), ("long-straddle", False), ("long-strangle", False)]:
            with self.subTest(kind=kind):
                table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
                self.assertEqual(all(c < 0 for c in table["cost"]), credit)
                if credit:                                 # the most it can make is the credit it is paid
                    np.testing.assert_allclose(table["max-profit"], [-c for c in table["cost"]], rtol=1e-4)
                else:                                      # the most it can lose is the debit it costs
                    np.testing.assert_allclose(table["max-loss"], table["cost"], rtol=1e-4)

    def test_which_options_a_kind_uses(self):
        """Puts for the put spreads, calls for the call spreads, both for the kinds that use both."""
        for kind, types in [("bull-call", {"C"}), ("bear-put", {"P"}), ("iron-condor", {"C", "P"}), ("long-straddle", {"C", "P"})]:
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
        for kind in ("bull-call", "iron-condor", "long-strangle"):
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
        for kind in ("bull-call", "bull-put", "iron-condor", "long-straddle"):
            self.assertNotIn(102.5, self.strike_set(kind, rows), kind)
        self.make_chain(rows)
        table = self.spreads("(option-spreads-for-chain chain 'bull-call \"2026-12-18\" 108)")      # (the day may be text)
        self.assertEqual(len(table["ratio"]), 0)                  # only one December call: no spread

    def test_a_kind_that_needs_a_type_of_option_the_day_does_not_have_is_an_error(self):
        self.make_chain([r for r in self.BASE if r["type" if "type" in r else "bid"] != "Put"])      # no puts at all
        self.assertEqual(len(self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108)")["ratio"]), 3)
        for kind in ("bull-put", "bear-put", "put-butterfly", "iron-condor", "long-straddle", "long-strangle"):
            with self.subTest(kind=kind):
                self.assertLispError("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind,
                                     "the chain has no puts expiring on 2026-11-20; its puts expire on no day at all")
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
        for kind, per_root in [("bull-call", 3), ("call-butterfly", 1), ("iron-condor", 0), ("long-straddle", 3), ("long-strangle", 3)]:
            with self.subTest(kind=kind):
                table = self.spreads("(option-spreads-for-chain chain '%s (date 2026 11 20) 108)" % kind)
                self.assertEqual(len(table["ratio"]), 2 * per_root)
                for i in range(len(table["ratio"])):
                    roots = {str(table[column][i])[:6].strip() for column in table if column.startswith("symbol-")}
                    self.assertEqual(len(roots), 1, [table[c][i] for c in table if c.startswith("symbol-")])

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
        # a strangle's width is the distance between its strikes
        strangle = self.spreads("(option-spreads-for-chain chain 'long-strangle (date 2026 11 20) 108 :max-width 5)")
        self.assertEqual(sorted(zip(strangle["strike-1"], strangle["strike-2"])), [(100, 105), (105, 110)])

    def test_min_risk_leaves_out_the_spreads_that_cannot_lose_much(self):
        self.make_chain(self.BASE)
        table = self.spreads("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :min-risk 2.5)")
        np.testing.assert_allclose(sorted(table["max-loss"]), [3.2, 5.0], rtol=1e-5)
        table = self.spreads("(option-spreads-for-chain chain 'bull-put (date 2026 11 20) 108 :min-risk 3)")
        self.assertTrue(all(x >= 3 for x in table["max-loss"]))

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
        for kind, options in [("bull-call", 2), ("call-butterfly", 3), ("iron-condor", 4), ("long-straddle", 2)]:
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

    def test_what_it_will_not_take(self):
        self.make_chain(self.BASE)
        self.assertLispError("(option-spreads-for-chain chain 'bull-calls (date 2026 11 20) 108)",
                             "bull-calls isn't a kind of spread; the kinds are bull-call, bear-call, bull-put, bear-put, "
                             "call-butterfly, put-butterfly, iron-condor, iron-butterfly, long-straddle, long-strangle")
        self.assertLispError("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :prices 'last)",
                             ":prices is 'bid-ask or 'mid")
        self.assertLispError("(option-spreads-for-chain chain 'bull-call (date 2026 11 20) 108 :size 2)", "unknown keyword")

    def test_the_kinds_are_listed(self):
        table = {str(n): list(v.items) for n, v in lisp_tables.table_columns(self.run_lisp("(option-spread-kinds)"), "test")}
        self.assertEqual([str(k) for k in table["kind"]], KINDS)
        self.assertEqual(str(table["legs"][0]), "buy call, sell call")
        self.assertEqual(str(table["legs"][4]), "buy call, sell 2 call, buy call")
        self.assertEqual(str(table["legs"][6]), "buy put, sell put, sell call, buy call")
        self.assertEqual([str(s) for s in table["schwab"]],
                         ["VERTICAL"] * 4 + ["BUTTERFLY"] * 2 + ["IRON_CONDOR"] * 2 + ["STRADDLE", "STRANGLE"])
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

    def reference(self, rows, kind, expected, prices="bid-ask", min_oi=1, min_volume=1, min_risk=0.0, max_width=None):
        """{(symbols of the spread): (strikes, prices, cost, max-loss, max-profit, worth, profit, ratio, breakeven-1,
        breakeven-2)}, as the definition gives them."""
        f32 = lambda x: float(np.float32(x))
        zero = lambda x: 0 if x != x else x
        counts = lambda r: zero(r["open_interest"]) >= min_oi and zero(r["volume"]) >= min_volume
        usable = [r for r in rows if r["bid"] > 0 and r["ask"] == r["ask"] and r["ask"] > 0 and counts(r)]
        found = {}
        for root in sorted({r["symbol"][:6] for r in usable}):
            options = {t: sorted((r for r in usable if r["symbol"][:6] == root and r["type"][0] == t), key=lambda r: r["strike"])
                       for t in "CP"}
            for combo in self.combos(kind, options, max_width):
                legs = LEGS[kind]
                price = lambda r, q: r["mid"] if prices == "mid" else (r["ask"] if q > 0 else r["bid"])
                cost = f32(sum(q * f32(price(r, q)) for (t, q), r in zip(legs, combo)))     # (the library's numbers are 32-bit)
                intrinsic = lambda S: sum(q * (np.maximum(S - r["strike"], 0) if t == "C" else np.maximum(r["strike"] - S, 0))
                                          for (t, q), r in zip(legs, combo))
                profit_on_grid = intrinsic(self.GRID) - cost
                max_loss = -profit_on_grid.min()
                if not (max_loss > 0.001 and max_loss >= min_risk):
                    continue
                unlimited = kind in ("long-straddle", "long-strangle")
                max_profit = NAN if unlimited else profit_on_grid.max()
                roots = []
                for a, b, pa, pb in zip(self.GRID[:-1], self.GRID[1:], profit_on_grid[:-1], profit_on_grid[1:]):
                    if (pa < 0 <= pb) or (pa > 0 >= pb):
                        roots.append(a + (b - a) * (-pa) / (pb - pa))
                first, last = (min(roots), max(roots)) if roots else (NAN, NAN)
                worth = float(intrinsic(expected))
                found[tuple(r["symbol"] for r in combo)] = (
                    [r["strike"] for r in combo], [f32(price(r, q)) for (t, q), r in zip(legs, combo)], cost, max_loss, max_profit,
                    worth, worth - cost, (worth - cost) / max_loss, first, NAN if last == first else last)
        return found

    def combos(self, kind, options, max_width):
        calls, puts = options["C"], options["P"]
        within = lambda width: max_width is None or width <= max_width
        shape = {"bull-call": "vertical", "bear-call": "vertical", "bull-put": "vertical", "bear-put": "vertical",
                 "call-butterfly": "butterfly", "put-butterfly": "butterfly", "iron-condor": "condor",
                 "iron-butterfly": "condor", "long-straddle": "straddle", "long-strangle": "strangle"}[kind]
        own = calls if LEGS[kind][0][0] == "C" else puts
        if shape == "vertical":
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
        legs = len(LEGS[kind])
        self.assertEqual(len(table["ratio"]), len(mine), "%s %s: number of spreads" % (kind, options))
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
                  (":max-width 12.5", {"max_width": 12.5})]

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
            self.assertGreater(total[kind], 100, kind)                       # (the comparison was of something)

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

    def order(self, kind, call="(option-spread-order search)", expected=108):
        """The order as Python (the JSON Schwab takes), for the best spread of the kind, and the search that found it."""
        import lisp_schwab
        self.run_lisp("(define search (option-spreads-for-chain chain '%s (date 2026 11 20) %s))" % (kind, expected))
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
        self.make_chain(rows)
        self.asked = []
        self.env[lisp_core.Symbol("schwab-option-chain")] = lambda creds, symbol, *options: (
            self.asked.append((str(creds), str(symbol), [lisp_core.to_string(o) for o in options])) or self.env[lisp_core.Symbol("chain")])
        self.env[lisp_core.Symbol("creds")] = lisp_core.LispString("credentials.json")

    def test_it_asks_schwab_for_the_calls_the_puts_or_both_as_the_kind_needs(self):
        for kind, contracts in [("bull-call", '"CALL"'), ("call-butterfly", '"CALL"'), ("bull-put", '"PUT"'), ("bear-put", '"PUT"'),
                                ("put-butterfly", '"PUT"'), ("iron-condor", '"ALL"'), ("iron-butterfly", '"ALL"'),
                                ("long-straddle", '"ALL"'), ("long-strangle", '"ALL"')]:
            with self.subTest(kind=kind):
                del self.asked[:]
                table = self.spreads('(option-spreads creds "XYZ" \'%s "2026-11-20" 108 :prices \'mid :min-risk 0.5)' % kind)
                self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", contracts])])
                self.assertGreater(len(table["ratio"]), 0)
                self.assertShows("(spread-search-prices search)", "mid")                  # its options were passed on
                self.assertShows("(spread-search-kind search)", kind)

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

    def test_showing_a_search_that_found_nothing_says_why(self):
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108 :min-volume 6))")
        self.assertIn("No such spread can be made", self.printed())
        self.assertIn("give :min-volume 0", self.printed())
        self.assertIn("prices. 0 spreads.", self.printed())

    def test_one_spread_is_not_spreads(self):
        self.run_lisp("(show-option-spreads (option-spreads-for-chain chain 'iron-condor (date 2026 11 20) 108 :max-width 5 "
                      ":min-risk 4.6))")
        self.assertIn("prices. 1 spread.", self.printed())

    def test_the_example_takes_the_stock_the_kind_the_day_and_the_price_from_the_command_line(self):
        try:
            lisp_builtins.set_command_line_arguments(["XYZ", "iron-condor", "2026-11-20", "108"])
            lisp_core.run_file(os.path.join(EXAMPLES, "option_spreads_example.lsp"), self.env)
            self.assertEqual(self.asked, [("credentials.json", "XYZ", [":expiration", "2026-11-20", ":type", '"ALL"'])])
            self.assertIn("Iron condors expiring 2026-11-20", self.printed())
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
