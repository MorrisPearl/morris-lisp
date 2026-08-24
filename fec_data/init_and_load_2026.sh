#!/usr/bin/env bash
#
# init_and_load_2026.sh
#
# One-shot bootstrap: wipes any existing SQLite FEC database, creates a
# fresh schema, then downloads and loads the full 2025-2026 cycle
# (Candidate Master, Committee Master, Candidate-Committee Linkages,
# and Contributions by Individuals) via fec_loader_sqlite.py.
#
# Run again later (without this script) with:
#   python fec_loader_sqlite.py load-static --cycle <year>
#   python fec_loader_sqlite.py load-indiv  --cycle <year>
# to add other cycles without wiping the database -- this script is
# only for the initial from-scratch load.

set -euo pipefail
cd "$(dirname "$0")"

CONFIG="config.ini"
CYCLE=2026

if [ ! -f "$CONFIG" ]; then
    echo "No $CONFIG found -- creating one from config.ini.example."
    echo "(Edit it afterward if you want a different db_path or download dir.)"
    cp config.ini.example "$CONFIG"
fi

DB_PATH=$(python3 -c "
import configparser
c = configparser.ConfigParser()
c.read('$CONFIG')
print(c.get('sqlite', 'db_path', fallback='./fec.db'))
")

echo "== Database: $DB_PATH =="
if [ -f "$DB_PATH" ]; then
    echo "Removing existing database to start from scratch."
    rm -f "$DB_PATH" "${DB_PATH}-wal" "${DB_PATH}-shm"
fi

echo "== setup =="
python3 fec_loader_sqlite.py --config "$CONFIG" setup

echo "== load-all --cycle $CYCLE =="
python3 fec_loader_sqlite.py --config "$CONFIG" load-all --cycle "$CYCLE"

echo "== status =="
python3 fec_loader_sqlite.py --config "$CONFIG" status
