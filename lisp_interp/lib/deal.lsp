; deal.lsp
; ========
; A structured deal as a tree. The root is the collateral, a pool of mortgages, which pays interest and principal each month.
; Each is divided among the root's children by a split: in order (sequential), in proportion to what each is still owed
; (pro-rata), and so on. Each child can be divided again, to any depth, until the leaves, which are the bonds that trade:
;
;   POOL (the collateral) -- sequential --> A -- sequential --> A1, A2
;                                           B -- floater and inverse floater --> B1, B2
;
; A deal can have more than one piece of collateral, each the root of a tree of its own. This file does the interest and the
; principal. (The losses are for later: they go through the same tree by rules of their own.)
;
;   (load "deal.lsp")
;
;   (define pool (collateral-from-psa "POOL" 100000000 6.5 :term 360 :age 0 :psa 150))   ; balance, rate in percent
;   (define deal (start-deal "Demo 2026-1" pool))
;   (deal-sequential! deal "POOL" '(("A" 60000000) ("B" 40000000)))         ; the children of POOL, and their balances
;   (deal-floater-inverse! deal "B" "B1" "B2" :cap 0.09 :margin 0.005)     ; B is divided again, into a floater and an inverse
;   (deal-run! deal :index (make-vector 360 0.04))                          ; the interest and the principal each bond gets, each month
;   (deal-check deal)                                                       ; #t, or an error that says what is wrong
;   (display-table (deal-principal-table deal))
;   (display-table (deal-interest-table deal))
;
; THE PARTS. A node (the struct node) has a name; a balance vector, a principal vector and an interest vector, one element a month;
; a coupon; and the split that divides it among its children, if it has one. Balance[t] is what the node owes at the start of
; month t (so a balance is one element longer), principal[t] is what it is paid in month t, and so is interest[t]: what the pool
; pays, or what its parent's split gave it. A collateral and a tranche are nodes. A tranche with no split is a bond; with one, it
; passes on what it is paid. The coupon is a function of the index, a number (0.04 is 4%) for the month: (coupon index) is the
; annual rate of interest that the node is owed, on its balance at the start of the month, a twelfth of it. For the collateral it
; is a constant, which is the interest it pays (the cash flows of the collateral are given, and are taken as they are). A split
; gives its children coupons when it is added, which for most kinds are the parent's, and a floater's or an inverse floater's are
; formulas that it works out with the sizes.
;
; A split (the struct split) names its children, and what is different about one kind of split from another is its methods, of
; two generic functions (see defgeneric and defmethod). (pay-principal split deal parent t) divides the principal of month t that
; the parent was paid among its children, by calling (pay-child! child t cash [floor]) for each child it pays, which pays what
; the child still owes, down to the floor (0 unless given), up to the cash, and returns the cash left. The method does not call
; the splits of the children: deal-run! walks the tree, so every kind of split does only its own part. (pay-interest split deal
; parent t) does the same for the interest, which is paid before the principal each month (an accrual bond, which is to come, is
; paid in principal what it accrues). (calculate-sizes split deal parent) works out how big the children are, as a list of
; balances in the order of the children, or '() if it is not for the split to say (the sizes are those the children were given,
; which is what the method for split, any kind, does): a PAC split sizes the PAC from its parent at two prepayment speeds, and a
; floater and inverse floater split sizes them from the cap. (assign-coupons split deal parent) gives the children their
; coupons, which for a split of any kind is the parent's. To make another kind of split, include split (or a kind there is) and
; write its methods, as sequential-split, pro-rata-split, pac-split and the others have; (call-next-method) calls the method of
; the kind that it extends.
;
; A split is added in two steps, so that the first can be looked at: a plan (a split-plan: the tranches to add and the split) is made by
; sequential-plan, pac-plan and the others, and deal-add-plan! adds it; deal-sequential! and the others are the two together. A split that is in
; the deal is changed by deal-replace-split!, which works out what is below it again, and taken away, with what is below it, by
; deal-delete-split!. deal-outline is the deal as a table, a row for each node, each below its parent. lib/deal_builder.lsp is a way to do
; all of that by clicking, in a notebook.
;
; A deal is made in double precision (cents of a balance of hundreds of millions are not kept in single), and sums are checked to
; within deal-tolerance of the pool's balance, which is not an amount of money but a fraction of the pool.
;

(require "prepayment_model.lsp")

(define deal-tolerance 1e-9)       ; how close, as a fraction of the pool's balance, amounts that should be equal must be

; ---------------------------------------------------------------------------
; The structs
; ---------------------------------------------------------------------------

(defstruct node name balance principal interest accrual loss shortfall coupon (split '())
  (z-flag #f)                ; a Z (accrual) bond: its interest is not paid but added to its balance, and pays the bonds ahead of it
  (notional-flag #f)         ; an interest-only bond: a notional balance that follows another's, interest, and no principal
  (follows '()) (share 1.0)) ; the name of the node whose balance a notional bond follows, and what share of it

(defstruct (collateral (:include node)) rate term age psa)   ; (rate, term, age and psa are those collateral-from-psa made it from)

(defstruct (tranche (:include node)))

; loss-rule says how the split divides a loss among its children: reverse (the last first, up to what each owes), forward (the first
; first), or pro-rata (by what each owes)
(defstruct split children (loss-rule 'reverse))                           ; (a kind of split is a type that includes this one)

(defstruct (sequential-split (:include split)) (accretion-to '()))   ; (the bond that what the Z bonds accrue is paid to first)
(defstruct (pro-rata-split (:include split)) (loss-rule 'pro-rata))
(defstruct (pac-split (:include split)) low-psa high-psa schedule)

; the floater and the inverse floater are paid principal pro rata, so that their sizes stay in the proportion that makes their
; coupons, together, the parent's whatever the index is; leverage and constant are what the sizes and the cap give
(defstruct (floater-inverse-split (:include pro-rata-split)) cap margin index-name leverage constant)

; the premium bond has the higher coupon than the parent, and the discount bond a lower, and the sizes make them, together, the parent's
(defstruct (premium-discount-split (:include pro-rata-split)) premium-coupon discount-coupon)

; an interest-only bond and a principal-only bond: both are as big as the parent, the IO's balance is a notional one that follows the
; PO's, the PO is paid all the principal, and the coupon of the parent, less io-coupon, is the PO's ('() is all of it the IO's)
(defstruct (io-po-split (:include split)) (io-coupon '()))

(defstruct deal name (nodes (make-hash-table)) (names '()) (roots '()) periods (index '()) (shortfalls #f))

(defgeneric pay-principal (split deal parent t)
  "Divides the principal of month t that the parent was paid among the children of the split: see the top of the file.")

(defgeneric pay-interest (split deal parent t)
  "Divides the interest of month t that the parent was paid among the children of the split.")

(defgeneric calculate-sizes (split deal parent)
  "The sizes of the split's children, a list in their order, or '() if the split does not work them out.")

(defgeneric assign-coupons (split deal parent)
  "Gives the children of the split their coupons.")

(defgeneric allocate-loss (split deal parent t)
  "Divides the loss of month t that the parent was allocated among the children of the split, by the loss rule of the split.")

(defgeneric check-split (split deal parent)
  "An error if the split cannot divide the parent: its children, which are in the deal, are not as the kind of split needs.")

(defgeneric split-label (split)
  "A few words that say what kind of split it is, for the outline of the deal: \"sequential\", \"PAC and companion\".")

(defmethod calculate-sizes ((split split) deal parent)
  "The children are as big as they were made."
  '())

(defmethod assign-coupons ((split split) deal parent)
  "The children have the coupon of the parent."
  (dolist (name (split-children split))
    (node-coupon-set! (get-node deal name) (node-coupon parent))))

(define (constant-coupon rate)
  "A coupon that is this rate, a decimal (0.06 is 6%), whatever the index is."
  (lambda (index) rate))

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
   percent of the PSA curve (100 is the standard curve, 0 no prepayments). It has its cash flows worked out, and pays its interest at its
   rate (that is its coupon, as a decimal). Collateral from another source is made with make-collateral, with its balance, principal and
   interest vectors and its coupon (see constant-coupon)."
  (unless (and (> term age) (>= age 0))
    (error (format "collateral-from-psa: the age {} must be from 0 up to the term {}" age term)))
  (let ((flows (pool-cash-flows balance rate term age psa)))
    (make-collateral :name name :balance (caddr flows) :principal (car flows) :interest (cadr flows)
                     :coupon (constant-coupon (/ rate 100.0)) :rate rate :term term :age age :psa psa)))

; ---------------------------------------------------------------------------
; Building a deal
; ---------------------------------------------------------------------------

(define (start-deal name collateral &key (shortfalls #f))
  "A deal whose root is the collateral. (More collateral, each the root of a tree of its own, is added by deal-add-collateral!.) With
   :shortfalls #t the interest that is not enough to pay what the bonds are owed is a shortfall of the bonds that go without, carried
   forward, instead of an error: see \"Losses and shortfalls\", in the library manual."
  (unless (eq? (vector-precision) 'double)
    (error "start-deal: a deal is made in double precision: (set-vector-precision! 'double)"))
  (unless (collateral? collateral)
    (error (format "start-deal: the collateral is made by collateral-from-psa or make-collateral, not {}" collateral)))
  (let ((deal (make-deal :name name :periods (vector-length (node-principal collateral)) :shortfalls shortfalls)))
    (deal-add-collateral! deal collateral)
    deal))

(define (deal-add-collateral! deal collateral)
  "Adds a piece of collateral to the deal, the root of a tree of its own. It pays for as many months as the rest of the collateral does."
  (unless (collateral? collateral)
    (error (format "deal-add-collateral!: expected collateral, made by collateral-from-psa or make-collateral, not {}" collateral)))
  (unless (= (vector-length (node-principal collateral)) (deal-periods deal))
    (error (format "{} pays for {} months, and the rest of the collateral for {}: give them all the same number of months (zeros after the last)"
                   (node-name collateral) (vector-length (node-principal collateral)) (deal-periods deal))))
  (when (and (not (null? (node-coupon collateral))) (not (vector? (node-interest collateral))))
    (error (format "{} has a coupon, and needs the interest it pays: make-collateral :interest, a vector for the months" (node-name collateral))))
  (deal-add-node! deal collateral)
  (deal-roots-set! deal (append (deal-roots deal) (list (node-name collateral))))
  collateral)

(define (deal-add-node! deal node)
  "Adds a node to the deal, which has no node of that name yet."
  (when (hash-table-ref (deal-nodes deal) (node-name node))
    (error (format "the deal already has a node called {}" (node-name node))))
  (unless (vector? (node-accrual node))
    (node-accrual-set! node (make-vector (deal-periods deal) 0.0)))
  (unless (vector? (node-shortfall node))
    (node-shortfall-set! node (make-vector (deal-periods deal) 0.0)))
  (if (vector? (node-loss node))
      (unless (= (vector-length (node-loss node)) (deal-periods deal))
        (error (format "{} has a loss for {} months, and the deal has {}" (node-name node) (vector-length (node-loss node)) (deal-periods deal))))
      (node-loss-set! node (make-vector (deal-periods deal) 0.0)))
  (hash-table-set! (deal-nodes deal) (node-name node) node)
  (deal-names-set! deal (append (deal-names deal) (list (node-name node))))
  node)

(define (get-node deal name)
  "The node of the deal called name."
  (or (hash-table-ref (deal-nodes deal) name)
      (error (format "the deal has no node called {} (it has {})" name (string-join (deal-names deal) " ")))))

(define (deal-add-tranche! deal name balance &key (z #f) (notional #f) (follows '()))
  "Adds a tranche with this starting balance to the deal. It is paid by its parent's split: see deal-add-split!. :z #t makes it a Z
   bond, which accrues its interest, and :notional #t an interest-only bond, which is a notional balance that follows (:follows) the
   balance of another node."
  (deal-add-node! deal (make-tranche :name name :z-flag z :notional-flag notional :follows follows
                                     :balance (let ((balances (make-vector (+ (deal-periods deal) 1) 0.0)))
                                                (vector-set! balances 0 balance)
                                                balances)
                                     :principal (make-vector (deal-periods deal) 0.0)
                                     :interest (make-vector (deal-periods deal) 0.0))))

(define (deal-add-split! deal parent-name split)
  "Makes the split divide the parent among the children it names, which are tranches already in the deal. A node has one split,
   and its children's balances add up to its own: the split works them out, if it is of a kind that does (see calculate-sizes). The
   children are given their coupons (see assign-coupons). The children of a notional (interest-only) bond are notional too, and follow
   it, each in the share of it that it is."

  (let ((parent (get-node deal parent-name)))
    (unless (null? (node-split parent))
      (error (format "{} already has a split" parent-name)))
    (when (null? (split-children split))
      (error (format "the split of {} has no children" parent-name)))
    (dolist (name (split-children split))
      (get-node deal name)
      (when (or (member name (deal-roots deal)) (member name (deal-children-names deal)))
        (error (format "{} is already paid by a split: a node is paid by one split, and the collateral by none" name))))
    (deal-size-split! deal parent split)
    (node-split-set! parent split)
    split))

(define (deal-size-split! deal parent split &key (rescale #f))
  "Checks that the split can divide the parent, and gives its children their balances, notional shares and coupons: the balances
   are those the split works out (see calculate-sizes), or the ones they have, which must add up to the parent's. With :rescale #t
   the balances that they have are made to add up to the parent's, each the share of it that it was, for a split that is being kept
   when its parent has changed size."
  (check-split split deal parent)
  (let ((sizes (calculate-sizes split deal parent))
        (leading (filter (lambda (name) (not (member (node-follows (get-node deal name)) (split-children split)))) (split-children split))))
    (cond ((not (null? sizes))
           (for-each (lambda (name size) (vector-set! (node-balance (get-node deal name)) 0 size)) (split-children split) sizes))
          (rescale
           (let ((have (apply + (map (lambda (name) (vector-ref (node-balance (get-node deal name)) 0)) leading)))
                 (want (vector-ref (node-balance parent) 0)))
             (when (and (= have 0.0) (not (= want 0.0)))
               (error (format "the children of {} have no balance to scale to the {} that {} has" (node-name parent) want (node-name parent))))
             (unless (= have 0.0)
               (dolist (name leading)
                 (let ((balances (node-balance (get-node deal name))))
                   (vector-set! balances 0 (* (vector-ref balances 0) (/ want have)))))))))
    (deal-check-total deal (node-name parent)
                      (apply + (map (lambda (name) (vector-ref (node-balance (get-node deal name)) 0)) leading)))
    (when (node-notional-flag parent)
      (dolist (name (split-children split))
        (let ((child (get-node deal name)))
          (node-notional-flag-set! child #t)
          (node-follows-set! child (node-name parent))
          (node-share-set! child (if (= (vector-ref (node-balance parent) 0) 0.0)
                                     0.0
                                     (/ (vector-ref (node-balance child) 0) (vector-ref (node-balance parent) 0)))))))
    (assign-coupons split deal parent)))

(define (deal-check-total deal parent-name total)
  "An error unless the balances of a node's children, which add up to total, add up to its own."
  (let ((expected (vector-ref (node-balance (get-node deal parent-name)) 0)))
    (unless (<= (abs (- total expected)) (* deal-tolerance (deal-size deal)))
      (error (format "the children of {} have balances that add up to {}, and {} has {}" parent-name total parent-name expected)))))

; A split is made in two steps, so that the first can be done and looked at without the second: a plan says what is to be added under
; a parent (the tranches, with the balances they are given, and the split that divides the parent among them), and adding the plan
; adds it. There is a function for the plan of each kind of split, and one to add it, deal-add-plan!, and the functions that
; add a split in one step, deal-sequential! and the others, are those two. (The plan of a split of a kind that is your own is
; made with make-split-plan.)
(defstruct split-plan tranches split)     ; (tranches: a list of the arguments of deal-add-tranche!, each (name balance :z ...))

(define (deal-add-plan! deal parent-name plan)
  "Adds the tranches of the plan, and divides the parent by its split among them. If something is wrong none of it is added."
  (deal-check-new-children deal parent-name (map car (split-plan-tranches plan)))
  (dolist (tranche (split-plan-tranches plan))
    (apply deal-add-tranche! deal tranche))
  (catch-error (deal-add-split! deal parent-name (split-plan-split plan))
    (message)
    (dolist (tranche (split-plan-tranches plan))
      (deal-forget-node! deal (car tranche)))
    (error message))
  (split-plan-split plan))

(define (split-plan-sizes deal parent plan)
  "The balances of the tranches of the plan, as a list in their order, if it is added to the parent: those the split works out (see
   calculate-sizes), or the balances that they were given. The deal is not changed."
  (let ((sizes (calculate-sizes (split-plan-split plan) deal parent)))
    (if (null? sizes)
        (map cadr (split-plan-tranches plan))
        sizes)))

(define (deal-forget-node! deal name)
  "Takes a node out of the deal again: for what was added and then could not be used."
  (hash-table-remove! (deal-nodes deal) name)
  (deal-names-set! deal (filter (lambda (n) (not (equal? n name))) (deal-names deal))))

(define (deal-check-new-children deal parent-name names)
  "An error unless the parent is in the deal with no split yet, and the names are new and different: for a split that adds tranches."
  (unless (null? (node-split (get-node deal parent-name)))
    (error (format "{} already has a split" parent-name)))
  (dolist (name names)
    (when (hash-table-ref (deal-nodes deal) name)
      (error (format "the deal already has a node called {}" name))))
  (unless (= (length (remove-duplicates names)) (length names))
    (error (format "the children of {} are not all called by different names" parent-name))))

(define (child-tranche child)
  "The arguments of deal-add-tranche! for a child given as (name balance) or (name balance z): the Z bonds are those marked z."
  (cond ((= (length child) 2) (list (car child) (cadr child)))
        ((and (= (length child) 3) (eq? (caddr child) 'z)) (list (car child) (cadr child) :z #t))
        (else (error (format "a child is (name balance), or (name balance z) for a Z bond, not {}" child)))))

(define (sequential-plan children &key (accretion-to '()) (losses 'reverse))
  "The plan of a sequential split into the children, a list of (name balance) or (name balance z): see deal-sequential!."
  (make-split-plan :tranches (map child-tranche children)
                   :split (make-sequential-split :children (map car children) :accretion-to accretion-to :loss-rule losses)))

(define (pro-rata-plan children &key (losses 'pro-rata))
  "The plan of a pro-rata split into the children, a list of (name balance): see deal-pro-rata!."
  (make-split-plan :tranches (map child-tranche children)
                   :split (make-pro-rata-split :children (map car children) :loss-rule losses)))

(define (pac-plan pac-name companion-name low-psa high-psa &key (losses 'reverse))
  "The plan of a split into a PAC and its companion, which are as big as the parent's principal at the two speeds says: see deal-pac!."
  (make-split-plan :tranches (list (list pac-name 0.0) (list companion-name 0.0))
                   :split (make-pac-split :children (list pac-name companion-name) :low-psa low-psa :high-psa high-psa :loss-rule losses)))

(define (floater-inverse-plan floater-name inverse-name &key cap (margin 0.0) (index-name '()))
  "The plan of a split into a floater and an inverse floater: see deal-floater-inverse!."
  (when (null? cap)
    (error "floater-inverse-plan: give the :cap of the floater, a decimal such as 0.09"))
  (make-split-plan :tranches (list (list floater-name 0.0) (list inverse-name 0.0))
                   :split (make-floater-inverse-split :children (list floater-name inverse-name) :cap cap :margin margin
                                                      :index-name index-name)))

(define (premium-discount-plan premium-name discount-name &key premium-coupon discount-coupon)
  "The plan of a split into a premium bond and a discount bond: see deal-premium-discount!."
  (when (or (null? premium-coupon) (null? discount-coupon))
    (error "premium-discount-plan: give the :premium-coupon and the :discount-coupon, decimals such as 0.08 and 0.04"))
  (make-split-plan :tranches (list (list premium-name 0.0) (list discount-name 0.0))
                   :split (make-premium-discount-split :children (list premium-name discount-name)
                                                       :premium-coupon premium-coupon :discount-coupon discount-coupon)))

(define (io-po-plan io-name po-name &key (io-coupon '()))
  "The plan of a split into an interest-only bond and a principal-only bond: see deal-io-po!."
  (make-split-plan :tranches (list (list io-name 0.0 :notional #t :follows po-name) (list po-name 0.0))
                   :split (make-io-po-split :children (list io-name po-name) :io-coupon io-coupon)))

(define (deal-sequential! deal parent-name children &key (accretion-to '()) (losses 'reverse))
  "Adds the children, a list of (name balance), and pays the parent's principal to them in order: the first until it is paid, then
   the next. A child written (name balance z) is a Z bond: its interest is not paid but added to its balance, and what it accrues is paid,
   as principal, to the bonds in the order, and the Z bond is paid, in its place in the order, what is left. :accretion-to is the
   name of a bond that is paid what the Z bonds accrue first, before the order: an accretion directed bond. :losses is how a loss is divided
   among the children: reverse (the default: the last child is written down first), forward, or pro-rata."
  (deal-add-plan! deal parent-name (sequential-plan children :accretion-to accretion-to :losses losses)))

(define (deal-pro-rata! deal parent-name children &key (losses 'pro-rata))
  "Adds the children, a list of (name balance), and pays the parent's principal to them in proportion to what each still owes. :losses
   is how a loss is divided among them: pro-rata (the default), reverse or forward."
  (deal-add-plan! deal parent-name (pro-rata-plan children :losses losses)))

(define (deal-pac! deal parent-name pac-name companion-name low-psa high-psa &key (losses 'reverse))
  "Divides the parent, the collateral or another node, into a PAC and its companion. The PAC is as big as the parent is paid when
   the collateral prepays at both of the speeds, low-psa and high-psa (percents of the PSA curve), and is paid on the schedule of the
   least it is paid at them. :losses is how a loss is divided between the two: reverse (the default: the companion is written down first),
   forward or pro-rata. Nothing is added if there is something wrong."
  (deal-add-plan! deal parent-name (pac-plan pac-name companion-name low-psa high-psa :losses losses)))

(define (deal-floater-inverse! deal parent-name floater-name inverse-name &key cap (margin 0.0) (index-name '()))
  "Divides the parent, which has a fixed coupon, into a floater and an inverse floater. The floater's coupon is the index plus the
   margin, to the cap, and the inverse floater's is what makes the two, together, pay the parent's coupon whatever the index is: the
   floater is as big as the parent's coupon is of the cap, and the inverse floater is the rest. Their principal is paid pro rata,
   which keeps them in that proportion. The cap is a decimal (0.09 is 9%), above the parent's coupon, and the margin is a decimal
   (0.005 is half a percent) below it. The index is a number for each month given to deal-run!, with :index; index-name is for whoever
   reads it, and the index is clamped at 0. Nothing is added if there is something wrong."
  (deal-add-plan! deal parent-name (floater-inverse-plan floater-name inverse-name :cap cap :margin margin :index-name index-name)))

(define (deal-premium-discount! deal parent-name premium-name discount-name &key premium-coupon discount-coupon)
  "Divides the parent, which has a fixed coupon, into a premium bond, with a coupon above the parent's, and a discount bond, with a
   coupon below it, by the sizes that make the two, together, pay the parent's coupon. Their principal is paid pro rata, which keeps them
   in that proportion. The coupons are decimals (0.08 is 8%). Nothing is added if there is something wrong."
  (deal-add-plan! deal parent-name (premium-discount-plan premium-name discount-name
                                                           :premium-coupon premium-coupon :discount-coupon discount-coupon)))

(define (deal-io-po! deal parent-name io-name po-name &key (io-coupon '()))
  "Divides the parent into an interest-only bond and a principal-only bond. Both are as big as the parent: the PO is paid all of the
   parent's principal, and the IO has a notional balance that follows the PO's, and no principal. The IO is paid the parent's coupon on its
   notional balance, and the PO none, unless :io-coupon (a decimal) is given, when the IO is paid that, and the PO the rest of the parent's
   coupon. The parent may be any node but a Z bond, an IO or a PO. Nothing is added if there is something wrong."
  (deal-add-plan! deal parent-name (io-po-plan io-name po-name :io-coupon io-coupon)))

; ---------------------------------------------------------------------------
; Changing a split, and taking one away
; ---------------------------------------------------------------------------
;
; A split that is changed is replaced by the plan of another (a plan is for the same parent; see split-plan): the tranches it names that
; are in the deal already stay, with what is under them, and so do those it leaves out that have nothing under them; the others are new.
; The children are given their sizes and coupons again, and so are the children of the splits below them, and so on to the leaves, because
; what a split works out depends on the size and the coupon of its parent (a split that was given the sizes of its children, which are
; not worked out, keeps each in the share of the parent that it was). It is tried on a copy of the deal first, so that if anything is
; wrong the deal is as it was.

(define (deal-update-tranche! deal name balance &key (z #f) (notional #f) (follows '()))
  "Gives a tranche that is in the deal the balance and the flags that deal-add-tranche! gives a new one."
  (let ((node (get-node deal name)))
    (vector-set! (node-balance node) 0 balance)
    (node-z-flag-set! node z)
    (node-notional-flag-set! node notional)
    (node-follows-set! node follows)
    node))

(define (deal-trial-copy deal)
  "A copy of the deal to try a change on: the same nodes and splits, copied, with balances of their own. (The other vectors, of what is
   paid, are shared: a change of a split does not touch them.)"
  (let ((copy (make-deal :name (deal-name deal) :periods (deal-periods deal) :index (deal-index deal)
                         :shortfalls (deal-shortfalls deal))))
    (dolist (name (deal-names deal))
      (let ((node (copy-node (get-node deal name))))
        (node-balance-set! node (vector-copy (node-balance node)))
        (unless (null? (node-split node))
          (node-split-set! node (copy-split (node-split node))))
        (hash-table-set! (deal-nodes copy) name node)))
    (deal-names-set! copy (deal-names deal))
    (deal-roots-set! copy (deal-roots deal))
    copy))

(define (deal-resize-below! deal node)
  "Gives the children of the node's split their balances, notional shares and coupons again, and then the children of theirs, and so on
   down the tree: for after the node has changed its size or its coupon."
  (let ((split (node-split node)))
    (unless (null? split)
      (deal-size-split! deal node split :rescale #t)
      (dolist (name (split-children split))
        (deal-resize-below! deal (get-node deal name))))))

(define (deal-install-plan! deal parent-name plan)
  "Replaces the split of the parent by the plan's, and works out what is below it again. Whatever is wrong is an error, and the deal
   is half changed (see deal-replace-split!, which tries it first on a copy)."
  (let* ((parent (get-node deal parent-name))
         (old (node-split parent))
         (names (map car (split-plan-tranches plan)))
         (kept (if (null? old) '() (split-children old))))
    (when (null? old)
      (error (format "{} has no split to change: add one" parent-name)))
    (when (null? names)
      (error (format "the split of {} has no children" parent-name)))
    (unless (= (length (remove-duplicates names)) (length names))
      (error (format "the children of {} are not all called by different names" parent-name)))
    (dolist (name names)
      (when (and (not (member name kept)) (hash-table-ref (deal-nodes deal) name))
        (error (format "the deal already has a node called {}" name))))
    (dolist (name kept)
      (unless (or (member name names) (null? (node-split (get-node deal name))))
        (error (format "{} is divided, so it cannot be left out: take away its split first" name))))
    (dolist (name kept)
      (unless (member name names)
        (deal-forget-node! deal name)))
    (node-split-set! parent '())
    (dolist (tranche (split-plan-tranches plan))
      (if (member (car tranche) kept)
          (apply deal-update-tranche! deal tranche)
          (apply deal-add-tranche! deal tranche)))
    (deal-size-split! deal parent (split-plan-split plan))
    (node-split-set! parent (split-plan-split plan))
    (dolist (name names)
      (deal-resize-below! deal (get-node deal name)))
    (split-plan-split plan)))

(define (deal-replace-split! deal parent-name plan)
  "Changes the split of the parent to the plan's: its children are as the plan says (those that are in the deal already stay, with what is
   under them), and they, and what is under them, have their sizes and coupons worked out again. Nothing is changed if something is wrong
   (a tranche that is left out that has a split under it, a size that cannot be, and so on)."
  (deal-trial-of-plan deal parent-name plan)
  (deal-install-plan! deal parent-name plan))

(define (deal-trial-of-plan deal parent-name plan)
  "A copy of the deal with the plan applied to the parent: added, if the parent has no split, and replacing the split, if it has. The
   deal itself is not changed, so that it can be looked at (what would be the sizes?), and it is an error if the plan cannot be applied."
  (let ((trial (deal-trial-copy deal)))
    (if (null? (node-split (get-node trial parent-name)))
        (deal-add-plan! trial parent-name plan)
        (deal-install-plan! trial parent-name plan))
    trial))

(define (deal-delete-split! deal parent-name)
  "Takes away the split of the parent, and every node below it, to any depth: the parent is a bond again. Returns the names of the
   nodes that were taken away."
  (let ((parent (get-node deal parent-name)))
    (when (null? (node-split parent))
      (error (format "{} has no split to take away" parent-name)))
    (let ((below (cdr (deal-tree-names deal parent-name))))
      (node-split-set! parent '())
      (dolist (name below)
        (deal-forget-node! deal name))
      below)))

(define (deal-size deal)
  "The balance of all the collateral, which the tolerance is a fraction of."
  (apply + (map (lambda (name) (vector-ref (node-balance (get-node deal name)) 0)) (deal-roots deal))))

(define (deal-tree-names deal root-name)
  "The names of a tree of the deal: its root, and the nodes under it, at any depth."
  (let ((split (node-split (get-node deal root-name))))
    (cons root-name
          (if (null? split) '() (append-map (lambda (child) (deal-tree-names deal child)) (split-children split))))))

(define (deal-root-of deal name)
  "The name of the collateral at the root of the tree that the node called name is in, or #f if it is in none: a tranche that has not
   been given a parent."
  (find-if (lambda (root) (member name (deal-tree-names deal root))) (deal-roots deal)))

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
; Coupons, and paying interest
; ---------------------------------------------------------------------------

(define (deal-index-at deal t)
  "The index in month t, the number given to deal-run! with :index, or '() if it was not given one."
  (let ((index (deal-index deal)))
    (if (null? index) '() (vector-ref index t))))

(define (node-coupon-rate deal node t)
  "The annual rate of interest that a node is owed in month t, a decimal: its coupon, at the index of the month."
  (when (null? (node-coupon node))
    (error (format "{} has no coupon: the collateral needs one (see constant-coupon)" (node-name node))))
  ((node-coupon node) (deal-index-at deal t)))

(define (node-interest-due deal node t)
  "The interest that a node is owed in month t: a twelfth of its coupon, of its balance at the start of the month."
  (* (vector-ref (node-balance node) t) (/ (node-coupon-rate deal node t) 12.0)))

(define (index-rate index)
  "The index, for a coupon that floats: 0 if it is negative. An error if the deal was run without one."
  (when (null? index)
    (error "a bond of this deal has a floating rate: give deal-run! an :index, a number for each month, or one number"))
  (max 0.0 index))

(define (parent-coupon-rate parent what)
  "The fixed coupon of a node that is to be divided into bonds with coupons that float or differ: an error if it has none, or it is
not the same at every index."
  (when (null? (node-coupon parent))
    (error (format "{} has no coupon, which {} split divides: the collateral needs one (see constant-coupon)" (node-name parent) what)))
  (let ((rate ((node-coupon parent) 0.0)))
    (unless (= rate ((node-coupon parent) 0.05))
      (error (format "the coupon of {} floats, and {} split divides a node with a fixed coupon" (node-name parent) what)))
    rate))

(define (interest-carried deal node t)
  "What a node was owed in interest in the month before and not paid, with a month's interest on it at its coupon: it is owed that too."
  (if (= t 0)
      0.0
      (* (vector-ref (node-shortfall node) (- t 1)) (+ 1.0 (/ (node-coupon-rate deal node t) 12.0)))))

(define (node-interest-owed deal node t)
  "What a node is owed in interest in month t. A bond (a node with no split under it) is owed a twelfth of its coupon, of its balance at
   the start of the month, and what it was owed and not paid the month before (see interest-carried); a node that is divided is owed what its
   children are."
  (if (null? (node-split node))
      (+ (node-interest-due deal node t) (interest-carried deal node t))
      (apply + (map (lambda (name) (node-interest-owed deal (get-node deal name) t)) (split-children (node-split node))))))

(define (settle-interest! deal split parent t pay)
  "Pays the children of the split the interest of month t that the parent was paid, in the amounts that (pay owed cash total) says: owed
   is what each child is owed, a list, cash what there is, and total what the children are owed together. A Z bond is not paid in cash: what it is
   paid is added to its balance, as its accrual. In a deal with shortfalls what a bond is owed and is not paid is its shortfall, carried to
   the next month; in one without, it is an error that the children are owed more than there is, or less. In either, it is an error if
   some is left over."
  (let* ((children (map (lambda (name) (get-node deal name)) (split-children split)))
         (owed (map (lambda (child) (node-interest-owed deal child t)) children))
         (cash (vector-ref (node-interest parent) t))
         (total (apply + owed))
         (tolerance (* deal-tolerance (deal-size deal))))
    (when (or (> cash (+ total tolerance)) (and (not (deal-shortfalls deal)) (> total (+ cash tolerance))))
      (error (format "the split of {} was paid {:.6g} of interest in month {}, and its children are owed {:.6g} ({})"
                     (node-name parent) cash t total (if (> total cash) "there is not enough" "some is left over"))))
    (for-each (lambda (child owes paid)
                (if (node-z-flag child)
                    (vector-set! (node-accrual child) t paid)
                    (vector-increment! (node-interest child) t paid))
                (when (and (deal-shortfalls deal) (null? (node-split child)))
                  (vector-set! (node-shortfall child) t (max 0.0 (- owes paid)))))
              children owed (pay owed cash total))))

(defmethod pay-interest ((split split) deal parent t)
  "Pays each child, in order, the interest it is owed (see settle-interest!): what there is goes to the first, up to what it is owed,
and then to the next."
  (settle-interest! deal split parent t
                    (lambda (owed cash total)
                      (let ((left cash))
                        (map (lambda (owes) (let ((paid (min left owes))) (set! left (- left paid)) paid)) owed)))))

(defmethod pay-interest ((split pro-rata-split) deal parent t)
  "Pays each child its share of the interest, in proportion to what it is owed: all of it, unless there is not enough."
  (settle-interest! deal split parent t
                    (lambda (owed cash total)
                      (let ((share (if (> total 0.0) (min 1.0 (/ cash total)) 0.0)))
                        (map (lambda (owes) (* owes share)) owed)))))

; A floater and an inverse floater. Of the parent's balance B and coupon c, with the cap C and the margin m: the floater is
; F = B c / C, the inverse floater is I = B - F, the leverage is L = F / I, and the constant is K = L (C - m). The floater's coupon
; is the index plus m, to C; the inverse floater's is K less L times the index, to 0. Where the index is less than C - m they pay
; F (index + m) + I (K - L index) = F m + I K = F m + F (C - m) = F C = B c, and where it is more, F C + 0, the same: together the
; parent's coupon on the parent's balance, at every index, so long as F and I stay in proportion, which pro-rata principal does.
(define (floater-inverse-sizes balance coupon cap margin)
  "The sizes of the floater and the inverse floater, and the leverage and the constant of the inverse floater: (F I L K). An error
if the cap is not above the coupon, or the margin is not from 0 up to the cap."
  (unless (> cap coupon)
    (error (format "the cap of the floater, {}, must be above the coupon of the node that is divided, {}" cap coupon)))
  (unless (and (>= margin 0.0) (< margin cap))
    (error (format "the margin of the floater, {}, must be from 0 up to the cap, {}" margin cap)))
  (let* ((floater (/ (* balance coupon) cap))
         (inverse (- balance floater))
         (leverage (/ floater inverse)))
    (list floater inverse leverage (* leverage (- cap margin)))))

(defmethod calculate-sizes ((split floater-inverse-split) deal parent)
  "The floater is as big as the parent's coupon is of the cap, and the inverse floater is the rest. Sets the leverage and the constant
   of the inverse floater."
  (let ((sizes (floater-inverse-sizes (vector-ref (node-balance parent) 0) (parent-coupon-rate parent "a floater and inverse floater")
                                      (floater-inverse-split-cap split) (floater-inverse-split-margin split))))
    (floater-inverse-split-leverage-set! split (caddr sizes))
    (floater-inverse-split-constant-set! split (list-ref sizes 3))
    (list (car sizes) (cadr sizes))))

(defmethod assign-coupons ((split floater-inverse-split) deal parent)
  "The floater's coupon is the index plus the margin, to the cap, and the inverse floater's is the constant less the leverage times
   the index, to 0."
  (let ((cap (floater-inverse-split-cap split))
        (margin (floater-inverse-split-margin split))
        (leverage (floater-inverse-split-leverage split))
        (constant (floater-inverse-split-constant split)))
    (node-coupon-set! (get-node deal (car (split-children split)))
                      (lambda (index) (min cap (+ (index-rate index) margin))))
    (node-coupon-set! (get-node deal (cadr (split-children split)))
                      (lambda (index) (max 0.0 (- constant (* leverage (index-rate index))))))))

; A premium bond and a discount bond. Of the parent's balance B and coupon c, with the premium coupon p above c and the discount
; coupon d below it: the premium bond is B (c - d) / (p - d) and the discount bond is the rest, so that they pay B c together.
(define (premium-discount-sizes balance coupon premium discount)
  "The sizes of the premium bond and the discount bond: (premium-size discount-size). An error unless the coupon is between the two."
  (unless (< discount coupon premium)
    (error (format "the coupon of the node that is divided, {}, must be between the discount coupon, {}, and the premium coupon, {}"
                   coupon discount premium)))
  (let ((premium-size (/ (* balance (- coupon discount)) (- premium discount))))
    (list premium-size (- balance premium-size))))

(defmethod calculate-sizes ((split premium-discount-split) deal parent)
  "The sizes that make the premium bond and the discount bond pay the parent's coupon, together."
  (premium-discount-sizes (vector-ref (node-balance parent) 0) (parent-coupon-rate parent "a premium and discount")
                          (premium-discount-split-premium-coupon split) (premium-discount-split-discount-coupon split)))

(defmethod assign-coupons ((split premium-discount-split) deal parent)
  "The premium bond and the discount bond have their coupons."
  (node-coupon-set! (get-node deal (car (split-children split))) (constant-coupon (premium-discount-split-premium-coupon split)))
  (node-coupon-set! (get-node deal (cadr (split-children split))) (constant-coupon (premium-discount-split-discount-coupon split))))

; ---------------------------------------------------------------------------
; Paying principal
; ---------------------------------------------------------------------------

(define (node-owed child t)
  "What a node can still be paid in month t: its balance then, and what it accrues this month if it is a Z bond, less what it has been
   paid this month so far."
  (max 0.0 (- (+ (vector-ref (node-balance child) t) (vector-ref (node-accrual child) t)) (vector-ref (node-principal child) t))))

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
  "Pays the children in order. What the Z bonds accrue this month is paid too, as principal: first to the bond it is directed to, if
   there is one, and then in the order."
  (let* ((children (map (lambda (name) (get-node deal name)) (split-children split)))
         (accrued (apply + (map (lambda (child) (vector-ref (node-accrual child) t)) children)))
         (cash (vector-ref (node-principal parent) t)))
    (unless (null? (sequential-split-accretion-to split))
      (set! accrued (pay-child! (get-node deal (sequential-split-accretion-to split)) t accrued)))
    (set! cash (+ cash accrued))
    (dolist (child children)
      (set! cash (pay-child! child t cash)))
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

; ---------------------------------------------------------------------------
; Losses
; ---------------------------------------------------------------------------
; The collateral has a loss for each month: balance that is written off, with no cash. Each month, after the principal, it is divided
; among the children of the collateral by its split, and among theirs by theirs, to the bonds, whose balances it reduces. How it is
; divided is the split's loss rule: reverse, the last child first, up to what it has left, and then the one before (the junior bonds are
; last); forward, the first first; or pro-rata, in proportion to what each has left. A pro-rata split has the pro-rata rule, and any other kind
; reverse, unless it is made with another.

(define (node-remaining node t)
  "What a node still has in month t, after the principal and the losses of the month so far: its balance and what it accrues, less what it
   has been paid and written down."
  (max 0.0 (- (+ (vector-ref (node-balance node) t) (vector-ref (node-accrual node) t))
              (vector-ref (node-principal node) t) (vector-ref (node-loss node) t))))

(define (write-down-child! child t amount)
  "Writes the child down, in month t, by the amount, but not by more than it has left. Returns the amount left to write down."
  (let ((taken (min amount (node-remaining child t))))
    (vector-increment! (node-loss child) t taken)
    (- amount taken)))

(define (check-all-written-down! parent t amount deal)
  "An error if a split has loss that none of its children can be written down by."
  (when (> amount (* deal-tolerance (deal-size deal)))
    (error (format "the split of {} was allocated a loss of {:.6g} that its children, which have too little left, cannot take, in month {}"
                   (node-name parent) amount t))))

(defmethod allocate-loss ((split split) deal parent t)
  "Divides the loss by the loss rule of the split."
  (let* ((rule (split-loss-rule split))
         (children (map (lambda (name) (get-node deal name)) (split-children split)))
         (amount (vector-ref (node-loss parent) t)))
    (cond ((eq? rule 'reverse)
           (dolist (child (reverse children)) (set! amount (write-down-child! child t amount))))
          ((eq? rule 'forward)
           (dolist (child children) (set! amount (write-down-child! child t amount))))
          (else
           (let* ((total (apply + (map (lambda (child) (node-remaining child t)) children)))
                  (to-take (min amount total)))
             (for-each (lambda (child)
                         (write-down-child! child t (if (> total 0.0) (* to-take (/ (node-remaining child t) total)) 0.0)))
                       children)
             (set! amount (- amount to-take)))))
    (check-all-written-down! parent t amount deal)))

(defmethod allocate-loss ((split io-po-split) deal parent t)
  "Writes the PO down: the IO has no balance of its own, and its notional balance follows the PO's."
  (check-all-written-down! parent t (write-down-child! (get-node deal (cadr (split-children split))) t (vector-ref (node-loss parent) t)) deal))

; What a split can divide. A Z bond has its accrual to be paid, which only a sequential split does, so a Z bond is a child of one, and
; is not itself divided (the accrual of its children is not modeled); and a Z bond is paid principal, which a notional bond has none of.
(define (deal-parent-of deal name)
  "The node whose split has the node called name as a child, or #f for the collateral and a tranche that has not been given a parent."
  (find-if (lambda (node) (and (not (null? (node-split node))) (member name (split-children (node-split node)))))
           (map (lambda (n) (get-node deal n)) (deal-names deal))))

(define (deal-po? deal node)
  "Whether the node is the principal-only bond of an IO/PO split: its second child."
  (let ((parent (deal-parent-of deal (node-name node))))
    (and parent (io-po-split? (node-split parent)) (equal? (node-name node) (cadr (split-children (node-split parent)))))))

(define (check-parent-not-z parent)
  (when (node-z-flag parent)
    (error (format "{} is a Z bond, which is not divided: it accrues interest, and the accrual of its children is not modeled" (node-name parent)))))

(define (check-loss-rule split)
  (unless (member (split-loss-rule split) '(reverse forward pro-rata))
    (error (format "the loss rule of a split is reverse, forward or pro-rata, not {}" (split-loss-rule split)))))

(defmethod check-split ((split split) deal parent)
  "A split of any kind can divide a node that is not a Z bond, into bonds that are not Z bonds."
  (check-loss-rule split)
  (check-parent-not-z parent)
  (dolist (name (split-children split))
    (when (node-z-flag (get-node deal name))
      (error (format "{} is a Z bond, which can only be the child of a sequential split" name)))))

(defmethod check-split ((split sequential-split) deal parent)
  "A sequential split can have Z bonds as children, unless the parent is an IO or a PO. The bond the accretion is directed to is one of
the children, and not a Z bond."
  (check-loss-rule split)
  (check-parent-not-z parent)
  (when (and (or (node-notional-flag parent) (deal-po? deal parent))
             (some (lambda (name) (node-z-flag (get-node deal name))) (split-children split)))
    (error (format "{} is an IO or a PO, which is not divided into a Z bond" (node-name parent))))
  (let ((directed (sequential-split-accretion-to split)))
    (unless (null? directed)
      (unless (member directed (split-children split))
        (error (format "the accretion is directed to {}, which is not one of the children {}" directed (string-join (split-children split) " "))))
      (when (node-z-flag (get-node deal directed))
        (error (format "the accretion is directed to {}, which is a Z bond: it is paid to the bonds that are not" directed))))))

(defmethod check-split ((split io-po-split) deal parent)
  "An IO/PO split divides a bond that is not a Z bond, an IO or a PO, into an IO that follows the PO, and the PO."
  (call-next-method)
  (when (node-notional-flag parent)
    (error (format "{} is an interest-only bond, which is not divided into an IO and a PO" (node-name parent))))
  (when (deal-po? deal parent)
    (error (format "{} is a principal-only bond, which is not divided into an IO and a PO" (node-name parent))))
  (unless (= (length (split-children split)) 2)
    (error "an IO/PO split has two children: the IO and the PO"))
  (let ((io (get-node deal (car (split-children split))))
        (po (get-node deal (cadr (split-children split)))))
    (unless (and (node-notional-flag io) (equal? (node-follows io) (node-name po)) (not (node-notional-flag po)))
      (error "the IO of an IO/PO split is a notional bond that follows the PO (see deal-io-po!)"))))

(defmethod calculate-sizes ((split io-po-split) deal parent)
  "Both are as big as the parent: the PO is the parent's balance, and the IO's notional balance is that."
  (let ((balance (vector-ref (node-balance parent) 0)))
    (list balance balance)))

(defmethod assign-coupons ((split io-po-split) deal parent)
  "The IO is paid the parent's coupon (or :io-coupon), on the notional balance, and the PO the rest of it, which is none, if the IO has
   all of it."
  (let ((io-coupon (io-po-split-io-coupon split))
        (parent-coupon (node-coupon parent)))
    (if (null? io-coupon)
        (begin (node-coupon-set! (get-node deal (car (split-children split))) parent-coupon)
               (node-coupon-set! (get-node deal (cadr (split-children split))) (constant-coupon 0.0)))
        (begin (node-coupon-set! (get-node deal (car (split-children split))) (constant-coupon io-coupon))
               (node-coupon-set! (get-node deal (cadr (split-children split)))
                                 (lambda (index) (max 0.0 (- (parent-coupon index) io-coupon))))))))

(defmethod pay-principal ((split io-po-split) deal parent t)
  "Pays all of the principal to the PO: the IO has none."
  (let ((cash (vector-ref (node-principal parent) t)))
    (set! cash (pay-child! (get-node deal (cadr (split-children split))) t cash))
    (check-all-paid! parent t cash deal)))

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

(define (deal-collateral-for deal name)
  "The collateral at the root of the tree that the node called name is in, which has to be one that can be run at another speed: made by
collateral-from-psa."
  (let ((root-name (deal-root-of deal name)))
    (unless root-name
      (error (format "{} is not in a tree of the deal: it has not been given a parent" name)))
    (let ((root (get-node deal root-name)))
      (when (null? (collateral-rate root))
        (error (format "the collateral {} was not made by collateral-from-psa, so it cannot be run at another speed" root-name)))
      root)))

(define (deal-ancestors deal name)
  "The names of the nodes above the node called name, from the collateral down to its parent: '() for the collateral."
  (let ((parent (deal-parent-of deal name)))
    (if parent
        (append (deal-ancestors deal (node-name parent)) (list (node-name parent)))
        '())))

(define (deal-principal-at deal name psa)
  "The principal that the node called name would be paid in each month, as a vector, if the collateral of its tree prepaid at psa
   percent of the PSA curve: the collateral is run at that speed, and the tree, as it is now, with its interest (a Z bond's accrual is
   paid as principal), down to the node: the splits above it, that is; what it and the nodes beside it are divided into is not
   in it (and need not be as it should be, in a deal that is being changed). The deal itself is not changed: it is run on copies
   of the nodes of the tree, at the index it was last run with, or at 0 if it was not."
  (let* ((root (deal-collateral-for deal name))
         (above (deal-ancestors deal name))
         (flows (pool-cash-flows (vector-ref (node-balance root) 0) (collateral-rate root) (collateral-term root)
                                 (collateral-age root) psa))
         (copy (make-deal :name (deal-name deal) :periods (deal-periods deal)
                          :index (if (null? (deal-index deal)) (make-vector (deal-periods deal) 0.0) (deal-index deal)))))
    (dolist (node-name (deal-tree-names deal (node-name root)))
      (let ((node (copy-node (get-node deal node-name))))
        (unless (member node-name above)      ; (a node that is not above the node is a bond here: what it divides is no matter)
          (node-split-set! node '()))
        (node-balance-set! node (vector-copy (node-balance node)))
        (node-principal-set! node (vector-copy (node-principal node)))
        (node-interest-set! node (vector-copy (node-interest node)))
        (node-accrual-set! node (vector-copy (node-accrual node)))
        (node-loss-set! node (vector-copy (node-loss node)))
        (node-shortfall-set! node (vector-copy (node-shortfall node)))
        (deal-add-node! copy node)))
    (deal-roots-set! copy (list (node-name root)))
    (let ((pool (get-node copy (node-name root))))       ; (the balances are worked out again by the run)
      (node-principal-set! pool (car flows))
      (node-interest-set! pool (cadr flows))
      (node-loss-set! pool (make-vector (deal-periods deal) 0.0)))      ; (a PAC's schedule is of the cash flows, without losses)
    (deal-run-months! copy)
    (node-principal (get-node copy name))))

(define (pac-check-arguments split deal parent)
  "An error if a PAC split could not be sized: it has two children, its two speeds go from the lower to the higher, and the
   collateral of the tree of the parent can be run at another speed."
  (unless (= (length (split-children split)) 2)
    (error "a PAC split has two children: the PAC and the companion"))
  (unless (< 0 (pac-split-low-psa split) (pac-split-high-psa split))
    (error (format "the PAC's speeds must be from the lower to the higher, above 0, not {} and {}"
                   (pac-split-low-psa split) (pac-split-high-psa split))))
  (deal-collateral-for deal (node-name parent))
  #t)

(defmethod calculate-sizes ((split pac-split) deal parent)
  "The size of the PAC is what the parent pays at both of the two speeds of the collateral, month by month the least of the two,
   added up; the companion is the rest. (What the parent pays is found by running the deal at each speed: see deal-principal-at.)
   Sets the schedule of the PAC, its balance at the start of each month, from that size, less the least each month. Returns
   (PAC-size companion-size)."
  (pac-check-arguments split deal parent)
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

(define (walk-interest! deal node t)
  "The same for the interest."
  (let ((split (node-split node)))
    (unless (null? split)
      (pay-interest split deal node t)
      (dolist (name (split-children split))
        (walk-interest! deal (get-node deal name) t)))))

(define (walk-losses! deal node t)
  "The same for the loss."
  (let ((split (node-split node)))
    (unless (null? split)
      (allocate-loss split deal node t)
      (dolist (name (split-children split))
        (walk-losses! deal (get-node deal name) t)))))

(define (deal-set-index! deal index)
  "Sets the index of the deal: a number for every month, or a vector of them, or '() for none."
  (cond ((null? index) (deal-index-set! deal '()))
        ((number? index) (deal-index-set! deal (make-vector (deal-periods deal) (+ index 0.0))))
        ((and (vector? index) (>= (vector-length index) (deal-periods deal))) (deal-index-set! deal index))
        (else (error (format "the index is a number, or a vector with a number for each of the {} months, not {}" (deal-periods deal) index)))))

(define (deal-run-months! deal)
  "Month by month, the interest, then the principal, and then the loss that each node is paid or written down by, and the balance it has
   next. The interest comes first because a Z bond is paid, in principal, what it accrues, and the loss last, because it is of what is left.
   Only collateral that has a coupon has its interest paid on. A balance is its last, and what it accrues, less what it is paid and written
   down by; a notional balance is a share of the balance that it follows."
  (dolist (name (deal-names deal))
    (let ((node (get-node deal name)))
      (vector-fill! (node-accrual node) 0.0)
      (vector-fill! (node-shortfall node) 0.0)
      (unless (member name (deal-roots deal))
        (vector-fill! (node-principal node) 0.0)
        (vector-fill! (node-interest node) 0.0)
        (vector-fill! (node-loss node) 0.0))))
  (loop for t from 0 below (deal-periods deal)
        do (begin
             (dolist (root (deal-roots deal))
               (unless (null? (node-coupon (get-node deal root)))
                 (walk-interest! deal (get-node deal root) t)))
             (dolist (root (deal-roots deal))
               (walk-principal! deal (get-node deal root) t))
             (dolist (root (deal-roots deal))
               (walk-losses! deal (get-node deal root) t))
             (dolist (name (deal-names deal))
               (let ((node (get-node deal name)))
                 (unless (node-notional-flag node)
                   (vector-set! (node-balance node) (+ t 1)
                                (- (+ (vector-ref (node-balance node) t) (vector-ref (node-accrual node) t))
                                   (vector-ref (node-principal node) t) (vector-ref (node-loss node) t))))))
             (dolist (name (deal-names deal))             ; (the notional bonds, after the bonds they follow: those are before them)
               (let ((node (get-node deal name)))
                 (when (node-notional-flag node)
                   (vector-set! (node-balance node) (+ t 1)
                                (* (node-share node) (vector-ref (node-balance (get-node deal (node-follows node))) (+ t 1)))))))))
  deal)

(define (deal-run! deal &key (index '()))
  "Works out, month by month, the interest and then the principal that each node is paid, and the balance it has next. The index is
   what the coupons that float are of: a vector with a number for each month, or one number for every month (0.04 is 4%). It can be run
   again, with another index or after a change."
  (deal-set-index! deal index)
  (deal-run-months! deal))

; ---------------------------------------------------------------------------
; Looking at it
; ---------------------------------------------------------------------------

(define (deal-check deal)
  "#t if the principal and the interest of the deal add up, or an error that says where they do not: in every month, what the
   children of a split were paid adds up to what the parent was paid (and a Z bond's accrual is paid as principal), no balance has gone
   below 0, every node with a coupon was paid, or accrued, exactly the interest it was owed, and a notional bond has no principal and
   is its share of the balance it follows. (The amounts are equal to within deal-tolerance of the collateral.)"
  (let ((tolerance (* deal-tolerance (deal-size deal))))
    (dolist (name (deal-names deal))
      (let* ((node (get-node deal name))
             (split (node-split node))
             (children (if (null? split) '() (map (lambda (child) (get-node deal child)) (split-children split)))))
        (loop for t from 0 to (deal-periods deal)
              do (when (< (vector-ref (node-balance node) t) (- tolerance))
                   (error (format "{} owes {} in month {}: it has been paid more than it was owed" name (vector-ref (node-balance node) t) t))))
        (when (node-notional-flag node)
          (loop for t from 0 to (deal-periods deal)
                do (let ((followed (* (node-share node) (vector-ref (node-balance (get-node deal (node-follows node))) t))))
                     (when (> (abs (- (vector-ref (node-balance node) t) followed)) tolerance)
                       (error (format "the notional balance of {} is {} in month {}, and it is to be {} of {}, which is {}"
                                      name (vector-ref (node-balance node) t) t (node-share node) (node-follows node) followed)))))
          (loop for t from 0 below (deal-periods deal)
                do (when (> (abs (vector-ref (node-principal node) t)) tolerance)
                     (error (format "{} is a notional bond, and was paid {} of principal in month {}" name (vector-ref (node-principal node) t) t)))
                   (when (> (abs (vector-ref (node-loss node) t)) tolerance)
                     (error (format "{} is a notional bond, and was written down by {} in month {}" name (vector-ref (node-loss node) t) t)))))
        (unless (null? split)
          (loop for t from 0 below (deal-periods deal)
                do (let ((paid (apply + (map (lambda (child) (vector-ref (node-principal child) t)) children)))
                         (accrued (apply + (map (lambda (child) (vector-ref (node-accrual child) t)) children))))
                     (when (> (abs (- paid (+ (vector-ref (node-principal node) t) accrued))) tolerance)
                       (error (format "the children of {} were paid {} in month {}, and {} was paid {} and its Z bonds accrued {} (has deal-run! been called?)"
                                      name paid t name (vector-ref (node-principal node) t) accrued))))))
        (unless (null? split)
          (loop for t from 0 below (deal-periods deal)
                do (let ((written (apply + (map (lambda (child) (vector-ref (node-loss child) t)) children))))
                     (when (> (abs (- written (vector-ref (node-loss node) t))) tolerance)
                       (error (format "the children of {} were written down by {} in month {}, and {} by {}"
                                      name written t name (vector-ref (node-loss node) t)))))))
        (unless (null? (node-coupon node))
          (if (null? split)
              ;; a bond is paid, or accrues, or carries what it is owed (the collateral, in a deal with shortfalls, is paid what it is)
              (unless (and (deal-shortfalls deal) (member name (deal-roots deal)))
                (loop for t from 0 below (deal-periods deal)
                      do (let ((owed (node-interest-owed deal node t))
                               (got (+ (vector-ref (node-interest node) t) (vector-ref (node-accrual node) t) (vector-ref (node-shortfall node) t))))
                           (when (> (abs (- owed got)) tolerance)
                             (error (format "{} was paid {:.6g} of interest in month {}, and it is owed {:.6g} (has deal-run! been called?)"
                                            name got t owed))))))
              ;; a node that is divided is paid what its coupon is, unless there are shortfalls
              (unless (deal-shortfalls deal)
                (loop for t from 0 below (deal-periods deal)
                      do (let ((due (node-interest-due deal node t))
                               (paid (+ (vector-ref (node-interest node) t) (vector-ref (node-accrual node) t))))
                           (when (> (abs (- due paid)) tolerance)
                             (error (format "{} was paid {:.6g} of interest in month {}, and it is owed {:.6g} (has deal-run! been called?)"
                                            name paid t due)))))))
          (unless (null? split)
            (loop for t from 0 below (deal-periods deal)
                  do (let ((paid (apply + (map (lambda (child) (+ (vector-ref (node-interest child) t) (vector-ref (node-accrual child) t))) children)))
                           (dues (apply + (map (lambda (child) (node-interest-due deal child t)) children))))
                       (when (> (abs (- paid (vector-ref (node-interest node) t))) tolerance)
                         (error (format "the children of {} were paid {:.6g} of interest in month {}, and {} was paid {:.6g}"
                                        name paid t name (vector-ref (node-interest node) t))))
                       (when (> (abs (- dues (node-interest-due deal node t))) tolerance)
                         (error (format "the coupons of the children of {} do not add up to its own: they are owed {:.6g} in month {}, and it {:.6g}"
                                        name dues t (node-interest-due deal node t))))))))))
    #t))

(defmethod split-label ((split split)) "split")
(defmethod split-label ((split sequential-split)) "sequential")
(defmethod split-label ((split pro-rata-split)) "pro rata")
(defmethod split-label ((split pac-split)) "PAC and companion")
(defmethod split-label ((split floater-inverse-split)) "floater and inverse floater")
(defmethod split-label ((split premium-discount-split)) "premium and discount")
(defmethod split-label ((split io-po-split)) "IO and PO")

(define (deal-outline-below deal name depth)
  "The node called name and the nodes under it, depth first, as a list of (name . depth): its own depth is given, and each child's is one more."
  (let ((split (node-split (get-node deal name))))
    (cons (cons name depth)
          (if (null? split)
              '()
              (append-map (lambda (child) (deal-outline-below deal child (+ depth 1))) (split-children split))))))

(define (deal-outline-entries deal)
  "Every node of the deal, a tree at a time, each below its parent and before the node after it, as a list of (name . depth): the
   collateral is at depth 0, and what its split pays at depth 1."
  (append-map (lambda (root) (deal-outline-below deal root 0)) (deal-roots deal)))

(define (deal-outline deal)
  "A table of the nodes of the deal, one to a row, each below its parent (the collateral first, then what it is divided into, and what
   those are divided into): the node's name, indented by how far down the tree it is, its balance at the start, to the cent, and the
   kind of split that divides it, if any."
  (let ((entries (deal-outline-entries deal)))
    (make-table "tranche" (list->vector (map (lambda (entry) (string-append (format-value "" (format ">{}" (* 2 (cdr entry)))) (car entry)))
                                             entries))
                "balance" (list->vector (map (lambda (entry) (/ (round (* 100 (vector-ref (node-balance (get-node deal (car entry))) 0))) 100.0))
                                             entries))                                             ; (to the cent)
                "split" (list->vector (map (lambda (entry)
                                             (let ((split (node-split (get-node deal (car entry)))))
                                               (if (null? split) "" (split-label split))))
                                           entries)))))

(define (deal-table-of deal first-month rows column-of)
  "A table with a row for each month from first-month, and a column for each node, made by (column-of node)."
  (apply make-table
         (cons "month" (cons (+ first-month (vector-range rows))
                             (append-map (lambda (name) (list name (column-of (get-node deal name)))) (deal-names deal))))))

(define (deal-principal-table deal)
  "A table of the principal paid in each month, one row for a month from 1, with a column for each node."
  (deal-table-of deal 1 (deal-periods deal) node-principal))

(define (deal-interest-table deal)
  "A table of the interest paid in each month, one row for a month from 1, with a column for each node."
  (deal-table-of deal 1 (deal-periods deal) node-interest))

(define (deal-accrual-table deal)
  "A table of what each node accrues in each month, one row for a month from 1: a Z bond's interest, which is added to its balance."
  (deal-table-of deal 1 (deal-periods deal) node-accrual))

(define (deal-loss-table deal)
  "A table of what each node is written down by in each month, one row for a month from 1."
  (deal-table-of deal 1 (deal-periods deal) node-loss))

(define (deal-shortfall-table deal)
  "A table of the interest that each bond is owed and has not been paid at the end of each month, one row for a month from 1: its
shortfall, which it is owed with interest at its coupon the next month. (Only the bonds have one, in a deal with shortfalls.)"
  (deal-table-of deal 1 (deal-periods deal) node-shortfall))

(define (deal-coupon-table deal)
  "A table of the coupon of each node in each month, a decimal, at the index the deal was run with (nothing for a node without one)."
  (deal-table-of deal 1 (deal-periods deal)
                 (lambda (node)
                   (let ((rates (make-vector (deal-periods deal) nan)))
                     (unless (null? (node-coupon node))
                       (loop for t from 0 below (deal-periods deal)
                             do (vector-set! rates t (node-coupon-rate deal node t))))
                     rates))))

(define (deal-balance-table deal)
  "A table of the balance of each node at the start of each month, with a row for the end of the last month too: month 0 is the
   start."
  (deal-table-of deal 0 (+ 1 (deal-periods deal)) node-balance))
