; ---------------------------------------------------------------------
; init.lsp
;
; Loaded automatically, into a fresh global environment, every time the
; interpreter starts -- batch mode (python3 lisp_interpreter.py script.lsp),
; the console REPL, and the GUI all load this file first, before anything
; else runs. See load_init_file() / DEFAULT_INIT_FILE in lisp_interpreter.py.
;
; Put your own always-available definitions and macros here -- they'll
; be in scope for every script and REPL session without having to
; (load ...) them by hand each time. This file is optional: if it's
; empty (or you delete it), startup behaves exactly as if it didn't
; exist.
;
; To use a different init file instead of this one, either edit this
; file in place or set the LISP_INIT_FILE environment variable to another
; path.
; ---------------------------------------------------------------------
