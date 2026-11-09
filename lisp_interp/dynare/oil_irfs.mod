// oil_irfs.mod
// ============
// What happens to the economy after each kind of surprise, quarter by quarter (impulse responses), for the model in oil_model.inc with the
// parameters as given there, or as the caller changes them. Each surprise is one typical size (its shock size); dynare-run's caller scales them.
//
// The caller can set, with dynare-run's :macros,
//   quarters   how many quarters to follow the economy after a surprise (default 20)

@#ifndef quarters
@#define quarters = 20
@#endif

@#include "oil_model.inc"

shocks;
    var oil_price_shock;    stderr oil_price_shock_size;
    var productivity_shock; stderr productivity_shock_size;
    var demand_shock;       stderr demand_shock_size;
    var fed_shock;          stderr fed_shock_size;
    var cost_push_shock;    stderr cost_push_shock_size;
    var wage_shock;         stderr wage_shock_size;
end;

// irf: how many quarters to follow; order=1: the linear model; nograph: the Lisp side draws the charts.
stoch_simul(order=1, irf=@{quarters}, nograph, nofunctions)
    gdp consumption hours real_wage marginal_cost core_inflation headline_inflation fed_rate real_oil_price goods_made oil_used;
