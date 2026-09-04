( define api-key "/Users/morris/credentials.json" )
( define creds   "/Users/morris/credentials.json" )

; some of the examples use api-key and some use creds

(defmacro while (test body)
  `(let ()
     (define (%loop)
	 (if ,test
             (begin ,body (%loop))
             '()))
     (%loop)))

