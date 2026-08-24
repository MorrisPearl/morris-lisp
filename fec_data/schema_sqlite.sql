-- schema_sqlite.sql
--
-- Table definitions for the FEC bulk-data database loaded by
-- fec_loader_sqlite.py. This file is kept in sync with the schema
-- built by `fec_loader_sqlite.py setup` (which is what actually runs);
-- use this file if you want to create the schema directly with the
-- sqlite3 client instead, e.g.:
--
--     sqlite3 fec.db < schema_sqlite.sql
--
-- This is the SQLite counterpart of schema.sql (the MySQL version).
-- Differences from the MySQL schema are purely dialect-driven:
--   - VARCHAR(n)/DECIMAL -> TEXT/REAL (SQLite has no fixed-length or
--     fixed-precision types; it uses dynamic typing with "affinity").
--   - Indexes are declared with separate CREATE INDEX statements
--     instead of inline INDEX(...) clauses.
--   - `sub_id INTEGER PRIMARY KEY ON CONFLICT IGNORE` replaces MySQL's
--     `PRIMARY KEY (sub_id)` + `LOAD DATA ... IGNORE`: in SQLite the
--     conflict-resolution policy can live on the constraint itself, so
--     *every* insert into indiv_contributions (including the plain
--     INSERT used by the bulk loader) silently skips rows whose sub_id
--     already exists, with no need for an explicit "OR IGNORE" at each
--     call site.

CREATE TABLE IF NOT EXISTS candidate_master (
    cand_id              TEXT PRIMARY KEY,
    cand_name            TEXT,
    cand_pty_affiliation TEXT,
    cand_election_yr     INTEGER,
    cand_office_st       TEXT,
    cand_office          TEXT,
    cand_office_district TEXT,
    cand_ici             TEXT,
    cand_status          TEXT,
    cand_pcc             TEXT,
    cand_st1             TEXT,
    cand_st2             TEXT,
    cand_city            TEXT,
    cand_st              TEXT,
    cand_zip             TEXT
);
CREATE INDEX IF NOT EXISTS idx_cand_pcc ON candidate_master (cand_pcc);
CREATE INDEX IF NOT EXISTS idx_cand_office_st ON candidate_master (cand_office_st, cand_office);

CREATE TABLE IF NOT EXISTS committee_master (
    cmte_id             TEXT PRIMARY KEY,
    cmte_nm             TEXT,
    tres_nm             TEXT,
    cmte_st1            TEXT,
    cmte_st2            TEXT,
    cmte_city           TEXT,
    cmte_st             TEXT,
    cmte_zip            TEXT,
    cmte_dsgn           TEXT,
    cmte_tp             TEXT,
    cmte_pty_affiliation TEXT,
    cmte_filing_freq    TEXT,
    org_tp              TEXT,
    connected_org_nm    TEXT,
    cand_id             TEXT
);
CREATE INDEX IF NOT EXISTS idx_cmte_cand_id ON committee_master (cand_id);

CREATE TABLE IF NOT EXISTS candidate_committee_linkage (
    cand_id           TEXT NOT NULL,
    cand_election_yr  INTEGER NOT NULL,
    fec_election_yr   INTEGER NOT NULL,
    cmte_id           TEXT,
    cmte_tp           TEXT,
    cmte_dsgn         TEXT,
    linkage_id        INTEGER PRIMARY KEY
);
CREATE INDEX IF NOT EXISTS idx_ccl_cand_id ON candidate_committee_linkage (cand_id);
CREATE INDEX IF NOT EXISTS idx_ccl_cmte_id ON candidate_committee_linkage (cmte_id);

CREATE TABLE IF NOT EXISTS indiv_contributions (
    cmte_id           TEXT,
    amndt_ind         TEXT,
    rpt_tp            TEXT,
    transaction_pgi   TEXT,
    image_num         TEXT,
    transaction_tp    TEXT,
    entity_tp         TEXT,
    name              TEXT,
    city              TEXT,
    state             TEXT,
    zip_code          TEXT,
    employer          TEXT,
    occupation        TEXT,
    transaction_dt    TEXT,    -- ISO YYYY-MM-DD text, converted from MMDDYYYY
    transaction_amt   REAL,
    other_id          TEXT,
    tran_id           TEXT,
    file_num          INTEGER,
    memo_cd           TEXT,
    memo_text         TEXT,
    sub_id            INTEGER PRIMARY KEY ON CONFLICT IGNORE,
    -- extra bookkeeping columns, not part of the FEC file, used to
    -- support incremental loading:
    election_cycle    TEXT,
    source_file       TEXT,
    load_batch_id     INTEGER,
    loaded_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_indiv_cmte_id ON indiv_contributions (cmte_id);
CREATE INDEX IF NOT EXISTS idx_indiv_name ON indiv_contributions (name);
CREATE INDEX IF NOT EXISTS idx_indiv_transaction_dt ON indiv_contributions (transaction_dt);
CREATE INDEX IF NOT EXISTS idx_indiv_zip_code ON indiv_contributions (zip_code);
CREATE INDEX IF NOT EXISTS idx_indiv_election_cycle ON indiv_contributions (election_cycle);
CREATE INDEX IF NOT EXISTS idx_indiv_load_batch_id ON indiv_contributions (load_batch_id);

CREATE TABLE IF NOT EXISTS load_history (
    load_batch_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name      TEXT NOT NULL,
    source_file     TEXT NOT NULL,
    election_cycle  TEXT,
    rows_in_file    INTEGER,
    rows_inserted   INTEGER,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
);
