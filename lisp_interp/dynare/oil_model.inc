// oil_model.inc
// =============
// A small model of the US economy in which the price of oil can jump: the model part of oil_irfs.mod (what happens after a shock, with
// parameters chosen by hand) and oil_estimate.mod (the parameters estimated from US data). Both files include this one.
//
// The economy, in words:
//
//   Households buy a bundle of domestic goods and oil (gasoline, heating oil). They save or borrow at the Fed's rate, and work.
//   Firms make the domestic good from labor and oil, and set prices that change only now and then (a Calvo price: each quarter a firm has
//   the chance 1 - price_stickiness to change its price), so an increase in costs shows up in inflation slowly.
//   Oil comes from abroad, paid for with domestic goods; its price, compared with domestic goods, moves on its own (an "exogenous" shock).
//   Real wages may be slow to adjust (wage_rigidity): workers resist a cut in what their pay buys. This is the reason an oil shock does more harm
//   when wages are rigid (Blanchard and Gali, 2007, "The Macroeconomic Effects of Oil Price Shocks: Why are the 2000s so Different from the
//   1970s?").
//   The Fed sets its rate by a Taylor rule: it raises the rate when inflation or output is above normal, a little at a time.
//
// Every variable is a percent difference from its normal ("steady state") level: gdp = 1 means GDP is 1% above normal. Rates and inflation
// are percentage points, per quarter: headline_inflation = 0.5 is inflation half a point a quarter (about 2 points a year) above normal. The equations
// are the model's first-order (log-linear) approximation, which is what Dynare would compute from the full model anyway; written out,
// each one can be read as a sentence. doc/lisp_macro_models_manual.md explains the model and how to use it.

var
    gdp                       // GDP (value added: domestic goods made, less the oil used to make them)
    consumption               // consumption
    hours                     // hours worked
    oil_used                  // oil used by firms
    goods_made                // domestic goods made (gross output)
    real_wage                 // the real wage: what an hour's pay buys of the consumption bundle
    marginal_cost             // firms' real marginal cost: what one more unit costs to make, in domestic goods
    core_inflation            // core inflation: the price of domestic goods
    headline_inflation        // headline inflation: the price of the consumption bundle, oil included
    fed_rate                  // the Fed's interest rate
    real_oil_price            // the real price of oil: the price of oil compared with the price of domestic goods
    productivity              // productivity
    demand                    // households' wish to spend now rather than later (a "demand shock")
    // What the data show, for estimation: growth rates and levels in the units of the data file (oil_estimate.mod)
    gdp_growth_data real_wage_growth_data core_inflation_data headline_inflation_data fed_rate_data real_oil_price_change_data
;

varexo
    oil_price_shock           // a surprise in the price of oil
    productivity_shock        // a surprise in productivity
    demand_shock              // a surprise in demand
    fed_shock                 // a surprise in the Fed's rate (monetary policy)
    cost_push_shock           // a surprise in core inflation not explained by costs (a "cost-push" shock: a change in firms' markups)
    wage_shock                // a surprise in wages not explained by the labor market (a change in workers' bargaining power)
;

parameters
    patience risk_aversion labor_dislike oil_cost_share oil_consumption_share markup price_stickiness wage_rigidity
    fed_inflation_response fed_gdp_response fed_smoothing core_weight
    productivity_persistence demand_persistence oil_price_persistence
    oil_price_shock_size productivity_shock_size demand_shock_size fed_shock_size cost_push_shock_size wage_shock_size
;

// The calibration: values commonly used for the US, by the quarter. oil_estimate.mod estimates most of them from the data.
patience                  = 0.99;       // how much households value next quarter compared with this one (a real interest rate of 4% a year)
risk_aversion             = 1;          // how much households dislike uneven consumption: 1 / risk_aversion is how much spending moves with the real interest rate
labor_dislike             = 1;          // how fast the wish not to work grows with hours (1 / labor_dislike is the "Frisch elasticity" of labor supply)
oil_cost_share            = 0.02;       // oil's share of the cost of making domestic goods
oil_consumption_share     = 0.02;       // oil's share of what households buy
markup                    = 1.2;        // firms' prices over their marginal cost, in normal times
price_stickiness          = 0.75;       // the chance a firm can't change its price this quarter (0.75: prices last a year, on average)
wage_rigidity             = 0.5;        // real wage rigidity: 0 is wages that adjust at once, near 1 is wages that hardly adjust
fed_inflation_response    = 1.5;        // how much the Fed raises its rate for a point of inflation
fed_gdp_response          = 0.125;      // how much the Fed raises its rate for a percent of GDP above normal
fed_smoothing             = 0.8;        // how slowly the Fed moves its rate toward what the rule says (0: at once)
core_weight               = 0.5;        // the weight the Fed puts on core inflation; the rest is on headline inflation
productivity_persistence  = 0.95;       // how long a change in productivity lasts (0: one quarter, near 1: almost for good)
demand_persistence        = 0.8;        // how long a change in demand lasts
oil_price_persistence     = 0.95;       // how long a change in the real price of oil lasts
oil_price_shock_size      = 12;         // the size of a typical surprise, in percent: the price of oil moves about 12% in a typical quarter
productivity_shock_size   = 0.7;
demand_shock_size         = 1;
fed_shock_size            = 0.25;
cost_push_shock_size      = 0.2;
wage_shock_size           = 0.5;

// Parameters given by the caller go here.

model(linear);
    // Quantities that follow from the parameters (model-local variables, written with #):
    # price_flexibility               = (1 - price_stickiness) * (1 - patience * price_stickiness) / price_stickiness;// how much core inflation moves with marginal cost
    # oil_share_of_output             = oil_cost_share / markup;                                        // oil used by firms, as a share of domestic goods made
    # consumption_share_of_output     = 1 - oil_share_of_output;                                        // consumption, as a share of domestic goods made

    // Headline inflation is core inflation plus oil's share of what households buy times the change in the real price of oil.
    headline_inflation = core_inflation + oil_consumption_share * (real_oil_price - real_oil_price(-1));

    // Households (the Euler equation): they spend more now when the real interest rate (the Fed's rate less the inflation they expect) is
    // low, or when they would rather spend now (demand).
    risk_aversion * consumption = risk_aversion * consumption(+1) - (fed_rate - headline_inflation(+1)) + (demand - demand(+1));

    // Wages: the wage workers would accept for the hours they work (risk_aversion * consumption + labor_dislike * hours) is reached only a part 1 - wage_rigidity at a time.
    real_wage = wage_rigidity * real_wage(-1) + (1 - wage_rigidity) * (risk_aversion * consumption + labor_dislike * hours) + wage_shock;

    // Firms make domestic goods from labor and oil.
    goods_made = productivity + (1 - oil_cost_share) * hours + oil_cost_share * oil_used;

    // They hire until an hour's work adds what it costs: the real wage in domestic goods is real_wage + oil_consumption_share * real_oil_price, since what the pay buys includes oil.
    hours = marginal_cost + goods_made - (real_wage + oil_consumption_share * real_oil_price);

    // And they buy oil until a barrel adds what it costs.
    oil_used = marginal_cost + goods_made - real_oil_price;

    // Core inflation (the New Keynesian Phillips curve): firms that can change their price raise it when their costs are high, now and
    // expected. Higher oil prices raise costs both directly and through the real wage, when the real wage does not fall to make up for it.
    core_inflation = patience * core_inflation(+1) + price_flexibility * marginal_cost + cost_push_shock;

    // What is made is bought: consumption (of domestic goods and of oil, paid for with domestic goods) and oil for firms.
    goods_made = consumption_share_of_output * (consumption + oil_consumption_share * real_oil_price)
        + oil_share_of_output * (real_oil_price + oil_used);

    // GDP is what is made less the oil used to make it, at normal prices.
    gdp = (goods_made - oil_share_of_output * oil_used) / consumption_share_of_output;

    // The Fed's rule: it moves its rate toward fed_inflation_response times inflation (a mix of core and headline) plus fed_gdp_response times GDP, a part
    // 1 - fed_smoothing at a time.
    fed_rate = fed_smoothing * fed_rate(-1)
        + (1 - fed_smoothing) * (fed_inflation_response * (core_weight * core_inflation + (1 - core_weight) * headline_inflation)
                                 + fed_gdp_response * gdp)
        + fed_shock;

    // The shocks: productivity, demand and the real price of oil last a while; the others last a quarter.
    productivity = productivity_persistence * productivity(-1) + productivity_shock;
    demand = demand_persistence * demand(-1) + demand_shock;
    real_oil_price = oil_price_persistence * real_oil_price(-1) + oil_price_shock;

    // What the data show (the data file has each series less its average over the sample):
    gdp_growth_data             = gdp - gdp(-1);                              // GDP growth, percent a quarter
    real_wage_growth_data       = real_wage - real_wage(-1);                  // real wage growth
    core_inflation_data         = core_inflation;                             // core inflation
    headline_inflation_data     = headline_inflation;                         // headline inflation
    fed_rate_data               = fed_rate;                                   // the federal funds rate, percent a quarter
    real_oil_price_change_data  = real_oil_price - real_oil_price(-1);        // the change in the real price of oil
end;

steady;
check;
