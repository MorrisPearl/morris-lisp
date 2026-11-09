// crash_model.inc
// ===============
// A small model of the US economy in which a fall in the value of firms can slow the economy down: the model part of crash_irfs.mod (what
// happens after a shock, with parameters chosen by hand) and crash_estimate.mod (the parameters estimated from US data). Both include it.
//
// The economy, in words:
//
//   Households work, consume and save at the Fed's rate. Firms (the model's "entrepreneurs") make goods from labor and capital, and set
//   prices that change only now and then, as in oil_model.inc.
//   Firms own the capital and must pay for part of it with borrowed money. A lender can't see how well a firm will do, so it charges
//   more than the safe rate, and the more the firm borrows compared with its own net worth, the more it charges: the "external finance
//   premium". This is the financial accelerator of Bernanke, Gertler and Gilchrist (1999, "The Financial Accelerator in a Quantitative
//   Business Cycle Framework").
//   So a fall in the value of firms (a fall in their net worth: think of a stock market crash) raises the premium; with the premium
//   higher, firms invest less; with less investment the value of capital falls further, and net worth with it. The first blow is made
//   bigger as it goes around: that is the accelerator.
//   The Fed sets its rate by a Taylor rule. The model is linear, so it has no zero lower bound: it can't say what happens when the Fed
//   can't cut any more (2009 to 2015), which makes the crash of 2008 itself beyond what it can say.
//
// Every variable is a percent difference from its normal ("steady state") level, as in oil_model.inc. Rates and inflation are
// percentage points per quarter. doc/lisp_macro_models_manual.md explains the model and how to use it.

var
    gdp                       // GDP
    consumption               // consumption
    investment                // investment
    capital                   // capital (the amount of it at the end of the quarter)
    hours                     // hours worked
    real_wage                 // the real wage
    marginal_cost             // firms' real marginal cost
    capital_earnings          // what one more unit of capital earns firms in a quarter (its marginal product, in goods)
    capital_price             // the price of capital: what a unit of capital costs compared with a unit of goods (Tobin's q)
    capital_return            // the return on capital in the quarter, counting the change in its price
    real_rate                 // the real interest rate (the Fed's rate less the inflation expected)
    credit_spread             // the external finance premium: how much more than the safe rate firms are expected to pay for the money they borrow
    net_worth                 // firms' net worth: what they own less what they owe (the "stock market")
    inflation                 // inflation
    fed_rate                  // the Fed's interest rate
    productivity              // productivity
    demand                    // households' wish to spend now rather than later (a "demand shock")
    lender_fear               // how risky lenders find lending to firms (a "risk shock"): it adds to the premium
    // What the data show, for estimation: growth rates and levels in the units of the data file (crash_estimate.mod)
    consumption_growth_data investment_growth_data inflation_data fed_rate_data credit_spread_data
;

varexo
    net_worth_shock           // a surprise in firms' net worth: wealth lost (or gained) other than through the economy's ups and downs
    lender_fear_shock         // a surprise in lenders' fears
    demand_shock              // a surprise in demand
    productivity_shock        // a surprise in productivity
    fed_shock                 // a surprise in the Fed's rate (monetary policy)
    cost_push_shock           // a surprise in inflation not explained by costs (a "cost-push" shock)
;

parameters
    patience risk_aversion labor_dislike capital_share depreciation price_stickiness capital_price_response accelerator
    leverage net_worth_survival consumption_share investment_share rental_share wealth_effect
    fed_inflation_response fed_gdp_response fed_smoothing
    productivity_persistence demand_persistence lender_fear_persistence
    net_worth_shock_size lender_fear_shock_size demand_shock_size productivity_shock_size fed_shock_size cost_push_shock_size
;

// The calibration: values commonly used for the US, by the quarter. crash_estimate.mod estimates some of them from the data.
patience                  = 0.99;       // how much households value next quarter compared with this one (a real interest rate of 4% a year)
risk_aversion             = 1;          // how much households dislike uneven consumption
labor_dislike             = 1;          // how fast the wish not to work grows with hours
capital_share             = 0.35;       // capital's share of what is made
depreciation              = 0.025;      // the part of capital that wears out each quarter
price_stickiness          = 0.75;       // the chance a firm can't change its price this quarter
capital_price_response    = 0.25;       // how much the price of capital rises when investment rises 1% (the cost of changing the capital stock quickly)
accelerator               = 0.05;       // how much the premium rises when firms borrow 1% more compared with their net worth: THE ACCELERATOR (0: none)
leverage                  = 2;          // capital compared with net worth, in normal times: a firm owns 2 dollars of capital for each dollar of its own
net_worth_survival        = 0.97;       // the part of net worth that stays in the firms from one quarter to the next (the rest is paid out or lost)
consumption_share         = 0.8;        // consumption as a share of GDP, in normal times
investment_share          = 0.2;        // investment as a share of GDP
wealth_effect             = 0.1;        // how much households' wish to spend rises with firms' net worth (they own the shares): 0 is no wealth effect
// The share of the return on capital that is earned in the quarter (the rest is the capital's resale price), when the return on capital
// in normal times is the safe rate plus a premium of 2 points a year: (return - (1 - depreciation)) / return.
rental_share              = ((1 / patience + 0.005) - (1 - depreciation)) / (1 / patience + 0.005);
fed_inflation_response    = 1.5;        // how much the Fed raises its rate for a point of inflation
fed_gdp_response          = 0.125;      // how much the Fed raises its rate for a percent of GDP above normal
fed_smoothing             = 0.8;        // how slowly the Fed moves its rate toward what the rule says
productivity_persistence  = 0.95;       // how long a change in productivity lasts
demand_persistence        = 0.8;        // how long a change in demand lasts
lender_fear_persistence   = 0.9;        // how long lenders' fears last
net_worth_shock_size      = 2;          // the size of a typical surprise to net worth, in percent
lender_fear_shock_size    = 0.1;        // a typical surprise to the premium, points a quarter
demand_shock_size         = 1;
productivity_shock_size   = 0.7;
fed_shock_size            = 0.25;
cost_push_shock_size      = 0.2;

// Parameters given by the caller go here.

model(linear);
    # price_flexibility = (1 - price_stickiness) * (1 - patience * price_stickiness) / price_stickiness;   // how much inflation moves with marginal cost

    // Households: they spend more now when the real interest rate is low, or when they would rather spend now: because of a demand shock
    // (demand), or because the shares they own are worth more (wealth_effect * net_worth).
    risk_aversion * consumption = risk_aversion * consumption(+1) - real_rate
        + ((demand + wealth_effect * net_worth) - (demand(+1) + wealth_effect * net_worth(+1)));
    real_rate = fed_rate - inflation(+1);

    // Workers: the real wage is what an hour's work costs them in the pleasure of consuming and not working.
    real_wage = risk_aversion * consumption + labor_dislike * hours;

    // Firms make goods from capital (the capital they had at the start of the quarter) and labor, and hire until an hour's work adds
    // what it costs and a unit of capital adds what it earns.
    gdp = productivity + capital_share * capital(-1) + (1 - capital_share) * hours;
    marginal_cost = real_wage + hours - gdp;
    capital_earnings = marginal_cost + gdp - capital(-1);

    // Inflation (the New Keynesian Phillips curve): firms that can change their price raise it when their costs are high.
    inflation = patience * inflation(+1) + price_flexibility * marginal_cost + cost_push_shock;

    // Investment and the price of capital: the price of capital rises when investment is high compared with the capital there is.
    capital_price = capital_price_response * (investment - capital(-1));
    capital = (1 - depreciation) * capital(-1) + depreciation * investment;

    // The return on capital: what it earns in the quarter plus its resale price, less what it cost at the start of the quarter.
    capital_return = rental_share * capital_earnings + (1 - rental_share) * capital_price - capital_price(-1);

    // THE FINANCIAL ACCELERATOR. Firms buy capital until its expected return is the safe rate plus the premium; and the premium rises
    // with how much they borrow compared with their own net worth (capital_price + capital - net_worth).
    capital_return(+1) - real_rate = credit_spread;
    credit_spread = accelerator * (capital_price + capital - net_worth) + lender_fear;

    // Net worth: what the firms made on their capital, less what they owe on what they borrowed, added to the net worth they had.
    // (leverage is capital over net worth, so leverage - 1 is borrowing over net worth.)
    net_worth = net_worth_survival * (leverage * capital_return - (leverage - 1) * real_rate(-1) + net_worth(-1))
        + net_worth_shock;

    // What is made is bought.
    gdp = consumption_share * consumption + investment_share * investment;

    // The Fed's rule.
    fed_rate = fed_smoothing * fed_rate(-1)
        + (1 - fed_smoothing) * (fed_inflation_response * inflation + fed_gdp_response * gdp) + fed_shock;

    // The shocks.
    productivity = productivity_persistence * productivity(-1) + productivity_shock;
    demand = demand_persistence * demand(-1) + demand_shock;
    lender_fear = lender_fear_persistence * lender_fear(-1) + lender_fear_shock;

    // What the data show (each series less its average over the sample):
    // (GDP growth is not observed: in this model GDP is consumption_share times consumption plus investment_share times investment, so the data on all three would
    // fit an exact equation, which real data never do.)
    consumption_growth_data   = consumption - consumption(-1);        // consumption growth, percent a quarter
    investment_growth_data    = investment - investment(-1);          // investment growth
    inflation_data            = inflation;                            // inflation
    fed_rate_data             = fed_rate;                             // the federal funds rate, percent a quarter
    credit_spread_data        = credit_spread;                        // the spread of corporate bond yields over Treasuries, percent a quarter
end;

steady;
check;
