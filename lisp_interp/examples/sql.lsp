; sql.lsp
;
; A small SQL interpreter, simple enough to read and see how SQL works. Its
; tables are the interpreter's own tables -- the ones load-csv, load-sqlite,
; and the other data sources make -- so it can ask questions of any table you
; already have, and a table it makes or changes is an ordinary table you can
; pass to display-table, plot-chart, or a regression.
;
;   (load "sql.lsp")
;   (sql-register-table! "loans" (load-csv "loans.csv"))   ; any table you have
;   (show-sql "SELECT state, SUM(balance) AS upb FROM loans GROUP BY state ORDER BY upb DESC")
;   (sql "SELECT * FROM loans WHERE rate > 6")             ; the result, as a table
;   (sql-repl)                                             ; type statements at a prompt
;
; (show-sql "...") prints the result of each statement in the text; (sql "...")
; runs them and returns the result of the last. A SELECT gives a table; the
; other statements give a sentence saying what they did.
;
; What it understands:
;
;   SELECT [DISTINCT] item, ... [FROM table [alias] [[INNER|LEFT [OUTER]] JOIN table [alias] ON a = b [AND ...]]]
;          [WHERE condition] [GROUP BY expression, ...] [HAVING condition]
;          [ORDER BY expression [ASC|DESC], ...] [LIMIT n [OFFSET m]]
;   INSERT INTO table [(column, ...)] VALUES (value, ...), ... | SELECT ...
;   UPDATE table SET column = expression, ... [WHERE condition]
;   DELETE FROM table [WHERE condition]
;   CREATE TABLE [IF NOT EXISTS] table (column type, ...)     (types: integer, real, text, date)
;   DROP TABLE [IF EXISTS] table
;
; An item is *, alias.*, or an expression with an optional [AS] name. An
; expression has numbers, 'text', NULL, columns (name or table.name), + - * / %,
; = <> != < <= > >=, AND, OR, NOT, IS [NOT] NULL, [NOT] LIKE, [NOT] BETWEEN,
; [NOT] IN (list), and the functions upper, lower, length, abs, round,
; coalesce, and date, and the aggregates count(*), count(x), sum, avg, min, max.
;
; What it leaves out, to stay small: subqueries, UNION, joins on anything but
; equal columns, count(DISTINCT x), constraints (PRIMARY KEY, NOT NULL), and
; transactions. Where it differs from most SQL databases:
;
;   - Names are not case-sensitive. Text is: 'CA' and 'ca' are different.
;   - / is exact division, even of whole numbers (7 / 2 is 3.5), and numbers with
;     fractions are the interpreter's usual 32-bit floats, so about 7 digits.
;   - Rows with the same value in ORDER BY stay in the order they were in, and a
;     missing value (NULL) sorts after the others, or before them in DESC order.
;   - A table has no row order promised, and a query with no ORDER BY gives
;     the rows in whatever order is handy.
;
; How it works, in the order of this file:
;
;   1. The database -- the tables, and the kind of value (number, text, date) in each column.
;   2. The grammar -- a table of rules that says what a statement is made of, read by the parser
;      framework in lib/parser.lsp. It cuts the text into tokens (words, numbers, 'strings', symbols)
;      with regular expressions, and builds a tree from them, such as (add (col "x") (num 1)).
;   3. Expressions -- a tree and a table to a vector, one value for each row of the table.
;   4. Groups -- GROUP BY and the aggregates, with table-group-by.
;   5. SELECT -- the steps of a query, one after another, each with a table function.
;   6. The other statements, and the ways to run them.

(load "parser.lsp")

; ---------------------------------------------------------------------------
; 1. The database
; ---------------------------------------------------------------------------
; The tables are in a hash table, by name in lower case. The table itself is
; just a table, a list of (column-name . vector) pairs. SQL says what kind of
; value each column holds, which a table doesn't, so the kinds -- one of
; number, text, or date for each column -- are kept beside it. They matter when
; a value is added: a missing number is nan, and a missing piece of text is '().

(define sql-tables (make-hash-table))
(define sql-kinds (make-hash-table))

(define (sql-error . parts)
  (apply error "sql:" parts))

(define (sql-reset!)
  "Forgets every table."
  (set! sql-tables (make-hash-table))
  (set! sql-kinds (make-hash-table)))

(define (missing-value? x)
  (or (null? x) (and (number? x) (not (= x x)))))

(define (kind-of-column values)
  "number, text, or date: the kind of the first value in the vector that isn't missing."
  (let ((present (vector-select values (vector-not (vector-nan? values)))))
    (cond ((= (vector-length present) 0) 'number)
          ((string? (vector-ref present 0)) 'text)
          ((number? (vector-ref present 0)) 'number)
          (else 'date))))

(define (sql-register-table! name table)
  "Makes a table you have available to SQL as `name`."
  (hash-table-set! sql-tables (string-downcase name) table)
  (hash-table-set! sql-kinds (string-downcase name)
                   (map (lambda (column) (kind-of-column (cdr column))) table)))

(define (sql-table name)
  "The table with this name, as it is now."
  (find-table name))

(define (sql-table-names)
  (sort (hash-table-keys sql-tables)))

(define (find-table name)
  (let ((table (hash-table-ref sql-tables (string-downcase name))))
    (if table
        table
        (sql-error "no such table:" name))))

(define (store-table! name table)
  (hash-table-set! sql-tables (string-downcase name) table))

(define (column-kinds-of name)
  (hash-table-ref sql-kinds (string-downcase name)))

(define (bare-name name)
  "A column's name without its table's: dept for e.dept."
  (let ((dot (string-search name ".")))
    (if dot
        (substring name (+ dot 1))
        name)))

(define (resolve-column name names)
  "Which of the columns `names` (e.dept, d.name, ...) the name in the query means:
the one it matches exactly, or else the one whose part after the table's name it
matches. Case doesn't matter."
  (let ((exact (filter (lambda (n) (string=? (string-downcase n) name)) names)))
    (if (not (null? exact))
        (car exact)
        (let ((ends (filter (lambda (n) (string-ends-with? (string-downcase n) (string-append "." name))) names)))
          (cond ((null? ends) (sql-error "no such column:" name))
                ((> (length ends) 1) (sql-error "ambiguous column name:" name "-- say which table, as" (car ends)))
                (else (car ends)))))))

(define (qualified-table name alias)
  "The table `name` with each column's name made table.column, with the alias as the table, so
that in a join the columns of the tables can't be confused."
  (map (lambda (column) (cons (string-append alias "." (car column)) (cdr column)))
       (find-table name)))

; ---------------------------------------------------------------------------
; 2. The grammar
; ---------------------------------------------------------------------------
; The text of a statement is read by a grammar: a table of rows, in the form lib/parser.lsp
; takes. There are two kinds of row.
;
; A token row, (token kind regular-expression [function]), says what a piece of the text looks
; like: a number, a 'quoted string', a word, a symbol such as <=. The words SQL uses to organize
; a statement (select, from, where ...) are a kind of their own, keyword, so that a name
; can't be one. A token's value is its text, unless there's a function to make it something else:
; the number from the text of a number, the text between the quotes, the word in lower case,
; since names don't depend on case.
;
; A rule row, (rule name (item ...) action), says what a part of the language is made of: a
; text in quotes is a token with that text (in any case), a symbol is a kind of token or another
; rule, and (opt ...), (flag ...), (star ...), (sep-by "," ...), (or ...), and (chain ...)
; are as parser.lsp explains them. Rows with the same name are alternatives, tried in order.
; The action makes the value of the part from the values of the items that have one -- the
; ones that aren't texts -- and the values are trees:
;
;   expressions   (num 3)  (text "ca")  (null)  (col "e.dept")
;                 (add a b)  (subtract a b)  (multiply a b)  (divide a b)  (modulo a b)
;                 (equal a b)  (not-equal a b)  (less a b)  (less-equal a b)  (greater a b)  (greater-equal a b)
;                 (and a b)  (or a b)  (not a)  (negate a)  (is-null a)  (is-not-null a)
;                 (like a pattern)  (not-like a pattern)
;                 (call "upper" a ...)  (aggregate "sum" a)  (aggregate "count" (star))
;   a SELECT      a select-query, with the parts of the query
;   the others    (create name columns if-not-exists)  (drop name if-exists)
;                 (insert name columns source)  (update name assignments where)  (delete name where)
;
; The rules for expressions go from OR, which holds its operands least tightly, to a single number
; or column, which holds them most, as in SQL; (chain x ("+" . add) ...) is x, and more x after a
; + (and so on), grouped from the left, as the tree (add left right): 1 - 2 - 3 is (1 - 2) - 3. A
; parenthesis starts all over, with expression.

(defstruct select-query distinct items from where group-by having order-by limit offset)

(define reserved-words
  '("select" "from" "where" "group" "by" "having" "order" "limit" "offset" "join" "inner" "left"
    "outer" "on" "and" "or" "not" "as" "union" "asc" "desc" "distinct" "values" "set" "into" "is"
    "null" "like" "in" "between" "insert" "update" "delete" "create" "drop" "table" "if" "exists"))

(define aggregate-names '("count" "sum" "avg" "min" "max"))

(define column-types
  '(("integer" . number) ("int" . number) ("real" . number) ("float" . number) ("double" . number)
    ("numeric" . number) ("number" . number) ("text" . text) ("varchar" . text) ("char" . text)
    ("string" . text) ("date" . date)))

(define comparison-heads
  '(("=" . equal) ("<>" . not-equal) ("!=" . not-equal) ("<" . less) ("<=" . less-equal)
    (">" . greater) (">=" . greater-equal)))

; --- What the actions do ---

(define (keyword-regex)
  "A regular expression for any of the reserved words, in any case, as a whole word (so that selection is a name)."
  (string-append "(?i:\\b(?:" (string-join reserved-words "|") ")\\b)"))

(define (text-of-quotes text)
  "The text between the quotes, with each '' in it a single '."
  (string-replace (substring text 1 (- (string-length text) 1)) "''" "'"))

(define (quote-never-ends text)
  (sql-error "a quote that never ends: text goes between single quotes, as 'CA'"))

(define (apply-tail left tail)
  "A sum, and the tail that may follow it (a comparison, IS NULL, LIKE, ...), which is a procedure of the sum."
  (if (null? tail)
      left
      (tail left)))

(define (tail-of-comparison head right)
  (lambda (left) (list head left right)))

(define (negated-if negated tree)
  (if negated (list 'not tree) tree))

(define (in-list left items)
  "left IN (a, b, c) as left = a OR left = b OR left = c."
  (let ((tree (list 'equal left (car items))))
    (dolist (item (cdr items))
      (set! tree (list 'or tree (list 'equal left item))))
    tree))

(define (make-call name arguments)
  "A call of a function or an aggregate: the tree for it."
  (cond ((member name aggregate-names)
         (when (equal? arguments '((star)))
           (unless (equal? name "count")
             (sql-error name "needs a column or expression, not *")))
         (unless (= (length arguments) 1)
           (sql-error name "takes one column or expression"))
         (list 'aggregate name (car arguments)))
        ((assoc name scalar-functions) (cons 'call (cons name arguments)))
        (else (sql-error "unknown function:" name))))

(define (make-select distinct items from where group-by having order-by limit offset)
  (make-select-query :distinct distinct :items items :from from :where where :group-by group-by
                     :having having :order-by order-by :limit limit :offset offset))

(define (make-table-reference name alias)
  "(table name alias): the alias is the name, if there is none."
  (list 'table name (if (null? alias) name alias)))

(define (make-column-definition name type)
  (let ((kind (assoc type column-types)))
    (unless kind
      (sql-error "unknown column type:" type "-- use integer, real, text, or date"))
    (cons name (cdr kind))))

(define (constraints-not-supported name type)
  (sql-error "constraints such as PRIMARY KEY, NOT NULL, and DEFAULT aren't supported"))

; --- The table ---

(define-grammar sql-grammar
  (option ignore-case #t)
  (option error-prefix "sql:")
  (option end-name "the end of the statement")
  (option start script)

  ; The tokens. A text is tried against these in order: a quote with no end must come after the strings.
  (token skip      "\\s+")
  (token number    "\\d+(?:\\.\\d+)?" string->number)
  (token string    "'(?:[^']|'')*'" text-of-quotes)
  (token bad-quote "'" quote-never-ends)
  (token keyword   (keyword-regex) string-downcase)
  (token word      "[A-Za-z_][A-Za-z_0-9]*" string-downcase)
  (token symbol    "<=|>=|<>|!=|[-+*/%=<>(),.;]")

  (describe word "a name")
  (describe number "a number")

  ; Statements, separated by semicolons.
  (rule script ((drop (star ";")) (star statement (drop (or (plus ";") end)))))
  (rule statement (select))
  (rule statement (insert))
  (rule statement (update))
  (rule statement (delete))
  (rule statement (create))
  (rule statement (drop-table))
  (describe statement "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP")

  ; SELECT
  (rule select ("select" (flag "distinct") (sep-by "," select-item) (opt from-clause)
                (opt "where" expression) (opt "group" "by" (sep-by "," expression)) (opt "having" expression)
                (opt "order" "by" (sep-by "," order-item)) (opt "limit" number) (opt "offset" number))
    make-select)
  (rule select-item ("*") (lambda () '(star)))
  (rule select-item (table-name "." "*") (node-builder 'star))
  (rule select-item (expression (opt alias)) (node-builder 'item))
  (rule alias ("as" word))
  (rule alias (word))
  (rule order-item (expression (opt (one-of "asc" "desc")))
    (lambda (expression direction) (list expression (if (null? direction) 'asc (string->symbol direction)))))
  (rule from-clause ("from" table-reference (star join))
    (lambda (first joins) (cons first joins)))
  (rule table-reference (table-name (opt alias)) make-table-reference)
  (rule join (join-kind table-reference "on" expression)
    (lambda (kind table condition) (list 'join kind (cadr table) (caddr table) condition)))
  (rule join-kind ("join") (lambda () 'inner))
  (rule join-kind ("inner" "join") (lambda () 'inner))
  (rule join-kind ("left" (drop (opt "outer")) "join") (lambda () 'left))

  ; Expressions, from the loosest to the tightest.
  (rule expression ((chain conjunction ("or" . or))))
  (rule conjunction ((chain negation ("and" . and))))
  (rule negation ("not" negation) (node-builder 'not))
  (rule negation (comparison))
  (rule comparison (sum (opt comparison-tail)) apply-tail)
  (rule comparison-tail ((one-of "=" "<>" "!=" "<=" ">=" "<" ">") sum)
    (lambda (operator right) (tail-of-comparison (cdr (assoc operator comparison-heads)) right)))
  (rule comparison-tail ("is" (flag "not") "null")
    (lambda (negated) (lambda (left) (list (if negated 'is-not-null 'is-null) left))))
  (rule comparison-tail ((flag "not") "like" sum)
    (lambda (negated pattern) (lambda (left) (list (if negated 'not-like 'like) left pattern))))
  (rule comparison-tail ((flag "not") "between" sum "and" sum)
    (lambda (negated low high)
      (lambda (left)
        (negated-if negated (list 'and (list 'greater-equal left low) (list 'less-equal left high))))))
  (rule comparison-tail ((flag "not") "in" "(" (sep-by "," expression) ")")
    (lambda (negated items) (lambda (left) (negated-if negated (in-list left items)))))
  (rule sum ((chain product ("+" . add) ("-" . subtract))))
  (rule product ((chain unary ("*" . multiply) ("/" . divide) ("%" . modulo))))
  (rule unary ("-" unary) (node-builder 'negate))
  (rule unary (primary))
  (rule primary (number) (node-builder 'num))
  (rule primary (string) (node-builder 'text))
  (rule primary ("(" expression ")"))
  (rule primary ("null") (lambda () '(null)))
  (rule primary ("true") (lambda () '(num 1)))
  (rule primary ("false") (lambda () '(num 0)))
  (rule primary (word "(" call-arguments ")") make-call)
  (rule primary (column))
  (describe unary "a column, number, or text")
  (describe expression "an expression")
  (rule call-arguments ("*") (lambda () '((star))))
  (rule call-arguments ("distinct" expression) (lambda (argument) (sql-error "count(DISTINCT x) isn't supported")))
  (rule call-arguments ((opt (sep-by "," expression))))
  (rule column (word "." word) (lambda (table name) (list 'col (string-append table "." name))))
  (rule column (word) (node-builder 'col))
  (rule table-name (word))
  (describe table-name "a table name")
  (rule column-name (word))
  (describe column-name "a column name")

  ; The other statements
  (rule insert ("insert" "into" table-name (opt "(" (sep-by "," column-name) ")") insert-source)
    (node-builder 'insert))
  (rule insert-source ("values" (sep-by "," value-row)) (node-builder 'values))
  (rule insert-source (select) (node-builder 'query))
  (rule value-row ("(" (sep-by "," expression) ")"))
  (rule update ("update" table-name "set" (sep-by "," assignment) (opt "where" expression))
    (node-builder 'update))
  (rule assignment (column-name "=" expression) cons)
  (rule delete ("delete" "from" table-name (opt "where" expression)) (node-builder 'delete))
  (rule create ("create" "table" (flag "if" "not" "exists") table-name "(" (sep-by "," column-definition) ")")
    (lambda (if-not-exists name columns) (list 'create name columns if-not-exists)))
  (rule column-definition (column-name word (drop (opt "(" number ")")) (drop (or "primary" "not" "unique" "default")))
    constraints-not-supported)
  (rule column-definition (column-name word (drop (opt "(" number ")"))) make-column-definition)
  (rule drop-table ("drop" "table" (flag "if" "exists") table-name)
    (lambda (if-exists name) (list 'drop name if-exists))))

(define (parse-statements text)
  "The statements in the text, separated by semicolons, each as a tree. All of the text is read before any
statement is run, so a mistake in the last statement stops all of them."
  (grammar-parse sql-grammar text))

; ---------------------------------------------------------------------------
; 3. Expressions
; ---------------------------------------------------------------------------
; An expression is evaluated for a whole table at once: the result is a vector
; with a value for each row, made with the vector functions, as the rest of the
; interpreter does it, not by going through the rows. A number in a query is
; a vector of that number repeated. A condition's result is a mask, 1 for each
; row it is true of and 0 for the others, which table-filter uses to keep rows.
;
; NULL is a missing value: nan for numbers, '() for text. A comparison with a missing
; value is false (vector= and the others work that way), as it is in SQL, where it is
; "unknown", which also keeps a row out of a WHERE. A NOT would turn that false into
; true, so NOT is never applied to a result: the condition is turned around instead,
; with NOT (a < b) becoming a >= b, which is false for a missing value as well.

(define (expression? x)
  (and (pair? x) (symbol? (car x))))

(define (subexpressions e)
  "The expressions directly inside e."
  (filter expression? (cdr e)))

(define (map-subexpressions f e)
  "e, with f applied to each expression directly inside it."
  (cons (car e)
        (map (lambda (part) (if (expression? part) (f part) part))
             (cdr e))))

(define (qualify e names)
  "e with each column name replaced by the full name -- table.column -- of the column it means among `names`."
  (if (eq? (car e) 'col)
      (list 'col (resolve-column (cadr e) names))
      (map-subexpressions (lambda (part) (qualify part names)) e)))

(define opposite-heads
  '((equal . not-equal) (not-equal . equal)
    (less . greater-equal) (greater-equal . less) (greater . less-equal) (less-equal . greater)
    (is-null . is-not-null) (is-not-null . is-null) (like . not-like) (not-like . like)))

(define (opposite e)
  "The condition that's true of the rows e is false of (and not unknown): NOT e."
  (let ((turned (assoc (car e) opposite-heads)))
    (cond ((eq? (car e) 'not) (cadr e))
          ((eq? (car e) 'and) (list 'or (opposite (cadr e)) (opposite (caddr e))))
          ((eq? (car e) 'or) (list 'and (opposite (cadr e)) (opposite (caddr e))))
          (turned (cons (cdr turned) (cdr e)))
          (else (list 'equal e (list 'num 0))))))        ; a number used as a condition: false is 0

(define (known values)
  "A mask of the values that aren't missing."
  (vector-not (vector-nan? values)))

(define (column-of table name)
  (if (member name (table-column-names table))
      (table-column table name)
      (sql-error name "can't be used here: it isn't in GROUP BY, inside an aggregate such as sum(), or (after SELECT DISTINCT) in the select list")))

(define (like-regex pattern)
  "The regular expression for a LIKE pattern: % is any text, _ is any one character, anything else is itself.
Upper and lower case are the same."
  (string-append "(?is)^"
                 (regex-replace "_" (regex-replace "%" (regex-quote pattern) ".*") ".")
                 "$"))

(define (like-mask values pattern wanted)
  "A mask of the text in values that does match the LIKE pattern (wanted is 1) or doesn't (wanted is 0).
Missing values are in neither."
  (let ((regex (like-regex pattern)))
    (vector-map (lambda (s)
                  (cond ((not (string? s)) 0)
                        ((regex-match regex s) wanted)
                        (else (- 1 wanted))))
                values)))

(define comparison-functions
  (list (cons 'equal vector=) (cons 'less vector<) (cons 'less-equal vector<=)
        (cons 'greater vector>) (cons 'greater-equal vector>=)))

(define arithmetic-functions
  (list (cons 'add vector-add) (cons 'subtract vector-sub) (cons 'multiply vector-mul) (cons 'modulo mod)))

(define (evaluate e table)
  "The vector of the values of the expression e, for each row of the table."
  (let ((rows (table-row-count table))
        (arithmetic (assoc (car e) arithmetic-functions))
        (comparison (assoc (car e) comparison-functions)))
    (cond (arithmetic ((cdr arithmetic) (evaluate (cadr e) table) (evaluate (caddr e) table)))
          (comparison ((cdr comparison) (evaluate (cadr e) table) (evaluate (caddr e) table)))
          (else
           (case (car e)
             ((num text) (make-vector rows (cadr e)))
             ((null) (make-vector rows nan))
             ((col) (column-of table (cadr e)))
             ((negate) (vector-mul (evaluate (cadr e) table) -1))
             ((divide)
              (let ((top (evaluate (cadr e) table))
                    (bottom (evaluate (caddr e) table)))
                (vector-where (vector= bottom 0) nan (vector-div top bottom))))      ; x / 0 is NULL
             ((not-equal)
              (let ((a (evaluate (cadr e) table))
                    (b (evaluate (caddr e) table)))
                (vector-and (vector/= a b) (known a) (known b))))
             ((and) (vector-and (evaluate (cadr e) table) (evaluate (caddr e) table)))
             ((or) (vector-or (evaluate (cadr e) table) (evaluate (caddr e) table)))
             ((not) (evaluate (opposite (cadr e)) table))
             ((is-null) (vector-nan? (evaluate (cadr e) table)))
             ((is-not-null) (known (evaluate (cadr e) table)))
             ((like) (like-mask (evaluate (cadr e) table) (like-pattern (caddr e)) 1))
             ((not-like) (like-mask (evaluate (cadr e) table) (like-pattern (caddr e)) 0))
             ((call) (apply (cdr (assoc (cadr e) scalar-functions))
                            (map (lambda (argument) (evaluate argument table)) (cddr e))))
             ((aggregate) (sql-error (string-append (cadr e) "()") "can't be used here: aggregates are for the select list, HAVING, and ORDER BY"))
             (else (sql-error "can't evaluate" e)))))))

(define (like-pattern e)
  (if (eq? (car e) 'text)
      (cadr e)
      (sql-error "LIKE needs a pattern in quotes, such as 'A%'")))

; --- The functions ---

(define (on-text f missing)
  "A function of a vector that applies f to each piece of text in it, and gives `missing` for the others."
  (lambda (values)
    (vector-map (lambda (s) (if (string? s) (f s) missing)) values)))

(define (round-half-away values digits)
  "Rounds as people do, with halves going away from zero (the vector-round function rounds them to even)."
  (let* ((scale (expt 10 digits))
         (magnitude (floor (+ (* (vector-abs values) scale) 0.5))))
    (vector-div (vector-mul (vector-where (vector< values 0) -1 1) magnitude) scale)))

(define (coalesce first . others)
  "The first of the vectors that has a value, for each row."
  (let ((result first))
    (dolist (next others)
      (set! result (vector-where (vector-nan? result) next result)))
    result))

(define scalar-functions
  (list (cons "upper" (on-text string-upcase '()))
        (cons "lower" (on-text string-downcase '()))
        (cons "length" (on-text string-length nan))
        (cons "abs" vector-abs)
        (cons "round" (lambda (values . digits)
                        (round-half-away values (if (null? digits) 0 (vector-ref (car digits) 0)))))
        (cons "coalesce" coalesce)
        (cons "date" (on-text string->date '()))))

; ---------------------------------------------------------------------------
; 4. Groups
; ---------------------------------------------------------------------------
; GROUP BY, or an aggregate such as sum() in the select list, makes one row from
; each group of rows. table-group-by does that, given the columns that tell
; the groups apart and what to find in each: we make columns of everything it
; needs (the group expressions, and what each aggregate adds up), and give them
; names it can use: %g0, %g1, ... for the groups, %a0, %a1, ... for the
; aggregates, and the like.
;
; After that the select list, HAVING, and ORDER BY are expressions of the new
; table, in which each group expression and each aggregate is now a column. So
; they're rewritten: in  SELECT dept, SUM(salary) * 12 ... GROUP BY dept,  dept
; becomes (col "e.dept") -- the group column keeps its name -- and SUM(salary)
; becomes (col "%a0"). A column that is in neither is not in the new table, which
; is the error SQL gives for it.

(define (aggregates-in e)
  "The aggregate calls in the expression, each once."
  (if (eq? (car e) 'aggregate)
      (list e)
      (remove-duplicates (apply append (map aggregates-in (subexpressions e))))))

(define (all-aggregates-in expressions)
  (remove-duplicates (apply append (map aggregates-in expressions))))

(define (index-of item items position)
  "Where item is in the list (from `position`, the place of the first), or #f."
  (cond ((null? items) #f)
        ((equal? item (car items)) position)
        (else (index-of item (cdr items) (+ position 1)))))

(define (group-name expression index)
  (if (eq? (car expression) 'col)
      (cadr expression)
      (format "%g{}" index)))

(define (aggregate-name index)
  (format "%a{}" index))

(define (replace-groups e group-expressions aggregates)
  "e, for the grouped table: with each group expression and each aggregate in it replaced by its column."
  (let ((group (index-of e group-expressions 0))
        (aggregate (index-of e aggregates 0)))
    (cond (group (list 'col (group-name e group)))
          (aggregate (list 'col (aggregate-name aggregate)))
          (else (map-subexpressions (lambda (part) (replace-groups part group-expressions aggregates)) e)))))

(define (aggregate-of-nothing aggregates)
  "The one row an aggregate query gives when there are no rows at all: 0 for count, and NULL for the others."
  (table-from-rows
   (list (map (lambda (aggregate) (if (equal? (cadr aggregate) "count") 0 nan)) aggregates))
   (loop for i from 0 below (length aggregates) collect (aggregate-name i))))

(define table-group-by-functions
  '(("sum" . sum) ("avg" . mean) ("min" . min) ("max" . max)))

(define (grouped-table rows group-expressions aggregates)
  "The table with a row for each group of the rows: the group columns, then %a0, %a1, ... the aggregates.
With no group expressions, all of the rows are one group."
  (if (and (null? group-expressions) (= (table-row-count rows) 0))
      (aggregate-of-nothing aggregates)
      (let ((work rows)                                    ; the rows, and the columns table-group-by needs
            (keys '())                                     ; the names of the group columns
            (specs '())                                    ; what table-group-by is to find
            (sums '()))                                    ; (sum-column . count-column) for each sum
        (loop for expression in group-expressions
              for i from 0
              do (let ((name (group-name expression i)))
                   (unless (member name (table-column-names work))
                     (set! work (table-add-column work name (evaluate expression rows))))
                   (set! keys (append keys (list name)))))
        (when (null? keys)
          (set! work (table-add-column work "%all" (make-vector (table-row-count rows) 0)))
          (set! keys (list "%all")))
        (loop for aggregate in aggregates
              for i from 0
              do (let ((name (aggregate-name i))
                       (function (cadr aggregate))
                       (argument (caddr aggregate))
                       (values-name (format "%v{}" i)))
                   (if (eq? (car argument) 'star)
                       (set! specs (append specs (list (list name 'count))))
                       (let ((values (evaluate argument rows)))
                         (cond ((equal? function "count")      ; count(x) counts the rows where x isn't missing
                                (set! work (table-add-column work values-name (known values)))
                                (set! specs (append specs (list (list name 'sum values-name)))))
                               (else
                                (set! work (table-add-column work values-name values))
                                (set! specs (append specs (list (list name (cdr (assoc function table-group-by-functions)) values-name))))
                                (when (equal? function "sum")  ; the sum of nothing but missing values is NULL, not 0
                                  (let ((present-name (format "%p{}" i)))
                                    (set! work (table-add-column work present-name (known values)))
                                    (set! specs (append specs (list (list (format "%c{}" i) 'sum present-name))))
                                    (set! sums (append sums (list (cons name (format "%c{}" i)))))))))))))
        (let ((grouped (table-group-by work keys specs)))
          (dolist (sum sums)
            (set! grouped (table-add-column grouped (car sum)
                                            (vector-where (vector> (table-column grouped (cdr sum)) 0)
                                                          (table-column grouped (car sum))
                                                          nan))))
          (if (null? sums)
              grouped
              (table-drop-columns grouped (map cdr sums)))))))

; ---------------------------------------------------------------------------
; 5. SELECT
; ---------------------------------------------------------------------------
; The steps of a query, in the order SQL means them:
;
;   FROM (and JOIN)   the table to start with, its columns named table.column
;   WHERE             keep the rows the condition is true of     table-filter
;   GROUP BY, HAVING  one row for each group; keep some          table-group-by, table-filter
;   SELECT            a column for each item in the list          evaluate
;   DISTINCT          one of each different row                   table-group-by
;   ORDER BY          sort                                        table-sort
;   LIMIT, OFFSET     keep some of the rows                       table-slice

(define (join-key-pairs condition left-names right-names)
  "The columns to join on, from a condition that is equalities between the columns of the two tables
joined by AND: a list of (left-column . right-column)."
  (cond ((eq? (car condition) 'and)
         (append (join-key-pairs (cadr condition) left-names right-names)
                 (join-key-pairs (caddr condition) left-names right-names)))
        ((and (eq? (car condition) 'equal)
              (eq? (car (cadr condition)) 'col)
              (eq? (car (caddr condition)) 'col))
         (let ((a (cadr (cadr condition)))
               (b (cadr (caddr condition))))
           (cond ((and (member a left-names) (member b right-names)) (list (cons a b)))
                 ((and (member b left-names) (member a right-names)) (list (cons b a)))
                 (else (sql-error "each equality in ON must compare a column of one table with a column of the other")))))
        (else (sql-error "ON must be equalities between columns, joined by AND; this program joins on equal columns only"))))

(define (join-tables left right kind condition)
  "The tables joined on the equalities in the condition. table-join joins on columns with the same name
in both tables, so each pair of columns is copied to new columns with a name in common (%k0, %k1, ...) to join on, and
those are dropped afterward. A missing value is never equal to anything in SQL, as table-join takes it
to be, so the right table's rows with a missing key are left out: no row would match them."
  (let* ((left-names (table-column-names left))
         (right-names (table-column-names right))
         (pairs (join-key-pairs (qualify condition (append left-names right-names)) left-names right-names))
         (keys (loop for i from 0 below (length pairs) collect (format "%k{}" i))))
    (loop for pair in pairs
          for key in keys
          do (set! left (table-add-column left key (table-column left (car pair))))
             (set! right (table-add-column right key (table-column right (cdr pair))))
             (set! right (table-filter right (known (table-column right key)))))
    (table-drop-columns (table-join left right keys kind) keys)))

(define (build-source from)
  "The table the query starts from: the first table in FROM, joined to the others. With no FROM, a table of one row
and a column no one can name, so that SELECT 1 + 2 has a row to be."
  (if (null? from)
      (make-table "%" (vector 0))
      (let ((source (qualified-table (cadr (car from)) (caddr (car from)))))
        (dolist (join (cdr from))
          (destructuring-bind (kind name alias condition) (cdr join)
            (let ((right (qualified-table name alias)))
              (when (not (null? (filter (lambda (n) (member n (table-column-names source))) (table-column-names right))))
                (sql-error alias "is the name of two tables in the query: give one of them another name, as in FROM" name "AS other"))
              (set! source (join-tables source right kind condition)))))
        source)))

(define (star-columns item names)
  "The columns that * or table.* means."
  (if (null? (cdr item))
      (begin (when (equal? names '("%")) (sql-error "* needs a FROM"))
             names)
      (let ((prefix (string-append (cadr item) ".")))
        (let ((these (filter (lambda (n) (string-starts-with? (string-downcase n) prefix)) names)))
          (when (null? these) (sql-error "no such table:" (cadr item)))
          these))))

(define (expand-items items names)
  "The select list as a list of (expression name): the name of each column of the result, with * and table.*
replaced by the columns they mean, and the columns in the expressions named in full."
  (apply append
         (map (lambda (item)
                (if (eq? (car item) 'star)
                    (map (lambda (n)                       ; a column of * is named for itself, unless two have the same name
                           (list (list 'col n)
                                 (if (and (null? (cdr item))
                                          (> (length (filter (lambda (other) (string=? (bare-name other) (bare-name n))) names)) 1))
                                     n
                                     (bare-name n))))
                         (star-columns item names))
                    (let ((qualified (qualify (cadr item) names))
                          (alias (caddr item)))
                      (list (list qualified
                                  (cond ((not (null? alias)) alias)
                                        ((eq? (car qualified) 'col) (bare-name (cadr qualified)))
                                        (else (expression->text (cadr item)))))))))
              items)))

(define (unique-names names)
  "The names, with later copies of the same name made different: id, id_2, id_3."
  (let ((seen (make-hash-table)))
    (map (lambda (name)
           (let ((count (+ 1 (hash-table-ref seen name 0))))
             (hash-table-set! seen name count)
             (if (= count 1) name (format "{}_{}" name count))))
         names)))

; The names of the columns of a result that is not just a column, such as  sum(salary) * 12, are the text of the expression.

(define operator-texts
  '((add . "+") (subtract . "-") (multiply . "*") (divide . "/") (modulo . "%")
    (equal . "=") (not-equal . "<>") (less . "<") (less-equal . "<=") (greater . ">") (greater-equal . ">=")
    (and . "and") (or . "or") (like . "like") (not-like . "not like")))

(define (precedence e)
  "How tightly the expression's operator holds its operands: more is tighter."
  (case (car e)
    ((or) 1)
    ((and) 2)
    ((not) 3)
    ((equal not-equal less less-equal greater greater-equal like not-like is-null is-not-null) 4)
    ((add subtract) 5)
    ((multiply divide modulo) 6)
    ((negate) 7)
    (else 9)))

(define (operand->text e least)
  "The expression as text, in parentheses if it holds its operands less tightly than `least`."
  (if (>= (precedence e) least)
      (expression->text e)
      (string-append "(" (expression->text e) ")")))

(define (expression->text e)
  "The expression written out, as SQL: sum(salary) * 12."
  (let ((tightness (precedence e)))
    (case (car e)
      ((num) (number->string (cadr e)))
      ((text) (string-append "'" (cadr e) "'"))
      ((null) "null")
      ((col) (cadr e))
      ((star) "*")
      ((negate) (string-append "-" (operand->text (cadr e) tightness)))
      ((not) (string-append "not " (operand->text (cadr e) tightness)))
      ((is-null) (string-append (operand->text (cadr e) 5) " is null"))
      ((is-not-null) (string-append (operand->text (cadr e) 5) " is not null"))
      ((call aggregate) (format "{}({})" (cadr e) (string-join (map expression->text (cddr e)) ", ")))
      (else
       (format "{} {} {}"
               (operand->text (cadr e) (if (= tightness 4) 5 tightness))      ; a - b - c is (a - b) - c; a < b < c isn't SQL
               (cdr (assoc (car e) operator-texts))
               (operand->text (caddr e) (+ tightness 1)))))))

(define (distinct-rows result)
  "The result with one of each different row (grouping by every column, and dropping the count)."
  (table-drop-columns (table-group-by result (map car result) (list (list "%count" 'count)))
                      (list "%count")))

(define (order-column e names)
  "An ORDER BY number, as ORDER BY 2, means the column of the result in that place."
  (if (and (eq? (car e) 'num) (integer? (cadr e)))
      (if (<= 1 (cadr e) (length names))
          (list 'col (list-ref names (- (cadr e) 1)))
          (sql-error "ORDER BY" (cadr e) "is not a column of the result"))
      e))

(define (order-rows result extended orders)
  "The result sorted by the orders, a list of (expression asc-or-desc) to evaluate for the rows of `extended`,
which is the result and the columns it was made from. table-sort sorts by columns and keeps rows that tie in
their order, so sorting by each of the orders from the last to the first, as separate sorts, gives the order of all."
  (let ((sorted result)
        (key-names (loop for i from 0 below (length orders) collect (format "%o{}" i))))
    (loop for order in orders
          for key in key-names
          do (set! sorted (table-add-column sorted key (evaluate (car order) extended))))
    (loop for order in (reverse orders)
          for key in (reverse key-names)
          do (set! sorted (table-sort sorted (list key) (eq? (cadr order) 'desc))))
    (table-drop-columns sorted key-names)))

(define (limit-rows table limit offset)
  (let ((start (if (null? offset) 0 offset)))
    (cond ((null? limit) (if (= start 0) table (table-slice table start)))
          (else (table-slice table start (+ start limit))))))

(define (run-select q)
  (let* ((source (build-source (select-query-from q)))
         (names (table-column-names source))
         ; WHERE
         (where (select-query-where q))
         (rows (if (null? where)
                   source
                   (table-filter source (evaluate (qualify where names) source))))
         ; the expressions of the query, named in full: the select list, ORDER BY (in which the names
         ; of the select list's columns are also names), GROUP BY, and HAVING
         (items (expand-items (select-query-items q) names))
         (item-names (unique-names (map cadr items)))
         (orders (map (lambda (order)
                        (list (qualify (order-column (car order) item-names) (append item-names names))
                              (cadr order)))
                      (select-query-order-by q)))
         (group-expressions (map (lambda (e) (qualify e names)) (select-query-group-by q)))
         (having (if (null? (select-query-having q)) '() (qualify (select-query-having q) names)))
         ; GROUP BY and the aggregates
         (aggregates (all-aggregates-in (append (map car items) (map car orders) (if (null? having) '() (list having)))))
         (grouped? (or (not (null? group-expressions)) (not (null? aggregates))))
         (rewrite (lambda (e) (if grouped? (replace-groups e group-expressions aggregates) e)))
         (groups (if grouped? (grouped-table rows group-expressions aggregates) rows))
         ; HAVING
         (kept (if (null? having) groups (table-filter groups (evaluate (rewrite having) groups))))
         ; SELECT
         (result (map (lambda (item name) (cons name (evaluate (rewrite (car item)) kept)))
                      items item-names))
         ; DISTINCT
         (result (if (select-query-distinct q) (distinct-rows result) result))
         ; ORDER BY: by the columns of the result, or the columns it was made from
         (extended (if (select-query-distinct q)
                       result
                       (append result (filter (lambda (column) (not (member (car column) item-names))) kept))))
         (result (if (null? orders)
                     result
                     (order-rows result extended (map (lambda (order) (list (rewrite (car order)) (cadr order))) orders)))))
    ; LIMIT, OFFSET
    (limit-rows result (select-query-limit q) (select-query-offset q))))

; ---------------------------------------------------------------------------
; 6. The other statements, and ways to run them
; ---------------------------------------------------------------------------

(define (rows-word count)
  (format "{} {}" count (if (= count 1) "row" "rows")))

(define (run-create name columns if-not-exists)
  (cond ((hash-table-ref sql-tables (string-downcase name))
         (if if-not-exists
             (format "table {} is already there" name)
             (sql-error "table" name "already exists")))
        (else
         (hash-table-set! sql-tables (string-downcase name)
                          (map (lambda (column) (cons (car column) (vector))) columns))
         (hash-table-set! sql-kinds (string-downcase name) (map cdr columns))
         (format "table {} created" name))))

(define (run-drop name if-exists)
  (cond ((hash-table-ref sql-tables (string-downcase name))
         (hash-table-remove! sql-tables (string-downcase name))
         (hash-table-remove! sql-kinds (string-downcase name))
         (format "table {} dropped" name))
        (if-exists (format "there is no table {}" name))
        (else (sql-error "no such table:" name))))

(define (as-kind kind value column)
  "A value for a column of this kind: a missing one is nan in a column of numbers and '() in the others, and a value
of the wrong kind is an error."
  (cond ((missing-value? value) (if (eq? kind 'number) nan '()))
        ((and (eq? kind 'number) (not (number? value))) (sql-error "column" column "holds numbers, not" value))
        ((and (eq? kind 'text) (not (string? value))) (sql-error "column" column "holds text, not" value))
        (else value)))

(define (columns->rows table)
  "A table as a list of rows, each a list of values."
  (apply map list (map (lambda (column) (vector->list (cdr column))) table)))

(define (rows-to-insert source)
  "The rows an INSERT adds, as lists of values, from its VALUES or SELECT."
  (if (eq? (car source) 'values)
      (map (lambda (row)
             (map (lambda (e)
                    (vector-ref (evaluate (qualify e '("%")) (make-table "%" (vector 0))) 0))
                  row))
           (cadr source))
      (let ((result (run-select (cadr source))))
        (if (= (table-row-count result) 0) '() (columns->rows result)))))

(define (run-insert name columns source)
  (let* ((table (find-table name))
         (table-names (table-column-names table))
         (kinds (column-kinds-of name))
         (targets (if (null? columns)
                      table-names
                      (map (lambda (c) (resolve-column c table-names)) columns)))
         (rows (rows-to-insert source)))
    (dolist (row rows)
      (unless (= (length row) (length targets))
        (sql-error "a row has" (length row) "values for" (length targets) "columns")))
    (unless (null? rows)
      (store-table! name
                    (table-append table
                                  (table-from-rows
                                   (map (lambda (row)      ; each row in the table's order, with NULL for the columns not given
                                          (map (lambda (column kind)
                                                 (let ((place (index-of column targets 0)))
                                                   (as-kind kind (if place (list-ref row place) nan) column)))
                                               table-names kinds))
                                        rows)
                                   table-names))))
    (format "{} added" (rows-word (length rows)))))

(define (rows-mask where view)
  "The mask of the rows of the table (with its columns named table.column, as `view`) that a WHERE keeps: all, with none."
  (if (null? where)
      (make-vector (table-row-count view) 1)
      (evaluate (qualify where (table-column-names view)) view)))

(define (run-update name assignments where)
  (let* ((table (find-table name))
         (view (qualified-table name name))
         (mask (rows-mask where view))
         (kinds (column-kinds-of name))
         (updated table))
    (dolist (assignment assignments)                       ; all of them see the values from before the update
      (let* ((column (resolve-column (car assignment) (table-column-names table)))
             (new (evaluate (qualify (cdr assignment) (table-column-names view)) view)))
        (set! updated (table-add-column updated column (vector-where mask new (table-column table column))))))
    (store-table! name updated)
    (format "{} changed" (rows-word (vector-sum mask)))))

(define (run-delete name where)
  (let* ((table (find-table name))
         (mask (rows-mask where (qualified-table name name))))
    (store-table! name (table-filter table (vector-not mask)))
    (format "{} deleted" (rows-word (vector-sum mask)))))

(define (execute statement)
  "Runs one parsed statement: a table for a SELECT, a sentence for the others."
  (if (select-query? statement)
      (run-select statement)
      (case (car statement)
        ((create) (apply run-create (cdr statement)))
        ((drop) (apply run-drop (cdr statement)))
        ((insert) (apply run-insert (cdr statement)))
        ((update) (apply run-update (cdr statement)))
        ((delete) (apply run-delete (cdr statement)))
        (else (sql-error "can't run" statement)))))

(define (run-sql text)
  "The results of the statements in the text, in order."
  (let ((results '()))
    (dolist (statement (parse-statements text))
      (set! results (append results (list (execute statement)))))
    results))

(define (sql text)
  "Runs the statements in the text; the result of the last: a table for a SELECT, a sentence for the others."
  (let ((results (run-sql text)))
    (if (null? results)
        "nothing to do"
        (car (last results)))))

(define (show-result result)
  (if (string? result)
      (display (format "{}\n" result))
      (begin
        (display-table result :max-rows 200)
        (display (format "({})\n" (rows-word (table-row-count result)))))))

(define (show-sql text)
  "Runs the statements in the text and prints the result of each."
  (dolist (result (run-sql text))
    (show-result result)))

(define (sql-repl)
  "SQL at a prompt: type a statement, ending with ;  -- it can go on for several lines. quit; or the end of input ends it."
  (display "SQL. End a statement with a semicolon. quit; leaves.\n")
  (let ((text "")
        (line ""))
    (while line
      (set! line (read-line (if (equal? text "") "sql> " "  ... ")))
      (cond ((not line) '())
            ((and (equal? text "") (member (string-downcase (string-trim line)) '("quit;" "quit" "exit;" "exit")))
             (set! line #f))
            (else
             (set! text (string-append text line "\n"))
             (when (string-ends-with? (string-trim text) ";")
               (catch-error (show-sql text)
                            (message) (display (format "Error: {}\n" message)))
               (set! text "")))))))
