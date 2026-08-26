-- schema_pa.sql
--
-- SQLite schema for the PythonAnywhere deployment of the Patriotic
-- Millionaires donor-lookup app. This is a trimmed variant of
-- fec_data/schema_sqlite.sql:
--
--   - indiv_contributions only keeps the columns contribution_info.py
--     (and the indiv_m rebuild) actually use, plus zip_code (kept for
--     possible future queries per request) and the bookkeeping columns
--     the incremental loader needs. Dropped: amndt_ind, rpt_tp,
--     transaction_pgi, image_num, transaction_tp, entity_tp,
--     occupation, other_id, tran_id, file_num, memo_cd, memo_text.
--   - ngp_contacts / indiv_m match the *live* production MySQL schema
--     minus the `dares` and `ep_max_out` columns, which the live table
--     has but which are NULL on every single row (confirmed against a
--     live export) -- i.e. genuinely unused, per request.
--
-- candidate_master / committee_master / load_history are unchanged
-- from schema_sqlite.sql (small reference tables; no need to trim).

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
    cmte_id              TEXT PRIMARY KEY,
    cmte_nm              TEXT,
    tres_nm              TEXT,
    cmte_st1             TEXT,
    cmte_st2             TEXT,
    cmte_city            TEXT,
    cmte_st              TEXT,
    cmte_zip             TEXT,
    cmte_dsgn            TEXT,
    cmte_tp              TEXT,
    cmte_pty_affiliation TEXT,
    cmte_filing_freq     TEXT,
    org_tp               TEXT,
    connected_org_nm     TEXT,
    cand_id              TEXT
);
CREATE INDEX IF NOT EXISTS idx_cmte_cand_id ON committee_master (cand_id);

-- Trimmed: only the columns the app and indiv_m rebuild use, plus
-- zip_code (kept for possible future queries) and loader bookkeeping.
CREATE TABLE IF NOT EXISTS indiv_contributions (
    cmte_id           TEXT,
    name              TEXT,
    city              TEXT,
    state             TEXT,
    zip_code          TEXT,
    employer          TEXT,
    transaction_dt    TEXT,
    transaction_amt   REAL,
    sub_id            INTEGER PRIMARY KEY ON CONFLICT IGNORE,
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

-- Membership list. Matches the live production ngp_contacts schema
-- minus dares/ep_max_out (always NULL there -- unused).
CREATE TABLE IF NOT EXISTS ngp_contacts (
    last_name   TEXT,
    first_name  TEXT,
    city        TEXT,
    state       TEXT,
    match_name  TEXT,
    priv        INTEGER,
    pub         INTEGER,
    mem         INTEGER,
    prospect    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ngp_match_name ON ngp_contacts (match_name);

-- Pre-computed join of ngp_contacts x indiv_contributions (matched by
-- indiv_contributions.name LIKE ngp_contacts.match_name), rebuilt
-- after ngp_contacts or indiv_contributions changes. This is what
-- makes the donor-lookup query fast -- see rebuild_indiv_m() in
-- fec_loader_pa.py.
CREATE TABLE IF NOT EXISTS indiv_m (
    last_name       TEXT,
    first_name      TEXT,
    city            TEXT,
    state           TEXT,
    match_name      TEXT,
    priv            INTEGER,
    pub             INTEGER,
    mem             INTEGER,
    prospect        INTEGER,
    fec_name        TEXT,
    fec_city        TEXT,
    fec_state       TEXT,
    fec_employer    TEXT,
    committee_id    TEXT,
    trans_amount    REAL,
    trans_date      TEXT
);
CREATE INDEX IF NOT EXISTS idx_indiv_m_match_name ON indiv_m (match_name);
CREATE INDEX IF NOT EXISTS idx_indiv_m_committee_id ON indiv_m (committee_id);

-- Tracks the highest indiv_contributions.load_batch_id already folded
-- into indiv_m, so update_indiv_m() (the incremental nightly path in
-- fec_loader_pa.py) only has to look at rows added since the last
-- rebuild/update instead of rescanning the whole table each time.
CREATE TABLE IF NOT EXISTS indiv_m_state (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    last_load_batch_id  INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO indiv_m_state (id, last_load_batch_id) VALUES (1, 0);
