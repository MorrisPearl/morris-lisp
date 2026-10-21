"""What the tests of deals share, besides LispTestCase: a pool of mortgages in the form that new-deal takes its collateral, and a deal
whose collateral pays cash flows that are written out by hand, so that what the bonds are paid can be worked out on paper.

A deal made for a person has the cash flows of its collateral worked out from pieces of collateral (see new-deal). The hand-made deal
here is the same deal with the vectors of its root put in directly, which is how a test checks the rules of the tree (who is paid what,
in what order, and who is written down) on numbers that can be added up in the head."""

from support import *  # noqa: F401,F403 -- the interpreter's modules, numpy, mock, and LispTestCase


def numbers(values):
    """The numbers as Lisp text, floats, for the inside of (vector ...) or (list ...)."""
    return " ".join(repr(float(value)) for value in values)


def pool_of(balance, rate, term=360, age=0):
    """Lisp for a list of one piece of collateral, a pool of loans that pay a rate (in percent), have term months to run less the age,
    and are paid out at the same rate: what new-deal takes as :collateral."""
    return "(list (list %r %r %r %d %d))" % (float(balance), float(rate), float(rate), term - age, age)


def psa_deal(name, balance, rate, term=360, age=0, psa=100, options=""):
    """Lisp for a deal of one pool of loans (see pool_of) that prepays at this many percent of the PSA curve: the pricing speed.
    options is more arguments for new-deal, as text."""
    return '(new-deal "%s" :collateral %s :speed (prepayment-speed (quote psa) %d) %s)' % (name, pool_of(balance, rate, term, age), psa, options)


HAND_DEAL = """
(define (hand-deal name balances principals &key (interest '()) (coupon '()) (loss '()) (shortfalls #f))
  "A deal whose collateral, POOL, pays these cash flows month by month (vectors: the balances one longer than the others), with no pieces
of collateral to work them out from."
  (let* ((deal (new-deal name :shortfalls shortfalls))
         (pool (get-node deal "POOL")))
    (deal-set-periods! deal (vector-length principals))
    (node-balance-set! pool balances)
    (node-principal-set! pool principals)
    (unless (null? interest) (node-interest-set! pool interest))
    (unless (null? coupon) (node-coupon-set! pool coupon))
    (unless (null? loss) (node-loss-set! pool loss))
    deal))
"""


def hand_deal(balances, principals, interest=None, coupon=None, loss=None, shortfalls=False, name="demo", variable="deal"):
    """Lisp that defines a variable (deal) as a hand-made deal (see HAND_DEAL), and pool as its collateral node. balances and principals
    are lists of numbers; interest and loss are too, if given; coupon is a number (0.12 is 12%), if given: the collateral's coupon."""
    options = ""
    if interest is not None:
        options += " :interest (vector %s)" % numbers(interest)
    if coupon is not None:
        options += " :coupon (constant-coupon %r)" % float(coupon)
    if loss is not None:
        options += " :loss (vector %s)" % numbers(loss)
    if shortfalls:
        options += " :shortfalls #t"
    return HAND_DEAL + '(define %s (hand-deal "%s" (vector %s) (vector %s)%s)) (define pool (get-node %s "POOL"))' % (
        variable, name, numbers(balances), numbers(principals), options, variable)


def level_pool(amount, months, coupon=None):
    """Lisp for a hand-made deal (see hand_deal) whose collateral pays this principal each of this many months, and, if there is a coupon,
    the interest on its balance at it."""
    balances = [amount * (months - t) for t in range(months + 1)]
    interest = None if coupon is None else [balance * coupon / 12 for balance in balances[:-1]]
    return hand_deal(balances, [amount] * months, interest=interest, coupon=coupon)
