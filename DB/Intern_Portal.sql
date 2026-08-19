-- ==============================================================================
-- DMRC INTERNSHIP APPLICATION PORTAL - COMPLETE MASTER SCHEMA (FINAL - PHASE 2)
-- Architecture: 3NF Relational Foundation + Dynamic Capacity Engine + Audit Ledger
-- Target Engine: TiDB / MySQL 8.0+
-- Encoding: UTF-8 Unicode (utf8mb4)
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS dmrc_internship_portal
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE dmrc_internship_portal;

-- Every table this script creates must appear below, or re-running the script
-- over an existing database fails partway through with "table already exists".
-- The four archive/draft/requirement tables added by later migrations were
-- missing from this list; they are included now.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS archived_document_requirements;
DROP TABLE IF EXISTS archived_status_history;
DROP TABLE IF EXISTS archived_documents;
DROP TABLE IF EXISTS archived_academic_details;
DROP TABLE IF EXISTS archived_applications;
DROP TABLE IF EXISTS application_document_requirements;
DROP TABLE IF EXISTS application_drafts;
DROP TABLE IF EXISTS system_audit_logs;
DROP TABLE IF EXISTS application_status_history;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS joining_details;
DROP TABLE IF EXISTS cycle_sub_departments;
DROP TABLE IF EXISTS sub_departments;
DROP TABLE IF EXISTS cycle_joining_dates;
DROP TABLE IF EXISTS cycle_document_requirements;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS document_types;
DROP TABLE IF EXISTS academic_details;
DROP TABLE IF EXISTS applications;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS cycle_department_capacities;
DROP TABLE IF EXISTS internship_cycles;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS roles;
SET FOREIGN_KEY_CHECKS = 1;

-- ==============================================================================
-- 1. SYSTEM CONFIGURATION & AUTHENTICATION LAYER
-- ==============================================================================

CREATE TABLE roles (
    role_id INT AUTO_INCREMENT PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL UNIQUE, 
    permissions_level INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE departments (
    department_id INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Global Master Dictionary of all Sub-Departments ever created
CREATE TABLE sub_departments (
    sub_department_id INT AUTO_INCREMENT PRIMARY KEY,
    sub_department_name VARCHAR(100) NOT NULL UNIQUE,
    is_global_active BOOLEAN DEFAULT TRUE 
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mirrors the DMRC employee directory. Every column here must be obtainable
-- from the intranet, since that is where these rows come from. There is
-- deliberately NO salutation: DMRC IT have confirmed the directory does not
-- hold one, so the column could never have been populated.
CREATE TABLE employees (
    employee_id INT AUTO_INCREMENT PRIMARY KEY,
    employee_code VARCHAR(50) NOT NULL UNIQUE, 
    full_name VARCHAR(150) NOT NULL,
    designation VARCHAR(100) NOT NULL,
    department_id INT NOT NULL, 
    official_email VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_emp_dept FOREIGN KEY (department_id) REFERENCES departments(department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    role_id INT NOT NULL,
    employee_id INT NOT NULL UNIQUE, 
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(150) NOT NULL UNIQUE,
    
    -- SIGNATURE AUTHORITY
    --
    -- An HR-APP's signature is stamped onto every offer letter they issue, so
    -- changing one is an administrative act, not a preference:
    --
    --   HR-APP uploads     -> pending_signature_path set, status 'Pending',
    --                         signature_uploaded_at stamped
    --   SYS-ADMIN approves -> pending becomes active, signature_activated_at
    --                         stamped, pending cleared
    --   SYS-ADMIN rejects  -> pending cleared and quarantined, reason recorded
    --
    -- The ACTIVE signature keeps working throughout. An officer waiting on a
    -- decision carries on issuing letters with their existing signature; work
    -- does not stop for an approval.
    --
    -- Signature images are stored under PROTECTED_DOCUMENT_ROOT, never under
    -- MEDIA_ROOT. A signature reachable by URL is a signature that can be
    -- lifted and reused on anything.
    active_signature_path VARCHAR(500) NULL,
    pending_signature_path VARCHAR(500) NULL,
    signature_approval_status ENUM('None', 'Pending', 'Approved', 'Rejected') DEFAULT 'None',
    signature_uploaded_at TIMESTAMP NULL,
    signature_activated_at TIMESTAMP NULL,
    signature_reviewed_at TIMESTAMP NULL,
    signature_reviewed_by_user_id INT NULL,
    -- A SYS-ADMIN must say why when refusing a signature, so there has to be
    -- somewhere to put it.
    signature_rejection_reason TEXT NULL,
    
    is_active BOOLEAN DEFAULT TRUE,
    status_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_role FOREIGN KEY (role_id) REFERENCES roles(role_id),
    CONSTRAINT fk_user_employee FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE,
    -- Self-referencing: the reviewer is another user, always a SYS-ADMIN.
    -- SET NULL because removing an administrator's account must not erase the
    -- record of the decision they took.
    CONSTRAINT fk_user_sig_reviewer FOREIGN KEY (signature_reviewed_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 2. DYNAMIC CYCLE & CAPACITY ENGINE
-- ==============================================================================

CREATE TABLE internship_cycles (
    cycle_id INT AUTO_INCREMENT PRIMARY KEY,
    session_term ENUM('Summer', 'Winter') NOT NULL,
    application_year INT NOT NULL,
    application_start_date DATE NOT NULL,
    application_end_date DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE (session_term, application_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE cycle_department_capacities (
    capacity_id INT AUTO_INCREMENT PRIMARY KEY,
    cycle_id INT NOT NULL,
    department_id INT NOT NULL,
    max_capacity INT NOT NULL,
    seats_occupied INT NOT NULL DEFAULT 0,
    UNIQUE (cycle_id, department_id),
    CONSTRAINT fk_cap_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,
    CONSTRAINT fk_cap_dept FOREIGN KEY (department_id) REFERENCES departments(department_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE cycle_joining_dates (
    date_id INT AUTO_INCREMENT PRIMARY KEY,
    cycle_id INT NOT NULL,
    allowed_doj DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    CONSTRAINT fk_cjd_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,
    UNIQUE (cycle_id, allowed_doj)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Cycle-Specific Sub-Department Mapping (Allows isolation of lists per cycle)
CREATE TABLE cycle_sub_departments (
    mapping_id INT AUTO_INCREMENT PRIMARY KEY,
    cycle_id INT NOT NULL,
    sub_department_id INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    CONSTRAINT fk_csd_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,
    CONSTRAINT fk_csd_subdept FOREIGN KEY (sub_department_id) REFERENCES sub_departments(sub_department_id) ON DELETE CASCADE,
    UNIQUE (cycle_id, sub_department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 3. CORE ENTITIES & STATE ARCHITECTURE
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- STUDENTS
--
-- Most columns are NULLABLE, which is deliberate and load-bearing.
--
-- An employee referral always arrives complete: the Phase-1 form refuses to
-- submit with any field blank. A COLLEGE referral does not. It begins as a
-- preliminary record holding only what the institution actually sent -- a name
-- and an email address, sometimes a mobile number -- and is completed later,
-- once HR corresponds with the candidate.
--
-- Completeness is therefore enforced where it belongs: by the application form
-- on submission, and again by the server before an institutional record may be
-- merged into the main pipeline. Enforcing it here as well would make a
-- half-collected candidate impossible to file at all, which is precisely the
-- state the College Referrals section exists to manage.
--
-- full_name and personal_email stay NOT NULL: both are mandatory on the
-- preliminary intake form, so no record can exist without them.
-- ------------------------------------------------------------------------------
CREATE TABLE students (
    student_id INT AUTO_INCREMENT PRIMARY KEY,
    -- The CANDIDATE's title, typed into the Phase-1 form by the referrer. This
    -- is not the same thing as an employee salutation and is never fetched from
    -- the intranet: the portal collects it, so it can keep it.
    salutation VARCHAR(10) NULL,
    full_name VARCHAR(150) NOT NULL,
    fathers_name VARCHAR(150) NULL,
    gender ENUM('Male', 'Female', 'Other') NULL,
    date_of_birth DATE NULL,
    mobile_number VARCHAR(20) NULL,
    personal_email VARCHAR(150) NOT NULL,
    aadhaar_number VARCHAR(12) NULL,
    permanent_address TEXT NULL,
    emergency_contact_name VARCHAR(150) NULL,
    emergency_contact_mobile VARCHAR(20) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- COLLEGE REFERRALS  (no staging table -- see below)
--
-- An earlier design held institutional candidates in a separate
-- `college_referral_drafts` table until their details were complete. That table
-- has been REMOVED, because two requirements of the finished design cannot be
-- met by a record that is not a real application:
--
--   * a referral rejected before its form is filled must appear in the main
--     pipeline's Rejected list, alongside every other closed application; and
--   * every step -- intake, scheduling, completion, arrival -- must appear on
--     the application timeline and in the audit ledger.
--
-- Both `application_status_history` and `system_audit_logs` are keyed to an
-- application. A record living outside the applications table can have neither
-- a timeline nor a ticket number.
--
-- Institutional candidates are therefore ORDINARY APPLICATIONS from the moment
-- HR files the preliminary form, distinguished by:
--
--     referral_source = 'Institutional'   (no employee referrer exists)
--     status          = 'Intake Draft' -> 'Pending Arrival' -> 'Ready for Merge'
--
-- Those three staging statuses are already part of the applications.status
-- ENUM below. On arrival the record joins the main pipeline at
-- 'Pending Offer Letter' and is thereafter indistinguishable from an employee
-- referral, apart from its permanent institutional marker.
-- ------------------------------------------------------------------------------

-- ------------------------------------------------------------------------------
-- APPLICATION DRAFTS  (server-side, resume-anywhere)
--
-- A draft is partial by definition, so it cannot live in `applications`: that
-- table and `students` require a complete candidate record. Drafts therefore
-- get their own table with a JSON payload, free of NOT NULL constraints that
-- half-filled forms cannot satisfy.
--
-- Ownership is by EMPLOYEE, not by browser session. That is what allows a
-- referrer to start an application on one machine and finish it on another.
--
-- Uploaded files live under MEDIA_ROOT/draft_documents/<draft_id>/ and are
-- referenced from the payload. They are true overwrites: a draft is not part of
-- the audit trail yet, so replacing a file simply deletes the previous one. The
-- versioning rules in `documents` apply only after submission.
--
-- On submission the draft is converted into a real application and deleted.
-- Drafts belonging to a closed cycle are purged automatically.
-- ------------------------------------------------------------------------------
CREATE TABLE application_drafts (
    draft_id INT AUTO_INCREMENT PRIMARY KEY,
    owner_employee_id INT NOT NULL,
    cycle_id INT NULL,
    candidate_name VARCHAR(150) NULL,
    -- Full wizard state: student, academic, placement and document references.
    payload JSON NOT NULL,
    current_step INT NOT NULL DEFAULT 1,
    highest_step INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_draft_owner FOREIGN KEY (owner_employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE,
    CONSTRAINT fk_draft_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,
    INDEX idx_draft_owner (owner_employee_id),
    INDEX idx_draft_cycle (cycle_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE applications (
    application_id INT AUTO_INCREMENT PRIMARY KEY,
    application_code VARCHAR(50) UNIQUE NULL,
    dmrc_reference_code VARCHAR(50) UNIQUE NULL,
    student_id INT NOT NULL,
    referral_source ENUM('Employee', 'Institutional') NOT NULL DEFAULT 'Employee',
    -- NULL for an institutional referral: a college referral has no DMRC
    -- employee standing behind it. The institution named in
    -- academic_details.college_name takes the referrer's place on every screen.
    referrer_employee_id INT NULL,
    referrer_notification_email VARCHAR(150) NULL,
    -- Optional at intake: a college does not always state which department a
    -- candidate is aimed at. Required by the Phase-1 form before submission.
    department_id INT NULL,
    -- cycle_id stays NOT NULL: it is mandatory on the preliminary form, and it
    -- supplies both the ticket series and the list of allowed joining dates.
    cycle_id INT NOT NULL, 
    -- Chosen in the full application form, not at intake. The CHECK below still
    -- refuses any value other than 4, 6 or 8; a CHECK against NULL evaluates to
    -- UNKNOWN, which passes, so a not-yet-chosen duration is accepted.
    duration_weeks INT NULL,
    is_ward BOOLEAN DEFAULT FALSE,
    accepted_declarations BOOLEAN DEFAULT FALSE,
    approved_by_user_id INT NULL, 
    
    form_correction_remarks TEXT NULL,
    -- 'Unsatisfactory Evaluation' closes an internship that was actually served
    -- but failed its mentor's assessment. Without it that person is filed
    -- identically to a candidate rejected months earlier for a bad photograph,
    -- and no report can tell the two apart.
    --
    -- Values are only ever APPENDED to this list. MySQL and TiDB store an ENUM
    -- as a number counting from the left, so inserting a value in the middle
    -- silently re-labels every rejection already on record.
    rejection_category ENUM('Invalid Document', 'No Show', 'Withdrawn', 'Other', 'Unsatisfactory Evaluation') NULL,
    
    approval_reference_id VARCHAR(100) NULL,
    is_admin_escalated BOOLEAN DEFAULT FALSE,

    -- THE MENTOR'S EVALUATION
    --
    -- 'Unsatisfactory' is not a lesser pass. It ends the internship without a
    -- certificate: the certificate's wording is unconditionally complimentary,
    -- and there is no version of it that honestly describes a failed
    -- assessment. The application is rejected instead, under its own category.
    --
    -- The remarks are kept whichever way the result goes. They are the mentor's
    -- own words about someone's work and outlive the decision.
    mentor_evaluation_result ENUM('Satisfactory', 'Unsatisfactory') NULL,
    mentor_evaluation_remarks TEXT NULL,

    -- THE CLEARANCE CHECKLIST
    --
    -- Two physical confirmations and a title. Nothing is uploaded against the
    -- tick-boxes, so the tick IS the record -- which is why it is stored here
    -- rather than left in a browser. project_report_title is printed on the
    -- certificate as the project the intern worked on.
    --
    -- approval_reference_id above is THE FILE NUMBER, typed by HR-OPS at Submit
    -- for Final Review against a physical approval they are holding. Stored and
    -- shown in the drawer, deliberately NOT printed on the certificate.
    attendance_record_verified BOOLEAN NOT NULL DEFAULT FALSE,
    project_report_verified BOOLEAN NOT NULL DEFAULT FALSE,
    project_report_title VARCHAR(255) NULL,
    clearance_submitted_at DATETIME NULL,

    -- CERTIFICATE ISSUANCE
    --
    -- The same three columns as the offer letter, for the same reasons: the
    -- issue date is stored rather than computed so a reprint shows the date it
    -- was signed, and the signature path is frozen at signing so a later change
    -- of signature cannot silently alter a certificate already issued.
    certificate_issued_at DATETIME NULL,
    certificate_signed_by_user_id INT NULL,
    certificate_signature_path VARCHAR(500) NULL,

    -- DISPATCH
    --
    -- certificate_email_status starts at 'Pending'. Dispatching records the
    -- certificate as issued to the candidate with the email OWED, so the
    -- pipeline completes without the portal claiming to have sent a message it
    -- never sent. 'Failed' is here now, unused, so adding delivery later needs
    -- no migration.
    certificate_dispatched_at DATETIME NULL,
    certificate_email_status ENUM('Pending', 'Sent', 'Failed') NULL,
    
    -- OFFER LETTER ISSUANCE
    --
    -- offer_letter_issued_at is the "Dated:" line printed on the letter. It is
    -- STORED rather than computed, so reprinting next month still shows the
    -- date the letter was actually signed.
    --
    -- offer_letter_signature_path freezes the exact signature image used at the
    -- moment of signing. Without it, an officer changing their signature would
    -- silently alter every letter ever reprinted -- including letters signed by
    -- somebody who has since left.
    offer_letter_issued_at DATETIME NULL,
    offer_letter_signed_by_user_id INT NULL,
    offer_letter_signature_path VARCHAR(500) NULL,
    
    -- HANDOVER CONFIRMATION
    --
    -- The two hard-copy declarations HR-OPS collects on the intern's first day
    -- before marking them Joined. These are physical documents: nothing is
    -- uploaded, so the tick IS the record and has to be stored and stamped
    -- rather than left sitting in a browser.
    hardcopy_undertaking_received BOOLEAN NOT NULL DEFAULT FALSE,
    hardcopy_attendance_received BOOLEAN NOT NULL DEFAULT FALSE,
    handover_completed_at DATETIME NULL,
    
    status ENUM(
        'Draft', 'Intake Draft', 'Pending Arrival', 'Ready for Merge',
        'Submitted', 'Under Verification', 'Fix Joining', 
        'Fix Clearance', 'Approved', 'Offer Ready', 'Pending Offer Re-Approval', 'Scheduled', 'Pending Offer Letter', 
        'Joined', 'Pending Certificate', 'Pending Dispatch', 'Completed', 'Rejected'
    ) DEFAULT 'Draft',
    
    is_waitlisted BOOLEAN DEFAULT FALSE,
    is_no_show BOOLEAN DEFAULT FALSE,
    is_resubmitted BOOLEAN DEFAULT FALSE,
    -- TRUE while a Rejected application is parked with the referrer awaiting a
    -- correction or no-show response. Distinguishes a temporary bounce-back
    -- from a final rejection: both carry status='Rejected', so without this the
    -- referrer portal cannot tell an actionable item from a closed one, and
    -- rejection reporting cannot separate the two. Cleared on resubmission.
    awaiting_referrer_action BOOLEAN NOT NULL DEFAULT FALSE,
    doj_reschedule_expires_at TIMESTAMP NULL,
    doj_reschedules_count INT NOT NULL DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP NULL,
    
    CONSTRAINT fk_app_student FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    CONSTRAINT fk_app_employee FOREIGN KEY (referrer_employee_id) REFERENCES employees(employee_id),
    CONSTRAINT fk_app_dept FOREIGN KEY (department_id) REFERENCES departments(department_id),
    CONSTRAINT fk_app_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id),    
    CONSTRAINT fk_app_approver FOREIGN KEY (approved_by_user_id) REFERENCES users(user_id),
    CONSTRAINT fk_app_offer_signer FOREIGN KEY (offer_letter_signed_by_user_id) REFERENCES users(user_id),
    CONSTRAINT fk_app_certificate_signer FOREIGN KEY (certificate_signed_by_user_id) REFERENCES users(user_id),
    CONSTRAINT chk_app_duration CHECK (duration_weeks IN (4, 6, 8)),
    
    INDEX idx_app_status_dept (status, department_id),
    INDEX idx_app_waitlist_status (is_waitlisted, status),
    INDEX idx_app_resubmitted (is_resubmitted),
    INDEX idx_app_awaiting_referrer (awaiting_referrer_action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 4. INTERACTION & LOGISTICS CHILD TABLES
-- ==============================================================================

-- college_name is NOT NULL because the institution is mandatory on the
-- preliminary intake form: for a college referral it stands in place of the
-- employee referrer as the source of the candidate. Everything else here is
-- supplied by the candidate later and is blank until then. See the note on the
-- students table for why completeness is enforced by the form rather than here.
CREATE TABLE academic_details (
    academic_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    university_name VARCHAR(200) NULL,
    college_name VARCHAR(200) NOT NULL,
    degree_program VARCHAR(100) NULL,
    branch_name VARCHAR(100) NULL,
    current_semester VARCHAR(20) NULL,
    grading_system ENUM('CGPA', 'Percentage') NULL DEFAULT 'CGPA',
    current_score DECIMAL(5,2) NULL,
    CONSTRAINT fk_academic_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE document_types (
    doc_type_id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(100) NOT NULL UNIQUE,
    allowed_extensions VARCHAR(100) DEFAULT '.pdf,.jpg,.jpeg',
    max_size_mb INT DEFAULT 2,
    is_system_generated BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    -- Core documents ship with the portal and are always listed in the admin
    -- dashboard. They may be enabled or disabled, never deleted, because the
    -- form, the drawers and the archive all assume they can exist historically.
    is_core BOOLEAN NOT NULL DEFAULT FALSE,
    -- Collecting this document requires the applicant's explicit consent.
    -- Aadhaar is the only one today; the flag exists so a future sensitive
    -- document needs configuration rather than code.
    requires_consent BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE cycle_document_requirements (
    requirement_id INT AUTO_INCREMENT PRIMARY KEY,
    cycle_id INT NOT NULL,
    doc_type_id INT NOT NULL,
    is_mandatory BOOLEAN DEFAULT TRUE,
    CONSTRAINT fk_req_cycle FOREIGN KEY (cycle_id) REFERENCES internship_cycles(cycle_id) ON DELETE CASCADE,
    CONSTRAINT fk_req_doc FOREIGN KEY (doc_type_id) REFERENCES document_types(doc_type_id) ON DELETE CASCADE,
    UNIQUE (cycle_id, doc_type_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- DOCUMENT VAULT (VERSIONED)
--
-- A document is never mutated or deleted in place. Uploading a replacement
-- SUPERSEDES the previous row: the old row is demoted (is_current -> NULL,
-- superseded_at stamped) and a new row is inserted at version + 1.
--
-- Exactly one live document may exist per (application, doc_type). This is
-- enforced by the database, not by convention:
--
--   is_current = 1     -> the single live document for that category
--   is_current = NULL  -> superseded; never returned by any API read path
--
-- The uq_doc_current index relies on standard SQL semantics in which NULL
-- values are considered distinct inside a UNIQUE index. Two live rows would
-- both be (app, type, 1) and collide; any number of superseded rows may
-- coexist as (app, type, NULL). Do NOT change is_current to NOT NULL or
-- default it to 0 -- doing so would allow only one superseded version and
-- break the audit chain.
-- ------------------------------------------------------------------------------
-- ------------------------------------------------------------------------------
-- APPLICATION DOCUMENT REQUIREMENTS  (per-application snapshot)
--
-- An application is judged against the rules in force WHEN IT WAS SUBMITTED,
-- not the rules as they stand today. These rows are copied from the cycle's
-- configuration at submission and never change afterwards.
--
-- This is what makes a dynamic document list safe:
--   * adding a document mid-cycle does not retroactively make submitted
--     applications incomplete;
--   * removing one does not erase what was already collected;
--   * two applications in the same cycle may legitimately carry different
--     document sets, and both still render correctly;
--   * the archive needs no knowledge of historical cycle configuration,
--     because every application carries its own.
--
-- doc_type_name is denormalised on purpose: it survives the deletion of a
-- custom document type, exactly as archived_documents already does.
-- ------------------------------------------------------------------------------
CREATE TABLE application_document_requirements (
    requirement_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    doc_type_id INT NULL,
    doc_type_name VARCHAR(100) NOT NULL,
    allowed_extensions VARCHAR(100) NOT NULL DEFAULT '.pdf,.jpg,.jpeg',
    is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
    requires_consent BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INT NOT NULL DEFAULT 0,
    CONSTRAINT fk_adr_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE,
    CONSTRAINT fk_adr_type FOREIGN KEY (doc_type_id) REFERENCES document_types(doc_type_id) ON DELETE SET NULL,
    UNIQUE (application_id, doc_type_name),
    INDEX idx_adr_app (application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE documents (
    document_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    doc_type_id INT NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    is_current TINYINT(1) NULL DEFAULT 1,
    superseded_at TIMESTAMP NULL,
    is_manually_overridden BOOLEAN DEFAULT FALSE,
    verification_status ENUM('Pending', 'Verified', 'Rejected') NULL DEFAULT 'Pending',
    hr_remarks TEXT NULL,
    
    -- ------------------------------------------------------------------------
    -- THE CORRECTION LOOP  (offer letters, and any future document that must be
    -- approved before it counts)
    --
    -- A corrected offer letter uploaded by HR-OPS must NOT become the official
    -- document until HR-APP approves it. That state is neither current nor
    -- superseded: it cannot be current because it is not official yet, and
    -- calling it superseded would hide it from the approval queue and make it
    -- indistinguishable from the discarded versions underneath it.
    --
    -- So it gets a second flag, using the same NULL-distinctness rule that
    -- uq_doc_current already relies on:
    --
    --     is_pending_approval = 1     awaiting HR-APP's decision (is_current NULL)
    --     is_pending_approval = NULL  everything else
    --
    -- uq_doc_pending then permits at most ONE pending upload per document per
    -- application, enforced by the database rather than by trust: HR-OPS cannot
    -- stack two corrections and leave HR-APP guessing which one is live.
    --
    -- On approval the pending row becomes is_current = 1 and the previous
    -- official row is demoted the usual way. On rejection both flags go NULL,
    -- the mandatory remark is stored in approval_remarks, and the file is moved
    -- to quarantine.
    --
    -- Do NOT give is_pending_approval a DEFAULT of 0 or make it NOT NULL.
    -- Either would allow only one non-pending document in the entire history of
    -- an application, exactly as it would for is_current.
    -- ------------------------------------------------------------------------
    is_pending_approval TINYINT(1) NULL DEFAULT NULL,
    uploaded_by_user_id INT NULL,
    reviewed_by_user_id INT NULL,
    reviewed_at TIMESTAMP NULL,
    -- HR-APP's mandatory reason when sending a corrected letter back. Kept
    -- apart from hr_remarks, which belongs to document VERIFICATION during the
    -- Phase-1 check and answers a different question.
    approval_remarks TEXT NULL,
    
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_doc_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE,
    CONSTRAINT fk_doc_type FOREIGN KEY (doc_type_id) REFERENCES document_types(doc_type_id),
    CONSTRAINT fk_doc_uploader FOREIGN KEY (uploaded_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL,
    CONSTRAINT fk_doc_reviewer FOREIGN KEY (reviewed_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL,
    UNIQUE KEY uq_doc_current (application_id, doc_type_id, is_current),
    UNIQUE KEY uq_doc_pending (application_id, doc_type_id, is_pending_approval)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE joining_details (
    joining_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT UNIQUE NOT NULL,
    -- An employee referrer REQUESTS a joining date. A college referral has no
    -- such request: HR allots the date directly, so this stays NULL and
    -- allotted_date_of_joining is the operative field.
    requested_doj DATE NULL,
    allotted_date_of_joining DATE NULL,
    allotted_sub_department_id INT NULL,
    reporting_time TIME NULL,
    reporting_officer_id INT NULL, 
    assigned_room_location VARCHAR(100) NULL,
    documents_to_carry TEXT NULL, 
    actual_date_of_joining DATE NULL,
    dmra_session_date DATE NULL,
    dmra_attended BOOLEAN NULL,
    date_of_completion DATE NULL,
    CONSTRAINT fk_joining_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE,
    CONSTRAINT fk_joining_subdept FOREIGN KEY (allotted_sub_department_id) REFERENCES sub_departments(sub_department_id),
    CONSTRAINT fk_joining_officer FOREIGN KEY (reporting_officer_id) REFERENCES employees(employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 5. OPERATIONS, TRACKING QUEUES & AUDIT LEDGER
-- ==============================================================================

CREATE TABLE application_status_history (
    history_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    changed_by_user_id INT NULL, 
    previous_status VARCHAR(50) NULL,
    new_status ENUM(
        'Draft', 'Intake Draft', 'Pending Arrival', 'Ready for Merge',
        'Submitted', 'Under Verification', 'Fix Joining', 
        'Fix Clearance', 'Approved', 'Offer Ready', 'Pending Offer Re-Approval', 'Scheduled', 'Pending Offer Letter', 
        'Joined', 'Pending Certificate', 'Pending Dispatch', 'Completed', 'Rejected'
    ) NOT NULL,
    remarks TEXT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_hist_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE,
    CONSTRAINT fk_hist_user FOREIGN KEY (changed_by_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE notifications (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NULL, 
    notification_type ENUM(
        'Registration Successful', 'Application Submitted', 'Documents Pending', 
        'Application Approved', 'Application Rejected', 'Joining Schedule', 
        'Completion Approved', 'Reminder', 'Announcement', 
        'Returned for Correction', 'Offer Letter Issued', 'Completion Certificate Issued'
    ) NOT NULL,
    recipient_email VARCHAR(150) NOT NULL,
    subject VARCHAR(150) NOT NULL,
    message TEXT NOT NULL,
    delivery_status ENUM('Pending', 'Sent', 'Failed') DEFAULT 'Pending',
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP NULL,
    CONSTRAINT fk_note_app FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The System Audit Ledger (Immutable)
CREATE TABLE system_audit_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    actor_user_id INT NULL,
    role_name VARCHAR(50) NULL,
    action_type VARCHAR(100) NOT NULL, 
    target_entity_type VARCHAR(50) NOT NULL, 
    target_entity_id INT NOT NULL,
    old_value JSON NULL,
    new_value JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_user FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 6. HISTORICAL COLD STORAGE COMPLIANCE (UPDATED FOR AUDIT SAFETY)
-- ==============================================================================

CREATE TABLE archived_applications (
    archive_id INT AUTO_INCREMENT PRIMARY KEY,
    original_application_id INT NOT NULL,
    application_code VARCHAR(50) NULL,
    dmrc_reference_code VARCHAR(50) NULL,
    student_name VARCHAR(150) NOT NULL,
    student_email VARCHAR(150) NOT NULL,
    student_mobile VARCHAR(20) NULL,
    student_aadhaar VARCHAR(12) NULL,
    college_name VARCHAR(200) NOT NULL,
    -- A college referral rejected before its form was filled is archived with
    -- these fields still empty, so the archive must accept them blank.
    branch_name VARCHAR(100) NULL,
    grading_system VARCHAR(20) NULL DEFAULT 'CGPA',
    current_score DECIMAL(5,2) NULL,
    department_name VARCHAR(100) NULL,
    allotted_sub_department VARCHAR(100) NULL,
    session_term VARCHAR(20) NOT NULL, 
    application_year INT NOT NULL,     
    duration_weeks INT NULL,
    status VARCHAR(50) NOT NULL,
    is_waitlisted BOOLEAN DEFAULT FALSE,
    is_no_show BOOLEAN DEFAULT FALSE,
    is_employee_ward BOOLEAN DEFAULT FALSE,
    
    referral_source VARCHAR(50) NULL,
    referrer_name VARCHAR(150) NULL,
    referrer_employee_code VARCHAR(50) NULL,
    referrer_notification_email VARCHAR(150) NULL, -- NEW FIELD FOR EMAIL NOTIFICATIONS
    -- Both dates are kept: a candidate scheduled and then rejected never joined,
    -- so actual is empty while the date they were told to report still matters.
    allotted_date_of_joining DATE NULL,
    actual_date_of_joining DATE NULL,
    dmra_session_date DATE NULL,
    dmra_attended BOOLEAN NULL,
    date_of_completion DATE NULL,
    
    rejection_category VARCHAR(50) NULL,
    
    -- The signer is stored by NAME rather than as a link to users, for the same
    -- reason archived_status_history stores its actors that way: staff leave
    -- and accounts are removed, but an archived letter must still say who
    -- signed it.
    offer_letter_issued_at DATETIME NULL,
    offer_letter_signed_by_name VARCHAR(150) NULL,

    -- The clearance record and who signed the certificate. Kept by NAME for the
    -- reason every other actor is: staff leave, accounts are removed, and an
    -- archived certificate must still say who signed it.
    mentor_evaluation_result VARCHAR(20) NULL,
    mentor_evaluation_remarks TEXT NULL,
    project_report_title VARCHAR(255) NULL,
    certificate_issued_at DATETIME NULL,
    certificate_signed_by_name VARCHAR(150) NULL,
    
    approval_reference_id VARCHAR(100) NULL,
    is_admin_escalated BOOLEAN DEFAULT FALSE,
    
    is_resubmitted BOOLEAN DEFAULT FALSE,
    doj_reschedule_expires_at TIMESTAMP NULL,
    doj_reschedules_count INT NOT NULL DEFAULT 0,
    
    archived_year INT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Explicitly defining these rather than using "LIKE" to decouple live foreign keys
CREATE TABLE archived_academic_details (
    archive_academic_id INT AUTO_INCREMENT PRIMARY KEY,
    original_application_id INT NOT NULL,
    university_name VARCHAR(200) NULL,
    college_name VARCHAR(200) NOT NULL,
    degree_program VARCHAR(100) NULL,
    branch_name VARCHAR(100) NULL,
    current_semester VARCHAR(20) NULL,
    grading_system VARCHAR(20) NULL,
    current_score DECIMAL(5,2) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Uploaded files STAY on disk under PROTECTED_DOCUMENT_ROOT when a cycle is
-- archived; only the paths are copied here. Moving thousands of files is a
-- large operation that can half-fail, and buys nothing -- the folder is already
-- outside the web root and unreachable by URL.
--
-- original_document_id lets the secure viewer resolve a link after the live
-- `documents` row has been deleted; without it every archived document would
-- return "not found".
CREATE TABLE archived_documents (
    archive_doc_id INT AUTO_INCREMENT PRIMARY KEY,
    original_application_id INT NOT NULL,
    original_document_id INT NULL,
    application_code VARCHAR(50) NULL,
    doc_type_name VARCHAR(100) NOT NULL, 
    file_path VARCHAR(500) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    is_manually_overridden BOOLEAN DEFAULT FALSE,
    is_system_generated BOOLEAN NOT NULL DEFAULT FALSE,
    verification_status VARCHAR(50) NULL,
    hr_remarks TEXT NULL,
    uploaded_at TIMESTAMP NOT NULL,
    INDEX idx_arch_doc_original (original_document_id),
    INDEX idx_arch_doc_code (application_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- ARCHIVED TIMELINE
--
-- Hard-closing a cycle DELETES its applications, and application_status_history
-- is ON DELETE CASCADE -- so without this table archiving would destroy the
-- timeline. For a college referral rejected before its form was ever filled the
-- timeline is the ONLY record of what happened: that application has no
-- documents and no academic details, just a name and an outcome.
--
-- The actor is stored by NAME and ROLE rather than as a link to users: staff
-- leave and accounts are removed, but an archived decision must still say who
-- took it. new_status is VARCHAR rather than an ENUM so that adding or renaming
-- a status in a later version cannot make old records unreadable.
-- ------------------------------------------------------------------------------
CREATE TABLE archived_status_history (
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

-- ------------------------------------------------------------------------------
-- ARCHIVED DOCUMENT REQUIREMENTS
--
-- What each application was ASKED to supply, as frozen at submission. Without
-- it the archive cannot distinguish "this cycle never asked for a
-- recommendation letter" from "it was asked for and the candidate declined" --
-- both look like an absent file.
--
-- The Phase-1 form refuses to submit while a MANDATORY document is missing, so
-- this is not about missing mandatory documents. It is about optional documents
-- that were declined, and about college referrals rejected before any documents
-- were ever requested.
--
-- Stores the document NAME, never a link: the type may since have been
-- disabled, reconfigured or deleted, and none of that may alter the record of
-- what this candidate was asked for.
-- ------------------------------------------------------------------------------
CREATE TABLE archived_document_requirements (
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

-- ==============================================================================
-- 7. SYSTEM SEEDING & INITIALIZATION
-- ==============================================================================

INSERT INTO roles (role_name, permissions_level) VALUES 
('SYS-ADMIN', 5), 
('HR-APP', 4),
('HR-OPS', 3);

-- Upper case, consistent with sub_departments and with every field the portal
-- displays. These names are matched exactly when an application is filed, and
-- the form's department list is populated from this table, so both sides move
-- together.
INSERT INTO departments (department_name) VALUES 
('CIVIL'), ('MECHANICAL/RS'), ('ELECTRICAL'), ('IT'),
('S&T'), ('FINANCE'), ('HR'), ('LEGAL');

-- Official DMRC post designations, supplied by HR. Stored in UPPER CASE like
-- every other field in this portal; the punctuation is part of the name and is
-- preserved exactly.
INSERT INTO sub_departments (sub_department_name) VALUES
('GM/LEGAL'), ('GM/PB'), ('GM/FINANCE'), ('CGM/TRACTION'), ('ED/FINANCE'),
('GM/HR/O&M'), ('AGM/HR/P'),
-- CPM 2 to 6 are FIVE separate units, not one. They were seeded as a single
-- row reading 'CPM-2,3,4,5,6', so an intern could only ever be posted to all
-- five at once and the offer letter printed that string as their posting.
('CPM - 2'), ('CPM - 3'), ('CPM - 4'), ('CPM - 5'), ('CPM - 6'),
('GM/E&M'), ('GM/SIGNALLING'), ('GM/TELECOM'), ('ED/S&T/R&D'), ('ED/IT'),
('ED/RS/O&M'), ('GM/OPERATIONS');

-- The five DEFAULT applicant documents, in the order the applicant sees them.
-- These are what a new cycle starts with; a SYS-ADMIN may add others during
-- cycle initialisation or later from Edit Ruleset.
INSERT INTO document_types (type_name, allowed_extensions, is_system_generated, is_core, requires_consent) VALUES 
('PASSPORT PHOTO',           '.jpg,.jpeg',      FALSE, TRUE, FALSE),
('SIGNATURE',                '.jpg,.jpeg',      FALSE, TRUE, FALSE),
('COLLEGE ID',               '.pdf,.jpg,.jpeg', FALSE, TRUE, FALSE),
-- Aadhaar carries a consent requirement, so the checkbox appears with it and
-- disappears when it is disabled -- no special-casing anywhere in the code.
('AADHAR CARD',              '.pdf,.jpg,.jpeg', FALSE, TRUE, TRUE),
('LETTER OF RECOMMENDATION', '.pdf,.jpg,.jpeg', FALSE, TRUE, FALSE);

-- Available to the system but NEVER offered to applicants by default:
-- collected during the internship, at clearance, or generated by the portal.
-- OFFER LETTER is PDF only. It is generated as a PDF, and a corrected version
-- is produced in Word, exported to PDF and uploaded as PDF -- an official
-- letter should not be acceptable as a photograph of itself.
--
-- There is no COMPLETION LETTER. It appeared here as a name only: nothing ever
-- generated one, uploaded one or read one.
INSERT INTO document_types (type_name, allowed_extensions, is_system_generated) VALUES 
('ANNEXURE B', '.pdf', FALSE),
('MENTOR''S EVALUATION', '.pdf,.jpg,.jpeg', FALSE),
('DMRA EXEMPTION LETTER', '.pdf', FALSE),
('OFFER LETTER', '.pdf', TRUE),
('COMPLETION CERTIFICATE', '.pdf,.jpg,.jpeg', TRUE);

-- ==============================================================================
-- 8. CASCADE ANALYTICAL REPORT VIEWS
-- ==============================================================================

CREATE OR REPLACE VIEW vw_hr_student_master_list AS
SELECT 
    a.application_id AS id, s.full_name, s.personal_email AS email, s.mobile_number, 
    ac.college_name, ac.branch_name AS branch, 'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name 
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN academic_details ac ON a.application_id = ac.application_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
UNION ALL
SELECT 
    original_application_id AS id, student_name AS full_name, student_email AS email, student_mobile AS mobile_number, 
    college_name, branch_name AS branch, 'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name 
FROM archived_applications;

CREATE OR REPLACE VIEW vw_hr_college_analytics AS
SELECT 
    ac.college_name, a.application_id, s.full_name, ac.branch_name AS branch, ac.current_score AS score, ac.grading_system, 
    'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name 
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN academic_details ac ON a.application_id = ac.application_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
UNION ALL
SELECT 
    college_name, original_application_id AS application_id, student_name AS full_name, branch_name AS branch, current_score AS score, grading_system, 
    'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name 
FROM archived_applications;

CREATE OR REPLACE VIEW vw_hr_internship_analytics AS
SELECT 
    d.department_name, sd.sub_department_name, a.application_id, s.full_name, a.duration_weeks, 
    'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name 
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN departments d ON a.department_id = d.department_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
LEFT JOIN joining_details j ON a.application_id = j.application_id
LEFT JOIN sub_departments sd ON j.allotted_sub_department_id = sd.sub_department_id
UNION ALL
SELECT 
    department_name, allotted_sub_department AS sub_department_name, original_application_id AS application_id, student_name AS full_name, duration_weeks, 
    'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name 
FROM archived_applications;

CREATE OR REPLACE VIEW vw_hr_application_status_tracker AS
SELECT 
    a.application_id AS id, s.full_name, a.status, a.referral_source, a.is_waitlisted, a.is_no_show, 
    a.is_ward AS is_employee_ward, a.is_resubmitted, 
    a.doj_reschedule_expires_at, a.doj_reschedules_count, 
    a.referrer_notification_email, 
    d.department_name, a.created_at, 
    'Live' AS record_source, ic.application_year AS report_year, ic.session_term AS cycle_name 
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN departments d ON a.department_id = d.department_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
UNION ALL
SELECT 
    original_application_id AS id, student_name AS full_name, status, referral_source, is_waitlisted, is_no_show, 
    is_employee_ward, is_resubmitted, 
    doj_reschedule_expires_at, doj_reschedules_count, 
    referrer_notification_email, 
    department_name, created_at, 
    'Archived' AS record_source, archived_year AS report_year, session_term AS cycle_name 
FROM archived_applications;

CREATE OR REPLACE VIEW vw_hr_completion_report AS
SELECT 
    a.application_id AS id, s.full_name, d.department_name, a.duration_weeks,
    j.actual_date_of_joining, j.date_of_completion, 
    (EXISTS (
        SELECT 1 FROM documents doc 
        JOIN document_types dt ON doc.doc_type_id = dt.doc_type_id 
        WHERE doc.application_id = a.application_id AND dt.type_name = 'MENTOR''S EVALUATION'
    )) AS is_evaluation_uploaded, 
    (EXISTS (
        SELECT 1 FROM documents doc 
        JOIN document_types dt ON doc.doc_type_id = dt.doc_type_id 
        WHERE doc.application_id = a.application_id AND dt.type_name = 'ANNEXURE B'
    )) AS is_annexure_b_uploaded,
    a.status,
    ic.application_year AS report_year, ic.session_term AS cycle_name 
FROM applications a
JOIN students s ON a.student_id = s.student_id
JOIN departments d ON a.department_id = d.department_id
JOIN internship_cycles ic ON a.cycle_id = ic.cycle_id
LEFT JOIN joining_details j ON a.application_id = j.application_id
WHERE a.status IN ('Joined', 'Fix Clearance', 'Pending Certificate', 'Completed')
UNION ALL
SELECT 
    original_application_id AS id, student_name AS full_name, department_name, duration_weeks,
    actual_date_of_joining, date_of_completion, 
    1 AS is_evaluation_uploaded, 1 AS is_annexure_b_uploaded, status,
    archived_year AS report_year, session_term AS cycle_name 
FROM archived_applications
WHERE status IN ('Joined', 'Fix Clearance', 'Pending Certificate', 'Completed');