; kenken_example.lsp
;
; A KenKen solver. A KenKen puzzle is an N x N grid to fill with the digits
; 1 to N, so that no digit appears twice in any row or column -- and so
; that each cage, a group of cells outlined in the puzzle, comes out right:
; its digits, combined by the cage's operation, give the cage's number.
;
; A puzzle is its size and a list of its cages. A cell is written as its
; row and column -- 23 is row 2, column 3 -- and a cage as its cells and
; its arithmetic:
;   ((11 12 13 23) (+ 17))   the four digits add up to 17
;   ((31 41) (- 2))          the larger digit less the smaller is 2
;   ((32 33) (* 12))         the digits multiply to 12
;   ((34 44) (/ 3))          the larger digit divided by the smaller is 3
;   ((42) (= 4))             the digit is 4
; (A - or / cage of more than two cells works the same way: the largest
; digit less, or divided by, all the others.)
;
; How it's solved. For each cell, the solver keeps the digits it could
; still be, and for each cage, the combinations of digits that make its
; arithmetic come out. It rules out what can't be, over and over, until
; nothing more can be ruled out:
;   - a cage combination that needs a digit a cell can no longer be is out,
;     and a cell can only be a digit that one of its cage's combinations
;     puts there;
;   - a digit that's settled in one cell is out for the rest of its row and
;     column;
;   - a digit that can go in only one cell of a row or column goes there.
; (Each rule is about one group of cells -- a cage, a row, or a column --
; and is applied again only when one of the group's cells has lost a
; digit.) Most of the puzzle is usually solved that way. When it stalls, the solver
; guesses: it takes the cell with the fewest digits left, tries each one in
; turn, and carries on from there -- going back to try the next digit if a
; guess leads to a cell or cage with nothing left.
;
; Run it from the examples directory:
;   python3 ../lisp_interpreter.py kenken_example.lsp
; In a Jupyter notebook, the puzzles are drawn as grids with their cages
; outlined.

; ---------------------------------------------------------------------------
; 1. Cells and cages
; ---------------------------------------------------------------------------

(define (row-of cell) (quotient cell 10))
(define (column-of cell) (remainder cell 10))

(define (same-line? a b)
  "Whether cells a and b are in the same row or column."
  (or (= (row-of a) (row-of b)) (= (column-of a) (column-of b))))

(define (grid-cells size)
  "Every cell of a size x size grid, row by row."
  (loop for row from 1 to size
        append (loop for column from 1 to size collect (+ (* 10 row) column))))

(define (grid-lines size)
  "The rows and the columns of the grid, each a list of its cells."
  (append (loop for row from 1 to size
                collect (loop for column from 1 to size collect (+ (* 10 row) column)))
          (loop for column from 1 to size
                collect (loop for row from 1 to size collect (+ (* 10 row) column)))))

(defstruct cage
  number           ; its place in the puzzle's list of cages, from 0
  cells            ; a list of cells, such as (11 12 13 23)
  operation        ; one of the symbols + - * / =
  target           ; the number the operation must give
  combinations)    ; every list of digits for the cells that gives it

(define (comes-out? operation target digits)
  "Whether the digits, combined by the operation, give target."
  (let ((largest (apply max digits))
        (sum (apply + digits))
        (product (apply * digits)))
    (case operation
      ((+) (= sum target))
      ((*) (= product target))
      ((-) (= (- largest (- sum largest)) target))           ; the largest less the others
      ((/) (= (* largest largest) (* target product)))        ; the largest / the others' product
      ((=) (= sum target)))))

(define (could-still-come-out? operation target digits)
  "Whether a cage only partly filled with the digits could still come out:
adding more digits only makes a sum bigger, and a product can only come
out if the digits so far multiply to a divisor of it."
  (case operation
    ((+) (< (apply + digits) target))
    ((*) (= (remainder target (apply * digits)) 0))
    (else #t)))

(define (combinations-for cells operation target size)
  "Every way to fill the cells with digits from 1 to size that comes out
right, with no digit twice in a row or column: a list of lists of digits,
one digit for each cell, in the order of cells."
  (define (fill chosen remaining)
    ; chosen: the (cell . digit) pairs so far, most recent first
    (cond ((null? remaining)
           (let ((digits (reverse (map cdr chosen))))
             (if (comes-out? operation target digits) (list digits) '())))
          ((and (pair? chosen)
                (not (could-still-come-out? operation target (map cdr chosen))))
           '())
          (else
           (let ((cell (car remaining)))
             (loop for digit from 1 to size
                   unless (some (lambda (pair) (and (= (cdr pair) digit) (same-line? (car pair) cell)))
                                chosen)
                   append (fill (cons (cons cell digit) chosen) (cdr remaining)))))))
  (fill '() cells))

(define (check-puzzle size descriptions)
  "Complain about a puzzle that isn't well formed: each cell must be in
exactly one cage, and each cage's arithmetic must make sense."
  (let ((cage-of (make-hash-table)))
    (dolist (description descriptions)
      (let ((cells (first description))
            (operation (first (second description))))
        (unless (member operation '(+ - * / =))
          (error "kenken: the operation must be + - * / or =, not" operation "in" description))
        (when (and (eq? operation '=) (not (= (length cells) 1)))
          (error "kenken: an = cage has just one cell:" description))
        (when (and (member operation '(- /)) (< (length cells) 2))
          (error "kenken: a - or / cage needs at least two cells:" description))
        (dolist (cell cells)
          (unless (and (<= 1 (row-of cell) size) (<= 1 (column-of cell) size))
            (error "kenken: there's no cell" cell "in a" size "x" size "grid"))
          (when (hash-table-has? cage-of cell)
            (error "kenken: cell" cell "is in two cages"))
          (hash-table-set! cage-of cell description))))
    (dolist (cell (grid-cells size))
      (unless (hash-table-has? cage-of cell)
        (error "kenken: cell" cell "isn't in any cage")))))

(define (make-cages size descriptions)
  "The cages of a puzzle, from their descriptions -- without their
combinations, which make-kenken adds."
  (check-puzzle size descriptions)
  (loop for description in descriptions
        for number from 0
        collect (make-cage :number number
                           :cells (first description)
                           :operation (first (second description))
                           :target (second (second description)))))

; ---------------------------------------------------------------------------
; 2. The puzzle, and what's still possible
; ---------------------------------------------------------------------------
; Each rule is about one group of cells: a cage, a row, or a column.

(defstruct group
  number           ; from 0, to tell the groups apart
  cells            ; its cells
  cage)            ; for a cage's group, the cage; for a row or column, #f

(defstruct puzzle
  size
  cages            ; as make-cages makes them
  groups           ; every group: each cage, row, and column
  groups-of)       ; a hash table: cell -> the groups it's in (its cage, row, and column)

(define (make-kenken size descriptions)
  "A puzzle, from its size and its cages' descriptions."
  (let* ((cages (make-cages size descriptions))
         (_ (dolist (cage cages)
              (cage-combinations-set! cage (combinations-for (cage-cells cage) (cage-operation cage)
                                                             (cage-target cage) size))))
         (groups (loop for (cells . cage) in (append (map (lambda (cage) (cons (cage-cells cage) cage)) cages)
                                                     (map (lambda (line) (cons line #f)) (grid-lines size)))
                       for number from 0
                       collect (make-group :number number :cells cells :cage cage)))
         (groups-of (make-hash-table)))
    (dolist (group groups)
      (dolist (cell (group-cells group))
        (hash-table-set! groups-of cell (cons group (hash-table-ref groups-of cell '())))))
    (make-puzzle :size size :cages cages :groups groups :groups-of groups-of)))

; The solver's state: for each cell, the digits it could still be, and for
; each cage, the combinations still possible. When it guesses, it works on
; a copy, so that going back is just going back to the state before.

(defstruct possibilities
  digits           ; a hash table: cell -> a list of digits
  combinations)    ; a hash table: cage number -> a list of combinations

(define (starting-possibilities puzzle)
  (let ((digits (make-hash-table))
        (combinations (make-hash-table))
        (size (puzzle-size puzzle)))
    (dolist (cell (grid-cells size))
      (hash-table-set! digits cell (loop for digit from 1 to size collect digit)))
    (dolist (cage (puzzle-cages puzzle))
      (hash-table-set! combinations (cage-number cage) (cage-combinations cage)))
    (make-possibilities :digits digits :combinations combinations)))

(define (copy-of possibilities)
  (make-possibilities :digits (hash-table-copy (possibilities-digits possibilities))
                      :combinations (hash-table-copy (possibilities-combinations possibilities))))

(define (digits-of possibilities cell)
  (hash-table-ref (possibilities-digits possibilities) cell))

(define (combinations-of possibilities cage)
  (hash-table-ref (possibilities-combinations possibilities) (cage-number cage)))

; ---------------------------------------------------------------------------
; 3. Ruling things out
; ---------------------------------------------------------------------------
; Each rule returns the cells it took digits away from, and raises the
; signal 'impossible -- caught by kenken-solutions, below -- if it leaves a
; cell or a cage with nothing possible.

(define (limit-digits! possibilities cell allowed)
  "Keep only the cell's digits that are in allowed. #t if any went."
  (let* ((before (digits-of possibilities cell))
         (after (filter (lambda (digit) (member digit allowed)) before)))
    (when (null? after)
      (throw 'impossible #f))
    (hash-table-set! (possibilities-digits possibilities) cell after)
    (< (length after) (length before))))

(define (still-possible? possibilities cells combination)
  "Whether each cell can still be its digit in the combination."
  (or (null? cells)
      (and (member (car combination) (digits-of possibilities (car cells)))
           (still-possible? possibilities (cdr cells) (cdr combination)))))

(define (apply-cage! possibilities cage)
  "Keep the cage's combinations whose digits its cells can still be; then
keep only the digits for each cell that some combination puts there."
  (let ((still-possible
          (filter (lambda (combination) (still-possible? possibilities (cage-cells cage) combination))
                  (combinations-of possibilities cage))))
    (when (null? still-possible)
      (throw 'impossible #f))
    (hash-table-set! (possibilities-combinations possibilities) (cage-number cage) still-possible)
    (loop for cell in (cage-cells cage)
          for position from 0
          when (limit-digits! possibilities cell
                              (map (lambda (combination) (list-ref combination position)) still-possible))
          collect cell)))

(define (apply-line! possibilities line size)
  "In one row or column: a digit settled in one cell can't be in the
others, and a digit with only one cell it can go in goes there."
  (let ((changed '())
        (places (make-hash-table)))         ; digit -> the cells it could go in
    (dolist (cell line)
      (let ((digits (digits-of possibilities cell)))
        (when (null? (cdr digits))              ; settled
          (dolist (other line)
            (when (and (not (= other cell))
                       (member (car digits) (digits-of possibilities other)))
              (limit-digits! possibilities other
                             (filter (lambda (d) (not (= d (car digits)))) (digits-of possibilities other)))
              (push other changed))))))
    (dolist (cell line)
      (dolist (digit (digits-of possibilities cell))
        (hash-table-set! places digit (cons cell (hash-table-ref places digit '())))))
    (loop for digit from 1 to size
          do (let ((cells (hash-table-ref places digit '())))
               (when (null? cells)
                 (throw 'impossible #f))
               (when (and (null? (cdr cells))
                          (limit-digits! possibilities (car cells) (list digit)))
                 (push (car cells) changed))))
    changed))

(define (rule-out! possibilities puzzle to-do)
  "Apply the rules until none of them rules anything more out. A group's
rule is worth applying again only when one of its cells has lost a digit
since. So the groups wait in a to-do list, starting with to-do, and when a
cell loses a digit, its cage, row, and column go on the list (unless
they're on it already)."
  (let ((waiting (make-hash-table)))          ; the numbers of the groups on the list
    (dolist (group to-do)
      (hash-table-set! waiting (group-number group) #t))
    (while (pair? to-do)
      (let ((group (car to-do)))
        (set! to-do (cdr to-do))
        (hash-table-remove! waiting (group-number group))
        (dolist (cell (if (group-cage group)
                          (apply-cage! possibilities (group-cage group))
                          (apply-line! possibilities (group-cells group) (puzzle-size puzzle))))
          (dolist (affected (hash-table-ref (puzzle-groups-of puzzle) cell))
            (unless (hash-table-has? waiting (group-number affected))
              (hash-table-set! waiting (group-number affected) #t)
              (push affected to-do))))))))

; ---------------------------------------------------------------------------
; 4. Solving
; ---------------------------------------------------------------------------

(define (least-settled-cell possibilities size)
  "The unsettled cell with the fewest digits left, or #f if every cell is
settled."
  (let ((best #f))
    (dolist (cell (grid-cells size))
      (let ((count (length (digits-of possibilities cell))))
        (when (and (> count 1)
                   (or (not best) (< count (length (digits-of possibilities best)))))
          (set! best cell))))
    best))

(define (grid-of possibilities size)
  "The solution, as a list of rows, each a list of digits."
  (loop for row from 1 to size
        collect (loop for column from 1 to size
                      collect (car (digits-of possibilities (+ (* 10 row) column))))))

(define *guesses* 0)

(define (kenken-solutions size descriptions &key (limit 2))
  "The puzzle's solutions -- up to limit of them, each a list of rows --
so (length (kenken-solutions ...)) is 1 for a puzzle with exactly one
solution."
  (let ((puzzle (make-kenken size descriptions))
        (found '()))
    (define (search possibilities to-do)
      (when (and (< (length found) limit)
                 (catch 'impossible
                   (rule-out! possibilities puzzle to-do)
                   #t))
        (let ((cell (least-settled-cell possibilities size)))
          (if (not cell)
              (push (grid-of possibilities size) found)
              (dolist (digit (digits-of possibilities cell))
                (let ((guess (copy-of possibilities)))
                  (incf *guesses*)
                  (hash-table-set! (possibilities-digits guess) cell (list digit))
                  ; Only the guessed cell's cage, row, and column need looking at, at first.
                  (search guess (hash-table-ref (puzzle-groups-of puzzle) cell))))))))
    (set! *guesses* 0)
    (search (starting-possibilities puzzle) (puzzle-groups puzzle))
    (reverse found)))

(define (solve-kenken size descriptions)
  "The puzzle's solution, as a list of rows -- the first one found, if
there's more than one -- or #f if there's none."
  (let ((solutions (kenken-solutions size descriptions :limit 1)))
    (if (null? solutions) #f (car solutions))))

; ---------------------------------------------------------------------------
; 5. Drawing a puzzle
; ---------------------------------------------------------------------------
; In a Jupyter notebook, as a grid with each cage outlined and its number
; and operation in its top-left cell; elsewhere, as text:
;
;   +-----+-----+-----+-----+
;   |9+   |3×         |2    |
;   |  4  |  3     1  |  2  |
;   +     +-----+-----+-----+

(define (cage-label cage)
  "The cage's number and operation, as KenKen prints them: 17+, 2−, 12×, 3÷, or just 4."
  (let ((operation (cage-operation cage)))
    (format "{}{}" (cage-target cage)
            (cond ((eq? operation '+) "+") ((eq? operation '-) "−")
                  ((eq? operation '*) "×") ((eq? operation '/) "÷") (else "")))))

(define (cage-lookup cages)
  "A hash table from each cell to its cage."
  (let ((table (make-hash-table)))
    (dolist (cage cages)
      (dolist (cell (cage-cells cage))
        (hash-table-set! table cell cage)))
    table))

(define (show-kenken size descriptions &key (solution '()))
  "Draw the puzzle -- with the digits of solution, a list of rows, if given."
  (let* ((cages (make-cages size descriptions))
         (cage-at (cage-lookup cages))
         (digit-at (lambda (cell)
                     (if (null? solution) ""
                         (list-ref (list-ref solution (- (row-of cell) 1)) (- (column-of cell) 1)))))
         (label-at (lambda (cell)
                     (let ((cage (hash-table-ref cage-at cell)))
                       (if (= cell (apply min (cage-cells cage))) (cage-label cage) ""))))
         (border? (lambda (cell neighbor)       ; whether a cage border runs between them
                    (or (not (hash-table-has? cage-at neighbor))
                        (not (eq? (hash-table-ref cage-at cell) (hash-table-ref cage-at neighbor)))))))
    (display-html (kenken-html size digit-at label-at border?)
                  (kenken-text size digit-at label-at border?))))

(define (kenken-text size digit-at label-at border?)
  (let ((lines '()))
    (define (add! line) (push line lines))
    (define (border-line row)               ; the line above this row
      (string-append
        (apply string-append
               (loop for column from 1 to size
                     collect (let ((cell (+ (* 10 row) column)))
                               (if (or (= row 1) (border? cell (- cell 10))) "+-----" "+     "))))
        "+"))
    (define (cell-line row text-of)
      (string-append
        (apply string-append
               (loop for column from 1 to size
                     collect (let ((cell (+ (* 10 row) column)))
                               (string-append (if (or (= column 1) (border? cell (- cell 1))) "|" " ")
                                              (text-of cell)))))
        "|"))
    (loop for row from 1 to size
          do (add! (border-line row))
             (add! (cell-line row (lambda (cell) (format "{:<5}" (label-at cell)))))
             (add! (cell-line row (lambda (cell) (format "{:^5}" (digit-at cell))))))
    (add! (border-line (+ size 1)))
    (string-join (reverse lines) "\n")))

(define (kenken-html size digit-at label-at border?)
  (define (side cell neighbor)
    (if (border? cell neighbor) "3px solid black" "1px solid #bbb"))
  (define (cell-html cell)
    (format (string-append "<td style=\"width:46px; height:46px; padding:2px; vertical-align:top; "
                           "background:white; color:black; border-top:{}; border-bottom:{}; "
                           "border-left:{}; border-right:{}\">"
                           "<div style=\"font-size:11px; height:13px; text-align:left\">{}</div>"
                           "<div style=\"font-size:24px; text-align:center\">{}</div></td>")
            (side cell (- cell 10)) (side cell (+ cell 10)) (side cell (- cell 1)) (side cell (+ cell 1))
            (label-at cell) (digit-at cell)))
  (string-append
    "<table style=\"border-collapse:collapse\">"
    (apply string-append
           (loop for row from 1 to size
                 collect (string-append
                           "<tr style=\"background:none\">"
                           (apply string-append
                                  (loop for column from 1 to size
                                        collect (cell-html (+ (* 10 row) column))))
                           "</tr>")))
    "</table>"))

; ---------------------------------------------------------------------------
; 6. Some puzzles
; ---------------------------------------------------------------------------

(define (solve-and-show name size descriptions)
  (display (format "{}:\n" name))
  (show-kenken size descriptions)
  (let* ((start (current-time))
         (solutions (kenken-solutions size descriptions)))
    (display (format "\n{} -- {} guesses, {}s:\n"
                     (cond ((null? solutions) "No solution")
                           ((null? (cdr solutions)) "Its one solution")
                           (else "It has more than one solution; here's one"))
                     *guesses* (seconds-between start (current-time))))
    (unless (null? solutions)
      (show-kenken size descriptions :solution (car solutions)))
    (newline)
    (newline)))

(define puzzle-4
  '(((11 21 22) (+ 9))  ((12 13) (* 3))     ((14) (= 2))
    ((23 24 34) (+ 9))  ((31 32 41) (+ 4))  ((33 43 44) (* 18))
    ((42) (= 4))))

(define puzzle-6
  '(((11 12) (+ 9))     ((13 23) (- 1))     ((14 24) (+ 6))     ((15 25) (- 2))
    ((16 26) (* 6))     ((21 22 31) (* 24)) ((32 33) (- 1))     ((34 44 45) (* 48))
    ((35 36 46) (+ 7))  ((41 51) (/ 5))     ((42) (= 3))        ((43 53) (- 2))
    ((52 62) (- 3))     ((54 55 56) (* 90)) ((61) (= 2))        ((63 64) (+ 7))
    ((65 66) (* 12))))

; A harder one: no cell is given, and the cages are bigger.
(define puzzle-9
  '(((11 12) (/ 4))           ((13 14 15 24) (* 420))  ((16 17 27) (+ 13))
    ((18 28) (- 1))           ((19 29 39) (* 96))      ((21 22) (* 63))
    ((23 33 34 43) (* 1008))  ((25 26 35) (* 54))      ((31 32 41 42) (* 42))
    ((36 46 47) (+ 15))       ((37 38 48) (* 96))      ((44 45 54 55) (* 480))
    ((49 59) (- 1))           ((51 52 53) (+ 14))      ((56 57 66) (+ 11))
    ((58 68 69) (+ 14))       ((61 71 72) (+ 20))      ((62 63 73) (+ 13))
    ((64 74) (/ 9))           ((65 75 76 85) (* 480))  ((67 77 78) (+ 16))
    ((79 89 98 99) (+ 19))    ((81 91 92) (+ 16))      ((82 83 84) (+ 9))
    ((86 87 97) (* 48))       ((88) (= 7))             ((93 94 95) (+ 23))
    ((96) (= 7))))

(solve-and-show "A 4 x 4 puzzle" 4 puzzle-4)
(solve-and-show "A 6 x 6 puzzle" 6 puzzle-6)
(solve-and-show "A 9 x 9 puzzle" 9 puzzle-9)
