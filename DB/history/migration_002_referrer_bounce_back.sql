-- ==============================================================================
-- MIGRATION 002 : REFERRER BOUNCE-BACK TRACKING
--
-- Adds applications.awaiting_referrer_action.
--
-- A "Request Correction" or "No Show -> Send to Referrer" action parks an
-- application with status='Rejected' so it surfaces in the HR Rejected tab.
-- A final rejection carries the same status. This flag separates the two:
--
--   TRUE   parked with the referrer, awaiting their correction. Actionable in
--          the referrer portal, and excluded from genuine rejection counts.
--   FALSE  a normal application, or a final rejection.
--
-- Cleared automatically when the referrer resubmits.
--
-- Run with:  python3 run_sql.py ../DB/migration_002_referrer_bounce_back.sql
--
-- NOTE ON THE TWO STATEMENTS
-- TiDB rejects adding a column and an index on that same new column inside one
-- ALTER statement (error 1072: column does not exist). MySQL tolerates it; TiDB
-- does not. They are therefore issued separately and must stay that way.
--
-- NOTE ON RE-RUNNING
-- DDL auto-commits and cannot be rolled back, so a failure part-way through
-- leaves earlier statements applied. If statement 1 already succeeded, re-running
-- fails with "Duplicate column name" -- harmless. Check the current state with
-- DESCRIBE applications; before re-running, and delete whichever statement has
-- already been applied.
-- ==============================================================================

USE dmrc_internship_portal;

-- STEP 1 : the column
ALTER TABLE applications
    ADD COLUMN awaiting_referrer_action BOOLEAN NOT NULL DEFAULT FALSE AFTER is_resubmitted;

-- STEP 2 : the index, as a separate statement (see note above)
ALTER TABLE applications
    ADD INDEX idx_app_awaiting_referrer (awaiting_referrer_action);

-- ------------------------------------------------------------------------------
-- VERIFICATION
--   DESCRIBE applications;
--     -> awaiting_referrer_action | tinyint(1) | NO | | 0 |
--
--   SHOW INDEX FROM applications WHERE Key_name = 'idx_app_awaiting_referrer';
--     -> one row
-- ==============================================================================
