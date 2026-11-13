; hand_drawn_chart.lsp
;
; A simple chart that looks drawn by hand, as an SVG string: bars for one list of values, and symbols (squares,
; triangles, stars, ...) for any number of other lists of values. Every end point of every line -- the axes, the
; sides of each bar, each stroke of each symbol -- is moved a small random distance, so no line is quite straight
; and no corner quite meets. All the text is in the Architects Daughter font, which looks like handwriting.
;
; The result is a string, so a notebook shows it with display-svg, and write-text-file saves it as a .svg file that
; a Google Slide (Insert > Image) or another program can use.
;
; Usage:
;   (display-svg (hand-drawn-chart '("Jan" "Feb" "Mar") '(3 5 4)))
;   (display-svg (hand-drawn-chart '("Jan" "Feb" "Mar") '(3 5 4)
;                  :title "Sales"
;                  :extras '(("target" "star" (4 4 5)) ("last year" "triangle" (2 6 3)))))
;   (write-text-file "sales.svg" (hand-drawn-chart labels values :seed 7))
;
; The labels go under the horizontal axis, one for each value. The vertical axis runs from the lowest to the highest
; of all the numbers (the bars' and the symbols'), written at the bottom and top of the axis; :y-min and :y-max
; give other ends (for bars that start from zero, :y-min 0). Each extra is (name symbol values), where the symbol
; is "square", "triangle", "diamond", "circle", "cross" or "star", and the values are as many as the labels.
;
; Keys:
;   :extras  the lists of symbols, as above (none)           :title  text above the chart (none)
;   :wobble  the largest move of a point, in pixels (2)      :seed   a number, to draw the same picture again (none)
;   :width :height  the picture's size in pixels (600, 400)  :y-min :y-max  the ends of the vertical axis

; The font. The @import fetches it from Google Fonts when the picture is shown; without it, a cursive font is used.
(define hand-chart-font "'Architects Daughter', 'Comic Sans MS', cursive")
(define hand-chart-colors '("#d95f02" "#1b9e77" "#7570b3" "#e7298a" "#66a61e"))

; ---------------------------------------------------------------------------
; Small helpers
; ---------------------------------------------------------------------------

; A number as text for SVG: one decimal.
(define (hand-chart--n x) (format "{:.1f}" x))

; The text with & < > replaced, so that a label can't break the SVG.
(define (hand-chart--escape text)
  (string-replace (string-replace (string-replace (to-string text) "&" "&amp;") "<" "&lt;") ">" "&gt;"))

; A random number between -wobble and wobble.
(define (hand-chart--shake wobble)
  (random-float (- wobble) wobble))

; ---------------------------------------------------------------------------
; The parts of the picture, each a string of SVG
; ---------------------------------------------------------------------------

; A line from (x1 y1) to (x2 y2), each end moved a little.
(define (hand-chart--line x1 y1 x2 y2 color width wobble)
  (format "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"{}\" stroke-width=\"{}\" stroke-linecap=\"round\"/>"
          (hand-chart--n (+ x1 (hand-chart--shake wobble))) (hand-chart--n (+ y1 (hand-chart--shake wobble)))
          (hand-chart--n (+ x2 (hand-chart--shake wobble))) (hand-chart--n (+ y2 (hand-chart--shake wobble)))
          color width))

; Some text. anchor is "start", "middle" or "end".
(define (hand-chart--text x y text anchor size)
  (format "<text x=\"{}\" y=\"{}\" text-anchor=\"{}\" font-size=\"{}\" font-family=\"{}\" fill=\"#333\">{}</text>"
          (hand-chart--n x) (hand-chart--n y) anchor size hand-chart-font (hand-chart--escape text)))

; A bar: a rectangle whose four corners are each moved a little, filled and outlined.
(define (hand-chart--bar left right top bottom wobble)
  (let ((corners (list (list left top) (list right top) (list right bottom) (list left bottom))))
    (format "<polygon points=\"{}\" fill=\"#9ecae1\" stroke=\"#333\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>"
            (string-join
              (map (lambda (corner)
                     (format "{},{}" (hand-chart--n (+ (car corner) (hand-chart--shake wobble)))
                                     (hand-chart--n (+ (cadr corner) (hand-chart--shake wobble)))))
                   corners)
              " "))))

; ---------------------------------------------------------------------------
; Symbols: each is a list of strokes, a stroke being a list of (x y) points joined by lines, drawn around
; (0 0) and no more than 1 away from it. The picture scales them.
; ---------------------------------------------------------------------------

(define (hand-chart--star-points)
  ; Five points, joined each to the one two places on (a pentagram), so it is drawn without lifting the pen.
  (loop for i from 0 to 5
        collect (let ((angle (- (* i (/ (* 4 pi) 5)) (/ pi 2))))
                  (list (cos angle) (sin angle)))))

(define (hand-chart--circle-points)
  (loop for i from 0 to 10
        collect (let ((angle (* i (/ (* 2 pi) 10))))
                  (list (cos angle) (sin angle)))))

(define (hand-chart--symbol-strokes kind)
  (cond ((equal? kind "square")   (list '((-1 -1) (1 -1) (1 1) (-1 1) (-1 -1))))
        ((equal? kind "triangle") (list '((0 -1) (1 0.8) (-1 0.8) (0 -1))))
        ((equal? kind "diamond")  (list '((0 -1.2) (1.2 0) (0 1.2) (-1.2 0) (0 -1.2))))
        ((equal? kind "cross")    (list '((-1 -1) (1 1)) '((-1 1) (1 -1))))
        ((equal? kind "circle")   (list (hand-chart--circle-points)))
        ((equal? kind "star")     (list (hand-chart--star-points)))
        (else (error (format "hand-drawn-chart: the symbol should be \"square\", \"triangle\", \"diamond\", \"circle\", \"cross\" or \"star\", not {}"
                             (to-string kind))))))

; The symbol of that kind at (x y), size pixels across: each segment of each stroke a line, each end moved a little.
(define (hand-chart--symbol kind x y size color wobble)
  (string-join
    (apply append
      (map (lambda (stroke)
             (loop for i from 0 below (- (length stroke) 1)
                   collect (let ((from (list-ref stroke i))
                                 (to (list-ref stroke (+ i 1))))
                             (hand-chart--line (+ x (* size (car from))) (+ y (* size (cadr from)))
                                               (+ x (* size (car to)))   (+ y (* size (cadr to)))
                                               color 2 (* 0.5 wobble)))))
           (hand-chart--symbol-strokes kind)))
    ""))

; ---------------------------------------------------------------------------
; The chart
; ---------------------------------------------------------------------------

(define (hand-drawn-chart labels values
                          &key (extras '()) (title #f) (wobble 2) (seed #f)
                               (width 600) (height 400) (y-min #f) (y-max #f))
  (if seed (random-seed seed))
  (let* ((values (if (vector? values) (vector->list values) values))
         (extras (map (lambda (extra)                     ; the values of each as a list
                        (list (car extra) (cadr extra)
                              (if (vector? (caddr extra)) (vector->list (caddr extra)) (caddr extra))))
                      extras))
         (labels (if (vector? labels) (vector->list labels) labels))
         (count (length labels))
         (all-values (apply append values (map caddr extras)))
         (low (or y-min (apply min all-values)))
         (high (or y-max (apply max all-values)))
         (low (if (= low high) (- low 1) low))            ; (a flat chart still has an axis)
         (high (if (= low high) (+ high 1) high))
         (left 70) (right (- width 20))
         (top (if title 55 30)) (bottom (- height 55))
         (slot (/ (- right left) count))
         (symbol-size 8)
         (center (lambda (i) (+ left (* slot (+ i 0.5)))))
         (y-of (lambda (value) (- bottom (* (- bottom top) (/ (- value low) (- high low))))))
         (parts '()))
    (if (not (= (length values) count))
        (error (format "hand-drawn-chart: {} labels but {} values" count (length values))))
    (dolist (extra extras)
      (if (not (= (length (caddr extra)) count))
          (error (format "hand-drawn-chart: {} labels but {} values for \"{}\"" count (length (caddr extra)) (car extra)))))
    (define (add! part) (set! parts (cons part parts)))
    ; the axes
    (add! (hand-chart--line left bottom right bottom "#333" 2 wobble))
    (add! (hand-chart--line left top left bottom "#333" 2 wobble))
    ; the lowest and highest numbers, at the bottom and top of the vertical axis
    (add! (hand-chart--text (- left 8) (+ bottom 5) (format "{:g}" low) "end" 16))
    (add! (hand-chart--text (- left 8) (+ top 5) (format "{:g}" high) "end" 16))
    ; the title
    (if title (add! (hand-chart--text (/ (+ left right) 2) 30 title "middle" 22)))
    ; each label, and each bar
    (loop for i from 0 below count
          do (add! (hand-chart--text (center i) (+ bottom 28) (list-ref labels i) "middle" 16))
             (add! (hand-chart--bar (- (center i) (* 0.25 slot)) (+ (center i) (* 0.25 slot))
                                    (y-of (list-ref values i)) bottom wobble)))
    ; the symbols of each extra list, and its name in a key at the top right
    (loop for extra in extras
          for k from 0
          do (let ((color (list-ref hand-chart-colors (mod k (length hand-chart-colors)))))
               (loop for i from 0 below count
                     do (add! (hand-chart--symbol (cadr extra) (center i) (y-of (list-ref (caddr extra) i))
                                                  symbol-size color wobble)))
               (add! (hand-chart--symbol (cadr extra) (- right 110) (+ top 10 (* 24 k)) symbol-size color wobble))
               (add! (hand-chart--text (- right 94) (+ top 15 (* 24 k)) (car extra) "start" 16))))
    (string-append
      (format "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}\" height=\"{}\" viewBox=\"0 0 {} {}\">"
              width height width height)
      "<style>@import url('https://fonts.googleapis.com/css2?family=Architects+Daughter');</style>"
      (format "<rect width=\"{}\" height=\"{}\" fill=\"white\"/>" width height)
      (string-join (reverse parts) "")
      "</svg>")))
