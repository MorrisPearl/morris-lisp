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
