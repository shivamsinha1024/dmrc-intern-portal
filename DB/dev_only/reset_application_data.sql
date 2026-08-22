-- ==============================================================================
-- RESET APPLICATION DATA  --  CLEAN SLATE
--
-- Deletes every application and everything derived from it, so testing can
-- start from scratch. Configuration and identity are PRESERVED, so there is no
-- need to re-run Intern_Portal.sql or seed_dev_data.sql afterwards.
--
--   python3 run_sql.py ../DB/reset_application_data.sql
--
-- ------------------------------------------------------------------------------
-- CLEARED
--   applications, students, academic_details, documents, joining_details
--   application_status_history, notifications, system_audit_logs
--   archived_* (all six cold-storage tables)
--   cycle_department_capacities.seats_occupied  -> reset to 0
--
-- PRESERVED
--   roles, users, employees          (your three dashboard logins stay working)
--   departments, sub_departments, document_types
--   internship_cycles and its capacity / joining-date / document-requirement rows
--     (the cycle you initialised through the wizard is NOT touched)
--
-- ------------------------------------------------------------------------------
-- IMPORTANT: THIS DOES NOT DELETE UPLOADED FILES
--
-- Documents on disk are not referenced by the database once these rows are
-- gone, so they become orphans. Remove them separately, from the Back End
-- folder:
--
--     rm -rf media/intern_documents/*
--     rm -rf quarantine/*
--
-- ------------------------------------------------------------------------------
-- THIS IS IRREVERSIBLE. Back up first if any of the data matters:
--
--     python3 -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','dmrc_core.settings');django.setup();from django.core.management import call_command;call_command('dumpdata','portal',output='backup.json')"
-- ==============================================================================

USE dmrc_internship_portal;

-- Child rows first, so foreign keys are never violated mid-script and the
-- statements remain readable without disabling integrity checks.

-- THE FULL ARCHIVE, not three tables of six.
--
-- archived_status_history and archived_document_requirements were missing
-- from this script: a reset left every archived timeline and requirement
-- row behind, pointing at applications that no longer existed. Invisible
-- in the interface, but they accumulate with every reset and surface in
-- any later archive query.
--
-- archived_cycle_joining_dates came with the archive rebuild.
DELETE FROM archived_cycle_joining_dates;
DELETE FROM archived_status_history;
DELETE FROM archived_document_requirements;
DELETE FROM archived_documents;
DELETE FROM archived_academic_details;
DELETE FROM archived_applications;

DELETE FROM application_status_history;
DELETE FROM notifications;
DELETE FROM documents;
DELETE FROM joining_details;
DELETE FROM academic_details;

DELETE FROM applications;
DELETE FROM students;
-- college_referral_drafts was NOT cleared here -- the table no longer
-- exists. Migration 01 dropped it: a college referral is an ordinary
-- applications row from the moment of intake, so the delete above already
-- covers it. The statement that stood here aborted this script with
-- "Table doesn't exist", leaving the reset half-finished -- applications
-- and students gone, the audit ledger and seat counters untouched.
-- factory_reset.sql had the same line and was fixed; this file was missed.

-- The global admin ledger. Cleared too, so the audit view starts empty and
-- matches the (now empty) application set.
DELETE FROM system_audit_logs;

-- seats_occupied is a stored counter, not a live COUNT(*). Left untouched it
-- would keep reporting seats as taken and could hold departments at capacity,
-- silently waitlisting new test applications.
UPDATE cycle_department_capacities SET seats_occupied = 0;

-- Restart ticket numbering from a clean base.
ALTER TABLE applications AUTO_INCREMENT = 90001;
ALTER TABLE students AUTO_INCREMENT = 1;

-- ------------------------------------------------------------------------------
-- VERIFICATION -- every count must be 0, and the last query must still show
-- your three dashboard users and the active cycle.
-- ------------------------------------------------------------------------------
-- SELECT
--   (SELECT COUNT(*) FROM applications)              AS applications,
--   (SELECT COUNT(*) FROM students)                  AS students,
--   (SELECT COUNT(*) FROM documents)                 AS documents,
--   (SELECT COUNT(*) FROM application_status_history) AS history,
--   (SELECT COUNT(*) FROM system_audit_logs)         AS audit_logs;
--
-- SELECT
--   (SELECT COUNT(*) FROM users)             AS users_kept,
--   (SELECT COUNT(*) FROM internship_cycles) AS cycles_kept,
--   (SELECT SUM(seats_occupied) FROM cycle_department_capacities) AS seats_in_use;
-- ==============================================================================