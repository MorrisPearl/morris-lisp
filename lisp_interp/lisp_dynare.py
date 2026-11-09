"""Dynare, for the Lisp interpreter: macroeconomic models solved and estimated by Dynare (https://www.dynare.org), run under GNU Octave.

  (dynare-run model-file [:parameters p :macros m :data table :directory d :echo #t :timeout seconds])

A Dynare model is a .mod file: the model's variables, parameters and equations, then what to do with it (stoch_simul: how the economy
responds to each kind of surprise; estimation: the parameters estimated from data). dynare-run copies the model's folder into a folder
of its own, runs Dynare there under Octave, and returns what Dynare found as a hash table (see dynare_run). The models that come with the
interpreter are in the dynare/ folder beside this file; lib/macro_models.lsp has the functions for using them.

Dynare needs GNU Octave, with Octave Forge's statistics package (pkg install -forge io datatypes statistics), and Dynare's Octave build
(Homebrew's: brew install dynare). The Dynare in /Applications is MATLAB's, which Octave can't use. The environment variables OCTAVE
and DYNARE_PATH say where they are, if not in the usual places.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

from lisp_core import LispError, LispHashTable, LispString, LispVector, Pair, keyword_options, pairs_to_list
from lisp_tables import make_table_value
import lisp_csv

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_FOLDER = os.path.join(HERE, "dynare")        # the models that come with the interpreter, and export_results.m
EXPORT_SCRIPT = os.path.join(MODELS_FOLDER, "export_results.m")

# The line of a model file where dynare-run puts the parameter values its caller gives, so that they replace the calibration's.
PARAMETERS_MARKER = "// Parameters given by the caller go here."

OCTAVE_PLACES = ["/opt/homebrew/bin/octave-cli", "/usr/local/bin/octave-cli", "/usr/bin/octave-cli"]
DYNARE_PLACES = ["/opt/homebrew/opt/dynare/lib/dynare/matlab", "/usr/local/opt/dynare/lib/dynare/matlab",
                 "/usr/lib/dynare/matlab", "/usr/share/dynare/matlab"]

DEFAULT_TIMEOUT = 3600      # seconds; an estimation with many draws takes some minutes


def find_octave(who):
    """The path of octave-cli: $OCTAVE, or the one on the PATH, or one in a usual place."""
    candidates = [os.environ.get("OCTAVE"), shutil.which("octave-cli")] + OCTAVE_PLACES
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise LispError("%s: can't find GNU Octave's octave-cli (brew install octave), or set OCTAVE to its path" % who)


def find_dynare(who):
    """The folder of Dynare's Octave code (the one with dynare.m): $DYNARE_PATH, or one in a usual place."""
    candidates = [os.environ.get("DYNARE_PATH")] + DYNARE_PLACES
    for folder in candidates:
        if folder and os.path.isfile(os.path.join(folder, "dynare.m")):
            return folder
    raise LispError("%s: can't find Dynare for Octave (brew install dynare), or set DYNARE_PATH to the folder with its dynare.m" % who)


def model_path(model_file, who):
    """The model file's path: as given, or else the file of that name in the interpreter's dynare/ folder."""
    path = os.path.expanduser(str(model_file))
    if os.path.isfile(path):
        return os.path.abspath(path)
    bundled = os.path.join(MODELS_FOLDER, path)
    if os.path.isfile(bundled):
        return bundled
    raise LispError("%s: there is no model file %s, here or in %s" % (who, model_file, MODELS_FOLDER))


def name_value_pairs(value, who, what):
    """A Lisp association list ((name . value) ...) or hash table, as a Python list of (name text, value) pairs."""
    if value is None or value == []:
        return []
    if isinstance(value, LispHashTable):
        items = list(value.table.items())
    else:
        items = []
        for entry in pairs_to_list(value):
            if not isinstance(entry, Pair):
                raise LispError("%s: %s is a list of (name . value) pairs; %s isn't one" % (who, what, entry))
            items.append((entry.car, entry.cdr))
    return [(str(name).lstrip(":"), number) for name, number in items]     # a name can be a symbol, a keyword or text


def number_text(value, who, name):
    """A parameter's value as Dynare reads it: a number, written in full."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LispError("%s: the value of %s is a number, not %s" % (who, name, value))
    return repr(float(value))


def prepare_folder(model, folder, parameters, data, who):
    """Copies the model's folder (its .mod, .inc and .m files) and export_results.m into folder, puts the parameters at the
    marker line of the model file or the first file it includes that has it, and writes data, if any, to data.csv."""
    source = os.path.dirname(model)
    for name in os.listdir(source):
        if os.path.splitext(name)[1] in (".mod", ".inc", ".m") and os.path.isfile(os.path.join(source, name)):
            shutil.copy(os.path.join(source, name), os.path.join(folder, name))
    shutil.copy(EXPORT_SCRIPT, os.path.join(folder, "export_results.m"))

    if parameters:
        lines = "".join("%s = %s;\n" % (name, number_text(value, who, name)) for name, value in parameters)
        with open(model) as f:
            included = re.findall(r'@#include\s+"([^"]+)"', f.read())
        for name in [os.path.basename(model)] + included:
            path = os.path.join(folder, name)
            with open(path) as f:
                text = f.read()
            if PARAMETERS_MARKER in text:
                with open(path, "w") as f:
                    f.write(text.replace(PARAMETERS_MARKER, PARAMETERS_MARKER + "\n" + lines, 1))
                break
        else:
            raise LispError("%s: to be given :parameters, the model needs the line %s where they go" % (who, PARAMETERS_MARKER))

    if data is not None:
        lisp_csv.write_columns_csv_fn(LispString(os.path.join(folder, "data.csv")), data)


def octave_script(dynare_folder, folder, model_name, macros):
    """What Octave is to do: run Dynare on the model, then export_results; on an error, say what it was and stop."""
    options = "".join(" -D%s=%s" % (name, value) for name, value in macros)
    return ("warning('off', 'all'); addpath('%s'); cd('%s');\n"
            "try\n"
            "  dynare %s noclearall nograph%s\n"
            "  export_results\n"
            "catch err\n"
            "  disp(['error: ' err.message]); exit(1);\n"
            "end\n") % (dynare_folder, folder, model_name, options)


def run_octave(octave, script, folder, echo, timeout, who):
    """Runs Octave on the script in folder, writing what it prints to dynare.log (and to echo, if given, as it comes). Returns the text."""
    log_path = os.path.join(folder, "dynare.log")
    lines = []
    with open(log_path, "w") as log:
        with subprocess.Popen([octave, "--no-gui", "--quiet", "--eval", script], cwd=folder,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
            try:
                for line in process.stdout:
                    lines.append(line)
                    log.write(line)
                    if echo is not None:
                        echo(line)
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                raise LispError("%s: Dynare took more than %s seconds; what it printed is in %s" % (who, timeout, log_path))
    return "".join(lines)


def first_error(log_text):
    """The first error Octave or Dynare reported, or the last lines it printed if it didn't say."""
    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("error:") or line.startswith("ERROR"):
            return "\n".join(lines[i:i + 3])
    return "\n".join(lines[-10:])


# ---------------------------------------------------------------------------
# Reading results.json
# ---------------------------------------------------------------------------

def as_list(value):
    """A value from Octave's jsonencode as a Python list: a one-element array comes out as just the element."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def split_irf_name(key, variables, shocks):
    """Dynare names a response "gdp_oil_price_shock" (gdp after oil_price_shock); names can have underscores in them, so this finds the shock it ends with."""
    for shock in sorted(shocks, key=len, reverse=True):
        if key.endswith("_" + shock) and key[:-len(shock) - 1] in variables:
            return key[:-len(shock) - 1], shock
    return None, None


def irf_tables(irfs, variables, shocks):
    """A hash table from each shock's name to a table of the responses to it: a quarter column (1 is the quarter of the surprise), then a
    column for each variable, in the model's order. irfs is a list of (suffix, Dynare's dict of responses): "" for the responses
    themselves, " low" and " high" for the bottom and top of their bands. Dynare leaves out a response that is zero all the way."""
    by_shock = {}
    periods = 0
    for suffix, responses in irfs:
        for key, values in responses.items():
            variable, shock = split_irf_name(key, variables, shocks)
            if shock is not None:
                by_shock.setdefault(shock, {})[variable + suffix] = as_list(values)
                periods = max(periods, len(as_list(values)))
    result = LispHashTable()
    for shock in shocks:
        if shock not in by_shock:
            continue
        columns = [("quarter", LispVector(list(range(1, periods + 1))))]
        for variable in variables:
            if any(variable + suffix in by_shock[shock] for suffix, _ in irfs):
                for suffix, _ in irfs:
                    columns.append((variable + suffix, LispVector(by_shock[shock].get(variable + suffix, [0.0] * periods))))
        result.table[LispString(shock)] = make_table_value(columns)
    return result


def estimates_table(results):
    """A row for each estimated parameter, shock size and measurement error: its name, its prior's mean and standard deviation, the
    posterior mode, and the posterior mean with the bottom and top of its 90% interval (NaN for those the run didn't make)."""
    names = as_list(results.get("prior_names"))
    groups = [("parameters", ""), ("shocks_std", "stderr "), ("measurement_errors_std", "stderr ")]

    def lookup(kind, name):
        part = results.get(kind)
        if not isinstance(part, dict):
            return float("nan")
        for group, prefix in groups:
            if name.startswith(prefix) and isinstance(part.get(group), dict) and name[len(prefix):] in part[group]:
                return part[group][name[len(prefix):]]
        return float("nan")

    columns = [("name", LispVector([LispString(n) for n in names])),
               ("prior mean", LispVector(as_list(results.get("prior_mean")))),
               ("prior stdev", LispVector(as_list(results.get("prior_stdev"))))]
    for heading, kind in (("mode", "posterior_mode"), ("mean", "posterior_mean"),
                          ("low", "posterior_hpdinf"), ("high", "posterior_hpdsup")):
        columns.append((heading, LispVector([lookup(kind, name) for name in names])))
    return make_table_value(columns)


def variance_table(results, shocks):
    """How much of each variable's ups and downs comes from each kind of shock, in percent: a row a variable, a column a shock."""
    rows = results["variance_decomposition"]
    rows = [as_list(row) for row in (rows if isinstance(rows[0], list) else [rows])]
    names = as_list(results.get("variance_decomposition_names"))
    columns = [("variable", LispVector([LispString(n) for n in names]))]
    for j, shock in enumerate(shocks):
        columns.append((shock, LispVector([row[j] for row in rows])))
    return make_table_value(columns)


def draws_table(results):
    """The draws of the Markov chains as a table: the chain each is from (1, 2, ...), its number within the chain, its log posterior
    density (how well it fits the data and the priors together), then a column for each estimated parameter."""
    names = as_list(results.get("prior_names"))
    rows = results["draws"]
    rows = rows if isinstance(rows[0], list) else [rows]
    per_chain = int(results["draws_per_chain"])
    columns = [("chain", LispVector([1 + k // per_chain for k in range(len(rows))])),
               ("draw", LispVector([1 + k % per_chain for k in range(len(rows))])),
               ("log posterior", LispVector(as_list(results["draw_log_posterior"])))]
    for j, name in enumerate(names):
        columns.append((name, LispVector([row[j] for row in rows])))
    return make_table_value(columns)


def results_hash_table(results, folder, log_text):
    """What dynare-run returns, from the dict export_results.m wrote."""
    variables = as_list(results.get("endo_names"))
    shocks = as_list(results.get("shock_names"))
    result = LispHashTable()

    def put(key, value):
        result.table[LispString(key)] = value

    put("folder", LispString(folder))
    put("log", LispString(log_text))
    put("parameters", make_table_value([
        ("name", LispVector([LispString(n) for n in as_list(results.get("param_names"))])),
        ("value", LispVector(as_list(results.get("param_values"))))]))
    put("shocks", make_table_value([
        ("shock", LispVector([LispString(n) for n in shocks])),
        ("stderr", LispVector(as_list(results.get("shock_stderr"))))]))
    if "irfs" in results:
        put("responses", irf_tables([("", results["irfs"])], variables, shocks))
    if "posterior_irf_mean" in results:
        put("responses", irf_tables([("", results["posterior_irf_mean"]), (" low", results["posterior_irf_low"]),
                                     (" high", results["posterior_irf_high"])], variables, shocks))
    if "variance_decomposition" in results:
        put("variance-decomposition", variance_table(results, shocks))
    if "prior_names" in results:
        put("estimates", estimates_table(results))
    if "draws" in results:
        put("draws", draws_table(results))
    if isinstance(results.get("marginal_density"), dict):
        put("log-marginal-density", results["marginal_density"].get("LaplaceApproximation", float("nan")))
    return result


def make_dynare_builtins(out):
    """dynare-run, writing what Dynare prints, when it's asked to (:echo #t), where display's output goes."""

    def dynare_run(model_file, *options):
        """(dynare-run model-file [:parameters p :macros m :data table :directory d :echo #t :timeout seconds]) -- runs Dynare on a
        model under Octave and returns what it found, as a hash table:

          "responses"               a hash table from each shock's name to a table of how the variables respond to one typical
                                    surprise of that kind, quarter by quarter (quarter 1 is the quarter of the surprise); after an
                                    estimation with bayesian_irf, the posterior mean, with "<variable> low" and "<variable> high"
                                    columns for its 90% band
          "estimates"               after an estimation: each estimated parameter's prior mean and stdev, posterior mode, posterior
                                    mean and 90% interval (low, high)
          "draws"                   after an estimation: the draws the posterior mean and interval are made from, a row each (see
                                    the macro models manual, "What the estimation produces")
          "log-marginal-density"    after an estimation: how well the model fits the data (higher is better), for comparing models
          "variance-decomposition"  after stoch_simul: the percent of each variable's variance that comes from each shock
          "parameters"              every parameter's value as Dynare last had it (after an estimation, the posterior mode or mean)
          "shocks"                  each shock's typical size (its standard deviation)
          "folder", "log"           the folder it ran in, and everything Octave printed

        model-file is a .mod file, or the name of one in the interpreter's dynare/ folder. The files of the model's folder are copied
        into a new folder (or :directory) and run there. :parameters, an association list ((theta . 0.8) ...) or a hash table, sets
        parameters after the model's calibration, at its "// Parameters given by the caller go here." line. :macros sets Dynare
        macro-variables (-Dname=value), such as an estimation's number of draws. :data, a table, is written to data.csv for an
        estimation to read. :echo #t shows Octave's output as it comes; :timeout is in seconds (an hour, unless it says)."""
        who = "dynare-run"
        options = keyword_options(options, ["parameters", "macros", "data", "directory", "echo", "timeout"], who)
        model = model_path(model_file, who)
        octave = find_octave(who)
        dynare_folder = find_dynare(who)
        model_name = os.path.splitext(os.path.basename(model))[0]

        if options.get("directory") is not None:
            folder = os.path.abspath(os.path.expanduser(str(options["directory"])))
            os.makedirs(folder, exist_ok=True)
        else:
            folder = tempfile.mkdtemp(prefix="dynare-%s-" % model_name)

        parameters = name_value_pairs(options.get("parameters"), who, ":parameters")
        macros = name_value_pairs(options.get("macros"), who, ":macros")
        prepare_folder(model, folder, parameters, options.get("data"), who)

        results_path = os.path.join(folder, "results.json")
        if os.path.exists(results_path):
            os.remove(results_path)
        echo = out.write if options.get("echo") not in (None, False, []) else None
        log_text = run_octave(octave, octave_script(dynare_folder, folder, model_name, macros), folder, echo,
                              options.get("timeout", DEFAULT_TIMEOUT), who)

        # Octave's exit status says nothing here: after an estimation it crashes on its way out, when Dynare is done. export_results.m,
        # the last step, writes results.json only if every step before it worked.
        if not os.path.exists(results_path):
            raise LispError("%s: Dynare stopped: %s\n(everything it printed is in %s)"
                            % (who, first_error(log_text), os.path.join(folder, "dynare.log")))
        with open(results_path) as f:
            results = json.load(f)
        return results_hash_table(results, folder, log_text)

    return {"dynare-run": dynare_run}
