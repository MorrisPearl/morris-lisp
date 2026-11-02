// crash_estimate.mod
// ==================
// The model in crash_model.inc, its parameters estimated from US data (Bayesian estimation; oil_estimate.mod explains the method).
//
// The data file, data.csv, has a column for each observed variable (varobs, below): the growth of consumption and investment, core
// inflation, the federal funds rate and the spread of corporate bond yields over Treasuries (the price of the external finance premium),
// each by the quarter in percent, less its average over the sample. (lib/macro_models.lsp makes it from FRED.)
//
// The caller can set, with dynare-run's :macros,
//   draws      how many draws each of the two chains makes (default 4000; the first half of them are thrown away as the chain settles)
//   quarters   how many quarters to follow the economy after a surprise (default 20)

@#ifndef draws
@#define draws = 4000
@#endif
@#ifndef quarters
@#define quarters = 20
@#endif

@#include "crash_model.inc"

varobs consumption_growth_data investment_growth_data inflation_data fed_rate_data credit_spread_data;

// What we believe before looking at the data. The parameters not listed keep the values crash_model.inc gives them (patience, capital_share, depreciation,
// leverage, net_worth_survival and the shares: these the data say little about, or they are measured directly).
estimated_params;
    price_stickiness,                   beta_pdf,       0.66,   0.10;  // how sticky prices are
    risk_aversion,                      gamma_pdf,      1.50,   0.375;
    labor_dislike,                      gamma_pdf,      2.00,   0.75;
    capital_price_response,             gamma_pdf,      0.25,   0.10;  // how costly it is to change the capital stock quickly
    accelerator,                        gamma_pdf,      0.05,   0.03;  // THE ACCELERATOR: how much the premium rises with firms' borrowing compared with their net worth
    wealth_effect,                      gamma_pdf,      0.10,   0.08;  // how much spending rises with the shares households own
    fed_inflation_response,             normal_pdf,     1.50,   0.25;
    fed_gdp_response,                   normal_pdf,     0.125,  0.05;
    fed_smoothing,                      beta_pdf,       0.75,   0.10;
    productivity_persistence,           beta_pdf,       0.50,   0.20;
    demand_persistence,                 beta_pdf,       0.50,   0.20;
    lender_fear_persistence,            beta_pdf,       0.50,   0.20;
    // The size of a typical surprise of each kind:
    stderr net_worth_shock,             inv_gamma_pdf,  2,      inf;
    stderr lender_fear_shock,           inv_gamma_pdf,  0.1,    inf;
    stderr demand_shock,                inv_gamma_pdf,  0.5,    inf;
    stderr productivity_shock,          inv_gamma_pdf,  0.5,    inf;
    stderr fed_shock,                   inv_gamma_pdf,  0.1,    inf;
    stderr cost_push_shock,             inv_gamma_pdf,  0.1,    inf;
    stderr credit_spread_data,          inv_gamma_pdf,  0.05,   inf;   // the part of the spread the model's premium doesn't explain
end;

estimation(datafile='data.csv', mode_compute=5, mh_replic=@{draws}, mh_nblocks=2, mh_tune_jscale, mh_drop=0.5,
           bayesian_irf, irf=@{quarters}, nograph, nodisplay, graph_format=none)
    gdp consumption investment hours real_wage inflation fed_rate net_worth capital_price credit_spread;
