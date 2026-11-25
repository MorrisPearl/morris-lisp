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
; The labels go under the horizontal axis. Each series is (name values), (name values shape), (name values :axis 2) or
; (name values shape :axis 2): the values are as many as the labels, and the shape is "bar", "stacked-bar", "square", "triangle", "diamond", "circle", "cross" or
; "star". The series with no shape get "square", "star", "cross", "circle", "triangle" and "diamond" in turn.
; Several series of "bar" stand side by side. The series of "stacked-bar" stand one on top of another, in the order
; of the list, in one more bar (for the principal and the interest of a payment, say, to show that they add up to the
; same amount each time). The names are in a key below the labels. The vertical axis runs from the lowest to the
; highest of all the numbers (of the stacks, for stacked bars, and from zero), written at its bottom and top;
; :y-min and :y-max give other ends (for bars that start from zero, :y-min 0).
;
; A bar series with :scribble #t is filled with a scribbled line, as with a pencil, in the place of a solid color
; (:scribble #t as a key of the chart does it for all the bars; a series' own :scribble #f then makes it solid).
;
; A series with :axis 2 is drawn on a second vertical axis, on the right, with its own scale, written at its top and
; bottom: for numbers of very different sizes, such as housing starts and interest rates. The key says (right) after
; the names of those series.
;
; Keys:
;   :title  text above the chart (none)                  :wobble  the largest move of a point, in pixels (4)
;   :seed   a number, to draw the same picture again (none)   :width :height  the picture's size in pixels (600, 400)
;   :y-min :y-max  the ends of the vertical axis              :alt-y-min :alt-y-max  the ends of the right axis
;   :scribble  #t scribbles all the bars (#f)                  :end-labels-only  #t writes only the first and last
;                                                               labels, for when there are too many to fit (#f)
;
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

; A scribble across a rectangle: one line going back and forth from side to side, down the rectangle, with the end of
; each stroke moved a little, in the place of a solid color: always 4 strokes, however big the rectangle.
(define (hand-chart--scribble left right top bottom color wobble)
  (let* ((high (min top bottom))
         (low (max top bottom))
         (strokes 4)
         (points (loop for k from 0 to strokes
                       collect (format "{},{}"
                                       (hand-chart--n (+ (if (even? k) left right) (hand-chart--shake (* 1.5 wobble))))
                                       (hand-chart--n (+ high (* k (/ (- low high) strokes)) (hand-chart--shake (* 3.5 wobble))))))))
    (format "<polyline points=\"{}\" fill=\"none\" stroke=\"{}\" stroke-width=\"6.5\" stroke-linejoin=\"round\" stroke-linecap=\"round\"/>"
            (string-join points " ") color)))

; A bar: a rectangle whose four corners are each moved a little, outlined in the color, and filled with a light color
; or, if scribble is true, with a scribble.
(define (hand-chart--bar left right top bottom color wobble scribble)
  (let ((corners (list (list left top) (list right top) (list right bottom) (list left bottom))))
    (string-append
      (format "<polygon points=\"{}\" fill=\"{}\" fill-opacity=\"0.35\" stroke=\"{}\" stroke-width=\"2\" stroke-linejoin=\"round\"/>"
              (string-join
                (map (lambda (corner)
                       (format "{},{}" (hand-chart--n (+ (car corner) (hand-chart--shake wobble)))
                                       (hand-chart--n (+ (cadr corner) (hand-chart--shake wobble)))))
                     corners)
                " ")
              (if scribble "none" color) color)
      (if scribble (hand-chart--scribble left right top bottom color wobble) ""))))

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

; Each series as (name values shape axis): the values as a list, and the axis 1 or 2. A series with no shape gets the
; next of the default shapes: the first of those without a shape is a square, the second a star, and so on.
(define (hand-chart--complete-all series)
  (let ((defaults-used 0))
    (loop for one in series
          collect (let* ((values (cadr one))
                         (rest (cddr one))
                         (has-shape (and (pair? rest) (string? (car rest))))
                         (options (if has-shape (cdr rest) rest))
                         (axis-place (member :axis options))
                         (scribble-place (member :scribble options)))
                    (list (car one)
                          (if (vector? values) (vector->list values) values)
                          (if has-shape
                              (car rest)
                              (let ((shape (list-ref hand-chart-default-shapes
                                                     (mod defaults-used (length hand-chart-default-shapes)))))
                                (set! defaults-used (+ defaults-used 1))
                                shape))
                          (if axis-place (cadr axis-place) 1)
                          (if scribble-place (cadr scribble-place) 'default))))))

(define (hand-chart--shape one) (caddr one))
(define (hand-chart--axis-of one) (cadddr one))
(define (hand-chart--scribble-of one scribble-all)      ; true or false: the series' own :scribble, or the chart's
  (let ((own (car (cddddr one))))
    (if (equal? own 'default) scribble-all own)))
(define (hand-chart--bar-shape? shape) (or (equal? shape "bar") (equal? shape "stacked-bar")))

; The lowest and highest of the numbers of the series on one axis: the stacked series count as their stacks, and
; start from zero. y-min and y-max, when given, are used in their place.
(define (hand-chart--range axis-series y-min y-max)
  (let* ((stacked (filter (lambda (one) (equal? (hand-chart--shape one) "stacked-bar")) axis-series))
         (others (filter (lambda (one) (not (equal? (hand-chart--shape one) "stacked-bar"))) axis-series))
         (numbers (append (apply append (map cadr others))
                          (if (null? stacked) '() (apply map + (map cadr stacked)))
                          (if (null? stacked) '() '(0))))
         (low (or y-min (if (null? numbers) 0 (apply min numbers))))
         (high (or y-max (if (null? numbers) 1 (apply max numbers)))))
    (if (= low high)                                      ; (a flat chart still has an axis)
        (list (- low 1) (+ high 1))
        (list low high))))

(define (hand-drawn-chart labels series
                          &key (title #f) (wobble 4) (seed #f) (width 600) (height 400) (y-min #f) (y-max #f)
                               (alt-y-min #f) (alt-y-max #f) (end-labels-only #f) (scribble #f))
  (if seed (random-seed seed))
  (let* ((series (hand-chart--complete-all series))
         (labels (if (vector? labels) (vector->list labels) labels))
         (count (length labels))
         (on-axis (lambda (axis) (filter (lambda (one) (= (hand-chart--axis-of one) axis)) series)))
         (two-axes (not (null? (on-axis 2))))
         (range-1 (hand-chart--range (on-axis 1) y-min y-max))
         (range-2 (hand-chart--range (on-axis 2) alt-y-min alt-y-max))
         (left 70) (right (- width (if two-axes 70 20)))
         ; The key goes under the labels, in rows: each entry (symbol, then name) is where the one before ends, or at
         ; the start of the next row when it would not fit.
         (key-names (map (lambda (one) (if (and two-axes (= (hand-chart--axis-of one) 2)) (string-append (car one) " (right)") (car one))) series))
         (key-places (let ((x left) (row 0))              ; each entry's (x row)
                       (loop for name in key-names
                             collect (let ((entry-width (+ 40 (* 8.5 (string-length name)))))
                                       (if (and (> x left) (> (+ x entry-width) (- width 20)))
                                           (begin (set! x left) (set! row (+ row 1))))
                                       (let ((place (list x row)))
                                         (set! x (+ x entry-width))
                                         place)))))
         (key-rows (if (null? key-places) 0 (+ 1 (apply max (map cadr key-places)))))
         (top (if title 55 30)) (bottom (- height 55 (* 24 key-rows)))
         (slot (/ (- right left) count))
         (symbol-size 8)
         (bar-series (filter (lambda (one) (equal? (hand-chart--shape one) "bar")) series))
         (stacks (lambda (axis) (filter (lambda (one) (equal? (hand-chart--shape one) "stacked-bar")) (on-axis axis))))
         ; The bars side by side at a label: each "bar" series, then the stack of each axis that has one.
         (stack-columns (filter (lambda (axis) (not (null? (stacks axis)))) '(1 2)))
         (columns (+ (length bar-series) (length stack-columns)))
         (group (* 0.6 slot))                             ; the width of all the columns of a label together
         (bar-width (if (= columns 0) 0 (/ group columns)))
         (center (lambda (i) (+ left (* slot (+ i 0.5)))))
         (y-of (lambda (axis value)
                 (let ((range (if (= axis 1) range-1 range-2)))
                   (- bottom (* (- bottom top) (/ (- value (car range)) (- (cadr range) (car range))))))))
         (color-of (lambda (place) (list-ref hand-chart-colors (mod place (length hand-chart-colors)))))
         (parts '()))
    (define (add! part) (set! parts (cons part parts)))
    (dolist (one series)
      (if (not (= (length (cadr one)) count))
          (error (format "hand-drawn-chart: {} labels but {} values for \"{}\"" count (length (cadr one)) (car one))))
      (if (not (or (hand-chart--bar-shape? (hand-chart--shape one)) (member (hand-chart--shape one) hand-chart-default-shapes)))
          (error (format "hand-drawn-chart: the shape of \"{}\" should be \"bar\", \"stacked-bar\", \"square\", \"triangle\", \"diamond\", \"circle\", \"cross\" or \"star\", not {}"
                         (car one) (to-string (hand-chart--shape one)))))
      (if (not (member (hand-chart--axis-of one) '(1 2)))
          (error (format "hand-drawn-chart: the axis of \"{}\" should be 1 or 2, not {}"
                         (car one) (to-string (hand-chart--axis-of one))))))
    ; the axes, and the lowest and highest numbers at the bottom and top of each vertical axis
    (add! (hand-chart--line left bottom right bottom "#333" 2 wobble))
    (add! (hand-chart--line left top left bottom "#333" 2 wobble))
    (add! (hand-chart--text (- left 8) (+ bottom 5) (format "{:g}" (car range-1)) "end" 16))
    (add! (hand-chart--text (- left 8) (+ top 5) (format "{:g}" (cadr range-1)) "end" 16))
    (if two-axes
        (begin
          (add! (hand-chart--line right top right bottom "#333" 2 wobble))
          (add! (hand-chart--text (+ right 8) (+ bottom 5) (format "{:g}" (car range-2)) "start" 16))
          (add! (hand-chart--text (+ right 8) (+ top 5) (format "{:g}" (cadr range-2)) "start" 16))))
    (if title (add! (hand-chart--text (/ (+ left right) 2) 30 title "middle" 22)))
    ; each label
    (loop for i from 0 below count
          do (if (or (not end-labels-only) (= i 0) (= i (- count 1)))
                 (add! (hand-chart--text (center i) (+ bottom 28) (list-ref labels i) "middle" 16))))
    ; each series: its bars or symbols at each label, and its place in the key below the labels
    (loop for one in series
          for place from 0
          do (let* ((color (color-of place))
                    (shape (hand-chart--shape one))
                    (axis (hand-chart--axis-of one))
                    (key-x (car (list-ref key-places place)))                       ; the key's entry for this series
                    (key-y (+ bottom 58 (* 24 (cadr (list-ref key-places place)))))
                    (scribbled (hand-chart--scribble-of one scribble))
                    (bar-place (if (equal? shape "bar") (- (length bar-series) (length (member one bar-series))) 0))
                    (stack-place (if (equal? shape "stacked-bar") (- (length (stacks axis)) (length (member one (stacks axis)))) 0))
                    (stack-column (+ (length bar-series)
                                     (if (member axis stack-columns) (- (length stack-columns) (length (member axis stack-columns))) 0))))
               (loop for i from 0 below count
                     do (let ((y (y-of axis (list-ref (cadr one) i))))
                          (cond ((equal? shape "bar")
                                 (let ((bar-left (+ (- (center i) (* 0.5 group)) (* bar-place bar-width))))
                                   (add! (hand-chart--bar bar-left (+ bar-left bar-width) y (y-of axis (car (if (= axis 1) range-1 range-2))) color wobble scribbled))))
                                ((equal? shape "stacked-bar")  ; on top of the stacked series before it
                                 (let* ((below (apply + (cons 0 (loop for j from 0 below stack-place
                                                                       collect (list-ref (cadr (list-ref (stacks axis) j)) i)))))
                                        (bar-left (+ (- (center i) (* 0.5 group)) (* stack-column bar-width))))
                                   (add! (hand-chart--bar bar-left (+ bar-left bar-width)
                                                          (y-of axis (+ below (list-ref (cadr one) i))) (y-of axis below) color wobble scribbled))))
                                (else (add! (hand-chart--symbol shape (center i) y symbol-size color wobble))))))
               (if (hand-chart--bar-shape? shape)
                   (add! (hand-chart--bar (+ key-x 2) (+ key-x 18) (+ key-y -7) (+ key-y 7) color wobble #f))
                   ; (the key's swatch is solid, scribbled or not)
                   (add! (hand-chart--symbol shape (+ key-x 10) key-y symbol-size color wobble)))
               (add! (hand-chart--text (+ key-x 26) (+ key-y 5) (list-ref key-names place) "start" 16))))
    (string-append
      (format "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}\" height=\"{}\" viewBox=\"0 0 {} {}\">"
              width height width height)
      "<style>@import url('https://fonts.googleapis.com/css2?family=Architects+Daughter');</style>"
      (format "<rect width=\"{}\" height=\"{}\" fill=\"white\"/>" width height)
      (string-join (reverse parts) "")
      "</svg>")))
