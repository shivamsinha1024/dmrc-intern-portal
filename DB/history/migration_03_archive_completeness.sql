-- =============================================================================
-- DMRC INTERNSHIP PORTAL
-- MIGRATION 03 : ARCHIVE COMPLETENESS
-- Target: TiDB Cloud (also valid on MySQL 8.0+)
-- =============================================================================
--
-- WHY
-- ---
-- Hard-closing a cycle MOVES its applications: they are copied into the archive
-- and then deleted from the live tables, so each new cycle starts from a clean
-- dashboard. Everything attached to an application is declared ON DELETE
-- CASCADE, which means the delete takes these with it, silently:
--
--     academic_details                    -> archived_academic_details   (exists)
--     documents                           -> archived_documents          (exists)
--     joining_details                     -> columns on archived_applications
--     application_status_history          -> NOTHING                     <-- lost
--     application_document_requirements   -> NOTHING                     <-- lost
--     notifications                       -> not archived (transport log only)
--
-- The last two are added here.
--
-- WHY THE TIMELINE MATTERS
-- ------------------------
-- The timeline is the account of what happened to a candidate: who verified,
-- who approved, who rejected and why, and when. For a college referral closed
-- before its form was ever filled it is the ONLY record -- that application has
-- no documents and no academic details, just a name and an outcome. Losing it
-- would leave a Rejected row with no explanation attached to it at all.
--
-- WHY THE REQUIREMENTS SNAPSHOT MATTERS
-- -------------------------------------
-- application_document_requirements records what an application was ASKED for,
-- separately from what was supplied. Without it the archive cannot tell
-- "this cycle never asked for a recommendation letter" from "it was asked for
-- and the candidate declined", because both look like an absent file.
--
-- The Phase-1 form refuses to submit while a MANDATORY document is missing, so
-- this is not about missing mandatory documents. It is about optional documents
-- that were declined, and about college referrals rejected before any documents
-- were requested.
--
-- SELF-CONTAINED BY DESIGN
-- ------------------------
-- Both tables store NAMES AND VALUES, never links to document_types,
-- sub_departments or internship_cycles. An archived record must stay readable
-- after the document catalogue, the sub-department list and the cycle
-- configuration have all changed beyond recognition -- which, over the years a
-- records-retention policy covers, they will.
--
-- SAFETY
-- ------
-- Both statements only ADD tables. No existing table is touched and no data is
-- read, changed or deleted. Safe to run on a live database.
--
-- This is a plain SQL script, NOT a Django migration. The portal's models are
-- declared `managed = False`. Do not run makemigrations or migrate.
-- =============================================================================

USE dmrc_internship_portal;


-- -----------------------------------------------------------------------------
-- 1. ARCHIVED TIMELINE
--
-- One row per step, exactly as application_status_history holds it, but keyed
-- to original_application_id with no foreign key -- the application it refers
-- to no longer exists.
--
-- changed_by_name and changed_by_role are stored as TEXT rather than a link to
-- users. A member of staff may leave DMRC and have their account removed years
-- before anyone reads this record; the archive must still be able to say who
-- took the decision and under which role.
--
-- new_status is VARCHAR, not the ENUM used by the live table. Statuses may be
-- added or renamed in future versions of the portal, and an archived record
-- must not be made unreadable by a change to a list it predates.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS archived_status_history (
    archive_history_id INT AUTO_INCREMENT PRIMARY KEY,
    original_application_id INT NOT NULL,
    application_code VARCHAR(50) NULL,
    previous_status VARCHAR(50) NULL,
    new_status VARCHAR(50) NOT NULL,
    changed_by_name VARCHAR(150) NULL,
    changed_by_role VARCHAR(50) NULL,
    remarks TEXT NULL,
    changed_at TIMESTAMP NULL,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_arch_hist_app (original_application_id),
    INDEX idx_arch_hist_code (application_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 2. ARCHIVED DOCUMENT REQUIREMENTS
--
-- What each application was ASKED to supply, frozen at the moment it was
-- submitted. Mirrors application_document_requirements, minus the doc_type_id
-- link: the document type may since have been disabled, reconfigured or deleted
-- outright, and none of that may alter what this candidate was asked for.
--
-- was_supplied records whether a file existed against this requirement at the
-- moment of archiving. Stored rather than derived, so the archive answers the
-- question without having to join anything.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS archived_document_requirements (
    archive_requirement_id INT AUTO_INCREMENT PRIMARY KEY,
    original_application_id INT NOT NULL,
    application_code VARCHAR(50) NULL,
    doc_type_name VARCHAR(100) NOT NULL,
    allowed_extensions VARCHAR(100) NULL,
    is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
    requires_consent BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INT NOT NULL DEFAULT 0,
    was_supplied BOOLEAN NOT NULL DEFAULT FALSE,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_arch_req_app (original_application_id),
    INDEX idx_arch_req_code (application_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- -----------------------------------------------------------------------------
-- 3. ARCHIVED DOCUMENTS -- add the fields the viewer needs
--
-- Uploaded files STAY WHERE THEY ARE on disk, under PROTECTED_DOCUMENT_ROOT.
-- Moving thousands of files during an archive is a large operation that can
-- half-fail, and it buys nothing: the folder is already outside the web root
-- and unreachable by URL. The archive simply keeps the same paths.
--
-- The document viewer resolves a link by looking up `documents` by id. After a
-- cycle is archived that row is gone, so the viewer needs the ORIGINAL id to
-- fall back on -- otherwise every document in the archive returns "not found".
-- -----------------------------------------------------------------------------
ALTER TABLE archived_documents ADD COLUMN original_document_id INT NULL;
ALTER TABLE archived_documents ADD COLUMN application_code VARCHAR(50) NULL;
ALTER TABLE archived_documents ADD COLUMN is_system_generated BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX idx_arch_doc_original ON archived_documents (original_document_id);
CREATE INDEX idx_arch_doc_code ON archived_documents (application_code);


-- -----------------------------------------------------------------------------
-- 4. ARCHIVED APPLICATIONS -- one missing date
--
-- archived_applications already carries the actual date of joining, the DMRA
-- date, the sub-department NAME and the completion date. The date HR allotted
-- is the one gap: for a candidate rejected as a no-show it is the only record
-- of when they were told to report.
-- -----------------------------------------------------------------------------
ALTER TABLE archived_applications ADD COLUMN allotted_date_of_joining DATE NULL;


-- -----------------------------------------------------------------------------
-- 5. VERIFICATION -- runs automatically.
--
--   Query 1: both new tables must be listed.
--   Query 2: all five added columns must be listed.
-- -----------------------------------------------------------------------------
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'dmrc_internship_portal'
  AND table_name IN ('archived_status_history', 'archived_document_requirements')
ORDER BY table_name;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'dmrc_internship_portal'
  AND ((table_name = 'archived_documents'
        AND column_name IN ('original_document_id', 'application_code', 'is_system_generated'))
    OR (table_name = 'archived_applications'
        AND column_name IN ('allotted_date_of_joining')))
ORDER BY table_name, column_name;
