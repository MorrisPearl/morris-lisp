; parser.lsp
;
; A framework for parsing small languages -- a query language, a calculator,
; a configuration file, a data format -- with a table of rules instead of a
; function for every part of the grammar. It is no more powerful than
; recursive descent (a rule that has to guess which way to go tries one way,
; and if it fails tries the next), and the pieces of text it reads -- numbers,
; words, symbols -- are described by regular expressions.
;
; A grammar has two tables, written one row to a line:
;
;   (define-grammar calculator
;     (token skip   "\\s+")                              ; spaces: read, and thrown away
;     (token number "\\d+(?:\\.\\d+)?"  string->number)  ; the text is turned into a number
;     (token symbol "[-+*/()]")
;
;     (rule expression ((chain term ("+" . +) ("-" . -))))
;     (rule term       ((chain factor ("*" . *) ("/" . /))))
;     (rule factor     (number))
;     (rule factor     ("(" expression ")")))
;
;   (grammar-parse calculator "2 + 3 * (4 - 1)")         ; => (+ 2 (* 3 (- 4 1)))
;
; TOKENS. A token row is (token kind regular-expression [function]). The text
; is cut into tokens by trying the regular expressions in the order of the rows
; at each place, and taking the first that matches. A token's value is the
; text it matched, or what the function makes of the text. A token of kind
; skip is read and thrown away. Any character no row matches is a token of
; kind unknown, which no rule accepts, so it's an error where it's found.
; The regular expressions must not capture groups (use (?:...), not (...)),
; or start with a flag such as (?i) -- write (?i:...) around the part it's for.
;
; RULES. A rule row is (rule name (item ...) [action]). Several rows with the
; same name are alternatives, tried in the order they are written; the first
; whose items all match is the rule's. An item is:
;
;   "text"              a token whose text is that. It has no value.
;   kind                a token of that kind (a name from a token row). Its value is the token's value.
;   name                the rule of that name; its value is what that rule makes.
;   end                 only the end of the text; no value
;   (opt item ...)      the items if they match, else nothing: the value is the items' value, or '()
;   (flag item ...)     #t if the items match, else #f
;   (star item ...)     the items as many times as they match, even none: a list of their values
;   (plus item ...)     the same, but at least once
;   (sep-by sep item ...)  the items one or more times with sep between: a list of the values
;   (or item ...)       the first item that matches
;   (one-of "a" "b")    one of those texts; its value is the text as written here
;   (seq item ...)      the items in a row; used inside an or, or where a group is wanted
;   (drop item ...)     the items, with their value thrown away
;   (not item ...)      succeeds, reading nothing, if the items do NOT match
;   (chain operand (op . node) ...)   operand, and then more of it with an operator between, grouped
;                       from the left: 1 - 2 - 3 is (- (- 1 2) 3). op is a text, as above; node is
;                       a symbol, and the value is the list (node left right); or a procedure,
;                       called with left and right. Only a data table (make-grammar) can hold one.
;
; Items that are several together -- the items of a rule, or in an opt, star, flag, and so on --
; have the value of the group: the values of the items that have a value (the items with
; none, the text and end and drop and not, are left out). If there is one the value is it, if
; there are several the value is the list of them, and if there are none it's #t.
;
; A rule's action is a procedure called with the value of each item of the row that has one,
; and what it returns is the rule's value. With no action, the value is the group's.
; (node-builder 'x) makes the action that returns the list (x value ...).
;
; A grammar can't have a rule that calls itself before it has read anything (a rule that
; begins with itself: expression = expression "+" term). That's written as a loop instead,
; with chain, star, or sep-by; the error says so if it's tried.
;
; OTHER ROWS. (option name value): ignore-case (#t, for a language such as SQL where
; select and SELECT are the same: it applies to the texts in rules), start (the rule
; to begin with; the first rule is the default), error-prefix (what a message starts
; with), and end-name (what the end of the text is called in a message). (describe name text)
; says what a rule or kind of token is called in a message, "a number" for number.
;
; WHEN IT FAILS, the error says what was expected at the furthest place the text could be read to,
; and what was found there:   expected ), +, - or the end of the input but found foo (at character 12)
;
; HOW IT WORKS:
;   1. The grammar -- the rows of the table, checked and put in hash tables.
;   2. Reading the tokens -- one regular expression cuts the text up.
;   3. Matching -- a function for each kind of item. Each is given a place in the tokens, and
;      returns #f if the item doesn't match there, or (value . next-place) if it does.
;   4. Rules -- the alternatives of a rule, tried in order. What each rule finds at each place
;      is remembered, so that a rule that is tried at the same place again (as it is when an
;      alternative that has gone some way fails, and the next starts over) costs nothing: the
;      time is in proportion to the length of the text.
;   5. Parsing, and the error message.

; ---------------------------------------------------------------------------
; 1. The grammar
; ---------------------------------------------------------------------------

(defstruct parser-grammar
  tokens          ; the token rows: (kind regular-expression function-or-#f), in order
  lexer           ; the one regular expression that cuts the text up
  rules           ; hash table: rule name -> its alternatives, each (items . action-or-#f)
  descriptions    ; hash table: rule or token name -> what it is called in a message
  options)        ; hash table: option name -> value

(define peg-no-value (list 'no-value))            ; what an item with no value gives (compared with eq?)

(define peg-item-forms '(opt flag star plus sep-by or one-of seq drop not chain))

(define (peg-error . parts)
  (apply error "grammar:" parts))

(define (peg-option grammar name)
  (hash-table-ref (parser-grammar-options grammar) name))

(define (peg-groups-in regex)
  "How many groups the regular expression captures: it is tried against the empty text with an
empty alternative, which can't fail, and a group that took no part gives (), so the match is a list
of the text and one more for each group."
  (- (length (regex-search (string-append regex "|") "")) 1))

(define (peg-check-token-row row)
  (destructuring-bind (kind regex function) (cdr row)
    (unless (symbol? kind)
      (peg-error "a token's kind is a name, not" kind))
    (when (member kind '(unknown end))
      (peg-error kind "can't be the kind of a token: it's the name of something else"))
    (unless (string? regex)
      (peg-error "the regular expression of" kind "is not a string:" regex))
    (catch-error (regex-search regex "")
                 (message)
                 (peg-error "the regular expression of" kind "isn't valid:" message))
    (when (> (peg-groups-in regex) 0)
      (peg-error "the regular expression of" kind "has a group that captures; use (?:...) instead of (...)"))
    (when (regex-match regex "")
      (peg-error "the regular expression of" kind "matches no text at all, which would never end"))))

(define (peg-lexer-regex token-rows)
  "The tokens' regular expressions as one, with a group around each, and last a group for any character at all."
  (string-append (string-join (map (lambda (row) (string-append "(" (caddr row) ")")) token-rows) "|")
                 "|([\\s\\S])"))

(define (peg-sub-items item)
  "The items directly inside an item."
  (cond ((not (pair? item)) '())
        ((eq? (car item) 'one-of) '())
        ((eq? (car item) 'chain) (cons (cadr item) (map car (cddr item))))
        (else (cdr item))))

(define (peg-check-item item names rule)
  "Signals an error if an item of a rule isn't one: a text, a name of a token or rule, or a form with an item list."
  (cond ((string? item) #t)
        ((symbol? item)
         (unless (member item names)
           (peg-error "rule" rule "uses" item "which is neither a rule nor a kind of token")))
        ((and (pair? item) (member (car item) peg-item-forms))
         (when (and (eq? (car item) 'one-of) (not (every string? (cdr item))))
           (peg-error "in rule" rule "(one-of ...) is for texts, as (one-of \"+\" \"-\")"))
         (when (and (eq? (car item) 'chain) (not (every pair? (cddr item))))
           (peg-error "in rule" rule "(chain ...) takes an operand and then (text . node) pairs"))
         (dolist (inner (peg-sub-items item))
           (peg-check-item inner names rule)))
        (else
         (peg-error "in rule" rule "this isn't an item:" item))))

(define (peg-add-alternative! rules name alternative)
  (hash-table-set! rules name (append (hash-table-ref rules name '()) (list alternative))))

(define peg-option-names '(ignore-case start error-prefix end-name))

(define (make-grammar rows)
  "A grammar from the rows of its tables: lists (token kind regex [function]), (rule name (item ...)
[action]), (option name value), and (describe name text). define-grammar makes them from its clauses."
  (let ((token-rows '())
        (rules (make-hash-table))
        (descriptions (make-hash-table))
        (options (make-hash-table))
        (first-rule '()))
    (dolist (row rows)
      (case (if (pair? row) (car row) '())
        ((token)
         (destructuring-bind (kind regex &optional (function #f)) (cdr row)
           (set! token-rows (append token-rows (list (list 'token kind regex function))))))
        ((rule)
         (destructuring-bind (name items &optional (action #f)) (cdr row)
           (when (null? first-rule) (set! first-rule name))
           (peg-add-alternative! rules name (cons items action))))
        ((option)
         (destructuring-bind (name value) (cdr row)
           (unless (member name peg-option-names)
             (peg-error "unknown option" name "-- the options are" peg-option-names))
           (hash-table-set! options name value)))
        ((describe)
         (destructuring-bind (name text) (cdr row)
           (hash-table-set! descriptions name text)))
        (else (peg-error "a row of a grammar is (token ...), (rule ...), (option ...), or (describe ...), not" row))))
    (when (null? token-rows)
      (peg-error "a grammar needs at least one (token kind regular-expression) row"))
    (dolist (row token-rows)
      (peg-check-token-row row))
    (catch-error (regex-find-all (peg-lexer-regex token-rows) "")           ; are they a regular expression together?
                 (message)
                 (peg-error "the token regular expressions don't work together:" message
                            "-- a flag such as (?i) belongs inside a group: (?i:...)"))
    (let ((kinds (map cadr token-rows)))
      (unless (= (length kinds) (length (remove-duplicates kinds)))
        (peg-error "two token rows have the same kind"))
      (dolist (name (hash-table-keys rules))
        (when (member name (cons 'end kinds))
          (peg-error name "is the name of a rule, and of a kind of token or of end")))
      (let ((names (append '(end) kinds (hash-table-keys rules))))
        (dolist (name (hash-table-keys rules))
          (dolist (alternative (hash-table-ref rules name))
            (dolist (item (car alternative))
              (peg-check-item item names name))))
        (dolist (name (hash-table-keys descriptions))
          (unless (member name names)
            (peg-error "(describe" name "...) is not a rule or a kind of token")))
        (unless (hash-table-has? options 'start)
          (when (null? first-rule) (peg-error "a grammar needs at least one rule"))
          (hash-table-set! options 'start first-rule))
        (unless (hash-table-has? rules (hash-table-ref options 'start))
          (peg-error "the start rule" (hash-table-ref options 'start) "isn't a rule"))
        (unless (hash-table-has? options 'ignore-case) (hash-table-set! options 'ignore-case #f))
        (unless (hash-table-has? options 'error-prefix) (hash-table-set! options 'error-prefix "parse error:"))
        (unless (hash-table-has? options 'end-name) (hash-table-set! options 'end-name "the end of the input"))
        (make-parser-grammar :tokens (map cdr token-rows)
                             :lexer (peg-lexer-regex token-rows)
                             :rules rules
                             :descriptions descriptions
                             :options options)))))

(define (peg-clause-expression clause)
  "The expression that makes one row of the table for a clause of define-grammar: the names and items are
as written, and the regular expressions, functions, actions, and option values are worked out."
  (let ((optional (lambda (rest) (if (pair? rest) (car rest) #f))))
    (case (car clause)
      ((token) `(list 'token ',(cadr clause) ,(caddr clause) ,(optional (cdddr clause))))
      ((rule) `(list 'rule ',(cadr clause) ',(caddr clause) ,(optional (cdddr clause))))
      ((option) (if (eq? (cadr clause) 'start)
                    `(list 'option 'start ',(caddr clause))                ; the name of a rule
                    `(list 'option ',(cadr clause) ,(caddr clause))))
      ((describe) `(list 'describe ',(cadr clause) ,(caddr clause)))
      (else (peg-error "a clause of define-grammar is (token ...), (rule ...), (option ...), or (describe ...), not" clause)))))

(defmacro define-grammar (name . clauses)
  "(define-grammar name clause ...) defines name as the grammar of the rows, which are written one to a
clause: (token kind regex [function]), (rule name (item ...) [action]), (option name value), and
(describe name text). The regular expressions, functions, actions, and option values are evaluated;
the names, the items, and the start rule aren't."
  `(define ,name (make-grammar (list ,@(map peg-clause-expression clauses)))))

(define (node-builder head)
  "The action that makes a list of head and the values: (node-builder 'add) is the action for (add 1 2)."
  (lambda values (cons head values)))

; ---------------------------------------------------------------------------
; 2. Reading the tokens
; ---------------------------------------------------------------------------

(defstruct peg-token kind text value position)

(define (peg-first-text match)
  "Which group of a match took part: the place of the first that isn't empty."
  (let go ((groups match) (place 0))
    (if (string=? (car groups) "")
        (go (cdr groups) (+ place 1))
        place)))

(define (peg-read-tokens grammar text)
  "The tokens of the text, a list. All of the text is in one token or another, so a token's
position is the sum of the lengths of the ones before it."
  (let ((rows (append (parser-grammar-tokens grammar) (list (list 'unknown "" #f))))
        (tokens '())
        (position 0))
    (dolist (match (regex-find-all (parser-grammar-lexer grammar) text))
      (let* ((place (peg-first-text match))
             (row (list-ref rows place))
             (piece (list-ref match place)))
        (unless (eq? (car row) 'skip)
          (set! tokens (cons (make-peg-token :kind (car row)
                                             :text piece
                                             :value (if (caddr row) ((caddr row) piece) piece)
                                             :position position)
                             tokens)))
        (set! position (+ position (string-length piece)))))
    (reverse tokens)))

(define (grammar-tokens grammar text)
  "The tokens of the text, as a list of (kind text): to see what a grammar's token rows make of it."
  (map (lambda (token) (list (peg-token-kind token) (peg-token-text token)))
       (peg-read-tokens grammar text)))

; ---------------------------------------------------------------------------
; 3. Matching
; ---------------------------------------------------------------------------
; The place in the tokens is a number, from 0. The state is one parse's tokens (in a hash table
; by place), what it has remembered of each rule, and how far it got and what it was looking
; for there -- for the error message.

(defstruct peg-state
  grammar
  tokens          ; hash table: place -> token
  count           ; how many tokens
  rules           ; the grammar's, for speed
  ignore-case     ; the grammar's option, for speed
  memo            ; hash table: rule name -> hash table: place -> what the rule found there
  furthest        ; the furthest place a match has failed at
  expected        ; what was being looked for there: a list of texts
  soft-expected   ; the same for what was only a try: an optional part that didn't begin there
  soft-place)     ; while an optional part is being tried: the place it began, where a failure is only a try

(define (peg-token-at state place)
  "The token at that place, or #f at the end."
  (hash-table-ref (peg-state-tokens state) place #f))

(define (peg-fail! state place expectation)
  "Notes that the expectation (a text) wasn't met at the place, if that's the furthest place yet or as far
as any other; always returns #f. A failure at the place where an optional part began (softly) is
noted apart: that the part didn't begin there is only one of the things that could come next, not a mistake.
The message gives those only if there are no others."
  (let ((furthest (peg-state-furthest state)))
    (when (>= place furthest)
      (let ((soft (= place (peg-state-soft-place state))))
        (when (> place furthest)
          (peg-state-furthest-set! state place)
          (peg-state-expected-set! state '())
          (peg-state-soft-expected-set! state '()))
        (if soft
            (unless (member expectation (peg-state-soft-expected state))
              (peg-state-soft-expected-set! state (cons expectation (peg-state-soft-expected state))))
            (unless (member expectation (peg-state-expected state))
              (peg-state-expected-set! state (cons expectation (peg-state-expected state))))))))
  #f)

(defmacro softly (place state . body)
  "Evaluates the body, during which a failure at the place is only a try (see peg-fail!), and returns its value."
  `(let ((outside (peg-state-soft-place ,state)))
     (peg-state-soft-place-set! ,state ,place)
     (let ((result (begin ,@body)))
       (peg-state-soft-place-set! ,state outside)
       result)))

(define (peg-shown-expectation expectation state)
  "An expectation as it is shown in a message. A text that was looked for (a pair, (literal . text)) is in
capitals when the case of the texts doesn't matter, as keywords usually are; a description is as written."
  (cond ((not (pair? expectation)) expectation)
        ((peg-state-ignore-case state) (string-upcase (cdr expectation)))
        (else (cdr expectation))))

(define (peg-same-text? a b state)
  (if (peg-state-ignore-case state)
      (string=? (string-downcase a) (string-downcase b))
      (string=? a b)))

(define (peg-collapse values)
  "The value of a group of items from the values of those with one: that value, or the list of them, or #t if none."
  (cond ((null? values) #t)
        ((null? (cdr values)) (car values))
        (else values)))

(define (peg-describe state name)
  (hash-table-ref (parser-grammar-descriptions (peg-state-grammar state)) name (symbol->string name)))

(define (peg-match-text text place state)
  "A token with the text."
  (let ((token (peg-token-at state place)))
    (if (and token (peg-same-text? (peg-token-text token) text state))
        (cons peg-no-value (+ place 1))
        (peg-fail! state place (cons 'literal text)))))

(define (peg-match-name name place state)
  "The end, or a rule, or a kind of token."
  (let ((token (peg-token-at state place)))
    (cond ((eq? name 'end)
           (if token
               (peg-fail! state place (peg-option (peg-state-grammar state) 'end-name))
               (cons peg-no-value place)))
          ((hash-table-has? (peg-state-rules state) name)
           (peg-call-rule name place state))
          ((and token (eq? (peg-token-kind token) name))
           (cons (peg-token-value token) (+ place 1)))
          (else (peg-fail! state place (peg-describe state name))))))

(define (peg-match-sequence items place state)
  "The items one after another: (list-of-values . next-place), or #f."
  (let go ((items items) (place place) (values '()))
    (if (null? items)
        (cons (reverse values) place)
        (let ((found (peg-match-item (car items) place state)))
          (cond ((not found) #f)
                ((eq? (car found) peg-no-value) (go (cdr items) (cdr found) values))
                (else (go (cdr items) (cdr found) (cons (car found) values))))))))

(define (peg-match-group items place state)
  "The items as one: (value . next-place), with the value of the group."
  (let ((found (peg-match-sequence items place state)))
    (and found (cons (peg-collapse (car found)) (cdr found)))))

(define (peg-match-repeated items minimum place state)
  "The items again and again, as many as match (and at least `minimum`), stopping if one reads nothing.
Once there are enough, another is only a try."
  (let go ((place place) (found '()))
    (let ((next (if (>= (length found) minimum)
                    (softly place state (peg-match-group items place state))
                    (peg-match-group items place state))))
      (cond ((and next (> (cdr next) place))
             (go (cdr next) (cons (car next) found)))
            ((>= (length found) minimum) (cons (reverse found) place))
            (else #f)))))

(define (peg-match-separated separator items place state)
  "One or more of the items with the separator between them. A separator with no item after it isn't read."
  (let ((first (peg-match-group items place state)))
    (and first
         (let go ((place (cdr first)) (found (list (car first))))
           (let ((next (softly place state
                                (let ((comma (peg-match-item separator place state)))
                                  (and comma (peg-match-group items (cdr comma) state))))))
             (if next
                 (go (cdr next) (cons (car next) found))
                 (cons (reverse found) place)))))))

(define (peg-match-first-of items place state)
  "The first of the items that matches."
  (and (not (null? items))
       (or (peg-match-group (list (car items)) place state)
           (peg-match-first-of (cdr items) place state))))

(define (peg-match-one-of texts place state)
  "The first of the texts that is the next token's; its value is the text."
  (cond ((null? texts) #f)
        ((let ((token (peg-token-at state place)))
           (and token (peg-same-text? (peg-token-text token) (car texts) state)))
         (cons (car texts) (+ place 1)))
        (else
         (peg-fail! state place (cons 'literal (car texts)))
         (peg-match-one-of (cdr texts) place state))))

(define (peg-match-not items place state)
  "Succeeds, reading nothing, when the items don't match. What they fail to find isn't something to report."
  (let* ((furthest (peg-state-furthest state))
         (expected (peg-state-expected state))
         (found (peg-match-group items place state)))
    (peg-state-furthest-set! state furthest)
    (peg-state-expected-set! state expected)
    (if found #f (cons peg-no-value place))))

(define (peg-build node left right)
  "The value of an operator applied to two operands: (node left right), or what the procedure makes of them."
  (if (symbol? node)
      (list node left right)
      (node left right)))

(define (peg-match-operator operators place state)
  "The first of the operators (text . node) that's next: (node . next-place)."
  (if (null? operators)
      #f
      (let ((found (peg-match-text (car (car operators)) place state)))
        (if found
            (cons (cdr (car operators)) (cdr found))
            (peg-match-operator (cdr operators) place state)))))

(define (peg-match-chain operand operators place state)
  "The operand, and more operands each after an operator, grouped from the left."
  (let ((first (peg-match-item operand place state)))
    (and first
         (let go ((left (car first)) (place (cdr first)))
           (let ((more (softly place state
                                (let ((operator (peg-match-operator operators place state)))
                                  (and operator
                                       (let ((right (peg-match-item operand (cdr operator) state)))
                                         (and right (cons (peg-build (car operator) left (car right)) (cdr right)))))))))
             (if more
                 (go (car more) (cdr more))
                 (cons left place)))))))

(define (peg-match-item item place state)
  "Matches the item at the place: (value . next-place), or #f. The value is peg-no-value for an item that has none."
  (cond ((string? item) (peg-match-text item place state))
        ((symbol? item) (peg-match-name item place state))
        (else
         (case (car item)
           ((opt)
            (or (softly place state (peg-match-group (cdr item) place state))
                (cons '() place)))
           ((flag)
            (let ((found (softly place state (peg-match-group (cdr item) place state))))
              (if found (cons #t (cdr found)) (cons #f place))))
           ((star) (peg-match-repeated (cdr item) 0 place state))
           ((plus) (peg-match-repeated (cdr item) 1 place state))
           ((sep-by) (peg-match-separated (cadr item) (cddr item) place state))
           ((or) (peg-match-first-of (cdr item) place state))
           ((one-of) (peg-match-one-of (cdr item) place state))
           ((seq) (peg-match-group (cdr item) place state))
           ((drop)
            (let ((found (peg-match-group (cdr item) place state)))
              (and found (cons peg-no-value (cdr found)))))
           ((not) (peg-match-not (cdr item) place state))
           ((chain) (peg-match-chain (cadr item) (cddr item) place state))
           (else (peg-error "not an item:" item))))))

; ---------------------------------------------------------------------------
; 4. Rules
; ---------------------------------------------------------------------------

(define (peg-apply-action action values)
  (if action
      (apply action values)
      (peg-collapse values)))

(define (peg-try-alternatives alternatives place state)
  "The first alternative of a rule whose items match at the place: (value . next-place)."
  (if (null? alternatives)
      #f
      (let* ((alternative (car alternatives))
             (found (peg-match-sequence (car alternative) place state)))
        (if found
            (cons (peg-apply-action (cdr alternative) (car found)) (cdr found))
            (peg-try-alternatives (cdr alternatives) place state)))))

(define (peg-run-rule name place state)
  "Tries the rule's alternatives. If it fails without having got past where it started, and it has a
description, the message says what it is the description of, not each thing it tried."
  (let* ((furthest (peg-state-furthest state))
         (expected (peg-state-expected state))
         (soft-expected (peg-state-soft-expected state))
         (found (peg-try-alternatives (hash-table-ref (peg-state-rules state) name) place state))
         (descriptions (parser-grammar-descriptions (peg-state-grammar state))))
    (when (and (not found)
               (hash-table-has? descriptions name)
               (= (peg-state-furthest state) place))
      (peg-state-expected-set! state (if (= furthest place) expected '()))
      (peg-state-soft-expected-set! state (if (= furthest place) soft-expected '()))
      (peg-fail! state place (hash-table-ref descriptions name)))
    found))

(define (peg-call-rule name place state)
  "What the rule finds at the place, remembered. A rule that is asked for again while it is looking
at the same place is one that begins with itself."
  (let* ((memo (hash-table-ref (peg-state-memo state) name))
         (before (hash-table-ref memo place 'not-yet)))
    (cond ((eq? before 'in-progress)
           (peg-error "rule" name "begins with itself, so it would never stop. Write the repetition as chain, star, or sep-by"))
          ((not (eq? before 'not-yet)) before)
          (else
           (hash-table-set! memo place 'in-progress)
           (let ((found (peg-run-rule name place state)))
             (hash-table-set! memo place found)
             found)))))

; ---------------------------------------------------------------------------
; 5. Parsing
; ---------------------------------------------------------------------------

(define (peg-list-alternatives texts)
  "a, b or c; or, for a long list, the first few and ..."
  (cond ((null? texts) "something else")
        ((null? (cdr texts)) (car texts))
        ((> (length texts) 8) (string-append (string-join (peg-first-items texts 8) ", ") ", ..."))
        (else (string-append (string-join (reverse (cdr (reverse texts))) ", ") " or " (car (reverse texts))))))

(define (peg-first-items items count)
  (loop for item in items
        for i from 0 below count
        collect item))

(define (peg-token-shown token)
  "A token as it is shown in a message: its text, or its kind if the text is only spaces (a newline)."
  (if (string=? (string-trim (peg-token-text token)) "")
      (symbol->string (peg-token-kind token))
      (peg-token-text token)))

(define (peg-fail-with-message state)
  "Signals the error that says what was expected where the parse got to, and what was there."
  (let* ((grammar (peg-state-grammar state))
         (token (peg-token-at state (peg-state-furthest state)))
         (expected (map (lambda (text) (peg-shown-expectation text state))
                        (reverse (if (null? (peg-state-expected state))
                                     (peg-state-soft-expected state)
                                     (peg-state-expected state))))))
    (error (peg-option grammar 'error-prefix)
           "expected" (peg-list-alternatives expected)
           "but found"
           (if token
               (format "{} (at character {})" (peg-token-shown token) (peg-token-position token))
               (peg-option grammar 'end-name)))))

(define (peg-start-state grammar tokens)
  "A new state for parsing the tokens (a list): their places in a hash table, and a table for what each rule finds."
  (let ((places (make-hash-table))
        (memo (make-hash-table)))
    (loop for token in tokens
          for place from 0
          do (hash-table-set! places place token))
    (dolist (name (hash-table-keys (parser-grammar-rules grammar)))
      (hash-table-set! memo name (make-hash-table)))
    (make-peg-state :grammar grammar :tokens places :count (length tokens)
                    :rules (parser-grammar-rules grammar)
                    :ignore-case (peg-option grammar 'ignore-case) :memo memo
                    :furthest -1 :expected '() :soft-expected '() :soft-place -1)))

(define (grammar-parse grammar text &key (start '()))
  "The value of the text by the grammar's rule `start` (:start name; the grammar's start rule, if none is given). All of the
text has to be the rule's; if it isn't, or no rule fits, the error says what was expected and where."
  (let* ((tokens (peg-read-tokens grammar text))
         (name (if (null? start) (peg-option grammar 'start) start)))
    (unless (hash-table-has? (parser-grammar-rules grammar) name)
      (peg-error name "isn't a rule of the grammar"))
    (let* ((state (peg-start-state grammar tokens))
           (found (peg-call-rule name 0 state)))
      (cond ((and found (= (cdr found) (peg-state-count state))) (car found))
            (else
             (when found                                   ; read a first part, and there's more: the end could have been here
               (softly (cdr found) state
                       (peg-fail! state (cdr found) (peg-option grammar 'end-name))))
             (peg-fail-with-message state))))))
