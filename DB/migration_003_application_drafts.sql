-- ==============================================================================
-- MIGRATION 003 : SERVER-SIDE APPLICATION DRAFTS
--
-- Creates application_drafts, moving referrer drafts out of browser
-- localStorage and onto the server so a draft can be resumed from any machine.
--
-- Run with:  python3 run_sql.py ../DB/migration_003_application_drafts.sql
--
-- Purely additive: creates one new table and touches nothing existing. Safe on
-- a populated database. Re-running fails harmlessly with "table already exists".
--
-- ------------------------------------------------------------------------------
-- AFTER RUNNING THIS
--
-- Existing drafts held in browser localStorage are NOT migrated -- they are
-- per-browser data the server has never seen. Referrers with unfinished local
-- drafts will need to start those again. Clear the old keys from any browser
-- that has them by running this in the developer console on the Phase 1 page:
--
--   Object.keys(localStorage).filter(k => k.startsWith('dmrc_'))
--       .forEach(k => localStorage.removeItem(k));
-- ==============================================================================

USE dmrc_internship_portal;

CREATE TABLE application_drafts (
    draft_id INT AUTO_INCREMENT PRIMARY KEY,

    -- Ownership is by EMPLOYEE, not by browser session. This is what makes a
    -- draft resumable from any machine the referrer signs in from.
    owner_employee_id INT NOT NULL,

    cycle_id INT NULL,
    candidate_name VARCHAR(150) NULL,

    -- Full wizard state: student, academic, placement and document references.
    -- Held as JSON because a draft is partial by definition and cannot satisfy
    -- the NOT NULL constraints on `applications` and `students`.
    payload JSON NOT NULL,

    current_step INT NOT NULL DEFAULT 1,
    highest_step INT NOT NULL DEFAULT 1,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_draft_owner FOREIGN KEY (owner_employee_id)
        REFERENCES employees(employee_id) ON DELETE CASCADE,
    CONSTRAINT fk_draft_cycle FOREIGN KEY (cycle_id)
        REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,

    INDEX idx_draft_owner (owner_employee_id),
    INDEX idx_draft_cycle (cycle_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- VERIFICATION
--   DESCRIBE application_drafts;      -> 9 columns
--   SELECT COUNT(*) FROM application_drafts;  -> 0
-- ==============================================================================
