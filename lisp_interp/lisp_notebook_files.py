"""Notebooks as files: file-to-notebook (a Lisp file's top-level forms, each in a code cell of a new notebook),
set-slide-types (the slide type of each cell of a notebook, for a slideshow), and notebook-to-slides (a slideshow
of a notebook, as a reveal.js page that works with no internet connection). make_global_env (lisp_builtins.py)
adds them to every environment, with make_notebook_file_builtins."""

import json
import os
import re
import shutil
import urllib.parse
from html import escape as html_escape

from lisp_core import LispError, LispString, NIL, Tokens, _brief, read_from


def top_level_form_texts(text):
    """The source text of each top-level form of a Lisp file, as a list of strings, in order: each form exactly as the file has it
    (its comments and layout included, so nothing is pretty-printed away). A comment above a form goes with it, and one at the end
    of a form's line goes with that form; a comment on a line of its own after the last form is left out. The forms are found by
    the interpreter's own reader, so a syntax error is raised, and nothing is returned, as when the file is loaded."""
    tokens = Tokens(text)
    texts = []
    previous_end = 0                              # where the text after the form before begins
    while tokens.more():
        first = tokens.position
        read_from(tokens)
        start = tokens.start_of(first)            # where the form's first token begins, and its last one ends
        end = tokens.end_of(tokens.position - 1)
        line_end = text.find("\n", end)
        line_end = len(text) if line_end == -1 else line_end
        if text[end:line_end].lstrip().startswith(";"):          # a comment at the end of the form's line is the form's own
            end = line_end
        comment = text.find(";", previous_end, start)            # a comment between the forms goes with this one
        texts.append(text[comment if comment != -1 else start:end].strip())
        previous_end = end
    return texts


# What a page can show on its own, without a running notebook.
STATIC_OUTPUT_TYPES = ("text/html", "text/markdown", "text/latex", "image/png", "image/jpeg", "image/svg+xml", "image/gif")
# What only a running notebook can show: a widget (its saved form is a line of text that describes it) and a script.
LIVE_OUTPUT_TYPES = ("application/vnd.jupyter.widget-view+json", "application/javascript")


def only_a_live_notebook_can_show(output):
    """Whether an output of a notebook's cell (a dictionary) is a widget or a script with nothing besides its description in words that a
    page could show: on a slide it would be a line such as <IPython.core.display.Javascript object>."""
    data = output.get("data", {})
    return (output.get("output_type") in ("display_data", "execute_result")
            and any(kind in data for kind in LIVE_OUTPUT_TYPES) and not any(kind in data for kind in STATIC_OUTPUT_TYPES))


def without_live_outputs(notebook):
    """Takes the outputs that only a live notebook can show out of the cells of the notebook (a notebook node), and says how many."""
    left_out = 0
    for cell in notebook.cells:
        if cell.cell_type == "code":
            kept = [output for output in cell.outputs if not only_a_live_notebook_can_show(output)]
            left_out += len(cell.outputs) - len(kept)
            cell.outputs = kept
    return left_out


def write_notebook(path, document):
    """Writes the notebook (a dictionary) in the form Jupyter writes it in, through a file beside it that then takes its place, so that
    a notebook is never left half written."""
    temporary = path + ".writing"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(document, f, sort_keys=True, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(temporary, path)


def link_path(name):
    """Where a link in a notebook's output finds the file called name: its path from the folder that the notebook runs in (which is the
    notebook's own folder in JupyterLab), with / between the folders. A path from the top of the computer, /Users/..., would be a place
    on the web server, which has no such file: JupyterLab opens a notebook by its path from the folder it was started in."""
    return os.path.relpath(os.path.abspath(name), os.getcwd()).replace(os.sep, "/")


def notebook_json(texts):
    """A Jupyter notebook (format 4.4) with a code cell for each text, none run, for the morris_lisp kernel (install_lisp_kernel.py)."""
    def cell(text):
        lines = text.splitlines(keepends=True)
        return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": lines}
    return {
        "cells": [cell(text) for text in texts],
        "metadata": {"kernelspec": {"name": "morris-lisp", "display_name": "morris_lisp", "language": "scheme"},
                     "language_info": {"name": "scheme", "file_extension": ".lsp", "mimetype": "text/x-scheme"}},
        "nbformat": 4,
        "nbformat_minor": 4,
    }


SLIDE_STYLES = ("each-cell", "by-heading")

# Where tools/get_slide_files.py puts the files that a slideshow needs to work with no internet connection: reveal.js, require.js and jQuery.
SLIDES_SUPPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slides_support")
SLIDE_SUPPORT_FILES = ("require.min.js", "jquery.min.js")


# Where find_font_file looks for the file of a font that is installed on this computer.
FONT_DIRECTORIES = ["~/Library/Fonts", "/Library/Fonts", "/System/Library/Fonts", "~/.fonts", "~/.local/share/fonts", "/usr/share/fonts"]


def find_font_file(name):
    """The path of the file of the installed font called name ("Architects Daughter", in ArchitectsDaughter-Regular.ttf), or None. Looks
    for the name with no spaces, then -Regular, as fonts are usually named, in the folders of FONT_DIRECTORIES."""
    stem = name.replace(" ", "").lower()
    wanted = {stem + "-regular.ttf", stem + "-regular.otf", stem + ".ttf", stem + ".otf"}
    for directory in FONT_DIRECTORIES:
        for folder, _, files in os.walk(os.path.expanduser(directory)):
            for file in files:
                if file.lower() in wanted:
                    return os.path.join(folder, file)
    return None


def font_style(name, folder, font_file):
    """The <style> that makes a slideshow use the font called name: its @font-face, if there is a font_file to copy into the folder of
    the page's files, and the rules that set the font of the slides' text, headings and the notebook's text cells (not of the code, which stays as it is)."""
    face = ""
    if font_file is not None:
        face = '@font-face { font-family: "%s"; src: url("%s/%s"); }\n' % (name, urllib.parse.quote(os.path.basename(folder)),
                                                                        urllib.parse.quote(os.path.basename(font_file)))
    text = ", ".join([".reveal"] + [".reveal h%d" % level for level in range(1, 7)] + [".reveal .jp-RenderedHTMLCommon"])
    return '<style>\n%s%s { font-family: "%s", sans-serif; }\n</style>\n' % (face, text, name)


def themes_without_web_fonts():
    """The names of the reveal.js themes (in the downloaded files) that do not fetch their fonts from Google, so that they show with no
    internet: white, black and serif, in reveal.js 4.0.2. Sorted, with white first."""
    folder = os.path.join(SLIDES_SUPPORT, "reveal.js", "dist", "theme")
    found = []
    for file in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if file.endswith(".css"):
            with open(os.path.join(folder, file), encoding="utf-8") as f:
                if "fonts.googleapis.com" not in f.read():
                    found.append(file[:-len(".css")])
    return sorted(found, key=lambda theme: (theme != "white", theme))

# nbconvert's slide template imports mermaid (for diagrams) from a web address; with none, its line is an import of nothing.
EMPTY_MERMAID_IMPORT = re.compile(r"<script type=\"module\">\s*import mermaid from '';.*?</script>", re.DOTALL)


def slide_types_for(cells, style):
    """The slide type of each cell of a notebook (the cells are the notebook's, as dictionaries), as a list of strings that Jupyter's
    slideshow tools know: "slide" (a new slide), "subslide" (a new slide below this one), or "-" (continues the slide before it).
      each-cell    every cell is a slide of its own.
      by-heading   a markdown cell whose first line is a heading begins a slide, if it is "# ...", or a subslide, if it is "## ..."
                   or deeper; every other cell continues the slide before it. The first cell always begins a slide."""
    if style == "each-cell":
        return ["slide"] * len(cells)
    types = []
    for cell in cells:
        text = "".join(cell.get("source", [])).lstrip()
        if cell.get("cell_type") == "markdown" and text.startswith("#"):
            types.append("slide" if not text.startswith("##") else "subslide")
        else:
            types.append("-")
    if types and types[0] == "-":
        types[0] = "slide"
    return types


def choose_lisp_file():
    """Asks for a Lisp file with a file dialog, and returns its path, or None if the dialog is cancelled. An error if the dialog
    cannot be shown (tkinter is not installed, or there is no display)."""
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        raise LispError("file-to-notebook: there is no file dialog here (tkinter is not installed): give the file's path, (file-to-notebook \"file.lsp\")")
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title="Choose a Lisp file", filetypes=[("Lisp files", "*.lsp"), ("All files", "*")])
    except tkinter.TclError as e:
        raise LispError("file-to-notebook: there is no file dialog here (%s): give the file's path, (file-to-notebook \"file.lsp\")" % e)
    finally:
        root.destroy()
    return path or None


def make_notebook_file_builtins(out, html, find_lisp_file):
    """file-to-notebook, set-slide-types, and notebook-to-slides, for one environment: out is where its display output goes,
    html shows a link to a file that one of them wrote, in a notebook (None elsewhere), and find_lisp_file finds a file
    where load would."""

    def show_link(name, what):
        """Says that the notebook called name was written, with what: in a notebook, as a link that opens it in a new tab; elsewhere, as
        a line of text."""
        if html is not None and not out.is_redirected():
            html('<a href="%s" target="_blank">Open %s</a>' % (urllib.parse.quote(link_path(name)), html_escape(name)))
        else:
            out.write("Wrote %s, %s (open it in Jupyter)\n" % (name, what))

    def file_to_notebook(path=None, notebook=None):
        """(file-to-notebook [path [notebook]]) -- writes a Jupyter notebook with each top-level form of a Lisp file in its own code
        cell, without running any of them. The path is a string (relative to the current directory, or the load path); without one,
        a file dialog asks for the file. The notebook is notebook (a string), or else the file's name with .ipynb, in the current
        directory; it is not written over a file that is there. In a notebook, a link to the new notebook is shown: a click opens it
        in a new tab. Returns the notebook's path."""
        if path is None:
            path = choose_lisp_file()
            if path is None:
                return NIL
        elif not isinstance(path, LispString):
            raise LispError("file-to-notebook: expected the file's path as a string, or no path for a file dialog, not %s" % _brief(path))
        found = find_lisp_file(str(path))
        with open(found, encoding="utf-8") as f:
            texts = top_level_form_texts(f.read())
        name = str(notebook) if notebook is not None else os.path.splitext(os.path.basename(found))[0] + ".ipynb"
        if os.path.exists(name):
            raise LispError("file-to-notebook: %s is there already: give the notebook another name, (file-to-notebook \"%s\" \"other.ipynb\")"
                            % (name, path))
        with open(name, "w", encoding="utf-8") as f:
            json.dump(notebook_json(texts), f, indent=1)
            f.write("\n")
        show_link(name, "with %d cells" % len(texts))
        return LispString(name)

    def set_slide_types(notebook, style=None, output=None):
        """(set-slide-types notebook [style [output]]) -- sets the slide type of every cell of a Jupyter notebook, for a slideshow of it (with
        jupyterlab-deck in JupyterLab, or jupyter nbconvert --to slides). notebook is the path of the notebook, a string, and it is the
        notebook that is changed: the cells, their outputs and everything else in it are kept. style is each-cell (the default: every cell
        is a slide) or by-heading (a markdown cell that begins with "# " starts a slide, "## " or deeper a sub-slide, and the cells after it
        stay on it). Given output, a string, the notebook is left as it is, and a copy with the slide types is written there instead; it is
        not written over a file that is there, and in a notebook a link to it is shown. Returns the path of the notebook that was written."""
        if not isinstance(notebook, LispString):
            raise LispError("set-slide-types: expected the notebook's path as a string, not %s" % _brief(notebook))
        style = "each-cell" if style is None else str(style)
        if style not in SLIDE_STYLES:
            raise LispError("set-slide-types: the style is each-cell or by-heading, not %s" % style)
        source = find_lisp_file(str(notebook))
        with open(source, encoding="utf-8") as f:
            try:
                document = json.load(f)
            except ValueError as e:
                raise LispError("set-slide-types: %s is not a notebook (%s)" % (notebook, e))
        if not isinstance(document, dict) or not isinstance(document.get("cells"), list):
            raise LispError("set-slide-types: %s is not a notebook: it has no cells" % notebook)
        name = str(output) if output is not None else source
        if output is not None and os.path.exists(name):
            raise LispError("set-slide-types: %s is there already: give the copy another name, (set-slide-types \"%s\" '%s \"other.ipynb\")"
                            % (name, notebook, style))
        for cell, slide_type in zip(document["cells"], slide_types_for(document["cells"], style)):
            cell.setdefault("metadata", {}).setdefault("slideshow", {})["slide_type"] = slide_type
        write_notebook(name, document)
        if output is not None:
            show_link(name, "with the slide types set on %d cells" % len(document["cells"]))
        else:
            out.write("Set the slide types of the %d cells of %s. If it is open in JupyterLab, reload it from the disk (File, Reload Notebook "
                      "from Disk): save it first if it has changes of its own, since reloading takes them out\n" % (len(document["cells"]), name))
        return LispString(name)

    def notebook_to_slides(notebook, output=None, theme=None, font=None):
        """(notebook-to-slides notebook [output [theme [font]]]) -- makes a slideshow of a Jupyter notebook (a reveal.js page), that works with no
        internet connection. notebook is the path of the notebook, a string, whose cells have slide types (see set-slide-types). The page is
        output, or else the notebook's name with .slides.html; the files it needs go in a folder beside it, with _files added to its name:
        copy both to show it somewhere else. Neither is written over what is there. theme is white (the default), black or serif: the
        themes whose fonts come with reveal.js, and so need no internet. font is the name of a font installed here, "Architects Daughter" for an
        informal look, which the slides use for their text and headings: its file is copied into the folder beside the page, so that the
        slideshow shows it on another computer too. Open the page in a browser. The notebook is not run: the outputs it
        has are what the slides show, but not a widget or a script, which only a live notebook can show: the call says how many it left out. Needs the files that tools/get_slide_files.py downloads once. Returns the page's path."""
        if not isinstance(notebook, LispString):
            raise LispError("notebook-to-slides: expected the notebook's path as a string, not %s" % _brief(notebook))
        try:
            from nbconvert import SlidesExporter
        except ImportError:
            raise LispError("notebook-to-slides: the nbconvert package is needed (pip install nbconvert)")
        if not os.path.isdir(os.path.join(SLIDES_SUPPORT, "reveal.js")):
            raise LispError("notebook-to-slides: the files that a slideshow needs to work with no internet are not here yet: download them "
                            "once, with  python3 tools/get_slide_files.py  (run it where lisp_interpreter.py is: %s)"
                            % os.path.dirname(SLIDES_SUPPORT))
        themes = themes_without_web_fonts()
        theme = "white" if theme is None else str(theme)
        if theme not in themes:
            raise LispError("notebook-to-slides: the theme is %s, not %s (the other themes of reveal.js load their fonts from the internet)"
                            % (" or ".join(themes), theme))
        if font is not None and not (isinstance(font, LispString) and re.fullmatch(r"[A-Za-z0-9 _-]+", font)):
            raise LispError("notebook-to-slides: the font is the name of an installed font, a string such as \"Architects Daughter\", not %s"
                            % _brief(font))
        source = find_lisp_file(str(notebook))
        name = str(output) if output is not None else os.path.splitext(str(notebook))[0] + ".slides.html"
        folder = os.path.splitext(name)[0] + "_files"
        for taken in (name, folder):
            if os.path.exists(taken):
                raise LispError("notebook-to-slides: %s is there already: give the slideshow another name, (notebook-to-slides \"%s\" \"other.html\")"
                                % (taken, notebook))
        place = urllib.parse.quote(os.path.basename(folder))              # (the page and its folder are side by side)
        exporter = SlidesExporter(reveal_theme=theme, reveal_url_prefix=place + "/reveal.js", require_js_url=place + "/require.min.js",
                                  jquery_url=place + "/jquery.min.js", mathjax_url="", mermaid_js_url="", mermaid_layout_elk_js_url="")
        import nbformat
        notebook_node = nbformat.read(source, as_version=4)
        left_out = without_live_outputs(notebook_node)
        page, _ = exporter.from_notebook_node(notebook_node)
        font_file = find_font_file(str(font)) if font is not None else None
        page = EMPTY_MERMAID_IMPORT.sub("", page)
        if font is not None:
            page = page.replace("</head>", font_style(str(font), folder, font_file) + "</head>", 1)
        with open(name, "w", encoding="utf-8") as f:
            f.write(page)
        shutil.copytree(os.path.join(SLIDES_SUPPORT, "reveal.js"), os.path.join(folder, "reveal.js"))
        for support_file in SLIDE_SUPPORT_FILES:
            shutil.copy(os.path.join(SLIDES_SUPPORT, support_file), folder)
        if font_file is not None:
            shutil.copy(font_file, folder)
        out.write("Wrote %s, and %s/ beside it, which it needs: open the page in a browser; it works with no internet\n"
                  % (name, os.path.basename(folder)))
        if left_out:
            out.write("Left out %d output%s that only a live notebook can show (widgets and scripts): present live, with the deck, to see %s\n"
                      % (left_out, "" if left_out == 1 else "s", "it" if left_out == 1 else "them"))
        if font is not None and font_file is None:
            out.write("The font %s is not installed here, so it is not in that folder: the slides show it only on a computer that has it\n" % font)
        return LispString(name)

    return {
        "file-to-notebook": file_to_notebook,
        "set-slide-types": set_slide_types,
        "notebook-to-slides": notebook_to_slides,
    }
