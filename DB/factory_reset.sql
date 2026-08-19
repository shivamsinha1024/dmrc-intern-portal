-- ==============================================================================
-- FACTORY RESET
--
-- Returns the portal to a freshly-installed state: no applications, no cycles,
-- no uploaded documents, no audit history. The system is left exactly as it is
-- after running Intern_Portal.sql and seed_dev_data.sql, ready to initialise a
-- cycle from scratch.
--
--   python3 run_sql.py ../DB/factory_reset.sql
--
-- ------------------------------------------------------------------------------
-- UPDATED FOR THE COLLEGE REFERRALS PIPELINE
--
-- The `college_referral_drafts` table no longer exists -- migration 01 dropped
-- it. College referrals are ordinary `applications` rows from the moment of
-- intake, so they are cleared by the applications delete below and need no
-- separate statement. The old DELETE against that table would now abort this
-- script partway through with "Table doesn't exist", leaving the reset
-- half-finished.
--
-- The file-cleanup list has also gained `protected_documents/`, which is where
-- every referrer- and HR-uploaded document is now stored.
--
-- ------------------------------------------------------------------------------
-- CLEARED
--   applications, students, academic_details, documents, joining_details
--   application_status_history, application_document_requirements
--   notifications, system_audit_logs, application_drafts
--   archived_applications, archived_academic_details, archived_documents,
--   archived_status_history, archived_document_requirements
--   internship_cycles  AND its capacities, joining dates, sub-department and
--                      document-requirement rows
--
-- PRESERVED
--   roles, users, employees      -- your dashboard logins keep working
--   departments                  -- organisational structure
--
-- REBUILT
--   sub_departments              -- restored to the standard 19 (see below)
--   document_types               -- rebuilt to the default catalogue
--   document_types               -- rebuilt to the default catalogue (see below)
--
-- ------------------------------------------------------------------------------
-- FILES ON DISK ARE NOT DELETED BY SQL. From the Back End folder:
--
--     rm -rf protected_documents/*      <-- uploaded documents live HERE now
--     rm -rf generated_documents/*      <-- offer letters and certificates
--     rm -rf media/intern_documents/*   <-- legacy location, clear it too
--     rm -rf media/draft_documents/*
--     rm -rf media/generated_docs/*     <-- legacy location, clear it too
--     rm -rf quarantine/*
--
-- NOT deleted: signatures/ . Those belong to your HR-APP accounts, which this
-- script preserves, and an officer should not have to re-upload a signature
-- and wait for approval again just because the application data was cleared.
--
-- ------------------------------------------------------------------------------
-- THIS IS IRREVERSIBLE. Back up first if anything matters:
--
--     python3 -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','dmrc_core.settings');django.setup();from django.core.management import call_command;call_command('dumpdata','portal',output='backup.json')"
-- ==============================================================================

USE dmrc_internship_portal;

-- ------------------------------------------------------------------------------
-- 1. APPLICATION DATA  (children first, so no foreign key is ever violated)
--
-- This clears employee referrals and college referrals alike. An institutional
-- record is an ordinary applications row carrying referral_source =
-- 'Institutional', so it is removed here along with everything else.
-- ------------------------------------------------------------------------------
-- The archive, including the timeline and requirement records added for
-- hard-close. Without these two the reset would leave orphaned timelines and
-- requirement rows pointing at applications that no longer exist -- invisible
-- in the interface, but they would surface in any later archive query.
DELETE FROM archived_status_history;
DELETE FROM archived_document_requirements;
DELETE FROM archived_documents;
DELETE FROM archived_academic_details;
DELETE FROM archived_applications;

DELETE FROM application_document_requirements;
DELETE FROM application_status_history;
DELETE FROM notifications;
DELETE FROM documents;
DELETE FROM joining_details;
DELETE FROM academic_details;

DELETE FROM applications;
DELETE FROM students;

DELETE FROM application_drafts;

DELETE FROM system_audit_logs;

-- ------------------------------------------------------------------------------
-- 2. CYCLE CONFIGURATION
--
-- Deleted explicitly rather than relying on ON DELETE CASCADE, so the order is
-- visible and the script behaves identically on any engine.
-- ------------------------------------------------------------------------------
DELETE FROM cycle_document_requirements;
DELETE FROM cycle_joining_dates;
DELETE FROM cycle_sub_departments;
DELETE FROM cycle_department_capacities;
DELETE FROM internship_cycles;

-- ------------------------------------------------------------------------------
-- 2b. SUB-DEPARTMENTS
--
-- Restored to DMRC's standard 19. Anything a SYS-ADMIN added afterwards is
-- removed, which is the point of a factory reset: the system comes back as
-- shipped, not as somebody left it.
--
-- Safe to delete outright at this point because everything that could reference
-- a sub-department -- joining_details and cycle_sub_departments -- has already
-- been cleared above. Doing this any earlier would violate a foreign key.
--
-- CPM 2 to 6 are FIVE separate units. They were once seeded as a single row
-- reading 'CPM-2,3,4,5,6', so an intern could only be posted to all five at
-- once and the offer letter printed that string as their posting.
-- ------------------------------------------------------------------------------
DELETE FROM sub_departments;
ALTER TABLE sub_departments AUTO_INCREMENT = 1;

INSERT INTO sub_departments (sub_department_name) VALUES
('GM/LEGAL'), ('GM/PB'), ('GM/FINANCE'), ('CGM/TRACTION'), ('ED/FINANCE'),
('GM/HR/O&M'), ('AGM/HR/P'),
-- CPM 2 to 6 are FIVE separate units, not one. They were seeded as a single
-- row reading 'CPM-2,3,4,5,6', so an intern could only ever be posted to all
-- five at once and the offer letter printed that string as their posting.
('CPM - 2'), ('CPM - 3'), ('CPM - 4'), ('CPM - 5'), ('CPM - 6'),
('GM/E&M'), ('GM/SIGNALLING'), ('GM/TELECOM'), ('ED/S&T/R&D'), ('ED/IT'),
('ED/RS/O&M'), ('GM/OPERATIONS');

-- ------------------------------------------------------------------------------
-- 3. DOCUMENT CATALOGUE
--
-- Rebuilt so the five applicant documents are the default set. The remaining
-- types stay in the catalogue because the system needs them: Offer Letter and
-- the certificates are generated, Annexure B and the DMRA Exemption Letter are
-- collected during the internship, and Mentor's Evaluation belongs to the
-- clearance stage. None of them are offered to applicants -- a SYS-ADMIN adds
-- whichever are wanted during cycle initialisation or from Edit Ruleset.
-- ------------------------------------------------------------------------------
DELETE FROM document_types;
ALTER TABLE document_types AUTO_INCREMENT = 1;

-- The five CORE documents. is_core = TRUE protects them from deletion: an
-- administrator may disable and re-enable them, never remove them, because
-- historical applications and the archive assume they can exist.
--
-- AADHAR Card carries requires_consent = TRUE. The consent checkbox AND the
-- Aadhaar number field both follow that flag, so disabling the document
-- removes all three together with no special-casing in code.
INSERT INTO document_types (type_name, allowed_extensions, is_system_generated, is_active, is_core, requires_consent) VALUES
('PASSPORT PHOTO',           '.jpg,.jpeg',      FALSE, TRUE, TRUE,  FALSE),
('SIGNATURE',                '.jpg,.jpeg',      FALSE, TRUE, TRUE,  FALSE),
('COLLEGE ID',               '.pdf,.jpg,.jpeg', FALSE, TRUE, TRUE,  FALSE),
('AADHAR CARD',              '.pdf,.jpg,.jpeg', FALSE, TRUE, TRUE,  TRUE),
('LETTER OF RECOMMENDATION', '.pdf,.jpg,.jpeg', FALSE, TRUE, TRUE,  FALSE);

-- Registered but NOT core and never offered by default: collected by HR during
-- the internship, at clearance, or generated by the portal. An administrator
-- can add any of these to a cycle by name from the wizard or Edit Ruleset.
--
-- OFFER LETTER is PDF only: it is generated as a PDF, and a corrected version
-- is produced in Word, exported to PDF and uploaded as PDF.
--
-- COMPLETION LETTER has been removed from the catalogue. It was a name and
-- nothing else -- never generated, never uploaded, never read.
INSERT INTO document_types (type_name, allowed_extensions, is_system_generated, is_active, is_core, requires_consent) VALUES
('ANNEXURE B',              '.pdf',            FALSE, TRUE, FALSE, FALSE),
('MENTOR''S EVALUATION',    '.pdf,.jpg,.jpeg', FALSE, TRUE, FALSE, FALSE),
('DMRA EXEMPTION LETTER',   '.pdf',            FALSE, TRUE, FALSE, FALSE),
('OFFER LETTER',            '.pdf',            TRUE,  TRUE, FALSE, FALSE),
('COMPLETION CERTIFICATE',  '.pdf,.jpg,.jpeg', TRUE,  TRUE, FALSE, FALSE);

-- ------------------------------------------------------------------------------
-- 4. RESTART NUMBERING
--
-- These affect internal row ids only. TICKET numbers are not stored as counters:
-- each is derived from the highest application_code already issued for its
-- cycle, checked across both the live and archived tables. Both are now empty
-- and every cycle has been removed, so the next cycle's first ticket is
-- DMRC-<year><S|W>-001 with no further action needed.
--
-- TiDB may decline to LOWER an auto-increment counter. That is harmless here --
-- these ids are internal and never shown to anyone.
-- ------------------------------------------------------------------------------
ALTER TABLE applications        AUTO_INCREMENT = 90001;
ALTER TABLE students            AUTO_INCREMENT = 1;
ALTER TABLE internship_cycles   AUTO_INCREMENT = 1;
ALTER TABLE application_drafts  AUTO_INCREMENT = 1;

-- ------------------------------------------------------------------------------
-- 5. VERIFICATION -- runs automatically as the last statements.
--
--   Query 1: every column must read 0.
--   Query 2: your logins and org structure, unchanged.
--   Query 3: exactly 10 document types.
-- ------------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM applications)               AS applications,
  (SELECT COUNT(*) FROM archived_status_history)    AS arch_timeline,
  (SELECT COUNT(*) FROM archived_document_requirements) AS arch_requirements,
  (SELECT COUNT(*) FROM students)                   AS students,
  (SELECT COUNT(*) FROM documents)                  AS documents,
  (SELECT COUNT(*) FROM application_drafts)         AS drafts,
  (SELECT COUNT(*) FROM application_status_history) AS history,
  (SELECT COUNT(*) FROM system_audit_logs)          AS audit,
  (SELECT COUNT(*) FROM archived_applications)      AS archived,
  (SELECT COUNT(*) FROM internship_cycles)          AS cycles;

SELECT
  (SELECT COUNT(*) FROM users)           AS users_kept,
  (SELECT COUNT(*) FROM employees)       AS employees_kept,
  (SELECT COUNT(*) FROM departments)     AS departments_kept,
  (SELECT COUNT(*) FROM sub_departments) AS sub_departments_standard,
  (SELECT COUNT(*) FROM document_types)  AS document_types;
-- ==============================================================================