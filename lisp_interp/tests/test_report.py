"""lib/report.lsp: reports with control breaks, from a table, in a text file. Every report here is small enough to work out
by hand, and the expected text is written out in full."""

import os
import re
import tempfile

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

LOANS = '''
(define loans (make-table
  "loan-id" (vector "L1" "L2" "L3" "L4" "L5")
  "state"   (vector "NY" "CA" "CA" "CA" "NY")
  "zip"     (vector "10001" "90001" "90002" "90001" "10001")
  "balance" (vector 100.0 200.0 300.0 400.0 500.0)
  "rate"    (vector 5.0 6.0 7.0 8.0 9.0)))
'''

TRANSACTIONS = '''
(define transactions (make-table
  "client" (vector "Zed" "Amy" "Zed" "Amy" "Amy" "Zed")
  "date"   (vector "2026-03-05" "2026-03-02" "2026-03-01" "2026-03-09" "2026-03-01" "2026-03-20")
  "what"   (vector "rent" "coffee" "books" "food" "gas" "gift")
  "amount" (vector 100.0 4.5 30.0 20.0 40.0 5.25)))
'''

# The mortgages by state and by zip code within it, with a grand total, and no pages.
BY_STATE = '''
(define spec
  (make-report-spec
    :report-header "Mortgages ({{loans}} loans)"
    :detail "{{loan-id:<4}} {{zip:<6}} {{balance:>8,.2f}}"
    :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
    :breaks (list (make-report-break :field "state" :header "State {{state}}"
                                     :footer "  {{state}} total: {{loans}} loans {{total:>9,.2f}}")
                  (make-report-break :field "zip" :footer "    {{zip}}: {{total:>9,.2f}}"))
    :report-footer "All: {{loans}} loans {{total:>9,.2f}}"))
'''

BY_STATE_TEXT = """Mortgages (5 loans)
State CA
L2   90001    200.00
L4   90001    400.00
    90001:    600.00
L3   90002    300.00
    90002:    300.00
  CA total: 3 loans    900.00
State NY
L1   10001    100.00
L5   10001    500.00
    10001:    600.00
  NY total: 2 loans    600.00
All: 5 loans  1,500.00
"""


class ReportTestCase(LispTestCase):

    def setUp(self):
        super().setUp()
        self.run_lisp('(load "report.lsp")')
        self.run_lisp(LOANS)
        self.run_lisp(TRANSACTIONS)

    def text(self, spec="spec", table="loans"):
        return str(self.run_lisp("(report-text %s %s)" % (table, spec)))


class TestControlBreaks(ReportTestCase):

    def test_the_mortgages_by_state_and_zip_with_a_grand_total(self):
        self.run_lisp(BY_STATE)
        self.assertEqual(self.text(), BY_STATE_TEXT)

    def test_the_rows_need_not_be_in_order_and_the_table_is_not_changed(self):
        self.run_lisp(BY_STATE)
        before = self.show("loans")
        self.assertEqual(self.text(), BY_STATE_TEXT)          # (the loans are in no order)
        self.assertEqual(self.show("loans"), before)

    def test_a_header_has_the_totals_of_its_group_as_well_as_a_footer(self):
        self.run_lisp(LOANS)
        self.run_lisp('''(define spec (make-report-spec
            :detail "{{loan-id}}"
            :summaries (list (list "loans" 'count) (list "total" 'sum "balance") (list "rate" 'weighted-mean "rate" "balance"))
            :breaks (list (make-report-break :field "state"
                            :header "{{state}}: {{loans}} loans, {{total:,.1f}}, at {{rate:.3f}}%"))))''')
        # CA: 200, 300, 400 at 6, 7, 8 -> (1200 + 2100 + 3200) / 900; NY: 100, 500 at 5, 9 -> (500 + 4500) / 600
        self.assertEqual(self.text(), "CA: 3 loans, 900.0, at 7.222%\nL2\nL3\nL4\nNY: 2 loans, 600.0, at 8.333%\nL1\nL5\n")

    def test_a_report_with_no_breaks_has_a_grand_total_only(self):
        self.run_lisp('''(define spec (make-report-spec
            :detail "{{loan-id}} {{balance:,.0f}}" :summaries (list (list "total" 'sum "balance"))
            :report-footer "total {{total:,.0f}}"))''')
        self.assertEqual(self.text(), "L1 100\nL2 200\nL3 300\nL4 400\nL5 500\ntotal 1,500\n")

    def test_the_innermost_group_is_sorted_by_detail_order(self):
        self.run_lisp('''(define spec (make-report-spec
            :detail "{{zip}} {{loan-id}} {{balance:,.0f}}" :detail-order '("balance")
            :breaks (list (make-report-break :field "state" :header "{{state}}"))))''')
        self.assertEqual(self.text(), "CA\n90001 L2 200\n90002 L3 300\n90001 L4 400\nNY\n10001 L1 100\n10001 L5 500\n")

    def test_a_table_already_in_order_can_be_said_to_be(self):
        self.run_lisp('''(define sorted (table-sort loans (list "state" "zip")))
          (define spec (make-report-spec :presorted #t :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :header "{{state}}")
                          (make-report-break :field "zip" :header " {{zip}}"))))''')
        self.assertEqual(self.text(table="sorted"), "CA\n 90001\nL2\nL4\n 90002\nL3\nNY\n 10001\nL1\nL5\n")

    def test_summary_functions_are_those_of_table_group_by(self):
        self.run_lisp('''(define spec (make-report-spec
            :summaries (list (list "low" 'min "balance") (list "high" 'max "balance") (list "mean" 'mean "balance"))
            :breaks (list (make-report-break :field "state" :footer "{{state}} {{low:.0f}}-{{high:.0f}} mean {{mean:.1f}}"))
            :report-footer "{{low:.0f}}-{{high:.0f}} mean {{mean:.1f}}"))''')
        self.assertEqual(self.text(), "CA 200-400 mean 300.0\nNY 100-500 mean 300.0\n100-500 mean 300.0\n")

    def test_the_break_can_be_on_numbers_and_on_dates(self):
        self.run_lisp('''(define table (make-table "year" #(2025 2024 2025) "when" (vector (date 2026 1 5) (date 2026 1 6) (date 2026 1 5)) "x" #(1 2 4)))
          (define spec (make-report-spec :detail "{{x:.0f}}" :summaries (list (list "sum" 'sum "x"))
            :breaks (list (make-report-break :field "year" :footer "{{year}}: {{sum:.0f}}")
                          (make-report-break :field "when" :footer "  {{when}}: {{sum:.0f}}"))))''')
        self.assertEqual(self.text(table="table"), "2\n  2026-01-06: 2\n2024: 2\n1\n4\n  2026-01-05: 5\n2025: 5\n")

    def test_variables_and_the_row_number_are_in_the_templates(self):
        self.run_lisp('''(define spec (make-report-spec
            :variables (list (list 'title "Book") (list 'who "me"))
            :report-header "{{title}} by {{who}}"
            :detail "{{row-number}}. {{loan-id}}"
            :breaks (list (make-report-break :field "state" :footer "({{title}})"))))''')
        self.assertEqual(self.text(), "Book by me\n1. L2\n2. L3\n3. L4\n(Book)\n4. L1\n5. L5\n(Book)\n")

    def test_a_template_may_have_each_and_if_and_says_the_same_as_the_simple_ones(self):
        simple = '''(make-report-spec :detail "{{loan-id}}:{{balance:,.0f}}" :breaks (list (make-report-break :field "state")))'''
        general = '''(make-report-spec :detail "{{#if loan-id}}{{loan-id}}{{/if}}:{{balance:,.0f}}" :breaks (list (make-report-break :field "state")))'''
        self.assertEqual(self.text(simple), self.text(general))
        self.assertEqual(self.text(simple), "L2:200\nL3:300\nL4:400\nL1:100\nL5:500\n")

    def test_a_group_with_no_detail_template_shows_only_its_headers_and_footers(self):
        self.run_lisp('''(define spec (make-report-spec :summaries (list (list "n" 'count))
            :breaks (list (make-report-break :field "state" :header "{{state}}" :footer "  {{n}}"))))''')
        self.assertEqual(self.text(), "CA\n  3\nNY\n  2\n")

    def test_a_template_may_be_several_lines_and_a_blank_one_is_a_blank_line(self):
        self.run_lisp('''(define spec (make-report-spec :detail ""
            :breaks (list (make-report-break :field "state" :header "{{state}}\\n--" :footer ""))))''')
        # CA: its header of two lines, a blank row for each of three, a blank footer; NY: two rows
        self.assertEqual(self.text(), "CA\n--\n\n\n\n\nNY\n--\n\n\n\n")

    def test_an_empty_table_has_its_header_and_footer_with_nothing_counted(self):
        self.run_lisp('''(define nothing (table-where loans "balance" 12345))
          (define spec (make-report-spec :report-header "start" :detail "{{loan-id}}"
            :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
            :breaks (list (make-report-break :field "state" :header "{{state}}"))
            :report-footer "{{loans}} loans {{total:.1f}}"))''')
        self.assertEqual(self.text(table="nothing"), "start\n0 loans 0.0\n")


class TestPages(ReportTestCase):

    PAGED = '''
    (define spec
      (make-report-spec
        :page-lines 12
        :page-header "Mortgages   page {{page}}\\n-----"
        :page-footer "(page total {{total:,.0f}})"
        :detail "{{loan-id:<4}} {{zip:<6}} {{balance:>6,.0f}}"
        :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
        :breaks (list (make-report-break :field "state" :header "State {{state}}" :footer "  {{state}}: {{loans}} loans {{total:,.0f}}")
                      (make-report-break :field "zip" :footer "    {{zip}}: {{total:,.0f}}"))
        :report-footer "ALL {{loans}} loans {{total:,.0f}}"))
    '''

    def test_pages_have_a_header_a_footer_with_the_totals_of_their_rows_and_a_length(self):
        self.run_lisp(self.PAGED)
        self.assertEqual(self.text(), """Mortgages   page 1
-----
State CA
L2   90001     200
L4   90001     400
    90001: 600
L3   90002     300
    90002: 300
  CA: 3 loans 900
State NY
L1   10001     100
(page total 1,000)
Mortgages   page 2
-----
L5   10001     500
    10001: 600
  NY: 2 loans 600
ALL 5 loans 1,500





(page total 500)
""")

    def test_every_page_is_the_length_it_was_asked_to_be(self):
        self.run_lisp(self.PAGED)
        lines = self.text().rstrip("\n").split("\n")
        self.assertEqual(len(lines), 24)                        # two pages of 12
        self.assertTrue(lines[11].startswith("(page total"))
        self.assertTrue(lines[23].startswith("(page total"))

    def test_the_number_of_pages_is_what_write_report_gives_back(self):
        self.run_lisp(self.PAGED)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.txt")
            pages = self.run_lisp('(write-report loans "%s" spec)' % path)
            self.assertEqual(pages, 2)
            self.assertEqual(open(path).read(), self.text())

    def test_a_page_separator_follows_each_page(self):
        self.run_lisp(self.PAGED.replace(":page-lines 12", ":page-lines 12 :page-separator \"\\f\""))
        pages = self.text().split("\f\n")
        self.assertEqual(len(pages), 3)                          # (after the last, an empty piece)
        self.assertTrue(pages[0].startswith("Mortgages   page 1") and pages[1].startswith("Mortgages   page 2"))
        self.assertEqual(pages[2], "")

    def test_a_group_header_is_never_the_last_line_of_a_page(self):
        # State NY's header needs room for its first row too: the page breaks before it, not after
        self.run_lisp(self.PAGED.replace(":page-lines 12", ":page-lines 11"))
        text = self.text()
        self.assertNotIn("State NY\n(page total", text)
        self.assertIn("(page total 900)\nMortgages   page 2\n-----\nState NY\nL1", text)

    def test_the_footer_of_a_page_has_the_keys_of_the_group_it_ends_in(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 5
            :page-header "{{state}}-{{page}}" :page-footer "end {{state}} {{n}}"
            :summaries (list (list "n" 'count))
            :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state"))))''')
        # a page holds 5 lines: its header and footer and three between. CA's three rows fill the first; the page ends,
        # with CA's key, when NY's first row does not fit; the second has NY's two rows, a blank line and its footer.
        self.assertEqual(self.text(), "CA-1\nL2\nL3\nL4\nend CA 3\nNY-2\nL1\nL5\n\nend NY 2\n")

    def test_a_group_can_start_a_new_page_and_restart_the_page_numbers(self):
        self.run_lisp(TRANSACTIONS)
        self.run_lisp('''(define letters (make-report-spec
            :page-lines 12
            :page-header "Acme Bank - {{client}}   page {{page}}"
            :page-footer "-- page {{page}} --"
            :detail "{{date}} {{what:<8}} {{amount:>7,.2f}}" :detail-order '("date")
            :summaries (list (list "n" 'count) (list "total" 'sum "amount"))
            :breaks (list (make-report-break :field "client" :new-page #t :restart-page-numbers #t
                            :header "Dear {{client}}: {{n}} transactions\\n"
                            :footer "Total {{total:,.2f}}"))))''')
        self.assertEqual(self.text("letters", "transactions"), """Acme Bank - Amy   page 1
Dear Amy: 3 transactions

2026-03-01 gas        40.00
2026-03-02 coffee      4.50
2026-03-09 food       20.00
Total 64.50




-- page 1 --
Acme Bank - Zed   page 1
Dear Zed: 3 transactions

2026-03-01 books      30.00
2026-03-05 rent      100.00
2026-03-20 gift        5.25
Total 135.25




-- page 1 --
""")

    def test_without_restarting_the_numbers_go_on(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "p{{page}}" :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :new-page #t))))''')
        self.assertEqual(self.text(), "p1\nL2\nL3\nL4\np2\nL1\nL5\n\n")        # CA fills 3 of a page's 4 lines, then NY's page

    def test_the_first_group_does_not_leave_an_empty_first_page(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 6 :page-header "p{{page}}" :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :new-page #t))))''')
        self.assertTrue(self.text().startswith("p1\nL2\nL3\nL4\n"))

    def test_the_page_summaries_are_those_of_the_rows_on_the_page(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 5 :page-footer "{{total:,.0f}} of {{n}}" :detail "{{loan-id}}"
            :summaries (list (list "n" 'count) (list "total" 'sum "balance"))))''')
        # the rows by loan: L1..L5 of 100..500, four lines of rows per page
        self.assertEqual(self.text(), "L1\nL2\nL3\nL4\n1,000 of 4\nL5\n\n\n\n500 of 1\n")

    def test_a_page_that_is_too_short_for_its_header_and_footer_is_refused(self):
        self.run_lisp('(define spec (make-report-spec :page-lines 2 :detail "{{loan-id}}"))')
        self.assertLispError("(report-text loans spec)", ":page-lines")

    def test_a_block_taller_than_a_page_goes_on_a_page_of_its_own_and_the_report_ends(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "h" :detail "a\\nb\\nc\\nd\\ne"))''')
        text = self.text()
        self.assertEqual(text.count("h\n"), 5)                   # one page for each row (the header, and the five lines)
        self.assertEqual(text.count("e\n"), 5)


class TestLargeReports(ReportTestCase):

    def test_a_report_of_many_pages_is_written_in_pieces_and_is_the_same_as_the_string(self):
        self.run_lisp('''(define big (make-table "k" (list->vector (map (lambda (i) (if (< i 1500) "a" "b")) (iota 3000))) "x" (make-vector 3000 2.0)))
          (define spec (make-report-spec :detail "{{x:.0f}}" :page-lines 100 :page-header "page {{page}}" :page-footer "end {{page}}"
            :summaries (list (list "n" 'count) (list "total" 'sum "x"))
            :breaks (list (make-report-break :field "k" :footer "{{k}} {{n}} {{total:.0f}}"))))''')
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.txt")
            pages = self.run_lisp('(write-report big "%s" spec)' % path)
            written = open(path).read()
        self.assertEqual(written, self.text("spec", "big"))
        self.assertEqual(pages, 31)                              # 3002 lines of body, 98 to a page (a, b, and each page's two)
        self.assertEqual(len(written.rstrip("\n").split("\n")), 31 * 100)
        self.assertIn("a 1500 3000\n", written)
        self.assertIn("b 1500 3000\n", written)

    def test_the_file_is_replaced_not_added_to(self):
        self.run_lisp(BY_STATE)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.txt")
            open(path, "w").write("old text that is longer than the report " * 100)
            self.run_lisp('(write-report loans "%s" spec)' % path)
            self.assertEqual(open(path).read(), BY_STATE_TEXT)


class TestTheSpecIsChecked(ReportTestCase):

    def test_a_template_may_use_only_the_names_it_has(self):
        self.run_lisp('(define spec (make-report-spec :detail "{{loan-id}} {{typo}}"))')
        self.assertLispError("(report-text loans spec)", "the detail uses {{typo}}")
        self.run_lisp('(define spec (make-report-spec :breaks (list (make-report-break :field "state" :header "{{zip}}"))))')
        self.assertLispError("(report-text loans spec)", "header of the break on state uses {{zip}}")
        self.run_lisp('''(define spec (make-report-spec :summaries (list (list "total" 'sum "balance"))
            :breaks (list (make-report-break :field "state" :header "{{loan-id}}"))))''')
        self.assertLispError("(report-text loans spec)", "uses {{loan-id}}")
        self.run_lisp('(define spec (make-report-spec :page-header "{{total}}" :summaries (list (list "total" (quote sum) "balance"))))')
        self.assertLispError("(report-text loans spec)", "page header uses {{total}}")

    def test_an_outer_break_may_not_use_the_key_of_an_inner_one(self):
        self.run_lisp('''(define spec (make-report-spec
            :breaks (list (make-report-break :field "state" :footer "{{zip}}") (make-report-break :field "zip"))))''')
        self.assertLispError("(report-text loans spec)", "footer of the break on state uses {{zip}}")

    def test_the_error_names_what_can_be_used(self):
        self.run_lisp('(define spec (make-report-spec :detail "{{nope}}"))')
        self.assertLispError("(report-text loans spec)", "loan-id")

    def test_a_break_column_must_be_in_the_table_and_named(self):
        self.run_lisp('(define spec (make-report-spec :breaks (list (make-report-break :field "county"))))')
        self.assertLispError("(report-text loans spec)", "a break is on the column county, and the table has loan-id state zip balance rate")
        self.run_lisp('(define spec (make-report-spec :breaks (list (make-report-break :header "x"))))')
        self.assertLispError("(report-text loans spec)", "needs the name of the column")
        self.run_lisp('(define spec (make-report-spec :breaks (list "state")))')
        self.assertLispError("(report-text loans spec)", "make-report-break")

    def test_the_detail_order_the_summaries_and_the_templates_are_checked(self):
        self.run_lisp('(define spec (make-report-spec :detail-order (list "nothing")))')
        self.assertLispError("(report-text loans spec)", ":detail-order names the column nothing")
        self.run_lisp('(define spec (make-report-spec :summaries (list (list "total" "balance"))))')
        self.assertLispError("(report-text loans spec)", "a summary is (name function column)")
        self.run_lisp('(define spec (make-report-spec :detail 5))')
        self.assertLispError("(report-text loans spec)", "the detail must be a string")

    def test_the_arguments_are_checked(self):
        self.run_lisp(BY_STATE)
        self.assertLispError("(report-text 5 spec)", "must be a table")
        self.assertLispError("(report-text loans 5)", "make-report-spec")
        self.assertLispError('(write-report loans "/nonexistent-folder/x.txt" spec)', "nonexistent-folder")

    def test_a_summary_function_that_table_group_by_does_not_have_is_its_error(self):
        self.run_lisp('(define spec (make-report-spec :summaries (list (list "x" (quote frobnicate) "balance")) :detail "{{loan-id}}"))')
        self.assertLispError("(report-text loans spec)", "frobnicate")


class TestTheLibraryAsAutoloaded(LispTestCase):

    def test_the_functions_are_there_without_loading_the_library_when_the_autoloads_are_loaded(self):
        self.run_lisp('(load "autoloads.lsp")')
        self.run_lisp(LOANS)
        text = self.show('(report-text loans (make-report-spec :detail "{{loan-id}}" '
                         ':breaks (list (make-report-break :field "state" :footer "{{state}}"))))')
        self.assertEqual(text, '"L2\nL3\nL4\nCA\nL1\nL5\nNY\n"')
        self.assertShows("(report-spec? (make-report-spec))", "#t")
        self.assertShows('(report-break-new-page (make-report-break :field "x" :new-page #t))', "#t")


class TestTheExample(LispTestCase):

    def test_it_writes_the_mortgage_report_and_a_letter_to_each_client(self):
        with in_a_temporary_folder() as folder:
            lisp_core.run_file(os.path.join(EXAMPLES, "report_example.lsp"), self.env)
            report = open(os.path.join(folder, "mortgage_report.txt")).read()
            web_page = open(os.path.join(folder, "mortgage_report.html")).read()
            letters = open(os.path.join(folder, "client_letters.txt")).read()
        shown = self.printed()
        self.assertIn("3 pages written to mortgage_report.txt", shown)
        lines = report.rstrip("\n").split("\n")
        self.assertEqual(len(lines), 78)                                   # three pages of 26 lines
        # (the 30 loans, 12 and 11 and 7 to a page: a page 2 and a page 3 start with a repeated header; their balances add up as the pages go)
        self.assertEqual([line for line in lines if line.startswith("(this page")],
                         ["(this page: 12 loans, 2,280,000; so far 2,280,000)", "(this page: 11 loans, 2,109,000; so far 4,389,000)",
                          "(this page: 7 loans, 1,416,000; so far 5,805,000)"])
        self.assertEqual([line for line in lines if line.startswith("MORTGAGE REPORT")],
                         ["MORTGAGE REPORT                      page %d of 3" % page for page in (1, 2, 3)])
        self.assertEqual([line for line in lines if "(continued)" in line], ["STATE NY (continued)", "STATE TX (continued)"])
        self.assertIn("3 pages written to mortgage_report.html", shown)
        self.assertEqual(re.findall(r"<section class='page' id='p(\d)'>", web_page), ["1", "2", "3"])
        self.assertIn("<title>Mortgage report</title>", web_page)
        self.assertIn("ALL STATES: 30 loans     5,805,000 at 6.283%", report)   # 150 + 153 + ... + 237 thousand
        for state, count, total in (("CA", 10, "1,935,000"), ("NY", 10, "1,905,000"), ("TX", 10, "1,965,000")):
            self.assertIn("  %s: %d loans     %s at" % (state, count, total), report)
        # a letter to each client, on pages of their own, each numbered from 1
        self.assertEqual(letters.count("page 1\n"), 3)
        for client, total in (("Amy Lee", "64.50"), ("Bo Park", "146.20"), ("Zed Co", "1,235.25")):
            self.assertIn("Dear %s," % client, letters)
            self.assertIn("Statement for %s\n" % client, letters)
            self.assertIn("  Total%s%s\n" % (" " * (7 + 14 - len(total)), total), letters)
        self.assertEqual(letters.count("Thank you for banking with us."), 3)


class TestWhatTheMutationRunAsked(ReportTestCase):
    """Cases that a deliberate breakage of the library showed nothing tested."""

    def test_a_break_column_may_not_have_missing_values(self):
        self.run_lisp('''(define holes (make-table "year" (vector 2025 nan 2025) "x" #(1 2 3)))
          (define spec (make-report-spec :detail "{{x:.0f}}" :breaks (list (make-report-break :field "year"))))''')
        self.assertLispError("(report-text holes spec)", "the column year, which a break is on, has missing values")

    def test_a_table_said_to_be_in_order_that_is_not_is_an_error(self):
        self.run_lisp('''(define spec (make-report-spec :presorted #t :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state"))))''')
        self.assertLispError("(report-text loans spec)", "groups of the summaries are not in the order of the rows")

    def test_a_template_with_each_and_if_may_say_the_names_it_has_and_those_its_loops_make(self):
        self.run_lisp('''(define spec (make-report-spec
            :variables (list (list 'tags (list "a" "b" "c")) (list 'comma ", ") (list 'flag #t))
            :detail "{{loan-id}}: {{#each tag in tags sep comma}}{{tag}}{{/each}}{{#if flag}} (flagged){{else}} (plain){{/if}}"))''')
        self.assertEqual(self.text().split("\n")[0], "L1: a, b, c (flagged)")

    def test_the_list_of_an_each_and_the_name_of_an_if_must_be_there_in_both_branches(self):
        self.run_lisp('(define spec (make-report-spec :detail "{{#each tag in tags}}{{tag}}{{/each}}"))')
        self.assertLispError("(report-text loans spec)", "the detail uses {{tags}}")
        self.run_lisp('(define spec (make-report-spec :detail "{{#if loan-id}}yes{{else}}{{missing}}{{/if}}"))')
        self.assertLispError("(report-text loans spec)", "the detail uses {{missing}}")
        self.run_lisp('(define spec (make-report-spec :detail "{{#if loan-id}}{{missing}}{{/if}}"))')
        self.assertLispError("(report-text loans spec)", "the detail uses {{missing}}")
        self.run_lisp('(define spec (make-report-spec :detail "{{#each t in loan-id sep nope}}{{t}}{{/each}}"))')
        self.assertLispError("(report-text loans spec)", "the detail uses {{nope}}")

    def test_the_header_of_an_outer_break_and_the_report_header_have_only_their_own_names(self):
        self.run_lisp('''(define spec (make-report-spec
            :breaks (list (make-report-break :field "state" :header "{{zip}}") (make-report-break :field "zip"))))''')
        self.assertLispError("(report-text loans spec)", "header of the break on state uses {{zip}}")
        self.run_lisp('(define spec (make-report-spec :report-header "{{balance}}"))')
        self.assertLispError("(report-text loans spec)", "report header uses {{balance}}")

    def test_the_detail_may_say_a_variable_and_the_page(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "h" :variables (list (list 'unit "$"))
            :detail "{{loan-id}} {{unit}}{{balance:.0f}} p{{page}}"))''')
        # a page is a header and three rows (there is no footer), and the second ends with a blank line: and a row that
        # starts a page says that page's number, though it was ready before the page ended
        self.assertEqual(self.text(), "h\nL1 $100 p1\nL2 $200 p1\nL3 $300 p1\nh\nL4 $400 p2\nL5 $500 p2\n\n")

    def test_a_page_that_ends_in_group_headers_has_the_keys_of_the_last_of_them_in_its_footer(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-footer "end {{loan-id}}"
            :breaks (list (make-report-break :field "loan-id" :header "{{loan-id}}"))))''')
        # three headers and the footer to a page: L1 L2 L3 | end L3 ; L4 L5 and a blank | end L5
        self.assertEqual(self.text(), "L1\nL2\nL3\nend L3\nL4\nL5\n\nend L5\n")

    def test_the_file_is_written_a_thousand_lines_at_a_time(self):
        self.run_lisp('''(define big (make-table "x" (make-vector 2500 1.0)))
          (define spec (make-report-spec :detail "{{x:.0f}}"))''')
        written = []
        self.env[lisp_core.Symbol("write-text-file")] = lambda path, text, append=False: written.append((str(text), append))
        self.run_lisp('(write-report big "nowhere" spec)')
        self.assertEqual(written[0], ("", False))                                  # the file is made empty first
        self.assertEqual([text.count("\n") for text, _ in written[1:]], [1000, 1000, 500])
        self.assertTrue(all(append for _, append in written[1:]))

    def test_a_group_header_that_starts_a_page_says_that_pages_number(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 6 :page-header "H" :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :header "{{state}} p{{page}}"))))''')
        # CA fills five lines of the six, NY's header and first row need two: they go to the next page, and the header is
        # written again there, with its number
        self.assertEqual(self.text(), "H\nCA p1\nL2\nL3\nL4\n\nH\nNY p2\nL1\nL5\n\n\n")

    def test_a_group_footer_that_starts_a_page_says_that_pages_number(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 3 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :footer "{{state}} p{{page}}"))))''')
        self.assertEqual(self.text(), "L2\nL3\nL4\nCA p2\nL1\nL5\nNY p3\n\n\n")


class TestPageXOfY(ReportTestCase):

    def test_a_page_may_say_how_many_pages_there_are(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "p{{page}}/{{pages}}" :detail "{{loan-id}}"))''')
        # a page is a header and three rows: five loans make two, and the second ends with a blank line
        self.assertEqual(self.text(), "p1/2\nL1\nL2\nL3\np2/2\nL4\nL5\n\n")

    def test_a_footer_and_a_group_header_may_say_it_too(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 5 :page-footer "{{page}} of {{pages}}" :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :header "{{state}} of {{pages}}"))))''')
        # CA: header and three rows on page 1 and the footer; NY's header and first row fit nowhere on it: page 2 has all of NY
        self.assertEqual(self.text(), "CA of 2\nL2\nL3\nL4\n1 of 2\nNY of 2\nL1\nL5\n\n2 of 2\n")

    def test_the_pages_of_a_run_of_page_numbers_are_those_of_that_run(self):
        self.run_lisp(TRANSACTIONS)
        self.run_lisp('''(define letters (make-report-spec :page-lines 3 :page-header "{{client}} p{{page}}/{{pages}}"
            :detail "{{what}}" :detail-order '("date")
            :breaks (list (make-report-break :field "client" :new-page #t :restart-page-numbers #t))))''')
        # two pages for each client, though there are four pages in all
        self.assertEqual(self.text("letters", "transactions"),
                         "Amy p1/2\ngas\ncoffee\nAmy p2/2\nfood\n\nZed p1/2\nbooks\nrent\nZed p2/2\ngift\n\n")

    def test_each_run_of_page_numbers_has_its_own_total(self):
        self.run_lisp('''(define uneven (make-table "who" (vector "A" "B" "A" "A") "what" (vector "x1" "y1" "x2" "x3")))
          (define spec (make-report-spec :page-lines 3 :page-header "{{who}} p{{page}}/{{pages}}" :detail "{{what}}"
            :breaks (list (make-report-break :field "who" :new-page #t :restart-page-numbers #t))))''')
        # A has three rows, two to a page: two pages; B has one: one page
        self.assertEqual(self.text("spec", "uneven"), "A p1/2\nx1\nx2\nA p2/2\nx3\n\nB p1/1\ny1\n\n")

    def test_the_pages_are_counted_by_a_first_pass_that_writes_nothing(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "{{pages}}" :detail "{{loan-id}}"))''')
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.txt")
            self.assertEqual(self.run_lisp('(write-report loans "%s" spec)' % path), 2)       # (the pages, not twice the pages)
            self.assertEqual(open(path).read(), "2\nL1\nL2\nL3\n2\nL4\nL5\n\n")

    def test_without_pages_in_a_template_there_is_one_pass_only(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :detail "{{loan-id}}"))''')
        seen = []
        original = self.env[lisp_core.Symbol("write-text-file")]
        self.env[lisp_core.Symbol("write-text-file")] = lambda path, text, append=False: seen.append(str(text))
        self.run_lisp('(write-report loans "nowhere" spec)')
        self.assertEqual("".join(seen).count("L1"), 1)


class TestRunningTotals(ReportTestCase):

    def test_a_running_total_in_a_row_includes_the_row_and_restarts_in_its_scope(self):
        self.run_lisp('''(define spec (make-report-spec
            :running (list (list "all" 'sum "balance") (list "st" 'sum "balance" "state") (list "n" 'count "state"))
            :report-header "begin {{all:.0f}}"
            :detail "{{loan-id}} {{all:.0f}} {{st:.0f}} {{n}}"
            :breaks (list (make-report-break :field "state" :header "{{state}} start {{all:.0f}} {{st:.0f}} {{n}}"
                                             :footer "{{state}} end {{all:.0f}} {{st:.0f}} {{n}}"))
            :report-footer "end {{all:.0f}}"))''')
        self.assertEqual(self.text(), "begin 0\nCA start 0 0 0\nL2 200 200 1\nL3 500 500 2\nL4 900 900 3\nCA end 900 900 3\n"
                                      "NY start 900 0 0\nL1 1000 100 1\nL5 1500 600 2\nNY end 1500 600 2\nend 1500\n")

    def test_a_total_of_an_outer_group_goes_on_through_the_groups_inside_it(self):
        self.run_lisp('''(define spec (make-report-spec :running (list (list "st" 'sum "balance" "state") (list "zp" 'sum "balance" "zip"))
            :detail "{{loan-id}} {{st:.0f}} {{zp:.0f}}"
            :breaks (list (make-report-break :field "state") (make-report-break :field "zip"))))''')
        # CA's zips: L2 and L4, then L3: the state's total goes on, and the zip's starts again; NY: L1 and L5
        self.assertEqual(self.text(), "L2 200 200\nL4 600 600\nL3 900 300\nL1 100 100\nL5 600 600\n")

    def test_a_template_with_if_says_the_same_running_total_as_one_without(self):
        self.run_lisp('''(define spec (make-report-spec :running (list (list "so-far" 'sum "balance"))
            :detail "{{#if loan-id}}{{loan-id}}: {{so-far:.0f}}{{/if}}"))''')
        self.assertEqual(self.text(), "L1: 100\nL2: 300\nL3: 600\nL4: 1,000\nL5: 1,500\n".replace("1,000", "1000").replace("1,500", "1500"))

    def test_a_page_has_the_total_brought_forward_and_carried_forward_and_one_that_starts_again(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 5
            :running (list (list "all" 'sum "balance") (list "pg" 'sum "balance" 'page))
            :page-header "h {{all:.0f}} {{pg:.0f}}" :page-footer "f {{all:.0f}} {{pg:.0f}}"
            :detail "{{loan-id}} {{all:.0f}} {{pg:.0f}}"))''')
        self.assertEqual(self.text(), "h 0 0\nL1 100 100\nL2 300 300\nL3 600 600\nf 600 600\n"
                                      "h 600 0\nL4 1000 400\nL5 1500 900\n\nf 1500 900\n")

    def test_a_missing_value_adds_nothing(self):
        self.run_lisp('''(define holes (make-table "x" (vector 1.0 nan 3.0)))
          (define spec (make-report-spec :running (list (list "so-far" 'sum "x")) :detail "{{so-far:.0f}}"))''')
        self.assertEqual(self.text(table="holes"), "1\n1\n4\n")

    def test_a_running_total_is_one_of_the_templates_names_everywhere(self):
        self.run_lisp('''(define spec (make-report-spec :running (list (list "so-far" 'sum "balance"))
            :page-header "{{so-far}}" :page-footer "{{so-far}}" :report-header "{{so-far}}" :report-footer "{{so-far}}"
            :breaks (list (make-report-break :field "state" :header "{{so-far}}" :footer "{{so-far}}"))
            :detail "{{so-far}}"))''')
        self.text()

    def test_the_running_totals_are_checked(self):
        for spec, fragment in (
                ('(list (list "x" (quote mean) "balance"))', "a running total is (name sum column [scope])"),
                ('(list (list "x" (quote sum) "nothing"))', "the running total x needs a column of the table"),
                ('(list (list "x" (quote sum) "balance" "zip"))', "the scope of the running total x is page or the column of a break"),
                ('(list (list "x" (quote count) "zip"))', "the scope of the running total x"),
                ('(list "x")', "a running total is")):
            self.run_lisp('(define spec (make-report-spec :running %s :breaks (list (make-report-break :field "state"))))' % spec)
            self.assertLispError("(report-text loans spec)", fragment)


class TestRepeatedHeaders(ReportTestCase):

    def test_a_group_that_goes_over_a_page_has_its_header_again_saying_so(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 6 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :repeat-header #t
                                             :header "{{state}}{{#if continued}} cont{{/if}}"))))''')
        self.assertEqual(self.text(), "CA\nL2\nL3\nL4\nNY\nL1\nNY cont\nL5\n\n\n\n\n")

    def test_a_header_that_is_not_to_be_repeated_is_not(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 6 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :header "{{state}}"))))''')
        # the second page has only the row that did not fit, and five blank lines
        self.assertEqual(self.text(), "CA\nL2\nL3\nL4\nNY\nL1\nL5\n\n\n\n\n\n")

    def test_a_new_group_that_starts_a_page_has_its_own_header_only(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 5 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :repeat-header #t
                                             :header "{{state}}{{#if continued}} cont{{/if}}"))))''')
        self.assertEqual(self.text(), "CA\nL2\nL3\nL4\n\nNY\nL1\nL5\n\n\n")

    def test_a_page_that_starts_with_a_footer_does_not_repeat_the_header_of_the_group_it_ends(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :repeat-header #t :header "{{state}}{{#if continued}} cont{{/if}}"
                                             :footer "end {{state}}"))))''')
        self.assertEqual(self.text(), "CA\nL2\nL3\nL4\nend CA\nNY\nL1\nL5\nend NY\n\n\n\n")

    def test_a_page_that_starts_with_the_footer_of_an_inner_group_repeats_the_header_of_the_outer_one(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 3 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :repeat-header #t :header "{{state}}{{#if continued}} cont{{/if}}")
                          (make-report-break :field "zip" :footer "z{{zip}}"))))''')
        # Page 2 starts with the footer of CA's first zip, and CA goes on after it: so CA's header is there again. Page 3
        # starts with the footer of the last zip of CA, and nothing of CA goes on after it. Page 4 starts with a row of NY.
        self.assertEqual(self.text(), "CA\nL2\nL4\nCA cont\nz90001\nL3\nz90002\nNY\nL1\nNY cont\nL5\nz10001\n")

    def test_a_group_that_starts_a_page_inside_another_repeats_the_outer_header_only(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 8 :detail "{{loan-id}}"
            :breaks (list (make-report-break :field "state" :repeat-header #t :header "{{state}}{{#if continued}} cont{{/if}}")
                          (make-report-break :field "zip" :new-page #t :header "z{{zip}}"))))''')
        self.assertEqual(self.text(), "CA\nz90001\nL2\nL4\n" + "\n" * 4 + "CA cont\nz90002\nL3\n" + "\n" * 5 + "NY\nz10001\nL1\nL5\n" + "\n" * 4)

    def test_continued_is_a_name_of_a_header_only(self):
        self.run_lisp('(define spec (make-report-spec :breaks (list (make-report-break :field "state" :footer "{{continued}}"))))')
        self.assertLispError("(report-text loans spec)", "footer of the break on state uses {{continued}}")


class TestTheWebPage(ReportTestCase):

    PAGES = re.compile(r"<section class='page' id='p(\d+)'><pre>(.*?)</pre></section>", re.S)

    def page(self, spec="spec", table="loans", title=None):
        """The web page of the report, as text, and the number of pages that write-report-html gives back."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.html")
            extra = "" if title is None else ' :title "%s"' % title
            pages = self.run_lisp('(write-report-html %s "%s" %s%s)' % (table, path, spec, extra))
            return open(path, encoding="utf-8").read(), pages

    def test_each_page_of_the_report_is_a_section_of_the_page_in_order(self):
        self.run_lisp(TestPages.PAGED)
        html, pages = self.page()
        self.assertEqual(pages, 2)
        found = self.PAGES.findall(html)
        self.assertEqual([number for number, _ in found], ["1", "2"])
        # the pages are those of the text report, line for line
        self.assertEqual("\n".join(text for _, text in found) + "\n", self.text())

    def test_the_page_has_the_bar_to_go_through_the_pages_and_a_script_for_it(self):
        self.run_lisp(TestPages.PAGED)
        html, _ = self.page()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertTrue(html.rstrip().endswith("</html>"))
        for name in ("first", "previous", "next", "last", "number", "total"):
            self.assertIn("id='%s'" % name, html)
        self.assertIn("<script>", html)
        self.assertIn("ArrowRight", html)                      # the keys work
        self.assertLess(html.index("<main>"), html.index("<nav>"))
        self.assertLess(html.index("id='p2'"), html.index("<nav>"))      # the bar is at the bottom, after the pages
        self.assertIn("position: fixed", html)
        self.assertIn("@media print", html)                  # printed, every page, one after another
        self.assertIn(".js .page { display: none; }", html)    # (without the script, every page shows)

    def test_the_title_and_the_text_are_made_safe_for_the_web(self):
        self.run_lisp('''(define odd (make-table "name" (vector "A<B & C" "x>y")))
          (define spec (make-report-spec :detail "{{name}}"))''')
        html, _ = self.page("spec", "odd", title="Loans & <more>")
        self.assertIn("<title>Loans &amp; &lt;more&gt;</title>", html)
        self.assertIn("A&lt;B &amp; C\nx&gt;y", html)
        self.assertNotIn("A<B", html)

    def test_a_report_with_no_page_length_is_in_pages_of_fifty_lines_and_the_spec_is_not_changed(self):
        self.run_lisp('''(define long (make-table "n" (list->vector (iota 120))))
          (define spec (make-report-spec :detail "{{n:.0f}}"))''')
        html, pages = self.page("spec", "long")
        found = self.PAGES.findall(html)
        self.assertEqual(pages, 3)
        self.assertEqual([len(text.split("\n")) for _, text in found], [50, 50, 50])
        self.assertTrue(found[0][1].startswith("0\n1\n2\n"))
        self.assertTrue(found[2][1].endswith("119" + "\n" * 30))           # 20 rows and thirty blank lines
        self.assertShows("(report-spec-page-lines spec)", "#f")

    def test_the_page_separator_is_not_written(self):
        self.run_lisp(TestPages.PAGED.replace(":page-lines 12", ':page-lines 12 :page-separator "\\f"'))
        html, _ = self.page()
        self.assertNotIn("\f", html)

    def test_page_x_of_y_and_running_totals_are_in_the_web_page_too(self):
        self.run_lisp('''(define spec (make-report-spec :page-lines 4 :page-header "{{page}}/{{pages}}" :detail "{{loan-id}} {{so-far:.0f}}"
            :running (list (list "so-far" 'sum "balance"))))''')
        html, _ = self.page()
        self.assertEqual([text for _, text in self.PAGES.findall(html)], ["1/2\nL1 100\nL2 300\nL3 600", "2/2\nL4 1000\nL5 1500\n"])

    def test_the_arguments_are_checked_before_the_file_is_written(self):
        self.assertLispError('(write-report-html 5 "/nonexistent/x.html" (make-report-spec))', "must be a table")
        self.run_lisp('(define spec (make-report-spec :detail "{{typo}}"))')
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.html")
            self.assertLispError('(write-report-html loans "%s" spec)' % path, "the detail uses {{typo}}")

    def test_a_long_report_is_written_in_pieces(self):
        self.run_lisp('''(define big (make-table "x" (make-vector 3000 1.0)))
          (define spec (make-report-spec :detail "{{x:.0f}}" :page-lines 100))''')
        written = []
        self.env[lisp_core.Symbol("write-text-file")] = lambda path, text, append=False: written.append(str(text))
        self.run_lisp('(write-report-html big "nowhere" spec)')
        self.assertGreater(len(written), 3)
        self.assertEqual(len(self.PAGES.findall("".join(written))), 30)


class TestMarkdown(ReportTestCase):
    """:markdown #t writes each run of rows as a Markdown table, laid out as display-table lays out a table."""

    BY_STATE_AND_ZIP = '''
(define spec
  (make-report-spec
    :markdown #t
    :formats '(("state" hide) ("zip" hide) ("balance" ",.2f") ("rate" ".1f"))
    :summaries (list (list "loans" 'count) (list "total" 'sum "balance"))
    :breaks (list (make-report-break :field "state" :header "## {{state}}"
                                     :footer "{{state}}: {{loans}} loans, total {{total:,.2f}}\\n")
                  (make-report-break :field "zip" :header "zip {{zip}}"))
    :report-footer "All: {{loans}} loans, total {{total:,.2f}}"))
'''

    def test_each_group_of_rows_is_a_table_between_the_headers_and_footers(self):
        self.run_lisp(self.BY_STATE_AND_ZIP)
        self.assertEqual(self.text(), """## CA
zip 90001

| loan-id | balance | rate |
|:---|---:|---:|
| L2 | 200.00 | 6.0 |
| L4 | 400.00 | 8.0 |

zip 90002

| loan-id | balance | rate |
|:---|---:|---:|
| L3 | 300.00 | 7.0 |

CA: 3 loans, total 900.00

## NY
zip 10001

| loan-id | balance | rate |
|:---|---:|---:|
| L1 | 100.00 | 5.0 |
| L5 | 500.00 | 9.0 |

NY: 2 loans, total 600.00

All: 5 loans, total 1,500.00
""")

    def test_a_table_with_no_breaks_is_one_table_of_the_rows_in_order_with_nothing_before_it(self):
        self.run_lisp('''(define spec (make-report-spec :markdown #t
            :formats '(("state" hide) ("zip" hide) ("rate" hide) ("balance" ",.2f"))))''')
        self.assertEqual(self.text(), """| loan-id | balance |
|:---|---:|
| L1 | 100.00 |
| L2 | 200.00 |
| L3 | 300.00 |
| L4 | 400.00 |
| L5 | 500.00 |
""")

    def test_groups_with_nothing_written_between_them_are_one_table(self):
        self.run_lisp('''(define spec (make-report-spec :markdown #t
            :formats '(("zip" hide) ("rate" hide) ("balance" hide))
            :breaks (list (make-report-break :field "state"))))''')
        self.assertEqual(self.text(), """| loan-id | state |
|:---|:---|
| L2 | CA |
| L3 | CA |
| L4 | CA |
| L1 | NY |
| L5 | NY |
""")

    def test_it_is_the_table_that_display_table_shows(self):
        formats = '\'(("balance" ",.2f") ("rate" ".3%") ("zip" hide))'
        shown = []
        display = lisp_builtins.make_display_table_builtin(io.StringIO(), shown.append)["display-table"]
        display(self.run_lisp("loans"), self.run_lisp(formats))
        self.run_lisp("(define spec (make-report-spec :markdown #t :formats %s))" % formats)
        self.assertEqual(self.text(), lisp_builtins.markdown_table(shown[0]) + "\n")

    def test_what_markdown_would_read_as_something_else_is_escaped_in_the_cells(self):
        self.run_lisp('''(define odd (make-table "name" (vector "a|b *c*" "$5 and $6")))
          (define spec (make-report-spec :markdown #t))''')
        self.assertEqual(self.text("spec", "odd"), "| name |\n|:---|\n| a\\|b \\*c\\* |\n| \\$5 and \\$6 |\n")

    def test_a_missing_number_is_a_blank_cell(self):
        self.run_lisp('''(define gaps (make-table "x" (vector 1.0 nan)))
          (define spec (make-report-spec :markdown #t :formats '(("x" ".1f"))))''')
        self.assertEqual(self.text("spec", "gaps"), "| x |\n|---:|\n| 1.0 |\n|  |\n")

    def test_a_group_that_starts_a_new_page_ends_its_table_before_the_page_separator(self):
        self.run_lisp(''' (define spec (make-report-spec :markdown #t :page-separator "---"
            :formats '(("client" hide) ("amount" ".2f"))
            :detail-order '("date")
            :breaks (list (make-report-break :field "client" :new-page #t :header "Dear {{client}}"))))''')
        self.assertEqual(self.text("spec", "transactions"), """Dear Amy

| date | what | amount |
|:---|:---|---:|
| 2026-03-01 | gas | 40.00 |
| 2026-03-02 | coffee | 4.50 |
| 2026-03-09 | food | 20.00 |

---
Dear Zed

| date | what | amount |
|:---|:---|---:|
| 2026-03-01 | books | 30.00 |
| 2026-03-05 | rent | 100.00 |
| 2026-03-20 | gift | 5.25 |
---
""")

    def test_write_report_writes_it_to_a_file(self):
        self.run_lisp(self.BY_STATE_AND_ZIP)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.md")
            self.assertEqual(self.run_lisp('(write-report loans "%s" spec)' % path), 1)
            self.assertEqual(open(path, encoding="utf-8").read(), self.text())

    def test_a_markdown_report_has_rows_of_a_table_not_a_template_and_no_pages(self):
        self.assertLispError('(report-text loans (make-report-spec :markdown #t :detail "{{loan-id}}"))', "no :detail template")
        for slot in (":page-lines 20", ':page-header "x"', ':page-footer "x"'):
            self.assertLispError("(report-text loans (make-report-spec :markdown #t %s))" % slot, "has no pages")

    def test_formats_are_for_a_markdown_report(self):
        self.assertLispError('(report-text loans (make-report-spec :detail "{{loan-id}}" :formats \'(("zip" hide))))', "which this is not")

    def test_a_mistake_in_the_formats_is_found_before_the_file_is_written(self):
        self.run_lisp('''(define spec (make-report-spec :markdown #t :formats '(("balance" "nonsense"))))
          (define hidden (make-report-spec :markdown #t :formats '(("loan-id") ("state") ("zip") ("balance") ("rate"))))''')
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.md")
            self.assertLispError('(write-report loans "%s" spec)' % path, "balance")
            self.assertLispError('(write-report loans "%s" hidden)' % path, "every column is hidden")
            self.assertFalse(os.path.exists(path))

    def test_it_is_not_for_the_web_page(self):
        self.run_lisp("(define spec (make-report-spec :markdown #t))")
        self.assertLispError('(write-report-html loans "/nonexistent/x.html" spec)', "write-report")

    def test_table_markdown_is_a_string_of_the_tables_lines(self):
        self.assertShows('(table-markdown (make-table "a" #(1 2) "b" (vector "x" "y")))',
                         '"| a | b |\n|---:|:---|\n| 1 | x |\n| 2 | y |"')
        self.assertLispError('(table-markdown loans \'(("loan-id") ("state") ("zip") ("balance") ("rate")))', "every column is hidden")
