; template.lsp
; ============
; A small, general-purpose text-templating engine -- {{name}} variable
; substitution, {{#each item in list}}...{{/each}} loops (with an
; optional separator), and {{#if name}}...{{else}}...{{/if}} conditionals
; -- with a SECOND rendering mode specifically for building SQL safely.
;
; General use (plain text -- messages, filenames, generated reports,
; anything that isn't SQL):
;
;   (template-render "Hello, {{name}}! You have {{count}} new message{{s}}."
;                     (template-bindings (name "Ada") (count 3) (s "s")))
;   ; => "Hello, Ada! You have 3 new messages."
;
; SQL use -- the feature this file was written for -- typing a query with
; "?" placeholders and a matching list of values, e.g.
;   "...WHERE column_a = ? AND column_b = ?"
; the ordinary way any parameterized-query API works, except here the
; placeholders and the values that fill them are written together, right
; next to each other, as {{name}}:
;
;   (define rendered
;     (template-render-sql
;       "SELECT * FROM loans WHERE state = {{state}} AND balance > {{min-balance}}"
;       (template-bindings (state "CA") (min-balance 100000))))
;   (car rendered)   ; => "SELECT * FROM loans WHERE state = ? AND balance > ?"
;   (cdr rendered)   ; => ("CA" 100000)
;
;   ; ...or skip the two steps above and run it directly:
;   (sqlite-query-template conn
;     "SELECT * FROM loans WHERE state = {{state}} AND balance > {{min-balance}}"
;     (template-bindings (state "CA") (min-balance 100000)))
;
; WHY THIS CAN'T PRODUCE A SQL INJECTION, BY CONSTRUCTION
; ---------------------------------------------------------------------
; template-render-sql does not have an "unsafe"/"raw" substitution mode.
; Every single {{name}} it sees becomes a literal "?" character in the
; rendered SQL text -- never the value itself -- with the looked-up value
; appended to a separate list instead. That list is then handed to
; sqlite-query/sqlite-execute's own `params` argument, which passes it to
; SQLite's native parameter binding (see _sqlite_run in lisp_interpreter.py):
; SQLite receives the VALUE over a completely separate channel from the
; SQL TEXT, so it is structurally impossible for a value's contents --
; quotes, semicolons, comment markers, anything -- to be interpreted as
; SQL syntax. This is the same reason parameterized queries are considered
; safe in every language; the only difference here is that the query text
; and its parameter list are written together, in one place, instead of a
; SQL string with "?"s in one spot and a separate positional value list
; somewhere else that has to be kept in sync with it by hand.
;
; The one thing this can't protect against -- nothing could -- is passing
; UNTRUSTED data as the template STRING itself (as opposed to as a bound
; VALUE): e.g. (template-render-sql (string-append "SELECT * FROM " x) ...)
; splices `x` directly into the SQL text before the template engine ever
; sees it, the same way handing raw, unparameterized, string-built SQL to
; any database driver would. The template you write is trusted, hand-authored
; code, exactly like a parameterized query string is in any language; only
; the {{name}} VALUES are meant to come from elsewhere.
;
; TEMPLATE SYNTAX
; ---------------------------------------------------------------------
;   {{name}}
;     Substitute the value bound to `name`. In template-render (plain
;     text), this is the value's display text (via number->string, which
;     -- despite the name -- stringifies any Lisp value: numbers,
;     strings, symbols, lists, ...). In template-render-sql, this is
;     ALWAYS a literal "?", with the value going into the params list
;     instead -- see above.
;
;   {{#each item in list}} ... {{item}} ... {{/each}}
;     Renders the body once per element of the list bound to `list`
;     (a plain Lisp list, or a vector -- either works), with `item`
;     bound to the current element inside the body. Nests fine --
;     each loop introduces its own item name, so an inner {{#each}}
;     doesn't shadow an outer one's.
;
;   {{#each item in list sep sepname}} ... {{/each}}
;     Same, but joins consecutive renderings with the separator bound to
;     `sepname` (not a literal -- bind it in your own bindings, e.g.
;     (template-bindings (sep ", "))) -- handy for a SQL "IN (...)" list:
;
;       (template-render-sql
;         "SELECT * FROM loans WHERE id IN ({{#each x in ids sep comma}}{{x}}{{/each}})"
;         (template-bindings (ids (list 1 2 3)) (comma ", ")))
;       ; => ("SELECT * FROM loans WHERE id IN (?, ?, ?)" . (1 2 3))
;
;   {{#if name}} ... {{/if}}
;   {{#if name}} ... {{else}} ... {{/if}}
;     Renders the first (or, if given, second) branch depending on
;     whether the value bound to `name` is true -- this Lisp's own
;     truthiness rule: anything except #f, including '() and 0. A name
;     with nothing bound to it (see template--alist-get's default,
;     below) is treated as #f, so {{#if maybe-flag}} works even when
;     `maybe-flag` is simply left out of the bindings.
;
; A template can be rendered directly as a string, or parsed once with
; template-parse and rendered many times (e.g. once per row of a report)
; without re-parsing -- template-render/template-render-sql accept
; either a raw template string or an already-parsed node list.
;
; Not supported, on purpose, to keep this simple: no escaping a literal
; "{{"/"}}" in template text (don't put those two characters next to each
; other outside a real tag), no per-item loop index, no nested-field
; access inside {{...}} (a placeholder is always a single bound name --
; compute anything more complex in Lisp first and bind the result).

; ---------------------------------------------------------------------
; Low-level string utilities (no string-search/split builtin exists, so
; these are written from scratch on top of substring/string-length/
; string=?; naive O(length) scans, which is completely fine for parsing
; a template -- normally a few dozen to a few hundred characters, not
; huge data).
; ---------------------------------------------------------------------

(define (template--char s i)
  (substring s i (+ i 1)))

(define (template--index-of-from haystack needle start)
  "Index of the first occurrence of `needle` in `haystack` at or after
`start`, or -1 if there isn't one."
  (define hn (string-length haystack))
  (define nn (string-length needle))
  (define (scan i)
    (cond
      ((> (+ i nn) hn) -1)
      ((string=? (substring haystack i (+ i nn)) needle) i)
      (else (scan (+ i 1)))))
  (scan start))

(define (template--is-space? c)
  "Space, tab, newline, or carriage return (the last one matters for a
template loaded from a Windows-authored CRLF text file)."
  (or (string=? c " ") (string=? c "\t") (string=? c "\n") (string=? c "\r")))

(define (template--trim s)
  "Strip leading/trailing whitespace."
  (define n (string-length s))
  (define (find-start i)
    (if (and (< i n) (template--is-space? (template--char s i))) (find-start (+ i 1)) i))
  (define (find-end i)
    (if (and (> i 0) (template--is-space? (template--char s (- i 1)))) (find-end (- i 1)) i))
  (define start (find-start 0))
  (define end (find-end n))
  (if (>= start end) "" (substring s start end)))

(define (template--split-whitespace s)
  "Split s on runs of whitespace into a list of non-empty tokens."
  (define n (string-length s))
  (define (skip-spaces i)
    (if (and (< i n) (template--is-space? (template--char s i))) (skip-spaces (+ i 1)) i))
  (define (scan-token i)
    (if (and (< i n) (not (template--is-space? (template--char s i)))) (scan-token (+ i 1)) i))
  (define (loop i)
    (define start (skip-spaces i))
    (if (>= start n)
        '()
        (let ((end (scan-token start)))
          (cons (substring s start end) (loop end)))))
  (loop 0))

(define (template--member? x lst)
  (cond
    ((null? lst) #f)
    ((equal? (car lst) x) #t)
    (else (template--member? x (cdr lst)))))

; ---------------------------------------------------------------------
; Bindings: a plain list of (name value) pairs, the same two-element-list
; shape `let` itself uses -- so a lookup miss can be told apart from a
; deliberately-bound '() (used as the "found" sentinel below), and so
; nested scopes (a loop's item variable) are just "prepend one more
; pair" -- no separate environment type needed.
; ---------------------------------------------------------------------

(define (template--alist-get alist key default)
  (cond
    ((null? alist) default)
    ((equal? (car (car alist)) key) (car (cdr (car alist))))
    (else (template--alist-get (cdr alist) key default))))

(define (template--alist-set alist key value)
  (cons (list key value) alist))

(define (template--as-list x)
  "A bound `{{#each item in X}}` value can be a plain list already, or a
vector -- normalize either to a plain list for iteration."
  (if (vector? x) (vector->list x) x))

(define (template--truthy? x)
  "This Lisp's own truthiness rule (is_true in lisp_interpreter.py):
everything except #f is true, '() and 0 included. Deliberately routed
through `if` itself (not (eq? x #f) or similar) -- eq?'s equality
fallback (a is b or a == b) treats 0 as equal to #f, because Python's
bool is a subclass of int (0 == False is True at the Python level);
if's own native test doesn't have that problem, since it checks `is not
False` rather than equality, so reusing it here sidesteps the trap
instead of reintroducing it."
  (if x #t #f))

; ---------------------------------------------------------------------
; Parser: template-parse turns a template string into a list of nodes --
;   (text "literal text")
;   (var name)
;   (each itemvar listname sepvar-or-'() body-nodes)
;   (if condname then-nodes else-nodes)
; This is plain (non-tail) recursion -- fine here, since parse depth is
; bounded by how deeply {{#each}}/{{#if}} tags are NESTED IN THE
; TEMPLATE SOURCE (always small, a handful of levels at most), never by
; any runtime data size, the same reasoning lisp_interpreter.py's own
; eval_quasiquote uses for the same kind of recursion.
; ---------------------------------------------------------------------

(define (template--reserved-tag? content)
  (or (string=? content "else") (string=? content "/each") (string=? content "/if")))

(define (template--starts-with? s prefix)
  (define pn (string-length prefix))
  (and (>= (string-length s) pn) (string=? (substring s 0 pn) prefix)))

(define (template--text-node s)
  "A one-element list holding a text node for s, or '() if s is empty --
so an empty gap next to a tag doesn't produce a spurious empty node."
  (if (= (string-length s) 0) '() (list (list 'text s))))

(define (template--find-tag s pos)
  "The next {{...}} tag at or after pos: (list before-text trimmed-content
tag-start after-tag-pos), or '() if there are no more tags."
  (define open (template--index-of-from s "{{" pos))
  (if (= open -1)
      '()
      (let ((close (template--index-of-from s "}}" (+ open 2))))
        (if (= close -1)
            (error "template-parse: unterminated {{ opened at character" open "in" s)
            (list (substring s pos open)
                  (template--trim (substring s (+ open 2) close))
                  open
                  (+ close 2))))))

(define (template--parse-each-tag content)
  "content, e.g. \"#each item in list\" or \"#each item in list sep sepname\"
-> (list itemvar-symbol listname-symbol sepvar-symbol-or-'())."
  (define tokens (template--split-whitespace content))
  (define n (length tokens))
  (cond
    ((and (= n 4) (string=? (list-ref tokens 2) "in"))
     (list (string->symbol (list-ref tokens 1)) (string->symbol (list-ref tokens 3)) '()))
    ((and (= n 6) (string=? (list-ref tokens 2) "in") (string=? (list-ref tokens 4) "sep"))
     (list (string->symbol (list-ref tokens 1)) (string->symbol (list-ref tokens 3))
           (string->symbol (list-ref tokens 5))))
    (else (error "template-parse: malformed {{#each ...}} tag:" content))))

(define (template--parse-if-tag content)
  (define tokens (template--split-whitespace content))
  (if (= (length tokens) 2)
      (string->symbol (list-ref tokens 1))
      (error "template-parse: malformed {{#if ...}} tag:" content)))

(define (template--parse-var-tag content)
  (define tokens (template--split-whitespace content))
  (if (= (length tokens) 1)
      (string->symbol (car tokens))
      (error "template-parse: malformed {{...}} tag (expected one name):" content)))

(define (template--parse-nodes s pos end-tags)
  "Parse nodes from pos until hitting a tag whose trimmed content is one
of end-tags, or the end of the string (only valid when end-tags is '()).
Returns (list nodes-so-far new-pos matched-end-tag), matched-end-tag
being '() at end-of-string."
  (define found (template--find-tag s pos))
  (cond
    ((null? found)
     (if (not (null? end-tags))
         (error "template-parse: missing a closing {{/" (car end-tags) "}}")
         '())
     (list (template--text-node (substring s pos)) (string-length s) '()))
    (else
     (let* ((before (list-ref found 0))
            (content (list-ref found 1))
            (after-pos (list-ref found 3))
            (before-nodes (template--text-node before)))
       (cond
         ((template--member? content end-tags)
          (list before-nodes after-pos content))

         ((template--reserved-tag? content)
          (error "template-parse: unexpected {{" content "}} -- nothing open to close it"))

         ((template--starts-with? content "#each")
          (let* ((each-spec (template--parse-each-tag content))
                 (itemvar (list-ref each-spec 0))
                 (listname (list-ref each-spec 1))
                 (sepvar (list-ref each-spec 2))
                 (body-result (template--parse-nodes s after-pos (list "/each")))
                 (body-nodes (list-ref body-result 0))
                 (after-body (list-ref body-result 1))
                 (rest-result (template--parse-nodes s after-body end-tags)))
            (list (append before-nodes
                           (list (list 'each itemvar listname sepvar body-nodes))
                           (list-ref rest-result 0))
                  (list-ref rest-result 1)
                  (list-ref rest-result 2))))

         ((template--starts-with? content "#if")
          (let* ((condname (template--parse-if-tag content))
                 (then-result (template--parse-nodes s after-pos (list "/if" "else")))
                 (then-nodes (list-ref then-result 0))
                 (after-then (list-ref then-result 1))
                 (then-end-tag (list-ref then-result 2)))
            (if (string=? then-end-tag "else")
                (let* ((else-result (template--parse-nodes s after-then (list "/if")))
                       (after-else (list-ref else-result 1))
                       (rest-result (template--parse-nodes s after-else end-tags)))
                  (list (append before-nodes
                                 (list (list 'if condname then-nodes (list-ref else-result 0)))
                                 (list-ref rest-result 0))
                        (list-ref rest-result 1)
                        (list-ref rest-result 2)))
                (let ((rest-result (template--parse-nodes s after-then end-tags)))
                  (list (append before-nodes
                                 (list (list 'if condname then-nodes '()))
                                 (list-ref rest-result 0))
                        (list-ref rest-result 1)
                        (list-ref rest-result 2))))))

         (else
          (let* ((varname (template--parse-var-tag content))
                 (rest-result (template--parse-nodes s after-pos end-tags)))
            (list (append before-nodes (list (list 'var varname)) (list-ref rest-result 0))
                  (list-ref rest-result 1)
                  (list-ref rest-result 2)))))))))

(define (template-parse template-string)
  "Parse a template string into a node list -- see the file header for
the syntax, and template-render/template-render-sql for rendering it.
Pre-parsing with this (once) is only worth it if you're about to render
the SAME template many times; template-render/-sql happily take a raw
string directly otherwise."
  (car (template--parse-nodes template-string 0 '())))

; ---------------------------------------------------------------------
; Plain-text rendering.
; ---------------------------------------------------------------------

(define (template--render-nodes nodes bindings)
  (cond
    ((null? nodes) "")
    (else (string-append (template--render-node (car nodes) bindings)
                          (template--render-nodes (cdr nodes) bindings)))))

(define (template--render-each-items nodes items bindings itemvar sep)
  (cond
    ((null? items) "")
    ((null? (cdr items))
     (template--render-nodes nodes (template--alist-set bindings itemvar (car items))))
    (else
     (string-append
       (template--render-nodes nodes (template--alist-set bindings itemvar (car items)))
       sep
       (template--render-each-items nodes (cdr items) bindings itemvar sep)))))

(define (template--render-node node bindings)
  (define kind (car node))
  (cond
    ((eq? kind 'text) (list-ref node 1))
    ((eq? kind 'var) (number->string (template--alist-get bindings (list-ref node 1) "")))
    ((eq? kind 'each)
     (let* ((itemvar (list-ref node 1))
            (listname (list-ref node 2))
            (sepvar (list-ref node 3))
            (body (list-ref node 4))
            (items (template--as-list (template--alist-get bindings listname '())))
            (sep (if (null? sepvar) "" (number->string (template--alist-get bindings sepvar "")))))
       (template--render-each-items body items bindings itemvar sep)))
    ((eq? kind 'if)
     (let ((condval (template--alist-get bindings (list-ref node 1) #f)))
       (if (template--truthy? condval)
           (template--render-nodes (list-ref node 2) bindings)
           (template--render-nodes (list-ref node 3) bindings))))
    (else (error "template-render: unknown node kind" kind))))

(define (template-render template bindings)
  "Render `template` (a template string, or an already-parsed node list
from template-parse) against `bindings` (a list of (name value) pairs --
see template-bindings) to a plain string. See the file header for
{{name}}/{{#each}}/{{#if}} syntax. NOT meant for building a SQL string
out of untrusted data -- use template-render-sql for that."
  (define nodes (if (string? template) (template-parse template) template))
  (template--render-nodes nodes bindings))

; ---------------------------------------------------------------------
; SQL-safe rendering: every node-rendering function here returns
; (cons sql-text-fragment params-list-fragment) instead of just a
; string, and {{name}} ALWAYS contributes "?" plus one bound value to
; the params list -- see the file header for why this is what actually
; makes SQL injection impossible here, not just unlikely.
; ---------------------------------------------------------------------

(define (template--render-nodes-sql nodes bindings)
  (cond
    ((null? nodes) (cons "" '()))
    (else
     (let ((first (template--render-node-sql (car nodes) bindings))
           (rest (template--render-nodes-sql (cdr nodes) bindings)))
       (cons (string-append (car first) (car rest))
             (append (cdr first) (cdr rest)))))))

(define (template--render-each-items-sql nodes items bindings itemvar sep)
  (cond
    ((null? items) (cons "" '()))
    ((null? (cdr items))
     (template--render-nodes-sql nodes (template--alist-set bindings itemvar (car items))))
    (else
     (let ((first-part (template--render-nodes-sql nodes (template--alist-set bindings itemvar (car items))))
           (rest-part (template--render-each-items-sql nodes (cdr items) bindings itemvar sep)))
       (cons (string-append (car first-part) sep (car rest-part))
             (append (cdr first-part) (cdr rest-part)))))))

(define (template--render-node-sql node bindings)
  (define kind (car node))
  (cond
    ((eq? kind 'text) (cons (list-ref node 1) '()))
    ((eq? kind 'var) (cons "?" (list (template--alist-get bindings (list-ref node 1) '()))))
    ((eq? kind 'each)
     (let* ((itemvar (list-ref node 1))
            (listname (list-ref node 2))
            (sepvar (list-ref node 3))
            (body (list-ref node 4))
            (items (template--as-list (template--alist-get bindings listname '())))
            (sep (if (null? sepvar) "" (number->string (template--alist-get bindings sepvar "")))))
       (template--render-each-items-sql body items bindings itemvar sep)))
    ((eq? kind 'if)
     (let ((condval (template--alist-get bindings (list-ref node 1) #f)))
       (if (template--truthy? condval)
           (template--render-nodes-sql (list-ref node 2) bindings)
           (template--render-nodes-sql (list-ref node 3) bindings))))
    (else (error "template-render-sql: unknown node kind" kind))))

(define (template-render-sql template bindings)
  "Render `template` (a template string, or an already-parsed node list)
against `bindings` (see template-render) to (cons sql-string params-list)
-- pass that pair straight to sqlite-query/sqlite-execute's own `params`
argument (or use sqlite-query-template/sqlite-execute-template, below,
to skip that step). Every {{name}} becomes a bound parameter, never text
spliced into the SQL -- see the file header for why that's what makes
this safe against SQL injection, and for the {{#each ... sep ...}} \"IN
(?, ?, ?)\" pattern."
  (define nodes (if (string? template) (template-parse template) template))
  (template--render-nodes-sql nodes bindings))

; ---------------------------------------------------------------------
; Convenience: build a bindings list without hand-quoting each name.
; ---------------------------------------------------------------------

(defmacro template-bindings pairs
  (cons 'list (map (lambda (pair) (list 'list (list 'quote (car pair)) (car (cdr pair)))) pairs)))

; ---------------------------------------------------------------------
; Convenience: render a template in SQL mode and run it in one call.
; ---------------------------------------------------------------------

(define (sqlite-query-template conn template bindings . rest)
  "(sqlite-query-template conn template bindings [dtypes max-rows]) --
render `template` in SQL mode against `bindings` and run it via
sqlite-query, e.g.:
  (sqlite-query-template conn
    \"SELECT * FROM loans WHERE state = {{state}}\"
    (template-bindings (state \"CA\")))
`dtypes`/`max-rows`, if given, are passed straight through to
sqlite-query -- see its own docstring."
  (define rendered (template-render-sql template bindings))
  (define dtypes (if (> (length rest) 0) (list-ref rest 0) '()))
  (define max-rows (if (> (length rest) 1) (list-ref rest 1) '()))
  (sqlite-query conn (car rendered) dtypes max-rows (cdr rendered)))

(define (sqlite-execute-template conn template bindings)
  "(sqlite-execute-template conn template bindings) -- render `template`
in SQL mode against `bindings` and run it via sqlite-execute, returning
a cursor to step through with sqlite-fetch-row -- for a parameterized
query whose result you'd rather not materialize all at once."
  (define rendered (template-render-sql template bindings))
  (sqlite-execute conn (car rendered) (cdr rendered)))
