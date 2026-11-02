% export_results.m
% ================
% Run by dynare-run (lisp_dynare.py) after Dynare: writes what Dynare found to results.json, for the Lisp side to read. Every part is
% written only if the run made it (impulse responses come from stoch_simul or estimation's bayesian_irf, the posterior from estimation).

results = struct();
results.param_names = M_.param_names;
results.param_values = M_.params;
results.shock_names = M_.exo_names;
results.shock_stderr = sqrt(diag(M_.Sigma_e));
results.endo_names = M_.endo_names;

if isfield(oo_, 'irfs')
    results.irfs = oo_.irfs;                        % one vector a variable and shock: "y_e_oil" is y after e_oil
end

if isfield(oo_, 'variance_decomposition') && ~isempty(oo_.variance_decomposition)
    results.variance_decomposition = oo_.variance_decomposition;    % a row for each variable of var_list_, a column a shock, in percent
    results.variance_decomposition_names = var_list_;
end

if isfield(oo_, 'posterior_mode')
    results.posterior_mode = oo_.posterior_mode;
end
if isfield(oo_, 'posterior_mean')
    results.posterior_mean = oo_.posterior_mean;
    results.posterior_hpdinf = oo_.posterior_hpdinf;    % the bottom of the 90% highest posterior density interval
    results.posterior_hpdsup = oo_.posterior_hpdsup;    % and its top
end
if exist('bayestopt_', 'var') && isfield(bayestopt_, 'name')
    results.prior_names = bayestopt_.name;
    results.prior_mean = bayestopt_.p1;
    results.prior_stdev = bayestopt_.p2;
end
if isfield(oo_, 'MarginalDensity')
    results.marginal_density = oo_.MarginalDensity;
end
if isfield(oo_, 'PosteriorIRF')
    results.posterior_irf_mean = oo_.PosteriorIRF.dsge.Mean;
    results.posterior_irf_low = oo_.PosteriorIRF.dsge.HPDinf;
    results.posterior_irf_high = oo_.PosteriorIRF.dsge.HPDsup;
end

file = fopen('results.json', 'w');
fprintf(file, '%s', jsonencode(results));
fclose(file);
