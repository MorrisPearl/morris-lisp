; unification_grammar_example.lsp
;
; Grammar as logic. First a small Prolog: unification, and a prover that
; finds every answer to a question. Then grammar rules written as Prolog
; clauses, with features -- so "the dog sleeps" parses but "the dogs sleeps"
; doesn't -- that build the meaning of a sentence as a formula of logic while
; they parse it: "every dog chases a cat" means
;   (every ?x (dog ?x) (some ?y (cat ?y) (chase ?x ?y)))
; And because it's logic, the same grammar goes the other way: from a
; meaning to the sentences that say it.
;
; After chapters 20 and 21 of Peter Norvig's "Paradigms of Artificial
; Intelligence Programming" (1992), and the Prolog of chapter 11 that they
; build on. Norvig's Common Lisp code is at
; https://github.com/norvig/paip-lisp (MIT license); this is written afresh
; for this interpreter, with its own grammar -- a small slice of the English
; that chapter 21 covers. nlp_parsing_example.lsp is chapter 19.
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py unification_grammar_example.lsp

; ---------------------------------------------------------------------------
; 1. Unification
; ---------------------------------------------------------------------------
; A symbol that starts with ? is a variable. Unifying two expressions finds
; values for their variables that make them the same: (likes ?x terry) and
; (likes kim ?y) unify with ?x = kim and ?y = terry. The values are kept as
; bindings, an association list of (variable . value), and a variable's
; value can be another variable, or contain some. Unify returns the
; bindings, or #f if the two can't be made the same. No bindings at all is
; '(), which counts as true.

(define (variable? x)
  (and (symbol? x) (string-starts-with? (symbol->string x) "?")))

(define (unify x y bindings)
  "The bindings, added to so that x and y are the same -- or #f."
  (cond ((eq? bindings #f) #f)
        ((equal? x y) bindings)
        ((variable? x) (unify-variable x y bindings))
        ((variable? y) (unify-variable y x bindings))
        ((and (pair? x) (pair? y))
         (unify (cdr x) (cdr y) (unify (car x) (car y) bindings)))
        (else #f)))

(define (unify-variable var x bindings)
  "Unify the variable var with x."
  (let ((var-binding (assoc var bindings)))
    (cond (var-binding (unify (cdr var-binding) x bindings))
          ((and (variable? x) (assoc x bindings))
           (unify var (cdr (assoc x bindings)) bindings))
          ((occurs-in? var x bindings) #f)      ; ?x can't be (f ?x)
          (else (cons (cons var x) bindings)))))

(define (occurs-in? var x bindings)
  "Whether the variable var appears in x, following the bindings."
  (cond ((eq? var x) #t)
        ((and (variable? x) (assoc x bindings))
         (occurs-in? var (cdr (assoc x bindings)) bindings))
        ((pair? x) (or (occurs-in? var (car x) bindings)
                       (occurs-in? var (cdr x) bindings)))
        (else #f)))

(define (substitute bindings x)
  "x with each variable replaced by its value, as far as the bindings go."
  (cond ((variable? x)
         (let ((binding (assoc x bindings)))
           (if binding (substitute bindings (cdr binding)) x)))
        ((pair? x) (cons (substitute bindings (car x)) (substitute bindings (cdr x))))
        (else x)))

; ---------------------------------------------------------------------------
; 2. Clauses, and a prover
; ---------------------------------------------------------------------------
; A clause is (head goal ...): the head is true if all the goals are. A
; clause with no goals is a fact. (<- (member ?item (?item . ?rest))) says
; an item is a member of a list that starts with it;
; (<- (member ?item (?x . ?rest)) (member ?item ?rest)) that it's a member of
; a list whose rest it's a member of. The clauses are kept in a table by
; their predicate: the first symbol of the head.

(define *clauses* (make-hash-table))

(define (add-clause clause)
  (let ((predicate (caar clause)))
    (hash-table-update! *clauses* predicate (lambda (clauses) (append clauses (list clause))) '())))

(defmacro <- (head . body)
  "(<- head goal ...): add a clause."
  `(add-clause '(,head ,@body)))

(define *renamings* 0)

(define (rename-variables x)
  "x with each variable given a new name, never used before -- ?x becomes
?x.17 -- so that each use of a clause has variables of its own."
  (define (rename x)
    (cond ((variable? x) (string->symbol (format "{}.{}" x *renamings*)))
          ((pair? x) (cons (rename (car x)) (rename (cdr x))))
          (else x)))
  (incf *renamings*)
  (rename x))

; To prove a goal, try each clause for its predicate: if the goal unifies
; with the clause's head, prove the clause's goals. Every way that works is
; an answer, so a proof returns a list of bindings -- one for each answer,
; '() for none.

(define (prove goal bindings)
  "Every way to prove goal, given the bindings so far: a list of bindings."
  (let ((answers '()))
    (dolist (clause (hash-table-ref *clauses* (car goal) '()))
      (let ((clause (rename-variables clause)))
        (set! answers (append answers
                              (prove-all (cdr clause) (unify goal (car clause) bindings))))))
    answers))

(define (prove-all goals bindings)
  "Every way to prove all of the goals: a list of bindings."
  (cond ((eq? bindings #f) '())
        ((null? goals) (list bindings))
        (else
         (let ((answers '()))
           (dolist (b (prove (car goals) bindings))
             (set! answers (append answers (prove-all (cdr goals) b))))
           answers))))

(define (tidy-variables x)
  "x with its variables renamed ?x, ?y, ?z, ... in the order they appear,
so that (every ?x.31 (dog ?x.31) ...) reads as (every ?x (dog ?x) ...)."
  (let ((names '()))                    ; (old-name . new-name)
    (define (tidy x)
      (cond ((variable? x)
             (unless (assoc x names)
               (push (cons x (list-ref '(?x ?y ?z ?u ?v ?w) (length names))) names))
             (cdr (assoc x names)))
            ((pair? x) (cons (tidy (car x)) (tidy (cdr x))))
            (else x)))
    (tidy x)))

(define (solve-for x goals)
  "Every value of x -- a variable, or a list with variables in it -- that
makes all the goals true."
  (map (lambda (bindings) (tidy-variables (substitute bindings x)))
       (prove-all goals '())))

; Some clauses, and some questions. Note that append can be asked to run
; backwards: what lists, appended, make (1 2 3)?

(<- (= ?x ?x))
(<- (member ?item (?item . ?rest)))
(<- (member ?item (?x . ?rest)) (member ?item ?rest))
(<- (append () ?list ?list))
(<- (append (?x . ?rest) ?list (?x . ?result)) (append ?rest ?list ?result))

(display "Prolog:\n")
(display (format "  members of (a b c): {}\n" (solve-for '?m '((member ?m (a b c))))))
(display (format "  common members of (a b c d) and (d e b): {}\n"
                 (solve-for '?m '((member ?m (a b c d)) (member ?m (d e b))))))
(display (format "  ways to append two lists to make (1 2 3): {}\n"
                 (solve-for '(?front ?back) '((append ?front ?back (1 2 3))))))

; ---------------------------------------------------------------------------
; 3. Grammar rules as clauses
; ---------------------------------------------------------------------------
; A grammar rule such as
;   (rule (S ?meaning) --> (NP ...) (VP ...))
; becomes a clause by giving each part two more arguments: the words from
; where it starts, and the words left once it's done -- ?s0 to ?s2 for the
; whole S, ?s0 to ?s1 for the NP, and ?s1 to ?s2 for the VP:
;   ((S ?meaning ?s0 ?s2) (NP ... ?s0 ?s1) (VP ... ?s1 ?s2))
; A word, (:word dog), becomes (= ?si (dog . ?sj)): the words from ?si on
; start with dog, and ?sj is the rest. Then a sentence is an S whose words
; are the sentence's, with nothing left over: (S ?meaning (the dog sleeps) ()).
;
; The features are the other arguments. Unification does the work: in
; (S ?meaning) --> (NP ?n ...) (VP ?n ...), the NP and VP must have the same
; number ?n, sg or pl, so "the dogs sleeps" can't be an S.

(define (words-variable i)
  (string->symbol (format "?s{}" i)))

(define (grammar-rule->clause head parts)
  (let ((goals '())
        (i 0))
    (dolist (part parts)
      (let ((before (words-variable i))
            (after (words-variable (+ i 1))))
        (set! goals (append goals
                            (list (if (eq? (car part) ':word)
                                      (list '= before (cons (cadr part) after))
                                      (append part (list before after))))))
        (incf i)))
    (cons (append head (list (words-variable 0) (words-variable i)))
          goals)))

(defmacro rule (head arrow . parts)
  "(rule head --> part ...): add a grammar rule."
  `(add-clause (grammar-rule->clause ',head ',parts)))

; ---------------------------------------------------------------------------
; 4. A grammar, with meanings
; ---------------------------------------------------------------------------
; A noun phrase such as "every dog" says something about each thing ?x
; that's a dog: that the rest of the sentence -- its "scope", a formula
; about ?x -- is true of it. So an NP has four features: its number; ?x; the
; scope, given to it by the rest of the sentence; and the meaning of the
; whole. For "every dog", with the scope (sleep ?x), that's
;   (every ?x (dog ?x) (sleep ?x))
; A name is simpler: "kim", with the scope (sleep kim), means (sleep kim).

(rule (S ?meaning) -->
      (NP ?n ?x ?vp ?meaning) (VP ?n ?x ?vp))                    ; kim sleeps
(rule (S (not ?meaning)) -->
      (NP sg ?x ?vp ?meaning) (:word does) (:word not) (VP base ?x ?vp))
(rule (S (not ?meaning)) -->
      (NP pl ?x ?vp ?meaning) (:word do) (:word not) (VP base ?x ?vp))
(rule (S (question ?meaning)) -->
      (:word does) (NP sg ?x ?vp ?meaning) (VP base ?x ?vp))     ; does kim sleep
(rule (S (question ?meaning)) -->
      (:word do) (NP pl ?x ?vp ?meaning) (VP base ?x ?vp))

(rule (NP sg ?name ?scope ?scope) --> (Name ?name))
(rule (NP ?n ?x ?scope ?meaning) -->
      (Det ?n ?x ?restriction ?scope ?meaning) (Noun ?n ?x ?restriction))
(rule (NP ?n ?x ?scope ?meaning) -->                            ; a dog that sleeps
      (Det ?n ?x (and ?noun ?relative) ?scope ?meaning)
      (Noun ?n ?x ?noun) (:word that) (VP ?n ?x ?relative))

; A verb phrase's form is sg (sleeps), pl (sleep), or base (sleep, after
; "does"), and it says something about ?x, its subject.
(rule (VP ?form ?x ?meaning) --> (Verb/intransitive ?form ?x ?meaning))
(rule (VP ?form ?x ?meaning) -->
      (Verb/transitive ?form ?x ?y ?verb) (NP ?n ?y ?verb ?meaning))

; The determiners: each word, the number of noun it goes with, and the quantifier it means.
(rule (Det sg ?x ?restriction ?scope (every ?x ?restriction ?scope)) --> (:word every))
(rule (Det pl ?x ?restriction ?scope (every ?x ?restriction ?scope)) --> (:word all))
(rule (Det sg ?x ?restriction ?scope (some ?x ?restriction ?scope)) --> (:word a))
(rule (Det pl ?x ?restriction ?scope (some ?x ?restriction ?scope)) --> (:word some))
(rule (Det ?n ?x ?restriction ?scope (no ?x ?restriction ?scope)) --> (:word no))
(rule (Det ?n ?x ?restriction ?scope (the ?x ?restriction ?scope)) --> (:word the))

; The words. Each gets its rules from one of these, which say what the word
; means: "dogs" is (dog ?x), "chases" is (chase ?x ?y).

(define (add-word head word)
  (add-clause (grammar-rule->clause head (list (list ':word word)))))

(define (name word)
  (add-word (list 'Name word) word))

(define (noun singular plural)
  (add-word (list 'Noun 'sg '?x (list singular '?x)) singular)
  (add-word (list 'Noun 'pl '?x (list singular '?x)) plural))

(define (verb category base-form sg-form)
  "A verb, e.g. (verb 'Verb/transitive 'chase 'chases): chase is its
plural and base form, chases the singular."
  (let ((meaning (if (eq? category 'Verb/transitive)
                     (list base-form '?x '?y)
                     (list base-form '?x)))
        (subject-and-object (if (eq? category 'Verb/transitive) '(?x ?y) '(?x))))
    (add-word (append (list category 'sg) subject-and-object (list meaning)) sg-form)
    (add-word (append (list category 'pl) subject-and-object (list meaning)) base-form)
    (add-word (append (list category 'base) subject-and-object (list meaning)) base-form)))

(dolist (word '(kim terry lee)) (name word))
(noun 'dog 'dogs)
(noun 'cat 'cats)
(noun 'student 'students)
(noun 'book 'books)
(verb 'Verb/intransitive 'sleep 'sleeps)
(verb 'Verb/intransitive 'bark 'barks)
(verb 'Verb/transitive 'chase 'chases)
(verb 'Verb/transitive 'like 'likes)
(verb 'Verb/transitive 'read 'reads)

; ---------------------------------------------------------------------------
; 5. Parsing: from words to meanings
; ---------------------------------------------------------------------------

(define (sentence text)
  (map string->symbol (regex-find-all "[a-z]+" (string-downcase text))))

(define (meanings text)
  "The meaning of each way to parse the text as a sentence ('() if it
isn't one)."
  (solve-for '?meaning (list (list 'S '?meaning (sentence text) '()))))

(display "\nParsing, from a sentence to what it means:\n")
(dolist (text '("Kim sleeps."
                "Kim likes Terry."
                "Every dog barks."
                "All dogs bark."
                "The cats chase a dog."
                "Every student that reads a book likes Lee."
                "No dog that chases a cat sleeps."
                "Terry does not like the dog."
                "Does Kim read every book?"
                "Do the dogs chase some cats?"))
  (display (format "  {}\n      {}\n" text (meanings text))))

(display "\nAnd what isn't a sentence has no meaning:\n")
(dolist (text '("The dogs sleeps."
                "A dogs bark."
                "Kim sleep."
                "Does Kim likes Terry?"
                "Every cat chases."))
  (display (format "  {}  {}\n" text (meanings text))))

; ---------------------------------------------------------------------------
; 6. Generating: from a meaning to words
; ---------------------------------------------------------------------------
; Give S a meaning, and leave the words a variable: the prover finds the
; words that the grammar says mean that. So parsing a sentence and then
; generating from its meaning gives every sentence that means the same.
;
; One catch: in the meaning to say, ?x must stay ?x. As a variable, it could
; be unified with something else -- with lee, say, so that "lee chases every
; dog" would seem to mean (every ?x (dog ?x) (chase ?x lee)). So first the
; meaning's variables are frozen: turned into plain symbols, ?x into x, which
; can only ever be themselves.

(define (freeze x)
  (cond ((variable? x) (string->symbol (substring (symbol->string x) 1)))
        ((pair? x) (cons (freeze (car x)) (freeze (cdr x))))
        (else x)))

(define (sentences-meaning meaning)
  "Every sentence the grammar has that means meaning, as a list of words."
  (solve-for '?words (list (list 'S (freeze meaning) '?words '()))))

(display "\nGenerating: each sentence that means the same as the first one:\n")
(dolist (text '("Every dog barks."
                "Kim likes Terry."
                "Does a cat sleep?"
                "Terry does not like the dog."
                "Every student that reads a book likes Lee."))
  (display (format "  {}\n" text))
  (dolist (words (sentences-meaning (car (meanings text))))
    (display (format "      {}\n" words))))

; "The dog" and "the dogs" come out the same: the meanings in this grammar
; don't say whether "the" was about one thing or several.
