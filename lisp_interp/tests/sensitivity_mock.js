/*
 * A stand-in for the parts of Google's SpreadsheetApp that apps_script/sensitivity.gs uses, and the scenarios that
 * test the macro with it.  test_sensitivity.py puts the macro, then this file, after a line that says
 * `var FIXTURE = {...}` (or null), and runs them with macOS's JavaScript (osascript -l JavaScript); run() gives back
 * what happened as JSON for the Python test to check.
 *
 * The stand-in's cells have a value, or a formula that is a JavaScript function standing in for the spreadsheet's
 * own (registered under the formula's text), so that an output cell can depend on the input cells.
 */

var alerts = [];
var documentProperties = {};
var workbook = null;
var formulaFunctions = {};              // the text of a formula -> the function that works out its value

var SpreadsheetApp = {
  getActive: function () { return workbook; },
  flush: function () {},
  getUi: function () {
    return {alert: function (message) { alerts.push(message); }};
  }
};

var triggers = [];                      // timers: the name of the function each will run
var ScriptApp = {
  newTrigger: function (name) {
    return {timeBased: function () { return {after: function (milliseconds) { return {create: function () { triggers.push({name: name, after: milliseconds}); }}; }}; }};
  },
  getProjectTriggers: function () {
    return triggers.map(function (trigger) { return {getHandlerFunction: function () { return trigger.name; }, trigger: trigger}; });
  },
  deleteTrigger: function (handle) { triggers = triggers.filter(function (trigger) { return trigger !== handle.trigger; }); }
};

var PropertiesService = {
  getDocumentProperties: function () {
    return {
      getProperty: function (key) { return key in documentProperties ? documentProperties[key] : null; },
      setProperty: function (key, value) { documentProperties[key] = value; },
      deleteProperty: function (key) { delete documentProperties[key]; }
    };
  }
};

function lettersOf(column) {
  return columnLetter(column);
}

function columnOfLetters(letters) {
  var column = 0;
  for (var n = 0; n < letters.length; n++) {
    column = column * 26 + letters.charCodeAt(n) - 64;
  }
  return column;
}

function MockSheet(book, name) {
  this.book = book;
  this.name = name;
  this.cells = {};
}

MockSheet.prototype.cell = function (row, column) {
  var key = row + "," + column;
  if (!this.cells[key]) {
    this.cells[key] = {value: "", formula: "", format: "General"};
  }
  return this.cells[key];
};
MockSheet.prototype.getName = function () { return this.name; };
MockSheet.prototype.getMaxRows = function () { return 2000; };
MockSheet.prototype.getMaxColumns = function () { return 26; };
MockSheet.prototype.getLastRow = function () {
  var last = 1;
  for (var key in this.cells) {
    var cell = this.cells[key];
    if (cell.value !== "" || cell.formula !== "") {
      last = Math.max(last, Number(key.split(",")[0]));
    }
  }
  return last;
};
MockSheet.prototype.getRange = function (row, column, rows, columns) {
  return new MockRange(this, row, column, rows || 1, columns || 1);
};

function MockRange(sheet, row, column, rows, columns) {
  this.sheet = sheet;
  this.row = row;
  this.column = column;
  this.rows = rows;
  this.columns = columns;
}

MockRange.prototype.eachCell = function (action) {
  for (var r = 0; r < this.rows; r++) {
    for (var c = 0; c < this.columns; c++) {
      action(this.sheet.cell(this.row + r, this.column + c), r, c);
    }
  }
};
MockRange.prototype.valueOfCell = function (cell) {
  return cell.formula && formulaFunctions[cell.formula] ? formulaFunctions[cell.formula](this.sheet.book) : cell.value;
};
MockRange.prototype.getValue = function () { return this.valueOfCell(this.sheet.cell(this.row, this.column)); };
MockRange.prototype.getValues = function () {
  var self = this, values = [];
  this.eachCell(function (cell, r) {
    if (!values[r]) { values[r] = []; }
    values[r].push(self.valueOfCell(cell));
  });
  return values;
};
MockRange.prototype.setValue = function (value) {
  this.eachCell(function (cell) { cell.value = value; cell.formula = ""; });
  return this;
};
MockRange.prototype.setValues = function (values) {
  this.eachCell(function (cell, r, c) { cell.value = values[r][c]; cell.formula = ""; });
  return this;
};
MockRange.prototype.setFormula = function (formula) {
  this.eachCell(function (cell) { cell.formula = formula; cell.value = ""; });
  return this;
};
MockRange.prototype.setFormulas = function (formulas) {
  this.eachCell(function (cell, r, c) { cell.formula = formulas[r][c]; cell.value = ""; });
  return this;
};
MockRange.prototype.getFormula = function () { return this.sheet.cell(this.row, this.column).formula; };
MockRange.prototype.setFontWeight = function () { return this; };
MockRange.prototype.setNumberFormat = function (format) {
  this.eachCell(function (cell) { cell.format = format; });
  return this;
};
MockRange.prototype.getNumberFormat = function () { return this.sheet.cell(this.row, this.column).format; };
MockRange.prototype.clear = function () {
  var self = this;
  this.eachCell(function (cell, r, c) { delete self.sheet.cells[(self.row + r) + "," + (self.column + c)]; });
  return this;
};
MockRange.prototype.getNumRows = function () { return this.rows; };
MockRange.prototype.getNumColumns = function () { return this.columns; };
MockRange.prototype.getSheet = function () { return this.sheet; };
MockRange.prototype.getA1Notation = function () { return lettersOf(this.column) + this.row; };

function MockWorkbook() {
  this.sheets = {};
  this.names = {};
}
MockWorkbook.prototype.addSheet = function (name, rows) {
  var sheet = new MockSheet(this, name);
  this.sheets[name] = sheet;
  (rows || []).forEach(function (row, r) {
    row.forEach(function (value, c) {
      if (value !== null) { sheet.cell(r + 1, c + 1).value = value; }
    });
  });
  return sheet;
};
MockWorkbook.prototype.getSheetByName = function (name) { return this.sheets[name] || null; };
MockWorkbook.prototype.getRangeByName = function (name) {
  var where = this.names[name];
  return where ? this.getRange("'" + where[0] + "'!" + where[1]) : null;
};
MockWorkbook.prototype.getRange = function (address) {
  var match = /^(?:'((?:[^']|'')+)'!|([^'!]+)!)?([A-Z]+)([0-9]+)$/.exec(address);
  if (!match) { throw new Error("no such range: " + address); }
  var sheet = this.sheets[(match[1] || match[2] || "").replace(/''/g, "'")];
  if (!sheet) { throw new Error("no such sheet: " + address); }
  return sheet.getRange(Number(match[4]), columnOfLetters(match[3]), 1, 1);
};

/* the value of a name, for the functions that stand in for formulas */
function modelValue(name) {
  return workbook.getRangeByName(name).getValue();
}

/* A formula cell: its text, and the function that works out what it says. */
function putFormula(range, text, work) {
  formulaFunctions[text] = work;
  range.setFormula(text);
}

function resetWorld() {
  alerts = [];
  documentProperties = {};
  triggers = [];
  formulaFunctions = {};
  MOST_SECONDS = 240;
}


// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

/* The numbers that test the arithmetic. */
function mathScenario() {
  var result = {};
  result.cdf = [-3, -1.96, -1, 0, 0.5, 1, 1.96, 3].map(function (z) { return [z, normalCdf(z)]; });
  result.inverse = [0.001, 0.01, 0.025, 0.1, 0.3, 0.5, 0.7, 0.9, 0.975, 0.99, 0.999].map(function (p) { return [p, normalInverseCdf(p)]; });
  var inputs = {
    uniform: {distribution: "uniform", low: 2, average: 5, high: 10},
    triangular: {distribution: "triangular", low: 2, average: 3, high: 10},
    normal: {distribution: "normal", low: 2, average: 5, high: 8},
    skewed: {distribution: "normal", low: 0, average: 1, high: 10},
    flat: {distribution: "triangular", low: 4, average: 4, high: 4}
  };
  result.sampled = {};
  Object.keys(inputs).forEach(function (kind) {
    var input = inputs[kind], random = makeRandom(7), draws = [];
    for (var n = 0; n < 40000; n++) {
      draws.push(valueForProbability(input, Math.min(Math.max(random(), 1e-12), 1 - 1e-12)));
    }
    var mean = draws.reduce(function (a, b) { return a + b; }, 0) / draws.length;
    var variance = draws.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / draws.length;
    result.sampled[kind] = {mean: mean, deviation: Math.sqrt(variance), min: Math.min.apply(null, draws), max: Math.max.apply(null, draws)};
  });
  result.ends = {};
  Object.keys(inputs).forEach(function (kind) {
    result.ends[kind] = [0, 0.5, 1].map(function (p) { return valueForProbability(inputs[kind], p); });
  });
  result.randomNormals = (function () {
    var random = makeRandom(11), draws = [];
    for (var n = 0; n < 40000; n++) { draws.push(randomNormal(random)); }
    var mean = draws.reduce(function (a, b) { return a + b; }, 0) / draws.length;
    var variance = draws.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / draws.length;
    return {mean: mean, deviation: Math.sqrt(variance)};
  })();
  result.sameSeedSameNumbers = (function () {
    var first = randomForRun(5, 3), second = randomForRun(5, 3), other = randomForRun(5, 4);
    return [first() === second(), first() === second(), first() === other()];
  })();
  return result;
}

/* Correlated draws: the correlation of what comes out, and the matrices that can't be. */
function correlationScenario() {
  var result = {};
  var inputs = [{distribution: "normal", low: -2, average: 0, high: 2}, {distribution: "uniform", low: 0, average: 1, high: 1},
                {distribution: "triangular", low: 0, average: 1, high: 4}];
  [0.8, -0.6, 0].forEach(function (rho) {
    var factor = choleskyFactor([[1, rho, 0], [rho, 1, 0], [0, 0, 1]]);
    var random = makeRandom(99), rows = [];
    for (var n = 0; n < 6000; n++) { rows.push(drawInputs(inputs, factor, random)); }
    result["rho" + rho] = {firstSecond: pearson(rows, 0, 1), firstThird: pearson(rows, 0, 2)};
  });
  result.impossible = choleskyFactor([[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]]) === null;
  result.perfect = choleskyFactor([[1, 1], [1, 1]]);
  result.identity = choleskyFactor([[1, 0], [0, 1]]);
  return result;
}

function pearson(rows, first, second) {
  var n = rows.length, sumA = 0, sumB = 0, sumAA = 0, sumBB = 0, sumAB = 0;
  rows.forEach(function (row) {
    sumA += row[first]; sumB += row[second]; sumAA += row[first] * row[first]; sumBB += row[second] * row[second]; sumAB += row[first] * row[second];
  });
  return (sumAB - sumA * sumB / n) / Math.sqrt((sumAA - sumA * sumA / n) * (sumBB - sumB * sumB / n));
}

/* A small model on one tab and the setup on the Sensitivity tab, as the macro expects them. */
function smallWorld(runs, seed) {
  resetWorld();
  workbook = new MockWorkbook();
  var model = workbook.addSheet("Model", [["rate", 0.05], ["growth"], ["total"], ["other"]]);
  workbook.names = {rate: ["Model", "B1"], growth: ["Model", "B2"], total: ["Model", "B3"], other: ["Model", "B4"]};
  putFormula(model.getRange(2, 2), "=rate/2", function () { return modelValue("rate") / 2; });
  putFormula(model.getRange(3, 2), "=1000*(1+rate)*(1+growth)", function () { return 1000 * (1 + modelValue("rate")) * (1 + modelValue("growth")); });
  putFormula(model.getRange(4, 2), "=rate+growth", function () { return modelValue("rate") + modelValue("growth"); });
  workbook.addSheet("Sensitivity", [
    ["Title"],
    ["Number of runs", runs],
    ["Random seed (empty for a different one each time)", seed],
    ["Status"],
    [],
    ["Inputs"],
    ["Input", "Distribution", "Low", "Average", "High", "What it is"],
    ["rate", "uniform", 0.03, 0.05, 0.07],
    ["Model!B2", "Triangular", 0.01, 0.02, 0.04],
    [],
    ["Correlations"],
    ["Input", "Input", "Correlation"],
    ["rate", "Model!B2", 0.8],
    [],
    ["Outputs"],
    ["Output", "What it is"],
    ["total"],
    ["other"],
    [],
    ["Results"]
  ]);
  return workbook.sheets.Sensitivity;
}

function rowsOfRuns(sheet, count) {
  var rows = [];
  for (var r = 0; r < count; r++) { rows.push(sheet.getRange(31 + r, 1, 1, 5).getValues()[0]); }
  return rows;
}

function runScenario() {
  var result = {};
  var sheet = smallWorld(400, 123);
  runMonteCarlo();
  result.alerts = alerts.slice();
  result.status = sheet.getRange(4, 2).getValue();
  result.header = sheet.getRange(30, 1, 1, 5).getValues()[0];
  result.summaryLabels = sheet.getRange(21, 1, 9, 1).getValues().map(function (row) { return row[0]; });
  result.summaryFormulas = [sheet.getRange(21, 2).getFormula(), sheet.getRange(24, 4).getFormula(), sheet.getRange(29, 5).getFormula()];
  result.runs = rowsOfRuns(sheet, 400);
  result.lastRunNumber = sheet.getRange(430, 1).getValue();
  result.afterTheLastRun = sheet.getRange(431, 1).getValue();
  result.rateCell = [workbook.getRange("Model!B1").getValue(), workbook.getRange("Model!B1").getFormula()];
  result.growthCell = [workbook.getRange("Model!B2").getFormula(), workbook.getRange("Model!B2").getValue()];
  result.savedInputsLeft = documentProperties[SAVED_INPUTS] || null;
  result.format = sheet.getRange(31, 2).getNumberFormat();

  runMonteCarlo();                      // the same seed again
  result.sameAgain = JSON.stringify(rowsOfRuns(sheet, 400)) === JSON.stringify(result.runs);

  // a run that stops for time, and then continues
  smallWorld(400, 123);
  MOST_SECONDS = -1;
  runMonteCarlo();
  var stoppedSheet = workbook.sheets.Sensitivity;
  result.stoppedStatus = stoppedSheet.getRange(4, 2).getValue();
  result.stoppedAfter = stoppedSheet.getRange(32, 1).getValue();
  result.timerSet = triggers.slice();
  result.inputsBackWhenStopped = [workbook.getRange("Model!B1").getValue(), workbook.getRange("Model!B2").getFormula()];
  MOST_SECONDS = 240;
  continueMonteCarlo();
  result.continuedStatus = stoppedSheet.getRange(4, 2).getValue();
  result.continuedSame = JSON.stringify(rowsOfRuns(stoppedSheet, 400)) === JSON.stringify(result.runs);
  result.continuedAlerts = alerts.slice();
  result.timersAfterwards = triggers.slice();

  // mistakes in the setup are explained, and leave the model as it was
  var mistakes = {};
  var tryChange = function (name, change) {
    var s = smallWorld(10, 1);
    change(s);
    runMonteCarlo();
    mistakes[name] = {alerts: alerts.slice(), status: s.getRange(4, 2).getValue(),
                      rate: workbook.getRange("Model!B1").getValue(), growth: workbook.getRange("Model!B2").getFormula()};
  };
  tryChange("distribution", function (s) { s.getRange(8, 2).setValue("bell"); });
  tryChange("order", function (s) { s.getRange(8, 3).setValue(0.09); });
  tryChange("unknown", function (s) { s.getRange(8, 1).setValue("nothing_here"); });
  tryChange("noruns", function (s) { s.getRange(2, 2).setValue(0); });
  tryChange("notinput", function (s) { s.getRange(13, 2).setValue("total"); });
  tryChange("itself", function (s) { s.getRange(13, 2).setValue("rate"); });
  tryChange("tooBig", function (s) { s.getRange(13, 3).setValue(1.5); });
  tryChange("noOutputs", function (s) { s.getRange(17, 1).setValue(""); s.getRange(18, 1).setValue(""); });
  tryChange("average", function (s) { s.getRange(9, 4).setValue(0.5); });
  result.mistakes = mistakes;

  // putting the inputs back by hand, after a run that was cut off
  var cut = smallWorld(10, 1);
  var cutInputs = [{range: workbook.getRange("Model!B1")}, {range: workbook.getRange("Model!B2")}];
  saveInputs(cutInputs);
  cutInputs[0].range.setValue(0.9);
  cutInputs[1].range.setValue(0.8);
  alerts = [];
  putInputsBack();
  result.putBack = {alerts: alerts.slice(), rate: workbook.getRange("Model!B1").getValue(), growth: workbook.getRange("Model!B2").getFormula()};
  alerts = [];
  putInputsBack();
  result.putBackNothing = alerts.slice();

  // continuing when there was no run
  smallWorld(10, 1);
  continueMonteCarlo();
  result.noRunToContinue = alerts.slice();
  return result;
}

/* The tab the three-statement model makes, run against a workbook that has its names (the model itself is not here:
 * each output is the sum of the inputs). */
function fixtureScenario() {
  if (!FIXTURE) { return null; }
  resetWorld();
  workbook = new MockWorkbook();
  var model = workbook.addSheet("Model", []);
  var row = 1;
  var names = FIXTURE.names;
  Object.keys(names).forEach(function (name) {
    workbook.names[name] = ["Model", "A" + row];
    model.cell(row, 1).value = names[name];
    row++;
  });
  var tab = workbook.addSheet("Sensitivity", FIXTURE.sensitivity);
  var inputs = FIXTURE.inputs, outputs = FIXTURE.outputs;
  outputs.forEach(function (name) {
    var range = workbook.getRangeByName(name);
    putFormula(range, "=" + name, function () {
      return inputs.reduce(function (sum, input, n) { return sum + (n + 1) * modelValue(input); }, 0);
    });
  });
  var before = {};
  inputs.concat(outputs).forEach(function (name) { before[name] = workbook.getRangeByName(name).getValue(); });
  runMonteCarlo();
  var resultsRow = FIXTURE.sensitivity.findIndex(function (row) { return row[0] === "Results"; }) + 1;
  var headerRow = resultsRow + 10;
  var width = 1 + inputs.length + outputs.length;
  return {
    alerts: alerts.slice(), status: tab.getRange(FIXTURE.statusRow, 2).getValue(), before: before,
    header: tab.getRange(headerRow, 1, 1, width).getValues()[0],
    runs: tab.getRange(headerRow + 1, 1, FIXTURE.runs, width).getValues(),
    inputRanges: inputs.map(function (name) { var r = workbook.getRangeByName(name); return [r.getValue(), r.getFormula()]; })
  };
}

function run() {
  return JSON.stringify({math: mathScenario(), correlation: correlationScenario(), run: runScenario(), fixture: fixtureScenario()});
}
