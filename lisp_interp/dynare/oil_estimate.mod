// oil_estimate.mod
// ================
// The model in oil_model.inc, its parameters estimated from US data (Bayesian estimation): Dynare starts from what is believed about each
// parameter before looking at the data (its "prior"), finds the values that best fit the data together with the priors (the "posterior
// mode"), then draws many sets of values (Markov chain Monte Carlo) to find how sure the data let us be of each one.
//
// The data file, data.csv, has a column for each observed variable (varobs, below): GDP growth, real wage growth, core and headline
// inflation, the federal funds rate and the change in the real price of oil, each by the quarter in percent, less its average over the
// sample. (lib/macro_models.lsp makes it from FRED.)
//
// The caller can set, with dynare-run's :macros,
//   draws      how many draws each of the two chains makes (default 20000; the first half of them are thrown away as the chain settles)
//   quarters   how many quarters to follow the economy after a surprise (default 20)

@#ifndef draws
@#define draws = 20000
@#endif
@#ifndef quarters
@#define quarters = 20
@#endif

@#include "oil_model.inc"

// Headline inflation differs from core for reasons other than oil (food, for one), so the model allows it a measurement error.
varobs dy_obs dw_obs pi_q_obs pi_c_obs i_obs ds_obs;

// What we believe before looking at the data: for each parameter, the shape of the prior, its mean and its standard deviation. The
// parameters not listed keep the values oil_model.inc gives them (beta, alpha, chi, markup: these the data say little about).
estimated_params;
    theta,       beta_pdf,      0.66,  0.10;    // how sticky prices are
    gamma,       beta_pdf,      0.50,  0.20;    // how rigid real wages are
    sigma,       gamma_pdf,     1.50,  0.375;
    phi,         gamma_pdf,     2.00,  0.75;
    phi_pi,      normal_pdf,    1.50,  0.25;
    phi_y,       normal_pdf,    0.125, 0.05;
    rho_i,       beta_pdf,      0.75,  0.10;
    core_weight, beta_pdf,      0.50,  0.20;
    rho_a,       beta_pdf,      0.50,  0.20;
    rho_z,       beta_pdf,      0.50,  0.20;
    rho_s,       beta_pdf,      0.50,  0.20;
    // The size of a typical surprise of each kind (inverse gamma priors, which keep them positive and say little about them):
    stderr e_oil,    inv_gamma_pdf, 10,   inf;
    stderr e_a,      inv_gamma_pdf, 0.5,  inf;
    stderr e_z,      inv_gamma_pdf, 0.5,  inf;
    stderr e_i,      inv_gamma_pdf, 0.1,  inf;
    stderr e_p,      inv_gamma_pdf, 0.1,  inf;
    stderr e_w,      inv_gamma_pdf, 0.5,  inf;
    stderr pi_c_obs, inv_gamma_pdf, 0.1,  inf;   // the measurement error of headline inflation
end;

// mode_compute=5: Dynare's own optimizer for the posterior mode; mh_tune_jscale: it sizes the steps of the chains so that about a third
// of the proposed draws are taken; bayesian_irf: impulse responses for the draws, so they have bands around them; nograph, nodisplay,
// graph_format=none: no charts (the Lisp side draws its own, and Octave without a display crashes making them).
estimation(datafile='data.csv', mode_compute=5, mh_replic=@{draws}, mh_nblocks=2, mh_tune_jscale, mh_drop=0.5,
           bayesian_irf, irf=@{quarters}, nograph, nodisplay, graph_format=none) y c n w mc pi_q pi_c i s;
