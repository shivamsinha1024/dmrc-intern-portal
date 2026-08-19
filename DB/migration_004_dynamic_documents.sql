-- ==============================================================================
-- MIGRATION 004 : DYNAMIC DOCUMENT CONFIGURATION
--
-- Makes the document list genuinely configurable. Until now the five documents
-- were hardcoded through the whole stack: adding one in the admin dashboard
-- stored a row and changed nothing else.
--
--   python3 run_sql.py ../DB/migration_004_dynamic_documents.sql
--
-- ------------------------------------------------------------------------------
-- WHAT THIS ADDS
--
-- 1. document_types.is_core
--       The five shipped documents. Always listed in the admin dashboard, can
--       be enabled or disabled, never deleted -- historical applications and
--       the archive assume they can exist.
--
-- 2. document_types.requires_consent
--       Collecting this document needs the applicant's explicit consent.
--       Seeded TRUE for Aadhaar only. The consent checkbox and the Aadhaar
--       number field both follow this flag, so disabling the document removes
--       all three together with no special-casing in code.
--
-- 3. application_document_requirements
--       A per-application SNAPSHOT of the document rules, frozen at submission.
--       An application is judged against the rules in force when it was
--       submitted, not the rules as they stand today. This is what makes
--       mid-cycle changes safe -- see the table comment in Intern_Portal.sql.
--
-- 4. Drops cycle_document_requirements.required_at
--       Every configured document is collected in the Phase 1 form. The
--       Application/Clearance distinction was configurable but nothing in
--       Phase 2 ever consumed it, so the control did nothing.
--
-- ------------------------------------------------------------------------------
-- SAFE ON A POPULATED DATABASE
--
-- Additive except for the required_at drop, which removes a column nothing
-- reads. Existing applications get no snapshot rows; the backend falls back to
-- the cycle configuration for those, so nothing breaks retrospectively.
--
-- Statements are separate because TiDB rejects combined column-and-index
-- changes in one ALTER. Re-running fails harmlessly with "Duplicate column".
-- ==============================================================================

USE dmrc_internship_portal;

-- ------------------------------------------------------------------------------
-- STEP 1 : document_types flags
-- ------------------------------------------------------------------------------
ALTER TABLE document_types
    ADD COLUMN is_core BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE document_types
    ADD COLUMN requires_consent BOOLEAN NOT NULL DEFAULT FALSE;

-- The five shipped documents become protected.
UPDATE document_types
   SET is_core = TRUE
 WHERE type_name IN ('Passport Photo', 'Signature', 'College ID',
                     'AADHAR Card', 'Letter of Recommendation');

-- Aadhaar is the only document requiring explicit consent today.
UPDATE document_types
   SET requires_consent = TRUE
 WHERE type_name = 'AADHAR Card';

-- ------------------------------------------------------------------------------
-- STEP 2 : the per-application snapshot
-- ------------------------------------------------------------------------------
CREATE TABLE application_document_requirements (
    requirement_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,

    -- NULL once a custom document type is deleted. doc_type_name below keeps
    -- the record readable, exactly as archived_documents already does.
    doc_type_id INT NULL,
    doc_type_name VARCHAR(100) NOT NULL,

    allowed_extensions VARCHAR(100) NOT NULL DEFAULT '.pdf,.jpg,.jpeg',
    is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
    requires_consent BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INT NOT NULL DEFAULT 0,

    CONSTRAINT fk_adr_app FOREIGN KEY (application_id)
        REFERENCES applications(application_id) ON DELETE CASCADE,
    CONSTRAINT fk_adr_type FOREIGN KEY (doc_type_id)
        REFERENCES document_types(doc_type_id) ON DELETE SET NULL,
    UNIQUE (application_id, doc_type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE application_document_requirements
    ADD INDEX idx_adr_app (application_id);

-- ------------------------------------------------------------------------------
-- STEP 3 : retire the unused phase column
-- ------------------------------------------------------------------------------
ALTER TABLE cycle_document_requirements
    DROP COLUMN required_at;

-- ------------------------------------------------------------------------------
-- VERIFICATION
--   SELECT type_name, is_core, requires_consent, is_active
--     FROM document_types ORDER BY doc_type_id;
--     -> the five defaults show is_core = 1, Aadhaar shows requires_consent = 1
--
--   DESCRIBE application_document_requirements;   -> 8 columns
--   DESCRIBE cycle_document_requirements;         -> no required_at
-- ==============================================================================
