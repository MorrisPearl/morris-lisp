; loop.lsp
; ========
; The Common Lisp loop macro (most of it). Every new environment loads this
; file after macros_init.lsp, so loop is always available.
;
; A loop is written as a list of CLAUSES. They read a little like English,
; and each says one thing: what to step through, what to do each time, when
; to stop, what to give back.
;
;   (loop for i from 1 to 5 collect (* i i))          ; => (1 4 9 16 25)
;   (loop for x in '(3 1 4 1 5) sum x)                ; => 14
;   (loop for x in prices when (> x 100) collect x)   ; the prices over 100
;   (loop for month from 1 to 360
;         for balance = 200000 then (* balance 1.005)
;         until (> balance 300000)
;         finally (return month))                     ; months till the balance passes 300,000
;
; THE CLAUSES
;
;   Stepping (for or as; put these before the clauses that do things)
;     for x in list             x is each element         for x on list   x is each tail
;     for x across vector       x is each element
;     for i from 1 to 10 [by 2] counting (also upto, below, downto, above,
;                               downfrom; for i below 10 starts at 0)
;     for x = a then b          x is a the first time, then b each time
;     for x = a                 x is a again on every pass
;     for k being the hash-keys of table [using (hash-value v)]
;     for v being the hash-values of table [using (hash-key k)]
;     repeat n                  go round n times
;     For a list of lists, x can be a pattern: for (a b) in pairs, or for
;     (key . value) in an association list.
;
;   Variables
;     with x = a [and y = b]    variables that get their value once, at the start
;
;   Ending the loop
;     while test / until test   stop when the test fails / succeeds
;     always test / never test  return #f at once if the test fails / succeeds;
;                               otherwise the loop returns #t
;     thereis test              return the test's value at once if it's true;
;                               otherwise the loop returns #f
;
;   Doing things
;     do form...                evaluate the forms
;     return value              leave the loop, returning value
;     collect x / append list   the loop returns a list of the x's (or of all the
;                               elements of the lists)
;     sum x / count test        the loop returns the total / how many were true
;     maximize x / minimize x   the loop returns the largest / smallest
;         each of these can end with  into var  to accumulate in the variable
;         var instead. The loop then returns nothing in particular; use var
;         in a finally.
;     when test clause [and clause]... [else clause [and clause]...] [end]
;     unless test clause [and clause]...        (if works like when)
;
;   Before and after
;     initially form...         evaluate the forms before the first pass
;     finally form...           evaluate the forms after the last pass (not after return)
;     named name                gives the loop a name, for  (return-from name value)
;
; The words can also be written collecting, appending, summing, counting,
; maximizing, minimizing, and doing, as in Common Lisp.
;
; WHAT IS DIFFERENT FROM COMMON LISP
;   - Booleans are #t and #f, not t and nil: always, never, and thereis
;     return them. maximize and minimize return () if they never ran.
;   - Not supported: for ... and for ... (stepping in parallel), the variable
;     it, by for in and on, being the elements of, type declarations,
;     loop-finish, and multiple values.
;   - return, and the return-from macro below, are for loop. Unlike in Common
;     Lisp they aren't available in dolist, do, and while.
;   - Clauses happen in the order written. As in Common Lisp, write the
;     stepping clauses (for, repeat) before the clauses that do things.
;
; HOW IT WORKS
; loop is a macro: it turns the clauses into ordinary code, once, the first
; time the loop is run. For  (loop for x in prices when (> x 100) collect x)
; that code is, with the names of the hidden variables made shorter:
;
;   (let* ((keep-going #t) (rest prices) (x '())    ; the variables
;          (result '()) (tail '()) (temp '()))
;     (while keep-going
;       (if (pair? rest)                            ; a test: are there more?
;           (begin (set! x (car rest))              ; the next element
;                  (set! rest (cdr rest))
;                  (if (> x 100)                    ; the when
;                      (begin (set! temp (list x))  ; the collect adds to the end of result
;                             (if (null? result) (set! result temp) (set-cdr! tail temp))
;                             (set! tail temp))))
;           (set! keep-going #f)))                  ; no more: stop
;     result)                                       ; what the loop returns
;
; Each pass does the actions of the clauses in order. A stepping clause is
; a test (is there another element?) followed by setting its variable; a test
; that fails stops the loop and skips the rest of that pass, which is why the
; rest of the pass is inside the if. The hidden variables have names made by
; gensym, so they can't clash with yours. To see the code for any loop, use
;   (print-macroexpansion '(loop ...))
; A loop that uses return (or always, never, thereis) is wrapped in a catch,
; and return throws to it.

; ---------------------------------------------------------------------
; Small functions the expander uses. Their names start with loop-- so they
; stay out of the way of your own.
; ---------------------------------------------------------------------

; Words that mean the same as another word, so (loop for x in xs collecting x)
; and (loop as x in xs collect x) work.
(define loop--aliases
  '((as . for) (doing . do) (if . when)
    (collecting . collect) (appending . append) (nconc . append) (nconcing . append)
    (summing . sum) (counting . count) (maximizing . maximize) (minimizing . minimize)
    (upfrom . from) (upto . to) (hash-keys . hash-key) (hash-values . hash-value)))

(define (loop--word x)
  "The clause word that x stands for: collecting means collect, and so on.
Anything that isn't one of those is returned as it is."
  (let ((entry (assoc x loop--aliases)))
    (if entry (cdr entry) x)))

(define (loop--mentions? tree words)
  "Whether any of the symbols in the list words appears anywhere in tree."
  (cond ((pair? tree) (or (loop--mentions? (car tree) words)
                          (loop--mentions? (cdr tree) words)))
        ((symbol? tree) (if (member tree words) #t #f))
        (else #f)))

(define (loop--leading-forms rest)
  "The forms at the start of rest: the ones that are lists, not clause words."
  (if (and (pair? rest) (pair? (car rest)))
      (cons (car rest) (loop--leading-forms (cdr rest)))
      '()))

(define (loop--after-forms rest)
  "What is left of rest after its leading forms."
  (if (and (pair? rest) (pair? (car rest)))
      (loop--after-forms (cdr rest))
      rest))

; A variable in a for clause can be a pattern, to take a list apart:
; (a b) matches a two-element list, and (key . value) matches a pair.
; A () in a pattern is a place to ignore.

(define (loop--pattern-vars pattern)
  "The variables in a pattern, as a list."
  (cond ((null? pattern) '())
        ((pair? pattern) (append (loop--pattern-vars (car pattern))
                                 (loop--pattern-vars (cdr pattern))))
        (else (list pattern))))

(define (loop--first x)
  "The first element of x, or () if x isn't a pair: a pattern with more
variables than there are elements gives the extra ones the value ()."
  (if (pair? x) (car x) '()))

(define (loop--rest x)
  "What follows the first element of x, or () if x isn't a pair."
  (if (pair? x) (cdr x) '()))

(define (loop--pattern-setters pattern value)
  "Forms that set! each variable in the pattern to its part of value."
  (cond ((null? pattern) '())
        ((pair? pattern) (append (loop--pattern-setters (car pattern) `(loop--first ,value))
                                 (loop--pattern-setters (cdr pattern) `(loop--rest ,value))))
        (else (list `(set! ,pattern ,value)))))

(define (loop--nest actions keep-going)
  "Turn the actions of one pass round the loop into code. An action is
(do . form) or (test . form). A test that fails ends the loop, and skips
the rest of that pass, so the actions after a test go inside an if."
  (cond ((null? actions) '())
        ((eq? (caar actions) 'test)
         (list `(if ,(cdar actions)
                    (begin ,@(loop--nest (cdr actions) keep-going))
                    (set! ,keep-going #f))))
        (else (cons (cdar actions)
                    (loop--nest (cdr actions) keep-going)))))

; Accumulating: collect, append, sum, count, maximize, minimize. An
; accumulator is described by an entry, (variable kind tail scratch), where
; the kind says what's being accumulated (list, number, maximize, or
; minimize). For a list, tail is a variable that points at its last pair. A
; list or a maximize or minimize has a scratch variable, to hold the new
; cell or value for a moment (so that no scope has to be made on every pass).

(define (loop--kind word)
  (case word
    ((collect append) 'list)
    ((sum count) 'number)
    (else word)))

(define (loop--list-add entry item)
  "Code that adds the value of the expression item to the end of the list
that entry describes. The list is kept in order all the time, and the tail
pointer makes each add quick, so an `into` variable is usable at any point."
  (let ((head (car entry))
        (tail (list-ref entry 2))
        (cell (list-ref entry 3)))
    `(begin (set! ,cell (list ,item))
            (if (null? ,head) (set! ,head ,cell) (set-cdr! ,tail ,cell))
            (set! ,tail ,cell))))

(define (loop--extremum entry better expression)
  "Code that sets the accumulator's variable to the value of expression, if
the variable is still () or the value is better (> for maximize, < for
minimize)."
  (let ((variable (car entry))
        (value (list-ref entry 3)))
    `(begin (set! ,value ,expression)
            (if (or (null? ,variable) (,better ,value ,variable))
                (set! ,variable ,value)))))

(define (loop--accumulate word entry expression)
  "The code for one collect, append, sum, count, maximize, or minimize clause."
  (let ((variable (car entry)))
    (case word
      ((collect) (loop--list-add entry expression))
      ((append) (let ((item (gensym "item")))
                  `(dolist (,item ,expression) ,(loop--list-add entry item))))
      ((sum) `(set! ,variable (+ ,variable ,expression)))
      ((count) `(if ,expression (set! ,variable (+ ,variable 1))))
      ((maximize) (loop--extremum entry '> expression))
      (else (loop--extremum entry '< expression)))))

; ---------------------------------------------------------------------
; The expander
; ---------------------------------------------------------------------

(define (loop--expand clauses)
  "The code for (loop clause...), when the clauses start with a word.
It reads the clauses one after another. Each adds a little to what is built
up in the variables just below, and at the end assemble puts it together."

  ; What the clauses add up to:
  (define block-name 'loop-nil)     ; what return and return-from throw to
  (define bindings '())             ; (variable init) for the let*, newest first
  (define actions '())              ; what each pass does, newest first (see loop--nest)
  (define initially-forms '())
  (define finally-forms '())
  (define accumulators '())         ; entries, as described above, newest first
  (define default-accumulator '())  ; the variable holding what the loop returns
  (define result '())               ; (form), if always/never/thereis chose what to return
  (define first-pass '())           ; the flag that  for x = a then b  needs
  (define keep-going (gensym "keep-going"))
  (define uses-block? (loop--mentions? clauses '(return return-from)))

  (define (expect rest what)
    (if (pair? rest)
        (car rest)
        (error "loop: the clauses ended where" what "was expected")))

  (define (bind! variable init)
    (push (list variable init) bindings))

  (define (once! expression name)
    ; Something evaluated once, before the loop starts, and used on every
    ; pass: a number is used as it is, and anything else is kept in a variable.
    (cond ((number? expression) expression)
          ((null? expression) expression)
          (else (let ((variable (gensym name)))
                  (bind! variable expression)
                  variable))))

  (define (bind-pattern! pattern)
    (dolist (variable (loop--pattern-vars pattern))
      (bind! variable ''())))

  (define (do! form)
    (push (cons 'do form) actions))

  (define (test! form)
    (push (cons 'test form) actions))

  (define (set-variables! pattern value)
    (dolist (form (loop--pattern-setters pattern value))
      (do! form)))

  ; --- accumulating ---------------------------------------------------

  (define (new-accumulator name kind)
    (define tail (if (eq? kind 'list) (gensym "tail") '()))
    (define scratch (if (eq? kind 'number) '() (gensym "temp")))
    (bind! name (if (eq? kind 'number) 0 ''()))
    (if (not (null? tail)) (bind! tail ''()))
    (if (not (null? scratch)) (bind! scratch ''()))
    (define entry (list name kind tail scratch))
    (push entry accumulators)
    entry)

  (define (accumulator variable kind)
    ; The entry for the variable, made the first time it's needed. With no
    ; variable (no into) it's the loop's own, which the loop returns.
    (if (and (null? variable) (null? default-accumulator))
        (set! default-accumulator (gensym "result")))
    (define name (if (null? variable) default-accumulator variable))
    (define entry (assoc name accumulators))
    (cond ((not entry) (new-accumulator name kind))
          ((eq? (list-ref entry 1) kind) entry)
          (else (error "loop: can't accumulate a" kind "and a" (list-ref entry 1)
                       "in the same variable"))))

  (define (parse-accumulation word rest)
    (define expression (expect rest (string-append "an expression after " (symbol->string word))))
    (define after (cdr rest))
    (define into? (and (pair? after) (eq? (car after) 'into)))
    (define variable (if into? (expect (cdr after) "a variable after into") '()))
    (do! (loop--accumulate word (accumulator variable (loop--kind word)) expression))
    (if into? (cddr after) after))

  ; --- when, if, unless ------------------------------------------------

  (define (parse-branch rest)
    ; One branch of a when: a clause, or several joined by and. Returns
    ; (forms . what-is-left), the forms being the code the clauses added.
    (define saved actions)
    (set! actions '())
    (define (clauses-joined-by-and rest)
      (define after (parse-selectable rest))
      (if (and (pair? after) (eq? (car after) 'and))
          (clauses-joined-by-and (cdr after))
          after))
    (define left-over (clauses-joined-by-and rest))
    (define forms (map cdr (reverse actions)))
    (set! actions saved)
    (cons forms left-over))

  (define (parse-conditional rest negated?)
    (define test (expect rest "a test after when, if, or unless"))
    (define then-branch (parse-branch (cdr rest)))
    (define after-then (cdr then-branch))
    (define else? (and (pair? after-then) (eq? (car after-then) 'else)))
    (define else-branch (if else? (parse-branch (cdr after-then)) (cons '() after-then)))
    (define after-else (cdr else-branch))
    (do! `(if ,test
              (begin ,@(if negated? (car else-branch) (car then-branch)))
              (begin ,@(if negated? (car then-branch) (car else-branch)))))
    (if (and (pair? after-else) (eq? (car after-else) 'end))
        (cdr after-else)
        after-else))

  ; --- the clauses that can be in a when: do, return, accumulating, and when

  (define (parse-selectable rest)
    (define word (loop--word (car rest)))
    (case word
      ((do) (dolist (form (loop--leading-forms (cdr rest)))
              (do! form))
            (loop--after-forms (cdr rest)))
      ((return) (set! uses-block? #t)
                (do! `(throw ',block-name ,(expect (cdr rest) "a value after return")))
                (cddr rest))
      ((collect append sum count maximize minimize) (parse-accumulation word (cdr rest)))
      ((when) (parse-conditional (cdr rest) #f))
      ((unless) (parse-conditional (cdr rest) #t))
      (else (cond ((pair? (car rest))
                   (error "loop: a form like" (car rest) "needs do in front of it"))
                  ((eq? word 'and)
                   (error "loop: and can only join clauses inside a when, if, or unless"))
                  ((member word '(for with repeat while until always never thereis initially finally))
                   (error "loop:" word "can't be inside a when, if, or unless"))
                  (else (error "loop: don't know the loop word" (car rest)))))))

  ; --- for ---------------------------------------------------------------

  (define (for-in variable rest)
    (define remaining (gensym "rest"))
    (bind! remaining (expect rest "a list after in"))
    (bind-pattern! variable)
    (test! `(pair? ,remaining))
    (set-variables! variable `(car ,remaining))
    (do! `(set! ,remaining (cdr ,remaining)))
    (cdr rest))

  (define (for-on variable rest)
    (define remaining (gensym "rest"))
    (bind! remaining (expect rest "a list after on"))
    (bind-pattern! variable)
    (test! `(pair? ,remaining))
    (set-variables! variable remaining)
    (do! `(set! ,remaining (cdr ,remaining)))
    (cdr rest))

  (define (for-across variable rest)
    (define vector-variable (gensym "vector"))
    (define index (gensym "index"))
    (bind! vector-variable (expect rest "a vector after across"))
    (bind! index 0)
    (bind-pattern! variable)
    (test! `(< ,index (vector-length ,vector-variable)))
    (set-variables! variable `(vector-ref ,vector-variable ,index))
    (do! `(set! ,index (+ ,index 1)))
    (cdr rest))

  (define (for-equals variable rest)
    ; for x = init [then next]: without then, x is set to init on every pass
    (define init (expect rest "a value after ="))
    (define after (cdr rest))
    (define then? (and (pair? after) (eq? (car after) 'then)))
    (define value (gensym "value"))
    (bind-pattern! variable)
    (cond (then?
           (if (null? first-pass)
               (begin (set! first-pass (gensym "first-pass"))
                      (bind! first-pass #t)))
           (do! `(let ((,value (if ,first-pass ,init ,(expect (cdr after) "a value after then"))))
                   ,@(loop--pattern-setters variable value))))
          (else
           (do! `(let ((,value ,init))
                   ,@(loop--pattern-setters variable value)))))
    (if then? (cddr after) after))

  (define (for-numbers variable rest)
    ; from / downfrom, to / below / downto / above, and by, in any order
    (define start '())
    (define end '())
    (define end-word 'to)
    (define step '())
    (define counting-down? #f)
    (define (read-options rest)
      (define word (if (pair? rest) (loop--word (car rest)) '()))
      (cond ((eq? word 'from)
             (set! start (expect (cdr rest) "a value after from"))
             (read-options (cddr rest)))
            ((eq? word 'downfrom)
             (set! start (expect (cdr rest) "a value after downfrom"))
             (set! counting-down? #t)
             (read-options (cddr rest)))
            ((member word '(to below downto above))
             (set! end (expect (cdr rest) (string-append "a value after " (symbol->string word))))
             (set! end-word word)
             (if (member word '(downto above)) (set! counting-down? #t))
             (read-options (cddr rest)))
            ((eq? word 'by)
             (set! step (expect (cdr rest) "a value after by"))
             (read-options (cddr rest)))
            (else rest)))
    (define left-over (read-options rest))
    (if (not (symbol? variable))
        (error "loop: counting needs a single variable, not" variable))
    (if (and counting-down? (null? start))
        (error "loop: counting down needs a starting value (from or downfrom) for" variable))
    (define next (gensym "next"))
    (bind! next (if (null? start) 0 start))
    (bind! variable ''())
    (define limit (once! end "limit"))
    (define stride (if (null? step) 1 (once! step "step")))
    ; to and downto include the end; below and above don't
    (define included? (if (member end-word '(to downto)) #t #f))
    (define compare (if counting-down?
                        (if included? '>= '>)
                        (if included? '<= '<)))
    (if (not (null? end))
        (test! `(,compare ,next ,limit)))
    (do! `(set! ,variable ,next))
    (do! `(set! ,next (,(if counting-down? '- '+) ,next ,stride)))
    left-over)

  (define (for-hash variable rest)
    ; being the hash-keys of table [using (hash-value v)], or hash-values
    ; [using (hash-key k)]
    (define after-the (if (member (car rest) '(the each)) (cdr rest) rest))
    (define which (loop--word (expect after-the "hash-keys or hash-values")))
    (if (not (member which '(hash-key hash-value)))
        (error "loop: after being the, expected hash-keys or hash-values, not" which))
    (define after-which (cdr after-the))
    (if (not (and (pair? after-which) (member (car after-which) '(of in))))
        (error "loop: expected of or in after" which))
    (define table (expect (cdr after-which) "a hash table"))
    (define after-table (cddr after-which))
    (define using? (and (pair? after-table) (eq? (car after-table) 'using)))
    (define other-variable
      (if using?
          (cadr (expect (cdr after-table) "(hash-key k) or (hash-value v) after using"))
          '()))
    (define table-variable (gensym "table"))
    (define keys (gensym "keys"))
    (define key (gensym "key"))
    (define value `(hash-table-ref ,table-variable ,key))
    (bind! table-variable table)
    (bind! keys `(hash-table-keys ,table-variable))
    (bind! key ''())
    (bind-pattern! variable)
    (if using? (bind! other-variable ''()))
    (test! `(pair? ,keys))
    (do! `(set! ,key (car ,keys)))
    (do! `(set! ,keys (cdr ,keys)))
    (set-variables! variable (if (eq? which 'hash-key) key value))
    (if using? (do! `(set! ,other-variable ,(if (eq? which 'hash-key) value key))))
    (if using? (cddr after-table) after-table))

  (define (parse-for rest)
    (define variable (expect rest "a variable after for"))
    (define after (cdr rest))
    (define word (loop--word (expect after "in, on, across, =, from, ... after the variable")))
    (case word
      ((in) (for-in variable (cdr after)))
      ((on) (for-on variable (cdr after)))
      ((across) (for-across variable (cdr after)))
      ((=) (for-equals variable (cdr after)))
      ((being) (for-hash variable (cdr after)))
      ((from downfrom to below downto above by) (for-numbers variable after))
      (else (error "loop: don't understand" word "after the variable" variable "in a for clause"))))

  ; --- the other clauses ---------------------------------------------------

  (define (parse-with rest)
    ; with var [= value] {and var [= value]}...
    (define variable (expect rest "a variable after with"))
    (define after (cdr rest))
    (define value? (and (pair? after) (eq? (car after) '=)))
    (bind! variable (if value? (expect (cdr after) "a value after =") ''()))
    (define left-over (if value? (cddr after) after))
    (if (and (pair? left-over) (eq? (car left-over) 'and))
        (parse-with (cdr left-over))
        left-over))

  (define (parse-repeat rest)
    (define remaining (gensym "count"))
    (bind! remaining (expect rest "a number after repeat"))
    (test! `(> ,remaining 0))
    (do! `(set! ,remaining (- ,remaining 1)))
    (cdr rest))

  (define (parse-exit-test word rest)
    ; always, never, and thereis end the loop, with a value, as soon as they can
    (define test (expect rest (string-append "a test after " (symbol->string word))))
    (set! uses-block? #t)
    (set! result (list (if (eq? word 'thereis) #f #t)))
    (do! (case word
           ((always) `(if (not ,test) (throw ',block-name #f)))
           ((never) `(if ,test (throw ',block-name #f)))
           (else (let ((value (gensym "value")))
                   `(let ((,value ,test))
                      (if ,value (throw ',block-name ,value)))))))
    (cdr rest))

  (define (parse-clause rest)
    (define word (loop--word (car rest)))
    (case word
      ((for) (parse-for (cdr rest)))
      ((with) (parse-with (cdr rest)))
      ((repeat) (parse-repeat (cdr rest)))
      ((while) (test! (expect (cdr rest) "a test after while"))
               (cddr rest))
      ((until) (test! `(not ,(expect (cdr rest) "a test after until")))
               (cddr rest))
      ((always never thereis) (parse-exit-test word (cdr rest)))
      ((initially) (set! initially-forms (append initially-forms (loop--leading-forms (cdr rest))))
                   (loop--after-forms (cdr rest)))
      ((finally) (set! finally-forms (append finally-forms (loop--leading-forms (cdr rest))))
                 (loop--after-forms (cdr rest)))
      (else (parse-selectable rest))))

  (define (parse-all rest)
    (if (null? rest)
        '()
        (parse-all (parse-clause rest))))

  ; --- put it together ----------------------------------------------------

  (define (assemble)
    (if (not (null? first-pass))
        (do! `(set! ,first-pass #f)))
    (define value
      (cond ((not (null? default-accumulator)) default-accumulator)
            ((not (null? result)) (car result))
            (else ''())))
    (define code
      `(let* ,(reverse bindings)
         ,@initially-forms
         (while ,keep-going ,@(loop--nest (reverse actions) keep-going))
         ,@finally-forms
         ,value))
    (if uses-block?
        `(catch ',block-name ,code)
        code))

  ; (loop named name ...) gives the loop's block a name
  (if (and (pair? clauses) (eq? (car clauses) 'named))
      (begin (set! block-name (expect (cdr clauses) "a name after named"))
             (set! clauses (cddr clauses))))
  (bind! keep-going #t)
  (parse-all clauses)
  (assemble))

; ---------------------------------------------------------------------
; The macros
; ---------------------------------------------------------------------

; (loop form...) with no loop words is the simple loop: it repeats its
; forms until one of them does (return value).
(defmacro loop clauses
  (if (or (null? clauses) (pair? (car clauses)))
      `(catch 'loop-nil (while #t ,@clauses))
      (loop--expand clauses)))

; (return value) leaves the nearest loop that has no name, and makes it
; return value; (return-from name value) leaves the loop that is named name.
(defmacro return value
  `(throw 'loop-nil ,@value))

(defmacro return-from (name . value)
  `(throw ',name ,@value))
