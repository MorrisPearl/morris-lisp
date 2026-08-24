# FEC bulk data loader

Downloads four FEC bulk data files and loads them into a database with
table layouts that match the flat files field-for-field. Two
interchangeable loaders are provided:

- **`fec_loader.py`** -- loads into MySQL via `LOAD DATA LOCAL INFILE`.
  Use this if other things need concurrent read/write access to the
  data while it's being updated.
- **`fec_loader_sqlite.py`** -- loads into a local SQLite file via the
  `sqlite3` command-line tool's `.import` command (the closest SQLite
  equivalent of `LOAD DATA`). No server to run or configure. Best for
  unattended, single-writer setups (e.g. an overnight cron job) where
  nothing needs to read or write the database while it's loading --
  SQLite allows only one writer at a time. See
  [SQLite version](#sqlite-version) below.

Both loaders share the same table names, columns, `config.ini` file,
and command names (`setup`, `load-static`, `load-indiv`, `load-all`,
`sync-indiv`, `inspect-schedule-a`, `status`), so everything in this
README that isn't MySQL/SQL-syntax-specific applies to either one --
just substitute the script name.

| FEC file | Table | Refresh behavior |
|---|---|---|
| Candidate Master (`cn`) | `candidate_master` | truncate + reload every run |
| Candidate-Committee Linkages (`ccl`) | `candidate_committee_linkage` | truncate + reload every run |
| Committee Master (`cm`) | `committee_master` | truncate + reload every run |
| Contributions by Individuals (`itcont`) | `indiv_contributions` | append-only, deduped by `SUB_ID` |

Source: https://www.fec.gov/data/browse-data/?tab=bulk-data (field layouts
confirmed against the FEC's own file-description pages).

## Setup

```bash
pip install -r requirements.txt
cp config.ini.example config.ini
# edit config.ini with your MySQL host/user/password/database
```

On the MySQL server, local file loading must be turned on (it's off by
default):

```sql
SET GLOBAL local_infile = 1;
```

(or add `local-infile=1` under `[mysqld]` in `my.cnf` and restart).

Create the schema:

```bash
python fec_loader.py setup
```

## Usage

```bash
# Candidate Master, Committee Master, Candidate-Committee Linkages
# (small files, always re-downloaded and reloaded from scratch)
python fec_loader.py load-static

# Contributions by Individuals (huge file; only new rows get added)
python fec_loader.py load-indiv

# both of the above
python fec_loader.py load-all

# row counts + recent load history
python fec_loader.py status
```

All commands default to the current 2-year election cycle (e.g. the
2025-2026 cycle is requested as `cn26.zip`, `cm26.zip`, etc.). To target a
specific cycle, pass `--cycle` with the ending year:

```bash
python fec_loader.py load-static --cycle 2024
python fec_loader.py load-indiv --cycle 2024
```

Run `load-indiv` again periodically (e.g. daily/weekly via cron) to pick up
new contributions as the FEC updates the file -- or use `sync-indiv`
instead (see below) to avoid re-downloading the whole file every time.

## Faster incremental updates via the OpenFEC API

`load-indiv` re-downloads the full current-cycle bulk file (several GB)
every time, because FEC's bulk endpoint doesn't offer delta downloads. If
you're running updates often, `sync-indiv` is a lighter-weight alternative
that queries the [OpenFEC API](https://api.open.fec.gov) for only the
records newer than the highest `SUB_ID` you already have, instead of
re-downloading everything:

```bash
# one-time: get a free key at https://api.data.gov/signup/ and put it in
# config.ini under [openfec] api_key = ...

# do the initial full load via the bulk file (fast for the first load)
python fec_loader.py load-indiv

# then keep it current with lightweight API top-ups
python fec_loader.py sync-indiv
```

`sync-indiv` requires an existing initial load for the cycle (via
`load-indiv`) -- pulling an entire cycle's history through the API instead
of the bulk file would be extremely slow and rate-limited. Pass
`--allow-full-sync` if you want to do that anyway.

**Caveat -- please read before relying on this for unattended/scheduled
runs:** this script was built without the ability to reach
`api.open.fec.gov` from its development environment (network access was
blocked there), so the mapping from OpenFEC's JSON field names to this
database's columns (`SCHEDULE_A_FIELD_ALIASES` in `fec_loader.py`) is
based on well-established public documentation/usage of that API, not a
live response I was able to inspect myself. Two safeguards are built in:

1. `sync-indiv` validates its very first fetched record against the
   expected field names before inserting anything, and refuses to proceed
   (with a clear error listing the actual fields it found) if a column is
   genuinely unmatched.
2. Run `python fec_loader.py inspect-schedule-a` any time to fetch one
   real record and print its raw fields side by side with how the current
   mapping resolves them -- do this once before trusting `sync-indiv`,
   and again if a future FEC/OpenFEC change ever breaks it.

A field that got silently *renamed* to something not already in the alias
list could in principle pass validation with a `None` value rather than
being caught -- `inspect-schedule-a` is the way to catch that.

`sync-indiv` also assumes OpenFEC's seek-pagination cursor (`index`) and
the bulk file's `SUB_ID` are on a compatible numbering scheme, which is
the documented, intended way to resume from bulk data via the API. As
extra insurance, it always re-fetches a small overlap (2,000 rows by
default, `--overlap` to change) before your highest known `SUB_ID`, which
costs a little extra API traffic but nothing else -- overlapping rows are
silently skipped by `INSERT IGNORE`, same as everywhere else in this
script.

## How the incremental load works

FEC's bulk data page doesn't offer delta/incremental files -- the
`indivNN.zip` for the current cycle is always a full extract of everything
disclosed so far. `load-indiv` downloads that full file every time, but
loads it with:

```sql
LOAD DATA LOCAL INFILE '...' IGNORE INTO TABLE indiv_contributions ...
```

`SUB_ID` (FEC's own unique row id) is the table's primary key, so `IGNORE`
causes MySQL to silently skip any row whose `SUB_ID` you already have and
insert only the new ones. This keeps `indiv_contributions` free of
duplicates without ever needing to re-read or diff old data.

Every row is stamped with three bookkeeping columns not present in the raw
FEC file, so you can always tell where a row came from:

- `election_cycle` -- e.g. `2025-2026`
- `source_file` -- e.g. `indiv26.zip`
- `load_batch_id` -- foreign key into `load_history`, which records every
  run (file, cycle, row counts, start/end time, status)

Note: the download itself is still the full current-cycle file each time
(often several GB) -- FEC's bulk downloads don't support partial/date-range
downloads. If you want to fetch only *new* transactions since your last
run (and avoid re-downloading the whole file), that requires querying the
[OpenFEC API](https://api.open.fec.gov) instead of the bulk files; let me
know if you'd like that built as an alternative or a supplement.

## SQLite version

`fec_loader_sqlite.py` is a drop-in alternative to `fec_loader.py` that
needs no database server -- just a local file and the `sqlite3`
command-line tool (ships with macOS and most Linux distros; if it's
missing, `brew install sqlite` or `apt install sqlite3`).

```bash
pip install -r requirements.txt   # only 'requests' is actually needed here
cp config.ini.example config.ini
# edit config.ini: [sqlite] db_path = ./fec.db

python fec_loader_sqlite.py setup
python fec_loader_sqlite.py load-all
python fec_loader_sqlite.py status
```

All the same subcommands, `--cycle`, and `sync-indiv`/`inspect-schedule-a`
OpenFEC options work identically to `fec_loader.py` -- see the sections
above.

**Why SQLite instead of just using MySQL for everything:** if you don't
need concurrent access to the data while it's loading (e.g. you run
updates overnight via cron, when nothing else is querying it), SQLite
avoids running a database server at all. The tradeoff is that SQLite
only supports one writer at a time, so this isn't a good fit if you
need the data to stay live and queryable *during* a load.

**How the bulk loading works:** MySQL's `LOAD DATA LOCAL INFILE` has no
direct SQLite equivalent inside a normal database connection, but the
`sqlite3` command-line client's `.import` dot-command does the same
job -- it streams a delimited text file straight into a table without
going through row-by-row `INSERT` statements from Python. This script
shells out to that CLI (via `subprocess`) for every bulk load:

- Candidate Master, Committee Master and Candidate-Committee Linkages
  match their target tables' columns 1:1, so the extracted file is
  `.import`ed directly into a freshly dropped-and-recreated table
  (indexes are recreated afterward).
- Contributions by Individuals needs a little transformation (the
  `MMDDYYYY` date and three bookkeeping columns not present in the raw
  file), so it's `.import`ed into a throwaway staging table first, then
  copied into `indiv_contributions` with one `INSERT ... SELECT`.
  Deduplication by `SUB_ID` doesn't need MySQL's `IGNORE` keyword --
  `indiv_contributions` declares `sub_id INTEGER PRIMARY KEY ON
  CONFLICT IGNORE`, so *any* insert that collides on an existing
  `sub_id` (including this one) is silently skipped by SQLite itself.

Since this is meant for unattended single-writer runs where a crash
mid-load just means re-running the load, the loader trades away
durability for speed during the bulk-load step: `journal_mode=OFF`
(no rollback journal at all -- not even WAL) and `synchronous=OFF`.
This is meaningfully riskier than the defaults -- a crash mid-script
can in principle leave the database file corrupt, not just missing the
in-progress transaction -- so don't use this against a database you
can't afford to recreate from scratch. Each PRAGMA only applies to the
connection that sets it (the `sqlite3` CLI subprocess for that one
load), so it doesn't linger and affect other connections opened
afterward (e.g. `status`).

For `indiv_contributions`, the loader also drops its five secondary
indexes before the bulk insert and rebuilds them afterward, since
maintaining them row-by-row during a multi-million-row insert is much
slower than bulk-building them once at the end (the `sub_id` primary
key index stays in place throughout, since dedup depends on it). This
only happens for `load-indiv` (the bulk-file path); `sync-indiv` (the
OpenFEC API top-up, meant for small day-to-day deltas) leaves indexes
in place, since rebuilding all of them on every small top-up would cost
more than it saves.

By default, `load-static`/`load-indiv`/`load-all` delete each
downloaded zip and extracted flat file once it's been loaded
successfully -- pass `--keep-downloads` to keep them around instead.

`schema_sqlite.sql` is the SQLite counterpart of `schema.sql`, if you'd
rather create the schema by hand with `sqlite3 fec.db < schema_sqlite.sql`.

## Encoding

FEC bulk files are Latin-1/Windows-1252 encoded, not UTF-8.

- `fec_loader.py` tells MySQL to read the files as `latin1` and convert
  into the tables' `utf8mb4` columns, so names with accented characters
  come through intact.
- `fec_loader_sqlite.py` re-encodes each extracted file from Latin-1 to
  UTF-8 (SQLite text storage is always UTF-8, and `.import` has no
  per-file charset option) before running `.import`, then deletes the
  re-encoded copy.

## Notes

- No foreign key constraints are enforced between tables (FEC's own data
  has occasional referential gaps, e.g. a `CAND_ID` in `committee_master`
  that briefly doesn't yet exist in `candidate_master`). Indexes are added
  on the natural join columns (`cand_id`, `cmte_id`) instead.
- `TRANSACTION_DT` in the individual contributions file is converted from
  `MMDDYYYY` text to a real date column: `STR_TO_DATE(@transaction_dt,
  '%m%d%Y')` in `fec_loader.py` (MySQL `DATE`), or a `substr()`-built
  ISO `YYYY-MM-DD` string in `fec_loader_sqlite.py` (SQLite has no native
  date type; ISO text is what its own date functions expect). Blank
  dates become `NULL` in both.
