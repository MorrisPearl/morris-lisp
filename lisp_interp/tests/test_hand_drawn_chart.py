"""hand-drawn-chart: the SVG string of a hand-drawn chart of series, each as bars or a symbol."""

from support import *  # noqa: F401,F403
import xml.dom.minidom


class TestHandDrawnChart(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "hand_drawn_chart.lsp")')

    def chart(self, args):
        text = self.run_lisp('(hand-drawn-chart %s)' % args)
        return xml.dom.minidom.parseString(str(text))      # fails if the SVG isn't well-formed

    def texts(self, doc):
        return [t.firstChild.data for t in doc.getElementsByTagName("text")]

    def test_bars_and_symbols_are_independent_of_each_other(self):
        doc = self.chart('\'("a" "b" "c") \'(("x" (1 2 3) "bar") ("y" (3 2 1) "bar") ("s" (1 2 3) "star") ("t" (3 2 1)))')
        # 2 bar series x 3 labels, and 2 more bars in the key
        self.assertEqual(len(doc.getElementsByTagName("polygon")), 2 * 3 + 2)
        texts = self.texts(doc)
        self.assertEqual(texts[:2], ["1", "3"])                       # lowest and highest at the axis
        self.assertTrue({"a", "b", "c", "x", "y", "s", "t"} <= set(texts))
        self.assertIn("Architects Daughter", doc.getElementsByTagName("text")[0].getAttribute("font-family"))

    def test_a_series_with_no_shape_gets_the_next_default_shape(self):
        shapes = lambda src: len(self.chart(src).getElementsByTagName("line"))
        one = '\'("a") \'(("p" (1)))'                                     # a square: 4 strokes + 2 axes, + 4 in the key
        self.assertEqual(shapes(one), 2 + 4 + 4)
        two = '\'("a") \'(("b" (1) "bar") ("p" (1)))'                   # the bar doesn't use up the square
        self.assertEqual(shapes(two), 2 + 4 + 4)
        three = '\'("a") \'(("p" (1)) ("q" (1)))'                       # a square, then a star (5 strokes)
        self.assertEqual(shapes(three), 2 + (4 + 4) + (5 + 5))

    def test_a_seed_draws_the_same_picture_and_no_wobble_draws_straight_lines(self):
        a = self.run_lisp('(hand-drawn-chart \'("a") \'(("p" (1))) :seed 5)')
        b = self.run_lisp('(hand-drawn-chart \'("a") \'(("p" (1))) :seed 5)')
        self.assertEqual(str(a), str(b))
        doc = self.chart('\'("a" "b") \'(("p" #(1 2) "bar")) :wobble 0')
        axis = doc.getElementsByTagName("line")[0]
        self.assertEqual(axis.getAttribute("y1"), axis.getAttribute("y2"))

    def test_labels_are_escaped_and_mistakes_are_errors(self):
        self.assertIn("a & b", self.texts(self.chart('\'("a & b") \'(("p" (1)))')))
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp('(hand-drawn-chart \'("a" "b") \'(("p" (1))))')
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp('(hand-drawn-chart \'("a") \'(("p" (1) "blob")))')

    def test_end_labels_only_leaves_out_the_labels_between(self):
        src = '\'("a" "b" "c" "d") \'(("p" (1 2 3 4)))'
        self.assertEqual(self.texts(self.chart(src))[2:6], ["a", "b", "c", "d"])
        texts = self.texts(self.chart(src + " :end-labels-only #t"))
        self.assertIn("a", texts)
        self.assertIn("d", texts)
        self.assertNotIn("b", texts)
        self.assertNotIn("c", texts)
