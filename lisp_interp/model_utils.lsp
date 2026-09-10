; model_utils.lsp
;
; A small utility for turning a fitted model -- from linear-regression,
; logistic-regression, or spline-regression, any kind model-predict
; itself accepts -- into an ordinary Lisp function: call it with one
; argument per predictor, in the same order the model was fit with, and
; get back the predicted value of the dependent variable.

; (model->function m) -> a procedure taking one argument per predictor
; `m` was fit with.
;
; `args`, here, is this Lisp's variadic-lambda syntax: a bare symbol
; (not wrapped in parens) as the whole parameter list collects EVERY
; argument the caller passes into one ordinary Lisp list -- exactly the
; list-of-numbers shape model-predict itself expects, so this is nothing
; more than "collect the caller's arguments, hand them to model-predict."
; model-predict does its own argument-count checking against the model,
; so calling the returned function with the wrong number of arguments
; still raises a clear error naming how many predictors the model has.
(define (model->function m)
  (lambda args (model-predict m args)))
