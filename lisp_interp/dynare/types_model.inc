// types_model.inc
// ===============
// The model of crash_model.inc with four kinds of households instead of one: the model part of types_irfs.mod. Only the households
// differ; the firms, the financial accelerator, the prices and the Fed are as in crash_model.inc (read that file's description first).
//
// The four kinds are the groups the Federal Reserve's Distributional Financial Accounts follow, by how much wealth a household has:
//   bottom50   the bottom half of households by wealth (2% of the nation's net worth)
//   next40     the 50th to the 90th percentile: the middle (29%)
//   next9      the 90th to the 99th percentile: the well off (36%)
//   top1       the top 1% (33%)
// (the shares are of net worth, 2026 Q2). What matters to the model is that they differ in three ways:
//
//   1. How many of them live from paycheck to paycheck. A part of each group (hand_to_mouth) spends all it earns each quarter and saves
//      nothing: what happens to its wages and hours happens to its spending. The rest (the "savers") plan ahead: they spend according to
//      the real interest rate and what they own, not what they earned this quarter.
//   2. How much of the stock market they own. The savers' spending rises when the stocks they own rise, and the top 1% owns half of all
//      stocks, the bottom half almost none (0.6%).
//   3. How much their jobs move with the economy. When hours fall, they fall more for the bottom half than for the top (earnings_cyclicality).
//
//
// The model also has a government with one tax: a WEALTH TAX on the top 1%, zero unless the caller sets it (the wealth_tax_shock). The
// section "A wealth tax on the top 1%" of the manual explains it; in short, the top 1% pays a percentage of its wealth each year, part of
// which is avoided; the revenue goes back to households, or is spent, or retires debt (the caller says); and the top 1% spends less as it
// gets poorer. Each assumption is a parameter, below, with what it is based on.
//
// The model also has an AI BUST: a fall in the spending and the share prices of the companies building artificial intelligence, zero
// unless the caller sets its size (the ai_shock). The section "A shock to the AI companies" of the manual explains it; in short, the AI
// companies' investment falls (only the part of it made in the US counts in GDP: the rest is imported), their shares fall (households
// own them as they own other stocks), lenders may grow fearful (the credit spread), and the AI that other firms use may get cheaper
// (their productivity). Each part is a parameter; the Lisp function ai-bust-scenarios gives three sets of them.
//
// Each group's share of the nation's spending, of its wages and of its stocks are the weights below. Every variable is a percent
// difference from its normal level, as in crash_model.inc; each group's consumption and income are percent differences from that
// group's own normal.

var
    gdp                       // GDP
    consumption               // consumption of all households together
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
    saver_consumption         // what a saver who owns no stocks would spend, apart from demand shocks: it follows the real interest rate
    income_bottom50           // the wages of the bottom half
    income_next40             // ... of the 50th to 90th percentile
    income_next9              // ... of the 90th to 99th
    income_top1               // ... of the top 1%
    wealth_tax                // the wealth tax on the top 1%: percent of its wealth a year (0 in normal times)
    wealth_tax_revenue        // what the tax collects, after what is avoided: percent of GDP
    top1_wealth_lost          // how much poorer the tax has made the top 1%: percent of its wealth
    government_purchases      // what the government buys with the revenue: percent of GDP
    ai_bust                   // how much of the AI bust is still going on: 1 when it starts, fading slowly (0 in normal times)
    ai_investment             // the AI companies' investment (data centers, chips, servers): percent of GDP, from normal
    ai_stocks                 // the value of the AI companies' shares: percent from normal
    ai_productivity           // what cheaper AI adds to other firms' productivity: percent
    consumption_bottom50      // the spending of the bottom half
    consumption_next40        // ... of the 50th to 90th percentile
    consumption_next9         // ... of the 90th to 99th
    consumption_top1          // ... of the top 1%
;

varexo
    net_worth_shock           // a surprise in firms' net worth: wealth lost (or gained) other than through the economy's ups and downs
    lender_fear_shock         // a surprise in lenders' fears
    demand_shock              // a surprise in demand
    productivity_shock        // a surprise in productivity
    fed_shock                 // a surprise in the Fed's rate (monetary policy)
    cost_push_shock           // a surprise in inflation not explained by costs (a "cost-push" shock)
    wealth_tax_shock          // a surprise in the wealth tax: a rise in the rate, in points a year
    ai_shock                  // the AI bust: its size is in the ai_ parameters, so its typical size is 1
;

parameters
    patience risk_aversion labor_dislike capital_share depreciation price_stickiness capital_price_response accelerator
    leverage net_worth_survival consumption_share investment_share rental_share wealth_effect
    fed_inflation_response fed_gdp_response fed_smoothing
    productivity_persistence demand_persistence lender_fear_persistence
    net_worth_shock_size lender_fear_shock_size demand_shock_size productivity_shock_size fed_shock_size cost_push_shock_size
    consumption_weight_bottom50 consumption_weight_next40 consumption_weight_next9 consumption_weight_top1
    income_weight_bottom50 income_weight_next40 income_weight_next9 income_weight_top1
    stock_share_bottom50 stock_share_next40 stock_share_next9 stock_share_top1
    hand_to_mouth_bottom50 hand_to_mouth_next40 hand_to_mouth_next9 hand_to_mouth_top1
    earnings_cyclicality_bottom50 earnings_cyclicality_next40 earnings_cyclicality_next9 earnings_cyclicality_top1
    wealth_tax_shock_size wealth_tax_persistence tax_avoidance wealth_rebuilding wealth_spending_top1 tax_from_firm_equity
    household_wealth_to_gdp wealth_share_top1
    revenue_to_bottom50 revenue_to_next40 revenue_to_next9 revenue_to_top1 revenue_to_purchases
    ai_bust_persistence ai_investment_cut ai_investment_delay ai_domestic_share ai_stock_fall ai_market_share ai_credit_stress
    ai_productivity_gain ai_productivity_delay
;

// The calibration of everything but the households: as in crash_model.inc.
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
wealth_effect             = 0.1;        // how much ALL households' wish to spend rises with firms' net worth, added up: each group gets its stock_share of it
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

// The households. Each of the first three lists adds up to 1 (a caller who changes one of them must keep it so).
//
// Each group's share of all spending. NOT the Fed's data: roughly what the Consumer Expenditure Survey and studies of spending by wealth
// show (the rich save much of what they earn, so the top 1% is 33% of the wealth and about 8% of the spending).
consumption_weight_bottom50 = 0.29;
consumption_weight_next40   = 0.42;
consumption_weight_next9    = 0.21;
consumption_weight_top1     = 0.08;
// Each group's share of all wages. NOT the Fed's data: roughly what studies of earnings by wealth show.
income_weight_bottom50      = 0.20;
income_weight_next40        = 0.45;
income_weight_next9         = 0.24;
income_weight_top1          = 0.11;
// Each group's share of the corporate equities and mutual fund shares households own: the Fed's Distributional Financial Accounts, 2026 Q2
// (0.6%, 11.4%, 37.2% and 50.9%; one tenth of a point is taken off the top 1% so that they add to 1). The Lisp function wealth-by-type
// fetches the latest.
stock_share_bottom50        = 0.006;
stock_share_next40          = 0.114;
stock_share_next9           = 0.372;
stock_share_top1            = 0.508;
// The part of each group that spends all it earns each quarter. NOT the Fed's data: studies of "hand-to-mouth" households (Kaplan, Violante
// and Weidner, 2014) find about a third of US households, most of them with little wealth; this puts a third of all spending there.
hand_to_mouth_bottom50      = 0.70;
hand_to_mouth_next40        = 0.30;
hand_to_mouth_next9         = 0.10;
hand_to_mouth_top1          = 0;
// How much each group's hours move compared with the others': 1.4 means a group's hours fall 1.4% when the average falls 1%. NOT the Fed's
// data: unemployment and short hours fall hardest on the workers with the least pay and wealth. The model scales these so that the groups'
// hours, added up by their income_weight, equal the economy's hours.
earnings_cyclicality_bottom50 = 1.4;
earnings_cyclicality_next40   = 1.0;
earnings_cyclicality_next9    = 0.8;
earnings_cyclicality_top1     = 0.6;

// The wealth tax. NOT the Fed's data, except where it says so: these are assumptions, and the manual shows how much they matter.
wealth_tax_shock_size       = 1;        // the size of a typical surprise to the tax: 1 point a year (1% of the top 1%'s wealth each year)
wealth_tax_persistence      = 0.995;    // how long a change in the tax lasts: 0.995 a quarter is a tax that is nearly permanent (it lasts decades)
tax_avoidance               = 0.2;      // the part of the tax that is avoided and never collected: moving wealth abroad, valuing it low, giving it away
wealth_rebuilding           = 0.01;     // the part of the wealth the tax has taken that the top 1% makes up each quarter by saving (4% a year)
wealth_spending_top1        = 0.5;      // how much the top 1%'s spending falls when its wealth falls 1% (spending 2% of wealth a year is spending 1% of it, a half)
tax_from_firm_equity        = 0.25;     // the part of what the tax collects that comes out of firms' net worth (payouts to shareholders to pay it, sales of shares nobody buys)
household_wealth_to_gdp     = 5.6;      // households' net worth in years of GDP: the Fed's Financial Accounts, 2026 Q2 ($185.7 trillion; GDP $33.0 trillion)
wealth_share_top1           = 0.325;    // the top 1%'s share of households' net worth: the Fed's Distributional Financial Accounts, 2026 Q2
// What is done with the revenue, as shares of it (the rest retires government debt, which in this model has no effect). The calibration pays it
// out equally to every household: the bottom half of households get half of it, the next 40% get 40% of it, and so on.
revenue_to_bottom50         = 0.50;
revenue_to_next40           = 0.40;
revenue_to_next9            = 0.09;
revenue_to_top1             = 0.01;
revenue_to_purchases        = 0;        // the part spent on goods and services, instead

// The AI bust. All zero but the shares and the speeds: the caller (ai-bust-scenarios) gives a scenario's sizes. NOT the Fed's data, except
// where it says so; the manual shows how much they matter.
ai_bust_persistence         = 0.98;     // how slowly the bust fades: 0.98 a quarter leaves two thirds of it after five years
ai_investment_cut           = 0;        // how much the AI companies' investment falls, in percent of GDP (the boom is about 1.5% of GDP: see the manual)
ai_investment_delay         = 0.7;      // how slowly the cut comes: each quarter, investment moves 30% of the way to the cut (projects underway are finished)
ai_domestic_share           = 0.5;      // the part of AI investment made in the US (buildings, power, installation, US chip makers' design and profits); the rest is imported
ai_stock_fall               = 0;        // how much the AI companies' shares fall, in percent
ai_market_share             = 0.3;      // the AI companies' part of the US stock market (Nvidia, Microsoft, Alphabet, Amazon, Meta, Broadcom, Oracle and others)
ai_credit_stress            = 0;        // how much lenders' fear adds to the credit spread when the bust starts, in points a year (it fades as lender_fear does)
ai_productivity_gain        = 0;        // how much cheaper AI adds to the productivity of the firms that use it, in percent, once it has spread
ai_productivity_delay       = 0.9;      // how slowly that gain comes: each quarter, it moves 10% of the way

// Parameters given by the caller go here.

model(linear);
    # price_flexibility = (1 - price_stickiness) * (1 - patience * price_stickiness) / price_stickiness;   // how much inflation moves with marginal cost

    // What the wealth effect is for one group: the whole economy's wealth_effect, in proportion to the stocks the group owns (stock_share)
    // compared with the spending it does (consumption_weight). The top 1% owns half the stocks and does 8% of the spending: its wealth effect is
    // six times the economy's.
    # wealth_effect_bottom50 = wealth_effect * stock_share_bottom50 / consumption_weight_bottom50;
    # wealth_effect_next40   = wealth_effect * stock_share_next40 / consumption_weight_next40;
    # wealth_effect_next9    = wealth_effect * stock_share_next9 / consumption_weight_next9;
    # wealth_effect_top1     = wealth_effect * stock_share_top1 / consumption_weight_top1;

    // How much each group's hours (and so its wages) move when the economy's hours move 1%.
    # cyclicality_total = income_weight_bottom50 * earnings_cyclicality_bottom50 + income_weight_next40 * earnings_cyclicality_next40
        + income_weight_next9 * earnings_cyclicality_next9 + income_weight_top1 * earnings_cyclicality_top1;
    # hours_move_bottom50 = earnings_cyclicality_bottom50 / cyclicality_total;
    # hours_move_next40   = earnings_cyclicality_next40 / cyclicality_total;
    # hours_move_next9    = earnings_cyclicality_next9 / cyclicality_total;
    # hours_move_top1     = earnings_cyclicality_top1 / cyclicality_total;

    // What the tax collects, as a share of GDP, is in terms of the top 1%'s wealth in years of GDP; and firms' net worth, in quarters of GDP, is what
    // capital is worth (capital's share of what is made, over what a unit of capital yields each quarter) over leverage.
    # top1_wealth_to_gdp = wealth_share_top1 * household_wealth_to_gdp;
    # net_worth_to_gdp = capital_share / (rental_share * (1 / patience + 0.005)) / leverage;

    // The stocks households own: firms' net worth, and the shares of the AI companies, which are a part (ai_market_share) of the market. (In
    // the crash and the wealth tax, the AI shares don't move, and this is net worth alone.)
    # household_stocks = net_worth + ai_market_share * ai_stocks;

    // Households that plan ahead. A saver who owns no stocks spends less now when the real interest rate is high (it pays to wait); a
    // saver's spending is that, plus a rise when there is a demand shock, and when the shares the saver owns are worth more. (These are
    // the Euler equations of all the savers, written so that what they have in common appears once: they differ only in the stocks they own.)
    risk_aversion * saver_consumption = risk_aversion * saver_consumption(+1) - real_rate;
    real_rate = fed_rate - inflation(+1);

    // Households that live from paycheck to paycheck spend what they earn. What households earn together moves with GDP (what firms do not
    // pay in wages comes back as profits and as government benefits); a group's income moves more than that if its hours do. And what the
    // government pays out of the wealth tax to a group adds to its income, in percent of what the group spends.
    income_bottom50 = gdp + (hours_move_bottom50 - 1) * hours
        + revenue_to_bottom50 * wealth_tax_revenue / (consumption_share * consumption_weight_bottom50);
    income_next40   = gdp + (hours_move_next40 - 1) * hours
        + revenue_to_next40 * wealth_tax_revenue / (consumption_share * consumption_weight_next40);
    income_next9    = gdp + (hours_move_next9 - 1) * hours
        + revenue_to_next9 * wealth_tax_revenue / (consumption_share * consumption_weight_next9);
    income_top1     = gdp + (hours_move_top1 - 1) * hours
        + revenue_to_top1 * wealth_tax_revenue / (consumption_share * consumption_weight_top1);

    // What each group spends: the part that lives from paycheck to paycheck spends its wages, the rest spends as savers do.
    consumption_bottom50 = hand_to_mouth_bottom50 * income_bottom50
        + (1 - hand_to_mouth_bottom50) * (saver_consumption + (demand + wealth_effect_bottom50 * household_stocks) / risk_aversion);
    consumption_next40 = hand_to_mouth_next40 * income_next40
        + (1 - hand_to_mouth_next40) * (saver_consumption + (demand + wealth_effect_next40 * household_stocks) / risk_aversion);
    consumption_next9 = hand_to_mouth_next9 * income_next9
        + (1 - hand_to_mouth_next9) * (saver_consumption + (demand + wealth_effect_next9 * household_stocks) / risk_aversion);
    // The top 1%, who pay the wealth tax, also spend less as the tax makes them poorer.
    consumption_top1 = hand_to_mouth_top1 * income_top1
        + (1 - hand_to_mouth_top1) * (saver_consumption + (demand + wealth_effect_top1 * household_stocks) / risk_aversion
                                      - wealth_spending_top1 * top1_wealth_lost);

    // The economy's consumption is the groups' added up.
    consumption = consumption_weight_bottom50 * consumption_bottom50 + consumption_weight_next40 * consumption_next40
        + consumption_weight_next9 * consumption_next9 + consumption_weight_top1 * consumption_top1;

    // Workers: the real wage is what an hour's work costs them in the pleasure of consuming and not working (the wage that a union of all
    // the workers would ask: it looks at the economy's consumption).
    real_wage = risk_aversion * consumption + labor_dislike * hours;

    // Firms make goods from capital (the capital they had at the start of the quarter) and labor, and hire until an hour's work adds
    // what it costs and a unit of capital adds what it earns.
    gdp = productivity + ai_productivity + capital_share * capital(-1) + (1 - capital_share) * hours;
    marginal_cost = real_wage + hours - gdp;
    capital_earnings = marginal_cost + gdp - capital(-1);

    // Inflation (the New Keynesian Phillips curve): firms that can change their price raise it when their costs are high.
    inflation = patience * inflation(+1) + price_flexibility * marginal_cost + cost_push_shock;

    // Investment and the price of capital: the price of capital rises when investment is high compared with the capital there is.
    capital_price = capital_price_response * (investment - capital(-1));
    capital = (1 - depreciation) * capital(-1) + depreciation * investment;

    // The return on capital: what it earns in the quarter plus its resale price, less what it cost at the start of the quarter.
    capital_return = rental_share * capital_earnings + (1 - rental_share) * capital_price - capital_price(-1);

    // THE FINANCIAL ACCELERATOR, as in crash_model.inc.
    capital_return(+1) - real_rate = credit_spread;
    credit_spread = accelerator * (capital_price + capital - net_worth) + lender_fear;

    // Net worth: what the firms made on their capital, less what they owe on what they borrowed, added to the net worth they had.
    // And what the wealth tax takes from them: the part of the revenue that is paid out of firms' net worth, as a share of it.
    net_worth = net_worth_survival * (leverage * capital_return - (leverage - 1) * real_rate(-1) + net_worth(-1))
        + net_worth_shock - tax_from_firm_equity * wealth_tax_revenue / net_worth_to_gdp;

    // The wealth tax. The rate follows its surprises; what it collects is the rate times the top 1%'s wealth, less what is avoided; the top 1% is
    // that much poorer each quarter (a quarter of the rate a year), less what it makes up by saving; and the government spends some of the revenue.
    wealth_tax = wealth_tax_persistence * wealth_tax(-1) + wealth_tax_shock;
    wealth_tax_revenue = (1 - tax_avoidance) * wealth_tax * top1_wealth_to_gdp;
    top1_wealth_lost = (1 - wealth_rebuilding) * top1_wealth_lost(-1) + (1 - tax_avoidance) * wealth_tax / 4;
    government_purchases = revenue_to_purchases * wealth_tax_revenue;

    // What is made is bought: by households, by firms, by the government, and by the AI companies (the part of their investment made in the US).
    gdp = consumption_share * consumption + investment_share * investment + government_purchases + ai_domestic_share * ai_investment;

    // The Fed's rule.
    fed_rate = fed_smoothing * fed_rate(-1)
        + (1 - fed_smoothing) * (fed_inflation_response * inflation + fed_gdp_response * gdp) + fed_shock;

    // The shocks.
    productivity = productivity_persistence * productivity(-1) + productivity_shock;
    demand = demand_persistence * demand(-1) + demand_shock;
    lender_fear = lender_fear_persistence * lender_fear(-1) + lender_fear_shock + ai_credit_stress / 4 * ai_shock;

    // The AI bust. It starts at 1 and fades slowly. Investment moves part of the way to its cut each quarter, as projects underway are finished
    // or abandoned; the shares fall at once; cheaper AI raises other firms' productivity part of the way each quarter.
    ai_bust = ai_bust_persistence * ai_bust(-1) + ai_shock;
    ai_investment = ai_investment_delay * ai_investment(-1) - (1 - ai_investment_delay) * ai_investment_cut * ai_bust;
    ai_stocks = -ai_stock_fall * ai_bust;
    ai_productivity = ai_productivity_delay * ai_productivity(-1) + (1 - ai_productivity_delay) * ai_productivity_gain * ai_bust;
end;

steady;
check;
