; nlp_parsing_example.lsp
;
; Parsing English with a phrase-structure grammar: finding every way a
; sentence can be put together from a grammar's rules, and so seeing where
; it's ambiguous; making that faster by remembering; guessing at words the
; grammar doesn't know; and turning a parse into a meaning. After chapter 19
; of Peter Norvig's "Paradigms of Artificial Intelligence Programming" (1992).
; Norvig's Common Lisp code is at https://github.com/norvig/paip-lisp (MIT
; license); this is written afresh for this interpreter, with its own
; grammars. unification_grammar_example.lsp goes on to chapters 20 and 21.
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py nlp_parsing_example.lsp

; ---------------------------------------------------------------------------
; 1. A grammar
; ---------------------------------------------------------------------------
; Each rule is (category -> right-hand-side). A right-hand side that's a list
; is the categories the phrase is made of; one that's a symbol is a word of
; that category. So (NP -> (D N)) says a noun phrase can be a determiner
; followed by a noun, and (N -> dog) that "dog" is a noun.

(define *english*
  '((S -> (NP VP))
    (NP -> (D N)) (NP -> (D A+ N)) (NP -> (NP PP)) (NP -> (Pro)) (NP -> (Name))
    (VP -> (V NP)) (VP -> (V)) (VP -> (VP PP))
    (PP -> (P NP))
    (A+ -> (A)) (A+ -> (A A+))
    (D -> the) (D -> a) (D -> every)
    (N -> man) (N -> woman) (N -> dog) (N -> park) (N -> telescope) (N -> hill) (N -> table)
    (V -> saw) (V -> liked) (V -> walked) (V -> slept)
    (A -> big) (A -> little) (A -> old) (A -> red)
    (P -> with) (P -> in) (P -> on) (P -> by)
    (Pro -> he) (Pro -> she) (Pro -> it)
    (Name -> terry) (Name -> kim)))

(define *grammar* *english*)

(define (rule-lhs rule) (car rule))
(define (rule-rhs rule) (caddr rule))

(define (lexical-rules word)
  "The rules that say what category word is."
  (let ((rules (filter (lambda (rule) (eq? (rule-rhs rule) word)) *grammar*)))
    (if (null? rules) (unknown-word-rules word) rules)))

(define (rules-starting-with category)
  "The rules whose right-hand side starts with category."
  (filter (lambda (rule) (and (pair? (rule-rhs rule)) (eq? (car (rule-rhs rule)) category)))
          *grammar*))

; ---------------------------------------------------------------------------
; 2. The parser
; ---------------------------------------------------------------------------
; A parse is (tree . remaining-words): a tree for a first part of the words,
; and the words it didn't use. A tree is (category part...), e.g.
; (NP (D the) (N dog)).
;
; parse works bottom-up. It looks up what the first word can be -- "the" is a
; D -- and extend-parse builds up from there: a D can start an NP, if a noun
; follows; the NP can start an S, if a VP follows; and so on, each time
; parsing the rest of the words for the category that's needed next. It
; finds every parse, so where a sentence is ambiguous, it finds all the
; readings.

(define *memo* (make-hash-table))       ; the words' length -> their parses
(define *calls* 0)                      ; how many times extend-parse is called
(define *remember?* #t)

(define (parse words)
  "Every parse of a first part of words."
  (cond ((null? words) '())
        ((and *remember?* (hash-table-has? *memo* (length words)))
         (hash-table-ref *memo* (length words)))
        (else
         (let ((parses (append-map (lambda (rule)
                                     (extend-parse (rule-lhs rule) (list (car words)) (cdr words) '()))
                                   (lexical-rules (car words)))))
           (hash-table-set! *memo* (length words) parses)
           parses))))

(define (extend-parse lhs rhs remaining needed)
  "A phrase of category lhs, made of the parts rhs so far, and needing the
categories in needed to finish it: every way to finish it from the
remaining words, and every bigger phrase it can start."
  (set! *calls* (+ *calls* 1))
  (if (null? needed)
      (let ((tree (cons lhs rhs)))
        (cons (cons tree remaining)
              (append-map (lambda (rule)
                            (extend-parse (rule-lhs rule) (list tree) remaining (cdr (rule-rhs rule))))
                          (rules-starting-with lhs))))
      (append-map (lambda (next)
                    (if (eq? (car (car next)) (car needed))
                        (extend-parse lhs (append rhs (list (car next))) (cdr next) (cdr needed))
                        '()))
                  (parse remaining))))

(define (parser words)
  "Every complete parse tree of the words: those that use all of them."
  (set! *memo* (make-hash-table))       ; the memo is for one sentence's words
  (map car (filter (lambda (p) (null? (cdr p))) (parse words))))

(define (bracketing tree)
  "A tree with the category names left out, to show how the words group."
  (cond ((not (pair? tree)) tree)
        ((null? (cddr tree)) (bracketing (cadr tree)))
        (else (map bracketing (cdr tree)))))

(define (sentence text)
  "A sentence, as a list of words (symbols in lower case)."
  (map string->symbol (regex-find-all "[a-z]+" (string-downcase text))))

; ---------------------------------------------------------------------------
; 3. Parsing, and ambiguity
; ---------------------------------------------------------------------------

(display "The parse of \"the dog saw a little red telescope\":\n")
(print (car (parser (sentence "the dog saw a little red telescope"))))

(display "\n\"The man saw the woman with the telescope\" has two readings:\n")
(dolist (tree (parser (sentence "the man saw the woman with the telescope")))
  (print (bracketing tree)))

(display "\nEach extra phrase multiplies the readings:\n")
(dolist (text '("the man saw the woman in the park"
                "the man saw the woman in the park with the telescope"
                "the man saw the woman in the park with the telescope on the hill"
                "the man saw the woman in the park with the telescope on the hill by the table"))
  (display (format "  {} readings: {}\n" (length (parser (sentence text))) text)))

; ---------------------------------------------------------------------------
; 4. Remembering
; ---------------------------------------------------------------------------
; The same words get parsed again and again -- "the telescope" once for each
; way of reaching it. Remembering each parse of the last n words (a table
; keyed by n, since the words are always the end of the sentence) means each
; is worked out once.

(define long-sentence (sentence "the man saw the woman in the park with the telescope on the hill by the table"))
(set! *calls* 0)
(parser long-sentence)
(define with-memo *calls*)
(set! *remember?* #f)
(set! *calls* 0)
(parser long-sentence)
(set! *remember?* #t)
(display (format "\nParsing the longest one calls extend-parse {} times remembering, {} times not.\n"
                 with-memo *calls*))

; ---------------------------------------------------------------------------
; 5. Words the grammar doesn't know
; ---------------------------------------------------------------------------
; Rather than give up on an unknown word, the parser can try it as each of
; the "open" categories -- the ones that take new words all the time, nouns,
; verbs, adjectives, and names -- and let the rest of the sentence decide.

(define *open-categories* '(N V A Name))

(define (unknown-word-rules word)
  (map (lambda (category) (list category '-> word)) *open-categories*))

(display "\nWith two words it has never seen, \"glorp\" and \"blicked\":\n")
(dolist (tree (parser (sentence "the glorp blicked a dog")))
  (print tree))

; ---------------------------------------------------------------------------
; 6. From a parse to a meaning
; ---------------------------------------------------------------------------
; A grammar can say what each phrase means, too: here, spoken arithmetic,
; where "two" means 2 and "E plus E" means the sum. Each rule gets a third
; part: for a word, its meaning; for a phrase, a procedure that combines the
; meanings of its parts. The same parser finds the trees, and meaning works
; them out. "Two plus three times four" is ambiguous -- (2 + 3) * 4 or
; 2 + (3 * 4) -- and so has two meanings.

(define *arithmetic*
  (list (list 'E '-> '(E Op E) (lambda (x op y) (op x y)))
        (list 'E '-> '(Number) (lambda (n) n))
        (list 'Number '-> '(Digit) (lambda (n) n))              ; three
        (list 'Number '-> '(Tens) (lambda (n) n))               ; twenty
        (list 'Number '-> '(Tens Digit) (lambda (n m) (+ n m))) ; twenty three
        (list 'Op '-> 'plus +) (list 'Op '-> 'minus -) (list 'Op '-> 'times *) (list 'Op '-> 'over /)
        (list 'Digit '-> 'one 1) (list 'Digit '-> 'two 2) (list 'Digit '-> 'three 3)
        (list 'Digit '-> 'four 4) (list 'Digit '-> 'five 5) (list 'Digit '-> 'six 6)
        (list 'Digit '-> 'seven 7) (list 'Digit '-> 'eight 8) (list 'Digit '-> 'nine 9)
        (list 'Number '-> 'ten 10)
        (list 'Tens '-> 'twenty 20) (list 'Tens '-> 'thirty 30) (list 'Tens '-> 'forty 40)))

(define (rule-meaning rule) (cadddr rule))

(define (meaning tree)
  "What the tree means, by the grammar's rules."
  (let ((category (car tree))
        (parts (cdr tree)))
    (if (and (null? (cdr parts)) (not (pair? (car parts))))
        ; a word: the meaning its lexical rule gives it
        (rule-meaning (car (filter (lambda (rule) (and (eq? (rule-lhs rule) category)
                                                       (eq? (rule-rhs rule) (car parts))))
                                   *grammar*)))
        ; a phrase: its rule's procedure, applied to the meanings of its parts
        (let ((rule (car (filter (lambda (rule) (and (eq? (rule-lhs rule) category)
                                                     (equal? (rule-rhs rule) (map car parts))))
                                 *grammar*))))
          (apply (rule-meaning rule) (map meaning parts))))))

(define (meanings text)
  (map meaning (parser (sentence text))))

(set! *grammar* *arithmetic*)
(display "\nMeanings of spoken arithmetic:\n")
(dolist (text '("two plus three"
                "two plus three times four"
                "twenty one times two"
                "ten minus four minus three"
                "six over two times three"))
  (display (format "  {}: {}\n" text (meanings text))))
(set! *grammar* *english*)
