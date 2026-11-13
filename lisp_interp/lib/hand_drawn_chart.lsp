; hand_drawn_chart.lsp
;
; A simple chart that looks drawn by hand, as an SVG string: any number of series of numbers, each drawn as bars or
; as a symbol (square, triangle, star, ...) at its value for each label. Every end point of every line -- the axes,
; the sides of each bar, each stroke of each symbol -- is moved a small random distance, so no line is quite straight
; and no corner quite meets. All the text is in the Architects Daughter font, which looks like handwriting.
;
; The result is a string, so a notebook shows it with display-svg, and write-text-file saves it as a .svg file that
; a Google Slide (Insert > Image) or another program can use.
;
; Usage:
;   (display-svg (hand-drawn-chart '("Jan" "Feb" "Mar")
;                  '(("sales" (3 5 4) "bar")
;                    ("target" (4 4 5))
;                    ("last year" (2 6 3) "triangle"))
;                  :title "Sales"))
;   (write-text-file "sales.svg" (hand-drawn-chart labels series :seed 7))
;
; The labels go under the horizontal axis. Each series is (name values) or (name values shape): the values are as
; many as the labels, and the shape is "bar", "square", "triangle", "diamond", "circle", "cross" or "star". The series
; with no shape get "square", "star", "cross", "circle", "triangle" and "diamond" in turn. Several series of bars
; stand side by side. The names are in a key at the top right. The vertical axis runs from the lowest to the highest
; of all the numbers, written at its bottom and top; :y-min and :y-max give other
; ends (for bars that start from zero, :y-min 0).
;
; Keys:
;   :title  text above the chart (none)                      :wobble  the largest move of a point, in pixels (4)
;   :seed   a number, to draw the same picture again (none)  :width :height  the picture's size in pixels (600, 400)
;   :y-min :y-max  the ends of the vertical axis       :end-labels-only  #t writes only the first and last labels, for
;                                                       when there are too many to fit (#f)

; The font. The @import fetches it from Google Fonts when the picture is shown; without it, a cursive font is used.
(define hand-chart-font "'Architects Daughter', 'Comic Sans MS', cursive")
(define hand-chart-default-shapes '("square" "star" "cross" "circle" "triangle" "diamond"))
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

; A bar: a rectangle whose four corners are each moved a little, filled (lightly) and outlined in the color.
(define (hand-chart--bar left right top bottom color wobble)
  (let ((corners (list (list left top) (list right top) (list right bottom) (list left bottom))))
    (format "<polygon points=\"{}\" fill=\"{}\" fill-opacity=\"0.35\" stroke=\"{}\" stroke-width=\"2\" stroke-linejoin=\"round\"/>"
            (string-join
              (map (lambda (corner)
                     (format "{},{}" (hand-chart--n (+ (car corner) (hand-chart--shake wobble)))
                                     (hand-chart--n (+ (cadr corner) (hand-chart--shake wobble)))))
                   corners)
              " ")
            color color)))

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

; Each series as (name values shape), the values as a list. A series with no shape gets the next of the default
; shapes: the first of those without a shape is a square, the second a star, and so on.
(define (hand-chart--complete-all series)
  (let ((defaults-used 0))
    (loop for one in series
          collect (let ((values (cadr one)))
                    (list (car one)
                          (if (vector? values) (vector->list values) values)
                          (if (> (length one) 2)
                              (caddr one)
                              (let ((shape (list-ref hand-chart-default-shapes
                                                     (mod defaults-used (length hand-chart-default-shapes)))))
                                (set! defaults-used (+ defaults-used 1))
                                shape)))))))

(define (hand-drawn-chart labels series
                          &key (title #f) (wobble 4) (seed #f) (width 600) (height 400) (y-min #f) (y-max #f)
                               (end-labels-only #f))
  (if seed (random-seed seed))
  (let* ((series (hand-chart--complete-all series))
         (labels (if (vector? labels) (vector->list labels) labels))
         (count (length labels))
         (all-values (apply append (map cadr series)))
         (low (or y-min (apply min all-values)))
         (high (or y-max (apply max all-values)))
         (low (if (= low high) (- low 1) low))            ; (a flat chart still has an axis)
         (high (if (= low high) (+ high 1) high))
         (left 70) (right (- width 20))
         (top (if title 55 30)) (bottom (- height 55))
         (slot (/ (- right left) count))
         (symbol-size 8)
         (bar-series (filter (lambda (one) (equal? (caddr one) "bar")) series))
         (group (* 0.6 slot))                             ; the width of all the bars of a label together
         (bar-width (if (null? bar-series) 0 (/ group (length bar-series))))
         (center (lambda (i) (+ left (* slot (+ i 0.5)))))
         (y-of (lambda (value) (- bottom (* (- bottom top) (/ (- value low) (- high low))))))
         (color-of (lambda (place) (list-ref hand-chart-colors (mod place (length hand-chart-colors)))))
         (parts '()))
    (define (add! part) (set! parts (cons part parts)))
    (dolist (one series)
      (if (not (= (length (cadr one)) count))
          (error (format "hand-drawn-chart: {} labels but {} values for \"{}\"" count (length (cadr one)) (car one))))
      (if (not (or (equal? (caddr one) "bar") (member (caddr one) hand-chart-default-shapes)))
          (error (format "hand-drawn-chart: the shape of \"{}\" should be \"bar\", \"square\", \"triangle\", \"diamond\", \"circle\", \"cross\" or \"star\", not {}"
                         (car one) (to-string (caddr one))))))
    ; the axes
    (add! (hand-chart--line left bottom right bottom "#333" 2 wobble))
    (add! (hand-chart--line left top left bottom "#333" 2 wobble))
    ; the lowest and highest numbers, at the bottom and top of the vertical axis
    (add! (hand-chart--text (- left 8) (+ bottom 5) (format "{:g}" low) "end" 16))
    (add! (hand-chart--text (- left 8) (+ top 5) (format "{:g}" high) "end" 16))
    (if title (add! (hand-chart--text (/ (+ left right) 2) 30 title "middle" 22)))
    ; each label
    (loop for i from 0 below count
          do (if (or (not end-labels-only) (= i 0) (= i (- count 1)))
                 (add! (hand-chart--text (center i) (+ bottom 28) (list-ref labels i) "middle" 16))))
    ; each series: its bars or symbols at each label, and its place in the key at the top right
    (loop for one in series
          for place from 0
          do (let ((color (color-of place))
                   (shape (caddr one))
                   (bar-place (if (equal? (caddr one) "bar") (- (length bar-series) (length (member one bar-series))) 0)))
               (loop for i from 0 below count
                     do (let ((y (y-of (list-ref (cadr one) i))))
                          (if (equal? shape "bar")
                              (let ((bar-left (+ (- (center i) (* 0.5 group)) (* bar-place bar-width))))
                                (add! (hand-chart--bar bar-left (+ bar-left bar-width) y bottom color wobble)))
                              (add! (hand-chart--symbol shape (center i) y symbol-size color wobble)))))
               (if (equal? shape "bar")
                   (add! (hand-chart--bar (- right 118) (- right 102) (+ top 3 (* 24 place)) (+ top 17 (* 24 place)) color wobble))
                   (add! (hand-chart--symbol shape (- right 110) (+ top 10 (* 24 place)) symbol-size color wobble)))
               (add! (hand-chart--text (- right 94) (+ top 15 (* 24 place)) (car one) "start" 16))))
    (string-append
      (format "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}\" height=\"{}\" viewBox=\"0 0 {} {}\">"
              width height width height)
      "<style>@import url('https://fonts.googleapis.com/css2?family=Architects+Daughter');</style>"
      (format "<rect width=\"{}\" height=\"{}\" fill=\"white\"/>" width height)
      (string-join (reverse parts) "")
      "</svg>")))
