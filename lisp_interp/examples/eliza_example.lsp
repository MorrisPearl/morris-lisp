; eliza_example.lsp
;
; ELIZA, Joseph Weizenbaum's 1966 program that holds a conversation by
; matching patterns, after chapter 5 of Peter Norvig's "Paradigms of
; Artificial Intelligence Programming" (1992). Norvig's Common Lisp code is
; at https://github.com/norvig/paip-lisp (MIT license); this is written
; afresh for this interpreter, with its own rules.
;
; ELIZA doesn't understand anything. It looks for a pattern that fits what
; you typed -- "... i want ..." -- and answers from a template for that
; pattern, reusing some of your own words: "Why do you want a vacation?"
;
; Run it from the examples directory to see a scripted conversation:
;   python3 ../lisp_interpreter.py eliza_example.lsp
; To talk to it yourself, (load "eliza_example.lsp") and then (eliza).

; ---------------------------------------------------------------------------
; 1. Pattern matching
; ---------------------------------------------------------------------------
; A pattern is a list of words. A symbol that starts with ? is a variable,
; which matches any one word: (i need ?x) matches (i need help). A segment
; variable, (?* ?x), matches any number of words, none included:
; ((?* ?x) need (?* ?y)) matches (i really need a long vacation), with ?x
; bound to (i really) and ?y to (a long vacation).
;
; pat-match returns the bindings -- an association list of (variable .
; value) -- or #f if the pattern doesn't match. No bindings at all is '(),
; which counts as true, so a match with no variables still succeeds.

(define (variable? x)
  (and (symbol? x) (string-starts-with? (symbol->string x) "?")))

(define (segment-pattern? pattern)
  "Whether pattern starts with a segment variable: ((?* var) ...)."
  (and (pair? pattern) (pair? (car pattern)) (eq? (caar pattern) '?*)))

(define (pat-match pattern input bindings)
  "Match pattern against input, given the bindings made so far."
  (cond ((eq? bindings #f) #f)
        ((variable? pattern) (match-variable pattern input bindings))
        ((equal? pattern input) bindings)
        ((segment-pattern? pattern) (segment-match pattern input bindings 0))
        ((and (pair? pattern) (pair? input))
         (pat-match (cdr pattern) (cdr input)
                    (pat-match (car pattern) (car input) bindings)))
        (else #f)))

(define (match-variable var input bindings)
  "Bind var to input, unless it's already bound to something else."
  (let ((binding (assoc var bindings)))
    (cond ((not binding) (cons (cons var input) bindings))
          ((equal? (cdr binding) input) bindings)
          (else #f))))

(define (segment-match pattern input bindings n)
  "Match ((?* var) . rest): give var the first n words of input, and match
the rest of the pattern against the rest of the input; if that fails, try
n + 1 words, and so on. (The book finds the next word of the pattern in the
input instead; trying every length is simpler, and quick for a sentence.)"
  (if (> n (length input))
      #f
      (let* ((var (cadr (car pattern)))
             (first-words (butlast input (- (length input) n)))
             (result (pat-match (cdr pattern) (list-tail input n)
                                (match-variable var first-words bindings))))
        (or result (segment-match pattern input bindings (+ n 1))))))

; ---------------------------------------------------------------------------
; 2. The rules
; ---------------------------------------------------------------------------
; Each rule is a pattern and some responses; ELIZA uses the first rule whose
; pattern matches, and picks one of its responses at random. In a response,
; ?x stands for the words the variable ?x matched. So the most particular
; patterns come first, and the catch-all last.

(define *eliza-rules*
  '((((?* ?x) hello (?* ?y))
     "Hello. What would you like to talk about?"
     "Hi. How are you feeling today?")
    (((?* ?x) computer (?* ?y))
     "Do computers worry you?"
     "Why do you mention computers?"
     "Do you think machines have anything to do with your problem?")
    (((?* ?x) my (?* ?y) (?* ?z) mother (?* ?w))
     "Tell me more about your family."
     "How do you get along with your mother?")
    (((?* ?x) my (?* ?y) (?* ?z) father (?* ?w))
     "Tell me more about your family."
     "Does your father often come to mind?")
    (((?* ?x) my (?* ?y))
     "Your ?y?"
     "Why do you say your ?y?")
    (((?* ?x) i want (?* ?y))
     "Why do you want ?y?"
     "What would it mean to you if you got ?y?"
     "Suppose you got ?y soon. Then what?")
    (((?* ?x) i need (?* ?y))
     "Why do you need ?y?"
     "Would it really help you to get ?y?")
    (((?* ?x) i am (?* ?y))
     "How long have you been ?y?"
     "Do you believe it is normal to be ?y?"
     "Do you enjoy being ?y?")
    (((?* ?x) i feel (?* ?y))
     "Do you often feel ?y?"
     "What makes you feel ?y?")
    (((?* ?x) i was (?* ?y))
     "Were you really?"
     "Why do you tell me you were ?y now?")
    (((?* ?x) because (?* ?y))
     "Is that the real reason?"
     "Does any other reason come to mind?")
    (((?* ?x) you are (?* ?y))
     "What makes you think I am ?y?"
     "Does it please you to believe I am ?y?")
    (((?* ?x) if (?* ?y))
     "Do you really think it is likely that ?y?"
     "What do you think about ?y?")
    (((?* ?x) always (?* ?y))
     "Can you think of a particular example?"
     "Really, always?")
    (((?* ?x) (?* ?y) alike (?* ?z))
     "In what way?"
     "What resemblance do you see?")
    (((?* ?x) no (?* ?y))
     "Why not?"
     "You are being a bit negative.")
    (((?* ?x) yes (?* ?y))
     "You seem quite sure."
     "I see.")
    (((?* ?x))
     "Please go on."
     "Very interesting."
     "I am not sure I understand you fully."
     "What does that suggest to you?")))

(define (rule-pattern rule) (car rule))
(define (rule-responses rule) (cdr rule))

; ---------------------------------------------------------------------------
; 3. Reading what the user types, and answering
; ---------------------------------------------------------------------------

; Contractions, spelled out, so the patterns can use plain words: "I'm" is
; "i am". (A quote mark can't be part of a symbol in this Lisp.)
(define *contractions*
  '(("\bi'm\b" "i am") ("\bi've\b" "i have") ("\bi'd\b" "i would")
    ("\bdon't\b" "do not") ("\bcan't\b" "cannot") ("\bwon't\b" "will not")
    ("\byou're\b" "you are") ("\bit's\b" "it is") ("\bthat's\b" "that is")))

(define (phrase->words text)
  "One phrase of what was typed, as a list of symbols: in lower case, with
contractions spelled out and punctuation left out."
  (let ((text (string-downcase text)))
    (dolist (contraction *contractions*)
      (set! text (regex-replace (car contraction) text (cadr contraction))))
    (map string->symbol (regex-find-all "[a-z0-9]+" text))))

(define (input->phrases text)
  "What was typed, split into phrases at commas and the ends of sentences,
each a list of words."
  (filter pair? (map phrase->words (regex-split "[,.;!?]" text))))

; Swap the speaker's words and the listener's, so "you hate me" comes back
; as "I hate you".
(define *viewpoint* '((i . you) (you . i) (me . you) (am . are) (my . your)
                      (your . my) (myself . yourself) (yourself . myself)))

(define (switch-viewpoint words)
  (map (lambda (word)
         (let ((swap (assoc word *viewpoint*)))
           (if swap (cdr swap) word)))
       words))

(define (random-element items)
  (list-ref items (random-int 0 (- (length items) 1))))

(define (fill-in response bindings)
  "The response with each ?x replaced by the words ?x matched, seen from
ELIZA's side."
  (regex-replace "\?[a-z]+" response
                 (lambda (match)
                   (let ((binding (assoc (string->symbol (car match)) bindings)))
                     (if binding
                         (string-join (switch-viewpoint (cdr binding)))
                         "")))))

(define (first-rule-match words)
  "The first rule whose pattern matches the words, as (position rule
bindings); every phrase matches the last rule, at least."
  (define (try rules position)
    (let ((bindings (pat-match (rule-pattern (car rules)) words '())))
      (if bindings
          (list position (car rules) bindings)
          (try (cdr rules) (+ position 1)))))
  (try *eliza-rules* 0))

(define (eliza-response text)
  "ELIZA's answer to one line of input. As the original ELIZA did, it
answers the phrase that matches the earliest -- most particular -- rule, so
in \"Well, my mother made me come here\" it's the mother that counts."
  (let* ((phrases (input->phrases text))
         (matches (map first-rule-match (if (null? phrases) '(()) phrases)))
         (best (car (sort matches car))))
    (regex-replace "\bi\b" (fill-in (random-element (rule-responses (cadr best))) (caddr best)) "I")))

(define (eliza)
  "Talk with ELIZA: type a line, press Enter, and it answers. Type bye to stop."
  (display "ELIZA: Hello. What would you like to talk about?\n")
  (let ((text (read-line "You: ")))
    (while (and text (not (member (string-downcase (string-trim text)) '("bye" "goodbye" "quit"))))
      (display (format "ELIZA: {}\n" (eliza-response text)))
      (set! text (read-line "You: "))))
  (display "ELIZA: Goodbye.\n"))

; ---------------------------------------------------------------------------
; 4. A conversation
; ---------------------------------------------------------------------------

(random-seed 5)
(dolist (line '("Hello there."
                "Men are all alike."
                "They're always bugging us about something or other."
                "Well, my boyfriend made me come here."
                "I'm depressed much of the time."
                "I need some help, that much seems certain."
                "Perhaps I could learn to get along with my mother."
                "I want to know why my computer never listens to me."
                "You are not very helpful."
                "No, I don't think so."))
  (display (format "You:   {}\nELIZA: {}\n" line (eliza-response line))))
