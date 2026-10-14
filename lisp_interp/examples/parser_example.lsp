; parser_example.lsp
;
; The parser framework in lib/parser.lsp at work on two small languages: a
; calculator, and a settings file whose lines become a table. (The SQL
; interpreter in sql.lsp is read by it, too.)
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py parser_example.lsp

(load "parser.lsp")

; ---------------------------------------------------------------------------
; A calculator
; ---------------------------------------------------------------------------
; The grammar is a table with a row for each kind of token and each way a part of the
; language can be made. (chain term ("+" . +) ("-" . -)) is a term, and more terms each
; after a + or -, grouped from the left, as the tree (+ left right) -- which is Lisp.

(define-grammar calculator
  (token skip   "\\s+")
  (token number "\\d+(?:\\.\\d+)?"  string->number)
  (token symbol "[-+*/()]")

  (rule expression ((chain term ("+" . +) ("-" . -))))
  (rule term       ((chain factor ("*" . *) ("/" . /))))
  (rule factor     ("-" factor) (node-builder '-))
  (rule factor     (number))
  (rule factor     ("(" expression ")"))
  (describe factor "a number, - or ("))

(define (calculate text)
  (let ((tree (grammar-parse calculator text)))
    (display (format "  {}  =>  {}  =>  {}\n" text tree (eval tree)))))

(display "The tree for each text, and its value:\n")
(calculate "2 + 3 * 4")
(calculate "(2 + 3) * 4")
(calculate "100 - 30 - 20")
(calculate "-2 * (7 - 10) / 4")

(display "\nWhat the tokens are:\n")
(display (format "  {}\n" (grammar-tokens calculator "2 * (3 + 4)")))

(display "\nWhat is wrong with a text that isn't one:\n")
(dolist (text '("2 +" "2 3" "(2 + 3" "2 $ 3" "* 2"))
  (display (format "  {}  =>  {}\n" text (catch-error (grammar-parse calculator text) (message) message))))

; ---------------------------------------------------------------------------
; A settings file
; ---------------------------------------------------------------------------
; Lines of  name = value  in sections  [like this], with # comments. The grammar makes a
; list of the lines, and an ordinary function turns them into the rows of a table.

(define (without-quotes text)
  (substring text 1 (- (string-length text) 1)))

(define-grammar settings
  (token skip    "[ \\t\\r]+|#[^\\n]*")
  (token newline "\\n")
  (token number  "-?\\d+(?:\\.\\d+)?" string->number)
  (token string  "\"[^\"]*\"" without-quotes)
  (token name    "[A-Za-z_][A-Za-z_0-9.]*")
  (token symbol  "[=\\[\\]]")
  (describe name "a name")
  (describe value "a number, a name, or text in quotes")

  (option end-name "the end of the file")

  (rule file ((star line)))
  (rule line ("[" name "]" (drop (or newline end))) (node-builder 'section))
  (rule line (name "=" value (drop (or newline end))) (node-builder 'setting))
  (rule line ((drop newline)) (lambda () '(blank)))              ; an empty line
  (rule value (number))
  (rule value (string))
  (rule value (name)))

(define (settings-table text)
  "The settings in the text, as a table with a row for each: its section, name, and value."
  (let ((section "")
        (rows '()))
    (dolist (line (grammar-parse settings text))
      (case (car line)
        ((section) (set! section (cadr line)))
        ((setting) (set! rows (append rows (list (list section (cadr line) (caddr line))))))))
    (table-from-rows rows (list "section" "name" "value"))))

(define file-text "# the paths to the data
[data]
folder = \"/Users/ada/pools\"
months = 36
discount = 0.045

[model]
name = ols
folds = 5   # for the cross-validation
")

(display "\nThe settings file, as a table (the numbers are numbers, the rest text):\n\n")
(define table (settings-table file-text))
(display-table table)

(display "\nOne of its settings: ")
(display (table-column (table-where table "name" "folds") "value"))
(newline)

(display "\nAnd a mistake in a settings file:\n")
(display (format "  {}\n" (catch-error (settings-table "[data]\nmonths = \nfolds = 5\n") (message) message)))
