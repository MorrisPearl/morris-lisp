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
        self.assertEqual(shown, ['<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(self.notebook), html.escape(self.notebook))])
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
        self.assertEqual(shown, ['<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(notebook), html.escape(notebook))])
        with open(notebook) as f:
            self.assertEqual(["".join(c["source"]) for c in json.load(f)["cells"]],
                             ["(define first-cell 1)", "(define second-cell (* 2 first-cell))"])


if __name__ == "__main__":
    unittest.main()
