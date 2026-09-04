

(defstruct tranche
  (children ())
  (child_count 0)
  (money 0.0)
  (f (lambda (x) (* x 3)))
  )


(defstruct bond
  (children ())
  (child_count 0)
  (money 0.0)
  (f (lambda (x) (* x 5)))
  )

