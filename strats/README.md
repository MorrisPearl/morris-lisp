# Stratification Report Builder

A PyQt6 desktop app for building stratification reports from a data file.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

A `sample_data.csv` file is included so you can try it immediately.

## How it works

1. **Load Input File** — browse to a CSV/TSV file and click Load.
   - Check **"File has no header row"** if the file has no column names.
     Columns will be auto-named `Column1`, `Column2`, ... — just type the
     real names directly into the **Field** column of the table below
     (it's editable), then click **Apply Column Names**. This also works
     any time you want to rename a field, header row or not.
   - Every column becomes a row in the field configuration table, auto-
     detected as **numeric** or **categorical**.

2. **Configure Fields** — for each field, set:
   - **Weight?** — pick at most one field as the WEIGHT field (used for
     weighted stats and for "equal weight" bucketing). Leave unset to
     treat every record equally. Use "Clear Weight Selection" to unset it.
   - **N (buckets)** — how many buckets that field's own report should have.
     For categorical fields you can check **All** instead, to give every
     distinct value its own bucket (no "Other" bucket).
   - **Method**:
     - *Equal Count Buckets* (numeric) — same number of records per bucket.
     - *Equal Weight Buckets* (numeric) — buckets with approximately equal
       total weight (uses the designated WEIGHT field; falls back to equal
       count if no weight is set).
     - *Manual Breakpoints* (numeric) — you supply the exact cut points
       (e.g. `100, 250, 500`), which creates `len(breakpoints) + 1` buckets.
     - *Top Values + Other* (categorical) — the N-1 most common values, plus
       one "Other" bucket for the rest.
     - *None* — don't generate a standalone report for this field at all
       (it can still be used as the WEIGHT field, a summary column, or a
       dimension in a multi-field report).
   - **Breakpoints** — only used with Manual Breakpoints.
   - **Summary Stats** — click the button to open a picker where you can
     select **one or more** statistics for this field. Each selected stat
     becomes its own column wherever this field is summarized in a report:
     Sum, Average, Median, Weighted Average, Weighted Median, Percentile
     (you specify which percentile), Weighted Percentile, Min, Max, Mode,
     Weighted Mode, or Representative Value (an arbitrary actual value from
     the bucket — useful for text/ID fields). Leave the list empty to
     exclude the field entirely (equivalent to "None").

3. **Multi-Field Reports (optional)** — click **Add Multi-Field Report...**
   and check 2 or more fields to stratify on *simultaneously*. Each row of
   the resulting report is the intersection of one bucket from each chosen
   field (using that field's own N/Method settings from the table above) —
   up to the product of their bucket counts, though combinations with zero
   matching records are omitted. You'll get a confirmation prompt if a
   combination could produce an unusually large number of rows.

4. **Save / Load Configuration** — save everything you've entered (weight
   field, every field's N/Method/breakpoints/stats, and all multi-field
   report definitions) to a nicely formatted JSON file, and reload it later.
   If the JSON's referenced input file is still at the same path, loading
   the configuration will load that file and apply all the settings
   automatically.

5. **Generate Reports** — builds one report per input field (skipping any
   with Method = None) plus every defined multi-field report. Each report's
   first column(s) identify the bucket, followed by `Count`, `Total Weight`,
   and one column per selected summary statistic per other field.

6. **Export** — save every generated report as one multi-sheet Excel
   workbook, or as a folder of individual CSV files.

## Files

- `main.py` — the PyQt6 GUI.
- `stratify_engine.py` — the bucketing / summary-statistic logic (pure
  pandas, no Qt dependency — easy to unit test or reuse in a script).
- `sample_data.csv` — example input data.
