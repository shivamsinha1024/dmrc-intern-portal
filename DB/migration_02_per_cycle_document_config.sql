-- =============================================================================
-- DMRC INTERNSHIP PORTAL
-- MIGRATION 02 : PER-CYCLE DOCUMENT CONFIGURATION
-- Target: TiDB Cloud (also valid on MySQL 8.0+)
-- =============================================================================
--
-- WHY
-- ---
-- DMRC runs more than one intake cycle at a time. A document's configuration
-- must therefore belong to the CYCLE, not to the document itself.
--
-- Until now it was split:
--
--     is_mandatory        cycle_document_requirements   per cycle   (correct)
--     is_active           document_types                GLOBAL      (wrong)
--     allowed_extensions  document_types                GLOBAL      (wrong)
--
-- With Winter 2026 and Summer 2027 both open, switching off "Letter of
-- Recommendation" for Summer also removed it from Winter -- silently, because
-- the configuration screen only ever showed one cycle. Every application
-- submitted to Winter after that point stopped being asked for a document
-- Winter still required.
--
-- This migration gives each cycle its own copy of both settings.
--
-- WHAT STAYS GLOBAL, AND WHY
-- --------------------------
-- document_types keeps its own is_active and allowed_extensions. They are no
-- longer what a cycle reads; they are the CATALOGUE DEFAULT applied when a
-- document is first added to a new cycle. document_types continues to own what
-- is genuinely global: the document's name, whether it is core, whether it
-- requires consent, and whether the system generates it.
--
-- SAFETY
-- ------
-- Both columns are added with defaults and then backfilled from the current
-- global values, so every existing cycle keeps exactly the configuration it has
-- today. Nothing changes behaviour on the day this runs.
--
-- Each column is altered in its OWN statement: TiDB refuses a single ALTER
-- TABLE that changes several columns at once.
--
-- This is a plain SQL script, NOT a Django migration. The portal's models are
-- declared `managed = False`. Do not run makemigrations or migrate.
-- =============================================================================

USE dmrc_internship_portal;


-- -----------------------------------------------------------------------------
-- 1. ADD THE PER-CYCLE COLUMNS
--
-- Defaults are deliberately permissive so that any row created between this
-- statement and the backfill below is enabled rather than invisible.
-- -----------------------------------------------------------------------------
ALTER TABLE cycle_document_requirements
    ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE cycle_document_requirements
    ADD COLUMN allowed_extensions VARCHAR(100) NULL;


-- -----------------------------------------------------------------------------
-- 2. BACKFILL FROM THE CURRENT GLOBAL VALUES
--
-- Every cycle inherits exactly what it was effectively using yesterday, so no
-- cycle's document set changes on the day this migration runs.
-- -----------------------------------------------------------------------------
UPDATE cycle_document_requirements r
JOIN document_types d ON d.doc_type_id = r.doc_type_id
SET r.is_enabled         = d.is_active,
    r.allowed_extensions = d.allowed_extensions;


-- -----------------------------------------------------------------------------
-- 3. VERIFICATION -- runs automatically.
--
--   Query 1: mismatches between a cycle's setting and the old global one.
--            Must be 0 immediately after this migration. Once an administrator
--            starts configuring cycles independently it will grow, and that is
--            the entire point.
--   Query 2: every requirement row now carries its own format. no_format must
--            be 0 -- a NULL there would fall back to the global value.
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS rows_differing_from_global
FROM cycle_document_requirements r
JOIN document_types d ON d.doc_type_id = r.doc_type_id
WHERE r.is_enabled <> d.is_active
   OR IFNULL(r.allowed_extensions, '') <> IFNULL(d.allowed_extensions, '');

SELECT
  COUNT(*)                                                    AS requirement_rows,
  SUM(CASE WHEN allowed_extensions IS NULL THEN 1 ELSE 0 END) AS no_format,
  SUM(CASE WHEN is_enabled THEN 1 ELSE 0 END)                 AS enabled_rows
FROM cycle_document_requirements;