-- ==============================================================================
-- MIGRATION 05 - OFFER LETTER GENERATION & SIGNATURE AUTHORITY
--
--   python3 run_sql.py ../DB/migration_05_offer_letters.sql
--
-- Run once, against an existing database. A freshly created database from
-- Intern_Portal.sql already contains everything below and does NOT need this
-- file -- the master script has been updated in step with it.
--
-- RUNNING IT TWICE: every column and index statement uses IF NOT EXISTS and is
-- safe to repeat. The four FOREIGN KEYS in section 9 are NOT -- MySQL and TiDB
-- have no IF NOT EXISTS for a constraint, so a second run reports "Duplicate
-- foreign key constraint name" on each of them. That error is harmless (the
-- constraint is already there), but if you would rather it ran cleanly, delete
-- section 9 before re-running. Nothing else in the file will complain.
--
-- (IF NOT EXISTS on ADD COLUMN is a TiDB extension. DMRC IT receive the master
-- script, not this file, so nothing here needs to work on plain MySQL.)
--
-- ------------------------------------------------------------------------------
-- WHAT THIS ADDS, AND WHY
--
-- 1. SIGNATURE AUTHORITY on `users`. The columns that hold the signature image
--    itself already existed and were never used. What was missing was the
--    paperwork around an approval: when it was submitted, who decided, when,
--    and -- on a rejection -- why. A SYS-ADMIN must give a reason, so there has
--    to be somewhere to put it.
--
-- 2. OFFER LETTER STATE on `applications`. Three of these matter more than they
--    look:
--
--      offer_letter_issued_at        the "Dated:" printed on the letter. Stored
--                                    rather than computed, so a reprint next
--                                    month still shows the date it was signed.
--      offer_letter_signature_path   the exact signature image used, frozen at
--                                    the moment of signing. Without this, an
--                                    officer changing their signature would
--                                    silently alter every letter ever reprinted.
--      offer_letter_signed_by_user_id  who signed. Their name and designation
--                                    are printed under the signature.
--
-- 3. HANDOVER CONFIRMATION, also on `applications`. The two hard-copy
--    declarations HR-OPS ticks before an intern becomes Joined. Physical
--    documents: nothing is uploaded, the tick IS the record, so it needs to be
--    stored and stamped rather than left in the browser.
--
-- 4. THE CORRECTION LOOP on `documents`. A corrected offer letter uploaded by
--    HR-OPS must NOT become the official document until HR-APP approves it.
--    Today an upload is official the instant it lands. See the long note above
--    the ALTER for how the two states are kept apart.
--
-- 5. A REJECTION CATEGORY for an intern who completed the internship but was
--    marked Unsatisfactory by their mentor. Without it that person is recorded
--    identically to a candidate rejected months earlier for a bad photograph.
--
-- 6. COMPLETION LETTER is removed from the document catalogue. It was never
--    generated, never uploaded and never referenced.
--
-- 7. Two ARCHIVE columns, so a closed cycle still records that a letter was
--    issued and by whom.
-- ==============================================================================

USE dmrc_internship_portal;

-- ------------------------------------------------------------------------------
-- 1. SIGNATURE AUTHORITY
--
-- The workflow these support:
--   HR-APP uploads      -> pending_signature_path set, status 'Pending',
--                          signature_uploaded_at stamped
--   SYS-ADMIN approves  -> pending becomes active, signature_activated_at
--                          stamped, pending cleared
--   SYS-ADMIN rejects   -> pending cleared and quarantined, reason recorded
--
-- Throughout all of it the ACTIVE signature keeps working. An officer whose new
-- signature is awaiting approval carries on issuing letters with their old one.
-- ------------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_uploaded_at TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_activated_at TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_reviewed_at TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_reviewed_by_user_id INT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_rejection_reason TEXT NULL;

-- (The foreign key for signature_reviewed_by_user_id is in section 9.)

-- ------------------------------------------------------------------------------
-- 2. OFFER LETTER ISSUANCE STATE
-- ------------------------------------------------------------------------------
ALTER TABLE applications ADD COLUMN IF NOT EXISTS offer_letter_issued_at DATETIME NULL;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS offer_letter_signed_by_user_id INT NULL;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS offer_letter_signature_path VARCHAR(500) NULL;

-- (The foreign key for offer_letter_signed_by_user_id is in section 9.)

-- ------------------------------------------------------------------------------
-- 3. HANDOVER CONFIRMATION
--
-- NOT NULL DEFAULT FALSE: every existing application answers "no" to both,
-- which is correct -- none of them has been handed over under this process.
-- ------------------------------------------------------------------------------
ALTER TABLE applications ADD COLUMN IF NOT EXISTS hardcopy_undertaking_received BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS hardcopy_attendance_received BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS handover_completed_at DATETIME NULL;

-- ------------------------------------------------------------------------------
-- 4. THE CORRECTION LOOP
--
-- `documents` already guarantees exactly one live row per (application, type)
-- through uq_doc_current, using the rule that NULLs are distinct inside a
-- UNIQUE index:
--
--     is_current = 1     the single official document
--     is_current = NULL  superseded; never returned by any read path
--
-- A corrected letter awaiting HR-APP approval is neither. It cannot be current
-- -- it is not official yet -- but calling it superseded would hide it from the
-- approval queue and make it indistinguishable from the discarded versions
-- underneath it.
--
-- So it gets a second flag using the same NULL-distinctness rule:
--
--     is_pending_approval = 1     awaiting HR-APP's decision (is_current NULL)
--     is_pending_approval = NULL  everything else
--
-- uq_doc_pending then permits at most ONE pending upload per document per
-- application, enforced by the database rather than by trust. HR-OPS cannot
-- stack two corrections and leave HR-APP guessing which is live.
--
-- On approval the pending row becomes is_current = 1 and the previous official
-- row is demoted the usual way. On rejection both flags go NULL, the reason is
-- stored, and the file is moved to quarantine.
--
-- Do NOT give is_pending_approval a DEFAULT of 0 or make it NOT NULL. Either
-- would allow only one non-pending document in the entire history of an
-- application and break the version chain.
-- ------------------------------------------------------------------------------
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_pending_approval TINYINT(1) NULL DEFAULT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by_user_id INT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS reviewed_by_user_id INT NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP NULL;

-- HR-APP's mandatory remark when sending a corrected letter back. Kept separate
-- from hr_remarks, which belongs to document VERIFICATION during the Phase-1
-- check and means something different.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS approval_remarks TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_pending
    ON documents (application_id, doc_type_id, is_pending_approval);

-- (The foreign keys for uploaded_by_user_id and reviewed_by_user_id are in
-- section 9.)

-- ------------------------------------------------------------------------------
-- 5. REJECTION CATEGORY FOR A FAILED EVALUATION
--
-- APPENDED to the end of the list, never inserted in the middle. MySQL and TiDB
-- store an ENUM as a number counting from the left, so reordering the values
-- would silently re-label every rejection already on record.
-- ------------------------------------------------------------------------------
ALTER TABLE applications
    MODIFY COLUMN rejection_category
    ENUM('Invalid Document', 'No Show', 'Withdrawn', 'Other', 'Unsatisfactory Evaluation') NULL;

-- ------------------------------------------------------------------------------
-- 6. DOCUMENT CATALOGUE
--
-- COMPLETION LETTER never existed as anything but a name. The guard makes the
-- delete refuse rather than fail if any application somehow holds one.
--
-- OFFER LETTER is narrowed to PDF. A corrected letter is produced in Word,
-- exported to PDF and uploaded as PDF -- an official letter should not be
-- acceptable as a photograph of itself.
-- ------------------------------------------------------------------------------
DELETE FROM document_types
WHERE type_name = 'COMPLETION LETTER'
  AND doc_type_id NOT IN (SELECT DISTINCT doc_type_id FROM documents);

UPDATE document_types SET allowed_extensions = '.pdf' WHERE type_name = 'OFFER LETTER';

-- ------------------------------------------------------------------------------
-- 7. ARCHIVE
--
-- The signer is stored by NAME, not as a link to users, for the reason the
-- archive already stores every other actor that way: staff leave, accounts are
-- removed, and an archived letter must still say who signed it.
-- ------------------------------------------------------------------------------
ALTER TABLE archived_applications ADD COLUMN IF NOT EXISTS offer_letter_issued_at DATETIME NULL;
ALTER TABLE archived_applications ADD COLUMN IF NOT EXISTS offer_letter_signed_by_name VARCHAR(150) NULL;

-- ------------------------------------------------------------------------------
-- 8. SALUTATION
--
-- The letter prints "Ms./Mr." and the portal picks one. The form offered
-- "Miss." while the letter format says "Ms.", so the two are brought into line
-- and existing records are corrected. Nothing else reads this column.
-- ------------------------------------------------------------------------------
UPDATE students SET salutation = 'Ms.' WHERE salutation IN ('Miss.', 'Miss', 'Ms');

-- ------------------------------------------------------------------------------
-- 9. FOREIGN KEYS
--
-- Gathered here because these are the only statements in the file that cannot
-- be repeated: MySQL and TiDB have no IF NOT EXISTS for a constraint. If you
-- ever need to re-run this migration, delete this section first.
--
-- All four use ON DELETE SET NULL except the signer, which does not: an
-- application whose offer letter was signed keeps pointing at that user, and
-- users are deactivated rather than deleted in this portal.
-- ------------------------------------------------------------------------------
ALTER TABLE users
    ADD CONSTRAINT fk_user_sig_reviewer
    FOREIGN KEY (signature_reviewed_by_user_id) REFERENCES users(user_id)
    ON DELETE SET NULL;

ALTER TABLE applications
    ADD CONSTRAINT fk_app_offer_signer
    FOREIGN KEY (offer_letter_signed_by_user_id) REFERENCES users(user_id);

ALTER TABLE documents
    ADD CONSTRAINT fk_doc_uploader
    FOREIGN KEY (uploaded_by_user_id) REFERENCES users(user_id)
    ON DELETE SET NULL;

ALTER TABLE documents
    ADD CONSTRAINT fk_doc_reviewer
    FOREIGN KEY (reviewed_by_user_id) REFERENCES users(user_id)
    ON DELETE SET NULL;

-- ==============================================================================
-- VERIFICATION -- runs automatically. Check each result below.
-- ==============================================================================

-- Expect 5 rows: the signature paperwork columns.
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dmrc_internship_portal' AND TABLE_NAME = 'users'
  AND COLUMN_NAME LIKE 'signature_%'
ORDER BY ORDINAL_POSITION;

-- Expect 6 rows: 3 offer letter + 3 handover.
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dmrc_internship_portal' AND TABLE_NAME = 'applications'
  AND (COLUMN_NAME LIKE 'offer_letter_%' OR COLUMN_NAME LIKE 'hardcopy_%' OR COLUMN_NAME = 'handover_completed_at')
ORDER BY ORDINAL_POSITION;

-- Expect 5 rows, and is_pending_approval MUST read YES under IS_NULLABLE.
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dmrc_internship_portal' AND TABLE_NAME = 'documents'
  AND COLUMN_NAME IN ('is_pending_approval', 'uploaded_by_user_id', 'reviewed_by_user_id', 'reviewed_at', 'approval_remarks')
ORDER BY ORDINAL_POSITION;

-- Expect both uq_doc_current and uq_doc_pending, each across 3 columns.
SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_covered
FROM INFORMATION_SCHEMA.STATISTICS
WHERE TABLE_SCHEMA = 'dmrc_internship_portal' AND TABLE_NAME = 'documents'
  AND INDEX_NAME IN ('uq_doc_current', 'uq_doc_pending')
GROUP BY INDEX_NAME;

-- Expect the 5 rejection categories, ending in 'Unsatisfactory Evaluation'.
SELECT COLUMN_TYPE AS rejection_categories
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dmrc_internship_portal' AND TABLE_NAME = 'applications'
  AND COLUMN_NAME = 'rejection_category';

-- Expect 10 document types, no COMPLETION LETTER, OFFER LETTER limited to .pdf.
SELECT COUNT(*) AS document_types_total FROM document_types;
SELECT type_name, allowed_extensions, is_system_generated, is_core
FROM document_types ORDER BY doc_type_id;

-- Expect 0. Any row here is a candidate whose title never made it across.
SELECT COUNT(*) AS salutations_not_migrated
FROM students WHERE salutation IN ('Miss.', 'Miss', 'Ms');
-- ==============================================================================
