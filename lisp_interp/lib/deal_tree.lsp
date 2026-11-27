; deal_tree.lsp
; =============
; Builds a deal in a window of its own, which draws the deal as a tree: each tranche is a box (a node of the tree), and each split is
; the set of lines that join a tranche to its children, with the kind of split written on them.
;
;   (define deal (new-deal "Demo 2026-1" :first-payment (date 2026 12 25)
;                            :collateral '((100000000 6.5 6.0 360))))
;   (deal-tree deal)
;
; Click a tranche that is not divided, and a menu lists the kinds of split. Choose one, and a window pops up with what that kind of split
; needs: the names and balances of the children of a sequential split, the two speeds of a PAC, the cap of a floater. It has two buttons.
; "Calculate the sizes" shows what the tranches would be (their balances, what each is of its parent, and their average lives) without
; changing the deal. "Add the tranches to the deal" adds them; it can be pressed once the sizes have been calculated, and is turned off again
; when a field is changed, so that what is added is what was looked at. Click a tranche that is divided, and the menu offers to change its
; split (the same window, with the fields as they were filled in) or to take the split away, with every tranche under it.
;
; The kinds of split in the menu, and the fields of each, are the split-forms of deal_builder.lsp, (standard-split-forms): each says what
; it asks for (see split-form-inputs) and how to make a split-plan from the answers. A kind of split of your own is added with :forms:
;
;   (deal-tree deal :forms (append (standard-split-forms) (list my-form)))
;
; The window is drawn by lisp_deal_tree.py, with PyQt6. In a notebook, the cell finishes and the window stays open beside it: the deal is
; the notebook's, so what the window adds is in the deal, and what the notebook (or another view, such as (bonds deal)) changes is drawn in
; the window. Run from a Lisp file at the command line, (deal-tree deal) returns when the window is closed.

(require "deal_builder.lsp")

; ---------------------------------------------------------------------------
; What the window is told about the deal
; ---------------------------------------------------------------------------

(define (deal-tree--nodes-below deal name parent-name)
  "The node called name and the nodes under it, depth first, each as a list (name parent-name balance split-label kind): parent-name is
\"\" for the collateral, split-label is \"\" for a node that is not divided, and kind is \"Z\" for a Z bond, \"notional\" for a node whose
balance is a notional one (an IO), and \"\" for the others."
  (let* ((node (get-node deal name))
         (split (node-split node))
         (kind (cond ((node-z-flag node) "Z")
                     ((node-notional-flag node) "notional")
                     (else ""))))
    (cons (list name parent-name (vector-ref (node-balance node) 0) (if (null? split) "" (split-label split)) kind)
          (if (null? split)
              '()
              (append-map (lambda (child) (deal-tree--nodes-below deal child name)) (split-children split))))))

(define (deal-tree--nodes deal)
  "Every node of the deal, the collateral first, each before the nodes under it: see deal-tree--nodes-below."
  (deal-tree--nodes-below deal (deal-root deal) ""))

(define (deal-tree--form forms title)
  "The split-form whose title is title."
  (let ((form (find-if (lambda (form) (equal? (split-form-title form) title)) forms)))
    (unless form
      (error (format "there is no kind of split called {}" title)))
    form))

(define (deal-tree--title-of-split forms deal name)
  "The title of the form for the kind of split that divides the node called name, or \"\" if no form is for that kind (it can then be taken
away, but not changed)."
  (let ((form (find-if (lambda (form) (equal? (split-form-label form) (split-label (node-split (get-node deal name))))) forms)))
    (if form (split-form-title form) "")))

(define (deal-tree--asking forms deal title name)
  "What the pop-up window for dividing the node called name by the form called title shows, as a list (heading help fields): the line at
the top, the line that explains the kind of split, and the fields (see split-form-inputs)."
  (let* ((form (deal-tree--form forms title))
         (node (get-node deal name))
         (balance (vector-ref (node-balance node) 0)))
    (list (if (null? (node-split node))
              (format "Divide {}, which has a balance of {:,.2f}, by a {} split" name balance (split-form-label form))
              (format "Change the {} split of {}, which has a balance of {:,.2f}" (split-form-label form) name balance))
          (split-form-help form)
          (split-form-inputs form deal node))))

(define (deal-tree--plan forms deal title name answers)
  "The split-plan for dividing the node called name as the answers (a list of (field-name . value)) on the form called title say."
  ((split-form-plan (deal-tree--form forms title)) (get-node deal name) answers))

(define (deal-tree--sizes forms deal title name answers)
  "What the tranches below the node called name would be, if it were divided as the answers say, as a list (heading columns rows): the
deal is not changed (see deal-trial-of-plan). The columns and the rows are those of deal-builder--plan-effect."
  (let* ((trial (deal-trial-of-plan deal name (deal-tree--plan forms deal title name answers)))
         (table (deal-builder--plan-effect deal trial name)))
    (list (deal-builder--plan-effect-heading trial name)
          (map car table)
          (loop for row from 0 below (vector-length (cdr (car table)))
                collect (map (lambda (column) (vector-ref (cdr column) row)) table)))))

(define (deal-tree--apply! forms deal title name answers)
  "Divides the node called name as the answers say, or changes its split if it is divided, and returns a line that says what was done."
  (let* ((plan (deal-tree--plan forms deal title name answers))
         (adding (null? (node-split (get-node deal name))))
         (children (string-join (split-children (split-plan-split plan)) ", ")))
    (if adding
        (deal-add-plan! deal name plan)
        (deal-replace-split! deal name plan))
    (if adding
        (format "Added {} under {}, by a {} split." children name (split-label (split-plan-split plan)))
        (format "Changed the split of {}: it is a {} split into {}, and what is under them is worked out again."
                name (split-label (split-plan-split plan)) children))))

(define (deal-tree--delete! deal name)
  "Takes away the split of the node called name, and every node under it, and returns a line that says what was taken away."
  (let ((gone (deal-delete-split! deal name)))
    (format "Took away the split of {}, and {}. {} is not divided." name (string-join gone ", ") name)))

; ---------------------------------------------------------------------------
; The window
; ---------------------------------------------------------------------------

(define (deal-tree deal &key (forms (standard-split-forms)))
  "A window that draws the deal as a tree, to click a tranche and divide it, or change or take away its split: see the top of the file.
:forms are the kinds of split in the menu, split-forms (see deal_builder.lsp). Returns the window."
  (let ((window (deal-tree-window
                  (deal-name deal)
                  :nodes (lambda () (deal-tree--nodes deal))
                  :kinds (lambda () (map split-form-title forms))
                  :title-of-split (lambda (name) (deal-tree--title-of-split forms deal name))
                  :asking (lambda (title name) (deal-tree--asking forms deal title name))
                  :sizes (lambda (title name answers) (deal-tree--sizes forms deal title name answers))
                  :apply (lambda (title name answers) (deal-tree--apply! forms deal title name answers))
                  :delete (lambda (name) (deal-tree--delete! deal name)))))
    (deal-add-view! deal '(tranches) (lambda () (deal-tree-window-redraw window)))
    (deal-tree-window-show window)))
