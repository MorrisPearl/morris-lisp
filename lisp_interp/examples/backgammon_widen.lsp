; backgammon_widen.lsp
;
; Adds hidden units to a trained backgammon network, so that training can go on
; with a larger one that starts out playing almost as the old one did (see
; backgammon-widen-net in lib/backgammon_net.lsp). The arguments are the
; file of the network, the file for the wider one, the number of units to add,
; and a random seed (1 by default). Run it from the examples directory:
;   python3 ../lisp_interpreter.py backgammon_widen.lsp net.txt wider.txt 20
; and go on training with the start-file argument of backgammon_train.lsp.

(destructuring-bind (file new-file extra &optional (seed "1")) (command-line-arguments)
  (random-seed (string->number seed))
  (let* ((net (backgammon-load-net file))
         (wider (backgammon-widen-net net (string->number extra))))
    (backgammon-save-net wider new-file)
    (display (format "{} hidden units in {}, {} in {}\n"
                     (backgammon-net-hidden net) file (backgammon-net-hidden wider) new-file))))
