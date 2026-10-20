; deal.lsp
; ========
; A structured deal as a tree. The root is the collateral, a pool of mortgages, which pays principal each month. That
; principal is divided among the root's children by a split: in order (sequential), or in proportion to what each is still
; owed (pro-rata). Each child can be divided again, to any depth, until the leaves, which are the bonds that trade:
;
;   POOL (the collateral) -- sequential --> A -- sequential --> A1, A2
;                                           B -- pro-rata ----> B1, B2
;
; This file does the principal. (The interest, and the losses, are for later: each of them goes through the same tree by
; rules of its own.)
;
;   (load "deal.lsp")
;
;   (define pool (collateral-from-psa "POOL" 100000000 6.5 :term 360 :age 0 :psa 150))   ; balance, rate in percent
;   (define deal (start-deal "Demo 2026-1" pool))
;   (deal-sequential! deal "POOL" '(("A" 60000000) ("B" 40000000)))         ; the children of POOL, and their balances
;   (deal-pro-rata! deal "B" '(("B1" 10000000) ("B2" 30000000)))           ; and B is divided again
;   (deal-run! deal)                                                        ; the principal each bond gets, each month
;   (deal-check deal)                                                       ; #t, or an error that says what is wrong
;   (display-table (deal-principal-table deal))
;
; THE PARTS. A node (the struct node) has a name, a balance vector and a principal vector, one element a month, and the split
; that divides it among its children, if it has one. Balance[t] is what the node owes at the start of month t (so a balance is
; one element longer), and principal[t] is what it is paid in month t: what the pool pays, or what its parent's split gave it. A
; collateral and a tranche are nodes. A tranche with no split is a bond; with one, it passes on what it is paid.
;
; A split (the struct split) names its children, and what is different about one kind of split from another is its methods, of
; two generic functions (see defgeneric and defmethod). (pay-principal split deal parent t) divides the principal of month t that
; the parent was paid among its children, by calling (pay-child! child t cash [floor]) for each child it pays, which pays what
; the child still owes, down to the floor (0 unless given), up to the cash, and returns the cash left. The method does not call
; the splits of the children: deal-run! walks the tree, so every kind of split does only its own part. (calculate-sizes split
; deal parent) works out how big the children are, as a list of balances in the order of the children, or '() if it is not for
; the split to say (the sizes are those the children were given, which is what the method for split, any kind, does): a PAC split
; sizes the PAC from its parent at two prepayment speeds. To make another kind of split, include split (or a kind there is) and
; write its methods, as sequential-split, pro-rata-split and pac-split have; (call-next-method) calls the method of the kind
; that it extends.
;
; A deal is made in double precision (cents of a balance of hundreds of millions are not kept in single), and sums are checked to
; within deal-tolerance of the pool's balance, which is not an amount of money but a fraction of the pool.

(load "prepayment_model.lsp")

(define deal-tolerance 1e-9)       ; how close, as a fraction of the pool's balance, amounts that should be equal must be

; ---------------------------------------------------------------------------
; The structs
; ---------------------------------------------------------------------------

(defstruct node name balance principal (split '()))
(defstruct (collateral (:include node)) rate term age psa interest)
(defstruct (tranche (:include node)))
(defstruct split children)                                                 ; (a kind of split is a type that includes this one)
(defstruct (sequential-split (:include split)))
(defstruct (pro-rata-split (:include split)))
(defstruct (pac-split (:include split)) low-psa high-psa schedule)
(defstruct deal name (nodes (make-hash-table)) (names '()) root periods)

(defgeneric pay-principal (split deal parent t)
  "Divides the principal of month t that the parent was paid among the children of the split: see the top of the file.")
(defgeneric calculate-sizes (split deal parent)
  "The sizes of the split's children, a list in their order, or '() if the split does not work them out.")

(defmethod calculate-sizes ((split split) deal parent)
  "The children are as big as they were made."
  '())

; ---------------------------------------------------------------------------
; The collateral
; ---------------------------------------------------------------------------

(define (pool-cash-flows balance rate term age psa)
  "The cash flows of a pool of level-pay mortgages, with the PSA prepayment speed: (principal interest balance), each a vector,
the first two one element a month and the balance one longer. balance is the balance now, rate the annual rate in percent, term
the number of months the loans began with and age the months they have gone, so the pool has term - age months to run."
  (let* ((months (- term age))
         (monthly-rate (/ rate 1200.0))
         (principal (make-vector months 0.0))
         (interest (make-vector months 0.0))
         (balances (make-vector (+ months 1) 0.0)))
    (vector-set! balances 0 balance)
    (loop for t from 0 below months
          do (let* ((owed (vector-ref balances t))
                    (interest-due (* owed monthly-rate))
                    (scheduled (min owed (- (payment monthly-rate (- months t) owed) interest-due)))
                    (prepaid (* (smm-from-cpr (cpr (+ age t) psa)) (- owed scheduled)))
                    (paid (min owed (+ scheduled prepaid))))
               (vector-set! interest t interest-due)
               (vector-set! principal t paid)
               (vector-set! balances (+ t 1) (- owed paid))))
    (list principal interest balances)))

(define (collateral-from-psa name balance rate &key (term 360) (age 0) (psa 100))
  "The collateral node for a pool: its balance, its rate in percent, its term and age in months, and its prepayment speed in
percent of the PSA curve (100 is the standard curve, 0 no prepayments). It has its cash flows worked out."
  (unless (and (> term age) (>= age 0))
    (error (format "collateral-from-psa: the age {} must be from 0 up to the term {}" age term)))
  (let ((flows (pool-cash-flows balance rate term age psa)))
    (make-collateral :name name :balance (caddr flows) :principal (car flows) :interest (cadr flows)
                     :rate rate :term term :age age :psa psa)))

; ---------------------------------------------------------------------------
; Building a deal
; ---------------------------------------------------------------------------

(define (start-deal name collateral)
  "A deal whose root is the collateral."
  (unless (eq? (vector-precision) 'double)
    (error "start-deal: a deal is made in double precision: (set-vector-precision! 'double)"))
  (let ((deal (make-deal :name name :root (node-name collateral) :periods (vector-length (node-principal collateral)))))
    (deal-add-node! deal collateral)
    deal))

(define (deal-add-node! deal node)
  "Adds a node to the deal, which has no node of that name yet."
  (when (hash-table-ref (deal-nodes deal) (node-name node))
    (error (format "the deal already has a node called {}" (node-name node))))
  (hash-table-set! (deal-nodes deal) (node-name node) node)
  (deal-names-set! deal (append (deal-names deal) (list (node-name node))))
  node)

(define (get-node deal name)
  "The node of the deal called name."
  (or (hash-table-ref (deal-nodes deal) name)
      (error (format "the deal has no node called {} (it has {})" name (string-join (deal-names deal) " ")))))

(define (deal-add-tranche! deal name balance)
  "Adds a tranche with this starting balance to the deal. It is paid by its parent's split: see deal-add-split!."
  (deal-add-node! deal (make-tranche :name name
                                     :balance (let ((balances (make-vector (+ (deal-periods deal) 1) 0.0)))
                                                (vector-set! balances 0 balance)
                                                balances)
                                     :principal (make-vector (deal-periods deal) 0.0))))

(define (deal-add-split! deal parent-name split)
  "Makes the split divide the parent among the children it names, which are tranches already in the deal. A node has one split,
and its children's balances add up to its own: the split works them out, if it is of a kind that does (see calculate-sizes)."
  (let ((parent (get-node deal parent-name)))
    (unless (null? (node-split parent))
      (error (format "{} already has a split" parent-name)))
    (when (null? (split-children split))
      (error (format "the split of {} has no children" parent-name)))
    (dolist (name (split-children split))
      (get-node deal name)
      (when (or (equal? name (deal-root deal)) (member name (deal-children-names deal)))
        (error (format "{} is already paid by a split: a node is paid by one split, and the collateral by none" name))))
    (let ((sizes (calculate-sizes split deal parent)))
      (unless (null? sizes)
        (for-each (lambda (name size) (vector-set! (node-balance (get-node deal name)) 0 size)) (split-children split) sizes)))
    (deal-check-total deal parent-name
                      (apply + (map (lambda (name) (vector-ref (node-balance (get-node deal name)) 0)) (split-children split))))
    (node-split-set! parent split)
    split))

(define (deal-check-total deal parent-name total)
  "An error unless the balances of a node's children, which add up to total, add up to its own."
  (let ((expected (vector-ref (node-balance (get-node deal parent-name)) 0)))
    (unless (<= (abs (- total expected)) (* deal-tolerance (deal-size deal)))
      (error (format "the children of {} have balances that add up to {}, and {} has {}" parent-name total parent-name expected)))))

(define (deal-split! deal parent-name make-the-split children)
  "Adds a tranche for each of the children, (name balance), and divides the parent among them by the split that
(make-the-split names) makes. Nothing is added if there is something wrong."
  (let ((parent (get-node deal parent-name)))
    (unless (null? (node-split parent))
      (error (format "{} already has a split" parent-name)))
    (dolist (child children)
      (when (hash-table-ref (deal-nodes deal) (car child))
        (error (format "the deal already has a node called {}" (car child)))))
    (unless (= (length (remove-duplicates (map car children))) (length children))
      (error (format "the children of {} are not all called by different names" parent-name)))
    (deal-check-total deal parent-name (apply + (map cadr children))))
  (dolist (child children)
    (deal-add-tranche! deal (car child) (cadr child)))
  (deal-add-split! deal parent-name (make-the-split (map car children))))

(define (deal-sequential! deal parent-name children)
  "Adds the children, a list of (name balance), and pays the parent's principal to them in order: the first until it is paid, then
the next."
  (deal-split! deal parent-name (lambda (names) (make-sequential-split :children names)) children))

(define (deal-pro-rata! deal parent-name children)
  "Adds the children, a list of (name balance), and pays the parent's principal to them in proportion to what each still owes."
  (deal-split! deal parent-name (lambda (names) (make-pro-rata-split :children names)) children))

(define (deal-pac! deal parent-name pac-name companion-name low-psa high-psa)
  "Divides the parent, the collateral or another node, into a PAC and its companion. The PAC is as big as the parent is paid when
the collateral prepays at both of the speeds, low-psa and high-psa (percents of the PSA curve), and is paid on the schedule of the
least it is paid at them. Nothing is added if there is something wrong."
  (let ((parent (get-node deal parent-name)))
    (unless (null? (node-split parent))
      (error (format "{} already has a split" parent-name)))
    (dolist (name (list pac-name companion-name))
      (when (hash-table-ref (deal-nodes deal) name)
        (error (format "the deal already has a node called {}" name))))
    (when (equal? pac-name companion-name)
      (error "the PAC and the companion are called by different names"))
    (let ((split (make-pac-split :children (list pac-name companion-name) :low-psa low-psa :high-psa high-psa)))
      (pac-check-arguments split deal)
      (deal-add-tranche! deal pac-name 0.0)
      (deal-add-tranche! deal companion-name 0.0)
      (deal-add-split! deal parent-name split))))

(define (deal-size deal)
  "The balance of the collateral, which the tolerance is a fraction of."
  (vector-ref (node-balance (get-node deal (deal-root deal))) 0))

(define (deal-children-names deal)
  "The names of the nodes that are paid by a split: every node but the collateral that has been given a parent."
  (append-map (lambda (name)
                (let ((split (node-split (get-node deal name))))
                  (if (null? split) '() (split-children split))))
              (deal-names deal)))

(define (deal-leaves deal)
  "The names of the bonds: the tranches that have no split."
  (filter (lambda (name) (and (tranche? (get-node deal name)) (null? (node-split (get-node deal name)))))
          (deal-names deal)))

; ---------------------------------------------------------------------------
; Paying principal
; ---------------------------------------------------------------------------

(define (node-owed child t)
  "What a node can still be paid in month t: its balance then, less what it has been paid this month so far."
  (max 0.0 (- (vector-ref (node-balance child) t) (vector-ref (node-principal child) t))))

(define (pay-child! child t cash &optional (floor 0.0))
  "Pays the child, in month t, what it is owed, up to the cash, but not so that it owes less than the floor (0 unless given, so
that it is paid off). Returns the cash left."
  (let ((amount (min cash (max 0.0 (- (node-owed child t) floor)))))
    (vector-increment! (node-principal child) t amount)
    (- cash amount)))

(define (check-all-paid! parent t cash deal)
  "An error if a split has principal left that none of its children can be paid."
  (when (> cash (* deal-tolerance (deal-size deal)))
    (error (format "the split of {} has {} of principal left over in month {}: its children are all paid" (node-name parent) cash t))))

(defmethod pay-principal ((split sequential-split) deal parent t)
  "Pays the children in order."
  (let ((cash (vector-ref (node-principal parent) t)))
    (dolist (name (split-children split))
      (set! cash (pay-child! (get-node deal name) t cash)))
    (check-all-paid! parent t cash deal)))

(defmethod pay-principal ((split pro-rata-split) deal parent t)
  "Pays each child its share of the principal, in proportion to what it still owes."
  (let* ((cash (vector-ref (node-principal parent) t))
         (children (map (lambda (name) (get-node deal name)) (split-children split)))
         (total-owed (apply + (map (lambda (child) (node-owed child t)) children)))
         (to-pay (min cash total-owed))
         (shares (map (lambda (child) (if (> total-owed 0.0) (* to-pay (/ (node-owed child t) total-owed)) 0.0)) children)))
    (for-each (lambda (child share) (pay-child! child t share)) children shares)
    (check-all-paid! parent t (- cash to-pay) deal)))

; A PAC and its companion. The PAC is paid on a schedule, which is the least its parent pays in each month when the collateral
; prepays at either of two speeds, so it is paid that, if the collateral pays at any speed between them, and the companion is paid
; what is over, or goes without. The parent is the collateral or any node below it (a second PAC, under the first one's companion).
; The children are the PAC and then the companion. The schedule is the balance the PAC is to have at the start of each
; month; it is worked out, with the sizes, when the split is added: see the calculate-sizes method of pac-split.
(defmethod pay-principal ((split pac-split) deal parent t)
  "Pays the PAC down to the balance it is scheduled to have, then the companion, and then what is left to the PAC."
  (let ((pac (get-node deal (car (split-children split))))
        (companion (get-node deal (cadr (split-children split))))
        (cash (vector-ref (node-principal parent) t)))
    (set! cash (pay-child! pac t cash (vector-ref (pac-split-schedule split) (+ t 1))))
    (set! cash (pay-child! companion t cash))
    (set! cash (pay-child! pac t cash))
    (check-all-paid! parent t cash deal)))

(define (deal-principal-at deal name psa)
  "The principal that the node called name would be paid in each month, as a vector, if the collateral prepaid at psa percent of
the PSA curve: the collateral is run at that speed, and the deal, as it is now, down to the node. The deal itself is not
changed: it is run on copies of its nodes."
  (let ((root (get-node deal (deal-root deal))))
    (unless (and (collateral? root) (not (null? (collateral-rate root))))
      (error "the deal's collateral was not made by collateral-from-psa, so it cannot be run at another speed"))
    (let ((flows (pool-cash-flows (vector-ref (node-balance root) 0) (collateral-rate root) (collateral-term root)
                                  (collateral-age root) psa))
          (copy (make-deal :name (deal-name deal) :root (deal-root deal) :periods (deal-periods deal))))
      (dolist (node-name (deal-names deal))
        (let ((node (copy-node (get-node deal node-name))))
          (node-balance-set! node (vector-copy (node-balance node)))
          (node-principal-set! node (vector-copy (node-principal node)))
          (deal-add-node! copy node)))
      (let ((pool (get-node copy (deal-root deal))))
        (node-principal-set! pool (car flows)))                 ; (the balances are worked out again by the run)
      (deal-run! copy)
      (node-principal (get-node copy name)))))

(define (pac-check-arguments split deal)
  "An error if a PAC split could not be sized: it has two children, its two speeds go from the lower to the higher, and the
collateral can be run at another speed."
  (unless (= (length (split-children split)) 2)
    (error "a PAC split has two children: the PAC and the companion"))
  (unless (< 0 (pac-split-low-psa split) (pac-split-high-psa split))
    (error (format "the PAC's speeds must be from the lower to the higher, above 0, not {} and {}"
                   (pac-split-low-psa split) (pac-split-high-psa split))))
  (let ((root (get-node deal (deal-root deal))))
    (unless (and (collateral? root) (not (null? (collateral-rate root))))
      (error "the deal's collateral was not made by collateral-from-psa, so it cannot be run at another speed"))))

(defmethod calculate-sizes ((split pac-split) deal parent)
  "The size of the PAC is what the parent pays at both of the two speeds of the collateral, month by month the least of the two,
added up; the companion is the rest. (What the parent pays is found by running the deal at each speed: see deal-principal-at.)
Sets the schedule of the PAC, its balance at the start of each month, from that size, less the least each month. Returns
(PAC-size companion-size)."
  (pac-check-arguments split deal)
  (let* ((balance (vector-ref (node-balance parent) 0))
         (slow (deal-principal-at deal (node-name parent) (pac-split-low-psa split)))
         (fast (deal-principal-at deal (node-name parent) (pac-split-high-psa split)))
         (least (vector-where (< slow fast) slow fast))
         (size (vector-sum least))
         (schedule (make-vector (+ (vector-length least) 1) size)))
    (loop for t from 0 below (vector-length least)
          do (vector-set! schedule (+ t 1) (- (vector-ref schedule t) (vector-ref least t))))
    (pac-split-schedule-set! split schedule)
    (list size (- balance size))))

(define (walk-principal! deal node t)
  "Divides what the node was paid in month t among its children, and then what each of them was paid among theirs, to the leaves."
  (let ((split (node-split node)))
    (unless (null? split)
      (pay-principal split deal node t)
      (dolist (name (split-children split))
        (walk-principal! deal (get-node deal name) t)))))

(define (deal-run! deal)
  "Works out the principal that each node is paid, in every month, and its balance. It can be run again after a change."
  (dolist (name (deal-names deal))
    (let ((node (get-node deal name)))
      (unless (eq? name (deal-root deal))
        (vector-fill! (node-principal node) 0.0))))
  (loop for t from 0 below (deal-periods deal)
        do (begin
             (walk-principal! deal (get-node deal (deal-root deal)) t)
             (dolist (name (deal-names deal))
               (let ((node (get-node deal name)))
                 (vector-set! (node-balance node) (+ t 1)
                              (- (vector-ref (node-balance node) t) (vector-ref (node-principal node) t)))))))
  deal)

; ---------------------------------------------------------------------------
; Looking at it
; ---------------------------------------------------------------------------

(define (deal-check deal)
  "#t if the principal of the deal adds up, or an error that says where it does not: in every month, what the children of a split
were paid adds up to what the parent was paid, and no balance has gone below 0. It is within deal-tolerance of the pool."
  (let ((tolerance (* deal-tolerance (deal-size deal))))
    (dolist (name (deal-names deal))
      (let* ((node (get-node deal name))
             (split (node-split node)))
        (loop for t from 0 to (deal-periods deal)
              do (when (< (vector-ref (node-balance node) t) (- tolerance))
                   (error (format "{} owes {} in month {}: it has been paid more than it was owed" name (vector-ref (node-balance node) t) t))))
        (unless (null? split)
          (loop for t from 0 below (deal-periods deal)
                do (let ((paid (apply + (map (lambda (child) (vector-ref (node-principal (get-node deal child)) t)) (split-children split)))))
                     (when (> (abs (- paid (vector-ref (node-principal node) t))) tolerance)
                       (error (format "the children of {} were paid {} in month {}, and {} was paid {} (has deal-run! been called?)"
                                      name paid t name (vector-ref (node-principal node) t)))))))))
    #t))

(define (deal-principal-table deal)
  "A table of the principal paid in each month, one row for a month from 1, with a column for each node."
  (apply make-table
         (cons "month" (cons (+ 1 (vector-range (deal-periods deal)))
                             (append-map (lambda (name) (list name (node-principal (get-node deal name)))) (deal-names deal))))))

(define (deal-balance-table deal)
  "A table of the balance of each node at the start of each month, with a row for the end of the last month too: month 0 is the
start."
  (apply make-table
         (cons "month" (cons (vector-range (+ 1 (deal-periods deal)))
                             (append-map (lambda (name) (list name (node-balance (get-node deal name)))) (deal-names deal))))))
