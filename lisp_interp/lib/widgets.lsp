; widgets.lsp
; ===========
; The common widgets of a Jupyter notebook, one call each: a slider, a button, a drop-down list, a check box, a text box,
; a place for output, and rows and columns to lay them out in. Each is make-widget (any widget of ipywidgets can be made
; with it) with the usual choices made, and with a function to call when the user changes it, if you give one:
;
;   (define out (widget-output))
;   (display-widget
;     (widget-column
;       (widget-slider 1 30 :value 15 :description "years"
;                      :on-change (lambda (years) (widget-capture out (lambda () (display (payment years)))))
;       out))
;
; Outside a notebook they make the same widgets, but only a notebook can show one. See "Widgets" in the language manual.
; A table is edited in a grid with table-grid and grid-table, which are builtins.

(define (widget--on-change widget on-change output)
  "Calls (on-change new-value) when the widget's value changes, if there is an on-change function."
  (unless (null? on-change)
    (widget-on-change widget "value" on-change :output output))
  widget)

(define (widget-slider low high &key (value low) (step 1) (description "") on-change output (continuous-update #f))
  "A slider from low to high: whole numbers if low, high and step are, and otherwise decimals. (on-change value) is called when
it moves: when it is let go, unless :continuous-update is #t (when it is called all the while it moves)."
  (widget--on-change
    (make-widget (if (and (integer? low) (integer? high) (integer? step)) "IntSlider" "FloatSlider")
                 :min low :max high :value value :step step :description description
                 :continuous-update continuous-update)
    on-change output))

(define (widget-button description function &key output (button-style ""))
  "A button that calls (function) when it is clicked. :button-style is \"primary\", \"success\", \"info\", \"warning\", \"danger\" or \"\"."
  (let ((button (make-widget "Button" :description description :button-style button-style)))
    (widget-on-click button function :output output)
    button))

(define (widget-dropdown options &key value (description "") on-change output)
  "A drop-down list of the options (a list of strings or numbers); :value is the one chosen to begin with (the first, if none)."
  (widget--on-change
    (if (null? value)
        (make-widget "Dropdown" :options options :description description)
        (make-widget "Dropdown" :options options :value value :description description))
    on-change output))

(define (widget-checkbox &key (value #f) (description "") on-change output)
  "A check box: its value is #t when it is checked."
  (widget--on-change (make-widget "Checkbox" :value value :description description) on-change output))

(define (widget-text &key (value "") (description "") (placeholder "") on-change output)
  "A box to type text in: (on-change text) is called when the user presses Enter, or leaves the box."
  (widget--on-change
    (make-widget "Text" :value value :description description :placeholder placeholder :continuous-update #f)
    on-change output))

(define (widget-output)
  "A place on the page for what a function displays: widget-capture sends it there, and widget-clear empties it."
  (make-widget "Output"))

(define (widget-column &rest widgets)
  "The widgets one above the other."
  (make-widget "VBox" :children widgets))

(define (widget-row &rest widgets)
  "The widgets side by side."
  (make-widget "HBox" :children widgets))

; ---------------------------------------------------------------------------
; Showing and hiding
; ---------------------------------------------------------------------------

(define (widget-visible widget shown)
  "Shows the widget if shown is #t, and hides it (it takes no room on the page) if #f."
  (widget-set! (widget-get widget "layout") "display" (if shown '() "none")))

; ---------------------------------------------------------------------------
; A panel of actions, to ask the user what to do and with what
; ---------------------------------------------------------------------------
;
; An action panel is a set of tabs (or an accordion), one for each thing the user might do. Each has some fields to fill in
; (a floater's cap, the bands of a PAC) and a button to press when ready. It is one widget, which goes in a column with others, and
; hides and shows like any other. What the button does is the function the panel was given: (on-go action answers), with the
; title of the tab and the answers on it, as a list of (field-name . value). What that function displays goes below the tabs.
;
; The pages are a list, each (title item ...); an item is a field, (name kind label default [options]), or a string, which is
; a line of text to explain the fields. The kinds of field:
;
;   number     a decimal number, such as 8.5
;   integer    a whole number
;   text       a line of text
;   checkbox   a box to check; its value is #t or #f
;   dropdown   a choice from the options, a list of strings or numbers
;
;   (define panel
;     (widget-actions
;       (list (list "Floater cap" "The most the coupon can reach."
;                   (list "cap" 'number "Cap %" 8.5)
;                   (list "index" 'dropdown "Index" "SOFR" (list "SOFR" "Term SOFR")))
;             (list "PAC bands" (list "low" 'number "Low PSA" 100) (list "high" 'number "High PSA" 300)))
;       :on-go (lambda (action answers) (display (list action answers)))))

(define (widget--style)
  "A style that lets a label be as long as it is."
  (let ((style (make-hash-table)))
    (hash-table-set! style "description_width" "initial")
    style))

(define (widget--field spec)
  "The widget for one field spec, (name kind label default [options]), as (name . widget)."
  (let* ((name (list-ref spec 0))
         (kind (list-ref spec 1))
         (label (list-ref spec 2))
         (default (list-ref spec 3))
         (options (if (> (length spec) 4) (list-ref spec 4) '())))
    (cons name
          (cond ((eq? kind 'number)   (make-widget "FloatText" :value default :description label :style (widget--style)))
                ((eq? kind 'integer)  (make-widget "IntText" :value default :description label :style (widget--style)))
                ((eq? kind 'text)     (make-widget "Text" :value default :description label :style (widget--style)))
                ((eq? kind 'checkbox) (make-widget "Checkbox" :value default :description label :style (widget--style)))
                ((eq? kind 'dropdown) (make-widget "Dropdown" :options options :value default :description label :style (widget--style)))
                (else (error (format "widget-actions: the field {} is of kind {}, which is not one of number, integer, text, checkbox, dropdown"
                                     name kind)))))))

(define (widget-actions--answers fields)
  "The answers on a page: a list of (field-name . value)."
  (map (lambda (field) (cons (car field) (widget-get (cdr field) "value"))) fields))

(define (widget-actions--page page button on-go output)
  "One page of the panel: (title . fields), and the widget that holds it."
  (let* ((title (car page))
         (entries (map (lambda (item) (if (string? item)
                                          (cons #f (make-widget "HTML" :value item))
                                          (widget--field item)))
                       (cdr page)))
         (fields (filter (lambda (entry) (string? (car entry))) entries))
         (go (widget-button button
                            (lambda ()
                              (widget-clear output)
                              (on-go title (widget-actions--answers fields)))
                            :output output :button-style "primary")))
    (list (cons title fields)
          (widget-column (make-widget "VBox" :children (map cdr entries)) go))))

(define (widget-actions pages &key on-go (style "tabs") (button "Go") (heading ""))
  "A panel with a page for each of the pages, as tabs (:style \"tabs\") or as an accordion (:style \"accordion\"), each with the
fields it says and a button, :button (\"Go\"). Pressing the button calls (on-go title answers). :heading is a line of HTML above
the pages (see widget-actions-heading)."
  (unless (procedure? on-go)
    (error "widget-actions: :on-go is the function to call when a button is pressed, (lambda (action answers) ...)"))
  (let* ((output (widget-output))
         (heading-widget (make-widget "HTML" :value heading))
         (built (map (lambda (page) (widget-actions--page page button on-go output)) pages))
         (container (make-widget (if (equal? style "accordion") "Accordion" "Tab")
                                 :children (map cadr built)
                                 :titles (map car pages)))
         (panel (widget-column heading-widget container output)))
    (widget-set-tag! panel (list (map car built) container heading-widget))
    panel))

(define (widget-actions--tag panel who)
  (let ((tag (widget-tag panel)))
    (when (null? tag)
      (error (format "{}: expected a panel made by widget-actions" who)))
    tag))

(define (widget-actions--fields panel title)
  "The (name . widget) fields of a page of the panel."
  (let ((page (assoc title (car (widget-actions--tag panel "widget-actions")))))
    (unless page
      (error (format "widget-actions: the panel has no page {}" title)))
    (cdr page)))

(define (widget-actions-heading panel text)
  "Changes the line of HTML above the pages: what the panel is for, such as the tranche chosen."
  (widget-set! (caddr (widget-actions--tag panel "widget-actions-heading")) "value" text))

(define (widget-actions-set! panel title name value)
  "Puts a value in a field of a page, such as a default that depends on what was chosen."
  (let ((field (assoc name (widget-actions--fields panel title))))
    (unless field
      (error (format "widget-actions-set!: the page {} has no field {}" title name)))
    (widget-set! (cdr field) "value" value)))

(define (widget-actions-answers panel title)
  "What is in the fields of a page now, as a list of (field-name . value)."
  (widget-actions--answers (widget-actions--fields panel title)))

(define (widget-actions-select panel title)
  "Brings a page to the front."
  (let ((place (position title (map car (car (widget-actions--tag panel "widget-actions-select"))))))
    (unless place
      (error (format "widget-actions-select: the panel has no page {}" title)))
    (widget-set! (cadr (widget-actions--tag panel "widget-actions-select")) "selected_index" place)))
