/*
 * Monte Carlo analysis for a Google Sheet: a macro (Google Apps Script) that runs a spreadsheet model many times.
 *
 * It works on any spreadsheet that has a tab called "Sensitivity" laid out like the one the three-statement model
 * makes (lisp_financial_sensitivity.py).  The tab has
 *
 *   Number of runs, Random seed, Status   in column A, with their values in column B
 *   "Inputs"        a title in column A, a header row, and then a row for each cell to vary:
 *                     Input (a named range, or an address such as DCF!B9), Distribution, Low, Average, High, Shape
 *   "Custom values" (optional) a title, a header row, and a row for each possible value of an input whose distribution
 *                  is custom: the Input, the Value, and its Chance (any positive numbers; they are divided by their total)
 *   "Correlations"  a title, a header row, and a row for each pair of inputs that move together:
 *                     the first Input, the second Input, and their correlation (-1 to 1)
 *   "Outputs"       a title, a header row, and a row for each cell to record: a named range or an address
 *   "Results"       a title; everything below it is the macro's: a summary and then a row for each run
 *
 * For each run the macro draws a value for every input, types it into the input's cell (the spreadsheet works out
 * everything that depends on it), reads the output cells, and adds a row to the results with the run's number, the
 * inputs, and the outputs.  When it is finished (or stops) it puts every input cell back as it was: a number if it
 * was a number, a formula if it was a formula.
 *
 * Every distribution takes its numbers from the Low, Average, High and Shape columns, and no value is ever outside
 * Low and High.  (The Distributions tab of the model's workbook lists them with examples.)
 *   continuous
 *     uniform      every value from Low to High is equally likely (Average isn't used)
 *     triangular   Low to High, the likeliest being Average (a straight line up from Low to Average, and down to High)
 *     pert         like triangular, but smoother: more of the values near Average, fewer in the tails
 *     normal       the bell curve centered on Average, with Low and High two standard deviations either side of it
 *                  (so (High - Low) / 4 is the standard deviation)
 *     lognormal    never below Low (which must be above 0): the logarithm of the value is a bell curve; Average is the
 *                  mean, and Low and High are two standard deviations of the logarithm either side
 *     exponential  starts at Low, with mean Average: many small values and a few large ones
 *     gamma        starts at Low, with mean Average; Shape (bigger than 0) makes it more bell-shaped as it grows
 *     weibull      starts at Low, with mean Average; Shape (bigger than 0) says if the chance of a value rises or falls
 *     beta         from Low to High, with mean Average; Shape (bigger than 0) is how tightly values bunch round Average
 *   discrete
 *     discrete uniform  the whole numbers from Low to High, each equally likely
 *     bernoulli         Low or High, with mean Average (so the chance of High is (Average - Low) / (High - Low))
 *     binomial          Low + the number of successes in (High - Low) tries, with mean Average
 *     poisson           Low + a count of events with mean (Average - Low), with no more than High
 *     custom            the values and chances in the Custom values table
 *
 * A correlation between two inputs makes them move together (positive) or in opposite directions (negative): the
 * bell curves behind the draws are correlated, and each is then turned into its input's distribution, so the
 * distributions are as chosen and the rank correlation is close to the one given.
 *
 * Install it with Extensions > Apps Script: delete what is there, paste this file, and save.  The first time you
 * run it Google asks you to allow it to see and change this spreadsheet.  After the sheet is reloaded there is a
 * "Sensitivity" menu.  (To have a button instead: Insert > Drawing, draw one, and assign the script runMonteCarlo.)
 *
 * Google stops a script after six minutes, so the macro stops itself before that, with a note in the Status cell,
 * and sets a timer to go on a minute later with the next run (the first time, Google asks you to allow that too).
 * Or choose "Continue a run that stopped".  A run's draws depend only on the seed and the run's number, so the same
 * seed gives the same results however many pieces they are made in.
 */

var SHEET_NAME = "Sensitivity";
var MOST_SECONDS = 240;                 // stop this long after starting, to stay under Google's limit
var CONTINUE_AFTER_SECONDS = 60;        // and go on this long after stopping
var RUNS_PER_WRITE = 20;                // runs collected before the results sheet is written
var MOST_CELLS_OF_RESULTS = 2000000;
var CONTINUOUS = ["uniform", "triangular", "pert", "normal", "lognormal", "exponential", "gamma", "weibull", "beta"];
var DISCRETE = ["discrete uniform", "bernoulli", "binomial", "poisson", "custom"];
var DISTRIBUTIONS = CONTINUOUS.concat(DISCRETE);
var SECTIONS = ["inputs", "correlations", "outputs", "results"];
var OPTIONAL_SECTIONS = ["custom values"];
var SETUP_COLUMNS = 7;                  // the setup is in columns A to G (G says what the input is, and isn't read)
var MOST_TRIES = 100000;                // the most tries a binomial can have
var BISECTION_STEPS = 60;
var SAVED_INPUTS = "sensitivity_inputs";        // (document properties: the inputs as they were, and the seed)
var SAVED_SEED = "sensitivity_seed";

// what the summary above the runs says about each column: its label, and its formula (the range goes in place of %)
var SUMMARY = [
  ["Mean", "AVERAGE(%)"], ["Standard deviation", "STDEV(%)"], ["Lowest", "MIN(%)"],
  ["5th percentile", "PERCENTILE(%,0.05)"], ["25th percentile", "PERCENTILE(%,0.25)"], ["Median", "MEDIAN(%)"],
  ["75th percentile", "PERCENTILE(%,0.75)"], ["95th percentile", "PERCENTILE(%,0.95)"], ["Highest", "MAX(%)"]
];


// ---------------------------------------------------------------------------
// The menu
// ---------------------------------------------------------------------------

function onOpen() {
  SpreadsheetApp.getUi().createMenu("Sensitivity")
    .addItem("Run Monte Carlo", "runMonteCarlo")
    .addItem("Continue a run that stopped", "continueMonteCarlo")
    .addItem("Put the inputs back as they were", "putInputsBack")
    .addToUi();
}

function runMonteCarlo() {
  execute(false);
}

function continueMonteCarlo() {
  execute(true);
}

function putInputsBack() {
  var count = restoreInputs(SpreadsheetApp.getActive());
  tell(count ? "The " + count + " input cells are as they were." : "No input cells had been changed.");
}

/* A message in a box (there is no box when a timer starts the macro). */
function tell(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    // (nobody is looking at the sheet; the Status cell has the message)
  }
}

/* Go on with the run a minute from now, by itself. */
function scheduleContinuation() {
  removeContinuation();
  ScriptApp.newTrigger("continueMonteCarlo").timeBased().after(CONTINUE_AFTER_SECONDS * 1000).create();
}

function removeContinuation() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "continueMonteCarlo") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}


// ---------------------------------------------------------------------------
// Random numbers and the distributions
// ---------------------------------------------------------------------------

/* A function that gives numbers from 0 up to (not including) 1, the same ones every time for the same seed. */
function makeRandom(seed) {
  var state = seed >>> 0;
  return function () {
    state = (state + 0x6D2B79F5) >>> 0;
    var t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* The random numbers of one run: the seed and the run's number decide them. */
function randomForRun(seed, runNumber) {
  return makeRandom((seed + Math.imul(runNumber, 0x9E3779B1)) >>> 0);
}

/* A standard normal value (mean 0, standard deviation 1), by the Box-Muller method. */
function randomNormal(random) {
  var first = 1 - random();             // (not 0, which has no logarithm)
  var second = random();
  return Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * second);
}

/* The chance that a standard normal value is below z. */
function normalCdf(z) {
  var x = Math.abs(z) / Math.SQRT2;
  var t = 1 / (1 + 0.5 * x);
  var erfc = t * Math.exp(-x * x - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
    t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return z >= 0 ? 1 - 0.5 * erfc : 0.5 * erfc;
}

/* The z for which the chance of a standard normal value below it is p (Peter Acklam's approximation). */
function normalInverseCdf(p) {
  var a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  var b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  var c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  var d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  var tail = 0.02425;
  var q, r;
  if (p < tail) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > 1 - tail) {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  q = p - 0.5;
  r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

/* The natural logarithm of the gamma function, for x above 0 (the Lanczos approximation). */
function logGamma(x) {
  var coefficients = [76.18009172947146, -86.50532032941677, 24.01409824083091,
                      -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  var total = x + 5.5;
  total -= (x + 0.5) * Math.log(total);
  var series = 1.000000000190015;
  for (var n = 0; n < coefficients.length; n++) {
    series += coefficients[n] / (x + n + 1);
  }
  return -total + Math.log(2.5066282746310005 * series / x);
}

/* The chance that a gamma value with the given shape (and scale 1) is below x. */
function gammaCdf(shape, x) {
  if (x <= 0) {
    return 0;
  }
  var front = Math.exp(-x + shape * Math.log(x) - logGamma(shape));
  if (x < shape + 1) {
    // a series that converges quickly when x is small
    var term = 1 / shape, sum = term;
    for (var n = 1; n < 100000 && Math.abs(term) > Math.abs(sum) * 1e-13; n++) {
      term *= x / (shape + n);
      sum += term;
    }
    return sum * front;
  }
  // a continued fraction for the chance of being above x, which converges quickly when x is large
  var tiny = 1e-300, b = x + 1 - shape, c = 1 / tiny, d = 1 / b, fraction = d;
  for (var i = 1; i < 100000; i++) {
    var a = -i * (i - shape);
    b += 2;
    d = a * d + b;
    d = Math.abs(d) < tiny ? tiny : d;
    c = b + a / c;
    c = Math.abs(c) < tiny ? tiny : c;
    d = 1 / d;
    fraction *= d * c;
    if (Math.abs(d * c - 1) < 1e-13) {
      break;
    }
  }
  return 1 - front * fraction;
}

/* The continued fraction that betaCdf needs. */
function betaFraction(x, first, second) {
  var tiny = 1e-300;
  var keepAway = function (value) { return Math.abs(value) < tiny ? tiny : value; };
  var c = 1, d = 1 / keepAway(1 - (first + second) * x / (first + 1)), fraction = d;
  for (var m = 1; m < 100000; m++) {
    var twice = 2 * m;
    var a = m * (second - m) * x / ((first + twice - 1) * (first + twice));
    d = 1 / keepAway(1 + a * d);
    c = keepAway(1 + a / c);
    fraction *= d * c;
    a = -(first + m) * (first + second + m) * x / ((first + twice) * (first + twice + 1));
    d = 1 / keepAway(1 + a * d);
    c = keepAway(1 + a / c);
    fraction *= d * c;
    if (Math.abs(d * c - 1) < 1e-13) {
      break;
    }
  }
  return fraction;
}

/* The chance that a beta value (between 0 and 1) with the two shapes is below x. */
function betaCdf(x, first, second) {
  if (x <= 0) {
    return 0;
  }
  if (x >= 1) {
    return 1;
  }
  var front = Math.exp(logGamma(first + second) - logGamma(first) - logGamma(second) +
                       first * Math.log(x) + second * Math.log(1 - x));
  if (x < (first + 1) / (first + second + 2)) {
    return front * betaFraction(x, first, second) / first;
  }
  return 1 - front * betaFraction(1 - x, second, first) / second;
}

/*
 * The value from low to high for a probability p (0 to 1), for a distribution whose chance of being below x is
 * cdf(x): found by halving the distance between low and high until the chance there is right.  The part of the
 * distribution beyond low and high is left out, so p = 0 gives low and p = 1 gives high.
 */
function valueByCdf(cdf, low, high, p) {
  if (p <= 0) {
    return low;
  }
  if (p >= 1) {
    return high;
  }
  var atLow = cdf(low), atHigh = cdf(high);
  var target = atLow + p * (atHigh - atLow);
  var below = low, above = high;
  for (var step = 0; step < BISECTION_STEPS; step++) {
    var middle = (below + above) / 2;
    if (cdf(middle) < target) {
      below = middle;
    } else {
      above = middle;
    }
  }
  return (below + above) / 2;
}

function triangularValue(low, average, high, p) {
  if (high === low) {
    return low;
  }
  var chanceBelowAverage = (average - low) / (high - low);
  if (p < chanceBelowAverage) {
    return low + Math.sqrt(p * (high - low) * (average - low));
  }
  return high - Math.sqrt((1 - p) * (high - low) * (high - average));
}

/* A beta curve from low to high whose peak is at average (the "PERT" curve of project planning). */
function pertValue(low, average, high, p) {
  if (high === low) {
    return low;
  }
  var span = high - low;
  var first = 1 + 4 * (average - low) / span, second = 1 + 4 * (high - average) / span;
  var share = valueByCdf(function (x) { return betaCdf(x, first, second); }, 0, 1, p);
  return low + span * share;
}

/* The normal curve, with no value below low or above high: only the part of the probabilities between theirs is used. */
function normalValue(low, average, high, p) {
  var deviation = (high - low) / 4;
  if (deviation === 0) {
    return average;
  }
  var chanceBelowLow = normalCdf((low - average) / deviation);
  var chanceBelowHigh = normalCdf((high - average) / deviation);
  var value = average + deviation * normalInverseCdf(chanceBelowLow + p * (chanceBelowHigh - chanceBelowLow));
  return Math.min(Math.max(value, low), high);
}

function lognormalValue(low, average, high, p) {
  var deviation = (Math.log(high) - Math.log(low)) / 4;           // (of the logarithm)
  if (deviation === 0) {
    return average;
  }
  var center = Math.log(average) - deviation * deviation / 2;     // (so that the mean is average)
  return valueByCdf(function (x) { return normalCdf((Math.log(x) - center) / deviation); }, low, high, p);
}

function exponentialValue(low, average, high, p) {
  var mean = average - low;
  var chanceBelowHigh = 1 - Math.exp(-(high - low) / mean);
  return Math.min(low - mean * Math.log(1 - p * chanceBelowHigh), high);
}

function gammaValue(low, average, high, shape, p) {
  var scale = (average - low) / shape;
  return valueByCdf(function (x) { return gammaCdf(shape, (x - low) / scale); }, low, high, p);
}

function weibullValue(low, average, high, shape, p) {
  var scale = (average - low) / Math.exp(logGamma(1 + 1 / shape));        // (so that the mean is average)
  var chanceBelowHigh = 1 - Math.exp(-Math.pow((high - low) / scale, shape));
  var value = low + scale * Math.pow(-Math.log(1 - p * chanceBelowHigh), 1 / shape);
  return Math.min(value, high);
}

/* A beta curve from low to high with mean average; shape is the sum of the curve's two shapes. */
function betaValue(low, average, high, shape, p) {
  var share = (average - low) / (high - low);
  var first = share * shape, second = (1 - share) * shape;
  return low + (high - low) * valueByCdf(function (x) { return betaCdf(x, first, second); }, 0, 1, p);
}

function discreteUniformValue(low, high, p) {
  var count = high - low + 1;
  return low + Math.max(Math.ceil(p * count) - 1, 0);
}

function bernoulliValue(low, average, high, p) {
  var chanceOfHigh = (average - low) / (high - low);
  return p <= 1 - chanceOfHigh ? low : high;
}

/* low plus the number of successes in high - low tries, each succeeding with the chance that makes the mean average. */
function binomialValue(low, average, high, p) {
  var tries = high - low, chance = (average - low) / tries;
  if (chance <= 0) {
    return low;
  }
  if (chance >= 1) {
    return high;
  }
  var logChance = Math.log(chance), logMiss = Math.log(1 - chance);
  var logExactly = tries * logMiss;                                // (the chance of exactly 0 successes)
  var atMost = 0;
  for (var count = 0; count < tries; count++) {
    atMost += Math.exp(logExactly);
    if (atMost >= p) {
      return low + count;
    }
    logExactly += Math.log((tries - count) / (count + 1)) + logChance - logMiss;
  }
  return high;
}

/* low plus a Poisson count with mean average - low, if that is no more than high. */
function poissonValue(low, average, high, p) {
  var mean = average - low, most = high - low;
  if (mean <= 0) {
    return low;
  }
  var target = p * (1 - gammaCdf(most + 1, mean));                 // (the chance of a count of most or less is that)
  var logExactly = -mean;                                          // (the chance of exactly 0)
  var atMost = 0;
  for (var count = 0; count < most; count++) {
    atMost += Math.exp(logExactly);
    if (atMost >= target || (count > mean && logExactly < -50)) {
      return low + count;
    }
    logExactly += Math.log(mean / (count + 1));
  }
  return high;
}

/* The value of a custom input: choices are {value, upTo} in order of value, upTo being the chance of that value or less. */
function customValue(choices, p) {
  for (var n = 0; n < choices.length; n++) {
    if (p <= choices[n].upTo) {
      return choices[n].value;
    }
  }
  return choices[choices.length - 1].value;
}

/*
 * The value of an input for a probability p (0 to 1): the value that a draw from its distribution is below with
 * chance p.  An input is {distribution, low, average, high, shape, choices}.
 */
function valueForProbability(input, p) {
  var low = input.low, average = input.average, high = input.high, shape = input.shape;
  switch (input.distribution) {
    case "uniform": return low + p * (high - low);
    case "triangular": return triangularValue(low, average, high, p);
    case "pert": return pertValue(low, average, high, p);
    case "normal": return normalValue(low, average, high, p);
    case "lognormal": return lognormalValue(low, average, high, p);
    case "exponential": return exponentialValue(low, average, high, p);
    case "gamma": return gammaValue(low, average, high, shape, p);
    case "weibull": return weibullValue(low, average, high, shape, p);
    case "beta": return betaValue(low, average, high, shape, p);
    case "discrete uniform": return discreteUniformValue(low, high, p);
    case "bernoulli": return bernoulliValue(low, average, high, p);
    case "binomial": return binomialValue(low, average, high, p);
    case "poisson": return poissonValue(low, average, high, p);
    default: return customValue(input.choices, p);
  }
}

/*
 * The lower-triangular matrix L with L times its transpose equal to the (symmetric) matrix, so that L times
 * independent normal values gives normal values with the correlations of the matrix.  Null if no such matrix is
 * possible, as when A and B are correlated 0.9, B and C 0.9, but A and C -0.9.
 */
function choleskyFactor(matrix) {
  var size = matrix.length;
  var factor = [];
  for (var i = 0; i < size; i++) {
    factor.push(new Array(size).fill(0));
  }
  for (var row = 0; row < size; row++) {
    for (var column = 0; column <= row; column++) {
      var rest = matrix[row][column];
      for (var k = 0; k < column; k++) {
        rest -= factor[row][k] * factor[column][k];
      }
      if (row === column) {
        if (rest < -1e-9) {
          return null;
        }
        factor[row][row] = rest > 1e-12 ? Math.sqrt(rest) : 0;
      } else if (factor[column][column] > 0) {
        factor[row][column] = rest / factor[column][column];
      } else if (Math.abs(rest) > 1e-9) {
        return null;
      }
    }
  }
  return factor;
}

/* The values of all the inputs for one run: an array, in the order of the inputs. */
function drawInputs(inputs, factor, random) {
  var normals = inputs.map(function () { return randomNormal(random); });
  return inputs.map(function (input, row) {
    var correlated = 0;
    for (var column = 0; column <= row; column++) {
      correlated += factor[row][column] * normals[column];
    }
    var probability = Math.min(Math.max(normalCdf(correlated), 1e-12), 1 - 1e-12);
    return valueForProbability(input, probability);
  });
}


// ---------------------------------------------------------------------------
// Reading the setup
// ---------------------------------------------------------------------------

function fail(message) {
  throw new Error(message);
}

function normalized(value) {
  return String(value).trim().toLowerCase();
}

/* The value in column B of the row whose column A begins with the label, or undefined if there is no such row. */
function parameterRow(block, label, resultsRow) {
  for (var r = 1; r < resultsRow; r++) {
    if (normalized(block[r - 1][0]).indexOf(label) === 0) {
      return r;
    }
  }
  return 0;
}

/* The single cell that a name or an address stands for. */
function findCell(spreadsheet, text, row) {
  var range = spreadsheet.getRangeByName(text);
  if (!range) {
    try {
      range = spreadsheet.getRange(text);
    } catch (error) {
      range = null;
    }
  }
  if (!range) {
    fail("Row " + row + ": there is no named range or cell called " + text + ".");
  }
  if (range.getNumRows() !== 1 || range.getNumColumns() !== 1) {
    fail("Row " + row + ": " + text + " is more than one cell.");
  }
  return range;
}

function isNumber(value) {
  return typeof value === "number" && isFinite(value);
}

/* The distributions that have no Average, that have a Shape, and that start at Low (so Average has to be above it). */
var WITHOUT_AVERAGE = ["uniform", "discrete uniform", "custom"];
var WITH_SHAPE = ["gamma", "weibull", "beta"];
var STARTING_AT_LOW = ["exponential", "gamma", "weibull"];
var WHOLE_NUMBERS = ["discrete uniform", "binomial", "poisson"];

/* Checks the numbers of an input against what its distribution needs, saying what is wrong in a message. */
function checkNumbers(input, row) {
  var kind = input.distribution, name = input.name;
  if (kind === "custom") {
    return;                             // (its values are in the Custom values table)
  }
  var hasAverage = WITHOUT_AVERAGE.indexOf(kind) < 0;
  if (!hasAverage && !isNumber(input.average)) {
    input.average = (input.low + input.high) / 2;
  }
  if (!isNumber(input.low) || !isNumber(input.average) || !isNumber(input.high)) {
    fail("Row " + row + ": " + name + " needs numbers for " + (hasAverage ? "Low, Average, and High" : "Low and High") + ".");
  }
  if (input.low > input.high || (hasAverage && (input.average < input.low || input.average > input.high))) {
    fail("Row " + row + ": " + name + " needs " + (hasAverage ? "Low, Average, High" : "Low, High") + " in order, smallest first.");
  }
  if (WITH_SHAPE.indexOf(kind) >= 0 && (!isNumber(input.shape) || input.shape <= 0)) {
    fail("Row " + row + ": " + name + " (" + kind + ") needs a Shape bigger than 0.");
  }
  if (kind === "lognormal" && input.low <= 0) {
    fail("Row " + row + ": " + name + " (lognormal) needs a Low bigger than 0.");
  }
  if (STARTING_AT_LOW.indexOf(kind) >= 0 && input.average <= input.low) {
    fail("Row " + row + ": " + name + " (" + kind + ") needs an Average above Low.");
  }
  if ((kind === "beta" && (input.average <= input.low || input.average >= input.high)) ||
      ((kind === "bernoulli" || kind === "binomial") && input.high <= input.low)) {
    fail("Row " + row + ": " + name + " (" + kind + ") needs Low below " + (kind === "beta" ? "Average below " : "") + "High.");
  }
  if (WHOLE_NUMBERS.indexOf(kind) >= 0 && (input.low !== Math.floor(input.low) || input.high !== Math.floor(input.high))) {
    fail("Row " + row + ": " + name + " (" + kind + ") needs whole numbers for Low and High.");
  }
  if ((kind === "binomial" && input.high - input.low > MOST_TRIES) || (kind === "poisson" && input.average - input.low > MOST_TRIES)) {
    fail("Row " + row + ": " + name + " (" + kind + ") is too large: " + MOST_TRIES + " is the most.");
  }
}

/* Gives each custom input its choices {value, upTo}, from the rows of the Custom values table (Input, Value, Chance). */
function readCustomValues(inputs, rows, block, numberOf) {
  var chances = inputs.map(function () { return []; });
  rows.forEach(function (r) {
    var number = numberOf(block[r - 1][0], r), value = block[r - 1][1], chance = block[r - 1][2];
    if (inputs[number].distribution !== "custom") {
      fail("Row " + r + ": " + inputs[number].name + " is not a custom distribution, so it has no custom values.");
    }
    if (!isNumber(value) || !isNumber(chance) || chance < 0) {
      fail("Row " + r + ": a custom value needs a number for Value and a chance that is 0 or more.");
    }
    chances[number].push({value: value, chance: chance});
  });
  inputs.forEach(function (input, number) {
    if (input.distribution !== "custom") {
      return;
    }
    var total = chances[number].reduce(function (sum, row) { return sum + row.chance; }, 0);
    if (total <= 0) {
      fail(input.name + " is a custom distribution: give it rows in the Custom values table, with chances above 0.");
    }
    var sorted = chances[number].slice().sort(function (first, second) { return first.value - second.value; });
    var upTo = 0;
    input.choices = sorted.map(function (row) {
      upTo += row.chance / total;
      return {value: row.value, upTo: upTo};
    });
    input.low = sorted[0].value;
    input.high = sorted[sorted.length - 1].value;
  });
}

/*
 * What the Sensitivity tab says to do, checked: {runs, seed (or null), inputs, correlations, outputs, rows} where an
 * input is {name, distribution, low, average, high, shape, choices, range} (choices only for a custom distribution),
 * a correlation {first, second, value} (the numbers of the inputs), an output {name, range}, and resultsRow is the
 * row with the Results title.
 */
function readSetup(spreadsheet, sheet) {
  var titles = sheet.getRange(1, 1, sheet.getLastRow(), 1).getValues().map(function (row) { return normalized(row[0]); });
  var titleRow = {};
  SECTIONS.concat(OPTIONAL_SECTIONS).forEach(function (title) {
    var at = titles.indexOf(title);
    if (at < 0 && OPTIONAL_SECTIONS.indexOf(title) < 0) {
      fail('The ' + SHEET_NAME + ' tab needs a row with "' + title[0].toUpperCase() + title.slice(1) + '" in column A.');
    }
    if (at >= 0) {
      titleRow[title] = at + 1;
    }
  });
  var resultsRow = titleRow.results;
  var block = sheet.getRange(1, 1, resultsRow, SETUP_COLUMNS).getValues();

  // a table's rows: from two below its title (the header is between) until the next title
  var rowsOf = function (title) {
    var end = resultsRow;
    Object.keys(titleRow).forEach(function (other) {
      if (titleRow[other] > titleRow[title] && titleRow[other] < end) {
        end = titleRow[other];
      }
    });
    var rows = [];
    for (var r = titleRow[title] + 2; r < end; r++) {
      if (String(block[r - 1][0]).trim() !== "") {
        rows.push(r);
      }
    }
    return rows;
  };

  var runsRow = parameterRow(block, "number of runs", resultsRow);
  var runs = runsRow ? block[runsRow - 1][1] : null;
  if (!isNumber(runs) || runs < 1 || runs !== Math.floor(runs)) {
    fail('"Number of runs" needs a whole number, 1 or more, in column B.');
  }
  var seedRow = parameterRow(block, "random seed", resultsRow);
  var seed = seedRow && String(block[seedRow - 1][1]).trim() !== "" ? block[seedRow - 1][1] : null;
  if (seed !== null && (!isNumber(seed) || seed !== Math.floor(seed))) {
    fail('"Random seed" needs a whole number, or nothing.');
  }

  var inputs = [];
  rowsOf("inputs").forEach(function (r) {
    var name = String(block[r - 1][0]).trim();
    var distribution = normalized(block[r - 1][1]);
    if (DISTRIBUTIONS.indexOf(distribution) < 0) {
      fail("Row " + r + ": the distribution of " + name + " must be one of " + DISTRIBUTIONS.join(", ") + ", not \"" + block[r - 1][1] + "\".");
    }
    var input = {name: name, distribution: distribution, low: block[r - 1][2], average: block[r - 1][3],
                 high: block[r - 1][4], shape: block[r - 1][5]};
    checkNumbers(input, r);
    if (inputs.some(function (other) { return normalized(other.name) === normalized(name); })) {
      fail("Row " + r + ": " + name + " is already an input.");
    }
    input.range = findCell(spreadsheet, name, r);
    if (!isNumber(input.range.getValue())) {
      fail("Row " + r + ": " + name + " has to be a number now (it is " + input.range.getValue() + ").");
    }
    inputs.push(input);
  });
  if (inputs.length === 0) {
    fail("There are no inputs: fill in the first column of the Inputs table.");
  }

  var numberOf = function (name, r) {
    for (var n = 0; n < inputs.length; n++) {
      if (normalized(inputs[n].name) === normalized(name)) {
        return n;
      }
    }
    fail("Row " + r + ": " + name + " is not one of the inputs.");
  };
  readCustomValues(inputs, titleRow["custom values"] ? rowsOf("custom values") : [], block, numberOf);

  var correlations = [];
  rowsOf("correlations").forEach(function (r) {
    var first = numberOf(block[r - 1][0], r), second = numberOf(block[r - 1][1], r), value = block[r - 1][2];
    if (first === second) {
      fail("Row " + r + ": " + block[r - 1][0] + " can't be correlated with itself.");
    }
    if (!isNumber(value) || value < -1 || value > 1) {
      fail("Row " + r + ": a correlation is a number from -1 to 1.");
    }
    if (correlations.some(function (c) { return (c.first === first && c.second === second) || (c.first === second && c.second === first); })) {
      fail("Row " + r + ": that pair is already there.");
    }
    correlations.push({first: first, second: second, value: value});
  });

  var outputs = [];
  rowsOf("outputs").forEach(function (r) {
    var name = String(block[r - 1][0]).trim();
    outputs.push({name: name, range: findCell(spreadsheet, name, r)});
  });
  if (outputs.length === 0) {
    fail("There are no outputs: fill in the first column of the Outputs table.");
  }

  return {runs: runs, seed: seed, inputs: inputs, correlations: correlations, outputs: outputs,
          resultsRow: resultsRow};
}

/* The matrix of correlations (1 on the diagonal) and its factor, or an error saying they can't all be true. */
function correlationFactor(setup) {
  var size = setup.inputs.length;
  var matrix = [];
  for (var i = 0; i < size; i++) {
    matrix.push(new Array(size).fill(0));
    matrix[i][i] = 1;
  }
  setup.correlations.forEach(function (c) {
    matrix[c.first][c.second] = c.value;
    matrix[c.second][c.first] = c.value;
  });
  var factor = choleskyFactor(matrix);
  if (factor === null) {
    fail("The correlations can't all be true together (for example, A and B at 0.9, B and C at 0.9, and A and C at -0.9). Make some smaller.");
  }
  return factor;
}


// ---------------------------------------------------------------------------
// Putting the inputs back
// ---------------------------------------------------------------------------

function addressOf(range) {
  return "'" + range.getSheet().getName().replace(/'/g, "''") + "'!" + range.getA1Notation();
}

/* Keep each input cell as it is now (its formula, if it has one), to put it back. */
function saveInputs(inputs) {
  var saved = inputs.map(function (input) {
    return {address: addressOf(input.range), formula: input.range.getFormula(), value: input.range.getValue()};
  });
  PropertiesService.getDocumentProperties().setProperty(SAVED_INPUTS, JSON.stringify(saved));
}

/* Put back the input cells that saveInputs kept; how many there were (0 if none were changed). */
function restoreInputs(spreadsheet) {
  var properties = PropertiesService.getDocumentProperties();
  var text = properties.getProperty(SAVED_INPUTS);
  if (!text) {
    return 0;
  }
  var saved = JSON.parse(text);
  saved.forEach(function (cell) {
    var range = spreadsheet.getRange(cell.address);
    if (cell.formula) {
      range.setFormula(cell.formula);
    } else {
      range.setValue(cell.value);
    }
  });
  properties.deleteProperty(SAVED_INPUTS);
  SpreadsheetApp.flush();
  return saved.length;
}


// ---------------------------------------------------------------------------
// The results
// ---------------------------------------------------------------------------

function columnLetter(column) {
  var letters = "";
  for (var n = column; n > 0; n = Math.floor((n - 1) / 26)) {
    letters = String.fromCharCode(65 + (n - 1) % 26) + letters;
  }
  return letters;
}

/* The row whose column A begins with Status (0 if there is none): where the macro says how it is getting on. */
function findStatusRow(sheet) {
  var labels = sheet.getRange(1, 1, Math.min(sheet.getLastRow(), 30), 1).getValues();
  for (var n = 0; n < labels.length; n++) {
    if (normalized(labels[n][0]).indexOf("status") === 0) {
      return n + 1;
    }
  }
  return 0;
}

function setStatus(sheet, statusRow, text) {
  if (statusRow) {
    sheet.getRange(statusRow, 2).setValue(text);
  }
}

/*
 * Where the results go: the summary rows (right below the title), the header row, and the first row of runs.  The
 * header says Run and then the name of each input and each output.
 */
function resultsLayout(setup) {
  var header = ["Run"].concat(setup.inputs.map(function (input) { return input.name; }),
                             setup.outputs.map(function (output) { return output.name; }));
  var summaryRow = setup.resultsRow + 1;
  var headerRow = summaryRow + SUMMARY.length;
  return {header: header, width: header.length, summaryRow: summaryRow, headerRow: headerRow, firstRunRow: headerRow + 1};
}

/*
 * The summary formulas.  Each takes the runs of its column as the setup's number of rows starting just below the
 * column's heading (OFFSET(B$72,1,0,100,1) is the 100 cells under B72), so that it follows the heading if rows are
 * inserted or deleted above it, and never reaches past the last run.
 */
function writeSummary(sheet, setup, layout) {
  var formulas = SUMMARY.map(function (row) {
    var cells = [];
    for (var column = 2; column <= layout.width; column++) {
      var runs = "OFFSET(" + columnLetter(column) + "$" + layout.headerRow + ",1,0," + setup.runs + ",1)";
      cells.push("=" + row[1].replace("%", runs));
    }
    return cells;
  });
  sheet.getRange(layout.summaryRow, 2, SUMMARY.length, layout.width - 1).setFormulas(formulas);
}

/*
 * Makes room for the results: the sheet is given rows down to the last run, and columns across to the last output,
 * added at the bottom and the right (this is not left to Google, which grows a sheet by itself when something is written
 * past its edge).
 */
function makeRoom(sheet, setup, layout) {
  var lastRunRow = layout.firstRunRow + setup.runs - 1;
  if (sheet.getMaxRows() < lastRunRow) {
    sheet.insertRowsAfter(sheet.getMaxRows(), lastRunRow - sheet.getMaxRows());
  }
  if (sheet.getMaxColumns() < layout.width) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), layout.width - sheet.getMaxColumns());
  }
}

/* Removes the rows of an earlier run's results: everything below the Results title (the summary, headings, and runs). */
function deleteOldResults(sheet, layout) {
  var rows = sheet.getMaxRows() - layout.summaryRow + 1;
  if (rows > 0) {
    sheet.deleteRows(layout.summaryRow, rows);
  }
}

/* The headings, the summary formulas over the rows of runs, and the number formats, as the setup now calls for. */
function writeResultsFrame(sheet, setup, layout) {
  makeRoom(sheet, setup, layout);
  sheet.getRange(layout.headerRow, 1, 1, layout.width).setValues([layout.header]).setFontWeight("bold");
  var labels = SUMMARY.map(function (row) { return [row[0]]; });
  sheet.getRange(layout.summaryRow, 1, SUMMARY.length, 1).setValues(labels);
  writeSummary(sheet, setup, layout);
  var cells = setup.inputs.concat(setup.outputs);
  cells.forEach(function (cell, n) {
    var format = cell.range.getNumberFormat();
    sheet.getRange(layout.summaryRow, n + 2, SUMMARY.length, 1).setNumberFormat(format);
    sheet.getRange(layout.firstRunRow, n + 2, setup.runs, 1).setNumberFormat(format);
  });
}

/* How many runs the results already hold, if their header is the one the setup now gives (else an error). */
function runsDone(sheet, setup, layout) {
  var existing = sheet.getRange(layout.headerRow, 1, 1, layout.width).getValues()[0];
  var same = existing.every(function (text, n) { return String(text) === String(layout.header[n]); });
  if (!same) {
    fail("The inputs or outputs are not the ones of the runs already made. Choose Run Monte Carlo to start again.");
  }
  var numbers = sheet.getRange(layout.firstRunRow, 1, setup.runs, 1).getValues();
  var done = 0;
  while (done < numbers.length && isNumber(numbers[done][0])) {
    done++;
  }
  return done;
}


// ---------------------------------------------------------------------------
// The run
// ---------------------------------------------------------------------------

function execute(continuing) {
  var started = Date.now();
  var spreadsheet = SpreadsheetApp.getActive();
  var sheet = spreadsheet.getSheetByName(SHEET_NAME);
  var statusRow = sheet ? findStatusRow(sheet) : 0;
  try {
    removeContinuation();               // (a timer from an earlier stop; another is set if this one stops too)
    if (!sheet) {
      fail('There is no tab called "' + SHEET_NAME + '".');
    }
    restoreInputs(spreadsheet);         // (if an earlier run was cut off, the inputs are as it left them)
    var setup = readSetup(spreadsheet, sheet);
    var factor = correlationFactor(setup);
    var layout = resultsLayout(setup);
    if (setup.runs * layout.width > MOST_CELLS_OF_RESULTS) {
      fail("That many runs with that many columns is too much for one sheet: use fewer runs.");
    }
    var properties = PropertiesService.getDocumentProperties();
    var done = 0;
    var seed;
    if (continuing) {
      seed = Number(properties.getProperty(SAVED_SEED));
      if (!properties.getProperty(SAVED_SEED)) {
        fail("There is no run to continue. Choose Run Monte Carlo.");
      }
      done = runsDone(sheet, setup, layout);
    } else {
      seed = setup.seed !== null ? setup.seed : Math.floor(Math.random() * 1000000000);
      properties.setProperty(SAVED_SEED, String(seed));
      deleteOldResults(sheet, layout);
    }
    writeResultsFrame(sheet, setup, layout);

    saveInputs(setup.inputs);
    var stopped = false;
    var pending = [];
    for (var run = done + 1; run <= setup.runs && !stopped; run++) {
      var values = drawInputs(setup.inputs, factor, randomForRun(seed, run));
      setup.inputs.forEach(function (input, n) { input.range.setValue(values[n]); });
      SpreadsheetApp.flush();
      var results = setup.outputs.map(function (output) { return output.range.getValue(); });
      pending.push([run].concat(values, results));
      stopped = (Date.now() - started) / 1000 > MOST_SECONDS;
      if (pending.length >= RUNS_PER_WRITE || run === setup.runs || stopped) {
        sheet.getRange(layout.firstRunRow + pending[0][0] - 1, 1, pending.length, layout.width).setValues(pending);
        pending = [];
        setStatus(sheet, statusRow, "Running: " + run + " of " + setup.runs + " runs");
      }
    }
    restoreInputs(spreadsheet);
    writeSummary(sheet, setup, layout);         // (again, last, so that they are right whatever happened to the rows meanwhile)
    var last = run - 1;                 // (the last run made: everything collected has been written)
    if (stopped && last < setup.runs) {
      var goingOn = "it goes on by itself in a minute (or choose Sensitivity > Continue a run that stopped)";
      try {
        scheduleContinuation();
      } catch (error) {
        goingOn = "choose Sensitivity > Continue a run that stopped (it could not set a timer: " + error.message + ")";
      }
      setStatus(sheet, statusRow, "Stopped after " + last + " of " + setup.runs + " runs, to stay within Google's time limit: " + goingOn + ".");
    } else {
      setStatus(sheet, statusRow, "Done: " + setup.runs + " runs, seed " + seed + ".");
    }
  } catch (error) {
    try {
      restoreInputs(spreadsheet);
    } catch (ignored) {
      // (the message below matters more)
    }
    if (sheet) {
      setStatus(sheet, statusRow, "Stopped: " + error.message);
    }
    tell(error.message);
  }
}
