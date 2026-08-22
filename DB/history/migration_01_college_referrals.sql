-- =============================================================================
-- DMRC INTERNSHIP PORTAL
-- MIGRATION 01 : COLLEGE REFERRALS PIPELINE
-- Target: TiDB Cloud (also valid on MySQL 8.0+)
-- =============================================================================
--
-- WHAT THIS DOES
-- --------------
-- A college referral begins life as a preliminary record holding only what the
-- institution actually sent: a cycle, a candidate name, a college name and an
-- email address. The rest of the application -- date of birth, Aadhaar, marks,
-- duration, documents -- is collected later, when the candidate corresponds
-- with HR.
--
-- Today the database refuses to store such a record: a dozen columns are
-- declared NOT NULL, so a partially-known candidate cannot be filed at all.
-- This migration relaxes exactly those columns and no others.
--
-- WHAT THIS DOES NOT DO
-- ---------------------
-- It does NOT make the Phase-1 application form any less strict. That form
-- still refuses to submit with a single field left blank, for employee
-- referrals and college referrals alike. Completeness is now checked at the
-- point it actually matters -- when an application is submitted, and again
-- before an institutional record may be merged into the main pipeline --
-- rather than being enforced by the storage layer against records that are
-- legitimately still being assembled.
--
-- In short: blanks stay honestly blank while a record is in the College
-- Referrals section, and nothing incomplete ever escapes it.
--
-- SAFETY
-- ------
-- Every statement below only WIDENS what a column will accept. No data is
-- read, changed or deleted, and every row already stored remains valid.
-- Running it on a database that already holds live applications is safe.
--
-- NOTE ON STATEMENT STYLE
-- -----------------------
-- Each column is altered in its OWN statement. TiDB refuses a single ALTER
-- TABLE that changes several columns at once ("Unsupported multi schema
-- change"), so the verbose form below is deliberate, not an oversight.
--
-- This is a plain SQL script, NOT a Django migration. The portal's models are
-- declared `managed = False`, so Django never creates or alters tables -- the
-- schema is maintained by hand in SQL. Do not run `manage.py makemigrations`
-- or `migrate` for this change; they would do nothing.
-- =============================================================================

USE dmrc_internship_portal;


-- -----------------------------------------------------------------------------
-- 1. STUDENTS
--
-- The preliminary intake form collects a name and an email address, and
-- optionally a mobile number. Everything else about the candidate arrives
-- later, once HR makes contact.
--
-- full_name and personal_email stay NOT NULL: both are mandatory on the
-- preliminary form, so a record can never exist without them.
-- -----------------------------------------------------------------------------
ALTER TABLE students MODIFY COLUMN fathers_name             VARCHAR(150) NULL;
ALTER TABLE students MODIFY COLUMN gender                   ENUM('Male', 'Female', 'Other') NULL;
ALTER TABLE students MODIFY COLUMN date_of_birth            DATE NULL;
ALTER TABLE students MODIFY COLUMN mobile_number            VARCHAR(20) NULL;
ALTER TABLE students MODIFY COLUMN aadhaar_number           VARCHAR(12) NULL;
ALTER TABLE students MODIFY COLUMN permanent_address        TEXT NULL;
ALTER TABLE students MODIFY COLUMN emergency_contact_name   VARCHAR(150) NULL;
ALTER TABLE students MODIFY COLUMN emergency_contact_mobile VARCHAR(20) NULL;


-- -----------------------------------------------------------------------------
-- 2. ACADEMIC DETAILS
--
-- college_name stays NOT NULL: the institution is mandatory on the preliminary
-- form and is what identifies the referral source in place of an employee
-- referrer. Course and branch are optional at intake, and the university,
-- semester and marks are not known until the candidate supplies them.
-- -----------------------------------------------------------------------------
ALTER TABLE academic_details MODIFY COLUMN university_name  VARCHAR(200) NULL;
ALTER TABLE academic_details MODIFY COLUMN degree_program   VARCHAR(100) NULL;
ALTER TABLE academic_details MODIFY COLUMN branch_name      VARCHAR(100) NULL;
ALTER TABLE academic_details MODIFY COLUMN current_semester VARCHAR(20) NULL;
ALTER TABLE academic_details MODIFY COLUMN grading_system   ENUM('CGPA', 'Percentage') NULL DEFAULT 'CGPA';
ALTER TABLE academic_details MODIFY COLUMN current_score    DECIMAL(5,2) NULL;


-- -----------------------------------------------------------------------------
-- 3. APPLICATIONS
--
-- Department is optional on the preliminary form -- a college does not always
-- say which branch a candidate is aimed at -- and the internship duration is
-- chosen later, in the full form.
--
-- cycle_id and student_id remain NOT NULL. The cycle is mandatory at intake
-- (it supplies both the ticket series and the allowed joining dates), and
-- every application must point at a candidate record.
--
-- NOTE ON chk_app_duration: the existing CHECK (duration_weeks IN (4, 6, 8))
-- is left in place and needs no change. In SQL a CHECK against NULL evaluates
-- to UNKNOWN, which passes -- so a blank duration is accepted while a wrong
-- one is still refused.
-- -----------------------------------------------------------------------------
ALTER TABLE applications MODIFY COLUMN department_id  INT NULL;
ALTER TABLE applications MODIFY COLUMN duration_weeks INT NULL;


-- -----------------------------------------------------------------------------
-- 4. JOINING DETAILS
--
-- An employee referrer REQUESTS a joining date when they file the application.
-- For a college referral there is no such request: HR allots the date directly
-- from the cycle's approved calendar. The requested date is therefore absent
-- for institutional records, and the allotted date is the operative one.
-- -----------------------------------------------------------------------------
ALTER TABLE joining_details MODIFY COLUMN requested_doj DATE NULL;


-- -----------------------------------------------------------------------------
-- 5. ARCHIVE TABLES
--
-- A college referral can be rejected before its full form is ever filled --
-- for example when a candidate never sends their documents. When such a record
-- is eventually archived, the fields that were never collected are still
-- empty, so the archive must be able to hold them.
--
-- Without this, archiving a rejected intake would fail outright, and the
-- record would be stuck in the live table permanently.
-- -----------------------------------------------------------------------------
ALTER TABLE archived_applications MODIFY COLUMN student_mobile  VARCHAR(20) NULL;
ALTER TABLE archived_applications MODIFY COLUMN branch_name     VARCHAR(100) NULL;
ALTER TABLE archived_applications MODIFY COLUMN grading_system  VARCHAR(20) NULL DEFAULT 'CGPA';
ALTER TABLE archived_applications MODIFY COLUMN current_score   DECIMAL(5,2) NULL;
ALTER TABLE archived_applications MODIFY COLUMN department_name VARCHAR(100) NULL;
ALTER TABLE archived_applications MODIFY COLUMN duration_weeks  INT NULL;

ALTER TABLE archived_academic_details MODIFY COLUMN university_name  VARCHAR(200) NULL;
ALTER TABLE archived_academic_details MODIFY COLUMN degree_program   VARCHAR(100) NULL;
ALTER TABLE archived_academic_details MODIFY COLUMN branch_name      VARCHAR(100) NULL;
ALTER TABLE archived_academic_details MODIFY COLUMN current_semester VARCHAR(20) NULL;
ALTER TABLE archived_academic_details MODIFY COLUMN grading_system   VARCHAR(20) NULL;
ALTER TABLE archived_academic_details MODIFY COLUMN current_score    DECIMAL(5,2) NULL;


-- -----------------------------------------------------------------------------
-- 6. RETIRE THE UNUSED STAGING TABLE
--
-- college_referral_drafts was an earlier design in which institutional
-- candidates lived in a separate holding table until they were complete. That
-- approach cannot satisfy two requirements of the finished design:
--
--   * a rejected intake must appear in the main pipeline's Rejected list, and
--   * every step must be recorded on the application timeline,
--
-- both of which are keyed to a real application record. Institutional
-- candidates are therefore ordinary applications from the moment of intake,
-- distinguished by referral_source = 'Institutional' and by the three staging
-- statuses already present in the applications.status ENUM.
--
-- The table was never read or written by any code path, so dropping it removes
-- nothing that was ever in use. If you would rather keep it for reference,
-- comment this statement out -- it is inert either way.
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS college_referral_drafts;


-- -----------------------------------------------------------------------------
-- 7. VERIFICATION -- runs automatically as the last statement.
--
-- EVERY row of the result must read YES in the is_nullable column, and there
-- should be 18 rows. Any NO means that particular change did not apply.
-- -----------------------------------------------------------------------------
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'dmrc_internship_portal'
  AND (
        (table_name = 'students'         AND column_name IN ('fathers_name','gender','date_of_birth','mobile_number','aadhaar_number','permanent_address','emergency_contact_name','emergency_contact_mobile'))
     OR (table_name = 'academic_details' AND column_name IN ('university_name','degree_program','branch_name','current_semester','grading_system','current_score'))
     OR (table_name = 'applications'     AND column_name IN ('department_id','duration_weeks'))
     OR (table_name = 'joining_details'  AND column_name IN ('requested_doj'))
      )
ORDER BY table_name, column_name;
