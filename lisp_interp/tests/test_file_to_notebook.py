"""file-to-notebook (lisp_builtins.py): a Lisp file's top-level forms, each in its own code cell of a new Jupyter notebook, none run;
the link to the notebook shown in a notebook. The splitter is checked directly; the notebook's shape, the builtin in the console and in
a notebook; and, through a real kernel, the link a notebook shows."""

import html
import json
import tempfile
import urllib.parse

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase

SAMPLE = r''';; the header comment
(define (f x) ; a comment with ) paren
  "a string with ( paren and \" quote"
  (* x 2))

'quoted-thing
; a note about g
(define g 3)   ; trailing
(list 1 (2 3))
#(1 2)
"just a string"
atom-here
'(a b)
'''

SAMPLE_TEXTS = [
    ';; the header comment\n(define (f x) ; a comment with ) paren\n  "a string with ( paren and \\" quote"\n  (* x 2))',
    "'quoted-thing",
    "; a note about g\n(define g 3)   ; trailing",
    "(list 1 (2 3))",
    "#(1 2)",
    '"just a string"',
    "atom-here",
    "'(a b)",
]


class TestTheSplitter(unittest.TestCase):

    def test_each_top_level_form_is_its_own_text_with_its_comments_and_layout(self):
        self.assertEqual(lisp_builtins.top_level_form_texts(SAMPLE), SAMPLE_TEXTS)

    def test_the_texts_read_back_as_the_same_forms(self):
        for text in lisp_builtins.top_level_form_texts(SAMPLE):
            self.assertEqual(len(list(lisp_core.parse(text))), 1, text)

    def test_a_string_in_vertical_bars_may_hold_parentheses_semicolons_and_quotation_marks(self):
        source = '(define s |has ) a paren and ; a semicolon and "quotes"|)\n(define t 2)\n|just a bar string|\n'
        self.assertEqual(lisp_builtins.top_level_form_texts(source),
                         ['(define s |has ) a paren and ; a semicolon and "quotes"|)', "(define t 2)", "|just a bar string|"])
        self.assertEqual(lisp_builtins.top_level_form_texts(r"(f |a \| bar|) (g)"), [r"(f |a \| bar|)", "(g)"])

    def test_a_file_with_no_forms_has_no_texts(self):
        self.assertEqual(lisp_builtins.top_level_form_texts("; only a comment\n\n"), [])

    def test_a_syntax_error_is_raised_before_anything_is_split_off(self):
        with self.assertRaises(lisp_core.LispError):
            lisp_builtins.top_level_form_texts("(define ok 1) (define broken 2")


class TestTheNotebook(unittest.TestCase):

    def test_it_is_a_notebook_with_one_code_cell_for_each_text_for_the_morris_lisp_kernel(self):
        notebook = lisp_builtins.notebook_json(["(define a 1)", "; two\n(define b 2)"])
        self.assertEqual((notebook["nbformat"], notebook["nbformat_minor"]), (4, 4))
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "morris-lisp")
        self.assertEqual([c["cell_type"] for c in notebook["cells"]], ["code", "code"])
        self.assertEqual(["".join(c["source"]) for c in notebook["cells"]], ["(define a 1)", "; two\n(define b 2)"])
        self.assertTrue(all(c["outputs"] == [] and c["execution_count"] is None for c in notebook["cells"]))


class TestFileToNotebook(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "sample.lsp")
        with open(self.path, "w") as f:
            f.write(SAMPLE)
        self.notebook = os.path.join(self.folder, "sample-notebook.ipynb")

    def written(self, notebook=None):
        with open(notebook or self.notebook) as f:
            return json.load(f)

    def test_the_forms_go_in_cells_and_nothing_is_run(self):
        self.assertShows('(file-to-notebook "%s" "%s")' % (self.path, self.notebook), '"%s"' % self.notebook)
        self.assertEqual(["".join(c["source"]) for c in self.written()["cells"]], SAMPLE_TEXTS)
        self.assertEqual(self.printed(), "Wrote %s, with 8 cells (open it in Jupyter)\n" % self.notebook)
        self.assertIsNone(self.env.lookup_or_none(lisp_core.Symbol("f")))

    def test_the_notebook_is_named_after_the_file_when_no_name_is_given(self):
        cwd = os.getcwd()
        os.chdir(self.folder)
        self.addCleanup(os.chdir, cwd)
        self.run_lisp('(file-to-notebook "%s")' % self.path)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "sample.ipynb")))

    def test_a_notebook_that_is_there_already_is_not_written_over(self):
        with open(self.notebook, "w") as f:
            f.write("mine")
        self.assertLispError('(file-to-notebook "%s" "%s")' % (self.path, self.notebook), "is there already")
        with open(self.notebook) as f:
            self.assertEqual(f.read(), "mine")

    def test_a_notebook_shows_a_link_that_opens_the_new_notebook_in_a_new_tab(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, html=shown.append)
        self.run_lisp('(file-to-notebook "%s" "%s")' % (self.path, self.notebook), env)
        self.assertEqual(shown, ['<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(os.path.relpath(self.notebook)), html.escape(self.notebook))])
        self.assertEqual(self.printed(), "")

    def test_a_path_is_found_on_the_load_path_too(self):
        with mock.patch.dict(os.environ, {"LISP_PATH": self.folder}):
            self.run_lisp('(file-to-notebook "sample.lsp" "%s")' % self.notebook)
        self.assertEqual(len(self.written()["cells"]), 8)

    def test_without_a_path_a_file_dialog_asks_and_a_cancel_writes_nothing(self):
        cwd = os.getcwd()
        os.chdir(self.folder)
        self.addCleanup(os.chdir, cwd)
        with mock.patch.object(lisp_builtins, "choose_lisp_file", return_value=self.path):
            self.run_lisp("(file-to-notebook)")
        self.assertEqual(len(self.written(os.path.join(self.folder, "sample.ipynb"))["cells"]), 8)
        with mock.patch.object(lisp_builtins, "choose_lisp_file", return_value=None):
            self.assertShows("(file-to-notebook)", "()")

    def test_a_dialog_that_cannot_be_shown_says_to_give_the_path(self):
        with mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertLispError("(file-to-notebook)", "there is no file dialog here")

    def test_what_is_wrong_is_said(self):
        self.assertLispError("(file-to-notebook 5)", "expected the file's path as a string")
        self.assertLispError('(file-to-notebook "no-such-file.lsp" "%s")' % self.notebook, "no-such-file.lsp")


def cell(kind, text, **more):
    return dict({"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}, **more)


class TestSlideTypes(unittest.TestCase):

    CELLS = [cell("code", "(define a 1)"), cell("markdown", "# Part one"), cell("code", "a"), cell("markdown", "## A detail"),
             cell("markdown", "just words"), cell("markdown", "  # Part two")]

    def test_every_cell_is_a_slide_of_its_own_by_default(self):
        self.assertEqual(lisp_builtins.slide_types_for(self.CELLS, "each-cell"), ["slide"] * 6)

    def test_a_heading_starts_a_slide_or_a_sub_slide_and_the_other_cells_stay_on_it(self):
        self.assertEqual(lisp_builtins.slide_types_for(self.CELLS, "by-heading"),
                         ["slide", "slide", "-", "subslide", "-", "slide"])      # (the first cell always starts a slide)

    def test_a_code_cell_that_looks_like_a_heading_is_not_one(self):
        cells = [cell("markdown", "# Title"), cell("code", "# a comment, not a heading\n(f)")]
        self.assertEqual(lisp_builtins.slide_types_for(cells, "by-heading"), ["slide", "-"])

    def test_no_cells_have_no_types(self):
        self.assertEqual(lisp_builtins.slide_types_for([], "by-heading"), [])


class TestSetSlideTypes(LispTestCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.notebook = os.path.join(self.folder, "talk.ipynb")
        self.document = {"cells": [cell("markdown", "# Title"), cell("code", "(+ 1 2)", execution_count=3,
                                                                       outputs=[{"output_type": "stream", "name": "stdout", "text": ["3\n"]}]),
                                   cell("markdown", "## Detail")],
                         "metadata": {"kernelspec": {"name": "morris-lisp"}}, "nbformat": 4, "nbformat_minor": 4}
        with open(self.notebook, "w") as f:
            json.dump(self.document, f)

    def types(self, path):
        with open(path) as f:
            return [c["metadata"]["slideshow"]["slide_type"] for c in json.load(f)["cells"]]

    def test_the_notebook_itself_is_changed_unless_a_copy_is_asked_for(self):
        self.assertShows('(set-slide-types "%s")' % self.notebook, '"%s"' % self.notebook)
        self.assertEqual(self.types(self.notebook), ["slide", "slide", "slide"])
        self.assertIn("Set the slide types of the 3 cells of %s. If it is open in JupyterLab, reload it" % self.notebook, self.printed())
        self.assertEqual(sorted(os.listdir(self.folder)), ["talk.ipynb"])             # (no copy, and nothing left over from writing)

    def test_by_heading_and_a_name_for_a_copy(self):
        copy = os.path.join(self.folder, "mine.ipynb")
        self.assertShows("(set-slide-types \"%s\" 'by-heading \"%s\")" % (self.notebook, copy), '"%s"' % copy)
        self.assertEqual(self.types(copy), ["slide", "-", "subslide"])
        self.assertIn("Wrote %s, with the slide types set on 3 cells (open it in Jupyter)" % copy, self.printed())
        with open(self.notebook) as f:
            self.assertEqual(json.load(f), self.document)                              # (the notebook is as it was)

    def test_everything_else_in_the_notebook_is_kept(self):
        self.run_lisp("(set-slide-types \"%s\" 'by-heading)" % self.notebook)
        self.assertEqual(self.types(self.notebook), ["slide", "-", "subslide"])
        with open(self.notebook) as f:
            written = json.load(f)
        for c in written["cells"]:
            del c["metadata"]["slideshow"]
        self.assertEqual(written, self.document)                          # (outputs, execution counts, kernel: all as they were)

    def test_it_is_written_as_jupyter_writes_a_notebook(self):
        self.run_lisp('(set-slide-types "%s")' % self.notebook)
        with open(self.notebook, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, indent=1, ensure_ascii=False) + "\n")

    def test_a_notebook_shows_a_link_to_the_copy(self):
        shown = []
        env = lisp_builtins.make_global_env(output=self.out.append, html=shown.append)
        copy = os.path.join(self.folder, "talk-slides.ipynb")
        self.run_lisp('(set-slide-types "%s" (quote each-cell) "%s")' % (self.notebook, copy), env)
        self.assertEqual(shown, ['<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(os.path.relpath(copy)), html.escape(copy))])

    def test_a_copy_that_is_there_already_is_not_written_over(self):
        copy = os.path.join(self.folder, "talk-slides.ipynb")
        with open(copy, "w") as f:
            f.write("mine")
        self.assertLispError('(set-slide-types "%s" (quote each-cell) "%s")' % (self.notebook, copy), "is there already")
        with open(copy) as f:
            self.assertEqual(f.read(), "mine")

    def test_what_is_wrong_is_said(self):
        self.assertLispError("(set-slide-types 5)", "expected the notebook's path as a string")
        self.assertLispError('(set-slide-types "%s" (quote everywhere))' % self.notebook, "the style is each-cell or by-heading, not everywhere")
        self.assertLispError('(set-slide-types "no-such-notebook.ipynb")', "no-such-notebook.ipynb")
        plain = os.path.join(self.folder, "plain.ipynb")
        with open(plain, "w") as f:
            f.write("not json")
        self.assertLispError('(set-slide-types "%s")' % plain, "is not a notebook")
        with open(plain, "w") as f:
            f.write('{"metadata": {}}')
        self.assertLispError('(set-slide-types "%s")' % plain, "it has no cells")


class TestNotebookToSlides(LispTestCase):
    """notebook-to-slides, against a small stand-in for the files that tools/get_slide_files.py downloads."""

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.support = os.path.join(self.folder, "support")
        for path, text in (("reveal.js/dist/reveal.js", "// reveal"), ("reveal.js/plugin/notes/notes.js", "// notes"),
                           ("reveal.js/dist/theme/white.css", "/* local fonts */"), ("reveal.js/dist/theme/black.css", "/* local fonts */"),
                           ("reveal.js/dist/theme/simple.css", "@import url(https://fonts.googleapis.com/css?family=Lato);"),
                           ("require.min.js", "// require"), ("jquery.min.js", "// jquery")):
            os.makedirs(os.path.dirname(os.path.join(self.support, path)), exist_ok=True)
            with open(os.path.join(self.support, path), "w") as f:
                f.write(text)
        patcher = mock.patch.object(lisp_builtins, "SLIDES_SUPPORT", self.support)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.notebook = os.path.join(self.folder, "talk.ipynb")
        document = {"cells": [cell("markdown", "# Title"), cell("code", "(+ 1 2)", execution_count=1, outputs=[]), cell("markdown", "## Detail")],
                    "metadata": {"kernelspec": {"name": "morris-lisp", "display_name": "morris_lisp", "language": "scheme"}},
                    "nbformat": 4, "nbformat_minor": 4}
        for c, slide_type in zip(document["cells"], ("slide", "slide", "subslide")):
            c["metadata"]["slideshow"] = {"slide_type": slide_type}
        with open(self.notebook, "w") as f:
            json.dump(document, f)
        self.page = os.path.join(self.folder, "talk.slides.html")

    def read_page(self, path=None):
        with open(path or self.page, encoding="utf-8") as f:
            return f.read()

    def test_a_page_and_the_folder_of_files_it_needs_are_written(self):
        self.assertShows('(notebook-to-slides "%s")' % self.notebook, '"%s"' % self.page)
        files = os.path.join(self.folder, "talk.slides_files")
        self.assertEqual(sorted(os.listdir(files)), ["jquery.min.js", "require.min.js", "reveal.js"])
        self.assertTrue(os.path.exists(os.path.join(files, "reveal.js", "dist", "reveal.js")))
        self.assertTrue(os.path.exists(os.path.join(files, "reveal.js", "plugin", "notes", "notes.js")))
        self.assertIn("open the page in a browser; it works with no internet", self.printed())

    def test_the_page_names_only_files_beside_it(self):
        self.run_lisp('(notebook-to-slides "%s")' % self.notebook)
        page = self.read_page()
        addresses = re.findall(r'(?:src|href)="([^"]*)"', page) + re.findall(r'"(talk\.slides_files/[^"]*)"', page)
        self.assertEqual([a for a in addresses if a.startswith(("http:", "https:", "//"))], [])
        for needed in ("talk.slides_files/reveal.js/dist/reveal.js", "talk.slides_files/reveal.js/plugin/notes/notes.js",
                       "talk.slides_files/require.min.js", "talk.slides_files/jquery.min.js", "talk.slides_files/reveal.js/dist/theme/white.css"):
            self.assertIn(needed, page)
        self.assertNotIn("import mermaid from ''", page)
        self.assertNotIn("mathjax.org", page)

    def test_every_cell_is_on_a_slide_in_order(self):
        self.run_lisp('(notebook-to-slides "%s")' % self.notebook)
        text = re.sub(r"<[^>]*>", "", self.read_page())
        self.assertEqual([text.index(word) for word in ("Title", "(+ 1 2)", "Detail")], sorted(text.index(word) for word in ("Title", "(+ 1 2)", "Detail")))
        self.assertGreaterEqual(self.read_page().count("<section"), 3)          # (a sub-slide is a section inside its slide's)

    def test_what_only_a_live_notebook_can_show_is_left_out_and_the_rest_is_kept(self):
        with open(self.notebook) as f:
            document = json.load(f)
        document["cells"][1]["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": ["a plain line of output\n"]},
            {"output_type": "execute_result", "execution_count": 1, "metadata": {}, "data": {"text/plain": ["a plain result"]}},
            {"output_type": "display_data", "metadata": {}, "data": {"text/html": ["<b>a table</b>"], "text/plain": ["a table"]}},
            {"output_type": "display_data", "metadata": {}, "data": {"application/vnd.jupyter.widget-view+json": {"model_id": "abc", "version_major": 2},
                                                                      "text/plain": ["VBox(children=(DataGrid(auto_fit_params=ZZGRID"]}},
            {"output_type": "display_data", "metadata": {}, "data": {"application/javascript": ["window.x = 1"],
                                                                      "text/plain": ["<IPython.core.display.Javascript object>"]}}]
        with open(self.notebook, "w") as f:
            json.dump(document, f)
        self.run_lisp('(notebook-to-slides "%s")' % self.notebook)
        page = self.read_page()
        for kept in ("a plain line of output", "a plain result", "<b>a table</b>"):
            self.assertIn(kept, page)
        for left_out in ("ZZGRID", "Javascript object", "window.x = 1"):
            self.assertNotIn(left_out, page)
        self.assertIn("Left out 2 outputs that only a live notebook can show (widgets and scripts)", self.printed())

    def test_a_notebook_with_none_of_them_says_nothing_of_it(self):
        self.run_lisp('(notebook-to-slides "%s")' % self.notebook)
        self.assertNotIn("Left out", self.printed())

    def test_a_name_for_the_page_and_a_theme(self):
        page = os.path.join(self.folder, "dark.html")
        self.run_lisp("(notebook-to-slides \"%s\" \"%s\" 'black)" % (self.notebook, page))
        self.assertIn("dark_files/reveal.js/dist/theme/black.css", self.read_page(page))
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "dark_files")))

    def test_a_theme_that_loads_its_fonts_from_the_internet_is_not_offered(self):
        self.assertEqual(lisp_builtins.themes_without_web_fonts(), ["white", "black"])
        self.assertLispError('(notebook-to-slides "%s" "%s" (quote simple))' % (self.notebook, os.path.join(self.folder, "x.html")),
                             "the theme is white or black, not simple")
        self.assertFalse(os.path.exists(os.path.join(self.folder, "x.html")))

    def make_font(self, name="Hand Written-Regular.ttf"):
        folder = os.path.join(self.folder, "fonts", "nested")
        os.makedirs(folder)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"font bytes")
        patcher = mock.patch.object(lisp_builtins, "FONT_DIRECTORIES", [os.path.join(self.folder, "fonts")])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_font_is_used_for_the_text_and_its_file_goes_in_the_folder(self):
        self.make_font("HandWritten-Regular.ttf")
        self.run_lisp('(notebook-to-slides "%s" "%s" (quote white) "Hand Written")' % (self.notebook, self.page))
        page = self.read_page()
        self.assertIn('@font-face { font-family: "Hand Written"; src: url("talk.slides_files/HandWritten-Regular.ttf"); }', page)
        self.assertIn('.reveal .jp-RenderedHTMLCommon { font-family: "Hand Written", sans-serif; }', page)
        with open(os.path.join(self.folder, "talk.slides_files", "HandWritten-Regular.ttf"), "rb") as f:
            self.assertEqual(f.read(), b"font bytes")
        self.assertNotIn("is not installed here", self.printed())

    def test_a_font_that_is_not_installed_is_named_in_the_page_and_the_call_says_so(self):
        self.make_font("Other-Regular.ttf")
        self.run_lisp('(notebook-to-slides "%s" "%s" (quote white) "Hand Written")' % (self.notebook, self.page))
        page = self.read_page()
        self.assertIn('{ font-family: "Hand Written", sans-serif; }', page)
        self.assertNotIn("@font-face", page)
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, "talk.slides_files"))), ["jquery.min.js", "require.min.js", "reveal.js"])
        self.assertIn("The font Hand Written is not installed here", self.printed())

    def test_a_font_is_a_name_and_the_slides_have_none_unless_one_is_given(self):
        self.assertLispError('(notebook-to-slides "%s" "%s" (quote white) "Bad\\" name")' % (self.notebook, self.page), "the font is the name of an installed font")
        self.assertLispError('(notebook-to-slides "%s" "%s" (quote white) 5)' % (self.notebook, self.page), "the font is the name of an installed font")
        self.run_lisp('(notebook-to-slides "%s")' % self.notebook)
        self.assertNotIn("font-family: \"", self.read_page().split("</head>")[0].split("theme/white.css")[-1])

    def test_what_is_there_already_is_not_written_over(self):
        with open(self.page, "w") as f:
            f.write("mine")
        self.assertLispError('(notebook-to-slides "%s")' % self.notebook, "is there already")
        self.assertEqual(self.read_page(), "mine")
        os.remove(self.page)
        os.makedirs(os.path.join(self.folder, "talk.slides_files"))
        self.assertLispError('(notebook-to-slides "%s")' % self.notebook, "talk.slides_files is there already")

    def test_what_is_wrong_is_said(self):
        self.assertLispError("(notebook-to-slides 5)", "expected the notebook's path as a string")
        self.assertLispError('(notebook-to-slides "no-such.ipynb")', "no-such.ipynb")
        with mock.patch.object(lisp_builtins, "SLIDES_SUPPORT", os.path.join(self.folder, "nothing-here")):
            self.assertLispError('(notebook-to-slides "%s")' % self.notebook, "python3 tools/get_slide_files.py")


class TestTheLinkToANotebook(unittest.TestCase):

    def test_it_is_the_path_from_the_folder_the_notebook_runs_in_not_from_the_top_of_the_computer(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = os.path.realpath(folder)
            cwd = os.getcwd()
            os.chdir(folder)
            self.addCleanup(os.chdir, cwd)
            self.assertEqual(lisp_builtins.link_path(os.path.join(folder, "slides.ipynb")), "slides.ipynb")      # (given in full: the 404 of a link with /Users/...)
            self.assertEqual(lisp_builtins.link_path("slides.ipynb"), "slides.ipynb")
            self.assertEqual(lisp_builtins.link_path(os.path.join(folder, "sub", "a b.ipynb")), "sub/a b.ipynb")
            self.assertEqual(lisp_builtins.link_path(os.path.join(os.path.dirname(folder), "other.ipynb")), "../other.ipynb")


class TestFileToNotebookInARealKernel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from test_debugging import start_test_kernel
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, "two.lsp")
        with open(cls.path, "w") as f:
            f.write("(define first-cell 1)\n(define second-cell (* 2 first-cell))\n")
        cls.frontend = start_test_kernel(cls.tmp, "lisp-file-to-notebook-test")

    @classmethod
    def tearDownClass(cls):
        cls.frontend.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_kernel_writes_the_notebook_and_shows_the_link(self):
        notebook = os.path.join(self.tmp, "two.ipynb")
        cell = self.frontend.kc.execute('(file-to-notebook "%s" "%s")' % (self.path, notebook))
        shown = []
        while True:
            message = self.frontend.kc.get_iopub_msg(timeout=30)
            if message["parent_header"].get("msg_id") != cell:
                continue
            if message["msg_type"] == "display_data":
                shown.append(message["content"]["data"]["text/html"])
            if message["msg_type"] == "status" and message["content"]["execution_state"] == "idle":
                break
        self.assertEqual(shown, ['<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(os.path.relpath(notebook)), html.escape(notebook))])
        with open(notebook) as f:
            self.assertEqual(["".join(c["source"]) for c in json.load(f)["cells"]],
                             ["(define first-cell 1)", "(define second-cell (* 2 first-cell))"])


if __name__ == "__main__":
    unittest.main()
