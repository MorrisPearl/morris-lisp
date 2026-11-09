// types_irfs.mod
// ==============
// What happens to the economy, and to each of four kinds of households, after each kind of surprise, quarter by quarter (impulse
// responses), for the model in types_model.inc with the parameters as given there, or as the caller changes them. Each surprise is one
// typical size (its sigma); the Lisp side scales them.
//
// The caller can set, with dynare-run's :macros,
//   quarters   how many quarters to follow the economy after a surprise (default 20)

@#ifndef quarters
@#define quarters = 20
@#endif

@#include "types_model.inc"

shocks;
    var net_worth_shock;    stderr net_worth_shock_size;
    var lender_fear_shock;  stderr lender_fear_shock_size;
    var demand_shock;       stderr demand_shock_size;
    var productivity_shock; stderr productivity_shock_size;
    var fed_shock;          stderr fed_shock_size;
    var cost_push_shock;    stderr cost_push_shock_size;
    var wealth_tax_shock;   stderr wealth_tax_shock_size;
    var ai_shock;           stderr 1;
end;

stoch_simul(order=1, irf=@{quarters}, nograph, nofunctions)
    gdp consumption investment hours real_wage inflation fed_rate net_worth capital_price credit_spread
    income_bottom50 income_next40 income_next9 income_top1
    consumption_bottom50 consumption_next40 consumption_next9 consumption_top1
    wealth_tax wealth_tax_revenue top1_wealth_lost government_purchases
    ai_investment ai_stocks ai_productivity;
