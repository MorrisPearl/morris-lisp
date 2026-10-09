"""Charts and maps: plot-chart, plot-histogram, plot-panels, and plot-map.
support.py says how to run them."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


class TestPlotChart(LispTestCase):
    """plot-chart: several (X, Y) series on one X axis, each with symbols,
    a line, or bars."""

    def setUp(self):
        super().setUp()
        self.specs = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)

    def drawn(self, src):
        """The axes plot-chart's chart is drawn on (with matplotlib, off screen)."""
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.run_lisp(src)
        self.fig = lisp_charts.Figure()
        lisp_charts.FigureCanvasAgg(self.fig)
        ax = self.fig.add_subplot(111)
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        return ax

    def legend_texts(self):
        legends = [a.get_legend() for a in self.fig.axes if a.get_legend()]
        self.assertEqual(len(legends), 1)
        return [t.get_text() for t in legends[0].get_texts()]

    def test_a_fitted_line_follows_its_series(self):
        self.run_lisp('(plot-chart (list (list "y" #(1 2 3 4) #(3 5 7 9) :symbol #t :fit "linear")))')
        data, fit = self.specs[-1]["series"]
        self.assertEqual(fit["label"], "y, linear fit")
        self.assertEqual((fit["x"], fit["line"], fit["symbol"]), ([1.0, 4.0], "dashed", None))
        np.testing.assert_allclose(fit["y"], [3.0, 9.0])          # y = 2x + 1
        self.assertIsNone(data["line"])                           # (the series itself is only symbols)

    def test_a_least_absolute_deviation_fit_isnt_pulled_by_an_outlier(self):
        self.run_lisp('(plot-chart (list (list "y" #(1 2 3 4 5) #(3 5 7 9 100) :symbol #t :fit "lad")))')
        fit = self.specs[-1]["series"][1]
        self.assertEqual(fit["label"], "y, lad fit")
        np.testing.assert_allclose(fit["y"], [3.0, 11.0], atol=1e-6)   # y = 2x + 1, despite the 100

    def test_a_logistic_fit_is_an_s_shaped_curve(self):
        self.run_lisp('(plot-chart (list (list "p" #(1 2 3 4 5 6) #(0 0 1 0 1 1) :symbol #t :fit "logistic")))')
        fit = self.specs[-1]["series"][1]
        self.assertEqual(len(fit["x"]), 100)
        self.assertTrue(all(0 < y < 1 for y in fit["y"]))
        self.assertEqual(fit["y"], sorted(fit["y"]))                # rising, for these

    def test_a_fit_against_dates_and_what_fit_wont_take(self):
        self.run_lisp('(plot-chart (list (list "d" (vector (date 2024 1 1) (date 2024 7 1)) #(1 2) :fit "linear")))')
        self.assertEqual(self.specs[-1]["series"][1]["x"], [datetime.date(2024, 1, 1), datetime.date(2024, 7, 1)])
        self.assertLispError('(plot-chart (list (list "y" #(1 2 3) #(1 2 3) :fit "cubic")))', ':fit is "linear", "lad", or "logistic"')
        self.assertLispError('(plot-chart (list (list "y" (vector "a" "b" "c") #(1 2 3) :fit "linear")))',
                             "for X values that are numbers or dates")

    def test_series_and_how_each_is_drawn(self):
        self.run_lisp('(plot-chart (list (list "a" (vector (date 2024 1 1) (date 2024 2 1) (date 2024 3 1))'
                      '                        (vector 1 nan 3))'
                      '                  (list "b" (list (date 2024 1 1)) (list 5) :bars #t :symbol #t'
                      '                        :line "dashed" :color "red" :line-width 3))'
                      '            :title "T" :symbol-size 9)')
        spec = self.specs[-1]
        self.assertEqual((spec["kind"], spec["title"], spec["x_kind"]), ("plot-chart", "T", "date"))
        a, b = spec["series"]
        self.assertEqual(a["x"], [datetime.date(2024, 1, 1), datetime.date(2024, 3, 1)])   # the NaN is left out
        self.assertEqual(a["y"], [1.0, 3.0])
        self.assertEqual((a["line"], a["symbol"], a["bars"]), ("solid", None, False))      # a line, unless told
        self.assertEqual((a["line_width"], a["symbol_size"]), (1.5, 9.0))
        self.assertEqual((b["line"], b["symbol"], b["bars"], b["color"]), ("dashed", "square", True, "red"))
        self.assertEqual(b["line_width"], 3.0)          # #t: the second series gets the second symbol
        self.assertEqual(spec["legend"], "best")

    def test_text_is_categories_in_the_order_they_first_appear(self):
        self.run_lisp('(plot-chart (list (list "a" #("NY" "TX") #(1 2) :bars #t)'
                      '                  (list "b" #("CA" "TX") #(3 4) :symbol "star")) :legend #f)')
        self.assertEqual(self.specs[-1]["categories"], ["NY", "TX", "CA"])
        self.assertIsNone(self.specs[-1]["legend"])

    def test_mistakes(self):
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2)) (list "b" #("x") #(1))))',
                             "the X values must be all dates, all numbers, or all text")
        self.assertLispError('(plot-chart (list (list "a" (list 1 "x") #(1 2))))',
                             "series a's X values are a mix of text and number")
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2 3))))', "has 2 X values but 3 Y values")
        self.assertLispError('(plot-chart (list (list "a" #(1 1) #(1 2) :bars #t)))',
                             "can have only one Y value for each X")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :symbol "hexagon")))', "there's no symbol")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :line "wavy")))', "there's no line style")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :size 3)))', ":size isn't an option")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :bars "piled")', ':bars must be "grouped"')
        self.assertLispError('(plot-chart (list (list "a" #(1))))', "each series is a list (name x y [options])")
        self.assertLispError("(plot-chart '())", "there are no series to plot")

    def test_grouped_bars_sit_side_by_side(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q") #(1 2) :bars #t)'
                        '                  (list "b" #("p" "q") #(3 4) :bars #t)))')
        bars = [(round(p.get_x(), 6), round(p.get_width(), 6), p.get_height()) for p in ax.patches]
        # 0.8 of the room between categories, shared by the two series
        self.assertEqual(bars, [(-0.4, 0.4, 1), (0.6, 0.4, 2), (0.0, 0.4, 3), (1.0, 0.4, 4)])

    def test_stacked_bars_build_up_from_zero_and_down_from_it(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(1 -2) :bars #t)'
                        '                  (list "b" #(1 2) #(3 -1) :bars #t)'
                        '                  (list "c" #(1 2) #(-5 4) :bars #t)) :bars "stacked")')
        bottoms = [(p.get_x() + p.get_width() / 2, p.get_y(), p.get_height()) for p in ax.patches]
        self.assertEqual([(round(x, 6), y, h) for x, y, h in bottoms],
                         [(1, 0, 1), (2, 0, -2),          # a
                          (1, 1, 3), (2, -2, -1),         # b, on top of a (below it, if negative)
                          (1, 0, -5), (2, 0, 4)])         # c: the first below 0 at 1, the first above at 2

    def test_monthly_and_quarterly_dates_share_the_axis(self):
        ax = self.drawn('(plot-chart (list (list "m" (vector (date 2024 1 1) (date 2024 2 1) (date 2024 3 1)'
                        '                                    (date 2024 4 1)) #(1 2 3 4) :symbol "dot")'
                        '                  (list "q" (vector (date 2024 1 1) (date 2024 4 1)) #(5 6) :bars #t)))')
        january, april = [p.get_x() + p.get_width() / 2 for p in ax.patches]
        self.assertAlmostEqual(april - january, 91)                  # days: on a calendar
        self.assertAlmostEqual(ax.patches[0].get_width(), 0.8 * 91)  # the quarterly bars' room, not the months'
        line = ax.get_lines()[0]
        self.assertEqual(list(line.get_xdata())[3], april)

    def test_a_secondary_axis_has_its_own_scale(self):
        ax = self.drawn('(plot-chart (list (list "big" #(1 2 3) #(1000 2000 3000) :bars #t)'
                        '                  (list "small" #(1 2 3) #(0.1 0.2 0.3) :secondary #t))'
                        '            :y-label "dollars" :secondary-label "percent")')
        self.assertEqual(len(self.fig.axes), 2)
        right = self.fig.axes[1]
        for found, expected in zip(right.get_lines()[0].get_ydata(), [0.1, 0.2, 0.3]):
            self.assertAlmostEqual(found, expected, places=6)      # (vectors hold 32-bit numbers)
        self.assertEqual(len(ax.get_lines()), 1)                  # just the line at 0 for the bars
        self.assertEqual((ax.get_ylabel(), right.get_ylabel()), ("dollars", "percent"))
        self.assertEqual(self.legend_texts(), ["big", "small (right)"])       # one legend, in order

    def test_bars_on_both_axes(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(10 20) :bars #t)'
                        '                  (list "b" #(1 2) #(1 2) :bars #t :secondary #t)'
                        '                  (list "c" #(1 2) #(5 5) :line #t)))')
        right = self.fig.axes[1]
        # grouped: side by side, though on two scales
        self.assertEqual([round(p.get_x(), 6) for p in ax.patches], [0.6, 1.6])
        self.assertEqual([round(p.get_x(), 6) for p in right.patches], [1.0, 2.0])
        self.assertGreater(ax.get_zorder(), right.get_zorder())   # so the secondary bars don't hide c's line
        ax = self.drawn('(plot-chart (list (list "a" #(1) #(10) :bars #t) (list "b" #(1) #(1) :bars #t :secondary #t)'
                        '                  (list "c" #(1) #(5) :bars #t)) :bars "stacked")')
        self.assertEqual([p.get_y() for p in ax.patches], [0, 10])               # a, then c on top of it
        self.assertEqual([p.get_y() for p in self.fig.axes[1].patches], [0])     # b: its own stack

    def test_horizontal_charts(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q" "r") #(1 2 3) :bars #t)'
                        '                  (list "b" #("p" "q") #(30 40) :symbol #t :secondary #t))'
                        '            :horizontal #t :x-label "place" :y-label "amount")')
        bars = [(p.get_y() + p.get_height() / 2, round(p.get_height(), 6), p.get_width()) for p in ax.patches]
        self.assertEqual(bars, [(0, 0.8, 1), (1, 0.8, 2), (2, 0.8, 3)])     # going across
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["p", "q", "r"])
        self.assertTrue(ax.yaxis_inverted())                                 # p at the top
        self.assertEqual((ax.get_ylabel(), ax.get_xlabel()), ("place", "amount"))
        top = self.fig.axes[1]
        self.assertEqual(list(top.get_lines()[0].get_xdata()), [30, 40])     # the Y values across the top
        self.assertEqual(self.legend_texts(), ["a", "b (top)"])

    def test_limits_ticks_and_log_scales(self):
        ax = self.drawn('(plot-chart (list (list "a" #(1 2 3) #(1000 2000 3000) :bars #t)'
                        '                  (list "b" #(1 2 3) #(2 40 900) :secondary #t))'
                        '            :y-min 0 :y-max 4000 :y-ticks (list 0 1500 3000) :secondary-log #t)')
        self.assertEqual(ax.get_ylim(), (0, 4000))
        self.assertEqual(list(ax.get_yticks()), [0, 1500, 3000])
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["0", "1,500", "3,000"])
        right = self.fig.axes[1]
        self.assertEqual(right.get_yscale(), "log")
        low, high = right.get_ylim()
        self.assertEqual(list(right.get_yticks()), lisp_plot_chart.log_ticks(low, high, 8))
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(5 7) :bars #t)) :y-log #t :horizontal #t :y-max 100)')
        self.assertEqual((ax.get_xscale(), ax.get_xlim()[1]), ("log", 100))    # across, when horizontal
        self.assertEqual(ax.get_lines(), [])                                    # no line at 0 on a log scale
        ax = self.drawn('(plot-chart (list (list "a" #(1 2 3) #(0 50 100))) :y-ticks 3)')
        low, high = ax.get_ylim()
        self.assertEqual([t for t in ax.get_yticks() if low <= t <= high], [0, 50, 100])   # about 3, round

    def test_axis_mistakes(self):
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 -2))) :y-log #t)',
                             "series a has values of 0 or less, which a log scale can't show")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1) :secondary #t)) :secondary-log #t :secondary-min 0)',
                             "a log scale's :secondary-min must be more than 0")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-min 5 :y-max 1)', ":y-min must be less than :y-max")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-ticks 1)', ":y-ticks is about how many ticks")
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(1 -2))) :secondary-log #t)')   # nothing's on that axis

    def test_round_numbers_for_ticks(self):
        self.assertEqual([lisp_plot_chart.tick_text(v) for v in (1500, 0.25, -5.5e-17, 0.30000000000000004, -1250.5)],
                         ["1,500", "0.25", "0", "0.3", "-1,250.5"])
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            self.skipTest("matplotlib isn't installed")
        self.assertEqual(lisp_plot_chart.log_ticks(23, 340, 8), [30, 50, 100, 200, 300])        # 1, 2, 3, 5
        self.assertEqual(lisp_plot_chart.log_ticks(0.5, 2000, 8), [1, 3, 10, 30, 100, 300, 1000])
        self.assertEqual(lisp_plot_chart.log_ticks(1, 1e12, 5), [1, 1e3, 1e6, 1e9, 1e12])     # every third power
        self.assertEqual(lisp_plot_chart.log_ticks(130, 335, 8), [150, 200, 250, 300])         # within a decade

    def test_reference_lines_shading_and_notes(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q" "r") #(1 5 3) :bars #t))'
                        '            :y-lines (list 2 (list 4 "target" "red")) :x-lines (list "q")'
                        '            :shade (list (list "q" "r" "late")) :notes (list (list "q" 5 "the most")))')
        lines = [(list(line.get_xdata()), list(line.get_ydata())) for line in ax.get_lines()]
        self.assertIn(([0, 1], [2, 2]), lines)                     # across, at Y = 2 (x in axes fractions)
        self.assertIn(([0, 1], [4, 4]), lines)
        self.assertIn(([1, 1], [0, 1]), lines)                     # up and down, at "q"
        texts = [t.get_text() for t in ax.texts]
        self.assertEqual(texts, ["late", "target", "the most"])
        span = [p for p in ax.patches if p.get_x() == 0.5]           # "q" and "r", whole: 0.5 to 2.5
        self.assertEqual(span[0].get_width(), 2)

    def test_formats_and_x_limits(self):
        ax = self.drawn('(plot-chart (list (list "a" #(0 1000 2000) #(0.05 0.1 0.15)))'
                        '            :y-format "{:.0%}" :y-ticks (list 0.05 0.1) :x-format "${:,.0f}" :x-max 3000)')
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["5%", "10%"])
        self.assertEqual(ax.xaxis.get_major_formatter()(1500, 0), "$1,500")
        self.assertEqual(ax.get_xlim()[1], 3000)
        ax = self.drawn('(plot-chart (list (list "a" (vector (date 2024 1 1) (date 2024 6 1)) #(1 2)))'
                        '            :x-min (date 2023 1 1) :y-format ",d")')
        self.assertEqual(ax.get_xlim()[0], lisp_plot_chart.x_positions(self.specs[-1], [datetime.date(2023, 1, 1)])[0])
        self.assertEqual(ax.yaxis.get_major_formatter()(1234.6, 0), "1,235")       # a whole number, rounded
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :y-format "{:q}")', "isn't a format for numbers")
        self.assertLispError('(plot-chart (list (list "a" #("p") #(1))) :x-min 1)', ":x-min is for X values that are dates")
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2))) :x-lines (list (date 2024 1 1)))',
                             ":x-lines must be a number, like the chart's X values")
        self.assertLispError('(plot-chart (list (list "a" #("p") #(1))) :x-lines (list "z"))', "the chart has no category")
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :shade (list 1 2))', "each :shade entry is a list")

    def test_areas_and_bands(self):
        ax = self.drawn('(plot-chart (list (list "area" #(1 2 3) #(1 3 2) :fill #t)'
                        '                  (list "band" #(1 2 3) #(4 5 6) :fill (list 5 nan 8) :line #t)))')
        area, band = ax.collections
        self.assertEqual(sorted({tuple(v) for v in area.get_paths()[0].vertices}),
                         [(1, 0), (1, 1), (2, 0), (2, 3), (3, 0), (3, 2)])           # down to 0
        self.assertEqual(sorted({tuple(v) for v in band.get_paths()[0].vertices}),
                         [(1, 4), (1, 5), (3, 6), (3, 8)])                           # X = 2 is left out
        self.assertEqual(len(self.specs[-1]["series"][1]["x"]), 2)
        self.assertEqual(self.legend_texts(), ["area", "band"])
        self.assertLispError('(plot-chart (list (list "a" #(1 2) #(1 2) :fill #(1))))', "a's :fill has 1 values, for 2")

    def test_values_printed_on_bars_and_points(self):
        ax = self.drawn('(plot-chart (list (list "a" #("p" "q") #(1500 25.5) :bars #t :labels #t)'
                        '                  (list "b" #("p" "q") #(0.25 0.5) :labels "{:.0%}" :secondary #t)))')
        self.assertEqual([t.get_text() for t in ax.texts], ["1,500", "25.5"])
        self.assertEqual([t.get_text() for t in self.fig.axes[1].texts], ["25%", "50%"])

    def test_histograms(self):
        self.run_lisp('(plot-histogram #(1 2 2 3 3 3 nan 9) :bins (list 0 2 4 10))')
        spec = self.specs[-1]
        self.assertEqual(spec["series"][0]["x"], [1.0, 3.0, 7.0])                    # the bins' middles
        self.assertEqual(spec["series"][0]["y"], [1.0, 5.0, 1.0])                    # 2 counts in [2, 4)
        self.assertEqual((spec["bar_width"], spec["legend"], spec["y_axis"]["lines"]), (1.0, None, []))
        self.run_lisp('(plot-histogram (list (list "a" #(1 1 2 2)) (list "b" #(2 2 2 2) :color "red"))'
                      '                :bins 2 :percent #t :title "T")')
        spec = self.specs[-1]
        self.assertEqual([s["y"] for s in spec["series"]], [[50.0, 50.0], [0.0, 100.0]])
        self.assertEqual((spec["series"][1]["color"], spec["title"], spec["legend"]), ("red", "T", "best"))
        self.assertEqual(spec["y_label"], "percent")
        self.assertLispError("(plot-histogram #())", "there are no values to count")
        self.assertLispError('(plot-histogram #(1 2) :bins 0)', ":bins is how many bins there are")

    def test_panels_share_the_x_axis(self):
        ax = self.drawn('(plot-panels (list (list (list (list "a" #(1 2 3) #(1 2 3))) :title "top" :y-log #t)'
                        '                   (list (list (list "b" #(2 3 4) #(5 6 7) :bars #t)'
                        '                               (list "c" #(2 3 4) #(1 1 1) :secondary #t))))'
                        '             :title "Both" :heights (list 3 1) :x-label "x" :shade (list (list 2 3)))')
        spec = self.specs[-1]
        self.assertEqual((spec["height"], spec["heights"]), (6.0, [3.0, 1.0]))
        top, bottom, right = self.fig.axes
        self.assertIs(ax, top)
        self.assertEqual((top.get_title(), top.get_yscale(), bottom.get_xlabel(), top.get_xlabel()),
                         ("top", "log", "x", ""))
        self.assertEqual(top.get_xlim(), bottom.get_xlim())                         # one X axis
        self.assertEqual(self.fig.get_suptitle(), "Both")
        self.assertEqual([len([p for p in a.patches if p.get_x() == 2]) for a in (top, bottom)], [1, 1])  # shaded
        self.assertFalse(any(t.get_visible() and t.get_text() for t in top.get_xticklabels()))
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')                # the GUI's next chart
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        self.assertEqual((self.fig.axes, self.fig.get_suptitle()), ([ax], ""))
        self.assertEqual(ax.get_subplotspec().get_geometry(), (1, 1, 0, 0))

    def test_the_figure_s_title_is_above_the_top_panel_s(self):
        # six panels with titles, on a tall figure, where matplotlib's own layout overlaps the two titles
        panel = '(list (list (list "a" #(1 2 3) #(1 2 3))) :title "a panel")'
        top = self.drawn('(plot-panels (list %s) :title "All of them" :height 16)' % " ".join([panel] * 6))
        self.fig.set_size_inches(8, 16)
        lisp_charts.draw_chart_on_axes(self.fig, top, self.specs[-1])       # (laid out for this size)
        renderer = self.fig.canvas.get_renderer()
        figure_title = self.fig._suptitle.get_window_extent(renderer)
        self.assertGreaterEqual(figure_title.y0, top.title.get_window_extent(renderer).y1)

    def test_panel_mistakes_and_summary(self):
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))) :x-min 0)))', ":x-min isn't an option")
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))))) :heights (list 1 2))',
                             ":heights is a list of the panels' heights")
        self.assertLispError('(plot-panels (list (list (list (list "a" #(1) #(1))))'
                             '                   (list (list (list "b" #("p") #(1))))))', "share one X axis")
        self.run_lisp('(plot-panels (list (list (list (list "a" #(1) #(1))))'
                      '                   (list (list (list "b" #(1) #(1))) :legend "upper left")) :legend #f)')
        self.assertEqual([panel["legend"] for panel in self.specs[-1]["panels"]], [None, "upper left"])
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(plot-panels (list (list (list (list "a" #(1) #(1))) :title "A")'
                      '                   (list (list (list "b" #(1) #(2) :fill #t)))) :title "Two")')
        self.assertEqual(self.printed(), "[chart] Two\n  panel 1: A\n    a: 1 points (line)\n"
                                         "  panel 2:\n    b: 1 points (filled)\n")

    def test_chart_size(self):
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))) :width 9 :height 2.5)')
        self.assertEqual((self.specs[-1]["width"], self.specs[-1]["height"]), (9.0, 2.5))
        self.env[lisp_core.Symbol("names")] = lisp_core.LispVector([lisp_core.LispString("s%d" % i)
                                                                    for i in range(40)])
        self.run_lisp('(plot-chart (list (list "a" names (vector-map (lambda (n) 1) names) :bars #t)) :horizontal #t)')
        self.assertEqual(self.specs[-1]["height"], 1.5 + 0.25 * 40)          # tall enough for 40 labels
        self.assertLispError('(plot-chart (list (list "a" #(1) #(1))) :width 0)', ":width is the chart's width")

    def test_a_new_chart_in_the_same_figure_starts_fresh(self):
        """The GUI draws each chart on the same axes."""
        ax = self.drawn('(plot-chart (list (list "a" #(1 2) #(3 4) :bars #t :secondary #t)) :horizontal #t)')
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')
        lisp_charts.draw_chart_on_axes(self.fig, ax, self.specs[-1])
        self.assertEqual(self.fig.axes, [ax])
        self.assertFalse(ax.yaxis_inverted())
        self.assertEqual(ax.get_zorder(), 0)

    def test_the_console_summary_and_saving(self):
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4) :bars #t :symbol #t)'
                      '                  (list "b" #(1 2) #(3 4) :secondary #t)) :title "Two" :width 4 :height 2)')
        self.assertEqual(self.printed(), "[chart] Two\n  a: 2 points (symbols, bars)\n"
                                         "  b: 2 points (line, on the secondary axis)\n")
        if lisp_charts.MATPLOTLIB_AVAILABLE:
            import matplotlib.image
            folder = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, folder, True)
            self.run_lisp('(save-chart "%s" 4 3 50)' % os.path.join(folder, "given.png"))
            self.assertEqual(matplotlib.image.imread(os.path.join(folder, "given.png")).shape[:2], (150, 200))
            self.run_lisp('(save-chart "%s" \'() \'() 50)' % os.path.join(folder, "own.png"))   # the chart's size
            self.assertEqual(matplotlib.image.imread(os.path.join(folder, "own.png")).shape[:2], (100, 200))


def shapefile_zip(records, fields):
    """A zipped shapefile, as the Census's are, for testing: records are
    (rings, values) -- rings a list of closed rings of (x, y) points, or []
    for a record without a shape -- and fields are (name, kind, width)."""
    import struct
    import zipfile
    contents = []
    for rings, _ in records:
        if not rings:
            contents.append(struct.pack("<i", 0))
            continue
        points = [point for ring in rings for point in ring]
        starts = [sum(len(r) for r in rings[:i]) for i in range(len(rings))]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        contents.append(struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(points))
                        + struct.pack("<%di" % len(rings), *starts)
                        + b"".join(struct.pack("<2d", x, y) for x, y in points))
    body = b"".join(struct.pack(">2i", i + 1, len(c) // 2) + c for i, c in enumerate(contents))
    shp = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2) + struct.pack("<2i8d", 1000, 5, *[0.0] * 8) + body
    header_length, record_length = 32 + 32 * len(fields) + 1, 1 + sum(width for _, _, width in fields)
    dbf = struct.pack("<4BIHH20x", 3, 126, 1, 1, len(records), header_length, record_length)
    for name, kind, width in fields:
        dbf += struct.pack("<11sc4xBB14x", name.encode(), kind.encode(), width, 0)
    dbf += b"\r"
    for _, values in records:
        dbf += b" " + b"".join((str(v).ljust(w) if k == "C" else str(v).rjust(w)).encode()
                               for v, (_, k, w) in zip(values, fields))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("cb_test.shp", shp)
        z.writestr("cb_test.dbf", dbf + b"\x1a")
        z.writestr("cb_test.cpg", "UTF-8")
    return archive.getvalue()


def square(lon, lat, size=1.0):
    """A closed ring around a square, clockwise (as a shapefile's outside rings go)."""
    return [(lon, lat), (lon, lat + size), (lon + size, lat + size), (lon + size, lat), (lon, lat)]


class TestMaps(LispTestCase):
    """lisp_maps: reading the Census's shapefiles (made up here, with the
    Census's server played by a fake), the equal-area projection, and
    plot-map."""

    FIELDS = [("STATEFP", "C", 2), ("GEOID", "C", 5), ("NAME", "C", 20), ("ALAND", "N", 14)]
    # Three made-up counties -- two in "state 36" (one with a lake in it), one in 06 -- and a record
    # with no shape.
    RECORDS = [([square(-75, 42, 2), [(-74.5, 42.5), (-73.5, 42.5), (-73.5, 43.5), (-74.5, 43.5), (-74.5, 42.5)]],
                ["36", "36001", "Albany", 5000]),
               ([square(-73, 42)], ["36", "36003", "Bronx", 1500]),
               ([square(-120, 37)], ["06", "06001", "Alameda", 2000]),
               ([], ["06", "06003", "Alpine", ""])]

    def setUp(self):
        super().setUp()
        import lisp_maps
        self.lisp_maps = lisp_maps
        self.specs = []
        self.env = lisp_builtins.make_global_env(output=self.out.append, plot=self.specs.append)
        self.urls = []
        archive = shapefile_zip(self.RECORDS, self.FIELDS)

        def fake_download(url, cache_hours, headers, who, shown_url=None):
            self.urls.append(url)
            if "GENZ2026" in url or "GENZ2025" in url:
                raise lisp_core.LispError("%s: %s returned HTTP 404 Not Found" % (who, url))
            return archive
        self.kept = tempfile.mkdtemp()               # where the boundary files are kept, for these tests
        self.addCleanup(shutil.rmtree, self.kept, True)
        for patcher in (mock.patch.object(lisp_maps.lisp_http, "download", fake_download),
                        mock.patch.dict(os.environ, {"LISP_MAPS_DIRECTORY": self.kept})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def column(self, src, name):
        return self.run_lisp('(table-column %s "%s")' % (src, name)).items.tolist()

    def test_reading_a_shapefile(self):
        names, rows, shapes = self.lisp_maps.read_shapefile(shapefile_zip(self.RECORDS, self.FIELDS), "t")
        self.assertEqual(names, ["STATEFP", "GEOID", "NAME", "ALAND"])
        self.assertEqual(rows[0], ["36", "36001", "Albany", 5000])
        self.assertEqual(rows[3][3], None)                                   # a blank number
        self.assertEqual([len(shape.rings) for shape in shapes], [2, 1, 1, 0])
        self.assertEqual(shapes[1].rings[0].tolist(), [list(p) for p in square(-73, 42)])
        self.assertEqual(str(shapes[0]), "#<shape: 2 rings>")
        renamed = shapefile_zip([([square(0, 0)], ["10027"])], [("GEOID20", "C", 5)])
        self.assertEqual(self.lisp_maps.read_shapefile(renamed, "t")[0], ["GEOID"])     # 2020's "20" dropped

    def test_census_shapes(self):
        self.run_lisp('(define c (census-shapes "county"))')
        self.assertShows("(table-column-names c)", '("STATEFP" "GEOID" "NAME" "ALAND" "shape")')
        self.assertShows('(table-column c "GEOID")', '#("36001" "36003" "06001" "06003")')
        self.assertTrue(self.urls[-1].endswith("GENZ2024/shp/cb_2024_us_county_20m.zip"))   # the latest there is
        self.run_lisp('(define ny (census-shapes "county" :state "NY"))')
        self.assertShows('(table-column ny "NAME")', '#("Albany" "Bronx")')
        self.assertTrue(self.urls[-1].endswith("cb_2024_us_county_500k.zip"))   # one state: more detail
        self.run_lisp('(census-shapes "tract" :state 6 :year 2023)')
        self.assertTrue(self.urls[-1].endswith("GENZ2023/shp/cb_2023_06_tract_500k.zip"))
        self.run_lisp('(census-shapes "zip")')
        self.assertTrue(self.urls[-1].endswith("GENZ2020/shp/cb_2020_us_zcta520_500k.zip"))
        self.assertLispError('(census-shapes "tract")', "give :state")
        self.assertLispError('(census-shapes "county" :state "XX")', "isn't a state's postal abbreviation")
        self.assertLispError('(census-shapes "parish")', "the levels are")

    def test_boundary_files_are_kept_for_good(self):
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # 2026 and 2025: none yet; 2024
        self.assertEqual(os.listdir(self.kept), ["cb_2024_us_county_20m.zip"])
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # kept: not downloaded again
        shutil.copy(os.path.join(self.kept, "cb_2024_us_county_20m.zip"),
                    os.path.join(self.kept, "cb_2025_us_county_20m.zip"))
        self.run_lisp('(census-shapes "county")')
        self.assertEqual(len(self.urls), 3)                                  # the newest kept: 2025's
        self.run_lisp('(census-shapes "county" :year 2023)')
        self.assertTrue(self.urls[-1].endswith("cb_2023_us_county_20m.zip"))
        with open(os.path.join(self.kept, "cb_2023_us_county_20m.zip"), "wb") as f:
            f.write(b"not a zip file")
        self.assertLispError('(census-shapes "county" :year 2023)', "delete it, and it will be downloaded again")
        with mock.patch.dict(os.environ, {"LISP_MAPS_DIRECTORY": ""}):
            self.assertEqual(self.lisp_maps.maps_directory(),
                             os.path.join(os.path.expanduser("~"), ".cache", "morris_lisp", "maps"))

    def test_the_projection_keeps_areas(self):
        """A one-degree square's area on the map is its area on the earth:
        R squared, times its width in radians, times the difference of the
        sines of its latitudes -- wherever it is."""
        R = self.lisp_maps.EARTH_RADIUS_KM
        edge = np.linspace(0, 1, 400)
        for lon, lat, parameters in ((-100, 30, (-96, 37.5, 29.5, 45.5)), (-80, 60, (-96, 37.5, 29.5, 45.5)),
                                     (179.5, 52, (-154, 50, 55, 65))):        # (across the 180th meridian)
            lons = np.concatenate([lon + 0 * edge, lon + edge, lon + 1 + 0 * edge, lon + 1 - edge])
            lats = np.concatenate([lat + edge, lat + 1 + 0 * edge, lat + 1 - edge, lat + 0 * edge])
            x, y = self.lisp_maps.albers(lons, lats, *parameters)
            area = abs(self.lisp_maps.ring_area(np.column_stack([x, y])))
            on_earth = R ** 2 * math.radians(1) * (math.sin(math.radians(lat + 1)) - math.sin(math.radians(lat)))
            self.assertAlmostEqual(area / on_earth, 1, places=5)
        self.assertAlmostEqual(float(self.lisp_maps.longitude_difference(179.8, -154)), -26.2, places=6)  # the short way

    def test_where_places_go_on_a_map_of_the_country(self):
        shape = self.lisp_maps.Shape
        places = {"contiguous": shape([np.array(square(-100, 40))]), "alaska": shape([np.array(square(-150, 62))]),
                  "hawaii": shape([np.array(square(-157, 20, 0.5))]), "puerto rico": shape([np.array(square(-66.5, 18, 0.3))]),
                  "pacific": shape([np.array(square(144.6, 13.3, 0.3))])}                    # Guam
        for region, place in places.items():
            self.assertEqual(self.lisp_maps.place_region(place), region)
        project = self.lisp_maps.map_projection(list(places.values()))
        self.assertIsNone(project(places["pacific"]))                        # not drawn
        alaska = project(places["alaska"])[0]
        center_lon, origin_lat, p1, p2, scale = self.lisp_maps.NATIONAL_PROJECTIONS["alaska"]
        corners = np.array(square(-150, 62))
        own = np.column_stack(self.lisp_maps.albers(corners[:, 0], corners[:, 1], center_lon, origin_lat, p1, p2))
        self.assertAlmostEqual(abs(self.lisp_maps.ring_area(alaska)) / abs(self.lisp_maps.ring_area(own)),
                               0.35 ** 2)                                     # Alaska, at 35% of the scale
        one_state = self.lisp_maps.map_projection([places["contiguous"]])     # a smaller map: fitted to it
        x, y = one_state(places["contiguous"])[0].mean(axis=0)
        self.assertLess(abs(x), 60)                                           # (its middle is near the middle)

    def test_matching_data_to_places(self):
        codes = ["06", "36", "48"]
        self.env[lisp_core.Symbol("data")] = lisp_tables.make_table_value([
            ("fips", lisp_core.LispVector([lisp_core.LispString("36000"), lisp_core.LispString("06000")])),
            ("value", lisp_core.LispVector([5.0, 7.0]))])
        values = self.lisp_maps.values_for_places(None, codes, self.run_lisp("data"), None, "value", "t")
        self.assertEqual(values, [7.0, 5.0, None])                           # BEA's state codes: 36000 is 36
        self.assertEqual(self.lisp_maps.normalized_code(6, 2), "06")
        self.assertEqual(self.lisp_maps.normalized_code(1001.0, 5), "01001")
        self.env[lisp_core.Symbol("twice")] = lisp_tables.make_table_value([
            ("state", lisp_core.LispVector([lisp_core.LispString("36"), lisp_core.LispString("36")])),
            ("county", lisp_core.LispVector([lisp_core.LispString("001"), lisp_core.LispString("001")])),
            ("value", lisp_core.LispVector([1, 2]))])
        with self.assertRaises(lisp_core.LispError) as caught:
            self.lisp_maps.values_for_places(None, ["36001"], self.run_lisp("twice"), lisp_core.list_to_pairs(
                [lisp_core.LispString("state"), lisp_core.LispString("county")]), "value", "t")
        self.assertIn("more than one row for 36001", str(caught.exception))

    def test_a_map_colored_by_values_with_symbols(self):
        self.run_lisp('(define c (census-shapes "county"))'
                      '(define d (make-table "state" #("36" "36" "06") "county" #("001" "003" "001")'
                      '                      "income" #(50000 80000 nan) "people" #(1000 4000 0)))')
        self.run_lisp('(plot-map c :data d :key (list "state" "county") :fill "income" :symbols "people"'
                      '          :format "${:,.0f}" :title "T")')
        spec = self.specs[-1]
        self.assertEqual((spec["kind"], spec["title"], len(spec["places"])), ("map", "T", 3))   # Alpine: no shape
        self.assertEqual(spec["fill"]["values"], [50000.0, 80000.0, None])
        self.assertEqual([p[2] for p in spec["symbols"]["points"]], [1000.0, 4000.0])          # 0: no symbol
        self.assertEqual(spec["symbols"]["legend_values"], [2500.0, 1000.0, 250.0])   # round numbers
        if not lisp_charts.MATPLOTLIB_AVAILABLE:
            return
        fig = lisp_charts.Figure()
        lisp_charts.FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        lisp_charts.draw_chart_on_axes(fig, ax, spec)
        places, = ax.collections[:1]
        self.assertEqual(len(places.get_paths()), 3)
        symbols = [c for c in ax.collections if c is not places and len(c.get_sizes()) == 2][0]
        sizes = sorted(symbols.get_sizes())
        self.assertAlmostEqual(sizes[1] / sizes[0], 4.0)                     # areas in proportion to the values
        self.assertEqual(len(fig.axes), 2)                                   # the map, and its color bar
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertEqual(legend, ["no data", "$2,500", "$1,000", "$250"])
        self.run_lisp('(plot-chart (list (list "a" #(1 2) #(3 4))))')        # the GUI's next chart
        lisp_charts.draw_chart_on_axes(fig, ax, self.specs[-1])
        self.assertEqual((fig.axes, ax.axison, ax.get_aspect()), ([ax], True, "auto"))

    def test_symbols_on_other_places_and_mistakes(self):
        self.run_lisp('(define c (census-shapes "county"))'
                      '(define d (make-table "GEOID" #("36003" "06001") "n" #(9 5)))')
        self.run_lisp('(plot-map (table-head c 2) :symbols-on c :data d :symbols "n")')    # New York's two
        spec = self.specs[-1]
        self.assertEqual(len(spec["places"]), 2)
        self.assertEqual([value for _, _, value in spec["symbols"]["points"]], [9.0])   # not California's: off the map
        self.assertLispError('(plot-map c :data d :fill "n" :colors "rainbows")', "isn't one of matplotlib's color maps")
        self.assertLispError('(plot-map (make-table "a" #(1)))', "must be a table from census-shapes")
        self.assertLispError('(plot-map c :data (make-table "code" #("1")) :fill "code")', "give :key")
        self.env = lisp_builtins.make_global_env(output=self.out.append)
        self.run_lisp('(define c (census-shapes "county"))'
                      '(plot-map c :data (make-table "GEOID" #("36003") "n" #(9)) :fill "n" :title "M")')
        self.assertEqual(self.printed(), "[map] M\n  3 places, 1 colored by n\n")

    def test_where_a_symbol_goes(self):
        big, small = np.array(square(0, 0, 10), dtype=float), np.array(square(20, 0, 1), dtype=float)
        self.assertEqual(self.lisp_maps.center_of([small, big]).tolist(), [5.0, 5.0])    # the largest piece's middle
        self.assertEqual(self.lisp_maps.round_number_below(217075), 200000)
        self.assertEqual(self.lisp_maps.round_number_below(0.03), 0.025)


if __name__ == "__main__":
    unittest.main()
