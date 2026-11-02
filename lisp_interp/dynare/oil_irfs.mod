// oil_irfs.mod
// ============
// What happens to the economy after each kind of surprise, quarter by quarter (impulse responses), for the model in oil_model.inc with the
// parameters as given there, or as the caller changes them. Each surprise is one typical size (its sigma); dynare-run's caller scales them.
//
// The caller can set, with dynare-run's :macros,
//   quarters   how many quarters to follow the economy after a surprise (default 20)

@#ifndef quarters
@#define quarters = 20
@#endif

@#include "oil_model.inc"

shocks;
    var e_oil; stderr sigma_oil;
    var e_a;   stderr sigma_a;
    var e_z;   stderr sigma_z;
    var e_i;   stderr sigma_i;
    var e_p;   stderr sigma_p;
    var e_w;   stderr sigma_w;
end;

// irf: how many quarters to follow; order=1: the linear model; nograph: the Lisp side draws the charts.
stoch_simul(order=1, irf=@{quarters}, nograph, nofunctions) y c n w mc pi_q pi_c i s q m;
