// oil_model.inc
// =============
// A small model of the US economy in which the price of oil can jump: the model part of oil_irfs.mod (what happens after a shock, with
// parameters chosen by hand) and oil_estimate.mod (the parameters estimated from US data). Both files include this one.
//
// The economy, in words:
//
//   Households buy a bundle of domestic goods and oil (gasoline, heating oil). They save or borrow at the Fed's rate, and work.
//   Firms make the domestic good from labor and oil, and set prices that change only now and then (a Calvo price: each quarter a firm has
//   the chance 1 - theta to change its price), so an increase in costs shows up in inflation slowly.
//   Oil comes from abroad, paid for with domestic goods; its price, compared with domestic goods, moves on its own (an "exogenous" shock).
//   Real wages may be slow to adjust (gamma): workers resist a cut in what their pay buys. This is the reason an oil shock does more harm
//   when wages are rigid (Blanchard and Gali, 2007, "The Macroeconomic Effects of Oil Price Shocks: Why are the 2000s so Different from the
//   1970s?").
//   The Fed sets its rate by a Taylor rule: it raises the rate when inflation or output is above normal, a little at a time.
//
// Every variable is a percent difference from its normal ("steady state") level: y = 1 means GDP is 1% above normal. Rates and inflation
// are percentage points, per quarter: pi_c = 0.5 is inflation half a point a quarter (about 2 points a year) above normal. The equations
// are the model's first-order (log-linear) approximation, which is what Dynare would compute from the full model anyway; written out,
// each one can be read as a sentence. doc/lisp_macro_models_manual.md explains the model and how to use it.

var
    y        // GDP (value added: domestic goods made, less the oil used to make them)
    c        // consumption
    n        // hours worked
    m        // oil used by firms
    q        // domestic goods made (gross output)
    w        // the real wage: what an hour's pay buys of the consumption bundle
    mc       // firms' real marginal cost: what one more unit costs to make, in domestic goods
    pi_q     // core inflation: the price of domestic goods
    pi_c     // headline inflation: the price of the consumption bundle, oil included
    i        // the Fed's interest rate
    s        // the real price of oil: the price of oil compared with the price of domestic goods
    a        // productivity
    z        // households' wish to spend now rather than later (a "demand shock")
    // What the data show, for estimation: growth rates and levels in the units of the data file (oil_estimate.mod)
    dy_obs dw_obs pi_q_obs pi_c_obs i_obs ds_obs
;

varexo
    e_oil    // a surprise in the price of oil
    e_a      // a surprise in productivity
    e_z      // a surprise in demand
    e_i      // a surprise in the Fed's rate (monetary policy)
    e_p      // a surprise in core inflation not explained by costs (a "cost-push" shock: a change in firms' markups)
    e_w      // a surprise in wages not explained by the labor market (a change in workers' bargaining power)
;

parameters
    beta sigma phi alpha chi markup theta gamma
    phi_pi phi_y rho_i core_weight
    rho_a rho_z rho_s
    sigma_oil sigma_a sigma_z sigma_i sigma_p sigma_w
;

// The calibration: values commonly used for the US, by the quarter. oil_estimate.mod estimates most of them from the data.
beta        = 0.99;     // how much households value next quarter compared with this one (a real interest rate of 4% a year)
sigma       = 1;        // how much households dislike uneven consumption: 1 / sigma is how much spending moves with the real interest rate
phi         = 1;        // how fast the wish not to work grows with hours (1 / phi is the "Frisch elasticity" of labor supply)
alpha       = 0.02;     // oil's share of the cost of making domestic goods
chi         = 0.02;     // oil's share of what households buy
markup      = 1.2;      // firms' prices over their marginal cost, in normal times
theta       = 0.75;     // the chance a firm can't change its price this quarter (0.75: prices last a year, on average)
gamma       = 0.5;      // real wage rigidity: 0 is wages that adjust at once, near 1 is wages that hardly adjust
phi_pi      = 1.5;      // how much the Fed raises its rate for a point of inflation
phi_y       = 0.125;    // how much the Fed raises its rate for a percent of GDP above normal
rho_i       = 0.8;      // how slowly the Fed moves its rate toward what the rule says (0: at once)
core_weight = 0.5;      // the weight the Fed puts on core inflation; the rest is on headline inflation
rho_a       = 0.95;     // how long a change in productivity lasts (0: one quarter, near 1: almost for good)
rho_z       = 0.8;      // how long a change in demand lasts
rho_s       = 0.95;     // how long a change in the real price of oil lasts
sigma_oil   = 12;       // the size of a typical surprise, in percent: the price of oil moves about 12% in a typical quarter
sigma_a     = 0.7;
sigma_z     = 1;
sigma_i     = 0.25;
sigma_p     = 0.2;
sigma_w     = 0.5;

// Parameters given by the caller go here.

model(linear);
    // Quantities that follow from the parameters (model-local variables, written with #):
    # kappa   = (1 - theta) * (1 - beta * theta) / theta;   // how much core inflation moves with marginal cost
    # share_m = alpha / markup;                              // oil used by firms, as a share of domestic goods made
    # share_c = 1 - share_m;                                 // consumption, as a share of domestic goods made

    // Headline inflation is core inflation plus oil's share of what households buy times the change in the real price of oil.
    pi_c = pi_q + chi * (s - s(-1));

    // Households (the Euler equation): they spend more now when the real interest rate (the Fed's rate less the inflation they expect) is
    // low, or when they would rather spend now (z).
    sigma * c = sigma * c(+1) - (i - pi_c(+1)) + (z - z(+1));

    // Wages: the wage workers would accept for the hours they work (sigma * c + phi * n) is reached only a part 1 - gamma at a time.
    w = gamma * w(-1) + (1 - gamma) * (sigma * c + phi * n) + e_w;

    // Firms make domestic goods from labor and oil.
    q = a + (1 - alpha) * n + alpha * m;

    // They hire until an hour's work adds what it costs: the real wage in domestic goods is w + chi * s, since what the pay buys includes oil.
    n = mc + q - (w + chi * s);

    // And they buy oil until a barrel adds what it costs.
    m = mc + q - s;

    // Core inflation (the New Keynesian Phillips curve): firms that can change their price raise it when their costs are high, now and
    // expected. Higher oil prices raise costs both directly and through the real wage, when the real wage does not fall to make up for it.
    pi_q = beta * pi_q(+1) + kappa * mc + e_p;

    // What is made is bought: consumption (of domestic goods and of oil, paid for with domestic goods) and oil for firms.
    q = share_c * (c + chi * s) + share_m * (s + m);

    // GDP is what is made less the oil used to make it, at normal prices.
    y = (q - share_m * m) / share_c;

    // The Fed's rule: it moves its rate toward phi_pi times inflation (a mix of core and headline) plus phi_y times GDP, a part 1 - rho_i
    // at a time.
    i = rho_i * i(-1) + (1 - rho_i) * (phi_pi * (core_weight * pi_q + (1 - core_weight) * pi_c) + phi_y * y) + e_i;

    // The shocks: productivity, demand and the real price of oil last a while; the others last a quarter.
    a = rho_a * a(-1) + e_a;
    z = rho_z * z(-1) + e_z;
    s = rho_s * s(-1) + e_oil;

    // What the data show (the data file has each series less its average over the sample):
    dy_obs   = y - y(-1);     // GDP growth, percent a quarter
    dw_obs   = w - w(-1);     // real wage growth
    pi_q_obs = pi_q;          // core inflation
    pi_c_obs = pi_c;          // headline inflation
    i_obs    = i;             // the federal funds rate, percent a quarter
    ds_obs   = s - s(-1);     // the change in the real price of oil
end;

steady;
check;
