"""hand-drawn-chart: the SVG string of a hand-drawn bar chart with symbols."""

from support import *  # noqa: F401,F403
import xml.dom.minidom


class TestHandDrawnChart(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "hand_drawn_chart.lsp")')

    def chart(self, args):
        text = self.run_lisp('(hand-drawn-chart %s)' % args)
        return xml.dom.minidom.parseString(str(text))      # fails if the SVG isn't well-formed

    def test_bars_labels_and_symbols(self):
        doc = self.chart('\'("a" "b" "c") \'(1 2 3) :extras \'(("s" "star" (1 2 3)) ("t" "triangle" (3 2 1)))')
        self.assertEqual(len(doc.getElementsByTagName("polygon")), 3)           # a bar for each value
        texts = [t.firstChild.data for t in doc.getElementsByTagName("text")]
        self.assertEqual(texts[:2], ["1", "3"])                                 # lowest and highest at the axis
        self.assertTrue({"a", "b", "c", "s", "t"} <= set(texts))
        self.assertIn("Architects Daughter", doc.getElementsByTagName("text")[0].getAttribute("font-family"))

    def test_a_seed_draws_the_same_picture_and_no_wobble_draws_straight_lines(self):
        a = self.run_lisp('(hand-drawn-chart \'("a") \'(1) :seed 5)')
        b = self.run_lisp('(hand-drawn-chart \'("a") \'(1) :seed 5)')
        self.assertEqual(str(a), str(b))
        doc = self.chart('\'("a" "b") \'(1 2) :wobble 0')
        axis = doc.getElementsByTagName("line")[0]
        self.assertEqual(axis.getAttribute("y1"), axis.getAttribute("y2"))

    def test_labels_are_escaped_and_mistakes_are_errors(self):
        doc = self.chart('\'("a & b") \'(1)')
        self.assertIn("a & b", [t.firstChild.data for t in doc.getElementsByTagName("text")])
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp('(hand-drawn-chart \'("a" "b") \'(1))')
        with self.assertRaises(lisp_core.LispError):
            self.run_lisp('(hand-drawn-chart \'("a") \'(1) :extras \'(("s" "blob" (1))))')
