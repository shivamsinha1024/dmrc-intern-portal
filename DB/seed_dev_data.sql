-- ==============================================================================
-- DMRC INTERNSHIP PORTAL - DEVELOPMENT SEED DATA
--
-- Run AFTER Intern_Portal.sql. Creates the minimum set of employees and
-- dashboard accounts needed for the application to run and be demonstrated.
--
--   mysql ... dmrc_internship_portal < seed_dev_data.sql
--
-- ------------------------------------------------------------------------------
-- FOR THE DMRC IT TEAM
--
-- These rows exist only because there is no way to bootstrap the very first
-- SYS-ADMIN through the UI (creating a user requires being logged in as one).
--
-- On the intranet, employee identity comes from the payslip login system, and
-- `employees` becomes a projection of that directory keyed on employee_code.
-- Replace the employee_code, full_name, designation and official_email values
-- below with the real records of the staff who should hold each role, then
-- delete this file. Do NOT ship it to production as-is.
--
-- `users` remains authoritative for AUTHORISATION only: which employee holds
-- which dashboard role. Identity is never stored here -- there are no
-- passwords in this schema by design.
--
-- ------------------------------------------------------------------------------
-- TWO CONVENTIONS THIS FILE FOLLOWS
--
-- 1. NO SALUTATION. The employees table no longer has that column: DMRC IT
--    confirmed the employee directory does not hold one, so it could never be
--    populated for a real member of staff. (The CANDIDATE's title is a separate
--    field on `students`, typed into the Phase-1 form, and is unaffected.)
--
-- 1a. DESIGNATIONS ARE PRINTED. The designation below appears under the
--     signature on every offer letter and completion certificate that employee
--     signs, as "<designation>/HR". Use the short official form DMRC prints --
--     'AM', not 'Assistant Manager'.
--
-- 2. UPPER CASE. Every stored text field is upper case, which is how the portal
--    displays them -- the sole exception being email addresses, where case can
--    matter and which are machine-read rather than scanned. Usernames follow the
--    email convention for the same reason: they are identifiers, not labels.
-- ==============================================================================

USE dmrc_internship_portal;

-- ------------------------------------------------------------------------------
-- EMPLOYEES
-- department_id values reference the departments seeded by Intern_Portal.sql:
--   1 CIVIL | 2 MECHANICAL/RS | 3 ELECTRICAL | 4 IT | 5 S&T | 6 FINANCE
--   7 HR    | 8 LEGAL
-- ------------------------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, designation, department_id, official_email) VALUES
('EMP-OHR-001', 'DIPTI SHARMA',   'HR OPERATIONS EXECUTIVE', 7, 'dipti.sharma@dmrc.org'),
('EMP-AHR-001', 'REENA ARORA',    'AM',                      7, 'reena.arora@dmrc.org'),
('EMP-ADM-001', 'VARUN MALHOTRA', 'SYSTEMS ADMINISTRATOR',   4, 'varun.malhotra@dmrc.org'),
('EMP-4471',    'R. SHARMA',      'SENIOR ENGINEER',         5, 'r.sharma@dmrc.org');

-- ------------------------------------------------------------------------------
-- DASHBOARD ACCOUNTS
-- role_id references the roles seeded by Intern_Portal.sql:
--   1 SYS-ADMIN | 2 HR-APP | 3 HR-OPS
--
-- Note that EMP-4471 (R. SHARMA) intentionally gets NO row here. He is an
-- ordinary employee: able to refer candidates through the Phase 1 portal, but
-- with no access to the HR dashboard. That is the default for all staff.
-- ------------------------------------------------------------------------------
INSERT INTO users (role_id, employee_id, username, email, is_active)
SELECT 3, employee_id, 'dipti.sharma', official_email, TRUE
FROM employees WHERE employee_code = 'EMP-OHR-001';

INSERT INTO users (role_id, employee_id, username, email, is_active)
SELECT 2, employee_id, 'reena.arora', official_email, TRUE
FROM employees WHERE employee_code = 'EMP-AHR-001';

INSERT INTO users (role_id, employee_id, username, email, is_active)
SELECT 1, employee_id, 'varun.malhotra', official_email, TRUE
FROM employees WHERE employee_code = 'EMP-ADM-001';

-- ------------------------------------------------------------------------------
-- VERIFICATION -- runs automatically. Expect exactly three rows, one per role,
-- with names and designations in upper case.
-- ------------------------------------------------------------------------------
SELECT u.username, r.role_name, e.employee_code, e.full_name, e.designation,
       d.department_name
FROM users u
JOIN roles r       ON r.role_id = u.role_id
JOIN employees e   ON e.employee_id = u.employee_id
JOIN departments d ON d.department_id = e.department_id
ORDER BY r.permissions_level;
-- ==============================================================================