-- ==============================================================================
-- CORRECT PLACEHOLDER EMPLOYEE NAMES
--
-- The initial seed used invented surnames. This replaces them with first names
-- only, and rebuilds the derived username and email values so no fabricated
-- surname remains anywhere in the database.
--
-- Run with:  python3 run_sql.py ../DB/fix_employee_names.sql
--
-- If the real full names, official emails or employee codes become available,
-- edit the values below and run this file again -- it is safe to re-run, since
-- it updates existing rows rather than inserting new ones.
-- ==============================================================================

USE dmrc_internship_portal;

-- SYS-ADMIN
UPDATE employees SET full_name = 'Varun' WHERE employee_code = 'EMP-ADM-001';
UPDATE users u JOIN employees e ON e.employee_id = u.employee_id
   SET u.username = 'varun', u.email = 'varun@dmrc.org'
 WHERE e.employee_code = 'EMP-ADM-001';
UPDATE employees SET official_email = 'varun@dmrc.org' WHERE employee_code = 'EMP-ADM-001';

-- HR-APP
UPDATE employees SET full_name = 'Reena' WHERE employee_code = 'EMP-AHR-001';
UPDATE users u JOIN employees e ON e.employee_id = u.employee_id
   SET u.username = 'reena', u.email = 'reena@dmrc.org'
 WHERE e.employee_code = 'EMP-AHR-001';
UPDATE employees SET official_email = 'reena@dmrc.org' WHERE employee_code = 'EMP-AHR-001';

-- HR-OPS
UPDATE employees SET full_name = 'Dipti' WHERE employee_code = 'EMP-OHR-001';
UPDATE users u JOIN employees e ON e.employee_id = u.employee_id
   SET u.username = 'dipti', u.email = 'dipti@dmrc.org'
 WHERE e.employee_code = 'EMP-OHR-001';
UPDATE employees SET official_email = 'dipti@dmrc.org' WHERE employee_code = 'EMP-OHR-001';

-- ------------------------------------------------------------------------------
-- VERIFY -- run this afterwards to confirm the result:
--
--   SELECT r.role_name, e.full_name, e.employee_code, e.official_email, u.username
--   FROM users u
--   JOIN roles r     ON r.role_id = u.role_id
--   JOIN employees e ON e.employee_id = u.employee_id
--   ORDER BY r.permissions_level DESC;
-- ==============================================================================
