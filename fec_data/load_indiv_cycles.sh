#!/usr/bin/env bash
#
# load_indiv_cycles.sh [CYCLE ...]
#
# Adds one or more prior election cycles' Contributions by Individuals
# data to the existing database (does NOT touch candidate_master /
# committee_master / candidate_committee_linkage, which are always a
# snapshot of *current* state, not per-cycle history -- re-running
# load-static for an old cycle would overwrite this cycle's static data
# with stale data, which we don't want).
#
# Usage:
#   ./load_indiv_cycles.sh 2024 2022 2020

set -euo pipefail
cd "$(dirname "$0")"

CONFIG="config.ini"
CYCLES=("$@")
if [ ${#CYCLES[@]} -eq 0 ]; then
    CYCLES=(2024 2022 2020)
fi

for CYCLE in "${CYCLES[@]}"; do
    echo "== load-indiv --cycle $CYCLE =="
    python3 fec_loader_sqlite.py --config "$CONFIG" load-indiv --cycle "$CYCLE"
done

echo "== status =="
python3 fec_loader_sqlite.py --config "$CONFIG" status
