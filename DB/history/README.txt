DEVELOPMENT SCHEMA HISTORY -- DO NOT RUN THESE FILES
==============================================================================

These eight files record how the database schema evolved during development.
They were applied one at a time to a development database that already existed.

EVERY CHANGE THEY MAKE IS ALREADY PRESENT IN ../Intern_Portal.sql.

On a new installation, run ../Intern_Portal.sql and nothing else. These files
are kept for reference only -- so that a future maintainer can see why a column
exists and what problem it solved.

WHAT HAPPENS IF THEY ARE RUN ANYWAY
------------------------------------------------------------------------------
  migration_05_offer_letters.sql
      FAILS ON MYSQL. It uses ADD COLUMN IF NOT EXISTS and
      CREATE INDEX IF NOT EXISTS, which are TiDB extensions that plain MySQL
      does not support. 19 statements are affected.

  migration_04_sub_departments.sql
      DELETES ROWS. It clears cycle_sub_departments and sub_departments before
      re-inserting them. Harmless on an empty database, destructive on one that
      holds live cycle configuration.

  the remaining six
      Fail with duplicate-column and duplicate-table errors, because the master
      script already contains everything they add.

FILES
------------------------------------------------------------------------------
  migration_01_college_referrals.sql          relaxed NOT NULL for partial
                                              institutional intake records
  migration_02_per_cycle_document_config.sql  moved document configuration from
                                              global to per-cycle
  migration_03_archive_completeness.sql       added archived timeline and
                                              requirements snapshot tables
  migration_04_sub_departments.sql            replaced placeholder units with
                                              official DMRC designations
  migration_002_referrer_bounce_back.sql      added awaiting_referrer_action
  migration_003_application_drafts.sql        moved referrer drafts from browser
                                              storage to the server
  migration_004_dynamic_documents.sql         made the document catalogue
                                              configurable; added consent flag
  migration_05_offer_letters.sql              offer letter issuance, signature
                                              authority, correction loop
==============================================================================
