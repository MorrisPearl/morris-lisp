-- schema.sql
--
-- Table definitions for the FEC bulk-data database loaded by
-- fec_loader.py. This file is kept in sync with SCHEMA_STATEMENTS in
-- fec_loader.py (which is what `fec_loader.py setup` actually runs);
-- use this file if you want to create the schema directly with the
-- mysql client instead, e.g.:
--
--     mysql -u root -p fec < schema.sql
--
-- (create the database first, e.g. `CREATE DATABASE fec CHARACTER SET
-- utf8mb4 COLLATE utf8mb4_unicode_ci;`)

CREATE TABLE IF NOT EXISTS candidate_master (
    cand_id                 VARCHAR(9)   NOT NULL,
    cand_name                VARCHAR(200),
    cand_pty_affiliation     VARCHAR(3),
    cand_election_yr         SMALLINT UNSIGNED,
    cand_office_st           VARCHAR(2),
    cand_office               VARCHAR(1),
    cand_office_district      VARCHAR(2),
    cand_ici                  VARCHAR(1),
    cand_status                VARCHAR(1),
    cand_pcc                   VARCHAR(9),
    cand_st1                   VARCHAR(34),
    cand_st2                   VARCHAR(34),
    cand_city                  VARCHAR(30),
    cand_st                    VARCHAR(2),
    cand_zip                   VARCHAR(9),
    PRIMARY KEY (cand_id),
    INDEX idx_cand_pcc (cand_pcc),
    INDEX idx_cand_office_st (cand_office_st, cand_office)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS committee_master (
    cmte_id                 VARCHAR(9)   NOT NULL,
    cmte_nm                  VARCHAR(200),
    tres_nm                  VARCHAR(90),
    cmte_st1                  VARCHAR(34),
    cmte_st2                  VARCHAR(34),
    cmte_city                 VARCHAR(30),
    cmte_st                   VARCHAR(2),
    cmte_zip                  VARCHAR(9),
    cmte_dsgn                  VARCHAR(1),
    cmte_tp                    VARCHAR(1),
    cmte_pty_affiliation       VARCHAR(3),
    cmte_filing_freq           VARCHAR(1),
    org_tp                     VARCHAR(1),
    connected_org_nm           VARCHAR(200),
    cand_id                    VARCHAR(9),
    PRIMARY KEY (cmte_id),
    INDEX idx_cand_id (cand_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candidate_committee_linkage (
    cand_id               VARCHAR(9)  NOT NULL,
    cand_election_yr       SMALLINT UNSIGNED NOT NULL,
    fec_election_yr         SMALLINT UNSIGNED NOT NULL,
    cmte_id                  VARCHAR(9),
    cmte_tp                  VARCHAR(1),
    cmte_dsgn                 VARCHAR(1),
    linkage_id                 BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (linkage_id),
    INDEX idx_cand_id (cand_id),
    INDEX idx_cmte_id (cmte_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS indiv_contributions (
    cmte_id                 VARCHAR(9),
    amndt_ind                 VARCHAR(1),
    rpt_tp                     VARCHAR(3),
    transaction_pgi             VARCHAR(5),
    image_num                    VARCHAR(18),
    transaction_tp                VARCHAR(3),
    entity_tp                      VARCHAR(3),
    name                             VARCHAR(200),
    city                              VARCHAR(30),
    state                              VARCHAR(2),
    zip_code                           VARCHAR(9),
    employer                            VARCHAR(38),
    occupation                           VARCHAR(38),
    transaction_dt                        DATE,
    transaction_amt                        DECIMAL(14,2),
    other_id                                VARCHAR(9),
    tran_id                                  VARCHAR(32),
    file_num                                  BIGINT UNSIGNED,
    memo_cd                                    VARCHAR(1),
    memo_text                                   VARCHAR(100),
    sub_id                                       BIGINT UNSIGNED NOT NULL,
    -- extra bookkeeping columns, not part of the FEC file, used to
    -- support incremental loading:
    election_cycle    VARCHAR(9)   NULL,
    source_file       VARCHAR(60)  NULL,
    load_batch_id     INT          NULL,
    loaded_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sub_id),
    INDEX idx_cmte_id (cmte_id),
    INDEX idx_name (name(40)),
    INDEX idx_transaction_dt (transaction_dt),
    INDEX idx_zip_code (zip_code),
    INDEX idx_election_cycle (election_cycle)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS load_history (
    load_batch_id   INT AUTO_INCREMENT PRIMARY KEY,
    table_name      VARCHAR(60)  NOT NULL,
    source_file     VARCHAR(120) NOT NULL,
    election_cycle  VARCHAR(9)   NULL,
    rows_in_file    BIGINT       NULL,
    rows_inserted   BIGINT       NULL,
    started_at      DATETIME     NOT NULL,
    finished_at     DATETIME     NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'running'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
